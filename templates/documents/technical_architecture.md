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
