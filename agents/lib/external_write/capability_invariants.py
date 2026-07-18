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
import stat
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
    fail-closed/empty-safe, never guesses."""
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
        if isinstance(target, ast.Name) and target.id == "OP_KIND":
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


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
