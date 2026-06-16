"""Deterministic AgentIntent -> agent-record assembler (stdlib-only).

Turns each narrow AgentIntent (the operator-meaning of an agent) into a complete
agent record (the 11 fields the emission plan requires, plus optional cron cadence).
The DETERMINISTIC code owns everything an agent must NOT be free to invent — its id,
write directories, output directory, model tiers, cron cadence — sourcing them from
the system shape's scaffold policy. The intent supplies only meaning (role, what
counts as done) and resource CLAIMS.

Resource-claim policy is fail-loud, never silent-default:
  - a claim the shape does not permit (not in allowed_resource_claims) is REJECTED;
  - a claim the shape allows but that maps to no deterministic generation effect
    (not in CLAIM_EFFECTS) is REJECTED. allowed_resource_claims MUST be a subset of
    CLAIM_EFFECTS — that invariant is what prevents an allowed claim from silently
    vanishing during assembly (the failure class this layer exists to close).

Stdlib-only, pip-install-free.
"""

import re
from typing import Any, Dict, List

from build_intent import AgentIntent, ConstraintViolation  # type: ignore
from scaffold_plan import ScaffoldPlan  # type: ignore


# Each allowed resource claim must map to a deterministic generation effect here.
# A claim allowed by a shape but absent from this map is rejected (resource_claim_unmapped).
CLAIM_EFFECTS = {
    "requires_cron": "agent_cron_cadence",
}

# Slugs the emitter reserves for the control plane: every emitted system writes an
# Orchestrator (agents/prompts/orchestrator_prompt.md) and a QA agent, and the roster
# hardcodes both rows. A specialist whose slug equals one of these would OVERWRITE the
# control-plane orchestrator prompt ('orchestrator') or duplicate the built-in QA roster
# row ('qa') — so a specialist resolving to a reserved id is rejected fail-loud here,
# before any emit. (The markdown-CC control plane; per-shape — other shapes realize the
# control plane differently and would declare their own reserved set.)
RESERVED_AGENT_IDS = {"orchestrator", "qa"}


def _slug(name: str) -> str:
    """Deterministic id from a display name: lowercase, non-alnum -> '-', trimmed."""
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower())
    return re.sub(r"-{2,}", "-", s).strip("-")


def assemble_agent_records(intents: List[AgentIntent], scaffold_plan: ScaffoldPlan) -> List[Dict[str, Any]]:
    """Project agent intents into validated agent-record dicts (deterministic; sorted by id).

    Raises ConstraintViolation (fail-loud) on: a critical agent with unresolved
    insufficiency; a forbidden or unmapped resource claim; an empty/duplicate id;
    an unknown criticality tier. Code never invents fs/model/cron values.
    """
    profile = scaffold_plan.agent_output_profile
    policy = scaffold_plan.criticality_model_policy
    allowed = set(scaffold_plan.allowed_resource_claims)
    default_cadence = scaffold_plan.orchestrator.get("schedule") or "0 * * * *"

    records: List[Dict[str, Any]] = []
    seen_ids = set()
    for ai in intents:
        # A critical agent cannot be safely assembled with known gaps (confirmation UX is a later phase).
        if ai.criticality_tier == "critical" and ai.insufficiency_flags:
            raise ConstraintViolation(
                kind="critical_agent_insufficient", subject=ai.display_name,
                detail=f"critical agent has unresolved insufficiency flags {ai.insufficiency_flags}",
                operator_options=["resolve the missing details", "lower the criticality tier"],
            )
        if ai.criticality_tier not in policy:
            raise ConstraintViolation(
                kind="unknown_criticality", subject=ai.display_name,
                detail=f"criticality_tier {ai.criticality_tier!r} has no model policy in this shape",
                operator_options=[f"set one of {sorted(policy)}"],
            )

        # Resource-claim policy: forbidden (not allowed) OR allowed-but-unmapped -> fail loud.
        for claim in ai.resource_claims.claimed():
            if claim not in allowed:
                raise ConstraintViolation(
                    kind="resource_claim_forbidden", subject=ai.display_name,
                    detail=f"{claim} is not a recorded resource claim for the "
                           f"{scaffold_plan.system_shape} shape — this shape does not provision "
                           f"or gate it (recorded claims: {sorted(allowed)})",
                    operator_options=[f"do not record {claim} for this shape",
                                      "use a shape that provisions this resource"],
                )
            if claim not in CLAIM_EFFECTS:
                raise ConstraintViolation(
                    kind="resource_claim_unmapped", subject=ai.display_name,
                    detail=f"{claim} is allowed by the shape but has no deterministic generation effect",
                    operator_options=["map the claim to an effect before allowing it", f"drop {claim}"],
                )

        agent_id = _slug(ai.display_name)
        if not agent_id:
            raise ConstraintViolation(
                kind="empty_agent_id", subject=ai.display_name,
                detail="display_name did not produce a non-empty id",
                operator_options=["give the agent an alphanumeric name"],
            )
        if agent_id in RESERVED_AGENT_IDS:
            raise ConstraintViolation(
                kind="reserved_agent_id", subject=ai.display_name,
                detail=f"agent id {agent_id!r} is reserved for the control plane — the "
                       f"{scaffold_plan.system_shape} shape always emits an Orchestrator and a "
                       f"QA agent, so a specialist with this id would overwrite the control-plane "
                       f"prompt or duplicate the built-in roster row",
                operator_options=[f"rename the agent so it does not resolve to one of "
                                  f"{sorted(RESERVED_AGENT_IDS)}"],
            )
        if agent_id in seen_ids:
            raise ConstraintViolation(
                kind="duplicate_agent_id", subject=ai.display_name,
                detail=f"two agents resolve to the same id {agent_id!r}",
                operator_options=["rename one of the agents so the ids differ"],
            )
        seen_ids.add(agent_id)

        tiers = policy[ai.criticality_tier]
        signals = "; ".join(s for s in ai.acceptance_signals if str(s).strip()) \
            or "the task's stated acceptance signals are met"
        rec: Dict[str, Any] = {
            "id": agent_id,
            "role_description": ai.role_intent,
            "criticality_tier": ai.criticality_tier,
            "primary_model_tier": tiers["primary_model_tier"],
            "status_model_tier": tiers["status_model_tier"],
            "permitted_write_directories": list(profile["permitted_write_directories"]),
            "additional_context_files": list(profile["additional_context_files"]),
            "step_completion_criteria": f"Each step is complete when: {signals}.",
            "task_completion_criteria": f"The task is complete when: {signals}.",
            "output_format_specification": profile["output_format_specification"],
            "output_directory": profile["output_directory"],
        }
        # Claim effect (requires_cron -> populate the cron_cadence plan field; carried + validated.
        # Wiring per-agent cadence into the emitted cron config is a later-phase item).
        if ai.resource_claims.requires_cron:
            rec["cron_cadence"] = default_cadence
        records.append(rec)

    records.sort(key=lambda r: r["id"])
    return records
