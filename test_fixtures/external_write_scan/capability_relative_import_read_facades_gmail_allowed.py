"""Legal (Task R10-T1 negative guard): the relative bare-import shape applied
to an emitted read-facade module -- `from . import read_facades_gmail`.
`read_facades_gmail` is neither the registry (`adapter_registry`) nor an
adapter-PROFILE module: it does not start with the `adapters_` prefix
(`"read_facades_gmail".startswith("adapters_")` is False), so the new
relative-import check must NOT fire. Must NOT be flagged.
"""

from . import read_facades_gmail


def build_facade(client):
    return read_facades_gmail.GmailReadFacade(client)
