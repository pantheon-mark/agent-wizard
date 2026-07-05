"""B1-4 — the deterministic pre-write gate: the runtime-enforcement heart of the safety
substrate.

`run_operation` (adapters.py) is the single chokepoint every external write passes through.
This module supplies the deterministic gate it runs BEFORE anything touches the
surface, making the design's core invariant mechanically true:

    No high-risk external action may run unless it is covered by a descriptor-declared,
    ACCEPTED phase — and until accepted, only against the declared test target (copy /
    bounded_sample / dry_run / native_undo), never live. An accepted phase authorizes only
    the declared bounded-test actions during build/supervised — it is NOT blanket live
    authorization.

THE OVERRIDING PROPERTY is fail-safe everywhere: a missing input (absent target signal,
absent/unreadable/malformed descriptor set, unknown/unclassified risk) must NEVER open the
gate. Every branch below defaults to refuse.

Design points settled from the code (see the B1-4 report):

  * Target signal — an explicit, machine-readable `target` argument threaded through
    run_operation, whose test-target vocabulary REUSES dependency_projection.TEST_TARGETS and
    whose copy value reuses copy_run_proof's copy-surface convention: an Operation whose
    surface is COPY_SURFACE ("copy_surface") is implicitly a copy target even with no explicit
    target. A declared test target is honored ONLY when the op physically targets a recognized
    test/copy surface (is_test_surface); a test-target claim on a live surface is refused (I1),
    because the target string is a caller assertion and the write lands on op.surface.
    For a gated op an ABSENT target (no arg + a non-copy surface) fails safe to refuse
    — the gate never defaults to live. Extending the Operation record was rejected: its
    canonical_repr / digest is hash-bound (broker receipts key off it) and a target is an
    execution-context signal, not part of the operation's approved identity.

  * Blast-radius counter — an injected in-memory InvocationLedger keyed on the capability
    (surface::op_kind). The "window" is the ledger instance's lifetime, owned by the caller
    (per-session / per-batch). For a live irreversible op an ABSENT ledger fails safe to
    refuse (the cap cannot be enforced without a counter). Recording happens at gate-permit
    time; over-counting on a later refusal is the SAFE direction for a blast-radius cap.

Vocabulary constants below are duplicated from wizard/scripts/lib/dependency_projection.py
(external_write cannot import the build-side tree — D-B1-a) and pinned equal by cross-tree
tests in test_external_write_write_gate.py, exactly as contracts.RISK_CLASSES is.

Stdlib only — no third-party dependencies.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from external_write.operations import Operation, Result
from external_write.contracts import OperationContract, get_contract


# ---------------------------------------------------------------------------
# Vocabulary (duplicated from dependency_projection.py; cross-tree-tested)
# ---------------------------------------------------------------------------

# The one risk class the gate must NEVER reach by silent fallback (design §4.5): an explicit
# read_only_local classification skips the gate; an ABSENT/unknown one never resolves here.
READ_ONLY_LOCAL = "read_only_local"

# F-28: an absent/unrecognized risk_class resolves to the MOST-protected class, never the safe
# one. Mirrors dependency_projection.FAIL_SAFE_RISK_CLASS / resolve_risk_class().
FAIL_SAFE_RISK_CLASS = "irreversible_external"

# The classes the gate treats as high-risk: acceptance + test-target required. Everything in the
# risk vocabulary except read_only_local (never gated) and reversible_external (already gated by
# the broker + copy_run_proof; the seeded status ops live here and stay ungated by B1-4).
GATED_RISK_CLASSES = frozenset({
    "irreversible_external", "standing_automation", "sensitive_data",
})

# The declared-test-target vocabulary (design §4.5/§4.7/§5.1), reused verbatim from
# dependency_projection.TEST_TARGETS. A gated op may run against any of these before acceptance.
TEST_TARGETS = frozenset({"copy", "bounded_sample", "dry_run", "native_undo"})

# The explicit live-target signal. A gated op must carry target=LIVE_TARGET affirmatively to
# even attempt a live write — it can never reach live by omission.
LIVE_TARGET = "live"

# copy_run_proof's copy-surface convention (copy_run_proof._synthetic_op). An Operation on this
# surface is inherently a copy target. Reusing it is why B1-4 introduces no parallel mechanism.
COPY_SURFACE = "copy_surface"

# The recognized bounded/copy/test surfaces (I1): physical surfaces a write can land on WITHOUT
# reaching the operator's live record. A declared test target (copy/bounded_sample/dry_run/
# native_undo) is a caller ASSERTION about intent; it is honored only when the op physically
# targets one of these surfaces — otherwise a caller could pass target="copy" on a live surface
# and the write would still hit the live record. The sole convention today is copy_run_proof's
# COPY_SURFACE; a real bounded_sample / dry_run surface is a B2 concern and must be added here
# EXPLICITLY (never inferred), exactly like the vocabulary constants above.
TEST_SURFACES = frozenset({COPY_SURFACE})


def is_test_surface(surface: Any) -> bool:
    """True iff `surface` is a recognized bounded/copy/test surface — one a write cannot use to
    reach the operator's live record. Deterministic and fail-safe: an unrecognized surface is
    NOT a test surface, so a claimed test target on it is refused (I1)."""
    return surface in TEST_SURFACES


# ---------------------------------------------------------------------------
# F-22: system clock — the single source of any date this module writes
# ---------------------------------------------------------------------------

def system_clock() -> datetime:
    """Return the current UTC time from the system clock. The gate NEVER accepts a
    model-authored / passed-in 'today' string; every timestamp it writes originates here (F-22).
    Injectable in run_operation via `clock=` for deterministic tests. Reusable by B1-7's
    date-site fold-in."""
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime) -> str:
    """ISO-8601 UTC with Z suffix (matches the receipt/broker timestamp format)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Fail-safe descriptor-set loader
# ---------------------------------------------------------------------------

# B2-T2: the project-root-relative path to the ONE descriptor-set file every emitted
# writes-back system carries (security/capability_descriptors.json). It holds the FULL
# descriptor set — every declared descriptor, `accepted` flags varying — not only the accepted
# ones; the prior name (ACCEPTED_DESCRIPTOR_SET_PATH) misled at a trust surface. BOTH gates read
# this SAME file: this module (write_gate, runtime) filters on `accepted: true` + surface match;
# the build-time coverage gate (coverage_gate.py) ignores `accepted` entirely and checks only
# DECLARATION. The loader's `open(path)` resolves against cwd — both the coverage-gate CLI and
# agent invocations run from the operator project root (see coverage_gate.py's CLI docstring and
# the project's operating rule that agents run from project root), so this project-root-relative
# path resolves correctly from either caller.
DESCRIPTOR_SET_PATH: Optional[str] = "security/capability_descriptors.json"


def load_descriptor_set(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load the machine-readable descriptor set (B1-2 render_descriptor_registry_json shape: a
    JSON array of entries with id/name/action_class/risk_class/recovery_profile_ref/
    declared_test_target/blast_radius_cap/accepted). Holds the FULL set — every declared
    descriptor, `accepted` flags varying; write_gate filters on `accepted: true` (+ surface
    match) below, the build-time coverage gate ignores `accepted` entirely.

    FAIL-SAFE by construction: any missing input — no path configured, absent file, unreadable
    file, malformed JSON, or a non-array payload — returns [] (nothing accepted/declared), so a
    live gated op is refused. It NEVER raises and NEVER treats an unreadable set as permissive."""
    if path is None:
        path = DESCRIPTOR_SET_PATH
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return data


# ---------------------------------------------------------------------------
# Blast-radius invocation ledger (deterministic counter, outside the LLM)
# ---------------------------------------------------------------------------

class InvocationLedger:
    """A simple in-memory invocation counter — the deterministic blast-radius window.

    The window is this instance's lifetime: the caller owns it (a per-session or per-batch
    ledger gives a per-session / per-batch window). Keyed on the capability (surface::op_kind).
    Deliberately below the LLM: no model text can move these counts."""

    def __init__(self) -> None:
        self._counts: Dict[str, int] = {}

    def count(self, key: str) -> int:
        return self._counts.get(key, 0)

    def record(self, key: str) -> None:
        self._counts[key] = self.count(key) + 1


# ---------------------------------------------------------------------------
# Gate decision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GateDecision:
    """Outcome of the pre-write gate.

    permitted: True iff the op may proceed to receipt validation + write.
    refusal:   the Result to return immediately when not permitted (never None if not permitted).
    audit:     a dict to merge into the final 'written' Result.detail on success (e.g. the
               irreversibility acknowledgement); None for ops that write no audit record.
    """
    permitted: bool
    refusal: Optional[Result] = None
    audit: Optional[Dict[str, Any]] = None


_PERMIT = GateDecision(permitted=True)


def _refuse(reason: str, **extra: Any) -> GateDecision:
    detail: Dict[str, Any] = {"reason": reason, "gate": "write_gate_v1"}
    detail.update(extra)
    return GateDecision(permitted=False, refusal=Result(status="refused", detail=detail))


def _effective_risk_class(contract: Optional[OperationContract]) -> str:
    """F-28: an op with no contract, or a contract whose risk_class is not in the known
    vocabulary, resolves to the MOST-protected class — never read_only_local by omission."""
    if contract is None:
        return FAIL_SAFE_RISK_CLASS
    rc = contract.risk_class
    known = GATED_RISK_CLASSES | {READ_ONLY_LOCAL, "reversible_external"}
    if isinstance(rc, str) and rc in known:
        return rc
    return FAIL_SAFE_RISK_CLASS


def _resolve_target(op: Operation, target: Optional[str]) -> Optional[str]:
    """Resolve the machine-readable target signal. Reuses copy_run_proof's copy-surface
    convention (surface==COPY_SURFACE => implicit 'copy'). Returns None when the signal is
    ABSENT (no explicit arg and not a copy surface) — the caller fails that safe to refuse."""
    if op.surface == COPY_SURFACE:
        return "copy"
    return target


def _covering_entry(descriptor_set: Sequence[Dict[str, Any]], op: Operation,
                    risk_class: str) -> Optional[Dict[str, Any]]:
    """Return the first accepted descriptor entry that COVERS this op, or None.

    Covering requires all of: accepted is exactly True; the entry's capability id or name
    matches the op's surface (the deterministic op->capability join); and the entry's declared
    risk_class equals the op's effective risk_class (an acceptance recorded at a different risk
    level does not cover). Anything short of a full match => not covered => refuse live."""
    for e in descriptor_set:
        if not isinstance(e, dict):
            continue
        if e.get("accepted") is not True:
            continue
        if e.get("id") != op.surface and e.get("name") != op.surface:
            continue
        if e.get("risk_class") != risk_class:
            continue
        return e
    return None


def _effective_cap(contract: Optional[OperationContract],
                   covering: Optional[Dict[str, Any]]) -> Optional[int]:
    """Effective blast-radius cap = the SMALLEST of the caps present (the per-capability
    descriptor cap may override the contract default DOWNWARD, never upward — B1-3). Returns
    None only when neither a contract cap nor a descriptor cap is set."""
    caps: List[int] = []
    if contract is not None and isinstance(contract.blast_radius_cap, int) \
            and not isinstance(contract.blast_radius_cap, bool):
        caps.append(contract.blast_radius_cap)
    if covering is not None:
        dc = covering.get("blast_radius_cap")
        if isinstance(dc, int) and not isinstance(dc, bool):
            caps.append(dc)
    return min(caps) if caps else None


def _ledger_key(op: Operation) -> str:
    return f"{op.surface}::{op.op_kind}"


def evaluate_write_gate(op: Operation, *, target: Optional[str] = None,
                        descriptor_set: Optional[Sequence[Dict[str, Any]]] = None,
                        cap_ledger: Optional[InvocationLedger] = None,
                        clock: Optional[Any] = None) -> GateDecision:
    """The deterministic pre-write gate. Returns a GateDecision; the caller returns the refusal
    immediately when not permitted, and merges `audit` into the success Result otherwise.

    Order (each step fails safe):
      1. Resolve the contract + effective risk class (F-28 fail-safe classification).
      2. read_only_local => never trips (design §4.5): permit untouched.
      3. Not gated (reversible_external, ungated) => permit untouched (byte-identical to pre-B1-4).
      4. Gated => resolve target: absent => refuse; a recognized test target ON a recognized
         test/copy surface => permit (bounded test, no acceptance/cap needed — no live blast
         radius); a test target on a live surface => refuse (I1 — the target claim must bind to
         the write surface); live => require a covering accepted entry, then the recovery floor
         (F-29) and the blast-radius cap.
    """
    if clock is None:
        clock = system_clock

    contract = get_contract(op.op_kind)
    risk_class = _effective_risk_class(contract)

    # (2) read_only_local NEVER trips — but ONLY when explicitly classified so (F-28: an absent
    # risk_class resolved to FAIL_SAFE_RISK_CLASS above, so it can never reach this branch).
    if risk_class == READ_ONLY_LOCAL:
        return _PERMIT

    # (3) Is this op gated at all?  Unknown/uncovered writer (no contract) is gated (F-28);
    # any GATED_RISK_CLASSES member is gated; an explicit requires_accepted_phase is gated.
    gated = (
        contract is None
        or risk_class in GATED_RISK_CLASSES
        or bool(getattr(contract, "requires_accepted_phase", False))
    )
    if not gated:
        return _PERMIT

    # (4) Gated path — target resolution first.
    resolved = _resolve_target(op, target)
    if resolved is None:
        return _refuse(
            "gated operation refused: no target signal — a high-risk op must declare its "
            "target (a declared test target, or an affirmative live target); it never "
            "defaults to live",
            op_kind=op.op_kind, risk_class=risk_class)

    if resolved in TEST_TARGETS:
        # I1: a declared test target is a caller ASSERTION; it is honored ONLY when the op's
        # surface is a recognized test/copy surface. A test target claimed on a live (non-test)
        # surface must NOT permit — client.write would otherwise hit the live record. Fail-safe:
        # bind the target claim to where the write physically lands.
        if not is_test_surface(op.surface):
            return _refuse(
                f"gated operation refused: target {resolved!r} is a declared test target but "
                f"the surface {op.surface!r} is not a recognized test/copy surface — a "
                "test-target claim on a live surface is never honored (the write would hit the "
                "live record). Route the operation to a copy/bounded test surface, or declare "
                f"the affirmative live target and satisfy the accepted-phase gate.",
                op_kind=op.op_kind, risk_class=risk_class, surface=op.surface)
        # Bounded test against a recognized test/copy surface — always allowed, acceptance-
        # independent, no live blast radius, so no cap and no ledger required.
        return _PERMIT

    if resolved != LIVE_TARGET:
        return _refuse(
            f"gated operation refused: unrecognized target {resolved!r}; must be {LIVE_TARGET!r} "
            f"or a declared test target ({sorted(TEST_TARGETS)})",
            op_kind=op.op_kind)

    # resolved == LIVE_TARGET — require a covering ACCEPTED descriptor phase.
    ds = load_descriptor_set() if descriptor_set is None else descriptor_set
    covering = _covering_entry(ds, op, risk_class)
    if covering is None:
        return _refuse(
            "live target refused: no covering ACCEPTED descriptor phase for this capability at "
            f"risk_class {risk_class!r} — run against the declared test target until a covering "
            "phase is accepted; an accepted phase authorizes only the declared bounded-test "
            "actions, never blanket live mutation",
            op_kind=op.op_kind, risk_class=risk_class)

    # F-29 recovery floor — NON-GRADUATING for standing_automation: a live standing_automation
    # op requires a recovery profile on its covering entry, and NO autonomy/maturity signal can
    # waive it (there is no such parameter on this gate — the floor is structural, not narrated).
    if risk_class == "standing_automation":
        ref = covering.get("recovery_profile_ref")
        if not (isinstance(ref, str) and ref.strip()):
            return _refuse(
                "live standing_automation refused: the non-graduating recovery floor is not "
                "satisfied — the covering accepted entry declares no recovery_profile_ref (a "
                "backup/recover path). Maturity graduates supervision, never this safety net.",
                op_kind=op.op_kind, risk_class=risk_class)

    # Blast-radius cap — deterministic, outside the LLM. Mandatory for irreversible ops; also
    # enforced for any gated class that carries an effective cap.
    effective_cap = _effective_cap(contract, covering)
    cap_required = (risk_class == FAIL_SAFE_RISK_CLASS) or (effective_cap is not None)
    audit: Optional[Dict[str, Any]] = None
    if cap_required:
        if effective_cap is None:
            return _refuse(
                "live irreversible op refused: no blast-radius cap could be determined (neither "
                "a contract default nor a per-capability descriptor cap). An unbounded "
                "irreversible action is never permitted.",
                op_kind=op.op_kind, risk_class=risk_class)
        if cap_ledger is None:
            return _refuse(
                "live irreversible op refused: no invocation ledger supplied, so the "
                f"blast-radius cap ({effective_cap}) cannot be enforced. Refusing rather than "
                "running an untracked irreversible action.",
                op_kind=op.op_kind, risk_class=risk_class, blast_radius_cap=effective_cap)
        key = _ledger_key(op)
        if cap_ledger.count(key) >= effective_cap:
            return _refuse(
                f"live irreversible op refused: blast-radius cap of {effective_cap} reached for "
                f"this capability in the current window (irreversible actions never batch).",
                op_kind=op.op_kind, risk_class=risk_class, blast_radius_cap=effective_cap)
        cap_ledger.record(key)

        # F-22 + design §4.7: a live irreversible action writes an explicit, clock-stamped
        # "this cannot be reversed" acknowledgement. The timestamp comes from the clock, NEVER
        # a passed-in string.
        if risk_class == FAIL_SAFE_RISK_CLASS:
            audit = {
                "irreversibility_acknowledgement": {
                    "reversible": False,
                    "note": "This action cannot be reversed.",
                    "op_kind": op.op_kind,
                    "blast_radius_cap": effective_cap,
                    "invocation_index": cap_ledger.count(key),  # 1-based (post-record)
                    "recorded_at": _iso_z(clock()),
                }
            }

    return GateDecision(permitted=True, audit=audit)
