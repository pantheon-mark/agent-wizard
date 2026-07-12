"""Bypass fixture (Task R8-T1): the dispatch dict a cross-vendor
re-ratification found unguarded -- `adapter_registry._DISPATCH_REGISTRY`
(the dict `get_dispatch` itself reads from) was missing from the banned
adapter-registry symbol set, even though `_REGISTRY` (the older, adapter-
keyed dict) was already banned. Must be flagged `adapter_registry_reference`
on the attribute reference alone, the same symbol-ban discipline as
`_REGISTRY` / `get_adapter` / `AdapterDispatch`.
"""

from external_write import adapter_registry

OP_KIND = "acme_sync"


def peek_dispatch_registry():
    return adapter_registry._DISPATCH_REGISTRY[OP_KIND]
