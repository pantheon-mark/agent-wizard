# Notification Log

*All alerts delivered — type, severity, channel, timestamp, and content. Rolling 7-day window: entries older than 7 days are moved to `/archive/notification_archive.md` daily.*

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
| Critical | System-stopping event — never deferred, always delivered via real-time push |
| High | Significant event — real-time alert via NTFY |
| Informational | Digest entry — delivered at next scheduled digest |

---

## Alert statuses

| Status | Meaning |
|--------|---------|
| Delivered | Alert sent and confirmed received |
| Deferred | Alert acknowledged but explicitly deferred by user |
| Acknowledged | User confirmed they have seen and acted on this alert |
| Superseded | Alert rendered irrelevant by a subsequent event — auto-closed |
| Archived | Moved to `/archive/notification_archive.md` (past 7-day window) |

---

## Entries

| Alert ID | Timestamp | Severity | Event type | Channel | Alert text summary | CLI command included | Status |
|----------|-----------|----------|-----------|---------|-------------------|---------------------|--------|
