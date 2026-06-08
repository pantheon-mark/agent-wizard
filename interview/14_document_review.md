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
> "Resume wizard from 14_document_review.md. OPERATIONS_CONFIGURED = true. Read the staging file, then continue from where you left off."

Do not begin DOC-1 until you are confident the full phase will complete before compaction risk. (This phase is brief — compaction risk here is low.)

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_14_*` (e.g., `step_14_DOC-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_14: complete`) is not, proceed directly to the success condition.

---

## Foundation-only-mode entry guard

Before doing anything else in this step:

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

## Operator Interaction Contract

Before the two explanations below, read `wizard/interview/_operator_interaction_contract.md` and apply it — plain voice, no filler. If you show the operator any rendered document or change summary to review, write it to a reviewable file they open in a viewer (§ 4).

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

Write sub-step marker: Append `step_14_DOC-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## DOC-2 — Change summary [EXPLANATION]

**Say:**

> Every time the system updates one of your documents, your digest will include a plain-language note — what changed, why it changed, and what the document says now that's different from before.
>
> You'll never open a document and wonder why it looks different from the last time you saw it. The system always explains itself.

No response required. Proceed directly to the success condition.

Write sub-step marker: Append `step_14_DOC-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

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

---

## Foundation-only adapted path

**Disposition: ADAPT — adapt document review to the 4-file foundation doc set; skip system-level document review.**

Deliver the document review explanations adapted for the foundation-only mode document set per `_foundation_only_mode_gate.md` § 5:

**Documents covered (foundation-only output):**

- `vision.md`
- `approach.md`
- `technical_architecture.md`
- `execution_plan.md`
- `project_instructions.md` (foundation-only voice)
- `manual.md` (pointer doc)
- `next_steps.md` (NEW; path-forward guidance)

**Documents NOT covered (foundation-only mode does not produce):**

- `test_cases.md`, `audit_framework.md` (implementation-validation-shape; not foundation per `_foundation_only_mode_gate.md` § 5)
- Agent files, scripts, `.env`, `.gitignore`, `start-session.sh`, `session_bootstrap.md` (implementation per § 5)
- No `/docs/`, `/agents/`, `/quality/`, `/work/`, `/logs/`, `/security/` directories

**Adapted DOC-1 (document sync):**

Briefer; foundation docs sync via direct edits. Drift-detection mechanisms designed for the full system are NOT installed in foundation-only mode (no `/quality/`, no validation gate). The foundation docs are self-contained; operator edits them directly if requirements change. Tell operator:

> The foundation docs in your project directory are self-contained. If your requirements change, edit the docs directly. There's no automated drift detection in foundation-only mode — the wizard installs that with the system implementation, which we're deferring per the foundation-only mode path you chose earlier.

**Adapted DOC-2 (change communication):**

Briefer; foundation docs do not have automated change-summary tooling. Operator's path forward (direct-Claude-Code build OR wait-for-v2) decides whether change-tracking matters. Tell operator:

> Change-tracking tooling for the foundation docs is up to you. If you take these docs to Claude Code directly to build the implementation, ask Claude Code to set up change-tracking for you at that time. If you wait for v2 wizard shape support, change-tracking is installed at re-run.

DO:

- Append captured document review acknowledgment to the staging file under `## Foundation-only-mode captures > Document review acknowledgment`

**Write completion marker:** Append `step_14: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `15_close.md`.
