"""Tests for the TRIAL WRITE-AHEAD JOURNAL — `external_write.trial_journal`.

The one property that matters more than every other property in this file:

    NO state transition is persisted AFTER the action it authorizes.

A journal whose apply-intent record lands after `apply_one` provides exactly as
much crash safety as no journal at all, which is the state the apply path is in
today: a bare `for unit in units: dispatch.apply_one(...)` loop with no per-unit
record, over an adapter layer that writes nothing to disk. So the keystone class
below does not assert that the file exists afterwards. It hands the journal to a
mutation callback and asserts, FROM INSIDE THAT CALLBACK — i.e. at the moment
before the external mutation would occur — that the record is already on disk,
already complete, and already fsynced.

What these tests do NOT claim
-----------------------------
  * They do not claim the real trial executor calls the journal in the right
    order. That executor does not exist yet; `_ExecutorDouble` below is a TEST
    DOUBLE and lives only in this file. What IS proved structurally is the part
    the journal owns: an outcome state is reachable ONLY from the write-ahead
    state that authorizes the action it reports, so an executor that skipped the
    intent record cannot record the outcome at all.
  * They do not claim `apply_confirmed` means the mutation landed, or that
    `restored_verified` means the surface was observed restored. Both are records
    of what the CALLER established; the journal cannot check either, and says so.
  * No fixture adapter here is a claim about any real operator-authored adapter.

Every `AuthorizedPlan` used below is obtained from the REAL
`write_authorization.authorize_operation` entrypoint. None is hand-built — a
hand-built one is impossible by construction, and a stand-in would prove nothing
about the surface the real executor will be handed.

Uses stub clients only; no network. Every test writes into its own temp
directory, so nothing here touches the real project's `security/` tree or its
ambient paused-mechanisms state.
"""

import ast
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

from external_write import scan, zones  # noqa: E402
from external_write import trial_eligibility as te  # noqa: E402
from external_write import trial_journal as tj  # noqa: E402
from external_write import write_authorization as wa  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    get_dispatch, register_adapter, unregister_adapter,
)
from external_write.contracts import (  # noqa: E402
    OPERATION_CONTRACTS, OperationContract, WRITE_AFFECTING_MODULES,
    register_contract,
)
from external_write.lifecycle_test_fixtures import (  # noqa: E402
    hermetic_paused_mechanisms,
)
from external_write.operations import EffectUnit, Operation  # noqa: E402
from external_write.write_gate import InvocationLedger  # noqa: E402

_EXTERNAL_WRITE_DIR = _AGENTS_LIB / "external_write"
_MODULE_PATH = _EXTERNAL_WRITE_DIR / "trial_journal.py"


# ---------------------------------------------------------------------------
# Fixtures. `_CompliantAdapter` reproduces the CONTRACT SHAPE of a
# trial-eligible adapter (an undo_ref per unit carrying the absolute prior
# state, both evidence predicates as real callables, the absolute-state-restore
# declaration on the same class that defines the undo_one it describes). It is
# not a claim about any shipped or operator-authored adapter.
# ---------------------------------------------------------------------------

class _RecordingClient:
    def __init__(self):
        self.applied = []
        self.undone = []

    def set_exact_labels(self, message_id, label_ids):
        self.applied.append((message_id, list(label_ids)))

    def restore_exact_labels(self, message_id, label_ids):
        self.undone.append((message_id, list(label_ids)))


class _CompliantAdapter:
    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def plan(self, params):
        return [
            EffectUnit(unit_id=m["message_id"],
                       target_ref={"message_id": m["message_id"]},
                       undo_ref={"message_id": m["message_id"],
                                 "prior_label_ids": list(m.get("prior_label_ids", ()))})
            for m in (params or {}).get("messages", [])
        ]

    def apply_one(self, raw_client, unit):
        raw_client.set_exact_labels(unit.target_ref["message_id"], ["TRASH"])

    def undo_one(self, raw_client, unit):
        raw_client.restore_exact_labels(unit.undo_ref["message_id"],
                                        unit.undo_ref["prior_label_ids"])

    def verify_one(self, observer, unit):
        return {"current_label_ids": list(observer.get_message(unit.unit_id))}

    def verify_apply_landed(self, evidence):
        return bool(evidence.poststate.get("is_trashed"))

    def verify_undo_restored(self, evidence):
        return bool(evidence.poststate.get("matches_prestate"))


class _ObservingAdapter(_CompliantAdapter):
    """An adapter whose `apply_one` / `undo_one` run a caller-supplied observer
    BEFORE recording the mutation. The observer is where the write-ahead
    assertions live: it runs at exactly the instant the external mutation would
    be issued, so what it can read off disk is what a crash at that instant
    would leave behind.

    It re-declares `UNDO_IS_ABSOLUTE_STATE_RESTORE` on ITSELF rather than
    inheriting it, because it overrides `undo_one` -- and the preflight's
    absolute-state clause is scoped to the `undo_one` it describes, so an
    inherited claim over replacement code is refused. That refusal is correct and
    the re-declaration is truthful: this override delegates to the base's
    absolute prior-state restore."""

    UNDO_IS_ABSOLUTE_STATE_RESTORE = True

    def __init__(self, on_apply=None, on_undo=None):
        self.on_apply = on_apply
        self.on_undo = on_undo

    def apply_one(self, raw_client, unit):
        if self.on_apply is not None:
            self.on_apply(unit)
        super().apply_one(raw_client, unit)

    def undo_one(self, raw_client, unit):
        if self.on_undo is not None:
            self.on_undo(unit)
        super().undo_one(raw_client, unit)


class _ExecutorDouble:
    """TEST DOUBLE for the journaled trial executor, which is a separate concern
    and does not exist yet. It exists here for one reason: to drive the journal
    in the order the real executor must use, so the write-ahead property can be
    observed from inside the mutation. Nothing in production code refers to it.
    """

    def __init__(self, journal, raw_client):
        self.journal = journal
        self.raw_client = raw_client

    def apply_all(self, plan):
        for unit in plan.units:
            self.journal.record_apply_intent(unit.unit_id)
            plan.dispatch.apply_one(plan.dispatch.instance, self.raw_client, unit)
            self.journal.record_apply_confirmed(unit.unit_id)

    def undo_all(self, plan):
        for unit in reversed(plan.units):
            self.journal.record_undo_intent(unit.unit_id)
            plan.dispatch.undo_one(plan.dispatch.instance, self.raw_client, unit)
            self.journal.record_restored_verified(unit.unit_id)


def _receipt(op):
    digest = hashlib.sha256(op.canonical_repr().encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc)
                  + timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"approved_operation_digest": digest, "expires_at": expires_at}


def _entry(*, id="fixture_surface"):
    return {"id": id, "name": id, "action_class": "modify",
            "risk_class": "sensitive_data", "recovery_profile_ref": None,
            "declared_test_target": "native_undo", "blast_radius_cap": 25,
            "accepted": False}


class _Base(unittest.TestCase):
    """Registration hygiene + a hermetic journal directory. The adapter and
    contract registries are module-global, so every fixture registration is
    undone on teardown, and no test writes into the real project tree."""

    OP_KIND = "fixture.journal.set_exact_labels"
    SURFACE = "fixture_surface"

    def setUp(self):
        self.client = _RecordingClient()
        self.ledger = InvocationLedger()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.journal_dir = str(Path(tmp.name) / "security" / "trial_runs")
        paused = hermetic_paused_mechanisms()
        self.paused_root = paused.__enter__()
        self.addCleanup(paused.__exit__, None, None, None)

    def register(self, adapter=None, *, op_kind=None):
        op_kind = op_kind or self.OP_KIND
        register_adapter(op_kind, adapter if adapter is not None else _CompliantAdapter())
        self.addCleanup(unregister_adapter, op_kind)
        register_contract(OperationContract(
            op_kind=op_kind, writes=("labels",), produces=(),
            dependency_set=WRITE_AFFECTING_MODULES,
            verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False,
            risk_class="sensitive_data", requires_accepted_phase=True,
            blast_radius_cap=25))
        self.addCleanup(OPERATION_CONTRACTS.pop, op_kind, None)
        return get_dispatch(op_kind)

    def op(self, *, op_kind=None, n=1):
        return Operation(
            surface=self.SURFACE, object_id="m1", field="labels",
            new_value="TRASH", op_kind=op_kind or self.OP_KIND, batch_id="b1",
            params={"messages": [{"message_id": f"m{i}",
                                  "prior_label_ids": ["INBOX"]}
                                 for i in range(1, n + 1)]})

    def capsules(self, op):
        """Capsules built through the module's OWN sanctioned constructor — the
        single spelling of the capsule's field names."""
        dispatch = get_dispatch(op.op_kind)
        out = {}
        for unit in dispatch.plan(dispatch.instance, op.params):
            out[unit.unit_id] = tj.build_recovery_capsule(
                op.op_kind, unit,
                target_ref_json=dict(unit.target_ref),
                undo_ref_json=dict(unit.undo_ref))
        return out

    def authorized_trial_plan(self, op, *, capsules=None, intent=None):
        authorization = wa.authorize_operation(
            op, _receipt(op),
            intent=intent or wa.EXECUTION_INTENT_TRIAL,
            target="native_undo", descriptor_set=[_entry()],
            cap_ledger=self.ledger,
            recovery_capsules=self.capsules(op) if capsules is None else capsules,
            paused_root=self.paused_root)
        self.assertTrue(
            authorization.authorized,
            "fixture precondition: the trial must authorize; got refusal "
            f"{authorization.refusal.detail if authorization.refusal else None!r}")
        return authorization.plan

    def open_journal(self, op=None, **kwargs):
        op = self.op() if op is None else op
        plan = self.authorized_trial_plan(op)
        return plan, tj.open_trial_journal(plan, journal_dir=self.journal_dir,
                                          **kwargs)

    def on_disk(self, journal):
        """The record as it actually exists on disk, read fresh from the path —
        never the in-memory handle, which would prove nothing about durability."""
        with open(journal.path, encoding="utf-8") as f:
            return json.load(f)


# ---------------------------------------------------------------------------
# 1. THE KEYSTONE: write-ahead means write-ahead
# ---------------------------------------------------------------------------

class WriteAheadOrderingTests(_Base):

    def test_full_plan_and_every_capsule_are_durable_before_the_first_mutation(self):
        """The done-condition: at the instant the FIRST external mutation would
        be issued, the whole plan and every unit's recovery capsule are already
        on disk. Observed from inside `apply_one`, not after the run."""
        seen = {}

        def observer(unit):
            if seen:  # only the FIRST mutation is the interesting instant
                return
            seen["record"] = self.on_disk(journal)

        self.register(_ObservingAdapter(on_apply=observer))
        op = self.op(n=3)
        plan = self.authorized_trial_plan(op)
        expected_capsules = dict(plan.recovery_capsules)
        journal = tj.open_trial_journal(plan, journal_dir=self.journal_dir)

        _ExecutorDouble(journal, self.client).apply_all(plan)

        record = seen["record"]
        units = record["units"]
        self.assertEqual([u["unit_id"] for u in units], ["m1", "m2", "m3"],
                         "every planned unit must be on disk before the first "
                         "mutation, in plan order")
        self.assertEqual({u["unit_id"]: u["recovery_capsule"] for u in units},
                         expected_capsules,
                         "every unit's recovery capsule must be durable before "
                         "the first mutation -- a capsule written afterwards "
                         "cannot restore a unit the crash already applied")

    def test_apply_intent_is_on_disk_before_apply_one_runs(self):
        observed = []

        def observer(unit):
            record = self.on_disk(journal)
            state = {u["unit_id"]: u["state"] for u in record["units"]}[unit.unit_id]
            observed.append((unit.unit_id, state))

        self.register(_ObservingAdapter(on_apply=observer))
        op = self.op(n=2)
        plan = self.authorized_trial_plan(op)
        journal = tj.open_trial_journal(plan, journal_dir=self.journal_dir)

        _ExecutorDouble(journal, self.client).apply_all(plan)

        self.assertEqual(observed, [("m1", tj.STATE_APPLY_INTENT),
                                    ("m2", tj.STATE_APPLY_INTENT)],
                         "each unit's apply-intent record must already be on "
                         "disk when its own mutation is issued")

    def test_undo_intent_is_on_disk_before_undo_one_runs(self):
        observed = []

        def observer(unit):
            record = self.on_disk(journal)
            state = {u["unit_id"]: u["state"] for u in record["units"]}[unit.unit_id]
            observed.append((unit.unit_id, state))

        self.register(_ObservingAdapter(on_undo=observer))
        op = self.op(n=2)
        plan = self.authorized_trial_plan(op)
        journal = tj.open_trial_journal(plan, journal_dir=self.journal_dir)
        executor = _ExecutorDouble(journal, self.client)
        executor.apply_all(plan)

        executor.undo_all(plan)

        self.assertEqual(observed, [("m2", tj.STATE_UNDO_INTENT),
                                    ("m1", tj.STATE_UNDO_INTENT)],
                         "each unit's undo-intent record must already be on "
                         "disk when its own reversal is issued")

    def test_the_intent_record_is_fsynced_before_the_mutation_can_observe_it(self):
        """Present on disk is not the same as DURABLE on disk: without an fsync
        the bytes can sit in the page cache and be lost by exactly the crash the
        journal exists to survive. Asserted by counting real fsync calls in the
        module under test, not by reading the source."""
        fsync_calls_at_mutation = []
        real_fsync = os.fsync
        counter = {"n": 0}

        def counting_fsync(fd):
            counter["n"] += 1
            return real_fsync(fd)

        def observer(unit):
            fsync_calls_at_mutation.append(counter["n"])

        self.register(_ObservingAdapter(on_apply=observer))
        op = self.op(n=1)
        plan = self.authorized_trial_plan(op)
        with mock.patch.object(tj.os, "fsync", counting_fsync):
            journal = tj.open_trial_journal(plan, journal_dir=self.journal_dir)
            at_open = counter["n"]
            _ExecutorDouble(journal, self.client).apply_all(plan)

        self.assertGreaterEqual(
            at_open, 2,
            "opening the journal must fsync the plan + capsules -- BOTH the "
            "file contents and the directory entry the rename published, or the "
            "record can be lost by the crash it exists to survive")
        self.assertGreaterEqual(
            fsync_calls_at_mutation[0] - at_open, 2,
            "the apply-intent record must be fully fsynced (contents AND "
            "directory entry) BEFORE the mutation is issued; an fsync that "
            "happens afterwards leaves exactly the crash window the journal "
            "exists to close")

    def test_a_crash_between_intent_and_confirmation_leaves_the_intent_durable(self):
        """The ambiguous window is ambiguous BY DESIGN, and the journal's job is
        to make the intent survive it. Simulated by raising from inside
        `apply_one` -- the record must still name the unit as apply-intent, so a
        later process knows a mutation for it may have landed."""
        def observer(unit):
            raise RuntimeError("simulated crash mid-apply")

        self.register(_ObservingAdapter(on_apply=observer))
        op = self.op(n=2)
        plan = self.authorized_trial_plan(op)
        journal = tj.open_trial_journal(plan, journal_dir=self.journal_dir)

        with self.assertRaises(RuntimeError):
            _ExecutorDouble(journal, self.client).apply_all(plan)

        reloaded = tj.load_trial_journal(journal.trial_id,
                                         journal_dir=self.journal_dir)
        self.assertEqual(reloaded.unit_state("m1"), tj.STATE_APPLY_INTENT)
        self.assertEqual(reloaded.unit_state("m2"), tj.STATE_PLANNED)
        self.assertEqual(reloaded.recovery_capsule("m1"),
                         plan.recovery_capsules["m1"],
                         "the capsule must be readable from disk alone after "
                         "the crash -- that is the whole point of writing it "
                         "before the mutation")


# ---------------------------------------------------------------------------
# 2. The state machine: an outcome is reachable ONLY from its authorizing intent
# ---------------------------------------------------------------------------

class StateClassificationTests(unittest.TestCase):
    """Structural, not behavioural: these assert the shape of the transition
    table itself, so a future state added without a classification fails here
    rather than silently defaulting into the permissive direction."""

    def test_every_state_is_classified_exactly_once(self):
        write_ahead = set(tj.WRITE_AHEAD_STATES)
        outcome = set(tj.OUTCOME_STATES)
        self.assertEqual(write_ahead | outcome, set(tj.TRIAL_UNIT_STATES),
                         "every state must be declared either write-ahead or an "
                         "outcome; an unclassified state has no ordering rule")
        self.assertEqual(write_ahead & outcome, set(),
                         "a state cannot be both write-ahead and an outcome")

    def test_apply_confirmed_is_reachable_only_from_apply_intent(self):
        self.assertEqual(_predecessors(tj.STATE_APPLY_CONFIRMED),
                         {tj.STATE_APPLY_INTENT},
                         "if apply_confirmed were reachable from planned, an "
                         "executor could apply without a durable intent record "
                         "and still report the outcome")

    def test_restored_verified_is_reachable_only_from_undo_intent(self):
        self.assertEqual(_predecessors(tj.STATE_RESTORED_VERIFIED),
                         {tj.STATE_UNDO_INTENT},
                         "if restored_verified were reachable from "
                         "apply_confirmed, an executor could undo without a "
                         "durable undo-intent record")

    def test_every_transition_target_is_a_declared_state(self):
        for state, targets in tj.LEGAL_TRANSITIONS.items():
            self.assertIn(state, tj.TRIAL_UNIT_STATES)
            for target in targets:
                self.assertIn(target, tj.TRIAL_UNIT_STATES)

    def test_terminal_states_have_no_successors(self):
        for state in tj.TERMINAL_STATES:
            self.assertEqual(tj.LEGAL_TRANSITIONS[state], ())

    def test_recovery_requireds_ONLY_exit_is_a_fresh_write_ahead_undo_intent(self):
        """`recovery_required` must be LEAVABLE and leavable exactly one way.

        Two separate obligations meet here and this is the assertion that keeps
        both. It must be leavable at all, because a blocking state with no
        performable repair is a state the operator cannot get out of. And it must
        be leavable ONLY through `undo_intent`, because that is what forbids the
        two wrong exits: a direct hop to `restored_verified` would let something
        mark a unit resolved with no fresh write-ahead record and no observed
        post-condition behind it, and a hop to `apply_intent` would be a RE-APPLY
        — a live write the operator never consented to at that moment.
        """
        self.assertEqual(tj.LEGAL_TRANSITIONS[tj.STATE_RECOVERY_REQUIRED],
                         (tj.STATE_UNDO_INTENT,))
        self.assertNotIn(tj.STATE_RESTORED_VERIFIED,
                         tj.LEGAL_TRANSITIONS[tj.STATE_RECOVERY_REQUIRED],
                         "nothing may mark a unit resolved without a fresh "
                         "write-ahead undo intent behind it")
        self.assertNotIn(tj.STATE_APPLY_INTENT,
                         tj.LEGAL_TRANSITIONS[tj.STATE_RECOVERY_REQUIRED],
                         "recovery converges by reversing, NEVER by re-applying")

    def test_apply_intent_is_reachable_only_from_planned(self):
        """The structural half of "recovery never re-applies": no state other
        than `planned` may advance to `apply_intent`, so no resumed or recovering
        process can issue a second apply for a unit through this journal at
        all."""
        self.assertEqual(_predecessors(tj.STATE_APPLY_INTENT),
                         {tj.STATE_PLANNED})

    def test_the_states_a_resumed_trial_must_drive_are_declared(self):
        """A resumed trial needs to know which units may still be outstanding.
        That set is DECLARED here rather than re-derived by each consumer, and it
        is exactly the states in which a mutation may have been issued and no
        verified restore has been recorded:

          * `apply_intent`     — the ambiguous window; the apply may have landed
          * `apply_confirmed`  — `apply_one` returned
          * `undo_intent`      — the reversal was issued, its outcome unrecorded
          * `recovery_required`— a prior attempt did not establish restoration

        `planned` is deliberately EXCLUDED: the apply-intent record is fsynced
        before `apply_one` is called, so a unit still at `planned` was provably
        never applied and has nothing outstanding. `restored_verified` is excluded
        because it is terminal and settled.
        """
        self.assertEqual(
            set(tj.RECOVERY_DRIVEN_STATES),
            {tj.STATE_APPLY_INTENT, tj.STATE_APPLY_CONFIRMED,
             tj.STATE_UNDO_INTENT, tj.STATE_RECOVERY_REQUIRED})
        self.assertNotIn(tj.STATE_PLANNED, tj.RECOVERY_DRIVEN_STATES)
        self.assertNotIn(tj.STATE_RESTORED_VERIFIED, tj.RECOVERY_DRIVEN_STATES)
        # Every driven state must be able to reach `undo_intent`, or a unit in it
        # could not be reversed at all.
        for state in tj.RECOVERY_DRIVEN_STATES:
            if state == tj.STATE_UNDO_INTENT:
                continue
            self.assertIn(tj.STATE_UNDO_INTENT, tj.LEGAL_TRANSITIONS[state],
                          f"a unit at {state!r} must be reversible")


def _predecessors(state):
    return {src for src, targets in tj.LEGAL_TRANSITIONS.items()
            if state in targets}


class StateMachineRefusalTests(_Base):

    def setUp(self):
        super().setUp()
        self.register()
        self.plan, self.journal = self.open_journal(self.op(n=2))

    def test_confirming_an_apply_that_was_never_intended_refuses(self):
        with self.assertRaises(tj.TrialJournalError) as ctx:
            self.journal.record_apply_confirmed("m1")
        self.assertIn("planned", str(ctx.exception))
        self.assertEqual(self.journal.unit_state("m1"), tj.STATE_PLANNED,
                         "a refused transition must leave the record untouched")

    def test_verifying_a_restore_that_was_never_intended_refuses(self):
        self.journal.record_apply_intent("m1")
        self.journal.record_apply_confirmed("m1")
        with self.assertRaises(tj.TrialJournalError):
            self.journal.record_restored_verified("m1")
        self.assertEqual(self.journal.unit_state("m1"), tj.STATE_APPLY_CONFIRMED)

    def test_undo_intent_is_legal_directly_from_apply_intent(self):
        """The crash-ambiguity convergence path. A crash between apply-intent and
        apply-confirmation leaves it unknowable whether the mutation landed, so a
        later process converges on the invariant by reversing anyway -- which it
        cannot do if the journal refuses the transition."""
        self.journal.record_apply_intent("m1")
        self.journal.record_undo_intent("m1")
        self.assertEqual(self.journal.unit_state("m1"), tj.STATE_UNDO_INTENT)

    def test_a_terminal_unit_cannot_be_transitioned_again(self):
        for state_call in (self.journal.record_apply_intent,
                           self.journal.record_apply_confirmed,
                           self.journal.record_undo_intent,
                           self.journal.record_restored_verified):
            state_call("m1")
        self.assertEqual(self.journal.unit_state("m1"), tj.STATE_RESTORED_VERIFIED)
        with self.assertRaises(tj.TrialJournalError):
            self.journal.record_apply_intent("m1")

    def test_recovery_required_is_reachable_from_every_non_terminal_state(self):
        self.journal.record_recovery_required("m1", reason="nothing was applied")
        self.assertEqual(self.journal.unit_state("m1"),
                         tj.STATE_RECOVERY_REQUIRED)
        self.journal.record_apply_intent("m2")
        self.journal.record_recovery_required("m2", reason="undo raised")
        self.assertEqual(self.journal.unit_state("m2"),
                         tj.STATE_RECOVERY_REQUIRED)

    def test_a_recovery_required_unit_can_be_driven_back_out_and_verified(self):
        """The operator exit, at the journal layer. A unit that a prior attempt
        left `recovery_required` must be able to reach `restored_verified` — and
        only by the route that re-establishes the guarantee: a fresh, durable
        `undo_intent` first, then the observed restore."""
        self.journal.record_apply_intent("m1")
        self.journal.record_apply_confirmed("m1")
        self.journal.record_undo_intent("m1")
        self.journal.record_recovery_required("m1", reason="could not observe")
        self.assertEqual(self.journal.unit_state("m1"),
                         tj.STATE_RECOVERY_REQUIRED)

        # A direct hop to the settled state is refused -- no quiet clearing.
        with self.assertRaises(tj.TrialJournalError):
            self.journal.record_restored_verified("m1")
        self.assertEqual(self.journal.unit_state("m1"),
                         tj.STATE_RECOVERY_REQUIRED)

        self.journal.record_undo_intent("m1")
        self.journal.record_restored_verified("m1")
        self.assertEqual(self.journal.unit_state("m1"),
                         tj.STATE_RESTORED_VERIFIED)

    def test_a_recovery_required_unit_can_never_be_re_applied(self):
        """The absolute half of the recovery rule, held by the transition table
        rather than by a driver remembering not to: a trial that re-applied after
        a crash would be a live write the operator never consented to at that
        moment, so the journal refuses to record the intent for it."""
        self.journal.record_apply_intent("m1")
        self.journal.record_recovery_required("m1", reason="undo raised")
        with self.assertRaises(tj.TrialJournalError) as ctx:
            self.journal.record_apply_intent("m1")
        self.assertIn("re-appl", str(ctx.exception).lower(),
                      "the refusal must say WHY -- recovery reverses, it never "
                      "re-applies")
        self.assertEqual(self.journal.unit_state("m1"),
                         tj.STATE_RECOVERY_REQUIRED)

    def test_recovery_required_demands_a_reason(self):
        with self.assertRaises(tj.TrialJournalError):
            self.journal.record_recovery_required("m1", reason="")

    def test_an_unknown_unit_id_refuses(self):
        with self.assertRaises(tj.TrialJournalError) as ctx:
            self.journal.record_apply_intent("not-in-the-plan")
        self.assertIn("not-in-the-plan", str(ctx.exception))

    def test_each_transition_appends_to_the_units_durable_history(self):
        self.journal.record_apply_intent("m1")
        self.journal.record_apply_confirmed("m1")
        entry = [u for u in self.on_disk(self.journal)["units"]
                 if u["unit_id"] == "m1"][0]
        self.assertEqual([h["state"] for h in entry["history"]],
                         [tj.STATE_PLANNED, tj.STATE_APPLY_INTENT,
                          tj.STATE_APPLY_CONFIRMED])
        for h in entry["history"]:
            self.assertTrue(h["at"].endswith("Z"))

    def test_the_disk_is_authoritative_for_a_second_handle(self):
        """Two handles on the same trial must not diverge: a transition made
        through one is visible to the other, because every read and every
        transition reads the file rather than a cached in-process state."""
        other = tj.load_trial_journal(self.journal.trial_id,
                                      journal_dir=self.journal_dir)
        self.journal.record_apply_intent("m1")
        self.assertEqual(other.unit_state("m1"), tj.STATE_APPLY_INTENT)
        other.record_apply_confirmed("m1")
        self.assertEqual(self.journal.unit_state("m1"),
                         tj.STATE_APPLY_CONFIRMED)


# ---------------------------------------------------------------------------
# 3. The recovery-capsule format
# ---------------------------------------------------------------------------

class RecoveryCapsuleFormatTests(_Base):

    def setUp(self):
        super().setUp()
        self.register()
        self.unit = EffectUnit(unit_id="m1", target_ref={"message_id": "m1"},
                               undo_ref={"message_id": "m1",
                                         "prior_label_ids": ["INBOX"]})

    def build(self, **kwargs):
        params = {"target_ref_json": {"message_id": "m1"},
                  "undo_ref_json": {"message_id": "m1",
                                    "prior_label_ids": ["INBOX"]}}
        params.update(kwargs)
        return tj.build_recovery_capsule(self.OP_KIND, self.unit, **params)

    def test_a_built_capsule_carries_exactly_the_declared_keys(self):
        self.assertEqual(set(self.build()), set(tj.RECOVERY_CAPSULE_KEYS))

    def test_a_built_capsule_validates_and_survives_a_real_json_round_trip(self):
        capsule = self.build()
        self.assertIsNone(tj.validate_recovery_capsule(self.OP_KIND, "m1", capsule))
        self.assertEqual(json.loads(json.dumps(capsule)), capsule)

    def test_the_builder_has_no_default_for_either_reference(self):
        """Silence must refuse. A keyword default would let an adapter omit the
        undo reference and still produce a capsule the journal accepts."""
        with self.assertRaises(TypeError):
            tj.build_recovery_capsule(self.OP_KIND, self.unit,
                                      target_ref_json={"message_id": "m1"})
        with self.assertRaises(TypeError):
            tj.build_recovery_capsule(self.OP_KIND, self.unit,
                                      undo_ref_json={"message_id": "m1"})

    def test_a_null_undo_reference_is_refused(self):
        reason = tj.validate_recovery_capsule(
            self.OP_KIND, "m1", self.build(undo_ref_json=None))
        self.assertIsNotNone(reason)
        self.assertIn(tj.CAPSULE_KEY_UNDO_REF, reason)

    def test_an_explicitly_null_target_reference_is_accepted(self):
        """An adapter whose undo reference alone identifies the target declares
        that POSITIVELY, with an explicit null -- never by omitting the key."""
        self.assertIsNone(tj.validate_recovery_capsule(
            self.OP_KIND, "m1", self.build(target_ref_json=None)))

    def test_an_omitted_target_reference_key_is_refused(self):
        capsule = self.build()
        del capsule[tj.CAPSULE_KEY_TARGET_REF]
        reason = tj.validate_recovery_capsule(self.OP_KIND, "m1", capsule)
        self.assertIsNotNone(reason)
        self.assertIn(tj.CAPSULE_KEY_TARGET_REF, reason)

    def test_an_unrecognized_key_is_refused(self):
        capsule = self.build()
        capsule["prior_labels"] = ["INBOX"]
        reason = tj.validate_recovery_capsule(self.OP_KIND, "m1", capsule)
        self.assertIsNotNone(reason)
        self.assertIn("prior_labels", reason)

    def test_a_capsule_filed_under_a_different_unit_id_is_refused(self):
        """Identity is joined on the DECLARED value, never inferred from the key
        a capsule happens to be filed under: a capsule whose own unit_id
        disagrees with its key would restore the wrong record."""
        reason = tj.validate_recovery_capsule(self.OP_KIND, "m2", self.build())
        self.assertIsNotNone(reason)
        self.assertIn("m2", reason)

    def test_a_capsule_earned_by_another_operation_kind_is_refused(self):
        reason = tj.validate_recovery_capsule("some.other.op_kind", "m1",
                                             self.build())
        self.assertIsNotNone(reason)
        self.assertIn("some.other.op_kind", reason)

    def test_a_capsule_with_the_wrong_schema_tag_is_refused(self):
        capsule = self.build()
        capsule[tj.CAPSULE_KEY_SCHEMA] = "trial_recovery_capsule-v0"
        self.assertIsNotNone(
            tj.validate_recovery_capsule(self.OP_KIND, "m1", capsule))

    def test_a_non_mapping_capsule_is_refused(self):
        for degenerate in ({}, "", 0, False, [], None):
            self.assertIsNotNone(
                tj.validate_recovery_capsule(self.OP_KIND, "m1", degenerate),
                f"the degenerate capsule {degenerate!r} carries nothing a "
                "recovery path could use and must be refused by the FORMAT")

    def test_the_journal_serializer_agrees_with_the_preflight_round_trip(self):
        """The preflight proves a capsule survives a real JSON round trip. That
        proof is only a proof about THIS writer if the writer serializes with the
        same strictness. Asserted over values that sit either side of the line,
        by running both."""
        op = self.op()
        units = get_dispatch(self.OP_KIND).plan(
            get_dispatch(self.OP_KIND).instance, op.params)
        cases = [
            ("plain", {"message_id": "m1"}),
            ("nan", {"message_id": float("nan")}),
            ("infinity", {"message_id": float("inf")}),
            ("set", {"message_id": {"a", "b"}}),
        ]
        for label, payload in cases:
            with self.subTest(label):
                capsule = tj.build_recovery_capsule(
                    self.OP_KIND, units[0],
                    target_ref_json={"message_id": "m1"},
                    undo_ref_json=payload)
                verdict = te.check_trial_eligibility(
                    self.OP_KIND, units, {"m1": capsule})
                preflight_accepts = (
                    te.CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE
                    not in verdict.failed_clauses)
                try:
                    tj.serialize_journal_payload({"capsule": capsule})
                    writer_accepts = True
                except (TypeError, ValueError):
                    writer_accepts = False
                self.assertEqual(
                    preflight_accepts, writer_accepts,
                    "the preflight's serializability proof and the journal's "
                    "own writer must accept exactly the same capsules, or the "
                    "preflight is proving something about a different writer")


# ---------------------------------------------------------------------------
# 4. Opening: fail-closed, and bound to what was actually authorized
# ---------------------------------------------------------------------------

class OpenRefusalTests(_Base):

    def setUp(self):
        super().setUp()
        self.register()

    def test_a_non_plan_cannot_open_a_journal(self):
        for bogus in (None, {}, "plan", object()):
            with self.assertRaises(tj.TrialJournalError):
                tj.open_trial_journal(bogus, journal_dir=self.journal_dir)

    def test_an_ordinary_intent_plan_cannot_open_a_trial_journal(self):
        op = self.op()
        authorization = wa.authorize_operation(
            op, _receipt(op), intent=wa.EXECUTION_INTENT_ORDINARY,
            target="native_undo", descriptor_set=[_entry()],
            cap_ledger=self.ledger, paused_root=self.paused_root)
        self.assertTrue(authorization.authorized)
        with self.assertRaises(tj.TrialJournalError) as ctx:
            tj.open_trial_journal(authorization.plan,
                                  journal_dir=self.journal_dir)
        self.assertIn(wa.EXECUTION_INTENT_TRIAL, str(ctx.exception))

    def assertNoJournalWritten(self):
        """Assert the journal directory holds NOTHING -- not even a lock file.

        Deliberately stricter than "no `<trial_id>.json`", and it holds because
        every refusal this helper is used for happens BEFORE `open_trial_journal`
        enters its exclusive section, so no lock file has been created either. If
        a future refusal is moved inside `_exclusive`, this will report a failure
        naming the leftover `.lock` -- that is a signal to narrow the assertion to
        the journal file for that one case, not a bug in the refusal.
        """
        directory = Path(self.journal_dir)
        written = sorted(p.name for p in directory.iterdir()) \
            if directory.exists() else []
        self.assertEqual(written, [],
                         "a refused open must leave no half-written journal")

    def test_a_missing_capsule_refuses_and_writes_nothing(self):
        # The plan is rewritten in place with `object.__setattr__` -- the one
        # forgery route `write_authorization` discloses -- precisely so this
        # asserts the JOURNAL's own fail-closed check rather than restating the
        # preflight's. The preflight would refuse this capsule set too; the
        # journal must not depend on that having happened.
        op = self.op(n=2)
        capsules = self.capsules(op)
        capsules.pop("m2")
        plan = self.authorized_trial_plan(op)
        object.__setattr__(plan, "recovery_capsules", capsules)
        with self.assertRaises(tj.TrialJournalError) as ctx:
            tj.open_trial_journal(plan, journal_dir=self.journal_dir)
        self.assertIn("m2", str(ctx.exception))
        self.assertNoJournalWritten()

    def test_a_malformed_capsule_refuses_before_anything_is_written(self):
        """A capsule that is PRESENT but does not conform must be caught before
        the open record lands. If it were caught afterwards, the trial would
        already own a journal whose recovery data is unusable -- and a journal
        that exists is exactly what a later process trusts."""
        op = self.op(n=2)
        capsules = self.capsules(op)
        capsules["m2"] = dict(capsules["m2"])
        capsules["m2"][tj.CAPSULE_KEY_UNDO_REF] = None
        plan = self.authorized_trial_plan(op)
        object.__setattr__(plan, "recovery_capsules", capsules)
        with self.assertRaises(tj.TrialJournalError) as ctx:
            tj.open_trial_journal(plan, journal_dir=self.journal_dir)
        self.assertIn(tj.CAPSULE_KEY_UNDO_REF, str(ctx.exception))
        self.assertNoJournalWritten()

    def test_a_non_serializable_capsule_refuses_the_open_as_documented(self):
        """The path that justifies NOT duplicating the preflight's
        serializability check.

        The argument for leaving that check with its single owner is that the
        journal's own write IS the real round trip, performed before any mutation,
        so a capsule that cannot be serialized fails the OPEN. That argument was
        asserted nowhere, and the failure arrived as a bare `TypeError` from
        `json.dumps` rather than the `TrialJournalError` this entrypoint
        documents -- so a caller catching the documented exception would not have
        caught it. Driven through the REAL entrypoint, with a capsule that is
        format-valid (so the format validator passes it) and not JSON-safe.
        """
        op = self.op(n=2)
        capsules = self.capsules(op)
        capsules["m2"] = dict(capsules["m2"])
        capsules["m2"][tj.CAPSULE_KEY_UNDO_REF] = {"prior_label_ids"}  # a set
        plan = self.authorized_trial_plan(op)
        object.__setattr__(plan, "recovery_capsules", capsules)
        self.assertIsNone(
            tj.validate_recovery_capsule(self.OP_KIND, "m2", capsules["m2"]),
            "fixture precondition: the capsule must pass the FORMAT check, so "
            "this test exercises the serialization refusal and not that one")
        with self.assertRaises(tj.TrialJournalError) as ctx:
            tj.open_trial_journal(plan, journal_dir=self.journal_dir)
        self.assertIn("m2", str(ctx.exception))
        self.assertNoJournalWritten()

    def test_an_inaccessible_journal_path_refuses_rather_than_reading_as_absent(self):
        """A fail-closed filesystem check must distinguish ABSENT from
        INACCESSIBLE. `os.path.exists` answers False for both, so a permission
        error at the write-once check would be read as 'no prior trial' and the
        open would proceed to overwrite a record that may be the only thing that
        knows a real mutation is outstanding."""
        plan = self.authorized_trial_plan(self.op())
        real_lstat = os.lstat

        def denying_lstat(path, *args, **kwargs):
            if str(path).endswith(".json"):
                raise PermissionError(13, "Permission denied")
            return real_lstat(path, *args, **kwargs)

        with mock.patch.object(tj.os, "lstat", denying_lstat):
            with self.assertRaises(tj.TrialJournalError) as ctx:
                tj.open_trial_journal(plan, journal_dir=self.journal_dir)
        message = str(ctx.exception).lower()
        self.assertIn("inaccessible", message)
        self.assertNotIn(".json", sorted(
            p.suffix for p in Path(self.journal_dir).iterdir()
            if p.suffix == ".json"), "nothing may be written past that refusal")

    def test_a_capsule_for_a_unit_not_in_the_plan_refuses(self):
        op = self.op()
        plan = self.authorized_trial_plan(op)
        extra = dict(plan.recovery_capsules)
        extra["ghost"] = tj.build_recovery_capsule(
            self.OP_KIND,
            EffectUnit(unit_id="ghost", target_ref={}, undo_ref={}),
            target_ref_json={}, undo_ref_json={})
        object.__setattr__(plan, "recovery_capsules", extra)
        with self.assertRaises(tj.TrialJournalError) as ctx:
            tj.open_trial_journal(plan, journal_dir=self.journal_dir)
        self.assertIn("ghost", str(ctx.exception))

    def test_a_reused_trial_id_refuses_rather_than_clobbering(self):
        plan_a, journal = self.open_journal(self.op(), trial_id="fixed-trial-id")
        plan_b = self.authorized_trial_plan(self.op())
        with self.assertRaises(tj.TrialJournalError):
            tj.open_trial_journal(plan_b, journal_dir=self.journal_dir,
                                  trial_id="fixed-trial-id")
        self.assertEqual(self.on_disk(journal)["trial_id"], "fixed-trial-id",
                         "the first trial's recovery record must survive intact")

    def test_a_trial_id_outside_the_safe_charset_refuses_and_is_never_rewritten(self):
        """Silently sanitizing an id would map two distinct trial ids onto one
        file, so the second would clobber the first's recovery record."""
        plan = self.authorized_trial_plan(self.op())
        for bad in ("../escape", "trial id", "trial/id", "", ".", ".."):
            with self.subTest(bad):
                with self.assertRaises(tj.TrialJournalError):
                    tj.open_trial_journal(plan, journal_dir=self.journal_dir,
                                          trial_id=bad)

    def test_a_minted_trial_id_is_unique_per_trial(self):
        _, first = self.open_journal(self.op())
        _, second = self.open_journal(self.op())
        self.assertNotEqual(first.trial_id, second.trial_id)
        self.assertNotEqual(first.path, second.path)

    def test_the_open_record_binds_the_journal_to_the_authorized_operation(self):
        op = self.op()
        plan, journal = self.open_journal(op)
        record = self.on_disk(journal)
        self.assertEqual(record["schema"], tj.TRIAL_JOURNAL_SCHEMA)
        self.assertEqual(record["op_kind"], self.OP_KIND)
        self.assertEqual(record["surface"], self.SURFACE)
        self.assertEqual(record["operation_digest"], op.digest())
        self.assertEqual(record["resolved_target"], wa.TRIAL_TARGET)
        self.assertTrue(record["opened_at"].endswith("Z"))

    def test_the_default_journal_directory_is_the_declared_surface(self):
        self.assertEqual(tj.DEFAULT_TRIAL_JOURNAL_DIR, "security/trial_runs")


class LoadFailClosedTests(_Base):

    def setUp(self):
        super().setUp()
        self.register()

    def test_loading_an_absent_trial_raises_rather_than_reading_as_empty(self):
        """An empty envelope is the fail-SAFE reading of a missing budget file.
        For a recovery record it is the fail-OPEN one: an empty journal says
        'nothing was applied', which is the one claim a missing file cannot
        support."""
        with self.assertRaises(tj.TrialJournalError):
            tj.load_trial_journal("no-such-trial", journal_dir=self.journal_dir)

    def test_loading_a_malformed_trial_record_raises(self):
        os.makedirs(self.journal_dir, exist_ok=True)
        path = Path(self.journal_dir) / "broken.json"
        for text in ("{ not json", "[]", '{"schema": "something-else"}'):
            path.write_text(text, encoding="utf-8")
            with self.subTest(text):
                with self.assertRaises(tj.TrialJournalError):
                    tj.load_trial_journal("broken", journal_dir=self.journal_dir)

    def test_a_reloaded_journal_round_trips_every_capsule_faithfully(self):
        op = self.op(n=3)
        plan, journal = self.open_journal(op)
        reloaded = tj.load_trial_journal(journal.trial_id,
                                         journal_dir=self.journal_dir)
        self.assertEqual(reloaded.unit_ids(), ("m1", "m2", "m3"))
        for unit_id, capsule in plan.recovery_capsules.items():
            self.assertEqual(reloaded.recovery_capsule(unit_id), capsule)


# ---------------------------------------------------------------------------
# 5. Durability mechanics
# ---------------------------------------------------------------------------

class DurabilityMechanicsTests(_Base):

    def setUp(self):
        super().setUp()
        self.register()
        self.plan, self.journal = self.open_journal(self.op(n=2))

    def test_an_interrupted_transition_leaves_the_prior_record_intact(self):
        before = Path(self.journal.path).read_text(encoding="utf-8")
        with mock.patch.object(tj.os, "replace",
                               side_effect=OSError("simulated crash mid-write")):
            with self.assertRaises(OSError):
                self.journal.record_apply_intent("m1")
        self.assertEqual(Path(self.journal.path).read_text(encoding="utf-8"),
                         before,
                         "a crash before the atomic rename lands must leave the "
                         "prior journal completely intact")

    def test_an_interrupted_transition_leaves_no_temp_file_behind(self):
        with mock.patch.object(tj.os, "replace",
                               side_effect=OSError("simulated crash mid-write")):
            with self.assertRaises(OSError):
                self.journal.record_apply_intent("m1")
        leftovers = [p.name for p in Path(self.journal_dir).iterdir()
                     if p.name.startswith(".")]
        self.assertEqual(leftovers, [])

    def test_the_directory_entry_is_fsynced_so_the_rename_itself_is_durable(self):
        """fsync on the file makes the BYTES durable; the rename that publishes
        them is a directory-entry change, which needs its own fsync. Without it a
        crash can lose the whole record even though its contents were flushed."""
        opened_dirs = []
        real_open = os.open

        def recording_open(path, flags, *args, **kwargs):
            if flags & os.O_RDONLY == os.O_RDONLY and os.path.isdir(path):
                opened_dirs.append(str(path))
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(tj.os, "open", recording_open):
            self.journal.record_apply_intent("m1")
        self.assertIn(os.path.abspath(self.journal_dir),
                      [os.path.abspath(p) for p in opened_dirs])

    def test_the_record_is_written_with_a_canonical_byte_stable_serialization(self):
        first = tj.serialize_journal_payload({"b": 1, "a": {"d": 2, "c": 3}})
        second = tj.serialize_journal_payload({"a": {"c": 3, "d": 2}, "b": 1})
        self.assertEqual(first, second,
                         "identical content must serialize to identical bytes "
                         "regardless of insertion order")

    def test_the_journal_refuses_to_transition_without_a_cross_process_lock(self):
        """An unlocked read-modify-write can lose a transition, and a lost
        transition is a mutation with nothing on disk recording it -- the exact
        failure the journal exists to prevent. Repair: run the trial on a
        platform providing POSIX advisory locks."""
        with mock.patch.object(tj, "_fcntl", None):
            with self.assertRaises(tj.TrialJournalError) as ctx:
                self.journal.record_apply_intent("m1")
        self.assertIn("lock", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# 6. Enrollment, zone membership, and the no-pickle rule
# ---------------------------------------------------------------------------

class EnrollmentTests(unittest.TestCase):

    def test_the_journal_is_enrolled_in_the_emitted_lib_file_set(self):
        """Without enrollment the journal never physically reaches an operator
        project, so the trial protocol runs there with no write-ahead record --
        the state this module exists to end."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import agent_emitter
        self.assertIn("trial_journal.py",
                      agent_emitter._EXTERNAL_WRITE_LIB_FILES)


class ZoneMembershipTests(unittest.TestCase):

    _LIB = _EXTERNAL_WRITE_DIR
    _MODULE = _MODULE_PATH

    def test_the_journal_is_enrolled_as_sealed_kernel(self):
        self.assertIn("trial_journal.py", zones.SEALED_KERNEL_MODULE_PATHS)
        self.assertEqual(zones.classify_zone(self._MODULE, self._LIB),
                         zones.Zone.SEALED_KERNEL)

    def test_the_journal_scans_clean_as_sealed_kernel(self):
        self.assertEqual(scan.scan_paths([self._MODULE], allowed_root=self._LIB),
                         [])

    def test_without_that_membership_the_journal_would_be_flagged(self):
        """The counterfactual: the membership is load-bearing, not decorative.
        Scanned as CAPABILITY the module trips the CAPABILITY-zone-ONLY module
        boundary rule, because it legitimately reads the sibling kernel's
        authorization carrier."""
        without = frozenset(p for p in zones.SEALED_KERNEL_MODULE_PATHS
                            if p != "trial_journal.py")
        kinds = {v.kind for v in scan.scan_paths(
            [self._MODULE], allowed_root=self._LIB, sealed_kernel_paths=without)}
        self.assertEqual(kinds, {"sealed_kernel_import"})

    def test_sealed_kernel_membership_does_not_let_a_capability_import_it(self):
        self.assertNotIn("trial_journal",
                         scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES)


class SerializationDisciplineTests(unittest.TestCase):

    def test_the_module_never_reaches_for_pickle(self):
        """A recovery capsule holds adapter-defined values whose type nothing
        here controls. Pickling one would execute arbitrary code on the recovery
        path; JSON is the whole reason the capsule format exists. Checked by AST
        -- a text search cannot answer a question about code structure."""
        tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("pickle", imported)
        self.assertNotIn("marshal", imported)
        self.assertNotIn("shelve", imported)


if __name__ == "__main__":
    unittest.main()
