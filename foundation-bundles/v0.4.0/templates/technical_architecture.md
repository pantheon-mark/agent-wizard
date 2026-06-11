---
foundation_doc_type: technical_architecture
foundation_schema_version: v0.3
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

*Agent Architecture Detail — see [`approach.md` § Agent Roster](approach.md#agent-roster) for the canonical roster (agent / function / criticality). Below: per-agent architectural detail that extends the roster — state management, prompt template structure, decision logic, communication patterns. These details derive from the `technical_architecture.md` audience perspective and are NOT duplicated in `approach.md`.*

*Population status: **deferred**. Per-agent architectural detail is not captured at v0.4.0; this section will be populated when (a) the wizard interview iteration that captures per-agent architectural detail lands, OR (b) the first foundation-bundle emission slice that operationalizes architecture-detail derivation lands — whichever comes first.*

## Permission Boundary Architecture

*Permission Boundary Architecture — see [`execution_plan.md` § Human-in-the-Loop Map](execution_plan.md#human-in-the-loop-map) for the operator-facing projection (autonomy level, action categories, behaviors). Below: architectural extension of that boundary — enforcement point, override path, irrevocability classes, audit trail, Tier 1 baseline rationale. These details derive from the `technical_architecture.md` audience perspective and are NOT duplicated in `execution_plan.md`.*

*Population status: **deferred**. Architectural extension of the authority boundary is not captured at v0.4.0; this section will be populated when (a) the wizard interview iteration that captures boundary-architecture detail lands, OR (b) the first foundation-bundle emission slice that operationalizes boundary-architecture derivation lands — whichever comes first.*

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
