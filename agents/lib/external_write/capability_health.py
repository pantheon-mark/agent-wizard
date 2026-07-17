"""Emitted capability health-check module (F-55 C — session_2026-07-14 estate finding).

Why this exists
----------------
The estate dogfood found the session-start orientation inviting the operator
into a capability whose source file was import-broken (F-55 A/estate finding):
nothing DETERMINISTIC stood between "a capability exists on disk" and "an
agent tells the operator it is available to use". This module is that missing
composite health signal: a typed, deterministic, per-capability record an
agent's orientation prose (T5) reads BEFORE ever inviting the operator into a
capability, so it can refuse to invite the operator into one that is broken
(import-broken or scanner-red) or paused/pending-migration.

The typed status this module produces lives BELOW the LLM — pure, disk-read,
deterministic Python, no model judgment involved in computing it. What
happens with that status ("don't invite the operator into a red capability")
is agent-followed prose consuming this status, not a runtime/OS-level gate —
the same build-time + operator-as-approver enforcement ceiling every other
module in this package discloses, not a stronger claim.

What "health" means here
-------------------------
For each capability this module finds, health is RED iff ANY of:
  * the capability's source is not statically scanner-clean (an
    external_write.scan violation was found in it), OR
  * the capability could not be imported at all (a broken dependency, a
    syntax the AST scanner missed catching some other way, or a plain
    ImportError), OR
  * the capability is paused (an upgrade-reconcile safe-pause marker exists
    for it under ``.wizard/paused-mechanisms/``), OR
  * the capability has a pending migration request queued in
    ``agents/handoffs/pending_migrations.json``, OR
  * ``state_read_error`` is True — the pause-marker state and/or the
    migration queue EXISTS but could not be read/parsed for this capability,
    so "paused"/"pending_migration" could not be POSITIVELY determined
    either way (xvendor Fix B; see ``_is_paused`` / ``_is_pending_migration``
    below). Treated the same as a confirmed-paused/confirmed-pending
    capability: fail-closed to RED, never a silent "not paused" guess.
Otherwise health is GREEN. There is no third state: a capability this module
cannot positively verify clean, importable, unpaused, unqueued, AND
positively-read is RED — fail-closed, mirroring every other disclosed-bound
convention in this package (``write_gate.load_descriptor_set``'s "any missing
input ... returns []", not a raise and not a silent permissive default).
A missing/absent file (nothing yet written) is a NORMAL, non-error input for
every one of these checks — it is only an EXISTING-but-unreadable/malformed
file that signals ``state_read_error`` or the descriptor-enumeration sentinel
below; "absent" and "unreadable" are deliberately never conflated (the same
distinction ``write_gate._load_paused_op_kinds`` draws between a genuinely
absent marker directory and an inaccessible one).

Descriptor-enumeration degradation (xvendor Fix B)
------------------------------------------------------------------------------
``_load_descriptor_ids`` enumerates capability_ids declared in
``security/capability_descriptors.json`` (see "Enumeration" below). If that
file EXISTS but cannot be read or parsed, this module does NOT silently
resolve to the empty set — doing so would DROP a descriptor-only capability
(one with no source file, so it is enumerated ONLY via the descriptor set)
from the result entirely: a false all-clear, not a red flag, for exactly the
capability this checker exists to protect against inviting the operator into.
Instead ``check_capabilities`` inserts one additional sentinel record, keyed
``SENTINEL_DESCRIPTOR_ENUMERATION_ERROR_ID``, with ``health: "red"`` — so an
agent reading this module's output sees the health check ITSELF is degraded,
never a false all-clear for the capabilities it could still enumerate from
disk.

AST-first, import-second (the side-effect-safety ordering this module exists
to get right)
------------------------------------------------------------------------------
A retired-surface capability that references the raw kernel write primitive
(``run_operation``) trips ``external_write.scan``'s
``raw_run_operation_reference`` rule (CAPABILITY zone) even though the SAME
file might raise an ImportError if actually imported (e.g. a stale relative
import, a renamed dependency). Importing a module runs its module-scope code
— including any side effect a retired/compromised capability's top level
might perform. So this module NEVER imports a capability whose source is
already scanner-RED: the deterministic AST scan runs first, and an import is
attempted ONLY for a capability that scanned clean. This is not a performance
optimization; it is a safety ordering (see ``check_capabilities`` below).

The import itself then runs in an ISOLATED SUBPROCESS (``sys.executable -c``),
never in this process — a broken OR merely unexpected capability module must
never be able to crash, hang, or otherwise disturb the process running this
health check. The subprocess is given a bounded timeout, a controlled ``cwd``
(the project root — capability modules are written assuming they run from
there) and a controlled ``PYTHONPATH`` (the project's own
``agents/lib``, since a capability module imports ``external_write.*``
relative to that directory), and its stderr is captured (discarded here, but
never allowed to propagate as a crash in THIS process).

Enumeration — the union, not either set alone
------------------------------------------------------------------------------
A capability can exist in the machine-readable descriptor set
(``security/capability_descriptors.json`` — every DECLARED capability,
`accepted` flag varying, mirroring ``write_gate.load_descriptor_set``'s own
"holds the FULL set" discipline) without a source file (e.g. removed on disk
but never un-declared), or as a source file
(``agents/capabilities/<capability_id>_capability.py``) without a descriptor
entry (e.g. add-capability wrote the code before the descriptor step ran).
Checking only one side would silently miss the other half of a real broken
state, so this module enumerates the UNION of both, keyed by capability_id —
a capability_id present in ONLY the descriptor set (no source file to scan or
import) is reported RED (not importable, not scanner-clean — there is nothing
on disk to positively verify either property against), never silently
skipped.

Stdlib only — no third-party dependencies (this module ships into the
operator's own runtime, agents/lib/external_write/).
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# sys.path bootstrap: mirrors scan.py's own convention so this module also
# works if ever run/imported in a context where the ``external_write``
# package's parent (``agents/lib``) is not already on sys.path (e.g. invoked
# as a standalone script rather than imported as part of the package).
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write import scan  # noqa: E402
from external_write.capability_identity import (  # noqa: E402
    build_capability_index,
    IdentityResolutionError,
)


# ---------------------------------------------------------------------------
# Project-root-relative locations this module reads. Every one of these is
# duplicated-by-value from its own canonical owner (never imported across the
# build/runtime boundary — this module is emitted runtime code, the owners
# below are build-side or sibling-runtime modules) and pinned equal to that
# owner BY VALUE in a build-side cross-test in
# scripts/lib/test_capability_health.py (TestPathConstantsAntiDrift) — same
# discipline write_gate.py's PAUSED_MECHANISMS_DIR uses against
# upgrade_reconcile.py's PAUSED_MECHANISMS_DIR_REL, pinned in
# scripts/lib/test_external_write_write_gate.py
# (TestPausedMechanismsDirAntiDrift).
# ---------------------------------------------------------------------------

CAPABILITIES_DIR_REL = "agents/capabilities"
CAPABILITY_FILE_SUFFIX = "_capability.py"
DESCRIPTOR_SET_REL = "security/capability_descriptors.json"
PAUSED_MECHANISMS_DIR_REL = ".wizard/paused-mechanisms"
MIGRATION_QUEUE_REL = "agents/handoffs/pending_migrations.json"

# Bounded so a hung/broken capability import can never hang this checker.
IMPORT_TIMEOUT_SECONDS = 20

# (xvendor Fix B) The sentinel capability_id `check_capabilities` inserts, with
# health "red", when the descriptor set file EXISTS but could not be read or
# parsed -- signaling the health CHECK ITSELF is degraded (enumeration may be
# missing a descriptor-only capability_id) rather than silently reporting a
# false all-clear. See `_load_descriptor_ids` / `_DescriptorEnumerationError`.
SENTINEL_DESCRIPTOR_ENUMERATION_ERROR_ID = "__capability_health_check_degraded__"


class _DescriptorEnumerationError(Exception):
    """Raised internally by `_load_descriptor_ids` when the descriptor set
    file EXISTS but could not be read/parsed -- the capability_id union this
    module enumerates from might be missing a descriptor-only capability.
    Always caught by `check_capabilities`, which converts it into the single
    RED sentinel record (`SENTINEL_DESCRIPTOR_ENUMERATION_ERROR_ID`). Never
    escapes this module."""

# The subprocess program that attempts the import, path-addressed (capability
# files are not necessarily importable by dotted module name — they live
# under agents/capabilities/, not inside a package this process has already
# imported), via importlib.util rather than a bare ``import`` statement.
_IMPORT_HARNESS = """
import importlib.util
import sys

_spec = importlib.util.spec_from_file_location("_capability_health_probe", {path!r})
if _spec is None or _spec.loader is None:
    sys.exit(1)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
"""


def _load_descriptor_ids(project_root: Path) -> Set[str]:
    """The set of capability_ids declared in the descriptor set.

    Fail-safe on the genuinely-ABSENT case ONLY: a descriptor set file that
    does not exist yields the empty set — never raises, never crashes the
    checker (mirrors ``write_gate.load_descriptor_set``'s own fail-safe
    discipline, though this module deliberately does not import that runtime
    module — it reads the same file independently so this checker has no
    dependency on the write-gate's own import surface).

    (xvendor Fix B) EXISTING-but-unreadable/malformed is NOT the same as
    absent, and must not silently collapse to the empty set: doing so would
    DROP a descriptor-only capability_id (one enumerated ONLY via this file,
    with no source file on disk) from ``check_capabilities``'s result
    entirely — a false all-clear for exactly the capability this checker
    exists to catch. So this function RAISES ``_DescriptorEnumerationError``
    when the file exists but cannot be read (``OSError`` other than
    ``FileNotFoundError``), is not valid JSON, or is not a JSON array;
    ``check_capabilities`` catches that and inserts a RED sentinel record
    instead of silently under-enumerating."""
    path = project_root / DESCRIPTOR_SET_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()
    except OSError as exc:
        raise _DescriptorEnumerationError(
            f"descriptor set {path} exists but could not be read: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise _DescriptorEnumerationError(
            f"descriptor set {path} exists but is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise _DescriptorEnumerationError(
            f"descriptor set {path} exists but is not a JSON array")
    ids: Set[str] = set()
    for entry in data:
        if isinstance(entry, dict):
            cap_id = entry.get("id")
            if isinstance(cap_id, str) and cap_id:
                ids.add(cap_id)
    return ids


def _capability_source_files(project_root: Path) -> Dict[str, Path]:
    """capability_id -> source file path, for every
    ``agents/capabilities/<capability_id>_capability.py`` on disk. Fail-safe:
    an absent capabilities directory yields the empty dict."""
    cap_dir = project_root / CAPABILITIES_DIR_REL
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


def _is_paused(project_root: Path, capability_id: str) -> Tuple[bool, bool]:
    """Returns ``(paused, read_error)``. ``paused`` is True iff an
    upgrade-reconcile safe-pause marker exists for ``capability_id`` —
    either the bare ``.pause`` sentinel or the ``.json`` pause-state record
    (either one existing is sufficient; this module does not need to parse
    the JSON to know the mechanism is paused). ``read_error`` is True iff a
    marker path EXISTS but could not be positively verified as a normal
    paused/absent signal (e.g. permission-denied, or a ``.json`` path of the
    wrong shape) — a case that must NOT be silently treated as "not paused":

    (xvendor Fix B) the prior implementation used ``Path.is_file()``, which
    INTERNALLY SWALLOWS ``PermissionError``/``OSError`` and returns ``False``
    on any stat failure — indistinguishable from a genuinely-absent marker,
    so an existing-but-unreadable pause marker silently read as "not paused"
    (fail-OPEN). This stat-based check distinguishes the two:
    ``FileNotFoundError`` is the only genuinely-absent signal (fine, not an
    error); any other ``OSError`` sets ``read_error`` and the caller
    (``check_capabilities``) folds it into the RED verdict rather than
    guessing "not paused".

    (xvendor round-2, R2-3) SHAPE handling differs by suffix, and is itself
    fail-closed:
      * ``.pause`` — this module's own writer (``upgrade_reconcile.
        _safe_pause_entrypoint`` / ``_write_paused_live_write_state``) always
        creates it as an empty REGULAR file, but the entrypoint wrapper this
        marker gates checks for it with a plain shell ``[ -e ... ]`` test —
        which pauses on ANY existing path, regardless of shape. So ANY
        existing ``.pause`` path — regular file, directory, or anything
        else — is treated as a positive pause signal here too, matching the
        wrapper's own check exactly. The prior ``stat.S_ISREG``-only gate
        silently read a ``.pause`` marker that existed as a directory (the
        wrong shape — never legitimately written that way) as "not paused":
        a false green for a capability the wrapper itself would refuse to
        run.
      * ``.json`` — this is a STATE RECORD this module (and write_gate's
        runtime deny-branch) actually parses; an existing path of the wrong
        shape (not a regular file) is not a genuine pause-state record and
        not a genuinely-absent marker either — it is unreadable/malformed
        state, so it is folded into ``read_error`` (forces RED) rather than
        silently treated as absent."""
    paused_dir = project_root / PAUSED_MECHANISMS_DIR_REL
    read_error = False
    for suffix in (".pause", ".json"):
        marker = paused_dir / f"{capability_id}{suffix}"
        try:
            st = os.stat(str(marker))
        except FileNotFoundError:
            continue
        except OSError:
            read_error = True
            continue
        if suffix == ".pause":
            # Any EXISTING path counts as paused, regardless of shape (see
            # docstring) — mirrors the wrapper's own `[ -e ]` check.
            return True, read_error
        if stat.S_ISREG(st.st_mode):
            return True, read_error
        # ".json" of the wrong shape: existing but not a genuine state
        # record — force red via read_error, never silently "not paused".
        read_error = True
    return False, read_error


def _is_pending_migration(project_root: Path, capability_id: str) -> Tuple[bool, bool]:
    """Returns ``(pending, read_error)``. ``pending`` is True iff
    ``agents/handoffs/pending_migrations.json`` carries an entry whose
    ``mechanism_id`` (or, defensively, ``capability_id``) equals
    ``capability_id``. An ABSENT queue file is a normal, non-error input:
    reads as ``(False, False)`` — nothing has ever been queued.

    (xvendor Fix B) an EXISTING queue file that is unreadable or malformed
    is NOT the same as absent, and must not silently collapse to "not
    pending" (fail-OPEN — the prior implementation folded both cases into a
    bare ``False``, and this field feeds directly into the RED/GREEN
    verdict). Such a file returns ``read_error=True``; the caller
    (``check_capabilities``) folds that into the RED verdict rather than
    guessing "no pending migration". This is best-effort enrichment on top
    of the entrypoint-level safe-pause (``_is_paused``), not the sole gate,
    but a read failure here must never present as a clean bill of health."""
    path = project_root / MIGRATION_QUEUE_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, False
    except OSError:
        return False, True
    try:
        data = json.loads(text)
    except ValueError:
        return False, True
    if not isinstance(data, list):
        return False, True
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("mechanism_id") == capability_id or entry.get("capability_id") == capability_id:
            return True, False
    return False, False


def _scan_source(cap_path: Path) -> List[scan.Violation]:
    """Run the Task-5 AST bypass scanner against exactly this one capability
    file. Fail-safe: any unexpected exception from the scanner itself (not
    expected in normal operation — ``scan_paths`` already handles unparseable
    / unreadable source internally) is treated as a violation, not a crash
    and not a silent clean pass."""
    try:
        return scan.scan_paths([cap_path])
    except Exception as exc:  # noqa: BLE001 - fail-closed, never let this crash the checker
        return [scan.Violation(path=str(cap_path), lineno=0, kind=f"scan_error:{exc}")]


def _attempt_isolated_import(cap_path: Path, project_root: Path) -> bool:
    """Attempt to import ``cap_path`` in an ISOLATED SUBPROCESS. Returns True
    iff the import completed with no error. Never called for a capability
    whose static scan was not clean — see ``check_capabilities``.

    Isolation: a fresh ``sys.executable -c`` process, never this one — a
    broken or merely unexpected capability module can raise, exit, hang, or
    otherwise misbehave without ever touching this process's own state.
    Bounded by ``IMPORT_TIMEOUT_SECONDS`` so a hang cannot hang this checker
    either. ``cwd`` is the project root (capability modules are written
    assuming they run from there) and ``PYTHONPATH`` is set to the project's
    own ``agents/lib`` (capability modules import ``external_write.*``,
    which lives at ``agents/lib/external_write/``)."""
    agents_lib = str((project_root / "agents" / "lib").resolve())
    env = dict(os.environ)
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        agents_lib + os.pathsep + existing_path if existing_path else agents_lib
    )
    program = _IMPORT_HARNESS.format(path=str(cap_path.resolve()))
    try:
        result = subprocess.run(
            [sys.executable, "-c", program],
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        # Could not even launch/finish the probe (missing interpreter, a
        # timeout, ...) -- fail-safe: not importable, never a crash.
        return False
    return result.returncode == 0


def check_capabilities(project_root: Any) -> List[Dict[str, Any]]:
    """Return one composite health record per capability found under
    `project_root`, enumerated from the UNION of the descriptor set
    (``security/capability_descriptors.json``) and the source files on disk
    (``agents/capabilities/*_capability.py``) — see the module docstring's
    "Enumeration" section.

    Each record:
      ``{"capability_id": str, "importable": bool, "scanner_clean": bool,
        "violations": List[str], "paused": bool, "pending_migration": bool,
        "state_read_error": bool, "health": "green" | "red"}``

    ``health == "red"`` iff (NOT importable) OR (NOT scanner_clean) OR paused
    OR pending_migration OR state_read_error; else ``"green"``.

    ``state_read_error`` (xvendor Fix B) is True iff the pause-marker state
    and/or the migration queue EXISTS but could not be positively read for
    this capability (see ``_is_paused`` / ``_is_pending_migration``) — an
    unreadable state is never silently treated as "not paused"/"not
    pending"; it forces RED exactly like a confirmed pause would.

    AST-FIRST, IMPORT-SECOND (safety ordering, not an optimization): a
    capability is only ever handed to the isolated-subprocess import attempt
    if its static scan came back clean. A scanner-RED capability is marked
    red immediately, with `importable` fixed at False, and is NEVER imported
    -- see the module docstring's "AST-first, import-second" section for why.

    A capability_id present ONLY in the descriptor set (no matching source
    file on disk) is reported red -- there is nothing on disk to positively
    verify `importable`/`scanner_clean` against, and this module never
    guesses a capability healthy in the absence of evidence (fail-closed,
    same direction as every other disclosed-bound convention in this
    package).

    DESCRIPTOR-ENUMERATION DEGRADATION (xvendor Fix B): if the descriptor set
    file itself exists but could not be read/parsed, this function does NOT
    silently enumerate only the capabilities it could still find on disk --
    that would drop a descriptor-only capability_id from the result with no
    signal at all (a false all-clear). Instead it inserts ONE additional
    sentinel record, keyed ``SENTINEL_DESCRIPTOR_ENUMERATION_ERROR_ID``, with
    ``health: "red"``, alongside every capability_id it could still enumerate
    from source files on disk.

    Deterministic, ordered by capability_id (the sentinel record, when
    present, is inserted first). Never raises: every disk read this function
    performs is individually fail-safe or funneled through the sentinel
    above (see the private helpers above); a missing project_root, missing
    descriptor set, missing capabilities directory, and missing
    paused/migration files are all ordinary, silently-tolerated inputs, not
    error conditions -- only an EXISTING-but-unreadable/malformed file
    triggers ``state_read_error`` or the sentinel record.
    """
    root = Path(project_root)
    descriptor_enumeration_degraded = False
    try:
        descriptor_ids = _load_descriptor_ids(root)
    except _DescriptorEnumerationError:
        descriptor_ids = set()
        descriptor_enumeration_degraded = True
    source_files = _capability_source_files(root)

    # F-61 (Task A3): resolve each descriptor-only id to its OWNING module via the capability
    # identity index BEFORE the same-named-file check below. A capability whose module stem
    # differs from its descriptor id (the estate split: descriptor id "inbox-labels", module
    # stem "inbox_management") previously had no source file under its own exact name and was
    # reported red for "no source file to scan or import against" -- even though a healthy,
    # importable module for it exists on disk under a different name. A descriptor id that
    # already matches a module stem directly is left alone; one that cannot be resolved to
    # exactly one canonical (unresolved -- a genuinely orphaned descriptor entry -- or
    # ambiguous) is also left as its own raw id, unchanged fail-closed behavior (see
    # TestDescriptorOnlyCapabilityWithNoSourceFile / TestPathConstantsAntiDrift below).
    identity_index = build_capability_index(str(root))
    resolved_descriptor_ids: Set[str] = set()
    for d_id in descriptor_ids:
        if d_id in source_files:
            resolved_descriptor_ids.add(d_id)
            continue
        try:
            identity = identity_index.resolve(d_id, "descriptor_id")
        except IdentityResolutionError:
            resolved_descriptor_ids.add(d_id)
            continue
        resolved_descriptor_ids.add(identity.canonical_id)

    all_ids = sorted(resolved_descriptor_ids | set(source_files))

    records: List[Dict[str, Any]] = []
    if descriptor_enumeration_degraded:
        records.append({
            "capability_id": SENTINEL_DESCRIPTOR_ENUMERATION_ERROR_ID,
            "importable": False,
            "scanner_clean": False,
            "violations": [],
            "paused": False,
            "pending_migration": False,
            "state_read_error": True,
            "health": "red",
        })

    for cap_id in all_ids:
        cap_path = source_files.get(cap_id)
        paused, paused_read_error = _is_paused(root, cap_id)
        pending_migration, migration_read_error = _is_pending_migration(root, cap_id)
        state_read_error = paused_read_error or migration_read_error

        if cap_path is None:
            # Declared but no source file to scan or import against.
            importable = False
            scanner_clean = False
            violations: List[str] = []
        else:
            found = _scan_source(cap_path)
            scanner_clean = not found
            violations = [f"{v.kind}:{v.lineno}" for v in found]
            if scanner_clean:
                importable = _attempt_isolated_import(cap_path, root)
            else:
                # Scanner-RED -- never import (see module docstring).
                importable = False

        health = (
            "red"
            if (not importable) or (not scanner_clean) or paused or pending_migration
               or state_read_error
            else "green"
        )

        records.append({
            "capability_id": cap_id,
            "importable": importable,
            "scanner_clean": scanner_clean,
            "violations": violations,
            "paused": paused,
            "pending_migration": pending_migration,
            "state_read_error": state_read_error,
            "health": health,
        })

    return records


# ---------------------------------------------------------------------------
# CLI entrypoint -- an agent's orientation step (T5) reads this composite
# status to decide whether to invite the operator into a capability; this
# lets it be checked ad hoc from a shell too. Exits 0 regardless of findings
# (this is a REPORT, not a gate the process itself enforces) -- prints one
# JSON array to stdout.
#
# Usage:
#   python3 agents/lib/external_write/capability_health.py [<project_root>]
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    _root = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(check_capabilities(_root), indent=2, sort_keys=True))
