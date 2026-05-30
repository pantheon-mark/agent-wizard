"""Tests for the canonical interview transcript event store + filtered views (T1).

The recorder records a RICHER event vocabulary than the derived-record compiler accepts
(it must durably keep the operator's raw source answers, not only the derived fields +
confirmations). Filtered views project the event store down to the exact shapes each
consumer needs — crucially read_derived_replay_events() maps derived+confirmation events
into the unchanged shape compile_transcript consumes. RED→GREEN.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcript_recorder import (  # noqa: E402
    TranscriptRecorder,
    TranscriptError,
    read_derived_replay_events,
    read_agent_intents,
    answered_and_skipped,
    group_source_hash,
    source_event_range,
    event_log_projected_hash,
    KNOWN_EVENT_TYPES,
)
from derivation_replay import compile_transcript, project, replay_is_byte_identical  # noqa: E402
from derivation_groups import group_inputs_complete, group_confirmation_is_stale, DerivationGroup  # noqa: E402
from build_intent import AgentIntent, ResourceClaims  # noqa: E402

FIXED_CLOCK = lambda: "2026-05-30T12:00:00Z"  # noqa: E731  deterministic record-time stamp


def _envelope(**kw):
    base = {"_source": "operator-content", "_derivation_class": "extraction",
            "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
    base.update(kw)
    return base


class RecordReadTests(unittest.TestCase):
    def test_records_and_reads_back_in_seq_order(self):
        with tempfile.TemporaryDirectory() as td:
            r = TranscriptRecorder(Path(td) / "transcript.jsonl", clock=FIXED_CLOCK)
            r.record_source_answer("V-1", "vision", "build a thing")
            r.record_derived_field("VISION_PURPOSE", "vision", "Build a thing.", _envelope())
            r.record_field_confirmation("VISION_PURPOSE", "vision", "accepted")
            evs = r.events()
            self.assertEqual([e["event_seq"] for e in evs], [1, 2, 3])
            self.assertEqual([e["event_type"] for e in evs],
                             ["source_answer", "derived_field", "field_confirmation"])

    def test_disk_first_resume_continues_sequence(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.jsonl"
            r1 = TranscriptRecorder(p, clock=FIXED_CLOCK)
            r1.record_source_answer("V-1", "vision", "x")
            r1.record_source_answer("V-2", "vision", "y")
            # New recorder instance on the SAME file (simulates a resumed session).
            r2 = TranscriptRecorder(p, clock=FIXED_CLOCK)
            self.assertEqual(len(r2.events()), 2)               # prior events visible
            ev = r2.record_source_answer("V-3", "vision", "z")
            self.assertEqual(ev["event_seq"], 3)                # sequence continues
            self.assertEqual(len(r2.events()), 3)

    def test_unknown_event_type_on_disk_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.jsonl"
            p.write_text('{"event_seq": 1, "event_type": "bogus", "field": "X"}\n', encoding="utf-8")
            r = TranscriptRecorder(p, clock=FIXED_CLOCK)
            with self.assertRaises(TranscriptError):
                r.events()

    def test_known_event_types(self):
        self.assertEqual(
            KNOWN_EVENT_TYPES,
            {"source_answer", "source_skip", "derived_field", "field_confirmation",
             "group_proposed", "group_confirmed", "agent_intent"},
        )


class ReplayViewTests(unittest.TestCase):
    def _recorder_with_full_group(self, td):
        r = TranscriptRecorder(Path(td) / "t.jsonl", clock=FIXED_CLOCK)
        r.record_source_answer("V-1", "vision", "the purpose")
        r.record_source_skip("V-7b", "vision", reason="not applicable")
        r.record_derived_field("VISION_PURPOSE", "vision", "The purpose.", _envelope())
        r.record_field_confirmation("VISION_PURPOSE", "vision", "accepted",
                                    confirmed_at="2026-05-30T12:01:00Z")
        r.record_group_proposed("vision", ["VISION_PURPOSE"])
        return r

    def test_replay_view_maps_to_compile_transcript_shape(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._recorder_with_full_group(td)
            replay = read_derived_replay_events(r.events())
            # Only derivation + confirmation survive (source/group events dropped).
            self.assertEqual({e["event_type"] for e in replay}, {"derivation", "confirmation"})
            record = compile_transcript(replay)            # the UNCHANGED contract accepts it
            self.assertEqual(record["VISION_PURPOSE"], "The purpose.")
            self.assertEqual(record["_audit"]["VISION_PURPOSE"]["_confirmation_state"], "accepted")
            self.assertIn("VISION_PURPOSE", project(record))   # accepted -> projects

    def test_replay_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._recorder_with_full_group(td)
            self.assertTrue(replay_is_byte_identical(read_derived_replay_events(r.events())))

    def test_operator_edit_confirmation_carries_value(self):
        with tempfile.TemporaryDirectory() as td:
            r = TranscriptRecorder(Path(td) / "t.jsonl", clock=FIXED_CLOCK)
            r.record_derived_field("VISION_PURPOSE", "vision", "draft", _envelope())
            r.record_field_confirmation("VISION_PURPOSE", "vision", "accepted_with_adjustments",
                                        value="operator's edited purpose")
            record = compile_transcript(read_derived_replay_events(r.events()))
            self.assertEqual(record["VISION_PURPOSE"], "operator's edited purpose")
            self.assertTrue(record["_audit"]["VISION_PURPOSE"]["_confirmed_with_adjustments"])

    def test_projected_hash_stable(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._recorder_with_full_group(td)
            h1 = event_log_projected_hash(r.events())
            h2 = event_log_projected_hash(r.events())
            self.assertEqual(h1, h2)
            self.assertTrue(h1.startswith("sha256:"))


class SourceViewTests(unittest.TestCase):
    def test_answered_and_skipped_feeds_group_predicate(self):
        with tempfile.TemporaryDirectory() as td:
            r = TranscriptRecorder(Path(td) / "t.jsonl", clock=FIXED_CLOCK)
            for q in ("P1-1", "P1-2", "V-1", "V-2", "V-3", "V-4", "V-5", "V-6", "V-7", "V-8"):
                r.record_source_answer(q, "vision", f"answer-{q}")
            r.record_source_skip("V-7b", "vision", reason="n/a")
            answered, skipped = answered_and_skipped(r.events())
            self.assertIn("V-1", answered)
            self.assertIn("V-7b", skipped)
            g = DerivationGroup(
                group_id="vision",
                input_question_ids=["P1-1", "P1-2", "V-1", "V-2", "V-3", "V-4", "V-5", "V-6", "V-7", "V-7b", "V-8"],
                target_fields=["VISION_PURPOSE"], close_after="step_05",
                confirmation_marker="group_vision_confirmed", preview_docs=["vision.md"],
                skip_satisfied_if=["V-7b"],
            )
            self.assertTrue(group_inputs_complete(g, answered, skipped))   # V-7b validly skipped


class GroupHashTests(unittest.TestCase):
    def test_source_hash_changes_on_answer_edit_and_drives_staleness(self):
        with tempfile.TemporaryDirectory() as td:
            r = TranscriptRecorder(Path(td) / "t.jsonl", clock=FIXED_CLOCK)
            r.record_source_answer("V-1", "vision", "original purpose")
            qids = ["V-1"]
            h_before = group_source_hash(r.events(), qids)
            # operator goes back and edits V-1 (a later source_answer for the same qid wins)
            r.record_source_answer("V-1", "vision", "edited purpose")
            h_after = group_source_hash(r.events(), qids)
            self.assertNotEqual(h_before, h_after)
            # a group confirmed against the pre-edit hash is now stale (must re-confirm)
            stale_marker = {"status": "complete", "source_hash": h_before}
            self.assertTrue(group_confirmation_is_stale(stale_marker, h_after))

    def test_source_event_range(self):
        with tempfile.TemporaryDirectory() as td:
            r = TranscriptRecorder(Path(td) / "t.jsonl", clock=FIXED_CLOCK)
            r.record_source_answer("A", "g", "1")   # seq 1
            r.record_source_answer("X", "other", "y")  # seq 2 (different group)
            r.record_source_answer("B", "g", "2")   # seq 3
            lo, hi = source_event_range(r.events(), ["A", "B"])
            self.assertEqual((lo, hi), (1, 3))


class AgentIntentEventTests(unittest.TestCase):
    """agent_intent events persist the structured, Claude-derived agent intents disk-first
    (richer than any foundation-doc field; the operator confirms them at the approach_roster
    barrier but the bridge consumes them at close). read_agent_intents() reconstructs the
    AgentIntent objects; the derived-replay view drops them (they are not derived-record fields)."""

    def _ai(self, name, cron=False, crit="standard", flags=()):
        return AgentIntent(
            display_name=name, function_summary=f"{name} does a thing.",
            role_intent=f"{name} exists to do the thing for the operator.",
            acceptance_signals=["the thing is done"], output_purpose="a result",
            criticality_tier=crit, resource_claims=ResourceClaims(requires_cron=cron),
            confidence="high", insufficiency_flags=list(flags), source_spans=["ARCH-2#1"])

    def test_agent_intent_round_trips(self):
        with tempfile.TemporaryDirectory() as td:
            r = TranscriptRecorder(Path(td) / "t.jsonl", clock=FIXED_CLOCK)
            r.record_agent_intent("approach_roster", self._ai("Researcher", cron=True, crit="critical"))
            r.record_agent_intent("approach_roster", self._ai("Drafter"))
            intents = read_agent_intents(r.events())
            self.assertEqual([a.display_name for a in intents], ["Researcher", "Drafter"])
            self.assertTrue(intents[0].resource_claims.requires_cron)
            self.assertEqual(intents[0].criticality_tier, "critical")
            self.assertEqual(intents[0].source_spans, ["ARCH-2#1"])

    def test_agent_intent_dropped_from_replay_view(self):
        with tempfile.TemporaryDirectory() as td:
            r = TranscriptRecorder(Path(td) / "t.jsonl", clock=FIXED_CLOCK)
            r.record_derived_field("APPROACH_SOLUTION_BRIEF", "approach_roster", "a brief",
                                   _envelope(_source="claude-derived-operator-confirmed",
                                             _derivation_class="synthesis", _derivation_inputs=["AP-1"]))
            r.record_field_confirmation("APPROACH_SOLUTION_BRIEF", "approach_roster", "accepted")
            r.record_agent_intent("approach_roster", self._ai("Researcher"))
            replay = read_derived_replay_events(r.events())
            self.assertEqual({e["event_type"] for e in replay}, {"derivation", "confirmation"})
            # the compiler never sees an agent_intent event (would raise on unknown type)
            compile_transcript(replay)

    def test_agent_intent_last_wins_by_display_name(self):
        with tempfile.TemporaryDirectory() as td:
            r = TranscriptRecorder(Path(td) / "t.jsonl", clock=FIXED_CLOCK)
            r.record_agent_intent("approach_roster", self._ai("Researcher", crit="standard"))
            # operator revises during the one-round change: same agent, now critical
            r.record_agent_intent("approach_roster", self._ai("Researcher", crit="critical"))
            intents = read_agent_intents(r.events())
            self.assertEqual([a.display_name for a in intents], ["Researcher"])   # deduped
            self.assertEqual(intents[0].criticality_tier, "critical")             # last wins


if __name__ == "__main__":
    unittest.main()
