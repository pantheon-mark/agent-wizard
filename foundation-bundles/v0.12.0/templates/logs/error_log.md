# Error Log

*All errors, recovery attempts, and outcomes by severity. Captures both construction errors (during build) and runtime errors (during operation). Every error is logged here regardless of whether it was automatically recovered or escalated to the user.*

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
| Critical | System-stopping — automated recovery stopped, user involvement required |
| High | Significant failure — recovery attempted; user notified if unresolved |
| Warning | Notable issue — flagged but system continues |
| Informational | Minor event — logged for traceability |

---

## Entries

| Error ID | Timestamp | Severity | Type | Domain | Agent | Description | Recovery attempts | Outcome |
|----------|-----------|----------|------|--------|-------|-------------|------------------|---------|
