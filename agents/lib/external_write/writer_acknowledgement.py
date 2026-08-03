"""Operator acknowledgement of an unrepairable bespoke writer -- the ONE sanctioned
exit from ``WriterState.NEEDS_PERSON``.

This module keeps the name and the surface it has always had, because it is already
present in every emitted operator project, is enrolled in the emitted-lib file set,
and is loaded BY NAME by the build-side upgrade reconcile's own tests. What changed
is where the code lives: the machinery split into layers so the eligibility rule
could be tightened at all.

  * ``writer_ack_store``  -- the records: persistence, the hash-validity rule, and
                             the write primitive. Imports no sibling.
  * ``writer_commands``   -- the command: validates through the structural-state
                             core, writes through the store.

Both are re-exported here, so ``from external_write import writer_acknowledgement``
still gives you ``acknowledge_writer`` / ``active_acknowledgements`` /
``ACKNOWLEDGEMENTS_REL`` / ``ACKNOWLEDGEMENT_SCHEMA`` / ``WriterAcknowledgementError``
as the SAME objects, not copies -- asserted by identity in
``test_external_write_writer_state_layers.PublicSurfaceIdentityTests``. Nothing is
re-declared here and no value is re-spelled; there is still exactly one declaration
of each name.

Why the split was necessary
---------------------------
This module used to reach back into the state module for the open-entry list so it
could refuse to record a decision about a file nothing had flagged, while the state
module reached in here for the active records so it could label an entry
``acknowledged_risk``. Both imports were function-scope, so neither ever failed at
import time and nothing in the suite noticed the cycle -- but it meant any check
this side wanted to make about a writer's STATE had to come from the module already
asking it about decisions. The state question now goes to the structural-state core,
which knows nothing about records at all.

The four properties that keep this from being a hole -- explicit, hash-bound,
visible, audited -- are documented and enforced where they live, in
``writer_ack_store``. Never a silent dismissal: the word "acknowledge" is
deliberate, because the risk is accepted and recorded, not resolved.

Enforcement ceiling (disclosure): build-time + operator-as-approver, NOT a
runtime/OS sandbox -- the same ceiling every module in this package discloses. An
acknowledgement records a decision; it does not make the writer safe.

Stdlib only -- no third-party dependencies. The only non-stdlib imports are two
sibling modules of this same trusted package.
"""

from __future__ import annotations

from external_write.writer_ack_store import (  # noqa: F401
    ACKNOWLEDGEMENT_SCHEMA,
    ACKNOWLEDGEMENTS_REL,
    WriterAcknowledgementError,
    active_acknowledgements,
)
from external_write.writer_commands import acknowledge_writer  # noqa: F401

__all__ = [
    "ACKNOWLEDGEMENTS_REL",
    "ACKNOWLEDGEMENT_SCHEMA",
    "WriterAcknowledgementError",
    "acknowledge_writer",
    "active_acknowledgements",
]
