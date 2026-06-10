"""Tests for the field-manifest loader + validator (T3).

The manifest is the per-field derivation contract. The validator enforces the decision-field
coupling rule from the derived-record contract: a classification/policy field is always a
decision (decision_field true), and decision_field is true exactly when decision_kind != 'none'.
Also verified: cross-artifact consistency with the derivation-groups registry (every registry
target field has a manifest entry). RED->GREEN.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from field_manifest import (  # noqa: E402
    load_field_manifest, FieldManifest, FieldSpec, FieldManifestError,
    DERIVATION_CLASSES, DECISION_KINDS,
)
from derivation_groups import load_derivation_groups  # noqa: E402

SHAPE = "markdown-CC"


class LoaderTests(unittest.TestCase):
    def test_loads_and_specs(self):
        m = load_field_manifest(SHAPE)
        self.assertIsInstance(m, FieldManifest)
        self.assertEqual(m.system_shape, SHAPE)
        self.assertGreaterEqual(len(m.fields), 26)
        self.assertIsInstance(m.spec_for("SCALE_TIER"), FieldSpec)

    def test_unknown_field_fails_closed(self):
        m = load_field_manifest(SHAPE)
        with self.assertRaises(FieldManifestError):
            m.spec_for("NOT_A_FIELD")

    def test_unknown_shape_fails_closed(self):
        with self.assertRaises(FieldManifestError):
            load_field_manifest("no-such-shape")

    def test_dr6_coupling_holds_for_every_field(self):
        m = load_field_manifest(SHAPE)
        for name, spec in m.fields.items():
            # classification/policy => decision
            if spec.derivation_class in ("classification", "policy"):
                self.assertTrue(spec.decision_field, f"{name} is {spec.derivation_class} but not a decision")
            # decision_field iff decision_kind != none
            self.assertEqual(spec.decision_field, spec.decision_kind != "none", name)
            self.assertIn(spec.derivation_class, DERIVATION_CLASSES, name)
            self.assertIn(spec.decision_kind, DECISION_KINDS, name)

    def test_known_decision_fields(self):
        m = load_field_manifest(SHAPE)
        for f in ("SCALE_TIER", "AUTONOMY_LEVEL", "HITL_MAP_ROWS", "DRIFT_ANALYSIS_CADENCE"):
            self.assertTrue(m.spec_for(f).decision_field, f)

    def test_closed_value_has_enum_domain(self):
        m = load_field_manifest(SHAPE)
        st = m.spec_for("SCALE_TIER")
        self.assertEqual(st.decision_kind, "closed_value")
        self.assertTrue(st.constraints.get("enum_domain"))

    def test_policy_field_requires_negative_permissions(self):
        m = load_field_manifest(SHAPE)
        self.assertTrue(m.spec_for("HITL_MAP_ROWS").constraints.get("requires_explicit_negative_permissions"))

    def test_auto_and_projection_have_no_source_questions_others_do(self):
        m = load_field_manifest(SHAPE)
        for name, spec in m.fields.items():
            # auto fields are code-computed globals; projection fields derive from PRIOR PAYLOAD
            # FIELDS (via _derivation_inputs at derive time), never raw answers — both carry no
            # source_question_ids. Every other class cites at least one source question.
            if spec.derivation_class in ("auto", "projection"):
                self.assertEqual(spec.source_question_ids, [], f"{name} ({spec.derivation_class})")
            else:
                self.assertTrue(spec.source_question_ids, f"{name} ({spec.derivation_class}) has no source questions")

    def test_source_override_loaded(self):
        m = load_field_manifest(SHAPE)
        # AUTOMATION_CREDIT_POOL is extraction-class but its value is a plan-lookup, so it declares
        # an explicit provenance override (claude-derived), NOT the extraction default operator-content.
        self.assertEqual(m.spec_for("AUTOMATION_CREDIT_POOL").source, "claude-derived-operator-confirmed")
        # a field with no declared override carries source None (the envelope assembler uses the class default)
        self.assertIsNone(m.spec_for("VISION_PURPOSE").source)


class CrossArtifactConsistencyTests(unittest.TestCase):
    def test_manifest_covers_every_registry_target_field(self):
        m = load_field_manifest(SHAPE)
        dg = load_derivation_groups(SHAPE)
        for g in dg.groups:
            for tf in g.target_fields:
                self.assertIn(tf, m.fields, f"registry group {g.group_id} target field {tf} has no manifest entry")

    def test_every_manifest_group_id_is_real_or_auto(self):
        m = load_field_manifest(SHAPE)
        dg = load_derivation_groups(SHAPE)
        valid = {g.group_id for g in dg.groups} | {"auto"}
        for name, spec in m.fields.items():
            self.assertIn(spec.group_id, valid, f"{name} group_id {spec.group_id}")


class FailClosedTests(unittest.TestCase):
    def _write(self, td, fields):
        p = Path(td) / f"{SHAPE}.json"
        p.write_text(json.dumps({
            "contract_id": "field-manifest", "contract_version": "field-manifest-v1",
            "system_shape": SHAPE, "fields": fields,
        }), encoding="utf-8")
        return Path(td)

    def test_contract_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / f"{SHAPE}.json"
            p.write_text(json.dumps({"contract_id": "wrong", "system_shape": SHAPE, "fields": []}), encoding="utf-8")
            with self.assertRaises(FieldManifestError):
                load_field_manifest(SHAPE, manifests_dir=Path(td))

    def test_dr6_violation_classification_not_decision_fails(self):
        with tempfile.TemporaryDirectory() as td:
            d = self._write(td, [{
                "field": "BAD", "group_id": "vision", "derivation_class": "classification",
                "decision_field": False, "decision_kind": "none", "value_shape": "enum",
                "source_question_ids": ["V-1"], "preview_doc": ""}])
            with self.assertRaises(FieldManifestError):
                load_field_manifest(SHAPE, manifests_dir=d)

    def test_bad_source_override_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            d = self._write(td, [{
                "field": "BAD", "group_id": "vision", "derivation_class": "extraction",
                "source": "made-up-source", "decision_field": False, "decision_kind": "none",
                "value_shape": "prose", "source_question_ids": ["V-1"], "preview_doc": ""}])
            with self.assertRaises(FieldManifestError):
                load_field_manifest(SHAPE, manifests_dir=d)

    def test_dr6_violation_decision_field_kind_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            d = self._write(td, [{
                "field": "BAD", "group_id": "vision", "derivation_class": "extraction",
                "decision_field": True, "decision_kind": "none", "value_shape": "prose",
                "source_question_ids": ["V-1"], "preview_doc": ""}])
            with self.assertRaises(FieldManifestError):
                load_field_manifest(SHAPE, manifests_dir=d)

    def test_unknown_class_fails(self):
        with tempfile.TemporaryDirectory() as td:
            d = self._write(td, [{
                "field": "BAD", "group_id": "vision", "derivation_class": "telepathy",
                "decision_field": False, "decision_kind": "none", "value_shape": "prose",
                "source_question_ids": ["V-1"], "preview_doc": ""}])
            with self.assertRaises(FieldManifestError):
                load_field_manifest(SHAPE, manifests_dir=d)


if __name__ == "__main__":
    unittest.main()
