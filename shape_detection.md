# Shape Detection — canonical implementation spec

**Source:** S2.1 slice spec (`product_evidence/_slices/S2.1_shape_detection_handoff_scaffolding_2026-05-19.md` § A) — extracted verbatim at S2.1 implementation per slice § 1 + § A.

**Mechanism ID:** `mech-shape-detection-v0`
**Mechanism class:** AR-004 family A — Skill, pure markdown (advisory or guided)
**Status:** v0 active (S2.1 OPEN 2026-05-19)
**Authority:** This file is canonical for the wizard's shape-detection logic. Interview files (`wizard/interview/*.md`) reference this file as the spec for the probes they fire and the emit they produce.
**Cross-references:** PRD § 4.2 + § 4.3 + § 5.2 F-1 + § 5.13 F-12 / `governance/generated_system_data_defaults.md` § 2.2 + § 6.1 + § 6.3 / `wizard/handoff_contracts/shape_detection_v0.md` / `wizard/CLAUDE.md` § 9 (Forward-offered information capture)

---

## 1. What this does

The wizard's shape-detection logic emits a **provisional shape hypothesis with confidence** at step 01 (target) or step 02 (latest acceptable) of the operator interview. It re-checks the hypothesis before step 05 (vision generation) and before step 08 (architecture generation). It evaluates 4 stop conditions (regulation × shape mismatch) at pre-step-05 and halts the wizard with a foundation-state-preserved message if a stop condition fires. It produces a handoff contract artifact that downstream rebuild slices consume.

Shape categories per PRD § 4 Sub-option E: `markdown-agents` (v1 supported) / `python-service-operator-facing` (deferred) / `claude-skills` (deferred) / `node-ui` (deferred) / `multi-user-datastore` (deferred) / `hosted-cloud` (deferred) / `mixed` (deferred) / `unknown` (classifier output for insufficient signal).

The logic is **behavior-based** per PRD § 4.2 — operators are NOT asked "do you want Python service or markdown agents?" That recreates the technical-knob-mismatch failure (Stage 1 anchor #1; J2 anchored). Probes use plain-English business-side vocabulary; wizard-internal signal classifications are routing hints only, never surfaced to the operator.

## 2. Probe inventory + signal-to-shape mapping

### 2.1 Step 01 — minimum probe set (4 probes; always fires)

These are sub-steps P1-4 through P1-7 of `wizard/interview/01_phase1_capture.md` (after P1-3 staging file creation).

| Probe | Operator-facing text | Signal classification |
|---|---|---|
| **Probe-1 (continuous-runtime)** | "Does the system need to keep running on its own, even when you're not using Claude?" | yes → Python service / Node+UI / hosted-cloud signal; no → markdown-agents friendly |
| **Probe-2 (multi-user)** | "Will other people use this system — and need their own logins or different views?" | yes → Node+UI + multi-user-datastore signal; no → single-user-friendly |
| **Probe-3 (thinking-partner)** | "Is it mainly something you'll work on WITH Claude — like a thinking partner you bring questions to?" | yes → markdown-agents OR Claude-skills signal; no → automated-systems signal |
| **Probe-4 (external-software)** | "Does it need to talk to other software automatically — like getting prices, sending emails, checking accounts?" | yes → Python service signal; no → standalone-friendly |

Operator answers are stored as `yes | no | unsure`. `unsure` is treated as neutral signal (does not contribute strong-positive OR strong-negative).

### 2.2 Step 02 — conditional fallback probes (fire only if step 01 yields MEDIUM or LOW confidence)

Up to 4 additional probes from PRD § 4.2 candidate set. Fire at end of step 02 (after FIN-1 + FIN-2 complete; before step-02 success condition).

| Probe | Operator-facing text | Signal classification |
|---|---|---|
| **Probe-5 (state-memory)** | "Should the system remember things between times you use it?" | yes → datastore signal; no → stateless-friendly |
| **Probe-6 (regular-pattern)** | "Does it need to do something automatically, on a regular pattern — like every day, every Monday morning, every hour?" | yes → service signal (scheduled); no → on-demand-friendly |
| **Probe-7 (operator-confirm)** | "Should the system ask you before doing anything important — like making a booking, sending money, or contacting someone?" | yes → markdown-agents-friendly (human-gate aligns); no → autonomous-action implies stronger guardrails |
| **Probe-8 (document-output)** | "Does it produce a document, packet, or report that you'll review or share?" | yes → markdown-agents OR Claude-skills; no → service-output-friendly |

### 2.3 Signal-to-shape decision table

Cumulative across all fired probes. Strong-positive / strong-negative are tallied per shape.

| Shape | Strong-positive signals | Strong-negative signals |
|---|---|---|
| `markdown-agents` (Claude Code, Mac) | Probe-3 yes / Probe-7 yes / Probe-8 yes / Probe-1 no / Probe-4 no | Probe-1 yes / Probe-2 yes |
| `python-service-operator-facing` (deferred) | Probe-1 yes / Probe-4 yes / Probe-6 yes | Probe-3 yes |
| `claude-skills` (deferred) | Probe-3 yes / Probe-8 yes / Probe-7 yes | Probe-1 yes / Probe-2 yes |
| `node-ui` (deferred) | Probe-2 yes / (Probe-1 yes + Probe-5 yes) | Probe-3 yes |
| `multi-user-datastore` (deferred) | Probe-2 yes / Probe-5 yes | Probe-3 yes |
| `hosted-cloud` (deferred) | Probe-1 yes / Probe-2 yes / Probe-5 yes | Probe-3 yes |
| `mixed` (deferred) | ≥2 shape clusters each have ≥2 strong-positives AND no shape's signals subsume another | n/a |
| `unknown` | Insufficient signal density (no shape has ≥2 strong-positives) | n/a |

## 3. Confidence rubric

Computed after each probe-set fires.

| Confidence | Criteria |
|---|---|
| **HIGH** | (a) Top shape has ≥3 strong-positives AND 0 strong-negatives AND no other shape has ≥2 strong-positives; OR (b) Top shape has 2 strong-positives AND the same probe answers produce ≥2 strong-negatives for the next-closest competing shape (subsumption-by-strong-negatives ruling out alternatives) AND no other shape has ≥2 strong-positives |
| **MEDIUM** | Top shape has 2 strong-positives AND 0-1 strong-negatives AND HIGH branch (b) does not apply (no subsumption). OR HIGH-like signal density but with 1 conflicting strong-negative. |
| **LOW** | Top shape has 1 strong-positive AND signals scattered. OR ≥2 shapes tied with strong-positives. OR insufficient signal density (`mixed` / `unknown` emit). |

**Rubric note (per S2.1 advisor R1 C-005 disposition).** Branch (b) of HIGH captures the "2 strong-positives + clean discrimination via strong-negatives ruling out alternatives" case — e.g., s02 fixture where `python-service-operator-facing` has 2 strong-positives (Probes 1+4) AND the same answers produce strong-negatives for `markdown-agents`/`claude-skills` (Probes 1 yes / 3 no / 4 yes). Without (b), s02 would emit MEDIUM and fire step-02 fallback unnecessarily; with (b), HIGH at step 01 is honest.

**Promotion logic:**

1. Compute confidence after step 01 probes (Probe-1 through Probe-4).
2. If HIGH: emit hypothesis at end of step 01.
3. If MEDIUM or LOW: defer emit; fire step 02 fallback probes (Probe-5 through Probe-8) at end of step 02; recompute confidence.
4. If still LOW after step 02: emit `shape: unknown` with `confidence: low` AND set `forced_recheck_at_step_05: true`. Operator continues; pre-step-05 re-check re-evaluates with accumulated steps 02-04 context.

## 4. Provisional hypothesis emission contract

At classifier emit, write the following structure to `~/claude-wizard-draft/wizard_session_draft.md` under a new `## Shape detection` section (after the `## Captured answers` section). Per advisor R2 C-008 + C-009 dispositions: every finalized emit MUST include `status: emitted` (to disambiguate from deferred-emit placeholder), `schema_versions` block, AND `handoff_phase: provisional_shape_emit` field. These are the consumer-visible markers required by `wizard/handoff_contracts/shape_detection_v0.md`.

```yaml
## Shape detection

schema_versions:
  schema_major: 0
  schema_minor: 1                 # bumped 0 → 1 at S2.3 2026-05-19 (additive: optional `shape_revision` block per handoff contract § 9)
  shape_taxonomy_version: 0
  stop_condition_set_version: 0
  control_matrix_schema_version: 0

handoff_phase: provisional_shape_emit

shape_hypothesis:
  status: emitted   # 'emitted' for finalized; 'pending_step_02_fallback' for deferred at step 01
  shape: markdown-agents | python-service-operator-facing | claude-skills | node-ui | multi-user-datastore | hosted-cloud | mixed | unknown
  confidence: high | medium | low
  detected_at_step: 01 | 02
  v1_supported: true | false   # markdown-agents only = true at v1 ship region per PRD § 4.1
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: true | false   # true when emit was LOW
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
    - "<verbatim phrase from operator's P1-2 core-purpose answer per wizard/CLAUDE.md § 9>"
  mixed_component_basis: []   # ONLY populated when shape == mixed; per advisor R2 C-010 disposition; lists component shapes detected in the operator's input
  fallback_mode_offered: complete | foundation-only | scope-out | not_offered
  emit_timestamp: <ISO 8601>
```

**`status` field semantics (per advisor R2 C-008 disposition):**

- `status: emitted` — classifier has produced a finalized hypothesis at this step; downstream triggers (P1-9, P02-FB-6, pre-step-05 re-check) read this as the entry condition
- `status: pending_step_02_fallback` — classifier deferred emit at step 01 because confidence was MEDIUM or LOW; step 02 fallback will finalize

**`mixed_component_basis` field semantics (per advisor R2 C-010 disposition):**

- ONLY populated when `shape == mixed`
- Lists the component shapes detected in the operator's inputs (e.g., `["markdown-agents", "python-service-operator-facing"]` for a mixed system with markdown thinking-partner component AND python automation component)
- Downstream consumers reading `control_matrix_active` for a mixed shape can audit the basis: the weakest-path-across-components computation in § 8.3 takes its input from this list
- For v0, `mixed_component_basis` is the LLM agent's classification of which constituent shapes are present; precision is limited but the field provides an auditable record. Component-level capability tracking (per-component matrix blocks) is reserved for v1+.

**Lifecycle-phase update rule (per advisor R2 C-009 disposition):**

When downstream interview steps advance the handoff to a later lifecycle phase, they MUST update the `handoff_phase` field. Specifically:

- Step 03 UP-6 completion → `handoff_phase: regulatory_exposure_populated`
- Pre-step-05 re-check success path → `handoff_phase: pre_step_05_evaluated`
- Pre-step-08 re-check success path → `handoff_phase: pre_step_08_evaluated`

Terminal states retain their pre-terminal `handoff_phase` value (scope-out at step 01/02 keeps `provisional_shape_emit`; HALT at pre-step-05 keeps `pre_step_05_evaluated` with `stop_conditions.halted: true`).

**Append-only update rule.** After emit, re-checks at step 05 and step 08 append entries to a `recheck_log:` list rather than mutating prior entries:

```yaml
shape_hypothesis:
  # ... emit fields ...
  recheck_log:
    - step: 05
      timestamp: <ISO 8601>
      outcome: confirmed | revised | halted
      revised_shape: <if outcome == revised>
      revised_confidence: <if outcome == revised>
      stop_condition_fired: <if outcome == halted>
    - step: 08
      timestamp: <ISO 8601>
      outcome: confirmed | revised | halted
      # ... etc
```

## 5. Re-check protocol

### 5.1 Pre-step-05 re-check

Reachable from `wizard/interview/05_vision.md` opening. Implementation lives at `wizard/interview/_pre_step_05_recheck.md`.

Before step 05's first user-facing question, classifier re-reads:

1. The provisional `shape_hypothesis` from staging file
2. All operator answers captured in step 02 (financial) + step 03 (user profile; including regulatory-applicability probe UP-6) + step 04 (notifications)
3. The `regulatory_exposure` field populated at step 03 UP-6

**Re-check triggers** (any single condition fires re-check):

- Step 03 user-profile answer (UP-1 through UP-5) indicates operator role / availability / domain contradicting the initial shape signal (heuristic; e.g., "I need this running 24/7 for our team" contradicts `markdown-agents`)
- Step 04 notifications choices imply runtime shape (e.g., NTFY cron-pattern notifications imply service shape)
- Initial emit confidence was MEDIUM or LOW (always re-check when forced_recheck_at_step_05 = true)
- 4 stop conditions need evaluation (regulatory_exposure now populated)

**Re-check outcome paths:**

| Outcome | Action |
|---|---|
| `confirmed` | Append recheck entry `outcome: confirmed`; proceed to step 05 |
| `revised` (still v1-supported) | Update `shape_hypothesis.shape` + `confidence`; append recheck entry `outcome: revised` + `revised_shape:` + `revised_confidence:`; proceed to step 05 |
| `revised` (no longer v1-supported) | § 6 unsupported-shape transition fires (operator chooses scope-out vs foundation-only) |
| `halted` (stop condition fired) | § 7 halt fires; foundation state preserved; operator offered three paths per S2.3 — (a) save-and-exit / (b) change shape and re-evaluate / (c) re-evaluate regulatory exposure |

### 5.2 Pre-step-08 re-check

Reachable from `wizard/interview/08_architecture.md` opening. Implementation lives at `wizard/interview/_pre_step_08_recheck.md`.

Same structural pattern as pre-step-05 but reads accumulated steps 05 (vision) + 06 (approach) + 07 (advisors). Especially important for emergent-architecture projects (PRD § 5.13; J6 anchored).

Stop conditions are NOT re-evaluated at pre-step-08 (already evaluated at pre-step-05; regulatory exposure does not change between steps 03 and 08 under normal conditions). However, if pre-step-05 was `confirmed` but pre-step-08 reads emerging-architecture content that newly implicates a stop condition (rare; flagged for v1 monitoring), the re-check halts and the wizard surfaces the new evidence to the operator.

## 6. Unsupported-shape transition (foundation state preserved)

**Triggered when (per advisor R1 C-003 disposition; surface at the EARLIEST detection point to comply with PRD § 4.3):**

- Initial detection at step 01 (P1-8) emits a non-markdown shape with HIGH confidence → transition fires NOW at end of step 01; operator chooses scope-out OR foundation-only BEFORE step 02
- OR initial detection at step 02 fallback (P02-FB-5) emits a non-markdown shape with HIGH or MEDIUM confidence → transition fires NOW at end of step 02; operator chooses scope-out OR foundation-only BEFORE step 03
- OR pre-step-05 re-check revises shape to non-markdown → transition fires at pre-step-05 (revision case; previously confirmed markdown but accumulated context contradicts)
- OR pre-step-08 re-check revises shape to non-markdown → transition fires at pre-step-08 (late revision case)

**Step-01-or-02 transition is the canonical PRD § 4.3 surface.** Pre-step-05 and pre-step-08 transitions are revision-case backstops — they fire only when shape revises AFTER step 02 emit.

**Operator-facing text (verbatim per PRD § 4.3):**

> Your project looks like [shape X — Python service / Node+UI / etc.]. v1 of the wizard generates complete systems for markdown-agents-on-Claude-Code only.
>
> Two options:
>
> **(a) Stop here — wait for v2 / future versions.** Your project file is saved. When the wizard adds [shape X] support, we can pick up. For now, here's the roadmap for what triggers that addition: [pointer to PRD § 4.5 deferred shapes + un-defer triggers].
>
> **(b) Foundation-only mode.** I can produce a foundation-doc set for your project — the planning documents abstracted from implementation shape. You'd take those docs to Claude Code directly to build the implementation, OR wait for v2 shape support. We won't generate the system implementation itself.
>
> Which would you like? (Say "a" or "b".)

**Foundation state preservation:**

`~/claude-wizard-draft/wizard_session_draft.md` is unchanged by the transition; all captured answers remain. The `shape_hypothesis.fallback_mode_offered` field updates to `scope-out` (operator picks a) or `foundation-only` (operator picks b). Transition does NOT delete the staging file OR force operator restart.

**Per-path behavior:**

- **(a) scope-out:** wizard appends `scope_out: <timestamp>` marker to staging file under the shape_hypothesis section; says: "Saved. Re-run the wizard later when you're ready or when [shape X] support is added." Exits cleanly.
- **(b) foundation-only:** wizard proceeds with steps 05-15 in foundation-doc-only mode (NO system implementation generated). **Implementation landed at S2.2** — see `wizard/interview/_foundation_only_mode_gate.md` for the capability-field derivation rule + per-step entry-guard pattern + close-ceremony adaptation pointer. Each of `wizard/interview/05_vision.md` through `15_close.md` has a `## Foundation-only adapted path` section at file end implementing the steps-05-15 foundation-only-mode behavior per `_foundation_only_mode_gate.md` § 5 four-file foundation doc set + § 6 DOCUMENT-path gap integration + § 7 close-ceremony adaptation pointer.

Per PRD § 4.3 / advisor R2 F-2.3: foundation-only mode is NOT counted as "system implementation served"; disclosure is explicit at shape-diagnosis moment. NOT silent fallback.

## 7. Per-shape control matrix wiring

The classifier reads `governance/generated_system_data_defaults.md` § 2.2 control matrix at startup. On hypothesis emit, populate `control_matrix_active` for the detected shape:

**For `markdown-agents` (v1 supported):**

```yaml
control_matrix_active:
  shape: markdown-agents
  encryption_in_transit: provider-enforced
  encryption_at_rest: provider-enforced + operator-manual
  access_control_authn: not-applicable
  audit_trail_crud: advisory
  backup_restore: not-applicable
  data_handling_sla: operator-manual
  regulatory_framework_adherence: operator-manual
  no_secrets_input_boundary: operator-manual
  no_secrets_repo_boundary: enforced-after-mandatory-hook-trigger
  audit_log_retention: not-applicable
```

**For all other (deferred) shapes:** every control row populates to `deferred-until-shape` for extension-readiness:

```yaml
control_matrix_active:
  shape: python-service-operator-facing
  encryption_in_transit: deferred-until-shape
  encryption_at_rest: deferred-until-shape
  # ... etc per D1 § 2.2 column
```

**Honest characterization rule wired (D1 § 2.3):** when shape detection emits `markdown-agents`, the wizard's eventual README + foundation-doc output must include a "Controls applied per chosen shape" section listing the matrix status values for operator transparency. Implementation of this output is downstream of S2.1; the contract surface here defines what downstream slices consume.

## 8. 4 stop conditions implementation

### 8.1 Regulatory-applicability probe placement

Per S2.1 decision A: **step 03 (user profile)** as sub-step UP-6, after UP-5 (involvement appetite) and before the synthesis step. Two-step probe pattern per D1 § 6.1, abbreviated for step-03 conversational fit.

The probe is asked with this lead-in:

> Two more questions about the data your system will handle. These help me check whether your project's regulatory exposure is compatible with the system shape we've detected — so I don't generate something that won't work for your actual needs.

For each framework (GDPR / HIPAA / PCI-DSS / SOX / COPPA-or-GDPR-K / other-sector-specific), the wizard asks the two-step pattern from D1 § 6.1: (a) data-type question + (b) operator-role question. Both yes = framework applicable.

To minimize friction with non-technical operators, the wizard asks the framework questions PROPOSITIONALLY in plain language (not as a checklist of acronyms). Example combined prompt:

> Will the system handle any of the following on a regular basis?
>
> 1. **Health information about identifiable people** — patient records, medical histories, insurance claims
> 2. **Personal data of people in the EU/EEA** — names, contact info, behavioral data, etc.
> 3. **Credit card or payment card numbers**
> 4. **Financial reporting data subject to audit** — for publicly-traded companies or their auditors
> 5. **Data from children under 13** (or under 16 in the EU)
> 6. **Other regulated data** — government records, education records, sector-specific (energy, telecoms, etc.)
> 7. **None of the above** — no regulated data

For any "yes" answer, wizard asks the follow-up role question (D1 § 6.1 step (b)) to determine actual applicability. Example for #1: "Are you (or the system) acting as a healthcare provider, insurance plan, clearinghouse, OR a business associate processing health data on their behalf?"

If operator says "regulated" (any yes) but cannot identify which specific framework, store `no_compliance_claim_framework_identification: unknown` — this fires stop condition #4 at pre-step-05 re-check.

If operator says "none of the above," store `no_compliance_claim: yes` and proceed; wizard's eventual foundation-doc set will EXPLICITLY state "this system makes NO compliance claim under GDPR / HIPAA / PCI / SOX / etc." per D1 § 6.2.

### 8.2 regulatory_exposure schema

Stored in staging file under `## Regulatory exposure` section:

```yaml
## Regulatory exposure

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
```

### 8.3 Stop conditions lookup (CAPABILITY-BASED per advisor R1 C-002 disposition)

Evaluated at pre-step-05 re-check (per § 5.1). Conditions are evaluated against shape **capabilities** (the per-shape control matrix `control_matrix_active` block values) rather than shape labels. This handles `mixed` shapes correctly (mixed includes markdown-agents component providing certain controls at advisory-only) and is robust to future shape additions.

**Outcome split per advisor R1 C-003 disposition.** When a stop condition matches:

- If `shape_hypothesis.fallback_mode_offered == not_offered` (operator is on full-system-generation path; shape == markdown-agents): **HALT** per § 8.4
- If `shape_hypothesis.fallback_mode_offered == foundation-only` (operator chose foundation-only-mode at step 01/02 unsupported-shape transition): **DOCUMENT** per § 8.5 — record the matched condition; downstream foundation-only slice inserts honest text into generated foundation docs. Condition 4 is an EXCEPTION (see footnote).

| # | Capability condition | Operator-facing message (HALT or DOCUMENT path applies per above) |
|---|---|---|
| 1 | `regulatory_exposure.hipaa_applicable == yes` AND `control_matrix_active.audit_trail_crud != enforced` (status is `advisory` / `operator-manual` / `provider-enforced` / `not-applicable` / `deferred-until-shape`) | "This system as designed does not meet HIPAA compliance. The chosen shape provides audit trail at `<actual status from control_matrix_active>`; HIPAA requires enforced audit-trail. Either change the shape (Python service is on the roadmap but not in v1), change the regulatory exposure, OR commit to an operator-side compliance review before generating." |
| 2 | `regulatory_exposure.gdpr_applicable == yes` AND `control_matrix_active.access_control_authn != enforced` (proxy for DSR workflow capability; at v0 only enforced access_control supports defensible DSR endpoints) | "This system as designed does not meet GDPR compliance. The chosen shape provides access control at `<actual status>` — it does not have enforceable DSR (Data Subject Request) workflow primitives. GDPR Article 12-23 require enforceable DSR endpoints. Either change the shape OR commit to an operator-side compliance review." |
| 3 | `regulatory_exposure.pci_dss_applicable == yes` AND `control_matrix_active.encryption_at_rest != enforced` | "This system as designed does not meet PCI-DSS compliance. The chosen shape provides encryption-at-rest at `<actual status>`, not `enforced`. PCI-DSS requires deterministic encryption-at-rest. Either change the shape OR commit to an operator-side compliance review." |
| 4 | ANY of (`regulatory_exposure.{hipaa,gdpr,pci_dss,sox,coppa_or_gdpr_k}_applicable == yes`) OR (`regulatory_exposure.other_sector_specific` non-empty with `applicable == yes`) — **AND** `regulatory_exposure.no_compliance_claim_framework_identification == unknown` | "You've indicated this system handles regulated data, but we haven't identified which specific framework (HIPAA / GDPR / PCI / sector-specific). Before generating, please complete an operator-side compliance review to identify the applicable framework; the wizard will halt here." |

**Footnote on condition 4 + foundation-only path:** condition 4 fires HALT even in foundation-only-mode because foundation docs cannot be written honestly without framework identification — "regulated data but unknown which framework" is an operator-side resolution gap, not a documentation gap. Operator must complete compliance review and resume.

**Mixed-shape handling (per advisor R1 C-002 disposition; closes IDQ-057 candidate):** when `shape_hypothesis.shape == mixed`, the `control_matrix_active` block reflects the **union of components' capabilities** — for each control row, the LEAST-restrictive status across constituent components wins. Concretely: if the mixed system has a markdown-agents component (audit trail `advisory`) AND a python-service component (audit trail `enforced`), the matrix records `audit_trail_crud: advisory` because the markdown component's path can carry regulated data with only advisory audit trail. Condition 1 fires on the weakest path. This is the conservative correct behavior — regulated data MUST be handled by the enforced-audit-trail path; if any component fails, the system fails.

For future revisions: when downstream slices implement component-level capability tracking, the matrix evolves to per-component blocks (`control_matrix_active.components[<id>].audit_trail_crud: <status>`). v0 records the weakest-path conservatively in the single block. Component-level surface is reserved for v1+ per `wizard/handoff_contracts/shape_detection_v0.md` § 4.

### 8.4 Halt behavior (HALT path; full-system-generation)

When a stop condition fires AND `shape_hypothesis.fallback_mode_offered == not_offered` (operator is on full-system-generation path):

1. Wizard appends to staging file:
   ```yaml
   shape_hypothesis:
     recheck_log:
       - step: 05
         outcome: halted
         stop_condition_fired: <# from § 8.3>
         halt_timestamp: <ISO 8601>
         halt_message: <verbatim message; with `<actual status>` substituted from control_matrix_active>
   ```
2. Wizard says the halt message verbatim to operator (with capability status substituted).
3. Wizard offers three paths (S2.3 added (c)):
   > Three choices:
   > **(a) Save progress and exit** — your project file is saved; you can complete a compliance review and resume.
   > **(b) Change the shape and re-evaluate** — I'll re-run the shape probes with this regulatory exposure in mind.
   > **(c) Re-evaluate regulatory exposure** — I'll re-ask the step 03 regulatory questions with the stop condition surfaced; if your project actually doesn't fall under [framework] scope, the stop condition won't fire on re-evaluation.
4. If operator picks (b): invoke `wizard/interview/_stop_condition_reevaluate_loop.md` § 2 loop entry; loop sub-module runs probe re-ask + classifier re-emit + stop-condition re-evaluation per S2.3 implementation. **Loop semantics canonical at `_stop_condition_reevaluate_loop.md`** — see that file for state machine + iteration cap (default 2 per S2.3 Decision A) + terminal-state branching. Producer-visible terminal outcomes are the CLOSED 4-value enum: `continued` / `foundation_only` / `scope_out` / `next_iteration` (per R1 C-001 disposition; `forced_terminal` is internal-only branch state at sub-module § 6 — module handles final-choice prompt internally and maps to foundation_only or scope_out with `terminal_reason: iteration_cap_reached`). § 8.4 stays a summary; the canonical implementation lives in the sub-module.
5. If operator picks (c) "Re-evaluate regulatory exposure" (added at S2.3 per Decision C): invoke `wizard/interview/_stop_condition_reevaluate_loop.md` § 4 regulatory-exposure entry; loop sub-module re-asks step 03 UP-6 probes + mutates `regulatory_exposure` if operator clarifies + re-evaluates stop conditions against unchanged shape.

Foundation state IS preserved through halt (staging file unchanged except for halt-log entries).

### 8.5 Documentation behavior (DOCUMENT path; foundation-only mode)

When a stop condition fires AND `shape_hypothesis.fallback_mode_offered == foundation-only` (operator chose foundation-only-mode at step 01/02 unsupported-shape transition; per advisor R1 C-003 disposition):

For conditions 1-3 (capability mismatches that operator already accepted by choosing foundation-only):

1. Wizard appends to staging file:
   ```yaml
   stop_conditions:
     evaluated_at: 05_pre_vision
     fired: [<list of fired condition numbers>]
     halted: false
     documented_in_foundation: [<same list>]
   shape_hypothesis:
     recheck_log:
       - step: 05
         outcome: documented_in_foundation
         stop_conditions_recorded: [<list>]
   ```
2. No halt fires. Wizard proceeds to step 05.
3. **Foundation-only-mode implementation landed at S2.2 (per `wizard/interview/_foundation_only_mode_gate.md` § 6).** Documented stop-condition gaps land in `technical_architecture.md` § "Regulatory & compliance gaps (foundation-only mode)" at step 15 close, with one section per gap (framework name + capability gap + recommended resolution path; read from staging `stop_conditions.documented_in_foundation` + `control_matrix_active`). If `stop_conditions.documented_in_foundation` is empty, the section is omitted entirely (no empty header).

For condition 4 (regulated + no framework identified): **HALT fires even in foundation-only mode** — foundation docs cannot be written honestly without framework identification. Operator must complete operator-side compliance review and resume. Halt behavior per § 8.4 (a/b paths).

This split (HALT for full-system, DOCUMENT for foundation-only with condition 4 exception) is the structural resolution of "operator chose foundation-only knowingly; don't re-halt them; do faithfully record" without compromising honest characterization (D1 § 2.3).

## 9. Forward-offered information capture integration

Per wizard CLAUDE.md § 9. At P1-2 (core purpose), operators frequently volunteer shape signals embedded in their answer:

- "an automated newsletter that goes out every Monday morning" — Probe-1 yes + Probe-6 yes signals embedded
- "a thinking partner for legal research" — Probe-3 yes signal embedded
- "a customer portal where my team can log in and update records" — Probe-1 yes + Probe-2 yes + Probe-5 yes signals embedded

**Classifier integration (per decision E: interpretive prior; NOT authoritative):**

1. At P1-2 answer capture, the wizard's classifier scans the operator's free-text answer for shape-signal phrases heuristically. (Heuristic match patterns are spec-only at v0; precise regex/keyword inventory deferred to first-real-operator-data observation.)
2. Matched signals populate `shape_hypothesis.forward_offered_signals_at_step_01` as verbatim phrases.
3. Probes 1-4 STILL fire — forward-offered signals do NOT substitute for explicit probe answers.
4. When classifier resolves an ambiguous probe answer (operator says "unsure" or gives a non-binary answer), the forward-offered signals act as an **interpretive prior** — e.g., if Probe-1 answered "unsure" but the P1-2 answer contained "runs automatically every Monday," classifier may resolve Probe-1 toward yes; wizard then asks operator: "Earlier you mentioned [verbatim phrase] — does that mean the system needs to keep running on its own? (yes/no)"

**Anti-pattern to avoid:** treating forward-offered signals as authoritative answers without explicit probe confirmation. Probes are the canonical signal source.

## 10. Mechanism stack record (D2 § mechanism-stack-template)

Per `governance/operational_change_safety.md` v0 § 3 mechanism stack template:

| Field | Value |
|---|---|
| **mechanism_id** | `mech-shape-detection-v0` |
| **mechanism_name** | Shape-detection classifier |
| **mechanism_class** | AR-004 family A — Skill, pure markdown (advisory or guided) per S2.1 decision I |
| **primary** | Step 01 P1-4 through P1-7 probes + (conditional) step 02 fallback probes + classifier emit logic in `wizard/shape_detection.md` |
| **reinforcing** | Pre-step-05 re-check + pre-step-08 re-check; forward-offered signal capture at P1-2 (interpretive prior) |
| **detection-recovery** | Pre-step-05 stop-condition evaluation → halt with foundation state preserved; unsupported-shape transition → scope-out OR foundation-only; pre-step-05/08 re-check revise path |
| **rationale** | Behavior-based detection (not shape-name probing) prevents the technical-knob-mismatch failure (Stage 1 anchor #1). Pre-step-05 + pre-step-08 re-check catches signal drift from accumulated interview context. Stop conditions prevent silently generating a system the operator's regulatory exposure can't accept. Unsupported-shape transition preserves operator's foundation state so v2 support can resume without restart. Forward-offered signal capture acts as interpretive prior only — probes remain canonical. |
| **hybrid_contract_status** | n/a (not skill-calls-script) |
| **contract_fields_complete** | n/a |
| **health_check_last_run** | 2026-05-19 (S2.1 fixture-replay first-use) |
| **fallback_verified** | yes (synthetic-fixture replay; real-operator validation bound to next operator-facing slice OR E-α tester) |

## 11. Versioning

This is v0. The mechanism evolves through:

- **Probes refined** (calibration) — small revision per `governance/methodology.md` § 5.1; v0 → v0.1 amend
- **Stop conditions added** (e.g., 5th condition per IDQ-056) — substantive revision; v0 → v1
- **Schema field added to handoff contract** — substantive revision; coordinate with `wizard/handoff_contracts/shape_detection_v0.md` → v1
- **Foundation-shaping change** (e.g., shape taxonomy revised; classifier rewritten as non-markdown mechanism) — foundation-shaping; new ADR + new mechanism_id

## 12. Cross-references

- `wizard/handoff_contracts/shape_detection_v0.md` — handoff contract for downstream rebuild slices
- `wizard/interview/01_phase1_capture.md` — P1-4 through P1-7 probe sub-steps
- `wizard/interview/02_financial.md` — P02-end fallback hook
- `wizard/interview/03_user_profile.md` — UP-6 regulatory-applicability probe
- `wizard/interview/_pre_step_05_recheck.md` — pre-step-05 re-check module
- `wizard/interview/_pre_step_08_recheck.md` — pre-step-08 re-check module
- `governance/generated_system_data_defaults.md` § 2.2 / § 6.1 / § 6.3 — D1 control matrix + regulatory triage + 4 stop conditions
- `governance/operational_change_safety.md` v0 § 3 / § 5 — D2 mechanism stack template + validation evidence storage
- `governance/validation/mech-shape-detection-v0/2026-05-19_s2.1_initial_fixture_replay.md` — fixture-replay evidence (v0 first-use)
- PRD v1 § 4.1 (Sub-option E) / § 4.2 (early shape detection) / § 4.3 (foundation-only mode) / § 4.5 (deferred shapes + un-defer) / § 5.2 (F-1) / § 5.13 (F-12 re-open path) — requirements
- ADR-0018 (Stage 2 framework v0) — slice authority
- `wizard/CLAUDE.md` § 9 (Forward-offered information capture) — integration source
- S2.1 slice spec at `product_evidence/_slices/S2.1_shape_detection_handoff_scaffolding_2026-05-19.md` — design provenance
