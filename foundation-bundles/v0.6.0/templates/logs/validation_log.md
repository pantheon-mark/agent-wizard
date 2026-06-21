# Validation Log

*All validation gate events — structural passes, semantic passes, soft pushbacks, hard failures, user overrides, and calibration updates. Every input that passes through the validation gate is logged here.*

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
| High | Hard failure — input rejected, structural validation failed |
| Warning | Soft pushback raised — input flagged for user confirmation |
| Informational | Pass, auto-approval, or calibration update |

---

## Validation tiers

| Tier | What it checks |
|------|---------------|
| Structural | Format, schema, field presence, encoding — hard rules |
| Semantic | Meaning, domain plausibility, rules library match — soft rules |

---

## Entries

| Entry ID | Timestamp | Severity | Input type | Source | Tier | Result | Pushback type | User response | Override rationale |
|----------|-----------|----------|-----------|--------|------|--------|--------------|--------------|-------------------|
