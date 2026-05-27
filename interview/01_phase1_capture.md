# 01 — Phase 1: Immediate Capture

## What this file does
Capture the project name and core purpose — the two pieces of information the user knows immediately. Then create the project draft file that persists through the entire wizard interview. Fast, zero-friction, no wrong answers.

## When this file runs
Immediately after `00_env_check.md` passes. No project directory exists yet.

## Prerequisites
All four environment checks in `00_env_check.md` have passed.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: no project files exist yet to save. Tell the user:

> Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Start the wizard from phase 1 capture. The environment check has passed. Run `01_phase1_capture.md`, then continue from where you left off."

Do not begin P1-1 until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_01_*` (e.g., `step_01_P1-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the project draft file.

If all sub-step markers for this step are present but the step-level marker (`step_01: complete`) is not, proceed directly to the success condition.

---

## Step opening — progress and preview

**Say:**

> **Step 2 of 16 — Project basics**
> Two quick questions — your project name and what it's going to do for you.

---

## Step 0 — Resume check (run before asking any questions)

Before P1-1, check whether a prior wizard session exists:

**Run:** Check if `~/claude-wizard-draft/wizard_session_draft.md` exists.

**If the file does NOT exist:** Say "No previous session found — starting fresh." Then proceed to P1-1.

**If the file EXISTS — say this to the user:**

> I found an earlier wizard session. Here's what was captured:
>
> **Project name:** [read PROJECT_NAME from the file]
> **Purpose:** [read CORE_PURPOSE from the file]
> **Last completed step:** [read RESUME_FROM from the file]
>
> Would you like to continue from where you left off, or start fresh? (Say "continue" or "start fresh".)

**If user says "continue":** Read the full draft file. Identify RESUME_FROM. Skip all completed steps and resume from the indicated question ID. Update LAST_UPDATED in the draft file.

**If user says "start fresh":** Delete the existing draft file. Proceed to P1-1 normally.

**Note on draft location:** The draft directory `~/claude-wizard-draft/` is at the home directory level (not inside Documents) to avoid slow startup indexing caused by Claude Code scanning large document folders.

---

## P1-1 — Project name

**Ask the user:**

> What would you like to call this project?

Accept any name the user gives. No validation needed — there are no wrong answers here. Short names, long names, names with spaces are all fine. The name will be used to create the project folder, so note that spaces will become hyphens in the folder name (e.g. "My Business System" → `my-business-system`). Mention this only if the name contains spaces.

The project folder will be created at `~/[folder-name]` — directly in the home directory. This keeps the project isolated so Claude Code starts up quickly. Do not use `~/Documents/` as the default location.

**Store:**
- PROJECT_NAME = the user's answer (display name)
- PROJECT_FOLDER_NAME = lowercase version with spaces replaced by hyphens and special characters removed
- PROJECT_PATH = `~/` + PROJECT_FOLDER_NAME (e.g. `~/my-business-system`)

Write sub-step marker: Append `step_01_P1-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## P1-2 — Core purpose

**Ask the user:**

> In one sentence — what is this system going to do for you?

Accept any answer. One sentence is the goal but do not push back if they give more. If they give significantly more than one sentence, accept it gracefully and use the most purpose-focused sentence for the core purpose field. The full answer is preserved in the project draft file.

**Store:** CORE_PURPOSE = the user's answer

Write sub-step marker: Append `step_01_P1-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## P1-3 — Create project draft file [INTERNAL]

Do not ask the user anything. Perform these steps silently, then show one confirmation line.

**Steps:**

1. Create the directory `~/claude-wizard-draft/` if it does not already exist.

2. Write `~/claude-wizard-draft/wizard_session_draft.md` with the following content:

```
# Wizard Session Draft

PROJECT_NAME: [value from P1-1]
CORE_PURPOSE: [value from P1-2]
STARTED: [current date and time]
LAST_UPDATED: [current date and time]
RESUME_FROM: FIN-1

## Environment check
All four prerequisite checks passed.
- Homebrew: [version found]
- Git: [version found]
- Node.js: [version found]
- Claude Code: [version found]

## Captured answers
[P1-1] Project name: [value]
[P1-2] Core purpose: [value]
```

3. After writing the file successfully, **say this to the user:**

> I've created your project draft. Everything you tell me from here is saved as we go — if this session ever ends unexpectedly, we can pick up exactly where we left off.

Write sub-step marker: Append `step_01_P1-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Shape-detection probes — P1-4 through P1-7

The next four questions establish what kind of system you're building, in behavior-based terms. These are NOT about technology choices — they're about what the system needs to *do*. The wizard uses these answers (plus context from later steps) to decide which kind of system to generate.

The probes follow the canonical spec at `wizard/shape_detection.md` § 2.1.

**Internal note (per `wizard/shape_detection.md` § 9):** scan the operator's P1-2 core-purpose answer for shape-signal phrases (e.g., "automated newsletter every Monday" / "thinking partner for X" / "customer portal where my team logs in"). Capture any matched phrases verbatim under `shape_hypothesis.forward_offered_signals_at_step_01:` in the staging file. Probes still fire — forward-offered signals are interpretive prior only, not authoritative answers.

**Lead-in to operator:**

> Four quick yes/no/unsure questions about what your system needs to do. There are no wrong answers — this is just helping me understand what to build.

---

### P1-4 — Continuous-runtime probe

**Ask the user:**

> Does the system need to keep running on its own, even when you're not using Claude?

**Accept:** yes / no / unsure. If operator gives a qualified answer ("only sometimes" / "ideally yes but not required"), ask one follow-up to resolve to yes/no/unsure: "So is that more of a yes or a no?" If genuinely uncertain after one follow-up, store as `unsure`.

**Store:** `probe_1_continuous_runtime = yes | no | unsure`

Write sub-step marker: Append `step_01_P1-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

### P1-5 — Multi-user probe

**Ask the user:**

> Will other people use this system — and need their own logins or different views?

**Accept:** yes / no / unsure. Same one-follow-up resolution pattern as P1-4.

**Store:** `probe_2_multi_user = yes | no | unsure`

Write sub-step marker: Append `step_01_P1-5: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

### P1-6 — Thinking-partner probe

**Ask the user:**

> Is it mainly something you'll work on WITH Claude — like a thinking partner you bring questions to?

**Accept:** yes / no / unsure. Same one-follow-up resolution pattern.

**Store:** `probe_3_thinking_partner = yes | no | unsure`

Write sub-step marker: Append `step_01_P1-6: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

### P1-7 — External-software probe

**Ask the user:**

> Does it need to talk to other software automatically — like getting prices, sending emails, checking accounts?

**Accept:** yes / no / unsure. Same one-follow-up resolution pattern.

**Store:** `probe_4_external_software = yes | no | unsure`

Write sub-step marker: Append `step_01_P1-7: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

### P1-8 — Classifier emit [INTERNAL]

Do not ask the operator anything in this sub-step. Apply the classifier per `wizard/shape_detection.md` § 2.3 + § 3:

1. Tally strong-positive and strong-negative signals per shape across Probes 1-4 using the signal-to-shape decision table at § 2.3
2. Compute confidence (HIGH / MEDIUM / LOW) per § 3 rubric
3. If confidence is HIGH: emit shape hypothesis NOW (write `## Shape detection` section to staging file with `detected_at_step: 01`)
4. If confidence is MEDIUM or LOW: defer emit; the staging file gets a placeholder entry `shape_hypothesis.status: pending_step_02_fallback`; fallback probes 5-8 fire at end of step 02

**Emit format** (HIGH-confidence case at step 01 — append to staging file after `## Captured answers` section). Finalized emits MUST include `schema_versions`, `handoff_phase`, AND `shape_hypothesis.status: emitted`:

```yaml
## Shape detection

schema_versions:
  schema_major: 0
  schema_minor: 0
  shape_taxonomy_version: 0
  stop_condition_set_version: 0
  control_matrix_schema_version: 0

handoff_phase: provisional_shape_emit

shape_hypothesis:
  status: emitted
  shape: <classified shape per § 2.3 table>
  confidence: high
  detected_at_step: 01
  v1_supported: <true if shape == markdown-agents else false>
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals:
  probe_1_continuous_runtime: <stored value>
  probe_2_multi_user: <stored value>
  probe_3_thinking_partner: <stored value>
  probe_4_external_software: <stored value>
  probe_5_state_memory: not_asked
  probe_6_regular_pattern: not_asked
  probe_7_operator_confirm: not_asked
  probe_8_document_output: not_asked
  forward_offered_signals_at_step_01: <list of verbatim phrases captured at P1-2 scan; may be empty list>
  mixed_component_basis: <empty list unless shape == mixed; if shape == mixed, list constituent component shapes detected>
  fallback_mode_offered: not_offered
  emit_timestamp: <ISO 8601 timestamp>
  recheck_log: []
```

**Deferred-emit format** (MEDIUM or LOW at step 01 — write placeholder; step 02 finalizes). Schema versions + handoff phase included even in the deferred state so consumers reading a partially-emitted staging file at this point can identify the contract version:

```yaml
## Shape detection

schema_versions:
  schema_major: 0
  schema_minor: 0
  shape_taxonomy_version: 0
  stop_condition_set_version: 0
  control_matrix_schema_version: 0

handoff_phase: provisional_shape_emit

shape_hypothesis:
  status: pending_step_02_fallback
  step_01_signals:
  probe_1_continuous_runtime: <stored value>
  probe_2_multi_user: <stored value>
  probe_3_thinking_partner: <stored value>
  probe_4_external_software: <stored value>
  step_01_provisional_confidence: <medium | low>
  forward_offered_signals_at_step_01: <list>
  step_01_completed_timestamp: <ISO 8601>
```

Write sub-step marker: Append `step_01_P1-8: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## P1-9 — Unsupported-shape transition (CONDITIONAL; fires only when classifier emits HIGH-confidence non-markdown at step 01)

**Trigger condition (comply with the relevant product spec section honest-disclosure-at-step-02-or-earlier mandate; trigger uses unambiguous field combination):**

- `shape_hypothesis.status == emitted` (P1-8 wrote the field for HIGH-confidence finalized emit) AND `shape_hypothesis.detected_at_step == 01` AND `shape_hypothesis.v1_supported == false` AND `shape_hypothesis.confidence == high`

If trigger does NOT match (markdown-agents emit, OR step 01 deferred to step 02 fallback): SKIP P1-9. Proceed to step 02.

**If trigger matches:** fire the unsupported-shape transition per `wizard/shape_detection.md` § 6 NOW (do not defer to pre-step-05).

Say to operator (verbatim; substitute `<shape X>` with the classified shape in plain language):

> Your project looks like a [shape description in plain language — e.g., "system that needs to keep running on its own and talk to other software automatically" for python-service-operator-facing; "system multiple people will use with their own logins" for node-ui]. v1 of the wizard generates complete systems for one specific shape (markdown agents that you work with through Claude Code on your own machine).
>
> Two options:
>
> **(a) Stop here — wait for a future wizard release.** Your project file is saved at `~/claude-wizard-draft/wizard_session_draft.md`. When the wizard adds support for your shape, we can pick up.
>
> **(b) Foundation-only mode.** I can produce a foundation-doc set for your project — the planning documents (vision, approach, technical architecture, etc.) abstracted from implementation shape. You'd take those docs to Claude Code directly to build the implementation yourself, OR wait for v2 shape support. I won't generate the system implementation itself (no agents, scripts, or run files).
>
> Which would you like? (Say "a" or "b".)

**If operator picks (a) — scope-out:**

Append to staging file:

```yaml
shape_hypothesis:
  fallback_mode_offered: scope-out
  scope_out_timestamp: <ISO 8601>
```

Say: "Saved. Re-run the wizard later when you're ready or when [shape] support is added." Exit cleanly. Do NOT proceed to step 02.

**If operator picks (b) — foundation-only:**

Append to staging file:

```yaml
shape_hypothesis:
  fallback_mode_offered: foundation-only
  foundation_only_offered_timestamp: <ISO 8601>
```

Say: "Foundation-only mode confirmed. I'll continue through the interview to gather what's needed for the foundation documents, but I won't generate the system implementation at the end. Your downstream Claude Code build conversation will use the foundation docs we produce." Proceed to step 02.

Downstream: pre-step-05 re-check evaluates stop conditions in DOCUMENT-path (not HALT-path) per `wizard/shape_detection.md` § 8.5; foundation-doc-insertion of compliance-mismatch text via foundation-only-mode (see `wizard/interview/_foundation_only_mode_gate.md` § 6) (gaps land in `technical_architecture.md` § "Regulatory & compliance gaps (foundation-only mode)" at step 15 close).

Write sub-step marker: Append `step_01_P1-9: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Update rule — applies for the rest of the wizard

After every question answer from this point forward, append a new line to the `## Captured answers` section of `wizard_session_draft.md` in the format:

```
[QUESTION_ID] [Question label]: [Answer]
```

And update `RESUME_FROM` to the ID of the next question not yet answered, and update `LAST_UPDATED` to the current date and time.

This rule applies automatically through all subsequent interview files. It does not need to be re-stated in each file — it is always active once P1-3 completes.

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 01.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 01.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

P1-3 completed, project draft file written, confirmation shown to user.

**Write completion marker:** Append `step_01: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `02_financial.md`.
