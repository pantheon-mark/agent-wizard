"""Bypass fixture (Task R1 / BL-1 — external-write-gate-generalization slice):
the PRE-FIX emitted CAPABILITY-zone shape that physically HOLDS the adapter's
write-credential provider as a module-level name.

Before the BL-1 fix, the capability scaffold emitted exactly this: a
CAPABILITY-zone module that imported ``write_credential_provider`` from its
adapter module and passed it into ``run_operation`` "by reference only". That
made the emitted capability code ABLE TO OBTAIN the write client (it could just
call ``write_credential_provider()`` itself), so the credential-isolation
keystone (F-33) rested on a comment convention, not an enforced invariant.

This fixture is the regression guard: the scanner MUST flag a CAPABILITY-zone
import or reference of an adapter-profile credential-provider symbol
(``credential_provider_reference``). The write credential lives ONLY in the
ADAPTER_PROFILE zone; capability code must be UNABLE to name it.
"""

from external_write.adapters import run_operation
from external_write.adapters_acme import (
    AcmeReadFacade,
    write_credential_provider,
)


def run_approved(op, receipt, *, target=None, descriptor_set=None, cap_ledger=None):
    return run_operation(
        op, receipt, None,
        target=target, descriptor_set=descriptor_set, cap_ledger=cap_ledger,
        write_credential_provider=write_credential_provider,
    )
