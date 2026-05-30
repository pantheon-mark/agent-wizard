"""Tests for the strict single-doc preview renderer + the orchestration-only group barrier (T2).

render_foundation_doc_preview: renders ONE foundation doc, fail-fast on THAT doc's missing/empty
placeholders only (NOT all docs, NOT other docs' globals) — the partial-render hole the full
render_foundation_docs cannot fill (it renders all docs + fail-fasts on any missing placeholder).

group_barrier: orchestrates only — composes the registry (which fields, which preview docs) + the
transcript store + the renderer. It does the Partial Artifact RENDER (in memory, markdown to
SHOW the operator), the ready-to-close check, and the group-close marker. RED->GREEN.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generator import render_foundation_doc_preview, GeneratorError, FoundationDocArtifact  # noqa: E402
from transcript_recorder import TranscriptRecorder  # noqa: E402
from derivation_groups import load_derivation_groups  # noqa: E402
from group_barrier import (  # noqa: E402
    build_preview_inputs, render_group_previews, ready_to_close, close_group, BarrierError,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_VERSION = "v0.4.0"
FIXED_CLOCK = lambda: "2026-05-30T12:00:00Z"  # noqa: E731

AUTO_VALUES = {
    "SYSTEM_SHAPE": "markdown-CC", "FOUNDATION_ONLY_MODE": "false", "WIZARD_VERSION": "v0.4.0",
    "LAST_UPDATED_DATE": "2026-05-30", "LAST_UPDATED_TRIGGER": "initial build", "CURRENT_SPRINT_NUMBER": "1",
}

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


def _vision_recorder(td, fields=None):
    """A recorder with the vision group fully sourced + derived + confirmed."""
    fields = fields if fields is not None else VISION_FIELDS
    r = TranscriptRecorder(Path(td) / "t.jsonl", clock=FIXED_CLOCK)
    g = load_derivation_groups("markdown-CC").group_by_id("vision")
    for q in g.input_question_ids:
        if q == "V-7b":
            r.record_source_skip(q, "vision", reason="n/a")
        else:
            r.record_source_answer(q, "vision", f"answer for {q}")
    for f, v in fields.items():
        r.record_derived_field(f, "vision", v, _env())
        r.record_field_confirmation(f, "vision", "accepted")
    return r


class PreviewRendererTests(unittest.TestCase):
    def _full_vision_inputs(self):
        return {**AUTO_VALUES, **VISION_FIELDS}

    def test_renders_single_doc_no_unresolved(self):
        art = render_foundation_doc_preview(SOURCE_VERSION, "vision.md", self._full_vision_inputs(), REPO_ROOT)
        self.assertIsInstance(art, FoundationDocArtifact)
        self.assertEqual(art.doc_name, "vision.md")
        self.assertNotIn("{{", art.content)
        self.assertIn("The purpose is to help.", art.content)   # derived prose substituted

    def test_scoped_to_one_doc_other_docs_fields_not_required(self):
        # vision.md needs only VISION_* + globals; it must NOT require execution_plan/tech_arch
        # fields (AUTONOMY_LEVEL, ORCHESTRATION_MODEL, ...). This is the whole point vs the
        # all-docs render_foundation_docs (which would fail-fast on those).
        art = render_foundation_doc_preview(SOURCE_VERSION, "vision.md", self._full_vision_inputs(), REPO_ROOT)
        self.assertNotIn("{{", art.content)

    def test_fails_fast_on_missing_placeholder(self):
        inputs = self._full_vision_inputs()
        del inputs["VISION_PURPOSE"]
        with self.assertRaises(GeneratorError) as cm:
            render_foundation_doc_preview(SOURCE_VERSION, "vision.md", inputs, REPO_ROOT)
        self.assertIn("VISION_PURPOSE", str(cm.exception))

    def test_fails_fast_on_empty_placeholder(self):
        inputs = self._full_vision_inputs()
        inputs["VISION_PURPOSE"] = "   "   # present but empty -> strict preview rejects
        with self.assertRaises(GeneratorError) as cm:
            render_foundation_doc_preview(SOURCE_VERSION, "vision.md", inputs, REPO_ROOT)
        self.assertIn("VISION_PURPOSE", str(cm.exception))

    def test_unknown_doc_name_fails(self):
        with self.assertRaises(GeneratorError):
            render_foundation_doc_preview(SOURCE_VERSION, "not_a_doc.md", self._full_vision_inputs(), REPO_ROOT)


class GroupBarrierTests(unittest.TestCase):
    def test_render_group_previews_vision(self):
        with tempfile.TemporaryDirectory() as td:
            r = _vision_recorder(td)
            dg = load_derivation_groups("markdown-CC")
            arts = render_group_previews(r.events(), dg.group_by_id("vision"), dg,
                                         SOURCE_VERSION, REPO_ROOT, auto_values=AUTO_VALUES)
            self.assertEqual([a.doc_name for a in arts], ["vision.md"])   # uses group.preview_docs
            self.assertNotIn("{{", arts[0].content)
            self.assertIn("The purpose is to help.", arts[0].content)

    def test_build_preview_inputs_merges_confirmed_and_autos(self):
        with tempfile.TemporaryDirectory() as td:
            r = _vision_recorder(td)
            dg = load_derivation_groups("markdown-CC")
            inputs = build_preview_inputs(r.events(), dg, auto_values=AUTO_VALUES)
            self.assertEqual(inputs["VISION_PURPOSE"], "The purpose is to help.")  # confirmed field
            self.assertEqual(inputs["SYSTEM_SHAPE"], "markdown-CC")                # auto-global

    def test_ready_to_close_true_when_all_fields_confirmed(self):
        with tempfile.TemporaryDirectory() as td:
            r = _vision_recorder(td)
            dg = load_derivation_groups("markdown-CC")
            ready, reasons = ready_to_close(r.events(), dg.group_by_id("vision"))
            self.assertTrue(ready, reasons)

    def test_ready_to_close_false_when_field_unconfirmed(self):
        with tempfile.TemporaryDirectory() as td:
            # drop one target field -> not all projected -> not ready
            partial = dict(VISION_FIELDS)
            partial.pop("VISION_SUCCESS_CRITERIA")
            r = _vision_recorder(td, fields=partial)
            dg = load_derivation_groups("markdown-CC")
            ready, reasons = ready_to_close(r.events(), dg.group_by_id("vision"))
            self.assertFalse(ready)
            self.assertTrue(any("VISION_SUCCESS_CRITERIA" in x for x in reasons))

    def test_close_group_appends_marker_with_source_hash(self):
        with tempfile.TemporaryDirectory() as td:
            r = _vision_recorder(td)
            dg = load_derivation_groups("markdown-CC")
            ev = close_group(r, dg.group_by_id("vision"), confirmed_at="2026-05-30T12:30:00Z")
            self.assertEqual(ev["event_type"], "group_confirmed")
            self.assertEqual(ev["group_id"], "vision")
            self.assertTrue(ev["source_hash"].startswith("sha256:"))
            self.assertEqual(len(ev["source_event_range"]), 2)
            # the marker is on disk (resume can read it)
            self.assertTrue(any(e["event_type"] == "group_confirmed" for e in r.events()))

    def test_close_group_refuses_when_not_ready(self):
        with tempfile.TemporaryDirectory() as td:
            partial = dict(VISION_FIELDS)
            partial.pop("VISION_GOALS")
            r = _vision_recorder(td, fields=partial)
            dg = load_derivation_groups("markdown-CC")
            with self.assertRaises(BarrierError):
                close_group(r, dg.group_by_id("vision"))


if __name__ == "__main__":
    unittest.main()
