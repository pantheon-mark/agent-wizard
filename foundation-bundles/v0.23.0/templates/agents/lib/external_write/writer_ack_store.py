"""The store of operator acknowledgements for unrepairable bespoke writers --
record persistence and the hash-validity rule, and a LEAF: it imports no sibling
in this package.

Why this exists
---------------
The coarse safety gate blocks live-enable while an unresolved external-write bypass
is open. A real-operator validation found the unpriced cost: a writer can be
genuinely unrepairable. The estate's ``agents/upkeep/runner.py`` is zoned
CAPABILITY (so all network imports are banned) but ALSO delivers the operator's
working daily phone alert and email digest via ``urllib``. It can be neither made
scan-clean nor deleted without re-architecting a service the operator relies on
daily -- far beyond a non-technical operator. Its entry can therefore never be
reaped, and at one point that permanently blocked acceptance for EVERY capability
in the project.

The structural classifier calls such a writer ``needs_person``. That state REMAINS
BLOCKING deliberately -- letting it through automatically would re-open the false
green where acceptance goes green around an unmigrated LIVE writer with no human in
the loop. What this store holds is the missing exit: not a classifier's silent
judgement, but **a recorded human decision**.

The four properties that keep this from being a hole
-----------------------------------------------------
1. **Explicit.** It never happens automatically. The operator confirms in their
   own words, and that text is stored verbatim.
2. **Hash-bound.** The record carries the writer's content hash at the moment it
   was given, and is VOID the instant the file's bytes change. You cannot accept a
   file today and quietly change what it does tomorrow -- the same hash-binding
   discipline the migration quarantine already uses.
3. **Visible.** An accepted entry is still OPEN and still reported by
   ``capability_health --overall``; ``normal_status_allowed`` stays False. It stops
   blocking; it does not stop existing. Not blocking never means invisible.
4. **Audited.** The record is a committable JSON artifact under ``security/``,
   carrying who confirmed what, when, and against which violations.

Never a silent dismissal. The word "acknowledge" is deliberate: the risk is
accepted and recorded, not resolved.

What this module deliberately does NOT do
-----------------------------------------
It does not decide WHETHER a given writer may be acknowledged. Eligibility is a
question about the writer's state, and asking it from here is what used to make
this module and the state module import each other -- lazily, in both directions,
so neither import ever failed and the cycle went unnoticed for three cuts. That
question now belongs to ``writer_commands``, which asks the structural-state core
directly and writes through this store. Keeping the two apart is what makes the
eligibility rule tightenable at all.

Enforcement ceiling (disclosure): build-time + operator-as-approver, NOT a
runtime/OS sandbox -- the same ceiling every module in this package discloses. A
record captures a decision; it does not make the writer safe.

Zoning note: this module is listed in ``zones.SEALED_KERNEL_MODULE_PATHS``. It
WRITES project state (``security/bespoke_writer_acknowledgements.json``), which
makes it ordinary internal kernel wiring of the same class as ``lifecycle_state.py``.
It imports no sibling here, no vendor SDK, constructs no credential and never calls
``run_operation``, so it passes every universal check on its own merits.
Membership grants NO capability the right to import it (that allowlist is the
independent ``scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES`` set).

Stdlib only -- no third-party dependencies, and no first-party ones either.
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
    how the reap compares it, so the values are comparable. ``None`` when the file
    is absent or unreadable (never guessed)."""
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
    """Temp file + fsync + os.replace -- mirrors the queue writer's own atomic
    write so a crash mid-write never leaves a truncated record store."""
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


def _now_iso_z() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def active_acknowledgements(project_root: str) -> Dict[str, Dict[str, Any]]:
    """``writer_relpath -> record`` for every acknowledgement that is STILL
    VALID: one whose recorded ``content_sha256`` matches the writer file's
    current bytes.

    A record whose file has changed (or gone unreadable) is deliberately NOT
    returned -- the acknowledgement is VOID and the entry returns to
    ``needs_person``, blocking again until a person looks at it afresh. This is
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


def validate_confirmation(operator_confirmation: str) -> None:
    """Refuse, with a plain-language reason, anything that is not a usable
    single-line statement in the operator's own words. Raises; returns nothing.

    Ordered exactly as it has always been ordered, and called BEFORE any
    eligibility question, so what the operator reads on a bad confirmation does
    not depend on whether the file happened to be flagged."""
    if not isinstance(operator_confirmation, str) or not operator_confirmation.strip():
        raise WriterAcknowledgementError(
            "nothing was recorded -- please say in your own words that you accept "
            "the risk of leaving this file as it is")
    if "\n" in operator_confirmation or "\r" in operator_confirmation:
        raise WriterAcknowledgementError(
            "nothing was recorded -- the confirmation arrived split across lines, so it "
            "may be incomplete; please send it as a single line")


def require_writer_content_hash(project_root: str, writer_relpath: str) -> str:
    """The writer's current content hash, or a refusal. There is nothing to bind a
    decision to if the file cannot be read, and a record with no usable hash would
    be a standing waiver rather than a hash-bound one."""
    current = _content_sha256(Path(project_root) / writer_relpath)
    if current is None:
        raise WriterAcknowledgementError(
            f"nothing was recorded -- `{writer_relpath}` could not be read, so there is "
            "nothing to record a decision against")
    return current


def put_acknowledgement_record(project_root: str,
                               writer_relpath: str,
                               *,
                               content_sha256: str,
                               operator_confirmation: str,
                               acknowledged_at: Optional[str] = None) -> Dict[str, Any]:
    """Persist ONE record and return it. Idempotent per relpath: re-acknowledging
    replaces that writer's prior record rather than accumulating duplicates.

    The caller supplies ``content_sha256`` -- the value ``require_writer_content_
    hash`` already computed -- rather than this function re-reading the file. One
    read means the hash written into the record is provably the hash the caller's
    checks were made against, which a second read could not guarantee.

    Written atomically, so a crash mid-write never leaves a truncated store."""
    record = {
        "schema": ACKNOWLEDGEMENT_SCHEMA,
        "writer_relpath": writer_relpath,
        "content_sha256": content_sha256,
        "operator_confirmation": operator_confirmation,
        "acknowledged_at": acknowledged_at or _now_iso_z(),
    }
    kept = [r for r in _read_records(project_root)
            if r.get("writer_relpath") != writer_relpath]
    kept.append(record)
    _atomic_write(Path(project_root) / ACKNOWLEDGEMENTS_REL,
                  json.dumps(kept, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return record
