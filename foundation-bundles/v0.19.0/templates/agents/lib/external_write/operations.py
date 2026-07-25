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

Schema versioning (Task 1 — external-write-gate-generalization):
  Operation now carries a `schema` field so the model can represent both
  today's spreadsheet-style field writes and later verb-shaped vendor actions
  (e.g. "archive_task", "post_message") without disturbing anything already
  built on top of the field shape.

    operation-v1-field  (default) — the ORIGINAL shape. canonical_repr() for
                         this schema is BYTE-IDENTICAL to the pre-generalization
                         code: {surface, object_id, field, new_value, op_kind,
                         batch_id} as sorted-key JSON. Existing digest-bound
                         approval receipts and released-bundle replay depend on
                         this never changing. A receipt (or any mapping) that
                         does not carry a "schema_version" key predates this
                         generalization and MUST resolve to operation-v1-field
                         — see resolve_schema_version().

    operation-v2-action  — verb-shaped ops. canonical_repr() serialises
                         {surface, op_kind, params, undo_descriptor} as
                         sorted-key JSON. object_id / field / new_value are
                         legacy-only and are not part of this shape.

  Task 2 wires dispatch/registry/gate behaviour on top of this; this task is
  the data model only.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

# Schema identifiers. operation-v1-field is the implicit default: absence of
# a schema (on an Operation, or a "schema_version" key on a receipt-shaped
# mapping) always means the legacy field shape — no KeyError, no behavior
# change for anything minted before this generalization existed.
SCHEMA_V1_FIELD = "operation-v1-field"
SCHEMA_V2_ACTION = "operation-v2-action"


def resolve_schema_version(receipt: Optional[Mapping[str, Any]]) -> str:
    """Resolve the operation schema version implied by a receipt-shaped mapping.

    A `None`, empty, or "schema_version"-less mapping is legacy: it predates
    the v1/v2 schema split and MUST be treated as operation-v1-field. This
    never raises KeyError and never changes behaviour for a pre-existing
    receipt.
    """
    if not receipt:
        return SCHEMA_V1_FIELD
    return receipt.get("schema_version", SCHEMA_V1_FIELD)


@dataclass(frozen=True)
class Operation:
    """Immutable description of a single external write.

    Attributes
    ----------
    surface:         Identifies the external system (e.g. "google_sheets", "asana").
    op_kind:         Named operation class (e.g. "set_status", "complete_tasks",
                     "update_due_date", "archive_task"). Adapters dispatch on this.
    batch_id:        Caller-supplied identifier for the broader approval batch.
                     Used for audit / logging; does not affect write behaviour.
    object_id:       (operation-v1-field only) The target object within the
                     surface (sheet ID, task GID, …).
    field:           (operation-v1-field only) The field or column being
                     written (e.g. "Status", "Due Date").
    new_value:       (operation-v1-field only) The value to write. Must be a
                     type serialisable by json.dumps.
    schema:          Which canonicalization shape this Operation uses —
                     SCHEMA_V1_FIELD (default) or SCHEMA_V2_ACTION.
    params:          (operation-v2-action only) Named parameters for a
                     verb-shaped action. Must be json.dumps-serialisable.
    undo_descriptor: (operation-v2-action only) Opaque, adapter-defined
                     description of how to reverse this action. Must be
                     json.dumps-serialisable.
    """

    surface: str
    op_kind: str
    batch_id: str
    object_id: Optional[str] = None
    field: Optional[str] = None
    new_value: Any = None
    schema: str = SCHEMA_V1_FIELD
    params: Optional[dict] = None
    undo_descriptor: Optional[Any] = None

    def canonical_repr(self) -> str:
        """Stable, deterministic string representation used for digest computation.

        Fields are serialised as a sorted-key JSON object so the representation
        is independent of Python dataclass field order and dict insertion order.

        The shape depends on `schema`. Any value other than SCHEMA_V2_ACTION
        (including a missing/None schema, defensively) falls back to
        operation-v1-field — the shape existing receipts and replay depend on.
        """
        schema = getattr(self, "schema", None) or SCHEMA_V1_FIELD
        if schema == SCHEMA_V2_ACTION:
            return json.dumps(
                {
                    "surface": self.surface,
                    "op_kind": self.op_kind,
                    "params": self.params,
                    "undo_descriptor": self.undo_descriptor,
                },
                sort_keys=True,
                ensure_ascii=True,
            )
        # operation-v1-field — MUST remain byte-identical to the
        # pre-generalization representation.
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
class EffectUnit:
    """One discrete external mutation an Operation will perform.

    Later tasks use EffectUnit to count blast radius pre-execution: one
    EffectUnit is one discrete mutation against the external surface (one
    row write, one task archived, one message posted, …). Not wired into
    dispatch/gate behaviour in this task — see Task 2.

    Attributes
    ----------
    unit_id:    Identifier for this discrete mutation, unique within its
                Operation (e.g. a row key, a task GID).
    target_ref: Opaque, adapter-defined reference to what is being mutated.
    undo_ref:   Opaque, adapter-defined reference to how to reverse this one
                unit, if reversible. None when no undo is available.
    """

    unit_id: str
    target_ref: Any
    undo_ref: Optional[Any] = None


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
                                  NOTE (v0.12.0 Slice 1 / Task 3): 'written' NO LONGER
                                  implies the apply was confirmed on the real surface.
                                  Real-surface run-time verification is reported
                                  SEPARATELY in detail['verification'] — per-unit
                                  'verified' vs the honest 'applied_not_verified' (the
                                  kernel could not confirm the apply landed). Read
                                  detail['verification'], not the bare 'written' status,
                                  to know whether a write was verified.
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
