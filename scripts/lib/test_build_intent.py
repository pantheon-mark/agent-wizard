"""Tests for the build-intent seam (stdlib unittest; pip-install-free).

Covers the narrow interview-semantics layer: BuildIntent (= a derived record +
agent intents), AgentIntent / ResourceClaims (Claude-derived narrow intent only),
the fail-loud ConstraintViolation carrier, and the intent-layer validator.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_intent import (  # noqa: E402
    BuildIntent, AgentIntent, ResourceClaims, ConstraintViolation, validate_build_intent,
)


def _agent_intent(**kw):
    base = dict(
        display_name="Researcher", function_summary="Gathers source material.",
        role_intent="Produce verified research briefs.", acceptance_signals=["brief has citations"],
        output_purpose="research brief", criticality_tier="standard",
        resource_claims=ResourceClaims(), confidence="high",
        insufficiency_flags=[], source_spans=["ARCH-2#1"],
    )
    base.update(kw)
    return AgentIntent(**base)


class BuildIntentTests(unittest.TestCase):
    def test_valid_intent_constructs(self):
        bi = BuildIntent(derived_record={"_audit": {}}, agent_intents=[_agent_intent()])
        validate_build_intent(bi)  # no raise

    def test_unknown_criticality_fails_closed(self):
        with self.assertRaises(ConstraintViolation):
            validate_build_intent(BuildIntent(
                derived_record={"_audit": {}},
                agent_intents=[_agent_intent(criticality_tier="urgent")],
            ))

    def test_empty_display_name_fails_closed(self):
        with self.assertRaises(ConstraintViolation):
            validate_build_intent(BuildIntent(
                derived_record={"_audit": {}},
                agent_intents=[_agent_intent(display_name="")],
            ))

    def test_record_without_audit_fails_closed(self):
        with self.assertRaises(ConstraintViolation):
            validate_build_intent(BuildIntent(derived_record={}, agent_intents=[]))

    def test_resource_claims_default_false(self):
        rc = ResourceClaims()
        self.assertFalse(rc.requires_cron or rc.requires_external_network or rc.requires_broad_fs_read)

    def test_constraint_violation_carries_operator_options(self):
        cv = ConstraintViolation(
            kind="resource_claim_forbidden", subject="Researcher",
            detail="requires_external_network", operator_options=["drop", "change-shape"],
        )
        self.assertEqual(cv.kind, "resource_claim_forbidden")
        self.assertEqual(cv.subject, "Researcher")
        self.assertIn("drop", cv.operator_options)
        self.assertIn("requires_external_network", str(cv))


if __name__ == "__main__":
    unittest.main()
