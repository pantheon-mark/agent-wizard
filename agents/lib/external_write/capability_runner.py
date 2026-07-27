"""Kernel-as-runner: the sealed kernel RUNS a capability and INJECTS what it
needs (Cut 1.6 / bundle v0.20.0, Task 5 -- the keystone).

The defect this closes (F-VAL19-5, SEV-HIGH)
--------------------------------------------
A bespoke bulk writer that must READ external data to build its proposal had no
sanctioned way to obtain a read-only client. The only builder was an
adapter-class method, and CAPABILITY-zone code importing the adapter is an
``adapter_module_import`` violation. **A writer that complied could not read; a
writer that read could not comply.** Under the coarse presence-of-violation gate that made
acceptance permanently unreachable project-wide.

STEP 0 (the build-side validation record)
proved this was NOT a legacy-estate problem: a FRESHLY scaffolded capability
shared it. Of the four possible entrypoint shapes, three are scan-blocked and
the only compliant one is functionally dead (its client is necessarily ``None``;
the first read raises ``AttributeError``).

Why INVERSION rather than a provisioning function
-------------------------------------------------
The root cause is not a missing function -- it is that the scaffold emitted
three files that cannot run and deferred the credential seam to "whoever wires
this capability's entrypoint together", into the one zone where that seam is
illegal. Handing capability code a provisioner would legalise the seam; moving
the wiring into the kernel DELETES it.

Both cross-vendor advisors split on the question as posed (facade vs frozen
snapshot) but, when asked to ignore that framing entirely, independently
proposed this same shape (gpt-5.5's "Proposal Kernel", gemini's "Inverted
Entrypoint"). See the build-side validation record and
the disposition in the build-side validation record § D-1.

``capability_api`` gains NO new export: capability code never asks for anything,
so the property that module's docstring asserts is untouched.

Why op_kind is DERIVED, never passed (do not "simplify" this)
-------------------------------------------------------------
A caller-supplied ``op_kind`` would let a capability built for one surface
request a facade for another and read across surfaces -- write isolation fixed,
read isolation left horizontally open (gemini's regret-mode finding). Here the
kernel reads ``OP_KIND`` from the capability module it is actually running, so
requesting someone else's surface is not merely disallowed, it is
unrepresentable: a capability would have to change its own declared OP_KIND,
which changes its identity, breaks the 4-way capability-identity invariant, and is
visible at build time.

Honesty bound (do not overclaim)
--------------------------------
This removes the raw read-only client from the sanctioned path and removes the
only reason for capability code to import the adapter. It is NOT a structural
guarantee that capability code cannot recover a read-only client in-process:
``read_facade.py``'s disclosed residuals are unchanged -- ``facade._read`` accepts
arbitrary method names (``read_facade.py`` ~:367-397) and ``_WRAPPED_CLIENTS`` is
import-reachable (~:58-63). Both leak the READ-ONLY client only, never the
write-capable credential, and both sit inside this package's stated ceiling:
build-time + operator-as-approver, NOT a runtime/OS sandbox.

Stdlib only -- no third-party dependencies.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, List, Optional

from external_write.adapter_registry import get_dispatch
from external_write.read_facade import build_read_facade

CAPABILITIES_DIR_REL = "agents/capabilities"
CAPABILITY_MODULE_SUFFIX = "_capability"
EXTERNAL_WRITE_PKG = "external_write"


class CapabilityRunnerError(Exception):
    """A fail-closed refusal to run a capability's proposal step. Always carries
    a plain-language, operator-facing reason -- never a raw traceback (the
    repo's "no raw errors to the operator" convention)."""


def _import_capability_module(project_root: Path, capability_id: str) -> Any:
    """Import ``agents/capabilities/<capability_id>_capability.py``.

    Uses the 4-way capability-identity invariant (``capability_id == module
    stem``) rather than inferring the module from anything incidental. Mirrors
    the kernel-side importlib precedent in ``registered_adapters.py``."""
    module_stem = f"{capability_id}{CAPABILITY_MODULE_SUFFIX}"
    capabilities_dir = project_root / CAPABILITIES_DIR_REL
    source = capabilities_dir / f"{module_stem}.py"
    if not source.is_file():
        raise CapabilityRunnerError(
            f"there is no capability called `{capability_id}` in this project "
            f"(expected {CAPABILITIES_DIR_REL}/{module_stem}.py)")
    if str(capabilities_dir) not in sys.path:
        sys.path.insert(0, str(capabilities_dir))
    try:
        return importlib.import_module(module_stem)
    except Exception as exc:  # noqa: BLE001 -- turned into a plain-language refusal.
        raise CapabilityRunnerError(
            f"`{capability_id}` could not be loaded ({exc.__class__.__name__}) -- "
            "it needs to be rebuilt before it can run") from exc


def resolve_read_facade_class(project_root: Any, capability_id: str) -> type:
    """Resolve the ReadFacade subclass for ``capability_id``'s op_kind by
    reading what the modules DECLARE, never by deriving a filename from the
    id -- and never by pulling an unvalidated object out of the declaring
    module's namespace.

    Declaration topology is the mandatory authority for WHICH module to
    import (``declaration.module_stem`` -- filenames are still never an
    input). The OBJECT itself always comes from
    ``read_facade.get_read_facade_class``, the SAME registry accessor that
    ``register_read_facade`` populates, and only populates after checking
    ``isinstance(x, type) and issubclass(x, ReadFacade)`` -- so anything this
    function returns is guaranteed to already be a validated ReadFacade
    subclass. ``declaration.symbol`` is advisory only (naming things in a
    message); it is never the source of the returned object, because a
    declaration this module can locate but cannot read a plain symbol name
    for -- or one naming something that turns out not to be a ReadFacade --
    must still never be able to hand back an unvalidated value.

    Imports exactly one module -- the one that declares the op_kind --
    inside its own try/except, matching registered_adapters.py's
    per-module isolation.

    The directory scanned for declarations is this kernel module's OWN
    location, not anything derived from ``project_root``. The resolved
    module is subsequently imported as ``external_write.<module_stem>``, so
    the directory scanned here has to be the same directory that import will
    actually load from -- deriving it from ``project_root`` instead risks
    scanning one directory while importing from another, which would just be
    a second copy of the "two paths that have to agree" defect this is
    fixing.
    """
    from external_write.topology import build_topology, TopologyError
    from external_write.read_facade import get_read_facade_class

    root = Path(project_root)
    module = _import_capability_module(root, capability_id)
    op_kind = getattr(module, "OP_KIND", None)
    if not isinstance(op_kind, str) or not op_kind:
        raise CapabilityRunnerError(
            f"`{capability_id}` does not declare what kind of operation it "
            "performs, so it cannot be run safely -- it needs to be rebuilt")

    lib_dir = Path(__file__).resolve().parent
    topology = build_topology(lib_dir)
    try:
        declaration = topology.find_read_facade(op_kind)
    except TopologyError as exc:
        # Translate the build-time-audience topology message into plain,
        # operator-actionable language -- the detail stays available via
        # exception chaining, never in the sentence handed to the operator.
        hits = [d for d in topology.declarations
                if d.role == "read_facade" and d.op_kind == op_kind]
        conflicting = sorted({d.relpath for d in hits})
        if len(conflicting) > 1:
            raise CapabilityRunnerError(
                f"more than one file in this project claims to provide "
                f"read-only access for `{capability_id}` "
                f"({', '.join(conflicting)}), so it is unclear which one to "
                "use. One of them needs to be removed or fixed so only one "
                "remains.") from exc
        raise CapabilityRunnerError(
            f"`{capability_id}` cannot look at the outside system in "
            "read-only mode yet, so it cannot safely work out what to "
            "change -- it needs to be rebuilt") from exc

    try:
        importlib.import_module(f"{EXTERNAL_WRITE_PKG}.{declaration.module_stem}")
    except Exception as exc:  # noqa: BLE001 -- isolation, and it is REPORTED.
        raise CapabilityRunnerError(
            f"the file that provides read-only access for `{capability_id}` "
            f"({declaration.relpath}) could not be loaded "
            f"({exc.__class__.__name__}). It needs to be fixed before this "
            "can run.") from exc

    facade_cls = get_read_facade_class(op_kind)
    if facade_cls is None:
        raise CapabilityRunnerError(
            f"{declaration.relpath} loaded, but did not provide a working "
            f"reader for `{capability_id}`. It needs to be fixed before "
            "this can run.")
    return facade_cls


def build_capability_read_facade(project_root: Any, capability_id: str) -> Any:
    """Resolve a READ-ONLY facade for ``capability_id``, entirely kernel-side.

    The capability never names, imports, holds, or constructs the raw client --
    it receives only the facade. ``op_kind`` is read from the capability
    module's own ``OP_KIND`` constant, never from a caller argument (see the
    module docstring)."""
    root = Path(project_root)
    module = _import_capability_module(root, capability_id)

    op_kind = getattr(module, "OP_KIND", None)
    if not isinstance(op_kind, str) or not op_kind:
        raise CapabilityRunnerError(
            f"`{capability_id}` does not declare what kind of operation it performs, "
            "so it cannot be run safely -- it needs to be rebuilt")

    try:
        dispatch = get_dispatch(op_kind)
    except Exception as exc:  # noqa: BLE001
        raise CapabilityRunnerError(
            f"`{capability_id}` is not wired up to anything that can talk to the "
            "outside system yet -- it needs to be rebuilt") from exc
    if dispatch is None:
        raise CapabilityRunnerError(
            f"`{capability_id}` is not wired up to anything that can talk to the "
            "outside system yet -- it needs to be rebuilt")

    provision = getattr(dispatch, "provision_read_only_client", None)
    if provision is None:
        # Name the ADAPTER, not a rebuild of the capability. This is a defect in
        # the adapter's shape -- the read-only reader has to be a method on the
        # registered adapter class -- and the rebuild flow carries no guidance
        # for it, so "rebuild this capability" sends the operator in a circle.
        # Same wording the upgrade uses for the same fact, deliberately.
        raise CapabilityRunnerError(
            f"`{capability_id}` cannot look at the outside system in read-only "
            "mode yet, so it cannot safely work out what to change. What is "
            f"missing is on the adapter that handles `{op_kind}`, not in "
            f"`{capability_id}` itself: that adapter class needs a read-only "
            f"reader on it. Rebuilding `{capability_id}` will not fix this -- "
            "ask for the adapter to be updated instead")
    try:
        client = provision(dispatch.instance, None)
    except Exception as exc:  # noqa: BLE001
        raise CapabilityRunnerError(
            f"`{capability_id}` could not connect to the outside system in read-only "
            "mode -- check that its access is set up, then try again") from exc
    if client is None:
        raise CapabilityRunnerError(
            f"`{capability_id}` could not obtain read-only access to the outside "
            "system -- check that its access is set up, then try again")

    facade_cls = resolve_read_facade_class(project_root, capability_id)
    return build_read_facade(op_kind, client, facade_cls)


def run_capability_proposal(project_root: Any,
                            capability_id: str,
                            *,
                            batch_id: str,
                            context: Optional[Any] = None) -> List[Any]:
    """Run ``capability_id``'s proposal step with a kernel-built read facade
    injected, and return the Operations it proposes.

    This is the sanctioned entrypoint: the capability is CALLED, it does not
    bootstrap. Nothing here authorizes a write -- proposing is read-only; the
    write still goes through ``run_sanctioned_bulk`` under an operator-approved
    RunEnvelope."""
    root = Path(project_root)
    facade = build_capability_read_facade(root, capability_id)
    module = _import_capability_module(root, capability_id)

    propose = getattr(module, "propose_operations", None)
    if not callable(propose):
        raise CapabilityRunnerError(
            f"`{capability_id}` has no step that works out what to change, so there "
            "is nothing to propose -- it needs to be rebuilt")
    try:
        if context is None:
            operations = propose(facade, batch_id)
        else:
            operations = propose(facade, batch_id, context)
    except NotImplementedError as exc:
        raise CapabilityRunnerError(
            f"`{capability_id}` has not been finished yet -- the step that works out "
            "what to change is still a placeholder") from exc
    if operations is None:
        return []
    return list(operations)


# ---------------------------------------------------------------------------
# CLI entrypoint -- the sanctioned way to run a capability's proposal step.
#
# This is deliberately part of the KERNEL rather than an emitted per-capability
# runner script. An emitted entrypoint is a file that can drift, and every place
# an operator project could put one is CAPABILITY-zoned, where obtaining a read
# client is a scan violation -- which is precisely how F-VAL19-5 happened. The
# kernel already holds the only legitimate wiring, so it holds the entrypoint
# too, and there is no per-capability file to get wrong.
#
# Usage:
#   python3 agents/lib/external_write/capability_runner.py <capability_id> [batch_id]
#
# Exits 0 on success (proposal count on stdout), 1 on a plain-language refusal.
# Never prints a traceback -- a non-technical operator reads this output.
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _argv = _sys.argv[1:]
    if not _argv or len(_argv) > 2:
        print("Usage: python3 agents/lib/external_write/capability_runner.py "
              "<capability_id> [batch_id]", file=_sys.stderr)
        raise SystemExit(2)

    _capability_id = _argv[0]
    _batch_id = _argv[1] if len(_argv) == 2 else "manual"
    try:
        _ops = run_capability_proposal(".", _capability_id, batch_id=_batch_id)
    except CapabilityRunnerError as _exc:
        print(f"Cannot run this yet: {_exc}", file=_sys.stderr)
        raise SystemExit(1)
    print(f"{_capability_id}: proposed {len(_ops)} change(s) for review.")
