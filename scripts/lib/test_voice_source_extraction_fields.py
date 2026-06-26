"""Tests for the three voice-source extraction fields.

UP_TECHNICAL_LITERACY (UP-1), NOTIFICATION_VERBOSITY (ERR-1), and QA_REPORTING_STYLE
(QA-1) are made real EXTRACTION-class derived fields so they project into
`foundation_doc_inputs`. That single change:
  - fixes the F-12 voice derivation (voice_settings_inputs reads real per-operator
    values, not the scaffold constants), AND
  - fixes the pre-existing generic project_instructions.md profile section (the
    scaffold-default constants are overridden via build_scaffold_inputs precedence).

TDD: these tests are written before the manifest / derivation-groups edits.

Covers:
  1. manifest declares the 3 fields, extraction-class, contract-shaped (DR-6 static).
  2. derivation-groups target_fields include them in the right group.
  3. contract conformance: a derive-field for each produces a DR-5/DR-6-valid envelope.
  4. projection: compile->project yields the 3 keys with the operator's values.
  5. differential voice test: two plans with DIFFERENT technical-literacy answers
     produce DIFFERENT voice values (the test that would have caught the theater bug).
  6. project_instructions.md (scaffold-emitted) shows the real values, not the
     scaffold constants ("standard"/"summary"/"(operator-configures during setup)").
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SHAPE = "markdown-CC"
CLOCK = "2026-06-25T00:00:00Z"

_NEW_FIELDS = ("UP_TECHNICAL_LITERACY", "NOTIFICATION_VERBOSITY", "QA_REPORTING_STYLE")
_FIELD_SOURCE = {
    "UP_TECHNICAL_LITERACY": "UP-1",
    "NOTIFICATION_VERBOSITY": "ERR-1",
    "QA_REPORTING_STYLE": "QA-1",
}
_FIELD_GROUP = {
    "UP_TECHNICAL_LITERACY": "hitl_autonomy",
    "NOTIFICATION_VERBOSITY": "hitl_autonomy",
    "QA_REPORTING_STYLE": "tests_audit",
}


class ManifestDeclaresExtractionFields(unittest.TestCase):
    """The field manifest declares all three as extraction-class, contract-shaped."""

    def setUp(self):
        from field_manifest import load_field_manifest  # noqa: F401
        self.m = load_field_manifest(SHAPE)

    def test_fields_present_and_extraction(self):
        for f in _NEW_FIELDS:
            spec = self.m.spec_for(f)  # raises if absent
            self.assertEqual(spec.derivation_class, "extraction", f)
            self.assertFalse(spec.decision_field, f)
            self.assertEqual(spec.decision_kind, "none", f)
            # DR-6 static coupling: decision_field == (decision_kind != none)
            self.assertEqual(spec.decision_field, spec.decision_kind != "none", f)

    def test_fields_cite_correct_source_question(self):
        for f in _NEW_FIELDS:
            spec = self.m.spec_for(f)
            self.assertIn(_FIELD_SOURCE[f], spec.source_question_ids, f)

    def test_fields_in_correct_group(self):
        for f in _NEW_FIELDS:
            self.assertEqual(self.m.spec_for(f).group_id, _FIELD_GROUP[f], f)

    def test_fields_render_into_no_preview_doc(self):
        # They render into scaffold-emitted project_instructions.md, not a foundation doc.
        for f in _NEW_FIELDS:
            self.assertEqual(self.m.spec_for(f).preview_doc, "", f)


class DerivationGroupsTargetFields(unittest.TestCase):
    """The derivation-groups registry lists each field as a target of the right group."""

    def setUp(self):
        from derivation_groups import load_derivation_groups  # noqa: F401
        self.dg = load_derivation_groups(SHAPE)

    def test_target_fields_include_new_fields(self):
        for f in _NEW_FIELDS:
            g = self.dg.group_by_id(_FIELD_GROUP[f])
            self.assertIn(f, g.target_fields, f)

    def test_source_questions_present_in_group_inputs(self):
        for f in _NEW_FIELDS:
            g = self.dg.group_by_id(_FIELD_GROUP[f])
            self.assertIn(_FIELD_SOURCE[f], g.input_question_ids,
                          f"{_FIELD_SOURCE[f]} must be in {g.group_id}.input_question_ids")


class ExtractionEnvelopeIsContractValid(unittest.TestCase):
    """Deriving each field via the CLI extraction path produces a DR-valid envelope."""

    def _derive_one(self, tmp_transcript: Path, field: str, value: str):
        import interview_cli as cli  # noqa: F401
        cli.cmd_derive_field(str(tmp_transcript), SHAPE, field, value,
                             sources=[_FIELD_SOURCE[field]], inputs=None, clock=lambda: CLOCK)
        cli.cmd_confirm_field(str(tmp_transcript), field, _FIELD_GROUP[field], "accepted",
                              clock=lambda: CLOCK)

    def test_extraction_envelope_validates_against_contract(self):
        import tempfile
        from transcript_recorder import TranscriptRecorder, read_derived_replay_events
        from derivation_replay import compile_transcript
        from derived_record import (load_contract, default_contract_path,
                                     validate_derived_record)
        from interview_cli import cmd_record_answer
        contract = load_contract(default_contract_path())
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "transcript.jsonl"
            values = {
                "UP_TECHNICAL_LITERACY": "plain language only",
                "NOTIFICATION_VERBOSITY": "Standard",
                "QA_REPORTING_STYLE": "Summary",
            }
            for f, v in values.items():
                cmd_record_answer(str(t), _FIELD_SOURCE[f], _FIELD_GROUP[f], v, clock=lambda: CLOCK)
                self._derive_one(t, f, v)
            record = compile_transcript(read_derived_replay_events(TranscriptRecorder(t).events()))
            # Full record validates (DR-1..DR-10), incl. DR-5 (no _derivation_inputs for
            # extraction) and DR-6 (decision coupling).
            validate_derived_record(record, contract)
            for f in _NEW_FIELDS:
                env = record["_audit"][f]
                self.assertEqual(env["_source"], "operator-content", f)
                self.assertEqual(env["_derivation_class"], "extraction", f)
                self.assertFalse(env["_decision_field"], f)
                self.assertEqual(env["_decision_kind"], "none", f)
                self.assertTrue(env.get("_source_question_ids"), f)
                self.assertNotIn("_derivation_inputs", env, f)  # DR-5 forbids for extraction


def _record_with_voice_answers(tmp_dir: Path, *, literacy: str, verbosity: str,
                                qa_style: str):
    """Build a minimal transcript carrying the three voice-source extraction fields
    (derived + confirmed) and return the projected foundation_doc_inputs."""
    import interview_cli as cli  # noqa: F401
    from transcript_recorder import TranscriptRecorder, read_derived_replay_events
    from derivation_replay import compile_transcript, project
    t = tmp_dir / "transcript.jsonl"
    values = {
        "UP_TECHNICAL_LITERACY": literacy,
        "NOTIFICATION_VERBOSITY": verbosity,
        "QA_REPORTING_STYLE": qa_style,
    }
    for f, v in values.items():
        cli.cmd_record_answer(str(t), _FIELD_SOURCE[f], _FIELD_GROUP[f], v, clock=lambda: CLOCK)
        cli.cmd_derive_field(str(t), SHAPE, f, v, sources=[_FIELD_SOURCE[f]], inputs=None,
                             clock=lambda: CLOCK)
        cli.cmd_confirm_field(str(t), f, _FIELD_GROUP[f], "accepted", clock=lambda: CLOCK)
    events = read_derived_replay_events(TranscriptRecorder(t).events())
    return project(compile_transcript(events))


class ProjectionCarriesOperatorValues(unittest.TestCase):
    """compile->project surfaces the three keys with the operator's confirmed values."""

    def test_three_keys_project_with_operator_values(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            fdi = _record_with_voice_answers(
                Path(d), literacy="comfortable with technical terms",
                verbosity="Detailed", qa_style="Live")
            self.assertEqual(fdi.get("UP_TECHNICAL_LITERACY"), "comfortable with technical terms")
            self.assertEqual(fdi.get("NOTIFICATION_VERBOSITY"), "Detailed")
            self.assertEqual(fdi.get("QA_REPORTING_STYLE"), "Live")


class DifferentialVoiceTest(unittest.TestCase):
    """Two operators with DIFFERENT technical-literacy answers get DIFFERENT voice values.

    This is the test that would have caught the theater bug: when the source keys did
    not project, voice values were constant for everyone.
    """

    def test_literacy_drives_distinct_technical_level(self):
        import tempfile
        from voice_settings import voice_settings_inputs
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            plain_fdi = _record_with_voice_answers(
                Path(d1), literacy="plain language only, no jargon",
                verbosity="Standard", qa_style="Summary")
            tech_fdi = _record_with_voice_answers(
                Path(d2), literacy="comfortable with technical terms",
                verbosity="Standard", qa_style="Summary")
            plain_voice = voice_settings_inputs(plain_fdi)
            tech_voice = voice_settings_inputs(tech_fdi)
            self.assertEqual(plain_voice["TECHNICAL_LEVEL"], "plain")
            self.assertIn(tech_voice["TECHNICAL_LEVEL"], ("technical", "some-technical"))
            self.assertNotEqual(plain_voice["TECHNICAL_LEVEL"], tech_voice["TECHNICAL_LEVEL"],
                                "voice must be operator-specific, not constant")


class ProjectInstructionsShowsRealValues(unittest.TestCase):
    """The scaffold-emitted project_instructions.md shows the operator's values, not
    the scaffold constants — via build_scaffold_inputs precedence."""

    def test_scaffold_merge_precedence_for_operator_values(self):
        """Merge-precedence only: directly-injected fdi values override scaffold constants.

        This proves the merge logic but does NOT drive the real derive->project pipeline
        (foundation_doc_inputs is hand-mutated). See
        test_real_pipeline_values_reach_scaffold_inputs for the end-to-end test.
        """
        import copy
        from scaffold_emitter import build_scaffold_inputs, _default_scaffold_inputs
        from emission_plan import (validate_emission_plan, load_contract,
                                    default_contract_path)
        from test_emission_plan import _valid_plan  # canonical valid plan fixture
        plan_dict = copy.deepcopy(_valid_plan())
        plan_dict["foundation_doc_inputs"]["UP_TECHNICAL_LITERACY"] = "plain language only"
        plan_dict["foundation_doc_inputs"]["NOTIFICATION_VERBOSITY"] = "Detailed"
        plan_dict["foundation_doc_inputs"]["QA_REPORTING_STYLE"] = "Live"
        plan = validate_emission_plan(plan_dict, load_contract(default_contract_path()))
        merged = build_scaffold_inputs(plan)
        # The scaffold constants are overridden by the operator's projected values.
        defaults = _default_scaffold_inputs()
        self.assertEqual(defaults["NOTIFICATION_VERBOSITY"], "standard")  # constant default
        self.assertEqual(defaults["QA_REPORTING_STYLE"], "summary")
        self.assertEqual(merged["UP_TECHNICAL_LITERACY"], "plain language only")
        self.assertEqual(merged["NOTIFICATION_VERBOSITY"], "Detailed")
        self.assertEqual(merged["QA_REPORTING_STYLE"], "Live")

    def test_real_pipeline_values_reach_scaffold_inputs(self):
        """End-to-end: values from the real derive->project pipeline reach build_scaffold_inputs.

        Uses _record_with_voice_answers (record-answer -> cmd_derive_field ->
        cmd_confirm_field -> compile_transcript -> project) to produce a real
        foundation_doc_inputs carrying UP_TECHNICAL_LITERACY / NOTIFICATION_VERBOSITY /
        QA_REPORTING_STYLE, then inserts it into a plan and asserts build_scaffold_inputs
        yields the operator's real values — NOT the scaffold constants
        ("standard" / "summary" / CONFIGURE).

        This is the load-bearing assertion that the prior test could not make: it
        proves the full pipeline deposits these three keys into foundation_doc_inputs
        as consumed by the emitter, not just that the merge layer honours them once
        they arrive by hand.
        """
        import copy
        import tempfile
        from scaffold_emitter import build_scaffold_inputs, _default_scaffold_inputs
        from emission_plan import (validate_emission_plan, load_contract,
                                    default_contract_path)
        from test_emission_plan import _valid_plan  # canonical valid plan fixture

        # Build a real foundation_doc_inputs through the derive->project pipeline.
        with tempfile.TemporaryDirectory() as d:
            real_fdi = _record_with_voice_answers(
                Path(d),
                literacy="comfortable with technical terms",
                verbosity="Detailed",
                qa_style="Live",
            )

        # The three keys must have been deposited by the real pipeline.
        self.assertEqual(real_fdi.get("UP_TECHNICAL_LITERACY"), "comfortable with technical terms",
                         "pipeline must project UP_TECHNICAL_LITERACY")
        self.assertEqual(real_fdi.get("NOTIFICATION_VERBOSITY"), "Detailed",
                         "pipeline must project NOTIFICATION_VERBOSITY")
        self.assertEqual(real_fdi.get("QA_REPORTING_STYLE"), "Live",
                         "pipeline must project QA_REPORTING_STYLE")

        # Merge those pipeline-produced values into a plan and verify scaffold sees them.
        plan_dict = copy.deepcopy(_valid_plan())
        plan_dict["foundation_doc_inputs"].update(real_fdi)
        plan = validate_emission_plan(plan_dict, load_contract(default_contract_path()))
        merged = build_scaffold_inputs(plan)

        # Scaffold constants must be overridden by the pipeline-produced values.
        defaults = _default_scaffold_inputs()
        self.assertEqual(defaults["NOTIFICATION_VERBOSITY"], "standard",
                         "scaffold constant is 'standard' — operator value must differ")
        self.assertEqual(defaults["QA_REPORTING_STYLE"], "summary",
                         "scaffold constant is 'summary' — operator value must differ")
        self.assertEqual(merged["UP_TECHNICAL_LITERACY"], "comfortable with technical terms")
        self.assertEqual(merged["NOTIFICATION_VERBOSITY"], "Detailed")
        self.assertEqual(merged["QA_REPORTING_STYLE"], "Live")


class VoiceInjectionGatedOnSourceFields(unittest.TestCase):
    """Replay-conformance fix: the voice-value injection is GATED on the voice source
    fields actually being present in foundation_doc_inputs.

    The regression: Task 3 added voice injection unconditionally, which RETROACTIVELY
    changed what a released version (e.g. v0.6.9) re-renders for docs/voice_and_style.md.
    A pre-v0.7.0 estate's capsule lacks the voice source fields, so it was installed with
    sentinel values; once injection ran unconditionally the re-render produced voice
    DEFAULTS instead, no longer reproducing the installed manifest base_hash, and the
    replay-conformance gate (correctly) REFUSED the upgrade.

    The fix data-gates the injection: with NO source field present, no voice keys are
    injected and the scaffold sentinels stand — so render(released version, old capsule)
    reproduces the installed sentinel content. With a source field present (a v0.7.0
    build), the derived values are injected as before.

    These tests exercise the real upgrade-time re-derivation entry point
    (derive_scaffold_render_inputs) so they cover all the injection sites uniformly
    (the gate lives inside voice_settings_inputs).
    """

    SHAPE = "markdown-CC"
    SENTINEL = "(operator-configures during setup)"
    VOICE_KEYS = (
        "TONE", "TECHNICAL_LEVEL", "EXPLANATION_DEPTH",
        "LENGTH_PREFERENCE", "LIST_STYLE", "TABLE_STYLE",
    )

    def _repo_root(self):
        return Path(__file__).resolve().parents[2]  # wizard/

    def test_old_capsule_without_source_fields_round_trips_to_sentinels(self):
        """render(v0.6.9, capsule WITHOUT voice source fields) leaves the voice keys at
        their installed sentinel values — no spurious drift, conformance restored."""
        from bundle_templates import derive_scaffold_render_inputs
        old_capsule_fdi = {"AUTONOMY_LEVEL": "1", "CORE_PURPOSE": "pre-v0.7.0 system"}
        out = derive_scaffold_render_inputs(
            system_shape=self.SHAPE,
            foundation_doc_inputs=old_capsule_fdi,
            project_name="LegacyEstate",
            target_version="v0.6.9",
            build_repo_root=self._repo_root(),
        )
        for k in self.VOICE_KEYS:
            self.assertEqual(
                out.get(k), self.SENTINEL,
                f"old-capsule voice key {k!r} must fall back to the installed sentinel "
                f"(got {out.get(k)!r}); a derived value here is the conformance regression",
            )

    def test_v070_capsule_with_source_fields_injects_derived_values(self):
        """render(v0.7.0, capsule WITH a voice source field) injects derived voice values
        (NOT sentinels) — the v0.7.0 behavior stays intact."""
        from bundle_templates import derive_scaffold_render_inputs
        new_capsule_fdi = {
            "AUTONOMY_LEVEL": "1",
            "CORE_PURPOSE": "v0.7.0 system",
            "UP_TECHNICAL_LITERACY": "plain language only",
            "NOTIFICATION_VERBOSITY": "Detailed",
            "QA_REPORTING_STYLE": "summary",
        }
        out = derive_scaffold_render_inputs(
            system_shape=self.SHAPE,
            foundation_doc_inputs=new_capsule_fdi,
            project_name="ModernEstate",
            target_version="v0.7.0",
            build_repo_root=self._repo_root(),
        )
        # Derived values, not sentinels.
        for k in self.VOICE_KEYS:
            self.assertNotEqual(
                out.get(k), self.SENTINEL,
                f"v0.7.0 capsule voice key {k!r} must be a derived value, not the sentinel",
            )
        self.assertEqual(out["TONE"], "plain-and-direct")
        self.assertEqual(out["TECHNICAL_LEVEL"], "plain")       # from UP_TECHNICAL_LITERACY
        self.assertEqual(out["EXPLANATION_DEPTH"], "detailed")  # from NOTIFICATION_VERBOSITY
        self.assertEqual(out["LENGTH_PREFERENCE"], "concise")   # from QA_REPORTING_STYLE


if __name__ == "__main__":
    unittest.main()
