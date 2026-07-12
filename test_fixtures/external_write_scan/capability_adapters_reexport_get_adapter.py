"""Bypass fixture (Task R7-T4): a CAPABILITY-zone module that imports
`get_adapter` via a RE-EXPORT shape -- `from external_write.adapters import
get_adapter` (the bare kernel dispatch module, NOT the adapter registry
module). The scanner must flag the NAME regardless of which module a
capability claims to import it from: naming the symbol at all is the bypass,
not merely the module path used to reach it. The bare `adapters` module
import itself stays legal (it is where `run_operation` legitimately lives),
so this fixture must be flagged `adapter_registry_reference` but NOT
`adapter_module_import`.
"""

from external_write.adapters import get_adapter

OP_KIND = "acme_sync"


def peek_adapter():
    return get_adapter(OP_KIND)
