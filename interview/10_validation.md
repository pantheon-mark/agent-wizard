# 10 — Input Validation

## What this file does
Configure the validation gate — the layer that checks everything coming into the system before agents act on it. Claude proposes the input type inventory and domain sensitivity settings from the confirmed vision, approach, and architecture content (read from the transcript; the docs are not on disk yet). The user confirms and adjusts but does not design. The answers are recorded to the transcript and pre-populate the generated `quality/validation_gate_config.md` at close — nothing is written mid-interview.

## When this file runs
After `09_credentials.md` completes: `step_09: complete` is in `~/claude-wizard-draft/wizard_progress.md`. The staging-file `CREDENTIALS_CONFIRMED` mirror is a human-readable convenience, not the gate.

## Prerequisites
`step_09: complete` in `~/claude-wizard-draft/wizard_progress.md`, and `group_vision_confirmed` + `group_approach_roster_confirmed` recorded in `~/claude-wizard-draft/wizard_transcript.jsonl`. The vision and approach/architecture content is confirmed in the transcript; the foundation documents themselves are emitted by the generator at close (`15_close.md`), so they are not on disk yet — read the confirmed content from the transcript, not from disk files.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 10_validation.md. Confirm `step_09: complete` in `~/claude-wizard-draft/wizard_progress.md`. Read the staging file and the confirmed vision/approach/architecture content from `~/claude-wizard-draft/wizard_transcript.jsonl` (the foundation docs are not on disk yet — they emit at close), then continue from where you left off."

Do not begin GATE-1 until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_10_*` (e.g., `step_10_GATE-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_10: complete`) is not, proceed directly to the success condition.

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

Before the validation questions below, read `wizard/interview/_operator_interaction_contract.md` and apply it — ground the proposed input inventory and sensitivity settings in the operator's vision, approach, and architecture, keep the ask balanced, plain voice, no filler.

---

## Step opening — progress and preview

**Say:**

> **Step 11 of 16 — Input validation**
> We'll configure how carefully the system checks incoming data before acting on it.

---

## How to run this phase

Read the confirmed vision, approach, and architecture content from the transcript (`~/claude-wizard-draft/wizard_transcript.jsonl`) before speaking — the foundation documents are not emitted to disk until close, so the transcript is the source. Build a complete candidate list of input types and domain areas from everything you find — every source of data, every user action, every external feed the agents will receive.

**The user does not design the validation configuration.** You propose it. They confirm, remove, or adjust.

Note: agent-to-agent handoffs are not routed through the validation gate. This gate governs inputs arriving at the system boundary — from external sources, users, and integrations.

---

## GATE-1 — Input type inventory [DYNAMIC]

Present the proposed input type inventory. For each input: what it is, why it needs to be checked, and what could go wrong without the check.

**Say:**

> Before your agents start working, everything coming into the system gets checked — to catch problems before they cause bad outputs.
>
> Here's every type of input I see your system receiving, based on your vision, approach, and architecture:
>
> **[Input type plain-language name]**
> [What it is — one sentence.] It needs to be checked because [specific risk — e.g., "customer names can contain formatting that breaks downstream reports" or "dates can be ambiguous without a format check"]. Without the check, [what could go wrong].
>
> **[Repeat for each input type.]**
>
> Does this list look complete? Is there anything you'd expect the system to receive that isn't here?

**Wait for answer.**

- If the user confirms: proceed to GATE-2.
- If the user removes an input type: note the implication briefly ("Understood — that source won't be checked on the way in") and update the list.
- If the user adds an input type: add it with a proposed name, description, and check rationale. Confirm before proceeding.
- If an input source is uncertain: mark it as pending. Note it clearly. It must be resolved before the system runs fully.
- **If your analysis produces zero external input types** (the system processes only internally generated data with no external sources or user inputs at the system boundary): present this to the user: "Based on your vision and architecture, your system receives all data internally — no external sources or user-provided inputs cross the system boundary. Is that right?" If confirmed, write `VALIDATION_CONFIGURED = true` and `INPUT_TYPE_COUNT = 0` to the staging file. There are no domain areas to configure, so in the Recording section below record GATE-1 = `"none (internal-only system; no external inputs)"` and GATE-2 = `"none (no external input domains)"` (NOT skips — the `tests_audit` group derives `INPUT_TYPE_INVENTORY` + `DOMAIN_SENSITIVITY_SETTINGS` as mandatory targets, and these "none" answers derive to valid EMPTY tables; a skip would leave the targets unprojected and the group could not close). Proceed to GATE-3 and GATE-4 (the override and pushback explanations still apply to internal validation). Note that input types can be added later when integrations are expanded.

Write sub-step marker: Append `step_10_GATE-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## GATE-2 — Domain sensitivity configuration [DYNAMIC]

For each domain area in the confirmed vision, approach, and agent roster: propose a sensitivity level with a one-sentence rationale. The user confirms, adjusts, or asks questions.

**Sensitivity levels:**
- **Low** — Flag only clear structural problems. Let borderline inputs through with a note.
- **Medium** — Flag structural problems and unusual patterns. Ask the user to confirm anything that looks off.
- **High** — Flag structural problems and anything semantically unexpected. Pause and ask before acting on flagged inputs.

**Say:**

> The system can be more or less cautious depending on the area. Some domains are more sensitive than others — a wrong date in a financial calculation is more dangerous than a wrong date in a blog post draft.
>
> Here's what I'm proposing for your system:
>
> | Domain area | Sensitivity | Why |
> |-------------|-------------|-----|
> | [Domain name] | Low / Medium / High | [One sentence rationale] |
> | [Repeat for each domain area] | | |
>
> Does this match your expectations? If any area feels too strict or too loose, tell me and I'll adjust.

**Wait for answer.**

- If the user confirms: proceed.
- If the user adjusts a sensitivity level: update it and note the user's reasoning in the config. Confirm before proceeding.
- If the user asks what a sensitivity level means in practice: give a concrete example using their domain ("At High, if your system receives a client name that contains characters it hasn't seen before, it will pause and ask you before using it in a report. At Low, it would use it and flag it in the log.").

The confirmed input inventory (GATE-1) and domain sensitivity (GATE-2) are *recorded* to the transcript in the Recording section at the end of this step — nothing is written to a project directory mid-interview. The `quality/validation_gate_config.md` file is generated at close (`15_close.md`), pre-populated from these recorded answers via the `INPUT_TYPE_INVENTORY` + `DOMAIN_SENSITIVITY_SETTINGS` derived fields.

Write sub-step marker: Append `step_10_GATE-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## GATE-3 — Override behavior [EXPLANATION]

**Say:**

> When the system flags something and you tell me you meant it, I'll accept it and note it down.
>
> If you find yourself doing that a lot in the same area — the system keeps flagging things you're fine with — that's a signal the sensitivity is set too high for that area. You can lower it any time by just telling me.
>
> Over time, the system learns what you normally accept in each area and gets better at telling the difference between a real problem and a pattern you've already signed off on.

**Wait for any questions, then proceed.**

Write sub-step marker: Append `step_10_GATE-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## GATE-4 — Hard vs. soft pushback [EXPLANATION]

**Say:**

> Two types of problems get handled differently.
>
> **Things the system won't accept until fixed:** If something is structurally wrong — the wrong format, a missing required field, data that can't be parsed — the system will stop and tell you what's broken. It won't try to proceed with broken input.
>
> **Things the system flags and asks you about:** If something looks unusual but could be intentional, the system will describe what it found and ask you to confirm before continuing. You can say "yes, I meant that" and it will proceed — and note that you approved it.
>
> The first kind protects you from silent failures. The second keeps you in control without stopping work unnecessarily.

**Wait for any questions, then proceed.**

Write sub-step marker: Append `step_10_GATE-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Confirm validation configuration (no mid-interview disk write)

After GATE-1 through GATE-4, do NOT write any file to a project directory. The project directory does not exist yet (it is created at close), and writing one here would crash the close-emit's non-empty-target guard. The `quality/validation_gate_config.md` file is generated at close from the GATE-1/GATE-2 answers you record in the next section — the `INPUT_TYPE_INVENTORY` and `DOMAIN_SENSITIVITY_SETTINGS` derived fields pre-populate the emitted file's input-type inventory and domain-sensitivity tables. (The emitted file's structural rules column and an Override Log section populate at runtime.)

**Say:**

> Validation is configured. Here's what that means in practice:
>
> - **[n] input types** your system will check before agents act on them
> - [**[n] sources** still pending — those will need to be confirmed before the system runs fully] *(omit if none pending)*
> - Sensitivity settings: [list domains and levels in one line, e.g., "Financial: High, Content: Medium, Admin: Low"]
>
> Next we'll configure how the system handles errors and quality issues.

Update staging file: VALIDATION_CONFIGURED = true (a staging convenience flag; the configuration itself lives in the recorded GATE-1/GATE-2 answers and is emitted at close).

Write sub-step marker: Append `step_10_WRITE: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Recording answers (event transcript)

Record this step's `tests_audit` source answers to `~/claude-wizard-draft/wizard_transcript.jsonl`. GATE-1 (input-type inventory) and GATE-2 (domain sensitivity) carry operator content that feeds the agent-specific tests; GATE-3 (override behavior) and GATE-4 (hard vs soft pushback) are explanations with no derivation source content, recorded as skips (registry skip-satisfied):

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid GATE-1 --group tests_audit --value "<input type inventory>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid GATE-2 --group tests_audit --value "<domain sensitivity configuration>"
python3 wizard/scripts/interview_cli.py skip-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid GATE-3 --group tests_audit --reason "override behavior explanation; no derivation source content"
python3 wizard/scripts/interview_cli.py skip-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid GATE-4 --group tests_audit --reason "hard vs soft pushback explanation; no derivation source content"
```

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 10.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 10.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

GATE-1 through GATE-4 complete. GATE-1 (input type inventory) and GATE-2 (domain sensitivity) recorded to the transcript as `tests_audit` source answers (they derive into `INPUT_TYPE_INVENTORY` + `DOMAIN_SENSITIVITY_SETTINGS` at the group barrier and pre-populate the generated `quality/validation_gate_config.md` at close); GATE-3/GATE-4 recorded as skips. VALIDATION_CONFIGURED = true in the staging file (convenience flag). Nothing written to a project directory mid-interview.

**Write completion marker:** Append `step_10: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `11_error_handling.md`.

---

## Foundation-only adapted path

**Disposition: ADAPT — capture validation rules as foundation section; skip implementation config file.**

Conduct the validation interview from the existing step content above (GATE-1 through GATE-4; Claude proposes input types + domain sensitivity from vision + approach + architecture).

**Difference from normal behavior:**

DO NOT:

- Write `/quality/validation_gate_config.md` (quality directory is implementation-specific in foundation-only mode)

DO:

- Conduct the validation questions and capture answers
- Append captured validation rules to the staging file under `## Foundation-only-mode captures > Validation rules` (input types + sensitivity classifications + pushback behavior preferences)

At step 15 close, the captured validation rules extract to `technical_architecture.md` § "Operational requirements" > "Validation rules" per `_foundation_only_mode_gate.md` § 5.

**Write completion marker:** Append `step_10: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `11_error_handling.md`.
