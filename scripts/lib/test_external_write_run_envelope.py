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
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.operations import Operation, EffectUnit, Result  # noqa: E402
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
    Tranche,
    REVIEWED_SET_SCHEMA_V1,
    REVIEWED_SET_SCHEMA_V2,
    RUN_STATE_PENDING,
    RUN_STATE_EXECUTING,
    RUN_STATE_FINALIZED,
    RECOVERABLE_BY_SYSTEM,
    NOT_RECOVERABLE_BY_SYSTEM,
    ResumeAuthorization,
    append_tranche,
    authorize_resume,
    compute_reviewed_set_digest,
    derive_ledger_window_id,
    finalize_run,
    load_run_consent_receipt,
    load_run_envelope,
    mint_run_envelope,
    render_review_artifact,
    report_run_recoverability,
    resume_run_envelope,
    run_enveloped_operation,
    # D6a — the sanctioned bulk-run helper (F-79/F-80).
    BulkRunSummary,
    new_bulk_run_id,
    run_sanctioned_bulk,
    _op_receipt,
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
            approved_at="2026-07-19T22:45:48Z", envelope_dir=d)

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

    # -- D2: WAL run-state + load-existing resume (F-79/F-84 substrate) -----

    def test_mint_writes_pending_run_state(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d).envelope
            self.assertEqual(env.run_state, RUN_STATE_PENDING)
            # persisted + reloadable
            self.assertEqual(load_run_envelope("run-1", envelope_dir=d).run_state,
                             RUN_STATE_PENDING)

    def test_append_tranche_advances_to_executing(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d).envelope
            updated = append_tranche(
                env, Tranche(applied_unit_ids=("row0",), per_unit_result={},
                             verification_status="applied_not_verified"),
                envelope_dir=d)
            self.assertEqual(updated.run_state, RUN_STATE_EXECUTING)
            self.assertEqual(load_run_envelope("run-1", envelope_dir=d).run_state,
                             RUN_STATE_EXECUTING)

    def test_finalize_run_sets_finalized_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            self._mint(d)
            f1 = finalize_run("run-1", envelope_dir=d)
            self.assertEqual(f1.run_state, RUN_STATE_FINALIZED)
            f2 = finalize_run("run-1", envelope_dir=d)  # idempotent
            self.assertEqual(f2.run_state, RUN_STATE_FINALIZED)

    def test_finalized_envelope_is_not_spendable(self):
        # Fix 1 (D2 review): the WAL is one-way PENDING_RUN->EXECUTING->
        # FINALIZED -- a further run_enveloped_operation/append_tranche must
        # never write after the run's consent is closed. is_spendable() must
        # inspect run_state directly, not just budget/consent fields.
        with tempfile.TemporaryDirectory() as d:
            self._mint(d)
            finalize_run("run-1", envelope_dir=d)
            env = load_run_envelope("run-1", envelope_dir=d)
            self.assertEqual(env.run_state, RUN_STATE_FINALIZED)
            self.assertFalse(
                env.is_spendable(),
                "a FINALIZED run must not be spendable -- no writes after a "
                "consent-closed run")

    def test_append_tranche_on_finalized_run_does_not_revert_state(self):
        # Fix 1 defense-in-depth: append_tranche must not silently revert a
        # FINALIZED run back to EXECUTING, even if called with a stale
        # in-memory envelope captured before finalize_run.
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d).envelope
            finalize_run("run-1", envelope_dir=d)
            result = append_tranche(
                env, Tranche(applied_unit_ids=("row0",), per_unit_result={},
                             verification_status="applied_not_verified"),
                envelope_dir=d)
            self.assertEqual(
                result.run_state, RUN_STATE_FINALIZED,
                "append_tranche must not revert a FINALIZED run back to EXECUTING")
            reloaded = load_run_envelope("run-1", envelope_dir=d)
            self.assertEqual(reloaded.run_state, RUN_STATE_FINALIZED)
            self.assertEqual(
                len(reloaded.tranches), 0,
                "no tranche may be appended to a finalized run")

    def test_finalize_after_append_tranche_is_idempotent(self):
        # Fix 4: the realistic idempotency case -- EXECUTING -> FINALIZED ->
        # FINALIZED, after at least one real append_tranche (not just the
        # PENDING -> FINALIZED -> FINALIZED case already covered above).
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d).envelope
            updated = append_tranche(
                env, Tranche(applied_unit_ids=("row0",), per_unit_result={},
                             verification_status="applied_not_verified"),
                envelope_dir=d)
            self.assertEqual(updated.run_state, RUN_STATE_EXECUTING)
            f1 = finalize_run("run-1", envelope_dir=d)
            self.assertEqual(f1.run_state, RUN_STATE_FINALIZED)
            self.assertEqual(len(f1.tranches), 1)
            f2 = finalize_run("run-1", envelope_dir=d)  # idempotent
            self.assertEqual(f2.run_state, RUN_STATE_FINALIZED)
            self.assertEqual(len(f2.tranches), 1)

    def test_resume_loads_existing_and_reports_already_applied(self):
        # A killed-mid-run envelope resumes by LOADING the same run_id (never
        # re-minting a colliding id, which D1 refuses) and reports which
        # unit_ids were already applied so the caller does not re-apply them.
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d).envelope
            append_tranche(
                env, Tranche(applied_unit_ids=("row0", "row1"), per_unit_result={},
                             verification_status="applied_not_verified"),
                envelope_dir=d)
            resumed, already = resume_run_envelope("run-1", envelope_dir=d)
            self.assertEqual(resumed.run_id, "run-1")
            self.assertEqual(resumed.run_state, RUN_STATE_EXECUTING)
            self.assertEqual(already, ("row0", "row1"))
            # resume did NOT create a second envelope / re-mint
            self.assertEqual(len([p for p in os.listdir(d) if p.endswith(".json")
                                  and "consent_receipt" not in p]), 1)


# ===========================================================================
# Fix 2/3 (D2 review) — tranche-aware run_state backfill for a pre-D2
# on-disk envelope, and fail-safe validation of a corrupt run_state value.
# ===========================================================================

class TestRunStateBackfillFromDisk(unittest.TestCase):

    def _write_old_shape(self, d, run_id, *, tranches, has_run_state_key=False,
                         run_state_value=None):
        raw = {
            "schema": "run_envelope-v1",
            "run_id": run_id, "capability_id": "cap:test", "op_kind": "whatever",
            "contract_hash": "ch", "implementation_hash": "ih",
            "reviewed_set": _reviewed_set(1), "reviewed_set_digest": "x",
            "population_count": 1, "stratification_summary": {},
            "ceiling": None, "consent": None, "evidence_policy": {},
            "ledger_window_id": "", "tranches": tranches,
        }
        if has_run_state_key:
            raw["run_state"] = run_state_value
        (Path(d) / f"{run_id}.json").write_text(json.dumps(raw), encoding="utf-8")

    def _tranche_dict(self):
        return {"applied_unit_ids": ["row0"], "per_unit_result": {},
                "verification_status": "applied_not_verified",
                "restore_verified": None}

    def test_old_shape_with_tranches_and_no_run_state_key_loads_executing(self):
        # F-79 killed-mid-run shape: a genuine pre-D2 envelope with recorded
        # tranches but no run_state key must load as EXECUTING, not PENDING
        # -- it contradicts resume_run_envelope's non-empty already-applied
        # output otherwise.
        with tempfile.TemporaryDirectory() as d:
            self._write_old_shape(d, "pre-d2-midrun",
                                  tranches=[self._tranche_dict()])
            env = load_run_envelope("pre-d2-midrun", envelope_dir=d)
            self.assertEqual(env.run_state, RUN_STATE_EXECUTING)

    def test_old_shape_without_tranches_and_no_run_state_key_loads_pending(self):
        with tempfile.TemporaryDirectory() as d:
            self._write_old_shape(d, "pre-d2-fresh", tranches=[])
            env = load_run_envelope("pre-d2-fresh", envelope_dir=d)
            self.assertEqual(env.run_state, RUN_STATE_PENDING)

    def test_corrupt_run_state_value_falls_back_to_tranche_derived_default(self):
        # Fix 3: _RUN_STATES validation -- a garbage on-disk run_state value
        # must never be propagated verbatim; fall back fail-safe to the
        # Fix-2 tranche-derived default.
        with tempfile.TemporaryDirectory() as d:
            self._write_old_shape(d, "bogus-state", tranches=[self._tranche_dict()],
                                  has_run_state_key=True, run_state_value="bogus")
            env = load_run_envelope("bogus-state", envelope_dir=d)
            self.assertEqual(env.run_state, RUN_STATE_EXECUTING)
            self.assertNotEqual(env.run_state, "bogus")


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

    def test_mint_refuses_to_overwrite_existing_run_id(self):
        # F-79: a run_id is write-once. A reused run_id (e.g. a crash-and-retry
        # that reuses the same id, or a generated loop replaying a prior id)
        # must never clobber a prior run's persisted envelope/receipt — that
        # would destroy the recovery record for a possibly in-flight run.
        with tempfile.TemporaryDirectory() as d:
            kw = dict(
                run_id="inbox-bulk-1", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=_reviewed_set(3), population_count=100,
                stratification_summary={}, operator_approval_verbatim="yes",
                consent_sentence_shown="Apply 3 changes.",
                approved_at="2026-07-19T22:45:48Z", envelope_dir=d)
            first = mint_run_envelope(**kw)
            self.assertTrue(first.accepted, first.reason)
            second = mint_run_envelope(**kw)  # same run_id, second invocation
            self.assertFalse(second.accepted)
            self.assertIn("already exists", (second.reason or ""))
            # the first run's envelope + receipt are UNTOUCHED
            self.assertTrue(os.path.exists(os.path.join(d, "inbox-bulk-1.json")))
            self.assertTrue(os.path.exists(
                os.path.join(d, "inbox-bulk-1.consent_receipt.json")))

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
                consent_sentence_shown="Apply 3 changes.",
                approved_at="2026-07-19T22:45:48Z", envelope_dir=d)
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
# D3 (F-80) — run-level consent bound to the operator utterance time, never
# a machine-minted default
# ===========================================================================

class TestRunLevelConsentUtteranceTime(unittest.TestCase):

    def setUp(self):
        _register_field_contract()

    def tearDown(self):
        _unregister_field_contract()

    def test_mint_refuses_without_operator_utterance_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            res = mint_run_envelope(
                run_id="run-u", capability_id="c", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=_reviewed_set(3), population_count=100,
                stratification_summary={}, operator_approval_verbatim="yes go ahead",
                consent_sentence_shown="Apply 3 changes.",
                approved_at=None, envelope_dir=d)          # NO utterance time
            self.assertFalse(res.accepted)
            self.assertIn("approved_at", (res.reason or "").lower())

    def test_consent_records_the_operator_utterance_time_not_mint_time(self):
        with tempfile.TemporaryDirectory() as d:
            utterance_ts = "2026-07-19T22:45:48Z"
            res = mint_run_envelope(
                run_id="run-u2", capability_id="c", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=_reviewed_set(3), population_count=100,
                stratification_summary={}, operator_approval_verbatim="yes go ahead",
                consent_sentence_shown="Apply 3 changes.",
                approved_at=utterance_ts, envelope_dir=d)
            self.assertTrue(res.accepted, res.reason)
            self.assertEqual(res.envelope.consent.approved_at, utterance_ts)
            self.assertNotEqual(res.envelope.minted_at, "")        # machine time captured separately
            self.assertNotEqual(res.envelope.minted_at, utterance_ts)
            # receipt carries the SAME single utterance time, plus a distinct minted_at
            rcpt = load_run_consent_receipt("run-u2", receipt_dir=d)
            self.assertEqual(rcpt["approved_at"], utterance_ts)
            self.assertIn("minted_at", rcpt)


class TestResumeRequiresFreshConsent(unittest.TestCase):
    """Task D4 (F-84): a resume is a FRESH operator decision at the process
    boundary. ``authorize_resume`` refuses fail-closed on a background resume
    with no fresh consent, a replayed verbatim/timestamp, a re-scope (digest
    or contract/implementation hash changed), or an expired consent — and
    authorizes only a genuinely fresh operator consent event over the
    (possibly-narrowed) remaining work."""

    def setUp(self):
        _register_field_contract()

    def tearDown(self):
        _unregister_field_contract()

    def _mint_run(self, d, run_id="run-r"):
        return mint_run_envelope(
            run_id=run_id, capability_id="c", op_kind=FIELD_OP,
            contract_hash="ch", implementation_hash="ih",
            reviewed_set=_reviewed_set(3), population_count=100,
            stratification_summary={}, operator_approval_verbatim="yes go ahead",
            consent_sentence_shown="Apply 3 changes.",
            approved_at="2026-07-19T22:45:48Z", envelope_dir=d).envelope

    def test_background_resume_without_fresh_consent_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint_run(d)
            auth = authorize_resume(
                "run-r", fresh_operator_approval_verbatim="",   # no fresh operator decision
                fresh_approved_at="", current_reviewed_set_digest=env.reviewed_set_digest,
                current_contract_hash="ch", current_implementation_hash="ih",
                now_iso="2026-07-19T22:50:00Z", envelope_dir=d)
            self.assertFalse(auth.authorized)
            self.assertIn("fresh", (auth.reason or "").lower())

    def test_replayed_verbatim_timestamp_refuses(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint_run(d)
            auth = authorize_resume(
                "run-r", fresh_operator_approval_verbatim="yes go ahead",
                fresh_approved_at="2026-07-19T22:45:48Z",       # SAME as stored = replay
                current_reviewed_set_digest=env.reviewed_set_digest,
                current_contract_hash="ch", current_implementation_hash="ih",
                now_iso="2026-07-19T22:50:00Z", envelope_dir=d)
            self.assertFalse(auth.authorized)

    def test_rescope_refuses_even_with_fresh_consent(self):
        with tempfile.TemporaryDirectory() as d:
            self._mint_run(d)
            auth = authorize_resume(
                "run-r", fresh_operator_approval_verbatim="yes again",
                fresh_approved_at="2026-07-19T22:50:00Z",
                current_reviewed_set_digest="a-different-digest",   # re-scoped
                current_contract_hash="ch", current_implementation_hash="ih",
                now_iso="2026-07-19T22:50:05Z", envelope_dir=d)
            self.assertFalse(auth.authorized)

    def test_fresh_consent_same_scope_authorizes(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint_run(d)
            auth = authorize_resume(
                "run-r", fresh_operator_approval_verbatim="yes, continue",
                fresh_approved_at="2026-07-19T22:50:00Z",
                current_reviewed_set_digest=env.reviewed_set_digest,
                current_contract_hash="ch", current_implementation_hash="ih",
                now_iso="2026-07-19T22:50:05Z", envelope_dir=d)
            self.assertTrue(auth.authorized, auth.reason)
            self.assertIsNotNone(auth.envelope)

    def test_replayed_verbatim_with_fresh_timestamp_refuses(self):
        # D4 review Fix 1 (Critical): a caller holding the paused envelope
        # replays the STORED verbatim but supplies a genuinely fresh clock
        # timestamp. Before the fix this was authorized (only approved_at was
        # compared) -- reopening F-84. Must refuse: the verbatim alone
        # matching the paused run's stored verbatim is a replayed consent
        # event, even with a new timestamp.
        with tempfile.TemporaryDirectory() as d:
            env = self._mint_run(d)
            auth = authorize_resume(
                "run-r", fresh_operator_approval_verbatim="yes go ahead",  # STORED verbatim replayed
                fresh_approved_at="2026-07-19T22:50:00Z",                 # fresh timestamp
                current_reviewed_set_digest=env.reviewed_set_digest,
                current_contract_hash="ch", current_implementation_hash="ih",
                now_iso="2026-07-19T22:50:05Z", envelope_dir=d)
            self.assertFalse(auth.authorized)
            self.assertIn("reused", (auth.reason or "").lower())

    def test_finalized_run_returns_finalized_specific_message(self):
        # D4 review Fix 2 (Important): a genuinely FINALIZED run must get the
        # specific "already finished and is closed" message, not the generic
        # "cannot be found or is not in a resumable state" message that
        # is_spendable()'s FINALIZED short-circuit would otherwise always
        # produce first.
        with tempfile.TemporaryDirectory() as d:
            env = self._mint_run(d)
            finalize_run("run-r", envelope_dir=d)
            auth = authorize_resume(
                "run-r", fresh_operator_approval_verbatim="yes, continue",
                fresh_approved_at="2026-07-19T22:50:00Z",
                current_reviewed_set_digest=env.reviewed_set_digest,
                current_contract_hash="ch", current_implementation_hash="ih",
                now_iso="2026-07-19T22:50:05Z", envelope_dir=d)
            self.assertFalse(auth.authorized)
            self.assertIn("already finished", (auth.reason or "").lower())

    def test_absent_run_still_returns_cannot_be_found_message(self):
        # Guard against a naive reorder of the FINALIZED check: an absent /
        # never-minted run_id loads as the fail-closed EMPTY envelope, which
        # also defaults run_state to FINALIZED internally (_empty_envelope) as
        # its own not-resumable signal. That case must NOT be mistaken for a
        # genuinely finalized real run -- it must keep the "cannot be found"
        # message, not "already finished".
        with tempfile.TemporaryDirectory() as d:
            auth = authorize_resume(
                "run-never-existed", fresh_operator_approval_verbatim="yes, continue",
                fresh_approved_at="2026-07-19T22:50:00Z",
                current_reviewed_set_digest="whatever",
                current_contract_hash="ch", current_implementation_hash="ih",
                now_iso="2026-07-19T22:50:05Z", envelope_dir=d)
            self.assertFalse(auth.authorized)
            self.assertIn("cannot be found", (auth.reason or "").lower())


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
            approved_at="2026-07-19T22:45:48Z", envelope_dir=d).envelope

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
# D5 — honest recoverability reporting from durable records (F-81): every
# queried id gets an explicit claim; an id with no durable applied-tranche
# entry is reported not_recoverable_by_system, never sampled-around.
# ===========================================================================

class TestHonestRecoverabilityReporting(unittest.TestCase):

    OP_KIND = "_env_recoverability_field_probe"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND, writes=("Status",), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="reversible_external",  # reversible tier -> recoverable-eligible
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
            approved_at="2026-07-19T22:45:48Z", envelope_dir=d).envelope

    def test_unmanifested_id_reported_not_recoverable(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            store = {"row1": {"value": "Open"}}
            op = self._op()
            run_enveloped_operation(env, op, _receipt(op), _FieldWriteClient(store),
                                    read_only_client=_FieldReadOnlyClient(store),
                                    envelope_dir=d, ledger_dir=d)
            report = report_run_recoverability(
                "run-e2e", candidate_unit_ids=["row1", "ghost-never-applied"],
                envelope_dir=d)
            self.assertEqual(report["per_id"]["row1"], RECOVERABLE_BY_SYSTEM)
            self.assertEqual(report["per_id"]["ghost-never-applied"],
                             NOT_RECOVERABLE_BY_SYSTEM)
            self.assertEqual(report["counts"]["recoverable_by_system"], 1)
            self.assertEqual(report["counts"]["not_recoverable_by_system"], 1)

    def test_absent_envelope_reports_all_not_recoverable(self):
        with tempfile.TemporaryDirectory() as d:
            report = report_run_recoverability(
                "never-minted", candidate_unit_ids=["a", "b"], envelope_dir=d)
            self.assertEqual(report["per_id"]["a"], NOT_RECOVERABLE_BY_SYSTEM)
            self.assertEqual(report["per_id"]["b"], NOT_RECOVERABLE_BY_SYSTEM)
            self.assertEqual(report["counts"]["recoverable_by_system"], 0)

    def test_recoverability_does_not_gate_on_verification_status(self):
        # Controller decision Q2: recoverability and verification are separate
        # axes. Without a read-only client the tranche is honestly recorded
        # applied_not_verified (never verified) -- but the unit is still
        # recoverable_by_system (Gmail-Trash-style: prestate is the restore
        # basis regardless of whether the write was independently verified).
        # Gating recoverability on verified would report zero recoverable for
        # the estate's real evidence, which is exactly the F-81 failure mode.
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            store = {"row1": {"value": "Open"}}
            op = self._op()
            updated, result = run_enveloped_operation(
                env, op, _receipt(op), _FieldWriteClient(store),
                envelope_dir=d, ledger_dir=d)  # no read-only client
            self.assertEqual(result.status, "written")
            self.assertEqual(updated.tranches[0].verification_status,
                             "applied_not_verified")
            report = report_run_recoverability(
                "run-e2e", candidate_unit_ids=["row1"], envelope_dir=d)
            self.assertEqual(report["per_id"]["row1"], RECOVERABLE_BY_SYSTEM)

    def test_irreversible_op_reports_not_recoverable_even_when_applied(self):
        # Controller decision Q1(c): recoverability requires the op be
        # reversible (ceiling.recovery_tier) -- an applied, reviewed id under
        # an IRREVERSIBLE-tier run must never be reported recoverable_by_system.
        irr_kind = "_env_recoverability_irreversible_probe"
        contracts_mod.OPERATION_CONTRACTS[irr_kind] = OperationContract(
            op_kind=irr_kind, writes=("Status",), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="irreversible_external",
            read_only_scope="fixture.readonly")
        register_read_facade(irr_kind, _FieldReadFacade)
        register_adapter(irr_kind, _FieldAdapter())
        try:
            with tempfile.TemporaryDirectory() as d:
                mint = mint_run_envelope(
                    run_id="run-irr", capability_id="cap:test", op_kind=irr_kind,
                    contract_hash="ch", implementation_hash="ih",
                    reviewed_set=[{"unit_id": "row1", "prestate_digest": "d",
                                   "intended_mutation": {"value": "Complete"},
                                   "category": "status", "protected_status": False}],
                    population_count=50, stratification_summary={},
                    operator_approval_verbatim="yes", consent_sentence_shown="Apply 1 change.",
                    approved_at="2026-07-19T22:45:48Z", envelope_dir=d)
                self.assertTrue(mint.accepted, mint.reason)
                self.assertEqual(mint.envelope.ceiling.recovery_tier, "irreversible")
                store = {"row1": {"value": "Open"}}
                op = Operation(surface="fixture_surface", op_kind=irr_kind,
                               batch_id="e2e-1",
                               params={"rows": [{"row_id": "row1", "intended_value": "Complete"}]})
                run_enveloped_operation(
                    mint.envelope, op, _receipt(op), _FieldWriteClient(store),
                    read_only_client=_FieldReadOnlyClient(store),
                    envelope_dir=d, ledger_dir=d)
                report = report_run_recoverability(
                    "run-irr", candidate_unit_ids=["row1"], envelope_dir=d)
                self.assertEqual(report["per_id"]["row1"], NOT_RECOVERABLE_BY_SYSTEM)
                self.assertEqual(report["counts"]["recoverable_by_system"], 0)
        finally:
            contracts_mod.OPERATION_CONTRACTS.pop(irr_kind, None)
            unregister_adapter(irr_kind)
            unregister_read_facade(irr_kind)

    def test_finalized_run_still_reports_honest_recoverability(self):
        # Recoverability must not gate on the WAL lifecycle state -- a
        # FINALIZED run's durable records are still reportable (this is
        # exactly when an operator would ask "what can still be undone?").
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            store = {"row1": {"value": "Open"}}
            op = self._op()
            run_enveloped_operation(env, op, _receipt(op), _FieldWriteClient(store),
                                    read_only_client=_FieldReadOnlyClient(store),
                                    envelope_dir=d, ledger_dir=d)
            finalize_run("run-e2e", envelope_dir=d)
            report = report_run_recoverability(
                "run-e2e", candidate_unit_ids=["row1"], envelope_dir=d)
            self.assertEqual(report["run_state"], RUN_STATE_FINALIZED)
            self.assertEqual(report["per_id"]["row1"], RECOVERABLE_BY_SYSTEM)

    def test_default_candidate_set_is_reviewed_union_applied(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            store = {"row1": {"value": "Open"}}
            op = self._op()
            run_enveloped_operation(env, op, _receipt(op), _FieldWriteClient(store),
                                    read_only_client=_FieldReadOnlyClient(store),
                                    envelope_dir=d, ledger_dir=d)
            report = report_run_recoverability("run-e2e", envelope_dir=d)
            self.assertEqual(report["per_id"], {"row1": RECOVERABLE_BY_SYSTEM})
            self.assertEqual(report["counts"]["reviewed"], 1)
            self.assertEqual(report["counts"]["applied"], 1)

    def test_partial_candidate_set_keeps_count_families_internally_consistent(self):
        # D5 review Fix 1 (Important): recoverable_by_system/
        # not_recoverable_by_system (and verified/applied_not_verified) must
        # be counted over the SAME query set as reviewed/applied -- never
        # over the whole envelope. Before the fix, `reviewed`/`applied` were
        # whole-envelope counts while the recoverability/verification counts
        # were query-scoped, so a partial `candidate_unit_ids` query produced
        # an internally-inconsistent counts object (e.g. reviewed=5 alongside
        # recoverable=1/not_recoverable=1 for a 2-id query) -- misleading for
        # a feature whose whole purpose is trustworthy reporting.
        with tempfile.TemporaryDirectory() as d:
            reviewed = [
                {"unit_id": f"row{i}", "prestate_digest": f"d{i}",
                 "intended_mutation": {"value": "Complete"},
                 "category": "status", "protected_status": False}
                for i in range(5)
            ]
            mint = mint_run_envelope(
                run_id="run-partial", capability_id="cap:test", op_kind=self.OP_KIND,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=reviewed, population_count=50, stratification_summary={},
                operator_approval_verbatim="yes", consent_sentence_shown="Apply changes.",
                approved_at="2026-07-19T22:45:48Z", envelope_dir=d)
            self.assertTrue(mint.accepted, mint.reason)
            env = mint.envelope
            store = {f"row{i}": {"value": "Open"} for i in range(5)}
            # Apply only 3 of the 5 reviewed rows (row0, row1, row2).
            op = Operation(
                surface="fixture_surface", op_kind=self.OP_KIND, batch_id="e2e-1",
                params={"rows": [{"row_id": f"row{i}", "intended_value": "Complete"}
                                 for i in range(3)]})
            run_enveloped_operation(env, op, _receipt(op), _FieldWriteClient(store),
                                    read_only_client=_FieldReadOnlyClient(store),
                                    envelope_dir=d, ledger_dir=d)

            # Query a PARTIAL candidate set of 2 ids: row0 (reviewed + applied)
            # and row3 (reviewed but never applied) -- out of a whole envelope
            # that reviewed 5 and applied 3.
            report = report_run_recoverability(
                "run-partial", candidate_unit_ids=["row0", "row3"], envelope_dir=d)
            counts = report["counts"]
            # Invariant: recoverable + not_recoverable == the number of ids
            # actually classified in THIS query, regardless of the larger
            # whole-envelope sets.
            self.assertEqual(
                counts["recoverable_by_system"] + counts["not_recoverable_by_system"], 2)
            self.assertEqual(counts["recoverable_by_system"], 1)      # row0 only
            self.assertEqual(counts["not_recoverable_by_system"], 1)  # row3 never applied
            # reviewed/applied are now scoped to the SAME query set as the
            # recoverable/not_recoverable family above.
            self.assertEqual(counts["reviewed"], 2)   # row0 + row3 both reviewed
            self.assertEqual(counts["applied"], 1)    # only row0 was applied
            # Whole-envelope figures remain available as run-level context,
            # under visibly-distinct *_total names so no consumer can assume
            # cross-family summation.
            self.assertEqual(counts["reviewed_total"], 5)
            self.assertEqual(counts["applied_total"], 3)

    def test_tampered_envelope_reviewed_set_digest_reports_not_recoverable(self):
        # D5 review Fix 2 (Minor, cheap): _envelope_is_durable must treat a
        # mismatched reviewed_set_digest as non-durable, the same way
        # is_spendable() does -- a run whose on-disk envelope was tampered (or
        # corrupted) must never report its applied ids recoverable, even
        # though a tranche recorded a real apply.
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            store = {"row1": {"value": "Open"}}
            op = self._op()
            run_enveloped_operation(env, op, _receipt(op), _FieldWriteClient(store),
                                    read_only_client=_FieldReadOnlyClient(store),
                                    envelope_dir=d, ledger_dir=d)
            env_path = Path(d) / "run-e2e.json"
            raw = json.loads(env_path.read_text())
            raw["reviewed_set_digest"] = "deadbeef_not_the_real_digest"
            env_path.write_text(json.dumps(raw), encoding="utf-8")

            report = report_run_recoverability(
                "run-e2e", candidate_unit_ids=["row1"], envelope_dir=d)
            self.assertEqual(report["per_id"]["row1"], NOT_RECOVERABLE_BY_SYSTEM)
            self.assertEqual(report["counts"]["recoverable_by_system"], 0)
            self.assertEqual(report["counts"]["not_recoverable_by_system"], 1)


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
            approved_at="2026-07-19T22:45:48Z", envelope_dir=d).envelope

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
            consent_sentence_shown="Apply the reviewed set.",
            approved_at="2026-07-19T22:45:48Z", envelope_dir=d,
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
                consent_sentence_shown="Apply 3 changes.",
                approved_at="2026-07-19T22:45:48Z", envelope_dir=d)
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
                consent_sentence_shown="Apply.",
                approved_at="2026-07-19T22:45:48Z", envelope_dir=d,
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


# ===========================================================================
# Task D6a (Cut 1.1 Cluster D — F-79/F-80) — run_sanctioned_bulk: the helper
# OWNS the mint so the sanctioned bulk path exposes NO per-batch mint: one
# call = one mint = one run_id = one run-level consent = many tranches.
# ===========================================================================

def _bulk_op_builder(chunk_ids, value="Complete"):
    """The op_builder callback: (chunk_unit_ids) -> Operation. Op-kind-agnostic
    per Q3 — uses the existing FIELD_OP fixture, never a Gmail op."""
    return Operation(
        surface="fixture_surface", op_kind=FIELD_OP, batch_id="bulk-1",
        params={"rows": [{"row_id": uid, "intended_value": value} for uid in chunk_ids]})


class TestRunSanctionedBulk(unittest.TestCase):

    def setUp(self):
        _register_field_contract()
        register_read_facade(FIELD_OP, _FieldReadFacade)
        register_adapter(FIELD_OP, _FieldAdapter())

    def tearDown(self):
        _unregister_field_contract()
        unregister_adapter(FIELD_OP)
        unregister_read_facade(FIELD_OP)

    # -- Step 1 -------------------------------------------------------------

    def test_new_bulk_run_id_is_unique_and_label_prefixed(self):
        a = new_bulk_run_id("inbox promos sweep")
        b = new_bulk_run_id("inbox promos sweep")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("inbox_promos_sweep-"))
        self.assertNotIn("/", a)

    # -- Step 2 ---------------------------------------------------------

    def _fresh_kwargs(self, d, n=6, chunk_size=2, run_label="t2",
                      op_builder=_bulk_op_builder, approved_at="2026-07-19T22:45:48Z"):
        # ledger_dir is a SEPARATE subdirectory from envelope_dir so a test's
        # `glob("*.json")` over the envelope directory sees only the envelope
        # (+ consent-receipt) files, never the persistent ledger's own
        # `<window>.ledger.json`.
        return dict(
            op_builder=op_builder, run_label=run_label, capability_id="cap:test",
            op_kind=FIELD_OP, contract_hash="ch", implementation_hash="ih",
            reviewed_set=_reviewed_set(n), operator_approval_verbatim="yes apply these",
            consent_sentence_shown=f"Apply {n}.", approved_at=approved_at,
            chunk_size=chunk_size, envelope_dir=d,
            ledger_dir=os.path.join(d, "ledger"), receipt_dir=d)

    def test_fresh_bulk_mints_once_applies_all_chunks_and_finalizes(self):
        with tempfile.TemporaryDirectory() as d:
            store = {f"row{i}": {"value": "Open"} for i in range(6)}
            summary = run_sanctioned_bulk(
                **self._fresh_kwargs(d, n=6, chunk_size=2),
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(summary.completed, summary.refusal_reason)
            self.assertTrue(summary.finalized)
            self.assertEqual(set(summary.applied_unit_ids), {f"row{i}" for i in range(6)})
            # exactly ONE envelope file on disk (glob minus the consent-receipt file).
            json_files = [p for p in Path(d).glob("*.json")
                         if not p.name.endswith(".consent_receipt.json")]
            self.assertEqual(len(json_files), 1)
            self.assertEqual(json_files[0].stem, summary.run_id)
            env = load_run_envelope(summary.run_id, envelope_dir=d)
            self.assertEqual(env.run_state, RUN_STATE_FINALIZED)
            self.assertEqual(len(env.tranches), 3)   # 6 rows / chunk_size 2

    def test_fresh_bulk_refuses_when_approved_at_absent(self):
        # F-80/D3 guard survives the helper: never default to a machine time.
        with tempfile.TemporaryDirectory() as d:
            kwargs = self._fresh_kwargs(d, n=6, chunk_size=2)
            kwargs["approved_at"] = None
            summary = run_sanctioned_bulk(**kwargs)
            self.assertTrue(summary.refused)
            self.assertIn("operator-utterance", (summary.refusal_reason or "").lower())
            self.assertEqual(list(Path(d).glob("*.json")), [])  # nothing minted

    # -- Step 3 -----------------------------------------------------------

    def test_bulk_run_has_exactly_one_consent_receipt_and_no_per_chunk_consent(self):
        with tempfile.TemporaryDirectory() as d:
            store = {f"row{i}": {"value": "Open"} for i in range(6)}
            summary = run_sanctioned_bulk(
                **self._fresh_kwargs(d, n=6, chunk_size=2),
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(summary.completed, summary.refusal_reason)
            # ONE consent artifact for the whole run -- never a per-chunk consent.
            receipt_files = list(Path(d).glob("*.consent_receipt.json"))
            self.assertEqual(len(receipt_files), 1)

            op = _bulk_op_builder(("row0", "row1"))
            receipt = _op_receipt(op)
            self.assertEqual(set(receipt.keys()), {"approved_operation_digest", "expires_at"})
            self.assertNotIn("operator_confirmation", receipt)
            self.assertEqual(receipt["approved_operation_digest"], op.digest())

    # -- Step 4 -------------------------------------------------------------

    def test_resume_without_fresh_consent_refuses_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            n = 30  # > the Knob B floor (25) -> the aggregate ceiling refuses a later chunk.
            store = {f"row{i}": {"value": "Open"} for i in range(n)}
            summary = run_sanctioned_bulk(
                **self._fresh_kwargs(d, n=n, chunk_size=5),
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(summary.refused)
            self.assertFalse(summary.finalized)
            env_before = load_run_envelope(summary.run_id, envelope_dir=d)
            tranche_count_before = len(env_before.tranches)
            self.assertGreaterEqual(tranche_count_before, 1)

            resumed = run_sanctioned_bulk(
                op_builder=_bulk_op_builder, resume_run_id=summary.run_id, chunk_size=5,
                envelope_dir=d, ledger_dir=os.path.join(d, "ledger"), receipt_dir=d,
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(resumed.refused)
            self.assertIn("fresh", (resumed.refusal_reason or "").lower())
            env_after = load_run_envelope(summary.run_id, envelope_dir=d)
            self.assertEqual(len(env_after.tranches), tranche_count_before)

    def test_resume_with_fresh_consent_skips_applied_and_completes(self):
        with tempfile.TemporaryDirectory() as d:
            store = {f"row{i}": {"value": "Open"} for i in range(4)}
            calls = {"n": 0}

            def flaky_builder(chunk_ids):
                # Simulate a crash-like interruption: the SECOND chunk this
                # process attempts diverges from the frozen reviewed set (as
                # a killed-and-regenerated loop might), so the first chunk's
                # tranche lands durably but the run stops without finalizing.
                calls["n"] += 1
                if calls["n"] == 2:
                    return Operation(
                        surface="fixture_surface", op_kind=FIELD_OP, batch_id="bulk-1",
                        params={"rows": [{"row_id": "not-a-reviewed-row",
                                          "intended_value": "Complete"}]})
                return _bulk_op_builder(chunk_ids)

            first = run_sanctioned_bulk(
                **self._fresh_kwargs(d, n=4, chunk_size=2, run_label="t4b",
                                     op_builder=flaky_builder),
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(first.refused)
            self.assertFalse(first.finalized)
            self.assertEqual(set(first.applied_unit_ids), {"row0", "row1"})

            resumed = run_sanctioned_bulk(
                op_builder=_bulk_op_builder, resume_run_id=first.run_id, chunk_size=2,
                fresh_operator_approval_verbatim="yes, continue for real",
                fresh_approved_at="2026-07-19T23:10:00Z", now_iso="2026-07-19T23:10:00Z",
                envelope_dir=d, ledger_dir=os.path.join(d, "ledger"), receipt_dir=d,
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(resumed.completed, resumed.refusal_reason)
            self.assertIn("row0", resumed.skipped_already_applied)
            self.assertIn("row1", resumed.skipped_already_applied)
            self.assertEqual(set(resumed.applied_unit_ids), {"row2", "row3"})

    # -- Step 5 -------------------------------------------------------------

    def test_chunk_refusal_stops_and_does_not_finalize(self):
        with tempfile.TemporaryDirectory() as d:
            store = {}

            def divergent_builder(chunk_ids):
                return Operation(
                    surface="fixture_surface", op_kind=FIELD_OP, batch_id="bulk-1",
                    params={"rows": [{"row_id": "not-reviewed", "intended_value": "Complete"}]})

            summary = run_sanctioned_bulk(
                **self._fresh_kwargs(d, n=3, chunk_size=3, run_label="t5a",
                                     op_builder=divergent_builder),
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(summary.refused)
            self.assertFalse(summary.finalized)
            self.assertFalse(summary.completed)
            env = load_run_envelope(summary.run_id, envelope_dir=d)
            self.assertNotEqual(env.run_state, RUN_STATE_FINALIZED)
            self.assertTrue(summary.recoverability)

    def test_resume_of_finalized_run_is_idempotent_noop(self):
        with tempfile.TemporaryDirectory() as d:
            store = {f"row{i}": {"value": "Open"} for i in range(3)}
            first = run_sanctioned_bulk(
                **self._fresh_kwargs(d, n=3, chunk_size=3, run_label="t5b"),
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(first.completed, first.refusal_reason)
            self.assertTrue(first.finalized)
            tranche_count = len(load_run_envelope(first.run_id, envelope_dir=d).tranches)

            resumed = run_sanctioned_bulk(
                op_builder=_bulk_op_builder, resume_run_id=first.run_id, chunk_size=3,
                envelope_dir=d, ledger_dir=os.path.join(d, "ledger"), receipt_dir=d,
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(resumed.completed)
            self.assertTrue(resumed.finalized)
            self.assertFalse(resumed.refused)
            self.assertEqual(
                len(load_run_envelope(first.run_id, envelope_dir=d).tranches), tranche_count)
            self.assertTrue(resumed.recoverability)

    # -- D6a review fixes ----------------------------------------------------

    def test_completed_agrees_with_finalized_even_when_finalize_fails(self):
        # Fix 1: `completed` must be DERIVED from the run's ACTUAL finalized
        # state, never hardcoded True on the full-completion path.
        # `finalize_run` genuinely returns a NON-finalized envelope when the
        # loaded envelope turns out non-spendable -- simulate exactly that by
        # patching `finalize_run` to return an EXECUTING (not FINALIZED)
        # envelope, and assert `completed` never disagrees with `finalized`.
        with tempfile.TemporaryDirectory() as d:
            store = {f"row{i}": {"value": "Open"} for i in range(3)}
            kwargs = self._fresh_kwargs(d, n=3, chunk_size=3, run_label="t6a")
            non_finalized = RunEnvelope(
                run_id="placeholder", capability_id="cap:test", op_kind=FIELD_OP,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=(), reviewed_set_digest="", population_count=0,
                stratification_summary={}, ceiling=None, consent=None,
                evidence_policy={}, tranches=(), run_state=RUN_STATE_EXECUTING)
            with mock.patch("external_write.run_envelope.finalize_run",
                             return_value=non_finalized):
                summary = run_sanctioned_bulk(
                    **kwargs, client=_FieldWriteClient(store),
                    read_only_client=_FieldReadOnlyClient(store))
            self.assertFalse(summary.finalized)
            self.assertEqual(summary.completed, summary.finalized)
            self.assertFalse(summary.completed)

    def test_applied_unit_ids_reflect_tranche_ground_truth_not_requested_ids(self):
        # Fix 2: `applied_unit_ids` must be read back from the envelope's
        # DURABLE tranche records (ground truth), never assumed from the
        # requested chunk_ids -- consistent with D5's "durable-records-only"
        # principle. Simulate a `run_enveloped_operation` that reports
        # "written" for the whole chunk but whose durable tranche covers
        # FEWER ids than were requested -- the summary must report the
        # ground-truth id, not the full requested chunk.
        def _partial_landing(env, op, receipt, client, **kw):
            requested_ids = tuple(r["row_id"] for r in op.params["rows"])
            landed_id = requested_ids[0]
            tranche = Tranche(
                applied_unit_ids=(landed_id,),
                per_unit_result={landed_id: {"status": "verified"}},
                verification_status="verified")
            updated = append_tranche(env, tranche, envelope_dir=kw.get("envelope_dir"))
            return updated, Result(status="written", detail={})

        with tempfile.TemporaryDirectory() as d:
            kwargs = self._fresh_kwargs(d, n=2, chunk_size=2, run_label="t6b")
            with mock.patch("external_write.run_envelope.run_enveloped_operation",
                             side_effect=_partial_landing):
                summary = run_sanctioned_bulk(**kwargs)
            self.assertTrue(summary.completed, summary.refusal_reason)
            self.assertEqual(set(summary.applied_unit_ids), {"row0"})


if __name__ == "__main__":
    unittest.main()
