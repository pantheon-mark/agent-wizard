# 02 — Financial Guardrails

## What this file does
Establish the financial guardrails that govern all autonomous spending by the system. Two questions: overage plan type and monthly spend ceiling. These answers are stored in `project_instructions.md` and enforced by the system from the first day of operation.

## When this file runs
After `01_phase1_capture.md` completes. The staging file exists and is being updated after each answer.

## Prerequisites
Staging file at `~/Documents/claude-wizard-draft/wizard_session_draft.md` has been created and contains the P1-1 and P1-2 answers.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 02_financial.md. The staging file is at `~/claude-wizard-draft/wizard_session_draft.md` — read it, then begin FIN-1."

Do not begin FIN-1 until you are confident the full phase will complete before compaction risk.

---

## FIN-1 — Overage plan confirmation

**Ask the user:**

> One quick thing before we dive in — does your Claude plan stop automatically when you hit your monthly limit, or does it continue and charge you for the extra usage?
>
> If you're not sure, you can check at claude.ai/settings/billing. Just come back and let me know what you find.
>
> (Answer "stops" or "charges extra" — or describe what you see on the billing page.)

**Wait for answer.**

**If "stops" (plan has a hard limit, no overages):**

> Got it — your plan stops at the limit. That means the system's spend ceiling is a safety measure to make sure you always have enough budget left for the work you care about most. We'll set that in the next step.

Store: OVERAGE_PLAN_TYPE = "hard-stop"

**If "charges extra" (plan continues with overages):**

> Got it — your plan charges for overages. That means the spend ceiling is even more important — once the system hits it, it stops all autonomous work immediately until you decide to resume. We'll set that ceiling in the next step.

Store: OVERAGE_PLAN_TYPE = "overage-charges"

**If unsure or can't determine:**

> No problem — we'll note this as something to confirm. For now, we'll set the ceiling conservatively, which is the right call when you're not sure. You can update this any time.

Store: OVERAGE_PLAN_TYPE = "unknown"

Update staging file with answer.

---

## FIN-2 — Monthly spend ceiling

**Ask the user:**

> What's a comfortable monthly ceiling for what this system spends on Claude API calls — the amount where, if it hit that, you'd want it to stop and check in with you?
>
> There's no right answer here. Some people start at $20 and adjust up. Others set $100 from day one. Your system won't spend anywhere near this in the early weeks — it's a safety net, not a budget prediction.
>
> What number feels right to start?

**Wait for answer.** Accept any dollar amount. If the user gives a range (e.g. "maybe $50 to $100"), pick the lower end and note it.

**Once you have a number:**

Calculate the intensive operation threshold at 10% of the ceiling (e.g. if ceiling is $50, threshold is $5.00).

**Say this:**

> Got it — I'll set your ceiling at $[SPEND_CEILING]. Any time a single operation is estimated to cost more than $[INTENSIVE_THRESHOLD] on its own, the system will pause and ask for your approval before proceeding. You can raise or lower these at any time.

Store:
- SPEND_CEILING = the dollar amount
- INTENSIVE_OPERATION_THRESHOLD = 10% of SPEND_CEILING (rounded to two decimal places)

Update staging file with both values.

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 02.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 02.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

Both FIN-1 and FIN-2 answered and stored. Proceed to `03_user_profile.md`.
