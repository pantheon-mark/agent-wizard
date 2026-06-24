"""The typed Update Advice Contract: recommendation stance is SYSTEM-COMPUTED
from author-declared registry facts (safety_class + tier), never inferred by the LLM and
NEVER keyed on the lifecycle `status` (prerelease is the universal pre-v1 status and carries
no risk signal — keying on it is what produced F-10: the system dissuaded the operator from a
safe fix because it was 'prerelease').

These tests pin the pure function so the trust-critical verdict can't drift back into prose/
inference. Design recorded in the build project's decision records.
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


class UpgradeCheckRenderTests(unittest.TestCase):
    """render_upgrade_check must surface the system-computed advice (what's-new + stance +
    safe command) and OMIT the bare `status` (prerelease) from operator-facing output (D4)."""

    def _result(self):
        from lib.upgrade import UpgradeCheckResult, compute_recommendation
        entry = {
            "foundation_bundle_version": "v0.6.4",
            "release_date": "2026-06-24",
            "status": "prerelease",
            "tier": "patch-behavioral",
            "changelog": "Fixes the receipt-gate false-positives.",
            "safety_class": "safety_fix",
            "recommendation_reason": "Fixes a safety-check bug that interrupted your edits.",
        }
        target = dict(entry)
        target.update(compute_recommendation(entry, tier="patch-behavioral"))
        return UpgradeCheckResult(
            operator_project_path="/x", current_version="v0.6.3",
            available_targets=[target], drift_report=None,
            standing_approval_status="unavailable", notes=[],
        )

    def test_render_omits_prerelease_and_surfaces_advice(self):
        from lib.upgrade import render_upgrade_check
        out = render_upgrade_check(self._result())
        self.assertNotIn("status=prerelease", out, "F-10: bare prerelease status must not show to the operator")
        self.assertNotIn("status=", out)
        self.assertIn("what's new:", out)
        self.assertIn("recommendation: recommend_apply", out)
        self.assertIn("wizard self-upgrade --to v0.6.4 --apply", out)
        self.assertIn("v0.6.4", out)


if __name__ == "__main__":
    unittest.main()
