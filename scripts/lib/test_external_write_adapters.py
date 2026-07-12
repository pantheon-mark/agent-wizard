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

from external_write.operations import Operation, Result, EffectUnit  # noqa: E402
from external_write.adapters import run_operation          # noqa: E402
from external_write import contracts as contracts_mod       # noqa: E402
from external_write.contracts import OperationContract       # noqa: E402
from external_write.adapter_registry import (                # noqa: E402
    register_adapter,
    unregister_adapter,
)
from external_write.write_gate import InvocationLedger, LIVE_TARGET  # noqa: E402


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


class _RaisingClient:
    """A spy client whose write/read RAISE if ever called. Used to prove a dry_run op
    never reaches the sole external-write site (nor a read-back call) — T2's core
    no-mutation guarantee. Any call to either method is treated as a test failure via
    the raised AssertionError."""

    def write(self, object_id, field, value):
        raise AssertionError(
            "client.write must NEVER be called for a dry_run operation "
            f"(called with object_id={object_id!r}, field={field!r}, value={value!r})"
        )

    def read(self, object_id, field):
        raise AssertionError(
            "client.read must NEVER be called for a dry_run operation "
            f"(called with object_id={object_id!r}, field={field!r})"
        )


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


class TestPostwriteVerificationAttach(unittest.TestCase):
    """Clause A attachment: a supplied post-write verification record is validated
    after read-back; back-compat is preserved when none is supplied."""

    def _op(self):
        return Operation(
            surface="google_sheets", object_id="sheet:abc123", field="Status",
            new_value="Complete", op_kind="set_status", batch_id="batch-pv",
        )

    def _good_verification(self, op):
        from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA
        return {
            "schema": POSTWRITE_VERIFICATION_SCHEMA,
            "verification_mode": "prestate_snapshot_diff",
            "claim_strength": "verified",
            "verifier_id": "prestate_snapshot_diff_v1",
            "source_lineage": {
                "pre_write_sources": ["prewrite_csv_backup"],
                "post_write_sources": ["live_surface_read"],
                # Must cover the registry's forbidden_verification_inputs for this verifier.
                "forbidden_sources": [
                    "writer_generated_id_map",
                    "live_id_column_as_truth",
                    "apply_report",
                ],
            },
            "invariant_checked": "row ids stable",
            "evidence_ref": "agents/handoffs/.pv_evidence.txt",
        }

    def test_no_verification_keeps_legacy_written(self):
        op = self._op()
        result = run_operation(op, _receipt(op), _AcceptingClient())
        self.assertEqual(result.status, "written")

    def test_valid_verification_returns_written_with_claim(self):
        op = self._op()
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               postwrite_verification=self._good_verification(op))
        self.assertEqual(result.status, "written")
        self.assertEqual(result.detail["verification"]["claim_strength"], "verified")

    def test_forbidden_lineage_verification_refused(self):
        op = self._op()
        rec = self._good_verification(op)
        rec["source_lineage"]["post_write_sources"] = ["apply_report"]
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               postwrite_verification=rec)
        self.assertEqual(result.status, "refused")
        self.assertIn("apply_report", result.detail["reason"])


class TestDryRunNoMutation(unittest.TestCase):
    """T2 — the adapter-side no-mutation guarantee that makes T1's unconditional
    dry_run gate permit safe. `client.write` is the SOLE external-write site
    (adapters.py); these tests prove a dry_run op never reaches it (nor a
    read-back client.read, nor postwrite verification), while the full pre-write
    pipeline (gate, then receipt validation) still runs in order first."""

    def _ungated_op(self, batch_id="dry-1"):
        # op_kind="set_status" is one of the seeded, ungated status ops
        # (risk_class="reversible_external") — the gate is a no-op for it either way.
        return Operation(
            surface="google_sheets",
            object_id="sheet:abc123",
            field="Status",
            new_value="Complete",
            op_kind="set_status",
            batch_id=batch_id,
        )

    def _gated_op(self, batch_id="dry-2"):
        # op_kind="delete_record" is gated (risk_class="irreversible_external",
        # requires_accepted_phase=True, blast_radius_cap=5) — normally refused live
        # without a covering accepted descriptor + cap ledger. dry_run permits it
        # unconditionally at the gate (T1); this class proves the adapter never lets
        # that permit reach client.write.
        return Operation(
            surface="google_sheets",
            object_id="obj:dry-delete",
            field="__record__",
            new_value="<deleted>",
            op_kind="delete_record",
            batch_id=batch_id,
        )

    # ------------------------------------------------------------------
    # Core no-mutation proof: a spy client whose .write RAISES if ever called.
    # ------------------------------------------------------------------
    def test_dry_run_never_calls_client_write_or_read(self):
        op = self._ungated_op()
        client = _RaisingClient()
        receipt = _receipt(op)
        # Must NOT raise — client.write/client.read are never invoked for dry_run.
        result = run_operation(op, receipt, client, target="dry_run")
        self.assertIsInstance(result, Result)
        self.assertEqual(result.status, "written")
        self.assertIsNotNone(result.detail)
        self.assertTrue(result.detail.get("dry_run") is True,
                        "dry_run Result.detail must unambiguously mark dry_run=True")

    def test_dry_run_of_gated_op_never_calls_client_write(self):
        # Same proof, but on a GATED op that would be refused live (no accepted
        # descriptor, no cap ledger) — dry_run still permits at the gate (T1) and the
        # adapter still never reaches client.write.
        op = self._gated_op()
        client = _RaisingClient()
        receipt = _receipt(op)
        result = run_operation(op, receipt, client, target="dry_run")
        self.assertEqual(result.status, "written")
        self.assertTrue(result.detail.get("dry_run") is True)

    # ------------------------------------------------------------------
    # Fail-safe overriding: receipt validation precedes the no-write return.
    # ------------------------------------------------------------------
    def test_dry_run_with_missing_receipt_is_refused(self):
        op = self._ungated_op(batch_id="dry-3")
        client = _RaisingClient()
        result = run_operation(op, None, client, target="dry_run")
        self.assertEqual(result.status, "refused")

    def test_dry_run_with_expired_receipt_is_refused(self):
        op = self._ungated_op(batch_id="dry-4")
        client = _RaisingClient()
        receipt = _receipt(op, expired=True)
        result = run_operation(op, receipt, client, target="dry_run")
        self.assertEqual(result.status, "refused")

    def test_dry_run_with_wrong_digest_receipt_is_refused(self):
        op = self._ungated_op(batch_id="dry-5")
        client = _RaisingClient()
        receipt = _receipt(op, wrong_digest=True)
        result = run_operation(op, receipt, client, target="dry_run")
        self.assertEqual(result.status, "refused")

    # ------------------------------------------------------------------
    # dry_run of a gated op with NO covering/declared descriptor and no cap: still
    # permitted at the gate (T1 unconditional dry_run permit) and still no client.write.
    # ------------------------------------------------------------------
    def test_dry_run_of_gated_op_with_no_descriptor_or_cap_still_returns_dry_run_result(self):
        op = self._gated_op(batch_id="dry-6")
        client = _RaisingClient()
        receipt = _receipt(op)
        result = run_operation(
            op, receipt, client, target="dry_run",
            descriptor_set=[], cap_ledger=None,
        )
        self.assertEqual(result.status, "written")
        self.assertTrue(result.detail.get("dry_run") is True)

    # ------------------------------------------------------------------
    # Faithful preview: the simulated value is surfaced in detail.
    # ------------------------------------------------------------------
    def test_dry_run_detail_carries_simulated_value(self):
        op = self._ungated_op(batch_id="dry-7")
        client = _RaisingClient()
        receipt = _receipt(op)
        result = run_operation(op, receipt, client, target="dry_run")
        self.assertEqual(result.detail.get("simulated_value"), op.new_value)

    # ------------------------------------------------------------------
    # Postwrite verification is ignored for dry_run: a supplied (non-None)
    # postwrite_verification must not be consulted, and client.write/client.read
    # must still never be called (same _RaisingClient spy proof as above).
    # ------------------------------------------------------------------
    def test_dry_run_ignores_postwrite_verification_still_no_write(self):
        op = self._ungated_op(batch_id="dry-10")
        client = _RaisingClient()
        receipt = _receipt(op)
        result = run_operation(
            op, receipt, client,
            postwrite_verification={"anything": "non-none-should-be-ignored"},
            target="dry_run",
        )
        self.assertEqual(result.status, "written")
        self.assertTrue(result.detail.get("dry_run") is True)

    # ------------------------------------------------------------------
    # Non-dry_run behavior is unaffected: client.write is still called.
    # ------------------------------------------------------------------
    def test_non_dry_run_live_op_still_calls_client_write(self):
        op = self._ungated_op(batch_id="dry-8")
        client = _AcceptingClient()
        receipt = _receipt(op)
        result = run_operation(op, receipt, client)  # no target -> unaffected path
        self.assertEqual(result.status, "written")
        self.assertEqual(client.read("sheet:abc123", "Status"), "Complete")

    def test_copy_target_op_still_calls_client_write(self):
        # target="copy" on a recognized test/copy surface is a REAL write to that
        # surface (unchanged/byte-identical I1 behavior) — only dry_run is no-write.
        op = Operation(
            surface="copy_surface",
            object_id="obj:copy-1",
            field="__record__",
            new_value="<x>",
            op_kind="delete_record",
            batch_id="dry-9",
        )
        client = _AcceptingClient()
        receipt = _receipt(op)
        result = run_operation(op, receipt, client, target="copy")
        self.assertEqual(result.status, "written")
        self.assertEqual(client.read("obj:copy-1", "__record__"), "<x>")


class _BulkPlanAdapter:
    """Test adapter whose plan() fans out to `n` EffectUnits. Records every
    apply_one call so a test can assert it was NEVER invoked (the F-31
    regression proof: a many-target Operation must be refused on cardinality
    BEFORE any unit is applied)."""

    def __init__(self, n):
        self._n = n
        self.applied = []

    def plan(self, params):
        return [EffectUnit(unit_id=f"u{i}", target_ref=params) for i in range(self._n)]

    def apply_one(self, raw_client, unit):
        self.applied.append(unit)
        raw_client.write(unit.unit_id, "Status", "Complete")

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return True


class TestAdapterDispatchCardinalityCap(unittest.TestCase):
    """T2 — run_operation dispatches to a registered adapter and enforces the
    blast-radius cap on len(effect_units) BEFORE any write (the F-31 regression:
    a single Operation carrying many targets must not slip past the cap)."""

    OP_KIND = "_bulk_probe_op"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="reversible_external",  # ungated -- isolates the cardinality
            blast_radius_cap=25,               # cap under test, independent of the gate
        )

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)

    def _op(self, batch_id="bulk-1"):
        return Operation(
            surface="google_sheets",
            op_kind=self.OP_KIND,
            batch_id=batch_id,
            params={"rows": list(range(55))},
        )

    def test_55_unit_plan_over_cap_25_refuses_with_zero_writes(self):
        adapter = _BulkPlanAdapter(55)
        register_adapter(self.OP_KIND, adapter)
        op = self._op()
        client = _RaisingClient()  # raises AssertionError if .write/.read ever called
        receipt = _receipt(op)

        result = run_operation(op, receipt, client)

        self.assertEqual(result.status, "refused")
        self.assertEqual(len(adapter.applied), 0,
                          "apply_one must NEVER be called once the planned unit count "
                          "exceeds the blast-radius cap")
        self.assertIn("55", result.detail.get("reason", ""))
        self.assertIn("25", result.detail.get("reason", ""))

    def test_under_cap_plan_applies_every_unit(self):
        adapter = _BulkPlanAdapter(10)
        register_adapter(self.OP_KIND, adapter)
        op = self._op(batch_id="bulk-2")
        client = _AcceptingClient()
        receipt = _receipt(op)

        result = run_operation(op, receipt, client)

        self.assertEqual(result.status, "written")
        self.assertEqual(len(adapter.applied), 10)

    def test_op_with_no_registered_adapter_still_writes_via_field_path(self):
        """Parity: an op_kind with NO registered adapter must fall through to the
        existing field-write path, byte-identical to pre-T2 behavior."""
        op = Operation(
            surface="google_sheets",
            object_id="sheet:parity-1",
            field="Status",
            new_value="Complete",
            op_kind="set_status",  # a seeded op_kind -- deliberately unregistered
            batch_id="parity-1",
        )
        client = _AcceptingClient()
        receipt = _receipt(op)

        result = run_operation(op, receipt, client)

        self.assertEqual(result.status, "written")
        self.assertEqual(client.read("sheet:parity-1", "Status"), "Complete")


class _UnitPlanAdapter:
    """Test adapter whose plan() fans out to a FIXED number of EffectUnits,
    for exercising the aggregate blast-radius WINDOW's per-operation unit
    count (NF3) -- distinct from _BulkPlanAdapter above, which exists to
    prove the single-op F-31 cardinality cap. Records every apply_one call so
    a test can confirm exactly how many units actually got applied."""

    def __init__(self, n):
        self._n = n
        self.applied = []

    def plan(self, params):
        return [EffectUnit(unit_id=f"u{i}", target_ref=params) for i in range(self._n)]

    def apply_one(self, raw_client, unit):
        self.applied.append(unit)
        raw_client.write(unit.unit_id, "Status", "Complete")

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return True


class TestUnitAwareBlastRadiusWindow(unittest.TestCase):
    """NF3 -- the aggregate blast-radius WINDOW (the shared InvocationLedger's
    lifetime) must be bounded in UNITS, not in invocation count. The per-op
    cap (F-31, TestAdapterDispatchCardinalityCap above) is an independent,
    single-op bound and stays intact; this class is about the SEPARATE
    aggregate window a cap_ledger enforces across MULTIPLE invocations of the
    SAME capability. Uses a GATED (irreversible_external, requires_accepted_
    phase=True) op_kind with an ACCEPTED covering descriptor entry so the op
    actually runs the live-enforcement funnel (_enforce_live_funnel) where the
    window lives."""

    OP_KIND = "_unit_window_probe"
    SURFACE = "google_sheets"
    CAP = 25

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="irreversible_external",
            requires_accepted_phase=True,
            blast_radius_cap=self.CAP,
        )

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)

    def _op(self, batch_id):
        return Operation(
            surface=self.SURFACE,
            op_kind=self.OP_KIND,
            batch_id=batch_id,
            params={"batch": batch_id},
        )

    def _accepted_entry(self):
        return {
            "id": self.SURFACE, "name": self.SURFACE, "action_class": "delete",
            "risk_class": "irreversible_external", "recovery_profile_ref": None,
            "declared_test_target": "copy", "blast_radius_cap": None,
            "accepted": True,
        }

    def _ledger_key(self):
        return f"{self.SURFACE}::{self.OP_KIND}"

    def test_aggregate_window_bounded_by_units_not_invocations(self):
        # cap=25; three ops of 10 units each. Bounded by UNITS: the first two
        # (10, then 20 units consumed) are permitted; the third would reach
        # 30 units and is refused. Under the OLD one-slot-per-invocation
        # window this sequence is only invocation 3 of 25 -- nowhere near the
        # cap -- so a pass here on the new code but the assertions below on
        # led.count() failing would expose a regression to invocation-only
        # counting.
        adapter = _UnitPlanAdapter(10)
        register_adapter(self.OP_KIND, adapter)
        ds = [self._accepted_entry()]
        led = InvocationLedger()
        key = self._ledger_key()

        op1 = self._op("b1")
        r1 = run_operation(op1, _receipt(op1), _AcceptingClient(),
                           target=LIVE_TARGET, descriptor_set=ds, cap_ledger=led)
        self.assertEqual(r1.status, "written")
        self.assertEqual(led.count(key), 10,
                         "the window must consume len(effect_units) per op, not 1 slot")

        op2 = self._op("b2")
        r2 = run_operation(op2, _receipt(op2), _AcceptingClient(),
                           target=LIVE_TARGET, descriptor_set=ds, cap_ledger=led)
        self.assertEqual(r2.status, "written")
        self.assertEqual(led.count(key), 20)

        op3 = self._op("b3")
        r3 = run_operation(op3, _receipt(op3), _AcceptingClient(),
                           target=LIVE_TARGET, descriptor_set=ds, cap_ledger=led)
        self.assertEqual(
            r3.status, "refused",
            "third 10-unit op must be refused: 20 units already consumed + "
            "10 more = 30 > cap of 25 -- a session of 25-unit invocations "
            "must be bounded by TOTAL UNITS, not invocation count")
        self.assertIn("cap", r3.detail["reason"].lower())
        # The refused op recorded NOTHING to the ledger and applied nothing.
        self.assertEqual(led.count(key), 20)
        self.assertEqual(len(adapter.applied), 20,
                         "the refused third op must not have applied any unit")

    def test_contrast_one_slot_per_invocation_window_would_have_passed_all_three(self):
        # Direct contrast proof (per the task brief): replay the exact same
        # 3-invocation sequence against the LEGACY one-slot-per-invocation
        # counting convention (InvocationLedger.record(key) with no explicit
        # n -- the pre-NF3 default) and show it would sit at 3/25, nowhere
        # near refusal -- i.e. the bound genuinely is unit-based now, not
        # merely coincidentally stricter.
        legacy_ledger = InvocationLedger()
        key = self._ledger_key()
        for _ in range(3):
            legacy_ledger.record(key)  # legacy call site: n defaults to 1
        self.assertEqual(legacy_ledger.count(key), 3)
        self.assertLess(
            legacy_ledger.count(key), self.CAP,
            "under a 1-slot-per-invocation window, 3 invocations of a 10-unit "
            "op would never approach a cap of 25, even though 30 units were "
            "actually consumed -- contrast proof that the real fix must "
            "count units, not invocations")


class _MalformedParamsAdapter:
    """Test adapter whose plan() is PURE but NOT TOTAL — like the seeded Gmail
    adapters (adapters_gmail.py), it indexes directly into params (e.g.
    `m["message_id"]`) and raises on malformed input rather than validating.
    Used to reproduce the R3 regression: run_operation's Step -1 hoists
    plan() above the gate to compute n_units, so a plan() failure on
    malformed params must become a clean refused Result, not an uncaught
    exception. Records every plan()/apply_one() call so a test can confirm
    dry_run never even attempts to plan."""

    def __init__(self):
        self.plan_calls = 0
        self.applied = []

    def plan(self, params):
        self.plan_calls += 1
        params = params or {}
        units = []
        for m in params["messages"]:  # KeyError if "messages" is absent/malformed
            units.append(EffectUnit(unit_id=m["message_id"], target_ref=m))
        return units

    def apply_one(self, raw_client, unit):
        self.applied.append(unit)
        raw_client.write(unit.unit_id, "Status", "Complete")

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return True


class TestPlanHoistTotality(unittest.TestCase):
    """R3 fix — regression found in review of the NF3 change (commit 9e69837):
    run_operation's Step -1 called adapter.plan(op.params) UNCONDITIONALLY,
    before the gate/receipt/dry_run short-circuit, to compute n_units. plan()
    is side-effect-free but NOT total (the seeded Gmail adapters raise KeyError
    on malformed params) — so an op the gate would have cleanly refused, or a
    dry_run preview, raised instead of returning a Result, breaking
    run_operation's "always returns a Result" contract and dry_run's no-op
    guarantee. Fixed by: (1) never planning for dry_run, and (2) guarding the
    hoisted plan() call so any exception becomes a clean refused Result."""

    OP_KIND = "_malformed_params_probe"
    SURFACE = "gmail"
    CAP = 25

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("labels",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="irreversible_external",
            requires_accepted_phase=True,
            blast_radius_cap=self.CAP,
        )

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)

    def _op(self, batch_id, params=None):
        return Operation(
            surface=self.SURFACE,
            op_kind=self.OP_KIND,
            batch_id=batch_id,
            params=params if params is not None else {},  # missing "messages" -- malformed
        )

    def _accepted_entry(self):
        return {
            "id": self.SURFACE, "name": self.SURFACE, "action_class": "delete",
            "risk_class": "irreversible_external", "recovery_profile_ref": None,
            "declared_test_target": "copy", "blast_radius_cap": None,
            "accepted": True,
        }

    def test_gate_refusal_target_none_with_malformed_params_is_refused_not_exception(self):
        # A gated op with target=None is a clean gate refusal (missing target fails
        # safe). Malformed params (no "messages" key) would make the adapter's
        # plan() raise KeyError. Before the R3 fix, Step -1's unconditional plan()
        # call raised BEFORE the gate ever ran. The fix must still return a
        # REFUSED Result -- never let the exception propagate.
        adapter = _MalformedParamsAdapter()
        register_adapter(self.OP_KIND, adapter)
        op = self._op("mp-1")  # target defaults to None
        client = _RaisingClient()  # would raise AssertionError if ever touched

        result = run_operation(op, _receipt(op), client)

        self.assertIsInstance(result, Result)
        self.assertEqual(result.status, "refused")
        self.assertEqual(len(adapter.applied), 0)

    def test_dry_run_of_malformed_params_is_noop_preview_and_never_plans(self):
        # dry_run must return its no-op preview even when the op's params are
        # malformed -- it must not plan at all (planning is unnecessary for
        # dry_run, and would crash on this adapter's malformed-input params).
        adapter = _MalformedParamsAdapter()
        register_adapter(self.OP_KIND, adapter)
        op = self._op("mp-2")
        client = _RaisingClient()  # would raise AssertionError if ever touched

        result = run_operation(op, _receipt(op), client, target="dry_run")

        self.assertEqual(result.status, "written")
        self.assertTrue(result.detail.get("dry_run") is True)
        self.assertEqual(adapter.plan_calls, 0,
                         "dry_run must never call adapter.plan() -- it consumes no "
                         "window and needs no units")
        self.assertEqual(len(adapter.applied), 0)

    def test_live_op_with_malformed_params_is_refused_not_exception(self):
        # A live (or live-bounded/accepted-descriptor) op whose params are
        # malformed must still come back as a clean refused Result, never an
        # uncaught exception -- this is the fail-safe direction the fix requires.
        adapter = _MalformedParamsAdapter()
        register_adapter(self.OP_KIND, adapter)
        ds = [self._accepted_entry()]
        led = InvocationLedger()
        op = self._op("mp-3")
        client = _RaisingClient()  # would raise AssertionError if ever touched

        result = run_operation(op, _receipt(op), client,
                               target=LIVE_TARGET, descriptor_set=ds, cap_ledger=led)

        self.assertIsInstance(result, Result)
        self.assertEqual(result.status, "refused")
        self.assertEqual(len(adapter.applied), 0)
        self.assertEqual(led.count(f"{self.SURFACE}::{self.OP_KIND}"), 0,
                         "a plan-failure refusal must not have recorded anything "
                         "to the aggregate window")


# ---------------------------------------------------------------------------
# R7-T2 — captured dispatch is monkey-patch-inert (cross-vendor-ratified
# defense-in-depth fix). Cross-vendor ratification found: capability code
# could do `a = get_adapter(op.op_kind); a.apply_one = thief;
# run_operation(op, forged_receipt, None, target="copy")` and the kernel
# would provision the REAL write client and hand it to the hijacked
# `apply_one`, because run_operation used to call the adapter's MUTABLE
# INSTANCE method. These tests prove that is no longer possible: the thief
# is never invoked, and the write-capable client is never leaked to it.
# ---------------------------------------------------------------------------

class _WriteCapableRecorder:
    """The real write-capable object -- only ever reachable via the
    registered adapter's OWN (captured, class-bound) apply_one/
    build_write_client. If a thief ever got hold of this, that would BE the
    security failure these tests exist to rule out."""

    def __init__(self):
        self.recorded = []

    def record(self, unit):
        self.recorded.append(unit)


class _RaisingCapabilitySideClient2:
    """Stands in for whatever object capability/proposal-side code passes as
    run_operation's `client` argument. Raises if ever used -- proves the
    self-provisioning adapter path never falls back to it."""

    def record(self, unit):
        raise AssertionError(
            "the capability-side client argument must never be used when "
            "the adapter's CLASS self-provisions its own write client")


class _MonkeyPatchableAdapter:
    """A self-provisioning adapter (defines build_write_client on its CLASS)
    used to prove that reassigning apply_one / build_write_client as an
    INSTANCE attribute AFTER registration is inert against run_operation --
    the captured class-bound dispatch runs instead, every time."""

    def __init__(self, write_capable):
        self._write_capable = write_capable
        self.real_apply_calls = []
        self.real_build_calls = []

    def plan(self, params):
        return [EffectUnit(unit_id="u1", target_ref=params)]

    def apply_one(self, raw_client, unit):
        self.real_apply_calls.append(raw_client)
        raw_client.record(unit)

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return True

    def build_write_client(self, op):
        self.real_build_calls.append(op)
        return self._write_capable


class TestCapturedDispatchMonkeyPatchIsInert(unittest.TestCase):

    OP_KIND = "_monkey_patch_dispatch_probe"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="reversible_external",  # ungated -- isolates the dispatch mechanism
        )

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)

    def _op(self, batch_id):
        return Operation(
            surface="fixture_surface",
            op_kind=self.OP_KIND,
            batch_id=batch_id,
            params={"target": "x"},
        )

    def test_instance_apply_one_reassignment_does_not_hijack_run_operation(self):
        write_capable = _WriteCapableRecorder()
        adapter = _MonkeyPatchableAdapter(write_capable)
        register_adapter(self.OP_KIND, adapter)

        stolen = {"called": False, "client": None}

        def _thief_apply_one(raw_client, unit):
            stolen["called"] = True
            stolen["client"] = raw_client
            raise AssertionError("the hijacked apply_one must never be invoked")

        # This is exactly the exploit shape the cross-vendor ratification found:
        # obtain a reference to the registered adapter instance, then reassign
        # one of its methods, THEN drive run_operation.
        adapter.apply_one = _thief_apply_one

        op = self._op("mp-apply-1")
        result = run_operation(op, _receipt(op), _RaisingCapabilitySideClient2())

        self.assertEqual(result.status, "written")
        self.assertFalse(stolen["called"],
                         "the reassigned instance apply_one (thief) must NEVER be called")
        self.assertIsNone(stolen["client"],
                          "the write-capable client must never reach the thief")
        # The REAL (captured, class-bound) apply_one ran instead, against the
        # REAL write-capable client -- not the capability-side client, and not
        # anything the thief ever saw.
        self.assertEqual(len(adapter.real_apply_calls), 1)
        self.assertIs(adapter.real_apply_calls[0], write_capable)
        self.assertEqual(len(write_capable.recorded), 1)

    def test_instance_build_write_client_reassignment_does_not_hijack_run_operation(self):
        real_write_capable = _WriteCapableRecorder()
        thief_write_capable = _WriteCapableRecorder()
        adapter = _MonkeyPatchableAdapter(real_write_capable)
        register_adapter(self.OP_KIND, adapter)

        thief_calls = []

        def _thief_build_write_client(op):
            thief_calls.append(op)
            return thief_write_capable

        adapter.build_write_client = _thief_build_write_client

        op = self._op("mp-build-1")
        result = run_operation(op, _receipt(op), _RaisingCapabilitySideClient2())

        self.assertEqual(result.status, "written")
        self.assertEqual(len(thief_calls), 0,
                         "the reassigned instance build_write_client (thief) must NEVER be called")
        # The REAL (captured, class-bound) build_write_client ran instead, and
        # its result -- not the thief's -- is what apply_one actually received.
        self.assertEqual(len(adapter.real_build_calls), 1)
        self.assertIs(adapter.real_apply_calls[0], real_write_capable)
        self.assertEqual(len(real_write_capable.recorded), 1)
        self.assertEqual(len(thief_write_capable.recorded), 0,
                         "the thief's write-capable client must never be used for a real mutation")

    def test_both_methods_reassigned_together_still_fully_inert(self):
        # Belt-and-braces: both apply_one AND build_write_client hijacked at
        # once must still be fully inert against run_operation.
        real_write_capable = _WriteCapableRecorder()
        adapter = _MonkeyPatchableAdapter(real_write_capable)
        register_adapter(self.OP_KIND, adapter)

        calls = {"apply": 0, "build": 0}

        def _thief_apply_one(raw_client, unit):
            calls["apply"] += 1
            raise AssertionError("hijacked apply_one must never run")

        def _thief_build_write_client(op):
            calls["build"] += 1
            return _WriteCapableRecorder()

        adapter.apply_one = _thief_apply_one
        adapter.build_write_client = _thief_build_write_client

        op = self._op("mp-both-1")
        result = run_operation(op, _receipt(op), _RaisingCapabilitySideClient2())

        self.assertEqual(result.status, "written")
        self.assertEqual(calls, {"apply": 0, "build": 0})
        self.assertEqual(len(real_write_capable.recorded), 1)


# ---------------------------------------------------------------------------
# R7-T2 — plan() return-type guard (gpt ratification finding F4). The
# hoisted plan() call in run_operation's Step -1 was wrapped in a try/except,
# but the `len(_planned_units)` use sat OUTSIDE that guard -- so a plan()
# that returned None (or any other non-list) raised instead of producing a
# clean refusal. Fixed by validating isinstance(_planned_units, list) INSIDE
# the same guard: any failure (exception OR wrong type) is now a clean
# refused Result, never a crash.
# ---------------------------------------------------------------------------

class _NonListPlanAdapter:
    """Adapter whose plan() returns whatever fixed (non-list) value it was
    constructed with, regardless of params. apply_one/undo_one/verify_one
    raise if ever called -- a plan() returning the wrong type must be refused
    before any unit is ever applied."""

    def __init__(self, planned_value):
        self._planned_value = planned_value

    def plan(self, params):
        return self._planned_value

    def apply_one(self, raw_client, unit):
        raise AssertionError("apply_one must never be called when plan() returns a non-list")

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return True


class _ListPlanControlAdapter(_NonListPlanAdapter):
    """Control fixture for the guard's non-triggering path: a REAL, working
    apply_one defined on the CLASS (dispatch is captured off the class, so an
    instance-level override would not do -- see AdapterDispatch's docstring)."""

    def apply_one(self, raw_client, unit):
        raw_client.write(unit.unit_id, "Status", "Complete")


class TestPlanReturnTypeGuard(unittest.TestCase):

    OP_KIND = "_plan_return_type_probe"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="reversible_external",
        )

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)

    def _op(self, batch_id):
        return Operation(
            surface="fixture_surface",
            op_kind=self.OP_KIND,
            batch_id=batch_id,
            params={},
        )

    def test_plan_returning_none_is_refused_not_a_crash(self):
        adapter = _NonListPlanAdapter(None)
        register_adapter(self.OP_KIND, adapter)
        op = self._op("ptg-none")

        result = run_operation(op, _receipt(op), _AcceptingClient())

        self.assertIsInstance(result, Result)
        self.assertEqual(result.status, "refused")

    def test_plan_returning_a_dict_is_refused_not_a_crash(self):
        adapter = _NonListPlanAdapter({"not": "a list"})
        register_adapter(self.OP_KIND, adapter)
        op = self._op("ptg-dict")

        result = run_operation(op, _receipt(op), _AcceptingClient())

        self.assertIsInstance(result, Result)
        self.assertEqual(result.status, "refused")

    def test_plan_returning_a_string_is_refused_not_silently_miscounted(self):
        # A string is len()-able AND iterable, so a naive len()-only guard (or
        # no guard at all) would not crash on this input -- it would silently
        # treat each CHARACTER as a planned "unit" and iterate straight into
        # apply_one, which is exactly the silent-corruption failure mode the
        # isinstance(list) check exists to catch, not merely the None-crash case.
        adapter = _NonListPlanAdapter("not-a-list-of-effect-units")
        register_adapter(self.OP_KIND, adapter)
        op = self._op("ptg-str")

        result = run_operation(op, _receipt(op), _AcceptingClient())

        self.assertIsInstance(result, Result)
        self.assertEqual(result.status, "refused")

    def test_plan_returning_a_list_still_works_unaffected(self):
        # Control: a well-behaved plan() returning an actual list is unaffected
        # by the guard.
        adapter = _ListPlanControlAdapter([EffectUnit(unit_id="u1", target_ref={})])
        register_adapter(self.OP_KIND, adapter)
        op = self._op("ptg-list-ok")

        result = run_operation(op, _receipt(op), _AcceptingClient())

        self.assertEqual(result.status, "written")


if __name__ == "__main__":
    unittest.main()
