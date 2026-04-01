# Templates — Logs Directory

Templates for the log files in the user's System `/logs/` directory. All log files are permanently excluded from git. The wizard creates them at setup with the correct header and column structure so runtime agents can write entries immediately without needing to initialize the file.

## Files in this directory

| Template file | Generates |
|--------------|-----------|
| `audit_log.md` | `/logs/audit_log.md` |
| `session_log.md` | `/logs/session_log.md` |
| `error_log.md` | `/logs/error_log.md` |
| `qa_log.md` | `/logs/qa_log.md` |
| `source_health_log.md` | `/logs/source_health_log.md` |
| `drift_log.md` | `/logs/drift_log.md` |
| `advisor_log.md` | `/logs/advisor_log.md` |
| `notification_log.md` | `/logs/notification_log.md` |
| `validation_log.md` | `/logs/validation_log.md` |
| `cost_efficiency_log.md` | `/logs/cost_efficiency_log.md` |

Each template contains: the log file's purpose statement, the PII/data classification rule (no raw personal data, opaque IDs only), the severity level reference, and the column headers for that log's entry format.

`/digests/` is a runtime directory — files written at runtime by the digest generator. No template needed.
