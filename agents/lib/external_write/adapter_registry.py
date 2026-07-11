"""Static per-op_kind adapter registry (Task 2 — external-write-gate-generalization).

`run_operation` (adapters.py) is the single external-write chokepoint. Prior to this
task it knew exactly one write shape: a spreadsheet-style field write
(client.write(object_id, field, value)). This module lets a named op_kind declare a
richer, verb-shaped write instead — a registered Adapter that plans a list of
discrete EffectUnits (operations.py) and applies them one at a time.

The registry is a plain module-level dict, populated by `register_adapter` at import
time (a future adapter module calls register_adapter(op_kind, MyAdapter()) at module
scope). It performs NO validation of op_kind against contracts.py — that join
happens in adapters.py, which resolves the op's contract/risk-class/cap independently
of whether an adapter is registered.

Scope note (T2/T8 boundary): this task does NOT migrate the six seeded field
op_kinds (set_status, complete_tasks, update_due_date, add_note, set_priority,
delete_record) onto this registry — that migration, plus replay-conformance, is
Task 8. Until then the registry stays empty for every existing op_kind, and
run_operation's field-write path (unchanged) handles them exactly as before.

Stdlib only — no third-party dependencies.
"""

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from external_write.operations import EffectUnit


@runtime_checkable
class Adapter(Protocol):
    """The contract a registered op_kind handler must satisfy.

    plan       — pure planning: given the Operation's `params`, return the list of
                 discrete EffectUnits this operation will perform. Must NOT touch
                 the surface (no writes, no reads) — run_operation counts
                 len(units) against the blast-radius cap BEFORE calling apply_one
                 even once, so a plan() that has side effects would defeat that
                 ordering guarantee.
    apply_one  — perform exactly ONE EffectUnit's mutation against raw_client.
                 Adapters must not fan out inside apply_one (one call = one
                 mutation) — enforcing that per-adapter is a later task; T2 only
                 counts units from plan().
    undo_one   — reverse exactly one previously-applied EffectUnit, if the unit is
                 reversible (undo_ref is not None). Not invoked by T2's dispatch
                 path; reserved for a later rollback/undo task.
    verify_one — verify exactly one applied EffectUnit landed as intended. Not
                 invoked by T2's dispatch path; reserved for a later verification
                 task.
    """

    def plan(self, params: Optional[dict]) -> List[EffectUnit]:
        ...

    def apply_one(self, raw_client: Any, unit: EffectUnit) -> None:
        ...

    def undo_one(self, raw_client: Any, unit: EffectUnit) -> None:
        ...

    def verify_one(self, raw_client: Any, unit: EffectUnit) -> Any:
        ...


# The registry itself: op_kind -> Adapter. Static and module-level by design (see
# module docstring) — populated by import of adapter modules, not built dynamically
# at request time.
_REGISTRY: Dict[str, Adapter] = {}


def register_adapter(op_kind: str, adapter: Adapter) -> None:
    """Register `adapter` as the handler for `op_kind`. Re-registering the same
    op_kind overwrites the prior entry (last-registered wins) — callers own
    ordering; this function does not raise on a duplicate op_kind."""
    _REGISTRY[op_kind] = adapter


def get_adapter(op_kind: str) -> Optional[Adapter]:
    """Return the registered Adapter for op_kind, or None if nothing is registered.

    run_operation treats None as "fall through to the existing field-write path" —
    the registry itself makes no claim about whether an unregistered op_kind is
    valid; that is contracts.py's concern."""
    return _REGISTRY.get(op_kind)


def unregister_adapter(op_kind: str) -> None:
    """Remove a registration, if present. Test-only convenience for isolating
    adapter-registry test cases from one another; production adapter modules
    register once at import time and never unregister."""
    _REGISTRY.pop(op_kind, None)
