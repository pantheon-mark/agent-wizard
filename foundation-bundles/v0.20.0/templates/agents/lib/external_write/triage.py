"""The judgment-path triage primitive (Task 8, A3 / F-48 — v0.13.0 Slice 2).

Why this exists
---------------
Slice 1 (v0.12.0) built the DESTRUCTIVE path's trust core: an operator
approves a FROZEN ``reviewed_set`` and ``run_envelope`` enforces apply-by-id
against it (F-40). But nothing upstream of that helped the operator actually
DECIDE what belongs in the reviewed_set in the first place — the judgment
path (discover candidates, group them, tell safe from suspect from
protected) had no operator-facing mechanism at all. Worse, ``mint_run_envelope``
originally accepted ANY non-empty list of dicts, so a mis-bucketed
destructive/protected item could ride along into an approved envelope with
nothing checking the bucketing itself.

This module is the read-only judgment-path tool that closes that gap: it
groups candidates, classifies them into a small generic vocabulary, and
itemizes exceptions — producing exactly the shape ``mint_run_envelope``'s
``reviewed_set-v2`` schema (see ``run_envelope.py``) expects. It performs NO
external writes: no adapter import, no ``run_operation`` reference, no
credential, no client of any kind. It only classifies data the caller already
collected (read-only, upstream of any write decision).

Generic by construction — no vendor/domain vocabulary here
------------------------------------------------------------
Any vendor-specific grouping concept (e.g. a messaging system's originator
field, a commerce catalog's SKU, a records system's account id) is an
ADAPTER-LEVEL instantiation of the underlying, fully generic concepts this
module actually works with: an ``entity_key`` (whatever the caller's domain
groups by), a ``unit_id`` (the single stable identity of one candidate item),
and a caller-supplied per-candidate safety judgment (``is_safe`` /
``protected_status``) this module never second-guesses or infers on its own.
The SAME code below groups two entirely different rosters identically — see
``test_external_write_triage.py``'s divergent-domain anti-overfit case.

The classification vocabulary (generic, four buckets)
------------------------------------------------------
Every group of same-``entity_key`` candidates is classified into exactly one
of:

  * ``protected``           — ANY member is ``protected_status=True``. This
                               check runs FIRST and unconditionally wins —
                               see "Bucketing is a safety surface" below.
  * ``uniformly_safe``      — no protected member, and EVERY member is
                               ``is_safe=True``.
  * ``contains_exceptions`` — no protected member, at least one ``is_safe``
                               member AND at least one non-safe member — the
                               non-safe ones are itemized as ``exceptions``.
  * ``requires_review``     — no protected member, and NO member is
                               ``is_safe`` (nothing here looked safe enough
                               to auto-bucket) — the caller must look at it.

Bucketing is a safety surface
------------------------------
A destructive/protected unit must NEVER be classified ``uniformly_safe`` —
this is the mechanized safety property this module exists to guarantee
(tested directly in ``test_external_write_triage.py``). The ``protected``
check running before the ``uniformly_safe`` check, unconditionally, on the
WHOLE group (not just the individual unit) is what makes this true even when
a protected item shares an ``entity_key`` with otherwise-safe items.

Two outputs, two altitudes
---------------------------
  * ``triage_candidates`` — one row PER UNIT: ``{unit_id, entity_key,
    reason_shown, category, protected_status, source_snapshot_digest}`` (the
    exact shape ``run_envelope.mint_run_envelope``'s ``reviewed_set-v2``
    schema requires). This is what an operator's approved SUBSET becomes the
    ``reviewed_set`` for minting.
  * ``triage_discovery`` — DEDUPED discovery: exactly ONE row per
    ``entity_key``, never N-rows-per-unit, however many units share that key.
    This is the operator-facing summary altitude — see the (thin) emitted
    skill this module backs for how it is actually shown to an operator.

Read-only, no external writes
------------------------------
This module MUST NOT import ``external_write.adapters``, ``adapter_registry``,
``run_operation``, any adapter-profile module, or any credential/client. It
performs no external I/O of any kind — it is a pure classification over
caller-supplied dicts. (It legitimately falls into the CAPABILITY trust zone
by the fail-closed default in ``zones.py`` — it needs no SEALED_KERNEL or
ADAPTER_PROFILE exemption, because it never touches anything either of those
zones exist to gate.)

Stdlib only — no third-party dependencies.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

# The generic classification vocabulary (Task 8 spec).
CATEGORY_UNIFORMLY_SAFE = "uniformly_safe"
CATEGORY_CONTAINS_EXCEPTIONS = "contains_exceptions"
CATEGORY_REQUIRES_REVIEW = "requires_review"
CATEGORY_PROTECTED = "protected"

CATEGORIES: Tuple[str, ...] = (
    CATEGORY_UNIFORMLY_SAFE,
    CATEGORY_CONTAINS_EXCEPTIONS,
    CATEGORY_REQUIRES_REVIEW,
    CATEGORY_PROTECTED,
)

# Required generic fields on every raw candidate dict. A candidate missing
# any of these (or carrying the wrong type) is DROPPED — never guessed at,
# never defaulted into a permissive bucket (fail-closed on malformed input).
_REQUIRED_STRING_FIELDS = ("unit_id", "entity_key", "reason_shown", "source_snapshot_digest")


@dataclass(frozen=True)
class TriageCandidate:
    """One validated, caller-supplied candidate. ``is_safe`` and
    ``protected_status`` are the caller's OWN judgment (e.g. an adapter's
    own reputation heuristic, or a spreadsheet-cleanup rule) — this module
    never infers either one; it only groups and classifies from them."""

    unit_id: str
    entity_key: str
    reason_shown: str
    source_snapshot_digest: str
    protected_status: bool
    is_safe: bool


def _validate_candidate(raw: Any) -> Optional[TriageCandidate]:
    """Fail-closed per-entry validation: a malformed candidate is dropped
    (returns None), never raised on and never guessed into a bucket."""
    if not isinstance(raw, dict):
        return None
    for field in _REQUIRED_STRING_FIELDS:
        value = raw.get(field)
        if not (isinstance(value, str) and value.strip()):
            return None
    return TriageCandidate(
        unit_id=raw["unit_id"],
        entity_key=raw["entity_key"],
        reason_shown=raw["reason_shown"],
        source_snapshot_digest=raw["source_snapshot_digest"],
        protected_status=bool(raw.get("protected_status", False)),
        is_safe=bool(raw.get("is_safe", False)),
    )


def _parse_candidates(raw_candidates: Any) -> List[TriageCandidate]:
    return [c for c in (_validate_candidate(r) for r in (raw_candidates or [])) if c is not None]


def _group_by_entity_key(
    candidates: Sequence[TriageCandidate],
) -> Tuple[List[str], Dict[str, List[TriageCandidate]]]:
    """Group candidates by ``entity_key``, preserving FIRST-SEEN order (both
    for deterministic output and so ``triage_discovery`` emits its deduped
    rows in a stable, reproducible order)."""
    order: List[str] = []
    groups: Dict[str, List[TriageCandidate]] = {}
    for c in candidates:
        if c.entity_key not in groups:
            groups[c.entity_key] = []
            order.append(c.entity_key)
        groups[c.entity_key].append(c)
    return order, groups


def _classify_group(members: Sequence[TriageCandidate]) -> str:
    """The one deterministic classification rule (see module docstring).
    ``protected`` is checked FIRST and unconditionally — see "Bucketing is a
    safety surface" above: this is what guarantees a protected/destructive
    unit can never fall into ``uniformly_safe``, however the rest of its
    group looks."""
    if any(m.protected_status for m in members):
        return CATEGORY_PROTECTED
    if all(m.is_safe for m in members):
        return CATEGORY_UNIFORMLY_SAFE
    if any(m.is_safe for m in members):
        return CATEGORY_CONTAINS_EXCEPTIONS
    return CATEGORY_REQUIRES_REVIEW


def triage_candidates(raw_candidates: Any) -> List[Dict[str, Any]]:
    """Read-only: classify each candidate into its GROUP's category. Returns
    one dict per VALID candidate (malformed entries are silently dropped —
    see ``_validate_candidate``), each carrying exactly:
    ``{unit_id, entity_key, reason_shown, category, protected_status,
    source_snapshot_digest}`` — the shape ``run_envelope.mint_run_envelope``'s
    ``reviewed_set-v2`` schema requires. Order is preserved: candidates are
    emitted in their original input order (not re-grouped/re-sorted), so a
    caller can zip this output back against its own source list."""
    candidates = _parse_candidates(raw_candidates)
    _, groups = _group_by_entity_key(candidates)
    category_by_key = {key: _classify_group(members) for key, members in groups.items()}
    return [
        {
            "unit_id": c.unit_id,
            "entity_key": c.entity_key,
            "reason_shown": c.reason_shown,
            "category": category_by_key[c.entity_key],
            "protected_status": c.protected_status,
            "source_snapshot_digest": c.source_snapshot_digest,
        }
        for c in candidates
    ]


def triage_discovery(raw_candidates: Any) -> List[Dict[str, Any]]:
    """Read-only, DEDUPED discovery: exactly ONE row per ``entity_key``, never
    N-rows-per-unit, however many units share that key. Each row is:

    ``{entity_key, category, unit_count, reason_shown, exceptions}``

    ``reason_shown`` is populated ONLY for ``requires_review`` and
    ``protected`` groups (the categories the spec says must show it) — a
    representative member's reason (the protected member's, for a
    ``protected`` group). It is the empty string for ``uniformly_safe`` and
    ``contains_exceptions`` groups, whose per-item detail belongs in
    ``exceptions`` instead, never a top-level generic summary line.

    ``exceptions`` itemizes the non-safe members of a ``contains_exceptions``
    group — ``[{unit_id, reason_shown}, ...]`` — and is empty for every other
    category."""
    candidates = _parse_candidates(raw_candidates)
    order, groups = _group_by_entity_key(candidates)

    rows: List[Dict[str, Any]] = []
    for key in order:
        members = groups[key]
        category = _classify_group(members)

        reason_shown = ""
        exceptions: List[Dict[str, str]] = []
        if category == CATEGORY_PROTECTED:
            protected_member = next(m for m in members if m.protected_status)
            reason_shown = protected_member.reason_shown
        elif category == CATEGORY_REQUIRES_REVIEW:
            reason_shown = members[0].reason_shown
        elif category == CATEGORY_CONTAINS_EXCEPTIONS:
            exceptions = [
                {"unit_id": m.unit_id, "reason_shown": m.reason_shown}
                for m in members if not m.is_safe
            ]

        rows.append({
            "entity_key": key,
            "category": category,
            "unit_count": len(members),
            "reason_shown": reason_shown,
            "exceptions": exceptions,
        })
    return rows
