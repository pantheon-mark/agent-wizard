# Cost and Efficiency Log

*Structured running log of token usage per agent per run, cumulative costs, and cost-per-output over time. Written continuously by agents and the orchestrator. Read by architectural review, digest generator, and agents for runtime self-regulation.*

*Permanently excluded from git. Never committed under any circumstances.*

---

## Data classification rule

**No raw personal data in any log entry.** This rule is not configurable and cannot be overridden.

What may never appear: names, email addresses, phone numbers, physical addresses, account numbers, payment data, authentication tokens, or any field that uniquely identifies a specific person.

What is safe to log: opaque record IDs (e.g., `customer [ID:4782]`), task names, agent names, operation types, timestamps, status codes, and file paths that do not contain personal identifiers.

---

## Severity levels

| Level | Meaning |
|-------|---------|
| Critical | 100% of automation budget reached — autonomous operations stop per the configured behavior (wait / interactive-fallback / paid-overflow) |
| High | 90% of automation budget reached — real-time alert |
| Warning | 75% of automation budget reached — digest entry |
| Informational | Normal cost log entry |

---

## Automation budget (monthly): {{PROJECT_AUTOMATION_BUDGET}}
## Intensive operation threshold: {{INTENSIVE_OPERATION_THRESHOLD}} ({{INTENSIVE_OPERATION_THRESHOLD_PCT}}% of budget)

*Metering is the system's own estimate (tokens × API rate) against the automation budget, with a conservative safety margin — there is no live credit-balance read (v0 bridge). The included plan automation credit is a platform hard-boundary; paid overflow (if enabled) is capped at the operator's Anthropic spending limit.*

---

## Entries

| Entry ID | Timestamp | Severity | Agent | Task ID | Tokens used | Session cumulative | Monthly cumulative | Monthly % of budget | Notes |
|----------|-----------|----------|-------|---------|-------------|-------------------|-------------------|---------------------|-------|
