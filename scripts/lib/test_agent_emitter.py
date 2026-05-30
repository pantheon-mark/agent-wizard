"""Tests for the agent-layer emitter (stdlib unittest; pip-install-free).

Emits the /agents/ tree from a validated EmissionPlan against the REAL agent
templates into a temp staging dir, and asserts: structure, placeholder
exhaustion (no {{KEY}} survives), the tier-name-in-prompt / resolved-model-in-
script split, script executability, and foundation-only mode emits nothing.
"""

import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_emitter import emit_agent_layer  # noqa: E402
from emission_plan import load_contract, default_contract_path, validate_emission_plan  # noqa: E402
from generator import PLACEHOLDER_RE  # noqa: E402
from test_emission_plan import _valid_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


class AgentEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _emit(self, plan_dict):
        plan = validate_emission_plan(plan_dict, self.contract)
        self._tmp = tempfile.TemporaryDirectory()
        staging = Path(self._tmp.name)
        written = emit_agent_layer(plan, staging, REPO_ROOT)
        return staging, written

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_emits_full_agent_tree(self):
        staging, written = self._emit(_valid_plan())
        a = staging / "agents"
        for rel in ["prompts/orchestrator_prompt.md", "prompts/qa_agent_prompt.md",
                    "prompts/researcher_prompt.md", "scripts/researcher.sh",
                    "cron/cron_config.md", "roster.md"]:
            self.assertTrue((a / rel).exists(), f"missing emitted file: agents/{rel}")
        self.assertEqual(len(written), 6)

    def test_placeholder_exhaustion(self):
        # Emitting at all proves fail-fast covered every placeholder; this re-asserts
        # no {{KEY}} survived in any emitted artifact.
        staging, written = self._emit(_valid_plan())
        for p in written:
            text = p.read_text(encoding="utf-8")
            leftover = PLACEHOLDER_RE.findall(text)
            self.assertEqual(leftover, [], f"unsubstituted placeholder(s) in {p.name}: {leftover}")

    def test_project_name_substituted(self):
        staging, _ = self._emit(_valid_plan())
        orch = (staging / "agents/prompts/orchestrator_prompt.md").read_text()
        self.assertIn("demo", orch)

    def test_tier_name_in_prompt_resolved_model_in_script(self):
        # The split: prompt carries the tier NAME 'standard'; the invocation script
        # carries the RESOLVED model string 'model-standard' (never the bare tier name as --model).
        staging, _ = self._emit(_valid_plan())
        prompt = (staging / "agents/prompts/researcher_prompt.md").read_text()
        script = (staging / "agents/scripts/researcher.sh").read_text()
        self.assertIn("standard", prompt)                       # tier name present in prompt
        self.assertIn('AGENT_MODEL="model-standard"', script)   # resolved model in script
        self.assertNotIn('AGENT_MODEL="standard"', script)      # NOT the bare tier name

    def test_script_is_executable(self):
        staging, _ = self._emit(_valid_plan())
        script = staging / "agents/scripts/researcher.sh"
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR, "invocation script is not executable")

    def test_roster_lists_agent(self):
        staging, _ = self._emit(_valid_plan())
        roster = (staging / "agents/roster.md").read_text()
        self.assertIn("researcher", roster)
        self.assertIn("Orchestrator", roster)
        self.assertIn("QA", roster)

    def test_foundation_only_emits_nothing(self):
        import copy
        p = copy.deepcopy(_valid_plan())
        p["foundation_only_mode"] = True
        p["agents"] = []  # I7: foundation-only forbids agents
        staging, written = self._emit(p)
        self.assertEqual(written, [])
        self.assertFalse((staging / "agents").exists())

    # --- T7 / C-008: cron-claim consumption into the emitted cron_config.md ---

    @staticmethod
    def _cron_plan():
        """A valid plan whose single agent carries a cron cadence (the requires_cron
        path: assembler stamps orchestrator.schedule onto the agent's cron_cadence)."""
        import copy
        p = copy.deepcopy(_valid_plan())
        p["agents"][0]["cron_cadence"] = "0 * * * *"
        return p

    def _cron_entry_rows(self, staging):
        """The cron_config.md table rows that name the scheduled agent 'researcher'."""
        cron = (staging / "agents/cron/cron_config.md").read_text()
        rows = [ln for ln in cron.splitlines()
                if ln.lstrip().startswith("|") and "researcher" in ln]
        return cron, rows

    def test_cron_agent_cadence_reaches_cron_config(self):
        # The requires_cron agent's cadence must reach the emitted cron config as a
        # scheduled entry — today the emitter copies the static template verbatim and
        # the cadence is dropped on the floor.
        staging, _ = self._emit(self._cron_plan())
        cron, rows = self._cron_entry_rows(staging)
        self.assertTrue(rows, "no cron table row for the requires_cron agent 'researcher'")
        self.assertTrue(any("0 * * * *" in ln for ln in rows),
                        "the agent's cron cadence did not reach its cron_config row")
        self.assertNotIn("No entries yet", cron,
                         "cron config still shows the empty-state note despite a scheduled agent")

    def test_scheduled_job_invokes_orchestrator_by_default(self):
        # Control-plane rule: a scheduled job invokes the Orchestrator (control plane) by
        # default; directly scheduling the specialist (agents/scripts/<id>.sh) is the
        # declared exception, not the default.
        staging, _ = self._emit(self._cron_plan())
        _cron, rows = self._cron_entry_rows(staging)
        self.assertTrue(rows)
        self.assertTrue(any("orchestrator_prompt.md" in ln for ln in rows),
                        "scheduled entry does not invoke the Orchestrator by default")
        self.assertFalse(any("scripts/researcher.sh" in ln for ln in rows),
                         "scheduled entry directly invokes the specialist (declared exception, not the default)")

    def test_no_cron_agents_preserves_empty_state_note(self):
        # Differential-gate baseline: with no scheduled agent the cron config keeps its
        # honest empty-state note (byte-equivalent to the prior verbatim copy). Guards
        # the empty branch so the retirement differential stays green.
        staging, _ = self._emit(_valid_plan())  # researcher carries no cron_cadence
        cron = (staging / "agents/cron/cron_config.md").read_text()
        self.assertIn("No entries yet", cron)


if __name__ == "__main__":
    unittest.main()
