"""Tests for the immutable UpdateResolution (the operator-approved upgrade contract).

The resolution captures EXACTLY what the operator approved at check time so that self-update
(later, in a separate invocation) can verify the fetched toolkit+bundle == approved before
applying. It binds: the fetched registry bytes (registry_sha256), the target entry
(target_entry_sha256), the EXPECTED bundle hashes (copied from the entry, declared at build
time), the exact public commit (target_public_commit_sha, Option A+), the operator's manifest
at approve time, and the engine-version envelope. All hashing is canonicalized so a remote HTTP
body and a later git checkout of identical content compare equal.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from update_resolution import (  # noqa: E402
    UPDATE_RESOLUTION_REL,
    UPDATE_RESOLUTION_SCHEMA_VERSION,
    UpdateResolution,
    UpdateResolutionError,
    build_update_resolution,
    load_update_resolution,
    write_update_resolution,
    registry_text_sha256,
)
from upgrade import sha256_bytes  # noqa: E402

_ENTRY = {
    "foundation_bundle_version": "v0.6.2",
    "path": "foundation-bundles/v0.6.2/",
    "manifest": "foundation-bundles/v0.6.2/manifest.yaml",
    "status": "prerelease",
    "changelog": "what's new",
    "bundle_tree_sha256": "sha256:tree-expected",
    "bundle_manifest_sha256": "sha256:manifest-expected",
}


def _operator_project(tmp: Path, version: str = "v0.6.1") -> Path:
    (tmp / ".wizard").mkdir(parents=True, exist_ok=True)
    (tmp / ".wizard" / "manifest.json").write_text(
        json.dumps({"foundation_bundle_version": version}), encoding="utf-8")
    return tmp


def _build(tmp: Path, *, registry_raw="{...raw registry bytes...}", entry=None) -> UpdateResolution:
    return build_update_resolution(
        operator_project_dir=tmp,
        registry_raw_text=registry_raw,
        source_url="https://raw.githubusercontent.com/o/r/main/registry/foundation-bundles.json",
        source_origin_id="github:o/r",
        source_ref="main",
        entry=entry if entry is not None else _ENTRY,
        from_version="v0.6.1",
        target_public_commit_sha="abc123def456",
        min_engine_version="v0.5.0",
        checked_engine_version="v0.6.0",
        checked_at="2026-06-23T00:00:00Z",
    )


class BuildResolutionTest(unittest.TestCase):
    def test_binds_expected_fields_from_entry_and_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            r = _build(_operator_project(Path(td)))
            self.assertEqual(r.resolution_schema_version, UPDATE_RESOLUTION_SCHEMA_VERSION)
            self.assertEqual(r.target_version, "v0.6.2")
            self.assertEqual(r.from_version, "v0.6.1")
            self.assertEqual(r.target_public_commit_sha, "abc123def456")
            # bundle hashes are COPIED from the declared entry (expected values)
            self.assertEqual(r.target_bundle_tree_sha256, "sha256:tree-expected")
            self.assertEqual(r.target_bundle_manifest_sha256, "sha256:manifest-expected")
            # registry + entry + operator-manifest hashes are computed
            self.assertEqual(r.registry_sha256, registry_text_sha256("{...raw registry bytes...}"))
            self.assertTrue(r.target_entry_sha256.startswith("sha256:"))
            self.assertTrue(r.operator_manifest_sha256.startswith("sha256:"))

    def test_registry_hash_is_canonicalized_crlf_equals_lf(self):
        """A remote HTTP body and a later git checkout of identical content differ only by line
        endings (Windows autocrlf); canonicalized hashing makes them compare EQUAL — else
        self-update would fail closed on a benign transport/checkout difference."""
        lf = '{"bundles":[]}\n'
        crlf = '{"bundles":[]}\r\n'
        self.assertEqual(registry_text_sha256(lf), registry_text_sha256(crlf))

    def test_entry_hash_changes_when_entry_changes(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _operator_project(Path(td))
            base = _build(proj)
            mutated = dict(_ENTRY, status="released")
            other = _build(proj, entry=mutated)
            self.assertNotEqual(base.target_entry_sha256, other.target_entry_sha256)

    def test_operator_manifest_hash_changes_with_manifest(self):
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            a = _build(_operator_project(Path(td1), version="v0.6.1"))
            b = _build(_operator_project(Path(td2), version="v0.5.0"))
            self.assertNotEqual(a.operator_manifest_sha256, b.operator_manifest_sha256)

    def test_missing_operator_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(UpdateResolutionError):
                _build(Path(td))  # no .wizard/manifest.json


class SerializeRoundTripTest(unittest.TestCase):
    def test_to_json_is_canonical_and_round_trips(self):
        with tempfile.TemporaryDirectory() as td:
            r = _build(_operator_project(Path(td)))
            text = r.to_json()
            self.assertTrue(text.endswith("\n"))
            # canonical: sorted keys, stable
            self.assertEqual(text, r.to_json())
            parsed = json.loads(text)
            self.assertEqual(list(parsed.keys()), sorted(parsed.keys()))
            self.assertEqual(UpdateResolution.from_dict(parsed), r)

    def test_write_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _operator_project(Path(td))
            r = _build(proj)
            dest = write_update_resolution(proj, r)
            self.assertEqual(dest, proj / UPDATE_RESOLUTION_REL)
            self.assertEqual(load_update_resolution(proj), r)


class LoadFailClosedTest(unittest.TestCase):
    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(UpdateResolutionError):
                load_update_resolution(Path(td))

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / UPDATE_RESOLUTION_REL
            p.parent.mkdir(parents=True)
            p.write_text("not json {{{", encoding="utf-8")
            with self.assertRaises(UpdateResolutionError):
                load_update_resolution(Path(td))

    def test_wrong_schema_version_raises(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _operator_project(Path(td))
            r = _build(proj)
            d = r.to_dict()
            d["resolution_schema_version"] = "update-resolution-v999"
            p = proj / UPDATE_RESOLUTION_REL
            p.write_text(json.dumps(d), encoding="utf-8")
            with self.assertRaises(UpdateResolutionError):
                load_update_resolution(proj)

    def test_missing_required_field_raises(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _operator_project(Path(td))
            d = _build(proj).to_dict()
            del d["target_bundle_tree_sha256"]
            p = proj / UPDATE_RESOLUTION_REL
            p.write_text(json.dumps(d), encoding="utf-8")
            with self.assertRaises(UpdateResolutionError):
                load_update_resolution(proj)


if __name__ == "__main__":
    unittest.main()
