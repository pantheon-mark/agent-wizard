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


if __name__ == "__main__":
    unittest.main()
