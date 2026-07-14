"""Tests for the two-knob scale-adaptive bounds engine (Task 4, A1 — v0.12.0
Slice 1, design §3): Knob A prove-it-out coverage sample + Knob B aggregate
blast-radius ceiling with recovery-profile-tiered absolute cap + progressive
escalating tranches.

Runner: unittest, from wizard/scripts. Stdlib only.

Anti-overfit (Global Constraint #3): every behavior is exercised on the
recovery tiers that ≥2 divergent op_kinds resolve to — a reversible tier
(gmail.message.trash / a spreadsheet field op) AND an irreversible tier
(delete_record) — and on candidate shapes for BOTH a gmail-style op and a
field/spreadsheet-style op.
"""

import random
import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import bounds  # noqa: E402
from external_write.bounds import (  # noqa: E402
    ABSOLUTE_CAP_BY_RECOVERY_TIER,
    FAIL_SAFE_RECOVERY_TIER,
    FIELD_OP_FALLBACK_STRATA_KEYS,
    RESIDUAL_STRATUM,
    absolute_cap_for_risk_class,
    knob_b_ceiling,
    next_tranche_size,
    recovery_tier_for_risk_class,
    select_coverage_sample,
)


# ===========================================================================
# Recovery-profile tiering (risk_class -> recovery tier -> absolute cap)
# ===========================================================================

class TestRecoveryTiering(unittest.TestCase):

    def test_reversible_risk_classes_map_to_reversible_tier(self):
        # A spreadsheet field edit (reversible_external) AND the gmail label op
        # (sensitive_data — the EDIT is reversible, e.g. trash/untrash) both
        # resolve to the larger reversible tier (the design's ~600 exemplar).
        self.assertEqual(recovery_tier_for_risk_class("reversible_external"), "reversible")
        self.assertEqual(recovery_tier_for_risk_class("sensitive_data"), "reversible")

    def test_irreversible_and_standing_map_to_irreversible_tier(self):
        self.assertEqual(recovery_tier_for_risk_class("irreversible_external"), "irreversible")
        self.assertEqual(recovery_tier_for_risk_class("standing_automation"), "irreversible")

    def test_absent_or_unknown_risk_class_fails_safe_to_irreversible(self):
        self.assertEqual(recovery_tier_for_risk_class(None), FAIL_SAFE_RECOVERY_TIER)
        self.assertEqual(recovery_tier_for_risk_class("not_a_real_class"), FAIL_SAFE_RECOVERY_TIER)
        self.assertEqual(FAIL_SAFE_RECOVERY_TIER, "irreversible")

    def test_absolute_cap_reversible_is_large_irreversible_is_tiny(self):
        # Reversible larger (~500-600); irreversible tiny, <= existing per-op
        # regime (delete_record's per-op blast_radius_cap is 5).
        self.assertGreaterEqual(ABSOLUTE_CAP_BY_RECOVERY_TIER["reversible"], 500)
        self.assertLessEqual(ABSOLUTE_CAP_BY_RECOVERY_TIER["reversible"], 600)
        self.assertLessEqual(ABSOLUTE_CAP_BY_RECOVERY_TIER["irreversible"], 5)
        self.assertEqual(absolute_cap_for_risk_class("gmail_wontmatch") ,
                         ABSOLUTE_CAP_BY_RECOVERY_TIER["irreversible"])  # fail-safe
        self.assertEqual(absolute_cap_for_risk_class("reversible_external"),
                         ABSOLUTE_CAP_BY_RECOVERY_TIER["reversible"])
        self.assertEqual(absolute_cap_for_risk_class("irreversible_external"),
                         ABSOLUTE_CAP_BY_RECOVERY_TIER["irreversible"])


# ===========================================================================
# Knob B ceiling: clamp(P% of frozen population, floor, ABSOLUTE_CAP)
# ===========================================================================

class TestKnobBCeiling(unittest.TestCase):

    def test_large_population_reversible_hits_absolute_cap(self):
        # 5% of 15000 = 750, clamped down to the reversible absolute cap.
        c = knob_b_ceiling(15000, "sensitive_data")  # gmail.message.trash tier
        self.assertEqual(c, ABSOLUTE_CAP_BY_RECOVERY_TIER["reversible"])

    def test_small_population_reversible_hits_floor(self):
        # 5% of 100 = 5, clamped UP to the floor (25), never above population.
        c = knob_b_ceiling(100, "reversible_external")
        self.assertEqual(c, 25)

    def test_large_population_irreversible_hits_tiny_absolute_cap(self):
        c = knob_b_ceiling(15000, "irreversible_external")  # delete_record tier
        self.assertEqual(c, ABSOLUTE_CAP_BY_RECOVERY_TIER["irreversible"])

    def test_small_population_irreversible_floor_never_exceeds_cap(self):
        # The invariant: floor (25) must never exceed the absolute cap (5) —
        # the effective floor is clamped down to the cap.
        c = knob_b_ceiling(100, "irreversible_external")
        self.assertEqual(c, ABSOLUTE_CAP_BY_RECOVERY_TIER["irreversible"])
        self.assertLessEqual(c, ABSOLUTE_CAP_BY_RECOVERY_TIER["irreversible"])

    def test_ceiling_never_exceeds_population(self):
        # Population smaller than the floor -> ceiling is the whole population.
        self.assertEqual(knob_b_ceiling(3, "reversible_external"), 3)
        self.assertEqual(knob_b_ceiling(0, "reversible_external"), 0)

    def test_floor_never_exceeds_cap_across_all_tiers(self):
        for rc in ("reversible_external", "sensitive_data",
                   "irreversible_external", "standing_automation", None):
            cap = absolute_cap_for_risk_class(rc)
            c = knob_b_ceiling(10_000, rc)
            self.assertLessEqual(c, cap,
                                 f"ceiling for {rc!r} exceeded its absolute cap")


# ===========================================================================
# Progressive escalating tranches — NEVER "the remainder" in one consent
# ===========================================================================

class TestProgressiveTranches(unittest.TestCase):

    def test_tranches_escalate_and_never_authorize_the_remainder(self):
        # A large frozen population against the reversible absolute cap: walk
        # the whole tranche schedule and assert the precise invariant — while
        # the remaining population is STILL LARGER than the absolute cap, no
        # single tranche may equal/exceed it (the F-39 hole: one consent
        # authorizing "the remainder" of a still-large population). Only the
        # final tail (remaining <= cap, a small reversible set) may be cleared.
        cap = ABSOLUTE_CAP_BY_RECOVERY_TIER["reversible"]
        remaining_population = 15000
        prior = 0
        sizes = []
        for _ in range(200):
            size = next_tranche_size(prior, remaining_population, cap)
            if size <= 0:
                break
            self.assertLessEqual(size, cap, "a tranche exceeded the absolute cap")
            if remaining_population > cap:
                self.assertLess(size, remaining_population,
                                "a single tranche authorized the remainder of a "
                                "still-large population — F-39 hole")
            sizes.append(size)
            prior = size
            remaining_population -= size
        # The escalation phase genuinely escalated (small first -> larger),
        # every tranche stayed at/under the cap, and the schedule reached the
        # cap (it did not plateau early below it).
        self.assertEqual(sizes[0], 10)
        self.assertGreater(sizes[3], sizes[0], "tranches must escalate small -> larger")
        self.assertEqual(max(sizes), cap)
        self.assertLessEqual(max(sizes), cap)

    def test_first_tranche_is_small_not_the_whole_population(self):
        cap = ABSOLUTE_CAP_BY_RECOVERY_TIER["reversible"]
        first = next_tranche_size(0, 15000, cap)
        self.assertLess(first, cap)
        self.assertLess(first, 15000)

    def test_tail_within_cap_may_clear_the_remainder(self):
        # When the remaining population is <= the absolute cap (a small,
        # reversible tail), a final evidence-gated tranche may legitimately
        # clear it — the "never the remainder" rule guards against jumping the
        # WHOLE large population in one consent, not against finishing a tail.
        cap = ABSOLUTE_CAP_BY_RECOVERY_TIER["irreversible"]  # 5
        size = next_tranche_size(0, 3, cap)
        self.assertEqual(size, 3)

    def test_no_tranche_for_empty_remaining(self):
        self.assertEqual(next_tranche_size(10, 0, 600), 0)


# ===========================================================================
# Knob A — prove-it-out coverage sample (I3(b) field-op strata fallback)
# ===========================================================================

class TestKnobAFieldStrataFallback(unittest.TestCase):

    def test_field_op_fallback_strata_keys_are_the_specified_five_dimensions(self):
        # I3(b): the field-op degrade-to-random strata are explicitly defined,
        # not hand-waved: field name / validation status / prestate value class
        # / protected row-or-category / confidence-source.
        self.assertEqual(
            FIELD_OP_FALLBACK_STRATA_KEYS,
            ("field_name", "validation_status", "prestate_value_class",
             "protected_status", "confidence_source"),
        )


class TestKnobACoverageSample(unittest.TestCase):

    def test_population_at_or_below_floor_returns_whole_population(self):
        cands = [{"unit_id": f"u{i}", "risk_stratum": "s1"} for i in range(10)]
        sel = select_coverage_sample(cands, floor=25)
        self.assertEqual(len(sel), 10)

    def test_declared_strata_each_covered_plus_residual(self):
        # gmail-style candidates with a declared generic risk_stratum: every
        # observed stratum is sampled, and the mandatory residual/low-confidence
        # stratum is always represented in the grouping.
        rng = random.Random(1234)
        cands = []
        for i in range(120):
            stratum = f"stratum_{i % 4}"
            cands.append({"unit_id": f"m{i}", "risk_stratum": stratum})
        # a handful with NO stratum -> must land in the mandatory residual
        for i in range(5):
            cands.append({"unit_id": f"r{i}"})  # no risk_stratum key
        sel = select_coverage_sample(cands, depth=8, floor=25, soft_cap=100, rng=rng)
        selected_strata = {c.get("risk_stratum", RESIDUAL_STRATUM) for c in sel}
        for k in range(4):
            self.assertIn(f"stratum_{k}", selected_strata,
                          "a declared stratum was not covered")
        # the residual (no-stratum) candidates are represented
        self.assertTrue(any("risk_stratum" not in c for c in sel),
                        "the mandatory residual stratum was not sampled")
        self.assertLessEqual(len(sel), 100, "soft cap not respected")

    def test_no_declared_strata_degrades_to_random_stratified_not_fail_closed(self):
        # A field/spreadsheet op with NO declared risk_strata must NOT fail
        # closed and must NOT force categories: it degrades to random
        # stratified sampling keyed on the field-op fallback dimensions.
        rng = random.Random(99)
        cands = []
        for i in range(200):
            cands.append({
                "unit_id": f"row{i}",
                "field_name": "Status",
                "validation_status": "valid" if i % 2 == 0 else "invalid",
                "prestate_value_class": "empty" if i % 3 == 0 else "nonempty",
                "protected_status": (i % 10 == 0),
                "confidence_source": "model" if i % 4 else "operator",
            })
        sel = select_coverage_sample(cands, depth=8, floor=25, soft_cap=100, rng=rng)
        self.assertGreaterEqual(len(sel), 25, "floor not honored on degrade path")
        self.assertLessEqual(len(sel), 100)
        # It did not fail closed (empty) and did not return the whole population.
        self.assertTrue(0 < len(sel) < len(cands))
        # Coverage across the validation-status dimension (a fallback stratum).
        vstatuses = {c["validation_status"] for c in sel}
        self.assertEqual(vstatuses, {"valid", "invalid"})

    def test_empty_population_returns_empty(self):
        self.assertEqual(select_coverage_sample([]), [])

    def test_soft_cap_downsample_protects_the_residual_stratum(self):
        # M-1: the soft-cap down-sample must NOT be able to drop every residual/
        # low-confidence representative. Many declared strata overshoot the soft
        # cap; a small residual group must survive the down-sample (the mandatory-
        # residual guarantee holds THROUGH the cap, not just before it).
        rng = random.Random(0)
        cands = []
        for s in range(8):                       # 8 declared strata x 3 = 24 members
            for i in range(3):
                cands.append({"unit_id": f"s{s}_{i}", "risk_stratum": f"stratum_{s}"})
        for i in range(5):                       # 5 residual (no stratum) members
            cands.append({"unit_id": f"res{i}"})  # no risk_stratum key
        # depth 8 covers each 3-member stratum fully -> 24 + 5 residual = 29 selected,
        # well over a soft cap of 10 -> forces the down-sample path.
        sel = select_coverage_sample(cands, depth=8, floor=25, soft_cap=10, rng=rng)
        self.assertEqual(len(sel), 10, "soft cap not respected")
        residual_in_sel = [c for c in sel if "risk_stratum" not in c]
        self.assertEqual(
            len(residual_in_sel), 5,
            "M-1: the down-sample dropped residual representatives — the residual "
            "quota (all 5, within depth+spot-checks and the soft cap) must be protected")


if __name__ == "__main__":
    unittest.main()
