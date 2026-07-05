# Source Health Log

*Source health check results and status changes for all external data sources registered in `/quality/source_registry.md`. Every check — pass or fail — is logged here.*

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
| High | Source unavailable, structurally changed, or quarantined |
| Warning | Source degraded — returning unexpected or inconsistent responses |
| Informational | Check passed — source healthy |

---

## Entries

| Entry ID | Timestamp | Severity | Source | Check type | Status | Finding | Action taken | Agent |
|----------|-----------|----------|--------|-----------|--------|---------|-------------|-------|
