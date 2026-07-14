"""Gate-wired-by-construction capability code scaffold emitter.

Why this exists
----------------
`add-capability` (wizard/skills/add-capability.md) designs a capability
in plain business language, then hands off to `next-phase` to build it. Before
this task, "build it" meant an agent freely authoring the capability's Python
from scratch — including, for a capability that touches an external system,
whatever adapter/credential/mutation code it thought the vendor needed. That is
exactly the shape the whole external-write-gate-generalization slice exists to
close off: a freely-authored capability can drift outside the gate (the
"own-your-safety" finding — the ONLY thing that caught a real bypass in
dogfooding was the Claude Code harness's auto-mode classifier, never the
emitted gate itself, because the emitted gate was never actually wired for
that capability).

This module is the fix for the BUILD side of that gap: a deterministic,
template-driven emitter that turns a small, typed `CapabilityCodeSpec` (the
op_kind + vendor read-only scope + blast-radius cap the design phase already
settled — see add-capability.md Steps C/D) into THREE files that are ALREADY
gate-wired, by construction, before a single line is hand-authored (this
rewired the emitter from two files to three, mirroring the reference split
proven by `read_facades_gmail.py`):

  1. An **adapter module** (the ADAPTER_PROFILE trust zone) —
     `agents/lib/external_write/adapters_<capability_id>.py`. Registers a
     `contracts.OperationContract` (declaring op_kind + read_only_scope +
     blast_radius_cap + risk_class — this task's requirement 1) and an
     `adapter_registry.Adapter` (plan/apply_one/undo_one/verify_one) at
     module scope — the SAME self-registering convention `adapters_gmail.py`
     already established. Its filename is appended to the
     capability-added registry `zones.py` reads (see
     `zones.effective_adapter_profile_paths` / `_load_extra_adapter_profile_paths`),
     so the module is a recognized
     ADAPTER_PROFILE member the moment it is written, with NO hand-edit of
     `zones.py`'s source required. It no longer defines a ReadFacade
     subclass at all (see item 2) — the ONLY thing this module's write
     credential is reachable from.
  2. A **read-facade module** (SCANNED, NOT ADAPTER_PROFILE) —
     `agents/lib/external_write/read_facades_<capability_id>.py`. Defines
     ONLY the `<Prefix>ReadFacade` subclass and registers it against the
     kernel registry (`read_facade.register_read_facade`) at module scope.
     Imports ONLY `ReadFacade` + `register_read_facade` from
     `external_write.read_facade` — no vendor SDK, no Adapter class, no
     `build_write_client`, no credential of any kind. Deliberately left OUT
     of both zone allowlists (fail-closed default: CAPABILITY), which is
     fine because it scans clean on its own merits — the same shape
     `read_facades_gmail.py` already proved.
  3. A **capability module** (the CAPABILITY trust zone) —
     `agents/capabilities/<capability_id>_capability.py`. Imports ONLY the
     curated kernel surface — `external_write.capability_api`
     (`run_enveloped_operation` + `build_read_facade`) and
     `external_write.operations`
     (pure data) — never a vendor SDK, never the adapter module, never the
     adapter registry, never the concrete `<Prefix>ReadFacade` class, and
     never the raw `run_operation` primitive. It
     resolves its read facade via `build_read_facade(op_kind,
     read_only_client)` (the two-arg, kernel-registry-resolved form — the
     concrete subclass is found via the read-facade module's registration,
     not by import), and cannot even NAME a write-credential provider. It
     routes any actual write through `capability_api.run_enveloped_operation`
     (under a ceremony-minted RunEnvelope — so the run-level protections apply
     by construction), which internally resolves the write-capable client from
     the registered adapter's `build_write_client` method (the
     credential-isolation keystone — enforced deterministically by scan.py's
     credential_provider_reference rule, and the raw_run_operation_reference
     rule that flags any capability reaching raw run_operation, not by a
     comment convention).

The structural point of the three-way split: before this rewiring, the
capability module imported its `<Prefix>ReadFacade` class from the SAME
adapter module that defines `build_write_client` — giving capability code a
legitimate-looking reason to be in that module's import graph, and a
capability that recovered `facade.__class__.__module__` landed on a module
that ALSO holds write-capable adapter code. Now the capability module's
entire `external_write` import surface is the curated
`capability_api`/`operations` pair, and a facade recovered via
`__class__.__module__` lands on the credential-free read-facade module
instead.

Both emitted files are runnable/importable stubs — `plan`/`apply_one`/
`undo_one`/`verify_one` and the adapter's `build_write_client` raise
`NotImplementedError` with a plain TODO pointing at the one thing that still
needs a human decision (the actual per-vendor call shape) — but the GATE
WIRING itself (contract declaration, adapter registration, zone membership,
credential isolation, no-vendor-import) is complete and verified BEFORE
next-phase ever touches the capability. The acceptance test for this module
(`test_capability_code_scaffold.py`) proves the emitted pair passes
`external_write.scan.scan_paths` — the build-time gate — by
construction, with zero manual wiring.

Boundary discipline (same as every other build-side module that
touches the external_write package): this module lives in `wizard/scripts/lib`
(the wizard TOOLKIT engine) and WRITES INTO the operator project's
`agents/lib/external_write/` and `agents/capabilities/` directories; it does
not itself import from the `external_write` package (it only emits Python
source text for it) and it is invoked from the wizard toolkit, not from
inside the operator's own trust-boundary code.

Stdlib only — no third-party dependencies.
"""

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Dict, List, Optional, Tuple


_VALID_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Default op_kind contract fields shared with every seeded/reference contract in
# contracts.py (see contracts.WRITE_AFFECTING_MODULES) — the shared plumbing every
# op_kind's implementation_hash covers regardless of whether it has its own adapter.
_DEFAULT_VERIFIER_SET: Tuple[str, ...] = ("operator_attested_v1",)


class CapabilityCodeScaffoldError(Exception):
    """Raised when a CapabilityCodeSpec is malformed, or when emission cannot
    complete cleanly. Fail-closed: never emit a partial or structurally
    unsound scaffold."""


@dataclass(frozen=True)
class CapabilityCodeSpec:
    """Everything the emitter needs to render a gate-wired capability pair.

    Every field here is something add-capability's design phase (Steps C/D)
    already settles in plain language before this emitter is ever invoked —
    this dataclass is the typed handoff from that design to this deterministic
    build step, not a new set of questions for the operator.

    Attributes
    ----------
    capability_id:      Lowercase identifier (``^[a-z][a-z0-9_]*$``) — becomes
                        both file-name and class-name material. When this
                        capability migrates a mechanism upgrade-reconcile that
                        was safe-paused, this MUST equal that mechanism's
                        ``mechanism_id`` (see operator_acceptance.
                        close_pending_migration_if_matched) so acceptance can
                        close the pending-migration entry automatically.
    display_name:       Plain-language name (docstrings/comments only).
    op_kind:            The named operation kind this capability registers
                        (e.g. ``"acme.record.archive"``).
    surface:            External-system identifier (e.g. ``"acme_crm"``).
    read_only_scope:    The vendor read-only scope the ReadFacade is built
                        against (e.g. ``"gmail.readonly"``). Required — an
                        op_kind with none is ineligible for the ReadFacade
                        safety model (read_facade.py).
    blast_radius_cap:   Positive int — the per-window invocation cap.
    risk_class:         One of contracts.RISK_CLASSES (checked at emit time).
    writes:             Field/range(s) this op is allowed to change.
    read_methods:       Read-only method names the ReadFacade subclass
                        declares (at least one).
    verifier_set:       Accepted post-write verifier ids.
    introduces_persistent_binding: Whether this op creates a standing binding
                        (durability-check trigger — see contracts.py).
    requires_accepted_phase: Whether a covering ACCEPTED phase is required
                        before a live write (True by default — a freshly
                        emitted capability starts gated).
    """

    capability_id: str
    display_name: str
    op_kind: str
    surface: str
    read_only_scope: str
    blast_radius_cap: int
    risk_class: str = "sensitive_data"
    writes: Tuple[str, ...] = ("__record__",)
    read_methods: Tuple[str, ...] = ("list_items", "get_item")
    verifier_set: Tuple[str, ...] = _DEFAULT_VERIFIER_SET
    introduces_persistent_binding: bool = False
    requires_accepted_phase: bool = True

    def __post_init__(self) -> None:
        if not (isinstance(self.capability_id, str) and _VALID_ID_RE.match(self.capability_id)):
            raise CapabilityCodeScaffoldError(
                f"capability_id {self.capability_id!r} must match "
                f"^[a-z][a-z0-9_]*$ -- it becomes a Python module/class name")
        if not (isinstance(self.display_name, str) and self.display_name.strip()):
            raise CapabilityCodeScaffoldError("display_name must be a non-empty string")
        if not (isinstance(self.op_kind, str) and self.op_kind.strip()):
            raise CapabilityCodeScaffoldError("op_kind must be a non-empty string")
        if not (isinstance(self.surface, str) and self.surface.strip()):
            raise CapabilityCodeScaffoldError("surface must be a non-empty string")
        if not (isinstance(self.read_only_scope, str) and self.read_only_scope.strip()):
            raise CapabilityCodeScaffoldError(
                "read_only_scope must be a non-empty string -- an op_kind with no "
                "declared read-only scope is ineligible for the ReadFacade "
                "credential-isolation safety model (read_facade.py)")
        if not (isinstance(self.blast_radius_cap, int)
                and not isinstance(self.blast_radius_cap, bool)
                and self.blast_radius_cap > 0):
            raise CapabilityCodeScaffoldError("blast_radius_cap must be a positive integer")
        if not self.read_methods or not all(
                isinstance(m, str) and _VALID_ID_RE.match(m) for m in self.read_methods):
            raise CapabilityCodeScaffoldError(
                "read_methods must declare at least one identifier-safe read method name")

    @property
    def class_prefix(self) -> str:
        """PascalCase class-name prefix derived from capability_id, e.g.
        'acme_row_sync' -> 'AcmeRowSync'."""
        return "".join(part.capitalize() for part in self.capability_id.split("_"))

    @property
    def adapter_module_stem(self) -> str:
        return f"adapters_{self.capability_id}"

    @property
    def read_facade_module_stem(self) -> str:
        """The split-out read-facade module's filename stem,
        mirroring the reference `read_facades_gmail.py` naming."""
        return f"read_facades_{self.capability_id}"

    @property
    def capability_module_stem(self) -> str:
        return f"{self.capability_id}_capability"


# ---------------------------------------------------------------------------
# Adapter module (ADAPTER_PROFILE zone) template
# ---------------------------------------------------------------------------

_ADAPTER_MODULE_TEMPLATE = Template('''"""${display_name} — adapter module (ADAPTER_PROFILE trust zone).

GENERATED by wizard/scripts/lib/capability_code_scaffold.py for the
"${capability_id}" capability, via add-capability's build cascade. This is the
ONLY module for this capability allowed to import a vendor SDK, construct or
obtain a write-capable credential, and perform a raw vendor mutation -- see
zones.py for the full trust-zone rationale. Its relative filename is
registered in the sibling adapter_profile_registry.json (never hand-edited
into zones.py's source) so it is recognized as ADAPTER_PROFILE the moment
this file is written.

This module deliberately does NOT define this capability's ReadFacade
subclass (mirrors the reference split in read_facades_gmail.py): that class lives in the sibling
${read_facade_module_stem}.py, a SCANNED module with no adapter and no
credential in it, so a capability that recovers
`facade.__class__.__module__` never lands here.

TODO (next-phase / a human decision, not this emitter's job): the plan /
apply_one / undo_one / verify_one bodies below are structural stubs -- they
declare the SHAPE the gate requires (one EffectUnit per discrete mutation;
undo restores the prior state) but not the real per-vendor call. Fill those
in against the real ${surface} API. Do NOT add a send/forward/permanent-delete
path unless the design in vision.md/execution_plan.md explicitly calls for it
-- see adapters_gmail.py's "Structural safety -- held by ABSENCE of code"
section for the pattern to follow.

TODO (turnkey-honesty note, also next-phase / a human decision): this
generated class does NOT yet declare ``verify_apply_landed`` /
``verify_undo_restored`` -- the two evidence predicates
adapter_registry.AdapterDispatch resolves via ``getattr(cls, ..., None)`` and
copy_run_proof.py REQUIRES (refuses with "no ... evidence predicate" when
either is None). Add both methods to ${class_prefix}Adapter below, each
taking the ``AdapterEvidence`` ``verify_one`` observed and returning bool --
see adapters_gmail.py's own ``verify_apply_landed``/``verify_undo_restored``
for the reference shape -- BEFORE a copy-run proof for this capability can
validate and operator-acceptance can accept it for live use.
"""

from typing import Any, List, Optional

from external_write.adapter_registry import register_adapter
from external_write.contracts import (
    OperationContract, WRITE_AFFECTING_MODULES, register_contract,
)
from external_write.operations import EffectUnit


OP_KIND = "${op_kind}"


# ---------------------------------------------------------------------------
# Contract registration -- declares op_kind + read_only_scope + blast_radius_cap
# at import time, module scope, exactly like
# adapter_registry.register_adapter's own established convention.
# ---------------------------------------------------------------------------

register_contract(OperationContract(
    op_kind=OP_KIND,
    writes=${writes},
    produces=(),
    dependency_set=WRITE_AFFECTING_MODULES,
    verifier_set=${verifier_set},
    introduces_persistent_binding=${introduces_persistent_binding},
    risk_class=${risk_class},
    requires_accepted_phase=${requires_accepted_phase},
    blast_radius_cap=${blast_radius_cap},
    read_only_scope=${read_only_scope},
))


# ---------------------------------------------------------------------------
# Adapter -- plan/apply_one/undo_one/verify_one (adapter_registry.Adapter protocol).
# ---------------------------------------------------------------------------

class ${class_prefix}Adapter:
    """Adapter for '${op_kind}'. See the module TODO -- apply_one/undo_one/
    verify_one are structural stubs; plan() is pure (no read, no write) per
    the Adapter protocol's ordering guarantee (adapter_registry.py).

    build_write_client (the credential-isolation keystone) is the ONLY
    place this capability's write-capable credential may be constructed.
    run_operation (adapters.py) calls it ITSELF, INSIDE the adapter execution
    path, keyed by this registered adapter -- never by capability-zone code,
    which cannot even NAME it (enforced by scan.py's
    credential_provider_reference rule). Because it is a METHOD on this
    ADAPTER_PROFILE-zone adapter (not an importable module-level symbol), there
    is no provider name for the CAPABILITY zone to reach."""

    def build_write_client(self, op: Any) -> Any:
        raise NotImplementedError(
            "TODO: construct/obtain the write-capable ${surface} credential/client here "
            "(this method is the ONLY legal place to do so for this capability) "
            "and return it. Called by run_operation inside the adapter execution "
            "path, never by capability code.")

    def plan(self, params: Optional[dict]) -> List[EffectUnit]:
        params = params or {}
        units: List[EffectUnit] = []
        for item in params.get("items", []):
            item_id = item["item_id"]
            units.append(EffectUnit(
                unit_id=item_id,
                target_ref={"item_id": item_id, "params": item},
                undo_ref={"item_id": item_id, "prior_state": item.get("prior_state")},
            ))
        return units

    def apply_one(self, raw_client: Any, unit: EffectUnit) -> None:
        raise NotImplementedError(
            "TODO: perform the one real ${surface} mutation for "
            f"{unit.unit_id!r} against raw_client here.")

    def undo_one(self, raw_client: Any, unit: EffectUnit) -> None:
        raise NotImplementedError(
            "TODO: reverse the mutation for "
            f"{unit.unit_id!r} against raw_client here (restore unit.undo_ref).")

    def verify_one(self, observer: Any, unit: EffectUnit) -> Any:
        # READ-ONLY OBSERVER (run-time verification): `observer` is the
        # READ-ONLY facade the kernel builds for this op_kind -- NEVER the
        # write-capable client apply_one/undo_one receive. Observe this unit's
        # current state and return an opaque poststate mapping that this
        # adapter's verify_apply_landed predicate can evaluate. Reading the
        # write-capable client here would defeat credential isolation.
        raise NotImplementedError(
            "TODO: OBSERVE the live state for "
            f"{unit.unit_id!r} via the read-only `observer` (never a "
            "write-capable client) and return a poststate mapping "
            "verify_apply_landed can check.")

    # TODO (turnkey-honesty note -- see the module docstring's matching TODO):
    # add verify_apply_landed(self, evidence) -> bool and
    # verify_undo_restored(self, evidence) -> bool methods HERE, evaluating the
    # poststate verify_one observed above. Until both exist, copy_run_proof.py
    # refuses this capability's proof with "no ... evidence predicate" and
    # operator-acceptance can never accept it for live use -- see
    # adapters_gmail.py for the reference implementation shape.


register_adapter(OP_KIND, ${class_prefix}Adapter())


# ---------------------------------------------------------------------------
# Read-only client -- scoped to the declared read-only scope; NOT write-capable.
# The write-capable credential is built only by ${class_prefix}Adapter.
# build_write_client above (the ONE legal place), reached only by run_operation
# inside the adapter execution path.
# ---------------------------------------------------------------------------

def build_read_only_client() -> Any:
    raise NotImplementedError(
        "TODO: construct/obtain a client scoped to the read-only scope "
        "${read_only_scope} here and return it.")
''')

_READ_METHOD_BODY_TEMPLATE = Template('''    def ${method_name}(self, *args: Any, **kwargs: Any) -> Any:
        return self._read("${method_name}", *args, **kwargs)
''')


def render_adapter_module(spec: CapabilityCodeSpec) -> str:
    """Render the ADAPTER_PROFILE-zone module source for `spec`. Pure string
    rendering -- no filesystem I/O, no import of the rendered code."""
    return _ADAPTER_MODULE_TEMPLATE.substitute(
        display_name=spec.display_name,
        capability_id=spec.capability_id,
        surface=spec.surface,
        op_kind=spec.op_kind,
        class_prefix=spec.class_prefix,
        writes=repr(tuple(spec.writes)),
        verifier_set=repr(tuple(spec.verifier_set)),
        introduces_persistent_binding=repr(bool(spec.introduces_persistent_binding)),
        risk_class=repr(spec.risk_class),
        requires_accepted_phase=repr(bool(spec.requires_accepted_phase)),
        blast_radius_cap=repr(int(spec.blast_radius_cap)),
        read_only_scope=repr(spec.read_only_scope),
        read_facade_module_stem=spec.read_facade_module_stem,
    )


# ---------------------------------------------------------------------------
# Read-facade module (SCANNED zone, NOT ADAPTER_PROFILE) template
# — mirrors the reference split in read_facades_gmail.py. Holds
# ONLY the ReadFacade subclass; imports ONLY ReadFacade + register_read_facade
# from the kernel read_facade module; no vendor SDK, no Adapter class, no
# build_write_client, no credential of any kind. Registers itself against the
# kernel registry at module scope, so build_read_facade(op_kind, client) (the
# two-arg, capability-facing form) resolves it once this module has been
# imported at least once in the running process.
# ---------------------------------------------------------------------------

_READ_FACADE_MODULE_TEMPLATE = Template('''"""${display_name} — read-only facade module (SCANNED zone, NOT
ADAPTER_PROFILE).

GENERATED by wizard/scripts/lib/capability_code_scaffold.py for the
"${capability_id}" capability, mirroring the reference split in
read_facades_gmail.py. This module imports ONLY ``ReadFacade`` + ``register_read_facade``
from ``external_write.read_facade`` (the kernel) -- no vendor SDK import, no
Adapter class, no ``build_write_client``, no credential/provisioner of any
kind.

It is NOT listed in either of zones.py's allowlists (SEALED_KERNEL /
ADAPTER_PROFILE), so it defaults to the fail-closed CAPABILITY
classification -- which is fine here, because it contains nothing that trips
scan.py's checks (see test_capability_code_scaffold.py's zone-clean golden
emit tests). A capability that recovers `facade.__class__.__module__` for
'${op_kind}' lands HERE -- a module with no adapter and no credential
anywhere in it -- never on ${adapter_module_stem}.py, which defines this
capability's write-capable Adapter.

The op_kind string below is deliberately DUPLICATED from the adapter module's
own OP_KIND constant, not imported from it -- importing anything from the
adapter module, even a harmless string literal, would re-create exactly the
coupling this split exists to remove.
"""

from typing import Any

from external_write.read_facade import ReadFacade, register_read_facade


OP_KIND = "${op_kind}"


class ${class_prefix}ReadFacade(ReadFacade):
    """Read-only facade for '${op_kind}', built against ${read_only_scope}."""

    read_methods = ${read_methods}

${read_method_bodies}

register_read_facade(OP_KIND, ${class_prefix}ReadFacade)
''')


def render_read_facade_module(spec: CapabilityCodeSpec) -> str:
    """Render the SCANNED (non-ADAPTER_PROFILE) read-facade module source for
    `spec`. Pure string rendering -- no filesystem I/O, no import of the
    rendered code."""
    read_method_bodies = "\n".join(
        _READ_METHOD_BODY_TEMPLATE.substitute(method_name=m) for m in spec.read_methods
    )
    return _READ_FACADE_MODULE_TEMPLATE.substitute(
        display_name=spec.display_name,
        capability_id=spec.capability_id,
        adapter_module_stem=spec.adapter_module_stem,
        op_kind=spec.op_kind,
        class_prefix=spec.class_prefix,
        read_only_scope=repr(spec.read_only_scope),
        read_methods=repr(tuple(spec.read_methods)),
        read_method_bodies=read_method_bodies,
    )


# ---------------------------------------------------------------------------
# Capability module (CAPABILITY zone) template — imports ONLY the
# curated kernel surface (external_write.capability_api's run_enveloped_operation
# + build_read_facade, and external_write.operations' pure data types) — never
# the adapter module, never the adapter registry, never the concrete
# ReadFacade subclass, and never the raw run_operation primitive. No vendor
# import, no write credential, no client re-stash, and no importable
# credential-provider symbol to reach; reads only via the facade
# capability_api.build_read_facade resolves from the kernel registry (populated
# by the sibling read_facades_<capability_id>.py module at import time); routes
# any write through capability_api.run_enveloped_operation (under a
# ceremony-minted RunEnvelope), which enforces the run-level envelope checks
# and internally resolves the write client from the registered adapter's
# build_write_client method.
# ---------------------------------------------------------------------------

_CAPABILITY_MODULE_TEMPLATE = Template('''"""${display_name} — capability module (CAPABILITY trust zone).

GENERATED by wizard/scripts/lib/capability_code_scaffold.py for the
"${capability_id}" capability.

Structural safety -- held by ABSENCE of code, not a runtime check (mirrors
adapters_gmail.py's own "Structural safety" section): this module never
imports a vendor SDK, never constructs or references a write-capable
credential, and never calls anything shaped like a raw vendor mutation. Its
ENTIRE external_write import surface is the curated kernel surface --
``external_write.capability_api`` (``run_enveloped_operation`` +
``build_read_facade``)
and ``external_write.operations`` (pure data) -- it never imports
${adapter_module_stem}.py, the adapter registry, ``get_adapter``, the raw
``run_operation`` primitive, or the
concrete ${class_prefix}ReadFacade class (see
${read_facade_module_stem}.py, which registers that class against the kernel
read-facade registry at import time; ``build_read_facade`` resolves it from
there, keyed by op_kind, so this module never needs to name it at all).

It cannot even NAME a write-credential provider: the write-capable credential
is built solely by the adapter module's ${class_prefix}Adapter.build_write_client,
resolved INTERNALLY inside the adapter execution path (run_enveloped_operation
calls the kernel primitive, which resolves it) -- enforced deterministically
by scan.py's credential_provider_reference rule, not by a comment convention.

NOTE for whoever wires this capability's entrypoint together: `build_facade`
below requires ${read_facade_module_stem}.py to have been imported at least
once in the running process (its module-scope `register_read_facade` call is
what populates the kernel registry `build_read_facade` resolves from) --
`build_read_facade` fails closed (raises ReadFacadeEligibilityError) if it
has not been.

TODO (a human/next-phase decision, not this emitter's job): propose_operations
below is a structural stub -- it shows the SHAPE (read via the facade, build
Operation objects with real params) but the actual "what changed, what should
this capability propose" logic is domain-specific and is filled in against
the real design in vision.md / execution_plan.md.
"""

from typing import Any, List, Optional

from external_write.capability_api import build_read_facade, run_enveloped_operation
from external_write.operations import Operation, SCHEMA_V2_ACTION


OP_KIND = "${op_kind}"
SURFACE = "${surface}"


def build_facade(read_only_client: Any) -> Any:
    """Build this capability's read-only facade via the kernel registry (the
    two-arg, capability-facing form -- the concrete subclass is resolved by
    ``build_read_facade`` from the registry ${read_facade_module_stem}.py
    populates at import time, never imported here by name). `read_only_client`
    must already be scoped to ${read_only_scope} by its caller (see the
    adapter module's build_read_only_client)."""
    return build_read_facade(OP_KIND, read_only_client)


def propose_operations(facade: Any, batch_id: str) -> List[Operation]:
    """TODO: read via `facade` (its declared read methods only) and return the
    Operation(s) this capability proposes. Structural stub -- returns no
    operations until the real per-capability logic is filled in."""
    raise NotImplementedError(
        "TODO: read via facade and build the real Operation params for "
        "'${op_kind}' here.")


def run_approved(envelope: Any, op: Operation, receipt: Any, *,
                 target: str = "live", descriptor_set: Any = None,
                 cap_ledger: Any = None) -> Any:
    """Execute an already-approved Operation UNDER a ceremony-minted
    RunEnvelope -- the ONLY sanctioned CAPABILITY live-write path. Routing
    through run_enveloped_operation (never the raw run_operation primitive)
    is what enforces the run-level protections by construction:
    disk-authoritative envelope spendability, consent-receipt binding,
    APPLY-BY-ID against the frozen reviewed_set, and the AGGREGATE CEILING.
    (scan.py's raw_run_operation_reference rule deterministically flags any
    capability that reaches raw run_operation instead.)

    Passes NO write-credential provider -- this capability zone cannot obtain
    one. run_enveloped_operation calls the kernel primitive internally, which
    resolves the write-capable client keyed by the registered adapter
    (${class_prefix}Adapter.build_write_client), inside the adapter execution
    path, only once dispatch is committed. Returns
    (updated_envelope, result)."""
    return run_enveloped_operation(
        envelope, op, receipt, None,
        target=target, descriptor_set=descriptor_set, cap_ledger=cap_ledger,
    )
''')


def render_capability_module(spec: CapabilityCodeSpec) -> str:
    """Render the CAPABILITY-zone module source for `spec`. Pure string
    rendering -- no filesystem I/O, no import of the rendered code."""
    return _CAPABILITY_MODULE_TEMPLATE.substitute(
        display_name=spec.display_name,
        capability_id=spec.capability_id,
        surface=spec.surface,
        op_kind=spec.op_kind,
        class_prefix=spec.class_prefix,
        adapter_module_stem=spec.adapter_module_stem,
        read_facade_module_stem=spec.read_facade_module_stem,
        read_only_scope=repr(spec.read_only_scope),
    )


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

DEFAULT_EXTERNAL_WRITE_REL = Path("agents") / "lib" / "external_write"
DEFAULT_CAPABILITIES_REL = Path("agents") / "capabilities"
ADAPTER_PROFILE_REGISTRY_BASENAME = "adapter_profile_registry.json"

# Task 7 (A4 / F-37, v0.13.0 Slice 2): the build-emitted static adapter
# registry `operator_acceptance.py` imports at module scope so the operator-
# acceptance CLI is turnkey for a freshly-declared capability -- see
# registered_adapters.py's own module docstring for the full rationale. This
# emitter regenerates it (idempotently, appending one import line) the same
# way it already regenerates ADAPTER_PROFILE_REGISTRY_BASENAME above.
REGISTERED_ADAPTERS_BASENAME = "registered_adapters.py"

# The baseline content this emitter creates the file WITH if it is not
# already present. Only used as a fallback for a project whose lib files
# were not yet copied in; a real operator project already has this file
# (lib-emitted) before any capability is ever added, so the normal path is
# "read existing content, append one import line".
#
# CROSS-REFERENCE (single-source-of-truth discipline): this string is a
# VERBATIM copy of the real, hand-maintained
# agents/lib/external_write/registered_adapters.py shipped by Task 7 (A4 /
# F-37, v0.13.0 Slice 2) -- duplicated here, not imported, per this module's
# own boundary discipline (it does not import from the external_write
# package -- AST/text only, mirroring _extract_registered_op_kinds above).
# If registered_adapters.py's docstring or import line ever changes, update
# THIS constant to match in the same commit (registered_adapters.py's own
# module docstring carries the mirror-image pointer back to here) -- a test
# in test_capability_code_scaffold.py pins byte-equality between the two so
# a missed update fails closed rather than silently drifting.
_REGISTERED_ADAPTERS_BASELINE = '''"""Static adapter-registration import list — the build-emitted static adapter
registry (Task 7, A4 / F-37 — v0.13.0 Slice 2).

The problem this closes
------------------------
`adapter_registry.register_adapter` and `contracts.register_contract` both
fire at IMPORT of an adapter module (a module-scope call — see
`adapters_gmail.py`'s own registration block, and the per-capability adapter
module `capability_code_scaffold.py` emits). `get_contract(op_kind)` and
`adapter_registry.get_dispatch(op_kind)` — the two lookups the operator-
acceptance ceremony needs to compute an operation's trust hashes — resolve
correctly ONLY after that specific adapter module has been imported at least
once in the running process.

Before this module existed, NOTHING imported a capability's adapter module on
the operator-acceptance CLI's path (`operator_acceptance.py`'s `__main__` /
`record_operator_acceptance`) — the CLI is invoked fresh, per the documented
usage in `skills/next-phase.md`'s Step 6, and a freshly-declared capability's
adapter module was never on that fresh process's import graph. The result:
the prescribed operator-acceptance command refused EVERY freshly-declared
capability with "no registered contract for op_kind ..." — a real,
plain-language refusal, not a crash, but one that made the promised turnkey
acceptance flow simply not work out of the box for anything beyond the
already-import-triggered case, with no operator-facing (or CLI-flag) way to
fix it, because the fix requires an IMPORT, not an argument.

The fix
-------
Importing THIS ONE module fires every shipped and every capability-added
adapter module's module-scope registration, in one place, before any op_kind
resolution is attempted. `operator_acceptance.py` imports it at module scope
(so both the `__main__` CLI wrapper and `record_operator_acceptance`, its
underlying runner, get the fix regardless of which one is invoked) — see that
module's own docstring for the BI-2 pre-check this enables.

No operator-controlled import string
-------------------------------------
There is deliberately no CLI flag or descriptor field naming an adapter
module to import (the descriptor's `ENTRY_KEYS` — capability_registration.
REGISTERED_ENTRY_KEYS — are unchanged by this task; op_kind is read from the
copy_run_proof, never from the descriptor, and no descriptor field names an
adapter module either). The import set is entirely build-emitted and static:
whichever adapter modules are LISTED HERE are the only ones that can ever
register — a bare-metal allowlist, not a dynamically resolved string an
operator or a model-authored value could redirect.

GENERATED shape
----------------
For the shipped substrate this is a hand-maintained module enumerating the
shipped ADAPTER_PROFILE modules (today: `adapters_gmail.py`, the one
reference adapter). `wizard/scripts/lib/capability_code_scaffold.py`'s
`emit_capability_code_scaffold` regenerates it (idempotently, appending one
import line) whenever a capability adapter is added via the add-capability
build cascade — mirroring exactly how it already regenerates the sibling
`adapter_profile_registry.json` — and asserts, BEFORE writing, that the
newly-added module's op_kind does not collide with any op_kind already
registered by a module already listed here (see
`capability_code_scaffold._update_registered_adapters` /
`_extract_registered_op_kinds`).

Importing this module has side effects (registration at import time) — that
IS the point; see `adapter_registry.py`'s own module docstring ("populated by
`register_adapter` at import time").

Cross-reference (single-source-of-truth discipline): `wizard/scripts/lib/
capability_code_scaffold.py`'s `_REGISTERED_ADAPTERS_BASELINE` duplicates
this module's ENTIRE source (this docstring + the import line below)
VERBATIM as its fallback-content constant (used only when a target project's
copy of this file does not exist yet) -- that module's own boundary
discipline forbids importing this package to derive it live, so it is text,
not code. If this docstring or the import line changes, update that constant
to match in the same commit -- a byte-equality test in
test_capability_code_scaffold.py pins the two together so a missed update
fails closed rather than silently drifting.

Stdlib only — no third-party dependencies.
"""

import external_write.adapters_gmail  # noqa: F401 -- registers the 4 shipped Gmail op_kinds.
'''


_REGISTERED_ADAPTERS_IMPORT_RE = re.compile(
    r"^import external_write\.(\w+)\s*(?:#.*)?$", re.MULTILINE)


def _extract_registered_op_kinds(source: str, module_label: str) -> List[str]:
    """Statically extract every op_kind string passed to a module-scope
    ``register_adapter(op_kind, ...)`` call in `source`, WITHOUT executing
    it (this module must not import the external_write package -- see its
    own boundary-discipline note in the module docstring). Resolves a simple
    ``NAME = "literal"`` module-level constant used as the call's first
    argument (the shape both adapters_gmail.py and this emitter's own
    generated adapter modules use); a first argument this cannot resolve to
    a literal string is a scaffold-generation failure, surfaced plainly
    (never a raw traceback further downstream)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise CapabilityCodeScaffoldError(
            f"could not parse {module_label} to check for duplicate op_kind "
            f"registrations -- fix step: ensure {module_label} is valid "
            f"Python ({e})")

    string_constants: Dict[str, str] = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            string_constants[node.targets[0].id] = node.value.value

    op_kinds: List[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "register_adapter" and node.args):
            continue
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
            op_kinds.append(arg0.value)
        elif isinstance(arg0, ast.Name) and arg0.id in string_constants:
            op_kinds.append(string_constants[arg0.id])
        else:
            raise CapabilityCodeScaffoldError(
                f"{module_label} calls register_adapter(...) with an op_kind "
                "argument this scaffold cannot statically resolve to a "
                "literal string -- fix step: declare the op_kind as a simple "
                "NAME = \"literal\" module-level constant (as adapters_gmail.py "
                "and this emitter's own template both do), or pass a literal "
                "string directly")
    return op_kinds


def _assert_no_duplicate_op_kind(external_write_dir: Path, new_module_stem: str,
                                 new_op_kind: str) -> None:
    """Pure validation (no writes) for AC-T7/BI-1: raise a plain-language,
    resumable ``CapabilityCodeScaffoldError`` iff `new_op_kind` collides with
    an op_kind any adapter module ALREADY listed in
    ``<external_write_dir>/registered_adapters.py`` registers. Deliberately
    called BEFORE this emitter writes anything for the new capability (see
    `emit_capability_code_scaffold`), so a collision never leaves a partial
    emit behind (the new capability's own trio of files, and its entry in
    ``adapter_profile_registry.json``, are never written on this path).

    Re-emitting the SAME capability's own module (`new_module_stem` already
    listed) is a no-op here -- never a duplicate-op_kind error against
    itself; the idempotent re-write is `_update_registered_adapters`'s job.

    A listed import whose module file is not present locally is skipped
    (nothing to statically verify against) rather than treated as an error
    -- this emitter only ever WRITES the capability's own adapter file into
    `external_write_dir`; the shared lib files (including adapters_gmail.py)
    are copied in by a separate emission step this module does not perform
    (see this module's own boundary-discipline note), so a test harness that
    exercises only THIS emitter in isolation legitimately has no local copy
    of e.g. adapters_gmail.py to check against.
    """
    registry_path = external_write_dir / REGISTERED_ADAPTERS_BASENAME
    content = (registry_path.read_text(encoding="utf-8") if registry_path.is_file()
               else _REGISTERED_ADAPTERS_BASELINE)
    existing_modules = _REGISTERED_ADAPTERS_IMPORT_RE.findall(content)

    if new_module_stem in existing_modules:
        return

    seen: Dict[str, str] = {}
    for mod_stem in existing_modules:
        mod_path = external_write_dir / f"{mod_stem}.py"
        if not mod_path.is_file():
            continue
        mod_label = f"{mod_stem}.py"
        for op_kind in _extract_registered_op_kinds(
                mod_path.read_text(encoding="utf-8"), mod_label):
            if op_kind in seen and seen[op_kind] != mod_label:
                raise CapabilityCodeScaffoldError(
                    f"op_kind {op_kind!r} is registered by BOTH {seen[op_kind]} "
                    f"and {mod_label} -- fix step: give one of these two "
                    "adapters a distinct op_kind before regenerating "
                    f"{REGISTERED_ADAPTERS_BASENAME}")
            seen[op_kind] = mod_label

    if new_op_kind in seen:
        raise CapabilityCodeScaffoldError(
            f"op_kind {new_op_kind!r} is already registered by "
            f"{seen[new_op_kind]} -- fix step: choose a distinct op_kind for "
            f"the new {new_module_stem}.py adapter")


def _update_registered_adapters(external_write_dir: Path, new_module_stem: str,
                                new_op_kind: str) -> Path:
    """Idempotently add ``import external_write.<new_module_stem>`` to
    ``<external_write_dir>/registered_adapters.py`` (creating it from the
    baseline if absent). Assumes `_assert_no_duplicate_op_kind` has ALREADY
    been called for this exact `(new_module_stem, new_op_kind)` pair (see
    `emit_capability_code_scaffold`, which validates before writing anything)
    -- re-asserted here too (cheap; the file has not changed in between in
    the normal call path) so this function is safe to call standalone.
    """
    _assert_no_duplicate_op_kind(external_write_dir, new_module_stem, new_op_kind)

    registry_path = external_write_dir / REGISTERED_ADAPTERS_BASENAME
    content = (registry_path.read_text(encoding="utf-8") if registry_path.is_file()
               else _REGISTERED_ADAPTERS_BASELINE)
    existing_modules = _REGISTERED_ADAPTERS_IMPORT_RE.findall(content)

    if new_module_stem in existing_modules:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not registry_path.is_file():
            registry_path.write_text(content, encoding="utf-8")
        return registry_path

    content = content.rstrip("\n") + "\n" + f"import external_write.{new_module_stem}  # noqa: F401\n"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(content, encoding="utf-8")
    return registry_path


def _update_adapter_profile_registry(external_write_dir: Path, new_relpath: str) -> Path:
    """Idempotently add `new_relpath` to
    `<external_write_dir>/adapter_profile_registry.json` (creating the file if
    absent). This is the "one-line reviewable diff" zones.py's module
    docstring describes -- written by this deterministic emitter, never
    hand-edited into zones.py's own source. Returns the registry path."""
    registry_path = external_write_dir / ADAPTER_PROFILE_REGISTRY_BASENAME
    entries: List[str] = []
    if registry_path.is_file():
        try:
            loaded = json.loads(registry_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                entries = [e for e in loaded if isinstance(e, str)]
        except (OSError, ValueError):
            entries = []
    if new_relpath not in entries:
        entries.append(new_relpath)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
    return registry_path


def emit_capability_code_scaffold(
    spec: CapabilityCodeSpec,
    project_root: Path,
    *,
    external_write_rel: Path = DEFAULT_EXTERNAL_WRITE_REL,
    capabilities_rel: Path = DEFAULT_CAPABILITIES_REL,
) -> List[Path]:
    """Emit the gate-wired-by-construction adapter + read-facade + capability
    module TRIO for `spec` into `project_root` (three files, not
    two; see this module's docstring for the full rationale), register ONLY
    the adapter module in the ADAPTER_PROFILE registry, and add the adapter
    module to the turnkey-acceptance static registry (Task 7 / F-37 --
    `registered_adapters.py`, asserting no duplicate op_kind first). Returns
    the list of paths written, in this order: adapter module, read-facade
    module, capability module, ADAPTER_PROFILE registry file,
    registered-adapters registry file.

    The read-facade module (`read_facades_<capability_id>.py`) is written
    alongside the adapter module in `external_write_dir` — same directory as
    the reference `read_facades_gmail.py` — but is deliberately NEVER added
    to either registry above: it is a SCANNED module (fail-closed default
    CAPABILITY classification), not an ADAPTER_PROFILE one, and it registers
    no op_kind of its own.

    Idempotent for the code files (a re-run overwrites its own prior emit, not
    duplicates it); both registry updates are idempotent by construction (see
    `_update_adapter_profile_registry` / `_update_registered_adapters`).
    """
    project_root = Path(project_root)
    external_write_dir = project_root / external_write_rel
    capabilities_dir = project_root / capabilities_rel

    external_write_dir.mkdir(parents=True, exist_ok=True)
    capabilities_dir.mkdir(parents=True, exist_ok=True)

    # AC-T7/BI-1: validate BEFORE writing anything for this capability -- a
    # duplicate op_kind must never leave a partial emit behind (the new
    # capability's own trio of files, or its adapter_profile_registry.json
    # entry, written even though registered_adapters.py's own update refused).
    _assert_no_duplicate_op_kind(external_write_dir, spec.adapter_module_stem, spec.op_kind)

    adapter_path = external_write_dir / f"{spec.adapter_module_stem}.py"
    read_facade_path = external_write_dir / f"{spec.read_facade_module_stem}.py"
    capability_path = capabilities_dir / f"{spec.capability_module_stem}.py"

    adapter_path.write_text(render_adapter_module(spec), encoding="utf-8")
    read_facade_path.write_text(render_read_facade_module(spec), encoding="utf-8")
    capability_path.write_text(render_capability_module(spec), encoding="utf-8")

    registry_path = _update_adapter_profile_registry(
        external_write_dir, f"{spec.adapter_module_stem}.py")
    registered_adapters_path = _update_registered_adapters(
        external_write_dir, spec.adapter_module_stem, spec.op_kind)

    return [adapter_path, read_facade_path, capability_path, registry_path,
            registered_adapters_path]


# ---------------------------------------------------------------------------
# CLI wrapper — add-capability's build cascade invokes this (from the wizard
# toolkit, e.g. `${WIZARD_HOME:-$HOME/agent-wizard}/scripts/lib/
# capability_code_scaffold.py`) for a writes-back capability, BEFORE the
# acceptance file is written. Exits 0 on emission, 1 on a malformed spec, 2 on
# usage.
# ---------------------------------------------------------------------------

def _spec_from_json(data: dict) -> CapabilityCodeSpec:
    kwargs = dict(data)
    for tuple_field in ("writes", "read_methods", "verifier_set"):
        if tuple_field in kwargs and kwargs[tuple_field] is not None:
            kwargs[tuple_field] = tuple(kwargs[tuple_field])
    return CapabilityCodeSpec(**kwargs)


if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _args = _sys.argv[1:]
    _opts = {"--spec": None, "--project-root": None}
    _usage = ("Usage: capability_code_scaffold.py --spec <spec.json> "
              "--project-root <path>")
    _i = 0
    while _i < len(_args):
        _a = _args[_i]
        if _a in _opts:
            if _i + 1 >= len(_args):
                print(_usage, file=_sys.stderr)
                _sys.exit(2)
            _opts[_a] = _args[_i + 1]
            _i += 2
        else:
            print(f"unknown argument {_a!r}\n{_usage}", file=_sys.stderr)
            _sys.exit(2)

    if not _opts["--spec"] or not _opts["--project-root"]:
        print(_usage, file=_sys.stderr)
        _sys.exit(2)

    try:
        with open(_opts["--spec"], encoding="utf-8") as _f:
            _spec = _spec_from_json(json.load(_f))
    except (CapabilityCodeScaffoldError, Exception) as _e:  # noqa: BLE001
        print(f"REFUSED: could not build a valid capability spec: {_e}", file=_sys.stderr)
        _sys.exit(1)

    _written = emit_capability_code_scaffold(_spec, Path(_opts["--project-root"]))
    print("EMITTED (gate-wired by construction):")
    for _p in _written:
        print(f"  {_p}")
    _sys.exit(0)
