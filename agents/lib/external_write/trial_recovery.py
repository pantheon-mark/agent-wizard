"""TRIAL RECOVERY — resuming an interrupted trial by converging on the invariant,
never by reconstructing history (Cut 1.9 Task 5).

------------------------------------------------------------------------------
The problem, and why this module does not solve it the obvious way
------------------------------------------------------------------------------
A journaled trial records `apply_intent` — durably, fsynced, contents and
directory entry both — BEFORE it calls the adapter's `apply_one`. If the process
dies between that record and `apply_confirmed`, the journal says exactly one
thing: *this unit's mutation may have landed.* Nothing on disk can say whether it
did, and nothing ever will be able to: the record that would have said so is the
record the crash prevented.

The obvious response is to go and find out — re-read the surface, compare it
against something, decide whether the apply happened, then act on that decision.
**This module deliberately does not do that.** Reconstructing the history means
building a second, inferential answer to a question the durable record cannot
answer, and then making a live write conditional on that inference being right.

Instead it converges on the **invariant the trial exists to hold**: *the surface
equals the prior state.* For any unit that might still be outstanding it reverses
the unit and then asks the adapter's own absolute post-condition whether the
surface is now at its prior state. That question is answerable without knowing
whether the apply ever landed, which is the whole hinge — the ambiguity never has
to be resolved because nothing depends on the answer.

    for each unit that may still be outstanding:
        undo_one                      (write-ahead undo intent already durable)
        verify_one -> verify_undo_restored
            True   -> restored_verified.  The ambiguity never had to be resolved.
            False  -> recovery_required, carrying the OBSERVED poststate
            unanswerable -> recovery_required (fail-closed; never a blind pass)

------------------------------------------------------------------------------
Why this is sound — it rests on two DECLARED adapter properties, not on hope
------------------------------------------------------------------------------
  1. **`undo_one` is an ABSOLUTE-STATE restore, and therefore idempotent.** It
     sets the prior state (the exact prior label set, the prior cell value), not a
     compensating or relative delta. So running it against a surface that is
     ALREADY at its prior state is a no-op. That is precisely what makes it safe
     to reverse a unit when nobody knows whether the apply landed.
  2. **`verify_undo_restored` is an ABSOLUTE post-condition**, not a "did the undo
     call run" check: true only if the OBSERVED live state equals the recorded
     prior state. It is never a blind pass.

Neither property is assumed here. Both are things the TRIAL-ELIGIBILITY PREFLIGHT
requires the adapter to DECLARE before a trial may run at all — the absolute-state
declaration exists for exactly this reason — so a journal on disk is a journal for
an op_kind whose adapter made that declaration. What the declaration cannot do is
make the claim true: nothing static can verify an adapter's undo semantics, and a
lying declaration is within this package's disclosed enforcement ceiling
(build-time plus operator-as-approver, never a runtime sandbox). Recovery's own
fail-closed net for that case is the observed post-condition: an undo that did not
in fact restore is not recorded as restored.

------------------------------------------------------------------------------
Two things this module will NOT do, and they are absolute
------------------------------------------------------------------------------
  * **It never re-applies.** Not by convention — structurally. There is no
    `apply_one` call site in this file, and the journal makes `apply_intent`
    reachable only from `planned`, so no resumed process can record the intent
    that would authorize a second apply. A trial that re-applied after a crash
    would be a live write the operator never consented to at that moment: they
    approved one bounded trial, in a session that no longer exists.
  * **It never asks whether the apply landed.** The apply-side evidence predicate
    is not evaluated here and is not referenced here. Converging is the answer;
    investigating is the design this one replaces.

------------------------------------------------------------------------------
The states it drives, and the one it deliberately leaves alone
------------------------------------------------------------------------------
`trial_journal.RECOVERY_DRIVEN_STATES` is the DECLARED set, read from there rather
than re-listed here — a second enumeration of "which units may still be
outstanding" would be a second classification, and a state added later without
being classified would silently drop out of this driver's scope.

  * `apply_intent`      — the ambiguous window. Driven.
  * `apply_confirmed`   — `apply_one` returned. Driven.
  * `undo_intent`       — the reversal was issued and its outcome never recorded.
                          Driven — and NOT re-recorded: the write-ahead record is
                          already on disk, which is what write-ahead means. This
                          driver confirms the durable state IS `undo_intent`
                          before issuing the reversal, and refuses if it is not.
  * `recovery_required` — a previous attempt could not establish restoration.
                          Driven. This is the operator's exit, below.

  * `planned`           — NOT driven, and this is the one exclusion worth stating
                          plainly. The apply-intent record is fsynced before
                          `apply_one` is called, so a unit still recorded
                          `planned` was provably never applied. Reversing it would
                          be a write with nothing to undo, on a record the
                          operator's trial never touched.
  * `restored_verified` — NOT driven. Settled and terminal.

------------------------------------------------------------------------------
`recovery_required` HAS AN EXIT, and that is a requirement rather than a nicety
------------------------------------------------------------------------------
This whole protocol was built because two real operator states had no way out. A
`recovery_required` unit with no performable repair would be a third one, so it is
a first-class state with a real, resumable, operator-invocable exit:

    python3 agents/lib/external_write/trial_recovery.py --trial-id <trial id>

That is this module's own `__main__`, and `recovery_command` renders it. It is
single-sourced: the trial executor's own refusal calls that function rather than
spelling a command of its own, so the surface that ANNOUNCES the blocking state
and the surface that PERFORMS the repair cannot drift into naming different
things.

The exit is real in both directions, which is what makes it worth having. When the
cause was transient — the read path was down, a vendor call failed, a credential
had expired — re-running reverses the unit again under a fresh durable intent, and
an observed restore moves it to `restored_verified`: the state actually clears.
When the cause persists, it stays `recovery_required` and says why. The journal
makes both of those true rather than this driver promising them: the state's ONLY
successor is `undo_intent`, so it can never be cleared quietly (there is no route
to the settled state that skips the write-ahead record or the observation) and it
can never be cleared by re-applying.

------------------------------------------------------------------------------
Recovery is authorized by the JOURNAL, and does not mint or require a receipt
------------------------------------------------------------------------------
Stated explicitly because it is the one place a reader might expect an
authorization call and not find one.

A journal on disk exists only because `write_authorization.authorize_operation`
already issued an `AuthorizedPlan` for the TRIAL intent against the bounded trial
target, and `open_trial_journal` accepts nothing else. So the operator's approval
of exactly these units, against exactly this bounded target, already happened —
and the reversal this module performs is the completion of that approved trial,
not a new operation. Requiring a fresh receipt would be requiring an artifact only
the dead process held: the operator's approval lives in memory in the session that
obtained it, and there is no on-disk per-operation approved-operation record
anywhere in this package. A repair that cannot be performed is not a repair, and a
blocking state whose repair cannot be performed is the dead end this cut exists to
close.

What recovery therefore does NOT do, and must not be read as doing: it does not
re-run the eligibility preflight, it does not consume a second blast-radius slot
for a reversal that was already counted, and — above all — it does not extend the
authorization to anything the journal does not name. It reverses units listed in
that journal, using the values in their own recovery capsules, and it cannot apply.

DISCLOSED, not glossed: a hand-authored journal file on disk would therefore drive
`undo_one` calls without a fresh receipt. That is within the standing enforcement
ceiling and not a new hole — hand-editing a journal has always been exactly as
available as hand-editing anything else on disk, and the same is true of the
adapter code itself — but it is a real write capability and it is named here
rather than left for a reader to discover. What bounds it is narrow and worth
stating: the record must validate as a trial journal, its recorded target must be
the bounded trial target, and the only adapter method reachable from here is
`undo_one`.

------------------------------------------------------------------------------
HONEST RESIDUALS — both adjudicated, recorded rather than argued
------------------------------------------------------------------------------
  1. **Recovery may perform a NO-OP WRITE.** If the apply never landed, the
     reversal writes prior value over prior value. The surface is unchanged — but
     it IS an API call: it consumes a rate/ledger slot and it appears in the
     vendor's own audit log, where an operator may later see a write they did not
     initiate. This is accepted deliberately, because the alternative is to decide
     whether the apply landed and skip the undo when the answer looks like "no" —
     i.e. to leave a possibly-applied mutation on the operator's live record on
     the strength of an inference. Converging is strictly safer, and the cost is
     disclosed instead of hidden.
  2. **Recovery needs the READ PATH.** `verify_undo_restored` judges an
     observation produced through the read-only facade. If the read path is down
     at recovery time, the verdict is unanswerable and the unit lands
     `recovery_required` — correct and fail-closed. Note the ORDER, which is a
     deliberate divergence from the trial executor: the executor refuses BEFORE
     any mutation when it cannot observe, because nothing has happened yet and a
     trial that cannot observe can never earn a proof. Recovery is in the opposite
     position — a unit may be outstanding on the operator's record right now — so
     it converges the surface FIRST and reports the unverifiable verdict second.
     Restoring without being able to confirm it is better than not restoring.

------------------------------------------------------------------------------
It produces no proof, and that is not an omission
------------------------------------------------------------------------------
A `copy_run_proof` carries the OBSERVED apply-side evidence of a unit. That
observation was never in the durable record — the journal records states and prior
states, never observed poststates — so a resumed run cannot produce it, and
writing an affirmative proof around evidence it did not observe would be forged
evidence of the exact kind every gate in this package exists to refuse. A trial
whose proof is still needed is re-run as a NEW trial, under a fresh approval the
operator gives at that moment. `run_trial` remains the only producer.

Zone: SEALED_KERNEL (enumerated in `zones.py`). Membership does not invite use:
capability code may not import this module (the independent
`scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES` set governs that, and this
module is absent from it). A capability reversing the external writes it proposed
is the same inversion the authorization split exists to prevent.

Stdlib only — no third-party dependencies.
"""

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# sys.path bootstrap (mirrors `trial_journal.py` / `run_envelope.py`): make the
# package parent importable when this file is run as a direct script from the
# project root, which is exactly how the operator invokes it.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.adapter_registry import (
    get_dispatch, resolve_read_only_client, resolve_write_client,
)
from external_write.capability_runner import (
    ReadFacadeDeclarationError, import_declared_read_facade,
)
from external_write.operations import EffectUnit
from external_write.read_facade import (
    ReadFacadeEligibilityError, build_read_facade,
)
from external_write.trial_executor import (
    REFUSAL_MARKER_NOT_RESTORED, REFUSAL_MARKER_NOTHING_OUTSTANDING,
    UNDO_PREDICATE_NAME, evaluate_evidence_predicate, observe_unit,
    trial_source_lineage, unit_evidence,
)
from external_write.trial_journal import (
    CAPSULE_KEY_TARGET_REF, CAPSULE_KEY_UNDO_REF, DEFAULT_TRIAL_JOURNAL_DIR,
    RECOVERY_DRIVEN_STATES, STATE_RECOVERY_REQUIRED, STATE_RESTORED_VERIFIED,
    STATE_UNDO_INTENT, TrialJournalError, load_trial_journal,
)
from external_write.write_authorization import TRIAL_TARGET


# ---------------------------------------------------------------------------
# The operator-invocable entrypoint, named in exactly one place
# ---------------------------------------------------------------------------

# The project-relative path of THIS file in an emitted operator project. Spelled
# once, here, because two surfaces render a command that has to point at it: this
# module's own `recovery_command`, and (through that function) the trial
# executor's refusal. A re-spelling is how a named repair comes to name a path
# that no longer exists.
RECOVERY_ENTRYPOINT_REL = "agents/lib/external_write/trial_recovery.py"

# Process exit codes, following this package's existing CLI convention (0 =
# succeeded, 1 = refused by domain logic, 2 = usage error). `EXIT_RECOVERY_REQUIRED`
# is the domain refusal: the command ran correctly and the honest answer is that a
# unit still needs attention. Non-zero so nothing monitoring the exit status can
# mistake it for an all-clear.
EXIT_RESTORED = 0
EXIT_RECOVERY_REQUIRED = 1
EXIT_BAD_ARGS = 2

_FLAG_TRIAL_ID = "--trial-id"
_FLAG_JOURNAL_DIR = "--journal-dir"

USAGE = (
    f"Usage: python3 {RECOVERY_ENTRYPOINT_REL} {_FLAG_TRIAL_ID} <trial id> "
    f"[{_FLAG_JOURNAL_DIR} <path>]\n"
    "Brings every unit of an interrupted trial back to the state it was in "
    "before the trial touched it, and checks that it worked.\n"
    "It never re-does the change it was reversing.\n"
    f"Exit codes: {EXIT_RESTORED} = everything is back and confirmed; "
    f"{EXIT_RECOVERY_REQUIRED} = something still needs attention (it says what); "
    f"{EXIT_BAD_ARGS} = the command was not understood."
)


def recovery_command(trial_id: str, *,
                     journal_dir: Optional[str] = None) -> str:
    """The exact, paste-ready command that leaves `recovery_required` — rendered
    in ONE place so every surface that has to name the repair names the same one.

    The `--journal-dir` flag is emitted only when the directory is NOT the
    production default: an operator's real invocation should carry no flag they
    would have to understand, and the default IS the production convention. A
    non-default directory is quoted, because an unquoted path containing a space
    would silently split into two arguments and the "paste-ready" command would
    not run.

    Deliberately a single physical line. A command that wraps is the paste hazard
    this package has already paid for once.
    """
    command = f"python3 {RECOVERY_ENTRYPOINT_REL} {_FLAG_TRIAL_ID} {trial_id}"
    if journal_dir and journal_dir != DEFAULT_TRIAL_JOURNAL_DIR:
        command += f" {_FLAG_JOURNAL_DIR} {shlex.quote(journal_dir)}"
    return command


def parse_recovery_args(argv: Any) -> Tuple[Optional[Dict[str, Optional[str]]],
                                            Optional[str]]:
    """Strict, fail-closed parse of a recovery invocation's argv.

    Returns `(options, None)` for a recognized shape, or `(None, message)` for ANY
    other input. DENY BY DEFAULT: there is no branch that ignores an argument it
    does not recognize and proceeds anyway. This package has already shipped that
    defect once — an unrecognized `--checkonly` probe was silently dropped and the
    wrapper ran the live job regardless — and here the payload is a live write.
    """
    args = list(argv or ())
    options: Dict[str, Optional[str]] = {_FLAG_TRIAL_ID: None,
                                        _FLAG_JOURNAL_DIR: None}
    index = 0
    while index < len(args):
        flag = args[index]
        if flag not in options:
            return None, f"unrecognized argument {flag!r}.\n\n{USAGE}"
        if index + 1 >= len(args):
            return None, f"{flag} needs a value.\n\n{USAGE}"
        options[flag] = args[index + 1]
        index += 2
    if not (options[_FLAG_TRIAL_ID] or "").strip():
        return None, f"missing required {_FLAG_TRIAL_ID}.\n\n{USAGE}"
    return options, None


class TrialRecoveryError(Exception):
    """A fail-closed refusal to START a recovery, raised before anything external
    has been touched.

    An exception rather than a returned value, matching `TrialJournalError` and
    `TrialExecutorError`: every condition raised here means the recovery cannot be
    attempted at all, and failing loudly is strictly safer than a soft "no" a
    caller might treat as advisory. A refusal here is NEVER an all-clear — the
    units it could not reach may still be changed on the operator's live record —
    so no message raised from this module claims that nothing is outstanding.
    """


@dataclass(frozen=True)
class RecoveredUnit:
    """What the recovery run established about ONE unit.

    `undo_restored` is three-valued on purpose. True and False are OBSERVED
    verdicts; None means the question could not be answered at all — the reversal
    raised, the surface could not be read, or the adapter's predicate raised.
    "The question could not be asked" and "the answer is no" are different facts
    and None is never treated as either verdict anywhere below.

    `observed_poststate` is the DIAGNOSIS a `False` verdict carries: what was
    actually seen on the surface, so the next reader gets a diagnosis rather than
    a bare verdict. None when nothing could be observed.
    """

    unit_id: str
    state_before: str
    state_after: str
    undo_restored: Optional[bool] = None
    observed_poststate: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class RecoveryOutcome:
    """The typed result of a recovery run. `ok` is True only when NOTHING is left
    outstanding: every unit that could still have been changed is recorded back at
    its prior state, on the strength of an observation.

    Typed rather than prose so a caller (and any operator-facing narration built
    over it) reports what actually happened instead of re-deriving it from a
    sentence. Deliberately carries no `proof_path` field: a recovery run cannot
    produce a proof, and a field for one would invite a future caller to look for
    it.
    """

    ok: bool
    trial_id: str
    journal_path: str
    summary: str
    units: Tuple[RecoveredUnit, ...] = ()
    restored_unit_ids: Tuple[str, ...] = ()
    recovery_required_unit_ids: Tuple[str, ...] = ()
    never_applied_unit_ids: Tuple[str, ...] = ()
    already_settled_unit_ids: Tuple[str, ...] = ()
    next_command: Optional[str] = None


# ---------------------------------------------------------------------------
# Rebuilding a unit from its capsule — from disk alone, never by re-planning
# ---------------------------------------------------------------------------

def _unit_from_capsule(unit_id: str, capsule: Dict[str, Any]) -> EffectUnit:
    """Rebuild the `EffectUnit` for `unit_id` from its recovery capsule.

    This is what the capsule exists for. The alternative — calling the adapter's
    `plan()` again — is not available to a recovery path even in principle: a
    second plan is a second OBSERVATION of a surface the trial has already
    mutated, so it could hand back units describing the post-apply world and the
    reversal would then restore to the wrong prior state.

    The capsule's own keys are read through the journal's constants, not
    re-spelled. Its contents have already been validated as a conforming capsule
    for this unit by the journal's fail-closed read, so the values are present and
    the undo reference is non-null.

    DISCLOSED BOUND: `target_ref` / `undo_ref` here are the JSON ROUND TRIP of
    what the adapter originally planned, because that is what the capsule is — an
    explicitly JSON-safe rendering, made durable before the first mutation. A
    tuple the adapter planned therefore arrives back as a list. For an adapter
    that reads its own references as data this is faithful; one that requires a
    specific Python container type would fail the reversal, and that failure lands
    `recovery_required` with the raised error named. It is fail-closed rather than
    silent, and the fix is on the adapter's side of a contract it owns.
    """
    return EffectUnit(
        unit_id=unit_id,
        target_ref=capsule[CAPSULE_KEY_TARGET_REF],
        undo_ref=capsule[CAPSULE_KEY_UNDO_REF],
    )


# ---------------------------------------------------------------------------
# The per-unit convergence — the ONE place this module mutates anything
# ---------------------------------------------------------------------------

def _converge_unit(journal: Any, dispatch: Any, op_kind: str, unit: Any,
                   lineage: Any, state_before: str, *, write_client: Any,
                   facade: Any,
                   unverifiable_reason: Optional[str] = None) -> RecoveredUnit:
    """Reverse one unit, observe the surface, and record the verdict the
    observation supports — and nothing stronger than that.

    THE ONLY function in this module that mutates anything, and the only
    `undo_one` call site. That is deliberate rather than incidental: the
    unverifiable case (the read path or the verification lineage unavailable) is
    handled INSIDE this function rather than by a sibling that repeats the
    reversal, because a second reversal path would be a second copy of the
    write-ahead ordering below — two paths that would have to agree about the one
    thing that must never be got wrong.

    The two clients are KEYWORD-ONLY, and that is a safety property rather than a
    style choice: the one mistake with real consequences here is transposing them,
    handing the observer a write-capable client. As keyword-only parameters the
    interpreter refuses it, which removes the route instead of detecting it.

    THE WRITE-AHEAD ORDER, and the one case that needs care. A unit already at
    `undo_intent` has its authorizing record on disk — a previous attempt wrote it
    and then died — and the journal correctly refuses to write it again. So the
    intent is recorded only when the unit is not already there, and then the
    DURABLE state is re-read from disk and required to be `undo_intent` before the
    reversal is issued. That check is the actual guarantee: it asserts the END
    STATE on disk rather than trusting that a call was made, so neither a refused
    transition nor a partially-written record can lead to a mutation whose
    authorizing record is not already durable.

    `unverifiable_reason`, when set, means the result of the reversal cannot be
    checked at all. The reversal is STILL issued (see residual 2 in the module
    docstring — a possibly-outstanding mutation left in place is the harm this
    exists to prevent) and the unit lands `recovery_required` with the reason
    named. It is never a blind pass: nothing here records a restore it did not
    observe.
    """
    unit_id = unit.unit_id
    reasons: List[str] = []
    if unverifiable_reason:
        reasons.append(unverifiable_reason)

    def _blocked(reason: str, **fields: Any) -> RecoveredUnit:
        reasons.append(reason)
        joined = " | ".join(reasons)
        journal.record_recovery_required(unit_id, reason=joined)
        return RecoveredUnit(
            unit_id=unit_id, state_before=state_before,
            state_after=journal.unit_state(unit_id), reason=joined, **fields)

    if state_before != STATE_UNDO_INTENT:
        journal.record_undo_intent(unit_id)

    # Read FRESH from disk. The journal holds no cached copy, so this is the
    # durable record as any other process would find it.
    authorized_state = journal.unit_state(unit_id)
    if authorized_state != STATE_UNDO_INTENT:
        return _blocked(
            f"the durable record for unit {unit_id!r} of {op_kind!r} is at "
            f"{authorized_state!r}, not {STATE_UNDO_INTENT!r}, so the write-ahead "
            "record that would authorize reversing it is not on disk. Nothing was "
            "reversed for this unit.")

    try:
        dispatch.undo_one(dispatch.instance, write_client, unit)
    except Exception as exc:
        return _blocked(
            f"undo_one raised reversing unit {unit_id!r} of {op_kind!r} "
            f"({exc!r}), so the unit may still be changed on the real surface "
            "and needs attention")

    if unverifiable_reason:
        return _blocked(
            f"unit {unit_id!r} of {op_kind!r} was reversed, but the result could "
            "not be checked, so it is NOT recorded as restored")

    poststate, reason = observe_unit(dispatch, unit, op_kind, facade=facade)
    if reason is not None:
        return _blocked(reason)

    undo_restored, reason = evaluate_evidence_predicate(
        dispatch, UNDO_PREDICATE_NAME,
        unit_evidence(op_kind, unit_id, poststate, lineage))
    if undo_restored is not True:
        return _blocked(
            reason or (
                f"the observed evidence does not show unit {unit_id!r} of "
                f"{op_kind!r} back at its prior state after the reversal "
                f"({UNDO_PREDICATE_NAME} returned {undo_restored!r}), so it needs "
                "attention"),
            undo_restored=undo_restored, observed_poststate=poststate)

    # The one condition under which the settled state may be recorded: the prior
    # state was OBSERVED, and the adapter's own absolute post-condition agreed.
    journal.record_restored_verified(unit_id)
    return RecoveredUnit(
        unit_id=unit_id, state_before=state_before,
        state_after=journal.unit_state(unit_id), undo_restored=True,
        observed_poststate=poststate)


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------

def recover_trial(trial_id: str, *,
                  journal_dir: Optional[str] = None,
                  client: Any = None,
                  read_only_client: Any = None,
                  lib_dir: Optional[str] = None) -> RecoveryOutcome:
    """Bring every possibly-outstanding unit of trial `trial_id` back to its prior
    state, confirm it from an observation, and report what is left.

    Everything it needs comes from the journal on disk: the operation kind, the
    units, and each unit's prior state. No plan, no `Operation`, no effect units
    and no in-memory state from the interrupted run are required or accepted —
    that is the point, because a fresh process after a kill has none of them.

    Parameters
    ----------
    trial_id:
        the interrupted trial. It appears in the durable record's own path, which
        the trial executor's refusal names.
    journal_dir:
        override for a caller (a test above all) that must not depend on ambient
        project state. The default is the production convention.
    client / read_only_client:
        optional fallbacks, used only for an adapter that does not provision its
        own clients — exactly as the ordinary write path and the trial executor
        use them, resolved through the SAME shared resolvers so recovery obtains
        its credentials by the rule production obtains them by.
    lib_dir:
        override for the directory scanned to find which module declares the
        read-only reader for this operation kind. Defaults to the kernel's own
        location, which is where the import will load from.

    Returns
    -------
    A `RecoveryOutcome`. `ok` is True only when nothing is left outstanding.

    Raises
    ------
    `TrialJournalError` when the durable record is absent, unreadable or
    malformed — propagated unchanged, because it already names the problem
    exactly and an absent recovery record must never be read as "nothing was
    applied". `TrialRecoveryError` when the recovery cannot be attempted at all,
    always before anything external is touched.
    """
    journal = load_trial_journal(trial_id, journal_dir=journal_dir)
    record = journal.read_record()
    op_kind = record["op_kind"]

    # The recorded target must be the bounded trial target. A journal is only ever
    # created from an authorization for that target, so anything else means the
    # record was not produced by the trial protocol -- and the narrow bound on
    # what a journal authorizes (see the module docstring) rests on this holding.
    resolved_target = record.get("resolved_target")
    if resolved_target != TRIAL_TARGET:
        raise TrialRecoveryError(
            f"the durable record at {journal.path!r} says it ran against target "
            f"{resolved_target!r}, but a trial runs against {TRIAL_TARGET!r} and "
            "nothing else. This record was not produced by the trial protocol, "
            "so it is refused rather than acted on. Nothing was reversed.")

    states = journal.unit_states()
    driven = [unit_id for unit_id in journal.unit_ids()
              if states[unit_id] in RECOVERY_DRIVEN_STATES]
    never_applied = tuple(unit_id for unit_id in journal.unit_ids()
                          if states[unit_id] not in RECOVERY_DRIVEN_STATES
                          and states[unit_id] != STATE_RESTORED_VERIFIED)
    already_settled = tuple(unit_id for unit_id in journal.unit_ids()
                            if states[unit_id] == STATE_RESTORED_VERIFIED)

    if not driven:
        return RecoveryOutcome(
            ok=True, trial_id=journal.trial_id, journal_path=journal.path,
            never_applied_unit_ids=never_applied,
            already_settled_unit_ids=already_settled,
            summary=(
                f"nothing to recover for trial {journal.trial_id!r}: every unit "
                "it applied is already recorded back at its prior state, and no "
                "other unit was ever applied. "
                f"{REFUSAL_MARKER_NOTHING_OUTSTANDING}."))

    dispatch = get_dispatch(op_kind)
    if dispatch is None:
        raise TrialRecoveryError(
            f"no adapter is registered for {op_kind!r}, so there is nothing to "
            f"reverse the units of trial {journal.trial_id!r} with. Fix step: "
            "enroll this capability's adapter module so it registers at import "
            "time, then run this command again. Nothing was reversed, and the "
            f"units still needing attention are {driven}.")

    # The WRITE side first, and it is a hard refusal: without a connection able to
    # make the change there is no reversal to perform at all, so refusing before
    # anything is touched is the whole of the honest response.
    try:
        write_client = resolve_write_client(dispatch, None, fallback=client)
    except Exception as exc:
        raise TrialRecoveryError(
            f"a connection able to reverse {op_kind!r} could not be obtained "
            f"({exc!r}). Nothing was reversed, and the units still needing "
            f"attention are {driven}.") from exc
    if write_client is None:
        raise TrialRecoveryError(
            f"no connection able to reverse {op_kind!r} is available -- the "
            "adapter does not provide one and none was supplied -- so the units "
            f"of trial {journal.trial_id!r} cannot be brought back. Nothing was "
            f"reversed, and the units still needing attention are {driven}.")

    # The READ side is resolved best-effort, NOT as a precondition, and the
    # ordering is a deliberate divergence from the trial executor. There, an
    # unobservable surface refuses before any mutation, because nothing has
    # happened yet. Here a unit may be outstanding on the operator's live record
    # right now, so the reversal is worth issuing even when its result cannot be
    # confirmed: the unconfirmed verdict then lands `recovery_required`, which is
    # correct and fail-closed, and the surface has still converged.
    facade, facade_reason = _read_facade(op_kind, dispatch,
                                        fallback=read_only_client,
                                        lib_dir=lib_dir)
    lineage, lineage_reason = _lineage(op_kind)

    unverifiable = None if (facade is not None and lineage is not None) \
        else (facade_reason or lineage_reason)

    results: List[RecoveredUnit] = []
    for unit_id in driven:
        state_before = states[unit_id]
        unit = _unit_from_capsule(unit_id, journal.recovery_capsule(unit_id))
        results.append(_converge_unit(
            journal, dispatch, op_kind, unit, lineage, state_before,
            write_client=write_client, facade=facade,
            unverifiable_reason=unverifiable))

    restored = tuple(r.unit_id for r in results
                     if r.state_after == STATE_RESTORED_VERIFIED)
    outstanding = tuple(r.unit_id for r in results
                        if r.state_after == STATE_RECOVERY_REQUIRED)
    if outstanding:
        return RecoveryOutcome(
            ok=False, trial_id=journal.trial_id, journal_path=journal.path,
            units=tuple(results), restored_unit_ids=restored,
            recovery_required_unit_ids=outstanding,
            never_applied_unit_ids=never_applied,
            already_settled_unit_ids=already_settled,
            next_command=recovery_command(journal.trial_id,
                                          journal_dir=journal_dir),
            summary=_outstanding_summary(journal, results, outstanding,
                                         journal_dir=journal_dir))
    return RecoveryOutcome(
        ok=True, trial_id=journal.trial_id, journal_path=journal.path,
        units=tuple(results), restored_unit_ids=restored,
        never_applied_unit_ids=never_applied,
        already_settled_unit_ids=already_settled,
        summary=(
            f"every unit of trial {journal.trial_id!r} that could still have "
            "been changed is now recorded back at its prior state, confirmed by "
            f"reading the real surface: {list(restored)}. "
            f"{REFUSAL_MARKER_NOTHING_OUTSTANDING}. The durable record is "
            f"{journal.path}."))


def _outstanding_summary(journal: Any, results: List[RecoveredUnit],
                         outstanding: Tuple[str, ...], *,
                         journal_dir: Optional[str]) -> str:
    """The operator-facing sentence for a run that could not bring everything
    back — and it must say the RIGHT one of the two things.

    `REFUSAL_MARKER_NOT_RESTORED` is reused rather than re-worded, and it is
    mutually exclusive with `REFUSAL_MARKER_NOTHING_OUTSTANDING` by construction.
    Inventing a third phrasing for recovery would recreate the two-surfaces-that-
    must-agree defect, and telling an operator that nothing is outstanding while a
    unit is durably changed on their live record is the false safety claim that
    makes someone stop looking.

    It NAMES the repair. A durable blocking record with no command attached is a
    verdict handed to someone who cannot act on it.
    """
    causes = "; ".join(
        f"{r.unit_id}: {r.reason}" for r in results if r.reason)
    return (
        f"trial {journal.trial_id!r} is not fully recovered: "
        f"{REFUSAL_MARKER_NOT_RESTORED} — these are not: {list(outstanding)}. "
        f"They may still be changed on the real surface. What was observed: "
        f"{causes}. The durable record of what happened to each unit is "
        f"{journal.path}. When the cause above is resolved, run this again and it "
        "will reverse them again and re-check:\n"
        + recovery_command(journal.trial_id, journal_dir=journal_dir))


def _read_facade(op_kind: str, dispatch: Any, *, fallback: Any,
                 lib_dir: Optional[str]) -> Tuple[Any, Optional[str]]:
    """A READ-ONLY facade over `op_kind`'s surface, or `(None, reason)`.

    The facade class is resolved by `build_read_facade` from the kernel read-facade
    registry, exactly as the trial executor and the ordinary post-write
    verification path resolve it — ONE resolution, not a second one here.

    What this adds is the step a FRESH process needs and a warm one does not:
    POPULATING that registry. Nothing in production imports a read-facade module
    at module scope; the registry is populated only by such an import, and in the
    ordinary flow the proposal step has already caused it. A recovery command runs
    in a process where nothing has — so a driver that assumed a warm registry
    would fail to observe on EVERY real invocation, and a unit could then never
    leave `recovery_required`, which is precisely the dead end this protocol exists
    to remove.

    The population goes through the ONE shared resolver
    (`capability_runner.import_declared_read_facade`): the declaration topology
    names which module declares a reader for this op_kind, and that module is
    imported. It is attempted only when the registry has no entry, so a caller that
    has already imported the declaring module — or registered a facade directly,
    which the kernel and its tests both do — is unaffected.

    Returns a reason instead of raising, because an unobservable surface must not
    stop the reversal — see residual 2 in the module docstring.
    """
    from external_write.read_facade import get_read_facade_class

    if get_read_facade_class(op_kind) is None:
        try:
            import_declared_read_facade(op_kind, lib_dir=lib_dir)
        except ReadFacadeDeclarationError as exc:
            return None, (
                f"the reader for {op_kind!r} is declared in {exc.relpath} but "
                f"could not be loaded ({exc}), so the real surface cannot be "
                "checked")
        except Exception as exc:  # noqa: BLE001 -- reported, never swallowed.
            return None, (
                f"the reader for {op_kind!r} could not be resolved ({exc!r}), so "
                "the real surface cannot be checked")
    try:
        effective_read_only_client = resolve_read_only_client(
            dispatch, None, fallback=fallback)
    except Exception as exc:
        return None, (
            f"a read-only connection for {op_kind!r} could not be obtained "
            f"({exc!r}), so the real surface cannot be checked")
    if effective_read_only_client is None:
        return None, (
            f"no read-only connection is available for {op_kind!r} -- the adapter "
            "does not provide one and none was supplied -- so the real surface "
            "cannot be checked")
    try:
        return build_read_facade(op_kind, effective_read_only_client), None
    except ReadFacadeEligibilityError as exc:
        return None, (
            f"{op_kind!r} cannot be observed through a read-only facade "
            f"({exc}), so the real surface cannot be checked")


def _lineage(op_kind: str) -> Tuple[Any, Optional[str]]:
    """The ONE lineage declaration a trial's observations rest on, resolved from
    `op_kind` through the trial executor's own `trial_source_lineage`.

    Shared rather than rebuilt, because the lineage is part of the evidence the
    adapter's predicate is handed: a recovery run that declared a different
    lineage from the one the trial declared would be asking the same predicate a
    subtly different question.

    Returns a reason instead of raising for the same reason `_read_facade` does.
    The failure is not hypothetical-only: the lineage resolves through the
    op_kind's registered contract and verifier, and a journal can outlive a
    registration change. When it cannot be resolved the unit is still reversed and
    lands `recovery_required` — never silently green.
    """
    try:
        return trial_source_lineage(op_kind), None
    except Exception as exc:
        return None, (
            f"the verification lineage for {op_kind!r} could not be resolved "
            f"({exc!r}), so an observation of the surface could not be judged")


# ---------------------------------------------------------------------------
# CLI -- the operator-invocable exit from `recovery_required`.
#
# Kernel-side, like every other operator entrypoint in this package, and for the
# same reason: every place an operator project could put an emitted script is
# CAPABILITY-zoned, where obtaining a write client is a scan violation. The kernel
# already holds the only legitimate wiring, so it holds the entrypoint too.
#
# Never prints a traceback -- a non-technical operator reads this output.
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    # A freshly-invoked process has imported no adapter module, so `get_dispatch`
    # would resolve None for an op_kind whose adapter IS enrolled. Importing this
    # module fires every shipped and every operator-enrolled adapter module's
    # registration. Done HERE, inside `__main__`, and not at this module's top
    # level: this module is imported as a library by the trial executor's refusal
    # path, which must not eagerly register every adapter as a side effect. Same
    # placement, for the same reason, as the acceptance CLI's own import of it.
    import external_write.registered_adapters  # noqa: E402,F401

    _options, _error = parse_recovery_args(_sys.argv[1:])
    if _error is not None:
        print(_error, file=_sys.stderr)
        _sys.exit(EXIT_BAD_ARGS)

    try:
        _outcome = recover_trial(_options[_FLAG_TRIAL_ID],
                                journal_dir=_options[_FLAG_JOURNAL_DIR])
    except (TrialRecoveryError, TrialJournalError) as _exc:
        # A refusal, in plain language, and NOT an all-clear: whatever it could
        # not reach may still be changed on the operator's record. Exit 1, so
        # nothing checking the status reads it as success.
        print(str(_exc), file=_sys.stderr)
        _sys.exit(EXIT_RECOVERY_REQUIRED)

    print(_outcome.summary)
    _sys.exit(EXIT_RESTORED if _outcome.ok else EXIT_RECOVERY_REQUIRED)
