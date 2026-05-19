# Handoff contract — Shape detection v0

**Produced by:** the wizard's shape-detection module (`wizard/shape_detection.md`) across steps 01-08
**Consumed by:** downstream Stage 2 rebuild slices — interview-steps scaffolding / agent-prompt-build / validation-drift / `test_cases.md` replacement
**Schema:** see explicit version fields under § 2.1 (per advisor R1 C-006 disposition; single schema_version replaced with per-sub-surface versioning)
**Authority:** This file is canonical for the handoff structure downstream slices may rely on.
**Cross-references:** ADR-0018 / PRD v1 § 5.2 F-1 / `wizard/shape_detection.md`

---

## 1. Purpose

When the wizard's shape-detection module advances through its lifecycle phases (provisional emit at step 01 or step 02; regulatory exposure populated at step 03 UP-6; full evaluation at pre-step-05; final confirmation at pre-step-08), it produces the structure below. Downstream rebuild slices that branch behavior on shape (per-shape control matrix; agent-prompt selection; etc.) read this structure from the staging file as their entry condition.

## 2. Lifecycle phases (per advisor R1 C-004 disposition)

The handoff is **emitted progressively** across the interview, NOT in a single shot. Consumers must check the `handoff_phase` field to know which top-level keys are populated. v0 defines four phases; consumers consuming at a given phase may rely on all fields required at that phase.

### 2.1 Schema version fields (per advisor R1 C-006 disposition)

Versioning was previously a single `schema_version` field; this caused internal inconsistency (e.g., a 5th stop condition "bumps schema to v1" contradicted the closed-taxonomy-extension rule that says additions need major bumps). Replaced with explicit per-sub-surface versioning. ALL handoff phases include:

```yaml
schema_versions:
  schema_major: 0
  schema_minor: 1                 # bumped 0 → 1 at S2.3 2026-05-19 (additive: optional `shape_revision` block per § 9 added)
  shape_taxonomy_version: 0       # closed taxonomy; extension = major bump
  stop_condition_set_version: 0   # closed taxonomy; extension = major bump
  control_matrix_schema_version: 0  # closed status-value taxonomy per D1 § 2.1
```

**Consumer contract on versions:**

- Consumers MUST check `schema_major` first. If `schema_major != <consumer's expected major>`, abort with operator-facing message — major bump means breaking changes.
- Consumers MAY increment `schema_minor` tolerance — minor adds optional fields backward-compatibly.
- Consumers checking shape behavior MUST also check `shape_taxonomy_version` — if extended, the shape enumeration includes additions and consumer's per-shape branching is incomplete.
- Consumers checking stop conditions MUST check `stop_condition_set_version` similarly.
- Consumers reading control matrix status values MUST check `control_matrix_schema_version` — status value enumeration changes (e.g., adding a 7th status) require major bump on this field.

### 2.2 Phase definitions

| Phase value | Trigger | Required top-level keys | Optional top-level keys |
|---|---|---|---|
| `provisional_shape_emit` | Classifier emit at end of step 01 (P1-8) OR end of step 02 (P02-FB-5) | `schema_versions`, `handoff_phase`, `shape_hypothesis` (without `recheck_log`) | `shape_hypothesis.forward_offered_signals_at_step_01` |
| `regulatory_exposure_populated` | After step 03 UP-6 (regulatory probe) completes | All above + `regulatory_exposure` | n/a |
| `pre_step_05_evaluated` | After pre-step-05 re-check completes (success path: confirmed / revised / documented_in_foundation) | All above + `stop_conditions` + `control_matrix_active` + `foundation_state` + `shape_hypothesis.recheck_log` containing entry with `step: 05` | `stop_conditions.documented_in_foundation` (populated when DOCUMENT path fires); `shape_revision` (populated only if operator entered the loop per § 9) |
| `pre_step_08_evaluated` | After pre-step-08 re-check completes | All above + `shape_hypothesis.recheck_log` containing entry with `step: 08` | `shape_revision` (populated only if operator entered the loop per § 9) |

### 2.3 Phase-specific guarantees

- **At `provisional_shape_emit`:** the handoff is SHAPE-CLASSIFICATION-ONLY. Downstream consumers reading at this phase get shape + confidence + operator-signals only; regulatory exposure + stop conditions + control matrix are NOT yet populated. Consumers needing those fields MUST defer to a later phase.
- **At `regulatory_exposure_populated`:** consumers may begin regulatory-exposure-dependent branching but MUST NOT branch on stop-condition outcomes (not yet evaluated).
- **At `pre_step_05_evaluated`:** the handoff is FULL. All downstream rebuild slice consumers may consume at this phase.
- **At `pre_step_08_evaluated`:** the handoff is FINAL. Final shape revision (if any) has occurred; no further changes expected until next operator session.

### 2.4 Halt + scope-out paths

Two terminal states do NOT advance to `pre_step_05_evaluated` or later:

- **Scope-out at step 01/02 unsupported-shape transition:** handoff stays at `provisional_shape_emit` with `shape_hypothesis.fallback_mode_offered: scope-out`. Wizard exited; staging file preserved; no downstream consumer should expect later phases for this session.
- **Halt at pre-step-05 (HALT path):** handoff has `handoff_phase: pre_step_05_evaluated` with `stop_conditions.halted: true`. Downstream consumers reading this state MUST treat it as a terminal failure — the wizard did NOT proceed to vision generation; foundation state preserved for resume.

## 3. Full schema (all fields across all phases)

```yaml
# shape_detection_handoff_v0
schema_versions:
  schema_major: 0
  schema_minor: 1                 # bumped 0 → 1 at S2.3 2026-05-19 (additive: optional `shape_revision` block per § 9)
  shape_taxonomy_version: 0
  stop_condition_set_version: 0
  control_matrix_schema_version: 0

handoff_phase: provisional_shape_emit | regulatory_exposure_populated | pre_step_05_evaluated | pre_step_08_evaluated

shape_hypothesis:
  shape: markdown-agents | python-service-operator-facing | claude-skills | node-ui | multi-user-datastore | hosted-cloud | mixed | unknown
  confidence: high | medium | low
  detected_at_step: 01 | 02
  v1_supported: true | false   # markdown-agents only = true at v1 ship region per PRD § 4.1
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: true | false
  operator_signals:
    probe_1_continuous_runtime: yes | no | unsure
    probe_2_multi_user: yes | no | unsure
    probe_3_thinking_partner: yes | no | unsure
    probe_4_external_software: yes | no | unsure
    probe_5_state_memory: yes | no | unsure | not_asked
    probe_6_regular_pattern: yes | no | unsure | not_asked
    probe_7_operator_confirm: yes | no | unsure | not_asked
    probe_8_document_output: yes | no | unsure | not_asked
  forward_offered_signals_at_step_01:
    - "<verbatim phrase from operator's P1-2 core-purpose answer>"
  fallback_mode_offered: complete | foundation-only | scope-out | not_offered
  emit_timestamp: <ISO 8601>
  recheck_log:
    - step: 05 | 08
      timestamp: <ISO 8601>
      outcome: confirmed | revised | halted | documented_in_foundation
      revised_shape: <if outcome == revised>
      revised_confidence: <if outcome == revised>
      stop_condition_fired: <if outcome == halted>
      stop_conditions_recorded: <if outcome == documented_in_foundation; list>

regulatory_exposure:
  gdpr_applicable: yes | no | unknown
  hipaa_applicable: yes | no | unknown
  pci_dss_applicable: yes | no | unknown
  sox_applicable: yes | no | unknown
  coppa_or_gdpr_k_applicable: yes | no | unknown
  other_sector_specific:
    - { framework: <name>, applicable: yes | no | unknown }
  no_compliance_claim: yes | no | unknown
  no_compliance_claim_framework_identification: yes | no | unknown
  probed_at_step: 03_up6
  probed_timestamp: <ISO 8601>

stop_conditions:
  evaluated_at: 05_pre_vision | 08_pre_architecture | none
  fired: [<list of condition numbers from `wizard/shape_detection.md` § 8.3>]
  halted: true | false
  documented_in_foundation: [<list; populated when DOCUMENT path fires; subset of fired>]
  halt_message: <verbatim if halted; with `<actual status>` substituted from control_matrix_active>

control_matrix_active:
  shape: <same as shape_hypothesis.shape>
  encryption_in_transit: <status per D1 § 2.2 column for shape>
  encryption_at_rest: <status>
  access_control_authn: <status>
  audit_trail_crud: <status>
  backup_restore: <status>
  data_handling_sla: <status>
  regulatory_framework_adherence: <status>
  no_secrets_input_boundary: <status>
  no_secrets_repo_boundary: <status>
  audit_log_retention: <status>

foundation_state:
  staging_file_path: ~/claude-wizard-draft/wizard_session_draft.md
  staging_file_preserved: true
  rechecks_completed: [05] | [05, 08] | []
  fallback_mode_offered: <same as shape_hypothesis.fallback_mode_offered>

# Optional block — populated only if operator entered the stop-condition halt → re-evaluate-shape loop
# (picked "(b) Change the shape and re-evaluate" OR "(c) Re-evaluate regulatory exposure" at pre_step_05 Step 2a OR pre_step_08 Step 2 late-emergence)
# Added at S2.3 (schema_minor: 1) per `wizard/interview/_stop_condition_reevaluate_loop.md`
shape_revision:
  pending: false                # boolean — true during active loop iteration; flipped to false at terminal state
  iteration: 0                  # integer — current loop iteration count; 0 before first entry; increments at each (b)/(c) entry
  iteration_cap: 2              # integer — stable at v0 per S2.3 Decision A; means "two loop iterations permitted; on entering a third, force terminal"
  history:                      # append-only array — preserved at terminal per S2.3 Decision I/J
    - iteration: 1
      entered_at: <ISO 8601>
      entered_from: pre_step_05 | pre_step_08
      pre_iteration_shape: <shape value>
      pre_iteration_fired_conditions: [<condition numbers>]
      operator_choice: (b) change_shape | (c) regulatory_exposure_revise
      probes_re_asked: [P-5, P-6, P-7]   # or UP-6 field names for (c)
      classifier_re_emit: <shape value>  # only for (b) path
      regulatory_exposure_revised:       # only for (c) path
        - field: <field name>
          old: <old value>
          new: <new value>
          reason: operator_clarification | framework_identification
      post_iteration_shape: <shape value>
      post_iteration_fired_conditions: [<condition numbers>]
      outcome: continued | foundation_only | scope_out | next_iteration   # producer-visible enum; CLOSED — forced_terminal is internal-only branch state at sub-module § 6 per R1 C-001 disposition; never recorded here
      terminal_reason: passing_shape_re_emit | regulatory_exposure_revised_clears_conditions | unsupported_shape_transition | iteration_cap_reached | operator_chose_save_and_exit   # optional; populated only at terminal entries; disambiguates HOW outcome was reached
      terminal_at: <ISO 8601>            # only if outcome is terminal

# When loop terminal outcome is `foundation_only`, the sub-module ALSO mutates `stop_conditions` block (cross-slice integration with S2.2 gate module § 6):
#   stop_conditions.halted: true → false
#   stop_conditions.documented_in_foundation: [<previously-fired conditions>]
#   stop_conditions.resolved_via: stop_condition_reevaluate_loop_foundation_only
# Required so S2.2 gate module § 6 surfaces compliance-gap entries in technical_architecture.md at step 15 close.
```

## 4. Stability contract

Downstream slices may RELY on the following holding at v0 (all listed under `schema_major: 0`):

- The 4 phases (`provisional_shape_emit` / `regulatory_exposure_populated` / `pre_step_05_evaluated` / `pre_step_08_evaluated`) are CLOSED — phase additions require `schema_major` bump
- All field names within each phase's required keys are stable at `schema_minor: 0` — field renames within a major require `schema_major` bump
- The 8 shape categories AND `unknown` are CLOSED — additions require `shape_taxonomy_version` bump (separate from `schema_major`)
- The 4 stop conditions are CLOSED — additions require `stop_condition_set_version` bump (separate from `schema_major`)
- The 6 control-matrix status values are CLOSED — additions require `control_matrix_schema_version` bump (separate from `schema_major`)
- Mixed-shape handling: `control_matrix_active` reflects weakest-path-across-components per § 8.3 of `wizard/shape_detection.md`. Component-level surface is reserved for v1+.
- HALT vs DOCUMENT path semantics: stable across v0 per `wizard/shape_detection.md` § 8.4 + § 8.5.
- `shape_revision.iteration_cap` value (2 at v0; introduced at `schema_minor: 1`) is stable; revising the cap requires `schema_minor` bump and consumer notification.
- `shape_revision` block being absent from a staging file means operator never entered the loop. Consumers MUST default-handle absent block as `{ pending: false, iteration: 0, iteration_cap: 2, history: [] }` per § 9.

## 5. What is NOT in v0 (reserved for v1+)

These additions will bump the relevant version field. v0 consumers can ignore them safely IF the version field they consume increments only.

- **Generator-version identity field** (per Stage 2 planning F-9 cross-vendor finding): when E-β fires at a future Stage 2 slice, the handoff gains `generator_version` field. Will bump `schema_minor` if added as optional; `schema_major` if made required.
- **Per-component control matrix wiring** (mixed-shape native support): `control_matrix_active.components[<id>]` block addition. Bumps `schema_minor` (additive).
- **Operator-authority-profile fields** (IDQ-050; E-γ-bound): operator-profile block addition. Bumps `schema_minor` (additive).
- **Hash-based drift signals** (D3 / ADR-0017): drift signal block for foundation-bundle update path. Bumps `schema_minor` (additive).
- **5th stop condition** (IDQ-056 — regulated + insufficient operator authority): closed-taxonomy extension. Bumps `stop_condition_set_version` to 1; consumers checking this field will catch the change.
- **9th shape category** or extended shape enumeration: closed-taxonomy extension. Bumps `shape_taxonomy_version`.
- **7th control-matrix status value** (e.g., adding `enforced-conditionally` or `auditable-only`): closed-taxonomy extension. Bumps `control_matrix_schema_version`.
- **`discovery_in_progress` field** (IDQ-055): handoff field for slices interacting with operators still resolving shape. Bumps `schema_minor` (additive).

## 6. Versioning rules

- **Field renamed OR field semantics changed OR phase added/removed OR phase order changed** → bump `schema_major`; consumers MUST adapt
- **Field added as required OR phase's required-keys set extended** → bump `schema_major`; consumers MUST adapt
- **Field added as optional** → bump `schema_minor`; consumers MAY ignore safely
- **Shape enumeration extended (new shape value)** → bump `shape_taxonomy_version`; consumers branching on shape MUST adapt
- **Stop condition added** → bump `stop_condition_set_version`; consumers reading stop_conditions.fired MUST adapt
- **Control matrix status value enumeration extended** → bump `control_matrix_schema_version`; consumers reading control_matrix_active values MUST adapt
- **Description / clarifying text only (no semantic change)** → no version bump

## 7. Consumer contract

Downstream slices that consume this handoff MUST:

- Read `schema_versions` first; abort with operator-facing message if any major version mismatches consumer expectation
- Read `handoff_phase` to know which top-level keys are populated; treat missing keys at earlier phases as expected (not as error)
- Treat all required keys for the relevant phase as present (NOT optional) when reading at that phase
- Treat unfired re-check entries as `recheck_log: []` (empty list; valid pre-step-05 state at `provisional_shape_emit` or `regulatory_exposure_populated` phases)
- Handle `shape: unknown` and `confidence: low` paths gracefully (these are valid v0 emit states; not error states)
- Handle the two terminal failure states (scope-out + HALT) gracefully — they are valid contract states, not consumer-side errors
- NOT mutate the staging file's `shape_hypothesis` fields directly; re-check updates use the append-only `recheck_log:` pattern
- Treat foundation-state-preserved as a hard invariant — never delete the staging file based on this handoff

## 9. `shape_revision` block (added 2026-05-19 per S2.3; schema_minor: 1)

Tracks state of stop-condition halt → re-evaluate-shape loop iterations per `wizard/interview/_stop_condition_reevaluate_loop.md`. Optional top-level block; populated only when operator enters the loop (picks "(b) Change the shape and re-evaluate" OR "(c) Re-evaluate regulatory exposure" at pre_step_05 Step 2a OR pre_step_08 Step 2 late-emergence halt).

Full schema lives in § 3 above (after `foundation_state` block). Loop semantics canonical at `wizard/interview/_stop_condition_reevaluate_loop.md`.

**Consumer rules on `shape_revision`:**

- Consumers reading a staging file WITHOUT `shape_revision` block MUST default to `{ pending: false, iteration: 0, iteration_cap: 2, history: [] }` (operator never entered the loop). Absence is the expected state for most operator sessions.
- Consumers MUST check `schema_versions.schema_minor >= 1` before reading `shape_revision`; at `schema_minor: 0` the block does not exist by contract.
- Consumers MUST NOT mutate `shape_revision.history[]` — only `wizard/interview/_stop_condition_reevaluate_loop.md` is permitted to append iteration entries.
- Consumers MAY read `shape_revision.pending` to detect mid-loop state (e.g., a wizard restart mid-loop should surface this to the operator).
- Consumers MAY read `shape_revision.history[*].outcome` for diagnostic surfaces (e.g., audit reports; future tester-feedback slices).

## 10. Cross-references

- `wizard/shape_detection.md` — the canonical implementation spec; this contract reflects its emit shape
- `wizard/interview/_foundation_only_mode_gate.md` — **consumer for `fallback_mode_offered: foundation-only`** (S2.2 implementation). The gate module's § 2 derivation rule maps the `fallback_mode_offered` enum label in this contract to a derived mode profile (`produce_foundation_docs` / `produce_system_implementation` / `capture_implementation_inputs` / `honest_characterization_disclosure`) that gates per-step behavior in steps 05-15. **No contract-shape change at v0** — derived mode profile is downstream of this contract, derived at use, NOT persisted to staging; no schema bump.
- `wizard/interview/_stop_condition_reevaluate_loop.md` — **producer for `shape_revision` block** (S2.3 implementation; added at `schema_minor: 1`). Loop sub-module appends iteration entries to `shape_revision.history[]` + mutates `shape_revision.pending` / `shape_revision.iteration` during loop execution. Invoked from `_pre_step_05_recheck.md` Step 2a + `_pre_step_08_recheck.md` Step 2 late-emergence.
- `governance/generated_system_data_defaults.md` § 2.2 (control matrix) + § 6.3 (stop conditions) — D1 sources
- PRD v1 § 5.2 (F-1) — requirements source
- ADR-0018 — slice authority
- S2.1 slice spec — design provenance (handoff contract origin)
- S2.2 slice spec — consumer-side implementation (`product_evidence/_slices/S2.2_foundation_only_mode_2026-05-19.md`)
- S2.3 slice spec — `shape_revision` block + loop sub-module (`product_evidence/_slices/S2.3_stop_condition_reevaluate_loop_2026-05-19.md`)
