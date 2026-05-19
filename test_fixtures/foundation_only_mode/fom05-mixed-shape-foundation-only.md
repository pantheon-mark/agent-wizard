---
fixture_id: fom05-mixed-shape-foundation-only
fixture_class: foundation-only-mode
source_shape: mixed
source_fixture: s07-mixed-shapes
mode: foundation-only
expected_unsupported_shape_transition: step_01_or_02
expected_halt: false
notes: Mixed-shape input (operator describes a system with multiple shape characteristics — e.g., markdown-agents-with-Python-service-component). Classifier emits `mixed` shape. Operator picks (b) foundation-only at unsupported-shape transition. Capability-based stop conditions evaluate against weakest-path-across-components per `wizard/shape_detection.md` § 8.3 mixed-shape handling.
---

# Fixture fom05 — mixed shape + foundation-only

## Synthetic operator inputs

Source-shape inputs derived from `wizard/test_fixtures/shape_detection/s07-mixed-shapes.md`.

**At unsupported-shape transition:** operator picks **(b) foundation-only**.

`shape_hypothesis.fallback_mode_offered` updates to `foundation-only`.

## Expected per-step entry-guard branching

Per `_foundation_only_mode_gate.md` § 2 derivation rule:

- `fallback_mode_offered: foundation-only`
- `produce_foundation_docs: true`
- `produce_system_implementation: false`
- `capture_implementation_inputs: true`
- `honest_characterization_disclosure: foundation_only`

Capability-based stop conditions at pre-step-05 evaluate against `control_matrix_active` populated for mixed shape (weakest-path-across-components per `wizard/shape_detection.md` § 8.3). If any compliance gap is identified, DOCUMENT-path integration fires per fom04 pattern.

## Expected artifacts at step 15 close

Same 7 files produced as fom01. If regulatory exposure surfaces compliance gaps during pre-step-05 evaluation, § "Regulatory & compliance gaps (foundation-only mode)" appears in `technical_architecture.md` per fom04 pattern.

`next_steps.md` substitutes `[SHAPE]` as `mixed` and acknowledges that the mixed shape may have multiple component-implementation paths forward — direct Claude Code build per component, OR wait for v2 multi-shape support.

## Expected CLOSE-13 closing message

Identical to fom01 verbatim closing message.

## Replay outcome

Same PASS / FAIL criterion as fom01 (+ fom04-style gap entry check if compliance gaps surface).

**Key behavior exercised:** mixed-shape weakest-path-across-components consumption in foundation-only mode. v0 emits a single `control_matrix_active` block (weakest path); v1+ may add per-component matrix blocks per S2.1 handoff contract § 5 "What is NOT in v0." Current S2.2 implementation handles the v0 weakest-path emission correctly.
