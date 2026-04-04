# {{PROJECT_NAME}}

{{PROJECT_PURPOSE}}

This file is read by Claude Code at every session start. Read it completely before taking any action.

---

## Session startup sequence

This system starts via `./start-session.sh`. Three modes:

| Command | When to use |
|---------|-------------|
| `./start-session.sh` | Normal start — beginning a new work session |
| `./start-session.sh --resume` | Resuming after a planned pause or `/clear` |
| `./start-session.sh --resume --alert` | Responding to a system alert |

**At every session start, read these five files in order before acting:**

1. `session_bootstrap.md` — current state, last completed step, open items
2. `/logs/notification_log.md` — any alerts requiring attention
3. `pending_decisions.md` — decisions awaiting advisor input
4. `/work/work_queue.md` — current work queue
5. `/quality/human_review_queue.md` — items flagged for user judgment

**Alert-response sessions (`--resume --alert`):** Read the notification log first. Identify what triggered the alert and confirm the correct response before acting on anything else. Critical alerts are adjudicated before all other work.

**Maintenance mode:** At the start of every interactive session, check whether `/work/maintenance_mode.md` exists.
- If it exists: a previous session ended without clearing it (crashed or force-quit). Delete it, write a Warning alert entry to `/logs/notification_log.md` noting the stale flag, and continue.
- Once confirmed absent: create `/work/maintenance_mode.md`. This prevents cron-triggered agent runs from executing while the interactive session is active.
- At session end: delete `/work/maintenance_mode.md` before closing.

---

## Foundation documents

Five documents govern this system. Read the relevant document before acting on any task in its domain.

| Document | Contains |
|----------|----------|
| `vision.md` | Purpose, goals, scope, constraints, success criteria |
| `approach.md` | How the vision becomes a solution; agent roster and roles |
| `technical_architecture.md` | Data sources, integrations, security, logging, scale assumptions |
| `execution_plan.md` | Work sequencing, sprint plans, context management, human-in-the-loop map |
| `project_instructions.md` | Autonomy authorizations, notification preferences, thresholds, model tier mapping, spend ceiling |

These are living documents — maintained by the system as the project evolves. Never modify them outside the system's document update mechanism.

---

## Skills and agents

**Skills** — this system's capabilities — live in `/wizard/skills/`. Before beginning any task, search for a relevant skill. If one exists, follow it. Skills carry the detailed methodology; this file does not repeat it.

**Agents** — agent prompt files live in `/agents/prompts/`. Agent invocation scripts live in `/agents/scripts/`. Each agent file contains the agent's role, instructions, permissions, and completion criteria. Load the relevant agent prompt file and pass it at invocation — agents read from disk, not from session memory. Never modify agent files without deliberate architectural review.

**Agent roster:** `/agents/roster.md` lists all agents, their roles, and their criticality tiers.

---

## Context integrity protocol

**Proactive — do not begin large work units near the saturation threshold.**

Threshold values are stored in `project_instructions.md` (pre-flight threshold and mid-execution threshold). Check them before beginning any substantial operation.

Before starting any large work unit:
1. Assess current context usage against the pre-flight threshold.
2. If usage is within range of that threshold: stop — do not begin. Save current state to disk. Give the user a `/clear` command and a paste-ready resume prompt. Begin the work unit in clean context.
3. Never silently start a task that may not complete before compaction fires.

**Mid-execution saturation:** If saturation is detected mid-task, stop immediately. Write a checkpoint file to `/agents/checkpoints/[task_id]_checkpoint.md`. Provide the user with an exact resume prompt. Do not attempt to complete the task in compressed context — a saturation event mid-task is a failure mode, not a recoverable operating condition.

**Autocompaction is a session-reset event.** When autocompaction fires:
1. Stop work immediately.
2. Re-read this file and `session_bootstrap.md`.
3. Produce a verifiable re-orientation statement before continuing.
4. Discard any work product generated after compaction fired but before re-orientation is confirmed — this covers all work product: documents, agent outputs, log entries, anything.

---

## Autonomy level

Current level: **{{AUTONOMY_LEVEL}}**

The autonomy level governs what Claude may do independently versus what requires user initiation. The specific authorizations active at this level are in `project_instructions.md`.

**Claude never self-promotes its own authority level.** Autonomy advances only when the user consciously expands authorization in `project_instructions.md`.

**Bash authorization is separate from content authorization.** Check `project_instructions.md` for current bash permissions before running any shell command autonomously. A system can be authorized to update documents autonomously while still requiring user initiation for all bash commands.

---

## Core operating principles

**Disk-first.** Everything lives on disk. Nothing relies on session memory. Any new session with zero prior context must be able to read the files and orient completely.

**No PII in logs.** No raw personal data in any log entry — no names, email addresses, phone numbers, account numbers, or authentication tokens. Opaque IDs only. This rule is not configurable.

**Audit trail.** Every autonomous action is logged in `/logs/audit_log.md` — what was done, why, and what changed.

**Three-strikes escalation.** A task that fails at the configured threshold (see `project_instructions.md`) escalates to the user rather than retrying silently.

**Spend ceiling.** When the project's spend ceiling is reached (see `project_instructions.md`): unconditional stop. No auto-resume. User must explicitly authorize continuation.

**Exact prompts always.** Every significant recommendation includes an exact prompt or command, which model to use, and whether to run it in Claude.ai or Claude Code.

**Session close enforcement.** Every session must update four files before ending, in this order: (1) `SESSION_STATE.md` — current task state, (2) `session_bootstrap.md` — carry-forwards, next priorities, upcoming cron jobs, (3) `/work/work_queue.md` — status updates, (4) `/logs/session_log.md` — close entry with stop reason and summary. This sequence runs even if the session is ending due to a problem. The orchestrator stops work with enough budget and context remaining to complete this sequence. State persistence is higher priority than any in-progress task.

**Idempotency for external operations.** For any operation that modifies external state (API calls, message sends, file writes to external services), persist a record of the operation before or immediately after execution. On retry or session resume, check whether the operation has already been completed before executing it again. This prevents duplicate external actions when sessions crash and resume.

**Foundational document integrity.** Before making any decision or producing any output, read the relevant foundational documents from disk in this session. Do not operate from a recalled or summarized version. If a foundational document has not been read in this session, read it before proceeding.

---

## Permission scope

Claude Code will ask for confirmation before editing files or running shell commands. This is expected — these prompts protect the system from unintended changes.

**What this system will request permission to do:**

- Read and write files within the project directory
- Run bash commands for: starting agents, running the test suite, git commits, and log management
- Read foundation documents and agent files at session start

**What this system will not request permission to do without explicit user authorization:**

- Access files outside the project directory
- Connect to external services not configured during wizard setup
- Advance its own autonomy level

If a permission prompt asks for something outside this scope, deny it and note what triggered the request. Surface the unexpected prompt to the user before continuing.
