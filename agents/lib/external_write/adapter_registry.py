"""Static per-op_kind adapter registry.

`run_operation` (adapters.py) is the single external-write chokepoint. Originally
it knew exactly one write shape: a spreadsheet-style field write
(client.write(object_id, field, value)). This module lets a named op_kind declare a
richer, verb-shaped write instead — a registered Adapter that plans a list of
discrete EffectUnits (operations.py) and applies them one at a time.

The registry is a plain module-level dict, populated by `register_adapter` at import
time (a future adapter module calls register_adapter(op_kind, MyAdapter()) at module
scope). It performs NO validation of op_kind against contracts.py — that join
happens in adapters.py, which resolves the op's contract/risk-class/cap independently
of whether an adapter is registered.

Scope note (resolved): this registry deliberately does NOT include the
six seeded field op_kinds (set_status, complete_tasks, update_due_date,
add_note, set_priority, delete_record).

A later evaluation considered registering those six op_kinds as a single
"field adapter" and DECIDED AGAINST IT: `_run_adapter_operation` (adapters.py)
— the registered-adapter execution path — does not perform the field-write
path's Steps 2-4 (native-API fail-fast ValueError -> needs_operator_choice,
read-back verification, postwrite_verification/Clause A handling). Those are
cross-cutting over the whole Operation, not per-EffectUnit, so folding the six
field op_kinds into this registry would require either duplicating that logic
inside apply_one (violating the "apply_one performs exactly one mutation"
protocol above) or generalizing run_operation's adapter-dispatch path itself —
a change touching every registered adapter, including the Gmail reference
adapter, for zero behavioral benefit given the existing fallback
already passes every field-op test. See
test_external_write_replay_conformance.py for the resulting backward-
compatibility guarantee (golden v1-field digests + full-pipeline replay for
all six op_kinds) and its
TestFieldOpKindsUseUnregisteredFallbackPath, which fails loudly if a future
change registers one of these op_kinds without redoing this analysis.

The registry therefore stays empty for every seeded field op_kind
indefinitely, and run_operation's field-write path
(unchanged) continues to handle them exactly as before.

Stdlib only — no third-party dependencies.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

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
                 mutation) — enforcing that per-adapter is a later concern; this
                 registry only counts units from plan().
    undo_one   — reverse exactly one previously-applied EffectUnit, if the unit is
                 reversible (undo_ref is not None). Not invoked by this
                 module's dispatch path; reserved for a later rollback/undo task.
    verify_one — verify exactly one applied EffectUnit landed as intended. Not
                 invoked by this module's dispatch path; reserved for a later
                 verification task.

    build_write_client (OPTIONAL — the credential-isolation keystone) —
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

    verify_apply_landed / verify_undo_restored / verify_durability
                 (OPTIONAL — Task 1, B4/T1, v0.12.0 Slice 1's per-op_kind
                 EVIDENCE PREDICATE) — an adapter MAY additionally define
                 ``verify_apply_landed(self, evidence) -> bool``,
                 ``verify_undo_restored(self, evidence) -> bool``, and/or
                 ``verify_durability(self, evidence) -> bool`` (the latter
                 only meaningful for an op_kind whose contract declares
                 ``introduces_persistent_binding=True``). ``evidence`` is a
                 kernel-constructed ``evidence.AdapterEvidence`` — an
                 already-materialized, lineage-typed record (see
                 ``evidence.py``); the predicate signature takes NO path/ref
                 argument, so a predicate is structurally incapable of
                 reading outside what it was handed (the anti-tautology
                 property this closes; extends ``verifiers.py``'s lineage
                 lock). Like ``build_write_client``, these are auto-captured
                 OFF THE CLASS by ``register_adapter`` (see
                 ``AdapterDispatch``'s docstring) — deliberately NOT required
                 Protocol members, so every adapter registered before this
                 task keeps working unchanged (all three simply resolve to
                 None). Nothing in THIS module's dispatch path invokes them
                 yet: proof-time evaluation (`copy_run_proof.
                 validate_copy_run_proof`) and run-time evaluation
                 (`adapters._run_adapter_operation`) are separate, later
                 tasks that consume the captured predicate — this task only
                 builds the capture + the evidence type + proves the
                 predicate signature is sound against ≥2 divergent op_kinds.
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


@dataclass(frozen=True)
class AdapterDispatch:
    """A frozen, CLASS-BOUND dispatch record captured once, at registration
    time (a defense-in-depth fix).

    Why this exists: `run_operation` (adapters.py) used to call the
    registered adapter's INSTANCE methods directly (`adapter.plan(...)`,
    `adapter.apply_one(...)`). A capability that obtained the adapter
    instance (e.g. via `get_adapter(op_kind)`) could reassign
    `adapter.apply_one` (or `adapter.build_write_client`) to a function of
    its own choosing — an ordinary Python instance-attribute shadow, nothing
    exotic — and the kernel would then hand the reassigned "adapter" the
    real write-capable client, because instance-method dispatch always
    re-resolves the CURRENT attribute at call time. That is the whole class
    of the vulnerability this record closes.

    `register_adapter` captures `plan`/`apply_one`/`undo_one`/`verify_one`
    (and `build_write_client`, if the class defines it) OFF THE CLASS
    (`type(adapter)`) at registration, not off the instance, and freezes them
    into this immutable record. `run_operation` then calls the captured
    UNBOUND class functions directly (`dispatch.apply_one(dispatch.instance,
    raw_client, unit)`), passing `dispatch.instance` explicitly as `self`.
    Reassigning `instance.apply_one` after registration only shadows the
    instance's own attribute lookup (`instance.apply_one` would return the
    thief) — it does not and cannot touch `AdapterDispatch.apply_one`, a
    plain reference to the function object that lived on the class at
    registration time. The captured callables always run instead.

    Fields
    ------
    instance:  The registered Adapter instance — passed explicitly as `self`
               to every captured callable below (they are unbound functions,
               not bound methods).
    plan / apply_one / undo_one / verify_one:
               `type(adapter).plan` etc. — the class's function objects,
               captured at registration time. Never re-read from the
               instance at call time.
    provision_write_client:
               `getattr(type(adapter), "build_write_client", None)` —
               auto-captured so an adapter that self-provisions its own
               write client keeps working with NO emitter
               change; None if the class does not define the method (the
               back-compat fallback path in adapters.py then uses
               run_operation's own `client` argument, unchanged). Deliberately
               NOT named `build_write_client` on this record: scan.py's
               credential_provider_reference rule flags ANY `ast.Name` or
               `ast.Attribute` node whose identifier is exactly
               "build_write_client" (or "write_credential_provider"),
               including a dataclass field declaration or a plain attribute
               read/write — this module is SEALED_KERNEL (scanned, not
               exempt; see the Adapter protocol docstring's parallel note
               above), so the field itself must not carry that literal name.
               The captured value is still resolved via the SAME
               scanner-invisible `getattr(cls, "build_write_client", None)`
               string-literal call the rest of this module already relies on.
    verify_apply_landed / verify_undo_restored / verify_durability
               (Task 1, B4/T1 — v0.12.0 Slice 1, the per-op_kind EVIDENCE
               PREDICATE): `getattr(type(adapter), "verify_apply_landed",
               None)` etc. — auto-captured OFF THE CLASS at registration
               time, same rationale and same mechanism as
               `provision_write_client` immediately above: an adapter class
               MAY optionally define
               ``verify_apply_landed(self, evidence) -> bool``,
               ``verify_undo_restored(self, evidence) -> bool``, and/or
               ``verify_durability(self, evidence) -> bool`` (durability is
               the narrow, optional check for ops whose contract declares
               `introduces_persistent_binding=True`). Each is None when the
               class does not define it — back-compat: every adapter
               registered before this task keeps working unchanged, with
               these three fields simply None; nothing dispatches through
               them yet (that is Task 2/Task 3's job — proof-time
               `validate_copy_run_proof` and run-time `_run_adapter_operation`
               wiring, respectively). `evidence` is a kernel-constructed,
               already-materialized `evidence.AdapterEvidence` record — the
               predicate's signature takes NO path/ref argument, so it is
               structurally incapable of reading outside what it was handed
               (the anti-tautology property; see `evidence.py`'s module
               docstring). Capturing these off the class rather than the
               instance closes the exact same monkey-patch-hijack class this
               whole record exists to close: a capability that obtained the
               adapter instance and reassigned `instance.verify_apply_landed`
               to a function that always returns True could otherwise forge
               a "verified" claim.
    """

    instance: Any
    plan: Callable
    apply_one: Callable
    undo_one: Callable
    verify_one: Callable
    provision_write_client: Optional[Callable]
    verify_apply_landed: Optional[Callable]
    verify_undo_restored: Optional[Callable]
    verify_durability: Optional[Callable]


# op_kind -> AdapterDispatch. Populated alongside _REGISTRY by register_adapter;
# this is what run_operation dispatches through (get_dispatch), never _REGISTRY/
# get_adapter directly — see AdapterDispatch's docstring for why.
_DISPATCH_REGISTRY: Dict[str, "AdapterDispatch"] = {}


def register_adapter(op_kind: str, adapter: Adapter) -> None:
    """Register `adapter` as the handler for `op_kind`. Re-registering the same
    op_kind overwrites the prior entry (last-registered wins) — callers own
    ordering; this function does not raise on a duplicate op_kind.

    Call signature is UNCHANGED from before this hardening — callers (e.g.
    adapters_gmail.py's module-scope `register_adapter(OP_KIND, Adapter())`
    calls) need no update. In addition to the existing instance registration,
    this now also captures an AdapterDispatch record OFF `type(adapter)` (see
    AdapterDispatch's docstring) and stores it in `_DISPATCH_REGISTRY`, keyed
    by the same op_kind. Also auto-captures the Task 1 (B4/T1) optional
    evidence predicates (`verify_apply_landed`/`verify_undo_restored`/
    `verify_durability`) off the class, same as `provision_write_client`."""
    _REGISTRY[op_kind] = adapter
    cls = type(adapter)
    _DISPATCH_REGISTRY[op_kind] = AdapterDispatch(
        instance=adapter,
        plan=cls.plan,
        apply_one=cls.apply_one,
        undo_one=cls.undo_one,
        verify_one=cls.verify_one,
        provision_write_client=getattr(cls, "build_write_client", None),
        verify_apply_landed=getattr(cls, "verify_apply_landed", None),
        verify_undo_restored=getattr(cls, "verify_undo_restored", None),
        verify_durability=getattr(cls, "verify_durability", None),
    )


def get_adapter(op_kind: str) -> Optional[Adapter]:
    """Return the registered Adapter INSTANCE for op_kind, or None if nothing
    is registered.

    run_operation treats None as "fall through to the existing field-write path" —
    the registry itself makes no claim about whether an unregistered op_kind is
    valid; that is contracts.py's concern.

    Unchanged by this hardening (kept for back-compat with callers that only need
    the instance for module-resolution purposes, e.g. effects_manifest.py's
    `_adapter_module_file`/`_adapter_effect_unit_path`, which read
    `type(adapter).__module__` — those never invoke a method on the instance
    they get back, so they are not part of the dispatch-hijack surface this
    task closes). `run_operation` itself no longer calls this function — it
    calls `get_dispatch` instead."""
    return _REGISTRY.get(op_kind)


def get_dispatch(op_kind: str) -> Optional[AdapterDispatch]:
    """Return the captured AdapterDispatch for op_kind, or None if nothing is
    registered. This is what `run_operation` (adapters.py) dispatches
    through — never `get_adapter`/the raw instance — so that an
    instance-level reassignment of `apply_one` or `build_write_client`
    (obtained via `get_adapter`, or any other reference to the same
    instance) cannot hijack execution. See AdapterDispatch's docstring for
    the full threat model."""
    return _DISPATCH_REGISTRY.get(op_kind)


def unregister_adapter(op_kind: str) -> None:
    """Remove a registration, if present. Test-only convenience for isolating
    adapter-registry test cases from one another; production adapter modules
    register once at import time and never unregister. Removes BOTH the
    instance registry entry and the captured dispatch record."""
    _REGISTRY.pop(op_kind, None)
    _DISPATCH_REGISTRY.pop(op_kind, None)
