"""Tests for the deterministic financial-guardrail projection (pure-code arithmetic).

The money safety-envelope is computed in pure code, not authored by the model. These tests pin:
budget = round(pool x share) with fixed share fractions (sole 0.9 / one-of-several 0.4); threshold
= max(1, round(0.10 x budget)); ROUND_HALF_UP (not banker's rounding); fail-closed on a malformed
pool / out-of-enum share / missing input; byte-determinism (the property the change-propagation
engine relies on to auto-halt an unchanged financial subset); and the live estate values.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import financial_projection as fp  # type: ignore  # noqa: E402


class TestBudget(unittest.TestCase):
    def test_estate_team_premium_one_of_several(self):
        # FIN-1 team premium -> pool $100; FIN-3 one-of-several -> 0.4 -> $40 (the live estate).
        self.assertEqual(
            fp.project("PROJECT_AUTOMATION_BUDGET",
                       {"AUTOMATION_CREDIT_POOL": "$100", "PROJECT_SHARE_POSTURE": "one-of-several"}),
            "$40")

    def test_sole_uses_most_of_pool(self):
        self.assertEqual(
            fp.project("PROJECT_AUTOMATION_BUDGET",
                       {"AUTOMATION_CREDIT_POOL": "$100", "PROJECT_SHARE_POSTURE": "sole"}),
            "$90")

    def test_pro_pool_sole(self):
        # $20 x 0.9 = 18.0 -> $18
        self.assertEqual(
            fp.project("PROJECT_AUTOMATION_BUDGET",
                       {"AUTOMATION_CREDIT_POOL": "$20", "PROJECT_SHARE_POSTURE": "sole"}),
            "$18")

    def test_pro_pool_one_of_several(self):
        # $20 x 0.4 = 8.0 -> $8
        self.assertEqual(
            fp.project("PROJECT_AUTOMATION_BUDGET",
                       {"AUTOMATION_CREDIT_POOL": "$20", "PROJECT_SHARE_POSTURE": "one-of-several"}),
            "$8")

    def test_parses_pool_with_seat_suffix(self):
        self.assertEqual(
            fp.project("PROJECT_AUTOMATION_BUDGET",
                       {"AUTOMATION_CREDIT_POOL": "$100/seat", "PROJECT_SHARE_POSTURE": "sole"}),
            "$90")

    def test_round_half_up(self):
        # $25 x 0.9 = 22.5 -> ROUND_HALF_UP -> $23 (banker's rounding would give $22).
        self.assertEqual(
            fp.project("PROJECT_AUTOMATION_BUDGET",
                       {"AUTOMATION_CREDIT_POOL": "$25", "PROJECT_SHARE_POSTURE": "sole"}),
            "$23")


class TestThreshold(unittest.TestCase):
    def test_estate_threshold(self):
        # 0.10 x $40 = 4.0 -> $4 (the live estate).
        self.assertEqual(
            fp.project("INTENSIVE_OPERATION_THRESHOLD", {"PROJECT_AUTOMATION_BUDGET": "$40"}),
            "$4")

    def test_threshold_floored_at_one_dollar(self):
        # 0.10 x $8 = 0.8 -> round 1 -> max(1,1) = $1; even tiny budgets keep a >=$1 gate.
        self.assertEqual(
            fp.project("INTENSIVE_OPERATION_THRESHOLD", {"PROJECT_AUTOMATION_BUDGET": "$8"}),
            "$1")

    def test_threshold_round_half_up(self):
        # 0.10 x $18 = 1.8 -> $2
        self.assertEqual(
            fp.project("INTENSIVE_OPERATION_THRESHOLD", {"PROJECT_AUTOMATION_BUDGET": "$18"}),
            "$2")


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_same_output(self):
        inp = {"AUTOMATION_CREDIT_POOL": "$200", "PROJECT_SHARE_POSTURE": "one-of-several"}
        self.assertEqual(fp.project("PROJECT_AUTOMATION_BUDGET", inp),
                         fp.project("PROJECT_AUTOMATION_BUDGET", inp))


class TestDerivationInputs(unittest.TestCase):
    def test_budget_inputs(self):
        self.assertEqual(fp.derivation_inputs_for("PROJECT_AUTOMATION_BUDGET"),
                         ["AUTOMATION_CREDIT_POOL", "PROJECT_SHARE_POSTURE"])

    def test_threshold_inputs(self):
        self.assertEqual(fp.derivation_inputs_for("INTENSIVE_OPERATION_THRESHOLD"),
                         ["PROJECT_AUTOMATION_BUDGET"])

    def test_unknown_field_fails(self):
        with self.assertRaises(fp.FinancialProjectionError):
            fp.derivation_inputs_for("NOPE")

    def test_projection_fields_membership(self):
        self.assertIn("PROJECT_AUTOMATION_BUDGET", fp.PROJECTION_FIELDS)
        self.assertIn("INTENSIVE_OPERATION_THRESHOLD", fp.PROJECTION_FIELDS)
        self.assertNotIn("AUTOMATION_CREDIT_POOL", fp.PROJECTION_FIELDS)  # pool is extraction, not here


class TestFailClosed(unittest.TestCase):
    def test_bad_share_enum(self):
        with self.assertRaises(fp.FinancialProjectionError):
            fp.project("PROJECT_AUTOMATION_BUDGET",
                       {"AUTOMATION_CREDIT_POOL": "$100", "PROJECT_SHARE_POSTURE": "half"})

    def test_unparseable_pool(self):
        with self.assertRaises(fp.FinancialProjectionError):
            fp.project("PROJECT_AUTOMATION_BUDGET",
                       {"AUTOMATION_CREDIT_POOL": "lots", "PROJECT_SHARE_POSTURE": "sole"})

    def test_missing_input(self):
        with self.assertRaises(fp.FinancialProjectionError):
            fp.project("PROJECT_AUTOMATION_BUDGET", {"AUTOMATION_CREDIT_POOL": "$100"})

    def test_negative_pool(self):
        with self.assertRaises(fp.FinancialProjectionError):
            fp.project("PROJECT_AUTOMATION_BUDGET",
                       {"AUTOMATION_CREDIT_POOL": "-$100", "PROJECT_SHARE_POSTURE": "sole"})

    def test_unknown_projection_field(self):
        with self.assertRaises(fp.FinancialProjectionError):
            fp.project("NOPE", {})


if __name__ == "__main__":
    unittest.main()
