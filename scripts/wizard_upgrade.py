#!/usr/bin/env python3
"""Wizard upgrade CLI.

Argparse-only shim; engine lives in `wizard/scripts/lib/upgrade.py` (library-first split).

Subcommands (per the foundation-versioning policy upgrade flow):
    upgrade-check          Inspect operator-project drift + available targets
    upgrade                Plan-only by default; --apply performs the merge-apply
    upgrade-plan           Synonym for `upgrade --plan-only`

Usage:
    wizard_upgrade.py upgrade-check [--manifest-path PATH] [--registry-path PATH] [--json]
    wizard_upgrade.py upgrade --to VERSION --plan-only [--manifest-path PATH] [--registry-path PATH] [--json]
    wizard_upgrade.py upgrade --to VERSION --apply [--ack] [--manifest-path PATH] [--registry-path PATH]
    wizard_upgrade.py upgrade-plan --to VERSION [--manifest-path PATH] [--registry-path PATH] [--json]

Exit codes:
    0  success (plan emitted; or apply completed cleanly)
    1  upgrade engine error (manifest / registry / target version / drift-class; or apply refused)
    2  tooling error (invalid CLI arguments; neither --plan-only nor --apply given)

The apply path (`--apply`) changes ONLY the foundation documents the target bundle
carries, gated on explicit operator action. There is no --latest; the operator
names the target version. Standing auto-approval is fully disabled — every apply is
operator-explicit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# The apply engine (upgrade_apply) uses sibling imports (generator / upgrade /
# replay_capsule), so lib/ must be importable as a flat directory too.
_LIB = _HERE / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from lib.upgrade import (  # noqa: E402
    BundleNotFoundError,
    MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME,
    OPERATOR_MANIFEST_JSON_FILENAME,
    OperatorManifestError,
    PlanOnlyRequiredError,
    RegistryError,
    UpgradeError,
    compute_upgrade_analysis,
    compute_upgrade_check,
    compute_upgrade_plan,
    find_bundle_entry,
    load_migration_manifest,
    load_operator_manifest,
    load_registry,
    render_upgrade_check,
    render_upgrade_plan,
    upgrade_check_to_dict,
    upgrade_plan_to_dict,
)
from lib.upgrade_apply import (  # noqa: E402
    apply_upgrade,
    compute_target_change_set,
    render_apply_result,
    UpgradeApplyError,
)


def populate_plan_analysis(
    plan,
    operator_dir: Path,
    target_version: str,
    build_repo_root: Path,
    registry: dict,
    manifest: dict,
) -> None:
    """Populate `plan.artifact_analysis` over the TARGET-CHANGE SET (read-only).

    This is the wiring the prior C1 build was missing: it computes the artifacts the
    target version adds/modifies (reusing the apply engine's render + surface
    computation, read-only via `compute_target_change_set`), loads the target
    migration-manifest's `artifact_notes` for the plain-language benefit text, and
    joins them into per-artifact analysis entries on the plan.

    Fail-soft: any error here (e.g. a legacy v1 capsule that cannot replay the
    operating layer, or a missing migration manifest) leaves `artifact_analysis = []`
    and the plan still renders — the drift report remains the complementary
    "your local changes" view. For a v2-capsule system this populates the full set."""
    try:
        change_set = compute_target_change_set(
            operator_dir, target_version, build_repo_root,
            registry=registry, manifest=manifest,
        )
    except UpgradeError:
        return
    if not change_set:
        return
    migration_manifest: dict = {}
    target_entry = find_bundle_entry(registry, target_version)
    if target_entry is not None:
        migration_json = (
            build_repo_root / target_entry.get("path", "")
            / MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME
        )
        if migration_json.exists():
            try:
                migration_manifest = load_migration_manifest(migration_json)
            except UpgradeError:
                migration_manifest = {}
    plan.artifact_analysis = compute_upgrade_analysis(change_set, migration_manifest)


def _resolve_build_repo_root(registry_path: Path) -> Path:
    """Resolve the build-repo root that the apply path renders bundles from.

    The registry lives at <root>/wizard/registry/foundation-bundles.json, so the
    root is two levels above the registry directory."""
    return registry_path.resolve().parent.parent.parent


_DEFAULT_REGISTRY_PATH = Path("wizard/registry/foundation-bundles.json")
_DEFAULT_MANIFEST_RELATIVE = Path(".wizard") / OPERATOR_MANIFEST_JSON_FILENAME


def _resolve_manifest_path(manifest_arg: str | None) -> Path:
    """Resolve --manifest-path; default = ./.wizard/manifest.json relative to cwd."""
    if manifest_arg:
        return Path(manifest_arg)
    return Path.cwd() / _DEFAULT_MANIFEST_RELATIVE


def _resolve_registry_path(registry_arg: str | None) -> Path:
    """Resolve --registry-path; default = wizard/registry/foundation-bundles.json (cwd-relative)."""
    if registry_arg:
        return Path(registry_arg)
    return Path.cwd() / _DEFAULT_REGISTRY_PATH


def cmd_upgrade_check(args: argparse.Namespace) -> int:
    """`wizard upgrade-check`."""
    manifest_path = _resolve_manifest_path(args.manifest_path)
    registry_path = _resolve_registry_path(args.registry_path)
    try:
        manifest = load_operator_manifest(manifest_path)
        registry = load_registry(registry_path)
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    operator_dir = manifest_path.parent.parent
    try:
        result = compute_upgrade_check(operator_dir, manifest, registry, registry_path=registry_path)
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(upgrade_check_to_dict(result), sort_keys=True, indent=2, ensure_ascii=False))
    else:
        print(render_upgrade_check(result), end="")
    return 0


def _run_upgrade_plan(args: argparse.Namespace, plan_only_invoked_via_synonym: bool) -> int:
    """Shared body for `upgrade --plan-only` + `upgrade-plan` synonym."""
    manifest_path = _resolve_manifest_path(args.manifest_path)
    registry_path = _resolve_registry_path(args.registry_path)
    try:
        manifest = load_operator_manifest(manifest_path)
        registry = load_registry(registry_path)
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    operator_dir = manifest_path.parent.parent
    try:
        plan = compute_upgrade_plan(operator_dir, manifest, args.to, registry, registry_path=registry_path)
    except BundleNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    # Populate the per-artifact analysis over the target-change set (read-only). This is
    # the wiring the prior C1 build omitted, which left artifact_analysis empty on every
    # real plan run. Fail-soft: leaves the analysis empty if it cannot be computed.
    populate_plan_analysis(
        plan, operator_dir, args.to,
        _resolve_build_repo_root(registry_path), registry, manifest,
    )
    if args.json:
        print(json.dumps(upgrade_plan_to_dict(plan), sort_keys=True, indent=2, ensure_ascii=False))
    else:
        print(render_upgrade_plan(plan), end="")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """`wizard upgrade --to VERSION --apply [--ack]` — the merge-apply path.

    Changes ONLY the foundation documents the target bundle carries. Operator-edited
    files are never clobbered: they are kept in place and the new version is saved
    for review. Every apply is operator-explicit (no standing auto-approval)."""
    manifest_path = _resolve_manifest_path(args.manifest_path)
    registry_path = _resolve_registry_path(args.registry_path)
    try:
        manifest = load_operator_manifest(manifest_path)
        registry = load_registry(registry_path)
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    operator_dir = manifest_path.parent.parent
    build_repo_root = _resolve_build_repo_root(registry_path)
    try:
        result = apply_upgrade(
            operator_dir, args.to, build_repo_root,
            registry=registry, registry_path=registry_path,
            manifest=manifest, manifest_path=manifest_path,
            ack=args.ack,
        )
    except UpgradeApplyError as e:
        # Refusal — no live writes. Surface the actionable message verbatim.
        print(f"upgrade refused: {e}", file=sys.stderr)
        return 1
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(render_apply_result(result), end="")
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    """`wizard upgrade --to VERSION` — plan-only by default; `--apply` mutates.

    Exactly one of `--plan-only` / `--apply` must be given (`--apply` performs the
    merge-apply; `--plan-only` previews without changing anything)."""
    if args.apply and args.plan_only:
        print("error: pass only one of --plan-only / --apply, not both.", file=sys.stderr)
        return 2
    if args.apply:
        return cmd_apply(args)
    if args.plan_only:
        return _run_upgrade_plan(args, plan_only_invoked_via_synonym=False)
    msg = (
        "error: `wizard upgrade --to <version>` requires --plan-only (preview) or --apply (apply).\n"
        "       --plan-only shows what would change without touching files.\n"
        "       --apply performs the foundation-document upgrade (operator-explicit; add --ack to\n"
        "       adopt the new version of any file you have edited under a warn-on-drift rule)."
    )
    print(msg, file=sys.stderr)
    return 2


def cmd_upgrade_plan(args: argparse.Namespace) -> int:
    """`wizard upgrade-plan --to VERSION` (synonym for `upgrade --to VERSION --plan-only`)."""
    return _run_upgrade_plan(args, plan_only_invoked_via_synonym=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wizard_upgrade",
        description=(
            "Foundation-bundle upgrade CLI (plan-only preview + operator-explicit apply). "
            "Per the foundation-versioning policy upgrade flow."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    check_p = sub.add_parser("upgrade-check", help="Inspect operator-project drift + available targets")
    check_p.add_argument("--manifest-path", default=None,
                         help="Path to operator-project `.wizard/manifest.json` (default: ./.wizard/manifest.json)")
    check_p.add_argument("--registry-path", default=None,
                         help="Path to `wizard/registry/foundation-bundles.json` (default: cwd-relative)")
    check_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    check_p.set_defaults(func=cmd_upgrade_check)

    upgrade_p = sub.add_parser("upgrade", help="Upgrade to a target version (plan-only preview or --apply)")
    upgrade_p.add_argument("--to", required=True, help="Target foundation_bundle_version (operator-explicit; no --latest)")
    upgrade_p.add_argument("--plan-only", action="store_true",
                           help="Preview the plan; performs no mutation.")
    upgrade_p.add_argument("--apply", action="store_true",
                           help="Apply the foundation-document upgrade (operator-explicit). "
                                "Operator-edited files are kept and the new version saved for review.")
    upgrade_p.add_argument("--ack", action="store_true",
                           help="With --apply: acknowledge adopting the new version of a warn-on-drift "
                                "file you have edited (your version is backed up first).")
    upgrade_p.add_argument("--manifest-path", default=None,
                           help="Path to operator-project `.wizard/manifest.json`")
    upgrade_p.add_argument("--registry-path", default=None,
                           help="Path to `wizard/registry/foundation-bundles.json`")
    upgrade_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    upgrade_p.set_defaults(func=cmd_upgrade)

    plan_p = sub.add_parser("upgrade-plan",
                            help="Synonym for `upgrade --to VERSION --plan-only` (plan-only at v0)")
    plan_p.add_argument("--to", required=True, help="Target foundation_bundle_version")
    plan_p.add_argument("--manifest-path", default=None)
    plan_p.add_argument("--registry-path", default=None)
    plan_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    plan_p.set_defaults(func=cmd_upgrade_plan)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
