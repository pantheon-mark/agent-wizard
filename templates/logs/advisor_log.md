# Advisor Log

*All advisor routing events, responses processed, knowledge base entries written, and rules applied autonomously. Provides a complete record of every advisor interaction and its outcome.*

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
| High | Advisor decision overdue past the configured stale threshold |
| Warning | Decision approaching stale threshold — reminder due |
| Informational | Normal routing, response, or rule-application event |

---

## Event types

| Type | Description |
|------|------------|
| Routed | Decision sent to advisor or surfaced for input |
| Guide generated | Interview guide written for enhanced-path consultation |
| Response received | Advisor response received and processed |
| Entry written | Knowledge base entry written from advisor input |
| Rule applied | Advisor knowledge base rule applied autonomously |
| Review due | Entry flagged for reconfirmation has reached its review date |

---

## Entries

| Entry ID | Timestamp | Severity | Event type | Advisor | Decision ID | Details | Outcome |
|----------|-----------|----------|-----------|---------|------------|---------|---------|
