"""Tests for the per-op_kind EVIDENCE PREDICATE mechanism (Task 1, B4/T1 —
v0.12.0 Slice 1): proves the captured `verify_apply_landed` /
`verify_undo_restored` / `verify_durability` predicates (adapter_registry.py)
actually evaluate a kernel-supplied `evidence.AdapterEvidence` correctly, and
that the mechanism is SHAPE-NEUTRAL across ≥2 divergent op_kinds (Global
Constraint #3, mandatory anti-overfit):

  1. gmail.message.trash (real production adapter, adapters_gmail.py) — reads
     LABEL STATE (boolean flags already produced by the existing
     verify_one/_label_diff shape).
  2. A field/spreadsheet-shaped op_kind (a throwaway test-fixture adapter,
     per the task's ambiguity-resolution note — the six seeded field
     op_kinds have no registered production adapter at all; see
     adapter_registry.py's module docstring, unchanged by this task) —
     reads a PRESTATE-DIFF (comparing observed prestate/poststate value
     mappings), a genuinely different evaluation shape from Gmail's boolean
     flags.

Also proves the anti-tautology structural property at the call-site level:
the captured predicate's signature is exactly `(self, evidence)` — no path,
ref, or filename parameter through which a predicate could reach outside the
evidence it was hafnded — for BOTH divergent op_kinds, and that
`verify_durability` (optional) is exercised correctly on gmail.filter.create,
the one op_kind in this reference set with introduces_persistent_binding=True.

None of this wires the predicate into `validate_copy_run_proof` (Task 2) or
`_run_adapter_operation` (Task 3) — this task hand-constructs
`AdapterEvidence` the way a later kernel task will, and calls the captured
dispatch predicate directly, exactly the shape those later tasks will use.
"""

import inspect
import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract, SourceLineage  # noqa: E402
from external_write.evidence import AdapterEvidence  # noqa: E402
from external_write.operations import EffectUnit  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    register_adapter, unregister_adapter, get_dispatch,
)
from external_write.adapters_gmail import (  # noqa: E402
    OP_TRASH, OP_FILTER_CREATE,
    GmailMessageTrashAdapter, GmailFilterCreateAdapter,
)


def _lineage():
    return SourceLineage(
        pre_write_sources=("prewrite_csv_backup",),
        post_write_sources=("live_surface_read",),
        forbidden_verification_inputs=("writer_generated_id_map",),
    )


# ---------------------------------------------------------------------------
# Divergent exemplar 2: a field/spreadsheet-shaped adapter (throwaway test
# fixture — the six seeded field op_kinds have no registered production
# adapter; see adapter_registry.py's module docstring, unaffected by this
# task). Its predicates read a PRESTATE-DIFF, a different evaluation shape
# from Gmail's live-label boolean flags, proving the (self, evidence) -> bool
# signature is not accidentally Gmail-shaped.
# ---------------------------------------------------------------------------

class _FieldStyleAdapter:
    """Minimal verb-shaped stand-in for a spreadsheet-style field write
    (e.g. set_status), whose evidence predicates evaluate a prestate/
    poststate VALUE DIFF rather than Gmail's boolean label flags."""

    def plan(self, params):
        params = params or {}
        return [EffectUnit(unit_id=r["row_id"], target_ref=r)
                for r in params.get("rows", [])]

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return {}

    def verify_apply_landed(self, evidence: AdapterEvidence) -> bool:
        """Landed iff the observed poststate value equals the intended
        value AND differs from the observed prestate value (a genuine
        change happened) -- a prestate-diff evaluation, not a boolean flag
        read off a live re-query."""
        if evidence.prestate is None:
            return False
        return (
            evidence.poststate.get("value") == evidence.poststate.get("intended_value")
            and evidence.prestate.get("value") != evidence.poststate.get("value")
        )

    def verify_undo_restored(self, evidence: AdapterEvidence) -> bool:
        """Restored iff the observed poststate value equals the observed
        prestate's ORIGINAL value -- the undo-side prestate-diff."""
        if evidence.prestate is None:
            return False
        return evidence.poststate.get("value") == evidence.prestate.get("value")


class TestFieldShapedAdapterEvidencePredicate(unittest.TestCase):
    """Exemplar 2 -- field/spreadsheet-shaped op_kind, prestate-diff."""

    OP_KIND = "_field_style_evidence_probe"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="reversible_external",
        )
        self.adapter = _FieldStyleAdapter()
        register_adapter(self.OP_KIND, self.adapter)

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)

    def _dispatch(self):
        return get_dispatch(self.OP_KIND)

    def test_captured_off_class(self):
        dispatch = self._dispatch()
        self.assertIs(dispatch.verify_apply_landed, _FieldStyleAdapter.verify_apply_landed)
        self.assertIs(dispatch.verify_undo_restored, _FieldStyleAdapter.verify_undo_restored)
        # This exemplar does not define verify_durability -- correctly None.
        self.assertIsNone(dispatch.verify_durability)

    def test_apply_landed_true_when_value_actually_changed_to_intended(self):
        dispatch = self._dispatch()
        evidence = AdapterEvidence(
            op_kind=self.OP_KIND, unit_id="row1",
            prestate={"value": "Open"},
            poststate={"value": "Complete", "intended_value": "Complete"},
            source_lineage=_lineage(),
        )
        self.assertTrue(dispatch.verify_apply_landed(dispatch.instance, evidence))

    def test_apply_landed_false_when_poststate_still_matches_prestate(self):
        """The write claimed to land but the observed poststate is
        unchanged from prestate -- a false 'verified' claim this predicate
        must catch (this is exactly the shape of F-38's regression, proven
        generically here rather than against copy_run_proof, which is
        Task 2's job)."""
        dispatch = self._dispatch()
        evidence = AdapterEvidence(
            op_kind=self.OP_KIND, unit_id="row1",
            prestate={"value": "Open"},
            poststate={"value": "Open", "intended_value": "Complete"},
            source_lineage=_lineage(),
        )
        self.assertFalse(dispatch.verify_apply_landed(dispatch.instance, evidence))

    def test_undo_restored_true_when_poststate_matches_original_prestate(self):
        dispatch = self._dispatch()
        evidence = AdapterEvidence(
            op_kind=self.OP_KIND, unit_id="row1",
            prestate={"value": "Open"},
            poststate={"value": "Open"},
            source_lineage=_lineage(),
        )
        self.assertTrue(dispatch.verify_undo_restored(dispatch.instance, evidence))

    def test_undo_restored_false_when_poststate_diverges_from_prestate(self):
        dispatch = self._dispatch()
        evidence = AdapterEvidence(
            op_kind=self.OP_KIND, unit_id="row1",
            prestate={"value": "Open"},
            poststate={"value": "Complete"},
            source_lineage=_lineage(),
        )
        self.assertFalse(dispatch.verify_undo_restored(dispatch.instance, evidence))

    def test_predicate_signature_has_no_path_or_ref_parameter(self):
        dispatch = self._dispatch()
        for predicate in (dispatch.verify_apply_landed, dispatch.verify_undo_restored):
            params = list(inspect.signature(predicate).parameters)
            self.assertEqual(params, ["self", "evidence"])


# ---------------------------------------------------------------------------
# Divergent exemplar 1: gmail.message.trash — the REAL production adapter.
# Its predicates read LABEL STATE (boolean flags), a genuinely different
# evaluation shape from the field adapter's prestate-diff above.
# ---------------------------------------------------------------------------

class TestGmailAdapterEvidencePredicate(unittest.TestCase):

    def test_captured_off_class_for_trash(self):
        dispatch = get_dispatch(OP_TRASH)
        self.assertIsNotNone(dispatch)
        self.assertIs(dispatch.verify_apply_landed,
                      GmailMessageTrashAdapter.verify_apply_landed)
        self.assertIs(dispatch.verify_undo_restored,
                      GmailMessageTrashAdapter.verify_undo_restored)

    def test_apply_landed_true_when_poststate_reports_trashed(self):
        dispatch = get_dispatch(OP_TRASH)
        evidence = AdapterEvidence(
            op_kind=OP_TRASH, unit_id="m1",
            poststate={"message_id": "m1", "current_label_ids": ["TRASH"],
                       "is_trashed": True, "matches_prestate": False},
            source_lineage=_lineage(),
        )
        self.assertTrue(dispatch.verify_apply_landed(dispatch.instance, evidence))

    def test_apply_landed_false_when_poststate_reports_not_trashed(self):
        """The apply claimed to land but the observed live label state
        shows the message never left the inbox -- must be caught, not
        rubber-stamped."""
        dispatch = get_dispatch(OP_TRASH)
        evidence = AdapterEvidence(
            op_kind=OP_TRASH, unit_id="m1",
            poststate={"message_id": "m1", "current_label_ids": ["INBOX"],
                       "is_trashed": False, "matches_prestate": True},
            source_lineage=_lineage(),
        )
        self.assertFalse(dispatch.verify_apply_landed(dispatch.instance, evidence))

    def test_undo_restored_true_when_poststate_matches_prestate(self):
        dispatch = get_dispatch(OP_TRASH)
        evidence = AdapterEvidence(
            op_kind=OP_TRASH, unit_id="m1",
            poststate={"message_id": "m1", "current_label_ids": ["INBOX"],
                       "is_trashed": False, "matches_prestate": True},
            source_lineage=_lineage(),
        )
        self.assertTrue(dispatch.verify_undo_restored(dispatch.instance, evidence))

    def test_undo_restored_false_when_poststate_still_diverges_from_prestate(self):
        dispatch = get_dispatch(OP_TRASH)
        evidence = AdapterEvidence(
            op_kind=OP_TRASH, unit_id="m1",
            poststate={"message_id": "m1", "current_label_ids": ["TRASH"],
                       "is_trashed": True, "matches_prestate": False},
            source_lineage=_lineage(),
        )
        self.assertFalse(dispatch.verify_undo_restored(dispatch.instance, evidence))

    def test_predicate_signature_has_no_path_or_ref_parameter(self):
        dispatch = get_dispatch(OP_TRASH)
        for predicate in (dispatch.verify_apply_landed, dispatch.verify_undo_restored):
            params = list(inspect.signature(predicate).parameters)
            self.assertEqual(params, ["self", "evidence"])


# ---------------------------------------------------------------------------
# Optional verify_durability — exercised on gmail.filter.create, the one
# op_kind in this reference set with introduces_persistent_binding=True
# (contracts._gmail_filter_create_contract).
# ---------------------------------------------------------------------------

class TestGmailFilterCreateDurabilityPredicate(unittest.TestCase):

    def test_filter_create_captures_verify_durability(self):
        dispatch = get_dispatch(OP_FILTER_CREATE)
        self.assertIsNotNone(dispatch)
        self.assertIs(dispatch.verify_durability, GmailFilterCreateAdapter.verify_durability)

    def test_durability_true_when_poststate_reports_filter_still_exists(self):
        dispatch = get_dispatch(OP_FILTER_CREATE)
        evidence = AdapterEvidence(
            op_kind=OP_FILTER_CREATE, unit_id="filter-0",
            poststate={"unit_id": "filter-0", "exists": True, "filter_id": "filter-1"},
            source_lineage=_lineage(),
        )
        self.assertTrue(dispatch.verify_durability(dispatch.instance, evidence))

    def test_durability_false_when_poststate_reports_filter_gone(self):
        """The op introduced a persistent binding but a later ordinary
        operator action made it not survive -- the exact case
        copy_run_proof's durability_checks (Task 2) exists to catch."""
        dispatch = get_dispatch(OP_FILTER_CREATE)
        evidence = AdapterEvidence(
            op_kind=OP_FILTER_CREATE, unit_id="filter-0",
            poststate={"unit_id": "filter-0", "exists": False, "filter_id": None},
            source_lineage=_lineage(),
        )
        self.assertFalse(dispatch.verify_durability(dispatch.instance, evidence))

    def test_durability_predicate_signature_has_no_path_or_ref_parameter(self):
        dispatch = get_dispatch(OP_FILTER_CREATE)
        params = list(inspect.signature(dispatch.verify_durability).parameters)
        self.assertEqual(params, ["self", "evidence"])


if __name__ == "__main__":
    unittest.main()
