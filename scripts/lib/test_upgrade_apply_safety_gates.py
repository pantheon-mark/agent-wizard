"""Apply-path safety gates for operator-reach:

  - MF-2: apply must refuse with ENGINE_TOO_OLD (not best-effort apply) when the local
    engine is older than the target bundle's declared min_engine_version.
  - MF-4: the data-apply path must REJECT any bundle/contract entry whose resolved
    target falls within the engine's own code area (scripts/, scripts/lib/,
    wizard_upgrade.py); data bundles modify only operator-estate files, never the engine.

Both are fail-closed with NO writes. Reuses the synthetic build-repo + operator-project
fixtures from test_upgrade_apply (small, version-agnostic, divergent rosters).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upgrade import (  # noqa: E402
    load_operator_manifest,
    load_registry,
    EngineDirectoryBoundaryError,
    target_escapes_engine_dir,
)
from upgrade_apply import apply_upgrade, UpgradeApplyError  # noqa: E402

# Reuse the synthetic-bundle builders from the existing apply test module.
from test_upgrade_apply import (  # noqa: E402
    _write_build_repo,
    _build_operator_project,
)


class EngineDirectoryBoundaryUnitTest(unittest.TestCase):
    """target_escapes_engine_dir is the pure-predicate guard MF-4 enforces. It must
    flag any operator-relative target that lands in the engine's own code area, across
    divergent path shapes — not just one fixture string."""

    def test_engine_paths_are_rejected(self):
        for rel in (
            "scripts/lib/upgrade_apply.py",
            "scripts/lib/upgrade.py",
            "scripts/wizard_upgrade.py",
            "scripts/generator.py",
            "scripts/lib/section_merge.py",
            "./scripts/lib/upgrade_apply.py",
            "scripts/../scripts/lib/upgrade.py",
        ):
            with self.subTest(rel=rel):
                self.assertTrue(
                    target_escapes_engine_dir(rel),
                    f"{rel!r} targets the engine and must be flagged",
                )

    def test_operator_estate_paths_are_allowed(self):
        for rel in (
            "foundation/vision.md",
            "CLAUDE.md",
            ".claude/settings.json",
            "agents/prompts/orchestrator.md",
            "quality/rules_library.md",
            ".wizard/UPGRADING.md",
            "scripts_notes/readme.md",   # NOT the engine 'scripts/' dir
            "my_scripts/run.py",
        ):
            with self.subTest(rel=rel):
                self.assertFalse(
                    target_escapes_engine_dir(rel),
                    f"{rel!r} is an operator-estate file and must be allowed",
                )

    def test_parent_traversal_out_of_project_is_rejected(self):
        for rel in ("../scripts/lib/upgrade.py", "../../wizard/scripts/wizard_upgrade.py"):
            with self.subTest(rel=rel):
                self.assertTrue(target_escapes_engine_dir(rel))


class ApplyEngineDirectoryBoundaryTest(unittest.TestCase):
    """A crafted bundle whose contract adds an entry targeting an engine file must be
    refused by apply with NO writes (MF-4)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_apply_refuses_contract_entry_targeting_engine_file(self):
        build_root, registry_path = _write_build_repo(self.tmp)
        # Craft a system-artifacts.json in the TARGET bundle with a malicious entry that
        # would write into the engine's own code area.
        target_bundle = build_root / "wizard" / "foundation-bundles" / "v0.5.0"
        (target_bundle / "templates" / "scripts" / "lib").mkdir(parents=True, exist_ok=True)
        (target_bundle / "templates" / "scripts" / "lib" / "upgrade_apply.py").write_text(
            "print('pwned')\n", encoding="utf-8")
        contract = {
            "artifacts": [
                {
                    "relpath": "scripts/lib/upgrade_apply.py",
                    "delivery": "wizard",
                    "render_kind": "copy",
                    "merge_strategy": "warn_on_drift",
                    "template_path": "templates/scripts/lib/upgrade_apply.py",
                    "mode": "0644",
                },
            ]
        }
        (target_bundle / "system-artifacts.json").write_text(
            json.dumps(contract, indent=2), encoding="utf-8")

        proj, manifest_path, _ = _build_operator_project(self.tmp, build_root, roster="A")
        # Capture a pre-apply snapshot of the engine file location inside the project to
        # confirm nothing was written there.
        engine_target = proj / "scripts" / "lib" / "upgrade_apply.py"

        manifest = load_operator_manifest(manifest_path)
        registry = load_registry(registry_path)
        with self.assertRaises((UpgradeApplyError, EngineDirectoryBoundaryError)) as ctx:
            apply_upgrade(
                proj, "v0.5.0", build_root,
                registry=registry, registry_path=registry_path,
                manifest=manifest, manifest_path=manifest_path,
            )
        self.assertIn("engine", str(ctx.exception).lower())
        self.assertFalse(engine_target.exists(), "no engine file may be written")


class ApplyEngineCompatGateTest(unittest.TestCase):
    """MF-2 at apply: a target bundle whose manifest.json declares a min_engine_version
    NEWER than the installed engine must refuse the apply (ENGINE_TOO_OLD), not
    best-effort apply. With NO writes."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _write_bundle_manifest(self, build_root, version, *, min_engine):
        bundle = build_root / "wizard" / "foundation-bundles" / version
        bundle.mkdir(parents=True, exist_ok=True)
        bundle.joinpath("manifest.json").write_text(json.dumps({
            "foundation_bundle_version": version,
            "bundle_manifest_schema_version": "v2",
            "min_engine_version": min_engine,
        }, indent=2), encoding="utf-8")

    def test_apply_refuses_when_engine_too_old(self):
        build_root, registry_path = _write_build_repo(self.tmp)
        # Stamp the target bundle with a min_engine_version no installed engine satisfies.
        self._write_bundle_manifest(build_root, "v0.5.0", min_engine="v99.0.0")
        proj, manifest_path, _ = _build_operator_project(self.tmp, build_root, roster="A")

        # Record the pre-apply bytes of a managed doc to prove no write happened.
        vision = proj / "vision.md"
        before = vision.read_text(encoding="utf-8")

        manifest = load_operator_manifest(manifest_path)
        registry = load_registry(registry_path)
        with self.assertRaises(UpgradeApplyError) as ctx:
            apply_upgrade(
                proj, "v0.5.0", build_root,
                registry=registry, registry_path=registry_path,
                manifest=manifest, manifest_path=manifest_path,
            )
        msg = str(ctx.exception).lower()
        self.assertTrue("refresh" in msg or "older" in msg or "too old" in msg, msg)
        self.assertEqual(vision.read_text(encoding="utf-8"), before, "no files may change")

    def test_apply_proceeds_when_engine_compatible(self):
        build_root, registry_path = _write_build_repo(self.tmp)
        # A satisfiable min_engine_version (installed engine is v1.0.0).
        self._write_bundle_manifest(build_root, "v0.5.0", min_engine="v1.0.0")
        proj, manifest_path, _ = _build_operator_project(self.tmp, build_root, roster="A")
        manifest = load_operator_manifest(manifest_path)
        registry = load_registry(registry_path)
        # Should NOT raise on the engine-compat gate (may still apply/partial normally).
        result = apply_upgrade(
            proj, "v0.5.0", build_root,
            registry=registry, registry_path=registry_path,
            manifest=manifest, manifest_path=manifest_path,
        )
        self.assertIn(result.classification, ("applied", "partial"))


if __name__ == "__main__":
    unittest.main()
