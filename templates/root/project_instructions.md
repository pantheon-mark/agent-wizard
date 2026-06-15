# {{PROJECT_NAME}} — Project Instructions

*System-owned configuration file. All threshold values, authorizations, and preferences for this project are stored here. Read by agents at every session start. Updated only through the system's authorized update mechanisms — never edited manually except during wizard setup.*

*Last updated: {{LAST_UPDATED_DATE}} | Trigger: wizard setup*

---

## User Profile

**Technical literacy:** {{UP_TECHNICAL_LITERACY}}
**Information preference:** {{UP_INFORMATION_PREFERENCE}}
**Decision preference:** {{UP_DECISION_PREFERENCE}}
**Domain expertise:** {{UP_DOMAIN_EXPERTISE}}
**Involvement appetite:** {{UP_INVOLVEMENT_APPETITE}}

**Profile summary:** {{UP_PROFILE_SUMMARY}}

---

## Autonomy Level

**Current level:** {{AUTONOMY_LEVEL}}
**Set:** {{LAST_UPDATED_DATE}}
**Advancement:** Autonomy level advances only when the user explicitly expands authorization in this file. Claude never self-promotes its own authority level.

### What the system may do without asking (Level {{AUTONOMY_LEVEL}})

{{AUTONOMOUS_ACTIONS}}

### What the system always asks first

**Baseline Tier 1 items (not removable):**

- Spending money — any financial transaction or commitment
- Sending messages on behalf of the user — emails, messages, posts, or external communications of any kind
- Irreversible actions — deleting files, removing data, or actions that cannot be undone
- Guardrail violations — anything that would cross a rule this system is configured to follow
- Legal or compliance actions — anything that could create a legal obligation or compliance issue
- Contradictions — when an action conflicts with the vision document or the user's confirmed rules

**User additions to Tier 1:**

{{TIER_1_ADDITIONS}}

### Bash authorization

**Current authorization:** {{BASH_AUTHORIZATION}}

*Bash authorization is tracked separately from content authorization. Check this field before running any shell command autonomously. Bash authorization level advances only on explicit user instruction.*

---

## Financial Configuration

This system's autonomous (unattended/scheduled) work draws on the separate monthly **automation credit** included with your Claude plan — not your everyday interactive Claude use, which is unaffected.

| Setting | Value |
|---------|-------|
| Plan automation credit (monthly) | {{AUTOMATION_CREDIT_POOL}} |
| This project's automation budget (monthly) | {{PROJECT_AUTOMATION_BUDGET}} |
| Sharing posture | {{PROJECT_SHARE_POSTURE}} |
| When the budget is used up | {{EXHAUSTION_BEHAVIOR}} |
| Paid-overflow cap | {{PAYG_CAP}} |
| Intensive operation threshold | {{INTENSIVE_OPERATION_THRESHOLD}} |

**Budget enforcement (self-metered estimate — v0).** The system meters its own estimated automation spend (tokens × API rate; see `/logs/cost_efficiency_log.md`) against this project's monthly automation budget, with a conservative safety margin. There is no live credit-balance read, so it errs early. The included automation credit is itself a platform hard-boundary: when the plan's monthly credit is exhausted, unattended requests stop at the platform unless paid overflow ("usage credits") is enabled.

**When this project's automation budget is reached, behavior follows `{{EXHAUSTION_BEHAVIOR}}`:**

- **wait** — stop unattended work; no auto-resume; resume next billing cycle or on explicit user authorization. No extra cost.
- **interactive-fallback** — stop unattended (scheduled/headless) dispatch, but continue serving queued work whenever the user is in an interactive session (which draws the separate interactive allowance, not the automation credit). No extra cost. In this mode the Orchestrator must NOT spawn headless `claude -p` runs; interactive sessions drain `/work/work_queue.md` directly.
- **paid-overflow** — continue into the platform's pay-as-you-go usage credits up to {{PAYG_CAP}}. The AUTHORITATIVE cap is the user's Anthropic platform monthly spending limit (set at claude.ai/settings/usage, with auto-reload OFF); this system self-meters an estimate, alerts when paid usage begins and as it nears the cap, and stops before the cap. Requires usage credits enabled (on Team plans, by an org admin).

*Any single operation estimated above the intensive operation threshold ({{INTENSIVE_OPERATION_THRESHOLD}}) pauses for explicit user approval regardless of remaining budget.*

*To change any of these, tell the system in a session (e.g. "switch to wait" or "raise my overflow cap to $30") — it updates this file and confirms. The user never edits this file by hand.*

---

## Notification Preferences

| Setting | Value |
|---------|-------|
| NTFY alert topic | `{{NTFY_TOPIC}}` |
| Digest delivery email | {{DIGEST_EMAIL}} |
| Digest cadence | {{DIGEST_CADENCE}} |
| Stale decision threshold | {{STALE_DECISION_THRESHOLD_DAYS}} days |
| Notification verbosity | {{NOTIFICATION_VERBOSITY}} |

*Verbosity governs all alerts below critical level. Critical alerts always use full detail regardless of this setting.*

---

## Quality and Error Settings

| Setting | Value |
|---------|-------|
| Three-strikes threshold | {{THREE_STRIKES_THRESHOLD}} attempts per step |
| Confidence flagging threshold | {{CONFIDENCE_FLAGGING_THRESHOLD}} |
| QA reporting style | {{QA_REPORTING_STYLE}} |

*Three-strikes threshold is per step, not per task. Completed steps are preserved when a later step escalates.*

---

## Operational Settings

| Setting | Value |
|---------|-------|
| Retry threshold | {{RETRY_THRESHOLD}} attempts |
| Gate conflict timeout | {{GATE_CONFLICT_TIMEOUT}} |
| Deferred alert threshold | {{DEFERRED_ALERT_THRESHOLD}} deferrals before escalation |
| Chunk confirmation | {{CHUNK_CONFIRMATION}} |
| Drift analysis cadence | {{DRIFT_ANALYSIS_CADENCE}} |

---

## Scale Tier

**Tier:** {{SCALE_TIER}} (provisional)
**Set:** {{SCALE_TIER_SET_DATE}}
**Rationale:** {{SCALE_TIER_RATIONALE}}

*Provisional — set during wizard setup. Requires explicit user confirmation before this value changes.*

---

## Model Tier Mapping

*Fetched from Anthropic documentation at wizard setup. Checked for currency at each architectural review. Deprecated model strings require immediate update. Stale but non-deprecated mappings are flagged at the next phase-gate.*

| Tier | Model | Notes |
|------|-------|-------|
| High | {{MODEL_HIGH}} | {{MODEL_HIGH_NOTES}} |
| Standard | {{MODEL_STANDARD}} | {{MODEL_STANDARD_NOTES}} |
| Fast | {{MODEL_FAST}} | {{MODEL_FAST_NOTES}} |

*Last verified: {{MODEL_MAPPING_VERIFIED_DATE}}*

---

## Context Management

| Setting | Value |
|---------|-------|
| Context window limit | {{CONTEXT_WINDOW_LIMIT}} |
| Pre-flight saturation threshold | {{PREFLIGHT_THRESHOLD}} |
| Mid-execution saturation threshold | {{MID_EXECUTION_THRESHOLD}} |

*Default thresholds: pre-flight 50%, mid-execution 65%. Adjustments require user authorization before being applied to this file.*

---

## Per-Agent Directory Permissions

*Centralized permission registry. Each agent's prompt file also contains its own permission boundary — this table is the single-view audit reference. Updated when agents are added, modified, or removed.*

| Agent | Permitted write directories | Criticality tier |
|-------|---------------------------|------------------|
{{AGENT_PERMISSION_ROWS}}

---

## Input Type Inventory

*Confirmed during wizard input validation phase. Updated when new input types are identified or existing ones change. Full validation behavior (sensitivity, override log) lives in `/quality/validation_gate_config.md`.*

| Input type | Source | What it is | What stops without it | Structural rules | Status |
|------------|--------|------------|----------------------|------------------|--------|
{{INPUT_TYPE_INVENTORY}}

---

## Credential Reference

*Credential values are in `.env` — never in this file. This table is a reference only: which environment variable names correspond to which services.*

| Credential | ENV variable | Expiry behavior |
|------------|-------------|-----------------|
{{CREDENTIAL_REFERENCE_ROWS}}

*Expiry handling: the system warns you {{ROTATION_LEAD_TIME_DAYS}} days before a credential expires, and re-checks credentials that don't expire on their own {{CREDENTIAL_CHECK_CADENCE}}. You don't track expiry yourself — the system tracks each credential and alerts you in time to act.*

---

## Version Pins

*Confirmed working versions for key dependencies. Updated after every successful update via the dependency update mechanism.*

| Package | Confirmed version | Last verified |
|---------|------------------|---------------|
{{VERSION_PIN_ROWS}}

---

## GitHub Remote

**Remote URL:** {{GITHUB_REMOTE_URL}}

*(Empty if local-only setup was chosen during wizard.)*
