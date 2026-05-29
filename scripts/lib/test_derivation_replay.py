"""Tests for derivation_replay.py — event-sourced compile, byte-identity, drift split.

Neutral synthetic transcript (real field names, all derivation classes, an edit, a
deferred field, an auto field). No operator content.
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import derivation_replay as rp
import derived_record as dr


def _transcript():
    return [
        {"event_seq": 1, "event_type": "derivation", "field": "VISION_PURPOSE",
         "value": "A system to track customer follow-ups.",
         "envelope": {"_source": "operator-content", "_derivation_class": "extraction",
                      "_decision_field": False, "_decision_kind": "none"}},
        {"event_seq": 2, "event_type": "confirmation", "field": "VISION_PURPOSE",
         "confirmation_state": "accepted", "confirmed_at": "2026-01-01"},
        {"event_seq": 3, "event_type": "derivation", "field": "AUTONOMY_LEVEL",
         "value": "2",
         "envelope": {"_source": "operator-preference", "_derivation_class": "classification",
                      "_decision_field": True, "_decision_kind": "closed_value",
                      "_source_question_ids": ["UP-AUTONOMY"]}},
        {"event_seq": 4, "event_type": "confirmation", "field": "AUTONOMY_LEVEL",
         "confirmation_state": "accepted", "confirmed_at": "2026-01-01"},
        {"event_seq": 5, "event_type": "derivation", "field": "AUTONOMOUS_ACTIONS",
         "value": "The system drafts updates for review (illustrative).",
         "envelope": {"_source": "claude-derived-operator-confirmed", "_derivation_class": "policy",
                      "_decision_field": True, "_decision_kind": "policy_rule",
                      "_derivation_inputs": ["AUTONOMY_LEVEL"]}},
        {"event_seq": 6, "event_type": "confirmation", "field": "AUTONOMOUS_ACTIONS",
         "confirmation_state": "accepted_with_adjustments", "confirmed_at": "2026-01-01",
         "value": "The system drafts updates and reads provided files for review (illustrative)."},
        {"event_seq": 7, "event_type": "derivation", "field": "NTFY_TOPIC",
         "value": "TBD; provided later.",
         "envelope": {"_source": "operator-preference", "_derivation_class": "extraction",
                      "_decision_field": False, "_decision_kind": "none",
                      "_revisit_trigger": "when the operator sets it up"}},
        {"event_seq": 8, "event_type": "confirmation", "field": "NTFY_TOPIC",
         "confirmation_state": "deferred_not_emittable"},
        {"event_seq": 9, "event_type": "derivation", "field": "WIZARD_VERSION",
         "value": "v0.3.0",
         "envelope": {"_source": "auto", "_derivation_class": "auto",
                      "_decision_field": False, "_decision_kind": "none"}},
    ]


class TestCompileAndReplay(unittest.TestCase):
    def test_compile_is_byte_identical(self):
        self.assertTrue(rp.replay_is_byte_identical(_transcript()))

    def test_snapshot_hash_stable(self):
        a = rp.snapshot_hash(rp.compile_transcript(_transcript()))
        b = rp.snapshot_hash(rp.compile_transcript(_transcript()))
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("sha256:"))

    def test_edit_confirmation_updates_value(self):
        rec = rp.compile_transcript(_transcript())
        self.assertIn("reads provided files", rec["AUTONOMOUS_ACTIONS"])
        self.assertTrue(rec["_audit"]["AUTONOMOUS_ACTIONS"]["_confirmed_with_adjustments"])

    def test_compiled_record_validates(self):
        rec = rp.compile_transcript(_transcript())
        contract = dr.load_contract(dr.default_contract_path())
        dr.validate_derived_record(rec, contract)  # no raise

    def test_project_excludes_deferred(self):
        rec = rp.compile_transcript(_transcript())
        proj = rp.project(rec)
        self.assertNotIn("NTFY_TOPIC", proj)          # deferred_not_emittable
        self.assertIn("VISION_PURPOSE", proj)
        self.assertIn("WIZARD_VERSION", proj)          # auto field projects
        self.assertEqual(proj["AUTONOMY_LEVEL"], "2")


class TestDriftSplit(unittest.TestCase):
    def setUp(self):
        self.prev = rp.compile_transcript(_transcript())

    def test_decision_flip_is_alarming(self):
        new = copy.deepcopy(self.prev)
        new["AUTONOMOUS_ACTIONS"] = "The system sends updates automatically without review."
        d = rp.compute_drift(self.prev, new)
        self.assertIn("AUTONOMOUS_ACTIONS", d["content"]["decision"])
        self.assertNotIn("AUTONOMOUS_ACTIONS", d["content"]["narrative"])

    def test_narrative_reword_is_informational(self):
        new = copy.deepcopy(self.prev)
        new["VISION_PURPOSE"] = "A system to keep customer follow-ups on track."
        d = rp.compute_drift(self.prev, new)
        self.assertIn("VISION_PURPOSE", d["content"]["narrative"])
        self.assertNotIn("VISION_PURPOSE", d["content"]["decision"])

    def test_envelope_change_detected(self):
        new = copy.deepcopy(self.prev)
        new["_audit"]["AUTONOMY_LEVEL"]["_confirmation_state"] = "accepted_with_adjustments"
        d = rp.compute_drift(self.prev, new)
        self.assertIn("AUTONOMY_LEVEL", d["envelope"])

    def test_no_drift_when_identical(self):
        d = rp.compute_drift(self.prev, copy.deepcopy(self.prev))
        self.assertEqual(d["protocol"], [])
        self.assertEqual(d["envelope"], [])
        self.assertEqual(d["content"]["decision"], [])
        self.assertEqual(d["content"]["narrative"], [])


if __name__ == "__main__":
    unittest.main()
