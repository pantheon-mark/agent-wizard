"""Bypass fixture (Task R9-T1): a CAPABILITY-zone module that reaches an
ADAPTER-PROFILE module via the PACKAGE-LEVEL import shape -- `from
external_write import adapters_gmail` -- instead of the dotted
`external_write.adapters_gmail` form `adapter_module_import` already caught.
This shape puts the profile submodule name in `alias.name`
("adapters_gmail") with `node.module == "external_write"` (a bare parent
package), which the dotted-module check alone never inspects. Must be
flagged `adapter_module_import`: capability code has no legitimate reason to
reach a profile module by ANY import spelling, and this shape would
otherwise let it call straight through to `adapters_gmail.GmailMessageTrashAdapter()`.
"""

from external_write import adapters_gmail


def build():
    return adapters_gmail.GmailMessageTrashAdapter()
