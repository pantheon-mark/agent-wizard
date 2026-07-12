"""Bypass fixture (Task R10-T1, cross-vendor-verified gap): a CAPABILITY-zone
module that reaches the adapter registry module via the RELATIVE import
shape -- `from .adapter_registry import get_adapter` -- the relative sibling
of the absolute `external_write.adapter_registry` form `adapter_module_import`
already caught. `node.level > 0` and `node.module == "adapter_registry"`
(the submodule name, with no `external_write.` prefix). Must be flagged
BOTH `adapter_module_import` (the relative import of the registry module
itself) AND `adapter_registry_reference` (the `get_adapter` symbol named by
the import).
"""

from .adapter_registry import get_adapter

OP_KIND = "gmail_trash"


def peek_adapter():
    return get_adapter(OP_KIND)
