"""Released-bundle replay conformance (Task 8 — external-write-gate-generalization).

The core deliverable of this task: prove that operations/receipts produced
under the PRE-GENERALIZATION (operation-v1-field) canonicalization still
validate and replay identically today. This is the guarantee that a released
bundle (e.g. the estate operator project's v0.10.2) is not broken by Tasks
1-7's generalization work — an approval receipt minted by that bundle's
broker, using the OLD digest algorithm, must still be honored by TODAY's
`run_operation`.

Two layers are tested, deliberately kept separate:

  1. Model layer (canonicalization/digest) — extends Task 1's golden fixture
     (which pinned ONE field op_kind, set_status) to cover every seeded field
     op_kind: complete_tasks, update_due_date, add_note, set_priority, and
     delete_record. All six share the exact same v1-field JSON shape
     (Operation.canonical_repr(), operations.py); the golden values below were
     captured by calling that unchanged code path directly — the invariant
     under test is that this shape has not drifted, not that it was re-derived
     by inspection.

  2. Pipeline layer (full replay) — for each field op_kind, mint a receipt
     using the GOLDEN digest (exactly as a pre-generalization broker would
     have computed it) and run it through TODAY's `run_operation`. This
     proves the whole chokepoint — gate, receipt validation, dispatch,
     write, read-back — still honors an old receipt end to end, not merely
     that the digest function agrees in isolation.

Field-adapter registration decision (this task's other in-scope option):
  Task 8 evaluated wrapping the six seeded field op_kinds as a single
  registered Adapter (adapters_field.py) so every op_kind flows through the
  registry uniformly. That was NOT done. `_run_adapter_operation` (adapters.py)
  — the registered-adapter execution path — does not perform: (a) the
  native-API fail-fast catch of a surface ValueError into
  'needs_operator_choice' with a parsed allowed-set, (b) read-back
  verification, or (c) postwrite_verification (Clause A) handling; those are
  Steps 2-4 of the field-write path in run_operation, cross-cutting over the
  WHOLE operation rather than per-EffectUnit, and do not fit the
  plan()/apply_one() shape without a broader refactor of the adapter dispatch
  contract itself. Making that refactor "the field adapter" would mean either
  duplicating those steps inside apply_one (breaking the "apply_one performs
  exactly one mutation" protocol documented in adapter_registry.py) or
  generalizing run_operation's dispatch to run them for every adapter,
  including the Gmail reference adapter (Task 7) — a change with a large
  surface for zero behavioral benefit, since the existing fallback already
  passes every field-op test. Per the task brief's guidance, that risk is
  reason enough not to register: field ops intentionally keep using the T2
  fallback path (Step 1.75 in adapters.py, "no registered adapter -> existing
  field-write path"), and this file's replay-conformance suite is what
  actually carries the backward-compatibility guarantee.

Stdlib only; unittest, not pytest.
"""

import hashlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (the canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import Operation, SCHEMA_V1_FIELD  # noqa: E402
from external_write.adapters import run_operation  # noqa: E402
from external_write.adapter_registry import get_adapter  # noqa: E402

# Sibling test module's Task 1 golden fixture, imported (not re-derived) so the
# set_status case in this file is provably the SAME golden value Task 1 pinned
# -- DRY: one golden per op_kind, never two independently-typed literals that
# could silently drift apart.
from test_external_write_operations import (  # noqa: E402
    _GOLDEN_CANONICAL_REPR as _T1_SET_STATUS_CANONICAL_REPR,
    _GOLDEN_DIGEST as _T1_SET_STATUS_DIGEST,
)


# ---------------------------------------------------------------------------
# Golden fixtures — one per seeded field op_kind. Captured by calling the
# unchanged Operation.canonical_repr()/.digest() directly (see module
# docstring). Do NOT "fix" these to match new output if a future change
# perturbs them -- that is a digest break for released receipts and must be
# treated as an incident, not a test update.
# ---------------------------------------------------------------------------

# op_kind -> (surface, object_id, field, new_value, batch_id, canonical_repr, digest)
_GOLDEN_FIELD_OPS = {
    "set_status": (
        "google_sheets", "sheet:abc123", "Status", "Complete", "batch-001",
        _T1_SET_STATUS_CANONICAL_REPR,
        _T1_SET_STATUS_DIGEST,
    ),
    "complete_tasks": (
        "google_sheets", "sheet:def456", "Status", "Done", "batch-101",
        '{"batch_id": "batch-101", "field": "Status", "new_value": "Done", '
        '"object_id": "sheet:def456", "op_kind": "complete_tasks", "surface": "google_sheets"}',
        "9728298fb9300ff389045639acb77f0d58d3a7fc71d0111fdda394abe7d2ff5c",
    ),
    "update_due_date": (
        "google_sheets", "sheet:ghi789", "Due Date", "2026-08-01", "batch-102",
        '{"batch_id": "batch-102", "field": "Due Date", "new_value": "2026-08-01", '
        '"object_id": "sheet:ghi789", "op_kind": "update_due_date", "surface": "google_sheets"}',
        "78ae347a9e43c35ebd3c0cbada03b150010ec0bdfe8048c08d67ffc75a73b9ff",
    ),
    "add_note": (
        "google_sheets", "sheet:jkl012", "Note", "Reviewed", "batch-103",
        '{"batch_id": "batch-103", "field": "Note", "new_value": "Reviewed", '
        '"object_id": "sheet:jkl012", "op_kind": "add_note", "surface": "google_sheets"}',
        "7372ff93a3258dff9c53c6dff35c154c7ac101acbc0636391f8f0079f06170cf",
    ),
    "set_priority": (
        "google_sheets", "sheet:mno345", "Priority", "High", "batch-104",
        '{"batch_id": "batch-104", "field": "Priority", "new_value": "High", '
        '"object_id": "sheet:mno345", "op_kind": "set_priority", "surface": "google_sheets"}',
        "bdda50c6e63f22736c530668af907ede63c75f684d58abb0e60b48eb4c86ff48",
    ),
    # delete_record is gated (irreversible_external) -- the replay pipeline test
    # below runs it against the copy-surface convention (implicit copy target),
    # not a live surface, so the B1-4 gate does not interfere with what THIS
    # file actually tests: v1-field digest/canonicalization replay.
    "delete_record": (
        "copy_surface", "obj:pqr678", "__record__", "<deleted>", "batch-105",
        '{"batch_id": "batch-105", "field": "__record__", "new_value": "<deleted>", '
        '"object_id": "obj:pqr678", "op_kind": "delete_record", "surface": "copy_surface"}',
        "7c050e8b272b6be607c16f89f478934ff2788e3def49bd466884f0a80385706b",
    ),
}


def _build_op(op_kind):
    surface, object_id, field, new_value, batch_id, _repr, _digest = _GOLDEN_FIELD_OPS[op_kind]
    return Operation(
        surface=surface, object_id=object_id, field=field, new_value=new_value,
        op_kind=op_kind, batch_id=batch_id,
    )


def _golden_receipt(op_kind, *, ttl_seconds=900):
    """A receipt exactly as a pre-generalization broker would have minted it:
    approved_operation_digest computed from the (unchanged) v1-field shape,
    no schema_version key at all (that key did not exist pre-generalization)."""
    _surface, _object_id, _field, _new_value, _batch_id, _repr, digest = _GOLDEN_FIELD_OPS[op_kind]
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {"approved_operation_digest": digest, "expires_at": expires_at}


class _ReplayAcceptingClient:
    """Minimal stub client (mirrors test_external_write_adapters._AcceptingClient):
    accepts any write and reads it back unchanged."""

    def write(self, object_id, field, value):
        self._store = {(object_id, field): value}

    def read(self, object_id, field):
        return getattr(self, "_store", {}).get((object_id, field))


class TestGoldenFieldOpCanonicalizationByteIdentical(unittest.TestCase):
    """Layer 1 — model layer. Every seeded field op_kind's v1-field
    canonical_repr()/digest() must reproduce the pinned pre-generalization
    bytes exactly, and must default to SCHEMA_V1_FIELD with no explicit
    schema kwarg (matching how every released bundle constructs an Operation)."""

    def test_all_seeded_field_op_kinds_have_golden_fixtures(self):
        # Six seeded field op_kinds per contracts.py OPERATION_CONTRACTS
        # (T2/T8 boundary note in adapter_registry.py).
        expected = {
            "set_status", "complete_tasks", "update_due_date",
            "add_note", "set_priority", "delete_record",
        }
        self.assertEqual(set(_GOLDEN_FIELD_OPS.keys()), expected)

    def test_golden_canonical_repr_byte_identical_for_every_field_op_kind(self):
        for op_kind, (*_rest, expected_repr, _expected_digest) in _GOLDEN_FIELD_OPS.items():
            with self.subTest(op_kind=op_kind):
                op = _build_op(op_kind)
                self.assertEqual(op.canonical_repr(), expected_repr)

    def test_golden_digest_byte_identical_for_every_field_op_kind(self):
        for op_kind, (*_rest, _expected_repr, expected_digest) in _GOLDEN_FIELD_OPS.items():
            with self.subTest(op_kind=op_kind):
                op = _build_op(op_kind)
                self.assertEqual(op.digest(), expected_digest)
                # Independently recompute via hashlib against the pinned repr,
                # so a coincidental Operation.digest() bug can't paper over a
                # canonical_repr() drift and vice versa.
                self.assertEqual(
                    hashlib.sha256(op.canonical_repr().encode()).hexdigest(),
                    expected_digest,
                )

    def test_field_op_kinds_default_to_schema_v1_field(self):
        for op_kind in _GOLDEN_FIELD_OPS:
            with self.subTest(op_kind=op_kind):
                op = _build_op(op_kind)
                self.assertEqual(op.schema, SCHEMA_V1_FIELD)

    def test_set_status_golden_matches_task1_pinned_golden(self):
        # Cross-check: this file's set_status fixture must be the SAME value
        # Task 1 golden-pinned, not an independently-typed literal that could
        # silently diverge.
        surface, object_id, field, new_value, batch_id, expected_repr, expected_digest = (
            _GOLDEN_FIELD_OPS["set_status"]
        )
        self.assertEqual(expected_repr, _T1_SET_STATUS_CANONICAL_REPR)
        self.assertEqual(expected_digest, _T1_SET_STATUS_DIGEST)


class TestReleasedBundleReceiptStillReplays(unittest.TestCase):
    """Layer 2 — pipeline layer. A receipt minted with the golden (pre-
    generalization) digest, carrying NO schema_version key, must still be
    honored end-to-end by today's run_operation: not refused, and the write/
    read-back observed exactly as it would have been pre-generalization."""

    def test_every_field_op_kind_replays_to_written_via_golden_receipt(self):
        for op_kind in _GOLDEN_FIELD_OPS:
            with self.subTest(op_kind=op_kind):
                op = _build_op(op_kind)
                receipt = _golden_receipt(op_kind)
                client = _ReplayAcceptingClient()

                kwargs = {}
                if op_kind == "delete_record":
                    # Gated (irreversible_external); replay it against the
                    # copy-surface convention so gate evaluation (a LATER,
                    # unrelated generalization step) does not obscure what
                    # this test actually verifies: the receipt/digest replay.
                    kwargs["target"] = "copy"

                result = run_operation(op, receipt, client, **kwargs)

                self.assertEqual(
                    result.status, "written",
                    f"{op_kind}: a receipt minted under the pre-generalization "
                    f"digest algorithm must still be honored by run_operation "
                    f"(got status={result.status!r}, detail={result.detail!r})",
                )
                self.assertEqual(client.read(op.object_id, op.field), op.new_value)

    def test_golden_receipt_has_no_schema_version_key(self):
        # Pre-generalization receipts never carried this key -- confirm the
        # fixture itself is faithful to that shape, not accidentally "helped"
        # by a key that didn't exist yet.
        for op_kind in _GOLDEN_FIELD_OPS:
            with self.subTest(op_kind=op_kind):
                receipt = _golden_receipt(op_kind)
                self.assertNotIn("schema_version", receipt)

    def test_tampered_digest_still_refused(self):
        # Fail-safe control: replay conformance must not have accidentally
        # loosened receipt validation. A receipt whose digest does not match
        # the golden op is still refused, for every field op_kind.
        for op_kind in _GOLDEN_FIELD_OPS:
            with self.subTest(op_kind=op_kind):
                op = _build_op(op_kind)
                receipt = _golden_receipt(op_kind)
                receipt = dict(receipt, approved_operation_digest="0" * 64)
                client = _ReplayAcceptingClient()
                kwargs = {"target": "copy"} if op_kind == "delete_record" else {}
                result = run_operation(op, receipt, client, **kwargs)
                self.assertEqual(result.status, "refused")


class TestFieldOpKindsUseUnregisteredFallbackPath(unittest.TestCase):
    """Documents + enforces this task's registration decision (see module
    docstring): every seeded field op_kind has NO registered adapter, so
    run_operation's Step 1.75 falls through to the unchanged field-write
    path for all of them. If a future change registers one of these
    op_kinds, this test will fail and force a conscious update here (and, per
    the module docstring, a fresh parity proof against the golden fixtures
    above) rather than a silent behavior change."""

    def test_no_seeded_field_op_kind_has_a_registered_adapter(self):
        for op_kind in _GOLDEN_FIELD_OPS:
            with self.subTest(op_kind=op_kind):
                self.assertIsNone(
                    get_adapter(op_kind),
                    f"{op_kind} unexpectedly has a registered adapter -- Task 8 "
                    "deliberately kept the six seeded field op_kinds on the "
                    "fallback path (see this file's module docstring); if this "
                    "changed intentionally, this test and the replay-conformance "
                    "fixtures above must be re-verified for byte-identical "
                    "behavior, not just updated to pass.",
                )


if __name__ == "__main__":
    unittest.main()
