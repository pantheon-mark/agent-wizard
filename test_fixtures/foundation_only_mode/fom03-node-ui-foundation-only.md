---
fixture_id: fom03-node-ui-foundation-only
schema_version: fixture-replay-v1
fixture_class: foundation-only-mode
source_shape: node-ui
source_fixture: s04-node-ui-clean
mode: foundation-only
expected_unsupported_shape_transition: step_01
expected_halt: false
notes: Operator chooses (b) foundation-only at the step-01 unsupported-shape transition. Wizard proceeds with foundation-doc-only mode through steps 05-15.
---

# Fixture fom03 — node-ui + foundation-only

## Synthetic operator inputs

Source-shape inputs derived from `wizard/test_fixtures/shape_detection/s04-node-ui-clean.md`.

**At step-01 unsupported-shape transition:** operator picks **(b) foundation-only**.

`shape_hypothesis.fallback_mode_offered` updates to `foundation-only` per `wizard/shape_detection.md` § 6.

## Expected per-step entry-guard branching

Per `wizard/interview/_foundation_only_mode_gate.md` § 2 derivation rule — identical to fom01:

- `fallback_mode_offered: foundation-only`
- `produce_foundation_docs: true`
- `produce_system_implementation: false`
- `capture_implementation_inputs: true`
- `honest_characterization_disclosure: foundation_only`

## Expected artifacts at step 15 close

Identical to fom01 expected-artifacts list.

## Expected CLOSE-13 closing message

Identical to fom01 verbatim closing message, with `[SHAPE]` substituted as `node-ui` in `next_steps.md`.

## Replay outcome

Same PASS / FAIL criterion as fom01. Third coverage point for shape-agnosticism of the foundation-only-true branch.
