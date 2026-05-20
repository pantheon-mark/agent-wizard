---
fixture_id: scrl05-condition-4-identify-sector-framework-to-continue
schema_version: fixture-replay-v1
fixture_class: stop-condition-reevaluate-loop
source_scenario: synthetic-no-direct-ancestor
entry_path: pre_step_05_Step_2a_halt_path
trigger_condition: 4
operator_choice_at_halt: (c) regulatory_exposure_revise
c_sub_case: framework_identification
expected_loop_iterations: 1
expected_regulatory_revision:
  - field: no_compliance_claim_framework_identification
    old: unknown
    new: no
    reason: framework_identification
  - field: other_sector_specific[]
    old: []
    new: [{framework: "State Wildlife Data Reporting Standard (Advisory)", applicable: yes}]
    reason: framework_identification
expected_post_iteration_fired_conditions: []
expected_terminal_outcome: continued
expected_terminal_reason: regulatory_exposure_revised_clears_conditions
expected_fallback_mode_offered: not_offered
notes: |
  Condition-4 halt at pre-step-05 → operator picks (c) → identifies a sector-specific framework that is advisory-only (no enforced compliance controls) → mutation populates `other_sector_specific[]` array + flips `no_compliance_claim_framework_identification: unknown → no` → re-evaluation finds no conditions fire (the identified framework is advisory; does not trigger conditions 1/2/3 against markdown-agents) → continued. Exercises the rare-but-possible happy path of condition-4 framework-identification. Demonstrates `other_sector_specific[]` array-append per UP-6 line 236-241 + the `unknown → no` mutation per sub-module § 4.3.
---

# Fixture scrl05 — Condition-4 identify-sector-framework-to-continue

## Synthetic operator inputs

- **P1-1 (project name):** "Field data tracker"
- **P1-2 (purpose):** "I run a small wildlife conservation nonprofit. I want a Claude-powered helper to organize my field observation notes — sort by location, summarize trends, draft reports. Just me and one other volunteer using it."
- **Step 01 probes (P1-4, P1-5, P1-6, P1-7):**
  - P1-4 (interactive question-answer pattern): no
  - P1-5 (continuous-running): no
  - P1-6 (multi-user): no
  - P1-7 (external systems integration): no
  - → classifier emits `shape: markdown-agents` / `confidence: high`
- **Step 03 UP-6.1 (data-type question):** marks #6 (Other regulated data — government records, education, sector-specific)
- **Step 03 UP-6.2 follow-up for #6:** "I know there's some kind of regulation around state-level wildlife data reporting, but I don't know which framework specifically. It's not HIPAA or GDPR or anything common — just sector-specific reporting standards that vary by state." → wizard stores `no_compliance_claim_framework_identification: unknown`

## Expected classifier emit (at end of step 01)

```yaml
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  detected_at_step: 01
  v1_supported: true
  fallback_mode_offered: not_offered
  operator_signals:
    probe_1_4_interactive: no
    probe_1_5_continuous_running: no
    probe_1_6_multi_user: no
    probe_1_7_external_systems: no
```

## Expected step 03 UP-6 regulatory_exposure state (pre-halt)

```yaml
regulatory_exposure:
  gdpr_applicable: no
  hipaa_applicable: no
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: no
  no_compliance_claim_framework_identification: unknown
  probed_at_step: 03_up6
  probed_timestamp: <ISO 8601>
```

## Expected pre-step-05 re-check Step 2 evaluation

Stop-condition 4 fires: `no_compliance_claim_framework_identification == unknown` AND at least one UP-6.1 data-bucket marker is non-zero (operator marked #6).

`shape_hypothesis.fallback_mode_offered == not_offered` → HALT path.

Wizard says halt message with condition-4-specific phrasing (per `_pre_step_05_recheck.md` Step 2 + sub-module § 4.2 Variant B framing — condition fired without a specific framework name); offers (a) / (b) / (c). **Operator picks (c).**

## Expected loop sub-module behavior (iteration 1, (c) path)

`_stop_condition_reevaluate_loop.md` § 4 entry:

1. **Counter increment.** `shape_revision.iteration: 0 → 1`. `pending: true`.
2. **Honest-characterization disclosure § 4.2 Variant B (verbatim, condition-4 case):**

   > OK, let me re-ask the regulatory questions. The stop condition that fired was "regulated data is involved but the specific compliance framework isn't yet identified." There are two ways to clear this:
   >
   > (i) **Identify the specific framework that applies.** If you can name the framework (e.g., HIPAA / GDPR / PCI-DSS / SOX / COPPA / sector-specific), I can re-evaluate with that framework's actual capability requirements — the loop may converge to foundation-only OR exit OR (rarely) a passing path.
   >
   > (ii) **Revise the regulated-data flag itself.** If on reflection your project doesn't actually involve regulated data (e.g., you initially marked health information but you're producing aggregate de-identified statistics not subject to HIPAA), the stop condition won't fire on re-evaluation.
   >
   > Common reasons operators initially mark a regulated bucket but framework is unknown: (1) "I work with sensitive data but I'm not sure which regulation applies"; (2) "I picked the closest bucket but the actual framework is sector-specific (e.g., FERPA for education, GLBA for finance, COPPA for under-13 users)." Either route — framework identification OR regulated-flag revision — is a valid loop exit.

3. **§ 4.3 framework-identification path (operator's sub-case choice):**
   - Wizard asks: "If you can identify the specific framework that applies to your project's regulated data, tell me which one — HIPAA / GDPR / PCI-DSS / SOX / COPPA / or sector-specific (e.g., FERPA, GLBA, financial-services-specific, healthcare-adjacent). Identifying the framework lets me evaluate against its actual capability requirements."
   - **Operator response:** "OK, I looked it up — there's a state-level wildlife observation data reporting standard, but it's an advisory framework with no specific compliance enforcement requirements. It's not HIPAA, GDPR, or any of the common ones. The closest description is 'State Wildlife Data Reporting Standard (Advisory).'"
4. **Mutation per sub-module § 4.3:**
   - Append to `other_sector_specific[]`:
     ```yaml
     - framework: "State Wildlife Data Reporting Standard (Advisory)"
       applicable: yes
     ```
   - Update `no_compliance_claim_framework_identification: unknown → no` per UP-6 source semantics at `03_user_profile.md` line 264 (`no` means "no unresolved framework-identification gap"; the framework identification clears the condition-4 trigger)
   - Append revision entry to `shape_revision.history[1].regulatory_exposure_revised[]` with `reason: framework_identification` (per sub-module § 4.3 step 4 + S2.3 R3 C-001 / advisor lesson)
5. **Re-evaluate stop conditions (§ 4.4) against updated regulatory state + unchanged `control_matrix_active`:**
   - Condition 1 (HIPAA): `hipaa_applicable == no` → not fired
   - Condition 2 (GDPR): `gdpr_applicable == no` → not fired
   - Condition 3 (PCI-DSS): `pci_dss_applicable == no` → not fired
   - Condition 4: `no_compliance_claim_framework_identification == no` now → not fired
   - The newly-identified sector-specific framework ("State Wildlife Data Reporting Standard (Advisory)") is advisory-only; does NOT enforce audit-trail / encryption / access-control. Markdown-agents `advisory` control posture (per `governance/generated_system_data_defaults.md` § 2.2 + ADR-0015 per-shape control matrix) is structurally compatible with an advisory-only sector framework.
6. **No conditions fire post-revision.** Outcome: `continued`. § 7 Terminal: continued.

## Expected § 7 Terminal: continued behavior

Wizard says (substituting framework name):

> OK, after re-evaluation, the framework you identified (State Wildlife Data Reporting Standard (Advisory)) is an advisory-only sector framework that doesn't require enforced controls. Markdown-agents' advisory compliance posture is compatible with that framework. We can continue with markdown-agents generation. Vision phase next.

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
      probes_re_asked: [UP-6-other-sector-specific-identification]
      regulatory_exposure_revised:
        - field: no_compliance_claim_framework_identification
          old: unknown
          new: no
          reason: framework_identification
        - field: other_sector_specific[]
          old: []
          new: [{framework: "State Wildlife Data Reporting Standard (Advisory)", applicable: yes}]
          reason: framework_identification
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
  other_sector_specific:
    - framework: "State Wildlife Data Reporting Standard (Advisory)"
      applicable: yes
  no_compliance_claim: no
  no_compliance_claim_framework_identification: no   # revised from unknown
  probed_at_step: 03_up6
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  fallback_mode_offered: not_offered   # unchanged; operator did NOT go to foundation-only or scope-out
schema_versions:
  schema_major: 0
  schema_minor: 2
```

## Expected downstream behavior

Wizard proceeds to pre_step_05 Step 3 (re-check trigger evaluation), then to step 05 vision generation. Full wizard flow continues normally (NOT foundation-only mode). Foundation-only-mode entry guards at steps 05-15 take the `produce_system_implementation == true` branch per `_foundation_only_mode_gate.md` Section 2 derivation rule (label is `not_offered`).

## Discrimination value

This is the **rare-but-possible happy path for condition-4** — operator identifies a sector-specific framework that is advisory-only and therefore doesn't trigger conditions 1/2/3 against markdown-agents.

- Demonstrates the `unknown → no` mutation per sub-module § 4.3 step 4
- Demonstrates the `other_sector_specific[]` array-append per UP-6 line 236-241 pattern
- Demonstrates the `reason: framework_identification` revision-entry per sub-module § 4.3
- Distinct from scrl03 (named-framework GDPR-revise → `gdpr_applicable: yes → no`) by exercising the sector-specific-identification + array-append code path

Without this fixture, the condition-4 framework-identification → continued branch (the operationally happy path of (c) under condition-4) is unfixtured.

## Coverage note

This is one of the two (c) framework-identification sub-paths in v1 reality. The dominant sub-path (operator identifies HIPAA / GDPR / PCI-DSS-class framework → triggers conditions 1/2/3 → foundation_only at iteration cap) is covered by scrl06. The framework-revision regulated-flag-revision sub-path (operator realizes no regulated data) is covered by scrl07.
