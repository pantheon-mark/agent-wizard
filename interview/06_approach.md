# 06 — Approach Document

## What this file does
Derive the approach document from the vision document and the approach-level content buffer maintained during the vision interview. There are no user interview questions in this step — Claude drafts internally and presents for confirmation. One round of changes, confirm, write to disk.

## When this file runs
After `05_vision.md` completes and the vision document is confirmed on disk.

## Prerequisites
VISION_CONFIRMED = true in the staging file. Approach-level content buffer active from the vision interview.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 06_approach.md. VISION_CONFIRMED = true. Read the vision document on disk and the staging file at `~/claude-wizard-draft/wizard_session_draft.md`, then continue from where you left off."

Do not begin AP-1 until you are confident the full phase — including draft, revision round, and disk write — will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_06_*` (e.g., `step_06_AP-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_06: complete`) is not, proceed directly to the success condition.

---

## Foundation-only-mode entry guard

Before doing anything else in this step:

1. **Schema-version check (per handoff contract consumer rule).** Read `~/claude-wizard-draft/wizard_session_draft.md`; locate the `schema_versions` block under shape_hypothesis. Verify `schema_major == 0`. If `schema_major` mismatches the consumer expected major (currently `0` at v0), abort with operator-facing internal-state error: "I hit a wizard-internal version mismatch — the staging file's shape-detection schema major is `<actual>`, but this version of the wizard expects major `0`. Your project file is saved. Please update the wizard OR resume with the matching wizard version." Exit cleanly; do NOT proceed.

2. Locate the `shape_hypothesis.fallback_mode_offered` field.

3. Consult `wizard/interview/_foundation_only_mode_gate.md` § 2 derivation rule. Determine:
   - `produce_foundation_docs` (boolean)
   - `produce_system_implementation` (boolean)
   - `capture_implementation_inputs` (boolean)
   - `honest_characterization_disclosure` (enum value)

4. Branch:
   - If `produce_system_implementation == true` (label is `complete` OR `not_offered`): follow the rest of this file's existing step content below this entry guard (the wizard's normal behavior for this step).
   - If `produce_system_implementation == false` AND `produce_foundation_docs == true` (label is `foundation-only`): skip the existing step content and follow the section titled `## Foundation-only adapted path` at the end of this file.
   - If `produce_foundation_docs == false` (label is `scope-out`): wizard-internal-state error — wizard should have exited at the unsupported-shape transition; do NOT proceed past this step. Halt with internal-error message; foundation state preserved.

5. If `fallback_mode_offered` is missing from staging file entirely: wizard-internal-state error. Halt with internal-error message; foundation state preserved. Tell operator: "I hit an internal state error in the wizard. The shape hypothesis is missing. Your project file is saved at `~/claude-wizard-draft/wizard_session_draft.md`. Please resume the wizard; it'll pick up at the right step." Exit cleanly.

---

## Step opening — progress and preview

**Say:**

> **Step 7 of 16 — Approach**
> I'll draft how your system will work based on everything you've told me so far. No new questions — just review and confirm.

---

## What the approach document is

The approach document is the solution brief — how the system described in the vision document will actually work. It bridges vision ("what and why") and architecture ("what agents, what structure"). It is derived entirely from what the user has already said; nothing new is requested here.

The approach document contains two sections:

1. **Solution brief** — how the system turns vision into operational reality: the overall approach, key processes, any technology or mechanics the user described, and how the pieces fit together
2. **Agent roster (preliminary)** — a first-pass list of the agents the system will need, drawn from the vision and the approach buffer. This roster is refined and confirmed in detail during the architecture phase (`08_architecture.md`) — it is not finalized here

---

## AP-1 — Derive and draft [DYNAMIC]

Do not ask the user any questions before drafting.

Draft the approach document from two sources:
1. The confirmed vision document (already on disk at `[PROJECT_DIR]/vision.md`)
2. The approach-level content buffer accumulated during the vision interview — everything the user said about implementation, technology, process, or mechanics

If the approach buffer is thin or empty (the user stayed purely at the vision level during the interview), draft from the vision document alone. Use the vision document's purpose, goals, audience/outputs, scope boundary, and constraints to infer a reasonable first-pass approach. Thin is fine — this is a living document and the architecture phase will elaborate it.

**Approach document structure:**

```
# Approach

## Solution Brief
[How the system turns the vision into operational reality. Key processes,
mechanics, and implementation approach. Written in plain language — not
technical. If the user described how they imagine it working, capture that.
If not, describe a reasonable approach derived from the vision.]

## Agent Roster (Preliminary)
[First-pass list of agents the system will likely need. For each agent:
one sentence on its role. Mark as preliminary — this list is confirmed
and detailed during the architecture phase.]
```

Write in plain language. No jargon. If a section is thin, write what can be derived — even one sentence is valid. Do not pad or invent specifics not grounded in what the user said or what the vision implies.

Write sub-step marker: Append `step_06_AP-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## AP-2 — Present and confirm [DYNAMIC]

Present the draft and say:

> Here's the approach document — this is the bridge between your vision and the system we'll build. It captures how the system will work and the agents it will need. Take a look and tell me anything that's off or missing — you have one round of changes here. This is also a living document, so as the architecture takes shape it will stay current. What would you like to change, if anything?

**Wait for answer.**

- If the user makes no changes: confirm and proceed to AP-3.
- If the user requests changes: incorporate them now. Do not open another round. Confirm the updated draft and proceed to AP-3.

Write sub-step marker: Append `step_06_AP-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## AP-3 — Write to disk

Write the confirmed approach document to:

```
[PROJECT_DIR]/approach.md
```

**Say:**

> Approach document saved. In the next step, we'll work through the architecture in detail — confirming how the agents are organized, what each one does, and what the system can and can't do on its own.

Update the staging file: APPROACH_CONFIRMED = true

Write sub-step marker: Append `step_06_AP-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 06.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 06.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

AP-1 through AP-3 complete. Approach document confirmed by the user and written to `[PROJECT_DIR]/approach.md`. APPROACH_CONFIRMED = true in the staging file.

**Write completion marker:** Append `step_06: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `07_advisors.md`.

---

## Foundation-only adapted path

**Disposition: PRODUCE.**

In foundation-only mode, this step's behavior is identical to the normal path. Approach is a foundation-level artifact; shape-agnostic; the same draft / revision round / disk write applies.

Follow the existing step content above. The approach document is one of the four foundation docs per `_foundation_only_mode_gate.md` § 5.

**Write completion marker + proceed:** same as normal path (`step_06: complete | <timestamp>`; proceed to `07_advisors.md`).
