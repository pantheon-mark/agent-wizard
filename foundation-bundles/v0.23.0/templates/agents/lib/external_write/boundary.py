"""Boundary clause — declared-write-set cross-check.

The bound orchestrator + AST bypass scanner (scan.py) already enforce that the ONLY
legal external writer is code inside this adapter package: any write outside it fails
the build. This module names that as the Boundary clause and adds the per-operation
companion check: a named operation may write only the field(s) its contract declares.
A write to an undeclared field is refused before it reaches the surface.

Enforcement ceiling: build-time + operator-as-approver, NOT a runtime/OS guarantee.

Stdlib only — no third-party dependencies.
"""

from dataclasses import dataclass
from typing import Optional

from external_write.operations import Operation
from external_write.contracts import get_contract


@dataclass(frozen=True)
class BoundaryResult:
    ok: bool
    reason: Optional[str]


def check_declared_write_set(op: Operation) -> BoundaryResult:
    """Return ok=True iff op writes only a field declared in its contract's write set."""
    contract = get_contract(op.op_kind)
    if contract is None:
        return BoundaryResult(
            ok=False,
            reason=f"operation kind {op.op_kind!r} has no registered contract",
        )
    if op.field not in contract.writes:
        return BoundaryResult(
            ok=False,
            reason=(
                f"field {op.field!r} is outside the declared write set "
                f"{contract.writes!r} for operation {op.op_kind!r}"
            ),
        )
    return BoundaryResult(ok=True, reason=None)
