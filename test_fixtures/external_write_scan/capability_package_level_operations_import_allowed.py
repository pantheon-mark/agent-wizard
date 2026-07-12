"""Legal (Task R9-T1 negative guard): the package-level import shape applied
to a legitimate CAPABILITY-facing module -- `from external_write import
operations`. `operations` is neither the registry (`adapter_registry`) nor
an adapter-PROFILE module (does not start with `adapters_`), so the new
package-level check must NOT fire. Must NOT be flagged.
"""

from external_write import operations


def describe(op: "operations.Operation"):
    return op
