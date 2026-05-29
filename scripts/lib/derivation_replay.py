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


class DerivationReplayError(Exception):
    """Raised on a malformed transcript or a replay determinism violation."""


# --- canonicalization --------------------------------------------------------

def canonicalize(obj: Any) -> str:
    """Deterministic textual form: sorted keys, compact separators, NFC, LF newlines."""
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    s = unicodedata.normalize("NFC", s)
    return s.replace("\r\n", "\n").replace("\r", "\n")


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


def project(record: Dict[str, Any]) -> Dict[str, Any]:
    """Project a derived record into emission `foundation_doc_inputs` (values only).

    Fields whose `_confirmation_state == deferred_not_emittable` do NOT project.
    """
    audit = record.get(_META_KEY, {})
    out: Dict[str, Any] = {}
    for f, env in audit.items():
        if env.get("_confirmation_state") == "deferred_not_emittable":
            continue
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
    return {k for k in record if k != _META_KEY}


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

    for f in sorted(prev_keys & new_keys):
        pe = prev_audit.get(f, {})
        ne = new_audit.get(f, {})
        if any(pe.get(k) != ne.get(k) for k in _PROTOCOL_KEYS):
            protocol.append(f)
        if any(pe.get(k) != ne.get(k) for k in _ENVELOPE_DRIFT_KEYS):
            envelope.append(f)
        if prev_record[f] != new_record[f]:
            if ne.get("_decision_field") is True:
                decision.append(f)
            else:
                narrative.append(f)

    return {
        "protocol": protocol,
        "envelope": sorted(envelope),
        "content": {"decision": decision, "narrative": narrative},
    }
