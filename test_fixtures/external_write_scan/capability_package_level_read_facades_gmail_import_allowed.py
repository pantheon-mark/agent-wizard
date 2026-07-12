"""Legal (Task R9-T1 negative guard): the package-level import shape applied
to an emitted read-facade module -- `from external_write import
read_facades_gmail`. `read_facades_gmail` is neither the registry
(`adapter_registry`) nor an adapter-PROFILE module: it does not start with
the `adapters_` prefix (`"read_facades_gmail".startswith("adapters_")` is
False), so the new package-level check must NOT fire. Must NOT be flagged.
"""

from external_write import read_facades_gmail


def build_facade(client):
    return read_facades_gmail.GmailReadFacade(client)
