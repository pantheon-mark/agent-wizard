"""Behavioral (script-level) tests for the two safety hooks shipped to every
emitted operator system: the receipt-gate PreToolUse hook and the context-monitor
Stop-hook idle guard.

These are negative / anti-overfit tests: instead of re-asserting the script SOURCE
contains the right strings (already covered by the scaffold-emitter tests), they
INVOKE the real source scripts as subprocesses, feed them synthetic hook-event JSON
on stdin with CLAUDE_PROJECT_DIR pointed at a temp dir, and assert the runtime
DECISION. This proves the safety properties actually hold end-to-end:

receipt_gate.sh:
  - a benign local action is ungated (no decision printed, exit 0);
  - a high-risk action with NO / EXPIRED / WRONG-SCHEMA receipt forces "ask";
  - a high-risk action with a FRESH VALID receipt is allowed;
  - an MCP write tool is classified high-risk by tool_name alone.

context_monitor.sh:
  - on a Stop event with stop_hook_active true, the idle guard does NOT block,
    even with a phase awaiting acceptance (loop-safety).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RECEIPT_GATE = REPO_ROOT / "wizard" / "templates" / "claude_config" / "receipt_gate.sh"
CONTEXT_MONITOR = REPO_ROOT / "wizard" / "templates" / "claude_config" / "context_monitor.sh"

BASH = shutil.which("bash")
HAVE_TOOLS = bool(BASH) and bool(shutil.which("python3"))


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_receipt(created_at=None, expires_after_seconds=900, schema="prewrite-receipt-v1"):
    """A fully-formed, fresh pre-write receipt matching the prewrite-receipt-v1 shape
    documented in operating_discipline.md."""
    return {
        "schema": schema,
        "action_class": "external-communications",
        "target_id": "sheet:abc123",
        "operation": "update cells A1:A2",
        "backup_ref": "agents/handoffs/backup_abc.json",
        "verifications": [
            {"claim": "share scope is editor", "status": "verified", "evidence": "raw cli output"}
        ],
        "operator_confirmation": "yes, send it",
        "created_at": created_at if created_at is not None else _now_iso(),
        "expires_after_seconds": expires_after_seconds,
    }


@unittest.skipUnless(HAVE_TOOLS, "bash and/or python3 unavailable")
class ReceiptGateBehaviorTests(unittest.TestCase):
    """Invoke the real receipt_gate.sh as a subprocess with synthetic hook JSON."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_receipt(self, receipt):
        d = self.proj / "agents" / "handoffs"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".prewrite_receipt.json").write_text(
            receipt if isinstance(receipt, str) else json.dumps(receipt),
            encoding="utf-8",
        )

    def _run(self, event):
        """Run the gate with `event` (a dict) as the hook stdin JSON; return (exit, decision)
        where decision is the parsed permissionDecision or None when nothing was printed."""
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.proj)
        res = subprocess.run(
            [BASH, str(RECEIPT_GATE)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        out = res.stdout.strip()
        decision = None
        if out:
            parsed = json.loads(out)  # any printed output MUST be valid hook JSON
            decision = parsed.get("hookSpecificOutput", {}).get("permissionDecision")
        return res.returncode, decision, out

    def test_benign_ls_is_ungated(self):
        # A benign local read must print nothing and exit 0 — never stall the session.
        code, decision, out = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
        )
        self.assertEqual(code, 0)
        self.assertEqual(out, "", "benign action emitted a decision (should be ungated)")
        self.assertIsNone(decision)

    def test_highrisk_no_receipt_asks(self):
        # curl with no receipt on disk -> the gate must force the operator dialog.
        code, decision, _ = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "curl https://api.example.com"}}
        )
        self.assertEqual(code, 0)
        self.assertEqual(decision, "ask",
                         "high-risk action with no receipt was not gated to 'ask'")

    def test_highrisk_fresh_valid_receipt_allows(self):
        # A fresh, valid, complete receipt for this high-risk action -> allow.
        self._write_receipt(_valid_receipt())
        code, decision, _ = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "curl https://api.example.com"}}
        )
        self.assertEqual(code, 0)
        self.assertEqual(decision, "allow",
                         "fresh valid receipt did not allow the high-risk action")

    def test_highrisk_expired_receipt_asks(self):
        # created_at far in the past so created_at + ttl < now -> expired -> ask.
        old = (datetime.now(timezone.utc) - timedelta(seconds=10000)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        self._write_receipt(_valid_receipt(created_at=old, expires_after_seconds=900))
        code, decision, _ = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "curl https://api.example.com"}}
        )
        self.assertEqual(code, 0)
        self.assertEqual(decision, "ask", "expired receipt did not fall back to 'ask'")

    def test_highrisk_wrong_schema_receipt_asks(self):
        # A receipt whose schema is not prewrite-receipt-v1 is invalid -> ask.
        self._write_receipt(_valid_receipt(schema="prewrite-receipt-v0"))
        code, decision, _ = self._run(
            {"tool_name": "Bash", "tool_input": {"command": "curl https://api.example.com"}}
        )
        self.assertEqual(code, 0)
        self.assertEqual(decision, "ask", "wrong-schema receipt did not fall back to 'ask'")

    def test_mcp_write_tool_no_receipt_asks(self):
        # An MCP write verb is classified high-risk by tool_name ALONE (benign args).
        code, decision, _ = self._run(
            {"tool_name": "mcp__sheets__update_cells",
             "tool_input": {"range": "A1", "values": [["x"]]}}
        )
        self.assertEqual(code, 0)
        self.assertEqual(decision, "ask",
                         "MCP write tool was not classified high-risk / not gated to 'ask'")

    # ------------------------------------------------------------------ #
    # Classification must be by ACTION SHAPE, not by scanning the prose
    # content of a local edit. These are the live false-positives an earlier
    # over-broad substring regex produced (everyday words like "firm"/"High"
    # tripped rm/gh), plus the must-gate cases that prove the real protection
    # still fires.
    # ------------------------------------------------------------------ #

    def _assert_ungated(self, event, why):
        code, decision, out = self._run(event)
        self.assertEqual(code, 0)
        self.assertEqual(out, "", f"benign action emitted a decision (should be ungated): {why}")
        self.assertIsNone(decision, why)

    def _assert_asks(self, event, why):
        code, decision, _ = self._run(event)
        self.assertEqual(code, 0)
        self.assertEqual(decision, "ask", why)

    # --- must NOT gate: local edits whose CONTENT contains danger substrings --- #

    def test_edit_markdown_with_firm_and_high_is_ungated(self):
        # The live regression: "fi-rm", "Hi-gh", "throu-gh" tripped rm/gh substrings.
        self._assert_ungated(
            {"tool_name": "Edit", "tool_input": {
                "file_path": "audit_log.md",
                "old_string": "x",
                "new_string": "confirm with the firm | High | look through the docs"}},
            "Edit of markdown containing firm/High/through must never gate")

    def test_write_markdown_with_danger_words_is_ungated(self):
        self._assert_ungated(
            {"tool_name": "Write", "tool_input": {
                "file_path": "prep_briefing.md",
                "content": "Steps: confirm the sale, review aws billing notes, DELETE this draft line"}},
            "Write of a local markdown file must never gate on its prose")

    # --- must NOT gate: Bash where danger words live INSIDE quoted strings --- #

    def test_bash_echo_firm_in_string_is_ungated(self):
        self._assert_ungated(
            {"tool_name": "Bash", "tool_input": {"command": 'echo "confirm the firm sale"'}},
            "echo of a string containing 'firm' is not a destructive command")

    def test_bash_quoted_operator_with_rm_in_string_is_ungated(self):
        # gemini's strongest case: naive operator-splitting would extract 'rm' here.
        self._assert_ungated(
            {"tool_name": "Bash", "tool_input": {"command": 'git commit -m "fix bug ; rm old files"'}},
            "rm inside a quoted commit message is not a command")

    def test_bash_aws_read_subcommand_is_ungated(self):
        self._assert_ungated(
            {"tool_name": "Bash", "tool_input": {"command": "aws s3 ls s3://bucket"}},
            "aws read subcommand (ls) must not gate")

    def test_bash_gh_read_subcommand_is_ungated(self):
        self._assert_ungated(
            {"tool_name": "Bash", "tool_input": {"command": "gh issue list"}},
            "gh read subcommand (issue list) must not gate")

    def test_bash_plain_git_push_is_ungated(self):
        self._assert_ungated(
            {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}},
            "plain fast-forward git push is reversible -> not gated")

    def test_mcp_read_tool_is_ungated(self):
        self._assert_ungated(
            {"tool_name": "mcp__sheets__get_values", "tool_input": {"range": "A1:B2"}},
            "MCP read verb (get) must not gate")

    # --- must GATE: real irreversible / outgoing actions (no receipt) --- #

    def test_bash_rm_rf_asks(self):
        self._assert_asks(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf build/"}},
            "rm -rf must gate")

    def test_bash_semicolon_rm_asks(self):
        self._assert_asks(
            {"tool_name": "Bash", "tool_input": {"command": "echo done; rm important.txt"}},
            "rm as a command after ; must gate")

    def test_bash_find_delete_asks(self):
        self._assert_asks(
            {"tool_name": "Bash", "tool_input": {"command": "find . -name '*.tmp' -delete"}},
            "find -delete must gate")

    def test_bash_find_exec_rm_asks(self):
        self._assert_asks(
            {"tool_name": "Bash", "tool_input": {"command": "find . -name '*.bak' -exec rm {} ;"}},
            "find -exec rm must gate")

    def test_bash_xargs_rm_asks(self):
        self._assert_asks(
            {"tool_name": "Bash", "tool_input": {"command": "ls *.tmp | xargs rm"}},
            "xargs rm must gate")

    def test_bash_aws_write_subcommand_asks(self):
        self._assert_asks(
            {"tool_name": "Bash", "tool_input": {"command": "aws s3 rm s3://bucket/key"}},
            "aws write subcommand (rm) must gate")

    def test_bash_gh_write_subcommand_asks(self):
        self._assert_asks(
            {"tool_name": "Bash", "tool_input": {"command": "gh release create v1.0"}},
            "gh write subcommand (release create) must gate")

    def test_bash_git_push_force_asks(self):
        self._assert_asks(
            {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}},
            "git push --force rewrites remote history -> must gate")

    def test_mcp_send_tool_asks(self):
        self._assert_asks(
            {"tool_name": "mcp__gmail__send_message", "tool_input": {"to": "a@b.com"}},
            "MCP send verb must gate")

    def test_mcp_unknown_verb_asks(self):
        self._assert_asks(
            {"tool_name": "mcp__connector__frobnicate", "tool_input": {}},
            "unknown MCP verb on an external connector must gate (D5)")


@unittest.skipUnless(HAVE_TOOLS, "bash and/or python3 unavailable")
class ContextMonitorLoopSafetyTests(unittest.TestCase):
    """Invoke the real context_monitor.sh Stop-hook path as a subprocess and prove the
    stop_hook_active loop-safety guard prevents a re-block."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        # A ledger with a phase that IS awaiting acceptance ('built', not yet accepted):
        # without the loop-safe guard this would otherwise produce a block decision.
        (self.proj / "build_progress.md").write_text(
            "# Build Progress Ledger\n\n"
            "| Phase | Capability | State | Layer-A | Layer-B | Open | Deferred | Date |\n"
            "|-------|-----------|-------|---------|---------|------|----------|------|\n"
            "| 1 | ingest | built | - | - | - | - | 2026-01-01 |\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, event):
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.proj)
        res = subprocess.run(
            [BASH, str(CONTEXT_MONITOR)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        return res.returncode, res.stdout

    def test_stop_hook_active_does_not_block(self):
        # stop_hook_active == true: Claude Code is already continuing from a prior block.
        # The guard MUST NOT block again (else it wedges the session in a continue loop).
        code, out = self._run({"hook_event_name": "Stop", "stop_hook_active": True})
        self.assertEqual(code, 0)
        self.assertNotIn("block", out.lower(),
                         "idle guard re-blocked while stop_hook_active was true (loop unsafe)")

    def test_stop_without_active_flag_blocks_pending_phase(self):
        # Control case proving the guard is actually armed: a FIRST Stop (stop_hook_active
        # absent/false) with a pending phase DOES block — so the no-op above is the guard
        # being loop-safe, not the guard being inert.
        code, out = self._run({"hook_event_name": "Stop"})
        self.assertEqual(code, 0)
        self.assertIn("block", out.lower(),
                      "idle guard failed to block a first Stop with a phase awaiting acceptance")
        payload = json.loads(out.strip())
        self.assertEqual(payload.get("decision"), "block")


if __name__ == "__main__":
    unittest.main()
