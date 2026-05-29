"""Tests for the emission-plan loader/validator (stdlib unittest; pip-install-free).

Covers: a valid plan parses to a typed EmissionPlan, and each load-bearing
invariant fails closed (I3 authority basis/source coupling, I4 unique paths,
I6 tier-keys-not-model-strings, I7 foundation-only, I8 source self-containment,
I9 path coverage, I10 tier-in-map). Validates against the REAL distributed
contract (emission-plan-contract-v1.json).
"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from emission_plan import (  # noqa: E402
    EmissionPlan,
    EmissionPlanError,
    load_contract,
    default_contract_path,
    validate_emission_plan,
)


# Complete, boundary-clean foundation-doc placeholder set for the demo plan. Every
# {{KEY}} referenced by the 6 v0.4.0 foundation templates appears here so the
# full-system path can emit foundation docs without a fail-fast on a missing key.
# Values are neutral demo content (NO build provenance — these land in the emitted
# operator tree, which is provenance-scanned) and deterministic (no clock).
_FOUNDATION_DOC_INPUTS = {
    "VISION_PURPOSE": "Help the demo operator keep track of incoming requests.",
    "VISION_GOALS": "Capture requests, triage them, and surface a daily summary.",
    "VISION_AUDIENCE_OUTPUTS": "A solo operator; outputs are short markdown summaries.",
    "VISION_SCOPE_BOUNDARY": "In scope: triage and summary. Out of scope: sending replies.",
    "VISION_CONSTRAINTS": "Runs locally; no external data leaves the machine.",
    "VISION_SUCCESS_CRITERIA": "Every request is triaged within a day.",
    "APPROACH_SOLUTION_BRIEF": "A small set of agents read a work queue and write summaries.",
    "MVP_CORE_FUNCTION": "Read the queue and produce a triage summary.",
    "MVP_MINIMUM_VIABLE_STATE": "One agent triages; one agent summarizes.",
    "MVP_SUCCESS_CONDITION": "The operator gets one accurate summary per run.",
    "ORCHESTRATION_MODEL": "A single coordinator routes work to specialist agents.",
    "AGENT_ROSTER_ROWS": "| researcher | Gathers source material | standard |",
    "HITL_MAP_ROWS": "| triage | operator approves before send | required |",
    "INTEGRATIONS": "None at this stage; everything is local files.",
    "SCALE_TIER": "small",
    "SCALE_TIER_BASIS": "single operator, low volume",
    "SCALE_TIER_RATIONALE": "Low request volume needs no concurrency.",
    "SYSTEM_SHAPE": "markdown-CC",
    "FOUNDATION_ONLY_MODE": "false",
    "AUTONOMY_LEVEL": "2",
    "DRIFT_ANALYSIS_CADENCE": "weekly",
    "WIZARD_VERSION": "v0.4.0",
    "EXECUTION_SEQUENCE": "1. Triage the queue. 2. Summarize. 3. Notify the operator.",
    "BUILD_PHASES_ROWS": "| 1 | Stand up the queue and agents | done |",
    "CURRENT_SPRINT_NUMBER": "1",
    "LAST_UPDATED_DATE": "(set at operator setup)",
    "LAST_UPDATED_TRIGGER": "operator setup",
    "AGENT_SPECIFIC_TESTS": "Researcher returns a non-empty summary for a known queue.",
    "TASK_COMPLETION_CHECKLISTS": "- Queue read\n- Summary written\n- Operator notified",
    "COMPLIANCE_GAPS_CONTENT": "No regulated data handled at this stage.",
}


def _valid_plan() -> dict:
    """A minimal plan that satisfies every invariant (I1-I10)."""
    return {
        "schema_version": "emission-plan-v1",
        "system_shape": "markdown-CC",
        "foundation_only_mode": False,
        "project_name": "demo",
        "bundle_version": "v0.4.0",
        "generator_version": "0" * 40,
        "authority_profile": {
            "id": "provisional_operator_approval_v0",
            "posture": "low-autonomy-operator-approval",
            "source": "wizard-default",
            "expires_on_trigger": "operator-authority-profile-available",
        },
        "model_tiers": {"high": "model-high", "standard": "model-standard", "fast": "model-fast"},
        "control_plane": {
            "queue_path": "work/work_queue.md",
            "lock_path": "maintenance_mode.md",
            "handoff_dir": "agents/handoffs",
            "checkpoint_dir": "agents/checkpoints",
            "cron_config_path": "agents/cron/cron_config.md",
            "session_state_path": "SESSION_STATE.md",
            "session_bootstrap_path": "session_bootstrap.md",
            "session_log_path": "logs/session_log.md",
            "error_log_path": "logs/error_log.md",
            "notification_log_path": "logs/notification_log.md",
        },
        "control_plane_runtime_created": [
            "maintenance_mode.md", "agents/handoffs", "agents/checkpoints", "work/agent_outputs",
        ],
        "orchestrator": {
            "model_tier_high": "high", "model_tier_standard": "standard",
            "model_tier_fast": "fast", "schedule": "0 * * * *",
        },
        "agents": [
            {
                "id": "researcher", "role_description": "Gathers source material.",
                "criticality_tier": "standard", "primary_model_tier": "standard",
                "status_model_tier": "fast", "permitted_write_directories": ["work/agent_outputs"],
                "additional_context_files": ["approach.md"], "step_completion_criteria": "step done",
                "task_completion_criteria": "task done", "output_format_specification": "markdown",
                "output_directory": "work/agent_outputs",
            }
        ],
        "foundation_doc_inputs": _FOUNDATION_DOC_INPUTS,
        "corpus_cells": [
            {
                "cell_id": "cell-applies-all", "emission_target": ["quality/rules_library.md"],
                "emission_posture": "install-verbatim", "authority_gate": "applies-all",
                "authority_basis": "not_applicable", "authority_source": "not_applicable",
                "source_type": "inline_payload", "payload": "A rule.",
            },
            {
                "cell_id": "cell-gated", "emission_target": ["CLAUDE.md"],
                "emission_posture": "install-verbatim", "authority_gate": "high-risk-operator-approved",
                "authority_basis": "provisional_default", "authority_source": "delegated",
                "source_type": "template_variant", "template_variant_key": "markdown-CC",
            },
        ],
        "emitted_files": [
            {"path": p, "managed_by": "wizard", "local_modifications": "not_recommended",
             "merge_strategy": "warn_on_drift", "source_refs": []}
            for p in [
                "work/work_queue.md", "agents/cron/cron_config.md", "SESSION_STATE.md",
                "session_bootstrap.md", "logs/session_log.md", "logs/error_log.md",
                "logs/notification_log.md", "quality/rules_library.md", "CLAUDE.md",
                "agents/prompts/researcher.md",
            ]
        ],
        "template_variants": [
            {"cell_id": "cell-gated", "system_shape": "markdown-CC",
             "template_path": "templates/corpus/markdown-CC/cell-gated.md"},
        ],
    }


class EmissionPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _expect_fail(self, plan, invariant):
        with self.assertRaises(EmissionPlanError) as ctx:
            validate_emission_plan(plan, self.contract)
        self.assertIn(invariant, str(ctx.exception))

    def test_valid_plan_parses(self):
        ep = validate_emission_plan(_valid_plan(), self.contract)
        self.assertIsInstance(ep, EmissionPlan)
        self.assertEqual(ep.project_name, "demo")
        self.assertEqual(len(ep.agents), 1)
        self.assertEqual(len(ep.corpus_cells), 2)
        self.assertEqual(ep.authority_profile.posture, "low-autonomy-operator-approval")

    def test_I3_applies_all_with_provisional_basis_fails(self):
        p = copy.deepcopy(_valid_plan())
        p["corpus_cells"][0]["authority_basis"] = "provisional_default"
        self._expect_fail(p, "I3")

    def test_I3_gated_with_not_applicable_basis_fails(self):
        p = copy.deepcopy(_valid_plan())
        p["corpus_cells"][1]["authority_basis"] = "not_applicable"
        self._expect_fail(p, "I3")

    def test_I3_gated_with_not_applicable_source_fails(self):
        p = copy.deepcopy(_valid_plan())
        p["corpus_cells"][1]["authority_source"] = "not_applicable"
        self._expect_fail(p, "I3")

    def test_I4_duplicate_emitted_path_fails(self):
        p = copy.deepcopy(_valid_plan())
        p["emitted_files"].append(dict(p["emitted_files"][0]))
        self._expect_fail(p, "I4")

    def test_I6_literal_model_string_fails(self):
        p = copy.deepcopy(_valid_plan())
        p["agents"][0]["primary_model_tier"] = "claude-opus-4-8"
        self._expect_fail(p, "I6")

    def test_I7_foundation_only_with_agents_fails(self):
        p = copy.deepcopy(_valid_plan())
        p["foundation_only_mode"] = True
        self._expect_fail(p, "I7")

    def test_I8_inline_payload_empty_fails(self):
        p = copy.deepcopy(_valid_plan())
        p["corpus_cells"][0]["payload"] = ""
        self._expect_fail(p, "I8")

    def test_I8_template_variant_missing_registry_fails(self):
        p = copy.deepcopy(_valid_plan())
        p["template_variants"] = []
        self._expect_fail(p, "I8")

    def test_I9_uncovered_control_plane_path_fails(self):
        p = copy.deepcopy(_valid_plan())
        p["emitted_files"] = [ef for ef in p["emitted_files"] if ef["path"] != "work/work_queue.md"]
        self._expect_fail(p, "I9")

    def test_I10_tier_not_in_model_tiers_fails(self):
        p = copy.deepcopy(_valid_plan())
        del p["model_tiers"]["fast"]  # 'fast' is still a valid tier key (passes I6) but absent from the map
        self._expect_fail(p, "I10")

    def test_base_hash_in_input_plan_rejected(self):
        p = copy.deepcopy(_valid_plan())
        p["emitted_files"][0]["base_hash"] = "sha256:deadbeef"
        self._expect_fail(p, "I1")


if __name__ == "__main__":
    unittest.main()
