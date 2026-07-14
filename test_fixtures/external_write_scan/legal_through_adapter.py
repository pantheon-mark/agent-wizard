"""Legal write script: routes every external mutation through the sanctioned
run-envelope entrypoint (run_enveloped_operation), which internally calls the
kernel adapter primitive. Performs NO direct network or surface-write call, and
NEVER names the raw run_operation primitive (v0.12.0 S1).

This is the shape a correct build-authored write script must take. The scanner
must report ZERO violations for this file.
"""

from agents.lib.external_write.operations import Operation
from agents.lib.external_write.capability_api import run_enveloped_operation


def mark_task_complete(envelope, task_id, client, receipt):
    op = Operation(
        kind="set_status",
        object_id=task_id,
        field="status",
        new_value="Complete",
    )
    # The only path to the external surface is the run-envelope entrypoint.
    return run_enveloped_operation(envelope, op, receipt, client)
