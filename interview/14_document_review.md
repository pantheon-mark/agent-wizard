# 14: Document Artifacts

## What this file does
Two parts. DOC-1 is ACTIVE: surface any change-implications left unresolved from earlier in the interview (an edited answer or decision whose downstream effects were not yet reconciled), let the operator decide each (apply / revise / defer / intentional_divergence / freeze), and close the loop. DOC-2 is a plain-language explanation of how document changes work after the system is built (build-time propagation now; run-time detect-and-reconcile later: the system tells the operator about drift, it does not silently rewrite documents). The operator does not configure a document-update engine; they decide the specific changes surfaced to them.

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

Do not begin DOC-1 until you are confident the full phase will complete before compaction risk. (This phase is brief. Compaction risk here is low.)

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_14_*` (e.g., `step_14_DOC-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker; do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_14: complete`) is not, proceed directly to the success condition.

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
   - If `produce_foundation_docs == false` (label is `scope-out`): wizard-internal-state error. The wizard should have exited at the unsupported-shape transition; do NOT proceed past this step. Halt with internal-error message; foundation state preserved.

5. If `fallback_mode_offered` is missing from staging file entirely: wizard-internal-state error. Halt with internal-error message; foundation state preserved. Tell operator: "I hit an internal state error in the wizard. The shape hypothesis is missing. Your project file is saved at `~/claude-wizard-draft/wizard_session_draft.md`. Please resume the wizard; it'll pick up at the right step." Exit cleanly.

---

## Operator Interaction Contract

Before the two explanations below, read `wizard/interview/_operator_interaction_contract.md` and apply it: plain voice, no filler. If you show the operator any rendered document or change summary to review, write it to a reviewable file they open in a viewer (§ 4).

---

## Step opening: progress and preview

**Say:**

> **Step 15 of 16: Keeping your documents consistent**
> Your answers connect to each other: your vision shapes your approach, which shapes what your agents do. This step makes sure that if anything changed during the interview, the documents that depend on it stay consistent. Almost there.

---

## DOC-1: Review any changes that need your decision [ACTIVE]

Your documents are built from your answers, and some answers feed others. When you go back and change an earlier answer (for example, you revise your vision after seeing the approach), the things that were built from it can become inconsistent. The wizard catches that automatically and brings it to you here. It never changes a decision on its own, and it will not build your system while a decision that affects how your agents behave is left undecided.

**Do this:**

1. **Check for unresolved changes.** If, earlier in the interview, you flagged a change to an answer or a decision and the downstream effects were not yet resolved, they are recorded against this transcript. Re-derive the affected items and identify which ones actually changed. (Items that did not actually change are not shown. You only see real changes.)

2. **If there are no unresolved changes:** tell the operator plainly and move on:

   > Nothing changed earlier that needs a decision here. Your documents are consistent. Moving on.

   Then write the sub-step marker and proceed to DOC-2.

3. **If there ARE unresolved changes:** render the change summary to a reviewable file the operator opens in a viewer (per the Operator Interaction Contract § 4), grouped by kind: wording changes versus rules your system follows. For each item, show what it is in plain language (use the operator-facing label, never the raw field name), how it would change, and ask the operator to choose one:

   - **apply**: accept the change
   - **revise**: you edit it yourself
   - **defer**: decide later (note: a rule/decision left deferred will stop your system from being built until you decide)
   - **intentional_divergence**: you want the two to stay different on purpose (recorded with your reason)
   - **freeze**: leave this part as it is and stop here

   Record each decision with the exact command (one per item; fill in the bracketed values):

   ```
   python3 wizard/scripts/interview_cli.py record-impact-disposition --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --change-id [CHANGE_ID] --node-kind field --node-id [FIELD] --disposition [apply|revise|defer|intentional_divergence|freeze]
   ```

4. **Close the loop.** After the operator decides, confirm their original concern is resolved:

   > Does that resolve what you wanted to fix?

   If not, trace it back to the answer it came from (the change summary lists the contributing answers), correct it at the source, and re-run this review from the corrected answer.

> **Why this matters (say only if asked):** Your vision and goals are anchors. The wizard will flag what it thinks should change because of an edit, but it will not change those anchors on its own. You decide every time.

Write sub-step marker: Append `step_14_DOC-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## DOC-2: How changes work after your system is built [EXPLANATION]

**Say:**

> Two honest notes about documents once your system is running:
>
> **While we build (now):** if you change an earlier answer, I catch what depends on it and bring the real changes to you to decide. That is what we just did. Your system will not be built with a decision left undecided.
>
> **After it is built:** if a document gets edited later, your system can notice that it no longer matches what it was built from and tell you, so you can reconcile it. It does not silently rewrite your documents on its own, and it does not run unattended in the background rewriting things. Noticing and telling you is the honest limit today.

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

**If neither condition is true:** Skip this section entirely. Do not show any prompt.

---

## Success condition

DOC-1 and DOC-2 delivered. No staging file values to write. This phase is informational only.

**Write completion marker:** Append `step_14: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `15_close.md`.

---

## Foundation-only adapted path

**Disposition: ADAPT. Adapt document review to the 4-file foundation doc set; skip system-level document review.**

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

> The foundation docs in your project directory are self-contained. If your requirements change, edit the docs directly. There's no automated drift detection in foundation-only mode. The wizard installs that with the system implementation, which we're deferring per the foundation-only mode path you chose earlier.

**Adapted DOC-2 (change communication):**

Briefer; foundation docs do not have automated change-summary tooling. Operator's path forward (direct-Claude-Code build OR wait-for-v2) decides whether change-tracking matters. Tell operator:

> Change-tracking tooling for the foundation docs is up to you. If you take these docs to Claude Code directly to build the implementation, ask Claude Code to set up change-tracking for you at that time. If you wait for v2 wizard shape support, change-tracking is installed at re-run.

DO:

- Append captured document review acknowledgment to the staging file under `## Foundation-only-mode captures > Document review acknowledgment`

**Write completion marker:** Append `step_14: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `15_close.md`.
