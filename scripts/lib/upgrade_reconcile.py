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
import hashlib
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
    resolve_registered_adapter_classes,
)
from capability_code_scaffold import (
    _missing_evidence_predicates_for_adapter_source as _missing_evidence_predicates_for_adapter,
)
from capability_code_scaffold import (
    _update_adapter_profile_registry,
)
from adapter_migrations import ADAPTER_MIGRATIONS, MigrationContext
from provisioner_migration import PROVISIONER_NAME


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

_EXTERNAL_WRITE_IMPORT_RE = re.compile(r'\bexternal_write\b')
_DISCOVERY_EXCLUDE_DIR_NAMES = frozenset(
    {".venv", "venv", "__pycache__", ".git", ".wizard", "node_modules"})


def discover_external_write_importers(
    operator_project_dir: Path,
    *,
    exclude_dir_names: "frozenset[str]" = _DISCOVERY_EXCLUDE_DIR_NAMES,
) -> List[Path]:
    """B-opt2 (V15-3a): every .py file under the operator project that
    references the ``external_write`` package, EXCEPT the sealed lib itself
    (``agents/lib/external_write``) and excluded dirs. Deriving the reconcile's
    scan target from the real import graph -- not a fixed directory list -- is
    what makes a hand-rolled bulk runner visible wherever it lives (the estate's
    ``agents/inbox/runner.py`` was outside the old fixed OPERATOR_CODE_DIRS).

    Over-inclusion is SAFE (an extra clean file yields no violation);
    under-inclusion re-opens V15-3, so the match is deliberately broad: a
    token-anywhere text search for ``external_write`` (word-boundary-scoped,
    so ``external_write_helper`` does not match), not just an import-line
    parse. This is what makes a hand-authored runner visible even when it
    never puts ``external_write`` on an import line at all -- e.g. one that
    ``sys.path``-hacks straight into ``agents/lib/external_write`` and then
    bare-imports ``from run_envelope import mint_run_envelope`` -- because the
    ``external_write`` path literal still has to appear somewhere in the file
    (the ``sys.path.insert`` line) for that hack to work. It also still
    catches a comma-list import (``import os, external_write`` / ``import
    json, external_write as ew``) regardless of ordering, since token-anywhere
    is a superset of the import-line match. Static/textual scan only;
    dynamic or string-obfuscated references (e.g. building the
    ``external_write`` path from concatenated pieces so the literal token
    never appears) are the sole disclosed residual (near-zero for emitted,
    non-technical-operator code)."""
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
                        NOTE: this field is a REPORTING/join identity only (also
                        used for the Orchestrator cron-route match and the
                        descriptor-id join in ``resolve_paused_op_kinds`` — both
                        need the legacy stem/capability_id convention). It is
                        deliberately stem-only and CAN collide across directories
                        for a bespoke writer (see the disclosed bound this used to
                        carry here). That collision no longer reaches the
                        pending-migrations queue or the pause-marker filename,
                        though: those are keyed on ``_migration_identity``
                        instead (F-3A fix), which relpath-derives (and, where the
                        stem still collides after normalization, hash-suffixes) an
                        id ONLY for a bespoke writer whose stem actually collides
                        with another bespoke writer in the SAME discovered set —
                        see that function's own docstring for the exact guarantee
                        and why keeping THIS field on the legacy value is still
                        safe (bespoke writers have no descriptor to join back
                        against, so nothing here depends on mechanism_id being
                        collision-free).
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
                                        orchestrator-routed, and (fail-safe
                                        scaffolding only, V15-3) no violation was
                                        present for the writer either -- the
                                        pre-existing "no schedule found" fallback.
                                        Unreachable through the real scanner-driven
                                        flow today (see "broken_requires_migration",
                                        below): this module's only detection
                                        channel is the AST scanner, which returns
                                        ONLY scanner-red files, so every relpath
                                        that reaches this classification already
                                        has a non-empty `violations` list and takes
                                        that branch instead. Retained so a
                                        hypothetical future zero-violation writer
                                        still has a real, tested primitive to land
                                        on rather than this module inventing one.
                                    "broken_requires_migration" -- (B1, this task;
                                        generalized V15-3) no wrapper, not
                                        orchestrator-routed, and the writer IS
                                        scanner-red (any violation present, of any
                                        kind -- NOT gated on the writer's directory:
                                        the estate's hand-rolled bulk runner at
                                        agents/inbox/runner.py, outside the
                                        operator-capability directory, is exactly
                                        this shape). Every mechanism this module
                                        ever sees is scanner-red (the AST scanner
                                        only returns violating files), and a writer
                                        in this shape has no structural entrypoint
                                        to safe-pause. This covers TWO distinct
                                        runtime shapes, not just one: the writer may
                                        be import-broken (cannot run at all), OR it
                                        may be scanner-red but perfectly IMPORTABLE
                                        and RUNNABLE (e.g. a hand-rolled runner that
                                        imports the real, existing
                                        ``mint_run_envelope`` -- the file runs fine;
                                        that it bypasses the sanctioned surface is
                                        exactly the danger this state exists to
                                        surface). Honest state, not a continuity
                                        claim: it means "physically must migrate,"
                                        never "necessarily runtime-blocked" -- do
                                        not read "nothing was paused" as "nothing
                                        could run."
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

    same_id_twins_healed: (Task 4, F-2) capability_ids for which the descriptor set carried MORE
        THAN ONE entry sharing the exact same ``id`` with more than one unaccepted -- a
        data-integrity defect (the registry never enforces ``id`` as a primary key), NOT normal
        ambiguity. ALSO scanner-status-independent. See ``_heal_same_id_descriptor_twins``.
    """
    operator_project_path: str
    from_version: str
    to_version: str
    mechanisms: List[MechanismReport] = field(default_factory=list)
    notice_path: Optional[str] = None
    migration_queue_path: Optional[str] = None
    stale_acceptance_reset: List[str] = field(default_factory=list)
    predicate_stubs_scaffolded: List["PredicateStubRemediation"] = field(default_factory=list)
    same_id_twins_healed: List[str] = field(default_factory=list)
    read_provisioner_violations: List["ReadProvisionerViolation"] = field(
        default_factory=list)

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
    descriptor id`` here is what makes ``resolve_paused_op_kinds``'s descriptor
    lookup, the ``capability_identity`` alias index, and every other per-id
    consumer agree with each other and with the id the rebuild-paused-
    capability flow (Task B4, F-77) rebuilds under -- it keeps the SAME id
    rather than having the operator re-declare a new one. For a
    CAPABILITY-dir writer this value is ALSO what the pause-marker filename
    and migration-queue entry are keyed on (see ``_migration_identity``,
    below, which is identical to this for that shape). For a BESPOKE writer
    it no longer is -- see ``_migration_identity``."""
    stem = Path(writer_relpath).stem
    if _is_under_capability_dir(writer_relpath) and stem.endswith(CAPABILITY_MODULE_SUFFIX):
        return stem[: -len(CAPABILITY_MODULE_SUFFIX)]
    return stem


_NON_IDENTITY_CHARS_RE = re.compile(r"[^A-Za-z0-9]+")


def _migration_identity(
    writer_relpath: str,
    colliding_bespoke_stems: "frozenset[str]" = frozenset(),
) -> str:
    """(F-3A fix -- the root-cause fix for a validation-stop finding) The
    identity key used ONLY for three things: the pending-migrations queue's
    dedup/replace key (``_append_migration_request``), that same queue
    entry's ``mechanism_id`` field, and the pause-marker / pause-state
    FILENAME (``_pause_marker_path`` / ``_pause_state_path``). Never used for
    anything that needs to match the legacy per-capability_id/module-stem
    convention: the Orchestrator cron-route match
    (``_orchestrator_routed_entrypoint``), the descriptor ``id`` join in
    ``resolve_paused_op_kinds``, and the ``capability_identity`` module-stem
    resolve in ``_reset_accepted_for_scanner_red_capability`` all keep
    receiving ``_capability_mechanism_id``'s legacy value unchanged -- see
    ``reconcile_upgrade``'s call sites, which pass the two different values
    to the right places on purpose.

    For a CAPABILITY-dir writer (``_is_under_capability_dir``), this is
    IDENTICAL to ``_capability_mechanism_id`` -- unchanged, byte-for-byte.
    Many consumers depend on mechanism_id == capability_id == descriptor id
    for that shape (see ``_capability_mechanism_id``'s own docstring and this
    task's brief); this function must never diverge from it there.

    For a BESPOKE writer (anything else -- a cron/scripts mechanism, or a
    hand-rolled runner with no descriptor at all) whose bare file STEM is
    NOT in ``colliding_bespoke_stems`` (build-lead decision: relpath-keying is
    a real cost -- it degrades a clean id like "estate_upkeep" to
    "agents_cron_estate_upkeep" -- so it is paid ONLY by a writer that
    actually needs it), this returns the plain stem unchanged: identical to
    the pre-F-3A behavior, and identical to ``_capability_mechanism_id`` for
    that writer.

    For a BESPOKE writer whose stem IS in ``colliding_bespoke_stems``
    (``reconcile_upgrade`` computes this as a pre-pass: every bare stem shared
    by 2+ bespoke writers discovered in the SAME reconcile pass), this derives
    from the file's FULL project-relative path, with a short deterministic
    hex digest of that exact relpath appended -- e.g.
    ``agents/inbox/runner.py`` -> ``agents_inbox_runner_<8-hex-digest>``. The
    digest is what makes this GENUINELY collision-free (not just "usually
    distinct"): ``_NON_IDENTITY_CHARS_RE`` collapses every run of non-
    alphanumeric characters to a single "_", which is lossy -- e.g.
    ``agents/a.b/runner.py`` and ``agents/a-b/runner.py`` both normalize to
    the identical ``agents_a_b_runner`` -- so the normalized path ALONE is not
    a safe uniqueness guarantee once two colliding-stem writers also happen to
    normalize to the same string. Appending ``sha1(writer_relpath)[:8]``
    closes that gap: two DIFFERENT relpaths can never collide on both the
    normalized prefix AND the digest of their own (necessarily different)
    exact string. This is the actual bug this task fixes: the estate's real
    ``agents/inbox/runner.py`` and a hypothetical ``agents/upkeep/runner.py``
    both normalized to the SAME bare-stem mechanism_id ("runner") under the
    old scheme, so the second one processed in a single ``reconcile_upgrade``
    pass silently REPLACED the first's migration-queue entry
    (``_append_migration_request``'s own dedup-by-mechanism_id convention),
    and both wrappers' pause-marker guard blocks pointed at the exact same
    ``.wizard/paused-mechanisms/runner.*`` pair -- pausing (or later
    un-pausing) one falsely paused/unpaused the other too.

    Safe specifically because bespoke writers have no descriptor entry to
    begin with (add-capability's id-declaration convention only applies under
    ``agents/capabilities/``), so nothing downstream ever needed to join back
    on the legacy stem for them -- and the runtime write_gate's own paused-
    marker loader (``write_gate._load_paused_op_kinds``) globs every ``*.json``
    directly under the paused-mechanisms directory and unions their
    ``paused_op_kinds`` content, filename-agnostic -- so a bespoke writer's
    live-write runtime block (when one is installed) keeps working
    regardless of what its marker is named. See this task's brief ("Locked
    design") for the full analysis of every verified consumer."""
    if _is_under_capability_dir(writer_relpath):
        return _capability_mechanism_id(writer_relpath)
    p = Path(writer_relpath)
    stem = p.stem
    if stem not in colliding_bespoke_stems:
        return stem
    relpath_no_suffix = (p.parent / p.stem).as_posix()
    normalized = _NON_IDENTITY_CHARS_RE.sub("_", relpath_no_suffix).strip("_") or stem
    digest = hashlib.sha1(writer_relpath.encode("utf-8")).hexdigest()[:8]
    return f"{normalized}_{digest}"


def _migrate_legacy_bespoke_identity(
    operator_project_dir: Path,
    writer_relpath: str,
    legacy_id: str,
    migration_id: str,
) -> None:
    """(F-3A, Step 5 -- legacy-marker cleanup) A project that ran an
    upgrade-reconcile BEFORE this fix existed may carry a pause marker/state
    pair and a pending-migrations queue entry keyed on the OLD bare-stem
    identity (``legacy_id``) for a bespoke writer this fix now keys on its
    full relpath instead (``migration_id``). Left alone, that stale artifact
    would become an ORPHAN forever: nothing after this fix ever looks it up
    again by the old key, so it would neither get cleaned up nor kept
    coherent with the new one.

    No-op when ``legacy_id == migration_id`` (every capability-dir writer,
    and any bespoke writer whose derived key happens to already equal its
    legacy stem) or when no legacy artifact for THIS EXACT ``writer_relpath``
    exists. Deliberately checks the ``writer_relpath`` recorded INSIDE the
    old marker/queue-entry content before touching anything -- never a blind
    match on the bare stem alone, since an unrelated writer could coincidentally
    share that same legacy stem (that ambiguity is exactly what this fix
    closes; this cleanup must not re-introduce it by cross-wiring two
    different writers' state during migration). CRITICAL invariant fixed here:
    the legacy marker/state files are removed ONLY inside the confirmed-match
    branch below -- never as an unconditional sibling of that check. The
    unconditional form (present before this fix) deleted ANY legacy artifact
    at ``legacy_id`` the moment it existed on disk, even when its recorded
    ``writer_relpath`` belonged to a DIFFERENT writer that coincidentally
    shared the same legacy stem -- destroying that other writer's own live
    pause state.

    Also fixes a second, related fail-open: if ``writer_relpath``'s
    conventional wrapper was ALREADY safe-paused by an EARLIER reconcile pass
    (before this identity split existed), its inserted guard block is a frozen
    string that literally names the legacy marker FILENAME --
    ``_safe_pause_entrypoint`` never rewrites an existing guard (idempotent on
    ``_GUARD_BEGIN in original``). Deleting the legacy marker file without
    also updating that frozen reference would leave the guard's ``-e`` check
    pointing at nothing, silently UN-PAUSING an already-paused writer even
    though its pause state was "carried forward" onto the new key. See
    ``_rewrite_wrapper_guard_marker_id``, called below BEFORE the legacy files
    are removed, which keeps the guard and an existing marker in agreement --
    the invariant: a writer that was paused stays paused across this rekey.

    Carries the pause state FORWARD onto the new key (never silently drops
    an operator's existing pause) and removes the stale legacy-keyed
    marker/state files and queue entry so no orphan is left behind.

    Cut 1.4 fold (Finding #5b -- non-blocking minor, deferred): this only
    migrates the FORWARD direction (bare-stem `legacy_id` -> relpath-keyed
    `migration_id`, the shape a NEW stem collision produces). It does not
    handle the REVERSE transition: a writer that was relpath-keyed in some
    EARLIER pass (because it collided with another same-stem writer back
    then) whose collision no longer exists today (e.g. the other writer was
    removed) -- a fresh `migration_id` computation for it would now resolve
    back to the bare stem, but nothing here migrates a relpath-keyed marker
    back down to a stem-keyed one. The result is a stale relpath-keyed
    marker/state file left as an orphan. This is NOT a safety gap: the
    wrapper's guard block still literally references that same relpath-keyed
    `.pause` filename (see `_guard_block`/`_rewrite_wrapper_guard_marker_id`),
    so the writer correctly stays paused either way -- only the orphaned
    file's cleanup is deferred."""
    if legacy_id == migration_id:
        return
    operator_project_dir = Path(operator_project_dir)

    legacy_state_path = _pause_state_path(operator_project_dir, legacy_id)
    legacy_marker_path = _pause_marker_path(operator_project_dir, legacy_id)
    if legacy_state_path.exists():
        try:
            legacy_state = json.loads(legacy_state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            legacy_state = None
        if isinstance(legacy_state, dict) and legacy_state.get("writer_relpath") == writer_relpath:
            entrypoint_relpath = legacy_state.get("entrypoint_relpath") or _find_entrypoint(
                operator_project_dir, writer_relpath)
            # (F-3A residual fix) Capture whether the guard rewrite actually
            # succeeded -- previously discarded -- so the legacy `.pause`
            # unlink below can be gated on it. If it did NOT succeed, only
            # proceed with the unlink when there is no live guard reference
            # left to break (see `_wrapper_guard_still_references_legacy_marker`);
            # a guard that still names the legacy marker must keep that
            # marker file on disk, even as an orphan, rather than be
            # silently un-paused.
            safe_to_unlink_legacy_marker = True
            if entrypoint_relpath:
                rewrite_succeeded = _rewrite_wrapper_guard_marker_id(
                    operator_project_dir, entrypoint_relpath, legacy_id, migration_id)
                if not rewrite_succeeded:
                    safe_to_unlink_legacy_marker = not _wrapper_guard_still_references_legacy_marker(
                        operator_project_dir, entrypoint_relpath, legacy_id)

            new_state_path = _pause_state_path(operator_project_dir, migration_id)
            new_marker_path = _pause_marker_path(operator_project_dir, migration_id)
            if not new_state_path.exists():
                legacy_state["mechanism_id"] = migration_id
                _atomic_write(
                    new_state_path,
                    json.dumps(legacy_state, indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n",
                )
            if legacy_marker_path.exists() and not new_marker_path.exists():
                new_marker_path.parent.mkdir(parents=True, exist_ok=True)
                new_marker_path.write_text("", encoding="utf-8")

            # (CRITICAL fix) Remove the legacy files ONLY here, inside the
            # confirmed writer_relpath match -- see the docstring above. A
            # legacy artifact that did NOT match this writer_relpath is left
            # completely untouched: it belongs to someone else.
            #
            # (F-3A residual fix) The `.pause` sentinel specifically is
            # further gated on `safe_to_unlink_legacy_marker`: the state
            # `.json` is always cleaned up (nothing reads it by the legacy
            # key any more), but the `.pause` file a still-un-rewritten guard
            # references must be left in place -- an orphaned marker file is
            # an acceptable cost; a silently un-paused writer is not.
            stale_paths = [legacy_state_path]
            if safe_to_unlink_legacy_marker:
                stale_paths.append(legacy_marker_path)
            for stale in stale_paths:
                try:
                    stale.unlink()
                except OSError:
                    pass

    queue_path = operator_project_dir / MIGRATION_QUEUE_REL
    try:
        existing = json.loads(queue_path.read_text(encoding="utf-8")) if queue_path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except (json.JSONDecodeError, OSError):
        existing = []
    filtered = [
        e for e in existing
        if not (isinstance(e, dict) and e.get("mechanism_id") == legacy_id
                and e.get("writer_relpath") == writer_relpath)
    ]
    if len(filtered) != len(existing):
        _atomic_write(
            queue_path,
            json.dumps(filtered, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )


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
        if not (isinstance(e, dict) and e.get("mechanism_id") == canonical_id
                and e.get("kind") == "missing_evidence_predicates")
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


def _append_ambiguous_adapter_registration_manual_repair_request(
    operator_project_dir: Path,
    canonical_id: str,
    adapter_relpath: str,
    from_version: str,
    to_version: str,
) -> Path:
    """(F-1) Land (or refresh) a manual-repair task in the SAME
    pending-migrations queue `_append_missing_predicate_migration_request`
    writes to, for a capability whose adapter module has AT LEAST ONE
    module-level `register_adapter(...)` call this pass could not uniquely
    resolve to a single class (0 or >1 same-named candidates, or a
    non-constructor-call argument -- see `capability_code_scaffold.
    resolve_registered_adapter_classes`'s own docstring). Never guessed at:
    this pass scaffolds NOTHING for that registration -- a human (or a
    human-in-the-loop agent) must resolve the ambiguity by hand before any
    evidence-predicate stub can be safely targeted at it.

    Distinguished from a `missing_evidence_predicates` entry by `"kind":
    "ambiguous_adapter_registration"` -- keyed on BOTH `mechanism_id` and
    `kind` (not `mechanism_id` alone) so this entry and a co-existing
    `missing_evidence_predicates` entry for the SAME capability (e.g. one
    registration in a multi-adapter module is ambiguous while another
    resolves cleanly and genuinely needs a stub) never clobber each other.
    Idempotent: re-running an upgrade REPLACES this capability's existing
    entry of this SAME kind rather than duplicating it."""
    path = Path(operator_project_dir) / MIGRATION_QUEUE_REL
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except (json.JSONDecodeError, OSError):
        existing = []
    existing = [
        e for e in existing
        if not (isinstance(e, dict) and e.get("mechanism_id") == canonical_id
                and e.get("kind") == "ambiguous_adapter_registration")
    ]
    existing.append({
        "mechanism_id": canonical_id,
        "writer_relpath": adapter_relpath,
        "entrypoint_relpath": None,
        "requested_at": _utcnow_iso(),
        "from_version": from_version,
        "to_version": to_version,
        "kind": "ambiguous_adapter_registration",
        "reason": (
            "this adapter module has a register_adapter(...) call whose "
            "target class could not be uniquely identified by static "
            "analysis -- the evidence-predicate migrator refuses to guess "
            "which class to check or repair"
        ),
        "suggested_next_step": (
            f"Open {adapter_relpath} and confirm which class each "
            "register_adapter(...) call registers (it must be a direct "
            "ClassName() constructor call naming exactly one class defined "
            "in this module), then check that class by hand against the "
            "required evidence predicates."
        ),
        "status": "pending",
    })
    _atomic_write(path, json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path


#: Refusal reasons that mean "correctly nothing to do", not "could not act".
#: Queueing these would put a blocking entry in every already-correct project.
_BENIGN_REFUSAL_MARKERS = ("nothing to do",)


def record_adapter_migration_refusals(
    operator_project_dir: Path,
    refusals: Sequence[Tuple[str, "AdapterMigrationOutcome"]],
    *,
    from_version: str,
    to_version: str,
) -> None:
    """Persist EXACTLY the set of migrations that declined to act this run.

    A refusal that exists only as a return value is how a remediation the
    operator needed goes missing -- the one that matters most is "there is more
    than one registered adapter class, so this has to be moved by hand", which is
    a dead end unless it lands somewhere durable and visible.

    Set-reconciled, not append-only: entries of this kind are rebuilt from THIS
    run's outcomes, so a refusal whose cause has since been fixed disappears on
    the next reconcile. Append-only would be a permanent block -- this entry kind
    records no content hash (so the auto-reaper cannot clear it) and carries no
    canonical id the acceptance flow can match, which would leave a repaired
    project blocked with no operator-reachable way out.

    Single authority: only entries of this kind are added or removed; every other
    entry is left exactly as found. A benign "nothing to do" outcome is never
    recorded -- a blocking entry in an already-correct project is a guard nobody
    reads.
    """
    path = Path(operator_project_dir) / MIGRATION_QUEUE_REL
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except (json.JSONDecodeError, OSError):
        existing = []

    kept = [e for e in existing
            if not (isinstance(e, dict)
                    and e.get("kind") == "adapter_migration_refused")]

    for canonical_id, outcome in refusals:
        if any(marker in outcome.reason for marker in _BENIGN_REFUSAL_MARKERS):
            continue
        kept.append({
            "mechanism_id": canonical_id,
            "writer_relpath": outcome.relpath,
            "entrypoint_relpath": None,
            "requested_at": _utcnow_iso(),
            "from_version": from_version,
            "to_version": to_version,
            "kind": "adapter_migration_refused",
            "migration_name": outcome.migration_name,
            "reason": outcome.reason,
            "suggested_next_step": (
                f"Ask your assistant to look at {outcome.relpath} and finish this "
                "update by hand. It stopped rather than guess, so nothing has been "
                "changed in that file."),
            "status": "pending",
        })

    if kept == existing:
        return
    _atomic_write(path, json.dumps(kept, indent=2, ensure_ascii=False,
                                   sort_keys=True) + "\n")


#: Adapter modules the wizard itself ships into every project. They are
#: emitted-lib code, refreshed by the upgrade's own file delivery, and are never
#: migration targets: rewriting one in an operator's project would damage a
#: working shipped adapter. Kept as a name set rather than a zone lookup because
#: this decision is about provenance (who wrote the file), not about zoning.
_SHIPPED_ADAPTER_MODULE_NAMES = frozenset({"adapters.py", "adapters_gmail.py"})

_OPERATOR_ADAPTER_MANIFEST_REL = (
    DEFAULT_EXTERNAL_WRITE_REL / "operator_adapters.json").as_posix()


@dataclass(frozen=True)
class AdapterTargets:
    """The adapter modules this upgrade may rewrite.

    ``manifest_blocking_reason`` is set when an enrolment manifest is PRESENT but
    unusable. In that state ``relpaths`` is deliberately empty: migrating the
    subset the filename convention happens to find, and reporting success, is
    precisely the false green this resolution exists to prevent. The caller
    turns the reason into a durable blocking entry.
    """

    relpaths: Tuple[str, ...] = ()
    manifest_blocking_reason: Optional[str] = None


def resolve_adapter_migration_targets(
    operator_project_dir: Path,
    canonical_ids: Sequence[str],
) -> AdapterTargets:
    """Resolve which adapter modules the declared migration set may rewrite.

    Two sources, UNIONED, never one instead of the other:

      * the explicit enrolment manifest ``operator_adapters.json`` -- the typed
        source of truth the runtime registry already reads. Authoritative when
        present.
      * the ``adapters_<canonical_id>.py`` filename convention -- kept for
        installs that predate the manifest.

    The union is what closes the observed gap: an enrolled adapter whose filename
    does not match its capability's canonical id is invisible to the convention,
    and an install predating the manifest is invisible to the manifest.

    A PRESENT-but-unusable manifest is a fail-closed block, never a silent
    fallback. An ABSENT manifest is a clean no-op -- most installs have none.
    """
    root = Path(operator_project_dir)
    lib_rel = DEFAULT_EXTERNAL_WRITE_REL.as_posix()
    found: List[str] = []

    manifest_path = root / _OPERATOR_ADAPTER_MANIFEST_REL
    if manifest_path.exists():
        try:
            raw = manifest_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return AdapterTargets(
                (),
                f"the list of adapters you have added ({_OPERATOR_ADAPTER_MANIFEST_REL}) "
                f"could not be read ({exc.__class__.__name__}), so this upgrade "
                "cannot tell which of them still need updating")
        try:
            data = json.loads(raw)
        except ValueError:
            return AdapterTargets(
                (),
                f"the list of adapters you have added ({_OPERATOR_ADAPTER_MANIFEST_REL}) "
                "is not readable as a list, so this upgrade cannot tell which of "
                "them still need updating")
        if not isinstance(data, list) or any(
                not isinstance(stem, str) or not stem for stem in data):
            return AdapterTargets(
                (),
                f"the list of adapters you have added ({_OPERATOR_ADAPTER_MANIFEST_REL}) "
                "does not contain a plain list of adapter names, so this upgrade "
                "cannot tell which of them still need updating")
        for stem in data:
            found.append(f"{lib_rel}/{stem}.py")

    for canonical_id in canonical_ids:
        found.append(f"{lib_rel}/adapters_{canonical_id}.py")

    keep: List[str] = []
    for relpath in found:
        if Path(relpath).name in _SHIPPED_ADAPTER_MODULE_NAMES:
            continue
        if not (root / relpath).is_file():
            continue
        if relpath not in keep:
            keep.append(relpath)
    return AdapterTargets(tuple(sorted(keep)), None)


@dataclass(frozen=True)
class AdapterMigrationOutcome:
    """What ONE declared migration did to ONE adapter module.

    Recorded for changed AND unchanged outcomes alike: a refusal that goes
    nowhere is how a remediation the operator needed to know about gets lost.
    """

    relpath: str
    migration_name: str
    changed: bool
    reason: str
    detail: Tuple[str, ...] = ()


def reconcile_adapter_migrations(
    operator_project_dir: Path,
    build_repo_root: Path,
    *,
    from_version: str,
    to_version: str,
) -> Tuple[List[PredicateStubRemediation], List["AdapterMigrationOutcome"], Optional[str]]:
    """Apply every DECLARED adapter migration to every resolved adapter module.

    One read, all migrations, one atomic write per module. Composition rather
    than sequencing is the shipped form deliberately: two passes that each read
    and write the same module make the second write clobber the first from stale
    text, and no test of either pass alone would notice.

    Returns ``(predicate_remediations, outcomes, blocking_reason)``.
    ``blocking_reason`` is non-None when the adapter-enrolment manifest is
    present but unusable -- the caller turns it into a durable blocking entry
    rather than proceeding against a partial target set.

    Best-effort per module, exactly as the pass it replaces: an unparseable or
    unwritable adapter skips that module and never half-corrupts a project.

    Also reconciles every resolved target's ADAPTER_PROFILE zone-registry
    entry (``adapter_profile_registry.json``), regardless of whether that
    target's source needed a migration -- see the inline comment at the call
    site for why. Idempotent and additive only; never touches a shipped
    baseline (those are excluded from ``targets`` before this function ever
    sees them).
    """
    operator_project_dir = Path(operator_project_dir)
    remediated: List[PredicateStubRemediation] = []
    outcomes: List[AdapterMigrationOutcome] = []
    refusals: List[Tuple[str, AdapterMigrationOutcome]] = []

    try:
        capability_identity = _external_write_module(build_repo_root, "capability_identity")
        evidence = _external_write_module(build_repo_root, "evidence")
    except Exception:
        return remediated, outcomes, None
    required = tuple(getattr(evidence, "REQUIRED_EVIDENCE_PREDICATES", ()) or ())
    try:
        index = capability_identity.build_capability_index(str(operator_project_dir))
        canonical_ids = sorted(index.canonical_ids)
    except Exception:
        return remediated, outcomes, None

    targets = resolve_adapter_migration_targets(operator_project_dir, canonical_ids)
    if targets.manifest_blocking_reason:
        return remediated, outcomes, targets.manifest_blocking_reason

    external_write_dir = operator_project_dir / DEFAULT_EXTERNAL_WRITE_REL
    context = MigrationContext(required_predicates=required)
    canonical_by_relpath = {
        f"{DEFAULT_EXTERNAL_WRITE_REL.as_posix()}/adapters_{cid}.py": cid
        for cid in canonical_ids
    }

    for relpath in targets.relpaths:
        adapter_path = operator_project_dir / relpath
        try:
            source = adapter_path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue  # never guess at an unparseable adapter module

        canonical_id = canonical_by_relpath.get(relpath, Path(relpath).stem)

        _resolved, ambiguous_count = resolve_registered_adapter_classes(tree)
        if ambiguous_count:
            _append_ambiguous_adapter_registration_manual_repair_request(
                operator_project_dir, canonical_id, relpath,
                from_version, to_version,
            )

        current = source
        for migration in ADAPTER_MIGRATIONS:
            result = migration.plan(current, context)
            outcomes.append(AdapterMigrationOutcome(
                relpath=relpath, migration_name=migration.name,
                changed=result.changed, reason=result.reason,
                detail=tuple(result.detail),
            ))
            if result.changed:
                current = result.source
                if migration.name == "missing_evidence_predicates":
                    remediated.append(PredicateStubRemediation(
                        canonical_id=canonical_id, adapter_relpath=relpath,
                        missing_predicates=list(result.detail),
                    ))
                    _append_missing_predicate_migration_request(
                        operator_project_dir, canonical_id, relpath,
                        list(result.detail), from_version, to_version,
                    )
            else:
                refusals.append((canonical_id, outcomes[-1]))

        if current != source:
            _atomic_write(adapter_path, current)

        # `relpath` reached this point because resolve_adapter_migration_targets
        # already declared it an operator adapter (enrolment manifest UNION
        # canonical-id convention, shipped baselines excluded) -- not because
        # its source needed a migration. The ADAPTER_PROFILE zone allowlist is
        # a materialized view of that SAME declaration, so it is reconciled
        # here for every resolved target, changed or not: an enrolled adapter
        # missing its zone-registry entry is scan-RED on a file this reconcile
        # may have just repaired, which would block the operator's own
        # ability to rebuild or accept the fix. Reuses the sanctioned writer
        # (idempotent, additive) rather than hand-rolling the JSON. Best-
        # effort, like every other per-module step above: a failure here
        # skips this module's registration and never aborts the rest of the
        # reconcile.
        try:
            _update_adapter_profile_registry(external_write_dir, Path(relpath).name)
        except OSError:
            pass

    record_adapter_migration_refusals(
        operator_project_dir, refusals,
        from_version=from_version, to_version=to_version)

    return remediated, outcomes, None


# ===== The conformance POST-CONDITION ==========================================
#
# Every item above this line improves the enumeration of which adapter modules an
# upgrade should migrate. This check makes an enumeration bug non-fatal.
#
# It asks one question of the END STATE, after the migrations have run: for every
# op_kind a capability in this project declares, does the adapter class actually
# registered for it carry a read-client builder? The kernel builds a read facade
# unconditionally before running any capability's proposal step, so for a
# capability-declared op_kind the answer must be yes -- it is not a judgement
# call. If a migration missed a module for ANY reason -- a filename that does not
# match, an unusable enrolment manifest, a naming shape nobody predicted -- this
# still catches it and blocks.
#
# Two deliberate scope decisions, both of which a wider check gets wrong:
#
#  1. CAPABILITY-DECLARED op_kinds, not every registered one. The wizard ships
#     baseline adapters that register op_kinds no capability declares and that
#     legitimately have no read-client builder. Quantifying over every
#     registration would flag them in every project, fresh builds included, and a
#     guard that always fires is a guard people learn to click past.
#
#  2. STATIC analysis, never an import. The operator's adapters import vendor
#     SDKs this process has no reason to have, so an import-based check would
#     fail -- and therefore block -- in any project whose interpreter is not the
#     operator's. A fail-closed check that cannot run is a check that blocks
#     everything. The runtime property is asserted where dependencies are
#     controlled: the fresh-emit gate runs the real emitted wiring and proves a
#     working facade.


@dataclass(frozen=True)
class ReadProvisionerViolation:
    """One capability whose read path cannot work.

    ``kind`` is recorded on the durable queue entry so a later reader can tell a
    missing builder from a missing registration without re-deriving it.
    """

    capability_id: str
    op_kind: str
    adapter_relpath: Optional[str]
    kind: str
    reason: str


def _module_level_string_constants(tree: ast.Module) -> Dict[str, str]:
    """Module-scope ``NAME = "literal"`` assignments.

    Needed because a registration names its op_kind through a constant
    (``register_adapter(OP_KIND, Adapter())``), so resolving the registered
    op_kind means resolving that constant."""
    found: Dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                found[target.id] = node.value.value
    return found


def _registered_op_kind_classes(tree: ast.Module) -> Dict[str, str]:
    """Map each op_kind this module registers to the class name it registers.

    Reads ``register_adapter(<op_kind>, <Class>())`` calls at module scope,
    resolving an op_kind given as a module-level string constant. A
    registration contributes only when its second argument is a call of a
    bare name -- that name is recorded as-is, so a factory call such as
    ``make_adapter()`` has the same shape and still contributes, under the
    function's own name, which then fails the class lookup downstream and
    surfaces as a violation rather than a silent pass. A bare variable
    reference or a call through an attribute contributes nothing."""
    constants = _module_level_string_constants(tree)
    mapping: Dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if fname != "register_adapter" or len(node.args) < 2:
            continue
        op_arg, adapter_arg = node.args[0], node.args[1]
        if isinstance(op_arg, ast.Constant) and isinstance(op_arg.value, str):
            op_kind = op_arg.value
        elif isinstance(op_arg, ast.Name):
            op_kind = constants.get(op_arg.id, "")
        else:
            continue
        if not op_kind:
            continue
        if isinstance(adapter_arg, ast.Call) and isinstance(adapter_arg.func, ast.Name):
            mapping[op_kind] = adapter_arg.func.id
    return mapping


def _class_or_in_module_base_defines(tree: ast.Module, class_name: str,
                                     method_name: str) -> bool:
    """True when ``class_name`` -- or any base class defined in this same module,
    transitively -- declares ``method_name``.

    Inheritance within the module is a legitimate shape; flagging it would be a
    false red. Bases from other modules are not followed: this check never
    imports, so an out-of-module base is simply unprovable here, which the
    fresh-emit runnable gate covers instead."""
    by_name = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    seen = set()
    queue = [class_name]
    while queue:
        name = queue.pop()
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        node = by_name[name]
        if any(isinstance(b, ast.FunctionDef) and b.name == method_name
               for b in node.body):
            return True
        for base in node.bases:
            if isinstance(base, ast.Name):
                queue.append(base.id)
    return False


def check_read_provisioner_conformance(
    operator_project_dir: Path,
) -> List[ReadProvisionerViolation]:
    """Assert every capability-declared op_kind has a usable read-client builder.

    Static, never an import. Globs the adapter directory rather than resolving by
    filename or manifest, which is what makes it immune to a resolution bug in
    the migration's own target enumeration.

    Returns one violation per capability whose read path cannot work. An empty
    list means the property holds.
    """
    root = Path(operator_project_dir)
    lib_dir = root / DEFAULT_EXTERNAL_WRITE_REL
    caps_dir = root / DEFAULT_CAPABILITIES_REL

    # op_kind -> (adapter_relpath, class_name, parsed module)
    registry: Dict[str, Tuple[str, str, ast.Module]] = {}
    if lib_dir.is_dir():
        for adapter_path in sorted(lib_dir.glob("adapters*.py")):
            try:
                tree = ast.parse(adapter_path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            relpath = adapter_path.relative_to(root).as_posix()
            for op_kind, class_name in _registered_op_kind_classes(tree).items():
                registry.setdefault(op_kind, (relpath, class_name, tree))

    violations: List[ReadProvisionerViolation] = []
    if not caps_dir.is_dir():
        return violations

    for cap_path in sorted(caps_dir.glob(f"*{CAPABILITY_MODULE_SUFFIX}.py")):
        capability_id = cap_path.stem[: -len(CAPABILITY_MODULE_SUFFIX)]
        try:
            cap_tree = ast.parse(cap_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        op_kind = _module_level_string_constants(cap_tree).get("OP_KIND", "")
        if not op_kind:
            continue  # a capability declaring no op_kind is refused elsewhere

        entry = registry.get(op_kind)
        if entry is None:
            violations.append(ReadProvisionerViolation(
                capability_id=capability_id, op_kind=op_kind,
                adapter_relpath=None, kind="no_registered_adapter",
                reason=(
                    f"`{capability_id}` says it performs `{op_kind}`, but no "
                    "adapter in this project is registered to handle it, so it "
                    "cannot talk to the outside system at all"),
            ))
            continue

        relpath, class_name, adapter_tree = entry
        if not _class_or_in_module_base_defines(
                adapter_tree, class_name, PROVISIONER_NAME):
            violations.append(ReadProvisionerViolation(
                capability_id=capability_id, op_kind=op_kind,
                adapter_relpath=relpath, kind="read_provisioner_missing",
                reason=(
                    f"`{capability_id}` needs to look at the outside system in "
                    "read-only mode before it can work out what to change, but "
                    f"`{class_name}` in {relpath} has no read-only reader on it, "
                    "so that is not possible yet"),
            ))
    return violations


def record_read_provisioner_conformance(
    operator_project_dir: Path,
    violations: Sequence[ReadProvisionerViolation],
    *,
    from_version: str,
    to_version: str,
) -> None:
    """Persist the post-condition's verdict as durable, blocking, visible state.

    Reuses the pending-migrations queue rather than inventing a state file. The
    project-wide safety predicate selects every queue entry with a non-empty
    ``writer_relpath`` and ``pending`` status, regardless of kind or attribution,
    and an entry recording no violation kinds classifies as blocking because
    nothing recorded means nothing proven. So an entry written here is already
    open, already blocking live-enable, already named in the operator-facing
    state report, and already withholds the all-clear -- with no new blocking
    channel and no new persisted source of truth.

    Deliberately records NO content hash. The auto-reaper clears an entry whose
    file changed and which now scans clean; with a hash recorded, editing an
    unrelated line in the adapter would satisfy that and un-block a project whose
    read path was still broken. This kind is cleared by re-running the check --
    which happens on every upgrade and on every ``reconcile`` -- and by nothing
    else.

    Single authority: only entries of the kinds this check owns are added or
    removed. Every other entry is left exactly as found.
    """
    owned_kinds = {"read_provisioner_missing", "no_registered_adapter"}
    path = Path(operator_project_dir) / MIGRATION_QUEUE_REL
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except (json.JSONDecodeError, OSError):
        existing = []

    kept = [e for e in existing
            if not (isinstance(e, dict) and e.get("kind") in owned_kinds)]

    for v in violations:
        if v.kind == "no_registered_adapter":
            next_step = (
                f"`{v.capability_id}` has nothing wired up to talk to the outside "
                "system. Ask your assistant to rebuild this capability, which "
                "will create and register the adapter it needs.")
        else:
            next_step = (
                f"Ask your assistant to add the read-only reader to the adapter "
                f"in {v.adapter_relpath}. This is a change to the adapter, not to "
                f"`{v.capability_id}` itself -- rebuilding the capability will "
                "not fix it.")
        kept.append({
            "mechanism_id": v.capability_id,
            "writer_relpath": v.adapter_relpath or (
                f"{DEFAULT_CAPABILITIES_REL.as_posix()}/"
                f"{v.capability_id}{CAPABILITY_MODULE_SUFFIX}.py"),
            "entrypoint_relpath": None,
            "requested_at": _utcnow_iso(),
            "from_version": from_version,
            "to_version": to_version,
            "kind": v.kind,
            "op_kind": v.op_kind,
            "reason": v.reason,
            "suggested_next_step": next_step,
            "status": "pending",
        })

    if kept == existing:
        return
    _atomic_write(path, json.dumps(kept, indent=2, ensure_ascii=False,
                                   sort_keys=True) + "\n")


def _append_adapter_enrolment_blocking_request(
    operator_project_dir: Path,
    reason: str,
    from_version: str,
    to_version: str,
) -> Path:
    """A PRESENT-but-unusable adapter-enrolment list is a blocking state, not a
    warning. Without this the upgrade would migrate whichever subset a filename
    convention happened to find and report success -- an upgrade that says it
    worked while an enrolled adapter was skipped. Idempotent: replaces this
    kind's entry rather than duplicating it."""
    path = Path(operator_project_dir) / MIGRATION_QUEUE_REL
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except (json.JSONDecodeError, OSError):
        existing = []
    existing = [e for e in existing
                if not (isinstance(e, dict)
                        and e.get("kind") == "adapter_enrolment_unreadable")]
    existing.append({
        "mechanism_id": "adapter_enrolment",
        "writer_relpath": _OPERATOR_ADAPTER_MANIFEST_REL,
        "entrypoint_relpath": None,
        "requested_at": _utcnow_iso(),
        "from_version": from_version,
        "to_version": to_version,
        "kind": "adapter_enrolment_unreadable",
        "reason": reason,
        "suggested_next_step": (
            f"Ask your assistant to repair {_OPERATOR_ADAPTER_MANIFEST_REL}. It "
            "should be a plain list of the adapter file names you have added. "
            "Until it is readable, this upgrade cannot safely tell which "
            "adapters still need updating, so it has stopped rather than "
            "guessing."),
        "status": "pending",
    })
    _atomic_write(path, json.dumps(existing, indent=2, ensure_ascii=False,
                                   sort_keys=True) + "\n")
    return path


def record_reconcile_incomplete(
    operator_project_dir: Path,
    detail: str,
    *,
    from_version: str,
    to_version: str,
) -> Path:
    """Persist "the upgrade safety check did not finish" as a blocking state.

    The apply itself may well have succeeded, and this deliberately does not undo
    it. What it prevents is the combination that actually hurts: a completed
    apply, a safety check that crashed, a note on stderr, and a project that
    reports itself normal. Since the read path now depends on this check having
    run, not-having-run is itself a blocking condition.

    Idempotent. Uses the same queue as every other remediation, so it is picked
    up by the project-wide predicate with no new channel.
    """
    path = Path(operator_project_dir) / MIGRATION_QUEUE_REL
    try:
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(existing, list):
            existing = []
    except (json.JSONDecodeError, OSError):
        existing = []
    existing = [e for e in existing
                if not (isinstance(e, dict)
                        and e.get("kind") == "reconcile_incomplete")]
    existing.append({
        "mechanism_id": "upgrade_safety_check",
        "writer_relpath": MIGRATION_QUEUE_REL,
        "entrypoint_relpath": None,
        "requested_at": _utcnow_iso(),
        "from_version": from_version,
        "to_version": to_version,
        "kind": "reconcile_incomplete",
        "reason": (
            "the upgrade safety check could not finish, so this project has not "
            f"been confirmed safe to run ({detail})"),
        "suggested_next_step": (
            "Ask your assistant to run `wizard reconcile`. That re-runs the same "
            "safety check against what is installed now. This entry clears by "
            "itself once the check completes."),
        "status": "pending",
    })
    _atomic_write(path, json.dumps(existing, indent=2, ensure_ascii=False,
                                   sort_keys=True) + "\n")
    return path


def _clear_reconcile_incomplete(operator_project_dir: Path) -> None:
    """Remove the did-not-finish marker. Called only from a reconcile run that
    reached this point, which is the only evidence that the check completed."""
    path = Path(operator_project_dir) / MIGRATION_QUEUE_REL
    if not path.exists():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            return
    except (json.JSONDecodeError, OSError):
        return
    kept = [e for e in existing
            if not (isinstance(e, dict)
                    and e.get("kind") == "reconcile_incomplete")]
    if kept != existing:
        _atomic_write(path, json.dumps(kept, indent=2, ensure_ascii=False,
                                       sort_keys=True) + "\n")


def reconcile_missing_evidence_predicates(
    operator_project_dir: Path,
    build_repo_root: Path,
    *,
    from_version: str,
    to_version: str,
) -> List[PredicateStubRemediation]:
    """Back-compatible projection over :func:`reconcile_adapter_migrations`.

    Kept because existing callers and tests name this function; it is no longer
    a separate pass. There is exactly ONE pass over adapter modules now, and it
    applies every declared migration.
    """
    remediated, _outcomes, _blocking = reconcile_adapter_migrations(
        operator_project_dir, build_repo_root,
        from_version=from_version, to_version=to_version)
    return remediated


# ===== F-3B: hash-bound content record for scan.py's migration quarantine ====
#
# Anti-deadlock coupling with F-3A (relpath-keyed migration identity, Task 1):
# `_safe_pause_entrypoint`/`_write_paused_live_write_state` gate a writer's
# wrapper (or install a runtime block) WITHOUT ever touching the flagged
# `writer_relpath` file itself, and `_append_migration_request` queues it for
# the operator's rebuild flow -- but the file stays exactly as scanner-red as
# it was before. Left alone, the NEXT time the real build-time gate runs
# (`python3 agents/lib/external_write/scan.py agents/`, recursively) it
# re-flags that SAME still-unmigrated file and fails the build: a hard
# deadlock, since a non-technical operator has no way to "fix" a violation
# that is, by design, awaiting a future rebuild rather than an immediate
# repair. `scan.py`'s hash-bound quarantine (F-3B) closes that gap by
# exempting a violation ONLY when it is provably the SAME pause-time
# violation on the SAME unedited file -- this helper records the content hash
# that quarantine hinges on.
def _content_sha256(operator_project_dir: Path, writer_relpath: str) -> Optional[str]:
    """sha256 hex digest of ``writer_relpath``'s CURRENT on-disk bytes, read at
    pause/queue-time. Becomes ``paused_content_sha256`` in both the pause
    marker and the pending-migrations queue entry. Returns ``None`` -- never
    fabricates a hash -- if the file cannot be read; a caller storing
    ``None`` simply means the quarantine can never match it later (fail-
    closed), the same "cannot resolve, do not guess" discipline every other
    helper in this module follows (see `_extract_op_kind_literal`'s own
    docstring)."""
    try:
        content = (Path(operator_project_dir) / writer_relpath).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(content).hexdigest()


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
        "paused_content_sha256": _content_sha256(operator_project_dir, writer_relpath),
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


# ===== Task 4 (F-2): heal same-id descriptor twins at source =================================
#
# The D' single-line acceptance command (operator_acceptance.py's `resolve_pending_phase`)
# derives a capability's phase from its descriptor entry; when the descriptor set carries MORE
# THAN ONE entry sharing the exact same `id` (the registry never enforces `id` as a primary
# key), that is a data-integrity defect -- an `identity_conflict` (see capability_health.py's
# `_same_id_unaccepted_conflict_ids`) -- not something a non-technical operator should ever be
# asked to dedup by hand. This heals it AT SOURCE, during the SAME scanner-status-independent
# reconcile pass as B2b/B2 above, so a corrupted registry self-heals on the next upgrade.

def _heal_same_id_descriptor_twins(operator_project_dir: Path) -> List[str]:
    """(Task 4, F-2) Dedup/strip unaccepted orphaned same-id descriptor twins in
    ``security/capability_descriptors.json``.

    For every capability_id with 2+ raw entries sharing that EXACT id string where MORE THAN
    ONE of them is unaccepted (the same trigger ``capability_health`` surfaces as
    ``identity_conflict``):
      * exactly one of the group is ``accepted: true`` -- keep it, strip every unaccepted
        duplicate (they add nothing an accepted row doesn't already carry: the ledger/audit
        history any of them might have authorized is keyed by the shared ``id`` string, not by
        the row's position in the array, so it stays reachable regardless of which row survives);
      * none of the group is accepted -- keep the FIRST occurrence (stable, deterministic),
        strip the rest (a clean, never-touched duplicate carries no state of its own to lose --
        the same "safe to retire" reasoning ``capability_health``'s normalized-twin
        classification already applies to a different-but-equivalent shape);
      * MORE THAN ONE of the group is accepted -- a genuinely contradictory shape this function
        does not resolve; left completely untouched for a person to sort out (never guessed).

    A group with only ONE unaccepted entry (0 or 1) is entirely untouched, whether or not it
    also has an accepted row -- this mirrors ``capability_health``'s own ">1 unaccepted" trigger
    exactly, so healing and detection never disagree about what counts as a conflict.

    Returns the sorted list of capability_ids actually healed this pass (mirrors every other
    scanner-status-independent pass's own "ids acted on" return convention, e.g.
    ``_reconcile_conformant_rebuild_staleness``). Fail-safe: an absent/unreadable/malformed
    descriptor set is a normal no-op (``[]``), never a raised error blocking the rest of
    reconcile -- mirrors ``_load_capability_descriptor_set``'s own fail-safe convention (this
    function reuses it rather than re-reading the file a second way)."""
    entries = _load_capability_descriptor_set(operator_project_dir)
    if not entries:
        return []

    by_id: Dict[str, List[int]] = {}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        cap_id = entry.get("id")
        if isinstance(cap_id, str) and cap_id:
            by_id.setdefault(cap_id, []).append(idx)

    keep_indices = set(range(len(entries)))
    healed: List[str] = []
    for cap_id, idxs in by_id.items():
        if len(idxs) <= 1:
            continue
        accepted_idxs = [i for i in idxs if entries[i].get("accepted") is True]
        unaccepted_idxs = [i for i in idxs if entries[i].get("accepted") is not True]
        if len(unaccepted_idxs) <= 1:
            # Not this check's concern -- 0 or 1 unaccepted entry in the group, whether or not
            # an accepted row is also present (mirrors capability_health's own trigger exactly).
            continue
        if len(accepted_idxs) > 1:
            # Genuinely contradictory -- more than one row claims to be THE accepted one for
            # this id. Not auto-resolved; leave every row untouched for a human to sort out.
            continue
        if len(accepted_idxs) == 1:
            # Keep the accepted row; every unaccepted duplicate is a stale, safely-discardable
            # twin -- the accepted row is now authoritative.
            for i in unaccepted_idxs:
                keep_indices.discard(i)
        else:
            # None accepted -- keep the first occurrence (stable, deterministic), strip the rest.
            for i in unaccepted_idxs[1:]:
                keep_indices.discard(i)
        healed.append(cap_id)

    if not healed:
        return []

    new_entries = [entries[i] for i in sorted(keep_indices)]
    _atomic_write(
        operator_project_dir / CAPABILITY_DESCRIPTOR_SET_REL,
        json.dumps(new_entries, indent=2, ensure_ascii=False) + "\n",
    )
    return sorted(healed)


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


def _wrapper_guard_marker_ref(entrypoint_relpath: str, mechanism_id: str) -> str:
    """The exact marker-existence-check path string the inserted guard block
    (see ``_guard_block``) embeds for ``mechanism_id``, as seen from
    ``entrypoint_relpath``'s own wrapper location. Cut 1.4 fold (Finding #5a
    -- non-blocking minor, DRY): extracted so
    ``_rewrite_wrapper_guard_marker_id`` and ``_wrapper_guard_still_
    references_legacy_marker`` -- which each used to reconstruct this SAME
    string independently -- can never silently diverge if the marker-path
    format ever changes. This is on the fail-closed pause-safety path
    (F-3B coupling): a mismatch between the two reconstructions could either
    fail to rewrite a stale guard reference, or fail to detect one still
    present -- both would silently un-pause a writer. Pure string
    construction; no I/O."""
    prefix = _relative_prefix(entrypoint_relpath)
    return f"{prefix}/{PAUSED_MECHANISMS_DIR_REL}/{mechanism_id}.pause"


def _rewrite_wrapper_guard_marker_id(
    operator_project_dir: Path,
    entrypoint_relpath: str,
    legacy_id: str,
    migration_id: str,
) -> bool:
    """(F-3A CRITICAL fix) ``entrypoint_relpath``'s wrapper may ALREADY carry a
    safe-pause guard block inserted by an EARLIER reconcile pass (before this
    identity split existed). That guard's marker-existence check
    (``_guard_block``) is a FROZEN string literally naming the ``legacy_id``
    ``.pause`` filename -- ``_safe_pause_entrypoint`` never rewrites an
    existing guard (its own idempotency check is exactly ``_GUARD_BEGIN not
    in original``). If ``_migrate_legacy_bespoke_identity`` then moved/removed
    that legacy marker file without also updating this frozen reference, the
    guard's ``-e`` check would find nothing and the wrapper would run the
    paused script again -- silently UN-PAUSING a writer that was safe-paused
    before this fix landed.

    Rewrites that ONE embedded path in place, from the legacy filename to the
    new ``migration_id``-keyed filename, so the guard and the marker this
    same reconcile pass (re)writes under ``migration_id`` stay in agreement.
    No-op (returns False) when there is no guard block, the ids already
    match, or the guard does not reference the exact legacy filename (nothing
    to migrate) -- never a blind substring replace that could touch an
    unrelated marker reference."""
    if legacy_id == migration_id:
        return False
    wrapper_path = Path(operator_project_dir) / entrypoint_relpath
    try:
        original = wrapper_path.read_text(encoding="utf-8")
    except OSError:
        return False
    if _GUARD_BEGIN not in original:
        return False
    old_marker_ref = _wrapper_guard_marker_ref(entrypoint_relpath, legacy_id)
    new_marker_ref = _wrapper_guard_marker_ref(entrypoint_relpath, migration_id)
    if old_marker_ref not in original:
        return False
    _atomic_write(wrapper_path, original.replace(old_marker_ref, new_marker_ref))
    return True


def _wrapper_guard_still_references_legacy_marker(
    operator_project_dir: Path, entrypoint_relpath: str, legacy_id: str,
) -> bool:
    """(F-3A residual fix, Step 5 gate) Best-effort read of
    ``entrypoint_relpath``'s CURRENT on-disk content -- called only after a
    ``_rewrite_wrapper_guard_marker_id`` attempt did NOT return ``True`` -- to
    tell apart the two reasons that can happen: (a) there was never a guard
    block naming the legacy marker to begin with (no wrapper, no
    ``_GUARD_BEGIN``, or a guard that already names something else), in which
    case deleting the legacy ``.pause`` file is harmless; versus (b) a guard
    IS present and still literally names the legacy marker file, in which
    case deleting it would leave that guard's ``-e`` check pointing at
    nothing -- silently un-pausing the writer. Mirrors
    ``_rewrite_wrapper_guard_marker_id``'s own read + reference-reconstruction
    logic, but never mutates anything; any read failure is treated as "no
    guard to protect" (fail-closed lives in the caller only withholding the
    unlink when this returns True, not in guessing here)."""
    wrapper_path = Path(operator_project_dir) / entrypoint_relpath
    try:
        content = wrapper_path.read_text(encoding="utf-8")
    except OSError:
        return False
    if _GUARD_BEGIN not in content:
        return False
    old_marker_ref = _wrapper_guard_marker_ref(entrypoint_relpath, legacy_id)
    return old_marker_ref in content


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
        "paused_content_sha256": _content_sha256(operator_project_dir, writer_relpath),
    }
    _pause_state_path(operator_project_dir, mechanism_id).parent.mkdir(
        parents=True, exist_ok=True)
    _atomic_write(
        _pause_state_path(operator_project_dir, mechanism_id),
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


# ===== Task E (Cut 1.5 / v0.19.0): ADVISORY owning-capability link -- UX ONLY ===================
#
# Duplicated-by-value from ``_ext_write_state.derive_owning_capability`` (wizard/agents/lib/
# external_write/_ext_write_state.py) -- never imported: THIS module is build-side toolkit
# (ships via ``wizard self-update``), that module is the emitted runtime kernel copied into the
# operator's own project. Every shared algorithm crossing that boundary is duplicated-by-value,
# never imported, the same discipline this module already follows for
# ``MIGRATION_QUEUE_REL``/``PAUSED_MECHANISMS_DIR_REL``/etc. -- see this module's own imports
# and ``_ext_write_state.py``'s module docstring.
#
# Stamps ``owning_capability_id`` / ``ownership_status`` onto a bespoke-writer migration entry
# AT THE MOMENT IT IS QUEUED (``_append_migration_request``, immediately below) -- a purely
# advisory annotation a completion/acceptance view MAY use to enrich its plain-language message
# ("fix `<writer>` (part of `<capability>`)"). NEVER a safety input: Task A's project-wide,
# attribution-free block (the mere EXISTENCE of an open bespoke-writer entry) already covers
# safety regardless of whether this resolves an owner -- nothing in ``reconcile_upgrade`` or
# anywhere else in this module may ever let these two fields change a scan/pause/queue decision.
# See ``test_owning_capability_advisory.py``'s dedicated safety-independence assertions for the
# runtime-side proof of this same boundary.

def _owning_capability_known_modules(operator_project_dir: Path) -> Dict[str, Path]:
    """capability_id -> source file path, for every ``agents/capabilities/<capability_id>_
    capability.py`` on disk under ``operator_project_dir`` -- the known-capability universe this
    derivation matches a writer's evidence against. Fail-safe: an absent capabilities directory
    yields ``{}``, never a raise (this is advisory-only; it must never be able to abort
    anything)."""
    cap_dir = Path(operator_project_dir) / DEFAULT_CAPABILITIES_REL
    found: Dict[str, Path] = {}
    if not cap_dir.is_dir():
        return found
    suffix = f"{CAPABILITY_MODULE_SUFFIX}.py"
    for path in sorted(cap_dir.glob(f"*{suffix}")):
        if not path.is_file():
            continue
        cap_id = path.name[: -len(suffix)]
        if cap_id:
            found[cap_id] = path
    return found


def _owning_capability_module_literal(source_text: str, target_name: str) -> Optional[str]:
    """Statically extract a module-level ``<target_name> = "<literal>"`` string assignment via
    AST parse only -- NEVER imported/executed. Generalizes ``_extract_op_kind_literal`` (same
    discipline) to any single target name, so this one helper covers both ``OP_KIND`` and
    ``ENVELOPE_CAPABILITY_ID`` evidence below. MODULE-LEVEL ONLY (``tree.body``, not
    ``ast.walk``). Returns ``None`` when the source does not parse, cannot be read, or carries
    no such literal -- fail-closed/empty-safe (toward "no evidence"), never guesses."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        else:
            continue
        if isinstance(target, ast.Name) and target.id == target_name:
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


def _owning_capability_imports_module(source_text: str, module_stem: str) -> bool:
    """True iff ``source_text`` contains an import naming ``module_stem`` (a capability's
    module stem, e.g. ``google_sheets_capability``) -- ``import <module_stem>``, a dotted
    ``import a.b.<module_stem>``, ``from a.b import <module_stem>``, or ``from <module_stem>
    import x`` / ``from a.b.<module_stem> import x``. AST parse only, NEVER imported/executed.
    Walks the WHOLE tree (``ast.walk``), unlike the module-level-only literal extractor above --
    an import can legitimately appear anywhere a writer chooses to place it. Returns ``False`` on
    any parse failure -- fail-closed toward "no evidence", never guesses."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_stem or alias.name.endswith("." + module_stem):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == module_stem or node.module.endswith("." + module_stem)
            ):
                return True
            for alias in node.names:
                if alias.name == module_stem:
                    return True
    return False


def _derive_owning_capability_at_reconcile(
    operator_project_dir: Path, writer_relpath: str,
) -> Tuple[Optional[str], str]:
    """ADVISORY-ONLY ranked-evidence derivation, called once at migration-queue-write time by
    ``_append_migration_request`` (never re-derived later by this module -- a completion/
    acceptance view on the RUNTIME side may re-derive fresh via ``_ext_write_state.derive_
    owning_capability`` instead of trusting this stamp; see that function's own docstring for
    the full ranked-evidence contract this mirrors: STRONG-only evidence -- the writer imports
    ``<id>_capability``, OR carries a literal ``ENVELOPE_CAPABILITY_ID`` matching a known
    capability id, OR shares its ``OP_KIND`` with EXACTLY ONE known capability; WEAK stem/path
    similarity is NEVER authority).

    Returns ``(owning_capability_id_or_None, "resolved" | "ambiguous" | "unresolved")``. NEVER a
    safety input and never raises: any read/parse failure, a missing writer file, or an absent/
    empty capabilities directory simply contributes no evidence rather than aborting."""
    try:
        writer_source = (Path(operator_project_dir) / writer_relpath).read_text(encoding="utf-8")
    except OSError:
        return None, "unresolved"

    known = _owning_capability_known_modules(operator_project_dir)
    if not known:
        return None, "unresolved"

    candidates: set = set()

    # Signal 1: the writer imports `<id>_capability` for some known capability id.
    for cap_id in known:
        if _owning_capability_imports_module(
            writer_source, f"{cap_id}{CAPABILITY_MODULE_SUFFIX}"
        ):
            candidates.add(cap_id)

    # Signal 2: the writer carries a literal ENVELOPE_CAPABILITY_ID == <canonical id>.
    envelope_literal = _owning_capability_module_literal(writer_source, "ENVELOPE_CAPABILITY_ID")
    if envelope_literal is not None and envelope_literal in known:
        candidates.add(envelope_literal)

    # Signal 3: the writer's own OP_KIND literal is shared with EXACTLY ONE known capability.
    writer_op_kind = _owning_capability_module_literal(writer_source, "OP_KIND")
    if writer_op_kind is not None:
        sharing: List[str] = []
        for cap_id, cap_path in known.items():
            try:
                cap_source = cap_path.read_text(encoding="utf-8")
            except OSError:
                continue
            if _owning_capability_module_literal(cap_source, "OP_KIND") == writer_op_kind:
                sharing.append(cap_id)
        if len(sharing) == 1:
            candidates.add(sharing[0])

    if len(candidates) == 1:
        return next(iter(candidates)), "resolved"
    if len(candidates) >= 2:
        return None, "ambiguous"
    return None, "unresolved"


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
    # (Cut 1.5 / v0.19.0, Task E -- ADVISORY ONLY, never a safety input) Best-effort
    # owning-capability attribution, computed once here at queue-write time. See
    # `_derive_owning_capability_at_reconcile`'s own docstring immediately above for the
    # ranked-evidence contract and the hard "never gates safety" boundary this stamp must
    # never be allowed to cross.
    owning_capability_id, ownership_status = _derive_owning_capability_at_reconcile(
        operator_project_dir, writer_relpath)
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
        # (F-3B, anti-deadlock) scan.py's hash-bound migration quarantine keys
        # on this exact field to verify the paused file has not been edited
        # since pause-time -- see `_content_sha256`'s own docstring.
        "paused_content_sha256": _content_sha256(operator_project_dir, writer_relpath),
        "suggested_next_step": (
            "Use the rebuild-paused-capability flow to rebuild this mechanism's write "
            "path so it routes through a registered external-write adapter "
            "(run_operation), then let that flow carry it through proof and "
            "acceptance again."
        ),
        # (Cut 1.5 / v0.19.0, Task E) ADVISORY ONLY -- see the derivation's own docstring.
        # `owning_capability_id` is None unless `ownership_status == "resolved"`.
        "owning_capability_id": owning_capability_id,
        "ownership_status": ownership_status,
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
    # (F-3A, build-lead decision) Relpath-keying is a real cost -- it degrades a
    # clean id like "estate_upkeep" to "agents_cron_estate_upkeep" -- so pay it
    # ONLY for a bespoke (non-agents/capabilities/) writer whose bare stem
    # actually collides with another bespoke writer discovered in THIS SAME
    # pass. A one-off bespoke writer (no collision) keeps its bare-stem id,
    # unchanged from pre-F-3A behavior. See `_migration_identity`'s docstring.
    _bespoke_stem_counts: Dict[str, int] = {}
    for _r in by_relpath:
        if not _is_under_capability_dir(_r):
            _stem = Path(_r).stem
            _bespoke_stem_counts[_stem] = _bespoke_stem_counts.get(_stem, 0) + 1
    colliding_bespoke_stems = frozenset(
        stem for stem, count in _bespoke_stem_counts.items() if count > 1)

    mechanisms: List[MechanismReport] = []
    for relpath in sorted(by_relpath):
        violations = by_relpath[relpath]
        mechanism_id = _capability_mechanism_id(relpath)
        # (F-3A fix) The identity used ONLY for the migration-queue dedup/entry
        # and the pause-marker/state FILENAME -- see `_migration_identity`'s
        # own docstring for why this must stay separate from `mechanism_id`
        # above (which keeps its legacy stem/capability_id value for the
        # Orchestrator cron-route match, the descriptor-id join, and the
        # capability_identity resolve, below).
        migration_id = _migration_identity(relpath, colliding_bespoke_stems)
        _migrate_legacy_bespoke_identity(
            operator_project_dir, relpath, mechanism_id, migration_id)
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
                operator_project_dir, migration_id, relpath, entrypoint,
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
                # (F-55 B1; V15-3 generalization) No wrapper, not orchestrator-
                # routed. This module's ONLY detection channel is the AST
                # scanner (scan_operator_mechanisms above), which returns ONLY
                # scanner-red files -- so `violations` is NEVER empty for a
                # relpath that reached this loop through the real scanner-
                # driven path. A scanner-red writer with no structural
                # entrypoint to safe-pause has no honest "keeps running as
                # before" story -- it is queued for migration regardless of
                # WHICH directory it happens to live under (the estate's
                # hand-rolled bulk runner at agents/inbox/runner.py, well
                # outside the operator-capability directory, is exactly this
                # shape). Routes generically on "any violation present" -- not
                # on the specific violation `kind` (e.g. sealed_kernel_import)
                # and not on `_is_under_capability_dir` -- so every future
                # scanner-red kind and every writer location inherits the
                # same honest handling automatically. The `else` branch below
                # (`manual_review`) is retained as fail-safe scaffolding for a
                # hypothetical writer that reaches this loop with NO
                # violations at all -- unreachable through the real scanner-
                # driven flow today (mirrors the existing `scan_clean=True`
                # scaffolding just below), never a live path in practice.
                if violations:
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
                            operator_project_dir, migration_id, relpath, violations,
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
            operator_project_dir, migration_id, relpath, entrypoint, violations,
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

    # (Task 4, F-2) Heal same-id descriptor twins FIRST, before any of the passes below read
    # the descriptor set again -- a corrupted registry (two rows sharing an id) is cleaned up
    # before other scanner-status-independent reconciliation runs against it, rather than after.
    same_id_twins_healed = _heal_same_id_descriptor_twins(operator_project_dir)

    # (Task B2b) Run AFTER the scanner-driven loop above (and its notice) so this pass's own
    # revocations never interfere with — or get shadowed by — the scanner-red handling; see
    # _reconcile_conformant_rebuild_staleness's own docstring for why re-checking an
    # already-scanner-red-reset capability here is a harmless no-op.
    stale_acceptance_reset = _reconcile_conformant_rebuild_staleness(
        operator_project_dir, build_repo_root)

    # (Task B2, F-75) ALSO scanner-status-independent, same reasoning as the pass just
    # above: a fully gate-conformant capability (never scanner-flagged, nothing in
    # `mechanisms`) can still be missing a newly-required adapter evidence predicate.
    # ONE pass over adapter modules, applying every DECLARED migration to each.
    # Membership in the declared set is the only way a migration runs, so a
    # migration nobody remembered to call cannot exist.
    (predicate_stubs_scaffolded,
     adapter_migration_outcomes,
     adapter_targets_blocking_reason) = reconcile_adapter_migrations(
        operator_project_dir, build_repo_root,
        from_version=from_version, to_version=to_version,
    )

    # A completed run clears any marker a previous crashed run left behind --
    # otherwise a one-off failure would block the project permanently.
    _clear_reconcile_incomplete(operator_project_dir)

    # THE POST-CONDITION. Runs after the migrations, against the end state, so a
    # gap in what they enumerated cannot produce a green upgrade with a broken
    # read path. Its verdict is durable and blocking, never a printed note.
    read_provisioner_violations = check_read_provisioner_conformance(
        operator_project_dir)
    record_read_provisioner_conformance(
        operator_project_dir, read_provisioner_violations,
        from_version=from_version, to_version=to_version,
    )
    if adapter_targets_blocking_reason:
        _append_adapter_enrolment_blocking_request(
            operator_project_dir, adapter_targets_blocking_reason,
            from_version, to_version,
        )

    return ReconcileResult(
        operator_project_path=str(operator_project_dir),
        from_version=from_version,
        to_version=to_version,
        mechanisms=mechanisms,
        notice_path=str(notice_path) if notice_path else None,
        migration_queue_path=(
            str(operator_project_dir / MIGRATION_QUEUE_REL)
            if (mechanisms or stale_acceptance_reset or predicate_stubs_scaffolded
                or read_provisioner_violations) else None
        ),
        stale_acceptance_reset=stale_acceptance_reset,
        predicate_stubs_scaffolded=predicate_stubs_scaffolded,
        same_id_twins_healed=same_id_twins_healed,
        read_provisioner_violations=read_provisioner_violations,
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
    only when NEITHER carries anything to report.

    (This function renders EVERY section that carries something to report. It
    returns "" only when none of them do. A field that does real work to the
    operator's project and renders nothing is a silent switch-off; that has now
    happened twice in this function's history, once per field, so the guard
    enumerates the fields rather than naming two of them.)"""
    if not (result.mechanisms or result.stale_acceptance_reset
            or result.predicate_stubs_scaffolded
            or result.read_provisioner_violations):
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
    for remediation in result.predicate_stubs_scaffolded:
        lines.append(
            f"  - {remediation.canonical_id}: a check it was missing has been "
            f"added to {remediation.adapter_relpath} as a placeholder, so it "
            "stays switched off until someone writes the real check")
    for violation in result.read_provisioner_violations:
        if violation.kind == "no_registered_adapter":
            lines.append(
                f"  - {violation.capability_id}: nothing in this project is set "
                "up to talk to the outside system for it, so it cannot run")
        else:
            lines.append(
                f"  - {violation.capability_id}: it cannot look at the outside "
                f"system in read-only mode yet -- the adapter in "
                f"{violation.adapter_relpath} needs a read-only reader added to "
                "it (this is an adapter change, not a rebuild of the capability)")
    if result.notice_path:
        lines.append(f"  See {result.notice_path} for what this means and what happens next.")
    elif result.migration_queue_path:
        # No impact notice was written this pass (nothing scanner-flagged), but a
        # repair task WAS queued (a scaffolded predicate stub, most often) -- point
        # at the durable queue file so this isn't the silent switch-off the
        # docstring above warns about.
        lines.append(f"  See {result.migration_queue_path} for what this means and what happens next.")
    return "\n".join(lines) + "\n"
