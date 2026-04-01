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

## V-2 — Goals, objectives, and priorities [FIXED]

**Ask:**

> When this system is working well, what does that look like for you day-to-day? If you had to name the one or two most important outcomes, what would they be?

**Wait for answer.**

---

## V-3 — Audience and outputs [FIXED]

**Ask:**

> Who will use or benefit from what this system produces — just you, or others? What form do you expect its outputs to take — reports, alerts, processed data, decisions made on your behalf?

**Wait for answer.**

---

## V-4 — Scope boundary [FIXED]

**Ask:**

> What is this system explicitly not responsible for? Are there things that are clearly out of scope — work that belongs elsewhere, decisions it should never make, areas it should stay out of?

**Wait for answer.**

---

## V-5 — Constraints [FIXED]

**Ask:**

> Are there things this system must always do or rules it must always follow? And are there things it should never do — data it should never touch, actions it should never take without asking you first?

**Wait for answer.**

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
- Scope boundary: *"Is there anything you'd want to make sure this system stays out of — decisions it shouldn't make, areas it shouldn't touch?"*
- Constraints: *"Are there rules you'd want the system to always follow — or things it should never do without asking first?"*
- Success criteria: *"How would you know in six months whether this was worth it?"*

If all six categories are present (even thinly), skip V-7 entirely and proceed to drafting.

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

## Success condition

V-1 through V-8 complete. Vision document confirmed by the user and written to `[PROJECT_DIR]/vision.md`. VISION_CONFIRMED = true in the staging file. Approach content buffer active and ready to carry forward. Proceed to `06_approach.md`.
