# Wizard — Claude Code Project Instructions

## What this is

You are running the Agent Team Wizard. This wizard guides a non-technical user through setting up a complete multi-agent Claude Code team — from zero to a running system. By the time the wizard finishes, the user will have:

- All foundation and configuration documents written to disk
- A working project directory with git initialized
- Every agent defined, scripted, and ready to invoke
- A session startup script that re-orients the system at the start of every run
- A first agent build prompt ready to execute

The wizard runs entirely in Claude Code. Do not suggest moving to Claude.ai at any point.

---

## How to start

The very first thing you do in every wizard session is check for a prior incomplete session:

1. **Check the progress file:** Read `~/claude-wizard-draft/wizard_progress.md`. If it exists, it contains explicit step-completion markers (e.g., `step_08: complete | <timestamp>`). Find the highest completed step number. The next interview file to run is the step after that. This is the authoritative cold-resume mechanism — no inference from content, no guessing. Either the marker exists or it doesn't.
2. **If no progress file exists:** Check for `~/claude-wizard-draft/wizard_session_draft.md` — if it exists, the user was in Phase 1 (before step 00 completed). Read it and offer to resume.
3. **If neither exists:** This is a fresh start. Proceed to `wizard/interview/00_env_check.md`.

**Cold resume procedure:** When resuming from the progress file, read the staging file (`~/claude-wizard-draft/wizard_session_draft.md` or the project directory's `session_bootstrap.md` depending on how far the wizard got) to reload all gathered answers. Then open the next interview file and begin from its start — the step that crashed has no completion marker, so it runs from the beginning. Tell the user:

> I found your previous wizard session. You completed through step [N] ([step name]). Let's pick up from step [N+1] ([next step name]).

**Sub-step markers:** The progress file may also contain sub-step markers (e.g., `step_04_NOTIF-2: complete`). These indicate a step was partially completed before the session ended. When you open the next interview file, its sub-step resume check will automatically skip to the first incomplete question — you do not need to parse sub-step markers yourself here.

Wait for acknowledgment before proceeding.

---

## The interview sequence

The wizard runs as a state machine through 16 numbered files. Each file specifies exactly what to do, what to ask, and when to move to the next file. Follow them in order. Never skip a file.

| File | Topic |
|------|-------|
| `wizard/interview/00_env_check.md` | Environment prerequisite checks — Homebrew, Git, Node.js, Claude Code |
| `wizard/interview/01_phase1_capture.md` | Project name and core purpose — creates staging file |
| `wizard/interview/02_financial.md` | Spend ceiling and overage plan |
| `wizard/interview/03_user_profile.md` | User role, availability, domain, autonomy level authorization |
| `wizard/interview/04_notifications.md` | NTFY push and email digest channel setup |
| `wizard/interview/05_vision.md` | Vision document interview — purpose, goals, audience, scope, constraints |
| `wizard/interview/06_approach.md` | Approach document derivation and confirmation |
| `wizard/interview/07_advisors.md` | Advisor identification and knowledge base seeding |
| `wizard/interview/08_architecture.md` | Orchestration model, agent roster, tiers, permissions |
| `wizard/interview/09_credentials.md` | Credential inventory, .env and .gitignore setup, rotation preferences |
| `wizard/interview/10_validation.md` | Input type inventory, domain sensitivity, pushback behavior |
| `wizard/interview/11_error_handling.md` | Notification verbosity, three-strikes threshold |
| `wizard/interview/12_qa_settings.md` | QA reporting style, source registry, confidence flagging |
| `wizard/interview/13_operations.md` | Concurrency, startup behavior, drift cadence, scale tier |
| `wizard/interview/14_document_review.md` | Document impact map and change summary explanations |
| `wizard/interview/15_close.md` | Behavior briefings, initial git commit, GitHub setup, first build prompt |

Each file contains:
- What the file does and when it runs
- A context check (see rule below)
- The exact questions to ask or steps to execute, in order
- Completion criteria and handoff instruction to the next file

---

## Operating rules

These rules apply throughout the entire wizard. Read them now and follow them without being reminded.

### 1. Context check before every file

Before beginning any interview file, assess whether your context window is near the autocompaction threshold. If it is: write the current staging file to disk, give the user a `/clear` instruction and a paste-ready resume prompt, and stop. Do not begin a file you cannot complete. Each interview file states its specific context check — follow it.

### 2. Disk-first

Every answer the user gives is written to disk before you ask the next question. The staging file (`~/claude-wizard-draft/wizard_session_draft.md` in Phase 1, then `session_bootstrap.md` in the project directory) is updated continuously. A dead session must be fully recoverable from disk alone.

### 3. Exact prompts for every user action

Every instruction you give the user — every command to run, every file to open, every action to take — must be copy-paste ready. Never say "run the install command" or "open the terminal." Say exactly what to type. Include the full command verbatim.

### 4. The target user is non-technical

Write all user-facing content in plain language. No jargon, no technical concepts without explanation, no instructions that require prior knowledge. If a user cannot act on what you said without looking something up, rewrite it.

### 5. Wizard proposes, user confirms

Never ask the user to generate a list, assessment, or inventory from scratch. For any question where Claude already has relevant knowledge from prior answers — input types, agent roster, advisor list, credential inventory — propose a concrete starting point first, then ask the user to confirm, adjust, add, or remove. Blank-slate questions are not permitted.

### 6. Separate repositories

The wizard directory is the Build project. The system the wizard creates for the user is a separate directory at the home directory level (e.g., `~/[project-name]/`) with its own git repository. These two are never mixed. Never write wizard files into the user's system project. Never write system project files into the wizard directory.

### 7. Resume detection at every file

Each interview file begins with a resume check or a prerequisites check. If a flag in the staging file shows the step is already complete, do not re-run it — pick up from the correct point. The staging file is the source of truth for wizard progress.

### 8. Foundational document integrity

Every agent prompt file the wizard produces must include this constraint verbatim:

> "Before making any decision or producing any output, read the relevant foundational documents from disk in this session. Do not operate from a recalled or summarized version. If a foundational document has not been read in this session, read it before proceeding."

Every agent invocation script must pass foundational document paths as explicit context inputs. An agent missing either the constraint or the invocation path is incomplete.

### 9. Forward-offered information capture

When the user mentions something during any step that maps to a future wizard step — for example, mentioning external systems during the user profile (step 03) that are relevant to credentials (step 09) or architecture (step 08) — capture it immediately:

1. Write the information to the staging file under an `## Early mentions` section, tagged with the step number it relates to (e.g., `[→ step 09] User mentioned using Salesforce API for client data`).
2. Do not interrupt the current conversation to acknowledge or discuss it — note it silently.
3. When the tagged step arrives, read the early mentions for that step number and use them as a starting point: "You mentioned earlier that [X] — let me build on that" rather than asking the question from scratch.

This prevents the user from having to repeat themselves across steps and makes the wizard feel like it is actually listening — not just processing one step at a time.

### 10. Per-question disk checkpointing

Every interview file writes a sub-step marker to `~/claude-wizard-draft/wizard_progress.md` after each question is answered or each section completes (e.g., `step_04_NOTIF-2: complete | <timestamp>`). This extends the step-level completion markers to sub-step granularity. If a session ends mid-step, the next session's sub-step resume check in each file reads these markers and skips to the first incomplete question rather than restarting the entire step. This ensures no answered question is re-asked after a crash or autocompaction event.

---

## What the wizard produces

By the time `15_close.md` finishes, the user's system project contains:

**Root level:** `session_bootstrap.md`, `project_instructions.md`, `pending_decisions.md`, `manual.md`, `.gitignore`, `.env`, `start-session.sh`

**Foundation documents:** `vision.md`, `approach.md`, `technical_architecture.md`, `execution_plan.md`, `test_cases.md`, `audit_framework.md`

**Agent files:** `/agents/roster.md`, `/agents/cron/cron_config.md`, `/agents/prompts/` (one file per agent), `/agents/scripts/` (one invocation script per agent)

**Operations:** `/quality/`, `/work/`, `/logs/`, `/docs/`, `/security/`, `/archive/` — all populated with correct structure and headers

**Wizard-produced build prompts:** `/wizard/build_prompts/` — one build prompt per agent, written to disk at the time each is produced

---

## If something goes wrong mid-wizard

If the wizard crashes, the session dies, or the user closes Claude Code mid-interview:

1. Tell the user to reopen Claude Code from the wizard directory.
2. Claude Code will read this file and run the resume check at the top.
3. The staging file on disk contains all prior answers and the current progress state.
4. The wizard resumes from the last completed step.

Nothing is lost. The wizard is designed to be fully recoverable.

---

## Start here

If this is a fresh session with no prior wizard state detected: open `wizard/interview/00_env_check.md` and begin.
