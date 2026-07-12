"""Bypass fixture (Task R11-T1, F1 -- cross-vendor-ratified gap): a
CAPABILITY-zone module that reaches an ADAPTER-PROFILE module via a BARE,
non-relative `import adapters_gmail` -- no `external_write.` prefix at all,
and no relative dot either (a plain `import` statement has no `level`
concept, so the R10-T1 relative-import checks never apply to it). This is
invisible to the existing dotted-module match
(`_module_matches_adapter_registry` / `_module_matches_adapter_profile`, both
of which require an explicit `external_write` component somewhere in the
path) -- the module name here is JUST `adapters_gmail`, one bare component.
Must be flagged `adapter_module_import`.
"""

import adapters_gmail


def build():
    return adapters_gmail.GmailMessageTrashAdapter()
