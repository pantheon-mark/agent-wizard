"""Two-knob scale-adaptive bounds engine (Task 4, A1 — v0.12.0 Slice 1,
design §3).

This module is a PURE, deterministic sizing library — no disk, no clock, no
LLM, no surface access. It computes the two bounds the RunEnvelope carries:

  * Knob A — the prove-it-out COVERAGE SAMPLE. Size by CATEGORY COVERAGE over a
    capability-declared generic ``risk_stratum`` (protected class / confidence
    band / decision reason / data class / edge flags), sampling each observed
    stratum to a small fixed depth plus a MANDATORY residual/low-confidence
    stratum plus random spot-checks. If the adapter declares no strata, DEGRADE
    to random stratified sampling — never fail closed, never force categories
    (that would break field ops). The field-op degrade strata (I3(b)) are
    explicitly named: field name / validation status / prestate value class /
    protected row-or-category / confidence-source.

  * Knob B — the aggregate BLAST-RADIUS CEILING per approval:
    ``ceiling = clamp(P% of frozen population, floor, ABSOLUTE_CAP)``, P ~= 5%,
    with a RECOVERY-PROFILE-TIERED absolute cap (reversible/restore-proven
    larger; irreversible tiny, <= the existing per-op regime). The floor never
    exceeds the absolute cap. Progressive, evidence-gated tranches escalate
    across the session (small first -> larger) UP TO the absolute cap — a single
    tranche NEVER authorizes "the remainder" of a large frozen population in one
    consent (the F-39 hole).

Enforcement ceiling (unchanged): build-time + operator-as-approver, NOT
runtime/OS. Stdlib only — no third-party dependencies.
"""

import math
import random as _random
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Recovery-profile tiering: risk_class -> recovery tier -> aggregate ABSOLUTE_CAP
# ---------------------------------------------------------------------------

# Recovery-profile tiers. The absolute cap is keyed on RECOVERY (reversibility),
# not on data sensitivity: a reversible/restore-proven op can safely aggregate to
# a larger ceiling because it can be undone; an irreversible op is held to a tiny
# ceiling <= the existing per-op regime.
#
# Numbers: reversible ~600 (the design's anti-fatigue target — a whole-population
# whittle becomes ~1 evidence-backed ceremony per session, not ~30); irreversible
# 5 (== delete_record's per-op blast_radius_cap in contracts.py — "<= existing
# per-op regime"). These are v0 starting values, deliberately conservative.
ABSOLUTE_CAP_BY_RECOVERY_TIER: Dict[str, int] = {
    "reversible": 600,
    "irreversible": 5,
}

# risk_class -> recovery tier. sensitive_data resolves to REVERSIBLE because the
# EDIT it gates is reversible (e.g. gmail.message.trash/untrash) — the data being
# sensitive earns the gated CLASS, not a smaller recovery profile. standing_
# automation resolves to IRREVERSIBLE: a persistent binding is not cleanly
# reversible in aggregate. read_only_local is never gated, but maps fail-safe.
RISK_CLASS_TO_RECOVERY_TIER: Dict[str, str] = {
    "reversible_external": "reversible",
    "sensitive_data": "reversible",
    "irreversible_external": "irreversible",
    "standing_automation": "irreversible",
    "read_only_local": "irreversible",
}

# Fail-safe: an absent / unknown risk_class resolves to the MOST-protected
# (tiniest-cap) tier, never the permissive one. Mirrors write_gate's
# FAIL_SAFE_RISK_CLASS discipline.
FAIL_SAFE_RECOVERY_TIER = "irreversible"


def recovery_tier_for_risk_class(risk_class: Optional[str]) -> str:
    """Resolve the recovery tier for a risk_class. Fail-safe: an absent /
    out-of-vocabulary risk_class resolves to the most-protected tier."""
    if not isinstance(risk_class, str):
        return FAIL_SAFE_RECOVERY_TIER
    return RISK_CLASS_TO_RECOVERY_TIER.get(risk_class, FAIL_SAFE_RECOVERY_TIER)


def absolute_cap_for_risk_class(risk_class: Optional[str]) -> int:
    """The aggregate ABSOLUTE_CAP for a risk_class, via its recovery tier.
    Fail-safe: unknown risk_class -> the tiniest (irreversible) cap."""
    tier = recovery_tier_for_risk_class(risk_class)
    return ABSOLUTE_CAP_BY_RECOVERY_TIER.get(tier, ABSOLUTE_CAP_BY_RECOVERY_TIER["irreversible"])


# ---------------------------------------------------------------------------
# Knob B — aggregate blast-radius ceiling per approval
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_PERCENT = 0.05   # P ~= 5% start
DEFAULT_KNOB_B_FLOOR = 25       # small-population floor (bounded down to the cap)


def knob_b_ceiling(frozen_population: int, risk_class: Optional[str], *,
                   sample_percent: float = DEFAULT_SAMPLE_PERCENT,
                   floor: int = DEFAULT_KNOB_B_FLOOR) -> int:
    """The aggregate ceiling for one approval:
    ``clamp(ceil(P% of frozen_population), effective_floor, ABSOLUTE_CAP)``,
    then bounded by the frozen population itself.

    The ``effective_floor`` is ``min(floor, ABSOLUTE_CAP)`` — the floor NEVER
    exceeds the absolute cap (design §3 invariant). Fail-safe: a non-positive or
    non-integer population yields 0 (nothing authorized); an unknown risk_class
    resolves to the tiniest cap via ``absolute_cap_for_risk_class``."""
    if not isinstance(frozen_population, int) or isinstance(frozen_population, bool):
        return 0
    if frozen_population <= 0:
        return 0
    cap = absolute_cap_for_risk_class(risk_class)
    effective_floor = min(floor, cap)               # floor never exceeds cap
    raw = int(math.ceil(sample_percent * frozen_population))
    ceiling = max(effective_floor, min(raw, cap))    # clamp(raw, floor, cap)
    return min(ceiling, frozen_population)            # never exceed the population


# ---------------------------------------------------------------------------
# Progressive escalating tranches (never "the remainder" for a large population)
# ---------------------------------------------------------------------------

KNOB_B_FIRST_TRANCHE = 10       # small first
KNOB_B_ESCALATION_FACTOR = 2    # small -> larger


def next_tranche_size(prior_tranche_size: Optional[int], remaining_population: int,
                      absolute_cap: int, *, first: int = KNOB_B_FIRST_TRANCHE,
                      factor: int = KNOB_B_ESCALATION_FACTOR) -> int:
    """Size the NEXT progressive tranche.

    The escalation is ``first`` for the opening tranche, then ``prior * factor``,
    capped at ``absolute_cap`` and by the remaining population. Because a tranche
    is always ``<= absolute_cap``, whenever ``remaining_population > absolute_cap``
    the tranche is STRICTLY LESS than the remaining population — a single consent
    can never authorize "the remainder" of a large frozen population (the F-39
    hole). Only once the remaining population has shrunk to within the absolute
    cap may a final evidence-gated tranche clear the small reversible tail.

    Returns 0 when there is nothing left to authorize."""
    if remaining_population <= 0 or absolute_cap <= 0:
        return 0
    base = first if not prior_tranche_size else prior_tranche_size * factor
    size = min(base, absolute_cap, remaining_population)
    return max(size, 0)


# ---------------------------------------------------------------------------
# Knob A — prove-it-out coverage sample
# ---------------------------------------------------------------------------

KNOB_A_STRATUM_DEPTH = 8        # per-stratum sample depth (>= 5-10)
KNOB_A_FLOOR = 25               # sample floor (or whole population if smaller)
KNOB_A_SOFT_CAP = 100           # soft ceiling on the total sample
KNOB_A_RESIDUAL_SPOT_CHECKS = 5 # extra random spot-checks across the residual

# The residual / "uncategorized / low-confidence" stratum key (always present).
RESIDUAL_STRATUM = "__residual_low_confidence__"

# I3(b): the field-op degrade-to-random strata dimensions — explicitly defined,
# not hand-waved. When a field op declares no generic risk_stratum, candidates
# are stratified on the COMPOSITE of whichever of these keys they carry.
FIELD_OP_FALLBACK_STRATA_KEYS = (
    "field_name",
    "validation_status",
    "prestate_value_class",
    "protected_status",
    "confidence_source",
)


def _declares_strata(candidates: Sequence[Any], stratum_key: str) -> bool:
    for c in candidates:
        if isinstance(c, dict) and c.get(stratum_key) not in (None, ""):
            return True
    return False


def _fallback_composite_key(candidate: Any) -> Any:
    """The I3(b) field-op degrade key: the composite of whichever fallback
    strata dimensions this candidate carries. A candidate carrying NONE of them
    falls into the residual stratum (never forced into a fabricated category)."""
    if not isinstance(candidate, dict):
        return RESIDUAL_STRATUM
    parts = tuple(
        (k, candidate[k]) for k in FIELD_OP_FALLBACK_STRATA_KEYS if k in candidate
    )
    return parts if parts else RESIDUAL_STRATUM


def select_coverage_sample(candidates: Sequence[Any], *,
                           stratum_key: str = "risk_stratum",
                           depth: int = KNOB_A_STRATUM_DEPTH,
                           floor: int = KNOB_A_FLOOR,
                           soft_cap: int = KNOB_A_SOFT_CAP,
                           residual_spot_checks: int = KNOB_A_RESIDUAL_SPOT_CHECKS,
                           rng: Optional[_random.Random] = None) -> List[Any]:
    """Select the Knob A prove-it-out coverage sample from ``candidates``.

    Strategy:
      * Population at or below the floor -> return the WHOLE population (there is
        nothing to sample down to).
      * If any candidate declares a generic ``risk_stratum``, group by it;
        otherwise DEGRADE to random stratified sampling keyed on the field-op
        fallback composite (I3(b)) — never fail closed, never force categories.
      * A MANDATORY residual/low-confidence stratum is always present. Each
        stratum (including the residual) is sampled to ``depth``; extra random
        spot-checks are drawn across the residual.
      * Honor the floor (top up with random picks if coverage came in under it)
        and the soft cap (down-sample if coverage came in over it).

    Deterministic when a seeded ``rng`` is supplied; otherwise uses a fresh
    ``random.Random``. Returns a subset of the input candidates (identity
    preserved)."""
    pool: List[Any] = list(candidates)
    n = len(pool)
    if n == 0:
        return []
    if n <= floor:
        return list(pool)
    if rng is None:
        rng = _random.Random()

    declared = _declares_strata(pool, stratum_key)

    def stratum_of(c: Any) -> Any:
        if declared:
            s = c.get(stratum_key) if isinstance(c, dict) else None
            return s if s not in (None, "") else RESIDUAL_STRATUM
        return _fallback_composite_key(c)

    groups: Dict[Any, List[Any]] = {}
    for c in pool:
        groups.setdefault(stratum_of(c), []).append(c)
    # The residual stratum is mandatory — always represented in the grouping.
    groups.setdefault(RESIDUAL_STRATUM, [])

    selected: List[Any] = []
    seen = set()

    def _take(items: List[Any], k: int) -> None:
        if k <= 0 or not items:
            return
        picks = items if len(items) <= k else rng.sample(items, k)
        for m in picks:
            if id(m) not in seen:
                seen.add(id(m))
                selected.append(m)

    # Per-stratum coverage to the fixed depth.
    for members in groups.values():
        _take(members, depth)

    # Mandatory random spot-checks across the residual stratum.
    residual_remaining = [m for m in groups.get(RESIDUAL_STRATUM, []) if id(m) not in seen]
    _take(residual_remaining, residual_spot_checks)

    # Honor the floor: top up with random picks from anything not yet selected.
    if len(selected) < floor:
        remaining = [m for m in pool if id(m) not in seen]
        _take(remaining, floor - len(selected))

    # Honor the soft cap: down-sample deterministically if we overshot.
    if len(selected) > soft_cap:
        selected = rng.sample(selected, soft_cap)

    return selected
