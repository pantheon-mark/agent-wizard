"""Pure assembler: derives a per-phase acceptance contract from CAPABILITY_INCREMENTS
and agent records.

A PhaseAcceptanceContract is the plain-language checklist the operator is asked at
acceptance time for each committed phase. One contract is produced per committed phase
(mvp + post_mvp_roadmap buckets), ascending by phase number.
candidate_conditional increments carry no phase and are excluded entirely.

Inputs:
  capability_increments — list of dicts matching the CAPABILITY_INCREMENTS schema
                          (keys: capability, release_bucket, phase, agents, depends_on, …)
  agent_records         — list of dicts carrying per-agent identity + acceptance_signals
                          (identity key is 'display_name' or 'id'; signals in
                          'acceptance_signals' as a list of strings)

Pure function: no file I/O, no emission, no hardcoded project or agent names.
Stdlib-only, pip-install-free.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# Committed release buckets (candidate_conditional is excluded).
_COMMITTED_BUCKETS = frozenset({"mvp", "post_mvp_roadmap"})


@dataclass
class PhaseAcceptanceContract:
    """Plain-language acceptance checklist for one committed phase."""
    phase: int
    capability: str
    agents: List[str]
    operator_questions: List[str]
    required_evidence: List[str]
    core_checks: List[str]
    defer_trigger: Optional[str]


def _agent_name(record: dict) -> str:
    """Return the canonical identifier string for an agent record dict.
    Prefers 'display_name'; falls back to 'id'."""
    return str(record.get("display_name") or record.get("id") or "").strip()


def _build_agent_index(agent_records: list) -> Dict[str, List[str]]:
    """Build a name -> acceptance_signals map from agent_records."""
    index: Dict[str, List[str]] = {}
    for rec in agent_records:
        name = _agent_name(rec)
        if name:
            signals = [str(s) for s in rec.get("acceptance_signals", []) if str(s).strip()]
            index[name] = signals
    return index


def _parse_agents_string(agents_value) -> List[str]:
    """Parse the 'agents' field of a capability increment into a list of names.
    The field may be a comma-separated string or a list."""
    if not agents_value:
        return []
    if isinstance(agents_value, list):
        return [str(a).strip() for a in agents_value if str(a).strip()]
    # Comma-separated string.
    return [a.strip() for a in str(agents_value).split(",") if a.strip()]


def _compose_operator_questions(
    capability: str,
    agent_names: List[str],
    core_checks: List[str],
) -> List[str]:
    """Compose plain-language yes/no-ish questions the operator can judge.

    Rules:
    - Always include one "did it do <capability> on your real work?" question.
    - For a multi-agent phase, include one question about the combined/handoff result.
    - Plain voice; no internal field names or jargon tokens.
    """
    questions: List[str] = []

    # Primary real-work question.
    questions.append(
        f"Did the system successfully complete '{capability}' on your real work — "
        f"did you get the result you expected?"
    )

    # For a multi-agent phase, add a combined/handoff question.
    if len(agent_names) > 1:
        agents_str = " and ".join(agent_names)
        questions.append(
            f"Did {agents_str} work together correctly — did the handoff between them "
            f"produce a complete, usable final result?"
        )

    # Add one question per core check if there are any (plain-language version of each signal).
    for check in core_checks:
        # Only add if the check is not already covered by the primary question wording.
        questions.append(f"Did the output show: {check}?")

    return questions


def _compose_required_evidence(
    capability: str,
    agent_names: List[str],
    core_checks: List[str],
) -> List[str]:
    """Generic/derived list of what the operator needs to see to judge the phase."""
    evidence: List[str] = []

    # The outputs the phase produced.
    evidence.append(
        f"The output produced for '{capability}' — open it and check it looks right."
    )

    # What the system held back (if any approval step exists).
    evidence.append(
        "Any items the system flagged for your approval before proceeding."
    )

    # Confirmation that each agent completed its step.
    if agent_names:
        for agent in agent_names:
            evidence.append(f"Confirmation that {agent} completed its step without errors.")

    return evidence


def _compose_defer_trigger(
    capability: str,
    agent_names: List[str],
    agent_index: Dict[str, List[str]],
) -> Optional[str]:
    """Return a generic defer condition if the phase cannot yet be exercised on real work.

    A phase is considered un-exercisable if none of its assigned agents has a matching
    record in agent_index (i.e. the agent is not yet configured). In that case we set
    a descriptive trigger; otherwise None.
    """
    if not agent_names:
        # No agents assigned — cannot exercise this phase at all.
        return f"No agents are assigned to '{capability}' yet; exercise this phase after the agents are configured."

    # Check if at least one assigned agent is present in the index.
    matched = [a for a in agent_names if a in agent_index]
    if not matched:
        return (
            f"The agent(s) for '{capability}' ({', '.join(agent_names)}) "
            f"are not yet configured; exercise this phase once they are set up."
        )

    return None


def assemble_phase_acceptance(
    capability_increments: list,
    agent_records: list,
) -> List[PhaseAcceptanceContract]:
    """Derive a per-phase acceptance contract for every committed phase.

    Returns one PhaseAcceptanceContract per committed phase (mvp + post_mvp_roadmap),
    sorted ascending by phase number. candidate_conditional increments are excluded.

    Args:
        capability_increments: list of dicts (CAPABILITY_INCREMENTS schema).
        agent_records: list of dicts carrying 'display_name' or 'id' and
                       'acceptance_signals' (list of strings).

    Returns:
        list[PhaseAcceptanceContract] sorted ascending by phase.
    """
    agent_index = _build_agent_index(agent_records)

    # Collect committed increments and group by phase.
    phase_groups: Dict[int, List[dict]] = {}
    for inc in capability_increments:
        bucket = inc.get("release_bucket", "")
        if bucket not in _COMMITTED_BUCKETS:
            continue
        phase = inc.get("phase")
        if not isinstance(phase, int) or isinstance(phase, bool):
            continue
        if phase not in phase_groups:
            phase_groups[phase] = []
        phase_groups[phase].append(inc)

    contracts: List[PhaseAcceptanceContract] = []

    for phase in sorted(phase_groups.keys()):
        increments_for_phase = phase_groups[phase]

        # Capability: join all capabilities for this phase (handles multi-increment phases).
        capabilities = [
            inc["capability"].strip()
            for inc in increments_for_phase
            if isinstance(inc.get("capability"), str) and inc["capability"].strip()
        ]
        capability_str = "; ".join(capabilities) if capabilities else f"Phase {phase}"

        # Agents: collect all unique agent names across increments for this phase.
        agent_names: List[str] = []
        seen_agents = set()
        for inc in increments_for_phase:
            for name in _parse_agents_string(inc.get("agents")):
                if name and name not in seen_agents:
                    agent_names.append(name)
                    seen_agents.add(name)

        # core_checks: aggregate acceptance_signals from all matched agents.
        core_checks: List[str] = []
        seen_checks: set = set()
        for name in agent_names:
            for signal in agent_index.get(name, []):
                if signal not in seen_checks:
                    core_checks.append(signal)
                    seen_checks.add(signal)

        # defer_trigger.
        defer_trigger = _compose_defer_trigger(capability_str, agent_names, agent_index)

        # operator_questions.
        operator_questions = _compose_operator_questions(
            capability_str, agent_names, core_checks
        )

        # required_evidence.
        required_evidence = _compose_required_evidence(
            capability_str, agent_names, core_checks
        )

        contracts.append(PhaseAcceptanceContract(
            phase=phase,
            capability=capability_str,
            agents=agent_names,
            operator_questions=operator_questions,
            required_evidence=required_evidence,
            core_checks=core_checks,
            defer_trigger=defer_trigger,
        ))

    return contracts
