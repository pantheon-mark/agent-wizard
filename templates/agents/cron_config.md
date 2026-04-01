# Cron Configuration

*Plain-language record of all scheduled agent runs — the human-readable reference alongside the actual crontab entries. Entries are added during the wizard closing sequence as agent schedules are confirmed.*

*Updated by the system when agents are added or schedules change. Never edited manually.*

---

| Agent | What it does on schedule | Schedule | Cron expression | Invocation command | Last run | Last status |
|-------|------------------------|----------|----------------|-------------------|----------|------------|

*No entries yet. Cron entries are added during the wizard closing sequence.*

---

## Schedule reference

| Human-readable | Cron expression |
|---------------|----------------|
| Every day at 6 AM | `0 6 * * *` |
| Every day at midnight | `0 0 * * *` |
| Every hour | `0 * * * *` |
| Every weekday at 9 AM | `0 9 * * 1-5` |
| Every Sunday at 8 PM | `0 20 * * 0` |

*Custom schedules use standard cron syntax in the cron expression column.*

---

## Maintenance mode behavior

When `/work/maintenance_mode.md` exists, all scheduled agent runs are skipped. The cron job logs the skip reason and the scheduled time — it does not fail silently.
