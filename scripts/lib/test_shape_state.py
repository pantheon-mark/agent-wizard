"""Tests for shape_state.py — the read-only shape-lifecycle verifier.

Fixtures are neutral synthetic session-draft snippets (no operator content): a populated
shape block, an empty recheck_log, and a missing-fields case. They exercise the line-oriented
parse + the fail-closed check (the consumer-gate assertion + the write receipt)."""

import os
import sys
import tempfile
import unittest

_LIB = os.path.dirname(__file__)
_SCRIPTS = os.path.dirname(_LIB)
sys.path.insert(0, _LIB)
sys.path.insert(0, _SCRIPTS)
import shape_state as ss  # noqa: E402
import interview_cli as cli  # noqa: E402


_POPULATED = """\
## Shape detection

schema_versions:
  schema_major: 1
  schema_minor: 0

handoff_phase: pre_step_08_evaluated

shape_hypothesis:
  status: emitted
  shape: markdown-agents
  confidence: high
  fallback_mode_offered: not_offered
  recheck_log:
  - step: 05
    timestamp: 2026-01-01T00:00:00Z
    outcome: confirmed
  - step: 08
    timestamp: 2026-01-01T00:00:00Z
    outcome: confirmed
  emit_basis: "synthetic"
"""

_EMPTY_RECHECK = """\
handoff_phase: regulatory_exposure_populated

shape_hypothesis:
  status: emitted
  fallback_mode_offered: not_offered
  recheck_log: []
  emit_basis: "synthetic"
"""

_MISSING = """\
shape_hypothesis:
  status: emitted
"""


class ParseShapeState(unittest.TestCase):
    def test_populated_block(self):
        st = ss.parse_shape_state(_POPULATED)
        self.assertEqual(st["handoff_phase"], "pre_step_08_evaluated")
        self.assertEqual(st["recheck_steps"], [5, 8])  # leading zeros stripped
        self.assertEqual(st["fallback_mode_offered"], "not_offered")

    def test_empty_recheck_log(self):
        st = ss.parse_shape_state(_EMPTY_RECHECK)
        self.assertEqual(st["handoff_phase"], "regulatory_exposure_populated")
        self.assertEqual(st["recheck_steps"], [])
        self.assertEqual(st["fallback_mode_offered"], "not_offered")

    def test_missing_fields(self):
        st = ss.parse_shape_state(_MISSING)
        self.assertIsNone(st["handoff_phase"])
        self.assertEqual(st["recheck_steps"], [])
        self.assertIsNone(st["fallback_mode_offered"])

    def test_inline_comment_stripped(self):
        st = ss.parse_shape_state("handoff_phase: pre_step_05_evaluated  # advanced by re-check\n")
        self.assertEqual(st["handoff_phase"], "pre_step_05_evaluated")


class CheckShapeState(unittest.TestCase):
    def test_phase_match_passes(self):
        failures, _ = ss.check_shape_state(_POPULATED, expect_phase="pre_step_08_evaluated")
        self.assertEqual(failures, [])

    def test_phase_mismatch_fails(self):
        failures, _ = ss.check_shape_state(_EMPTY_RECHECK, expect_phase="pre_step_05_evaluated")
        self.assertEqual(len(failures), 1)
        self.assertIn("handoff_phase", failures[0])

    def test_expected_recheck_present(self):
        failures, _ = ss.check_shape_state(_POPULATED, expect_recheck_step=5)
        self.assertEqual(failures, [])

    def test_expected_recheck_absent_fails(self):
        # the exact gap a skipped pre-step-05 re-check leaves: empty recheck_log, step 5 expected
        failures, _ = ss.check_shape_state(_EMPTY_RECHECK, expect_recheck_step=5)
        self.assertEqual(len(failures), 1)
        self.assertIn("step:5", failures[0])

    def test_require_field_present(self):
        failures, _ = ss.check_shape_state(_POPULATED, require_fields=("fallback_mode_offered",))
        self.assertEqual(failures, [])

    def test_require_field_missing_fails(self):
        failures, _ = ss.check_shape_state(_MISSING, require_fields=("fallback_mode_offered",))
        self.assertEqual(len(failures), 1)

    def test_combined_expectations_accumulate(self):
        failures, _ = ss.check_shape_state(
            _MISSING, expect_phase="pre_step_08_evaluated", expect_recheck_step=8,
            require_fields=("fallback_mode_offered",))
        self.assertEqual(len(failures), 3)


class CheckShapeStateCLI(unittest.TestCase):
    """Exercise the carrier-visible receipt: cmd raises (-> non-zero) on an unmet expectation."""

    def _write(self, text):
        fd, path = tempfile.mkstemp(suffix=".md")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_cmd_passes_on_satisfied(self):
        path = self._write(_POPULATED)
        state = cli.cmd_check_shape_state(path, expect_phase="pre_step_08_evaluated",
                                          expect_recheck_step=5)
        self.assertEqual(state["recheck_steps"], [5, 8])

    def test_cmd_raises_on_skipped_recheck(self):
        path = self._write(_EMPTY_RECHECK)
        with self.assertRaises(cli.InterviewCLIError):
            cli.cmd_check_shape_state(path, expect_phase="pre_step_05_evaluated",
                                      expect_recheck_step=5)

    def test_cmd_raises_on_missing_draft(self):
        with self.assertRaises(cli.InterviewCLIError):
            cli.cmd_check_shape_state("/nonexistent/draft/path.md", expect_phase="x")


if __name__ == "__main__":
    unittest.main()
