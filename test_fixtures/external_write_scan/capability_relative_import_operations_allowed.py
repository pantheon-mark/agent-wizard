"""Legal (Task R10-T1 negative guard): the relative bare-import shape applied
to a legitimate CAPABILITY-facing module -- `from . import operations`.
`operations` is neither the registry (`adapter_registry`) nor an
adapter-PROFILE module (does not start with `adapters_`), so the new
relative-import check must NOT fire. Must NOT be flagged.
"""

from . import operations


def describe(op: "operations.Operation"):
    return op
