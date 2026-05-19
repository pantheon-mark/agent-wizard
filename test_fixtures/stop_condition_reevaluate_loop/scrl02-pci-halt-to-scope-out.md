---
fixture_id: scrl02-pci-halt-to-scope-out
fixture_class: stop-condition-reevaluate-loop
source_scenario: sc03-pci-markdown-halt
entry_path: pre_step_05_Step_2a_halt_path
operator_choice_at_halt: (b) change_shape
expected_loop_iterations: 2
expected_classifier_re_emit: markdown-agents
expected_post_iteration_fired_conditions: [3]
expected_terminal_outcome: scope_out
expected_terminal_reason: iteration_cap_reached
expected_operator_choice_at_forced_disclosure: scope-out
expected_fallback_mode_offered: scope-out
expected_stop_conditions_mutation: none (terminal scope_out does NOT trigger cross-slice mutation — only terminal foundation_only does per R1 C-002)
notes: PCI-DSS halt at pre-step-05 → operator picks (b) → loop iterations 1 + 2 → cap reached → operator picks scope-out at forced-terminal final-choice prompt. Exercises clean-exit path through the loop. Producer-visible outcome is scope_out (NOT forced_terminal) per R1 C-001 disposition; terminal_reason: iteration_cap_reached captures how operator reached terminal.
---

# Fixture scrl02 — PCI-DSS halt → (b) loop → cap → scope-out

## Synthetic operator inputs

Inherits from `sc03-pci-markdown-halt.md` fixture:

- P1-1: "Subscription billing dashboard"
- P1-2: "I run a small subscription business and want a Claude-powered dashboard to help me see who's paid, who's overdue, and draft past-due reminders. I'd use it on my laptop a couple times a week."
- Step 01 probes: P1-4 no / P1-5 no / P1-6 yes / P1-7 no (markdown-agents)
- Step 03 UP-6.1: marks PCI-DSS-related (#5 Financial / payment data)
- UP-6.2 follow-up: "I store full credit card numbers in a spreadsheet to send to my payment processor manually."
- Store `pci_dss_applicable: yes`

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

Stop-condition 3 fires: `pci_dss_applicable == yes` AND `control_matrix_active.encryption_at_rest != enforced` (markdown-agents has `advisory` only).

`shape_hypothesis.fallback_mode_offered == not_offered` → HALT path.

Wizard says halt message; offers (a) / (b) / (c). **Operator picks (b).**

## Expected loop sub-module behavior

**Iteration 1:**

1. Counter increment: `iteration: 0 → 1`. Under cap.
2. Honest-characterization disclosure per § 2.2.
3. Probe re-ask P-5/P-6/P-7 with PCI-constraint framing. Operator answers same way (project genuinely doesn't need continuous-runtime / multi-user / external-software — operator already manually sends data to payment processor).
4. Classifier re-emits: same shape, markdown-agents.
5. Stop-condition re-eval: condition 3 still fires.
6. Branch: iteration == 1 (< cap=2). Outcome: `next_iteration`. Re-offer (a)/(b)/(c).

**Operator picks (b) again at iteration 2.**

**Iteration 2:**

1. Counter increment: `iteration: 1 → 2`. At cap.
2-5. Same as iteration 1.
6. Branch: iteration == 2 (== cap). Internal branch state: `forced_terminal` → § 7 final-choice prompt. Producer-visible outcome (set by module after operator's (i)/(ii) pick): `scope_out` (operator picks (ii)) with `terminal_reason: iteration_cap_reached`.

## Expected § 7 Terminal: forced behavior

Wizard says verbatim (with PCI-DSS substituted for HIPAA):

> We've cycled through 2 iterations of re-evaluation. v1 supports only `markdown-agents` shape, and `markdown-agents` doesn't meet PCI-DSS compliance per stop condition 3. Your remaining options are:
>
> (i) Foundation-only mode — I generate planning documents for your project; you implement separately, OR wait for v2 shape support that meets PCI-DSS compliance natively.
>
> (ii) Save and exit — resume when v2 supports your shape, OR after you've completed an operator-side compliance review and revised your regulatory exposure assessment.
>
> Which would you like? (Say "i" or "ii".)

**Operator picks (ii) save-and-exit.**

## Expected staging-file state at terminal

```yaml
shape_revision:
  pending: false
  iteration: 2
  iteration_cap: 2
  history:
    - iteration: 1
      entered_from: pre_step_05
      pre_iteration_shape: markdown-agents
      pre_iteration_fired_conditions: [3]
      operator_choice: (b) change_shape
      probes_re_asked: [P-5, P-6, P-7]
      classifier_re_emit: markdown-agents
      post_iteration_fired_conditions: [3]
      outcome: next_iteration
    - iteration: 2
      entered_from: pre_step_05
      pre_iteration_shape: markdown-agents
      pre_iteration_fired_conditions: [3]
      operator_choice: (b) change_shape
      probes_re_asked: [P-5, P-6, P-7]
      classifier_re_emit: markdown-agents
      post_iteration_fired_conditions: [3]
      outcome: scope_out             # producer-visible terminal outcome per R1 C-001 (forced_terminal is internal-only)
      terminal_reason: iteration_cap_reached
      terminal_at: <ISO 8601>
shape_hypothesis:
  shape: markdown-agents
  fallback_mode_offered: scope-out
  scope_out_at_halt: <ISO 8601>
stop_conditions:                   # PRESERVED from original halt; no cross-slice mutation for terminal scope_out (only foundation_only triggers mutation per R1 C-002)
  evaluated_at: 05_pre_vision
  fired: [3]
  halted: true                      # preserved; operator chose scope-out so halt remains valid
schema_versions:
  schema_major: 0
  schema_minor: 1
```

## Expected downstream behavior

Wizard exits cleanly. Staging file preserved. No further steps run. Operator can resume the wizard later after completing operator-side compliance review (e.g., switching to a payment processor that doesn't require them to handle full PANs) OR when v2 supports a PCI-DSS-compliant shape.

## Discrimination note

This fixture exercises the **clean-exit path** through the loop. Operator runs the loop honestly (sees the structural mismatch via probe re-ask + iteration cap), then chooses scope-out at the forced-terminal — not because foundation-only is unattractive, but because the operator can take action (modify their data-handling practice) that would change `pci_dss_applicable` to `no` on a future wizard run. Honest characterization at terminal-forced disclosure makes the trade-off visible.
