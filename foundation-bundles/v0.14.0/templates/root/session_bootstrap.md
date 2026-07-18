# {{PROJECT_NAME}} — Session Bootstrap

*Updated: {{LAST_UPDATED_DATE}} | Trigger: {{LAST_UPDATED_TRIGGER}}*

---

## Project

**Name:** {{PROJECT_NAME}}  
**Purpose:** {{PROJECT_PURPOSE}}  
**GitHub remote:** {{GITHUB_REMOTE_URL}}  

---

## System status

| Field | Value |
|-------|-------|
| Autonomy level | {{AUTONOMY_LEVEL}} |
| Current phase | {{CURRENT_PHASE}} |
| Last session | {{LAST_SESSION_DATE}} |
| Last agent run | {{LAST_AGENT_RUN}} |

---

## Build progress

Read `build_progress.md` and `execution_plan.md` at the start of every session. Identify the next unbuilt phase from `execution_plan.md` and check its current state in `build_progress.md`.

**Refusing precondition:** do not start the next phase until the prior phase is `accepted` (or `provisionally-accepted` with its deferred core precondition cleared). If the prior phase is not yet accepted, do not proceed with building -- surface what remains to close acceptance first.

To build the next phase, use the `wizard/skills/next-phase.md` skill.

The system orients the operator at every transition per `operating_discipline.md` — it always names a single recommended next step and will not go idle while a decision is pending (the Stop-hook idle guard).

**Saved next step takes precedence.** If the "Next action" below is set, or a "Resume here" note was left when the operator paused, that saved step is the lead next step — including when a thread was left mid-way or set aside. Treat a paused or in-progress thread as an active next step, not "no action"; do not lead with a phase- or date-derived task while a saved next step or paused thread is waiting. (Per `operating_discipline.md` § Orientation; this is the same precedence the `orientation.md` skill applies on demand.)

---

## Last session

**Summary:** {{LAST_SESSION_SUMMARY}}  
**Left incomplete:** {{ITEMS_LEFT_INCOMPLETE}}  
**Next action:** {{NEXT_RECOMMENDED_ACTION}}  

---

## Active queues

*Counts as of last update. Read each detail file for full content.*

| Queue | Count | Critical / Top item |
|-------|-------|---------------------|
| Work queue (`/work/work_queue.md`) | {{WORK_QUEUE_OPEN_COUNT}} open | {{WORK_QUEUE_TOP_ITEM}} |
| Alerts (`/logs/notification_log.md`) | {{ALERT_ACTIVE_COUNT}} active | {{CRITICAL_ALERT_NOTE}} |
| Pending decisions (`pending_decisions.md`) | {{PENDING_DECISION_COUNT}} pending | — |
| Human review queue (`/quality/human_review_queue.md`) | {{REVIEW_QUEUE_COUNT}} items | — |

---

## Upcoming scheduled tasks

*Cron-triggered Orchestrator runs (which route to the configured agents). Updated at session close from `/agents/cron/cron_config.md`.*

| Agent | Next trigger | Frequency | Notes |
|-------|-------------|-----------|-------|
{{CRON_SCHEDULE_ROWS}}

---

## Quick reference

*Frequently needed values. Full configuration in `project_instructions.md`.*

| Setting | Value |
|---------|-------|
| Automation budget (monthly) | {{PROJECT_AUTOMATION_BUDGET}} — when reached: {{EXHAUSTION_BEHAVIOR}} |
| Three-strikes threshold | {{THREE_STRIKES_THRESHOLD}} |
| Confidence flagging threshold | {{CONFIDENCE_THRESHOLD}} |
| Pre-flight saturation threshold | {{PREFLIGHT_THRESHOLD}} |
| Mid-execution saturation threshold | {{MID_EXECUTION_THRESHOLD}} |
| Model — High tier | {{MODEL_HIGH}} |
| Model — Standard tier | {{MODEL_STANDARD}} |
| Model — Fast tier | {{MODEL_FAST}} |
| Alert channel (NTFY) | {{NTFY_TOPIC}} |
| Digest delivery | {{DIGEST_EMAIL}} |
| Scale tier | {{SCALE_TIER}} |

---

*This file is the first file a new session reads. Update it at every session close and after any significant system state change. Keep it current — a new session's ability to orient depends on it.*
