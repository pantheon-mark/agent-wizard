"""Bypass fixture (Task R11-T1, F1): a CAPABILITY-zone module that imports the
adapter registry module BARE -- `import adapter_registry` -- with no
`external_write.` prefix and no relative dot. Must be flagged
`adapter_module_import` (the bare registry-module import) AND
`adapter_registry_reference` (the `get_adapter` symbol named off it).
"""

import adapter_registry


def reach(op_kind):
    return adapter_registry.get_adapter(op_kind)
