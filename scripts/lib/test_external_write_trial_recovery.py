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
import shlex
import subprocess
import sys
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
