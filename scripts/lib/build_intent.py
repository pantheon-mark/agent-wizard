"""Build-intent seam — the durable interview-semantics layer (stdlib-only).

A BuildIntent is what the interview produces: a derived record (the structured
result of deriving an operator's foundation-doc fields from their answers) plus a
list of agent intents. It is the stable layer the system generator assembles a
runnable system FROM — interview semantics live here; the generator's plan is a
mechanical projection of it.

An AgentIntent is the NARROW, operator-meaning part of an agent: what it is for,
how you know it succeeded, what it needs (resource claims), and how confident the
derivation is. It deliberately does NOT carry filesystem paths, model selection,
cron cadence, or permissions — those are decided deterministically by the
assembler from the system shape's policy, not invented per agent. Keeping the
intent narrow is what prevents an agent from claiming false runnable specificity.

ConstraintViolation is the fail-loud carrier: when an intent cannot be mapped onto
the shape (an unsupported nuance, or a resource a shape forbids), the assembler
surfaces a ConstraintViolation with operator options rather than silently mapping
to a generic default.

Stdlib-only, pip-install-free.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


# The shape's criticality vocabulary (matches the emission-plan criticality_tier enum).
CRITICALITY_TIERS = ("critical", "standard", "supporting")


class ConstraintViolation(Exception):
    """Fail-loud: an intent could not be mapped onto the system shape.

    Carries enough for the caller to surface a real choice to the operator
    (drop the capability / change the shape) rather than silently defaulting.
    `kind` distinguishes the failure class (e.g. resource_claim_forbidden,
    resource_claim_unmapped, duplicate_agent_id, critical_agent_insufficient,
    unknown_criticality, uncovered_path).
    """

    def __init__(self, kind: str, subject: str, detail: str, operator_options: List[str]):
        self.kind = kind
        self.subject = subject
        self.detail = detail
        self.operator_options = list(operator_options)
        super().__init__(
            f"{kind} on {subject!r}: {detail} "
            f"(operator options: {', '.join(self.operator_options) or 'none'})"
        )


@dataclass(frozen=True)
class ResourceClaims:
    """What an agent claims it NEEDS. Each claim must map to a deterministic
    generation effect in the shape's policy; an unmapped or forbidden claim is
    rejected by the assembler, never silently dropped."""
    requires_cron: bool = False
    requires_external_network: bool = False
    requires_broad_fs_read: bool = False

    def claimed(self) -> List[str]:
        """The names of the claims set to True (deterministic order)."""
        out: List[str] = []
        if self.requires_cron:
            out.append("requires_cron")
        if self.requires_external_network:
            out.append("requires_external_network")
        if self.requires_broad_fs_read:
            out.append("requires_broad_fs_read")
        return out


@dataclass(frozen=True)
class AgentIntent:
    """The narrow, Claude-derived meaning of one agent. No filesystem/model/cron
    fields — those are the assembler's job (deterministic, from shape policy)."""
    display_name: str
    function_summary: str
    role_intent: str
    acceptance_signals: List[str]
    output_purpose: str
    criticality_tier: str
    resource_claims: ResourceClaims
    confidence: str
    insufficiency_flags: List[str]
    source_spans: List[str]
    operator_facing: bool = False


@dataclass(frozen=True)
class BuildIntent:
    """The durable seam: a derived record + the agent intents. The generator's
    EmissionPlan is assembled mechanically from this; interview semantics stay here."""
    derived_record: Dict[str, Any]
    agent_intents: List[AgentIntent] = field(default_factory=list)


def validate_build_intent(intent: BuildIntent) -> None:
    """Validate the INTENT layer (fail-closed). Deep derived-record envelope
    validation is `derived_record.validate_derived_record`'s job — done by the
    assembler before projection; here we check only the intent-layer invariants."""
    rec = intent.derived_record
    if not isinstance(rec, dict) or not isinstance(rec.get("_audit"), dict):
        raise ConstraintViolation(
            kind="malformed_derived_record", subject="<build-intent>",
            detail="derived_record must be an object carrying an `_audit` map",
            operator_options=["re-run the interview derivation"],
        )
    for ai in intent.agent_intents:
        if not (isinstance(ai.display_name, str) and ai.display_name.strip()):
            raise ConstraintViolation(
                kind="empty_agent_name", subject="<agent-intent>",
                detail="agent display_name must be a non-empty string",
                operator_options=["name the agent"],
            )
        if ai.criticality_tier not in CRITICALITY_TIERS:
            raise ConstraintViolation(
                kind="unknown_criticality", subject=ai.display_name,
                detail=f"criticality_tier {ai.criticality_tier!r} is not one of {CRITICALITY_TIERS}",
                operator_options=[f"set one of {CRITICALITY_TIERS}"],
            )
