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

# Schema tag for the INDEPENDENT run-consent receipt (Task 5, A1 — v0.12.0
# Slice 1, design §4). See the "Receipt binding" section below for why this
# is a SEPARATE persisted artifact from the envelope's own `consent` field.
RUN_CONSENT_RECEIPT_SCHEMA = "run_consent_receipt-v1"

# I-3: the persistent-ledger key under which the envelope's AGGREGATE Knob B
# ceiling (``ceiling.granted_this_approval``) is enforced across the whole run.
# It is deliberately NOT of the form ``surface::op_kind`` (the per-op gate key),
# so the aggregate bound and the per-op cap occupy DISTINCT slots in the same
# per-window ledger file and compose — neither masks the other. This bound is
# enforced for EVERY op_kind regardless of the write gate's risk-class gating, so
# a reversible bulk run (which the gate does not cap) is still bounded.
AGGREGATE_LEDGER_KEY = "__run_envelope_aggregate__"

# ---------------------------------------------------------------------------
# reviewed_set schema versioning (Task 8, A3 / F-48 — v0.13.0 Slice 2)
# ---------------------------------------------------------------------------
#
# v1 (the v0.12.0 shape): `mint_run_envelope` validates only that `reviewed_set`
# is a non-empty list/tuple of mappings — the minimal shape every existing
# caller/test already produces (e.g. `{"unit_id": "row1", "prestate_digest": "d",
# ...}`). This is UNCHANGED and remains the default so every v0.12.0 caller
# keeps working with zero changes.
#
# v2 (the triage-driven shape): a reviewed_set produced by a judgment-path
# triage tool (see `triage.py`) carries stronger per-entry guarantees the
# operator's review actually depended on — a unique `unit_id`, a `reason_shown`
# the operator was told, and a `source_snapshot_digest` binding the entry to the
# exact state that was reviewed. F-48: without this, a mis-bucketed destructive
# item could be minted into a spendable envelope with nothing checking that the
# reviewed entries are what the operator actually reviewed, one at a time.
#
# ANTI-DOWNGRADE (AC-T8b): a caller cannot simply omit `reviewed_set_schema` (or
# pass v1) to skip the stronger v2 checks on a reviewed_set that is CLEARLY
# triage-shaped (carries the v2-only marker fields). `_looks_v2_shaped` catches
# exactly this: entries carrying `reason_shown` / `source_snapshot_digest` but
# declared v1 refuse the mint outright, rather than silently falling through to
# the weaker v1 validation. A genuinely legacy, non-triage v1 caller (the
# existing `_reviewed_set()` test shape — no `reason_shown` / no
# `source_snapshot_digest`) is unaffected and keeps minting exactly as before.
REVIEWED_SET_SCHEMA_V1 = "reviewed_set-v1"
REVIEWED_SET_SCHEMA_V2 = "reviewed_set-v2"
_REVIEWED_SET_SCHEMAS = (REVIEWED_SET_SCHEMA_V1, REVIEWED_SET_SCHEMA_V2)

# The v2-only marker fields: their mere PRESENCE on an entry is what triggers
# the anti-downgrade refusal above when the caller declares v1 anyway.
_V2_MARKER_KEYS = ("reason_shown", "source_snapshot_digest")


def _looks_v2_shaped(reviewed_set: Any) -> bool:
    """True if ANY entry carries a v2-only marker field. Used to refuse a
    declared-v1 mint over a reviewed_set that is clearly triage-shaped (AC-T8b
    anti-downgrade) -- never silently validated under the weaker v1 rules."""
    return any(
        isinstance(e, dict) and any(k in e for k in _V2_MARKER_KEYS)
        for e in (reviewed_set or []))


def _validate_reviewed_set_v2(reviewed_set: Any) -> Optional[str]:
    """The reviewed_set-v2 schema check (AC-T8b): every entry must carry a
    unique, non-empty ``unit_id``, ``reason_shown``, and
    ``source_snapshot_digest``. Returns a refusal reason string on the FIRST
    violation found (missing / empty / duplicate), or ``None`` when every
    entry passes -- fail-closed, never a partial acceptance."""
    seen_ids = set()
    for entry in (reviewed_set or []):
        uid = entry.get("unit_id") if isinstance(entry, dict) else None
        if not (isinstance(uid, str) and uid.strip()):
            return "reviewed_set-v2 entry is missing a non-empty unit_id"
        if uid in seen_ids:
            return (
                f"reviewed_set-v2 has a duplicate unit_id {uid!r} — every "
                "reviewed entry must be uniquely identified")
        seen_ids.add(uid)
        reason = entry.get("reason_shown")
        if not (isinstance(reason, str) and reason.strip()):
            return f"reviewed_set-v2 entry {uid!r} is missing a non-empty reason_shown"
        digest = entry.get("source_snapshot_digest")
        if not (isinstance(digest, str) and digest.strip()):
            return (
                f"reviewed_set-v2 entry {uid!r} is missing a non-empty "
                "source_snapshot_digest")
    return None


# Static enum -> plain-language label map for the operator-facing category
# column in ``render_review_artifact``. FIXED constant, never derived at
# render time — ``render_review_artifact`` must render identical bytes for an
# identical reviewed_set on every call (mint AND ``is_spendable`` both
# recompute the artifact from the frozen set and compare digests against it),
# so this map cannot vary by time, locale, or caller. An unrecognized/unknown
# category value is rendered verbatim (fail-safe) rather than raising, so an
# out-of-vocabulary value never breaks rendering or the digest.
_CATEGORY_PLAIN_LABELS: Dict[str, str] = {
    "uniformly_safe": "Uniformly safe",
    "contains_exceptions": "Contains exceptions",
    "requires_review": "Requires review",
    "protected": "Protected",
}


def render_review_artifact(reviewed_set: Any) -> Tuple[str, str]:
    """Deterministically render the operator-facing review artifact from the
    FROZEN ``reviewed_set`` — pure: an identical reviewed_set (content + order)
    always renders identical bytes/digest; no clock, no randomness. Returns
    ``(artifact_text, digest)``.

    This is the consent-binding surface AC-T8a closes: the caller shows this
    rendered text to the operator, the operator approves it, and the caller
    hands the EXACT approved text back to ``mint_run_envelope`` as
    ``operator_approved_review_artifact``. Mint NEVER trusts a caller-supplied
    digest number for this artifact — it always recomputes ``digest`` here,
    from the frozen reviewed_set, and separately hashes the approved text
    itself, then compares the two. A caller cannot simply assert "this digest
    matches" — the two hashes must actually agree.

    Rendered fields are ``unit_id``, a plain-language rendering of
    ``category`` (via the fixed ``_CATEGORY_PLAIN_LABELS`` map — an
    unrecognized value renders verbatim rather than raising), and
    ``reason_shown``. ``unit_id`` and the category label are deliberately
    INCLUDED here — they are exactly what the operator's approval must bind
    to (which items, and how each was classified), per the consent-binding
    purpose this function serves. What is EXCLUDED is the raw internal hash:
    ``source_snapshot_digest`` stays part of the underlying reviewed_set (and
    so still binds via ``reviewed_set_digest``), it is simply not printed
    into operator-facing text — no digest/hash leaks into the consent
    surface, the same convention ``consent_narration.py`` follows. A missing
    field renders as an empty string rather than raising — this function is
    pure rendering, never validation (schema validation is
    ``_validate_reviewed_set_v2``'s job)."""
    normalized = [dict(e) for e in (reviewed_set or [])]
    lines: List[str] = [
        "REVIEWED ITEMS FOR APPROVAL",
        f"total: {len(normalized)}",
        "",
    ]
    for e in normalized:
        unit_id = e.get("unit_id", "")
        category = e.get("category", "")
        category_label = _CATEGORY_PLAIN_LABELS.get(category, category)
        reason = e.get("reason_shown", "")
        lines.append(f"- {unit_id} [{category_label}]: {reason}")
    artifact = "\n".join(lines) + "\n"
    digest = hashlib.sha256(artifact.encode("utf-8")).hexdigest()
    return artifact, digest


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
    # Task 8 (A3 / F-48): the reviewed_set schema tag ("reviewed_set-v1" default
    # / "reviewed_set-v2") and the review-artifact digest the operator's
    # approval is bound to (v2 only; empty for v1). See the "reviewed_set
    # schema versioning" section above `RunEnvelope` for the full rationale.
    reviewed_set_schema: str = REVIEWED_SET_SCHEMA_V1
    review_artifact_digest: str = ""

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
        # AC-T8a (verify half): for a reviewed_set-v2 envelope, the stored
        # review_artifact_digest must RECOMPUTE from the CURRENT reviewed_set
        # via render_review_artifact — never trusted as a bare stored field.
        # This mirrors the reviewed_set_digest self-check just above; it
        # catches a tamper of review_artifact_digest alone, or a reviewed_set
        # edit that leaves a now-stale review_artifact_digest behind. (A
        # single WHOLESALE self-consistent tamper of every one of these
        # fields together is the same disclosed residual the reviewed_set_digest/
        # consent self-check already carries -- see the "Receipt binding"
        # section above; closing that fully is the independent-receipt
        # mechanism, out of this check's scope.)
        if self.reviewed_set_schema == REVIEWED_SET_SCHEMA_V2:
            if not self.review_artifact_digest:
                return False
            _, recomputed_artifact_digest = render_review_artifact(self.reviewed_set)
            if self.review_artifact_digest != recomputed_artifact_digest:
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
        consent=None, evidence_policy={}, tranches=(), stored_ledger_window_id="",
        reviewed_set_schema=REVIEWED_SET_SCHEMA_V1, review_artifact_digest="")


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
        "reviewed_set_schema": env.reviewed_set_schema,
        "review_artifact_digest": env.review_artifact_digest,
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
        reviewed_set_schema=str(raw.get("reviewed_set_schema") or REVIEWED_SET_SCHEMA_V1),
        review_artifact_digest=str(raw.get("review_artifact_digest", "")),
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
# Receipt binding (Task 5, A1/T5 — v0.12.0 Slice 1, design §4; closes F-40's
# consent-fidelity half)
# ---------------------------------------------------------------------------
#
# WHY A SEPARATE ARTIFACT, when the envelope already carries a `consent` field
# whose `approval_bound_to` is checked against `reviewed_set_digest` by
# `is_spendable()`? Because that internal check can only ever compare the
# envelope's OWN fields against EACH OTHER — a single, wholesale, SELF-
# CONSISTENT tamper of the persisted envelope file (rewrite `reviewed_set`,
# recompute `reviewed_set_digest` to match, and rewrite
# `consent.approval_bound_to` to match too) would still satisfy
# `is_spendable()`, because nothing outside that one file is ever consulted.
# The run-consent RECEIPT is minted ONCE, at the same ceremony moment
# (`mint_run_envelope`), into its OWN file — mirroring exactly how
# `acceptance_ceremony` does not trust a descriptor's own fields in isolation
# but cross-checks them against the INDEPENDENTLY-produced
# `operator_acceptance_receipt-v1`. A receipt whose bound
# `reviewed_set_digest` disagrees with the envelope's CURRENT
# `reviewed_set_digest` — because the reviewed set was mutated, reordered
# (order is digest-significant; see `compute_reviewed_set_digest`), or
# re-scanned post-approval — is refused, even if the envelope file alone
# looks perfectly self-consistent.
#
# Disk-authoritative, exactly like the envelope itself (C1): the receipt is
# always re-loaded from its own file by `verify_run_consent_receipt`, never
# trusted from a caller-supplied in-memory value.


def _consent_receipt_path(run_id: str, receipt_dir: Optional[str]) -> str:
    # Stored ALONGSIDE the envelope by default (same directory) so every
    # existing call site that scopes an envelope to a directory (tests, a
    # per-run working directory) automatically scopes its receipt too, with
    # no extra plumbing required.
    directory = receipt_dir if receipt_dir else DEFAULT_ENVELOPE_DIR
    return os.path.join(directory, f"{_safe_run_id(run_id)}.consent_receipt.json")


def load_run_consent_receipt(run_id: str, *, receipt_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fail-safe load of the persisted run-consent receipt. Returns None on an
    absent / unreadable / malformed file — NEVER raises, never treats a
    malformed receipt as present."""
    if not (isinstance(run_id, str) and run_id):
        return None
    path = _consent_receipt_path(run_id, receipt_dir)
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _mint_run_consent_receipt(
    *, run_id: str, reviewed_set_digest: str, operator_confirmation: str,
    approved_at: str, receipt_dir: Optional[str] = None,
) -> str:
    """Persist the run-consent receipt atomically. Raises on any write failure
    (the caller — `mint_run_envelope` — treats that as a mint refusal)."""
    receipt = {
        "schema": RUN_CONSENT_RECEIPT_SCHEMA,
        "run_id": run_id,
        "reviewed_set_digest": reviewed_set_digest,
        "operator_confirmation": operator_confirmation,
        "approved_at": approved_at,
    }
    path = _consent_receipt_path(run_id, receipt_dir)
    _atomic_write_json(path, receipt)
    return path


def verify_run_consent_receipt(
    envelope: RunEnvelope, *, receipt_dir: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Verify that an INDEPENDENTLY-persisted run-consent receipt exists for
    ``envelope.run_id`` and binds the operator's approval to EXACTLY
    ``envelope``'s CURRENT ``reviewed_set_digest``. Fail-closed on every
    branch: absent, unreadable, malformed, wrong schema/run_id, an empty
    confirmation, or ANY digest mismatch all refuse — (ok=False, reason).
    ``(True, None)`` only when every check holds."""
    receipt = load_run_consent_receipt(envelope.run_id, receipt_dir=receipt_dir)
    if not isinstance(receipt, dict):
        return False, (
            "no run-consent receipt found for this run — a live run may not "
            "proceed without an independently-persisted record of the "
            "operator's approval bound to the reviewed set")
    if receipt.get("schema") != RUN_CONSENT_RECEIPT_SCHEMA:
        return False, (
            f"run-consent receipt has an unexpected schema "
            f"{receipt.get('schema')!r}; expected {RUN_CONSENT_RECEIPT_SCHEMA!r}")
    if receipt.get("run_id") != envelope.run_id:
        return False, (
            "run-consent receipt run_id does not match this envelope's run_id "
            "— it does not authorize this run")
    bound_digest = receipt.get("reviewed_set_digest")
    if not (isinstance(bound_digest, str) and bound_digest):
        return False, "run-consent receipt carries no non-empty reviewed_set_digest"
    if bound_digest != envelope.reviewed_set_digest:
        return False, (
            f"run-consent receipt is bound to reviewed_set_digest {bound_digest!r}, "
            f"which does not match the envelope's CURRENT reviewed_set_digest "
            f"{envelope.reviewed_set_digest!r} — the reviewed set was mutated, "
            "reordered, or re-scanned since the operator approved it; refusing "
            "rather than acting on a set the operator never actually saw")
    confirmation = receipt.get("operator_confirmation")
    if not (isinstance(confirmation, str) and confirmation.strip()):
        return False, "run-consent receipt carries no non-empty operator_confirmation"
    return True, None


# ---------------------------------------------------------------------------
# Apply-by-id + forced diff-and-reconfirm (Task 5, A1/T5 — v0.12.0 Slice 1,
# design §4; closes F-40's mechanism half)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReviewedSetDiff:
    """A CONCRETE, id-keyed diff between a FROZEN reviewed set and a fresh
    re-scan — never a full-population diff, however large the population.
    Entries are sorted unit_id tuples for deterministic comparison/testing."""
    added_ids: Tuple[str, ...]
    removed_ids: Tuple[str, ...]
    changed_category_ids: Tuple[str, ...]
    changed_protected_status_ids: Tuple[str, ...]

    def is_divergent(self) -> bool:
        return bool(self.added_ids or self.removed_ids
                    or self.changed_category_ids or self.changed_protected_status_ids)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "added_ids": list(self.added_ids),
            "removed_ids": list(self.removed_ids),
            "changed_category_ids": list(self.changed_category_ids),
            "changed_protected_status_ids": list(self.changed_protected_status_ids),
        }


def diff_reviewed_set_against_rescan(
    frozen_reviewed_set: Any, rescanned_entries: Any,
) -> ReviewedSetDiff:
    """Compute the CONCRETE diff between the FROZEN reviewed_set (the entries
    an approved envelope carries) and a fresh re-scan of the same candidate
    shape (`{unit_id, prestate_digest, intended_mutation, category,
    protected_status}` entries). Used when a re-scan is genuinely unavoidable
    (design §4): never a silent re-scan, never a 15k-line/full-population
    diff — exactly which ids were added, removed, or changed category/
    protected-status. Malformed entries (not a dict, or no `unit_id`) are
    ignored on both sides (they cannot be compared by identity)."""
    def _by_id(entries: Any) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for e in (entries or []):
            if isinstance(e, dict):
                uid = e.get("unit_id")
                if isinstance(uid, str) and uid:
                    out[uid] = e
        return out

    frozen_by_id = _by_id(frozen_reviewed_set)
    rescan_by_id = _by_id(rescanned_entries)
    frozen_ids = set(frozen_by_id)
    rescan_ids = set(rescan_by_id)

    added = tuple(sorted(rescan_ids - frozen_ids))
    removed = tuple(sorted(frozen_ids - rescan_ids))
    common = frozen_ids & rescan_ids
    changed_category = tuple(sorted(
        uid for uid in common
        if frozen_by_id[uid].get("category") != rescan_by_id[uid].get("category")))
    changed_protected = tuple(sorted(
        uid for uid in common
        if frozen_by_id[uid].get("protected_status") != rescan_by_id[uid].get("protected_status")))
    return ReviewedSetDiff(added, removed, changed_category, changed_protected)


def refuse_on_rescan_divergence(
    frozen_reviewed_set: Any, rescanned_entries: Any,
) -> Optional[Result]:
    """If a re-scan is genuinely unavoidable, call this BEFORE proceeding.
    Returns a `Result(status="refused", ...)` carrying the CONCRETE diff when
    the fresh scan diverges from the frozen reviewed set in ANY way (added /
    removed / changed category / changed protected-status) — the caller must
    force a fresh operator reconfirm on that exact diff before continuing,
    NEVER proceed silently. Returns None when the re-scan matches the frozen
    set exactly (nothing to reconfirm)."""
    diff = diff_reviewed_set_against_rescan(frozen_reviewed_set, rescanned_entries)
    if not diff.is_divergent():
        return None
    return Result(
        status="refused",
        detail={
            "reason": (
                "a re-scan of the candidate population diverges from the "
                "reviewed set the operator approved — re-confirm with the "
                "operator on this EXACT diff before proceeding; never a "
                "silent re-scan, never a full-population diff"),
            "gate": "reviewed_set_rescan_divergence",
            "diff": diff.as_dict(),
        })


# ---------------------------------------------------------------------------
# I1 — the SOLE minter of a spendable approved envelope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MintResult:
    accepted: bool
    reason: Optional[str] = None
    envelope_ref: Optional[str] = None
    envelope: Optional[RunEnvelope] = None
    receipt_ref: Optional[str] = None


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
    reviewed_set_schema: Optional[str] = None,
    operator_approved_review_artifact: Optional[str] = None,
) -> MintResult:
    """Mint an APPROVED, spendable RunEnvelope and persist it atomically — the
    SOLE minter (I1). Fail-safe: any missing / ambiguous / empty input refuses
    and writes nothing spendable.

    The ceiling is computed by Knob B (``bounds.knob_b_ceiling``) from the
    frozen ``population_count`` and the op_kind's contract risk class; the
    ``ledger_window_id`` is DERIVED from the verified identity; the consent is
    bound to the ``reviewed_set_digest``. (The machine-generated consent SENTENCE
    is Task 6 and apply-by-id enforcement is Task 5 — this mints the manifest.)

    Task 8 (A3 / F-48) adds two OPTIONAL, backward-compatible parameters:
    ``reviewed_set_schema`` (default "reviewed_set-v1" — every v0.12.0 caller's
    existing call keeps minting exactly as before) and, for
    ``"reviewed_set-v2"`` only, ``operator_approved_review_artifact`` — the
    EXACT text of the rendered review artifact (``render_review_artifact``) the
    operator approved. See the "reviewed_set schema versioning" section near
    the top of this module for the full v1/v2 + anti-downgrade rationale."""
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

    # reviewed_set schema resolution + validation (Task 8 / AC-T8b). Resolve
    # FIRST, before anything else touches reviewed_set, so a bad/downgraded
    # schema refuses before any budget/consent work happens.
    schema = (reviewed_set_schema if isinstance(reviewed_set_schema, str)
              and reviewed_set_schema.strip() else REVIEWED_SET_SCHEMA_V1)
    if schema not in _REVIEWED_SET_SCHEMAS:
        return _mint_refuse(f"unrecognized reviewed_set_schema {schema!r}")
    if schema == REVIEWED_SET_SCHEMA_V1 and _looks_v2_shaped(reviewed_set):
        return _mint_refuse(
            "reviewed_set entries carry reviewed_set-v2 fields (reason_shown / "
            "source_snapshot_digest) but reviewed_set_schema was not declared "
            "'reviewed_set-v2' — a triage-driven reviewed set may not downgrade "
            "to v1 to skip v2 validation; pass "
            "reviewed_set_schema='reviewed_set-v2' explicitly")
    if schema == REVIEWED_SET_SCHEMA_V2:
        v2_reason = _validate_reviewed_set_v2(reviewed_set)
        if v2_reason:
            return _mint_refuse(v2_reason)

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
    resolved_approved_at = approved_at if approved_at else _now_iso_z()

    # AC-T8a — the consent-artifact binding (v2 only): recompute the review
    # artifact digest from the FROZEN, schema-validated reviewed_set and
    # compare it to a digest WE compute over the operator-approved text. Never
    # trust a caller-supplied artifact digest as authoritative — there is no
    # parameter here that even accepts one; only the raw approved TEXT, hashed
    # by this function itself.
    review_artifact_digest = ""
    if schema == REVIEWED_SET_SCHEMA_V2:
        if not (isinstance(operator_approved_review_artifact, str)
                and operator_approved_review_artifact.strip()):
            return _mint_refuse(
                "reviewed_set-v2 requires operator_approved_review_artifact — "
                "the operator must approve the rendered review artifact "
                "(render_review_artifact), not merely give a verbatim "
                "confirmation string")
        _, recomputed_artifact_digest = render_review_artifact(reviewed_set_tuple)
        approved_digest = hashlib.sha256(
            operator_approved_review_artifact.encode("utf-8")).hexdigest()
        if recomputed_artifact_digest != approved_digest:
            return _mint_refuse(
                "review artifact digest mismatch: the artifact rendered from "
                "the frozen reviewed_set does not match the artifact the "
                "operator approved — refusing rather than trusting a "
                "caller-supplied digest or acting on an artifact the operator "
                "never actually saw")
        review_artifact_digest = recomputed_artifact_digest

    consent = Consent(
        operator_approval_verbatim=operator_approval_verbatim,
        consent_sentence_shown=consent_sentence_shown if isinstance(consent_sentence_shown, str) else "",
        approved_at=resolved_approved_at,
        approval_bound_to=reviewed_set_digest,
    )

    # Receipt binding (Task 5, design §4): mint the INDEPENDENT run-consent
    # receipt FIRST, bound to this exact reviewed_set_digest, before the
    # envelope itself is persisted. If the receipt cannot be written, refuse
    # outright — nothing spendable is left on disk without an independently
    # verifiable record of the operator's approval (see the "Receipt binding"
    # section above for why this is a SEPARATE artifact from `consent`).
    try:
        receipt_ref = _mint_run_consent_receipt(
            run_id=run_id, reviewed_set_digest=reviewed_set_digest,
            operator_confirmation=operator_approval_verbatim,
            approved_at=resolved_approved_at, receipt_dir=envelope_dir)
    except Exception as e:
        return _mint_refuse(
            f"could not persist the run-consent receipt; nothing minted: {e}")

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
        reviewed_set_schema=schema,
        review_artifact_digest=review_artifact_digest,
    )

    path = _envelope_path(run_id, envelope_dir)
    try:
        _atomic_write_json(path, _to_disk_dict(env))
    except Exception as e:
        return _mint_refuse(f"could not persist the run envelope; nothing minted: {e}")

    # Re-load from disk so the returned envelope carries the persisted
    # (derived) ledger_window_id and matches exactly what any consumer will see.
    loaded = load_run_envelope(run_id, envelope_dir=envelope_dir)
    return MintResult(accepted=True, envelope_ref=path, envelope=loaded, receipt_ref=receipt_ref)


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
        reviewed_set_schema=env.reviewed_set_schema,
        review_artifact_digest=env.review_artifact_digest,
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
    receipt_dir: Optional[str] = None,
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

    RECEIPT BINDING + APPLY-BY-ID (Task 5, A1/T5 — v0.12.0 Slice 1, design §4;
    closes F-40): two ADDITIONAL fail-closed checks run before anything is
    applied. (1) ``verify_run_consent_receipt`` re-loads an INDEPENDENTLY
    persisted receipt (never the passed envelope's own ``consent`` field) and
    refuses if it is not bound to this envelope's CURRENT
    ``reviewed_set_digest``. (2) every planned effect unit's ``unit_id`` must
    be a member of the envelope's FROZEN ``reviewed_set`` — any id outside it
    (a live re-scan result, a regenerated loop's fresh query, "--all" instead
    of the reviewed subset) refuses with a CONCRETE diff, never silently and
    never a full-population diff.

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

    # Receipt binding (Task 5, design §4): the envelope's own internal
    # consistency (is_spendable, just above) is NOT sufficient on its own — a
    # wholesale, self-consistent tamper of the envelope file would still pass
    # it (see the "Receipt binding" section's docstring above). Independently
    # re-load the run-consent receipt and verify it is bound to EXACTLY this
    # envelope's CURRENT reviewed_set_digest. Absent / malformed / mismatched
    # -> refuse before anything is applied.
    receipt_ok, receipt_reason = verify_run_consent_receipt(
        envelope, receipt_dir=receipt_dir if receipt_dir is not None else envelope_dir)
    if not receipt_ok:
        return envelope, Result(
            status="refused",
            detail={"reason": receipt_reason, "gate": "run_envelope_consent_receipt"})

    ledger = cap_ledger if cap_ledger is not None else PersistentInvocationLedger(
        envelope.ledger_window_id,
        ledger_dir=ledger_dir if ledger_dir is not None else DEFAULT_LEDGER_DIR)

    # Deferred import to avoid any import-order coupling at package load; adapters
    # imports write_gate, this module imports both, and adapters never imports
    # this module — so there is no cycle, but the local import keeps the run path
    # self-evidently side-effect-free at module import time. ``planned_unit_ids``
    # lives in adapters (not here) so the adapter-registry reference stays inside a
    # scanner-exempt module — see its docstring.
    from external_write.adapters import planned_unit_ids, run_operation

    # I-3: enforce the aggregate Knob B ceiling BEFORE applying. Size the
    # reservation by the same planned unit ids run_operation will use.
    ids = planned_unit_ids(op)
    n_units = None if ids is None else len(ids)
    granted = envelope.ceiling.granted_this_approval if envelope.ceiling else 0

    if n_units is None:
        # plan() failed / malformed params: nothing will be applied, so consume
        # no aggregate budget — let run_operation return the clean refusal.
        result = run_operation(
            op, receipt, client, target=target, descriptor_set=descriptor_set,
            cap_ledger=ledger, clock=clock, read_only_client=read_only_client)
        return envelope, result

    # APPLY-BY-ID (Task 5, design §4 — the core F-40 fix): the planned effect
    # units this op will apply must be addressed by their STABLE unit_id, and
    # every one of those ids must be a MEMBER of the FROZEN reviewed_set this
    # envelope was approved against. This is never a live re-scan check on the
    # candidate POPULATION — it is a structural guarantee that the op ACTUALLY
    # being applied cannot touch anything outside what the operator reviewed
    # and approved, however its params were constructed upstream (a regenerated
    # loop, a "--all" re-scan, a reordered/mutated candidate list). Any id
    # planned that is NOT in the frozen reviewed set refuses with a CONCRETE
    # diff (added ids named explicitly) — never silently, never a
    # full-population diff, and never applied.
    frozen_ids = {
        e.get("unit_id") for e in envelope.reviewed_set
        if isinstance(e, dict) and isinstance(e.get("unit_id"), str)
    }
    divergent_ids = sorted(set(ids) - frozen_ids)
    if divergent_ids:
        return envelope, Result(
            status="refused",
            detail={
                "reason": (
                    "run refused: this operation plans to apply "
                    f"{len(divergent_ids)} effect unit(s) whose id is NOT a "
                    "member of the frozen reviewed set this run was approved "
                    "against — apply-by-id requires every applied unit to be "
                    "one the operator actually reviewed; re-confirm with the "
                    "operator on this exact diff before proceeding (never a "
                    "silent re-scan, never applied)."
                ),
                "gate": "run_envelope_apply_by_id",
                "diff": {
                    "added_ids": divergent_ids,
                    "reviewed_set_size": len(frozen_ids),
                    "planned_size": len(ids),
                },
            })

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
