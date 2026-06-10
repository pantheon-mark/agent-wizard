"""Unit tests for the change-propagation & consistency engine (change_impact.py).

NEUTRAL SYNTHETIC FIXTURES ONLY. The engine must be blind to any real scenario
(anti-overfit guarantee): "the mechanism detected the X->Y link" is true only because
the graph generically carried that edge, never because a test taught it.
No fixture here encodes the held-out cross-document scenario this engine is validated against.
"""

import copy
import unittest

from field_manifest import FieldManifest, FieldSpec
from derivation_groups import parse_progress_markers, group_confirmation_is_stale
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

    def test_projection_class_is_pure_code(self):
        """`projection` fields are a deterministic role-filter/reshape of prior fields ->
        pure_code, so an unchanged projected role-subset auto-halts instead of re-surfacing."""
        self.assertEqual(ci.determinism_kind_for("projection"), ci.PURE_CODE)

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


class ReceiptTest(unittest.TestCase):
    def _impacts(self):
        return [
            ci.ImpactNode(ci.Node("field", "FB"), ci.RULE_DECISION, ci.MODEL_UNSTABLE,
                          ci.REQUIRES_DISPOSITION),
            ci.ImpactNode(ci.Node("field", "FA"), ci.CONTENT_ONLY, ci.MODEL_UNSTABLE,
                          ci.REQUIRES_DISPOSITION),
        ]

    def test_impact_set_hash_is_order_independent(self):
        """The impact-set hash is a stable function of the SET of surfaced impacts, not
        their order."""
        a = ci.impact_set_hash(self._impacts())
        b = ci.impact_set_hash(list(reversed(self._impacts())))
        self.assertEqual(a, b)

    def test_impact_set_hash_changes_with_membership(self):
        impacts = self._impacts()
        fewer = impacts[:1]
        self.assertNotEqual(ci.impact_set_hash(impacts), ci.impact_set_hash(fewer))

    def test_make_receipt_carries_four_part_fingerprint(self):
        """The receipt is fingerprinted by graph_version + source_hash + engine_version +
        impact_set_hash, so a stale approval cannot unblock emit after any of them changes."""
        receipt = ci.make_receipt(
            change_detected_on=ci.Node("answer", "Q1"),
            graph_version="gv-1", source_hash="sha256:src",
            impacts=self._impacts(),
            dispositions={ci.Node("field", "FB"): ci.APPLY},
            recorded_at="2026-01-01T00:00:00Z",
        )
        fp = receipt["fingerprint"]
        self.assertEqual(fp["graph_version"], "gv-1")
        self.assertEqual(fp["source_hash"], "sha256:src")
        self.assertEqual(fp["engine_version"], ci.ENGINE_VERSION)
        self.assertEqual(fp["impact_set_hash"], ci.impact_set_hash(self._impacts()))

    def test_make_receipt_records_implicated_classes_and_dispositions(self):
        receipt = ci.make_receipt(
            change_detected_on=ci.Node("answer", "Q1"),
            graph_version="gv-1", source_hash="sha256:src",
            impacts=self._impacts(),
            dispositions={ci.Node("field", "FB"): ci.APPLY},
            recorded_at="2026-01-01T00:00:00Z",
        )
        self.assertEqual(receipt["implicated"]["field:FB"], ci.RULE_DECISION)
        self.assertEqual(receipt["implicated"]["field:FA"], ci.CONTENT_ONLY)
        self.assertEqual(receipt["dispositions"]["field:FB"], ci.APPLY)


class PendingDispositionsGateTest(unittest.TestCase):
    def _impact(self, fid, klass):
        return ci.ImpactNode(ci.Node("field", fid), klass, ci.MODEL_UNSTABLE,
                             ci.REQUIRES_DISPOSITION)

    def test_undispositioned_rule_decision_is_pending(self):
        impacts = [self._impact("FB", ci.RULE_DECISION)]
        pending = ci.pending_dispositions(impacts, dispositions={})
        self.assertEqual([p.node for p in pending], [ci.Node("field", "FB")])

    def test_applied_rule_decision_is_not_pending(self):
        impacts = [self._impact("FB", ci.RULE_DECISION)]
        pending = ci.pending_dispositions(impacts, {ci.Node("field", "FB"): ci.APPLY})
        self.assertEqual(pending, [])

    def test_deferred_rule_decision_stays_pending(self):
        """`defer` does NOT resolve a rule/decision implication — emit stays blocked."""
        impacts = [self._impact("FB", ci.RULE_DECISION)]
        pending = ci.pending_dispositions(impacts, {ci.Node("field", "FB"): ci.DEFER})
        self.assertEqual([p.node for p in pending], [ci.Node("field", "FB")])

    def test_content_only_never_blocks(self):
        """An un-dispositioned content-only impact is guided, not blocking — never pending."""
        impacts = [self._impact("FA", ci.CONTENT_ONLY)]
        self.assertEqual(ci.pending_dispositions(impacts, {}), [])

    def test_intentional_divergence_resolves(self):
        impacts = [self._impact("FB", ci.RULE_DECISION)]
        pending = ci.pending_dispositions(
            impacts, {ci.Node("field", "FB"): ci.INTENTIONAL_DIVERGENCE})
        self.assertEqual(pending, [])

    def test_emit_blocked_predicate(self):
        self.assertTrue(ci.emit_blocked_by_pending([self._impact("FB", ci.RULE_DECISION)]))
        self.assertFalse(ci.emit_blocked_by_pending([]))


class FreshnessTest(unittest.TestCase):
    def test_node_with_pending_implication_is_not_fresh(self):
        """Freshness is a validation input at EVERY boundary: a node with a pending blocking
        implication is not fresh, so it cannot be used as a derivation input / rendered /
        closed / emitted until dispositioned."""
        pending = [ci.ImpactNode(ci.Node("field", "FB"), ci.RULE_DECISION,
                                 ci.MODEL_UNSTABLE, ci.REQUIRES_DISPOSITION)]
        self.assertFalse(ci.is_fresh(ci.Node("field", "FB"), pending))
        self.assertTrue(ci.is_fresh(ci.Node("field", "FOTHER"), pending))


class TombstoneTest(unittest.TestCase):
    def test_tombstoned_marker_triggers_existing_stale_gate(self):
        """A tombstoned confirmation marker drops its source_hash, so the substrate's
        group_confirmation_is_stale fires automatically (no change to that ratified module)."""
        line = ci.tombstone_marker_line("group_vision_confirmed",
                                        reason="upstream change applied",
                                        recorded_at="2026-06-08T00:00:00Z")
        parsed = parse_progress_markers(line)
        marker = parsed["group_vision_confirmed"]
        self.assertEqual(marker["status"], "tombstoned")
        # Any current hash -> stale, because the tombstone removed the stored source_hash.
        self.assertTrue(group_confirmation_is_stale(marker, "sha256:whatever-current"))


class PendingFromEventsTest(unittest.TestCase):
    def _change_event(self, change_id, impacts):
        return {"event_type": "impact_change", "change_id": change_id,
                "impacts": impacts, "detected_at": "2026-06-08T00:00:00Z"}

    def _disp_event(self, change_id, fid, disposition):
        return {"event_type": "impact_disposition", "change_id": change_id,
                "node_kind": "field", "node_id": fid, "disposition": disposition,
                "recorded_at": "2026-06-08T00:00:01Z"}

    def test_undispositioned_rule_decision_change_is_pending(self):
        events = [self._change_event("c1", [
            {"node_kind": "field", "node_id": "FB", "impact_class": ci.RULE_DECISION},
        ])]
        pending = ci.pending_from_events(events)
        self.assertEqual([p.node for p in pending], [ci.Node("field", "FB")])

    def test_disposition_for_matching_change_id_resolves(self):
        events = [
            self._change_event("c1", [{"node_kind": "field", "node_id": "FB",
                                       "impact_class": ci.RULE_DECISION}]),
            self._disp_event("c1", "FB", ci.APPLY),
        ]
        self.assertEqual(ci.pending_from_events(events), [])

    def test_disposition_for_different_change_id_does_not_resolve(self):
        """A new upstream change yields a new change_id; an old change's disposition does not
        unblock it (this is how 'a stale approval cannot unblock emit' falls out)."""
        events = [
            self._change_event("c2", [{"node_kind": "field", "node_id": "FB",
                                       "impact_class": ci.RULE_DECISION}]),
            self._disp_event("c1", "FB", ci.APPLY),  # disposition for the OLD change
        ]
        self.assertEqual([p.node for p in ci.pending_from_events(events)],
                         [ci.Node("field", "FB")])


class ImpactTransactionTest(unittest.TestCase):
    def _surfaced(self):
        return [
            ci.ImpactNode(ci.Node("field", "VISION_PURPOSE"), ci.CONTENT_ONLY,
                          ci.MODEL_UNSTABLE, ci.REQUIRES_DISPOSITION),
            ci.ImpactNode(ci.Node("field", "AUTONOMY_LEVEL"), ci.RULE_DECISION,
                          ci.MODEL_UNSTABLE, ci.REQUIRES_DISPOSITION),
        ]

    def test_summary_counts_by_class(self):
        txn = ci.build_impact_transaction(self._surfaced())
        self.assertEqual(txn["summary"][ci.CONTENT_ONLY], 1)
        self.assertEqual(txn["summary"][ci.RULE_DECISION], 1)

    def test_items_carry_operator_labels_and_options(self):
        """Each item shows an operator-facing label (never the raw field key when a label is
        provided) and the full disposition option set."""
        labels = {ci.Node("field", "AUTONOMY_LEVEL"): "How much your system may do on its own"}
        txn = ci.build_impact_transaction(self._surfaced(), labels=labels)
        item = next(i for i in txn["items"] if i["node"] == ci.Node("field", "AUTONOMY_LEVEL"))
        self.assertEqual(item["label"], "How much your system may do on its own")
        self.assertEqual(set(item["options"]), set(ci.DISPOSITION_OPTIONS))

    def test_label_falls_back_to_field_id(self):
        txn = ci.build_impact_transaction(self._surfaced())
        item = next(i for i in txn["items"] if i["node"] == ci.Node("field", "VISION_PURPOSE"))
        self.assertEqual(item["label"], "VISION_PURPOSE")

    def test_sources_section_carried_for_bidirectional_trace(self):
        sources_list = [ci.Node("answer", "V-1"), ci.Node("answer", "V-7b")]
        txn = ci.build_impact_transaction(self._surfaced(), sources=sources_list)
        self.assertEqual(txn["sources"], sources_list)


class RenderTransactionMarkdownTest(unittest.TestCase):
    def test_markdown_has_summary_items_and_options(self):
        surfaced = [ci.ImpactNode(ci.Node("field", "AUTONOMY_LEVEL"), ci.RULE_DECISION,
                                  ci.MODEL_UNSTABLE, ci.REQUIRES_DISPOSITION)]
        labels = {ci.Node("field", "AUTONOMY_LEVEL"): "How much your system may do on its own"}
        md = ci.render_impact_transaction_md(
            ci.build_impact_transaction(surfaced, labels=labels))
        self.assertIn("How much your system may do on its own", md)
        self.assertIn(ci.APPLY, md)
        self.assertIn(ci.INTENTIONAL_DIVERGENCE, md)
        # the raw field key is not the operator-facing label, but appears as a machine ref
        self.assertIn("rule", md.lower())


if __name__ == "__main__":
    unittest.main()
