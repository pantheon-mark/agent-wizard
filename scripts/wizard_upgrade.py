#!/usr/bin/env python3
"""Wizard upgrade CLI — plan-only at v0.

Argparse-only shim; engine lives in `wizard/scripts/lib/upgrade.py` (library-first split).

Subcommands (per the foundation-versioning policy upgrade flow):
    upgrade-check          Inspect operator-project drift + available targets
    upgrade                Plan-only upgrade (requires --plan-only at v0)
    upgrade-plan           Synonym for `upgrade --plan-only`

Usage:
    wizard_upgrade.py upgrade-check [--manifest-path PATH] [--registry-path PATH] [--json]
    wizard_upgrade.py upgrade --to VERSION --plan-only [--manifest-path PATH] [--registry-path PATH] [--json]
    wizard_upgrade.py upgrade-plan --to VERSION [--manifest-path PATH] [--registry-path PATH] [--json]

Exit codes:
    0  success
    1  upgrade engine error (manifest / registry / target version / drift-class)
    2  tooling error (invalid CLI arguments; --plan-only missing at v0)
    3  reserved for future apply-path-blocked (next emission release lands)

NOTE: `wizard upgrade --to <version>` at v0 REQUIRES `--plan-only`. The apply path
lands at the next foundation-bundle emission release.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lib.upgrade import (  # noqa: E402
    BundleNotFoundError,
    OPERATOR_MANIFEST_JSON_FILENAME,
    OperatorManifestError,
    PlanOnlyRequiredError,
    RegistryError,
    UpgradeError,
    compute_upgrade_check,
    compute_upgrade_plan,
    load_operator_manifest,
    load_registry,
    render_upgrade_check,
    render_upgrade_plan,
    upgrade_check_to_dict,
    upgrade_plan_to_dict,
)


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
    if args.json:
        print(json.dumps(upgrade_plan_to_dict(plan), sort_keys=True, indent=2, ensure_ascii=False))
    else:
        print(render_upgrade_plan(plan), end="")
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    """`wizard upgrade --to VERSION --plan-only`.

    At v0: `--plan-only` is MANDATORY.
    """
    if not args.plan_only:
        msg = (
            "error: `wizard upgrade --to <version>` requires --plan-only at v0.\n"
            "       Apply path lands at the next foundation-bundle emission release.\n"
            "       Use `wizard upgrade-plan --to <version>` as a synonym, or pass --plan-only explicitly."
        )
        print(msg, file=sys.stderr)
        return 2
    return _run_upgrade_plan(args, plan_only_invoked_via_synonym=False)


def cmd_upgrade_plan(args: argparse.Namespace) -> int:
    """`wizard upgrade-plan --to VERSION` (synonym for `upgrade --to VERSION --plan-only`)."""
    return _run_upgrade_plan(args, plan_only_invoked_via_synonym=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wizard_upgrade",
        description=(
            "Foundation-bundle upgrade CLI (plan-only at v0; apply path lands at the next emission release). "
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

    upgrade_p = sub.add_parser("upgrade", help="Upgrade to a target version (plan-only at v0)")
    upgrade_p.add_argument("--to", required=True, help="Target foundation_bundle_version (operator-explicit; no --latest)")
    upgrade_p.add_argument("--plan-only", action="store_true",
                           help="REQUIRED at v0. Emits plan; performs no mutation. Apply path lands at the next emission release.")
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
