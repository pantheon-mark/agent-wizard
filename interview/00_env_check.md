# 00 — Environment Check

## What this file does
Silently verify that all four prerequisites are installed and at acceptable versions before the wizard interview begins. This step is invisible to the user unless a check fails. If all four checks pass, proceed immediately to `01_phase1_capture.md` without any user-facing message.

## When this file runs
At the very start of a wizard session, before any questions are asked and before any files are created. No project directory exists. No staging file exists. This is the zero-state starting point.

## Prerequisites
None. This is the first step.

---

## Step 0 — Permission prompts orientation [user-facing, run first]

Before running any checks, say this to the user:

> Before we start, one thing to know about how this works:
>
> As I set up your project, I'll need to create files, run commands, and make changes on your computer. Claude Code will occasionally ask for your permission before I do something — you'll see a prompt that says something like "Claude wants to edit a file" or "Claude wants to run a command."
>
> **When you see these prompts: click "Allow" or "Yes."** These are expected — they're just me doing the work of setting up your system. You will not be asked about anything unexpected or outside of what we're doing together.
>
> If you'd like to allow all operations for this session without being asked each time, you can type `/accept-all` — but reviewing each one is fine too.
>
> Any questions about this before we begin?

Wait for acknowledgment. If the user has questions, answer them in plain language. Once they're ready, proceed to the check sequence.

---

## Check sequence

Run all four checks in order. For each check: if it passes, move silently to the next. If it fails, show the failure message and fix command to the user, wait for confirmation that the fix was applied, re-run that specific check, and do not advance to the next check until the current one passes. The loop for a failing check is: show message → show fix command → wait for confirmation → re-run → if still failing, repeat.

---

### Check 1 — Homebrew

**Run:** `brew --version`

**Passes if:** Command executes without error and returns any version string.

**If it fails — say this to the user:**

> Homebrew isn't installed yet. Homebrew is a tool that manages software on your Mac — your system needs it to install the other tools that make this work. Here's the command to install it:
>
> ```
> /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
> ```
>
> Open a new Terminal window, paste the command, and press Enter. It will walk you through the installation — follow any prompts it shows. When it's done, come back here and tell me.

Wait for the user to confirm the fix is done. Re-run `brew --version`. If it still fails, show the same message again. Do not proceed to Check 2 until this check passes.

---

### Check 2 — Git

**Run:** `git --version`

**Passes if:** Command returns a version string beginning with "git version 2." or higher.

**If Git is not installed — say this to the user:**

> Git isn't installed yet. Git keeps a history of your project — if something ever goes wrong, it lets you go back to an earlier version. Here's the command to install it:
>
> ```
> brew install git
> ```
>
> Open a Terminal window, paste the command, and press Enter. When it finishes, come back and tell me.

**If Git is installed but on version 1.x — say this to the user:**

> Your version of Git is out of date. Here's the command to update it:
>
> ```
> brew upgrade git
> ```
>
> Open a Terminal window, paste the command, and press Enter. When it finishes, come back and tell me.

Wait for confirmation. Re-run `git --version`. Do not proceed to Check 3 until this check passes.

---

### Check 3 — Node.js

**Run:** `node --version`

**Passes if:** Command returns a version string of v18.0.0 or higher (v18.x, v20.x, v22.x, etc.).

**If Node.js is not installed — say this to the user:**

> Node.js isn't installed yet. Node.js is what allows your agent team to run scheduled tasks and operate in the background without you needing to be present. Here's the command to install it:
>
> ```
> brew install node
> ```
>
> Open a Terminal window, paste the command, and press Enter. It takes a couple of minutes. When it finishes, come back and tell me.

**If Node.js is installed but below v18 — say this to the user:**

> Your version of Node.js is too old for Claude Code to work correctly. Here's the command to update it:
>
> ```
> brew upgrade node
> ```
>
> Open a Terminal window, paste the command, and press Enter. When it finishes, come back and tell me.

Wait for confirmation. Re-run `node --version`. Do not proceed to Check 4 until this check passes.

---

### Check 4 — Claude Code

**Run:** `claude --version`

**Passes if:** Command returns a version string. (Claude Code is already running if this wizard is executing — this check verifies the global installation is current.)

**If the check fails or returns an unexpected result — say this to the user:**

> Claude Code needs a quick update before we continue. Here's the command:
>
> ```
> npm install -g @anthropic-ai/claude-code
> ```
>
> Open a Terminal window, paste the command, and press Enter. When it finishes, come back and tell me.

Wait for confirmation. Re-run `claude --version`. Do not proceed to `01_phase1_capture.md` until this check passes.

---

## Success condition

All four checks have passed. Do not show any message to the user. Proceed immediately to `01_phase1_capture.md`.

## Log note

There is no file to log to at this stage — the project directory and staging file do not exist yet. The result of this environment check (all four checks passed, versions found) is recorded as the first entry in `wizard_session_draft.md` when it is created in `01_phase1_capture.md` (step P1-3).
