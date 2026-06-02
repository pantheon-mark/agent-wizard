# 05 — Vision Document

## What this file does
Conduct the vision document interview. Ask the six question categories that define the vision document: purpose, goals, audience and outputs, scope boundary, constraints, and success criteria. Check for genuinely absent categories and ask one follow-up per absent category if needed. Draft the vision document, present it with explicit one-round framing, incorporate one round of changes, confirm, and write to disk. Carry any approach-level content surfaced during this interview forward to seed the approach document.

## When this file runs
After `04_notifications.md` completes and both notification channels (NTFY and email) are confirmed.

## Prerequisites
NTFY_CONFIRMED = true and EMAIL_CONFIRMED = true in the staging file.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 05_vision.md. NTFY_CONFIRMED = true and EMAIL_CONFIRMED = true. Read the staging file at `~/claude-wizard-draft/wizard_session_draft.md`, then continue from where you left off."

**Important:** The vision interview is the most open-ended phase of the wizard. Do not begin it unless you are confident the full interview — including field derivation, the rendered-preview confirmation round, and the group close — will complete before compaction risk. If there is any doubt, clear context first.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_05_*` (e.g., `step_05_V-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_05: complete`) is not, proceed directly to the success condition.

---

## Pre-step-05 re-check (shape-detection re-evaluation + 4 stop conditions)

Before any step-05 user-facing question fires, run `wizard/interview/_pre_step_05_recheck.md`. This module re-evaluates the provisional `shape_hypothesis` against accumulated context (steps 02-04 answers + step 03 UP-6 regulatory exposure), evaluates the 4 stop conditions, and triggers the unsupported-shape transition if shape revises to non-v1-supported.

**The re-check is mandatory.** Hard stop before vision generation — shape and stop conditions must be resolved here.

If `step_05_pre_recheck: complete` is already in `~/claude-wizard-draft/wizard_progress.md` (e.g., resuming a partial step 05), skip the pre-recheck and proceed to the step opening. Otherwise, run the pre-recheck module first.

After pre-recheck completes successfully (no halt; no scope-out): proceed to the foundation-only-mode entry guard below.

---

## Foundation-only-mode entry guard

*(Placement note — per `_foundation_only_mode_gate.md` § 3: this entry guard MUST run AFTER the pre-step-05 re-check above, because the re-check can mutate `shape_hypothesis.fallback_mode_offered` via the unsupported-shape transition. An entry guard run BEFORE the re-check would branch on stale state.)*

Before any step-05 user-facing question fires:

1. **Schema-version check (per handoff contract consumer rule).** Read `~/claude-wizard-draft/wizard_session_draft.md`; locate the `schema_versions` block under shape_hypothesis. Verify `schema_major == 1`. If `schema_major` mismatches the consumer expected major (currently `1`), abort with operator-facing internal-state error: "I hit a wizard-internal version mismatch — the staging file's shape-detection schema major is `<actual>`, but this version of the wizard expects major `1`. Your project file is saved. Please update the wizard OR resume with the matching wizard version." Exit cleanly; do NOT proceed.

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

> **Step 6 of 16 — Your vision**
> This is the heart of the interview — we'll define what your system is going to do and why. Take your time here.

---

## How to run this interview

The six questions are conversational — not a form. The user may answer in any order, blend categories, or volunteer information across multiple categories in a single answer. Accept everything. Do not redirect the user or ask them to stay on topic.

**Voice — human but real, never performative.** Match the plain, direct, calm voice of `about.md`. The wizard shows it is listening by *grounding each proposal in what the operator already said* — not by narrating that it heard them. Do NOT open answers with acknowledgment filler ("Got it!", "I hear you", "Great — that makes sense") or by reflecting the operator's words back as a standalone beat. Those read as fake and AI-ish and erode trust faster than plain directness. Move from a grounded proposal straight into the question.

**Maintain an internal approach-level content buffer throughout.** Any time the user says something about implementation, technology, process, or mechanics ("I imagine it would work by...", "I was thinking the agents could..."), note it internally but do not react to it or ask follow-up questions about it here. This buffer is carried forward after the vision is confirmed — it seeds the approach document draft. The user will not be asked to repeat themselves.

**Read the working definition carried forward from step 01.** Before V-1, read the `## Working definition` section from `~/claude-wizard-draft/wizard_session_draft.md`. At step 01's light definition pass, the wizard sketched the system's key features and rough scope and the operator reacted to it — that sketch is the starting point this step **deepens**, not re-opens. Use it to ground the vision questions — **not only V-1/V-2 (purpose/goals) but also V-3 (audience/outputs) and especially V-4 (scope boundary)**: the in/out-of-scope the operator confirmed at step 01 lives ONLY in this staging section (it was deliberately not written to the event transcript), so the recorded V-answers are the wizard's one chance to carry it into the foundation docs. When you propose V-3/V-4, ground them on what the operator already sketched so that confirmed scope is not silently dropped. Do NOT ask the operator to define the system from scratch, and do NOT read the definition back to them as a recap (acknowledgment filler reads as fake — operating-voice rule above); show you're building on it by making your proposals concrete and specific to what they sketched. The vision step turns that working definition into the six vision categories; it does not restate it.

---

## Recording answers (event transcript)

This step records each answer to an **event transcript** at `~/claude-wizard-draft/wizard_transcript.jsonl` in addition to the staging file. The transcript is the authoritative record the system is built from; the staging file is the human-readable mirror used for resume. After each question below is answered, record it:

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid <Q-ID> --group vision --value "<the operator's answer>"
```

If a conditional question (V-7 follow-up, V-7b) is validly skipped, record the skip instead:

```
python3 wizard/scripts/interview_cli.py skip-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid <Q-ID> --group vision --reason "<why it was skipped>"
```

Keep writing the staging file and the sub-step markers exactly as before — the transcript runs alongside them, it does not replace them.

---

## V-1 — Purpose [FIXED]

**Ask:**

> In your own words — what problem does this system solve for you, or what would it make possible that you can't do now?

**Wait for answer.** Accept any response. The user may answer briefly or at length. Do not prompt for elaboration unless the category is genuinely absent (handled in V-7).

Note internally which of the six categories have been addressed as the user speaks.

Write sub-step marker: Append `step_05_V-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## V-2 — Goals, objectives, and priorities [DYNAMIC]

**Before asking:** Read the staging file to retrieve the user's project purpose (P1-2), the `## Working definition` carried forward from step 01, and the user profile (step 03 answers — role, availability, domain, involvement level). Use these to construct a concrete day-to-day scenario grounded in what the operator already sketched.

**Propose a scenario, then ask the user to react:**

> Based on what you've told me so far, here's what I think a typical day might look like once this system is running:
>
> [Draft a 2–3 sentence scenario grounded in the user's stated purpose and profile. Example for a parent managing college planning: "You check your phone over coffee and see a digest — your system monitored three scholarship deadlines overnight and flagged one that closes this week. There's a draft email to the guidance counselor ready for your review. The research agent found two new programs that match your criteria and added them to the list." Example for a small business owner: "You start your morning with a summary — two client deliverables were completed overnight, one is blocked waiting for a vendor response, and there's a draft follow-up ready for your approval."]
>
> Does that feel right? What would you change about that picture — and if you had to name the one or two most important outcomes, what would they be?

**Wait for answer.**

- If the user confirms the scenario with adjustments: note adjustments and capture as goals.
- If the user redirects to a different picture entirely: accept the redirect — their version replaces the proposal.
- If the user can't react meaningfully: that's fine — note what they did say and proceed. V-7b will catch vague answers later.

Write sub-step marker: Append `step_05_V-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## V-3 — Audience and outputs [FIXED]

**Ask:**

> Who will use or benefit from what this system produces — just you, or others? What form do you expect its outputs to take — reports, alerts, processed data, decisions made on your behalf?

**Wait for answer.**

Write sub-step marker: Append `step_05_V-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## V-4 — Scope boundary [FIXED]

**Ask:**

> We're still early — you haven't seen what the system can do yet, so you don't need a complete boundary map. But are there any areas you already know are out of bounds? Things you're sure you don't want this system involved in, or decisions it should never touch?
>
> It's fine if the answer is "not yet" — these boundaries naturally refine once you see the system taking shape.

**Wait for answer.**

- If the user names boundaries: capture them as initial scope constraints.
- If the user says "not yet" or "I'm not sure": acknowledge that's expected at this stage. Note scope boundary as "to be refined during architecture and build" and proceed. Do not press for an answer.

Write sub-step marker: Append `step_05_V-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## V-5 — Constraints [DYNAMIC]

**Before asking:** Read the staging file to retrieve the user's Tier 1 decision confirmations from step 04 (NOTIF-3) and any Tier 1 additions (TIER_1_ADDITIONS). These are rules the user has already confirmed — do not re-ask them.

**Present what's already captured, then ask for additions:**

> You've already locked in some rules for this system in the notification step. Here's what you told me it must always stop and ask about:
>
> [Read back the confirmed Tier 1 baseline items and any TIER_1_ADDITIONS from the staging file. Present as a bulleted list — e.g., "Spending money," "Sending messages on your behalf," "Irreversible actions," plus any user additions.]
>
> Beyond those — are there other rules this system should always follow, or other things it should never do? For example, data it should never access, topics it should stay away from, or actions specific to your situation that should always require your approval.

**Wait for answer.**

- If the user adds new constraints: capture them. These are vision-level constraints, distinct from but complementary to the Tier 1 operational rules.
- If the user says the Tier 1 list covers it: acknowledge and proceed. Note V-5 constraints as "covered by Tier 1 rules" in the staging file.
- Do not re-present or re-confirm the Tier 1 items themselves — they were already confirmed in step 04.

Write sub-step marker: Append `step_05_V-5: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## V-6 — Success criteria [FIXED]

**Ask:**

> How will you know in six months whether this system was worth building?

**Wait for answer.**

Write sub-step marker: Append `step_05_V-6: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## V-7 — Completeness check [DYNAMIC]

Before drafting, run an internal check across the six categories:

1. Purpose
2. Goals, objectives, and priorities
3. Audience and outputs
4. Scope boundary
5. Constraints
6. Success criteria

**The bar is absent, not thin.** A category addressed even partially — even indirectly — is present. Only ask a follow-up if a category received nothing at all from the user's answers across all six questions.

For each genuinely absent category, ask one targeted follow-up question. Maximum one follow-up per absent category. Then draft regardless of how thin any individual category is after follow-ups.

**Example follow-ups by category (use judgment — these are not fixed):**

- Purpose: *"Before I draft this, I want to make sure I have the right anchor — what's the main thing you're hoping this system will do for you?"*
- Goals: *"What would a win look like for you once this is running?"*
- Audience/outputs: *"Who else, if anyone, will see what this system produces?"*
- Scope boundary: *"Are there any areas you already know you don't want this system involved in?"*
- Constraints: *"Beyond the rules you already set in the notification step — any other things this system should always or never do?"*
- Success criteria: *"How would you know in six months whether this was worth it?"*

If all six categories are present (even thinly), skip V-7 entirely and proceed to the vague-answer check below.

Write sub-step marker: Append `step_05_V-7: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## V-7b — Vague-answer detection [DYNAMIC]

**This is distinct from V-7.** V-7 catches absent categories. V-7b catches categories that are *present but too vague to build from* — answers like "be more efficient" or "help me stay organized" that technically address a category but give the wizard nothing concrete to derive agent work from.

After V-7 follow-ups (or after skipping V-7), scan the user's answers for purpose and goals categories specifically. If either answer is so vague that you could not propose a specific agent task from it, ask one concrete anchoring question:

> You've given me a good sense of direction. To make sure I build the right thing, let me ask one more question:
>
> **If you could hand off one specific task starting tomorrow — something you actually do right now that takes time or attention — what would it be?**

**Wait for answer.**

This question is designed to produce a concrete, actionable anchor even when the user can't articulate a grand vision. One real task is enough to derive the first agent from.

- If the answer gives a concrete task: note it as the primary anchor for the agent roster. Proceed to drafting.
- If the answer is still vague ("just general help"): accept it and proceed to drafting. The approach document (step 06) and architecture (step 08) will provide additional opportunities to ground the system. Do not press further here.

**If purpose and goals are already concrete enough to derive agent work from:** skip V-7b entirely and proceed to drafting.

Write sub-step marker: Append `step_05_V-7b: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## V-8 — Derive the vision fields, render the preview, confirm, close the group [DYNAMIC]

The vision answers are complete. Instead of hand-writing a vision document and saving it to disk now, **derive the vision FIELDS, show the operator the rendered vision draft, take one round of changes, and close the vision group.** The vision document file is emitted by the generator at the end of the interview — not written here.

### Step 1 — Derive the vision fields

Derive each vision field from the recorded answers, using the matching class derivation prompt (`wizard/foundation-bundles/v0/derivation-prompts/<class>.md`) and the field manifest (`wizard/foundation-bundles/v0/field-manifests/markdown-CC.json`, which names each field's class and the question-IDs that feed it). All vision fields are **extraction** class — preserve the operator's own words; do not polish or invent. Sort the answers into the six categories; thin is fine; do not pad or fabricate.

Fields: `PROJECT_NAME` and `CORE_PURPOSE` (from P1-1 / P1-2 recorded at step 01), `VISION_PURPOSE`, `VISION_GOALS`, `VISION_AUDIENCE_OUTPUTS`, `VISION_SCOPE_BOUNDARY`, `VISION_CONSTRAINTS`, `VISION_SUCCESS_CRITERIA`.

For each, record the derived value (the command assembles the audit envelope from the manifest + the class prompt — you supply only the value and the question-IDs you actually drew from):

```
python3 wizard/scripts/interview_cli.py derive-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field VISION_PURPOSE --value "<derived value, in the operator's words>" --sources V-1
```

### Step 2 — Constraint elevation

Scan the confirmed vision constraints. If any names a rule the system must **always stop and ask about** (a top-level always-ask rule), derive `TIER_1_ADDITIONS` — a policy field: state both what is permitted and what is forbidden. Record it with `derive-field --field TIER_1_ADDITIONS --sources V-5,V-7`. If the constraints contain no such rule, skip this step. These additions are carried forward into the later approval-rules step.

### Step 3 — Render the preview and show the operator

```
python3 wizard/scripts/interview_cli.py preview-group --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --group vision --source-version v0.4.0 --build-repo-root <path to the wizard build repo root> --auto SYSTEM_SHAPE=markdown-CC --auto FOUNDATION_ONLY_MODE=<false|true> --auto WIZARD_VERSION=v0.4.0 --auto LAST_UPDATED_DATE=<today> --auto LAST_UPDATED_TRIGGER="initial build" --auto CURRENT_SPRINT_NUMBER=1
```

Show the operator the **rendered vision markdown** the command prints — the actual document they will receive, not the field values.

### Step 4 — One round of changes, then confirm

Say exactly this before the operator responds:

> Here's your vision document based on what you've told me. Take a look and tell me anything that's wrong or missing — you have one round of changes here. The system keeps this document current as things evolve, so anything else that comes up later is easy to update. Good enough to build from is the right standard here, not perfect. What would you like to change, if anything?

**Wait for answer.**

- **No changes:** confirm each field — `python3 wizard/scripts/interview_cli.py confirm-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field <FIELD> --group vision --state accepted`.
- **Changes:** incorporate them into the affected field(s), re-derive those fields (Step 1), then confirm with the edited value — add `--state accepted --value "<edited value>"`. Re-render the preview once (Step 3) to show the updated draft, then confirm. Do not open a second round.

The one-round limit is set before the operator responds — it cannot be renegotiated after the fact.

### Step 5 — Close the vision group

```
python3 wizard/scripts/interview_cli.py close-group --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --progress ~/claude-wizard-draft/wizard_progress.md --shape markdown-CC --group vision
```

This records the `group_vision_confirmed` marker (carrying the source hash). The group cannot close unless every vision field is confirmed. **Do NOT write `step_05: complete` until this succeeds** — a step marker before its group is confirmed is an illegal state.

**Do NOT write a `vision.md` file here.** The vision document is emitted by the generator at the end of the interview from the confirmed transcript; the operator has already seen and confirmed the rendered draft (Steps 3–4).

**Say:**

> Vision confirmed. This is the anchor your system will build from — everything else references it. It stays current as your goals evolve.

Update the staging file (human-readable mirror): VISION_CONFIRMED = true.

Write sub-step marker: Append `step_05_V-8: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

### Step 6 — Carry forward approach content

Do not discard the approach-level content buffer maintained during this interview. Note it internally — it seeds the approach group in the next interview file. Do not mention the buffer to the user or ask them to confirm it here.

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 05.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 05.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

V-1 through V-8 complete. The vision fields are derived, the operator has confirmed the rendered draft, and the vision group is closed (`group_vision_confirmed` recorded). VISION_CONFIRMED = true in the staging file. **No `vision.md` was written — the generator emits it at the end.** Approach content buffer active and ready to carry forward.

**Write completion marker:** Append `step_05: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`. (Only after `group_vision_confirmed` is recorded — the step marker is illegal before its group closes.)

Proceed to `06_approach.md`.

---

## Foundation-only adapted path

**Disposition: PRODUCE.**

In foundation-only mode, this step's behavior is identical to the normal path. Vision is a foundation-level artifact; shape-agnostic; the same questions (V-1 through V-8), the same derive / render-preview / one-round confirmation / group-close flow apply (pass `--auto FOUNDATION_ONLY_MODE=true` to the preview command). No `vision.md` is written here in either mode; the vision document is emitted at the end — in foundation-only mode through the generator's foundation-only branch.

Follow the existing step content above. The vision document is one of the four foundation docs per `_foundation_only_mode_gate.md` § 5.

The honest-characterization disclosure that distinguishes foundation-only mode is delivered at step 15 close (per `_foundation_only_mode_gate.md` § 4); no per-step disclosure required here.

**Write completion marker + proceed:** same as normal path (`step_05: complete | <timestamp>`; proceed to `06_approach.md`).
