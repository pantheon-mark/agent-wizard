"""Tests for capability_descriptor_registry (B1-2, NET-NEW): the two renderings of the
capability-descriptor projection over EXTERNAL_DEPENDENCY_IDENTITY's typed descriptor fields
(B1-1). Pins: the machine-readable entry schema (the cross-task contract for B1-4 / B1-5), the
fail-safe risk_class resolution (never read_only_local by omission), the accepted:false default,
the descriptor-bearing inclusion rule, fail-closed parse, markdown-rendering shape, determinism,
and derivation_inputs_for.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_descriptor_registry as cdr  # type: ignore  # noqa: E402
import dependency_projection as dp  # type: ignore  # noqa: E402


def _dep(id_="d1", name="Dep", **extra):
    row = {"id": id_, "name": name, "type": "Unknown", "roles": ["boundary_output"]}
    row.update(extra)
    return row


def _json(rows):
    return json.dumps(rows)


class DerivationInputsTest(unittest.TestCase):
    def test_registry_field_reads_only_identity(self):
        self.assertEqual(cdr.derivation_inputs_for(cdr.REGISTRY_FIELD), [dp.IDENTITY_FIELD])

    def test_markdown_field_reads_only_identity(self):
        self.assertEqual(cdr.derivation_inputs_for(cdr.MARKDOWN_FIELD), [dp.IDENTITY_FIELD])

    def test_unknown_field_fails_closed(self):
        with self.assertRaises(cdr.CapabilityDescriptorRegistryError):
            cdr.derivation_inputs_for("NOPE")


class InclusionRuleTest(unittest.TestCase):
    """A dependency is entered iff it carries >=1 of the five descriptor fields."""

    def test_dependency_with_no_descriptor_fields_is_excluded(self):
        rows = [_dep("bare", "Bare Data Source")]
        entries = cdr.build_descriptor_entries(_json(rows))
        self.assertEqual(entries, [])

    def test_dependency_with_only_action_class_is_included(self):
        rows = [_dep("d1", "Mailer", action_class="send_execute")]
        entries = cdr.build_descriptor_entries(_json(rows))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "d1")

    def test_dependency_with_only_blast_radius_cap_is_included(self):
        rows = [_dep("d1", "Mailer", blast_radius_cap=50)]
        entries = cdr.build_descriptor_entries(_json(rows))
        self.assertEqual(len(entries), 1)

    def test_mixed_deps_only_descriptor_bearing_ones_project(self):
        rows = [
            _dep("bare", "Bare Data Source"),
            _dep("mailer", "Mailer", action_class="send_execute", risk_class="irreversible_external"),
        ]
        entries = cdr.build_descriptor_entries(_json(rows))
        ids = [e["id"] for e in entries]
        self.assertEqual(ids, ["mailer"])


class SchemaTest(unittest.TestCase):
    """The machine-readable entry: EXACTLY these keys (the cross-task contract)."""

    def test_entry_has_exactly_the_contract_keys(self):
        rows = [_dep("d1", "Mailer", action_class="send_execute", risk_class="irreversible_external",
                     recovery_profile_ref="rp-1", declared_test_target="dry_run", blast_radius_cap=10)]
        entries = cdr.build_descriptor_entries(_json(rows))
        self.assertEqual(set(entries[0]), set(cdr.ENTRY_KEYS))

    def test_entry_values_pass_through_from_identity(self):
        rows = [_dep("d1", "Mailer", action_class="send_execute", risk_class="irreversible_external",
                     recovery_profile_ref="rp-1", declared_test_target="dry_run", blast_radius_cap=10)]
        e = cdr.build_descriptor_entries(_json(rows))[0]
        self.assertEqual(e["id"], "d1")
        self.assertEqual(e["name"], "Mailer")
        self.assertEqual(e["action_class"], "send_execute")
        self.assertEqual(e["risk_class"], "irreversible_external")
        self.assertEqual(e["recovery_profile_ref"], "rp-1")
        self.assertEqual(e["declared_test_target"], "dry_run")
        self.assertEqual(e["blast_radius_cap"], 10)

    def test_absent_optional_fields_are_none_not_fabricated(self):
        rows = [_dep("d1", "Mailer", action_class="send_execute")]  # risk_class etc. absent
        e = cdr.build_descriptor_entries(_json(rows))[0]
        self.assertIsNone(e["recovery_profile_ref"])
        self.assertIsNone(e["declared_test_target"])
        self.assertIsNone(e["blast_radius_cap"])

    def test_accepted_always_defaults_false(self):
        rows = [_dep("d1", "Mailer", action_class="delete")]
        e = cdr.build_descriptor_entries(_json(rows))[0]
        self.assertIs(e["accepted"], False)

    def test_accepted_false_even_when_risk_class_is_the_safe_class(self):
        rows = [_dep("d1", "Reader", action_class="read_only", risk_class=dp.READ_ONLY_LOCAL)]
        e = cdr.build_descriptor_entries(_json(rows))[0]
        self.assertIs(e["accepted"], False)


class FailSafeRiskClassTest(unittest.TestCase):
    """F-28 regression pin: risk_class in the registry is ALWAYS fail-safe-resolved, never the
    raw absent/unknown value, and never silently lands on read_only_local by omission."""

    def test_absent_risk_class_resolves_to_fail_safe_not_raw_absence(self):
        rows = [_dep("d1", "Deleter", action_class="delete")]  # no risk_class at all
        e = cdr.build_descriptor_entries(_json(rows))[0]
        self.assertEqual(e["risk_class"], dp.FAIL_SAFE_RISK_CLASS)

    def test_unknown_risk_class_resolves_to_fail_safe(self):
        rows = [_dep("d1", "Deleter", action_class="delete", risk_class="totally_made_up")]
        # parse_identity validates risk_class at parse time and would normally reject this,
        # so build the row directly (bypassing JSON validation) to exercise the resolver's
        # own defense-in-depth for a row that reached it without going through parse_identity.
        e = {"id": "d1", "name": "Deleter", "action_class": "delete", "risk_class": "totally_made_up"}
        self.assertEqual(dp.resolve_risk_class(e), dp.FAIL_SAFE_RISK_CLASS)

    def test_regression_never_resolves_absent_or_unknown_to_read_only_local(self):
        for rows in (
            [_dep("d1", "Deleter", action_class="delete")],
            [_dep("d1", "Deleter", action_class="delete", risk_class="reversible_external")],
        ):
            entries = cdr.build_descriptor_entries(_json(rows))
            for e in entries:
                if e["action_class"] != "read_only":
                    self.assertNotEqual(
                        e["risk_class"], dp.READ_ONLY_LOCAL,
                        f"entry {e!r} must never silently resolve to read_only_local",
                    )

    def test_explicit_read_only_local_is_honored_not_overridden(self):
        rows = [_dep("d1", "Reader", action_class="read_only", risk_class=dp.READ_ONLY_LOCAL)]
        e = cdr.build_descriptor_entries(_json(rows))[0]
        self.assertEqual(e["risk_class"], dp.READ_ONLY_LOCAL)


class FailClosedParseTest(unittest.TestCase):
    def test_malformed_json_raises(self):
        with self.assertRaises(dp.DependencyProjectionError):
            cdr.build_descriptor_entries("not json")

    def test_non_array_raises(self):
        with self.assertRaises(dp.DependencyProjectionError):
            cdr.build_descriptor_entries(json.dumps({"id": "d1"}))

    def test_malformed_action_class_raises(self):
        rows = [_dep("d1", "Mailer", action_class="teleport")]
        with self.assertRaises(dp.DependencyProjectionError):
            cdr.build_descriptor_entries(_json(rows))

    def test_malformed_blast_radius_cap_raises(self):
        rows = [_dep("d1", "Mailer", blast_radius_cap=-1)]
        with self.assertRaises(dp.DependencyProjectionError):
            cdr.build_descriptor_entries(_json(rows))

    def test_error_is_never_silently_swallowed_into_an_empty_registry(self):
        """A capability with a malformed field must raise, not silently drop out of the set."""
        rows = [_dep("d1", "Mailer", risk_class="not_a_real_class")]
        with self.assertRaises(dp.DependencyProjectionError):
            cdr.build_descriptor_entries(_json(rows))


class JsonRenderTest(unittest.TestCase):
    def test_render_is_valid_json_array_of_entries(self):
        rows = [_dep("d1", "Mailer", action_class="send_execute")]
        text = cdr.render_descriptor_registry_json(_json(rows))
        parsed = json.loads(text)
        self.assertIsInstance(parsed, list)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["id"], "d1")

    def test_render_ends_with_trailing_newline(self):
        text = cdr.render_descriptor_registry_json(_json([_dep("d1", "Mailer", action_class="notify")]))
        self.assertTrue(text.endswith("\n"))

    def test_empty_registry_renders_empty_array(self):
        text = cdr.render_descriptor_registry_json(_json([_dep("bare", "Bare")]))
        self.assertEqual(json.loads(text), [])

    def test_render_is_byte_identical_across_runs(self):
        rows = [_dep("d1", "Mailer", action_class="send_execute", risk_class="irreversible_external")]
        a = cdr.render_descriptor_registry_json(_json(rows))
        b = cdr.render_descriptor_registry_json(_json(rows))
        self.assertEqual(a, b)


class MarkdownProjectionTest(unittest.TestCase):
    def test_unknown_field_rejected(self):
        with self.assertRaises(cdr.CapabilityDescriptorRegistryError):
            cdr.project("NOPE", _json([]))

    def test_zero_dependencies_gives_empty_body(self):
        self.assertEqual(cdr.project(cdr.MARKDOWN_FIELD, _json([])), "")

    def test_no_descriptor_bearing_dependency_gives_empty_body(self):
        rows = [_dep("bare", "Bare Data Source")]
        self.assertEqual(cdr.project(cdr.MARKDOWN_FIELD, _json(rows)), "")

    def test_row_contains_name_and_resolved_risk_class(self):
        rows = [_dep("d1", "Mailer", action_class="send_execute")]  # risk_class absent
        body = cdr.project(cdr.MARKDOWN_FIELD, _json(rows))
        self.assertIn("Mailer", body)
        self.assertIn("send_execute", body)
        self.assertIn(dp.FAIL_SAFE_RISK_CLASS, body)  # fail-safe resolved, shown in the row

    def test_accepted_column_reads_no_at_b1(self):
        rows = [_dep("d1", "Mailer", action_class="notify")]
        body = cdr.project(cdr.MARKDOWN_FIELD, _json(rows))
        self.assertTrue(body.strip().endswith("| No |"))

    def test_absent_optional_fields_render_as_readable_placeholders_not_none(self):
        rows = [_dep("d1", "Mailer", action_class="notify")]
        body = cdr.project(cdr.MARKDOWN_FIELD, _json(rows))
        self.assertNotIn("None", body)

    def test_row_count_matches_descriptor_bearing_dependency_count(self):
        rows = [
            _dep("bare", "Bare Data Source"),
            _dep("d1", "Mailer", action_class="notify"),
            _dep("d2", "Deleter", action_class="delete", risk_class="irreversible_external"),
        ]
        body = cdr.project(cdr.MARKDOWN_FIELD, _json(rows))
        self.assertEqual(len(body.splitlines()), 2)

    def test_byte_identical_across_runs(self):
        rows = [_dep("d1", "Mailer", action_class="notify")]
        a = cdr.project(cdr.MARKDOWN_FIELD, _json(rows))
        b = cdr.project(cdr.MARKDOWN_FIELD, _json(rows))
        self.assertEqual(a, b)


class BackwardCompatTest(unittest.TestCase):
    """Importing/using this module must not change dependency_projection's existing surfaces."""

    def test_dependency_projection_projections_unaffected(self):
        identity = _json([
            {"id": "g", "name": "Sheet", "type": "Spreadsheet", "roles": ["boundary_input"]},
        ])
        body = dp.project("INPUT_TYPE_INVENTORY", identity, "[]")
        self.assertIn("Sheet", body)


# ---------------------------------------------------------------------------
# Base declared descriptors (B2-T2)
# ---------------------------------------------------------------------------
#
# Cross-tree imports of external_write's coverage_gate / write_gate mirror the precedent already
# established by test_external_write_contracts.test_risk_classes_constant_matches_build_side_
# vocabulary: a TEST file in wizard/scripts/lib may import wizard/agents/lib (the direction
# external_write itself may never import — D-B1-a).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.contracts import OPERATION_CONTRACTS  # type: ignore  # noqa: E402
from external_write.coverage_gate import (  # type: ignore  # noqa: E402
    evaluate_coverage_gate,
    _is_guarded_mutator,
    _effective_contract_risk_class,
)
from external_write.write_gate import _covering_entry  # type: ignore  # noqa: E402
from external_write.operations import Operation  # type: ignore  # noqa: E402


class BaseDeclaredDescriptorsSchemaTest(unittest.TestCase):
    def test_every_entry_has_exactly_the_entry_keys(self):
        for e in cdr.base_declared_descriptors():
            self.assertEqual(set(e.keys()), set(cdr.ENTRY_KEYS))

    def test_every_entry_is_unaccepted(self):
        for e in cdr.base_declared_descriptors():
            self.assertIs(e["accepted"], False)

    def test_id_and_name_carry_the_reserved_prefix(self):
        for e in cdr.base_declared_descriptors():
            self.assertTrue(e["id"].startswith(cdr.BASE_DESCRIPTOR_ID_PREFIX), e["id"])
            self.assertTrue(e["name"].startswith(cdr.BASE_DESCRIPTOR_ID_PREFIX), e["name"])

    def test_deterministic_across_calls(self):
        self.assertEqual(cdr.base_declared_descriptors(), cdr.base_declared_descriptors())

    def test_delete_record_risk_class_is_represented(self):
        risk_classes = {e["risk_class"] for e in cdr.base_declared_descriptors()}
        self.assertIn("irreversible_external", risk_classes)

    def test_delete_record_action_class_is_delete(self):
        entries = {e["risk_class"]: e for e in cdr.base_declared_descriptors()}
        self.assertEqual(entries["irreversible_external"]["action_class"], "delete")


class BaseDeclaredDescriptorsCoverageTest(unittest.TestCase):
    """The hard requirement (B2-T2 brief item 2): for every guarded op_kind in the REAL
    OPERATION_CONTRACTS registry, the base descriptor set includes a DECLARED covering
    descriptor of its effective risk class, so evaluate_coverage_gate PASSES on the base set
    alone with a clean scan — a fresh writes-back system with zero operator-declared
    capabilities still passes coverage."""

    def test_base_set_alone_passes_coverage_gate_with_clean_scan(self):
        decision = evaluate_coverage_gate(
            scan_violations=[], descriptor_set=cdr.base_declared_descriptors())
        self.assertTrue(decision.passed, decision.failures)
        self.assertEqual(decision.failures, [])

    def test_every_guarded_op_kind_has_a_covering_base_entry(self):
        base = cdr.base_declared_descriptors()
        base_risk_classes = {e["risk_class"] for e in base}
        for op_kind, contract in OPERATION_CONTRACTS.items():
            if not _is_guarded_mutator(contract):
                continue
            rc = _effective_contract_risk_class(contract)
            self.assertIn(rc, base_risk_classes,
                          f"guarded op_kind {op_kind!r} (risk_class {rc!r}) has no covering "
                          "base declared descriptor")

    def test_non_guarded_op_kinds_need_no_base_entry(self):
        # Sanity: the base set does not manufacture coverage for ops that need none (status ops).
        base = cdr.base_declared_descriptors()
        base_risk_classes = {e["risk_class"] for e in base}
        for op_kind in ("set_status", "complete_tasks", "update_due_date",
                        "add_note", "set_priority"):
            contract = OPERATION_CONTRACTS[op_kind]
            self.assertFalse(_is_guarded_mutator(contract), op_kind)


class BaseDeclaredDescriptorsSurfaceJoinSafetyTest(unittest.TestCase):
    """A base entry's reserved id/name must never join against a real live surface at runtime —
    even in the hypothetical where a base entry were `accepted`. Base entries are never emitted
    accepted:true by this producer; this test asserts the surface-join safety independently of
    that fact, by forcing accepted=True on a copy for the probe."""

    def test_base_entry_never_covers_a_realistic_live_surface(self):
        for base_entry in cdr.base_declared_descriptors():
            forced = dict(base_entry, accepted=True)  # hypothetical only — never real
            for surface in ("google_sheets", "gmail", "airtable", "notion", "salesforce", ""):
                op = Operation(surface=surface, object_id="obj:1", field="__record__",
                               new_value="<x>", op_kind="delete_record", batch_id="b1")
                covering = _covering_entry([forced], op, base_entry["risk_class"])
                self.assertIsNone(
                    covering,
                    f"base entry {base_entry['id']!r} must never cover real surface {surface!r}")


if __name__ == "__main__":
    unittest.main()
