"""Tests for Task 5 (A1/T5 — v0.12.0 Slice 1, design §4): the frozen
`reviewed_set` + apply-by-id enforcement + receipt binding that closes F-40.

F-40: the estate approved "clean promo senders" (a specific reviewed set of
message ids) but the tool actually ran `--all` — every junk-flagged message
across every sender — and recorded an agent-paraphrased consent. The
REVIEWED set and the APPLIED set diverged, silently. This suite proves:

  1. APPLY-BY-ID: `run_enveloped_operation` applies ONLY units whose stable
     `unit_id` is a member of the envelope's FROZEN `reviewed_set` — never a
     live re-scan's fresh result. A planned unit outside the frozen set
     refuses with a CONCRETE diff (added ids named explicitly), and NOTHING
     is applied (not even the legitimate units in the same op) — never a
     partial silent apply.
  2. FORCED DIFF-AND-RECONFIRM on an unavoidable re-scan:
     `diff_reviewed_set_against_rescan` / `refuse_on_rescan_divergence`
     compute an explicit, id-keyed diff (added/removed/changed
     category/changed protected-status) — never a full-population diff —
     and force a refusal whenever the re-scan disagrees with the frozen set
     in any way.
  3. RECEIPT BINDING: an INDEPENDENTLY-persisted run-consent receipt must be
     bound to the envelope's CURRENT `reviewed_set_digest`. A receipt that is
     absent, or bound to a STALE digest (because the reviewed set was
     mutated/reordered/re-scanned after the operator approved it — even via a
     single, fully SELF-CONSISTENT tamper of the envelope file, which the
     internal `is_spendable()` check alone cannot catch), refuses.

Anti-overfit (Global Constraint #3): every mechanism is proven on TWO
divergent op_kinds — a Gmail-label-shaped op (mirroring the REAL
`gmail.message.trash` adapter's `message_id` identity; `planned_unit_ids` is
also exercised directly against the real adapter) and a field/row-shaped op
whose `unit_id` is an explicit vendor row key, never a list position — the
row-identity-vs-row-number distinction the design brief calls out
specifically. The two run-path op_kinds are registered `reversible_external`
(ungated), the same isolation convention `test_external_write_run_envelope.py`
already uses to exercise the run-path mechanism independently of the
descriptor/acceptance-ceremony chain (out of this task's scope).

Runner: unittest, from wizard/scripts. Stdlib only.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.operations import Operation, EffectUnit  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    register_adapter, unregister_adapter,
)
from external_write.adapters import planned_unit_ids  # noqa: E402
from external_write.adapters_gmail import OP_TRASH  # noqa: E402
from external_write.read_facade import ReadFacade, register_read_facade, unregister_read_facade  # noqa: E402
from external_write.run_envelope import (  # noqa: E402
    compute_reviewed_set_digest,
    derive_ledger_window_id,
    diff_reviewed_set_against_rescan,
    load_run_consent_receipt,
    load_run_envelope,
    mint_run_envelope,
    refuse_on_rescan_divergence,
    run_enveloped_operation,
    verify_run_consent_receipt,
    RUN_CONSENT_RECEIPT_SCHEMA,
)


def _receipt(op):
    digest = hashlib.sha256(op.canonical_repr().encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=900)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    return {"approved_operation_digest": digest, "expires_at": expires_at}


def _reviewed_entry(unit_id, category="clean_promo_sender", protected=False):
    return {"unit_id": unit_id, "prestate_digest": f"d-{unit_id}",
            "intended_mutation": {"action": "trash"},
            "category": category, "protected_status": protected}


# ===========================================================================
# 0. planned_unit_ids — the primitive apply-by-id relies on
# ===========================================================================

class TestPlannedUnitIds(unittest.TestCase):

    def test_real_gmail_trash_adapter_yields_message_ids(self):
        # Exercises the REAL adapters_gmail.GmailMessageTrashAdapter (already
        # registered at module import) — not a fixture stand-in.
        op = Operation(surface="gmail", op_kind=OP_TRASH, batch_id="b1",
                       params={"messages": [{"message_id": "m1"},
                                            {"message_id": "m2"}]})
        self.assertEqual(planned_unit_ids(op), ["m1", "m2"])

    def test_malformed_params_yields_none_not_a_crash(self):
        op = Operation(surface="gmail", op_kind=OP_TRASH, batch_id="b1",
                       params={"messages": [{"no_message_id_key": True}]})
        self.assertIsNone(planned_unit_ids(op))

    def test_unregistered_op_kind_falls_back_to_object_id(self):
        op = Operation(surface="sheet", op_kind="_no_such_registered_op_kind",
                       batch_id="b1", object_id="row-42")
        self.assertEqual(planned_unit_ids(op), ["row-42"])


# ===========================================================================
# 1. Apply-by-id — full run_enveloped_operation, ≥2 divergent op_kinds
# ===========================================================================

class _GmailShapedWriteClient:
    """A message_id -> label-set store, mirroring the REAL Gmail adapter's
    label-delta shape (never the real vendor SDK)."""
    def __init__(self, store):
        self._store = store
        self.trashed = []

    def trash(self, message_id):
        self.trashed.append(message_id)
        self._store[message_id] = "TRASH"


class _GmailShapedReadOnlyClient:
    def __init__(self, store):
        self._store = store

    def read_label(self, message_id):
        return self._store.get(message_id)


class _GmailShapedReadFacade(ReadFacade):
    read_methods = ("read_label",)

    def read_label(self, message_id):
        return self._read("read_label", message_id)


class _GmailShapedAdapter:
    """Ungated Gmail-labels-SHAPED fixture (isolates the run-path mechanism
    from the descriptor/acceptance-ceremony chain — same convention
    test_external_write_run_envelope.py uses). unit_id is the message_id, the
    exact stable vendor identity the real adapter assigns."""

    def plan(self, params):
        params = params or {}
        return [EffectUnit(unit_id=m["message_id"], target_ref=m)
               for m in params.get("messages", [])]

    def apply_one(self, raw_client, unit):
        raw_client.trash(unit.unit_id)

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        return {"label": observer.read_label(unit.unit_id)}

    def verify_apply_landed(self, evidence):
        return evidence.poststate.get("label") == "TRASH"


class _FieldShapedWriteClient:
    def __init__(self, store):
        self._store = store
        self.writes = []

    def write_row(self, row_key, value):
        self.writes.append((row_key, value))
        self._store[row_key] = value


class _FieldShapedReadOnlyClient:
    def __init__(self, store):
        self._store = store

    def read_row(self, row_key):
        return self._store.get(row_key)


class _FieldShapedReadFacade(ReadFacade):
    read_methods = ("read_row",)

    def read_row(self, row_key):
        return self._read("read_row", row_key)


class _FieldShapedAdapter:
    """Field/row-shaped fixture whose unit_id is an EXPLICIT vendor row key
    (`row_key`), never derived from the row's POSITION in `params['rows']` —
    the row-identity-vs-row-number distinction the design brief calls out.
    Reordering the input rows must not change which id is which."""

    def plan(self, params):
        params = params or {}
        return [EffectUnit(unit_id=r["row_key"], target_ref=r)
               for r in params.get("rows", [])]

    def apply_one(self, raw_client, unit):
        raw_client.write_row(unit.unit_id, unit.target_ref["intended_value"])

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        return {"value": observer.read_row(unit.unit_id),
                "intended_value": unit.target_ref["intended_value"]}

    def verify_apply_landed(self, evidence):
        return evidence.poststate.get("value") == evidence.poststate.get("intended_value")


class _ApplyByIdFixtureCase(unittest.TestCase):
    """Shared setup for both op_kind exemplars — subclasses set OP_KIND,
    ADAPTER_CLS, READ_FACADE_CLS."""

    OP_KIND = None
    ADAPTER_CLS = None
    READ_FACADE_CLS = None

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND, writes=(), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="reversible_external",  # ungated: isolates the run-path mechanism
            read_only_scope="fixture.readonly")
        register_read_facade(self.OP_KIND, self.READ_FACADE_CLS)
        register_adapter(self.OP_KIND, self.ADAPTER_CLS())

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)
        unregister_read_facade(self.OP_KIND)

    def _mint(self, d, reviewed_set, run_id="run-1"):
        return mint_run_envelope(
            run_id=run_id, capability_id="cap:test", op_kind=self.OP_KIND,
            contract_hash="ch", implementation_hash="ih",
            reviewed_set=reviewed_set, population_count=max(len(reviewed_set), 1),
            stratification_summary={}, operator_approval_verbatim="yes, apply these",
            consent_sentence_shown="Apply the reviewed set.",
            approved_at="2026-07-19T22:45:48Z", envelope_dir=d).envelope


class TestApplyByIdGmailShaped(_ApplyByIdFixtureCase):

    OP_KIND = "_awb_gmail_labels_probe"
    ADAPTER_CLS = _GmailShapedAdapter
    READ_FACADE_CLS = _GmailShapedReadFacade

    def _op(self, message_ids):
        return Operation(surface="fixture_gmail", op_kind=self.OP_KIND, batch_id="b1",
                         params={"messages": [{"message_id": mid} for mid in message_ids]})

    def test_applies_when_planned_ids_exactly_match_frozen_reviewed_set(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = [_reviewed_entry("m-clean-1"), _reviewed_entry("m-clean-2")]
            env = self._mint(d, reviewed)
            store = {}
            write_client = _GmailShapedWriteClient(store)
            op = self._op(["m-clean-1", "m-clean-2"])
            updated, result = run_enveloped_operation(
                env, op, _receipt(op), write_client,
                read_only_client=_GmailShapedReadOnlyClient(store),
                envelope_dir=d, ledger_dir=d)
            self.assertEqual(result.status, "written")
            self.assertEqual(sorted(write_client.trashed), ["m-clean-1", "m-clean-2"])

    def test_refuses_the_whole_op_when_one_planned_id_is_outside_the_reviewed_set(self):
        # The F-40 regression itself: the operator approved "clean promo
        # senders" (m-clean-1, m-clean-2); the tool ran --all and also
        # touched m-other-99 (a message outside the reviewed set).
        with tempfile.TemporaryDirectory() as d:
            reviewed = [_reviewed_entry("m-clean-1"), _reviewed_entry("m-clean-2")]
            env = self._mint(d, reviewed)
            store = {}
            write_client = _GmailShapedWriteClient(store)
            op = self._op(["m-clean-1", "m-clean-2", "m-other-99"])
            updated, result = run_enveloped_operation(
                env, op, _receipt(op), write_client,
                read_only_client=_GmailShapedReadOnlyClient(store),
                envelope_dir=d, ledger_dir=d)
            self.assertEqual(result.status, "refused")
            self.assertEqual(result.detail.get("gate"), "run_envelope_apply_by_id")
            self.assertEqual(result.detail["diff"]["added_ids"], ["m-other-99"])
            # NOTHING was applied — not even the two legitimate ids in the
            # same op. Never a partial silent apply on a divergent set.
            self.assertEqual(write_client.trashed, [])
            self.assertEqual(len(updated.tranches), 0)


class TestApplyByIdFieldShaped(_ApplyByIdFixtureCase):

    OP_KIND = "_awb_field_row_key_probe"
    ADAPTER_CLS = _FieldShapedAdapter
    READ_FACADE_CLS = _FieldShapedReadFacade

    def _op(self, row_keys):
        rows = [{"row_key": rk, "intended_value": "Complete"} for rk in row_keys]
        return Operation(surface="fixture_sheet", op_kind=self.OP_KIND, batch_id="b1",
                         params={"rows": rows})

    def test_applies_when_planned_row_keys_are_a_reordered_subset_of_frozen_set(self):
        # Row IDENTITY, not row NUMBER: the reviewed set was approved in one
        # order; the op plans the SAME row keys in a DIFFERENT order. Because
        # apply-by-id checks set membership (identity), not list position,
        # this must still apply cleanly.
        with tempfile.TemporaryDirectory() as d:
            reviewed = [_reviewed_entry("R-77"), _reviewed_entry("R-12"), _reviewed_entry("R-3")]
            env = self._mint(d, reviewed)
            store = {}
            write_client = _FieldShapedWriteClient(store)
            op = self._op(["R-3", "R-77"])  # reordered subset
            updated, result = run_enveloped_operation(
                env, op, _receipt(op), write_client,
                read_only_client=_FieldShapedReadOnlyClient(store),
                envelope_dir=d, ledger_dir=d)
            self.assertEqual(result.status, "written")
            self.assertEqual(sorted(rk for rk, _ in write_client.writes), ["R-3", "R-77"])

    def test_refuses_when_a_rescanned_row_id_falls_outside_the_reviewed_set(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = [_reviewed_entry("R-1"), _reviewed_entry("R-2")]
            env = self._mint(d, reviewed)
            store = {}
            write_client = _FieldShapedWriteClient(store)
            # A live re-scan swept in R-999, a row never reviewed/approved.
            op = self._op(["R-2", "R-1", "R-999"])
            updated, result = run_enveloped_operation(
                env, op, _receipt(op), write_client,
                read_only_client=_FieldShapedReadOnlyClient(store),
                envelope_dir=d, ledger_dir=d)
            self.assertEqual(result.status, "refused")
            self.assertEqual(result.detail.get("gate"), "run_envelope_apply_by_id")
            self.assertEqual(result.detail["diff"]["added_ids"], ["R-999"])
            self.assertEqual(write_client.writes, [])
            self.assertEqual(len(updated.tranches), 0)


# ===========================================================================
# 2. Forced diff-and-reconfirm on an unavoidable re-scan
# ===========================================================================

class TestDiffAndReconfirmOnRescan(unittest.TestCase):

    def test_matching_rescan_is_not_divergent_and_returns_none(self):
        frozen = [_reviewed_entry("a"), _reviewed_entry("b")]
        rescan = [_reviewed_entry("a"), _reviewed_entry("b")]
        self.assertIsNone(refuse_on_rescan_divergence(frozen, rescan))

    def test_diff_identifies_added_removed_changed_category_and_protected_status(self):
        frozen = [
            _reviewed_entry("a", category="clean_promo_sender", protected=False),
            _reviewed_entry("b", category="clean_promo_sender", protected=False),
            _reviewed_entry("c", category="clean_promo_sender", protected=False),
        ]
        rescan = [
            _reviewed_entry("a", category="clean_promo_sender", protected=False),  # unchanged
            _reviewed_entry("b", category="reclassified_sender", protected=False),  # category changed
            _reviewed_entry("c", category="clean_promo_sender", protected=True),  # protected changed
            _reviewed_entry("d", category="clean_promo_sender", protected=False),  # added
            # "b" stays present above; simulate a REMOVAL via a 4-entry frozen set instead:
        ]
        diff = diff_reviewed_set_against_rescan(frozen, rescan)
        self.assertEqual(diff.added_ids, ("d",))
        self.assertEqual(diff.removed_ids, ())
        self.assertEqual(diff.changed_category_ids, ("b",))
        self.assertEqual(diff.changed_protected_status_ids, ("c",))
        self.assertTrue(diff.is_divergent())

    def test_diff_identifies_removed_ids(self):
        frozen = [_reviewed_entry("a"), _reviewed_entry("b"), _reviewed_entry("c")]
        rescan = [_reviewed_entry("a")]
        diff = diff_reviewed_set_against_rescan(frozen, rescan)
        self.assertEqual(diff.removed_ids, ("b", "c"))
        self.assertEqual(diff.added_ids, ())

    def test_refusal_carries_the_concrete_diff_never_a_full_population_diff(self):
        # A large frozen population where only ONE id diverges — the refusal
        # must name exactly that one id, never dump the whole population.
        frozen = [_reviewed_entry(f"id-{i}") for i in range(500)]
        rescan = [_reviewed_entry(f"id-{i}") for i in range(500)] + [_reviewed_entry("id-new")]
        refusal = refuse_on_rescan_divergence(frozen, rescan)
        self.assertIsNotNone(refusal)
        self.assertEqual(refusal.status, "refused")
        self.assertEqual(refusal.detail["gate"], "reviewed_set_rescan_divergence")
        self.assertEqual(refusal.detail["diff"]["added_ids"], ["id-new"])
        self.assertEqual(refusal.detail["diff"]["removed_ids"], [])


# ===========================================================================
# 3. Receipt binding
# ===========================================================================

class TestReceiptBinding(_ApplyByIdFixtureCase):

    OP_KIND = "_awb_receipt_binding_probe"
    ADAPTER_CLS = _FieldShapedAdapter
    READ_FACADE_CLS = _FieldShapedReadFacade

    def _op(self, row_keys):
        rows = [{"row_key": rk, "intended_value": "Complete"} for rk in row_keys]
        return Operation(surface="fixture_sheet", op_kind=self.OP_KIND, batch_id="b1",
                         params={"rows": rows})

    def test_mint_persists_a_receipt_bound_to_the_reviewed_set_digest(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = [_reviewed_entry("R-1")]
            res = mint_run_envelope(
                run_id="run-r", capability_id="cap:test", op_kind=self.OP_KIND,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=reviewed, population_count=1, stratification_summary={},
                operator_approval_verbatim="yes", consent_sentence_shown="Apply 1 change.",
                approved_at="2026-07-19T22:45:48Z", envelope_dir=d)
            self.assertTrue(res.accepted, res.reason)
            self.assertIsNotNone(res.receipt_ref)
            receipt = load_run_consent_receipt("run-r", receipt_dir=d)
            self.assertIsNotNone(receipt)
            self.assertEqual(receipt["schema"], RUN_CONSENT_RECEIPT_SCHEMA)
            self.assertEqual(receipt["reviewed_set_digest"],
                             compute_reviewed_set_digest(reviewed))
            ok, reason = verify_run_consent_receipt(res.envelope, receipt_dir=d)
            self.assertTrue(ok, reason)

    def test_run_path_refuses_when_no_receipt_was_ever_minted(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = [_reviewed_entry("R-1")]
            env = self._mint(d, reviewed)
            # Delete the receipt the mint just wrote, simulating "never
            # independently recorded" (or a hand-built envelope skipping the
            # ceremony's receipt half).
            receipt_path = Path(d) / "run-1.consent_receipt.json"
            self.assertTrue(receipt_path.exists())
            receipt_path.unlink()

            store = {}
            write_client = _FieldShapedWriteClient(store)
            op = self._op(["R-1"])
            updated, result = run_enveloped_operation(
                env, op, _receipt(op), write_client,
                read_only_client=_FieldShapedReadOnlyClient(store),
                envelope_dir=d, ledger_dir=d)
            self.assertEqual(result.status, "refused")
            self.assertEqual(result.detail.get("gate"), "run_envelope_consent_receipt")
            self.assertEqual(write_client.writes, [])

    def test_self_consistent_tamper_of_the_envelope_is_still_caught_by_the_receipt(self):
        # The threat is real: someone rewrites the PERSISTED envelope's
        # reviewed_set to a DIFFERENT set, recomputes reviewed_set_digest AND
        # consent.approval_bound_to to match — the envelope is internally
        # self-consistent (is_spendable() would say True) — but the
        # INDEPENDENTLY-persisted receipt is still bound to the ORIGINAL
        # digest the operator actually approved, so the run must refuse.
        with tempfile.TemporaryDirectory() as d:
            original_reviewed = [_reviewed_entry("R-1")]
            self._mint(d, original_reviewed)

            new_reviewed = [_reviewed_entry("R-1"), _reviewed_entry("R-999")]
            new_digest = compute_reviewed_set_digest(new_reviewed)

            env_path = Path(d) / "run-1.json"
            raw = json.loads(env_path.read_text())
            raw["reviewed_set"] = new_reviewed
            raw["reviewed_set_digest"] = new_digest
            raw["consent"]["approval_bound_to"] = new_digest
            # ledger_window_id is DERIVED from reviewed_set_digest (among
            # other identity fields) -- a truly self-consistent tamper must
            # also recompute it, or is_spendable()'s existing tamper check
            # would ALREADY catch the change (a weaker test than intended;
            # the point here is that even a FULLY self-consistent tamper is
            # still caught by the independent receipt).
            raw["ledger_window_id"] = derive_ledger_window_id(
                run_id=raw["run_id"], capability_id=raw["capability_id"],
                op_kind=raw["op_kind"], contract_hash=raw["contract_hash"],
                implementation_hash=raw["implementation_hash"],
                reviewed_set_digest=new_digest)
            env_path.write_text(json.dumps(raw), encoding="utf-8")

            tampered_env = load_run_envelope("run-1", envelope_dir=d)
            self.assertTrue(tampered_env.is_spendable(),
                            "the tamper is deliberately self-consistent -- is_spendable() "
                            "alone cannot catch it; the independent receipt must")

            store = {}
            write_client = _FieldShapedWriteClient(store)
            op = self._op(["R-1", "R-999"])
            updated, result = run_enveloped_operation(
                tampered_env, op, _receipt(op), write_client,
                read_only_client=_FieldShapedReadOnlyClient(store),
                envelope_dir=d, ledger_dir=d)
            self.assertEqual(result.status, "refused")
            self.assertEqual(result.detail.get("gate"), "run_envelope_consent_receipt")
            self.assertEqual(write_client.writes, [])

    def test_reordering_the_reviewed_set_changes_the_digest_and_the_receipt_refuses(self):
        # compute_reviewed_set_digest is order-sensitive (by design). Reorder
        # the persisted reviewed_set (self-consistently: recompute the digest
        # and consent binding to match the NEW order) -- the independently
        # persisted receipt, still bound to the ORIGINAL order's digest,
        # must refuse the reordered envelope.
        with tempfile.TemporaryDirectory() as d:
            original_reviewed = [_reviewed_entry("R-1"), _reviewed_entry("R-2")]
            self._mint(d, original_reviewed)

            reordered = list(reversed(original_reviewed))
            reordered_digest = compute_reviewed_set_digest(reordered)

            env_path = Path(d) / "run-1.json"
            raw = json.loads(env_path.read_text())
            raw["reviewed_set"] = reordered
            raw["reviewed_set_digest"] = reordered_digest
            raw["consent"]["approval_bound_to"] = reordered_digest
            raw["ledger_window_id"] = derive_ledger_window_id(
                run_id=raw["run_id"], capability_id=raw["capability_id"],
                op_kind=raw["op_kind"], contract_hash=raw["contract_hash"],
                implementation_hash=raw["implementation_hash"],
                reviewed_set_digest=reordered_digest)
            env_path.write_text(json.dumps(raw), encoding="utf-8")

            reordered_env = load_run_envelope("run-1", envelope_dir=d)
            self.assertTrue(reordered_env.is_spendable())
            ok, reason = verify_run_consent_receipt(reordered_env, receipt_dir=d)
            self.assertFalse(ok)
            self.assertIn("reviewed_set_digest", reason)


if __name__ == "__main__":
    unittest.main()
