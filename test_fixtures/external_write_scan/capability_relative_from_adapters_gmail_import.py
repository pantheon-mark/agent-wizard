"""Bypass fixture (Task R10-T1, cross-vendor-verified gap): a CAPABILITY-zone
module that reaches an ADAPTER-PROFILE module via the RELATIVE import shape
-- `from .adapters_gmail import GmailMessageTrashAdapter` -- instead of the
absolute `external_write.adapters_gmail` / package-level `from external_write
import adapters_gmail` forms `adapter_module_import` already caught. This
shape has `node.level > 0` and `node.module == "adapters_gmail"` (the
submodule name, with no `external_write.` prefix at all, since a relative
import never spells the package name). A file physically inside
external_write/ is CAPABILITY-classified by fail-closed zoning unless
explicitly listed as SEALED_KERNEL/ADAPTER_PROFILE, so this relative sibling
import is a plausible drift shape reaching adapter-profile code. Must be
flagged `adapter_module_import`.
"""

from .adapters_gmail import GmailMessageTrashAdapter


def build():
    return GmailMessageTrashAdapter()
