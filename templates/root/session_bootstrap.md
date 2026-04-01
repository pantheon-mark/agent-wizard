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

## Quick reference

*Frequently needed values. Full configuration in `project_instructions.md`.*

| Setting | Value |
|---------|-------|
| Spend ceiling | {{SPEND_CEILING}} |
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
