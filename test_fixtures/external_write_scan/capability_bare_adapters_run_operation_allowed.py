"""Legal (Task R7-T4 negative guard): capability code importing ONLY
`run_operation` from the bare kernel dispatch module `external_write.adapters`
-- one of the two legitimate CAPABILITY-facing entrypoints into the gate
(alongside the identical name re-exported by `external_write.capability_api`).
Must NOT be flagged: `adapters` (bare) is the kernel module where
`run_operation` lives, not an adapter-PROFILE module (`adapters_<vendor>`)
and not the registry (`adapter_registry`), and `run_operation` is not itself
a banned registry symbol.
"""

from external_write.adapters import run_operation


def run_approved(op, receipt, client):
    return run_operation(op, receipt, client)
