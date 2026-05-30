"""Resume-mid-group no-regression coverage (stdlib unittest; pip-install-free).

A live interview can die at any point. Because the transcript is an append-only,
disk-first event store, "resume" is just a NEW recorder reading the same JSONL — the
cold-resume guarantee. This suite drives the interview to each of five interruption
PREFIXES, re-opens the recorder, and asserts the correct resume signal:

  1. pre-derive          sources recorded, nothing derived yet
  2. pre-confirm         fields derived, none confirmed -> group not closable
  3. pre-group-marker    all fields confirmed, no group_confirmed marker -> resume can close
  4. pre-step-marker     group_confirmed marker on disk but the carrier's wizard_progress step
                         marker never landed -> a re-run step finds the group already
                         confirmed-and-FRESH and must skip re-derivation
  5. post-upstream-edit  an answer feeding a confirmed group is edited -> the stored
                         confirmation is STALE (group_source_hash changed) -> re-derive + re-confirm

These verify EXISTING, unit-tested mechanisms (transcript resume, the group barrier, and
derivation_groups.group_confirmation_is_stale) compose correctly across a resume — so they
are expected to pass; a failure means a real resume regression.

Note on point 4: "both-marker resume" spans two marker CLASSES — the transcript
group_confirmed marker (covered here at the lib level) and the wizard_progress.md step
marker (carrier-managed markdown, exercised in a live session, not stdlib-testable). This
suite covers the transcript side: a re-run that finds a fresh group marker does not redo
the group.
"""

import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcript_recorder import TranscriptRecorder, group_source_hash  # noqa: E402
from derivation_groups import load_derivation_groups, group_confirmation_is_stale  # noqa: E402
from group_barrier import ready_to_close, close_group  # noqa: E402

FIXED_CLOCK = lambda: "2026-05-30T12:00:00Z"  # noqa: E731

# The vision group's target fields, with neutral derived prose (mirrors test_group_barrier).
VISION_FIELDS = {
    "PROJECT_NAME": "Helper", "CORE_PURPOSE": "help with things",
    "VISION_PURPOSE": "The purpose is to help.", "VISION_GOALS": "- be useful",
    "VISION_AUDIENCE_OUTPUTS": "the operator gets summaries",
    "VISION_SCOPE_BOUNDARY": "in scope: helping; out: everything else",
    "VISION_CONSTRAINTS": "must be cheap", "VISION_SUCCESS_CRITERIA": "the operator is helped",
}


def _env(**kw):
    base = {"_source": "operator-content", "_derivation_class": "extraction",
            "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
    base.update(kw)
    return base


def _build(td, stage):
    """Build a transcript for the vision group up to `stage` and return (path, group).
    Validly-skippable conditional questions are skipped (count as satisfied)."""
    path = Path(td) / "t.jsonl"
    r = TranscriptRecorder(path, clock=FIXED_CLOCK)
    g = load_derivation_groups("markdown-CC").group_by_id("vision")
    skippable = set(g.skip_satisfied_if)

    for q in g.input_question_ids:                      # sources
        if q in skippable:
            r.record_source_skip(q, g.group_id, reason="n/a")
        else:
            r.record_source_answer(q, g.group_id, f"answer for {q}")
    if stage == "pre_derive":
        return path, g

    for f, v in VISION_FIELDS.items():                  # derivations
        r.record_derived_field(f, g.group_id, v, _env())
    if stage == "pre_confirm":
        return path, g

    for f in VISION_FIELDS:                             # confirmations
        r.record_field_confirmation(f, g.group_id, "accepted")
    if stage == "pre_group_marker":
        return path, g

    close_group(r, g, confirmed_at="2026-05-30T12:30:00Z")   # group_confirmed marker
    if stage == "closed":
        return path, g

    if stage == "post_edit":                            # operator edits an upstream answer
        edit_q = next(q for q in g.input_question_ids if q not in skippable)
        r.record_source_answer(edit_q, g.group_id, "EDITED — changed after the group was confirmed")
        return path, g

    raise ValueError(f"unknown stage {stage!r}")


class ResumeMidGroupTests(unittest.TestCase):
    @staticmethod
    def _resume(path):
        """Cold resume: a fresh recorder over the same file reads the prior events."""
        return TranscriptRecorder(path, clock=FIXED_CLOCK)

    @staticmethod
    def _types(events):
        return Counter(e["event_type"] for e in events)

    @staticmethod
    def _group_markers(events, group):
        return [e for e in events
                if e["event_type"] == "group_confirmed" and e["group_id"] == group.group_id]

    def test_resume_pre_derive_has_sources_no_derivations(self):
        with tempfile.TemporaryDirectory() as td:
            path, g = _build(td, "pre_derive")
            ev = self._resume(path).events()
            t = self._types(ev)
            self.assertGreater(t["source_answer"], 0, "source answers did not persist across resume")
            self.assertEqual(t["derived_field"], 0, "nothing should be derived at pre-derive")
            ready, _ = ready_to_close(ev, g)
            self.assertFalse(ready, "a group with no derived/confirmed fields must not be closable")

    def test_resume_pre_confirm_has_derivations_no_confirmations(self):
        with tempfile.TemporaryDirectory() as td:
            path, g = _build(td, "pre_confirm")
            ev = self._resume(path).events()
            t = self._types(ev)
            self.assertGreater(t["derived_field"], 0, "derivations did not persist across resume")
            self.assertEqual(t["field_confirmation"], 0, "nothing should be confirmed at pre-confirm")
            ready, _ = ready_to_close(ev, g)
            self.assertFalse(ready, "derived-but-unconfirmed fields must not make the group closable")

    def test_resume_pre_group_marker_ready_but_unmarked_then_closes_on_resume(self):
        with tempfile.TemporaryDirectory() as td:
            path, g = _build(td, "pre_group_marker")
            r = self._resume(path)
            ev = r.events()
            self.assertEqual(self._types(ev)["group_confirmed"], 0, "marker should not exist yet")
            ready, reasons = ready_to_close(ev, g)
            self.assertTrue(ready, reasons)
            marker = close_group(r, g, confirmed_at="2026-05-30T13:00:00Z")   # resume completes the close
            self.assertEqual(marker["event_type"], "group_confirmed")
            self.assertEqual(self._types(r.events())["group_confirmed"], 1)

    def test_resume_pre_step_marker_group_already_confirmed_and_fresh(self):
        with tempfile.TemporaryDirectory() as td:
            path, g = _build(td, "closed")
            ev = self._resume(path).events()
            markers = self._group_markers(ev, g)
            self.assertEqual(len(markers), 1, "the group_confirmed marker must survive resume")
            current = group_source_hash(ev, g.input_question_ids)
            self.assertFalse(group_confirmation_is_stale(markers[-1], current),
                             "an unedited confirmed group must read as FRESH (re-run skips re-derivation)")

    def test_resume_post_upstream_edit_invalidates_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            path, g = _build(td, "post_edit")
            ev = self._resume(path).events()
            markers = self._group_markers(ev, g)
            self.assertEqual(len(markers), 1)
            current = group_source_hash(ev, g.input_question_ids)
            self.assertNotEqual(markers[-1]["source_hash"], current,
                                "editing an upstream answer must change the group source hash")
            self.assertTrue(group_confirmation_is_stale(markers[-1], current),
                            "a confirmed group whose source answer changed must read as STALE")


if __name__ == "__main__":
    unittest.main()
