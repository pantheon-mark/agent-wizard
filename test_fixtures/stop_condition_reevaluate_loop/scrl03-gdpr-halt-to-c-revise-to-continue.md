---
fixture_id: scrl03-gdpr-halt-to-c-revise-to-continue
schema_version: fixture-replay-v1
fixture_class: stop-condition-reevaluate-loop
source_scenario: sc02-gdpr-markdown-halt
entry_path: pre_step_05_Step_2a_halt_path
operator_choice_at_halt: (c) regulatory_exposure_revise
expected_loop_iterations: 1
expected_regulatory_revision: gdpr_applicable yes → no
expected_post_iteration_fired_conditions: []
expected_terminal_outcome: continued
expected_terminal_reason: regulatory_exposure_revised_clears_conditions
expected_fallback_mode_offered: not_offered
notes: GDPR halt at pre-step-05 → operator picks (c) → UP-6 re-asked with GDPR-context disclosure → operator clarifies (no actual EU customers; they assumed GDPR applies broadly) → gdpr_applicable revised to no → condition 2 no longer fires → continue to step 05. Exercises the (c) regulatory-revise path's value proposition — operator misclassified at step 03; (c) gives them the recovery surface. Single loop iteration (cap not exercised).
---

# Fixture scrl03 — GDPR halt → (c) regulatory-revise → conditions cleared → continue

## Synthetic operator inputs

Inherits from `sc02-gdpr-markdown-halt.md` fixture:

- P1-1: "Marketing email assistant"
- P1-2: "I run a small B2B SaaS in the US. I want a Claude-powered helper to draft my marketing emails — review my drafts, suggest subject lines, check tone. Just me using it on my laptop."
- Step 01 probes: P1-4 no / P1-5 no / P1-6 yes / P1-7 no (markdown-agents)
- Step 03 UP-6.1: marks #3 (Personal data about individuals — customers / users)
- UP-6.2 follow-up: "I have a customer list with names and emails. I'm not sure if GDPR applies — better safe than sorry, I'll say yes." → `gdpr_applicable: yes` (initial)
- Store `gdpr_applicable: yes`

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

Stop-condition 2 fires: `gdpr_applicable == yes` AND `control_matrix_active.access_control_authn != enforced` (markdown-agents has `advisory` only; no DSR endpoint capability at v0).

`shape_hypothesis.fallback_mode_offered == not_offered` → HALT path.

Wizard says halt message; offers (a) / (b) / (c). **Operator picks (c).**

## Expected loop sub-module behavior (iteration 1, (c) path)

`_stop_condition_reevaluate_loop.md` § 4 entry:

1. **Counter increment.** `shape_revision.iteration: 0 → 1`. `pending: true`.
2. **Honest-characterization disclosure** (§ 4.2 verbatim with GDPR-specific examples):

   > OK, let me re-ask the regulatory questions. The stop condition that fired was that GDPR applies — if your project actually doesn't fall under GDPR's scope, the stop condition won't fire on re-evaluation. Common reasons operators initially answer "yes" to GDPR but later revise to "no":
   >
   > — **GDPR:** "GDPR applies if you have EU customers OR EU-based users (regardless of payment / commercial relationship). Not just any project that might be accessed from the EU."

3. **UP-6 re-ask** for GDPR field:
   - "Earlier you said GDPR applies (yes). Based on the clarification above, do you want to revise that answer?"
   - **Operator answers:** "Actually, my customer list is all US-based businesses. I don't have any EU customers. I was being over-cautious." → revise `gdpr_applicable: yes → no`.
4. **Record revision** in `shape_revision.history[1].regulatory_exposure_revised[]`:
   ```yaml
   regulatory_exposure_revised:
     - field: gdpr_applicable
       old: yes
       new: no
       reason: operator_clarification
   ```
5. **Re-evaluate stop conditions** (§ 4.4) against updated `regulatory_exposure` + unchanged `control_matrix_active`:
   - Condition 1 (HIPAA): `hipaa_applicable == no` → not fired
   - Condition 2 (GDPR): `gdpr_applicable == no` (revised) → not fired
   - Condition 3 (PCI-DSS): `pci_dss_applicable == no` → not fired
   - Condition 4 (regulated + no framework): not applicable since no framework applies after revision
6. **No conditions fire.** Outcome: `continued`. § 7 Terminal: continued.

## Expected § 7 Terminal: continued behavior

Wizard says:

> OK, after re-evaluation, GDPR no longer applies. We can continue with markdown-agents generation. Vision phase next.

`shape_revision.pending: false` set; loop history preserved.

## Expected staging-file state at terminal

```yaml
shape_revision:
  pending: false
  iteration: 1
  iteration_cap: 2
  history:
    - iteration: 1
      entered_at: <ISO 8601>
      entered_from: pre_step_05
      pre_iteration_shape: markdown-agents
      pre_iteration_fired_conditions: [2]
      operator_choice: (c) regulatory_exposure_revise
      probes_re_asked: [UP-6-gdpr]
      regulatory_exposure_revised:
        - field: gdpr_applicable
          old: yes
          new: no
          reason: operator_clarification
      post_iteration_shape: markdown-agents
      post_iteration_fired_conditions: []
      outcome: continued
      terminal_reason: regulatory_exposure_revised_clears_conditions
      terminal_at: <ISO 8601>
regulatory_exposure:
  gdpr_applicable: no   # revised from yes
  # ... other fields unchanged
shape_hypothesis:
  shape: markdown-agents
  fallback_mode_offered: not_offered   # unchanged; operator did NOT go to foundation-only or scope-out
schema_versions:
  schema_major: 0
  schema_minor: 2
```

## Expected downstream behavior

Wizard proceeds to pre_step_05 Step 3 (re-check trigger evaluation) per `_pre_step_05_recheck.md` Step 3, then to step 05 vision generation. Full wizard flow continues normally (NOT foundation-only mode). Foundation-only-mode entry guards at steps 05-15 take the `produce_system_implementation == true` branch per `_foundation_only_mode_gate.md` Section 2 derivation rule (label is `not_offered`).

## Discrimination note

This fixture exercises the **(c) regulatory-revise path's load-bearing value**: in v1, this is the only path that lets an operator avoid foundation-only mode after hitting a stop condition (because all v1 shapes are markdown-agents and markdown-agents structurally fails on enforced compliance fields).

The honest-characterization disclosure at § 4.2 is what makes this work — operator hears the GDPR-specific examples ("GDPR applies if you have EU customers"), realizes their initial answer was over-cautious, revises. Without (c), the operator would be forced through the (b) loop into foundation-only OR scope-out — losing real-system generation for a regulatory concern that doesn't actually apply.

Per advisor per a prior advisor finding framing: operator-driven clarification on UP-6 is a legitimate revision class (recorded as `reason: operator_clarification` per schema); the wizard is NOT pushing the operator to "say no" to escape the halt — it's surfacing the framework's actual applicability scope so the operator can answer correctly.
