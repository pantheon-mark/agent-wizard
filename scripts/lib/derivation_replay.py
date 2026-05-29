"""Event-sourced derivation replay + drift detection (stdlib-only).

The derivation of an operator's fields is non-deterministic model work, so it is not
byte-replayable directly. Instead the wizard records a TRANSCRIPT — an ordered event
log of the model's emitted values/envelopes and the operator's confirmation events.
This module re-compiles a derived record deterministically from that transcript: the
COMPILE (transcript -> record -> projected foundation_doc_inputs) is a pure function
of the transcript and is byte-stable. Replay never re-runs the model; it replays
recorded event payloads only. Auto values and timestamps are recorded in the
transcript, never re-evaluated at replay.

Determinism is anchored by canonicalization (sorted keys, NFC, normalized newlines)
plus sorting of list-valued envelope keys, so the same transcript hashes identically.

Drift detection compares a prior accepted record to a freshly compiled one across three
axes (protocol / envelope / content); content drift is partitioned by decision-ness as
a routing heuristic — alarming-for-review on decision fields, informational on narrative
fields (NOT a proof of a decision change).
"""

import hashlib
import json
import unicodedata
from typing import Any, Dict, List

# Envelope keys whose change constitutes envelope drift (a structural change).
_ENVELOPE_DRIFT_KEYS = ("_source", "_derivation_class", "_decision_field", "_decision_kind", "_confirmation_state")
# Envelope keys tracking the derivation protocol/version.
_PROTOCOL_KEYS = ("_prompt_version", "_spec_version")
# List-valued envelope keys sorted at compile for determinism.
_LIST_ENVELOPE_KEYS = ("_derivation_inputs", "_source_question_ids", "_source_candidates")

_META_KEY = "_audit"
# Top-level record metadata keys — excluded from payload-key comparisons (must match
# derived_record.TOP_LEVEL_META_KEYS so drift and validation agree on what a payload key is).
_TOP_LEVEL_META_KEYS = frozenset({"_provenance", "_audit", "_schema_extension_points", "_source_taxonomy"})


class DerivationReplayError(Exception):
    """Raised on a malformed transcript or a replay determinism violation."""


# --- canonicalization --------------------------------------------------------

def _normalize_text(s: str) -> str:
    """NFC + LF-normalized text. Applied to string CONTENT, before serialization."""
    return unicodedata.normalize("NFC", s).replace("\r\n", "\n").replace("\r", "\n")


def _normalize_strings(obj: Any) -> Any:
    """Recursively NFC+LF-normalize every string key and value.

    Newline/Unicode normalization MUST happen on the string content BEFORE json.dumps:
    once serialized, a real CR/LF inside a value is escaped to the two literal characters
    backslash-r / backslash-n, so a post-serialization replace is a no-op and a Windows vs.
    Unix operator would hash differently.
    """
    if isinstance(obj, str):
        return _normalize_text(obj)
    if isinstance(obj, dict):
        return {(_normalize_text(k) if isinstance(k, str) else k): _normalize_strings(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_strings(x) for x in obj]
    return obj


def canonicalize(obj: Any) -> str:
    """Deterministic textual form: string content NFC+LF-normalized, then sorted-key compact JSON."""
    return json.dumps(_normalize_strings(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonicalize(obj).encode("utf-8")).hexdigest()


# --- compile -----------------------------------------------------------------

def compile_transcript(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compile an ordered transcript into a derived record (payload keys + `_audit`).

    Pure function of `events`: no clock, no randomness, deterministic iteration. Two
    compiles of the same transcript produce byte-identical canonical forms.
    """
    if not isinstance(events, list):
        raise DerivationReplayError("transcript must be a list of events")
    payload: Dict[str, Any] = {}
    audit: Dict[str, Dict[str, Any]] = {}

    for ev in sorted(events, key=lambda e: e.get("event_seq", 0)):
        if not isinstance(ev, dict) or "field" not in ev or "event_type" not in ev:
            raise DerivationReplayError(f"malformed event: {ev!r}")
        f = ev["field"]
        etype = ev["event_type"]
        if etype == "derivation":
            payload[f] = ev["value"]
            audit[f] = dict(ev.get("envelope", {}))
        elif etype == "confirmation":
            env = audit.setdefault(f, {})
            if "confirmation_state" in ev:
                env["_confirmation_state"] = ev["confirmation_state"]
            if "confirmed_at" in ev:
                env["_confirmed_at"] = ev["confirmed_at"]
            if "revisit_trigger" in ev:
                env["_revisit_trigger"] = ev["revisit_trigger"]
            if "value" in ev:  # operator edited the proposal
                payload[f] = ev["value"]
                env["_confirmed_with_adjustments"] = True
            elif ev.get("confirmed_with_adjustments") is not None:
                env["_confirmed_with_adjustments"] = ev["confirmed_with_adjustments"]
        else:
            raise DerivationReplayError(f"unknown event_type {etype!r} for field {f!r}")

    # Normalize list-valued envelope keys so the compile is order-stable.
    for env in audit.values():
        for lk in _LIST_ENVELOPE_KEYS:
            if lk in env and isinstance(env[lk], list):
                env[lk] = sorted(env[lk])

    record = dict(payload)
    record[_META_KEY] = audit
    return record


_PROJECTABLE_STATES = {"accepted", "accepted_with_adjustments", "accepted_uncertain_for_now"}


def project(record: Dict[str, Any]) -> Dict[str, Any]:
    """Project a derived record into emission `foundation_doc_inputs` (values only).

    WHITELIST (defense-in-depth; `project` is an independent public function, not gated by
    the validator): a field projects only if `_source == auto` (mechanical fill, no
    confirmation) OR its `_confirmation_state` is an accepted* state. `deferred_not_emittable`
    and unconfirmed mid-interview fields (a derivation event but no confirmation event yet)
    do NOT project.
    """
    audit = record.get(_META_KEY, {})
    out: Dict[str, Any] = {}
    for f, env in audit.items():
        cstate = env.get("_confirmation_state")
        if cstate == "deferred_not_emittable":
            continue
        if env.get("_source") == "auto" or cstate in _PROJECTABLE_STATES:
            out[f] = record[f]
    return out


def snapshot_hash(record: Dict[str, Any]) -> str:
    """Content hash of the accepted snapshot (the canonical derived record)."""
    return content_hash(record)


def replay_is_byte_identical(events: List[Dict[str, Any]]) -> bool:
    """Compile twice and confirm the canonical forms are byte-identical."""
    a = canonicalize(compile_transcript(events))
    b = canonicalize(compile_transcript(events))
    return a == b


# --- drift -------------------------------------------------------------------

def _payload_keys(record: Dict[str, Any]) -> set:
    return {k for k in record if k not in _TOP_LEVEL_META_KEYS}


def compute_drift(prev_record: Dict[str, Any], new_record: Dict[str, Any]) -> Dict[str, Any]:
    """Three-way drift between a prior accepted record and a freshly compiled one.

    Returns: {
      "protocol": [fields with changed _prompt_version/_spec_version],
      "envelope": [fields added/removed or with changed structural envelope keys],
      "content":  {"decision": [...], "narrative": [...]}  # content changed, partitioned
    }
    Content-drift partition is a routing heuristic (alarming-for-review on decision
    fields), NOT proof of a decision change.
    """
    prev_audit = prev_record.get(_META_KEY, {})
    new_audit = new_record.get(_META_KEY, {})
    prev_keys = _payload_keys(prev_record)
    new_keys = _payload_keys(new_record)

    protocol: List[str] = []
    envelope: List[str] = sorted((prev_keys ^ new_keys))  # added or removed fields
    decision: List[str] = []
    narrative: List[str] = []

    # Net-new fields are content too — a newly invented DECISION is the most alarming drift,
    # so it must reach content.decision, not just envelope.
    for f in (new_keys - prev_keys):
        if new_audit.get(f, {}).get("_decision_field") is True:
            decision.append(f)
        else:
            narrative.append(f)

    # Removed fields are symmetric — a silently DROPPED decision (a deleted permission /
    # constraint / spend limit) is as impactful as an added one. Classify by the PRIOR audit.
    for f in (prev_keys - new_keys):
        if prev_audit.get(f, {}).get("_decision_field") is True:
            decision.append(f)
        else:
            narrative.append(f)

    for f in sorted(prev_keys & new_keys):
        pe = prev_audit.get(f, {})
        ne = new_audit.get(f, {})
        if any(pe.get(k) != ne.get(k) for k in _PROTOCOL_KEYS):
            protocol.append(f)
        if any(pe.get(k) != ne.get(k) for k in _ENVELOPE_DRIFT_KEYS):
            envelope.append(f)
        # Compare CANONICAL forms, not Python objects: 1 vs 1.0 (and dict key-order) are
        # Python-equal but canonically distinct — Python `!=` would miss a hash-affecting change.
        if canonicalize(prev_record[f]) != canonicalize(new_record[f]):
            if ne.get("_decision_field") is True:
                decision.append(f)
            else:
                narrative.append(f)

    return {
        "protocol": protocol,
        "envelope": sorted(envelope),
        "content": {"decision": sorted(decision), "narrative": sorted(narrative)},
    }
