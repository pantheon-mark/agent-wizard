---
fixture_id: fom04-markdown-document-path
schema_version: fixture-replay-v1
fixture_class: foundation-only-mode
source_shape: markdown-agents
source_fixture: sc01-hipaa-markdown-halt
mode: foundation-only-DOCUMENT-path
expected_unsupported_shape_transition: |
  none (shape is markdown; transition not fired at step 01 or 02)
expected_halt_initial: |
  true (HIPAA stop condition fires HALT at pre-step-05 with `fallback_mode_offered: not_offered`)
expected_halt_after_choice: |
  false (operator picks (b) foundation-only at HALT recovery; re-evaluation triggers DOCUMENT path; no halt)
notes: |
  Markdown-agents shape + HIPAA regulatory exposure. Operator initially on `not_offered` path (no transition fired since shape is markdown). Stop-condition HALT fires at pre-step-05; operator picks (b) foundation-only at the halt recovery prompt; capability-based stop conditions now evaluate under foundation-only mode and fire DOCUMENT path (not HALT) for conditions 1-3. Compliance gap entry lands in `technical_architecture.md` at step 15.
---

# Fixture fom04 — markdown-agents + HIPAA + foundation-only DOCUMENT path

## Synthetic operator inputs

Source-shape inputs derived from `wizard/test_fixtures/shape_detection/sc01-hipaa-markdown-halt.md`.

**Initial state:** shape `markdown-agents` with HIGH confidence; `fallback_mode_offered: not_offered`.

**At pre-step-05 stop-condition evaluation:** HIPAA condition fires per `wizard/shape_detection.md` § 8.3 condition 1 (`regulatory_exposure.hipaa_applicable == yes` AND `control_matrix_active.audit_trail_crud != enforced`).

**HALT path (2a) fires** per `_pre_step_05_recheck.md` Step 2a — wizard says verbatim halt message + offers operator (a) save-and-exit OR (b) change-the-shape-and-re-evaluate.

**Operator picks (b)** at halt recovery prompt. Per `_pre_step_05_recheck.md` Step 2a final paragraph: wizard offers operator to switch to foundation-only mode (since loop-back-to-shape-probes is out of a prior slice scope at the time `_pre_step_05_recheck.md` was authored). Operator confirms foundation-only.

`shape_hypothesis.fallback_mode_offered` updates to `foundation-only`. Re-evaluation of conditions under foundation-only mode: per `_pre_step_05_recheck.md` Step 2b, conditions 1-3 follow DOCUMENT path (no HALT); compliance gap is recorded in staging.

## Expected staging-file state after pre-step-05 re-check

```yaml
stop_conditions:
  evaluated_at: 05_pre_vision
  fired: [1]
  halted: false
  documented_in_foundation: [1]

shape_hypothesis:
  fallback_mode_offered: foundation-only
  recheck_log:
    - step: 05
      outcome: documented_in_foundation
      stop_conditions_recorded: [1]
```

## Expected per-step entry-guard branching

Per `_foundation_only_mode_gate.md` § 2 derivation rule (after operator's foundation-only choice):

- `fallback_mode_offered: foundation-only`
- `produce_foundation_docs: true`
- `produce_system_implementation: false`
- `capture_implementation_inputs: true`
- `honest_characterization_disclosure: foundation_only`

## Expected artifacts at step 15 close

Same 7 files produced as fom01 — WITH ONE DIFFERENCE in `technical_architecture.md`:

`technical_architecture.md` includes a § "Regulatory & compliance gaps (foundation-only mode)" section per `_foundation_only_mode_gate.md` § 6, with ONE gap entry:

```markdown
### Gap: HIPAA

**Status:** documented (foundation-only mode)
**Framework:** HIPAA
**Capability gap:** HIPAA audit trail requires `enforced` audit_trail_crud capability; markdown-agents-on-Claude-Code provides `advisory` only. (Read from staging `control_matrix_active.audit_trail_crud`.)
**Recommended resolution path:** Implementation in a shape supporting enforced audit trail (e.g., python-service-with-database, multi-user-datastore) required before HIPAA-bound data handling.
```

Same SKIP list as fom01.

## Expected CLOSE-13 closing message

Identical to fom01 verbatim closing message. Closing acknowledges the regulatory gap surface via `next_steps.md` which mentions "any regulatory/compliance gaps identified at pre-step-05 re-check."

## Replay outcome

PASS criterion: 7 files produced + § "Regulatory & compliance gaps (foundation-only mode)" section appears in `technical_architecture.md` with HIPAA entry + no implementation files produced + no git init.

FAIL criterion: any of the above missed, OR the § "Regulatory & compliance gaps (foundation-only mode)" header is missing or empty.

**Key behavior exercised:** DOCUMENT-path integration from `_pre_step_05_recheck.md` Step 2b feeding into `_foundation_only_mode_gate.md` § 6 at step 15 close. This is the cross-mechanism integration that a prior slice specified the contract for + a prior slice implements the consumer side.
