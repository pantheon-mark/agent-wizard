"""Tests for the doc-centric operator-output routing convention (v0.7.0 templates + emitter).

Template-content tests: read the v0.7.0 template files directly and assert the new
text is present.  v0.7.0 is NOT registered (that is a later freeze task), so these
tests never emit from v0.7.0 — they only read the template files.

Unit test: call _operator_output_pointer directly with an operator-facing record and
an internal record; assert the correct values without any full emit.
"""

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_emitter import _operator_output_pointer, _OPERATOR_OUTPUT_POINTER_TEXT  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
V070_TEMPLATES = REPO_ROOT / "wizard" / "foundation-bundles" / "v0.7.0" / "templates"


class V070TemplateContentTests(unittest.TestCase):
    """Assert the routing convention landed in the v0.7.0 template files."""

    def test_project_instructions_has_operator_facing_section(self):
        text = (V070_TEMPLATES / "root" / "project_instructions.md").read_text(encoding="utf-8")
        self.assertIn("## Operator-facing deliverables", text,
                      "project_instructions.md missing the global routing rule heading")
        self.assertIn("deliverables/", text,
                      "project_instructions.md missing the deliverables/ directory reference")
        self.assertIn("voice_and_style.md", text,
                      "project_instructions.md missing the voice_and_style.md reference")

    def test_agent_prompt_template_has_operator_output_pointer_placeholder(self):
        text = (V070_TEMPLATES / "agents" / "agent_prompt_template.md").read_text(encoding="utf-8")
        self.assertIn("{{OPERATOR_OUTPUT_POINTER}}", text,
                      "agent_prompt_template.md missing {{OPERATOR_OUTPUT_POINTER}} placeholder")

    def test_orchestrator_prompt_has_placement_safety_net(self):
        text = (V070_TEMPLATES / "agents" / "orchestrator_prompt.md").read_text(encoding="utf-8")
        self.assertIn("## Operator deliverables — placement safety-net", text,
                      "orchestrator_prompt.md missing the safety-net heading")
        self.assertIn("deliverables/", text,
                      "orchestrator_prompt.md safety-net missing deliverables/ reference")
        self.assertIn("work/agent_outputs/", text,
                      "orchestrator_prompt.md safety-net missing work/agent_outputs/ reference")


class OperatorOutputPointerUnitTests(unittest.TestCase):
    """Unit tests for _operator_output_pointer — the function that decides the
    per-agent OPERATOR_OUTPUT_POINTER substitution value."""

    def _make_agent_record(self, operator_facing: bool):
        """Minimal stand-in for an AgentRecord-like object."""
        rec = types.SimpleNamespace()
        rec.operator_facing = operator_facing
        return rec

    def test_operator_facing_agent_gets_pointer_text(self):
        a = self._make_agent_record(operator_facing=True)
        result = _operator_output_pointer(a)
        self.assertEqual(result, _OPERATOR_OUTPUT_POINTER_TEXT,
                         "operator-facing agent did not get the pointer text")
        self.assertIn("project_instructions.md", result)
        self.assertIn("voice_and_style.md", result)
        self.assertIn("deliverable location", result)

    def test_internal_agent_gets_empty_string(self):
        a = self._make_agent_record(operator_facing=False)
        result = _operator_output_pointer(a)
        self.assertEqual(result, "",
                         "internal agent should get empty string for OPERATOR_OUTPUT_POINTER")

    def test_missing_operator_facing_attr_defaults_to_empty(self):
        """A record without the operator_facing attribute (older record) defaults to empty."""
        a = types.SimpleNamespace()  # no operator_facing attribute
        result = _operator_output_pointer(a)
        self.assertEqual(result, "",
                         "record without operator_facing attr should default to empty string")


if __name__ == "__main__":
    unittest.main()
