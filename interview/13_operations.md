# 13 — Operations Settings

## What this file does
Configure how the system behaves during operation: agent retry behavior, resource conflict handling, session startup preferences, drift analysis cadence, and scale tier. Claude recommends defaults based on the vision document and confirmed agent roster. Produces the scale tier entry in `technical_architecture.md` and `project_instructions.md`. Writes all configured values to the staging file.

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

This phase covers four topic groups in order: concurrency and recovery (CONC-1, CONC-2), session startup behavior (START-1, START-2), drift and review cadences (DRIFT-1), and scale tier (SCALE-1 through SCALE-4). Work through them in sequence. All are configuration preferences — no disk artifacts are written until SCALE-4 is confirmed.

**Before starting:** Read the vision document and confirmed agent roster so you can tailor defaults and rationale to this specific system.

---

## CONC-1 — Retry threshold [FIXED — topic]

**Say:**

> If one of your agents runs into a problem — a connection fails, a step doesn't complete — the system will try to fix it automatically before asking you.
>
> **How many automatic attempts should it make before stopping and getting your attention?**
>
> I'd recommend starting with **three attempts**. That's enough to handle brief interruptions like a slow API or a momentary network issue, without spinning for a long time before you find out something is wrong.
>
> You can change this at any time.

**Wait for answer.**

- If the user accepts three: confirm "Three attempts — I'll escalate to you if it hasn't resolved by then."
- If the user chooses a different number: confirm their choice and note that lower numbers mean earlier escalation and higher numbers mean more autonomous recovery attempts.
- If the user asks what "fix it automatically" means: "The system diagnoses the failure, picks the most likely resolution, applies it, and checks whether the problem is gone. Each attempt follows that same cycle."

Write the configured value to the staging file: `RETRY_THRESHOLD = [number]`.

---

## CONC-2 — Gate conflict timeout [FIXED — topic]

**Before asking:** Read the vision document and agent roster. Assess workflow complexity:
- **Simple:** Few agents, mostly sequential handoffs, low concurrency — propose **30 seconds**.
- **Moderate:** Several agents, some parallel activity, shared resources — propose **2 minutes**.
- **Complex:** Many agents, high concurrency, shared databases or external APIs accessed by multiple agents simultaneously — propose **5 minutes**.

**Say:**

> Your agents sometimes need to access the same resource — a file, a database, or an external service — at the same time. The system uses a queuing mechanism to coordinate this safely, so two agents aren't making conflicting changes simultaneously.
>
> If one agent is waiting for access and it's taking longer than expected, how long should the system wait before flagging it for your attention?
>
> Based on how your system is designed, I'd suggest **[recommended timeout]**. [One-sentence rationale — e.g., "Your agents mostly work in sequence, so a 30-second wait is long enough to catch a real problem without false alarms" or "With several agents running in parallel, 2 minutes gives the system room to work through normal queue wait times before escalating."]
>
> Does that work for you, or would you prefer a different threshold?

**Wait for answer.**

- If the user accepts the recommendation: confirm the value and proceed.
- If the user chooses differently: accept it without pushback and record the preference.
- If the user is unsure: "Start with my recommendation — you can adjust it once the system is running and you can see how often conflicts come up."

Write the configured value to the staging file: `GATE_CONFLICT_TIMEOUT = [value in seconds or minutes]`.

---

## START-1 — Deferred alert threshold [FIXED — topic]

**Say:**

> When the system sends you an alert and you're not ready to deal with it right away, you can defer it — it stays in the queue and comes back at your next session.
>
> If you keep deferring the same alert without resolving it, at some point the system should flag that it needs a real decision rather than another postpone.
>
> **How many times should you be able to defer an alert before it gets escalated?**
>
> I'd recommend **three deferrals**. That gives you a few sessions to get to it naturally, but stops an unresolved issue from quietly sitting in the queue indefinitely.

**Wait for answer.**

- If the user accepts three: confirm "Three deferrals before escalation."
- If the user chooses differently: confirm their choice. If they choose a higher number, note it's fine but some alerts may go longer without resolution.
- If the user asks what "escalation" means here: "The system marks it as overdue and moves it to a higher-priority position so it leads your next session rather than sitting at the bottom of the list."

Write the configured value to the staging file: `DEFERRED_ALERT_THRESHOLD = [number]`.

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

> Last set of questions before we wrap up. These help me understand the scale your system will need to operate at — not technical details, just how your business actually works.

Ask each question in sequence. Wait for the answer before moving to the next.

**SCALE-1:**

> How many clients, customers, or records does your business actively work with?

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

## Success condition

CONC-1, CONC-2, START-1, START-2, DRIFT-1, and SCALE-1 through SCALE-4 complete. Scale tier written to `technical_architecture.md` and `project_instructions.md`. All configured values written to the staging file. `OPERATIONS_CONFIGURED = true` in the staging file. Proceed to `14_document_review.md`.
