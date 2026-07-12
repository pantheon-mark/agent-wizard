"""Legal (Task R11-T1, F1 negative guard): the bare kernel dispatch module
name spelled with NO `external_write.` prefix and no relative dot -- `import
adapters` -- followed by using `run_operation`, the one legitimate
CAPABILITY-facing entrypoint that module exports. `adapters` (bare) is NOT an
adapter-PROFILE module: `"adapters".startswith("adapters_")` is False (the
prefix requires the trailing underscore + a non-empty suffix), and it is not
the registry (`adapter_registry`) either. Must NOT be flagged
`adapter_module_import`.
"""

import adapters


def run_approved(op, receipt, client):
    return adapters.run_operation(op, receipt, client)
