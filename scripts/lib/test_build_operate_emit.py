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


class MaRevBypassScannerEmitTests(unittest.TestCase):
    """T4-A: Emitted MA-REV instructions require running the bypass scanner and fail the phase on a violation."""

    @classmethod
    def setUpClass(cls):
        from operator_system_emitter import emit_operator_system  # noqa: E402
        dr = _dr_with_increments()
        bi = BuildIntent(derived_record=dr, agent_intents=[_ai_collector(), _ai_summariser()])
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        typed_plan = validate_emission_plan(plan_dict, EP_CONTRACT)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        emit_operator_system(typed_plan, staging, REPO_ROOT)
        cls.pi_text = (staging / "project_instructions.md").read_text(encoding="utf-8")
        cls.orch_text = (staging / "agents/prompts/orchestrator_prompt.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    # --- project_instructions.md ---

    def test_pi_ma_rev_references_bypass_scanner(self):
        """project_instructions.md MA-REV section references the bypass scanner."""
        self.assertTrue(
            "scan.py" in self.pi_text or "bypass scanner" in self.pi_text.lower(),
            "project_instructions.md must reference the bypass scanner (scan.py) in its MA-REV section",
        )

    def test_pi_ma_rev_fail_closed_on_violation(self):
        """project_instructions.md MA-REV section states the phase FAILS if the scanner reports a violation."""
        lower = self.pi_text.lower()
        self.assertTrue(
            ("fail" in lower or "fails" in lower) and ("violation" in lower or "bypass" in lower),
            "project_instructions.md must state the phase fails on a scanner violation (fail-closed semantics)",
        )

    # --- orchestrator_prompt.md ---

    def test_orch_ma_rev_references_bypass_scanner(self):
        """orchestrator_prompt.md MA-REV section references the bypass scanner."""
        self.assertTrue(
            "scan.py" in self.orch_text or "bypass scanner" in self.orch_text.lower(),
            "orchestrator_prompt.md must reference the bypass scanner (scan.py) in its MA-REV section",
        )

    def test_orch_ma_rev_fail_closed_on_violation(self):
        """orchestrator_prompt.md MA-REV section states the phase FAILS if the scanner reports a violation."""
        lower = self.orch_text.lower()
        self.assertTrue(
            ("fail" in lower or "fails" in lower) and ("violation" in lower or "bypass" in lower),
            "orchestrator_prompt.md must state the phase fails on a scanner violation (fail-closed semantics)",
        )

    def test_no_build_ids_in_scanner_prose(self):
        """Emitted MA-REV scanner prose must not contain build-provenance tokens."""
        import re
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        for name, text in [("project_instructions.md", self.pi_text),
                            ("orchestrator_prompt.md", self.orch_text)]:
            m = pattern.search(text)
            self.assertIsNone(m, f"build ID found in {name}: {m}")


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


if __name__ == "__main__":
    unittest.main()
