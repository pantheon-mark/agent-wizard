"""Tests for verify_fetched_against_resolution — the A+ apply-side integrity gate.

After self-update fetches + checks out the approved commit, this recomputes the content hashes
over the LOCAL (checked-out) toolkit + operator state and confirms they match what the operator
APPROVED in the immutable resolution. Any mismatch fails closed (the fetched bytes are not what
was approved -> refuse, before any apply). Fully offline: builds a real toolkit+bundle fixture.
"""

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from resolution_verify import verify_fetched_against_resolution  # noqa: E402
from update_resolution import build_update_resolution  # noqa: E402
from upgrade import compute_bundle_tree_sha256, compute_bundle_manifest_sha256  # noqa: E402


def _make_toolkit(root: Path, version: str = "v0.6.2") -> Path:
    """A minimal toolkit layout: registry/ + foundation-bundles/<v>/ with a manifest + a file.
    Returns the registry path."""
    bundle = root / "foundation-bundles" / version
    bundle.mkdir(parents=True)
    (bundle / "migration-manifest.json").write_text(
        json.dumps({"target": version}), encoding="utf-8")
    (bundle / "doc.md").write_text("hello\n", encoding="utf-8")
    entry = {
        "foundation_bundle_version": version,
        "path": f"foundation-bundles/{version}/",
        "bundle_tree_sha256": compute_bundle_tree_sha256(bundle),
        "bundle_manifest_sha256": compute_bundle_manifest_sha256(bundle),
    }
    reg = {"registry_schema_version": "v2", "bundles": [entry]}
    reg_dir = root / "registry"
    reg_dir.mkdir()
    reg_path = reg_dir / "foundation-bundles.json"
    reg_path.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")
    return reg_path


def _operator(root: Path, version: str = "v0.6.1") -> Path:
    (root / ".wizard").mkdir(parents=True)
    (root / ".wizard" / "manifest.json").write_text(
        json.dumps({"foundation_bundle_version": version}), encoding="utf-8")
    return root


def _resolution_for(reg_path: Path, operator: Path, *, commit="c" * 40):
    """Build a resolution whose expected hashes are taken from the fixture registry/bundle —
    i.e. an HONEST approved contract for this exact toolkit state."""
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    entry = reg["bundles"][0]
    return build_update_resolution(
        operator_project_dir=operator,
        registry_raw_text=reg_path.read_text(encoding="utf-8"),
        source_url="https://x/registry/foundation-bundles.json",
        source_origin_id="github:o/r", source_ref="main", entry=entry,
        from_version="v0.6.1", target_public_commit_sha=commit,
        min_engine_version="", checked_engine_version="",
        checked_at="2026-06-23T00:00:00Z")


class VerifyFetchedAgainstResolutionTest(unittest.TestCase):
    def test_matching_toolkit_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = _make_toolkit(root)
            op = _operator(root / "estate")
            res = _resolution_for(reg, op)
            result = verify_fetched_against_resolution(reg, op, res)
            self.assertTrue(result.ok, f"expected pass; failures={result.failures}")
            self.assertEqual(result.failures, [])

    def test_tampered_bundle_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = _make_toolkit(root)
            op = _operator(root / "estate")
            res = _resolution_for(reg, op)
            # tamper a bundle file AFTER the resolution was approved
            (root / "foundation-bundles" / "v0.6.2" / "doc.md").write_text("EVIL\n", encoding="utf-8")
            result = verify_fetched_against_resolution(reg, op, res)
            self.assertFalse(result.ok)
            self.assertIn("bundle_tree_sha256", " ".join(result.failures))

    def test_tampered_registry_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = _make_toolkit(root)
            op = _operator(root / "estate")
            res = _resolution_for(reg, op)
            reg.write_text(reg.read_text(encoding="utf-8") + "\n  ", encoding="utf-8")  # change bytes
            # NOTE: appending whitespace changes registry bytes but canonicalization may absorb
            # trailing whitespace; use a semantic change to be unambiguous.
            data = json.loads(reg.read_text(encoding="utf-8"))
            data["bundles"][0]["status"] = "tampered"
            reg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            result = verify_fetched_against_resolution(reg, op, res)
            self.assertFalse(result.ok)

    def test_changed_operator_manifest_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = _make_toolkit(root)
            op = _operator(root / "estate")
            res = _resolution_for(reg, op)
            # operator state changed between approve and apply
            (op / ".wizard" / "manifest.json").write_text(
                json.dumps({"foundation_bundle_version": "v0.0.0"}), encoding="utf-8")
            result = verify_fetched_against_resolution(reg, op, res)
            self.assertFalse(result.ok)
            self.assertIn("operator_manifest_sha256", " ".join(result.failures))

    def test_missing_target_entry_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = _make_toolkit(root)
            op = _operator(root / "estate")
            res = _resolution_for(reg, op)
            # drop the target from the local registry
            data = json.loads(reg.read_text(encoding="utf-8"))
            data["bundles"] = []
            reg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            result = verify_fetched_against_resolution(reg, op, res)
            self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
