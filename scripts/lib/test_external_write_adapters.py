"""Tests for the external-write operation model and named-operation adapters.

Four tests:
  1. valid op + valid receipt -> writes + reads back -> 'written'
  2. out-of-vocab value -> surface rejects -> 'needs_operator_choice' with allowed set in detail
  3. missing / invalid / expired receipt -> 'refused'
  4. value-validity strategy: native-API fail-fast reject path triggers correctly when
     Sheets dataValidation is not readable (the reject path fires on surface rejection)

Uses stub clients only; no network, no real Google API.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (the canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import Operation, Result  # noqa: E402
from external_write.adapters import run_operation          # noqa: E402


# ---------------------------------------------------------------------------
# Stub client helpers
# ---------------------------------------------------------------------------

class _AcceptingClient:
    """Simulates a surface that accepts any value and reads it back."""

    def write(self, object_id, field, value):
        """Accept the write, store for read-back."""
        self._store = {(object_id, field): value}

    def read(self, object_id, field):
        return self._store.get((object_id, field))


class _RejectingClient:
    """Simulates a surface that rejects an out-of-vocab value with its allowed set."""

    ALLOWED = ("Open", "In progress", "Waiting", "Complete")

    def write(self, object_id, field, value):
        if value not in self.ALLOWED:
            raise ValueError(
                f"Invalid value '{value}' for field '{field}'. "
                f"Allowed: {self.ALLOWED}"
            )
        self._store = {(object_id, field): value}

    def read(self, object_id, field):
        return getattr(self, "_store", {}).get((object_id, field))


class _MismatchReadBackClient:
    """Simulates a surface that ACCEPTS the write but reads back a DIFFERENT value.
    This tests the fail-closed read-back verification path in run_operation: after
    a successful write the adapter reads the value back; if it does not match
    op.new_value the operation is refused with 'read-back verification failed'.
    """

    def write(self, object_id, field, value):
        """Accept the write — no exception."""
        pass  # write appears to succeed

    def read(self, object_id, field):
        """Return a value that does NOT match what was written."""
        return "__stale_or_wrong_value__"


class _UnreadableValidationClient:
    """Simulates a surface where dataValidation rules are not machine-readable.
    The surface still rejects invalid values at write time (native-API fail-fast).
    Reading the allowed set before the write is NOT possible via this client.
    """

    ALLOWED = ("Approved", "Rejected", "Pending")

    def write(self, object_id, field, value):
        """Surface rejects the value if it is out-of-vocab — no pre-read available."""
        if value not in self.ALLOWED:
            # Error shape: surface gives allowed set at write time.
            raise ValueError(
                f"Value '{value}' not accepted. Allowed: {self.ALLOWED}"
            )
        self._store = {(object_id, field): value}

    def read(self, object_id, field):
        return getattr(self, "_store", {}).get((object_id, field))


# ---------------------------------------------------------------------------
# Receipt helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


def _receipt(op, *, valid=True, expired=False, wrong_digest=False):
    """Build a minimal receipt dict conforming to the receipt contract.

    Receipt contract (Task 1 definition, for Task 2 conformance):
      approved_operation_digest: str  — SHA-256 hex of the canonical op repr
      expires_at: str                 — ISO-8601 UTC timestamp (Z suffix)

    run_operation checks:
      - receipt is present (not None / empty)
      - approved_operation_digest matches the digest of the op being run
      - expires_at is in the future
    """
    import hashlib
    digest = hashlib.sha256(op.canonical_repr().encode()).hexdigest()
    if wrong_digest:
        digest = "0" * 64
    if expired:
        expires_at = (_now() - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        expires_at = (_now() + timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not valid:
        return {}
    return {
        "approved_operation_digest": digest,
        "expires_at": expires_at,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExternalWriteAdapters(unittest.TestCase):

    # ------------------------------------------------------------------
    # Test 1: valid op + valid receipt -> writes + reads back -> 'written'
    # ------------------------------------------------------------------
    def test_valid_op_writes_and_reads_back(self):
        op = Operation(
            surface="google_sheets",
            object_id="sheet:abc123",
            field="Status",
            new_value="Complete",
            op_kind="set_status",
            batch_id="batch-001",
        )
        client = _AcceptingClient()
        receipt = _receipt(op)
        result = run_operation(op, receipt, client)
        self.assertIsInstance(result, Result)
        self.assertEqual(result.status, "written")
        # Confirm the value was actually written and read back.
        self.assertEqual(client.read("sheet:abc123", "Status"), "Complete")

    # ------------------------------------------------------------------
    # Test 2: out-of-vocab value -> surface rejects -> 'needs_operator_choice'
    # ------------------------------------------------------------------
    def test_out_of_vocab_value_returns_needs_operator_choice(self):
        op = Operation(
            surface="google_sheets",
            object_id="sheet:abc123",
            field="Status",
            new_value="INVALID_STATUS",
            op_kind="set_status",
            batch_id="batch-002",
        )
        client = _RejectingClient()
        receipt = _receipt(op)
        result = run_operation(op, receipt, client)
        self.assertEqual(result.status, "needs_operator_choice")
        # detail must surface the allowed set so the operator knows their options.
        self.assertIsNotNone(result.detail)
        allowed = result.detail.get("allowed")
        self.assertIsNotNone(allowed, "detail must include 'allowed' with the surface's allowed set")
        for item in ("Open", "In progress", "Waiting", "Complete"):
            self.assertIn(item, allowed)

    # ------------------------------------------------------------------
    # Test 3a: missing receipt -> 'refused'
    # Test 3b: invalid receipt (empty dict) -> 'refused'
    # Test 3c: expired receipt -> 'refused'
    # Test 3d: wrong digest -> 'refused'
    # ------------------------------------------------------------------
    def test_missing_receipt_refused(self):
        op = Operation(
            surface="google_sheets",
            object_id="sheet:abc123",
            field="Status",
            new_value="Complete",
            op_kind="set_status",
            batch_id="batch-003",
        )
        client = _AcceptingClient()
        result = run_operation(op, None, client)
        self.assertEqual(result.status, "refused")

    def test_invalid_receipt_refused(self):
        op = Operation(
            surface="google_sheets",
            object_id="sheet:abc123",
            field="Status",
            new_value="Complete",
            op_kind="set_status",
            batch_id="batch-003b",
        )
        client = _AcceptingClient()
        result = run_operation(op, {}, client)
        self.assertEqual(result.status, "refused")

    def test_expired_receipt_refused(self):
        op = Operation(
            surface="google_sheets",
            object_id="sheet:abc123",
            field="Status",
            new_value="Complete",
            op_kind="set_status",
            batch_id="batch-003c",
        )
        client = _AcceptingClient()
        receipt = _receipt(op, expired=True)
        result = run_operation(op, receipt, client)
        self.assertEqual(result.status, "refused")

    def test_wrong_digest_refused(self):
        op = Operation(
            surface="google_sheets",
            object_id="sheet:abc123",
            field="Status",
            new_value="Complete",
            op_kind="set_status",
            batch_id="batch-003d",
        )
        client = _AcceptingClient()
        receipt = _receipt(op, wrong_digest=True)
        result = run_operation(op, receipt, client)
        self.assertEqual(result.status, "refused")

    # ------------------------------------------------------------------
    # Test 5: read-back mismatch -> 'refused' with read-back failure reason
    #
    # After a write is accepted by the surface, run_operation reads the value
    # back and compares it to op.new_value.  If they differ the operation is
    # refused — this is the fail-closed trust path that guards against silent
    # write failures (e.g. caching, propagation delay, write-then-read race).
    # ------------------------------------------------------------------
    def test_readback_mismatch_refused_with_verification_reason(self):
        """A surface that accepts the write but reads back a different value must
        cause run_operation to return status='refused' with a reason that indicates
        read-back verification failure.  This guards the fail-closed trust path."""
        op = Operation(
            surface="google_sheets",
            object_id="sheet:abc123",
            field="Status",
            new_value="Complete",
            op_kind="set_status",
            batch_id="batch-005",
        )
        client = _MismatchReadBackClient()
        receipt = _receipt(op)
        result = run_operation(op, receipt, client)
        # Must be refused — not 'written' or 'needs_operator_choice'
        self.assertEqual(
            result.status,
            "refused",
            "run_operation must refuse when the read-back value does not match "
            "the written value (fail-closed trust path)",
        )
        # The detail must indicate read-back verification failure so callers can
        # distinguish this failure mode from a receipt-validation refusal.
        self.assertIsNotNone(result.detail, "refused result must carry detail")
        reason = result.detail.get("reason", "")
        self.assertIn(
            "read-back verification failed",
            reason,
            "refused detail reason must name 'read-back verification failed' so callers "
            "can distinguish this failure from a receipt-validation refusal",
        )

    # ------------------------------------------------------------------
    # Test 4: value-validity strategy — native-API fail-fast
    #
    # When Sheets dataValidation is NOT machine-readable before the write
    # (unreadable-validation client), the adapter STILL catches the surface's
    # own rejection at write time and returns 'needs_operator_choice'.
    # The adapter does NOT bypass validation or silently accept the write.
    # ------------------------------------------------------------------
    def test_unreadable_validation_triggers_fail_fast_reject_path(self):
        op = Operation(
            surface="google_sheets",
            object_id="sheet:xyz789",
            field="Approval",
            new_value="WRONG_VALUE",
            op_kind="set_status",
            batch_id="batch-004",
        )
        client = _UnreadableValidationClient()
        receipt = _receipt(op)
        result = run_operation(op, receipt, client)
        # Must NOT silently bypass validation.
        self.assertNotEqual(result.status, "written")
        # Must surface the rejection as needs_operator_choice (not an unhandled error).
        self.assertEqual(result.status, "needs_operator_choice")
        self.assertIsNotNone(result.detail)
        allowed = result.detail.get("allowed")
        self.assertIsNotNone(allowed, "detail must include allowed set parsed from surface rejection")


if __name__ == "__main__":
    unittest.main()
