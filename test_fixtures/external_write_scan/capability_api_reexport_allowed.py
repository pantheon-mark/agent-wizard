"""Legal (Task R7-T4 negative guard): the curated capability-facing surface
-- `external_write.capability_api` re-exports EXACTLY `run_operation` and
`build_read_facade`, neither of which is a banned adapter-registry symbol,
and `capability_api` is neither the adapter registry nor an adapter-profile
module. Must NOT be flagged.
"""

from external_write.capability_api import build_read_facade, run_operation


def run_approved(op, receipt, client, read_only_client):
    facade = build_read_facade("acme_sync", read_only_client)
    return run_operation(op, receipt, client), facade
