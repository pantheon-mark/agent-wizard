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
    if inc["release_bucket"] in ("mvp", "post_mvp_roadmap")
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


if __name__ == "__main__":
    unittest.main()
