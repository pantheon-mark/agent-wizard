"""Tests for the base-scaffold emitter (stdlib unittest; pip-install-free).

Emits the operator-project base scaffold (root/ + operational dirs) from a
validated EmissionPlan against the REAL wizard/templates into a temp staging
dir, and asserts: the core scaffold files exist, the model-tier map resolves to
RESOLVED model strings (not tier names) in project_instructions.md and
start-session.sh, placeholder exhaustion (no {{KEY}} survives), the foundation
docs / agents runtime / wizard-internal _index.md / corpus-owned rules_library
are NOT emitted by the scaffold layer, and start-session.sh is executable.
"""

import stat
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scaffold_emitter import emit_scaffold  # noqa: E402
from emission_plan import load_contract, default_contract_path, validate_emission_plan  # noqa: E402
from generator import PLACEHOLDER_RE  # noqa: E402
from test_emission_plan import _valid_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


class ScaffoldEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _emit(self, plan_dict=None):
        plan = validate_emission_plan(plan_dict or _valid_plan(), self.contract)
        self._tmp = tempfile.TemporaryDirectory()
        staging = Path(self._tmp.name)
        written = emit_scaffold(plan, staging, REPO_ROOT)
        return staging, written

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_emits_core_root_files(self):
        staging, _ = self._emit()
        for rel in ["CLAUDE.md", "project_instructions.md", "session_bootstrap.md",
                    "pending_decisions.md", "manual.md", ".gitignore", "start-session.sh"]:
            self.assertTrue((staging / rel).exists(), f"missing scaffold file: {rel}")

    def test_operating_discipline_doc_emitted(self):
        staging, _ = self._emit()
        p = staging / "operating_discipline.md"
        self.assertTrue(p.exists(), "operating_discipline.md not emitted")
        text = p.read_text()
        for anchor in ["Verified", "Not verified", "Not observable",
                       "UNVERIFIABLE_LOCALLY", "co-protected-workflows.md", "narration"]:
            self.assertIn(anchor, text, f"operating_discipline.md missing anchor: {anchor}")

    def test_operating_discipline_referenced(self):
        staging, _ = self._emit()
        for rel in ["CLAUDE.md", "project_instructions.md", "session_bootstrap.md"]:
            self.assertIn("operating_discipline.md", (staging / rel).read_text(),
                          f"{rel} does not reference operating_discipline.md")

    def test_emits_operational_dir_files(self):
        staging, _ = self._emit()
        for rel in ["logs/audit_log.md", "logs/session_log.md", "logs/error_log.md",
                    "quality/validation_gate_config.md", "work/work_queue.md",
                    "docs/document_impact_map.md", "security/credentials_registry.md"]:
            self.assertTrue((staging / rel).exists(), f"missing operational file: {rel}")

    def test_model_tier_map_resolves_to_model_strings(self):
        # The scaffold model placeholders ({{MODEL_HIGH}} etc.) carry RESOLVED model
        # strings (for the operator's --model flag + the project_instructions tier map),
        # NOT the bare tier names.
        staging, _ = self._emit()
        pi = (staging / "project_instructions.md").read_text()
        self.assertIn("model-high", pi)
        self.assertIn("model-standard", pi)
        self.assertIn("model-fast", pi)
        sess = (staging / "start-session.sh").read_text()
        self.assertIn('MODEL="model-high"', sess)
        self.assertNotIn('MODEL="high"', sess)  # NOT the bare tier name

    def test_placeholder_exhaustion(self):
        staging, written = self._emit()
        for p in written:
            if p.is_dir():
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            leftover = PLACEHOLDER_RE.findall(text)
            self.assertEqual(leftover, [], f"unsubstituted placeholder(s) in {p.name}: {leftover}")

    def test_project_name_substituted(self):
        staging, _ = self._emit()
        self.assertIn("demo", (staging / "CLAUDE.md").read_text())

    def test_excludes_foundation_docs_agents_indexes_and_rules_library(self):
        # Foundation docs (generator/Phase 4), agents runtime (agent_emitter/Phase 1B),
        # wizard-internal _index.md catalogs, and the corpus-owned rules_library are NOT
        # emitted by the scaffold layer.
        staging, _ = self._emit()
        self.assertFalse((staging / "documents").exists(), "scaffold must not emit foundation docs")
        self.assertFalse((staging / "vision.md").exists())
        self.assertFalse((staging / "agents").exists(), "scaffold must not emit the agents runtime")
        self.assertFalse((staging / "quality/rules_library.md").exists(),
                         "rules_library.md is corpus-owned; scaffold must not emit it")
        # no wizard-internal _index.md catalogs anywhere in the emitted tree
        indexes = list(staging.rglob("_index.md"))
        self.assertEqual(indexes, [], f"scaffold emitted wizard-internal _index.md catalogs: {indexes}")

    def test_start_session_is_executable(self):
        staging, _ = self._emit()
        sess = staging / "start-session.sh"
        self.assertTrue(sess.stat().st_mode & stat.S_IXUSR, "start-session.sh is not executable")

    def test_claude_config_emitted_with_statusline_and_context_hook(self):
        # F-04: every emitted operator system ships a .claude/ config so it can SEE its
        # actual context (the operator via the statusline, the session via the context-
        # monitor hook) instead of guessing — making the CLAUDE.md context-integrity
        # protocol runnable on real data.
        import json as _json
        staging, _ = self._emit()
        settings_path = staging / ".claude" / "settings.json"
        self.assertTrue(settings_path.exists(), ".claude/settings.json not emitted")
        settings = _json.loads(settings_path.read_text())
        self.assertIn("statusLine", settings, "settings.json has no statusLine")
        hooks = settings.get("hooks", {})
        self.assertTrue(
            any("context_monitor" in _json.dumps(hooks).lower() for _ in [0]),
            "settings.json hooks do not wire the context monitor",
        )
        for script in ("statusline.sh", "context_monitor.sh"):
            sp = staging / ".claude" / script
            self.assertTrue(sp.exists(), f".claude/{script} not emitted")
            self.assertTrue(sp.stat().st_mode & stat.S_IXUSR, f".claude/{script} not executable")
        # The actual context signal comes from Claude Code's built-in statusline JSON
        # field (portable to any project), not an AWB-specific source.
        statusline = (staging / ".claude" / "statusline.sh").read_text()
        self.assertIn("used_percentage", statusline)
        # The statusline also surfaces the plan usage limits (5h + 7d) — load-bearing
        # for a non-technical operator on a budget.
        self.assertIn("five_hour", statusline, "statusline omits the 5h usage limit")
        self.assertIn("seven_day", statusline, "statusline omits the 7d usage limit")

    def test_stop_hook_idle_guard_present(self):
        staging, _ = self._emit()
        text = (staging / ".claude" / "context_monitor.sh").read_text()
        self.assertIn("stop_hook_active", text)   # loop-safe guard present
        self.assertIn("build_progress.md", text)  # checks pending acceptance

    def test_settings_self_protect_permissions_and_receipt_gate(self):
        # The receipt-gate PreToolUse hook + anti-self-bypass deny-rules
        # (project-scope, honestly bounded) must be present in the emitted settings.
        import json as _json
        staging, _ = self._emit()
        s = _json.loads((staging / ".claude" / "settings.json").read_text())
        self.assertIn("receipt_gate.sh", _json.dumps(s.get("hooks", {})),
                      "PreToolUse does not invoke receipt_gate.sh")
        perms = s.get("permissions", {})
        deny = perms.get("deny", [])
        self.assertIn("Edit(.claude/**)", deny, "missing .claude Edit deny-rule")
        self.assertIn("Write(.claude/**)", deny, "missing .claude Write deny-rule")
        self.assertEqual(perms.get("disableBypassPermissionsMode"), "disable")

    def test_receipt_gate_script_emitted_executable(self):
        import os
        staging, _ = self._emit()
        sp = staging / ".claude" / "receipt_gate.sh"
        self.assertTrue(sp.exists(), "receipt_gate.sh not emitted")
        self.assertTrue(os.access(sp, os.X_OK), "receipt_gate.sh not executable")

    def test_start_session_launches_with_orientation_kickoff_not_bare(self):
        # A bare `claude` launch sits at a silent prompt — a non-technical operator who
        # runs ./start-session.sh sees "nothing happened" and the CLAUDE.md
        # read-at-start-and-act sequence never fires (Claude Code takes no turn until the
        # user types). The launch must seed a kickoff prompt so the session orients on its
        # first turn and tells the operator the next step without them knowing what to type.
        import re
        staging, _ = self._emit()
        sess = (staging / "start-session.sh").read_text()
        # Tolerate flags between --model and --effort (e.g. --fallback-model for the 1M
        # high tier) — the captured tail after `--effort high` must still be the kickoff prompt.
        m = re.search(r'^\s*claude --model "\$MODEL".*?--effort high(.*)$', sess, re.M)
        self.assertIsNotNone(m, "could not find the claude launch line")
        self.assertTrue(
            m.group(1).strip(),
            "start-session.sh launches `claude` with no kickoff prompt — the operator faces "
            "a silent prompt and the startup-sequence orientation never fires",
        )
        low = sess.lower()
        # The kickoff must produce a gentle, plain-language lay of the land that leads to a
        # SINGLE next step — not a technical orientation dump or a menu of internal options
        # (the over-asking a fresh non-technical operator hit).
        self.assertTrue(any(k in low for k in ("next step", "what to do", "next action")),
                        "kickoff does not orient toward a next step")
        self.assertIn("plain", low, "kickoff does not require plain (non-technical) language")
        self.assertIn("silently", low, "kickoff does not orient silently (it narrates internals)")
        self.assertIn("menu", low, "kickoff does not forbid presenting a menu of options")


class FoundationOnlyDisciplineLayerTests(unittest.TestCase):
    """Anti-overfit: the operating-discipline layer must be present even for a
    foundation-only system that defines NO agents and does NO high-risk writes.

    The receipt gate / R2 sequence stay dormant for such a system (no agents to run
    them), but the doctrine doc, the ceremony-maturity table, and the operator skills
    must still ship — the layer is not contingent on the system having a high-risk
    capability. This builds a real foundation-only plan through the assembler (the
    genuine path that seeds the ceremony rows), not a hand-tweaked dict, so the test
    cannot pass by accident on a foundation_doc_inputs default."""

    @classmethod
    def setUpClass(cls):
        from build_intent import BuildIntent
        from scaffold_plan import load_scaffold_plan
        from corpus_loader import load_corpus_pack
        from emission_plan_assembler import assemble_emission_plan
        from test_emission_plan_assembler import _dr  # foundation-doc record builder

        sp = load_scaffold_plan("markdown-CC")
        corpus = load_corpus_pack()
        # FOUNDATION_ONLY_MODE true + zero agents == a system with no high-risk capability.
        bi = BuildIntent(derived_record=_dr(overrides={"FOUNDATION_ONLY_MODE": "true"}),
                         agent_intents=[])
        # v0.6.0: the first coherent system-bundle (foundation docs + operating layer).
        cls.plan = assemble_emission_plan(bi, sp, corpus, model_tiers=sp.model_tiers,
                                          bundle_version="v0.6.0")
        contract = load_contract(default_contract_path())
        plan = validate_emission_plan(cls.plan, contract)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        emit_scaffold(plan, staging, REPO_ROOT)
        cls.staging = staging

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_is_actually_foundation_only(self):
        # Guard the premise of this whole class: the assembled plan really is
        # foundation-only with no agents.
        self.assertTrue(self.plan["foundation_only_mode"])
        self.assertEqual(self.plan["agents"], [])

    def test_operating_discipline_doc_still_emitted(self):
        p = self.staging / "operating_discipline.md"
        self.assertTrue(p.exists(), "operating_discipline.md not emitted for a foundation-only system")
        text = p.read_text()
        for anchor in ["Verified", "Not verified", "Not observable",
                       "UNVERIFIABLE_LOCALLY", "co-protected-workflows.md", "narration"]:
            self.assertIn(anchor, text, f"foundation-only operating_discipline.md missing anchor: {anchor}")

    def test_ceremony_maturity_table_seeds_all_five_classes(self):
        # The five fixed high-risk action classes are seeded probationary even though
        # this system has no high-risk capability — the table is a fixed list, not
        # derived per-phase, so it never spuriously gates and never silently omits.
        text = (self.staging / "operating_discipline.md").read_text()
        # The {{CEREMONY_MATURITY_ROWS}} placeholder must be filled (not left raw).
        self.assertNotIn("{{CEREMONY_MATURITY_ROWS}}", text)
        for cls_name in ("financial", "external-communications",
                         "irreversible-data", "guardrail", "legal"):
            self.assertIn(f"| {cls_name} | probationary |", text,
                          f"ceremony table missing probationary seed for action class: {cls_name}")
        # No action-class ROW may carry a graduated maturity (the column header
        # "Last graduated" legitimately uses the word, so scan the data rows only).
        self.assertNotIn("| graduated |", text,
                         "a fresh foundation-only system must have no graduated action class")

    def test_operator_skills_still_emitted(self):
        # The orientation + pause skills are static operator capabilities; they ship for
        # every system including a foundation-only one. Emitted by the operator-fill
        # layer; assert here that the foundation-only plan does not strip them.
        from operator_fill_emitter import emit_operator_fill_templates
        contract = load_contract(default_contract_path())
        plan = validate_emission_plan(self.plan, contract)
        with tempfile.TemporaryDirectory() as td:
            staging = Path(td)
            emit_operator_fill_templates(plan, staging, REPO_ROOT)
            for skill in ("orientation.md", "pause.md"):
                self.assertTrue((staging / "wizard" / "skills" / skill).exists(),
                                f"operator skill not emitted for a foundation-only system: {skill}")


class ManualMdContentTests(unittest.TestCase):
    """Assert that the emitted manual.md carries the operator's Operating Manual
    shape: correct title, build-and-operate loop section, role section, operating
    rhythm section, setup steps demoted to an appendix, and no unfilled date
    placeholder."""

    @classmethod
    def setUpClass(cls):
        contract = load_contract(default_contract_path())
        plan = validate_emission_plan(_valid_plan(), contract)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        # Supply a real-date MANUAL_LAST_UPDATED via extra_inputs so the test
        # exercises the real-date wiring path (same mechanism as LAST_UPDATED_DATE).
        emit_scaffold(plan, staging, REPO_ROOT,
                      extra_inputs={"MANUAL_LAST_UPDATED": "2026-01-01"})
        cls.text = (staging / "manual.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_title_is_operating_manual_not_setup_guide(self):
        self.assertIn("Operating Manual", self.text)
        self.assertNotIn("Setup Guide", self.text)

    def test_contains_build_and_operate_loop_section(self):
        lower = self.text.lower()
        self.assertIn("build-and-operate loop", lower)

    def test_contains_your_role_section(self):
        lower = self.text.lower()
        self.assertIn("your role", lower)

    def test_contains_operating_rhythm_section(self):
        lower = self.text.lower()
        self.assertIn("operating rhythm", lower)

    def test_install_steps_are_under_appendix_heading(self):
        # The appendix heading must appear before the install content.
        appendix_pos = self.text.lower().find("appendix")
        homebrew_pos = self.text.lower().find("homebrew")
        self.assertGreater(appendix_pos, 0, "no appendix heading found")
        self.assertGreater(homebrew_pos, 0, "homebrew content missing")
        self.assertLess(appendix_pos, homebrew_pos,
                        "Homebrew install content must appear after the appendix heading")

    def test_no_literal_set_at_operator_setup(self):
        self.assertNotIn("(set at operator setup)", self.text)

    def test_manual_last_updated_renders_to_real_date(self):
        # The placeholder must be replaced by the value we supplied, not left as {{...}}.
        self.assertNotIn("{{MANUAL_LAST_UPDATED}}", self.text)
        self.assertIn("2026-01-01", self.text)


class HowItWorksCrossLinkTests(unittest.TestCase):
    """Assert that the emitted how_your_system_works.md cross-links to manual.md."""

    @classmethod
    def setUpClass(cls):
        contract = load_contract(default_contract_path())
        plan = validate_emission_plan(_valid_plan(), contract)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        emit_scaffold(plan, staging, REPO_ROOT,
                      extra_inputs={"MANUAL_LAST_UPDATED": "2026-01-01"})
        cls.text = (staging / "docs" / "how_your_system_works.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_cross_links_to_manual(self):
        self.assertIn("manual.md", self.text)
        self.assertIn("what your system does on its own", self.text)


class SessionStartUpgradeNoticeTests(unittest.TestCase):
    """F-C2: every emitted operator system ships upgrade_notice.sh wired as a
    SessionStart hook so the operator gets a quiet, read-only heads-up when a
    newer version of their system bundle is available. The hook never blocks the
    session and never changes anything."""

    def _emit(self, plan_dict=None):
        contract = load_contract(default_contract_path())
        plan = validate_emission_plan(plan_dict or _valid_plan(), contract)
        self._tmp = tempfile.TemporaryDirectory()
        staging = Path(self._tmp.name)
        emit_scaffold(plan, staging, REPO_ROOT)
        return staging

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_claude_config_emits_sessionstart_notice_hook(self):
        """A fresh emit produces .claude/upgrade_notice.sh (exists, mode 0755,
        bash -n clean) AND .claude/settings.json has a SessionStart hook invoking it,
        matching the existing hooks schema."""
        import json as _json
        import subprocess as _sub
        staging = self._emit()

        # --- 1. script file emitted and executable ---
        script = staging / ".claude" / "upgrade_notice.sh"
        self.assertTrue(script.exists(), ".claude/upgrade_notice.sh not emitted")
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR,
                        ".claude/upgrade_notice.sh not executable")

        # --- 2. bash -n syntax check ---
        r = _sub.run(["bash", "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0,
                         f"bash -n failed on emitted upgrade_notice.sh: {r.stderr}")

        # --- 3. settings.json has SessionStart hook invoking upgrade_notice.sh ---
        settings = _json.loads((staging / ".claude" / "settings.json").read_text())
        hooks = settings.get("hooks", {})
        session_start = hooks.get("SessionStart", [])
        self.assertTrue(
            len(session_start) > 0,
            "settings.json has no SessionStart hook entry",
        )
        # The hook must follow the same shape as the existing hooks:
        # a list of dicts each with a "hooks" list of {"type": "command", "command": "..."}.
        hook_entry = session_start[0]
        self.assertIn("hooks", hook_entry,
                      "SessionStart hook entry must have a 'hooks' key")
        inner_hooks = hook_entry["hooks"]
        self.assertTrue(len(inner_hooks) > 0, "SessionStart hooks list is empty")
        inner = inner_hooks[0]
        self.assertEqual(inner.get("type"), "command",
                         "SessionStart hook must be type 'command'")
        cmd = inner.get("command", "")
        self.assertIn("upgrade_notice.sh", cmd,
                      f"SessionStart hook command does not invoke upgrade_notice.sh: {cmd!r}")


if __name__ == "__main__":
    unittest.main()
