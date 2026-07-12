"""Bypass fixture (Task R11-T1, F2): a NESTED registry submodule --
`from external_write.adapter_registry.sub import get_adapter` -- three
dotted components on the `from` side, so the registry name sits BETWEEN
`external_write` and a further submodule (`sub`), not as the trailing
component the old trailing-two-components check required. Must be flagged
BOTH `adapter_module_import` (the nested registry-module import) AND
`adapter_registry_reference` (the `get_adapter` symbol named).
"""

from external_write.adapter_registry.sub import get_adapter


def reach(op_kind):
    return get_adapter(op_kind)
