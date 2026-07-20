"""Curated capability-facing import surface for `external_write` (part of
the kernel ReadFacade registry generalization).

This is the ONLY `external_write` module (besides `operations`, which is
pure data — Operation/EffectUnit — and carries nothing credential-reachable
either) that emitted capability code is meant to import. It re-exports
EXACTLY the three capability-facing entrypoints and NOTHING else:

    run_enveloped_operation  (external_write.run_envelope) -- the sanctioned
                        CAPABILITY live-write entrypoint for a SINGLE
                        already-approved op. Capability code runs an approved
                        Operation UNDER a ceremony-minted RunEnvelope, so the
                        run-level trust protections are enforced by
                        construction: disk-authoritative envelope
                        spendability, consent-receipt binding, APPLY-BY-ID
                        against the frozen `reviewed_set`, and the AGGREGATE
                        CEILING. Internally this calls the raw kernel primitive
                        `run_operation` ONCE per approved op.
    run_sanctioned_bulk  (external_write.run_envelope) -- the sanctioned
                        CAPABILITY live-write entrypoint for a WHOLE
                        operator-approved bulk run (Task D6). One call mints
                        the run envelope ONCE (or, on resume, re-authorizes a
                        genuinely fresh operator consent), loops
                        `run_enveloped_operation` per chunk under that ONE
                        run id, and finalizes. Capability code must call this
                        for a multi-item bulk run instead of hand-rolling a
                        per-batch mint/apply loop -- see run_envelope.py's own
                        module docstring for the F-79/F-80 rationale this
                        closes.
    build_read_facade  (external_write.read_facade) -- resolves a registered
                        ReadFacade subclass for an op_kind (the capability-
                        facing two-arg call shape: `build_read_facade(op_kind,
                        read_only_client)` — the kernel resolves the concrete
                        subclass from its own registry; see read_facade.py).

WHY raw `run_operation` is deliberately NOT re-exported here (a change from
the prior surface): `run_operation` is the kernel write PRIMITIVE — it applies
one approved Operation but knows nothing about the run-level envelope. The
run-level protections (spendability / consent binding / apply-by-id / aggregate
ceiling) live ONLY inside `run_enveloped_operation`, which wraps it. If
capability code could reach `run_operation` directly it could loop it and
bypass every one of those checks (the per-op write gate alone does not cap a
reversible bulk run). So capability code must go through the envelope: this
module no longer exposes the raw primitive, and scan.py's CAPABILITY-zone-ONLY
`raw_run_operation_reference` rule deterministically flags any capability
module that names `run_operation` through any reach path. `run_operation`'s
own signature/contract is unchanged — it stays the kernel primitive
`run_enveloped_operation` calls.

It deliberately does NOT re-export:
  * `get_adapter` / `get_dispatch` / `AdapterDispatch` / the adapter registry
    (`adapter_registry.py`) — the mutable Adapter instance (or its captured
    dispatch record) a capability could otherwise reach and monkey-patch.
    These names are already banned in the CAPABILITY zone by scan.py's
    `adapter_registry_reference` rule; listed here too so this module's own
    non-reachability surface is self-documenting.
  * Any Adapter class or ADAPTER_PROFILE module (e.g. `adapters_gmail.py`).
  * `register_read_facade` / `_READ_FACADE_REGISTRY` — registration is a
    module-import-time, kernel/facade-module concern, not something
    capability code ever calls.
  * Any credential provisioner, write-capable client, or symbol from which
    one is reachable — the whole point of this module existing is that a
    capability importing ONLY from here has no path to a write credential,
    by construction of what this file contains, not by convention.

Why this module exists (the hole it closes): previously, capability
code reached its `ReadFacade` subclass by importing it directly from the
same ADAPTER_PROFILE module that defined `build_write_client` (e.g.
`from external_write.adapters_gmail import GmailReadFacade`) — an
architectural hole, because that import gave
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

from external_write.read_facade import build_read_facade
from external_write.run_envelope import run_enveloped_operation, run_sanctioned_bulk

__all__ = ["run_enveloped_operation", "run_sanctioned_bulk", "build_read_facade"]
