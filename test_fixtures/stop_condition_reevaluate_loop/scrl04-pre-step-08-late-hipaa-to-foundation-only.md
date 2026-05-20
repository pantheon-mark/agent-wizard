---
fixture_id: scrl04-pre-step-08-late-hipaa-to-foundation-only
schema_version: fixture-replay-v1
fixture_class: stop-condition-reevaluate-loop
source_scenario: markdown-agents shape with no step 03 HIPAA exposure; late-emergence HIPAA implication in vision content
entry_path: pre_step_08_Step_2_late_emergence_halt_path
operator_choice_at_halt: (b) change_shape
expected_loop_iterations: 2
expected_classifier_re_emit: markdown-agents
expected_post_iteration_fired_conditions: [1]
expected_terminal_outcome: foundation_only
expected_terminal_reason: iteration_cap_reached
expected_operator_choice_at_forced_disclosure: foundation-only
expected_fallback_mode_offered: foundation-only
expected_foundation_state_preserved: [vision.md, approach.md]
expected_stop_conditions_mutation: {halted: false, documented_in_foundation: [1], resolved_via: stop_condition_reevaluate_loop_foundation_only}
notes: Operator did NOT surface HIPAA at step 03 UP-6 (project framed generically). Vision content (step 05) mentions "patient communication" → pre-step-08 late-emergence stop-condition check (per `_pre_step_08_recheck.md` Step 2) re-fires HIPAA UP-6 probe → operator confirms HIPAA applies → condition 1 fires at pre-step-08 → operator picks (b) → loop iterations 1 + 2 → cap reached → foundation-only chosen. Vision.md + approach.md preserved on disk through loop iterations (foundation state preserved). Producer-visible terminal outcome is foundation_only (NOT forced_terminal) per R1 C-001; module mutates stop_conditions block per R1 C-002.
---

# Fixture scrl04 — Pre-step-08 late-emergence HIPAA → (b) loop → foundation-only with vision+approach preserved

## Synthetic operator inputs

**Step 01:**

- P1-1: "Care plan note helper"
- P1-2: "I want a helper that organizes notes from sessions with people I work with. Just me using it on my laptop." (Note: ambiguous; operator does NOT surface healthcare context here.)
- Step 01 probes: P1-4 no / P1-5 no / P1-6 yes / P1-7 no (markdown-agents; HIGH confidence)

**Step 02 (not fired):** HIGH confidence at step 01.

**Step 03 UP-6:**

- UP-6.1: operator marks none of the regulated-data buckets (just sees "general business data" framing; doesn't think their work falls under healthcare).
- All `*_applicable` fields → `no`.

**Step 04 / Step 05 (vision content):**

- Vision document content includes phrases like "structured patient communication notes" / "session details for each patient" / "follow-up tracking for each patient encounter."
- **THIS is the late-emergence signal.** Operator's actual work is healthcare-related; they didn't surface it at step 03 because the UP-6 framing didn't make the connection clear.

**Step 06 / Step 07:** approach.md + advisors written without HIPAA flags surfaced.

## Expected pre-step-05 re-check

No stop conditions fire (no regulatory exposure declared at step 03). Re-check confirms `markdown-agents`; proceeds to step 05 vision generation. Vision.md written to disk per step 05.

## Expected pre-step-08 re-check Step 2 (late-emergence)

Per `_pre_step_08_recheck.md` Step 2: scan vision + approach + advisor content for newly-surfaced regulatory exposure.

Vision content matches "patient communication" → re-fire HIPAA framework-applicability probe per Step 2:

> Looking at what we've built so far — the vision and approach documents — I see "structured patient communication notes" and "session details for each patient." That suggests HIPAA may apply (if you're a covered entity OR business associate handling protected health information). Before we generate the architecture, we need to handle this.
>
> [Re-fire UP-6.2 follow-up:] Are you a healthcare provider, plan, clearinghouse, OR a business associate handling PHI on their behalf?

**Operator answers:** "Yes, I'm a licensed therapist. I work with patients in private practice. I should have said HIPAA at the start — I just didn't think of my session notes as 'health information' in the framing of step 03."

Update `regulatory_exposure.hipaa_applicable: no → yes`. Re-evaluate stop conditions per `_pre_step_05_recheck.md` Step 2 logic.

Condition 1 fires: `hipaa_applicable == yes` AND `control_matrix_active.audit_trail_crud == advisory` (still markdown-agents).

## Expected friction-acknowledgment + three-choice offer

Per `_pre_step_08_recheck.md` Step 2 friction-ack (S2.3 Decision E):

> Looking at what we've built so far — the vision and approach documents — I see "structured patient communication notes" and "session details for each patient." That suggests HIPAA applies, which I didn't pick up on at step 03. Before we generate the architecture, we need to handle this.
>
> Note: vision and approach documents are already on disk — they're abstracted from implementation shape (they describe what your system does, not how), so they stay valid through any shape revision or regulatory revision. We won't lose them.

Offer (a) / (b) / (c) per three-choice path. **Operator picks (b).**

## Expected loop sub-module behavior

`_stop_condition_reevaluate_loop.md` § 2 entry with `entered_from: pre_step_08`. Per § 3 counter-reset rule: prior `shape_revision.history[*]` is empty (no pre_step_05 loop fired); counter starts at 0 normally. `iteration: 0 → 1`.

**Iteration 1:**

1. Counter increment: `iteration: 0 → 1`. Under cap (cap=2).
2. Honest-characterization disclosure (§ 2.2 verbatim).
3. Probe re-ask P-5/P-6/P-7 with HIPAA-constraint framing. Operator answers same way (work is genuinely one-person-on-laptop; doesn't need continuous-runtime / multi-user / external-software).
4. Classifier re-emits: same shape, markdown-agents, HIGH confidence.
5. Stop-condition re-eval: condition 1 still fires.
6. Branch: iteration == 1 (< cap). Outcome: `next_iteration`. Re-offer (a)/(b)/(c).

**Operator picks (b) again at iteration 2.**

**Iteration 2:**

1. Counter increment: `iteration: 1 → 2`. At cap.
2-5. Same as iteration 1.
6. Branch: iteration == 2 (== cap). Internal branch state: `forced_terminal` → § 7 final-choice prompt. Producer-visible outcome (set by module after operator's (i)/(ii) pick): `foundation_only` (operator picks (i)) with `terminal_reason: iteration_cap_reached`.

## Expected § 7 Terminal: forced behavior

Wizard says verbatim (with HIPAA substituted):

> We've cycled through 2 iterations of re-evaluation. v1 supports only `markdown-agents` shape, and `markdown-agents` doesn't meet HIPAA compliance per stop condition 1. Your remaining options are:
>
> (i) Foundation-only mode — I generate planning documents for your project; you implement separately, OR wait for v2 shape support that meets HIPAA compliance natively. **Note: vision and approach documents we've already written stay valid and roll forward into the foundation doc set.**
>
> (ii) Save and exit — resume when v2 supports your shape, OR after you've completed an operator-side compliance review and revised your regulatory exposure assessment. **Vision and approach documents on disk are preserved.**
>
> Which would you like? (Say "i" or "ii".)

**Operator picks (i) foundation-only.**

## Expected staging-file + disk state at terminal

```yaml
shape_revision:
  pending: false
  iteration: 2
  iteration_cap: 2
  history:
    - iteration: 1
      entered_from: pre_step_08
      late_emergence_source: vision
      pre_iteration_shape: markdown-agents
      pre_iteration_fired_conditions: [1]
      operator_choice: (b) change_shape
      outcome: next_iteration
    - iteration: 2
      entered_from: pre_step_08
      late_emergence_source: vision
      pre_iteration_shape: markdown-agents
      pre_iteration_fired_conditions: [1]
      operator_choice: (b) change_shape
      outcome: foundation_only           # producer-visible terminal outcome per R1 C-001
      terminal_reason: iteration_cap_reached
      terminal_at: <ISO 8601>
shape_hypothesis:
  shape: markdown-agents
  fallback_mode_offered: foundation-only
  foundation_only_offered_timestamp: <ISO 8601>
regulatory_exposure:
  hipaa_applicable: yes   # revised from no via late-emergence
stop_conditions:                       # MUTATED at terminal foundation_only per R1 C-002 cross-slice rule
  evaluated_at: 08_pre_architecture     # late-emergence evaluation point
  fired: [1]
  halted: false                         # FLIPPED true → false (loop resolved halt to foundation-only)
  documented_in_foundation: [1]         # POPULATED from `fired` so S2.2 gate module § 6 emits HIPAA gap in technical_architecture.md
  resolved_via: stop_condition_reevaluate_loop_foundation_only
  halt_message: <preserved verbatim from original late-emergence halt>
  late_emergence_source: vision
schema_versions:
  schema_major: 0
  schema_minor: 2
```

**Disk state:**
- `<project>/vision.md` — preserved unchanged through loop
- `<project>/approach.md` — preserved unchanged through loop
- `<project>/advisors.md` (if step 07 generated content) — preserved unchanged through loop

## Expected downstream behavior

Wizard proceeds to step 08 architecture phase per pre_step_08 Step 6 completion. Foundation-only-mode entry guard at step 08 fires per `_foundation_only_mode_gate.md` § 3 (placement: post-recheck). Step 08 follows ADAPT-split disposition per `_foundation_only_mode_gate.md` § 3 (PRODUCE `technical_architecture.md` as shape-agnostic foundation doc; SKIP agent roster + permission tier files). Steps 09-15 follow respective adapted paths per gate module.

Step 15 close produces foundation-doc set per `_foundation_only_mode_gate.md` § 5:
- `vision.md` (already on disk from step 05 — preserved through loop) ✓
- `approach.md` (already on disk from step 06 — preserved through loop) ✓
- `technical_architecture.md` (produced at step 08 ADAPT-split) — includes § "Regulatory & compliance gaps (foundation-only mode)" with HIPAA entry
- `execution_plan.md` (produced at step 13)
- `project_instructions.md` (ADAPT — foundation-only voice)
- `manual.md` (ADAPT — pointer doc)
- `next_steps.md` (NEW)

## Discrimination note

This fixture exercises the **pre-step-08 late-emergence loop with foundation state preservation through iterations**. Three key behaviors:

1. **Late-emergence detection** at pre_step_08 catches the HIPAA implication that step 03 UP-6 framing missed. Per ADR-0008 v1 honest-characterization rule — wizard surfaces the gap honestly rather than silently generating a non-compliant system.

2. **Foundation state preserved through loop iterations**: vision.md + approach.md are on disk from earlier steps; the loop's probe re-ask + classifier re-emit + stop-condition re-eval do NOT touch those files. This honors the S2.1 contract `foundation_state.staging_file_preserved: true` semantics extended to vision/approach docs.

3. **Fresh iteration counter at pre_step_08** (S2.3 Decision E): even if a prior pre_step_05 loop had run + reached terminal (not the case here — no prior loop), pre_step_08 invocation would reset counter to 0 before increment. Reason: late-emergence regulatory exposure is genuinely new context; not a continuation of pre_step_05 loop.

The friction-acknowledgment ("vision + approach are on disk; they're abstracted from implementation shape; we won't lose them") is critical — without it, operator may feel "the wizard wasted my time on vision + approach if HIPAA was going to fail." With it, operator sees the documents have lasting value regardless of which path they pick at terminal.
