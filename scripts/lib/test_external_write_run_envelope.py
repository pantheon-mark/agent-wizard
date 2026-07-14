"""Tests for the RunEnvelope primitive (Task 4, A1 — v0.12.0 Slice 1, design
§0) + the envelope-driven run path that threads the read-only client and
records per-unit verification into ``tranches[]``.

Invariants under test:
  * I1 SOLE-MINTER — an approved RunEnvelope with spendable budget may be
    minted ONLY by ``mint_run_envelope`` (the consent-ceremony entry point),
    receipt-bound. A caller-chosen / fabricated ``run_id`` yields an EMPTY
    envelope (0 budget, no frozen reviewed set) -> fail-closed. A fabricated
    on-disk envelope (wrong reviewed_set_digest, tampered ledger_window_id, or
    absent operator consent) is NOT spendable. ``ledger_window_id`` is DERIVED
    from verified identity, never a trusted stored field.
  * Fail-closed load — absent / unreadable / malformed envelope file loads as
    the empty envelope (0 budget), never as a permissive one.
  * Run-path wiring (closes the Task 3 carry-forward at broker.py:128 — a run
    path that calls run_operation WITHOUT a read-only client): the enveloped
    run threads ``read_only_client`` into ``run_operation`` and records the
    per-unit verification result into ``RunEnvelope.tranches[]``, keeping
    credential isolation intact.

Anti-overfit (Global Constraint #3): exercised on ≥2 divergent op_kinds — a
field/spreadsheet op AND the gmail.message.trash op_kind.

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
from external_write.read_facade import (  # noqa: E402
    ReadFacade, register_read_facade, unregister_read_facade,
)
from external_write.run_envelope import (  # noqa: E402
    Ceiling,
    Consent,
    RunEnvelope,
    REVIEWED_SET_SCHEMA_V1,
    REVIEWED_SET_SCHEMA_V2,
    compute_reviewed_set_digest,
    derive_ledger_window_id,
    load_run_envelope,
    mint_run_envelope,
    render_review_artifact,
    run_enveloped_operation,
)


def _receipt(op):
    digest = hashlib.sha256(op.canonical_repr().encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=900)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    return {"approved_operation_digest": digest, "expires_at": expires_at}


def _reviewed_set(n=3, prefix="row"):
    return [
        {"unit_id": f"{prefix}{i}", "prestate_digest": f"d{i}",
         "intended_mutation": {"value": "Complete"},
         "category": "status_change", "protected_status": False}
        for i in range(n)
    ]


# A reversible field op_kind so mint computes a real (reversible-tier) ceiling.
FIELD_OP = "_env_field_probe"
GMAIL_OP = "gmail.message.trash"


def _register_field_contract():
    contracts_mod.OPERATION_CONTRACTS[FIELD_OP] = OperationContract(
        op_kind=FIELD_OP, writes=("Status",), produces=(), dependency_set=(),
        verifier_set=(), introduces_persistent_binding=False,
        risk_class="reversible_external", read_only_scope="fixture.readonly")


def _unregister_field_contract():
    contracts_mod.OPERATION_CONTRACTS.pop(FIELD_OP, None)


# ===========================================================================
# Minting + serialization round-trip
# ===========================================================================

class TestMintAndLoad(unittest.TestCase):

    def setUp(self):
        _register_field_contract()

    def tearDown(self):
        _unregister_field_contract()

    def _mint(self, d, run_id="run-1", population=15000, op_kind=FIELD_OP):
        return mint_run_envelope(
            run_id=run_id, capability_id="cap:test", op_kind=op_kind,
            contract_hash="ch-abc", implementation_hash="ih-abc",
            reviewed_set=_reviewed_set(3), population_count=population,
            stratification_summary={"status_change": 3},
            operator_approval_verbatim="yes, apply these three changes",
            consent_sentence_shown="Apply 3 reversible status changes.",
            envelope_dir=d)

    def test_mint_produces_spendable_envelope_with_budget(self):
        with tempfile.TemporaryDirectory() as d:
            res = self._mint(d)
            self.assertTrue(res.accepted, res.reason)
            env = res.envelope
            self.assertTrue(env.is_spendable())
            self.assertGreater(env.remaining_budget(), 0)
            # reversible tier, population 15000 -> clamped to the reversible cap.
            self.assertEqual(env.ceiling.recovery_tier, "reversible")
            self.assertEqual(env.remaining_budget(), env.ceiling.granted_this_approval)

    def test_load_round_trips_a_minted_spendable_envelope(self):
        with tempfile.TemporaryDirectory() as d:
            minted = self._mint(d).envelope
            loaded = load_run_envelope("run-1", envelope_dir=d)
            self.assertTrue(loaded.is_spendable())
            self.assertEqual(loaded.remaining_budget(), minted.remaining_budget())
            self.assertEqual(loaded.reviewed_set_digest, minted.reviewed_set_digest)
            self.assertEqual(loaded.ledger_window_id, minted.ledger_window_id)

    def test_reviewed_set_digest_matches_the_frozen_set(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d).envelope
            self.assertEqual(
                env.reviewed_set_digest,
                compute_reviewed_set_digest(_reviewed_set(3)))

    def test_ledger_window_id_is_derived_from_identity(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d).envelope
            expected = derive_ledger_window_id(
                run_id="run-1", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch-abc", implementation_hash="ih-abc",
                reviewed_set_digest=env.reviewed_set_digest)
            self.assertEqual(env.ledger_window_id, expected)

    def test_gmail_op_kind_mints_reversible_tier_envelope(self):
        # Divergent op_kind #2: gmail.message.trash (sensitive_data -> reversible tier).
        with tempfile.TemporaryDirectory() as d:
            res = self._mint(d, run_id="run-gmail", op_kind=GMAIL_OP)
            self.assertTrue(res.accepted, res.reason)
            self.assertEqual(res.envelope.ceiling.recovery_tier, "reversible")
            self.assertTrue(res.envelope.is_spendable())


# ===========================================================================
# I1 — sole-minter + fail-closed
# ===========================================================================

class TestI1SoleMinter(unittest.TestCase):

    def setUp(self):
        _register_field_contract()

    def tearDown(self):
        _unregister_field_contract()

    def test_fabricated_run_id_never_minted_loads_empty_zero_budget(self):
        with tempfile.TemporaryDirectory() as d:
            env = load_run_envelope("a_run_id_the_loop_made_up", envelope_dir=d)
            self.assertFalse(env.is_spendable())
            self.assertEqual(env.remaining_budget(), 0)
            self.assertEqual(len(env.reviewed_set), 0)

    def test_mint_refuses_empty_operator_confirmation(self):
        # Honest capture: an empty operator "yes" is not consent; nothing minted.
        with tempfile.TemporaryDirectory() as d:
            res = mint_run_envelope(
                run_id="run-x", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=_reviewed_set(3), population_count=100,
                stratification_summary={}, operator_approval_verbatim="   ",
                consent_sentence_shown="Apply 3 changes.", envelope_dir=d)
            self.assertFalse(res.accepted)
            # And nothing spendable was written to disk.
            self.assertFalse(load_run_envelope("run-x", envelope_dir=d).is_spendable())

    def test_mint_refuses_empty_reviewed_set(self):
        with tempfile.TemporaryDirectory() as d:
            res = mint_run_envelope(
                run_id="run-y", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=[], population_count=100,
                stratification_summary={}, operator_approval_verbatim="yes",
                consent_sentence_shown="x", envelope_dir=d)
            self.assertFalse(res.accepted)

    def test_hand_fabricated_envelope_with_fake_budget_is_not_spendable(self):
        # A loop writes its OWN envelope file with a huge budget but a
        # reviewed_set_digest that does not match its reviewed_set -> the
        # consistency check refuses it (0 budget). It cannot fabricate a fresh
        # approved window to escape an exhausted budget.
        with tempfile.TemporaryDirectory() as d:
            forged = {
                "schema": "run_envelope-v1",
                "run_id": "forged", "capability_id": "cap:test",
                "op_kind": FIELD_OP, "contract_hash": "ch", "implementation_hash": "ih",
                "reviewed_set": _reviewed_set(3),
                "reviewed_set_digest": "deadbeef_not_the_real_digest",
                "population_count": 3,
                "stratification_summary": {},
                "ceiling": {"granted_this_approval": 999999, "remaining_budget": 999999,
                            "absolute_cap": 600, "recovery_tier": "reversible"},
                "consent": {"operator_approval_verbatim": "yes",
                            "consent_sentence_shown": "x", "approved_at": "now",
                            "approval_bound_to": "deadbeef_not_the_real_digest"},
                "evidence_policy": {},
                "ledger_window_id": "whatever",
                "tranches": [],
            }
            (Path(d) / "forged.json").write_text(json.dumps(forged), encoding="utf-8")
            env = load_run_envelope("forged", envelope_dir=d)
            self.assertFalse(env.is_spendable())
            self.assertEqual(env.remaining_budget(), 0)

    def test_tampered_ledger_window_id_is_not_spendable_and_property_is_derived(self):
        with tempfile.TemporaryDirectory() as d:
            mint_run_envelope(
                run_id="run-t", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=_reviewed_set(3), population_count=100,
                stratification_summary={}, operator_approval_verbatim="yes",
                consent_sentence_shown="Apply 3 changes.", envelope_dir=d)
            p = Path(d) / "run-t.json"
            raw = json.loads(p.read_text())
            raw["ledger_window_id"] = "tampered_window_id"
            p.write_text(json.dumps(raw), encoding="utf-8")
            env = load_run_envelope("run-t", envelope_dir=d)
            self.assertFalse(env.is_spendable(),
                             "a tampered ledger_window_id must void spendability")
            # The property is DERIVED, never the trusted stored field.
            self.assertNotEqual(env.ledger_window_id, "tampered_window_id")
            self.assertEqual(env.ledger_window_id, derive_ledger_window_id(
                run_id="run-t", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set_digest=env.reviewed_set_digest))

    def test_malformed_envelope_file_loads_empty(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "junk.json").write_text("{not valid json", encoding="utf-8")
            env = load_run_envelope("junk", envelope_dir=d)
            self.assertFalse(env.is_spendable())
            self.assertEqual(env.remaining_budget(), 0)

    def test_empty_stored_ledger_window_id_is_not_spendable(self):
        # C1: an EMPTY stored ledger_window_id can no longer short-circuit the
        # tamper check to "spendable" — it fails closed even when every other
        # field is internally consistent (a minted envelope always persists the
        # derived id, so a blank one is a hand-built envelope skipping the ceremony).
        reviewed = _reviewed_set(3)
        digest = compute_reviewed_set_digest(reviewed)
        env = RunEnvelope(
            run_id="r", capability_id="c", op_kind=FIELD_OP,
            contract_hash="ch", implementation_hash="ih",
            reviewed_set=tuple(reviewed), reviewed_set_digest=digest,
            population_count=3, stratification_summary={},
            ceiling=Ceiling(granted_this_approval=10, remaining_budget=10,
                            absolute_cap=600, recovery_tier="reversible"),
            consent=Consent(operator_approval_verbatim="yes", consent_sentence_shown="x",
                            approved_at="now", approval_bound_to=digest),
            evidence_policy={}, tranches=(), stored_ledger_window_id="")
        self.assertFalse(env.is_spendable(),
                         "an empty stored ledger_window_id must fail the tamper check (C1)")


# ===========================================================================
# Run path — threads read_only_client + records verification into tranches
# ===========================================================================

class _FieldWriteClient:
    def __init__(self, store):
        self._store = store
        self.write_calls = []

    def write_row(self, row_id, value):
        self.write_calls.append((row_id, value))
        self._store[row_id] = {"value": value}


class _FieldReadOnlyClient:
    def __init__(self, store):
        self._store = store
        self.read_calls = []

    def read_row(self, row_id):
        self.read_calls.append(row_id)
        return dict(self._store.get(row_id, {}))


class _FieldReadFacade(ReadFacade):
    read_methods = ("read_row",)

    def read_row(self, row_id):
        return self._read("read_row", row_id)


class _FieldAdapter:
    def plan(self, params):
        params = params or {}
        return [EffectUnit(unit_id=r["row_id"], target_ref=r)
                for r in params.get("rows", [])]

    def apply_one(self, raw_client, unit):
        raw_client.write_row(unit.unit_id, unit.target_ref["intended_value"])

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        observed = observer.read_row(unit.unit_id)
        return {"value": observed.get("value"),
                "intended_value": unit.target_ref["intended_value"]}

    def verify_apply_landed(self, evidence):
        return evidence.poststate.get("value") == evidence.poststate.get("intended_value")


class TestEnvelopedRunPathRecordsTranches(unittest.TestCase):

    OP_KIND = "_env_run_field_probe"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND, writes=("Status",), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="reversible_external",  # ungated: isolates the run-path wiring
            read_only_scope="fixture.readonly")
        register_read_facade(self.OP_KIND, _FieldReadFacade)
        register_adapter(self.OP_KIND, _FieldAdapter())

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)
        unregister_read_facade(self.OP_KIND)

    def _op(self):
        return Operation(surface="fixture_surface", op_kind=self.OP_KIND,
                         batch_id="e2e-1",
                         params={"rows": [{"row_id": "row1", "intended_value": "Complete"}]})

    def _mint(self, d):
        return mint_run_envelope(
            run_id="run-e2e", capability_id="cap:test", op_kind=self.OP_KIND,
            contract_hash="ch", implementation_hash="ih",
            reviewed_set=[{"unit_id": "row1", "prestate_digest": "d",
                           "intended_mutation": {"value": "Complete"},
                           "category": "status", "protected_status": False}],
            population_count=50, stratification_summary={},
            operator_approval_verbatim="yes", consent_sentence_shown="Apply 1 change.",
            envelope_dir=d).envelope

    def test_run_path_records_verification_into_a_tranche(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            store = {"row1": {"value": "Open"}}
            write_client = _FieldWriteClient(store)
            read_only_client = _FieldReadOnlyClient(store)
            op = self._op()

            updated, result = run_enveloped_operation(
                env, op, _receipt(op), write_client,
                read_only_client=read_only_client, envelope_dir=d, ledger_dir=d)

            self.assertEqual(result.status, "written")
            # A tranche was appended recording the real-surface verification.
            self.assertEqual(len(updated.tranches), 1)
            tr = updated.tranches[0]
            self.assertIn("row1", tr.applied_unit_ids)
            self.assertEqual(tr.per_unit_result["row1"]["status"], "verified")
            self.assertEqual(tr.verification_status, "verified")
            # Credential isolation preserved: the verification read reached the
            # read-only client, the write reached the write client.
            self.assertEqual(write_client.write_calls, [("row1", "Complete")])
            self.assertEqual(read_only_client.read_calls, ["row1"])
            # The tranche was persisted to disk (reloadable).
            reloaded = load_run_envelope("run-e2e", envelope_dir=d)
            self.assertEqual(len(reloaded.tranches), 1)

    def test_run_path_threads_read_only_client_unverified_without_it(self):
        # Without a read-only client the run still applies, but the tranche is
        # honestly recorded as applied_not_verified (never verified) — proving
        # the read-only client is what the run path threads for verification.
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            store = {"row1": {"value": "Open"}}
            write_client = _FieldWriteClient(store)
            op = self._op()
            updated, result = run_enveloped_operation(
                env, op, _receipt(op), write_client, envelope_dir=d,
                ledger_dir=d)  # no ro client
            self.assertEqual(result.status, "written")
            tr = updated.tranches[0]
            self.assertEqual(tr.per_unit_result["row1"]["status"], "applied_not_verified")
            self.assertEqual(tr.verification_status, "applied_not_verified")

    def test_run_path_refuses_a_non_spendable_envelope(self):
        with tempfile.TemporaryDirectory() as d:
            empty = load_run_envelope("never-minted", envelope_dir=d)
            store = {"row1": {"value": "Open"}}
            op = self._op()
            updated, result = run_enveloped_operation(
                empty, op, _receipt(op), _FieldWriteClient(store),
                read_only_client=_FieldReadOnlyClient(store), envelope_dir=d, ledger_dir=d)
            self.assertEqual(result.status, "refused")
            self.assertEqual(len(updated.tranches), 0)

    def test_run_path_refuses_a_fabricated_in_memory_spendable_envelope(self):
        # C1: a hand-built in-memory envelope that PASSES is_spendable() in memory
        # (every field is caller-computable, INCLUDING the correctly-derived stored
        # ledger_window_id) but was NEVER minted to disk under this run_id must be
        # REFUSED by the disk-authoritative run path — a fresh fabricated run_id
        # has no persisted budget, so generated loop code cannot escape an
        # exhausted cap by fabricating a fresh approved window.
        with tempfile.TemporaryDirectory() as d:
            reviewed = [{"unit_id": "row1", "prestate_digest": "d",
                         "intended_mutation": {"value": "Complete"},
                         "category": "status", "protected_status": False}]
            digest = compute_reviewed_set_digest(reviewed)
            window = derive_ledger_window_id(
                run_id="fresh-fabricated-run-id", capability_id="cap:test",
                op_kind=self.OP_KIND, contract_hash="ch", implementation_hash="ih",
                reviewed_set_digest=digest)
            fabricated = RunEnvelope(
                run_id="fresh-fabricated-run-id", capability_id="cap:test",
                op_kind=self.OP_KIND, contract_hash="ch", implementation_hash="ih",
                reviewed_set=tuple(reviewed), reviewed_set_digest=digest,
                population_count=3, stratification_summary={},
                ceiling=Ceiling(granted_this_approval=999999, remaining_budget=999999,
                                absolute_cap=600, recovery_tier="reversible"),
                consent=Consent(operator_approval_verbatim="yes", consent_sentence_shown="x",
                                approved_at="now", approval_bound_to=digest),
                evidence_policy={}, tranches=(), stored_ledger_window_id=window)
            # The threat is real: in memory this LOOKS fully spendable.
            self.assertTrue(fabricated.is_spendable(),
                            "the fabricated envelope must look spendable in memory — "
                            "that is exactly the C1 threat the disk-authoritative path closes")
            store = {"row1": {"value": "Open"}}
            write_client = _FieldWriteClient(store)
            op = self._op()
            updated, result = run_enveloped_operation(
                fabricated, op, _receipt(op), write_client,
                read_only_client=_FieldReadOnlyClient(store), envelope_dir=d, ledger_dir=d)
            self.assertEqual(result.status, "refused",
                             "a fabricated in-memory envelope with a fresh run_id must be "
                             "refused — the run path reloads authority from disk (C1)")
            self.assertEqual(len(updated.tranches), 0)
            self.assertEqual(write_client.write_calls, [],
                             "nothing may be written for a fabricated envelope")
            self.assertEqual(store["row1"]["value"], "Open")


# ===========================================================================
# I-3 — aggregate Knob B ceiling enforced in the run path, composing with the
# per-op cap, applying even to a REVERSIBLE op the write gate does not cap
# ===========================================================================

class _MultiRowFieldAdapter:
    """Plans one effect unit per row in params['rows'] — so a single op applies
    n_units = len(rows), exercising the aggregate ceiling across chunks."""

    def plan(self, params):
        params = params or {}
        return [EffectUnit(unit_id=r["row_id"], target_ref=r)
                for r in params.get("rows", [])]

    def apply_one(self, raw_client, unit):
        raw_client.write_row(unit.unit_id, unit.target_ref["intended_value"])

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        observed = observer.read_row(unit.unit_id)
        return {"value": observed.get("value"),
                "intended_value": unit.target_ref["intended_value"]}

    def verify_apply_landed(self, evidence):
        return evidence.poststate.get("value") == evidence.poststate.get("intended_value")


class TestI3AggregateCeilingComposesWithPerOpCap(unittest.TestCase):

    OP_KIND = "_env_agg_field_probe"

    def setUp(self):
        # reversible_external -> the write gate does NOT cap it (not gated), so the
        # aggregate ceiling is the ONLY blast-radius bound: proves reversible bulk
        # is bounded by the envelope even though the per-op gate lets it through.
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND, writes=("Status",), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="reversible_external", read_only_scope="fixture.readonly")
        register_read_facade(self.OP_KIND, _FieldReadFacade)
        register_adapter(self.OP_KIND, _MultiRowFieldAdapter())

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)
        unregister_read_facade(self.OP_KIND)

    def _op_n_rows(self, n):
        rows = [{"row_id": f"row{i}", "intended_value": "Complete"} for i in range(n)]
        return Operation(surface="fixture_surface", op_kind=self.OP_KIND,
                         batch_id="agg-1", params={"rows": rows})

    def _mint(self, d):
        # population 50, reversible -> Knob B ceiling clamps to the floor (25).
        # The frozen reviewed_set carries every row id run_chunk() will ever
        # plan (row0..row9, applied repeatedly across chunks) — apply-by-id
        # (Task 5) requires every planned unit to be a member of this set, so
        # this fixture must name them all, not just one, to keep exercising
        # the aggregate-ceiling behavior this test targets.
        reviewed = [{"unit_id": f"row{i}", "prestate_digest": "d",
                    "intended_mutation": {"value": "Complete"},
                    "category": "status", "protected_status": False}
                   for i in range(10)]
        return mint_run_envelope(
            run_id="run-agg", capability_id="cap:test", op_kind=self.OP_KIND,
            contract_hash="ch", implementation_hash="ih",
            reviewed_set=reviewed,
            population_count=50, stratification_summary={},
            operator_approval_verbatim="yes", consent_sentence_shown="Apply changes.",
            envelope_dir=d).envelope

    def test_aggregate_ceiling_refuses_bulk_that_each_chunk_passes_per_op(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            self.assertEqual(env.ceiling.granted_this_approval, 25)
            store = {f"row{i}": {"value": "Open"} for i in range(10)}

            def run_chunk():
                # A fresh op + fresh clients each chunk (the F-39-shaped driver);
                # the aggregate persists on disk across chunks via the same window.
                op = self._op_n_rows(10)
                return run_enveloped_operation(
                    env, op, _receipt(op), _FieldWriteClient(store),
                    read_only_client=_FieldReadOnlyClient(store),
                    envelope_dir=d, ledger_dir=d)

            _, r1 = run_chunk()   # aggregate 0 -> 10
            _, r2 = run_chunk()   # aggregate 10 -> 20
            _, r3 = run_chunk()   # aggregate 20 + 10 = 30 > 25 -> refused
            self.assertEqual(r1.status, "written")
            self.assertEqual(r2.status, "written")
            self.assertEqual(r3.status, "refused",
                             "the aggregate approval ceiling must refuse the chunk that "
                             "would exceed granted_this_approval, even though the "
                             "reversible per-op gate passes every chunk (I-3)")
            self.assertEqual(r3.detail.get("gate"), "run_envelope_aggregate_ceiling")


# ===========================================================================
# Task 8 (A3 / F-48) — reviewed_set-v2 schema + consent-artifact binding
# (AC-T8a, AC-T8b)
# ===========================================================================

def _v2_reviewed_set(n=3, prefix="row", category="status_change", protected=False):
    """A reviewed_set-v2-shaped set: every entry carries the v2-only marker
    fields (reason_shown, source_snapshot_digest) alongside a unique unit_id."""
    return [
        {"unit_id": f"{prefix}{i}", "reason_shown": f"Change {prefix}{i} to Complete",
         "source_snapshot_digest": f"snap-{prefix}{i}", "category": category,
         "protected_status": protected}
        for i in range(n)
    ]


class TestReviewedSetV2AndArtifactBinding(unittest.TestCase):
    """AC-T8a (consent-artifact binding) + AC-T8b (reviewed_set-v2 versioning
    + anti-downgrade). See run_envelope.py's "reviewed_set schema versioning"
    section for the full rationale."""

    def setUp(self):
        _register_field_contract()

    def tearDown(self):
        _unregister_field_contract()

    def _mint_v2(self, d, reviewed_set, *, artifact=None, run_id="run-v2",
                op_kind=FIELD_OP, schema=REVIEWED_SET_SCHEMA_V2):
        if artifact is None:
            artifact, _ = render_review_artifact(reviewed_set)
        return mint_run_envelope(
            run_id=run_id, capability_id="cap:test", op_kind=op_kind,
            contract_hash="ch-abc", implementation_hash="ih-abc",
            reviewed_set=reviewed_set, population_count=len(reviewed_set),
            stratification_summary={}, operator_approval_verbatim="yes, apply these",
            consent_sentence_shown="Apply the reviewed set.", envelope_dir=d,
            reviewed_set_schema=schema, operator_approved_review_artifact=artifact)

    # --- AC-T8b: versioning ---------------------------------------------

    def test_legacy_v1_caller_without_v2_fields_still_accepted(self):
        # A genuinely legacy, non-triage v1 caller (existing shape: unit_id +
        # prestate_digest, no reason_shown / source_snapshot_digest at all)
        # must keep minting exactly as before -- no schema param at all.
        with tempfile.TemporaryDirectory() as d:
            res = mint_run_envelope(
                run_id="run-legacy", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=_reviewed_set(3), population_count=100,
                stratification_summary={}, operator_approval_verbatim="yes",
                consent_sentence_shown="Apply 3 changes.", envelope_dir=d)
            self.assertTrue(res.accepted, res.reason)
            self.assertEqual(res.envelope.reviewed_set_schema, REVIEWED_SET_SCHEMA_V1)

    def test_v2_shaped_set_declared_v1_refuses_anti_downgrade(self):
        # A triage-driven (v2-shaped) reviewed_set declared v1 (or the schema
        # param simply omitted) must REFUSE -- it may not downgrade to skip
        # the v2 checks.
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(3)
            res = mint_run_envelope(
                run_id="run-downgrade", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=reviewed, population_count=100,
                stratification_summary={}, operator_approval_verbatim="yes",
                consent_sentence_shown="Apply 3 changes.", envelope_dir=d)
            self.assertFalse(res.accepted)
            self.assertIn("downgrade", res.reason)

            # Explicitly declaring v1 over v2-shaped entries refuses the same way.
            res2 = mint_run_envelope(
                run_id="run-downgrade2", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=reviewed, population_count=100,
                stratification_summary={}, operator_approval_verbatim="yes",
                consent_sentence_shown="Apply 3 changes.", envelope_dir=d,
                reviewed_set_schema=REVIEWED_SET_SCHEMA_V1)
            self.assertFalse(res2.accepted)
            self.assertIn("downgrade", res2.reason)

    def test_v2_declared_applies_v2_checks_and_mints(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(3)
            res = self._mint_v2(d, reviewed)
            self.assertTrue(res.accepted, res.reason)
            self.assertEqual(res.envelope.reviewed_set_schema, REVIEWED_SET_SCHEMA_V2)
            self.assertTrue(res.envelope.review_artifact_digest)

    def test_v2_duplicate_unit_id_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(2)
            reviewed[1]["unit_id"] = reviewed[0]["unit_id"]  # duplicate id
            res = self._mint_v2(d, reviewed)
            self.assertFalse(res.accepted)
            self.assertIn("duplicate", res.reason)

    def test_v2_missing_reason_shown_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(2)
            reviewed[0]["reason_shown"] = ""
            res = self._mint_v2(d, reviewed)
            self.assertFalse(res.accepted)
            self.assertIn("reason_shown", res.reason)

    def test_v2_missing_source_snapshot_digest_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(2)
            del reviewed[0]["source_snapshot_digest"]
            res = self._mint_v2(d, reviewed)
            self.assertFalse(res.accepted)
            self.assertIn("source_snapshot_digest", res.reason)

    # --- AC-T8a: consent-artifact binding --------------------------------

    def test_render_review_artifact_is_deterministic(self):
        reviewed = _v2_reviewed_set(3)
        a1, d1 = render_review_artifact(reviewed)
        a2, d2 = render_review_artifact(reviewed)
        self.assertEqual(a1, a2)
        self.assertEqual(d1, d2)

    def test_matching_artifact_and_reviewed_set_mints_and_records_both_digests(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(3)
            artifact, digest = render_review_artifact(reviewed)
            res = self._mint_v2(d, reviewed, artifact=artifact)
            self.assertTrue(res.accepted, res.reason)
            self.assertEqual(res.envelope.review_artifact_digest, digest)
            self.assertEqual(res.envelope.reviewed_set_digest,
                             compute_reviewed_set_digest(reviewed))

    def test_mutated_artifact_alone_refuses(self):
        # The reviewed_set is untouched; the text the operator supposedly
        # approved was tampered with independently.
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(3)
            artifact, _ = render_review_artifact(reviewed)
            tampered_artifact = artifact + "\nTAMPERED LINE\n"
            res = self._mint_v2(d, reviewed, artifact=tampered_artifact)
            self.assertFalse(res.accepted)
            self.assertIn("mismatch", res.reason)

    def test_mutated_reviewed_set_alone_refuses(self):
        # The artifact text the operator approved is untouched; the
        # reviewed_set passed to mint was mutated independently (an extra
        # entry snuck in after the operator saw the artifact).
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(3)
            artifact, _ = render_review_artifact(reviewed)
            mutated_reviewed = reviewed + _v2_reviewed_set(1, prefix="sneaked-in-")
            res = self._mint_v2(d, mutated_reviewed, artifact=artifact)
            self.assertFalse(res.accepted)
            self.assertIn("mismatch", res.reason)

    def test_missing_operator_approved_artifact_refuses_for_v2(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(2)
            res = mint_run_envelope(
                run_id="run-noartifact", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=reviewed, population_count=100,
                stratification_summary={}, operator_approval_verbatim="yes",
                consent_sentence_shown="Apply.", envelope_dir=d,
                reviewed_set_schema=REVIEWED_SET_SCHEMA_V2)
            self.assertFalse(res.accepted)
            self.assertIn("operator_approved_review_artifact", res.reason)

    def test_load_round_trips_v2_schema_and_artifact_digest(self):
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(2)
            res = self._mint_v2(d, reviewed)
            loaded = load_run_envelope("run-v2", envelope_dir=d)
            self.assertEqual(loaded.reviewed_set_schema, REVIEWED_SET_SCHEMA_V2)
            self.assertEqual(loaded.review_artifact_digest, res.envelope.review_artifact_digest)
            self.assertTrue(loaded.is_spendable())

    def test_tampered_review_artifact_digest_on_disk_is_not_spendable(self):
        # AC-T8a "verify" half: is_spendable() recomputes the artifact digest
        # from the CURRENT on-disk reviewed_set and refuses a stored
        # review_artifact_digest that no longer matches.
        with tempfile.TemporaryDirectory() as d:
            reviewed = _v2_reviewed_set(2)
            self._mint_v2(d, reviewed, run_id="run-tamper")
            env_path = Path(d) / "run-tamper.json"
            raw = json.loads(env_path.read_text())
            raw["review_artifact_digest"] = "deadbeef_not_the_real_digest"
            env_path.write_text(json.dumps(raw), encoding="utf-8")
            tampered = load_run_envelope("run-tamper", envelope_dir=d)
            self.assertFalse(tampered.is_spendable())


if __name__ == "__main__":
    unittest.main()
