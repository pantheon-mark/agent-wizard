---
fixture_id: scrl01-hipaa-halt-to-foundation-only
fixture_class: stop-condition-reevaluate-loop
source_scenario: sc01-hipaa-markdown-halt
entry_path: pre_step_05_Step_2a_halt_path
operator_choice_at_halt: (b) change_shape
expected_loop_iterations: 2
expected_classifier_re_emit: markdown-agents
expected_post_iteration_fired_conditions: [1]
expected_terminal_outcome: foundation_only
expected_terminal_reason: iteration_cap_reached
expected_operator_choice_at_forced_disclosure: foundation-only
expected_fallback_mode_offered: foundation-only
expected_stop_conditions_mutation: {halted: false, documented_in_foundation: [1], resolved_via: stop_condition_reevaluate_loop_foundation_only}
notes: |
  HIPAA halt at pre-step-05 → operator picks (b) → step 02 fallback probes re-asked → operator gives same answers (project really does need to be markdown-agents) → classifier re-emits same shape → conditions still fire → operator picks (b) again → iteration 2 same trace → iteration cap reached → operator forced to choose foundation-only OR exit → picks foundation-only. Module mutates stop_conditions block per R1 C-002: rolls fired conditions into documented_in_foundation + flips halted to false + records resolved_via provenance.
---

# Fixture scrl01 — HIPAA halt → (b) loop → foundation-only converged

## Synthetic operator inputs

Inherits from `sc01-hipaa-markdown-halt.md` fixture:

- P1-1: "Patient note assistant"
- P1-2: "I'm a primary care physician. I want to use Claude to help me write up patient encounter notes from my dictation..."
- Step 01 probes: P1-4 no / P1-5 no / P1-6 yes / P1-7 no (all signaling markdown-agents)
- Step 03 UP-6.1: #1 (Health information) + UP-6.2: "I'm a covered entity under HIPAA"
- Store `hipaa_applicable: yes`

## Expected classifier emit (at end of step 01)

```yaml
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  detected_at_step: 01
  v1_supported: true
  fallback_mode_offered: not_offered
```

## Expected pre-step-05 re-check Step 2 evaluation

Stop-condition 1 fires: `hipaa_applicable == yes` AND `control_matrix_active.audit_trail_crud == advisory` (markdown-agents D1 § 2.2 column).

`shape_hypothesis.fallback_mode_offered == not_offered` → HALT path (per `_pre_step_05_recheck.md` Step 2a).

Wizard says halt message; offers (a) / (b) / (c).

**Operator picks (b).**

## Expected loop sub-module behavior (iteration 1)

`_stop_condition_reevaluate_loop.md` § 2 entry:

1. **Counter increment.** `shape_revision.iteration: 0 → 1`. `pending: true`. Under cap (cap=2).
2. **Honest-characterization disclosure** (§ 2.2 verbatim disclosure said to operator).
3. **Probe re-ask** (P-5 / P-6 / P-7 with HIPAA-constraint framing):
   - P-5 (`is_continuous_running`): "Earlier you indicated the system doesn't need to keep running on its own. Given that HIPAA applies, the system would need to support enforced audit-trail. Does that change your answer? Does the system actually need to keep running continuously?" → **Operator answers: no.** (System genuinely doesn't need to be a service; doctor uses it interactively.)
   - P-6 (`is_multi_user`): same framing → **Operator answers: no.**
   - P-7 (`requires_external_systems`): same framing → **Operator answers: no.** (System produces drafts; doctor manually transfers to EMR; no direct API call.)
4. **Classifier re-emit:** same signal profile as original (all no/no/no/yes-thinking-partner). Classifier re-emits `shape: markdown-agents, confidence: high`. No shape change.
5. **`control_matrix_active` unchanged** (shape unchanged).
6. **Stop-condition re-evaluation** (§ 6): condition 1 still fires; `markdown-agents` still has `audit_trail_crud: advisory` against HIPAA.
7. **Branch:** new shape is markdown-agents (v1-supported) AND condition 1 still fires AND iteration == 1 (under cap=2). Outcome: `next_iteration`.
8. **Loop re-offers (a) / (b) / (c) at producer** for iteration 2.

**Operator picks (b) again** at iteration 2 attempt.

Loop re-enters § 2.1: `new_iteration = 2`; `new_iteration <= iteration_cap` (2 == 2; under-or-equal-to). Re-runs steps 2.2-2.5 + § 6. Same shape; same conditions fire.

After this iteration, branch: iteration == 2 (== cap). Internal branch state: `forced_terminal` → § 7 final-choice prompt. Producer-visible outcome (set by module after operator's (i)/(ii) pick): `foundation_only` (operator picks (i)) with `terminal_reason: iteration_cap_reached`.

## Expected § 7 Terminal: forced behavior

Wizard says verbatim:

> We've cycled through 2 iterations of re-evaluation. v1 supports only `markdown-agents` shape, and `markdown-agents` doesn't meet HIPAA compliance per stop condition 1. Your remaining options are:
>
> (i) Foundation-only mode — I generate planning documents for your project; you implement separately, OR wait for v2 shape support that meets HIPAA compliance natively.
>
> (ii) Save and exit — resume when v2 supports your shape, OR after you've completed an operator-side compliance review and revised your regulatory exposure assessment.
>
> Which would you like? (Say "i" or "ii".)

**Operator picks (i) foundation-only.**

## Expected staging-file state at terminal

```yaml
shape_revision:
  pending: false
  iteration: 2
  iteration_cap: 2
  history:
    - iteration: 1
      entered_at: <ISO 8601>
      entered_from: pre_step_05
      pre_iteration_shape: markdown-agents
      pre_iteration_fired_conditions: [1]
      operator_choice: (b) change_shape
      probes_re_asked: [P-5, P-6, P-7]
      classifier_re_emit: markdown-agents
      post_iteration_shape: markdown-agents
      post_iteration_fired_conditions: [1]
      outcome: next_iteration
    - iteration: 2
      entered_at: <ISO 8601>
      entered_from: pre_step_05
      pre_iteration_shape: markdown-agents
      pre_iteration_fired_conditions: [1]
      operator_choice: (b) change_shape
      probes_re_asked: [P-5, P-6, P-7]
      classifier_re_emit: markdown-agents
      post_iteration_shape: markdown-agents
      post_iteration_fired_conditions: [1]
      outcome: foundation_only           # producer-visible terminal outcome; CLOSED enum per R1 C-001 (forced_terminal is internal-only branch state)
      terminal_reason: iteration_cap_reached
      terminal_at: <ISO 8601>
shape_hypothesis:
  shape: markdown-agents
  fallback_mode_offered: foundation-only
  foundation_only_offered_timestamp: <ISO 8601>
stop_conditions:                       # MUTATED at terminal foundation_only per R1 C-002 cross-slice rule
  evaluated_at: 05_pre_vision           # preserved from original halt
  fired: [1]                            # preserved from original halt
  halted: false                         # FLIPPED true → false (loop resolved halt to foundation-only)
  documented_in_foundation: [1]         # POPULATED from `fired` so S2.2 gate module § 6 emits HIPAA gap entry in technical_architecture.md
  resolved_via: stop_condition_reevaluate_loop_foundation_only
  halt_message: <preserved verbatim from original halt>
schema_versions:
  schema_major: 0
  schema_minor: 2
```

## Expected downstream behavior

Wizard proceeds to step 05. Foundation-only-mode entry guards fire per `_foundation_only_mode_gate.md` § 3. Steps 05-15 follow adapted paths per S2.2. Step 15 close produces 4-file foundation doc set + project_instructions.md (ADAPT) + manual.md (ADAPT) + next_steps.md (NEW) per `_foundation_only_mode_gate.md` § 5. DOCUMENT-path § "Regulatory & compliance gaps (foundation-only mode)" section added to `technical_architecture.md` with HIPAA gap entry, because `stop_conditions.documented_in_foundation: [1]` is populated by the loop sub-module's terminal foundation_only mutation (per R1 C-002 cross-slice rule); S2.2 gate module § 6 reads this and emits the gap entry.

## Discrimination note

This fixture exercises the **dominant v1 path**: HIPAA-fires → operator opts to loop → loop converges to foundation-only because markdown-agents can't meet HIPAA. The loop's value here is operator-agency + honest discovery: operator sees the structural mismatch (markdown-agents has audit_trail at `advisory`; HIPAA requires `enforced`) before committing to foundation-only. Honest characterization throughout (§ 2.2 disclosure + § 7 forced-terminal language). NOT silent fallback per ADR-0015 § 2.3.
