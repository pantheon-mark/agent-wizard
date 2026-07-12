"""Gate-wired-by-construction capability code scaffold emitter (Task 10 —
external-write-gate-generalization slice).

Why this exists
----------------
`add-capability` (wizard/skills/add-capability.md) designs a capability
in plain business language, then hands off to `next-phase` to build it. Before
this task, "build it" meant an agent freely authoring the capability's Python
from scratch — including, for a capability that touches an external system,
whatever adapter/credential/mutation code it thought the vendor needed. That is
exactly the shape the whole external-write-gate-generalization slice exists to
close off: a freely-authored capability can drift outside the gate (F-33's
"own-your-safety" finding — the ONLY thing that caught a real bypass in
dogfooding was the Claude Code harness's auto-mode classifier, never the
emitted gate itself, because the emitted gate was never actually wired for
that capability).

This module is the fix for the BUILD side of that gap: a deterministic,
template-driven emitter that turns a small, typed `CapabilityCodeSpec` (the
op_kind + vendor read-only scope + blast-radius cap the design phase already
settled — see add-capability.md Steps C/D) into two files that are ALREADY
gate-wired, by construction, before a single line is hand-authored:

  1. An **adapter module** (Task 5's ADAPTER_PROFILE trust zone) —
     `agents/lib/external_write/adapters_<capability_id>.py`. Registers a
     `contracts.OperationContract` (declaring op_kind + read_only_scope +
     blast_radius_cap + risk_class — this task's requirement 1) and an
     `adapter_registry.Adapter` (plan/apply_one/undo_one/verify_one) at
     module scope — the SAME self-registering convention `adapters_gmail.py`
     (Task 7) already established. Its filename is appended to the
     capability-added registry `zones.py` reads (see
     `zones.effective_adapter_profile_paths` / `_load_extra_adapter_profile_paths`
     — Task 10's zones.py change), so the module is a recognized
     ADAPTER_PROFILE member the moment it is written, with NO hand-edit of
     `zones.py`'s source required.
  2. A **capability module** (Task 5's CAPABILITY trust zone) —
     `agents/capabilities/<capability_id>_capability.py`. Holds only a
     `read_facade.ReadFacade` built against the declared read-only scope;
     never imports a vendor SDK; never constructs or references a write
     credential; and cannot even NAME a write-credential provider. It routes
     any actual write through `adapters.run_operation`, which resolves the
     write-capable client INTERNALLY from the registered adapter's
     `build_write_client` method (BL-1 / F-33 credential-isolation keystone —
     enforced deterministically by scan.py's credential_provider_reference
     rule, not by a comment convention).

Both emitted files are runnable/importable stubs — `plan`/`apply_one`/
`undo_one`/`verify_one` and the adapter's `build_write_client` raise
`NotImplementedError` with a plain TODO pointing at the one thing that still
needs a human decision (the actual per-vendor call shape) — but the GATE
WIRING itself (contract declaration, adapter registration, zone membership,
credential isolation, no-vendor-import) is complete and verified BEFORE
next-phase ever touches the capability. The acceptance test for this module
(`test_capability_code_scaffold.py`) proves the emitted pair passes
`external_write.scan.scan_paths` — the Task 5 build-time gate — by
construction, with zero manual wiring.

Boundary discipline (D-B1-a, same as every other build-side module that
touches the external_write package): this module lives in `wizard/scripts/lib`
(the wizard TOOLKIT engine) and WRITES INTO the operator project's
`agents/lib/external_write/` and `agents/capabilities/` directories; it does
not itself import from the `external_write` package (it only emits Python
source text for it) and it is invoked from the wizard toolkit, not from
inside the operator's own trust-boundary code.

Stdlib only — no third-party dependencies.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import List, Optional, Tuple


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
                        capability migrates a mechanism upgrade-reconcile
                        (Task 9) safe-paused, this MUST equal that mechanism's
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
    def capability_module_stem(self) -> str:
        return f"{self.capability_id}_capability"


# ---------------------------------------------------------------------------
# Adapter module (ADAPTER_PROFILE zone) template
# ---------------------------------------------------------------------------

_ADAPTER_MODULE_TEMPLATE = Template('''"""${display_name} — adapter module (ADAPTER_PROFILE trust zone).

GENERATED by wizard/scripts/lib/capability_code_scaffold.py (Task 10 —
external-write-gate-generalization slice) for the "${capability_id}" capability,
via add-capability's build cascade. This is the ONLY module for this capability
allowed to import a vendor SDK, construct or obtain a write-capable credential,
and perform a raw vendor mutation -- see zones.py for the full trust-zone
rationale. Its relative filename is registered in the sibling
adapter_profile_registry.json (never hand-edited into zones.py's source) so it
is recognized as ADAPTER_PROFILE the moment this file is written.

TODO (next-phase / a human decision, not this emitter's job): the plan /
apply_one / undo_one / verify_one bodies below are structural stubs -- they
declare the SHAPE the gate requires (one EffectUnit per discrete mutation;
undo restores the prior state) but not the real per-vendor call. Fill those
in against the real ${surface} API. Do NOT add a send/forward/permanent-delete
path unless the design in vision.md/execution_plan.md explicitly calls for it
-- see adapters_gmail.py's "Structural safety -- held by ABSENCE of code"
section for the pattern to follow.
"""

from typing import Any, List, Optional

from external_write.adapter_registry import register_adapter
from external_write.contracts import (
    OperationContract, WRITE_AFFECTING_MODULES, register_contract,
)
from external_write.operations import EffectUnit
from external_write.read_facade import ReadFacade


OP_KIND = "${op_kind}"


# ---------------------------------------------------------------------------
# Contract registration -- declares op_kind + read_only_scope + blast_radius_cap
# (Task 10 requirement 1) at import time, module scope, exactly like
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

    build_write_client (BL-1 / F-33 credential-isolation keystone) is the ONLY
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

    def verify_one(self, raw_client: Any, unit: EffectUnit) -> Any:
        raise NotImplementedError(
            "TODO: read back the live state for "
            f"{unit.unit_id!r} against raw_client and report whether it matches.")


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


# ---------------------------------------------------------------------------
# Read-only facade (declares ONLY the read methods named below; see
# read_facade.py -- a subclass may not define any other public attribute).
# ---------------------------------------------------------------------------

class ${class_prefix}ReadFacade(ReadFacade):
    """Read-only facade for '${op_kind}', built against ${read_only_scope}."""

    read_methods = ${read_methods}

${read_method_bodies}
''')

_READ_METHOD_BODY_TEMPLATE = Template('''    def ${method_name}(self, *args: Any, **kwargs: Any) -> Any:
        return self._read("${method_name}", *args, **kwargs)
''')


def render_adapter_module(spec: CapabilityCodeSpec) -> str:
    """Render the ADAPTER_PROFILE-zone module source for `spec`. Pure string
    rendering -- no filesystem I/O, no import of the rendered code."""
    read_method_bodies = "\n".join(
        _READ_METHOD_BODY_TEMPLATE.substitute(method_name=m) for m in spec.read_methods
    )
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
        read_methods=repr(tuple(spec.read_methods)),
        read_method_bodies=read_method_bodies,
    )


# ---------------------------------------------------------------------------
# Capability module (CAPABILITY zone) template — no vendor import, no write
# credential, no client re-stash, and no importable credential-provider symbol
# to reach; reads only via the ReadFacade above; routes any write through
# adapters.run_operation, which resolves the write client internally from the
# registered adapter's build_write_client method.
# ---------------------------------------------------------------------------

_CAPABILITY_MODULE_TEMPLATE = Template('''"""${display_name} — capability module (CAPABILITY trust zone).

GENERATED by wizard/scripts/lib/capability_code_scaffold.py (Task 10 —
external-write-gate-generalization slice) for the "${capability_id}" capability.

Structural safety -- held by ABSENCE of code, not a runtime check (mirrors
adapters_gmail.py's own "Structural safety" section): this module never
imports a vendor SDK, never constructs or references a write-capable
credential, and never calls anything shaped like a raw vendor mutation. It
reads ONLY through ${class_prefix}ReadFacade (declared read methods only) and
proposes/executes writes ONLY through adapters.run_operation. It cannot even
NAME a write-credential provider: the write-capable credential is built solely
by the adapter module's ${class_prefix}Adapter.build_write_client, resolved
INTERNALLY by run_operation inside the adapter execution path (BL-1 / F-33 --
enforced deterministically by scan.py's credential_provider_reference rule, not
by a comment convention).

TODO (a human/next-phase decision, not this emitter's job): propose_operations
below is a structural stub -- it shows the SHAPE (read via the facade, build
Operation objects with real params) but the actual "what changed, what should
this capability propose" logic is domain-specific and is filled in against
the real design in vision.md / execution_plan.md.
"""

from typing import Any, List, Optional

from external_write.adapters import run_operation
from external_write.adapters_${capability_id} import ${class_prefix}ReadFacade
from external_write.operations import Operation, SCHEMA_V2_ACTION
from external_write.read_facade import build_read_facade


OP_KIND = "${op_kind}"
SURFACE = "${surface}"


def build_facade(read_only_client: Any) -> ${class_prefix}ReadFacade:
    """Build this capability's read-only facade. `read_only_client` must
    already be scoped to ${read_only_scope} by its caller (see the adapter
    module's build_read_only_client)."""
    return build_read_facade(OP_KIND, read_only_client, ${class_prefix}ReadFacade)


def propose_operations(facade: ${class_prefix}ReadFacade, batch_id: str) -> List[Operation]:
    """TODO: read via `facade` (its declared read methods only) and return the
    Operation(s) this capability proposes. Structural stub -- returns no
    operations until the real per-capability logic is filled in."""
    raise NotImplementedError(
        "TODO: read via facade and build the real Operation params for "
        "'${op_kind}' here.")


def run_approved(op: Operation, receipt: Any, *, target: Optional[str] = None,
                 descriptor_set: Any = None, cap_ledger: Any = None) -> Any:
    """Execute an already-approved Operation. Passes NO write-credential
    provider -- this capability zone cannot obtain one. run_operation resolves
    the write-capable client internally, keyed by the registered adapter
    (${class_prefix}Adapter.build_write_client), inside the adapter execution
    path, only once dispatch is committed (BL-1 / F-33)."""
    return run_operation(
        op, receipt, None,
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
        read_only_scope=repr(spec.read_only_scope),
    )


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

DEFAULT_EXTERNAL_WRITE_REL = Path("agents") / "lib" / "external_write"
DEFAULT_CAPABILITIES_REL = Path("agents") / "capabilities"
ADAPTER_PROFILE_REGISTRY_BASENAME = "adapter_profile_registry.json"


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
    """Emit the gate-wired-by-construction adapter + capability module pair for
    `spec` into `project_root`, and register the adapter module in the
    ADAPTER_PROFILE registry. Returns the list of paths written (adapter
    module, capability module, registry file — in that order).

    Idempotent for the code files (a re-run overwrites its own prior emit, not
    duplicates it); the registry update is idempotent by construction (see
    `_update_adapter_profile_registry`).
    """
    project_root = Path(project_root)
    external_write_dir = project_root / external_write_rel
    capabilities_dir = project_root / capabilities_rel

    external_write_dir.mkdir(parents=True, exist_ok=True)
    capabilities_dir.mkdir(parents=True, exist_ok=True)

    adapter_path = external_write_dir / f"{spec.adapter_module_stem}.py"
    capability_path = capabilities_dir / f"{spec.capability_module_stem}.py"

    adapter_path.write_text(render_adapter_module(spec), encoding="utf-8")
    capability_path.write_text(render_capability_module(spec), encoding="utf-8")

    registry_path = _update_adapter_profile_registry(
        external_write_dir, f"{spec.adapter_module_stem}.py")

    return [adapter_path, capability_path, registry_path]


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
