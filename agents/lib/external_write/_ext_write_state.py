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

import ast
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

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


# ---------------------------------------------------------------------------
# Task E (Cut 1.5 / v0.19.0): ADVISORY owning-capability link. UX ONLY -- NEVER a safety input.
# See the module docstring's Task A section: the block above fires on the mere EXISTENCE of an
# open bespoke-writer entry, independent of any owning-capability attribution. This section adds
# the OPPOSITE-purpose, deliberately-non-authoritative companion: a best-effort, ranked-evidence
# guess at which capability (if any) a bespoke writer belongs to, so a plain-language view can
# say "fix `<writer>` (part of `<capability>`)" instead of just naming a path. Nothing in this
# section may ever be consulted by a safety/block decision -- see
# ``test_owning_capability_advisory.py``'s dedicated safety-independence assertions.
# ---------------------------------------------------------------------------

# Duplicated-by-value (same discipline as MIGRATION_QUEUE_REL above and every other module in
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
    """ADVISORY-ONLY (Task E, Cut 1.5 / v0.19.0): the ranked-evidence derivation of which
    capability, if any, OWNS the bespoke writer named by ``entry["writer_relpath"]`` -- used
    ONLY to enrich the plain-language "fix this file (part of X)" message a completion/
    acceptance view shows the operator (see ``lifecycle_state._completion_not_done_message``).

    THIS IS NEVER A SAFETY INPUT. Task A's project-wide, attribution-free block (the mere
    EXISTENCE of an open bespoke-writer entry -- see ``open_bespoke_writer_migrations`` above)
    already covers safety regardless of whether this function resolves an owner; no caller may
    let its result change any block/refuse/done decision. See ``test_owning_capability_
    advisory.py``'s dedicated safety-independence assertions, which prove ``open_bespoke_writer_
    migrations`` / ``lifecycle_state.check_completion`` / ``capability_health.overall_status``
    fire identically for a resolved, an ambiguous, and an unresolved entry.

    RANKED EVIDENCE -- STRONG signals only; WEAK evidence (a writer's file stem/path merely
    resembling a capability id) is NEVER authority and is not consulted at all:
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
# Task 1 (Cut 1.6 / v0.20.0): deterministic STATE CLASSES over the open
# bespoke-writer set.
#
# ADR-0046's coarse, attribution-free gate WORKED and is NOT undone here:
# ``open_bespoke_writer_migrations`` above is untouched and remains the single
# attribution-free definition of "is there an open external-write bypass".
# What the v0.19.0 real-operator validation found (F-VAL19-1 / F-VAL19-5) is
# that making EVERY open entry block EVERYTHING means one unrepairable writer
# bricks acceptance project-wide, permanently, with no operator-reachable exit
# -- ADR-0046's own "never block the REPAIR" principle holding locally and
# failing globally.
#
# THE DECIDABILITY MOVE. "Does a reachable remediation exist?" is undecidable
# in general -- proving a behaviour-preserving rewrite to scan-clean code
# exists is exactly the semantic judgement the coarse gate exists to keep out
# (both cross-vendor advisors independently rejected asking it). So we do not
# ask it. We ask a question we CAN answer: does OUR OWN deterministic
# remediator cover every violation recorded on this entry? That is decidable,
# because we know what our remediator does. It keys on the scanner's recorded
# violation KINDS, which the reconcile already persists on each entry.
#
# DELIBERATE DEVIATION FROM ADVISOR OUTPUT -- DO NOT "SIMPLIFY" BACK.
# gpt-5.5's proposed table listed ``needs_person`` as NON-blocking. That
# silently re-opens F-VAL18-1 (acceptance green around an unmigrated LIVE
# writer, no human in the loop). Here NEEDS_PERSON REMAINS BLOCKING; its only
# sanctioned exit is an explicit, hash-bound operator acknowledgement (Task 3)
# -- a recorded human decision, never a classifier's silent judgement.
# Guarded by test_writer_state_classes.test_needs_person_without_
# acknowledgement_is_blocking.
# ---------------------------------------------------------------------------

class WriterState:
    """The five states an open bespoke-writer entry can be in. Plain string
    constants (not an Enum) so they serialize into health/report JSON directly,
    matching how every other typed signal in this package is surfaced."""

    BLOCKING_LIVE_ENABLE = "blocking_live_enable"
    NEEDS_PERSON = "needs_person"
    NON_LIVE = "non_live"
    ACKNOWLEDGED_RISK = "acknowledged_risk"
    RESOLVED = "resolved"   # reserved: emitted by the REAPER, never by classify_bespoke_writer_entry


#: Violation kinds OUR OWN remediation covers. The rebuild flow rewrites a
#: bespoke writer onto the sanctioned bulk path, and Cut 1.6's kernel-runner
#: injection removes the capability's reason to name a client/adapter at all --
#: between them these five kinds are mechanically fixable. Verified against all
#: 7 real estate entries 2026-07-25: agents/inbox/runner.py and
#: scripts/finish_estate_cleanup.py record only kinds from this set (correctly
#: BLOCKING -- we can fix them), while agents/upkeep/runner.py additionally
#: records ``forbidden_import`` (correctly NEEDS_PERSON -- F-VAL19-1's entangled
#: urllib notification delivery, which no remediator of ours rewrites).
REMEDIABLE_VIOLATION_KINDS = frozenset({
    "adapter_module_import",
    "adapter_registry_reference",
    "sealed_kernel_import",
    "raw_run_operation_reference",
    "credential_provider_reference",
})

#: Declared invocation surfaces -- the places the running system says what it
#: actually invokes. Used only to DISQUALIFY a non_live classification, never to
#: grant one.
_LIVE_SURFACE_RELPATHS = (
    "agents/cron/cron_config.md",
    "agents/roster.md",
)

#: Directory names that are never operator code and never an invocation
#: surface: vendored dependencies, VCS internals, and derived caches. Excluded
#: from the reference scan entirely. (Real estate case 2026-07-25: `.venv`
#: carried third-party pycparser modules that are INTENTIONALLY unparseable,
#: and scanning them fail-closed every non_live classification in the project.)
_NON_PROJECT_DIRS = frozenset({
    ".venv", "venv", ".git", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", "site-packages", "build", "dist",
})


def _recorded_violation_kinds(entry: Dict[str, Any]) -> set:
    """The set of violation ``kind`` strings recorded on ``entry`` by the
    reconcile at pause time. Unknown/odd shapes contribute a sentinel that is
    NOT in ``REMEDIABLE_VIOLATION_KINDS``, so anything unrecognised fails
    closed toward NEEDS_PERSON rather than toward "we can fix it"."""
    kinds = set()
    for v in entry.get("violations") or []:
        if isinstance(v, dict):
            kind = v.get("kind") or v.get("rule")
            kinds.add(str(kind) if kind else "__unrecognised__")
        else:
            kinds.add("__unrecognised__")
    return kinds


def _matches_test_naming(writer_relpath: str) -> bool:
    """Signal 1 of 3 for non_live: unittest discovery naming."""
    stem = Path(writer_relpath).name
    return stem.startswith("test_") or stem.endswith("_test.py")


def _has_test_structure(source_text: str) -> bool:
    """Signal 2 of 3 for non_live: the module actually contains test-framework
    structure -- a ``unittest``/``pytest`` import AND either a TestCase-shaped
    class or a ``test_*`` function. AST-parsed, never a text grep, so a mere
    mention in a string or comment does not qualify. Unparseable -> False
    (fail-closed: an unparseable module is never granted non_live)."""
    try:
        tree = ast.parse(source_text)
    except (SyntaxError, ValueError):
        return False

    imports_framework = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[0] in ("unittest", "pytest") for a in node.names):
                imports_framework = True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in ("unittest", "pytest"):
                imports_framework = True
    if not imports_framework:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                if name == "TestCase":
                    return True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                return True
    return False


def _referenced_by_live_surface(root: Path, writer_relpath: str) -> bool:
    """Signal 3 of 3 for non_live (inverted): is this writer named by anything
    the running system actually invokes? True DISQUALIFIES non_live.

    Checks the declared invocation surfaces (cron config / roster) and any
    non-test Python module in the project that names this writer's relpath or
    module stem. Any read failure returns True (fail-closed: unverifiable means
    we must not grant the non-blocking classification)."""
    stem = Path(writer_relpath).stem

    # Declared invocation surfaces are prose/tables, not code -- a textual
    # match is the only available signal and the right one there.
    for rel in _LIVE_SURFACE_RELPATHS:
        p = root / rel
        try:
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8")
        except OSError:
            return True
        if writer_relpath in text or stem in text:
            return True

    # Python modules are parsed, never grepped. A COMMENT mentioning the module
    # is NOT an invocation (real estate case: agents/inbox/runner.py carries
    # `# Header / From parsing (pure -- see test_inbox_runner.py)`), whereas an
    # import or a string literal naming it IS. The AST gives exactly that
    # discrimination for free: comments are absent from the tree, string
    # literals are not. A text grep here would be the same infer-from-
    # incidental-text defect class ADR-0045 exists to close.
    try:
        candidates = list(root.rglob("*.py"))
    except OSError:
        return True
    for p in candidates:
        try:
            rel_posix = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel_posix == writer_relpath:
            continue
        if _matches_test_naming(rel_posix):
            continue          # a test referencing a test does not make it live
        if "/lib/external_write/" in "/" + rel_posix:
            continue          # the sealed kernel is not an invocation surface
        parts = set(Path(rel_posix).parts)
        if parts & _NON_PROJECT_DIRS:
            continue          # vendored/derived trees are not invocation surfaces.
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return True       # unreadable -> cannot verify -> fail closed.
        # Cheap, over-inclusive PRE-FILTER: a file that never mentions this
        # writer cannot reference it, so it is irrelevant and is never parsed.
        # Without this, one unparseable file ANYWHERE would disqualify every
        # non_live classification -- the same "one bad file bricks everything"
        # fault this cut exists to fix.
        if writer_relpath not in text and stem not in text:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return True       # mentions it but unparseable -> fail closed.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name.split(".")[-1] == stem for a in node.names):
                    return True
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.split(".")[-1] == stem or any(a.name == stem for a in node.names):
                    return True
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if writer_relpath in node.value or node.value.strip() == stem:
                    return True
    return False


def _active_acknowledgement_relpaths(project_root: str) -> set:
    """Writer relpaths carrying a VALID, hash-matching operator acknowledgement
    (Task 3). Delegated to ``writer_acknowledgement`` so this module never owns
    the acknowledgement record format. Absent module -> empty set (no
    acknowledgements), which is the fail-closed direction: without it every
    NEEDS_PERSON entry simply stays blocking."""
    try:
        from external_write import writer_acknowledgement as _ack
    except ImportError:
        return set()
    try:
        return set(_ack.active_acknowledgements(project_root))
    except Exception:
        return set()   # unreadable acknowledgement state -> treat as none -> keep blocking.


def classify_bespoke_writer_entry(project_root: str,
                                  entry: Dict[str, Any],
                                  acknowledged: Optional[set] = None) -> str:
    """Classify ONE open bespoke-writer ``entry`` into a ``WriterState``.

    Deterministic and fail-closed: every path that cannot positively establish a
    non-blocking state returns ``BLOCKING_LIVE_ENABLE``. Precedence:

      1. writer file ABSENT            -> RESOLVED   (agrees with the Cut 1.5
                                                      reap predicate; never a
                                                      second conflicting truth)
      2. valid acknowledgement present -> ACKNOWLEDGED_RISK
      3. test module, unreferenced     -> NON_LIVE   (3 signals, all required)
      4. any non-remediable violation  -> NEEDS_PERSON  (STILL BLOCKING)
      5. otherwise                     -> BLOCKING_LIVE_ENABLE

    An INACCESSIBLE-but-present writer is never RESOLVED (os.stat-style
    absent-vs-inaccessible distinction, via the read's own exception type --
    never ``os.path.exists``/``is_file``, which conflate the two)."""
    root = Path(project_root)
    writer_relpath = str(entry.get("writer_relpath") or "")
    if not writer_relpath:
        return WriterState.BLOCKING_LIVE_ENABLE

    writer_path = root / writer_relpath
    try:
        source_text = writer_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Deliberately NOT "absent -> RESOLVED". ``reap_resolved_writer_migrations`` is the SINGLE
        # authority on whether a writer is resolved -- it owns the full predicate (absent OR
        # hash-changed-AND-scan-clean) and it REMOVES the entry. A second, weaker resolution rule
        # here would be two authorities over one fact: exactly the duplicated-inference defect
        # class ADR-0045 exists to close, and it would silently un-block an entry the reaper has
        # not cleared. So an unreadable/absent writer simply falls through to fail-closed BLOCKING;
        # reconcile-on-read runs the reaper moments later and the entry disappears properly.
        # (Caught by test_open_bespoke_bypass_refuses_live_enable_with_no_partial_state, whose
        # fixture has no writer file on disk -- that keystone regression test found this.)
        return WriterState.BLOCKING_LIVE_ENABLE

    if acknowledged is None:
        acknowledged = _active_acknowledgement_relpaths(project_root)
    if writer_relpath in acknowledged:
        return WriterState.ACKNOWLEDGED_RISK

    if (_matches_test_naming(writer_relpath)
            and _has_test_structure(source_text)
            and not _referenced_by_live_surface(root, writer_relpath)):
        return WriterState.NON_LIVE

    kinds = _recorded_violation_kinds(entry)
    if not kinds:
        return WriterState.BLOCKING_LIVE_ENABLE   # nothing recorded -> unprovable -> block.
    if kinds - REMEDIABLE_VIOLATION_KINDS:
        return WriterState.NEEDS_PERSON
    return WriterState.BLOCKING_LIVE_ENABLE


#: The states that hold back live-enable. NEEDS_PERSON is deliberately here --
#: see the section header. Only an explicit operator acknowledgement moves an
#: entry out of it.
BLOCKING_WRITER_STATES = frozenset({
    WriterState.BLOCKING_LIVE_ENABLE,
    WriterState.NEEDS_PERSON,
})


def blocking_bespoke_writer_migrations(project_root: str) -> List[Dict[str, Any]]:
    """The subset of ``open_bespoke_writer_migrations`` whose state is in
    ``BLOCKING_WRITER_STATES`` -- a FILTER over the attribution-free superset,
    never a different query (asserted by
    ``test_blocking_is_always_a_subset_of_open``). Raises
    ``ExternalWriteStateReadError`` on an unreadable queue, preserving ADR-0046's
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
