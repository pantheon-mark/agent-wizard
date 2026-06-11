# 13 — Operations Settings

## What this file does
Configure how the system behaves during operation. Three technical thresholds (retry threshold, gate conflict timeout, deferred alert limit) are set as **silent defaults** from the system profile — the user has no basis for choosing these values. User-facing questions cover chunk confirmation preference, drift analysis cadence, and scale tier. This step records its operations answers to the event transcript and, at its end, **closes the three operational logical groups** — `orchestration_build`, then `hitl_autonomy`, then `tests_audit` (in that order; the order is load-bearing — see "How to run this phase"). It does **not** write `technical_architecture.md`, `execution_plan.md`, `test_cases.md`, `audit_framework.md`, or `project_instructions.md` — those are emitted by the generator at the end of the interview from the confirmed transcript.

## When this file runs
After `12_qa_settings.md` completes: `step_12: complete` is in `~/claude-wizard-draft/wizard_progress.md`. The staging-file `QA_CONFIGURED` mirror is a human-readable convenience, not the gate.

## Prerequisites
`step_12: complete` in `~/claude-wizard-draft/wizard_progress.md`.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 13_operations.md. QA_CONFIGURED = true. Read the staging file, then continue from where you left off."

Do not begin CONC-1 until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_13_*` (e.g., `step_13_AUTO-DEFAULTS: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_13: complete`) is not, proceed directly to the success condition.

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

Before the operations questions below, read `wizard/interview/_operator_interaction_contract.md` and apply it — ground each question in what the operator already told you, keep the ask balanced, plain voice, no filler.

---

## Step opening — progress and preview

**Say:**

> **Step 14 of 16 — Operations**
> Last set of preferences — how the system behaves day to day.

---

## How to run this phase

This phase sets operational behavior. Three technical thresholds (CONC-1 retry threshold, CONC-2 gate conflict timeout, START-1 deferred alert limit) are **silent defaults** — the user has no basis for choosing these values and the recommendations are accepted >90% of the time. They are derived from the system profile and presented as a summary, not asked as questions.

The remaining topics require genuine user input: chunk confirmation preference (START-2), drift analysis cadence (DRIFT-1), and scale tier (SCALE-1 through SCALE-4). Work through them in sequence after presenting the auto-configured defaults.

**Recording (event transcript).** Record each operations answer to `~/claude-wizard-draft/wizard_transcript.jsonl`, tagged to the group it feeds: CONC-2 + SCALE-1/2/3/4 → `orchestration_build`; CONC-1 + START-1 + START-2 → `hitl_autonomy`; DRIFT-1 → `tests_audit`. The record-answer line is shown at each step below. **No foundation-doc or `project_instructions.md` file is written here** — the scale tier and everything else are emitted by the generator at the end.

**Group closes at the end of this step (order is load-bearing).** After all answers are recorded, this step closes the three operational groups **in registry order: `orchestration_build` FIRST, then `hitl_autonomy`, then `tests_audit`.** The order matters because `execution_plan.md` (the `hitl_autonomy` preview) renders fields derived in `orchestration_build` (the MVP/build-phase/execution fields) — the cumulative-confirmed preview inputs only contain them once `orchestration_build` has closed. Closing out of order would fail the strict single-doc preview render.

**Before starting:** Read the confirmed vision, the confirmed agent roster, and the system profile (domain sensitivity from step 10, involvement level from step 03) to derive the silent defaults and tailor rationale to this specific system.

---

## Auto-configured defaults — CONC-1, CONC-2, START-1 [SILENT DEFAULTS]

*These values are set automatically from the system profile. Do not ask the user — a non-technical user has no basis for choosing between these technical thresholds, and the recommendations are accepted >90% of the time.*

**Before presenting:** Read the confirmed vision content and agent roster from the transcript (`~/claude-wizard-draft/wizard_transcript.jsonl`) — the foundation documents are not on disk until close. Assess workflow complexity for CONC-2:
- **Simple** (few agents, mostly sequential handoffs, low concurrency): set `GATE_CONFLICT_TIMEOUT = 30 seconds`
- **Moderate** (several agents, some parallel activity, shared resources): set `GATE_CONFLICT_TIMEOUT = 2 minutes`
- **Complex** (many agents, high concurrency, shared databases or external APIs): set `GATE_CONFLICT_TIMEOUT = 5 minutes`

Write all three values to the staging file:
- `RETRY_THRESHOLD = 3`
- `GATE_CONFLICT_TIMEOUT = [derived value from assessment above]`
- `DEFERRED_ALERT_THRESHOLD = 3`

**Say:**

> Before we get into the questions that need your input, here's how I've configured the technical settings based on your system's design:
>
> - **Retry threshold:** 3 automatic attempts before escalating to you — enough to handle brief glitches without spinning on a real problem
> - **Resource conflict timeout:** **[derived value]** — [one-sentence rationale from workflow complexity assessment, e.g., "your agents mostly work in sequence, so a 30-second wait catches real problems without false alarms"]
> - **Deferred alert limit:** 3 deferrals before an alert is escalated as overdue — stops unresolved issues from sitting quietly in the queue
>
> These are tuned for your setup and adjustable anytime — just tell me if you'd like to change any of them.

Do not wait for a response. Proceed to START-2.

Write sub-step marker: Append `step_13_AUTO-DEFAULTS: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record the three silent-default thresholds as source answers** (they feed their groups even though they were not asked):

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid CONC-1 --group hitl_autonomy --value "retry threshold = 3 automatic attempts before escalation"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid CONC-2 --group orchestration_build --value "gate conflict timeout = <derived value>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid START-1 --group hitl_autonomy --value "deferred alert limit = 3 deferrals before escalation"
```

---

## START-2 — Chunk confirmation preference [FIXED — topic]

**Say:**

> When your system is working through a list of tasks — fixing a batch of issues, updating several documents, running a sequence of steps — you have a choice in how it proceeds.
>
> **Option 1 — Confirm each step:** The system completes one step, tells you what it did and what it's about to do next, and waits for your go-ahead before continuing. Nothing moves forward without your sign-off.
>
> **Option 2 — Confirm only the important ones:** The system works through lower-risk steps on its own and only stops when it reaches something that needs your judgment — an action that's harder to reverse, touches something sensitive, or has broader consequences.
>
> I'd suggest starting with **confirm each step**. As you get more familiar with how your system behaves, you can move to the second option and let it handle routine steps on its own. You're not locked in — you can switch at any time.
>
> Which would you like to start with?

**Wait for answer.**

- If the user chooses confirm each: confirm "Confirm-each to start. You can move to confirm-important-only once you're comfortable with how the system makes decisions."
- If the user chooses confirm important only: confirm their choice. Note: "Good — the system will still tell you about every step it takes, it just won't wait for approval on the routine ones."
- If the user asks what counts as "important": "Anything that affects a document your other processes depend on, that communicates externally, that involves money, or that's hard to reverse. The system applies the same Tier 1 rules you confirmed earlier."

Write the configured value to the staging file: `CHUNK_CONFIRMATION = [Confirm each / Confirm important only]`.

Write sub-step marker: Append `step_13_START-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:** `python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid START-2 --group hitl_autonomy --value "<CHUNK_CONFIRMATION>"`

---

## DRIFT-1 — Drift analysis cadence [FIXED — topic]

**Before asking:** Read the confirmed vision content from the transcript (`~/claude-wizard-draft/wizard_transcript.jsonl`) — the foundation documents are not on disk until close. Assess system complexity and how frequently the user's domain evolves:
- **Simple system or stable domain:** Recommend **monthly**.
- **Moderate complexity or moderately evolving domain:** Recommend **biweekly**.
- **Complex system, multiple integrations, or rapidly changing domain:** Recommend **weekly**.

**Say:**

> Over time, any system can drift — it keeps doing what it was originally built to do, but the world around it has changed. A data source restructured its output. A process your system supports was updated. A goal shifted.
>
> Drift analysis is when your system checks its own behavior against the vision document you confirmed at the start — asking "is what I'm doing still what I was built to do?"
>
> **How often should that check happen?**
>
> Based on [one-sentence rationale referencing system complexity or domain — e.g., "your system handles several integrations in a domain that changes regularly" or "your system is focused on a narrow, stable workflow"], I'd recommend **[recommended cadence]** as a starting point.
>
> That means once [weekly / every two weeks / monthly], the system reviews its own activity logs against your vision document and flags anything that looks like drift — for your review, never for autonomous correction without your input.
>
> Does that cadence feel right, or would you prefer more or less frequent checks?

**Wait for answer.**

- If the user accepts the recommendation: confirm the cadence and proceed.
- If the user chooses differently: accept without pushback. If they choose less frequent than monthly, note gently: "That's fine — worth knowing that drift tends to accumulate quietly, so you may want to revisit this as the system matures."
- If the user asks what happens when drift is detected: "The system flags it in your digest with a plain-language description — 'I noticed I've been doing X, but your vision document says the goal is Y. Here's what I think should change. Do you want me to adjust?' It never silently reorients itself."

Write the configured value to the staging file: `DRIFT_CADENCE = [Weekly / Biweekly / Monthly]`.

Write sub-step marker: Append `step_13_DRIFT-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:** `python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid DRIFT-1 --group tests_audit --value "<DRIFT_CADENCE>"`

---

## Scale tier — SCALE-1, SCALE-2, SCALE-3 [FIXED]

**Say:**

> Last set of questions before we wrap up. These help me understand the scale your system will need to operate at — not technical details, just how your day-to-day actually works.

Ask each question in sequence. Wait for the answer before moving to the next.

**SCALE-1:**

**Before asking:** From the confirmed transcript, identify the operator's largest single category of tracked items — the primary working set the system spends most of its effort on (e.g., the master task list). Ground the question in that example per the Operator Interaction Contract. Do NOT ask the operator to total unlike categories together: tasks, advisors, accounts, and properties are different kinds of things at different orders of magnitude, and a non-technical operator cannot meaningfully combine them into one number. Ask for the size of the *biggest single group*, since that is the volume that drives sizing.

> Of all the things your system keeps track of, what's the biggest single group — and roughly how many are in it? Most setups have one main set the system works through (tasks, clients, cases, records, properties — whatever fits yours), and that's the one that matters for sizing the system. Smaller groups, like a few advisors or a couple of accounts, don't change it. A rough number is fine.

**Wait for answer.**

**SCALE-2:**

> How often does your system need to process or refresh information — a few times a day, hourly, or continuously?

**Wait for answer.**

**SCALE-3:**

> Are there peak periods where the volume spikes significantly?

**Wait for answer.**

Write sub-step marker: Append `step_13_SCALE: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:**

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid SCALE-1 --group orchestration_build --value "<volume answer>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid SCALE-2 --group orchestration_build --value "<frequency answer>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid SCALE-3 --group orchestration_build --value "<peak-period answer>"
```

---

## SCALE-4 — Tier confirmation [DYNAMIC]

**Before stating the tier:** Map the user's three answers to a provisional tier using the following guide:

| Tier S (Small) | Tier M (Medium) | Tier L (Large) |
|----------------|-----------------|----------------|
| Hundreds of records or fewer | Thousands of records | Tens of thousands of records or more |
| A few times a day or less | Hourly | Near-continuous or continuous |
| No significant peaks, or very minor spikes | Some peaks, manageable | Significant peak periods with meaningful volume spikes |

When answers span tiers, round to the higher tier if two or more indicators point there.

**Say:**

> Based on what you've described, I'm treating this as a **Tier [S / M / L]** system — [one-sentence rationale, e.g., "you're working with hundreds of records and processing happens a few times a day, so the system doesn't need to be built for high-throughput operation" or "with thousands of records processed hourly and meaningful peaks, the system needs to handle concurrent load reliably"].
>
> This is a starting assumption. Once your agents are running with real data, I'll check whether what I actually observe matches. Does that sound right?

**Wait for answer.**

- If the user confirms: proceed.
- If the user adjusts the tier: accept the adjustment. Ask "What's different from what you described?" so the rationale is accurate. Record the user-confirmed tier.
- If the user is uncertain: "That's fine — I'll start with [tier] and watch how the system actually behaves. If what I observe is consistently different, I'll flag it and we'll revisit."

Write the configured value to the staging file: `SCALE_TIER = [S / M / L] (provisional)`.

Write sub-step marker: Append `step_13_SCALE-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Record:** `python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid SCALE-4 --group orchestration_build --value "<the operator-confirmed tier: small / medium / large + any adjustment note>"` (the SCALE_TIER field itself is derived + confirmed at the orchestration_build barrier below; this records the operator's tier input).

---

## Close the three operational groups — derive, render, confirm, close (IN ORDER)

All inputs for the three operational groups are now captured (across steps 01-13). Instead of writing any foundation-doc or `project_instructions.md` file, derive each group's fields, show the operator the rendered preview, take one round of changes, and close the group. **Close in this order — `orchestration_build`, then `hitl_autonomy`, then `tests_audit`** — because the hitl preview (`execution_plan.md`) renders orchestration_build's fields, which are only in the cumulative confirmed set once orchestration_build has closed.

Throughout: synthesis/policy fields cite prior **confirmed field keys** via `--inputs` (not question-IDs); extraction/classification fields cite question-IDs via `--sources`. The class derivation prompts live at `wizard/foundation-bundles/v0/derivation-prompts/<class>.md`; the field manifest (`wizard/foundation-bundles/v0/field-manifests/markdown-CC.json`) names each field's class, decision coupling, and which doc it previews. Render each preview with the same `preview-group` command shape used at the vision/approach barriers (pass all six `--auto` globals + `--source-version v0.4.0 --build-repo-root <wizard build repo root>`), and **always add `--include-unconfirmed --out-file ~/claude-wizard-draft/<doc>_PREVIEW.md`** so each preview renders the just-derived draft (before confirming) into an operator-clean review file the operator opens in a viewer (Operator Interaction Contract § 4) — never paste preview content into chat. Confirm with the one-round pattern; **forced confirmation on every decision/policy field** (CAPABILITY_INCREMENTS, SCALE_TIER, AUTONOMY_LEVEL, HITL_MAP_ROWS, DRIFT_ANALYSIS_CADENCE). Decision fields with operator-facing weight (the MVP/roadmap boundary and the human-in-the-loop map) are confirmed as **guided reviews**, not artifact audits — see the per-barrier notes.

### Barrier 1 — orchestration_build (preview `technical_architecture.md`)

Derive the extraction/classification fields first so the synthesis fields can cite them. The
credential + integration surfaces now derive from the canonical dependency record captured at step
09 (`EXTERNAL_DEPENDENCY_IDENTITY`), NOT from raw credential answers:

```
# extraction + classification (cite question-IDs)
interview_cli derive-field --field SCALE_TIER --value "<small|medium|large>" --sources SCALE-1,SCALE-2,SCALE-3,SCALE-4   # decision: forced confirm
interview_cli derive-field --field CREDENTIAL_CHECK_CADENCE --value "<monthly|quarterly|biannual>" --sources CRED-4   # decision: forced confirm
interview_cli derive-field --field ROTATION_LEAD_TIME_DAYS --value "<days, e.g. 14>" --sources CRED-3
# projection (deterministic role-filter of the canonical record — no --value, no separate confirm):
interview_cli derive-projection --field CREDENTIAL_REGISTRY_ROWS   # the needs_credential subset -> credentials_registry.md (Status: Pending)
# synthesis (cite prior confirmed field keys)
interview_cli derive-field --field INTEGRATIONS --value "<prose list of the integrations / data sources>" --inputs EXTERNAL_DEPENDENCY_IDENTITY
interview_cli derive-field --field ORCHESTRATION_MODEL --value "<...>" --inputs INTEGRATIONS
interview_cli derive-field --field SCALE_TIER_BASIS --value "<...>" --inputs SCALE_TIER
interview_cli derive-field --field SCALE_TIER_RATIONALE --value "<...>" --inputs SCALE_TIER
interview_cli derive-field --field COMPLIANCE_GAPS_CONTENT --value "<...>" --inputs INTEGRATIONS
interview_cli derive-field --field TASK_COMPLETION_CHECKLISTS --value "<...>" --inputs ORCHESTRATION_MODEL
# CAPABILITY_INCREMENTS — THE MVP<->roadmap release-boundary decision (synthesis; DECISION field;
# FORCED confirm). Derive it BEFORE the phase table and MVP prose. Propose the system's capability
# increments and, for each, whether it lands in the MVP, on the roadmap (in scope but planned for
# after the MVP), or is only a possibility for later (a candidate, with the condition that would
# trigger it). Ground the proposal in the approach brief, the agent roster, the orchestration model,
# and the scope + success the operator confirmed at the vision step, plus anything they flagged as
# "later / phase 2 / maybe" in earlier steps. JSON: a list of {capability, agents, phase (an integer
# for committed work; omit for a candidate), release_bucket (mvp | post_mvp_roadmap |
# candidate_conditional), depends_on?, rationale?, condition? (required for candidate_conditional)}.
interview_cli derive-field --field CAPABILITY_INCREMENTS --value '<JSON list of capability increments, each bucketed mvp / post_mvp_roadmap / candidate_conditional>' --inputs APPROACH_SOLUTION_BRIEF,AGENT_ROSTER_ROWS,ORCHESTRATION_MODEL,VISION_SCOPE_BOUNDARY,VISION_SUCCESS_CRITERIA
interview_cli confirm-field --field CAPABILITY_INCREMENTS --group orchestration_build --state accepted
# BUILD_PHASES_ROWS + MVP_ROADMAP_BOUNDARY are DETERMINISTIC projections of CAPABILITY_INCREMENTS
# (pure code; no --value, no separate confirm). The build order and the MVP/roadmap split are views
# of the ONE confirmed source, so they cannot contradict the MVP narrative:
interview_cli derive-projection --field BUILD_PHASES_ROWS        # committed increments (mvp + roadmap) grouped by phase
interview_cli derive-projection --field MVP_ROADMAP_BOUNDARY     # the MVP / on-the-roadmap / possible-later buckets
interview_cli derive-field --field EXECUTION_SEQUENCE --value "<...>" --inputs ORCHESTRATION_MODEL
# MVP prose derives FROM the confirmed boundary (cite CAPABILITY_INCREMENTS) so the MVP narrative
# names exactly the mvp-bucket capabilities — never capabilities the phase table actually defers:
interview_cli derive-field --field MVP_CORE_FUNCTION --value "<...>" --inputs CAPABILITY_INCREMENTS,APPROACH_SOLUTION_BRIEF
interview_cli derive-field --field MVP_MINIMUM_VIABLE_STATE --value "<...>" --inputs CAPABILITY_INCREMENTS,APPROACH_SOLUTION_BRIEF
interview_cli derive-field --field MVP_SUCCESS_CONDITION --value "<...>" --inputs CAPABILITY_INCREMENTS,VISION_SUCCESS_CRITERIA
```

(`interview_cli` = `python3 wizard/scripts/interview_cli.py ... --transcript ~/claude-wizard-draft/wizard_transcript.jsonl` — `--shape markdown-CC` for derive-field/derive-projection.) Confirm each derived field (`confirm-field --group orchestration_build --state accepted`; forced confirm on the decision fields SCALE_TIER + CREDENTIAL_CHECK_CADENCE + **CAPABILITY_INCREMENTS**). **`derive-projection` fields are NOT separately confirmed** — a projection is a deterministic view of an already-confirmed source (it auto-projects); this now includes CREDENTIAL_REGISTRY_ROWS **and BUILD_PHASES_ROWS + MVP_ROADMAP_BOUNDARY** (both views of the confirmed CAPABILITY_INCREMENTS).

**Confirm CAPABILITY_INCREMENTS as a GUIDED review, not a JSON audit (Operator Interaction Contract §4 + §1).** Do not show the operator the JSON or ask them to check a table. Walk the split in plain terms grounded in their own system: name what the system will do *first* (the MVP — the smallest version worth trusting), then what is *in scope but planned for after that* (the roadmap), then anything that is *only a possibility for later* and what would trigger it. Then ask one judgeable question — e.g. "Does it make sense to get [the MVP capabilities] working and trusted first, and bring [the deferred ones] in afterward — or is any of the later work something you'd need from day one?" Record their adjustments; a moved capability changes the bucket, which re-renders the phase table and the boundary automatically. Render `technical_architecture.md` via `preview-group --group orchestration_build`, show the operator the rendered markdown, one round of changes, then `close-group --group orchestration_build`.

### Barrier 2 — hitl_autonomy (preview `execution_plan.md`)

This group derives **seven** fields: the autonomy level, the human-in-the-loop policy map, and the **five financial-guardrail fields** that govern what the system spends on its own (the included monthly automation credit, this project's budget, the sharing posture, the exhaustion behavior, and the intensive-operation threshold). The financial source answers (FIN-1 plan / FIN-3 sharing / FIN-4 exhaustion) were captured at step 02; the dollar values are derived **here**, where the group closes — the wizard computes every dollar (the operator never set one).

```
# --- Financial guardrail (the cost safety-envelope) ---
# Plan -> included monthly automation-credit pool (extraction lookup; the operator confirmed their
# plan at step 02, and confirms the dollar pool against the plan table there). Pro $20 / Max5x $100 /
# Max20x $200 / Team-Std $20 / Team-Premium $100 (unknown -> $20).
interview_cli derive-field --field AUTOMATION_CREDIT_POOL --value "<$pool for the operator's plan>" --sources FIN-1
# Sharing posture + exhaustion behavior (classification of the operator's plain step-02 choices; forced confirm):
interview_cli derive-field --field PROJECT_SHARE_POSTURE --value "<sole|one-of-several>" --sources FIN-3
interview_cli confirm-field --field PROJECT_SHARE_POSTURE --group hitl_autonomy --state accepted
interview_cli derive-field --field EXHAUSTION_BEHAVIOR --value "<wait|interactive-fallback|paid-overflow>" --sources FIN-4
interview_cli confirm-field --field EXHAUSTION_BEHAVIOR --group hitl_autonomy --state accepted
# Budget + intensive-operation threshold are DETERMINISTIC projections (pure code: budget =
# round(pool x share; sole 0.9 / one-of-several 0.4); threshold = max(1, round(10% of budget)).
# No --value and no separate confirm — the wizard computes the money, it is never authored here:
interview_cli derive-projection --field PROJECT_AUTOMATION_BUDGET
interview_cli derive-projection --field INTENSIVE_OPERATION_THRESHOLD

# --- AUTONOMY_LEVEL (classification, from the operator authority profile; forced confirm) ---
# Compute the level deterministically with the authority-profile ceiling/min model:
#   level = max(1, min(desired_level, domain_risk_cap, reversibility_cap, trust_cap))
# where desired_level comes from the operator's decision preference + involvement (UP-3, UP-5),
# domain_risk_cap from DR, reversibility_cap from REV, and trust_cap from the trust posture
# (auto 'probationary' at first build -> cap 2). Routine action classes stay autonomous even at
# level 1. Use authority_profile.py's mapping; do not eyeball it.
interview_cli derive-field --field AUTONOMY_LEVEL --value "<1|2|3 from the ceiling/min above>" --sources UP-3,UP-5,DR,REV
interview_cli confirm-field --field AUTONOMY_LEVEL --group hitl_autonomy --state accepted

# --- HITL_MAP_ROWS (policy; forced confirm) ---
# Consume the authority posture + the vision-barrier always-stop-and-ask elevations. Cite
# AUTONOMY_LEVEL (always present); add TIER_1_ADDITIONS only if the vision barrier produced it.
interview_cli derive-field --field HITL_MAP_ROWS --value "<markdown table: Action | System behavior | Rationale; state BOTH what is permitted AND what is forbidden>" --inputs AUTONOMY_LEVEL
interview_cli confirm-field --field HITL_MAP_ROWS --group hitl_autonomy --state accepted
```

`AUTONOMY_LEVEL` is a decision field derived from the operator's confirmed authority answers (it is no longer a provisional placeholder). Surface the basis in the rationale you record — including that the trust posture is `probationary` at first build (which caps the level at 2) and lifts over time. `HITL_MAP_ROWS` is a policy rule set: it MUST state explicit negative permissions; it derives from `AUTONOMY_LEVEL` (the per-class autonomous-vs-ask-first posture) plus the always-stop-and-ask elevations the operator confirmed at the vision step (cite `TIER_1_ADDITIONS` in `--inputs` only when that field exists), plus the operator's always-ask summary from the architecture step. The budget and threshold do **not** render into this preview (`execution_plan.md`) — they land in the system's instructions and cost log at emission; the operator confirmed the plain choices that produce them at step 02, and the dollar values are deterministic. The paid-overflow cap is only present if the operator chose paid overflow, and it was handled at step 02 — it is not derived here. Render `execution_plan.md` via `preview-group --group hitl_autonomy` (it renders orchestration_build's MVP / build-phase / boundary fields too — that is why orchestration_build closed first), show the operator, one round, then `close-group --group hitl_autonomy`.

**Review the human-in-the-loop map as a GUIDED review, not a permissions audit (Operator Interaction Contract §4 + §1).** The rendered `execution_plan.md` contains a permissions table; handing a non-technical operator a table to audit puts the burden on the wrong person — they have no basis to know whether the rows are right. Instead, walk the load-bearing distinction in plain terms, grounded in their system: the small number of things the system will **do on its own and just tell you about** (the routine, reversible work) versus the things it will **always check with you before doing** (money, anything sent outside, anything hard to undo, anything you marked sensitive). Surface the autonomy level plainly — at the current level it leans toward checking first, and that loosens over time as you build trust — without naming internal tiers or levels as jargon. Then ask one judgeable question, e.g. "Is there anything here it would handle on its own that you'd rather it check with you about first — or anything it checks with you on that you'd be glad to let it just handle?" Record adjustments to the map; the rendered file is still produced for them to open, but the *review* is the plain walk plus that question, not the table itself.

### Barrier 3 — tests_audit (preview `test_cases.md` + `audit_framework.md`)

```
interview_cli derive-field --field AGENT_SPECIFIC_TESTS --value "<markdown list of per-agent acceptance tests>" --inputs APPROACH_SOLUTION_BRIEF
interview_cli confirm-field --field AGENT_SPECIFIC_TESTS --group tests_audit --state accepted
interview_cli derive-field --field DRIFT_ANALYSIS_CADENCE --value "<DRIFT_CADENCE>" --sources DRIFT-1   # decision: forced confirm
interview_cli confirm-field --field DRIFT_ANALYSIS_CADENCE --group tests_audit --state accepted
interview_cli derive-field --field DOMAIN_SENSITIVITY_SETTINGS --value "<table: Domain | Sensitivity level | Rationale | Last reviewed>" --sources GATE-2   # decision: forced confirm
interview_cli confirm-field --field DOMAIN_SENSITIVITY_SETTINGS --group tests_audit --state accepted
# The content-only annotation of the canonical dependency record (purpose / what-stops + the
# per-role detail enriched at steps 11 and 13). MUST be derived + confirmed BEFORE the two
# projections below, which read it. Build the JSON array from the dependencies already in the
# step-09 identity record (no orphaned facets — only ids present there).
interview_cli derive-field --field EXTERNAL_DEPENDENCY_ANNOTATION --value '<JSON array of {id, purpose, what_stops, boundary_input_facet?, health_facet?}>' --sources DEP-1,GATE-1,QA-3
interview_cli confirm-field --field EXTERNAL_DEPENDENCY_ANNOTATION --group tests_audit --state accepted
# projections (deterministic role-filter of the canonical record — no --value, no separate confirm):
interview_cli derive-projection --field INPUT_TYPE_INVENTORY    # the boundary_input subset -> validation_gate_config.md
interview_cli derive-projection --field SOURCE_REGISTRY_ROWS    # the health_monitored subset -> source_registry.md
```

**Deferred-items capture (WI-013):** while in this group, scan the interview for items the operator explicitly deferred ("not now", "later", "phase 2") and capture them as deferred-item content. NOTE (build-side): the emitted `future_items.md` target for these is not yet a manifest field — its re-home is owed before close-assembly retirement (tracked with the advisor-KB gap); do not block the tests_audit close on it at v0. Render both `test_cases.md` and `audit_framework.md` via `preview-group --group tests_audit` (two docs), show the operator, one round, then `close-group --group tests_audit`.

---

## Confirm with the user

**Say:**

> Operations settings confirmed, and that completes the interview content. Here's what's in place:
>
> - **Retry threshold:** 3 automatic attempts before escalation
> - **Gate conflict timeout:** [value] before flagging resource conflicts
> - **Deferred alert limit:** 3 deferrals before an alert is escalated as overdue
> - **Chunk confirmation:** [Confirm each step / Confirm important only]
> - **Drift analysis:** Runs [Weekly / Biweekly / Monthly]
> - **Scale tier:** Tier [S / M / L] (provisional)
>
> Next we'll review the documents your system has produced so far and set up your GitHub backup.

Update staging file: `OPERATIONS_CONFIGURED = true`. **No foundation-doc or `project_instructions.md` file was written — the scale tier and all operational settings are emitted by the generator at the end from the confirmed transcript.**

Write sub-step marker: Append `step_13_WRITE: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`. (Only after all three operational `group_*_confirmed` markers are recorded — a `step_13` marker before its groups close is an illegal state.)

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 13.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 13.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

CONC-1, CONC-2, START-1, START-2, DRIFT-1, and SCALE-1 through SCALE-4 recorded to the transcript (tagged to their groups). **All three operational groups closed** (`group_orchestration_build_confirmed`, `group_hitl_autonomy_confirmed`, `group_tests_audit_confirmed` recorded, in that order): each group's fields derived, the rendered preview shown and confirmed (forced confirmation on the decision/policy fields). **No `technical_architecture.md`, `execution_plan.md`, `test_cases.md`, `audit_framework.md`, or `project_instructions.md` file was written** — they are emitted by the generator at the end. `OPERATIONS_CONFIGURED = true` in the staging file.

**Write completion marker:** Append `step_13: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`. (Only after all three operational `group_*_confirmed` markers are recorded — the step marker is illegal before its groups close.)

Proceed to `14_document_review.md`.

---

## Foundation-only adapted path

**Disposition: ADAPT — same recording + the three operational barriers; the foundation-only emission split happens at the generator, not here.**

Conduct the operations interview exactly as the normal path above (CONC-1, CONC-2, START-1, START-2, DRIFT-1, SCALE-1 through SCALE-4, recorded to the transcript), and close the three operational groups exactly as above (orchestration_build → hitl_autonomy → tests_audit; pass `--auto FOUNDATION_ONLY_MODE=true` to each `preview-group`).

**No foundation-doc or `project_instructions.md` file is written here in either mode.** At the end of the interview the bridge dispatches a foundation-only `EmissionPlan` to the generator's foundation-only branch, which emits the shape-agnostic foundation docs (scale tier appears as a foundation-level operational note, not a runtime-config knob) and skips the runtime/implementation artifacts. The captured operations answers live in the transcript; append any additional foundation-level operational requirements surfaced here to the staging file under `## Foundation-only-mode captures > Operational requirements (cadence, scale, drift)` for the step-15 close assembly per `_foundation_only_mode_gate.md` § 5/§ 6.

**Write completion marker:** Append `step_13: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md` (only after all three operational `group_*_confirmed` markers).

Proceed to `14_document_review.md`.
