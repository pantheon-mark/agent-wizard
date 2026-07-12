"""Bypass fixture (Task R11-T1, F1): a CAPABILITY-zone module that reaches an
ADAPTER-PROFILE module via a BARE, non-relative `from adapters_gmail import
X` -- `node.level == 0` and `node.module == "adapters_gmail"`, no
`external_write.` prefix at all. Invisible to the existing dotted-module
match (requires an explicit `external_write` component) and to the R10-T1
relative-import checks (require `node.level > 0`) -- this is the third,
previously-uncaught spelling: bare AND absolute. Must be flagged
`adapter_module_import`.
"""

from adapters_gmail import GmailMessageTrashAdapter


def build():
    return GmailMessageTrashAdapter()
