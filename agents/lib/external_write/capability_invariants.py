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

Every one of the seven checks below REUSES an existing, already-trusted
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
  6. marker residue (post-acceptance only, Task A2/F-70) -- a direct disk read
                            of ``.wizard/paused-mechanisms/<canonical_id>.{pause,
                            json}`` (the same marker ``capability_health.
                            check_capabilities_with_self_heal`` self-heals and
                            ``lifecycle_state.reconcile_state`` clears). N/A --
                            never a failure -- for a capability that is not yet
                            ``accepted: true`` (a marker on a not-yet-accepted
                            capability is the normal paused/pending-migration
                            state, not a defect). This is the emitted self-QA's
                            OWN independent catch: if reconcile-on-accept (A1)
                            or reconcile-on-read (A2) is ever bypassed, an
                            orphaned marker on an otherwise-accepted capability
                            still surfaces here as a required-fix failure,
                            rather than silently letting a structurally
                            inconsistent capability proceed to a live trial.
  7. adapter evidence predicates (Task B1, F-74) -- ``external_write.evidence.
                            REQUIRED_EVIDENCE_PREDICATES`` (the SAME canonical
                            list ``copy_run_proof.validate_copy_run_proof``
                            reads at proof/run time), checked against the
                            capability's own ``OP_KIND``'s registered
                            ``adapter_registry.get_dispatch`` result. Fires
                            ONLY when that op_kind has a REGISTERED adapter
                            (the six seeded field op_kinds have none, by
                            permanent design, and are correctly N/A here,
                            never a failure -- mirroring
                            ``copy_run_proof.py``'s identical scope note).
                            Before this check existed, a capability whose
                            adapter was missing a required evidence predicate
                            passed this self-QA and only failed mid-trial in
                            ``copy_run_proof`` -- two gates, one requirement,
                            out of sync (F-74). Reading the SAME shared
                            constant both gates consume means a predicate
                            added to that list is required by BOTH, never
                            just one of them.

Fail-closed, always
--------------------
Every check that cannot be positively evaluated (a missing source file, an
unreadable descriptor set, a scan that itself raises, a capability with no
resolvable identity) is treated as a FAILURE, never a silent pass and never a
raised exception -- the same disclosed-bound discipline every other module in
this package uses. ``operator_message`` is always plain language with a
concrete next step; it never contains a Python traceback.

Zone note (updated Task B1, F-74 -- Cut 1.1 Cluster B)
-------------------------------------------------------
Before Task B1, this module was intentionally NOT added to
``zones.SEALED_KERNEL_MODULE_PATHS`` -- like ``capability_health.py``, it
needed no exemption from anything ``scan.py`` enforces (it never referenced
``run_operation``, the adapter registry's internals, or a write-capable
credential), so it was left in the default, most-restrictive CAPABILITY
zone. Task B1's Check 7 changes that: it must READ a capability's registered
adapter's dispatch record (``adapter_registry.get_dispatch``) to verify the
adapter declares the REQUIRED evidence predicates
(``evidence.REQUIRED_EVIDENCE_PREDICATES``) -- the SAME read-only inspection
``operator_acceptance.py``/``acceptance_ceremony.py`` (both SEALED_KERNEL)
already perform legitimately for the identical reason. This module is
therefore now listed in ``zones.SEALED_KERNEL_MODULE_PATHS`` (see that
frozenset's own entry for the full rationale) -- it is exempt ONLY from the
four CAPABILITY-zone-ONLY rules (``adapter_module_import`` /
``adapter_registry_reference`` / ``introspection_escape_hatch`` /
``raw_run_operation_reference``); it is still held to every OTHER check
``scan.py`` enforces (SEALED_KERNEL is not a free pass -- see ``zones.py``'s
module docstring), and it still never imports a vendor SDK,
constructs/obtains a write-capable credential, or calls ``run_operation``
itself. See ``scan.py`` / ``zones.py`` for the full taxonomy.

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
from typing import List, NamedTuple, Optional

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
# (Task B1, F-74) The adapter registry's dispatch lookup + the ONE canonical
# source of the required evidence-predicate NAMES -- see evidence.py's
# REQUIRED_EVIDENCE_PREDICATES docstring for why this module must reference
# it via the MODULE (``evidence.REQUIRED_EVIDENCE_PREDICATES``), never a
# frozen name-import.
from external_write.adapter_registry import get_dispatch  # noqa: E402
from external_write import evidence  # noqa: E402
# Fires every shipped AND capability-added adapter module's module-scope
# ``register_adapter``/``register_contract`` call, exactly like
# ``operator_acceptance.py``'s own BI-2 pre-check -- see that module's
# docstring and ``registered_adapters.py``'s own "The fix" section. Without
# this import, check 4 below would refuse EVERY adapter-backed op_kind
# (correctly registered or not) merely because nothing had triggered
# registration yet in this process -- a false negative, not a true one.
import external_write.registered_adapters  # noqa: E402,F401

# (Task A2, F-70) Duplicated-by-value from capability_health.py / lifecycle_state.py's own
# PAUSED_MECHANISMS_DIR_REL and write_gate.py's PAUSED_MECHANISMS_DIR -- the SAME
# never-import-across-runtime-siblings discipline every one of those modules' own docstrings
# already documents (this module ships into the operator's own runtime alongside them, not across
# a build/runtime boundary, but the convention here is "each runtime module declares its own copy
# so none of them has a load-order dependency on another"). Pinned by value in
# scripts/lib/test_capability_invariants.py (TestPausedMechanismsDirAntiDrift), mirroring
# test_capability_health.py's own TestPathConstantsAntiDrift.
PAUSED_MECHANISMS_DIR_REL = ".wizard/paused-mechanisms"


@dataclass(frozen=True)
class InvariantResult:
    """The outcome of ``check_capability_invariants``.

    ok:               True iff every one of the seven checks passed (or was
                       N/A -- see checks 5, 6, and 7).
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
            "is coherent across the descriptor/capability/mechanism/module names, its "
            "operation kind is registered, its registered adapter (if any) declares every "
            "required evidence predicate, and (if accepted) it carries no residual pause "
            "marker."
        )
    lines = [
        "This capability failed one or more required structural checks and must not proceed "
        "to a live trial until every issue below is fixed:",
    ]
    lines.extend(f"  - {f}" for f in failures)
    lines.append("Fix the issue(s) above, then re-run this check before continuing.")
    return "\n".join(lines)


def check_capability_invariants(project_root: str, canonical_id: str) -> InvariantResult:
    """Run the seven AWB-authored, deterministic invariant checks for the
    capability whose canonical (module-derived) id is ``canonical_id``, in
    the project rooted at ``project_root``. Never raises -- every check that
    cannot be positively evaluated is folded into ``failures`` as its own
    fail-closed line (see the module docstring). Composes existing signals
    only; this function does not re-implement the scanner, the identity
    resolver, the test-target vocabulary, the contract registry, the
    audit-record dedup check, the pause-marker read, or the adapter-dispatch
    registry -- see the module docstring's numbered list for exactly which
    existing primitive backs each of the seven checks below.
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
    # op_kind is hoisted to the outer scope (default None) so Check 7 below --
    # a DIFFERENT concern (does the registered ADAPTER declare its required
    # evidence predicates), independent of whether a CONTRACT is registered --
    # can reuse whichever op_kind this capability actually declares, without
    # re-extracting it from source a second time.
    op_kind: Optional[str] = None
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
                f"{op_kind!r}, which has no registered contract. Fix step: enroll this "
                "capability's adapter module in agents/lib/external_write/operator_adapters.json "
                "(the add-capability build cascade does this for you) so it registers at import "
                "time, then re-run this check."
            )

    # --- Check 7: adapter evidence predicates (Task B1, F-74) ---------------
    # Fires ONLY when this capability's op_kind resolves to a REGISTERED
    # adapter (mirrors copy_run_proof.validate_copy_run_proof's identical
    # scope note: the six seeded field op_kinds have no registered adapter by
    # permanent design and are correctly N/A here, never a failure). Also N/A
    # when op_kind itself could not be resolved -- Check 4 above already
    # reports that failure on its own; this check adds nothing more for that
    # case. Reads the required predicate NAMES from the SAME canonical source
    # (external_write.evidence.REQUIRED_EVIDENCE_PREDICATES) the proof/
    # run-time gate reads -- see that constant's own docstring for why this
    # closes F-74 (two gates, one requirement, kept in sync rather than
    # drifting).
    if op_kind is not None:
        dispatch = get_dispatch(op_kind)
        if dispatch is not None:
            missing_predicates = [
                name for name in evidence.REQUIRED_EVIDENCE_PREDICATES
                if getattr(dispatch, name, None) is None or not callable(getattr(dispatch, name))
            ]
            if missing_predicates:
                failures.append(
                    f'Adapter evidence predicates: capability "{canonical_id}"\'s registered '
                    f"adapter for operation kind {op_kind!r} does not define "
                    f"{'/'.join(missing_predicates)}. This capability's adapter must define how "
                    "it verifies its write landed / can be undone; it stays paused until it "
                    "does. Fix step: add the missing predicate method(s) to this capability's "
                    "adapter module, then re-run this check."
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

    # --- Check 6: no residual paused_live_write marker, post-acceptance only ---------------
    # (Task A2, F-70 crash-safety half) An accepted capability should carry NO pause marker for
    # its own canonical id. Reconcile-on-accept (Task A1) and reconcile-on-read
    # (``capability_health.check_capabilities_with_self_heal``, Task A2) both already exist to
    # clear exactly this -- this check is the emitted self-QA's OWN independent catch, so that a
    # capability with an orphaned marker still surfaces as a required-fix failure here even if
    # BOTH of those mechanisms are somehow bypassed, rather than silently letting a structurally
    # inconsistent capability proceed to a live trial. N/A -- never a failure -- for a capability
    # that is not yet ``accepted: true`` (a marker on a not-yet-accepted capability is the normal
    # paused/pending-migration state, not a defect; mirrors check 5's own pre-acceptance N/A).
    if descriptor_entry is not None and descriptor_entry.get("accepted") is True:
        marker_paths = (
            root / PAUSED_MECHANISMS_DIR_REL / f"{canonical_id}.pause",
            root / PAUSED_MECHANISMS_DIR_REL / f"{canonical_id}.json",
        )
        # Fail-closed like every check above: ANY existing path -- a normal marker file, or one
        # in an unexpected/unreadable shape -- counts as residue; only a genuinely ABSENT path
        # (``_file_state`` returning "absent") is clean. Mirrors
        # ``capability_health._is_paused``'s own "any existing .pause path counts, regardless of
        # shape" convention.
        if any(_file_state(p) != "absent" for p in marker_paths):
            failures.append(
                f'Marker residue: capability "{canonical_id}" is marked accepted, but a pause '
                f"marker still exists on disk at {PAUSED_MECHANISMS_DIR_REL}/{canonical_id}.* for "
                "its operation kind(s). An accepted capability must carry no residual pause "
                "marker. Run this project's capability health check (python3 "
                "agents/lib/external_write/capability_health.py), which reconciles this "
                "automatically on read, then re-run this check."
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
# ``check_test_quality`` adds THREE RIGHT-SIZED, deterministic probes on top of
# D1-1 (the first two per the 2026-07-17 design consult's right-sizing calibration -- full
# mutation-style per-branch checks are heavier and partly redundant with the
# D1-1 invariants, and are deliberately deferred, not built here; the third added by Task A3,
# Cut 1.1, F-71 -- see that probe's own section below for why):
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
#   3. lifecycle hermeticity (AST, static; Task A3, F-71) -- does this capability's own test
#      file call the write gate's paused-op-kind check, or otherwise touch the ambient
#      ``.wizard/paused-mechanisms/`` path, WITHOUT going through the hermetic fixture
#      (``external_write.lifecycle_test_fixtures.hermetic_paused_mechanisms``)? A test that
#      relies on the write gate's own ambient default (or reads/writes the real project's
#      pause-marker path directly) gives a DIFFERENT verdict depending on this project's own
#      transient pause/rebuild/re-accept lifecycle state at the moment it happens to run --
#      exactly the F-71 false-RED. See that probe's own section for the full detection shape
#      and its documented limits.
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
#     bare or via attribute access, WHOSE TARGET TRACES BACK TO AN IMPORT OF
#     THE REAL ENTRYPOINT (DR-2 + Critical-fix conjunction: an import alone,
#     never called, is not sufficient -- neither is a call alone with no
#     matching import anywhere in the file, e.g. a locally-defined fake
#     ``run_enveloped_operation`` or an arbitrary object's
#     ``.run_enveloped_operation(...)`` -- see ``_ast_references_entrypoint``'s
#     own docstring for the exact import+call conjunction required), or an
#     import/module-reference of ``operator_acceptance`` (the acceptance CLI
#     -- import-only stays sufficient there; it is invoked as a subprocess,
#     not called in-process)?
#   * does it define its own class whose name IS (exactly, case-insensitive)
#     an optional fake/stub/mock/dummy affix plus ``Operation``/``Adapter``/
#     ``Plan`` (e.g. ``Operation``, ``FakeOperation``, ``StubAdapter``,
#     ``PlanFake``) -- a locally-defined stand-in for the real producer,
#     exactly the SB-8 shape?
#
# LIMITS (stated per this task's instruction to surface heuristic ambiguity):
#   * This is a NAME-based heuristic, not a data-flow analysis. (DR-2 fix) A
#     test that only IMPORTS the real entrypoint but never actually calls it
#     anywhere is correctly FLAGGED by this probe itself, not left to probe 2
#     (known-bad-fails) to catch indirectly. (Critical fix, task review) The
#     converse is also required and enforced: a CALL alone, with no import of
#     the real entrypoint anywhere in the file (a locally-defined fake
#     ``def run_enveloped_operation(): ...`` and a bare call to it, or an
#     arbitrary ``FakeThing().run_enveloped_operation()``), is correctly
#     FLAGGED too -- this probe requires the CONJUNCTION of a genuine import
#     of the real entrypoint (or its hosting module) AND a call whose target
#     resolves back to that same import, never either alone. The heuristic
#     still cannot tell whether a real ``ast.Call`` to the entrypoint is
#     reached at runtime (a call inside dead/unreachable code, or one whose
#     arguments are wrong, still satisfies this AST-only check) -- that
#     residual is exactly what probe 2 remains for.
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
#
# Detection shape + its limits (lifecycle hermeticity, Task A3, F-71)
# --------------------------------------------------------------------
# The F-71 defect was NOT a bare string literal sitting in a test file -- the real, verified
# defective test never once wrote the words ``.wizard/paused-mechanisms`` anywhere; it simply
# called ``write_gate.evaluate_write_gate(...)`` without a ``paused_root`` keyword, which is
# what let the gate fall through to ITS OWN ambient default. So this probe is not a grep for
# that path string -- per the design consult, "not a bare string ban" -- it is two STRUCTURAL,
# AST-only checks against the same discovered test file(s) probes 1/2 already use:
#
#   (a) a genuine ``ast.Call`` to the REAL ``write_gate.evaluate_write_gate`` (resolved back to
#       an actual import, the SAME import-tracking discipline
#       ``_ast_references_entrypoint`` already uses for ``run_enveloped_operation`` -- never a
#       same-named local function or an unrelated object's method) whose keyword arguments do
#       NOT include ``paused_root`` at all -- i.e. a call that necessarily falls through to the
#       gate's own ambient ``PAUSED_MECHANISMS_DIR`` default. A call that unpacks a bare
#       ``**mapping`` into its keywords is UNDECIDABLE from source text alone (the mapping's own
#       keys are not visible to an AST-only pass) and is deliberately NOT flagged -- a known gap,
#       not a designed pass. Likewise, a call that explicitly passes ``paused_root=None`` (the
#       same VALUE as the omitted-keyword default) is not flagged either, even though it is
#       behaviorally identical to omitting the keyword -- this probe checks for the keyword's
#       PRESENCE, not the value behind it.
#   (b) a literal string equal to (or path-prefixed by) ``PAUSED_MECHANISMS_DIR_REL`` appearing
#       as an argument to a recognizable filesystem-operation call (``open``, ``Path``,
#       ``os.makedirs``/``mkdir``/``listdir``/``remove``/``stat``/``path.join``, ``shutil.*``,
#       or a ``Path`` method such as ``.write_text``/``.mkdir``/``.exists``) anywhere in the
#       test file -- the direct-ambient-touch shape, independent of whether the file calls
#       ``evaluate_write_gate`` at all. Anchored to the literal being an ARGUMENT INSIDE a
#       recognized filesystem call (never a bare substring match anywhere in the file), so a
#       test that merely references the constant's VALUE for an unrelated comparison (e.g.
#       pinning ``write_gate.PAUSED_MECHANISMS_DIR`` against an expected string, with no
#       filesystem call in sight) is correctly left unflagged.
#
# Both checks are scoped to the SAME test file(s) ``_discover_capability_test_files`` already
# found for this capability -- a test file that never mentions this capability's own module is
# out of scope for every D1-2 probe, including this one. A file that legitimately uses the
# hermetic fixture (imports ``lifecycle_test_fixtures.hermetic_paused_mechanisms`` and passes
# its returned path as ``paused_root=``) never trips either check: it never omits the keyword
# and it never needs to reference the ambient literal at all -- the fixture module owns its own
# temp path internally. LIMITS: like every AST-only probe in this file, this cannot tell whether
# a flagged call is actually REACHED at runtime (dead code still satisfies the shape), and (a)'s
# ``**mapping`` gap means a test that hides ``paused_root`` inside a dict-unpack defeats
# detection -- both are documented gaps, not silent false assurance, exactly like probe 1's own
# documented LIMITS above.
# =============================================================================

_TEST_DISCOVERY_SKIP_DIR_NAMES = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".hg", ".svn", ".tox",
}

# The two names that mark a REAL producer-entrypoint reference: the sanctioned
# live-write entrypoint capability code is meant to call, and the acceptance
# CLI's own module name (imported by name or invoked as a module).
_ENTRYPOINT_IMPORT_NAMES = frozenset({"run_enveloped_operation"})
_ACCEPTANCE_CLI_MODULE_NAME = "operator_acceptance"
# The real module that HOSTS run_enveloped_operation (external_write.capability_api) -- its own
# last dotted segment, used to recognize the module-import + attribute-access-call shape (see
# _ast_references_entrypoint). Matched the same way _ACCEPTANCE_CLI_MODULE_NAME is: the last
# dotted segment of an ``import`` statement's dotted name, never the full path (a test may import
# it as ``external_write.capability_api`` or bare ``capability_api``).
_ENTRYPOINT_MODULE_NAME = "capability_api"
# The package that HOSTS the real entrypoint module above (external_write.capability_api's
# own PACKAGE) -- used only defensively, to scope the from-package import-module idiom
# (``from external_write import capability_api``) to the real package, never to accept
# ``from <anything> import capability_api`` unconditionally.
_ENTRYPOINT_MODULE_PACKAGE_NAME = "external_write"

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

# (Task A3, F-71) The name that marks a genuine call to the write gate's own paused-op-kind
# check, and the module that hosts it -- matched the SAME way ``_ENTRYPOINT_IMPORT_NAMES`` /
# ``_ENTRYPOINT_MODULE_NAME`` match the real live-write entrypoint above (import-tracked, never
# a same-named local function or an unrelated object's method).
_WRITE_GATE_CALL_NAME = "evaluate_write_gate"
_WRITE_GATE_MODULE_NAME = "write_gate"
# The keyword a call to evaluate_write_gate must carry to be hermetic -- see this probe's own
# "Detection shape + its limits" section above.
_PAUSED_ROOT_KWARG_NAME = "paused_root"
# The hermetic fixture helper (external_write.lifecycle_test_fixtures.hermetic_paused_mechanisms)
# a capability test should import instead -- named here only for the operator-facing failure
# message text, not matched against by either AST check (a file that genuinely uses it simply
# never trips either check in the first place -- see the module docstring section above).
_HERMETIC_FIXTURE_MODULE_NAME = "lifecycle_test_fixtures"
_HERMETIC_FIXTURE_HELPER_NAME = "hermetic_paused_mechanisms"
# The recognizable filesystem-operation call names probe 3's check (b) scopes to -- mirrors
# ``_ENTRYPOINT_IMPORT_NAMES``'s "a fixed, named vocabulary, not an open-ended guess" discipline.
_FS_OPERATION_CALL_NAMES = frozenset({
    "open", "Path", "makedirs", "mkdir", "listdir", "remove", "unlink", "rmtree",
    "stat", "join", "exists", "write_text", "write_bytes", "read_text", "read_bytes",
})


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


def _ast_dotted_name(node: ast.AST) -> Optional[str]:
    """Reconstruct the dotted name a ``Name``/``Attribute`` chain spells out
    (e.g. ``external_write.capability_api`` for
    ``Attribute(attr="capability_api", value=Name(id="external_write"))``), or
    ``None`` if ``node`` is not a pure name/attribute chain (e.g. it is itself
    a call result, a subscript, ...) -- used to resolve the OBJECT an
    attribute-access call's ``.run_enveloped_operation(...)`` is made on back
    to whatever was actually imported, so that object can be checked against
    the set of names genuinely bound to the real entrypoint module (see
    ``_ast_references_entrypoint``)."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


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
    honest producer-entrypoint verdict).

    (Critical fix, task review) The conjunction below requires BOTH an IMPORT
    of the real entrypoint AND a CALL whose target traces back to that import
    -- a call alone (no matching import anywhere in the file) is NEVER
    sufficient. Before this fix, ``call_names`` was seeded with
    ``run_enveloped_operation`` UNCONDITIONALLY (before any import was even
    inspected), and the attribute-call branch matched ``func.attr ==
    "run_enveloped_operation"`` on ANY object regardless of what it was --
    together these accepted a test file that defines its OWN local ``def
    run_enveloped_operation(): ...`` and calls it, or an arbitrary
    ``FakeThing().run_enveloped_operation()``, with the REAL entrypoint never
    imported from anywhere. This now requires a real ``ast.Call`` reaching the
    entrypoint, in EITHER shape:
      * ``from ... import run_enveloped_operation`` (optionally ``as X``) then a
        bare ``run_enveloped_operation(...)`` / ``X(...)`` call whose name was
        bound by exactly that import, or
      * an ``import`` of the real entrypoint's module -- a dotted path whose
        LAST segment is ``capability_api`` (``import external_write.capability_api``,
        ``import external_write.capability_api as cap``, bare ``import
        capability_api``, ...) -- binding a local name (the alias, or the
        dotted name/its first component for a plain ``import``), THEN an
        attribute-access call ``<that bound reference>.run_enveloped_operation(...)``
        whose object resolves (by dotted name/attribute-chain reconstruction,
        see ``_ast_dotted_name``) back to exactly what that import bound (e.g.
        ``capability_api.run_enveloped_operation(...)`` after ``import
        capability_api``, or ``external_write.capability_api.run_enveloped_operation(...)``
        after ``import external_write.capability_api``), or
      * (selfqa idiom fix) an ``ast.ImportFrom`` that imports the real entrypoint
        MODULE (not the entrypoint NAME) from its own package -- ``from
        external_write import capability_api`` (optionally ``as X``) -- binding a
        local name the same way, THEN the same attribute-access call shape
        (``capability_api.run_enveloped_operation(...)``). Recognized by the
        imported alias's name matching ``_ENTRYPOINT_MODULE_NAME`` exactly (the
        same constant the plain-``import`` branch matches against -- never a
        second hardcoded literal), defensively scoped to a from-module whose
        last dotted segment is the real entrypoint's own package
        (``_ENTRYPOINT_MODULE_PACKAGE_NAME``).

      An attribute call on an object that was never imported as the real
      entrypoint module (a locally-defined class instance, an unrelated
      import, ...) is REJECTED even though its trailing attribute name
      matches.

    DECISION (per this task's own "if unsure" default): the acceptance-CLI path
    is deliberately left as import/module-reference-only, NOT also requiring a
    call -- ``operator_acceptance`` is invoked as a CLI subprocess (``python -m
    operator_acceptance ...``), not called as an in-process Python function, so
    there is no ``ast.Call`` node to require in the first place; naming the
    module remains the right-sized evidence for that entrypoint."""
    call_names = set()
    module_refs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_parts = (node.module or "").split(".")
            if _ACCEPTANCE_CLI_MODULE_NAME in module_parts:
                return True
            for alias in node.names:
                if alias.name in _ENTRYPOINT_IMPORT_NAMES:
                    call_names.add(alias.asname or alias.name)
                elif (
                    alias.name == _ENTRYPOINT_MODULE_NAME
                    and module_parts
                    and module_parts[-1] == _ENTRYPOINT_MODULE_PACKAGE_NAME
                ):
                    # ``from external_write import capability_api`` -- an ImportFrom
                    # that imports the real entrypoint MODULE (not the entrypoint
                    # NAME) from its own package. Recognized the same way the
                    # ``import`` branch below recognizes ``import
                    # external_write.capability_api`` -- by the real module's own
                    # name (``_ENTRYPOINT_MODULE_NAME``, reused, never
                    # re-hardcoded) -- so a later
                    # ``capability_api.run_enveloped_operation(...)`` attribute
                    # call resolves back to it via ``module_refs``.
                    module_refs.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                dotted_parts = alias.name.split(".")
                if _ACCEPTANCE_CLI_MODULE_NAME in dotted_parts:
                    return True
                if dotted_parts[-1] == _ENTRYPOINT_MODULE_NAME:
                    module_refs.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in call_names:
            return True
        if isinstance(func, ast.Attribute) and func.attr in _ENTRYPOINT_IMPORT_NAMES:
            base_dotted = _ast_dotted_name(func.value)
            if base_dotted is not None and base_dotted in module_refs:
                return True
    return False


def _ast_calls_write_gate_without_paused_root(tree: ast.AST) -> List[ast.Call]:
    """(Task A3, F-71) Every ``ast.Call`` in ``tree`` that resolves to the REAL
    ``write_gate.evaluate_write_gate`` (the SAME import-tracking discipline
    ``_ast_references_entrypoint`` uses for ``run_enveloped_operation`` above -- a call whose
    target traces back to an actual import of ``evaluate_write_gate`` itself, or of the
    ``write_gate`` module followed by a matching attribute-access call) and does NOT pass an
    explicit ``paused_root`` keyword -- i.e. a call that necessarily falls through to the gate's
    own ambient default (``write_gate.PAUSED_MECHANISMS_DIR``, the real project's
    ``.wizard/paused-mechanisms/``), exactly the F-71 shape.

    A call whose keywords include a bare ``**mapping`` unpack (``kw.arg is None``) is
    UNDECIDABLE from source text alone -- the mapping's own keys are not visible to an AST-only
    pass -- and is deliberately NOT flagged (see this probe's module-level LIMITS note); a call
    that explicitly passes ``paused_root=None`` is also not flagged, even though it is
    behaviorally identical to omitting the keyword (this checks the keyword's PRESENCE, not the
    value behind it)."""
    call_names = set()
    module_refs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_parts = (node.module or "").split(".")
            for alias in node.names:
                if alias.name == _WRITE_GATE_CALL_NAME:
                    call_names.add(alias.asname or alias.name)
                elif (
                    alias.name == _WRITE_GATE_MODULE_NAME
                    and module_parts
                    and module_parts[-1] == _ENTRYPOINT_MODULE_PACKAGE_NAME
                ):
                    module_refs.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                dotted_parts = alias.name.split(".")
                if dotted_parts[-1] == _WRITE_GATE_MODULE_NAME:
                    module_refs.add(alias.asname or alias.name)

    hits: List[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_write_gate_call = False
        if isinstance(func, ast.Name) and func.id in call_names:
            is_write_gate_call = True
        elif isinstance(func, ast.Attribute) and func.attr == _WRITE_GATE_CALL_NAME:
            base_dotted = _ast_dotted_name(func.value)
            if base_dotted is not None and base_dotted in module_refs:
                is_write_gate_call = True
        if not is_write_gate_call:
            continue
        if any(kw.arg is None for kw in node.keywords):
            continue  # **mapping unpack -- undecidable statically, not flagged (LIMIT)
        if any(kw.arg == _PAUSED_ROOT_KWARG_NAME for kw in node.keywords):
            continue  # explicit paused_root passed -- hermetic (or at least intentional)
        hits.append(node)
    return hits


def _ast_call_name(func: ast.AST) -> Optional[str]:
    """The plain call-target name for ``func`` -- a bare ``Name`` id, or an ``Attribute``'s own
    trailing ``.attr`` (so ``os.makedirs(...)`` and a bare ``makedirs(...)`` both resolve to
    ``"makedirs"``) -- or ``None`` for any other call shape (e.g. a call on a call result).
    Deliberately name-only, not object-resolved: see ``_ast_touches_ambient_paused_mechanisms_path``
    for why this is sufficient for that check's purposes."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _ast_touches_ambient_paused_mechanisms_path(tree: ast.AST) -> bool:
    """(Task A3, F-71) True iff a string constant equal to, or path-prefixed by,
    ``PAUSED_MECHANISMS_DIR_REL`` appears as an argument (positional or keyword) to a
    recognizable filesystem-operation call (``_FS_OPERATION_CALL_NAMES``) anywhere in ``tree`` --
    the direct-ambient-touch shape, independent of whether the file calls
    ``evaluate_write_gate`` at all (see ``_ast_calls_write_gate_without_paused_root`` for that
    shape). Each argument subtree is walked (not only its top level) so a literal nested inside
    an ``os.path.join(root, ".wizard/paused-mechanisms", ...)`` call is still caught.

    Anchored to the literal being an ARGUMENT INSIDE a recognized filesystem call -- never a bare
    substring match anywhere in the file (per the design consult, "not a bare string ban") -- so
    a test that merely references the constant's VALUE for an unrelated comparison (e.g. pinning
    ``write_gate.PAUSED_MECHANISMS_DIR`` against an expected string, with no filesystem call in
    sight) is correctly left unflagged. See this probe's module-level "Detection shape + its
    limits" section for what this heuristic does not catch."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _ast_call_name(node.func) not in _FS_OPERATION_CALL_NAMES:
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for sub in ast.walk(arg):
                if (
                    isinstance(sub, ast.Constant)
                    and isinstance(sub.value, str)
                    and (
                        sub.value == PAUSED_MECHANISMS_DIR_REL
                        or sub.value.startswith(PAUSED_MECHANISMS_DIR_REL + "/")
                    )
                ):
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


class _DiscoverOutcome(NamedTuple):
    """Structured outcome of one ``_run_discover`` subprocess run (DR-1 fix).

    tests_run:     the number unittest itself reports having run, parsed from
                    its own "Ran N tests" summary line. This INCLUDES a
                    synthetic collection-failure test unittest fabricates when
                    a test module cannot even be imported (see
                    ``import_error`` below) -- so ``tests_run`` alone cannot
                    distinguish "N real tests ran" from "collection itself
                    failed and unittest counted its own synthetic failure test
                    as one".
    import_error:   True iff the run's own output carries unittest's
                    collection-failure marker ("Failed to import test module" /
                    "unittest.loader._FailedTest") -- i.e. ``tests_run`` (if
                    nonzero) reflects a SYNTHETIC collection failure, not a
                    real test that exercised the capability's own code.
    failed:         True iff the subprocess exited non-zero -- a failure or
                    error was reported, real or synthetic; see
                    ``real_tests_ran`` / ``real_failure`` below for the
                    distinction callers actually need.
    """

    tests_run: int
    import_error: bool
    failed: bool

    @property
    def real_tests_ran(self) -> int:
        """The number of tests that ACTUALLY EXERCISED the capability's own
        code -- always 0 when ``import_error`` is True: a collection failure
        is never a real test, regardless of what ``tests_run`` reports."""
        return 0 if self.import_error else self.tests_run

    @property
    def real_failure(self) -> bool:
        """True iff a REAL test (not a collection failure) actually failed or
        errored -- what a suite that genuinely caught a deliberate break
        SHOULD show."""
        return self.failed and not self.import_error


# unittest's own TextTestRunner summary line ("Ran 3 tests in 0.001s") -- present
# on every completed run, INCLUDING a run whose only "test" is unittest's own
# synthetic collection-failure stand-in (see _DiscoverOutcome.import_error).
_TESTS_RUN_RE = re.compile(r"Ran (\d+) tests? in")

# unittest.loader's own marker text for a module that could not even be
# imported/collected -- stable across CPython versions (unittest.loader._FailedTest
# is the same synthetic-test class used for an import failure, a load_tests
# failure, and a few other collection-time errors -- see that module's own
# _make_failed_import_test). Checked in the run's own combined output rather than
# by re-implementing unittest's collection machinery in a subprocess-invoked
# snippet -- cheaper, and just as robust to the actual failure text unittest
# itself prints.
_IMPORT_ERROR_MARKERS = ("Failed to import test module", "unittest.loader._FailedTest")


def _run_discover(python_exe: str, cwd: Path, test_file: Path, env: dict) -> Optional[_DiscoverOutcome]:
    """Run ONE test file's suite via ``python -m unittest discover``, scoped to
    exactly that file (``-s <its directory>``, ``-p <its exact basename>``) so
    unrelated tests elsewhere in the (copied) tree are never pulled in.

    Returns a ``_DiscoverOutcome`` describing not just whether the run exited
    non-zero, but whether any REAL test actually ran (DR-1 fix -- see that
    NamedTuple's own docstring): a bare exit-code check cannot tell "a real
    test caught the deliberate break" apart from "this test file could not
    even be imported/collected, so unittest's own synthetic failure test
    tripped the same non-zero exit without a single real test ever running".
    Returns ``None`` if the run could not be completed at all (timeout /
    launch failure), or if unittest's own summary line could not be found in
    the run's output at all (an even more fundamental failure than an import
    error -- the run did not get far enough to report anything unittest
    itself vouches for) -- the caller folds ``None`` into a fail-closed
    failure line, never a silent pass, exactly as before."""
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
    combined_output = (result.stdout or "") + (result.stderr or "")
    match = _TESTS_RUN_RE.search(combined_output)
    if match is None:
        return None
    return _DiscoverOutcome(
        tests_run=int(match.group(1)),
        import_error=any(marker in combined_output for marker in _IMPORT_ERROR_MARKERS),
        failed=result.returncode != 0,
    )


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
          run again. Every one of them MUST now fail with a REAL test
          failure/error (not merely a non-zero exit); any that does not is
          inert.

    (DR-1 fix) A bare exit-code/boolean signal from ``_run_discover`` is
    ITSELF not enough to tell a real test failure apart from a suite that
    collected and ran ZERO real tests -- two distinct failure modes this
    fix closes:
      * a pytest-style suite (bare ``def test_...`` functions, never inside a
        ``unittest.TestCase``) collects ZERO tests under ``unittest
        discover`` and exits CLEAN (0) both before and after the mutation --
        the OLD baseline check scored that clean exit as "green" and let it
        fall through to the mutated run, where it landed on the generic
        "still reported all tests passing" inert-suite message: unhelpful and
        dead-ending for an operator who wrote functionally-correct tests in
        the wrong style.
      * a suite built entirely of MODULE-LEVEL assertions (never inside a
        ``unittest.TestCase`` method) also collects ZERO real tests, but
        passes SILENTLY at baseline (the real, working implementation makes
        the assertion pass at import time) and then CRASHES ON IMPORT once
        the implementation is mutated -- unittest folds that import crash
        into a synthetic one-test failure, which the OLD bare-boolean check
        could not distinguish from a real test genuinely catching the break,
        so this was scored ``ok=True`` (false assurance) even though zero
        real tests ever ran.

    Both failure modes share the same root cause -- ZERO real tests ran at
    baseline -- and the same fix: if ``real_tests_ran == 0`` at baseline (see
    ``_DiscoverOutcome.real_tests_ran``), STOP right there with a plain-
    language, actionable message (write real ``unittest.TestCase`` tests) --
    this is NEITHER scored "effective" (there is nothing to be effective; the
    mutated run is never even reached) NOR the generic inert-suite dead-end
    (which implies the suite ran and just didn't catch anything, which is not
    what happened here). A baseline run that DOES collect real tests but
    fails or errors for a real reason (or crashes on an UNRELATED import,
    e.g. a genuinely missing dependency) still gets the existing "does not
    pass cleanly" message, unchanged.

    The probe passes only when (a) is entirely green (real tests ran, none
    failed) AND (b) is entirely red (every file shows a REAL failure/error,
    never merely an import crash). Returns a plain-language failure line, or
    ``None`` if the probe passed. Always cleans up the temp directory, even
    on error -- see module docstring for the full isolation and boundedness
    contract."""
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
        # Three buckets, checked in this order per file (a collection-time crash
        # -- import_error or a non-zero exit -- always takes priority over the
        # zero-real-tests bucket, so an UNRELATED import crash, e.g. a genuinely
        # missing dependency, still gets the "does not pass cleanly" message, not
        # the "write as unittest.TestCase" one):
        baseline_not_green: List[str] = []
        baseline_zero_real_tests: List[str] = []
        baseline_uncertain = False
        for rel_tf in rel_test_files:
            outcome = _run_discover(sys.executable, copy_root, copy_root / rel_tf, env)
            if outcome is None:
                baseline_uncertain = True
            elif outcome.import_error or outcome.failed:
                baseline_not_green.append(str(rel_tf))
            elif outcome.tests_run == 0:
                baseline_zero_real_tests.append(str(rel_tf))
            # else: real_tests_ran > 0, not failed, not import_error -- green.

        if baseline_uncertain:
            return (
                f'Known-bad-fails: this capability\'s own test suite could not be run to check '
                "whether it passes cleanly on its own (before any deliberate change), so its "
                "effectiveness cannot be verified."
            )
        if baseline_zero_real_tests:
            return (
                f'Known-bad-fails: {", ".join(baseline_zero_real_tests)} did not run as unittest '
                "tests -- unittest only discovers tests defined as methods inside a "
                "class MyTest(unittest.TestCase) with def test_... names; bare pytest-style "
                "functions (or assertions written at module level, outside any test method) are "
                "never found, so this capability's test suite's effectiveness cannot be "
                "verified. Write each test as a class MyTest(unittest.TestCase) with def test_... "
                "methods, then re-run this check."
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
            elif not outcome.real_failure:
                # Not "effective": either a clean pass (genuinely inert -- the
                # mutation broke nothing this suite noticed) OR a collection-time
                # import crash (DR-1 fix -- an import-time crash is NOT evidence a
                # real test caught the break; see this function's own docstring).
                # Both get the same treatment here: this file did not prove
                # anything, so it is not scored effective.
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
            "This capability's own tests passed all three deterministic quality probes: they "
            "exercise the real capability module and its real acceptance/gate entrypoint (not a "
            "hand-built stand-in), they never depend on this project's own ambient pause/"
            "lifecycle state, and they correctly fail when run against a deliberately broken "
            "copy of the implementation."
        )
    lines = [
        "This capability's tests failed one or more required quality checks and must be fixed "
        "before this capability proceeds to a live trial:",
    ]
    lines.extend(f"  - {f}" for f in failures)
    lines.append("Fix the issue(s) above, then re-run this check before continuing.")
    return "\n".join(lines)


def check_test_quality(project_root: str, canonical_id: str) -> InvariantResult:
    """Run the three AWB-authored, deterministic test-quality probes (D1-2 + Task A3) for
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

    # --- Probe 3: lifecycle hermeticity (AST, static; Task A3, F-71) --------
    # Independent of probe 1 above: a capability test can pass probe 1 (it genuinely exercises
    # the real capability + entrypoint) and still be non-hermetic in a completely separate test
    # method that touches paused/lifecycle state -- so this probe fires on its own evidence, not
    # gated on probe 1's outcome. See the module-level "Detection shape + its limits" section
    # (above ``_TEST_DISCOVERY_SKIP_DIR_NAMES``) for exactly what each check catches and does not.
    ambient_hits: List[str] = []
    for tf in test_files:
        try:
            tree = ast.parse(tf.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue  # already excluded by discovery; defensive only
        rel = str(tf.relative_to(root))
        if _ast_calls_write_gate_without_paused_root(tree) or _ast_touches_ambient_paused_mechanisms_path(tree):
            ambient_hits.append(rel)

    if ambient_hits:
        failures.append(
            f'Lifecycle hermeticity: {", ".join(sorted(ambient_hits))} calls '
            f"{_WRITE_GATE_CALL_NAME}(...) without an explicit {_PAUSED_ROOT_KWARG_NAME}=... "
            f"keyword, or otherwise touches the ambient {PAUSED_MECHANISMS_DIR_REL} path "
            "directly -- so its outcome depends on THIS PROJECT'S OWN real, transient pause "
            "state at whatever moment the test happens to run, and will silently flip pass/fail "
            "as that state changes (for example, once this capability is re-accepted and its "
            "pause marker is cleared). Pause/lifecycle-state enforcement is the write gate's own "
            "concern, already proven by its own test suite -- a capability's test should not "
            f"re-test it against ambient state. If a test genuinely needs to exercise paused "
            f"behavior, import {_HERMETIC_FIXTURE_HELPER_NAME} from "
            f"external_write.{_HERMETIC_FIXTURE_MODULE_NAME} and pass its returned temp "
            f"directory as {_PAUSED_ROOT_KWARG_NAME}=..., never the real project's own path. "
            "Fix the test(s) above, then re-run this check."
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
