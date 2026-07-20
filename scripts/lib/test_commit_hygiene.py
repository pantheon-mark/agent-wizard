"""Behavioral (script-level) tests for the always-on commit-hygiene guard shipped
to every emitted operator system: wizard/templates/claude_config/commit_hygiene.sh.

Like test_receipt_gate.py, these are NOT source-string assertions — they build a REAL
temporary git repo, invoke the real canonical commit_hygiene.sh as a subprocess with a
synthetic hook-event JSON on stdin and CLAUDE_PROJECT_DIR pointed at the temp repo, and
assert the runtime RESULT (what got committed, what did NOT, what was surfaced). This
proves the safety properties actually hold end-to-end:

  Piece 4 (policy-aware commit) + F-30:
    - code/docs/state files ARE committed on SessionEnd;
    - data/secret files are NEVER committed — even a NON-gitignored one passed in;
    - an already-TRACKED sensitive file (committed before its ignore rule existed) is
      detected, `git rm --cached`'d, and a history-scrub prompt is surfaced;
    - fail-open: run outside a git repo (or on a git error) exits 0, never wedges.
  Piece 2 (SessionStart clean-tree check):
    - surfaces the count of uncommitted changes from prior work;
    - surfaces F-30 already-tracked sensitive findings at orientation.
  Piece 1 (SessionEnd enforced commit):
    - a clean tree yields no new commit; outstanding work is committed.

The emission of this script into .claude/ (and its SessionEnd / second-SessionStart hook
wiring in settings.json) is asserted separately below against the CANONICAL templates —
emission itself is sourced from the frozen bundle (which will carry this file once a bundle
is cut), so the bundle-sourced scaffold tests are not the place to assert a not-yet-cut
canonical addition.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMIT_HYGIENE = REPO_ROOT / "wizard" / "templates" / "claude_config" / "commit_hygiene.sh"
SETTINGS_JSON = REPO_ROOT / "wizard" / "templates" / "claude_config" / "settings.json"

BASH = shutil.which("bash")
GIT = shutil.which("git")
HAVE_TOOLS = bool(BASH) and bool(GIT) and bool(shutil.which("python3"))


def _git(repo, *args, check=True):
    return subprocess.run(
        [GIT, "-C", str(repo), *args],
        capture_output=True, text=True, check=check,
    )


@unittest.skipUnless(HAVE_TOOLS, "bash / git / python3 unavailable")
class CommitHygieneBehaviorTests(unittest.TestCase):
    """Invoke the real commit_hygiene.sh against a real temp git repo."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@t.test")
        _git(self.repo, "config", "user.name", "Test")
        # a committed baseline so HEAD exists
        (self.repo / "README.md").write_text("baseline\n", encoding="utf-8")
        _git(self.repo, "add", "README.md")
        _git(self.repo, "commit", "-q", "-m", "baseline")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, event, extra_env=None):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.repo)}
        if extra_env:
            env.update(extra_env)
        payload = json.dumps({"hook_event_name": event}) if event else ""
        return subprocess.run(
            [BASH, str(COMMIT_HYGIENE)],
            input=payload, capture_output=True, text=True,
            cwd=str(self.repo), env=env,
        )

    def _tracked(self):
        return set(_git(self.repo, "ls-files").stdout.split())

    def _head_files(self):
        out = _git(self.repo, "show", "--name-only", "--pretty=format:", "HEAD").stdout
        return set(f for f in out.split() if f)

    # ---- Piece 4: positive — code/docs + KNOWN-PATH config committed -------
    # NOTE (Important-1 fix): under the fail-safe (deny-by-default) posture a bare
    # `state.json` at the repo root is NO LONGER auto-committed — a `.json` is committed
    # ONLY at a known config path (.claude/settings.json, .wizard/manifest.json). This
    # test was corrected from asserting the old allow-by-default behavior (root state.json
    # committed) to the new posture; a separate test proves a root/data `.json` surfaces.
    def test_code_docs_and_known_config_are_committed_on_session_end(self):
        (self.repo / "notes.md").write_text("doc\n", encoding="utf-8")
        (self.repo / "run.py").write_text("print(1)\n", encoding="utf-8")
        # the system's own config/state at KNOWN paths (the only way a .json commits):
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.json").write_text('{"a":1}\n', encoding="utf-8")
        (self.repo / ".wizard").mkdir()
        (self.repo / ".wizard" / "manifest.json").write_text('{"v":1}\n', encoding="utf-8")
        before = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(before, after, "SessionEnd made no commit for outstanding work")
        tracked = self._tracked()
        for f in ("notes.md", "run.py", ".claude/settings.json", ".wizard/manifest.json"):
            self.assertIn(f, tracked, f"{f} (code/docs/known-config) was not committed")

    # ---- Piece 4 (Important-1 fix): data-shaped UNLISTED extensions are NOT
    # auto-committed and ARE surfaced (deny-by-default) --------------------
    def test_data_shaped_unlisted_extensions_are_not_committed_but_surfaced(self):
        # None of these are on the (old) built-in deny list a reviewer could enumerate;
        # under allow-by-default they would have been silently auto-committed. Under
        # deny-by-default they are not safe -> not committed -> surfaced.
        data_files = ("events.jsonl", "stream.ndjson", "model.pkl",
                      "array.npy", "dump.dat", "table.parquet")
        for f in data_files:
            (self.repo / f).write_text("payload\n", encoding="utf-8")
        # a legitimate doc alongside proves the guard still commits the safe part
        (self.repo / "ok.md").write_text("doc\n", encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        tracked = self._tracked()
        for f in data_files:
            self.assertNotIn(f, tracked, f"deny-by-default failed: data file committed: {f}")
        self.assertIn("ok.md", tracked, "guard failed to commit the legitimate doc")
        # never silently dropped: each unsafe file is surfaced for an operator decision
        out = r.stdout + r.stderr
        self.assertIn("REVIEW NEEDED", out, "unsafe files were not surfaced for decision")
        for f in data_files:
            self.assertIn(f, out, f"unsafe file {f} was neither committed nor surfaced")

    # ---- Piece 4 (Important-1 fix): a .json DATA export at a non-config path is
    # treated as data (NOT auto-committed), while a known-config .json commits ----
    def test_json_data_export_at_nonconfig_path_is_not_committed(self):
        (self.repo / "client_export.json").write_text('[{"pii":"x"}]\n', encoding="utf-8")
        # a KNOWN-path config .json in the same run must still commit
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.json").write_text('{"ok":1}\n', encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        tracked = self._tracked()
        self.assertNotIn("client_export.json", tracked,
                         "a non-config .json data export was auto-committed")
        self.assertIn(".claude/settings.json", tracked,
                      "a known-config .json was not committed")
        self.assertIn("client_export.json", r.stdout + r.stderr,
                      "the surfaced .json data export was silently dropped")

    # ---- Piece 4 (Important-2 fix): system-owned control-plane state paths
    # ARE auto-committed — agents/handoffs/ (control-plane handoff envelopes +
    # pre-write receipt) and security/capability_descriptors.json (the system
    # descriptor set) — widening the allowlist that Important-1 had narrowed
    # too far and started surfacing these as REVIEW NEEDED every session. ----
    def test_system_control_plane_state_paths_are_committed(self):
        # Seed agents/ and security/ as ALREADY-TRACKED (the wizard scaffolds both
        # at close, per CLAUDE.md's "Operations" list, before any handoff or
        # descriptor file is ever written) so the new files below are reported by
        # `git status` at file granularity rather than collapsed into a brand-new
        # top-level "agents/"/"security/" directory entry — matching real topology.
        (self.repo / "agents").mkdir()
        (self.repo / "agents" / "roster.md").write_text("roster\n", encoding="utf-8")
        (self.repo / "security").mkdir()
        (self.repo / "security" / "README.md").write_text("sec\n", encoding="utf-8")
        _git(self.repo, "add", "agents/roster.md", "security/README.md")
        _git(self.repo, "commit", "-q", "-m", "seed agents/ and security/ scaffolding")

        (self.repo / "agents" / "handoffs").mkdir(parents=True)
        (self.repo / "agents" / "handoffs" / "builder_task1_handoff.json").write_text(
            '{"task_id":"task1"}\n', encoding="utf-8")
        (self.repo / "agents" / "handoffs" / ".prewrite_receipt.json").write_text(
            '{"ok":true}\n', encoding="utf-8")
        (self.repo / "security" / "capability_descriptors.json").write_text(
            '{"descriptors":[]}\n', encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        tracked = self._tracked()
        for f in (
            "agents/handoffs/builder_task1_handoff.json",
            "agents/handoffs/.prewrite_receipt.json",
            "security/capability_descriptors.json",
        ):
            self.assertIn(f, tracked, f"{f} (system control-plane state) was not committed")

    # ---- Regression guard (Important-2 fix): the widening above must NOT
    # re-open the data-exposure vector Important-1 closed. A data .json at a
    # non-config path, and credential/secret paths — including ones that live
    # UNDER security/ but are NOT the specific descriptor path just allow-
    # listed — must still surface / not be committed. ----------------------
    def test_widened_allowlist_does_not_reopen_data_or_secret_exposure(self):
        # data-shaped .json at a non-config, non-control-plane path
        (self.repo / "client_export2.json").write_text('[{"pii":"y"}]\n', encoding="utf-8")
        # credential paths under security/ that are NOT the allow-listed descriptor file
        (self.repo / "security" / "session_cookies").mkdir(parents=True)
        (self.repo / "security" / "session_cookies" / "x").write_text(
            "cookie-data\n", encoding="utf-8")
        (self.repo / ".env").write_text("API_KEY=supersecret\n", encoding="utf-8")
        (self.repo / "id_rsa").write_text("-----BEGIN KEY-----\n", encoding="utf-8")
        (self.repo / "root_dump.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        tracked = self._tracked()
        for bad in (
            "client_export2.json",
            "security/session_cookies/x",
            ".env",
            "id_rsa",
            "root_dump.csv",
        ):
            self.assertNotIn(bad, tracked,
                              f"widened allowlist re-opened exposure for: {bad}")
        out = r.stdout + r.stderr
        for surfaced in ("client_export2.json", "id_rsa", "root_dump.csv"):
            self.assertIn(surfaced, out,
                          f"{surfaced} was neither committed nor surfaced (silently dropped)")

    # ---- Piece 4 (Important-1 fix): an entirely UNKNOWN extension is not
    # auto-committed (deny-by-default) and is surfaced ---------------------
    def test_unknown_extension_is_not_committed_but_surfaced(self):
        (self.repo / "mystery.xyzq").write_text("who knows\n", encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("mystery.xyzq", self._tracked(),
                         "an unknown-extension file was auto-committed")
        self.assertIn("mystery.xyzq", r.stdout + r.stderr,
                      "an unknown-extension file was neither committed nor surfaced")

    # ---- Piece 4: negative — data/secrets NEVER committed -----------------
    def test_secrets_and_data_are_never_committed(self):
        # .env + logs are gitignored (normal posture); secret.csv is NOT gitignored
        # (a misconfiguration) — the guard must refuse it anyway (defense in depth).
        (self.repo / ".gitignore").write_text(".env\n/logs/\n", encoding="utf-8")
        (self.repo / ".env").write_text("API_KEY=supersecret\n", encoding="utf-8")
        (self.repo / "logs").mkdir()
        (self.repo / "logs" / "run.log").write_text("stuff\n", encoding="utf-8")
        (self.repo / "master_list_copy.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        (self.repo / "id_rsa").write_text("-----BEGIN KEY-----\n", encoding="utf-8")
        (self.repo / "ok.md").write_text("real doc\n", encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        tracked = self._tracked()
        for bad in (".env", "logs/run.log", "master_list_copy.csv", "id_rsa"):
            self.assertNotIn(bad, tracked, f"guard committed a data/secret file: {bad}")
        # the legitimate doc AND the .gitignore itself (code/state) are fine to commit
        self.assertIn("ok.md", tracked, "guard failed to commit the legitimate doc")

    # ---- F-30: already-tracked sensitive file detected + rm --cached + scrub
    def test_f30_already_tracked_secret_is_uncached_and_scrub_prompted(self):
        # A CSV committed BEFORE any ignore rule existed — the estate's master_list_copy.csv.
        csv = self.repo / "master_list_copy.csv"
        csv.write_text("name,email\nx,y\n", encoding="utf-8")
        _git(self.repo, "add", "master_list_copy.csv")
        _git(self.repo, "commit", "-q", "-m", "oops tracked data")
        self.assertIn("master_list_copy.csv", self._tracked())
        # Now the ignore rule is added (policy stated) — but the file stays tracked (illusory).
        (self.repo / ".gitignore").write_text("*.csv\n", encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        # rm --cached: no longer tracked...
        self.assertNotIn("master_list_copy.csv", self._tracked(),
                         "F-30: already-tracked sensitive file was left tracked")
        # ...but the working file is preserved on disk (rm --cached, not rm)
        self.assertTrue(csv.exists(), "F-30 must not delete the operator's working file")
        # ...and a history-scrub prompt is surfaced.
        out = (r.stdout + r.stderr).lower()
        self.assertIn("master_list_copy.csv", r.stdout + r.stderr)
        self.assertIn("histor", out, "F-30 did not surface a history-scrub prompt")

    # ---- F-83: SAFETY CHECK keys on change TYPE (A/M vs D), not bare path
    # presence. An untracking (a `D` staged BEFORE this hook ran -- e.g. by a
    # prior `git rm --cached`, not caught by THIS run's F-30 tracked_bad set
    # because the path is already gone from `git ls-files` by the time the
    # hook's F-30 scan runs) must be committed, never reverted. -----------
    def test_f83_pre_staged_untracking_of_sensitive_path_is_committed_not_reverted(self):
        # A previously-tracked sensitive (csv) file, exactly the estate's
        # master_list_copy.csv shape -- but here the untracking already
        # happened BEFORE this hook invocation (simulating a prior session /
        # external `git rm --cached`), so THIS run's F-30 tracked_bad set
        # (computed from `git ls-files` at hook-start) will NOT contain it --
        # the scenario the old backstop's bare-path check falsely reverted.
        csv = self.repo / "legacy_export.csv"
        csv.write_text("name,email\nx,y\n", encoding="utf-8")
        _git(self.repo, "add", "legacy_export.csv")
        _git(self.repo, "commit", "-q", "-m", "oops tracked data (pre-existing)")
        (self.repo / ".gitignore").write_text("*.csv\n", encoding="utf-8")
        # Untrack it OURSELVES, standing in for "already untracked before the
        # hook ran" -- by hook time, `git ls-files` no longer lists it.
        _git(self.repo, "rm", "--cached", "-q", "legacy_export.csv")
        self.assertNotIn("legacy_export.csv", self._tracked(), "precondition: already untracked")
        before = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(before, after, "the untracking + .gitignore were not committed")
        self.assertNotIn("legacy_export.csv", self._tracked(),
                          "F-83: a pre-staged untracking of a sensitive path was REVERTED "
                          "(false-abort) instead of being committed")
        # the file must not be present in the new commit's TREE (ls-tree, not the
        # changed-paths list from `git show --name-only`, which lists a deletion too).
        tree = set(_git(self.repo, "ls-tree", "-r", "--name-only", "HEAD").stdout.split())
        self.assertNotIn("legacy_export.csv", tree,
                          "F-83: the reverted content was committed back into HEAD's tree")
        # the working copy is untouched (rm --cached, never a hard delete).
        self.assertTrue(csv.exists())

    def test_f83_worktree_only_deletion_of_sensitive_path_is_staged_and_committed(self):
        # A worktree-only delete (no prior staging at all) of a tracked sensitive
        # file: `os.remove` (not `git rm --cached`), so there is no leftover
        # untracked shadow file and no dual "D"/"??" status-record landmine --
        # the guard must stage this deletion itself and commit it.
        csv = self.repo / "old_dump.csv"
        csv.write_text("a,b\n1,2\n", encoding="utf-8")
        _git(self.repo, "add", "old_dump.csv")
        _git(self.repo, "commit", "-q", "-m", "oops tracked data 2")
        (self.repo / ".gitignore").write_text("*.csv\n", encoding="utf-8")
        os.remove(str(csv))
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("old_dump.csv", self._tracked(),
                          "F-83: a worktree-only deletion of a sensitive path was not staged/committed")

    def test_f30_already_tracked_intercepts_staged_sensitive_basename_before_backstop_runs(self):
        # RENAMED (E2 review, Important fix) from
        # test_f83_staged_sensitive_content_addition_still_reverted_by_backstop, which
        # claimed to prove the NEW F-83 backstop (_staged_status_records / _is_pure_delete /
        # status.startswith("D") at commit_hygiene.sh's staged-set check) does not
        # over-correct. It does not: `id_rsa` is a BUILTIN-sensitive basename
        # (SENSITIVE_BASENAME_GLOBS), and `git ls-files` lists a path the moment it is
        # `git add`ed -- even before any commit -- so the PRE-EXISTING F-30 "already-tracked"
        # pass (_tracked_sensitive, computed from git ls-files at hook-start) intercepts this
        # file and `git rm --cached`s it BEFORE the new backstop's staged-status check ever
        # runs. This test proves F-30 already-tracked interception, not the new backstop
        # logic. See test_f83_backstop_reverts_staged_unsafe_extension_pure_add below for a
        # test that genuinely isolates the new backstop path (a file F-30 does NOT catch).
        secret = self.repo / "id_rsa"
        secret.write_text("-----BEGIN KEY-----\n", encoding="utf-8")
        _git(self.repo, "add", "id_rsa")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("id_rsa", self._tracked(),
                          "F-30 already-tracked interception failed: staged sensitive "
                          "CONTENT (an add) was committed instead of being untracked")
        self.assertIn("id_rsa", r.stdout + r.stderr,
                      "staged sensitive content was neither committed nor surfaced")

    def test_f83_backstop_reverts_staged_unsafe_extension_pure_add(self):
        # Fix 1(b) (E2 review, Important fix): genuinely isolates the NEW F-83 backstop
        # (_staged_status_records / _is_pure_delete / status.startswith("D")) from the
        # PRE-EXISTING F-30 already-tracked pass exercised above. This file is chosen so
        # F-30 CANNOT intercept it: it is not a builtin-sensitive basename/path
        # (SENSITIVE_BASENAME_GLOBS / SENSITIVE_PATH_MARKERS do not match "field_export.xyzq"),
        # and it is not gitignored -- so _tracked_sensitive()/tracked_bad never sees it. It
        # IS unsafe to auto-commit (".xyzq" is not in SAFE_EXTS). It is staged as a PURE "A"
        # (add) -- no "D" component at all -- so the ONLY thing that can revert it is the
        # backstop's change-type check (_is_safe_to_commit against the real staged status
        # from _staged_status_records). This proves the change-type keying genuinely reverts
        # a real staged-content add, and that only a pure "D" is exempted -- not "anything
        # already staged."
        unsafe = self.repo / "field_export.xyzq"
        unsafe.write_text("mystery payload\n", encoding="utf-8")
        _git(self.repo, "add", "field_export.xyzq")
        status = _git(self.repo, "status", "--porcelain").stdout
        self.assertIn("A  field_export.xyzq", status,
                      "precondition: expected a pure staged-add (A) status, not a mixed one")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("field_export.xyzq", self._tracked(),
                          "the NEW backstop failed to revert a staged unsafe-extension pure "
                          "add -- change-type keying over-exempted a real content add")
        self.assertIn("field_export.xyzq", r.stdout + r.stderr,
                      "the reverted staged unsafe content was neither committed nor surfaced")

    def test_mixed_status_modified_then_deleted_is_not_treated_as_pure_delete(self):
        # Fix 2 (E2 review, Minor): _is_pure_delete must NOT treat a MIXED status record
        # -- staged content modification (M) plus an unstaged worktree deletion (D), i.e.
        # git status "MD" -- as a pure delete. A record with a "D" component that ALSO
        # carries an "M"/"A" staged-content component must still go through the normal
        # safety classification: the content side is HANDLED, not exempted. If it were
        # (wrongly) treated as a pure delete, the guard would `git add` it -- staging a
        # delete OVER the unvetted modification -- and commit that delete, and the file
        # would silently vanish from the repo without its staged content ever being
        # classified safe or unsafe.
        tracked = self.repo / "tracked_mixed.xyzq"
        tracked.write_text("hi\n", encoding="utf-8")
        _git(self.repo, "add", "tracked_mixed.xyzq")
        _git(self.repo, "commit", "-q", "-m", "baseline mixed-status file")
        tracked.write_text("modified content\n", encoding="utf-8")
        _git(self.repo, "add", "tracked_mixed.xyzq")  # stage the modification (M)
        os.remove(str(tracked))  # then delete from the worktree, unstaged -> status "MD"
        status = _git(self.repo, "status", "--porcelain").stdout
        self.assertIn("MD tracked_mixed.xyzq", status,
                      "precondition: mixed MD status was not reproduced")
        before = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(before, after,
                          "a mixed MD status was wrongly treated as a pure delete and "
                          "committed as a deletion without vetting the staged modification")
        self.assertIn("tracked_mixed.xyzq", self._tracked(),
                      "a mixed MD status was wrongly exempted as a pure delete -- the file "
                      "was removed from the repo instead of having its content side handled")
        self.assertIn("tracked_mixed.xyzq", r.stdout + r.stderr,
                      "the mixed-status file's unsafe content side was not surfaced")

    # ---- Fail-open: not a git repo ----------------------------------------
    def test_fail_open_outside_a_git_repo(self):
        nongit = tempfile.TemporaryDirectory()
        self.addCleanup(nongit.cleanup)
        env = {**os.environ, "CLAUDE_PROJECT_DIR": nongit.name}
        r = subprocess.run(
            [BASH, str(COMMIT_HYGIENE)],
            input=json.dumps({"hook_event_name": "SessionEnd"}),
            capture_output=True, text=True, cwd=nongit.name, env=env,
        )
        self.assertEqual(r.returncode, 0, "guard must fail-open (exit 0) outside a git repo")

    # ---- Piece 1: clean tree -> no commit ---------------------------------
    def test_clean_tree_makes_no_commit(self):
        before = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertEqual(before, after, "guard committed on an already-clean tree")

    # ---- Piece 2: SessionStart clean-tree check surfaces the count --------
    def test_session_start_surfaces_uncommitted_count(self):
        (self.repo / "dirty1.md").write_text("x\n", encoding="utf-8")
        (self.repo / "dirty2.py").write_text("y\n", encoding="utf-8")
        r = self._run("SessionStart")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip(), "SessionStart surfaced nothing for a dirty tree")
        # must be the additionalContext envelope so it reaches session context
        payload = json.loads(r.stdout)
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("2", ctx, "clean-tree check did not report the uncommitted count")
        # SessionStart is surface-only: it must NOT create a commit
        # (a start-hook that auto-commits would be surprising).

    def test_session_start_clean_tree_is_silent(self):
        r = self._run("SessionStart")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "", "SessionStart should be silent on a clean tree")

    # ---- F-73 durability wiring: a redacted audit projection under
    # security/audit/ IS auto-committed at SessionEnd (a known-committable
    # prefix), while an unknown .json elsewhere is still surfaced, and the
    # raw gitignored records are never committed. -------------------------
    def _seed_security_dir(self):
        # `git status` collapses a brand-new UNTRACKED directory into a single
        # "?? security/" entry instead of enumerating files inside it. The wizard
        # scaffolds `security/` (with a README) at project close, before any audit
        # projection or handoff file is ever written — seed that same baseline so
        # new files below are reported by `git status` at file granularity,
        # matching real topology (mirrors test_system_control_plane_state_paths_are_committed).
        (self.repo / "security").mkdir(exist_ok=True)
        (self.repo / "security" / "README.md").write_text("sec\n", encoding="utf-8")
        _git(self.repo, "add", "security/README.md")
        _git(self.repo, "commit", "-q", "-m", "seed security/ scaffolding")

    def test_security_audit_redacted_json_is_auto_committed(self):
        self._seed_security_dir()
        (self.repo / "security" / "audit").mkdir(parents=True)
        (self.repo / "security" / "audit" / "run-1.redacted_audit.json").write_text(
            '{"audit_schema_version": "redacted_audit_projection-v1"}\n', encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("security/audit/run-1.redacted_audit.json", self._tracked(),
                      "a redacted audit projection under security/audit/ was not auto-committed")

    def test_unknown_json_elsewhere_still_surfaced_not_auto_committed(self):
        self._seed_security_dir()
        (self.repo / "security" / "audit").mkdir(parents=True)
        (self.repo / "security" / "audit" / "run-1.redacted_audit.json").write_text(
            '{"ok": true}\n', encoding="utf-8")
        (self.repo / "random_export.json").write_text('[{"pii":"z"}]\n', encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        tracked = self._tracked()
        self.assertIn("security/audit/run-1.redacted_audit.json", tracked)
        self.assertNotIn("random_export.json", tracked,
                          "an unrelated .json elsewhere must NOT be broadly auto-committed "
                          "just because security/audit/ is now a known-committable prefix")
        self.assertIn("random_export.json", r.stdout + r.stderr,
                      "the unknown .json was neither committed nor surfaced")

    def test_security_audit_data_shaped_file_still_blocked_by_safety_check(self):
        # (iii): the known-committable-prefix classification is about the AUTO-COMMIT
        # allowlist only, NOT an exemption from the safety scan -- a data-shaped file
        # dropped under security/audit/ (not a real redacted projection) must still
        # be refused, proving _matches_builtin is still consulted for this path.
        self._seed_security_dir()
        (self.repo / "security" / "audit").mkdir(parents=True)
        (self.repo / "security" / "audit" / "leak.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("security/audit/leak.csv", self._tracked(),
                          "the SAFETY CHECK was bypassed for a data-shaped file under the "
                          "new known-committable security/audit/ prefix")

    def test_raw_gitignored_security_records_never_auto_committed(self):
        # Regression guard: the new security/audit/ prefix must not widen to swallow
        # the raw, PII-bearing, gitignored records it is deliberately distinct from.
        self._seed_security_dir()
        (self.repo / ".gitignore").write_text(
            "/security/run_envelopes/\n/security/invocation_ledgers/\n"
            "/security/acceptance_receipts/\n/security/capability_acceptance_log.jsonl\n",
            encoding="utf-8")
        (self.repo / "security" / "run_envelopes").mkdir(parents=True)
        (self.repo / "security" / "run_envelopes" / "run-1.json").write_text(
            '{"raw_id": "msg-123-pii"}\n', encoding="utf-8")
        (self.repo / "security" / "invocation_ledgers").mkdir(parents=True)
        (self.repo / "security" / "invocation_ledgers" / "run-1.json").write_text(
            '{"raw_id": "msg-123-pii"}\n', encoding="utf-8")
        (self.repo / "security" / "acceptance_receipts").mkdir(parents=True)
        (self.repo / "security" / "acceptance_receipts" / "r.json").write_text(
            '{}\n', encoding="utf-8")
        (self.repo / "security" / "capability_acceptance_log.jsonl").write_text(
            '{}\n', encoding="utf-8")
        (self.repo / "security" / "audit").mkdir(parents=True)
        (self.repo / "security" / "audit" / "run-1.redacted_audit.json").write_text(
            '{"audit_schema_version": "redacted_audit_projection-v1"}\n', encoding="utf-8")
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        tracked = self._tracked()
        for raw in (
            "security/run_envelopes/run-1.json",
            "security/invocation_ledgers/run-1.json",
            "security/acceptance_receipts/r.json",
            "security/capability_acceptance_log.jsonl",
        ):
            self.assertNotIn(raw, tracked, f"raw gitignored security record was auto-committed: {raw}")
        self.assertIn("security/audit/run-1.redacted_audit.json", tracked,
                      "the redacted audit projection alongside the raw records was not committed")

    def test_session_start_surfaces_f30_already_tracked(self):
        csv = self.repo / "already.csv"
        csv.write_text("a,b\n", encoding="utf-8")
        _git(self.repo, "add", "already.csv")
        _git(self.repo, "commit", "-q", "-m", "tracked data")
        (self.repo / ".gitignore").write_text("*.csv\n", encoding="utf-8")
        r = self._run("SessionStart")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already.csv", r.stdout,
                      "SessionStart did not surface the already-tracked sensitive file")


@unittest.skipUnless(HAVE_TOOLS, "bash / git / python3 unavailable")
class CommitHygieneWiringTests(unittest.TestCase):
    """Assert the CANONICAL settings.json wires the guard into the new SessionEnd key
    and a second SessionStart entry, and that the script exists + is fail-open shaped.
    (Emission from the bundle is covered once a bundle carrying the file is cut.)"""

    def test_script_exists(self):
        self.assertTrue(COMMIT_HYGIENE.is_file(), "commit_hygiene.sh not present in canonical templates")

    def test_settings_wires_session_end_commit(self):
        s = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        hooks = s.get("hooks", {})
        se = hooks.get("SessionEnd")
        self.assertTrue(se, "settings.json has no SessionEnd key")
        self.assertIn("commit_hygiene.sh", json.dumps(se),
                      "SessionEnd does not invoke commit_hygiene.sh")

    def test_settings_wires_second_session_start_clean_tree(self):
        s = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        ss = s["hooks"]["SessionStart"]
        blob = json.dumps(ss)
        self.assertIn("commit_hygiene.sh", blob,
                      "SessionStart does not invoke the clean-tree check")
        self.assertIn("upgrade_notice.sh", blob,
                      "the additive edit dropped the existing upgrade_notice SessionStart hook")

    def test_hook_command_uses_fail_open_idiom(self):
        s = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        blob = json.dumps(s["hooks"])
        # the shared "[ -x X ] && X || true" idiom every emitted hook uses
        self.assertIn("|| true", blob, "commit-hygiene hook wiring is not fail-open")


class CommitHygieneEmittedProseTests(unittest.TestCase):
    """Emitted-prose assertions for the non-shell pieces (3/5/6 + F-24), read against
    the canonical template/skill files. Keeps the prose from silently regressing."""

    def _read(self, rel):
        return (REPO_ROOT / rel).read_text(encoding="utf-8")

    def test_pause_updates_full_bootstrap_field_set(self):
        # F-24: pause.md must update the full orientation field set, not only NEXT_RECOMMENDED_ACTION.
        t = self._read("wizard/skills/pause.md")
        for field in ("Last session", "Last agent run", "Updated"):
            self.assertIn(field, t, f"pause.md does not update bootstrap field: {field}")

    def test_pause_uses_system_clock_not_model_guess(self):
        # F-22-adjacent: the "dated today" model-guess is replaced by the system clock.
        t = self._read("wizard/skills/pause.md")
        self.assertIn("date +%Y-%m-%d", t,
                      "pause.md still relies on a model-guessed date")

    def test_orchestrator_close_updates_full_bootstrap_fields(self):
        t = self._read("wizard/agents/orchestrator_prompt.md")
        for field in ("Last session", "Last agent run"):
            self.assertIn(field, t, f"orchestrator close does not name bootstrap field: {field}")

    def test_orchestrator_close_flags_session_log_divergence(self):
        # F-82: session-close must check session_log.md against committed-to-disk /
        # git-history reality and, on a mismatch, surface it in plain language plus a
        # proposed reconciliation to the operator -- not silently absorb it.
        t = self._read("wizard/agents/orchestrator_prompt.md").lower()
        self.assertIn("phantom entry", t,
                       "orchestrator close does not name the phantom-entry divergence case")
        self.assertIn("git log", t,
                       "orchestrator close does not check session_log.md against git log")
        self.assertTrue("propose" in t or "proposed" in t or "proposes" in t,
                         "orchestrator close does not propose a reconciliation for a divergence")
        self.assertIn("plain language", t,
                       "orchestrator close does not surface a divergence in plain language")

    def test_orchestrator_close_does_not_instruct_silent_reconcile(self):
        # F-82 (negative half): the fix must forbid the old silent-absorb behavior outright,
        # not merely add a competing instruction alongside it.
        t = self._read("wizard/agents/orchestrator_prompt.md").lower()
        self.assertIn("must not rewrite, delete, merge", t,
                       "orchestrator close does not forbid silently rewriting session_log.md history")
        self.assertIn("wait for the operator's explicit decision", t,
                       "orchestrator close does not gate log-history changes on operator confirmation")

    def test_orchestrator_close_gates_new_entry_on_verified_work(self):
        # F-82: the NEW entry the orchestrator writes at close must itself be gated on
        # committed-to-disk verification, not just the pre-existing history check.
        t = self._read("wizard/agents/orchestrator_prompt.md").lower()
        self.assertIn("gate this entry", t,
                       "orchestrator close does not gate the new session_log.md entry on verification")
        self.assertTrue("only work you have verified" in t or "actually happened" in t,
                         "orchestrator close does not restrict the new entry to verified work")

    def test_next_phase_asserts_clean_baseline_before_build(self):
        # Piece 5
        t = self._read("wizard/skills/next-phase.md").lower()
        self.assertIn("clean", t)
        self.assertTrue("baseline" in t or "uncommitted" in t,
                        "next-phase does not assert a clean baseline before building")

    def test_next_phase_commits_each_phase_as_its_own_unit(self):
        # Piece 6
        t = self._read("wizard/skills/next-phase.md").lower()
        self.assertTrue("commit" in t and ("revert" in t or "own" in t or "unit" in t),
                        "next-phase does not commit each accepted phase as its own revertable unit")

    def test_cron_config_documents_self_commit_or_scratch(self):
        # Piece 3
        t = self._read("wizard/templates/agents/cron_config.md").lower()
        self.assertIn("commit", t, "cron_config does not document the self-commit convention")
        self.assertTrue("scratch" in t or "git-ignored" in t or "gitignore" in t,
                        "cron_config does not mention git-ignored scratch as the alternative")

    def test_manifest_has_positive_code_vs_data_classification(self):
        # F-30 authority: a positive committed vs never-committed classification.
        t = self._read("wizard/templates/security/gitignore_manifest.md").lower()
        self.assertTrue("never committed" in t or "never commit" in t)
        self.assertIn("already-tracked", t.replace("already tracked", "already-tracked"))

    def test_manifest_documents_committable_redacted_audit_class(self):
        # F-73 durability wiring: security/audit/ is a COMMITTED, redacted, PII-safe
        # audit projection -- plain-language, and distinct from the raw gitignored
        # records (run_envelopes/ etc.) it is projected from.
        t = self._read("wizard/templates/security/gitignore_manifest.md")
        low = t.lower()
        self.assertIn("security/audit", low,
                      "gitignore_manifest.md does not document the security/audit/ class")
        self.assertTrue("redacted" in low, "manifest does not describe the audit projection as redacted")
        self.assertTrue("committed" in low)
        self.assertTrue(
            "run_envelopes" in low or "raw" in low,
            "manifest does not contrast security/audit/ with the raw gitignored records")


if __name__ == "__main__":
    unittest.main()
