# 13 — Operations Settings

## What this file does
Configure how the system behaves during operation. Three technical thresholds (retry threshold, gate conflict timeout, deferred alert limit) are set as **silent defaults** from the system profile — the user has no basis for choosing these values. User-facing questions cover chunk confirmation preference, drift analysis cadence, and scale tier. Produces the scale tier entry in `technical_architecture.md` and `project_instructions.md`. Writes all configured values to the staging file.

## When this file runs
After `12_qa_settings.md` completes and QA_CONFIGURED = true in the staging file.

## Prerequisites
QA_CONFIGURED = true in the staging file.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 13_operations.md. QA_CONFIGURED = true. Read the staging file, then begin the operations settings phase."

Do not begin CONC-1 until you are confident the full phase will complete before compaction risk.

---

## How to run this phase

This phase sets operational behavior. Three technical thresholds (CONC-1 retry threshold, CONC-2 gate conflict timeout, START-1 deferred alert limit) are **silent defaults** — the user has no basis for choosing these values and the recommendations are accepted >90% of the time. They are derived from the system profile and presented as a summary, not asked as questions.

The remaining topics require genuine user input: chunk confirmation preference (START-2), drift analysis cadence (DRIFT-1), and scale tier (SCALE-1 through SCALE-4). Work through them in sequence after presenting the auto-configured defaults. No disk artifacts are written until SCALE-4 is confirmed.

**Before starting:** Read the vision document, confirmed agent roster, and system profile (domain sensitivity from step 10, involvement level from step 03) to derive the silent defaults and tailor rationale to this specific system.

---

## Auto-configured defaults — CONC-1, CONC-2, START-1 [SILENT DEFAULTS]

*These values are set automatically from the system profile. Do not ask the user — a non-technical user has no basis for choosing between these technical thresholds, and the recommendations are accepted >90% of the time.*

**Before presenting:** Read the vision document and confirmed agent roster. Assess workflow complexity for CONC-2:
- **Simple** (few agents, mostly sequential handoffs, low concurrency): set `GATE_CONFLICT_TIMEOUT = 30 seconds`
- **Moderate** (several agents, some parallel activity, shared resources): set `GATE_CONFLICT_TIMEOUT = 2 minutes`
- **Complex** (many agents, high concurrency, shared databases or external APIs): set `GATE_CONFLICT_TIMEOUT = 5 minutes`

Write all three values to the staging file:
- `RETRY_THRESHOLD = 3`
- `GATE_CONFLICT_TIMEOUT = [derived value from assessment above]`
- `DEFERRED_ALERT_THRESHOLD = 3`

**Say:**

> Before we get into the questions that need your input, here's how I've configured the technical settings based on your system's design:
>
> - **Retry threshold:** 3 automatic attempts before escalating to you — enough to handle brief glitches without spinning on a real problem
> - **Resource conflict timeout:** **[derived value]** — [one-sentence rationale from workflow complexity assessment, e.g., "your agents mostly work in sequence, so a 30-second wait catches real problems without false alarms"]
> - **Deferred alert limit:** 3 deferrals before an alert is escalated as overdue — stops unresolved issues from sitting quietly in the queue
>
> These are tuned for your setup and adjustable anytime — just tell me if you'd like to change any of them.

Do not wait for a response. Proceed to START-2.

---

## START-2 — Chunk confirmation preference [FIXED — topic]

**Say:**

> When your system is working through a list of tasks — fixing a batch of issues, updating several documents, running a sequence of steps — you have a choice in how it proceeds.
>
> **Option 1 — Confirm each step:** The system completes one step, tells you what it did and what it's about to do next, and waits for your go-ahead before continuing. Nothing moves forward without your sign-off.
>
> **Option 2 — Confirm only the important ones:** The system works through lower-risk steps on its own and only stops when it reaches something that needs your judgment — an action that's harder to reverse, touches something sensitive, or has broader consequences.
>
> I'd suggest starting with **confirm each step**. As you get more familiar with how your system behaves, you can move to the second option and let it handle routine steps on its own. You're not locked in — you can switch at any time.
>
> Which would you like to start with?

**Wait for answer.**

- If the user chooses confirm each: confirm "Confirm-each to start. You can move to confirm-important-only once you're comfortable with how the system makes decisions."
- If the user chooses confirm important only: confirm their choice. Note: "Good — the system will still tell you about every step it takes, it just won't wait for approval on the routine ones."
- If the user asks what counts as "important": "Anything that affects a document your other processes depend on, that communicates externally, that involves money, or that's hard to reverse. The system applies the same Tier 1 rules you confirmed earlier."

Write the configured value to the staging file: `CHUNK_CONFIRMATION = [Confirm each / Confirm important only]`.

---

## DRIFT-1 — Drift analysis cadence [FIXED — topic]

**Before asking:** Read the vision document. Assess system complexity and how frequently the user's domain evolves:
- **Simple system or stable domain:** Recommend **monthly**.
- **Moderate complexity or moderately evolving domain:** Recommend **biweekly**.
- **Complex system, multiple integrations, or rapidly changing domain:** Recommend **weekly**.

**Say:**

> Over time, any system can drift — it keeps doing what it was originally built to do, but the world around it has changed. A data source restructured its output. A process your system supports was updated. A goal shifted.
>
> Drift analysis is when your system checks its own behavior against the vision document you confirmed at the start — asking "is what I'm doing still what I was built to do?"
>
> **How often should that check happen?**
>
> Based on [one-sentence rationale referencing system complexity or domain — e.g., "your system handles several integrations in a domain that changes regularly" or "your system is focused on a narrow, stable workflow"], I'd recommend **[recommended cadence]** as a starting point.
>
> That means once [weekly / every two weeks / monthly], the system reviews its own activity logs against your vision document and flags anything that looks like drift — for your review, never for autonomous correction without your input.
>
> Does that cadence feel right, or would you prefer more or less frequent checks?

**Wait for answer.**

- If the user accepts the recommendation: confirm the cadence and proceed.
- If the user chooses differently: accept without pushback. If they choose less frequent than monthly, note gently: "That's fine — worth knowing that drift tends to accumulate quietly, so you may want to revisit this as the system matures."
- If the user asks what happens when drift is detected: "The system flags it in your digest with a plain-language description — 'I noticed I've been doing X, but your vision document says the goal is Y. Here's what I think should change. Do you want me to adjust?' It never silently reorients itself."

Write the configured value to the staging file: `DRIFT_CADENCE = [Weekly / Biweekly / Monthly]`.

---

## Scale tier — SCALE-1, SCALE-2, SCALE-3 [FIXED]

**Say:**

> Last set of questions before we wrap up. These help me understand the scale your system will need to operate at — not technical details, just how your day-to-day actually works.

Ask each question in sequence. Wait for the answer before moving to the next.

**SCALE-1:**

> How many people, records, or items will your system need to keep track of? This could be clients, patients, properties, cases, family members — whatever applies to your situation.

**Wait for answer.**

**SCALE-2:**

> How often does your system need to process or refresh information — a few times a day, hourly, or continuously?

**Wait for answer.**

**SCALE-3:**

> Are there peak periods where the volume spikes significantly?

**Wait for answer.**

---

## SCALE-4 — Tier confirmation [DYNAMIC]

**Before stating the tier:** Map the user's three answers to a provisional tier using the following guide:

| Tier S (Small) | Tier M (Medium) | Tier L (Large) |
|----------------|-----------------|----------------|
| Hundreds of records or fewer | Thousands of records | Tens of thousands of records or more |
| A few times a day or less | Hourly | Near-continuous or continuous |
| No significant peaks, or very minor spikes | Some peaks, manageable | Significant peak periods with meaningful volume spikes |

When answers span tiers, round to the higher tier if two or more indicators point there.

**Say:**

> Based on what you've described, I'm treating this as a **Tier [S / M / L]** system — [one-sentence rationale, e.g., "you're working with hundreds of records and processing happens a few times a day, so the system doesn't need to be built for high-throughput operation" or "with thousands of records processed hourly and meaningful peaks, the system needs to handle concurrent load reliably"].
>
> This is a starting assumption. Once your agents are running with real data, I'll check whether what I actually observe matches. Does that sound right?

**Wait for answer.**

- If the user confirms: proceed.
- If the user adjusts the tier: accept the adjustment. Ask "What's different from what you described?" so the rationale is accurate. Record the user-confirmed tier.
- If the user is uncertain: "That's fine — I'll start with [tier] and watch how the system actually behaves. If what I observe is consistently different, I'll flag it and we'll revisit."

Write the configured value to the staging file: `SCALE_TIER = [S / M / L] (provisional)`.

---

## Disk writes

After SCALE-4 is confirmed, write the scale tier to two documents.

### Write to technical_architecture.md

Locate the `technical_architecture.md` file in the project directory. Add a new section titled **Scale Tier** at the end of the file:

```markdown
## Scale Tier

**Provisional tier:** [S / M / L]
**Rationale:** [The one-sentence rationale stated at SCALE-4.]
**Basis:** [Brief plain-language summary of the three scale answers — volume, frequency, and peak periods.]
**Status:** Provisional — set during wizard setup. Will be reviewed after first production run and checked weekly from that point. Requires explicit user confirmation to change.
```

### Write to project_instructions.md

Locate the `project_instructions.md` file in the project directory. Add a scale tier entry to the system configuration section:

```
Scale tier: [S / M / L] (provisional — set [DATE], confirmed by user at wizard setup)
```

Write an audit trail entry: `Scale tier set to [S/M/L] (provisional) during wizard setup — based on [volume description], [frequency description], [peak description]. User confirmed.`

---

## Confirm with the user

**Say:**

> Operations settings confirmed. Here's what's in place:
>
> - **Retry threshold:** [n] automatic attempts before escalation
> - **Gate conflict timeout:** [value] before flagging resource conflicts
> - **Deferred alert limit:** [n] deferrals before an alert is escalated as overdue
> - **Chunk confirmation:** [Confirm each step / Confirm important only]
> - **Drift analysis:** Runs [Weekly / Biweekly / Monthly]
> - **Scale tier:** Tier [S / M / L] (provisional)
>
> Next we'll review the documents your system has produced so far and set up your GitHub backup.

Update staging file: `OPERATIONS_CONFIGURED = true`

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 13.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 13.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

CONC-1, CONC-2, START-1, START-2, DRIFT-1, and SCALE-1 through SCALE-4 complete. Scale tier written to `technical_architecture.md` and `project_instructions.md`. All configured values written to the staging file. `OPERATIONS_CONFIGURED = true` in the staging file.

**Write completion marker:** Append `step_13: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `14_document_review.md`.
