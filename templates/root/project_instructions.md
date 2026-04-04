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

**Current level:** 2
**Set:** {{WIZARD_COMPLETION_DATE}}
**Advancement:** Autonomy level advances only when the user explicitly expands authorization in this file. Claude never self-promotes its own authority level.

### What the system may do without asking (Level 2)

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

| Setting | Value |
|---------|-------|
| Overage plan type | {{OVERAGE_PLAN_TYPE}} |
| Monthly spend ceiling | {{SPEND_CEILING}} |
| Intensive operation threshold | {{INTENSIVE_THRESHOLD}} |

*When the spend ceiling is reached: unconditional stop. No auto-resume. The user must explicitly authorize continuation before any autonomous work resumes.*

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

*Confirmed during wizard input validation phase. Updated when new input types are identified or existing ones change.*

{{INPUT_TYPE_INVENTORY}}

---

## Credential Reference

*Credential values are in `.env` — never in this file. This table is a reference only: which environment variable names correspond to which services.*

| Credential | ENV variable | Expiry behavior |
|------------|-------------|-----------------|
{{CREDENTIAL_REFERENCE_ROWS}}

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
