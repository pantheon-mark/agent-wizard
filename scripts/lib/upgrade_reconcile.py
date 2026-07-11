"""Upgrade impact-review + reconcile engine (task 9 of the
external-write-gate-generalization slice).

Why this exists
----------------
The external-write build-time enforcement mechanism ships a fail-closed
external-write gate: any script that mutates an external surface OUTSIDE the
emitted named-operation adapters fails the
build (Task 5's ``external_write.scan``). That gate is correct going FORWARD, but a
system built before the gate existed can carry operator-authored capability code
that already does this — confirmed live in the estate dogfood:
``agents/cron/estate_upkeep.py`` writes to a Google Sheet directly. Shipping the
amended gate to an EXISTING emitted project with no reconcile step would hand every
such project a build that newly fails, with no operator-doable fix (a non-technical
operator cannot "route the write through run_operation" themselves).

So an upgrade must not just deliver new files — it must **reconcile existing
functionality against the changed contract**. This module is that reconcile step,
run by the emitted upgrade-apply flow (``wizard_upgrade.py``'s ``cmd_apply`` /
``run_self_upgrade``'s ``apply_fn``) immediately after a successful
``upgrade_apply.apply_upgrade`` call, before control returns to the operator:

  1. DETECT   — run the Task-5 scanner across the OPERATOR's OWN code (never the
               emitted ``agents/lib/external_write`` gate machinery itself — that
               is trusted infrastructure, not operator-authored capability code).
  2. NOTICE   — write a plain-language impact notice: what changed, which
               capability is affected, what happens next. No jargon.
  3. SAFE-PAUSE — at the ENTRYPOINT level: disable the affected mechanism's
               mutating entrypoint/schedule while leaving read-only behavior
               (summaries/scans/reports) running. Credentials are preserved; only
               the write entrypoint is blocked. This module NEVER edits the
               flagged operator Python file itself (no surgical AST rewrite) — it
               only gates the wrapper script that schedules/invokes it.
  4. GUIDE MIGRATION — hand the fix to the existing operator-originated-
               enhancement flow (``add-capability`` / ``next-phase``): an
               approval-gated migration, never an automatic silent rewrite.
               This module records a durable, disk-first migration request
               (``agents/handoffs/pending_migrations.json``) that
               ``wizard/skills/add-capability.md`` checks at its Step A.

Safe-pause mechanics (the disclosed bound)
-------------------------------------------
Safe-pause depends on a mechanism's read path and write path being separable at
the ENTRYPOINT level. The convention this reuses is the one the wizard's own cron
scaffolding already follows (see a real emitted project's
``agents/cron/run_<name>.sh`` wrapping ``agents/cron/<name>.py``): a flagged
Python file at ``<dir>/<stem>.py`` has its scheduling/invocation wrapper at
``<dir>/run_<stem>.sh``. When that wrapper exists, this module inserts an
idempotent guard block (after the shebang, so the script stays runnable) that
checks a per-mechanism marker file and, if present, prints
``paused pending migration`` and exits 0 WITHOUT invoking anything — the flagged
Python file is never touched, never re-imported, never re-run. Any OTHER
mechanism's wrapper (a genuinely separate read-only reporting entrypoint) is left
completely untouched, so it keeps running exactly as before.

Where a mechanism entangles read and write behavior in the SAME file/entrypoint
(the real ``estate_upkeep.py`` does this — a single script that both writes a
Status-tidy fix and produces the read-only digest), a clean read/write split is
not available and pausing the one shared entrypoint necessarily pauses the whole
mechanism. This is a disclosed limit: "capabilities that entangle [read and
write] require operator-approved refactor before pause is clean." Paused-and-
safe beats running-ungated, so this module still pauses in
that case rather than leaving the write path live.

Un-pausing is a side effect of migration, not of this module: deleting the marker
file (done once the operator approves a migrated, gate-routed replacement) lets
the wrapper run normally again — the guard block itself never needs to be
reverted or edited.

Reuse discipline (DRY)
-----------------------
This module never reimplements bypass detection. It imports Task 5's
``external_write.scan`` from its single canonical home
(``<toolkit>/agents/lib/external_write/``), the same way
``test_external_write_scan.py`` does, resolved via ``bundle_templates.wizard_subroot``
so it works whether ``build_repo_root`` is an AWB checkout (``<repo>/wizard/...``)
or an operator's installed toolkit clone (``<toolkit>/...`` — the public-clone
layout the ``git subtree --prefix=wizard`` split produces, which is what actually
runs an operator's ``wizard upgrade --apply``).

Stdlib only — no third-party dependencies (operator/runtime path).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from bundle_templates import wizard_subroot  # type: ignore  # noqa: E402


# ===== Reused T5 scanner (single-home import; canonical location) ===========

def _external_write_agents_lib_dir(build_repo_root: Path) -> Path:
    """The toolkit's ``agents/lib`` directory — the single canonical home of the
    Task-5 AST bypass scanner (``external_write.scan``). Layout-agnostic via
    ``wizard_subroot`` (AWB build-repo checkout vs installed public-toolkit-clone —
    the two shapes an operator's ``wizard upgrade`` can actually run from)."""
    return wizard_subroot(Path(build_repo_root)) / "agents" / "lib"


def _scan_module(build_repo_root: Path):
    """Import the canonical scan module. DRY reuse of the Task-5 scanner — this
    module never reimplements bypass detection."""
    lib_dir = str(_external_write_agents_lib_dir(build_repo_root))
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    from external_write import scan as _scan  # type: ignore
    return _scan


# ===== Where operator-authored mechanism code lives ==========================
# The emitted GATE MACHINERY (agents/lib/external_write/) is deliberately never a
# scan target here — it is the trusted infrastructure the gate exists to enforce,
# not operator-authored capability code, and rescanning it would just reproduce
# the build-time gate battery inside the operator's own upgrade for no benefit.
OPERATOR_CODE_DIRS: Tuple[str, ...] = ("agents/cron", "agents/scripts")

PAUSED_MECHANISMS_DIR_REL = ".wizard/paused-mechanisms"
MIGRATION_QUEUE_REL = "agents/handoffs/pending_migrations.json"
UPGRADE_REVIEW_DIR_REL = ".wizard/upgrade-review"
IMPACT_NOTICE_BASENAME = "impact-notice.md"

_GUARD_BEGIN = "# --- BEGIN upgrade-reconcile safe-pause (managed; do not edit by hand) ---"
_GUARD_END = "# --- END upgrade-reconcile safe-pause ---"


@dataclass
class MechanismReport:
    """One operator-authored mechanism the reconcile found affected by the
    changed contract.

    mechanism_id:       derived from the flagged file's stem (e.g. "estate_upkeep").
                        NOTE (disclosed bound): keyed on stem only, so two flagged
                        files with the same stem in DIFFERENT operator-code
                        directories would collide — acceptable at v0 (the real
                        subject and the acceptance fixture are each a single file).
    writer_relpath:     the flagged file, project-relative (never edited).
    entrypoint_relpath: the wrapper script safe-paused, or None if no conventional
                        wrapper was found (nothing was paused automatically).
    paused:             True iff an entrypoint was found and safe-paused.
    pause_note:         operator/agent-facing note on what happened (or why not).
    """
    mechanism_id: str
    writer_relpath: str
    violation_summaries: List[str]
    entrypoint_relpath: Optional[str]
    paused: bool
    pause_note: str = ""


@dataclass
class ReconcileResult:
    """Outcome of one ``reconcile_upgrade`` call."""
    operator_project_path: str
    from_version: str
    to_version: str
    mechanisms: List[MechanismReport] = field(default_factory=list)
    notice_path: Optional[str] = None
    migration_queue_path: Optional[str] = None

    @property
    def any_affected(self) -> bool:
        return bool(self.mechanisms)

    @property
    def any_paused(self) -> bool:
        return any(m.paused for m in self.mechanisms)


# ===== Small stdlib helpers ====================================================

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + os.replace), preserving
    the destination's existing file mode (so an executable wrapper script stays
    executable — ``tempfile.mkstemp`` defaults to 0600, which would otherwise
    silently strip the exec bit on replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    preserved_mode = path.stat().st_mode if path.exists() else None
    fd, tmp = tempfile.mkstemp(prefix=".reconcile.", suffix=".tmp", dir=str(path.parent))
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
    if preserved_mode is not None:
        try:
            os.chmod(str(path), preserved_mode)
        except OSError:
            pass


# ===== 1. DETECT ================================================================

def scan_operator_mechanisms(
    operator_project_dir: Path,
    build_repo_root: Path,
    *,
    operator_code_dirs: Sequence[str] = OPERATOR_CODE_DIRS,
) -> Dict[str, List[Any]]:
    """Run the Task-5 scanner across the OPERATOR's own code (never the emitted
    ``agents/lib/external_write`` gate machinery) and group the violations found
    by the operator-project-relative path of the file they were found in.

    Returns ``{relpath: [Violation, ...]}`` — empty when nothing is affected.
    """
    operator_project_dir = Path(operator_project_dir).resolve()
    scan = _scan_module(Path(build_repo_root))
    by_relpath: Dict[str, List[Any]] = {}
    for d in operator_code_dirs:
        target = operator_project_dir / d
        if not target.is_dir():
            continue
        for v in scan.scan_paths([target]):
            try:
                rel = Path(v.path).resolve().relative_to(operator_project_dir).as_posix()
            except ValueError:  # pragma: no cover - defensive; scan_paths only sees `target`
                rel = v.path
            by_relpath.setdefault(rel, []).append(v)
    return by_relpath


# ===== 2. SAFE-PAUSE (entrypoint level) =========================================

def _wrapper_relpath_for(writer_relpath: str) -> str:
    """The conventional entrypoint wrapper for a scheduled Python mechanism file:
    ``<dir>/<stem>.py`` -> ``<dir>/run_<stem>.sh`` — the SAME naming convention the
    wizard's own cron scaffolding already uses (a real emitted project's
    ``agents/cron/run_estate_upkeep.sh`` wrapping ``agents/cron/estate_upkeep.py``)."""
    p = Path(writer_relpath)
    return str(p.parent / f"run_{p.stem}.sh")


def _find_entrypoint(operator_project_dir: Path, writer_relpath: str) -> Optional[str]:
    candidate = _wrapper_relpath_for(writer_relpath)
    if (Path(operator_project_dir) / candidate).is_file():
        return candidate
    return None


def _pause_marker_path(operator_project_dir: Path, mechanism_id: str) -> Path:
    return Path(operator_project_dir) / PAUSED_MECHANISMS_DIR_REL / f"{mechanism_id}.pause"


def _pause_state_path(operator_project_dir: Path, mechanism_id: str) -> Path:
    return Path(operator_project_dir) / PAUSED_MECHANISMS_DIR_REL / f"{mechanism_id}.json"


def _guard_block(mechanism_id: str, writer_relpath: str, marker_from_wrapper: str,
                 from_version: str, to_version: str) -> str:
    return (
        f"{_GUARD_BEGIN}\n"
        f"# This entrypoint was safe-paused by the upgrade to {to_version} (from "
        f"{from_version}) because {writer_relpath} was found to change something "
        "outside this project directly, bypassing the external-write safety check.\n"
        "# It stays paused -- and its saved access (credentials) stays untouched -- until\n"
        "# the fix is reviewed and approved through the add-capability flow. A genuinely\n"
        "# separate read-only entrypoint is not affected by this guard.\n"
        '_RECONCILE_HERE="$(cd "$(dirname "$0")" && pwd)"\n'
        f'if [ -e "$_RECONCILE_HERE/{marker_from_wrapper}" ]; then\n'
        '  echo "paused pending migration"\n'
        "  exit 0\n"
        "fi\n"
        f"{_GUARD_END}\n"
        "\n"
    )


def _relative_prefix(wrapper_relpath: str) -> str:
    """``..`` segments from the wrapper's own directory back up to the project
    root — computed statically at pause-time (we know the wrapper's relpath then),
    so the inserted guard never needs runtime path arithmetic beyond a plain
    existence check."""
    depth = len(Path(wrapper_relpath).parent.parts)
    return "/".join([".."] * depth) if depth else "."


def _safe_pause_entrypoint(
    operator_project_dir: Path,
    mechanism_id: str,
    writer_relpath: str,
    entrypoint_relpath: str,
    violations: List[Any],
    from_version: str,
    to_version: str,
) -> None:
    """Idempotently gate ``entrypoint_relpath`` so invoking it prints
    ``paused pending migration`` and exits, WITHOUT ever touching
    ``writer_relpath`` (the flagged operator file itself)."""
    operator_project_dir = Path(operator_project_dir)
    wrapper_path = operator_project_dir / entrypoint_relpath
    original = wrapper_path.read_text(encoding="utf-8")

    if _GUARD_BEGIN not in original:
        prefix = _relative_prefix(entrypoint_relpath)
        marker_from_wrapper = f"{prefix}/{PAUSED_MECHANISMS_DIR_REL}/{mechanism_id}.pause"
        guard = _guard_block(mechanism_id, writer_relpath, marker_from_wrapper,
                             from_version, to_version)
        lines = original.splitlines(keepends=True)
        if lines and lines[0].startswith("#!"):
            new_content = lines[0] + guard + "".join(lines[1:])
        else:
            new_content = guard + original
        _atomic_write(wrapper_path, new_content)

    marker_path = _pause_marker_path(operator_project_dir, mechanism_id)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    if not marker_path.exists():
        marker_path.write_text("", encoding="utf-8")

    state = {
        "mechanism_id": mechanism_id,
        "writer_relpath": writer_relpath,
        "entrypoint_relpath": entrypoint_relpath,
        "paused_at": _utcnow_iso(),
        "from_version": from_version,
        "to_version": to_version,
        "reason": "external-write gate violation detected on upgrade",
        "violations": [
            {"path": writer_relpath, "line": getattr(v, "lineno", None),
             "kind": getattr(v, "kind", "")}
            for v in violations
        ],
        "credentials_preserved": True,
        "migration_status": "pending",
    }
    _pause_state_path(operator_project_dir, mechanism_id).parent.mkdir(
        parents=True, exist_ok=True)
    _atomic_write(
        _pause_state_path(operator_project_dir, mechanism_id),
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


# ===== 3. GUIDE MIGRATION ========================================================

def _append_migration_request(
    operator_project_dir: Path,
    mechanism_id: str,
    writer_relpath: str,
    entrypoint_relpath: Optional[str],
    violations: List[Any],
    from_version: str,
    to_version: str,
) -> Path:
    """Land (or refresh) a durable, disk-first migration request in the pending-
    migrations queue that ``wizard/skills/add-capability.md`` checks at its
    Step A — this is the hand-off to the operator-originated-enhancement flow:
    approval-gated migration, never an automatic silent rewrite.

    Idempotent: re-running an upgrade (or a later reconcile pass) for the same
    mechanism_id REPLACES its existing entry rather than duplicating it."""
    path = Path(operator_project_dir) / MIGRATION_QUEUE_REL
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except (json.JSONDecodeError, OSError):
        existing = []
    existing = [
        e for e in existing
        if not (isinstance(e, dict) and e.get("mechanism_id") == mechanism_id)
    ]
    existing.append({
        "mechanism_id": mechanism_id,
        "writer_relpath": writer_relpath,
        "entrypoint_relpath": entrypoint_relpath,
        "requested_at": _utcnow_iso(),
        "from_version": from_version,
        "to_version": to_version,
        "reason": "flagged non-conformant with the external-write gate on upgrade",
        "violations": [
            {"path": writer_relpath, "line": getattr(v, "lineno", None),
             "kind": getattr(v, "kind", "")}
            for v in violations
        ],
        "suggested_next_step": (
            "Rebuild this mechanism's write path through add-capability so it routes "
            "through a registered external-write adapter (run_operation), then approve "
            "it live again through the normal build-and-accept flow."
        ),
        "status": "pending",
    })
    _atomic_write(path, json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path


# ===== 4. NOTICE (plain language) ================================================

def render_impact_notice(
    mechanisms: List[MechanismReport], from_version: str, to_version: str,
) -> str:
    """A plain-language, non-technical impact notice: what changed, which
    capability is affected, what happens next. No jargon."""
    lines = [
        "# Upgrade safety notice",
        "",
        f"Your system was upgraded from {from_version} to {to_version}. That upgrade adds "
        "a stronger check on anything that changes information outside this project "
        "(a spreadsheet, an inbox, a file store, and so on).",
        "",
        "While applying that check, it found something built before this rule existed "
        "that does not yet follow it.",
        "",
        "## What's affected",
        "",
    ]
    for m in mechanisms:
        lines.append(
            f"- **{m.mechanism_id}** (`{m.writer_relpath}`): this changes information "
            "outside the project directly, without going through the safety check."
        )
        if m.paused:
            lines.append(
                f"  - It has been paused (`{m.entrypoint_relpath}` will not make that "
                "change until this is fixed). Anything that only reads and reports to "
                "you was not touched — that keeps running exactly as before."
            )
        else:
            lines.append(
                "  - No automatic schedule was found for it, so nothing could be paused "
                "automatically — please review it by hand before relying on it."
            )
    lines += [
        "",
        "## What happens next",
        "",
        "- Nothing was deleted, and no saved access (credentials) was removed — only the "
        "part that changes things was switched off, until it is rebuilt the safe way.",
        "- To fix this, just tell your assistant (for example: \"let's fix the upkeep "
        "writer\") and it will walk through the same careful, reviewed process used for "
        "any new capability, so the paused part gets rebuilt onto the safety check and "
        "you approve it again before it runs live.",
        f"- This has also been written down in this project's pending-work list "
        f"(`{MIGRATION_QUEUE_REL}`) so it isn't forgotten.",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_impact_notice(operator_project_dir: Path, upgrade_id: str, text: str) -> Path:
    """Write the notice to the same upgrade-review area the apply engine already
    uses for per-upgrade review artifacts (or a dedicated ``reconcile`` folder when
    no ``upgrade_id`` is available)."""
    base = Path(operator_project_dir) / UPGRADE_REVIEW_DIR_REL / (upgrade_id or "reconcile")
    path = base / IMPACT_NOTICE_BASENAME
    _atomic_write(path, text)
    return path


# ===== The orchestrator ==========================================================

def reconcile_upgrade(
    operator_project_dir: Path,
    build_repo_root: Path,
    *,
    from_version: str,
    to_version: str,
    upgrade_id: str = "",
    operator_code_dirs: Sequence[str] = OPERATOR_CODE_DIRS,
) -> ReconcileResult:
    """The upgrade impact-review + reconcile step.

    Run by the emitted upgrade-apply flow AFTER ``upgrade_apply.apply_upgrade`` has
    delivered the new layer, and BEFORE control returns to the operator. See the
    module docstring for the full DETECT / NOTICE / SAFE-PAUSE / GUIDE-MIGRATE
    contract. Never touches the flagged operator Python file; only its
    conventional entrypoint wrapper (when one exists) is gated."""
    operator_project_dir = Path(operator_project_dir).resolve()
    by_relpath = scan_operator_mechanisms(
        operator_project_dir, build_repo_root, operator_code_dirs=operator_code_dirs)

    mechanisms: List[MechanismReport] = []
    for relpath in sorted(by_relpath):
        violations = by_relpath[relpath]
        mechanism_id = Path(relpath).stem
        entrypoint = _find_entrypoint(operator_project_dir, relpath)
        if entrypoint:
            _safe_pause_entrypoint(
                operator_project_dir, mechanism_id, relpath, entrypoint,
                violations, from_version, to_version,
            )
            paused = True
            note = f"entrypoint {entrypoint} safe-paused"
        else:
            paused = False
            note = (
                "no conventional schedule/entrypoint file was found for this mechanism "
                "-- it could not be paused automatically; review it by hand"
            )
        _append_migration_request(
            operator_project_dir, mechanism_id, relpath, entrypoint, violations,
            from_version, to_version,
        )
        mechanisms.append(MechanismReport(
            mechanism_id=mechanism_id,
            writer_relpath=relpath,
            violation_summaries=[f"{v.kind}:{v.lineno}" for v in violations],
            entrypoint_relpath=entrypoint,
            paused=paused,
            pause_note=note,
        ))

    notice_path: Optional[Path] = None
    if mechanisms:
        text = render_impact_notice(mechanisms, from_version, to_version)
        notice_path = write_impact_notice(operator_project_dir, upgrade_id, text)

    return ReconcileResult(
        operator_project_path=str(operator_project_dir),
        from_version=from_version,
        to_version=to_version,
        mechanisms=mechanisms,
        notice_path=str(notice_path) if notice_path else None,
        migration_queue_path=(
            str(operator_project_dir / MIGRATION_QUEUE_REL) if mechanisms else None
        ),
    )


def render_reconcile_result(result: ReconcileResult) -> str:
    """Short CLI-appended summary (plain language) — the full detail lives in the
    notice file this points at."""
    if not result.mechanisms:
        return ""
    lines = ["", "Upgrade safety check found something to review:"]
    for m in result.mechanisms:
        status = "paused" if m.paused else "needs manual review (no schedule found)"
        lines.append(f"  - {m.mechanism_id}: {status}")
    if result.notice_path:
        lines.append(f"  See {result.notice_path} for what this means and what happens next.")
    return "\n".join(lines) + "\n"
