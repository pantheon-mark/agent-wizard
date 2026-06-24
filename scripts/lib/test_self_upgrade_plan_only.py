"""`wizard self-upgrade --to V --plan-only` (read-only preview) + the `--expect-commit`
approval-continuity guard on `--apply`.

Two layers, both offline:
  * PlanOnly* — run_self_upgrade_plan with injected commit_resolver/fetcher over a temp project:
    the preview renders the change + the expect-commit apply command and writes NOTHING; an
    unresolvable source reports could-not-confirm (never a fabricated/stale preview).
  * ExpectCommitGuard* — run_self_upgrade over the real-local-git harness: a matching
    --expect-commit proceeds; a mismatched one fails closed BEFORE any write or self-update
    (the operator approved commit A, so applying a moved-to commit B is impossible).
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))          # lib/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # scripts/

import wizard_upgrade  # noqa: E402
from update_resolution import UPDATE_RESOLUTION_REL  # noqa: E402
from update_source import emit_update_source  # noqa: E402
from test_self_update_resolution import ApplyWithResolutionBase, _head  # noqa: E402
from test_wizard_self_upgrade_cli import _call  # noqa: E402

_SHA = "c" * 40
_ENTRY = {
    "foundation_bundle_version": "v0.6.6",
    "path": "foundation-bundles/v0.6.6/",
    "bundle_tree_sha256": "sha256:tree-x",
    "bundle_manifest_sha256": "sha256:manifest-x",
    "safety_class": "safety_fix",
    "recommendation_reason": "fixes the missing update preview",
    "changelog": "Adds a read-only preview before applying updates.",
}
_REGISTRY = json.dumps({"registry_schema_version": "v2", "bundles": [_ENTRY]})


def _project(tmp: Path, version="v0.6.5") -> Path:
    emit_update_source(tmp)  # .wizard/update-source.json (pantheon-mark/agent-wizard)
    (tmp / ".wizard" / "manifest.json").write_text(
        json.dumps({"foundation_bundle_version": version}), encoding="utf-8")
    return tmp


class PlanOnlyReadOnlyTest(unittest.TestCase):
    def _run(self, proj, **over):
        kw = dict(
            operator_dir=proj, toolkit_dir=proj, target_version="v0.6.6",
            from_version="v0.6.5", checked_at="2026-06-24T00:00:00Z",
            commit_resolver=lambda *a, **k: _SHA,
            fetcher=lambda url, t: _REGISTRY,
        )
        kw.update(over)
        return wizard_upgrade.run_self_upgrade_plan(**kw)

    def test_plan_only_renders_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project(Path(td))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = self._run(proj)
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            # READ-ONLY: no approved-resolution persisted, no toolkit change
            self.assertFalse((proj / UPDATE_RESOLUTION_REL).exists())
            # surfaces the change, the recommendation, and the expect-commit apply command
            self.assertIn("v0.6.6", out)
            self.assertIn("NOTHING", out)
            self.assertIn("--expect-commit", out)
            self.assertIn(_SHA[:12], out)
            self.assertIn("recommend_apply", out)

    def test_plan_only_json_marks_wrote_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project(Path(td))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = self._run(proj, json_mode=True)
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertFalse(payload["wrote_anything"])
            self.assertEqual(payload["expected_commit"], _SHA)
            self.assertFalse((proj / UPDATE_RESOLUTION_REL).exists())

    def test_plan_only_unresolvable_reports_currency_unconfirmed_no_write(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project(Path(td))
            errbuf = io.StringIO()
            with contextlib.redirect_stderr(errbuf):
                rc = self._run(proj, commit_resolver=lambda *a, **k: None)
            self.assertNotEqual(rc, 0)
            self.assertIn("CURRENCY_UNCONFIRMED", errbuf.getvalue())
            self.assertFalse((proj / UPDATE_RESOLUTION_REL).exists())


class ExpectCommitGuardTest(ApplyWithResolutionBase):
    def test_matching_expect_commit_proceeds(self):
        execs = []
        rc = _call(self, expect_commit=self.target_commit,
                   exec_fn=lambda exe, argv: execs.append((exe, argv)))
        self.assertEqual(rc, 0)
        self.assertTrue((self.operator / UPDATE_RESOLUTION_REL).exists())
        self.assertEqual(len(execs), 1, "matching preview must proceed to self-update + re-exec")

    def test_short_prefix_expect_commit_matches(self):
        rc = _call(self, expect_commit=self.target_commit[:12], exec_fn=lambda *a: None)
        self.assertEqual(rc, 0)
        self.assertTrue((self.operator / UPDATE_RESOLUTION_REL).exists())

    def test_mismatched_expect_commit_fails_closed(self):
        rc = _call(
            self,
            expect_commit="0" * 40,  # not the live-resolved target commit
            exec_fn=lambda *a: self.fail("must not self-update on a stale preview"),
            apply_fn=lambda r: self.fail("must not apply on a stale preview"),
        )
        self.assertNotEqual(rc, 0)
        self.assertFalse((self.operator / UPDATE_RESOLUTION_REL).exists(),
                         "stale-preview guard must write nothing")
        self.assertEqual(_head(self.toolkit), self.base_commit,
                         "toolkit must be untouched when the preview is stale")


if __name__ == "__main__":
    unittest.main()
