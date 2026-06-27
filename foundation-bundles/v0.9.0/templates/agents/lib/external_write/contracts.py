"""Per-operation contract registry — the Boundary clause's declared surface and the
Authority clause's accepted-verifier surface.

Each named operation declares, up front and machine-readably:
  * writes            — the field(s)/range(s) it is allowed to change.
  * produces          — any new artifacts it creates (empty for in-place edits).
  * dependency_set    — the lib modules whose code determines its write behavior;
                        used by the proof-hash computation so any change to write
                        logic changes the operation's identity.
  * verifier_set      — the verifier_ids whose post-write verification this op accepts.
  * introduces_persistent_binding — True iff the op introduces or relies on persistent
                        binding across operator-visible data (stable IDs, anchors,
                        cross-refs, hidden helper columns, formula-derived identity,
                        row mappings, linked records, metadata used for future writes).
                        This is the NARROW trigger for durability checks; False for
                        in-place status edits / one-shot / append-only surfaces.

A verifier declares its source lineage so the post-write validator can reject a
verification whose declared source overlaps the operation's forbidden inputs (the
known tautology class: verifying a write against the writer's own output).

This is a build-time + operator-as-approver enforcement ceiling, NOT a runtime or
OS-level guarantee.

Stdlib only — no third-party dependencies.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from external_write.verification_modes import VerificationMode


@dataclass(frozen=True)
class SourceLineage:
    """What sources a verifier may and may not consult."""

    pre_write_sources: Tuple[str, ...]
    post_write_sources: Tuple[str, ...]
    forbidden_verification_inputs: Tuple[str, ...]


@dataclass(frozen=True)
class VerifierDef:
    """A registered post-write verifier and its declared lineage."""

    verifier_id: str
    mode: VerificationMode
    source_lineage: SourceLineage


@dataclass(frozen=True)
class OperationContract:
    """The declared contract for one named operation kind."""

    op_kind: str
    writes: Tuple[str, ...]
    produces: Tuple[str, ...]
    dependency_set: Tuple[str, ...]
    verifier_set: Tuple[str, ...]
    introduces_persistent_binding: bool


# The lib modules whose source determines write behavior for the seeded in-place
# operations. Listed by canonical filename; the proof-hash computation resolves
# these against the installed adapter directory.
_WRITE_AFFECTING_MODULES = (
    "adapters.py",
    "broker.py",
    "operations.py",
    "verifiers.py",
)


VERIFIER_REGISTRY: dict = {
    "prestate_snapshot_diff_v1": VerifierDef(
        verifier_id="prestate_snapshot_diff_v1",
        mode=VerificationMode.PRESTATE_SNAPSHOT_DIFF,
        source_lineage=SourceLineage(
            pre_write_sources=("prewrite_csv_backup",),
            post_write_sources=("live_surface_read",),
            forbidden_verification_inputs=(
                "writer_generated_id_map",
                "live_id_column_as_truth",
                "apply_report",
            ),
        ),
    ),
    "operator_attested_v1": VerifierDef(
        verifier_id="operator_attested_v1",
        mode=VerificationMode.OPERATOR_ATTESTED,
        source_lineage=SourceLineage(
            pre_write_sources=(),
            post_write_sources=(),
            forbidden_verification_inputs=(),
        ),
    ),
}


def _status_contract(op_kind: str, field: str) -> OperationContract:
    """Build a contract for an in-place status-style write (the default seeded shape)."""
    return OperationContract(
        op_kind=op_kind,
        writes=(field,),
        produces=(),
        dependency_set=_WRITE_AFFECTING_MODULES,
        verifier_set=("prestate_snapshot_diff_v1",),
        introduces_persistent_binding=False,
    )


OPERATION_CONTRACTS: dict = {
    "set_status": _status_contract("set_status", "Status"),
    "complete_tasks": _status_contract("complete_tasks", "Status"),
    "update_due_date": _status_contract("update_due_date", "Due Date"),
    "add_note": _status_contract("add_note", "Note"),
    "set_priority": _status_contract("set_priority", "Priority"),
}


def get_contract(op_kind: str) -> Optional[OperationContract]:
    """Return the OperationContract for op_kind, or None if unregistered."""
    return OPERATION_CONTRACTS.get(op_kind)


def get_verifier(verifier_id: str) -> Optional[VerifierDef]:
    """Return the VerifierDef for verifier_id, or None if unregistered."""
    return VERIFIER_REGISTRY.get(verifier_id)


def accepted_verifier_ids(op_kind: str) -> Tuple[str, ...]:
    """Return the verifier_set declared by op_kind's contract (empty if unregistered)."""
    c = get_contract(op_kind)
    return c.verifier_set if c is not None else ()
