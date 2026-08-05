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
    `recovery_required` with a stated cause, and no proof is emitted. That record
    is durable and outlives this process, and it is not a dead end: its ONE exit
    is `trial_recovery.recover_trial`, which reverses the unit again under a fresh
    write-ahead intent and clears the state only on an observed restore. The
    refusal this function returns NAMES that command, single-sourced from
    `trial_recovery.recovery_command`, so the surface that announces the blocking
    state and the surface that performs the repair cannot drift apart.
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
    a crashed apply landed. That is `trial_recovery`'s concern, in its own module,
    and it does not try to determine it either: it converges on the invariant
    instead. There is deliberately no stub, hook or placeholder for it here — the
    one thing this module borrows from it is the operator command its own refusal
    has to name, imported at the point of use so neither module has to import the
    other at module scope.
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

------------------------------------------------------------------------------
How a trial is STARTED — the operator-invocable entrypoint at the end of this
module
------------------------------------------------------------------------------
`run_trial` is the library entry; `run_trial_for_capability` and this module's
`__main__` are the operator's. Until they existed this module was a producer
nobody could start: the proof acceptance requires had a zone-legal, journaled,
crash-survivable producer, and no operator-invocable way to reach it — the same
shape as a repair that exists only as a Python function, which is the defect this
protocol's other half was built to close.

The entrypoint is kernel-side, like every other operator entrypoint in this
package and for the same reason: every place an operator project could put an
emitted script is CAPABILITY-zoned, where obtaining a write client is a scan
violation. It resolves nothing for itself — it asks the capability what it
proposes (through the kernel-as-runner, so the capability never holds a client),
takes the operator's own words as the approval and mints the write-gate receipt
through the sanctioned broker, and hands the result to `run_trial`. See
`run_trial_for_capability` for its own disclosed bounds.

Stdlib only — no third-party dependencies.
"""

import os
import shlex
import tempfile
from dataclasses import dataclass, replace as _dataclass_replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# sys.path bootstrap (mirrors `trial_journal.py` / `trial_recovery.py`): make the
# package parent importable when this file is run as a direct script from the
# project root, which is exactly how the operator invokes it.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

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
# The operator-invocable entrypoint, named in exactly one place
# ---------------------------------------------------------------------------

# The project-relative path of THIS file in an emitted operator project. Spelled
# once, here, because more than one surface has to point at it: this module's own
# `trial_command`, the operator-invocable command manifest (which hand-spells its
# prefixes and is pinned equal to this constant by a build-time test rather than
# importing this module into the hook that loads the manifest), and the acceptance
# CLI's own "no proof yet" next step. A re-spelling is how a named command comes
# to name a path that no longer exists.
TRIAL_ENTRYPOINT_REL = "agents/lib/external_write/trial_executor.py"

# Process exit codes, following this package's existing CLI convention (0 =
# succeeded, 1 = refused by domain logic, 2 = usage error). `EXIT_NOT_PROVED` is
# the domain refusal: the command ran correctly and the honest answer is that no
# proof could be earned. Non-zero so nothing monitoring the exit status can
# mistake it for a proof that exists.
EXIT_PROVED = 0
EXIT_NOT_PROVED = 1
EXIT_BAD_ARGS = 2

FLAG_CAPABILITY = "--capability"
FLAG_APPROVAL = "--operator-approval"
FLAG_BATCH_ID = "--batch-id"

# What a surface renders in place of the operator's words when nobody has said
# them yet. A machine that filled this in would be forging the approval the whole
# gate rests on, so the placeholder is visibly a blank to fill in -- the same rule
# and the same shape as the acknowledgement command's own placeholder.
APPROVAL_PLACEHOLDER = "<your own words approving a bounded trial>"

#: The batch label a manual trial run records when the operator supplies none.
DEFAULT_TRIAL_BATCH_ID = "trial"

USAGE = (
    f"Usage: python3 {TRIAL_ENTRYPOINT_REL} {FLAG_CAPABILITY} <capability name> "
    f"{FLAG_APPROVAL} <your own words, on one line> [{FLAG_BATCH_ID} <label>]\n"
    "Tries one thing this capability wants to do on your real record, checks it "
    "landed, puts it straight back, and checks it came back.\n"
    "It writes down what it observed as the evidence the acceptance step asks "
    "for -- and writes nothing at all if it could not observe the whole round "
    "trip.\n"
    "Run it from your project's top folder.\n"
    f"Exit codes: {EXIT_PROVED} = the round trip was proved and the evidence is "
    f"written; {EXIT_NOT_PROVED} = no evidence was written (it says why); "
    f"{EXIT_BAD_ARGS} = the command was not understood."
)


def trial_command(capability_id: str, *,
                  operator_approval: Optional[str] = None) -> str:
    """The exact, paste-ready command that runs a trial for ONE capability --
    rendered in ONE place so every surface that has to name it names the same one.

    `operator_approval` is optional on purpose, exactly as the acknowledgement
    command's confirmation is: a surface rendering this command as guidance (an
    acceptance refusal that has no proof to read, a skill) does not yet know what
    the operator will say and must not invent it. Omitted, it renders as
    `APPROVAL_PLACEHOLDER`, which is visibly a blank for the operator to replace.

    A SINGLE PHYSICAL LINE, every interpolated value `shlex.quote`'d -- a command
    that wraps is the paste hazard this package has already paid for once. Raises
    on an approval containing a line break rather than emitting a "single line"
    command that is not one: quoting escapes shell metacharacters but does not
    strip an embedded newline.
    """
    approval = (APPROVAL_PLACEHOLDER if operator_approval is None
                else operator_approval)
    parts = ["python3", TRIAL_ENTRYPOINT_REL,
             FLAG_CAPABILITY, str(capability_id),
             FLAG_APPROVAL, approval]
    # Over EVERY interpolated part, not only the approval. The guarantee is about
    # the rendered LINE, and both values are data this module does not own: a
    # capability id reaches the acceptance CLI straight from argv. A check on one
    # field is how the sibling field goes unchecked.
    for part in parts:
        if "\n" in part or "\r" in part:
            raise ValueError(
                "refusing to build a trial command: a value interpolated into it "
                f"contains a line break ({part!r}), and quoting does not strip "
                "one -- the rendered command would not be a single physical line.")
    return " ".join(shlex.quote(p) for p in parts)


def trial_command_or_reason(
        capability_id: str, *,
        operator_approval: Optional[str] = None) -> Tuple[Optional[str],
                                                          Optional[str]]:
    """`(command, None)`, or `(None, reason)` when no paste-ready command can be
    built for these values.

    THE ONE PLACE that decides whether a hint is renderable, and the only entry a
    surface RENDERING GUIDANCE should use. `trial_command` raises, which is right
    for a caller that owns its inputs -- but a surface offering the command as an
    affordance beside a refusal does not own them: the acceptance CLI takes the
    capability id straight from argv. Calling the raising renderer there printed
    the refusal correctly and then a raw Python traceback underneath it, which is
    the one thing this package's CLIs are not allowed to show an operator. The
    refusal is load-bearing and the hint is an affordance; a hint that cannot be
    built must never take the refusal down with it.

    A REASON, not merely `None`: a caller handed only `None` would have to invent
    the sentence explaining it, and inventing operator-facing text about a value it
    did not validate is how a wrong sentence gets written. Returned as a pair,
    matching this package's own idiom for a question whose failure the caller has
    to be able to describe (`parse_trial_args`, and recovery's facade step).

    The reason is deliberately a SINGLE LINE -- it is printed where a one-line
    command would otherwise sit.
    """
    try:
        return trial_command(capability_id,
                             operator_approval=operator_approval), None
    except ValueError:
        return None, (
            f"a ready-to-paste command cannot be built for `{capability_id!r}` "
            "because it contains a line break -- a command that wraps does not "
            "run when pasted. Use a name that is a single line.")


def parse_trial_args(argv: Any) -> Tuple[Optional[Dict[str, Optional[str]]],
                                         Optional[str]]:
    """Strict, fail-closed parse of a trial invocation's argv.

    Returns `(options, None)` for a recognized shape, or `(None, message)` for ANY
    other input. DENY BY DEFAULT: there is no branch that ignores an argument it
    does not recognize and proceeds anyway. This package has already shipped that
    defect once -- an unrecognized `--checkonly` probe was silently dropped and
    the wrapper ran the live job regardless -- and here the payload is a real
    write to the operator's own record.

    The operator's approval is REQUIRED here, not defaulted and not optional: a
    trial is a live write, and the one thing this command may never do is supply
    the words that authorize it.
    """
    args = list(argv or ())
    options: Dict[str, Optional[str]] = {FLAG_CAPABILITY: None,
                                         FLAG_APPROVAL: None,
                                         FLAG_BATCH_ID: None}
    index = 0
    while index < len(args):
        flag = args[index]
        if flag not in options:
            return None, f"unrecognized argument {flag!r}.\n\n{USAGE}"
        if index + 1 >= len(args):
            return None, f"{flag} needs a value.\n\n{USAGE}"
        options[flag] = args[index + 1]
        index += 2
    if not (options[FLAG_CAPABILITY] or "").strip():
        return None, f"missing required {FLAG_CAPABILITY}.\n\n{USAGE}"
    if not (options[FLAG_APPROVAL] or "").strip():
        return None, (
            f"missing required {FLAG_APPROVAL} -- a trial makes a real change to "
            "your own record and puts it back, so it runs only on your own "
            f"words.\n\n{USAGE}")
    if (options[FLAG_APPROVAL] or "").strip() == APPROVAL_PLACEHOLDER:
        # The blank a surface renders BEFORE the operator has said anything. Pasted
        # unedited it would carry this module's own placeholder into a real bounded
        # live write as the words authorizing it -- a machine supplying the approval
        # the whole gate rests on. Only the placeholder itself is refused (trimmed),
        # so words that merely quote the phrase still pass.
        return None, (
            f"the {FLAG_APPROVAL} is still the blank the command was printed with "
            f"({APPROVAL_PLACEHOLDER}). Replace it with your own words -- a trial "
            "makes a real change to your own record, so what authorizes it has to "
            "be what you said, not what was printed for you to fill in -- then run "
            "it again. If you are not sure what to put there, ask your assistant to "
            f"show you the command with your own wording already in it.\n\n{USAGE}")
    return options, None


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

# ---------------------------------------------------------------------------
# The two refusal DISCRIMINATORS — mutually exclusive by construction.
#
# `run_trial` can refuse a proof for two reasons that mean opposite things to the
# person reading the sentence:
#
#   NOT-RESTORED  — a unit is still changed on the operator's live record. Their
#                   data needs attention.
#   ALL-RESTORED-UNPROVED — nothing is outstanding at all; the round trip simply
#                   was not observed end to end, so nothing can be certified.
#
# Telling an operator the SECOND when the FIRST is true is a false operator-facing
# safety claim — they stop looking at data that is still changed. That is the
# failure class a continuity promise which was false when written already cost a
# real operator nine days of silently suppressed output.
#
# Each marker appears in EXACTLY ONE of the two refusals, and the tests assert
# both directions (present in its own, absent from the other). Single-sourced
# here rather than pinned as prose fragments in a test, so a rewording moves one
# string and the mutual-exclusivity assertion still binds — and a rewording that
# put both markers in one message fails the assertion rather than passing it.
# ---------------------------------------------------------------------------
REFUSAL_MARKER_NOT_RESTORED = (
    "not every unit is recorded back at its prior state")
REFUSAL_MARKER_NOTHING_OUTSTANDING = "Nothing external is outstanding"


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
    #: How many operations the capability PROPOSED, of which this trial carried
    #: one through. Carried on the outcome rather than passed alongside it,
    #: because the operator-facing sentence is rendered by a caller that would
    #: otherwise have to remember to supply it -- and the first version of that
    #: sentence had exactly that shape: a parameter the only caller never passed,
    #: so a disclosed bound ("the count is reported, so a capability proposing
    #: several is not silently narrowed") had no path to an operator at all.
    #: Defaults to 1, which is the truth for every caller that hands over one
    #: operation, including `run_trial` itself.
    proposed_operation_count: int = 1


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

def observe_unit(dispatch: Any, unit: Any, op_kind: str, *,
                 facade: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Observe `unit`'s CURRENT state on the real surface through `facade` — the
    READ-ONLY facade, never the write-capable client — and return
    `(poststate, None)` or `(None, reason)`.

    Returns rather than raises so the caller can reverse the unit and record an
    honest outcome; a raised exception here would abandon a mutated unit.

    PUBLIC, and `facade` is KEYWORD-ONLY, for one reason each. Public because the
    trial protocol now has two kernel drivers — this module and `trial_recovery`
    — and this is the ONLY place either of them calls `verify_one`. A second
    observation site would be a second place the write-capable client could reach
    an observer, which is exactly the boundary violation the credential split
    exists to prevent; there is one site, so there is one thing to audit.
    Keyword-only because the mistake with real consequences here is passing the
    write client where the facade belongs, and as a keyword-only parameter the
    interpreter refuses the transposition instead of a test catching it later.
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


def unit_evidence(op_kind: str, unit_id: str, poststate: Dict[str, Any],
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


def evaluate_evidence_predicate(dispatch: Any, predicate_name: str,
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


def _drive_unit(journal: Any, dispatch: Any, op: Operation, unit: Any,
                lineage: SourceLineage, *, write_client: Any,
                facade: Any) -> _UnitRun:
    """Apply, observe, reverse, observe — for exactly one unit.

    The two clients are KEYWORD-ONLY, and that is a safety property rather than a
    style choice. They were adjacent positional parameters, which means the one
    mistake with real consequences here — transposing them, so the observer gets
    the write-capable client and the mutations get a read-only facade — was a
    call-site typo away, catchable only by a test. As keyword-only parameters the
    transposition is not expressible: the interpreter refuses it. Removing the
    route beats detecting it.

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
        apply_poststate, reason = observe_unit(dispatch, unit, op_kind,
                                               facade=facade)
        if reason is not None:
            reasons.append(reason)
        else:
            apply_landed, reason = evaluate_evidence_predicate(
                dispatch, APPLY_PREDICATE_NAME,
                unit_evidence(op_kind, unit_id, apply_poststate, lineage))
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

    undo_poststate, reason = observe_unit(dispatch, unit, op_kind, facade=facade)
    if reason is not None:
        reasons.append(reason)
        journal.record_recovery_required(unit_id, reason=reason)
        return _UnitRun(
            outcome=TrialUnitOutcome(
                unit_id=unit_id, journal_state=journal.unit_state(unit_id),
                apply_landed=apply_landed, undo_restored=None,
                reason=" | ".join(reasons)),
            apply_poststate=apply_poststate)

    undo_restored, reason = evaluate_evidence_predicate(
        dispatch, UNDO_PREDICATE_NAME,
        unit_evidence(op_kind, unit_id, undo_poststate, lineage))
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

    WHAT THIS CHECK IS FOR, stated precisely because an earlier version of this
    docstring got it wrong. The proof-blocking effect of this check is
    over-determined at `run_trial`'s call site — a unit that is not restored is
    also a unit whose round trip was not observed, so the check that follows would
    refuse the proof too. What is NOT over-determined, and what this check alone
    establishes, is the TRUTHFULNESS OF THE REFUSAL: without it the operator is
    told "every unit came back to its prior state… nothing external is
    outstanding" about a trial in which a unit is durably `recovery_required` on
    their live record. That is a false operator-facing safety claim, and an
    operator who reads it stops looking. `REFUSAL_MARKER_NOT_RESTORED` /
    `REFUSAL_MARKER_NOTHING_OUTSTANDING` are the mutually-exclusive discriminators
    that make the difference assertable, and the tests assert both directions.
    Deleting this check does not merely lose a redundant guard; it ships the
    false claim.

    (A second reason, forward-looking: a RESUMED trial's in-memory run list will
    not cover every planned unit, so the enumeration-side check will no longer be
    able to stand in for this one at all.)
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
    #
    # GATED OPERATIONS ONLY. `evaluate_write_gate` permits an ungated op BEFORE
    # target resolution, the cap and the ledger, so for the five of ten shipped
    # `op_kind`s whose contract is `reversible_external` without
    # `requires_accepted_phase` the live-bounded branch is never reached and a
    # trial of one enforces no limit at all. See write_authorization.py's
    # module docstring.
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
        run = _drive_unit(journal, dispatch, op, unit, lineage,
                          write_client=write_client, facade=facade)
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
    # function's bookkeeping. It must be checked FIRST and it must win: post-
    # condition 2 would also refuse the proof here, but it would refuse it while
    # saying nothing is outstanding — which is false whenever this one fires, and
    # is the sentence that makes an operator stop looking at data that is still
    # changed. This check is what keeps that sentence true, so it is load-bearing
    # for the CLAIM even where the refusal itself is over-determined.
    planned_ids = tuple(u.unit_id for u in plan.units)
    unrestored = _units_not_restored_on_disk(journal, planned_ids)
    if unrestored:
        # NAME the repair, do not merely report the state. A durable blocking
        # record with no command attached hands the operator a verdict; the
        # command is single-sourced from the module that performs it, imported
        # here at the point of use so the two modules need no module-scope
        # dependency on each other, and so a later declarative registry has ONE
        # function to bind rather than two hand-written sentences to reconcile.
        from external_write.trial_recovery import recovery_command
        return TrialOutcome(
            ok=base.ok, trial_id=base.trial_id, journal_path=base.journal_path,
            units=outcomes, recovery_required_unit_ids=recovery_required,
            refusal=(
                "no proof was written: the trial is only proof of anything when "
                "every unit it applied is recorded back at its prior state, and "
                f"{REFUSAL_MARKER_NOT_RESTORED} — these are not: {unrestored}. "
                "Those units may still be changed on the real surface. The "
                f"durable record of what happened to each unit is {journal.path}. "
                "To bring them back and have the result checked, run:\n"
                + recovery_command(journal.trial_id, journal_dir=journal_dir)))
    # Post-condition 2 of 2 — the EVIDENCE question, which is a different fact
    # with a different consequence: nothing is outstanding on the surface, but the
    # round trip was not OBSERVED end to end for every unit, so there is nothing
    # a proof could truthfully assert. Kept separate from post-condition 1 so the
    # refusal says which of the two happened; an operator reading "it did not come
    # back" must never be told that when everything did come back, and — the
    # direction that actually cost someone something — must never be told that
    # everything came back when it did not.
    unproved = [r.outcome.unit_id for r in runs if not r.proved]
    if unproved or len(runs) != len(planned_ids):
        return TrialOutcome(
            ok=base.ok, trial_id=base.trial_id, journal_path=base.journal_path,
            units=outcomes, recovery_required_unit_ids=recovery_required,
            refusal=(
                "no proof was written: every unit came back to its prior state, "
                "but the round trip was not observed end to end for "
                f"{unproved or list(planned_ids[len(runs):])}. "
                f"{REFUSAL_MARKER_NOTHING_OUTSTANDING}; the trial simply did not "
                "prove what a proof asserts."))

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
                f"check the acceptance step runs -- {verdict.reason}. "
                # Reached only AFTER both post-conditions passed, so this claim
                # is true here — the same marker, single-sourced, rather than a
                # second spelling of the same promise.
                f"{REFUSAL_MARKER_NOTHING_OUTSTANDING}."))

    path = copy_run_proof_path(capability_id, proof_dir=proof_dir)
    _atomic_write_json(path, proof)
    return TrialOutcome(
        ok=True, trial_id=journal.trial_id, journal_path=journal.path,
        proof_path=path, units=outcomes,
        recovery_required_unit_ids=recovery_required)


# ---------------------------------------------------------------------------
# The OPERATOR's entry: what an invocation has to assemble, and what it may not
# ---------------------------------------------------------------------------

def _validated_operator_approval(approval: Any) -> str:
    """The operator's own words, or a refusal.

    Never defaulted, never generated, and blank is never accepted. A trial is a
    real live write to a bounded subset of the operator's own record; the words
    that approve it are the one thing this module must not be able to supply.
    """
    if not (isinstance(approval, str) and approval.strip()):
        raise TrialExecutorError(
            "a trial makes a real change to your own record and then puts it "
            "back, so it runs only on your own words approving it -- nothing was "
            f"proposed and nothing was changed. Got {approval!r}.")
    return approval


def _warmed_read_facade_registry(op_kind: str, *,
                                 lib_dir: Optional[str] = None) -> None:
    """POPULATE the read-facade registry for `op_kind` if it is not already.

    The step a FRESH process needs and a warm one does not. Nothing in production
    imports a read-facade module at module scope; the registry `build_read_facade`
    resolves from is populated only by such an import, and this is an
    operator-invoked command in a process where nothing has imported one.

    The population goes through the ONE shared resolver
    (`capability_runner.import_declared_read_facade`) -- the same one the recovery
    entrypoint and the capability-facing resolver use. "Which module provides
    read-only access for this operation" is a classification, and a second
    implementation of it would be this package's most expensive recurring defect
    shape.

    DISCLOSED, because a guard whose value is overstated is worse than none: the
    proposal step this entrypoint runs first resolves through that SAME shared
    function (`capability_runner.resolve_read_facade_class`), so on the ordinary
    path the registry is already warm by the time this runs and the guard
    short-circuits. What this is for is that the facade `run_trial` resolves is
    the one for the OPERATION being trialled, and this entrypoint does not depend
    on another step's side effect for it. It is deliberately called from the
    runtime path and NOT at module scope: `trial_executor` is imported at module
    scope by every project that touches the health surface, and warming there
    would fire read-facade module imports on every health check in every project.

    Errors are not caught here. A reader that cannot be resolved means the trial
    cannot observe the surface, and `run_trial` refuses on exactly that a moment
    later -- swallowing it here would replace a specific refusal with a vaguer
    one. (Recovery is in the opposite position and reports a reason instead: it
    may have a unit outstanding on the live record right now, so it converges the
    surface first and reports the unverifiable verdict second.)
    """
    from external_write.capability_runner import import_declared_read_facade
    from external_write.read_facade import get_read_facade_class

    if get_read_facade_class(op_kind) is None:
        import_declared_read_facade(op_kind, lib_dir=lib_dir)


def run_trial_for_capability(capability_id: str, *,
                             operator_approval: Any,
                             project_root: Any = ".",
                             batch_id: Optional[str] = None,
                             descriptor_set: Any = None,
                             cap_ledger: Any = None,
                             clock: Any = None,
                             paused_root: Optional[str] = None,
                             journal_dir: Optional[str] = None,
                             proof_dir: Optional[str] = None,
                             lib_dir: Optional[str] = None,
                             review_dir: Optional[str] = None,
                             trial_id: Optional[str] = None) -> TrialOutcome:
    """Run a trial of what `capability_id` proposes, on the operator's own words.

    The operator-facing half of `run_trial`, and the only thing this module's
    `__main__` calls. It assembles what a trial needs and resolves NOTHING for
    itself:

      * WHAT to trial comes from the capability, through the kernel-as-runner
        (`capability_runner.run_capability_proposal`), so the capability is CALLED
        with a kernel-built read-only facade and never holds a client of its own.
      * THE APPROVAL is the operator's own words, minted into a write-gate receipt
        through the sanctioned broker (`broker.ApprovalBroker`), which records
        those words verbatim and binds the receipt to the exact operation's
        digest. This module never invents one: `run_trial` documents that it never
        mints a receipt, and an entrypoint that minted its own would be forging
        the consent the whole gate rests on.
      * EVERY enforcement step is `run_trial`'s and `authorize_operation`'s,
        unchanged: the trial-eligibility preflight, the mandatory blast-radius
        cap, the invocation ledger, the recovery floor, the declared-test-target
        requirement and receipt validation. Nothing here relaxes any of them and
        there is no flag that could. READ "EVERY" NARROWLY: it ranges over every
        step this entrypoint could have relaxed and did not. It is NOT a claim
        that every step runs for every operation.
      * GATED OPERATIONS ONLY. `evaluate_write_gate` permits an ungated op
        BEFORE target resolution, the cap and the ledger, so for the five of ten
        shipped `op_kind`s whose contract is `reversible_external` without
        `requires_accepted_phase` the live-bounded branch is never reached and a
        trial of one enforces no limit at all. A trial of one of those is still
        apply-then-undo with the round trip verified before any proof is
        written, so the harm is bounded by reversibility -- but reversibility
        there is a DECLARATION by whoever wrote the contract, not something this
        entrypoint establishes. See write_authorization.py's module docstring.

    Parameters
    ----------
    capability_id:
        the capability to trial. Its module is `agents/capabilities/
        <capability_id>_capability.py` -- the canonical identity the scaffold
        owns, not a guess at a filename.
    operator_approval:
        the operator's own words approving a bounded trial on their real record.
        Required; blank refuses.
    project_root / batch_id:
        where the capability lives, and the label recorded for this run.
    descriptor_set / cap_ledger / clock / paused_root / journal_dir / proof_dir /
    lib_dir / review_dir / trial_id:
        overrides for callers (tests above all) that must not depend on ambient
        project state. Every default is the production convention.

    Returns a `TrialOutcome` -- `ok` is True only when a proof was written and the
    SHIPPED validator accepted it.

    Raises `TrialExecutorError` when the trial cannot be set up at all (nothing
    proposed, nothing applied, nothing written), and lets
    `capability_runner.CapabilityRunnerError` propagate unchanged: it already says
    in plain language what about the capability could not be run, and re-wrapping
    it would hide which mechanism refused.

    DISCLOSED BOUND -- ONE proposed operation is trialled: the FIRST the capability
    proposes, stated here rather than left to be inferred. A trial earns evidence
    about a write path, and the `copy_run_proof-v1` schema carries one operation's
    observed apply/undo evidence; trialling every proposal would multiply live
    writes without adding anything the proof can assert. The count is reported to
    the operator so a capability proposing several is not silently narrowed. Every
    proposed operation must name the op_kind the capability DECLARES -- the facade
    the proposal step was given was built for that op_kind, so an operation naming
    another one would trial a surface this capability never declared.
    """
    # The private importer is REUSED rather than reimplemented (the same
    # discipline the acceptance record's own existence check is shared under): it
    # resolves the capability module by the identity invariant, and reading the
    # op_kind the module DECLARES off it is what makes the check below a
    # comparison against a declared value rather than against a guess.
    from external_write.broker import ApprovalBroker
    from external_write.capability_runner import (
        CAPABILITIES_DIR_REL, CAPABILITY_MODULE_SUFFIX,
        _import_capability_module, run_capability_proposal,
    )
    from external_write.write_gate import InvocationLedger

    approval = _validated_operator_approval(operator_approval)
    cid = _validated_capability_id(capability_id)
    module_stem = f"{cid}{CAPABILITY_MODULE_SUFFIX}"
    module_paths = (f"{CAPABILITIES_DIR_REL}/{module_stem}.py",)

    operations = run_capability_proposal(
        project_root, cid, batch_id=batch_id or DEFAULT_TRIAL_BATCH_ID)
    if not operations:
        raise TrialExecutorError(
            f"`{cid}` proposed nothing to change, so there is nothing to try. A "
            "trial earns its evidence by carrying one real change through and "
            "putting it back; with nothing proposed there is nothing to carry. "
            "Nothing was changed and nothing was written.")

    declared_op_kind = getattr(
        _import_capability_module(Path(project_root), cid), "OP_KIND", None)
    for candidate in operations:
        if candidate.op_kind != declared_op_kind:
            raise TrialExecutorError(
                f"`{cid}` says it works on {declared_op_kind!r} but proposed "
                f"{candidate.op_kind!r}. The read-only view it was given was "
                "built for what it declares, so this would try a change against "
                "something it never said it works on. Fix step: this capability "
                "needs to be rebuilt so what it proposes matches what it "
                "declares. Nothing was changed and nothing was written.")

    op = operations[0]
    _warmed_read_facade_registry(op.op_kind, lib_dir=lib_dir)

    # The sanctioned approval path, not a self-issued receipt: the broker records
    # the operator's verbatim words and binds one receipt per operation to that
    # operation's own digest, which is what `validate_receipt` checks. The proof
    # gate stays OFF here, deliberately and necessarily -- it exists to stop the
    # first LIVE use of unproven write logic, and a trial is how that logic earns
    # its proof. Enabling it would make the evidence a precondition of producing
    # the evidence.
    broker = ApprovalBroker(review_dir=review_dir)
    proposal = broker.propose([op])
    receipt = broker.confirm(proposal.pending_token, approval)

    # THE BLAST-RADIUS WINDOW, and it is the shipped ledger rather than anything
    # of this module's own: the gate REFUSES a live-bounded operation with no
    # ledger, because the cap cannot be enforced without one. The window is the
    # caller's to choose, and one invocation is one window here -- which is the
    # honest choice rather than a convenient one, because each invocation carries
    # its own FRESH operator approval, freshly typed. That is what makes this
    # unlike the defect a persistent ledger exists to stop: there, ONE approved
    # run was subdivided into chunks and each chunk minted its own window, so a
    # single approval bought an unbounded number of capped windows. Here the cap
    # bounds the units of THIS approval, and a second window costs a second
    # approval. Disclosed rather than implied, because the trade is real: nothing
    # accumulates a count ACROSS trials, so the cap is a per-approval bound and
    # not a lifetime one -- and a lifetime one would eventually leave a capability
    # that can never be trialled again, with no operator-facing way to clear it.
    outcome = run_trial(
        op, receipt.op_receipts[op.digest()],
        capability_id=cid, capability_module_paths=module_paths,
        descriptor_set=descriptor_set,
        cap_ledger=cap_ledger if cap_ledger is not None else InvocationLedger(),
        clock=clock, paused_root=paused_root, journal_dir=journal_dir,
        proof_dir=proof_dir, lib_dir=lib_dir, trial_id=trial_id)
    # The count travels ON the outcome, so the one sentence an operator reads
    # cannot be rendered without it. `run_trial` is handed one operation and knows
    # nothing about how many were proposed, which is why it is set here.
    return _dataclass_replace(outcome,
                              proposed_operation_count=len(operations))


def trial_summary(outcome: TrialOutcome, *, capability_id: str) -> str:
    """The operator-facing sentence for a completed trial.

    A trial that could not earn a proof already carries the gate's own
    plain-language reason (`TrialOutcome.refusal`), and that text is surfaced
    verbatim rather than re-described: the two refusals mean opposite things to
    the person reading them -- one says a change may still be live on their
    record, the other says nothing is outstanding -- and a second wording here
    would be a second chance to say the wrong one.

    A not-ok outcome carrying NO reason gets its own sentence rather than
    `str(None)`: "None" is not a reason, and the honest thing to say about a run
    that recorded nothing is that nothing can be established from it -- so this
    branch claims neither that something is outstanding nor that nothing is, and
    routes to a person. Every other refusal path in this module sets a reason;
    this exists because "cannot happen today" is not a property.

    The proposal count is read off the OUTCOME, never taken as a parameter. See
    `TrialOutcome.proposed_operation_count`.
    """
    if not outcome.ok:
        if outcome.refusal:
            return outcome.refusal
        return (
            f"The trial for `{capability_id}` did not produce the evidence the "
            "acceptance step asks for, and it did not record why. Nothing here "
            "can tell you whether a change it made is still on your real record. "
            f"The durable record of the run is {outcome.journal_path} -- ask your "
            "assistant to look at that file with you before treating anything as "
            "finished.")
    proposed = outcome.proposed_operation_count
    extra = ("" if proposed <= 1 else
             f" `{capability_id}` proposed {proposed} things to change; a trial "
             "carries one of them through, so this covers the first.")
    return (
        f"The trial for `{capability_id}` carried one change through on your real "
        "record, checked it landed, put it back, and checked it came back. Your "
        f"record is as it was.{extra}\nThe evidence the acceptance step asks for "
        f"is written to {outcome.proof_path}.\nThe durable record of the run "
        f"itself is {outcome.journal_path}.")


# ---------------------------------------------------------------------------
# CLI -- the operator-invocable way IN to the trial protocol.
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
    # level: this module is imported as a library by the health surface's own
    # import chain, which must not eagerly register every adapter as a side
    # effect. Same placement, for the same reason, as the recovery CLI's own
    # import of it.
    import external_write.registered_adapters  # noqa: E402,F401
    from external_write.capability_runner import (  # noqa: E402
        CapabilityRunnerError, ReadFacadeDeclarationError,
    )
    from external_write.topology import TopologyError  # noqa: E402
    from external_write.trial_journal import TrialJournalError  # noqa: E402

    _options, _error = parse_trial_args(_sys.argv[1:])
    if _error is not None:
        print(_error, file=_sys.stderr)
        _sys.exit(EXIT_BAD_ARGS)

    _capability_id = _options[FLAG_CAPABILITY]
    try:
        _outcome = run_trial_for_capability(
            _capability_id,
            operator_approval=_options[FLAG_APPROVAL],
            batch_id=_options[FLAG_BATCH_ID])
    except (TrialExecutorError, TrialJournalError, CapabilityRunnerError,
            TopologyError, ReadFacadeDeclarationError) as _exc:
        # A refusal, in plain language, and never an all-clear: no evidence was
        # written. Exit 1, so nothing checking the status reads it as a proof.
        print(str(_exc), file=_sys.stderr)
        _sys.exit(EXIT_NOT_PROVED)

    _message = trial_summary(_outcome, capability_id=_capability_id)
    if _outcome.ok:
        print(_message)
        _sys.exit(EXIT_PROVED)
    print(_message, file=_sys.stderr)
    _sys.exit(EXIT_NOT_PROVED)
