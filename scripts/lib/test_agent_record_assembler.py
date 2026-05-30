"""Tests for the deterministic AgentRecordAssembler (stdlib unittest).

Covers: AgentIntent -> agent-record-dict (code owns id/dirs/tiers/cron, not Claude);
the claim-vs-policy fail-fast — forbidden (R9) and allowed-but-unmapped (R8-class) —
and the duplicate / critical-insufficiency lints. Validates against the REAL
distributed scaffold plan (markdown-CC.json).
"""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scaffold_plan import load_scaffold_plan  # noqa: E402
from build_intent import AgentIntent, ResourceClaims, ConstraintViolation  # noqa: E402
from agent_record_assembler import assemble_agent_records  # noqa: E402

SP = load_scaffold_plan("markdown-CC")


def _ai(**kw):
    base = dict(
        display_name="Researcher", function_summary="Gathers source material.",
        role_intent="Produce verified research briefs.", acceptance_signals=["brief has citations"],
        output_purpose="research brief", criticality_tier="standard",
        resource_claims=ResourceClaims(), confidence="high",
        insufficiency_flags=[], source_spans=["ARCH-2#1"],
    )
    base.update(kw)
    return AgentIntent(**base)


class AgentRecordAssemblerTests(unittest.TestCase):
    def test_happy_path_maps_intent_to_record(self):
        recs = assemble_agent_records([_ai()], SP)
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["id"], "researcher")                       # code-owned: slugified
        self.assertEqual(r["role_description"], "Produce verified research briefs.")
        self.assertEqual(r["criticality_tier"], "standard")
        self.assertEqual(r["primary_model_tier"], "standard")         # code-owned: criticality policy
        self.assertEqual(r["status_model_tier"], "fast")
        self.assertEqual(r["output_directory"], "work/agent_outputs")
        self.assertEqual(r["permitted_write_directories"], ["work/agent_outputs"])
        self.assertEqual(r["additional_context_files"], ["approach.md"])
        self.assertEqual(r["output_format_specification"], "markdown")
        self.assertTrue(r["step_completion_criteria"])
        self.assertTrue(r["task_completion_criteria"])
        self.assertNotIn("requires_external_network", r)              # claims never leak into the record
        self.assertNotIn("cron_cadence", r)                          # not claimed

    def test_cron_only_when_claimed_and_allowed(self):
        recs = assemble_agent_records([_ai(resource_claims=ResourceClaims(requires_cron=True))], SP)
        self.assertIn("cron_cadence", recs[0])
        self.assertTrue(recs[0]["cron_cadence"])

    def test_forbidden_claim_rejected_fail_fast(self):               # R9
        with self.assertRaises(ConstraintViolation) as ctx:
            assemble_agent_records([_ai(resource_claims=ResourceClaims(requires_external_network=True))], SP)
        self.assertEqual(ctx.exception.kind, "resource_claim_forbidden")

    def test_allowed_but_unmapped_claim_rejected(self):              # R8-class
        # a shape that ALLOWS a claim with no deterministic effect must reject, not silently drop
        sp2 = replace(SP, allowed_resource_claims=["requires_cron", "requires_broad_fs_read"])
        with self.assertRaises(ConstraintViolation) as ctx:
            assemble_agent_records([_ai(resource_claims=ResourceClaims(requires_broad_fs_read=True))], sp2)
        self.assertEqual(ctx.exception.kind, "resource_claim_unmapped")

    def test_duplicate_agent_id_rejected(self):
        with self.assertRaises(ConstraintViolation) as ctx:
            assemble_agent_records([_ai(), _ai(function_summary="dup")], SP)
        self.assertEqual(ctx.exception.kind, "duplicate_agent_id")

    def test_critical_agent_with_insufficiency_rejected(self):
        with self.assertRaises(ConstraintViolation) as ctx:
            assemble_agent_records([_ai(criticality_tier="critical", insufficiency_flags=["missing_output_format"])], SP)
        self.assertEqual(ctx.exception.kind, "critical_agent_insufficient")

    def test_records_sorted_by_id(self):
        recs = assemble_agent_records([_ai(display_name="Zeta"), _ai(display_name="Alpha")], SP)
        self.assertEqual([r["id"] for r in recs], ["alpha", "zeta"])


if __name__ == "__main__":
    unittest.main()
