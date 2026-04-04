# 02 — Financial Guardrails

## What this file does
Establish the financial guardrails that govern all autonomous spending by the system. Two questions: overage plan type and monthly spend ceiling. These answers are stored in `project_instructions.md` and enforced by the system from the first day of operation.

## When this file runs
After `01_phase1_capture.md` completes. The staging file exists and is being updated after each answer.

## Prerequisites
Staging file at `~/claude-wizard-draft/wizard_session_draft.md` has been created and contains the P1-1 and P1-2 answers.

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

### Calibration guidance (after FIN-2, before proceeding)

After storing the ceiling, provide calibration guidance based on the user's plan type (FIN-1) and ceiling amount. This helps the user understand what their budget can support — framed in terms of what the system can do, not in technical terms like tokens or agent sessions.

**If OVERAGE_PLAN_TYPE = "hard-stop":**

> A few things worth knowing about that ceiling:
>
> - **Under $20/month:** Your system can handle light, focused work — checking a few things regularly and alerting you when something needs attention. You'll want to keep your agent team small (1–2 agents) and run them on a schedule rather than continuously.
> - **$20–$50/month:** Comfortable range for a small team of agents handling regular tasks — monitoring, summarizing, and flagging things for your review. Enough headroom for occasional intensive operations without hitting the ceiling unexpectedly.
> - **$50–$100/month:** Room for a more active system — multiple agents running frequently, handling more complex work, with budget to spare for the occasional large task.
> - **Over $100/month:** Your ceiling gives plenty of room. The system can operate at full capacity without budget being a constraint in normal operation.
>
> Since your plan stops at the limit, your ceiling also protects your remaining balance for any personal use of Claude you do outside this system. If you find the system is bumping against the ceiling regularly, that's a signal to either raise it or streamline what your agents are doing.

**If OVERAGE_PLAN_TYPE = "overage-charges":**

> A few things worth knowing about that ceiling:
>
> - **Under $20/month:** Your system can handle light, focused work — checking a few things regularly and alerting you when something needs attention. You'll want to keep your agent team small (1–2 agents) and run them on a schedule rather than continuously.
> - **$20–$50/month:** Comfortable range for a small team of agents handling regular tasks — monitoring, summarizing, and flagging things for your review.
> - **$50–$100/month:** Room for a more active system — multiple agents running frequently, handling more complex work.
> - **Over $100/month:** Your ceiling gives plenty of room. The system can operate at full capacity.
>
> Since your plan charges for overages, hitting the ceiling is a real spending boundary — the system stops all autonomous work the moment it's reached and waits for you to say "continue." It will never spend past this amount on its own.

**If OVERAGE_PLAN_TYPE = "unknown":**

Use the "hard-stop" guidance above. Add:

> Once you've confirmed your plan type, you can adjust these settings at any time.

**Note for step 13 cross-reference:** When SCALE-1 through SCALE-4 are answered in step 13 (operations), the wizard should compare the declared scale/velocity against the FIN-2 ceiling. If the scale suggests higher usage than the ceiling comfortably supports (e.g., Large scale tier with a $10 ceiling), surface the discrepancy to the user in plain language and ask if they'd like to adjust either the ceiling or the scale expectation. This check happens in step 13, not here — record `FIN_CALIBRATION_DELIVERED = true` in the staging file so step 13 knows to run the cross-reference.

Store: FIN_CALIBRATION_DELIVERED = true in staging file.

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

Both FIN-1 and FIN-2 answered and stored.

**Write completion marker:** Append `step_02: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `03_user_profile.md`.
