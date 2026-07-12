"""Bypass fixture (Task R11-T1, F1): bare, non-relative `from adapter_registry
import get_adapter` -- `node.level == 0`, `node.module == "adapter_registry"`,
no `external_write.` prefix. Must be flagged BOTH `adapter_module_import`
(the bare registry-module import) AND `adapter_registry_reference` (the
`get_adapter` symbol named), mirroring the dotted/relative registry-import
fixtures already covered by R7-T4/R9-T1/R10-T1.
"""

from adapter_registry import get_adapter


def reach(op_kind):
    return get_adapter(op_kind)
