# 02 — Financial Guardrails

## What this file does
Establish the financial guardrails for any work the system does **on its own** (unattended/scheduled runs). Three operator-facing elements: which Claude plan the operator is on (which sizes the included monthly automation allowance and gates out Free), how much of that allowance this project may use when several systems share it, and what the system should do if it ever uses the allowance up. The wizard does all dollar arithmetic internally — the operator never sets a dollar figure except at the one real-money boundary (paid overflow). These answers are derived into `project_instructions.md` and the system's cost log, and enforced from day one.

## When this file runs
After `01_phase1_capture.md` completes. The staging file exists and is being updated after each answer.

## Prerequisites
Staging file at `~/claude-wizard-draft/wizard_session_draft.md` has been created and contains the P1-1 and P1-2 answers, and the step-01 `## Shape detection` block.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 02_financial.md. The staging file is at `~/claude-wizard-draft/wizard_session_draft.md` — read it, then continue from where you left off."

Do not begin FIN-1 until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_02_*` (e.g., `step_02_FIN-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_02: complete`) is not, proceed directly to the success condition.

---

## Step opening — progress and preview

**Say:**

> **Step 3 of 16 — Spending and limits**
> A couple of quick questions so your system knows its boundaries when it works on its own.

---

## Operator Interaction Contract

Before the questions below, read `wizard/interview/_operator_interaction_contract.md` and apply it — ground the framing in what the operator told you about their system, keep the ask balanced, plain voice, no filler. This step has copy-paste-exact elements (plan names, the `claude.ai/settings/billing` URL) that stay verbatim per rule #3; the contract's "intent, not script" latitude covers conversational wording only.

---

## How the credit model works (wizard-internal — do NOT recite to the operator)

Read this; do not read it aloud. From 2026-06-15, work the system does **headlessly/on a schedule** (the Agent SDK / `claude -p` path the Orchestrator uses for unattended runs) draws a **separate monthly dollar "automation credit"** included with the operator's plan — distinct from their interactive 5h/7d Claude use, which it cannot touch. Pool size by plan (per-user, NOT pooled across teammates, no rollover):

| Plan | Included monthly automation credit (`AUTOMATION_CREDIT_POOL`) |
|------|------|
| Pro | $20 |
| Max 5x | $100 |
| Max 20x | $200 |
| Team Standard (per seat) | $20 |
| Team Premium (per seat) | $100 |
| Free | none |

`last_verified: 2026-06-11` against `support.claude.com/articles/15036540`. **Version-dependent** (effective 2026-06-15; re-verify these figures before relying — pricing/credit facts rot). *(Enterprise plans also carry a credit — $20 usage-based / $200 seat-Premium — but are not yet a FIN-1 option; if an operator is on Enterprise, treat as Max-tier sizing and note the gap.)* The credit is a **one-time opt-in the operator must claim once** ("your plan includes…" is false until claimed). **There is no programmatic balance read**, so the generated system meters its OWN estimated spend (tokens × API rate; already counted in `cost_efficiency_log.md`) with a conservative safety margin — a documented v0 bridge. The included pool is a platform hard-boundary: at $0, unattended requests stop unless the operator has enabled paid overflow ("usage credits").

**Budget arithmetic (wizard computes; operator never sets it):**
- `PROJECT_AUTOMATION_BUDGET` = `AUTOMATION_CREDIT_POOL` × share fraction, where share = ~0.9 if `PROJECT_SHARE_POSTURE = sole`, ~0.4 if `one-of-several` (conservative, leaves room for the operator's other systems). Express as a rounded dollar figure.
- `INTENSIVE_OPERATION_THRESHOLD` = ~10% of `PROJECT_AUTOMATION_BUDGET` (one estimated-expensive operation above this pauses for operator approval).
- A purely operator-invoked system (no scheduled/background runs per the step-01 shape signals) consumes little or none of this pool; keep the questions brief and frame honestly ("if your system does work on its own…"). *(Conditioning the whole step on `probe_1_scheduled_cadence` is a noted future refinement; v0 asks regardless, framed honestly.)*

---

## FIN-1 — Plan identification

**Ask the user:**

> Which Claude plan are you on? *(I use this to size how much your system can do on its own each month — you won't have to work any of that out.)*
>
> - **Pro**
> - **Max 5x**
> - **Max 20x**
> - **Team Standard**
> - **Team Premium**
> - **Free**
>
> Not sure? Open claude.ai/settings/billing — your plan's at the top.

**Wait for answer.**

**If Free:**

> The wizard needs a paid Claude plan — Pro at minimum — to build and run an agent system. The free tier doesn't include the automation allowance agents need to operate.
>
> You can upgrade at claude.ai/settings/billing. Pro ($20/month) is enough to get started. Come back and resume when you've upgraded — everything you've told me so far is saved.

Store: `PLAN_TYPE = "free"`

**HARD GATE: Do not proceed. The wizard cannot continue on a Free plan.**

**If Max (5x or 20x):** if the user already named the tier, use it. If they only said "Max," **ask:** "Is your Max plan the 5x ($100/month) tier or the 20x ($200/month) tier?" and **wait.** Store `MAX_TIER = "$100"` (5x) or `"$200"` (20x). Store `PLAN_TYPE = "max"`.

**If Team (Standard or Premium):** if the user already named the tier, use it. If they only said "Team," **ask:** "Is it Team Standard or Team Premium? (You can see which at claude.ai/settings/billing.)" and **wait.** Store `TEAM_TIER = "standard"` or `"premium"`. Store `PLAN_TYPE = "team"`.

**If Pro:** Store `PLAN_TYPE = "pro"`.

**If unsure / can't determine:**

> No problem — check claude.ai/settings/billing when you can; it shows your plan at the top. For now I'll set this up for Pro-level limits, which is the safest starting point, and you can tell me to adjust it later.

Store: `PLAN_TYPE = "unknown"` (treat as Pro for sizing).

**Internally** map the plan to `AUTOMATION_CREDIT_POOL` per the table above (unknown → $20). Update the staging file.

Write sub-step marker: Append `step_02_FIN-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Claim check (paid plans only — brief)

**Say:**

> One quick thing: that monthly automation allowance is something you turn on once for your account. If you haven't yet, you can activate it at claude.ai/settings/billing — I'll remind you again when we set the system live. Want me to note that as a setup step? *(yes/no)*

Note the answer in the staging file under `## Setup reminders` if yes (`[→ setup] Claim/activate Agent SDK automation credit`). Do not block on it.

---

## Orientation (one plain line — sets up both choices)

**Say:**

> Your plan includes some "runs on its own" time each month — work your system does in the background when you're not around — at no extra cost, up to a point. Two quick choices about that.

*(Ground the framing in what the operator told you about their system where it helps — per the Operator Interaction Contract § 2: frame with their context, keep the ask neutral, never pre-fill the answer.)*

---

## FIN-3 — Sharing posture

**Ask the user:**

> Is this your only system, or might you run a few? Anything you build shares that same monthly allowance.
>
> - **Just this one, for now** — it can use most of what your plan includes.
> - **One of a few** — I'll keep it modest so there's room for the others. *(Add another later and I'll rebalance them.)*

**Wait for answer.** Store: `PROJECT_SHARE_POSTURE = "sole"` or `"one-of-several"`. (If genuinely unsure, default `sole` and note it's adjustable.)

*Honest note (say only if asked how the limit is kept):* the system tracks its own estimated use and eases off as it nears its share; because there's no live balance read yet, it keeps a safety margin and errs on the cautious side. The included allowance itself can't be overspent — at the limit, unattended work simply stops.

Write sub-step marker: Append `step_02_FIN-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## FIN-4 — Exhaustion behavior

**Ask the user:**

> If it ever uses up that monthly amount, what should it do?
>
> - **Wait** — stop, and pick back up next month. No extra cost.
> - **Keep helping when you're around** — stop working on its own, but still help out whenever you're using it. No extra cost.
> - **Keep going on its own** — keep running past what's included, which costs a little extra. You set the limit, and I'll always tell you before it spends.
>
> Not sure? I'll choose **Wait** — it never costs extra, and you can change any of this later just by telling me.

**Wait for answer.** Store: `EXHAUSTION_BEHAVIOR = "wait"` | `"interactive-fallback"` (keep helping when you're around) | `"paid-overflow"` (keep going on its own). Default unsure → `"wait"`.

Write sub-step marker: Append `step_02_FIN-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## FIN-5 — Paid-overflow setup (CONDITIONAL — only if FIN-4 == "paid-overflow")

**If `EXHAUSTION_BEHAVIOR != "paid-overflow"`: skip this entire section.**

**Team-plan billing-authority gate (only if `PLAN_TYPE == "team"`):**

> Quick check — on a Team plan, only an account owner/admin can turn on paid usage. Are you the person who can change billing settings for this plan? *(yes / no / not sure)*

**If no / not sure:**

> No problem — turning on paid overflow needs an account owner, so I won't set that up now (your admin can switch it on later). Without it, here's what your system can do at no extra cost — which would you prefer?
>
> - **Wait** — stop when it reaches the monthly amount, and pick back up next month.
> - **Keep helping when you're around** — stop working on its own, but still help out whenever you're using it.

**Wait for answer.** Store `EXHAUSTION_BEHAVIOR = "wait"` or `"interactive-fallback"` per the operator's choice (no default — let the operator decide between the two no-cost behaviors). Add to staging `## Setup reminders`: `[→ setup] Operator chose paid overflow but needs a Team admin to enable usage credits — revisit once enabled.` Skip the rest of FIN-5.

**If yes (or non-Team plan), continue:**

> Two quick things:
>
> 1. How much extra per month are you comfortable spending? I'd start with a **$[propose a small default — e.g. $20]** cap — does that work, or would you prefer a different number?
> 2. You'll switch on extra usage in your Claude billing settings, and **leave auto-reload off** so your cap is a real ceiling. I'll show you exactly how when we set the system live.
>
> Once it's on paid usage, I'll alert you when it starts and as it nears your limit, keep a safety margin, and stop before the cap.

**Wait for answer.** Store: `PAYG_CAP = "$<amount>"`. Add to staging `## Setup reminders`: `[→ setup] Enable usage credits + set monthly spending cap to $<amount> at claude.ai/settings/usage; leave auto-reload OFF`.

*(Honest internal note: the operator's Anthropic platform spending cap is the AUTHORITATIVE hard limit; the generated system's `PAYG_CAP` is an early-stop guard + alerting + graceful checkpoint, enforced on its own conservative estimate. Both are recorded so the emitted system warns and stops early.)*

Write sub-step marker: Append `step_02_FIN-5: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Confirm (brief, plain)

**Say (substitute the operator's choices in plain language; do NOT recite credit/pool jargon):**

> Got it. Your system will do its own background work within what your plan includes, and if it ever reaches that point it'll **[wait for next month / keep helping when you're around / keep going at up to $[PAYG_CAP]]**. I'll also pause for your OK before any unusually large single task. You can change any of this later just by telling me.

This step **captures the operator's plain choices only** (plan, sharing posture, exhaustion behavior, and the paid-overflow cap if chosen) — recorded as the FIN source answers below. Do **not** compute or store `PROJECT_AUTOMATION_BUDGET` or `INTENSIVE_OPERATION_THRESHOLD` here: those dollar values are derived deterministically at the operations step where the financial guardrail group closes, from these same source answers. (The arithmetic above is wizard-internal context so you can answer honestly if the operator asks how the limit is kept — it is not a compute-to-staging instruction.)

---

## P02-end — Shape-detection fallback probes (CONDITIONAL)

Per `wizard/shape_detection.md` § 2.2 + § 3 promotion logic. Read the `## Shape detection` section in `~/claude-wizard-draft/wizard_session_draft.md`:

- **If `shape_hypothesis.status == emitted` with `detected_at_step: 01`:** step 01 emitted at HIGH confidence (finalized). Fallback probes do NOT fire. Skip directly to the success condition.
- **If `shape_hypothesis.status == pending_step_02_fallback`:** step 01 deferred emit (MEDIUM or LOW confidence). Fallback probes 5-8 fire now.
- **If `shape_hypothesis.status` is unset OR shape_hypothesis block missing:** internal wizard state error (P1-8 didn't write the status field). Halt with internal-error message per the same pattern as `_pre_step_05_recheck.md` prerequisites; foundation state preserved.

### Lead-in to operator (only if fallback fires)

**Say:**

> Quick check — your project's a little harder to categorize from the first four questions, so I have a few more to nail it down. Same yes/no/unsure pattern.

---

### P02-FB-1 — State-memory probe (probe-5)

**Ask the user:**

> Should the system remember things between times you use it?

**Accept:** yes / no / unsure. Same one-follow-up resolution pattern as step-01 probes.

**Store:** `probe_5_state_memory = yes | no | unsure`

Write sub-step marker: Append `step_02_P02-FB-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

### P02-FB-2 — Regular-pattern probe (probe-6)

**Ask the user:**

> Does it need to do something automatically, on a regular pattern — like every day, every Monday morning, every hour?

**Accept:** yes / no / unsure.

**Store:** `probe_6_regular_pattern = yes | no | unsure`

Write sub-step marker: Append `step_02_P02-FB-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

### P02-FB-3 — Operator-confirm probe (probe-7)

**Ask the user:**

> Should the system ask you before doing anything important — like making a booking, sending money, or contacting someone?

**Accept:** yes / no / unsure.

**Store:** `probe_7_operator_confirm = yes | no | unsure`

Write sub-step marker: Append `step_02_P02-FB-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

### P02-FB-4 — Document-output probe (probe-8)

**Ask the user:**

> Does it produce a document, packet, or report that you'll review or share?

**Accept:** yes / no / unsure.

**Store:** `probe_8_document_output = yes | no | unsure`

Write sub-step marker: Append `step_02_P02-FB-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

### P02-FB-5 — Classifier final emit [INTERNAL]

Do not ask the operator anything. Apply the classifier per `wizard/shape_detection.md` § 2.3 + § 3 across ALL 8 probes (step 01 + step 02 fallback):

1. Re-tally strong-positive and strong-negative signals per shape using all 8 probe values
2. Recompute confidence (HIGH / MEDIUM / LOW)
3. Emit final hypothesis (include status:emitted + schema_versions + handoff_phase + mixed_component_basis):

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
  confidence: <final confidence>
  detected_at_step: 02
  v1_supported: <true if shape == markdown-agents else false>
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: <true if confidence == low else false>
  operator_signals:
  probe_1_scheduled_cadence: <stored value> # derived from runtime_mode (yes only for "On a schedule"); shape-neutral
  probe_2_multi_user: <stored value>
  probe_3_thinking_partner: <stored value>
  probe_4_external_software: <stored value> # outbound; shape-neutral
  probe_5_state_memory: <stored value>
  probe_6_regular_pattern: <stored value>
  probe_7_operator_confirm: <stored value>
  probe_8_document_output: <stored value>
  probe_9_always_on: <stored value> # derived from runtime_mode (yes only for "All the time")
  probe_10_inbound_serve: <stored value>
  forward_offered_signals_at_step_01: <preserved from step 01 placeholder>
  mixed_component_basis: <empty list unless shape == mixed; if shape == mixed, list constituent component shapes detected from probe signals + free-text signals>
  fallback_mode_offered: not_offered
  emit_timestamp: <ISO 8601 timestamp>
  recheck_log: []
```

If final emit is `shape: unknown` + `confidence: low`: set `forced_recheck_at_step_05: true` per § 3 promotion logic.

Write sub-step marker: Append `step_02_P02-FB-5: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## P02-FB-6 — Unsupported-shape transition (CONDITIONAL; fires only when step 02 final emit is HIGH-or-MEDIUM-confidence non-markdown)

**Trigger condition (comply with the relevant product spec section honest-disclosure-at-step-02 mandate; trigger uses unambiguous field combination):**

- `shape_hypothesis.status == emitted` (P02-FB-5 wrote the field for finalized step-02 emit) AND `shape_hypothesis.detected_at_step == 02` AND `shape_hypothesis.v1_supported == false` AND `shape_hypothesis.confidence in [high, medium]`

If trigger does NOT match (markdown-agents final emit; OR LOW-confidence `unknown` emit with forced_recheck_at_step_05 = true; OR P02-FB-5 not fired because step 01 already emitted HIGH-confidence markdown-agents): SKIP P02-FB-6. Proceed to step-02 success condition.

**Special case:** if `shape_hypothesis.fallback_mode_offered` is already set (operator hit P1-9 at step 01 and chose foundation-only): SKIP P02-FB-6 (transition already happened at step 01).

**If trigger matches:** fire the unsupported-shape transition per `wizard/shape_detection.md` § 6 NOW (do not defer to pre-step-05).

Behavior is identical to step 01's P1-9 — same operator-facing message, same two-choice path, same staging-file updates. Substitute the classified shape in plain language per the same pattern.

Say to operator (verbatim; same template as step 01 P1-9):

> Your project looks like a [shape description in plain language]. v1 of the wizard generates complete systems for one specific shape (markdown agents that you work with through Claude Code on your own machine).
>
> Two options:
>
> **(a) Stop here — wait for a future wizard release.** Your project file is saved at `~/claude-wizard-draft/wizard_session_draft.md`. When the wizard adds support for your shape, we can pick up.
>
> **(b) Foundation-only mode.** I can produce a foundation-doc set for your project — the planning documents (vision, approach, technical architecture, etc.) abstracted from implementation shape. You'd take those docs to Claude Code directly to build the implementation yourself, OR wait for v2 shape support. I won't generate the system implementation itself (no agents, scripts, or run files).
>
> Which would you like? (Say "a" or "b".)

**If (a) scope-out:**

```yaml
shape_hypothesis:
  fallback_mode_offered: scope-out
  scope_out_timestamp: <ISO 8601>
```

Say exit message; exit cleanly. Do NOT proceed to step 03.

**If (b) foundation-only:**

```yaml
shape_hypothesis:
  fallback_mode_offered: foundation-only
  foundation_only_offered_timestamp: <ISO 8601>
```

Say confirmation message; proceed to step 03.

Write sub-step marker: Append `step_02_P02-FB-6: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Recording answers (event transcript)

Record this step's `hitl_autonomy` source answers to `~/claude-wizard-draft/wizard_transcript.jsonl` (values from the staging fields captured above). They feed the financial guardrail + the HITL map + autonomy defaults derived at the step-13 barrier:

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid FIN-1 --group hitl_autonomy --value "<plan type>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid FIN-3 --group hitl_autonomy --value "<share posture: sole | one-of-several>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid FIN-4 --group hitl_autonomy --value "<exhaustion behavior: wait | interactive-fallback | paid-overflow>"
```

If `EXHAUSTION_BEHAVIOR == "paid-overflow"`, also record FIN-5:

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid FIN-5 --group hitl_autonomy --value "<payg cap, e.g. $20>"
```

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 02.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 02.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

FIN-1 (plan identified — or hard-gated on Free), FIN-3 (sharing posture), and FIN-4 (exhaustion behavior) answered and stored; FIN-5 (paid-overflow cap) stored if and only if `EXHAUSTION_BEHAVIOR == "paid-overflow"`.

**Write completion marker:** Append `step_02: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `03_user_profile.md`.
