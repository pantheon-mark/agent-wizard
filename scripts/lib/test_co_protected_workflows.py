"""Tests for co_protected_workflows (B1-6, NET-NEW): the projected "Registered capability
workflows" section of quality/co-protected-workflows.md. Pins: which risk classes register
(irreversible_external / standing_automation / sensitive_data) vs. which don't
(read_only_local / reversible_external — no over-firing), the fail-safe registration of an
unknown/absent risk_class (F-28, inherited via capability_descriptor_registry), the F-29
standing_automation non-graduating recovery-floor note, derivation_inputs_for, empty-set
behavior, fail-closed parse, determinism, and cross-file risk-class-vocabulary consistency with
dependency_projection.RISK_CLASSES and (where feasible) agents/lib/external_write/contracts.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import co_protected_workflows as cpw  # type: ignore  # noqa: E402
import capability_descriptor_registry as cdr  # type: ignore  # noqa: E402
import dependency_projection as dp  # type: ignore  # noqa: E402
import derived_record as dr  # type: ignore  # noqa: E402

# Cross-tree import (mirrors test_external_write_contracts.py's own sys.path insert) — used only
# by the "feasible" contracts.py consistency check below; not required by any other test here.
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))
from external_write.contracts import OPERATION_CONTRACTS  # type: ignore  # noqa: E402


def _dep(id_="d1", name="Dep", **extra):
    row = {"id": id_, "name": name, "type": "Unknown", "roles": ["boundary_output"]}
    row.update(extra)
    return row


def _json(rows):
    return json.dumps(rows)


class DerivationInputsTest(unittest.TestCase):
    def test_markdown_field_reads_only_identity(self):
        self.assertEqual(cpw.derivation_inputs_for(cpw.MARKDOWN_FIELD), [dp.IDENTITY_FIELD])

    def test_unknown_field_fails_closed(self):
        with self.assertRaises(cpw.CoProtectedWorkflowsError):
            cpw.derivation_inputs_for("NOPE")


class RegistrationRuleTest(unittest.TestCase):
    """Which risk classes register (protection-requiring) vs. which don't (no over-firing)."""

    def test_irreversible_external_is_registered(self):
        rows = [_dep("d1", "Deleter", action_class="delete", risk_class="irreversible_external")]
        entries = cpw.build_registered_workflows(_json(rows))
        self.assertEqual([e["id"] for e in entries], ["d1"])

    def test_standing_automation_is_registered(self):
        rows = [_dep("d1", "Auto-filter", action_class="route", risk_class="standing_automation")]
        entries = cpw.build_registered_workflows(_json(rows))
        self.assertEqual([e["id"] for e in entries], ["d1"])

    def test_sensitive_data_is_registered(self):
        rows = [_dep("d1", "PII store", action_class="retain_archive", risk_class="sensitive_data")]
        entries = cpw.build_registered_workflows(_json(rows))
        self.assertEqual([e["id"] for e in entries], ["d1"])

    def test_read_only_local_is_not_registered(self):
        rows = [_dep("d1", "Reader", action_class="read_only", risk_class=dp.READ_ONLY_LOCAL)]
        entries = cpw.build_registered_workflows(_json(rows))
        self.assertEqual(entries, [])

    def test_reversible_external_is_not_registered(self):
        rows = [_dep("d1", "Status updater", action_class="mutate", risk_class="reversible_external")]
        entries = cpw.build_registered_workflows(_json(rows))
        self.assertEqual(entries, [])

    def test_mixed_set_registers_only_protection_requiring_ones(self):
        rows = [
            _dep("safe1", "Reader", action_class="read_only", risk_class=dp.READ_ONLY_LOCAL),
            _dep("safe2", "Status updater", action_class="mutate", risk_class="reversible_external"),
            _dep("risky1", "Deleter", action_class="delete", risk_class="irreversible_external"),
            _dep("risky2", "Auto-filter", action_class="route", risk_class="standing_automation"),
        ]
        entries = cpw.build_registered_workflows(_json(rows))
        self.assertEqual([e["id"] for e in entries], ["risky1", "risky2"])

    def test_no_descriptor_bearing_dependency_registers_nothing(self):
        rows = [_dep("bare", "Bare Data Source")]
        self.assertEqual(cpw.build_registered_workflows(_json(rows)), [])

    def test_empty_identity_registers_nothing(self):
        self.assertEqual(cpw.build_registered_workflows(_json([])), [])


class FailSafeRegistrationTest(unittest.TestCase):
    """F-28, inherited via capability_descriptor_registry: an unknown/absent risk_class on a
    writer (a dependency that carries a descriptor field but no explicit risk_class) must
    register as protected, never be silently omitted."""

    def test_absent_risk_class_on_a_writer_registers_as_protected(self):
        rows = [_dep("d1", "Mailer", action_class="send_execute")]  # no risk_class at all
        entries = cpw.build_registered_workflows(_json(rows))
        self.assertEqual([e["id"] for e in entries], ["d1"])
        self.assertEqual(entries[0]["risk_class"], dp.FAIL_SAFE_RISK_CLASS)

    def test_fail_safe_resolved_class_is_itself_a_protected_class(self):
        self.assertIn(dp.FAIL_SAFE_RISK_CLASS, cpw.PROTECTED_RISK_CLASSES)


class F29StandingAutomationTest(unittest.TestCase):
    """F-29: a registered standing_automation row states the non-graduating recovery floor."""

    def test_standing_automation_note_states_non_graduating(self):
        note = cpw._PROTECTION_NOTE[cpw.STANDING_AUTOMATION]
        self.assertIn("NON-GRADUATING", note)
        self.assertIn("never", note.lower())

    def test_standing_automation_row_carries_the_floor_note(self):
        rows = [_dep("d1", "Auto-filter", action_class="route", risk_class="standing_automation")]
        body = cpw.project(cpw.MARKDOWN_FIELD, _json(rows))
        self.assertIn("NON-GRADUATING", body)
        self.assertIn("Auto-filter", body)

    def test_non_standing_automation_row_does_not_carry_the_floor_note(self):
        rows = [_dep("d1", "Deleter", action_class="delete", risk_class="irreversible_external")]
        body = cpw.project(cpw.MARKDOWN_FIELD, _json(rows))
        self.assertNotIn("NON-GRADUATING", body)


class MarkdownProjectionTest(unittest.TestCase):
    def test_unknown_field_rejected(self):
        with self.assertRaises(cpw.CoProtectedWorkflowsError):
            cpw.project("NOPE", _json([]))

    def test_empty_identity_gives_empty_body(self):
        self.assertEqual(cpw.project(cpw.MARKDOWN_FIELD, _json([])), "")

    def test_no_registered_capability_gives_empty_body(self):
        rows = [_dep("d1", "Reader", action_class="read_only", risk_class=dp.READ_ONLY_LOCAL)]
        self.assertEqual(cpw.project(cpw.MARKDOWN_FIELD, _json(rows)), "")

    def test_row_contains_name_action_class_and_risk_class(self):
        rows = [_dep("d1", "Deleter", action_class="delete", risk_class="irreversible_external")]
        body = cpw.project(cpw.MARKDOWN_FIELD, _json(rows))
        self.assertIn("Deleter", body)
        self.assertIn("delete", body)
        self.assertIn("irreversible_external", body)

    def test_row_count_matches_registered_count_only(self):
        rows = [
            _dep("safe", "Reader", action_class="read_only", risk_class=dp.READ_ONLY_LOCAL),
            _dep("risky", "Deleter", action_class="delete", risk_class="irreversible_external"),
        ]
        body = cpw.project(cpw.MARKDOWN_FIELD, _json(rows))
        self.assertEqual(len(body.splitlines()), 1)

    def test_byte_identical_across_runs(self):
        rows = [_dep("d1", "Mailer", action_class="send_execute", risk_class="sensitive_data")]
        a = cpw.project(cpw.MARKDOWN_FIELD, _json(rows))
        b = cpw.project(cpw.MARKDOWN_FIELD, _json(rows))
        self.assertEqual(a, b)


class FailClosedParseTest(unittest.TestCase):
    def test_malformed_json_raises(self):
        with self.assertRaises(dp.DependencyProjectionError):
            cpw.build_registered_workflows("not json")

    def test_malformed_risk_class_raises(self):
        rows = [_dep("d1", "Mailer", risk_class="not_a_real_class")]
        with self.assertRaises(dp.DependencyProjectionError):
            cpw.build_registered_workflows(_json(rows))


class RiskClassVocabularyConsistencyTest(unittest.TestCase):
    """The risk classes used here must be the SAME vocabulary as B1-1's RISK_CLASSES (the
    contracts.py deterministic companion mirrors the same vocabulary) — QA prose and
    contracts.py must not diverge."""

    def test_protected_classes_are_a_subset_of_the_shared_vocabulary(self):
        self.assertTrue(cpw.PROTECTED_RISK_CLASSES.issubset(dp.RISK_CLASSES))

    def test_non_registered_classes_are_exactly_the_remaining_vocabulary(self):
        not_registered = dp.RISK_CLASSES - cpw.PROTECTED_RISK_CLASSES
        self.assertEqual(not_registered, {dp.READ_ONLY_LOCAL, "reversible_external"})

    def test_protected_classes_are_exactly_the_three_named_in_the_brief(self):
        self.assertEqual(
            cpw.PROTECTED_RISK_CLASSES,
            {"irreversible_external", "standing_automation", "sensitive_data"},
        )

    def test_every_acceptance_requiring_contract_risk_class_is_registered(self):
        """Where feasible: any op_kind contracts.py marks requires_accepted_phase=True carries
        a risk_class that this projection also registers as protected — QA and the deterministic
        enforcement companion must not diverge on what counts as high-risk."""
        checked_any = False
        for op_kind, contract in OPERATION_CONTRACTS.items():
            if contract.requires_accepted_phase:
                checked_any = True
                self.assertIn(
                    contract.risk_class, cpw.PROTECTED_RISK_CLASSES,
                    f"{op_kind} requires_accepted_phase but risk_class {contract.risk_class!r} "
                    f"is not registered as protected here",
                )
        self.assertTrue(checked_any, "no acceptance-requiring contract found to check against")


class DerivationClassProjectionEnvelopeTest(unittest.TestCase):
    """derivation_class=projection with correct _derivation_inputs and no _source_question_ids
    (mirrors the derived-record contract's DR-5 rule for a projection field), validated directly
    against the canonical derived-record contract."""

    def setUp(self):
        self.contract = dr.load_contract(dr.default_contract_path())
        self.payload_keys = {cpw.MARKDOWN_FIELD, dp.IDENTITY_FIELD}

    def _env(self, **overrides):
        env = {
            "_source": "auto",
            "_derivation_class": "projection",
            "_decision_field": False,
            "_decision_kind": "none",
            "_derivation_inputs": cpw.derivation_inputs_for(cpw.MARKDOWN_FIELD),
        }
        env.update(overrides)
        return env

    def test_valid_projection_envelope_passes(self):
        value = "| Mailer | send_execute | irreversible_external | Has an external effect... |"
        dr.validate_envelope(cpw.MARKDOWN_FIELD, self._env(), value, self.contract, self.payload_keys)

    def test_missing_derivation_inputs_fails_closed(self):
        env = self._env()
        del env["_derivation_inputs"]
        with self.assertRaises(dr.DerivedRecordError):
            dr.validate_envelope(cpw.MARKDOWN_FIELD, env, "some content", self.contract, self.payload_keys)

    def test_carrying_source_question_ids_fails_closed(self):
        env = self._env(_source_question_ids=["DEP-1"])
        with self.assertRaises(dr.DerivedRecordError):
            dr.validate_envelope(cpw.MARKDOWN_FIELD, env, "some content", self.contract, self.payload_keys)

    def test_derivation_inputs_reference_a_known_payload_key(self):
        # DR-8: every _derivation_inputs entry must resolve to a known payload key.
        env = self._env()
        dr.validate_envelope(cpw.MARKDOWN_FIELD, env, "some content", self.contract,
                             {cpw.MARKDOWN_FIELD, dp.IDENTITY_FIELD})


class BackwardCompatTest(unittest.TestCase):
    """Importing/using this module must not change capability_descriptor_registry's or
    dependency_projection's existing surfaces."""

    def test_capability_descriptor_registry_unaffected(self):
        rows = [_dep("d1", "Mailer", action_class="send_execute")]
        entries = cdr.build_descriptor_entries(_json(rows))
        self.assertEqual(len(entries), 1)

    def test_dependency_projection_projections_unaffected(self):
        identity = _json([
            {"id": "g", "name": "Sheet", "type": "Spreadsheet", "roles": ["boundary_input"]},
        ])
        body = dp.project("INPUT_TYPE_INVENTORY", identity, "[]")
        self.assertIn("Sheet", body)


if __name__ == "__main__":
    unittest.main()
