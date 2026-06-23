"""Integration tests for apply_self_update_with_resolution (Option A+ self-update transaction).

Uses a REAL local git upstream that CONTAINS a registry + bundle at the target commit (no
network). Proves the full transaction: fetch -> verify -> backup -> checkout exact commit ->
HEAD==approved -> content gate -> pin -> applied; and that a content mismatch or a pin failure
auto-rolls-back to the previous commit and NEVER reports applied.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from self_update import apply_self_update_with_resolution  # noqa: E402
from update_source import UPDATE_SOURCE_REL, CANONICAL_HTTPS_URL, render_update_source_json  # noqa: E402
from update_resolution import (  # noqa: E402
    UPDATE_RESOLUTION_REL, build_update_resolution, write_update_resolution, load_update_resolution,
)
from upgrade import compute_bundle_tree_sha256, compute_bundle_manifest_sha256  # noqa: E402


def _run(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True)


def _git(cwd, *args):
    return _run(cwd, "git", *args)


def _head(repo):
    return _run(repo, "git", "rev-parse", "HEAD").stdout.strip()


class ApplyWithResolutionBase(unittest.TestCase):
    VERSION = "v0.6.2"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

        # --- upstream: base commit, then a commit that ADDS a registry + bundle (= target) ---
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        _git(self.upstream, "init", "-q")
        _git(self.upstream, "config", "user.email", "t@t.t")
        _git(self.upstream, "config", "user.name", "t")
        _git(self.upstream, "checkout", "-q", "-b", "main")
        (self.upstream / "README.md").write_text("base\n", encoding="utf-8")
        _git(self.upstream, "add", "-A")
        _git(self.upstream, "commit", "-q", "-m", "base")
        self.base_commit = _head(self.upstream)

        bundle = self.upstream / "foundation-bundles" / self.VERSION
        bundle.mkdir(parents=True)
        (bundle / "migration-manifest.json").write_text(json.dumps({"target": self.VERSION}), encoding="utf-8")
        (bundle / "doc.md").write_text("hello world\n", encoding="utf-8")
        entry = {
            "foundation_bundle_version": self.VERSION,
            "path": f"foundation-bundles/{self.VERSION}/",
            "bundle_tree_sha256": compute_bundle_tree_sha256(bundle),
            "bundle_manifest_sha256": compute_bundle_manifest_sha256(bundle),
        }
        reg_dir = self.upstream / "registry"
        reg_dir.mkdir()
        (reg_dir / "foundation-bundles.json").write_text(
            json.dumps({"registry_schema_version": "v2", "bundles": [entry]}, indent=2) + "\n",
            encoding="utf-8")
        _git(self.upstream, "add", "-A")
        _git(self.upstream, "commit", "-q", "-m", "target")
        self.target_commit = _head(self.upstream)

        # --- toolkit: clone, origin = CANONICAL (verify compares to it), local remote = upstream,
        #     checked out at BASE so the update is "available". ---
        self.toolkit = self.root / "agent-wizard"
        _git(self.root, "clone", "-q", str(self.upstream), str(self.toolkit))
        _git(self.toolkit, "config", "user.email", "t@t.t")
        _git(self.toolkit, "config", "user.name", "t")
        _git(self.toolkit, "remote", "add", "local", str(self.upstream))
        _git(self.toolkit, "remote", "set-url", "origin", CANONICAL_HTTPS_URL)
        _git(self.toolkit, "checkout", "-q", self.base_commit)

        # --- operator: pin (last_known_good = base) + manifest ---
        self.operator = self.root / "estate"
        (self.operator / ".wizard").mkdir(parents=True)
        (self.operator / UPDATE_SOURCE_REL).write_text(
            render_update_source_json(last_known_good_commit=self.base_commit), encoding="utf-8")
        (self.operator / ".wizard" / "manifest.json").write_text(
            json.dumps({"foundation_bundle_version": "v0.6.1"}), encoding="utf-8")

        # --- the approved resolution (built from the target registry/bundle) ---
        target_reg_text = (reg_dir / "foundation-bundles.json").read_text(encoding="utf-8")
        self._resolution = build_update_resolution(
            operator_project_dir=self.operator,
            registry_raw_text=target_reg_text,
            source_url="https://x/registry/foundation-bundles.json",
            source_origin_id="github:pantheon-mark/agent-wizard",
            source_ref="main", entry=entry, from_version="v0.6.1",
            target_public_commit_sha=self.target_commit,
            min_engine_version="", checked_engine_version="",
            checked_at="2026-06-23T00:00:00Z")

    def tearDown(self):
        self._tmp.cleanup()

    def _write_resolution(self, **overrides):
        d = self._resolution.to_dict()
        d.update(overrides)
        (self.operator / UPDATE_RESOLUTION_REL).write_text(
            json.dumps(d, indent=2) + "\n", encoding="utf-8")


class HappyPathTest(ApplyWithResolutionBase):
    def test_applies_and_pins(self):
        write_update_resolution(self.operator, self._resolution)
        res = apply_self_update_with_resolution(self.toolkit, self.operator, fetch_remote="local")
        self.assertTrue(res.applied, f"expected applied; {res.reason_code}: {res.message}")
        self.assertEqual(_head(self.toolkit), self.target_commit)
        # pin recorded the new last-known-good
        src = json.loads((self.operator / UPDATE_SOURCE_REL).read_text(encoding="utf-8"))
        self.assertEqual(src["last_known_good_commit"], self.target_commit)


class ContentMismatchRollbackTest(ApplyWithResolutionBase):
    def test_tampered_expected_hash_rolls_back_not_applied(self):
        # operator approved a DIFFERENT bundle hash than what's actually at the target commit
        self._write_resolution(target_bundle_tree_sha256="sha256:" + "0" * 64)
        res = apply_self_update_with_resolution(self.toolkit, self.operator, fetch_remote="local")
        self.assertFalse(res.applied)
        self.assertEqual(res.reason_code, "resolution_mismatch")
        self.assertEqual(_head(self.toolkit), self.base_commit, "must roll back to the previous commit")


class PinFailureRollbackTest(ApplyWithResolutionBase):
    def test_pin_failure_rolls_back_and_not_applied(self):
        write_update_resolution(self.operator, self._resolution)

        def _boom(_commit):
            raise RuntimeError("simulated pin-write failure")

        res = apply_self_update_with_resolution(
            self.toolkit, self.operator, fetch_remote="local", record_commit_fn=_boom)
        self.assertFalse(res.applied, "pin failure must NOT report applied")
        self.assertEqual(res.reason_code, "pin_write_failed")
        self.assertEqual(_head(self.toolkit), self.base_commit, "must auto-roll-back on pin failure")


class NoResolutionTest(ApplyWithResolutionBase):
    def test_no_approved_resolution_refuses(self):
        # no .wizard/update-resolution.json written
        res = apply_self_update_with_resolution(self.toolkit, self.operator, fetch_remote="local")
        self.assertFalse(res.applied)
        self.assertEqual(res.reason_code, "no_approved_resolution")
        self.assertEqual(_head(self.toolkit), self.base_commit)


if __name__ == "__main__":
    unittest.main()
