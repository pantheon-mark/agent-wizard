"""CLI-level tests for `wizard self-upgrade` (run_self_upgrade) — the operator-reach two-phase
upgrade command: emit the approved resolution (the approve step), self-update the toolkit to the
approved commit, re-exec, and apply in the freshly-installed engine.

Offline by construction: the real-local-git harness (ApplyWithResolutionBase) supplies a git
upstream containing a registry + bundle; commit_resolver / fetcher / exec_fn / apply_fn are
injected so neither the network, a real os.execv, nor the heavy foundation-doc merge is needed.
The real os.execv crossing + real apply are covered by test_run_upgrade (orchestration) and the
post-publish live estate e2e — this layer pins the CLI glue: emit-or-skip, fail-closed, phase
routing, exit codes.
"""

import json
import subprocess
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))          # lib/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # scripts/

from test_self_update_resolution import ApplyWithResolutionBase, _head  # noqa: E402
from update_resolution import (  # noqa: E402
    UPDATE_RESOLUTION_REL,
    load_update_resolution,
    write_update_resolution,
)
import wizard_upgrade  # noqa: E402


def _reg_text(base) -> str:
    return (base.upstream / "registry" / "foundation-bundles.json").read_text(encoding="utf-8")


def _call(base, **overrides):
    """Drive run_self_upgrade with the harness paths + safe injected defaults; overrides win."""
    kwargs = dict(
        operator_dir=base.operator,
        toolkit_dir=base.toolkit,
        registry_path=base.toolkit / "registry" / "foundation-bundles.json",
        manifest_path=base.operator / ".wizard" / "manifest.json",
        manifest={"foundation_bundle_version": "v0.6.1"},
        target_version="v0.6.2",
        checked_at="2026-06-23T00:00:00Z",
        fetch_remote="local",
        commit_resolver=lambda tk, url, ref: base.target_commit,
        fetcher=lambda url, timeout=10: _reg_text(base),
        exec_fn=lambda exe, argv: None,
        apply_fn=lambda r: ("apply_complete", 0),
        reexec_argv=["wizard_upgrade.py", "self-upgrade", "--to", "v0.6.2", "--apply"],
    )
    kwargs.update(overrides)
    return wizard_upgrade.run_self_upgrade(**kwargs)


class SelfUpgradePhase1Test(ApplyWithResolutionBase):
    def test_emits_resolution_self_updates_and_reexecs(self):
        execs, applies = [], []
        rc = _call(
            self,
            exec_fn=lambda exe, argv: execs.append((exe, argv)),
            apply_fn=lambda r: applies.append(r) or ("apply_complete", 0),
        )
        # the approve step emitted the immutable resolution, bound to the exact target commit
        self.assertTrue((self.operator / UPDATE_RESOLUTION_REL).exists())
        res = load_update_resolution(self.operator)
        self.assertEqual(res.target_version, "v0.6.2")
        self.assertEqual(res.target_public_commit_sha, self.target_commit)
        # phase 1 self-updated the toolkit to the approved commit + re-exec'd; apply did NOT run here
        self.assertEqual(_head(self.toolkit), self.target_commit)
        self.assertEqual(len(execs), 1, "phase 1 must re-exec the fresh engine")
        self.assertEqual(applies, [], "apply runs in the re-exec'd phase 2, never in phase 1")
        self.assertEqual(rc, 0)


class SelfUpgradePhase2Test(ApplyWithResolutionBase):
    def test_skips_emit_and_applies_when_resolution_present_and_at_target(self):
        # re-exec'd engine: the resolution is already approved + the toolkit already at the target
        write_update_resolution(self.operator, self._resolution)
        subprocess.run(["git", "-C", str(self.toolkit), "fetch", "-q", "local"], check=True)
        subprocess.run(["git", "-C", str(self.toolkit), "checkout", "-q", self.target_commit], check=True)
        resolver_calls, applies = [], []
        rc = _call(
            self,
            commit_resolver=lambda *a: resolver_calls.append(a) or self.target_commit,
            fetcher=lambda url, timeout=10: self.fail("must not fetch in phase 2"),
            exec_fn=lambda *a: self.fail("phase 2 must NOT re-exec"),
            apply_fn=lambda r: applies.append(r) or ("apply_complete", 0),
            reexec_argv=["x"],
        )
        self.assertEqual(resolver_calls, [], "a matching resolution -> emit (and its git touch) is skipped")
        self.assertEqual(len(applies), 1, "phase 2 runs the apply step")
        self.assertEqual(rc, 0)


class SelfUpgradeFailClosedTest(ApplyWithResolutionBase):
    def test_emit_unresolvable_fails_closed_no_self_update(self):
        rc = _call(
            self,
            commit_resolver=lambda *a: None,  # git cannot resolve the public commit -> emit None
            fetcher=lambda url, timeout=10: self.fail("never reached when the commit is unresolved"),
            exec_fn=lambda *a: self.fail("must not self-update without an approved resolution"),
            apply_fn=lambda r: self.fail("must not apply"),
        )
        self.assertNotEqual(rc, 0, "could-not-prepare must be a nonzero (not-applied) exit")
        self.assertFalse((self.operator / UPDATE_RESOLUTION_REL).exists(), "nothing written on fail-closed")
        self.assertEqual(_head(self.toolkit), self.base_commit, "toolkit untouched on fail-closed")


class SelfUpgradeStaleResolutionTest(ApplyWithResolutionBase):
    def test_stale_resolution_for_other_target_is_reemitted(self):
        # a leftover resolution for a DIFFERENT target must be re-emitted for the requested version
        d = self._resolution.to_dict()
        d["target_version"] = "v9.9.9"
        (self.operator / UPDATE_RESOLUTION_REL).write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
        rc = _call(self, exec_fn=lambda *a: None)
        self.assertEqual(load_update_resolution(self.operator).target_version, "v0.6.2")
        self.assertEqual(rc, 0)

    def test_self_update_refusal_surfaces_nonzero(self):
        # resolution present + matching, but the toolkit is NOT at the target and self-update is
        # made to refuse (tampered expected bundle hash) -> run_resolution_upgrade returns refused.
        d = self._resolution.to_dict()
        d["target_bundle_tree_sha256"] = "sha256:" + "0" * 64
        (self.operator / UPDATE_RESOLUTION_REL).write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
        rc = _call(
            self,
            commit_resolver=lambda *a: self.fail("matching resolution -> no re-emit"),
            fetcher=lambda *a: self.fail("matching resolution -> no fetch"),
            exec_fn=lambda *a: self.fail("self-update refusal must not re-exec"),
            apply_fn=lambda r: self.fail("must not apply when self-update refuses"),
        )
        self.assertNotEqual(rc, 0)
        self.assertEqual(_head(self.toolkit), self.base_commit, "refused self-update leaves toolkit put")


if __name__ == "__main__":
    unittest.main()
