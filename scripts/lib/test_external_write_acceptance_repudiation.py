"""Tests for typed repudiation over the acceptance log, its reducer, and the revocation
transition it drives (``external_write.acceptance_ceremony`` reducer +
``external_write.lifecycle_state.repudiate_acceptance`` + the
``external_write.acceptance_repudiation`` operator entrypoint).

The property under test, stated as the thing that can go wrong: an operator can *accept* a
capability and, until now, could not take it back. A repudiation that merely appended a row to
the log while ``accepted: true`` stayed live would be WORSE than none -- a control that produces
a record and no effect, at the boundary that authorizes real external writes. So the tests here
are written in two halves: the log's reduced answer must change for every reader whose question
is "is this acceptance current", and the descriptor's ``accepted`` flag must actually go False
through the one sanctioned transition that already owns that flip.

ANTI-OVERFIT: every fixture is built at the REAL emitted relative paths inside a fresh
``tempfile.TemporaryDirectory()`` -- never a ``copytree`` of the dev tree -- and at least two
distinct capability_ids are present in every project fixture, so an assertion cannot pass by
accidentally reading the only capability there is.

The dangling-receipt fixture here is SYNTHESIZED, not copied: a structural equivalent of the
shape found in the field (an acceptance record whose ``operator_receipt_ref`` names a path that
does not resolve), with an invented capability id and invented confirmation text. Operator estate
content never enters this public subtree.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import acceptance_ceremony  # noqa: E402
from external_write import acceptance_repudiation  # noqa: E402
from external_write import capability_health  # noqa: E402
from external_write import capability_invariants  # noqa: E402
from external_write import command_manifest  # noqa: E402
from external_write import lifecycle_state  # noqa: E402
from external_write.acceptance_ceremony import (  # noqa: E402
    ACCEPTANCE_RECORD_SCHEMA,
    ACCEPTANCE_STATUS_ABSENT,
    ACCEPTANCE_STATUS_ACTIVE,
    ACCEPTANCE_STATUS_REPUDIATED,
    ACCEPTANCE_STATUS_UNREADABLE,
    REPUDIATION_RECORD_SCHEMA,
    reduce_acceptance_log,
    resolve_operator_receipt_ref,
)

_OP_KIND = "acme.ledger.post"
_PHASE = "phase-3"


# ---------------------------------------------------------------------------
# Fixture builders -- real emitted relpaths, two capabilities, nothing copied.
# ---------------------------------------------------------------------------

def _write_capability(root, cap_id, op_kind):
    d = Path(root) / "agents" / "capabilities"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cap_id}_capability.py").write_text(
        f'OP_KIND = "{op_kind}"\n# capability {cap_id}\n', encoding="utf-8")


def _write_descriptors(root, entries):
    d = Path(root) / "security"
    d.mkdir(parents=True, exist_ok=True)
    (d / "capability_descriptors.json").write_text(
        json.dumps(entries, indent=2), encoding="utf-8")


def _acceptance_record(cap_id, phase_id, *, operator_receipt_ref="security/"
                                                                 "acceptance_receipts/r.json",
                       implementation_hash="a" * 64, op_kind=_OP_KIND):
    return {
        "schema": ACCEPTANCE_RECORD_SCHEMA,
        "capability_id": cap_id,
        "phase_id": phase_id,
        "risk_class": "irreversible_external",
        "op_kind": op_kind,
        "copy_run_proof_ref": "agents/handoffs/p.json",
        "operator_receipt_ref": operator_receipt_ref,
        "contract_hash": "0" * 64,
        "implementation_hash": implementation_hash,
        "capability_module_hash": "b" * 64,
        "operator_confirmation": "yes, switch it on for real",
        "receipt_accepted_at": "2026-01-01T00:00:00Z",
    }


def _append(log_path, record):
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _two_capability_project(tmp, *, accepted=True, phase_id=_PHASE):
    """A project with TWO real capabilities, the first accepted and carrying one acceptance
    record, the second accepted and deliberately untouched by every assertion below."""
    root = Path(tmp)
    _write_capability(root, "acme_ledger_poster", _OP_KIND)
    _write_capability(root, "acme_report_reader", "acme.report.read")
    _write_descriptors(root, [
        {"id": "acme_ledger_poster", "accepted": accepted, "phase_id": phase_id},
        {"id": "acme_report_reader", "accepted": True, "phase_id": phase_id},
    ])
    return root


def _log_path(root):
    return Path(root) / lifecycle_state.ACCEPTANCE_LOG_REL


def _descriptors(root):
    return json.loads(
        (Path(root) / lifecycle_state.DESCRIPTOR_SET_REL).read_text(encoding="utf-8"))


def _entry(root, cap_id):
    return next(e for e in _descriptors(root) if e["id"] == cap_id)


def _queue(root):
    p = Path(root) / lifecycle_state.MIGRATION_QUEUE_REL
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


# ---------------------------------------------------------------------------
# 1. The reducer
# ---------------------------------------------------------------------------

class AcceptanceLogReducerTests(unittest.TestCase):
    """``reduce_acceptance_log`` is the ONE thing that answers "is this acceptance current".
    Every reader whose question is that routes through it; nothing re-derives it."""

    def test_absent_log_reduces_to_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            reduced = reduce_acceptance_log(
                str(Path(tmp) / "nope.jsonl"), ("acme_ledger_poster",), _PHASE)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_ABSENT)
            self.assertIsNone(reduced.record)
            self.assertIsNone(reduced.repudiation)

    def test_one_acceptance_record_reduces_to_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            _append(log, _acceptance_record("acme_ledger_poster", _PHASE))
            _append(log, _acceptance_record("acme_report_reader", _PHASE))
            reduced = reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_ACTIVE)
            self.assertEqual(reduced.record["capability_id"], "acme_ledger_poster")

    def test_a_later_repudiation_takes_the_acceptance_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            _append(log, _acceptance_record("acme_ledger_poster", _PHASE))
            _append(log, {
                "schema": REPUDIATION_RECORD_SCHEMA,
                "capability_id": "acme_ledger_poster",
                "phase_id": _PHASE,
                "repudiated_at": "2026-02-02T00:00:00Z",
                "operator_confirmation": "no, take that approval back",
            })
            reduced = reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_REPUDIATED)
            self.assertIsNone(
                reduced.record,
                "a repudiated acceptance must not hand its record back -- a caller that "
                "reads the record reads the hashes that say 'still current'")
            self.assertEqual(reduced.repudiation["operator_confirmation"],
                             "no, take that approval back")

    def test_an_acceptance_after_a_repudiation_is_active_again(self):
        """Order is what decides, not presence. The operator who took an approval back and
        then went through the whole trial + acceptance again is approved again."""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            _append(log, _acceptance_record("acme_ledger_poster", _PHASE))
            _append(log, {
                "schema": REPUDIATION_RECORD_SCHEMA,
                "capability_id": "acme_ledger_poster", "phase_id": _PHASE,
                "repudiated_at": "2026-02-02T00:00:00Z",
                "operator_confirmation": "no, take that approval back",
            })
            _append(log, _acceptance_record(
                "acme_ledger_poster", _PHASE, implementation_hash="c" * 64))
            reduced = reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_ACTIVE)
            self.assertEqual(reduced.record["implementation_hash"], "c" * 64)

    def test_a_repudiation_for_a_different_phase_leaves_this_phase_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            _append(log, _acceptance_record("acme_ledger_poster", _PHASE))
            _append(log, {
                "schema": REPUDIATION_RECORD_SCHEMA,
                "capability_id": "acme_ledger_poster", "phase_id": "phase-1",
                "repudiated_at": "2026-02-02T00:00:00Z",
                "operator_confirmation": "no, take that approval back",
            })
            reduced = reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_ACTIVE)

    def test_a_repudiation_for_a_different_capability_is_not_borrowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            _append(log, _acceptance_record("acme_ledger_poster", _PHASE))
            _append(log, {
                "schema": REPUDIATION_RECORD_SCHEMA,
                "capability_id": "acme_report_reader", "phase_id": _PHASE,
                "repudiated_at": "2026-02-02T00:00:00Z",
                "operator_confirmation": "no, take that approval back",
            })
            reduced = reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_ACTIVE)

    def test_a_repudiation_with_no_operator_words_is_not_a_repudiation(self):
        """Silence must mean NO repudiation. A row carrying the schema but no confirmation is
        not the operator's act, so it must not take an approval down."""
        with tempfile.TemporaryDirectory() as tmp:
            for blank in (None, "", "   "):
                log = Path(tmp) / f"log_{blank!r}.jsonl"
                _append(log, _acceptance_record("acme_ledger_poster", _PHASE))
                row = {
                    "schema": REPUDIATION_RECORD_SCHEMA,
                    "capability_id": "acme_ledger_poster", "phase_id": _PHASE,
                    "repudiated_at": "2026-02-02T00:00:00Z",
                }
                if blank is not None:
                    row["operator_confirmation"] = blank
                _append(log, row)
                reduced = reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE)
                self.assertEqual(
                    reduced.status, ACCEPTANCE_STATUS_ACTIVE,
                    f"a repudiation row with confirmation {blank!r} must not bind")

    def test_a_repudiation_event_never_reads_as_an_acceptance_record(self):
        """The two event shapes must be structurally disjoint, or a repudiation could satisfy
        the presence check it is supposed to defeat."""
        event = {
            "schema": REPUDIATION_RECORD_SCHEMA,
            "capability_id": "acme_ledger_poster", "phase_id": _PHASE,
            "repudiated_at": "2026-02-02T00:00:00Z",
            "operator_confirmation": "no, take that approval back",
        }
        self.assertFalse(acceptance_ceremony.is_valid_acceptance_record(
            event, "acme_ledger_poster", _PHASE))
        self.assertTrue(acceptance_ceremony.is_valid_repudiation_record(
            event, ("acme_ledger_poster",), _PHASE))
        record = _acceptance_record("acme_ledger_poster", _PHASE)
        self.assertFalse(acceptance_ceremony.is_valid_repudiation_record(
            record, ("acme_ledger_poster",), _PHASE))

    def test_a_malformed_line_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            _append(log, _acceptance_record("acme_ledger_poster", _PHASE))
            with log.open("a", encoding="utf-8") as f:
                f.write("{not json at all\n\n[]\n")
            reduced = reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_ACTIVE)

    @unittest.skipIf(hasattr(os, "getuid") and os.getuid() == 0,
                     "running as root ignores permission bits")
    def test_an_existing_but_unreadable_log_is_unreadable_not_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            log.write_text("", encoding="utf-8")
            log.chmod(0o000)
            try:
                reduced = reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE)
                self.assertEqual(reduced.status, ACCEPTANCE_STATUS_UNREADABLE)
            finally:
                log.chmod(0o644)

    def test_no_phase_given_means_any_phase_counts(self):
        """Mirrors the pre-existing reader contract: only when the descriptor itself carries no
        phase does the latest record for the capability, regardless of phase, apply."""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            _append(log, _acceptance_record("acme_ledger_poster", "phase-1"))
            reduced = reduce_acceptance_log(str(log), ("acme_ledger_poster",), None)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_ACTIVE)
            _append(log, {
                "schema": REPUDIATION_RECORD_SCHEMA,
                "capability_id": "acme_ledger_poster", "phase_id": "phase-1",
                "repudiated_at": "2026-02-02T00:00:00Z",
                "operator_confirmation": "no, take that approval back",
            })
            reduced = reduce_acceptance_log(str(log), ("acme_ledger_poster",), None)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_REPUDIATED)

    def test_the_join_is_on_the_declared_id_across_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            _append(log, _acceptance_record("acme-ledger-poster", _PHASE))
            reduced = reduce_acceptance_log(
                str(log), frozenset({"acme_ledger_poster", "acme-ledger-poster"}), _PHASE)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_ACTIVE)


# ---------------------------------------------------------------------------
# 2. The revocation transition
# ---------------------------------------------------------------------------

class RepudiateAcceptanceTests(unittest.TestCase):

    def test_repudiating_an_active_acceptance_revokes_accepted_and_queues_a_retrial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))

            result = lifecycle_state.repudiate_acceptance(
                str(root), "acme_ledger_poster",
                operator_confirmation="no -- take that approval back please")

            self.assertTrue(result.repudiated)
            self.assertTrue(result.revoked)
            self.assertIsNone(result.reason)
            # THE load-bearing assertion: live authorization is actually gone.
            self.assertIs(_entry(root, "acme_ledger_poster")["accepted"], False)
            self.assertFalse(result.reconcile.accepted)
            # A named, reachable exit was queued -- not a silent strand.
            queued = [e for e in _queue(root) if e["mechanism_id"] == "acme_ledger_poster"]
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0]["status"], "pending")
            self.assertTrue(queued[0]["suggested_next_step"].strip())
            # The typed event is durable, and the reducer now answers "repudiated".
            reduced = reduce_acceptance_log(
                str(_log_path(root)), ("acme_ledger_poster",), _PHASE)
            self.assertEqual(reduced.status, ACCEPTANCE_STATUS_REPUDIATED)
            self.assertEqual(reduced.repudiation["operator_confirmation"],
                             "no -- take that approval back please")
            # The unrelated capability is untouched on every axis.
            self.assertIs(_entry(root, "acme_report_reader")["accepted"], True)
            self.assertEqual(
                [e for e in _queue(root) if e["mechanism_id"] == "acme_report_reader"], [])

    def test_the_acceptance_record_itself_is_left_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))
            before = _log_path(root).read_text(encoding="utf-8")

            lifecycle_state.repudiate_acceptance(
                str(root), "acme_ledger_poster", operator_confirmation="take it back")

            after = _log_path(root).read_text(encoding="utf-8")
            self.assertTrue(after.startswith(before),
                            "the log is append-only -- the original record must survive verbatim")

    def test_a_repudiation_of_a_non_active_acceptance_is_refused(self):
        """A repudiation must apply only to something that is actually live on record. Applying
        one to nothing would let a second run re-queue a retrial for a capability the operator
        already took back, and would record consent about a state that is not there."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))
            first = lifecycle_state.repudiate_acceptance(
                str(root), "acme_ledger_poster", operator_confirmation="take it back")
            self.assertTrue(first.repudiated)
            lines_after_first = _log_path(root).read_text(encoding="utf-8").splitlines()

            second = lifecycle_state.repudiate_acceptance(
                str(root), "acme_ledger_poster", operator_confirmation="take it back again")

            self.assertFalse(second.repudiated)
            self.assertFalse(second.revoked)
            self.assertIsNotNone(second.reason)
            self.assertEqual(
                _log_path(root).read_text(encoding="utf-8").splitlines(), lines_after_first,
                "a refused repudiation must write NOTHING to the log")

    def test_a_capability_with_no_acceptance_record_at_all_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            result = lifecycle_state.repudiate_acceptance(
                str(root), "acme_ledger_poster", operator_confirmation="take it back")
            self.assertFalse(result.repudiated)
            self.assertFalse(result.revoked)
            self.assertIs(_entry(root, "acme_ledger_poster")["accepted"], True,
                          "a refusal must never flip the flag")
            self.assertFalse(_log_path(root).exists())

    def test_silence_is_never_a_repudiation(self):
        """No default may produce the operator's decision. A blank confirmation refuses."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))
            for blank in ("", "   ", "\n", None):
                result = lifecycle_state.repudiate_acceptance(
                    str(root), "acme_ledger_poster", operator_confirmation=blank)
                self.assertFalse(result.repudiated, f"confirmation {blank!r} must refuse")
                self.assertIs(_entry(root, "acme_ledger_poster")["accepted"], True)

    def test_a_record_on_file_with_the_descriptor_already_off_is_still_repudiable(self):
        """The field case this exists for: a record that reads as genuine consent while the
        descriptor is not accepted. There is nothing to switch off, but the operator must still
        be able to put on record that the approval is not theirs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp, accepted=False)
            _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))

            result = lifecycle_state.repudiate_acceptance(
                str(root), "acme_ledger_poster", operator_confirmation="that was not me")

            self.assertTrue(result.repudiated)
            self.assertFalse(result.revoked,
                             "nothing was flipped -- `revoked` must not claim otherwise")
            self.assertEqual(
                reduce_acceptance_log(
                    str(_log_path(root)), ("acme_ledger_poster",), _PHASE).status,
                ACCEPTANCE_STATUS_REPUDIATED)

    def test_the_operator_note_never_claims_an_off_state_it_did_not_reach(self):
        """If the flip somehow did not land, the note must not say the capability is off."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))
            with mock.patch.object(lifecycle_state, "_revoke_accepted_entries",
                                   return_value=False):
                result = lifecycle_state.repudiate_acceptance(
                    str(root), "acme_ledger_poster", operator_confirmation="take it back")
            self.assertTrue(result.reconcile.accepted)
            self.assertNotEqual(result.note, lifecycle_state.REPUDIATION_NOTE)
            self.assertIn("still", result.note.lower())

    def test_the_flag_is_already_off_before_the_event_is_appended(self):
        """Order is load-bearing, not incidental. The failure this ordering prevents is a
        recorded withdrawal sitting next to live authorization -- so if the append blows up, the
        capability must ALREADY be off, not still authorized with the operator believing
        otherwise."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))
            boom = RuntimeError("disk full")
            with mock.patch.object(lifecycle_state, "append_repudiation_record",
                                   side_effect=boom):
                with self.assertRaises(RuntimeError):
                    lifecycle_state.repudiate_acceptance(
                        str(root), "acme_ledger_poster",
                        operator_confirmation="take it back")
            self.assertIs(
                _entry(root, "acme_ledger_poster")["accepted"], False,
                "the revocation must already have landed when the append failed")
            # And the log is untouched, so a re-run still sees ACTIVE and retries the append.
            self.assertEqual(
                reduce_acceptance_log(
                    str(_log_path(root)), ("acme_ledger_poster",), _PHASE).status,
                ACCEPTANCE_STATUS_ACTIVE)
            retried = lifecycle_state.repudiate_acceptance(
                str(root), "acme_ledger_poster", operator_confirmation="take it back")
            self.assertTrue(retried.repudiated)
            self.assertFalse(retried.revoked, "nothing left to flip on the retry")

    def test_the_retrial_reason_does_not_claim_the_code_changed(self):
        """The staleness path's reason says the implementation changed. That is false for a
        repudiation, and the two must not share a sentence."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))
            lifecycle_state.repudiate_acceptance(
                str(root), "acme_ledger_poster", operator_confirmation="take it back")
            entry = next(e for e in _queue(root) if e["mechanism_id"] == "acme_ledger_poster")
            self.assertNotIn("changed since", entry["reason"])
            self.assertIn("took", entry["reason"].lower())


# ---------------------------------------------------------------------------
# 3. Every reader of the acceptance log
# ---------------------------------------------------------------------------

class EveryReaderSeesTheRepudiationTests(unittest.TestCase):
    """This cut has paid repeatedly for a fix that corrected one consumer of a shared truth and
    left the others reading the old answer. These are the three readers of the acceptance log,
    named individually, with the answer each one must now give."""

    def _repudiated_project(self, tmp):
        root = _two_capability_project(tmp)
        _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))
        lifecycle_state.repudiate_acceptance(
            str(root), "acme_ledger_poster", operator_confirmation="take it back")
        # Put the flag back by hand -- the point of these assertions is that the readers do NOT
        # depend on the flip having survived. A hand edit, a half-applied transition, or a
        # restored backup must not resurrect a repudiated approval.
        entries = _descriptors(root)
        for e in entries:
            if e["id"] == "acme_ledger_poster":
                e["accepted"] = True
        _write_descriptors(root, entries)
        return root

    def test_reader_one_the_staleness_detector_treats_it_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repudiated_project(tmp)
            self.assertTrue(
                lifecycle_state.acceptance_hash_is_stale(str(root), "acme_ledger_poster"),
                "a repudiated acceptance must never supply hashes that read as current")

    def test_reader_two_the_completion_gate_is_not_done_and_says_why_honestly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repudiated_project(tmp)
            result = lifecycle_state.check_completion(str(root), "acme_ledger_poster")
            self.assertFalse(result.done)
            self.assertIn("acceptance-not-repudiated", result.failed_conjuncts)
            self.assertNotIn(
                "audit-appended", result.failed_conjuncts,
                "the record IS on file -- saying none was found would be a false claim")

    def test_reader_three_the_self_qa_battery_flags_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repudiated_project(tmp)
            failures = capability_invariants.check_capability_invariants(
                str(root), "acme_ledger_poster").failures
            hits = [f for f in failures if "took" in f.lower() or "taken back" in f.lower()]
            self.assertTrue(hits, f"no repudiation-aware failure in {failures!r}")

    def test_identity_twin_history_deliberately_still_reads_as_history(self):
        """The fourth reader of this log asks a DIFFERENT question -- "did this id ever carry
        real acceptance history" -- and its honest answer does not change. A repudiated
        acceptance is still history; answering False would make a twin that once held live
        authorization look safely disposable."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repudiated_project(tmp)
            has_record, read_error = capability_health._has_acceptance_audit_record(
                Path(root), "acme_ledger_poster")
            self.assertTrue(has_record)
            self.assertFalse(read_error)


# ---------------------------------------------------------------------------
# 4. operator_receipt_ref resolvability
# ---------------------------------------------------------------------------

class OperatorReceiptResolvabilityTests(unittest.TestCase):

    def test_a_present_json_receipt_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "r.json"
            receipt.write_text(json.dumps({"schema": "x"}), encoding="utf-8")
            res = resolve_operator_receipt_ref(
                _acceptance_record("acme_ledger_poster", _PHASE,
                                   operator_receipt_ref=str(receipt)))
            self.assertTrue(res.resolved)

    def test_a_dangling_ref_is_detected_rather_than_reading_as_genuine(self):
        """The synthesized equivalent of the shape found in the field: a record that looks like
        real consent, pointing at a receipt that is not there."""
        with tempfile.TemporaryDirectory() as tmp:
            res = resolve_operator_receipt_ref(
                _acceptance_record(
                    "acme_ledger_poster", _PHASE,
                    operator_receipt_ref=str(Path(tmp) / "security" /
                                             "acceptance_receipts" / "gone.json")))
            self.assertFalse(res.resolved)
            self.assertEqual(res.status, acceptance_ceremony.RECEIPT_STATUS_ABSENT)

    def test_a_missing_or_blank_ref_does_not_resolve(self):
        for ref in (None, "", "   ", 7):
            record = _acceptance_record("acme_ledger_poster", _PHASE)
            record["operator_receipt_ref"] = ref
            res = resolve_operator_receipt_ref(record)
            self.assertFalse(res.resolved, f"ref {ref!r} must not resolve")
            self.assertEqual(res.status, acceptance_ceremony.RECEIPT_STATUS_NO_REF)

    def test_a_non_json_receipt_does_not_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "r.json"
            receipt.write_text("not json", encoding="utf-8")
            res = resolve_operator_receipt_ref(
                _acceptance_record("acme_ledger_poster", _PHASE,
                                   operator_receipt_ref=str(receipt)))
            self.assertFalse(res.resolved)
            self.assertEqual(res.status, acceptance_ceremony.RECEIPT_STATUS_UNPARSABLE)

    def test_a_json_non_object_receipt_does_not_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "r.json"
            receipt.write_text("[1, 2]", encoding="utf-8")
            res = resolve_operator_receipt_ref(
                _acceptance_record("acme_ledger_poster", _PHASE,
                                   operator_receipt_ref=str(receipt)))
            self.assertFalse(res.resolved)
            self.assertEqual(res.status, acceptance_ceremony.RECEIPT_STATUS_NOT_AN_OBJECT)

    @unittest.skipIf(hasattr(os, "getuid") and os.getuid() == 0,
                     "running as root ignores permission bits")
    def test_an_inaccessible_receipt_is_distinguished_from_an_absent_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "locked"
            d.mkdir()
            receipt = d / "r.json"
            receipt.write_text("{}", encoding="utf-8")
            d.chmod(0o000)
            try:
                res = resolve_operator_receipt_ref(
                    _acceptance_record("acme_ledger_poster", _PHASE,
                                       operator_receipt_ref=str(receipt)))
                self.assertFalse(res.resolved)
                self.assertEqual(res.status, acceptance_ceremony.RECEIPT_STATUS_UNREADABLE)
            finally:
                d.chmod(0o755)

    def test_resolvability_is_never_claimed_to_be_authenticity(self):
        doc = resolve_operator_receipt_ref.__doc__ or ""
        low = doc.lower()
        self.assertIn("does not", low)
        self.assertTrue("genuine" in low or "authentic" in low,
                        "the docstring must disclose what resolution does NOT establish")

    def test_the_self_qa_battery_flags_a_dangling_receipt_on_a_live_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            _append(_log_path(root), _acceptance_record(
                "acme_ledger_poster", _PHASE,
                operator_receipt_ref="security/acceptance_receipts/gone.json"))
            failures = capability_invariants.check_capability_invariants(
                str(root), "acme_ledger_poster").failures
            hits = [f for f in failures if "receipt" in f.lower()]
            self.assertTrue(hits, f"no dangling-receipt failure in {failures!r}")
            self.assertTrue(
                any(acceptance_repudiation.REPUDIATION_ENTRYPOINT_REL in f for f in hits),
                "a detection with no named way out is the dead end this cut exists to close")

    def test_a_resolvable_receipt_produces_no_receipt_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            receipt = Path(root) / "security" / "acceptance_receipts" / "r.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps({"schema": "operator_acceptance_receipt-v1"}),
                               encoding="utf-8")
            _append(_log_path(root), _acceptance_record(
                "acme_ledger_poster", _PHASE,
                operator_receipt_ref="security/acceptance_receipts/r.json"))
            failures = capability_invariants.check_capability_invariants(
                str(root), "acme_ledger_poster").failures
            self.assertEqual([f for f in failures if "receipt" in f.lower()], [])


# ---------------------------------------------------------------------------
# 5. The operator entrypoint
# ---------------------------------------------------------------------------

class RepudiationEntrypointTests(unittest.TestCase):

    def test_the_entrypoint_path_names_a_file_that_exists(self):
        self.assertTrue(
            (_AGENTS_LIB.parent.parent /
             acceptance_repudiation.REPUDIATION_ENTRYPOINT_REL).is_file())

    def test_the_rendered_command_is_a_single_physical_line(self):
        cmd = acceptance_repudiation.repudiation_command("acme_ledger_poster")
        self.assertNotIn("\n", cmd)
        self.assertIn(acceptance_repudiation.REPUDIATION_ENTRYPOINT_REL, cmd)
        self.assertIn(acceptance_repudiation.CONFIRMATION_PLACEHOLDER, cmd)

    def test_the_renderer_refuses_a_confirmation_that_spans_lines(self):
        with self.assertRaises(ValueError):
            acceptance_repudiation.repudiation_command(
                "acme_ledger_poster", operator_confirmation="take\nit back")

    def test_the_parser_denies_by_default(self):
        for argv in ([], ["--capability-id"], ["--capability-id", "x"],
                     ["--capability-id", "x", "--operator-confirmation", "  "],
                     ["--capability-id", "x", "--operator-confirmation", "y", "--extra", "z"]):
            options, error = acceptance_repudiation.parse_repudiation_args(argv)
            self.assertIsNone(options, f"{argv!r} must not parse")
            self.assertTrue(error)

    def test_the_parser_accepts_the_real_shape(self):
        options, error = acceptance_repudiation.parse_repudiation_args(
            ["--capability-id", "acme_ledger_poster",
             "--operator-confirmation", "take it back"])
        self.assertIsNone(error)
        self.assertEqual(options[acceptance_repudiation.FLAG_CAPABILITY],
                         "acme_ledger_poster")

    def test_the_confirmation_flag_is_the_one_the_baked_consent_scan_watches(self):
        """Reusing the same flag spelling is what puts a machine-written repudiation inside the
        existing static baked-consent check's reach, rather than shipping a second consent flag
        nothing watches."""
        from external_write.scan import OPERATOR_CONFIRMATION_FLAG
        self.assertEqual(acceptance_repudiation.FLAG_CONFIRMATION,
                         OPERATOR_CONFIRMATION_FLAG)

    def test_the_retrial_next_step_names_commands_that_actually_exist(self):
        """The post-revocation state's declared exit is the re-trial queue entry, and its
        next-step text names two commands by path. Those paths are hand-spelled there rather
        than imported (importing `trial_executor` into `lifecycle_state` for a string would pull
        the whole trial stack into the completion gate's import graph -- the same reasoning
        `command_manifest` records for its own prefixes). Hand-spelled is only acceptable when
        something fails on drift, which is what this is: an exit that names a path no longer on
        disk is a dead end wearing a next step."""
        text = lifecycle_state.REPUDIATION_RETRIAL_NEXT_STEP
        project = _AGENTS_LIB.parent.parent
        for rel in ("agents/lib/external_write/trial_executor.py",
                    "agents/lib/external_write/operator_acceptance.py"):
            self.assertIn(rel, text, f"the exit must name {rel}")
            self.assertTrue((project / rel).is_file(), f"{rel} is named but not on disk")
            self.assertTrue(
                any(e.command_prefix.endswith("/" + Path(rel).name)
                    for e in command_manifest.BASELINE_COMMANDS),
                f"{rel} is named as an exit but is not an enrolled operator command")
        from external_write.trial_executor import TRIAL_ENTRYPOINT_REL
        self.assertIn(TRIAL_ENTRYPOINT_REL, text)

    def test_the_entrypoint_constant_agrees_with_the_enrolled_prefix(self):
        entry = command_manifest.find_command("repudiate-acceptance")
        self.assertEqual(entry.command_prefix,
                         f"python3 {acceptance_repudiation.REPUDIATION_ENTRYPOINT_REL}")

    def test_the_command_is_enrolled_as_a_live_write(self):
        entry = command_manifest.find_command("repudiate-acceptance")
        self.assertIsNotNone(entry, "an operator-invocable command must be classified")
        self.assertEqual(entry.command_class, command_manifest.LIVE_WRITE)
        self.assertTrue(entry.writes_external)
        self.assertFalse(command_manifest.is_allowlist_eligible(entry),
                         "what this records is the operator's own decision -- never auto-approved")
        self.assertTrue(
            entry.command_prefix.endswith(
                "/" + Path(acceptance_repudiation.REPUDIATION_ENTRYPOINT_REL).name))

    def test_the_cli_takes_the_approval_down_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))
            env = dict(os.environ)
            env["PYTHONPATH"] = str(_AGENTS_LIB) + os.pathsep + env.get("PYTHONPATH", "")
            proc = subprocess.run(
                [sys.executable, "-B",
                 str(_AGENTS_LIB / "external_write" / "acceptance_repudiation.py"),
                 "--capability-id", "acme_ledger_poster",
                 "--operator-confirmation", "no, take that approval back"],
                cwd=str(root), env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, acceptance_repudiation.EXIT_RECORDED,
                             f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
            self.assertIs(_entry(root, "acme_ledger_poster")["accepted"], False)
            self.assertEqual(
                reduce_acceptance_log(
                    str(_log_path(root)), ("acme_ledger_poster",), _PHASE).status,
                ACCEPTANCE_STATUS_REPUDIATED)

    def test_the_cli_refuses_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            env = dict(os.environ)
            env["PYTHONPATH"] = str(_AGENTS_LIB) + os.pathsep + env.get("PYTHONPATH", "")
            proc = subprocess.run(
                [sys.executable, "-B",
                 str(_AGENTS_LIB / "external_write" / "acceptance_repudiation.py"),
                 "--capability-id", "acme_ledger_poster",
                 "--operator-confirmation", "no, take that approval back"],
                cwd=str(root), env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, acceptance_repudiation.EXIT_REFUSED)
            self.assertNotIn("Traceback", proc.stderr)


# ---------------------------------------------------------------------------
# 6. Fix round 1 -- claims that outran what the mechanism established
# ---------------------------------------------------------------------------

class ReceiptFailureSaysWhatIsActuallyWrongTests(unittest.TestCase):
    """The receipt check covers several distinct causes, and one sentence for all of them is
    false for most. A record carrying NO reference does not "point at a receipt file", there is
    no file to "restore", and an internal status token is not something a non-technical operator
    can act on."""

    def _failures_for(self, tmp, record_overrides):
        root = _two_capability_project(tmp)
        record = _acceptance_record("acme_ledger_poster", _PHASE)
        record.update(record_overrides)
        _append(_log_path(root), record)
        return capability_invariants.check_capability_invariants(
            str(root), "acme_ledger_poster").failures

    def _receipt_failure(self, failures):
        hits = [f for f in failures if f.startswith("Acceptance receipt:")]
        self.assertEqual(len(hits), 1, f"expected exactly one receipt failure in {failures!r}")
        return hits[0]

    def test_a_record_with_no_reference_at_all_is_not_described_as_pointing_at_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = self._receipt_failure(
                self._failures_for(tmp, {"operator_receipt_ref": None}))
            self.assertNotIn("points at a receipt file", message)
            self.assertNotIn("restore that receipt file", message)
            self.assertIn("no reference to a receipt", message)
            # The only honest exit for this one: there is no file to put back.
            self.assertIn(acceptance_repudiation.REPUDIATION_ENTRYPOINT_REL, message)

    def test_a_dangling_reference_still_offers_the_restore_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = self._receipt_failure(self._failures_for(
                tmp, {"operator_receipt_ref": "security/acceptance_receipts/gone.json"}))
            # The intent is that the put-it-back exit is offered, not that a particular verb is
            # used -- the message deliberately says "put that file back" rather than "restore",
            # which is the plainer wording for a non-technical reader.
            self.assertIn("put that file back", message)
            self.assertIn("security/acceptance_receipts/gone.json", message)
            self.assertIn(acceptance_repudiation.REPUDIATION_ENTRYPOINT_REL, message)

    def test_no_internal_token_or_python_none_reaches_the_operator(self):
        for overrides in ({"operator_receipt_ref": None},
                          {"operator_receipt_ref": "security/acceptance_receipts/gone.json"}):
            with tempfile.TemporaryDirectory() as tmp:  # a fresh project per case
                message = self._receipt_failure(self._failures_for(tmp, overrides))
                for leak in ("None", "no_ref", "not_an_object", "unparsable",
                             "RECEIPT_STATUS"):
                    self.assertNotIn(leak, message,
                                     f"{leak!r} leaked into an operator-facing line: {message!r}")


class AnUnreadableLogIsNotReportedAsAnAbsentRecordTests(unittest.TestCase):
    """"No record was ever written" and "the log is there and we could not read it" are opposite
    evidence, and they call for opposite repairs: re-run the approval step, versus fix a file you
    cannot read. Reporting the second as the first attaches the wrong next step to a permissions
    problem."""

    def _unreadable_log_project(self, tmp):
        root = _two_capability_project(tmp)
        log = _log_path(root)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("", encoding="utf-8")
        log.chmod(0o000)
        return root, log

    @unittest.skipIf(hasattr(os, "getuid") and os.getuid() == 0,
                     "running as root ignores permission bits")
    def test_the_self_qa_battery_says_it_could_not_read_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, log = self._unreadable_log_project(tmp)
            try:
                failures = capability_invariants.check_capability_invariants(
                    str(root), "acme_ledger_poster").failures
            finally:
                log.chmod(0o644)
            audit = [f for f in failures if f.startswith("Audit record:")]
            self.assertEqual(len(audit), 1, f"expected one audit failure in {failures!r}")
            self.assertNotIn("no matching acceptance audit record was found", audit[0])
            self.assertIn("could not be read", audit[0])

    @unittest.skipIf(hasattr(os, "getuid") and os.getuid() == 0,
                     "running as root ignores permission bits")
    def test_the_completion_gate_reports_it_as_its_own_conjunct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, log = self._unreadable_log_project(tmp)
            try:
                result = lifecycle_state.check_completion(str(root), "acme_ledger_poster")
            finally:
                log.chmod(0o644)
            self.assertFalse(result.done)
            self.assertIn("audit-log-readable", result.failed_conjuncts)
            self.assertNotIn(
                "audit-appended", result.failed_conjuncts,
                "an unreadable log is not evidence that no entry exists")
            self.assertIn("could not be read", result.operator_message)

    def test_a_genuinely_absent_record_still_reports_audit_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            result = lifecycle_state.check_completion(str(root), "acme_ledger_poster")
            self.assertIn("audit-appended", result.failed_conjuncts)
            self.assertNotIn("audit-log-readable", result.failed_conjuncts)


class TheAcceptanceShapePredicateStaysOnTheEnforcedPathTests(unittest.TestCase):
    """``is_valid_acceptance_record`` and the reducer's ACTIVE branch must not be two
    implementations of "is this line a real acceptance record for this pair" with nothing forcing
    them to agree. The reducer DELEGATES; these pin that it still does."""

    def test_the_reducer_calls_the_predicate(self):
        import ast
        src = (_AGENTS_LIB / "external_write" / "acceptance_ceremony.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "reduce_acceptance_log")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn(
            "is_valid_acceptance_record", called,
            "the reducer must decide 'is this a real acceptance record for this pair' through "
            "the one predicate that owns that question, not by re-spelling it inline")

    def test_the_reducer_and_the_predicate_agree_line_for_line(self):
        good = _acceptance_record("acme_ledger_poster", _PHASE)
        cases = [good]
        for field in ("implementation_hash", "op_kind"):
            absent = dict(good)
            absent.pop(field)
            blank = dict(good)
            blank[field] = ""
            wrong_type = dict(good)
            wrong_type[field] = 7
            cases += [absent, blank, wrong_type]
        wrong_phase = dict(good)
        wrong_phase["phase_id"] = "phase-other"
        cases.append(wrong_phase)
        with tempfile.TemporaryDirectory() as tmp:
            for i, rec in enumerate(cases):
                log = Path(tmp) / f"log{i}.jsonl"
                _append(log, rec)
                reduced_active = (
                    reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE).status
                    == ACCEPTANCE_STATUS_ACTIVE)
                predicate = acceptance_ceremony.is_valid_acceptance_record(
                    rec, "acme_ledger_poster", _PHASE)
                self.assertEqual(reduced_active, predicate,
                                 f"reducer and predicate disagree on {rec!r}")


class NoFalseAbsolutesTests(unittest.TestCase):

    def test_the_cli_does_not_claim_it_never_prints_a_traceback(self):
        """It catches two named exceptions. An I/O failure from the descriptor write or the log
        append is not one of them, so the absolute was a claim the except tuple did not make."""
        src = (_AGENTS_LIB / "external_write" / "acceptance_repudiation.py").read_text(
            encoding="utf-8")
        self.assertNotIn("Never prints a traceback", src)

    def test_the_usage_does_not_claim_a_refusal_always_changed_nothing(self):
        """One path exits refused after the change already landed: the state check that runs
        AFTER the revoke and the append can fail on its own."""
        usage = acceptance_repudiation.USAGE
        self.assertNotIn("nothing was changed (it says why)", usage)
        self.assertIn("after", usage.lower())

    def test_the_result_docstring_discloses_the_unresolved_id_case(self):
        doc = (lifecycle_state.RepudiationResult.__doc__ or "").lower()
        self.assertIn("as given", doc)
        self.assertIn("blank-confirmation refusal", doc)

    def test_a_blank_confirmation_refuses_before_identity_resolution_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            result = lifecycle_state.repudiate_acceptance(
                str(root), "no_such_capability_anywhere", operator_confirmation="   ")
            self.assertFalse(result.repudiated)
            self.assertEqual(result.canonical_id, "no_such_capability_anywhere")

    def test_the_appender_enforces_the_disjointness_the_docstring_claims(self):
        """The two event shapes being disjoint was asserted as "can never", but nothing stopped a
        hand-built hybrid from being appended. The appender now enforces it."""
        event = acceptance_ceremony.build_repudiation_record(
            "acme_ledger_poster", _PHASE, "take it back",
            repudiated_at="2026-02-02T00:00:00Z")
        hybrid = dict(event)
        hybrid["implementation_hash"] = "a" * 64
        hybrid["op_kind"] = _OP_KIND
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            with self.assertRaises(ValueError):
                acceptance_ceremony.append_repudiation_record(str(log), hybrid)
            self.assertFalse(log.exists(), "a refused append must write nothing")

    def test_a_hand_written_hybrid_line_still_reduces_to_repudiated(self):
        """Belt and braces on the resolved direction: even a line the appender would refuse, if
        someone wrote it by hand, is read as the repudiation it declares itself to be."""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            _append(log, _acceptance_record("acme_ledger_poster", _PHASE))
            hybrid = {
                "schema": REPUDIATION_RECORD_SCHEMA,
                "capability_id": "acme_ledger_poster", "phase_id": _PHASE,
                "repudiated_at": "2026-02-02T00:00:00Z",
                "operator_confirmation": "take it back",
                "implementation_hash": "a" * 64, "op_kind": _OP_KIND,
            }
            _append(log, hybrid)
            self.assertEqual(
                reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE).status,
                ACCEPTANCE_STATUS_REPUDIATED)


class ThePlaceholderIsNotTheOperatorsWordsTests(unittest.TestCase):
    """The rendered command carries a blank for the operator to replace. Pasted unedited, it
    would write the machine's placeholder into the log as their verbatim consent -- the field
    whose whole content is supposed to be what THEY said."""

    def test_the_placeholder_pasted_unedited_is_refused(self):
        options, error = acceptance_repudiation.parse_repudiation_args(
            ["--capability-id", "acme_ledger_poster",
             "--operator-confirmation", acceptance_repudiation.CONFIRMATION_PLACEHOLDER])
        self.assertIsNone(options)
        self.assertTrue(error)

    def test_the_placeholder_with_surrounding_space_is_also_refused(self):
        options, error = acceptance_repudiation.parse_repudiation_args(
            ["--capability-id", "acme_ledger_poster",
             "--operator-confirmation",
             f"  {acceptance_repudiation.CONFIRMATION_PLACEHOLDER}  "])
        self.assertIsNone(options)
        self.assertTrue(error)

    def test_real_words_that_merely_mention_the_shape_are_still_accepted(self):
        options, error = acceptance_repudiation.parse_repudiation_args(
            ["--capability-id", "acme_ledger_poster",
             "--operator-confirmation",
             "I never said what you said, word for word, so take it back"])
        self.assertIsNone(error, error)
        self.assertIsNotNone(options)


class TheAddCapabilitySkillDescribesTheNewEntryKindTests(unittest.TestCase):
    """The pending-migration queue now carries an entry kind whose cause is the operator's own
    withdrawal, with nothing changed about the capability's code. The skill's prose asserted the
    opposite for every entry."""

    SKILL = Path(__file__).resolve().parents[2] / "skills" / "add-capability.md"

    def test_the_skill_does_not_claim_every_entry_came_from_an_upgrade(self):
        text = self.SKILL.read_text(encoding="utf-8")
        self.assertNotIn(
            "an upgrade previously found an existing mechanism that no longer follows a safety "
            "rule (see `operating_discipline.md`) and safe-paused it rather than leaving it "
            "running unsafely or breaking it outright — each entry names the paused mechanism",
            text)

    def test_the_skill_does_not_claim_only_technical_wiring_changes(self):
        text = self.SKILL.read_text(encoding="utf-8")
        self.assertNotIn("Its business purpose does not change — only its technical wiring does",
                         text)

    def test_the_skill_names_the_withdrawal_kind_and_reads_the_entrys_own_words(self):
        text = self.SKILL.read_text(encoding="utf-8")
        self.assertIn("suggested_next_step", text)
        low = text.lower()
        self.assertTrue("took" in low or "taken back" in low or "withdrew" in low,
                        "the skill must name the operator-withdrawal entry kind")


# ---------------------------------------------------------------------------
# 7. Fix round 2
# ---------------------------------------------------------------------------

class TheQueueEntryDeclaresWhatItIsTests(unittest.TestCase):
    """The rebuild flow dispatches on an entry's ``kind``. A retrial entry that carries none
    lands in the branch for "no kind field", which is a decision made from a field's ABSENCE --
    inferring identity from incidental structure, in the one place whose output is a code rewrite
    of the operator's own file. The writer declares what it wrote; the reader joins on that."""

    def test_a_repudiation_entry_declares_its_own_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            _append(_log_path(root), _acceptance_record("acme_ledger_poster", _PHASE))
            lifecycle_state.repudiate_acceptance(
                str(root), "acme_ledger_poster", operator_confirmation="take it back")
            entry = next(e for e in _queue(root) if e["mechanism_id"] == "acme_ledger_poster")
            self.assertEqual(entry["kind"], lifecycle_state.RETRIAL_KIND_REPUDIATED)

    def test_the_two_retrial_causes_declare_DIFFERENT_kinds(self):
        """A reader that cannot tell them apart is back to guessing: one means the code moved,
        the other means the operator changed their mind and the code is untouched."""
        self.assertNotEqual(lifecycle_state.RETRIAL_KIND_REPUDIATED,
                            lifecycle_state.RETRIAL_KIND_STALE)

    def test_a_staleness_entry_declares_its_own_kind_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            lifecycle_state._queue_retrial_migration(
                root, "acme_ledger_poster",
                kind=lifecycle_state.RETRIAL_KIND_STALE,
                reason=lifecycle_state.STALENESS_RETRIAL_REASON,
                suggested_next_step=lifecycle_state.STALENESS_RETRIAL_NEXT_STEP)
            entry = next(e for e in _queue(root) if e["mechanism_id"] == "acme_ledger_poster")
            self.assertEqual(entry["kind"], lifecycle_state.RETRIAL_KIND_STALE)

    def test_the_rebuild_skill_dispatches_on_both_declared_kinds(self):
        text = (Path(__file__).resolve().parents[2] / "skills"
                / "rebuild-paused-capability.md").read_text(encoding="utf-8")
        for kind in (lifecycle_state.RETRIAL_KIND_REPUDIATED,
                     lifecycle_state.RETRIAL_KIND_STALE):
            self.assertIn(kind, text,
                          f"the rebuild flow must name the {kind!r} entry kind it will receive")

    def test_the_rebuild_skill_kindless_branch_no_longer_assumes_a_writer_rewrite(self):
        """The kind-less branch used to say, unconditionally, that a kind-less entry IS a
        direct-write violation. That is a claim from a field not being there."""
        text = (Path(__file__).resolve().parents[2] / "skills"
                / "rebuild-paused-capability.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "**If the entry has no `kind` field** (a direct-write violation an upgrade caught, "
            "not a missing-predicate gap):", text)
        self.assertIn("external_write_gate_violation", text)

    def test_the_rebuild_skill_does_not_frame_every_arrival_as_an_upgrade(self):
        text = (Path(__file__).resolve().parents[2] / "skills"
                / "rebuild-paused-capability.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "An upgrade found that one of the operator's existing capabilities no longer matches "
            "a safety rule the system now enforces, and safe-paused it rather than leave it "
            "running unsafely or break it outright. This skill is the one, guided path back "
            "from that:", text)

    def test_add_capability_exclusion_is_not_scoped_to_upgrades_only(self):
        text = (Path(__file__).resolve().parents[2] / "skills"
                / "add-capability.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "It also does not rebuild an existing capability that a contract-changing upgrade "
            "paused", text)

    def test_add_capability_does_not_say_two_fields_after_naming_three(self):
        text = (Path(__file__).resolve().parents[2] / "skills"
                / "add-capability.md").read_text(encoding="utf-8")
        self.assertNotIn("Read those two fields", text)


class EveryConfirmationEntrypointRefusesItsOwnPlaceholderTests(unittest.TestCase):
    """F6 closed this in one module. Its twin renders a byte-identical blank and accepted it
    verbatim, which is the same hazard one module over -- the body-without-target-hooks shape.

    Written as a POPULATION rather than as two cases: the declared set below must equal the set
    of modules that actually render a confirmation blank, so a third entrypoint added later fails
    here until it is enrolled with its own refusal, rather than shipping the hazard again."""

    #: module -> (the constant holding its rendered blank, the parser that must refuse it).
    #: Declared, not derived from a name pattern: which function guards a module, and which
    #: constant it renders, are not things to infer from spelling.
    _ENROLLED = {
        "acceptance_repudiation": ("CONFIRMATION_PLACEHOLDER", "parse_repudiation_args"),
        "writer_acknowledgement": ("CONFIRMATION_PLACEHOLDER", "parse_acknowledgement_args"),
        "trial_executor": ("APPROVAL_PLACEHOLDER", "parse_trial_args"),
    }

    def _modules_rendering_a_blank(self):
        """Discovered on the constant's VALUE -- a ``<...>`` fill-in-the-blank -- never on its
        symbol name. Keying on the name `CONFIRMATION_PLACEHOLDER` is what let this population
        miss `trial_executor.APPROVAL_PLACEHOLDER`, at the surface that authorizes a real
        bounded live write: a name is incidental structure, and the enrolled set then equalled
        the discovered set only because the discovery was looking for the wrong thing."""
        import ast
        found = {}
        d = _AGENTS_LIB / "external_write"
        for path in sorted(d.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                targets = ([node.target] if isinstance(node, ast.AnnAssign)
                           else getattr(node, "targets", []))
                value = getattr(node, "value", None)
                if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                    continue
                if not (value.value.startswith("<") and value.value.endswith(">")):
                    continue
                for t in targets:
                    if isinstance(t, ast.Name):
                        found[path.stem] = t.id
        return found

    def test_the_enrolled_set_is_the_whole_population(self):
        discovered = self._modules_rendering_a_blank()
        self.assertEqual(
            set(discovered), set(self._ENROLLED),
            "a module that renders an operator's own words as a fill-in blank must have a "
            "parser that refuses that blank pasted unedited, and be enrolled here")
        for mod_name, const_name in discovered.items():
            self.assertEqual(self._ENROLLED[mod_name][0], const_name,
                             f"{mod_name} renders a different constant than enrolled")

    def _argv_with(self, mod, const_name, filler):
        """Every declared FLAG_ on the module, with the words-flag carrying ``filler``. The
        words-flag is the one whose value the module interpolates its blank into."""
        blank = getattr(mod, const_name)
        argv = []
        for attr in sorted(a for a in dir(mod) if a.startswith("FLAG_")):
            flag = getattr(mod, attr)
            argv += [flag, filler if attr in ("FLAG_CONFIRMATION", "FLAG_APPROVAL")
                     else "some_subject"]
        return argv, blank

    def test_each_one_refuses_its_own_placeholder_pasted_unedited(self):
        import importlib
        for mod_name, (const_name, parser_name) in self._ENROLLED.items():
            mod = importlib.import_module(f"external_write.{mod_name}")
            argv, blank = self._argv_with(mod, const_name, getattr(mod, const_name))
            options, error = getattr(mod, parser_name)(argv)
            self.assertIsNone(options, f"{mod_name} accepted its own printed blank {blank!r}")
            self.assertTrue(error)

    def test_each_refusal_routes_the_operator_onward(self):
        """A refusal that names nothing to do instead is a dead end, and the surfaces that
        render these commands hand them over with the blank still in.

        CORRECTED READING (an earlier version of this docstring asserted the opposite, and it
        was wrong): the round-trip test that drives the rendered acknowledgement command did go
        red the moment this refusal existed without a route -- but NOT because a success became
        a failure. In that fixture two entries name one file, so pre-refusal the placeholder
        parsed and the command then failed on the AMBIGUITY refusal, exit 1, recording nothing.
        The test was already on its non-zero branch; what changed was the MESSAGE, which stopped
        carrying the repair constant that branch accepts. The forged-consent hazard this refusal
        closes is real -- nothing between the parser and the record checks the blank -- but that
        test is not evidence of it."""
        import importlib
        for mod_name, (const_name, parser_name) in self._ENROLLED.items():
            mod = importlib.import_module(f"external_write.{mod_name}")
            argv, _blank = self._argv_with(mod, const_name, getattr(mod, const_name))
            _options, error = getattr(mod, parser_name)(argv)
            low = (error or "").lower()
            self.assertIn("replace it with your own words", low, mod_name)
            self.assertIn("ask your assistant", low,
                          f"{mod_name}: a refusal must route someone who does not know what to "
                          "type, not just tell them they are wrong")

    def test_each_one_still_accepts_real_words(self):
        import importlib
        for mod_name, (const_name, parser_name) in self._ENROLLED.items():
            mod = importlib.import_module(f"external_write.{mod_name}")
            argv, _blank = self._argv_with(mod, const_name, "yes, I really mean it")
            options, error = getattr(mod, parser_name)(argv)
            self.assertIsNone(error, f"{mod_name}: {error}")
            self.assertIsNotNone(options)


class ClaimsMatchTheirMechanismRoundTwoTests(unittest.TestCase):

    def test_the_no_ref_arm_does_not_deny_the_record_of_what_was_said(self):
        """A real ceremony append writes the operator's own words into that same record. What is
        missing is the receipt it points at, not every trace of what they said."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            record = _acceptance_record("acme_ledger_poster", _PHASE)
            record["operator_receipt_ref"] = None
            _append(_log_path(root), record)
            failures = capability_invariants.check_capability_invariants(
                str(root), "acme_ledger_poster").failures
            message = next(f for f in failures if f.startswith("Acceptance receipt:"))
            self.assertNotIn("no record of what you signed off", message)
            self.assertIn("cannot be traced back", message)

    @unittest.skipIf(hasattr(os, "getuid") and os.getuid() == 0,
                     "running as root ignores permission bits")
    def test_an_unreachable_receipt_is_not_asserted_to_exist(self):
        """The UNREADABLE arm is reached whenever os.stat raises something other than
        FileNotFoundError -- including a parent directory the reader cannot traverse, where
        whether the file exists is UNKNOWN. Saying "it is there" inverts the very asymmetry the
        resolver's own docstring is careful about."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            locked = Path(root) / "security" / "locked"
            locked.mkdir(parents=True, exist_ok=True)
            (locked / "r.json").write_text("{}", encoding="utf-8")
            _append(_log_path(root), _acceptance_record(
                "acme_ledger_poster", _PHASE,
                operator_receipt_ref="security/locked/r.json"))
            locked.chmod(0o000)
            try:
                failures = capability_invariants.check_capability_invariants(
                    str(root), "acme_ledger_poster").failures
            finally:
                locked.chmod(0o755)
            message = next(f for f in failures if f.startswith("Acceptance receipt:"))
            self.assertNotIn("is there but", message)
            self.assertIn("could not be reached", message)

    @unittest.skipIf(hasattr(os, "getuid") and os.getuid() == 0,
                     "running as root ignores permission bits")
    def test_an_unreadable_acceptance_log_is_not_asserted_to_exist_either(self):
        """Same correction, the audit-log half. NOTE on coverage, so the next reader does not
        assume more than this proves: the parent-directory variant (existence genuinely unknown)
        is NOT reachable through this entrypoint for the acceptance log, because its parent
        folder also holds the descriptor set -- locking it degrades the check before check 5 ever
        runs. The receipt half of this correction IS reachable that way and is tested above. Here
        the sentence is pinned on the reachable file-level failure, and what it must not do is
        assert existence in either case."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            log = _log_path(root)
            _append(log, _acceptance_record("acme_ledger_poster", _PHASE))
            log.chmod(0o000)
            try:
                failures = capability_invariants.check_capability_invariants(
                    str(root), "acme_ledger_poster").failures
            finally:
                log.chmod(0o644)
            audit = [f for f in failures if f.startswith("Audit record:")]
            self.assertEqual(len(audit), 1, f"expected one audit failure in {failures!r}")
            self.assertNotIn("is there but", audit[0])
            self.assertIn("could not be read", audit[0])
            self.assertIn("not confirmation the file is gone", audit[0])

    def test_the_hybrid_refusal_is_not_described_as_either_field(self):
        """The guard requires BOTH a non-empty implementation_hash AND a non-empty op_kind, so
        "either" names a refusal that does not happen."""
        for doc in (acceptance_ceremony.is_valid_repudiation_record.__doc__ or "",
                    acceptance_ceremony.append_repudiation_record.__doc__ or ""):
            self.assertNotIn("either", doc)

    def test_a_one_field_row_is_appended_and_the_docstring_does_not_deny_it(self):
        """The guard requires BOTH fields, so a one-field row is written. The substantive
        property still holds -- the reducer reads it as a repudiation -- but the sentence must
        not claim a refusal that does not happen."""
        event = acceptance_ceremony.build_repudiation_record(
            "acme_ledger_poster", _PHASE, "take it back",
            repudiated_at="2026-02-02T00:00:00Z")
        one_field = dict(event)
        one_field["op_kind"] = _OP_KIND
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.jsonl"
            acceptance_ceremony.append_repudiation_record(str(log), one_field)
            self.assertTrue(log.exists())
            self.assertEqual(
                reduce_acceptance_log(str(log), ("acme_ledger_poster",), _PHASE).status,
                ACCEPTANCE_STATUS_REPUDIATED)

    def test_the_usage_does_not_promise_the_message_says_what_changed(self):
        usage = acceptance_repudiation.USAGE
        self.assertNotIn("says whether anything changed", usage)
        self.assertIn("after", usage.lower())

    def test_the_reducer_consumer_list_is_complete(self):
        """A list that enumerates its consumers has to enumerate all of them, or the next reader
        trusts it and misses one."""
        import ast
        src = (_AGENTS_LIB / "external_write" / "acceptance_ceremony.py").read_text(
            encoding="utf-8")
        doc = ast.get_docstring(next(
            n for n in ast.parse(src).body
            if isinstance(n, ast.FunctionDef) and n.name == "is_valid_acceptance_record")) or ""
        self.assertIn("repudiate_acceptance", doc)

    def test_every_named_reducer_consumer_really_calls_it(self):
        """And the list must not name a consumer that does not exist -- the mirror-image error."""
        import ast
        callers = set()
        for name in ("acceptance_ceremony.py", "lifecycle_state.py", "capability_invariants.py"):
            tree = ast.parse((_AGENTS_LIB / "external_write" / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                for call in ast.walk(node):
                    if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                            and call.func.id == "reduce_acceptance_log"):
                        callers.add(node.name)
        self.assertIn("repudiate_acceptance", callers)
        self.assertIn("_acceptance_record_exists", callers)


class RoundThreeTests(unittest.TestCase):

    def test_F12_the_consumer_list_completeness_is_actually_compared(self):
        """The docstring claims a test keeps its consumer list complete. Assert the claim by
        BUILDING the comparison it names: the set the doc enumerates must equal the set the AST
        finds, in BOTH directions. Checking that two known names are present cannot notice a
        sixth consumer, which is exactly what the sentence promised."""
        import ast, re
        d = _AGENTS_LIB / "external_write"
        src = (d / "acceptance_ceremony.py").read_text(encoding="utf-8")
        doc = ast.get_docstring(next(
            n for n in ast.parse(src).body
            if isinstance(n, ast.FunctionDef) and n.name == "is_valid_acceptance_record")) or ""
        named = set(re.findall(r"``(?:[a-z_]+\.)?([a-z_][a-z_0-9]*)``", doc))

        found = set()
        for name in ("acceptance_ceremony.py", "lifecycle_state.py", "capability_invariants.py"):
            for node in ast.walk(ast.parse((d / name).read_text(encoding="utf-8"))):
                if not isinstance(node, ast.FunctionDef):
                    continue
                for call in ast.walk(node):
                    if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                            and call.func.id == "reduce_acceptance_log"):
                        found.add(node.name)
        self.assertTrue(found, "the AST sweep must find something")
        self.assertEqual(
            found - named, set(),
            "a consumer of the reducer is not named in the list that claims to enumerate them")
        self.assertEqual(
            {n for n in named if n in found or n.startswith(("_read_", "check_", "repudiate_",
                                                             "_acceptance_"))} - found, set(),
            "the list names a consumer that does not call the reducer")

    def test_F13_a_bad_kind_never_leaves_authorization_revoked_with_no_exit(self):
        """The guard must sit BEFORE the irreversible half. Called with an undeclared kind, the
        transition must refuse having changed nothing -- not revoke the approval, fail to queue
        the exit, and strand the capability in the state this cut exists to close."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            with self.assertRaises(ValueError):
                lifecycle_state._revoke_and_queue_retrial(
                    root, frozenset({"acme_ledger_poster"}), "acme_ledger_poster",
                    kind="not_a_declared_kind", reason="r", suggested_next_step="s")
            self.assertIs(_entry(root, "acme_ledger_poster")["accepted"], True,
                          "authorization was revoked by a call that then refused")
            self.assertEqual(_queue(root), [],
                             "no exit was queued, so the revocation above would have stranded it")

    def test_F14_queuing_a_retrial_does_not_destroy_a_safety_entry_for_the_same_id(self):
        """The replace clause is idempotency for THIS writer's own entries. Dropping every entry
        sharing the mechanism_id also drops a live safety record written by someone else -- and
        that direction destroys evidence rather than a duplicate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            (Path(root) / "agents" / "handoffs").mkdir(parents=True, exist_ok=True)
            (Path(root) / lifecycle_state.MIGRATION_QUEUE_REL).write_text(json.dumps([{
                "mechanism_id": "acme_ledger_poster",
                "writer_relpath": "agents/acme_writer.py",
                "kind": "external_write_gate_violation",
                "reason": "flagged non-conformant with the external-write gate on upgrade",
                "status": "pending",
            }]), encoding="utf-8")

            lifecycle_state._queue_retrial_migration(
                root, "acme_ledger_poster",
                kind=lifecycle_state.RETRIAL_KIND_REPUDIATED,
                reason="r", suggested_next_step="s")

            kinds = [e.get("kind") for e in _queue(root)]
            self.assertIn("external_write_gate_violation", kinds,
                          "a live safety entry was destroyed by a retrial queue write")
            self.assertIn(lifecycle_state.RETRIAL_KIND_REPUDIATED, kinds)

    def test_F14b_a_second_retrial_still_replaces_its_own_prior_entry(self):
        """And the idempotency it was written for must survive: same id, same kind, one entry."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            for _ in range(2):
                lifecycle_state._queue_retrial_migration(
                    root, "acme_ledger_poster",
                    kind=lifecycle_state.RETRIAL_KIND_REPUDIATED,
                    reason="r", suggested_next_step="s")
            mine = [e for e in _queue(root)
                    if e.get("kind") == lifecycle_state.RETRIAL_KIND_REPUDIATED]
            self.assertEqual(len(mine), 1)

    def test_F14c_the_other_retrial_kind_for_the_same_id_is_also_replaced(self):
        """The two retrial kinds are this writer's own family: a capability that went stale and
        was then repudiated must not accumulate two competing exits."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _two_capability_project(tmp)
            lifecycle_state._queue_retrial_migration(
                root, "acme_ledger_poster", kind=lifecycle_state.RETRIAL_KIND_STALE,
                reason="r", suggested_next_step="s")
            lifecycle_state._queue_retrial_migration(
                root, "acme_ledger_poster", kind=lifecycle_state.RETRIAL_KIND_REPUDIATED,
                reason="r", suggested_next_step="s")
            self.assertEqual(len(_queue(root)), 1)
            self.assertEqual(_queue(root)[0]["kind"], lifecycle_state.RETRIAL_KIND_REPUDIATED)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
