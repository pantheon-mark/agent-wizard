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
from typing import Any, Optional, Sequence

from external_write.operations import Operation, Result
from external_write.verifiers import validate_postwrite_verification
from external_write.write_gate import evaluate_write_gate, InvocationLedger, resolve_effective_cap
from external_write.adapter_registry import get_adapter


# ---------------------------------------------------------------------------
# Receipt validation
# ---------------------------------------------------------------------------

def _validate_receipt(op: Operation, receipt: Any) -> Optional[str]:
    """Return None if the receipt is valid for this op; return a reason string if not.

    Receipt contract (minimal — Task 2 must produce conforming receipts):
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
# T2: registered-adapter action path
# ---------------------------------------------------------------------------

def _run_adapter_operation(op: Operation, raw_client: Any, adapter: Any,
                           descriptor_set: Any, gate_audit: Optional[dict]) -> Result:
    """Plan, cap-check, then apply — the registered-adapter counterpart to the
    field-write Steps 2-4 in run_operation.

    THE ORDERING GUARANTEE (F-31): `adapter.plan(...)` is called first and must be
    pure (no writes, no reads — see the Adapter protocol docstring). Its result is
    counted and compared against the blast-radius cap BEFORE `adapter.apply_one` is
    called even once. A plan whose unit count exceeds the cap is refused in full —
    zero units are applied, not "cap-many, then stop."

    Credential isolation (BL-1 / F-33 — the keystone): the write-capable raw
    client is resolved INTERNALLY, here, keyed by the registered adapter — NOT
    from any caller-supplied argument. If the adapter self-provisions its own
    write client (it defines `build_write_client(op) -> raw_write_client`, as
    the emitted ADAPTER_PROFILE-zone adapters do), THIS function — the adapter
    EXECUTION path, reached only once dispatch is already committed — calls
    `adapter.build_write_client(op)` to obtain it, and uses it immediately for
    `adapter.apply_one`, never storing it or handing it back out. Capability/
    proposal-side code can no longer even NAME a credential provider, let alone
    pass one in (enforced deterministically by scan.py's
    credential_provider_reference rule, not by a comment convention).

    Backward compatibility: an adapter that does NOT self-provision (no
    `build_write_client` method — e.g. the Gmail reference adapter, or any
    adapter whose write client is handed in by its trusted caller) falls back
    to `raw_client` (run_operation's `client` argument) used as-is — the
    unchanged, pre-BL-1 behavior. The six seeded field op_kinds have no
    registered adapter at all and never reach this path (see
    adapter_registry.py's scope note; test_external_write_replay_conformance.py
    carries their byte-identical guarantee).
    """
    units = adapter.plan(op.params)
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

    build_write_client = getattr(adapter, "build_write_client", None)
    effective_raw_client = (
        build_write_client(op) if callable(build_write_client)
        else raw_client
    )

    for unit in units:
        adapter.apply_one(effective_raw_client, unit)

    detail: dict = dict(gate_audit) if gate_audit else {}
    detail["units_applied"] = len(units)
    return Result(status="written", detail=detail)


# ---------------------------------------------------------------------------
# Core dispatch
# ---------------------------------------------------------------------------

def run_operation(op: Operation, receipt: Any, client: Any,
                  postwrite_verification: Any = None, *,
                  target: Optional[str] = None,
                  descriptor_set: Any = None,
                  cap_ledger: Optional[InvocationLedger] = None,
                  clock: Any = None) -> Result:
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
    target:  (B1-4, keyword-only) the machine-readable target signal for a gated (high-risk)
             op: LIVE_TARGET ('live') or a declared test target ('copy'/'bounded_sample'/
             'dry_run'/'native_undo'). An op on the copy-surface convention is an implicit copy
             target. A declared test target is honored ONLY when the op targets a recognized
             test/copy surface (is_test_surface); a test-target claim on a live surface is
             refused (I1). For a gated op an ABSENT target fails safe to refuse. Ignored for the
             ungated seeded status ops (read_only_local / reversible_external): the gate is a
             no-op for them and their behavior is byte-identical to pre-B1-4.
    descriptor_set: (B1-4) the accepted-descriptor set (B1-2 shape). None => loaded fail-safe
             from disk (absent until B2 => nothing accepted => live refused).
    cap_ledger: (B1-4) the InvocationLedger enforcing the deterministic blast-radius cap on
             live irreversible ops. Absent on a live irreversible op => fail-safe refuse.
    clock:   (B1-4/F-22) a no-arg callable returning a UTC datetime; every date this code writes
             comes from it. Defaults to the system clock; injected only for deterministic tests.

    Credential isolation (BL-1 / F-33): run_operation takes NO caller-supplied
             write-credential provider. When op.op_kind has a registered adapter that
             self-provisions its own write client, the write-capable raw client is resolved
             INTERNALLY inside the adapter execution path (see _run_adapter_operation:
             `adapter.build_write_client(op)`), keyed by the registered adapter — never by a
             caller of run_operation and never exposed to capability/proposal-side code. An
             adapter that does not self-provision falls back to `client` as the raw write
             client (unchanged, backward-compatible). The legacy field-write path uses
             `client` directly.

    Returns
    -------
    Result with status in {'written', 'needs_operator_choice', 'refused'}.
    """

    # Step 0 (B1-4): the deterministic pre-write gate — the single chokepoint's fail-safe heart.
    # Runs BEFORE receipt validation and before anything touches the surface. A no-op for the
    # ungated seeded status ops; refuses fail-safe for every missing input on a gated op.
    decision = evaluate_write_gate(
        op, target=target, descriptor_set=descriptor_set,
        cap_ledger=cap_ledger, clock=clock)
    if not decision.permitted:
        return decision.refusal
    _gate_audit = decision.audit

    # Step 1: receipt validation — refuse before touching the surface.
    reason = _validate_receipt(op, receipt)
    if reason:
        return Result(status="refused", detail={"reason": reason})

    # Step 1.5 (T2): dry_run no-mutation guarantee. The gate (Step 0) permits `dry_run`
    # UNCONDITIONALLY (T1) precisely because THIS adapter guarantees it never reaches
    # client.write (the sole external-write site, below) — nor the client.read read-back,
    # nor post-write verification. A dry_run is a preview of whether the REAL write would
    # be permitted: the gate and receipt validation above still run in full, in order, so
    # a dry_run of a would-be-refused op still reports refused (fail-safe overriding).
    # Once both pass, report the write that WOULD happen without ever performing it.
    # Reuses status="written" (see adapters test module / write_gate T1 tests, which
    # already assert status=="written" for dry_run) with an unambiguous dry_run=True
    # detail marker — no consumer of Result.status distinguishes a real write from this.
    if target == "dry_run":
        detail: dict = {"dry_run": True, "simulated_value": op.new_value}
        return Result(status="written", detail=detail)

    # Step 1.75 (T2): registered-adapter action path. When op.op_kind has a
    # registered Adapter (adapter_registry.py), dispatch to it INSTEAD of the
    # field-write path below: plan the effect units, refuse before any write if the
    # planned count exceeds the blast-radius cap (the F-31 fix — a single Operation
    # carrying many targets can no longer slip past the cap by counting as one
    # invocation), then apply each unit in turn. An op_kind with NO registered
    # adapter falls straight through to the unchanged field-write path. Task 8
    # evaluated migrating the six seeded field op_kinds onto this registry and
    # decided against it (see adapter_registry.py's module docstring for the
    # full reasoning) — they stay on this fallback path indefinitely; the
    # backward-compatibility guarantee is proven by
    # test_external_write_replay_conformance.py instead.
    adapter = get_adapter(op.op_kind)
    if adapter is not None:
        return _run_adapter_operation(op, client, adapter, descriptor_set, _gate_audit)

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
    # The gate's audit record (e.g. the F-22 clock-stamped irreversibility acknowledgement) is
    # merged into the success detail; it is None for the ungated status ops, so their written
    # Result stays byte-identical (detail=None) to pre-B1-4.
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
