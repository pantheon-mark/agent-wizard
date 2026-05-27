# Cron Configuration

*Plain-language record of all scheduled runs — the human-readable reference alongside the actual crontab entries. Entries are added during the wizard closing sequence as schedules are confirmed.*

*Updated by the system when agents are added or schedules change. Never edited manually.*

**Scheduling model.** Scheduled jobs invoke the **Orchestrator** by default. The Orchestrator then reads the work queue and routes to specialist agents — so the single-coordination-point model holds for scheduled work exactly as it does for operator-initiated work. Directly scheduling a specialist agent (bypassing the Orchestrator) is an advanced exception: it must declare its rationale, the queue scope it is permitted to touch, how it coordinates the session lock, and where it writes its handoff. Every scheduled run is invoked, runs to completion, and exits — the system is never a continuously-running background process.

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

When `maintenance_mode.md` exists in the project root, all scheduled runs are skipped. This is the same session-lock file the Orchestrator creates while a session is active and clears when it finishes — so a scheduled run never collides with an in-progress session, and a deliberate maintenance pause stops scheduled work too. The cron job logs the skip reason and the scheduled time — it does not fail silently.
