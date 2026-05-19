---
fixture_id: scrl09-condition-1-hipaa-named-framework-revise-to-continue
fixture_class: stop-condition-reevaluate-loop
source_scenario: scrl03-pattern-parallel-for-hipaa
entry_path: pre_step_05_Step_2a_halt_path
trigger_condition: 1
operator_choice_at_halt: (c) regulatory_exposure_revise
c_sub_case: named_framework_applicability_revise
expected_loop_iterations: 1
expected_regulatory_revision:
  - field: hipaa_applicable
    old: yes
    new: no
    reason: operator_clarification
expected_post_iteration_fired_conditions: []
expected_terminal_outcome: continued
expected_terminal_reason: regulatory_exposure_revised_clears_conditions
expected_fallback_mode_offered: not_offered
notes: |
  HIPAA halt at pre-step-05 (condition 1) → operator picks (c) → UP-6 re-asked with HIPAA-specific covered-entity disclosure → operator clarifies (de-identified aggregate statistics; not handling PHI) → `hipaa_applicable: yes → no` → condition 1 no longer fires → continue. Parallel to scrl03 (GDPR-revise) but for HIPAA. Decision A YES (S2.4 OPEN) included scrl09 as named-framework-revise coverage extension. Single loop iteration (cap not exercised). NOT a condition-4 case.
---

# Fixture scrl09 — Condition-1 HIPAA named-framework revise-to-continue

## Synthetic operator inputs

- **P1-1 (project name):** "Health data analytics scratch pad"
- **P1-2 (purpose):** "I'm a hospital systems analyst. I want a Claude-powered helper to summarize de-identified aggregate statistics from quarterly health-utilization reports — readmission rates, average length-of-stay, etc. by service line. I'm preparing aggregate dashboards for hospital leadership. Just me using it; the aggregate data has no PHI."
- **Step 01 probes:**
  - P1-4 interactive: no
  - P1-5 continuous-running: no
  - P1-6 multi-user: no
  - P1-7 external systems: no
  - → classifier emits `shape: markdown-agents` / `confidence: high`
- **Step 03 UP-6.1:** marks #1 (Health information about identifiable people)
- **Step 03 UP-6.2 follow-up for #1:** "I work with health utilization data at a hospital — I'm hospital staff and the hospital is a covered entity. I'd better say yes to HIPAA to be safe; I work with health data at a covered entity." → wizard stores `hipaa_applicable: yes` (operator's initial cautious answer; note operator over-applied "I work with health data" rather than the precise covered-entity-handling-PHI test)

## Expected step 03 UP-6 regulatory_exposure state (pre-halt)

```yaml
regulatory_exposure:
  gdpr_applicable: no
  hipaa_applicable: yes               # operator's initial cautious answer
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: no
  no_compliance_claim_framework_identification: no
  probed_at_step: 03_up6
```

## Expected pre-step-05 re-check Step 2 evaluation

Stop-condition 1 fires: `hipaa_applicable == yes` AND `control_matrix_active.audit_trail != enforced` (markdown-agents `advisory`).

`fallback_mode_offered == not_offered` → HALT. (a)/(b)/(c). **Operator picks (c).**

## Expected loop sub-module behavior (iteration 1, (c) path; HIPAA named-framework revise)

1. **Counter increment.** `shape_revision.iteration: 0 → 1`. `pending: true`.
2. **§ 4.2 Variant A disclosure** (HIPAA fired — named framework; verbatim per sub-module § 4.2):

   > OK, let me re-ask the regulatory questions. The stop condition that fired was that HIPAA applies — if your project actually doesn't fall under HIPAA's scope, the stop condition won't fire on re-evaluation. Common reasons operators initially answer "yes" to HIPAA but later revise to "no":
   >
   > — **HIPAA:** "HIPAA only applies if you're a covered entity (health-care provider, plan, or clearinghouse) OR a business associate handling protected health information (PHI) on their behalf. Not just any health-related project."

3. **§ 4.3 step 1-3 UP-6 re-ask** for HIPAA field:

   Wizard: "Earlier you said HIPAA applies (yes). Based on the clarification above, do you want to revise that answer?"

   **Operator response:** "OK now I think about it more carefully — my project uses **de-identified aggregate statistics only**. No individual patient records, no PHI flowing through this system. The aggregate dashboards are like 'service line X had Y readmissions out of Z discharges, average LOS was N days' — no identifiable patient data. Under HIPAA, de-identified data isn't PHI, and my system isn't processing PHI on the covered entity's behalf — it's processing aggregate operational metrics. I was being over-cautious. Let me revise — `hipaa_applicable: yes → no`."

4. **Record revision** in `shape_revision.history[1].regulatory_exposure_revised[]`:
   ```yaml
   regulatory_exposure_revised:
     - field: hipaa_applicable
       old: yes
       new: no
       reason: operator_clarification
   ```

5. **Re-evaluate stop conditions (§ 4.4) against updated `regulatory_exposure` + unchanged `control_matrix_active`:**
   - Condition 1 (HIPAA): `hipaa_applicable == no` (revised) → not fired
   - Condition 2 (GDPR): `gdpr_applicable == no` → not fired
   - Condition 3 (PCI-DSS): `pci_dss_applicable == no` → not fired
   - Condition 4: `no_compliance_claim_framework_identification == no` → not fired

6. **No conditions fire post-revision.** Outcome: `continued`. § 7 Terminal: continued.

## Expected § 7 Terminal: continued behavior

Wizard says:

> OK, after re-evaluation, HIPAA no longer applies — de-identified aggregate statistics aren't PHI, and your role as a hospital analyst working with aggregate utilization metrics doesn't put you in the PHI-handling path. We can continue with markdown-agents generation. Vision phase next.

`shape_revision.pending: false` set; history preserved.

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
      pre_iteration_fired_conditions: [1]
      operator_choice: (c) regulatory_exposure_revise
      probes_re_asked: [UP-6-hipaa]
      regulatory_exposure_revised:
        - field: hipaa_applicable
          old: yes
          new: no
          reason: operator_clarification
      post_iteration_shape: markdown-agents
      post_iteration_fired_conditions: []
      outcome: continued
      terminal_reason: regulatory_exposure_revised_clears_conditions
      terminal_at: <ISO 8601>
regulatory_exposure:
  gdpr_applicable: no
  hipaa_applicable: no                # revised from yes
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: no
  no_compliance_claim_framework_identification: no
  probed_at_step: 03_up6
shape_hypothesis:
  shape: markdown-agents
  fallback_mode_offered: not_offered
schema_versions:
  schema_major: 0
  schema_minor: 2
```

## Expected downstream behavior

Wizard proceeds normally to step 05 vision (not foundation-only). Foundation docs include a "Regulatory exposure" section noting HIPAA was initially marked but revised after the loop's disclosure clarified covered-entity-status / PHI-handling scope.

## Discrimination value

This fixture is the **HIPAA parallel of scrl03 (GDPR-revise)** — operator initially over-cautious on HIPAA + (c) path's covered-entity-status disclosure surfaces the precise applicability rule + operator clarifies + revision clears condition.

- Demonstrates that the (c) path's load-bearing-value (operator-agency on (c) when initial UP-6 answer was over-cautious) extends to named-framework HIPAA case, not just GDPR
- Closes S2.3 known coverage limit (partial — HIPAA-revise tested; PCI-revise still assumed; PCI-revise pattern follows same shape per § 4.2 Variant A PCI-DSS-specific examples)
- Same `reason: operator_clarification` value as scrl03 (legitimate UP-6 revision class per S2.1 R1 C-006 framing)

Single loop iteration; cap (2) not exercised; foundation-only / scope-out paths not exercised.

## Coverage limit closed

S2.3 § 10 known coverage limit "HIPAA / PCI-DSS / regulated-no-framework revise cases assumed to follow same pattern" — this fixture closes the HIPAA half. PCI-DSS-revise remains assumed (next coverage extension if surfaced as gap).
