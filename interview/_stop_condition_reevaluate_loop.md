# Stop-condition halt → re-evaluate-shape loop — canonical state machine

## What this file does

Provides the single-source-of-truth for the **stop-condition halt → re-evaluate-shape loop** — the wizard's behavior when (a) a stop condition fires at pre-step-05 OR pre-step-08 in the HALT path AND (b) the operator picks one of two recovery options:

- **"(b) Change the shape and re-evaluate"** — wizard runs the step 02 fallback probes again with the regulatory exposure surfaced; classifier re-emits; stop conditions re-evaluate. If the new shape passes, continue. If not, offer terminal choice.
- **"(c) Re-evaluate regulatory exposure"** — wizard re-asks the step 03 UP-6 framework-applicability probes; mutates `regulatory_exposure` if operator clarifies; re-evaluates stop conditions against unchanged shape. If conditions cleared, continue. If not, offer terminal choice.

The wizard does NOT silently fizzle the operator into foundation-only mode at halt — the loop runs transparently; the operator's path through the loop's terminal state is operator-elected at every step.

This module is invoked from two producer sites:

- `wizard/interview/_pre_step_05_recheck.md` Step 2a — when a stop condition fires in the HALT path (operator on full-system-generation path; `fallback_mode_offered: not_offered`)
- `wizard/interview/_pre_step_08_recheck.md` Step 2 — when a late-emergence stop condition fires (vision / approach / advisors content newly implicates a framework)

## When this file runs

This is a SHARED reference module, NOT an interview step. Per-producer entry guards (in `_pre_step_05_recheck.md` Step 2a + `_pre_step_08_recheck.md` Step 2) invoke this module's § 2 loop entry OR § 4 regulatory-exposure entry based on operator's choice. The module runs the loop, then returns control to the producer with a terminal-state outcome that the producer acts on.

## Prerequisites

- `~/claude-wizard-draft/wizard_session_draft.md` exists
- `shape_hypothesis` block populated with `fallback_mode_offered: not_offered` (operator on full-system-generation path; HALT seam)
- `regulatory_exposure` block populated (step 03 UP-6 completed)
- `stop_conditions.fired` non-empty (at least one stop condition fired at the producer site that invoked this module)
- `control_matrix_active` populated for the current shape

If any prerequisite is missing, this is a wizard-internal-state error per the producer's own prerequisite-check pattern; halt with internal-error message; foundation state preserved.

## Reference spec

- The originating slice spec (build-side; not distributed) is the design provenance for this module.
- `wizard/shape_detection.md` § 8.3 (4 stop conditions) + § 8.4 (HALT path) + § 6 (unsupported-shape transition) — canonical contracts this loop implements
- `wizard/handoff_contracts/shape_detection_v0.md` § 9 `shape_revision` block + § 7 consumer rules — schema for loop state
- the relevant product spec section (unsupported-shape transition) + § 5.2 F-1 (shape detection contract)

---

## Section 1 — Loop entry contract (called by producers)

Producers invoke this module with the following inputs (passed via shared staging file context — no explicit parameter list at v0 markdown-skill stage):

| Input | Source | Semantics |
|---|---|---|
| `entered_from` | producer | `pre_step_05` OR `pre_step_08` |
| `pre_iteration_fired_conditions` | staging `stop_conditions.fired` | List of condition numbers that fired at the producer's evaluation |
| `late_emergence_source` (pre_step_08 only) | producer | `vision` OR `approach` OR `advisors` (which step-05-07 surface implicated the framework) |
| `operator_choice` | operator's halt-time pick | `(b) change_shape` OR `(c) regulatory_exposure_revise` |

Module **outputs** (via staging-file mutation):

| Output | Target field | Semantics |
|---|---|---|
| Loop history entry | `shape_revision.history[]` | One entry per iteration |
| Loop pending state | `shape_revision.pending` | `true` during active iteration; `false` at terminal |
| Loop iteration counter | `shape_revision.iteration` | Increments at each (b)/(c) entry |
| New `shape_hypothesis` (if (b) path led to new shape) | `shape_hypothesis.*` | Updated by classifier re-emit |
| New `regulatory_exposure` (if (c) path revised) | `regulatory_exposure.*` | Updated by UP-6 re-ask |
| Re-evaluated `stop_conditions` | `stop_conditions.*` | Re-populated against post-iteration shape + regulatory state |
| `stop_conditions.fired` + `documented_in_foundation` + `resolved_during_loop` + `halted: false` mutation | `stop_conditions.*` | At terminal `foundation_only`: **active terminal conditions** (those still firing at terminal evaluation, after all loop revisions) roll into `documented_in_foundation` so gate module § 6 surfaces them as compliance gaps; **transitional conditions resolved during loop iterations** (e.g., condition 4 resolved by framework-identification) go to `resolved_during_loop` audit-trail field, NOT to `documented_in_foundation`; `halted: true → false` (operator-elected foundation-only resolved the halt) per advisor finding active-vs-transitional distinction |
| Terminal-state outcome | `shape_revision.history[<last>].outcome` | `continued` / `foundation_only` / `scope_out` / `next_iteration` (producer-visible; closed enum) |
| Terminal reason metadata | `shape_revision.history[<last>].terminal_reason` | Disambiguates HOW the terminal outcome was reached. Optional field; populated at terminal entries only. Values: `passing_shape_re_emit` / `regulatory_exposure_revised_clears_conditions` / `unsupported_shape_transition` / `iteration_cap_reached` / `operator_chose_save_and_exit` |

After this module returns, the producer reads `shape_revision.history[<last>].outcome` and acts on **one of four producer-visible terminal outcomes**:

- `continued` → producer proceeds to its next step (pre_step_05 → step 05 vision; pre_step_08 → step 08 architecture)
- `foundation_only` → producer sets `shape_hypothesis.fallback_mode_offered: foundation-only` AND proceeds (downstream foundation-only-mode entry guards per `_foundation_only_mode_gate.md` handle the path); compliance gaps from **active terminal conditions** are rolled into `stop_conditions.documented_in_foundation` by the module; **transitional conditions resolved during the loop** go to `stop_conditions.resolved_during_loop` audit-trail field per § 7 active-vs-transitional distinction
- `scope_out` → producer exits cleanly (foundation state preserved)
- `next_iteration` → producer re-offers (a)/(b)/(c) at the halt; module is re-invoked with new `operator_choice`

**`forced_terminal` is NOT a producer-visible outcome.** It is an internal-only branch state at § 6 that triggers the § 7 Terminal: forced final-choice prompt. The module handles that prompt internally and maps the operator's (i)/(ii) pick to `foundation_only` or `scope_out` (with `terminal_reason: iteration_cap_reached` recorded). Producers MUST NOT see `outcome: forced_terminal` in history entries at terminal state.

---

## Section 2 — Loop entry: (b) Change the shape and re-evaluate

### Step 2.1 — Increment iteration counter

Read `shape_revision` block from staging (if absent, initialize with `iteration: 0, iteration_cap: 2, history: []`). Compute:

```
new_iteration = (shape_revision.iteration or 0) + 1
```

If `new_iteration > shape_revision.iteration_cap` (default cap = 2): **iteration cap reached.** Skip to § 7 Terminal: forced — do not run a third probe round.

If under cap: continue to Step 2.2. Set `shape_revision.pending: true`.

### Step 2.2 — Honest-characterization disclosure

Say verbatim to operator:

> Let me re-check the shape with the regulatory exposure in mind. v1 of the wizard supports only the `markdown-agents` shape for full system generation — alternative shapes (Python service, hosted cloud, multi-user-datastore, etc.) are on the v2+ roadmap. The most likely outcomes from re-running the probes: (i) you converge to foundation-only mode; (ii) you choose to exit and resume later when v2 supports your shape. There's a small chance the re-evaluation surfaces a shape we hadn't considered — let me re-run the probes and see where we land.

This disclosure is **NOT optional** per the honest-characterization rule. Operators must understand the v1-shape-set constraint before consenting to the loop.

### Step 2.3 — Re-ask step 02 fallback probes (P-5, P-6, P-7)

Re-ask **only the step 02 fallback probes** (P-5 / P-6 / P-7), NOT step 01 probes P-1 through P-4.

For each of P-5, P-6, P-7 in order (probes defined at `wizard/shape_detection.md` § 2.2):

1. Read the operator's prior answer from `shape_hypothesis.operator_signals.probe_<N>_*`.
2. Surface that answer + the framework constraint + ask whether they'd answer differently now.

Example for P-5 (`is_continuous_running`):

> Earlier you said the system [<paraphrase prior answer — e.g., "needs to keep running continuously" / "doesn't need to keep running on its own">]. Given that [<framework name from `regulatory_exposure`>] applies, the system would need to support [<capability requirement summarized from § 8.3 stop condition that fired — e.g., "enforced audit-trail" / "enforced encryption-at-rest" / "enforced access control with DSR endpoints">]. Does that change your answer? Does the system actually need to keep running on its own continuously? (yes / no / unsure)

Repeat the pattern for P-6 (`is_multi_user`) and P-7 (`requires_external_systems`) — each with the same framework-constraint framing.

### Step 2.4 — Classifier re-emit

After collecting new P-5/P-6/P-7 answers, the classifier re-emits per `wizard/shape_detection.md` § 2.3 signal-to-shape decision table. The re-emit MAY:

- Produce same `shape: markdown-agents` (likely outcome if probe answers didn't materially change)
- Produce `shape: python-service-operator-facing` / `claude-skills` / `node-ui` / `multi-user-datastore` / `hosted-cloud` / `mixed` (rare — would have been caught at step 01 originally; possible if probes were originally answered with low-confidence and operator now revises)
- Produce `shape: unknown` (if probes yielded LOW after re-ask)

Update `shape_hypothesis.shape`, `shape_hypothesis.confidence`, `shape_hypothesis.operator_signals.*` per re-emit.

### Step 2.5 — Re-populate `control_matrix_active`

If new `shape != prior shape`: re-populate `control_matrix_active` per `wizard/shape_detection.md` § 7 + the per-shape control-matrix column for new shape. For `mixed` shapes, weakest-path-across-components per § 8.3.

If new shape == prior shape: `control_matrix_active` unchanged.

Proceed to § 6 stop-condition re-evaluation.

---

## Section 3 — Iteration cap + counter semantics

**Iteration cap = 2** at v0 (calibration-pending; first-real-operator-data may revise).

**Semantics of cap = 2:** two loop iterations are permitted; on entering a third loop iteration, force terminal per § 7. Concretely:

- `iteration: 0` — operator never entered the loop (initial state before any (b)/(c) pick)
- `iteration: 1` — operator picked (b) or (c) once; iteration 1 has run or is running
- `iteration: 2` — operator picked (b) or (c) twice; iteration 2 has run or is running; on completion, branch table sets internal state `forced_terminal` → § 7 final-choice prompt → terminal outcome foundation_only or scope_out
- `iteration: > 2` — cannot reach this state under the cap; on attempted entry at `new_iteration = 3`, module skips iteration body and routes directly to § 7 Terminal: forced final-choice prompt

When `new_iteration > iteration_cap`, the loop forces terminal choice per § 7. No third probe re-ask runs; the operator is offered only foundation-only OR scope-out.

**Cap applies per-producer.** Per the counter-reset policy, pre_step_08 invocation starts fresh counter (`shape_revision.iteration` resets to 0 when entered_from changes from pre_step_05 to pre_step_08, AS LONG AS pre_step_05 reached terminal first; otherwise treat as continuation). Implementation: on `entered_from: pre_step_08` AND prior `shape_revision.history[*].entered_from: pre_step_05` AND prior outcomes all terminal, RESET counter to 0 before increment. Document this transition in `shape_revision.history[]` for traceability.

---

## Section 4 — Loop entry: (c) Re-evaluate regulatory exposure

The (c) regulatory-exposure re-evaluation path is supported at v0.

### Step 4.1 — Increment iteration counter

Same logic as § 2.1. Cap applies to (b) and (c) combined; an operator who picks (c) on iteration 1 then (b) on iteration 2 has used both iterations.

### Step 4.2 — Honest-characterization disclosure

**Two disclosure variants** depending on which condition fired:

**Variant A: conditions 1, 2, or 3 fired** (framework named: HIPAA / GDPR / PCI-DSS). Say verbatim:

> OK, let me re-ask the regulatory questions. The stop condition that fired was that [<framework>] applies — if your project actually doesn't fall under [<framework>]'s scope, the stop condition won't fire on re-evaluation. Common reasons operators initially answer "yes" to [<framework>] but later revise to "no":
>
> [<framework-specific examples, choose by framework:>]
> — **HIPAA:** "HIPAA only applies if you're a covered entity (health-care provider, plan, or clearinghouse) OR a business associate handling protected health information (PHI) on their behalf. Not just any health-related project."
> — **GDPR:** "GDPR applies if you have EU customers OR EU-based users (regardless of payment / commercial relationship). Not just any project that might be accessed from the EU."
> — **PCI-DSS:** "PCI-DSS applies if your system stores, processes, or transmits cardholder data (CHD) — full PANs, sensitive auth data. Not just any project that accepts payments via a hosted gateway."

**Variant B: condition 4 fired** (regulated + framework not identified — the framework is unknown, so disclosure cannot cite a specific framework). Say verbatim:

> OK, let me re-ask the regulatory questions. The stop condition that fired was "regulated data is involved but the specific compliance framework isn't yet identified." There are two ways to clear this:
>
> (i) **Identify the specific framework that applies.** If you can name the framework (e.g., HIPAA / GDPR / PCI-DSS / SOX / COPPA / sector-specific), I can re-evaluate with that framework's actual capability requirements — the loop may converge to foundation-only OR exit OR (rarely) a passing path.
>
> (ii) **Revise the regulated-data flag itself.** If on reflection your project doesn't actually involve regulated data (e.g., you initially marked health information but you're producing aggregate de-identified statistics not subject to HIPAA), the stop condition won't fire on re-evaluation.
>
> Common reasons operators initially mark a regulated bucket but framework is unknown: (1) "I work with sensitive data but I'm not sure which regulation applies"; (2) "I picked the closest bucket but the actual framework is sector-specific (e.g., FERPA for education, GLBA for finance, COPPA for under-13 users)." Either route — framework identification OR regulated-flag revision — is a valid loop exit.

### Step 4.3 — Re-ask UP-6 probes

For the framework that fired the stop condition (and any related framework — e.g., re-asking HIPAA may also re-ask `no_compliance_claim` related questions), re-fire the UP-6 framework-applicability probe per `wizard/interview/03_user_profile.md` UP-6 patterns.

For each framework field (`hipaa_applicable` / `gdpr_applicable` / `pci_dss_applicable` / `sox_applicable` / `coppa_or_gdpr_k_applicable` / `other_sector_specific[*].applicable` / `no_compliance_claim` / `no_compliance_claim_framework_identification`):

1. Read prior answer.
2. Ask: "Earlier you said [framework] applies (yes/no/unknown). Based on the clarification above, do you want to revise that answer?"
3. If operator revises: update `regulatory_exposure.<field>` AND append revision entry to `shape_revision.history[<current iteration>].regulatory_exposure_revised[]`.

**Condition-4 variant of UP-6 re-ask** (framework not identified): in addition to the per-field revision questions above, also offer the framework-identification path:

- Ask: "If you can identify the specific framework that applies to your project's regulated data, tell me which one — HIPAA / GDPR / PCI-DSS / SOX / COPPA / or sector-specific (e.g., FERPA, GLBA, financial-services-specific, healthcare-adjacent). Identifying the framework lets me evaluate against its actual capability requirements."
- If operator identifies a framework: update `regulatory_exposure.no_compliance_claim_framework_identification: unknown → no` (per UP-6 source semantics at `03_user_profile.md` line 264 — `no` means "no unresolved framework-identification gap"; the framework identification clears the condition-4 trigger; using the contract-defined enum `yes | no | unknown`) AND populate the corresponding `*_applicable: yes` field (e.g., `hipaa_applicable: yes` if operator identified HIPAA; for sector-specific frameworks, append `{ framework: <name>, applicable: yes }` entry to `other_sector_specific[]` per UP-6 line 236-241 pattern). Append a revision entry to `shape_revision.history[<current iteration>].regulatory_exposure_revised[]` with `reason: framework_identification`.
- If operator picks "I still can't identify it but I'm sure regulated data is involved": preserve `no_compliance_claim_framework_identification: unknown`; condition 4 will still fire on re-evaluation; route to next-iteration or forced-terminal per § 6 branch table.

### Step 4.4 — Re-evaluate stop conditions

Run stop-condition evaluation per `wizard/interview/_pre_step_05_recheck.md` Step 2 logic against updated `regulatory_exposure` + unchanged `control_matrix_active` (shape is unchanged in (c) path; new conditions may fire if condition-4 variant resolved to a specific framework that now triggers conditions 1/2/3 against the unchanged shape's capabilities).

If conditions cleared (no stop condition fires post-revision): mark `outcome: continued` + `terminal_reason: regulatory_exposure_revised_clears_conditions`; proceed to § 7 Terminal: continued.

If conditions still fire: proceed to § 6 with same shape + revised regulatory state. Note: condition-4 path may transition into conditions 1/2/3 firing when operator identifies the framework — that's expected behavior; loop continues from § 6 branch table.

---

## Section 5 — (Reserved for future expansion — not used at v0)

This section is intentionally blank at v0. Reserved for a potential third operator path "(d) commit to operator-side compliance review" if first-real-operator-data shows demand for an in-wizard compliance-review-acknowledgment surface distinct from (a) save-and-exit. Currently (a) save-and-exit subsumes this case operationally.

---

## Section 6 — Stop-condition re-evaluation after iteration

Run the same logic as `wizard/interview/_pre_step_05_recheck.md` Step 2 against the **post-iteration state**:

- **Capability-based evaluation** (mixed-shape weakest-path across components per § 8.3)
- **HALT-vs-DOCUMENT path split** — but note that this loop only runs in the HALT path (operator on `fallback_mode_offered: not_offered`); DOCUMENT-path stop conditions don't enter this loop.

Branching after re-evaluation (internal branch state may differ from producer-visible terminal outcome per § 1 — see "internal branch state" column):

| Post-iteration state | Internal branch state | Producer-visible outcome | terminal_reason | Action |
|---|---|---|---|---|
| New shape is v1-supported (`markdown-agents`) AND no conditions fire | `continued` | `continued` | `passing_shape_re_emit` (for (b) path) OR `regulatory_exposure_revised_clears_conditions` (for (c) path) | Terminal: continued; record outcome; return to producer |
| New shape is NOT v1-supported (`python-service-operator-facing` / `claude-skills` / `node-ui` / `multi-user-datastore` / `hosted-cloud` / `mixed`) | `unsupported_shape_transition` | `foundation_only` OR `scope_out` (depending on operator pick unsupported-shape transition) | `unsupported_shape_transition` | Trigger unsupported-shape transition per `wizard/shape_detection.md` § 6 — operator offered foundation-only OR scope-out contract; module records the operator's pick as terminal outcome |
| New shape is `markdown-agents` AND conditions still fire AND iteration < cap | `next_iteration` | `next_iteration` | (not populated; not a terminal state) | Re-offer (a)/(b)/(c) at producer; module returns; producer re-invokes module on next (b)/(c) pick (or exits on (a)) |
| New shape is `markdown-agents` AND conditions still fire AND iteration == cap | `forced_terminal` (internal) | `foundation_only` OR `scope_out` (per operator's (i)/(ii) pick at § 7 forced disclosure) | `iteration_cap_reached` | § 7 Terminal: forced disclosure said by module; module reads operator's (i)/(ii) pick; sets producer-visible outcome accordingly |
| New shape is `unknown` (LOW confidence after re-ask) | `forced_terminal` (internal; treated same as conditions-still-fire-at-cap) | `foundation_only` OR `scope_out` | `iteration_cap_reached` (with unknown-shape note in history) | § 7 forced disclosure; operator offered foundation-only OR scope-out |

Record producer-visible outcome in `shape_revision.history[<last>].outcome` per § 9 schema. Record disambiguating `terminal_reason` for terminal entries.

**Internal branch state `forced_terminal` is NOT recorded as a producer-visible outcome.** It is captured only as a `terminal_reason: iteration_cap_reached` entry on the foundation_only / scope_out outcome that follows (per § 1 output contract).

---

## Section 7 — Terminal-state branching

### Terminal: continued

State: new shape passes stop conditions OR (c) regulatory-exposure-revise eliminated firing condition.

```yaml
shape_revision:
  pending: false
  iteration: <N>
  history:
  -...
  outcome: continued
  terminal_at: <ISO 8601>
```

Say to operator:

> OK, after re-evaluation, [<framework>] [no longer applies / now matches a passing shape]. We can continue with [<shape>] generation. [Vision phase / architecture phase] next.

Return to producer with `outcome: continued`. Producer proceeds.

### Terminal: foundation-only

State: operator picked foundation-only at unsupported-shape transition OR at forced-terminal final-choice prompt (§ 7 Terminal: forced).

**Cross-slice mutation: roll ACTIVE terminal stop conditions into DOCUMENT-path block.** When loop terminal foundation-only is reached, the **active terminal-state fired stop conditions** (those firing at the terminal evaluation, after operator revisions during the loop) must be rolled into `stop_conditions.documented_in_foundation` so the gate module's § 6 surfaces them as compliance-gap entries in `technical_architecture.md`. WITHOUT this mutation, the foundation-only mode's gate module would see `documented_in_foundation: []` (or absent) and omit the compliance-gaps section entirely — that would be a silent loss of the operator's regulatory-mismatch documentation (violating the honest-characterization rule).

**Active vs transitional distinction.** When the loop transitions through conditions (e.g., condition 4 fires at entry → operator identifies HIPAA via (c) path → condition 4 resolved + condition 1 fires post-revision → terminal foundation-only), only conditions firing **at terminal evaluation** are active compliance gaps; transitional conditions resolved during the loop (e.g., condition 4 resolved by framework-identification) are NOT active gaps and MUST NOT appear in `documented_in_foundation`. Including a resolved condition would emit a false "regulated-but-unnamed-framework" gap in technical_architecture.md, contradicting the actual loop outcome (framework was identified; the gap is HIPAA-on-markdown-agents, not regulation-without-framework).

Use the optional `resolved_during_loop` array to preserve audit-trail of conditions that fired during the loop but were resolved before terminal:

```yaml
stop_conditions:
  fired: [<active terminal conditions only>] # at terminal: snapshot of conditions still firing post-loop
  halted: false # flipped true → false at terminal foundation_only
  documented_in_foundation: [<active terminal conditions only>]
  resolved_during_loop: [<conditions that fired during loop iterations but were resolved>]
  resolved_via: stop_condition_reevaluate_loop_foundation_only
```

For audit: `shape_revision.history[].pre_iteration_fired_conditions` already preserves the per-iteration firing history; `resolved_during_loop` is an aggregate of which of those were resolved before terminal (i.e., conditions that fired at iteration N but did NOT fire at iteration N+1).

```yaml
shape_revision:
  pending: false
  iteration: <N>
  history:
  -...
  outcome: foundation_only
  terminal_reason: <unsupported_shape_transition | iteration_cap_reached>
  terminal_at: <ISO 8601>
shape_hypothesis:
  fallback_mode_offered: foundation-only
  foundation_only_offered_timestamp: <ISO 8601>
stop_conditions:
  evaluated_at: <05_pre_vision | 08_pre_architecture> # preserved from original halt
  fired: [<active terminal conditions only>] # those still firing at terminal evaluation (post all loop revisions); NOT historical fired list
  halted: false # FLIPPED true → false at terminal foundation-only (loop resolved the halt to foundation-only path)
  documented_in_foundation: [<active terminal conditions only>] # equals `fired` at terminal; gate module § 6 emits gaps for these
  resolved_during_loop: [<conditions that fired during loop iterations but were resolved before terminal>] # optional audit-trail; empty if loop had no transitional resolution
  resolved_via: stop_condition_reevaluate_loop_foundation_only # provenance of how documented_in_foundation came to be populated
  halt_message: <preserved verbatim from original halt — operator already saw it; record retained>
```

The unsupported-shape-transition foundation-only message is reused verbatim (no new operator-facing message required at this seam; foundation-only entry is structurally same regardless of how operator reached it):

> Foundation-only mode confirmed. I'll generate the planning documents for your project — vision, approach, technical architecture, and so on — abstracted from the implementation shape. You'll take those docs to Claude Code directly to build the implementation. We won't generate the actual agents, scripts, or run files.

Return to producer with `outcome: foundation_only`. Producer proceeds (downstream foundation-only-mode entry guards per `_foundation_only_mode_gate.md` handle the path; § 6 DOCUMENT-path integration reads `stop_conditions.documented_in_foundation` and emits compliance-gap section into `technical_architecture.md` at step 15 close).

### Terminal: scope_out

State: operator picked save-and-exit at any (a) prompt OR at unsupported-shape transition (a) OR at forced-terminal scope-out (§ 7 Terminal: forced (ii)).

```yaml
shape_revision:
  pending: false
  iteration: <N>
  history:
  -...
  outcome: scope_out
  terminal_reason: <operator_chose_save_and_exit | unsupported_shape_transition | iteration_cap_reached>
  terminal_at: <ISO 8601>
shape_hypothesis:
  fallback_mode_offered: scope-out
  scope_out_at_halt: <ISO 8601>
```

Say to operator (verbatim per the slice spec):

> Saved. Re-run the wizard when you're ready.

Return to producer with `outcome: scope_out`. Producer exits cleanly.

### Terminal: forced (internal branch state when iteration cap reached)

State: iteration cap reached AND conditions still fire. This is an **internal branch state**, NOT a producer-visible terminal outcome (per § 1 output contract). The module handles the final-choice prompt internally; the operator's pick maps to `foundation_only` or `scope_out` outcome with `terminal_reason: iteration_cap_reached`.

Say verbatim to operator:

> We've cycled through [<iteration count>] iterations of re-evaluation. v1 supports only `markdown-agents` shape, and `markdown-agents` doesn't meet [<framework>] compliance per stop condition [<condition number>]. Your remaining options are:
>
> **(i) Foundation-only mode** — I generate planning documents for your project; you implement separately, OR wait for v2 shape support that meets [<framework>] compliance natively.
>
> **(ii) Save and exit** — resume when v2 supports your shape, OR after you've completed an operator-side compliance review and revised your regulatory exposure assessment.
>
> Which would you like? (Say "i" or "ii".)

If operator picks (i): set producer-visible `outcome: foundation_only` + `terminal_reason: iteration_cap_reached`; route to Terminal: foundation-only handling (including `stop_conditions.documented_in_foundation` mutation per cross-slice rule above).
If operator picks (ii): set producer-visible `outcome: scope_out` + `terminal_reason: iteration_cap_reached`; route to Terminal: scope_out handling.

There is no third (b) loop entry from forced-terminal — the cap is hard. The producer NEVER sees `outcome: forced_terminal`; the module records the final operator-elected outcome (foundation_only or scope_out) instead.

---

## Section 8 — Honest-characterization disclosure rules

Per the honest-characterization rule.

The disclosure surfaces at three points:

1. **At loop iteration entry (operator picks (b) at halt)** — per § 2.2 verbatim
2. **At loop iteration entry (operator picks (c) at halt)** — per § 4.2 verbatim
3. **At forced-terminal** — per § 7 Terminal: forced verbatim

The disclosure is **NOT optional** — silent fallback into foundation-only without disclosure would violate the honest-characterization rule.

**NOT silent fallback.** Foundation-only at terminal is operator-elected (operator picks "i" at forced-terminal OR (b) at unsupported-shape transition). The loop's value is operator-agency + honest discovery, not "find a passing shape silently."

---

## Section 9 — Persistence schema

Per the persistence-schema design + handoff contract § 9.

```yaml
shape_revision:
  pending: false # boolean — true during active loop iteration; flipped to false at terminal state
  iteration: 0 # integer — current loop iteration count; 0 before first entry; increments at each (b)/(c) entry
  iteration_cap: 2 # integer — stable at v0 per the relevant slice decision; means "two loop iterations permitted; on entering a third, force terminal"
  history: # append-only array — preserved at terminal per the cleanup-discipline policy
  - iteration: 1
  entered_at: <ISO 8601>
  entered_from: pre_step_05 | pre_step_08
  pre_iteration_shape: <shape value>
  pre_iteration_fired_conditions: [<condition numbers>]
  operator_choice: (b) change_shape | (c) regulatory_exposure_revise
  probes_re_asked: [P-5, P-6, P-7] # or UP-6 field names for (c)
  classifier_re_emit: <shape value> # only for (b) path
  regulatory_exposure_revised: # only for (c) path
  - field: <field name>
  old: <old value>
  new: <new value>
  reason: operator_clarification
  post_iteration_shape: <shape value>
  post_iteration_fired_conditions: [<condition numbers>]
  outcome: continued | foundation_only | scope_out | next_iteration # producer-visible enum; CLOSED (forced_terminal is internal-only branch state per § 6 + § 1 — never recorded here)
  terminal_reason: passing_shape_re_emit | regulatory_exposure_revised_clears_conditions | unsupported_shape_transition | iteration_cap_reached | operator_chose_save_and_exit # optional; populated only at terminal entries; disambiguates HOW outcome was reached
  terminal_at: <ISO 8601> # only if outcome is terminal
```

**Cross-slice mutation companion (terminal foundation_only only).** When `outcome: foundation_only` is recorded, the module also mutates the staging file's `stop_conditions` block per § 7 Terminal: foundation-only:

- `fired: [<active terminal conditions only>]` — those still firing at terminal evaluation, post-all-loop-revisions (NOT historical fired list across all iterations; per advisor finding active-vs-transitional distinction)
- `documented_in_foundation: [<same as fired>]` — POPULATED so gate module § 6 emits gaps for these
- `resolved_during_loop: [<conditions that fired during loop but were resolved before terminal>]` — OPTIONAL audit-trail field; records transitional resolutions for diagnostic provenance; empty if no transitional resolution occurred
- `halted: true → false` — flipped at terminal foundation-only
- `resolved_via: stop_condition_reevaluate_loop_foundation_only` — provenance

This is NOT in the `shape_revision` block; it's an out-of-block mutation required for cross-slice integration with the foundation-only-mode gate module's § 6. gate module § 6 reads `documented_in_foundation` only; `resolved_during_loop` is audit-only and NOT consumed by the gate module (verified R2).

**Cleanup discipline.** At terminal state, `pending: false` is set; `history[]` array is **preserved** (not cleared) for diagnostic / audit-trail value. Subsequent producers reading the staging file see full loop history. The cross-slice `stop_conditions` mutation (when applicable) is also preserved.

**Counter-reset across producers.** Per the counter-reset policy: on `entered_from: pre_step_08` AND prior `shape_revision.history[*].entered_from: pre_step_05` AND prior outcomes all terminal, RESET `iteration` to 0 before increment. The reset transition is itself recorded in `history` for traceability.

---

## Section 10 — Mechanism stack record (D2 § mechanism-stack-template)

Per the operational change safety spec mechanism-stack-template.

```yaml
mechanism_id: mech-stop-condition-reevaluate-loop-v0
mechanism_name: Stop-condition halt → re-evaluate-shape loop
mechanism_class: Skill — pure markdown (advisory or guided)
mechanism_type: markdown
hybrid_contract_status: not-applicable
canonical_governance_doc: wizard/interview/_stop_condition_reevaluate_loop.md
primary_mechanism: this loop sub-module (state machine + iteration cap + probe re-ask + stop-condition re-evaluation + terminal-state branching + (c) regulatory-exposure re-evaluation path); invocations from `_pre_step_05_recheck.md` Step 2a + `_pre_step_08_recheck.md` Step 2 (late-emergence)
reinforcing_mechanisms:
  - shape_hypothesis block in staging file (mutated by loop's classifier re-emit; consumer pattern verifies schema_versions check per advisor finding lesson)
  - shape_revision block in staging file (NEW ; persistence of loop history; additive schema extension via schema_minor 0 → 1)
  - wizard/shape_detection.md § 8.4 step 4 (cross-references this sub-module as canonical impl)
  - wizard/handoff_contracts/shape_detection_v0.md § 9 (consumer contract for shape_revision block; additive)
  - Iteration cap (2 at v0) — prevents infinite loops + bounds operator-loop-fatigue exposure
  - Honest-characterization disclosure rule — disclosed at loop iteration entry + at terminal state
  - foundation-only-mode interaction (mech-foundation-only-mode-v0) — loop terminal state may transition to foundation-only mode
detection_recovery_mechanisms:
  - Iteration cap forces terminal choice (foundation-only OR exit) — prevents infinite loop
  - Schema_versions check on shape_revision block (consumer pattern) — prevents stale-schema misread
  - Foundation state preservation through loop iterations — staging file + vision/approach (pre_step_08 case) preserved; loop does NOT mutate them
  - Honest-characterization disclosure at iteration entry — operator knows the likely outcomes; no surprise foundation-only landing
rationale: prior wizard work specified the contract surface ("(b) Change the shape and re-evaluate") at pre_step_05 + pre_step_08 + shape_detection.md § 8.4 step 4 but deferred implementation; this module implements the real loop. The loop's value in v1 is operator-agency: even when the loop converges to foundation-only OR exit (the dominant v1 outcome given v1-shape-set constraints — markdown-agents only), running it transparently lets the operator discover their options vs. silently dropping them into foundation-only. The (c) regulatory-exposure path adds a third axis of operator agency — operator can realize they over-stated regulatory exposure at step 03 and revise without committing to shape revision. The iteration cap prevents loop-fatigue. The shared sub-module pattern earns its keep through substantive state-machine logic + propagation-fragility of inlining (per the validate-the-WHY discipline; the precedent-source's shared-module justification was different, but the structural reason transfers here).
validation_method: manual paper-replay walkthrough of loop state machine + iteration cap + probe re-ask + terminal-state branching against synthetic fixtures (4 stop-condition-reevaluate-loop fixtures + regression check). Per the validation evidence storage convention.
validation_evidence: validation/mech-stop-condition-reevaluate-loop-v0/2026-05-19_s2.4_condition_4_fixture_extension.md (extends validation/mech-stop-condition-reevaluate-loop-v0/2026-05-19_s2.3_initial_fixture_replay.md)
known_coverage_limits:
  - Synthetic fixtures only; no real-operator data
  - Paper-replay only (markdown-driven interview agent; no executable run)
  - Iteration cap calibration (2) is hypothesis-only; first-real-operator-data may revise
  - Probe re-ask path (step 02 fallback probes only; P-5/P-6/P-7) is the v0 default; first-real-operator-data may revise to Alt A (re-ask all 7 probes) or Alt B (free-text describe-changes)
  - PCI-DSS / SOX / COPPA (c) revise paths not separately fixtured at v0 (HIPAA + GDPR + sector-specific covered via scrl03 + scrl05 + scrl06 + scrl08 + scrl09; remaining named frameworks assumed symmetric per § 4.2 Variant A framework-specific disclosure variants)
  - Pre-step-08 loop with vision+approach already on disk tested for HIPAA late-emergence only (scrl04); pre-step-08 condition-4 late-emergence NOT separately fixtured (pre_step_05 only; structurally same as scrl04 with different trigger framework); other framework late-emergence cases assumed to follow same pattern
  - Mixed-shape per-component capability loop interaction not exercised (reserved for v1+ handoff contract § 5)
  - Concurrent loop-then-late-emergence-at-pre-step-08 case tested with fresh iteration counter at pre_step_08; inherit-counter alternative not exercised
  - Sector-specific compliance-class frameworks (FERPA / GLBA / similar with enforceable controls) NOT exercised on continuing paths because v0 has no 5th stop condition for sector-specific compliance frameworks beyond the named ones (HIPAA / GDPR / PCI-DSS / SOX / COPPA). Demonstrating active compliance-class sector framework on continuing path would violate the honest-characterization rule. an open question reserves the design space for the 5th stop condition; v0 fixtures use named-compliance frameworks (HIPAA + GDPR in scrl08) for multi-framework re-ask coverage. Forward-looking gap; not a demonstrated-working surface. scrl08 was restructured from HIPAA + FERPA to HIPAA + GDPR to avoid demonstrating an honest-characterization-rule violation.
  - Active-vs-transitional distinction at cross-slice mutation: `documented_in_foundation` records active terminal-state fired conditions only; transitional conditions resolved during loop iterations (e.g., condition 4 resolved when operator identifies framework) are recorded in optional `resolved_during_loop` audit-trail field, NOT in `documented_in_foundation`. Without this distinction, foundation docs would emit false stale gaps (e.g., "regulated-but-unnamed-framework" gap when framework was actually identified). scrl06 fixture demonstrates correct behavior.
reverify_trigger: first real-operator-input loop iteration; OR iteration cap calibration revised; OR the probe-re-ask-path policy revised; OR shape-detection contract major-version bump (would change shape_revision block schema semantics); OR foundation-only-mode mechanism revised (mech-foundation-only-mode-v0 revision); OR new v1-supported shape added (would change loop convergence behavior); OR 5th stop condition added; OR sector-specific framework treatment policy revised
mvp_lifecycle: foundation-tier (gates operator-recovery path from regulatory-constraint halt; load-bearing for full-system-generation path completion when stop conditions fire)
```

---

## Cross-references

- The originating slice spec (build-side; not distributed) is the design provenance for this module.
- `wizard/shape_detection.md` § 8.3 (stop conditions) + § 8.4 (HALT path) — stop-condition + halt protocol contracts this loop implements.
- `wizard/interview/_foundation_only_mode_gate.md` — foundation-only-mode interaction at terminal: foundation-only branch.
- `wizard/shape_detection.md` § 8.3 (4 stop conditions) + § 8.4 (HALT path; cross-references this module) + § 6 (unsupported-shape transition)
- `wizard/handoff_contracts/shape_detection_v0.md` § 7 (consumer rules) + § 9 (shape_revision block)
- `wizard/interview/_pre_step_05_recheck.md` Step 2a — producer site #1 invocation point
- `wizard/interview/_pre_step_08_recheck.md` Step 2 — producer site #2 invocation point
- `wizard/interview/_foundation_only_mode_gate.md` — terminal-state handoff target (when loop converges to foundation-only)
- the per-shape control matrix — honest characterization rule
- the operational change safety spec § mechanism-stack-template — mechanism stack record format
- the relevant product spec section + § 5.2 F-1 — requirements
