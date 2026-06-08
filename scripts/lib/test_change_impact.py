"""Unit tests for the change-propagation & consistency engine (change_impact.py).

NEUTRAL SYNTHETIC FIXTURES ONLY. The engine must be blind to any real scenario
(anti-overfit guarantee): "the mechanism detected the X->Y link" is true only because
the graph generically carried that edge, never because a test taught it.
No fixture here encodes the held-out cross-document scenario this engine is validated against.
"""

import copy
import unittest

from field_manifest import FieldManifest, FieldSpec
import change_impact as ci


def _spec(field, *, group_id="g", derivation_class="extraction", decision_field=False,
          decision_kind="none", value_shape="prose", source_question_ids=None,
          preview_doc="", source=None, constraints=None):
    """Construct a synthetic FieldSpec with sensible defaults."""
    return FieldSpec(
        field=field, group_id=group_id, derivation_class=derivation_class,
        decision_field=decision_field, decision_kind=decision_kind, value_shape=value_shape,
        source_question_ids=list(source_question_ids or []), preview_doc=preview_doc,
        constraints=constraints or {}, source=source,
    )


def _manifest(*specs):
    return FieldManifest(system_shape="test-shape", fields={s.field: s for s in specs})


class BuildGraphStaticSkeletonTest(unittest.TestCase):
    def test_answer_to_field_and_field_to_doc_edges(self):
        """The static skeleton carries answer->field (source_question_ids) and
        field->doc (preview_doc) edges, derived generically from the manifest."""
        manifest = _manifest(
            _spec("FPURPOSE", source_question_ids=["Q1", "Q2"], preview_doc="alpha.md"),
        )

        graph = ci.build_graph(manifest)

        field = ci.Node("field", "FPURPOSE")
        self.assertEqual(
            graph.successors(ci.Node("answer", "Q1")), {field},
        )
        self.assertEqual(
            graph.successors(ci.Node("answer", "Q2")), {field},
        )
        self.assertEqual(
            graph.successors(field), {ci.Node("doc", "alpha.md")},
        )

    def test_empty_preview_doc_produces_no_doc_edge(self):
        """A field with preview_doc == '' (not rendered into any doc) has no doc successor."""
        manifest = _manifest(
            _spec("FINTERNAL", source_question_ids=["Q1"], preview_doc=""),
        )

        graph = ci.build_graph(manifest)

        self.assertEqual(graph.successors(ci.Node("field", "FINTERNAL")), set())


class FieldToFieldOverlayTest(unittest.TestCase):
    def test_derivation_inputs_create_field_to_field_edges(self):
        """An `_audit` overlay adds field->field edges from `_derivation_inputs`:
        each input field FED the derived field, so the edge is input -> derived."""
        manifest = _manifest(
            _spec("FBASE", source_question_ids=["Q1"]),
            _spec("FDERIVED", derivation_class="synthesis", source_question_ids=["Q2"]),
        )
        audit = {
            "FBASE": {"_derivation_inputs": []},
            "FDERIVED": {"_derivation_inputs": ["FBASE"]},
        }

        graph = ci.build_graph(manifest, audit=audit)

        base = ci.Node("field", "FBASE")
        derived = ci.Node("field", "FDERIVED")
        self.assertIn(derived, graph.successors(base))
        self.assertIn(base, graph.predecessors(derived))

    def test_no_overlay_when_audit_absent(self):
        """Without an audit overlay there are NO field->field edges (skeleton only)."""
        manifest = _manifest(
            _spec("FBASE", source_question_ids=["Q1"]),
            _spec("FDERIVED", derivation_class="synthesis", source_question_ids=["Q2"]),
        )

        graph = ci.build_graph(manifest)

        self.assertEqual(graph.successors(ci.Node("field", "FBASE")), set())


class ClassifyTest(unittest.TestCase):
    def test_decision_field_envelope_is_rule_decision(self):
        """A field whose envelope marks it a decision classifies as rule-decision,
        read structurally from `_decision_field` (no prose reading)."""
        env = {"_decision_field": True, "_decision_kind": "closed_value"}
        self.assertEqual(ci.classify(env), ci.RULE_DECISION)

    def test_non_decision_envelope_is_content_only(self):
        """A non-decision field classifies as content-only."""
        env = {"_decision_field": False, "_decision_kind": "none"}
        self.assertEqual(ci.classify(env), ci.CONTENT_ONLY)

    def test_missing_decision_field_defaults_content_only(self):
        """An envelope without `_decision_field` classifies as content-only — consistent with
        the contract coupling (decision_field == (decision_kind != 'none')): absence means
        not-a-decision. A genuinely malformed envelope is caught upstream by the derived-record
        validator (DR-1/DR-2), not by classify."""
        self.assertEqual(ci.classify({}), ci.CONTENT_ONLY)


class DeterminismKindTest(unittest.TestCase):
    def test_auto_class_is_pure_code(self):
        """`auto` fields are computed by deterministic code -> pure_code (auto-halt eligible)."""
        self.assertEqual(ci.determinism_kind_for("auto"), ci.PURE_CODE)

    def test_model_classes_are_model_unstable(self):
        """Every model-derived class is model_unstable at v0: re-derivation of model
        output is non-idempotent, so its fingerprint is unreliable -> never auto-halts."""
        for dclass in ("extraction", "synthesis", "classification", "policy", "authoring"):
            with self.subTest(dclass=dclass):
                self.assertEqual(ci.determinism_kind_for(dclass), ci.MODEL_UNSTABLE)

    def test_only_pure_code_may_auto_halt(self):
        """auto-halt eligibility is exactly determinism_kind == pure_code."""
        self.assertTrue(ci.may_auto_halt(ci.PURE_CODE))
        self.assertFalse(ci.may_auto_halt(ci.MODEL_UNSTABLE))
        self.assertFalse(ci.may_auto_halt(ci.RECORDED_REPLAY_ONLY))


class NodeFingerprintTest(unittest.TestCase):
    def test_field_fingerprint_changes_on_value_change(self):
        env = {"_decision_field": False, "_decision_kind": "none", "_source": "operator-content"}
        a = ci.field_fingerprint("old text", env)
        b = ci.field_fingerprint("new text", env)
        self.assertNotEqual(a, b)

    def test_field_fingerprint_changes_on_metadata_change_with_identical_value(self):
        """Behavior can change through metadata while rendered text is identical.
        Same value, changed `_decision_kind` -> different fingerprint."""
        value = "twice-weekly"
        env_a = {"_decision_field": True, "_decision_kind": "schedule"}
        env_b = {"_decision_field": True, "_decision_kind": "closed_value"}
        self.assertNotEqual(ci.field_fingerprint(value, env_a),
                            ci.field_fingerprint(value, env_b))

    def test_field_fingerprint_stable_under_confirmed_at_change(self):
        """A no-op re-confirmation (only `_confirmed_at` changes) must NOT register as a
        change — `_confirmed_at` is bookkeeping, not behavior."""
        value = "the same prose"
        env_a = {"_decision_field": False, "_decision_kind": "none",
                 "_source": "operator-content", "_confirmed_at": "2026-01-01T00:00:00Z"}
        env_b = dict(env_a, _confirmed_at="2026-06-08T12:00:00Z")
        self.assertEqual(ci.field_fingerprint(value, env_a),
                         ci.field_fingerprint(value, env_b))

    def test_doc_fingerprint_changes_on_rendered_change(self):
        a = ci.doc_fingerprint("alpha.md", "rendered body v1")
        b = ci.doc_fingerprint("alpha.md", "rendered body v2")
        self.assertNotEqual(a, b)

    def test_doc_fingerprint_includes_doc_id(self):
        """Two docs with identical body but different ids have distinct fingerprints."""
        self.assertNotEqual(ci.doc_fingerprint("alpha.md", "body"),
                            ci.doc_fingerprint("beta.md", "body"))


class SourcesInvertedTraceTest(unittest.TestCase):
    def _chain_graph(self):
        # Q1 -> FBASE -> FDERIVED -> alpha.md  (a linear derivation chain)
        manifest = _manifest(
            _spec("FBASE", source_question_ids=["Q1"]),
            _spec("FDERIVED", derivation_class="synthesis", source_question_ids=["Q2"],
                  preview_doc="alpha.md"),
        )
        audit = {"FBASE": {"_derivation_inputs": []},
                 "FDERIVED": {"_derivation_inputs": ["FBASE"]}}
        return ci.build_graph(manifest, audit=audit)

    def test_returns_transitive_upstream_contributors(self):
        """From a point-of-notice, sources() enumerates every upstream contributor
        (intermediate fields AND the originating answers), excluding downstream docs."""
        graph = self._chain_graph()
        result = ci.sources(graph, ci.Node("field", "FDERIVED"))
        self.assertIn(ci.Node("field", "FBASE"), result)
        self.assertIn(ci.Node("answer", "Q1"), result)
        self.assertIn(ci.Node("answer", "Q2"), result)  # direct source of FDERIVED
        self.assertNotIn(ci.Node("doc", "alpha.md"), result)  # downstream, not a source

    def test_ranks_nearer_contributors_first(self):
        """Structural ranking primary signal = shortest path: a direct input ranks above
        a transitively-reached one."""
        graph = self._chain_graph()
        result = ci.sources(graph, ci.Node("field", "FDERIVED"))
        self.assertLess(result.index(ci.Node("field", "FBASE")),
                        result.index(ci.Node("answer", "Q1")))

    def test_no_upstream_returns_empty(self):
        graph = self._chain_graph()
        self.assertEqual(ci.sources(graph, ci.Node("answer", "Q1")), [])


class CascadeTest(unittest.TestCase):
    def test_immediate_model_unstable_dependent_requires_disposition(self):
        """A change to an answer surfaces its immediate model-derived dependent for operator
        disposition (model_unstable never auto-halts)."""
        manifest = _manifest(
            _spec("FDERIVED", derivation_class="synthesis", source_question_ids=["Q1"]),
        )
        record = {
            "FDERIVED": "some prose",
            "_audit": {
                "FDERIVED": {"_derivation_class": "synthesis", "_decision_field": False,
                             "_decision_kind": "none"},
            },
        }
        graph = ci.build_graph(manifest, audit=record["_audit"])

        result = ci.cascade(graph, ci.Node("answer", "Q1"), record)

        surfaced = {n.node: n for n in result.surfaced}
        fnode = ci.Node("field", "FDERIVED")
        self.assertIn(fnode, surfaced)
        self.assertEqual(surfaced[fnode].status, ci.REQUIRES_DISPOSITION)
        self.assertEqual(surfaced[fnode].determinism_kind, ci.MODEL_UNSTABLE)
        self.assertEqual(surfaced[fnode].impact_class, ci.CONTENT_ONLY)


    def test_pure_code_dependent_unchanged_fingerprint_auto_halts(self):
        """A pure_code dependent whose inputs are all known and whose re-derived fingerprint
        is unchanged is AUTO_HALTED (pruned from the operator surface)."""
        manifest = _manifest(
            _spec("FBASE", source_question_ids=["Q1"]),
            _spec("FCALC", derivation_class="auto", source_question_ids=[]),
        )
        audit = {
            "FBASE": {"_derivation_class": "extraction", "_decision_field": False,
                      "_decision_kind": "none", "_derivation_inputs": []},
            "FCALC": {"_derivation_class": "auto", "_decision_field": False,
                      "_decision_kind": "none", "_derivation_inputs": ["FBASE"]},
        }
        record = {"FBASE": "old", "FCALC": "computed-old", "_audit": audit}
        graph = ci.build_graph(manifest, audit=audit)

        # FCALC re-derives to the SAME value+envelope -> unchanged fingerprint.
        def rederive(field, known_values):
            return ("computed-old", audit["FCALC"])

        result = ci.cascade(graph, ci.Node("field", "FBASE"), record,
                            rederive=rederive, candidate_values={"FBASE": "new"})

        fcalc = ci.Node("field", "FCALC")
        self.assertIn(fcalc, result.auto_halted)
        self.assertNotIn(fcalc, {n.node for n in result.surfaced})


    def test_changed_pure_code_propagates_new_value_to_downstream(self):
        """A CHANGED pure_code node propagates its new value into candidate space, so a
        downstream pure_code node can be re-derived (and here auto-halted). This discriminates
        the CHANGED branch: without the known-value propagation, FCALC2's inputs would be
        unknown and it would wrongly surface instead of auto-halting."""
        manifest = _manifest(
            _spec("FBASE", source_question_ids=["Q1"]),
            _spec("FCALC", derivation_class="auto", source_question_ids=[]),
            _spec("FCALC2", derivation_class="auto", source_question_ids=[]),
        )
        audit = {
            "FBASE": {"_derivation_class": "extraction", "_decision_field": False,
                      "_decision_kind": "none", "_derivation_inputs": []},
            "FCALC": {"_derivation_class": "auto", "_decision_field": False,
                      "_decision_kind": "none", "_derivation_inputs": ["FBASE"]},
            "FCALC2": {"_derivation_class": "auto", "_decision_field": False,
                       "_decision_kind": "none", "_derivation_inputs": ["FCALC"]},
        }
        record = {"FBASE": "old", "FCALC": "calc-old", "FCALC2": "calc2-old", "_audit": audit}
        graph = ci.build_graph(manifest, audit=audit)

        def rederive(field, known_values):
            if field == "FCALC":
                return ("calc-NEW", audit["FCALC"])        # changed
            if field == "FCALC2":
                assert "FCALC" in known_values, "downstream re-derive needs propagated value"
                return ("calc2-old", audit["FCALC2"])      # unchanged -> should auto-halt
            raise AssertionError(field)

        result = ci.cascade(graph, ci.Node("field", "FBASE"), record,
                            rederive=rederive, candidate_values={"FBASE": "new"})

        surfaced = {n.node: n for n in result.surfaced}
        self.assertEqual(surfaced[ci.Node("field", "FCALC")].status, ci.CHANGED)
        self.assertIn(ci.Node("field", "FCALC2"), result.auto_halted)

    def test_cascade_does_not_mutate_record(self):
        """The cascade is computed in side-effect-free candidate space — the baseline
        record is never mutated."""
        manifest = _manifest(
            _spec("FDERIVED", derivation_class="synthesis", source_question_ids=["Q1"]),
        )
        audit = {"FDERIVED": {"_derivation_class": "synthesis", "_decision_field": False,
                              "_decision_kind": "none"}}
        record = {"FDERIVED": "some prose", "_audit": audit}
        before = copy.deepcopy(record)

        ci.cascade(graph=ci.build_graph(manifest, audit=audit),
                   changed_node=ci.Node("answer", "Q1"), record=record)

        self.assertEqual(record, before)


if __name__ == "__main__":
    unittest.main()
