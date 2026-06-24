"""S2.46 — the typed Update Advice Contract: recommendation stance is SYSTEM-COMPUTED
from author-declared registry facts (safety_class + tier), never inferred by the LLM and
NEVER keyed on the lifecycle `status` (prerelease is the universal pre-v1 status and carries
no risk signal — keying on it is what produced F-10: the system dissuaded the operator from a
safe fix because it was 'prerelease').

These tests pin the pure function so the trust-critical verdict can't drift back into prose/
inference. Cross-vendor design: external_review/s2.46_crossvendor_decisions_2026-06-24.md (D1).
"""

import unittest

from lib.upgrade import compute_recommendation  # noqa: E402


def _entry(version="v0.6.4", **kw):
    e = {"foundation_bundle_version": version}
    e.update(kw)
    return e


class RecommendationStanceTests(unittest.TestCase):

    def test_safety_fix_patch_is_recommend_apply(self):
        r = compute_recommendation(_entry(safety_class="safety_fix",
                                          recommendation_reason="Fixes the receipt-gate false-positives."),
                                   tier="patch-behavioral")
        self.assertEqual(r["recommendation_stance"], "recommend_apply")
        self.assertFalse(r["requires_operator_review"])
        self.assertIn("Fixes the receipt-gate", r["recommendation_reason"])

    def test_reliability_fix_is_recommend_apply(self):
        r = compute_recommendation(_entry(safety_class="reliability_fix"), tier="patch-behavioral")
        self.assertEqual(r["recommendation_stance"], "recommend_apply")

    def test_routine_improvement_is_neutral_offer(self):
        r = compute_recommendation(_entry(safety_class="routine_improvement"), tier="minor-additive")
        self.assertEqual(r["recommendation_stance"], "neutral_offer")
        self.assertFalse(r["requires_operator_review"])

    def test_breaking_change_safety_class_is_manual_review(self):
        r = compute_recommendation(_entry(safety_class="breaking_change"), tier="minor-additive")
        self.assertEqual(r["recommendation_stance"], "manual_review")
        self.assertTrue(r["requires_operator_review"])

    def test_major_breaking_tier_forces_manual_review_even_if_safety_fix(self):
        # tier guard: a breaking tier overrides an over-optimistic safety_class.
        r = compute_recommendation(_entry(safety_class="safety_fix"), tier="major-breaking")
        self.assertEqual(r["recommendation_stance"], "manual_review")
        self.assertTrue(r["requires_operator_review"])

    def test_unknown_or_missing_safety_class_is_manual_review_conservative(self):
        self.assertEqual(compute_recommendation(_entry(), tier="patch-behavioral")["recommendation_stance"],
                         "manual_review")
        self.assertEqual(compute_recommendation(_entry(safety_class="unknown"), tier="patch-behavioral")["recommendation_stance"],
                         "manual_review")

    def test_yanked_is_do_not_apply(self):
        r = compute_recommendation(_entry(safety_class="safety_fix", yanked=True), tier="patch-behavioral")
        self.assertEqual(r["recommendation_stance"], "do_not_apply")
        self.assertTrue(r["requires_operator_review"])

    def test_stance_NEVER_keys_on_prerelease_status(self):
        # THE F-10 REGRESSION: a safe fix marked status=prerelease must STILL be recommend_apply.
        r = compute_recommendation(_entry(safety_class="safety_fix", status="prerelease"),
                                   tier="patch-behavioral")
        self.assertEqual(r["recommendation_stance"], "recommend_apply",
                         "prerelease status must NOT downgrade a safe fix (this is F-10)")

    def test_actionable_command_is_self_upgrade_apply(self):
        # The universally-safe command (refreshes the toolkit then applies; no-op refresh if current).
        r = compute_recommendation(_entry(version="v0.6.4", safety_class="safety_fix"), tier="patch-behavioral")
        self.assertEqual(r["actionable_command"], "wizard self-upgrade --to v0.6.4 --apply")
        self.assertIn("upgrade-plan --to v0.6.4", r["preview_hint"])  # preview != apply (D3)


if __name__ == "__main__":
    unittest.main()
