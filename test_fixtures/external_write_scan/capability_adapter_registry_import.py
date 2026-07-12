"""Bypass fixture (Task R7-T4): a CAPABILITY-zone module that imports the
adapter registry module directly. Must be flagged BOTH `adapter_module_import`
(the import of `external_write.adapter_registry` itself) AND
`adapter_registry_reference` (the `get_adapter` symbol named by the import) --
the registry's mutable-instance reach path this task closes off from
capability code entirely. This is a legitimate reach path for SEALED_KERNEL
code only (see adapters.py / effects_manifest.py, which import this same
symbol and must NOT be flagged -- see TestAdapterRegistryKernelStaysClean).
"""

from external_write.adapter_registry import get_adapter

OP_KIND = "acme_sync"


def peek_adapter():
    return get_adapter(OP_KIND)
