"""Tests for the MF-2 engine-compatibility gate.

Before plan/apply, the engine compares its own installed semantic `ENGINE_VERSION`
against the target bundle's declared `min_engine_version`:

  - installed >= min_engine_version          -> compatible (proceed)
  - installed <  min_engine_version          -> ENGINE_TOO_OLD, STOP (do NOT best-effort apply)
  - NEW-schema bundle MISSING min_engine_version -> FAIL CLOSED (do not assume compatible)
  - LEGACY bundle (no bundle_manifest_schema_version) -> compatible (gate applies prospectively)

Anti-overfit: the version comparison is exercised across divergent (older / equal /
newer / patch-only / major-jump) min_engine values, not one fixture, and the
missing-metadata fail-closed is asserted for the NEW-schema case while a legacy bundle
without the field still passes.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upgrade import (  # noqa: E402
    ENGINE_VERSION,
    BUNDLE_MANIFEST_SCHEMA_ENGINE_COMPAT,
    check_engine_compatibility,
    load_registry,
    find_bundle_entry,
)


_VERSION = "v0.9.0"


def _write_toolkit(td: Path, *, manifest_obj, entry_path="foundation-bundles/v0.9.0/"):
    """Create a public-clone-layout toolkit with a registry + one bundle whose
    manifest.json is `manifest_obj`. Returns (registry_path, registry, entry)."""
    toolkit = td
    registry_path = toolkit / "registry" / "foundation-bundles.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps({
        "schema_version": "v2",
        "registry_schema_version": "v2",
        "bundles": [{
            "foundation_bundle_version": _VERSION,
            "path": entry_path,
            "status": "prerelease",
        }],
    }, indent=2), encoding="utf-8")
    bundle_dir = toolkit / "foundation-bundles" / _VERSION
    bundle_dir.mkdir(parents=True, exist_ok=True)
    if manifest_obj is not None:
        bundle_dir.joinpath("manifest.json").write_text(
            json.dumps(manifest_obj, indent=2), encoding="utf-8")
    registry = load_registry(registry_path)
    entry = find_bundle_entry(registry, _VERSION)
    return registry_path, registry, entry


def _new_schema_manifest(min_engine):
    m = {
        "foundation_bundle_version": _VERSION,
        "bundle_manifest_schema_version": BUNDLE_MANIFEST_SCHEMA_ENGINE_COMPAT,
    }
    if min_engine is not None:
        m["min_engine_version"] = min_engine
    return m


class EngineCompatCompareTest(unittest.TestCase):
    def test_compatible_when_installed_meets_or_exceeds(self):
        # ENGINE_VERSION is v1.0.0 in the engine. Targets requiring <= it are compatible.
        for min_engine in ("v0.1.0", "v1.0.0", ENGINE_VERSION):
            with self.subTest(min_engine=min_engine):
                with tempfile.TemporaryDirectory() as td:
                    rp, reg, entry = _write_toolkit(
                        Path(td), manifest_obj=_new_schema_manifest(min_engine))
                    compat = check_engine_compatibility(rp, reg, entry)
                    self.assertTrue(compat.compatible, f"min={min_engine}")

    def test_incompatible_when_installed_older(self):
        # A target requiring a NEWER engine than installed -> too old.
        for min_engine in ("v1.1.0", "v2.0.0", "v1.0.1"):
            with self.subTest(min_engine=min_engine):
                with tempfile.TemporaryDirectory() as td:
                    rp, reg, entry = _write_toolkit(
                        Path(td), manifest_obj=_new_schema_manifest(min_engine))
                    compat = check_engine_compatibility(rp, reg, entry)
                    self.assertFalse(compat.compatible, f"min={min_engine}")
                    self.assertEqual(compat.min_engine_version, min_engine)
                    self.assertEqual(compat.installed_engine_version, ENGINE_VERSION)


class EngineCompatFailClosedTest(unittest.TestCase):
    def test_new_schema_missing_min_engine_fails_closed(self):
        """A NEW-schema bundle that omits min_engine_version must be treated as
        INCOMPATIBLE (fail closed), never assumed compatible."""
        with tempfile.TemporaryDirectory() as td:
            rp, reg, entry = _write_toolkit(
                Path(td), manifest_obj=_new_schema_manifest(None))
            compat = check_engine_compatibility(rp, reg, entry)
            self.assertFalse(compat.compatible)
            self.assertIn("min_engine_version", (compat.reason or "").lower())

    def test_legacy_bundle_without_schema_version_is_compatible(self):
        """A legacy bundle (no bundle_manifest_schema_version) predates the gate; it is
        NOT subject to the engine-compat requirement (applies prospectively)."""
        with tempfile.TemporaryDirectory() as td:
            rp, reg, entry = _write_toolkit(
                Path(td),
                manifest_obj={"foundation_bundle_version": _VERSION})  # no schema version, no min_engine
            compat = check_engine_compatibility(rp, reg, entry)
            self.assertTrue(compat.compatible)

    def test_unparseable_min_engine_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            rp, reg, entry = _write_toolkit(
                Path(td), manifest_obj=_new_schema_manifest("not-a-version"))
            compat = check_engine_compatibility(rp, reg, entry)
            self.assertFalse(compat.compatible)

    def test_absent_manifest_is_legacy_exempt(self):
        """No manifest.json at all -> a legacy / foundation-only bundle (the new-schema
        operating-layer bundles always ship one). Exempt from the gate (compatible);
        the fail-closed case is a NEW-schema manifest MISSING the min_engine field."""
        with tempfile.TemporaryDirectory() as td:
            rp, reg, entry = _write_toolkit(Path(td), manifest_obj=None)
            compat = check_engine_compatibility(rp, reg, entry)
            self.assertTrue(compat.compatible)


class RealBundleEngineCompatTest(unittest.TestCase):
    """The real shipped v0.6.1 bundle declares min_engine_version and is compatible with
    the installed engine; the legacy v0.6.0 bundle (no schema version) is compatible."""

    def test_real_v061_declares_min_engine_and_is_compatible(self):
        repo_root = Path(__file__).resolve().parents[3]
        registry_path = repo_root / "wizard" / "registry" / "foundation-bundles.json"
        registry = load_registry(registry_path)
        entry = find_bundle_entry(registry, "v0.6.1")
        self.assertIsNotNone(entry)
        compat = check_engine_compatibility(registry_path, registry, entry)
        self.assertTrue(compat.compatible, compat.reason)
        self.assertTrue(compat.min_engine_version, "v0.6.1 must declare a min_engine_version")

    def test_real_v060_legacy_is_compatible(self):
        repo_root = Path(__file__).resolve().parents[3]
        registry_path = repo_root / "wizard" / "registry" / "foundation-bundles.json"
        registry = load_registry(registry_path)
        entry = find_bundle_entry(registry, "v0.6.0")
        self.assertIsNotNone(entry)
        compat = check_engine_compatibility(registry_path, registry, entry)
        self.assertTrue(compat.compatible)


if __name__ == "__main__":
    unittest.main()
