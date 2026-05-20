---
fixture_id: scrl07-condition-4-revise-regulated-flag-to-continue
schema_version: fixture-replay-v1
fixture_class: stop-condition-reevaluate-loop
source_scenario: synthetic-no-direct-ancestor
entry_path: pre_step_05_Step_2a_halt_path
trigger_condition: 4
operator_choice_at_halt: (c) regulatory_exposure_revise
c_sub_case: regulated_flag_revision
expected_loop_iterations: 1
expected_regulatory_revision:
  - field: no_compliance_claim
    old: no
    new: yes
    reason: operator_clarification
  - field: no_compliance_claim_framework_identification
    old: unknown
    new: no
    reason: operator_clarification
expected_post_iteration_fired_conditions: []
expected_terminal_outcome: continued
expected_terminal_reason: regulatory_exposure_revised_clears_conditions
expected_fallback_mode_offered: not_offered
notes: |
  Condition-4 halt at pre-step-05 → operator picks (c) → realizes initial UP-6.1 markers were over-cautious → revises `no_compliance_claim: no → yes` (no actual regulated data) + `no_compliance_claim_framework_identification: unknown → no` → conditions clear → continued. Exercises the regulated-flag-revision sub-case of (c) under condition-4. Uses `reason: operator_clarification` (NOT `framework_identification`) per sub-module § 4.3 distinction. Mirrors scrl03 GDPR-revise pattern's reason value but applied to condition-4 regulated-flag-revision rather than named-framework-applicability-revise.
---

# Fixture scrl07 — Condition-4 revise-regulated-flag-to-continue

## Synthetic operator inputs

- **P1-1 (project name):** "Customer feedback summarizer"
- **P1-2 (purpose):** "I run a small consulting business doing B2B advisory work. I want a Claude-powered helper to summarize customer feedback notes my team writes after client calls. The notes have the customer's company name + my contact's name + key issues raised + my advice. Just me and 2 staff using it."
- **Step 01 probes:**
  - P1-4 interactive: no
  - P1-5 continuous-running: no
  - P1-6 multi-user: yes (3 staff)
  - P1-7 external systems: no
  - → classifier emits `shape: markdown-agents` / `confidence: medium` (multi-user with non-shared markdown still classifies as markdown-agents at v0; small-team threshold)
- **Step 03 UP-6.1:** marks #2 (Personal data of people in EU/EEA) + #6 (Other regulated data — sector-specific)
- **Step 03 UP-6.2 follow-up for #2:** "Actually we're US-only B2B; no EU customers — I marked #2 because I wasn't sure if business-contact information counts as personal data." → wizard stores `gdpr_applicable: no` (per UP-6.2 controller/processor rule — no EU customers; over-caution corrected)
- **Step 03 UP-6.2 follow-up for #6:** "I'm not sure which framework applies to B2B consulting feedback notes — there's general business confidentiality concerns but I don't know if any specific regulation applies." → wizard stores `no_compliance_claim_framework_identification: unknown` (this triggers condition-4 at pre-step-05)

## Expected step 03 UP-6 regulatory_exposure state (pre-halt)

```yaml
regulatory_exposure:
  gdpr_applicable: no                  # corrected at UP-6.2; no EU customers
  hipaa_applicable: no
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: no              # operator marked #2 + #6 at UP-6.1 (even though #2 then resolved to no)
  no_compliance_claim_framework_identification: unknown
  probed_at_step: 03_up6
```

## Expected pre-step-05 re-check Step 2 evaluation

Stop-condition 4 fires: `no_compliance_claim_framework_identification == unknown` AND data-bucket markers active at UP-6.1.

(Note: even though `gdpr_applicable: no` after UP-6.2 correction, the **UP-6.1 marker** for #2 was active — the regulated-data signal exists at UP-6.1 level. Condition 4 evaluates at the UP-6.1 + framework-identification layer, not just framework-applicable fields. Per `_pre_step_05_recheck.md` Step 2 logic: condition 4 = "any UP-6.1 data bucket marked AND no specific framework identified.")

`fallback_mode_offered == not_offered` → HALT. (a)/(b)/(c). **Operator picks (c).**

## Expected loop sub-module behavior (iteration 1, (c) path; regulated-flag-revision sub-case)

1. **Counter increment.** `shape_revision.iteration: 0 → 1`. `pending: true`.
2. **§ 4.2 Variant B disclosure** (verbatim; condition-4 case).
3. **§ 4.3 regulated-flag-revision path (operator's sub-case choice):**
   - Wizard offers both sub-paths: "(i) identify framework / (ii) revise regulated-data flag."
   - **Operator response (chooses ii):** "Wait, let me think about this — my customer feedback notes are about *business* issues, not personal data. The contact names are business contacts using company emails, used for normal B2B communication. The 'issues raised' are things like 'company X wants to expand to Region Y; competitor Z is undercutting price.' Nothing regulated — no health, no payment data, no EU customers, no children's data, no financial reporting. I was being over-cautious when I marked the UP-6.1 buckets. Let me revise — none of UP-6.1 actually applies."
4. **Mutation per sub-module § 4.3 step 3 (UP-6 per-field revision flow; `reason: operator_clarification`):**
   - Update `no_compliance_claim: no → yes` (operator confirmed no regulated data after reflection)
   - Update `no_compliance_claim_framework_identification: unknown → no` (no regulated data → no framework-identification gap)
   - All framework-applicable fields already `no`; stay `no`
   - Append revision entries to `shape_revision.history[1].regulatory_exposure_revised[]`:
     ```yaml
     regulatory_exposure_revised:
       - field: no_compliance_claim
         old: no
         new: yes
         reason: operator_clarification
       - field: no_compliance_claim_framework_identification
         old: unknown
         new: no
         reason: operator_clarification
     ```

   **Note on `reason: operator_clarification`** — this is the regulated-flag-revision sub-case (operator clarifies UP-6.1 markers were over-cautious; no framework being identified). Distinct from `reason: framework_identification` (which fires in scrl05 + scrl06 where operator NAMES a framework).
5. **Re-evaluate stop conditions (§ 4.4):**
   - Condition 1 (HIPAA): `hipaa_applicable == no` → not fired
   - Condition 2 (GDPR): `gdpr_applicable == no` → not fired
   - Condition 3 (PCI-DSS): `pci_dss_applicable == no` → not fired
   - Condition 4: `no_compliance_claim == yes` AND `no_compliance_claim_framework_identification == no` → not fired
6. **No conditions fire.** Outcome: `continued`. § 7 Terminal: continued.

## Expected § 7 Terminal: continued behavior

Wizard says:

> OK, after re-evaluation, you've confirmed your project doesn't actually involve regulated data — business contact information used for B2B communication doesn't fall under the regulated-data buckets at UP-6.1. We can continue with markdown-agents generation. Vision phase next.

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
      pre_iteration_fired_conditions: [4]
      operator_choice: (c) regulatory_exposure_revise
      probes_re_asked: [UP-6.1-data-bucket-revision]
      regulatory_exposure_revised:
        - field: no_compliance_claim
          old: no
          new: yes
          reason: operator_clarification
        - field: no_compliance_claim_framework_identification
          old: unknown
          new: no
          reason: operator_clarification
      post_iteration_shape: markdown-agents
      post_iteration_fired_conditions: []
      outcome: continued
      terminal_reason: regulatory_exposure_revised_clears_conditions
      terminal_at: <ISO 8601>
regulatory_exposure:
  gdpr_applicable: no
  hipaa_applicable: no
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: yes             # revised from no
  no_compliance_claim_framework_identification: no   # revised from unknown
  probed_at_step: 03_up6
shape_hypothesis:
  shape: markdown-agents
  fallback_mode_offered: not_offered   # unchanged
schema_versions:
  schema_major: 0
  schema_minor: 2
```

## Expected downstream behavior

Wizard proceeds to pre_step_05 Step 3 (re-check trigger evaluation), then to step 05 vision generation. Full wizard flow continues normally (NOT foundation-only mode).

## Discrimination value

This is the **regulated-flag-revision sub-case of (c) under condition-4** — operator realizes initial UP-6.1 markers were over-cautious; revises `no_compliance_claim: no → yes` rather than identifying a framework.

- Demonstrates the regulated-flag-revision sub-case is distinct from framework-identification sub-case (scrl05 / scrl06) — different `reason` value in revision entry (`operator_clarification` vs `framework_identification`)
- Disambiguates the two reason values that fire under (c) per sub-module § 4.3
- Shows the operationally common path of "operator was being cautious at step 03; (c) gives them a non-coercive surface to back off" — without (c), operator would be forced through (b) loop into foundation-only OR scope-out for a regulatory concern that doesn't actually apply (operator-agency benefit of (c) path)

Distinct from scrl03 (GDPR-revise — same `reason: operator_clarification` but operator revising a specific framework-applicable field `gdpr_applicable: yes → no`, not the umbrella `no_compliance_claim` flag).

## Coverage note on reason-enum

The fixture explicitly demonstrates `reason: operator_clarification` for regulated-flag revision. Sub-module § 4.3 uses two reason values:

- `reason: operator_clarification` — when operator revises a UP-6 field answer (per scrl03 + scrl07 pattern)
- `reason: framework_identification` — when operator names a framework that was previously unknown (per scrl05 + scrl06 pattern)

Both values are normatively used in v0; fixture coverage confirms both code-paths exercised.
