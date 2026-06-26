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

    def test_auto_values_gap_fill_supplies_missing_global_and_routes(self):
        # The auto-global overlay fills a global project() left out (no interview step records the
        # auto-class config) AND drives routing: a record missing FOUNDATION_ONLY_MODE + the overlay
        # = foundation-only. This is the emission-boundary supply the live emit path now performs.
        bi = BuildIntent(derived_record=_dr(defer={"FOUNDATION_ONLY_MODE"}), agent_intents=[])
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers,
                                      auto_values={"FOUNDATION_ONLY_MODE": "true"})
        validate_emission_plan(plan, EP_CONTRACT)
        self.assertTrue(plan["foundation_only_mode"])
        self.assertEqual(plan["foundation_doc_inputs"]["FOUNDATION_ONLY_MODE"], "true")

    def test_auto_values_do_not_override_projected(self):
        # Precedence mirror of the preview path: a value project() produced from the transcript WINS;
        # the auto overlay is a gap-fill default, never an override.
        bi = BuildIntent(derived_record=_dr(), agent_intents=[_ai()])   # _dr carries SYSTEM_SHAPE
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers,
                                      auto_values={"SYSTEM_SHAPE": "WRONG-SHAPE"})
        self.assertEqual(plan["foundation_doc_inputs"]["SYSTEM_SHAPE"], "markdown-CC")

    def test_auto_values_rejects_non_auto_global_key(self):
        # Fail-closed backdoor guard: a key outside the shape's declared auto_global_fields must NOT
        # be injectable into foundation_doc_inputs — this is what keeps the overlay from reopening
        # the retired raw-foundation_doc_inputs injection path.
        bi = BuildIntent(derived_record=_dr(), agent_intents=[_ai()])
        with self.assertRaises(ValueError):
            assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers,
                                   auto_values={"VISION_PURPOSE": "smuggled content"})

    def test_ceremony_maturity_rows_seed_probationary(self):
        from emission_plan_assembler import _ceremony_maturity_rows
        rows = _ceremony_maturity_rows({})
        self.assertIn("financial", rows)
        self.assertIn("external-communications", rows)
        self.assertIn("| probationary |", rows)
        self.assertNotIn("graduated", rows)


class WritesBackPermissionWiringTests(unittest.TestCase):
    """Task 7 — derive_permission_map is wired onto the assembler (enforced) path.

    The interview captures a writes-back dependency (boundary_output) with an
    owner_agent_id; the assembler must fold the derived external-write grant into the
    OWNING agent's permitted_write_directories AND the orchestrator's, and render the
    AGENT_PERMISSION_ROWS table (the single-view audit surface in project_instructions.md)
    from the derived map. A plan with NO writes-back dependency yields no external-write
    grant.
    """

    def _writes_back_dep(self, owner="researcher", surface="company_tracker"):
        import json
        return json.dumps([{
            "id": "tracker", "name": surface, "type": "Google Sheet",
            "roles": ["boundary_output"], "owner_agent_id": owner,
        }])

    def _read_only_dep(self):
        import json
        return json.dumps([{
            "id": "feed", "name": "rss_feed", "type": "RSS",
            "roles": ["boundary_input"],
        }])

    def test_writes_back_grant_reaches_owning_agent_permitted_writes(self):
        # B + C: owner_agent_id populated end-to-end -> the OWNING agent's emitted
        # permitted_write_directories carries the external-write surface.
        bi = BuildIntent(
            derived_record=_dr(overrides={"EXTERNAL_DEPENDENCY_IDENTITY": self._writes_back_dep()}),
            agent_intents=[_ai()],
        )
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        validate_emission_plan(plan, EP_CONTRACT)
        researcher = next(a for a in plan["agents"] if a["id"] == "researcher")
        self.assertIn("company_tracker", researcher["permitted_write_directories"])

    def test_orchestrator_carveout_in_derived_map_on_emit_path(self):
        # C (enforced surface): the derived permission map the assembler applies carries the
        # orchestrator carve-out for the writes-back surface. Proven by re-deriving the map from
        # the SAME plan inputs the assembler used and asserting the carve-out — the assembler's
        # _apply_permission_map then folds the per-agent grants into the emitted agent records.
        from scaffold_plan import derive_permission_map
        bi = BuildIntent(
            derived_record=_dr(overrides={"EXTERNAL_DEPENDENCY_IDENTITY": self._writes_back_dep()}),
            agent_intents=[_ai()],
        )
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        import json
        deps = json.loads(plan["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"])
        pmap = derive_permission_map(SP, plan["agents"], deps)
        self.assertIn("company_tracker", pmap["orchestrator"])
        self.assertIn("company_tracker", pmap["researcher"])

    def test_non_owning_agent_does_not_get_surface(self):
        # No dead grant: an agent that does not own the writes-back surface must not get it.
        bi = BuildIntent(
            derived_record=_dr(overrides={"EXTERNAL_DEPENDENCY_IDENTITY":
                                          self._writes_back_dep(owner="someone-else")}),
            agent_intents=[_ai()],
        )
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        researcher = next(a for a in plan["agents"] if a["id"] == "researcher")
        self.assertNotIn("company_tracker", researcher["permitted_write_directories"])

    def test_read_only_dependency_yields_no_write_grant(self):
        # A boundary_input-only dependency must never produce an external-write grant.
        bi = BuildIntent(
            derived_record=_dr(overrides={"EXTERNAL_DEPENDENCY_IDENTITY": self._read_only_dep()}),
            agent_intents=[_ai()],
        )
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        researcher = next(a for a in plan["agents"] if a["id"] == "researcher")
        self.assertNotIn("rss_feed", researcher["permitted_write_directories"])

    def test_no_dependencies_preserves_base_permitted_writes(self):
        # With no dependency record, the fold is a no-op for grants but still applies the
        # derived map (base paths preserved) — proving the derivation runs on every plan.
        bi = BuildIntent(derived_record=_dr(), agent_intents=[_ai()])
        plan = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        researcher = next(a for a in plan["agents"] if a["id"] == "researcher")
        self.assertIn("work/agent_outputs", researcher["permitted_write_directories"])


if __name__ == "__main__":
    unittest.main()
