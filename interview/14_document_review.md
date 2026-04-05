# 14 — Document Artifacts

## What this file does
Deliver two plain-language explanations of how the system keeps its own documents in sync and how it communicates document changes to the user. No questions, no configuration — both entries are informational only. User does not configure document update behavior; it is fully automatic.

## When this file runs
After `13_operations.md` completes and OPERATIONS_CONFIGURED = true in the staging file.

## Prerequisites
OPERATIONS_CONFIGURED = true in the staging file.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 14_document_review.md. OPERATIONS_CONFIGURED = true. Read the staging file, then deliver the document artifacts explanations."

Do not begin DOC-1 until you are confident the full phase will complete before compaction risk. (This phase is brief — compaction risk here is low.)

---

## Step opening — progress and preview

**Say:**

> **Step 15 of 16 — Document management**
> A quick overview of how your system keeps its own documentation current. Almost there.

---

## DOC-1 — Impact map [EXPLANATION]

**Say:**

> As your system runs, things will change — agents will be added, integrations will be updated, your goals may evolve. When that happens, your supporting documents need to stay current.
>
> Here's how that works:
>
> **When something changes, the system knows which documents to update.** If a new agent is added, the architecture document is updated. If a data source changes, the source registry is updated. If your goals shift, the vision document is flagged for your review. The system has a built-in map of which events trigger which updates — you don't manage this.
>
> **Vision and roadmap updates are always surfaced to you first.** Those documents are anchors — the system will never change them autonomously. It will flag what it thinks should change and wait for your confirmation.
>
> Would you like me to explain any specific part of how document updates work, or are you ready to move on?

**Wait for answer.**

- If the user wants more detail on any part: provide a plain-language explanation. Keep it grounded in examples specific to their system (from the vision document).
- If the user is ready to move on: proceed to DOC-2.

---

## DOC-2 — Change summary [EXPLANATION]

**Say:**

> Every time the system updates one of your documents, your digest will include a plain-language note — what changed, why it changed, and what the document says now that's different from before.
>
> You'll never open a document and wonder why it looks different from the last time you saw it. The system always explains itself.

No response required. Proceed directly to the success condition.

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 14.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 14.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

DOC-1 and DOC-2 delivered. No staging file values to write — this phase is informational only.

**Write completion marker:** Append `step_14: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `15_close.md`.
