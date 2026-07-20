"""Deterministic regression net for the sanctioned bulk-run path
(``run_sanctioned_bulk``) — proves the trust-core guarantees the underlying
primitives provide individually still hold when exercised together, end to
end, over a temp fixture project via the one enforced entrypoint.

Composed behaviors under test (each a scenario below):

  1. A run id minted by the sanctioned path is write-once: a second call that
     happens to derive the SAME run id (a collision — e.g. a crash-and-retry,
     or a generated loop replaying a prior id) is refused rather than
     clobbering the first run's envelope and consent receipt.
  2. An interrupted run leaves a resumable (non-finalized) envelope under its
     original run id; resuming continues under that SAME id — no second
     envelope is minted, and the tranche sequence continues rather than
     restarting.
  3. The whole run — however many chunks it takes — carries exactly ONE
     operator consent artifact. The per-chunk write-gate receipt is a
     distinct, mechanical, non-consent artifact.
  4. Resuming with a REPLAYED operator confirmation (the exact verbatim and
     timestamp already on record for the paused run) is refused; a
     genuinely fresh confirmation over the same scope proceeds.
  5. The end-of-run recoverability report marks every applied, durably
     manifested unit recoverable, and any unmanifested / fabricated id
     not_recoverable_by_system — counts stay internally consistent.
  6. A run is refused — nothing minted, nothing written — when the operator
     consent timestamp is absent, empty, or whitespace-only. An empty-ish
     "yes" is not an honest record of operator consent.

Together these demonstrate that reusing a run id can no longer destroy a
prior run's recovery record, and that a single operator approval can no
longer be stretched into a per-chunk consent, on the sanctioned path.

Anti-overfit: uses the existing op-kind-agnostic ``FIELD_OP`` fixture from
the sibling test module (never a Gmail/estate-specific op) — real disk
store, real fixture clients, consistent with the rest of this suite. The one
deliberate ``unittest.mock`` use (scenario 1) patches only the run-id
generator, to construct an otherwise-astronomically-unlikely id collision
without touching any of the mint/write logic under test.

Stdlib only; unittest, not pytest.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Single-home: import from wizard/agents/lib/external_write (the canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import Operation  # noqa: E402
from external_write.adapter_registry import register_adapter, unregister_adapter  # noqa: E402
from external_write.read_facade import register_read_facade, unregister_read_facade  # noqa: E402
from external_write.run_envelope import (  # noqa: E402
    RUN_STATE_FINALIZED,
    RECOVERABLE_BY_SYSTEM,
    NOT_RECOVERABLE_BY_SYSTEM,
    load_run_envelope,
    report_run_recoverability,
    run_sanctioned_bulk,
    _op_receipt,
)

# Reuse the sibling test module's existing op-kind-agnostic fixture rather
# than re-deriving it (must be run via `unittest discover` from this
# directory so the flat sibling import resolves — see the repo's existing
# cross-import test modules, e.g. test_external_write_replay_conformance.py).
from test_external_write_run_envelope import (  # noqa: E402
    FIELD_OP,
    _register_field_contract,
    _unregister_field_contract,
    _reviewed_set,
    _FieldWriteClient,
    _FieldReadOnlyClient,
    _FieldReadFacade,
    _FieldAdapter,
)


def _op_builder(chunk_ids, value="Complete"):
    """The op_builder callback: (chunk_unit_ids) -> Operation. Op-kind-agnostic
    — uses the shared FIELD_OP fixture, never a Gmail op."""
    return Operation(
        surface="fixture_surface", op_kind=FIELD_OP, batch_id="iso-1",
        params={"rows": [{"row_id": uid, "intended_value": value} for uid in chunk_ids]})


def _divergent_op_builder(chunk_ids):
    """Yields an id that is NOT a member of any frozen reviewed_set — the
    apply-by-id gate inside the run path refuses this chunk. Used to simulate
    a run getting interrupted mid-flight (e.g. a killed-and-regenerated
    driver that briefly diverges from the reviewed set)."""
    return Operation(
        surface="fixture_surface", op_kind=FIELD_OP, batch_id="iso-1",
        params={"rows": [{"row_id": "not-a-reviewed-row", "intended_value": "Complete"}]})


class _IsolationFixtureMixin:
    """Shared setUp/tearDown + kwargs builder — every scenario below exercises
    ``run_sanctioned_bulk`` over the same op-kind-agnostic fixture, with a
    real on-disk envelope/ledger/receipt store and real fixture clients."""

    def setUp(self):
        _register_field_contract()
        register_read_facade(FIELD_OP, _FieldReadFacade)
        register_adapter(FIELD_OP, _FieldAdapter())

    def tearDown(self):
        _unregister_field_contract()
        unregister_adapter(FIELD_OP)
        unregister_read_facade(FIELD_OP)

    def _fresh_kwargs(self, d, n=6, chunk_size=2, run_label="iso",
                      op_builder=_op_builder, approved_at="2026-07-19T22:45:48Z",
                      operator_approval_verbatim="yes, apply these"):
        # ledger_dir is a SEPARATE subdirectory from envelope_dir so a test's
        # glob("*.json") over the envelope directory sees only the envelope
        # (+ consent-receipt) files, never the persistent ledger's own file.
        return dict(
            op_builder=op_builder, run_label=run_label, capability_id="cap:iso-test",
            op_kind=FIELD_OP, contract_hash="ch", implementation_hash="ih",
            reviewed_set=_reviewed_set(n), operator_approval_verbatim=operator_approval_verbatim,
            consent_sentence_shown=f"Apply {n} changes.", approved_at=approved_at,
            chunk_size=chunk_size, envelope_dir=d,
            ledger_dir=os.path.join(d, "ledger"), receipt_dir=d)

    def _store(self, n):
        return {f"row{i}": {"value": "Open"} for i in range(n)}


# ===========================================================================
# Scenario 1 — write-once: a run id collision never clobbers a prior run
# ===========================================================================

class TestSanctionedBulkIsWriteOnce(_IsolationFixtureMixin, unittest.TestCase):

    def test_second_call_reusing_the_same_run_id_is_refused_without_clobbering(self):
        with tempfile.TemporaryDirectory() as d:
            fixed_id = "iso-collision-fixed-id"
            store = self._store(6)

            with mock.patch("external_write.run_envelope.new_bulk_run_id",
                             return_value=fixed_id):
                first = run_sanctioned_bulk(
                    **self._fresh_kwargs(d, n=6, chunk_size=6),
                    client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
                self.assertTrue(first.completed, first.refusal_reason)
                self.assertEqual(first.run_id, fixed_id)

                env_path = Path(d) / f"{fixed_id}.json"
                receipt_path = Path(d) / f"{fixed_id}.consent_receipt.json"
                self.assertTrue(env_path.exists())
                self.assertTrue(receipt_path.exists())
                env_bytes_before = env_path.read_bytes()
                receipt_bytes_before = receipt_path.read_bytes()

                # A second, otherwise-independent fresh call that happens to
                # derive the identical run id — the collision this scenario
                # constructs on purpose (a genuine uuid collision cannot be
                # provoked; patching only the id-generator simulates it
                # without touching any mint/write logic under test).
                second = run_sanctioned_bulk(
                    **self._fresh_kwargs(d, n=6, chunk_size=6),
                    client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))

            self.assertTrue(second.refused)
            self.assertFalse(second.completed)
            self.assertFalse(second.finalized)
            self.assertIn("already exists", (second.refusal_reason or ""))
            self.assertEqual(second.run_id, fixed_id)

            # The first run's envelope + consent receipt are UNTOUCHED on disk.
            self.assertEqual(env_path.read_bytes(), env_bytes_before)
            self.assertEqual(receipt_path.read_bytes(), receipt_bytes_before)


# ===========================================================================
# Scenario 2 — resume loads the existing envelope under the SAME run id;
# it never re-mints, and the tranche sequence never restarts
# ===========================================================================

class TestSanctionedBulkResumeLoadsNeverRemints(_IsolationFixtureMixin, unittest.TestCase):

    def test_resume_continues_under_the_same_run_id_without_restarting_tranches(self):
        with tempfile.TemporaryDirectory() as d:
            n = 4
            store = self._store(n)
            calls = {"n": 0}

            def flaky_builder(chunk_ids):
                # The SECOND chunk this process attempts diverges from the
                # frozen reviewed set (as a killed-and-regenerated loop
                # might) — the first chunk's tranche lands durably, but the
                # run stops without finalizing.
                calls["n"] += 1
                if calls["n"] == 2:
                    return _divergent_op_builder(chunk_ids)
                return _op_builder(chunk_ids)

            interrupted = run_sanctioned_bulk(
                **self._fresh_kwargs(d, n=n, chunk_size=2, run_label="iso-resume",
                                     op_builder=flaky_builder),
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(interrupted.refused)
            self.assertFalse(interrupted.finalized)
            run_id = interrupted.run_id
            self.assertEqual(set(interrupted.applied_unit_ids), {"row0", "row1"})

            env_after_interrupt = load_run_envelope(run_id, envelope_dir=d)
            tranche_count_before = len(env_after_interrupt.tranches)
            self.assertEqual(tranche_count_before, 1)  # only the first chunk landed
            self.assertNotEqual(env_after_interrupt.run_state, RUN_STATE_FINALIZED)

            envelope_files = lambda: {  # noqa: E731
                p.name for p in Path(d).glob("*.json")
                if not p.name.endswith(".consent_receipt.json")}
            self.assertEqual(envelope_files(), {f"{run_id}.json"})

            resumed = run_sanctioned_bulk(
                op_builder=_op_builder, resume_run_id=run_id, chunk_size=2,
                fresh_operator_approval_verbatim="yes, continue for real",
                fresh_approved_at="2026-07-19T23:10:00Z", now_iso="2026-07-19T23:10:00Z",
                envelope_dir=d, ledger_dir=os.path.join(d, "ledger"), receipt_dir=d,
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))

            self.assertTrue(resumed.completed, resumed.refusal_reason)
            self.assertEqual(resumed.run_id, run_id)          # SAME id — never re-derived
            self.assertEqual(set(resumed.applied_unit_ids), {"row2", "row3"})

            # No second envelope file was minted for the resume.
            self.assertEqual(envelope_files(), {f"{run_id}.json"})

            # The tranche sequence CONTINUED (one more tranche appended)
            # rather than restarting at index 0; the first tranche's content
            # is unchanged.
            final_env = load_run_envelope(run_id, envelope_dir=d)
            self.assertEqual(len(final_env.tranches), tranche_count_before + 1)
            self.assertEqual(final_env.tranches[0].applied_unit_ids,
                             env_after_interrupt.tranches[0].applied_unit_ids)


# ===========================================================================
# Scenario 3 — exactly one consent for the whole (multi-chunk) run
# ===========================================================================

class TestSanctionedBulkHasExactlyOneConsent(_IsolationFixtureMixin, unittest.TestCase):

    def test_one_consent_receipt_for_a_multi_chunk_run_and_no_per_chunk_consent(self):
        with tempfile.TemporaryDirectory() as d:
            n = 6
            store = self._store(n)
            summary = run_sanctioned_bulk(
                **self._fresh_kwargs(d, n=n, chunk_size=2, run_label="iso-consent"),
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(summary.completed, summary.refusal_reason)

            env = load_run_envelope(summary.run_id, envelope_dir=d)
            self.assertEqual(len(env.tranches), 3)  # 6 rows / chunk_size 2 -> 3 chunks

            receipt_files = list(Path(d).glob("*.consent_receipt.json"))
            self.assertEqual(len(receipt_files), 1,
                             "exactly one operator consent for the whole multi-chunk run")

            # The per-chunk write-gate receipt is a distinct, mechanical,
            # non-consent artifact — it never carries an operator confirmation.
            for chunk_ids in (("row0", "row1"), ("row2", "row3"), ("row4", "row5")):
                op = _op_builder(chunk_ids)
                receipt = _op_receipt(op)
                self.assertEqual(set(receipt.keys()), {"approved_operation_digest", "expires_at"})
                self.assertNotIn("operator_confirmation", receipt)
                self.assertNotIn("approved_at", receipt)
                self.assertEqual(receipt["approved_operation_digest"], op.digest())


# ===========================================================================
# Scenario 4 — resume requires a genuinely FRESH consent; a replayed
# confirmation is refused
# ===========================================================================

class TestSanctionedBulkResumeRequiresFreshConsent(_IsolationFixtureMixin, unittest.TestCase):

    def _interrupt(self, d, run_label="iso-freshconsent"):
        n = 4
        store = self._store(n)
        original_verbatim = "yes apply these"
        original_approved_at = "2026-07-19T22:45:48Z"
        calls = {"n": 0}

        def flaky_builder(chunk_ids):
            calls["n"] += 1
            if calls["n"] == 2:
                return _divergent_op_builder(chunk_ids)
            return _op_builder(chunk_ids)

        summary = run_sanctioned_bulk(
            **self._fresh_kwargs(d, n=n, chunk_size=2, run_label=run_label,
                                 op_builder=flaky_builder,
                                 operator_approval_verbatim=original_verbatim,
                                 approved_at=original_approved_at),
            client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
        self.assertTrue(summary.refused)
        self.assertFalse(summary.finalized)
        return summary.run_id, store, original_verbatim, original_approved_at

    def test_replayed_confirmation_refuses_resume(self):
        with tempfile.TemporaryDirectory() as d:
            run_id, store, verbatim, approved_at = self._interrupt(d)
            resumed = run_sanctioned_bulk(
                op_builder=_op_builder, resume_run_id=run_id, chunk_size=2,
                fresh_operator_approval_verbatim=verbatim,      # REPLAYED, identical
                fresh_approved_at=approved_at,                  # REPLAYED, identical
                now_iso="2026-07-19T23:00:00Z", envelope_dir=d,
                ledger_dir=os.path.join(d, "ledger"), receipt_dir=d,
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(resumed.refused)
            self.assertFalse(resumed.completed)
            reason = (resumed.refusal_reason or "").lower()
            self.assertTrue(
                any(k in reason for k in ("fresh", "reused", "replay")),
                f"expected a freshness/replay refusal reason, got: {reason!r}")

    def test_genuinely_fresh_confirmation_over_the_same_scope_proceeds(self):
        with tempfile.TemporaryDirectory() as d:
            run_id, store, _verbatim, _approved_at = self._interrupt(d)
            resumed = run_sanctioned_bulk(
                op_builder=_op_builder, resume_run_id=run_id, chunk_size=2,
                fresh_operator_approval_verbatim="yes, continue for real",  # NEW verbatim
                fresh_approved_at="2026-07-19T23:00:00Z",                  # NEW timestamp
                now_iso="2026-07-19T23:00:05Z", envelope_dir=d,
                ledger_dir=os.path.join(d, "ledger"), receipt_dir=d,
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertFalse(resumed.refused, resumed.refusal_reason)
            self.assertTrue(resumed.completed)
            self.assertEqual(set(resumed.applied_unit_ids), {"row2", "row3"})


# ===========================================================================
# Scenario 5 — honest recoverability: applied+manifested units are
# recoverable, an unmanifested/ghost id is not_recoverable_by_system
# ===========================================================================

class TestSanctionedBulkHonestRecoverability(_IsolationFixtureMixin, unittest.TestCase):

    def test_applied_units_recoverable_ghost_unit_not_recoverable_counts_consistent(self):
        with tempfile.TemporaryDirectory() as d:
            n = 4
            store = self._store(n)
            summary = run_sanctioned_bulk(
                **self._fresh_kwargs(d, n=n, chunk_size=2, run_label="iso-recoverability"),
                client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))
            self.assertTrue(summary.completed, summary.refusal_reason)

            ghost_id = "ghost-never-applied"
            candidate_ids = list(summary.applied_unit_ids) + [ghost_id]
            report = report_run_recoverability(
                summary.run_id, candidate_unit_ids=candidate_ids, envelope_dir=d)

            for uid in summary.applied_unit_ids:
                self.assertEqual(report["per_id"][uid], RECOVERABLE_BY_SYSTEM)
            self.assertEqual(report["per_id"][ghost_id], NOT_RECOVERABLE_BY_SYSTEM)

            counts = report["counts"]
            self.assertEqual(
                counts["recoverable_by_system"] + counts["not_recoverable_by_system"],
                len(candidate_ids))
            self.assertEqual(counts["recoverable_by_system"], len(summary.applied_unit_ids))
            self.assertEqual(counts["not_recoverable_by_system"], 1)

            # The BulkRunSummary the caller actually receives already carries
            # an honest recoverability claim — never absent.
            self.assertTrue(summary.recoverability)
            self.assertEqual(summary.recoverability["run_state"], RUN_STATE_FINALIZED)


# ===========================================================================
# Scenario 6 — consent honesty: an absent/empty/whitespace-only operator
# consent timestamp refuses the mint outright; nothing is written
# ===========================================================================

class TestSanctionedBulkConsentHonesty(_IsolationFixtureMixin, unittest.TestCase):

    def test_absent_empty_and_whitespace_only_approved_at_all_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            for label, bad_approved_at in (
                ("absent", None), ("empty", ""), ("whitespace_only", "   "),
            ):
                with self.subTest(approved_at=label):
                    files_before = set(Path(d).glob("**/*"))
                    kwargs = self._fresh_kwargs(
                        d, n=3, chunk_size=3, run_label=f"iso-honesty-{label}")
                    kwargs["approved_at"] = bad_approved_at
                    summary = run_sanctioned_bulk(**kwargs)
                    self.assertTrue(summary.refused)
                    self.assertFalse(summary.completed)
                    self.assertIn("approved_at", (summary.refusal_reason or "").lower())
                    # Nothing minted or written for any of the three
                    # empty-ish inputs.
                    files_after = set(Path(d).glob("**/*"))
                    self.assertEqual(files_before, files_after)


if __name__ == "__main__":
    unittest.main()
