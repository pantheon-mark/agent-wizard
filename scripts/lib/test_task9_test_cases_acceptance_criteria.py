"""Task 9 — test_cases.md acceptance-criteria update verification.

Asserts:
  1. MA-VS-3 no longer says "invocation scripts" and now references
     project_instructions / additional_context_files (mechanism correction).
  2. Three new MA-OF rows are present:
       MA-OF-1  Operator deliverables land in deliverables/ with human-readable names
       MA-OF-2  Orchestrator safety-net relocates stranded deliverables
       MA-OF-3  design-outbound-message skill runs before significant outbound messages
  3. MA-VS-1/2/4/5/6 unchanged (regression guard on unrelated rows).
  4. No internal build IDs (e.g. "S2.51") appear in the template.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_CASES_PATH = (
    REPO_ROOT
    / "wizard"
    / "foundation-bundles"
    / "v0.7.0"
    / "templates"
    / "test_cases.md"
)


def _read() -> str:
    return TEST_CASES_PATH.read_text(encoding="utf-8")


class MAVS3MechanismCorrectionTest(unittest.TestCase):
    """MA-VS-3 must reflect the doc-centric consult mechanism, not invocation scripts."""

    def test_ma_vs3_no_longer_says_invocation_scripts(self):
        text = _read()
        # Find the MA-VS-3 row
        for line in text.splitlines():
            if "MA-VS-3" in line:
                self.assertNotIn(
                    "invocation scripts",
                    line.lower(),
                    "MA-VS-3 must not say 'invocation scripts' — use the doc-centric mechanism",
                )
                return
        self.fail("MA-VS-3 row not found in test_cases.md")

    def test_ma_vs3_references_project_instructions(self):
        text = _read()
        for line in text.splitlines():
            if "MA-VS-3" in line:
                self.assertIn(
                    "project_instructions",
                    line,
                    "MA-VS-3 must reference project_instructions.md as the mechanism",
                )
                return
        self.fail("MA-VS-3 row not found in test_cases.md")

    def test_ma_vs3_references_additional_context_files(self):
        text = _read()
        for line in text.splitlines():
            if "MA-VS-3" in line:
                self.assertIn(
                    "additional_context_files",
                    line,
                    "MA-VS-3 must reference additional_context_files as the mechanism",
                )
                return
        self.fail("MA-VS-3 row not found in test_cases.md")

    def test_ma_vs3_still_describes_voice_and_style(self):
        text = _read()
        for line in text.splitlines():
            if "MA-VS-3" in line:
                self.assertIn(
                    "voice_and_style",
                    line,
                    "MA-VS-3 must still reference voice_and_style.md",
                )
                return
        self.fail("MA-VS-3 row not found in test_cases.md")


class MAOFRowsPresentTest(unittest.TestCase):
    """All three MA-OF acceptance-criteria rows must be present."""

    def _rows(self) -> dict:
        rows = {}
        for line in _read().splitlines():
            for key in ("MA-OF-1", "MA-OF-2", "MA-OF-3"):
                if key in line:
                    rows[key] = line
        return rows

    def test_ma_of1_present(self):
        rows = self._rows()
        self.assertIn("MA-OF-1", rows,
                      "MA-OF-1 row missing from test_cases.md")

    def test_ma_of1_mentions_deliverables_directory(self):
        rows = self._rows()
        self.assertIn("MA-OF-1", rows)
        self.assertIn("deliverables/", rows["MA-OF-1"],
                      "MA-OF-1 must mention the deliverables/ directory")

    def test_ma_of1_mentions_naming_pattern(self):
        rows = self._rows()
        self.assertIn("MA-OF-1", rows)
        row = rows["MA-OF-1"].lower()
        self.assertTrue(
            "naming" in row or "human-readable" in row,
            "MA-OF-1 must reference naming pattern or human-readable names",
        )

    def test_ma_of2_present(self):
        rows = self._rows()
        self.assertIn("MA-OF-2", rows,
                      "MA-OF-2 row missing from test_cases.md")

    def test_ma_of2_mentions_orchestrator_relocation(self):
        rows = self._rows()
        self.assertIn("MA-OF-2", rows)
        row = rows["MA-OF-2"].lower()
        self.assertTrue(
            "orchestrator" in row or "relocat" in row or "moves" in row,
            "MA-OF-2 must describe the orchestrator safety-net relocation",
        )

    def test_ma_of2_mentions_work_agent_outputs(self):
        rows = self._rows()
        self.assertIn("MA-OF-2", rows)
        self.assertIn("work/agent_outputs/", rows["MA-OF-2"],
                      "MA-OF-2 must reference work/agent_outputs/ as the stranded location")

    def test_ma_of2_mentions_deliverables_not_touched(self):
        rows = self._rows()
        self.assertIn("MA-OF-2", rows)
        row = rows["MA-OF-2"].lower()
        self.assertTrue(
            "not touch" in row or "already in" in row or "not touched" in row,
            "MA-OF-2 must state that files already in deliverables/ are not touched",
        )

    def test_ma_of3_present(self):
        rows = self._rows()
        self.assertIn("MA-OF-3", rows,
                      "MA-OF-3 row missing from test_cases.md")

    def test_ma_of3_mentions_design_outbound_message_skill(self):
        rows = self._rows()
        self.assertIn("MA-OF-3", rows)
        self.assertIn("design-outbound-message", rows["MA-OF-3"],
                      "MA-OF-3 must reference the design-outbound-message skill")

    def test_ma_of3_mentions_email(self):
        rows = self._rows()
        self.assertIn("MA-OF-3", rows)
        self.assertIn("email", rows["MA-OF-3"].lower(),
                      "MA-OF-3 must mention email as a trigger")

    def test_ma_of3_mentions_internal_exclusion(self):
        rows = self._rows()
        self.assertIn("MA-OF-3", rows)
        self.assertIn("internal", rows["MA-OF-3"].lower(),
                      "MA-OF-3 must state that internal artifacts are excluded")


class MAVSRegressionTest(unittest.TestCase):
    """MA-VS-1/2/4/5/6 must still be present and unchanged in substance."""

    def _find_row(self, row_id: str) -> str:
        for line in _read().splitlines():
            if row_id in line:
                return line
        return ""

    def test_ma_vs1_present(self):
        self.assertTrue(self._find_row("MA-VS-1"),
                        "MA-VS-1 row missing — regression")

    def test_ma_vs1_mentions_seeded_from_profile(self):
        row = self._find_row("MA-VS-1").lower()
        self.assertTrue("profile" in row or "vision" in row,
                        "MA-VS-1 must still mention operator profile or vision seeding")

    def test_ma_vs2_present(self):
        self.assertTrue(self._find_row("MA-VS-2"),
                        "MA-VS-2 row missing — regression")

    def test_ma_vs2_mentions_no_new_questions(self):
        row = self._find_row("MA-VS-2").lower()
        self.assertTrue("no additional" in row or "without new" in row or "existing" in row,
                        "MA-VS-2 must still state no new questions")

    def test_ma_vs4_present(self):
        self.assertTrue(self._find_row("MA-VS-4"),
                        "MA-VS-4 row missing — regression")

    def test_ma_vs4_mentions_internal_agents_excluded(self):
        row = self._find_row("MA-VS-4").lower()
        self.assertTrue("internal" in row or "excluded" in row,
                        "MA-VS-4 must still mention internal agents are excluded")

    def test_ma_vs5_present(self):
        self.assertTrue(self._find_row("MA-VS-5"),
                        "MA-VS-5 row missing — regression")

    def test_ma_vs6_present(self):
        self.assertTrue(self._find_row("MA-VS-6"),
                        "MA-VS-6 row missing — regression")

    def test_ma_vs6_mentions_starter_note(self):
        row = self._find_row("MA-VS-6").lower()
        self.assertTrue("starting defaults" in row or "starter note" in row,
                        "MA-VS-6 must still mention the starter note")


class NoBuildIDsTest(unittest.TestCase):
    """No internal build slice IDs may appear in the v0.7.0 template."""

    def test_no_slice_ids_in_test_cases(self):
        text = _read()
        import re
        # Internal slice IDs match pattern S<digit>.<digit>
        match = re.search(r'\bS\d+\.\d+\b', text)
        self.assertIsNone(match,
                          f"Internal slice ID found in test_cases.md: {match.group() if match else ''}")


class OperatorFacingOutputSectionHeaderTest(unittest.TestCase):
    """The Operator-Facing Output section header must exist."""

    def test_operator_facing_output_heading_present(self):
        text = _read()
        self.assertIn("Operator-Facing Output", text,
                      "test_cases.md missing 'Operator-Facing Output' section header")


if __name__ == "__main__":
    unittest.main()
