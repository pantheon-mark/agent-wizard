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
| Critical | 100% of spend ceiling reached — all autonomous operations stopped unconditionally |
| High | 90% of spend ceiling or plan limit reached — real-time alert |
| Warning | 75% of spend ceiling or plan limit reached — digest entry |
| Informational | Normal cost log entry |

---

## Spend ceiling: {{SPEND_CEILING}}
## Intensive operation threshold: {{INTENSIVE_OPERATION_THRESHOLD}} ({{INTENSIVE_OPERATION_THRESHOLD_PCT}}% of ceiling)

---

## Entries

| Entry ID | Timestamp | Severity | Agent | Task ID | Tokens used | Session cumulative | Monthly cumulative | Monthly % of ceiling | Notes |
|----------|-----------|----------|-------|---------|-------------|-------------------|-------------------|---------------------|-------|
