"""Bypass fixture (Task R1 / BL-1 residual — external-write-gate-generalization
slice): a CAPABILITY-zone module that reaches the write-capable client through
the Adapter's ``build_write_client`` method.

After the BL-1 keystone fix moved credential provisioning off a module-level
``write_credential_provider`` symbol and onto an Adapter method, the write
client was STILL reachable from capability-zone code:

    wc = get_adapter(OP_KIND).build_write_client(op)   # returns the write client

The scanner must flag this ``.build_write_client`` attribute reference as
``credential_provider_reference`` exactly as it flags the retired provider name.
The write client is provisioned ONLY inside the trusted ADAPTER_PROFILE zone,
by the concrete adapter's own ``def build_write_client`` (exempt); capability
code must be UNABLE to name that method to obtain the client.
"""

from external_write.adapter_registry import get_adapter
from external_write.adapters import run_operation

OP_KIND = "acme_sync"


def run_approved(op, receipt, *, target=None, descriptor_set=None, cap_ledger=None):
    # Capability-zone reach into the write-capable client via the adapter method.
    write_client = get_adapter(OP_KIND).build_write_client(op)
    return run_operation(
        op, receipt, write_client,
        target=target, descriptor_set=descriptor_set, cap_ledger=cap_ledger,
    )
