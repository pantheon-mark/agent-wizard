"""End-to-end emit tests for operator-facing output wiring (v0.7.0 registered bundle).

Full `generate_operator_system` emits from v0.7.0 — reads EMITTED files in a temp
staging dir rather than template files — verifying that the Tasks 5/6/9 template edits
and agent-emitter pointer wiring produce a correct emitted operator system.

Eight assertion groups (§1-§8 in the brief):
  §1 Global deliverable rule  — project_instructions.md has the routing section
  §2 Orchestrator safety-net  — orchestrator_prompt.md has the placement safety-net
  §3 Operator-facing agent    — pointer text + deliverables/ in permitted writes
  §4 Internal agent           — no pointer text, no deliverables/, no voice_and_style.md
  §5 voice_and_style.md       — no CONFIGURE sentinels; derived voice values present
  §6 design-outbound-message  — skill file emitted at wizard/skills/
  §7 deliverables/README.md   — emitted into the operator system
  §8 Split-brain invariants   — parametrized across ≥2 divergent rosters (anti-overfit)

Known wiring gap (§7, surfaced by this test suite): `deliverables/README.md` is
declared in system-artifacts.json (render_kind: copy) but `generate_operator_system`
does not emit it — the `deliverables/` subdirectory is absent from SCAFFOLD_SUBDIRS
and no other emitter copies it. The §7 test is written at full fidelity and is
expected to FAIL until a production fix adds `deliverables` to SCAFFOLD_SUBDIRS (or
adds a bespoke emitter step). It is intentionally NOT weakened.

Stdlib-only, pip-install-free. Runner: python3 -m unittest discover -s lib
"""

import copy
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from operator_system_emitter import generate_operator_system  # noqa: E402
from emission_plan import load_contract, default_contract_path, validate_emission_plan  # noqa: E402
from test_emission_plan import _valid_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# Voice-source fixture values for two divergent operator profiles.
_PROFILE_PLAIN = {
    "UP_TECHNICAL_LITERACY": "plain language only, no jargon",
    "NOTIFICATION_VERBOSITY": "Minimal",
    "QA_REPORTING_STYLE": "Summary",
}
_PROFILE_TECH = {
    "UP_TECHNICAL_LITERACY": "comfortable with technical terms",
    "NOTIFICATION_VERBOSITY": "Detailed",
    "QA_REPORTING_STYLE": "Live",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contract():
    return load_contract(default_contract_path())


def _base_plan_dict(voice_profile: Dict[str, str]) -> dict:
    """Build a v0.7.0 plan dict from the minimal valid plan + a voice profile."""
    d = copy.deepcopy(_valid_plan())
    d["bundle_version"] = "v0.7.0"
    d["foundation_doc_inputs"].update(voice_profile)
    return d


def _add_operator_facing_agent(plan_dict: dict) -> None:
    """Mutate the first (researcher) agent to operator_facing=True with deliverables/ write."""
    plan_dict["agents"][0]["operator_facing"] = True
    if "deliverables/" not in plan_dict["agents"][0]["permitted_write_directories"]:
        plan_dict["agents"][0]["permitted_write_directories"].append("deliverables/")


def _add_internal_agent(plan_dict: dict) -> None:
    """Append a second, internal (non-operator-facing) agent to the roster."""
    plan_dict["agents"].append({
        "id": "internal_processor",
        "role_description": "Processes intermediate data. Outputs are internal only.",
        "criticality_tier": "standard",
        "primary_model_tier": "standard",
        "status_model_tier": "fast",
        "operator_facing": False,
        "permitted_write_directories": [
            "work/agent_outputs", "agents/checkpoints", "agents/handoffs",
            "logs/error_log.md", "logs/session_log.md", "logs/audit_log.md",
            "work/issues_log.md",
        ],
        "additional_context_files": ["approach.md"],
        "step_completion_criteria": "step done",
        "task_completion_criteria": "task done",
        "output_format_specification": "markdown",
        "output_directory": "work/agent_outputs",
    })
    plan_dict["emitted_files"].append({
        "path": "agents/prompts/internal_processor.md",
        "managed_by": "wizard",
        "local_modifications": "not_recommended",
        "merge_strategy": "warn_on_drift",
        "source_refs": [],
    })


def _emit(plan_dict: dict) -> Path:
    """Validate plan_dict and emit into a fresh temp staging dir. Returns staging path."""
    contract = _contract()
    plan = validate_emission_plan(plan_dict, contract)
    tmp = tempfile.mkdtemp()
    staging = Path(tmp) / "system"
    generate_operator_system(plan, staging, REPO_ROOT, generator_version_override="0" * 40)
    return staging


def _permitted_writes_in_prompt(prompt_text: str) -> List[str]:
    """Extract the permitted-write entries from a prompt's permission-boundary section."""
    out: List[str] = []
    grabbing = False
    for ln in prompt_text.splitlines():
        if "Write to the following directories and files only" in ln:
            grabbing = True
            continue
        if grabbing:
            s = ln.strip()
            if s.startswith(("-", "*")):
                item = s.lstrip("-* ").strip()
                item = re.split(r"\s+[—-]\s+", item)[0].strip().strip("`")
                if item:
                    out.append(item)
            elif s == "":
                continue
            else:
                break
    return out


# ---------------------------------------------------------------------------
# §1 Global deliverable rule
# ---------------------------------------------------------------------------

class GlobalDeliverableRuleEmitTests(unittest.TestCase):
    """§1: emitted project_instructions.md carries the operator-facing deliverables rule."""

    @classmethod
    def setUpClass(cls):
        plan_dict = _base_plan_dict(_PROFILE_TECH)
        cls.staging = _emit(plan_dict)
        cls.pi = (cls.staging / "project_instructions.md").read_text(encoding="utf-8")

    def test_operator_facing_deliverables_section_present(self):
        self.assertIn(
            "## Operator-facing deliverables", self.pi,
            "emitted project_instructions.md missing '## Operator-facing deliverables' heading"
        )

    def test_deliverables_directory_named(self):
        self.assertIn(
            "deliverables/", self.pi,
            "emitted project_instructions.md missing 'deliverables/' directory reference"
        )

    def test_naming_pattern_present(self):
        # The rule must prescribe a naming pattern (e.g. <Type> — <subject> — <YYYY-MM-DD>.md)
        has_pattern = re.search(r"YYYY-MM-DD|<type>|<subject>|name\s+pattern|naming.pattern",
                                self.pi, re.I) is not None
        self.assertTrue(
            has_pattern,
            "emitted project_instructions.md does not prescribe a deliverable naming pattern"
        )


# ---------------------------------------------------------------------------
# §2 Orchestrator safety-net
# ---------------------------------------------------------------------------

class OrchestratorSafetyNetEmitTests(unittest.TestCase):
    """§2: emitted orchestrator_prompt.md carries the placement safety-net rule."""

    @classmethod
    def setUpClass(cls):
        plan_dict = _base_plan_dict(_PROFILE_PLAIN)
        cls.staging = _emit(plan_dict)
        cls.op = (cls.staging / "agents" / "prompts" / "orchestrator_prompt.md").read_text(
            encoding="utf-8")

    def test_safety_net_heading_present(self):
        has_heading = (
            "placement safety-net" in self.op.lower()
            or "## Operator deliverables — placement safety-net" in self.op
        )
        self.assertTrue(
            has_heading,
            "emitted orchestrator_prompt.md missing placement safety-net section"
        )

    def test_safety_net_references_deliverables(self):
        self.assertIn(
            "deliverables/", self.op,
            "emitted orchestrator_prompt.md safety-net missing 'deliverables/' reference"
        )

    def test_safety_net_references_work_agent_outputs(self):
        self.assertIn(
            "work/agent_outputs/", self.op,
            "emitted orchestrator_prompt.md safety-net missing 'work/agent_outputs/' reference"
        )

    def test_safety_net_relocate_rule_stated(self):
        # Must state the relocate/move rule
        has_relocate = re.search(r"reloca|move.*(deliverable|output)", self.op, re.I) is not None
        self.assertTrue(
            has_relocate,
            "emitted orchestrator_prompt.md safety-net does not state the relocation rule"
        )


# ---------------------------------------------------------------------------
# §3 Operator-facing agent prompt
# ---------------------------------------------------------------------------

class OperatorFacingAgentPromptTests(unittest.TestCase):
    """§3: the emitted prompt for an operator-facing agent carries the pointer text and
    includes deliverables/ in its permitted-write set."""

    @classmethod
    def setUpClass(cls):
        plan_dict = _base_plan_dict(_PROFILE_TECH)
        _add_operator_facing_agent(plan_dict)
        _add_internal_agent(plan_dict)
        cls.staging = _emit(plan_dict)
        cls.rp = (cls.staging / "agents" / "prompts" / "researcher_prompt.md").read_text(
            encoding="utf-8")
        cls.permitted = _permitted_writes_in_prompt(cls.rp)

    def test_operator_output_pointer_text_present(self):
        # The pointer text refers the agent to project_instructions.md and voice_and_style.md
        # for deliverable/voice rules.
        has_pointer = (
            "deliverable location" in self.rp
            or "deliverable" in self.rp.lower() and "voice_and_style.md" in self.rp
        )
        self.assertTrue(
            has_pointer,
            "emitted operator-facing agent prompt missing OPERATOR_OUTPUT_POINTER text"
        )

    def test_pointer_references_project_instructions(self):
        self.assertIn(
            "project_instructions.md", self.rp,
            "operator-facing agent pointer must reference project_instructions.md"
        )

    def test_pointer_references_voice_and_style(self):
        self.assertIn(
            "voice_and_style.md", self.rp,
            "operator-facing agent pointer must reference voice_and_style.md"
        )

    def test_deliverables_in_permitted_writes(self):
        has_deliverables = any("deliverables" in w for w in self.permitted)
        self.assertTrue(
            has_deliverables,
            f"operator-facing agent prompt must permit writes to deliverables/; "
            f"found permitted writes: {self.permitted}"
        )


# ---------------------------------------------------------------------------
# §4 Internal agent prompt
# ---------------------------------------------------------------------------

class InternalAgentPromptTests(unittest.TestCase):
    """§4: the emitted prompt for an internal agent has no pointer text, no deliverables/
    in permitted writes, and does not receive voice_and_style.md as additional context."""

    @classmethod
    def setUpClass(cls):
        plan_dict = _base_plan_dict(_PROFILE_TECH)
        _add_operator_facing_agent(plan_dict)
        _add_internal_agent(plan_dict)
        cls.staging = _emit(plan_dict)
        cls.ip = (cls.staging / "agents" / "prompts" / "internal_processor_prompt.md").read_text(
            encoding="utf-8")
        cls.permitted = _permitted_writes_in_prompt(cls.ip)

    def test_no_operator_output_pointer_text(self):
        has_pointer = (
            "deliverable location" in self.ip
            and "voice_and_style.md" in self.ip
            and "project_instructions.md" in self.ip
        )
        self.assertFalse(
            has_pointer,
            "internal agent prompt must NOT contain the OPERATOR_OUTPUT_POINTER routing text"
        )

    def test_deliverables_not_in_permitted_writes(self):
        has_deliverables = any("deliverables" in w for w in self.permitted)
        self.assertFalse(
            has_deliverables,
            f"internal agent prompt must NOT permit writes to deliverables/; "
            f"found permitted writes: {self.permitted}"
        )

    def test_voice_and_style_not_in_additional_context(self):
        # The additional_context_files section lists files by name; voice_and_style.md
        # must not appear there for an internal agent (it's not in its additional_context_files).
        # We check the section that begins "Additional context files:" or similar.
        m = re.search(r"Additional context files.*?\n((?:[^\n]*\n)*?)(?:\n##|\Z)",
                      self.ip, re.I | re.S)
        section = m.group(0) if m else self.ip
        self.assertNotIn(
            "voice_and_style.md", section,
            "internal agent additional context must NOT include voice_and_style.md"
        )


# ---------------------------------------------------------------------------
# §5 voice_and_style.md populated
# ---------------------------------------------------------------------------

class VoiceAndStyleEmitTests(unittest.TestCase):
    """§5: emitted docs/voice_and_style.md has no CONFIGURE sentinels, contains the new
    sections, and reflects the fixture's derived voice values."""

    _SENTINEL = "(operator-configures during setup)"

    @classmethod
    def setUpClass(cls):
        plan_dict = _base_plan_dict(_PROFILE_PLAIN)
        cls.staging = _emit(plan_dict)
        cls.vs = (cls.staging / "docs" / "voice_and_style.md").read_text(encoding="utf-8")

    def test_no_configure_sentinels(self):
        self.assertNotIn(
            self._SENTINEL, self.vs,
            "emitted voice_and_style.md must have NO '(operator-configures during setup)' sentinels"
        )

    def test_channel_appropriate_rendering_section_present(self):
        self.assertIn(
            "Channel-appropriate rendering", self.vs,
            "emitted voice_and_style.md missing 'Channel-appropriate rendering' section"
        )

    def test_information_architecture_section_present(self):
        self.assertIn(
            "Information architecture", self.vs,
            "emitted voice_and_style.md missing 'Information architecture' section"
        )

    def test_technical_level_reflects_plain_profile(self):
        # _PROFILE_PLAIN uses 'plain language only' -> TECHNICAL_LEVEL must be 'plain'
        self.assertIn(
            "plain", self.vs,
            "emitted voice_and_style.md TECHNICAL_LEVEL must reflect the 'plain' profile"
        )

    def test_technical_level_reflects_tech_profile(self):
        """Differential: 'comfortable with technical terms' -> TECHNICAL_LEVEL != plain."""
        plan_dict = _base_plan_dict(_PROFILE_TECH)
        tmp = tempfile.mkdtemp()
        staging = Path(tmp) / "system"
        contract = _contract()
        plan = validate_emission_plan(plan_dict, contract)
        generate_operator_system(plan, staging, REPO_ROOT, generator_version_override="0" * 40)
        vs_tech = (staging / "docs" / "voice_and_style.md").read_text(encoding="utf-8")
        # 'plain' profile should show "plain"; tech profile should show "technical" or "some-technical"
        self.assertNotIn(
            "plain", vs_tech.lower().split("technical level")[1][:100] if "technical level" in vs_tech.lower() else "",
            "emitted voice_and_style.md for tech profile must not show 'plain' TECHNICAL_LEVEL"
        )
        has_tech = "technical" in vs_tech
        self.assertTrue(
            has_tech,
            "emitted voice_and_style.md for 'comfortable with technical terms' profile must "
            "show a technical-level voice value"
        )


# ---------------------------------------------------------------------------
# §6 design-outbound-message skill delivered
# ---------------------------------------------------------------------------

class DesignOutboundSkillEmitTests(unittest.TestCase):
    """§6: wizard/skills/design-outbound-message.md is emitted into the operator system."""

    @classmethod
    def setUpClass(cls):
        plan_dict = _base_plan_dict(_PROFILE_PLAIN)
        cls.staging = _emit(plan_dict)

    def test_skill_file_emitted(self):
        skill_path = self.staging / "wizard" / "skills" / "design-outbound-message.md"
        self.assertTrue(
            skill_path.exists(),
            f"wizard/skills/design-outbound-message.md not emitted into operator system "
            f"(expected at {skill_path})"
        )

    def test_emitted_skill_references_voice_and_style(self):
        skill_path = self.staging / "wizard" / "skills" / "design-outbound-message.md"
        if not skill_path.exists():
            self.skipTest("skill not emitted (§6 dependency)")
        text = skill_path.read_text(encoding="utf-8")
        self.assertIn(
            "voice_and_style.md", text,
            "emitted design-outbound-message.md must reference voice_and_style.md"
        )

    def test_emitted_skill_states_email_trigger(self):
        skill_path = self.staging / "wizard" / "skills" / "design-outbound-message.md"
        if not skill_path.exists():
            self.skipTest("skill not emitted (§6 dependency)")
        text = skill_path.read_text(encoding="utf-8")
        self.assertIn(
            "email", text.lower(),
            "emitted design-outbound-message.md must state email as a trigger"
        )


# ---------------------------------------------------------------------------
# §7 deliverables/README.md delivered
# ---------------------------------------------------------------------------

class DeliverablesReadmeEmitTests(unittest.TestCase):
    """§7: deliverables/README.md is emitted into the operator system.

    KNOWN WIRING GAP: as of the time these tests were written, this assertion
    FAILS because `generate_operator_system` does not emit `deliverables/` — the
    directory is absent from scaffold_emitter.SCAFFOLD_SUBDIRS and no other
    emitter copies the render_kind:copy entry in system-artifacts.json at initial
    emit time. This test documents the gap at full fidelity rather than weakening
    the assertion.
    """

    @classmethod
    def setUpClass(cls):
        plan_dict = _base_plan_dict(_PROFILE_TECH)
        cls.staging = _emit(plan_dict)

    def test_deliverables_readme_emitted(self):
        readme_path = self.staging / "deliverables" / "README.md"
        self.assertTrue(
            readme_path.exists(),
            "deliverables/README.md not emitted into operator system — "
            "wiring gap: deliverables/ is in system-artifacts.json (render_kind:copy) "
            "but SCAFFOLD_SUBDIRS does not include 'deliverables' and no other emitter "
            "copies it at initial emit time"
        )

    def test_deliverables_readme_content(self):
        readme_path = self.staging / "deliverables" / "README.md"
        if not readme_path.exists():
            self.skipTest("deliverables/README.md not emitted (§7 known gap)")
        text = readme_path.read_text(encoding="utf-8")
        self.assertIn(
            "Deliverables", text,
            "emitted deliverables/README.md must contain a Deliverables heading"
        )


# ---------------------------------------------------------------------------
# §8 Split-brain invariants — parametrized across ≥2 divergent rosters
# ---------------------------------------------------------------------------

def _roster_a_plan() -> dict:
    """Roster A: one operator-facing agent (researcher), one internal agent.
    Higher-verbosity tech profile."""
    d = _base_plan_dict(_PROFILE_TECH)
    _add_operator_facing_agent(d)
    _add_internal_agent(d)
    return d


def _roster_b_plan() -> dict:
    """Roster B: two internal agents only (researcher stays internal), plain profile.
    Divergent from Roster A on: operator_facing flags, voice profile, agent count."""
    d = _base_plan_dict(_PROFILE_PLAIN)
    # researcher remains internal (default operator_facing=False)
    # Add second internal agent
    d["agents"].append({
        "id": "second_internal",
        "role_description": "Second internal agent — data enrichment only.",
        "criticality_tier": "standard",
        "primary_model_tier": "fast",
        "status_model_tier": "fast",
        "operator_facing": False,
        "permitted_write_directories": [
            "work/agent_outputs", "agents/checkpoints", "agents/handoffs",
            "logs/error_log.md", "logs/session_log.md",
        ],
        "additional_context_files": [],
        "step_completion_criteria": "done",
        "task_completion_criteria": "done",
        "output_format_specification": "markdown",
        "output_directory": "work/agent_outputs",
    })
    d["emitted_files"].append({
        "path": "agents/prompts/second_internal.md",
        "managed_by": "wizard",
        "local_modifications": "not_recommended",
        "merge_strategy": "warn_on_drift",
        "source_refs": [],
    })
    return d


def _agent_prompt_path(staging: Path, agent_id: str) -> Path:
    return staging / "agents" / "prompts" / f"{agent_id}_prompt.md"


class SplitBrainInvariantTests(unittest.TestCase):
    """§8: split-brain invariants, parametrized across two divergent rosters.

    Invariant 1: for EVERY emitted agent, deliverables/ in permitted-writes IFF operator_facing.
    Invariant 2: global rule (## Operator-facing deliverables) always present in project_instructions.md.
    Invariant 3: orchestrator safety-net always present in orchestrator_prompt.md.
    Invariant 4: emitted docs/voice_and_style.md never contains the CONFIGURE sentinel.

    These are input-independent (hold for every conformant roster), so parametrizing
    across two divergent rosters (different agent counts, operator_facing mixes, voice
    profiles) is the anti-overfit gate.
    """

    _SENTINEL = "(operator-configures during setup)"

    @classmethod
    def setUpClass(cls):
        cls.rosters = {
            "roster_a": {
                "plan_dict": _roster_a_plan(),
                "agents_with_facing": {"researcher"},  # operator_facing=True
                "agents_without_facing": {"internal_processor"},  # operator_facing=False
            },
            "roster_b": {
                "plan_dict": _roster_b_plan(),
                "agents_with_facing": set(),  # no operator-facing agents
                "agents_without_facing": {"researcher", "second_internal"},
            },
        }
        cls.stagings: Dict[str, Path] = {}
        for name, r in cls.rosters.items():
            cls.stagings[name] = _emit(r["plan_dict"])

    def _check_invariant_deliverables_iff_operator_facing(self, roster_name: str):
        staging = self.stagings[roster_name]
        r = self.rosters[roster_name]
        errors: List[str] = []

        for agent_id in r["agents_with_facing"]:
            prompt = _agent_prompt_path(staging, agent_id)
            if not prompt.exists():
                errors.append(f"operator-facing agent '{agent_id}' prompt not emitted")
                continue
            permitted = _permitted_writes_in_prompt(prompt.read_text(encoding="utf-8"))
            if not any("deliverables" in w for w in permitted):
                errors.append(
                    f"operator-facing agent '{agent_id}' does not have deliverables/ "
                    f"in permitted writes (got: {permitted})"
                )

        for agent_id in r["agents_without_facing"]:
            prompt = _agent_prompt_path(staging, agent_id)
            if not prompt.exists():
                errors.append(f"internal agent '{agent_id}' prompt not emitted")
                continue
            permitted = _permitted_writes_in_prompt(prompt.read_text(encoding="utf-8"))
            if any("deliverables" in w for w in permitted):
                errors.append(
                    f"internal agent '{agent_id}' has deliverables/ in permitted writes "
                    f"(must not): {permitted}"
                )

        self.assertEqual(
            errors, [],
            f"{roster_name}: deliverables/ in permitted-writes IFF operator_facing invariant "
            f"violated: {errors}"
        )

    def test_invariant_deliverables_iff_operator_facing_roster_a(self):
        self._check_invariant_deliverables_iff_operator_facing("roster_a")

    def test_invariant_deliverables_iff_operator_facing_roster_b(self):
        self._check_invariant_deliverables_iff_operator_facing("roster_b")

    def _check_invariant_global_rule_always_present(self, roster_name: str):
        staging = self.stagings[roster_name]
        pi = (staging / "project_instructions.md").read_text(encoding="utf-8")
        self.assertIn(
            "## Operator-facing deliverables", pi,
            f"{roster_name}: global deliverable rule missing from emitted project_instructions.md"
        )

    def test_invariant_global_rule_present_roster_a(self):
        self._check_invariant_global_rule_always_present("roster_a")

    def test_invariant_global_rule_present_roster_b(self):
        self._check_invariant_global_rule_always_present("roster_b")

    def _check_invariant_orchestrator_safety_net_always_present(self, roster_name: str):
        staging = self.stagings[roster_name]
        op = (staging / "agents" / "prompts" / "orchestrator_prompt.md").read_text(
            encoding="utf-8")
        has_safety_net = (
            "placement safety-net" in op.lower()
            or "Operator deliverables" in op
        )
        self.assertTrue(
            has_safety_net,
            f"{roster_name}: orchestrator safety-net missing from emitted orchestrator_prompt.md"
        )

    def test_invariant_orchestrator_safety_net_present_roster_a(self):
        self._check_invariant_orchestrator_safety_net_always_present("roster_a")

    def test_invariant_orchestrator_safety_net_present_roster_b(self):
        self._check_invariant_orchestrator_safety_net_always_present("roster_b")

    def _check_invariant_voice_doc_no_sentinel(self, roster_name: str):
        staging = self.stagings[roster_name]
        vs = (staging / "docs" / "voice_and_style.md").read_text(encoding="utf-8")
        self.assertNotIn(
            self._SENTINEL, vs,
            f"{roster_name}: emitted voice_and_style.md still contains CONFIGURE sentinel "
            f"(voice derivation not wired)"
        )

    def test_invariant_voice_doc_no_sentinel_roster_a(self):
        self._check_invariant_voice_doc_no_sentinel("roster_a")

    def test_invariant_voice_doc_no_sentinel_roster_b(self):
        self._check_invariant_voice_doc_no_sentinel("roster_b")


if __name__ == "__main__":
    unittest.main()
