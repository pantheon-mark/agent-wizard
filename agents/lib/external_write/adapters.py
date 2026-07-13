"""Named-operation adapters for external writes.

Each adapter wraps one named operation kind (e.g. set_status, complete_tasks).
All writes go through run_operation, which enforces:

  1. Receipt validation — must be present, unexpired, and digest-match the op.
     (NEVER write without a valid, matching receipt.)
  2. Write via the surface's own validating path (no validation bypass).
  3. Native-API fail-fast value validity — attempt the write; if the surface
     rejects the value, catch the rejection, parse the allowed set from the
     surface's error, and return needs_operator_choice.  The adapter does NOT
     pre-fetch vocabulary schemas before the write (that is an enhancement for
     surfaces where machine-readable validation rules are cheap to fetch; it is
     not the default). For surfaces where dataValidation is not readable ahead
     of time, the native-reject path is the sole gate — and it fires reliably.
  4. Read-back verification on success, then optional mode-bounded post-write verification (Clause A).

Value-validity strategy (native-API fail-fast):
  - DEFAULT: attempt write -> catch surface ValueError / rejection -> parse
    allowed set from the error message -> return needs_operator_choice.
  - ENHANCEMENT (not implemented here): for surfaces like Google Sheets where
    the dataValidation rules ARE machine-readable via a field-masked
    spreadsheets.get call, a pre-write read-live pass can be layered on top
    to give a cleaner operator prompt before a round-trip.  That is a future
    adapter variant; this module establishes the default contract.
  - FAIL-CLOSED: if the value is controlled but the allowed set cannot be
    determined from the surface error, return needs_operator_choice with
    allowed=None so the caller is forced to ask the operator — never silently
    pass a write through an ambiguous controlled field.

Stdlib only — no third-party dependencies.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

from external_write.operations import Operation, Result
from external_write.verifiers import validate_postwrite_verification
from external_write.write_gate import evaluate_write_gate, InvocationLedger, resolve_effective_cap
from external_write.adapter_registry import get_dispatch
from external_write.evidence import AdapterEvidence
from external_write.contracts import SourceLineage
from external_write.read_facade import build_read_facade, ReadFacadeEligibilityError


# ---------------------------------------------------------------------------
# Receipt validation
# ---------------------------------------------------------------------------

def _validate_receipt(op: Operation, receipt: Any) -> Optional[str]:
    """Return None if the receipt is valid for this op; return a reason string if not.

    Receipt contract (minimal — the receipt-issuing side must produce conforming receipts):
      {
        "approved_operation_digest": "<sha256-hex>",
        "expires_at": "<ISO-8601 UTC, Z suffix>"
      }
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
# Value-validity: parse allowed set from a surface rejection error
# ---------------------------------------------------------------------------

# Patterns that surfaces use to embed an allowed-set in rejection messages.
# Examples:
#   "Invalid value 'X'. Allowed: ('Open', 'In progress', 'Waiting', 'Complete')"
#   "Value 'X' not accepted. Allowed: ('Approved', 'Rejected', 'Pending')"
#   "allowed values are: foo, bar, baz"
_ALLOWED_TUPLE_RE = re.compile(r"Allowed:\s*\(([^)]+)\)")
_ALLOWED_LIST_RE = re.compile(r"[Aa]llowed(?:\s+values)?(?:\s+are)?[:\s]+([^.;]+)")


def _parse_allowed_from_error(message: str) -> Optional[list]:
    """Attempt to parse an allowed-values list from a surface rejection message.

    Returns a list of strings if parsed, or None if the message does not contain
    an identifiable allowed-values set.
    """
    # Try tuple-style: Allowed: ('A', 'B', 'C')
    m = _ALLOWED_TUPLE_RE.search(message)
    if m:
        raw = m.group(1)
        # Split on comma, strip quotes and whitespace.
        items = [s.strip().strip("'\"") for s in raw.split(",")]
        return [i for i in items if i]

    # Try list-style: Allowed: foo, bar, baz
    m = _ALLOWED_LIST_RE.search(message)
    if m:
        raw = m.group(1)
        items = [s.strip().strip("'\"") for s in raw.split(",")]
        return [i for i in items if i]

    return None


# ---------------------------------------------------------------------------
# Registered-adapter action path
# ---------------------------------------------------------------------------

def _verify_applied_units(op: Operation, dispatch: Any, units: list,
                          read_only_client: Any) -> dict:
    """Post-apply, run-time verification (Task 3, A2 run-time — v0.12.0
    Slice 1; closes F-41: `_run_adapter_operation` used to return
    status="written" unconditionally, without ever calling `verify_one` —
    the estate dogfood's "verified" claim came from the substrate's own
    manifest, never a real-surface check, and 118-vs-120 surfaced only
    because the operator counted by hand).

    For EACH applied unit, this OBSERVES the real external surface through a
    READ-ONLY FACADE (`read_facade.build_read_facade`) built from a
    read-only-scoped client — NEVER the write-capable client `apply_one`
    just used (credential isolation: see `adapter_registry.AdapterDispatch`'s
    `provision_read_only_client` docstring and `read_facade.py`'s module
    docstring) — and evaluates the adapter's OWN captured
    `verify_apply_landed` predicate over what was actually observed. A
    `verified` status is EARNED from that observation; anything the kernel
    could not itself confirm reports the HONEST `applied_not_verified`,
    NEVER `verified`:

      * the op_kind's registered adapter declares no `verify_apply_landed`
        predicate;
      * no read-only client is available (neither self-provisioned via
        `build_read_only_client` nor supplied by the caller via
        `run_operation`'s `read_only_client` argument);
      * the op_kind is ineligible for the read-only-facade model (no
        declared `read_only_scope` / no registered `ReadFacade` subclass);
      * `verify_one` (the adapter's read-only OBSERVER) raises, or does not
        return an observable poststate mapping; or
      * the predicate itself evaluates the observed evidence as NOT landed.

    Returns a dict — recorded into `Result.detail["verification"]` by the
    caller, never consumed here (the RunEnvelope tranche wiring that
    CONSUMES this is Task 4, out of this task's scope):
    {"per_unit": {unit_id: {"status": "verified"|"applied_not_verified",
    "reason": <str, present only when not verified>}}, "verified_count": N,
    "applied_not_verified_count": M} — a legible, reconciled aggregate count
    per EffectUnit (the apply/verify granularity the adapter itself chose in
    `plan()`; a surface quirk like Gmail thread-vs-message grouping is the
    adapter's own poststate shape to reconcile before returning it from
    `verify_one`, not something this generic kernel function assumes).
    """
    per_unit: Dict[str, dict] = {}

    if dispatch.verify_apply_landed is None:
        reason = (
            f"operation kind {op.op_kind!r} has a registered adapter but "
            "declares no verify_apply_landed evidence predicate -- a "
            "'verified' claim cannot be earned without one"
        )
        for unit in units:
            per_unit[unit.unit_id] = {"status": "applied_not_verified", "reason": reason}
        return {"per_unit": per_unit, "verified_count": 0,
                "applied_not_verified_count": len(units)}

    facade = None
    facade_error: Optional[str] = None
    # Resolve the read-only client — self-provisioned by the adapter if it
    # defines build_read_only_client, else the caller-supplied fallback.
    # Fail-SAFE: the apply loop already ran; a provisioning failure here must
    # NEVER propagate (it would turn a successful write into an uncaught
    # exception), so any exception degrades to applied_not_verified, honest.
    _provision_ro = dispatch.provision_read_only_client
    effective_read_only_client = None
    try:
        effective_read_only_client = (
            _provision_ro(dispatch.instance, op) if _provision_ro is not None
            else read_only_client
        )
    except Exception as exc:
        facade_error = (
            f"could not obtain a read-only client for {op.op_kind!r} "
            f"(build_read_only_client raised): {exc!r}"
        )

    if facade_error is not None:
        pass
    elif effective_read_only_client is None:
        facade_error = (
            f"no read-only client is available for {op.op_kind!r} -- the "
            "adapter did not self-provision one (build_read_only_client) and "
            "the caller did not supply run_operation's read_only_client "
            "argument -- the real surface cannot be queried"
        )
    else:
        try:
            facade = build_read_facade(op.op_kind, effective_read_only_client)
        except ReadFacadeEligibilityError as exc:
            facade_error = (
                f"operation kind {op.op_kind!r} is not eligible for the "
                f"read-only-facade credential-isolation model: {exc}"
            )
        except Exception as exc:
            facade_error = (
                f"could not build a read-only facade for {op.op_kind!r}: {exc!r}"
            )

    verified_count = 0
    unverified_count = 0
    for unit in units:
        if facade is None:
            per_unit[unit.unit_id] = {"status": "applied_not_verified", "reason": facade_error}
            unverified_count += 1
            continue

        try:
            poststate = dispatch.verify_one(dispatch.instance, facade, unit)
        except Exception as exc:
            per_unit[unit.unit_id] = {
                "status": "applied_not_verified",
                "reason": f"verify_one raised while observing the real surface: {exc!r}",
            }
            unverified_count += 1
            continue

        if not isinstance(poststate, dict):
            per_unit[unit.unit_id] = {
                "status": "applied_not_verified",
                "reason": "verify_one did not return an observable poststate mapping",
            }
            unverified_count += 1
            continue

        evidence = AdapterEvidence(
            op_kind=op.op_kind,
            unit_id=unit.unit_id,
            poststate=poststate,
            prestate=None,
            source_lineage=SourceLineage(
                pre_write_sources=(),
                post_write_sources=("live_read_only_facade_observation",),
                forbidden_verification_inputs=(),
            ),
        )
        try:
            landed = bool(dispatch.verify_apply_landed(dispatch.instance, evidence))
        except Exception as exc:
            per_unit[unit.unit_id] = {
                "status": "applied_not_verified",
                "reason": f"verify_apply_landed raised evaluating observed evidence: {exc!r}",
            }
            unverified_count += 1
            continue

        if landed:
            per_unit[unit.unit_id] = {"status": "verified"}
            verified_count += 1
        else:
            per_unit[unit.unit_id] = {
                "status": "applied_not_verified",
                "reason": (
                    "observed evidence from the read-only facade does not "
                    "confirm the apply landed"
                ),
            }
            unverified_count += 1

    return {
        "per_unit": per_unit,
        "verified_count": verified_count,
        "applied_not_verified_count": unverified_count,
    }


def _run_adapter_operation(op: Operation, raw_client: Any, dispatch: Any,
                           descriptor_set: Any, gate_audit: Optional[dict],
                           units: list, read_only_client: Any = None) -> Result:
    """Cap-check, then apply — the registered-adapter counterpart to the
    field-write Steps 2-4 in run_operation.

    THE ORDERING GUARANTEE: `units` is `dispatch.plan(dispatch.instance,
    op.params)`'s result, already computed ONCE by run_operation (Step 0
    hoists that pure planning call above the gate to compute the window's
    `n_units`; see run_operation's docstring). It is counted and compared
    against the blast-radius cap BEFORE `dispatch.apply_one` is called even
    once. A plan whose unit count exceeds the cap is refused in full — zero
    units are applied, not "cap-many, then stop." This function does NOT call
    plan() again — it is contractually pure (no writes, no reads — see the
    Adapter protocol docstring), so a second call would be safe but wasteful;
    the caller already has the one true planned list and passes it straight
    through.

    Captured dispatch, not the mutable instance (a defense-in-depth
    fix): `dispatch` is an `adapter_registry.
    AdapterDispatch` — `plan`/`apply_one`/`undo_one`/`verify_one` (and
    `provision_write_client`, if the class defines `build_write_client`) were
    captured OFF `type(adapter)` at `register_adapter` time, not read off the
    instance here. Every call below therefore goes through the CLASS's
    function object, with `dispatch.instance` passed explicitly as `self` —
    reassigning `dispatch.instance.apply_one` (or `.build_write_client`) as an
    ordinary instance attribute, however a capability obtained a reference to
    that instance, cannot change what this function calls: `dispatch.apply_one`
    is a plain reference to the function that lived on the class at
    registration time, immune to any later instance-level shadowing. See
    `adapter_registry.AdapterDispatch`'s docstring for the full threat model
    this closes.

    Credential isolation (the keystone): the write-capable raw
    client is resolved INTERNALLY, here, keyed by the registered adapter's
    CAPTURED provisioner — NOT from any caller-supplied argument and NOT by
    re-reading `instance.build_write_client` (which a capability could have
    reassigned). If the adapter self-provisions its own write client (its
    class defines `build_write_client(self, op) -> raw_write_client`, as the
    emitted ADAPTER_PROFILE-zone adapters do), THIS function — the adapter
    EXECUTION path, reached only once dispatch is already committed — calls
    the captured `dispatch.provision_write_client(dispatch.instance, op)` to
    obtain it, and uses it immediately for `dispatch.apply_one`, never storing
    it or handing it back out. Capability/proposal-side code can no longer
    even NAME a credential provider, let alone pass one in (enforced
    deterministically by scan.py's credential_provider_reference rule, not by
    a comment convention).

    Backward compatibility: an adapter whose class does NOT self-provision (no
    `build_write_client` method — e.g. the Gmail reference adapter, or any
    adapter whose write client is handed in by its trusted caller) has
    `dispatch.provision_write_client is None`, so this falls back to
    `raw_client` (run_operation's `client` argument) used as-is — the
    unchanged, original behavior. The six seeded field op_kinds have no
    registered adapter at all and never reach this path (see
    adapter_registry.py's scope note; test_external_write_replay_conformance.py
    carries their byte-identical guarantee).

    Run-time verification (Task 3, A2 run-time — v0.12.0 Slice 1; closes
    F-41): AFTER the apply loop below, `_verify_applied_units` observes the
    REAL surface for every applied unit through a READ-ONLY facade — built
    from the adapter's self-provisioned read-only client
    (`dispatch.provision_read_only_client`) if present, else from
    `read_only_client` (this function's own new parameter, mirroring
    `raw_client`'s write-side caller-supplied fallback) — and records an
    honest per-unit `verified`/`applied_not_verified` status into
    `Result.detail["verification"]`. This NEVER uses `effective_raw_client`
    (the write-capable client resolved above) for the read: the two
    resolutions are entirely independent, exactly like write-side credential
    isolation is independent of any caller-supplied argument.
    """
    cap = resolve_effective_cap(op, descriptor_set)
    if cap is not None and len(units) > cap:
        return Result(
            status="refused",
            detail={
                "reason": (
                    f"operation refused: planned {len(units)} effect unit(s) exceeds "
                    f"the blast-radius cap of {cap} for op_kind {op.op_kind!r} — "
                    "refused before any write was attempted."
                ),
                "planned_units": len(units),
                "blast_radius_cap": cap,
            },
        )

    # Already captured off the class at registration time (adapter_registry.
    # AdapterDispatch) — never re-read from the (possibly reassigned) instance.
    _provision = dispatch.provision_write_client
    effective_raw_client = (
        _provision(dispatch.instance, op) if _provision is not None
        else raw_client
    )

    for unit in units:
        dispatch.apply_one(dispatch.instance, effective_raw_client, unit)

    # Run-time verification (Task 3, A2 run-time — v0.12.0 Slice 1; closes
    # F-41): NEVER uses `effective_raw_client` above — see this function's
    # docstring and `_verify_applied_units`'s own docstring for the
    # credential-isolation rationale.
    verification = _verify_applied_units(op, dispatch, units, read_only_client)

    detail: dict = dict(gate_audit) if gate_audit else {}
    detail["units_applied"] = len(units)
    detail["verification"] = verification
    return Result(status="written", detail=detail)


# ---------------------------------------------------------------------------
# Core dispatch
# ---------------------------------------------------------------------------

def run_operation(op: Operation, receipt: Any, client: Any,
                  postwrite_verification: Any = None, *,
                  target: Optional[str] = None,
                  descriptor_set: Any = None,
                  cap_ledger: Optional[InvocationLedger] = None,
                  clock: Any = None,
                  read_only_client: Any = None) -> Result:
    """Run a named external-write operation with receipt validation and fail-fast
    value-validity enforcement.

    Parameters
    ----------
    op:      The Operation to execute.
    receipt: A dict conforming to the receipt contract (see operations.py).
             Must contain approved_operation_digest + expires_at.
    client:  A surface client stub or real client.  Must implement:
               client.write(object_id, field, value) -> None  (raises ValueError on bad value)
               client.read(object_id, field) -> Any
    read_only_client: (keyword-only, Task 3 — A2 run-time, v0.12.0 Slice 1) a
             READ-ONLY-scoped client for the registered-adapter path's
             post-apply run-time verification (`_verify_applied_units`) —
             the read-side mirror of `client`: used ONLY as a fallback when
             the op_kind's registered adapter does NOT self-provision one
             (no `build_read_only_client` on its class); ignored entirely by
             the legacy field-write path and by any op_kind with no
             registered adapter. Absent/None (the default) means run-time
             verification cannot query the real surface: every applied unit
             is reported `applied_not_verified` (honest fail-safe), never
             `verified` — this is NEVER the same object as `client`/the
             resolved write-capable client (credential isolation; see
             `adapter_registry.AdapterDispatch.provision_read_only_client`
             and `read_facade.py`).
    target:  (keyword-only) the machine-readable target signal for a gated (high-risk)
             op: LIVE_TARGET ('live') or a declared test target ('copy'/'bounded_sample'/
             'dry_run'/'native_undo'). An op on the copy-surface convention is an implicit copy
             target. A declared test target is honored ONLY when the op targets a recognized
             test/copy surface (is_test_surface); a test-target claim on a live surface is
             refused (I1). For a gated op an ABSENT target fails safe to refuse. Ignored for the
             ungated seeded status ops (read_only_local / reversible_external): the gate is a
             no-op for them and their behavior is byte-identical to the ungated path.
    descriptor_set: the accepted-descriptor set (contracts.py's descriptor-registry shape). None => loaded fail-safe
             from disk (absent => nothing accepted => live refused).
    cap_ledger: the InvocationLedger enforcing the deterministic blast-radius cap on
             live irreversible ops. Absent on a live irreversible op => fail-safe refuse.
             The SAME ledger's window is bounded in UNITS across its lifetime (not
             invocation count) — see n_units below.
    clock:   a no-arg callable returning a UTC datetime; every date this code writes
             comes from it. Defaults to the system clock; injected only for deterministic tests.

    n_units / plan-once: when op.op_kind has a
             registered adapter AND target is not 'dry_run', this function resolves its CAPTURED
             dispatch (adapter_registry.get_dispatch — see AdapterDispatch's docstring for why
             this is captured off the class rather than the mutable instance) and
             calls `dispatch.plan(dispatch.instance, op.params)` ONCE, before Step 0's gate —
             plan() is contractually PURE
             (no reads/writes; see the Adapter protocol docstring), so hoisting it above the gate
             does not touch the surface and does not weaken "the gate refuses before any write."
             The resulting `len(units)` is passed into evaluate_write_gate as n_units, so the
             shared InvocationLedger's aggregate window is consumed in UNITS, not in one slot per
             invocation regardless of fan-out (the fan-out gap this closes — see write_gate.py's
             _enforce_live_funnel). The SAME already-planned `units` list is then passed
             straight into _run_adapter_operation, which does NOT call plan() again (avoiding a
             redundant, if harmless, second pure call). An op_kind with no registered adapter
             plans nothing and uses n_units=1, exactly like the legacy field-write path.
             `dry_run` is exempted from the hoist entirely (plan-hoist totality):
             dry_run never consumes the aggregate window (it short-circuits at Step 1.5, before
             Step 1.75's adapter dispatch, and never applies a unit), so it needs no `n_units`
             and no planned `units` — n_units stays at the default of 1 (unused for this path)
             and _planned_units stays None. Planning for dry_run would be wasted work and, worse,
             a crash risk: plan() is pure but NOT total — the seeded Gmail adapters index
             directly into params (e.g. `m["message_id"]`) and raise KeyError on malformed
             input, which is exactly the shape a dry_run preview of a would-be-refused op can
             have. For the non-dry_run registered-adapter path, the hoisted plan() call is also
             guarded: any exception it raises is caught and turned into a clean refused Result
             (never propagated), so a malformed-params op is a fail-safe refusal everywhere,
             never an uncaught exception breaking run_operation's "always returns a Result"
             contract.

    Credential isolation: run_operation takes NO caller-supplied
             write-credential provider. When op.op_kind has a registered adapter whose CLASS
             self-provisions its own write client, the write-capable raw client is resolved
             INTERNALLY inside the adapter execution path (see _run_adapter_operation:
             `dispatch.provision_write_client(dispatch.instance, op)` — the CAPTURED class
             method, immune to an instance-level `build_write_client` reassignment), keyed by
             the registered adapter — never by a caller of run_operation and never exposed to
             capability/proposal-side code. An adapter whose class does not self-provision falls
             back to `client` as the raw write client (unchanged, backward-compatible). The
             legacy field-write path uses `client` directly.

    Returns
    -------
    Result with status in {'written', 'needs_operator_choice', 'refused'}.
    """

    # Step -1: resolve the adapter and plan ONCE, before the gate. plan() is
    # contractually PURE (no reads/writes), so calling it here — ahead of Step 0 — does not
    # touch the surface; it exists solely to compute n_units for the gate's unit-aware window
    # (write_gate._enforce_live_funnel). None planned (no registered adapter) => n_units=1,
    # matching the legacy field-write path exactly.
    #
    # Disclosed: this hoist runs plan() BEFORE the write gate, so plan()'s
    # purity is load-bearing — a plan() that performed a write would execute it before the
    # gate ever ran. That purity is an adapter-author invariant verified by operator review
    # of the trusted adapter module, NOT machine-enforced by scan.py (ADAPTER_PROFILE modules,
    # where every plan() implementation lives, are exempt from every scanner check — see
    # scan.py's "Bounds NOT covered" docstring section for the full disclosure).
    #
    # Two fail-safe exemptions/guards address a regression found in review of the
    # plan-hoist change — plan() is PURE but NOT TOTAL: seeded adapters index directly
    # into params, e.g. `m["message_id"]`, and raise on malformed input):
    #   1. `dry_run` never plans at all. dry_run consumes no window (it short-circuits at Step
    #      1.5, below, before Step 1.75's adapter dispatch even runs) and needs no `units`, so
    #      skipping the hoisted plan() here preserves dry_run's no-crash, no-op preview guarantee
    #      even for malformed params. n_units stays at the unused default of 1 for this path.
    #   2. For every other path, a plan() failure is caught and converted into a clean refused
    #      Result rather than propagated — so a malformed-params op is a fail-safe refusal
    #      everywhere (an improvement over the earlier behavior, where such an op crashed later, inside
    #      _run_adapter_operation's now-removed second plan() call), never an uncaught exception
    #      breaking run_operation's "always returns a Result" contract.
    dispatch = get_dispatch(op.op_kind)
    _planned_units: Optional[list] = None
    n_units = 1
    if dispatch is not None and target != "dry_run":
        try:
            _planned_units = dispatch.plan(dispatch.instance, op.params)
            # plan() is contractually a List[EffectUnit],
            # but nothing upstream enforces that at the type level. Validate the
            # shape INSIDE this guard — a plan() returning None (or any other
            # non-list, e.g. a string, which is itself len()-able and iterable
            # and would otherwise be silently misread as a sequence of
            # one-character "units") must become a clean refusal here, not a
            # TypeError/AttributeError raised later at `len(_planned_units)` or
            # a silent-corruption bug from iterating the wrong thing.
            if not isinstance(_planned_units, list):
                raise TypeError(
                    "plan() must return a list of EffectUnit; got "
                    f"{type(_planned_units).__name__!r}"
                )
        except Exception as exc:
            return Result(
                status="refused",
                detail={
                    "reason": (
                        "operation refused: could not plan effect units from the "
                        f"operation params for op_kind {op.op_kind!r} — {exc!r}"
                    ),
                },
            )
        n_units = len(_planned_units)

    # Step 0: the deterministic pre-write gate — the single chokepoint's fail-safe heart.
    # Runs BEFORE receipt validation and before anything touches the surface. A no-op for the
    # ungated seeded status ops; refuses fail-safe for every missing input on a gated op.
    decision = evaluate_write_gate(
        op, target=target, descriptor_set=descriptor_set,
        cap_ledger=cap_ledger, clock=clock, n_units=n_units)
    if not decision.permitted:
        return decision.refusal
    _gate_audit = decision.audit

    # Step 1: receipt validation — refuse before touching the surface.
    reason = _validate_receipt(op, receipt)
    if reason:
        return Result(status="refused", detail={"reason": reason})

    # Step 1.5: dry_run no-mutation guarantee. The gate (Step 0) permits `dry_run`
    # UNCONDITIONALLY precisely because THIS adapter guarantees it never reaches
    # client.write (the sole external-write site, below) — nor the client.read read-back,
    # nor post-write verification. A dry_run is a preview of whether the REAL write would
    # be permitted: the gate and receipt validation above still run in full, in order, so
    # a dry_run of a would-be-refused op still reports refused (fail-safe overriding).
    # Once both pass, report the write that WOULD happen without ever performing it.
    # Reuses status="written" (see the adapters and write_gate test modules, which
    # already assert status=="written" for dry_run) with an unambiguous dry_run=True
    # detail marker — no consumer of Result.status distinguishes a real write from this.
    if target == "dry_run":
        detail: dict = {"dry_run": True, "simulated_value": op.new_value}
        return Result(status="written", detail=detail)

    # Step 1.75: registered-adapter action path. When op.op_kind has a
    # registered Adapter (adapter_registry.py), dispatch to it INSTEAD of the
    # field-write path below: plan the effect units, refuse before any write if the
    # planned count exceeds the blast-radius cap (a single Operation
    # carrying many targets can no longer slip past the cap by counting as one
    # invocation), then apply each unit in turn. An op_kind with NO registered
    # adapter falls straight through to the unchanged field-write path. A prior
    # evaluation considered migrating the six seeded field op_kinds onto this registry and
    # decided against it (see adapter_registry.py's module docstring for the
    # full reasoning) — they stay on this fallback path indefinitely; the
    # backward-compatibility guarantee is proven by
    # test_external_write_replay_conformance.py instead.
    #
    # `dispatch` and `_planned_units` were already resolved/planned once above (Step -1),
    # ahead of the gate, so the cap-check + apply step here reuses that SAME planned list
    # rather than calling plan() a second time.
    if dispatch is not None:
        return _run_adapter_operation(op, client, dispatch, descriptor_set, _gate_audit,
                                      _planned_units, read_only_client)

    # Step 2: attempt write via the surface's validating path.
    try:
        client.write(op.object_id, op.field, op.new_value)
    except ValueError as exc:
        # Surface rejected the value.  Parse the allowed set from the error.
        allowed = _parse_allowed_from_error(str(exc))
        return Result(
            status="needs_operator_choice",
            detail={
                "reason": str(exc),
                "allowed": allowed,
            },
        )

    # Step 3: read-back verification.
    written_value = client.read(op.object_id, op.field)
    if written_value != op.new_value:
        # Read-back mismatch — treat as a soft failure; caller must re-verify.
        return Result(
            status="refused",
            detail={
                "reason": "read-back verification failed",
                "written": op.new_value,
                "read_back": written_value,
            },
        )

    # Step 4: optional post-write verification (Clause A — Authority).
    # When a caller supplies a postwrite-verification-v1 record, the success claim
    # is bounded by the record's mode and rejected on declared-dependency overlap.
    # Back-compat: no record -> the read-back-confirmed write is reported as before.
    # The gate's audit record (e.g. the clock-stamped irreversibility acknowledgement) is
    # merged into the success detail; it is None for the ungated status ops, so their written
    # Result stays byte-identical (detail=None) to the ungated path.
    if postwrite_verification is None:
        return Result(status="written",
                      detail=dict(_gate_audit) if _gate_audit else None)

    vresult = validate_postwrite_verification(op, postwrite_verification)
    if not vresult.ok:
        return Result(status="refused", detail={"reason": vresult.reason})

    detail: dict = {
        "verification": {
            "claim_strength": vresult.claim_strength.value,
            "verifier_id": postwrite_verification["verifier_id"],
        }
    }
    if _gate_audit:
        detail.update(_gate_audit)
    return Result(status="written", detail=detail)
