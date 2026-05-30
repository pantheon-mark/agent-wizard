"""Tests for the operator-fill template emitter (build-session helpers + .env).

The review-prompt + skill templates are STATIC operator-fill templates: copied
verbatim into the operator project (parity with the legacy close-assembly), keeping
their {{KEY}} placeholders intact for the operator to complete during build/review
sessions. Their placeholder vocabulary is disjoint from the generation-time keys, so
the key-set-aware placeholder check already ignores them; the verbatim copy must NOT
substitute them. An empty .env placeholder is emitted too. RED->GREEN.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_parity import _plan, REPO_ROOT  # noqa: E402  reuse the validated neutral plan
from operator_fill_emitter import emit_operator_fill_templates  # noqa: E402


class OperatorFillEmitterTests(unittest.TestCase):
    def test_emits_helpers_and_env(self):
        plan = _plan()
        with tempfile.TemporaryDirectory() as td:
            written = emit_operator_fill_templates(plan, Path(td), REPO_ROOT)
            rels = {str(p.relative_to(td)) for p in written}
            for rel in ("wizard/review_prompts/post_wizard_review.md",
                        "wizard/review_prompts/per_agent_review.md",
                        "wizard/review_prompts/phase_gate_review.md",
                        "wizard/skills/_index.md",
                        "wizard/skills/skill_template_external.md",
                        "wizard/skills/skill_template_internal.md",
                        ".env"):
                self.assertIn(rel, rels, f"missing emitted operator-fill artifact: {rel}")

    def test_helpers_copied_verbatim_with_operator_fill_placeholders_intact(self):
        plan = _plan()
        with tempfile.TemporaryDirectory() as td:
            emit_operator_fill_templates(plan, Path(td), REPO_ROOT)
            ext = (Path(td) / "wizard/skills/skill_template_external.md").read_text(encoding="utf-8")
            self.assertIn("{{SKILL_NAME}}", ext)   # intentional operator-fill placeholder NOT substituted
            src = (REPO_ROOT / "wizard/skills/skill_template_external.md").read_text(encoding="utf-8")
            self.assertEqual(ext, src)              # byte-for-byte copy

    def test_env_is_empty(self):
        plan = _plan()
        with tempfile.TemporaryDirectory() as td:
            emit_operator_fill_templates(plan, Path(td), REPO_ROOT)
            self.assertEqual((Path(td) / ".env").read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
