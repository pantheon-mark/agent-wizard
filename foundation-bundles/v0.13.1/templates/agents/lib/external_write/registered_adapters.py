"""Static adapter-registration import list — the build-emitted static adapter
registry (Task 7, A4 / F-37 — v0.13.0 Slice 2).

The problem this closes
------------------------
`adapter_registry.register_adapter` and `contracts.register_contract` both
fire at IMPORT of an adapter module (a module-scope call — see
`adapters_gmail.py`'s own registration block, and the per-capability adapter
module `capability_code_scaffold.py` emits). `get_contract(op_kind)` and
`adapter_registry.get_dispatch(op_kind)` — the two lookups the operator-
acceptance ceremony needs to compute an operation's trust hashes — resolve
correctly ONLY after that specific adapter module has been imported at least
once in the running process.

Before this module existed, NOTHING imported a capability's adapter module on
the operator-acceptance CLI's path (`operator_acceptance.py`'s `__main__` /
`record_operator_acceptance`) — the CLI is invoked fresh, per the documented
usage in `skills/next-phase.md`'s Step 6, and a freshly-declared capability's
adapter module was never on that fresh process's import graph. The result:
the prescribed operator-acceptance command refused EVERY freshly-declared
capability with "no registered contract for op_kind ..." — a real,
plain-language refusal, not a crash, but one that made the promised turnkey
acceptance flow simply not work out of the box for anything beyond the
already-import-triggered case, with no operator-facing (or CLI-flag) way to
fix it, because the fix requires an IMPORT, not an argument.

The fix
-------
Importing THIS ONE module fires every shipped and every capability-added
adapter module's module-scope registration, in one place, before any op_kind
resolution is attempted. `operator_acceptance.py` imports it at module scope
(so both the `__main__` CLI wrapper and `record_operator_acceptance`, its
underlying runner, get the fix regardless of which one is invoked) — see that
module's own docstring for the BI-2 pre-check this enables.

No operator-controlled import string
-------------------------------------
There is deliberately no CLI flag or descriptor field naming an adapter
module to import (the descriptor's `ENTRY_KEYS` — capability_registration.
REGISTERED_ENTRY_KEYS — are unchanged by this task; op_kind is read from the
copy_run_proof, never from the descriptor, and no descriptor field names an
adapter module either). The import set is entirely build-emitted and static:
whichever adapter modules are LISTED HERE are the only ones that can ever
register — a bare-metal allowlist, not a dynamically resolved string an
operator or a model-authored value could redirect.

GENERATED shape
----------------
For the shipped substrate this is a hand-maintained module enumerating the
shipped ADAPTER_PROFILE modules (today: `adapters_gmail.py`, the one
reference adapter). `wizard/scripts/lib/capability_code_scaffold.py`'s
`emit_capability_code_scaffold` regenerates it (idempotently, appending one
import line) whenever a capability adapter is added via the add-capability
build cascade — mirroring exactly how it already regenerates the sibling
`adapter_profile_registry.json` — and asserts, BEFORE writing, that the
newly-added module's op_kind does not collide with any op_kind already
registered by a module already listed here (see
`capability_code_scaffold._update_registered_adapters` /
`_extract_registered_op_kinds`).

Importing this module has side effects (registration at import time) — that
IS the point; see `adapter_registry.py`'s own module docstring ("populated by
`register_adapter` at import time").

Cross-reference (single-source-of-truth discipline): `wizard/scripts/lib/
capability_code_scaffold.py`'s `_REGISTERED_ADAPTERS_BASELINE` duplicates
this module's ENTIRE source (this docstring + the import line below)
VERBATIM as its fallback-content constant (used only when a target project's
copy of this file does not exist yet) -- that module's own boundary
discipline forbids importing this package to derive it live, so it is text,
not code. If this docstring or the import line changes, update that constant
to match in the same commit -- a byte-equality test in
test_capability_code_scaffold.py pins the two together so a missed update
fails closed rather than silently drifting.

Stdlib only — no third-party dependencies.
"""

import external_write.adapters_gmail  # noqa: F401 -- registers the 4 shipped Gmail op_kinds.
