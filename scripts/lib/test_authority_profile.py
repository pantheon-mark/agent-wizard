"""Tests for the operator authority profile derivation. RED->GREEN.

Covers the ceiling/min autonomy-level logic (NOT additive), the per-class posture that keeps
routine classes autonomous even at the most-locked level (no "ask before everything", no empty
autonomous set), lineage isolation to the authority answers only, the AUTONOMY_LEVEL
classification envelope, and fail-closed enum validation.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from authority_profile import (  # noqa: E402
    AuthorityDimensions, AuthorityProfile, derive_authority, AuthorityProfileError,
)


def _dims(**over):
    base = dict(
        expertise="mixed",
        desired_autonomy="high",
        reversibility_tolerance="high",
        approval_latency="async-business-hours",
        domain_risk="low",
        trust_posture="calibrated",
        review_capability="no",
    )
    base.update(over)
    return AuthorityDimensions(**base)


class AutonomyLevelTests(unittest.TestCase):
    def test_all_permissive_gives_level_3(self):
        p = derive_authority(_dims(desired_autonomy="high", domain_risk="low",
                                    reversibility_tolerance="high", trust_posture="calibrated"))
        self.assertEqual(p.autonomy_level, "3")

    def test_high_risk_lowrev_probationary_lands_at_1_not_below(self):
        # The most-restrictive corner: must land at 1 via min (floored), never an unusable <1.
        p = derive_authority(_dims(desired_autonomy="high", domain_risk="high",
                                    reversibility_tolerance="low", trust_posture="probationary"))
        self.assertEqual(p.autonomy_level, "1")

    def test_single_high_risk_cap_binds_via_min_not_additive(self):
        # All else permissive; only domain_risk=high. min(3,1,3,3)=1. (Additive would also hit 1 here,
        # but the point is a SINGLE binding cap controls — no stacking artifacts.)
        p = derive_authority(_dims(desired_autonomy="high", domain_risk="high",
                                    reversibility_tolerance="high", trust_posture="calibrated"))
        self.assertEqual(p.autonomy_level, "1")

    def test_desired_autonomy_is_itself_a_ceiling(self):
        # low desired stays 1 even if every constraint is permissive (operator preference caps too).
        p = derive_authority(_dims(desired_autonomy="low", domain_risk="low",
                                    reversibility_tolerance="high", trust_posture="established"))
        self.assertEqual(p.autonomy_level, "1")

    def test_probationary_caps_at_2(self):
        p = derive_authority(_dims(desired_autonomy="high", domain_risk="low",
                                    reversibility_tolerance="high", trust_posture="probationary"))
        self.assertEqual(p.autonomy_level, "2")


class HitlPostureTests(unittest.TestCase):
    def test_routine_classes_autonomous_even_at_level_1(self):
        # At the most-locked level the autonomous set is non-empty and keeps
        # class #4 (artifact quality) + #5 (workflow/session hygiene) — never "ask before everything".
        p = derive_authority(_dims(desired_autonomy="high", domain_risk="high",
                                    reversibility_tolerance="low", trust_posture="probationary"))
        self.assertEqual(p.autonomy_level, "1")
        self.assertIn(4, p.autonomous_classes)
        self.assertIn(5, p.autonomous_classes)
        self.assertTrue(p.autonomous_classes)

    def test_security_class_1_always_ask_first(self):
        # class #1 (security/data/destructive/irreversible) never autonomous, even at level 3.
        p = derive_authority(_dims(desired_autonomy="high", domain_risk="low",
                                    reversibility_tolerance="high", trust_posture="established"))
        self.assertEqual(p.autonomy_level, "3")
        self.assertNotIn(1, p.autonomous_classes)
        self.assertIn(1, p.ask_first_classes)

    def test_autonomous_and_ask_first_partition_the_eight_classes(self):
        p = derive_authority(_dims())
        self.assertEqual(p.autonomous_classes | p.ask_first_classes, frozenset(range(1, 9)))
        self.assertEqual(p.autonomous_classes & p.ask_first_classes, frozenset())

    def test_higher_level_is_a_superset_of_lower_level_autonomy(self):
        lo = derive_authority(_dims(desired_autonomy="low"))    # level 1
        hi = derive_authority(_dims(desired_autonomy="high"))   # level 3
        self.assertTrue(lo.autonomous_classes <= hi.autonomous_classes)


class LineageAndEnvelopeTests(unittest.TestCase):
    def test_source_question_ids_are_authority_answers_only(self):
        p = derive_authority(_dims())
        self.assertTrue(p.source_question_ids)
        # Vision / Phase-1 question-IDs never leak into the authority lineage.
        self.assertNotIn("V-1", p.source_question_ids)
        self.assertNotIn("P1-2", p.source_question_ids)
        for q in ("UP-3", "DR", "REV"):
            self.assertIn(q, p.source_question_ids)

    def test_autonomy_level_envelope_is_a_classification_decision(self):
        # the auto->classification flip target: classification + decision + closed_value + non-empty sources.
        env = derive_authority(_dims()).autonomy_level_envelope()
        self.assertEqual(env["_derivation_class"], "classification")
        self.assertIs(env["_decision_field"], True)
        self.assertEqual(env["_decision_kind"], "closed_value")
        self.assertTrue(env["_source_question_ids"])  # non-empty => satisfies field_manifest source_required


class FailClosedTests(unittest.TestCase):
    def test_out_of_enum_domain_risk_fails_closed(self):
        with self.assertRaises(AuthorityProfileError):
            derive_authority(_dims(domain_risk="catastrophic"))

    def test_out_of_enum_desired_autonomy_fails_closed(self):
        with self.assertRaises(AuthorityProfileError):
            derive_authority(_dims(desired_autonomy="YOLO"))


if __name__ == "__main__":
    unittest.main()
