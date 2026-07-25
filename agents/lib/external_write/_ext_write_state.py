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

Task B (Cut 1.5 / v0.19.0) -- the reap that CLEARS a resolved bespoke-writer
entry
------------------------------------------------------------------------------
Task A above only DETECTS an open bypass; on its own it would hold a project
non-green forever, even after the operator genuinely fixes the writer. Task B
adds ``reap_resolved_writer_migrations`` -- the stateless, attribution-free
self-heal that REMOVES a bespoke-writer entry from the queue once its writer is
demonstrably resolved: either the writer file is gone, or its content changed
since pause-time AND it now passes the real bypass scan. Called from
``lifecycle_state.reconcile_state`` (fail-safe self-heal on read).

The reap consults the SAME AST bypass scanner the build-time gate uses
(``external_write.scan.scan_paths``), run with the F-3B hash-bound migration
QUARANTINE DISABLED (``project_root`` deliberately omitted -- see that function's
docstring: default ``None`` means the quarantine plays no part). This matters
because a quarantined file is inert, NOT migrated: the quarantine exempts a
listed-paused + hash-matched file from violations so the build does not deadlock,
but that same file is still the bespoke writer. The reap must see the file's REAL
verdict, so it never asks the quarantine and instead pairs the scan with an
explicit hash-CHANGED check (an unchanged file is never reaped, regardless of any
scan result).

Zoning note (Task B): adding the state-mutating reap (it REWRITES
``pending_migrations.json``) and importing a sibling kernel submodule
(``external_write.scan``) makes this module ordinary internal kernel wiring, the
same class as ``lifecycle_state.py`` -- so it is now listed in
``zones.SEALED_KERNEL_MODULE_PATHS`` (a reviewable, one-line allowlist edit).
SEALED_KERNEL membership exempts it from the CAPABILITY-zone-only import-boundary
rule (so the ``scan`` import is legitimate kernel wiring, not a bypass); it grants
NO capability the right to import this module (that allowlist is the independent
``scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES`` set), and the module still
passes every universal bypass check on its own merits (no vendor SDK, no
write-capable credential, no raw vendor mutation, no raw ``run_operation``).

Stdlib only -- no third-party dependencies (this module ships into the
operator's own runtime, agents/lib/external_write/). The only non-stdlib import is
a sibling module of this same trusted package (``external_write.scan``, itself
stdlib-only); it never imports across the build/runtime boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from external_write import scan as _scan

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


def _read_migration_queue(project_root: str) -> List[Any]:
    """The full, parsed pending-migrations queue (every entry, whatever its
    shape) under ``project_root`` -- the single fail-closed reader every consumer
    in this module goes through.

    Absent queue file -> ``[]`` (nothing queued; a NORMAL non-error input).
    Existing-but-unreadable/malformed/non-array -> raises
    ``ExternalWriteStateReadError`` (fail-closed; see module docstring) -- never a
    misleading empty list on a read failure."""
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
    return data


def _is_open_bespoke_writer_entry(entry: Any) -> bool:
    """The ONE canonical per-entry predicate: True iff ``entry`` is an OPEN
    bespoke-writer entry -- a dict whose ``writer_relpath`` is set (non-null,
    non-empty) AND whose ``status`` equals ``"pending"``.

    A non-dict individual entry is skipped (it cannot carry a ``writer_relpath``
    to act on). "set (non-null)" per the contract; an empty string is
    degenerate/not a real relpath and is treated as unset. Any other non-null
    value counts (fail-closed: an odd-shaped-but-present ``writer_relpath`` still
    blocks). A canonical-capability migration entry has ``writer_relpath is None``
    and is deliberately NOT a bespoke writer (no over-firing)."""
    if not isinstance(entry, dict):
        return False
    writer_relpath = entry.get("writer_relpath")
    if writer_relpath is None or writer_relpath == "":
        return False
    return entry.get("status") == "pending"


def open_bespoke_writer_migrations(project_root: str) -> List[Dict[str, Any]]:
    """Return the list of OPEN bespoke-writer migration entries under
    ``project_root`` -- every entry in ``agents/handoffs/pending_migrations.json``
    whose ``writer_relpath`` is set (non-null, non-empty) AND whose ``status``
    equals ``"pending"`` (see ``_is_open_bespoke_writer_entry``).

    This is the ONE canonical definition of "is there an open external-write
    bypass in this project" -- attribution-free (it deliberately ignores
    ``mechanism_id`` / any owning-capability field) and reused by every safety
    view, never re-implemented per caller.

    Absent queue file -> ``[]`` (nothing queued). Existing-but-unreadable/
    malformed -> raises ``ExternalWriteStateReadError`` (fail-closed; see module
    docstring). Never returns a misleading empty list on a read failure."""
    return [e for e in _read_migration_queue(project_root)
            if _is_open_bespoke_writer_entry(e)]


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


# ---------------------------------------------------------------------------
# Task B (Cut 1.5 / v0.19.0): stateless auto-reap of a RESOLVED bespoke-writer
# migration entry. See the module docstring's "Task B" section for the full
# rationale (why the scan runs with the quarantine DISABLED, and why zoning
# moved to SEALED_KERNEL).
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + fsync + os.replace) --
    mirrors ``lifecycle_state._atomic_write`` exactly, so a partial/failed write
    never leaves a truncated or corrupt pending-migrations queue behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="._ext_write_state.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _writer_migration_is_resolved(root: Path, entry: Dict[str, Any], writer_relpath: str) -> bool:
    """The locked reap predicate for ONE open bespoke-writer ``entry``: True iff
    the writer is demonstrably resolved --

      (the writer file no longer EXISTS) OR
      (current file hash != recorded ``paused_content_sha256`` AND the file passes
       ``scan_paths`` run with the pending-migration quarantine DISABLED).

    Fail-closed throughout -- any state that cannot be positively verified as
    resolved leaves the entry in place (returns ``False``):

    * ABSENT writer file (``FileNotFoundError``) -> resolved (the bypass is gone).
      An INACCESSIBLE-but-present file (any other ``OSError``) is NOT "no longer
      exists" -- it is unverifiable, so it is kept (distinguished via the read's
      own exception type, never ``os.path.exists``/``is_file`` which conflate the
      two).
    * No recorded ``paused_content_sha256`` (a pre-F-3B / hand-authored entry) ->
      no pause-time baseline to prove the file CHANGED, so it is kept (never
      guessed reaped).
    * current hash == recorded hash -> the file is UNCHANGED since pause-time: it
      is still the same bespoke writer, so it is kept regardless of any scan
      result (this is the case the quarantine would otherwise exempt as "clean" --
      exactly why the reap must not trust the quarantine).
    * hash changed but the (non-quarantined) scan still reports ANY violation ->
      not migrated, kept.
    * the scan itself cannot be run/verified -> kept (fail-closed).

    The hash is ``hashlib.sha256`` of the file's raw bytes -- byte-identical to
    how ``upgrade_reconcile._content_sha256`` COMPUTED and recorded
    ``paused_content_sha256`` at pause-time, and to how ``scan._quarantined_
    violations`` verifies it, so the comparison is meaningful. (Duplicated-by-value
    across the build/runtime boundary, the same discipline every path constant in
    this package follows -- ``upgrade_reconcile`` is build-side and must never be
    imported here.)"""
    writer_path = root / writer_relpath
    try:
        current_bytes = writer_path.read_bytes()
    except FileNotFoundError:
        return True   # writer file no longer exists -> resolved.
    except OSError:
        return False  # present but inaccessible -> cannot verify -> keep (fail-closed).

    recorded_hash = entry.get("paused_content_sha256")
    if not isinstance(recorded_hash, str) or not recorded_hash:
        return False  # no pause-time baseline -> cannot prove change -> keep.

    if hashlib.sha256(current_bytes).hexdigest() == recorded_hash:
        return False  # unchanged since pause-time -> still the bespoke writer -> keep.

    # Content changed since pause-time: ask the REAL scanner for its verdict, with the
    # F-3B migration quarantine DISABLED (project_root deliberately omitted -- default None
    # means the quarantine plays no part; a quarantined file is inert, not migrated). A
    # single-file scan returns only this file's violations; clean => resolved.
    try:
        violations = _scan.scan_paths([str(writer_path)])
    except Exception:
        return False  # scanner unavailable/failed -> cannot verify clean -> keep (fail-closed).
    return not violations


def reap_resolved_writer_migrations(project_root: str) -> List[str]:
    """Stateless, attribution-free self-heal: REMOVE from
    ``agents/handoffs/pending_migrations.json`` every OPEN bespoke-writer entry
    whose writer is demonstrably resolved (see ``_writer_migration_is_resolved``),
    and return the reaped entries' ``mechanism_id``s (order-preserving).

    No capability join -- it reaps on the writer's own state alone, the mirror of
    ``open_bespoke_writer_migrations``'s attribution-free detection. Only OPEN
    bespoke-writer entries are ever candidates; every other entry (canonical-
    capability entries, non-pending entries, non-dict junk) is preserved
    byte-for-value. When nothing is reaped, the queue file is left completely
    untouched (no rewrite, no timestamp churn) -- so a project with no resolved
    writer is a pure read.

    The rewrite (when there IS something to reap) is atomic (temp file +
    os.replace) so a crash mid-write never corrupts the queue. Absent queue ->
    ``[]``. Raises ``ExternalWriteStateReadError`` on an existing-but-unreadable/
    malformed queue (same fail-closed contract as ``open_bespoke_writer_
    migrations``); ``reconcile_state`` runs this best-effort, and its own
    ``build_capability_index`` state-read-error check still fail-closes a genuinely
    broken queue into a blocking ``ReconcileStateError``."""
    root = Path(project_root)
    queue = _read_migration_queue(project_root)
    reaped_ids: List[str] = []
    kept: List[Any] = []
    for entry in queue:
        if _is_open_bespoke_writer_entry(entry):
            writer_relpath = str(entry.get("writer_relpath"))
            if _writer_migration_is_resolved(root, entry, writer_relpath):
                reaped_ids.append(str(entry.get("mechanism_id")))
                continue
        kept.append(entry)

    if reaped_ids:
        _atomic_write(
            root / MIGRATION_QUEUE_REL,
            json.dumps(kept, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )
    return reaped_ids
