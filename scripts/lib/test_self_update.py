"""Tests for the guarded toolkit self-update contract (self_update.py).

Uses a REAL temp git repo (git is available) to exercise the fail-closed gates and the
safe-ordering apply: clean happy path; URL/remote mismatch -> tampered; non-descendant
candidate -> unverified; dirty tree -> refuse; backup created + rollback documented;
operator-project files untouched; new last-known-good recorded.

Stdlib unittest; pip-install-free.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from self_update import (  # noqa: E402
    apply_self_update,
    resolve_remote_commit,
    verify_self_update,
)
from update_source import (  # noqa: E402
    UPDATE_SOURCE_REL,
    CANONICAL_HTTPS_URL,
    record_last_known_good_commit,
    render_update_source_json,
)
from upgrade import UpdateStatus  # noqa: E402


def _run(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True)


def _git(cwd, *args):
    return _run(cwd, "git", *args)


def _commit(repo, msg, fname="file.txt", content="x"):
    (repo / fname).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)
    return _run(repo, "git", "rev-parse", "HEAD").stdout.strip()


class SelfUpdateBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # An "upstream" bare-ish source repo + a toolkit clone of it.
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        _git(self.upstream, "init", "-q")
        _git(self.upstream, "config", "user.email", "t@t.t")
        _git(self.upstream, "config", "user.name", "t")
        _git(self.upstream, "checkout", "-q", "-b", "main")
        self.base_commit = _commit(self.upstream, "base")

        # Toolkit = a clone whose origin remote is the canonical URL (we set it explicitly
        # so verification can compare it to the pinned source).
        self.toolkit = self.root / "agent-wizard"
        _git(self.root, "clone", "-q", str(self.upstream), str(self.toolkit))
        _git(self.toolkit, "config", "user.email", "t@t.t")
        _git(self.toolkit, "config", "user.name", "t")
        # `origin` carries the CANONICAL URL (what verification compares against); a
        # separate `local` remote points at the real upstream path so the test can fetch
        # new commits without hitting the network (the canonical origin is unreachable).
        _git(self.toolkit, "remote", "add", "local", str(self.upstream))
        _git(self.toolkit, "remote", "set-url", "origin", CANONICAL_HTTPS_URL)

        # Operator project with a pinned update-source.json + a sentinel operator file.
        self.operator = self.root / "estate"
        (self.operator / ".wizard").mkdir(parents=True)
        self._write_source(self.base_commit)
        self.sentinel = self.operator / "vision.md"
        self.sentinel.write_text("OPERATOR CONTENT", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _write_source(self, last_known_good):
        (self.operator / UPDATE_SOURCE_REL).write_text(
            render_update_source_json(last_known_good_commit=last_known_good),
            encoding="utf-8",
        )

    def _add_upstream_commit(self):
        new = _commit(self.upstream, "newer", content="y")
        # fetch the new object into the toolkit via the local fetch remote (origin is the
        # unreachable canonical URL used only for origin verification).
        _git(self.toolkit, "fetch", "-q", "local")
        return new


class ResolveRemoteCommitTests(SelfUpdateBase):
    """Option A+: check resolves the EXACT public commit (`git ls-remote <url> <ref>`) and
    binds it into the approved resolution, so self-update checks out exactly that commit. Runs
    against the real local upstream (no network). Fail-closed (None) on any git failure → the
    check renders a could-not-determine status, never a false 'current'."""

    def test_resolves_ref_to_head_sha(self):
        self.assertEqual(
            resolve_remote_commit(self.toolkit, str(self.upstream), "main"), self.base_commit)

    def test_tracks_new_head(self):
        new = self._add_upstream_commit()
        self.assertEqual(
            resolve_remote_commit(self.toolkit, str(self.upstream), "main"), new)

    def test_unknown_ref_returns_none(self):
        self.assertIsNone(
            resolve_remote_commit(self.toolkit, str(self.upstream), "no-such-branch"))

    def test_unreachable_source_returns_none(self):
        self.assertIsNone(
            resolve_remote_commit(self.toolkit, str(self.root / "nope-not-a-repo"), "main"))


class VerifyGateTests(SelfUpdateBase):
    def test_happy_path_update_available(self):
        new = self._add_upstream_commit()
        res = verify_self_update(self.toolkit, self.operator, candidate_commit=new)
        self.assertEqual(res.status, UpdateStatus.UPDATE_AVAILABLE)
        self.assertFalse(res.applied)
        # honest ceiling is surfaced
        self.assertIn("NOT a cryptographic signature", res.message)

    def test_source_unconfigured(self):
        (self.operator / UPDATE_SOURCE_REL).unlink()
        res = verify_self_update(self.toolkit, self.operator)
        self.assertEqual(res.status, UpdateStatus.SOURCE_UNCONFIGURED)

    def test_remote_mismatch_is_tampered(self):
        _git(self.toolkit, "remote", "set-url", "origin",
             "https://github.com/attacker/evil.git")
        new = self._add_upstream_commit()
        res = verify_self_update(self.toolkit, self.operator, candidate_commit=new)
        self.assertEqual(res.status, UpdateStatus.UPDATE_SOURCE_TAMPERED)
        self.assertFalse(res.applied)

    def test_dirty_tree_refused(self):
        new = self._add_upstream_commit()
        (self.toolkit / "dirty.txt").write_text("uncommitted", encoding="utf-8")
        res = verify_self_update(self.toolkit, self.operator, candidate_commit=new)
        self.assertEqual(res.status, UpdateStatus.TOOLKIT_UNVERIFIED)

    def test_non_descendant_candidate_unverified(self):
        # Create a divergent commit on a separate orphan branch (not descended from base).
        _git(self.toolkit, "checkout", "-q", "--orphan", "rogue")
        _run(self.toolkit, "git", "rm", "-rf", "--cached", ".")
        (self.toolkit / "rogue.txt").write_text("rogue", encoding="utf-8")
        _git(self.toolkit, "add", "-A")
        _git(self.toolkit, "commit", "-q", "-m", "rogue")
        rogue = _run(self.toolkit, "git", "rev-parse", "HEAD").stdout.strip()
        # restore HEAD to base so working tree is clean + lineage base == base_commit
        _git(self.toolkit, "checkout", "-q", "main")
        res = verify_self_update(self.toolkit, self.operator, candidate_commit=rogue)
        self.assertEqual(res.status, UpdateStatus.CANDIDATE_UNVERIFIED)

    def test_already_current_checked_current(self):
        # candidate == current HEAD, last-known-good == base
        res = verify_self_update(self.toolkit, self.operator, candidate_commit=self.base_commit)
        self.assertEqual(res.status, UpdateStatus.CHECKED_CURRENT)

    def test_not_a_git_repo_toolkit_unverified(self):
        plain = self.root / "plain"
        plain.mkdir()
        res = verify_self_update(plain, self.operator, candidate_commit=self.base_commit)
        self.assertEqual(res.status, UpdateStatus.TOOLKIT_UNVERIFIED)


class ApplyTests(SelfUpdateBase):
    def test_apply_happy_path_backs_up_swaps_records(self):
        new = self._add_upstream_commit()

        def _record(commit):
            record_last_known_good_commit(self.operator, commit)

        res = apply_self_update(
            self.toolkit, self.operator, candidate_commit=new, record_commit_fn=_record,
        )
        self.assertEqual(res.status, UpdateStatus.UPDATE_AVAILABLE)
        self.assertTrue(res.applied)
        # toolkit advanced to the new commit
        head = _run(self.toolkit, "git", "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(head, new)
        # backup created
        self.assertTrue(Path(res.backup_dir).is_dir())
        self.assertIn("Rename the backup", res.rollback_instructions)
        # new last-known-good recorded into the (read-only-to-AI) reference
        src = json.loads((self.operator / UPDATE_SOURCE_REL).read_text())
        self.assertEqual(src["last_known_good_commit"], new)

    def test_apply_never_touches_operator_files(self):
        new = self._add_upstream_commit()
        before = self.sentinel.read_text()
        apply_self_update(self.toolkit, self.operator, candidate_commit=new)
        self.assertEqual(self.sentinel.read_text(), before)

    def test_apply_refuses_dirty_tree_no_backup(self):
        new = self._add_upstream_commit()
        (self.toolkit / "dirty.txt").write_text("uncommitted", encoding="utf-8")
        res = apply_self_update(self.toolkit, self.operator, candidate_commit=new)
        self.assertEqual(res.status, UpdateStatus.TOOLKIT_UNVERIFIED)
        self.assertFalse(res.applied)
        self.assertEqual(res.backup_dir, "")  # refused before backup

    def test_apply_tampered_remote_no_change(self):
        _git(self.toolkit, "remote", "set-url", "origin",
             "https://github.com/attacker/evil.git")
        new = self._add_upstream_commit()
        head_before = _run(self.toolkit, "git", "rev-parse", "HEAD").stdout.strip()
        res = apply_self_update(self.toolkit, self.operator, candidate_commit=new)
        self.assertEqual(res.status, UpdateStatus.UPDATE_SOURCE_TAMPERED)
        self.assertFalse(res.applied)
        head_after = _run(self.toolkit, "git", "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(head_before, head_after)  # unchanged


if __name__ == "__main__":
    unittest.main()
