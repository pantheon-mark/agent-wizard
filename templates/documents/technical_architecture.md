---
foundation_doc_type: technical_architecture
foundation_schema_version: v0.1
wizard_version_compatible: "{{WIZARD_VERSION}}"
managed_by: wizard
system_shape: "{{SYSTEM_SHAPE}}"
foundation_only_mode: "{{FOUNDATION_ONLY_MODE}}"
---

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

## Regulatory & compliance gaps (foundation-only mode)

*Populated when DOCUMENT-path stop conditions are documented during the shape-detection reevaluate loop. This section renders in `foundation_only` mode only (schema `render_modes: [foundation_only]`); in `complete` render mode it does not appear. If no compliance gaps were documented during the loop, the wizard may omit this section or emit "No compliance gaps documented during shape-detection."*

{{COMPLIANCE_GAPS_CONTENT}}
