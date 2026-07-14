"""Tests for the evidence-checked apply/undo gate wired into
`validate_copy_run_proof` (Task 2, A2 proof-time — v0.12.0 Slice 1): the exact
F-38 regression. Before this task, `validate_copy_run_proof` accepted a
`claim_strength:"verified"` / `accepted_for_live_use:true` proof on the
strength of `validate_postwrite_verification`'s RECORD checks alone — a
well-formed record plus a non-empty `evidence_ref` STRING — without ever
opening that evidence to confirm the observed round-trip actually landed. A
proof asserting "verified" with a dangling `evidence_ref` therefore passed.
That is F-38.

This file proves the fix is SHAPE-NEUTRAL across >=2 divergent op_kinds
(Global Constraint #3, mandatory anti-overfit):

  1. gmail.message.trash — the REAL production adapter (adapters_gmail.py),
     whose evidence predicates read LABEL STATE (boolean flags).
  2. A field/spreadsheet-shaped throwaway test-fixture adapter (ported from
     Task 1's `_FieldStyleAdapter` in test_external_write_evidence_predicate.py
     — the six seeded field op_kinds have no registered production adapter at
     all, per adapter_registry.py's module docstring), whose predicates read a
     PRESTATE-DIFF — a genuinely different evaluation shape.

Also proves:
  * an adapter registered with NO evidence predicate at all (e.g.
    gmail.message.untrash, a real production adapter that defines no
    verify_apply_landed/verify_undo_restored) fails CLOSED, not open.
  * a proof lacking the evidence content needed to build an AdapterEvidence
    (missing apply_evidence/undo_evidence) fails CLOSED.
  * an op_kind with NO registered adapter at all (e.g. set_status) is
    unaffected by this gate — unchanged, pre-existing behavior (see
    test_external_write_copy_run_proof.py).
"""

import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.copy_run_proof import (  # noqa: E402
    COPY_RUN_PROOF_SCHEMA,
    validate_copy_run_proof,
    ProofResult,
)
from external_write.proof_hash import SHA256_HEX_LEN  # noqa: E402
from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA  # noqa: E402
from external_write.operations import EffectUnit  # noqa: E402
from external_write.evidence import AdapterEvidence  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    register_adapter, unregister_adapter, get_dispatch,
)
from external_write.adapters_gmail import (  # noqa: E402
    OP_TRASH, OP_UNTRASH, OP_FILTER_CREATE,
)


def _verification():
    return {
        "schema": POSTWRITE_VERIFICATION_SCHEMA,
        "verification_mode": "prestate_snapshot_diff",
        "claim_strength": "verified",
        "verifier_id": "prestate_snapshot_diff_v1",
        "source_lineage": {
            "pre_write_sources": ["prewrite_csv_backup"],
            "post_write_sources": ["live_surface_read"],
            "forbidden_sources": [
                "writer_generated_id_map",
                "live_id_column_as_truth",
                "apply_report",
            ],
        },
        "invariant_checked": "rows stable",
        "evidence_ref": "agents/handoffs/.ev.txt",
    }


def _proof(op_kind, apply_evidence=None, undo_evidence=None, accepted=True,
           durability=None, durability_evidence=None):
    apply_proof = {
        "apply_receipt_ref": "agents/handoffs/.apply_receipt.json",
        "apply_verification": _verification(),
    }
    if apply_evidence is not None:
        apply_proof["apply_evidence"] = apply_evidence

    undo_proof = {
        "undo_receipt_ref": "agents/handoffs/.undo_receipt.json",
        "undo_verification": _verification(),
    }
    if undo_evidence is not None:
        undo_proof["undo_evidence"] = undo_evidence

    durability_list = [] if durability is None else durability
    if durability_evidence is not None and durability_list:
        durability_list[0]["durability_evidence"] = durability_evidence

    return {
        "schema": COPY_RUN_PROOF_SCHEMA,
        "operation_id": "op-001",
        "op_kind": op_kind,
        "data_class": "test_rows",
        "copy_source_ref": "copies/copy.csv",
        "prestate_snapshot_ref": "copies/copy.prestate.csv",
        "copy_apply_proof": apply_proof,
        "copy_undo_proof": undo_proof,
        "durability_checks": durability_list,
        "accepted_for_live_use": accepted,
        "implementation_hash": "a" * SHA256_HEX_LEN,
        "contract_hash": "b" * SHA256_HEX_LEN,
    }


# ---------------------------------------------------------------------------
# Divergent exemplar 1: gmail.message.trash — the REAL production adapter.
# ---------------------------------------------------------------------------

class TestGmailTrashEvidenceCheckedProof(unittest.TestCase):
    """gmail.message.trash's evidence predicates read LABEL STATE (boolean
    flags) — see adapters_gmail.GmailMessageTrashAdapter."""

    def test_genuine_round_trip_passes(self):
        p = _proof(
            OP_TRASH,
            apply_evidence={
                "unit_id": "m1",
                "poststate": {"is_trashed": True, "matches_prestate": False},
            },
            undo_evidence={
                "unit_id": "m1",
                "poststate": {"is_trashed": False, "matches_prestate": True},
            },
        )
        r = validate_copy_run_proof(p)
        self.assertIsInstance(r, ProofResult)
        self.assertTrue(r.ok, r.reason)

    def test_f38_regression_verified_claim_with_not_restored_evidence_fails(self):
        """THE key regression test: claim_strength:"verified" and
        accepted_for_live_use:true are both asserted, apply genuinely landed,
        but the observed UNDO evidence shows the message was NOT restored
        (still trashed). Before this task, this proof passed — the validator
        never opened the evidence. It must now fail."""
        p = _proof(
            OP_TRASH,
            apply_evidence={
                "unit_id": "m1",
                "poststate": {"is_trashed": True, "matches_prestate": False},
            },
            undo_evidence={
                # Undo claimed to restore prestate, but the message is
                # observably STILL trashed -- matches_prestate is False.
                "unit_id": "m1",
                "poststate": {"is_trashed": True, "matches_prestate": False},
            },
            accepted=True,
        )
        # Sanity: the proof itself still asserts the strongest possible claim.
        self.assertEqual(p["copy_apply_proof"]["apply_verification"]["claim_strength"],
                         "verified")
        self.assertTrue(p["accepted_for_live_use"])
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("verify_undo_restored", r.reason)

    def test_f38_regression_verified_claim_with_not_landed_evidence_fails(self):
        """Symmetric regression on the APPLY side: apply claimed to land but
        the observed evidence shows the message never left the inbox."""
        p = _proof(
            OP_TRASH,
            apply_evidence={
                "unit_id": "m1",
                "poststate": {"is_trashed": False, "matches_prestate": True},
            },
            undo_evidence={
                "unit_id": "m1",
                "poststate": {"is_trashed": False, "matches_prestate": True},
            },
            accepted=True,
        )
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("verify_apply_landed", r.reason)

    def test_missing_apply_evidence_fails_closed(self):
        """A dangling proof -- no apply_evidence content at all -- must fail
        closed, not pass because the record alone was well-formed (this is
        F-38's literal shape: nothing here to open)."""
        p = _proof(OP_TRASH, apply_evidence=None, undo_evidence={
            "unit_id": "m1", "poststate": {"is_trashed": False, "matches_prestate": True},
        })
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("apply_evidence", r.reason)

    def test_missing_undo_evidence_fails_closed(self):
        p = _proof(OP_TRASH, apply_evidence={
            "unit_id": "m1", "poststate": {"is_trashed": True, "matches_prestate": False},
        }, undo_evidence=None)
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("undo_evidence", r.reason)

    def test_malformed_apply_evidence_fails_closed(self):
        """apply_evidence present but missing required unit_id -- still
        fails closed rather than defaulting/guessing."""
        p = _proof(OP_TRASH, apply_evidence={"poststate": {"is_trashed": True}},
                   undo_evidence={"unit_id": "m1",
                                  "poststate": {"is_trashed": False, "matches_prestate": True}})
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("apply_evidence", r.reason)


class TestAdapterWithNoPredicateFailsClosed(unittest.TestCase):
    """gmail.message.untrash is a REAL registered production adapter that
    defines no verify_apply_landed/verify_undo_restored at all (see
    adapters_gmail.GmailMessageUntrashAdapter). A 'verified' proof against it
    must fail closed -- there is nothing to check, and F-38 is exactly the
    failure of accepting 'verified' with nothing checkable."""

    def test_registered_adapter_without_predicate_fails_closed(self):
        p = _proof(
            OP_UNTRASH,
            apply_evidence={"unit_id": "m1", "poststate": {}},
            undo_evidence={"unit_id": "m1", "poststate": {}},
        )
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("declares no", r.reason)


class TestUnregisteredOpKindUnaffected(unittest.TestCase):
    """The six seeded field op_kinds have NO registered adapter at all, by
    permanent design (adapter_registry.py). This gate must not fire for them
    -- their proofs are governed by the pre-existing record checks alone,
    unchanged (see test_external_write_copy_run_proof.py for the full
    pre-existing suite, still green after this task)."""

    def test_set_status_proof_with_no_evidence_blocks_still_passes(self):
        p = _proof("set_status")  # no apply_evidence/undo_evidence at all
        r = validate_copy_run_proof(p)
        self.assertTrue(r.ok, r.reason)


# ---------------------------------------------------------------------------
# gmail.filter.create -- Task 2b follow-on (closes task-2-report.md Concern
# 1). At Task 2 time, GmailFilterCreateAdapter defined ONLY verify_durability
# -- gmail.filter.create's own copy_run_proof could never pass this gate at
# all: it would fail at "declares no evidence predicate" (the
# TestAdapterWithNoPredicateFailsClosed shape above) before durability was
# ever reached, even for a genuinely-landed create/delete round trip. Task 2b
# added verify_apply_landed/verify_undo_restored to the shipped adapter (see
# adapters_gmail.py); this is the full end-to-end exercise of all three
# predicates through validate_copy_run_proof itself, including the
# durability_checks this op_kind's contract makes mandatory
# (introduces_persistent_binding=True -- see
# contracts._gmail_filter_create_contract).
# ---------------------------------------------------------------------------

class TestGmailFilterCreateFullEvidenceCheckedProof(unittest.TestCase):

    def test_adapter_now_declares_apply_undo_predicates(self):
        """Sanity/regression guard: before Task 2b, both of these were
        None, which is exactly why every gmail.filter.create proof failed
        closed at "declares no evidence predicate" -- see
        TestAdapterWithNoPredicateFailsClosed above for that same shape
        against gmail.message.untrash, still true today."""
        dispatch = get_dispatch(OP_FILTER_CREATE)
        self.assertIsNotNone(dispatch)
        self.assertIsNotNone(dispatch.verify_apply_landed)
        self.assertIsNotNone(dispatch.verify_undo_restored)

    def test_genuine_create_then_remove_round_trip_passes(self):
        p = _proof(
            OP_FILTER_CREATE,
            apply_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": True, "filter_id": "f1"},
            },
            undo_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": False, "filter_id": None},
            },
            durability=[{"action": "sort", "binding_survived": True}],
            durability_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": True, "filter_id": "f1"},
            },
        )
        r = validate_copy_run_proof(p)
        self.assertTrue(r.ok, r.reason)

    def test_regression_apply_claimed_landed_but_filter_never_created_fails(self):
        """apply_verification asserts 'verified'/accepted, but the observed
        evidence shows the filter was never actually created -- must fail,
        not pass on the strength of the self-report alone."""
        p = _proof(
            OP_FILTER_CREATE,
            apply_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": False, "filter_id": None},
            },
            undo_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": False, "filter_id": None},
            },
            durability=[{"action": "sort", "binding_survived": True}],
            durability_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": False, "filter_id": None},
            },
            accepted=True,
        )
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("verify_apply_landed", r.reason)

    def test_regression_undo_claimed_restored_but_filter_still_exists_fails(self):
        """The undo half claims restored, but the observed evidence shows
        the filter is STILL resolvable -- delete never actually landed."""
        p = _proof(
            OP_FILTER_CREATE,
            apply_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": True, "filter_id": "f1"},
            },
            undo_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": True, "filter_id": "f1"},
            },
            durability=[{"action": "sort", "binding_survived": True}],
            durability_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": True, "filter_id": "f1"},
            },
            accepted=True,
        )
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("verify_undo_restored", r.reason)

    def test_missing_apply_evidence_fails_closed(self):
        p = _proof(
            OP_FILTER_CREATE,
            apply_evidence=None,
            undo_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": False, "filter_id": None},
            },
            durability=[{"action": "sort", "binding_survived": True}],
            durability_evidence={
                "unit_id": "filter-0",
                "poststate": {"unit_id": "filter-0", "exists": True, "filter_id": "f1"},
            },
        )
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("apply_evidence", r.reason)


# ---------------------------------------------------------------------------
# Divergent exemplar 2: a field/spreadsheet-shaped op_kind (throwaway test
# fixture, ported from Task 1's test_external_write_evidence_predicate.py
# _FieldStyleAdapter) -- proves the mechanism is not accidentally Gmail-shaped.
# Its predicates read a PRESTATE-DIFF rather than boolean label flags.
# ---------------------------------------------------------------------------

class _FieldStyleAdapter:
    """Minimal verb-shaped stand-in for a spreadsheet-style field write (e.g.
    set_status), whose evidence predicates evaluate a prestate/poststate
    VALUE DIFF rather than Gmail's boolean label flags."""

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
        if evidence.prestate is None:
            return False
        return (
            evidence.poststate.get("value") == evidence.poststate.get("intended_value")
            and evidence.prestate.get("value") != evidence.poststate.get("value")
        )

    def verify_undo_restored(self, evidence: AdapterEvidence) -> bool:
        if evidence.prestate is None:
            return False
        return evidence.poststate.get("value") == evidence.prestate.get("value")


class TestFieldStyleEvidenceCheckedProof(unittest.TestCase):

    OP_KIND = "_field_style_copy_run_proof_probe"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False,
            risk_class="reversible_external",
        )
        self.adapter = _FieldStyleAdapter()
        register_adapter(self.OP_KIND, self.adapter)

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)

    def test_genuine_round_trip_passes(self):
        p = _proof(
            self.OP_KIND,
            apply_evidence={
                "unit_id": "row1",
                "prestate": {"value": "Open"},
                "poststate": {"value": "Complete", "intended_value": "Complete"},
            },
            undo_evidence={
                "unit_id": "row1",
                "prestate": {"value": "Open"},
                "poststate": {"value": "Open"},
            },
        )
        r = validate_copy_run_proof(p)
        self.assertTrue(r.ok, r.reason)

    def test_f38_regression_apply_verified_but_value_never_changed_fails(self):
        """The apply half claims 'verified'/accepted, but the observed
        poststate value never actually moved off the prestate value -- the
        prestate-diff equivalent of F-38's dangling-evidence-ref regression."""
        p = _proof(
            self.OP_KIND,
            apply_evidence={
                "unit_id": "row1",
                "prestate": {"value": "Open"},
                "poststate": {"value": "Open", "intended_value": "Complete"},
            },
            undo_evidence={
                "unit_id": "row1",
                "prestate": {"value": "Open"},
                "poststate": {"value": "Open"},
            },
            accepted=True,
        )
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("verify_apply_landed", r.reason)

    def test_f38_regression_undo_verified_but_value_not_restored_fails(self):
        p = _proof(
            self.OP_KIND,
            apply_evidence={
                "unit_id": "row1",
                "prestate": {"value": "Open"},
                "poststate": {"value": "Complete", "intended_value": "Complete"},
            },
            undo_evidence={
                "unit_id": "row1",
                "prestate": {"value": "Open"},
                "poststate": {"value": "Complete"},
            },
            accepted=True,
        )
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("verify_undo_restored", r.reason)

    def test_missing_evidence_content_fails_closed(self):
        p = _proof(self.OP_KIND)  # no apply_evidence/undo_evidence at all
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("apply_evidence", r.reason)


# ---------------------------------------------------------------------------
# Durability evidence-check path (the "+ durability when
# introduces_persistent_binding" half of Task 2's spec). A throwaway
# persistent-binding fixture that defines ALL THREE predicates (a different
# evaluation shape -- prestate-diff -- from gmail.filter.create's boolean
# existence check below) so this code path is exercised end-to-end through
# validate_copy_run_proof itself with a divergent poststate shape, not just
# the raw predicate (already covered by test_external_write_evidence_
# predicate.py for gmail.filter.create).
#
# NOTE (Task 2b follow-on, closes task-2-report.md Concern 1): at Task 2
# time, GmailFilterCreateAdapter defined ONLY verify_durability --
# gmail.filter.create's own copy_run_proof could never pass the apply/undo
# evidence gate above (it would always fail at "declares no evidence
# predicate" before durability was even reached). Task 2b added
# verify_apply_landed/verify_undo_restored to GmailFilterCreateAdapter (see
# adapters_gmail.py) -- TestGmailFilterCreateFullEvidenceCheckedProof below
# is the full end-to-end copy_run_proof exercise of the shipped
# gmail.filter.create adapter (all three predicates + durability_checks)
# this note used to flag as missing.
# ---------------------------------------------------------------------------

class _BindingFieldStyleAdapter(_FieldStyleAdapter):
    """Extends _FieldStyleAdapter with a durability predicate reading the
    SAME prestate-diff-style poststate shape as filter-create's existence
    check, generalized: 'durable' iff the observed poststate still reports
    the binding present."""

    def verify_durability(self, evidence: AdapterEvidence) -> bool:
        return bool(evidence.poststate.get("binding_present"))


class TestFieldStyleDurabilityEvidenceCheckedProof(unittest.TestCase):

    OP_KIND = "_field_style_copy_run_proof_durability_probe"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=True,
            risk_class="standing_automation",
        )
        self.adapter = _BindingFieldStyleAdapter()
        register_adapter(self.OP_KIND, self.adapter)

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)

    def _apply_undo_evidence(self):
        return dict(
            apply_evidence={
                "unit_id": "row1", "prestate": {"value": "Open"},
                "poststate": {"value": "Complete", "intended_value": "Complete"},
            },
            undo_evidence={
                "unit_id": "row1", "prestate": {"value": "Open"},
                "poststate": {"value": "Open"},
            },
        )

    def test_genuine_surviving_binding_passes(self):
        p = _proof(
            self.OP_KIND,
            **self._apply_undo_evidence(),
            durability=[{"action": "sort", "binding_survived": True}],
            durability_evidence={"unit_id": "row1", "poststate": {"binding_present": True}},
        )
        r = validate_copy_run_proof(p)
        self.assertTrue(r.ok, r.reason)

    def test_f38_regression_durability_asserted_survived_but_evidence_shows_gone_fails(self):
        """The durability entry self-reports binding_survived:true, but the
        observed evidence shows the binding is actually gone after the
        ordinary operator action -- must fail even though the self-report
        alone would have passed the pre-existing check."""
        p = _proof(
            self.OP_KIND,
            **self._apply_undo_evidence(),
            durability=[{"action": "sort", "binding_survived": True}],
            durability_evidence={"unit_id": "row1", "poststate": {"binding_present": False}},
        )
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("verify_durability", r.reason)

    def test_missing_durability_evidence_fails_closed(self):
        p = _proof(
            self.OP_KIND,
            **self._apply_undo_evidence(),
            durability=[{"action": "sort", "binding_survived": True}],
        )
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("durability_evidence", r.reason)


if __name__ == "__main__":
    unittest.main()
