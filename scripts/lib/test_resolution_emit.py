"""Tests for emit_update_resolution_for_target — the check-side orchestration that, when an
update is available, resolves the EXACT public commit, fetches the registry AT that commit, and
writes the immutable approved-resolution the operator will approve + self-update will verify.

git (commit resolution) and the network (commit-pinned fetch) are injected, so no test touches
either. Fail-closed: any unresolved step returns None (and writes nothing) so the check renders
a could-not-determine status rather than a partial/false contract.
"""

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from resolution_emit import emit_update_resolution_for_target  # noqa: E402
from update_resolution import UPDATE_RESOLUTION_REL, load_update_resolution  # noqa: E402
from update_source import emit_update_source  # noqa: E402

_ENTRY = {
    "foundation_bundle_version": "v0.6.2",
    "path": "foundation-bundles/v0.6.2/",
    "bundle_tree_sha256": "sha256:tree-x",
    "bundle_manifest_sha256": "sha256:manifest-x",
}
_REGISTRY = json.dumps({"registry_schema_version": "v2", "bundles": [_ENTRY]})
_SHA = "c" * 40


def _project(tmp: Path, version="v0.6.1") -> Path:
    emit_update_source(tmp)  # .wizard/update-source.json (pantheon-mark/agent-wizard)
    (tmp / ".wizard" / "manifest.json").write_text(
        json.dumps({"foundation_bundle_version": version}), encoding="utf-8")
    return tmp


def _emit(proj, **over):
    kw = dict(
        from_version="v0.6.1", checked_at="2026-06-23T00:00:00Z",
        commit_resolver=lambda *a, **k: _SHA,
        fetcher=lambda url, t: _REGISTRY,
    )
    kw.update(over)
    return emit_update_resolution_for_target(proj, proj, "v0.6.2", **kw)


class EmitResolutionTest(unittest.TestCase):
    def test_emits_and_writes_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project(Path(td))
            r = _emit(proj)
            self.assertIsNotNone(r)
            self.assertEqual(r.target_version, "v0.6.2")
            self.assertEqual(r.from_version, "v0.6.1")
            self.assertEqual(r.target_public_commit_sha, _SHA)
            self.assertEqual(r.target_bundle_tree_sha256, "sha256:tree-x")
            self.assertEqual(r.source_origin_id, "github:pantheon-mark/agent-wizard")
            # written to disk + reloadable
            self.assertTrue((proj / UPDATE_RESOLUTION_REL).is_file())
            self.assertEqual(load_update_resolution(proj), r)

    def test_commit_unresolved_returns_none_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project(Path(td))
            r = _emit(proj, commit_resolver=lambda *a, **k: None)
            self.assertIsNone(r)
            self.assertFalse((proj / UPDATE_RESOLUTION_REL).exists())

    def test_target_absent_in_commit_registry_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project(Path(td))
            other = json.dumps({"registry_schema_version": "v2", "bundles": [
                {"foundation_bundle_version": "v9.9.9", "path": "x",
                 "bundle_tree_sha256": "sha256:t", "bundle_manifest_sha256": "sha256:m"}]})
            r = _emit(proj, fetcher=lambda url, t: other)
            self.assertIsNone(r)
            self.assertFalse((proj / UPDATE_RESOLUTION_REL).exists())

    def test_no_pin_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / ".wizard").mkdir()
            (proj / ".wizard" / "manifest.json").write_text(
                json.dumps({"foundation_bundle_version": "v0.6.1"}), encoding="utf-8")
            # no update-source pin
            r = _emit(proj)
            self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
