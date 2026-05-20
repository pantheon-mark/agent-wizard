---
fixture_id: scrl08-multi-framework-up6-reask-hipaa-and-gdpr-revise
schema_version: fixture-replay-v1
fixture_class: stop-condition-reevaluate-loop
source_scenario: synthetic-no-direct-ancestor
entry_path: pre_step_05_Step_2a_halt_path
trigger_conditions: [1, 2]                    # both HIPAA + GDPR fire their respective conditions (S2.4 R2 C-006 — honest fired-list representation)
primary_trigger_condition: 1                  # HIPAA fired first per condition-evaluation order; § 4.2 Variant A disclosure focuses on HIPAA per primary
co_fired_conditions: [2]                       # GDPR-fires-condition-2 captured explicitly
operator_choice_at_halt: (c) regulatory_exposure_revise
c_sub_case: multi_field_per_framework_revise
expected_loop_iterations: 1
expected_regulatory_revision:
  - field: hipaa_applicable
    old: yes
    new: no
    reason: operator_clarification
  - field: gdpr_applicable
    old: yes
    new: no
    reason: operator_clarification
expected_post_iteration_fired_conditions: []
expected_terminal_outcome: continued
expected_terminal_reason: regulatory_exposure_revised_clears_conditions
expected_fallback_mode_offered: not_offered
notes: |
  Condition-1 halt at pre-step-05 (HIPAA + markdown-agents) with HIPAA + GDPR both active in regulatory_exposure → operator picks (c) → § 4.3 multi-field UP-6 re-ask iterates per-framework → operator revises BOTH `hipaa_applicable: yes → no` (not actually a business associate in the data flow) AND `gdpr_applicable: yes → no` (clients exited EU operations last year; thought they were still applicable) → condition 1 + condition 2 BOTH clear post-revision → continued. NOT a condition-4 case; this is the "+ UP-6 re-ask testing" half of S2.4 binding. Exercises § 4.3 step 1-3 per-framework loop with 2+ compliance-class frameworks active. Both frameworks are compliance-class (no ADR-0015 honesty gap per S2.4 R1 C-002 disposition — previously used FERPA which was insufficient-control sector-specific; restructured at R1).
---

# Fixture scrl08 — Multi-framework UP-6 re-ask (HIPAA + GDPR both revised)

## Synthetic operator inputs

- **P1-1 (project name):** "International consulting note assistant"
- **P1-2 (purpose):** "I run a solo international consulting practice — pharmaceutical regulatory consulting. I want a Claude-powered helper to organize my client engagement notes — meeting summaries, advice given, client questions. I work with both US healthcare clients and some EU pharma firms. Just me using it on my laptop."
- **Step 01 probes:**
  - P1-4 interactive: no
  - P1-5 continuous-running: no
  - P1-6 multi-user: no
  - P1-7 external systems: no
  - → classifier emits `shape: markdown-agents` / `confidence: high`
- **Step 03 UP-6.1:** marks #1 (Health information about identifiable people) + #2 (Personal data of people in EU/EEA)
- **Step 03 UP-6.2 follow-up for #1:** "I consult with healthcare clients about regulatory affairs. They share patient case studies with me for advice. I'm being cautious — I think I might be a business associate handling PHI on their behalf." → wizard stores `hipaa_applicable: yes` (operator's initial cautious answer)
- **Step 03 UP-6.2 follow-up for #2:** "I worked with EU pharma firms last year and have some lingering client records from that work. GDPR applies to those." → wizard stores `gdpr_applicable: yes` (operator's initial answer based on past records)

## Expected step 03 UP-6 regulatory_exposure state (pre-halt)

```yaml
regulatory_exposure:
  gdpr_applicable: yes                # operator's initial answer (legacy EU records)
  hipaa_applicable: yes               # operator's initial cautious answer (business-associate worry)
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: no
  no_compliance_claim_framework_identification: no   # both frameworks identified (HIPAA + GDPR); no unresolved gap
  probed_at_step: 03_up6
```

## Expected pre-step-05 re-check Step 2 evaluation

**Both conditions 1 + 2 fire** (per `_pre_step_05_recheck.md` Step 2 condition-evaluation; S2.4 R2 C-006 honest fired-list representation):

- Condition 1 (HIPAA): `hipaa_applicable == yes` AND `control_matrix_active.audit_trail_crud != enforced` (markdown-agents `advisory`) — FIRES.
- Condition 2 (GDPR): `gdpr_applicable == yes` AND `control_matrix_active.access_control_authn != enforced` — FIRES.

`stop_conditions.fired: [1, 2]` is recorded at pre-iteration. Per sub-module § 4.2 disclosure-variant rule, the **primary trigger condition** (the one named in operator-facing disclosure) is condition 1 per evaluation order — HIPAA is the disclosure-driver. Per sub-module § 4.3 multi-field re-ask, ALL active framework-applicable fields are re-asked, not just the primary-trigger's framework.

Condition 4 does NOT fire: `no_compliance_claim_framework_identification == no` (both frameworks identified at step 03; no unresolved framework-identification gap).

`fallback_mode_offered == not_offered` → HALT. (a)/(b)/(c). **Operator picks (c).**

## Expected loop sub-module behavior (iteration 1, (c) path; multi-field UP-6 re-ask)

1. **Counter increment.** `shape_revision.iteration: 0 → 1`. `pending: true`.
2. **§ 4.2 Variant A disclosure** (HIPAA fired condition 1 first; named framework). Wizard says verbatim (HIPAA-specific examples):

   > OK, let me re-ask the regulatory questions. The stop condition that fired was that HIPAA applies — if your project actually doesn't fall under HIPAA's scope, the stop condition won't fire on re-evaluation. Common reasons operators initially answer "yes" to HIPAA but later revise to "no":
   >
   > — **HIPAA:** "HIPAA only applies if you're a covered entity (health-care provider, plan, or clearinghouse) OR a business associate handling protected health information (PHI) on their behalf. Not just any health-related project."

   **Note: Variant A is used because the firing condition is condition 1 (HIPAA named-framework). The disclosure naturally focuses on HIPAA; GDPR re-ask happens later in § 4.3 step 1-3.**

3. **§ 4.3 step 1-3 multi-field UP-6 re-ask loop** — iterates per framework field with `applicable == yes`:

   **HIPAA re-ask (firing condition's framework, first):**
   - Wizard: "Earlier you said HIPAA applies (yes). Based on the clarification above, do you want to revise that answer?"
   - **Operator response:** "On reflection — I'm a regulatory affairs consultant; I review my clients' regulatory submissions and advise on compliance. The patient case studies they share with me are de-identified or aggregated as case examples — I'm not in the PHI data flow. The clients themselves are covered entities; I'm an outside consultant advising on their processes, not handling PHI on their behalf. Let me revise — `hipaa_applicable: yes → no`."

   **GDPR re-ask (also applicable):**
   - Wizard: "You also said GDPR applies (yes) — that you have legacy EU client records. Do you want to revise that answer? Note GDPR generally still applies to processing of EU personal data even after the client relationship ended, if records persist."
   - **Operator response:** "Actually let me think about this more carefully... My EU client engagement ended in early 2025. Per my data retention policy, I shredded all the client records they shared with me at engagement-close. What I have now is my own advice notes (no client personal data in them — just my technical assessments). So I'm not actually processing EU personal data anymore. Let me revise — `gdpr_applicable: yes → no`."

4. **Record both revisions** in `shape_revision.history[1].regulatory_exposure_revised[]`:
   ```yaml
   regulatory_exposure_revised:
     - field: hipaa_applicable
       old: yes
       new: no
       reason: operator_clarification
     - field: gdpr_applicable
       old: yes
       new: no
       reason: operator_clarification
   ```

5. **§ 4.4 re-evaluate stop conditions:**
   - Condition 1 (HIPAA): `hipaa_applicable == no` (revised) → not fired
   - Condition 2 (GDPR): `gdpr_applicable == no` (revised) → not fired
   - Condition 3 (PCI-DSS): not fired
   - Condition 4: `no_compliance_claim_framework_identification == no` → not fired

6. **No conditions fire post-revision.** Outcome: `continued`. § 7 Terminal: continued.

## Expected § 7 Terminal: continued behavior

Wizard says:

> OK, after re-evaluation, neither HIPAA nor GDPR applies (you're an outside consultant not in the PHI data flow; and you've shredded all EU client personal data records per your retention policy). We can continue with markdown-agents generation. Vision phase next.

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
      pre_iteration_fired_conditions: [1, 2]                       # both HIPAA + GDPR fire per honest fired-list representation (S2.4 R2 C-006)
      primary_trigger_condition: 1                                  # disclosure-variant driver
      operator_choice: (c) regulatory_exposure_revise
      probes_re_asked: [UP-6-hipaa-applicable, UP-6-gdpr-applicable]
      regulatory_exposure_revised:
        - field: hipaa_applicable
          old: yes
          new: no
          reason: operator_clarification
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
  gdpr_applicable: no                   # revised from yes
  hipaa_applicable: no                  # revised from yes
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

Wizard proceeds to pre_step_05 Step 3 (re-check trigger evaluation), then to step 05 vision generation. Full wizard flow continues normally.

## Discrimination value

This fixture demonstrates the **multi-field UP-6 re-ask flow** per sub-module § 4.3 step 1-3 — operator with multiple compliance-class frameworks active at UP-6.1 enters (c) path; wizard iterates per-framework; revisions tracked per-field in `regulatory_exposure_revised[]`.

- Demonstrates § 4.3 step 1-3 per-framework loop (not just single-framework re-ask)
- Demonstrates `regulatory_exposure_revised[]` array correctly records per-field revisions for multiple frameworks revised in one (c) iteration
- Demonstrates Variant A disclosure (named-framework HIPAA fired) — the firing condition determines disclosure variant; subsequent frameworks re-asked at § 4.3 step 1-3 don't trigger separate disclosures
- Both frameworks (HIPAA + GDPR) are **compliance-class** with enforcement requirements; revising both clears conditions; no ADR-0015 honest-characterization gap

## Restructuring history

**S2.4 R1 C-002 disposition (2026-05-19):** original scrl08 design used HIPAA + FERPA (FERPA in `other_sector_specific[]` active). Advisor flagged: FERPA is a compliance-class sector framework with enforceable disclosure restrictions; markdown-agents has only advisory-class controls; "FERPA-applicable + markdown-agents continued" violates ADR-0015 § 2.3 honest-characterization rule (compliance-class workloads on advisory-only controls must surface as stop condition, not as terminal-continued-with-disclaimer). Restructured scrl08 to use HIPAA + GDPR (both compliance-class with named-framework fields; both revisable via (c) path). The multi-framework re-ask coverage value is preserved; the ADR-0015 gap is closed.

**S2.4 R1 known coverage limit retained (about IDQ-056):** active FERPA / GLBA / similar compliance-class sector frameworks NOT exercised on a continuing path because v0 has no 5th stop condition for sector-specific compliance frameworks (IDQ-056). Demonstrating such a path would violate ADR-0015 § 2.3. The coverage limit is forward-looking — "this surface design is unresolved" — not "this surface is demonstrated working."
