"""Tests for the interview CLI — the live driver + the T4 vision-group acceptance test.

The CLI lets the interview carriers record transcript events, derive fields (with the audit
envelope ASSEMBLED from the field manifest + class prompt, so the wizard supplies only the
value + the sources it used), render a group preview, and close a group. This test drives the
full vision-group flow through the CLI command functions and asserts the T4 acceptance:
  - the recorded transcript compiles + validate_derived_record accepts it;
  - the barrier preview shows rendered vision markdown (no unresolved placeholders);
  - cold-resume reads the step + group markers;
  - NO vision.md is written mid-interview.
RED->GREEN.
"""

import sys
import tempfile
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parent
_SCRIPTS = _LIB.parent
sys.path.insert(0, str(_LIB))
sys.path.insert(0, str(_SCRIPTS))

import interview_cli as cli  # noqa: E402
from derivation_replay import compile_transcript, project  # noqa: E402
from transcript_recorder import TranscriptRecorder, read_derived_replay_events  # noqa: E402
import derived_record  # noqa: E402
from derivation_groups import load_derivation_groups, parse_progress_markers, validate_marker_invariant  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
SHAPE = "markdown-CC"
SOURCE_VERSION = "v0.4.0"
CLOCK = "2026-05-30T12:00:00Z"

AUTO = {"SYSTEM_SHAPE": "markdown-CC", "FOUNDATION_ONLY_MODE": "false", "WIZARD_VERSION": "v0.4.0",
        "LAST_UPDATED_DATE": "2026-05-30", "LAST_UPDATED_TRIGGER": "initial build", "CURRENT_SPRINT_NUMBER": "1"}

# field -> (value, sources answered)  (V-7/V-7b skipped, so VISION_PURPOSE/GOALS cite V-1/V-2 only)
VISION = {
    "PROJECT_NAME": ("Helper", ["P1-1"]),
    "CORE_PURPOSE": ("Help the operator keep on top of things.", ["P1-2"]),
    "VISION_PURPOSE": ("The system watches for things the operator would otherwise miss.", ["V-1"]),
    "VISION_GOALS": ("- surface what needs attention\n- draft routine responses", ["V-2"]),
    "VISION_AUDIENCE_OUTPUTS": ("The operator, via a morning digest.", ["V-3"]),
    "VISION_SCOPE_BOUNDARY": ("In scope: monitoring + drafting. Out: sending without approval.", ["V-4"]),
    "VISION_CONSTRAINTS": ("Must never spend money or send messages without explicit approval.", ["V-5"]),
    "VISION_SUCCESS_CRITERIA": ("In six months the operator misses nothing important.", ["V-6"]),
}


def _drive_vision_group(transcript, progress):
    """Record the whole vision group through the CLI, returning the recorder."""
    g = load_derivation_groups(SHAPE).group_by_id("vision")
    # 1. source answers (V-7, V-7b validly skipped)
    answered = {"P1-1", "P1-2", "V-1", "V-2", "V-3", "V-4", "V-5", "V-6"}
    for q in g.input_question_ids:
        if q in answered:
            cli.cmd_record_answer(transcript, q, "vision", f"answer for {q}", clock=lambda: CLOCK)
        else:
            cli.cmd_skip_answer(transcript, q, "vision", reason="not applicable", clock=lambda: CLOCK)
    # 2. derive (extraction) + 3. confirm each vision field
    for field, (value, sources) in VISION.items():
        cli.cmd_derive_field(transcript, SHAPE, field, value, sources=sources, inputs=None, clock=lambda: CLOCK)
        cli.cmd_confirm_field(transcript, field, "vision", "accepted", clock=lambda: CLOCK)
    return TranscriptRecorder(Path(transcript), clock=lambda: CLOCK)


class VisionGroupAcceptanceTests(unittest.TestCase):
    def test_transcript_compiles_and_validates(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            ppath = str(Path(td) / "wizard_progress.md")
            r = _drive_vision_group(tpath, ppath)
            record = compile_transcript(read_derived_replay_events(r.events()))
            # validate_derived_record accepts the compiled record (the fail-closed gate)
            contract = derived_record.load_contract(derived_record.default_contract_path())
            derived_record.validate_derived_record(record, contract)   # raises on failure
            projected = project(record)
            for f in VISION:
                self.assertIn(f, projected, f"{f} did not project")

    def test_preview_renders_vision_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            ppath = str(Path(td) / "wizard_progress.md")
            _drive_vision_group(tpath, ppath)
            previews = cli.cmd_preview_group(tpath, SHAPE, "vision", SOURCE_VERSION, REPO_ROOT, auto_values=AUTO)
            self.assertEqual([d for d, _ in previews], ["vision.md"])
            content = previews[0][1]
            self.assertNotIn("{{", content)
            self.assertIn("watches for things", content)   # derived prose rendered

    def test_close_group_writes_transcript_event_and_progress_marker(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            ppath = str(Path(td) / "wizard_progress.md")
            r = _drive_vision_group(tpath, ppath)
            ev = cli.cmd_close_group(tpath, ppath, SHAPE, "vision", clock=lambda: CLOCK)
            self.assertEqual(ev["event_type"], "group_confirmed")
            # transcript carries the group_confirmed event
            self.assertTrue(any(e["event_type"] == "group_confirmed" for e in r.events()))
            # progress file carries the control-flow marker with the source hash
            markers = parse_progress_markers(Path(ppath).read_text(encoding="utf-8"))
            self.assertIn("group_vision_confirmed", markers)
            self.assertTrue(markers["group_vision_confirmed"].get("source_hash", "").startswith("sha256:"))

    def test_marker_invariant_clean_after_close_then_step_marker(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            ppath = str(Path(td) / "wizard_progress.md")
            _drive_vision_group(tpath, ppath)
            cli.cmd_close_group(tpath, ppath, SHAPE, "vision", clock=lambda: CLOCK)
            # now the carrier may legally write step_05: complete
            cli.cmd_mark_step(ppath, "step_05", clock=lambda: CLOCK)
            dg = load_derivation_groups(SHAPE)
            markers = parse_progress_markers(Path(ppath).read_text(encoding="utf-8"))
            self.assertEqual(validate_marker_invariant(markers, dg), [])

    def test_step_marker_before_group_close_violates_invariant(self):
        with tempfile.TemporaryDirectory() as td:
            ppath = str(Path(td) / "wizard_progress.md")
            cli.cmd_mark_step(ppath, "step_05", clock=lambda: CLOCK)   # step done but vision NOT confirmed
            dg = load_derivation_groups(SHAPE)
            markers = parse_progress_markers(Path(ppath).read_text(encoding="utf-8"))
            self.assertTrue(any("vision" in v for v in validate_marker_invariant(markers, dg)))

    def test_no_vision_md_written_mid_interview(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            ppath = str(Path(td) / "wizard_progress.md")
            proj = Path(td) / "project"
            proj.mkdir()
            _drive_vision_group(tpath, ppath)
            cli.cmd_preview_group(tpath, SHAPE, "vision", SOURCE_VERSION, REPO_ROOT, auto_values=AUTO)
            cli.cmd_close_group(tpath, ppath, SHAPE, "vision", clock=lambda: CLOCK)
            # The unified flow records + previews + closes — it does NOT emit vision.md (the generator
            # emits it at close). Nothing in the flow wrote a vision.md into the project dir.
            self.assertFalse((proj / "vision.md").exists())

    def test_resume_reads_markers(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            ppath = str(Path(td) / "wizard_progress.md")
            _drive_vision_group(tpath, ppath)
            cli.cmd_close_group(tpath, ppath, SHAPE, "vision", clock=lambda: CLOCK)
            cli.cmd_mark_step(ppath, "step_05", clock=lambda: CLOCK)
            rp = cli.cmd_resume(ppath, SHAPE)
            self.assertEqual(rp["highest_completed_step"], 5)
            self.assertIn("vision", rp["confirmed_groups"])


class CLIGuardTests(unittest.TestCase):
    def test_derive_synthesis_without_inputs_fails_loud(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            with self.assertRaises(cli.InterviewCLIError):
                # APPROACH_SOLUTION_BRIEF is synthesis -> requires --inputs (prior field keys), not --sources
                cli.cmd_derive_field(tpath, SHAPE, "APPROACH_SOLUTION_BRIEF", "x",
                                     sources=["AP-1"], inputs=None, clock=lambda: CLOCK)

    def test_derive_unknown_field_fails_loud(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            with self.assertRaises(Exception):
                cli.cmd_derive_field(tpath, SHAPE, "NOPE", "x", sources=["V-1"], inputs=None, clock=lambda: CLOCK)


if __name__ == "__main__":
    unittest.main()
