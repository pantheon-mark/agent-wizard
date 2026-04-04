# 12 — Quality Preferences

## What this file does
Configure how the QA system works: investigation reporting style, preferred future alert channel, external source registry, and how often the system checks uncertain outputs with the user. Claude proposes the source registry from the vision and approach documents. Produces `/quality/source_registry.md` and writes quality preference values to the staging file.

## When this file runs
After `11_error_handling.md` completes and ERROR_HANDLING_CONFIGURED = true in the staging file.

## Prerequisites
ERROR_HANDLING_CONFIGURED = true in the staging file.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 12_qa_settings.md. ERROR_HANDLING_CONFIGURED = true. Read the staging file, then begin the quality preferences phase."

Do not begin QA-1 until you are confident the full phase will complete before compaction risk.

---

## How to run this phase

QA-1, QA-3, and QA-4 require specific user choices. QA-2 is a brief preference capture — no action is taken on it now. Work through them in order.

---

## QA-1 — Investigation workflow reporting style [FIXED — topic]

Present the same quality issue handled two ways. The user chooses by reading both — not by interpreting labels.

**Say:**

> When your QA agent finds something worth investigating, there are two ways it can keep you informed. Here's the same situation handled both ways:

---

> **Option 1 — Summary when done**
>
> You get one message when the investigation is complete:
>
> > **QA finding resolved**
> > I investigated why the weekly report was showing inconsistent figures. The source data had a formatting change that caused two fields to be read out of order. I've flagged the pattern as a rule so it won't happen again. No action needed — I'll include this in your next digest.
> > Run `./start-session.sh --resume` if you'd like to review the details.

---

> **Option 2 — Updates as it goes**
>
> You get a message at each step of the investigation:
>
> > **QA — investigation started**
> > I noticed inconsistent figures in the weekly report. Starting investigation now.
>
> > **QA — finding identified**
> > The source data has a formatting change. Two fields are being read out of order. Checking whether this is a one-time issue or a pattern.
>
> > **QA — resolved**
> > Confirmed it's a pattern. I've added a rule to catch it. No action needed — I'll include this in your next digest.

---

> Which style do you prefer — summary when done, or updates as it goes?

**Wait for answer.**

- If the user chooses summary: confirm "Summary when done" and proceed.
- If the user chooses updates: confirm "Updates as it goes" and proceed.
- If the user asks if they can change it later: "Yes — tell me at any point."

Write the configured value to the staging file: `QA_REPORTING_STYLE = [Summary / Live]`.

---

## QA-2 — Future feedback channel [FIXED — topic]

**Say:**

> One more preference to record — this one doesn't change anything right now, but it's worth capturing.
>
> Your current alerts run through NTFY and email. As your system grows, you may want to move to a more direct channel for production alerts. When that time comes, what's your preference?
>
> **Options:** SMS, Slack, Teams, or Email (as a primary real-time channel rather than digest only)
>
> This is just recorded for now — we'll revisit it when the system is running and you're thinking about what comes next.

**Wait for answer.** Record the preference. If the user is unsure, note "undecided — revisit at Phase 3."

Write the configured value to the staging file: `FUTURE_ALERT_CHANNEL = [SMS / Slack / Teams / Email / Undecided]`.

---

## QA-3 — Source registry initialization [DYNAMIC]

Read the vision document and approach document. Identify every external data dependency the system will rely on — specific named sources, services, APIs, and integrations.

**Note:** the source registry records specific external sources (e.g., "Salesforce CRM API", "company website"), not input categories. It tracks whether each source is healthy, when it was last verified, and what the system expects from it.

**Say:**

> Your QA agent monitors every external source your system depends on — so if a connection breaks or a data format changes, the system catches it before it causes problems.
>
> Here are all the external sources I see your system relying on:
>
> **[Source plain-language name]**
> [What it is — one sentence.] Your system needs it to [what it provides]. Without it, [what stops or degrades].
>
> **[Repeat for each source.]**
>
> Does this list look complete? Is there anything your system will pull from that isn't here?

**Wait for answer.**

- If the user confirms: proceed.
- If the user removes a source: note the implication and update the list.
- If the user adds a source: add it with a proposed name, description, and dependency statement. Confirm before proceeding.
- If a source is uncertain: mark it as pending.

Write `/quality/source_registry.md` after the list is confirmed (see disk write section below).

---

## QA-4 — Confidence flagging threshold [FIXED — topic]

**Say:**

> Sometimes your system will produce something it's not fully confident about — a report where one figure is uncertain, a summary where a source was ambiguous. You can choose how often it stops to ask you when that happens.
>
> **Most cautious — Ask whenever uncertain:** Any time the system isn't fully confident in an output, it flags it for your review before proceeding.
>
> **Balanced — Ask when it matters:** The system flags uncertainty in high-sensitivity areas and anything that affects a decision or goes to a recipient. Routine outputs in low-sensitivity areas proceed with the uncertainty noted in the log.
>
> **Least cautious — Ask only for significant uncertainty:** The system only surfaces outputs where confidence is materially low. Minor uncertainty is logged but doesn't interrupt work.

Then:

> Based on your domain, I'd recommend **[Balanced / Most cautious]** as a starting point — [one-sentence rationale from the vision document, e.g., "your outputs go to clients, so uncertain figures reaching them would be a problem" or "your domain has high factual sensitivity so catching uncertainty early is worth the interruption"].
>
> Which would you like to start with?

**Wait for answer.**

- If the user accepts the recommendation: confirm and proceed.
- If the user chooses a different level: confirm and proceed.
- If the user wants to discuss what counts as "significant" uncertainty: explain that the system uses its own calibration based on domain sensitivity settings from the validation gate, and that it can be adjusted as patterns emerge.

Write the configured value to the staging file: `CONFIDENCE_FLAGGING_THRESHOLD = [Most cautious / Balanced / Least cautious]`.

---

## Write source registry to disk

After QA-3, write the source registry.

**File:** `[PROJECT_DIR]/quality/source_registry.md`

**Structure:**

```markdown
# Source Registry

| Source | Description | What depends on it | Expected behavior | Last verified | Status |
|--------|-------------|-------------------|-------------------|---------------|--------|
| [Plain-language name] | [What it is] | [Which agents use it] | [What normal looks like] | [Date] | Active / Pending |
```

Write an audit trail entry: `Source registry initialized during wizard setup — [n] sources active, [n] pending`.

**Say:**

> Quality preferences confirmed. Here's what's in place:
>
> - QA reporting: **[Summary when done / Updates as it goes]**
> - Future alert channel preference: **[channel]** — recorded for when the time comes
> - **[n] external sources** your system will monitor
> - Confidence flagging: **[threshold level]**
>
> Next we'll set up the operational behavior settings — how the system handles retries, conflicts, startup, and drift.

Update staging file: QA_CONFIGURED = true

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 12.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 12.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

QA-1 through QA-4 complete. `/quality/source_registry.md` written to disk. QA_REPORTING_STYLE, FUTURE_ALERT_CHANNEL, and CONFIDENCE_FLAGGING_THRESHOLD written to staging file. QA_CONFIGURED = true in the staging file.

**Write completion marker:** Append `step_12: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `13_operations.md`.
