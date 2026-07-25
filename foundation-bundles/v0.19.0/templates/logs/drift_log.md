# Drift Log

*Drift observations, analysis reports, and alignment fixes. Records every drift check — whether or not drift was found — and every fix applied as a result. Drift is measured against the vision document on the configured cadence.*

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
| High | Significant drift found — user decision required before fix is applied |
| Warning | Minor drift — autonomous alignment fix applied and logged |
| Informational | Check run with no drift found; or fix completed successfully |

---

## Entry types

| Type | Description |
|------|------------|
| Observation | A drift signal noted during normal operation — not yet a full analysis |
| Analysis | A scheduled drift analysis run — full report with findings |
| Fix | An alignment fix applied, either autonomously (low-risk) or after user approval |

---

## Entries

| Entry ID | Timestamp | Severity | Type | Description | Documents affected | User decision | Outcome |
|----------|-----------|----------|------|-------------|-------------------|--------------|---------|
