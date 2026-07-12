"""Bypass fixture (Task R11-T1, F1): the ALIASED bare-import spelling --
`import adapters_gmail as ag` -- must be flagged the same as the unaliased
form above. The scanner matches on `alias.name` (the real module path being
imported), not on the local bound name (`ag`), so an alias is no defense.
"""

import adapters_gmail as ag


def build():
    return ag.GmailMessageTrashAdapter()
