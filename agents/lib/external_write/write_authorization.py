"""Authorization, split from execution — the ONE place an external write is
authorized, and the single carrier both executors consume.

------------------------------------------------------------------------------
Why this module exists
------------------------------------------------------------------------------
`adapters.run_operation` used to do two jobs in one function body: it planned the
effect units, ran the deterministic pre-write gate, validated the receipt, and
then — in the very same call — applied those units. That is fine for the ordinary
write path, which applies and returns. It is NOT fine for a journaled TRIAL
(`apply -> verify -> undo -> verify-restored` against a real, bounded live
target), which must write a per-unit journal entry to disk BEFORE each mutation
so that a crash part-way through leaves something on disk able to drive recovery.

A trial therefore cannot simply call `run_operation`: that call enters the bare
apply loop immediately (`adapters._run_adapter_operation`), and the adapter layer
writes nothing to disk at all — so a partial application would leave real
mutations behind with no record of them anywhere.

The fix is NOT a second copy of the authorization logic. Two authorization paths
that must agree is the failure mode this package has paid for more than once. The
fix is to split the ONE authorization implementation out of execution:

    plan -> preflight -> authorize through the EXISTING live-bounded funnel
         -> AuthorizedPlan -> ordinary executor OR journaled trial executor

Both executors consume the SAME `AuthorizedPlan`. `run_operation` is the ordinary
executor's entry point and is now a CALLER of `authorize_operation` — so there is
exactly one implementation of "may this write proceed", and it is exercised on
every production write in the system, not only on the trial path.

------------------------------------------------------------------------------
What is, and is not, relaxed for a trial
------------------------------------------------------------------------------
Nothing here relaxes any enforcement, and there is deliberately NO "trial mode"
flag that could. A trial is authorized through `write_gate.evaluate_write_gate`'s
EXISTING live-bounded branch, which runs the SAME shared live-enforcement funnel
as an accepted live write: the recovery floor, the mandatory blast-radius cap, the
invocation ledger, and the irreversibility audit. No cap is re-implemented here.
No second ledger exists. Nothing is counted twice and nothing is counted less.

The ONE relaxation is the one that branch already grants — and it grants it to
every caller, not specially to a trial: `accepted: true` is not required, because
a DECLARED capability whose `declared_test_target` exactly matches the requested
target suffices before acceptance. Acceptance is precisely what a trial exists to
earn. A DECLARATION is still mandatory, and so is everything else.

The trial intent additionally NARROWS what is permitted, in two ways:

  * The target the gate will actually act on must be exactly `TRIAL_TARGET`.
    Every other value is refused, each for its own reason: `dry_run` performs no
    write at all, so a restoration proof derived from it would be evidence of
    nothing; `copy` lands on a separated surface, which cannot produce evidence
    about the operator's live record; an affirmative live target requires the
    very acceptance a trial exists to earn; `bounded_sample` is the OTHER
    live-bounded target and is refused for a reason of its own, given at
    `TRIAL_TARGET`'s own definition below; and an absent signal is refused, as it
    is everywhere else.
    The check is made against the target the GATE resolves
    (`write_gate.resolve_effective_target`), never the requested string — an
    operation on the copy-surface convention resolves to `copy` no matter what
    its caller asked for, and would take the gate's isolated branch (no cap, no
    ledger) while a naive check on the request string still believed a
    live-bounded funnel had run.

  * The trial-eligibility preflight (`trial_eligibility.check_trial_eligibility`)
    must return an ELIGIBLE verdict for exactly the planned units.

------------------------------------------------------------------------------
The preflight is UNAVOIDABLE — precisely what makes it so
------------------------------------------------------------------------------
A gate that exists and is not on the enforced path is worth nothing. Four
structural facts, not one convention, put the preflight on the path:

  1. `AuthorizedPlan` is the ONLY carrier of authorization in this package. A
     trial executor is handed one; it has no other source of the units to apply,
     the dispatch to apply them through, or the audit to record.

  2. Bringing an `AuthorizedPlan` into existence requires this module's private
     construction token, and "bringing into existence" is meant to cover every
     route Python offers, not just `AuthorizedPlan(...)`:
       * a direct construction without the token raises;
       * the token is an `InitVar`, so it is NOT retained as a field — it cannot
         be read back off a plan you were legitimately handed, and
         `dataclasses.replace` cannot carry it forward, so `replace` raises
         (this is the route that made an earlier version of this docstring
         false: while the token was an ordinary field, `replace` inherited it and
         could swap the units, the dispatch, the target, or escalate an ordinary
         plan to a trial plan, all while holding no token);
       * `__copy__` / `__deepcopy__` / `__reduce__` / `__replace__` all raise, so
         copying, deep-copying, pickling and (on interpreters that have it) the
         `copy.replace` protocol cannot yield a carrier that skipped
         `__post_init__`. An authorization is not a portable document: reviving
         one in another process, at another time, with the registry in another
         state, is not something the gate ever authorized.
       * SUBCLASSING raises, via `__init_subclass__`. This was the one route the
         claim above did not actually cover, and it was the worst of them: a
         subclass that OVERRIDES `__post_init__` never runs the token check at
         all, so its instances carry NONE of the invariants below while still
         satisfying `isinstance(plan, AuthorizedPlan)` in every consumer — and
         the token is never named, so no guard watching the token could see it.
         It is refused at class-creation time rather than instance-creation time,
         so the refusal cannot depend on what the subclass happens to override.

  3. A trial-intent plan re-validates its own preconditions in
     `__post_init__`, so the invariants hold at CONSUMPTION time, not merely at
     the moment they were checked: the carried verdict must be a real
     `trial_eligibility.TrialEligibility`, eligible, with no refusals, for THIS
     operation kind; the plan's units must be byte-equal to the units that
     verdict blessed (a check-then-swap cannot substitute a different plan after
     the blessing); the resolved target must be the trial target; a dispatch must
     exist AND be the one the registry currently holds for this operation kind
     (`dispatch is None` alone was not enough — a plan carrying a DIFFERENT
     adapter's dispatch would apply the blessed units through someone else's
     `apply_one`); and the recovery capsules must be a mapping. An ordinary plan
     is forbidden from carrying a trial verdict at all.

  4. `authorize_operation` calls the preflight UNCONDITIONALLY on the trial
     branch — there is no flag, no argument and no early exit that skips it —
     and it calls it BEFORE the live-enforcement funnel, so an ineligible
     operation never consumes a blast-radius slot it was never entitled to.

DISCLOSED BOUND — the ceiling is unchanged: build-time enforcement plus
operator-as-approver. This is not a runtime sandbox and not an OS-level control,
and the bound is stated as what it actually is rather than as the strongest thing
that could be said. Two forgeries remain available to an author who sets out to
commit one: reaching into this module for the private `_ISSUED_BY_AUTHORIZE`
sentinel AND hand-building an eligible-looking verdict (nothing can check a
verdict's provenance — it is an ordinary frozen record); or reaching past a
guard at runtime — rewriting a genuine plan in place with `object.__setattr__`,
or deleting `__init_subclass__` off the class — neither of which any Python
object can prevent. Both are exactly as available as mis-implementing `undo_one`
has always been.

This enumeration was previously WRONG rather than merely conservative: it said
two, but subclassing-with-an-overriding-`__post_init__` was a third, undisclosed
route, and the claim above that construction "covers every route Python offers"
did not hold for it. `__init_subclass__` closes it, and a companion AST
assertion over this package's own source
(`test_external_write_write_authorization._modules_subclassing`) catches any
in-package use of the route if that guard is ever removed. The count is two
because the route was closed, not because it was overlooked again.

What is structurally true is narrower and is the thing the design rests on: no
path through this package's own production code, and no ordinary
reconstruction, copy, revival or specialization of a plan a consumer was handed,
yields a trial authorization without the preflight having returned an eligible
verdict for exactly the units that will be applied.

------------------------------------------------------------------------------
What this module does NOT do
------------------------------------------------------------------------------
  * It performs no external write and no external read. It plans (a
    contractually PURE adapter call), consults the gate, validates the receipt,
    and returns a value.
  * It never takes, resolves, constructs or returns a write-capable client.
    Credential isolation is unchanged: the write-capable client is still
    resolved inside the adapter EXECUTION path, keyed by the registered
    adapter's own captured provisioner, and this authorization surface cannot
    even name one.
  * It writes nothing to disk ITSELF. Stated precisely, because a looser claim
    would be false: the gate it calls consumes the blast-radius ledger, and when
    the caller supplies a PERSISTENT ledger that consumption is a real disk
    write — unchanged from before this split, and it is the ledger's own file,
    reached through the shared funnel, never anything this module writes. The
    write-ahead journal a trial needs is a separate concern with its own module;
    this one hands it an authorized plan.
  * It does not execute anything. Both executors live elsewhere: the ordinary
    one is `adapters.run_operation`'s tail, and a journaled trial executor is a
    separate module that consumes the same `AuthorizedPlan`.

Zone: SEALED_KERNEL (enumerated in `zones.py`). It reads sibling kernel
submodules (`adapter_registry`, `operations`, `trial_eligibility`, `write_gate`)
as ordinary internal kernel wiring, imports no vendor SDK, constructs no
credential, and performs no vendor mutation.

Stdlib only — no third-party dependencies.
"""

from collections.abc import Mapping
from dataclasses import InitVar, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from external_write import trial_eligibility
from external_write.adapter_registry import get_dispatch
from external_write.operations import Operation, Result
from external_write.write_gate import (
    LIVE_BOUNDED_TEST_TARGETS, InvocationLedger, evaluate_write_gate,
    resolve_effective_target,
)


# ---------------------------------------------------------------------------
# Execution intent. Two values, both explicit — never a boolean "is_trial" flag
# and never an absent-means-trial default. An unrecognized value REFUSES rather
# than falling through to either branch.
# ---------------------------------------------------------------------------
EXECUTION_INTENT_ORDINARY = "ordinary"
EXECUTION_INTENT_TRIAL = "trial"
EXECUTION_INTENTS: Tuple[str, ...] = (EXECUTION_INTENT_ORDINARY,
                                      EXECUTION_INTENT_TRIAL)

# The machine-readable name this module stamps into its own refusal details, in
# the convention `write_gate` already established with "write_gate_v1".
AUTHORIZATION_GATE_NAME = "write_authorization_v1"

# The ONE target a trial may run against — deliberately narrower than the gate's
# `LIVE_BOUNDED_TEST_TARGETS`, which this does NOT redefine.
#
# Why one and not both. The two live-bounded targets are not interchangeable:
# the gate's own branch distinguishes them as perform-then-revert
# (`native_undo`) versus a bounded live sample (`bounded_sample`), and only the
# first describes what a trial does. A trial ALWAYS reverts — that is the whole
# point of `apply -> verify -> undo -> verify-restored`. So permitting
# `bounded_sample` would mean a capability whose operator-DECLARED test target
# says "a bounded sample, which persists" instead undergoes a reverting trial:
# the system doing something other than what the declaration describes. That is
# the declaration-fidelity failure this safety machinery exists to prevent, so
# it is refused here rather than shipped inside the mechanism meant to close it.
#
# Fail-closed and deliberately narrow: `bounded_sample` remains perfectly legal
# for its own, non-trial purpose (an ordinary write against a bounded-sample
# declaration is unaffected — only the TRIAL intent is narrowed). Widening this
# later is a one-line, reviewable change; an over-wide enforcement vocabulary
# shipped silently is not.
TRIAL_TARGET = "native_undo"


class AuthorizationRequiredError(Exception):
    """Raised when something attempts to bring an `AuthorizedPlan` into
    existence other than by being authorized.

    Deliberately an EXCEPTION, not a refusal Result: a refusal is the answer to
    a legitimate request ("may this write proceed?"), whereas this is a caller
    that has bypassed the question entirely. It must not be catchable as an
    ordinary "no" and must never be mistakable for one.
    """


# The private construction token. `AuthorizedPlan.__post_init__` requires
# identity against THIS object, so a plan cannot be constructed by anything that
# does not hold it — and it is passed at exactly one place (see
# `authorize_operation`). A plain sentinel object, in the same idiom
# `trial_eligibility._NO_BAD_KEY` uses: nothing about it is guessable or
# reconstructible, because identity is the whole check.
#
# It is declared on the carrier as an `InitVar`, which is load-bearing in two
# ways beyond documentation: the token is NOT retained as a field, so it cannot
# be read back off a plan a consumer was legitimately handed; and
# `dataclasses.replace` therefore cannot carry it forward, so a `replace` call
# reaches `__post_init__` with the default `None` and is refused. Both matter
# because a trial executor IS handed a plan.
_ISSUED_BY_AUTHORIZE = object()


@dataclass(frozen=True)
class AuthorizedPlan:
    """One authorized operation, ready to execute — the single thing both the
    ordinary executor and a journaled trial executor consume.

    Fields
    ------
    op:          the `Operation` that was authorized.
    intent:      `EXECUTION_INTENT_ORDINARY` or `EXECUTION_INTENT_TRIAL`.
    target:      the target signal as REQUESTED by the caller (may be None).
    resolved_target:
                 the target the gate actually acted on
                 (`write_gate.resolve_effective_target`) — this, never `target`,
                 is what the trial invariant is checked against.
    dispatch:    the FROZEN `adapter_registry.AdapterDispatch` for this op_kind,
                 or None for the legacy field-write path (no registered
                 adapter). Carried so an executor uses the same captured record
                 authorization resolved, never a fresh lookup that could have
                 changed underneath it — and validated below to BE the record the
                 registry currently holds for this operation kind, so a plan
                 cannot carry a different adapter's dispatch.
    units:       the planned effect units, as a tuple — or None for the legacy
                 field-write path and for a dry_run (which never plans).
    gate_audit:  the gate's audit dict to merge into a successful result (e.g.
                 the clock-stamped irreversibility acknowledgement); None when
                 the gate wrote no audit record.
    trial_verdict:
                 the `trial_eligibility.TrialEligibility` this plan rests on —
                 present IFF `intent` is the trial intent, and forbidden
                 otherwise.
    recovery_capsules:
                 the per-unit recovery capsules the preflight checked, carried
                 through to whatever writes the journal. Present for the trial
                 intent; None otherwise.
    issued_by:   an `InitVar`, NOT a retained field: it must be this module's
                 private construction token, and because it is not kept it can
                 neither be read back off a plan nor carried forward by
                 `dataclasses.replace`. See the module docstring's "The preflight
                 is UNAVOIDABLE" section.

    Every invariant below is re-validated HERE rather than only at the moment
    authorization computed it, so the guarantees hold at consumption time.
    """

    op: Operation
    intent: str
    target: Optional[str]
    resolved_target: Optional[str]
    dispatch: Any
    units: Optional[Tuple[Any, ...]]
    gate_audit: Optional[Dict[str, Any]]
    trial_verdict: Any = None
    recovery_capsules: Any = None
    issued_by: InitVar[Any] = None

    def __post_init__(self, issued_by: Any) -> None:
        if issued_by is not _ISSUED_BY_AUTHORIZE:
            raise AuthorizationRequiredError(
                "an AuthorizedPlan can only be produced by "
                "write_authorization.authorize_operation -- it is the single "
                "authorization implementation, and a hand-built plan would be "
                "an external write that nothing authorized")
        if self.intent not in EXECUTION_INTENTS:
            raise AuthorizationRequiredError(
                f"unrecognized execution intent {self.intent!r}; must be one of "
                f"{list(EXECUTION_INTENTS)}")

        # The carried dispatch must BE the record the registry holds for this
        # operation kind. Checking only `is None` (as an earlier version did) let
        # a plan carry a DIFFERENT adapter's dispatch, so the preflight-blessed
        # units would be applied through someone else's `apply_one`. Identity
        # against the registry is the same resolution both the preflight and
        # `authorize_operation` performed, so a legitimately-issued plan always
        # passes; a plan whose op_kind was re-registered since it was authorized
        # correctly stops being valid, which is the fail-closed direction. The
        # legacy field-write path has no adapter, so both sides are None and this
        # is satisfied by agreement rather than by exemption.
        if self.dispatch is not get_dispatch(self.op.op_kind):
            raise AuthorizationRequiredError(
                "this plan's adapter dispatch is not the one currently "
                f"registered for operation kind {self.op.op_kind!r} -- a plan "
                "may not carry another adapter's dispatch, and a plan whose "
                "adapter was re-registered after it was authorized is no longer "
                "the plan that was authorized")

        if self.intent != EXECUTION_INTENT_TRIAL:
            if self.trial_verdict is not None:
                raise AuthorizationRequiredError(
                    "an ordinary-intent AuthorizedPlan must not carry a trial "
                    "eligibility verdict: the trial invariants below are not "
                    "checked for it, so carrying one would let a consumer read "
                    "a trial authorization off a plan that never earned one")
            return

        verdict = self.trial_verdict
        if not isinstance(verdict, trial_eligibility.TrialEligibility):
            raise AuthorizationRequiredError(
                "a trial-intent AuthorizedPlan requires the trial-eligibility "
                "preflight's own verdict record; got "
                f"{type(verdict).__name__}")
        if verdict.eligible is not True or verdict.refusals != ():
            raise AuthorizationRequiredError(
                "a trial-intent AuthorizedPlan requires an ELIGIBLE preflight "
                f"verdict; this one refused on {list(verdict.failed_clauses)}")
        if verdict.op_kind != self.op.op_kind:
            raise AuthorizationRequiredError(
                "the preflight verdict is for operation kind "
                f"{verdict.op_kind!r}, but this plan would execute "
                f"{self.op.op_kind!r} -- a verdict earned by one operation kind "
                "never authorizes another")
        if self.dispatch is None:
            raise AuthorizationRequiredError(
                f"operation kind {self.op.op_kind!r} has no registered adapter, "
                "so there is no undo_one to reverse a trial with")
        if self.resolved_target != TRIAL_TARGET:
            raise AuthorizationRequiredError(
                f"a trial resolves to target {self.resolved_target!r}, but a "
                f"trial may only run against {TRIAL_TARGET!r} -- see that "
                "constant's own definition for why the other live-bounded target "
                "is not interchangeable with it")
        if not self.units or tuple(self.units) != tuple(verdict.units):
            raise AuthorizationRequiredError(
                "a trial-intent AuthorizedPlan must carry EXACTLY the units the "
                "preflight blessed; these differ, so the plan about to execute "
                "is not the plan that was checked")
        if not isinstance(self.recovery_capsules, Mapping):
            raise AuthorizationRequiredError(
                "a trial-intent AuthorizedPlan must carry the per-unit recovery "
                "capsules the preflight checked, as a mapping of unit_id -> "
                f"capsule; got {type(self.recovery_capsules).__name__}")

    # -- Reconstruction is not authorization ---------------------------------
    #
    # A guard that only covers `AuthorizedPlan(...)` is not a construction
    # guard. `copy`, `deepcopy` and `pickle` all rebuild an instance WITHOUT
    # running `__post_init__` at all, so each of them silently produced a
    # carrier that had never been validated; and `copy.replace` (on the
    # interpreters that have it) reconstructs through `__replace__`. Every one
    # of those routes refuses here. The `InitVar` token already closes
    # `dataclasses.replace` on every interpreter — a `replace` call cannot
    # supply the token, so it reaches `__post_init__` with the default and is
    # refused there — and `__replace__` closes the newer protocol explicitly
    # rather than relying on a hook that older interpreters do not call.
    #
    # There is a substantive reason beyond guarding, not just a mechanical one:
    # an authorization is not a portable document. It is a decision about ONE
    # operation, taken against the descriptor set, the ledger and the adapter
    # registry as they were AT THAT MOMENT. Reviving one in another process, at
    # another time, or after the registry moved is not something the gate ever
    # authorized — so a copy is refused rather than quietly honoured.

    def __copy__(self) -> "AuthorizedPlan":
        raise AuthorizationRequiredError(
            "an AuthorizedPlan cannot be copied: a copy would be a second "
            "authorization that no gate issued. Authorize the operation again "
            "if it needs to run again.")

    def __deepcopy__(self, memo: Any) -> "AuthorizedPlan":
        raise AuthorizationRequiredError(
            "an AuthorizedPlan cannot be deep-copied: a copy would be a second "
            "authorization that no gate issued. Authorize the operation again "
            "if it needs to run again.")

    def __replace__(self, /, **changes: Any) -> "AuthorizedPlan":
        # Called by `copy.replace` / `dataclasses.replace` on interpreters that
        # implement the replace protocol. On older ones `dataclasses.replace`
        # goes through `__init__` instead and is refused by the InitVar token.
        raise AuthorizationRequiredError(
            "an AuthorizedPlan cannot be rebuilt with altered fields: that is "
            f"exactly the check-then-swap the carrier exists to prevent (asked "
            f"to change {sorted(changes)}). Authorize the operation you actually "
            "intend to run.")

    def __reduce__(self) -> Any:
        raise AuthorizationRequiredError(
            "an AuthorizedPlan cannot be serialized: an authorization is a "
            "decision about one operation against the descriptor set, ledger and "
            "adapter registry as they were at that moment, and reviving it "
            "elsewhere or later would not be that decision.")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # SUBCLASSING is the third route into existence, alongside a direct call
        # and the reconstruction protocols above, and until this guard existed it
        # was open: `class Forged(AuthorizedPlan): def __post_init__(self,
        # issued_by): return` produces instances that never ran a single check
        # here, hold no token, and still pass `isinstance(plan, AuthorizedPlan)`
        # in every consumer. Nothing watching the token could catch it, because
        # such a subclass never names the token.
        #
        # Refused at CLASS-creation time on purpose. Refusing at instance
        # creation would have to reason about what the subclass overrode -- a
        # subclass that merely adds a field still reaches `__post_init__` without
        # a token and is refused there, but one that overrides `__post_init__`
        # never arrives. Removing the route is the fail-closed direction; watching
        # for its symptoms is not.
        #
        # This does not narrow any legitimate use. An adapter, an executor or a
        # journal CONSUMES a plan; none of them has a reason to specialize the
        # carrier, and a consumer that wants to carry extra state alongside an
        # authorization holds the plan as a field rather than inheriting from it.
        raise AuthorizationRequiredError(
            f"AuthorizedPlan cannot be subclassed (attempted by "
            f"{cls.__name__!r}): a subclass that overrides __post_init__ never "
            "runs the construction-token check, so its instances would carry "
            "none of the carrier's invariants while still passing isinstance() "
            "in every consumer of an authorization. Hold a plan as a field "
            "instead of inheriting from it.")


@dataclass(frozen=True)
class Authorization:
    """The outcome of an authorization attempt — the same shape
    `write_gate.GateDecision` uses, for the same reason: the caller either has a
    plan or has a refusal to return, never an ambiguous half state.

    authorized: True iff `plan` is present and the operation may execute.
    plan:       the `AuthorizedPlan`; None when not authorized.
    refusal:    the `Result` to return immediately; None when authorized.
    """

    authorized: bool
    plan: Optional[AuthorizedPlan] = None
    refusal: Optional[Result] = None


def _refuse(reason: str, **extra: Any) -> Authorization:
    detail: Dict[str, Any] = {"reason": reason, "gate": AUTHORIZATION_GATE_NAME}
    detail.update(extra)
    return Authorization(authorized=False,
                         refusal=Result(status="refused", detail=detail))


# ---------------------------------------------------------------------------
# Receipt validation
# ---------------------------------------------------------------------------

def validate_receipt(op: Operation, receipt: Any) -> Optional[str]:
    """Return None if the receipt is valid for this op; return a reason string if not.

    Receipt contract (minimal — the receipt-issuing side must produce conforming receipts):
      {
        "approved_operation_digest": "<sha256-hex>",
        "expires_at": "<ISO-8601 UTC, Z suffix>"
      }

    Lives here, alongside the gate call and the preflight, because validating
    the approval a write rests on IS authorization — and because both executors
    must be bound by exactly one implementation of it.
    """
    if not receipt:
        return "receipt is missing or empty"

    digest = receipt.get("approved_operation_digest")
    if not digest:
        return "receipt is missing approved_operation_digest"

    if digest != op.digest():
        return "receipt digest does not match this operation"

    expires_at_str = receipt.get("expires_at")
    if not expires_at_str:
        return "receipt is missing expires_at"

    try:
        expires_at = datetime.strptime(expires_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return f"receipt expires_at is not a valid ISO-8601 UTC timestamp: {expires_at_str!r}"

    if datetime.now(timezone.utc) >= expires_at:
        return "receipt has expired"

    return None


# ---------------------------------------------------------------------------
# The single authorization implementation
# ---------------------------------------------------------------------------

def authorize_operation(op: Operation, receipt: Any, *,
                        intent: str = EXECUTION_INTENT_ORDINARY,
                        target: Optional[str] = None,
                        descriptor_set: Any = None,
                        cap_ledger: Optional[InvocationLedger] = None,
                        clock: Any = None,
                        recovery_capsules: Any = None,
                        paused_root: Optional[str] = None) -> Authorization:
    """Decide whether `op` may execute, and under what plan. The ONE
    authorization implementation in this package; a second copy of any part of
    it is the defect, not a convenience.

    Order — each step fails safe, and the order is load-bearing:

      1. Validate `intent`. An unrecognized value refuses; it never falls
         through to either branch.
      2. Resolve the registered adapter and PLAN ONCE. `plan()` is contractually
         pure, so planning ahead of the gate touches no surface; the resulting
         unit count is what the gate's unit-aware window is charged. A `dry_run`
         is exempted from planning entirely (it consumes no window and applies
         nothing, and planning malformed params is a crash risk). A `plan()`
         failure becomes a clean refusal, never a propagated exception.
      3. TRIAL INTENT ONLY: refuse unless the target the gate will act on is
         live-bounded, then run the trial-eligibility preflight and refuse
         unless it returns an ELIGIBLE verdict. This happens BEFORE step 4, so
         an ineligible operation never consumes a blast-radius slot. The plan is
         then bound to the units the verdict blessed, never to a re-derived
         plan.
      4. The deterministic pre-write gate (`write_gate.evaluate_write_gate`) —
         unchanged, and the SAME call for both intents. A trial reaches the
         live-enforcement funnel through the gate's existing live-bounded
         branch; nothing here re-implements the cap, the ledger or the recovery
         floor, and nothing here can relax them.
      5. Receipt validation. Required for both intents: a trial is a real live
         write to a bounded subset, and the one relaxation it gets is the
         gate's own (acceptance not required pre-acceptance), never this one.

    Parameters
    ----------
    op / receipt / target / descriptor_set / cap_ledger / clock:
        exactly as `adapters.run_operation` documents them — this function is
        where those arguments were always consumed.
    intent:
        `EXECUTION_INTENT_ORDINARY` (the default, and every pre-existing
        behavior) or `EXECUTION_INTENT_TRIAL`.
    recovery_capsules:
        mapping of unit_id -> recovery capsule, required for the trial intent
        and handed to the preflight as-is. The capsule FORMAT belongs to
        whatever writes the journal, not here; the preflight checks presence,
        string mapping keys and a real JSON round trip, and nothing about shape
        (see `trial_eligibility`'s own clause (d) bound). Ignored for the
        ordinary intent.
    paused_root:
        threaded straight into the gate's paused-mechanisms check, and for the
        same reason the gate takes it: a caller (a test, above all) that must
        not depend on ambient project state can pass its own marker directory.
        None — the default and what every production caller passes — means the
        gate uses its own ambient default, unchanged.

    Returns an `Authorization`. NEVER raises for a refusable input: a malformed
    intent, an unplannable operation, an ineligible trial, a closed gate and a
    bad receipt all resolve to a refusal `Result`, because a traceback out of an
    authorization step is indistinguishable to its caller from a step that
    failed to run.

    A BROKEN preflight is the deliberate exception to that, and the distinction
    matters: an exception raised BY `check_trial_eligibility` itself is not a
    refusable input, it is the gate failing to run. It is left to propagate
    rather than caught, because catching it is how a gate silently stops gating —
    and a loud failure before anything has been written is strictly safer than a
    refusal an operator might read as an ordinary "no" and try to work around.
    This does not weaken `run_operation`'s "always returns a Result" contract:
    that path uses the ordinary intent, which never reaches the preflight.
    """
    if intent not in EXECUTION_INTENTS:
        return _refuse(
            f"operation refused: unrecognized execution intent {intent!r} -- "
            f"must be one of {list(EXECUTION_INTENTS)}. An unrecognized intent "
            "is never treated as either one; nothing is authorized by default.",
            op_kind=op.op_kind)

    # (2) Resolve the adapter and plan ONCE, ahead of the gate. plan() is
    # contractually PURE (no reads/writes), so this touches no surface; it
    # exists to compute the unit count the gate's window is charged, and — for a
    # trial — the units the preflight evaluates. dry_run never plans (it
    # consumes no window, applies nothing, and planning malformed params is a
    # crash risk); every other path converts a plan() failure into a clean
    # refusal rather than propagating it.
    dispatch = get_dispatch(op.op_kind)
    planned_units: Optional[list] = None
    n_units = 1
    if dispatch is not None and target != "dry_run":
        try:
            planned_units = dispatch.plan(dispatch.instance, op.params)
            # plan() is contractually a List[EffectUnit], but nothing upstream
            # enforces that at the type level. A non-list (e.g. a string, which
            # is itself len()-able and iterable and would otherwise be misread
            # as a sequence of one-character "units") must become a clean
            # refusal here, not a TypeError later or a silent corruption.
            if not isinstance(planned_units, list):
                raise TypeError(
                    "plan() must return a list of EffectUnit; got "
                    f"{type(planned_units).__name__!r}"
                )
        except Exception as exc:
            return Authorization(
                authorized=False,
                refusal=Result(
                    status="refused",
                    detail={
                        "reason": (
                            "operation refused: could not plan effect units from the "
                            f"operation params for op_kind {op.op_kind!r} — {exc!r}"
                        ),
                    },
                ))
        n_units = len(planned_units)

    # The target the GATE will act on — never the requested string. An operation
    # on the copy-surface convention resolves to 'copy' whatever its caller
    # asked for, and would take the gate's isolated branch (no cap, no ledger):
    # a trial check made on the request string would believe a live-bounded
    # funnel had run when none did. Resolved through the gate's own public
    # accessor so there is one implementation of target resolution, not two.
    resolved = resolve_effective_target(op, target)

    # (3) TRIAL INTENT ONLY — and unconditional within it. There is no flag,
    # argument or early exit that reaches step 4 with the trial intent and an
    # unchecked plan.
    verdict = None
    if intent == EXECUTION_INTENT_TRIAL:
        if resolved != TRIAL_TARGET:
            # Refused immediately rather than reported alongside the preflight's
            # own grounds: the target is chosen by the kernel-driven trial
            # protocol, not by an operator, so a wrong one is a caller error to
            # correct rather than an eligibility fact about the operation.
            other_live_bounded = sorted(LIVE_BOUNDED_TEST_TARGETS - {TRIAL_TARGET})
            return _refuse(
                "trial refused: a trial performs a real write to a bounded "
                "subset of the live resource and then REVERTS it, so its target "
                f"must be exactly {TRIAL_TARGET!r}; this operation resolves to "
                f"{resolved!r}. A dry run performs no write, so nothing could be "
                "observed as restored; a copy surface is not the operator's live "
                "record; an affirmative live target requires the acceptance a "
                "trial exists to earn; an absent target never defaults to "
                f"anything; and {other_live_bounded} declares a bounded live "
                "sample that PERSISTS, so running a reverting trial under that "
                "declaration would do something other than what the declaration "
                "describes.",
                op_kind=op.op_kind, requested_target=target,
                resolved_target=resolved, trial_target=TRIAL_TARGET)

        verdict = trial_eligibility.check_trial_eligibility(
            op.op_kind, planned_units or (), recovery_capsules)
        if not verdict.eligible:
            return _refuse(
                f"trial refused: operation kind {op.op_kind!r} is not eligible "
                "for a trial, so nothing was written and no blast-radius slot "
                f"was consumed.\n{verdict.reason_text()}",
                op_kind=op.op_kind,
                trial_ineligible_clauses=list(verdict.failed_clauses))
        # Bind to the units the preflight blessed, NOT to a re-derived plan: a
        # second plan() call could return something the gate never saw.
        planned_units = list(verdict.units)
        n_units = len(planned_units)

    # (4) The deterministic pre-write gate — the SAME call for both intents. A
    # trial reaches the shared live-enforcement funnel (recovery floor +
    # mandatory blast-radius cap + invocation ledger + irreversibility audit)
    # through the gate's EXISTING live-bounded branch. Nothing here duplicates
    # or weakens any of it.
    decision = evaluate_write_gate(
        op, target=target, descriptor_set=descriptor_set,
        cap_ledger=cap_ledger, clock=clock, n_units=n_units,
        paused_root=paused_root)
    if not decision.permitted:
        return Authorization(authorized=False, refusal=decision.refusal)

    # (5) Receipt validation — refuse before anything touches the surface.
    reason = validate_receipt(op, receipt)
    if reason:
        return Authorization(
            authorized=False,
            refusal=Result(status="refused", detail={"reason": reason}))

    return Authorization(
        authorized=True,
        plan=AuthorizedPlan(
            op=op,
            intent=intent,
            target=target,
            resolved_target=resolved,
            dispatch=dispatch,
            units=None if planned_units is None else tuple(planned_units),
            gate_audit=decision.audit,
            trial_verdict=verdict,
            recovery_capsules=(recovery_capsules
                               if intent == EXECUTION_INTENT_TRIAL else None),
            issued_by=_ISSUED_BY_AUTHORIZE,
        ))
