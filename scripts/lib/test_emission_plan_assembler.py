"""Tests for the deterministic EmissionPlanAssembler (stdlib unittest).

Covers: a BuildIntent assembles into a plan that validate_emission_plan accepts;
foundation_doc_inputs is projector-produced (deferred fields excluded); routing uses
ONLY the projected inputs (a deferred FOUNDATION_ONLY_MODE does not route foundation-only);
a forbidden resource claim fails loud; an invalid derived record fails even when the
assembler is called directly (caller-independent safety); the Day-2 current_state seam
accepts None and rejects a value; foundation-only yields no agents. Validates against the
REAL contracts + scaffold plan + corpus pack.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_emission_plan import _FOUNDATION_DOC_INPUTS  # noqa: E402  (neutral demo set; no provenance)
from scaffold_plan import load_scaffold_plan  # noqa: E402
from build_intent import BuildIntent, AgentIntent, ResourceClaims, ConstraintViolation  # noqa: E402
from corpus_loader import load_corpus_pack  # noqa: E402
from derived_record import DerivedRecordError  # noqa: E402
from emission_plan import validate_emission_plan, load_contract, default_contract_path  # noqa: E402
from emission_plan_assembler import assemble_emission_plan  # noqa: E402

SP = load_scaffold_plan("markdown-CC")
CORPUS = load_corpus_pack()
EP_CONTRACT = load_contract(default_contract_path())


def _env(cstate="accepted"):
    return {"_source": "operator-content", "_derivation_class": "extraction", "_decision_field": False,
            "_decision_kind": "none", "_confirmation_state": cstate, "_confirmed_at": "2026-05-30"}


def _dr(overrides=None, defer=()):
    inp = dict(_FOUNDATION_DOC_INPUTS)
    if overrides:
        inp.update(overrides)
    rec = dict(inp)
    rec["_audit"] = {k: _env("deferred_not_emittable" if k in defer else "accepted") for k in inp}
    return rec


def _ai(**kw):
    base = dict(display_name="Researcher", function_summary="Gathers source material.",
                role_intent="Gathers source material.", acceptance_signals=["non-empty summary"],
                output_purpose="summary", criticality_tier="standard", resource_claims=ResourceClaims(),
                confidence="high", insufficiency_flags=[], source_spans=["ARCH-2#1"])
    base.update(kw)
    return AgentIntent(**base)


class EmissionPlanAssemblerTests(unittest.TestCase):
    def test_assembled_plan_validates(self):
        bi = BuildIntent(derived_record=_dr(), agent_intents=[_ai()])
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        validate_emission_plan(plan, EP_CONTRACT)          # I1-I10 accept -> no raise
        self.assertEqual(plan["system_shape"], "markdown-CC")
        self.assertFalse(plan["foundation_only_mode"])
        self.assertEqual(plan["agents"][0]["id"], "researcher")
        # C-002: agent prompt + script paths are in emitted_files (correct names)
        paths = {ef["path"] for ef in plan["emitted_files"]}
        self.assertIn("agents/prompts/researcher_prompt.md", paths)
        self.assertIn("agents/scripts/researcher.sh", paths)

    def test_foundation_doc_inputs_are_projector_produced(self):
        # a deferred field must NOT reach foundation_doc_inputs (acceptance ii, unit-level)
        bi = BuildIntent(derived_record=_dr(overrides={"EXTRA": "x"}, defer={"EXTRA"}), agent_intents=[_ai()])
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        self.assertNotIn("EXTRA", plan["foundation_doc_inputs"])

    def test_deferred_foundation_only_does_not_route(self):   # C-004
        # FOUNDATION_ONLY_MODE=true but DEFERRED -> excluded from fdi -> must NOT route foundation-only
        bi = BuildIntent(derived_record=_dr(overrides={"FOUNDATION_ONLY_MODE": "true"},
                                            defer={"FOUNDATION_ONLY_MODE"}), agent_intents=[_ai()])
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        self.assertFalse(plan["foundation_only_mode"])
        self.assertEqual(len(plan["agents"]), 1)

    def test_forbidden_claim_fails_loud(self):                # R9 propagation
        bad = BuildIntent(derived_record=_dr(),
                          agent_intents=[_ai(resource_claims=ResourceClaims(requires_external_network=True))])
        with self.assertRaises(ConstraintViolation):
            assemble_emission_plan(bad, SP, CORPUS, model_tiers=SP.model_tiers)

    def test_direct_invalid_record_fails(self):               # C-005 / C-011: assembler seam is safe
        invalid = {"FOO": "bar", "_audit": {}}               # payload key with no envelope -> DR-1
        with self.assertRaises(DerivedRecordError):
            assemble_emission_plan(BuildIntent(derived_record=invalid, agent_intents=[]), SP, CORPUS,
                                   model_tiers=SP.model_tiers)

    def test_day2_signature_accepts_none_rejects_value(self):  # R11
        bi = BuildIntent(derived_record=_dr(), agent_intents=[_ai()])
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers, current_state=None)
        validate_emission_plan(plan, EP_CONTRACT)
        with self.assertRaises(NotImplementedError):
            assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers, current_state={"any": "plan"})

    def test_foundation_only_plan_has_no_agents(self):
        bi = BuildIntent(derived_record=_dr(overrides={"FOUNDATION_ONLY_MODE": "true"}), agent_intents=[])
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        validate_emission_plan(plan, EP_CONTRACT)
        self.assertTrue(plan["foundation_only_mode"])
        self.assertEqual(plan["agents"], [])


if __name__ == "__main__":
    unittest.main()
