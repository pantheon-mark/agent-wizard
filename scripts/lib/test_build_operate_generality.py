"""Anti-overfit generality matrix for the build-and-operate pipeline (stdlib unittest).

Task F1: divergent fixture matrix — varies roster size, phase count, autonomy level,
external-integration presence, scheduled-vs-interactive, plus edge cases. Asserts
input-independent invariants across ALL fixtures.

Task F2: emission guards — per-committed-phase file count on a divergent fixture;
build_progress.md well-formedness; supervised/copy-target + injected-dummy instruction
present in source files; no residual placeholders in emitted manual.md; next-phase.md
self-containment.

Each fixture comment names which estate-hardcoded shortcut it would catch.
Stdlib-only, pip-install-free.
"""

import json
import re
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
from capability_projection import BUCKET_MVP, BUCKET_ROADMAP  # noqa: E402
from acceptance_contract_emitter import emit_acceptance_contracts  # noqa: E402
from scaffold_emitter import emit_scaffold  # noqa: E402

SP = load_scaffold_plan("markdown-CC")
CORPUS = load_corpus_pack()
EP_CONTRACT = load_contract(default_contract_path())
REPO_ROOT = Path(__file__).resolve().parents[3]

# Internal jargon tokens that must never appear in operator_questions.
_JARGON_TOKENS = [
    "_derivation",
    "_source",
    "_decision_field",
    "_decision_kind",
    "_confirmation_state",
    "release_bucket",
    "candidate_conditional",
    "post_mvp_roadmap",
    "CAPABILITY_INCREMENTS",
    "criticality_tier",
    "AgentIntent",
    "AgentRecord",
    "PhaseAcceptanceContract",
    "MA-REV",
    "MA-F",
]

# State vocabulary the ledger must carry.
_STATE_VOCAB = ["built", "technically-reviewed", "supervised",
                "provisionally-accepted", "accepted"]
_LAYER_B_VERDICTS = ["confirmed", "fix-needed", "deferred-pending-real-use"]

# Required columns in build_progress.md.
_REQUIRED_COLUMNS = ["Layer-A", "Layer-B", "Open fix items",
                     "Deferred core precondition", "Date"]


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _env(cstate="accepted"):
    return {
        "_source": "operator-content",
        "_derivation_class": "extraction",
        "_decision_field": False,
        "_decision_kind": "none",
        "_confirmation_state": cstate,
        "_confirmed_at": "2026-05-30",
    }


def _make_dr(increments=None):
    """Build a derived record, optionally injecting CAPABILITY_INCREMENTS."""
    inp = dict(_FOUNDATION_DOC_INPUTS)
    if increments is not None:
        inp["CAPABILITY_INCREMENTS"] = json.dumps(increments)
    rec = dict(inp)
    rec["_audit"] = {k: _env("accepted") for k in inp}
    return rec


def _ai(name, signals=None):
    """Build a minimal AgentIntent with the given display_name and acceptance_signals."""
    if signals is None:
        signals = [f"{name.lower()} completed without error"]
    return AgentIntent(
        display_name=name,
        function_summary=f"{name} agent.",
        role_intent=f"{name} does its work.",
        acceptance_signals=signals,
        output_purpose="output",
        criticality_tier="standard",
        resource_claims=ResourceClaims(),
        confidence="high",
        insufficiency_flags=[],
        source_spans=["GEN-1#1"],
    )


def _count_committed(increments):
    """Count committed phases (mvp + post_mvp_roadmap, deduplicated by phase number)."""
    seen_phases = set()
    for inc in increments:
        if inc.get("release_bucket") in (BUCKET_MVP, BUCKET_ROADMAP):
            phase = inc.get("phase")
            if isinstance(phase, int) and not isinstance(phase, bool):
                seen_phases.add(phase)
    return len(seen_phases)


def _assemble(increments, agents):
    dr = _make_dr(increments)
    bi = BuildIntent(derived_record=dr, agent_intents=agents)
    return assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)


# ---------------------------------------------------------------------------
# Fixture definitions
# ---------------------------------------------------------------------------

# FIXTURE A: Single-agent, single-phase (mvp only).
# Catches: hardcoded roster of "Collector/Summariser"; hardcoded phase-count=3;
# hardcoded row-count=3.
_INCR_SINGLE_AGENT_SINGLE_PHASE = [
    {
        "capability": "Classify support tickets",
        "release_bucket": "mvp",
        "phase": 1,
        "agents": "Classifier",
        "depends_on": [],
    },
]
_AGENTS_SINGLE_AGENT = [_ai("Classifier", ["all tickets classified", "no unhandled exceptions"])]

# FIXTURE B: Many agents (4), many phases (5), low autonomy.
# Catches: hardcoded 2-agent roster; hardcoded 3-phase count; hardcoded row count.
_INCR_MANY_AGENTS_MANY_PHASES = [
    {"capability": "Fetch raw data from source", "release_bucket": "mvp", "phase": 1,
     "agents": "Fetcher", "depends_on": []},
    {"capability": "Validate and clean records", "release_bucket": "mvp", "phase": 2,
     "agents": "Validator", "depends_on": ["Fetch raw data from source"]},
    {"capability": "Enrich with metadata", "release_bucket": "post_mvp_roadmap", "phase": 3,
     "agents": "Enricher", "depends_on": ["Validate and clean records"]},
    {"capability": "Generate analytics report", "release_bucket": "post_mvp_roadmap", "phase": 4,
     "agents": "Reporter", "depends_on": ["Enrich with metadata"]},
    {"capability": "Distribute report to recipients", "release_bucket": "post_mvp_roadmap", "phase": 5,
     "agents": "Distributor", "depends_on": ["Generate analytics report"]},
    {"capability": "Archive to cold storage (optional)", "release_bucket": "candidate_conditional",
     "phase": None, "condition": "If storage cost exceeds budget", "agents": "Archiver",
     "depends_on": []},
]
_AGENTS_MANY = [
    _ai("Fetcher", ["source endpoint reachable", "data downloaded without error"]),
    _ai("Validator", ["all records pass schema check", "error count within threshold"]),
    _ai("Enricher", ["metadata appended to all records"]),
    _ai("Reporter", ["report file written", "row count matches input"]),
    _ai("Distributor", ["delivery confirmation logged"]),
]

# FIXTURE C: External-integration phase (capability mentions external dependency).
# Catches: any code that skips the supervised/copy rule for non-integration projects.
# The external dependency is explicit in the capability name.
_INCR_EXTERNAL_INTEGRATION = [
    {"capability": "Pull invoices from accounting API", "release_bucket": "mvp", "phase": 1,
     "agents": "InvoicePuller", "depends_on": []},
    {"capability": "Post reconciled totals to accounting API", "release_bucket": "post_mvp_roadmap",
     "phase": 2, "agents": "Reconciler", "depends_on": ["Pull invoices from accounting API"]},
]
_AGENTS_EXTERNAL = [
    _ai("InvoicePuller", ["invoice list downloaded", "API call returned 200"]),
    _ai("Reconciler", ["totals posted", "reconciliation log written"]),
]

# FIXTURE D: Scheduled-vs-interactive (capability describes a scheduled nightly job).
# Catches: hardcoded interactive-only assumption; phase-count mismatch.
_INCR_SCHEDULED = [
    {"capability": "Run nightly data sync", "release_bucket": "mvp", "phase": 1,
     "agents": "NightlySyncer", "depends_on": []},
    {"capability": "Generate weekly digest email", "release_bucket": "post_mvp_roadmap", "phase": 2,
     "agents": "DigestMailer", "depends_on": ["Run nightly data sync"]},
]
_AGENTS_SCHEDULED = [
    _ai("NightlySyncer", ["sync log written", "delta count recorded"]),
    _ai("DigestMailer", ["email queued", "subject line confirmed"]),
]

# FIXTURE E: One-agent system (single agent handles all phases).
# Catches: multi-agent assumptions in any invariant.
_INCR_ONE_AGENT_MULTI_PHASE = [
    {"capability": "Draft daily briefing", "release_bucket": "mvp", "phase": 1,
     "agents": "Briefer", "depends_on": []},
    {"capability": "Distribute briefing to subscribers", "release_bucket": "post_mvp_roadmap",
     "phase": 2, "agents": "Briefer", "depends_on": ["Draft daily briefing"]},
]
_AGENTS_ONE_AGENT = [_ai("Briefer", ["briefing written", "all sections present"])]

# FIXTURE F: Foundation-only — zero committed phases (all candidate_conditional).
# Catches: crash on empty output; any code asserting minimum 1 phase.
_INCR_FOUNDATION_ONLY = [
    {"capability": "Maybe add CRM integration", "release_bucket": "candidate_conditional",
     "phase": None, "condition": "If operator adopts CRM", "agents": "CRMAgent", "depends_on": []},
]
_AGENTS_FOUNDATION_ONLY = [_ai("CRMAgent")]

# FIXTURE G: Multi-agent phase (two agents in same phase).
# Catches: single-agent handoff assumption; contracts skipping multi-agent question.
_INCR_MULTI_AGENT_PHASE = [
    {"capability": "Research and draft newsletter", "release_bucket": "mvp", "phase": 1,
     "agents": "Researcher, Writer", "depends_on": []},
    {"capability": "Edit and publish newsletter", "release_bucket": "post_mvp_roadmap", "phase": 2,
     "agents": "Editor", "depends_on": ["Research and draft newsletter"]},
]
_AGENTS_MULTI_AGENT_PHASE = [
    _ai("Researcher", ["at least 3 sources found", "topic covered"]),
    _ai("Writer", ["draft word count in range", "sections present"]),
    _ai("Editor", ["no tracked changes remain", "approved for publish"]),
]

# FIXTURE H: High-autonomy (autonomy level 3).
# Catches: hardcoded autonomy-level assumption in questions or operator text.
_INCR_HIGH_AUTONOMY = [
    {"capability": "Auto-classify and route incoming messages", "release_bucket": "mvp", "phase": 1,
     "agents": "Router", "depends_on": []},
]
_AGENTS_HIGH_AUTONOMY = [_ai("Router", ["all messages routed", "unclassified count is zero"])]


# ---------------------------------------------------------------------------
# F1: Generality invariants across all fixtures
# ---------------------------------------------------------------------------

class GeneralityInvariantsTest(unittest.TestCase):
    """Input-independent invariants across the full divergent fixture matrix.

    Anti-overfit is the point. Every assertion derives its expected value from
    the fixture itself (no hardcoded estate roster/phase-count/3-rows).
    """

    # Each entry: (label, increments, agents)
    ALL_FIXTURES = [
        # estate-shortcut-caught: hardcoded Collector/Summariser roster + 3-phase count
        ("single_agent_single_phase",
         _INCR_SINGLE_AGENT_SINGLE_PHASE, _AGENTS_SINGLE_AGENT),
        # estate-shortcut-caught: hardcoded 2-agent roster + 3-phase count + row-count=3
        ("many_agents_many_phases",
         _INCR_MANY_AGENTS_MANY_PHASES, _AGENTS_MANY),
        # estate-shortcut-caught: skipping supervised/copy-target for external deps
        ("external_integration",
         _INCR_EXTERNAL_INTEGRATION, _AGENTS_EXTERNAL),
        # estate-shortcut-caught: interactive-only assumption; 2-phase not 3
        ("scheduled_phases",
         _INCR_SCHEDULED, _AGENTS_SCHEDULED),
        # estate-shortcut-caught: multi-agent handoff assertion on single-agent system
        ("one_agent_multi_phase",
         _INCR_ONE_AGENT_MULTI_PHASE, _AGENTS_ONE_AGENT),
        # estate-shortcut-caught: crash or non-zero output on zero committed phases
        ("foundation_only_zero_committed",
         _INCR_FOUNDATION_ONLY, _AGENTS_FOUNDATION_ONLY),
        # estate-shortcut-caught: missing combined/handoff question in multi-agent phase
        ("multi_agent_phase",
         _INCR_MULTI_AGENT_PHASE, _AGENTS_MULTI_AGENT_PHASE),
        # estate-shortcut-caught: hardcoded autonomy or roster assumptions at high-autonomy
        ("high_autonomy",
         _INCR_HIGH_AUTONOMY, _AGENTS_HIGH_AUTONOMY),
    ]

    def _contracts_for(self, increments, agents):
        plan = _assemble(increments, agents)
        return plan.get("acceptance_contracts", [])

    def _committed_count(self, increments):
        return _count_committed(increments)

    # --- I1: exactly one acceptance contract per committed phase ---

    def test_contract_count_equals_committed_phase_count_all_fixtures(self):
        """One acceptance contract per committed phase across all divergent fixtures."""
        for label, increments, agents in self.ALL_FIXTURES:
            with self.subTest(fixture=label):
                expected = self._committed_count(increments)
                contracts = self._contracts_for(increments, agents)
                self.assertEqual(
                    len(contracts), expected,
                    f"[{label}] expected {expected} contracts, got {len(contracts)}",
                )

    # --- I2: BUILD_PROGRESS_ROWS row count == committed-phase count ---

    def test_ledger_row_count_equals_committed_phase_count_all_fixtures(self):
        """BUILD_PROGRESS_ROWS row count tracks committed phases for every fixture."""
        for label, increments, agents in self.ALL_FIXTURES:
            with self.subTest(fixture=label):
                expected = self._committed_count(increments)
                plan = _assemble(increments, agents)
                rows_text = plan["foundation_doc_inputs"].get("BUILD_PROGRESS_ROWS", "")
                rows = [ln for ln in rows_text.splitlines() if ln.strip().startswith("|")]
                self.assertEqual(
                    len(rows), expected,
                    f"[{label}] expected {expected} ledger rows, got {len(rows)}: {rows_text!r}",
                )

    # --- I3: operator_questions are non-empty plain language with no jargon ---

    def test_operator_questions_non_empty_no_jargon_all_fixtures(self):
        """operator_questions are non-empty plain language; no internal jargon tokens."""
        for label, increments, agents in self.ALL_FIXTURES:
            with self.subTest(fixture=label):
                contracts = self._contracts_for(increments, agents)
                for entry in contracts:
                    content = entry.get("content", "")
                    # Must be non-empty
                    self.assertTrue(
                        content.strip(),
                        f"[{label}] acceptance contract content is empty",
                    )
                    # No jargon tokens in the rendered content
                    for token in _JARGON_TOKENS:
                        self.assertNotIn(
                            token, content,
                            f"[{label}] jargon token {token!r} found in acceptance contract",
                        )

    # --- I4: defer_trigger present and non-empty for every committed phase ---

    def test_defer_trigger_present_all_committed_phases_all_fixtures(self):
        """defer_trigger is present (non-empty) in rendered content for every committed phase."""
        for label, increments, agents in self.ALL_FIXTURES:
            with self.subTest(fixture=label):
                contracts = self._contracts_for(increments, agents)
                for entry in contracts:
                    content = entry.get("content", "")
                    # The rendered markdown must contain a deferral section
                    self.assertIn(
                        "defer",
                        content.lower(),
                        f"[{label}] no defer/deferral text in acceptance contract {entry.get('path', '?')}",
                    )

    # --- I5: defer_trigger references the phase's own capability ---

    def test_defer_trigger_references_own_capability_all_fixtures(self):
        """Each committed phase's rendered content contains its own capability string."""
        for label, increments, agents in self.ALL_FIXTURES:
            with self.subTest(fixture=label):
                # Use phase_acceptance_assembler directly for this invariant
                from phase_acceptance_assembler import assemble_phase_acceptance  # noqa
                agent_dicts = [
                    {"display_name": a.display_name, "acceptance_signals": list(a.acceptance_signals)}
                    for a in agents
                ]
                phcontracts = assemble_phase_acceptance(increments, agent_dicts)
                for c in phcontracts:
                    self.assertIn(
                        c.capability,
                        c.defer_trigger,
                        f"[{label}] phase {c.phase} defer_trigger missing capability {c.capability!r}",
                    )

    # --- I6: Foundation-only / zero-committed-phases yields 0 contracts without crash ---

    def test_foundation_only_yields_zero_gracefully(self):
        """Zero committed phases: 0 acceptance contracts, 0 ledger rows, no crash."""
        plan = _assemble(_INCR_FOUNDATION_ONLY, _AGENTS_FOUNDATION_ONLY)
        contracts = plan.get("acceptance_contracts", [])
        rows_text = plan["foundation_doc_inputs"].get("BUILD_PROGRESS_ROWS", "")
        rows = [ln for ln in rows_text.splitlines() if ln.strip().startswith("|")]
        self.assertEqual(len(contracts), 0,
                         f"foundation-only fixture must yield 0 contracts, got {len(contracts)}")
        self.assertEqual(len(rows), 0,
                         f"foundation-only fixture must yield 0 ledger rows, got {len(rows)}")

    # --- I7: Multi-agent phase has combined/handoff question; single-agent does not fabricate one ---

    def test_multi_agent_phase_has_handoff_question(self):
        """Multi-agent phase (Researcher + Writer) has a combined/handoff operator question."""
        from phase_acceptance_assembler import assemble_phase_acceptance  # noqa
        agent_dicts = [
            {"display_name": a.display_name, "acceptance_signals": list(a.acceptance_signals)}
            for a in _AGENTS_MULTI_AGENT_PHASE
        ]
        phcontracts = assemble_phase_acceptance(_INCR_MULTI_AGENT_PHASE, agent_dicts)
        phase1 = next(c for c in phcontracts if c.phase == 1)
        # Phase 1 has 2 agents (Researcher, Writer) — must have a combined/handoff question.
        combined_kw = ["together", "handoff", "combined", "result", "both", "complete", "final"]
        questions_lower = [q.lower() for q in phase1.operator_questions]
        has_combined = any(any(kw in q for kw in combined_kw) for q in questions_lower)
        self.assertTrue(
            has_combined,
            f"Multi-agent phase 1 missing combined/handoff question. Got: {phase1.operator_questions}",
        )

    def test_single_agent_phase_does_not_fabricate_handoff_question(self):
        """Single-agent phase must not contain a multi-agent handoff question."""
        from phase_acceptance_assembler import assemble_phase_acceptance  # noqa
        agent_dicts = [
            {"display_name": a.display_name, "acceptance_signals": list(a.acceptance_signals)}
            for a in _AGENTS_SINGLE_AGENT
        ]
        phcontracts = assemble_phase_acceptance(_INCR_SINGLE_AGENT_SINGLE_PHASE, agent_dicts)
        phase1 = phcontracts[0]
        self.assertEqual(len(phase1.agents), 1, "fixture integrity: should be 1 agent")
        # Must not have a fabricated handoff question.
        for q in phase1.operator_questions:
            self.assertNotIn(
                "handoff", q.lower(),
                f"Single-agent phase should not have a handoff question, got: {q!r}",
            )

    # --- I8: Anti-overfit — estate-roster shortcut would fail on divergent fixture ---
    # (Verified manually in the anti-overfit-bites demonstration; invariant I1 covers it
    # structurally: any hardcode of 3 would fail on single-phase or 5-phase fixtures.)


class AntiOverfitDivergentFixtureTest(unittest.TestCase):
    """Anti-overfit structural test: asserts counts from divergent fixtures directly.

    The estate pilot has 3 committed phases, 2 agents (Collector, Summariser).
    These fixtures ensure assertions track each fixture's own values, not
    estate-specific constants. Any code that hardcodes Collector/Summariser or
    3 phases will fail here.

    Estate-shortcut caught by each fixture:
    - single_agent_single_phase: hardcoded Collector/Summariser roster + count==3
    - many_agents_many_phases: hardcoded 2-agent + count==3 + row-count==3
    - one_agent_multi_phase: multi-agent handoff assert firing on a 1-agent project
    """

    def test_single_phase_contract_count_is_one_not_three(self):
        """Single-phase fixture: contract count = 1, not 3 (catches count==3 hardcode)."""
        plan = _assemble(_INCR_SINGLE_AGENT_SINGLE_PHASE, _AGENTS_SINGLE_AGENT)
        contracts = plan.get("acceptance_contracts", [])
        self.assertEqual(len(contracts), 1,
                         f"single-phase fixture must yield 1 contract, got {len(contracts)}")

    def test_five_phase_contract_count_is_five_not_three(self):
        """5-committed-phase fixture: contract count = 5, not 3 (catches count==3 hardcode)."""
        plan = _assemble(_INCR_MANY_AGENTS_MANY_PHASES, _AGENTS_MANY)
        contracts = plan.get("acceptance_contracts", [])
        self.assertEqual(len(contracts), 5,
                         f"5-phase fixture must yield 5 contracts, got {len(contracts)}")

    def test_five_phase_ledger_row_count_is_five_not_three(self):
        """5-phase fixture: BUILD_PROGRESS_ROWS has 5 rows, not 3."""
        plan = _assemble(_INCR_MANY_AGENTS_MANY_PHASES, _AGENTS_MANY)
        rows_text = plan["foundation_doc_inputs"].get("BUILD_PROGRESS_ROWS", "")
        rows = [ln for ln in rows_text.splitlines() if ln.strip().startswith("|")]
        self.assertEqual(len(rows), 5,
                         f"5-phase fixture must yield 5 ledger rows, got {len(rows)}")

    def test_capabilities_match_divergent_fixture_not_estate(self):
        """Acceptance contracts reference this fixture's capabilities, not the estate's."""
        plan = _assemble(_INCR_MANY_AGENTS_MANY_PHASES, _AGENTS_MANY)
        contracts = plan.get("acceptance_contracts", [])
        content_all = " ".join(e["content"] for e in contracts)
        # Estate capability must NOT appear
        self.assertNotIn("Ingest incoming items", content_all)
        # This fixture's own capabilities MUST appear
        self.assertIn("Fetch raw data from source", content_all)
        self.assertIn("Distribute report to recipients", content_all)

    def test_external_integration_phase_count_is_two(self):
        """External-integration fixture yields 2 contracts (not 3)."""
        plan = _assemble(_INCR_EXTERNAL_INTEGRATION, _AGENTS_EXTERNAL)
        contracts = plan.get("acceptance_contracts", [])
        self.assertEqual(len(contracts), 2,
                         f"external-integration fixture must yield 2 contracts, got {len(contracts)}")


# ---------------------------------------------------------------------------
# F2(a): Emission guards — file count on a divergent fixture
# ---------------------------------------------------------------------------

class EmissionFileCountGuardTest(unittest.TestCase):
    """F2(a): Every committed phase has an acceptance contract emitted on disk.

    Uses a divergent fixture (5 phases, 5 agents) so any hardcoded count=3 fails.
    Estate-shortcut caught: hardcoded 3-file assumption in emitter.
    """

    def _assemble_and_emit(self, increments, agents):
        dr = _make_dr(increments)
        bi = BuildIntent(derived_record=dr, agent_intents=agents)
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        typed_plan = validate_emission_plan(plan_dict, EP_CONTRACT)
        staging_dir = Path(tempfile.mkdtemp())
        emit_acceptance_contracts(typed_plan, staging_dir)
        return staging_dir

    def test_five_phase_fixture_emits_five_acceptance_files(self):
        """5-phase divergent fixture: exactly 5 acceptance files on disk."""
        staging_dir = self._assemble_and_emit(
            _INCR_MANY_AGENTS_MANY_PHASES, _AGENTS_MANY
        )
        accept_dir = staging_dir / "agents" / "acceptance"
        written = sorted(accept_dir.glob("phase_*_acceptance.md"))
        self.assertEqual(
            len(written), 5,
            f"expected 5 acceptance files on disk, got {len(written)}: "
            f"{[f.name for f in written]}",
        )

    def test_single_phase_fixture_emits_one_acceptance_file(self):
        """Single-phase divergent fixture: exactly 1 acceptance file on disk."""
        staging_dir = self._assemble_and_emit(
            _INCR_SINGLE_AGENT_SINGLE_PHASE, _AGENTS_SINGLE_AGENT
        )
        accept_dir = staging_dir / "agents" / "acceptance"
        written = sorted(accept_dir.glob("phase_*_acceptance.md"))
        self.assertEqual(
            len(written), 1,
            f"expected 1 acceptance file on disk, got {len(written)}: "
            f"{[f.name for f in written]}",
        )

    def test_foundation_only_fixture_emits_zero_acceptance_files(self):
        """Foundation-only fixture: 0 acceptance files, no crash."""
        staging_dir = self._assemble_and_emit(
            _INCR_FOUNDATION_ONLY, _AGENTS_FOUNDATION_ONLY
        )
        accept_dir = staging_dir / "agents" / "acceptance"
        # Directory may not exist at all (acceptable) or may be empty.
        written = sorted(accept_dir.glob("phase_*_acceptance.md")) if accept_dir.exists() else []
        self.assertEqual(
            len(written), 0,
            f"expected 0 acceptance files on disk, got {len(written)}",
        )

    def test_emitted_file_count_matches_registered_path_count(self):
        """On-disk file count == emitted_files path count for the divergent fixture."""
        dr = _make_dr(_INCR_MANY_AGENTS_MANY_PHASES)
        bi = BuildIntent(derived_record=dr, agent_intents=_AGENTS_MANY)
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        registered = [
            ef["path"] for ef in plan_dict["emitted_files"]
            if ef["path"].startswith("agents/acceptance/")
        ]
        typed_plan = validate_emission_plan(plan_dict, EP_CONTRACT)
        staging_dir = Path(tempfile.mkdtemp())
        emit_acceptance_contracts(typed_plan, staging_dir)
        written = sorted((staging_dir / "agents" / "acceptance").glob("phase_*_acceptance.md"))
        self.assertEqual(
            len(written), len(registered),
            f"on-disk count {len(written)} != registered count {len(registered)}",
        )


# ---------------------------------------------------------------------------
# F2(b): build_progress.md well-formedness guard
# ---------------------------------------------------------------------------

class BuildProgressWellFormedGuardTest(unittest.TestCase):
    """F2(b): build_progress.md is well-formed on a divergent fixture.

    Uses the 5-phase fixture. Any hardcoded 3-row assumption in the template fails.
    """

    @classmethod
    def setUpClass(cls):
        dr = _make_dr(_INCR_MANY_AGENTS_MANY_PHASES)
        bi = BuildIntent(derived_record=dr, agent_intents=_AGENTS_MANY)
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        typed_plan = validate_emission_plan(plan_dict, EP_CONTRACT)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        emit_scaffold(typed_plan, staging, REPO_ROOT)
        cls.content = (staging / "build_progress.md").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_state_vocabulary_present(self):
        """build_progress.md contains all five state vocabulary tokens."""
        for token in _STATE_VOCAB:
            self.assertIn(token, self.content,
                          f"state vocab token {token!r} missing from build_progress.md")

    def test_layer_b_verdicts_present(self):
        """build_progress.md contains all three Layer-B tri-state verdict tokens."""
        for token in _LAYER_B_VERDICTS:
            self.assertIn(token, self.content,
                          f"Layer-B verdict {token!r} missing from build_progress.md")

    def test_required_columns_present(self):
        """build_progress.md has all required columns."""
        for col in _REQUIRED_COLUMNS:
            self.assertIn(col, self.content,
                          f"required column {col!r} missing from build_progress.md")

    def test_five_phase_rows_present(self):
        """5-phase divergent fixture yields 5 table rows in build_progress.md."""
        rows = [ln for ln in self.content.splitlines() if ln.strip().startswith("|")]
        # Filter out separator rows (only dashes and pipes)
        data_rows = [r for r in rows if not re.match(r'^[\s|:\-]+$', r)]
        # Subtract the header row.
        self.assertGreaterEqual(
            len(data_rows), 5,
            f"expected at least 5 data rows (1 header + 5 phase rows), got {len(data_rows)}",
        )

    def test_no_unsubstituted_placeholders(self):
        """No {{KEY}} placeholders survive in build_progress.md."""
        leftover = re.findall(r'\{\{[A-Z_]+\}\}', self.content)
        self.assertEqual(leftover, [],
                         f"unsubstituted placeholders in build_progress.md: {leftover}")

    def test_five_phase_capabilities_in_ledger(self):
        """All 5 committed capabilities appear in the ledger on the divergent fixture."""
        for cap in ["Fetch raw data from source", "Validate and clean records",
                    "Enrich with metadata", "Generate analytics report",
                    "Distribute report to recipients"]:
            self.assertIn(cap, self.content,
                          f"capability {cap!r} missing from build_progress.md")


# ---------------------------------------------------------------------------
# F2(c): Supervised/copy-target + injected-dummy-Tier-1-demo instruction guard
# ---------------------------------------------------------------------------

class SupervisedCopyTargetSourceGuardTest(unittest.TestCase):
    """F2(c): Supervised/copy-target + injected-dummy-Tier-1-demo instruction present.

    15_close.md CLOSE-14 and wizard/skills/next-phase.md Step 5 are static source files
    (present for any project). Reads them directly — no per-phase emission needed.
    Also asserts universal presence covers any external-integration phase without
    requiring per-phase branching.
    """

    @classmethod
    def setUpClass(cls):
        cls.close14_path = REPO_ROOT / "wizard" / "interview" / "15_close.md"
        cls.next_phase_path = REPO_ROOT / "wizard" / "skills" / "next-phase.md"
        # The EMITTED home of the next-phase skill: the LATEST bundle's template.
        # Operators receive this copy (operator_fill_emitter sources skills from the
        # bundle templates/ tree, not from wizard/skills/). The drill fix must land
        # here too, or emitted/upgraded systems keep the un-grounded instruction.
        # Resolved dynamically from the registry (not a pinned version) so the byte-identity
        # guard below tracks whatever the newest cut is — the moment a future edit lands in
        # the dev-home skill without a re-cut, this test fails against the latest bundle.
        from upgrade import latest_bundle_version, load_registry  # noqa: E402
        _latest = latest_bundle_version(
            load_registry(REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json")
        )
        cls.bundle_next_phase_path = (
            REPO_ROOT / "wizard" / "foundation-bundles" / _latest
            / "templates" / "wizard" / "skills" / "next-phase.md"
        )
        cls.close14_text = cls.close14_path.read_text(encoding="utf-8")
        cls.next_phase_text = cls.next_phase_path.read_text(encoding="utf-8")
        cls.bundle_next_phase_text = cls.bundle_next_phase_path.read_text(encoding="utf-8")

    def test_close14_file_exists(self):
        """wizard/interview/15_close.md exists."""
        self.assertTrue(self.close14_path.exists(),
                        f"wizard/interview/15_close.md not found at {self.close14_path}")

    def test_next_phase_file_exists(self):
        """wizard/skills/next-phase.md exists."""
        self.assertTrue(self.next_phase_path.exists(),
                        f"wizard/skills/next-phase.md not found at {self.next_phase_path}")

    def test_close14_contains_supervised(self):
        """15_close.md CLOSE-14 contains 'supervised' instruction."""
        self.assertIn(
            "supervised", self.close14_text.lower(),
            "15_close.md must contain the supervised-run instruction",
        )

    def test_close14_contains_copy_target(self):
        """15_close.md CLOSE-14 contains copy/dummy target instruction."""
        lower = self.close14_text.lower()
        self.assertTrue(
            "copy" in lower or "dummy" in lower,
            "15_close.md must contain the copy/dummy-target instruction",
        )

    def test_close14_contains_drill(self):
        """15_close.md CLOSE-14 contains the drill/Tier-1-demo instruction."""
        lower = self.close14_text.lower()
        self.assertIn(
            "drill", lower,
            "15_close.md must contain the drill/Tier-1-demo instruction",
        )

    def test_next_phase_contains_supervised(self):
        """wizard/skills/next-phase.md Step 5 contains 'supervised' instruction."""
        self.assertIn(
            "supervised", self.next_phase_text.lower(),
            "next-phase.md must contain the supervised-run instruction",
        )

    def test_next_phase_contains_copy_target(self):
        """wizard/skills/next-phase.md Step 5 contains copy/dummy target instruction."""
        lower = self.next_phase_text.lower()
        self.assertTrue(
            "copy" in lower or "dummy" in lower,
            "next-phase.md must contain the copy/dummy-target instruction",
        )

    def test_next_phase_contains_drill(self):
        """wizard/skills/next-phase.md Step 5 contains the drill instruction."""
        self.assertIn(
            "drill", self.next_phase_text.lower(),
            "next-phase.md must contain the drill/Tier-1-demo instruction",
        )

    def test_supervised_instruction_is_universal_not_per_phase(self):
        """Supervised/copy-target instruction is universally present (not conditional on phase type).

        Both the build prompt (15_close.md) and the next-phase skill carry the instruction
        unconditionally. An external-integration phase does not require a separate branch —
        the instruction is already there for every phase.
        """
        # Assert the instruction is not inside an 'if external' or 'if integration' conditional
        # block (it's just present at top level in the prose). We verify by checking both
        # files carry the supervised keyword at the document level, not gated by a condition.
        self.assertIn("supervised", self.close14_text.lower())
        self.assertIn("supervised", self.next_phase_text.lower())

    # --- Drill example must be GROUNDED in the running phase's agents ---
    #
    # The drill previously illustrated the high-risk-action guardrail with an
    # un-grounded free-text placeholder + generic examples ("send this message" /
    # "update this live record"). On a research-only agent (reads + saves to the
    # operator's own files; no outbound/irreversible action) the agent improvised an
    # off-scope vivid action it never performs. The fix: ground the named action in
    # this phase's agents' actual declared actions, and for a no-irreversible-action
    # phase, say so and demonstrate the prompt hypothetically rather than inventing one.
    #
    # These assertions cover all three homes: the Phase-1 build prompt generator
    # (15_close.md), the Phase-2+ skill dev home (wizard/skills/next-phase.md), and the
    # EMITTED home (the latest bundle template that operators actually receive).

    def _assert_drill_grounded(self, text, where):
        lower = text.lower()
        # (a) Requires grounding the example in the phase's agents' actual actions.
        self.assertIn(
            "agent", lower,
            f"{where}: drill instruction must reference this phase's agents",
        )
        self.assertTrue(
            "configured to perform" in lower or "actually does" in lower
            or "declared actions" in lower,
            f"{where}: drill must require the named action be one the phase's agents "
            f"actually perform (grounding requirement missing)",
        )
        self.assertTrue(
            "do not invent" in lower or "not invent" in lower,
            f"{where}: drill must forbid inventing an action no agent in the phase performs",
        )
        self.assertTrue(
            "do not borrow an example" in lower or "another project" in lower,
            f"{where}: drill must forbid borrowing an example from another project/domain",
        )

    def _assert_drill_fallback(self, text, where):
        lower = text.lower()
        # (b) No-irreversible-action hypothetical fallback present.
        self.assertTrue(
            "low-risk" in lower or "low risk" in lower,
            f"{where}: drill must include the low-risk hypothetical fallback for a "
            f"phase whose agents take no irreversible/outbound action",
        )
        self.assertIn(
            "goes out in your name",
            lower,
            f"{where}: drill fallback must demonstrate the guardrail hypothetically "
            f"(\"goes out in your name or cannot be undone\")",
        )

    def _assert_no_generic_placeholder(self, text, where):
        lower = text.lower()
        # The un-grounded generic placeholder examples must be GONE as the only guidance.
        self.assertNotIn(
            "send this message", lower,
            f"{where}: the un-grounded generic placeholder example "
            f"('send this message') must be removed",
        )
        self.assertNotIn(
            "update this live record", lower,
            f"{where}: the un-grounded generic placeholder example "
            f"('update this live record') must be removed",
        )

    def test_close14_drill_grounded_in_phase_agents(self):
        """15_close.md drill requires grounding the example in Phase 1's agents' actions."""
        self._assert_drill_grounded(self.close14_text, "15_close.md")

    def test_close14_drill_has_no_irreversible_action_fallback(self):
        """15_close.md drill carries the no-irreversible-action hypothetical fallback."""
        self._assert_drill_fallback(self.close14_text, "15_close.md")

    def test_close14_drill_generic_placeholder_removed(self):
        """15_close.md no longer offers the un-grounded generic placeholder as guidance."""
        self._assert_no_generic_placeholder(self.close14_text, "15_close.md")

    def test_next_phase_drill_grounded_in_phase_agents(self):
        """next-phase.md (dev home) drill requires grounding in this phase's agents."""
        self._assert_drill_grounded(self.next_phase_text, "wizard/skills/next-phase.md")

    def test_next_phase_drill_has_no_irreversible_action_fallback(self):
        """next-phase.md (dev home) drill carries the no-irreversible-action fallback."""
        self._assert_drill_fallback(self.next_phase_text, "wizard/skills/next-phase.md")

    def test_next_phase_drill_generic_placeholder_removed(self):
        """next-phase.md (dev home) no longer offers the un-grounded generic placeholder."""
        self._assert_no_generic_placeholder(self.next_phase_text, "wizard/skills/next-phase.md")

    def test_bundle_next_phase_drill_grounded_in_phase_agents(self):
        """Emitted bundle next-phase.md drill requires grounding in this phase's agents."""
        self._assert_drill_grounded(self.bundle_next_phase_text,
                                    "latest-bundle templates/wizard/skills/next-phase.md")

    def test_bundle_next_phase_drill_has_no_irreversible_action_fallback(self):
        """Emitted bundle next-phase.md drill carries the no-irreversible-action fallback."""
        self._assert_drill_fallback(self.bundle_next_phase_text,
                                    "latest-bundle templates/wizard/skills/next-phase.md")

    def test_bundle_next_phase_drill_generic_placeholder_removed(self):
        """Emitted bundle next-phase.md no longer offers the un-grounded generic placeholder."""
        self._assert_no_generic_placeholder(self.bundle_next_phase_text,
                                            "latest-bundle templates/wizard/skills/next-phase.md")

    @unittest.expectedFailure
    def test_bundle_next_phase_matches_dev_home(self):
        """The emitted bundle next-phase.md is byte-identical to the dev home (single source
        of truth kept in sync by hand convention; no sync script exists).

        RE-SYNCED at the v0.10.0 bundle cut (B2-T9b) — see history: this guard was marked
        expectedFailure during B1-7/B2 for the identical reason it is marked again below, and
        was restored to a live assertion once that cut re-synced the bundle.

        RE-SYNCED AGAIN at the v0.14.0 bundle cut (Phase 3 Cut 1). D1-3 added the D-Layer-1
        deterministic self-QA wiring (the "Deterministic self-check" subsection naming
        capability_invariants.py) to the DEV-HOME wizard/skills/next-phase.md, and v0.13.1 —
        already-released and byte-immutable at the time — could not be edited to carry it, so
        this guard was marked expectedFailure until Cut 1 cut its own bundle. The v0.14.0 cut
        ported the current wizard/skills/next-phase.md into the bundle byte-for-byte, restoring
        dev-home == latest-bundle; the marker was removed accordingly.

        KNOWN PENDING DIVERGENCE AGAIN (Cut 1.1, Task A3, F-71). Task A3 added the "What this
        capability's own test should (and should not) cover" guidance section to the DEV-HOME
        wizard/skills/next-phase.md, steering a capability author away from writing an
        ambient-pause-state-dependent test and toward the new hermetic fixture
        (external_write.lifecycle_test_fixtures). v0.14.0 is an already-RELEASED,
        byte-immutable bundle -- it must never be edited to force this guard green (the same
        rule this test's own history already enforces above). So the dev home again
        intentionally LEADS the latest-bundle copy; byte-identity is re-established only when
        Cut 1.1's own bundle cut ships this next-phase.md edit (+ capability_invariants.py's
        third test-quality probe + lifecycle_test_fixtures.py) into a new bundle version. Marked
        expectedFailure, not deleted, for the same self-clearing reason the prior instances
        were: the moment a future cut restores dev-home == latest-bundle, unittest reports this
        as an UNEXPECTED SUCCESS and fails the suite, forcing the marker's removal. The dev-home
        content itself is unaffected by this bundle lag -- there is no bundle-independent
        wiring test for this specific prose section (unlike D1-3's Step 4 wiring, which
        NextPhaseSelfQAWiringTests reads from the canonical dev-home source directly), so this
        marker is the ONLY thing tracking the pending re-sync obligation for this change."""
        self.assertEqual(
            self.bundle_next_phase_text, self.next_phase_text,
            "bundle next-phase.md template diverged from wizard/skills/next-phase.md; "
            "the two homes must be kept byte-identical",
        )


# ---------------------------------------------------------------------------
# F2(d): No residual placeholders in emitted manual.md
# ---------------------------------------------------------------------------

class ResidualPlaceholderGuardTest(unittest.TestCase):
    """F2(d): Emitted manual.md contains no literal '(set at operator setup)' and no {{...}}.

    Extends the existing guard in test_scaffold_emitter.py (ManualMdContentTests) to run
    against the full assemble+emit pipeline with a divergent fixture and a real date
    supplied for MANUAL_LAST_UPDATED — locking the A1 fix that switched from the
    literal placeholder to a real date.
    """

    @classmethod
    def setUpClass(cls):
        from operator_system_emitter import emit_operator_system  # noqa
        dr = _make_dr(_INCR_MANY_AGENTS_MANY_PHASES)
        bi = BuildIntent(derived_record=dr, agent_intents=_AGENTS_MANY)
        plan_dict = assemble_emission_plan(bi, SP, CORPUS, model_tiers=SP.model_tiers)
        typed_plan = validate_emission_plan(plan_dict, EP_CONTRACT)
        cls._tmp = tempfile.TemporaryDirectory()
        staging = Path(cls._tmp.name)
        # Supply a real date so MANUAL_LAST_UPDATED resolves.
        emit_scaffold(typed_plan, staging, REPO_ROOT,
                      extra_inputs={"MANUAL_LAST_UPDATED": "2026-01-01"})
        manual_path = staging / "manual.md"
        cls.text = manual_path.read_text(encoding="utf-8") if manual_path.exists() else ""

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_manual_md_no_literal_set_at_operator_setup(self):
        """manual.md must not contain literal '(set at operator setup)'."""
        self.assertNotIn(
            "(set at operator setup)", self.text,
            "manual.md contains a residual '(set at operator setup)' placeholder",
        )

    def test_manual_md_no_unresolved_double_brace_placeholders(self):
        """manual.md must not contain unresolved {{KEY}} placeholders."""
        leftover = re.findall(r'\{\{[A-Z_]+\}\}', self.text)
        self.assertEqual(
            leftover, [],
            f"manual.md has unresolved {{{{KEY}}}} placeholders: {leftover}",
        )

    def test_manual_md_non_empty(self):
        """manual.md must be non-empty (emitted at all)."""
        self.assertTrue(
            self.text.strip(),
            "manual.md is empty or was not emitted",
        )


# ---------------------------------------------------------------------------
# F2(e): next-phase.md self-containment guard
# ---------------------------------------------------------------------------

class NextPhaseSkillSelfContainmentGuardTest(unittest.TestCase):
    """F2(e): The emitted next-phase.md skill is self-contained.

    Asserts it does NOT reference agent-wizard-build, AWB, or absolute build paths.
    Reads the source file directly (it is emitted verbatim via operator_fill).

    This guard may overlap with test_build_operate_emit.py::NextPhaseSkillEmitTests
    (test_next_phase_skill_no_awb_reference). If that test already covers it,
    this class adds value by also scanning for absolute build paths and running
    against the source file directly (not only the emitted copy).
    """

    @classmethod
    def setUpClass(cls):
        cls.source_path = REPO_ROOT / "wizard" / "skills" / "next-phase.md"
        cls.text = cls.source_path.read_text(encoding="utf-8")

    def test_source_does_not_reference_agent_wizard_build(self):
        """next-phase.md source must not reference 'agent-wizard-build'."""
        self.assertNotIn(
            "agent-wizard-build", self.text,
            "next-phase.md source references the build project (not self-contained)",
        )

    def test_source_does_not_reference_awb(self):
        """next-phase.md source must not reference 'AWB' abbreviation."""
        self.assertNotIn(
            "AWB", self.text,
            "next-phase.md source contains AWB build-project abbreviation",
        )

    def test_source_does_not_contain_absolute_build_paths(self):
        """next-phase.md source must not contain absolute paths starting with /Users/."""
        self.assertNotIn(
            "/Users/", self.text,
            "next-phase.md source contains an absolute build-machine path",
        )

    def test_source_does_not_contain_absolute_home_paths(self):
        """next-phase.md source must not contain absolute ~/Documents/ references."""
        self.assertNotIn(
            "Documents/agent-wizard", self.text,
            "next-phase.md source contains a Documents/agent-wizard path reference",
        )


if __name__ == "__main__":
    unittest.main()
