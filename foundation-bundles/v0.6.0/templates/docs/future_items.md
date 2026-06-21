# {{PROJECT_NAME}} — Future Items Register

*Time-triggered, condition-triggered, and monitoring cadence items. Checked by the orchestrator at every session close. Due items are surfaced via the session bootstrap update.*

*Last updated: {{LAST_UPDATED_DATE}}*

---

## Date-triggered items

*"On [date], do [action]." One-time items are marked triggered after execution. Items that were due while the system was offline are surfaced at the next session.*

| Item | Trigger date | Action | Source | Status |
|------|-------------|--------|--------|--------|
{{DATE_TRIGGERED_ROWS}}

---

## Condition-triggered items

*"When [condition], do [action]." Checked against current system state at every session close.*

| Item | Condition | Action | Source | Status |
|------|-----------|--------|--------|--------|
{{CONDITION_TRIGGERED_ROWS}}

---

## Monitoring cadence register

*Recurring checks that are not cron jobs. After each check, the next due date is updated.*

| Item | Cadence | Next due | Action | Source |
|------|---------|----------|--------|--------|
| Rules library review | Quarterly | {{FIRST_QUARTERLY_REVIEW_DATE}} | Review rules library for stale or conflicting entries | Wizard setup |
| Credential rotation check | {{CREDENTIAL_CHECK_CADENCE}} | {{FIRST_CREDENTIAL_CHECK_DATE}} | Verify all no-expiry credentials still valid | CRED-4 |
| Context window limit verification | Quarterly | {{FIRST_CONTEXT_CHECK_DATE}} | Verify context window limit in project_instructions.md matches current Anthropic account settings | Finding SG-1 |
{{ADDITIONAL_MONITORING_ROWS}}

---

*When work reveals a time-gated follow-up, condition-triggered dependency, or monitoring cadence, add it to this file immediately.*
