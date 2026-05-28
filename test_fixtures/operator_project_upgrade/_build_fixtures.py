#!/usr/bin/env python3
"""Build the operator-project-upgrade fixture corpus.

Deterministic; idempotent (overwrites). Run once at fixture authoring time; tests in
`tools/test_wizard_upgrade.py` reference the committed fixtures by path.

Fixtures:
    clean_v0.3.0/             clean operator project pinned at v0.3.0, no drift
    drift_one_file_v0.3.0/    same as clean but with one foundation file hash-modified
    pinned_at_older/          hypothetical operator at v0.2.0; v0.3.0 is upgrade target
    excluded_when_permits/    has upgrade-policy.yaml with permissive excluded_when (proves the v0
                              CLI ignores standing-approval predicates and always requires explicit
                              operator approval until operator-authority-profile generation resolves)
    missing_manifest/         no .wizard/manifest.json (negative fail-closed)
    malformed_manifest/       .wizard/manifest.json is malformed (negative fail-closed)
    fixture-registry.json     synthetic registry covering v0.2.0 + v0.3.0
"""

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIZARD_SCRIPTS = _HERE.parent.parent / "scripts"
if str(_WIZARD_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_WIZARD_SCRIPTS))

from lib.upgrade import sha256_file  # noqa: E402

FIXTURES_ROOT = _HERE
MANAGED_FILES_CONTENT = {
    "foundation/vision.md": "# Vision\n\nFixture vision content for upgrade tests.\n",
    "foundation/prd.md": "# PRD\n\nFixture prd content.\n",
    "foundation/approach.md": "# Approach\n\nFixture approach content.\n",
    "foundation/execution_plan.md": "# Execution Plan\n\nFixture execution plan content.\n",
    "foundation/technical_architecture.md": "# Technical Architecture\n\nFixture tech-arch content.\n",
    "foundation/test_cases.md": "# Test Cases\n\nFixture test cases content.\n",
    "foundation/audit_framework.md": "# Audit Framework\n\nFixture audit framework content.\n",
}
MANAGED_FILES_META = {
    "foundation/vision.md": {"managed_by": "shared", "local_modifications": "expected", "merge_strategy": "three_way"},
    "foundation/prd.md": {"managed_by": "operator", "local_modifications": "expected", "merge_strategy": "operator_review"},
    "foundation/approach.md": {"managed_by": "shared", "local_modifications": "allowed", "merge_strategy": "three_way"},
    "foundation/execution_plan.md": {"managed_by": "operator", "local_modifications": "expected", "merge_strategy": "operator_review"},
    "foundation/technical_architecture.md": {"managed_by": "shared", "local_modifications": "allowed", "merge_strategy": "three_way"},
    "foundation/test_cases.md": {"managed_by": "operator", "local_modifications": "expected", "merge_strategy": "operator_review"},
    "foundation/audit_framework.md": {"managed_by": "wizard", "local_modifications": "not_recommended", "merge_strategy": "warn_on_drift"},
}


def _write_file(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _build_foundation_files(root: Path) -> None:
    for rel, content in MANAGED_FILES_CONTENT.items():
        _write_file(root / rel, content)


def _compute_manifest_managed_files(root: Path) -> dict:
    result = {}
    for rel, meta in MANAGED_FILES_META.items():
        abs_path = root / rel
        h = sha256_file(abs_path)
        result[rel] = {
            "managed": "true",
            "base_hash": f"sha256:{h}",
            "current_hash_last_seen": f"sha256:{h}",
            "managed_by": meta["managed_by"],
            "local_modifications": meta["local_modifications"],
            "merge_strategy": meta["merge_strategy"],
        }
    return result


def _emit_manifest_json(out_path: Path, version: str, files: dict) -> None:
    payload = {
        "foundation_bundle_version": version,
        "foundation_schema_version": "v0.2",
        "agent_contract_version": "v0-pre-rebuild",
        "release_date": "2026-05-21",
        "source_commit": "fixture-only",
        "status": "fixture",
        "managed_files": files,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_clean(root: Path, version: str = "v0.3.0") -> None:
    _build_foundation_files(root)
    files = _compute_manifest_managed_files(root)
    _emit_manifest_json(root / ".wizard" / "manifest.json", version, files)


def build_drift_one_file(root: Path) -> None:
    build_clean(root, version="v0.3.0")
    # NOW modify one file AFTER manifest is committed → creates drift
    drifted = root / "foundation" / "vision.md"
    drifted.write_text(drifted.read_text(encoding="utf-8") + "\n## Local edit\n\nOperator-added section.\n", encoding="utf-8")


def build_pinned_at_older(root: Path) -> None:
    """Operator pinned at v0.2.0; v0.3.0 is in fixture-registry as upgrade target."""
    build_clean(root, version="v0.2.0")


def build_excluded_when_permits(root: Path) -> None:
    """Operator at v0.3.0 with upgrade-policy.yaml that WOULD permit standing approval.

    CLI must still report unavailable_idq_050_open + require explicit operator approval
    at v0.
    """
    build_clean(root, version="v0.3.0")
    upgrade_policy = root / ".wizard" / "upgrade-policy.yaml"
    upgrade_policy.parent.mkdir(parents=True, exist_ok=True)
    upgrade_policy.write_text(
        "# Fixture upgrade-policy.yaml — would permit standing approval if operator-authority-profile generation were resolved.\n"
        "# At v0 the CLI MUST ignore this and report unavailable_idq_050_open.\n"
        "standing_approval:\n"
        "  enabled: true\n"
        "  max_target: patch-mechanical\n"
        "  requires_clean_git: true\n"
        "  requires_backup_ready: false\n"
        "  requires_preflight_pass: true\n"
        "  excluded_when:\n"
        "    trust_posture: low\n"
        "    desired_autonomy: low\n"
        "    domain_risk: high\n"
        "    regulated_data: true\n",
        encoding="utf-8",
    )


def build_missing_manifest(root: Path) -> None:
    _build_foundation_files(root)
    # NO .wizard/manifest.json on purpose → fail-closed test


def build_malformed_manifest(root: Path) -> None:
    _build_foundation_files(root)
    manifest = root / ".wizard" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("this is { not : valid_json: at all\n", encoding="utf-8")


def emit_fixture_registry() -> None:
    """Emit synthetic registry covering v0.2.0 (hypothetical older) + v0.3.0 (current real)."""
    registry = {
        "schema_version": "v1",
        "bundles": [
            {
                "foundation_bundle_version": "v0.2.0",
                "path": "wizard/test_fixtures/operator_project_upgrade/_synthetic_bundles/v0.2.0/",
                "release_date": "2026-05-01",
                "source_commit": "fixture-only",
                "manifest": "wizard/test_fixtures/operator_project_upgrade/_synthetic_bundles/v0.2.0/manifest.yaml",
                "status": "fixture-hypothetical",
            },
            {
                "foundation_bundle_version": "v0.3.0",
                "path": "wizard/foundation-bundles/v0.3.0/",
                "release_date": "2026-05-21",
                "source_commit": "15757c5",
                "manifest": "wizard/foundation-bundles/v0.3.0/manifest.yaml",
                "status": "prerelease",
            },
        ],
    }
    (FIXTURES_ROOT / "fixture-registry.json").write_text(
        json.dumps(registry, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    FIXTURES_ROOT.mkdir(parents=True, exist_ok=True)
    build_clean(FIXTURES_ROOT / "clean_v0.3.0")
    build_drift_one_file(FIXTURES_ROOT / "drift_one_file_v0.3.0")
    build_pinned_at_older(FIXTURES_ROOT / "pinned_at_older")
    build_excluded_when_permits(FIXTURES_ROOT / "excluded_when_permits")
    build_missing_manifest(FIXTURES_ROOT / "missing_manifest")
    build_malformed_manifest(FIXTURES_ROOT / "malformed_manifest")
    emit_fixture_registry()
    print(f"fixtures emitted under {FIXTURES_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
