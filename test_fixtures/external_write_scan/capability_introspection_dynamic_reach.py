"""Bypass fixture (Task R7-T4): CAPABILITY-zone dynamic-reach escape hatches
that could otherwise reach the banned adapter registry / adapter-profile
modules WITHOUT a static `import` statement the adapter_module_import check
would see -- `sys.modules` (the already-loaded module cache) and
`importlib.import_module` (a runtime import). Both must be flagged
`introspection_escape_hatch` regardless of what literal argument follows --
broader than `dynamic_import`, which only fires for a KNOWN-forbidden
import-root literal (an internal module name like
"external_write.adapter_registry" is not in that denylist at all).

`import importlib` itself is also flagged (root-matched, mirroring
`_FORBIDDEN_IMPORT_ROOTS`'s convention) -- three sites total in this file.
"""

import importlib
import sys


def reach_registry_via_sys_modules():
    return sys.modules["external_write.adapter_registry"]


def reach_registry_via_import_module():
    return importlib.import_module("external_write.adapter_registry")
