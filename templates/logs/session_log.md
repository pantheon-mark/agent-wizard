# Session Log

*Per-session record of what was done, by whom, and why. One entry per session. Updated at session start (flag and mode) and session end (summary, files changed, commits made).*

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
| Critical | System-stopping event occurred during this session |
| High | Significant event occurred — surfaces in real-time alerts |
| Warning | Notable event — surfaces in digest |
| Informational | Normal session — logged for traceability |

---

## Entries

| Session ID | Started | Ended | Mode | Flag used | Summary of work | Files changed | Commits | Notes |
|-----------|---------|-------|------|-----------|----------------|--------------|---------|-------|
