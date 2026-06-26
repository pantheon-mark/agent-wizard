"""Approval broker for external-write operation sets.

The broker presents a set of Operations to the operator in plain language,
writes a review file for detailed inspection, and on confirmation mints a
receipt that the run_operation adapter can validate.

Workflow
--------
1. propose(operations) -> Proposal
   - Renders a plain-language summary (summary_text) the operator reads in chat.
   - Writes a review file (review_file_path) with per-operation detail for
     the operator to open and inspect before confirming.
   - Returns a pending_token bound to the exact operation set.

2. confirm(pending_token, operator_response) -> Receipt
   - Validates the token matches a live pending proposal.
   - Mints one per-operation receipt (usable with run_operation) for every
     approved operation, plus a combined digest that uniquely identifies
     the entire approved set.
   - Records the operator's confirmation text verbatim.

Receipt contract (per Task 1 adapters.py)
-----------------------------------------
run_operation checks receipt["approved_operation_digest"] == op.digest()
for each individual operation. The broker therefore mints one receipt dict
per operation:

    per_op_receipt = {
        "approved_operation_digest": op.digest(),
        "expires_at": "<ISO-8601 UTC Z>",
    }

These are stored in Receipt.op_receipts (keyed by op.digest()) so the
caller can retrieve the correct receipt for each op before calling
run_operation.

Combined digest scheme
-----------------------
The combined digest in Receipt.approved_operation_digest is the SHA-256 of
the sorted, newline-joined list of per-op digests:

    combined = sha256(sorted_per_op_digests joined by newlines)

This scheme is:
  - Deterministic: same op set (any insertion order) -> same combined digest.
  - Tamper-evident: any change to any single op changes its per-op digest
    and therefore the combined digest.
  - Distinct from all per-op digests (different input domain).

The combined digest is a batch-level audit token. It does NOT replace the
per-op digest that run_operation checks — those live in op_receipts.

Operator Interaction Contract conformance
------------------------------------------
summary_text is plain language per the Operator Interaction Contract:
  - No internal field names (op_kind, batch_id, object_id, new_value, …).
  - No raw JSON fragments.
  - No spreadsheet cell coordinates.
  - Written in the direct, calm voice of the contract.

review_file is readable plain text (not a raw JSON dump) describing each
operation so the operator can inspect the detail before confirming.

Stdlib only — no third-party dependencies.
"""

import hashlib
import secrets
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from external_write.operations import Operation


# ---------------------------------------------------------------------------
# Data classes returned to the caller
# ---------------------------------------------------------------------------

@dataclass
class Proposal:
    """Returned by propose(). Carries everything the caller needs to surface
    the pending approval to the operator.

    Attributes
    ----------
    summary_text:      Plain-language description of what will be written.
                       Safe to display directly in a chat message.
    review_file_path:  Absolute path to the review file the operator should
                       open for full detail.
    pending_token:     Opaque string that confirm() requires to mint a receipt.
                       Bound to the exact operation set — a changed set voids it.
    """
    summary_text: str
    review_file_path: str
    pending_token: str


@dataclass
class Receipt:
    """Returned by confirm(). Carries the minted approval evidence.

    Attributes
    ----------
    approved_operation_digest:
        Combined SHA-256 digest of the entire approved operation set.
        Uniquely identifies this exact batch.
    operator_confirmation:
        The operator's verbatim confirmation text.
    expires_at:
        ISO-8601 UTC timestamp with Z suffix (e.g. 2026-06-27T10:00:00Z).
        Matches the format run_operation expects.
    op_receipts:
        Dict mapping each approved operation's digest (str) to a receipt dict
        that run_operation will accept for that specific operation:
            {"approved_operation_digest": op.digest(), "expires_at": ...}
        Retrieve the correct receipt for each op before calling run_operation:
            receipt_for_op = batch_receipt.op_receipts[op.digest()]
            result = run_operation(op, receipt_for_op, client)
    """
    approved_operation_digest: str
    operator_confirmation: str
    expires_at: str
    op_receipts: Dict[str, Dict[str, str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_RECEIPT_TTL_SECONDS = 900  # 15 minutes


def _combined_digest(ops: Sequence[Operation]) -> str:
    """Stable combined digest for a set of operations.

    Sorts the per-op digest strings (ASCII-safe hex) and hashes the sorted,
    newline-joined sequence. Any change to any operation changes the result.
    """
    per_op_digests = sorted(op.digest() for op in ops)
    payload = "\n".join(per_op_digests)
    return hashlib.sha256(payload.encode()).hexdigest()


def _expires_at_str(ttl_seconds: int = _RECEIPT_TTL_SECONDS) -> str:
    """ISO-8601 UTC timestamp with Z suffix, ttl_seconds from now."""
    exp = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    return exp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain_surface_name(surface: str) -> str:
    """Convert an internal surface key to a readable label."""
    mapping = {
        "google_sheets": "Google Sheets",
        "asana": "Asana",
        "notion": "Notion",
        "airtable": "Airtable",
        "smartsheet": "Smartsheet",
    }
    return mapping.get(surface, surface.replace("_", " ").title())


def _plain_op_kind(op_kind: str) -> str:
    """Convert an op_kind key to a short readable phrase."""
    mapping = {
        "set_status": "set the status",
        "complete_tasks": "mark as complete",
        "update_due_date": "update the due date",
        "add_note": "add a note",
        "set_priority": "set the priority",
    }
    return mapping.get(op_kind, op_kind.replace("_", " "))


def _build_summary_text(ops: Sequence[Operation]) -> str:
    """Render a plain-language summary for the operator.

    Conforms to the Operator Interaction Contract:
    - No raw field names, no JSON, no cell coordinates.
    - Plain, direct language describing what will change.
    """
    count = len(ops)
    noun = "change" if count == 1 else "changes"
    lines = [
        f"The following {count} {noun} are ready for your review. "
        "Please confirm to proceed, or decline to cancel.",
        "",
    ]

    # Group by surface for readability
    by_surface: Dict[str, List[Operation]] = {}
    for op in ops:
        by_surface.setdefault(op.surface, []).append(op)

    for surface, surface_ops in by_surface.items():
        readable_surface = _plain_surface_name(surface)
        lines.append(f"In {readable_surface}:")
        for op in surface_ops:
            action = _plain_op_kind(op.op_kind)
            # Present field and value in plain language; avoid internal key names
            value_repr = str(op.new_value)
            lines.append(f"  - {action.capitalize()}: \"{value_repr}\"")
        lines.append("")

    lines.append("Open the review file for the full details before confirming.")
    return "\n".join(lines)


def _build_review_file(ops: Sequence[Operation], path: Path) -> None:
    """Write a plain-text review file the operator can open for full detail.

    The file is readable prose — not a raw JSON dump. It lists each
    operation in plain language with enough detail for the operator to
    understand exactly what will be written and where.
    """
    lines = [
        "Pending Write Review",
        "====================",
        "",
        f"Total changes: {len(ops)}",
        "",
    ]

    for i, op in enumerate(ops, 1):
        readable_surface = _plain_surface_name(op.surface)
        action = _plain_op_kind(op.op_kind)
        lines += [
            f"Change {i} of {len(ops)}",
            f"  Where:   {readable_surface} (target: {op.object_id})",
            f"  What:    {action.capitalize()}",
            f"  Writing: \"{op.new_value}\"",
            "",
        ]

    lines += [
        "To approve all changes, confirm in the chat.",
        "To cancel, decline in the chat.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public broker class
# ---------------------------------------------------------------------------

class ApprovalBroker:
    """Stateful approval broker.

    A single broker instance may manage multiple sequential proposals.
    Each call to propose() invalidates any previously outstanding token
    held by this broker instance.

    Parameters
    ----------
    review_dir:  Directory where review files are written. Must exist.
                 Defaults to a new temporary directory.
    """

    def __init__(self, review_dir: Optional[str] = None):
        if review_dir is None:
            # Create a long-lived temp dir for this broker instance
            self._tempdir = tempfile.mkdtemp()
            self._review_dir = Path(self._tempdir)
        else:
            self._review_dir = Path(review_dir)
        # Pending state: token -> (ops, combined_digest)
        self._pending: Dict[str, tuple] = {}
        self._active_token: Optional[str] = None

    def propose(self, operations: Sequence[Operation]) -> Proposal:
        """Present an operation set to the operator for approval.

        Parameters
        ----------
        operations:  Sequence of Operation objects to propose.
                     Must be non-empty.

        Returns
        -------
        Proposal with summary_text, review_file_path, and pending_token.

        Side effects
        ------------
        - Any previously outstanding token issued by this broker instance
          is voided. Only the token returned from this call is live.
        - Writes a review file at review_file_path.
        """
        if not operations:
            raise ValueError("operations must be non-empty")

        ops = list(operations)
        combined = _combined_digest(ops)

        # Void all prior tokens
        self._pending.clear()
        self._active_token = None

        # Mint a new token
        token = secrets.token_hex(32)

        # Build review file
        review_path = self._review_dir / f"review_{token[:8]}.txt"
        _build_review_file(ops, review_path)

        # Build plain-language summary
        summary = _build_summary_text(ops)

        # Register pending state
        self._pending[token] = (ops, combined)
        self._active_token = token

        return Proposal(
            summary_text=summary,
            review_file_path=str(review_path),
            pending_token=token,
        )

    def confirm(self, pending_token: str, operator_response: str) -> Receipt:
        """Confirm a pending proposal and mint a receipt.

        Parameters
        ----------
        pending_token:       The token returned by the most recent propose() call.
        operator_response:   The operator's verbatim confirmation text.

        Returns
        -------
        Receipt with:
          - approved_operation_digest: combined digest of the approved op set
          - operator_confirmation: the operator's verbatim text
          - expires_at: ISO-8601 UTC Z string
          - op_receipts: dict mapping op.digest() -> per-op receipt dict

        Raises
        ------
        KeyError  — token not found (unknown or already voided).
        """
        if pending_token not in self._pending:
            raise KeyError(
                f"pending_token not found or already voided: {pending_token!r}"
            )

        ops, combined = self._pending.pop(pending_token)
        if self._active_token == pending_token:
            self._active_token = None

        expires = _expires_at_str()

        # Mint one per-op receipt for each approved operation
        op_receipts: Dict[str, Dict[str, str]] = {}
        for op in ops:
            op_receipts[op.digest()] = {
                "approved_operation_digest": op.digest(),
                "expires_at": expires,
            }

        return Receipt(
            approved_operation_digest=combined,
            operator_confirmation=operator_response,
            expires_at=expires,
            op_receipts=op_receipts,
        )
