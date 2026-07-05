"""B1-5 / B2-T1 — the deterministic descriptor-COVERAGE gate: the second build-time safety gate.

Run in MA-REV ALONGSIDE the AST bypass scanner (``scan.py``) but SEPARATE from it. The two
gates answer complementary questions and together make the design invariant enforceable at
build time:

  * ``scan.py`` (unchanged, imported here, kept PURE): "does any write BYPASS the adapter
    package?" — a deterministic AST/call-graph check over the operator's scripts.
  * THIS gate: "is every GUARDED mutator covered by a DECLARED, structurally-valid descriptor of
    the right risk class?" — a deterministic projection over the in-code operation contracts
    (``contracts.py``) joined against the machine-readable declared-descriptor set (B1-2).

As of B2-T1, this gate does NOT check ``accepted``. ACCEPTANCE for live writes is enforced at
RUNTIME by the sibling ``write_gate`` (a capability runs against its declared test target until a
covering phase is accepted). The split exists because a descriptor is ALWAYS emitted with
``accepted: false`` and only becomes accepted after an operator accepts the BUILT capability —
requiring acceptance at BUILD time would deadlock the operator-originated-enhancement flow (a
capability cannot be accepted until it is built, but a build-time acceptance requirement would
block the build until it is accepted). So: build-time checks DECLARATION, runtime checks
ACCEPTANCE. The two are deliberately different gates enforcing different halves of the invariant.

THE OVERRIDING PROPERTY is fail-closed EVERYWHERE. A missing input — an absent/unreadable/empty
descriptor set, a malformed entry, a join MISS for a real mutator, any ambiguity — must NEVER
pass the gate. Every leg below defaults to FAIL. ``read_only_local`` NEVER trips (design §4.5:
a read-only local ingest must not fire the same fail-closed path as an external delete/send;
over-firing trains rubber-stamping).

------------------------------------------------------------------------------
The deterministic algorithm
------------------------------------------------------------------------------
Inputs (all deterministic; no clock, no randomness, no LLM):
  1. ``scan_violations`` — the output of ``scan.scan_paths()`` over the phase's code.
  2. ``descriptor_set``  — the machine-readable descriptor set (B1-2
     ``render_descriptor_registry_json`` shape; entries may be accepted or unaccepted — this gate
     does not care), loaded fail-closed (``[]`` when absent) via the SAME loader convention B1-4
     uses (``write_gate.load_accepted_descriptor_set``). (B2-T2 will point the build-time loader
     at the declared-registry file specifically; unchanged in this task.)
  3. ``contracts_map``   — op_kind -> ``OperationContract`` (defaults to the real
     ``contracts.OPERATION_CONTRACTS``): the authoritative, in-code enumeration of the named
     external-write operations. This is the "guarded mutator" demand side.

The gate FAILS (phase fails, fail-closed) when ANY leg holds:

  (a) ``scan_violations`` is non-empty — an external write outside the adapter package is an
      unguarded/uncovered write path.  [kind: ``bypass_scan_violation``]

  Malformed-input guard (fail-closed, evaluated before the coverage legs): any descriptor entry
  that is not a well-formed dict, or whose ``risk_class`` is not a value in the vocabulary
  (``contracts.RISK_CLASSES``), is MALFORMED. It is NOT fail-safe-resolved into a covering entry
  (doing so would be fail-OPEN — a garbage entry could "cover" an irreversible mutator); it
  fails the gate outright.  [kind: ``malformed_descriptor_entry``]

  (b)/(d) A write-shaped GUARDED mutator has NO covering DECLARED descriptor entry of its risk
      class — i.e. the op->descriptor join (below) MISSES. A guarded mutator is any op_kind whose
      contract's effective risk_class is in ``GATED_RISK_CLASSES`` OR whose contract sets
      ``requires_accepted_phase=True`` (exactly ``write_gate``'s gating boundary). A writer with
      no covering descriptor is NEVER treated as covered (carried req #1); a join miss fails
      closed and never falls through to pass (carried req #2).  [kind: ``uncovered_mutator``]

It PASSES only when the scan is clean AND every guarded mutator has a DECLARED covering
descriptor of the right risk class. ACCEPTANCE is deliberately NOT checked here — a descriptor
with ``accepted: false`` covers a mutator just as well as one with ``accepted: true``. Whether a
live write is actually allowed to run is enforced at RUNTIME by ``write_gate`` (against its
declared test target until a covering phase is accepted); this build-time gate only guarantees
that a descriptor was DECLARED for every guarded mutator, so runtime always has something to
check acceptance against.

------------------------------------------------------------------------------
The single explicit op -> descriptor join (carried req #2)
------------------------------------------------------------------------------
The contract layer is surface-AGNOSTIC (an ``OperationContract`` names an op_kind and a
risk_class, never a surface/dependency id). The descriptor layer is per-dependency (id/name is a
surface/dependency id). ``risk_class`` is the ONE typed attribute both layers share, and it is
exactly the SECONDARY join condition ``write_gate._covering_entry`` already uses at runtime
(where ``surface`` is the primary key). At build time no surface is available on the contract, so
this gate joins one altitude up, on ``risk_class`` alone:

    ``covering_declared_descriptor(risk_class, descriptor_set)`` returns the first descriptor
    entry whose ``risk_class`` equals the mutator's effective risk_class — regardless of
    ``accepted`` — or ``None`` (a join MISS => the caller fails closed).

This is the SINGLE explicit join function; there is no other path from a mutator to a descriptor.
Its known bound is disclosed, not silent: surface-level precision (does THIS surface's capability
have an accepted phase?) is the RUNTIME ``write_gate``'s job — it joins on surface AND checks
``accepted``. This build-time gate enforces only the contract-altitude DECLARATION invariant
(every guarded op_kind's risk class has a declared covering phase); it deliberately does not
enforce ACCEPTANCE — that is entirely runtime's job, checked against the same descriptor once a
surface is known.

Vocabulary constants (``GATED_RISK_CLASSES``, ``READ_ONLY_LOCAL``, ``FAIL_SAFE_RISK_CLASS``) are
imported from ``write_gate`` — a single source, already duplicated from the build-side tree
(D-B1-a) and pinned equal by cross-tree tests. This gate adds no new duplication.

Stdlib only — no third-party dependencies.
"""

from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Union
from pathlib import Path

# sys.path bootstrap: unlike scan.py (pure stdlib, no sibling imports), this module imports
# other modules of the external_write package. When invoked as a direct script from the project
# root (MA-REV: ``python3 agents/lib/external_write/coverage_gate.py agents/``), Python puts this
# file's OWN directory on sys.path, not the package parent, so ``import external_write.scan``
# would fail. Make the package parent (``agents/lib``) importable if it is not already (a no-op
# under the test harness, which puts it on the path itself). Anchored to __file__, not cwd.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.scan import Violation, scan_paths
from external_write.contracts import (
    OPERATION_CONTRACTS, OperationContract, RISK_CLASSES,
)
from external_write.write_gate import (
    load_accepted_descriptor_set,
    GATED_RISK_CLASSES,
    READ_ONLY_LOCAL,
    FAIL_SAFE_RISK_CLASS,
)

# The full known risk vocabulary (for effective-risk resolution), mirroring
# write_gate._effective_risk_class's `known` set.
_KNOWN_RISK_CLASSES = GATED_RISK_CLASSES | {READ_ONLY_LOCAL, "reversible_external"}


class CoverageFailure(NamedTuple):
    """One reason the coverage gate failed.

    kind:   one of 'bypass_scan_violation', 'malformed_descriptor_entry', 'uncovered_mutator'.
            Specific enough that a build-failure message tells the operator/agent WHAT to fix.
    detail: a human-readable description of the specific failing item.
    """

    kind: str
    detail: str


class CoverageDecision(NamedTuple):
    """Outcome of the coverage gate. ``passed`` is True IFF ``failures`` is empty."""

    passed: bool
    failures: List[CoverageFailure]


# ---------------------------------------------------------------------------
# Effective risk-class resolution (fail-safe, mirrors write_gate._effective_risk_class)
# ---------------------------------------------------------------------------

def _effective_contract_risk_class(contract: OperationContract) -> str:
    """The mutator's effective risk class: the contract's declared class if it is in the known
    vocabulary, else the MOST-protected class (never read_only_local by omission — F-28)."""
    rc = getattr(contract, "risk_class", None)
    if isinstance(rc, str) and rc in _KNOWN_RISK_CLASSES:
        return rc
    return FAIL_SAFE_RISK_CLASS


def _is_guarded_mutator(contract: OperationContract) -> bool:
    """A guarded (write-shaped, coverage-requiring) mutator — exactly write_gate's gating
    boundary: an effective risk class in GATED_RISK_CLASSES, OR requires_accepted_phase=True.
    read_only_local and plain reversible_external ops are NOT guarded here (read_only never
    trips; reversible is enforced by the broker + copy_run_proof, not by this mechanism)."""
    rc = _effective_contract_risk_class(contract)
    return rc in GATED_RISK_CLASSES or bool(getattr(contract, "requires_accepted_phase", False))


# ---------------------------------------------------------------------------
# The single explicit op -> descriptor join (carried req #2)
# ---------------------------------------------------------------------------

def covering_declared_descriptor(
    risk_class: str, descriptor_set: Sequence[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """THE join function. Return the first descriptor entry that COVERS a guarded mutator of the
    given effective ``risk_class``, or ``None`` (a join MISS — the caller fails closed).

    Covering requires ONLY that the entry's ``risk_class`` equals the mutator's effective
    risk_class (the only attribute the surface-agnostic contract layer and the per-dependency
    descriptor layer share; write_gate uses it as its secondary join condition). ``accepted`` is
    NOT checked — this build-time gate verifies DECLARATION, not acceptance; acceptance for live
    writes is runtime's job (write_gate). Entries are assumed already validated well-formed by
    the caller (malformed entries fail the gate before the join runs), so this never
    fail-safe-resolves a bad risk_class."""
    for e in descriptor_set:
        if not isinstance(e, dict):
            continue
        if e.get("risk_class") != risk_class:
            continue
        return e
    return None


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------

def _validate_entries(descriptor_set: Sequence[Any]) -> List[CoverageFailure]:
    """Fail-closed malformed-input guard. Every entry must be a dict whose ``risk_class`` is a
    value in the vocabulary. Anything else is malformed and fails the gate (it is NOT fail-safe-
    resolved into a covering entry — that would be fail-OPEN)."""
    failures: List[CoverageFailure] = []
    for i, e in enumerate(descriptor_set):
        if not isinstance(e, dict):
            failures.append(CoverageFailure(
                "malformed_descriptor_entry",
                f"descriptor entry #{i} is not a JSON object ({type(e).__name__})"))
            continue
        rc = e.get("risk_class")
        if not (isinstance(rc, str) and rc in RISK_CLASSES):
            ident = e.get("id") or e.get("name") or f"#{i}"
            failures.append(CoverageFailure(
                "malformed_descriptor_entry",
                f"descriptor {ident!r} has an absent/out-of-vocabulary risk_class {rc!r}; "
                f"known: {sorted(RISK_CLASSES)}"))
    return failures


def evaluate_coverage_gate(
    *,
    scan_violations: Sequence[Violation],
    descriptor_set: Sequence[Dict[str, Any]],
    contracts_map: Optional[Mapping[str, OperationContract]] = None,
) -> CoverageDecision:
    """Evaluate the descriptor-coverage gate deterministically. Returns a CoverageDecision;
    ``passed`` is True IFF no leg fires. Fail-closed everywhere (see module docstring).

    ``contracts_map`` defaults to the real ``contracts.OPERATION_CONTRACTS`` — the authoritative
    in-code enumeration of guarded mutators. It is injectable so tests can isolate a leg."""
    if contracts_map is None:
        contracts_map = OPERATION_CONTRACTS
    failures: List[CoverageFailure] = []

    # (a) Any bypass scan violation fails the gate — an external write outside the adapter
    # package is an unguarded/uncovered write path.
    for v in scan_violations:
        failures.append(CoverageFailure(
            "bypass_scan_violation", f"{v.path}:{v.lineno}: {v.kind}"))

    # Malformed-input guard (fail-closed) — must run before any join so a bad risk_class can
    # never be silently resolved into a covering entry.
    failures.extend(_validate_entries(descriptor_set))

    # (b)/(d) Demand side: every guarded mutator must have a DECLARED covering descriptor. This
    # gate does NOT check acceptance (B2-T1) — acceptance for live writes is runtime's job
    # (write_gate); a descriptor with accepted:false covers a mutator here just as well as one
    # with accepted:true.
    for op_kind in sorted(contracts_map):
        contract = contracts_map[op_kind]
        if not _is_guarded_mutator(contract):
            continue  # read_only_local / plain reversible_external ops need no descriptor
        rc = _effective_contract_risk_class(contract)
        if covering_declared_descriptor(rc, descriptor_set) is None:
            failures.append(CoverageFailure(
                "uncovered_mutator",
                f"guarded mutator {op_kind!r} (risk_class {rc!r}) has no covering DECLARED "
                "descriptor phase of that risk class — join MISS. A writer with no declared "
                "covering descriptor is never treated as covered."))

    return CoverageDecision(passed=not failures, failures=failures)


def run_coverage_gate(
    paths: Sequence[Union[str, Path]],
    descriptor_set_path: Optional[str] = None,
    allowed_root: Optional[Union[str, Path]] = None,
) -> CoverageDecision:
    """CLI-shaped helper: scan ``paths`` for bypasses (via the PURE ``scan_paths``), load the
    descriptor set fail-closed (via B1-4's accepted-descriptor loader — ``[]`` when
    absent/unreadable; unchanged for this task — B2-T2 will point the build-time loader at the
    declared-registry file specifically), read the real operation contracts, and evaluate the
    gate. This gate does not use the ``accepted`` field of any entry it loads. Mirrors scan.py's
    invocation shape."""
    violations = scan_paths(paths, allowed_root=allowed_root)
    descriptor_set = load_accepted_descriptor_set(descriptor_set_path)
    return evaluate_coverage_gate(
        scan_violations=violations, descriptor_set=descriptor_set)


# ---------------------------------------------------------------------------
# CLI entrypoint — run from its installed location inside the operator project so the
# __file__-anchored allowed-module exemption in scan_paths is correct.
#
# Usage:
#   python3 agents/lib/external_write/coverage_gate.py <path> [<path> ...] \
#       [--descriptor-set <path-to-accepted_descriptor_set.json>]
#
# Exits 0 if the gate passes (scan clean AND every guarded mutator covered by a DECLARED
# descriptor of the right risk class). ACCEPTANCE is NOT checked here — that is enforced at
# runtime by write_gate.
# Exits 1 and prints each failure if the gate fails (phase FAILS, fail-closed).
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _args = _sys.argv[1:]
    _descriptor_set_path: Optional[str] = None
    _paths: List[str] = []
    _i = 0
    while _i < len(_args):
        if _args[_i] == "--descriptor-set":
            if _i + 1 >= len(_args):
                print("Usage: coverage_gate.py <path> [...] [--descriptor-set <file>]",
                      file=_sys.stderr)
                _sys.exit(2)
            _descriptor_set_path = _args[_i + 1]
            _i += 2
        else:
            _paths.append(_args[_i])
            _i += 1

    if not _paths:
        print("Usage: coverage_gate.py <path> [...] [--descriptor-set <file>]",
              file=_sys.stderr)
        _sys.exit(2)

    _decision = run_coverage_gate(_paths, descriptor_set_path=_descriptor_set_path)
    if not _decision.passed:
        for _f in _decision.failures:
            print(f"{_f.kind}: {_f.detail}")
        print(
            f"\n{len(_decision.failures)} coverage failure(s). The descriptor-coverage gate "
            "FAILS: every guarded external mutator must be covered by a DECLARED, "
            "structurally-valid descriptor of the right risk class. (This gate does not check "
            "acceptance — a live write is only allowed to run once its covering descriptor is "
            "accepted, which write_gate enforces at runtime.) The build cannot proceed until "
            "every failure is resolved. (A missing/unreadable descriptor set fails closed — it "
            "never passes.)",
            file=_sys.stderr,
        )
        _sys.exit(1)
    else:
        print("Descriptor-coverage gate passed — every guarded mutator is covered by a "
              "declared descriptor phase of the right risk class. (Acceptance for live writes "
              "is enforced separately, at runtime, by write_gate.)")
        _sys.exit(0)
