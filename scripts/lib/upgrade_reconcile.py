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
  4. GUIDE MIGRATION — hand the fix to the dedicated ``rebuild-paused-capability``
               flow (Task B4, F-77): an approval-gated migration, never an
               automatic silent rewrite. This module records a durable,
               disk-first migration request
               (``agents/handoffs/pending_migrations.json``) that
               ``wizard/skills/rebuild-paused-capability.md`` reads and drives
               through reconcile -> stub-repair (if needed) -> proof -> accept
               -> live-readiness. ``add-capability`` is for a genuinely NEW
               capability only and no longer absorbs this queue (it used to;
               see F-77 for why that dead-ended a naive operator).

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

import ast
import importlib
import json
import os
import re
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
from capability_code_scaffold import (  # type: ignore  # noqa: E402
    DEFAULT_CAPABILITIES_REL,
    DEFAULT_EXTERNAL_WRITE_REL,
    CapabilityCodeScaffoldError,
    insert_missing_evidence_predicate_stubs,
)


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


def _external_write_module(build_repo_root: Path, module_name: str):
    """(Task B2) Import one of the toolkit's OWN operate-time
    ``agents/lib/external_write/<module_name>.py`` modules from its single canonical
    home — the exact same layout-agnostic resolution ``_scan_module`` already uses
    for the Task-5 scanner, extended to the two other trusted, stdlib-only
    lifecycle primitives this task needs: ``capability_identity`` (the A1 canonical-
    id resolver) and ``lifecycle_state`` (B1's marker/migration reconciler). This is
    NEVER a channel for executing operator-authored capability code — only this
    package's own trusted infrastructure, the same class of import the module
    docstring's "Reuse discipline" section already sanctions for the scanner."""
    lib_dir = str(_external_write_agents_lib_dir(build_repo_root))
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    return importlib.import_module(f"external_write.{module_name}")


# ===== Where operator-authored mechanism code lives ==========================
# The emitted GATE MACHINERY (agents/lib/external_write/) is deliberately never a
# scan target here — it is the trusted infrastructure the gate exists to enforce,
# not operator-authored capability code, and rescanning it would just reproduce
# the build-time gate battery inside the operator's own upgrade for no benefit.
# Scheduled-mechanism dirs + the capability emitter's real output dir (derive,
# don't drift -- this is the fix for F-55: the set used to be hardcoded and
# went blind to agents/capabilities/ once add-capability started emitting
# there).
OPERATOR_CODE_DIRS: Tuple[str, ...] = (
    "agents/cron", "agents/scripts", DEFAULT_CAPABILITIES_REL.as_posix(),
)

_EXTERNAL_WRITE_IMPORT_RE = re.compile(r'^\s*(?:from|import)\s+.*\bexternal_write\b', re.M)
_DISCOVERY_EXCLUDE_DIR_NAMES = frozenset(
    {".venv", "venv", "__pycache__", ".git", ".wizard", "node_modules"})


def discover_external_write_importers(
    operator_project_dir: Path,
    *,
    exclude_dir_names: "frozenset[str]" = _DISCOVERY_EXCLUDE_DIR_NAMES,
) -> List[Path]:
    """B-opt2 (V15-3a): every .py file under the operator project that imports
    the ``external_write`` package, EXCEPT the sealed lib itself
    (``agents/lib/external_write``) and excluded dirs. Deriving the reconcile's
    scan target from the real import graph -- not a fixed directory list -- is
    what makes a hand-rolled bulk runner visible wherever it lives (the estate's
    ``agents/inbox/runner.py`` was outside the old fixed OPERATOR_CODE_DIRS).

    Over-inclusion is SAFE (an extra clean file yields no violation);
    under-inclusion re-opens V15-3, so the import match is deliberately broad
    (a text scan of import lines, not a full AST parse -- a comment/string false
    positive only costs one wasted clean scan), and matches ``external_write``
    anywhere on the import statement -- not just as the first name -- so a
    comma-list import (``import os, external_write`` / ``import json,
    external_write as ew``) is caught regardless of ordering. Static import
    graph only; dynamic/string imports are a disclosed residual (near-zero for
    emitted, non-technical-operator code)."""
    root = Path(operator_project_dir).resolve()
    sealed = (root / "agents" / "lib" / "external_write").resolve()
    hits: List[Path] = []
    for p in root.rglob("*.py"):
        rp = p.resolve()
        try:
            rel_parts = rp.relative_to(root).parts
        except ValueError:  # pragma: no cover - defensive
            continue
        if any(part in exclude_dir_names for part in rel_parts):
            continue
        if str(rp) == str(sealed) or str(rp).startswith(str(sealed) + os.sep):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - unreadable file
            continue
        if _EXTERNAL_WRITE_IMPORT_RE.search(text):
            hits.append(p)
    return hits


PAUSED_MECHANISMS_DIR_REL = ".wizard/paused-mechanisms"

# (F-55 B2) Project-root-relative path to the operator project's descriptor
# set -- the SAME value as write_gate.DESCRIPTOR_SET_PATH ("security/
# capability_descriptors.json"). Duplicated as a plain string rather than
# imported: this module deliberately does not import the operator-emitted
# external_write package as production code (only the AST scanner, via
# _scan_module, and only for DETECTION -- see the module docstring's "Reuse
# discipline" note). Used only by resolve_paused_op_kinds below.
CAPABILITY_DESCRIPTOR_SET_REL = "security/capability_descriptors.json"

MIGRATION_QUEUE_REL = "agents/handoffs/pending_migrations.json"
UPGRADE_REVIEW_DIR_REL = ".wizard/upgrade-review"
IMPACT_NOTICE_BASENAME = "impact-notice.md"
CRON_CONFIG_REL = "agents/cron/cron_config.md"

# Read/report-shaped keyword indicators (F-43): a heuristic, deliberately broad,
# textual signal that a file's OWN source surfaces read-only output (a digest, an
# alert, a backup, ...). Broad on purpose -- a false positive here only makes the
# notice say "paused too" about something that was actually fine (the safe
# failure direction); it never causes a false continuity promise, which requires
# POSITIVE verification of a separate entrypoint (see
# ``_classify_read_output_entanglement``).
_READ_OUTPUT_INDICATORS: Tuple[str, ...] = (
    "digest", "alert", "backup", "summary", "notify", "report", "email",
)

# Naming convention this module checks for a genuinely SEPARATE read-only
# companion file living alongside a flagged writer (e.g. "estate_upkeep.py" +
# "estate_upkeep_digest.py"). Finding a candidate is necessary but not
# sufficient -- it must also have zero scan violations of its own AND an
# unpaused, ungated wrapper before it counts as verified (see
# ``_classify_read_output_entanglement``).
_READONLY_COMPANION_SUFFIXES: Tuple[str, ...] = (
    "_read", "_readonly", "_digest", "_report", "_summary",
)

_GUARD_BEGIN = "# --- BEGIN upgrade-reconcile safe-pause (managed; do not edit by hand) ---"
_GUARD_END = "# --- END upgrade-reconcile safe-pause ---"


@dataclass
class MechanismReport:
    """One operator-authored mechanism the reconcile found affected by the
    changed contract.

    mechanism_id:       derived from the flagged file's stem (e.g. "estate_upkeep"),
                        via ``_capability_mechanism_id`` (see xvendor round-2 R2-1).
                        For a writer under the operator-capability directory
                        (``agents/capabilities/``), exactly ONE trailing
                        ``_capability`` suffix is stripped from the stem first, so
                        mechanism_id equals the SAME capability_id the emitted
                        scaffold's descriptor entry declares as its ``id`` — the
                        join ``resolve_paused_op_kinds`` needs. Every other writer's
                        mechanism_id is its plain, unmodified file stem.
                        NOTE (disclosed bound): keyed on stem only, so two flagged
                        files with the same stem in DIFFERENT operator-code
                        directories would collide — acceptable at v0 (the real
                        subject and the acceptance fixture are each a single file).
    writer_relpath:     the flagged file, project-relative (never edited).
    entrypoint_relpath: the wrapper script safe-paused, or None if no conventional
                        wrapper was found (nothing was paused automatically).
    paused:             True iff an entrypoint was found and safe-paused.
    pause_note:         operator/agent-facing note on what happened (or why not).

    Read-output/entanglement fields (F-43 fix — the honest safe-pause notice).
    A paused entrypoint may ALSO be the thing that produces read-only outputs the
    operator relies on (a digest, phone alerts, a backup) — the real estate-tracker
    dogfood incident this fixes was exactly that: one entrypoint did digest + alert
    + backup + the gated write, so pausing it paused all of them, and the emitted
    notice said the opposite. These fields are DENY-BY-DEFAULT: they default to
    "unknown", and the notice renderer (``render_impact_notice``) treats unknown
    exactly like entangled — a continuity promise is only ever emitted when
    ``carries_read_outputs is False`` AND ``separate_readonly_entrypoint`` names a
    positively-verified companion (see ``_classify_read_output_entanglement``).
    carries_read_outputs:        True  -> the paused entrypoint's own file also
                                  surfaces read/report-shaped output (entangled).
                                  False -> a separate read-only entrypoint was
                                  positively verified to survive the pause.
                                  None  -> unverified/not applicable (e.g. nothing
                                  was paused, or verification could not be done) —
                                  treated as entangled by the notice.
    separate_readonly_entrypoint: relpath of the verified-separate read-only
                                  companion entrypoint, or None.
    entangled_read_outputs:       human-readable labels (e.g. ["digest", "backup"])
                                  the entangled file's own source surfaced, used to
                                  name which awareness function is now dark. Empty
                                  when not entangled or unknown.
    orchestrator_routed:          True iff this mechanism was discovered scheduled
                                  through the Orchestrator (see
                                  ``_orchestrator_routed_entrypoint``) rather than
                                  via a dedicated ``run_<stem>.sh`` wrapper. Always
                                  paired with ``paused=False`` -- there is no
                                  per-mechanism file this module can gate in that
                                  shape (see that function's docstring).
    state:                        (F-55 B1) the honest, operator-facing state
                                  discriminator for this mechanism. One of:
                                    "entrypoint_paused"       -- a conventional
                                        ``run_<stem>.sh`` wrapper was found and
                                        safe-paused (existing cron path).
                                    "orchestrator_routed"     -- scheduled through
                                        the Orchestrator; no per-mechanism file to
                                        gate (existing path).
                                    "manual_review"           -- no wrapper, not
                                        orchestrator-routed, and the writer is NOT
                                        under the operator-capability directory --
                                        the pre-existing "no schedule found"
                                        fallback.
                                    "broken_requires_migration" -- (B1, this task)
                                        no wrapper, not orchestrator-routed, and the
                                        writer IS under the operator-capability
                                        directory. Every mechanism this module ever
                                        sees is scanner-red (the AST scanner only
                                        returns violating files), and a capability
                                        in this shape has no structural entrypoint
                                        to safe-pause -- it is import-broken and
                                        cannot run at all. Honest state, not a
                                        continuity claim: nothing was "paused"
                                        because nothing could run.
                                    "paused_live_write"       -- (F-55 B2, this
                                        task) a still-RUNNABLE capability (import
                                        clean AND scan clean) under the
                                        operator-capability directory: it is not
                                        gated at the entrypoint level (there is
                                        none to gate at this shape -- see
                                        _is_under_capability_dir), so instead its
                                        live writes are denied at RUNTIME by the
                                        emitted write_gate's deny-branch, keyed on
                                        this mechanism's `paused_op_kinds` (written
                                        into its pause-state marker; see
                                        resolve_paused_op_kinds /
                                        _write_paused_live_write_state).
                                        GENERAL PRIMITIVE, HONEST SCAFFOLDING: this
                                        module's ONLY detection channel is the AST
                                        scanner (see scan_operator_mechanisms
                                        above), which returns ONLY scanner-red
                                        files -- so every relpath that reaches this
                                        classification already has a non-empty
                                        `violations` list, and "scan clean" is
                                        therefore always False in the REAL
                                        reconcile_upgrade path today. This state is
                                        unreachable through the real scanner-driven
                                        flow as a result -- it exists so a FUTURE
                                        non-scanner detection signal (one that can
                                        supply a genuinely scan-clean mechanism_id)
                                        has a real, tested primitive to land on,
                                        without this module inventing a fake path
                                        to reach it today.
                                  Defaults to "manual_review" to preserve existing
                                  behavior for any caller that does not set it
                                  explicitly.
    paused_op_kinds:               (F-55 B2) the resolved op_kind(s) this
                                  mechanism's live writes are denied for, when
                                  state == "paused_live_write". Empty for every
                                  other state.
    """
    mechanism_id: str
    writer_relpath: str
    violation_summaries: List[str]
    entrypoint_relpath: Optional[str]
    paused: bool
    pause_note: str = ""
    carries_read_outputs: Optional[bool] = None
    separate_readonly_entrypoint: Optional[str] = None
    entangled_read_outputs: List[str] = field(default_factory=list)
    orchestrator_routed: bool = False
    state: str = "manual_review"
    paused_op_kinds: List[str] = field(default_factory=list)


@dataclass
class ReconcileResult:
    """Outcome of one ``reconcile_upgrade`` call.

    stale_acceptance_reset: (Task B2b) canonical ids of capability-dir capabilities that were
        SCANNER-CLEAN the whole time (never appeared in ``mechanisms`` above -- the AST scanner
        found nothing wrong with them) but whose acceptance was revoked anyway because their
        recomputed ``implementation_hash`` no longer matched their acceptance audit record's
        stored hash -- the "conformant rebuild" half of the F-62 trust gap B2's scanner-red reset
        does not cover. See ``_reconcile_conformant_rebuild_staleness``.

    predicate_stubs_scaffolded: (Task B2, F-75) one entry per capability whose adapter was
        auto-scaffolded with a FAILING evidence-predicate stub this pass -- ALSO scanner-status-
        independent (a fully gate-conformant capability can still be missing a newly-required
        predicate). See ``reconcile_missing_evidence_predicates``.
    """
    operator_project_path: str
    from_version: str
    to_version: str
    mechanisms: List[MechanismReport] = field(default_factory=list)
    notice_path: Optional[str] = None
    migration_queue_path: Optional[str] = None
    stale_acceptance_reset: List[str] = field(default_factory=list)
    predicate_stubs_scaffolded: List["PredicateStubRemediation"] = field(default_factory=list)

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

    # B-opt2: fixed canonical dirs ∪ import-graph-discovered importers, deduped.
    targets: List[Path] = [
        operator_project_dir / d for d in operator_code_dirs
        if (operator_project_dir / d).is_dir()
    ]
    targets += discover_external_write_importers(operator_project_dir)

    seen: set = set()   # (resolved path, lineno, kind) -- a file under a canonical
                        # dir AND discovered as an importer is scanned once.
    for v in scan.scan_paths(targets):
        key = (Path(v.path).resolve().as_posix(), v.lineno, v.kind)
        if key in seen:
            continue
        seen.add(key)
        try:
            rel = Path(v.path).resolve().relative_to(operator_project_dir).as_posix()
        except ValueError:  # pragma: no cover - defensive
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


def _is_under_capability_dir(writer_relpath: str) -> bool:
    """(F-55 B1) True iff the flagged writer lives under the operator-capability
    directory (``agents/capabilities/`` in a real emitted project). Derived from
    the emitter's own ``DEFAULT_CAPABILITIES_REL`` — never hardcoded — so this
    stays correct if that convention ever moves. A capability in this shape has
    no ``run_<stem>.sh`` wrapper convention and is not cron/orchestrator-scheduled,
    so the entrypoint-level safe-pause mechanism does not structurally apply to
    it; see ``reconcile_upgrade``'s ``broken_requires_migration`` branch."""
    prefix = DEFAULT_CAPABILITIES_REL.as_posix().rstrip("/") + "/"
    return Path(writer_relpath).as_posix().startswith(prefix)


# (xvendor round-2, R2-1) The production scaffold
# (capability_code_scaffold.py's ``capability_module_stem``) writes a
# capability's module as ``agents/capabilities/<capability_id>_capability.py``
# -- so the file's own STEM carries this suffix, but its descriptor ``id`` (in
# security/capability_descriptors.json) equals the BARE ``capability_id``,
# with NO suffix. Before this fix, every mechanism_id derived below was the
# raw ``Path(relpath).stem`` -- WITH the suffix -- so ``resolve_paused_op_kinds``
# (which requires a descriptor entry with ``id == mechanism_id``) could never
# join against a REAL scaffolded capability's descriptor: the join silently
# failed, no ``paused_op_kinds`` marker was ever written, and the
# broken_requires_migration runtime-block fix (xvendor Finding-1) was
# defeated for every real capability. (The pre-fix regression test used a
# fixture filename with NO ``_capability`` suffix at all -- a real-emitted-
# path overfit that could never exercise this join.)
CAPABILITY_MODULE_SUFFIX = "_capability"


def _capability_mechanism_id(writer_relpath: str) -> str:
    """Normalize the mechanism_id for a flagged writer: strip exactly ONE
    trailing ``_capability`` suffix, but ONLY for a file under the
    operator-capability directory (see ``_is_under_capability_dir``) --
    never for a cron/scripts writer, whose mechanism_id is its plain file
    stem and must not be altered. Making ``mechanism_id == capability_id ==
    descriptor id`` here is what makes the pause-marker filename, the
    migration-queue entry, and ``resolve_paused_op_kinds``'s descriptor
    lookup all agree with each other and with the id the rebuild-paused-
    capability flow (Task B4, F-77) rebuilds under -- it keeps the SAME id
    rather than having the operator re-declare a new one."""
    stem = Path(writer_relpath).stem
    if _is_under_capability_dir(writer_relpath) and stem.endswith(CAPABILITY_MODULE_SUFFIX):
        return stem[: -len(CAPABILITY_MODULE_SUFFIX)]
    return stem


def _find_entrypoint(operator_project_dir: Path, writer_relpath: str) -> Optional[str]:
    candidate = _wrapper_relpath_for(writer_relpath)
    if (Path(operator_project_dir) / candidate).is_file():
        return candidate
    return None


def _orchestrator_routed_entrypoint(
    operator_project_dir: Path, mechanism_id: str,
) -> Optional[str]:
    """Detect the OTHER scheduling shape: a scheduled job invoked through the
    Orchestrator (the wizard's default scheduling model — see
    ``agent_emitter._orchestrator_invocation``, which embeds a literal
    ``agent=<agent_id> cadence=...`` trigger string into ``cron_config.md``),
    rather than a dedicated ``run_<stem>.sh`` wrapper script.

    There is no per-mechanism wrapper FILE to gate in this shape — the
    Orchestrator invocation is a single inline command this module does not own
    or safely rewrite (doing so is out of this module's scope; it would mean
    editing the Orchestrator's own routing, not an operator-authored mechanism
    file). So this is DETECTION-only: it never causes anything to be paused, and
    the reconcile loop / notice renderer word this shape honestly (no auto-pause
    happened, so no continuity claim is made about it either — deny-by-default).

    Returns the ``cron_config.md`` relpath when a matching scheduled row is
    found for ``mechanism_id``, else None.
    """
    cron_config = Path(operator_project_dir) / CRON_CONFIG_REL
    if not cron_config.is_file():
        return None
    try:
        text = cron_config.read_text(encoding="utf-8")
    except OSError:
        return None
    marker = f"agent={mechanism_id} "
    if marker in text or text.rstrip().endswith(f"agent={mechanism_id}"):
        return CRON_CONFIG_REL
    return None


def _detect_entangled_read_outputs(source_text: str) -> List[str]:
    """Which read/report-shaped keywords (see ``_READ_OUTPUT_INDICATORS``) this
    file's own source (function names, docstrings, comments) surfaces — a
    heuristic (disclosed bound: textual, not semantic) signal that the SAME
    file/entrypoint that was just paused also produces read-only output the
    operator relies on. Order-stable and de-duplicated for deterministic notice
    wording."""
    lowered = source_text.lower()
    return [kw for kw in _READ_OUTPUT_INDICATORS if kw in lowered]


def _classify_read_output_entanglement(
    operator_project_dir: Path,
    writer_relpath: str,
    flagged_relpaths: Sequence[str],
) -> Tuple[Optional[bool], Optional[str], List[str]]:
    """Classify whether the entrypoint just paused ALSO carries read-only
    outputs the operator relies on (entangled) or whether a genuinely separate,
    positively-verified read-only entrypoint survives the pause untouched
    (separate). DENY-BY-DEFAULT: only returns ``(False, <relpath>, [])`` when a
    companion is POSITIVELY verified; every other case returns
    ``carries_read_outputs`` as ``True`` (entangled) or ``None`` (unknown), and
    both are treated identically by ``render_impact_notice`` — never a
    continuity promise without positive proof.

    Returns ``(carries_read_outputs, separate_readonly_entrypoint, labels)``.
    """
    writer_path = Path(operator_project_dir) / writer_relpath
    try:
        source_text = writer_path.read_text(encoding="utf-8")
    except OSError:
        return None, None, []

    labels = _detect_entangled_read_outputs(source_text)
    if labels:
        return True, None, labels

    # No entanglement signal in the writer's OWN file -- look for a genuinely
    # separate, verified read-only companion using the <stem><suffix> naming
    # convention. A candidate only counts as "verified" when it (a) exists,
    # (b) carries no scan violations of its own, and (c) has its own wrapper
    # that is neither missing nor already gated by this module.
    stem_path = Path(writer_relpath)
    for suffix in _READONLY_COMPANION_SUFFIXES:
        candidate_relpath = str(stem_path.parent / f"{stem_path.stem}{suffix}.py")
        candidate_file = Path(operator_project_dir) / candidate_relpath
        if not candidate_file.is_file():
            continue
        if candidate_relpath in flagged_relpaths:
            continue  # it has violations of its own -- not verified read-only
        candidate_wrapper_relpath = _wrapper_relpath_for(candidate_relpath)
        candidate_wrapper = Path(operator_project_dir) / candidate_wrapper_relpath
        if not candidate_wrapper.is_file():
            continue
        try:
            wrapper_text = candidate_wrapper.read_text(encoding="utf-8")
        except OSError:
            continue
        if _GUARD_BEGIN in wrapper_text:
            continue  # already paused itself -- not a surviving continuity path
        return False, candidate_wrapper_relpath, []

    return None, None, []


# ===== F-55 B2: paused_op_kinds resolution + the paused_live_write writer =====

def _load_capability_descriptor_set(operator_project_dir: Path) -> List[Dict[str, Any]]:
    """Fail-safe loader for the operator project's descriptor set
    (security/capability_descriptors.json). Mirrors write_gate.load_descriptor_set's
    own fail-safe convention exactly: absent / unreadable / malformed / non-array all
    resolve to [] -- never raises."""
    path = Path(operator_project_dir) / CAPABILITY_DESCRIPTOR_SET_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _extract_op_kind_literal(source_text: str) -> List[str]:
    """Statically extract a module-level ``OP_KIND = "<literal>"`` string
    assignment from a capability module's own source -- AST parse only, NEVER
    imported/executed (this module never runs operator-authored code).
    ``capability_code_scaffold.py``'s ``render_capability_module`` bakes exactly
    this constant into every emitted CAPABILITY-zone module (the SAME file
    this reconcile module flags under ``agents/capabilities/``) -- duplicated
    verbatim from its paired adapter module's own ``OP_KIND`` constant by
    design (see that template's own docstring on why it is duplicated, not
    imported). Returns ``[]`` when the source does not parse, or carries no
    such literal string assignment -- fail-closed/empty-safe, never guesses.

    MODULE-LEVEL ONLY (matches the docstring's own claim): this scans
    ``tree.body`` directly -- the top-level statement list of the parsed
    module -- rather than ``ast.walk`` (which would also visit an ``OP_KIND``
    assignment nested inside a function/class/branch). The emitted form this
    function targets (``capability_code_scaffold.py``'s
    ``render_capability_module``) always writes ``OP_KIND = "..."`` at
    module scope, so restricting the scan here can never miss the real
    literal -- it only prevents an unrelated nested ``OP_KIND`` name (e.g.
    inside a helper function) from being picked up by mistake."""
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


def resolve_paused_op_kinds(
    operator_project_dir: Path,
    mechanism_id: str,
    writer_relpath: str,
    descriptor_set: Sequence[Dict[str, Any]],
) -> List[str]:
    """(F-55 B2) Resolve the normalized ``paused_op_kinds`` for a flagged
    capability -- the value recorded into its pause-state marker so the
    emitted write_gate's runtime deny-branch (write_gate.evaluate_write_gate /
    PAUSED_MECHANISMS_DIR) can key on it.

    DESIGN NOTE -- a disclosed resolution of a real schema gap, not a
    pre-existing pinned mapping: the descriptor-entry schema
    (capability_registration.REGISTERED_ENTRY_KEYS /
    capability_descriptor_registry.ENTRY_KEYS) carries id / name / risk_class /
    recovery_profile_ref / declared_test_target / blast_radius_cap / accepted /
    phase_id -- NEVER an op_kind field. op_kind is not part of a descriptor
    entry anywhere in this codebase (confirmed: OperationContract itself
    carries no capability/descriptor id either -- the two are joined only by
    an Operation instance's own surface/op_kind pair, and the add-capability
    convention that a declared descriptor's id equals the capability_id /
    mechanism_id, never by a stored op_kind field). So "resolved from the
    capability's descriptor entry" is implemented here as a two-part,
    fail-closed lookup:
      1. a descriptor entry with ``id == mechanism_id`` must EXIST -- the
         documented add-capability convention (descriptor id == capability_id
         == mechanism_id/file-stem; see wizard/skills/add-capability.md).
         Absent entry => ``[]`` (empty-safe, per this task's explicit
         contract -- never guesses at an op_kind for an undeclared
         capability).
      2. the actual op_kind VALUE is read from the flagged file's OWN
         SOURCE, never invented: capability_code_scaffold.py's emitted
         CAPABILITY-zone module (exactly the file this reconcile module
         flags) carries a literal ``OP_KIND = "..."`` module-level constant
         (render_capability_module / _CAPABILITY_MODULE_TEMPLATE) -- parsed
         statically by ``_extract_op_kind_literal``.
    Returns ``[]`` if either step fails to resolve -- fail-closed/empty-safe,
    never fabricates an op_kind."""
    has_descriptor = any(
        isinstance(e, dict) and e.get("id") == mechanism_id for e in descriptor_set
    )
    if not has_descriptor:
        return []
    writer_path = Path(operator_project_dir) / writer_relpath
    try:
        source_text = writer_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return _extract_op_kind_literal(source_text)


# ===== Task B2 (F-75): missing-adapter-evidence-predicate auto-scaffold =====
#
# A DIFFERENT axis than every mechanism above: those are all driven off the AST
# bypass SCANNER (scan_operator_mechanisms), which only ever flags operator code
# that writes AROUND the gate. An existing capability that is fully gate-
# conformant -- its write path was never rewritten, the scanner has nothing to
# flag -- can STILL fall out of compliance when a contract-changing upgrade adds
# a NEW name to the shared `evidence.REQUIRED_EVIDENCE_PREDICATES` tuple (Task
# B1, F-74) that this capability's adapter, built against the OLDER contract,
# does not declare. Before this task there was no remediation for that gap at
# all (F-75): the capability would simply start failing self-QA/proof-time with
# no hint at what to do about it beyond diff-archaeology.
#
# Detection here therefore enumerates every capability the project KNOWS about
# via `capability_identity.build_capability_index` (one canonical_id per
# `agents/capabilities/<id>_capability.py` on disk) -- not just the
# scanner-flagged ones -- and, for each with an adapter module on disk
# (`agents/lib/external_write/adapters_<id>.py`, the exact filename
# `capability_code_scaffold.py`'s `CapabilityCodeSpec.adapter_module_stem`
# always emits), statically checks that module's own source (AST-parsed only,
# NEVER imported/executed -- same discipline as `_extract_op_kind_literal`
# above) for which required predicate names its Adapter class does not define.

@dataclass
class PredicateStubRemediation:
    """(Task B2, F-75) One capability whose adapter was auto-scaffolded with a
    FAILING `NotImplementedError` stub for a required evidence predicate a
    contract upgrade added that this capability's adapter -- built under an
    earlier contract -- did not declare. NEVER a passing stub (see
    `capability_code_scaffold.render_missing_evidence_predicate_stub`'s own
    anti-trust-theater docstring). The capability's proof/acceptance stays
    refused until a real implementation replaces the stub -- `capability_
    invariants` Check 7 and `copy_run_proof.validate_copy_run_proof` both
    still gate on the predicate actually WORKING, not merely existing (see
    those modules' own fixes for this same task)."""
    canonical_id: str
    adapter_relpath: str
    missing_predicates: List[str]


def _missing_evidence_predicates_for_adapter(
    source_text: str, required_predicates: Sequence[str],
) -> Optional[List[str]]:
    """AST-parse an adapter module's OWN on-disk source (never imported/
    executed) and return the subset of `required_predicates` NOT defined as a
    method on its first top-level class -- the Adapter class every
    `capability_code_scaffold`-emitted adapter module declares exactly one of
    (see `render_adapter_module`'s `${class_prefix}Adapter`). Returns `None`
    (deliberately distinct from `[]`) when the source does not parse or
    declares no top-level class at all -- ambiguous, never guessed at; the
    caller skips this capability for this pass rather than risk a false
    negative or a corrupting edit, mirroring `_extract_op_kind_literal`'s own
    fail-closed/never-guess discipline."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return None
    class_node = next((n for n in tree.body if isinstance(n, ast.ClassDef)), None)
    if class_node is None:
        return None
    defined = {
        n.name for n in class_node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    return [name for name in required_predicates if name not in defined]


def _append_missing_predicate_migration_request(
    operator_project_dir: Path,
    canonical_id: str,
    adapter_relpath: str,
    missing_predicates: Sequence[str],
    from_version: str,
    to_version: str,
) -> Path:
    """(Task B2, F-75) Land (or refresh) a durable, disk-first repair task in
    the SAME pending-migrations queue `_append_migration_request` writes to --
    the dedicated `wizard/skills/rebuild-paused-capability.md` flow reads and
    drives this queue (Task B4, F-77), so this reuses that existing hand-off
    (the "standard rebuild loop" this task's own brief points at) rather than
    inventing a second queue. `wizard/skills/add-capability.md`'s Step A used
    to surface ANY entry here generically; B4 replaced that with a direct
    hand-off to `rebuild-paused-capability` instead, since add-capability's
    own scope is a genuinely new capability only and dead-ended a naive
    operator trying to rebuild an existing paused one.

    Idempotent: re-running an upgrade REPLACES this capability's existing
    entry (keyed on mechanism_id) rather than duplicating it -- mirrors
    `_append_migration_request`'s own convention exactly.

    Distinguished from a scanner-violation entry by `"kind":
    "missing_evidence_predicates"` and a `missing_predicates` field; no
    `violations` list (there is no bypass violation here -- this capability's
    write path is unchanged and still gate-conformant; it is simply missing a
    NEWLY required adapter method)."""
    path = Path(operator_project_dir) / MIGRATION_QUEUE_REL
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
    missing_joined = "/".join(missing_predicates)
    existing.append({
        "mechanism_id": canonical_id,
        "writer_relpath": adapter_relpath,
        "entrypoint_relpath": None,
        "requested_at": _utcnow_iso(),
        "from_version": from_version,
        "to_version": to_version,
        "kind": "missing_evidence_predicates",
        "missing_predicates": list(missing_predicates),
        "reason": (
            "a contract upgrade added a required adapter evidence predicate "
            f"({missing_joined}) this capability's adapter did not declare -- a "
            "FAILING stub has been auto-scaffolded so the gap is visible instead "
            "of hidden; the capability stays paused/refused until a real "
            "implementation replaces it"
        ),
        "suggested_next_step": (
            "Use the rebuild-paused-capability flow: implement the real "
            f"{missing_joined} predicate method(s) auto-scaffolded in "
            f"{adapter_relpath} (they currently raise NotImplementedError), "
            "then let that flow carry this capability through proof and "
            "acceptance again."
        ),
        "status": "pending",
    })
    _atomic_write(path, json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def reconcile_missing_evidence_predicates(
    operator_project_dir: Path,
    build_repo_root: Path,
    *,
    from_version: str,
    to_version: str,
) -> List[PredicateStubRemediation]:
    """(Task B2, F-75) The migrator's auto-scaffold pass: for every capability
    this project KNOWS about (via `capability_identity.build_capability_index`
    -- REGARDLESS of scanner status, unlike every mechanism above), check its
    adapter module (when one exists on disk) against the SAME canonical
    required-predicate tuple (`evidence.REQUIRED_EVIDENCE_PREDICATES`, read via
    MODULE attribute access -- never a frozen name-import, so a test that
    patches this attribute on the imported module object is honored) Task B1's
    self-QA gate and the proof/run-time gate both already read. For each
    missing predicate found, scaffolds a FAILING stub onto the adapter module
    IN PLACE and queues a repair task -- never a passing stub, and never a
    silent gap.

    Best-effort, project-wide and per-capability (mirrors `_reconcile_
    conformant_rebuild_staleness`'s own convention): a failure importing the
    toolkit's own trusted `capability_identity`/`evidence` modules, or building
    the capability index, degrades to an empty result (nothing scaffolded) --
    never half-corrupts a project. A failure resolving ONE capability's
    missing predicates or insertion point (unparseable/malformed adapter
    source) skips just that capability, never the whole pass -- see
    `_missing_evidence_predicates_for_adapter`'s and `insert_missing_evidence_
    predicate_stubs`'s own never-guess docstrings for why."""
    operator_project_dir = Path(operator_project_dir)
    remediated: List[PredicateStubRemediation] = []
    try:
        capability_identity = _external_write_module(build_repo_root, "capability_identity")
        evidence = _external_write_module(build_repo_root, "evidence")
    except Exception:
        return remediated
    required = tuple(getattr(evidence, "REQUIRED_EVIDENCE_PREDICATES", ()) or ())
    if not required:
        return remediated
    try:
        index = capability_identity.build_capability_index(str(operator_project_dir))
    except Exception:
        return remediated

    for canonical_id in sorted(index.canonical_ids):
        adapter_relpath = (
            DEFAULT_EXTERNAL_WRITE_REL / f"adapters_{canonical_id}.py"
        ).as_posix()
        adapter_path = operator_project_dir / adapter_relpath
        try:
            source_text = adapter_path.read_text(encoding="utf-8")
        except OSError:
            continue  # no adapter module for this capability -- not adapter-backed, N/A
        missing = _missing_evidence_predicates_for_adapter(source_text, required)
        if not missing:
            continue
        try:
            new_source = insert_missing_evidence_predicate_stubs(source_text, missing)
        except CapabilityCodeScaffoldError:
            continue  # could not find a safe insertion point -- never guess, skip
        _atomic_write(adapter_path, new_source)
        _append_missing_predicate_migration_request(
            operator_project_dir, canonical_id, adapter_relpath, missing,
            from_version, to_version,
        )
        remediated.append(PredicateStubRemediation(
            canonical_id=canonical_id, adapter_relpath=adapter_relpath,
            missing_predicates=list(missing),
        ))
    return remediated


def _write_paused_live_write_state(
    operator_project_dir: Path,
    mechanism_id: str,
    writer_relpath: str,
    violations: List[Any],
    from_version: str,
    to_version: str,
    paused_op_kinds: List[str],
) -> None:
    """(F-55 B2) Write the pause-state marker for a ``paused_live_write``
    capability. Unlike ``_safe_pause_entrypoint``, this NEVER touches an
    entrypoint wrapper -- there is none to gate at this shape (see
    ``_is_under_capability_dir``'s own docstring). The capability keeps
    running; its live writes for the resolved ``paused_op_kinds`` are denied
    at RUNTIME instead, by the emitted write_gate's deny-branch reading this
    exact marker file (any ``*.json`` directly under
    PAUSED_MECHANISMS_DIR_REL). Mirrors ``_safe_pause_entrypoint``'s state
    shape (mechanism_id / writer_relpath / credentials_preserved /
    migration_status) with ``paused_op_kinds`` ADDED and
    ``entrypoint_relpath`` explicitly ``None``."""
    marker_path = _pause_marker_path(operator_project_dir, mechanism_id)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    if not marker_path.exists():
        marker_path.write_text("", encoding="utf-8")

    state = {
        "mechanism_id": mechanism_id,
        "writer_relpath": writer_relpath,
        "entrypoint_relpath": None,
        "state": "paused_live_write",
        "paused_op_kinds": list(paused_op_kinds),
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


# ===== Task B2: rebuild/migration forces accepted:false until re-trial =======
#
# F-62 root cause (real estate dogfood finding): a previously-ACCEPTED capability
# was rewritten into a scanner-red shape (rebuilt / migrated / never brought onto
# the current gate) and its descriptor stayed accepted:true with NO pause marker
# at all — only a manual expert edit (accepted:true -> false) prevented the
# un-retrialed, rewritten write path from being live-authorized. B1 made the
# PAUSED state coherent (accepted:false + marker + queued migration, never
# "accepted:true but paused" limbo) but never flips accepted itself — that is
# deliberately this task's job: the ONE place acceptance is REVOKED on a
# detected code change. The acceptance ceremony remains the sole writer of
# accepted:true.
#
# Fail-safe direction: if a capability's identity cannot be resolved (unknown /
# ambiguous), nothing is reset here — never a guess at which descriptor entry to
# touch. This is not a regression: a capability that cannot be resolved to a
# real, on-disk capability module was never a candidate for the runtime-block
# marker either (see resolve_paused_op_kinds's own empty-safe convention).


def _reset_accepted_for_scanner_red_capability(
    operator_project_dir: Path,
    build_repo_root: Path,
    mechanism_id: str,
    descriptor_set: List[Dict[str, Any]],
) -> Optional[str]:
    """(Task B2) Force ``descriptor.accepted`` back to ``False`` for every
    descriptor entry that resolves to the SAME capability as ``mechanism_id`` —
    a capability this reconcile just found scanner-red under
    ``agents/capabilities/`` (rebuilt, migrated, or never brought onto the
    current gate). Never inherits a prior ``accepted: true`` onto rewritten,
    un-retrialed code.

    Keys through the SAME A1 canonical-id identity resolver
    (``external_write.capability_identity``) every other lifecycle consumer
    uses — resolving ``mechanism_id`` in its own ``module_stem`` namespace and
    then matching every alias the resolved capability is known by (never a
    bare ``entry["id"] == mechanism_id`` string check), so a legacy identity
    split (a descriptor id that differs from the capability's own module stem
    — the estate/F-60 shape) still gets its accepted:true entry found and
    reset, not silently missed.

    Mutates ``descriptor_set`` in place (the caller's own just-loaded
    snapshot) and, if anything changed, atomically writes it back to
    ``security/capability_descriptors.json``. Returns the resolved
    ``canonical_id`` (for the caller to follow up with
    ``lifecycle_state.reconcile_state``), or ``None`` if this capability's
    identity could not be resolved — fail-safe: no guess, nothing touched.
    """
    try:
        capability_identity = _external_write_module(build_repo_root, "capability_identity")
        identity = capability_identity.build_capability_index(
            str(operator_project_dir)).resolve(mechanism_id, "module_stem")
    except Exception:
        return None

    changed = False
    for entry in descriptor_set:
        if (isinstance(entry, dict) and entry.get("id") in identity.aliases
                and entry.get("accepted") is True):
            entry["accepted"] = False
            changed = True
    if changed:
        _atomic_write(
            operator_project_dir / CAPABILITY_DESCRIPTOR_SET_REL,
            json.dumps(descriptor_set, indent=2, ensure_ascii=False) + "\n",
        )
    return identity.canonical_id


def _reconcile_lifecycle_state_best_effort(
    operator_project_dir: Path, build_repo_root: Path, canonical_id: str,
) -> None:
    """(Task B2) Call B1's ``lifecycle_state.reconcile_state`` so the pause-
    marker and pending-migration MATERIALIZED VIEWS become coherent with the
    (possibly just-reset) ``accepted`` SSOT. Reused, not re-implemented: this
    module already wrote its OWN marker via ``_write_paused_live_write_state``
    earlier in this same reconcile pass; ``reconcile_state`` MERGES onto that
    existing marker (adding the ``canonical_id`` field B1 introduced, and
    refreshing ``paused_op_kinds`` if stale) rather than discarding its
    upgrade-time diagnostics — see ``lifecycle_state._merge_marker_state``'s
    own docstring.

    Best-effort by design: a failure here (unresolvable identity, or a
    present-but-unreadable descriptor/migration-queue file —
    ``ReconcileStateError``) must not take down this whole upgrade-reconcile
    pass over every OTHER mechanism. The safety-critical act — forcing
    ``accepted`` back to ``False`` — has already landed (by
    ``_reset_accepted_for_scanner_red_capability``, above) regardless of
    whether this coherence step succeeds.
    """
    try:
        lifecycle_state = _external_write_module(build_repo_root, "lifecycle_state")
        lifecycle_state.reconcile_state(str(operator_project_dir), canonical_id)
    except Exception:
        pass


# ===== Task B2b: conformant-rebuild acceptance-hash staleness (the SCANNER-CLEAN half) =======
#
# B2 above only ever revokes a capability the AST scanner finds RED -- a raw kernel-write / bypass
# shape. A capability that was rebuilt but kept its `run_operation` / `run_enveloped_operation`
# call shape stays scanner-clean and NEVER enters `by_relpath` (the loop above never even sees
# it), so it would otherwise keep `accepted: true` forever: write_gate authorizes on
# `accepted is True` alone and never re-checks `implementation_hash`. This closes that half by
# running B2b's detector/revoker (`lifecycle_state.acceptance_hash_is_stale` /
# `revoke_stale_acceptance`, agents/lib/external_write/lifecycle_state.py) against EVERY
# capability-dir canonical id known to this project -- not only the scanner-flagged ones.

def _reconcile_conformant_rebuild_staleness(
    operator_project_dir: Path, build_repo_root: Path,
) -> List[str]:
    """(Task B2b) Revoke acceptance for every capability-dir capability whose
    ``implementation_hash`` no longer matches its acceptance audit record, REGARDLESS of whether
    the AST scanner flagged it -- the scanner-red ones above are already reset by
    ``_reset_accepted_for_scanner_red_capability``, and re-checking them here is a harmless no-op
    (already ``accepted: false``, so ``acceptance_hash_is_stale`` reports "not accepted -> not
    stale" and nothing further happens to them).

    Best-effort, per capability (mirrors ``_reconcile_lifecycle_state_best_effort``'s own
    convention): a failure resolving or checking ONE capability must never take down this whole
    reconcile pass over every other one.

    CEILING (disclosed, per this task's brief): this runs once per upgrade-reconcile pass -- NOT a
    per-write runtime guarantee. A stale acceptance stays live until the next upgrade/reconcile
    (or an operate-time ``revoke_stale_acceptance`` call, wired the same way at B2b's own
    docstring).

    Returns the canonical ids actually revoked this pass (never surfaced to the operator as raw
    ids directly -- see ``ReconcileResult.stale_acceptance_reset``'s own docstring)."""
    revoked: List[str] = []
    try:
        capability_identity = _external_write_module(build_repo_root, "capability_identity")
        lifecycle_state = _external_write_module(build_repo_root, "lifecycle_state")
    except Exception:
        return revoked
    try:
        index = capability_identity.build_capability_index(str(operator_project_dir))
    except Exception:
        return revoked
    for canonical_id in sorted(index.canonical_ids):
        try:
            result = lifecycle_state.revoke_stale_acceptance(
                str(operator_project_dir), canonical_id)
        except Exception:
            continue
        if getattr(result, "revoked", False):
            revoked.append(result.canonical_id)
    return revoked


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
        "# the fix is reviewed and approved through the rebuild-paused-capability flow.\n"
        "# A genuinely separate read-only entrypoint is not affected by this guard.\n"
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
    migrations queue that ``wizard/skills/rebuild-paused-capability.md`` reads
    and drives (Task B4, F-77) — this is the hand-off to the dedicated
    rebuild flow: approval-gated migration, never an automatic silent
    rewrite. ``add-capability.md`` no longer absorbs this queue; its scope is
    a genuinely new capability only.

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
            "Use the rebuild-paused-capability flow to rebuild this mechanism's write "
            "path so it routes through a registered external-write adapter "
            "(run_operation), then let that flow carry it through proof and "
            "acceptance again."
        ),
        "status": "pending",
    })
    _atomic_write(path, json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path


# ===== 4. NOTICE (plain language) ================================================

def _human_join(items: Sequence[str]) -> str:
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _pause_notice_lines(m: MechanismReport) -> List[str]:
    """The per-mechanism notice line(s) for a PAUSED mechanism (F-43 fix).

    Deny-by-default honesty: a continuity promise (the "keeps running exactly
    as before" line) is emitted ONLY when ``m.carries_read_outputs is False``
    AND a verified ``m.separate_readonly_entrypoint`` exists. Every other case
    -- entangled (``True``) or unknown/unverified (``None``) -- tells the
    operator the read-only outputs are paused too, names what is going dark
    when that is known, and says it stays dark until this mechanism is rebuilt
    and re-migrated. An uncertain case never fails toward false reassurance.
    """
    paused_line = (
        f"  - It has been paused (`{m.entrypoint_relpath}` will not make that "
        "change until this is fixed)."
    )
    if m.carries_read_outputs is False and m.separate_readonly_entrypoint:
        return [
            paused_line + " A separate part that only reads and reports to you "
            f"(`{m.separate_readonly_entrypoint}`) was checked and confirmed "
            "untouched by this — that keeps running exactly as before."
        ]
    if m.carries_read_outputs:
        what = _human_join(m.entangled_read_outputs) or "reads and reports to you"
        return [
            paused_line + f" This is the same place that produces your {what} for "
            f"you, so your {what} is paused too, not just the change it was making "
            "-- it stays dark until this is rebuilt and reviewed again."
        ]
    # Unknown / unverified: fail toward "paused too", never toward reassurance.
    return [
        paused_line + " It has not been confirmed whether this same place also "
        "reads and reports to you (a summary, an alert, a backup). Until that is "
        "checked, treat anything it reports to you as paused too, not running as "
        "before -- it comes back once this is rebuilt and reviewed again."
    ]


def render_impact_notice(
    mechanisms: List[MechanismReport], from_version: str, to_version: str,
) -> str:
    """A plain-language, non-technical impact notice: what changed, which
    capability is affected, what happens next. No jargon.

    F-43 fix: there is no unconditional "keeps running exactly as before" line
    any more (see ``_pause_notice_lines``) — a continuity claim is only ever
    made when a separate read-only entrypoint was positively verified to
    survive the pause.
    """
    if from_version == to_version:
        # (review fix, F-55 D) `wizard reconcile` re-checks the CURRENTLY
        # installed version against today's safety rules -- from_version ==
        # to_version by construction (no upgrade happened). The upgrade-
        # wording opener would misleadingly read as "upgraded from v0.13.1
        # to v0.13.1", so this path gets an honest re-check framing instead.
        opener = (
            f"Your system (version {to_version}) was checked against the current "
            "safety rules for anything that changes information outside this project "
            "(a spreadsheet, an inbox, a file store, and so on)."
        )
    else:
        opener = (
            f"Your system was upgraded from {from_version} to {to_version}. That upgrade adds "
            "a stronger check on anything that changes information outside this project "
            "(a spreadsheet, an inbox, a file store, and so on)."
        )
    lines = [
        "# Upgrade safety notice",
        "",
        opener,
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
            lines.extend(_pause_notice_lines(m))
        elif m.orchestrator_routed:
            lines.append(
                "  - This runs on a schedule through your assistant (the Orchestrator), "
                "so it could not be automatically switched off the way a direct "
                "scheduled script can be. Until it is reviewed by hand, treat anything "
                "it reads and reports to you the same as its change to your "
                "information: not verified safe, not confirmed to still be running."
            )
        elif m.state == "broken_requires_migration":
            # (F-55 B1; reworded by xvendor Finding-1) Honest state: this was
            # built against a safety interface that has since changed. The
            # OLD wording here ("it cannot run as-is right now") was an
            # overclaim for a capability that references the raw kernel
            # write primitive directly (the scanner-red shape that lands a
            # mechanism here) but may still be importable -- import-broken
            # was never verified before this text was written. The TRUE
            # statement, whether or not it can still import, is that its
            # ability to make changes outside this project has been switched
            # off until it is rebuilt: when an op_kind could be resolved
            # (m.paused_op_kinds non-empty), a runtime block was actually
            # installed via the write_gate's paused-op_kind deny-branch --
            # closing the real safety gap (a previously-ACCEPTED capability
            # in this shape was otherwise not runtime-blocked at all). It was
            # not on any automatic schedule, so there was nothing to switch
            # off there; NO continuity/"keeps running as before" claim, and
            # entanglement does not apply to something built against a
            # changed safety interface.
            lines.append(
                "  - This was built against a safety check that has since changed, so "
                "its ability to make changes outside your project has been switched "
                "off until it is rebuilt. It was not on any automatic schedule, so "
                "there was nothing to switch off there. The fix has been queued, and "
                "it will be rebuilt through the same reviewed process used for any "
                "new capability before it runs live again."
                + ("" if m.paused_op_kinds else (
                    " A runtime block could not be automatically installed for it, so "
                    "do not rely on it being blocked until it is rebuilt."
                ))
            )
        elif m.state == "paused_live_write":
            # (F-55 B2) Honest state: distinct from BOTH "paused" (an entrypoint
            # was switched off) and "broken_requires_migration" (it cannot run at
            # all) -- this one still runs, but its specific external-write
            # action(s) are blocked every time it tries them until it is rebuilt.
            # Deliberately no internal identifiers (op_kind strings) in operator-
            # facing text -- plain language only, matching every other branch here.
            lines.append(
                "  - It keeps running, but the specific change(s) it makes outside this "
                "project have been switched off every time it tries them -- until it is "
                "rebuilt through the same reviewed process used for any new capability."
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

    flagged_relpaths = list(by_relpath)
    mechanisms: List[MechanismReport] = []
    for relpath in sorted(by_relpath):
        violations = by_relpath[relpath]
        mechanism_id = _capability_mechanism_id(relpath)
        entrypoint = _find_entrypoint(operator_project_dir, relpath)
        carries_read_outputs: Optional[bool] = None
        separate_readonly_entrypoint: Optional[str] = None
        entangled_read_outputs: List[str] = []
        orchestrator_routed = False
        paused_op_kinds: List[str] = []
        # (Phase 3 Cut 1, Task B2) Set below, only for a capability-dir mechanism whose
        # identity resolves -- the canonical_id to run lifecycle_state.reconcile_state
        # against AFTER _append_migration_request has queued its migration entry (so
        # reconcile_state's own migration-queue check sees it and ensures the paused
        # marker, rather than seeing "nothing queued yet").
        lifecycle_canonical_id: Optional[str] = None
        if entrypoint:
            _safe_pause_entrypoint(
                operator_project_dir, mechanism_id, relpath, entrypoint,
                violations, from_version, to_version,
            )
            paused = True
            note = f"entrypoint {entrypoint} safe-paused"
            state = "entrypoint_paused"
            carries_read_outputs, separate_readonly_entrypoint, entangled_read_outputs = (
                _classify_read_output_entanglement(
                    operator_project_dir, relpath, flagged_relpaths)
            )
        else:
            orchestrator_entry = _orchestrator_routed_entrypoint(
                operator_project_dir, mechanism_id)
            paused = False
            if orchestrator_entry:
                orchestrator_routed = True
                state = "orchestrator_routed"
                note = (
                    "scheduled through your assistant (the Orchestrator) via "
                    f"{orchestrator_entry}; no dedicated wrapper file exists to "
                    "safe-pause automatically -- review by hand"
                )
            else:
                orchestrator_routed = False
                # (F-55 B1) No wrapper, not orchestrator-routed. If the writer
                # lives under the operator-capability directory, it has no
                # structural entrypoint to safe-pause at all (no run_<stem>.sh
                # convention applies there) and -- because this module only ever
                # sees scanner-red files -- it is import-broken and cannot run.
                # That is a stronger, more honest claim than "review by hand":
                # the fix is queued, not merely recommended.
                if _is_under_capability_dir(relpath):
                    # (F-55 B2 general primitive; xvendor Finding-1 fix) A
                    # scan_clean=True capability classifies as
                    # paused_live_write (still runnable; deny writes at
                    # RUNTIME via write_gate's op_kind marker). This module's
                    # ONLY detection channel is the AST scanner
                    # (scan_operator_mechanisms above), which returns ONLY
                    # scanner-red files, so `violations` is NEVER empty for a
                    # relpath that reached this loop -- `scan_clean` below is
                    # always False through the REAL scanner-driven path
                    # today. `scan_clean=True` remains honest scaffolding for
                    # a FUTURE non-scanner detection signal (see
                    # MechanismReport.state's docstring); it is the
                    # `scan_clean=False` branch below that is the REAL path.
                    #
                    # xvendor Finding-1 (the safety gap this closes): a
                    # scanner-red-but-IMPORTABLE capability that was
                    # PREVIOUSLY ACCEPTED (its descriptor still carries
                    # accepted:true) was classified broken_requires_migration
                    # and migration-queued, but -- because no paused_op_kinds
                    # marker was ever written for it -- write_gate's
                    # PAUSED-op_kind deny-branch had nothing to key on, so
                    # the write_gate's ACCEPTED-descriptor branch still
                    # permitted its live writes: not runtime-blocked despite
                    # the impact notice implying otherwise. So op_kind
                    # resolution + marker-writing now run for EVERY detected
                    # capability-dir scanner-red writer, regardless of
                    # `scan_clean` -- not only the (currently unreachable)
                    # scan_clean=True case above. The STATE NAME
                    # ("broken_requires_migration") is unchanged; only
                    # whether a runtime block got installed varies with
                    # whether an op_kind could be resolved.
                    scan_clean = not violations
                    descriptor_set = _load_capability_descriptor_set(operator_project_dir)
                    resolved_paused_op_kinds = resolve_paused_op_kinds(
                        operator_project_dir, mechanism_id, relpath, descriptor_set)
                    # (Phase 3 Cut 1, Task B2 -- F-62 fix) This capability's code is
                    # scanner-red under agents/capabilities/: it was rebuilt, migrated,
                    # or never brought onto the current gate. A prior accepted:true
                    # must NEVER be inherited onto that rewritten, un-retrialed write
                    # path -- force it back to accepted:false now, regardless of
                    # whether an op_kind could also be resolved for a runtime block.
                    # The acceptance ceremony remains the sole writer of accepted:true;
                    # this is the one place acceptance is REVOKED on a code change.
                    lifecycle_canonical_id = _reset_accepted_for_scanner_red_capability(
                        operator_project_dir, build_repo_root, mechanism_id, descriptor_set)
                    if resolved_paused_op_kinds:
                        paused_op_kinds = resolved_paused_op_kinds
                        _write_paused_live_write_state(
                            operator_project_dir, mechanism_id, relpath, violations,
                            from_version, to_version, resolved_paused_op_kinds,
                        )
                    if scan_clean and resolved_paused_op_kinds:
                        state = "paused_live_write"
                        note = (
                            "still runs, but its live write(s) for "
                            f"{_human_join(sorted(resolved_paused_op_kinds))} are denied "
                            "at runtime pending migration"
                        )
                    else:
                        state = "broken_requires_migration"
                        if resolved_paused_op_kinds:
                            note = (
                                "no wrapper and not orchestrator-scheduled; this "
                                "capability was built against a safety interface that "
                                "changed -- a runtime block on its live write(s) for "
                                f"{_human_join(sorted(resolved_paused_op_kinds))} has "
                                "been installed; migration queued"
                            )
                        else:
                            note = (
                                "no wrapper and not orchestrator-scheduled; this "
                                "capability was built against a safety interface that "
                                "changed and a runtime block could not be "
                                "auto-installed (no resolvable op_kind) -- migration "
                                "queued; do not rely on it until rebuilt"
                            )
                else:
                    state = "manual_review"
                    note = (
                        "no conventional schedule/entrypoint file was found for "
                        "this mechanism -- it could not be paused automatically; "
                        "review it by hand"
                    )
        _append_migration_request(
            operator_project_dir, mechanism_id, relpath, entrypoint, violations,
            from_version, to_version,
        )
        # (Phase 3 Cut 1, Task B2) Run AFTER _append_migration_request (just above) so
        # the pending-migration queue already carries this mechanism's entry when
        # reconcile_state checks it -- otherwise its "not accepted, nothing queued yet"
        # branch would see no migration open and skip ensuring the paused marker this
        # same pass just wrote. See _reconcile_lifecycle_state_best_effort's docstring.
        if lifecycle_canonical_id:
            _reconcile_lifecycle_state_best_effort(
                operator_project_dir, build_repo_root, lifecycle_canonical_id)
        mechanisms.append(MechanismReport(
            mechanism_id=mechanism_id,
            writer_relpath=relpath,
            violation_summaries=[f"{v.kind}:{v.lineno}" for v in violations],
            entrypoint_relpath=entrypoint,
            paused=paused,
            pause_note=note,
            carries_read_outputs=carries_read_outputs,
            separate_readonly_entrypoint=separate_readonly_entrypoint,
            entangled_read_outputs=entangled_read_outputs,
            orchestrator_routed=orchestrator_routed,
            state=state,
            paused_op_kinds=paused_op_kinds,
        ))

    notice_path: Optional[Path] = None
    if mechanisms:
        text = render_impact_notice(mechanisms, from_version, to_version)
        notice_path = write_impact_notice(operator_project_dir, upgrade_id, text)

    # (Task B2b) Run AFTER the scanner-driven loop above (and its notice) so this pass's own
    # revocations never interfere with — or get shadowed by — the scanner-red handling; see
    # _reconcile_conformant_rebuild_staleness's own docstring for why re-checking an
    # already-scanner-red-reset capability here is a harmless no-op.
    stale_acceptance_reset = _reconcile_conformant_rebuild_staleness(
        operator_project_dir, build_repo_root)

    # (Task B2, F-75) ALSO scanner-status-independent, same reasoning as the pass just
    # above: a fully gate-conformant capability (never scanner-flagged, nothing in
    # `mechanisms`) can still be missing a newly-required adapter evidence predicate.
    predicate_stubs_scaffolded = reconcile_missing_evidence_predicates(
        operator_project_dir, build_repo_root,
        from_version=from_version, to_version=to_version,
    )

    return ReconcileResult(
        operator_project_path=str(operator_project_dir),
        from_version=from_version,
        to_version=to_version,
        mechanisms=mechanisms,
        notice_path=str(notice_path) if notice_path else None,
        migration_queue_path=(
            str(operator_project_dir / MIGRATION_QUEUE_REL)
            if (mechanisms or stale_acceptance_reset or predicate_stubs_scaffolded) else None
        ),
        stale_acceptance_reset=stale_acceptance_reset,
        predicate_stubs_scaffolded=predicate_stubs_scaffolded,
    )


def render_reconcile_result(result: ReconcileResult) -> str:
    """Short CLI-appended summary (plain language) — the full detail lives in the
    notice file this points at.

    (Task B2b-fix, Important) MUST NOT return "" just because ``result.mechanisms`` is empty:
    a capability can be revoked ONLY via ``stale_acceptance_reset`` (a conformant rebuild that
    stayed scanner-clean the whole time -- see ``_reconcile_conformant_rebuild_staleness``),
    never entering ``mechanisms`` at all. Returning "" in that case would be a SILENT
    switch-off -- the operator's own approved capability just lost its acceptance and nothing
    was ever printed about it. Both sections are rendered (whichever are non-empty); returns ""
    only when NEITHER carries anything to report."""
    if not result.mechanisms and not result.stale_acceptance_reset:
        return ""
    lines = ["", "Upgrade safety check found something to review:"]
    for m in result.mechanisms:
        if m.paused:
            status = "paused"
        elif m.state == "paused_live_write":
            status = "paused (live-write blocked pending migration)"
        elif m.state == "broken_requires_migration":
            # (xvendor round-2, R2-2) "cannot run as-is" was the same overclaim
            # the impact-notice text already dropped for this state (see the
            # module docstring's Finding-1 note just above) -- import-broken
            # was never actually verified before this label was written. The
            # honest claim, matching the notice: its ability to write outside
            # this project was switched off, not a claim about importability.
            status = "external writes switched off -- queued for rebuild"
        else:
            status = "needs manual review (no schedule found)"
        lines.append(f"  - {m.mechanism_id}: {status}")
    for canonical_id in result.stale_acceptance_reset:
        lines.append(
            f"  - {canonical_id}: its code changed since you approved it, so its approval "
            "has been switched back off until you try it again and approve it again"
        )
    if result.notice_path:
        lines.append(f"  See {result.notice_path} for what this means and what happens next.")
    return "\n".join(lines) + "\n"
