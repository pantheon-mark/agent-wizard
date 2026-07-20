"""Cluster-C isolation validation — a composition regression net proving the
command manifest, the settings.json allow/ask rules, the PreToolUse
auto-approve hook, the read-only `bulk-verify` command, and the manual's
trust-onboarding step all cohere as ONE system, not four independently
-tested parts that happen to agree today.

This is deliberately deterministic-only. The workspace-trust-dialog /
settings-allowlist RUNTIME behavior (how Claude Code itself gates a command
before and after the operator accepts the trust dialog) is inherently a
harness-interaction and is validated in the real-operator run, not here — see
docs/superpowers/plans/2026-07-19-cut1.1-C.md, "Isolation validation (after
B, before E)".

Each per-task behavior already has its own dedicated test module (the
manifest's classification rules, the settings/hook content and subprocess
behavior including the command-smuggling guard, the bulk-verify reconciliation
logic, and the manual's onboarding wording) — this module does not repeat that
coverage. It composes the REAL, already-landed artifacts across the seam
those per-task tests do not cross:

  1. Single-source coherence: for every command the manifest classifies,
     settings.json's allow/ask rules and the auto-approve hook's live
     subprocess decision AGREE with the manifest and with each other. No
     command may be eligible on one surface and not another.
  2. The `bulk-verify` command specifically coheres end-to-end: manifest
     classification -> settings allow-rule -> hook auto-approval -> the
     module's own read-only-by-construction proof.
  3. The two proven command-smuggling payloads (a newline appended after an
     eligible prefix; a backtick command substitution) still defer under the
     composed real artifacts, so a future manifest or settings edit cannot
     silently reopen a closed gap without this net catching it.
  4. The manual's guided trust-onboarding step is present and still avoids
     instructing permission-mode reasoning (a light re-assertion; the full
     wording contract lives in its own dedicated test module).

Stdlib unittest; pip-install-free. Mirrors the existing per-task test
modules' subprocess-invocation convention (temp CLAUDE_PROJECT_DIR carrying a
real copy of the manifest at the exact path the hook expects it).
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
WIZARD_ROOT = REPO_ROOT / "wizard"
AUTO_APPROVE_GATE = WIZARD_ROOT / "templates" / "claude_config" / "auto_approve_gate.sh"
SETTINGS_JSON = WIZARD_ROOT / "templates" / "claude_config" / "settings.json"
MANUAL_PATH = WIZARD_ROOT / "templates" / "root" / "manual.md"
AGENTS_LIB = WIZARD_ROOT / "agents" / "lib"
REAL_MANIFEST = AGENTS_LIB / "external_write" / "command_manifest.py"
BULK_VERIFY_MODULE_PATH = str(AGENTS_LIB / "external_write" / "bulk_verify.py")

BASH = shutil.which("bash")
HAVE_TOOLS = bool(BASH) and bool(shutil.which("python3"))

sys.path.insert(0, str(AGENTS_LIB))
from external_write import command_manifest as cm  # noqa: E402
from external_write.scan import scan_paths  # noqa: E402


def _install_real_manifest(proj_dir: Path) -> None:
    """Copy the real, landed command_manifest.py into `proj_dir` at the exact
    relative path the hook expects it (agents/lib/external_write/), the same
    convention the manifest's and hook's own dedicated tests use — this net
    exercises the real artifact, never a hand-built stand-in."""
    dest_dir = proj_dir / "agents" / "lib" / "external_write"
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "command_manifest.py").write_text(
        REAL_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8"
    )


def _run_hook(proj_dir: Path, command: str):
    """Invoke the real auto_approve_gate.sh as a subprocess against `proj_dir`
    with a synthetic Bash PreToolUse event, and return the decision
    ("allow" or None-for-defer)."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(proj_dir)
    event = {"tool_name": "Bash", "tool_input": {"command": command}}
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
        parsed = json.loads(out)  # any printed output must be valid hook JSON
        decision = parsed.get("hookSpecificOutput", {}).get("permissionDecision")
    return res.returncode, decision, out


def _realistic_command_for(entry) -> str:
    """A concrete, hook-safe-character invocation string for a manifest
    entry. Read-only entries' `command_prefix` is already a literal, safe
    invocation. The live-write entry's `command_prefix` carries a
    "<capability>" placeholder (its concrete script name is decided per
    capability at scaffold time, per command_manifest.py's own docstring) —
    substitute a representative stand-in name, the same shape the settings
    /hook behavioral tests already exercise, so this is a genuine
    safe-character bash invocation rather than a template string."""
    return entry.command_prefix.replace("<capability>", "some_capability")


# ---------------------------------------------------------------------------
# 1. Single-source coherence: manifest <-> settings.json <-> hook decision
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAVE_TOOLS, "bash and/or python3 unavailable")
class ManifestSettingsHookCoherenceTests(unittest.TestCase):
    """The Cluster-C architecture's central claim: the manifest is the SINGLE
    source that settings.json's allow/ask rules and the auto-approve hook's
    live decision both read from — so for every command they all agree, and
    none is eligible on one surface while blocked (or vice versa) on
    another."""

    @classmethod
    def setUpClass(cls):
        cls.settings = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        cls._tmp = tempfile.TemporaryDirectory()
        cls.proj = Path(cls._tmp.name)
        _install_real_manifest(cls.proj)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_every_read_only_command_is_allowed_and_settings_listed_and_hook_approved(self):
        allow_list = self.settings["permissions"]["allow"]
        eligible_entries = [e for e in cm.BASELINE_COMMANDS if cm.is_allowlist_eligible(e)]
        self.assertTrue(eligible_entries, "expected at least one allowlist-eligible command")
        for entry in eligible_entries:
            with self.subTest(command=entry.name):
                expected_allow_entry = f"Bash({entry.command_prefix} *)"
                self.assertIn(
                    expected_allow_entry, allow_list,
                    f"{entry.name!r} is manifest-eligible but missing from "
                    "settings.json permissions.allow",
                )
                _, decision, _ = _run_hook(self.proj, entry.command_prefix)
                self.assertEqual(
                    decision, "allow",
                    f"{entry.name!r} is manifest-eligible and settings-allowed "
                    "but the hook did not auto-approve it",
                )

    def test_every_live_write_command_is_never_allowed_and_never_hook_approved(self):
        allow_text = json.dumps(self.settings["permissions"]["allow"])
        ask_list = self.settings["permissions"]["ask"]
        live_write_entries = [e for e in cm.BASELINE_COMMANDS if not cm.is_allowlist_eligible(e)]
        self.assertTrue(live_write_entries, "expected at least one live-write command")
        for entry in live_write_entries:
            with self.subTest(command=entry.name):
                self.assertNotIn(
                    entry.command_prefix, allow_text,
                    f"{entry.name!r} is a live-write command but its prefix "
                    "appears in settings.json permissions.allow",
                )
                self.assertTrue(
                    ask_list,
                    "permissions.ask must not be empty while a live-write "
                    "command exists in the manifest",
                )
                _, decision, out = _run_hook(self.proj, _realistic_command_for(entry))
                self.assertIsNone(
                    decision,
                    f"{entry.name!r} is a live-write command but the hook "
                    "auto-approved it",
                )
                self.assertEqual(out, "")


# ---------------------------------------------------------------------------
# 2. bulk-verify end-to-end coherence
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAVE_TOOLS, "bash and/or python3 unavailable")
class BulkVerifyComposedCoherenceTests(unittest.TestCase):
    """`bulk-verify` specifically, composed across the manifest, the settings
    allow-rule, the hook's live decision, and the module's own
    read-only-by-construction proof (reusing the same scan_paths shape its
    own dedicated test module uses)."""

    @classmethod
    def setUpClass(cls):
        cls.settings = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        cls._tmp = tempfile.TemporaryDirectory()
        cls.proj = Path(cls._tmp.name)
        _install_real_manifest(cls.proj)
        cls.entry = cm.find_command("bulk-verify")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_bulk_verify_is_manifest_read_only_and_eligible(self):
        self.assertIsNotNone(self.entry)
        self.assertEqual(self.entry.command_class, cm.READ_ONLY)
        self.assertTrue(cm.is_allowlist_eligible(self.entry))

    def test_bulk_verify_is_covered_by_the_settings_allow_rule(self):
        allow_list = self.settings["permissions"]["allow"]
        self.assertIn(f"Bash({self.entry.command_prefix} *)", allow_list)

    def test_bulk_verify_is_auto_approved_by_the_hook(self):
        _, decision, _ = _run_hook(self.proj, self.entry.command_prefix)
        self.assertEqual(
            decision, "allow",
            "bulk-verify is manifest-eligible and settings-allowed but the "
            "hook did not auto-approve it",
        )

    def test_bulk_verify_module_is_read_only_by_construction(self):
        # Same proof shape as the module's own dedicated test module: a clean
        # AST bypass scan is the deterministic, build-time confirmation that
        # the classification the manifest asserts is actually true of the
        # code, not merely a label.
        violations = scan_paths([BULK_VERIFY_MODULE_PATH])
        self.assertEqual(violations, [], violations)


# ---------------------------------------------------------------------------
# 3. Command-smuggling guard holds under composition (regression)
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAVE_TOOLS, "bash and/or python3 unavailable")
class SmuggleGuardCompositionRegressionTests(unittest.TestCase):
    """Re-asserts the two proven command-smuggling payloads — a newline
    appended after an eligible read-only prefix, and a backtick command
    substitution — still defer (no auto-approve) against the real, composed
    manifest + hook, so a future manifest or settings.json edit cannot
    silently reopen a previously-closed smuggling path without this net
    catching it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        _install_real_manifest(self.proj)

    def tearDown(self):
        self._tmp.cleanup()

    def test_newline_smuggled_command_after_eligible_prefix_still_defers(self):
        _, decision, out = _run_hook(
            self.proj,
            "python3 agents/lib/external_write/scan.py\nrm -rf /HOME",
        )
        self.assertIsNone(
            decision,
            "regression: newline-smuggled command after an eligible prefix "
            "was auto-approved",
        )
        self.assertEqual(out, "")

    def test_backtick_command_substitution_still_defers(self):
        _, decision, out = _run_hook(
            self.proj,
            "python3 agents/lib/external_write/scan.py `rm -rf /tmp/x`",
        )
        self.assertIsNone(
            decision,
            "regression: backtick command substitution after an eligible "
            "prefix was auto-approved",
        )
        self.assertEqual(out, "")


# ---------------------------------------------------------------------------
# 4. Trust onboarding presence (light re-assertion)
# ---------------------------------------------------------------------------

class TrustOnboardingPresenceTests(unittest.TestCase):
    """Light re-assertion that the manual's guided trust-onboarding step is
    present and still avoids permission-mode reasoning. The full wording
    contract (framing, convenience-not-safety language, exact phrasing) is
    covered by its own dedicated test module; this is a coherence check that
    the step has not silently disappeared or regressed as part of this
    composed net."""

    @classmethod
    def setUpClass(cls):
        assert MANUAL_PATH.is_file(), f"expected {MANUAL_PATH} to exist"
        cls.text = MANUAL_PATH.read_text(encoding="utf-8")

    def test_names_the_trust_dialog_acceptance_phrase(self):
        self.assertIn("Yes, I trust this folder", self.text)

    def test_never_instructs_shift_tab_or_permission_mode_reasoning(self):
        self.assertNotRegex(self.text, r"[Ss]hift[\s+-]?[Tt]ab")
        self.assertNotRegex(self.text, r"permission mode")
        self.assertNotRegex(self.text, r"bypass\s*permissions?")


if __name__ == "__main__":
    unittest.main()
