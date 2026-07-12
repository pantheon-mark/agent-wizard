"""Curated capability-facing import surface for `external_write` (Task
R7-T1 — external-write-gate-generalization slice; kernel ReadFacade registry
generalization).

This is the ONLY `external_write` module (besides `operations`, which is
pure data — Operation/EffectUnit — and carries nothing credential-reachable
either) that emitted capability code is meant to import. It re-exports
EXACTLY the two capability-facing entrypoints and NOTHING else:

    run_operation      (external_write.adapters)   -- the single external-
                        write chokepoint; capability code builds an
                        Operation and a receipt and calls this to execute it.
    build_read_facade  (external_write.read_facade) -- resolves a registered
                        ReadFacade subclass for an op_kind (the capability-
                        facing two-arg call shape: `build_read_facade(op_kind,
                        read_only_client)` — the kernel resolves the concrete
                        subclass from its own registry; see read_facade.py).

It deliberately does NOT re-export:
  * `get_adapter` / the adapter registry (`adapter_registry.py`) — the
    mutable Adapter instance a capability could otherwise reach and
    monkey-patch.
  * Any Adapter class or ADAPTER_PROFILE module (e.g. `adapters_gmail.py`).
  * `register_read_facade` / `_READ_FACADE_REGISTRY` — registration is a
    module-import-time, kernel/facade-module concern, not something
    capability code ever calls.
  * Any credential provisioner, write-capable client, or symbol from which
    one is reachable — the whole point of this module existing is that a
    capability importing ONLY from here has no path to a write credential,
    by construction of what this file contains, not by convention.

Why this module exists (the hole it closes): prior to Task R7, capability
code reached its `ReadFacade` subclass by importing it directly from the
same ADAPTER_PROFILE module that defined `build_write_client` (e.g.
`from external_write.adapters_gmail import GmailReadFacade`) — a
cross-vendor-ratified architectural hole, because that import gave
capability code a reason to be in the SAME module namespace as write-capable
adapter code, and nothing stopped it from also importing (or reaching, via
`get_adapter`) the mutable adapter object itself. This module removes that
*reason*: capability code imports `build_read_facade` from HERE, and the
concrete subclass is resolved through the kernel registry
(`read_facade._READ_FACADE_REGISTRY`), keyed by op_kind — capability code
never needs to name (or import) the facade subclass, the adapter module, or
the adapter registry at all.

This module is a small, curated re-export shim — it is deliberately trivial
(no logic of its own) so that its entire credential-reachability surface can
be verified by reading its `__all__` and confirming each name traces to a
non-credential-reachable symbol, as documented above. The per-project emit
enrollment (making emitted capability code actually import from HERE instead
of an adapter module, and the scanner rules that would flag it if it
didn't) is a LATER task's concern — this module only builds the surface
itself.

Stdlib only — no third-party dependencies.
"""

from external_write.adapters import run_operation
from external_write.read_facade import build_read_facade

__all__ = ["run_operation", "build_read_facade"]
