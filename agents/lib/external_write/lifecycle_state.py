"""Emitted lifecycle-state reconciler (Task B1, Phase 3 Cut 1).

Why this exists
----------------
Before this module, a capability's paused/live state was tracked in THREE places that could
independently drift out of sync: the descriptor's ``accepted`` flag
(``security/capability_descriptors.json``), the runtime pause marker
(``.wizard/paused-mechanisms/<canonical_id>.{pause,json}`` -- read by
``write_gate._load_paused_op_kinds`` to deny live writes), and the pending-migration queue
(``agents/handoffs/pending_migrations.json``). A crash between two of those writes (or a manual
edit to one of them) could leave a capability ``accepted: true`` in its descriptor while a stale
pause marker still denied its writes at runtime -- or ``accepted: false`` with no marker at all,
silently permitting nothing to deny it (write_gate's ACCEPTED-descriptor branch still gates on
``accepted``, but a capability that races between "not yet accepted" and "was paused, needs
remigration" is exactly the confusable state this module exists to make impossible).

The fix: ``descriptor.accepted`` is declared the SINGLE SOURCE OF TRUTH. The pause marker and the
pending-migration queue are MATERIALIZED VIEWS, re-derived from that one field (and from whether
a migration is genuinely queued) by ``reconcile_state`` -- ONE idempotent, safely-re-runnable
function. Coherent paused state is exactly ``accepted: false`` + a pause marker + a queued
migration entry, all three together or none of them -- an ``accepted: true`` descriptor with a
still-present pause marker (or a lingering queued migration) is exactly the limbo this function
exists to close on every call.

``reconcile_state`` NEVER flips ``accepted`` itself -- that is the sanctioned resume/complete
tool's job (a later task). This module only makes the two materialized views agree with whatever
``accepted`` (and the migration queue) already say.

Fail-closed on broken state (never guesses over a corrupt file)
------------------------------------------------------------------------------
``build_capability_index`` (this package's own identity resolver) can detect that the descriptor
set or the migration queue file EXISTS but could not be read/parsed
(``CapabilityIndex.state_read_error``). When that is true, this module refuses to reconcile at
all and raises ``ReconcileStateError`` with a plain-language ``.operator_message`` (no traceback)
-- silently treating a broken state file as "no entry" could clear a marker (or leave one
missing) based on a picture that is actually incomplete, exactly the false-all-clear failure
class ``capability_health.py`` and ``write_gate.py`` already refuse to produce elsewhere in this
package. A ``canonical_id`` that does not resolve to a real capability module on disk raises
``external_write.capability_identity.IdentityResolutionError`` (already plain-language,
no traceback) -- this module does not wrap it further.

Reuse, not duplication, where a sanctioned primitive already exists
------------------------------------------------------------------------------
Closing a pending-migration entry reuses ``operator_acceptance.close_pending_migration_if_matched``
directly (same package, genuinely importable) rather than re-implementing the identity-corroborated
match-and-remove logic a second time. Resolving a raw name to its canonical identity reuses
``capability_identity.build_capability_index`` the same way every other lifecycle consumer in this
package does.

The pause-marker WRITE shape, by contrast, is duplicated-by-value from
``wizard/scripts/lib/upgrade_reconcile.py``'s ``_write_paused_live_write_state`` (never imported --
that module is BUILD-SIDE and this one ships into the operator's own runtime; the same
never-import-across-the-build/runtime-boundary discipline this package already documents
repeatedly, e.g. ``capability_identity.py``'s own module docstring and the
``DESCRIPTOR_SET_REL`` / ``MIGRATION_QUEUE_REL`` / ``PAUSED_MECHANISMS_DIR_REL`` constants
duplicated across ``write_gate.py`` / ``capability_health.py`` / ``capability_identity.py`` /
``upgrade_reconcile.py``). This module's own writer adds ONE new field the pre-existing shape
never carried: ``canonical_id`` (Task B1's A4-fold requirement) -- so a later evidence-bound
clearing check can verify a marker names the exact capability it claims to gate, regardless of
which of the two writers (this module, or the build-side upgrade-reconcile auto-pause) produced
it. ``write_gate._load_paused_op_kinds`` reads ONLY the ``paused_op_kinds`` key from each marker
file and ignores every other key present -- an added ``canonical_id`` key is inert to it (see
that function's own docstring: "A missing paused_op_kinds KEY ... is NOT malformed"; the
converse -- an extra key present -- is equally harmless, confirmed by reading its body, which
never enumerates or rejects unrecognized keys).

Idempotent by construction
------------------------------------------------------------------------------
Every write here first computes the DESIRED on-disk shape and compares it against what already
exists; a write only happens when they differ. A second call against unchanged inputs therefore
performs zero writes -- ``ReconcileResult.changed`` is ``False``, and the pause-marker directory,
the descriptor set, and the migration queue are byte-identical to the first call's result. This
is also what makes ``reconcile_state`` safe to re-run after a crash: whichever of the two ensured
writes (marker, migration-close) did not complete before the crash is simply retried, and
whichever one DID complete is left untouched, not rewritten with a new timestamp.

Stdlib only -- this module ships into the operator's own runtime, ``agents/lib/external_write/``.
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

# sys.path bootstrap (mirrors operator_acceptance.py / capability_registration.py): make the
# package parent importable when run as a direct script from the project root, so the sibling
# ``external_write.*`` imports resolve.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.capability_identity import (  # noqa: E402
    build_capability_index,
    CAPABILITIES_DIR_REL,
    CAPABILITY_FILE_SUFFIX,
    CapabilityIdentity,
    IdentityResolutionError,
)
from external_write.operator_acceptance import (  # noqa: E402
    close_pending_migration_if_matched,
)

# ---------------------------------------------------------------------------
# Project-root-relative locations this module reads/writes. Duplicated-by-value
# (never imported cross-module -- see module docstring) from the same-named
# constants in capability_health.py / capability_identity.py / write_gate.py /
# upgrade_reconcile.py.
# ---------------------------------------------------------------------------

DESCRIPTOR_SET_REL = "security/capability_descriptors.json"
MIGRATION_QUEUE_REL = "agents/handoffs/pending_migrations.json"
PAUSED_MECHANISMS_DIR_REL = ".wizard/paused-mechanisms"


class ReconcileStateError(Exception):
    """Raised by ``reconcile_state`` when the descriptor set or the pending-migration queue
    EXISTS but could not be read/parsed -- fail-closed: reconciling over a state file that
    might be hiding the true picture (an entry the corrupt file happens to be masking) risks
    clearing a marker that should stay, or leaving one missing that should exist. Plain-language
    ``.operator_message``, no traceback text -- this is read by whatever orchestrates the
    sanctioned resume/complete tool, never surfaced as a raw Python exception."""

    def __init__(self, operator_message: str) -> None:
        self.operator_message = operator_message
        super().__init__(operator_message)


@dataclass(frozen=True)
class ReconcileResult:
    """Outcome of one ``reconcile_state`` call.

    canonical_id:     the resolved canonical capability id this call reconciled.
    accepted:         the SSOT value read from the descriptor's ``accepted`` field for this
                       capability (``False`` when no descriptor entry exists at all).
    marker_present:   True iff a pause marker exists for this capability AFTER this call.
    migration_open:   True iff the pending-migration queue still carries an entry for this
                       capability AFTER this call.
    changed:          True iff this call actually wrote/removed anything on disk. A second,
                       back-to-back call against unchanged inputs always yields ``False`` here
                       (see module docstring's "Idempotent by construction").
    """
    canonical_id: str
    accepted: bool
    marker_present: bool
    migration_open: bool
    changed: bool


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + os.replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".lifecycle_state.", suffix=".tmp", dir=str(path.parent))
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


def _load_descriptor_set(root: Path) -> List[Dict[str, Any]]:
    """Fail-safe loader for the FULL descriptor entry list (mirrors
    ``write_gate.load_descriptor_set`` / ``upgrade_reconcile._load_capability_descriptor_set``'s
    own fail-safe convention: absent/unreadable/malformed/non-array all resolve to ``[]``).
    Only reached after the caller has already confirmed (via
    ``CapabilityIndex.state_read_error``) that this same file is not present-but-broken, so a
    further exception here is unexpected -- kept anyway as defense in depth, never a raise."""
    path = root / DESCRIPTOR_SET_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _load_migration_queue(root: Path) -> List[Dict[str, Any]]:
    """Fail-safe loader for the pending-migration queue's full entry list -- same convention
    and same "already confirmed not present-but-broken" precondition as ``_load_descriptor_set``
    above."""
    path = root / MIGRATION_QUEUE_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _find_descriptor_entry(descriptor_set: List[Dict[str, Any]],
                            aliases: FrozenSet[str]) -> Optional[Dict[str, Any]]:
    """The descriptor entry (if any) whose ``id`` is one of this capability's known aliases.
    ``aliases`` is the authoritative membership set from ``CapabilityIdentity`` -- never just
    the bare canonical id (see that dataclass's own docstring on why ``descriptor_id`` alone is
    not exhaustive)."""
    for entry in descriptor_set:
        if isinstance(entry, dict) and entry.get("id") in aliases:
            return entry
    return None


def _migration_open(migration_queue: List[Dict[str, Any]], aliases: FrozenSet[str]) -> bool:
    """True iff the pending-migration queue carries at least one entry whose ``mechanism_id``
    is one of this capability's known aliases."""
    return any(
        isinstance(e, dict) and e.get("mechanism_id") in aliases for e in migration_queue
    )


def _extract_op_kind_literal(source_text: str) -> List[str]:
    """Statically extract a module-level ``OP_KIND = "<literal>"`` string assignment from a
    capability module's own source -- AST parse only, NEVER imported/executed. Duplicated-by-value
    from ``upgrade_reconcile._extract_op_kind_literal`` (see module docstring's "Reuse, not
    duplication" section on why the WRITE shape is duplicated rather than imported across the
    build/runtime boundary). Module-level only (``tree.body``, not ``ast.walk``) -- matches the
    real emitted form (``capability_code_scaffold.py``'s ``render_capability_module`` always
    writes ``OP_KIND = "..."`` at module scope). Returns ``[]`` when the source does not parse,
    the file cannot be read, or no such literal assignment is present -- fail-closed/empty-safe,
    never guesses."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "OP_KIND":
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return [value.value]
    return []


def _resolve_op_kinds(root: Path, canonical_id: str) -> List[str]:
    """The ``paused_op_kinds`` to record for ``canonical_id`` -- read from the capability's own
    module source at its canonical, module-derived path
    (``agents/capabilities/<canonical_id>_capability.py`` -- guaranteed to exist here, since
    resolving ``canonical_id`` via the module_stem namespace already requires that exact file to
    be on disk). Empty-safe: an unreadable/unparsable file or a module carrying no ``OP_KIND``
    literal yields ``[]``, never a fabricated value."""
    path = root / CAPABILITIES_DIR_REL / f"{canonical_id}{CAPABILITY_FILE_SUFFIX}"
    try:
        source_text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return _extract_op_kind_literal(source_text)


def _pause_marker_path(root: Path, canonical_id: str) -> Path:
    return root / PAUSED_MECHANISMS_DIR_REL / f"{canonical_id}.pause"


def _pause_state_path(root: Path, canonical_id: str) -> Path:
    return root / PAUSED_MECHANISMS_DIR_REL / f"{canonical_id}.json"


def _read_existing_marker_state(root: Path, canonical_id: str) -> Optional[Dict[str, Any]]:
    path = _pause_state_path(root, canonical_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _ensure_paused_marker(root: Path, canonical_id: str, paused_op_kinds: List[str]) -> bool:
    """Ensure a pause marker exists for ``canonical_id`` with the given ``paused_op_kinds`` AND
    the resolved ``canonical_id`` recorded alongside it (Task B1's A4-fold requirement).

    Idempotent: computes the desired ``.json`` state and only rewrites when the existing one
    (if any) does not already match -- a second call against the same inputs performs no write
    (see module docstring). The ``.pause`` touch-file sentinel is created once and never
    rewritten (it carries no content to compare). Returns True iff anything was written this
    call."""
    changed = False
    marker_dir = root / PAUSED_MECHANISMS_DIR_REL
    pause_path = _pause_marker_path(root, canonical_id)
    if not pause_path.exists():
        marker_dir.mkdir(parents=True, exist_ok=True)
        pause_path.write_text("", encoding="utf-8")
        changed = True

    desired_op_kinds = list(paused_op_kinds)
    existing = _read_existing_marker_state(root, canonical_id)
    already_correct = (
        existing is not None
        and existing.get("canonical_id") == canonical_id
        and existing.get("mechanism_id") == canonical_id
        and existing.get("paused_op_kinds") == desired_op_kinds
        and existing.get("state") == "paused_live_write"
    )
    if not already_correct:
        state = {
            "mechanism_id": canonical_id,
            "canonical_id": canonical_id,
            "writer_relpath": f"{CAPABILITIES_DIR_REL}/{canonical_id}{CAPABILITY_FILE_SUFFIX}",
            "entrypoint_relpath": None,
            "state": "paused_live_write",
            "paused_op_kinds": desired_op_kinds,
            "paused_at": (existing or {}).get("paused_at") or _utcnow_iso(),
            "reason": "capability descriptor not accepted; migration pending (reconcile_state)",
            "credentials_preserved": True,
            "migration_status": "pending",
        }
        _atomic_write(
            _pause_state_path(root, canonical_id),
            json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        )
        changed = True
    return changed


def _clear_paused_marker(root: Path, canonical_id: str) -> bool:
    """Remove both marker files for ``canonical_id`` if present. Idempotent: a second call
    against an already-clear marker directory performs no filesystem write and returns False.
    "Un-pausing is a side effect of reconciling accepted:true" -- mirrors
    ``upgrade_reconcile.py``'s own documented convention that clearing a marker is exactly
    deleting it, never editing it in place."""
    changed = False
    for path in (_pause_marker_path(root, canonical_id), _pause_state_path(root, canonical_id)):
        if path.exists():
            path.unlink()
            changed = True
    return changed


def reconcile_state(project_root: str, canonical_id: str) -> ReconcileResult:
    """Read the SSOT (``descriptor.accepted`` for ``canonical_id``, resolved via
    ``capability_identity``) and make the materialized views (the pause marker, the
    pending-migration queue) MATCH it:

      * **not accepted** AND a migration is pending for this capability -> ensure the pause
        marker exists, keyed by ``canonical_id`` with the correct ``paused_op_kinds`` (and the
        new ``canonical_id`` field). The migration entry is left as-is (it is already queued --
        this branch never fabricates a queue entry from nothing; see module docstring).
      * **accepted** -> ensure the pause marker is cleared AND any matching pending-migration
        entry is closed (via ``operator_acceptance.close_pending_migration_if_matched``),
        regardless of whether a migration happened to still be queued.
      * **not accepted** AND no migration is queued -> nothing to reconcile (a capability that
        has simply never been accepted yet is not "paused"; no marker is written for it).

    Never flips ``accepted`` itself -- see module docstring. Fully idempotent: a second call
    with unchanged inputs yields ``changed=False`` and touches nothing on disk.

    Raises ``external_write.capability_identity.IdentityResolutionError`` if ``canonical_id``
    does not resolve to a real capability module on disk (already plain-language, no traceback --
    see that exception's own ``.operator_message``). Raises ``ReconcileStateError`` (plain
    language, no traceback) if the descriptor set or the pending-migration queue exists but
    could not be read/parsed -- reconciling over an unverifiable picture is refused rather than
    guessed (see module docstring's "Fail-closed on broken state").
    """
    root = Path(project_root).resolve()
    index = build_capability_index(str(root))
    if index.state_read_error:
        raise ReconcileStateError(
            "Could not safely check this capability's paused/migration state because the "
            "capability descriptor list (security/capability_descriptors.json) or the "
            "pending-migrations queue (agents/handoffs/pending_migrations.json) exists but "
            "could not be read or is corrupted. This is NOT confirmation that nothing is "
            "wrong -- repair or restore that file, then try again."
        )

    identity: CapabilityIdentity = index.resolve(canonical_id, "module_stem")
    aliases = identity.aliases

    descriptor_set = _load_descriptor_set(root)
    entry = _find_descriptor_entry(descriptor_set, aliases)
    accepted = bool(entry.get("accepted")) if entry else False

    migration_queue = _load_migration_queue(root)
    migration_open_before = _migration_open(migration_queue, aliases)

    if accepted:
        marker_changed = _clear_paused_marker(root, identity.canonical_id)
        migration_queue_path = str(root / MIGRATION_QUEUE_REL)
        close_result = close_pending_migration_if_matched(
            identity.canonical_id, migration_queue_path, project_root=str(root),
        )
        changed = marker_changed or close_result.closed
        # Re-check after the close attempt rather than assuming success -- an ambiguous
        # identity-resolution note leaves the entry in place, and that must be reported
        # honestly, never fabricated as closed.
        migration_open_after = _migration_open(_load_migration_queue(root), aliases)
        return ReconcileResult(
            canonical_id=identity.canonical_id, accepted=True,
            marker_present=False, migration_open=migration_open_after, changed=changed,
        )

    if migration_open_before:
        paused_op_kinds = _resolve_op_kinds(root, identity.canonical_id)
        marker_changed = _ensure_paused_marker(root, identity.canonical_id, paused_op_kinds)
        return ReconcileResult(
            canonical_id=identity.canonical_id, accepted=False,
            marker_present=True, migration_open=True, changed=marker_changed,
        )

    # Not accepted, nothing queued: never accepted yet -- nothing to reconcile.
    marker_present = _pause_marker_path(root, identity.canonical_id).exists() or (
        _pause_state_path(root, identity.canonical_id).exists()
    )
    return ReconcileResult(
        canonical_id=identity.canonical_id, accepted=False,
        marker_present=marker_present, migration_open=False, changed=False,
    )
