"""The journaled TRIAL EXECUTOR — the driver that makes a `copy_run_proof`
producible, and therefore operator acceptance reachable (Cut 1.9 Task 4).

------------------------------------------------------------------------------
Why this exists
------------------------------------------------------------------------------
Acceptance of a capability that writes to external state requires a
`copy_run_proof-v1` artifact demonstrating `apply -> verify -> undo ->
verify-restored`. Until this module, `copy_run_proof.py` exposed a VALIDATOR and
nothing anywhere produced the artifact it validates: no zone-legal code drove
that round trip against a real surface. A capability could be made fully
compliant and still never be acceptable — not because it failed a check, but
because the evidence its acceptance required could not be produced at all.

This module is that driver. Per unit, in this order and no other:

    apply_one  ->  verify_one (READ-ONLY facade) + verify_apply_landed
               ->  undo_one  ->  verify_one (READ-ONLY facade) + verify_undo_restored

and it emits `agents/handoffs/<capability_id>.copy_run_proof.json` ONLY after
every unit has reached the journal's `restored_verified` terminal state.

------------------------------------------------------------------------------
It is also the production CALLER two shipped mechanisms were waiting for
------------------------------------------------------------------------------
Stated plainly because a mechanism that exists off the enforced path is this
package's most-repeated defect — a provisioner hook that was `None` in every
deployment with its consuming branch never once executed; a migration nobody
invoked; a trust primitive that was an uncalled wrapper. Each shipped green,
because a test proved the FUNCTION worked.

Before this module, `write_authorization.authorize_operation`'s TRIAL branch and
the whole of `trial_journal` had exactly zero production callers. `run_trial` is
their caller, and it is the ONLY one:

  * it calls `authorize_operation(..., intent=EXECUTION_INTENT_TRIAL,
    target=TRIAL_TARGET)`. The target is fixed by this module, not accepted from
    a caller: the trial target is chosen by the kernel-driven protocol, and
    every other value is refused at authorization anyway.
  * it calls `trial_journal.open_trial_journal(plan)` UNCONDITIONALLY, before
    any client is used to mutate anything. There is no argument that supplies a
    journal, none that suppresses one, and no branch that reaches a mutation
    without one: the single `apply_one` call site and the single `undo_one` call
    site both live in a function that is handed the journal, and each is
    preceded by the write-ahead record that authorizes it. Structural
    assertions over this module's own source keep that true as it grows
    (`test_external_write_trial_executor.AntiZeroCallerTests`).

------------------------------------------------------------------------------
The credential split — why a kernel-side trial is legitimate
------------------------------------------------------------------------------
`apply_one` and `undo_one` receive the WRITE-CAPABLE client. `verify_one`
receives a `read_facade.ReadFacade` built over a READ-ONLY-scoped client, and
never the write client — that is what `adapter_registry`'s Adapter protocol
documents `verify_one` to be (a READ-ONLY OBSERVER), and collapsing the two
would make this module a boundary violation rather than a sanctioned kernel
driver.

Both clients are resolved through `adapter_registry.resolve_write_client` /
`resolve_read_only_client` — the SAME two functions the ordinary write path
(`adapters._run_adapter_operation` / `adapters._verify_applied_units`) resolves
through. That is deliberate and load-bearing: a trial exists to earn confidence
about the operator's real write path, so it must obtain its credentials by
exactly the rule production obtains them by. A second copy of that precedence
rule here would be a trial of a credential path no real run takes.

------------------------------------------------------------------------------
Honest failure: what happens when a unit does not come back
------------------------------------------------------------------------------
A trial ALWAYS reverts. Every unit this module applies is reversed in the same
call, before the next unit is touched, so at most one unit is mutated at any
instant.

  * `apply_one` raises, or the observed evidence does not show the apply landed:
    the unit is STILL reversed. An absolute-state restore — which the
    trial-eligibility preflight requires the adapter to declare — converges to
    the recorded prior state whether or not the apply landed, so reversing is
    safe and is the only honest response to an ambiguous apply. The journal then
    truthfully records `restored_verified`, and NO proof is emitted, because
    nothing observed the apply land.
  * `undo_one` raises, the surface cannot be observed afterwards, or
    `verify_undo_restored` is False over what was observed: the unit is recorded
    `recovery_required` with a stated cause, and no proof is emitted. That state
    is terminal in the journal and outlives this process.
  * In every failing case the run STOPS: units after the failure stay at
    `planned` and are never applied. Once a proof can no longer be earned,
    further live mutations are pure cost to the operator.

`recovery_required` is never written for a unit that was in fact restored, and
`restored_verified` is never written for a unit whose restoration was not
established from observed evidence. The journal is truthful in both directions
independently of whether the trial succeeded.

------------------------------------------------------------------------------
What this module does NOT do
------------------------------------------------------------------------------
  * It does not RESUME a crashed trial, and it does not try to determine whether
    a crashed apply landed. That is a separate concern with its own module;
    there is deliberately no stub, hook or placeholder for it here.
  * It does not re-implement authorization, eligibility, the blast-radius cap,
    the invocation ledger, receipt validation, the journal's state machine, or
    the proof validator. It CALLS each of them. In particular it validates the
    proof it just built with the shipped `copy_run_proof.validate_copy_run_proof`
    and refuses to write anything that validator rejects — so "the producer
    emits a proof the validator accepts" is structural here, not merely tested.
  * It never mints a receipt. A receipt is the operator's approval of a specific
    operation; a trial performs a real write to a bounded subset of the live
    resource, so it consumes an approval its caller already holds. A driver that
    minted its own would be forging the consent the whole gate rests on.
  * The enforcement ceiling is UNCHANGED: build-time plus operator-as-approver.
    This is not a runtime sandbox and not an OS-level control.

------------------------------------------------------------------------------
DISCLOSED BOUNDS — read these before trusting the artifact further than it goes
------------------------------------------------------------------------------
  1. The `copy_run_proof-v1` schema carries ONE apply-evidence block and ONE
     undo-evidence block, so a multi-unit trial's proof carries the observed
     evidence of ONE unit — the first in plan order, stated here so nothing has
     to guess which. That is not a claim about only one unit: emission is gated
     on EVERY unit reaching `restored_verified` (checked against the journal on
     disk, not against in-memory bookkeeping) and on every unit's apply having
     been observed to land. The full per-unit record is the trial journal, and
     the proof's `prestate_snapshot_ref` points at it. This module does not
     extend the v1 schema to carry more: a new key under an existing schema tag
     is indistinguishable to a reader from a misspelling, which is exactly why
     the recovery-capsule validator refuses unknown keys outright.
  2. `copy_source_ref` does not name a copy, because there is no copy. A trial
     runs against the LIVE bounded target (`native_undo`); the `copy` target is
     refused at authorization precisely because a copy surface is not the
     operator's live record. The field therefore carries an explicitly-labelled
     live-bounded trial reference (`LIVE_BOUNDED_TRIAL_REF_PREFIX`) rather than
     a path that would read as a copy that was never made.
  3. A recovery capsule is built by passing the adapter's own `target_ref` /
     `undo_ref` through unchanged. Those are contractually opaque, so this
     module cannot render them — only the adapter knows what a faithful
     rendering of its own reference is, and a kernel-side guess would be this
     module designing the adapter's data for it. Pass-through is correct exactly
     when the references already ARE JSON-representable, and the fail-closed net
     is real rather than hoped-for: the preflight's capsule clause performs a
     genuine `json.dumps` round trip and the journal re-serializes with the same
     strictness before the first mutation. An adapter whose references do not
     survive that is refused a trial, and the exit is available to it — the
     references are adapter-defined, so it can carry JSON-representable values
     in them.
  4. An op_kind whose contract declares `introduces_persistent_binding` is
     REFUSED a trial up front. Its proof would require `durability_checks`:
     tested ordinary operator actions (sort / filter / insert / delete / move)
     performed against the new structure, with the binding proven to survive.
     This protocol does not perform them, and a machine may never write an
     affirmative safety declaration it did not earn — a fabricated
     `binding_survived: true` would be forged consent. So the refusal names the
     durability requirement instead of emitting a proof that could not be
     honest. Such a capability's proof must come from the supervised copy-run
     route the durability clause was written for; refusing before any mutation
     also means no live write is issued for a proof that could never be emitted.

Zone: SEALED_KERNEL (enumerated in `zones.py`). SEALED_KERNEL membership is not
an invitation: capability code may not import this module (the independent
`scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES` set governs that). The
trial protocol is kernel-driven, and capability code has no business driving the
external writes it proposes.

Stdlib only — no third-party dependencies.
"""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Imported as a MODULE, not by name, for `open_trial_journal` and the state
# constants: the journal is the mechanism this executor must be seen to go
# through, and a module-qualified call keeps that visible at the call site (and
# keeps a test able to substitute the journal's own entrypoint rather than a
# local alias of it).
from external_write import trial_journal
from external_write.adapter_registry import (
    get_dispatch, resolve_read_only_client, resolve_write_client,
)
from external_write.contracts import (
    OperationContract, SourceLineage, get_contract, get_verifier,
)
from external_write.copy_run_proof import (
    COPY_RUN_PROOF_SCHEMA, copy_run_proof_path, validate_copy_run_proof,
)
from external_write.evidence import (
    LIVE_READ_ONLY_FACADE_OBSERVATION, AdapterEvidence,
)
from external_write.operations import EffectUnit, Operation
from external_write.proof_hash import (
    compute_contract_hash, compute_implementation_hash,
)
from external_write.read_facade import (
    ReadFacadeEligibilityError, build_read_facade,
)
from external_write.trial_journal import (
    STATE_APPLY_CONFIRMED, STATE_RESTORED_VERIFIED, build_recovery_capsule,
    serialize_journal_payload,
)
from external_write.verification_modes import (
    ClaimStrength, VerificationMode, max_claim_for,
)
from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA
from external_write.write_authorization import (
    EXECUTION_INTENT_TRIAL, TRIAL_TARGET, authorize_operation,
)


# ---------------------------------------------------------------------------
# Vocabulary this module owns
# ---------------------------------------------------------------------------

# The prefix of the proof's `copy_source_ref` for a trial. See DISCLOSED BOUND 2:
# a trial runs against the operator's LIVE record under a bounded target, so this
# field must not carry anything that reads as a path to a copy that was never
# made. Rendered as `<prefix>:<resolved target>:<trial id>`, which names what the
# trial actually ran against and which durable record describes it.
LIVE_BOUNDED_TRIAL_REF_PREFIX = "live_bounded_trial"

# The lineage token naming where the prestate that `verify_undo_restored` is
# judged against came from: the adapter's recorded prior state, carried in the
# per-unit recovery capsule and made durable in the trial journal BEFORE the
# first mutation. It is a real pre-write source, so declaring the record's
# `pre_write_sources` empty would understate what the observation was compared
# with.
TRIAL_CAPSULE_PRESTATE_SOURCE = "trial_journal_recovery_capsule"

# The two evidence-predicate names this module evaluates, spelled here so the
# postwrite-verification record can NAME the invariant it checked rather than
# describe it vaguely. Pinned equal to members of the canonical
# `evidence.REQUIRED_EVIDENCE_PREDICATES` by
# `test_external_write_trial_executor.EnrolmentTests.
# test_the_invariant_names_are_the_canonical_predicate_names`, so a rename of
# that canonical tuple fails loudly here rather than leaving this module
# describing an invariant under a name nothing else uses.
APPLY_PREDICATE_NAME = "verify_apply_landed"
UNDO_PREDICATE_NAME = "verify_undo_restored"

# Where a reader finds the evidence each half's verification record rests on.
# Deliberately an IN-ARTIFACT pointer rather than a filesystem path: the kernel
# validator builds the evidence it re-evaluates from the proof's OWN captured
# content and never opens this reference, so a path here would be a string
# nothing resolves — which is precisely the dangling `evidence_ref` that let an
# unverifiable "verified" claim pass before the validator started loading
# evidence itself.
APPLY_EVIDENCE_REF = "copy_apply_proof.apply_evidence"
UNDO_EVIDENCE_REF = "copy_undo_proof.undo_evidence"


class TrialExecutorError(Exception):
    """A fail-closed refusal to START a trial, raised before anything external
    has been touched.

    Deliberately an EXCEPTION rather than a returned refusal, matching
    `trial_journal.TrialJournalError` and `write_authorization.
    AuthorizationRequiredError`: a returned refusal is the answer to a
    legitimate question ("may this write proceed?"), and the gate's own answer to
    that question IS returned (see `TrialOutcome.refusal`). Every condition
    raised here is different in kind — the trial cannot be set up at all — and
    failing loudly before a mutation is strictly safer than a soft "no" a caller
    might treat as advisory.
    """


@dataclass(frozen=True)
class TrialUnitOutcome:
    """What the trial established about ONE unit.

    `apply_landed` / `undo_restored` are three-valued on purpose: True and False
    are observed verdicts, and None means the question could not be answered
    (the mutation raised, or the surface could not be read). None is never
    treated as either verdict anywhere below.
    """

    unit_id: str
    journal_state: str
    apply_landed: Optional[bool] = None
    undo_restored: Optional[bool] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class TrialOutcome:
    """The typed result of a trial. `ok` is True only when a proof was written.

    Typed rather than prose so a caller (and an operator-facing narration built
    over it) reports what actually happened instead of re-deriving it from a
    sentence. `refusal` carries the gate's own plain-language reason when the
    trial was refused, or this module's reason when a proof could not be earned.
    """

    ok: bool
    refusal: Optional[str] = None
    trial_id: Optional[str] = None
    journal_path: Optional[str] = None
    proof_path: Optional[str] = None
    units: Tuple[TrialUnitOutcome, ...] = ()
    recovery_required_unit_ids: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Input validation — every property is an explicit POSITIVE declaration
# ---------------------------------------------------------------------------

def _validated_capability_id(capability_id: Any) -> str:
    """The proof is bound to ONE capability: the acceptance ceremony asserts the
    proof's `capability_id` equals the descriptor being accepted, so a valid
    proof for a different same-op-kind capability can never cross-authorize. It
    is also the artifact's filename stem. Neither can be defaulted or guessed."""
    if not (isinstance(capability_id, str) and capability_id.strip()):
        raise TrialExecutorError(
            "a trial is run FOR one named capability and its proof is bound to "
            f"that capability's id; got {capability_id!r}. Without it the proof "
            "could not be tied to the capability it proves, and a proof that is "
            "not tied to one capability could authorize another.")
    return capability_id.strip()


def _validated_module_paths(paths: Any) -> Tuple[str, ...]:
    """The capability's OWN write-affecting module files, which the acceptance
    ceremony scans with the deterministic bypass scanner to establish that this
    capability's write path is actually gated.

    REQUIRED here, with no default, even though the structural proof validator
    treats the field as optional (older copy-run flows that never reached
    acceptance did not need it). A proof emitted without it is refused at the
    trust surface, so a producer that let it be omitted would emit artifacts
    that can never be accepted — and silence is never a declaration.

    Only the SHAPE is checked. Whether each file exists and scans clean is the
    ceremony's question, and it has exactly one implementation there; a second
    copy of that check here would be one more thing that has to agree.
    """
    if isinstance(paths, str) or not isinstance(paths, (list, tuple)):
        raise TrialExecutorError(
            "the capability's own write-affecting module files must be supplied "
            "as a list of paths (the acceptance step scans them to establish "
            f"that this capability's write path is gated); got {type(paths).__name__}.")
    cleaned = tuple(paths)
    if not cleaned or not all(isinstance(p, str) and p.strip() for p in cleaned):
        raise TrialExecutorError(
            "the capability's own write-affecting module files must be a "
            "non-empty list of non-empty paths -- the acceptance step refuses a "
            "proof that does not name the files it must scan, so a trial that "
            f"could not produce an acceptable proof does not start. Got {paths!r}.")
    return cleaned


def _resolved_contract(op_kind: str) -> OperationContract:
    contract = get_contract(op_kind)
    if contract is None:
        raise TrialExecutorError(
            f"operation kind {op_kind!r} has no registered contract, so neither "
            "the proof's trust hashes nor its verification records can be built. "
            "Fix step: enroll this capability's adapter module so it registers "
            "its contract at import time, then run the trial again.")
    if not contract.writes:
        raise TrialExecutorError(
            f"operation kind {op_kind!r} declares no write field, so there is "
            "nothing for a trial to apply and reverse.")
    if contract.introduces_persistent_binding:
        # See DISCLOSED BOUND 4. Refused BEFORE authorization, so no live write
        # is issued and no blast-radius slot is consumed for a proof that could
        # never be emitted honestly.
        raise TrialExecutorError(
            f"operation kind {op_kind!r} introduces a persistent binding, so its "
            "proof must additionally carry durability checks: ordinary operator "
            "actions (sort / filter / insert / delete / move) performed against "
            "the new structure, with the binding proven to survive each one. A "
            "journaled apply/undo trial does not perform those actions, and this "
            "executor will not write an affirmative durability result it did not "
            "earn. Fix step: this capability's proof must come from the "
            "supervised copy-run that the durability requirement was written "
            "for. Nothing was written and nothing was applied.")
    return contract


def _selected_verifier(op_kind: str, contract: OperationContract) -> Any:
    """The registered verifier whose declared mode permits a machine-VERIFIED
    claim, chosen from the op_kind's OWN declared `verifier_set`.

    Selection is on the DECLARED property (the mode's claim ceiling), never on
    position alone: an operator-attested verifier can never reach `verified`, so
    a trial's proof cannot rest on one. Declared order breaks a tie between two
    equally-eligible verifiers — that order is the contract author's own.
    """
    for verifier_id in contract.verifier_set:
        verifier = get_verifier(verifier_id)
        if verifier is None:
            continue
        try:
            ceiling = max_claim_for(VerificationMode(verifier.mode))
        except (ValueError, KeyError):
            continue
        if ceiling == ClaimStrength.VERIFIED:
            return verifier
    raise TrialExecutorError(
        f"operation kind {op_kind!r} declares no registered verifier whose mode "
        "permits a machine-verified claim (declared verifiers: "
        f"{list(contract.verifier_set)}), so a trial could not record an "
        "independently verified apply or restore. An operator attestation is "
        "never machine-verified evidence. Fix step: declare a verifier with an "
        "independent verification mode on this operation's contract.")


def _lineage_for(verifier: Any) -> SourceLineage:
    """The ONE lineage declaration a trial's observations rest on, used for BOTH
    the evidence this module evaluates itself AND the `source_lineage` written
    into the proof's verification records.

    One function, because the shipped validator rebuilds the evidence it
    re-evaluates FROM the record in the proof: if the lineage this module
    declared differed from the lineage the validator re-derives, a
    lineage-sensitive predicate could reach one verdict at run time and another
    at proof time, and the run-time one would be the unchecked one.

      pre_write_sources  — the recorded prior state, carried in the per-unit
                           recovery capsule and durable in the journal before
                           the first mutation. Declaring this empty would
                           understate what the restoration check compared
                           against.
      post_write_sources — the observation, read through a READ-ONLY facade.
      forbidden          — the op_kind's OWN registered verifier's forbidden
                           inputs, read from the registry rather than re-listed.
                           The Authority clause requires the record to
                           acknowledge the full authoritative forbidden set, and
                           re-spelling it here would be a second copy that can
                           drift from the registry. Neither declared source is a
                           member of it: an observation through a read-only
                           facade is precisely the independent source the
                           lineage lock exists to require.
    """
    return SourceLineage(
        pre_write_sources=(TRIAL_CAPSULE_PRESTATE_SOURCE,),
        post_write_sources=(LIVE_READ_ONLY_FACADE_OBSERVATION,),
        forbidden_verification_inputs=tuple(sorted(
            verifier.source_lineage.forbidden_verification_inputs)),
    )


def trial_source_lineage(op_kind: str) -> SourceLineage:
    """`_lineage_for`, resolved from `op_kind` alone — for a caller (a test above
    all) that needs the declaration this module will make without running a
    trial. `run_trial` uses the verifier it has already resolved rather than
    calling this, so a trial resolves the contract and the verifier exactly
    once."""
    return _lineage_for(_selected_verifier(op_kind, _resolved_contract(op_kind)))


# ---------------------------------------------------------------------------
# Planning + capsules
# ---------------------------------------------------------------------------

def _planned_units(dispatch: Any, op: Operation) -> List[EffectUnit]:
    """`plan()` is contractually PURE — no reads, no writes — so calling it here
    touches no surface. It is called so the per-unit recovery capsules exist
    BEFORE authorization, because the trial-eligibility preflight cannot judge a
    capsule it was not handed.

    `authorize_operation` plans again and binds its plan to the units the
    preflight blessed, never to these; the journal then refuses to open unless
    the capsule set matches the authorized units exactly. So a `plan()` that is
    not in fact pure or deterministic fails closed at the journal open, before
    any mutation, rather than silently filing a capsule against the wrong unit.
    """
    try:
        planned = dispatch.plan(dispatch.instance, op.params)
        if not isinstance(planned, list):
            raise TypeError(
                "plan() must return a list of EffectUnit; got "
                f"{type(planned).__name__!r}")
    except Exception as exc:
        raise TrialExecutorError(
            f"the effect units for {op.op_kind!r} could not be planned from the "
            f"operation's parameters ({exc!r}), so there is nothing a trial "
            "could apply, reverse, or write a recovery capsule for. Nothing was "
            "applied.") from exc
    return planned


def _recovery_capsules(op_kind: str,
                       units: Sequence[Any]) -> Dict[str, Any]:
    """One recovery capsule per planned unit, built through the journal's own
    sanctioned constructor so the capsule's field names are spelled once.

    The adapter's `target_ref` / `undo_ref` are passed through UNCHANGED — see
    DISCLOSED BOUND 3 for why a kernel-side rendering would be this module
    guessing at adapter-defined data, and what the fail-closed net is.
    """
    capsules: Dict[str, Any] = {}
    for unit in units:
        capsules[getattr(unit, "unit_id", None)] = build_recovery_capsule(
            op_kind, unit,
            target_ref_json=getattr(unit, "target_ref", None),
            undo_ref_json=getattr(unit, "undo_ref", None),
        )
    return capsules


# ---------------------------------------------------------------------------
# Observation — always through the read-only facade
# ---------------------------------------------------------------------------

def _observe(dispatch: Any, facade: Any, unit: Any,
             op_kind: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Observe `unit`'s CURRENT state on the real surface through `facade` — the
    READ-ONLY facade, never the write-capable client — and return
    `(poststate, None)` or `(None, reason)`.

    Returns rather than raises so the caller can reverse the unit and record an
    honest outcome; a raised exception here would abandon a mutated unit.
    """
    try:
        poststate = dispatch.verify_one(dispatch.instance, facade, unit)
    except Exception as exc:
        return None, (
            f"the surface could not be observed for unit {unit.unit_id!r} of "
            f"{op_kind!r}: verify_one raised {exc!r}")
    if not isinstance(poststate, dict):
        return None, (
            f"the observation of unit {unit.unit_id!r} of {op_kind!r} did not "
            "return a readable poststate, so there is no evidence to judge")
    return poststate, None


def _evidence(op_kind: str, unit_id: str, poststate: Dict[str, Any],
              lineage: SourceLineage) -> AdapterEvidence:
    """Kernel-constructed, lineage-typed evidence over what was ACTUALLY
    observed. The predicate that evaluates it takes no path or ref argument, so
    it is structurally incapable of reaching outside this."""
    return AdapterEvidence(
        op_kind=op_kind,
        unit_id=unit_id,
        poststate=poststate,
        prestate=None,
        source_lineage=lineage,
    )


def _evaluate(dispatch: Any, predicate_name: str,
              evidence: AdapterEvidence) -> Tuple[Optional[bool], Optional[str]]:
    """Ask the adapter's own captured evidence predicate. A predicate that RAISES
    yields None (unanswered), never False: 'the question could not be asked' and
    'the answer is no' are different facts, and only the first one is a defect in
    the adapter rather than in the round trip."""
    predicate = getattr(dispatch, predicate_name, None)
    if predicate is None:
        return None, (
            f"the adapter for {evidence.op_kind!r} declares no {predicate_name} "
            "evidence predicate, so nothing can be earned from the observation")
    try:
        return bool(predicate(dispatch.instance, evidence)), None
    except Exception as exc:
        return None, (
            f"{predicate_name} raised evaluating the observed evidence for unit "
            f"{evidence.unit_id!r} of {evidence.op_kind!r} ({exc!r}) -- a "
            "predicate that cannot run cannot certify anything")


# ---------------------------------------------------------------------------
# The per-unit drive — the ONE place this module mutates anything
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _UnitRun:
    outcome: TrialUnitOutcome
    apply_poststate: Optional[Dict[str, Any]] = None
    undo_poststate: Optional[Dict[str, Any]] = None

    @property
    def proved(self) -> bool:
        """A unit contributes to a proof only when BOTH halves were observed:
        the apply landed and the prior state was observed restored."""
        return (self.outcome.apply_landed is True
                and self.outcome.undo_restored is True)


def _drive_unit(journal: Any, dispatch: Any, op: Operation, write_client: Any,
                facade: Any, unit: Any, lineage: SourceLineage) -> _UnitRun:
    """Apply, observe, reverse, observe — for exactly one unit.

    `journal` is not optional and not defaulted: every state this function
    records is persisted and fsynced BEFORE the action it authorizes, and the
    journal's own transition table makes an outcome state reachable only from the
    write-ahead state that authorizes it. So a caller that skipped an intent
    record could not record the outcome at all.

    This is the ONLY function in this module that calls `apply_one` or
    `undo_one`, and it always reverses what it applied — including when the apply
    raised or was not observed to land (see the module docstring's honest-failure
    section).
    """
    op_kind = op.op_kind
    unit_id = unit.unit_id
    reasons: List[str] = []

    # -- apply -------------------------------------------------------------
    # The intent record is durable and fsynced when this returns, so a crash at
    # any instant after it leaves a durable record naming this unit as one whose
    # mutation may have landed -- the most that can honestly be said, and the
    # least that lets the unit be reversed.
    journal.record_apply_intent(unit_id)
    apply_failed = False
    try:
        dispatch.apply_one(dispatch.instance, write_client, unit)
    except Exception as exc:
        apply_failed = True
        reasons.append(
            f"apply_one raised for unit {unit_id!r} of {op_kind!r} ({exc!r}), so "
            "whether the mutation landed is unknown; the unit is reversed anyway")
    else:
        journal.record_apply_confirmed(unit_id)

    apply_landed: Optional[bool] = None
    apply_poststate: Optional[Dict[str, Any]] = None
    if not apply_failed:
        apply_poststate, reason = _observe(dispatch, facade, unit, op_kind)
        if reason is not None:
            reasons.append(reason)
        else:
            apply_landed, reason = _evaluate(
                dispatch, APPLY_PREDICATE_NAME,
                _evidence(op_kind, unit_id, apply_poststate, lineage))
            if reason is not None:
                reasons.append(reason)
            elif apply_landed is False:
                reasons.append(
                    f"the observed evidence does not show the apply for unit "
                    f"{unit_id!r} of {op_kind!r} landed, so a 'verified' apply "
                    "cannot be claimed for it")

    # -- reverse -----------------------------------------------------------
    # ALWAYS, whatever happened above. An absolute-state restore converges to the
    # recorded prior state whether or not the apply landed, which is exactly why
    # the preflight requires the adapter to declare one.
    journal.record_undo_intent(unit_id)
    try:
        dispatch.undo_one(dispatch.instance, write_client, unit)
    except Exception as exc:
        reason = (
            f"undo_one raised for unit {unit_id!r} of {op_kind!r} ({exc!r}), so "
            "the unit may still be changed on the real surface and needs "
            "attention")
        reasons.append(reason)
        journal.record_recovery_required(unit_id, reason=reason)
        return _UnitRun(
            outcome=TrialUnitOutcome(
                unit_id=unit_id, journal_state=journal.unit_state(unit_id),
                apply_landed=apply_landed, undo_restored=None,
                reason=" | ".join(reasons)),
            apply_poststate=apply_poststate)

    undo_poststate, reason = _observe(dispatch, facade, unit, op_kind)
    if reason is not None:
        reasons.append(reason)
        journal.record_recovery_required(unit_id, reason=reason)
        return _UnitRun(
            outcome=TrialUnitOutcome(
                unit_id=unit_id, journal_state=journal.unit_state(unit_id),
                apply_landed=apply_landed, undo_restored=None,
                reason=" | ".join(reasons)),
            apply_poststate=apply_poststate)

    undo_restored, reason = _evaluate(
        dispatch, UNDO_PREDICATE_NAME,
        _evidence(op_kind, unit_id, undo_poststate, lineage))
    if undo_restored is not True:
        reason = reason or (
            f"the observed evidence does not show unit {unit_id!r} of "
            f"{op_kind!r} back at its prior state after the reversal "
            f"({UNDO_PREDICATE_NAME} returned {undo_restored!r}), so it needs "
            "attention")
        reasons.append(reason)
        journal.record_recovery_required(unit_id, reason=reason)
        return _UnitRun(
            outcome=TrialUnitOutcome(
                unit_id=unit_id, journal_state=journal.unit_state(unit_id),
                apply_landed=apply_landed, undo_restored=undo_restored,
                reason=" | ".join(reasons)),
            apply_poststate=apply_poststate, undo_poststate=undo_poststate)

    # Restoration was established from observed evidence -- the one condition
    # under which this state may be recorded.
    journal.record_restored_verified(unit_id)
    return _UnitRun(
        outcome=TrialUnitOutcome(
            unit_id=unit_id, journal_state=journal.unit_state(unit_id),
            apply_landed=apply_landed, undo_restored=True,
            reason=" | ".join(reasons) if reasons else None),
        apply_poststate=apply_poststate, undo_poststate=undo_poststate)


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------

def _verification_record(verifier: Any, lineage: SourceLineage,
                         *, invariant: str, evidence_ref: str) -> Dict[str, Any]:
    """One `postwrite-verification-v1` record, built from the op_kind's OWN
    registered verifier and the single trial lineage declaration."""
    return {
        "schema": POSTWRITE_VERIFICATION_SCHEMA,
        "verification_mode": VerificationMode(verifier.mode).value,
        "claim_strength": ClaimStrength.VERIFIED.value,
        "verifier_id": verifier.verifier_id,
        "source_lineage": {
            "pre_write_sources": list(lineage.pre_write_sources),
            "post_write_sources": list(lineage.post_write_sources),
            # Named `forbidden_sources` in the record shape and
            # `forbidden_verification_inputs` on the lineage type -- the same
            # vocabulary under two names, because the record shape predates the
            # lineage type. The validator requires the record to acknowledge the
            # registry's full forbidden set.
            "forbidden_sources": list(lineage.forbidden_verification_inputs),
        },
        "invariant_checked": invariant,
        "evidence_ref": evidence_ref,
    }


def _build_proof(op: Operation, contract: OperationContract, verifier: Any,
                 lineage: SourceLineage, *, capability_id: str,
                 module_paths: Tuple[str, ...], journal: Any,
                 resolved_target: Optional[str], sampled: _UnitRun,
                 lib_dir: Optional[str]) -> Dict[str, Any]:
    """Assemble the `copy_run_proof-v1` artifact. Every field is either read off
    something real or computed over real material; nothing is asserted.

    The two hashes are COMPUTED here over the actual dependency bytes and the
    canonical contract, by the same functions the acceptance ceremony recomputes
    with — the ceremony refuses on a mismatch, so a declared-rather-than-computed
    hash would simply fail there.
    """
    unit_id = sampled.outcome.unit_id
    return {
        "schema": COPY_RUN_PROOF_SCHEMA,
        "operation_id": op.digest(),
        "op_kind": op.op_kind,
        # A structural identifier of the class of data touched, derived from the
        # operation's own surface and its contract's declared write fields --
        # never an operator-authored label this module would be inventing.
        "data_class": "{0}:{1}".format(op.surface, "+".join(contract.writes)),
        # NOT a copy path: see DISCLOSED BOUND 2.
        "copy_source_ref": "{0}:{1}:{2}".format(
            LIVE_BOUNDED_TRIAL_REF_PREFIX, resolved_target, journal.trial_id),
        # The per-unit prior state IS the journal: every unit's recovery capsule
        # was durable there before the first mutation.
        "prestate_snapshot_ref": journal.path,
        "copy_apply_proof": {
            "apply_receipt_ref": "{0}#{1}:{2}".format(
                journal.path, unit_id, STATE_APPLY_CONFIRMED),
            "apply_verification": _verification_record(
                verifier, lineage,
                invariant=("the observed read-only-facade poststate satisfies "
                           f"the adapter's {APPLY_PREDICATE_NAME} predicate"),
                evidence_ref=APPLY_EVIDENCE_REF),
            "apply_evidence": {"unit_id": unit_id,
                               "poststate": sampled.apply_poststate},
        },
        "copy_undo_proof": {
            "undo_receipt_ref": "{0}#{1}:{2}".format(
                journal.path, unit_id, STATE_RESTORED_VERIFIED),
            "undo_verification": _verification_record(
                verifier, lineage,
                invariant=("the observed read-only-facade poststate satisfies "
                           f"the adapter's {UNDO_PREDICATE_NAME} predicate"),
                evidence_ref=UNDO_EVIDENCE_REF),
            "undo_evidence": {"unit_id": unit_id,
                              "poststate": sampled.undo_poststate},
        },
        # Empty, and REQUIRED to be empty for a non-binding op_kind. A binding
        # one never reaches here (DISCLOSED BOUND 4).
        "durability_checks": [],
        "accepted_for_live_use": True,
        "implementation_hash": compute_implementation_hash(
            op.op_kind,
            lib_dir=Path(lib_dir) if lib_dir is not None else None),
        "contract_hash": compute_contract_hash(op.op_kind),
        "capability_id": capability_id,
        "capability_module_paths": list(module_paths),
    }


def _units_not_restored_on_disk(journal: Any,
                                planned_ids: Sequence[str]) -> List[str]:
    """Every unit the JOURNAL ON DISK does not record at `restored_verified`.

    The authoritative record of what happened to each unit is the file, not the
    loop that drove it: a producer that certified its own bookkeeping would be
    certifying its intentions. So the proof gate reads the end STATE here rather
    than counting the outcomes it thinks it produced.

    Quantified over the UNION of `planned_ids` and the ids the journal covers, so
    both directions of disagreement are reported rather than silently skipped: a
    planned unit missing from the journal (nothing establishes it came back) and
    a unit in the journal that the plan does not contain (the journal is not this
    plan's journal). Absent is never read as restored.

    DISCLOSED: at `run_trial`'s call site this check is REDUNDANT with the
    observed-round-trip check that follows it — every failure this module can
    itself produce leaves a unit unproved as well as unrestored, so no input can
    make this the sole reason a proof is refused. It is kept, and its logic is
    tested directly rather than only through a run, because the journal is the
    authoritative record and a later change to the drive loop must not be able to
    make the artifact emittable without the journal agreeing. The redundancy is
    stated rather than left for a reader to discover and mistake for a load-
    bearing guard.
    """
    states = journal.unit_states()
    return sorted(unit_id for unit_id in set(planned_ids) | set(states)
                  if states.get(unit_id) != trial_journal.STATE_RESTORED_VERIFIED)


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    """Write `payload` to `path` durably: temp file in the same directory, write,
    flush, fsync the contents, atomic `os.replace`, then fsync the directory.

    The same temp-file + fsync + replace pattern this package carries privately
    in `trial_journal`, `lifecycle_state`, `_ext_write_state` and `run_envelope`,
    with the directory fsync the journal added for the same reason: `os.fsync` on
    the file makes the BYTES durable, while the rename that publishes them is a
    directory-entry change that needs its own fsync.

    A torn proof would already fail the validator the ceremony runs, so this is
    not what makes the artifact trustworthy — it is what stops a half-written one
    from sitting at the acceptance path looking authoritative.

    Serialized by `trial_journal.serialize_journal_payload`: this package's
    canonical strict serialization (key-sorted, ASCII-escaped, `allow_nan=False`)
    rather than a second serializer with the same arguments. The strictness is
    load-bearing here too — the proof carries adapter-defined observed poststates,
    and a non-finite float in one would otherwise be written as invalid JSON that
    a strict reader rejects.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    text = serialize_journal_payload(payload)
    fd, tmp = tempfile.mkstemp(prefix=".copy_run_proof.", suffix=".tmp",
                               dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------

def run_trial(op: Operation, receipt: Any, *,
              capability_id: str,
              capability_module_paths: Any,
              client: Any = None,
              read_only_client: Any = None,
              descriptor_set: Any = None,
              cap_ledger: Any = None,
              clock: Any = None,
              paused_root: Optional[str] = None,
              journal_dir: Optional[str] = None,
              proof_dir: Optional[str] = None,
              lib_dir: Optional[str] = None,
              trial_id: Optional[str] = None) -> TrialOutcome:
    """Run a journaled trial of `op` and, if every unit comes back verified,
    write `capability_id`'s copy-run proof.

    Parameters
    ----------
    op / receipt / client / read_only_client / descriptor_set / cap_ledger /
    clock / paused_root:
        exactly as `adapters.run_operation` documents them — the same operation,
        the same operator-approved receipt, the same optional client fallbacks
        for an adapter that does not provision its own, and the same gate
        arguments. A trial is a real live write to a bounded subset, so it needs
        a real approval; this function never mints one.
    capability_id:
        the capability this trial proves. Bound into the proof (the acceptance
        ceremony asserts it equals the descriptor being accepted) and used as the
        artifact's filename stem.
    capability_module_paths:
        the capability's own write-affecting module files. Required — see
        `_validated_module_paths`.
    journal_dir / proof_dir / lib_dir / trial_id:
        overrides for callers (tests above all) that must not depend on ambient
        project state. Every default is the production convention.

    The TARGET is not a parameter. A trial runs against `TRIAL_TARGET` and
    nothing else: the target is chosen by this kernel-driven protocol, not by a
    caller or an operator, and every other value is refused at authorization
    anyway (a dry run performs no write, a copy surface is not the operator's
    live record, an affirmative live target requires the acceptance the trial
    exists to earn, and the other live-bounded target declares a sample that
    persists).

    Returns
    -------
    A `TrialOutcome`. `ok` is True only when a proof was written and the SHIPPED
    validator accepted it.

    Raises
    ------
    `TrialExecutorError` when the trial cannot be set up at all — nothing has
    been applied and nothing written. `trial_journal.TrialJournalError`
    propagates unchanged when the write-ahead record cannot be created: it
    already names the problem exactly, and re-wrapping it would hide which
    mechanism refused. A REFUSAL from the gate, the preflight or receipt
    validation is returned as `TrialOutcome(ok=False, refusal=...)`, because that
    is the legitimate answer to "may this write proceed?" and must not be
    mistakable for a mechanism that failed to run.
    """
    capability_id = _validated_capability_id(capability_id)
    module_paths = _validated_module_paths(capability_module_paths)
    contract = _resolved_contract(op.op_kind)
    verifier = _selected_verifier(op.op_kind, contract)
    lineage = _lineage_for(verifier)

    dispatch = get_dispatch(op.op_kind)
    if dispatch is None:
        raise TrialExecutorError(
            f"operation kind {op.op_kind!r} has no registered adapter, so there "
            "is no undo_one to reverse a trial with and no evidence predicate to "
            "ask whether it came back. Fix step: enroll this capability's adapter "
            "module so it registers at import time, then run the trial again.")

    units = _planned_units(dispatch, op)
    capsules = _recovery_capsules(op.op_kind, units)

    # The READ side is resolved BEFORE authorization on purpose: a trial that
    # cannot observe the real surface can never earn a proof, and the preflight
    # ordering this package already established says such an operation must not
    # consume a blast-radius slot. Fail-CLOSED here, unlike the ordinary write
    # path -- there, degrading to the honest `applied_not_verified` is right
    # because the write already happened; here nothing has happened yet and an
    # unobservable trial is simply not a trial.
    try:
        effective_read_only_client = resolve_read_only_client(
            dispatch, op, fallback=read_only_client)
    except Exception as exc:
        raise TrialExecutorError(
            f"a read-only connection for {op.op_kind!r} could not be obtained "
            f"({exc!r}), so the trial could not check the real surface and would "
            "have had nothing to prove restoration with. Nothing was applied.") from exc
    if effective_read_only_client is None:
        raise TrialExecutorError(
            f"no read-only connection is available for {op.op_kind!r} -- the "
            "adapter does not provide one and none was supplied -- so the trial "
            "could not observe whether the change landed or whether it came "
            "back. A trial that cannot look at the real surface cannot produce "
            "the evidence acceptance requires. Nothing was applied.")
    try:
        facade = build_read_facade(op.op_kind, effective_read_only_client)
    except ReadFacadeEligibilityError as exc:
        raise TrialExecutorError(
            f"operation kind {op.op_kind!r} cannot be observed through a "
            f"read-only facade: {exc}. The trial's observations must go through "
            "one, so that checking the surface can never reach for the "
            "write-capable connection. Nothing was applied.") from exc

    # The single authorization implementation, on its TRIAL branch: the
    # eligibility preflight, then the SAME live-bounded funnel an accepted live
    # write runs (recovery floor, mandatory blast-radius cap, invocation ledger,
    # irreversibility audit), then receipt validation. Nothing here relaxes any
    # of it and there is no trial-mode flag that could.
    authorization = authorize_operation(
        op, receipt, intent=EXECUTION_INTENT_TRIAL, target=TRIAL_TARGET,
        descriptor_set=descriptor_set, cap_ledger=cap_ledger, clock=clock,
        recovery_capsules=capsules, paused_root=paused_root)
    if not authorization.authorized:
        detail = (authorization.refusal.detail
                  if authorization.refusal is not None else None)
        reason = (detail.get("reason") if isinstance(detail, dict)
                  else None) or "the trial was refused"
        clauses = (detail.get("trial_ineligible_clauses")
                   if isinstance(detail, dict) else None)
        if clauses:
            reason = "{0}\nrefused clauses: {1}".format(reason, list(clauses))
        return TrialOutcome(ok=False, refusal=reason)

    plan = authorization.plan

    # The WRITE side is resolved only now, after the gate has said yes -- the
    # same ordering the ordinary executor uses (`run_operation` authorizes, then
    # `_run_adapter_operation` resolves the write client), through the same
    # shared resolver, so a trial obtains its write credential exactly the way a
    # production write does.
    try:
        write_client = resolve_write_client(dispatch, op, fallback=client)
    except Exception as exc:
        raise TrialExecutorError(
            f"a connection able to make the change for {op.op_kind!r} could not "
            f"be obtained ({exc!r}). Nothing was applied.") from exc
    if write_client is None:
        raise TrialExecutorError(
            f"no connection able to make the change is available for "
            f"{op.op_kind!r} -- the adapter does not provide one and none was "
            "supplied -- so the trial could not carry the change through. "
            "Nothing was applied.")

    # THE WRITE-AHEAD RECORD. Unconditional, and before anything is mutated: the
    # full plan and every unit's recovery capsule are durable on disk when this
    # returns, and this function holds no units to apply until it does. There is
    # no argument that supplies or suppresses this journal.
    journal = trial_journal.open_trial_journal(
        plan, trial_id=trial_id, journal_dir=journal_dir)

    runs: List[_UnitRun] = []
    for unit in plan.units:
        run = _drive_unit(journal, dispatch, op, write_client, facade, unit,
                          lineage)
        runs.append(run)
        if not run.proved:
            # Stop. A proof can no longer be earned, and every further unit
            # would be a live mutation bought for nothing. Units not reached
            # stay at `planned` and were never applied, so there is nothing
            # outstanding for them.
            break

    recovery_required = tuple(
        r.outcome.unit_id for r in runs
        if r.outcome.journal_state == trial_journal.STATE_RECOVERY_REQUIRED)
    outcomes = tuple(r.outcome for r in runs)
    base = TrialOutcome(
        ok=False, trial_id=journal.trial_id, journal_path=journal.path,
        units=outcomes, recovery_required_unit_ids=recovery_required)

    # Post-condition 1 of 2 — the SAFETY question: is anything still changed on
    # the operator's surface? Read from the JOURNAL ON DISK, never from this
    # function's bookkeeping. See `_units_not_restored_on_disk` for what it
    # quantifies over and for the disclosed fact that this check is redundant with
    # post-condition 2 at this call site.
    planned_ids = tuple(u.unit_id for u in plan.units)
    unrestored = _units_not_restored_on_disk(journal, planned_ids)
    if unrestored:
        return TrialOutcome(
            ok=base.ok, trial_id=base.trial_id, journal_path=base.journal_path,
            units=outcomes, recovery_required_unit_ids=recovery_required,
            refusal=(
                "no proof was written: the trial is only proof of anything when "
                "EVERY unit it applied is recorded back at its prior state, and "
                f"these are not: {unrestored}. The durable record of what "
                f"happened to each unit is {journal.path}."))
    # Post-condition 2 of 2 — the EVIDENCE question, which is a different fact
    # with a different consequence: nothing is outstanding on the surface, but the
    # round trip was not OBSERVED end to end for every unit, so there is nothing
    # a proof could truthfully assert. Kept separate from post-condition 1 so the
    # refusal says which of the two happened; an operator reading "it did not come
    # back" must never be told that when everything did come back.
    unproved = [r.outcome.unit_id for r in runs if not r.proved]
    if unproved or len(runs) != len(planned_ids):
        return TrialOutcome(
            ok=base.ok, trial_id=base.trial_id, journal_path=base.journal_path,
            units=outcomes, recovery_required_unit_ids=recovery_required,
            refusal=(
                "no proof was written: every unit came back to its prior state, "
                "but the round trip was not observed end to end for "
                f"{unproved or list(planned_ids[len(runs):])}. Nothing external "
                "is outstanding; the trial simply did not prove what a proof "
                "asserts."))

    # The SAMPLED unit whose observed evidence the v1 schema's single
    # apply/undo evidence blocks carry -- the first in plan order, named in the
    # module docstring's DISCLOSED BOUND 1 rather than left to be inferred.
    sampled = runs[0]
    proof = _build_proof(
        op, contract, verifier, lineage, capability_id=capability_id,
        module_paths=module_paths, journal=journal,
        resolved_target=plan.resolved_target, sampled=sampled, lib_dir=lib_dir)

    # The SHIPPED validator -- the same one the acceptance ceremony runs -- gets
    # the last word BEFORE anything is written. A proof it rejects is never
    # placed at the path acceptance reads from: an artifact that looks like
    # evidence and is not is worse than no artifact.
    verdict = validate_copy_run_proof(proof)
    if not verdict.ok:
        return TrialOutcome(
            ok=False, trial_id=journal.trial_id, journal_path=journal.path,
            units=outcomes, recovery_required_unit_ids=recovery_required,
            refusal=(
                "no proof was written: the trial completed and every unit came "
                "back, but the proof this produced was not accepted by the same "
                f"check the acceptance step runs -- {verdict.reason}. Nothing "
                "external is outstanding."))

    path = copy_run_proof_path(capability_id, proof_dir=proof_dir)
    _atomic_write_json(path, proof)
    return TrialOutcome(
        ok=True, trial_id=journal.trial_id, journal_path=journal.path,
        proof_path=path, units=outcomes,
        recovery_required_unit_ids=recovery_required)
