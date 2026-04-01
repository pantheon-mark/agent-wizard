# Audit Log

*Formal record of all auditable events — decisions made, actions authorized, changes applied, and approvals granted. Distinct from other logs: the audit log captures consequential events only. It is what makes this system traceable and defensible.*

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
| Critical | System-stopping event or irreversible action — immediate attention required |
| High | Significant event requiring attention — surfaced in real-time alerts |
| Warning | Notable event requiring monitoring — surfaced in digest |
| Informational | Normal operational event — logged for traceability |

---

## Entries

| Audit ID | Timestamp | Severity | Category | Event | Agent / Source | Context | Authorization | Related refs |
|----------|-----------|----------|----------|-------|---------------|---------|--------------|-------------|
