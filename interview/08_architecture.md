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

1. **Schema-version check (per handoff contract consumer rule).** Read `~/claude-wizard-draft/wizard_session_draft.md`; locate the `schema_versions` block under shape_hypothesis. Verify `schema_major == 0`. If `schema_major` mismatches the consumer expected major (currently `0` at v0), abort with operator-facing internal-state error: "I hit a wizard-internal version mismatch — the staging file's shape-detection schema major is `<actual>`, but this version of the wizard expects major `0`. Your project file is saved. Please update the wizard OR resume with the matching wizard version." Exit cleanly; do NOT proceed.

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

> **Step 9 of 16 — System architecture**
> I'll show you how the pieces fit together — agents, workflows, and permissions.

---

## How to run this phase

All five steps in this phase follow the same pattern: Claude derives and presents, the user confirms or adjusts. The user is not asked to make architectural decisions — only to confirm that Claude's understanding of their work matches reality. When the user corrects something, update the model and continue.

**Recording (event transcript).** Record each architecture answer to `~/claude-wizard-draft/wizard_transcript.jsonl`, tagged to the group it feeds: ARCH-1 (orchestration model) → `orchestration_build`; ARCH-2 (agent roster) + ARCH-3 (criticality tiers) → `approach_roster`; ARCH-4 (permission/always-ask summary) → `hitl_autonomy`; ARCH-5 (task completion conditions) → `tests_audit`. The record-answer line is shown at the end of each ARCH step below. Do **not** maintain or write a `technical_architecture.md` file here — the architecture is emitted by the generator at the end from the confirmed transcript. After ARCH-5, this step closes the `approach_roster` group (derive → render approach.md preview → confirm → close).

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

## ARCH-1 — Orchestration model [DYNAMIC]

Before speaking, read the vision document and approach document. Identify:
- Which workflows are independent — tasks that different agents can run without waiting on each other
- Which workflows are dependency-linked — tasks where one agent must finish before another can start

**Do not ask the user to make an architectural call.** Present your reading of how their work flows, and ask them to confirm whether it's accurate.

**Say:**

> Before we go through the agents themselves, I want to show you how they'll be organized.
>
> Based on what you've described, here's how the work will flow:
>
> **[Workflow name or description]:** [Plain-language description — e.g., "These steps can run at the same time — each agent works independently and doesn't need to wait for the others."]
>
> **[Workflow name or description]:** [Plain-language description — e.g., "These steps run in sequence — [Agent A] finishes first, then [Agent B] picks up from where it left off."]
>
> Does that match how you'd expect the work to happen?

**Wait for answer.**

- If the user confirms: note the orchestration model as confirmed and proceed.
- If the user corrects the workflow description: update your model to match, restate the corrected description, confirm, and proceed.
- If the user asks what the difference matters: explain in plain terms — independent workflows run faster because agents work simultaneously; sequential workflows ensure earlier results are available when later steps need them.

The architectural conclusion (whether a scoped orchestrator is needed, which workflows it manages) follows from the confirmed workflow description. Do not present this conclusion to the user — it is an internal implementation detail. The user only confirms the workflow description.

Write sub-step marker: Append `step_08_ARCH-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:** `python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid ARCH-1 --group orchestration_build --value "<the confirmed workflow/orchestration description>"`

---

## ARCH-2 — Agent roster [DYNAMIC]

Present the proposed agent roster derived from the vision document, approach document, and confirmed orchestration model. The user did not design this roster — Claude did. Present it for genuine review, not rubber-stamp approval.

**Say:**

> Here are the agents your system will need. For each one I'll tell you what it does, why it exists, and what would break without it.
>
> **[Agent name]**
> [One sentence: what it does.] It exists because [why — what gap it fills]. Without it, [what would break or be missing].
>
> **[Agent name]**
> [Repeat for each agent.]
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

## ARCH-3 — Criticality tier assignment [DYNAMIC]

Assign each confirmed agent a criticality tier. Present the assignments with a plain-language explanation of what each tier means.

**Say:**

> Each agent has a criticality level — this tells the system how to handle it if something goes wrong.
>
> - **Critical** — if this agent doesn't finish completely, the system stops. The work it does is required before anything else can continue.
> - **Standard** — if this agent hits a problem, it flags it and the system keeps going where it can. Gaps are noted but don't stop everything.
> - **Supporting** — partial results are fine. This agent adds value but the main work completes without it.
>
> Here's what I'm proposing for your system:
>
> | Agent | Tier | Why |
> |-------|------|-----|
> | [Agent name] | Critical | [One sentence reason] |
> | [Agent name] | Standard | [One sentence reason] |
> | [Agent name] | Supporting | [One sentence reason] |
>
> Does this match your expectations? If any of these feel off, let me know.

**Wait for answer.**

- If the user confirms: proceed.
- If the user disagrees with a tier: discuss the implication (e.g., moving an agent to Critical means the system halts if it fails), update the assignment, confirm.

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

## ARCH-5 — Task completion checklists [DYNAMIC]

For each agent in the confirmed roster, present how the system will know when that agent has finished its work.

**Say:**

> Last step in the architecture review. For each agent, here's how the system will know its work is done. Tell me if any of these don't match what you'd expect.

For each agent:

> **[Agent name]:** [Agent name]'s work is done when [plain-language completion condition — e.g., "the report has been generated and saved, all data sources have been checked, and no errors were flagged."]. Does that sound right?

**Wait for answer after each agent, or present the full list and ask for any corrections.**

- If the user confirms: note the checklist as confirmed.
- If the user adjusts a completion condition: update it and confirm.

Write sub-step marker: Append `step_08_ARCH-5: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:** `python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid ARCH-5 --group tests_audit --value "<the confirmed per-agent completion conditions>"`

---

## Close the approach_roster group — derive the agents, render the approach, confirm, close

All of the `approach_roster` group's inputs are now captured (UP-4 at step 03, AP-1/2/3 at step 06, ADV-1 at step 07, ARCH-2/3 here). **Instead of writing `technical_architecture.md` or `approach.md` to disk, derive the approach-group fields, derive the agents as structured intents, show the operator the rendered approach document, take one round of changes, and close the group.** The architecture answers ARCH-1/4/5 belong to groups that close later (at step 13) — they were recorded above and are consumed there. No foundation-doc file is written here; the generator emits them at the end.

### Step 1 — Derive the agents as structured intents

For each confirmed agent (from ARCH-2 + the criticality tiers from ARCH-3), derive a structured **agent intent** using the agent-intent derivation prompt (`wizard/foundation-bundles/v0/derivation-prompts/agent-intent.md`). The intent captures the agent's MEANING and its resource CLAIMS only — never its filesystem paths, model, cron cadence, or permissions (the generator decides those deterministically from the system shape). Draw each sub-field from the operator's own words (ARCH-2/3 + the approach answers AP-2/AP-3 + the vision); flag thin sub-fields in `insufficiency_flags`; never fabricate.

Record one intent per agent:

```
python3 wizard/scripts/interview_cli.py record-agent-intent --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --group approach_roster --display-name "<agent name>" --function-summary "<one sentence>" --role-intent "<2-4 sentences: why it exists>" --acceptance-signals "<signal 1>;<signal 2>" --output-purpose "<what its output is for>" --criticality-tier <critical|standard|supporting> --confidence <high|medium|low> --source-spans "ARCH-2;ARCH-3" [--requires-cron] [--requires-external-network] [--requires-broad-fs-read] [--insufficiency-flags "<subfield>;..."]
```

Add a resource-claim flag only when the operator's description actually implies it (e.g. `--requires-cron` for an agent that must run on a schedule). **Forced confirmation for the highest tier:** before recording any agent as `critical`, state plainly — "I've marked [agent] as your most critical agent; failures here have the highest impact — please confirm" — and only proceed on explicit acknowledgment (per the agent-intent prompt's confirmation hooks). Surface low-confidence agents explicitly.

### Step 2 — Derive the approach solution brief and the agent roster

Derive the two `approach_roster` foundation-doc fields (both `synthesis` — cite prior confirmed field keys, not question-IDs):

```
python3 wizard/scripts/interview_cli.py derive-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field APPROACH_SOLUTION_BRIEF --value "<the solution brief, in the operator's voice>" --inputs CORE_PURPOSE,VISION_PURPOSE,VISION_GOALS
python3 wizard/scripts/interview_cli.py derive-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field AGENT_ROSTER_ROWS --value "<a markdown table of the agents, rendered from the agent intents>" --inputs APPROACH_SOLUTION_BRIEF
```

Carry the operator's voice/style (their literacy + information preference + their own framing) into the prose — voice-and-style is a property of the derivation, not a separate field. Use names verbatim from the operator's answers everywhere (name-consistency; the structured projection then uses the accepted values verbatim, which structurally eliminates name drift).

### Step 3 — Render the approach preview and show the operator

```
python3 wizard/scripts/interview_cli.py preview-group --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --group approach_roster --source-version v0.4.0 --build-repo-root <path to the wizard build repo root> --auto SYSTEM_SHAPE=markdown-CC --auto FOUNDATION_ONLY_MODE=<false|true> --auto WIZARD_VERSION=v0.4.0 --auto LAST_UPDATED_DATE=<today> --auto LAST_UPDATED_TRIGGER="initial build" --auto CURRENT_SPRINT_NUMBER=1
```

Show the operator the **rendered approach markdown** the command prints — the actual document they will receive, not the field values.

### Step 4 — One round of changes, then confirm

Say exactly this before the operator responds:

> Here's your approach — how your system will work and the agents it'll need, based on everything so far. Take a look and tell me anything that's wrong or missing — you have one round of changes here. The system keeps this current as things evolve, so good enough to build from is the right standard. What would you like to change, if anything?

**Wait for answer.**

- **No changes:** confirm each field — `python3 wizard/scripts/interview_cli.py confirm-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field <FIELD> --group approach_roster --state accepted`.
- **Changes:** incorporate them, re-derive the affected field(s) (and re-record any changed agent intent), then confirm with the edited value (`--state accepted --value "<edited value>"`). Re-render the preview once, then confirm. Do not open a second round.

### Step 5 — Close the approach_roster group

```
python3 wizard/scripts/interview_cli.py close-group --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --progress ~/claude-wizard-draft/wizard_progress.md --shape markdown-CC --group approach_roster
```

This records `group_approach_roster_confirmed` (carrying the source hash). The group cannot close unless both approach fields are confirmed. **Do NOT write `step_08: complete` until this succeeds** — a step marker before its group is confirmed is an illegal state.

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
