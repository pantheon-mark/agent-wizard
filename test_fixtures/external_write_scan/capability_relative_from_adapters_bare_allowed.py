"""Legal (Task R10-T1 negative guard): the relative DOTTED-module import
shape applied to the bare kernel dispatch module -- `from .adapters import
run_operation`. `node.module == "adapters"` (bare, relative): NOT an
adapter-PROFILE module (`"adapters".startswith("adapters_")` is False) and
not the registry (`adapter_registry`). Must NOT be flagged
`adapter_module_import`. `run_operation` is also not itself a banned
registry symbol, so `adapter_registry_reference` must not fire either.
"""

from .adapters import run_operation


def run_approved(op, receipt, client):
    return run_operation(op, receipt, client)
