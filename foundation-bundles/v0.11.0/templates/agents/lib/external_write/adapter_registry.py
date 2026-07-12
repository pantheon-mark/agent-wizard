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

Scope note (T2/T8 boundary, resolved): Task 2 deliberately did NOT migrate the
six seeded field op_kinds (set_status, complete_tasks, update_due_date,
add_note, set_priority, delete_record) onto this registry, leaving that
decision plus replay-conformance to Task 8.

Task 8 evaluated registering those six op_kinds as a single "field adapter"
and DECIDED AGAINST IT: `_run_adapter_operation` (adapters.py) — the
registered-adapter execution path — does not perform the field-write path's
Steps 2-4 (native-API fail-fast ValueError -> needs_operator_choice,
read-back verification, postwrite_verification/Clause A handling). Those are
cross-cutting over the whole Operation, not per-EffectUnit, so folding the six
field op_kinds into this registry would require either duplicating that logic
inside apply_one (violating the "apply_one performs exactly one mutation"
protocol above) or generalizing run_operation's adapter-dispatch path itself —
a change touching every registered adapter, including the Gmail reference
adapter (Task 7), for zero behavioral benefit given the existing fallback
already passes every field-op test. See
test_external_write_replay_conformance.py for the resulting backward-
compatibility guarantee (golden v1-field digests + full-pipeline replay for
all six op_kinds) and its
TestFieldOpKindsUseUnregisteredFallbackPath, which fails loudly if a future
change registers one of these op_kinds without redoing this analysis.

The registry therefore stays empty for every seeded field op_kind
indefinitely (not just "until Task 8"), and run_operation's field-write path
(unchanged) continues to handle them exactly as before.

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

    build_write_client (OPTIONAL — BL-1 / F-33 credential-isolation keystone) —
                 an adapter MAY additionally define
                 ``build_write_client(self, op) -> raw_write_client``: the ONE
                 place this op_kind's write-capable credential/client is
                 constructed or obtained. When present, ``run_operation``'s
                 adapter execution path (``adapters._run_adapter_operation``)
                 calls it INTERNALLY — keyed by the registered adapter, never
                 by any caller of run_operation and never by capability/
                 proposal-side code — to obtain the raw client handed to
                 ``apply_one``. This is why capability-zone code no longer holds
                 a credential provider: the provider lives on the adapter,
                 inside the trusted ADAPTER_PROFILE zone. scan.py's
                 credential_provider_reference rule guards BOTH reach paths in
                 the capability zone — the retired ``write_credential_provider``
                 name AND a ``build_write_client`` reference (e.g.
                 ``get_adapter(op_kind).build_write_client(op)``) — so a
                 capability-zone hand-edit that names either is flagged by the
                 deterministic scanner. Disclosed bound (unchanged): resolving
                 the method by a string literal —
                 ``getattr(adapter, "build_write_client", None)``, as this
                 module's own kernel execution path does — hides the name in a
                 Constant node the symbol check cannot see; that aliased/dynamic
                 reach is the same known deterministic-scanner limitation as the
                 module's other curated-symbol surfaces, NOT closed here. It is
                 deliberately NOT a required Protocol member: an adapter whose
                 write client is supplied by its trusted caller (e.g. the Gmail
                 reference adapter, exercised with a hand-provided
                 ``raw_client``) simply omits it and falls back to
                 run_operation's ``client`` argument, unchanged.
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
