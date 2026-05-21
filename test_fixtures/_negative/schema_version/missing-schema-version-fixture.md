---
fixture_id: missing-schema-version-fixture
fixture_class: shape
target_shape: markdown-agents
expected_confidence: high
expected_emit_step: 01
expected_halt: false
notes: |
  NEGATIVE-TEST FIXTURE per a prior slice Decision H § A.8. Deliberately omits the schema_version field.
  Validator MUST FAIL on this fixture with a "required field schema_version missing" error.
  Used by `tools/replay_fixtures.py --include-negative` to verify the fail-closed schema-version
  check actually fails on missing schema_version (per advisor an advisor finding + a tracked open question narrow fold-in).
---

# Negative-test fixture — missing schema_version

This fixture is structurally valid per the `shape` fixture_class schema EXCEPT it omits the required `schema_version` frontmatter field. The validator's fail-closed schema-version check (a prior slice § A.3 + Decision H § A.8) MUST FAIL on this fixture.

## Synthetic operator inputs

(none — fixture exists solely to exercise schema-version fail-closed check; not a real shape-detection scenario)
