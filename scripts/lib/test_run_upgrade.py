"""Tests for run_resolution_upgrade — the two-phase A+ upgrade orchestration.

Phase 1 (toolkit not yet at the approved commit): under the upgrade lock, run the self-update
transaction, then re-exec (os.execv) so the NEW engine runs phase 2. Phase 2 (toolkit already
at the approved commit — the re-exec'd engine): under the lock, re-validate the content gate and
run the apply step. exec_fn + apply_fn are injected so the control flow is testable without
actually replacing the process or running the full foundation-doc merge. Reuses the real-local-
git fixture (a git upstream containing a registry+bundle).
"""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_self_update_resolution import ApplyWithResolutionBase, _head  # noqa: E402
from run_upgrade import run_resolution_upgrade  # noqa: E402
from update_resolution import write_update_resolution, UPDATE_RESOLUTION_REL  # noqa: E402


class RunUpgradePhaseOneTest(ApplyWithResolutionBase):
    def test_phase1_self_updates_then_reexecs(self):
        write_update_resolution(self.operator, self._resolution)
        execs = []
        applies = []
        out = run_resolution_upgrade(
            self.operator, self.toolkit, argv=["upgrade", "--to", "v0.6.2", "--apply"],
            exec_fn=lambda exe, argv: execs.append((exe, argv)),
            apply_fn=lambda r: applies.append(r) or ("applied", r.target_version),
            fetch_remote="local")
        # toolkit advanced to the approved commit (self-update ran)
        self.assertEqual(_head(self.toolkit), self.target_commit)
        # re-exec was triggered; apply did NOT run in this (phase 1) process
        self.assertEqual(len(execs), 1, "phase 1 must re-exec")
        self.assertEqual(applies, [], "apply must run in the re-exec'd phase 2, not phase 1")
        self.assertEqual(out[0], "execed")
        # lock released
        self.assertFalse((self.operator / ".wizard" / "upgrade.lock").exists())


class RunUpgradePhaseTwoTest(ApplyWithResolutionBase):
    def test_phase2_applies_when_already_at_target(self):
        write_update_resolution(self.operator, self._resolution)
        # simulate the re-exec'd engine: toolkit already at the approved commit.
        import subprocess
        subprocess.run(["git", "-C", str(self.toolkit), "fetch", "-q", "local"], check=True)
        subprocess.run(["git", "-C", str(self.toolkit), "checkout", "-q", self.target_commit], check=True)
        applies = []
        out = run_resolution_upgrade(
            self.operator, self.toolkit, argv=["upgrade", "--to", "v0.6.2", "--apply"],
            exec_fn=lambda exe, argv: self.fail("phase 2 must NOT re-exec"),
            apply_fn=lambda r: applies.append(r) or ("applied", r.target_version),
            fetch_remote="local")
        self.assertEqual(len(applies), 1, "phase 2 runs the apply step")
        self.assertEqual(out, ("applied", "v0.6.2"))

    def test_phase2_content_mismatch_refuses(self):
        # at target, but the approved resolution expects a different bundle hash
        import subprocess, json
        subprocess.run(["git", "-C", str(self.toolkit), "fetch", "-q", "local"], check=True)
        subprocess.run(["git", "-C", str(self.toolkit), "checkout", "-q", self.target_commit], check=True)
        d = self._resolution.to_dict()
        d["target_bundle_tree_sha256"] = "sha256:" + "0" * 64
        (self.operator / UPDATE_RESOLUTION_REL).write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
        out = run_resolution_upgrade(
            self.operator, self.toolkit, argv=["x"],
            exec_fn=lambda *a: None, apply_fn=lambda r: self.fail("must not apply on mismatch"),
            fetch_remote="local")
        self.assertEqual(out[0], "refused")


class RunUpgradeNoResolutionTest(ApplyWithResolutionBase):
    def test_no_resolution_refuses(self):
        out = run_resolution_upgrade(
            self.operator, self.toolkit, argv=["x"],
            exec_fn=lambda *a: self.fail("no exec"), apply_fn=lambda r: self.fail("no apply"),
            fetch_remote="local")
        self.assertEqual(out[0], "refused")


if __name__ == "__main__":
    unittest.main()
