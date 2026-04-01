# 01 — Phase 1: Immediate Capture

## What this file does
Capture the project name and core purpose — the two pieces of information the user knows immediately. Then create the staging file that persists through the entire wizard interview. Fast, zero-friction, no wrong answers.

## When this file runs
Immediately after `00_env_check.md` passes. No project directory exists yet.

## Prerequisites
All four environment checks in `00_env_check.md` have passed.

---

## Step 0 — Resume check (run before asking any questions)

Before P1-1, check whether a prior wizard session exists:

**Run:** Check if `~/Documents/claude-wizard-draft/wizard_session_draft.md` exists.

**If the file does NOT exist:** Proceed to P1-1 normally.

**If the file EXISTS — say this to the user:**

> I found an earlier wizard session. Here's what was captured:
>
> **Project name:** [read PROJECT_NAME from the file]
> **Purpose:** [read CORE_PURPOSE from the file]
> **Last completed step:** [read RESUME_FROM from the file]
>
> Would you like to continue from where you left off, or start fresh? (Say "continue" or "start fresh".)

**If user says "continue":** Read the full draft file. Identify RESUME_FROM. Skip all completed steps and resume from the indicated question ID. Update LAST_UPDATED in the draft file.

**If user says "start fresh":** Delete the existing draft file. Proceed to P1-1 normally.

**Note on staging location:** The staging directory `~/claude-wizard-draft/` is at the home directory level (not inside Documents) to avoid slow startup indexing caused by Claude Code scanning large document folders.

---

## P1-1 — Project name

**Ask the user:**

> What would you like to call this project?

Accept any name the user gives. No validation needed — there are no wrong answers here. Short names, long names, names with spaces are all fine. The name will be used to create the project folder, so note that spaces will become hyphens in the folder name (e.g. "My Business System" → `my-business-system`). Mention this only if the name contains spaces.

The project folder will be created at `~/[folder-name]` — directly in the home directory. This keeps the project isolated so Claude Code starts up quickly. Do not use `~/Documents/` as the default location.

**Store:**
- PROJECT_NAME = the user's answer (display name)
- PROJECT_FOLDER_NAME = lowercase version with spaces replaced by hyphens and special characters removed
- PROJECT_PATH = `~/` + PROJECT_FOLDER_NAME (e.g. `~/my-business-system`)

---

## P1-2 — Core purpose

**Ask the user:**

> In one sentence — what is this system going to do for you?

Accept any answer. One sentence is the goal but do not push back if they give more. If they give significantly more than one sentence, accept it gracefully and use the most purpose-focused sentence for the core purpose field. The full answer is preserved in the staging file.

**Store:** CORE_PURPOSE = the user's answer

---

## P1-3 — Create staging file [INTERNAL]

Do not ask the user anything. Perform these steps silently, then show one confirmation line.

**Steps:**

1. Create the directory `~/claude-wizard-draft/` if it does not already exist.

2. Write `~/claude-wizard-draft/wizard_session_draft.md` with the following content:

```
# Wizard Session Draft

PROJECT_NAME: [value from P1-1]
CORE_PURPOSE: [value from P1-2]
STARTED: [current date and time]
LAST_UPDATED: [current date and time]
RESUME_FROM: FIN-1

## Environment check
All four prerequisite checks passed.
- Homebrew: [version found]
- Git: [version found]
- Node.js: [version found]
- Claude Code: [version found]

## Captured answers
[P1-1] Project name: [value]
[P1-2] Core purpose: [value]
```

3. After writing the file successfully, **say this to the user:**

> I've created your project draft. Everything you tell me from here is saved as we go — if this session ever ends unexpectedly, we can pick up exactly where we left off.

---

## Update rule — applies for the rest of the wizard

After every question answer from this point forward, append a new line to the `## Captured answers` section of `wizard_session_draft.md` in the format:

```
[QUESTION_ID] [Question label]: [Answer]
```

And update `RESUME_FROM` to the ID of the next question not yet answered, and update `LAST_UPDATED` to the current date and time.

This rule applies automatically through all subsequent interview files. It does not need to be re-stated in each file — it is always active once P1-3 completes.

---

## Success condition

P1-3 completed, staging file written, confirmation shown to user. Proceed to `02_financial.md`.
