"""Tests for acceptance-contract emission wired into the assembly pipeline.

Covers:
  - assemble_emission_plan registers one agents/acceptance/phase_NN_acceptance.md
    path in emitted_files per committed phase;
  - plan["acceptance_contracts"] carries the rendered content for each phase;
  - rendered content is non-empty and contains the phase's operator_questions text;
  - zero committed phases -> zero acceptance files (valid, no error);
  - phase number zero-padding (e.g. phase 1 -> phase_01_acceptance.md);
  - candidate_conditional increments do not produce an acceptance file.

Anti-overfit fixture: 3 phases / 2 agents (not the 6-agent demo estate).
Stdlib-only, pip-install-free.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_emission_plan import _FOUNDATION_DOC_INPUTS  # noqa: E402
from scaffold_plan import load_scaffold_plan  # noqa: E402
from build_intent import BuildIntent, AgentIntent, ResourceClaims  # noqa: E402
from corpus_loader import load_corpus_pack  # noqa: E402
from emission_plan_assembler import assemble_emission_plan  # noqa: E402
from emission_plan import validate_emission_plan, load_contract, default_contract_path  # noqa: E402
from acceptance_contract_emitter import emit_acceptance_contracts  # noqa: E402

SP = load_scaffold_plan("markdown-CC")
CORPUS = load_corpus_pack()


def _env(cstate="accepted"):
    return {
        "_source": "operator-content",
        "_derivation_class": "extraction",
        "_decision_field": False,
        "_decision_kind": "none",
        "_confirmation_state": cstate,
        "_confirmed_at": "2026-05-30",
    }


# Three-phase / two-agent CAPABILITY_INCREMENTS fixture (anti-overfit: not 6-agent).
# Phase 1 (mvp): Ingestion handled by Collector.
# Phase 2 (post_mvp_roadmap): Summarisation handled by Summariser.
# Phase 3 (post_mvp_roadmap): Archive handled by Collector.
# One candidate_conditional: should NOT produce an acceptance file.
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


def _dr_with_increments():
    """Derived record with CAPABILITY_INCREMENTS set (accepted)."""
    inp = dict(_FOUNDATION_DOC_INPUTS)
    inp["CAPABILITY_INCREMENTS"] = json.dumps(_THREE_PHASE_INCREMENTS)
    rec = dict(inp)
    rec["_audit"] = {k: _env("accepted") for k in inp}
    return rec


def _dr_no_increments():
    """Derived record without CAPABILITY_INCREMENTS (not present in _audit)."""
    inp = dict(_FOUNDATION_DOC_INPUTS)
    rec = dict(inp)
    rec["_audit"] = {k: _env("accepted") for k in inp}
    return rec


def _dr_empty_increments():
    """Derived record with CAPABILITY_INCREMENTS as an empty list."""
    inp = dict(_FOUNDATION_DOC_INPUTS)
    inp["CAPABILITY_INCREMENTS"] = json.dumps([])
    rec = dict(inp)
    rec["_audit"] = {k: _env("accepted") for k in inp}
    return rec


def _dr_only_candidates():
    """Derived record with CAPABILITY_INCREMENTS containing only candidate_conditional."""
    increments = [
        {
            "capability": "Maybe export",
            "release_bucket": "candidate_conditional",
            "phase": None,
            "condition": "If needed",
            "agents": "Collector",
            "depends_on": [],
        }
    ]
    inp = dict(_FOUNDATION_DOC_INPUTS)
    inp["CAPABILITY_INCREMENTS"] = json.dumps(increments)
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


class AcceptanceContractEmitTests(unittest.TestCase):
    """Acceptance contracts wired into the emission pipeline."""

    def _assemble(self, dr, agents):
        bi = BuildIntent(derived_record=dr, agent_intents=agents)
        return assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)

    # ------------------------------------------------------------------
    # (a) emitted_files path registration
    # ------------------------------------------------------------------

    def test_three_phases_register_three_acceptance_files(self):
        """One acceptance file per committed phase registered in emitted_files."""
        plan = self._assemble(
            _dr_with_increments(), [_ai_collector(), _ai_summariser()]
        )
        acceptance_paths = {
            ef["path"] for ef in plan["emitted_files"]
            if ef["path"].startswith("agents/acceptance/")
        }
        self.assertEqual(acceptance_paths, {
            "agents/acceptance/phase_01_acceptance.md",
            "agents/acceptance/phase_02_acceptance.md",
            "agents/acceptance/phase_03_acceptance.md",
        })

    def test_zero_pad_phase_number(self):
        """Phase 1 -> phase_01_acceptance.md (zero-padded to 2 digits)."""
        plan = self._assemble(
            _dr_with_increments(), [_ai_collector(), _ai_summariser()]
        )
        paths = {ef["path"] for ef in plan["emitted_files"]}
        self.assertIn("agents/acceptance/phase_01_acceptance.md", paths)
        self.assertNotIn("agents/acceptance/phase_1_acceptance.md", paths)

    def test_candidate_conditional_not_registered(self):
        """candidate_conditional increments do not produce an acceptance file."""
        plan = self._assemble(
            _dr_with_increments(), [_ai_collector(), _ai_summariser()]
        )
        paths = {ef["path"] for ef in plan["emitted_files"]}
        # Only 3 committed phases; the candidate does not appear.
        acceptance_paths = [p for p in paths if p.startswith("agents/acceptance/")]
        self.assertEqual(len(acceptance_paths), 3)

    def test_no_increments_field_yields_zero_acceptance_files(self):
        """Missing CAPABILITY_INCREMENTS -> zero acceptance files (valid, no error)."""
        plan = self._assemble(_dr_no_increments(), [_ai_collector()])
        acceptance_paths = [
            ef["path"] for ef in plan["emitted_files"]
            if ef["path"].startswith("agents/acceptance/")
        ]
        self.assertEqual(acceptance_paths, [])

    def test_empty_increments_yields_zero_acceptance_files(self):
        """Empty CAPABILITY_INCREMENTS list -> zero acceptance files."""
        plan = self._assemble(_dr_empty_increments(), [_ai_collector()])
        acceptance_paths = [
            ef["path"] for ef in plan["emitted_files"]
            if ef["path"].startswith("agents/acceptance/")
        ]
        self.assertEqual(acceptance_paths, [])

    def test_only_candidates_yields_zero_acceptance_files(self):
        """Only candidate_conditional increments -> zero acceptance files."""
        plan = self._assemble(_dr_only_candidates(), [_ai_collector()])
        acceptance_paths = [
            ef["path"] for ef in plan["emitted_files"]
            if ef["path"].startswith("agents/acceptance/")
        ]
        self.assertEqual(acceptance_paths, [])

    def test_acceptance_emitted_files_have_correct_shape(self):
        """Registered acceptance files carry the same managed_by/merge_strategy as other files."""
        plan = self._assemble(
            _dr_with_increments(), [_ai_collector(), _ai_summariser()]
        )
        acceptance_entries = [
            ef for ef in plan["emitted_files"]
            if ef["path"].startswith("agents/acceptance/")
        ]
        self.assertEqual(len(acceptance_entries), 3)
        for ef in acceptance_entries:
            self.assertIn("managed_by", ef)
            self.assertIn("local_modifications", ef)
            self.assertIn("merge_strategy", ef)
            self.assertIn("source_refs", ef)

    # ------------------------------------------------------------------
    # (b) rendered content
    # ------------------------------------------------------------------

    def test_acceptance_contracts_key_present(self):
        """plan['acceptance_contracts'] is present with one entry per committed phase."""
        plan = self._assemble(
            _dr_with_increments(), [_ai_collector(), _ai_summariser()]
        )
        self.assertIn("acceptance_contracts", plan)
        self.assertEqual(len(plan["acceptance_contracts"]), 3)

    def test_each_contract_has_path_and_content(self):
        """Each acceptance_contracts entry has 'path' and 'content'."""
        plan = self._assemble(
            _dr_with_increments(), [_ai_collector(), _ai_summariser()]
        )
        for entry in plan["acceptance_contracts"]:
            self.assertIn("path", entry)
            self.assertIn("content", entry)
            self.assertTrue(entry["content"], "content must be non-empty")

    def test_content_contains_phase_operator_questions(self):
        """Each rendered file's content contains the operator_questions text for that phase."""
        plan = self._assemble(
            _dr_with_increments(), [_ai_collector(), _ai_summariser()]
        )
        by_path = {e["path"]: e["content"] for e in plan["acceptance_contracts"]}

        # Phase 1: capability is "Ingest incoming items" — primary real-work question must appear.
        p1 = by_path.get("agents/acceptance/phase_01_acceptance.md", "")
        self.assertIn("Ingest incoming items", p1)
        self.assertIn("- [ ]", p1)  # checklist items

        # Phase 2: capability is "Summarise daily batch".
        p2 = by_path.get("agents/acceptance/phase_02_acceptance.md", "")
        self.assertIn("Summarise daily batch", p2)

        # Phase 3: capability is "Archive processed items".
        p3 = by_path.get("agents/acceptance/phase_03_acceptance.md", "")
        self.assertIn("Archive processed items", p3)

    def test_content_contains_required_sections(self):
        """Rendered markdown contains the expected section headings."""
        plan = self._assemble(
            _dr_with_increments(), [_ai_collector(), _ai_summariser()]
        )
        for entry in plan["acceptance_contracts"]:
            content = entry["content"]
            self.assertIn("## What to confirm", content)
            self.assertIn("## What you should see", content)
            self.assertIn("## Core checks", content)

    def test_content_paths_match_emitted_files_paths(self):
        """The paths in acceptance_contracts match those in emitted_files."""
        plan = self._assemble(
            _dr_with_increments(), [_ai_collector(), _ai_summariser()]
        )
        contract_paths = {e["path"] for e in plan["acceptance_contracts"]}
        registered_paths = {
            ef["path"] for ef in plan["emitted_files"]
            if ef["path"].startswith("agents/acceptance/")
        }
        self.assertEqual(contract_paths, registered_paths)

    def test_no_build_ids_in_content(self):
        """Rendered content must not contain build-provenance tokens."""
        import re
        plan = self._assemble(
            _dr_with_increments(), [_ai_collector(), _ai_summariser()]
        )
        pattern = re.compile(r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]')
        for entry in plan["acceptance_contracts"]:
            self.assertIsNone(
                pattern.search(entry["content"]),
                f"build ID found in {entry['path']}: {pattern.search(entry['content'])}"
            )


EP_CONTRACT = load_contract(default_contract_path())


class AcceptanceContractOnDiskTests(unittest.TestCase):
    """On-disk emission: asserts that actual files written to a temp dir carry
    the agent's real acceptance_signals text in the ## Core checks section.

    This test catches the false-green where plan["acceptance_contracts"] has
    correct content but the emitter re-derives content from the typed EmissionPlan
    (which strips acceptance_signals), producing empty ## Core checks on disk.
    """

    def _assemble_and_emit(self):
        """Assemble a plan with known acceptance_signals, validate it into a typed
        EmissionPlan, emit to a temp dir, and return (staging_dir, typed_plan)."""
        dr = _dr_with_increments()
        bi = BuildIntent(derived_record=dr, agent_intents=[_ai_collector(), _ai_summariser()])
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        typed_plan = validate_emission_plan(plan_dict, EP_CONTRACT)
        staging_dir = Path(tempfile.mkdtemp())
        emit_acceptance_contracts(typed_plan, staging_dir)
        return staging_dir, typed_plan

    def test_on_disk_core_checks_contain_acceptance_signals(self):
        """phase_01_acceptance.md on disk must contain Collector's acceptance_signals text.

        Collector's acceptance_signals = ["items collected without error"].
        Phase 1 is handled by Collector. If the emitter re-derives from the typed
        EmissionPlan (which drops acceptance_signals), the ## Core checks section will
        contain the placeholder fallback "No specific acceptance signals recorded for
        this phase." — not the real signal. This test fails RED against pre-fix code.
        """
        staging_dir, _ = self._assemble_and_emit()
        phase_01 = staging_dir / "agents" / "acceptance" / "phase_01_acceptance.md"
        self.assertTrue(phase_01.exists(), f"phase_01_acceptance.md not written to {staging_dir}")
        content = phase_01.read_text(encoding="utf-8")
        # The real signal from _ai_collector().acceptance_signals
        self.assertIn(
            "items collected without error",
            content,
            "## Core checks section is missing the agent's acceptance_signals text on disk. "
            "This indicates the emitter is re-deriving content from the typed EmissionPlan "
            "(which drops acceptance_signals) instead of writing the pre-rendered content "
            "from plan['acceptance_contracts'].",
        )
        # Confirm it does NOT fall back to the empty-signals placeholder
        self.assertNotIn(
            "No specific acceptance signals recorded for this phase.",
            content,
            "## Core checks contains the empty-signals placeholder — emitter re-derived "
            "instead of carrying pre-rendered content through.",
        )

    def test_on_disk_phase_02_contains_summariser_signals(self):
        """phase_02_acceptance.md on disk must contain Summariser's acceptance_signals text."""
        staging_dir, _ = self._assemble_and_emit()
        phase_02 = staging_dir / "agents" / "acceptance" / "phase_02_acceptance.md"
        self.assertTrue(phase_02.exists(), f"phase_02_acceptance.md not written to {staging_dir}")
        content = phase_02.read_text(encoding="utf-8")
        # The real signal from _ai_summariser().acceptance_signals
        self.assertIn(
            "non-empty summary produced",
            content,
            "## Core checks missing Summariser's acceptance_signals on disk.",
        )

    def test_on_disk_three_files_written(self):
        """Three committed phases -> three files on disk."""
        staging_dir, _ = self._assemble_and_emit()
        accept_dir = staging_dir / "agents" / "acceptance"
        written = list(accept_dir.glob("phase_*_acceptance.md"))
        self.assertEqual(len(written), 3, f"Expected 3 on-disk acceptance files, got {len(written)}")


if __name__ == "__main__":
    unittest.main()
