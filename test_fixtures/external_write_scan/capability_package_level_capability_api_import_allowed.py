"""Legal (Task R9-T1 negative guard): the package-level import shape applied
to the curated capability-facing surface -- `from external_write import
capability_api`. `capability_api` is neither the registry nor an
adapter-PROFILE module, so the new package-level check must NOT fire. Must
NOT be flagged.
"""

from external_write import capability_api


def run_approved(op, receipt, client):
    return capability_api.run_operation(op, receipt, client)
