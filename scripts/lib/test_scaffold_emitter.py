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


if __name__ == "__main__":
    unittest.main()
