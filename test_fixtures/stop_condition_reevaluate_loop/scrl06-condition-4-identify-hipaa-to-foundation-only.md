---
fixture_id: scrl06-condition-4-identify-hipaa-to-foundation-only
schema_version: fixture-replay-v1
fixture_class: stop-condition-reevaluate-loop
source_scenario: synthetic-no-direct-ancestor
entry_path: pre_step_05_Step_2a_halt_path
trigger_condition: 4
operator_choice_at_halt: (c) regulatory_exposure_revise
c_sub_case: framework_identification
expected_loop_iterations: 2
expected_regulatory_revision:
  - field: hipaa_applicable
    old: no
    new: yes
    reason: framework_identification
  - field: no_compliance_claim_framework_identification
    old: unknown
    new: no
    reason: framework_identification
expected_post_iteration_1_fired_conditions: [1]
expected_post_iteration_2_fired_conditions: [1]
expected_terminal_outcome: foundation_only
expected_terminal_reason: iteration_cap_reached
expected_fallback_mode_offered: foundation-only
expected_cross_slice_mutation:
  stop_conditions.fired: [1]                              # active terminal-state conditions only (per a prior advisor finding); condition 4 resolved at iter 1
  stop_conditions.documented_in_foundation: [1]           # active terminal compliance gap only
  stop_conditions.resolved_during_loop: [4]               # transitional condition resolved during loop (audit-trail)
  stop_conditions.halted: false                           # flipped from true at terminal foundation_only
  stop_conditions.resolved_via: stop_condition_reevaluate_loop_foundation_only
notes: |
  Condition-4 halt at pre-step-05 → operator picks (c) → identifies HIPAA (was initially marked `hipaa_applicable: no` at UP-6.2 + framework-unknown at #6 path) → mutation `hipaa_applicable: no → yes` + `unknown → no` → condition-1 fires post-revision → loop next_iteration → operator picks (b) at re-prompt → iter 2 probes 5-7 re-asked → markdown-agents re-emitted (same answers) → iter 2 == cap → forced terminal foundation-only (operator picks i). Cross-slice mutation per a prior advisor finding active-vs-transitional distinction: records active terminal condition [1] in `documented_in_foundation` and transitional condition [4] in `resolved_during_loop` audit-trail. Demonstrates the common-path of condition-4 in v1 reality (framework identification triggers conditions 1/2/3 against markdown-agents → foundation-only at iteration cap).
---

# Fixture scrl06 — Condition-4 identify-HIPAA-to-foundation-only

## Synthetic operator inputs

- **P1-1 (project name):** "Health journal helper"
- **P1-2 (purpose):** "I'm building a journaling tool for tracking my health and consultations with my doctor. I want a Claude-powered helper to spot patterns across my notes — symptoms / treatments / lifestyle factors / mood. Just me using it."
- **Step 01 probes:**
  - P1-4 interactive: no
  - P1-5 continuous-running: no
  - P1-6 multi-user: no
  - P1-7 external systems: no
  - → classifier emits `shape: markdown-agents` / `confidence: high`
- **Step 03 UP-6.1:** marks #1 (Health information about identifiable people) + #6 (Other regulated data — government records, education, sector-specific)
- **Step 03 UP-6.2 follow-up for #1:** "It's just my own health information — I'm doing journaling for myself. I'm not a healthcare provider, not a business associate." → wizard stores `hipaa_applicable: no` per UP-6.2 covered-entity-status rule (no covered entity status → HIPAA doesn't apply to personal data of self)
- **Step 03 UP-6.2 follow-up for #6:** "There might be some HIPAA-adjacent state-level health-data requirements that apply to journals shared with healthcare providers — I'm not sure though." → wizard stores `no_compliance_claim_framework_identification: unknown` (this is the condition-4 trigger)

## Expected classifier emit (at end of step 01)

```yaml
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  detected_at_step: 01
  v1_supported: true
  fallback_mode_offered: not_offered
```

## Expected step 03 UP-6 regulatory_exposure state (pre-halt)

```yaml
regulatory_exposure:
  gdpr_applicable: no
  hipaa_applicable: no   # operator said not covered entity for personal use
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: no   # operator marked #1 + #6 (some data-bucket markers active)
  no_compliance_claim_framework_identification: unknown   # operator unsure which framework for #6
  probed_at_step: 03_up6
```

## Expected pre-step-05 re-check Step 2 evaluation

Stop-condition 4 fires: `no_compliance_claim_framework_identification == unknown` AND data-bucket UP-6.1 markers are non-zero (operator marked #1 + #6).

`shape_hypothesis.fallback_mode_offered == not_offered` → HALT path. (a)/(b)/(c) offered. **Operator picks (c).**

## Expected loop sub-module behavior — iteration 1 ((c) path; framework-identification → triggers condition 1)

1. **Counter increment.** `shape_revision.iteration: 0 → 1`. `pending: true`.
2. **§ 4.2 Variant B disclosure** (condition-4 case; same verbatim as scrl05).
3. **§ 4.3 framework-identification path:**
   - Wizard asks for framework identification.
   - **Operator response:** "Actually let me look this up... I think HIPAA does apply because I've been sharing my journal as part of treatment consultations with my doctor. My doctor's office is a covered entity, and if I'm formally part of that treatment relationship, I might count as a business associate handling PHI on their behalf. Let me revise — HIPAA applies."
4. **Mutation per sub-module § 4.3:**
   - Update `hipaa_applicable: no → yes`
   - Update `no_compliance_claim_framework_identification: unknown → no` (framework identified)
   - Append revision entries to `shape_revision.history[1].regulatory_exposure_revised[]`:
     ```yaml
     regulatory_exposure_revised:
       - field: hipaa_applicable
         old: no
         new: yes
         reason: framework_identification
       - field: no_compliance_claim_framework_identification
         old: unknown
         new: no
         reason: framework_identification
     ```
5. **Re-evaluate stop conditions (§ 4.4):**
   - Condition 1 (HIPAA): `hipaa_applicable == yes` AND `control_matrix_active.audit_trail != enforced` (markdown-agents is `advisory` for audit-trail / encryption / access-control per the relevant ADR per-shape control matrix) → **condition 1 fires**
   - Condition 2 (GDPR): not fired
   - Condition 3 (PCI-DSS): not fired
   - Condition 4: `no_compliance_claim_framework_identification == no` → no longer fires
6. **Conditions still fire (condition 1).** Iteration 1 < cap 2 → outcome `next_iteration`. Wizard returns to producer; producer re-offers (a)/(b)/(c) at the halt seam.

## Expected re-prompt at halt seam after iteration 1

Wizard says (per `_pre_step_05_recheck.md` Step 2a re-prompt pattern post-loop next_iteration):

> After re-evaluation, the framework you identified (HIPAA) is now triggering stop condition 1 against markdown-agents — HIPAA requires enforced audit-trail / encryption / access-control, and markdown-agents at v1 provides those as advisory only.
>
> Same three options again:
> (a) Save and exit
> (b) Change the shape and re-evaluate
> (c) Re-evaluate regulatory exposure further

**Operator picks (b)** — "Let me see if maybe the shape is more flexible than I thought; maybe I should answer the questions differently this time."

## Expected loop sub-module behavior — iteration 2 ((b) path; probe re-ask → cap reached)

1. **Counter increment.** `shape_revision.iteration: 1 → 2`. `pending: true`.
2. **§ 2.2 honest-characterization disclosure** (verbatim shape-revision case with HIPAA framework constraint surfaced).
3. **§ 2.3 probe re-ask** for P-5, P-6, P-7:
   - P-5 (`is_continuous_running`): "Earlier you said the system doesn't need to keep running on its own continuously. Given that HIPAA applies, the system would need to support enforced audit-trail and access-control. Does that change your answer?" → Operator: "No, it's still just me using it locally, doesn't need to run on its own."
   - P-6 (`is_multi_user`): "Same question for multi-user — given HIPAA, the system would need enforced access control with role separation. Does your situation actually involve multiple users with distinct roles?" → Operator: "No, just me. My doctor sees the output but doesn't use the system directly."
   - P-7 (`requires_external_systems`): "Same for external systems — given HIPAA, integration with healthcare IT systems would imply BAA-covered API access. Does your system need that?" → Operator: "No, just markdown files on my laptop."
4. **§ 2.4 classifier re-emit:** signals unchanged → `shape: markdown-agents`.
5. **§ 2.5 control_matrix_active** unchanged (shape unchanged).
6. **§ 6 stop-condition re-evaluation:**
   - Condition 1 (HIPAA): still fires (same shape; markdown-agents still `advisory` for HIPAA-required controls)
7. **Iteration 2 == iteration_cap (2).** Internal branch state: `forced_terminal`. Outcome: per § 7 Terminal: forced disclosure.

## Expected § 7 Terminal: forced behavior

Wizard says verbatim:

> We've cycled through 2 iterations of re-evaluation. v1 supports only `markdown-agents` shape, and `markdown-agents` doesn't meet HIPAA compliance per stop condition 1.
>
> Your remaining options are:
>
> **(i) Foundation-only mode** — I generate planning documents for your project; you implement separately, OR wait for v2 shape support that meets HIPAA compliance natively.
>
> **(ii) Save and exit** — resume when v2 supports your shape, OR after you've completed an operator-side compliance review and revised your regulatory exposure assessment.
>
> Which would you like? (Say "i" or "ii".)

**Operator picks (i).** → producer-visible outcome `foundation_only`; `terminal_reason: iteration_cap_reached`.

## Expected § 7 Terminal: foundation-only behavior (with cross-slice mutation)

`shape_hypothesis.fallback_mode_offered: not_offered → foundation-only`; `foundation_only_offered_timestamp` set.

**Cross-slice mutation per a prior slice Lesson 2 + per a prior advisor finding active-vs-transitional refinement:**

Per a prior slice advisor an advisor finding disposition (corrected at sub-module § 7 Terminal: foundation-only): `documented_in_foundation` records **active terminal-state conditions only** (those firing at terminal evaluation, not transitional conditions resolved during the loop). Condition 4 fired at iter-1 entry but was resolved when operator identified HIPAA (framework_identification: unknown → no); condition 1 fired post-revision and stayed unresolved through iter-2 cap. Only condition 1 is an active terminal compliance gap.

```yaml
stop_conditions:
  evaluated_at: 05_pre_vision
  fired: [1]                              # active terminal-state conditions only (condition 4 resolved at iter 1)
  halted: false                            # flipped from true (operator-elected foundation-only resolved the halt)
  documented_in_foundation: [1]            # active terminal compliance gap only; a prior slice gate module § 6 emits HIPAA gap (not regulation-without-framework)
  resolved_during_loop: [4]                # audit-trail of conditions that fired during loop but were resolved before terminal
  resolved_via: stop_condition_reevaluate_loop_foundation_only
  halt_message: <preserved verbatim from original condition-4 halt at iteration 0>
```

Verbatim a prior slice § A.5 foundation-only message said:

> Foundation-only mode confirmed. I'll generate the planning documents for your project — vision, approach, technical architecture, and so on — abstracted from the implementation shape. You'll take those docs to Claude Code directly to build the implementation. We won't generate the actual agents, scripts, or run files.

`shape_revision.pending: false` set; history preserved.

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
      pre_iteration_fired_conditions: [4]
      operator_choice: (c) regulatory_exposure_revise
      probes_re_asked: [UP-6-other-sector-specific-identification, UP-6-hipaa-applicable-revise]
      regulatory_exposure_revised:
        - field: hipaa_applicable
          old: no
          new: yes
          reason: framework_identification
        - field: no_compliance_claim_framework_identification
          old: unknown
          new: no
          reason: framework_identification
      post_iteration_shape: markdown-agents
      post_iteration_fired_conditions: [1]
      outcome: next_iteration
      # terminal_reason NOT populated (not a terminal state)
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
      outcome: foundation_only
      terminal_reason: iteration_cap_reached
      terminal_at: <ISO 8601>
regulatory_exposure:
  gdpr_applicable: no
  hipaa_applicable: yes              # revised from no
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: no
  no_compliance_claim_framework_identification: no   # revised from unknown
  probed_at_step: 03_up6
stop_conditions:
  evaluated_at: 05_pre_vision
  fired: [1]                                          # active terminal-state conditions only (per a prior advisor finding)
  halted: false                                       # flipped from true at terminal foundation_only
  documented_in_foundation: [1]                       # active terminal compliance gap only
  resolved_during_loop: [4]                           # condition 4 resolved at iter 1 (framework identified)
  resolved_via: stop_condition_reevaluate_loop_foundation_only
  halt_message: <preserved>
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  fallback_mode_offered: foundation-only
  foundation_only_offered_timestamp: <ISO 8601>
schema_versions:
  schema_major: 0
  schema_minor: 2
```

## Expected downstream behavior

`_foundation_only_mode_gate.md` § 6 reads `stop_conditions.documented_in_foundation: [1]` and emits a compliance-gap section in `technical_architecture.md` at step 15 close listing the active terminal compliance gap (HIPAA on markdown-agents). Condition 4 is NOT emitted as a gap because it was resolved during the loop (operator identified HIPAA → framework_identification: no); the `resolved_during_loop: [4]` field provides audit-trail without misleading the foundation docs into emitting a false "regulated-but-unnamed-framework" gap.

WITHOUT the cross-slice mutation, the compliance-gap section would be empty — operator would lose the regulatory-mismatch documentation. The mutation IS load-bearing per a prior slice Lesson 2; the active-vs-transitional distinction (per a prior advisor finding) ensures the right gap is documented, not a stale one.

## Discrimination value

This is the **common-path for condition-4** in v1 reality — operator identifies a framework (HIPAA most often) that triggers conditions 1/2/3 against markdown-agents → loop converges to foundation-only via iteration cap.

- Demonstrates the condition-4 → condition-1 **transition** per sub-module § 4.4 step "condition-4 path may transition into conditions 1/2/3 firing when operator identifies the framework — that's expected behavior; loop continues from § 6 branch table"
- Demonstrates the **iteration cap exercise** under condition-4 (parallel to a prior slice scrl02's PCI iteration-cap-to-scope-out, but resolving to foundation-only via operator pick rather than scope-out)
- Demonstrates the **cross-slice mutation contract with active-vs-transitional distinction** (per a prior advisor finding): `fired: [1]` + `documented_in_foundation: [1]` (active terminal gap only) + `resolved_during_loop: [4]` (audit-trail of transitional resolution); load-bearing for a prior slice gate module § 6 downstream consumption WITHOUT emitting a false condition-4 gap
- Demonstrates the **(c)→(b) operator path** within the loop (operator picks (c) first, then (b) at re-prompt) — different operator-agency-trajectory than scrl02 which exercised only (b)

Without this fixture, the condition-4 → foundation-only path is unfixtured AND the cross-slice mutation with a multi-condition fired-list is unfixtured.
