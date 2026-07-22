"""Machine-generated consent sentence + ceiling check-in prose (Task 6, A1/T6
— v0.12.0 Slice 1, design §4/§5; closes the F-49 narration gap).

Why this exists
----------------
F-49 (estate-tracker dogfood, 2026-07-13): the acceptance prose promised
"every batch pauses for your yes — that never goes away," which the auto-loop
workflow does not do; it under-stated the real scale; and it under-stated the
standing/unattended nature of recurring writes. This module is the fix: it
generates the operator-facing consent sentence and ceiling check-in prose
FROM the RunEnvelope's own prescribed facts — never letting narration promise
a mechanism the run does not actually have.

"Facts prescribed, tone voice-tuned" (design §4/§5)
----------------------------------------------------
The trust-critical FACTS — the exact count (from the frozen ``reviewed_set``),
the action, the reversibility (from the op_kind's recovery tier), and the
session cap (from ``ceiling.granted_this_approval``) — are PRESCRIBED with NO
model latitude: every builder in this module takes them as required
parameters and always renders them, regardless of voice/tone settings. Only
the SURROUNDING tone is tuned per ``voice_and_style.md`` (``EXPLANATION_DEPTH``
/ ``TECHNICAL_LEVEL``, the same closed vocabulary
``wizard/scripts/lib/voice_settings.py`` derives at emit time) — depth adds or
drops FRAMING sentences, never the facts themselves; technical level only
changes the WORDING of the reversibility clause, never its substance.

The manifest digest, ``run_id``, ``ledger_window_id``, and the raw op_kind
identifier live in the receipt / envelope (Task 4/5) — NEVER in operator text.
This module's function signatures structurally enforce that: no builder here
ever accepts a digest, a run_id, or a ledger_window_id as an input, so there is
no way for one to leak through a code path that never sees it. As defense in
depth (Operator Interaction Contract §1), every builder also runs its output
through ``_assert_no_internal_leak`` before returning.

Tone-anchor
-----------
Reuses the plain-language conventions ``broker.py`` already established (its
``_plain_op_kind`` mapping for the seeded status ops) rather than inventing a
second voice — see ``_action_clause`` below.

Stdlib only — no third-party dependencies. This module intentionally does NOT
import anything from ``run_envelope.py`` or ``contracts.py`` beyond duck-typed
attribute reads (``getattr``), so it stays usable directly against a
``RunEnvelope``/``Ceiling``/``Tranche``/``OperationContract`` OR a plain test
double with the same attribute names.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from external_write.broker import _plain_op_kind

# ---------------------------------------------------------------------------
# Operator Interaction Contract §1 — forbidden internal labels / identifiers.
# ---------------------------------------------------------------------------
# None of these may ever appear in operator-facing text. Exported so tests
# (and any other operator-facing renderer) can reuse the exact same list
# rather than re-deriving it.
FORBIDDEN_INTERNAL_TERMS = (
    "run_id",
    "reviewed_set_digest",
    "reviewed_set",
    "ledger_window_id",
    "contract_hash",
    "implementation_hash",
    "capability_id",
    "op_kind",
    "risk_class",
    "recovery_tier",
    "granted_this_approval",
    "remaining_budget",
    "absolute_cap",
    "population_count",
    "stratification_summary",
    "consent_sentence_shown",
    "approval_bound_to",
    "stored_ledger_window_id",
    "AGGREGATE_LEDGER_KEY",
    "envelope_dir",
    "receipt_dir",
    "RunEnvelope",
    "verification_status",
    "restore_verified",
    "applied_unit_ids",
    "per_unit_result",
    "reversible_external",
    "irreversible_external",
    "sensitive_data",
    "standing_automation",
    "read_only_local",
    "Tier-1",
    "Tier-2",
    "Tier-N",
)


def _assert_no_internal_leak(text: str, *, op_kind: Optional[str] = None) -> str:
    """Defense-in-depth: raise if any forbidden internal label/identifier (or
    the raw ``op_kind`` string itself) appears in generated operator text.
    Returns ``text`` unchanged so callers can wrap a ``return`` expression."""
    for term in FORBIDDEN_INTERNAL_TERMS:
        if term in text:
            raise ValueError(
                f"generated operator-facing text leaked an internal label/"
                f"identifier {term!r} — Operator Interaction Contract §1 "
                "forbids this")
    if op_kind and op_kind in text:
        raise ValueError(
            f"generated operator-facing text leaked the raw op_kind "
            f"identifier {op_kind!r} — state the substance, never the "
            "internal name")
    return text


# ---------------------------------------------------------------------------
# Voice settings — closed vocabulary, fail-safe default (never blocks
# narration; an absent/unrecognized value falls back to "standard"/"plain").
# ---------------------------------------------------------------------------

_VALID_DEPTHS = ("brief", "standard", "detailed")
_VALID_TECH_LEVELS = ("plain", "some-technical", "technical")


def _normalize_voice(voice: Optional[Dict[str, str]]) -> Dict[str, str]:
    voice = voice or {}
    depth = str(voice.get("EXPLANATION_DEPTH", "standard")).lower()
    if depth not in _VALID_DEPTHS:
        depth = "standard"
    tech = str(voice.get("TECHNICAL_LEVEL", "plain")).lower()
    if tech not in _VALID_TECH_LEVELS:
        tech = "plain"
    return {"EXPLANATION_DEPTH": depth, "TECHNICAL_LEVEL": tech}


def _extract_table_value(text: str, label: str) -> Optional[str]:
    m = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*([^|]+?)\s*\|", text)
    return m.group(1).strip() if m else None


def load_voice_settings_from_file(path: Any) -> Dict[str, str]:
    """Best-effort, fail-safe read of the rendered ``voice_and_style.md`` table
    rows into the tone knobs this module understands ("consulted by agents
    producing user-facing... output", per that file's own header). An absent
    file, an unreadable file, or a value that does not map to a recognized
    bucket simply falls back — this NEVER raises and NEVER blocks narration;
    tone is always a nice-to-have layered on top of the prescribed facts."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except Exception:
        return {}

    out: Dict[str, str] = {}

    depth_cell = _extract_table_value(raw, "Explanation depth")
    if depth_cell and not depth_cell.startswith("{{"):
        low = depth_cell.lower().strip()
        if low in _VALID_DEPTHS:
            # Exact-token fast path: the literal closed-vocabulary token
            # voice_settings.py actually renders into the table cell (not
            # free-form prose) — must always round-trip to itself.
            out["EXPLANATION_DEPTH"] = low
        elif "brief" in low or "minimal" in low or "concise" in low:
            out["EXPLANATION_DEPTH"] = "brief"
        elif "detail" in low:
            out["EXPLANATION_DEPTH"] = "detailed"
        else:
            out["EXPLANATION_DEPTH"] = "standard"

    tech_cell = _extract_table_value(raw, "Technical level")
    if tech_cell and not tech_cell.startswith("{{"):
        low = tech_cell.lower().strip()
        if low in _VALID_TECH_LEVELS:
            # Exact-token fast path (see above). This is the fix for the
            # real bug: without it, the literal token "some-technical" fell
            # through to the prose heuristics below, where the bare
            # "technical" in low check also matches as a SUBSTRING of
            # "some-technical" and misresolved it to "technical".
            out["TECHNICAL_LEVEL"] = low
        elif "not tech" in low or "non-tech" in low or "plain" in low:
            out["TECHNICAL_LEVEL"] = "plain"
        elif "some-technical" in low or "some tech" in low or "somewhat" in low:
            # Checked BEFORE the bare "technical" substring check below, for
            # the same reason as the exact-token fast path above: any prose
            # containing "some-technical" also contains "technical".
            out["TECHNICAL_LEVEL"] = "some-technical"
        elif "very" in low or "comfortable" in low or "technical" in low:
            out["TECHNICAL_LEVEL"] = "technical"
        else:
            out["TECHNICAL_LEVEL"] = "some-technical"

    return out


# ---------------------------------------------------------------------------
# Plain-language substance: noun, action clause, reversibility clause.
# ---------------------------------------------------------------------------

# Op_kinds broker.py already maps to a nice plain verb (the seeded status ops).
_BROKER_MAPPED_OP_KINDS = frozenset(
    {"set_status", "complete_tasks", "update_due_date", "add_note", "set_priority"}
)

# Explicit, hand-written multi-word action templates for the shapes the
# broker dict does not cover (Gmail's verb-shaped ops + the generic delete).
# ``{obj}`` is substituted with the already-built "N <noun> you just
# reviewed" object phrase.
_ACTION_TEMPLATES: Dict[str, str] = {
    "gmail.message.trash": "move the {obj} to trash",
    "gmail.message.untrash": "restore the {obj} from trash",
    "gmail.message.modify_labels": "change the labels on the {obj}",
    "gmail.filter.create": (
        "create a standing filter, based on the {obj}, that will act "
        "automatically on future matching messages"
    ),
    "delete_record": "delete the {obj}",
}

# Domain noun for the reviewed units, keyed by op_kind. Anything not listed
# here falls back to the generic, domain-neutral "item(s)" — the fallback is
# what keeps this shape-neutral across an arbitrary field-shaped op_kind.
_NOUNS: Dict[str, Any] = {
    "gmail.message.trash": ("message", "messages"),
    "gmail.message.untrash": ("message", "messages"),
    "gmail.message.modify_labels": ("message", "messages"),
    "gmail.filter.create": ("message", "messages"),
    "delete_record": ("record", "records"),
}


def _noun(op_kind: str, count: int) -> str:
    singular, plural = _NOUNS.get(op_kind, ("item", "items"))
    return singular if count == 1 else plural


def _object_phrase(op_kind: str, count: int) -> str:
    # Always render the literal number — never dropped for a singular count —
    # so "the exact count" is trivially present in every rendering (no model
    # latitude on the fact, however the surrounding words are tuned).
    return f"{count} {_noun(op_kind, count)} you just reviewed"


def _action_clause(op_kind: str, obj_phrase: str, contract: Optional[Any]) -> str:
    template = _ACTION_TEMPLATES.get(op_kind)
    if template:
        return template.format(obj=obj_phrase)
    if op_kind in _BROKER_MAPPED_OP_KINDS:
        verb = _plain_op_kind(op_kind)
        return f"{verb} for the {obj_phrase}"
    if contract is not None:
        writes = getattr(contract, "writes", None)
        if writes and writes[0] and writes[0] != "__record__":
            return f"update the {writes[0]} for the {obj_phrase}"
    # Fully generic, domain-neutral last resort: never fails closed on
    # wording, even for an op_kind this module has never seen before.
    return f"apply the reviewed change to the {obj_phrase}"


_REVERSIBILITY_PHRASES: Dict[Any, str] = {
    ("reversible", "plain"): "you'll be able to undo this afterward if needed",
    ("reversible", "some-technical"): "this can be reversed afterward if needed",
    ("reversible", "technical"): (
        "this action is reversible; a restore step is available if needed"
    ),
    ("irreversible", "plain"): "this cannot be undone once it happens",
    ("irreversible", "some-technical"): "this action is not reversible once applied",
    ("irreversible", "technical"): (
        "this action is irreversible; there is no restore path once applied"
    ),
}


def reversibility_phrase(recovery_tier: str, technical_level: str = "plain") -> str:
    """Plain-language reversibility clause for ``recovery_tier`` ("reversible"
    / "irreversible" — ``bounds.recovery_tier_for_risk_class``'s vocabulary).
    Fail-safe: anything other than the two known tiers, or an unrecognized
    technical level, resolves to the most-protected / plainest phrasing —
    never silently claims reversibility that was not explicitly granted."""
    tier = recovery_tier if recovery_tier == "reversible" else "irreversible"
    tech = technical_level if technical_level in _VALID_TECH_LEVELS else "plain"
    return _REVERSIBILITY_PHRASES[(tier, tech)]


# ---------------------------------------------------------------------------
# The machine-generated consent sentence (design §4)
# ---------------------------------------------------------------------------

def build_consent_sentence(
    *,
    count: int,
    op_kind: str,
    recovery_tier: str,
    session_cap: int,
    contract: Optional[Any] = None,
    is_standing_automation: bool = False,
    voice: Optional[Dict[str, str]] = None,
) -> str:
    """Build the ONE machine-generated consent sentence the operator approves
    verbatim, defers, or asks to change — never restates themselves.

    Prescribed facts (always present, regardless of ``voice``):
      * the exact count of reviewed units (``count``, from the frozen
        ``reviewed_set``)
      * the action (from ``op_kind`` / ``contract``)
      * reversibility (from ``recovery_tier``)
      * the session cap (``session_cap``, from ``ceiling.granted_this_
        approval``)

    ``is_standing_automation`` (True for a ``standing_automation`` risk_class,
    e.g. ``gmail.filter.create``) ALWAYS adds the ongoing/unattended-nature
    notice — this is a prescribed narration requirement (F-49), not a tone
    knob, so it is not gated by ``voice`` either.

    ``voice`` only tunes surrounding FRAMING (``EXPLANATION_DEPTH`` adds/drops
    trailing context sentences; ``TECHNICAL_LEVEL`` changes only the wording
    of the reversibility clause) — it can never drop a prescribed fact.
    """
    if not (isinstance(count, int) and not isinstance(count, bool) and count > 0):
        raise ValueError(
            "count must be a positive integer — a consent sentence is only "
            "generated over a frozen, non-empty reviewed set")
    if not (isinstance(session_cap, int) and not isinstance(session_cap, bool)
            and session_cap > 0):
        raise ValueError("session_cap must be a positive integer")
    if not (isinstance(op_kind, str) and op_kind):
        raise ValueError("op_kind must be a non-empty string")

    v = _normalize_voice(voice)
    obj_phrase = _object_phrase(op_kind, count)
    action = _action_clause(op_kind, obj_phrase, contract)
    reversibility = reversibility_phrase(recovery_tier, v["TECHNICAL_LEVEL"])
    cap_noun = _noun(op_kind, session_cap)

    core = (
        f"You're about to {action} — {reversibility}. Today's approval "
        f"covers up to {session_cap} {cap_noun}; if this run needs more than "
        "that, it will stop and check with you again before going further."
    )

    sentences: List[str] = [core]

    if is_standing_automation:
        sentences.append(build_standing_automation_notice(
            op_kind=op_kind, session_cap=session_cap, voice=voice))

    if v["EXPLANATION_DEPTH"] in ("standard", "detailed"):
        sentences.append(
            "You can decline this, or ask for changes instead of approving "
            "it as shown."
        )
    if v["EXPLANATION_DEPTH"] == "detailed":
        sentences.append(
            "Nothing runs until you reply to approve, and you can stop or "
            "change your mind at any point before that."
        )

    text = " ".join(sentences)
    _assert_no_internal_leak(text, op_kind=op_kind)
    # Facts must be present regardless of tone — assert our own invariant.
    assert str(count) in text and str(session_cap) in text
    return text


def build_standing_automation_notice(
    *, op_kind: str, session_cap: int, voice: Optional[Dict[str, str]] = None,
) -> str:
    """The F-49 fix, standalone: states the real ongoing/unattended nature of
    a standing-automation run and makes NO "every batch pauses for your yes"
    promise. Also usable on its own (e.g. re-shown at a later check-in)."""
    # ``voice`` is accepted for a consistent call shape across this module's
    # builders, but this notice has no depth/technical-level variance — the
    # ongoing-nature statement is itself a prescribed fact, not tone — so
    # there is nothing here to normalize or use.
    cap_noun = _noun(op_kind, session_cap)
    text = (
        "Once you approve this, it keeps applying on its own in the "
        "background — it will not stop and ask before each small batch. "
        f"It checks in with you again once it has gone through up to "
        f"{session_cap} {cap_noun}."
    )
    return _assert_no_internal_leak(text, op_kind=op_kind)


# ---------------------------------------------------------------------------
# Ceiling check-in / re-confirm prose (design §3's per-tranche ceremony)
# ---------------------------------------------------------------------------

_VERIFY_STATUS_PHRASES: Dict[str, str] = {
    "verified": "it went through, and we checked it actually landed",
    "applied_not_verified": (
        "it was applied, but we could not double-check that it landed"
    ),
}


def _verify_phrase(status: Optional[str]) -> str:
    # Fail-safe: any status other than the literal "verified" renders the
    # honest not-verified phrasing — never defaults to claiming "verified".
    if status == "verified":
        return _VERIFY_STATUS_PHRASES["verified"]
    return _VERIFY_STATUS_PHRASES["applied_not_verified"]


def build_ceiling_checkin_prose(
    *,
    op_kind: str,
    count_now: int,
    remaining_count: int,
    sample_descriptions: Sequence[str] = (),
    prior_tranche_status: Optional[str] = None,
    prior_restore_verified: Optional[bool] = None,
    voice: Optional[Dict[str, str]] = None,
) -> str:
    """Build the re-confirm ceremony prose shown at each ceiling check-in.

    Always shows: what changed (this tranche's count), the exact count +
    what's left, a sample of affected units, the PRIOR tranche's real-surface
    verification + restore result (honest — never overclaims "verified"), and
    an explicit stop/defer instruction.
    """
    if not (isinstance(count_now, int) and not isinstance(count_now, bool)
            and count_now > 0):
        raise ValueError("count_now must be a positive integer")
    if not (isinstance(remaining_count, int) and not isinstance(remaining_count, bool)
            and remaining_count >= 0):
        raise ValueError("remaining_count must be a non-negative integer")

    # ``voice`` is accepted for a consistent call shape across this module's
    # builders, but this check-in prose has no depth/technical-level
    # variance today, so there is nothing here to normalize or use.

    noun_now = _noun(op_kind, count_now)
    lines: List[str] = []

    if remaining_count == 0:
        lines.append(
            f"Here's where things stand: {count_now} more {noun_now} are "
            "ready to go, and that would complete everything you reviewed "
            "— nothing would be left after that."
        )
    else:
        noun_remaining = _noun(op_kind, remaining_count)
        lines.append(
            f"Here's where things stand: {count_now} more {noun_now} are "
            f"ready to go, and {remaining_count} {noun_remaining} would "
            "still be left after that."
        )

    samples = [s for s in (sample_descriptions or []) if isinstance(s, str) and s.strip()]
    if samples:
        shown = samples[:5]
        lines.append("A few examples of what's included: " + "; ".join(shown) + ".")

    lines.append(f"On the last batch: {_verify_phrase(prior_tranche_status)}.")

    if prior_restore_verified is True:
        lines.append(
            "The undo for that batch was tested and confirmed working."
        )
    elif prior_restore_verified is False:
        lines.append(
            "The undo for that batch was tested and did not confirm as "
            "working — worth checking before you continue."
        )
    # prior_restore_verified is None: no restore was applicable/attempted for
    # that tranche; say nothing further rather than fabricate a claim.

    lines.append(
        "Reply to go ahead, reply to stop here, or come back to this later "
        "— nothing more happens until you say go."
    )

    text = " ".join(lines)
    _assert_no_internal_leak(text, op_kind=op_kind)
    assert str(count_now) in text
    return text


# ---------------------------------------------------------------------------
# Convenience wrappers wired directly against RunEnvelope's own fields
# (``reviewed_set`` for the count, ``ceiling.granted_this_approval`` for the
# cap, ``ceiling.recovery_tier`` for reversibility, ``tranches`` for the
# prior-tranche check-in) — duck-typed so a real RunEnvelope/Ceiling/Tranche
# or a plain test double both work.
# ---------------------------------------------------------------------------

def build_multi_approval_notice(
    *, op_kind: str, population_count: int, granted_this_approval: int,
) -> str:
    """V15-2/E — multi-ceremony framing, at the ONLY place it can be stated
    accurately: run-level consent, where the real per-run ceiling
    (``ceiling.granted_this_approval``, Knob B / ``bounds.knob_b_ceiling``)
    and the real population count are both in hand together.

    States the real mechanism: one approval authorizes tranches that
    auto-escalate (10 -> 20 -> 40 ...) up to this run's aggregate ceiling with
    NO further consent in between (``run_sanctioned_bulk``); exhausting that
    ceiling always requires a FRESH operator approval for what's left — never
    "the rest happens automatically" and never a hardcoded population/cap
    figure (a prior version of this narration wrongly claimed a per-tranche
    boundary was a session boundary; see V15-2/E finding).

    Callers gate this on ``population_count > granted_this_approval`` — when
    the whole job fits inside one approval, this notice has nothing true to
    add and should not be called."""
    noun = _noun(op_kind, population_count)
    text = (
        f"This approval covers up to {granted_this_approval} of the "
        f"{population_count} {noun} — the rest will need a separate "
        "approval from you before it happens."
    )
    return _assert_no_internal_leak(text, op_kind=op_kind)


def build_run_envelope_consent_sentence(
    *,
    reviewed_set: Sequence[Any],
    op_kind: str,
    ceiling: Any,
    contract: Optional[Any] = None,
    voice: Optional[Dict[str, str]] = None,
) -> str:
    """Convenience: derive the prescribed facts straight from the values a
    ``mint_run_envelope`` caller already has in hand — the frozen
    ``reviewed_set`` (for the count) and the computed ``ceiling`` (Knob B,
    ``bounds.knob_b_ceiling`` — for the cap + recovery tier) — and build the
    sentence to show the operator BEFORE minting (its text becomes
    ``consent_sentence_shown``; the operator's own reply becomes
    ``operator_approval_verbatim`` — two distinct fields, never conflated).

    V15-2/E: when the population exceeds what THIS approval covers
    (``count > session_cap``), appends ``build_multi_approval_notice`` so the
    operator learns up front that a large whittle spans more than one
    approval/ceremony — using only this call's own real inputs, never a
    hardcoded population or cap figure."""
    count = len(reviewed_set)
    session_cap = getattr(ceiling, "granted_this_approval", None)
    if session_cap is None and isinstance(ceiling, dict):
        session_cap = ceiling.get("granted_this_approval")
    recovery_tier = getattr(ceiling, "recovery_tier", None)
    if recovery_tier is None and isinstance(ceiling, dict):
        recovery_tier = ceiling.get("recovery_tier")

    risk_class = getattr(contract, "risk_class", None) if contract is not None else None
    is_standing_automation = risk_class == "standing_automation"

    text = build_consent_sentence(
        count=count, op_kind=op_kind, recovery_tier=recovery_tier,
        session_cap=session_cap, contract=contract,
        is_standing_automation=is_standing_automation, voice=voice)

    if (isinstance(session_cap, int) and not isinstance(session_cap, bool)
            and session_cap > 0 and count > session_cap):
        text = text + " " + build_multi_approval_notice(
            op_kind=op_kind, population_count=count,
            granted_this_approval=session_cap)

    return _assert_no_internal_leak(text, op_kind=op_kind)


def build_run_envelope_checkin_prose(
    *,
    op_kind: str,
    count_now: int,
    remaining_count: int,
    sample_descriptions: Sequence[str] = (),
    prior_tranche: Optional[Any] = None,
    voice: Optional[Dict[str, str]] = None,
) -> str:
    """Convenience: derive the prior-tranche verification + restore result
    straight from a ``run_envelope.Tranche`` (or ``None`` for the first
    check-in, before any tranche has been applied)."""
    if prior_tranche is None:
        prior_status: Optional[str] = None
        prior_restore: Optional[bool] = None
    else:
        prior_status = getattr(prior_tranche, "verification_status", None)
        prior_restore = getattr(prior_tranche, "restore_verified", None)

    return build_ceiling_checkin_prose(
        op_kind=op_kind, count_now=count_now, remaining_count=remaining_count,
        sample_descriptions=sample_descriptions,
        prior_tranche_status=prior_status,
        prior_restore_verified=prior_restore, voice=voice)
