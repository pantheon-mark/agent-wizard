"""External-write bypass state predicate (Cut 1.5 / bundle v0.19.0, Task A --
V15-3 false-green keystone).

Why this exists
----------------
An operator project's pending-migration queue
(``agents/handoffs/pending_migrations.json``) can carry a "bespoke writer"
entry: a hand-rolled per-chunk write loop (e.g. the estate's
``agents/inbox/runner.py`` bulk ``mint_run_envelope`` loop) that bypasses the
sanctioned, gated bulk write path (``run_sanctioned_bulk``) and was flagged
non-conformant on upgrade. Such an entry is keyed on a RELPATH-DERIVED
``mechanism_id`` (via ``upgrade_reconcile._migration_identity``) with NO
owning-capability field -- so the three id-keyed safety views
(``capability_health._is_pending_migration`` / ``overall_status`` and
``lifecycle_state.check_completion``) were structurally BLIND to it: a project
with an OPEN bypass reported green/done anyway (V15-3, source-verified).

This module defines the ONE canonical predicate those views (and later Cut 1.5
tasks B/C/E) consume to close that hole with a coarse, fail-closed, PROJECT-WIDE
block: safety must NOT depend on attributing the writer back to a capability
(that attribution is a separate, advisory-only concern) -- the mere EXISTENCE of
any open bespoke-writer entry makes the whole project non-green.

What a "bespoke writer" entry IS
--------------------------------
An entry in the pending-migrations queue where ``writer_relpath`` is set
(non-null, non-empty) AND ``status == "pending"``. A canonical-capability
migration entry has ``writer_relpath is None`` (see
``upgrade_reconcile._append_migration_request`` / the ``MechanismReport``
schema) and is NOT a bespoke writer -- it is already covered by the id-keyed
views and must never trip this block (no over-firing).

Fail-closed contract (deliberate)
----------------------------------
* A genuinely ABSENT queue file is a NORMAL, non-error input: there is nothing
  queued, so there is no open bypass -> returns ``[]``. "Absent" and
  "unreadable" are never conflated (the same distinction every other reader in
  this package draws).
* An EXISTING-but-unreadable/malformed queue file (an ``OSError`` other than
  ``FileNotFoundError``, invalid JSON, or a top-level shape that is not a JSON
  array) must NEVER silently collapse to "no open entries" and thus a false
  green -- doing so is exactly the failure mode this predicate exists to close.
  It RAISES ``ExternalWriteStateReadError``; every caller treats that raise as
  NON-GREEN (blocking), never as a clean bill of health.
* A non-dict individual entry is skipped (it cannot carry a ``writer_relpath``
  to act on) -- per-entry tolerance mirrors ``capability_health.
  _is_pending_migration``; only the top-level structural failures above raise.

Enforcement ceiling (disclosure): this is build-time + operator-as-approver
enforcement, NOT a runtime/OS sandbox -- the same ceiling every module in this
package discloses. This predicate reports a state; the gate/health views that
consume it are what decline to say "done"/"normal".

Stdlib only -- no third-party dependencies (this module ships into the
operator's own runtime, agents/lib/external_write/). It imports NOTHING from the
``external_write`` package itself; it only reads one JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

# Duplicated-by-value from lifecycle_state.MIGRATION_QUEUE_REL /
# capability_health.MIGRATION_QUEUE_REL / upgrade_reconcile.MIGRATION_QUEUE_REL
# (never imported across the build/runtime boundary -- same discipline as every
# other path constant in this package).
MIGRATION_QUEUE_REL = "agents/handoffs/pending_migrations.json"


class ExternalWriteStateReadError(Exception):
    """The pending-migrations queue EXISTS but could not be read/parsed. Raised
    (never swallowed) so a read failure can never present as "no open bypass"
    (a false green). Callers treat this as NON-GREEN, exactly like a confirmed
    open bypass -- fail-closed."""


def open_bespoke_writer_migrations(project_root: str) -> List[Dict[str, Any]]:
    """Return the list of OPEN bespoke-writer migration entries under
    ``project_root`` -- every entry in ``agents/handoffs/pending_migrations.json``
    whose ``writer_relpath`` is set (non-null, non-empty) AND whose ``status``
    equals ``"pending"``.

    This is the ONE canonical definition of "is there an open external-write
    bypass in this project" -- attribution-free (it deliberately ignores
    ``mechanism_id`` / any owning-capability field) and reused by every safety
    view, never re-implemented per caller.

    Absent queue file -> ``[]`` (nothing queued). Existing-but-unreadable/
    malformed -> raises ``ExternalWriteStateReadError`` (fail-closed; see module
    docstring). Never returns a misleading empty list on a read failure."""
    path = Path(project_root) / MIGRATION_QUEUE_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ExternalWriteStateReadError(
            f"pending-migrations queue {path} exists but could not be read: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ExternalWriteStateReadError(
            f"pending-migrations queue {path} exists but is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ExternalWriteStateReadError(
            f"pending-migrations queue {path} exists but is not a JSON array")

    open_bespoke: List[Dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        writer_relpath = entry.get("writer_relpath")
        # "set (non-null)" per the contract; an empty string is degenerate/not a
        # real relpath and is treated as unset. Any other non-null value counts
        # (fail-closed: an odd-shaped-but-present writer_relpath still blocks).
        if writer_relpath is None or writer_relpath == "":
            continue
        if entry.get("status") == "pending":
            open_bespoke.append(entry)
    return open_bespoke


def open_bespoke_writer_relpaths(project_root: str) -> List[str]:
    """Convenience projection over ``open_bespoke_writer_migrations``: the sorted,
    de-duplicated ``writer_relpath`` string(s) of every open bespoke-writer entry
    -- the plain-language "fix this file" list a gate/health view names to the
    operator. Raises ``ExternalWriteStateReadError`` on an unreadable queue, same
    fail-closed contract as the predicate it derives from."""
    return sorted({
        str(e.get("writer_relpath"))
        for e in open_bespoke_writer_migrations(project_root)
    })
