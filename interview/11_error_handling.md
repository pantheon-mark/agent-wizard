# 11 — Error Handling

## What this file does
Configure how the system communicates when something goes wrong: notification verbosity, the three-strikes threshold before the system stops and asks for help, and a plain-language explanation of the difference between build-time and runtime errors. Writes configured values to the staging file for use in `project_instructions.md`.

## When this file runs
After `10_validation.md` completes and VALIDATION_CONFIGURED = true in the staging file.

## Prerequisites
VALIDATION_CONFIGURED = true in the staging file.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 11_error_handling.md. VALIDATION_CONFIGURED = true. Read the staging file, then begin the error handling configuration phase."

Do not begin ERR-1 until you are confident the full phase will complete before compaction risk.

---

## How to run this phase

This phase has no dynamic derivation from the project documents. ERR-1 and ERR-2 are configuration choices the user makes. ERR-3 is an explanation the user confirms they understand. Work through them in order.

---

## ERR-1 — Notification verbosity [FIXED — topic]

Present three rendered examples of the same hypothetical error at each verbosity level. The user chooses by comparing the examples side by side — not by interpreting abstract labels.

**Say:**

> When something goes wrong in your system, you'll get a notification. Here's the same problem written three different ways — choose the one that feels right for how you want to be kept informed.

---

> **Option 1 — Minimal**
>
> > Data sync failed. Run `./start-session.sh --resume --alert` to address.

---

> **Option 2 — Standard**
>
> > Your data agent couldn't reach the source it was reading from (connection refused). It tried 3 times and stopped. No data was changed.
> >
> > Run `./start-session.sh --resume --alert` to address.

---

> **Option 3 — Detailed**
>
> > **Data agent — connection failure**
> >
> > Your data agent tried to connect to its data source at 2:14 PM and was refused. It retried twice more and stopped after 3 attempts. No records were read, written, or changed.
> >
> > **What stopped:** The scheduled sync for today's records.
> > **What's unaffected:** All other agents are running normally. No data was lost.
> > **What to check:** The data source may be temporarily unavailable — it could be down, your credentials may have expired, or your network connection may have changed.
> >
> > Run `./start-session.sh --resume --alert` to address.

---

> Which of these feels right — Minimal, Standard, or Detailed?

**Wait for answer.**

- If the user chooses one: confirm the choice and proceed.
- If the user asks if they can change it later: "Yes — tell me at any point and I'll update it."
- If the user is unsure: suggest Standard as the default — enough context to act without being overwhelming.

One note: critical alerts always use full detail regardless of your preference. If the system needs to stop completely, you'll always get the complete picture. This setting governs everything below that level.

Write the configured value to the staging file: `NOTIFICATION_VERBOSITY = [Minimal / Standard / Detailed]`.

---

## ERR-2 — Three-strikes threshold [FIXED — topic]

**Say:**

> When the system hits a problem, it tries to fix it automatically. But if it keeps failing at the same step, there's a point where guessing doesn't help anymore — you need a person to look at it.
>
> How many attempts should the system make before it stops and asks you?
>
> I'd suggest **3 attempts** — enough to rule out a transient glitch, not so many that a real problem wastes time before reaching you. But if you want more or fewer, tell me.

**Wait for answer.**

- If the user accepts the default: confirm "3 attempts before escalating to you" and proceed.
- If the user chooses a different value: confirm the choice and proceed.

Note: the count applies per step — not per task. If step 2 of a task fails three times, the system escalates on step 2. Steps 1 and 3 aren't affected, and the work completed before the failure is preserved.

Write the configured value to the staging file: `THREE_STRIKES_THRESHOLD = [n]`.

---

## ERR-3 — Build vs. runtime distinction [EXPLANATION]

**Say:**

> One more thing before we move on — there's an important difference between two types of errors, and I want to make sure it makes sense before your build starts.
>
> **Errors during building** — when we build your agents, Claude Code will run into problems. That's normal. It's the same as any construction project: something doesn't fit, it gets adjusted. These errors are part of the process. You'll see them as part of the build output, and they get resolved as part of building.
>
> **Errors during operation** — once your system is running, errors mean something unexpected happened in the real world. A connection went down, data arrived in an unexpected format, an agent hit a limit. These trigger the recovery machinery: the three-strikes threshold, the alert system, the work queue.
>
> The difference matters because you should expect to see errors during the build phase and not be alarmed by them. The alert system you just configured is for when your system is up and running.
>
> Does that distinction make sense?

**Wait for answer.** If the user has questions, answer them in plain language. Then proceed.

---

## Write error handling configuration

After ERR-1 through ERR-3, the configured values are in the staging file. They will be written to `project_instructions.md` during the final build sequence.

**Say:**

> Error handling is configured. Your system will alert you at **[verbosity level]** and escalate to you after **[n] attempts** at any failing step.
>
> Next we'll set up quality preferences — how your QA agent works and how confident your system needs to be before it shows you results.

Update staging file: ERROR_HANDLING_CONFIGURED = true

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 11.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 11.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

ERR-1 through ERR-3 complete. NOTIFICATION_VERBOSITY and THREE_STRIKES_THRESHOLD written to staging file. ERROR_HANDLING_CONFIGURED = true in the staging file. Proceed to `12_qa_settings.md`.
