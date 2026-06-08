# 01 — Phase 1: Immediate Capture

## What this file does
Establish the basics, in an order a non-technical operator can actually follow: the system's **purpose** first; then a **light definition pass** that sketches what it'll involve; then a **proposed name**; then the project draft file that persists through the interview; and finally a short **grouped beat of capability questions** that establish what kind of system to build. This is a help-you-think orientation, not a blank-slate form — every beat after the purpose is grounded in what the operator already said. No wrong answers.

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

Do not begin the first question (P1-2 — core purpose) until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_01_*` (e.g., `step_01_P1-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the project draft file.

If all sub-step markers for this step are present but the step-level marker (`step_01: complete`) is not, proceed directly to the success condition.

---

## Step opening — progress and preview

**Say:**

> **Step 2 of 16 — The basics**
> Let's get the foundation down: what you want this to do, a quick sketch of what it'll involve, a name for it, and a few short questions about how it should work. Nothing here is locked in — we go deeper in later steps.

---

## Operator Interaction Contract

This step has real conversational beats (the definition sketch, the proposed name, the capability questions). Before running them, read `wizard/interview/_operator_interaction_contract.md` and apply it to every one — it is the canonical voice + grounding + recording rule and takes precedence over the prompt wording below. For this step in particular: open each beat with substance (the sketch, the name, or the question itself), never with affirmation or empathy filler, and keep the proposals you make distinct from what the operator actually adopts (contract § 3).

---

## Step 0 — Resume check (run before asking any questions)

Before the first question (P1-2), check whether a prior wizard session exists:

**Run:** Check if `~/claude-wizard-draft/wizard_session_draft.md` exists.

**If the file does NOT exist:** proceed silently to the first question (P1-2 — core purpose). Do NOT announce "starting fresh" — a first-time operator has no prior session to reconcile, and surfacing it mid-interview reads as a spurious resume concern.

> *Internal note: the authoritative resume handling runs at session-init (`wizard/CLAUDE.md` "How to start", before step 00), which already covers both the progress-marker case and the draft-file-existence case. This in-step check is a redundant backstop. Its full removal + the per-project-identity / explicit "new vs. continue [named project]" redesign are tracked as the separate **F3** sub-item; silencing the no-session announcement is the clean part that belongs with the front-door redesign and is done here.*

**If the file EXISTS — say this to the user:**

> I found an earlier wizard session. Here's what was captured:
>
> **Project name:** [read PROJECT_NAME from the file]
> **Purpose:** [read CORE_PURPOSE from the file]
> **Last completed step:** [read RESUME_FROM from the file]
>
> Would you like to continue from where you left off, or start fresh? (Say "continue" or "start fresh".)

**If user says "continue":** Read the full draft file. Identify RESUME_FROM. Skip all completed steps and resume from the indicated question ID. Update LAST_UPDATED in the draft file.

**If user says "start fresh":** Delete the existing draft file. Proceed to P1-2 (the first question) normally.

**Note on draft location:** The draft directory `~/claude-wizard-draft/` is at the home directory level (not inside Documents) to avoid slow startup indexing caused by Claude Code scanning large document folders.

---

## P1-2 — Core purpose [ASKED FIRST]

Purpose is the anchor everything else hangs off — the definition sketch, the proposed name, and the capability questions are all grounded in it. So it comes first, before the name.

**Ask the user:**

> In your own words — what is this system going to do for you? One sentence is plenty, but say as much as you like.

Accept any answer. One sentence is the goal but do not push back if they give more. If they give significantly more than one sentence, accept it gracefully and use the most purpose-focused sentence for the core purpose field. The full answer is preserved in the project draft file.

**Store:** CORE_PURPOSE = the user's answer

Write sub-step marker: Append `step_01_P1-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record to the event transcript** (the raw answer; the vision step derives `CORE_PURPOSE` from it later):

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid P1-2 --group vision --value "<the operator's one-sentence purpose>"
```

---

## Light definition pass — sketch what it'll involve

This is the orientation beat. Before naming or any capability questions, help the operator *see the shape of what they're describing*: propose a concrete first cut of what the system would involve, grounded in the purpose they just gave, then let them react. It is a proposal to react to, not a blank-slate ask (operating rule #5), and it is the anchor the name and the capability questions hang off — without it, those land without grounding.

**Propose, grounded in the purpose:**

Draft a short, plain-language sketch from the operator's purpose — a few key things the system might do, plus a rough sense of what's in and out of scope. Keep it concrete and illustrative, and be explicit that it's a starting sketch, not a fixed list. Example shape (adapt to their actual purpose; do not reuse verbatim):

> From what you said, here's a rough sketch of what this might involve — tell me what's right, what's off, and what's missing:
>
> - It would [key thing 1, in their terms]
> - It would probably [key thing 2]
> - It sounds like [X] is in scope, and [Y] is probably out — for now
>
> Does that match what you're picturing? What would you add, drop, or change?

**Wait for answer.** Accept whatever they say.

- If they confirm or adjust: fold their changes in. The result is the **working definition**.
- If they add things: capture them. Operator-provided lists are examples, never exhaustive — proactively name anything obvious that seems missing, framed as a "for instance," not as the answer.
- If they can't react meaningfully yet: that's fine. Keep the sketch light and proceed; the vision step (05) deepens it.

**Keep sources distinct (anti-bias).** What the operator actually said is their intent; what *you* proposed is a suggestion until they adopt it. When you write the working definition, do not silently convert your own suggested features into "what the operator wants" — keep anything they didn't explicitly confirm marked as a proposal (e.g., "(suggested — confirm later)"). This matters because the capability questions below are framed by the working definition: if a wizard-invented capability reads as operator intent, it can bias those answers.

Hold the working definition now — it is written to the staging file in P1-3 (under `## Working definition`) and **carried forward to the vision step (05), which deepens it rather than re-asking** (operating rule #9). Do NOT record it to the event transcript: it shapes the vision-step conversation and the framing of the beats below, not a generated field directly.

Write sub-step marker: Append `step_01_DEF: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## P1-1 — Propose the name [FOLLOWS PURPOSE]

Now that there's a working sketch, **propose** a name rather than asking the operator to invent one cold — a non-technical operator can't easily name a project before they've seen its shape, which is why this follows the purpose and definition (operating rule #5). Keep it low-stakes and reversible.

**Propose, grounded in the purpose / definition:**

> Based on that, I'll call it **"[proposed name]"** for now — you can rename it anytime, it's not locked in. Want to keep that, or call it something else?

Derive a short, plain proposed name from the purpose / working definition (e.g., a college-planning helper → "College Planner"; a client-deliverable tracker → "Deliverable Tracker"). If the operator offers their own name, use theirs. Accept any name — there are no wrong answers. Short names, long names, names with spaces are all fine.

The name will be used to create the project folder, so note that spaces will become hyphens in the folder name (e.g. "My Business System" → `my-business-system`). Mention this only if the chosen name contains spaces. The project folder will be created at `~/[folder-name]` — directly in the home directory. This keeps the project isolated so Claude Code starts up quickly. Do not use `~/Documents/` as the default location.

**Store:**
- PROJECT_NAME = the confirmed name (display name)
- PROJECT_FOLDER_NAME = lowercase version with spaces replaced by hyphens and special characters removed
- PROJECT_PATH = `~/` + PROJECT_FOLDER_NAME (e.g. `~/my-business-system`)

Write sub-step marker: Append `step_01_P1-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record to the event transcript** (the confirmed name; the vision step derives `PROJECT_NAME` from it later — a proposed-then-confirmed name records identically to a typed one, so downstream derivation is unchanged):

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid P1-1 --group vision --value "<the confirmed project name>"
```

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
[P1-2] Core purpose: [value]
[P1-1] Project name: [value]

## Working definition
[The working definition agreed in the light definition pass — the key things the system would do, plus rough in/out-of-scope. Carried forward to the vision step (05), which deepens it rather than re-asking. Human-readable mirror only; not recorded to the event transcript.]
```

3. After writing the file successfully, **say this to the user:**

> I've created your project draft. Everything you tell me from here is saved as we go — if this session ever ends unexpectedly, we can pick up exactly where we left off.

Write sub-step marker: Append `step_01_P1-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Capabilities beat — P1-4 through P1-7b (one grouped beat)

These questions establish what kind of system you're building, in behavior-based terms — what it needs to *do*, never technology choices. Ask them as **one grouped beat**, and frame each by the working definition the operator just sketched. The wizard uses these answers (plus context from later steps) to decide which kind of system to generate. Canonical spec: `wizard/shape_detection.md` § 2.1 (experiential capabilities beat).

**Internal note (per `wizard/shape_detection.md` § 9 — decision-E v1).** Scan the operator's purpose answer (P1-2) and the working definition for shape-signal phrases (e.g., "newsletter that goes out every Monday" / "something to think ideas through with" / "a place my team logs in"). Capture any matched phrases verbatim under `shape_hypothesis.forward_offered_signals_at_step_01:` in the staging file. These signals may **frame** a question ("Based on the newsletter you mentioned…") but must NEVER pre-fill an answer or skip a question — every question is always asked, and the operator's explicit answer is what gets recorded. Do not collapse "not sure" into "no."

**Lead-in to operator:**

> A few quick questions about how this should work — there are no wrong answers, and "not sure" is a perfectly good answer to any of them. They're independent, so any mix is fine.

Ask the questions below as one beat. **Default to one at a time, in this order** — for a non-technical operator that lands more clearly than a wall of questions, and it cuts mapping mistakes; only ask several together if the operator is clearly moving fast. Each resolves to a stored `probe_N` value (the runtime question is one *leveled* pick that derives two values). For the yes/no questions: accept **yes / no / unsure**; if the operator gives a qualified answer ("only sometimes" / "ideally yes but not required"), ask one follow-up to resolve to yes/no/unsure ("So is that more of a yes or a no?"); if still genuinely uncertain after one follow-up, store `unsure`.

**Apply the Operator Interaction Contract § 2 (Grounding) to the capability beat** — ground each question in what the operator already told you, balanced so both a yes and a no sound natural, examples frame and never pre-fill (this beat is the highest bias-risk one; the `shape_detection.md` § 9 anti-bias guardrail binds). For example, turn the generic "Will other people use it, with their own access?" into something like "Will [the specific person they named] sign into this and use it directly, with her own access — or are you the only one working in it, and you pass along what she needs to see?" — grounded and balanced so neither answer is the obvious one. Step-specific: the "Ask the user" column below is the canonical **meaning plus neutral fallback wording** (use it verbatim only when you have no context to ground from); the runtime question (2) keeps its three contrastive levels exactly, and only its cadence examples may be grounded.

| # | Ask the user | Store | Marker |
|---|---|---|---|
| 1 | "Will you want to chat with it or ask it questions directly — bring it things to think through?" | `probe_3_thinking_partner = yes \| no \| unsure` | `step_01_P1-6` |
| 2 (**leveled** — read the three and let them pick; "not sure" is fine) | "How does this need to run? — **(a) Only when you come to it** — you open it and ask when you need something. **(b) On a schedule** — it wakes at set times (like each morning, or a few times a day), does its work, sends you what it found, and is done until next time. **(c) All the time** — it has to stay on constantly and react within seconds the moment something happens." | `runtime_mode = on-demand \| scheduled \| always-on \| unsure` → derive `probe_1_scheduled_cadence` + `probe_9_always_on` (see derivation below) | `step_01_P1-4` |
| 3 | "Will other people use it, with their own access?" | `probe_2_multi_user = yes \| no \| unsure` | `step_01_P1-5` |
| 4 (**outbound**) | "Does it need to **reach out to your apps or accounts when it runs** — read your calendar, update your sheet, send an email? (**read or write** both count.)" | `probe_4_external_software = yes \| no \| unsure` | `step_01_P1-7` |
| 5 (**inbound**) | "Does it need to **receive things from other systems live** — let other people or apps connect to it, get live updates or alerts pushed in, or have people sign in to it as part of using it day-to-day? (Just setting it up once with your own accounts does NOT count.)" | `probe_10_inbound_serve = yes \| no \| unsure` | `step_01_P1-7b` |

**Frequency clarifier (question 2, only if they pick "(b) On a schedule").** Ask one short follow-up: "Roughly how often — a few times a day, hourly, or more often than that?" If the answer implies very frequent / near-real-time wakeups (every few minutes), gently note it's still buildable but worth knowing: "That's doable, but running it that often costs more to operate and can hit usage limits — we can revisit the cadence later." This stays on the scheduled (markdown-friendly) path; it is NOT an off-ramp. Capture the rough cadence verbatim under `## Early mentions` tagged `[→ step 13]` (scale tuning).

**Runtime-level → derived values (question 2).** Record the operator's pick, then derive:

| Operator picks | `probe_1_scheduled_cadence` | `probe_9_always_on` |
|---|---|---|
| (a) Only when you come to it | no | no |
| (b) On a schedule | yes | no |
| (c) All the time | no | yes |
| Not sure | unsure | unsure |

After each question is answered, store its value(s) in the staging `shape_hypothesis.operator_signals` block and append its marker to `~/claude-wizard-draft/wizard_progress.md`. The `probe_N` ↔ marker mapping is fixed (it preserves the downstream contract): question 1 → `probe_3` / `P1-6`; question 2 → runtime (`probe_1_scheduled_cadence` + `probe_9_always_on`) / `P1-4`; question 3 → `probe_2` / `P1-5`; question 4 → `probe_4` (outbound) / `P1-7`; question 5 → `probe_10_inbound_serve` / `P1-7b`. (Presentation order keeps the markers tied to their probe; the experiential order reads more naturally.)

**Record the RAW runtime answer (question 2) to the event transcript** — qid `P1-4`, group `orchestration_build` (it informs the orchestration / execution-cadence derivation at the step-13 barrier; the on-demand-vs-scheduled distinction is exactly what that derivation needs, and recording the raw mode keeps the always-on case in the transcript without a separate qid). The other dimensions are stored to the staging-file `shape_hypothesis` block only, not the transcript:

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid P1-4 --group orchestration_build --value "<runtime_mode: on-demand | scheduled | always-on | unsure>"
```

Once all five questions are answered (markers `step_01_P1-4`, `P1-5`, `P1-6`, `P1-7`, `P1-7b` written and the P1-4 transcript record made), proceed to P1-8. On resume: if any of the five markers is missing, re-run the whole beat (re-confirm already-answered dimensions quickly from the staging `shape_hypothesis` block rather than treating them as new).

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
  schema_major: 1 # (2026-06-02): bumped 0→1 — probe_1 renamed to probe_1_scheduled_cadence; probe_9_always_on + probe_10_inbound_serve added
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
  probe_1_scheduled_cadence: <stored value> # derived from runtime_mode (yes only for "On a schedule")
  probe_2_multi_user: <stored value>
  probe_3_thinking_partner: <stored value>
  probe_4_external_software: <stored value> # outbound; shape-neutral
  probe_5_state_memory: not_asked
  probe_6_regular_pattern: not_asked
  probe_7_operator_confirm: not_asked
  probe_8_document_output: not_asked
  probe_9_always_on: <stored value> # derived from runtime_mode (yes only for "All the time")
  probe_10_inbound_serve: <stored value>
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
  schema_major: 1 # (2026-06-02): bumped 0→1 — probe_1 renamed to probe_1_scheduled_cadence; probe_9_always_on + probe_10_inbound_serve added
  schema_minor: 0
  shape_taxonomy_version: 0
  stop_condition_set_version: 0
  control_matrix_schema_version: 0

handoff_phase: provisional_shape_emit

shape_hypothesis:
  status: pending_step_02_fallback
  step_01_signals:
  probe_1_scheduled_cadence: <stored value>
  probe_2_multi_user: <stored value>
  probe_3_thinking_partner: <stored value>
  probe_4_external_software: <stored value>
  probe_9_always_on: <stored value>
  probe_10_inbound_serve: <stored value>
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
