---
fixture_id: scrl10-pre-step-08-late-condition-4-to-foundation-only
schema_version: fixture-replay-v1
fixture_class: stop-condition-reevaluate-loop
source_scenario: synthetic-no-direct-ancestor — markdown-agents shape; no regulated exposure at step 03; an advisor identified at step 07 hints regulated data with framework unidentified, surfacing condition 4 at the pre-step-08 late-emergence re-check
entry_path: pre_step_08_Step_2_late_emergence_halt_path
trigger_condition: 4
operator_choice_at_halt: (c) regulatory_exposure_revise
c_sub_case: framework_identification
expected_loop_iterations: 2
expected_regulatory_revision:
  - field: no_compliance_claim
    old: yes
    new: no
    reason: late_emergence_advisor_hint
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
expected_foundation_state_preserved: [vision.md, approach.md, advisors.md]
expected_cross_slice_mutation:
  stop_conditions.fired: [1]                              # active terminal-state conditions only (condition 4 resolved at iter 1)
  stop_conditions.documented_in_foundation: [1]           # active terminal compliance gap only
  stop_conditions.resolved_during_loop: [4]               # transitional condition-4 resolved during loop (audit-trail)
  stop_conditions.halted: false                           # flipped from true at terminal foundation_only
  stop_conditions.resolved_via: stop_condition_reevaluate_loop_foundation_only
notes: |
  The pre-step-08 × condition-4 cell of the fixture matrix (a prior fixture covers pre-step-08 × condition-1
  named-framework; another covers pre-step-05 × condition-4). Operator surfaces NO regulated data at step 03
  (no_compliance_claim defaults yes). At step 07 they add a "compliance/audit advisor" to the knowledge base.
  The pre-step-08 late-emergence re-check (Step 2) scans vision + approach + advisor content and surfaces the
  advisor-hinted regulatory exposure WITHOUT a pre-identified framework → mutation no_compliance_claim: yes → no
  (operator confirms regulated data IS involved) + framework still unknown → condition 4 fires at pre-step-08.
  Operator picks (c) → on reflection identifies HIPAA → mutation hipaa_applicable: no → yes +
  no_compliance_claim_framework_identification: unknown → no → condition 1 fires post-revision (markdown-agents
  is advisory for HIPAA-required audit-trail / encryption / access-control) → loop next_iteration → operator
  picks (b) at re-prompt → iter 2 probes 5-7 re-asked → markdown-agents re-emitted (same answers) → iter 2 == cap
  → forced terminal foundation-only (operator picks i). Cross-slice mutation per the active-vs-transitional
  distinction (an advisor finding): records active terminal condition [1] in documented_in_foundation and the
  transitional condition [4] in resolved_during_loop audit-trail. Distinct from the pre-step-05 condition-4
  fixture by ENTRY POINT (pre-step-08 late-emergence via advisor hint, with vision + approach + advisors all on
  disk and preserved through the loop) and by late-emergence SOURCE (advisors, not vision content). Fresh
  iteration counter at pre-step-08 per the counter-reset rule (a prior slice).
---

# Fixture scrl10 — Pre-step-08 late-emergence condition-4 (advisor-hinted) → (c) identify-HIPAA → foundation-only

## Synthetic operator inputs

- **P1-1 (project name):** "Caseload note assistant"
- **P1-2 (purpose):** "A helper that organizes and cross-references my working notes about the people on my caseload — flags follow-ups, summarizes patterns over time. Just me, on my laptop." (Note: framed generically; operator does NOT connect this to regulated health/social-services data at step 03.)
- **Step 01 probes:**
  - P1-4 interactive: no
  - P1-5 continuous-running: no
  - P1-6 multi-user: no
  - P1-7 external systems: no
  - → classifier emits `shape: markdown-agents` / `confidence: high`
- **Step 02 (not fired):** HIGH confidence at step 01.
- **Step 03 UP-6.1:** operator marks **none** of the regulated-data buckets (reads "general business data" framing; doesn't connect caseload notes to any regulated category).
- **Step 03 UP-6 result:** all `*_applicable` fields → `no`; `no_compliance_claim: yes` (operator claimed no regulated data); `no_compliance_claim_framework_identification: unknown` (not yet probed — no buckets marked).

## Expected classifier emit (at end of step 01)

```yaml
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  detected_at_step: 01
  v1_supported: true
  fallback_mode_offered: not_offered
```

## Expected pre-step-05 re-check

No stop conditions fire (no regulated buckets declared at step 03; `no_compliance_claim: yes`). Re-check confirms `markdown-agents`; proceeds to step 05 vision generation. `vision.md` written to disk per step 05.

## Step 05–07 content (where the late signal accumulates)

- **Step 05 (vision):** describes "longitudinal notes on each person I support," "follow-up tracking per individual," "pattern summaries across sessions." Phrased about the operator's own practice; no explicit regulatory language.
- **Step 06 (approach):** written without regulatory flags surfaced.
- **Step 07 (advisors):** operator adds a **"compliance / records-retention advisor"** to the knowledge base — "someone who knows the rules about how long I have to keep case records and who can see them." **THIS is the late-emergence signal:** the advisor identification implies regulated data is involved, but no specific framework was ever named (per the pre-step-08 Step 2 example: "Advisors list includes compliance officer / DPO / audit advisor → regulatory exposure hinted but framework not pre-identified").

## Expected pre-step-08 re-check Step 2 (late-emergence — RARE emergent-architecture case)

Per the pre-step-08 re-check Step 2: scan vision + approach + advisor content for newly-surfaced regulatory exposure NOT captured at step 03 UP-6.

The advisor knowledge base entry ("compliance / records-retention advisor") matches the Step 2 advisor-hint example → the framework is NOT pre-identified, so this is a **regulated-but-unnamed-framework** signal (condition-4 shape), not a named-framework signal (condition-1 shape).

Wizard surfaces it with the late-emergence friction-acknowledgment (Step 2 verbatim pattern):

> Looking at what we've built so far — and especially the advisors you set up — I see you added a compliance / records-retention advisor. That suggests this system handles regulated data (records about identifiable people, with retention and access rules), which I didn't pick up on at step 03. Before we generate the architecture, we need to handle this.
>
> Note: your vision and approach documents are already on disk — they're abstracted from implementation shape (they describe what your system does, not how), so they stay valid through any shape revision or regulatory revision. We won't lose them.

**Operator confirms regulated data is involved but cannot name the framework:** "Yes — these are case records about real people, and there are rules about keeping them. But honestly I don't know which specific law applies — HIPAA, some state social-services regulation, something else. I'd have to check."

Mutation at pre-step-08:
- `regulatory_exposure.no_compliance_claim: yes → no` (operator now confirms regulated data IS involved — late-emergence advisor hint)
- `regulatory_exposure.no_compliance_claim_framework_identification: unknown` (unchanged — operator still can't name the framework)

Re-evaluate stop conditions per the pre-step-05 Step 2 logic:

**Condition 4 fires:** `no_compliance_claim == no` AND `no_compliance_claim_framework_identification == unknown`.

(`shape_hypothesis.fallback_mode_offered == not_offered` → HALT path per the condition-4 exception, which DOES halt even in foundation-only mode because foundation docs cannot be written honestly without framework identification.) Three-choice (a)/(b)/(c) offered. **Operator picks (c).**

Append:

```yaml
shape_hypothesis:
  recheck_log:
  - step: 08
    timestamp: <ISO 8601>
    outcome: halted
    stop_condition_fired: 4
    halt_message: <verbatim condition-4 halt>
    late_emergence_source: advisors
```

## Expected loop sub-module behavior — iteration 1 ((c) path; framework-identification → triggers condition 1)

`_stop_condition_reevaluate_loop.md` § 2 entry with `entered_from: pre_step_08`, `late_emergence_source: advisors`, `pre_iteration_fired_conditions: [4]`, `operator_choice: (c) regulatory_exposure_revise`. Per § 3 counter-reset rule: no prior pre_step_05 loop fired; counter starts at 0.

1. **Counter increment.** `shape_revision.iteration: 0 → 1`. `pending: true`.
2. **§ 4.2 Variant B disclosure** (condition-4 case — the framework is unknown, so disclosure cannot cite a specific framework).
3. **§ 4.3 framework-identification path:**
   - Wizard asks the operator to identify the framework (or run an operator-side compliance review).
   - **Operator response:** "Let me think it through — the people on my caseload are receiving health-related services, and I keep treatment-relevant notes that I share back with their care team. I think that makes me a business associate handling protected health information. HIPAA applies. Let me revise."
4. **Mutation per sub-module § 4.3:**
   - Update `hipaa_applicable: no → yes`
   - Update `no_compliance_claim_framework_identification: unknown → no` (framework identified — the condition-4 trigger clears)
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
   - Condition 4: `no_compliance_claim_framework_identification == no` → **no longer fires** (resolved)
6. **Conditions still fire (condition 1).** Iteration 1 < cap 2 → outcome `next_iteration`. Wizard returns to producer; producer re-offers (a)/(b)/(c) at the halt seam.

## Expected re-prompt at halt seam after iteration 1

Wizard says (per the post-loop next_iteration re-prompt pattern):

> After re-evaluation, the framework you identified (HIPAA) is now triggering stop condition 1 against markdown-agents — HIPAA requires enforced audit-trail / encryption / access-control, and markdown-agents at v1 provides those as advisory only.
>
> Same three options again:
> (a) Save and exit
> (b) Change the shape and re-evaluate
> (c) Re-evaluate regulatory exposure further

**Operator picks (b)** — "Let me see if answering the shape questions differently changes anything."

## Expected loop sub-module behavior — iteration 2 ((b) path; probe re-ask → cap reached)

1. **Counter increment.** `shape_revision.iteration: 1 → 2`. `pending: true`.
2. **§ 2.2 honest-characterization disclosure** (verbatim shape-revision case with the HIPAA framework constraint surfaced).
3. **§ 2.3 probe re-ask** for P-5, P-6, P-7 with HIPAA-constraint framing:
   - P-5 (`is_continuous_running`): "Given HIPAA applies, the system would need enforced audit-trail and access-control. Does it need to keep running on its own?" → Operator: "No, still just me opening it on my laptop when I need it."
   - P-6 (`is_multi_user`): "Given HIPAA, multi-user would mean enforced access control with role separation. Multiple users with distinct roles?" → Operator: "No, just me. The care team gets summaries from me; they don't use the tool."
   - P-7 (`requires_external_systems`): "Given HIPAA, integrating with healthcare IT would imply BAA-covered API access. Does it need that?" → Operator: "No, just markdown files locally."
4. **§ 2.4 classifier re-emit:** signals unchanged → `shape: markdown-agents`.
5. **§ 2.5 control_matrix_active** unchanged (shape unchanged).
6. **§ 6 stop-condition re-evaluation:**
   - Condition 1 (HIPAA): still fires (same shape; markdown-agents still `advisory` for HIPAA-required controls)
7. **Iteration 2 == iteration_cap (2).** Internal branch state: `forced_terminal`. Outcome: per § 7 Terminal: forced disclosure.

## Expected § 7 Terminal: forced behavior

Wizard says verbatim (HIPAA substituted):

> We've cycled through 2 iterations of re-evaluation. v1 supports only `markdown-agents` shape, and `markdown-agents` doesn't meet HIPAA compliance per stop condition 1.
>
> Your remaining options are:
>
> **(i) Foundation-only mode** — I generate planning documents for your project; you implement separately, OR wait for v2 shape support that meets HIPAA compliance natively. **Note: vision and approach documents we've already written stay valid and roll forward into the foundation doc set.**
>
> **(ii) Save and exit** — resume when v2 supports your shape, OR after you've completed an operator-side compliance review and revised your regulatory exposure assessment. **Vision and approach documents on disk are preserved.**
>
> Which would you like? (Say "i" or "ii".)

**Operator picks (i).** → producer-visible outcome `foundation_only`; `terminal_reason: iteration_cap_reached`.

## Expected § 7 Terminal: foundation-only behavior (with cross-slice mutation)

`shape_hypothesis.fallback_mode_offered: not_offered → foundation-only`; `foundation_only_offered_timestamp` set.

**Cross-slice mutation per the active-vs-transitional distinction (an advisor finding):** `documented_in_foundation` records **active terminal-state conditions only**. Condition 4 fired at iter-1 entry but was resolved when the operator identified HIPAA (framework_identification: unknown → no); condition 1 fired post-revision and stayed unresolved through the iter-2 cap. Only condition 1 is an active terminal compliance gap; condition 4 goes to the `resolved_during_loop` audit-trail.

```yaml
stop_conditions:
  evaluated_at: 08_pre_architecture          # late-emergence evaluation point
  fired: [1]                                 # active terminal-state conditions only (condition 4 resolved at iter 1)
  halted: false                              # flipped from true (operator-elected foundation-only resolved the halt)
  documented_in_foundation: [1]              # active terminal compliance gap only; gate module § 6 emits HIPAA gap (not regulation-without-framework)
  resolved_during_loop: [4]                  # audit-trail of the transitional condition resolved before terminal
  resolved_via: stop_condition_reevaluate_loop_foundation_only
  halt_message: <preserved verbatim from the original condition-4 halt at pre-step-08>
  late_emergence_source: advisors
```

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
      entered_from: pre_step_08
      late_emergence_source: advisors
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
      entered_from: pre_step_08
      late_emergence_source: advisors
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
  hipaa_applicable: yes              # revised from no via late-emergence (c) framework-identification
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: no            # revised from yes at pre-step-08 late-emergence
  no_compliance_claim_framework_identification: no   # revised from unknown at framework-identification
  probed_at_step: 08_pre_architecture
stop_conditions:
  evaluated_at: 08_pre_architecture
  fired: [1]                                 # active terminal-state conditions only
  halted: false                              # flipped from true at terminal foundation_only
  documented_in_foundation: [1]              # active terminal compliance gap only
  resolved_during_loop: [4]                  # condition 4 resolved at iter 1 (framework identified)
  resolved_via: stop_condition_reevaluate_loop_foundation_only
  halt_message: <preserved>
  late_emergence_source: advisors
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  fallback_mode_offered: foundation-only
  foundation_only_offered_timestamp: <ISO 8601>
schema_versions:
  schema_major: 0
  schema_minor: 2
```

**Disk state:**
- `<project>/vision.md` — preserved unchanged through loop
- `<project>/approach.md` — preserved unchanged through loop
- `<project>/advisors.md` — preserved unchanged through loop (the late-emergence source; preserved like the other foundation state)

## Expected downstream behavior

`_foundation_only_mode_gate.md` § 6 reads `stop_conditions.documented_in_foundation: [1]` and emits a compliance-gap section in `technical_architecture.md` at step 15 close listing the active terminal compliance gap (HIPAA on markdown-agents). Condition 4 is NOT emitted as a gap because it was resolved during the loop (operator identified HIPAA → framework_identification: no); the `resolved_during_loop: [4]` field provides audit-trail without misleading the foundation docs into emitting a false "regulated-but-unnamed-framework" gap.

Step 15 close produces the foundation-doc set per `_foundation_only_mode_gate.md` § 5 (vision.md + approach.md preserved through loop; technical_architecture.md with the HIPAA gap section; execution_plan.md; project_instructions.md; manual.md; next_steps.md).

## Discrimination value

This is the **pre-step-08 × condition-4 cell** of the stop-condition fixture matrix — the case named as a carry-forward but never fixtured. Three behaviors no existing fixture combines:

1. **Condition-4 detection at the pre-step-08 late-emergence re-check (Step 2).** A prior fixture exercises pre-step-08 late-emergence with a NAMED framework (condition 1 directly); another exercises condition-4 at pre-step-05. Neither exercises condition-4 emerging at pre-step-08 — the rare emergent-architecture case where the architecture-boundary scan surfaces a regulated-but-unnamed-framework signal.

2. **Late-emergence SOURCE = advisors** (not vision content). The advisor knowledge base hint ("compliance / records-retention advisor → regulated but framework not pre-identified") is the Step 2 example for an advisor-driven regulatory signal; no existing fixture exercises the advisors source.

3. **`no_compliance_claim` mutation at late-emergence** (`yes → no`). The operator claimed no regulated data at step 03; the late-emergence advisor hint flips that claim, which is what makes condition 4 reachable at pre-step-08. Existing condition-4 fixtures start from a step-03 bucket marking; this one starts from a clean step-03 and flips at pre-step-08.

The cross-slice mutation (active terminal condition [1] in `documented_in_foundation`; transitional condition [4] in `resolved_during_loop`) is identical in contract to the pre-step-05 condition-4 fixture — verifying the active-vs-transitional distinction holds regardless of entry point. The replay validator's condition-4 → foundation_only invariant (transitional resolution requires `resolved_during_loop`) is satisfied: `trigger_condition: 4` + `resolved_during_loop: [4]` + `documented_in_foundation: [1] == active fired [1]`.
