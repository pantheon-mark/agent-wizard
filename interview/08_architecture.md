# 08 — Architecture

## What this file does
Present the system architecture for user confirmation in five steps: orchestration model, agent roster, criticality tier assignments, permission summary, and task completion checklists. Claude derives all of these from the confirmed vision, the captured approach, and the advisor list — the user confirms and adjusts, but does not design. This step **records each architecture answer to the event transcript** and, at its end, **closes the `approach_roster` group** (the second logical group): it derives the agents as structured intents, derives the approach solution brief and the agent roster, shows the operator the rendered approach document for one round of confirmation, and closes the group. It does **not** write a `technical_architecture.md` or `approach.md` file — the architecture answers (ARCH-1/4/5) feed groups that close at step 13, and all foundation-doc files are emitted by the generator at the end of the interview.

## When this file runs
After `07_advisors.md` completes.

## Prerequisites
APPROACH_CAPTURED = true and ADVISORS_SEEDED = true in the staging file; `group_vision_confirmed` recorded. The approach source answers (AP-1/2/3) and advisor list (ADV-1) are in the transcript.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 08_architecture.md. APPROACH_CONFIRMED = true and ADVISORS_SEEDED = true. Read the vision document, approach document, advisor knowledge base, and staging file at `~/claude-wizard-draft/wizard_session_draft.md`, then continue from where you left off."

**Important:** The architecture phase involves reading multiple documents and producing a substantial confirmation artifact. Do not begin it unless you are confident the full phase — all five ARCH steps and the disk write — will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_08_*` (e.g., `step_08_ARCH-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_08: complete`) is not, proceed directly to the success condition.

---

## Pre-step-08 re-check (final shape-detection confirmation)

Before any step-08 user-facing question fires, run `wizard/interview/_pre_step_08_recheck.md`. This module re-evaluates the `shape_hypothesis` against accumulated step 05-07 content (vision + approach + advisors). Especially important for emergent-architecture projects (the relevant product spec section; J6 anchored) — the architecture phase frequently reveals shape signals that earlier steps did not surface.

If `step_08_pre_recheck: complete` is already in `~/claude-wizard-draft/wizard_progress.md` (resuming a partial step 08), skip the pre-recheck. Otherwise, run the pre-recheck module first.

After pre-recheck completes successfully (no halt; no scope-out): proceed to the foundation-only-mode entry guard below.

---

## Foundation-only-mode entry guard

*(Placement note — per `_foundation_only_mode_gate.md` § 3: this entry guard MUST run AFTER the pre-step-08 re-check above, because the re-check can mutate `shape_hypothesis.fallback_mode_offered` via the unsupported-shape transition. An entry guard run BEFORE the re-check would branch on stale state.)*

Before any step-08 user-facing question fires:

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

Before any architecture question below, read `wizard/interview/_operator_interaction_contract.md` and apply it — derive and present the orchestration model, agent roster, and approach document grounded in what the operator confirmed; plain voice; record only what they adopt (§ 3). When you render the approach document for confirmation, show it as a reviewable file the operator opens in a viewer (§ 4).

---

## Step opening — progress and preview

**Say:**

> **Step 9 of 16 — How your system is put together**
> I'll walk you through the parts that do the work, how they fit together, and what the system always checks with you about before acting.

---

## How to run this phase

This phase has two kinds of step, run differently:

- **Operator confirm-beats — ARCH-2 (the helpers) and ARCH-4 (what the system does on its own vs. always asks about).** These are about the operator's own work and their control preferences — things a non-technical operator can actually judge. Present them; let the operator confirm, add, or correct.
- **Derive-and-show — ARCH-1 (how the work runs), ARCH-3 (which helpers are most critical), ARCH-5 (how the system knows each is done).** These are engineering judgments a non-technical first-timer has no basis to validate (live evidence: the operator answers "I don't know" / "beats me" to all three). Claude DERIVES and RECORDS them exactly as before — the generator needs them — but does **not** present them as confirm-questions. They are surfaced read-only inside the approach-document preview at the end of this step, where the operator still gets one round to flag anything plainly wrong. Never ask the operator to confirm, rank, or design any of the three.

The operator is never asked to make an architectural decision. When the operator corrects something in a confirm-beat, update the model and continue.

**Recording (event transcript).** Record each architecture value to `~/claude-wizard-draft/wizard_transcript.jsonl`, tagged to the group it feeds: ARCH-1 (orchestration model) → `orchestration_build`; ARCH-2 (agent roster) + ARCH-3 (criticality tiers) → `approach_roster`; ARCH-4 (permission/always-ask summary) → `hitl_autonomy`; ARCH-5 (task completion conditions) → `tests_audit`. The derive-and-show values (ARCH-1/3/5) are recorded the same way — Claude records the value it derived, with no operator-confirmation gate. The record line is shown at the end of each ARCH step below. Do **not** maintain or write a `technical_architecture.md` file here — the architecture is emitted by the generator at the end from the transcript. After ARCH-5, this step closes the `approach_roster` group (derive → render approach.md preview → confirm → close).

---

## Pre-ARCH — Cross-step conflict detection [INTERNAL]

Before presenting any architecture, compare the user's answers across steps 05 (vision), 06 (approach), and the current architecture context. Look for scope drift or contradictions — for example, a user whose vision describes a full-lifecycle system, whose approach focused on one narrow area, and whose architecture questions suggest yet another direction.

**If the vision scope, approach focus, and implied architecture are aligned:** proceed to ARCH-1 without comment.

**If they suggest different systems:** name the discrepancy in plain language before proceeding. Do not ask the user to reconcile the contradiction themselves — propose the most coherent starting point.

**Say:**

> Before we set up the architecture, I want to flag something I noticed across your earlier answers.
>
> Your vision described [summary of vision scope]. Your approach focused on [summary of approach focus]. And the direction we're heading architecturally would build [summary of implied system].
>
> These aren't necessarily in conflict — but they suggest we should start with [proposed starting point] because [one-sentence rationale]. The other directions aren't lost — they become future agents once the core system is running.
>
> Does that starting point make sense to you?

**Wait for answer.**

- If the user confirms: proceed to ARCH-1 with the confirmed scope as the basis for the agent roster.
- If the user redirects: update your understanding to match their preference and proceed.
- If the user asks what the difference means: explain in plain terms which system each direction would produce and what would be deferred.

This check ensures the architecture is built from a coherent foundation rather than silently inheriting unresolved contradictions from earlier steps.

Write sub-step marker: Append `step_08_Pre-ARCH: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## ARCH-1 — Orchestration model [DERIVE-AND-SHOW — internal; no operator question]

Read the vision and approach. **Derive — do NOT ask the operator about — how the work coordinates:** which work is independent (can run in the same cycle) and which is dependency-linked (one part must finish before another), and from that the coordination model — a coordinator runs on the operator's schedule, routes work to the helpers, sequences changes to the shared master list so they don't collide, and brings decisions to the operator.

This is an engineering judgment, not an operator decision. Do NOT present it as a confirm-question — a non-technical first-timer cannot validate work sequencing (live evidence: "I don't know"). Record the derived coordination model. It is surfaced read-only inside the approach-document preview at the close of this step, where the operator can still flag anything plainly wrong. Never name internal parts, collision-handling, or "which part runs when" to the operator at any point in this step.

Write sub-step marker: Append `step_08_ARCH-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:** `python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid ARCH-1 --group orchestration_build --value "<the confirmed workflow/orchestration description>"`

---

## ARCH-2 — Agent roster [DYNAMIC]

Present the proposed agent roster derived from the vision document, approach document, and confirmed orchestration model. The user did not design this roster — Claude did. Present it for genuine review, not rubber-stamp approval.

**Say:**

> Here are the helpers your system will need. For each one I'll tell you what it does, why it's there, and what you'd lose without it.
>
> **[helper name]**
> [One sentence: what it does.] It's there because [why — what gap it fills]. Without it, [what would break or be missing].
>
> **[helper name]**
> [Repeat for each helper.]
>
> Do any of these not make sense? Is there anything you'd expect the system to do that isn't covered here?

**Wait for answer.**

- If the user confirms: proceed.
- If the user questions an agent's inclusion: explain the tradeoff. If the user wants to remove it, remove it and note the implication.
- If the user requests an addition: add it with a proposed name, function, and rationale. Confirm before proceeding.
- If the user asks a question about how an agent works: answer in plain language. Do not go into implementation detail unless asked.

Update the internal roster before proceeding to ARCH-3.

Write sub-step marker: Append `step_08_ARCH-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:** `python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid ARCH-2 --group approach_roster --value "<the confirmed agent roster: each agent's name + what it does + why it exists>"`

---

## ARCH-3 — Criticality tier assignment [DERIVE-AND-SHOW — internal; no operator question]

**Derive — do NOT ask the operator to rank — each helper's criticality tier:**

- **Critical** — if it doesn't finish, the system stops; its work is required before anything else continues.
- **Standard** — if it hits a problem, it flags it and the system keeps going where it can.
- **Supporting** — partial results are fine; the main work completes without it.

Assign conservatively from the confirmed roster + vision: the coordinator and the master-list keeper (the system's backbone) are **Critical**; helpers whose failure should flag-and-continue are **Standard**; helpers that only add value are **Supporting**.

This is a judgment a non-technical first-timer cannot make (live evidence: "beats me"), and it has a mild safety dimension (Critical = halt-on-fail), so the conservative default is deliberate. Do NOT present it as a confirm-question. Record the derived tiers. They appear read-only in the approach-document preview (the roster shows each helper's level), where the operator can still flag anything that looks wrong.

Write sub-step marker: Append `step_08_ARCH-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:** `python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid ARCH-3 --group approach_roster --value "<the confirmed criticality tier per agent: critical / standard / supporting>"`

---

## ARCH-4 — Permission summary [FIXED — topic]

Present what the system will and will not be able to do on its own, in plain language. Do not use technical permission categories.

**Say:**

> Here's what your system will be able to do on its own, and what it will always stop and ask you about first.
>
> **On its own, without asking:**
> [List: read access to specific data sources, write to project files, generate reports, send digests, apply advisor rules already in the knowledge base, etc. — derived from the confirmed agent roster and vision document.]
>
> **Always asks you first:**
> [List: spending money, sending messages on your behalf, irreversible actions, guardrail violations, anything flagged as Tier 1 during notifications setup — plus any additions the user made in NOTIF-3.]
>
> Does this match what you'd expect?

**Wait for answer.**

- If the user confirms: proceed.
- If the user wants to add something to the "always ask" list: note it as an additional Tier 1 item. Update the staging file.
- If the user wants to remove a "always ask" item: the baseline Tier 1 items (spending, external messaging, irreversible actions, guardrail violations, legal/compliance, contradictions) cannot be removed. Explain this clearly and move on.

Write sub-step marker: Append `step_08_ARCH-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:** `python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid ARCH-4 --group hitl_autonomy --value "<the confirmed always-ask additions + autonomous-action summary>"` (this feeds the HITL map derived at the step-13 barrier, alongside the vision-barrier Tier-1 additions).

---

## ARCH-5 — Task completion checklists [DERIVE-AND-SHOW — internal; no operator question]

**Derive — do NOT ask the operator to define — each helper's completion condition:** how the system knows that helper has finished, so it doesn't stop early or keep running with nothing left. Draw each from the helper's role + the operator's own words (e.g., the call-notes helper is done when the call is written up with its reference numbers and the candidate follow-up tasks are queued for the operator's okay).

This is a judgment a non-technical first-timer cannot make (live evidence: "looks right but I don't really know"). Do NOT present it as a confirm-question. Record the derived completion conditions. They appear read-only in the approach-document preview, where the operator can still flag anything that looks wrong.

Write sub-step marker: Append `step_08_ARCH-5: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:** `python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid ARCH-5 --group tests_audit --value "<the confirmed per-agent completion conditions>"`

---

## Close the approach_roster group — derive the agents, render the approach, confirm, close

All of the `approach_roster` group's inputs are now captured (UP-4 at step 03, AP-1/2/3 at step 06, ADV-1 at step 07, ARCH-2/3 here). **Instead of writing `technical_architecture.md` or `approach.md` to disk, derive the approach-group fields, derive the agents as structured intents, show the operator the rendered approach document, take one round of changes, and close the group.** The architecture answers ARCH-1/4/5 belong to groups that close later (at step 13) — they were recorded above and are consumed there. No foundation-doc file is written here; the generator emits them at the end.

The **derive-and-show** values (ARCH-1 coordination, ARCH-3 criticality tiers, ARCH-5 completion conditions) are surfaced **read-only** in the rendered approach document below — the roster shows each helper's level, and the brief reflects how the work runs and how each helper knows it's done. The operator reads them as part of the one-round review and can flag anything wrong, but was never asked to confirm them as standalone questions.

### Step 1 — Derive the agents as structured intents

For each confirmed agent (from ARCH-2 + the criticality tiers from ARCH-3), derive a structured **agent intent** using the agent-intent derivation prompt (`wizard/foundation-bundles/v0/derivation-prompts/agent-intent.md`). The intent captures the agent's MEANING and its resource CLAIMS only — never its filesystem paths, model, cron cadence, or permissions (the generator decides those deterministically from the system shape). Draw each sub-field from the operator's own words (ARCH-2/3 + the approach answers AP-2/AP-3 + the vision); flag thin sub-fields in `insufficiency_flags`; never fabricate.

Record one intent per agent:

```
python3 wizard/scripts/interview_cli.py record-agent-intent --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --group approach_roster --display-name "<agent name>" --function-summary "<one sentence>" --role-intent "<2-4 sentences: why it exists>" --acceptance-signals "<signal 1>;<signal 2>" --output-purpose "<what its output is for>" --criticality-tier <critical|standard|supporting> --confidence <high|medium|low> --source-spans "ARCH-2;ARCH-3" [--requires-cron] [--requires-external-network] [--requires-broad-fs-read] [--insufficiency-flags "<subfield>;..."]
```

Add a resource-claim flag only when the operator's description actually implies it (e.g. `--requires-cron` for an agent that must run on a schedule). **Forced confirmation for the highest tier:** before recording any agent as `critical`, state plainly — "I've marked [agent] as your most critical agent; failures here have the highest impact — please confirm" — and only proceed on explicit acknowledgment (per the agent-intent prompt's confirmation hooks). Surface low-confidence agents explicitly.

### Step 2 — Derive the approach solution brief, the agent roster, and the advisor entries

Derive the `approach_roster` group's fields. The first two are `synthesis` (cite prior confirmed field keys, not question-IDs); the third, the advisor knowledge-base entries, is `extraction` from the confirmed advisor list (`ADV-1` from step 07):

```
python3 wizard/scripts/interview_cli.py derive-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field APPROACH_SOLUTION_BRIEF --value "<the solution brief, in the operator's voice>" --inputs CORE_PURPOSE,VISION_PURPOSE,VISION_GOALS
python3 wizard/scripts/interview_cli.py derive-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field AGENT_ROSTER_ROWS --value "<a markdown table of the agents, rendered from the agent intents>" --inputs APPROACH_SOLUTION_BRIEF
python3 wizard/scripts/interview_cli.py derive-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field ADVISOR_ENTRIES --value "<one knowledge-base header block per confirmed advisor — role/name, Domain, Status: Active, Notes — taken verbatim from the advisor list; an empty string if the operator confirmed no advisors>" --sources ADV-1
```

`ADVISOR_ENTRIES` fills the advisor knowledge base the generator emits at the end — it is no longer written mid-interview at step 07. An empty value is correct (and matches a zero-advisor system) when no advisors were confirmed.

Carry the operator's voice/style (their literacy + information preference + their own framing) into the prose — voice-and-style is a property of the derivation, not a separate field. Use names verbatim from the operator's answers everywhere (name-consistency; the structured projection then uses the accepted values verbatim, which structurally eliminates name drift).

### Step 3 — Render the approach preview and show the operator

```
python3 wizard/scripts/interview_cli.py preview-group --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --group approach_roster --source-version v0.4.0 --build-repo-root <path to the wizard build repo root> --auto SYSTEM_SHAPE=markdown-CC --auto FOUNDATION_ONLY_MODE=<false|true> --auto WIZARD_VERSION=v0.4.0 --auto LAST_UPDATED_DATE=<today> --auto LAST_UPDATED_TRIGGER="initial build" --auto CURRENT_SPRINT_NUMBER=1
```

Show the operator the **rendered approach markdown** the command prints — the actual document they will receive, not the field values.

### Step 4 — One round of changes, then confirm

Say exactly this before the operator responds:

> Here's your approach — how your system will work and the helpers it'll need, based on everything so far. It also lays out how the work runs, which helpers matter most, and how the system knows each one is done. Take a look and tell me anything that's wrong or missing — you have one round of changes here. The system keeps this current as things evolve, so good enough to build from is the right standard. What would you like to change, if anything?

**Wait for answer.**

- **No changes:** confirm each field — `python3 wizard/scripts/interview_cli.py confirm-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field <FIELD> --group approach_roster --state accepted`.
- **Changes:** incorporate them, re-derive the affected field(s) (and re-record any changed agent intent), then confirm with the edited value (`--state accepted --value "<edited value>"`). Re-render the preview once, then confirm. Do not open a second round.

### Step 5 — Close the approach_roster group

```
python3 wizard/scripts/interview_cli.py close-group --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --progress ~/claude-wizard-draft/wizard_progress.md --shape markdown-CC --group approach_roster
```

This records `group_approach_roster_confirmed` (carrying the source hash). The group cannot close unless all of its derived fields — the solution brief, the agent roster, and the advisor entries — are confirmed. **Do NOT write `step_08: complete` until this succeeds** — a step marker before its group is confirmed is an illegal state.

**Say:**

> Approach confirmed. Next we'll go through the technical setup — credentials, integrations, and the build sequence.

Update the staging file (human-readable mirror): ARCHITECTURE_CONFIRMED = true; APPROACH_CONFIRMED = true.

Write sub-step marker: Append `step_08_WRITE: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 08.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 08.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

ARCH-1 through ARCH-5 recorded to the transcript (tagged to their groups). The `approach_roster` group is closed (`group_approach_roster_confirmed` recorded): the agents are captured as structured intents, the approach solution brief + roster are derived and confirmed against the rendered preview. **No `technical_architecture.md` or `approach.md` file was written** — they are emitted by the generator at the end; the operator confirmed the rendered approach draft at the barrier. ARCHITECTURE_CONFIRMED = true in the staging file.

**Write completion marker:** Append `step_08: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`. (Only after `group_approach_roster_confirmed` is recorded — the step marker is illegal before its group closes.)

Proceed to `09_credentials.md`.

---

## Foundation-only adapted path

**Disposition: ADAPT — same recording + approach_roster barrier; the foundation-only emission split happens at the generator, not here.**

Conduct the architecture interview exactly as the normal path above (ARCH-1 through ARCH-5, recorded to the transcript), and close the `approach_roster` group exactly as above (derive the agents as intents → derive the approach fields → render the approach preview → confirm → close). Pass `--auto FOUNDATION_ONLY_MODE=true` to the preview command.

**The foundation-level vs implementation split is the generator's job, not the interview's.** At the end of the interview the bridge dispatches a foundation-only `EmissionPlan` (with `agents == []`) to the generator's foundation-only branch, which emits the foundation docs (including a shape-agnostic `technical_architecture.md` and `approach.md`) and skips the agent layer / permission-tier files / per-agent task checklists. So: record the agent intents and derive `AGENT_ROSTER_ROWS` as normal (they render into the foundation-level `approach.md` and are harmlessly ignored by the foundation-only dispatch — no agent files are emitted); do NOT write any `technical_architecture.md` or `approach.md` here in either mode.

**Stop-condition DOCUMENT-path integration:** if `_pre_step_05_recheck.md` Step 2b recorded entries in `stop_conditions.documented_in_foundation`, the "Regulatory & compliance gaps (foundation-only mode)" section is assembled into the emitted `technical_architecture.md` at step 15 close per `_foundation_only_mode_gate.md` § 6 (read from staging `stop_conditions.documented_in_foundation` + `control_matrix_active`). Append any additional operational requirements surfaced here to the staging file under `## Foundation-only-mode captures > Architecture notes` for that assembly.

**Write completion marker:** Append `step_08: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md` (only after `group_approach_roster_confirmed`).

Proceed to `09_credentials.md`.
