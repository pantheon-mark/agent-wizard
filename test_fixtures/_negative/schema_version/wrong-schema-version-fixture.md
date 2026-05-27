---
fixture_id: wrong-schema-version-fixture
schema_version: fixture-replay-v99
fixture_class: shape
target_shape: markdown-agents
expected_confidence: high
expected_emit_step: 01
expected_halt: false
notes: |
  NEGATIVE-TEST FIXTURE per a prior slice. Deliberately declares schema_version
  fixture-replay-v99 (non-existent / wrong-pack-version). Validator MUST FAIL on this
  fixture with a "schema_version mismatch" error. Used by `tools/replay_fixtures.py
  --include-negative` to verify the fail-closed schema-version check actually fails on
  wrong schema_version (per advisor an advisor finding + a tracked open question narrow fold-in).
---

# Negative-test fixture — wrong schema_version

This fixture is structurally valid per the `shape` fixture_class schema EXCEPT it declares `schema_version: fixture-replay-v99` instead of the canonical expected `fixture-replay-v1`. The validator's fail-closed schema-version check (per a prior slice) MUST FAIL on this fixture with a version-mismatch error message.

## Synthetic operator inputs

(none — fixture exists solely to exercise schema-version fail-closed check; not a real shape-detection scenario)
