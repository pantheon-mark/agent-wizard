"""Canonical interview transcript event store + filtered views (stdlib-only).

A live interview must durably record more than the derived fields + confirmations that
the derived-record compiler consumes: it must keep the operator's RAW SOURCE answers (the
inputs derivation runs on) so a resumed session can re-derive, and so the group barrier has
source material. So the transcript is a canonical EVENT STORE with a richer vocabulary than
the compiler's two event types, and FILTERED VIEWS project it down to what each consumer
needs. Critically, the compiler's contract (derivation_replay.compile_transcript, which
accepts only `derivation`/`confirmation`) is NOT expanded — read_derived_replay_events()
maps the store's derived/confirmation events into exactly that shape.

Event vocabulary (event_type):
  - source_answer    operator answered an interview question (the derivation INPUT)
  - source_skip      a (conditional) question was validly skipped
  - derived_field    a foundation-doc field derived from source answers (-> "derivation")
  - field_confirmation  the operator's confirmation of a derived field (-> "confirmation")
  - group_proposed   a logical group's fields were proposed (rendered preview shown)
  - group_confirmed  a group barrier passed (carries source_event_range + source_hash)
  - agent_intent     a structured, Claude-derived AgentIntent (the operator-meaning of one
                     agent + its resource claims). Richer than any foundation-doc field, so
                     it cannot ride in a derived_field; persisted here so the intents are
                     disk-first + resume-safe (the bridge consumes them at close via
                     read_agent_intents()). NOT a derived-record field — the replay view
                     drops it.

Disk-first + resume-safe: each event is appended as one JSON line (JSONL) the moment it is
recorded, before the next question. A new recorder on an existing file continues the
sequence and sees prior events — the cold-resume guarantee. Event payloads are FIXED once
written (timestamps recorded once, never re-evaluated), so the replay view is byte-stable.

Stdlib-only, pip-install-free.
"""

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from derivation_replay import (  # type: ignore
    compile_transcript, project, content_hash,
)
from build_intent import AgentIntent, ResourceClaims  # type: ignore

KNOWN_EVENT_TYPES: Set[str] = {
    "source_answer", "source_skip", "derived_field", "field_confirmation",
    "group_proposed", "group_confirmed", "agent_intent",
}

# Sentinel hashed in place of a value for a validly-skipped source question, so an
# answer<->skip flip changes the group source hash (drives stale-confirmation detection).
_SKIP_SENTINEL = "\x00source_skip\x00"


class TranscriptError(Exception):
    """Raised on a malformed/corrupt transcript event (fail-closed on read)."""


def _default_clock() -> str:
    """ISO-8601 UTC stamp — the one non-deterministic moment, captured to disk once."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TranscriptRecorder:
    """Append-only, disk-first, resume-safe recorder over a JSONL event file."""

    def __init__(self, path: Path, clock: Optional[Callable[[], str]] = None):
        self.path = Path(path)
        self._clock = clock or _default_clock
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # --- read ----------------------------------------------------------------

    def events(self) -> List[Dict[str, Any]]:
        """Read all recorded events from disk, in file order (== sequence order).
        Fails closed on a malformed line or an unknown event_type."""
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError as e:
                    raise TranscriptError(f"corrupt transcript at line {lineno}: {e}") from e
                if not isinstance(ev, dict) or "event_seq" not in ev or "event_type" not in ev:
                    raise TranscriptError(f"malformed event at line {lineno}: {ev!r}")
                if ev["event_type"] not in KNOWN_EVENT_TYPES:
                    raise TranscriptError(
                        f"unknown event_type {ev['event_type']!r} at line {lineno}"
                    )
                out.append(ev)
        return out

    def _next_seq(self) -> int:
        existing = self.events()
        return (max((e["event_seq"] for e in existing), default=0)) + 1

    # --- append --------------------------------------------------------------

    def _append(self, event: Dict[str, Any]) -> Dict[str, Any]:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def record_source_answer(self, question_id: str, group_id: str, value: Any) -> Dict[str, Any]:
        return self._append({
            "event_seq": self._next_seq(), "event_type": "source_answer",
            "question_id": question_id, "group_id": group_id, "value": value,
            "recorded_at": self._clock(),
        })

    def record_source_skip(self, question_id: str, group_id: str, reason: str = "") -> Dict[str, Any]:
        return self._append({
            "event_seq": self._next_seq(), "event_type": "source_skip",
            "question_id": question_id, "group_id": group_id, "reason": reason,
            "recorded_at": self._clock(),
        })

    def record_derived_field(self, field: str, group_id: str, value: Any,
                             envelope: Dict[str, Any]) -> Dict[str, Any]:
        return self._append({
            "event_seq": self._next_seq(), "event_type": "derived_field",
            "field": field, "group_id": group_id, "value": value,
            "envelope": dict(envelope), "recorded_at": self._clock(),
        })

    def record_field_confirmation(self, field: str, group_id: str, confirmation_state: str, *,
                                  value: Any = None, confirmed_at: Optional[str] = None,
                                  confirmed_with_adjustments: Optional[bool] = None,
                                  revisit_trigger: Optional[str] = None) -> Dict[str, Any]:
        ev: Dict[str, Any] = {
            "event_seq": self._next_seq(), "event_type": "field_confirmation",
            "field": field, "group_id": group_id, "confirmation_state": confirmation_state,
            "confirmed_at": confirmed_at or self._clock(),
        }
        if value is not None:
            ev["value"] = value
        if confirmed_with_adjustments is not None:
            ev["confirmed_with_adjustments"] = confirmed_with_adjustments
        if revisit_trigger is not None:
            ev["revisit_trigger"] = revisit_trigger
        return self._append(ev)

    def record_group_proposed(self, group_id: str, fields: List[str]) -> Dict[str, Any]:
        return self._append({
            "event_seq": self._next_seq(), "event_type": "group_proposed",
            "group_id": group_id, "fields": list(fields), "recorded_at": self._clock(),
        })

    def record_group_confirmed(self, group_id: str, source_event_range: Tuple[int, int],
                               source_hash: str, confirmed_at: Optional[str] = None) -> Dict[str, Any]:
        return self._append({
            "event_seq": self._next_seq(), "event_type": "group_confirmed",
            "group_id": group_id, "source_event_range": list(source_event_range),
            "source_hash": source_hash, "confirmed_at": confirmed_at or self._clock(),
        })

    def record_agent_intent(self, group_id: str, intent: "AgentIntent") -> Dict[str, Any]:
        """Persist one structured AgentIntent (the narrow operator-meaning of an agent). The
        booleans/lists are stored flat so the event is plain JSON; read_agent_intents()
        reconstructs the AgentIntent. Re-recording the same display_name (an operator edit in
        the one-round change) appends a new event; the reader keeps the latest."""
        rc = intent.resource_claims
        return self._append({
            "event_seq": self._next_seq(), "event_type": "agent_intent",
            "group_id": group_id,
            "display_name": intent.display_name,
            "function_summary": intent.function_summary,
            "role_intent": intent.role_intent,
            "acceptance_signals": list(intent.acceptance_signals),
            "output_purpose": intent.output_purpose,
            "criticality_tier": intent.criticality_tier,
            "resource_claims": {
                "requires_cron": rc.requires_cron,
                "requires_external_network": rc.requires_external_network,
                "requires_broad_fs_read": rc.requires_broad_fs_read,
            },
            "confidence": intent.confidence,
            "insufficiency_flags": list(intent.insufficiency_flags),
            "source_spans": list(intent.source_spans),
            "recorded_at": self._clock(),
        })


# --- filtered views ----------------------------------------------------------

def read_derived_replay_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Project the event store down to exactly the shape compile_transcript consumes.

    derived_field -> {event_seq, field, event_type:'derivation', value, envelope}
    field_confirmation -> {event_seq, field, event_type:'confirmation', confirmation_state,
                           confirmed_at, [value], [confirmed_with_adjustments], [revisit_trigger]}
    Source + group events are DROPPED (they are not part of the derived-record compile and
    would make compile_transcript raise on an unknown event_type)."""
    out: List[Dict[str, Any]] = []
    for ev in events:
        et = ev.get("event_type")
        if et == "derived_field":
            out.append({
                "event_seq": ev["event_seq"], "field": ev["field"],
                "event_type": "derivation", "value": ev["value"],
                "envelope": dict(ev.get("envelope", {})),
            })
        elif et == "field_confirmation":
            m: Dict[str, Any] = {
                "event_seq": ev["event_seq"], "field": ev["field"], "event_type": "confirmation",
            }
            for k in ("confirmation_state", "confirmed_at", "revisit_trigger",
                      "value", "confirmed_with_adjustments"):
                if k in ev:
                    m[k] = ev[k]
            out.append(m)
        # source_answer / source_skip / group_proposed / group_confirmed / agent_intent:
        # not replay events.
    return out


def read_agent_intents(events: List[Dict[str, Any]]) -> List["AgentIntent"]:
    """Reconstruct the structured AgentIntent list from the agent_intent events — the view the
    bridge consumes at close. Deduped by display_name with the latest event winning (an operator
    edit during the one-round change re-records the agent), preserving first-seen order so the
    roster order is stable across a resume."""
    latest: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for ev in sorted(events, key=lambda e: e.get("event_seq", 0)):
        if ev.get("event_type") != "agent_intent":
            continue
        name = ev.get("display_name")
        if name not in latest:
            order.append(name)
        latest[name] = ev
    out: List[AgentIntent] = []
    for name in order:
        ev = latest[name]
        rc = ev.get("resource_claims", {}) or {}
        out.append(AgentIntent(
            display_name=ev["display_name"],
            function_summary=ev.get("function_summary", ""),
            role_intent=ev.get("role_intent", ""),
            acceptance_signals=list(ev.get("acceptance_signals", [])),
            output_purpose=ev.get("output_purpose", ""),
            criticality_tier=ev.get("criticality_tier", "standard"),
            resource_claims=ResourceClaims(
                requires_cron=bool(rc.get("requires_cron", False)),
                requires_external_network=bool(rc.get("requires_external_network", False)),
                requires_broad_fs_read=bool(rc.get("requires_broad_fs_read", False)),
            ),
            confidence=ev.get("confidence", "low"),
            insufficiency_flags=list(ev.get("insufficiency_flags", [])),
            source_spans=list(ev.get("source_spans", [])),
        ))
    return out


def answered_and_skipped(events: List[Dict[str, Any]]) -> Tuple[Set[str], Set[str]]:
    """(answered_question_ids, skipped_question_ids) from the source events. A later answer
    for a question that was previously skipped moves it to answered, and vice-versa (last
    event wins) — so a resumed/edited interview reports the current source state."""
    answered: Set[str] = set()
    skipped: Set[str] = set()
    for ev in sorted(events, key=lambda e: e.get("event_seq", 0)):
        qid = ev.get("question_id")
        if ev.get("event_type") == "source_answer" and qid is not None:
            answered.add(qid)
            skipped.discard(qid)
        elif ev.get("event_type") == "source_skip" and qid is not None:
            skipped.add(qid)
            answered.discard(qid)
    return answered, skipped


def _latest_source_value_map(events: List[Dict[str, Any]],
                             question_ids: List[str]) -> Dict[str, Any]:
    """Latest source value (or skip sentinel) per requested question-ID; last event wins."""
    wanted = set(question_ids)
    latest: Dict[str, Any] = {}
    for ev in sorted(events, key=lambda e: e.get("event_seq", 0)):
        qid = ev.get("question_id")
        if qid not in wanted:
            continue
        if ev.get("event_type") == "source_answer":
            latest[qid] = ev.get("value")
        elif ev.get("event_type") == "source_skip":
            latest[qid] = _SKIP_SENTINEL
    return latest


def group_source_hash(events: List[Dict[str, Any]], question_ids: List[str]) -> str:
    """Content hash over a group's latest source values (answers + skips). An edit to any of
    the group's source answers changes this hash — the signal a prior group confirmation is
    stale (drives derivation_groups.group_confirmation_is_stale). Order-independent (keyed by
    question-ID); canonicalized by content_hash."""
    return content_hash(_latest_source_value_map(events, question_ids))


def source_event_range(events: List[Dict[str, Any]],
                       question_ids: List[str]) -> Tuple[int, int]:
    """(min_event_seq, max_event_seq) of the source events for the given question-IDs, for the
    group_confirmed marker's source_event_range. (0, 0) if none recorded yet."""
    wanted = set(question_ids)
    seqs = [e["event_seq"] for e in events
            if e.get("event_type") in ("source_answer", "source_skip")
            and e.get("question_id") in wanted]
    if not seqs:
        return (0, 0)
    return (min(seqs), max(seqs))


def event_log_projected_hash(events: List[Dict[str, Any]]) -> str:
    """Hash of the derived record the event log projects to. The event log is the authority;
    a staging mirror is reconciled against this on resume (staging_mirror_hash must equal
    this, else regenerate staging from the log or halt)."""
    record = compile_transcript(read_derived_replay_events(events))
    return content_hash(project(record))
