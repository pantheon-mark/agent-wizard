"""Operator authority profile derivation (stdlib-only).

Derives the operator's authority surface from their confirmed authority-profile dimensions:
expertise / desired autonomy / reversibility tolerance / approval latency / domain risk /
trust posture, plus review capability. The non-deterministic step — proposing dimension values
from the operator's earlier interview answers (UP-1/UP-3/UP-4/UP-5/UP-6) plus the reversibility
(REV) and review-capability (RC) probes — happens upstream as a derivation prompt the operator
confirms; THIS module is the deterministic mapping of confirmed dimensions -> emitted authority
fields, so it is fully testable and replayable. The high-stakes constraints (domain risk, via the
DR confirmation; reversibility, via REV) are force-active operator choices, not passive defaults;
trust posture is auto-'probationary' at first build and lifts over time via the earn-up path.

Emitted authority surface (per field-manifests/markdown-CC.json): exactly
  - AUTONOMY_LEVEL  (enum "1"/"2"/"3")
  - the HITL posture that shapes HITL_MAP_ROWS (which action classes act autonomously vs ask-first)
There is no separate autonomous/ask-first field — HITL_MAP_ROWS carries that split.

AUTONOMY_LEVEL = max(1, min(desired_level, domain_risk_cap, reversibility_cap, trust_cap))
  — a CEILING/min model, NOT additive subtraction. Additive stacking could bottom out and produce
  an unusable "ask before everything" system; min() cannot stack, and the HITL posture keeps
  routine action classes (artifact quality + workflow hygiene) autonomous even at level 1, so the
  "approve-all" failure mode is structurally impossible.

Lineage isolation: the profile's source_question_ids are the confirmed authority answers ONLY —
never the vision / Phase-1 text that merely informed a PROPOSED default — so editing the vision
never drifts the authority envelope or forces a spurious re-confirmation.

Fail-closed: any out-of-enum dimension value is a hard error (no silent coercion).
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet, List


# --- closed enums (the operator authority dimensions + review-capability) ------
EXPERTISE = ("technical", "mixed", "non-technical")
DESIRED_AUTONOMY = ("low", "medium", "high")
REVERSIBILITY = ("low", "medium", "high")
APPROVAL_LATENCY = ("sync", "async-business-hours", "async-multi-day")
DOMAIN_RISK = ("low", "medium", "high")
TRUST_POSTURE = ("probationary", "calibrated", "established")
REVIEW_CAPABILITY = ("yes-budget", "yes-limited", "no")

# Q-IDs feeding each dimension — the lineage (authority answers only).
DIMENSION_SOURCES = {
    "expertise": ["UP-1", "UP-4"],
    "desired_autonomy": ["UP-3", "UP-5"],
    "reversibility_tolerance": ["REV"],
    "approval_latency": ["UP-5"],
    "domain_risk": ["DR"],
    "trust_posture": [],   # auto-'probationary' at first build (policy default; no operator probe at v0)
    "review_capability": ["RC"],
}

# The dimensions that CAP AUTONOMY_LEVEL (desired preference + the three constraints).
_AUTONOMY_LEVEL_DIMENSIONS = ("desired_autonomy", "domain_risk", "reversibility_tolerance", "trust_posture")

_ENUMS = {
    "expertise": EXPERTISE,
    "desired_autonomy": DESIRED_AUTONOMY,
    "reversibility_tolerance": REVERSIBILITY,
    "approval_latency": APPROVAL_LATENCY,
    "domain_risk": DOMAIN_RISK,
    "trust_posture": TRUST_POSTURE,
    "review_capability": REVIEW_CAPABILITY,
}

# Ceiling tables: each maps a dimension value to the MAXIMUM AUTONOMY_LEVEL it permits.
# AUTONOMY_LEVEL = max(1, min(all caps)) — a single binding constraint controls; caps never stack.
_DESIRED_LEVEL = {"low": 1, "medium": 2, "high": 3}      # operator preference is itself a ceiling
_DOMAIN_RISK_CAP = {"low": 3, "medium": 2, "high": 1}
_REVERSIBILITY_CAP = {"high": 3, "medium": 2, "low": 1}
_TRUST_CAP = {"established": 3, "calibrated": 3, "probationary": 2}

# Per-class autonomy by level (the baseline per-class defaults, level-modulated). Routine class
# #4 (artifact quality) + #5 (workflow/session hygiene) are autonomous at EVERY level (never "ask
# before everything"); #1 (security/data/destructive) + #7 (creative judgment) are never autonomous.
_AUTONOMOUS_BY_LEVEL = {
    1: frozenset({4, 5}),
    2: frozenset({4, 5, 8}),
    3: frozenset({4, 5, 8, 2}),
}
_ALL_CLASSES = frozenset(range(1, 9))


def _validate(dims: "AuthorityDimensions") -> None:
    for fld, allowed in _ENUMS.items():
        val = getattr(dims, fld)
        if val not in allowed:
            raise AuthorityProfileError(f"{fld} value {val!r} not in closed enum {allowed}")


class AuthorityProfileError(Exception):
    """Raised when a dimension value is out of its closed enum (fail-closed)."""


@dataclass(frozen=True)
class AuthorityDimensions:
    expertise: str
    desired_autonomy: str
    reversibility_tolerance: str
    approval_latency: str
    domain_risk: str
    trust_posture: str
    review_capability: str


@dataclass(frozen=True)
class AuthorityProfile:
    dimensions: AuthorityDimensions
    autonomy_level: str            # "1" | "2" | "3"
    autonomous_classes: FrozenSet[int]
    ask_first_classes: FrozenSet[int]
    source_question_ids: List[str]

    def autonomy_level_envelope(self) -> Dict[str, object]:
        """The field-manifest-shaped descriptor for AUTONOMY_LEVEL after the auto->classification
        flip: classification + decision + closed_value, with non-empty source_question_ids drawn
        from the cap dimensions ONLY (lineage isolation — the inputs that actually bound the
        level, never the vision text that informed a proposed default)."""
        srcs: List[str] = []
        for dim in _AUTONOMY_LEVEL_DIMENSIONS:
            for q in DIMENSION_SOURCES[dim]:
                if q not in srcs:
                    srcs.append(q)
        return {
            "_derivation_class": "classification",
            "_decision_field": True,
            "_decision_kind": "closed_value",
            "_source_question_ids": srcs,
        }


def derive_authority(dims: AuthorityDimensions) -> AuthorityProfile:
    """Deterministically map confirmed authority dimensions -> the emitted authority surface.
    AUTONOMY_LEVEL = max(1, min(caps)); HITL posture per level (routine classes always autonomous).
    Fail-closed on any out-of-enum dimension."""
    _validate(dims)

    level = max(1, min(
        _DESIRED_LEVEL[dims.desired_autonomy],
        _DOMAIN_RISK_CAP[dims.domain_risk],
        _REVERSIBILITY_CAP[dims.reversibility_tolerance],
        _TRUST_CAP[dims.trust_posture],
    ))
    autonomous = _AUTONOMOUS_BY_LEVEL[level]
    ask_first = _ALL_CLASSES - autonomous

    # Profile lineage: every authority dimension's source question-IDs, deduped, stable order.
    # Authority answers ONLY — DIMENSION_SOURCES never contains vision/Phase-1 question-IDs.
    sources: List[str] = []
    for dim_qids in DIMENSION_SOURCES.values():
        for q in dim_qids:
            if q not in sources:
                sources.append(q)

    return AuthorityProfile(
        dimensions=dims,
        autonomy_level=str(level),
        autonomous_classes=autonomous,
        ask_first_classes=ask_first,
        source_question_ids=sources,
    )
