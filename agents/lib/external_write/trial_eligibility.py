"""Trial-eligibility preflight — the fail-closed gate that decides which
operations may LEGALLY undergo a journaled TRIAL (Cut 1.9 Task 1, Phase A1' —
v0.23.0).

A capability could already be made fully compliant and still not be acceptable,
because acceptance requires a `copy_run_proof` and no zone-legal driver existed
to produce one: nothing drove `apply -> verify -> undo -> verify-restored`
against a real surface from the sealed kernel. Cut 1.9 builds that driver (the
write-ahead journal, the trial executor, and the recovery path — later tasks in
this cut). THIS module is the gate that runs FIRST, before any external write,
and decides whether a given operation may be trialled at all. Everything
downstream trusts its verdict, so every clause here is a positive declaration
that must be made explicitly: silence, absence, a malformed value, or an empty
plan all REFUSE.

------------------------------------------------------------------------------
The four clauses (all must pass), plus the plan-integrity precondition
------------------------------------------------------------------------------
  (a) CLAUSE_UNDO_REF_PRESENT — every planned `EffectUnit` carries a non-None
      `undo_ref`. A trial must be able to reverse EVERY unit it applies; one
      irreversible unit makes the whole plan untrialable, because the trial
      would leave the operator's real surface mutated with no way back.

  (b) CLAUSE_EVIDENCE_PREDICATES_DECLARED — the registered adapter declares
      every name in `evidence.REQUIRED_EVIDENCE_PREDICATES`
      (`verify_apply_landed`, `verify_undo_restored`) as a CALLABLE captured on
      its dispatch record. The trial ends by asking the adapter whether the
      OBSERVED live state was restored; without those predicates there is
      nothing to ask, and "restored" would be an assertion rather than
      something earned from evidence. The required names are READ from that
      canonical constant, never re-listed here — re-listing is the defect class
      this codebase has shipped five times (see that constant's own docstring,
      and the coupling test that patches the module attribute and asserts every
      consumer picks the change up).

  (c) CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE — the adapter declares
      `UNDO_IS_ABSOLUTE_STATE_RESTORE = True` (resolved through
      `adapter_registry.UNDO_IDEMPOTENCY_DECLARATION_ATTR`, captured off the
      class at registration). WHY the trial needs this specifically: after a
      crash the journal can only say the apply was INTENDED — it cannot say
      whether the mutation landed — so the recovery path runs `undo_one`
      regardless, and may run it more than once. An ABSOLUTE-state restore
      (write the recorded prior value; set the exact prior label set) converges
      to the same prior state under both conditions. A RELATIVE compensating
      action (delete what was created, subtract what was added) does not:
      repeating it can destroy state the trial never touched. So a relative
      undo is refused a trial rather than trusted with one.

  (d) CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE — every planned unit has a recovery
      capsule that survives a real `json.dumps` round trip. The journal is JSON
      on disk, written BEFORE the mutation; a capsule that cannot be written
      (or cannot be read back faithfully) means a crash leaves a unit that
      nothing can restore. Checked by actually serializing — never by an
      isinstance guess — and never with pickle.

  CLAUSE_PLAN_INTEGRITY (precondition) — the plan is non-empty and every unit
      is a real `EffectUnit` with a unique, usable `unit_id`. Without this,
      clause (a)'s "every unit" is a vacuous quantifier over an empty set (the
      textbook pass-by-default), and a duplicate `unit_id` silently collapses
      two mutations into one journal entry and one capsule — so one of them
      would never be undone.

------------------------------------------------------------------------------
What this module does NOT do, and does not claim
------------------------------------------------------------------------------
  * It performs NO external write, NO external read, and NO disk I/O. It reads
    the frozen dispatch record, the planned units, and the capsules it was
    handed. Nothing else.
  * It does NOT prove idempotency. Clause (c) is a DECLARATION check: nothing
    here (or anywhere in this package) can verify that a declaring adapter's
    `undo_one` really is absolute-state — that is a property of the vendor call
    it makes. A false declaration surfaces as a trial whose
    `verify_undo_restored` post-condition fails, or as the recovery path's
    `recovery_required` outcome — never as a silent pass. This bound is
    disclosed, not papered over.
  * It does NOT authorize anything. Eligibility is a precondition of
    authorization, not a substitute for it: the trial still runs through the
    EXISTING live-bounded authorization funnel (receipt, blast-radius cap,
    invocation ledger, aggregate ceiling). Nothing here relaxes any of that.
  * The ceiling is UNCHANGED: build-time enforcement plus operator-as-approver.
    This is not a runtime sandbox and not an OS-level control. A determined
    hand-edit of an adapter class can declare clause (c) falsely, exactly as it
    could always mis-implement `undo_one`.

------------------------------------------------------------------------------
Callers
------------------------------------------------------------------------------
`check_trial_eligibility` is the single entry point. The trial authorization
step (Cut 1.9 Task 2) calls it between `plan` and `authorize`, and binds its
AuthorizedPlan to the `units` this verdict echoes back — never to a
re-derived plan, which would allow a check-then-swap. Until that task lands,
this module has no production caller (the same convention `evidence.py` used
when it shipped the evidence TYPE one task ahead of the kernel wiring that
consumes it). It is complete and functional as it stands: there are no stubs
here, and nothing to wire up later inside this file.

Zone: SEALED_KERNEL (enumerated in `zones.py`). It reads sibling kernel
submodules (`adapter_registry`, `evidence`, `operations`) as ordinary internal
kernel wiring, imports no vendor SDK, constructs no credential, performs no
vendor mutation, and never calls `run_operation`.

Stdlib only — no third-party dependencies.
"""

import json
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from external_write import evidence
from external_write.adapter_registry import (
    UNDO_IDEMPOTENCY_DECLARATION_ATTR, AdapterDispatch, get_dispatch,
)
from external_write.operations import EffectUnit


# ---------------------------------------------------------------------------
# Clause identifiers. Stable, machine-readable names a caller (and a test) can
# assert on individually — never a single lumped "ineligible" boolean, because
# two independent clauses refusing the same op_kind is a property the design
# wants to be able to observe and keep.
# ---------------------------------------------------------------------------
CLAUSE_PLAN_INTEGRITY = "plan_integrity"
CLAUSE_UNDO_REF_PRESENT = "undo_ref_present"
CLAUSE_EVIDENCE_PREDICATES_DECLARED = "evidence_predicates_declared"
CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE = "undo_absolute_state_restore"
CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE = "recovery_capsule_serializable"

# Canonical evaluation + reporting order. Every clause is ALWAYS evaluated (the
# gate never short-circuits), and refusals are reported in this order, so a
# caller rendering them gets a stable sequence and a fix for one clause cannot
# hide another that is still broken.
TRIAL_ELIGIBILITY_CLAUSES: Tuple[str, ...] = (
    CLAUSE_PLAN_INTEGRITY,
    CLAUSE_UNDO_REF_PRESENT,
    CLAUSE_EVIDENCE_PREDICATES_DECLARED,
    CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE,
    CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE,
)


@dataclass(frozen=True)
class ClauseRefusal:
    """One clause's refusal, with the plain-language reason handed to whoever
    has to act on it.

    `reason` follows the convention `capability_invariants` already established
    for operator/agent-facing refusals: what is wrong, why it blocks a trial,
    and a concrete "Fix step:". It names the specific unit_id or predicate name
    at fault — a refusal that says only "something is not serializable" is not
    actionable.
    """

    clause: str
    reason: str


@dataclass(frozen=True)
class TrialEligibility:
    """The verdict. `eligible` is True IFF `refusals` is empty — there is no
    other path to eligibility in this module.

    `units` echoes back exactly the units that were checked, so the caller can
    bind its authorized plan to them instead of re-deriving a plan the gate
    never saw.
    """

    op_kind: str
    eligible: bool
    refusals: Tuple[ClauseRefusal, ...]
    units: Tuple[Any, ...]

    @property
    def failed_clauses(self) -> Tuple[str, ...]:
        """Which CLAUSES refused, each named once, in canonical clause order.

        De-duplicated deliberately: a plan with three irreversible units
        produces three refusals (one per unit — a caller needs to know WHICH
        units, and a single lumped message would hide two of them) but that is
        still one clause failing. `refusals` carries the per-unit detail; this
        answers "which clauses refused".
        """
        ordered: List[str] = []
        for refusal in self.refusals:
            if refusal.clause not in ordered:
                ordered.append(refusal.clause)
        return tuple(ordered)

    def reason_text(self) -> str:
        """Every refusal reason, one per line, in canonical clause order. Empty
        string when eligible."""
        return "\n".join(r.reason for r in self.refusals)


def _clause_sort_key(refusal: ClauseRefusal) -> int:
    try:
        return TRIAL_ELIGIBILITY_CLAUSES.index(refusal.clause)
    except ValueError:  # pragma: no cover - unreachable: every clause is listed
        return len(TRIAL_ELIGIBILITY_CLAUSES)


def _usable_unit_id(unit_id: Any) -> bool:
    """A unit_id must be a non-blank string: the journal keys every per-unit
    state on it, and the recovery-capsule set is keyed by it. A non-string (or
    blank) id cannot survive that round trip as itself."""
    return isinstance(unit_id, str) and bool(unit_id.strip())


def _check_plan_integrity(op_kind: str, units: Sequence[Any]) -> List[ClauseRefusal]:
    refusals: List[ClauseRefusal] = []
    if not units:
        refusals.append(ClauseRefusal(
            CLAUSE_PLAN_INTEGRITY,
            f"Plan integrity: operation kind {op_kind!r} planned no effect units, "
            "so a trial would apply nothing, undo nothing, and observe nothing — "
            "it cannot produce the restoration evidence a trial exists to produce. "
            "Fix step: plan at least one effect unit before requesting a trial."))
        return refusals

    seen = {}
    for index, unit in enumerate(units):
        if not isinstance(unit, EffectUnit):
            refusals.append(ClauseRefusal(
                CLAUSE_PLAN_INTEGRITY,
                f"Plan integrity: planned entry #{index} for {op_kind!r} is not an "
                f"EffectUnit (it is a {type(unit).__name__}). The trial journal and "
                "every clause below read a unit's unit_id and undo_ref off an "
                "EffectUnit. Fix step: return EffectUnit records from the adapter's "
                "plan()."))
            continue
        if not _usable_unit_id(unit.unit_id):
            refusals.append(ClauseRefusal(
                CLAUSE_PLAN_INTEGRITY,
                f"Plan integrity: planned unit #{index} for {op_kind!r} has an "
                f"unusable unit_id ({unit.unit_id!r}). The trial journal keys every "
                "per-unit state on unit_id, and it is written to and read back from "
                "JSON, so it must be a non-blank string. Fix step: give every "
                "EffectUnit a non-blank string unit_id, unique within its "
                "operation."))
            continue
        seen[unit.unit_id] = seen.get(unit.unit_id, 0) + 1

    for unit_id, count in seen.items():
        if count > 1:
            refusals.append(ClauseRefusal(
                CLAUSE_PLAN_INTEGRITY,
                f"Plan integrity: unit_id {unit_id!r} appears {count} times in the "
                f"plan for {op_kind!r}. The trial journal and the recovery-capsule "
                "set both key on unit_id, so duplicate ids collapse two distinct "
                "mutations into one journal entry and one capsule — one of them "
                "would be applied and never undone. Fix step: make every "
                "EffectUnit's unit_id unique within its operation."))
    return refusals


def _check_undo_refs(op_kind: str, units: Sequence[Any]) -> List[ClauseRefusal]:
    refusals: List[ClauseRefusal] = []
    for unit in units:
        if not isinstance(unit, EffectUnit):
            continue  # already refused by the plan-integrity clause
        if unit.undo_ref is None:
            refusals.append(ClauseRefusal(
                CLAUSE_UNDO_REF_PRESENT,
                f"Reversibility: unit {unit.unit_id!r} of {op_kind!r} plans "
                "undo_ref=None, so the adapter has supplied nothing with which to "
                "reverse it. A trial must be able to undo EVERY unit it applies — "
                "otherwise it leaves the real surface mutated with no way back. "
                "Fix step: have the adapter's plan() carry an undo_ref for every "
                "unit; if this operation kind genuinely has no reversal (a "
                "create-only action whose only reverse is a delete), it cannot be "
                "trialled and must reach acceptance another way."))
    return refusals


def _check_evidence_predicates(op_kind: str,
                               dispatch: Optional[AdapterDispatch],
                               ) -> List[ClauseRefusal]:
    # Required NAMES come from the ONE canonical source. Never re-listed here:
    # see evidence.REQUIRED_EVIDENCE_PREDICATES' own docstring, and the module
    # reference convention it mandates (module attribute, not a name-import, so
    # a change is visible to every consumer at call time).
    required = tuple(evidence.REQUIRED_EVIDENCE_PREDICATES)
    if dispatch is None:
        return [ClauseRefusal(
            CLAUSE_EVIDENCE_PREDICATES_DECLARED,
            f"Evidence predicates: operation kind {op_kind!r} has no registered "
            f"adapter, so nothing has declared {'/'.join(required)}. A trial ends "
            "by asking the adapter whether the observed live state was restored; "
            "with no adapter there is nothing to ask. Fix step: register an "
            "adapter for this operation kind (a seeded field operation has none "
            "by design and cannot be trialled through the adapter path).")]

    missing = [name for name in required
               if not callable(getattr(dispatch, name, None))]
    if not missing:
        return []
    return [ClauseRefusal(
        CLAUSE_EVIDENCE_PREDICATES_DECLARED,
        f"Evidence predicates: the registered adapter for {op_kind!r} does not "
        f"declare {'/'.join(missing)} as a callable method. The trial asks those "
        "predicates whether the observed live state shows the apply landed and "
        "the undo restored the prior state — a 'restored' claim must be earned "
        "from observed evidence, not asserted. Fix step: add the named method(s) "
        "to the adapter class, each taking the AdapterEvidence the kernel "
        "captured and returning bool. (A required name declared as a plain "
        "attribute rather than a method is refused here too: it can never be "
        "called.)")]


def _check_absolute_state_restore(op_kind: str,
                                  dispatch: Optional[AdapterDispatch],
                                  ) -> List[ClauseRefusal]:
    if dispatch is None:
        return [ClauseRefusal(
            CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE,
            f"Absolute-state undo: operation kind {op_kind!r} has no registered "
            "adapter, so nothing has declared "
            f"{UNDO_IDEMPOTENCY_DECLARATION_ATTR} = True. Fix step: register an "
            "adapter for this operation kind.")]

    declared = dispatch.undo_is_absolute_state_restore
    # Strict identity against the boolean True. A truthy non-boolean ("yes", 1,
    # a non-empty list) is a MALFORMED declaration, and a malformed declaration
    # at a gate that authorizes an external write is not consent — there is no
    # latitude here.
    if declared is True:
        return []
    if declared is None:
        observed = (f"the adapter class declares no "
                    f"{UNDO_IDEMPOTENCY_DECLARATION_ATTR} at all")
    elif declared is False:
        observed = (f"the adapter class declares "
                    f"{UNDO_IDEMPOTENCY_DECLARATION_ATTR} = False")
    else:
        observed = (f"the adapter class declares "
                    f"{UNDO_IDEMPOTENCY_DECLARATION_ATTR} = {declared!r}, which is "
                    "not the boolean True")
    return [ClauseRefusal(
        CLAUSE_UNDO_ABSOLUTE_STATE_RESTORE,
        f"Absolute-state undo: {observed}, so the kernel must assume undo_one is "
        "a relative, compensating action (delete what was created, subtract what "
        "was added). After a crash the trial journal can only say the apply was "
        "INTENDED — never whether it landed — so recovery runs undo_one anyway, "
        "and may run it more than once. An absolute-state restore (write the "
        f"recorded prior value; set the exact prior label set) is safe both ways; "
        "a compensating action is not, and can destroy state the trial never "
        f"touched. Fix step: if — and ONLY if — this adapter's undo_one restores "
        f"the recorded PRIOR state absolutely, declare "
        f"{UNDO_IDEMPOTENCY_DECLARATION_ATTR} = True on the adapter class. The "
        "kernel cannot check that claim, so declaring it for a compensating "
        "action is a false declaration that will surface as an unverifiable "
        "restoration mid-trial.")]


# Returned by `_first_non_string_mapping_key` to mean "every mapping key is a
# string". A SENTINEL rather than None, because `None` is itself a legal mapping
# key that json silently coerces (to the string "null") — using None as the
# not-found signal would make `{None: ...}` a false negative in a check whose
# whole job is to be fail-closed.
_NO_BAD_KEY = object()


def _first_non_string_mapping_key(value: Any) -> Any:
    """The first non-string mapping key found anywhere in `value`, else
    `_NO_BAD_KEY`.

    ADDITIONAL to — never a substitute for — the real json round trip below.
    `json.dumps({1: "a"})` SUCCEEDS and silently coerces the key to `"1"`, so a
    capsule keyed by anything but strings comes back from the journal with
    different keys than it went in with, and the resumed executor's lookup
    raises KeyError at exactly the moment recovery matters. Serializable is not
    the same as faithful.
    """
    if isinstance(value, Mapping):
        for key, sub in value.items():
            if not isinstance(key, str):
                return key
            found = _first_non_string_mapping_key(sub)
            if found is not _NO_BAD_KEY:
                return found
        return _NO_BAD_KEY
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _first_non_string_mapping_key(item)
            if found is not _NO_BAD_KEY:
                return found
    return _NO_BAD_KEY


def _check_recovery_capsules(op_kind: str, units: Sequence[Any],
                             recovery_capsules: Any) -> List[ClauseRefusal]:
    if not isinstance(recovery_capsules, Mapping):
        return [ClauseRefusal(
            CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE,
            f"Recovery capsules: the recovery capsules for {op_kind!r} were not "
            f"supplied as a mapping of unit_id -> capsule (got a "
            f"{type(recovery_capsules).__name__}), so no unit's capsule can be "
            "located at all. Fix step: pass one capsule per planned unit_id.")]

    refusals: List[ClauseRefusal] = []
    for unit in units:
        if not isinstance(unit, EffectUnit) or not _usable_unit_id(unit.unit_id):
            continue  # already refused by the plan-integrity clause
        capsule = recovery_capsules.get(unit.unit_id)
        if capsule is None:
            refusals.append(ClauseRefusal(
                CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE,
                f"Recovery capsule: no recovery capsule was supplied for unit "
                f"{unit.unit_id!r} of {op_kind!r}. The journal must be able to "
                "reconstruct that unit's undo from disk alone after a crash, so a "
                "unit with no capsule cannot be trialled. Fix step: supply one "
                "non-empty capsule per planned unit_id."))
            continue
        try:
            bad_key = _first_non_string_mapping_key(capsule)
        except RecursionError:
            # A self-referential (or pathologically deep) capsule. Deliberately
            # NOT reported from here: `json.dumps` below detects a circular
            # reference itself and names it exactly, and that refusal is the more
            # accurate one. Falling through keeps this gate's promise that bad
            # input produces a refusal, never a traceback.
            bad_key = _NO_BAD_KEY
        if bad_key is not _NO_BAD_KEY:
            refusals.append(ClauseRefusal(
                CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE,
                f"Recovery capsule: unit {unit.unit_id!r} of {op_kind!r} has a "
                f"capsule containing the non-string key {bad_key!r}. JSON silently "
                "coerces such a key to a string, so the capsule read back from the "
                "journal would not have the key the resumed executor looks up. Fix "
                "step: use string keys throughout the capsule."))
            continue
        try:
            # A REAL round trip, not a type guess: serialize with the strictness
            # the journal itself needs (allow_nan=False — the stdlib default
            # emits bare NaN/Infinity, which is not valid JSON and is rejected
            # by a strict reader) and read it back.
            json.loads(json.dumps(capsule, sort_keys=True, ensure_ascii=True,
                                  allow_nan=False))
        except (TypeError, ValueError, RecursionError) as exc:
            refusals.append(ClauseRefusal(
                CLAUSE_RECOVERY_CAPSULE_SERIALIZABLE,
                f"Recovery capsule: unit {unit.unit_id!r} of {op_kind!r} has a "
                f"capsule that does not survive a JSON round trip ({exc!r}). The "
                "trial journal is JSON on disk, written before the mutation; a "
                "capsule that cannot be written and read back leaves a crashed "
                "trial with a unit nothing can restore. Fix step: carry only "
                "JSON-representable values (no sets, no custom objects, no NaN or "
                "Infinity) in the capsule."))
    return refusals


def check_trial_eligibility(
    op_kind: str,
    units: Sequence[Any],
    recovery_capsules: Any,
) -> TrialEligibility:
    """Decide whether `op_kind`'s planned `units` may undergo a journaled trial.

    Parameters
    ----------
    op_kind:
        The operation kind. Its ADAPTER-side clauses are evaluated against the
        FROZEN dispatch record this module resolves itself
        (`adapter_registry.get_dispatch`) — a dispatch record is deliberately
        NOT accepted as an argument, so a caller cannot hand this gate a
        hand-built record that declares everything.
    units:
        The units the caller intends to execute — normally exactly what the
        adapter's `plan()` returned. The verdict echoes them back
        (`TrialEligibility.units`) so the authorization step can bind to the
        units this gate actually checked rather than re-deriving a plan.
    recovery_capsules:
        Mapping of unit_id -> recovery capsule. The capsule FORMAT is owned by
        the journal task, not by this gate: clause (d) checks only that each
        capsule survives a real JSON round trip. A `None` capsule is treated as
        absent (it carries nothing a resumed trial could use).

    Returns a `TrialEligibility` verdict. NEVER raises for bad input: malformed
    units, a malformed declaration, or non-mapping capsules all resolve to a
    REFUSAL with a plain-language reason, because a traceback out of a preflight
    is indistinguishable to a caller from a gate that failed to run.

    Every clause is evaluated — the gate never short-circuits — so a single
    verdict reports every independent reason the operation is ineligible.
    """
    unit_list: List[Any] = list(units or ())
    dispatch = get_dispatch(op_kind)

    refusals: List[ClauseRefusal] = []
    refusals.extend(_check_plan_integrity(op_kind, unit_list))
    refusals.extend(_check_undo_refs(op_kind, unit_list))
    refusals.extend(_check_evidence_predicates(op_kind, dispatch))
    refusals.extend(_check_absolute_state_restore(op_kind, dispatch))
    refusals.extend(_check_recovery_capsules(op_kind, unit_list, recovery_capsules))
    refusals.sort(key=_clause_sort_key)

    return TrialEligibility(
        op_kind=op_kind,
        eligible=not refusals,
        refusals=tuple(refusals),
        units=tuple(unit_list),
    )
