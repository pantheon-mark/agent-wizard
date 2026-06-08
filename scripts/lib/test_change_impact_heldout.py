"""Blind held-out fair test for the change-propagation engine (ACCEPTANCE, not TDD).

These tests validate the FINISHED engine against a held-out dependency SHAPE using OPAQUE
IDs. The seal is the opacity: the engine contains no string matching these ids, so detecting
the upstream->downstream implication can only come from GENERICALLY following the recorded
edges (source_question_ids / _derivation_inputs / preview_doc) — never a taught match.

The shape mirrors the real held-out case structurally without naming it:
    OQ_UP (answer) -> F_UP (authored prose) -> F_MID (synthesised prose) -> F_LEAF (table)
    F_UP -> D_ALPHA (doc); F_MID -> D_BETA (doc)
    F_MID -> F_DEC (a decision/rule field)
Pass = the engine DETECTS the cross-document implication of changing OQ_UP, CLASSIFIES the
decision node as blocking, SURFACES the batched transaction, CASCADES transitively, traces
BIDIRECTIONALLY to the source, and ENFORCES (blocks emit on the un-dispositioned decision).
"""

import unittest

from field_manifest import FieldManifest, FieldSpec
import change_impact as ci


def _spec(field, *, group_id="g", derivation_class="synthesis", decision_field=False,
          decision_kind="none", value_shape="prose", source_question_ids=None, preview_doc=""):
    return FieldSpec(field=field, group_id=group_id, derivation_class=derivation_class,
                     decision_field=decision_field, decision_kind=decision_kind,
                     value_shape=value_shape, source_question_ids=list(source_question_ids or []),
                     preview_doc=preview_doc, constraints={}, source=None)


def _heldout():
    manifest = FieldManifest("heldout", {
        "F_UP": _spec("F_UP", group_id="g_up", derivation_class="authoring",
                      source_question_ids=["OQ_UP"], preview_doc="D_ALPHA"),
        "F_MID": _spec("F_MID", group_id="g_mid", derivation_class="synthesis",
                       source_question_ids=["OQ_X"], preview_doc="D_BETA"),
        "F_LEAF": _spec("F_LEAF", group_id="g_mid", derivation_class="synthesis",
                        value_shape="table", source_question_ids=["OQ_Y"]),
        "F_DEC": _spec("F_DEC", group_id="g_mid", derivation_class="classification",
                       decision_field=True, decision_kind="closed_value", value_shape="enum",
                       source_question_ids=["OQ_Z"]),
    })
    audit = {
        "F_UP": {"_derivation_class": "authoring", "_decision_field": False,
                 "_decision_kind": "none", "_derivation_inputs": []},
        "F_MID": {"_derivation_class": "synthesis", "_decision_field": False,
                  "_decision_kind": "none", "_derivation_inputs": ["F_UP"]},
        "F_LEAF": {"_derivation_class": "synthesis", "_decision_field": False,
                   "_decision_kind": "none", "_derivation_inputs": ["F_MID"]},
        "F_DEC": {"_derivation_class": "classification", "_decision_field": True,
                  "_decision_kind": "closed_value", "_derivation_inputs": ["F_MID"]},
    }
    return ci.build_graph(manifest, audit=audit), audit


class HeldOutFairTest(unittest.TestCase):
    def setUp(self):
        self.graph, self.audit = _heldout()
        self.result = ci.cascade(self.graph, ci.Node("answer", "OQ_UP"),
                                 {"_audit": self.audit})
        self.surfaced = {n.node: n for n in self.result.surfaced}

    def test_detect_and_cascade_reaches_transitive_downstream(self):
        """Changing the upstream answer cascades to the mid + leaf fields AND their docs —
        via generic edges, with no taught match."""
        for fid in ("F_UP", "F_MID", "F_LEAF", "F_DEC"):
            self.assertIn(ci.Node("field", fid), self.surfaced, fid)
        self.assertIn(ci.Node("doc", "D_ALPHA"), self.surfaced)
        self.assertIn(ci.Node("doc", "D_BETA"), self.surfaced)

    def test_classify_decision_node_blocks_others_content(self):
        self.assertEqual(self.surfaced[ci.Node("field", "F_DEC")].impact_class, ci.RULE_DECISION)
        self.assertEqual(self.surfaced[ci.Node("field", "F_UP")].impact_class, ci.CONTENT_ONLY)
        self.assertEqual(self.surfaced[ci.Node("field", "F_MID")].impact_class, ci.CONTENT_ONLY)

    def test_surface_batches_by_class(self):
        txn = ci.build_impact_transaction(self.result.surfaced)
        self.assertEqual(txn["summary"][ci.RULE_DECISION], 1)         # only F_DEC
        self.assertEqual(txn["summary"][ci.CONTENT_ONLY], 5)          # F_UP F_MID F_LEAF + 2 docs

    def test_bidirectional_trace_to_source(self):
        """From the leaf, trace back to the originating upstream answer (edit-here -> where did
        it come from), through the intermediate fields."""
        ups = ci.sources(self.graph, ci.Node("field", "F_LEAF"))
        self.assertIn(ci.Node("answer", "OQ_UP"), ups)
        self.assertIn(ci.Node("field", "F_MID"), ups)
        self.assertIn(ci.Node("field", "F_UP"), ups)

    def test_enforce_blocks_until_decision_dispositioned(self):
        events = [{"event_type": "impact_change", "change_id": "c",
                   "impacts": [{"node_kind": "field", "node_id": "F_DEC",
                                "impact_class": ci.RULE_DECISION}]}]
        self.assertTrue(ci.emit_blocked_by_pending(ci.pending_from_events(events)))
        events.append({"event_type": "impact_disposition", "change_id": "c",
                       "node_kind": "field", "node_id": "F_DEC", "disposition": ci.APPLY})
        self.assertFalse(ci.emit_blocked_by_pending(ci.pending_from_events(events)))


class HeldOutDecisionToDecisionTest(unittest.TestCase):
    """A second held-out shape: a decision change that implies a downstream decision (the
    'a decision becomes inconsistent with a prior decision' need), still fully generic."""

    def test_decision_change_cascades_to_downstream_decision(self):
        manifest = FieldManifest("heldout2", {
            "F_POLICY": _spec("F_POLICY", derivation_class="classification", decision_field=True,
                              decision_kind="policy_rule", source_question_ids=["OQ_A"]),
            "F_GATE": _spec("F_GATE", derivation_class="classification", decision_field=True,
                            decision_kind="closed_value", value_shape="enum",
                            source_question_ids=["OQ_B"]),
        })
        audit = {
            "F_POLICY": {"_derivation_class": "classification", "_decision_field": True,
                         "_decision_kind": "policy_rule", "_derivation_inputs": []},
            "F_GATE": {"_derivation_class": "classification", "_decision_field": True,
                       "_decision_kind": "closed_value", "_derivation_inputs": ["F_POLICY"]},
        }
        graph = ci.build_graph(manifest, audit=audit)
        result = ci.cascade(graph, ci.Node("answer", "OQ_A"), {"_audit": audit})
        surfaced = {n.node: n for n in result.surfaced}
        self.assertIn(ci.Node("field", "F_GATE"), surfaced)
        self.assertEqual(surfaced[ci.Node("field", "F_GATE")].impact_class, ci.RULE_DECISION)


if __name__ == "__main__":
    unittest.main()
