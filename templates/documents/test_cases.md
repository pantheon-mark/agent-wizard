---
foundation_doc_type: test_cases
foundation_schema_version: v0.2
wizard_version_compatible: "{{WIZARD_VERSION}}"
managed_by: wizard
system_shape: "{{SYSTEM_SHAPE}}"
foundation_only_mode: "{{FOUNDATION_ONLY_MODE}}"
---

# Test Cases

*Validation criteria for the system the wizard builds. Five sections: four universal (apply to every system shape) plus one markdown-agent shape extension that renders only when the operator's system shape is `markdown-agents-on-claude-code`. Generated from the wizard's testing framework at setup. Tests run on the triggers listed under Validation Method. Results are written to the system's quality log.*

*Note: Wizard product tests (entries that verify the wizard itself behaves correctly during setup and operation) are NOT in this document. Those live in the build project's wizard testing framework. This file contains only tests that apply to the running system the wizard built.*

*Structural note: universal acceptance criteria are grouped into four pillars (Correctness / Reliability / Security / Operability) for navigability. The markdown agent validation matrix is grouped by functional area (Session Lifecycle / Agent Capabilities / System Coordination / Quality & Safety Guardrails). Grouping is presentation-only; no semantic change to any acceptance criterion.*

---

## Acceptance Criteria

*Universal acceptance criteria that apply to every system shape, organized into four pillars of system quality: Correctness, Reliability, Security, and Operability.*

### Pillar 1: Correctness

*Ensures the system produces the right outputs and behaves as intended.*

#### Input Validation

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-V-1 | Structural validation rejects malformed input | Malformed input rejected before reaching semantic check |
| AC-V-2 | Structural validation identifies failure type | Format, field, and encoding failures each identified correctly |
| AC-V-3 | Semantic validation runs after structural pass | Semantic check only runs when structural check passes |
| AC-V-4 | Semantic validation applies rules library | Rules library consulted for every semantic check |
| AC-V-5 | Hard pushback blocks input | Hard pushback stops input until it is corrected |
| AC-V-6 | Soft pushback allows operator confirmation | Soft pushback allows operator to confirm intent and proceed |
| AC-V-7 | Override logged with domain and rationale | Override logged; sensitivity setting unchanged |
| AC-V-8 | Sensitivity setting changes written to config | Sensitivity change written with rationale |
| AC-V-9 | External source failure logged and registry updated | External source validation failure logged at High severity and source registry updated |
| AC-V-10 | Repeated failures trigger source health investigation | Repeated external source failures trigger investigation workflow |
| AC-V-11 | No-rule semantic input routes to operator review | Input with no applicable rules library match routes to operator review queue |

#### Task Completion Enforcement

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-T-1 | Task completion checklist enforced before downstream propagation | Checklist verified before output is propagated to any downstream consumer (next component, external API, datastore commit, or shape-equivalent boundary) |
| AC-T-2 | Criticality tier thresholds enforced | Higher-tier failure halts dependent workflow; lower-tier flags and continues |
| AC-T-3 | System-level completion check against vision | Completed work checked for alignment with vision document |
| AC-T-4 | Document currency enforced | Change not logged as complete until document updates are written |

### Pillar 2: Reliability

*Ensures the system is resilient to failure, recovers gracefully, and operates predictably.*

#### Error Handling and Recovery

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-E-1 | Error detection and logging | All errors detected and recorded in the configured error log with severity and context |
| AC-E-2 | Recovery attempt sequence | System attempts recovery per configured threshold before escalating |
| AC-E-3 | Three-strikes escalation | Task escalates to operator after configured strike count — completed steps preserved |
| AC-E-4 | Halt criteria enforcement | Configured halt conditions stop all autonomous operations immediately |
| AC-E-5 | Cascading effect check execution | System checks downstream effects before treating a recovery as complete |
| AC-E-6 | Continue-with-flagging behavior | Lower-criticality failure flags and continues; higher-criticality failure stops the relevant workflow |

#### Atomicity, Checkpointing, and Retry Safety

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-A-6 | Output uses atomic write or transactional equivalent | Output operations use an atomicity primitive appropriate to the shape: temp-file-and-rename for filesystem stores; transaction commit for relational databases; idempotent API call with deduplication key for external services; or shape-equivalent |
| AC-A-7 | Progress marker written after output verified to durable store | Progress marker (checkpoint, sequence number, or shape-equivalent) written after the output is verifiably durable — not before |
| AC-A-8 | Retry resumes from first incomplete step | Retry behavior on partial completion resumes from the first not-yet-complete step; completed steps not re-executed |
| AC-A-9 | Retry on completed task passes idempotency check | A retry against a task that has already completed produces the same observable outcome without re-executing side effects |
| AC-A-10 | Three-strikes rule per step | Three-strikes applied per step — prior completed steps not re-run on later-step failure |

#### Idempotency for External Integrations

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-ID-1 | System instructions include idempotency principle | "Log what you did, check before repeating" for external state-modifying operations |
| AC-ID-2 | Components with external integrations log operations with retry-check detail | Sufficient detail logged to determine on retry whether operation already completed |
| AC-ID-3 | High-stakes external operations flagged independently | Payments, irreversible actions flagged independently of idempotency guidance |

### Pillar 3: Security

*Ensures the system protects sensitive data, manages credentials securely, and operates within defined boundaries.*

#### Security and Credentials

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-C-1 | Secrets never committed | All secret-bearing files absent from every commit |
| AC-C-2 | Credentials read from environment, not hardcoded | No hardcoded credential values in any system file |
| AC-C-3 | Credentials registry contains metadata only | Registry contains metadata — no credential values |
| AC-C-4 | Auto-refresh executes before expiry | Token refreshed before expiry for all auto-refreshable credentials |
| AC-C-5 | Auto-refresh failure triggers immediate alert | Auto-refresh failure fires real-time alert immediately |
| AC-C-6 | Credential expiry alert fires at lead time | Expiry alert fires at configured lead time — not after expiry |
| AC-C-7 | Rotation alert includes provider-specific instructions | Rotation alert instructions match the credential type and provider |
| AC-C-8 | No-expiry check fires at configured cadence | Confirmation check fires at configured cadence without being triggered manually |

#### PII Redaction

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-P-1 | Log entries with sensitive data contain opaque IDs only | Sample task with simulated sensitive data produces logs with opaque IDs — no raw names, emails, phone numbers, or account numbers |
| AC-P-2 | Error diagnostics with sensitive data contain opaque IDs only | Error context for sensitive-data tasks contains only opaque IDs |
| AC-P-3 | Logs absent from all version-control commits | Logs are not committed to source control by configuration (e.g., .gitignore entry, exclusion rule, or shape-equivalent) |
| AC-P-4 | Redaction rule present in every component's operating policy | Each component's operating policy, configuration, prompt, or equivalent — whatever surface the system shape uses to constrain component behavior — contains the redaction rule |

#### Permission Boundaries

*Principle of least privilege at component scope.*

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-A-1 | Permission boundary enforcement | Each component accesses only what its role authorizes |
| AC-A-2 | Storage access restriction | Component cannot access storage locations (directories, namespaces, datastores) outside its authorized set |
| AC-A-3 | External API restriction | Component cannot call APIs not authorized for its role |
| AC-A-4 | Command execution authority, where command execution exists | Component-initiated commands (shell, RPC, transaction, or equivalent if the shape uses command execution) respect current autonomy level authorization |
| AC-A-5 | Escalation on boundary exceeded | Boundary exceeded triggers escalation path immediately |

#### Security Audits

*Automated checks for common security concerns in system-produced artifacts.*

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-Q-1 | Security audit triggers on correct criteria | Audit fires for any of the qualifying criteria: external API call, cross-workspace access, external input acceptance, access control config, sensitive data handling |
| AC-Q-2 | Security audit does not trigger for internal-only artifacts | Internal artifact meeting none of the criteria does not trigger audit |
| AC-Q-3 | Minimum access scope check | Over-broad API scope requests and unnecessary directory access flagged |
| AC-Q-4 | Input boundary check | Unvalidated external input passed to commands, file writes, or API calls flagged |
| AC-Q-5 | Data containment check | Sensitive data in logs, unnecessary external services, or retained beyond operational lifetime flagged |
| AC-Q-6 | Critical finding quarantines artifact | Critical security finding stops artifact promotion to downstream consumers until resolved |
| AC-Q-7 | High finding routes to work queue | High security finding written to work queue without automatic quarantine |
| AC-Q-8 | Warning finding produces digest entry only | Warning finding appears in digest — no quarantine or work queue item |
| AC-Q-9 | Quarantine release requires explicit operator authorization | Quarantine not auto-released at any autonomy level |
| AC-Q-10 | All security audit results recorded durably | Audit results recorded in the configured durable audit store (filesystem log file, database table, observability sink, ticketing system, or shape-equivalent) regardless of finding severity |
| AC-Q-11 | Quarantined artifact excluded from automatic promotion | Quarantined artifact not committed, deployed, published, or propagated to downstream consumers until quarantine is lifted |
| AC-Q-12 | Security audit cannot be disabled | No configuration flag or autonomy level setting disables the security audit |
| AC-Q-13 | Security finding plain-language summary | Finding summary contains required elements: what the artifact does, what the concern is, what the proposed fix is |

### Pillar 4: Operability

*Ensures the system is manageable, observable, and controllable by a human operator.*

#### Human-in-the-Loop

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-L-1 | Tier 1 decisions intercepted and surfaced | Tier 1 decisions not auto-executed at any autonomy level |
| AC-L-2 | Stale decision threshold detection | Decision not resolved within threshold triggers follow-up |
| AC-L-3 | Pending decisions reflect current state | Open decisions accessible to operator; resolved decisions archived |
| AC-L-4 | Operations digest generation and delivery | Digest generated at configured cadence and delivered to operator via configured channel |
| AC-L-5 | Real-time alert delivery for Critical and High events | Alert delivered via configured channel for all Critical and High severity events |
| AC-L-6 | Advisor identification proposes relevant types per system shape | Operator confirms, removes, or adds advisor types; each confirmed advisor has a corresponding record in the operator's advisor reference (whatever surface the system shape uses to persist that reference) |

#### Alert Routing

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-N-1 | Critical events deliver real-time alert | Notification delivered via configured real-time channel for every Critical severity event |
| AC-N-2 | High events deliver real-time alert | Notification delivered via configured real-time channel for every High severity event |
| AC-N-3 | Alert template signal correct | ACTION NEEDED vs NO ACTION NEEDED correctly applied per alert type |
| AC-N-4 | Alert contains no raw log content | Alert plain-language translation contains no raw log content or internal file paths |
| AC-N-5 | Critical alerts always use full detail | Critical alerts ignore verbosity preference — always full detail |
| AC-N-6 | Every alert recorded in notification/audit log | Every alert written to the configured durable notification or audit log (filesystem log file, database table, observability sink, or shape-equivalent) |
| AC-N-7 | NO ACTION NEEDED alerts downgraded at higher autonomy | NO ACTION NEEDED alerts converted to digest entries at higher autonomy levels |

#### Cost Controls

*Spend thresholds, intensive-operation gating, periodic backstop review. Specific numbers (75/90/100% thresholds) are operator-configured; structural pattern is universal.*

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-F-1 | Spend ceiling configured at wizard setup | Spend ceiling, overage plan type, and intensive-operation threshold all present in system config |
| AC-F-2 | 75% threshold produces digest entry | 75% spend triggers digest entry — not a real-time alert |
| AC-F-3 | 90% threshold triggers High alert | 90% spend triggers real-time High severity alert |
| AC-F-4 | 100% ceiling stops system unconditionally | All autonomous operations halt at spend ceiling — no exceptions |
| AC-F-5 | Stop-the-system not auto-lifted | System remains stopped until explicit operator authorization |
| AC-F-6 | Cost/efficiency log written after every component run | Component, tokens, and cumulative total updated after each run |
| AC-F-7 | Periodic backstop review fires at cadence | Backstop review fires at correct interval — not skipped |

#### Scale Monitoring

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-SC-1 | Operator answers scale questions during wizard | Business-context questions asked and answered |
| AC-SC-2 | Scale tier labeled as provisional | Architecture doc scale tier is explicitly labeled provisional |
| AC-SC-3 | First-data advisory fires on first divergence | Advisory fires once on first production run where observed volume diverges from provisional tier |
| AC-SC-4 | First-data advisory does not fire when consistent | No advisory fired when observed volume is consistent with provisional tier |
| AC-SC-5 | Scale drift check runs from first system run | Drift check not deferred to higher autonomy levels |
| AC-SC-6 | Scale-drift finding after 2+ consecutive divergent weeks | Finding raised after 2 or more consecutive weeks of one-tier sustained divergence — not after one week |
| AC-SC-7 | Scale-drift finding routes correctly | Finding routes to issues log at High severity and to advisor queue |
| AC-SC-8 | Scale tier requires operator confirmation to change | No auto-update of scale tier — requires explicit operator confirmation |

#### Blast Radius

*Scope-declaration + write-permission gates on operation boundaries. Concept is universal; specific surface (handoff envelope, API request, transaction declaration, etc.) is shape-determined. Specific implementation lives in the markdown shape extension.*

| # | Acceptance criterion | Pass condition |
|---|---|---|
| AC-B-1 | Scope declaration present at every operation boundary | Each component-initiated operation (handoff, work request, API call, transaction, or shape-equivalent) declares its intended scope (target storage, external endpoints, sensitive-data classes touched) before any write occurs |
| AC-B-2 | Hard gate fires for out-of-scope write targets | Operation targeting a storage location, API endpoint, or boundary outside permitted set triggers hard gate |
| AC-B-3 | Hard gate does not fire for in-scope targets | All-in-scope operations do not trigger hard gate |
| AC-B-4 | Hard gate stops execution at all autonomy levels | No autonomy level bypasses the hard gate |
| AC-B-5 | Soft gate fires for unusually broad scope | Unusually broad declared scope triggers soft gate |
| AC-B-6 | Soft gate requires operator confirmation at lower autonomy | Soft gate confirmed by operator before execution proceeds at lower autonomy levels |
| AC-B-7 | Soft gate auto-approved at highest autonomy | Soft gate at highest level auto-approved with informational log entry |
| AC-B-8 | Operation without scope declaration does not proceed | Operation missing scope declaration flagged as incomplete — execution does not proceed |

---

## Test Pyramid

*Layer distribution chosen by the operator per system shape and risk profile. The pyramid is a planning surface; specific layer ratios are operator-set within `validation_method` below.*

| Layer | Purpose | Typical scope |
|---|---|---|
| **Unit (or shape-equivalent)** | Test smallest verifiable behavior in isolation | Pure functions / single-component prompt behavior / individual rule logic |
| **Integration** | Test boundaries between components | Handoffs / data exchanges / cross-component invariants |
| **End-to-end (or shape-equivalent)** | Test full workflow from input to output | Full operator scenarios / complete task flows / production-like data paths |

*Operator selects emphasis: e.g., heavy unit + light e2e for cost-bounded systems; balanced unit + integration + e2e for higher-stakes systems. Recorded in `validation_method` below.*

---

## Validation Method

*How each acceptance criterion above is verified concretely. Minimum requirement: every criterion in this document specifies a verification approach. Tooling chosen per layer and per operator deployment surface; cost-aware.*

### Test triggers

*When validation runs. Operator-configurable.*

| Trigger | Scope |
|---------|-------|
| After any error recovery attempt | Affected component and its dependencies |
| After any code or configuration change | Changed component and its dependencies |
| After new component or skill added | New component plus integration with existing components |
| After system drift alignment fix applied | Fixed component and downstream dependencies |
| After source health issue resolved | Source integration and downstream data flows |
| After significant system output | Output pipeline from source to delivery |
| On periodic schedule — cadence wizard-configured | Full system |
| After any foundational document update | Components governed by that document |
| After autonomy level authorization change | All components affected by expanded authorization |
| After any credential rotation | All components and integrations that use that credential |
| After dependency update — successful or rolled back | All components and integrations that depend on updated package |
| After phase-gate architectural review completes | All foundation documents reviewed, findings categorized |
| After context-window or saturation threshold updated | Pre-flight and mid-execution detection behavior for all components |

### Method selection per layer

| Layer | Approach |
|---|---|
| **Unit** | Tooling per shape: pytest / jest / shell scripts / Claude Code skill replay / etc. Operator chooses based on shape's ecosystem. |
| **Integration** | Boundary verification: schema validators / contract tests / handoff envelope structural checks. Tooling matches deployment surface. |
| **End-to-end** | Workflow replay: realistic scenario inputs with assertion on full output. May be manual (operator walkthrough) or automated (recorded scenario replay). |

### Verification approach per acceptance criterion

*Default: each AC-X-N criterion above lists its pass condition; verification approach is one of:*

- **Automated test** — runs on triggers above; result written to quality log
- **Structural check** — runs at component activation or change-set verification
- **Periodic audit** — runs at configured cadence; result in digest
- **Manual operator review** — operator confirms at phase-gate

*The wizard generates a specific verification table for each acceptance criterion at system build time based on operator's shape + tooling preferences. Verification details are added to this document when the build phase populates them.*

### Results

*All test results write to the system's quality log. Failure paths trigger the alert routing acceptance criteria above (AC-N-1 through AC-N-7).*

---

## Markdown Agent Validation Matrix

*Markdown-agents-on-claude-code-shape-specific tests. This section renders only when `system_shape: markdown-agents-on-claude-code`. For other shapes (python-service, node-ui, hosted-cloud, mixed), this section is absent.*

*Tests are grouped by functional area for navigability: Session Lifecycle & State Management / Agent Capabilities & Behavior / System Coordination & Integration / Quality & Safety Guardrails. Grouping is presentation-only; no semantic change to any test row.*

### Session Lifecycle & State Management

*Covers how an agent session starts, runs, checkpoints, and terminates cleanly.*

#### Session Startup Sequence

| # | Test | Pass condition |
|---|---|---|
| MA-S-1 | Startup reads correct files in order | All six startup files read in correct order before status is presented |
| MA-S-2 | Working files contain only active items | No resolved items in working files at startup |
| MA-S-3 | Critical alert tight loop enforces no-proceed | Operator cannot skip to briefing while Critical alert is unresolved |
| MA-S-4 | Blocked critical alert resurfaces at next startup | Unresolved Critical alert leads next session |
| MA-S-5 | Deferred alert relevance check runs automatically | Relevance check runs before surfacing deferred alerts |
| MA-S-6 | Superseded deferred alerts auto-closed | Alerts superseded by later events auto-closed with log entry |
| MA-S-7 | Deferred alert re-escalation threshold triggers flag | Alert escalated as overdue after configured deferral count |
| MA-S-8 | Execution plan chunks sized within session limits | Chunks sized before execution begins — no oversized chunks |
| MA-S-9 | Mid-session state save writes plan state file | State file written with resume command when mid-session save triggers |
| MA-S-10 | Resumed session continues from correct chunk | Resumes from correct chunk — no re-execution of completed chunks |
| MA-S-11 | Execution plan state file cleared on completion | State file deleted when plan completes successfully |
| MA-S-12 | Items archived immediately on resolution | Resolved items moved to archive immediately — not batched to session end |
| MA-S-13 | Notification log rolling archive runs daily | 7-day rolling window enforced; older entries moved to archive |
| MA-S-14 | Full status briefing only after adjudication | Full briefing not presented until all Critical and deferred alerts are adjudicated |
| MA-S-15 | Runtime health check runs every session | Health check runs after orientation and before work begins — not skipped |
| MA-S-16 | Health check validates all credentials | All credentials validated — expired or invalid detected |
| MA-S-17 | Health check validates external service integrations | All external integrations checked for reachability — unreachable services detected |
| MA-S-18 | Health check validates agent prompt files | All agent prompt files confirmed present and intact — missing or corrupted detected |
| MA-S-19 | Health check validates no configuration drift | System files match expected state — drift detected |
| MA-S-20 | Health check partial failure blocks dependent tasks only | Independent tasks proceed; only dependent tasks blocked |
| MA-S-21 | Health check full failure blocks all work | All work blocked with plain-language explanation of all failures |
| MA-S-22 | Health check results recorded in session log | Results recorded as standing section in session log |
| MA-S-23 | Health check failure message includes plain-language action instructions | No raw error output — operator sees actionable instructions |

#### Context & Complexity Management (Checkpoints)

*Pre-flight sizing, mid-execution checkpoints, retry-resume behavior.*

| # | Test | Pass condition |
|---|---|---|
| MA-A-14 | Pre-flight size assessment runs before every execution | Size estimate computed and threshold checked before agent runs |
| MA-A-15 | Pre-flight decomposition triggers at threshold | Decomposition fires when estimate exceeds pre-flight threshold |
| MA-A-16 | Decomposition plan written before sub-task 1 | Decomposition plan written to `/agents/checkpoints/` before any sub-task executes |
| MA-A-17 | Mid-execution checkpoint triggers at threshold | Checkpoint fires when context consumption exceeds mid-execution threshold |
| MA-A-18 | Checkpoint file written correctly | Checkpoint written to `/agents/checkpoints/` with completed steps, remaining steps, and resume prompt |
| MA-A-19 | Lower-autonomy pre-flight alert fires | At lower autonomy levels, pre-flight decomposition fires real-time alert with paste-ready Step 1 prompt |
| MA-A-20 | Higher-autonomy pre-flight proceeds silently | At higher autonomy levels, pre-flight decomposition proceeds silently with digest entry written |
| MA-A-21 | Lower-autonomy mid-execution alert fires | At lower autonomy levels, mid-execution checkpoint fires real-time alert with paste-ready resume prompt |
| MA-A-22 | Higher-autonomy mid-execution resumes silently | At higher autonomy levels, mid-execution checkpoint resumes in next invocation silently |
| MA-A-23 | Checkpoint and decomposition files cleared on completion | Files cleared when task completes successfully |
| MA-A-24 | Context window limit reads from project_instructions.md | Context window limit not hardcoded — read at every invocation |
| MA-A-25 | Saturation thresholds read from project_instructions.md | Both thresholds read from config — default applied correctly |
| MA-A-26 | Threshold adjustment requires operator authorization | New threshold not written until operator authorizes |
| MA-A-27 | Mid-execution detection triggers on quality degradation | Detection fires on output quality degradation signals in addition to the context percentage threshold |
| MA-A-28 | Interactive session claims gate before editing protected files | Gate claimed before editing protected directories |
| MA-A-29 | Interactive session gate released after edit | Gate released after edit completes — no orphaned claims |
| MA-A-30 | Complexity assessment runs before every task | Signals checked before every agent task — decomposition triggered only when signal present |
| MA-A-31 | No complexity signals — runs directly | Task with no complexity signals runs directly — no plan written |
| MA-A-32 | Complexity signal triggers plan before step 1 | Any complexity signal triggers plan written to `/agents/checkpoints/` before step 1 executes |
| MA-A-33 | Lower-autonomy plan approved before step 1 | Plan surfaced and approved once before step 1 executes |
| MA-A-34 | Lower-autonomy step results reported after each step | Step results reported after each step — no per-step approval prompt |
| MA-A-35 | Higher-autonomy plan and execution proceed silently | Plan and execution proceed silently — digest entry on completion |
| MA-A-36 | Completed checkpoints retained until phase-gate | DONE checkpoints retained until next phase-gate review, then pruned |
| MA-A-37 | Failed/incomplete checkpoints never auto-pruned | Failed or incomplete checkpoints retained until manually resolved |
| MA-A-38 | Step idempotency enforced even with partial checkpoint | Re-running a COMPLETE step produces the same output as the original |
| MA-A-39 | SG-1 and SG-3 stacking behavior | Context threshold + complexity signals stack: SG-1 pre-flight runs first and splits into sub-tasks; each sub-task then runs SG-3 complexity assessment independently |

#### Session Close Enforcement

| # | Test | Pass condition |
|---|---|---|
| MA-SCE-1 | Session close updates all four files in order | SESSION_STATE.md, session_bootstrap.md, work queue, session log — in order |
| MA-SCE-2 | Session close runs on abnormal termination | Close runs for error, budget exceeded, or operator abort — not skipped |
| MA-SCE-3 | Orchestrator reserves budget/context for close | Task work stops before exhaustion to ensure close completes |
| MA-SCE-4 | SESSION_STATE.md set to CLEAR when no task in progress | Correct state written at close |
| MA-SCE-5 | Session log close entry includes stop reason | Stop reason from taxonomy included in close entry |
| MA-SCE-6 | Incomplete close logged at High severity | Which files were not updated and why — logged |

### Agent Capabilities & Behavior

*Covers the core runtime behaviors and guardrails of individual agents.*

#### Identity and Permissions

*Markdown-shape-specific component invocation (scripts, cron, session-entry, stop-reason taxonomy, maintenance mode).*

| # | Test | Pass condition |
|---|---|---|
| MA-A-6 | Invocation script loads prompt file | Agent invocation script loads prompt file before invoking Claude — no invocation without guardrails |
| MA-A-7 | Invocation script aborts on missing prompt | If prompt file is missing, invocation script aborts and logs Critical |
| MA-A-8 | Invocation script disk I/O correctness | Inputs read from correct disk locations; outputs written to correct disk locations |
| MA-A-9 | Cron job triggers on correct schedule | Cron job fires the scheduled Orchestrator run on its configured schedule; the Orchestrator routes to the configured agents (direct specialist scheduling is a declared exception) |
| MA-A-10 | Headless agent run completes cleanly | Headless run completes, writes output to disk, and exits without error |
| MA-A-11 | Session entry scripts execute without error | All three start-session.sh flag variants complete without error after wizard setup |
| MA-A-12 | --resume flag initiates resume startup | `start-session.sh --resume` runs the resume startup sequence |
| MA-A-13 | --resume --alert flag initiates alert-response startup | `start-session.sh --resume --alert` runs the alert-response startup sequence |
| MA-A-40 | Every agent session logs a stop reason on termination | No session ends without a `stop_reason` field in the session log |
| MA-A-41 | Stop reason correctly assigned per taxonomy | `completed` / `budget_exceeded` / `error` / `timeout` / `user_cancelled` / `deferred` per taxonomy |
| MA-A-42 | Deferred stop reason distinct from completed | `deferred` means agent stopped before finishing; `completed` means agent finished |
| MA-A-43 | QA agent reads stop reasons as first-pass signal | `budget_exceeded` and `error` stop reasons trigger investigation check by QA agent |
| MA-A-44 | Orchestrator responds appropriately to stop reasons | `budget_exceeded` triggers continuation or escalation; `error` triggers investigation before retry |
| MA-A-45 | Maintenance mode causes the scheduled run to skip and log | The scheduled Orchestrator run is skipped and logged when the session lock (`maintenance_mode.md`) is present — not silent failure |
| MA-A-46 | Maintenance mode cleared at session end | Maintenance mode file deleted before session exits |
| MA-A-47 | Stale maintenance mode detected and cleared at startup | Stale file auto-cleared and Warning alert sent at session startup |

#### Auto-correct Behavior

| # | Test | Pass condition |
|---|---|---|
| MA-AC-1 | Scenario 1 fix followed by targeted verification | Autonomous fix immediately followed by targeted verification test of affected component |
| MA-AC-2 | Scenario 2 fix blocked before applying | Fix requiring approval not executed until operator approves |
| MA-AC-3 | Scenario 2 pre-authorized pattern applies without fresh approval | Pre-authorized fix pattern applied without requiring re-approval |
| MA-AC-4 | Scenario 2 novel fix still requires approval at highest autonomy | Genuinely novel fix still surfaces for approval even at highest autonomy |
| MA-AC-5 | Scenario 3 research consults all sources | Research step consults rules library, foundational docs, and audit trail before surfacing question |
| MA-AC-6 | Scenario 3 surfaces one targeted question | Exactly one targeted question surfaced — not a list |
| MA-AC-7 | Three-strikes rule enforced | Three failed attempts stops automated recovery regardless of scenario |
| MA-AC-8 | Tier 1 boundary enforced | Fix touching Tier 1 domain surfaces for approval at every autonomy level |
| MA-AC-9 | Guardrail-touching fix surfaces for approval | No guardrail-touching fix is auto-applied at any level |

#### Rationale Propagation & Self-Analysis

| # | Test | Pass condition |
|---|---|---|
| MA-R-1 | Higher-autonomy orchestrator consults prior records | Before building or modifying an agent at higher autonomy, orchestrator consults rules library, advisor knowledge base, and prior build records |
| MA-R-2 | Rationale propagation inactive at lower autonomy | No rationale propagation at lower autonomy — no operational history exists |
| MA-O-1 | /insights runs at closing orientation | Report generated, suggestions filtered for project relevance, only relevant suggestions presented |
| MA-O-2 | /insights suggestions require operator confirmation | Suggestions written to CLAUDE.md only after operator confirms — not auto-applied |
| MA-O-3 | Monthly operational review fires at correct cadence | Review fires at correct monthly interval — not skipped |
| MA-O-4 | Monthly review reads all three log sources | Error log, QA log, and cost/efficiency log all read |
| MA-O-5 | Monthly review produces digest entry | Plain-language summary of top failure types, cost drivers, and friction patterns |
| MA-O-6 | Monthly review does not trigger real-time alert | Review digest entry only — no real-time alert unless patterns warrant escalation through normal severity rules |

#### Voice and Style

| # | Test | Pass condition |
|---|---|---|
| MA-VS-1 | voice_and_style.md present after wizard build | Seeded from operator profile, notification verbosity, QA reporting style, and vision document voice |
| MA-VS-2 | Wizard seeds voice_and_style.md without new questions | Derived from existing wizard answers — no additional interview questions |
| MA-VS-3 | User-facing agents consult voice_and_style.md | Confirmed in invocation scripts for agents producing user-facing or external-facing output |
| MA-VS-4 | Internal-only agents do not receive voice_and_style.md | Context scoping principle applied — internal agents excluded |
| MA-VS-5 | Operator style preference updates voice_and_style.md | Orchestrator captures formatting or style preferences progressively |
| MA-VS-6 | voice_and_style.md includes starter note | Note reads: "These are starting defaults... tell it when you like or don't like how something looks" |

### System Coordination & Integration

*Covers how agents interact with each other, external services, and foundational documents.*

#### Handoff and Coordination

| # | Test | Pass condition |
|---|---|---|
| MA-H-1 | Handoff envelope format validation | Each agent produces a correctly structured handoff envelope |
| MA-H-2 | Gate claim and release behavior | Gate is claimed before work begins and released after — no orphaned claims |
| MA-H-3 | Gate conflict detection and resolution | Two agents attempting simultaneous access produce a conflict, one is queued |
| MA-H-4 | Idempotency — agent does not re-execute completed work | Re-running a completed task produces the same output without re-executing |
| MA-H-5 | Orchestration model routing — correct agent receives correct work | Each work item routes to the correct agent per the confirmed orchestration model |
| MA-H-6 | Parallel fan-out merge/coordinator gate | Parallel agents fan out and merge correctly — coordinator gate holds until all complete |

#### Git and Version Control

| # | Test | Pass condition |
|---|---|---|
| MA-G-1 | Auto-commit fires for every defined significant event | No significant events trigger without a corresponding commit |
| MA-G-2 | Auto-commit message format correct | Commit message contains event type, plain-language description, and audit trail reference |
| MA-G-3 | .env never in any commit | `.env` absent across all test commits |
| MA-G-4 | Session cookies never in any commit | `/security/session_cookies/` absent across all test commits |
| MA-G-5 | Logs never in any commit | `/logs/` absent from all commits — permanently excluded |
| MA-G-6 | Session-close commit captures all uncommitted changes | Session-close commit contains all changes not covered by event-triggered commits |
| MA-G-7 | Auto-commit failure fires High alert immediately | Auto-commit failure triggers real-time High severity alert |
| MA-G-8 | Routine rollback presents plain-language diff | No raw git output surfaced — plain language only |
| MA-G-9 | Routine rollback requires operator approval | Rollback not executed until operator approves |
| MA-G-10 | Critical rollback follows full approval sequence | Critical rollback not treated as routine — full approval sequence enforced |
| MA-G-11 | Critical rollback impact summary covers all downstream inconsistencies | Summary identifies all files affected by the rollback |
| MA-G-12 | Bad-state recovery saves progress after each approved step | Progress written to disk after each approved step |
| MA-G-13 | Bad-state recovery resumes from saved progress | Recovery resumes from correct saved step if session ends mid-recovery |
| MA-G-14 | Log rotation triggers at threshold | No log file grows beyond its configured size limit |
| MA-G-15 | Log rotation commits archive and new file atomically | Rotation produces a single atomic commit |
| MA-G-16 | Rotated logs land in /archive/logs/ with timestamp | Rotated file appears at `/archive/logs/` with correct timestamp suffix |
| MA-G-17 | Archived log cleanup requires operator approval | Archived log deletion surfaced in digest and requires explicit operator approval |
| MA-G-18 | Daily scheduled commit fires when no session occurs | Log files committed by daily scheduled commit when no session has occurred that day |

#### Document Update Mechanism

| # | Test | Pass condition |
|---|---|---|
| MA-D-1 | Change event correctly categorized | Change categorized against the document impact map correctly |
| MA-D-2 | Impact map identifies all affected documents | No gaps in affected document identification |
| MA-D-3 | Triggered update completes before change logged as done | Change not logged complete until all triggered updates are written |
| MA-D-4 | Three-part change summary generated | Summary contains trigger, assessment, what changed |
| MA-D-5 | Change summary delivered in digest | Summary appears in digest — not as a real-time alert |
| MA-D-6 | Periodic sweep detects inconsistencies | Sweep identifies document gaps and inconsistencies |
| MA-D-7 | Periodic sweep fixes resolved automatically | Resolved inconsistencies fixed using same sequence as triggered updates |
| MA-D-8 | Vision document update exception fires | Vision document change surfaced to operator — not auto-updated |
| MA-D-9 | Roadmap scope exception fires | Roadmap scope change surfaced to operator — not auto-updated |
| MA-D-10 | Partial update logged correctly | Completed parts and pending decision both recorded for partial updates |
| MA-D-11 | Impact map updated when new category encountered | New change category adds corresponding entry to impact map |
| MA-D-12 | Impact map update recorded in audit trail | Impact map change has audit trail entry |
| MA-D-13 | Impact map initialization presented at wizard setup | Operator sees the initial impact map in plain language during wizard setup |

#### External Dependencies (Credentials, Models, MCP)

| # | Test | Pass condition |
|---|---|---|
| MA-C-1 | .gitignore for .env present before .env created | `.gitignore` entry for `.env` confirmed before `.env` file is created |
| MA-C-2 | Session cookies never committed | `/security/session_cookies/` absent from all git commits |
| MA-C-3 | Proactive session refresh executes before expiry | Session refreshed before expiry where lifetime is known |
| MA-C-4 | Reactive session refresh retries operation | Operation retried automatically after reactive refresh |
| MA-C-5 | Session lifetime recorded after first reactive refresh | Lifetime recorded and used for proactive refresh on subsequent sessions |
| MA-C-6 | Automated login navigates and captures cookie | Login navigates correct URL, fills credentials from .env, captures cookie |
| MA-C-7 | Automated login failure identifies failure mode | Login failure correctly identifies the cause in plain language |
| MA-C-8 | Automated login failure halts and alerts | Login failure stops retries immediately and sends real-time alert |
| MA-C-9 | .gitignore manifest updated when new type introduced | Manifest updated automatically when new file type added to .gitignore |
| MA-C-10 | Playwright present and functioning | Playwright dependency verified after installation and after any system update |
| MA-MT-1 | Agent prompts use tier names only | No hardcoded model strings in any agent file |
| MA-MT-2 | Architectural review checks mapping currency | Mapping check not skipped in architectural review |
| MA-MT-3 | Deprecated model string classified as "act now" | Deprecated string triggers real-time High alert |
| MA-MT-4 | Stale non-deprecated mapping classified as "note for phase-gate" | Stale mapping written to staging file — not escalated as real-time alert |
| MA-MT-5 | Mapping update requires operator authorization | Mapping not updated until operator authorizes |
| MA-MT-6 | Capability modifier appended to High tier | Extended thinking or equivalent modifier correctly appended when specified |
| MA-MT-7 | start-session.sh includes --model flag | `start-session.sh` contains `--model` with resolved model name from High tier |
| MA-MT-8 | Every agent invocation script includes --model flag | Each script in `/agents/scripts/` contains `--model` with correct tier-resolved model name |
| MA-MT-9 | Build prompts reference start-session.sh for model | No build prompt tells operator to select a model manually — all reference `./start-session.sh` |
| MA-M-1 | MCP call failure triggers local output fallback | Skill completes logic and writes findings to disk even when MCP call fails |
| MA-M-2 | Plain-language action prompt fires on first MCP failure | Digest entry explains what was found, why it couldn't be delivered, and what to do manually |
| MA-M-3 | Degradation alert fires after 3 failures in 24 hours | High severity alert fires after 3 failures from same MCP source within 24-hour window — not on first failure |
| MA-M-4 | Degradation alert does not fire for failures spanning 24 hours | 3 failures spanning more than 24 hours do not trigger degradation alert |
| MA-M-5 | Internal-only skills have no degradation logic | Skills with no MCP calls do not include degradation logic |
| MA-M-6 | Degradation behavior identical at all autonomy levels | No level bypasses local fallback |

### Quality & Safety Guardrails

*Covers the mechanisms that enforce quality, financial, and operational safety.*

#### Financial Guardrails

*Markdown-shape implementation: intensive operations + autonomy-ladder framing + per-agent session budgets. Universal cost-control concepts (75/90/100% thresholds, stop-the-system, cost/efficiency log, periodic backstop) live in Acceptance Criteria § Cost Controls above (AC-F-1 through AC-F-7).*

| # | Test | Pass condition |
|---|---|---|
| MA-F-1 | Hard gate at lower autonomy for intensive operations | Every intensive operation surfaces for approval at lower autonomy levels regardless of threshold |
| MA-F-2 | Soft gate at higher autonomy below threshold | Intensive operations below threshold proceed without approval at higher autonomy levels |
| MA-F-3 | Soft gate at higher autonomy above threshold | Intensive operations above threshold surface for approval at higher autonomy levels |
| MA-F-4 | Phase-gate review runs before phase advancement proposal | Review not skippable |
| MA-F-5 | Phase-gate covers all foundation documents | All foundation documents checked for currency and correctness |
| MA-F-6 | Phase advancement blocked until findings cleared | Advancement blocked until all must-resolve findings are confirmed resolved |
| MA-F-7 | Event-triggered review fires on correct triggers | Review fires for significant error cluster, major integration, security incident, cost deviation |
| MA-F-8 | "Act now" findings route to advisor queue | Act-now findings trigger Tier 1 decision and real-time High alert |
| MA-F-9 | "Note for phase-gate" findings write to staging | Staged findings written to staging file — not advisor queue |
| MA-F-10 | Staged findings incorporated at next phase-gate | No staged finding missed in next phase-gate review |
| MA-F-11 | Phase-gate retrospective runs | Calibration signal captured as part of every phase-gate |
| MA-F-12 | Calibration feedback writes rules library entry | Rules library entry written for affected finding type after feedback |
| MA-F-13 | Per-agent session budget set at invocation | Budget amount derived from spend ceiling and agent workload fraction |
| MA-F-14 | Agent approaching budget initiates wrap-up mode | Progress summarized, state persisted, remaining work reported |
| MA-F-15 | Agent exceeding budget terminates gracefully | Graceful termination with state preserved |
| MA-F-16 | First budget-exceeded triggers auto-continue | New session started automatically — informational notification sent, no operator action required |
| MA-F-17 | Second budget-exceeded on same task triggers escalation | Orchestrator stops, operator receives progress summary and options |
| MA-F-18 | Budget-exceeded stop reason logged correctly | Session log `stop_reason` field set to `budget_exceeded` per stop reason taxonomy |
| MA-F-19 | Per-agent-build review can flag misaligned budget fractions | Budget too high or too low for agent's expected workload flagged in review |

#### QA Agent and Validation Gates

| # | Test | Pass condition |
|---|---|---|
| MA-Q-1 | Agent local quality gate before handoff | Each agent runs its quality gate before writing the handoff envelope |
| MA-Q-2 | QA agent independence from production pipeline | QA agent cannot modify production outputs — read access only |
| MA-Q-3 | Confidence flagging on uncertain outputs | Uncertain outputs flagged per configured threshold |
| MA-Q-4 | Confidence flagging threshold reads from project_instructions.md | Threshold not hardcoded; default applied correctly when no operator setting present |
| MA-Q-5 | Rules library check on new outputs | Each output checked against the rules library before handoff |
| MA-Q-6 | Source health monitoring — structural change detection | Structural change to a source detected and reported |
| MA-Q-7 | Source health monitoring — access change detection | Access change to a source detected and reported |
| MA-Q-8 | Investigation workflow spawning and reporting | High-severity source health event triggers investigation workflow and written report |
| MA-V-1 | Validation gate config written to disk | `validation_gate_config.md` present and correct after wizard completes |
| MA-V-2 | All validation events written to validation log | Every gate event written to `/logs/validation_log.md` |
| MA-V-3 | Gate silent at higher autonomy for calibrated domains | Structural passes and calibrated-domain soft pushbacks operate silently at higher autonomy levels |
| MA-V-4 | Agent-to-agent handoffs bypass validation gate | Handoffs between agents do not pass through the validation gate |
| MA-V-5 | Advisor interview guide written to disk | Generated interview guide written to `/advisor/interview-guides/` |
| MA-V-6 | Transcript extraction produces structured knowledge base entries | Structured entries produced with speaker labels and timestamps for `advisor_knowledge_base.md` |
| MA-V-7 | Advisor knowledge base entry written with required fields | Entry contains advisor, date, context, rule, conditions, review flag, and source decision |
| MA-V-8 | Advisor knowledge base entry applied correctly | Agent applies rule when situation matches, writes audit log entry |
| MA-V-9 | Review-flagged entry surfaces on correct date | Entry appears in digest on configured review date |
| MA-V-10 | Simple path closes pending decision correctly | Simple path closes with operator summary input — no interview guide required |

#### Model-as-Reviewer Quality Reviews

| # | Test | Pass condition |
|---|---|---|
| MA-REV-1 | Per-component review runs after each component build | Runs after build completes and before component goes live — not skipped |
| MA-REV-2 | Per-component review uses High tier model with fresh context | Adversarial prompt, fresh context, High tier |
| MA-REV-3 | Per-component review checks readiness criteria | Routing phrase, output format, error codes, composable output / permission/scope alignment / integration correctness / skill quality |
| MA-REV-4 | Per-component review includes upstream/downstream specs | Integration correctness check has information needed to verify format matching |
| MA-REV-5 | Per-component review scoped to component implementation | Does not re-review system design or foundation documents |
| MA-REV-6 | Per-component review mechanical findings auto-fixed | Fixed with plain-language explanation — no operator input required |
| MA-REV-7 | Per-component review judgment findings include concrete consequence | Judgment findings include concrete consequence (e.g., "downstream component will likely fail") |
| MA-REV-8 | Per-component review is a soft gate | Operator can say "that's fine, move on" — finding logged but does not block |
| MA-REV-9 | Per-component review same failure/retry/idempotency behavior | One retry, proceed on second failure |
| MA-REV-10 | Phase-gate review specifies High tier model | Fresh-context adversarial review added to existing phase-gate process |
| MA-REV-11 | Phase-gate review checks all criteria | System health trajectory, component performance, configuration drift, security posture, readiness for next level |
| MA-REV-12 | Phase-gate review reads all required inputs | All foundation documents, component roster, recent logs, and rules library |
| MA-REV-13 | Phase-gate review finding routing uses existing categories | "Act now" routes to advisor queue as Tier 1; "note for phase-gate" stages |
| MA-REV-14 | Phase-gate review same failure/retry behavior | One retry; proceed without High tier review on failure |
| MA-REV-15 | All review prompts are first-class wizard artifacts | Written and tested in `/wizard/review_prompts/` with same rigor as interview files |

#### Future Items Register

| # | Test | Pass condition |
|---|---|---|
| MA-FI-1 | future_items.md present after wizard build | Three sections present: date-triggered, condition-triggered, monitoring cadence |
| MA-FI-2 | Orchestrator checks future_items.md at every session close | Check not skipped |
| MA-FI-3 | Date-triggered items surfaced when date reached or passed | Not missed if system was offline on the exact date |
| MA-FI-4 | Condition-triggered items surfaced when condition becomes true | Checked against current system state |
| MA-FI-5 | One-time triggered items not re-surfaced | Marked as triggered after first surfacing |
| MA-FI-6 | Recurring monitoring cadence items rescheduled | Next due date updated after surfacing |
| MA-FI-7 | Due items pulled into next session context | Session bootstrap updated with due items |
| MA-FI-8 | System CLAUDE.md includes future items operating rule | Rule: add to `future_items.md` when work reveals time-gated follow-up, condition-triggered dependency, or monitoring cadence |

### Agent-Specific Tests

*Added during the build phase. One section per agent, populated when the agent's first build prompt is executed.*

{{AGENT_SPECIFIC_TESTS}}
