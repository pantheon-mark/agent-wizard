"""The RunEnvelope primitive — the persisted approval-run manifest (Task 4, A1
— v0.12.0 Slice 1, design §0), plus the envelope-driven run path that threads
the read-only client and records per-unit verification into ``tranches[]``.

Why this exists
---------------
A live MULTI-UNIT run (a bulk whittle across chunks / a regenerated loop / a
crash-and-restart) has safety-critical run state that the "bulk op_kind" shape
left homeless: the frozen reviewed candidate set, the aggregate blast-radius
ceiling, the operator consent, and the verification trail. The RunEnvelope is
the single home for that state, persisted under the operator project. A live
run may not proceed without a spendable envelope.

I1 — SOLE-MINTER (the trust core)
---------------------------------
An APPROVED envelope with SPENDABLE budget may be minted ONLY by
``mint_run_envelope`` — the consent-ceremony entry point — exactly as
``acceptance_ceremony.accept_capability_for_live_use`` is the sole hash-bound
writer of ``accepted: true``. The mechanism that makes this hold against
GENERATED LOOP CODE (which could otherwise fabricate a fresh ``run_id`` to
escape an exhausted budget):

  * Spendable budget lives ONLY in an envelope FILE the ceremony wrote, keyed
    by ``run_id``. ``load_run_envelope`` for a caller-chosen / fabricated
    ``run_id`` finds no file and returns the EMPTY envelope (0 budget, no frozen
    reviewed set) — fail-closed at the gate.
  * The gate/run path uses the DISK envelope's budget + the DISK ledger count,
    never an in-memory object a caller hands it — so constructing a
    ``RunEnvelope`` with fake budget in memory buys nothing.
  * On load, the envelope is RE-VALIDATED for internal consistency
    (``is_spendable``): the ``reviewed_set_digest`` must recompute over the
    frozen ``reviewed_set``; the consent must be present, non-empty, and bound
    to that digest; the ceiling must grant a positive budget; and the stored
    ``ledger_window_id`` must equal the value DERIVED from the verified
    identity. A hand-fabricated envelope that skips the ceremony cannot satisfy
    all of these without effectively replaying it (which needs the operator's
    real "yes").
  * ``ledger_window_id`` is a DERIVED property (``derive_ledger_window_id`` over
    run_id + capability + op_kind + hashes + reviewed_set_digest), never the
    mutable stored field — a tampered stored value is detected and voids
    spendability.

Enforcement ceiling (unchanged, disclosed): build-time + operator-as-approver,
NOT a runtime or OS-level guarantee. Like ``acceptance_ceremony``, this is the
sole LEGITIMATE minter and re-validates everything on load; it makes no claim of
tamper-proofness against a deliberate operator hand-edit of the trust file.

Emission (forward obligation): this runs at operator-side run time, so it must
be emitted into operator systems. A later slice-close step must add
``run_envelope.py`` (and ``bounds.py``) to ``agent_emitter._EXTERNAL_WRITE_LIB_
FILES`` + the foundation bundle — NOT wired here (CANONICAL-ONLY), mirroring the
``acceptance_ceremony.py`` emission note.

Stdlib only — no third-party dependencies.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# sys.path bootstrap (mirrors acceptance_ceremony.py): make the package parent
# importable when run as a direct script from the project root.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.bounds import (
    DEFAULT_KNOB_B_FLOOR,
    DEFAULT_SAMPLE_PERCENT,
    FAIL_SAFE_RECOVERY_TIER,
    absolute_cap_for_risk_class,
    knob_b_ceiling,
    recovery_tier_for_risk_class,
)
from external_write.contracts import get_contract
from external_write.operations import Result
from external_write.write_gate import DEFAULT_LEDGER_DIR, PersistentInvocationLedger

# Schema tag for the persisted envelope.
RUN_ENVELOPE_SCHEMA = "run_envelope-v1"

# Project-root-relative home for persisted run envelopes (disk-first + audit).
DEFAULT_ENVELOPE_DIR = "security/run_envelopes"

# I-3: the persistent-ledger key under which the envelope's AGGREGATE Knob B
# ceiling (``ceiling.granted_this_approval``) is enforced across the whole run.
# It is deliberately NOT of the form ``surface::op_kind`` (the per-op gate key),
# so the aggregate bound and the per-op cap occupy DISTINCT slots in the same
# per-window ledger file and compose — neither masks the other. This bound is
# enforced for EVERY op_kind regardless of the write gate's risk-class gating, so
# a reversible bulk run (which the gate does not cap) is still bounded.
AGGREGATE_LEDGER_KEY = "__run_envelope_aggregate__"


# ---------------------------------------------------------------------------
# Digest / identity derivation (never a trusted stored field)
# ---------------------------------------------------------------------------

def compute_reviewed_set_digest(reviewed_set: Any) -> str:
    """Deterministic digest over the FROZEN reviewed candidate set. Sorted-key
    JSON over the ordered list of entries, so the digest is independent of dict
    insertion order but bound to entry ORDER + content."""
    normalized: List[Dict[str, Any]] = [dict(e) for e in (reviewed_set or [])]
    canon = json.dumps(normalized, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canon.encode()).hexdigest()


def derive_ledger_window_id(*, run_id: str, capability_id: str, op_kind: str,
                            contract_hash: str, implementation_hash: str,
                            reviewed_set_digest: str) -> str:
    """DERIVE the persistent blast-radius window id from the verified envelope
    identity. Never read from a mutable stored field — an envelope whose stored
    ``ledger_window_id`` disagrees with this is not spendable (I1)."""
    canon = json.dumps(
        {
            "run_id": run_id,
            "capability_id": capability_id,
            "op_kind": op_kind,
            "contract_hash": contract_hash,
            "implementation_hash": implementation_hash,
            "reviewed_set_digest": reviewed_set_digest,
        },
        sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canon.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Envelope sub-structures (design §0)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ceiling:
    """The aggregate blast-radius budget for one approval (Knob B, §3)."""
    granted_this_approval: int
    remaining_budget: int
    absolute_cap: int
    recovery_tier: str


@dataclass(frozen=True)
class Consent:
    """The operator consent record. ``approval_bound_to`` binds the operator's
    verbatim approval to the frozen ``reviewed_set_digest`` (the manifest
    digest/cap live in the receipt; the operator-facing sentence is Task 6)."""
    operator_approval_verbatim: str
    consent_sentence_shown: str
    approved_at: str
    approval_bound_to: str


@dataclass(frozen=True)
class Tranche:
    """One applied tranche's record: which units were applied, the per-unit
    result + verification, the aggregate verification status, and the prior
    tranche's restore result (progressive-tranche gating, §3)."""
    applied_unit_ids: Tuple[str, ...]
    per_unit_result: Dict[str, Any]
    verification_status: str
    restore_verified: Optional[bool] = None


@dataclass(frozen=True)
class RunEnvelope:
    """The persisted approval-run manifest (design §0). Above ``Operation``.

    ``ledger_window_id`` is intentionally NOT a plain stored field: the raw
    stored value is kept only for tamper-detection (``stored_ledger_window_id``);
    the authoritative value is the DERIVED ``ledger_window_id`` property."""

    run_id: str
    capability_id: str
    op_kind: str
    contract_hash: str
    implementation_hash: str
    reviewed_set: Tuple[Dict[str, Any], ...]
    reviewed_set_digest: str
    population_count: int
    stratification_summary: Dict[str, Any]
    ceiling: Optional[Ceiling]
    consent: Optional[Consent]
    evidence_policy: Dict[str, Any]
    tranches: Tuple[Tranche, ...]
    stored_ledger_window_id: str = ""

    @property
    def ledger_window_id(self) -> str:
        """The DERIVED window id (never the stored field)."""
        return derive_ledger_window_id(
            run_id=self.run_id, capability_id=self.capability_id,
            op_kind=self.op_kind, contract_hash=self.contract_hash,
            implementation_hash=self.implementation_hash,
            reviewed_set_digest=self.reviewed_set_digest)

    def is_spendable(self) -> bool:
        """True IFF this envelope is an internally-consistent, ceremony-shaped,
        approved manifest with a positive budget. Every check defaults to
        refuse — an empty / fabricated / tampered / budgetless envelope is not
        spendable (I1, fail-closed)."""
        if not self.reviewed_set:
            return False
        if self.reviewed_set_digest != compute_reviewed_set_digest(self.reviewed_set):
            return False
        if self.consent is None:
            return False
        verbatim = self.consent.operator_approval_verbatim
        if not (isinstance(verbatim, str) and verbatim.strip()):
            return False
        if self.consent.approval_bound_to != self.reviewed_set_digest:
            return False
        if self.ceiling is None or self.ceiling.granted_this_approval <= 0:
            return False
        # C1: the stored window id must be PRESENT and equal the derived value.
        # A minted envelope always persists the derived id, so an EMPTY stored
        # value can no longer short-circuit this check to "spendable" — it fails
        # closed (a hand-built envelope that leaves it blank is refused), and a
        # tampered value that disagrees with the derived one is refused too.
        if not self.stored_ledger_window_id:
            return False
        if self.stored_ledger_window_id != self.ledger_window_id:
            return False
        return True

    def remaining_budget(self) -> int:
        """The granted aggregate budget (0 when not spendable). Dynamic
        consumption is tracked by the persistent ledger keyed by
        ``ledger_window_id``, not decremented on this field."""
        if not self.is_spendable() or self.ceiling is None:
            return 0
        return self.ceiling.remaining_budget


# ---------------------------------------------------------------------------
# (De)serialization
# ---------------------------------------------------------------------------

def _empty_envelope(run_id: str) -> RunEnvelope:
    """The fail-closed EMPTY envelope: 0 budget, no frozen reviewed set. Returned
    for a fabricated / absent / malformed envelope (I1, fail-closed)."""
    return RunEnvelope(
        run_id=run_id if isinstance(run_id, str) else "",
        capability_id="", op_kind="", contract_hash="", implementation_hash="",
        reviewed_set=(), reviewed_set_digest="", population_count=0,
        stratification_summary={},
        ceiling=Ceiling(0, 0, 0, FAIL_SAFE_RECOVERY_TIER),
        consent=None, evidence_policy={}, tranches=(), stored_ledger_window_id="")


def _to_disk_dict(env: RunEnvelope) -> Dict[str, Any]:
    return {
        "schema": RUN_ENVELOPE_SCHEMA,
        "run_id": env.run_id,
        "capability_id": env.capability_id,
        "op_kind": env.op_kind,
        "contract_hash": env.contract_hash,
        "implementation_hash": env.implementation_hash,
        "reviewed_set": [dict(e) for e in env.reviewed_set],
        "reviewed_set_digest": env.reviewed_set_digest,
        "population_count": env.population_count,
        "stratification_summary": dict(env.stratification_summary),
        "ceiling": None if env.ceiling is None else {
            "granted_this_approval": env.ceiling.granted_this_approval,
            "remaining_budget": env.ceiling.remaining_budget,
            "absolute_cap": env.ceiling.absolute_cap,
            "recovery_tier": env.ceiling.recovery_tier,
        },
        "consent": None if env.consent is None else {
            "operator_approval_verbatim": env.consent.operator_approval_verbatim,
            "consent_sentence_shown": env.consent.consent_sentence_shown,
            "approved_at": env.consent.approved_at,
            "approval_bound_to": env.consent.approval_bound_to,
        },
        "evidence_policy": dict(env.evidence_policy),
        # Persist the DERIVED window id (tamper-detected on load).
        "ledger_window_id": env.ledger_window_id,
        "tranches": [
            {
                "applied_unit_ids": list(t.applied_unit_ids),
                "per_unit_result": t.per_unit_result,
                "verification_status": t.verification_status,
                "restore_verified": t.restore_verified,
            }
            for t in env.tranches
        ],
    }


def _from_disk_dict(raw: Dict[str, Any], run_id: str) -> RunEnvelope:
    """Build a RunEnvelope from a parsed disk dict. Tolerant of missing keys —
    a missing/blank field simply leaves the envelope non-spendable via
    ``is_spendable`` (never raises, never treats a malformed field as valid)."""
    ceiling_raw = raw.get("ceiling")
    ceiling = None
    if isinstance(ceiling_raw, dict):
        try:
            ceiling = Ceiling(
                granted_this_approval=int(ceiling_raw.get("granted_this_approval", 0)),
                remaining_budget=int(ceiling_raw.get("remaining_budget", 0)),
                absolute_cap=int(ceiling_raw.get("absolute_cap", 0)),
                recovery_tier=str(ceiling_raw.get("recovery_tier", FAIL_SAFE_RECOVERY_TIER)),
            )
        except (TypeError, ValueError):
            ceiling = None

    consent_raw = raw.get("consent")
    consent = None
    if isinstance(consent_raw, dict):
        consent = Consent(
            operator_approval_verbatim=str(consent_raw.get("operator_approval_verbatim", "")),
            consent_sentence_shown=str(consent_raw.get("consent_sentence_shown", "")),
            approved_at=str(consent_raw.get("approved_at", "")),
            approval_bound_to=str(consent_raw.get("approval_bound_to", "")),
        )

    reviewed_set_raw = raw.get("reviewed_set")
    reviewed_set: Tuple[Dict[str, Any], ...] = tuple(
        e for e in reviewed_set_raw if isinstance(e, dict)) \
        if isinstance(reviewed_set_raw, list) else ()

    tranches_raw = raw.get("tranches")
    tranches: List[Tranche] = []
    if isinstance(tranches_raw, list):
        for t in tranches_raw:
            if not isinstance(t, dict):
                continue
            tranches.append(Tranche(
                applied_unit_ids=tuple(t.get("applied_unit_ids") or ()),
                per_unit_result=t.get("per_unit_result") or {},
                verification_status=str(t.get("verification_status", "")),
                restore_verified=t.get("restore_verified"),
            ))

    return RunEnvelope(
        run_id=str(raw.get("run_id", run_id)),
        capability_id=str(raw.get("capability_id", "")),
        op_kind=str(raw.get("op_kind", "")),
        contract_hash=str(raw.get("contract_hash", "")),
        implementation_hash=str(raw.get("implementation_hash", "")),
        reviewed_set=reviewed_set,
        reviewed_set_digest=str(raw.get("reviewed_set_digest", "")),
        population_count=int(raw.get("population_count", 0))
        if isinstance(raw.get("population_count", 0), int) else 0,
        stratification_summary=raw.get("stratification_summary") or {},
        ceiling=ceiling,
        consent=consent,
        evidence_policy=raw.get("evidence_policy") or {},
        tranches=tuple(tranches),
        stored_ledger_window_id=str(raw.get("ledger_window_id", "")),
    )


def _safe_run_id(run_id: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in run_id)


def _envelope_path(run_id: str, envelope_dir: Optional[str]) -> str:
    directory = envelope_dir if envelope_dir else DEFAULT_ENVELOPE_DIR
    return os.path.join(directory, f"{_safe_run_id(run_id)}.json")


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".run_envelope.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def load_run_envelope(run_id: str, *, envelope_dir: Optional[str] = None) -> RunEnvelope:
    """Load the persisted envelope for ``run_id``. FAIL-CLOSED: an absent /
    unreadable / malformed file returns the EMPTY envelope (0 budget) — never a
    permissive one. Spendability is re-validated by ``is_spendable`` (I1)."""
    if not (isinstance(run_id, str) and run_id):
        return _empty_envelope(run_id if isinstance(run_id, str) else "")
    path = _envelope_path(run_id, envelope_dir)
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return _empty_envelope(run_id)
    if not isinstance(raw, dict):
        return _empty_envelope(run_id)
    return _from_disk_dict(raw, run_id)


# ---------------------------------------------------------------------------
# I1 — the SOLE minter of a spendable approved envelope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MintResult:
    accepted: bool
    reason: Optional[str] = None
    envelope_ref: Optional[str] = None
    envelope: Optional[RunEnvelope] = None


def _mint_refuse(reason: str) -> MintResult:
    return MintResult(accepted=False, reason=reason)


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mint_run_envelope(
    *,
    run_id: str,
    capability_id: str,
    op_kind: str,
    contract_hash: str,
    implementation_hash: str,
    reviewed_set: Any,
    population_count: int,
    stratification_summary: Optional[Dict[str, Any]] = None,
    operator_approval_verbatim: str,
    consent_sentence_shown: str,
    approved_at: Optional[str] = None,
    evidence_policy: Optional[Dict[str, Any]] = None,
    envelope_dir: Optional[str] = None,
    sample_percent: float = DEFAULT_SAMPLE_PERCENT,
    floor: int = DEFAULT_KNOB_B_FLOOR,
) -> MintResult:
    """Mint an APPROVED, spendable RunEnvelope and persist it atomically — the
    SOLE minter (I1). Fail-safe: any missing / ambiguous / empty input refuses
    and writes nothing spendable.

    The ceiling is computed by Knob B (``bounds.knob_b_ceiling``) from the
    frozen ``population_count`` and the op_kind's contract risk class; the
    ``ledger_window_id`` is DERIVED from the verified identity; the consent is
    bound to the ``reviewed_set_digest``. (The machine-generated consent SENTENCE
    is Task 6 and apply-by-id enforcement is Task 5 — this mints the manifest.)"""
    for name, val in (("run_id", run_id), ("capability_id", capability_id),
                      ("op_kind", op_kind), ("contract_hash", contract_hash),
                      ("implementation_hash", implementation_hash)):
        if not (isinstance(val, str) and val.strip()):
            return _mint_refuse(f"missing / empty {name}")

    if not (isinstance(reviewed_set, (list, tuple)) and len(reviewed_set) > 0):
        return _mint_refuse(
            "reviewed_set is empty — a spendable envelope needs a frozen "
            "reviewed candidate set")
    if not all(isinstance(e, dict) for e in reviewed_set):
        return _mint_refuse("reviewed_set entries must be mappings")

    # Honest capture: an empty operator "yes" is not consent (mirrors
    # operator_acceptance.record_operator_acceptance).
    if not (isinstance(operator_approval_verbatim, str) and operator_approval_verbatim.strip()):
        return _mint_refuse(
            "operator confirmation is empty — the operator has not confirmed; "
            "nothing minted, nothing spendable")

    if not (isinstance(population_count, int) and not isinstance(population_count, bool)
            and population_count >= 0):
        return _mint_refuse("population_count must be a non-negative integer")

    contract = get_contract(op_kind)
    if contract is None:
        return _mint_refuse(
            f"op_kind {op_kind!r} has no registered contract — cannot resolve a "
            "recovery tier / ceiling")
    risk_class = contract.risk_class

    granted = knob_b_ceiling(population_count, risk_class,
                             sample_percent=sample_percent, floor=floor)
    if granted <= 0:
        return _mint_refuse(
            f"Knob B ceiling resolved to 0 for population {population_count} — "
            "nothing to authorize")

    ceiling = Ceiling(
        granted_this_approval=granted,
        remaining_budget=granted,
        absolute_cap=absolute_cap_for_risk_class(risk_class),
        recovery_tier=recovery_tier_for_risk_class(risk_class),
    )

    reviewed_set_tuple: Tuple[Dict[str, Any], ...] = tuple(dict(e) for e in reviewed_set)
    reviewed_set_digest = compute_reviewed_set_digest(reviewed_set_tuple)

    consent = Consent(
        operator_approval_verbatim=operator_approval_verbatim,
        consent_sentence_shown=consent_sentence_shown if isinstance(consent_sentence_shown, str) else "",
        approved_at=approved_at if approved_at else _now_iso_z(),
        approval_bound_to=reviewed_set_digest,
    )

    env = RunEnvelope(
        run_id=run_id,
        capability_id=capability_id,
        op_kind=op_kind,
        contract_hash=contract_hash,
        implementation_hash=implementation_hash,
        reviewed_set=reviewed_set_tuple,
        reviewed_set_digest=reviewed_set_digest,
        population_count=population_count,
        stratification_summary=dict(stratification_summary or {}),
        ceiling=ceiling,
        consent=consent,
        evidence_policy=dict(evidence_policy or {"predicate_version": None,
                                                 "verification_mode": None}),
        tranches=(),
        stored_ledger_window_id="",  # never trusted; the property derives it
    )

    path = _envelope_path(run_id, envelope_dir)
    try:
        _atomic_write_json(path, _to_disk_dict(env))
    except Exception as e:
        return _mint_refuse(f"could not persist the run envelope; nothing minted: {e}")

    # Re-load from disk so the returned envelope carries the persisted
    # (derived) ledger_window_id and matches exactly what any consumer will see.
    loaded = load_run_envelope(run_id, envelope_dir=envelope_dir)
    return MintResult(accepted=True, envelope_ref=path, envelope=loaded)


# ---------------------------------------------------------------------------
# Tranche recording + the envelope-driven run path
# ---------------------------------------------------------------------------

def append_tranche(env: RunEnvelope, tranche: Tranche, *,
                   envelope_dir: Optional[str] = None) -> RunEnvelope:
    """Append a tranche record to the envelope and persist it atomically.
    Returns the updated envelope."""
    updated = RunEnvelope(
        run_id=env.run_id, capability_id=env.capability_id, op_kind=env.op_kind,
        contract_hash=env.contract_hash, implementation_hash=env.implementation_hash,
        reviewed_set=env.reviewed_set, reviewed_set_digest=env.reviewed_set_digest,
        population_count=env.population_count,
        stratification_summary=env.stratification_summary,
        ceiling=env.ceiling, consent=env.consent,
        evidence_policy=env.evidence_policy,
        tranches=env.tranches + (tranche,),
        stored_ledger_window_id=env.stored_ledger_window_id,
    )
    _atomic_write_json(_envelope_path(env.run_id, envelope_dir), _to_disk_dict(updated))
    return updated


def _tranche_from_result(result: Result) -> Tranche:
    """Build a tranche record from a run_operation Result's verification detail.
    Honest: absent/partial verification records ``applied_not_verified``, never
    ``verified`` (mirrors Task 3's `_verify_applied_units`)."""
    detail = result.detail if isinstance(result.detail, dict) else {}
    verification = detail.get("verification") if isinstance(detail, dict) else None
    if not isinstance(verification, dict):
        return Tranche(applied_unit_ids=(), per_unit_result={},
                       verification_status="applied_not_verified", restore_verified=None)
    per_unit = verification.get("per_unit") if isinstance(verification.get("per_unit"), dict) else {}
    applied_ids = tuple(per_unit.keys())
    verified_count = verification.get("verified_count", 0)
    unverified_count = verification.get("applied_not_verified_count", 0)
    status = "verified" if (unverified_count == 0 and isinstance(verified_count, int)
                            and verified_count > 0) else "applied_not_verified"
    return Tranche(applied_unit_ids=applied_ids, per_unit_result=per_unit,
                   verification_status=status, restore_verified=None)


def run_enveloped_operation(
    envelope: RunEnvelope,
    op: Any,
    receipt: Any,
    client: Any,
    *,
    read_only_client: Any = None,
    cap_ledger: Optional[PersistentInvocationLedger] = None,
    descriptor_set: Any = None,
    clock: Any = None,
    target: str = "live",
    envelope_dir: Optional[str] = None,
    ledger_dir: Optional[str] = None,
) -> Tuple[RunEnvelope, Result]:
    """Run one operation UNDER an approved envelope, counting against the
    persistent ledger keyed by the envelope's derived ``ledger_window_id`` and
    recording the per-unit verification into ``tranches[]``.

    C1 — DISK-AUTHORITATIVE: the passed ``envelope`` is NEVER trusted for its
    spendability. Every input ``is_spendable`` checks is caller-computable
    (``reviewed_set_digest``, ``consent.approval_bound_to``, ``ceiling``, and the
    derivable ``ledger_window_id``), so generated loop code could hand-build a
    spendable-LOOKING envelope with a FRESH ``run_id`` to escape an exhausted
    budget. To close that, this reloads the persisted envelope via
    ``load_run_envelope(envelope.run_id)`` and enforces ``is_spendable`` on the
    DISK object — a ``run_id`` never minted to disk loads EMPTY (0 budget) and is
    refused. This mirrors the write gate reading acceptance from disk
    (``load_descriptor_set``) rather than trusting an in-memory flag.

    I-3 — AGGREGATE CEILING: before applying, the op's planned unit count is
    reserved atomically against ``ceiling.granted_this_approval`` on the
    persistent ledger (key ``AGGREGATE_LEDGER_KEY``). This aggregate bound is
    enforced for EVERY op_kind regardless of the write gate's per-op gating, and
    composes WITH the per-op cap (both count against the same per-window ledger
    in distinct slots; neither masks the other) — so a reversible bulk run, which
    the gate does not cap, is still bounded. If the reservation would exceed the
    granted budget the run refuses (require re-confirm), applying nothing.

    This also closes the Task 3 carry-forward (broker.py:128): ``read_only_client``
    is THREADED straight into ``run_operation`` so Task 3's ``_verify_applied_units``
    runs a real-surface check on envelope-driven ops. Credential isolation is
    preserved — the read-only client is passed ONLY as ``run_operation``'s
    ``read_only_client`` argument, never as the write ``client``.

    Returns ``(updated_envelope, result)``. On any refusal the returned envelope
    is the disk-authoritative one (or the empty envelope), and no tranche is
    appended."""
    # C1: reload and enforce spendability on the DISK object, never the passed one.
    disk_envelope = load_run_envelope(envelope.run_id, envelope_dir=envelope_dir)
    if not disk_envelope.is_spendable():
        return disk_envelope, Result(
            status="refused",
            detail={
                "reason": (
                    "run envelope is not spendable (absent / malformed / "
                    "tampered / no approved budget, or never minted to disk under "
                    "this run_id) — fail-closed; a live run may not proceed "
                    "without a ceremony-minted envelope on disk"),
                "gate": "run_envelope_v1",
            })
    envelope = disk_envelope

    ledger = cap_ledger if cap_ledger is not None else PersistentInvocationLedger(
        envelope.ledger_window_id,
        ledger_dir=ledger_dir if ledger_dir is not None else DEFAULT_LEDGER_DIR)

    # Deferred import to avoid any import-order coupling at package load; adapters
    # imports write_gate, this module imports both, and adapters never imports
    # this module — so there is no cycle, but the local import keeps the run path
    # self-evidently side-effect-free at module import time. ``planned_unit_count``
    # lives in adapters (not here) so the adapter-registry reference stays inside a
    # scanner-exempt module — see its docstring.
    from external_write.adapters import planned_unit_count, run_operation

    # I-3: enforce the aggregate Knob B ceiling BEFORE applying. Size the
    # reservation by the same planned unit count run_operation will use.
    n_units = planned_unit_count(op)
    granted = envelope.ceiling.granted_this_approval if envelope.ceiling else 0

    if n_units is None:
        # plan() failed / malformed params: nothing will be applied, so consume
        # no aggregate budget — let run_operation return the clean refusal.
        result = run_operation(
            op, receipt, client, target=target, descriptor_set=descriptor_set,
            cap_ledger=ledger, clock=clock, read_only_client=read_only_client)
        return envelope, result

    outcome = ledger.reserve(AGGREGATE_LEDGER_KEY, n_units, granted)
    if not outcome.reserved:
        if outcome.refusal == "lock_unavailable":
            reason = (
                "run refused: the blast-radius ledger's cross-process lock is "
                "unavailable, so the aggregate approval ceiling cannot be enforced "
                "atomically — fail-closed rather than risk exceeding it (I-2).")
        else:
            reason = (
                "run refused: this operation would exceed the aggregate approval "
                f"ceiling for this run ({granted} unit(s) granted this approval): "
                f"{outcome.consumed_before} already applied under this run, this "
                f"operation plans {n_units} more, bringing the total to "
                f"{outcome.consumed_before + n_units}. Re-confirm a further tranche "
                "with the operator before continuing.")
        return envelope, Result(
            status="refused",
            detail={
                "reason": reason,
                "gate": "run_envelope_aggregate_ceiling",
                "granted_this_approval": granted,
                "units_consumed_before": outcome.consumed_before,
                "n_units": n_units,
            })

    result = run_operation(
        op, receipt, client, target=target, descriptor_set=descriptor_set,
        cap_ledger=ledger, clock=clock, read_only_client=read_only_client)

    # A refused/needs-choice op applied nothing — record no tranche. (The
    # aggregate reservation already consumed n_units; over-counting on a later
    # refusal is the SAFE direction for a blast-radius cap — same convention the
    # write gate uses for its per-op ledger.)
    if result.status != "written":
        return envelope, result

    tranche = _tranche_from_result(result)
    updated = append_tranche(envelope, tranche, envelope_dir=envelope_dir)
    return updated, result
