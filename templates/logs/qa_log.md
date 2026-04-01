# QA Log

*QA agent findings, investigation workflows, and outcomes. Records every quality check — passes, failures, confidence flags, security audit results, and investigation outcomes. Source registry health issues are also captured here.*

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
| Critical | Security audit finding that quarantines an artifact — no downstream promotion until resolved |
| High | Finding requiring investigation or routing to work queue |
| Warning | Notable concern — surfaces in digest; no quarantine |
| Informational | Pass or routine quality event — logged for traceability |

---

## Entries

| Entry ID | Timestamp | Severity | Type | Producing agent | Output reference | Finding | Investigation | Outcome | Rule created |
|----------|-----------|----------|------|----------------|-----------------|---------|--------------|---------|-------------|
