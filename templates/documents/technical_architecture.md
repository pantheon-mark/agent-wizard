# Technical Architecture

## Orchestration Model
{{ORCHESTRATION_MODEL}}

## Agent Roster

| Agent | Function | Criticality |
|-------|----------|-------------|
{{AGENT_ROSTER_ROWS}}

## Permission Boundaries

### Autonomously, without asking
{{AUTONOMOUS_ACTIONS}}

### Always asks first
{{ASKS_FIRST_ACTIONS}}

## Task Completion Checklists
{{TASK_COMPLETION_CHECKLISTS}}

## Integrations

*Populated from the credentials and integrations phase. Each entry corresponds to a credential in `/security/credentials_registry.md`.*

{{INTEGRATIONS}}

## Scale Tier

**Provisional tier:** {{SCALE_TIER}}
**Rationale:** {{SCALE_TIER_RATIONALE}}
**Basis:** {{SCALE_TIER_BASIS}}
**Status:** Provisional — set during wizard setup. Will be reviewed after first production run and checked weekly from that point. Requires explicit user confirmation to change.
