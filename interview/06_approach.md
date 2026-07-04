# 06: Approach Document

## What this file does
Gather the approach content (how the system will work, and a first-pass sense of the agents it will need) by presenting a derived proposal grounded in the vision and the approach-level content buffer, and capturing the operator's reaction. This step **records the approach content to the event transcript**; it does **not** write an `approach.md` file and does **not** finalize the approach. The approach document is part of the `approach_roster` group, which is derived, shown to the operator as a rendered draft, confirmed, and closed at the end of step 08 (after the agent roster is captured). The `approach.md` file itself is emitted at the end of the interview by the generator, not written here.

## When this file runs
After `05_vision.md` completes and the vision group is confirmed (`group_vision_confirmed`).

## Prerequisites
`group_vision_confirmed` recorded in `~/claude-wizard-draft/wizard_progress.md`. Approach-level content buffer active from the vision interview.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 06_approach.md. VISION_CONFIRMED = true. Read the vision document on disk and the staging file at `~/claude-wizard-draft/wizard_session_draft.md`, then continue from where you left off."

Do not begin AP-1 until you are confident the full phase (including draft, revision round, and disk write) will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_06_*` (e.g., `step_06_AP-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker. Do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_06: complete`) is not, proceed directly to the success condition.

---

## Foundation-only-mode entry guard

Before doing anything else in this step:

1. **Schema-version check (per handoff contract consumer rule).** Read `~/claude-wizard-draft/wizard_session_draft.md`; locate the `schema_versions` block under shape_hypothesis. Verify `schema_major == 1`. If `schema_major` mismatches the consumer expected major (currently `1`), abort with operator-facing internal-state error: "I hit a wizard-internal version mismatch. The staging file's shape-detection schema major is `<actual>`, but this version of the wizard expects major `1`. Your project file is saved. Please update the wizard OR resume with the matching wizard version." Exit cleanly; do NOT proceed.

2. Locate the `shape_hypothesis.fallback_mode_offered` field.

3. Consult `wizard/interview/_foundation_only_mode_gate.md` § 2 derivation rule. Determine:
   - `produce_foundation_docs` (boolean)
   - `produce_system_implementation` (boolean)
   - `capture_implementation_inputs` (boolean)
   - `honest_characterization_disclosure` (enum value)

4. Branch:
   - If `produce_system_implementation == true` (label is `complete` OR `not_offered`): follow the rest of this file's existing step content below this entry guard (the wizard's normal behavior for this step).
   - If `produce_system_implementation == false` AND `produce_foundation_docs == true` (label is `foundation-only`): skip the existing step content and follow the section titled `## Foundation-only adapted path` at the end of this file.
   - If `produce_foundation_docs == false` (label is `scope-out`): wizard-internal-state error: wizard should have exited at the unsupported-shape transition; do NOT proceed past this step. Halt with internal-error message; foundation state preserved.

5. If `fallback_mode_offered` is missing from staging file entirely: wizard-internal-state error. Halt with internal-error message; foundation state preserved. Tell operator: "I hit an internal state error in the wizard. The shape hypothesis is missing. Your project file is saved at `~/claude-wizard-draft/wizard_session_draft.md`. Please resume the wizard; it'll pick up at the right step." Exit cleanly.

---

## Operator Interaction Contract

Before you present the approach proposal below, read `wizard/interview/_operator_interaction_contract.md` and apply it: ground the proposal in the operator's confirmed vision and the approach-level content buffer, plain voice, no filler. Because this step records the operator's reaction, record only what they confirm or adopt, not your own proposed specifics (contract § 3).

---

## Step opening: progress and preview

**Say:**

> **Step 7 of 16: Approach**
> I'll draft how your system will work based on everything you've told me so far. No new questions, just review and confirm.

---

## What the approach document is

The approach document is the solution brief: how the system described in the vision document will actually work. It bridges vision ("what and why") and architecture ("what agents, what structure"). It is derived entirely from what the user has already said; nothing new is requested here.

The approach document contains two sections:

1. **Solution brief**: how the system turns vision into operational reality: the overall approach, key processes, any technology or mechanics the user described, and how the pieces fit together
2. **Agent roster (preliminary)**: a first-pass list of the agents the system will need, drawn from the vision and the approach buffer. This roster is refined and confirmed in detail during the architecture phase (`08_architecture.md`). It is not finalized here

---

## Recording answers (event transcript)

This step records the approach content to the **event transcript** at `~/claude-wizard-draft/wizard_transcript.jsonl`, tagged to the `approach_roster` group, in addition to the staging file. The transcript is the authoritative record the system is built from; the staging file is the human-readable mirror. The approach content captured here (AP-1/AP-2/AP-3) feeds two derivations at the step-08 barrier: the approach solution brief and the agent intents. Keep writing the staging file and the sub-step markers exactly as before. The transcript runs alongside them.

---

## AP-1/AP-2/AP-3: Present the approach proposal, capture the operator's content [DYNAMIC]

Do not ask the operator to invent an approach from a blank slate (wizard proposes, user confirms). Instead **propose a derived approach, then capture how the operator reacts**, and record that content as the three approach source answers.

**Derive a proposal from two sources** (do not write it to a file):
1. The confirmed vision (the vision fields the operator confirmed at step 05)
2. The approach-level content buffer accumulated during the vision interview: everything the operator said about implementation, technology, process, or mechanics

If the buffer is thin, derive a reasonable first-pass approach from the vision alone. Thin is fine. This is a living document that the architecture step elaborates.

**Present the proposal and invite reaction:**

> Here's how I think your system will work, based on everything you've told me: the overall approach, the key things it'll do day to day, and a first sense of the helpers (agents) it'll need. Take a look and tell me what's right, what's off, and anything missing. We'll firm this up together once we've sketched the agents in the next step.
>
> [Present, in plain language: (1) the overall solution approach; (2) the key processes / how the agents will work day to day; (3) how the pieces fit together. Plus a preliminary one-line-per-agent roster. No jargon. Do not pad or invent specifics not grounded in the vision or what the operator said.]

**Wait for the operator's reaction.** Accept everything; incorporate their adjustments into your understanding.

**Record the approach content as three source answers** (the operator's confirmed/adjusted content, mapped to the three facets the solution brief covers; draw from their reaction plus the approach buffer; thin is fine, do not fabricate):

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid AP-1 --group approach_roster --value "<the overall solution approach, in the operator's framing>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid AP-2 --group approach_roster --value "<the key processes / how the agents will work day to day>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid AP-3 --group approach_roster --value "<how the pieces fit together>"
```

Write sub-step markers as each facet is captured: append `step_06_AP-1: complete | <timestamp>`, `step_06_AP-2: complete`, `step_06_AP-3: complete` to `~/claude-wizard-draft/wizard_progress.md`.

**Do NOT write an `approach.md` file here, and do NOT finalize the approach.** The approach solution brief and the agent roster are derived, rendered as a draft for the operator to confirm, and the `approach_roster` group is closed at the end of step 08 (after the agent roster is captured). The `approach.md` file is emitted at the end of the interview by the generator.

**Say:**

> Got it. I've captured your approach. Next we'll bring in any outside advisors or reference sources, then sketch the agents, and right after that I'll show you the finished approach to confirm.

Update the staging file (human-readable mirror): APPROACH_CAPTURED = true.

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 06.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 06.

**If neither condition is true:** Skip this section entirely. Do not show any prompt.

---

## Success condition

The approach content is recorded to the transcript as the three `approach_roster` source answers (AP-1/AP-2/AP-3). **No `approach.md` file was written.** The approach is derived, confirmed, and closed at the step-08 barrier, and the file is emitted by the generator at the end. APPROACH_CAPTURED = true in the staging file. (The `approach_roster` group is NOT closed here; it closes at step 08, so do not record `group_approach_roster_confirmed` yet.)

**Write completion marker:** Append `step_06: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `07_advisors.md`.

---

## Foundation-only adapted path

**Disposition: PRODUCE.**

In foundation-only mode, this step's behavior is identical to the normal path. Approach is a foundation-level artifact; shape-agnostic; the same propose / capture-source-answers flow applies (and, as in the normal path, no `approach.md` is written here; it is emitted at the end through the generator's foundation-only branch). The approach document is one of the four foundation docs per `_foundation_only_mode_gate.md` § 5.

**Write completion marker + proceed:** same as normal path (`step_06: complete | <timestamp>`; proceed to `07_advisors.md`).
