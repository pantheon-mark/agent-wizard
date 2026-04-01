# Execution Plan

*Living document — updated as the system is built and evolves. Read this document before any sprint planning or work sequencing decision.*

*Last updated: {{LAST_UPDATED_DATE}} | Trigger: {{LAST_UPDATED_TRIGGER}}*

---

## MVP Definition

**Core function:** {{MVP_CORE_FUNCTION}}
**Minimum viable state:** {{MVP_MINIMUM_VIABLE_STATE}}
**Success condition for MVP:** {{MVP_SUCCESS_CONDITION}}

*Derived from the vision document. The MVP is the smallest working version of the system that demonstrates the core value proposition — enough to validate the approach and earn confidence before building further.*

---

## Build Phases

*Logical build sequence — agents are built in this order, with each phase delivering a working capability increment.*

| Phase | Agents | Capability delivered | Depends on |
|-------|--------|---------------------|------------|
{{BUILD_PHASES_ROWS}}

*Phase sequence is revisited after each phase completes. Phases are not reorganized autonomously — any change to sequencing requires user confirmation.*

---

## Execution Sequence

*Operational workflow — how agents hand off work when the system is running.*

{{EXECUTION_SEQUENCE}}

---

## Human-in-the-Loop Map

*What the system handles on its own vs. what it always brings to you. Reflects permission boundaries confirmed during the architecture phase. Updated when autonomy level changes.*

**Current autonomy level:** {{AUTONOMY_LEVEL}}

| Action category | Current behavior | Notes |
|-----------------|-----------------|-------|
| Routine operations | Proceeds autonomously — noted in digest | Configurable via chunk confirmation setting |
| Tier 1 decisions (spending, external messaging, irreversible actions, guardrail violations, legal/compliance, contradictions) | Always stops and asks first | Baseline — not removable at any level |
{{HITL_MAP_ROWS}}

---

## Sprint Planning

*Active work plans. Each sprint is recorded at `/work/sprint_[n]_plan.md`. Sprint files are created by the system at the start of each work sprint and archived on completion.*

**Current sprint:** {{CURRENT_SPRINT_NUMBER}}
**Sprint file:** `/work/sprint_{{CURRENT_SPRINT_NUMBER}}_plan.md`

---

## Work Plans

*Active work items are in `/work/work_queue.md`. Completed items are archived in `/archive/work_archive.md`. Sprint-level plans are at `/work/sprint_[n]_plan.md`.*
