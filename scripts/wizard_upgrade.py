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
    UpdateStatus,
    UpgradeError,
    classify_update_status,
    check_engine_compatibility,
    compute_upgrade_analysis,
    compute_upgrade_check,
    compute_upgrade_plan,
    find_bundle_entry,
    load_migration_manifest,
    load_operator_manifest,
    load_registry,
    render_update_status,
    render_upgrade_check,
    render_upgrade_plan,
    resolve_bundle_dir,
    resolve_toolkit_root,
    status_exit_code,
    update_outcome_to_dict,
    upgrade_check_to_dict,
    upgrade_plan_to_dict,
)
from lib.upgrade_apply import (  # noqa: E402
    apply_upgrade,
    compute_target_change_set,
    render_apply_result,
    UpgradeApplyError,
)
from lib.self_update import (  # noqa: E402
    apply_self_update,
    render_self_update_result,
    self_update_exit_code,
    verify_self_update,
)
from lib.update_source import record_last_known_good_commit  # noqa: E402


def populate_plan_analysis(
    plan,
    operator_dir: Path,
    target_version: str,
    build_repo_root: Path,
    registry: dict,
    manifest: dict,
    registry_path: Path,
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
        # Registry-relative, layout-agnostic (build-repo + public-clone). Was a fixed
        # `build_repo_root / entry["path"]` join that re-prepended the build-repo
        # `wizard/` prefix and broke in the prefix-stripped public clone (F-OR-4).
        migration_json = (
            resolve_bundle_dir(registry_path, registry, target_entry)
            / MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME
        )
        if migration_json.exists():
            try:
                migration_manifest = load_migration_manifest(migration_json)
            except UpgradeError:
                migration_manifest = {}
    plan.artifact_analysis = compute_upgrade_analysis(change_set, migration_manifest)


def _resolve_build_repo_root(registry_path: Path) -> Path:
    """Resolve the toolkit root the apply/render path resolves bundles under.

    Registry-relative + layout-agnostic (operator-reach C1', fixes F-OR-4): the
    registry ALWAYS lives at `<toolkit>/registry/foundation-bundles.json`, so the
    toolkit root is the registry file's grandparent in BOTH shipping layouts:

      * BUILD-REPO  : `<root>/wizard/registry/...` -> `<root>/wizard`
      * PUBLIC-CLONE: `<clone>/registry/...`       -> `<clone>` (the `git subtree
        --prefix=wizard` split strips the `wizard/` prefix)

    The render engine (`bundle_templates.wizard_subroot`) accepts this toolkit root
    directly: it detects that the value already contains `foundation-bundles/` and does
    not re-prepend a `wizard/` segment, so resolution is identical in both layouts. The
    canonical per-bundle directory resolution is registry-relative
    (`upgrade.resolve_bundle_dir`).

    Was `registry_path.resolve().parent.parent.parent`, which assumed the build-repo
    `wizard/` prefix and re-prepended it in the prefix-stripped public clone -> the
    public clone was un-runnable (registry-not-found / bundle-directory-missing)."""
    return resolve_toolkit_root(registry_path)


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


def _emit_outcome(outcome, args, *, detail_render: str = "") -> int:
    """Shared emit for the typed honest-status contract: --json emits the structured
    outcome (status / reason_code / fields); otherwise the operator-facing message
    (rendered ONLY from the typed status, never raw logs) plus optional detail. Returns
    the status-mapped exit code so the could-not-determine band never collapses to 0."""
    if args.json:
        print(json.dumps(update_outcome_to_dict(outcome), sort_keys=True, indent=2, ensure_ascii=False))
    else:
        print(render_update_status(outcome))
        if detail_render:
            print()
            print(detail_render, end="")
    return status_exit_code(outcome.status)


def cmd_upgrade_check(args: argparse.Namespace) -> int:
    """`wizard upgrade-check` — typed honest-status contract (C6').

    Every outcome funnels through `classify_update_status` so no failure path can
    collapse into a false "up to date": a missing/unparseable registry -> REGISTRY_INVALID;
    a check that did not complete -> COULD_NOT_CHECK; an update that exists but the local
    engine is too old to apply -> ENGINE_TOO_OLD. Distinct exit code per status."""
    manifest_path = _resolve_manifest_path(args.manifest_path)
    registry_path = _resolve_registry_path(args.registry_path)

    # Operator-manifest load failures are an operator/config error, not an
    # update-status determination — keep the legacy tooling exit code 1.
    try:
        manifest = load_operator_manifest(manifest_path)
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # Registry load failure is an update-status determination: a missing/unparseable
    # registry means "could not check", classified REGISTRY_INVALID (NOT "no updates").
    try:
        registry = load_registry(registry_path)
    except RegistryError as e:
        return _emit_outcome(classify_update_status(e), args)

    operator_dir = manifest_path.parent.parent
    try:
        result = compute_upgrade_check(operator_dir, manifest, registry, registry_path=registry_path)
    except RegistryError as e:
        return _emit_outcome(classify_update_status(e), args)
    except UpgradeError as e:
        # The check itself did not complete (e.g. a target's migration manifest could
        # not be loaded) -> COULD_NOT_CHECK, never a false "current".
        return _emit_outcome(classify_update_status(e), args)

    # Engine-compatibility gate (MF-2): if an update exists but the local engine is older
    # than the latest available target's declared min_engine_version, surface ENGINE_TOO_OLD
    # (honest STOP — refresh the tool first) rather than UPDATE_AVAILABLE.
    engine_too_old = False
    min_engine = ""
    if result.available_targets:
        # Highest available target (the check sorts ascending; take the last).
        latest_target = result.available_targets[-1].get("foundation_bundle_version", "")
        target_entry = find_bundle_entry(registry, latest_target)
        if target_entry is not None:
            compat = check_engine_compatibility(registry_path, registry, target_entry)
            if not compat.compatible:
                engine_too_old = True
                min_engine = compat.min_engine_version

    outcome = classify_update_status(
        result, engine_too_old=engine_too_old, min_engine_version=min_engine,
    )
    detail = "" if args.json else render_upgrade_check(result)
    return _emit_outcome(outcome, args, detail_render=detail)


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
        registry_path=registry_path,
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


def _resolve_toolkit_dir(toolkit_arg: str | None) -> Path:
    """Resolve the installed-toolkit directory. Default = this engine's own toolkit root
    (`scripts/`'s parent), i.e. the directory the running engine lives under. This is the
    directory the guarded self-update verifies + backs up + swaps."""
    if toolkit_arg:
        return Path(toolkit_arg)
    return _HERE.parent


def cmd_self_update(args: argparse.Namespace) -> int:
    """`wizard self-update [--check | --apply]` — the GUARDED toolkit-currency contract.

    SAFE ORDERING: the CURRENTLY-INSTALLED engine performs verify (+ backup + swap on
    --apply); the freshly-fetched code is NOT executed in this run — it runs on the
    operator's NEXT invocation. Touches ONLY the toolkit directory, never operator files.

    --check  : verify only (origin + lineage + clean tree); report; change nothing.
    --apply  : verify, back up the toolkit, swap to the verified candidate, record the
               new last-known-good commit. Fail-closed on any failed gate.
    """
    toolkit_dir = _resolve_toolkit_dir(args.toolkit_dir)
    # The operator project is where `.wizard/update-source.json` lives (the pinned source).
    operator_dir = (
        Path(args.operator_dir) if args.operator_dir else _resolve_manifest_path(None).parent.parent
    )
    candidate = args.to_commit or None

    if args.apply:
        result = apply_self_update(
            toolkit_dir, operator_dir, candidate_commit=candidate,
            record_commit_fn=lambda c: record_last_known_good_commit(operator_dir, c),
        )
    else:
        # Default + --check: verify only, never mutate.
        result = verify_self_update(toolkit_dir, operator_dir, candidate_commit=candidate)

    print(render_self_update_result(result, json_mode=args.json), end="")
    # Reuse the typed status -> exit-code mapping so a caller branches on the outcome.
    # Routed through the engine's own helper to avoid an enum-identity mismatch across
    # module import paths.
    return self_update_exit_code(result)


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

    su_p = sub.add_parser(
        "self-update",
        help="Guarded update of the installed wizard toolkit itself (verify -> backup -> swap)",
    )
    su_mode = su_p.add_mutually_exclusive_group()
    su_mode.add_argument("--check", action="store_true",
                         help="Verify only (origin + lineage + clean tree); report; change nothing. (default)")
    su_mode.add_argument("--apply", action="store_true",
                         help="Verify, back up the toolkit, swap to the verified version, and record it. "
                              "The new version is used on your NEXT session (safe ordering).")
    su_p.add_argument("--toolkit-dir", default=None,
                      help="Path to the installed wizard toolkit (default: the directory this engine runs from)")
    su_p.add_argument("--operator-dir", default=None,
                      help="Path to the operator project holding .wizard/update-source.json (default: cwd)")
    su_p.add_argument("--to-commit", default=None,
                      help="Candidate commit to update to (default: current toolkit HEAD)")
    su_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    su_p.set_defaults(func=cmd_self_update)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
