"""Legal (Task R10-T1 negative guard): the relative bare-import shape applied
to the curated capability-facing surface -- `from . import capability_api`.
`capability_api` is neither the registry nor an adapter-PROFILE module, so
the new relative-import check must NOT fire. Must NOT be flagged.
"""

from . import capability_api


def run_approved(op, receipt, client):
    return capability_api.run_operation(op, receipt, client)
