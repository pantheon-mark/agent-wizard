# 02 — Financial Guardrails

## What this file does
Establish the financial guardrails that govern all autonomous spending by the system. Three elements: plan type identification (which determines rate limits and billing behavior), monthly spend ceiling, and calibration guidance tailored to the user's specific plan. These answers are stored in `project_instructions.md` and enforced by the system from the first day of operation.

## When this file runs
After `01_phase1_capture.md` completes. The staging file exists and is being updated after each answer.

## Prerequisites
Staging file at `~/claude-wizard-draft/wizard_session_draft.md` has been created and contains the P1-1 and P1-2 answers.

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

> **Step 3 of 16 — Financial setup**
> We'll set spending limits so your system knows its boundaries.

---

## FIN-1 — Plan type identification

**Ask the user:**

> Before we set up your system's spending limits, I need to know which Claude plan you're on. Different plans have different rate limits and billing — and that affects how much your agents can do.
>
> Which best describes your plan?
>
> - **Pro** ($20/month) — The standard paid plan for individuals. Fixed monthly cost with a daily message cap.
> - **Max 5x** ($100/month) — A higher personal tier, with roughly 5× Pro's usage. For regular, heavier use.
> - **Max 20x** ($200/month) — The highest personal tier, with roughly 20× Pro's usage. For intensive use.
> - **Team Standard** ($100/user/month) — A business plan shared across a team; same price and per-seat capacity as Max 5x. Its own billing, shared rate limits.
> - **Team Premium** ($200/user/month) — The higher business tier; same price and per-seat capacity as Max 20x.
> - **Free** — You use Claude without paying.
>
> If you're not sure, check claude.ai/settings/billing — it shows your current plan.

**Wait for answer.**

**If Free:**

> The wizard needs a paid Claude plan — Pro at minimum — to build and run an agent system. The free tier doesn't provide enough capacity for agents to operate reliably.
>
> You can upgrade at claude.ai/settings/billing. Pro ($20/month) is enough to get started. Come back and resume when you've upgraded — everything you've told me so far is saved.

Store: PLAN_TYPE = "free"

**HARD GATE: Do not proceed. The wizard cannot continue on a Free plan.**

**If Pro:**

> Great — Pro is the most common plan for running a system like this. Here's how it works with agents:
>
> - Your cost is fixed at $20/month — agent activity doesn't add extra charges on top of your subscription.
> - Pro has a daily message cap. When you or your agents approach it, Claude slows down (rate-limiting) rather than stopping entirely. Your agents still work, just more slowly during high-usage periods.
> - The system I'll build for you manages its workload to stay within your limits — it spreads tasks across the day rather than doing everything at once.

Store: PLAN_TYPE = "pro"
Store: OVERAGE_PLAN_TYPE = "rate-limited"

**If Max 5x or Max 20x:**

> Max gives you the most room to work with — your agents will rarely hit capacity constraints.

If the user already named the tier (Max 5x or Max 20x), use it. If they only said "Max," **ask:** "Is your Max plan the 5x ($100/month) tier or the 20x ($200/month) tier?" and **wait for the answer.**

Store: MAX_TIER = "$100" (Max 5x) or "$200" (Max 20x)

> Here's how Max works with agents:
>
> - Your cost is fixed at $[MAX_TIER]/month. No surprise charges from agent activity.
> - Max has significantly higher rate limits and priority access. Your system can handle more concurrent work and intensive tasks without slowing down.
> - Rate-limiting is rare on Max — you'd need sustained heavy use before it kicks in.

Store: PLAN_TYPE = "max"
Store: OVERAGE_PLAN_TYPE = "rate-limited"

**If Team Standard or Team Premium:**

> Team plans work a bit differently. Let me confirm your tier and ask two quick follow-ups.

If the user already named the tier (Team Standard or Team Premium), use it. If they only said "Team," **ask:** "Is it Team Standard (the $100/seat tier, same capacity as Max 5x) or Team Premium (the $200/seat tier, same capacity as Max 20x)?" and **wait for the answer.**

Store: TEAM_TIER = "standard" (Team Standard) or "premium" (Team Premium)

> **First:** Do you have access to your team's billing settings at claude.ai/settings/billing, or does someone else manage that?

**Wait for answer.** Store: TEAM_BILLING_ACCESS = true or false

> **Second:** How many people are on your team plan?

**Wait for answer.** Store: TEAM_SIZE = the number given

> Here's what matters for your system on a Team plan:
>
> - Rate limits are shared across everyone on the plan. Your agents' activity counts toward the team's total usage.
> - I'll configure the system to be mindful of shared limits so your agents don't crowd out your teammates.
> - If someone else manages billing, you may want to let them know you're setting up an agent system — they'll see the usage.

Store: PLAN_TYPE = "team"
Store: OVERAGE_PLAN_TYPE = "team-managed"

**If unsure or can't determine:**

> No problem. Check claude.ai/settings/billing when you get a chance — it shows your plan right at the top. For now, I'll assume Pro-level limits, which is the safest starting point. You can update this any time.

Store: PLAN_TYPE = "unknown"
Store: OVERAGE_PLAN_TYPE = "unknown"

Update staging file with all stored values.

Write sub-step marker: Append `step_02_FIN-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## FIN-2 — Monthly spend ceiling

**Ask the user:**

> Now let's set a monthly ceiling — the point where the system stops all autonomous work and checks in with you. This isn't a prediction of what you'll spend — it's a safety net.
>
> Your [PLAN_TYPE] plan has a fixed subscription cost, so this ceiling is about how much of your plan's capacity the system is allowed to use. If it hits this limit, it pauses and waits for you to decide what to do next.
>
> Some people start at $20 and adjust up. Others set $100 from day one. Your system won't use anywhere near this in the early weeks.
>
> What number feels right to start?

**Wait for answer.** Accept any dollar amount. If the user gives a range (e.g. "maybe $50 to $100"), pick the lower end and note it.

**Once you have a number:**

Calculate the intensive operation threshold at 10% of the ceiling (e.g. if ceiling is $50, threshold is $5.00).

**Say this:**

> Got it — I'll set your ceiling at $[SPEND_CEILING]. Any time a single operation is estimated to cost more than $[INTENSIVE_THRESHOLD] on its own, the system will pause and ask for your approval before proceeding. You can raise or lower these at any time.

Store:
- SPEND_CEILING = the dollar amount
- INTENSIVE_OPERATION_THRESHOLD = 10% of SPEND_CEILING (rounded to two decimal places)

Update staging file with both values.

### Calibration guidance (after FIN-2, before proceeding)

After storing the ceiling, provide calibration guidance based on the user's plan type (FIN-1) and ceiling amount. This helps the user understand what their budget can support — framed in terms of both what the system can do and the usage limits of their plan.

**If PLAN_TYPE = "pro":**

> A few things worth knowing about your ceiling and your Pro plan together:
>
> **Usage limits:** Pro gives you a daily message cap. Your agents share this cap with your personal Claude use. The system manages its workload to stay under the cap, but on days when you also use Claude heavily, agents may slow down.
>
> **What your ceiling supports:**
> - **Under $20/month:** Light, focused work — checking a few things regularly and alerting you when something needs attention. You'll want to keep your agent team small (1–2 agents) and run them on a schedule rather than continuously.
> - **$20–$50/month:** Comfortable range for a small team of agents handling regular tasks — monitoring, summarizing, and flagging things for your review. Enough headroom for occasional intensive operations.
> - **$50–$100/month:** Room for a more active system — multiple agents running frequently, handling more complex work.
> - **Over $100/month:** Your ceiling gives plenty of room. Budget won't be a constraint in normal operation.
>
> Since your Pro subscription is a fixed $20/month, the ceiling is about how much of your plan's capacity the system uses — not about surprise charges. If agents regularly bump against the ceiling or the daily message cap, that's a signal to either raise the ceiling, spread tasks across off-peak hours, or consider upgrading to Max.

**If PLAN_TYPE = "max" or PLAN_TYPE = "team":**

First determine the **capacity tier** — the Max-equivalent envelope this plan provides (Team plans share their counterpart Max plan's price and per-seat capacity):

- **5x tier:** Max 5x ($100) — or Team Standard ($100/seat).
- **20x tier:** Max 20x ($200) — or Team Premium ($200/seat).

**If the 5x tier (Max 5x or Team Standard):**

> A few things worth knowing about your ceiling and your plan together:
>
> **Usage limits:** Your plan gives you roughly 5× Pro's capacity, with higher rate limits and priority access. Rate-limiting is uncommon in normal use.
>
> **What your ceiling supports:**
> - **Under $50/month:** Conservative — light, focused work, leaving most of your capacity free.
> - **$50–$100/month:** Comfortable for a moderately active system with several agents handling regular tasks.
> - **Over $100/month:** Plenty of room; budget won't constrain normal operation.

**If the 20x tier (Max 20x or Team Premium):**

> A few things worth knowing about your ceiling and your plan together:
>
> **Usage limits:** Your plan gives you roughly 20× Pro's capacity — the most headroom available. Rate-limiting is rare; you'd need sustained heavy concurrent use before it kicks in.
>
> **What your ceiling supports:**
> - **Under $50/month:** Conservative — leaves most of your capacity unused.
> - **$50–$150/month:** Comfortable for a fully active system — multiple agents running frequently, handling complex work, with budget for intensive operations.
> - **Over $150/month:** Full room to operate; budget and capacity won't be constraints.

**If PLAN_TYPE = "team" (either tier), also add the shared-capacity note:**

> One Team-specific note: your tier's capacity is **per seat**, but heavy agent activity still draws on your team's shared usage across all [TEAM_SIZE] members. Setting the ceiling conservatively keeps agent work from crowding out teammates. If someone else manages billing, let them know you're running an agent system — they'll see the usage.

In all cases:

> Your subscription is a fixed monthly cost — the ceiling is about how much of your plan's capacity the system uses, not about surprise charges.

**If PLAN_TYPE = "unknown":**

Use the Pro guidance above. Add:

> Once you've confirmed your plan type (check claude.ai/settings/billing), let me know and I can adjust these settings to match.

**Note for step 13 cross-reference:** When SCALE-1 through SCALE-4 are answered in step 13 (operations), the wizard should compare the declared scale/velocity against the FIN-2 ceiling. If the scale suggests higher usage than the ceiling comfortably supports (e.g., Large scale tier with a $10 ceiling), surface the discrepancy to the user in plain language and ask if they'd like to adjust either the ceiling or the scale expectation. This check happens in step 13, not here — record `FIN_CALIBRATION_DELIVERED = true` in the staging file so step 13 knows to run the cross-reference.

Store: FIN_CALIBRATION_DELIVERED = true in staging file.

Write sub-step marker: Append `step_02_FIN-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

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

Record this step's `hitl_autonomy` source answers to `~/claude-wizard-draft/wizard_transcript.jsonl` (values from the staging fields captured above). They inform the HITL map + autonomy defaults derived at the step-13 barrier:

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid FIN-1 --group hitl_autonomy --value "<plan type>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid FIN-2 --group hitl_autonomy --value "<monthly spend ceiling>"
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

FIN-1 (plan type identified — or hard-gated on Free) and FIN-2 (spend ceiling set) answered and stored.

**Write completion marker:** Append `step_02: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `03_user_profile.md`.
