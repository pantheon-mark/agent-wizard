"""Bypass fixture (Task R10-T1, cross-vendor-verified gap): a CAPABILITY-zone
module that reaches an ADAPTER-PROFILE module via the RELATIVE bare-import
shape -- `from . import adapters_gmail` -- the relative sibling of the
package-level `from external_write import adapters_gmail` form
`adapter_module_import` already caught. This shape has `node.level > 0`,
`node.module is None` (a bare "from . import" has no module string at all),
and the submodule name sits in `alias.name` ("adapters_gmail") instead.
Must be flagged `adapter_module_import`: capability code has no legitimate
reason to reach a profile module by this import spelling either.
"""

from . import adapters_gmail


def build():
    return adapters_gmail.GmailMessageTrashAdapter()
