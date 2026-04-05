# 11 — Error Handling

## What this file does
Configure how the system communicates when something goes wrong: notification verbosity (user choice) and the three-strikes threshold (silent default — auto-configured at 3 attempts). Includes a plain-language explanation of the difference between build-time and runtime errors. Writes configured values to the staging file for use in `project_instructions.md`.

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

ERR-1 is a genuine personal preference — the user chooses notification verbosity from rendered examples. ERR-2 (retry threshold) is a **silent default** — the recommendation is accepted >90% of the time and the user has no basis for choosing a different value. It is set automatically and presented as an informational note, not a question. ERR-3 is an explanation the user confirms they understand. Work through them in order.

---

## ERR-1 — Notification verbosity [FIXED — topic]

Present three rendered examples of the same hypothetical error at each verbosity level. **Use the user's actual system context** — pick one of the agents from the confirmed roster and create a realistic error scenario grounded in the user's domain from the vision and approach documents. Do not use generic examples. The user makes a better choice when they see how notifications will actually look in their system.

**Say:**

> When something goes wrong in your system, you'll get a notification. Here's the same problem written three different ways — choose the one that feels right for how you want to be kept informed.

---

Then present three rendered examples. **Build these from the user's actual system** — pick one agent from the confirmed roster and create a realistic error for that agent's domain. The examples below are fallback structure only — replace the agent name, error scenario, and domain details with the user's real system context.

> **Option 1 — Minimal**
>
> > [Agent name] failed. Run `./start-session.sh --resume --alert` to address.

---

> **Option 2 — Standard**
>
> > Your [agent name] couldn't [what it was trying to do] ([plain-language reason]). It tried [N] times and stopped. [What was or wasn't affected].
> >
> > Run `./start-session.sh --resume --alert` to address.

---

> **Option 3 — Detailed**
>
> > **[Agent name] — [failure type]**
> >
> > Your [agent name] tried to [specific action] at [time] and [what went wrong]. It retried [N] more times and stopped after [total] attempts. [Specific scope of impact].
> >
> > **What stopped:** [The specific task that was interrupted.]
> > **What's unaffected:** [What's still running normally.]
> > **What to check:** [Plain-language suggestions for what might be wrong.]
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

## ERR-2 — Three-strikes threshold [SILENT DEFAULT]

*This value is set automatically. Do not ask the user — a non-technical user has no basis for choosing between 2, 3, or 5 retries, and the default is accepted >90% of the time.*

Write to the staging file: `THREE_STRIKES_THRESHOLD = 3`

**After confirming the user's ERR-1 verbosity choice, add:**

> I've also configured your system's retry threshold — when something goes wrong, the system will try to fix it automatically up to **3 attempts** before stopping and asking you. That's enough to handle brief glitches without spinning on a real problem. You can adjust this anytime.

Do not wait for a response. Proceed to ERR-3.

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

ERR-1 through ERR-3 complete. NOTIFICATION_VERBOSITY and THREE_STRIKES_THRESHOLD written to staging file. ERROR_HANDLING_CONFIGURED = true in the staging file.

**Write completion marker:** Append `step_11: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `12_qa_settings.md`.
