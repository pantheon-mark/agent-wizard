"""Tests for derived_record.py — the derived-record structural-invariant validator.

Fixtures are neutral synthetic content with real field names + all derivation
classes + the decoupling cases (operator-preference-classification; narrative-but-
decision; label-map placeholder; TBD; ambiguous; deferred). No operator content.
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import derived_record as dr


def _valid_record():
    """A representative derived record that satisfies every invariant."""
    record = {
        "_provenance": "synthetic test fixture",
        "_schema_extension_points": [],
        "_source_taxonomy": {},
        "WIZARD_VERSION": "v0.3.0",
        "VISION_PURPOSE": "A system that helps a small team track customer follow-ups.",
        "INTEGRATIONS": "Reads a shared spreadsheet and a local folder; portal access is operator-mediated.",
        "APPROACH_SOLUTION_BRIEF": "A back-of-house layer of agents handling follow-up tracking and reminders.",
        "SCALE_TIER": "small",
        "AUTONOMY_LEVEL": "2",
        "AUTONOMOUS_ACTIONS": "The system drafts updates and reads provided files (illustrative, not exhaustive).",
        "DRIFT_ANALYSIS_CADENCE": "twice-weekly initially; weekly thereafter.",
        "OPERATOR_EMAIL": "<operator email>",
        "NTFY_TOPIC": "TBD; topic to be provided later.",
        "DEFERRED_FIELD": "",
        "AMBIG_FIELD": "a value whose source class is genuinely unclear.",
        "_audit": {
            "WIZARD_VERSION": {"_source": "auto", "_derivation_class": "auto",
                               "_decision_field": False, "_decision_kind": "none"},
            "VISION_PURPOSE": {"_source": "operator-content", "_derivation_class": "extraction",
                               "_decision_field": False, "_decision_kind": "none",
                               "_confirmation_state": "accepted", "_confirmed_at": "2026-01-01"},
            "INTEGRATIONS": {"_source": "operator-content", "_derivation_class": "extraction",
                             "_decision_field": True, "_decision_kind": "integration_boundary",
                             "_confirmation_state": "accepted", "_confirmed_at": "2026-01-01"},
            "APPROACH_SOLUTION_BRIEF": {"_source": "claude-derived-operator-confirmed", "_derivation_class": "synthesis",
                                        "_decision_field": False, "_decision_kind": "none",
                                        "_derivation_inputs": ["VISION_PURPOSE", "INTEGRATIONS"],
                                        "_confirmation_state": "accepted", "_confirmed_at": "2026-01-01"},
            "SCALE_TIER": {"_source": "claude-derived-operator-confirmed", "_derivation_class": "classification",
                           "_decision_field": True, "_decision_kind": "closed_value",
                           "_derivation_inputs": ["INTEGRATIONS"],
                           "_confirmation_state": "accepted", "_confirmed_at": "2026-01-01"},
            "AUTONOMY_LEVEL": {"_source": "operator-preference", "_derivation_class": "classification",
                               "_decision_field": True, "_decision_kind": "closed_value",
                               "_source_question_ids": ["UP-AUTONOMY"],
                               "_confirmation_state": "accepted", "_confirmed_at": "2026-01-01"},
            "AUTONOMOUS_ACTIONS": {"_source": "claude-derived-operator-confirmed", "_derivation_class": "policy",
                                   "_decision_field": True, "_decision_kind": "policy_rule",
                                   "_derivation_inputs": ["AUTONOMY_LEVEL"],
                                   "_confirmation_state": "accepted_with_adjustments", "_confirmed_at": "2026-01-01",
                                   "_refinement_note": "illustrative-not-exhaustive prefix added"},
            "DRIFT_ANALYSIS_CADENCE": {"_source": "operator-preference", "_derivation_class": "extraction",
                                       "_decision_field": True, "_decision_kind": "schedule",
                                       "_source_question_ids": ["DRIFT-1"],
                                       "_confirmation_state": "accepted", "_confirmed_at": "2026-01-01",
                                       "_phases": {"initial": "twice-weekly", "steady": "weekly"}},
            "OPERATOR_EMAIL": {"_source": "operator-content", "_derivation_class": "extraction",
                               "_decision_field": False, "_decision_kind": "none",
                               "_label_map_reference": "label-map.json _placeholders.<operator email>",
                               "_confirmation_state": "accepted", "_confirmed_at": "2026-01-01"},
            "NTFY_TOPIC": {"_source": "operator-preference", "_derivation_class": "extraction",
                           "_decision_field": False, "_decision_kind": "none",
                           "_revisit_trigger": "when the operator sets up the topic",
                           "_confirmation_state": "accepted", "_confirmed_at": "2026-01-01"},
            "DEFERRED_FIELD": {"_source": "operator-preference", "_derivation_class": "extraction",
                               "_decision_field": False, "_decision_kind": "none",
                               "_confirmation_state": "deferred_not_emittable"},
            "AMBIG_FIELD": {"_source": "ambiguous", "_derivation_class": "extraction",
                            "_decision_field": False, "_decision_kind": "none",
                            "_source_candidates": ["operator-preference", "claude-derived-operator-confirmed"],
                            "_confirmation_state": "accepted", "_confirmed_at": "2026-01-01"},
        },
    }
    return record


class TestDerivedRecordValid(unittest.TestCase):
    def setUp(self):
        self.contract = dr.load_contract(dr.default_contract_path())

    def test_valid_record_passes(self):
        dr.validate_derived_record(_valid_record(), self.contract)  # no raise

    def test_deferred_field_empty_content_allowed(self):
        rec = _valid_record()
        # DEFERRED_FIELD has empty content but is deferred_not_emittable — allowed.
        dr.validate_derived_record(rec, self.contract)

    def test_annotation_key_allowed(self):
        rec = _valid_record()
        rec["_audit"]["VISION_PURPOSE"]["_clarification_note"] = "added during review"
        rec["_audit"]["VISION_PURPOSE"]["_decision_record"] = "ratified"
        dr.validate_derived_record(rec, self.contract)


class TestDerivedRecordInvariants(unittest.TestCase):
    def setUp(self):
        self.contract = dr.load_contract(dr.default_contract_path())

    def _expect(self, rec, code):
        with self.assertRaises(dr.DerivedRecordError) as ctx:
            dr.validate_derived_record(rec, self.contract)
        self.assertIn(code, str(ctx.exception))

    def test_dr1_missing_required_envelope_key(self):
        rec = _valid_record()
        del rec["_audit"]["VISION_PURPOSE"]["_derivation_class"]
        self._expect(rec, "DR-1")

    def test_dr1_payload_without_audit(self):
        rec = _valid_record()
        rec["EXTRA_FIELD"] = "x"
        self._expect(rec, "DR-1")

    def test_dr1_audit_without_payload(self):
        rec = _valid_record()
        rec["_audit"]["GHOST"] = {"_source": "auto", "_derivation_class": "auto",
                                  "_decision_field": False, "_decision_kind": "none"}
        self._expect(rec, "DR-1")

    def test_dr2_bad_source_enum(self):
        rec = _valid_record()
        rec["_audit"]["VISION_PURPOSE"]["_source"] = "made-up"
        self._expect(rec, "DR-2")

    def test_dr2_decision_field_not_bool(self):
        rec = _valid_record()
        rec["_audit"]["VISION_PURPOSE"]["_decision_field"] = "yes"
        self._expect(rec, "DR-2")

    def test_dr3_claude_derived_without_confirmation(self):
        rec = _valid_record()
        del rec["_audit"]["APPROACH_SOLUTION_BRIEF"]["_confirmation_state"]
        del rec["_audit"]["APPROACH_SOLUTION_BRIEF"]["_confirmed_at"]
        self._expect(rec, "DR-3")

    def test_dr4_operator_preference_with_derivation_inputs(self):
        rec = _valid_record()
        rec["_audit"]["AUTONOMY_LEVEL"]["_derivation_inputs"] = ["VISION_PURPOSE"]
        self._expect(rec, "DR-4")

    def test_dr5_synthesis_without_inputs(self):
        rec = _valid_record()
        del rec["_audit"]["APPROACH_SOLUTION_BRIEF"]["_derivation_inputs"]
        self._expect(rec, "DR-5")

    def test_dr6_classification_decision_field_false(self):
        rec = _valid_record()
        rec["_audit"]["SCALE_TIER"]["_decision_field"] = False
        self._expect(rec, "DR-6")

    def test_dr6_decision_field_true_but_kind_none(self):
        rec = _valid_record()
        rec["_audit"]["VISION_PURPOSE"]["_decision_field"] = True  # kind stays "none"
        self._expect(rec, "DR-6")

    def test_dr7_ambiguous_without_candidates(self):
        rec = _valid_record()
        del rec["_audit"]["AMBIG_FIELD"]["_source_candidates"]
        self._expect(rec, "DR-7")

    def test_dr8_derivation_input_unresolved(self):
        rec = _valid_record()
        rec["_audit"]["APPROACH_SOLUTION_BRIEF"]["_derivation_inputs"] = ["NONEXISTENT_FIELD"]
        self._expect(rec, "DR-8")

    def test_dr9_stub_content_projecting(self):
        rec = _valid_record()
        rec["VISION_PURPOSE"] = "   "
        self._expect(rec, "DR-9")

    def test_dr9_placeholder_without_label_map(self):
        rec = _valid_record()
        del rec["_audit"]["OPERATOR_EMAIL"]["_label_map_reference"]
        self._expect(rec, "DR-9")

    def test_dr9_tbd_without_revisit(self):
        rec = _valid_record()
        del rec["_audit"]["NTFY_TOPIC"]["_revisit_trigger"]
        self._expect(rec, "DR-9")

    def test_dr10_uncertain_without_revisit(self):
        rec = _valid_record()
        rec["_audit"]["SCALE_TIER"]["_confirmation_state"] = "accepted_uncertain_for_now"
        self._expect(rec, "DR-10")

    def test_dr10_unknown_envelope_key(self):
        rec = _valid_record()
        rec["_audit"]["VISION_PURPOSE"]["_bogus_structural_key"] = 1
        self._expect(rec, "DR-10")


if __name__ == "__main__":
    unittest.main()
