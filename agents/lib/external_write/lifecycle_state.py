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

Conformant-rebuild acceptance-hash staleness (Task B2b, Phase 3 Cut 1)
------------------------------------------------------------------------------
B2 (``upgrade_reconcile._reset_accepted_for_scanner_red_capability``) closes the F-62 trust gap
for a rebuilt capability the AST bypass scanner finds RED. It does not close the OTHER half: a
capability whose code changed since acceptance but KEPT its ``run_operation`` /
``run_enveloped_operation`` call shape stays scanner-clean forever, so it never enters that
scanner-driven reset path at all -- yet its descriptor can still carry a now-stale
``accepted: true``, because ``write_gate`` authorizes on ``accepted is True`` alone and never
re-checks ``implementation_hash``.

``acceptance_hash_is_stale`` is the detector: True iff a capability is currently accepted AND its
freshly recomputed ``proof_hash.compute_implementation_hash`` no longer matches the
``implementation_hash`` recorded in its own acceptance audit record (the durable JSONL log
``acceptance_ceremony`` appends to on every successful flip -- see that module's own
``ACCEPTANCE_RECORD_SCHEMA`` / ``DEFAULT_AUDIT_LOG_PATH``). ``revoke_stale_acceptance`` is the
revoker: when the detector reports stale it forces ``accepted`` back to ``False`` (atomic write,
same convention as ``upgrade_reconcile``'s own reset), queues a re-trial entry in the
pending-migration queue, and then calls ``reconcile_state`` (reused, not duplicated) so the pause
marker/migration-queue materialized views become coherent with the just-revoked SSOT. This is a
DELIBERATE, DISCLOSED exception to ``reconcile_state``'s own "never flips accepted" contract
above -- ``reconcile_state`` itself is UNCHANGED (it still never flips accepted); the flip lives
here, in a separate, explicitly-named function, exactly mirroring how ``upgrade_reconcile.py``'s
B2 reset is a separate step from its own call into (plain) ``reconcile_state``.

Fail-safe direction (never silently keep accepted:true): if the accepted hash cannot be read (no
matching acceptance record, an unreadable/malformed audit log, or a malformed record) OR the
current hash cannot be recomputed (``proof_hash.ProofHashError`` -- an unregistered op_kind or a
missing dependency file), the capability is treated as STALE and revoked. A capability that was
never accepted, or whose hashes still match, is left completely undisturbed (idempotent).

CEILING (disclosed, must stay honest in any operator-facing prose): detection runs at
reconcile/completion-check time -- once per upgrade-reconcile pass or per explicit
``revoke_stale_acceptance`` call -- NEVER per-write. A stale acceptance stays live (write_gate
would still authorize it) until the next such check runs. This is the SAME ceiling
``acceptance_ceremony`` and ``proof_hash`` already disclose (build-time + operator-as-approver,
not a runtime/OS guarantee), extended to this revocation path.

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
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

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
from external_write.proof_hash import (  # noqa: E402
    compute_implementation_hash,
    ProofHashError,
)

# ---------------------------------------------------------------------------
# Project-root-relative locations this module reads/writes. Duplicated-by-value
# (never imported cross-module -- see module docstring) from the same-named
# constants in capability_health.py / capability_identity.py / write_gate.py /
# upgrade_reconcile.py.
# ---------------------------------------------------------------------------

DESCRIPTOR_SET_REL = "security/capability_descriptors.json"
MIGRATION_QUEUE_REL = "agents/handoffs/pending_migrations.json"
# (Task B2b) Duplicated-by-value from acceptance_ceremony.DEFAULT_AUDIT_LOG_PATH -- this module
# does not import acceptance_ceremony (no need to; it only ever READS this append-only log, never
# writes to it -- the ceremony remains the sole writer of an acceptance record).
ACCEPTANCE_LOG_REL = "security/capability_acceptance_log.jsonl"
# (Task B2b) Duplicated-by-value from acceptance_ceremony.PHASE_ID_KEY -- same "read-only,
# no import needed" rationale as ACCEPTANCE_LOG_REL above.
PHASE_ID_KEY = "phase_id"
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


def _fresh_marker_state(canonical_id: str, desired_op_kinds: List[str]) -> Dict[str, Any]:
    """The full marker shape written when NO prior marker exists at all for ``canonical_id``."""
    return {
        "mechanism_id": canonical_id,
        "canonical_id": canonical_id,
        "writer_relpath": f"{CAPABILITIES_DIR_REL}/{canonical_id}{CAPABILITY_FILE_SUFFIX}",
        "entrypoint_relpath": None,
        "state": "paused_live_write",
        "paused_op_kinds": desired_op_kinds,
        "paused_at": _utcnow_iso(),
        "reason": "capability descriptor not accepted; migration pending (reconcile_state)",
        "credentials_preserved": True,
        "migration_status": "pending",
    }


def _merge_marker_state(existing: Dict[str, Any], canonical_id: str,
                         desired_op_kinds: List[str]) -> Dict[str, Any]:
    """(Coordinator review, must-fix #1) MERGE onto an existing marker -- never replace it
    wholesale. The COMMON case this exists for: a marker written by
    ``upgrade_reconcile._write_paused_live_write_state`` at upgrade time carries diagnostic
    fields this module knows nothing about (``from_version``, ``to_version``, ``violations``,
    a specific upgrade-time ``reason``) and, being written before this task, carries NO
    ``canonical_id``. A full-rewrite would silently destroy which-upgrade-introduced-the-
    violation context the first time ``reconcile_state`` ever touched that marker.

    Every existing key is preserved untouched EXCEPT ``mechanism_id``/``canonical_id`` (set to
    the resolved canonical id -- back-filling ``canonical_id`` onto a pre-B1 marker is exactly
    the point) and ``paused_op_kinds`` (refreshed if the capability's own ``OP_KIND`` changed
    since the marker was written). ``setdefault`` fills in any of this module's own baseline
    keys a hand-seeded or unusually minimal existing marker happens to be missing -- it never
    overwrites a key already present."""
    merged = dict(existing)
    merged["mechanism_id"] = canonical_id
    merged["canonical_id"] = canonical_id
    merged["paused_op_kinds"] = desired_op_kinds
    merged.setdefault("writer_relpath", f"{CAPABILITIES_DIR_REL}/{canonical_id}{CAPABILITY_FILE_SUFFIX}")
    merged.setdefault("entrypoint_relpath", None)
    merged.setdefault("state", "paused_live_write")
    merged.setdefault("paused_at", _utcnow_iso())
    merged.setdefault(
        "reason", "capability descriptor not accepted; migration pending (reconcile_state)")
    merged.setdefault("credentials_preserved", True)
    merged.setdefault("migration_status", "pending")
    return merged


def _ensure_paused_marker(root: Path, canonical_id: str, paused_op_kinds: List[str]) -> bool:
    """Ensure a pause marker exists for ``canonical_id`` with the given ``paused_op_kinds`` AND
    the resolved ``canonical_id`` recorded alongside it (Task B1's A4-fold requirement).

    MERGES onto an existing marker rather than replacing it wholesale (see
    ``_merge_marker_state``'s own docstring) -- a marker this module did not itself write (the
    common case: one written by the build-side upgrade-reconcile auto-pause at upgrade time)
    carries diagnostic fields this function must never discard.

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

    if existing is None:
        state = _fresh_marker_state(canonical_id, desired_op_kinds)
    else:
        already_correct = (
            existing.get("canonical_id") == canonical_id
            and existing.get("mechanism_id") == canonical_id
            and existing.get("paused_op_kinds") == desired_op_kinds
        )
        if already_correct:
            return changed
        state = _merge_marker_state(existing, canonical_id, desired_op_kinds)

    _atomic_write(
        _pause_state_path(root, canonical_id),
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    return True


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


# ---------------------------------------------------------------------------
# Task B2b: conformant-rebuild acceptance-hash staleness detection + revocation.
# See the module docstring's "Conformant-rebuild acceptance-hash staleness" section for the
# full rationale. ``reconcile_state`` above is left completely UNCHANGED (still never flips
# ``accepted``) -- the flip lives in ``revoke_stale_acceptance`` below, a separate, explicitly
# fail-safe function.
# ---------------------------------------------------------------------------

# The plain-language note surfaced to the operator on a revocation -- no jargon, no internal
# identifiers, no traceback text. Deliberately the SAME wording whether the capability's code was
# CONFIRMED changed or its acceptance simply could not be VERIFIED current (fail-safe direction,
# see module docstring) -- the operator does not need to distinguish the two; both mean "off until
# you re-trial and re-approve it."
STALE_ACCEPTANCE_NOTE = (
    "This capability's code changed since you approved it, so its approval has been switched "
    "back off. It will not run live again until you try it again and approve it again."
)


def _read_latest_acceptance_record(
    root: Path, aliases: FrozenSet[str], phase_id: Optional[str],
    audit_log_path: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """The most recent acceptance-audit record (``acceptance_ceremony``'s append-only JSONL log,
    ``ACCEPTANCE_LOG_REL`` by default) for a capability known by any of ``aliases`` -- "the CURRENT
    accepted record for a capability's accepted phase" (this task's brief). Preference order: the
    latest record whose own ``phase_id`` matches the descriptor's CURRENT ``phase_id`` (when one is
    given), else the latest record for the capability regardless of phase.

    Returns ``(record_or_None, read_error)``. ``read_error`` is True ONLY when the log file EXISTS
    but could not be opened at all (a present-but-unreadable file) -- distinct from a normal,
    non-error ABSENT file (``FileNotFoundError`` -> ``(None, False)``, mirroring every other
    fail-safe loader in this module). A malformed INDIVIDUAL line is skipped, not treated as a
    whole-file read error -- an append-only log surviving a partial write on one line must not lose
    every other, otherwise-good, line's evidence.

    Never raises."""
    path = Path(audit_log_path) if audit_log_path else (root / ACCEPTANCE_LOG_REL)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, False
    except OSError:
        return None, True

    latest_any: Optional[Dict[str, Any]] = None
    latest_phase_matched: Optional[Dict[str, Any]] = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("capability_id") not in aliases:
            continue
        latest_any = rec
        if phase_id is not None and rec.get("phase_id") == phase_id:
            latest_phase_matched = rec
    return (latest_phase_matched if latest_phase_matched is not None else latest_any), False


def acceptance_hash_is_stale(
    project_root: str, canonical_id: str, *,
    lib_dir: Optional[Path] = None, audit_log_path: Optional[str] = None,
) -> bool:
    """True iff ``canonical_id`` is currently ``accepted`` AND its freshly recomputed
    ``implementation_hash`` (``proof_hash.compute_implementation_hash``, reused verbatim -- never
    reinvented) no longer matches the ``implementation_hash`` recorded in its own acceptance audit
    record. False for a capability that is not accepted at all (nothing to be stale about) or
    whose hashes still match (a clean, undisturbed acceptance).

    Fail-safe (never silently keeps ``accepted:true`` unverified as not-stale): reports True
    (stale) when the accepted hash cannot be read at all -- no matching acceptance record, an
    unreadable/malformed audit log, or a record missing/mistyping its own ``implementation_hash``
    / ``op_kind`` -- OR when the current hash cannot be recomputed
    (``proof_hash.ProofHashError``, e.g. an unregistered op_kind or a missing dependency file).

    Resolves ``canonical_id`` through A1's canonical-id resolver
    (``capability_identity.build_capability_index``); raises
    ``external_write.capability_identity.IdentityResolutionError`` if it does not resolve, and
    ``ReconcileStateError`` (mirroring ``reconcile_state``'s own fail-closed convention) if the
    descriptor set or migration queue exists but could not be read/parsed -- the SAME fail-closed
    discipline ``reconcile_state`` already applies, reused rather than duplicated with different
    wording.

    CEILING: a single point-in-time check, meant to be called at reconcile/completion-check time
    (see module docstring) -- never a per-write guarantee.
    """
    root = Path(project_root).resolve()
    index = build_capability_index(str(root))
    if index.state_read_error:
        raise ReconcileStateError(
            "Could not safely check whether this capability's approval is still current "
            "because the capability descriptor list (security/capability_descriptors.json) or "
            "the pending-migrations queue (agents/handoffs/pending_migrations.json) exists but "
            "could not be read or is corrupted. This is NOT confirmation that nothing is wrong "
            "-- repair or restore that file, then try again."
        )

    identity: CapabilityIdentity = index.resolve(canonical_id, "module_stem")
    descriptor_set = _load_descriptor_set(root)
    entry = _find_descriptor_entry(descriptor_set, identity.aliases)
    if not entry or entry.get("accepted") is not True:
        return False

    phase_id = entry.get(PHASE_ID_KEY)
    if not isinstance(phase_id, str):
        phase_id = None

    record, read_error = _read_latest_acceptance_record(
        root, identity.aliases, phase_id, audit_log_path)
    if read_error or record is None:
        return True

    accepted_hash = record.get("implementation_hash")
    op_kind = record.get("op_kind")
    if not (isinstance(accepted_hash, str) and accepted_hash
            and isinstance(op_kind, str) and op_kind):
        return True

    try:
        current_hash = compute_implementation_hash(op_kind, lib_dir=lib_dir)
    except ProofHashError:
        return True

    return current_hash != accepted_hash


def _revoke_accepted_entries(
    root: Path, descriptor_set: List[Dict[str, Any]], aliases: FrozenSet[str],
) -> bool:
    """Force ``accepted`` back to ``False`` for every descriptor entry whose ``id`` is one of
    ``aliases`` and currently ``True``. Mutates ``descriptor_set`` in place and, if anything
    changed, atomically writes it back -- SAME formatting convention (``indent=2,
    ensure_ascii=False``, no key sorting) as ``upgrade_reconcile._reset_accepted_for_scanner_red_
    capability``'s own descriptor-set writer, so the two revocation paths (scanner-red,
    hash-stale) leave byte-identical shapes behind. Returns whether anything changed."""
    changed = False
    for entry in descriptor_set:
        if (isinstance(entry, dict) and entry.get("id") in aliases
                and entry.get("accepted") is True):
            entry["accepted"] = False
            changed = True
    if changed:
        _atomic_write(
            root / DESCRIPTOR_SET_REL,
            json.dumps(descriptor_set, indent=2, ensure_ascii=False) + "\n",
        )
    return changed


def _queue_staleness_retrial_migration(root: Path, canonical_id: str) -> None:
    """Land (or refresh) a durable, disk-first re-trial request in the pending-migration queue --
    the SAME queue ``wizard/skills/add-capability.md`` checks at its Step A, and the SAME
    idempotent replace-by-``mechanism_id`` convention ``upgrade_reconcile._append_migration_
    request`` uses (re-running a check for the same capability replaces its existing entry rather
    than duplicating it)."""
    path = root / MIGRATION_QUEUE_REL
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except (json.JSONDecodeError, OSError):
        existing = []
    existing = [
        e for e in existing
        if not (isinstance(e, dict) and e.get("mechanism_id") == canonical_id)
    ]
    existing.append({
        "mechanism_id": canonical_id,
        "requested_at": _utcnow_iso(),
        "reason": (
            "this capability's implementation changed since it was approved for live use; "
            "acceptance was automatically switched off pending a fresh trial"
        ),
        "suggested_next_step": (
            "Re-run this capability's copy-run trial and approve it again through the normal "
            "accept flow."
        ),
        "status": "pending",
    })
    _atomic_write(
        path, json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


@dataclass(frozen=True)
class RevocationResult:
    """Outcome of one ``revoke_stale_acceptance`` call.

    canonical_id: the resolved canonical capability id this call checked.
    stale:        the ``acceptance_hash_is_stale`` verdict (True iff a revocation was warranted).
    revoked:      True iff this call actually forced ``accepted`` back to False this call (always
                  equal to ``stale`` today -- kept as its own field so a future caller never has to
                  assume the two can never diverge).
    note:         the plain-language operator note (``STALE_ACCEPTANCE_NOTE``) when ``revoked`` is
                  True, else None.
    reconcile:    the ``ReconcileResult`` from the ``reconcile_state`` call this function always
                  makes afterward (reused, not duplicated) -- so the pause marker and
                  pending-migration queue are coherent with the (possibly just-revoked) SSOT
                  regardless of whether a revocation happened this call.
    """
    canonical_id: str
    stale: bool
    revoked: bool
    note: Optional[str]
    reconcile: ReconcileResult


def revoke_stale_acceptance(
    project_root: str, canonical_id: str, *,
    lib_dir: Optional[Path] = None, audit_log_path: Optional[str] = None,
) -> RevocationResult:
    """The operate-time entry point for the F-62 conformant-rebuild trust gap (Task B2b): checks
    ``acceptance_hash_is_stale`` for ``canonical_id`` and, if stale, forces its descriptor back to
    ``accepted: false`` (atomic), queues a re-trial migration entry, and always finishes by calling
    ``reconcile_state`` (reused) so the pause marker / pending-migration queue stay coherent with
    the SSOT -- whether or not a revocation happened this call.

    This is the operate-time mirror of ``upgrade_reconcile.py``'s own B2 wiring
    (``_reset_accepted_for_scanner_red_capability`` + ``_reconcile_lifecycle_state_best_effort``):
    intended to be called wherever a capability's acceptance is checked/completion-verified
    OUTSIDE an upgrade (a rebuild the operator made directly, with no upgrade in between) -- "the
    next reconcile/completion check" per this task's brief. Idempotent and safe to call on every
    such check: a capability that is not accepted, or whose hashes still match, is left completely
    undisturbed (``stale=False``, ``revoked=False``) and this call still returns a coherent
    ``reconcile`` view.

    CEILING (disclosed): a point-in-time check -- NOT a per-write runtime guarantee. See module
    docstring.

    Raises the same errors ``acceptance_hash_is_stale`` / ``reconcile_state`` raise
    (``IdentityResolutionError``, ``ReconcileStateError``) -- never guessed over an unverifiable
    state.
    """
    root = Path(project_root).resolve()
    stale = acceptance_hash_is_stale(
        str(root), canonical_id, lib_dir=lib_dir, audit_log_path=audit_log_path)

    note: Optional[str] = None
    if stale:
        index = build_capability_index(str(root))
        identity: CapabilityIdentity = index.resolve(canonical_id, "module_stem")
        descriptor_set = _load_descriptor_set(root)
        _revoke_accepted_entries(root, descriptor_set, identity.aliases)
        _queue_staleness_retrial_migration(root, identity.canonical_id)
        note = STALE_ACCEPTANCE_NOTE

    reconcile = reconcile_state(str(root), canonical_id)
    return RevocationResult(
        canonical_id=reconcile.canonical_id, stale=stale, revoked=stale,
        note=note, reconcile=reconcile,
    )
