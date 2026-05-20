---
fixture_id: fom02-claude-skills-foundation-only
schema_version: fixture-replay-v1
fixture_class: foundation-only-mode
source_shape: claude-skills
source_fixture: s03-claude-skills-clean
mode: foundation-only
expected_unsupported_shape_transition: step_01
expected_halt: false
notes: Operator chooses (b) foundation-only at the step-01 unsupported-shape transition. Wizard proceeds with foundation-doc-only mode through steps 05-15.
---

# Fixture fom02 — claude-skills + foundation-only

## Synthetic operator inputs

Source-shape inputs derived from `wizard/test_fixtures/shape_detection/s03-claude-skills-clean.md`.

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

Identical to fom01 expected-artifacts list (same 7 produced; same skip list; same not-initialized; same not-generated).

## Expected CLOSE-13 closing message

Identical to fom01 verbatim closing message, with `[SHAPE]` substituted as `claude-skills` in `next_steps.md`.

## Replay outcome

Same PASS / FAIL criterion as fom01. Tests that the same foundation-only-mode behavior applies regardless of the specific non-markdown shape (claude-skills vs python-service); confirms gate-module derivation is shape-agnostic in the foundation-only-true branch.
