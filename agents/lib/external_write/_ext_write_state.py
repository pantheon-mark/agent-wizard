"""The writer-state SERVICE: structural state combined with the operator's own
recorded decisions, plus the reap that clears a resolved entry and the advisory
owning-capability derivation.

This module is the public face of the bespoke-writer machinery and has been since
the coarse fail-closed completion gate was built on it -- ``lifecycle_state``,
``capability_health``, ``operator_acceptance`` and the build-side upgrade reconcile
all reach for it by this name, and it is present in every operator project already
emitted. So it keeps the name and the surface. What changed is where the code
underneath lives.

The layering, and why it exists
-------------------------------
The bespoke-writer machinery used to be two modules that imported each other, both
lazily, in opposite directions: this one reached for the active acknowledgement
records so it could label an entry ``acknowledged_risk``, and the acknowledgement
writer reached back for the open-entry list so it could refuse to record a decision
about a file nothing had flagged. Two lazy imports hide a cycle well -- neither
fails at import time, so nothing in the suite noticed -- but the cycle is what made
the eligibility rule impossible to tighten: any check the acknowledgement side
wanted to make about a writer's STATE had to come from the module that was already
asking it about decisions.

It is now four layers, and they form a DAG:

    writer_state_core   structural state -- the ``WriterState`` vocabulary, the
                        open bespoke-writer queue, and the classification that
                        depends on nothing but the queue entry and the writer file.
                        Imports NO sibling in this package, and consults NO record
                        of any human decision. That is the load-bearing property of
                        the whole split.
    writer_ack_store    the acknowledgement records: persistence, the hash-validity
                        rule, and the write primitive. Imports NO sibling either.
    _ext_write_state    this module. COMBINES the two, and keeps the reap and the
                        advisory owner derivation.
    writer_commands     the operator-invocable commands: validates via the core,
                        writes via the store. Does not depend on this module.

The queue predicates, the state vocabulary and the operator-facing entry wording
are re-exported below from the core rather than re-declared here, so every existing
consumer keeps working and there is still exactly ONE declaration of each. See
``test_external_write_writer_state_layers.py``, which asserts the graph is acyclic
AND, separately, that structural classification consults no acknowledgement state --
the first does not imply the second, and the second is what a later refactor breaks.

What "bespoke writer" means, and the fail-closed queue contract, are documented at
length in ``writer_state_core`` -- the single home for both.

The reap that CLEARS a resolved bespoke-writer entry
----------------------------------------------------
Detection alone would hold a project non-green forever, even after the operator
genuinely fixes the writer. ``reap_resolved_writer_migrations`` is the stateless,
attribution-free self-heal that REMOVES a bespoke-writer entry from the queue once
its writer is demonstrably resolved: either the writer file is gone, or its content
changed since pause-time AND it now passes the real bypass scan. Called from
``lifecycle_state.reconcile_state`` (fail-safe self-heal on read).

The reap consults the SAME AST bypass scanner the build-time gate uses
(``external_write.scan.scan_paths``), run with the hash-bound migration QUARANTINE
DISABLED (``project_root`` deliberately omitted -- see that function's docstring:
default ``None`` means the quarantine plays no part). This matters because a
quarantined file is inert, NOT migrated: the quarantine exempts a listed-paused +
hash-matched file from violations so the build does not deadlock, but that same file
is still the bespoke writer. The reap must see the file's REAL verdict, so it never
asks the quarantine and instead pairs the scan with an explicit hash-CHANGED check
(an unchanged file is never reaped, regardless of any scan result).

Enforcement ceiling (disclosure): build-time + operator-as-approver enforcement,
NOT a runtime/OS sandbox -- the same ceiling every module in this package discloses.
This module reports a state; the gate/health views that consume it are what decline
to say "done"/"normal".

Zoning note: this module is listed in ``zones.SEALED_KERNEL_MODULE_PATHS``. It
REWRITES ``pending_migrations.json`` and imports sibling kernel submodules, making
it ordinary internal kernel wiring, the same class as ``lifecycle_state.py``.
SEALED_KERNEL membership exempts it from the CAPABILITY-zone-only import-boundary
rule (so the sibling imports are legitimate kernel wiring, not a bypass); it grants
NO capability the right to import this module (that allowlist is the independent
``scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES`` set), and the module still
passes every universal bypass check on its own merits (no vendor SDK, no
write-capable credential, no raw vendor mutation, no raw ``run_operation``).

Stdlib only -- no third-party dependencies (this module ships into the operator's
own runtime, agents/lib/external_write/). The only non-stdlib imports are sibling
modules of this same trusted package, each stdlib-only; it never imports across the
build/runtime boundary.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from external_write import scan as _scan
from external_write import writer_state_core as _core

# Re-exported, NEVER re-declared: the queue predicates, the state vocabulary, the
# blocking set and the operator-facing entry wording all have exactly one
# declaration, in `writer_state_core`. Consumers of this module (`lifecycle_state`,
# `capability_health`, `operator_acceptance`, and the build-side upgrade reconcile,
# which loads this module by name) reach these through here, so the names must stay
# bound here -- but they are the SAME OBJECTS, asserted by identity in
# `test_external_write_writer_state_layers.PublicSurfaceIdentityTests`. A second
# spelling of any of them is the defect, not a convenience.
from external_write.writer_state_core import (  # noqa: F401
    BLOCKING_WRITER_STATES,
    ExternalWriteStateReadError,
    MIGRATION_QUEUE_REL,
    REMEDIABLE_VIOLATION_KINDS,
    WriterState,
    describe_blocking_entry,
    is_bypass_writer_entry,
    open_bespoke_writer_migrations,
    open_bespoke_writer_relpaths,
)


# ---------------------------------------------------------------------------
# The stateless auto-reap of a RESOLVED bespoke-writer migration entry. See the
# module docstring's reap section for the full rationale (why the scan runs with
# the quarantine DISABLED).
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
    * No recorded ``paused_content_sha256`` (a pre-quarantine / hand-authored
      entry) -> no pause-time baseline to prove the file CHANGED, so it is kept
      (never guessed reaped).
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
    # migration quarantine DISABLED (project_root deliberately omitted -- default None
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
    queue = _core.read_migration_queue(project_root)
    reaped_ids: List[str] = []
    kept: List[Any] = []
    for entry in queue:
        if _core.is_open_bespoke_writer_entry(entry):
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


# ---------------------------------------------------------------------------
# ADVISORY owning-capability link. UX ONLY -- NEVER a safety input.
# The coarse block fires on the mere EXISTENCE of an open bespoke-writer entry,
# independent of any owning-capability attribution. This section adds the
# OPPOSITE-purpose, deliberately-non-authoritative companion: a best-effort,
# ranked-evidence guess at which capability (if any) a bespoke writer belongs to,
# so a plain-language view can say "fix `<writer>` (part of `<capability>`)"
# instead of just naming a path. Nothing in this section may ever be consulted by
# a safety/block decision -- see ``test_owning_capability_advisory.py``'s
# dedicated safety-independence assertions.
# ---------------------------------------------------------------------------

# Duplicated-by-value (same discipline as MIGRATION_QUEUE_REL and every other module in
# this package -- acceptance_ceremony.py / capability_health.py / capability_identity.py each
# independently declare the identical two constants rather than importing a shared source).
CAPABILITIES_DIR_REL = "agents/capabilities"
CAPABILITY_FILE_SUFFIX = "_capability.py"
CAPABILITY_MODULE_SUFFIX = "_capability"


def _known_capability_modules(root: Path) -> Dict[str, Path]:
    """capability_id -> source file path, for every ``agents/capabilities/<capability_id>_
    capability.py`` on disk under ``root`` -- the known-capability universe ``derive_owning_
    capability`` matches a writer's evidence against. Duplicated-by-value from
    ``capability_health._capability_source_files`` (this module must not import
    ``capability_health`` -- ``capability_health`` already imports THIS module, so a reverse
    import would be circular). Fail-safe: an absent capabilities directory yields ``{}``, never
    a raise (this is advisory-only; it must never be able to abort anything)."""
    cap_dir = root / CAPABILITIES_DIR_REL
    found: Dict[str, Path] = {}
    if not cap_dir.is_dir():
        return found
    for path in sorted(cap_dir.glob(f"*{CAPABILITY_FILE_SUFFIX}")):
        if not path.is_file():
            continue
        cap_id = path.name[: -len(CAPABILITY_FILE_SUFFIX)]
        if cap_id:
            found[cap_id] = path
    return found


def _module_level_string_literal(source_text: str, target_name: str) -> Optional[str]:
    """Statically extract a module-level ``<target_name> = "<literal>"`` string assignment via
    AST parse only -- NEVER imported/executed (this module never runs operator-authored code).
    Generalizes ``lifecycle_state._extract_op_kind_literal`` / ``upgrade_reconcile._extract_
    op_kind_literal`` (duplicated-by-value, same discipline) to any single target name, so this
    one helper covers both ``OP_KIND`` and ``ENVELOPE_CAPABILITY_ID`` evidence below.
    MODULE-LEVEL ONLY (``tree.body``, not ``ast.walk``) -- matches the real emitted form (a
    capability's own ``OP_KIND`` is always written at module scope by ``capability_code_
    scaffold.py``'s ``render_capability_module``; a writer's own self-declared ``ENVELOPE_
    CAPABILITY_ID``, if any, is expected to follow the identical convention). Returns ``None``
    when the source does not parse, cannot be read, or carries no such literal -- fail-closed/
    empty-safe (toward "no evidence"), never guesses."""
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


def _imports_capability_module(source_text: str, module_stem: str) -> bool:
    """True iff ``source_text`` contains an import naming ``module_stem`` (a capability's
    module stem, e.g. ``google_sheets_capability``) -- ``import <module_stem>``, a dotted
    ``import a.b.<module_stem>``, ``from a.b import <module_stem>``, or ``from <module_stem>
    import x`` / ``from a.b.<module_stem> import x``. AST parse only, NEVER imported/executed.
    Walks the WHOLE tree (``ast.walk``), unlike the module-level-only literal extractor above --
    an import can legitimately appear anywhere a writer chooses to place it, unlike the fixed-
    convention module-scope literals. Returns ``False`` on any parse failure -- fail-closed
    toward "no evidence", never guesses."""
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


def derive_owning_capability(project_root: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """ADVISORY-ONLY: the ranked-evidence derivation of which capability, if any, OWNS
    the bespoke writer named by ``entry["writer_relpath"]`` -- used ONLY to enrich the
    plain-language "fix this file (part of X)" message a completion/acceptance view
    shows the operator (see ``lifecycle_state._completion_not_done_message``).

    THIS IS NEVER A SAFETY INPUT. The project-wide, attribution-free block (the mere
    EXISTENCE of an open bespoke-writer entry -- see ``open_bespoke_writer_migrations``)
    already covers safety regardless of whether this function resolves an owner; no
    caller may let its result change any block/refuse/done decision. See
    ``test_owning_capability_advisory.py``'s dedicated safety-independence assertions,
    which prove ``open_bespoke_writer_migrations`` / ``lifecycle_state.check_completion``
    / ``capability_health.overall_status`` fire identically for a resolved, an
    ambiguous, and an unresolved entry.

    RANKED EVIDENCE -- STRONG signals only; WEAK evidence (a writer's file stem/path
    merely resembling a capability id) is NEVER authority and is not consulted at all:
      - the writer's source imports ``<id>_capability`` for some known capability id, OR
      - the writer's source carries a literal ``ENVELOPE_CAPABILITY_ID = "<id>"`` matching a
        known capability id exactly, OR
      - the writer's own ``OP_KIND`` literal (if it has one) matches EXACTLY ONE known
        capability's own ``OP_KIND`` literal (shared with two or more -> that signal
        contributes no candidate at all -- it is not itself strong evidence for any one of
        them).
    Each signal that fires contributes the capability id(s) it points to; the UNION across all
    three signals is the candidate owner set.

    Returns ``{"owning_capability_id": <id> or None, "ownership_status": "resolved" |
    "ambiguous" | "unresolved"}``:
      - exactly one candidate            -> resolved,   owning_capability_id = that id.
      - two or more DISTINCT candidates   -> ambiguous, owning_capability_id = None.
      - zero candidates (including any read/parse failure or an empty/absent capabilities
        directory) -> unresolved, owning_capability_id = None.

    Fail-closed toward "we don't know" -- never toward fabricating/guessing a single owner it
    cannot support with strong evidence -- and never raises: a non-dict ``entry``, a missing/
    empty ``writer_relpath``, an unreadable writer file, or an unreadable/unparsable capability
    module file simply contributes no evidence (or is skipped) rather than aborting the whole
    derivation."""
    unresolved: Dict[str, Any] = {"owning_capability_id": None, "ownership_status": "unresolved"}
    if not isinstance(entry, dict):
        return unresolved
    writer_relpath = entry.get("writer_relpath")
    if not isinstance(writer_relpath, str) or not writer_relpath:
        return unresolved

    root = Path(project_root)
    try:
        writer_source = (root / writer_relpath).read_text(encoding="utf-8")
    except OSError:
        return unresolved

    known = _known_capability_modules(root)
    if not known:
        return unresolved

    candidates: set = set()

    # Signal 1: the writer imports `<id>_capability` for some known capability id.
    for cap_id in known:
        if _imports_capability_module(writer_source, f"{cap_id}{CAPABILITY_MODULE_SUFFIX}"):
            candidates.add(cap_id)

    # Signal 2: the writer carries a literal ENVELOPE_CAPABILITY_ID == <canonical id>.
    envelope_literal = _module_level_string_literal(writer_source, "ENVELOPE_CAPABILITY_ID")
    if envelope_literal is not None and envelope_literal in known:
        candidates.add(envelope_literal)

    # Signal 3: the writer's own OP_KIND literal is shared with EXACTLY ONE known capability.
    writer_op_kind = _module_level_string_literal(writer_source, "OP_KIND")
    if writer_op_kind is not None:
        sharing: List[str] = []
        for cap_id, cap_path in known.items():
            try:
                cap_source = cap_path.read_text(encoding="utf-8")
            except OSError:
                continue
            if _module_level_string_literal(cap_source, "OP_KIND") == writer_op_kind:
                sharing.append(cap_id)
        if len(sharing) == 1:
            candidates.add(sharing[0])

    if len(candidates) == 1:
        return {"owning_capability_id": next(iter(candidates)), "ownership_status": "resolved"}
    if len(candidates) >= 2:
        return {"owning_capability_id": None, "ownership_status": "ambiguous"}
    return unresolved


# ---------------------------------------------------------------------------
# The COMBINATION: structural state + the operator's recorded decisions.
# ---------------------------------------------------------------------------

def _active_acknowledgement_relpaths(project_root: str) -> set:
    """Writer relpaths carrying a VALID, hash-matching operator acknowledgement.
    Delegated to the acknowledgement store so this module never owns the record
    format. Absent module -> empty set (no acknowledgements), which is the
    fail-closed direction: without it every NEEDS_PERSON entry simply stays
    blocking.

    Imported lazily, and that is deliberate even though the cycle is gone: a
    module-scope import would make THIS module unimportable if the store were
    physically missing, and this module is hard-imported at module scope by both
    the completion gate and the health read. An operator project part-way through
    an upgrade must degrade to "no acknowledgements", not to a raw
    ModuleNotFoundError at session start."""
    try:
        from external_write import writer_ack_store as _store
    except ImportError:
        return set()
    try:
        return set(_store.active_acknowledgements(project_root))
    except Exception:
        return set()   # unreadable acknowledgement state -> treat as none -> keep blocking.


def classify_bespoke_writer_entry(project_root: str,
                                  entry: Dict[str, Any],
                                  acknowledged: Optional[set] = None) -> str:
    """Classify ONE open bespoke-writer ``entry`` into a ``WriterState`` -- the
    structural state from ``writer_state_core``, with a valid operator
    acknowledgement layered on top.

    Deterministic and fail-closed. The STRUCTURAL state is decided first, always,
    and a recorded decision can only ever change ONE of its answers:

      1. writer file ABSENT/unreadable -> BLOCKING_LIVE_ENABLE (deliberately NOT
                                          RESOLVED: the reaper is the single
                                          authority on resolution -- see
                                          ``structural_classification``)
      2. test module, unreferenced     -> NON_LIVE   (3 signals, all required)
      3. any non-remediable violation  -> NEEDS_PERSON, and ONLY here does a valid
                                          recorded decision apply, turning it into
                                          ACKNOWLEDGED_RISK
      4. otherwise                     -> BLOCKING_LIVE_ENABLE

    THE RECORD IS CHECKED LAST, NOT FIRST, AND THAT ORDER IS THE SAFETY PROPERTY.
    It used to be checked first, ahead of every other state, so a record against a
    fully REBUILDABLE writer took it straight out of the blocking set and its
    rebuild never had to happen. The eligible set is
    ``_core.ACKNOWLEDGEABLE_WRITER_STATES`` -- the SAME constant the command layer's
    own guard binds, declared once in the core.

    Both halves are needed. The command's guard stops an ineligible record being
    WRITTEN; this stops one being HONOURED. A record can reach the store without
    passing the command -- it is a plain JSON file in the project -- so this is what
    makes such a record INERT rather than trusted, for every state but one.

    The record is also applied only when the core actually got to read the writer's
    source (``source_readable``). That is load-bearing rather than incidental: a
    file that reads as BYTES but not as UTF-8 TEXT can carry a hash-matching record
    while being unclassifiable, and such a writer must stay blocking.
    ``source_readable`` comes back from the core's own single read rather than being
    re-derived here, so the two can never disagree about a file that changed in
    between.

    ``acknowledged`` may be supplied by a caller that already has the active set,
    so a report over N entries reads the store once rather than N times; ``None``
    means "look it up", and the lookup happens only where it can matter."""
    structural = _core.structural_classification(project_root, entry)
    if not structural.source_readable:
        return structural.state
    if structural.state not in _core.ACKNOWLEDGEABLE_WRITER_STATES:
        # Nothing a record could say applies to this state, so it is not even
        # consulted -- a record that named this writer is inert, not overridden.
        return structural.state

    writer_relpath = str(entry.get("writer_relpath") or "")
    if acknowledged is None:
        acknowledged = _active_acknowledgement_relpaths(project_root)
    if writer_relpath in acknowledged:
        return WriterState.ACKNOWLEDGED_RISK
    return structural.state


def blocking_bespoke_writer_migrations(project_root: str) -> List[Dict[str, Any]]:
    """The subset of ``open_bespoke_writer_migrations`` whose state is in
    ``BLOCKING_WRITER_STATES`` -- a FILTER over the attribution-free superset,
    never a different query (asserted by
    ``test_blocking_is_always_a_subset_of_open``). Raises
    ``ExternalWriteStateReadError`` on an unreadable queue, preserving the gate's
    fail-closed contract exactly."""
    acknowledged = _active_acknowledgement_relpaths(project_root)
    return [e for e in open_bespoke_writer_migrations(project_root)
            if classify_bespoke_writer_entry(project_root, e, acknowledged)
            in BLOCKING_WRITER_STATES]


def bespoke_writer_state_report(project_root: str) -> Dict[str, List[Dict[str, Any]]]:
    """Every open bespoke-writer entry bucketed by ``WriterState`` -- the
    visibility surface. Nothing becomes invisible merely because it stopped
    blocking: a NON_LIVE or ACKNOWLEDGED_RISK entry is still reported, and
    ``normal_status_allowed`` stays False while any bucket is non-empty."""
    acknowledged = _active_acknowledgement_relpaths(project_root)
    report: Dict[str, List[Dict[str, Any]]] = {
        WriterState.BLOCKING_LIVE_ENABLE: [],
        WriterState.NEEDS_PERSON: [],
        WriterState.NON_LIVE: [],
        WriterState.ACKNOWLEDGED_RISK: [],
        WriterState.RESOLVED: [],
    }
    for e in open_bespoke_writer_migrations(project_root):
        report[classify_bespoke_writer_entry(project_root, e, acknowledged)].append(e)
    return report
