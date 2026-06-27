"""Tests for the approval broker.

Four test groups:
  1. summary_text is plain language — no raw field names, no cell coordinates,
     no JSON fragments (assert forbidden shapes are absent).
  2. A review file is written at review_file_path and holds operation detail.
  3. confirm() mints a receipt whose combined digest corresponds to the exact
     approved operation set; a round-trip through run_operation proves each
     per-op receipt is accepted (and a receipt for a different op set is refused).
  4. Changed operation set voids a prior pending_token — the old token cannot
     approve a different set of operations.

Uses stdlib only; no network, no real external surface.
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import Operation, Result  # noqa: E402
from external_write.adapters import run_operation          # noqa: E402
from external_write.broker import (                        # noqa: E402
    ApprovalBroker,
    Proposal,
    Receipt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_op(surface="google_sheets", field="Status", new_value="Complete",
             op_kind="set_status", batch_id="batch-broker-test", object_id="sheet:abc123"):
    return Operation(
        surface=surface,
        object_id=object_id,
        field=field,
        new_value=new_value,
        op_kind=op_kind,
        batch_id=batch_id,
    )


def _make_ops():
    op_a = _make_op(field="Status", new_value="Complete", batch_id="batch-broker-001")
    op_b = _make_op(field="Due Date", new_value="2026-07-01", op_kind="update_due_date",
                    batch_id="batch-broker-001")
    return [op_a, op_b]


class _AcceptingClient:
    """Simulates a surface that accepts any value and reads it back."""

    def __init__(self):
        self._store = {}

    def write(self, object_id, field, value):
        self._store[(object_id, field)] = value

    def read(self, object_id, field):
        return self._store.get((object_id, field))


# ---------------------------------------------------------------------------
# Test group 1: summary_text is plain language
# ---------------------------------------------------------------------------

class TestSummaryPlainLanguage(unittest.TestCase):
    """summary_text must conform to the Operator Interaction Contract:
    plain language; no raw field names / cell coordinates / JSON.
    """

    def setUp(self):
        self.broker = ApprovalBroker(review_dir=tempfile.mkdtemp())
        self.ops = _make_ops()
        self.proposal = self.broker.propose(self.ops)

    def test_summary_text_is_non_empty(self):
        self.assertIsInstance(self.proposal.summary_text, str)
        self.assertGreater(len(self.proposal.summary_text.strip()), 0)

    def test_summary_text_contains_no_raw_json(self):
        """No JSON fragment — no bare { } delimiters used as data structure syntax."""
        text = self.proposal.summary_text
        # A raw JSON object or array opening/closing brace at the start of a value
        # is the forbidden shape. Allow normal English use of braces only if they
        # do not appear as JSON structure (i.e. paired { ... } in non-prose context).
        # Simplest reliable check: the text must not contain '{"' or '"}' — the
        # JSON-object-with-key pattern.
        self.assertNotIn('{"', text,
                         "summary_text must not contain raw JSON object fragments")
        self.assertNotIn('"}', text,
                         "summary_text must not contain raw JSON object fragments")

    def test_summary_text_contains_no_raw_field_names_in_technical_form(self):
        """No raw internal field names in snake_case / camelCase technical form.
        The contract forbids leaking wizard-internal labels: both schema field names
        (op_kind, batch_id, object_id, new_value, approved_operation_digest,
        canonical_repr) AND surface/op_kind internal keys (google_sheets, asana,
        notion, airtable, smartsheet, set_status, complete_tasks, update_due_date,
        add_note, set_priority) that the broker is required to translate to plain
        language before surfacing to the operator.
        """
        forbidden_field_names = [
            # Schema-level internal field names
            "op_kind",
            "batch_id",
            "object_id",
            "new_value",
            "canonical_repr",
            "approved_operation_digest",
            # Surface internal keys (broker must translate via _plain_surface_name)
            "google_sheets",
            "asana",
            "notion",
            "airtable",
            "smartsheet",
            # Op-kind internal keys (broker must translate via _plain_op_kind)
            "set_status",
            "complete_tasks",
            "update_due_date",
            "add_note",
            "set_priority",
        ]
        text = self.proposal.summary_text
        for name in forbidden_field_names:
            self.assertNotIn(name, text,
                             f"summary_text must not expose internal field name: {name!r}")

    def test_summary_text_contains_no_cell_coordinates(self):
        """No spreadsheet cell coordinates (e.g. A1, B3, Sheet1!C4)."""
        import re
        # Cell coordinate pattern: optional sheet prefix, column letter(s), row number.
        cell_coord_re = re.compile(r"\b[A-Z]{1,3}\d+\b")
        # Also match sheet-qualified coords like Sheet1!A1
        sheet_coord_re = re.compile(r"\w+![A-Z]{1,3}\d+")
        text = self.proposal.summary_text
        self.assertIsNone(cell_coord_re.search(text),
                          "summary_text must not contain cell coordinates like A1, B3")
        self.assertIsNone(sheet_coord_re.search(text),
                          "summary_text must not contain sheet-qualified coords like Sheet1!A1")

    def test_summary_text_mentions_count_of_operations(self):
        """Plain-language summary must communicate how many changes are proposed."""
        text = self.proposal.summary_text.lower()
        # Must mention a number (digit or word) near a relevant noun
        import re
        has_count = bool(re.search(r'\b(one|two|three|four|five|\d+)\b', text))
        self.assertTrue(has_count,
                        "summary_text should include the number of operations being proposed")


# ---------------------------------------------------------------------------
# Test group 2: review file is written with operation detail
# ---------------------------------------------------------------------------

class TestReviewFile(unittest.TestCase):
    """A review file must be written at review_file_path containing operation detail."""

    def setUp(self):
        self.broker = ApprovalBroker(review_dir=tempfile.mkdtemp())
        self.ops = _make_ops()
        self.proposal = self.broker.propose(self.ops)

    def test_review_file_exists(self):
        path = Path(self.proposal.review_file_path)
        self.assertTrue(path.exists(),
                        f"review file does not exist at {self.proposal.review_file_path}")

    def test_review_file_is_not_empty(self):
        path = Path(self.proposal.review_file_path)
        content = path.read_text(encoding="utf-8")
        self.assertGreater(len(content.strip()), 0, "review file must not be empty")

    def test_review_file_contains_operation_detail(self):
        """Review file must describe what will be written using plain language.
        The Operator Interaction Contract forbids wizard-internal labels in
        operator-facing text: the plain label ('google sheets') must be present
        and the internal key ('google_sheets') must be absent."""
        path = Path(self.proposal.review_file_path)
        content = path.read_text(encoding="utf-8").lower()
        # Must contain the plain-language surface name — not the internal key.
        self.assertIn("google sheets", content,
                      "review file must reference the surface using its plain name")
        # Must NOT contain the internal underscore form — that would violate the
        # Operator Interaction Contract which forbids wizard-internal labels in
        # operator-facing text.
        self.assertNotIn("google_sheets", content,
                         "review file must not expose the internal key 'google_sheets' "
                         "in operator-facing content")
        # Must contain a value being written
        self.assertIn("complete", content,
                      "review file must include the value being written")

    def test_review_file_not_raw_json_dump(self):
        """The operator's primary view must not be a raw JSON dump.
        Review file may contain structured detail but must have readable prose."""
        path = Path(self.proposal.review_file_path)
        content = path.read_text(encoding="utf-8").strip()
        # A file that is ONLY a JSON object or array is a raw dump — forbidden.
        try:
            parsed = json.loads(content)
            # If it parses as bare JSON, it is a raw dump.
            self.fail(
                "review file is a raw JSON dump — must be readable prose or structured plain text"
            )
        except json.JSONDecodeError:
            pass  # Not bare JSON — acceptable


# ---------------------------------------------------------------------------
# Test group 3: confirm() mints a valid receipt; round-trip through run_operation
# ---------------------------------------------------------------------------

class TestConfirmMintReceipt(unittest.TestCase):
    """confirm() must mint a receipt that run_operation accepts for each op."""

    def setUp(self):
        self.broker = ApprovalBroker(review_dir=tempfile.mkdtemp())
        self.ops = _make_ops()
        self.proposal = self.broker.propose(self.ops)
        self.receipt = self.broker.confirm(
            self.proposal.pending_token,
            operator_response="Confirmed, please proceed.",
        )

    def test_receipt_has_required_fields(self):
        self.assertIsInstance(self.receipt, Receipt)
        self.assertIsNotNone(self.receipt.approved_operation_digest)
        self.assertIsNotNone(self.receipt.operator_confirmation)
        self.assertIsNotNone(self.receipt.expires_at)

    def test_receipt_expires_at_format(self):
        """expires_at must be ISO-8601 UTC with Z suffix (matches Task 1 format)."""
        exp = self.receipt.expires_at
        self.assertTrue(exp.endswith("Z"),
                        f"expires_at must end with 'Z': {exp!r}")
        # Must parse without error
        datetime.strptime(exp, "%Y-%m-%dT%H:%M:%SZ")

    def test_receipt_expires_at_is_future(self):
        exp = datetime.strptime(self.receipt.expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        self.assertGreater(exp, datetime.now(timezone.utc),
                           "receipt expires_at must be in the future")

    def test_receipt_operator_confirmation_recorded(self):
        self.assertEqual(self.receipt.operator_confirmation,
                         "Confirmed, please proceed.")

    def test_combined_digest_is_deterministic(self):
        """Same op set -> same combined digest (deterministic)."""
        proposal2 = self.broker.propose(self.ops)
        receipt2 = self.broker.confirm(
            proposal2.pending_token,
            operator_response="yes",
        )
        self.assertEqual(
            self.receipt.approved_operation_digest,
            receipt2.approved_operation_digest,
        )

    def test_different_op_set_different_digest(self):
        """Different op set -> different combined digest."""
        other_ops = [_make_op(field="Status", new_value="Open",
                              batch_id="batch-broker-other")]
        proposal_other = self.broker.propose(other_ops)
        receipt_other = self.broker.confirm(
            proposal_other.pending_token,
            operator_response="yes",
        )
        self.assertNotEqual(
            self.receipt.approved_operation_digest,
            receipt_other.approved_operation_digest,
        )

    def test_round_trip_run_operation_accepts_each_approved_op(self):
        """A per-op receipt from the broker makes run_operation accept each approved op."""
        client = _AcceptingClient()
        for op in self.ops:
            per_op_receipt = self.receipt.op_receipts[op.digest()]
            result = run_operation(op, per_op_receipt, client)
            self.assertEqual(
                result.status, "written",
                f"run_operation must accept approved op {op.field!r}; got {result!r}",
            )

    def test_round_trip_run_operation_refuses_different_op(self):
        """A receipt minted for opsA must be refused by run_operation for a different op."""
        # Build an op that was NOT in the approved set
        different_op = _make_op(
            field="Priority",
            new_value="High",
            op_kind="set_priority",
            batch_id="batch-different",
        )
        client = _AcceptingClient()
        # Try to use the first op's per-op receipt against a different op
        first_op = self.ops[0]
        wrong_receipt = self.receipt.op_receipts[first_op.digest()]
        result = run_operation(different_op, wrong_receipt, client)
        self.assertEqual(
            result.status, "refused",
            "run_operation must refuse a receipt from a different op set",
        )


# ---------------------------------------------------------------------------
# Test group 4: changed op set voids the prior pending_token
# ---------------------------------------------------------------------------

class TestPendingTokenVoidOnChange(unittest.TestCase):
    """A pending_token is bound to the exact op set proposed.
    Confirming with a stale token for a different op set must be refused.
    """

    def setUp(self):
        self.broker = ApprovalBroker(review_dir=tempfile.mkdtemp())
        self.ops_a = _make_ops()
        self.ops_b = [_make_op(field="Priority", new_value="High",
                               op_kind="set_priority",
                               batch_id="batch-broker-b")]

    def test_stale_token_is_rejected_after_new_propose(self):
        """After propose(opsA), proposing opsB invalidates tokenA."""
        proposal_a = self.broker.propose(self.ops_a)
        token_a = proposal_a.pending_token
        # Propose a different set (this should void tokenA)
        _proposal_b = self.broker.propose(self.ops_b)
        # Now attempting to confirm with tokenA must raise or return an error
        with self.assertRaises(Exception):
            self.broker.confirm(token_a, operator_response="yes")

    def test_stale_token_per_op_receipt_refused_for_new_ops(self):
        """Even if confirm(tokenA) were called, the per-op receipts it mints
        must be refused by run_operation for opsB ops."""
        # Propose opsA, confirm immediately (token is still valid)
        proposal_a = self.broker.propose(self.ops_a)
        receipt_a = self.broker.confirm(
            proposal_a.pending_token, operator_response="yes"
        )
        # Now try to use receipt_a's per-op receipts for an op in opsB
        op_b = self.ops_b[0]
        client = _AcceptingClient()
        # Try each per-op receipt from receipt_a against op_b
        for per_op_receipt in receipt_a.op_receipts.values():
            result = run_operation(op_b, per_op_receipt, client)
            self.assertEqual(
                result.status, "refused",
                "A receipt minted for opsA must be refused for opsB ops",
            )

    def test_unknown_token_raises(self):
        """A completely unknown token must be rejected."""
        with self.assertRaises(Exception):
            self.broker.confirm("nonexistent-token-xyz", operator_response="yes")


class TestProofGate(unittest.TestCase):
    """Clause C: confirm() blocks first live use until the op's hashes are accepted."""

    def _broker_and_token(self):
        from external_write.broker import ApprovalBroker
        from external_write.operations import Operation
        broker = ApprovalBroker()
        op = Operation(surface="google_sheets", object_id="s:1", field="Status",
                       new_value="Complete", op_kind="set_status", batch_id="b")
        proposal = broker.propose([op])
        return broker, proposal.pending_token, op

    def test_gate_off_by_default_still_mints(self):
        broker, token, _ = self._broker_and_token()
        receipt = broker.confirm(token, "yes go ahead")
        self.assertTrue(receipt.op_receipts)

    def test_gate_blocks_when_not_accepted(self):
        from external_write.broker import CopyRunProofRequired
        from external_write.proof_hash import SHA256_HEX_LEN
        broker, token, op = self._broker_and_token()
        with self.assertRaises(CopyRunProofRequired) as ctx:
            broker.confirm(token, "yes", enforce_proof_gate=True,
                           accepted_write_registry=())
        self.assertEqual(ctx.exception.op_kind, "set_status")
        self.assertEqual(len(ctx.exception.implementation_hash), SHA256_HEX_LEN)

    def test_gate_passes_when_hashes_are_accepted(self):
        from external_write.proof_hash import (
            compute_implementation_hash, compute_contract_hash, AcceptedWriteKey,
        )
        broker, token, op = self._broker_and_token()
        key = AcceptedWriteKey(
            implementation_hash=compute_implementation_hash(op.op_kind),
            contract_hash=compute_contract_hash(op.op_kind),
        )
        receipt = broker.confirm(token, "yes", enforce_proof_gate=True,
                                 accepted_write_registry=(key,))
        self.assertTrue(receipt.op_receipts)

    def test_blocked_confirm_leaves_token_live(self):
        # A gate-blocked confirm() must NOT pop the pending token.
        # The op can be re-proposed/re-confirmed once the hashes are accepted.
        # Token pops only on gate pass (this is the named guarantee in the plan body).
        from external_write.broker import CopyRunProofRequired
        from external_write.proof_hash import (
            compute_implementation_hash, compute_contract_hash, AcceptedWriteKey,
        )
        broker, token, op = self._broker_and_token()

        # Step 1: confirm with empty registry -> gate blocks, raises CopyRunProofRequired.
        with self.assertRaises(CopyRunProofRequired):
            broker.confirm(token, "yes", enforce_proof_gate=True,
                           accepted_write_registry=())

        # Step 2: the token must still be live in _pending (not consumed).
        self.assertIn(token, broker._pending)

        # Step 3: a second confirm with the correct hashes succeeds with the SAME token.
        key = AcceptedWriteKey(
            implementation_hash=compute_implementation_hash(op.op_kind),
            contract_hash=compute_contract_hash(op.op_kind),
        )
        receipt = broker.confirm(token, "yes", enforce_proof_gate=True,
                                 accepted_write_registry=(key,))
        self.assertTrue(receipt.op_receipts)
        # Token is now consumed.
        self.assertNotIn(token, broker._pending)


if __name__ == "__main__":
    unittest.main()
