"""Operator acknowledgement of an unrepairable bespoke writer (Cut 1.6 / bundle
v0.20.0, Task 3) -- the ONE sanctioned exit from ``WriterState.NEEDS_PERSON``.

Why this exists
---------------
the coarse safety gate's coarse fail-closed gate blocks live-enable while an unresolved
external-write bypass is open. The v0.19.0 real-operator validation found the
unpriced cost (F-VAL19-1): a writer can be genuinely unrepairable. The estate's
``agents/upkeep/runner.py`` is zoned CAPABILITY (so all network imports are
banned) but ALSO delivers the operator's working daily phone alert and email
digest via ``urllib``. It can be neither made scan-clean nor deleted without
re-architecting a service the operator relies on daily -- far beyond a
non-technical operator. Its entry can therefore never be reaped, and under
v0.19.0 that permanently blocked acceptance for EVERY capability in the project.

``_ext_write_state`` classifies such a writer ``NEEDS_PERSON``. That state
REMAINS BLOCKING deliberately -- letting it through automatically would re-open
the F-VAL18-1 false green (acceptance going green around an unmigrated LIVE
writer with no human in the loop). What this module adds is the missing exit:
not a classifier's silent judgement, but **a recorded human decision**.

The four properties that keep this from being a hole
-----------------------------------------------------
1. **Explicit.** It never happens automatically. The operator confirms in their
   own words, and that text is stored verbatim.
2. **Hash-bound.** The acknowledgement records the writer's content hash at the
   moment it was given, and is VOID the instant the file's bytes change. You
   cannot acknowledge a file today and quietly change what it does tomorrow --
   the same hash-binding discipline the migration quarantine already uses.
3. **Visible.** An acknowledged entry is still OPEN and still reported by
   ``capability_health --overall``; ``normal_status_allowed`` stays False. It
   stops blocking; it does not stop existing. Not blocking never means
   invisible.
4. **Audited.** The record is a committable JSON artifact under ``security/``,
   carrying who confirmed what, when, and against which violations.

Never a silent dismissal. The word "acknowledge" is deliberate: the risk is
accepted and recorded, not resolved.

Enforcement ceiling (disclosure): build-time + operator-as-approver, NOT a
runtime/OS sandbox -- the same ceiling every module in this package discloses.
An acknowledgement records a decision; it does not make the writer safe.

Stdlib only -- no third-party dependencies.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

ACKNOWLEDGEMENTS_REL = "security/bespoke_writer_acknowledgements.json"
ACKNOWLEDGEMENT_SCHEMA = "bespoke-writer-acknowledgement-v1"


class WriterAcknowledgementError(Exception):
    """A refusal to record an acknowledgement. Always carries a plain-language,
    operator-facing reason -- never a raw traceback (the repo's "no raw errors
    to the operator" convention)."""


def _content_sha256(path: Path) -> Optional[str]:
    """sha256 of the file's raw bytes, byte-identical to how
    ``upgrade_reconcile._content_sha256`` records ``paused_content_sha256`` and
    how ``_ext_write_state`` compares it, so the values are comparable.
    ``None`` when the file is absent or unreadable (never guessed)."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _read_records(project_root: str) -> List[Dict[str, Any]]:
    """Every acknowledgement record on disk. Absent store -> ``[]`` (a NORMAL
    input). Existing-but-unreadable/malformed -> raises, so a corrupt store can
    never silently present as "acknowledged" (which would be the fail-OPEN
    direction) nor crash a read-only health view that catches this."""
    path = Path(project_root) / ACKNOWLEDGEMENTS_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise WriterAcknowledgementError(
            "the record of accepted-risk files could not be read") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise WriterAcknowledgementError(
            "the record of accepted-risk files is not valid JSON") from exc
    if not isinstance(data, list):
        raise WriterAcknowledgementError(
            "the record of accepted-risk files is not a JSON array")
    return [r for r in data if isinstance(r, dict)]


def _atomic_write(path: Path, text: str) -> None:
    """Temp file + fsync + os.replace -- mirrors ``_ext_write_state._atomic_write``
    so a crash mid-write never leaves a truncated acknowledgement store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".writer_ack.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        raise


def active_acknowledgements(project_root: str) -> Dict[str, Dict[str, Any]]:
    """``writer_relpath -> record`` for every acknowledgement that is STILL
    VALID: one whose recorded ``content_sha256`` matches the writer file's
    current bytes.

    A record whose file has changed (or gone unreadable) is deliberately NOT
    returned -- the acknowledgement is VOID and the entry returns to
    ``NEEDS_PERSON``, blocking again until a person looks at it afresh. This is
    what stops an acknowledgement from laundering a future edit. Stale records
    are left on disk as audit history rather than deleted."""
    active: Dict[str, Dict[str, Any]] = {}
    root = Path(project_root)
    for record in _read_records(project_root):
        relpath = record.get("writer_relpath")
        recorded = record.get("content_sha256")
        if not isinstance(relpath, str) or not relpath:
            continue
        if not isinstance(recorded, str) or not recorded:
            continue
        current = _content_sha256(root / relpath)
        if current is not None and current == recorded:
            active[relpath] = record
    return active


def acknowledge_writer(project_root: str,
                       writer_relpath: str,
                       *,
                       operator_confirmation: str,
                       acknowledged_at: Optional[str] = None) -> Dict[str, Any]:
    """Record the operator's accepted-risk decision for ONE unrepairable writer.

    Fails closed, with a plain-language reason, when:
      * the confirmation is blank/whitespace-only (no silent acknowledgement);
      * the confirmation contains a newline or carriage return (paste-safety --
        the same fail-closed rule the acceptance CLI applies, since a
        line-split paste can otherwise truncate what the operator "said");
      * the writer file is absent or unreadable (nothing to bind a hash to);
      * there is no OPEN bespoke-writer entry for this relpath (no orphan
        records, and no pre-acknowledging a file that is not flagged).

    Returns the stored record. Idempotent per relpath: re-acknowledging replaces
    that writer's prior record rather than accumulating duplicates."""
    if not isinstance(operator_confirmation, str) or not operator_confirmation.strip():
        raise WriterAcknowledgementError(
            "nothing was recorded -- please say in your own words that you accept "
            "the risk of leaving this file as it is")
    if "\n" in operator_confirmation or "\r" in operator_confirmation:
        raise WriterAcknowledgementError(
            "nothing was recorded -- the confirmation arrived split across lines, so it "
            "may be incomplete; please send it as a single line")

    root = Path(project_root)
    current = _content_sha256(root / writer_relpath)
    if current is None:
        raise WriterAcknowledgementError(
            f"nothing was recorded -- `{writer_relpath}` could not be read, so there is "
            "nothing to record a decision against")

    # Only a genuinely OPEN bespoke-writer entry may be acknowledged. Imported
    # lazily so this module stays a leaf (``_ext_write_state`` consults THIS
    # module for active acknowledgements; a module-scope import either way would
    # be a cycle).
    from external_write._ext_write_state import open_bespoke_writer_migrations
    open_relpaths = {str(e.get("writer_relpath"))
                     for e in open_bespoke_writer_migrations(project_root)}
    if writer_relpath not in open_relpaths:
        raise WriterAcknowledgementError(
            f"nothing was recorded -- `{writer_relpath}` is not currently flagged as "
            "needing attention, so there is nothing to accept")

    record = {
        "schema": ACKNOWLEDGEMENT_SCHEMA,
        "writer_relpath": writer_relpath,
        "content_sha256": current,
        "operator_confirmation": operator_confirmation,
        "acknowledged_at": acknowledged_at or _now_iso_z(),
    }

    kept = [r for r in _read_records(project_root)
            if r.get("writer_relpath") != writer_relpath]
    kept.append(record)
    _atomic_write(root / ACKNOWLEDGEMENTS_REL,
                  json.dumps(kept, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def _now_iso_z() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
