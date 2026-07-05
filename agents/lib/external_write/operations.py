"""Canonical operation model for external-write adapters.

Every external write that an operator system performs is represented as an
Operation before it is executed. The Operation is the unit the approval broker
mints a receipt for, and the unit the adapter validates against that receipt.

Stdlib only — no third-party dependencies.

Receipt contract (minimal; Task 2 must produce conforming receipts):
  {
    "approved_operation_digest": "<sha256-hex of op.canonical_repr()>",
    "expires_at": "<ISO-8601 UTC timestamp, Z suffix, e.g. 2026-06-27T10:00:00Z>"
  }

  run_operation checks:
    - receipt is present (not None / empty dict)
    - approved_operation_digest is present and matches sha256(op.canonical_repr())
    - expires_at is present and is a future timestamp (UTC)

  Approval brokers (Task 2) must use Operation.canonical_repr() to compute the
  digest before minting a receipt, so that run_operation can recompute and verify
  the same digest at execution time.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Operation:
    """Immutable description of a single external write.

    Attributes
    ----------
    surface:    Identifies the external system (e.g. "google_sheets", "asana").
    object_id:  The target object within the surface (sheet ID, task GID, …).
    field:      The field or column being written (e.g. "Status", "Due Date").
    new_value:  The value to write. Must be a type serialisable by json.dumps.
    op_kind:    Named operation class (e.g. "set_status", "complete_tasks",
                "update_due_date", "add_note"). Adapters dispatch on this.
    batch_id:   Caller-supplied identifier for the broader approval batch. Used
                for audit / logging; does not affect write behaviour.
    """

    surface: str
    object_id: str
    field: str
    new_value: Any
    op_kind: str
    batch_id: str

    def canonical_repr(self) -> str:
        """Stable, deterministic string representation used for digest computation.

        Fields are serialised as a sorted-key JSON object so the representation
        is independent of Python dataclass field order and dict insertion order.
        """
        return json.dumps(
            {
                "surface": self.surface,
                "object_id": self.object_id,
                "field": self.field,
                "new_value": self.new_value,
                "op_kind": self.op_kind,
                "batch_id": self.batch_id,
            },
            sort_keys=True,
            ensure_ascii=True,
        )

    def digest(self) -> str:
        """SHA-256 hex digest of the canonical representation."""
        return hashlib.sha256(self.canonical_repr().encode()).hexdigest()


@dataclass(frozen=True)
class Result:
    """Outcome of a run_operation call.

    Attributes
    ----------
    status: One of:
        'written'              — EITHER the write succeeded and read-back confirmed,
                                  OR this was a dry_run simulation: no external write
                                  and no read-back occurred, and detail['dry_run'] is
                                  True to mark the distinction unambiguously.
        'needs_operator_choice' — surface rejected the value as out-of-vocab;
                                  detail['allowed'] carries the surface's allowed set.
        'refused'              — receipt was missing, invalid, expired, or digest
                                  mismatch; write was NOT attempted.
    detail: Optional dict with supplementary information. For 'needs_operator_choice',
            must include 'allowed' (sequence of accepted values). For 'refused',
            includes 'reason' string. May be None for 'written'.
    """

    status: str  # 'written' | 'needs_operator_choice' | 'refused'
    detail: Optional[Any] = None
