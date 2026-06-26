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
  4. Read-back verification on success.

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
# Core dispatch
# ---------------------------------------------------------------------------

def run_operation(op: Operation, receipt: Any, client: Any) -> Result:
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

    Returns
    -------
    Result with status in {'written', 'needs_operator_choice', 'refused'}.
    """

    # Step 1: receipt validation — refuse before touching the surface.
    reason = _validate_receipt(op, receipt)
    if reason:
        return Result(status="refused", detail={"reason": reason})

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

    return Result(status="written")
