"""Integration tests for the canonical external-dependency record unification.

Covers the locked-design properties that span modules (the per-surface filter/reshape unit is in
test_dependency_projection): the identity/annotation decision-class split, the cross-group
freshness fix (a later edit to the canonical record re-flags the consuming groups), the
change-propagation cascade + bidirectional trace through the engine, and the end-to-end emission
of each projection into its OWN distinct file.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import change_impact as ci  # type: ignore  # noqa: E402
import dependency_projection as dp  # type: ignore  # noqa: E402
from field_manifest import load_field_manifest  # type: ignore  # noqa: E402
from derivation_groups import (  # type: ignore  # noqa: E402
    load_derivation_groups, group_confirmation_is_stale,
)
from transcript_recorder import TranscriptRecorder, group_source_hash  # type: ignore  # noqa: E402

SHAPE = "markdown-CC"
REPO_ROOT = Path(__file__).resolve().parents[3]

_IDENTITY = json.dumps([
    {"id": "google_sheet", "name": "Google Sheet task tracker", "type": "Spreadsheet",
     "roles": ["boundary_input", "health_monitored", "needs_credential"],
     "credential_facet": {"env_var": "GOOGLE_SHEETS_API_KEY", "cred_type": "API key",
                          "provider": "Google", "provisional_expiry": "Unknown"}},
])
_ANNOTATION = json.dumps([
    {"id": "google_sheet", "purpose": "the master task list", "what_stops": "tracking stops",
     "boundary_input_facet": {"input_risk": "malformed rows mis-route work"}, "health_facet": {}},
])


class DecisionClassingTest(unittest.TestCase):
    """The integration-boundary decision lives on the IDENTITY record; the annotation and the three
    projection caches are content-only (so a narrative edit / a re-rendered cache is not a blind-
    apply rule-decision — the cross-vendor decision to split identity from annotation)."""

    def setUp(self):
        self.m = load_field_manifest(SHAPE)

    def test_identity_is_the_integration_boundary_decision(self):
        s = self.m.spec_for("EXTERNAL_DEPENDENCY_IDENTITY")
        self.assertTrue(s.decision_field)
        self.assertEqual(s.decision_kind, "integration_boundary")
        self.assertEqual(s.derivation_class, "extraction")
        self.assertEqual(ci.classify({"_decision_field": True}), ci.RULE_DECISION)

    def test_annotation_is_content_only(self):
        s = self.m.spec_for("EXTERNAL_DEPENDENCY_ANNOTATION")
        self.assertFalse(s.decision_field)
        self.assertEqual(s.decision_kind, "none")
        self.assertEqual(ci.classify({"_decision_field": False}), ci.CONTENT_ONLY)

    def test_projections_are_content_only_caches(self):
        for f in ("INPUT_TYPE_INVENTORY", "SOURCE_REGISTRY_ROWS", "CREDENTIAL_REGISTRY_ROWS"):
            s = self.m.spec_for(f)
            self.assertEqual(s.derivation_class, "projection", f)
            self.assertFalse(s.decision_field, f"{f} must be content-only (the decision is on IDENTITY)")
            self.assertEqual(s.source_question_ids, [], f)


class CrossGroupFreshnessTest(unittest.TestCase):
    """Cross-group freshness (verified gap): group_source_hash keys only on a group's OWN input_question_ids, so a
    consuming group would stay falsely fresh on a later canonical-record edit. The fix puts DEP-1 in
    the consuming groups' input_question_ids, so editing DEP-1 changes their source hash -> stale."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tpath = str(Path(self._tmp.name) / "transcript.jsonl")
        self.dg = load_derivation_groups(SHAPE)

    def tearDown(self):
        self._tmp.cleanup()

    def _hash(self, group_id, events):
        return group_source_hash(events, self.dg.group_by_id(group_id).input_question_ids)

    def test_dep1_edit_reflags_both_consuming_groups_not_unrelated_ones(self):
        rec = TranscriptRecorder(Path(self.tpath))
        # answer enough that the three groups have a non-trivial hash, incl. DEP-1.
        for q in ("DEP-1", "GATE-1", "QA-3", "CRED-3", "P1-1"):
            rec.record_source_answer(q, "g", f"value-1 for {q}")
        before = {g: self._hash(g, rec.events()) for g in ("tests_audit", "orchestration_build", "vision")}

        # The operator later edits the dependency answer (DEP-1).
        rec.record_source_answer("DEP-1", "dependency_inventory", "value-2 for DEP-1 (edited)")
        after = {g: self._hash(g, rec.events()) for g in ("tests_audit", "orchestration_build", "vision")}

        # Both consuming groups re-flag; vision (no DEP-1 input) is untouched.
        self.assertNotEqual(before["tests_audit"], after["tests_audit"])
        self.assertNotEqual(before["orchestration_build"], after["orchestration_build"])
        self.assertEqual(before["vision"], after["vision"])

        # And a confirmation recorded under the OLD hash is now detected as stale (emit fail-closed).
        old_marker = {"source_hash": before["tests_audit"]}
        self.assertTrue(group_confirmation_is_stale(old_marker, after["tests_audit"]))


class CascadeTraceTest(unittest.TestCase):
    """The change-propagation engine cascades a canonical-record change into the projections and traces a
    projection back to the originating answer — with NO engine change (field->field edges come from
    _derivation_inputs generically)."""

    def setUp(self):
        self.m = load_field_manifest(SHAPE)
        self._audit = {
            "EXTERNAL_DEPENDENCY_IDENTITY": {"_derivation_class": "extraction", "_decision_field": True},
            "EXTERNAL_DEPENDENCY_ANNOTATION": {"_derivation_class": "extraction", "_decision_field": False},
        }
        for f in ("INPUT_TYPE_INVENTORY", "SOURCE_REGISTRY_ROWS", "CREDENTIAL_REGISTRY_ROWS"):
            self._audit[f] = {"_derivation_class": "projection", "_decision_field": False,
                              "_derivation_inputs": dp.derivation_inputs_for(f)}
        self.graph = ci.build_graph(self.m, self._audit)

    def test_identity_edge_reaches_every_projection(self):
        succ = self.graph.successors(ci.Node("field", "EXTERNAL_DEPENDENCY_IDENTITY"))
        for f in ("INPUT_TYPE_INVENTORY", "SOURCE_REGISTRY_ROWS", "CREDENTIAL_REGISTRY_ROWS"):
            self.assertIn(ci.Node("field", f), succ, f)

    def test_projection_traces_back_to_dep1(self):
        for f in ("INPUT_TYPE_INVENTORY", "SOURCE_REGISTRY_ROWS", "CREDENTIAL_REGISTRY_ROWS"):
            src = ci.sources(self.graph, ci.Node("field", f))
            self.assertIn(ci.Node("answer", "DEP-1"), src,
                          f"{f} must trace back to its originating answer DEP-1")

    def test_cascade_surfaces_changed_projection_and_auto_halts_unaffected(self):
        # Drop the boundary_input role: only INPUT_TYPE_INVENTORY's subset changes; the
        # health/credential projections are byte-identical and must auto-halt (no alert fatigue).
        changed = json.loads(_IDENTITY)
        changed[0]["roles"] = ["health_monitored", "needs_credential"]
        changed_identity = json.dumps(changed)

        record = {"EXTERNAL_DEPENDENCY_IDENTITY": _IDENTITY, "EXTERNAL_DEPENDENCY_ANNOTATION": _ANNOTATION}
        for f in ("INPUT_TYPE_INVENTORY", "SOURCE_REGISTRY_ROWS", "CREDENTIAL_REGISTRY_ROWS"):
            record[f] = dp.project(f, _IDENTITY, _ANNOTATION)
        record["_audit"] = self._audit

        def rederive(field, known):
            value = dp.project(field, known["EXTERNAL_DEPENDENCY_IDENTITY"],
                               known.get("EXTERNAL_DEPENDENCY_ANNOTATION", "[]"))
            return value, self._audit[field]

        result = ci.cascade(
            self.graph, ci.Node("field", "EXTERNAL_DEPENDENCY_IDENTITY"), record, rederive=rederive,
            candidate_values={"EXTERNAL_DEPENDENCY_IDENTITY": changed_identity,
                              "EXTERNAL_DEPENDENCY_ANNOTATION": _ANNOTATION})
        surfaced_ids = {n.node.id for n in result.surfaced if n.node.kind == "field"}
        halted_ids = {n.id for n in result.auto_halted}
        self.assertIn("INPUT_TYPE_INVENTORY", surfaced_ids)      # boundary_input subset changed
        self.assertIn("SOURCE_REGISTRY_ROWS", halted_ids)        # health subset unchanged -> pruned
        self.assertIn("CREDENTIAL_REGISTRY_ROWS", halted_ids)    # credential subset unchanged -> pruned


class EmissionContentTest(unittest.TestCase):
    """Each projection lands in its OWN distinct emitted file (the emitted files stay separate even
    though the internal record is unified)."""

    def setUp(self):
        from emission_plan import validate_emission_plan, load_contract, default_contract_path  # type: ignore
        from test_emission_plan import _valid_plan  # type: ignore
        from scaffold_emitter import emit_scaffold  # type: ignore
        contract = load_contract(default_contract_path())
        plan_dict = _valid_plan()
        plan_dict["foundation_doc_inputs"] = {
            **plan_dict.get("foundation_doc_inputs", {}),
            "INPUT_TYPE_INVENTORY": dp.project("INPUT_TYPE_INVENTORY", _IDENTITY, _ANNOTATION),
            "SOURCE_REGISTRY_ROWS": dp.project("SOURCE_REGISTRY_ROWS", _IDENTITY, _ANNOTATION),
            "CREDENTIAL_REGISTRY_ROWS": dp.project("CREDENTIAL_REGISTRY_ROWS", _IDENTITY, _ANNOTATION),
        }
        plan = validate_emission_plan(plan_dict, contract)
        self._tmp = tempfile.TemporaryDirectory()
        self.staging = Path(self._tmp.name)
        emit_scaffold(plan, self.staging, REPO_ROOT)

    def tearDown(self):
        self._tmp.cleanup()

    def _read(self, rel):
        return (self.staging / rel).read_text(encoding="utf-8")

    def test_validation_gate_has_the_boundary_input_row(self):
        gate = self._read("quality/validation_gate_config.md")
        self.assertIn("Google Sheet task tracker", gate)
        self.assertIn("malformed rows mis-route work", gate)   # the boundary_input facet

    def test_source_registry_has_the_health_row_with_pending(self):
        reg = self._read("quality/source_registry.md")
        self.assertIn("Google Sheet task tracker", reg)
        self.assertIn("Pending", reg)
        self.assertIn(dp.RUNTIME_PLACEHOLDER, reg)

    def test_credentials_registry_has_the_credential_row(self):
        creds = self._read("security/credentials_registry.md")
        self.assertIn("GOOGLE_SHEETS_API_KEY", creds)
        self.assertIn("Pending", creds)

    def test_files_stay_distinct(self):
        # the credential env var belongs ONLY in the credentials registry, not the others.
        self.assertNotIn("GOOGLE_SHEETS_API_KEY", self._read("quality/validation_gate_config.md"))
        self.assertNotIn("GOOGLE_SHEETS_API_KEY", self._read("quality/source_registry.md"))


if __name__ == "__main__":
    unittest.main()
