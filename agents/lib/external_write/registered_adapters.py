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
adapter module either). The BASELINE import set below (this file's
hand-maintained shipped content) is entirely build-emitted and static:
whichever adapter modules are LISTED HERE are the only baseline-registered
ones. Operator-enrolled adapters are a SEPARATE, explicitly segregated set —
see "Operator-enrollment segregation" below — never a dynamically resolved
string an operator or a model-authored value could redirect; the manifest
this module reads names only a MODULE, resolved the identical
`external_write.<stem>` way the baseline import below already does.

GENERATED shape
----------------
For the shipped substrate this is a hand-maintained module enumerating the
shipped ADAPTER_PROFILE modules (today: `adapters_gmail.py`, the one
reference adapter). This baseline import line is regenerated wholesale
whenever the emitted/operator project's copy of the `external_write` lib is
re-copied from a bundle template (fresh build, or a contract-changing
upgrade) — it is NEVER appended to or edited in place by
`capability_code_scaffold.py` (see "Operator-enrollment segregation" below
for why).

Operator-enrollment segregation (Task B3, Cut 1.1 Cluster B / F-76)
---------------------------------------------------------------------
Prior to this task, `wizard/scripts/lib/capability_code_scaffold.py`'s
`emit_capability_code_scaffold` (the add-capability build cascade's own
emitter) appended `import external_write.<new_module_stem>` directly INTO
this file, alongside the shipped baseline import above. That worked for a
freshly-emitted system, but this file is one of the static lib files a
contract-changing upgrade RE-COPIES wholesale from the new bundle version's
template (see `wizard/scripts/lib/agent_emitter.py`'s
`_EXTERNAL_WRITE_LIB_FILES`) — the new bundle's template of this file knows
only the SHIPPED baseline import, never an individual operator's
capability-added ones, so an upgrade silently overwrote this file and
dropped every operator-added adapter's import line with it. The adapter
module's own `.py` file, and its `adapter_profile_registry.json` zone entry
(read by `zones.py` — unaffected by this task, and already NOT part of the
bundle's lib-file copy set), both survived the upgrade untouched; only the
one line that IMPORTED the module — the thing that actually fires its
`register_adapter`/`register_contract` calls — was lost.

The fix is segregation, not a smarter merge: `capability_code_scaffold.py`
no longer writes to THIS file at all. Every capability-code-scaffold-added
adapter module's enrollment is instead recorded in a SIBLING JSON manifest,
`operator_adapters.json` (a plain JSON array of module stems, e.g.
`["adapters_acme_crm_sync"]`), living in this same directory. That manifest
is — exactly like `adapter_profile_registry.json` before it — never part of
`agent_emitter.py`'s `_EXTERNAL_WRITE_LIB_FILES` copy set, so a
contract-changing upgrade's wholesale re-copy of this file can never touch
it. `_import_operator_adapters` below reads that manifest and imports every
listed module at THIS module's own import time, UNIONING operator
registrations with the hand-maintained baseline import above — so importing
`external_write.registered_adapters` still fires every shipped AND every
operator-added adapter module's registration, exactly as before, but the
operator half of that union now lives somewhere an upgrade cannot reach. A
dropped enrollment is impossible BY CONSTRUCTION (the file that upgrade
regenerates never held it in the first place), never dependent on a
text/AST merge that could fail.

Fail-closed, mirroring `zones.py`'s own `_load_extra_adapter_profile_paths`
exactly: a missing, unreadable, malformed, non-list, or non-string manifest
entry resolves to "no operator adapters" (never an exception) — a corrupt or
absent manifest degrades to the baseline-only behavior this module already
had before Task 7, rather than breaking every OTHER capability's turnkey
import of this one module. A LISTED module stem whose file has gone missing
still raises `ModuleNotFoundError` on import, exactly as a stale baseline
import line always has — no new failure-isolation behavior is introduced for
that case.

This module's zone classification, and the `adapter_profile_registry.json`
zone-membership mechanism `zones.py` reads, are UNCHANGED by this task: an
operator-added adapter module is scanned and zoned by `scan.py` exactly like
any baseline adapter module — this manifest only affects whether the module
gets IMPORTED (registration), never whether it is exempt from a bypass
check.

Cross-reference (single-source-of-truth discipline): `wizard/scripts/lib/
capability_code_scaffold.py`'s `_REGISTERED_ADAPTERS_BASELINE` duplicates
this module's ENTIRE source (this docstring + the import line + the loader
code below) VERBATIM as its fallback-content constant (used only when a
target project's copy of this file does not exist yet) -- that module's own
boundary discipline forbids importing this package to derive it live, so it
is text, not code. If this docstring, the import line, or the loader code
changes, update that constant to match in the same commit -- a byte-equality
test in test_capability_code_scaffold.py pins the two together so a missed
update fails closed rather than silently drifting. Because this file now
carries ONLY baseline content (no capability_code_scaffold.py write path
touches it anymore), that pin covers baseline drift alone -- it never
fires because of an operator's own add-capability enrollment.

Stdlib only — no third-party dependencies.
"""

import importlib
import json
from pathlib import Path
from typing import Tuple

import external_write.adapters_gmail  # noqa: F401 -- registers the 4 shipped Gmail op_kinds.

# The sibling operator-enrollment manifest this module unions in at import
# time (see "Operator-enrollment segregation" above). Same directory as this
# file -- never a bundle-copied lib file, so a contract-changing upgrade's
# wholesale re-copy of THIS module never touches it.
_OPERATOR_ADAPTERS_FILENAME = "operator_adapters.json"


def _load_operator_adapter_module_stems(lib_dir: "Path | None" = None) -> Tuple[str, ...]:
    """Fail-closed loader for operator-enrolled adapter module stems (Task
    B3, F-76). Reads ``<lib_dir>/operator_adapters.json`` -- a plain JSON
    array of module stems (e.g. ``"adapters_acme_crm_sync"``), one per
    capability-code-scaffold-added adapter module. Returns an empty tuple
    (never raises) when the file is absent, unreadable, not valid JSON, not
    a JSON array, or contains a non-string/empty entry (that one entry is
    simply skipped, not fatal to the rest) -- mirrors ``zones.py``'s
    ``_load_extra_adapter_profile_paths`` exactly.

    `lib_dir` defaults to THIS module's own installed directory when
    omitted (the real package anchor), so production callers get the
    fully-merged operator set with zero code changes; a test passes its own
    `lib_dir` explicitly instead of relying on the process-wide default.
    """
    anchor = Path(lib_dir) if lib_dir is not None else Path(__file__).resolve().parent
    manifest_path = anchor / _OPERATOR_ADAPTERS_FILENAME
    if not manifest_path.is_file():
        return ()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return ()
    if not isinstance(data, list):
        return ()
    return tuple(stem for stem in data if isinstance(stem, str) and stem)


def _import_operator_adapters(lib_dir: "Path | None" = None) -> None:
    """Import every operator-enrolled adapter module named in
    ``operator_adapters.json`` (see `_load_operator_adapter_module_stems`),
    firing each one's module-scope `register_adapter`/`register_contract`
    call the identical way the baseline `adapters_gmail` import above
    already does. A listed stem whose module file is missing raises
    `ModuleNotFoundError` -- the same honest failure a stale baseline import
    line would already produce; this function performs no failure isolation
    beyond that (deliberately -- see this module's own docstring)."""
    for _stem in _load_operator_adapter_module_stems(lib_dir):
        importlib.import_module(f"external_write.{_stem}")


_import_operator_adapters()
