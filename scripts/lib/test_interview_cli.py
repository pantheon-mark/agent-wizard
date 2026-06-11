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

import json
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
from transcript_recorder import TranscriptRecorder, read_derived_replay_events, read_agent_intents  # noqa: E402
import change_impact as ci  # noqa: E402
import derived_record  # noqa: E402
from derivation_groups import load_derivation_groups, parse_progress_markers, validate_marker_invariant  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
SHAPE = "markdown-CC"
SOURCE_VERSION = "v0.4.0"
CLOCK = "2026-05-30T12:00:00Z"

AUTO = {"SYSTEM_SHAPE": "markdown-CC", "FOUNDATION_ONLY_MODE": "false", "WIZARD_VERSION": "v0.4.0",
        "LAST_UPDATED_DATE": "2026-05-30", "LAST_UPDATED_TRIGGER": "initial build"}

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
    # 2. derive (authoring for the 6 vision sections; extraction for PROJECT_NAME/CORE_PURPOSE) + 3. confirm each
    for field, (value, sources) in VISION.items():
        cli.cmd_derive_field(transcript, SHAPE, field, value, sources=sources, inputs=None, clock=lambda: CLOCK)
        cli.cmd_confirm_field(transcript, field, "vision", "accepted", clock=lambda: CLOCK)
    return TranscriptRecorder(Path(transcript), clock=lambda: CLOCK)


def _drive_approach_roster_group(transcript, progress):
    """Record the approach_roster group through the CLI on top of a driven vision group.

    Synthesis fields cite prior DERIVED field keys (DR-5/DR-8), so vision must run first.
    The raw AP/ADV/ARCH answers are recorded as source events (load-bearing for the
    group-complete close gate + the source hash), and one agent intent is recorded."""
    _drive_vision_group(transcript, progress)
    g = load_derivation_groups(SHAPE).group_by_id("approach_roster")
    answered = {"UP-4", "AP-1", "AP-2", "AP-3", "ADV-1", "ARCH-2", "ARCH-3"}  # ADV-2/3/4 validly skipped
    for q in g.input_question_ids:
        if q in answered:
            cli.cmd_record_answer(transcript, q, "approach_roster", f"answer for {q}", clock=lambda: CLOCK)
        else:
            cli.cmd_skip_answer(transcript, q, "approach_roster", reason="no advisors", clock=lambda: CLOCK)
    # one agent intent (structured; persisted disk-first; consumed by the bridge at close)
    cli.cmd_record_agent_intent(
        transcript, "approach_roster", display_name="Monitor",
        function_summary="Watches for things that need attention.",
        role_intent="Monitors the operator's sources and surfaces what needs action.",
        acceptance_signals=["nothing important missed"], output_purpose="a daily digest",
        criticality_tier="standard", source_spans=["ARCH-2#1"], clock=lambda: CLOCK)
    # the two approach_roster target fields (synthesis; cite prior derived field keys)
    cli.cmd_derive_field(transcript, SHAPE, "APPROACH_SOLUTION_BRIEF",
                         "A monitoring-and-drafting approach that surfaces what the operator would miss.",
                         inputs=["CORE_PURPOSE", "VISION_PURPOSE", "VISION_GOALS"], clock=lambda: CLOCK)
    cli.cmd_confirm_field(transcript, "APPROACH_SOLUTION_BRIEF", "approach_roster", "accepted", clock=lambda: CLOCK)
    cli.cmd_derive_field(transcript, SHAPE, "AGENT_ROSTER_ROWS",
                         "| Agent | Role |\n|---|---|\n| Monitor | Watches sources |",
                         inputs=["APPROACH_SOLUTION_BRIEF"], clock=lambda: CLOCK)
    cli.cmd_confirm_field(transcript, "AGENT_ROSTER_ROWS", "approach_roster", "accepted", clock=lambda: CLOCK)
    # advisor knowledge base entries (extraction; from the confirmed advisor list ADV-1)
    cli.cmd_derive_field(transcript, SHAPE, "ADVISOR_ENTRIES",
                         "## Care coordinator\n\n**Domain:** care decisions\n**Status:** Active\n**Notes:** None",
                         sources=["ADV-1"], clock=lambda: CLOCK)
    cli.cmd_confirm_field(transcript, "ADVISOR_ENTRIES", "approach_roster", "accepted", clock=lambda: CLOCK)
    return TranscriptRecorder(Path(transcript), clock=lambda: CLOCK)


class ApproachRosterAcceptanceTests(unittest.TestCase):
    def test_transcript_compiles_and_validates(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl"); ppath = str(Path(td) / "wizard_progress.md")
            r = _drive_approach_roster_group(tpath, ppath)
            record = compile_transcript(read_derived_replay_events(r.events()))
            contract = derived_record.load_contract(derived_record.default_contract_path())
            derived_record.validate_derived_record(record, contract)   # raises on failure
            projected = project(record)
            self.assertIn("APPROACH_SOLUTION_BRIEF", projected)
            self.assertIn("AGENT_ROSTER_ROWS", projected)

    def test_preview_renders_approach_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl"); ppath = str(Path(td) / "wizard_progress.md")
            _drive_approach_roster_group(tpath, ppath)
            previews = cli.cmd_preview_group(tpath, SHAPE, "approach_roster", SOURCE_VERSION, REPO_ROOT, auto_values=AUTO)
            self.assertEqual([d for d, _ in previews], ["approach.md"])
            content = previews[0][1]
            self.assertNotIn("{{", content)
            self.assertIn("monitoring-and-drafting", content)

    def test_close_group_and_agent_intent_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl"); ppath = str(Path(td) / "wizard_progress.md")
            r = _drive_approach_roster_group(tpath, ppath)
            ev = cli.cmd_close_group(tpath, ppath, SHAPE, "approach_roster", clock=lambda: CLOCK)
            self.assertEqual(ev["event_type"], "group_confirmed")
            intents = read_agent_intents(r.events())
            self.assertEqual([a.display_name for a in intents], ["Monitor"])
            markers = parse_progress_markers(Path(ppath).read_text(encoding="utf-8"))
            self.assertIn("group_approach_roster_confirmed", markers)


def _record_sources(transcript, group_id, answered):
    """Record every input question of a group: answer those in `answered`, validly skip the rest
    (the group's skip_satisfied_if set is what makes a skip count toward completeness)."""
    g = load_derivation_groups(SHAPE).group_by_id(group_id)
    for q in g.input_question_ids:
        if q in answered:
            cli.cmd_record_answer(transcript, q, group_id, f"answer for {q}", clock=lambda: CLOCK)
        else:
            cli.cmd_skip_answer(transcript, q, group_id, reason="n/a", clock=lambda: CLOCK)


def _derive_confirm(transcript, field, group, value, *, sources=None, inputs=None,
                    state="accepted", revisit=None):
    cli.cmd_derive_field(transcript, SHAPE, field, value, sources=sources, inputs=inputs, clock=lambda: CLOCK)
    cli.cmd_confirm_field(transcript, field, group, state, revisit_trigger=revisit, clock=lambda: CLOCK)


# A canonical dependency record with one dependency that plays all three roles, so each of the
# three projections produces a row. JSON values (the identity/annotation fields render into no
# foundation doc, so a machine-parseable shape is free and is what makes the projection pure code).
_IDENTITY_VALUE = json.dumps([
    {"id": "google_sheet", "name": "Google Sheet task tracker", "type": "Spreadsheet",
     "roles": ["boundary_input", "health_monitored", "needs_credential"],
     "credential_facet": {"env_var": "GOOGLE_SHEETS_API_KEY", "cred_type": "API key",
                          "provider": "Google", "provisional_expiry": "Unknown"}},
])
_ANNOTATION_VALUE = json.dumps([
    {"id": "google_sheet", "purpose": "the master task list", "what_stops": "tracking stops",
     "boundary_input_facet": {"input_risk": "malformed rows mis-route work"}, "health_facet": {}},
])


def _drive_dependency_inventory_group(transcript, progress):
    """Drive the canonical dependency_inventory group atop approach_roster: capture the external
    dependencies ONCE as EXTERNAL_DEPENDENCY_IDENTITY (the integration-boundary decision surface).
    Closes at step_09; the three tabular registries are projections of it, derived later."""
    _drive_approach_roster_group(transcript, progress)
    _record_sources(transcript, "dependency_inventory", {"DEP-1"})
    _derive_confirm(transcript, "EXTERNAL_DEPENDENCY_IDENTITY", "dependency_inventory",
                    _IDENTITY_VALUE, sources=["DEP-1"])
    return TranscriptRecorder(Path(transcript), clock=lambda: CLOCK)


def _drive_orchestration_build_group(transcript, progress):
    """Drive orchestration_build atop the dependency_inventory group. Extraction/classification
    fields first so the synthesis fields can cite them as prior derived field keys (DR-5/DR-8).
    INTEGRATIONS authors prose from the canonical record; CREDENTIAL_REGISTRY_ROWS is a projection."""
    _drive_dependency_inventory_group(transcript, progress)
    _record_sources(transcript, "orchestration_build",
                    {"P1-4", "ARCH-1", "ARCH-2", "AP-1", "V-4", "V-6", "DEP-1", "CRED-3", "CRED-4",
                     "SCALE-1", "SCALE-2", "SCALE-3", "SCALE-4", "CONC-2"})
    _derive_confirm(transcript, "INTEGRATIONS", "orchestration_build", "- a Google Sheet task tracker",
                    inputs=["EXTERNAL_DEPENDENCY_IDENTITY"])
    # CREDENTIAL_REGISTRY_ROWS is a projection: computed deterministically from the canonical record
    # (the needs_credential subset), not hand-authored, and not separately confirmed (auto-projects).
    cli.cmd_derive_projection(transcript, SHAPE, "CREDENTIAL_REGISTRY_ROWS", clock=lambda: CLOCK)
    _derive_confirm(transcript, "CREDENTIAL_CHECK_CADENCE", "orchestration_build", "quarterly", sources=["CRED-4"])
    _derive_confirm(transcript, "ROTATION_LEAD_TIME_DAYS", "orchestration_build", "14", sources=["CRED-3"])
    _derive_confirm(transcript, "SCALE_TIER", "orchestration_build", "small", sources=["SCALE-1", "SCALE-2"])
    _derive_confirm(transcript, "ORCHESTRATION_MODEL", "orchestration_build",
                    "A single orchestrator routes work to specialists.", inputs=["INTEGRATIONS"])
    for f in ("SCALE_TIER_BASIS", "SCALE_TIER_RATIONALE"):
        _derive_confirm(transcript, f, "orchestration_build", "Low volume, single operator.", inputs=["SCALE_TIER"])
    _derive_confirm(transcript, "COMPLIANCE_GAPS_CONTENT", "orchestration_build",
                    "No regulated data in scope.", inputs=["INTEGRATIONS"])
    _derive_confirm(transcript, "TASK_COMPLETION_CHECKLISTS", "orchestration_build",
                    "- output written\n- handoff recorded", inputs=["ORCHESTRATION_MODEL"])
    # CAPABILITY_INCREMENTS: THE release-boundary decision (synthesis, decision_field -> forced
    # confirm). Derived FIRST among the execution-plan fields, from the approach brief + roster +
    # orchestration model + vision scope/success. BUILD_PHASES_ROWS + MVP_ROADMAP_BOUNDARY are then
    # deterministic projection views of it, and MVP_* prose derives from it (so they cannot
    # contradict each other). One increment in the MVP, one deferred to the roadmap.
    _derive_confirm(transcript, "CAPABILITY_INCREMENTS", "orchestration_build",
                    json.dumps([
                        {"capability": "first agent", "agents": "Monitor", "phase": 1, "release_bucket": "mvp"},
                        {"capability": "drafting helper", "agents": "Drafter", "phase": 2,
                         "release_bucket": "post_mvp_roadmap", "depends_on": "Phase 1",
                         "rationale": "after the spine is reliable"},
                    ]),
                    inputs=["APPROACH_SOLUTION_BRIEF", "AGENT_ROSTER_ROWS", "ORCHESTRATION_MODEL",
                            "VISION_SCOPE_BOUNDARY", "VISION_SUCCESS_CRITERIA"], state="accepted")
    # BUILD_PHASES_ROWS + MVP_ROADMAP_BOUNDARY are projections of CAPABILITY_INCREMENTS (pure code,
    # no separate confirm — auto-project from the confirmed source).
    cli.cmd_derive_projection(transcript, SHAPE, "BUILD_PHASES_ROWS", clock=lambda: CLOCK)
    cli.cmd_derive_projection(transcript, SHAPE, "MVP_ROADMAP_BOUNDARY", clock=lambda: CLOCK)
    _derive_confirm(transcript, "EXECUTION_SEQUENCE", "orchestration_build",
                    "- build the monitor first", inputs=["ORCHESTRATION_MODEL"])
    _derive_confirm(transcript, "MVP_CORE_FUNCTION", "orchestration_build",
                    "Surface what needs attention.", inputs=["CAPABILITY_INCREMENTS", "APPROACH_SOLUTION_BRIEF"])
    _derive_confirm(transcript, "MVP_MINIMUM_VIABLE_STATE", "orchestration_build",
                    "One agent runs daily.", inputs=["CAPABILITY_INCREMENTS", "APPROACH_SOLUTION_BRIEF"])
    _derive_confirm(transcript, "MVP_SUCCESS_CONDITION", "orchestration_build",
                    "The operator misses nothing important.", inputs=["CAPABILITY_INCREMENTS", "VISION_SUCCESS_CRITERIA"])
    return TranscriptRecorder(Path(transcript), clock=lambda: CLOCK)


def _drive_hitl_autonomy_group(transcript, progress):
    """Drive hitl_autonomy atop orchestration_build (execution_plan.md, hitl's preview, needs
    orchestration_build's MVP_*/BUILD_PHASES/EXECUTION fields — so orchestration must close first)."""
    _drive_orchestration_build_group(transcript, progress)
    _record_sources(transcript, "hitl_autonomy",
                    {"FIN-1", "FIN-3", "FIN-4", "UP-1", "UP-2", "UP-3", "UP-5", "NOTIF-1", "NOTIF-2", "NOTIF-3",
                     "ARCH-4", "ERR-1", "ERR-2", "CONC-1", "START-1", "START-2", "QA-2", "DR", "REV"})
    # AUTONOMY_LEVEL: now a classification (operator-preference) derived from the authority answers.
    _derive_confirm(transcript, "AUTONOMY_LEVEL", "hitl_autonomy", "2",
                    sources=["UP-3", "UP-5", "DR", "REV"], state="accepted")
    # HITL_MAP_ROWS: policy citing prior FIELDS (the authority posture + vision elevations), with
    # explicit negative permissions in the rows. (RW-46: reconciled from VISION_CONSTRAINTS to the
    # real field-level inputs; ARCH-4 is the answer-level edge declared in the manifest.)
    _derive_confirm(transcript, "HITL_MAP_ROWS", "hitl_autonomy",
                    "| Action | System behavior | Rationale |\n|---|---|---|\n"
                    "| Spend money | Always stop and ask; never spends autonomously | Irreversible |",
                    inputs=["AUTONOMY_LEVEL"])  # + TIER_1_ADDITIONS when the vision barrier produced it (optional)
    # Financial guardrail: POOL (extraction lookup) + SHARE/EXHAUSTION (classification) are the
    # operator's plain choices; BUDGET + THRESHOLD are DETERMINISTIC projections computed in pure
    # code (financial_projection.py via derive-projection) — never model-authored. POOL=$20 sole ->
    # budget round(20*0.9)=$18 -> threshold max(1, round(0.1*18))=$2.
    _derive_confirm(transcript, "AUTOMATION_CREDIT_POOL", "hitl_autonomy", "$20", sources=["FIN-1"])
    _derive_confirm(transcript, "PROJECT_SHARE_POSTURE", "hitl_autonomy", "sole", sources=["FIN-3"])
    _derive_confirm(transcript, "EXHAUSTION_BEHAVIOR", "hitl_autonomy", "wait", sources=["FIN-4"])
    cli.cmd_derive_projection(transcript, SHAPE, "PROJECT_AUTOMATION_BUDGET", clock=lambda: CLOCK)
    cli.cmd_derive_projection(transcript, SHAPE, "INTENSIVE_OPERATION_THRESHOLD", clock=lambda: CLOCK)
    return TranscriptRecorder(Path(transcript), clock=lambda: CLOCK)


def _drive_tests_audit_group(transcript, progress):
    """Drive tests_audit atop hitl_autonomy. Two preview docs (test_cases.md + audit_framework.md)."""
    _drive_hitl_autonomy_group(transcript, progress)
    _record_sources(transcript, "tests_audit", {"DEP-1", "GATE-1", "GATE-2", "QA-1", "QA-3", "ARCH-5", "DRIFT-1"})
    _derive_confirm(transcript, "AGENT_SPECIFIC_TESTS", "tests_audit",
                    "- monitor surfaces a known item", inputs=["APPROACH_SOLUTION_BRIEF"])
    _derive_confirm(transcript, "DRIFT_ANALYSIS_CADENCE", "tests_audit", "weekly", sources=["DRIFT-1"])
    # The content-only annotation of the canonical record (purpose/what-stops + per-role facets),
    # enriched here from the dependencies already in the identity record (no orphaned facets).
    _derive_confirm(transcript, "EXTERNAL_DEPENDENCY_ANNOTATION", "tests_audit",
                    _ANNOTATION_VALUE, sources=["DEP-1", "GATE-1", "QA-3"])
    # GATE-2 -> DOMAIN_SENSITIVITY_SETTINGS (classification-from-question; NOT a dependency facet).
    _derive_confirm(transcript, "DOMAIN_SENSITIVITY_SETTINGS", "tests_audit",
                    "| Financial | High | money is involved | 2026-06-10 |", sources=["GATE-2"])
    # The validation-gate input inventory + QA source registry are now deterministic PROJECTIONS of
    # the canonical record (boundary_input / health_monitored subsets), computed from the confirmed
    # IDENTITY + ANNOTATION, not hand-authored. They auto-project (no separate confirmation).
    cli.cmd_derive_projection(transcript, SHAPE, "INPUT_TYPE_INVENTORY", clock=lambda: CLOCK)
    cli.cmd_derive_projection(transcript, SHAPE, "SOURCE_REGISTRY_ROWS", clock=lambda: CLOCK)
    return TranscriptRecorder(Path(transcript), clock=lambda: CLOCK)


# operational barriers fire in registry order at step_13; close them in that order.
_OPERATIONAL = ["orchestration_build", "hitl_autonomy", "tests_audit"]


class FullFiveGroupAcceptanceTests(unittest.TestCase):
    """The whole unified interview through the CLI: vision -> approach_roster -> the 3 operational
    groups (all closing at step_13, in registry order). Proves the cross-group cumulative-preview
    dependency (execution_plan.md needs orchestration_build fields), AUTONOMY_LEVEL's provisional
    auto modeling, the HITL policy field, tests_audit's two preview docs, and a clean marker
    invariant once every step_13 group is confirmed."""

    def test_full_transcript_compiles_and_validates(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "t.jsonl"); ppath = str(Path(td) / "p.md")
            r = _drive_tests_audit_group(tpath, ppath)
            record = compile_transcript(read_derived_replay_events(r.events()))
            contract = derived_record.load_contract(derived_record.default_contract_path())
            derived_record.validate_derived_record(record, contract)   # raises on failure
            projected = project(record)
            for f in ("AUTONOMY_LEVEL", "HITL_MAP_ROWS", "MVP_CORE_FUNCTION",
                      "AGENT_SPECIFIC_TESTS", "DRIFT_ANALYSIS_CADENCE", "SCALE_TIER",
                      "CAPABILITY_INCREMENTS", "MVP_ROADMAP_BOUNDARY"):
                self.assertIn(f, projected, f"{f} did not project")

    def test_execution_plan_preview_renders_mvp_roadmap_boundary(self):
        # The anti-contradiction guarantee, observable in the emitted doc: execution_plan.md carries
        # the MVP-and-Roadmap-Boundary section, the deferred increment shows on the roadmap (not the
        # MVP), and no placeholder is left unresolved.
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "t.jsonl"); ppath = str(Path(td) / "p.md")
            _drive_tests_audit_group(tpath, ppath)
            previews = dict(cli.cmd_preview_group(tpath, SHAPE, "hitl_autonomy",
                                                  SOURCE_VERSION, REPO_ROOT, auto_values=AUTO))
            content = previews["execution_plan.md"]
            self.assertIn("MVP and Roadmap Boundary", content)
            self.assertIn("On the roadmap", content)
            self.assertIn("drafting helper", content)   # the post_mvp_roadmap increment, on the roadmap
            self.assertNotIn("{{", content)

    def test_autonomy_level_is_profile_derived_classification(self):
        # Post-flip: AUTONOMY_LEVEL is no longer a provisional auto-default — it is an
        # operator-preference classification derived from the authority answers (UP-3/UP-5/DR/REV).
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "t.jsonl"); ppath = str(Path(td) / "p.md")
            r = _drive_tests_audit_group(tpath, ppath)
            record = compile_transcript(read_derived_replay_events(r.events()))
            env = record["_audit"]["AUTONOMY_LEVEL"]
            self.assertEqual(env["_derivation_class"], "classification")   # flipped from auto
            self.assertEqual(env["_source"], "operator-preference")
            self.assertTrue(env["_decision_field"])                        # still a decision
            self.assertEqual(env["_confirmation_state"], "accepted")       # no longer provisional
            self.assertEqual(set(env["_source_question_ids"]), {"UP-3", "UP-5", "DR", "REV"})
            self.assertNotIn("_revisit_trigger", env)                      # provisional revisit removed

    def test_all_operational_previews_render(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "t.jsonl"); ppath = str(Path(td) / "p.md")
            _drive_tests_audit_group(tpath, ppath)
            expected = {"orchestration_build": ["technical_architecture.md"],
                        "hitl_autonomy": ["execution_plan.md"],
                        "tests_audit": ["test_cases.md", "audit_framework.md"]}
            for grp, docs in expected.items():
                previews = cli.cmd_preview_group(tpath, SHAPE, grp, SOURCE_VERSION, REPO_ROOT, auto_values=AUTO)
                self.assertEqual([d for d, _ in previews], docs)
                for _, content in previews:
                    self.assertNotIn("{{", content, f"{grp} preview has an unresolved placeholder")

    def test_marker_invariant_clean_after_all_groups_close(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "t.jsonl"); ppath = str(Path(td) / "p.md")
            _drive_tests_audit_group(tpath, ppath)
            cli.cmd_close_group(tpath, ppath, SHAPE, "vision", clock=lambda: CLOCK)
            cli.cmd_mark_step(ppath, "step_05", clock=lambda: CLOCK)
            cli.cmd_close_group(tpath, ppath, SHAPE, "approach_roster", clock=lambda: CLOCK)
            cli.cmd_mark_step(ppath, "step_08", clock=lambda: CLOCK)
            for grp in _OPERATIONAL:
                cli.cmd_close_group(tpath, ppath, SHAPE, grp, clock=lambda: CLOCK)
            cli.cmd_mark_step(ppath, "step_13", clock=lambda: CLOCK)
            dg = load_derivation_groups(SHAPE)
            markers = parse_progress_markers(Path(ppath).read_text(encoding="utf-8"))
            self.assertEqual(validate_marker_invariant(markers, dg), [])
            rp = cli.cmd_resume(ppath, SHAPE)
            self.assertEqual(rp["highest_completed_step"], 13)
            self.assertEqual(set(rp["confirmed_groups"]),
                             {"vision", "approach_roster", "orchestration_build", "hitl_autonomy", "tests_audit"})

    def test_step_13_illegal_before_all_operational_groups_close(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "t.jsonl"); ppath = str(Path(td) / "p.md")
            _drive_tests_audit_group(tpath, ppath)
            cli.cmd_close_group(tpath, ppath, SHAPE, "orchestration_build", clock=lambda: CLOCK)
            # close hitl + tests NOT done; step_13 marker is now illegal
            cli.cmd_mark_step(ppath, "step_13", clock=lambda: CLOCK)
            dg = load_derivation_groups(SHAPE)
            markers = parse_progress_markers(Path(ppath).read_text(encoding="utf-8"))
            violations = validate_marker_invariant(markers, dg)
            self.assertTrue(any("hitl_autonomy" in v for v in violations))
            self.assertTrue(any("tests_audit" in v for v in violations))


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
            # The six vision sections are AUTHORED narrative (claude-derived), not extraction.
            vp = record["_audit"]["VISION_PURPOSE"]
            self.assertEqual(vp["_derivation_class"], "authoring")
            self.assertEqual(vp["_source"], "claude-derived-operator-confirmed")
            self.assertIn("V-1", vp["_source_question_ids"])
            self.assertNotIn("_derivation_inputs", vp)   # answer-only at v0
            # PROJECT_NAME / CORE_PURPOSE stay extraction (names + core purpose are verbatim).
            self.assertEqual(record["_audit"]["PROJECT_NAME"]["_derivation_class"], "extraction")
            self.assertEqual(record["_audit"]["CORE_PURPOSE"]["_derivation_class"], "extraction")

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
    def test_source_override_honored_for_automation_credit_pool(self):
        # AUTOMATION_CREDIT_POOL is extraction-class but a plan-lookup; the manifest declares a
        # `source` override, so the envelope assembler stamps claude-derived (not operator-content).
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            ev = cli.cmd_derive_field(tpath, SHAPE, "AUTOMATION_CREDIT_POOL", "$20",
                                      sources=["FIN-1"], inputs=None, clock=lambda: CLOCK)
            self.assertEqual(ev["envelope"]["_source"], "claude-derived-operator-confirmed")
            self.assertEqual(ev["envelope"]["_derivation_class"], "extraction")
            self.assertEqual(ev["envelope"]["_source_question_ids"], ["FIN-1"])

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


class AgentIntentCLITests(unittest.TestCase):
    def test_record_agent_intent_round_trips_through_cli(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            cli.cmd_record_agent_intent(
                tpath, "approach_roster",
                display_name="Researcher", function_summary="Gathers source material.",
                role_intent="Gathers source material for the operator.",
                acceptance_signals=["non-empty summary"], output_purpose="a summary",
                criticality_tier="critical", requires_cron=True,
                confidence="high", source_spans=["ARCH-2#1"], clock=lambda: CLOCK)
            intents = read_agent_intents(TranscriptRecorder(Path(tpath)).events())
            self.assertEqual([a.display_name for a in intents], ["Researcher"])
            self.assertTrue(intents[0].resource_claims.requires_cron)
            self.assertEqual(intents[0].criticality_tier, "critical")

    def test_record_agent_intent_bad_criticality_fails_loud(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "transcript.jsonl")
            with self.assertRaises(cli.InterviewCLIError):
                cli.cmd_record_agent_intent(
                    tpath, "approach_roster", display_name="X", function_summary="f",
                    role_intent="r", acceptance_signals=["s"], output_purpose="o",
                    criticality_tier="MEGA", clock=lambda: CLOCK)


class EmitSystemCLITests(unittest.TestCase):
    def test_emit_system_emits_a_complete_tree_from_a_transcript_file(self):
        # Build a RICH-shape transcript on disk (the recorder's vocabulary, as the live wizard
        # records) from the proven-emittable neutral field set, then emit through the CLI command.
        from test_emission_plan import _FOUNDATION_DOC_INPUTS
        from test_interview_bridge import _ai
        env = {"_source": "operator-content", "_derivation_class": "extraction",
               "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td) / "t.jsonl"
            r = TranscriptRecorder(tpath, clock=lambda: CLOCK)
            for k, v in _FOUNDATION_DOC_INPUTS.items():
                r.record_derived_field(k, "vision", v, dict(env))
                r.record_field_confirmation(k, "vision", "accepted")
            r.record_agent_intent("approach_roster", _ai())   # one agent -> full-system path
            target = Path(td) / "operator-project"
            rec = cli.cmd_emit_system(str(tpath), SHAPE, str(target), str(REPO_ROOT),
                                      generator_version_override="0" * 40)
            self.assertFalse(rec["foundation_only_mode"])
            self.assertTrue(rec["derived_record_hash"].startswith("sha256:"))
            tree = {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()}
            self.assertIn("vision.md", tree)
            self.assertTrue(any(t.endswith("CLAUDE.md") for t in tree))
            self.assertTrue(any(t.startswith("agents/prompts/") for t in tree))
            self.assertIn("quality/advisor_knowledge_base.md", tree)

    def test_emit_projects_gate_answers_into_validation_config(self):
        # Validation-gate regression: GATE-1/GATE-2 derivations must reach the EMITTED
        # quality/validation_gate_config.md (not just be present as a file with EMPTY tables).
        # Before the fix the scaffold hardcoded both placeholders to "" so this assertion would fail.
        from test_emission_plan import _FOUNDATION_DOC_INPUTS
        from test_interview_bridge import _ai
        base_env = {"_source": "operator-content", "_derivation_class": "extraction",
                    "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td) / "t.jsonl"
            r = TranscriptRecorder(tpath, clock=lambda: CLOCK)
            for k, v in _FOUNDATION_DOC_INPUTS.items():
                r.record_derived_field(k, "vision", v, dict(base_env))
                r.record_field_confirmation(k, "vision", "accepted")
            r.record_agent_intent("approach_roster", _ai())
            # The two validation-gate fields with their real envelopes (extraction decision / classification decision).
            inv_env = {"_source": "operator-content", "_derivation_class": "extraction",
                       "_decision_field": True, "_decision_kind": "integration_boundary",
                       "_source_question_ids": ["GATE-1"], "_prompt_version": "sha256:p1"}
            sens_env = {"_source": "operator-preference", "_derivation_class": "classification",
                        "_decision_field": True, "_decision_kind": "threshold",
                        "_source_question_ids": ["GATE-2"], "_prompt_version": "sha256:p1"}
            r.record_derived_field("INPUT_TYPE_INVENTORY", "tests_audit",
                                   "| Spreadsheet rows | Google Sheet | the task list | reports break | (runtime) | Active |",
                                   inv_env)
            r.record_field_confirmation("INPUT_TYPE_INVENTORY", "tests_audit", "accepted")
            r.record_derived_field("DOMAIN_SENSITIVITY_SETTINGS", "tests_audit",
                                   "| Financial | High | money is involved | 2026-06-10 |", sens_env)
            r.record_field_confirmation("DOMAIN_SENSITIVITY_SETTINGS", "tests_audit", "accepted")
            target = Path(td) / "operator-project"
            cli.cmd_emit_system(str(tpath), SHAPE, str(target), str(REPO_ROOT),
                                generator_version_override="0" * 40)
            vgc = (target / "quality/validation_gate_config.md").read_text()
            self.assertIn("Spreadsheet rows", vgc, "GATE-1 inventory did not reach validation_gate_config.md")
            self.assertIn("Financial", vgc, "GATE-2 sensitivity did not reach validation_gate_config.md")
            self.assertNotIn("{{INPUT_TYPE_INVENTORY}}", vgc)
            self.assertNotIn("{{DOMAIN_SENSITIVITY_SETTINGS}}", vgc)

    def test_emit_projects_qa3_into_source_registry(self):
        # RW-40 regression: QA-3 (source registry) must reach the EMITTED quality/source_registry.md.
        # Before the fix the template carried NO placeholder and QA-3 was a dead input, so the
        # emitted registry shipped with an EMPTY table. Mirrors the validation-gate regression above.
        from test_emission_plan import _FOUNDATION_DOC_INPUTS
        from test_interview_bridge import _ai
        base_env = {"_source": "operator-content", "_derivation_class": "extraction",
                    "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td) / "t.jsonl"
            r = TranscriptRecorder(tpath, clock=lambda: CLOCK)
            for k, v in _FOUNDATION_DOC_INPUTS.items():
                r.record_derived_field(k, "vision", v, dict(base_env))
                r.record_field_confirmation(k, "vision", "accepted")
            r.record_agent_intent("approach_roster", _ai())
            # QA-3 source registry: extraction decision (integration_boundary). Rows-only; runtime
            # cells (Expected behavior / Last verified / Health flag) carry placeholders, Status=Pending.
            src_env = {"_source": "operator-content", "_derivation_class": "extraction",
                       "_decision_field": True, "_decision_kind": "integration_boundary",
                       "_source_question_ids": ["QA-3"], "_prompt_version": "sha256:p1"}
            r.record_derived_field("SOURCE_REGISTRY_ROWS", "tests_audit",
                                   "| Google Sheet | API | the master task list | tracking stops | (set at runtime) | Pending | (set at runtime) | Pending |",
                                   src_env)
            r.record_field_confirmation("SOURCE_REGISTRY_ROWS", "tests_audit", "accepted")
            target = Path(td) / "operator-project"
            cli.cmd_emit_system(str(tpath), SHAPE, str(target), str(REPO_ROOT),
                                generator_version_override="0" * 40)
            sr = (target / "quality/source_registry.md").read_text()
            self.assertIn("Google Sheet", sr, "QA-3 source did not reach source_registry.md")
            self.assertNotIn("{{SOURCE_REGISTRY_ROWS}}", sr)

    def test_emit_projects_financial_guardrail_into_instructions_and_cost_log(self):
        # RW-46 / D-EMIT regression (the IS-1 closure this guardrail claimed): the DETERMINISTIC
        # financial projection (pool x share -> budget; 10% -> threshold) must reach the emitted
        # project_instructions.md + cost_efficiency_log.md as real dollars, not the CONFIGURE
        # fallbacks. Drives the real derive-projection path so the value is pure-code, not authored.
        from test_emission_plan import _FOUNDATION_DOC_INPUTS
        from test_interview_bridge import _ai
        base_env = {"_source": "operator-content", "_derivation_class": "extraction",
                    "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td) / "t.jsonl"
            r = TranscriptRecorder(tpath, clock=lambda: CLOCK)
            for k, v in _FOUNDATION_DOC_INPUTS.items():
                r.record_derived_field(k, "vision", v, dict(base_env))
                r.record_field_confirmation(k, "vision", "accepted")
            r.record_agent_intent("approach_roster", _ai())
            # Plain operator choices: pool (extraction lookup) + sharing posture (classification).
            pool_env = {"_source": "claude-derived-operator-confirmed", "_derivation_class": "extraction",
                        "_decision_field": False, "_decision_kind": "none",
                        "_source_question_ids": ["FIN-1"], "_prompt_version": "sha256:p1"}
            share_env = {"_source": "operator-preference", "_derivation_class": "classification",
                         "_decision_field": True, "_decision_kind": "closed_value",
                         "_source_question_ids": ["FIN-3"], "_prompt_version": "sha256:p1"}
            r.record_derived_field("AUTOMATION_CREDIT_POOL", "hitl_autonomy", "$100", pool_env)
            r.record_field_confirmation("AUTOMATION_CREDIT_POOL", "hitl_autonomy", "accepted")
            r.record_derived_field("PROJECT_SHARE_POSTURE", "hitl_autonomy", "one-of-several", share_env)
            r.record_field_confirmation("PROJECT_SHARE_POSTURE", "hitl_autonomy", "accepted")
            # The money is computed by pure code, not authored: $100 x 0.4 = $40; 10% -> $4.
            cli.cmd_derive_projection(str(tpath), SHAPE, "PROJECT_AUTOMATION_BUDGET", clock=lambda: CLOCK)
            cli.cmd_derive_projection(str(tpath), SHAPE, "INTENSIVE_OPERATION_THRESHOLD", clock=lambda: CLOCK)
            target = Path(td) / "operator-project"
            cli.cmd_emit_system(str(tpath), SHAPE, str(target), str(REPO_ROOT),
                                generator_version_override="0" * 40)
            pi = (target / "project_instructions.md").read_text()
            self.assertIn("$40", pi, "deterministic budget did not reach project_instructions.md")
            self.assertNotIn("{{PROJECT_AUTOMATION_BUDGET}}", pi)
            self.assertNotIn("{{INTENSIVE_OPERATION_THRESHOLD}}", pi)
            cel = (target / "logs/cost_efficiency_log.md").read_text()
            self.assertIn("$40", cel, "deterministic budget did not reach cost_efficiency_log.md")
            self.assertNotIn("{{PROJECT_AUTOMATION_BUDGET}}", cel)

    def test_emit_system_foundation_only_from_a_transcript_file(self):
        # The other e2e branch: a foundation-only transcript (FOUNDATION_ONLY_MODE=true, zero
        # agent intents) emits the foundation docs through the CLI WITHOUT the agent layer.
        from test_emission_plan import _FOUNDATION_DOC_INPUTS
        env = {"_source": "operator-content", "_derivation_class": "extraction",
               "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
        inputs = dict(_FOUNDATION_DOC_INPUTS)
        inputs["FOUNDATION_ONLY_MODE"] = "true"
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td) / "t.jsonl"
            r = TranscriptRecorder(tpath, clock=lambda: CLOCK)
            for k, v in inputs.items():
                r.record_derived_field(k, "vision", v, dict(env))
                r.record_field_confirmation(k, "vision", "accepted")
            # NO agent intent recorded -> the foundation-only branch
            target = Path(td) / "operator-project"
            rec = cli.cmd_emit_system(str(tpath), SHAPE, str(target), str(REPO_ROOT),
                                      generator_version_override="0" * 40)
            self.assertTrue(rec["foundation_only_mode"])
            tree = {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()}
            # foundation-only emits the foundation BUNDLE layout (docs under foundation/ + the
            # .wizard manifest), distinct from the full system's root-level docs.
            self.assertIn("foundation/vision.md", tree)
            self.assertFalse(any(t.startswith("agents/") for t in tree),
                             "foundation-only emission must not emit the agent layer")

    def test_emit_system_fails_closed_on_stale_group(self):
        # Defense-in-depth (cross-vendor close Finding C): a group confirmed earlier whose
        # upstream source answer changed AFTER confirmation (stale group_source_hash) must
        # abort emit before any write — the carrier re-confirms interactively, but emit must
        # not trust that and silently emit content derived from superseded answers.
        from test_emission_plan import _FOUNDATION_DOC_INPUTS
        from test_interview_bridge import _ai
        from derivation_groups import load_derivation_groups
        from transcript_recorder import group_source_hash, source_event_range
        env = {"_source": "operator-content", "_derivation_class": "extraction",
               "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td) / "t.jsonl"
            r = TranscriptRecorder(tpath, clock=lambda: CLOCK)
            g = load_derivation_groups(SHAPE).group_by_id("vision")
            skippable = set(g.skip_satisfied_if)
            for q in g.input_question_ids:                       # source answers
                if q in skippable:
                    r.record_source_skip(q, "vision", reason="n/a")
                else:
                    r.record_source_answer(q, "vision", f"answer for {q}")
            for k, v in _FOUNDATION_DOC_INPUTS.items():          # full record (emit would otherwise succeed)
                r.record_derived_field(k, "vision", v, dict(env))
                r.record_field_confirmation(k, "vision", "accepted")
            r.record_agent_intent("approach_roster", _ai())
            # confirm the vision group with the source hash AS OF NOW (mirrors close_group's marker)
            _ev = r.events()
            r.record_group_confirmed("vision", source_event_range(_ev, g.input_question_ids),
                                     group_source_hash(_ev, g.input_question_ids), confirmed_at=CLOCK)
            edit_q = next(q for q in g.input_question_ids if q not in skippable)
            r.record_source_answer(edit_q, "vision", "EDITED after the group was confirmed")  # -> stale
            target = Path(td) / "operator-project"
            with self.assertRaises(cli.InterviewCLIError):
                cli.cmd_emit_system(str(tpath), SHAPE, str(target), str(REPO_ROOT),
                                    generator_version_override="0" * 40)
            self.assertFalse(target.exists(), "emit must fail closed BEFORE writing on a stale group")

    def test_record_impact_disposition_cli_resolves_pending(self):
        # The carrier records a detected change + the operator's disposition via the CLI; the
        # emit-gate projection then sees no pending implication.
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "t.jsonl")
            cli.cmd_record_impact_change(
                tpath, "chg-9",
                [{"node_kind": "field", "node_id": "AUTONOMY_LEVEL",
                  "impact_class": ci.RULE_DECISION}])
            events = TranscriptRecorder(Path(tpath)).events()
            self.assertEqual(len(ci.pending_from_events(events)), 1)  # before disposition
            cli.cmd_record_impact_disposition(tpath, "chg-9", "field", "AUTONOMY_LEVEL", ci.APPLY)
            events = TranscriptRecorder(Path(tpath)).events()
            self.assertEqual(ci.pending_from_events(events), [])     # resolved

    def test_record_impact_disposition_cli_rejects_unknown_disposition(self):
        with tempfile.TemporaryDirectory() as td:
            tpath = str(Path(td) / "t.jsonl")
            with self.assertRaises(cli.InterviewCLIError):
                cli.cmd_record_impact_disposition(tpath, "chg-9", "field", "X", "banana")

    def _emittable_recorder(self, td, env):
        """A full, otherwise-emittable rich transcript (the proven neutral field set + one agent)."""
        from test_emission_plan import _FOUNDATION_DOC_INPUTS
        from test_interview_bridge import _ai
        tpath = Path(td) / "t.jsonl"
        r = TranscriptRecorder(tpath, clock=lambda: CLOCK)
        for k, v in _FOUNDATION_DOC_INPUTS.items():
            r.record_derived_field(k, "vision", v, dict(env))
            r.record_field_confirmation(k, "vision", "accepted")
        r.record_agent_intent("approach_roster", _ai())
        return r, tpath

    def test_emit_system_fails_closed_on_undispositioned_rule_decision(self):
        # The new enforcement dimension: an otherwise-emittable transcript that carries a
        # detected change with an un-dispositioned RULE-DECISION implication must fail closed
        # before any write (never silently ship a system with an undecided rule/decision change).
        env = {"_source": "operator-content", "_derivation_class": "extraction",
               "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
        with tempfile.TemporaryDirectory() as td:
            r, tpath = self._emittable_recorder(td, env)
            r.record_impact_change("chg-1", [
                {"node_kind": "field", "node_id": "AUTONOMY_LEVEL",
                 "impact_class": ci.RULE_DECISION},
            ])
            target = Path(td) / "operator-project"
            with self.assertRaises(cli.InterviewCLIError):
                cli.cmd_emit_system(str(tpath), SHAPE, str(target), str(REPO_ROOT),
                                    generator_version_override="0" * 40)
            self.assertFalse(target.exists(),
                             "emit must fail closed BEFORE writing on an un-dispositioned implication")

    def test_emit_system_proceeds_when_rule_decision_dispositioned(self):
        # Positive control (guards against over-blocking): once the rule-decision implication is
        # dispositioned (apply), emit proceeds normally.
        env = {"_source": "operator-content", "_derivation_class": "extraction",
               "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
        with tempfile.TemporaryDirectory() as td:
            r, tpath = self._emittable_recorder(td, env)
            r.record_impact_change("chg-1", [
                {"node_kind": "field", "node_id": "AUTONOMY_LEVEL",
                 "impact_class": ci.RULE_DECISION},
            ])
            r.record_impact_disposition("chg-1", "field", "AUTONOMY_LEVEL", ci.APPLY)
            target = Path(td) / "operator-project"
            rec = cli.cmd_emit_system(str(tpath), SHAPE, str(target), str(REPO_ROOT),
                                      generator_version_override="0" * 40)
            self.assertFalse(rec["foundation_only_mode"])
            self.assertTrue(target.exists())

    def test_emit_system_fails_closed_on_unconfirmed_sourced_group(self):
        # Cross-vendor close R2 (codex blocker): a LIVE group that recorded source answers but was
        # never confirmed (no group_confirmed marker — a carrier that skipped the rendered-preview
        # confirmation) must abort emit. Tolerating missing markers applies ONLY to field-only /
        # foundation-only transcripts with no source events.
        from test_emission_plan import _FOUNDATION_DOC_INPUTS
        from test_interview_bridge import _ai
        from derivation_groups import load_derivation_groups
        env = {"_source": "operator-content", "_derivation_class": "extraction",
               "_decision_field": False, "_decision_kind": "none", "_prompt_version": "sha256:p1"}
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td) / "t.jsonl"
            r = TranscriptRecorder(tpath, clock=lambda: CLOCK)
            g = load_derivation_groups(SHAPE).group_by_id("vision")
            skippable = set(g.skip_satisfied_if)
            for q in g.input_question_ids:                       # source answers recorded ...
                if q in skippable:
                    r.record_source_skip(q, "vision", reason="n/a")
                else:
                    r.record_source_answer(q, "vision", f"answer for {q}")
            for k, v in _FOUNDATION_DOC_INPUTS.items():
                r.record_derived_field(k, "vision", v, dict(env))
                r.record_field_confirmation(k, "vision", "accepted")
            r.record_agent_intent("approach_roster", _ai())
            # ... but the vision group is NEVER confirmed (no group_confirmed marker)
            target = Path(td) / "operator-project"
            with self.assertRaises(cli.InterviewCLIError):
                cli.cmd_emit_system(str(tpath), SHAPE, str(target), str(REPO_ROOT),
                                    generator_version_override="0" * 40)
            self.assertFalse(target.exists(),
                             "emit must fail closed BEFORE writing on a sourced-but-unconfirmed group")


if __name__ == "__main__":
    unittest.main()
