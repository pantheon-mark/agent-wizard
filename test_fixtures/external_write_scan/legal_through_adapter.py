"""Legal write script: routes every external mutation through the emitted
named-operation adapter. Performs NO direct network or surface-write call.

This is the shape a correct build-authored write script must take. The scanner
must report ZERO violations for this file.
"""

from agents.lib.external_write.operations import Operation
from agents.lib.external_write.adapters import run_operation


def mark_task_complete(task_id, client, receipt):
    op = Operation(
        kind="set_status",
        object_id=task_id,
        field="status",
        new_value="Complete",
    )
    # The only path to the external surface is the adapter.
    return run_operation(op, receipt, client)
