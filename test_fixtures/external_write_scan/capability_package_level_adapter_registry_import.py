"""Bypass fixture (Task R9-T1): a CAPABILITY-zone module that reaches the
adapter registry module via the PACKAGE-LEVEL import shape -- `from
external_write import adapter_registry` -- with NO symbol subsequently used
off it. `node.module == "external_write"` (bare parent package), so the
dotted-module check (`_module_matches_adapter_registry`) never inspects it,
and the module-level name `adapter_registry` is deliberately not itself a
member of `_ADAPTER_REGISTRY_SYMBOLS` (only names reachable THROUGH the
module -- get_adapter, get_dispatch, etc. -- are). Must be flagged
`adapter_module_import` regardless: capability code has no legitimate reason
to name the registry module by any import spelling, symbol use or not.
"""

from external_write import adapter_registry


def module_reference():
    return adapter_registry
