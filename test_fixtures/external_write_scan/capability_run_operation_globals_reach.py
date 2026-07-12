"""Bypass fixture (Task R8-T1): the function-introspection reflection reach
a cross-vendor re-ratification found unguarded -- `run_operation` is the
real function object defined in adapters.py, so its `__globals__` bridges
directly into the sealed kernel module namespace (where `get_dispatch`
lives). A capability that names `.__globals__` can walk straight into that
namespace by a string key, invisible to every symbol check in this module
(a Constant node, not a Name/Attribute). Must be flagged
`introspection_escape_hatch` on the `__globals__` attribute reference itself
-- this is what closes the bridge deterministically: capability code can no
longer NAME `.__globals__` at all, regardless of what it does with the
result.
"""

from external_write.adapters import run_operation


def steal_dispatch(op):
    get_dispatch = run_operation.__globals__["get_dispatch"]
    return get_dispatch(op)
