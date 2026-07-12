"""Legal (Task R11-T1, F1 negative guard): `from adapters import
run_operation`, bare and non-relative. `adapters` (bare) is neither the
registry nor an adapter-profile module by the first-dotted-component rule.
Must NOT be flagged `adapter_module_import`.
"""

from adapters import run_operation


def run_approved(op, receipt, client):
    return run_operation(op, receipt, client)
