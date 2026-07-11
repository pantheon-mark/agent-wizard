"""Behavioral + content-presence tests for the shared status-line convention (F-36).

Dogfood finding F-36: an operator ran an emitted command via `!` and it silently did
nothing -- empty output, exit 0 -- and only disk inspection caught it. The fix is a
small, shared bash convention embedded in every operator-runnable emitted script: on
ANY exit path (an explicit `exit N` the script's own logic reaches, OR an exit `set -e`
forces on a line the script's author never anticipated), print exactly one unambiguous
terminal line ("RESULT: done" on success, "RESULT: failed (exit N)" on failure) and
carry a real exit code. A `!`-run command can then never finish with empty output and
exit 0 and be mistaken for having done nothing.

Like test_commit_hygiene.py / test_upgrade_notice.py, these are NOT source-string-only
assertions for the behavioral half -- they invoke the REAL canonical templates as
subprocesses (with a mock `claude` on PATH so no real API call happens) and assert the
actual stdout/stderr + exit code. The content-presence half additionally asserts the two
canonical templates carry the SAME convention block byte-for-byte, so they cannot drift
out of sync (DRY -- one shared snippet, not scattered copies).

Canonical files under test (the live/master templates a new bundle cut sources from --
see scaffold_emitter.py / agent_emitter.py module docstrings for why these two, not the
frozen per-version copies under wizard/foundation-bundles/):
  - wizard/scripts/start_session_template.sh
  - wizard/scripts/agent_invocation_template.sh
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
START_SESSION = REPO_ROOT / "wizard" / "scripts" / "start_session_template.sh"
AGENT_INVOCATION = REPO_ROOT / "wizard" / "scripts" / "agent_invocation_template.sh"

BASH = shutil.which("bash")

# The marker comments bracketing the shared convention block in both canonical files.
# Extracting by marker (rather than diffing whole files) is what lets the two templates
# differ everywhere else (different placeholders, different logic) while still proving
# the ONE shared piece they must agree on has not drifted.
_BEGIN_MARKER = "Status-line convention (F-36 fix)"
_END_MARKER = "end status-line convention"

MOCK_CLAUDE = """#!/usr/bin/env bash
# Mock `claude` CLI for status-line convention tests: prints a dummy response and
# exits $MOCK_EXIT_CODE (default 0) so a test can drive either the success or the
# stubbed-failure path without a real API call.
echo "MOCK_RESPONSE: dummy output"
exit "${MOCK_EXIT_CODE:-0}"
"""


def _mock_claude_dir():
    d = Path(tempfile.mkdtemp())
    mock = d / "claude"
    mock.write_text(MOCK_CLAUDE, encoding="utf-8")
    mock.chmod(0o755)
    return d


def _status_line_block(text, path_label):
    start = text.find(_BEGIN_MARKER)
    end = text.find(_END_MARKER)
    if start == -1 or end == -1:
        raise AssertionError(f"{path_label} is missing the status-line convention markers")
    # Walk back to the start of the comment line carrying the begin marker, and forward
    # to the end of the line carrying the end marker, so the extracted block is whole lines.
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return text[line_start:line_end]


class StatusLineContentPresenceTests(unittest.TestCase):
    """Static assertions: both canonical templates carry the convention, identically."""

    def test_both_canonical_templates_exist(self):
        self.assertTrue(START_SESSION.is_file(), f"missing {START_SESSION}")
        self.assertTrue(AGENT_INVOCATION.is_file(), f"missing {AGENT_INVOCATION}")

    def test_start_session_contains_status_line_convention(self):
        text = START_SESSION.read_text(encoding="utf-8")
        self.assertIn("RESULT: done", text)
        self.assertIn("RESULT: failed", text)
        self.assertIn("trap", text)

    def test_agent_invocation_contains_status_line_convention(self):
        text = AGENT_INVOCATION.read_text(encoding="utf-8")
        self.assertIn("RESULT: done", text)
        self.assertIn("RESULT: failed", text)
        self.assertIn("trap", text)

    def test_convention_block_is_byte_identical_across_both_templates(self):
        """DRY guard: the shared snippet must not be allowed to drift between the two
        emitted surfaces it lives in -- a one-sided fix that patches one script and
        forgets the other reintroduces exactly the F-36 hazard for whichever it missed."""
        start_text = START_SESSION.read_text(encoding="utf-8")
        invoke_text = AGENT_INVOCATION.read_text(encoding="utf-8")
        start_block = _status_line_block(start_text, "start_session_template.sh")
        invoke_block = _status_line_block(invoke_text, "agent_invocation_template.sh")
        self.assertEqual(start_block, invoke_block,
                          "the status-line convention block has drifted between the two "
                          "canonical templates -- keep them byte-identical")


@unittest.skipIf(BASH is None, "bash not available")
class StartSessionBehaviorTests(unittest.TestCase):
    """Drives the REAL start_session_template.sh as a subprocess."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name)
        (self.proj / "session_bootstrap.md").write_text("# bootstrap\n", encoding="utf-8")
        (self.proj / "CLAUDE.md").write_text("# claude config\n", encoding="utf-8")
        script_src = START_SESSION.read_text(encoding="utf-8")
        script_src = script_src.replace("{{MODEL_HIGH}}", "test-model")
        script_src = script_src.replace("{{PROJECT_NAME}}", "Test Project")
        self.script = self.proj / "start-session.sh"
        self.script.write_text(script_src, encoding="utf-8")
        self.script.chmod(0o755)
        self.mockdir = _mock_claude_dir()
        self.addCleanup(lambda: shutil.rmtree(self.mockdir, ignore_errors=True))

    def _run(self, extra_env=None, args=None):
        env = dict(os.environ)
        env["PATH"] = f"{self.mockdir}{os.pathsep}{env['PATH']}"
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [BASH, str(self.script), *(args or [])],
            cwd=str(self.proj), env=env, capture_output=True, text=True,
        )

    def test_success_prints_done_and_exits_zero(self):
        proc = self._run(extra_env={"MOCK_EXIT_CODE": "0"})
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("RESULT: done", proc.stdout)

    def test_stubbed_failure_prints_failed_and_exits_nonzero(self):
        proc = self._run(extra_env={"MOCK_EXIT_CODE": "1"})
        self.assertNotEqual(proc.returncode, 0)
        combined = proc.stdout + proc.stderr
        self.assertIn("RESULT: failed", combined)

    def test_precondition_failure_path_also_prints_failed_line(self):
        """A failure BEFORE the claude invocation (missing CLAUDE.md) is exactly the class
        of gap the trap closes -- the script's own logic already prints its specific
        error, but nothing previously guaranteed the shared terminal signal on this path."""
        (self.proj / "CLAUDE.md").unlink()
        proc = self._run()
        self.assertNotEqual(proc.returncode, 0)
        combined = proc.stdout + proc.stderr
        self.assertIn("RESULT: failed", combined)


@unittest.skipIf(BASH is None, "bash not available")
class AgentInvocationBehaviorTests(unittest.TestCase):
    """Drives the REAL agent_invocation_template.sh as a subprocess."""

    AGENT_NAME = "smoke_agent"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name)
        (self.proj / "agents" / "scripts").mkdir(parents=True)
        (self.proj / "agents" / "prompts").mkdir(parents=True)
        (self.proj / "logs").mkdir()
        (self.proj / "session_bootstrap.md").write_text("# bootstrap\n", encoding="utf-8")
        (self.proj / "project_instructions.md").write_text("# instructions\n", encoding="utf-8")
        (self.proj / "vision.md").write_text("# vision\n", encoding="utf-8")
        (self.proj / "agents" / "prompts" / f"{self.AGENT_NAME}_prompt.md").write_text(
            "# prompt\n", encoding="utf-8")

        script_src = AGENT_INVOCATION.read_text(encoding="utf-8")
        script_src = script_src.replace("{{AGENT_NAME}}", self.AGENT_NAME)
        script_src = script_src.replace("{{AGENT_MODEL}}", "test-model")
        script_src = script_src.replace("{{OUTPUT_DIRECTORY}}", "work/agent_outputs")
        script_src = script_src.replace("{{ADDITIONAL_CONTEXT_FILES}}", "")
        self.script = self.proj / "agents" / "scripts" / f"{self.AGENT_NAME}.sh"
        self.script.write_text(script_src, encoding="utf-8")
        self.script.chmod(0o755)

        self.mockdir = _mock_claude_dir()
        self.addCleanup(lambda: shutil.rmtree(self.mockdir, ignore_errors=True))

    def _run(self, extra_env=None):
        env = dict(os.environ)
        env["PATH"] = f"{self.mockdir}{os.pathsep}{env['PATH']}"
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [BASH, str(self.script), "smoke001"],
            cwd=str(self.proj), env=env, capture_output=True, text=True,
        )

    def test_success_prints_done_and_exits_zero(self):
        proc = self._run(extra_env={"MOCK_EXIT_CODE": "0"})
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("RESULT: done", proc.stdout)

    def test_stubbed_failure_prints_failed_and_exits_nonzero(self):
        """The brief's named acceptance case: 'drive a stubbed failure' -- the mock claude
        exits nonzero, simulating a real agent invocation that errors out."""
        proc = self._run(extra_env={"MOCK_EXIT_CODE": "1"})
        self.assertNotEqual(proc.returncode, 0)
        combined = proc.stdout + proc.stderr
        self.assertIn("RESULT: failed", combined)
        # The pre-existing failure bookkeeping must still work alongside the new guarantee.
        self.assertTrue((self.proj / "logs" / "error_log.md").exists())

    def test_precondition_failure_path_also_prints_failed_line(self):
        """A failure BEFORE the claude invocation (missing prompt file) is exactly the
        class of gap the trap closes."""
        (self.proj / "agents" / "prompts" / f"{self.AGENT_NAME}_prompt.md").unlink()
        proc = self._run()
        self.assertNotEqual(proc.returncode, 0)
        combined = proc.stdout + proc.stderr
        self.assertIn("RESULT: failed", combined)


if __name__ == "__main__":
    unittest.main()
