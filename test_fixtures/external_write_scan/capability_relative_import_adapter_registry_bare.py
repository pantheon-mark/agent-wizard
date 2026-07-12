"""Bypass fixture (Task R10-T1, cross-vendor-verified gap): a CAPABILITY-zone
module that reaches the adapter registry module via the RELATIVE bare-import
shape -- `from . import adapter_registry` -- the relative sibling of the
package-level `from external_write import adapter_registry` form
`adapter_module_import` already caught. `node.level > 0`, `node.module is
None`, and the registry name sits in `alias.name` ("adapter_registry")
instead. No symbol is subsequently used off it. Must be flagged
`adapter_module_import` regardless: capability code has no legitimate reason
to name the registry module by any import spelling, symbol use or not.
"""

from . import adapter_registry


def module_reference():
    return adapter_registry
