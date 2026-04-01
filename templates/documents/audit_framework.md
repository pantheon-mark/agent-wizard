# Audit Framework

*Operational document — managed by the system. Defines the four audit types, their triggers, cadences, and processes. Agents reference this document before conducting audits.*

---

## Security Audits

**Trigger:** Runs on every agent-produced integration artifact. Cannot be disabled. Runs at all four autonomy levels.

**Qualifying criteria (any one triggers the audit):**

1. External API call — artifact makes a call to an external API
2. Cross-workspace access — artifact accesses files or data outside its declared scope
3. External input acceptance — artifact accepts or processes input from an external source
4. Access control configuration — artifact configures or modifies access controls
5. Sensitive data handling — artifact processes, stores, or transmits sensitive or personal data

**Three-check model:**

| Check | What it covers | Critical finding | High finding | Warning finding |
|-------|----------------|-----------------|--------------|-----------------|
| Minimum access scope | Flags over-broad API scope or unnecessary directory access | Agent requests write access to entire filesystem | Agent reads more directories than needed for the task | Minor scope excess that does not affect data integrity |
| Input boundary validation | Flags unvalidated external input passed to commands, file writes, or API calls | Direct SQL or command injection risk | Unvalidated input reaches file write | Unvalidated input logged but not propagated |
| Sensitive data containment | Flags sensitive data in logs, unnecessary external services, or retained beyond operational lifetime | Raw PII in log entries | Sensitive data passed to unnecessary service | Sensitive data retained longer than needed but not exposed |

**Finding actions:**

| Severity | Action |
|----------|--------|
| Critical | Quarantine artifact — not promoted to downstream agents until finding resolved. Quarantine requires explicit user authorization to lift. |
| High | Route finding to work queue. Orchestrator notified. No automatic quarantine. |
| Warning | Digest entry only. No quarantine. No work queue item. |

*At Levels 1-2, Critical and High findings both quarantine automatically. At Levels 3-4, Critical quarantines; High routes to work queue without quarantine.*

---

## Log Audits

**Trigger:** Runs on each log rotation event and as part of the periodic drift analysis sweep.

**Cadence:** At log rotation threshold and during drift analysis run.

**What it checks:**

- No raw PII in any log entry — names, email addresses, phone numbers, account numbers, and authentication tokens are prohibited. Opaque IDs only.
- Log files excluded from git — `/logs/` directory not present in any commit.
- Log file sizes within threshold — rotation triggered before any file exceeds the configured limit.

**Finding actions:** PII redaction violations are Critical — log entry flagged, entry quarantined, real-time alert sent. Size threshold violations trigger log rotation. Git violations trigger immediate High alert and git history review.

---

## Architecture Audits

**Three triggers:**

| Trigger | Scope | Timing |
|---------|-------|--------|
| Phase-gate review | All five foundation documents — currency and correctness checks | Before any autonomy level advancement |
| Event-triggered review | Documents affected by the triggering event | After significant error cluster, major integration, security incident, or cost deviation |
| Semi-annual backstop | Full system | Every six months, regardless of other events |

**Two finding categories:**

| Category | Description | Action |
|----------|-------------|--------|
| Act now | Requires immediate attention — deprecated model string, security gap, compliance risk | Routes to advisor queue as Tier 1 decision. Real-time High severity alert. |
| Note for phase-gate | Important but not time-critical | Written to `/docs/architectural_review_staging.md`. Incorporated automatically into next phase-gate. |

*Phase advancement is blocked until all must-resolve findings are cleared and confirmed. Phase-gate retrospective runs as part of every phase-gate — calibration feedback written to rules library.*

---

## Drift Audits

**Cadence:** {{DRIFT_ANALYSIS_CADENCE}}

*Set during wizard setup. Cadence options: weekly, biweekly, monthly. Adjustable via `project_instructions.md`.*

**What it checks:**

- System behavior vs. vision document — is what the system is doing still what it was built to do?
- Document currency — are all five foundation documents current with system state?
- Scale tier match — does observed data volume and frequency match the provisional scale tier assumption?

**Scope:** Full system check against the vision document and all five foundation documents.

**Finding actions:**

- Behavioral drift finding: routes to work queue at High severity, user notified in digest.
- Vision/roadmap scope exception: surfaced to user — not auto-updated.
- Scale drift (2+ consecutive weeks of one-tier divergence): routes to issues log at High severity and to advisor queue.
- Document gaps: fixed automatically using the document update mechanism, change summary delivered in digest.
