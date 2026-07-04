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

    # ---- Piece 4: positive — code/docs/state committed --------------------
    def test_code_docs_state_are_committed_on_session_end(self):
        (self.repo / "notes.md").write_text("doc\n", encoding="utf-8")
        (self.repo / "run.py").write_text("print(1)\n", encoding="utf-8")
        (self.repo / "state.json").write_text('{"a":1}\n', encoding="utf-8")
        before = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        r = self._run("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(before, after, "SessionEnd made no commit for outstanding work")
        tracked = self._tracked()
        for f in ("notes.md", "run.py", "state.json"):
            self.assertIn(f, tracked, f"{f} (code/docs/state) was not committed")

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


if __name__ == "__main__":
    unittest.main()
