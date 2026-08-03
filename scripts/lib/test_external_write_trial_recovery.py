"""Tests for TRIAL RECOVERY — `external_write.trial_recovery`.

The design this file exercises is the one that unblocked the trial protocol, and
it is worth stating before the tests because every assertion below serves it:

    A crash between apply-intent and apply-confirmed makes "did the mutation
    land?" unanswerable from the journal. Recovery DOES NOT TRY TO ANSWER IT. It
    converges on the invariant the trial exists to hold -- the surface equals the
    prior state -- rather than reconstructing history. For any unit that might
    have applied it runs `undo_one`, then `verify_undo_restored`, and that
    absolute post-condition gives the verdict.

So the four properties this file cares about most, each naming something that
would be a real defect:

  1. IT NEVER RE-APPLIES. Not "does not by convention" -- cannot: there is no
     `apply_one` call site in the module, and the journal's transition table makes
     `apply_intent` reachable only from `planned`. A trial that re-applied after a
     crash would be a live write the operator never consented to at that moment.

  2. IT NEVER ASKS WHETHER THE APPLY LANDED. The module does not evaluate
     `verify_apply_landed` anywhere. A recovery path that tried to reconstruct
     that history would be the design this one deliberately replaces.

  3. IT IS NEVER SILENTLY GREEN. A unit whose restoration cannot be established
     from OBSERVED evidence lands `recovery_required`, carrying the observed
     poststate as the diagnosis -- including when the observation itself fails.

  4. `recovery_required` HAS A REAL EXIT. A unit a prior attempt could not verify
     must be drivable again and must actually clear when the reversal works. A
     blocking state with no performable repair is the class of defect this whole
     protocol exists to remove, so opening one here would defeat it.

What these tests do NOT claim
-----------------------------
  * They do not claim anything about the two REAL operator adapters. Those live in
    the operator's estate and are not in this repository. The shipped-adapter test
    drives `adapters_gmail.GmailMessageTrashAdapter`; the fixture adapters
    reproduce contract SHAPES, not any operator's code.
  * They do not claim to kill a real OS process. The interruptions below raise a
    `BaseException` from inside `apply_one` / `undo_one`, which escapes every
    `except Exception` in the executor and therefore leaves exactly the durable
    record a kill at that instant would leave -- which is the thing under test.
    Real process-kill fault injection at every boundary is a separate concern with
    its own task.
  * They do not claim recovery can emit a proof. It cannot and must not: the
    apply-side observed evidence a proof carries was never in the durable record,
    and fabricating it would be forged evidence.

Fixtures (`_Base`, the surface, the two disjoint clients and the adapter shapes)
are imported from the trial executor's own test module rather than re-declared: a
second copy of a fixture that models the same contract shape is one more thing
that has to agree, and every crashed journal these tests recover is produced by
the REAL `trial_executor.run_trial`, never hand-built.

Uses stub clients only; no network. Every test writes into its own temp directory.
"""

import ast
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import capability_runner as cr  # noqa: E402
from external_write import scan, zones  # noqa: E402
from external_write import trial_executor as tx  # noqa: E402
from external_write import trial_journal as tj  # noqa: E402
from external_write import trial_recovery as trc  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    register_adapter, unregister_adapter,
)
from external_write.adapters_gmail import (  # noqa: E402
    OP_TRASH, GmailMessageTrashAdapter,
)
from external_write.operations import Operation  # noqa: E402
from external_write.read_facade import (  # noqa: E402
    get_read_facade_class, register_read_facade, unregister_read_facade,
)

from test_external_write_adapters_gmail import MockGmailService  # noqa: E402
from test_external_write_trial_executor import (  # noqa: E402
    APPLIED_LABEL, CAPABILITY_ID, _Base, _FixtureAdapter, _GmailReadOnlyClient,
    _entry, _receipt,
)

_EXTERNAL_WRITE_DIR = _AGENTS_LIB / "external_write"
_MODULE_PATH = _EXTERNAL_WRITE_DIR / "trial_recovery.py"


def _module_ast():
    return ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))


def _attribute_calls(tree, attr_name):
    """Every `<something>.<attr_name>(...)` call site in `tree`, as line numbers.
    AST, not text: a comment or a docstring mentioning the name is not a call."""
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr_name]


# ---------------------------------------------------------------------------
# Interruption fixtures -- each one leaves the journal in a DIFFERENT durable
# state, which is the whole point: recovery must give a verdict from each.
# ---------------------------------------------------------------------------

class _Interrupt(BaseException):
    """Not an `Exception`, deliberately. It escapes every `except Exception` in
    the executor, so what is on disk afterwards is exactly what a kill at that
    instant would have left -- no cleanup ran."""


class _KilledAfterTheMutationLanded(_FixtureAdapter):
    """The WORST case, and the one the design exists for: the mutation reached the
    live surface and then the process died before anything recorded it. The
    journal is left at `apply_intent`, which cannot say whether it landed."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def apply_one(self, raw_client, unit):
        super().apply_one(raw_client, unit)
        raise _Interrupt("killed after the vendor call returned")


class _KilledBeforeTheMutationLanded(_FixtureAdapter):
    """The other half of the ambiguity: the journal records the same
    `apply_intent`, but nothing was written. Recovery must converge here too --
    and its undo is then a no-op write over prior state, the disclosed residual."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def apply_one(self, raw_client, unit):
        raise _Interrupt("killed before the vendor call was issued")


class _KilledDuringTheUndo(_FixtureAdapter):
    """Killed after `undo_intent` was durable and after the reversal was issued,
    but before its outcome was recorded. The intent record is already on disk, so
    a resumed driver must NOT try to write it again."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def undo_one(self, raw_client, unit):
        super().undo_one(raw_client, unit)
        raise _Interrupt("killed after the reversal returned")


class _KilledBeforeTheUndoWasIssued(_FixtureAdapter):
    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def undo_one(self, raw_client, unit):
        raise _Interrupt("killed before the reversal was issued")


class _RecordingAdapter(_FixtureAdapter):
    """Records every mutation call it receives, so a test can assert what
    recovery did AND did not do -- above all that `apply_one` was never called."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def __init__(self, on_undo=None):
        super().__init__()
        self.applied = []
        self.undone = []
        self.undo_clients = []
        self.on_undo = on_undo

    def apply_one(self, raw_client, unit):
        self.applied.append(unit.unit_id)
        super().apply_one(raw_client, unit)

    def undo_one(self, raw_client, unit):
        self.undone.append(unit)
        self.undo_clients.append(raw_client)
        if self.on_undo is not None:
            self.on_undo(unit)
        super().undo_one(raw_client, unit)


class _NoOpUndoRecovery(_RecordingAdapter):
    """The reversal returns without restoring anything, so the observed evidence
    cannot show the unit back at its prior state."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def undo_one(self, raw_client, unit):
        self.undone.append(unit)
        self.undo_clients.append(raw_client)


class _RaisingUndoRecovery(_RecordingAdapter):
    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def undo_one(self, raw_client, unit):
        self.undone.append(unit)
        raise RuntimeError("the reversal call failed")


class _UnobservableRecovery(_RecordingAdapter):
    """The surface cannot be read at recovery time -- the disclosed read-path
    residual. The reversal must still be issued, and the verdict must still be
    fail-closed."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def verify_one(self, observer, unit):
        raise RuntimeError("the surface could not be read")


class _RecoveryBase(_Base):
    """Drives a real trial to a real interruption, then recovers from disk alone.

    `crash` returns nothing the recovery call uses except the trial id: every
    recovery below is given the trial id and the journal directory and nothing
    else -- no plan, no Operation, no effect units, no in-memory state -- because
    that is all a fresh process after a kill has.
    """

    def crash(self, adapter, *, n=1):
        """Run a trial that is interrupted, and return its trial id from disk."""
        self.register(adapter)
        op = self.op(n=n)
        with self.assertRaises(_Interrupt):
            self.run_trial(op)
        journals = sorted(Path(self.journal_dir).glob("*.json"))
        self.assertEqual(len(journals), 1,
                         "the interrupted trial must have left exactly one "
                         "durable journal")
        return journals[0].stem

    def reregister(self, adapter):
        """Replace the registered adapter for the recovery run.

        A fresh process after a kill re-imports the SAME adapter module, so the
        adapter the recovery run sees is normally the same class. These fixtures
        interrupt by raising from inside a mutation, which would interrupt the
        recovery's reversal too -- so where a test is about the RECOVERY rather
        than about a second failure, it swaps in the clean shape whose behaviour
        the real adapter would have on a run that is not being killed.
        """
        unregister_adapter(self.OP_KIND)
        register_adapter(self.OP_KIND, adapter)
        self.adapter = adapter
        return adapter

    def recover(self, trial_id, **kwargs):
        kwargs.setdefault("journal_dir", self.journal_dir)
        kwargs.setdefault("client", self.client)
        kwargs.setdefault("read_only_client", self.read_only_client)
        return trc.recover_trial(trial_id, **kwargs)

    def states(self, trial_id):
        return tj.load_trial_journal(
            trial_id, journal_dir=self.journal_dir).unit_states()


# ---------------------------------------------------------------------------
# 1. The convergence -- the design's own done-when
# ---------------------------------------------------------------------------

class ConvergenceTests(_RecoveryBase):

    def test_the_interruption_really_leaves_the_ambiguous_state(self):
        """Fixture precondition, asserted rather than assumed: without this the
        tests below would be recovering something other than the ambiguity."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        self.assertEqual(self.states(trial_id), {"r1": tj.STATE_APPLY_INTENT})
        self.assertEqual(self.surface.snapshot()["r1"], [APPLIED_LABEL],
                         "the mutation landed and nothing recorded it -- that is "
                         "the state the journal cannot resolve")

    def test_a_mid_apply_kill_converges_to_restored_and_verified(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        outcome = self.recover(trial_id)

        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RESTORED_VERIFIED})
        self.assertEqual(self.surface.snapshot()["r1"], ["OPEN"],
                         "the invariant the trial exists to hold: the surface "
                         "equals the prior state")
        self.assertEqual(outcome.recovery_required_unit_ids, ())
        self.assertEqual(outcome.restored_unit_ids, ("r1",))

    def test_an_apply_that_never_landed_also_converges(self):
        """The ambiguity is never resolved, and it never has to be: the same
        undo + absolute post-condition gives the verdict from the other side."""
        trial_id = self.crash(_KilledBeforeTheMutationLanded())
        self.assertEqual(self.states(trial_id), {"r1": tj.STATE_APPLY_INTENT})
        self.assertEqual(self.surface.snapshot()["r1"], ["OPEN"])

        outcome = self.recover(trial_id)

        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RESTORED_VERIFIED})
        self.assertEqual(self.surface.snapshot()["r1"], ["OPEN"])

    def test_the_no_op_write_residual_is_real_and_observable(self):
        """DISCLOSED RESIDUAL, asserted so it can never be quietly removed or
        quietly grown: when the apply never landed, recovery's undo writes prior
        value over prior value. The surface is unchanged, but it IS an API call --
        it consumes a ledger slot and appears in the vendor's own audit log. That
        is strictly safer than leaving a possibly-applied mutation in place, and
        it is disclosed rather than hidden."""
        trial_id = self.crash(_KilledBeforeTheMutationLanded())
        before = list(self.client.writes)

        self.recover(trial_id)

        self.assertEqual(len(self.client.writes), len(before) + 1,
                         "exactly ONE write is issued -- the reversal")
        self.assertEqual(self.client.writes[-1], ("r1", ["OPEN"]),
                         "and it writes the PRIOR value, so the surface is "
                         "unchanged by it")
        self.assertEqual(self.surface.snapshot()["r1"], ["OPEN"])

    def test_a_unit_at_apply_confirmed_is_driven_the_same_way(self):
        trial_id = self.crash(_KilledBeforeTheUndoWasIssued())
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_UNDO_INTENT},
                         "fixture precondition")
        self.reregister(_RecordingAdapter())

        outcome = self.recover(trial_id)
        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RESTORED_VERIFIED})

    def test_a_kill_during_the_undo_resumes_without_re_recording_the_intent(self):
        """A unit at `undo_intent` already HAS its write-ahead record on disk. The
        journal refuses to write it again, correctly, so a driver that called
        `record_undo_intent` unconditionally would raise instead of recovering.
        What must be confirmed is the durable STATE, not that a call was made."""
        trial_id = self.crash(_KilledDuringTheUndo())
        self.assertEqual(self.states(trial_id), {"r1": tj.STATE_UNDO_INTENT})
        self.reregister(_RecordingAdapter())

        outcome = self.recover(trial_id)

        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RESTORED_VERIFIED})

    def test_a_multi_unit_trial_converges_every_driven_unit(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded(), n=3)
        self.assertEqual(
            self.states(trial_id),
            {"r1": tj.STATE_APPLY_INTENT, "r2": tj.STATE_PLANNED,
             "r3": tj.STATE_PLANNED})

        outcome = self.recover(trial_id)

        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(self.surface.snapshot(),
                         {"r1": ["OPEN"], "r2": ["OPEN"], "r3": ["OPEN"]})
        self.assertEqual(outcome.never_applied_unit_ids, ("r2", "r3"))

    def test_recovery_is_idempotent(self):
        """Running the operator's exit twice must not be a hazard: the second run
        finds nothing outstanding, issues no write, and reports the same thing."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        first = self.recover(trial_id)
        writes_after_first = list(self.client.writes)

        second = self.recover(trial_id)

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(self.client.writes, writes_after_first,
                         "a second recovery of a settled trial must issue no "
                         "further write")
        self.assertEqual(second.restored_unit_ids, ())
        self.assertEqual(second.already_settled_unit_ids, ("r1",))


# ---------------------------------------------------------------------------
# 2. It never re-applies, and it never asks whether the apply landed
# ---------------------------------------------------------------------------

class NeverReAppliesTests(_RecoveryBase):

    def test_the_module_has_no_apply_one_call_site_at_all(self):
        sites = _attribute_calls(_module_ast(), "apply_one")
        self.assertEqual(sites, [],
                         "recovery converges by REVERSING. An apply call site "
                         "here would be a live write the operator never "
                         "consented to at that moment")

    def test_the_module_has_exactly_one_undo_one_call_site(self):
        self.assertEqual(len(_attribute_calls(_module_ast(), "undo_one")), 1,
                         "one mutation site, so there is one place to audit")

    def test_apply_one_is_never_called_at_run_time_either(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        adapter = self.reregister(_RecordingAdapter())

        self.recover(trial_id)

        self.assertEqual(adapter.applied, [],
                         "not one apply may be issued by a recovery")

    def test_the_module_never_evaluates_the_apply_landed_predicate(self):
        """The design does not try to answer 'did it land?'. A reference to the
        apply-side predicate would be the beginning of trying."""
        source = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        attrs = {node.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Attribute)}
        self.assertNotIn("APPLY_PREDICATE_NAME", names | attrs)
        self.assertNotIn("verify_apply_landed", names | attrs)
        self.assertEqual(_attribute_calls(tree, "verify_apply_landed"), [])
        self.assertNotIn("record_apply_intent", attrs)
        self.assertNotIn("record_apply_confirmed", attrs)

    def test_the_journal_refuses_a_re_apply_even_if_something_asked(self):
        """Belt and braces, and the braces are structural: even a future driver
        that tried could not record the intent, so the mutation could not be
        authorized by any record."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        journal = tj.load_trial_journal(trial_id, journal_dir=self.journal_dir)
        self.recover(trial_id)
        with self.assertRaises(tj.TrialJournalError):
            journal.record_apply_intent("r1")


# ---------------------------------------------------------------------------
# 3. Never silently green
# ---------------------------------------------------------------------------

class NeverSilentlyGreenTests(_RecoveryBase):

    def test_an_undo_that_does_not_restore_lands_recovery_required(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        self.reregister(_NoOpUndoRecovery())

        outcome = self.recover(trial_id)

        self.assertFalse(outcome.ok)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})
        self.assertEqual(outcome.recovery_required_unit_ids, ("r1",))
        self.assertIn(tx.REFUSAL_MARKER_NOT_RESTORED, outcome.summary)
        self.assertNotIn(tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, outcome.summary)

    def test_the_observed_poststate_is_carried_as_the_diagnosis(self):
        """`False` -> recovery-required CARRYING THE OBSERVED POSTSTATE. A durable
        blocking record that does not say what was actually seen hands the next
        reader a verdict instead of a diagnosis."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        self.reregister(_NoOpUndoRecovery())

        outcome = self.recover(trial_id)

        unit = next(u for u in outcome.units if u.unit_id == "r1")
        self.assertIsNotNone(unit.observed_poststate)
        self.assertEqual(unit.observed_poststate["observed_labels"],
                         [APPLIED_LABEL],
                         "the diagnosis must be what was SEEN on the surface")
        self.assertIs(unit.undo_restored, False)

    def test_an_undo_that_raises_lands_recovery_required(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        self.reregister(_RaisingUndoRecovery())

        outcome = self.recover(trial_id)

        self.assertFalse(outcome.ok)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})
        unit = next(u for u in outcome.units if u.unit_id == "r1")
        self.assertIsNone(unit.undo_restored,
                          "'the question could not be asked' is not 'the answer "
                          "is no'")

    def test_an_unobservable_surface_converges_then_lands_recovery_required(self):
        """DISCLOSED RESIDUAL: recovery needs the read path. If it is down the
        unit lands recovery-required, which is correct and fail-closed -- and the
        reversal is STILL issued first, because a possibly-applied mutation left in
        place is the harm the protocol exists to prevent."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        adapter = self.reregister(_UnobservableRecovery())

        outcome = self.recover(trial_id)

        self.assertFalse(outcome.ok)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})
        self.assertEqual([u.unit_id for u in adapter.undone], ["r1"],
                         "the reversal must still be issued")
        self.assertEqual(self.surface.snapshot()["r1"], ["OPEN"],
                         "and it must still have converged the surface")
        unit = next(u for u in outcome.units if u.unit_id == "r1")
        self.assertIsNone(unit.undo_restored)

    def test_a_reversal_whose_result_cannot_be_checked_AT_ALL_is_not_a_pass(self):
        """DISCLOSED RESIDUAL 2, and the path an earlier version of this file left
        entirely unexercised. It is distinct from "the observation raised": here the
        read path cannot be established in the first place, so no observation is
        ever attempted.

        Both halves must hold. The reversal IS still issued -- a unit that may be
        outstanding on the operator's live record is the harm this exists to
        prevent, and an absolute-state restore is safe to issue blind. And the
        verdict is NOT a pass: nothing may record a restore it did not observe.
        """
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        adapter = self.reregister(_RecordingAdapter())
        # The read path is gone entirely: no registered facade, and nothing in the
        # kernel declares a reader for this fixture op_kind either, so the
        # declaration topology cannot supply one.
        unregister_read_facade(self.OP_KIND)

        outcome = self.recover(trial_id)

        self.assertFalse(outcome.ok)
        self.assertEqual([u.unit_id for u in adapter.undone], ["r1"],
                         "the reversal must still be issued")
        self.assertEqual(self.surface.snapshot()["r1"], ["OPEN"],
                         "and it must still have converged the surface")
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED},
                         "but the result was never observed, so it is NOT "
                         "recorded as restored")
        unit = next(u for u in outcome.units if u.unit_id == "r1")
        self.assertIsNone(unit.undo_restored)
        self.assertIn("could not be checked", unit.reason)
        self.assertIn(tx.REFUSAL_MARKER_NOT_RESTORED, outcome.summary)

    def test_an_unresolvable_verification_lineage_also_lands_recovery_required(self):
        """The other producer of the same unverifiable verdict. The lineage the
        adapter's predicate is judged under resolves through the op_kind's
        registered contract and verifier, and a journal can outlive a registration
        change. Reversing blind and refusing to certify is the fail-closed answer;
        recording a restore under a lineage nothing backs is not."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        adapter = self.reregister(_RecordingAdapter())

        with mock.patch.object(
                trc, "trial_source_lineage",
                side_effect=tx.TrialExecutorError("no verifier is registered")):
            outcome = self.recover(trial_id)

        self.assertFalse(outcome.ok)
        self.assertEqual([u.unit_id for u in adapter.undone], ["r1"])
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})
        unit = next(u for u in outcome.units if u.unit_id == "r1")
        self.assertIn("lineage", unit.reason)

    def test_a_predicate_that_raises_is_never_read_as_restored(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())

        class _RaisingPredicate(_RecordingAdapter):
            UNDO_IS_ABSOLUTE_STATE_RESTORE = True

            def verify_undo_restored(self, evidence):
                raise RuntimeError("the predicate blew up")

        self.reregister(_RaisingPredicate())

        outcome = self.recover(trial_id)

        self.assertFalse(outcome.ok)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})

    def test_a_reason_is_always_recorded_in_the_journal(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        self.reregister(_NoOpUndoRecovery())

        self.recover(trial_id)

        record = tj.load_trial_journal(
            trial_id, journal_dir=self.journal_dir).read_record()
        entry = next(u for u in record["units"] if u["unit_id"] == "r1")
        last = entry["history"][-1]
        self.assertEqual(last["state"], tj.STATE_RECOVERY_REQUIRED)
        self.assertTrue(last.get("reason", "").strip(),
                        "a durable blocking record with no stated cause cannot "
                        "be acted on")


# ---------------------------------------------------------------------------
# 4. THE OPERATOR EXIT -- this cut must not open a third dead end
# ---------------------------------------------------------------------------

class OperatorExitTests(_RecoveryBase):

    def _stuck(self):
        """A trial with a unit durably `recovery_required` on the live surface."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        self.reregister(_NoOpUndoRecovery())
        outcome = self.recover(trial_id)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})
        return trial_id, outcome

    def test_a_recovery_required_unit_is_driven_again_and_CLEARS(self):
        """The whole self-consistency requirement in one test. The operator
        performs the named repair (the transient cause is gone) and the state
        actually clears -- it is not a record they are stuck with forever."""
        trial_id, _ = self._stuck()
        self.reregister(_RecordingAdapter())

        outcome = self.recover(trial_id)

        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RESTORED_VERIFIED})
        self.assertEqual(self.surface.snapshot()["r1"], ["OPEN"])
        self.assertEqual(outcome.recovery_required_unit_ids, ())

    def test_a_still_broken_unit_stays_recovery_required_rather_than_clearing(self):
        """The other direction, which is what makes the clearing meaningful: the
        repair only clears the state when it actually worked."""
        trial_id, _ = self._stuck()

        outcome = self.recover(trial_id)

        self.assertFalse(outcome.ok)
        self.assertEqual(self.states(trial_id),
                         {"r1": tj.STATE_RECOVERY_REQUIRED})

    def test_recovery_required_is_in_the_declared_driven_set(self):
        self.assertIn(tj.STATE_RECOVERY_REQUIRED, tj.RECOVERY_DRIVEN_STATES,
                      "a state a recovery run skips is a state nothing can "
                      "leave")

    def test_the_outcome_NAMES_the_command_that_leaves_the_state(self):
        """Prose promising a mechanism must NAME the mechanism. An operator told
        a unit needs attention, with no command, has been handed a verdict."""
        trial_id, outcome = self._stuck()
        command = trc.recovery_command(trial_id, journal_dir=self.journal_dir)

        self.assertIn(command, outcome.summary)
        self.assertIn(trc.RECOVERY_ENTRYPOINT_REL, command)
        self.assertIn(trial_id, command)
        self.assertEqual(outcome.next_command, command)

    def test_the_named_command_is_the_real_invocation_of_the_real_entrypoint(self):
        """The command must not merely mention a file. The file must exist, be the
        module under test, and the flags in the command must be the flags its own
        parser accepts."""
        trial_id, _ = self._stuck()
        command = trc.recovery_command(trial_id, journal_dir=self.journal_dir)

        self.assertTrue(
            (_AGENTS_LIB.parent.parent / trc.RECOVERY_ENTRYPOINT_REL).is_file()
            or _MODULE_PATH.is_file())
        argv = command.split()[2:]  # drop "python3 <path>"
        parsed, error = trc.parse_recovery_args(argv)
        self.assertIsNone(error, error)
        self.assertEqual(parsed["--trial-id"], trial_id)

    def test_the_trial_executors_refusal_names_the_same_command(self):
        """Single-sourced, so the later registry has ONE function to bind and the
        two surfaces cannot drift into naming different commands."""
        self.register(_NoOpUndoRecovery())
        outcome = self.run_trial(self.op())

        self.assertFalse(outcome.ok)
        self.assertIn(tx.REFUSAL_MARKER_NOT_RESTORED, outcome.refusal)
        self.assertIn(
            trc.recovery_command(outcome.trial_id, journal_dir=self.journal_dir),
            outcome.refusal,
            "the surface that announces the blocking state must name the exit")

    def test_the_command_is_a_single_paste_safe_line(self):
        trial_id, _ = self._stuck()
        command = trc.recovery_command(trial_id, journal_dir=self.journal_dir)
        self.assertNotIn("\n", command)
        self.assertNotIn("\r", command)

    def test_a_journal_dir_with_a_space_is_quoted(self):
        directory = str(self.root / "a directory with spaces")
        command = trc.recovery_command("trial-x", journal_dir=directory)
        self.assertNotIn("\n", command)
        self.assertIn("'", command,
                      "an unquoted path with a space would break the pasted "
                      "command into two arguments")

    def test_the_production_command_omits_the_default_journal_dir(self):
        """The operator's real invocation carries no flag they would have to
        understand: the default IS the production convention."""
        command = trc.recovery_command("trial-x")
        self.assertNotIn("--journal-dir", command)
        self.assertIn("--trial-id trial-x", command)


# ---------------------------------------------------------------------------
# 5. Write-ahead ordering, preserved at every new call site
# ---------------------------------------------------------------------------

class WriteAheadOrderingTests(_RecoveryBase):

    def test_the_undo_intent_is_durable_on_disk_before_the_reversal_is_issued(self):
        """Observed from INSIDE `undo_one`, read FRESH from disk -- i.e. at the
        instant a second kill would leave whatever is on the file as the only
        record. Not asserted afterwards, which would prove nothing about order."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        seen = []

        def on_undo(unit):
            fresh = tj.load_trial_journal(trial_id, journal_dir=self.journal_dir)
            seen.append((unit.unit_id, fresh.unit_state(unit.unit_id)))

        self.reregister(_RecordingAdapter(on_undo=on_undo))

        self.recover(trial_id)

        self.assertEqual(seen, [("r1", tj.STATE_UNDO_INTENT)])

    def test_the_ordering_holds_for_a_unit_that_was_already_at_undo_intent(self):
        trial_id = self.crash(_KilledDuringTheUndo())
        seen = []

        def on_undo(unit):
            fresh = tj.load_trial_journal(trial_id, journal_dir=self.journal_dir)
            seen.append(fresh.unit_state(unit.unit_id))

        self.reregister(_RecordingAdapter(on_undo=on_undo))

        self.recover(trial_id)

        self.assertEqual(seen, [tj.STATE_UNDO_INTENT])

    def test_a_unit_whose_intent_record_cannot_be_made_durable_is_not_reversed(self):
        """Fail-closed, and it ABORTS rather than degrading. If the durable record
        cannot be written at all, nothing can be recorded -- so continuing would
        issue reversals with no write-ahead record behind any of them, which is
        the one thing this protocol forbids. The journal's own error propagates
        unchanged because it already names the problem exactly."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        adapter = self.reregister(_RecordingAdapter())

        with mock.patch.object(tj.TrialJournal, "record_undo_intent",
                               side_effect=tj.TrialJournalError("disk full")):
            with self.assertRaises(tj.TrialJournalError):
                self.recover(trial_id)

        self.assertEqual(adapter.undone, [],
                         "no reversal may be issued when its authorizing record "
                         "is not on disk")
        self.assertEqual(self.states(trial_id)["r1"], tj.STATE_APPLY_INTENT,
                         "and the durable record is left exactly as it was")

    def test_an_intent_record_that_SILENTLY_does_not_land_still_blocks_the_reversal(self):
        """The case the raising test above cannot reach, and the one the durable
        re-read exists for: a transition call that RETURNS without the record
        having changed on disk. A driver that trusted the call rather than the
        durable state would issue a live reversal authorized by nothing.

        This is not a hypothetical shape -- it is what any future refactor that
        made a transition conditional, cached, or best-effort would look like from
        this function's side. So the guarantee is asserted against the END STATE on
        disk rather than against the call having been made.
        """
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        adapter = self.reregister(_RecordingAdapter())

        with mock.patch.object(tj.TrialJournal, "record_undo_intent",
                               return_value=None):
            outcome = self.recover(trial_id)

        self.assertFalse(outcome.ok)
        self.assertEqual(adapter.undone, [],
                         "the reversal must NOT be issued when the durable record "
                         "does not authorize it, however the transition behaved")
        self.assertEqual(self.states(trial_id)["r1"],
                         tj.STATE_RECOVERY_REQUIRED)
        unit = next(u for u in outcome.units if u.unit_id == "r1")
        self.assertIn(tj.STATE_APPLY_INTENT, unit.reason)
        self.assertIn("not on disk", unit.reason)


# ---------------------------------------------------------------------------
# 6. The credential split
# ---------------------------------------------------------------------------

class CredentialSplitTests(_RecoveryBase):

    def test_verify_one_receives_the_read_facade_and_never_the_write_client(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        adapter = self.reregister(_RecordingAdapter())
        adapter.observers.clear()

        self.recover(trial_id)

        self.assertTrue(adapter.observers)
        for observer in adapter.observers:
            self.assertIsNot(observer, self.client)
            self.assertIsNot(observer, self.read_only_client)
            self.assertFalse(hasattr(observer, "set_labels"),
                             "the write-capable method must not be reachable "
                             "through the observation facade")

    def test_undo_one_receives_the_write_client(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        adapter = self.reregister(_RecordingAdapter())

        self.recover(trial_id)

        self.assertTrue(adapter.undo_clients)
        for client in adapter.undo_clients:
            self.assertIs(client, self.client)

    def test_the_two_clients_cannot_be_transposed_at_the_call_site(self):
        """The one mistake with real consequences here -- handing the observer the
        write-capable client -- must not be expressible, not merely detectable."""
        tree = _module_ast()
        func = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "_converge_unit")
        kwonly = [a.arg for a in func.args.kwonlyargs]
        self.assertIn("write_client", kwonly)
        self.assertIn("facade", kwonly)
        with self.assertRaises(TypeError):
            trc._converge_unit(None, None, None, None, None, None, None)

    def test_the_module_never_calls_verify_one_itself(self):
        """It reuses the executor's single observation helper rather than opening
        a second `verify_one` call site, so there is no second place a write
        client could reach the observer."""
        self.assertEqual(_attribute_calls(_module_ast(), "verify_one"), [])


# ---------------------------------------------------------------------------
# 7. Recovery never produces a proof
# ---------------------------------------------------------------------------

class NoProofTests(_RecoveryBase):

    def test_no_proof_is_written_even_when_every_unit_is_restored(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        outcome = self.recover(trial_id)

        self.assertTrue(outcome.ok)
        self.assertFalse(self.proof_path().exists(),
                         "the apply-side observed evidence a proof carries was "
                         "never in the durable record; fabricating it would be "
                         "forged evidence")
        self.assertFalse(hasattr(outcome, "proof_path"))

    def test_the_module_reaches_for_no_proof_machinery_at_all(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)}
        called |= {node.func.id for node in ast.walk(tree)
                   if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name)}
        for banned in ("validate_copy_run_proof", "copy_run_proof_path",
                       "run_trial", "authorize_operation", "open_trial_journal"):
            self.assertNotIn(banned, called,
                             f"recovery must not call {banned}")


# ---------------------------------------------------------------------------
# 8. Fail-closed refusals -- before anything external is touched
# ---------------------------------------------------------------------------

class FailClosedTests(_RecoveryBase):

    def test_an_absent_journal_refuses_and_never_reads_as_nothing_applied(self):
        with self.assertRaises(tj.TrialJournalError):
            self.recover("trial-does-not-exist")

    def test_a_malformed_journal_refuses(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        path = Path(self.journal_dir) / f"{trial_id}.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(tj.TrialJournalError):
            self.recover(trial_id)

    def test_a_journal_recording_a_non_trial_target_is_refused(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        path = Path(self.journal_dir) / f"{trial_id}.json"
        import json as _json
        record = _json.loads(path.read_text(encoding="utf-8"))
        record["resolved_target"] = "affirmative_live"
        path.write_text(_json.dumps(record), encoding="utf-8")

        with self.assertRaises(trc.TrialRecoveryError) as ctx:
            self.recover(trial_id)
        self.assertIn("affirmative_live", str(ctx.exception))

    def test_no_registered_adapter_refuses_before_anything_is_touched(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        unregister_adapter(self.OP_KIND)
        writes = list(self.client.writes)

        with self.assertRaises(trc.TrialRecoveryError):
            self.recover(trial_id)
        self.assertEqual(self.client.writes, writes)

    def test_no_write_client_refuses_before_anything_is_touched(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        with self.assertRaises(trc.TrialRecoveryError) as ctx:
            self.recover(trial_id, client=None)
        self.assertIn("reverse", str(ctx.exception).lower())

    def test_the_refusal_never_claims_nothing_is_outstanding(self):
        """A pre-mutation refusal must not be mistakable for an all-clear -- the
        unit it could not reach may still be changed on the live record."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        with self.assertRaises(trc.TrialRecoveryError) as ctx:
            self.recover(trial_id, client=None)
        self.assertNotIn(tx.REFUSAL_MARKER_NOTHING_OUTSTANDING,
                         str(ctx.exception))


# ---------------------------------------------------------------------------
# 9. Reconstruction from the capsules on disk
# ---------------------------------------------------------------------------

class CapsuleReconstructionTests(_RecoveryBase):

    def test_the_reversed_unit_is_rebuilt_from_the_capsule_not_from_a_re_plan(self):
        """Re-running `plan()` after a crash would be a SECOND observation of a
        surface the trial has already mutated. The capsule exists so the unit can
        be reversed from disk alone."""
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        journal = tj.load_trial_journal(trial_id, journal_dir=self.journal_dir)
        capsule = journal.recovery_capsule("r1")

        adapter = _RecordingAdapter()

        def boom(params):
            raise AssertionError("plan() must never run on the recovery path")

        adapter.plan = boom
        self.reregister(adapter)

        self.recover(trial_id)

        self.assertEqual(len(adapter.undone), 1)
        unit = adapter.undone[0]
        self.assertEqual(unit.unit_id, "r1")
        self.assertEqual(unit.undo_ref, capsule[tj.CAPSULE_KEY_UNDO_REF])
        self.assertEqual(unit.target_ref, capsule[tj.CAPSULE_KEY_TARGET_REF])

    def test_the_module_never_calls_plan(self):
        self.assertEqual(_attribute_calls(_module_ast(), "plan"), [])

    def test_the_module_never_reaches_for_pickle(self):
        tree = _module_ast()
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for banned in ("pickle", "marshal", "shelve"):
            self.assertNotIn(banned, imported)


# ---------------------------------------------------------------------------
# 10. Untouched units
# ---------------------------------------------------------------------------

class UntouchedUnitsTests(_RecoveryBase):

    def test_a_unit_still_planned_is_never_reversed(self):
        """The apply-intent record is fsynced before `apply_one`, so a unit at
        `planned` was provably never applied. Reversing it would be a write with
        nothing to undo."""
        trial_id = self.crash(_KilledAfterTheMutationLanded(), n=3)
        adapter = self.reregister(_RecordingAdapter())

        outcome = self.recover(trial_id)

        self.assertEqual([u.unit_id for u in adapter.undone], ["r1"])
        self.assertEqual(self.states(trial_id)["r2"], tj.STATE_PLANNED)
        self.assertEqual(outcome.never_applied_unit_ids, ("r2", "r3"))

    def test_a_unit_already_restored_verified_is_never_reversed_again(self):
        self.register(_RecordingAdapter())
        outcome = self.run_trial(self.op(n=2))
        self.assertTrue(outcome.ok, outcome.refusal)
        self.adapter.undone.clear()

        recovered = self.recover(outcome.trial_id)

        self.assertTrue(recovered.ok)
        self.assertEqual(self.adapter.undone, [])
        self.assertEqual(recovered.already_settled_unit_ids, ("r1", "r2"))

    def test_a_planned_unit_is_never_reported_as_needing_recovery(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded(), n=2)
        outcome = self.recover(trial_id)
        self.assertNotIn("r2", outcome.recovery_required_unit_ids)

    def test_the_three_recovery_buckets_PARTITION_every_declared_unit_state(self):
        """The buckets must be a TOTAL partition, checked structurally rather than
        by inspection, because the alternative is a negative catch-all: "anything
        not driven and not settled was never applied". A negative bucket silently
        absorbs a state added later, and the state it absorbs is reported as
        harmless. Mirrors `test_every_state_is_classified_exactly_once` one screen
        away in the journal's own suite, for the same reason.
        """
        buckets = (tj.RECOVERY_DRIVEN_STATES,
                   tj.RECOVERY_NEVER_APPLIED_STATES,
                   tj.RECOVERY_SETTLED_STATES)
        union = set()
        for bucket in buckets:
            self.assertEqual(union & set(bucket), set(),
                             "a state may belong to exactly ONE bucket -- two "
                             "dispositions for one state is two answers")
            union |= set(bucket)
        self.assertEqual(union, set(tj.TRIAL_UNIT_STATES),
                         "every declared unit state must be classified; an "
                         "unclassified state has no disposition, and a state "
                         "with no disposition is one nobody decided about")

    def test_an_UNCLASSIFIED_state_holding_a_live_mutation_REFUSES(self):
        """The fail-open this closes, reproduced exactly.

        A future state added to the journal and classified into `OUTCOME_STATES`
        satisfies the journal's own exhaustiveness guard, so nothing there fires.
        If recovery buckets by "not driven and not settled", a unit sitting in that
        new state -- with a live, unreversed mutation on the operator's surface --
        is reported as never applied, the run returns ok, and the operator is told
        nothing is outstanding. Silence must REFUSE, not default to the benign
        answer.
        """
        seventh = "undo_confirmed"
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        self.assertEqual(self.surface.snapshot()["r1"], [APPLIED_LABEL],
                         "fixture precondition: the mutation is live")

        path = Path(self.journal_dir) / f"{trial_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["units"][0]["state"] = seventh
        path.write_text(json.dumps(record), encoding="utf-8")

        # The journal must ACCEPT the record, or this test would be measuring the
        # record validator instead of the bucket. Classified as an outcome state,
        # exactly as a real future addition would be.
        with mock.patch.object(tj, "TRIAL_UNIT_STATES",
                               tj.TRIAL_UNIT_STATES + (seventh,)), \
             mock.patch.object(tj, "OUTCOME_STATES",
                               tj.OUTCOME_STATES + (seventh,)), \
             mock.patch.dict(tj.LEGAL_TRANSITIONS,
                             {seventh: (tj.STATE_RESTORED_VERIFIED,)}):
            self.assertEqual(
                tj.load_trial_journal(
                    trial_id, journal_dir=self.journal_dir).unit_states(),
                {"r1": seventh}, "fixture precondition: the record validates")

            with self.assertRaises(trc.TrialRecoveryError) as ctx:
                self.recover(trial_id)

        message = str(ctx.exception)
        self.assertIn(seventh, message,
                      "the refusal must NAME the state it does not recognize")
        self.assertIn("r1", message)
        self.assertNotIn(tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, message,
                         "a unit in an unrecognized state may be holding a live "
                         "mutation, so nothing may claim otherwise")
        self.assertEqual(self.surface.snapshot()["r1"], [APPLIED_LABEL],
                         "and it refuses BEFORE touching anything")


# ---------------------------------------------------------------------------
# 11. The read-facade resolution is single-sourced, and works in a fresh process
# ---------------------------------------------------------------------------

class DeclaredReadFacadeResolutionTests(unittest.TestCase):
    """A fresh process after a crash has imported NO read-facade module: nothing
    in production imports one at module scope, and the registry that
    `build_read_facade` resolves from is populated only by that import. So a
    recovery command that relied on the registry already being warm would refuse
    on every real invocation -- and a unit could then never leave
    `recovery_required`, which is the dead end this cut exists to close.

    The resolution (op_kind -> declaring module -> import -> registry) already
    existed inside `capability_runner.resolve_read_facade_class`, keyed to a
    capability id. It is now ONE function with two callers rather than a second
    copy here.
    """

    def test_the_resolution_has_exactly_one_implementation(self):
        source = (_EXTERNAL_WRITE_DIR / "capability_runner.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        resolver = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef)
                        and n.name == "resolve_read_facade_class")
        called = {node.func.id for node in ast.walk(resolver)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name)}
        self.assertIn("import_declared_read_facade", called,
                      "the capability-facing resolver must delegate, not carry "
                      "its own copy")
        self.assertNotIn("build_topology", called,
                         "the topology lookup belongs to the one shared "
                         "implementation")

        recovery = _module_ast()
        recovery_called = {node.func.id for node in ast.walk(recovery)
                           if isinstance(node, ast.Call)
                           and isinstance(node.func, ast.Name)}
        self.assertIn("import_declared_read_facade", recovery_called)
        self.assertNotIn("build_topology", recovery_called)

    def test_the_shared_resolver_returns_the_registered_class_for_an_op_kind(self):
        facade_cls = cr.import_declared_read_facade(OP_TRASH)
        from external_write.read_facade import ReadFacade
        self.assertTrue(issubclass(facade_cls, ReadFacade))

    def test_an_op_kind_nothing_declares_is_refused_not_none(self):
        with self.assertRaises(Exception) as ctx:
            cr.import_declared_read_facade("nothing.declares.this")
        self.assertNotIsInstance(ctx.exception, AssertionError)


class ColdRegistryRecoveryTests(_Base):
    """THE test that makes the operator exit real rather than nominal.

    Every other test in this file runs in a process where a read facade is already
    registered -- because the fixtures register one, and because importing the
    executor's test module imports the shipped Gmail facade. A real recovery
    command has neither: it is a fresh process, and nothing in production imports a
    read-facade module at module scope.

    So this test EMPTIES the registry for the op_kind first. If recovery could not
    populate it, the observation would fail on every real invocation, every driven
    unit would land `recovery_required`, and re-running would never clear it -- a
    durable blocking state with no performable repair, which is exactly the dead
    end this protocol exists to remove. A test suite that only ever exercised the
    warm path would have been green and blind to that.
    """

    OP_KIND = OP_TRASH
    SURFACE = "gmail"

    def setUp(self):
        super().setUp()
        self.service = MockGmailService({"m1": {"INBOX", "IMPORTANT"}})
        self.gmail_read_only = _GmailReadOnlyClient(self.service)
        self.before = {mid: sorted(labels)
                       for mid, labels in self.service.messages.items()}

    def test_recovery_observes_the_surface_with_an_EMPTY_facade_registry(self):
        class _KilledTrashAdapter(GmailMessageTrashAdapter):
            UNDO_IS_ABSOLUTE_STATE_RESTORE = True

            def apply_one(self, raw_client, unit):
                super().apply_one(raw_client, unit)
                raise _Interrupt("killed after the vendor call returned")

        register_adapter(OP_TRASH, _KilledTrashAdapter())
        self.addCleanup(unregister_adapter, OP_TRASH)
        self.addCleanup(register_adapter, OP_TRASH, GmailMessageTrashAdapter())

        op = Operation(
            surface="gmail", object_id="m1", field="labels",
            new_value="TRASH", op_kind=OP_TRASH, batch_id="trial-batch",
            params={"messages": [{"message_id": "m1",
                                  "prior_label_ids": self.before["m1"]}]})
        with self.assertRaises(_Interrupt):
            tx.run_trial(
                op, _receipt(op), capability_id=CAPABILITY_ID,
                capability_module_paths=("agents/capabilities/x_capability.py",),
                client=self.service, read_only_client=self.gmail_read_only,
                descriptor_set=[_entry(id="gmail")], cap_ledger=self.ledger,
                paused_root=self.paused_root, journal_dir=self.journal_dir,
                proof_dir=self.proof_dir, lib_dir=str(_EXTERNAL_WRITE_DIR))

        trial_id = sorted(Path(self.journal_dir).glob("*.json"))[0].stem
        unregister_adapter(OP_TRASH)
        register_adapter(OP_TRASH, GmailMessageTrashAdapter())

        # THE FRESH-PROCESS CONDITION, and it takes two steps rather than one --
        # which the first draft of this test got wrong in an instructive way.
        # Emptying the registry alone is not a fresh process: the declaring module
        # is still in `sys.modules`, so re-importing it is a no-op and its
        # module-scope registration never re-runs. The resolver then correctly
        # reported "loaded, but registered nothing", and the test read as a product
        # defect when it was an unfaithful fixture. A real fresh interpreter has
        # neither the registry entry NOR the cached module, so both go.
        registered = get_read_facade_class(OP_TRASH)
        self.assertIsNotNone(registered, "fixture precondition")
        unregister_read_facade(OP_TRASH)
        self.addCleanup(register_read_facade, OP_TRASH, registered)
        cached = sys.modules.pop("external_write.read_facades_gmail", None)
        self.assertIsNotNone(cached, "fixture precondition: it was imported")
        self.addCleanup(sys.modules.setdefault,
                        "external_write.read_facades_gmail", cached)
        self.assertIsNone(get_read_facade_class(OP_TRASH))

        outcome = trc.recover_trial(
            trial_id, journal_dir=self.journal_dir, client=self.service,
            read_only_client=self.gmail_read_only)

        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(
            tj.load_trial_journal(trial_id,
                                  journal_dir=self.journal_dir).unit_states(),
            {"m1": tj.STATE_RESTORED_VERIFIED},
            "the verdict must rest on a real observation, which means the reader "
            "had to be resolved and imported by the recovery run itself")
        self.assertEqual({mid: sorted(labels)
                          for mid, labels in self.service.messages.items()},
                         self.before)
        self.assertIsNotNone(get_read_facade_class(OP_TRASH),
                             "and the registry it needed is the one it populated")


# ---------------------------------------------------------------------------
# 12. Enrollment -- a module nothing ships is a module nothing can run
# ---------------------------------------------------------------------------

class EnrolmentTests(unittest.TestCase):

    def test_the_module_is_enrolled_as_sealed_kernel(self):
        self.assertIn("trial_recovery.py", zones.SEALED_KERNEL_MODULE_PATHS)

    def test_the_module_scans_clean_under_the_bypass_scanner(self):
        violations = scan.scan_paths([str(_MODULE_PATH)])
        self.assertEqual(violations, [], [str(v) for v in violations])

    def test_without_that_membership_the_module_would_be_flagged(self):
        """The counterfactual: the membership is load-bearing, not decorative.
        Scanned as CAPABILITY the module trips the CAPABILITY-zone-ONLY module
        boundary rules on its ordinary internal kernel imports."""
        without = frozenset(p for p in zones.SEALED_KERNEL_MODULE_PATHS
                            if p != "trial_recovery.py")
        kinds = {v.kind for v in scan.scan_paths(
            [str(_MODULE_PATH)], allowed_root=str(_EXTERNAL_WRITE_DIR),
            sealed_kernel_paths=without)}
        self.assertTrue(kinds, "the membership must trip something")
        self.assertIn("sealed_kernel_import", kinds)

    def test_capability_zone_code_may_not_import_the_recovery_module(self):
        self.assertNotIn(
            "trial_recovery",
            scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES,
            "recovery drives real writes against the operator's live record; a "
            "capability has no business driving them")

    def test_the_module_is_enrolled_in_the_emitted_lib_file_set(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import agent_emitter
        self.assertIn("trial_recovery.py",
                      agent_emitter._EXTERNAL_WRITE_LIB_FILES)


# ---------------------------------------------------------------------------
# 13. The CLI -- the operator-invocable entrypoint itself
# ---------------------------------------------------------------------------

class CliTests(unittest.TestCase):

    def test_a_missing_trial_id_is_a_usage_error_not_a_guess(self):
        parsed, error = trc.parse_recovery_args([])
        self.assertIsNone(parsed)
        self.assertIn("--trial-id", error)

    def test_an_unrecognized_flag_refuses_rather_than_being_ignored(self):
        parsed, error = trc.parse_recovery_args(
            ["--trial-id", "t", "--force"])
        self.assertIsNone(parsed)
        self.assertIn("--force", error)

    def test_a_flag_with_no_value_refuses(self):
        parsed, error = trc.parse_recovery_args(["--trial-id"])
        self.assertIsNone(parsed)
        self.assertIsNotNone(error)

    def test_a_valid_invocation_parses(self):
        parsed, error = trc.parse_recovery_args(
            ["--trial-id", "trial-1", "--journal-dir", "d"])
        self.assertIsNone(error)
        self.assertEqual(parsed["--trial-id"], "trial-1")
        self.assertEqual(parsed["--journal-dir"], "d")

    def test_the_exit_codes_follow_this_packages_convention(self):
        self.assertEqual(trc.EXIT_RESTORED, 0)
        self.assertEqual(trc.EXIT_RECOVERY_REQUIRED, 1)
        self.assertEqual(trc.EXIT_BAD_ARGS, 2)

    def test_the_entrypoint_relpath_names_this_module(self):
        self.assertTrue(trc.RECOVERY_ENTRYPOINT_REL.endswith(
            "external_write/trial_recovery.py"))

    def test_the_entrypoint_relpath_agrees_with_the_emitters_lib_destination(self):
        """The `agents/lib/` half of the path was unpinned, and it is the half that
        matters most: if the emitted lib destination ever moves, the command the
        operator is told to run points at a file that does not exist — a named
        repair that cannot be performed, which is the failure this whole state's
        exit exists to avoid.

        The kernel cannot import the build-side constant (it ships into the
        operator's project, where `agent_emitter` does not exist), so the agreement
        is pinned here at build time instead of coupled at run time."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import agent_emitter
        self.assertEqual(
            trc.RECOVERY_ENTRYPOINT_REL,
            f"{agent_emitter._EXTERNAL_WRITE_LIB_REL}/trial_recovery.py")


class TheEntrypointActuallyRunsTests(_RecoveryBase):
    """The difference between "an exit exists" and "an exit runs".

    Everything above calls `recover_trial` in-process, which proves the logic and
    proves nothing about the command an operator is told to paste. This drives the
    real `__main__` as a REAL SUBPROCESS against a REAL journal on disk -- a fresh
    interpreter, with none of this test module's imports, registrations or sys.path
    manipulation. It is the only test here that exercises the argv parse, the
    adapter-registration import inside `__main__`, the journal load, the exit code
    and the operator-facing output as one chain.

    A named repair that has never been executed is a claim, not a repair.
    """

    def test_the_real_command_runs_loads_the_journal_and_refuses_in_plain_language(self):
        trial_id = self.crash(_KilledAfterTheMutationLanded())
        writes_before = list(self.client.writes)

        # Exactly the command the operator is handed, with only the journal
        # directory pointed at this test's own tree.
        command = trc.recovery_command(trial_id, journal_dir=self.journal_dir)
        argv = shlex.split(command)
        self.assertEqual(argv[0], "python3")
        result = subprocess.run(
            [sys.executable, str(_MODULE_PATH)] + argv[2:],
            capture_output=True, text=True, cwd=str(_AGENTS_LIB.parents[2]))

        output = result.stdout + result.stderr
        # A fresh process registers only the SHIPPED adapters, so this fixture
        # op_kind has none -- which is the right thing to observe here: the chain
        # ran all the way to a domain refusal about the journal it really loaded.
        self.assertEqual(result.returncode, trc.EXIT_RECOVERY_REQUIRED,
                         f"exit {result.returncode}; output: {output}")
        self.assertIn(self.OP_KIND, output)
        self.assertIn("r1", output, "it must name the unit still needing "
                                    "attention rather than refusing abstractly")
        self.assertNotIn("Traceback", output,
                         "a non-technical operator reads this output")
        self.assertEqual(self.client.writes, writes_before,
                         "a refusal before anything is touched must touch nothing")
        self.assertEqual(self.states(trial_id)["r1"], tj.STATE_APPLY_INTENT)

    def test_a_usage_error_exits_two_from_the_real_process(self):
        result = subprocess.run(
            [sys.executable, str(_MODULE_PATH), "--trial-id", "t", "--force"],
            capture_output=True, text=True, cwd=str(_AGENTS_LIB.parents[2]))
        self.assertEqual(result.returncode, trc.EXIT_BAD_ARGS)
        self.assertIn("--force", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


# The fixture operator project's adapter module. File-backed on both sides, so the
# "live surface" survives a hard process kill and a separate process can observe
# it -- which is the whole point: an in-memory surface cannot model a crash.
_FIXTURE_OP_KIND = "fixture.recovery.set_exact_labels"

_FIXTURE_ADAPTER_SOURCE = '''\
"""A trial-eligible adapter over a JSON file, for driving the real recovery
entrypoint in a real operator project. Not a claim about any shipped or
operator-authored adapter -- it reproduces the CONTRACT SHAPE only."""
import json
import os
from pathlib import Path

from external_write.adapter_registry import register_adapter
from external_write.contracts import (
    OPERATION_CONTRACTS, OperationContract, WRITE_AFFECTING_MODULES,
    register_contract,
)
from external_write.operations import EffectUnit

OP_KIND = "fixture.recovery.set_exact_labels"
SURFACE_PATH = Path(__file__).resolve().parents[3] / "surface.json"
KILL_MARKER = Path(__file__).resolve().parents[3] / "kill_on_apply"


def _read():
    return json.loads(SURFACE_PATH.read_text(encoding="utf-8"))


def _write(state):
    SURFACE_PATH.write_text(json.dumps(state), encoding="utf-8")


class _FileWriteClient:
    def set_labels(self, unit_id, labels):
        state = _read()
        state[unit_id] = list(labels)
        _write(state)


class _FileReadOnlyClient:
    def get_state(self, unit_id):
        return {"unit_id": unit_id, "labels": sorted(_read().get(unit_id, ()))}


class FixtureRecoveryAdapter:
    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def build_write_client(self, op):
        return _FileWriteClient()

    def build_read_only_client(self, op):
        return _FileReadOnlyClient()

    def plan(self, params):
        return [
            EffectUnit(unit_id=r["unit_id"],
                       target_ref={"unit_id": r["unit_id"]},
                       undo_ref={"unit_id": r["unit_id"],
                                 "prior_labels": list(r["prior_labels"])})
            for r in (params or {}).get("records", [])
        ]

    def apply_one(self, raw_client, unit):
        raw_client.set_labels(unit.target_ref["unit_id"], ["ARCHIVED"])
        if KILL_MARKER.exists():
            # A HARD kill, not an exception: no handler runs, nothing unwinds,
            # nothing is flushed. Exactly what the journal has to survive.
            os._exit(137)

    def undo_one(self, raw_client, unit):
        raw_client.set_labels(unit.undo_ref["unit_id"],
                              unit.undo_ref["prior_labels"])

    def verify_one(self, observer, unit):
        observed = observer.get_state(unit.unit_id)["labels"]
        prior = sorted((unit.undo_ref or {}).get("prior_labels", ()))
        return {"unit_id": unit.unit_id, "observed_labels": observed,
                "applied": observed == ["ARCHIVED"],
                "matches_prestate": observed == prior}

    def verify_apply_landed(self, evidence):
        return bool(evidence.poststate.get("applied"))

    def verify_undo_restored(self, evidence):
        return bool(evidence.poststate.get("matches_prestate"))


if OP_KIND not in OPERATION_CONTRACTS:
    register_contract(OperationContract(
        op_kind=OP_KIND, writes=("labels",), produces=(),
        dependency_set=WRITE_AFFECTING_MODULES,
        verifier_set=("prestate_snapshot_diff_v1",),
        introduces_persistent_binding=False,
        risk_class="sensitive_data", requires_accepted_phase=True,
        blast_radius_cap=25, read_only_scope="fixture.readonly"))

register_adapter(OP_KIND, FixtureRecoveryAdapter())
'''

_FIXTURE_FACADE_SOURCE = '''\
"""The read-only reader the declaration topology resolves for the fixture
op_kind. Its own module, declaring at top level, exactly as the shipped readers
do -- nothing imports it, which is the condition recovery has to survive."""
from external_write.read_facade import ReadFacade, register_read_facade

OP_KIND = "fixture.recovery.set_exact_labels"


class FixtureRecoveryReadFacade(ReadFacade):
    read_methods = ("get_state",)

    def get_state(self, unit_id):
        return self._read("get_state", unit_id)


register_read_facade(OP_KIND, FixtureRecoveryReadFacade)
'''

_TRIAL_DRIVER_SOURCE = '''\
"""Drives one real trial in the operator project, to be killed mid-apply."""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "agents" / "lib"))

import external_write.registered_adapters  # noqa: F401

# The TRIAL path needs a warm read-facade registry and does not warm it itself:
# in the real flow the proposal step (`capability_runner`) has already imported
# the declaring module by the time a trial runs. This driver stands in for that.
# The RECOVERY entrypoint deliberately does NOT get this line -- it runs in a
# fresh process where nothing has, which is the condition it has to survive.
import external_write.read_facades_fixturerecovery  # noqa: F401
from external_write import trial_executor as tx
from external_write.lifecycle_test_fixtures import hermetic_paused_mechanisms
from external_write.operations import Operation
from external_write.write_gate import InvocationLedger

OP_KIND = "fixture.recovery.set_exact_labels"
op = Operation(surface="fixture_surface", object_id="r1", field="labels",
               new_value="ARCHIVED", op_kind=OP_KIND, batch_id="b1",
               params={"records": [{"unit_id": "r1", "prior_labels": ["OPEN"]}]})
receipt = {
    "approved_operation_digest":
        hashlib.sha256(op.canonical_repr().encode()).hexdigest(),
    "expires_at": (datetime.now(timezone.utc)
                   + timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
entry = {"id": "fixture_surface", "name": "fixture_surface",
         "action_class": "modify", "risk_class": "sensitive_data",
         "recovery_profile_ref": None, "declared_test_target": "native_undo",
         "blast_radius_cap": 25, "accepted": False}

with hermetic_paused_mechanisms() as paused_root:
    outcome = tx.run_trial(
        op, receipt, capability_id="fixture_capability",
        capability_module_paths=("agents/capabilities/fixture_capability.py",),
        descriptor_set=[entry], cap_ledger=InvocationLedger(),
        paused_root=paused_root, journal_dir="security/trial_runs",
        proof_dir="agents/handoffs")
print(json.dumps({"ok": outcome.ok, "refusal": outcome.refusal,
                  "trial_id": outcome.trial_id}))
'''


class TheOperatorProjectHappyPathTests(unittest.TestCase):
    """The success branch of the operator's only repair, driven end to end.

    Every other subprocess test here ends non-zero (a domain refusal, a usage
    error), so the lines that print the success summary and exit `EXIT_RESTORED`
    had no automated coverage — and a never-exercised path is a latent failure, on
    this project's own standing lesson. This one is the happy path of the exit from
    a blocking state, which is the last place a paste-safety or exit-code
    regression should be allowed to hide.

    It is a REAL operator project: the emitted lib copied into it, a file-backed
    trial-eligible adapter enrolled through the shipped `operator_adapters.json`
    mechanism (so a fresh process registers it, with no import this test controls),
    a reader in its own module that nothing imports, and a hard `os._exit(137)`
    from inside `apply_one` — not a `BaseException`, so no handler runs and nothing
    unwinds. Then the production-form command, from the project root, with no
    flags.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        lib = self.root / "agents" / "lib" / "external_write"
        shutil.copytree(
            _EXTERNAL_WRITE_DIR, lib,
            ignore=shutil.ignore_patterns("test_*.py", "__pycache__"))
        (self.root / "agents" / "lib" / "external_write" / "__init__.py").touch(
            exist_ok=True)
        (lib / "adapters_fixturerecovery.py").write_text(
            _FIXTURE_ADAPTER_SOURCE, encoding="utf-8")
        (lib / "read_facades_fixturerecovery.py").write_text(
            _FIXTURE_FACADE_SOURCE, encoding="utf-8")
        (lib / "operator_adapters.json").write_text(
            json.dumps(["adapters_fixturerecovery"]), encoding="utf-8")
        (self.root / "drive_trial.py").write_text(
            _TRIAL_DRIVER_SOURCE, encoding="utf-8")
        (self.root / "surface.json").write_text(
            json.dumps({"r1": ["OPEN"]}), encoding="utf-8")
        (self.root / "security" / "trial_runs").mkdir(parents=True)
        (self.root / "agents" / "handoffs").mkdir(parents=True)

    def surface(self):
        return json.loads(
            (self.root / "surface.json").read_text(encoding="utf-8"))

    def journal_states(self, trial_id):
        record = json.loads(
            (self.root / "security" / "trial_runs" / f"{trial_id}.json")
            .read_text(encoding="utf-8"))
        return {u["unit_id"]: u["state"] for u in record["units"]}

    def run_recovery(self, trial_id):
        """The command in its PRODUCTION FORM: rendered by the shipped function,
        run from the project root, no flags the operator would have to understand."""
        command = trc.recovery_command(trial_id)
        self.assertNotIn("--journal-dir", command,
                         "the production invocation must carry no extra flag")
        argv = shlex.split(command)
        return subprocess.run([sys.executable] + argv[1:], capture_output=True,
                              text=True, cwd=str(self.root))

    def test_the_rendered_command_restores_a_hard_killed_trial_and_exits_zero(self):
        (self.root / "kill_on_apply").touch()
        killed = subprocess.run([sys.executable, "drive_trial.py"],
                                capture_output=True, text=True,
                                cwd=str(self.root))
        self.assertEqual(killed.returncode, 137,
                         f"fixture precondition: a hard kill. {killed.stderr}")
        trial_id = next(p.stem for p in
                        (self.root / "security" / "trial_runs").glob("*.json"))
        self.assertEqual(self.journal_states(trial_id),
                         {"r1": "apply_intent"},
                         "fixture precondition: the ambiguous window")
        self.assertEqual(self.surface()["r1"], ["ARCHIVED"],
                         "fixture precondition: the mutation is live on disk")

        # The cause of the kill is gone, as it is for a real operator re-running.
        (self.root / "kill_on_apply").unlink()

        result = self.run_recovery(trial_id)

        self.assertEqual(result.returncode, trc.EXIT_RESTORED,
                         f"stdout={result.stdout} stderr={result.stderr}")
        self.assertIn(tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, result.stdout)
        self.assertNotIn(tx.REFUSAL_MARKER_NOT_RESTORED, result.stdout)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual(self.journal_states(trial_id),
                         {"r1": "restored_verified"})
        self.assertEqual(self.surface()["r1"], ["OPEN"],
                         "the operator's real record is back at its prior state")
        self.assertFalse(
            (self.root / "agents" / "handoffs").glob("*.copy_run_proof.json")
            and list((self.root / "agents" / "handoffs").iterdir()),
            "a recovery must never write a proof")

    def test_a_still_blocked_unit_exits_one_and_prints_the_same_command_again(self):
        """The other direction, from the same real project: the state is entered,
        the command is offered, and re-running it once the cause is gone CLEARS it.
        Without this, exit 0 above could be a happy path that only ever runs on a
        trial that was never blocked."""
        (self.root / "kill_on_apply").touch()
        subprocess.run([sys.executable, "drive_trial.py"], capture_output=True,
                       text=True, cwd=str(self.root))
        trial_id = next(p.stem for p in
                        (self.root / "security" / "trial_runs").glob("*.json"))
        (self.root / "kill_on_apply").unlink()

        # Make the surface unreadable AND unwritable, so the reversal cannot be
        # confirmed: the disclosed read-path residual, on a real file.
        surface_path = self.root / "surface.json"
        original_mode = surface_path.stat().st_mode
        surface_path.chmod(0o000)
        self.addCleanup(surface_path.chmod, original_mode)

        blocked = self.run_recovery(trial_id)

        self.assertEqual(blocked.returncode, trc.EXIT_RECOVERY_REQUIRED,
                         f"stdout={blocked.stdout} stderr={blocked.stderr}")
        output = blocked.stdout + blocked.stderr
        self.assertIn(tx.REFUSAL_MARKER_NOT_RESTORED, output)
        self.assertNotIn(tx.REFUSAL_MARKER_NOTHING_OUTSTANDING, output)
        self.assertNotIn("Traceback", output)
        self.assertIn(trc.recovery_command(trial_id), output,
                      "the blocking output must offer the identical command")
        self.assertEqual(self.journal_states(trial_id),
                         {"r1": "recovery_required"})

        # The operator resolves the cause and re-runs the command they were given.
        surface_path.chmod(original_mode)
        cleared = self.run_recovery(trial_id)

        self.assertEqual(cleared.returncode, trc.EXIT_RESTORED,
                         f"stdout={cleared.stdout} stderr={cleared.stderr}")
        self.assertEqual(self.journal_states(trial_id),
                         {"r1": "restored_verified"},
                         "the state must actually CLEAR -- a repair that cannot "
                         "clear the state it names is not a repair")
        self.assertEqual(self.surface()["r1"], ["OPEN"])


# ---------------------------------------------------------------------------
# 14. The shipped adapter, end to end
# ---------------------------------------------------------------------------

class ShippedAdapterEndToEndTests(_Base):
    """`gmail.message.trash` through the REAL registered adapter, over the same
    Gmail mock that adapter's own suite trusts -- interrupted mid-apply, then
    recovered from disk alone."""

    OP_KIND = OP_TRASH
    SURFACE = "gmail"

    def setUp(self):
        super().setUp()
        self.service = MockGmailService({"m1": {"INBOX", "IMPORTANT"},
                                        "m2": {"INBOX"}})
        self.gmail_read_only = _GmailReadOnlyClient(self.service)

    def _op(self, n=2):
        return Operation(
            surface="gmail", object_id="m1", field="labels",
            new_value="TRASH", op_kind=OP_TRASH, batch_id="trial-batch",
            params={"messages": [
                {"message_id": mid, "prior_label_ids": sorted(labels)}
                for mid, labels in sorted(self.service.messages.items())[:n]]})

    def test_a_mid_apply_interruption_is_recovered_from_disk_alone(self):
        class _KilledTrashAdapter(GmailMessageTrashAdapter):
            UNDO_IS_ABSOLUTE_STATE_RESTORE = True

            def apply_one(self, raw_client, unit):
                super().apply_one(raw_client, unit)
                raise _Interrupt("killed after the vendor call returned")

        register_adapter(OP_TRASH, _KilledTrashAdapter())
        self.addCleanup(unregister_adapter, OP_TRASH)
        self.addCleanup(register_adapter, OP_TRASH, GmailMessageTrashAdapter())

        op = self._op()
        before = {mid: sorted(labels)
                  for mid, labels in self.service.messages.items()}

        with self.assertRaises(_Interrupt):
            tx.run_trial(
                op, _receipt(op), capability_id=CAPABILITY_ID,
                capability_module_paths=("agents/capabilities/x_capability.py",),
                client=self.service, read_only_client=self.gmail_read_only,
                descriptor_set=[_entry(id="gmail")], cap_ledger=self.ledger,
                paused_root=self.paused_root, journal_dir=self.journal_dir,
                proof_dir=self.proof_dir, lib_dir=str(_EXTERNAL_WRITE_DIR))

        trial_id = sorted(Path(self.journal_dir).glob("*.json"))[0].stem
        self.assertEqual(
            tj.load_trial_journal(trial_id,
                                  journal_dir=self.journal_dir).unit_states(),
            {"m1": tj.STATE_APPLY_INTENT, "m2": tj.STATE_PLANNED})

        unregister_adapter(OP_TRASH)
        register_adapter(OP_TRASH, GmailMessageTrashAdapter())

        outcome = trc.recover_trial(
            trial_id, journal_dir=self.journal_dir, client=self.service,
            read_only_client=self.gmail_read_only)

        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(
            tj.load_trial_journal(trial_id,
                                  journal_dir=self.journal_dir).unit_states(),
            {"m1": tj.STATE_RESTORED_VERIFIED, "m2": tj.STATE_PLANNED})
        self.assertEqual(
            {mid: sorted(labels)
             for mid, labels in self.service.messages.items()},
            before,
            "the real mailbox must be byte-for-byte back at its prior state")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
