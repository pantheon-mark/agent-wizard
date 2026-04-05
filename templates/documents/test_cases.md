# Test Cases

*System test suite — generated from the framework test suite accumulator at wizard setup. All entries that apply universally to every system are included. Agent-specific tests are added during the build phase.*

*Tests run automatically on the triggers listed below. Results are written to `/logs/qa_log.md`.*

*Note: Wizard testing framework entries (Gates 1–4, mode sequencing, exit criteria) are build-time entries that govern wizard development — they do not apply to the running system and are maintained in the build project's testing framework, not here.*

---

## Test Triggers

| Trigger | Scope |
|---------|-------|
| After any error recovery attempt | Affected component and its dependencies |
| After any code change | Changed component and its dependencies |
| After new agent added | New agent plus integration with existing agents |
| After system drift alignment fix applied | Fixed component and downstream dependencies |
| After source health issue resolved | Source integration and downstream data flows |
| After significant system output | Output pipeline from source to delivery |
| On periodic schedule — cadence wizard-configured | Full system |
| After any foundational document update | Components governed by that document |
| After autonomy level authorization change | All components affected by expanded authorization |
| After validation gate config updated | Validation gate and all input paths it governs |
| After expertise calibration model updated | Validation gate behavior for affected domain |
| After any credential rotation — manual or auto | All agents and integrations that use that credential |
| After automated login script updated | Session cookie refresh flow for affected site |
| After document impact map updated | Document update trigger logic and change summary generation |
| After dependency update — successful or rolled back | All agents and integrations that depend on updated package |
| After wizard Phase 2 completes | Project directory structure, git initialization, session_bootstrap.md, project_instructions.md |
| After first agent build and first agent run complete | Full integration stack: invocation script, handoff envelope, orchestrator routing, log entry, notification delivery |
| After spend ceiling or intensive operation threshold updated | Financial guardrail enforcement across all autonomous operations |
| After phase-gate architectural review completes | All foundation documents reviewed, findings categorized, staging file current |
| After architectural review calibration feedback — rules library entry written | Categorization behavior for affected finding type |
| After context window limit updated in project_instructions.md | Pre-flight and mid-execution saturation detection behavior for all agents |
| After saturation threshold adjusted | Pre-flight and mid-execution detection triggers at new threshold values |
| After phase-gate review checkpoint pruning | Completed checkpoints removed, failed/incomplete checkpoints retained |

---

## Test Coverage Requirements

### Handoff and coordination

| # | Test | Pass condition |
|---|------|---------------|
| H-1 | Handoff envelope format validation | Each agent produces a correctly structured handoff envelope |
| H-2 | Gate claim and release behavior | Gate is claimed before work begins and released after — no orphaned claims |
| H-3 | Gate conflict detection and resolution | Two agents attempting simultaneous access produce a conflict, one is queued |
| H-4 | Idempotency — agent does not re-execute completed work | Re-running a completed task produces the same output without re-executing |
| H-5 | Orchestration model routing — correct agent receives correct work | Each work item routes to the correct agent per the confirmed orchestration model |
| H-6 | Parallel fan-out merge/coordinator gate | Parallel agents fan out and merge correctly — coordinator gate holds until all complete |

---

### Error handling

| # | Test | Pass condition |
|---|------|---------------|
| E-1 | Error detection and logging | All errors detected and written to `/logs/error_log.md` with severity and context |
| E-2 | Recovery attempt sequence | System attempts recovery per configured threshold before escalating |
| E-3 | Level 2 error behavior | At Level 2, all errors surface to user with exact prompt — no automated recovery executes before user initiates |
| E-4 | Three-strikes escalation | Task escalates to user after configured strike count — completed steps preserved |
| E-5 | Stop-the-system criteria enforcement | Stop-the-system events halt all autonomous operations immediately |
| E-6 | Cascading effect check execution | System checks downstream effects before treating a recovery as complete |
| E-7 | Continue-with-flagging behavior | Standard-tier agent failure flags and continues; Critical-tier failure stops the relevant workflow |

---

### QA and quality

| # | Test | Pass condition |
|---|------|---------------|
| Q-1 | Agent local quality gate before handoff | Each agent runs its quality gate before writing the handoff envelope |
| Q-2 | QA agent independence from production pipeline | QA agent cannot modify production outputs — read access only |
| Q-3 | Confidence flagging on uncertain outputs | Uncertain outputs flagged per configured threshold |
| Q-4 | Confidence flagging threshold reads from project_instructions.md | Threshold is not hardcoded; default applied correctly when no user setting present |
| Q-5 | Rules library check on new outputs | Each output checked against the rules library before handoff |
| Q-6 | Source health monitoring — structural change detection | Structural change to a source detected and reported |
| Q-7 | Source health monitoring — access change detection | Access change to a source detected and reported |
| Q-8 | Investigation workflow spawning and reporting | High-severity source health event triggers investigation workflow and written report |
| Q-9 | Security audit triggers on correct criteria | Audit fires for any of the five qualifying criteria: external API call, cross-workspace access, external input acceptance, access control config, sensitive data handling |
| Q-10 | Security audit does not trigger for internal-only artifacts | Internal artifact meeting none of the five criteria does not trigger audit |
| Q-11 | Minimum access scope check | Over-broad API scope requests and unnecessary directory access flagged |
| Q-12 | Input boundary check | Unvalidated external input passed to commands, file writes, or API calls flagged |
| Q-13 | Data containment check | Sensitive data in logs, unnecessary external services, or retained beyond operational lifetime flagged |
| Q-14 | Critical finding quarantines artifact | Critical security finding stops artifact promotion to downstream agents until resolved |
| Q-15 | High finding routes to work queue | High security finding written to work queue without automatic quarantine |
| Q-16 | Warning finding produces digest entry only | Warning finding appears in digest — no quarantine or work queue item |
| Q-17 | Quarantine release requires explicit user authorization | Quarantine not auto-released at any autonomy level |
| Q-18 | Level 1-2 security finding behavior | At Levels 1-2, Critical and High findings both quarantine automatically |
| Q-19 | Level 3-4 security finding behavior | At Levels 3-4, Critical quarantines; High routes to work queue without quarantine |
| Q-20 | All security audit results written to disk | Audit results written regardless of finding severity |
| Q-21 | Quarantined artifact excluded from auto-commit | Quarantined artifact not committed until quarantine lifted |
| Q-22 | Security audit cannot be disabled | No configuration flag or autonomy level setting disables the security audit |
| Q-23 | Security finding plain-language summary | Finding summary contains all three required elements: what the artifact does, what the concern is, what the proposed fix is |

---

### Agent identity and permissions

| # | Test | Pass condition |
|---|------|---------------|
| A-1 | Permission boundary enforcement | Each agent accesses only what its role authorizes |
| A-2 | Directory access restriction | Agent cannot access directories outside its authorized set |
| A-3 | External API restriction | Agent cannot call APIs not authorized for its role |
| A-4 | Bash execution authority | Bash commands respect current autonomy level authorization |
| A-5 | Escalation on boundary exceeded | Boundary exceeded triggers escalation path immediately |
| A-6 | Invocation script loads prompt file | Agent invocation script loads prompt file before invoking Claude — no invocation without guardrails |
| A-7 | Invocation script aborts on missing prompt | If prompt file is missing, invocation script aborts and logs Critical |
| A-8 | Invocation script disk I/O correctness | Inputs read from correct disk locations; outputs written to correct disk locations |
| A-9 | Cron job triggers on correct schedule | Cron job fires for each configured agent on its configured schedule |
| A-10 | Headless agent run completes cleanly | Headless run completes, writes output to disk, and exits without error |
| A-11 | Session entry scripts execute without error | All three start-session.sh flag variants complete without error after wizard setup |
| A-12 | --resume flag initiates resume startup | start-session.sh --resume runs the resume startup sequence |
| A-13 | --resume --alert flag initiates alert-response startup | start-session.sh --resume --alert runs the alert-response startup sequence |
| A-14 | Pre-flight size assessment runs before every execution | Size estimate computed and threshold checked before agent runs |
| A-15 | Pre-flight decomposition triggers at threshold | Decomposition fires when estimate exceeds 50% pre-flight threshold |
| A-16 | Decomposition plan written before sub-task 1 | Decomposition plan written to `/agents/checkpoints/` before any sub-task executes |
| A-17 | Level 1-2 pre-flight alert fires | At Levels 1-2, pre-flight decomposition fires real-time alert with paste-ready Step 1 prompt |
| A-18 | Level 3-4 pre-flight proceeds silently | At Levels 3-4, pre-flight decomposition proceeds silently with digest entry written |
| A-19 | Mid-execution checkpoint triggers at threshold | Checkpoint fires when context consumption exceeds 65% mid-execution threshold |
| A-20 | Checkpoint file written correctly | Checkpoint written to `/agents/checkpoints/` with completed steps, remaining steps, and resume prompt |
| A-21 | Level 1-2 mid-execution alert fires | At Levels 1-2, mid-execution checkpoint fires real-time alert with paste-ready resume prompt |
| A-22 | Level 3-4 mid-execution resumes silently | At Levels 3-4, mid-execution checkpoint resumes in next invocation silently |
| A-23 | Checkpoint and decomposition files cleared on completion | Files cleared when task completes successfully |
| A-24 | Context window limit reads from project_instructions.md | Context window limit not hardcoded — read from project_instructions.md at every invocation |
| A-25 | Saturation thresholds read from project_instructions.md | Both thresholds read from project_instructions.md — default 50%/65% applied correctly |
| A-26 | Threshold adjustment requires user authorization | New threshold not written to project_instructions.md until user authorizes |
| A-27 | Mid-execution detection triggers on quality degradation | Detection fires on output quality degradation signals (truncated output, repetition, missing sections) in addition to the context percentage threshold |
| A-28 | Interactive session claims gate before editing protected files | Gate claimed before editing `/agents/prompts/`, `/agents/scripts/`, or `project_instructions.md` |
| A-29 | Interactive session gate released after edit | Gate released after edit completes — no orphaned claims |
| A-30 | Agent invocation scripts use atomic write pattern | Output written to temp file and renamed — no direct writes |
| A-31 | Maintenance mode causes cron agent to skip and log | Cron agent skips run and logs reason when maintenance mode file is present — not silent failure |
| A-32 | Maintenance mode cleared at session end | Maintenance mode file deleted before session exits |
| A-33 | Stale maintenance mode detected and cleared at startup | Stale file auto-cleared and Warning alert sent at session startup |
| A-34 | Complexity assessment runs before every task | Signals checked before every agent task — decomposition triggered only when signal present |
| A-35 | No complexity signals — runs directly | Task with no complexity signals runs directly — no plan written |
| A-36 | Complexity signal triggers plan before step 1 | Any complexity signal triggers plan written to `/agents/checkpoints/` before step 1 executes |
| A-37 | Checkpoint written after output confirmed on disk | Checkpoint written after output verified — not before |
| A-38 | Retry with IN PROGRESS checkpoint skips COMPLETE steps | Retry resumes from first PENDING step — completed steps not re-run |
| A-39 | Retry with DONE checkpoint passes idempotency check | Task not re-executed when checkpoint is already DONE |
| A-40 | Three-strikes rule per step | Three-strikes applied per step — prior completed steps not re-run on later-step failure |
| A-41 | Level 1-2 plan approved before step 1 | Plan surfaced to user and approved once before step 1 executes at Levels 1-2 |
| A-42 | Level 1-2 step results reported after each step | Step results reported after each step at Levels 1-2 — no per-step approval prompt |
| A-43 | Level 3-4 plan and execution proceed silently | Plan and execution proceed silently at Levels 3-4 — digest entry on completion |
| A-44 | Completed checkpoints retained until phase-gate | DONE checkpoints retained until next phase-gate review, then pruned |
| A-45 | Failed/incomplete checkpoints never auto-pruned | Failed or incomplete checkpoints retained until manually resolved |
| A-46 | Step idempotency enforced even with partial checkpoint | Re-running a COMPLETE step produces the same output as the original |
| A-47 | SG-1 and SG-3 stacking behavior | When both context threshold (SG-1) and complexity signals (SG-3) trigger, SG-1 pre-flight runs first and splits into sub-tasks; each sub-task then runs SG-3 complexity assessment independently |
| A-48 | Every agent session logs a stop reason on termination | No session ends without a `stop_reason` field in the session log |
| A-49 | Stop reason correctly assigned per taxonomy | `completed` for task finished, `budget_exceeded` for budget cap, `error` for unrecoverable error, `timeout` for time limit, `user_cancelled` for cancellation, `deferred` for agent-chosen deferral |
| A-50 | Deferred stop reason distinct from completed | `deferred` means agent stopped before finishing; `completed` means agent finished |
| A-51 | QA agent reads stop reasons as first-pass signal | `budget_exceeded` and `error` stop reasons trigger investigation check by QA agent |
| A-52 | Orchestrator responds appropriately to stop reasons | `budget_exceeded` triggers continuation or escalation; `error` triggers investigation before retry |

---

### MCP resilience

| # | Test | Pass condition |
|---|------|---------------|
| M-1 | MCP call failure triggers local output fallback | Skill completes logic and writes findings to disk even when MCP call fails |
| M-2 | Plain-language action prompt fires on first MCP failure | Digest entry explains what was found, why it couldn't be delivered, and what to do manually |
| M-3 | Degradation alert fires after 3 failures in 24 hours | High severity alert fires after 3 failures from same MCP source within 24-hour window — not on first failure |
| M-4 | Degradation alert does not fire for failures spanning 24 hours | 3 failures spanning more than 24 hours do not trigger degradation alert |
| M-5 | Internal-only skills have no degradation logic | Skills with no MCP calls do not include degradation logic |
| M-6 | Degradation behavior identical at all autonomy levels | No level bypasses local fallback |

---

### Task completion enforcement

| # | Test | Pass condition |
|---|------|---------------|
| T-1 | Task completion checklist enforced before handoff | Checklist verified before handoff envelope is written |
| T-2 | Criticality tier thresholds enforced | Critical-tier agent failure halts dependent workflow; Standard-tier flags and continues |
| T-3 | System-level completion check against vision document | Completed work checked for alignment with vision document |
| T-4 | Document currency enforced | Change not logged as complete until document updates are written |

---

### Human-in-the-loop

| # | Test | Pass condition |
|---|------|---------------|
| L-1 | Tier 1 decisions intercepted and surfaced | Tier 1 decisions not auto-executed at any level |
| L-2 | Stale decision threshold detection | Decision not resolved within threshold triggers follow-up |
| L-3 | Pending decisions file accurately reflects current state | File contains all open decisions; resolved decisions are in archive |
| L-4 | Operations digest generation and delivery | Digest generated at configured cadence and delivered via email |
| L-5 | Real-time alert delivery for Critical and High events | NTFY alert delivered for all Critical and High severity events |
| L-6 | Advisor identification proposes relevant types from vision document | Wizard proposes advisor types; user confirms, removes, or adds; each confirmed advisor has a header entry in advisor_knowledge_base.md |

---

### Notifications and alerts

| # | Test | Pass condition |
|---|------|---------------|
| N-1 | NTFY alert for every Critical event | NTFY notification delivered for every Critical severity event |
| N-2 | NTFY alert for every High event | NTFY notification delivered for every High severity event |
| N-3 | Alert template signal correct | ACTION NEEDED vs NO ACTION NEEDED correctly applied per alert type |
| N-4 | Alert contains no raw log content | Alert plain-language translation contains no raw log content or file paths |
| N-5 | Alert includes exact CLI startup command | Exact `./start-session.sh` command present verbatim in every alert |
| N-6 | Critical alerts always use full detail | Critical alerts ignore verbosity preference — always full detail |
| N-7 | High alerts respect verbosity preference | High severity alerts use configured verbosity level |
| N-8 | Every alert written to notification log | Every alert written to `/logs/notification_log.md` on disk |
| N-9 | Operations digest generated at cadence | Digest generated at configured cadence and delivered via email |
| N-10 | Every digest written to /digests/ | Timestamped digest file written to `/digests/` for every digest sent |
| N-11 | Digest narrative header reflects system state | Narrative header accurately describes overall system state |
| N-12 | Digest sections accurate | Pending items, autonomous actions, health, and upcoming events all accurate |
| N-13 | Digest includes CLI startup command | `./start-session.sh` command present in every digest |
| N-14 | NTFY test notification confirmed at wizard setup | Test notification sent and receipt confirmed before wizard proceeds |
| N-15 | Email digest test confirmed at wizard setup | Test email sent and receipt confirmed before wizard proceeds |
| N-16 | NO ACTION NEEDED alerts downgraded at Level 3+ | NO ACTION NEEDED alerts converted to digest entries at Level 3 and above |

---

### Session startup sequence

| # | Test | Pass condition |
|---|------|---------------|
| S-1 | Startup reads correct files in order | All six startup files read in correct order before status is presented |
| S-2 | Working files contain only active items | No resolved items in working files at startup |
| S-3 | Critical alert tight loop enforces no-proceed | User cannot skip to briefing while Critical alert is unresolved |
| S-4 | Blocked critical alert resurfaces at next startup | Unresolved Critical alert leads next session |
| S-5 | Deferred alert relevance check runs automatically | Relevance check runs before surfacing deferred alerts |
| S-6 | Superseded deferred alerts auto-closed | Alerts superseded by later events auto-closed with log entry — not shown to user |
| S-7 | Deferred alert re-escalation threshold triggers flag | Alert escalated as overdue after configured deferral count |
| S-8 | Execution plan chunks sized within session limits | Chunks sized before execution begins — no oversized chunks |
| S-9 | Mid-session state save writes plan state file | `/work/execution_plan_state.md` written with resume command when mid-session save triggers |
| S-10 | Resumed session continues from correct chunk | Resumes from correct chunk — no re-execution of completed chunks |
| S-11 | Execution plan state file cleared on completion | State file deleted when plan completes successfully |
| S-12 | Items archived immediately on resolution | Resolved items moved to archive immediately — not batched to session end |
| S-13 | Notification log rolling archive runs daily | 7-day rolling window enforced; older entries moved to archive |
| S-14 | Full status briefing only after adjudication | Full briefing not presented until all Critical and deferred alerts are adjudicated |
| S-15 | Runtime health check runs every session | Health check runs after orientation and before work begins — not skipped |
| S-16 | Health check validates all credentials | All credentials in `credentials_registry.md` validated — expired or invalid detected |
| S-17 | Health check validates external service integrations | All external integrations checked for reachability — unreachable services detected |
| S-18 | Health check validates agent prompt files | All agent prompt files confirmed present and intact — missing or corrupted detected |
| S-19 | Health check validates no configuration drift | System files match expected state — drift detected |
| S-20 | Health check partial failure blocks dependent tasks only | Independent tasks proceed; only dependent tasks blocked |
| S-21 | Health check full failure blocks all work | All work blocked with plain-language explanation of all failures |
| S-22 | Health check results recorded in session log | Results recorded as standing section in session log — not a separate file |
| S-23 | Health check failure message includes plain-language action instructions | No raw error output — user sees actionable instructions |

---

### Input validation

| # | Test | Pass condition |
|---|------|---------------|
| V-1 | Structural validation rejects malformed input | Malformed input rejected before reaching semantic check |
| V-2 | Structural validation identifies failure type | Format, field, and encoding failures each identified correctly |
| V-3 | Semantic validation runs after structural pass | Semantic check only runs when structural check passes |
| V-4 | Semantic validation applies rules library | Rules library consulted for every semantic check |
| V-5 | Hard pushback blocks input | Hard pushback stops input until it is corrected |
| V-6 | Soft pushback allows user confirmation | Soft pushback allows user to confirm intent and proceed |
| V-7 | Override logged with domain and rationale | "I meant that" override logged; sensitivity setting unchanged |
| V-8 | Low-sensitivity domain auto-approves at Level 3+ | Low-sensitivity soft pushback auto-approved and logged at Level 3 and above |
| V-9 | Level 2 surfaces all soft pushbacks | At Level 2, all soft pushbacks surface regardless of domain sensitivity |
| V-10 | Medium-sensitivity domain requires user confirmation | Medium-sensitivity soft pushback always surfaces for user confirmation |
| V-11 | Sensitivity setting change written to config | Sensitivity change written to `validation_gate_config.md` with rationale |
| V-12 | Sensitivity settings present after wizard | Domain, level, and rationale all present in `validation_gate_config.md` after wizard completes |
| V-13 | Phase-gate review includes sensitivity review | Sensitivity settings and rationale reviewed at each phase-gate |
| V-14 | Agent-to-agent handoffs bypass validation gate | Handoffs between agents do not pass through the validation gate |
| V-15 | External source failure logged and registry updated | External source validation failure logged at High severity and source registry updated |
| V-16 | Repeated failures trigger source health investigation | Repeated external source failures trigger investigation workflow |
| V-17 | Advisor interview guide written to disk | Generated interview guide written to `/advisor/interview-guides/` |
| V-18 | Transcript extraction produces structured knowledge base entries | Structured entries produced with speaker labels and timestamps for `advisor_knowledge_base.md` |
| V-19 | Advisor knowledge base entry written with required fields | Entry contains advisor, date, context, rule, conditions, review flag, and source decision |
| V-20 | Advisor knowledge base entry applied correctly | Agent applies rule when situation matches, writes audit log entry |
| V-21 | Review-flagged entry surfaces on correct date | Entry appears in digest on configured review date — not before, not silently missed |
| V-22 | Simple path closes pending decision correctly | Simple path closes with user summary input — no interview guide required |
| V-23 | No-rule semantic input routes to human review | Input with no applicable rules library match routes to human review queue |
| V-24 | Validation gate config written to disk | `validation_gate_config.md` present and correct after wizard completes |
| V-25 | All validation events written to validation log | Every gate event written to `/logs/validation_log.md` |
| V-26 | Gate silent at Level 3+ for calibrated domains | Structural passes and calibrated-domain soft pushbacks operate silently at Level 3 and above |

---

### Secrets and credentials

| # | Test | Pass condition |
|---|------|---------------|
| C-1 | .gitignore for .env present before .env created | `.gitignore` entry for `.env` confirmed before `.env` file is created |
| C-2 | .env never committed | `.env` absent from all git commits across all test runs |
| C-3 | Session cookies never committed | `/security/session_cookies/` absent from all git commits |
| C-4 | Agents read credentials from environment variables | No hardcoded credential values in any agent file |
| C-5 | Credentials registry contains no values | Registry contains metadata only — no credential values |
| C-6 | Auto-refresh executes before expiry | Token refreshed before expiry for all auto-refreshable credentials |
| C-7 | Auto-refresh failure triggers immediate alert | Auto-refresh failure fires real-time alert immediately |
| C-8 | Proactive session refresh executes before expiry | Session refreshed before expiry where lifetime is known |
| C-9 | Reactive session refresh retries operation | Operation retried automatically after reactive refresh |
| C-10 | Session lifetime recorded after first reactive refresh | Lifetime recorded and used for proactive refresh on subsequent sessions |
| C-11 | Automated login navigates and captures cookie | Login navigates correct URL, fills credentials from .env, captures cookie |
| C-12 | Automated login failure identifies failure mode | Login failure correctly identifies the cause in plain language |
| C-13 | Automated login failure halts and alerts | Login failure stops retries immediately and sends real-time user alert |
| C-14 | Credential expiry alert fires at lead time | Expiry alert fires at configured lead time — not after expiry |
| C-15 | Rotation alert includes provider-specific instructions | Rotation alert instructions match the credential type and provider |
| C-16 | No-expiry check fires at configured cadence | Confirmation check fires at configured cadence without being triggered manually |
| C-17 | .gitignore manifest updated when new type introduced | Manifest updated automatically when new file type added to .gitignore |
| C-18 | Playwright present and functioning | Playwright dependency verified after installation and after any system update |

---

### Document update mechanism

| # | Test | Pass condition |
|---|------|---------------|
| D-1 | Change event correctly categorized | Change categorized against the document impact map correctly |
| D-2 | Impact map identifies all affected documents | No gaps in affected document identification |
| D-3 | Triggered update completes before change logged as done | Change not logged complete until all triggered updates are written |
| D-4 | Three-part change summary generated | Summary contains all three required parts: trigger, assessment, what changed |
| D-5 | Change summary delivered in digest | Summary appears in digest — not as a real-time alert |
| D-6 | Periodic sweep detects inconsistencies | Sweep identifies document gaps and inconsistencies |
| D-7 | Periodic sweep fixes resolved automatically | Resolved inconsistencies fixed using same sequence as triggered updates |
| D-8 | Vision document update exception fires | Vision document change surfaced to user — not auto-updated |
| D-9 | Roadmap scope exception fires | Roadmap scope change surfaced to user — not auto-updated |
| D-10 | Partial update logged correctly | Completed parts and pending decision both recorded for partial updates |
| D-11 | Impact map updated when new category encountered | New change category adds corresponding entry to impact map |
| D-12 | Impact map update recorded in audit trail | Impact map change has audit trail entry |
| D-13 | Impact map initialization presented at wizard setup | User sees the initial impact map in plain language during wizard setup |

---

### Auto-correct behavior

| # | Test | Pass condition |
|---|------|---------------|
| AC-1 | Scenario 1 fix followed by targeted verification | Autonomous fix immediately followed by targeted verification test of affected component |
| AC-2 | Scenario 2 fix blocked before applying | Fix requiring approval not executed until user approves |
| AC-3 | Scenario 2 pre-authorized pattern applies without fresh approval | Pre-authorized fix pattern applied without requiring re-approval |
| AC-4 | Scenario 2 novel fix still requires approval at Level 4 | Genuinely novel fix still surfaces for approval even at Level 4 |
| AC-5 | Scenario 3 research consults all sources | Research step consults rules library, foundational docs, and audit trail before surfacing question |
| AC-6 | Scenario 3 surfaces one targeted question | Exactly one targeted question surfaced — not a list |
| AC-7 | Three-strikes rule enforced | Three failed attempts stops automated recovery regardless of scenario |
| AC-8 | Tier 1 boundary enforced | Fix touching Tier 1 domain surfaces for approval at every autonomy level |
| AC-9 | Guardrail-touching fix surfaces for approval | No guardrail-touching fix is auto-applied at any level |

---

### Git and version control

| # | Test | Pass condition |
|---|------|---------------|
| G-1 | Auto-commit fires for every defined significant event | No significant events trigger without a corresponding commit |
| G-2 | Auto-commit message format correct | Commit message contains event type, plain-language description, and audit trail reference |
| G-3 | .env never in any commit | `.env` absent across all test commits |
| G-4 | Session cookies never in any commit | `/security/session_cookies/` absent across all test commits |
| G-5 | /logs/ never in any commit | `/logs/` absent from all commits — permanently excluded |
| G-6 | Session-close commit captures all uncommitted changes | Session-close commit contains all changes not covered by event-triggered commits |
| G-7 | Auto-commit failure fires High alert immediately | Auto-commit failure triggers real-time High severity alert |
| G-8 | Routine rollback presents plain-language diff | No raw git output surfaced — plain language only |
| G-9 | Routine rollback requires user approval | Rollback not executed until user approves |
| G-10 | Critical rollback follows full approval sequence | Critical rollback not treated as routine — full approval sequence enforced |
| G-11 | Critical rollback impact summary covers all downstream inconsistencies | Summary identifies all files affected by the rollback, not just the primary file |
| G-12 | Bad-state recovery saves progress after each approved step | Progress written to disk after each approved step |
| G-13 | Bad-state recovery resumes from saved progress | Recovery resumes from correct saved step if session ends mid-recovery |
| G-14 | Log rotation triggers at threshold | No log file grows beyond its configured size limit |
| G-15 | Log rotation commits archive and new file atomically | Rotation produces a single atomic commit with both the archive and the new file |
| G-16 | Rotated logs land in /archive/logs/ with timestamp | Rotated file appears at `/archive/logs/` with correct timestamp suffix |
| G-17 | Archived log cleanup requires user approval | Archived log deletion surfaced in digest and requires explicit user approval |
| G-18 | Daily scheduled commit fires when no session occurs | Log files committed by daily scheduled commit when no session has occurred that day |

---

### Environment setup and dependency management

| # | Test | Pass condition |
|---|------|---------------|
| EN-1 | Environment health check runs before wizard interview | Health check not skipped |
| EN-2 | Health check identifies each missing prerequisite individually | Each failure identified separately — not a single pass/fail |
| EN-3 | Health check provides exact fix command per failure | Exact fix command provided for each identified failure |
| EN-4 | Health check re-runs after fix applied | Confirmation re-run after user applies fix |
| EN-5 | Wizard Phase 1 writes draft within first two exchanges | Draft file written to staging location within the first two exchanges |
| EN-6 | Wizard Phase 1 draft updated after every answer | No answer lost between updates |
| EN-7 | Wizard Phase 1 resume finds draft and resumes correctly | Resume correctly identifies staging draft and resumes from the correct question |
| EN-8 | Wizard Phase 2 triggered at correct time | Phase 2 triggered after project name and core purpose confirmed — not before, not after |
| EN-9 | Wizard Phase 2 creates correct structure | Directory structure created, git initialized, draft migrated to session_bootstrap.md |
| EN-10 | Staging location cleaned up after Phase 2 | Orphaned draft files not left in staging location |
| EN-11 | Dependency update check runs at session startup | Update check runs during Step 1 silent orientation |
| EN-12 | Update check covers all three packages | Git, Node.js, and Claude Code each checked separately |
| EN-13 | Successful updates logged in digest | Successful updates logged at Informational — no real-time alert |
| EN-14 | Failed updates trigger High alert immediately | Update failure fires real-time High severity alert |
| EN-15 | Post-update health check runs after every update | Health check runs after every update — pass logged, fail triggers alert |
| EN-16 | Version pin rollback triggers on health check failure | Prior confirmed working version restored on health check failure |
| EN-17 | Version pin record updated after successful update | `project_instructions.md` version pin updated after every successful update |
| EN-18 | manual.md present in project root after wizard | `manual.md` present and correct after wizard completes |
| EN-19 | manual.md treated as a living document | Document impact map updates manual.md when setup steps change |

---

### Wizard closing sequence

| # | Test | Pass condition |
|---|------|---------------|
| W-1 | Closing orientation moment complete before first build prompt | All five components of CLOSE-13 delivered before first build prompt is presented |
| W-2 | Orientation moment cannot be skipped | First build prompt not presented until all five components delivered |
| W-3 | Every build prompt written to disk before display | Build prompt file present at `/wizard/build_prompts/` before prompt is shown to user |
| W-4 | Build prompt files named descriptively | Files named consistently (e.g., `agent_01_build_prompt.md`) — no unnamed files |
| W-5 | Superpowers plugin installed and active after wizard build | Methodology enforcement layer confirmed present before first agent build begins |
| W-6 | co-protected-workflows.md present after wizard | File present in `/quality/` and pre-populated with all Tier 1 action-type patterns |
| W-7 | QA agent reads co-protected-workflows.md at every security audit | Read confirmed in agent invocation script |
| W-8 | Artifact matching co-protected pattern flagged for irreversible action gate | Agent-produced artifact matching a pattern in `co-protected-workflows.md` flagged regardless of originating skill's classification |
| W-9 | co-protected-workflows.md write-protected from agents | No agent at any level can modify this file |
| W-10 | GitHub remote correctly set if configured | `git remote -v` confirms remote origin set to user's private repo |
| W-11 | Initial push to remote completed at wizard close | Remote repo contains initial commit if GitHub was configured |
| W-12 | System project created at ~/[project-folder-name] | Project not inside ~/Documents/ or other large parent directory |
| W-13 | Wizard staging file at correct location | Staging file created at `~/claude-wizard-draft/wizard_session_draft.md` — not inside `~/Documents/` |

---

### Model tier mapping

| # | Test | Pass condition |
|---|------|---------------|
| MT-1 | Wizard fetches model mapping at setup | Mapping fetched from Anthropic documentation — not hardcoded |
| MT-2 | Initial model mapping written to project_instructions.md | All three tiers and extended thinking modifier present after wizard |
| MT-3 | Agent prompts use tier names only | No hardcoded model strings in any agent file |
| MT-4 | Architectural review checks mapping currency | Mapping check not skipped in architectural review |
| MT-5 | Deprecated model string classified as "act now" | Deprecated string triggers real-time High alert |
| MT-6 | Stale non-deprecated mapping classified as "note for phase-gate" | Stale mapping written to staging file — not escalated as real-time alert |
| MT-7 | Mapping update requires user authorization | Mapping not updated until user authorizes |
| MT-8 | Capability modifier appended to High tier | Extended thinking or equivalent modifier correctly appended when specified |
| MT-9 | start-session.sh includes --model flag | `start-session.sh` contains `--model` with resolved model name from High tier |
| MT-10 | Every agent invocation script includes --model flag | Each script in `/agents/scripts/` contains `--model` with correct tier-resolved model name |
| MT-11 | Build prompts reference start-session.sh for model | No build prompt tells user to select a model manually — all reference `./start-session.sh` |

---

### Financial guardrails

| # | Test | Pass condition |
|---|------|---------------|
| F-1 | Wizard records financial configuration correctly | Spend ceiling, overage plan type, and intensive operation threshold all present in `project_instructions.md` |
| F-2 | 75% threshold produces digest entry | 75% spend triggers digest entry — not a real-time alert |
| F-3 | 90% threshold triggers High alert | 90% spend triggers real-time High severity alert |
| F-4 | 100% ceiling stops system unconditionally | All autonomous operations halt at spend ceiling — no exceptions |
| F-5 | Stop-the-system not auto-lifted | System remains stopped until explicit user authorization |
| F-6 | Hard gate at Levels 1-2 for intensive operations | Every intensive operation surfaces for approval at Levels 1-2 regardless of threshold |
| F-7 | Soft gate at Levels 3-4 below threshold | Intensive operations below threshold proceed without approval at Levels 3-4 |
| F-8 | Soft gate at Levels 3-4 above threshold | Intensive operations above threshold surface for approval at Levels 3-4 |
| F-9 | Cost/efficiency log written after every agent run | Agent, tokens, and cumulative total updated after each run |
| F-10 | Phase-gate review runs before phase advancement proposal | Review not skippable |
| F-11 | Phase-gate covers all 7 documents | All 7 documents checked for currency and correctness |
| F-12 | Phase advancement blocked until findings cleared | Advancement blocked until all must-resolve findings are confirmed resolved |
| F-13 | Event-triggered review fires on correct triggers | Review fires for significant error cluster, major integration, security incident, cost deviation |
| F-14 | "Act now" findings route to advisor queue | Act-now findings trigger Tier 1 decision and real-time High alert |
| F-15 | "Note for phase-gate" findings write to staging | Staged findings written to `architectural_review_staging.md` — not advisor queue |
| F-16 | Staged findings incorporated at next phase-gate | No staged finding missed in next phase-gate review |
| F-17 | Phase-gate retrospective runs | Calibration signal captured as part of every phase-gate |
| F-18 | Calibration feedback writes rules library entry | Rules library entry written for affected finding type after feedback |
| F-19 | Semi-annual backstop review fires at cadence | Review fires at correct six-month interval — not skipped |
| F-20 | Per-agent session budget set at invocation | Budget amount derived from spend ceiling and agent workload fraction |
| F-21 | Agent approaching budget initiates wrap-up mode | Progress summarized, state persisted, remaining work reported |
| F-22 | Agent exceeding budget terminates gracefully | Not a crash or silent stop — graceful termination with state preserved |
| F-23 | First budget-exceeded triggers auto-continue | New session started automatically — informational notification sent, no user action required |
| F-24 | Second budget-exceeded on same task triggers escalation | Orchestrator stops, user receives progress summary and options |
| F-25 | Budget-exceeded stop reason logged correctly | Session log `stop_reason` field set to `budget_exceeded` per stop reason taxonomy |
| F-26 | Per-agent-build review can flag misaligned budget fractions | Budget too high or too low for agent's expected workload flagged in review |

---

### PII redaction rule enforcement

| # | Test | Pass condition |
|---|------|---------------|
| P-1 | Log entries with sensitive data contain opaque IDs only | Sample agent run with simulated sensitive data produces logs with opaque IDs — no raw names, emails, phone numbers, or account numbers |
| P-2 | Error diagnostics with sensitive data contain opaque IDs only | Error context for sensitive-data tasks contains only opaque IDs |
| P-3 | /logs/ absent from all git commits | Logs directory not present in any commit |
| P-4 | Redaction rule present in every agent instructions file | Each agent's operating constraints section contains the redaction rule — confirmed present and not truncated |

---

### Blast radius check

| # | Test | Pass condition |
|---|------|---------------|
| B-1 | Scope declaration present in handoff envelope | Scope declaration is the first field in every handoff envelope before any file is written |
| B-2 | Hard gate fires for out-of-scope write directories | Write directory outside permitted directories triggers hard gate |
| B-3 | Hard gate does not fire for in-scope directories | All-in-scope write directories do not trigger hard gate |
| B-4 | Hard gate stops execution at all levels | No autonomy level bypasses the hard gate |
| B-5 | Soft gate fires for unusually broad scope | Orchestrator assessment of unusually broad scope triggers soft gate |
| B-6 | Soft gate requires user confirmation at Levels 1-3 | Soft gate confirmed by user before execution proceeds at Levels 1-3 |
| B-7 | Soft gate autonomously approved at Level 4 | Soft gate at Level 4 auto-approved by orchestrator with Informational log entry |
| B-8 | Handoff without scope declaration does not proceed | Handoff envelope missing scope declaration flagged as incomplete — execution does not proceed |

---

### Scale monitoring

| # | Test | Pass condition |
|---|------|---------------|
| SC-1 | Wizard asks all three scale questions | All three business-context questions asked and answered during wizard |
| SC-2 | Scale tier labeled as provisional | technical_architecture.md scale tier is explicitly labeled provisional |
| SC-3 | First-data advisory fires on first divergence | Advisory fires once on first production run where observed volume diverges from provisional tier |
| SC-4 | First-data advisory does not fire when consistent | No advisory fired when observed volume is consistent with provisional tier |
| SC-5 | Weekly scale drift check runs from first agent run | Drift check not deferred to higher levels |
| SC-6 | Scale-drift finding after 2+ consecutive divergent weeks | Finding raised after 2 or more consecutive weeks of one-tier sustained divergence — not after one week |
| SC-7 | Scale-drift finding routes correctly | Finding routes to issues log at High severity and to advisor queue |
| SC-8 | Scale tier requires user confirmation to change | No auto-update of scale tier — requires explicit user confirmation |

---

### Wizard interview sequence

| # | Test | Pass condition |
|---|------|---------------|
| WZ-1 | Vision document — all six categories asked | Vision interview covers purpose, goals, audience/outputs, scope boundary, constraints, and success criteria — none skipped |
| WZ-2 | Completeness check before vision draft | Follow-up asked for each genuinely absent category — not thin categories, only absent ones |
| WZ-3 | Completeness check one follow-up per category | Maximum one follow-up per absent category |
| WZ-4 | Vision draft presented with one-round framing | One-round limit stated before user responds — not imposed after |
| WZ-5 | Living document standard stated | "Good enough to build from" standard stated in one-round framing |
| WZ-6 | One revision round incorporated and confirmed | Wizard does not re-open for further iteration after one round |
| WZ-7 | Approach-level content carried forward | Content from vision interview carried to approach draft — not discarded, not re-requested |
| WZ-8 | Vision document on disk before approach phase | Vision document written and committed before wizard moves to approach |

---

### Rationale propagation (Level 3+)

| # | Test | Pass condition |
|---|------|---------------|
| R-1 | Level 3+ orchestrator consults prior records | Before building or modifying an agent at Level 3+, orchestrator consults rules library, advisor knowledge base, and prior build records |
| R-2 | Rationale propagation inactive at Levels 1-2 | No rationale propagation at Levels 1-2 — no operational history exists |

---

### Operational self-analysis

| # | Test | Pass condition |
|---|------|---------------|
| O-1 | /insights runs at closing orientation | Report generated, suggestions filtered for project relevance, only relevant suggestions presented to user |
| O-2 | /insights suggestions require user confirmation | Suggestions written to CLAUDE.md only after user confirms — not auto-applied |
| O-3 | Monthly operational review fires at correct cadence | Review fires at correct monthly interval — not skipped |
| O-4 | Monthly review reads all three log sources | Error log, QA log, and cost/efficiency log all read — none skipped |
| O-5 | Monthly review produces digest entry | Plain-language summary of top failure types, cost drivers, and friction patterns |
| O-6 | Monthly review does not trigger real-time alert | Review digest entry only — no real-time alert unless patterns warrant escalation through normal severity rules |

---

### Model-as-reviewer quality reviews

| # | Test | Pass condition |
|---|------|---------------|
| REV-1 | Post-wizard review runs as INTERNAL step before CLOSE-13 | Review runs after last CLOSE explanation and before closing orientation — not skipped, not user-optional |
| REV-2 | Post-wizard review uses High tier model | Model resolved from tier mapping in `project_instructions.md` |
| REV-3 | Post-wizard review sub-agent receives fresh context | No carry-over from wizard interview conversation |
| REV-4 | Post-wizard review reads all required inputs | All 5 foundation documents, system config files, agent roster, skill files, invocation scripts, cron config, CLAUDE.md, and session_bootstrap.md user answers |
| REV-5 | Post-wizard review checks all 9 criteria | Foundation document quality, architecture soundness, technical feasibility, vision-to-output alignment, agent roster/skill fitness, configuration consistency, security posture, completeness, non-technical readiness |
| REV-6 | Post-wizard review produces structured findings | Each finding includes: what the issue is, why it matters, which criterion, and whether mechanical or judgment |
| REV-7 | Post-wizard review mechanical findings auto-fixed | Fixed with plain-language explanation — no user input required |
| REV-8 | Post-wizard review judgment findings presented one at a time | User resolves conversationally in plain language |
| REV-9 | Post-wizard review is a soft gate | User can say "that's fine, move on" — finding logged but does not block wizard completion |
| REV-10 | Post-wizard review technical feasibility check | Anything infeasible within stated constraints flagged — spend ceiling, available integrations, model capabilities, scale tier |
| REV-11 | Post-wizard review token budget checked before spawning | If input exceeds threshold, inputs prioritized by value-per-token ranking (foundation docs first), scoped review logged |
| REV-12 | Post-wizard review input assembled as structured manifest | Provenance labels: file identity, what produced it, what to focus on |
| REV-13 | Post-wizard review is idempotent | Read-only — can be safely re-run on session resume without side effects |
| REV-14 | Post-wizard review failure triggers one retry | Second failure: wizard logs failure, informs user, proceeds to CLOSE-13 without review |
| REV-15 | Post-wizard review runs after Gate 2 health check | Health check first (structural, faster, cheaper), model review second (semantic) |
| REV-16 | Per-agent review runs after each agent build | Runs after build completes and before agent goes live — not skipped, not user-optional |
| REV-17 | Per-agent review uses High tier model with fresh context | Adversarial prompt, fresh context, High tier |
| REV-18 | Per-agent review checks all 4 criteria | Agent-readiness (routing phrase, output format, error codes, composable output), permission/scope alignment, integration correctness, skill quality |
| REV-19 | Per-agent review includes upstream/downstream agent specs | Integration correctness check has information needed to verify format matching |
| REV-20 | Per-agent review scoped to agent implementation | Does not re-review system design or foundation documents |
| REV-21 | Per-agent review mechanical findings auto-fixed with consequence language | Judgment findings include concrete consequence (e.g., "downstream agent will likely fail") |
| REV-22 | Per-agent review is a soft gate | Same user-has-final-say principle as post-wizard review |
| REV-23 | Per-agent review same failure/retry/idempotency behavior | Same patterns as post-wizard review — one retry, proceed on second failure |
| REV-24 | Phase-gate review specifies High tier model | Fresh-context adversarial review added to existing phase-gate process |
| REV-25 | Phase-gate review checks 5 criteria | System health trajectory, agent performance, configuration drift, security posture, readiness for next level |
| REV-26 | Phase-gate review reads all required inputs | All 7 documents, agent roster, recent logs (error, QA, cost), and rules library |
| REV-27 | Phase-gate review finding routing uses existing categories | "Act now" routes to advisor queue as Tier 1; "note for phase-gate" stages in `architectural_review_staging.md` |
| REV-28 | Phase-gate review same failure/retry behavior | One retry; proceed without High tier review on failure (existing system self-review still runs) |
| REV-29 | All three review prompts are first-class wizard artifacts | Written and tested in `/wizard/review_prompts/` with same rigor as interview files |

---

### Idempotency guidance (external integrations)

| # | Test | Pass condition |
|---|------|---------------|
| ID-1 | System CLAUDE.md includes idempotency principle | "Log what you did, check before repeating" for external state-modifying operations |
| ID-2 | Agent build prompts include idempotency guidance | Builder guided to consider idempotency for each external integration |
| ID-3 | Per-agent review checks idempotency for external integrations | Integration correctness criterion includes: "does the implementation handle retry safely?" |
| ID-4 | Agents with external integrations log operations with retry-check detail | Sufficient detail logged to determine on retry whether operation already completed |
| ID-5 | Tier 1 co-protected workflows flags high-stakes external operations | Payments, irreversible actions flagged independently of idempotency guidance |

---

### Future items register

| # | Test | Pass condition |
|---|------|---------------|
| FI-1 | future_items.md present after wizard build | Three sections present: date-triggered, condition-triggered, monitoring cadence |
| FI-2 | Orchestrator checks future_items.md at every session close | Check not skipped |
| FI-3 | Date-triggered items surfaced when date reached or passed | Not missed if system was offline on the exact date |
| FI-4 | Condition-triggered items surfaced when condition becomes true | Checked against current system state |
| FI-5 | One-time triggered items not re-surfaced | Marked as triggered after first surfacing |
| FI-6 | Recurring monitoring cadence items rescheduled | Next due date updated after surfacing |
| FI-7 | Due items pulled into next session context | Session bootstrap updated with due items |
| FI-8 | System CLAUDE.md includes future items operating rule | Rule: add to `future_items.md` when work reveals time-gated follow-up, condition-triggered dependency, or monitoring cadence |

---

### Session close enforcement

| # | Test | Pass condition |
|---|------|---------------|
| SCE-1 | Session close updates all four files in order | SESSION_STATE.md, session_bootstrap.md, work queue, session log — in order |
| SCE-2 | Session close runs on abnormal termination | Close runs for error, budget exceeded, or user abort — not skipped |
| SCE-3 | Orchestrator reserves budget/context for close | Task work stops before exhaustion to ensure close completes |
| SCE-4 | SESSION_STATE.md set to CLEAR when no task in progress | Correct state written at close |
| SCE-5 | Session log close entry includes stop reason | Stop reason from taxonomy included in close entry |
| SCE-6 | Incomplete close logged at High severity | Which files were not updated and why — logged |

---

### Voice and style preferences

| # | Test | Pass condition |
|---|------|---------------|
| VS-1 | voice_and_style.md present after wizard build | Seeded from user profile, notification verbosity, QA reporting style, and vision document voice |
| VS-2 | Wizard seeds voice_and_style.md without new questions | Derived from existing wizard answers — no additional interview questions |
| VS-3 | User-facing agents consult voice_and_style.md | Confirmed in invocation scripts for agents producing user-facing or external-facing output |
| VS-4 | Internal-only agents do not receive voice_and_style.md | Context scoping principle applied — internal agents excluded |
| VS-5 | User style preference updates voice_and_style.md | Orchestrator captures formatting or style preferences progressively |
| VS-6 | voice_and_style.md includes starter note | Note reads: "These are starting defaults... tell it when you like or don't like how something looks" |

---

## Agent-Specific Tests

*Added during the build phase. One section per agent, populated when the agent's first build prompt is executed.*

{{AGENT_SPECIFIC_TESTS}}
