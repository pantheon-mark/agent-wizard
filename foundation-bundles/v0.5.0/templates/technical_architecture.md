---
foundation_doc_type: technical_architecture
foundation_schema_version: v0.4
wizard_version_compatible: "{{WIZARD_VERSION}}"
managed_by: wizard
system_shape: "{{SYSTEM_SHAPE}}"
foundation_only_mode: "{{FOUNDATION_ONLY_MODE}}"
---

# Technical Architecture

## Orchestration Model

*This system uses one logical coordinator — the Orchestrator — as its control plane: it owns the work queue, decides what runs next, routes work to specialist agents, and tracks session state. Specialist agents form the data plane that does the domain-specific work. The Orchestrator runs inside a Claude Code session (your control surface for the system); specialist agents are invoked as separate runs. You interact with the work queue and the Orchestrator, not with individual specialist agents directly.*

{{ORCHESTRATION_MODEL}}

## Agent Architecture Detail

*The canonical agent roster — each agent, what it does, and how critical it is — lives in [`approach.md` § Agent Roster](approach.md#agent-roster). This section is reserved for deeper per-agent architectural detail (internal state, prompt structure, decision logic, how agents pass work to each other).*

*Your system does not use this section. For the way your system runs today (markdown agents on Claude Code), the roster in `approach.md` and each agent's own prompt file (`agents/prompts/<agent>_prompt.md`) hold everything the agents and the build process need — there is nothing to add here, and nothing here is missing. Leave this section as is.*

## Permission Boundary Architecture

*What your system does on its own versus what it asks you about first — the autonomy level, the action categories, and the approval behaviors — is set out in [`execution_plan.md` § Human-in-the-Loop Map](execution_plan.md#human-in-the-loop-map). This section is reserved for deeper architectural detail behind that boundary (where it is enforced, the override path, which actions are irreversible, the audit trail).*

*Your system does not use this section. For the way your system runs today, the Human-in-the-Loop Map in `execution_plan.md` and each agent's permission boundary (in its prompt file) hold everything that governs what the agents may do — there is nothing to add here, and nothing here is missing. Leave this section as is.*

## Task Completion Checklists
{{TASK_COMPLETION_CHECKLISTS}}

## Integrations

*Every external dependency this system relies on. The ones that need a login or key are also listed in `/security/credentials_registry.md`; the rest — read-only sources and outbound alerts — do not require a credential.*

{{INTEGRATIONS}}

## Scale Tier

**Provisional tier:** {{SCALE_TIER}}
**Rationale:** {{SCALE_TIER_RATIONALE}}
**Basis:** {{SCALE_TIER_BASIS}}
**Status:** Provisional — set during wizard setup. Will be reviewed after first production run and checked weekly from that point. Requires explicit user confirmation to change.

## Regulatory & compliance considerations

*How this system handles personal, financial, and any regulated information, and where the limits are. Reflects the dependencies and data the system was set up to work with. If nothing of note was identified, this reads as "no regulatory exposure identified."*

{{COMPLIANCE_GAPS_CONTENT}}
