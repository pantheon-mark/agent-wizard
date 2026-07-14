"""Tests for build_progress.md acceptance ledger emission (Task C1).

Covers:
  - assemble_emission_plan injects BUILD_PROGRESS_ROWS into foundation_doc_inputs;
  - BUILD_PROGRESS_ROWS contains one row per committed phase (no candidate_conditional);
  - each row carries phase, capability, current-state vocabulary token, and column stubs;
  - state vocabulary tokens present: built / technically-reviewed / supervised /
    provisionally-accepted / accepted;
  - emit_scaffold writes build_progress.md to the staging root;
  - the on-disk file contains the rendered rows, the state vocabulary legend, and
    the Layer-B tri-state verdict legend;
  - zero committed phases -> BUILD_PROGRESS_ROWS is empty (placeholder resolves, no error);
  - row count matches committed-phase count (anti-overfit: derived from fixture, not hardcoded).

Anti-overfit fixture: 3 phases / 2 agents (matches test_acceptance_contract_emit.py;
NOT the 6-agent demo estate). Row count is asserted by counting committed phases,
not hardcoded to 3.

Stdlib-only, pip-install-free.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_emission_plan import _FOUNDATION_DOC_INPUTS, _valid_plan  # noqa: E402
from scaffold_plan import load_scaffold_plan  # noqa: E402
from build_intent import BuildIntent, AgentIntent, ResourceClaims  # noqa: E402
from corpus_loader import load_corpus_pack  # noqa: E402
from emission_plan_assembler import assemble_emission_plan  # noqa: E402
from emission_plan import validate_emission_plan, load_contract, default_contract_path  # noqa: E402
from scaffold_emitter import emit_scaffold  # noqa: E402
from capability_projection import BUCKET_MVP, BUCKET_ROADMAP  # noqa: E402

SP = load_scaffold_plan("markdown-CC")
CORPUS = load_corpus_pack()
EP_CONTRACT = load_contract(default_contract_path())
REPO_ROOT = Path(__file__).resolve().parents[3]

# State vocabulary tokens the ledger must record.
_STATE_VOCAB = [
    "built",
    "technically-reviewed",
    "supervised",
    "provisionally-accepted",
    "accepted",
]

# Layer-B tri-state verdict tokens.
_LAYER_B_VERDICTS = [
    "confirmed",
    "fix-needed",
    "deferred-pending-real-use",
]

# Three-phase / two-agent fixture (same as test_acceptance_contract_emit.py).
_THREE_PHASE_INCREMENTS = [
    {
        "capability": "Ingest incoming items",
        "release_bucket": "mvp",
        "phase": 1,
        "agents": "Collector",
        "depends_on": [],
    },
    {
        "capability": "Summarise daily batch",
        "release_bucket": "post_mvp_roadmap",
        "phase": 2,
        "agents": "Summariser",
        "depends_on": ["Ingest incoming items"],
    },
    {
        "capability": "Archive processed items",
        "release_bucket": "post_mvp_roadmap",
        "phase": 3,
        "agents": "Collector",
        "depends_on": ["Summarise daily batch"],
    },
    {
        "capability": "Export to external system",
        "release_bucket": "candidate_conditional",
        "phase": None,
        "condition": "If the operator needs external reporting",
        "agents": "Summariser",
        "depends_on": [],
    },
]

_COMMITTED_COUNT = sum(
    1 for inc in _THREE_PHASE_INCREMENTS
    if inc["release_bucket"] in (BUCKET_MVP, BUCKET_ROADMAP)
)  # 3


def _env(cstate="accepted"):
    return {
        "_source": "operator-content",
        "_derivation_class": "extraction",
        "_decision_field": False,
        "_decision_kind": "none",
        "_confirmation_state": cstate,
        "_confirmed_at": "2026-05-30",
    }


def _dr_with_increments():
    inp = dict(_FOUNDATION_DOC_INPUTS)
    inp["CAPABILITY_INCREMENTS"] = json.dumps(_THREE_PHASE_INCREMENTS)
    rec = dict(inp)
    rec["_audit"] = {k: _env("accepted") for k in inp}
    return rec


def _dr_no_increments():
    inp = dict(_FOUNDATION_DOC_INPUTS)
    rec = dict(inp)
    rec["_audit"] = {k: _env("accepted") for k in inp}
    return rec


def _ai_collector():
    return AgentIntent(
        display_name="Collector",
        function_summary="Collects incoming items.",
        role_intent="Collects incoming items.",
        acceptance_signals=["items collected without error"],
        output_purpose="item list",
        criticality_tier="standard",
        resource_claims=ResourceClaims(),
        confidence="high",
        insufficiency_flags=[],
        source_spans=["ARCH-1#1"],
    )


def _ai_summariser():
    return AgentIntent(
        display_name="Summariser",
        function_summary="Produces a daily summary.",
        role_intent="Produces a daily summary.",
        acceptance_signals=["non-empty summary produced"],
        output_purpose="summary",
        criticality_tier="standard",
        resource_claims=ResourceClaims(),
        confidence="high",
        insufficiency_flags=[],
        source_spans=["ARCH-1#2"],
    )


class BuildProgressRowsAssemblerTests(unittest.TestCase):
    """BUILD_PROGRESS_ROWS rendered in the assembler and present in foundation_doc_inputs."""

    def _assemble(self, dr, agents=None):
        if agents is None:
            agents = [_ai_collector(), _ai_summariser()]
        bi = BuildIntent(derived_record=dr, agent_intents=agents)
        return assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)

    def test_build_progress_rows_in_foundation_doc_inputs(self):
        """BUILD_PROGRESS_ROWS is present in plan['foundation_doc_inputs']."""
        plan = self._assemble(_dr_with_increments())
        self.assertIn(
            "BUILD_PROGRESS_ROWS",
            plan["foundation_doc_inputs"],
            "BUILD_PROGRESS_ROWS missing from foundation_doc_inputs",
        )

    def test_build_progress_rows_has_one_row_per_committed_phase(self):
        """BUILD_PROGRESS_ROWS has exactly _COMMITTED_COUNT table rows (no candidate rows)."""
        plan = self._assemble(_dr_with_increments())
        rows_text = plan["foundation_doc_inputs"]["BUILD_PROGRESS_ROWS"]
        # Count pipe-delimited rows (each table row starts with '|').
        rows = [line for line in rows_text.splitlines() if line.strip().startswith("|")]
        self.assertEqual(
            len(rows),
            _COMMITTED_COUNT,
            f"expected {_COMMITTED_COUNT} ledger rows, got {len(rows)}: {rows_text!r}",
        )

    def test_build_progress_rows_open_state_is_not_started(self):
        """Option A: a freshly emitted ledger opens every phase as 'not-started', NOT
        'built' — the operator hasn't brought any phase into operation yet; 'built' (and
        the later states) are earned through the build-and-operate loop. This keeps the
        ledger consistent with session_bootstrap ('nothing built yet') instead of
        contradicting it (the cross-file discrepancy a fresh operator session flagged)."""
        plan = self._assemble(_dr_with_increments())
        rows_text = plan["foundation_doc_inputs"]["BUILD_PROGRESS_ROWS"]
        rows = [l for l in rows_text.splitlines() if l.strip().startswith("|")]
        self.assertTrue(rows, "no ledger rows emitted")
        for r in rows:
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            state = cells[2]  # phase | capability | STATE | Layer-A | ...
            self.assertEqual(
                state, "not-started",
                f"ledger row opens in {state!r}, expected 'not-started' (Option A)",
            )

    def test_build_progress_rows_contains_phase_one_capability(self):
        """Phase 1 capability text appears in BUILD_PROGRESS_ROWS."""
        plan = self._assemble(_dr_with_increments())
        rows_text = plan["foundation_doc_inputs"]["BUILD_PROGRESS_ROWS"]
        self.assertIn("Ingest incoming items", rows_text)

    def test_build_progress_rows_contains_all_capabilities(self):
        """All committed phase capabilities appear in BUILD_PROGRESS_ROWS."""
        plan = self._assemble(_dr_with_increments())
        rows_text = plan["foundation_doc_inputs"]["BUILD_PROGRESS_ROWS"]
        self.assertIn("Summarise daily batch", rows_text)
        self.assertIn("Archive processed items", rows_text)

    def test_candidate_conditional_excluded_from_rows(self):
        """candidate_conditional phases do NOT appear in BUILD_PROGRESS_ROWS."""
        plan = self._assemble(_dr_with_increments())
        rows_text = plan["foundation_doc_inputs"]["BUILD_PROGRESS_ROWS"]
        self.assertNotIn("Export to external system", rows_text)

    def test_no_increments_yields_empty_rows(self):
        """Missing CAPABILITY_INCREMENTS -> BUILD_PROGRESS_ROWS is empty string."""
        plan = self._assemble(_dr_no_increments(), agents=[_ai_collector()])
        rows_text = plan["foundation_doc_inputs"].get("BUILD_PROGRESS_ROWS", None)
        self.assertIsNotNone(rows_text, "BUILD_PROGRESS_ROWS key must be present even with no increments")
        self.assertEqual(rows_text, "", f"expected empty string, got {rows_text!r}")

    def test_row_count_matches_committed_phase_count(self):
        """Row count is dynamically equal to the number of committed phases (anti-overfit)."""
        plan = self._assemble(_dr_with_increments())
        rows_text = plan["foundation_doc_inputs"]["BUILD_PROGRESS_ROWS"]
        rows = [line for line in rows_text.splitlines() if line.strip().startswith("|")]
        # Committed count was derived from the same fixture, not hardcoded.
        self.assertEqual(len(rows), _COMMITTED_COUNT)


class BuildProgressOnDiskTests(unittest.TestCase):
    """build_progress.md emitted on disk with correct structure."""

    def _assemble_and_emit(self, dr=None):
        if dr is None:
            dr = _dr_with_increments()
        bi = BuildIntent(derived_record=dr, agent_intents=[_ai_collector(), _ai_summariser()])
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        typed_plan = validate_emission_plan(plan_dict, EP_CONTRACT)
        staging_dir = Path(tempfile.mkdtemp())
        emit_scaffold(typed_plan, staging_dir, REPO_ROOT)
        return staging_dir, typed_plan

    def test_build_progress_md_present_on_disk(self):
        """emit_scaffold writes build_progress.md to the staging root."""
        staging_dir, _ = self._assemble_and_emit()
        bp = staging_dir / "build_progress.md"
        self.assertTrue(bp.exists(), f"build_progress.md not written to staging root {staging_dir}")

    def test_build_progress_md_contains_phase_rows(self):
        """On-disk build_progress.md contains a row for each committed phase."""
        staging_dir, _ = self._assemble_and_emit()
        content = (staging_dir / "build_progress.md").read_text(encoding="utf-8")
        self.assertIn("Ingest incoming items", content)
        self.assertIn("Summarise daily batch", content)
        self.assertIn("Archive processed items", content)

    def test_build_progress_md_contains_state_vocabulary(self):
        """build_progress.md contains all five state vocabulary tokens."""
        staging_dir, _ = self._assemble_and_emit()
        content = (staging_dir / "build_progress.md").read_text(encoding="utf-8")
        for token in _STATE_VOCAB:
            self.assertIn(
                token, content,
                f"state vocabulary token {token!r} missing from build_progress.md",
            )

    def test_build_progress_md_contains_layer_b_verdicts(self):
        """build_progress.md legend contains all three Layer-B tri-state verdict tokens."""
        staging_dir, _ = self._assemble_and_emit()
        content = (staging_dir / "build_progress.md").read_text(encoding="utf-8")
        for token in _LAYER_B_VERDICTS:
            self.assertIn(
                token, content,
                f"Layer-B verdict token {token!r} missing from build_progress.md",
            )

    def test_build_progress_md_has_required_columns(self):
        """build_progress.md table has columns for Layer-A result, Layer-B verdict,
        open-fix-items, deferred-core-precondition, and date."""
        staging_dir, _ = self._assemble_and_emit()
        content = (staging_dir / "build_progress.md").read_text(encoding="utf-8")
        # Column header presence (case-insensitive friendly — just check key words).
        self.assertIn("Layer-A", content, "Layer-A column missing")
        self.assertIn("Layer-B", content, "Layer-B column missing")
        self.assertIn("Open fix items", content, "Open fix items column missing")
        self.assertIn("Deferred core precondition", content, "Deferred core precondition column missing")
        self.assertIn("Date", content, "Date column missing")

    def test_build_progress_md_no_unsubstituted_placeholders(self):
        """No {{KEY}} placeholders survive substitution in build_progress.md."""
        import re
        staging_dir, _ = self._assemble_and_emit()
        content = (staging_dir / "build_progress.md").read_text(encoding="utf-8")
        leftover = re.findall(r'\{\{[A-Z_]+\}\}', content)
        self.assertEqual(leftover, [], f"unsubstituted placeholders in build_progress.md: {leftover}")

    def test_build_progress_md_no_build_ids(self):
        """On-disk build_progress.md must not contain build-provenance tokens."""
        import re
        staging_dir, _ = self._assemble_and_emit()
        content = (staging_dir / "build_progress.md").read_text(encoding="utf-8")
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        self.assertIsNone(
            pattern.search(content),
            f"build ID found in build_progress.md: {pattern.search(content)}",
        )

    def test_no_increments_build_progress_md_still_present(self):
        """build_progress.md is still emitted when there are no committed phases."""
        staging_dir, _ = self._assemble_and_emit(dr=_dr_no_increments())
        bp = staging_dir / "build_progress.md"
        self.assertTrue(bp.exists(), "build_progress.md must be emitted even with no phases")


class NextPhaseSkillEmitTests(unittest.TestCase):
    """next-phase.md is emitted into the operator project and carries required prose."""

    def _assemble_and_emit(self):
        from operator_system_emitter import emit_operator_system  # noqa: E402
        dr = _dr_with_increments()
        bi = BuildIntent(derived_record=dr, agent_intents=[_ai_collector(), _ai_summariser()])
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        typed_plan = validate_emission_plan(plan_dict, EP_CONTRACT)
        staging_dir = Path(tempfile.mkdtemp())
        emit_operator_system(typed_plan, staging_dir, REPO_ROOT)
        return staging_dir

    def test_next_phase_skill_present_in_operator_project(self):
        """wizard/skills/next-phase.md is emitted into the operator project."""
        staging_dir = self._assemble_and_emit()
        skill_path = staging_dir / "wizard/skills/next-phase.md"
        self.assertTrue(
            skill_path.exists(),
            f"wizard/skills/next-phase.md not found in staging dir {staging_dir}",
        )

    def test_next_phase_skill_reads_build_progress(self):
        """next-phase.md references build_progress.md."""
        staging_dir = self._assemble_and_emit()
        content = (staging_dir / "wizard/skills/next-phase.md").read_text(encoding="utf-8")
        self.assertIn(
            "build_progress.md",
            content,
            "next-phase.md must reference build_progress.md",
        )

    def test_next_phase_skill_has_refusing_precondition(self):
        """next-phase.md describes refusing to start the next phase until the prior is accepted."""
        staging_dir = self._assemble_and_emit()
        content = (staging_dir / "wizard/skills/next-phase.md").read_text(encoding="utf-8")
        # Must mention both blocking states by name.
        self.assertIn(
            "accepted",
            content,
            "next-phase.md must mention 'accepted' state (refusing precondition)",
        )
        self.assertIn(
            "provisionally-accepted",
            content,
            "next-phase.md must mention 'provisionally-accepted' state (refusing precondition)",
        )

    def test_next_phase_skill_reads_live_foundation_docs(self):
        """next-phase.md instructs reading live foundation docs + phase acceptance contract."""
        staging_dir = self._assemble_and_emit()
        content = (staging_dir / "wizard/skills/next-phase.md").read_text(encoding="utf-8")
        for doc in ("execution_plan.md", "approach.md", "technical_architecture.md"):
            self.assertIn(
                doc,
                content,
                f"next-phase.md must reference live foundation doc {doc}",
            )
        self.assertIn(
            "acceptance",
            content,
            "next-phase.md must reference the phase acceptance contract",
        )

    def test_next_phase_skill_has_stop_condition(self):
        """next-phase.md contains the plan-changed stop-condition."""
        staging_dir = self._assemble_and_emit()
        content = (staging_dir / "wizard/skills/next-phase.md").read_text(encoding="utf-8")
        # The stop-condition tells the operator to re-run the wizard or use upgrade flow.
        self.assertTrue(
            "wizard" in content.lower() or "upgrade" in content.lower(),
            "next-phase.md must reference re-running the wizard or upgrade flow (stop-condition)",
        )

    def test_next_phase_skill_no_build_ids(self):
        """next-phase.md must not contain build-provenance tokens (RW-/IDQ-/ADR-/S2./AR-/W-)."""
        import re
        staging_dir = self._assemble_and_emit()
        content = (staging_dir / "wizard/skills/next-phase.md").read_text(encoding="utf-8")
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        self.assertIsNone(
            pattern.search(content),
            f"build ID found in next-phase.md: {pattern.search(content)}",
        )

    def test_next_phase_skill_no_awb_reference(self):
        """next-phase.md must not reference agent-wizard-build or AWB (self-contained invariant)."""
        staging_dir = self._assemble_and_emit()
        content = (staging_dir / "wizard/skills/next-phase.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "agent-wizard-build",
            content,
            "next-phase.md must not reference the build project (self-contained invariant)",
        )
        self.assertNotIn(
            "AWB",
            content,
            "next-phase.md must not reference AWB (self-contained invariant)",
        )


class ProjectInstructionsBuildAndOperateTests(unittest.TestCase):
    """E1: project_instructions.md carries the build-and-operate loop section."""

    @classmethod
    def setUpClass(cls):
        from emission_plan import load_contract, default_contract_path, validate_emission_plan
        from scaffold_emitter import emit_scaffold
        contract = load_contract(default_contract_path())
        dr = _dr_with_increments()
        bi = BuildIntent(derived_record=dr, agent_intents=[_ai_collector(), _ai_summariser()])
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        typed_plan = validate_emission_plan(plan_dict, contract)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        emit_scaffold(typed_plan, staging, REPO_ROOT)
        cls.text = (staging / "project_instructions.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_build_and_operate_section_present(self):
        """project_instructions.md has a Build and Operate section."""
        self.assertIn("Build and Operate", self.text,
                      "project_instructions.md must contain a 'Build and Operate' section")

    def test_one_phase_at_a_time_loop_rule(self):
        """project_instructions.md states the one-phase-at-a-time loop rule."""
        lower = self.text.lower()
        self.assertTrue(
            "one phase at a time" in lower or "one phase" in lower,
            "project_instructions.md must state the one-phase-at-a-time loop rule",
        )

    def test_anti_log_and_move_on_principle(self):
        """project_instructions.md states the anti-log-and-move-on principle."""
        lower = self.text.lower()
        self.assertTrue(
            "not accepted" in lower or "not yet accepted" in lower
            or "do not build" in lower or "have not accepted" in lower,
            "project_instructions.md must state the anti-log-and-move-on principle",
        )

    def test_supervised_copy_target_rule(self):
        """project_instructions.md states the supervised/copy-target rule."""
        lower = self.text.lower()
        self.assertTrue(
            "copy" in lower or "dummy" in lower,
            "project_instructions.md must reference running supervised against a copy/dummy of external state",
        )
        self.assertIn(
            "supervised", lower,
            "project_instructions.md must state the supervised-until-accepted rule",
        )

    def test_in_session_fix_and_reconfirm_rule(self):
        """project_instructions.md states the in-session fix-and-reconfirm rule."""
        lower = self.text.lower()
        self.assertTrue(
            "fix" in lower and ("same session" in lower or "re-run" in lower or "reconfirm" in lower),
            "project_instructions.md must state the in-session fix-and-reconfirm rule",
        )

    def test_state_machine_sequence_present(self):
        """project_instructions.md contains the acceptance state-machine sequence."""
        lower = self.text.lower()
        for token in ("built", "technically-reviewed", "supervised", "accepted"):
            self.assertIn(token, lower,
                          f"project_instructions.md must contain state-machine token '{token}'")

    def test_operator_acceptance_flips_accepted(self):
        """project_instructions.md states operator business-acceptance flips the phase to accepted."""
        lower = self.text.lower()
        self.assertTrue(
            "operator" in lower and "accepted" in lower,
            "project_instructions.md must state that operator acceptance flips a phase to accepted",
        )

    def test_technical_reviews_are_preconditions(self):
        """project_instructions.md states that MA-REV/MA-F technical reviews are preconditions."""
        self.assertTrue(
            "MA-REV" in self.text or "MA-F" in self.text or "precondition" in self.text.lower(),
            "project_instructions.md must state that technical reviews are preconditions",
        )

    def test_scheduled_acceptance_non_blocking_rule(self):
        """project_instructions.md states that scheduled-acceptance is non-blocking."""
        lower = self.text.lower()
        self.assertTrue(
            "scheduled" in lower and ("non-blocking" in lower or "separate" in lower or "digest" in lower),
            "project_instructions.md must state the scheduled-acceptance-non-blocking rule",
        )

    def test_references_build_progress_and_next_phase(self):
        """project_instructions.md references build_progress.md and the next-phase skill."""
        self.assertIn("build_progress.md", self.text,
                      "project_instructions.md must reference build_progress.md")
        self.assertTrue(
            "next-phase" in self.text or "next-phase.md" in self.text,
            "project_instructions.md must reference the next-phase skill",
        )

    def test_no_build_ids(self):
        """project_instructions.md must not contain build-provenance tokens in the new section."""
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        self.assertIsNone(
            pattern.search(self.text),
            f"build ID found in project_instructions.md: {pattern.search(self.text)}",
        )


class SessionBootstrapBuildProgressTests(unittest.TestCase):
    """E2: session_bootstrap.md carries the build-progress section."""

    @classmethod
    def setUpClass(cls):
        from emission_plan import load_contract, default_contract_path, validate_emission_plan
        from scaffold_emitter import emit_scaffold
        contract = load_contract(default_contract_path())
        dr = _dr_with_increments()
        bi = BuildIntent(derived_record=dr, agent_intents=[_ai_collector(), _ai_summariser()])
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        typed_plan = validate_emission_plan(plan_dict, contract)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        emit_scaffold(typed_plan, staging, REPO_ROOT)
        cls.text = (staging / "session_bootstrap.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_build_progress_section_present(self):
        """session_bootstrap.md has a Build progress section."""
        lower = self.text.lower()
        self.assertIn("build progress", lower,
                      "session_bootstrap.md must contain a 'Build progress' section")

    def test_reads_build_progress_md(self):
        """session_bootstrap.md instructs reading build_progress.md."""
        self.assertIn("build_progress.md", self.text,
                      "session_bootstrap.md must instruct reading build_progress.md")

    def test_refusing_precondition_present(self):
        """session_bootstrap.md states the refusing precondition."""
        lower = self.text.lower()
        self.assertTrue(
            "accepted" in lower
            and ("prior" in lower or "previous" in lower or "precondition" in lower or "not start" in lower),
            "session_bootstrap.md must state the refusing precondition (do not start next phase until prior is accepted)",
        )

    def test_next_phase_skill_referenced(self):
        """session_bootstrap.md references the next-phase skill."""
        self.assertTrue(
            "next-phase" in self.text or "next-phase.md" in self.text,
            "session_bootstrap.md must reference the next-phase skill",
        )

    def test_no_build_ids(self):
        """session_bootstrap.md must not contain build-provenance tokens."""
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        self.assertIsNone(
            pattern.search(self.text),
            f"build ID found in session_bootstrap.md: {pattern.search(self.text)}",
        )


class OrchestratorAcceptanceStateMachineTests(unittest.TestCase):
    """E3: orchestrator_prompt.md carries the acceptance state machine."""

    @classmethod
    def setUpClass(cls):
        from emission_plan import load_contract, default_contract_path, validate_emission_plan
        contract = load_contract(default_contract_path())
        dr = _dr_with_increments()
        bi = BuildIntent(derived_record=dr, agent_intents=[_ai_collector(), _ai_summariser()])
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        typed_plan = validate_emission_plan(plan_dict, contract)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        from agent_emitter import emit_agent_layer
        emit_agent_layer(typed_plan, staging, REPO_ROOT)
        cls.text = (staging / "agents/prompts/orchestrator_prompt.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_acceptance_state_machine_present(self):
        """orchestrator_prompt.md has an acceptance state machine section."""
        lower = self.text.lower()
        self.assertTrue(
            "acceptance state machine" in lower or "acceptance" in lower,
            "orchestrator_prompt.md must contain an acceptance state machine section",
        )

    def test_state_machine_tokens_present(self):
        """orchestrator_prompt.md contains the full state-machine sequence tokens."""
        lower = self.text.lower()
        for token in ("built", "technically-reviewed", "supervised", "accepted"):
            self.assertIn(token, lower,
                          f"orchestrator_prompt.md must contain state-machine token '{token}'")

    def test_operator_acceptance_flips_accepted(self):
        """orchestrator_prompt.md makes explicit that operator business-acceptance flips accepted."""
        lower = self.text.lower()
        self.assertTrue(
            "operator" in lower and "accepted" in lower,
            "orchestrator_prompt.md must state operator business-acceptance flips a phase to accepted",
        )

    def test_technical_reviews_are_preconditions_not_authority(self):
        """orchestrator_prompt.md states technical reviews (MA-REV/MA-F) are preconditions."""
        self.assertTrue(
            "MA-REV" in self.text or "MA-F" in self.text or "precondition" in self.text.lower(),
            "orchestrator_prompt.md must state technical reviews are preconditions",
        )

    def test_references_build_progress_md(self):
        """orchestrator_prompt.md references build_progress.md."""
        self.assertIn("build_progress.md", self.text,
                      "orchestrator_prompt.md must reference build_progress.md")

    def test_references_project_instructions_for_authority(self):
        """orchestrator_prompt.md still references project_instructions.md for authority."""
        self.assertIn("project_instructions.md", self.text,
                      "orchestrator_prompt.md must still reference project_instructions.md")

    def test_no_build_ids(self):
        """orchestrator_prompt.md must not contain build-provenance tokens."""
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        self.assertIsNone(
            pattern.search(self.text),
            f"build ID found in orchestrator_prompt.md: {pattern.search(self.text)}",
        )


class MaRevBypassScannerWiringTests(unittest.TestCase):
    """T4-A: Canonical MA-REV templates require running the bypass scanner and fail the phase on a violation.

    The wiring is asserted at the CANONICAL TEMPLATE-FILE level (the source of
    truth the wizard maintains), not via emission. Emission sources templates
    from a REGISTERED frozen bundle, and the bundle carrying this Task-4 wiring
    is not cut until Task 8. Asserting on emitted prose from an existing frozen
    bundle would be wrong on two counts: it would require retro-editing an
    immutable released bundle (breaking replay-conformance), and it would not
    test the wiring the wizard actually maintains going forward. See the
    deferred end-to-end assertion in Task8DeferredScannerEmitTests below.
    """

    @classmethod
    def setUpClass(cls):
        cls.pi_path = REPO_ROOT / "wizard" / "templates" / "root" / "project_instructions.md"
        cls.orch_path = REPO_ROOT / "wizard" / "agents" / "orchestrator_prompt.md"
        cls.pi_text = cls.pi_path.read_text(encoding="utf-8")
        cls.orch_text = cls.orch_path.read_text(encoding="utf-8")

    # --- canonical project_instructions.md template ---

    def test_pi_ma_rev_references_bypass_scanner(self):
        """Canonical project_instructions.md MA-REV section references the bypass scanner CLI by path."""
        self.assertIn(
            "agents/lib/external_write/scan.py", self.pi_text,
            "canonical project_instructions.md must name the bypass scanner CLI (agents/lib/external_write/scan.py) in its MA-REV section",
        )

    def test_pi_ma_rev_fail_closed_on_violation(self):
        """Canonical project_instructions.md MA-REV section states the phase FAILS if the scanner reports a violation."""
        lower = self.pi_text.lower()
        self.assertTrue(
            ("fail" in lower) and ("violation" in lower),
            "canonical project_instructions.md must state the phase fails on a scanner violation (fail-closed semantics)",
        )

    # --- canonical orchestrator_prompt.md template ---

    def test_orch_ma_rev_references_bypass_scanner(self):
        """Canonical orchestrator_prompt.md MA-REV section references the bypass scanner CLI by path."""
        self.assertIn(
            "agents/lib/external_write/scan.py", self.orch_text,
            "canonical orchestrator_prompt.md must name the bypass scanner CLI (agents/lib/external_write/scan.py) in its MA-REV section",
        )

    def test_orch_ma_rev_fail_closed_on_violation(self):
        """Canonical orchestrator_prompt.md MA-REV section states the phase FAILS if the scanner reports a violation."""
        lower = self.orch_text.lower()
        self.assertTrue(
            ("fail" in lower) and ("violation" in lower),
            "canonical orchestrator_prompt.md must state the phase fails on a scanner violation (fail-closed semantics)",
        )

    def test_no_build_ids_in_scanner_prose(self):
        """Canonical MA-REV scanner prose must not contain build-provenance tokens."""
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        for name, text in [("templates/root/project_instructions.md", self.pi_text),
                            ("agents/orchestrator_prompt.md", self.orch_text)]:
            m = pattern.search(text)
            self.assertIsNone(m, f"build ID found in {name}: {m}")


class ControlledVocabularyRuleWiringTests(unittest.TestCase):
    """Task 7 (E): the controlled-vocabulary standing rule is wired into the canonical
    templates — write only values from the operator's allowed set / controlled vocabulary
    for a controlled field. Asserted at the CANONICAL TEMPLATE-FILE level (the same reason
    as MaRevBypassScannerWiringTests: emission sources from a frozen bundle cut in Task 8).

    R-005 reconciliation: the deliverable-folders rule (operator-facing deliverables go to
    their deliverable folder) and the controlled-vocabulary rule are distinct, non-conflicting
    standing rules — the controlled-vocab rule governs the VALUE written to a controlled field;
    the deliverable-folders rule governs WHERE operator-facing deliverables are written.
    """

    @classmethod
    def setUpClass(cls):
        cls.pi_path = REPO_ROOT / "wizard" / "templates" / "root" / "project_instructions.md"
        cls.od_path = REPO_ROOT / "wizard" / "templates" / "root" / "operating_discipline.md"
        cls.rl_path = REPO_ROOT / "wizard" / "templates" / "quality" / "rules_library.md"
        cls.sb_path = REPO_ROOT / "wizard" / "templates" / "root" / "session_bootstrap.md"
        cls.pi_text = cls.pi_path.read_text(encoding="utf-8")
        cls.od_text = cls.od_path.read_text(encoding="utf-8")
        cls.rl_text = cls.rl_path.read_text(encoding="utf-8")
        cls.sb_text = cls.sb_path.read_text(encoding="utf-8")

    def test_project_instructions_states_controlled_vocab_rule(self):
        """project_instructions.md carries the controlled-vocabulary standing rule."""
        lower = self.pi_text.lower()
        self.assertIn("controlled", lower,
                      "project_instructions.md must carry the controlled-vocabulary standing rule")
        self.assertTrue(
            ("allowed" in lower) and ("value" in lower),
            "the controlled-vocab rule must state writes use only values from the allowed set",
        )

    def test_operating_discipline_states_controlled_vocab_rule(self):
        """operating_discipline.md (write-integrity section) states the value-validity rule."""
        lower = self.od_text.lower()
        self.assertIn("controlled", lower)
        self.assertTrue(
            ("allowed" in lower) and ("value" in lower),
            "operating_discipline.md must state writes use only values from the allowed set",
        )

    def test_rules_library_documents_controlled_vocab_rule(self):
        """rules_library.md documents the controlled-vocabulary standing rule."""
        self.assertIn("controlled", self.rl_text.lower())

    def test_operating_discipline_states_saved_next_step_precedence(self):
        """F-23: operating_discipline.md Orientation states the SAVED / paused next step is the
        lead next step — a paused or in-progress thread is a real next step, not 'no action'."""
        lower = self.od_text.lower()
        self.assertIn("lead next step", lower,
                      "operating_discipline.md must name the saved step as the LEAD next step")
        self.assertIn("paused", lower,
                      "operating_discipline.md must state a paused thread is a real next step")
        self.assertIn("real next step", lower,
                      "operating_discipline.md must state a paused/half-finished thread is a "
                      "real next step, not 'nothing to do'")

    def test_session_bootstrap_states_saved_next_step_precedence(self):
        """F-23: the session_bootstrap template tells the session-start reader the saved 'Next
        action' / 'Resume here' note takes precedence over a phase/date-derived next step."""
        lower = self.sb_text.lower()
        self.assertIn("saved next step takes precedence", lower,
                      "session_bootstrap.md must state the saved next step takes precedence")
        self.assertTrue(
            ("resume here" in lower) and ("next action" in lower),
            "session_bootstrap.md must reference the saved 'Next action' and paused 'Resume here' note",
        )

    def test_operating_discipline_forbids_forward_version_prediction(self):
        """F-25: operating_discipline.md states the system records only the OBSERVED current
        version, never a forward-looking 'no update expected / on latest' prediction in state."""
        lower = self.od_text.lower()
        self.assertIn("forward-looking", lower,
                      "operating_discipline.md must forbid recording a forward-looking claim")
        self.assertIn("no update", lower,
                      "operating_discipline.md must name the 'no update expected' anti-pattern")
        self.assertTrue(
            ("checked fresh" in lower) or ("fresh at the start" in lower),
            "operating_discipline.md must state version currency is re-checked fresh each session",
        )

    def test_operating_discipline_states_both_surface_rule(self):
        """F-23/F-25 ext (Task 13): operating_discipline.md states that when a dated item
        lapsed during the operator's absence AND a saved/paused next step also exists, the
        greeting surfaces BOTH — the lapsed item and the still-pending saved next step —
        rather than silently dropping the saved thread in favor of the lapsed item. A single
        recommended next step is still preserved (no menu)."""
        lower = self.od_text.lower()
        self.assertIn("lapsed", lower,
                      "operating_discipline.md must name the 'lapsed while away' scenario")
        self.assertIn("surfaces both", lower,
                      "operating_discipline.md must state the greeting surfaces BOTH items")
        self.assertIn("still pending", lower,
                      "operating_discipline.md must state the saved next step is still pending, "
                      "not silently dropped")
        self.assertIn("never silently drop", lower,
                      "operating_discipline.md must state the saved thread is never silently "
                      "dropped in favor of the lapsed item")
        self.assertTrue(
            ("single recommended next step" in lower) or ("one recommended next step" in lower),
            "operating_discipline.md must state a single recommended next step is still given, "
            "even when both items are surfaced (no-menu convention preserved)",
        )

    def test_operating_discipline_forbids_guessed_day_of_week(self):
        """F-23/F-25 ext (Task 13) sub-guard: operating_discipline.md forbids stating a
        day-of-week label unless it has actually been computed from the calendar (the dogfood
        greeting mislabeled 'Wednesday 7/9' when 7/9 was in fact a Thursday)."""
        lower = self.od_text.lower()
        self.assertIn("day-of-week", lower,
                      "operating_discipline.md must name the day-of-week guard")
        self.assertTrue(
            ("computed" in lower),
            "operating_discipline.md must require the day-of-week to be COMPUTED, not guessed",
        )
        self.assertTrue(
            ("guess" in lower) or ("assume" in lower) or ("recalled" in lower) or ("memory" in lower),
            "operating_discipline.md must forbid guessing/assuming/recalling a day-of-week from "
            "memory rather than computing it",
        )

    def test_r005_deliverable_folders_not_contradicted(self):
        """R-005 reconciliation: the controlled-vocab rule and the deliverable-folders rule
        coexist without contradiction at the CANONICAL TEMPLATE level.

        The template carries text explicitly stating the controlled-vocab rule does NOT
        override the deliverable-folder rule, and that both apply — this is the in-template
        coexistence assertion. Full coexistence at the emitted-bundle level is deferred until
        the bundle cut (Task 8); this test covers what is verifiable now at the template level.

        # TODO(bundle-cut): after Task 8 cuts the new bundle, add an emitted-plan assertion
        # that both rules appear in the emitted project_instructions.md without contradiction.
        """
        lower = self.pi_text.lower()
        # The controlled-vocab rule must explicitly disclaim overriding the deliverable rule.
        # The template text says "does not override, the deliverable-folder rule" (verbatim).
        self.assertIn("does not override", lower,
                      "the controlled-vocab rule must explicitly state it does NOT override "
                      "the deliverable-folder rule (R-005 coexistence)")
        # The template must explicitly say both rules apply — not just one.
        self.assertIn("both apply", lower,
                      "the template must state 'both apply' — confirming coexistence, not conflict")
        # The deliverable-folder rule must be present and described as governing WHERE.
        self.assertTrue(
            "where" in lower and "deliverable" in lower,
            "the deliverable-folders rule must be described as governing WHERE deliverables "
            "are written (not overridden by the controlled-vocab rule)",
        )
        # No contradiction: the controlled-vocab rule must not forbid deliverable-folder writes.
        self.assertNotIn("never write to a deliverable", lower)

    def test_no_build_ids_in_controlled_vocab_prose(self):
        """The controlled-vocab rule prose must not contain build-provenance tokens."""
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]|F-2[0-9]')
        for name, text in [("templates/root/project_instructions.md", self.pi_text),
                           ("templates/root/operating_discipline.md", self.od_text),
                           ("templates/quality/rules_library.md", self.rl_text)]:
            m = pattern.search(text)
            self.assertIsNone(m, f"build ID found in {name}: {m}")


class WritesBackOwnershipCaptureTests(unittest.TestCase):
    """Task 7 (A): interview step 09 captures, per writes-back dependency, the owning agent,
    and flows it into EXTERNAL_DEPENDENCY_IDENTITY as owner_agent_id."""

    @classmethod
    def setUpClass(cls):
        cls.cred_path = REPO_ROOT / "wizard" / "interview" / "09_credentials.md"
        cls.cred_text = cls.cred_path.read_text(encoding="utf-8")

    def test_step09_has_writes_back_ownership_capture(self):
        lower = self.cred_text.lower()
        self.assertIn("writes-back ownership", lower,
                      "09_credentials.md must carry a writes-back ownership sub-pass")
        self.assertIn("own", lower)

    def test_step09_derivation_includes_owner_agent_id(self):
        self.assertIn("owner_agent_id", self.cred_text,
                      "09_credentials.md identity derivation must include owner_agent_id for writes-back deps")

    def test_step09_owner_keyed_to_boundary_output(self):
        # The owner is captured only for the writes-back (boundary_output) role.
        self.assertIn("boundary_output", self.cred_text)

    def test_no_build_ids_in_step09(self):
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]|F-2[0-9]')
        m = pattern.search(self.cred_text)
        self.assertIsNone(m, f"build ID found in 09_credentials.md: {m}")


class Task8ScannerEmitTests(unittest.TestCase):
    """T4-A: end-to-end assertion that the bypass-scanner wiring reaches an EMITTED
    operator system built from the bundle that carries it (v0.8.0).

    Emission sources the operating-layer templates from the REGISTERED frozen bundle;
    v0.8.0 is the bundle whose templates carry the Task-4 scanner wiring. This re-emits
    a full operator system from v0.8.0 and asserts the emitted project_instructions.md
    and agents/prompts/orchestrator_prompt.md both name the scanner CLI by path and
    state fail-closed-on-violation semantics. It would FAIL if the wiring were absent
    from the cut bundle. The canonical template-level wiring is also covered by
    MaRevBypassScannerWiringTests; this is the from-bundle proof.
    """

    _BUNDLE = "v0.8.0"

    @classmethod
    def setUpClass(cls):
        from operator_system_emitter import emit_operator_system  # noqa: E402
        dr = _dr_with_increments()
        bi = BuildIntent(derived_record=dr, agent_intents=[_ai_collector(), _ai_summariser()])
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers,
                                           bundle_version=cls._BUNDLE)
        typed_plan = validate_emission_plan(plan_dict, EP_CONTRACT)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        emit_operator_system(typed_plan, staging, REPO_ROOT)
        cls.pi_text = (staging / "project_instructions.md").read_text(encoding="utf-8")
        cls.orch_text = (staging / "agents/prompts/orchestrator_prompt.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_emitted_pi_names_bypass_scanner(self):
        self.assertIn("agents/lib/external_write/scan.py", self.pi_text,
                      "emitted project_instructions.md must name the bypass scanner CLI by path")

    def test_emitted_pi_fail_closed_on_violation(self):
        lower = self.pi_text.lower()
        self.assertTrue(("fail" in lower) and ("violation" in lower),
                        "emitted project_instructions.md must state the phase fails on a scanner violation")

    def test_emitted_orchestrator_names_bypass_scanner(self):
        self.assertIn("agents/lib/external_write/scan.py", self.orch_text,
                      "emitted orchestrator_prompt.md must name the bypass scanner CLI by path")

    def test_emitted_orchestrator_fail_closed_on_violation(self):
        lower = self.orch_text.lower()
        self.assertTrue(("fail" in lower) and ("violation" in lower),
                        "emitted orchestrator_prompt.md must state the phase fails on a scanner violation")


class Phase1BuildPromptScannerTests(unittest.TestCase):
    """T4-B: Phase-1 build prompt (generated by 15_close.md) names the scanner step."""

    @classmethod
    def setUpClass(cls):
        cls.close14_path = REPO_ROOT / "wizard" / "interview" / "15_close.md"
        cls.close14_text = cls.close14_path.read_text(encoding="utf-8")

    def test_close14_names_bypass_scanner(self):
        """15_close.md phase-1 build prompt names the bypass scanner step."""
        self.assertTrue(
            "scan.py" in self.close14_text or "bypass scanner" in self.close14_text.lower(),
            "15_close.md phase-1 build prompt must name the bypass scanner step",
        )

    def test_close14_scanner_is_in_technical_verification_step(self):
        """15_close.md scanner reference appears in the technical verification step context."""
        # The build prompt's Step 2 is 'Technical verification' — scanner must appear near it.
        lower = self.close14_text.lower()
        self.assertTrue(
            "technical verification" in lower or "technical review" in lower,
            "15_close.md must contain a technical verification step",
        )
        # Scanner reference must be present (the step names it).
        self.assertTrue(
            "scan.py" in self.close14_text or "bypass scanner" in lower,
            "15_close.md must name the bypass scanner in the technical verification context",
        )

    def test_close14_scanner_fail_closed(self):
        """15_close.md scanner instruction states fail-closed semantics."""
        lower = self.close14_text.lower()
        self.assertTrue(
            ("violation" in lower or "bypass" in lower) and ("fail" in lower),
            "15_close.md must state the phase fails on a scanner violation (fail-closed semantics)",
        )

    def test_no_build_ids_in_close14_scanner_prose(self):
        """15_close.md must not contain build-provenance tokens."""
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        m = pattern.search(self.close14_text)
        self.assertIsNone(m, f"build ID found in 15_close.md: {m}")


class ScanCliEntrypointTests(unittest.TestCase):
    """T4-C: scan.py CLI entrypoint exits non-zero on violations and zero on clean input."""

    def setUp(self):
        import sys
        self._agents_lib = str(REPO_ROOT / "wizard" / "agents" / "lib")
        self._scan_module = str(REPO_ROOT / "wizard" / "agents" / "lib" / "external_write" / "scan.py")
        self._fixtures = REPO_ROOT / "wizard" / "test_fixtures" / "external_write_scan"
        self._adapter_dir = str(REPO_ROOT / "wizard" / "agents" / "lib" / "external_write")

    def test_cli_exits_nonzero_on_violation(self):
        """scan.py CLI exits non-zero when given a file with a violation."""
        import subprocess
        result = subprocess.run(
            [sys.executable, self._scan_module,
             str(self._fixtures / "direct_api_call.py")],
            capture_output=True,
        )
        self.assertNotEqual(
            result.returncode, 0,
            "scan.py CLI must exit non-zero when a violation is found",
        )

    def test_cli_exits_zero_on_clean_input(self):
        """scan.py CLI exits zero when the scanned file is clean."""
        import subprocess
        result = subprocess.run(
            [sys.executable, self._scan_module,
             str(self._fixtures / "legal_through_adapter.py")],
            capture_output=True,
        )
        self.assertEqual(
            result.returncode, 0,
            f"scan.py CLI must exit zero on clean input; stderr={result.stderr.decode()!r}",
        )

    def test_cli_prints_violation_details_on_stderr_or_stdout(self):
        """scan.py CLI reports violation details (file, line, kind) on non-zero exit."""
        import subprocess
        result = subprocess.run(
            [sys.executable, self._scan_module,
             str(self._fixtures / "direct_api_call.py")],
            capture_output=True, text=True,
        )
        combined = result.stdout + result.stderr
        self.assertTrue(
            "direct_api_call" in combined or "violation" in combined.lower(),
            f"scan.py CLI must report violation kind; got stdout={result.stdout!r} stderr={result.stderr!r}",
        )


class Task5ApprovalProseTests(unittest.TestCase):
    """T5: Step-4 semantic approval + honest ceiling + hook demotion.

    All assertions are at the CANONICAL TEMPLATE-FILE level (wizard/templates/
    and wizard/agents/) — frozen bundles are immutable; the bundle carrying
    Task-5 changes is cut in Task 8. Assertions on emitted prose from an
    existing frozen bundle would require retro-editing immutable files.
    """

    @classmethod
    def setUpClass(cls):
        cls.od_path = (
            REPO_ROOT / "wizard" / "templates" / "root" / "operating_discipline.md"
        )
        cls.orch_path = REPO_ROOT / "wizard" / "agents" / "orchestrator_prompt.md"
        cls.apt_path = REPO_ROOT / "wizard" / "agents" / "agent_prompt_template.md"
        cls.gate_path = (
            REPO_ROOT / "wizard" / "templates" / "claude_config" / "receipt_gate.sh"
        )
        cls.od_text = cls.od_path.read_text(encoding="utf-8")
        cls.orch_text = cls.orch_path.read_text(encoding="utf-8")
        cls.apt_text = cls.apt_path.read_text(encoding="utf-8")
        cls.gate_text = cls.gate_path.read_text(encoding="utf-8")

    # --- 1. Distinct step-4 semantic approval ---

    def test_od_step4_distinct_semantic_approval(self):
        """operating_discipline.md states that step 4 is a distinct, semantic approval turn."""
        lower = self.od_text.lower()
        # Must say approval is distinct / separate — not implied, bundled, or silent.
        self.assertTrue(
            "distinct" in lower or "separate" in lower,
            "operating_discipline.md must describe step-4 approval as a distinct/separate step",
        )

    def test_od_step4_operator_reviews_plain_language_summary(self):
        """operating_discipline.md states the operator reviews a plain-language summary before approving."""
        lower = self.od_text.lower()
        self.assertTrue(
            ("plain" in lower and "summary" in lower) or "review" in lower,
            "operating_discipline.md must state the operator reviews a plain-language summary",
        )

    def test_od_step4_not_silent_or_bundled(self):
        """operating_discipline.md explicitly states approval is NOT silent, implied, or bundled."""
        lower = self.od_text.lower()
        self.assertTrue(
            "silent" in lower or "implied" in lower or "bundled" in lower,
            "operating_discipline.md must explicitly reject silent/implied/bundled approval",
        )

    def test_od_step4_re_approval_on_plan_evolution(self):
        """operating_discipline.md states that plan evolution (change after approval) voids
        prior approval and requires re-approval."""
        lower = self.od_text.lower()
        self.assertTrue(
            ("re-approval" in lower or "re-approve" in lower or "reapproval" in lower
             or "void" in lower or "prior approval" in lower),
            "operating_discipline.md must state that plan evolution voids prior approval and requires re-approval",
        )

    def test_od_step4_plan_change_triggers_reapproval(self):
        """operating_discipline.md mentions what triggers re-approval (plan changes / evolves)."""
        lower = self.od_text.lower()
        self.assertTrue(
            "change" in lower or "evolve" in lower or "evolves" in lower,
            "operating_discipline.md must describe plan change as the re-approval trigger",
        )

    def test_orch_step4_distinct_approval(self):
        """orchestrator_prompt.md states step-4 approval is a distinct semantic step."""
        lower = self.orch_text.lower()
        self.assertTrue(
            "distinct" in lower or "separate" in lower,
            "orchestrator_prompt.md must describe step-4 approval as a distinct/separate step",
        )

    def test_orch_step4_reapproval_on_plan_evolution(self):
        """orchestrator_prompt.md states re-approval is required when the plan changes."""
        lower = self.orch_text.lower()
        self.assertTrue(
            "re-approval" in lower or "re-approve" in lower or "void" in lower
            or "prior approval" in lower or "reapproval" in lower,
            "orchestrator_prompt.md must state re-approval is required when the plan changes",
        )

    def test_apt_step4_distinct_approval(self):
        """agent_prompt_template.md states step-4 approval is a distinct semantic step."""
        lower = self.apt_text.lower()
        self.assertTrue(
            "distinct" in lower or "separate" in lower,
            "agent_prompt_template.md must describe step-4 approval as a distinct/separate step",
        )

    def test_apt_step4_reapproval_on_plan_evolution(self):
        """agent_prompt_template.md states re-approval is required when the plan changes."""
        lower = self.apt_text.lower()
        self.assertTrue(
            "re-approval" in lower or "re-approve" in lower or "void" in lower
            or "prior approval" in lower or "reapproval" in lower,
            "agent_prompt_template.md must state re-approval is required when the plan changes",
        )

    # --- 2. Honest ceiling ---

    def test_od_honest_ceiling_build_time_enforcement(self):
        """operating_discipline.md discloses that write-integrity enforcement is build-time
        (bypass scanner) plus operator-as-approver, not a runtime or OS guarantee."""
        lower = self.od_text.lower()
        self.assertTrue(
            "build-time" in lower or "build time" in lower,
            "operating_discipline.md must disclose build-time enforcement (honest ceiling)",
        )

    def test_od_honest_ceiling_not_runtime_guarantee(self):
        """operating_discipline.md states that the system does NOT provide a runtime or
        OS-level enforcement guarantee."""
        lower = self.od_text.lower()
        # Must say NOT runtime / not an OS guarantee (some form of negation + runtime/os)
        self.assertTrue(
            "not a runtime" in lower or "no runtime" in lower
            or "not a guarantee" in lower or "not guaranteed" in lower
            or "not an os" in lower,
            "operating_discipline.md must state the enforcement is NOT a runtime/OS guarantee",
        )

    def test_od_honest_ceiling_operator_is_approver_of_record(self):
        """operating_discipline.md states the operator is the approver of record."""
        lower = self.od_text.lower()
        self.assertTrue(
            "approver of record" in lower or "operator is the approver" in lower
            or ("operator" in lower and "approver" in lower),
            "operating_discipline.md must name the operator as the approver of record",
        )

    # --- 3. Hook demotion — receipt_gate.sh ---

    def test_gate_uses_backstop_framing(self):
        """receipt_gate.sh uses 'backstop' framing (not 'enforcement' as the primary claim)."""
        lower = self.gate_text.lower()
        self.assertIn(
            "backstop",
            lower,
            "receipt_gate.sh must use 'backstop' framing",
        )

    def test_gate_does_not_claim_to_enforce(self):
        """receipt_gate.sh comment header must NOT claim the hook 'enforces' the protection
        or is 'the enforcement mechanism' — demotion means it is a backstop, not the enforcer."""
        # The word 'enforce' appears only in comments explaining the honest ceiling or
        # in the existing ASK_REASON message. Check that it does NOT appear in the top
        # comment block (lines before the python heredoc) as a primary claim.
        # Strategy: assert that 'backstop' appears AND that 'enforces' / 'enforcement'
        # is NOT used to describe the hook itself in a positive claim in the header.
        header_lines = []
        for line in self.gate_text.splitlines():
            if line.strip().startswith("PY") or "python3" in line:
                break
            header_lines.append(line.lower())
        header = "\n".join(header_lines)
        # The header must contain 'backstop'.
        self.assertIn(
            "backstop",
            header,
            "receipt_gate.sh header comment must use 'backstop' framing",
        )
        # Negative assertion: any occurrence of 'enforcement' in the header MUST
        # appear only within the demoting phrase 'not the primary enforcement mechanism'.
        # A bare 'this hook enforces' or 'the enforcement mechanism is this hook'
        # would be a re-introduced over-claim that must fail this test.
        # Strip out every occurrence of the approved demoting phrase then check no
        # residual 'enforc' root remains — that would indicate a positive claim.
        DEMOTING_PHRASE = "not the primary enforcement mechanism"
        header_stripped = header.replace(DEMOTING_PHRASE, "")
        self.assertNotIn(
            "enforc",
            header_stripped,
            "receipt_gate.sh header must not claim enforcement outside the demoting "
            "phrase 'not the primary enforcement mechanism' — a bare 'enforces' or "
            "'enforcement mechanism' in the header is an over-claim the hook does not satisfy",
        )

    # --- 4. Hook absent from operator-facing explanation prose ---

    def test_od_hook_absent_from_operator_explanation(self):
        """operating_discipline.md (operator-facing) must NOT surface the hook as the
        protection mechanism. Operator-facing prose talks about review + build-time check,
        not about the runtime hook."""
        lower = self.od_text.lower()
        # 'receipt_gate' is the hook implementation name; it must not appear in the
        # operator-facing document.
        self.assertNotIn(
            "receipt_gate",
            lower,
            "operating_discipline.md must not mention receipt_gate (hook name) in operator-facing prose",
        )
        # The document must not describe a hook as 'the mechanism' or 'how the system protects'.
        # Weaker check: 'pretooluse' (the hook event) must not appear.
        self.assertNotIn(
            "pretooluse",
            lower,
            "operating_discipline.md must not surface PreToolUse hook in operator-facing prose",
        )

    def test_od_no_build_ids_in_approval_prose(self):
        """operating_discipline.md must not contain build-provenance tokens."""
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        m = pattern.search(self.od_text)
        self.assertIsNone(m, f"build ID found in operating_discipline.md: {m}")

    def test_orch_no_build_ids_in_approval_prose(self):
        """orchestrator_prompt.md must not contain build-provenance tokens."""
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        m = pattern.search(self.orch_text)
        self.assertIsNone(m, f"build ID found in orchestrator_prompt.md: {m}")

    def test_apt_no_build_ids_in_approval_prose(self):
        """agent_prompt_template.md must not contain build-provenance tokens."""
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        m = pattern.search(self.apt_text)
        self.assertIsNone(m, f"build ID found in agent_prompt_template.md: {m}")


class Task8ApprovalEmitTests(unittest.TestCase):
    """T5: end-to-end assertion that the step-4 semantic-approval prose and the honest
    ceiling reach an EMITTED operator system built from the bundle that carries them
    (v0.8.0).

    Re-emits a full operator system from v0.8.0 and asserts the emitted
    operating_discipline.md and agents/prompts/orchestrator_prompt.md describe a
    distinct step-4 approval that re-approves on plan evolution, and that
    operating_discipline.md discloses the build-time (honest-ceiling) enforcement.
    Would FAIL if the Task-5 prose were absent from the cut bundle. The canonical
    template-level prose is also covered by Task5ApprovalProseTests; this is the
    from-bundle proof.
    """

    _BUNDLE = "v0.8.0"

    @classmethod
    def setUpClass(cls):
        from operator_system_emitter import emit_operator_system  # noqa: E402
        dr = _dr_with_increments()
        bi = BuildIntent(derived_record=dr, agent_intents=[_ai_collector(), _ai_summariser()])
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers,
                                           bundle_version=cls._BUNDLE)
        typed_plan = validate_emission_plan(plan_dict, EP_CONTRACT)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        emit_operator_system(typed_plan, staging, REPO_ROOT)
        cls.od_text = (staging / "operating_discipline.md").read_text(encoding="utf-8")
        cls.orch_text = (staging / "agents/prompts/orchestrator_prompt.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_emitted_od_step4_distinct_approval(self):
        lower = self.od_text.lower()
        self.assertTrue(("distinct" in lower) or ("separate" in lower),
                        "emitted operating_discipline.md must describe step-4 approval as distinct/separate")

    def test_emitted_od_reapproval_on_plan_evolution(self):
        lower = self.od_text.lower()
        self.assertTrue(
            ("re-approval" in lower or "re-approve" in lower or "reapproval" in lower
             or "void" in lower or "prior approval" in lower),
            "emitted operating_discipline.md must state plan evolution voids prior approval",
        )

    def test_emitted_od_honest_ceiling_build_time(self):
        lower = self.od_text.lower()
        self.assertIn("build-time", lower,
                      "emitted operating_discipline.md must disclose build-time enforcement (honest ceiling)")

    def test_emitted_orchestrator_step4_distinct_approval(self):
        lower = self.orch_text.lower()
        self.assertTrue(("distinct" in lower) or ("separate" in lower),
                        "emitted orchestrator_prompt.md must describe step-4 approval as distinct/separate")


class TestS253ContractDelta(unittest.TestCase):
    def _read(self, rel):
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        return (root / rel).read_text(encoding="utf-8")

    def test_operating_discipline_has_independent_check_and_pushback(self):
        text = self._read("wizard/templates/root/operating_discipline.md")
        self.assertIn("Checks afterward — independently", text)
        self.assertIn("When your observation contradicts a green check", text)
        self.assertIn("No absolute claims on a fresh mechanism", text)

    def test_operating_discipline_keeps_honest_ceiling(self):
        text = self._read("wizard/templates/root/operating_discipline.md")
        self.assertNotIn("runtime guarantee", text.lower().replace("not a runtime", "X"))

    def test_build_progress_requires_copy_run_proof_for_external_writes(self):
        text = self._read("wizard/templates/root/build_progress.md")
        self.assertIn("copy-run proof", text)
        self.assertIn("undo", text)

    def test_emit_set_lists_all_ten_lib_files(self):
        import agent_emitter
        for name in ("operations.py", "adapters.py", "broker.py", "scan.py",
                     "verification_modes.py", "contracts.py", "verifiers.py",
                     "boundary.py", "proof_hash.py", "copy_run_proof.py"):
            self.assertIn(name, agent_emitter._EXTERNAL_WRITE_LIB_FILES)

    def test_emit_set_lists_the_two_b2t2_gate_files(self):
        # B2-T2: coverage_gate.py (build-time) + write_gate.py (runtime) are enrolled in the
        # lib-emit tuple alongside the ten B1 files above.
        import agent_emitter
        for name in ("coverage_gate.py", "write_gate.py"):
            self.assertIn(name, agent_emitter._EXTERNAL_WRITE_LIB_FILES)

    def test_emit_set_lists_the_three_b2t9a_flow_files(self):
        # B2-T9a: the operator-originated-enhancement flow modules are enrolled so the flow's
        # runtime + build-time machinery actually ships (fifteen lib files at that point).
        import agent_emitter
        for name in ("acceptance_ceremony.py", "capability_registration.py",
                     "operator_acceptance.py"):
            self.assertIn(name, agent_emitter._EXTERNAL_WRITE_LIB_FILES)

    def test_emit_set_lists_the_five_t14_generalization_files(self):
        # T14 (external-write-gate-generalization bundle cut): the five new modules this slice
        # added under agents/lib/external_write/ must be enrolled, or an emitted writes-back
        # system's package breaks at import time (adapters_gmail/operations/scan/etc. import
        # these at module load, not just when called) — twenty lib files total at T14.
        import agent_emitter
        for name in ("adapter_registry.py", "adapters_gmail.py", "effects_manifest.py",
                     "read_facade.py", "zones.py"):
            self.assertIn(name, agent_emitter._EXTERNAL_WRITE_LIB_FILES)

    def test_emit_set_lists_the_two_r7_capability_zone_files(self):
        # R7 (external-write-gate-generalization, CAPABILITY-zone hardening): capability_api.py
        # and read_facades_gmail.py must be enrolled, or an emitted writes-back system's package
        # breaks at import time.
        import agent_emitter
        for name in ("capability_api.py", "read_facades_gmail.py"):
            self.assertIn(name, agent_emitter._EXTERNAL_WRITE_LIB_FILES)

    def test_emit_set_lists_the_four_v0_12_0_runenvelope_files(self):
        # v0.12.0 Slice 1 (RunEnvelope trust core): evidence.py is hard-load-bearing (adapters.py /
        # adapters_gmail.py / copy_run_proof.py import AdapterEvidence at module load); run_envelope.py
        # + consent_narration.py are the trust-core leaf API surfaces emitted capability code imports;
        # bounds.py is pulled in by run_envelope.py. All four must be enrolled or the emitted writes-back
        # package either breaks at import time (evidence/bounds) or has no enveloped route for a live
        # multi-unit write (run_envelope/consent_narration) — twenty-six lib files total.
        import agent_emitter
        for name in ("evidence.py", "run_envelope.py", "bounds.py", "consent_narration.py"):
            self.assertIn(name, agent_emitter._EXTERNAL_WRITE_LIB_FILES)

    def test_emit_set_lists_the_task7_registered_adapters_file(self):
        # Task 7 (A4 / F-37, v0.13.0 Slice 2): registered_adapters.py must be enrolled, or an
        # emitted writes-back system's operator_acceptance.py (which hard-imports
        # external_write.registered_adapters at module scope) breaks at import time —
        # twenty-seven lib files total (pre-Task-8).
        import agent_emitter
        self.assertIn("registered_adapters.py", agent_emitter._EXTERNAL_WRITE_LIB_FILES)

    def test_emit_set_lists_the_task8_triage_file(self):
        # Task 8 (A3 / F-48, v0.13.0 Slice 2): triage.py must be enrolled, or an emitted
        # writes-back system's operator-facing triage skill has no module to import —
        # twenty-eight lib files total.
        import agent_emitter
        self.assertIn("triage.py", agent_emitter._EXTERNAL_WRITE_LIB_FILES)
        self.assertEqual(len(agent_emitter._EXTERNAL_WRITE_LIB_FILES), 28)

    def _writes_back_plan(self):
        import copy, json
        from test_emission_plan import _valid_plan
        from emission_plan import validate_emission_plan, load_contract, default_contract_path
        contract = load_contract(default_contract_path())
        p = copy.deepcopy(_valid_plan())
        p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = json.dumps(
            [{"id": "sheet", "name": "sheet", "type": "Spreadsheet", "roles": ["boundary_output"]}]
        )
        return validate_emission_plan(p, contract)

    def test_emit_set_includes_gate_files_for_a_writes_back_plan(self):
        import agent_emitter
        plan = self._writes_back_plan()
        result = agent_emitter.external_write_lib_emit_set(plan)
        for rel in ("agents/lib/external_write/coverage_gate.py",
                    "agents/lib/external_write/write_gate.py"):
            self.assertIn(rel, result)

    # RETIRED at the v0.10.0 bundle cut (B2-T9b): the former
    # test_gate_files_not_yet_physically_copied_current_bundle_lacks_them asserted
    # coverage_gate.py / write_gate.py were NOT yet physically emitted (inert, source-gated,
    # pending the bundle cut). The v0.10.0 cut copied them into the latest bundle, so they ARE
    # now emitted for a writes-back plan — the inertness guard is obsolete and was removed
    # (its self-documented retirement trigger). Physical emission of the flow lib for a
    # writes-back plan against the latest bundle is now covered by
    # test_emit_set_includes_gate_files_for_a_writes_back_plan (enrollment) + the
    # source↔bundle diff at cut time.

    def test_emit_set_empty_for_read_only_system(self):
        """A plan whose dependencies are all read-only (boundary_input only, no boundary_output)
        must produce an empty emit set — the skip logic must not regress to always-emit."""
        import copy, json
        import agent_emitter
        from test_emission_plan import _valid_plan
        from emission_plan import validate_emission_plan, load_contract, default_contract_path
        contract = load_contract(default_contract_path())
        p = copy.deepcopy(_valid_plan())
        # A single boundary_input-only dependency: no writes-back role.
        p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = json.dumps(
            [{"id": "rss", "name": "rss_feed", "type": "RSS", "roles": ["boundary_input"]}]
        )
        plan = validate_emission_plan(p, contract)
        result = agent_emitter.external_write_lib_emit_set(plan)
        self.assertEqual(result, [],
                         "read-only plan (no boundary_output dependency) must emit NONE of the "
                         "external_write lib — skip logic has regressed if this is non-empty")

    def test_no_build_ids_in_changed_wizard_prose(self):
        import re
        for rel in ("wizard/templates/root/operating_discipline.md",
                    "wizard/templates/root/build_progress.md"):
            text = self._read(rel)
            self.assertIsNone(re.search(r"\bF-\d+\b", text))
            self.assertIsNone(re.search(r"\bADR-\d{4}\b", text))
            self.assertIsNone(re.search(r"\bIDQ-\d+\b", text))


if __name__ == "__main__":
    unittest.main()
