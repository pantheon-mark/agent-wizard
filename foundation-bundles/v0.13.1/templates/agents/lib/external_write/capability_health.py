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
    ``agents/handoffs/pending_migrations.json``.
Otherwise health is GREEN. There is no third state: a capability this module
cannot positively verify clean, importable, unpaused, AND unqueued is RED —
fail-closed, mirroring every other disclosed-bound convention in this package
(``write_gate.load_descriptor_set``'s "any missing input ... returns []", not
a raise and not a silent permissive default).

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
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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


# ---------------------------------------------------------------------------
# Project-root-relative locations this module reads. Every one of these is
# duplicated-by-value from its own canonical owner (never imported across the
# build/runtime boundary — this module is emitted runtime code, the owners
# below are build-side or sibling-runtime modules with their own value-pinned
# cross-tests) — same discipline write_gate.py's PAUSED_MECHANISMS_DIR uses
# against upgrade_reconcile.py's PAUSED_MECHANISMS_DIR_REL.
# ---------------------------------------------------------------------------

CAPABILITIES_DIR_REL = "agents/capabilities"
CAPABILITY_FILE_SUFFIX = "_capability.py"
DESCRIPTOR_SET_REL = "security/capability_descriptors.json"
PAUSED_MECHANISMS_DIR_REL = ".wizard/paused-mechanisms"
MIGRATION_QUEUE_REL = "agents/handoffs/pending_migrations.json"

# Bounded so a hung/broken capability import can never hang this checker.
IMPORT_TIMEOUT_SECONDS = 20

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
    """The set of capability_ids declared in the descriptor set. Fail-safe:
    an absent/unreadable/malformed descriptor set yields the empty set —
    never raises, never crashes the checker (mirrors
    ``write_gate.load_descriptor_set``'s own fail-safe discipline, though
    this module deliberately does not import that runtime module — it reads
    the same file independently so this checker has no dependency on the
    write-gate's own import surface)."""
    path = project_root / DESCRIPTOR_SET_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, list):
        return set()
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


def _is_paused(project_root: Path, capability_id: str) -> bool:
    """True iff an upgrade-reconcile safe-pause marker exists for
    ``capability_id`` — either the bare ``.pause`` sentinel or the ``.json``
    pause-state record (either one existing is sufficient; this module does
    not need to parse the JSON to know the mechanism is paused). Fail-safe:
    any filesystem error reading the paused-mechanisms directory is treated
    as "not paused" for that check, never a crash."""
    paused_dir = project_root / PAUSED_MECHANISMS_DIR_REL
    for suffix in (".pause", ".json"):
        try:
            if (paused_dir / f"{capability_id}{suffix}").is_file():
                return True
        except OSError:
            continue
    return False


def _is_pending_migration(project_root: Path, capability_id: str) -> bool:
    """True iff ``agents/handoffs/pending_migrations.json`` carries an entry
    whose ``mechanism_id`` (or, defensively, ``capability_id``) equals
    ``capability_id``. Fail-safe: an absent/unreadable/malformed queue file
    reads as "no pending migration" — never a crash, never a permissive
    guess in the other direction that would matter (a genuinely queued
    migration that could not be READ here still leaves the entrypoint-level
    safe-pause, if any, as the operative signal; this field is best-effort
    enrichment, not the sole gate)."""
    path = project_root / MIGRATION_QUEUE_REL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, list):
        return False
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if entry.get("mechanism_id") == capability_id or entry.get("capability_id") == capability_id:
            return True
    return False


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
        "health": "green" | "red"}``

    ``health == "red"`` iff (NOT importable) OR (NOT scanner_clean) OR paused
    OR pending_migration; else ``"green"``.

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

    Deterministic, ordered by capability_id. Never raises: every disk read
    this function performs is individually fail-safe (see the private
    helpers above); a missing project_root, missing descriptor set, missing
    capabilities directory, and missing paused/migration files are all
    ordinary, silently-tolerated inputs, not error conditions.
    """
    root = Path(project_root)
    descriptor_ids = _load_descriptor_ids(root)
    source_files = _capability_source_files(root)
    all_ids = sorted(descriptor_ids | set(source_files))

    records: List[Dict[str, Any]] = []
    for cap_id in all_ids:
        cap_path = source_files.get(cap_id)
        paused = _is_paused(root, cap_id)
        pending_migration = _is_pending_migration(root, cap_id)

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
            else "green"
        )

        records.append({
            "capability_id": cap_id,
            "importable": importable,
            "scanner_clean": scanner_clean,
            "violations": violations,
            "paused": paused,
            "pending_migration": pending_migration,
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
