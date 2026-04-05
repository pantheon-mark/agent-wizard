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
> "Resume wizard from 05_vision.md. NTFY_CONFIRMED = true and EMAIL_CONFIRMED = true. Read the staging file at `~/claude-wizard-draft/wizard_session_draft.md`, then begin the vision document interview."

**Important:** The vision interview is the most open-ended phase of the wizard. Do not begin it unless you are confident the full interview — including draft, revision round, and disk write — will complete before compaction risk. If there is any doubt, clear context first.

---

## Step opening — progress and preview

**Say:**

> **Step 6 of 16 — Your vision**
> This is the heart of the interview — we'll define what your system is going to do and why. Take your time here.

---

## How to run this interview

The six questions are conversational — not a form. The user may answer in any order, blend categories, or volunteer information across multiple categories in a single answer. Accept everything. Do not redirect the user or ask them to stay on topic.

**Maintain an internal approach-level content buffer throughout.** Any time the user says something about implementation, technology, process, or mechanics ("I imagine it would work by...", "I was thinking the agents could..."), note it internally but do not react to it or ask follow-up questions about it here. This buffer is carried forward after the vision document is confirmed — it seeds the approach document draft. The user will not be asked to repeat themselves.

---

## V-1 — Purpose [FIXED]

**Ask:**

> In your own words — what problem does this system solve for you, or what would it make possible that you can't do now?

**Wait for answer.** Accept any response. The user may answer briefly or at length. Do not prompt for elaboration unless the category is genuinely absent (handled in V-7).

Note internally which of the six categories have been addressed as the user speaks.

---

## V-2 — Goals, objectives, and priorities [DYNAMIC]

**Before asking:** Read the staging file to retrieve the user's project purpose (P1-2) and user profile (step 03 answers — role, availability, domain, involvement level). Use these to construct a concrete day-to-day scenario.

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

---

## V-3 — Audience and outputs [FIXED]

**Ask:**

> Who will use or benefit from what this system produces — just you, or others? What form do you expect its outputs to take — reports, alerts, processed data, decisions made on your behalf?

**Wait for answer.**

---

## V-4 — Scope boundary [FIXED]

**Ask:**

> We're still early — you haven't seen what the system can do yet, so you don't need a complete boundary map. But are there any areas you already know are out of bounds? Things you're sure you don't want this system involved in, or decisions it should never touch?
>
> It's fine if the answer is "not yet" — these boundaries naturally refine once you see the system taking shape.

**Wait for answer.**

- If the user names boundaries: capture them as initial scope constraints.
- If the user says "not yet" or "I'm not sure": acknowledge that's expected at this stage. Note scope boundary as "to be refined during architecture and build" and proceed. Do not press for an answer.

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

---

## V-6 — Success criteria [FIXED]

**Ask:**

> How will you know in six months whether this system was worth building?

**Wait for answer.**

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

---

## V-8 — Draft, one round of changes, confirm, write to disk [DYNAMIC]

### Step 1 — Draft

Draft the vision document from everything the user has said. Sort their answers into the six categories. Use plain, non-technical language. Write in the second person ("Your system...") or declarative statements — not as a transcript of the interview. The document should read as a coherent statement of intent, not a Q&A summary.

**Vision document structure:**

```
# Vision

## Purpose
[What problem this solves or what it makes possible]

## Goals, Objectives, and Priorities
[Day-to-day picture of success; the one or two most important outcomes]

## Audience and Outputs
[Who benefits; what form the outputs take]

## Scope Boundary
[What the system is explicitly not responsible for]

## Constraints
[What the system must always do; what it must never do without permission]

## Success Criteria
[How the user will know in six months whether this was worth building]
```

Thin sections are fine. Do not pad, infer, or fabricate. If a category is thin, write what was said — even one sentence is a valid entry.

### Step 2 — Present with explicit one-round framing

Present the draft and say exactly this before the user responds:

> Here's the vision document based on what you've told me. Take a look and tell me anything that's wrong or missing — you have one round of changes here. The system is designed to keep this document current as things evolve, so anything else that comes up during the build is easy to update later. Good enough to build from is the right standard here, not perfect. What would you like to change, if anything?

**Wait for answer.**

- If the user makes no changes: confirm and proceed to Step 3.
- If the user requests changes: incorporate them now. Do not open another round. Confirm the updated draft and proceed to Step 3.

The one-round limit is set before the user responds — it cannot be renegotiated after the fact.

### Step 3 — Write to disk

Write the confirmed vision document to:

```
[PROJECT_DIR]/vision.md
```

Where `PROJECT_DIR` is the system project directory established in Phase 1 (`01_phase1_capture.md`).

**Say:**

> Vision document saved. This is the anchor your system will build from — everything else references it. It's a living document, so when your goals evolve, we update it.

Update the staging file: VISION_CONFIRMED = true

### Step 4 — Carry forward approach content

Do not discard the approach-level content buffer maintained during this interview. Note it internally. It will be used to seed the approach document draft in the next interview file.

Do not mention the buffer to the user. Do not ask them to confirm or review it at this stage.

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

V-1 through V-8 complete. Vision document confirmed by the user and written to `[PROJECT_DIR]/vision.md`. VISION_CONFIRMED = true in the staging file. Approach content buffer active and ready to carry forward.

**Write completion marker:** Append `step_05: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `06_approach.md`.
