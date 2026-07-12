"""Legal (Task R10-T1 negative guard): the relative bare-import shape applied
to the bare kernel dispatch module -- `from . import adapters` -- followed by
using `run_operation`, the one legitimate CAPABILITY-facing entrypoint that
module exports. `adapters` (bare) is NOT an adapter-PROFILE module:
`"adapters".startswith("adapters_")` is False (the prefix requires the
trailing underscore + a non-empty suffix), and it is not the registry
(`adapter_registry`) either. Must NOT be flagged `adapter_module_import`.
`run_operation` is also not itself a banned registry symbol, so
`adapter_registry_reference` must not fire either.
"""

from . import adapters


def run_approved(op, receipt, client):
    return adapters.run_operation(op, receipt, client)
