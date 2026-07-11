"""Tests for the generalized Operation model and versioned canonicalization.

Task 1 of the external-write write-gate generalization: the Operation
dataclass gains a `schema` field so later tasks can gate verb-shaped vendor
APIs (operation-v2-action) alongside today's spreadsheet-style field writes
(operation-v1-field), plus an EffectUnit dataclass for blast-radius counting.

The critical invariant under test: operation-v1-field canonicalization and
digest computation are BYTE-IDENTICAL to the pre-generalization code. Existing
digest-bound approval receipts and released-bundle replay depend on this.
The golden fixture below was captured by running the pre-change
`Operation.canonical_repr()` / `Operation.digest()` directly, before any of
this task's edits were made.

This task does not wire dispatch/registry/gate behavior (Task 2) — it only
covers the data model and canonicalization.
"""

import sys
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (the canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import (  # noqa: E402
    Operation,
    EffectUnit,
    SCHEMA_V1_FIELD,
    SCHEMA_V2_ACTION,
    resolve_schema_version,
)


# ---------------------------------------------------------------------------
# Golden fixture — captured from the PRE-CHANGE Operation.canonical_repr() /
# .digest() for a representative legacy field operation. Do not "fix" these
# values to match new output; if they ever need to change, that is a digest
# break for released receipts and must be treated as an incident, not a test
# update.
# ---------------------------------------------------------------------------
_GOLDEN_CANONICAL_REPR = (
    '{"batch_id": "batch-001", "field": "Status", "new_value": "Complete", '
    '"object_id": "sheet:abc123", "op_kind": "set_status", "surface": "google_sheets"}'
)
_GOLDEN_DIGEST = "14b5ee563f89a03debb79e42c9ff92174085faf4d5c43df03bde2904cbce4524"


def _legacy_field_op(**overrides):
    kwargs = dict(
        surface="google_sheets",
        object_id="sheet:abc123",
        field="Status",
        new_value="Complete",
        op_kind="set_status",
        batch_id="batch-001",
    )
    kwargs.update(overrides)
    return Operation(**kwargs)


class TestLegacyFieldSchemaByteIdentical(unittest.TestCase):
    """operation-v1-field must reproduce the exact pre-change bytes."""

    def test_golden_canonical_repr_unchanged(self):
        op = _legacy_field_op()
        self.assertEqual(op.canonical_repr(), _GOLDEN_CANONICAL_REPR)

    def test_golden_digest_unchanged(self):
        op = _legacy_field_op()
        self.assertEqual(op.digest(), _GOLDEN_DIGEST)

    def test_schema_defaults_to_v1_field_when_omitted(self):
        op = _legacy_field_op()
        self.assertEqual(op.schema, SCHEMA_V1_FIELD)

    def test_explicit_v1_field_schema_still_byte_identical(self):
        op = _legacy_field_op(schema=SCHEMA_V1_FIELD)
        self.assertEqual(op.canonical_repr(), _GOLDEN_CANONICAL_REPR)
        self.assertEqual(op.digest(), _GOLDEN_DIGEST)

    def test_v1_field_canonical_repr_ignores_new_optional_fields(self):
        # params / undo_descriptor are v2-only; setting them on a v1-schema
        # op must not perturb the legacy digest.
        op = _legacy_field_op(params={"unused": True}, undo_descriptor="x")
        self.assertEqual(op.canonical_repr(), _GOLDEN_CANONICAL_REPR)
        self.assertEqual(op.digest(), _GOLDEN_DIGEST)


class TestV2ActionSchema(unittest.TestCase):
    """operation-v2-action serializes surface/op_kind/params/undo_descriptor."""

    def _action_op(self, **overrides):
        kwargs = dict(
            surface="asana",
            op_kind="archive_task",
            batch_id="batch-010",
            schema=SCHEMA_V2_ACTION,
            params={"task_gid": "999", "reason": "done"},
            undo_descriptor={"action": "unarchive_task", "task_gid": "999"},
        )
        kwargs.update(overrides)
        return Operation(**kwargs)

    def test_v2_canonical_repr_is_sorted_key_json_of_four_fields(self):
        op = self._action_op()
        expected = (
            '{"op_kind": "archive_task", "params": {"reason": "done", "task_gid": "999"}, '
            '"surface": "asana", "undo_descriptor": {"action": "unarchive_task", "task_gid": "999"}}'
        )
        self.assertEqual(op.canonical_repr(), expected)

    def test_v2_digest_is_sha256_of_canonical_repr(self):
        import hashlib

        op = self._action_op()
        self.assertEqual(
            op.digest(), hashlib.sha256(op.canonical_repr().encode()).hexdigest()
        )

    def test_v2_shape_is_stable_across_construction_order(self):
        op_a = self._action_op()
        op_b = Operation(
            schema=SCHEMA_V2_ACTION,
            undo_descriptor={"action": "unarchive_task", "task_gid": "999"},
            batch_id="batch-010",
            params={"task_gid": "999", "reason": "done"},
            op_kind="archive_task",
            surface="asana",
        )
        self.assertEqual(op_a.canonical_repr(), op_b.canonical_repr())
        self.assertEqual(op_a.digest(), op_b.digest())

    def test_v2_digest_ignores_legacy_field_style_attributes(self):
        # object_id / field / new_value are legacy-only; two v2 ops that
        # differ only in those must still collide (they are excluded from
        # the v2 canonical shape by design).
        op_a = self._action_op(object_id="irrelevant-a", field="irrelevant", new_value=1)
        op_b = self._action_op(object_id="irrelevant-b", field="also-irrelevant", new_value=2)
        self.assertEqual(op_a.canonical_repr(), op_b.canonical_repr())

    def test_v2_digest_changes_when_params_change(self):
        op_a = self._action_op(params={"task_gid": "999", "reason": "done"})
        op_b = self._action_op(params={"task_gid": "999", "reason": "duplicate"})
        self.assertNotEqual(op_a.digest(), op_b.digest())

    def test_v2_op_does_not_require_legacy_field_kwargs(self):
        # Verb-shaped ops must be constructible without dummy object_id/
        # field/new_value values — that is the point of the generalization.
        op = Operation(
            surface="asana",
            op_kind="archive_task",
            batch_id="batch-011",
            schema=SCHEMA_V2_ACTION,
            params={"task_gid": "1"},
            undo_descriptor=None,
        )
        self.assertEqual(op.op_kind, "archive_task")


class TestResolveSchemaVersion(unittest.TestCase):
    """A receipt dict lacking schema_version resolves to operation-v1-field."""

    def test_missing_schema_version_key_resolves_to_v1_field(self):
        receipt = {"approved_operation_digest": "abc", "expires_at": "2026-01-01T00:00:00Z"}
        self.assertEqual(resolve_schema_version(receipt), SCHEMA_V1_FIELD)

    def test_empty_dict_resolves_to_v1_field(self):
        self.assertEqual(resolve_schema_version({}), SCHEMA_V1_FIELD)

    def test_none_resolves_to_v1_field_no_keyerror(self):
        self.assertEqual(resolve_schema_version(None), SCHEMA_V1_FIELD)

    def test_explicit_schema_version_is_passed_through(self):
        receipt = {"schema_version": SCHEMA_V2_ACTION}
        self.assertEqual(resolve_schema_version(receipt), SCHEMA_V2_ACTION)


class TestEffectUnit(unittest.TestCase):
    """EffectUnit: one discrete external mutation, for blast-radius counting."""

    def test_construction_and_field_access(self):
        unit = EffectUnit(unit_id="u1", target_ref="sheet:abc123#Status", undo_ref="prev:Incomplete")
        self.assertEqual(unit.unit_id, "u1")
        self.assertEqual(unit.target_ref, "sheet:abc123#Status")
        self.assertEqual(unit.undo_ref, "prev:Incomplete")

    def test_undo_ref_optional(self):
        unit = EffectUnit(unit_id="u2", target_ref="asana:999")
        self.assertIsNone(unit.undo_ref)

    def test_is_frozen(self):
        import dataclasses

        unit = EffectUnit(unit_id="u3", target_ref="x")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            unit.unit_id = "changed"


if __name__ == "__main__":
    unittest.main()
