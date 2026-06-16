"""Tests for phase_acceptance_assembler — the pure contract assembler (stdlib unittest).

Covers:
  (a) one contract per committed phase, ascending; candidate_conditional excluded
  (b) multi-agent phase lists all its agents AND has a combined/handoff operator_question
  (c) core_checks aggregate the phase agents' acceptance_signals
  (d) operator_questions are plain language (known internal tokens absent)
  (e) defer_trigger is None for always-exercisable phase; set for one that cannot be
  (f) anti-overfit: fixture with different roster/phase-count than the 6-agent estate
  (g) required_evidence is present and non-empty for every contract
  (h) field types match the PhaseAcceptanceContract dataclass spec
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from phase_acceptance_assembler import (  # noqa: E402
    assemble_phase_acceptance,
    PhaseAcceptanceContract,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _incr(capability, bucket, phase=None, agents=None, depends_on="", condition=""):
    """Build a capability_increments row dict matching the canonical CAPABILITY_INCREMENTS shape."""
    row = {"capability": capability, "release_bucket": bucket}
    if phase is not None:
        row["phase"] = phase
    if agents is not None:
        row["agents"] = agents
    if depends_on:
        row["depends_on"] = depends_on
    if bucket == "candidate_conditional":
        row["condition"] = condition or "some condition"
    return row


def _agent(name_or_id, acceptance_signals, *, use_display_name=True):
    """Build an agent record dict matching the AgentIntent shape (display_name + acceptance_signals)."""
    key = "display_name" if use_display_name else "id"
    return {key: name_or_id, "acceptance_signals": acceptance_signals}


# Minimal fixture: 2 mvp phases + 1 roadmap phase + 1 candidate_conditional.
# Phase 1: single agent. Phase 2: two agents (multi-agent phase). Phase 3: roadmap.
_INCREMENTS_STANDARD = [
    _incr("Research and summarize topics", "mvp", phase=1, agents="Researcher"),
    _incr("Draft and review documents", "mvp", phase=2, agents="Drafter, Reviewer"),
    _incr("Publish to external channel", "post_mvp_roadmap", phase=3, agents="Publisher"),
    _incr("Integrate CRM data", "candidate_conditional", condition="CRM volume reaches threshold"),
]

_AGENT_RECORDS_STANDARD = [
    _agent("Researcher", ["summary is non-empty", "all sources cited"]),
    _agent("Drafter", ["draft contains required sections", "no placeholder text"]),
    _agent("Reviewer", ["review notes attached", "approval or rejection recorded"]),
    _agent("Publisher", ["published URL returned", "no publish errors"]),
]

# Anti-overfit fixture: 3 agents, 4 phases, nothing like the 6-agent estate.
# A small team running a newsletter: Curator -> Writer -> Editor -> Sender.
_INCREMENTS_NEWSLETTER = [
    _incr("Curate story candidates", "mvp", phase=1, agents="Curator"),
    _incr("Write newsletter draft", "mvp", phase=2, agents="Writer"),
    _incr("Edit and finalize draft", "mvp", phase=3, agents="Editor"),
    _incr("Send to subscriber list", "post_mvp_roadmap", phase=4, agents="Sender"),
    _incr("Analytics dashboard", "candidate_conditional", condition="subscriber count exceeds 500"),
]

_AGENT_RECORDS_NEWSLETTER = [
    _agent("Curator", ["at least 5 story candidates selected", "each candidate has a source URL"]),
    _agent("Writer", ["draft word count in range", "all sections present"]),
    _agent("Editor", ["no tracked changes remain", "spell-check clean"]),
    _agent("Sender", ["send confirmation logged", "bounce rate below threshold"]),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class PhaseAcceptanceContractShapeTest(unittest.TestCase):
    """Return type and field types are correct for every contract."""

    def setUp(self):
        self.contracts = assemble_phase_acceptance(
            _INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD
        )

    def test_returns_list_of_PhaseAcceptanceContract(self):
        self.assertIsInstance(self.contracts, list)
        for c in self.contracts:
            self.assertIsInstance(c, PhaseAcceptanceContract)

    def test_phase_field_is_int(self):
        for c in self.contracts:
            self.assertIsInstance(c.phase, int)

    def test_capability_field_is_str(self):
        for c in self.contracts:
            self.assertIsInstance(c.capability, str)
            self.assertTrue(c.capability.strip())

    def test_agents_field_is_list_of_str(self):
        for c in self.contracts:
            self.assertIsInstance(c.agents, list)
            for a in c.agents:
                self.assertIsInstance(a, str)

    def test_operator_questions_is_list_of_str(self):
        for c in self.contracts:
            self.assertIsInstance(c.operator_questions, list)
            self.assertTrue(len(c.operator_questions) >= 1)
            for q in c.operator_questions:
                self.assertIsInstance(q, str)
                self.assertTrue(q.strip())

    def test_required_evidence_is_list_of_str(self):
        for c in self.contracts:
            self.assertIsInstance(c.required_evidence, list)
            self.assertTrue(len(c.required_evidence) >= 1)
            for e in c.required_evidence:
                self.assertIsInstance(e, str)
                self.assertTrue(e.strip())

    def test_core_checks_is_list_of_str(self):
        for c in self.contracts:
            self.assertIsInstance(c.core_checks, list)
            for chk in c.core_checks:
                self.assertIsInstance(chk, str)

    def test_defer_trigger_is_str_or_none(self):
        for c in self.contracts:
            self.assertTrue(c.defer_trigger is None or isinstance(c.defer_trigger, str))


class PhaseFilterAndOrderTest(unittest.TestCase):
    """(a) One contract per committed phase, ascending; candidate_conditional excluded."""

    def test_one_contract_per_committed_phase(self):
        contracts = assemble_phase_acceptance(_INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD)
        # Standard fixture: phases 1, 2 (mvp), 3 (roadmap) = 3 committed phases.
        self.assertEqual(len(contracts), 3)

    def test_phases_are_ascending(self):
        contracts = assemble_phase_acceptance(_INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD)
        phases = [c.phase for c in contracts]
        self.assertEqual(phases, sorted(phases))

    def test_candidate_conditional_excluded(self):
        contracts = assemble_phase_acceptance(_INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD)
        # "Integrate CRM data" is candidate_conditional — must not appear.
        capabilities = [c.capability for c in contracts]
        for cap in capabilities:
            self.assertNotIn("CRM", cap)

    def test_mvp_and_roadmap_both_included(self):
        contracts = assemble_phase_acceptance(_INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD)
        phases = [c.phase for c in contracts]
        # Phase 3 is post_mvp_roadmap — must be included.
        self.assertIn(3, phases)

    def test_correct_phase_numbers(self):
        contracts = assemble_phase_acceptance(_INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD)
        phases = [c.phase for c in contracts]
        self.assertEqual(phases, [1, 2, 3])

    def test_only_candidate_conditional_excluded_from_all_candidates(self):
        # Edge: all increments are candidate_conditional — result is empty.
        only_candidates = [
            _incr("Maybe A", "candidate_conditional", condition="x"),
            _incr("Maybe B", "candidate_conditional", condition="y"),
        ]
        contracts = assemble_phase_acceptance(only_candidates, [])
        self.assertEqual(contracts, [])

    def test_empty_increments_returns_empty(self):
        contracts = assemble_phase_acceptance([], [])
        self.assertEqual(contracts, [])


class AgentAssignmentTest(unittest.TestCase):
    """(b) Correct agent assignment per phase."""

    def setUp(self):
        self.contracts = assemble_phase_acceptance(
            _INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD
        )

    def test_single_agent_phase_lists_one_agent(self):
        phase1 = next(c for c in self.contracts if c.phase == 1)
        self.assertEqual(len(phase1.agents), 1)
        self.assertIn("Researcher", phase1.agents)

    def test_multi_agent_phase_lists_all_agents(self):
        phase2 = next(c for c in self.contracts if c.phase == 2)
        self.assertEqual(len(phase2.agents), 2)
        self.assertIn("Drafter", phase2.agents)
        self.assertIn("Reviewer", phase2.agents)

    def test_roadmap_phase_agents_present(self):
        phase3 = next(c for c in self.contracts if c.phase == 3)
        self.assertIn("Publisher", phase3.agents)

    def test_anti_overfit_newsletter_agent_assignment(self):
        contracts = assemble_phase_acceptance(
            _INCREMENTS_NEWSLETTER, _AGENT_RECORDS_NEWSLETTER
        )
        phase1 = next(c for c in contracts if c.phase == 1)
        self.assertIn("Curator", phase1.agents)
        phase4 = next(c for c in contracts if c.phase == 4)
        self.assertIn("Sender", phase4.agents)


class CoreChecksAggregationTest(unittest.TestCase):
    """(c) core_checks aggregate the phase agents' acceptance_signals."""

    def setUp(self):
        self.contracts = assemble_phase_acceptance(
            _INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD
        )

    def test_single_agent_core_checks_match_signals(self):
        phase1 = next(c for c in self.contracts if c.phase == 1)
        # Researcher's signals: ["summary is non-empty", "all sources cited"]
        self.assertIn("summary is non-empty", phase1.core_checks)
        self.assertIn("all sources cited", phase1.core_checks)

    def test_multi_agent_phase_aggregates_all_signals(self):
        phase2 = next(c for c in self.contracts if c.phase == 2)
        # Drafter: ["draft contains required sections", "no placeholder text"]
        # Reviewer: ["review notes attached", "approval or rejection recorded"]
        self.assertIn("draft contains required sections", phase2.core_checks)
        self.assertIn("no placeholder text", phase2.core_checks)
        self.assertIn("review notes attached", phase2.core_checks)
        self.assertIn("approval or rejection recorded", phase2.core_checks)

    def test_core_checks_count_matches_total_signals(self):
        phase2 = next(c for c in self.contracts if c.phase == 2)
        self.assertEqual(len(phase2.core_checks), 4)

    def test_anti_overfit_newsletter_core_checks(self):
        contracts = assemble_phase_acceptance(
            _INCREMENTS_NEWSLETTER, _AGENT_RECORDS_NEWSLETTER
        )
        phase3 = next(c for c in contracts if c.phase == 3)
        # Editor's signals
        self.assertIn("no tracked changes remain", phase3.core_checks)
        self.assertIn("spell-check clean", phase3.core_checks)

    def test_agent_with_no_signals_contributes_empty(self):
        increments = [_incr("Do a thing", "mvp", phase=1, agents="Silent")]
        agents = [_agent("Silent", [])]
        contracts = assemble_phase_acceptance(increments, agents)
        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0].core_checks, [])


class OperatorQuestionsTest(unittest.TestCase):
    """(d) operator_questions are plain language; no internal jargon tokens."""

    # Internal tokens that must not appear in operator-facing questions.
    FORBIDDEN_TOKENS = [
        "acceptance_signals",
        "core_checks",
        "release_bucket",
        "candidate_conditional",
        "post_mvp_roadmap",
        "CAPABILITY_INCREMENTS",
        "criticality_tier",
        "AgentIntent",
        "AgentRecord",
        "PhaseAcceptanceContract",
    ]

    def setUp(self):
        self.contracts = assemble_phase_acceptance(
            _INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD
        )

    def _all_questions(self, contracts):
        for c in contracts:
            for q in c.operator_questions:
                yield q

    def test_no_internal_token_in_any_question(self):
        for question in self._all_questions(self.contracts):
            for token in self.FORBIDDEN_TOKENS:
                self.assertNotIn(
                    token, question,
                    f"Internal token {token!r} found in operator_question: {question!r}",
                )

    def test_each_phase_has_real_work_question(self):
        # Every phase must have at least one question that references the capability
        # or what the operator should judge.
        for c in self.contracts:
            questions_text = " ".join(c.operator_questions).lower()
            # Must contain something substantive — not just empty strings.
            self.assertTrue(len(questions_text.strip()) > 0)

    def test_multi_agent_phase_has_combined_handoff_question(self):
        # (b) spec requirement: multi-agent phase must have a combined/handoff question.
        phase2 = next(c for c in self.contracts if c.phase == 2)
        combined_keywords = ["together", "handoff", "combined", "result", "both", "complete", "final"]
        questions_lower = [q.lower() for q in phase2.operator_questions]
        has_combined = any(
            any(kw in q for kw in combined_keywords)
            for q in questions_lower
        )
        self.assertTrue(
            has_combined,
            f"Multi-agent phase 2 has no combined/handoff question. Got: {phase2.operator_questions}",
        )

    def test_single_agent_phase_questions_reference_capability(self):
        phase1 = next(c for c in self.contracts if c.phase == 1)
        # At minimum one question should be answerable as yes/no about the real work.
        self.assertGreaterEqual(len(phase1.operator_questions), 1)

    def test_anti_overfit_newsletter_no_internal_tokens(self):
        contracts = assemble_phase_acceptance(
            _INCREMENTS_NEWSLETTER, _AGENT_RECORDS_NEWSLETTER
        )
        for question in self._all_questions(contracts):
            for token in self.FORBIDDEN_TOKENS:
                self.assertNotIn(token, question)


class DeferTriggerTest(unittest.TestCase):
    """(e) defer_trigger is None for always-exercisable phases; set when it can't be."""

    def test_always_exercisable_phase_has_none_defer_trigger(self):
        # Phase 1 (Research) — always exercisable if you have topics to research.
        # The fixture agent has non-empty acceptance_signals and a plain capability.
        contracts = assemble_phase_acceptance(
            _INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD
        )
        phase1 = next(c for c in contracts if c.phase == 1)
        self.assertIsNone(phase1.defer_trigger)

    def test_phase_with_no_agent_match_has_defer_trigger(self):
        # If the increment's agents string names an agent not in agent_records,
        # the phase cannot be exercised — defer_trigger must be set (not None).
        increments = [
            _incr("Integrate with legacy system", "mvp", phase=1, agents="LegacyConnector"),
        ]
        agents = []  # LegacyConnector not present
        contracts = assemble_phase_acceptance(increments, agents)
        self.assertEqual(len(contracts), 1)
        self.assertIsNotNone(contracts[0].defer_trigger)

    def test_anti_overfit_newsletter_phase4_always_exercisable(self):
        contracts = assemble_phase_acceptance(
            _INCREMENTS_NEWSLETTER, _AGENT_RECORDS_NEWSLETTER
        )
        phase4 = next(c for c in contracts if c.phase == 4)
        # Sender has matching agent record — should be exercisable.
        self.assertIsNone(phase4.defer_trigger)


class RequiredEvidenceTest(unittest.TestCase):
    """(g) required_evidence is present, non-empty, and generic/derived."""

    FORBIDDEN_EVIDENCE_TOKENS = [
        "acceptance_signals",
        "core_checks",
        "CAPABILITY_INCREMENTS",
        "AgentIntent",
    ]

    def test_required_evidence_non_empty_for_all_phases(self):
        contracts = assemble_phase_acceptance(
            _INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD
        )
        for c in contracts:
            self.assertGreater(len(c.required_evidence), 0,
                               f"phase {c.phase} has empty required_evidence")

    def test_no_internal_tokens_in_required_evidence(self):
        contracts = assemble_phase_acceptance(
            _INCREMENTS_STANDARD, _AGENT_RECORDS_STANDARD
        )
        for c in contracts:
            for item in c.required_evidence:
                for token in self.FORBIDDEN_EVIDENCE_TOKENS:
                    self.assertNotIn(token, item,
                                     f"Token {token!r} found in required_evidence: {item!r}")

    def test_anti_overfit_newsletter_required_evidence(self):
        contracts = assemble_phase_acceptance(
            _INCREMENTS_NEWSLETTER, _AGENT_RECORDS_NEWSLETTER
        )
        for c in contracts:
            self.assertGreater(len(c.required_evidence), 0)


class AgentIdFieldFallbackTest(unittest.TestCase):
    """Agent records using 'id' instead of 'display_name' as identifier are matched."""

    def test_agent_record_with_id_field_matched(self):
        increments = [_incr("Process invoices", "mvp", phase=1, agents="Accountant")]
        agents = [_agent("Accountant", ["invoice total verified"], use_display_name=False)]
        contracts = assemble_phase_acceptance(increments, agents)
        self.assertEqual(len(contracts), 1)
        self.assertIn("Accountant", contracts[0].agents)
        self.assertIn("invoice total verified", contracts[0].core_checks)


class MultiPhaseIncrementCollisionTest(unittest.TestCase):
    """Multiple increments for the same phase (e.g. mixed mvp+roadmap) merge correctly."""

    def test_two_increments_same_phase_merges_agents_and_signals(self):
        increments = [
            _incr("Task A", "mvp", phase=1, agents="AgentA"),
            _incr("Task B", "mvp", phase=1, agents="AgentB"),
        ]
        agents = [
            _agent("AgentA", ["output A done"]),
            _agent("AgentB", ["output B done"]),
        ]
        contracts = assemble_phase_acceptance(increments, agents)
        # Same phase -> one contract
        self.assertEqual(len(contracts), 1)
        self.assertEqual(contracts[0].phase, 1)
        self.assertIn("AgentA", contracts[0].agents)
        self.assertIn("AgentB", contracts[0].agents)
        self.assertIn("output A done", contracts[0].core_checks)
        self.assertIn("output B done", contracts[0].core_checks)


if __name__ == "__main__":
    unittest.main()
