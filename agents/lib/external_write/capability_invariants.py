"""AWB-authored deterministic capability-invariant battery (Task D1-1, Phase 3
Cut 1 -- D-Layer-1, self-QA cluster D).

Why this exists
----------------
Cluster D gives the operator's own project a self-QA layer -- the operator
("Jacob") has no external cross-vendor reviewer the way this Build project
does. D-Layer-1 is the RELIABLE, DETERMINISTIC half of that self-QA: plain
Python checks for the exact structural failure class this project has already
seen break in the field (a capability quietly wired to the raw write
primitive; a descriptor drifting out of sync with the code it describes; an
op_kind nobody registered a contract for). These checks are AWB-authored, not
agent-authored -- no LLM judgment is involved in computing them -- and they
run in ``next-phase.md``'s Step 4 (technical verification), before Step 5
(the supervised trial), so a structurally broken capability never reaches a
live trial. D1-3 wires the stop; this module only computes the verdict.

Every one of the five checks below REUSES an existing, already-trusted
signal rather than re-implementing it:

  1. routing            -- ``external_write.scan``'s own AST bypass scanner
                            (``scan.scan_paths``), filtered to the
                            ``raw_run_operation_reference`` violation kind --
                            the same rule ``acceptance_ceremony`` (Invariant 7)
                            and ``capability_health.py`` already lean on.
  2. test-target enum    -- ``write_gate.ISOLATED_TEST_TARGETS |
                            write_gate.LIVE_BOUNDED_TEST_TARGETS``, the SAME
                            vocabulary the write gate itself matches
                            ``declared_test_target`` against at runtime.
  3. id coherence        -- ``capability_identity.build_capability_index(...)
                            .resolve(...)`` (this package's own identity
                            resolver) feeding ``capability_identity.
                            assert_identity_coherent`` (the operate-side A2
                            four-way, surface-excluded invariant).
  4. contract registered -- ``external_write.contracts.get_contract`` against
                            the capability's own declared ``OP_KIND``, after
                            importing ``external_write.registered_adapters``
                            (the build-emitted static import list that fires
                            every shipped/added adapter's registration --
                            mirrors ``operator_acceptance.py``'s own BI-2
                            pre-check, which resolves the identical question
                            for a copy_run_proof's op_kind).
  5. audit (post-acceptance only) -- ``acceptance_ceremony._acceptance_record_
                            exists`` (Task B4/F-59), the SAME dedup check the
                            ceremony's own idempotent-backfill path uses.
                            N/A -- never a failure -- for a capability that is
                            not yet ``accepted: true``.

Fail-closed, always
--------------------
Every check that cannot be positively evaluated (a missing source file, an
unreadable descriptor set, a scan that itself raises, a capability with no
resolvable identity) is treated as a FAILURE, never a silent pass and never a
raised exception -- the same disclosed-bound discipline every other module in
this package uses. ``operator_message`` is always plain language with a
concrete next step; it never contains a Python traceback.

Zone note
---------
This module is intentionally NOT added to ``zones.SEALED_KERNEL_MODULE_PATHS``
-- like ``capability_health.py`` before it, it needs no exemption from
anything ``scan.py`` enforces (it never references ``run_operation``, the
adapter registry's internals, or a write-capable credential), so it is left
in the default, most-restrictive CAPABILITY zone and simply never trips any
of that zone's bans. See ``scan.py`` / ``zones.py`` for the full taxonomy.

Stdlib only -- this module ships into the operator's own runtime,
``agents/lib/external_write/``.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# sys.path bootstrap: mirrors every sibling module's own convention (scan.py,
# capability_health.py, lifecycle_state.py, ...) so the ``external_write.*``
# imports below resolve whether this module is imported as part of the
# package or (rarely) run/loaded standalone.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write import scan  # noqa: E402
from external_write import write_gate  # noqa: E402
from external_write.capability_identity import (  # noqa: E402
    assert_identity_coherent,
    build_capability_index,
    CAPABILITIES_DIR_REL,
    CAPABILITY_FILE_SUFFIX,
    IdentityCoherenceError,
    IdentityResolutionError,
)
from external_write.contracts import get_contract  # noqa: E402
from external_write.acceptance_ceremony import (  # noqa: E402
    _acceptance_record_exists,
    DEFAULT_AUDIT_LOG_PATH,
)
# Fires every shipped AND capability-added adapter module's module-scope
# ``register_adapter``/``register_contract`` call, exactly like
# ``operator_acceptance.py``'s own BI-2 pre-check -- see that module's
# docstring and ``registered_adapters.py``'s own "The fix" section. Without
# this import, check 4 below would refuse EVERY adapter-backed op_kind
# (correctly registered or not) merely because nothing had triggered
# registration yet in this process -- a false negative, not a true one.
import external_write.registered_adapters  # noqa: E402,F401


@dataclass(frozen=True)
class InvariantResult:
    """The outcome of ``check_capability_invariants``.

    ok:               True iff every one of the five checks passed (or was
                       N/A -- see check 5).
    failures:          Plain-language failure lines, one per violated check
                       (a capability can fail more than one at once). Empty
                       iff ``ok`` is True.
    operator_message:  A single plain-language block combining every failure
                       with a concrete next step, or a short all-clear
                       message when ``ok`` is True. Never contains a Python
                       traceback.
    """

    ok: bool
    failures: List[str]
    operator_message: str


def _file_state(path: Path) -> str:
    """Classify ``path`` as ``"present"`` (a real regular file), ``"absent"``
    (genuinely does not exist), or ``"broken"`` (exists but is not a regular
    file, or exists but could not even be stat'd -- e.g. permission-denied).

    Deliberately ``os.stat``, never ``Path.is_file()``: ``is_file()``
    INTERNALLY SWALLOWS ``PermissionError``/``OSError`` and returns ``False``
    on any stat failure, making an existing-but-inaccessible file
    indistinguishable from a genuinely absent one -- the same fail-OPEN trap
    ``capability_health._is_paused`` / ``write_gate._load_paused_op_kinds``
    already correct elsewhere in this package. Here a "broken" file must
    fail this check closed, not silently read as "absent, so nothing to
    verify"."""
    try:
        st = os.stat(str(path))
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "broken"
    return "present" if stat.S_ISREG(st.st_mode) else "broken"


def _extract_op_kind_literal(source_text: str) -> Optional[str]:
    """AST-extract a capability module's own module-level ``OP_KIND =
    "<literal>"`` string assignment -- AST parse only, NEVER imported/executed
    (mirrors ``capability_identity._extract_surface``'s "AST-only, never
    import" discipline for the sibling ``SURFACE`` constant, and
    ``lifecycle_state._extract_op_kind_literal``'s identical extraction of
    this same constant for a different consumer). Module-level only
    (``tree.body``, not ``ast.walk``) -- matches the real emitted form
    (``capability_code_scaffold.py``'s ``render_capability_module`` always
    writes ``OP_KIND = "..."`` at module scope). Returns ``None`` when the
    source does not parse, cannot be read, or declares no such literal --
    fail-closed/empty-safe, never guesses.

    (DR-4 fix, mirrors ``capability_identity._extract_surface``'s xvendor R-6 fix)
    If ``OP_KIND`` is assigned MORE THAN ONCE at module level, the LAST valid
    string-literal assignment wins -- mirroring Python's own runtime
    last-assignment-wins semantics for a re-bound module-level name. Returning
    the first assignment (the prior behavior) would decouple this AST-only
    static read from what the module actually holds at runtime for a module
    that reassigns ``OP_KIND``."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return None
    op_kind: Optional[str] = None
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
                op_kind = value.value
    return op_kind


def _find_descriptor_entry(descriptor_set, aliases) -> Optional[dict]:
    """The descriptor entry (if any) whose ``id`` is one of ``aliases`` --
    mirrors ``lifecycle_state._find_descriptor_entry``'s identical lookup
    (duplicated here rather than imported: it is a three-line loop, not a
    trust-bearing primitive worth a cross-module dependency)."""
    for entry in descriptor_set:
        if isinstance(entry, dict) and entry.get("id") in aliases:
            return entry
    return None


def _build_operator_message(failures: List[str]) -> str:
    if not failures:
        return (
            "All deterministic structural checks passed for this capability: it routes "
            "through the safe write path, its declared test target is valid, its identity "
            "is coherent across the descriptor/capability/mechanism/module names, and its "
            "operation kind is registered."
        )
    lines = [
        "This capability failed one or more required structural checks and must not proceed "
        "to a live trial until every issue below is fixed:",
    ]
    lines.extend(f"  - {f}" for f in failures)
    lines.append("Fix the issue(s) above, then re-run this check before continuing.")
    return "\n".join(lines)


def check_capability_invariants(project_root: str, canonical_id: str) -> InvariantResult:
    """Run the five AWB-authored, deterministic invariant checks for the
    capability whose canonical (module-derived) id is ``canonical_id``, in
    the project rooted at ``project_root``. Never raises -- every check that
    cannot be positively evaluated is folded into ``failures`` as its own
    fail-closed line (see the module docstring). Composes existing signals
    only; this function does not re-implement the scanner, the identity
    resolver, the test-target vocabulary, the contract registry, or the
    audit-record dedup check -- see the module docstring's numbered list for
    exactly which existing primitive backs each of the five checks below.
    """
    root = Path(project_root)
    failures: List[str] = []

    cap_path = root / CAPABILITIES_DIR_REL / f"{canonical_id}{CAPABILITY_FILE_SUFFIX}"
    file_state = _file_state(cap_path)

    # --- Check 1: routing --------------------------------------------------
    if file_state != "present":
        failures.append(
            f'Routing: no readable source file was found for capability "{canonical_id}" at '
            f"{cap_path} ({file_state}). Restore or rebuild this capability's source file, then "
            "re-run this check."
        )
    else:
        try:
            scan_violations = scan.scan_paths([str(cap_path)])
        except Exception as exc:  # noqa: BLE001 - fail-closed, never let this crash the checker
            failures.append(
                f'Routing: the safety scan could not be run against capability '
                f'"{canonical_id}"\'s code ({exc}); treat it as unsafe until it can be '
                "re-checked."
            )
        else:
            if any(v.kind == "raw_run_operation_reference" for v in scan_violations):
                failures.append(
                    f'Routing: capability "{canonical_id}" still reaches the raw internal write '
                    "function directly instead of the safe, tracked write path. Have the coding "
                    "agent rebuild this capability so every live write goes through "
                    "capability_api.run_enveloped_operation, never raw run_operation."
                )

    # --- Shared: resolve this capability's identity (checks 2, 3, 5) -------
    identity = None
    identity_error_message: Optional[str] = None
    try:
        index = build_capability_index(str(root))
        identity = index.resolve(canonical_id, "module_stem")
    except IdentityResolutionError as exc:
        identity_error_message = exc.operator_message

    lookup_aliases = identity.aliases if identity is not None else frozenset({canonical_id})

    # --- Shared: load the descriptor entry (checks 2 and 5) ----------------
    descriptor_entry: Optional[dict] = None
    if write_gate.DESCRIPTOR_SET_PATH:
        descriptor_set = write_gate.load_descriptor_set(
            str(root / write_gate.DESCRIPTOR_SET_PATH)
        )
        descriptor_entry = _find_descriptor_entry(descriptor_set, lookup_aliases)

    # --- Check 2: test-target enum ------------------------------------------
    valid_test_targets = write_gate.ISOLATED_TEST_TARGETS | write_gate.LIVE_BOUNDED_TEST_TARGETS
    if descriptor_entry is None:
        failures.append(
            f'Test target: no descriptor entry could be found for capability "{canonical_id}" '
            "in security/capability_descriptors.json, so its declared test target cannot be "
            "verified. Add or repair this capability's descriptor entry, then re-run this check."
        )
    else:
        declared_target = descriptor_entry.get("declared_test_target")
        if declared_target not in valid_test_targets:
            failures.append(
                f'Test target: capability "{canonical_id}" declares declared_test_target '
                f"{declared_target!r}, which is not one of the allowed values "
                f"{sorted(valid_test_targets)}. Fix this capability's descriptor entry so "
                "declared_test_target is exactly one of those values."
            )

    # --- Check 3: id coherence (4-way, surface excluded) --------------------
    if identity is None:
        failures.append(
            f'Id coherence: capability "{canonical_id}" could not be resolved to a known '
            f"capability identity ({identity_error_message}). Fix the identity mismatch, then "
            "re-run this check."
        )
    else:
        # A namespace with no corroborating entry at all (e.g. this capability has never had a
        # pending migration) resolves to None -- that is "no evidence either way", not a
        # contradiction, so it is treated as coherent-by-default (substituted with the
        # canonical id) rather than an automatic failure. A namespace that DOES resolve to a
        # DIFFERENT string (e.g. a descriptor id wrongly set to this capability's own SURFACE,
        # corroborated back to this same canonical) is passed through verbatim, so
        # assert_identity_coherent still catches exactly that drift.
        descriptor_id = (
            identity.descriptor_id if identity.descriptor_id is not None else identity.canonical_id
        )
        mechanism_id = (
            identity.mechanism_id if identity.mechanism_id is not None else identity.canonical_id
        )
        try:
            assert_identity_coherent(
                descriptor_id, identity.canonical_id, mechanism_id, identity.module_stem
            )
        except IdentityCoherenceError as exc:
            failures.append(f"Id coherence: {exc}")

    # --- Check 4: contract registered ---------------------------------------
    if file_state != "present":
        failures.append(
            f'Contract registered: capability "{canonical_id}"\'s source file could not be read, '
            "so its operation kind and contract registration cannot be verified."
        )
    else:
        try:
            source_text = cap_path.read_text(encoding="utf-8")
        except OSError:
            source_text = None
        op_kind = _extract_op_kind_literal(source_text) if source_text is not None else None
        if op_kind is None:
            failures.append(
                f'Contract registered: capability "{canonical_id}" declares no OP_KIND constant '
                "(or its source could not be read), so its contract registration cannot be "
                'verified. Add a module-level OP_KIND = "..." constant naming its registered '
                "operation kind."
            )
        elif get_contract(op_kind) is None:
            failures.append(
                f'Contract registered: capability "{canonical_id}" declares operation kind '
                f"{op_kind!r}, which has no registered contract. Fix step: add this capability's "
                "adapter module to agents/lib/external_write/registered_adapters.py (the "
                "add-capability build cascade does this for you) so it registers at import "
                "time, then re-run this check."
            )

    # --- Check 5: audit record, post-acceptance only ------------------------
    # A capability that is not yet accepted has no acceptance to audit -- N/A, never a failure.
    if descriptor_entry is not None and descriptor_entry.get("accepted") is True:
        phase_id = descriptor_entry.get("phase_id")
        if not (isinstance(phase_id, str) and phase_id):
            failures.append(
                f'Audit record: capability "{canonical_id}" is marked accepted, but its '
                "descriptor entry carries no phase_id, so its acceptance audit record cannot be "
                "verified. Repair this capability's descriptor entry's phase_id, then re-run "
                "this check."
            )
        else:
            audit_log_path = str(root / DEFAULT_AUDIT_LOG_PATH)
            if not _acceptance_record_exists(audit_log_path, canonical_id, phase_id):
                failures.append(
                    f'Audit record: capability "{canonical_id}" is marked accepted for phase '
                    f'"{phase_id}", but no matching acceptance audit record was found in '
                    f"{DEFAULT_AUDIT_LOG_PATH}. This capability's acceptance cannot be verified "
                    "from the audit trail; treat it as unaccepted until the audit trail is "
                    "repaired."
                )

    ok = not failures
    return InvariantResult(ok=ok, failures=failures, operator_message=_build_operator_message(failures))


# =============================================================================
# Task D1-2: deterministic test-quality probes (right-sized)
# =============================================================================
#
# Why this exists (the SB-8 lesson)
# ----------------------------------
# D1-1 above proves the capability's OWN code is structurally sound. It says
# nothing about whether the TEST that is supposed to guard that code actually
# guards anything. During the 2026-07-16 STEP B dogfood, AWB itself produced a
# false verdict by hand-building an ``Operation`` and driving it through a real
# gate function instead of the real capability -- a hand-built stand-in proved
# nothing about the real system (the lesson: verify an emitted consumer via the
# producer's real entrypoint, not a hand-built stand-in). An
# agent-authored capability test can make the exact same mistake: define its
# own fake ``Operation``/adapter/plan and drive THAT instead of the real
# capability module and its real acceptance/gate entrypoint, and the test
# suite will happily stay green forever no matter what the real code does.
#
# ``check_test_quality`` adds two RIGHT-SIZED, deterministic probes on top of
# D1-1 (per the 2026-07-17 design consult's right-sizing calibration -- full
# mutation-style per-branch checks are heavier and partly redundant with the
# D1-1 invariants, and are deliberately deferred, not built here):
#
#   1. producer-entrypoint (AST, static) -- does this capability's own test
#      file actually reference the REAL capability module and the REAL
#      acceptance/gate entrypoint (``run_enveloped_operation`` /
#      ``operator_acceptance``), and does it avoid defining its own
#      hand-built ``Operation``/adapter/plan stand-in?
#   2. known-bad-fails (dynamic, bounded) -- does running this capability's
#      own test file(s) against a DELIBERATELY BROKEN copy of its own
#      implementation actually produce a failure? If the suite stays green
#      even when the implementation is broken, the suite is inert and proves
#      nothing -- exactly the SB-8 failure class, just caught mechanically
#      instead of relying on a reviewer's judgment.
#
# Detection heuristic + its limits (producer-entrypoint, AST-only)
# -------------------------------------------------------------------
# There is no established naming/location convention anywhere in this project
# for a capability's own test file (``add-capability.md`` hands test-writing
# to the builder agent with no fixed path). So this module does not assume
# one either: ``_discover_capability_test_files`` walks the WHOLE project
# tree for ``test_*.py`` / ``*_test.py`` files and keeps only the ones whose
# AST imports reference this capability's own module
# (``<canonical_id>_capability``) -- the same "search the filesystem, do not
# assume a fixed path" discipline ``capability_identity._capability_source_files``
# already uses for capability modules themselves.
#
# For each discovered test file, this module then checks, by AST only (never
# by importing the test file):
#   * does it reference the real acceptance/gate entrypoint -- a real CALL to
#     ``run_enveloped_operation`` (the sanctioned live-write entrypoint,
#     ``external_write.capability_api`` / ``external_write.run_envelope``),
#     bare or via attribute access (DR-2 fix: an import alone, never called,
#     is no longer sufficient -- see ``_ast_references_entrypoint``'s own
#     docstring), or an import/module-reference of ``operator_acceptance``
#     (the acceptance CLI -- import-only stays sufficient there; it is invoked
#     as a subprocess, not called in-process)?
#   * does it define its own class whose name IS (exactly, case-insensitive)
#     an optional fake/stub/mock/dummy affix plus ``Operation``/``Adapter``/
#     ``Plan`` (e.g. ``Operation``, ``FakeOperation``, ``StubAdapter``,
#     ``PlanFake``) -- a locally-defined stand-in for the real producer,
#     exactly the SB-8 shape?
#
# LIMITS (stated per this task's instruction to surface heuristic ambiguity):
#   * This is a NAME-based heuristic, not a data-flow analysis. (DR-2 fix) A
#     test that only IMPORTS the real entrypoint but never actually calls it
#     anywhere is now correctly FLAGGED by this probe itself, not left to
#     probe 2 (known-bad-fails) to catch indirectly. The heuristic still
#     cannot tell whether a real ``ast.Call`` to the entrypoint is reached at
#     runtime (a call inside dead/unreachable code, or one whose arguments are
#     wrong, still satisfies this AST-only check) -- that residual is exactly
#     what probe 2 remains for.
#   * A legitimately-named test helper class that happens to match the
#     stand-in name pattern (e.g. a fixture class a project deliberately
#     calls ``FakeAdapter`` to build a REAL ``Operation`` from, or a subclass
#     of the real ``Operation`` used only to add test-fixture convenience)
#     is flagged as a false positive. The pattern is anchored to the WHOLE
#     class name (not a substring match) specifically to avoid flagging
#     ordinary test-case class names like ``TestOperationRouting`` -- but it
#     cannot distinguish "renamed-but-still-real" from "genuinely fake."
#   * A test file that cannot be read or parsed at all is silently excluded
#     from discovery (there is no way to check whether an unparsable file
#     references this capability without parsing it) -- this is a known gap,
#     not a designed coverage guarantee; a capability with ONLY a broken test
#     file looks, to this probe, like a capability with NO test file (which
#     is itself a failure -- see the "no test file found" branch below), so
#     it is not silently treated as passing.
#
# Isolation + boundedness (known-bad-fails)
# --------------------------------------------
# The deliberately-broken copy is built and run entirely inside a fresh
# ``tempfile.mkdtemp()`` directory -- the operator's real project tree is
# NEVER written to. Exactly ONE mutation is made: every function/method body
# (module-level or nested, via AST) in THIS capability's own module (and only
# this module -- not the paired adapter module, not any shared library code)
# is replaced with ``raise RuntimeError(...)``, preserving every signature and
# decorator so the module still parses and imports cleanly -- only CALLING
# into it now fails. This is a single mechanical "blunt break," not
# per-branch/per-line mutation testing (explicitly deferred -- see the module
# docstring's cross-reference to the design consult). The capability's own
# discovered test file(s) are then run, ONE bounded ``unittest discover``
# subprocess per file (scoped to exactly that file via ``-p <its basename>``),
# each under a timeout, against the broken copy only. The temp directory is
# removed in a ``finally`` block regardless of outcome. If EVERY discovered
# test file reports a failure/error against the broken copy, the probe
# passes; if ANY of them still reports a clean pass, that test file is
# treated as inert and the probe fails (fail-closed, plain language, no
# traceback) -- see ``_check_known_bad_fails``.
# =============================================================================

_TEST_DISCOVERY_SKIP_DIR_NAMES = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".hg", ".svn", ".tox",
}

# The two names that mark a REAL producer-entrypoint reference: the sanctioned
# live-write entrypoint capability code is meant to call, and the acceptance
# CLI's own module name (imported by name or invoked as a module).
_ENTRYPOINT_IMPORT_NAMES = frozenset({"run_enveloped_operation"})
_ACCEPTANCE_CLI_MODULE_NAME = "operator_acceptance"

# Matches a locally-defined class name that IS (whole-string, case-insensitive)
# an optional fake/stub/mock/dummy affix plus Operation/Adapter/Plan -- e.g.
# "Operation", "FakeOperation", "StubAdapter", "PlanFake". Anchored to the
# WHOLE name (not a substring search) so an ordinary test-case class name like
# "TestOperationRouting" does not match -- see the module docstring's LIMITS
# note for the false-positive/false-negative this heuristic still carries.
_STANDIN_CLASS_NAME_RE = re.compile(
    r"(?i)^(fake|stub|mock|dummy)?(operation|adapter|plan)(fake|stub|mock|dummy)?$"
)

_KNOWN_BAD_FAILS_TIMEOUT_SECONDS = 90
_MUTATION_EXCEPTION_MESSAGE = "mutated-for-known-bad-fails-probe"
_KNOWN_BAD_COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", ".venv", "venv", "node_modules"
)


def _capability_module_name(canonical_id: str) -> str:
    """The importable module name for this capability's own source file --
    ``<canonical_id>_capability`` -- derived from ``CAPABILITY_FILE_SUFFIX``
    (``"_capability.py"``) rather than re-declared as a separate literal, so
    the two can never drift apart."""
    return f"{canonical_id}{CAPABILITY_FILE_SUFFIX[:-3]}"


def _iter_candidate_test_files(root: Path):
    """Yield every ``test_*.py`` / ``*_test.py`` file under ``root``, skipping
    common non-source noise directories (see ``_TEST_DISCOVERY_SKIP_DIR_NAMES``)
    and any hidden directory. No assumption about WHERE a capability's test
    file lives -- see module docstring."""
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [
            d for d in dirnames
            if d not in _TEST_DISCOVERY_SKIP_DIR_NAMES and not d.startswith(".")
        ]
        for name in filenames:
            if name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")):
                yield Path(dirpath) / name


def _ast_references_module(tree: ast.AST, module_name: str) -> bool:
    """True iff ``tree`` contains an ``import``/``from ... import`` referencing
    a module whose last dotted segment (for ``import``/``from X import``) or
    imported name (for ``from X import name`` / ``from . import name``) equals
    ``module_name`` exactly. Covers every realistic import shape (absolute,
    dotted-package, relative) without assuming any one of them."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == module_name:
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[-1] == module_name:
                return True
            for alias in node.names:
                if alias.name == module_name:
                    return True
    return False


def _ast_references_entrypoint(tree: ast.AST) -> bool:
    """True iff ``tree`` genuinely CALLS the real live-write entrypoint
    (``run_enveloped_operation``) or imports/references the ``operator_acceptance``
    module (the acceptance CLI -- import/module-reference alone stays sufficient
    there; see the DR-2 decision note below).

    (DR-2 fix) An IMPORT of ``run_enveloped_operation`` alone, never called, used
    to satisfy this probe -- that only proves the test file NAMES the real
    entrypoint, not that any test method actually EXERCISES it (probe 2,
    known-bad-fails, is what would have caught an import-only test's inertness,
    but a test author should not have to rely on that second probe to get an
    honest producer-entrypoint verdict). This now requires a real ``ast.Call``
    reaching the entrypoint, in EITHER shape:
      * ``from ... import run_enveloped_operation`` (optionally ``as X``) then a
        bare ``run_enveloped_operation(...)`` / ``X(...)`` call, or
      * a module import (``import external_write.capability_api`` or similar)
        then an attribute-access call ending in ``....run_enveloped_operation(...)``
        (e.g. ``capability_api.run_enveloped_operation(...)`` or
        ``external_write.capability_api.run_enveloped_operation(...)``) -- matched
        on the trailing attribute name alone, not on which module it was
        imported from, mirroring this module's other AST-only, name-based probes.

    DECISION (per this task's own "if unsure" default): the acceptance-CLI path
    is deliberately left as import/module-reference-only, NOT also requiring a
    call -- ``operator_acceptance`` is invoked as a CLI subprocess (``python -m
    operator_acceptance ...``), not called as an in-process Python function, so
    there is no ``ast.Call`` node to require in the first place; naming the
    module remains the right-sized evidence for that entrypoint."""
    call_names = set(_ENTRYPOINT_IMPORT_NAMES)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_parts = (node.module or "").split(".")
            if _ACCEPTANCE_CLI_MODULE_NAME in module_parts:
                return True
            for alias in node.names:
                if alias.name in _ENTRYPOINT_IMPORT_NAMES:
                    call_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _ACCEPTANCE_CLI_MODULE_NAME in alias.name.split("."):
                    return True

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in call_names:
            return True
        if isinstance(func, ast.Attribute) and func.attr in _ENTRYPOINT_IMPORT_NAMES:
            return True
    return False


def _ast_standin_class_names(tree: ast.AST) -> List[str]:
    """Every locally-defined class name in ``tree`` matching
    ``_STANDIN_CLASS_NAME_RE`` -- see that pattern's own docstring for exactly
    what it matches and its known false-positive/false-negative limits."""
    return sorted({
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _STANDIN_CLASS_NAME_RE.match(node.name)
    })


def _discover_capability_test_files(root: Path, module_name: str) -> List[Path]:
    """Every test file under ``root`` whose AST imports reference
    ``module_name`` -- i.e. every test file that is ABOUT this capability, by
    evidence (an import), never by assumed path/naming convention. A file
    that cannot be read or parsed is silently excluded (see module docstring
    LIMITS note) rather than raising."""
    matches: List[Path] = []
    for path in _iter_candidate_test_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        if _ast_references_module(tree, module_name):
            matches.append(path)
    return sorted(matches)


class _RaiseEveryFunctionBody(ast.NodeTransformer):
    """AST transformer: replaces every function/method body (module-level or
    nested) with a single ``raise RuntimeError(<marker>)`` statement, leaving
    the signature and decorators untouched -- the module still parses and
    imports cleanly; only CALLING into any of its functions now fails. One
    blunt, mechanical mutation of the whole module -- not per-branch mutation
    testing (see module docstring)."""

    def _raise_body(self, node):
        node.body = [
            ast.Raise(
                exc=ast.Call(
                    func=ast.Name(id="RuntimeError", ctx=ast.Load()),
                    args=[ast.Constant(value=_MUTATION_EXCEPTION_MESSAGE)],
                    keywords=[],
                ),
                cause=None,
            )
        ]
        return node

    def visit_FunctionDef(self, node):  # noqa: N802 - ast.NodeTransformer visitor naming
        return self._raise_body(node)

    def visit_AsyncFunctionDef(self, node):  # noqa: N802
        return self._raise_body(node)


def _mutate_to_known_bad(source: str) -> Optional[str]:
    """Return ``source`` with every function/method body replaced by a raise
    (see ``_RaiseEveryFunctionBody``), or ``None`` if ``source`` cannot be
    parsed/unparsed -- fail-closed, never raises."""
    if not hasattr(ast, "unparse"):  # pragma: no cover - this project requires Python 3.11+
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    mutated = _RaiseEveryFunctionBody().visit(tree)
    ast.fix_missing_locations(mutated)
    try:
        return ast.unparse(mutated)
    except Exception:  # noqa: BLE001 - fail-closed, never let this crash the checker
        return None


def _run_discover(python_exe: str, cwd: Path, test_file: Path, env: dict) -> Optional[bool]:
    """Run ONE test file's suite via ``python -m unittest discover``, scoped to
    exactly that file (``-s <its directory>``, ``-p <its exact basename>``) so
    unrelated tests elsewhere in the (copied) tree are never pulled in. Returns
    True if the run reported a failure/error (non-zero exit -- what a suite
    that actually caught the deliberate break SHOULD do), False if it exited
    clean, or None if the run could not be completed at all (timeout / launch
    failure) -- the caller folds ``None`` into a fail-closed failure line,
    never a silent pass."""
    try:
        result = subprocess.run(
            [python_exe, "-m", "unittest", "discover",
             "-s", str(test_file.parent), "-p", test_file.name],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=_KNOWN_BAD_FAILS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode != 0


def _purge_pycache(root: Path) -> None:
    """Remove every ``__pycache__`` directory under ``root``. Called between
    the baseline run and the mutated run so a compiled ``.pyc`` cached from
    the baseline run can never mask the source change made for the mutated
    run (belt-and-braces -- CPython's own mtime/hash pyc invalidation should
    already catch this, but this makes it certain, not merely likely)."""
    for dirpath, dirnames, _filenames in os.walk(str(root)):
        if "__pycache__" in dirnames:
            shutil.rmtree(Path(dirpath) / "__pycache__", ignore_errors=True)
            dirnames.remove("__pycache__")


def _check_known_bad_fails(root: Path, canonical_id: str, cap_path: Path,
                            test_files: List[Path]) -> Optional[str]:
    """The known-bad-fails probe: copy the project into an ISOLATED temp
    directory (never touching the operator's real files), then run this
    capability's own discovered test file(s) TWICE against that copy.

    (Review finding fix) A bare ``exit code != 0`` check is NOT evidence a
    suite "caught" anything -- an UNRELATED crash (a missing import, a suite
    that never actually runs) also exits non-zero, and would otherwise be
    scored exactly the same as a real, deliberate failure. So this now runs
    the suite against the UNMUTATED copy first and requires it to be fully
    green BEFORE ever looking at the mutated run:

      (a) BASELINE -- every discovered test file MUST pass cleanly (exit 0)
          against the copy's UNMUTATED implementation. If even one does not
          -- a genuine failing assertion, an unrelated crash, an import
          error, or a suite that never actually runs -- this capability's
          own tests cannot be trusted to catch anything, and the probe
          fails WITHOUT ever running the mutated copy (a suite that cannot
          even run cleanly on its own proves nothing about whether it would
          catch a real break).
      (b) MUTATED -- only once (a) is fully green, this capability's OWN
          module (and only this module) is overwritten, in the SAME copy,
          with every function/method body replaced by a raise (see
          ``_RaiseEveryFunctionBody``), and every discovered test file is
          run again. Every one of them MUST now fail; any that still passes
          is inert.

    The probe passes only when (a) is entirely green AND (b) is entirely
    red. Returns a plain-language failure line, or ``None`` if the probe
    passed. Always cleans up the temp directory, even on error -- see module
    docstring for the full isolation and boundedness contract."""
    try:
        original_source = cap_path.read_text(encoding="utf-8")
    except OSError:
        return (
            f'Known-bad-fails: capability "{canonical_id}"\'s source could not be read, so a '
            "deliberately-broken copy could not be built and its test suite's effectiveness "
            "cannot be verified."
        )

    mutated_source = _mutate_to_known_bad(original_source)
    if mutated_source is None:
        return (
            f'Known-bad-fails: capability "{canonical_id}"\'s source could not be parsed to build '
            "a deliberately-broken copy, so its test suite's effectiveness cannot be verified."
        )

    tmp_dir = tempfile.mkdtemp(prefix="awb_known_bad_fails_")
    try:
        copy_root = Path(tmp_dir) / "copy"
        try:
            shutil.copytree(root, copy_root, ignore=_KNOWN_BAD_COPY_IGNORE)
        except OSError:
            return (
                f'Known-bad-fails: an isolated copy of this project could not be built to test '
                f'capability "{canonical_id}"\'s implementation against; its test suite\'s '
                "effectiveness cannot be verified."
            )

        rel_cap_path = cap_path.relative_to(root)
        rel_test_files = [tf.relative_to(root) for tf in test_files]

        env = dict(os.environ)
        agents_lib = str(copy_root / "agents" / "lib")
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = agents_lib + (
            os.pathsep + existing_pythonpath if existing_pythonpath else ""
        )

        # --- (a) Baseline: the UNMUTATED copy must be fully green ------------
        baseline_not_green: List[str] = []
        baseline_uncertain = False
        for rel_tf in rel_test_files:
            outcome = _run_discover(sys.executable, copy_root, copy_root / rel_tf, env)
            if outcome is None:
                baseline_uncertain = True
            elif outcome is True:  # True == "reported a failure" -- bad news at baseline
                baseline_not_green.append(str(rel_tf))

        if baseline_uncertain:
            return (
                f'Known-bad-fails: this capability\'s own test suite could not be run to check '
                "whether it passes cleanly on its own (before any deliberate change), so its "
                "effectiveness cannot be verified."
            )
        if baseline_not_green:
            return (
                f'Known-bad-fails: {", ".join(baseline_not_green)} does not pass cleanly as '
                "written, on its own, before any deliberate change -- either it fails, or it "
                "never actually ran at all (for example, because of a missing import). A test "
                "suite that does not pass cleanly on its own cannot be trusted to catch a real "
                "problem. Fix this capability's own tests so they pass cleanly on their own "
                "first, then re-run this check."
            )

        # --- (b) Mutated: only reached once the baseline is fully green ------
        try:
            (copy_root / rel_cap_path).write_text(mutated_source, encoding="utf-8")
        except OSError:
            return (
                f'Known-bad-fails: the deliberately-broken copy of capability "{canonical_id}"\'s '
                "module could not be written, so its test suite's effectiveness cannot be "
                "verified."
            )
        _purge_pycache(copy_root)

        inert_files: List[str] = []
        uncertain = False
        for rel_tf in rel_test_files:
            outcome = _run_discover(sys.executable, copy_root, copy_root / rel_tf, env)
            if outcome is None:
                uncertain = True
            elif outcome is False:
                inert_files.append(str(rel_tf))

        if uncertain:
            return (
                f'Known-bad-fails: running capability "{canonical_id}"\'s test suite against a '
                "deliberately broken copy of its own implementation did not finish, so its "
                "effectiveness cannot be verified."
            )
        if inert_files:
            return (
                f'Known-bad-fails: {", ".join(inert_files)} still reported all tests passing even '
                f'when capability "{canonical_id}"\'s own implementation was deliberately broken -- '
                "these tests are not actually verifying its behavior. Strengthen them to assert on "
                "real behavior, then re-run this check."
            )
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _build_test_quality_operator_message(failures: List[str]) -> str:
    if not failures:
        return (
            "This capability's own tests passed both deterministic quality probes: they exercise "
            "the real capability module and its real acceptance/gate entrypoint (not a hand-built "
            "stand-in), and they correctly fail when run against a deliberately broken copy of the "
            "implementation."
        )
    lines = [
        "This capability's tests failed one or more required quality checks and must be fixed "
        "before this capability proceeds to a live trial:",
    ]
    lines.extend(f"  - {f}" for f in failures)
    lines.append("Fix the issue(s) above, then re-run this check before continuing.")
    return "\n".join(lines)


def check_test_quality(project_root: str, canonical_id: str) -> InvariantResult:
    """Run the two AWB-authored, deterministic test-quality probes (D1-2) for
    the capability whose canonical id is ``canonical_id``, in the project
    rooted at ``project_root``. Never raises -- every input that cannot be
    positively evaluated is folded into ``failures`` as its own fail-closed
    line (see module docstring). Reuses ``CAPABILITIES_DIR_REL`` /
    ``CAPABILITY_FILE_SUFFIX`` / ``_file_state`` from D1-1 for the same
    capability-module-path derivation and fail-closed file-state
    classification -- this module does not re-derive either.
    """
    root = Path(project_root)
    failures: List[str] = []

    cap_path = root / CAPABILITIES_DIR_REL / f"{canonical_id}{CAPABILITY_FILE_SUFFIX}"
    file_state = _file_state(cap_path)
    if file_state != "present":
        failures.append(
            f'Test quality: no readable source file was found for capability "{canonical_id}" at '
            f"{cap_path} ({file_state}), so its tests cannot be verified. Restore or rebuild this "
            "capability's source file, then re-run this check."
        )
        return InvariantResult(
            ok=False, failures=failures,
            operator_message=_build_test_quality_operator_message(failures))

    module_name = _capability_module_name(canonical_id)
    test_files = _discover_capability_test_files(root, module_name)

    if not test_files:
        failures.append(
            f'Producer entrypoint: no test file anywhere in this project imports capability '
            f'"{canonical_id}"\'s own module ("{module_name}"). Add a test that imports this '
            "capability's real module and exercises its real acceptance/gate entrypoint "
            "(run_enveloped_operation / the operator-acceptance CLI), then re-run this check."
        )
        return InvariantResult(
            ok=False, failures=failures,
            operator_message=_build_test_quality_operator_message(failures))

    # --- Probe 1: producer-entrypoint (AST, static) -------------------------
    standin_hits: List[str] = []
    entrypoint_seen = False
    for tf in test_files:
        try:
            tree = ast.parse(tf.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue  # already excluded by discovery; defensive only
        rel = str(tf.relative_to(root))
        if _ast_standin_class_names(tree):
            standin_hits.append(rel)
        if _ast_references_module(tree, module_name) and _ast_references_entrypoint(tree):
            entrypoint_seen = True

    if standin_hits:
        failures.append(
            f'Producer entrypoint: {", ".join(standin_hits)} defines its own hand-built '
            f'Operation/adapter/plan stand-in instead of driving capability "{canonical_id}"\'s '
            "real module through its real run_enveloped_operation / operator-acceptance-CLI "
            "entrypoint. A test that only exercises a locally-defined fake proves nothing about "
            "the real capability. Rewrite it to exercise the real capability module and its real "
            "entrypoint, then re-run this check."
        )
    elif not entrypoint_seen:
        rels = ", ".join(str(t.relative_to(root)) for t in test_files)
        failures.append(
            f'Producer entrypoint: none of this capability\'s test file(s) ({rels}) reference both '
            f'capability "{canonical_id}"\'s own module and its real run_enveloped_operation / '
            "operator-acceptance-CLI entrypoint. Update the test(s) to import and exercise the "
            "real capability module and its real entrypoint, then re-run this check."
        )

    # --- Probe 2: known-bad-fails (dynamic, bounded, isolated) --------------
    kb_failure = _check_known_bad_fails(root, canonical_id, cap_path, test_files)
    if kb_failure is not None:
        failures.append(kb_failure)

    ok = not failures
    return InvariantResult(
        ok=ok, failures=failures,
        operator_message=_build_test_quality_operator_message(failures))


# ---------------------------------------------------------------------------
# CLI entrypoint (Task D1-3) -- the exact, copy-paste command next-phase.md's Step 4 runs, for
# ONE capability, silently, after bringing that phase's agents to a runnable state and BEFORE
# Step 5's supervised trial. Runs BOTH D-Layer-1 batteries -- this module's own D1-1 structural
# invariants (check_capability_invariants) and D1-2 test-quality probes (check_test_quality) --
# and prints each battery's own plain-language operator_message, never a Python traceback.
# Mirrors lifecycle_state.py's own CLI shape exactly: positional
# ``<project_root> <canonical_id>``, exit 0 only on a full pass across both batteries, exit 1 on
# any failure in either one, exit 1 (with a plain usage line, never a traceback) when the
# arguments are missing.
#
# Usage:
#   python3 agents/lib/external_write/capability_invariants.py <project_root> <canonical_id>
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _cli_sys

    if len(_cli_sys.argv) < 3:
        print(
            "NOT READY -- usage: python3 capability_invariants.py <project_root> <canonical_id>. "
            "No project_root/canonical_id was given, so nothing was checked."
        )
        _cli_sys.exit(1)

    _cli_root, _cli_cap_id = _cli_sys.argv[1], _cli_sys.argv[2]
    _cli_invariants = check_capability_invariants(_cli_root, _cli_cap_id)
    _cli_quality = check_test_quality(_cli_root, _cli_cap_id)
    _cli_ok = _cli_invariants.ok and _cli_quality.ok

    print("ALL CHECKS PASSED" if _cli_ok else "NOT READY")
    print(_cli_invariants.operator_message)
    print(_cli_quality.operator_message)

    _cli_sys.exit(0 if _cli_ok else 1)
