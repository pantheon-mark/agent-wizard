import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.verification_modes import VerificationMode  # noqa: E402
from external_write.contracts import (  # noqa: E402
    VerifierDef,
    SourceLineage,
    OperationContract,
    VERIFIER_REGISTRY,
    OPERATION_CONTRACTS,
    RISK_CLASSES as EXTERNAL_WRITE_RISK_CLASSES,
    get_contract,
    get_verifier,
    accepted_verifier_ids,
)
import dependency_projection as dp  # type: ignore  # noqa: E402


class TestContracts(unittest.TestCase):
    def test_every_op_kind_has_a_contract(self):
        for op_kind in ("set_status", "complete_tasks", "update_due_date",
                        "add_note", "set_priority"):
            self.assertIsInstance(get_contract(op_kind), OperationContract)

    def test_contract_declares_write_and_dependency_sets(self):
        c = get_contract("set_status")
        self.assertEqual(c.op_kind, "set_status")
        self.assertIn("adapters.py", c.dependency_set)
        self.assertIn("verifiers.py", c.dependency_set)
        self.assertTrue(len(c.writes) >= 1)

    def test_verifier_set_references_registered_verifiers(self):
        for op_kind, c in OPERATION_CONTRACTS.items():
            for vid in c.verifier_set:
                self.assertIn(vid, VERIFIER_REGISTRY,
                              f"{op_kind} references unregistered verifier {vid}")

    def test_snapshot_diff_verifier_declares_forbidden_inputs(self):
        v = get_verifier("prestate_snapshot_diff_v1")
        self.assertEqual(v.mode, VerificationMode.PRESTATE_SNAPSHOT_DIFF)
        self.assertIn("writer_generated_id_map",
                      v.source_lineage.forbidden_verification_inputs)
        self.assertIn("apply_report",
                      v.source_lineage.forbidden_verification_inputs)
        self.assertIn("live_id_column_as_truth",
                      v.source_lineage.forbidden_verification_inputs)

    def test_operator_attested_verifier_is_attested_mode(self):
        v = get_verifier("operator_attested_v1")
        self.assertEqual(v.mode, VerificationMode.OPERATOR_ATTESTED)

    def test_accepted_verifier_ids_returns_verifier_set(self):
        self.assertEqual(accepted_verifier_ids("set_status"),
                         get_contract("set_status").verifier_set)

    def test_unknown_op_kind_returns_none(self):
        self.assertIsNone(get_contract("does_not_exist"))
        self.assertIsNone(get_verifier("does_not_exist"))

    def test_status_ops_do_not_introduce_persistent_binding(self):
        self.assertFalse(get_contract("set_status").introduces_persistent_binding)

    # -- B1-3: risk fields ------------------------------------------------

    def test_new_fields_default_non_breaking_when_omitted(self):
        """Constructing an OperationContract without the three new fields must
        preserve pre-B1-3 behavior: reversible_external / not phase-gated / no cap."""
        c = OperationContract(
            op_kind="legacy_shape", writes=("Field",), produces=(),
            dependency_set=("adapters.py",), verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False,
        )
        self.assertEqual(c.risk_class, "reversible_external")
        self.assertFalse(c.requires_accepted_phase)
        self.assertIsNone(c.blast_radius_cap)

    def test_status_ops_are_reversible_external_and_ungated(self):
        for op_kind in ("set_status", "complete_tasks", "update_due_date",
                        "add_note", "set_priority"):
            c = get_contract(op_kind)
            self.assertEqual(c.risk_class, "reversible_external", op_kind)
            self.assertFalse(c.requires_accepted_phase, op_kind)
            self.assertIsNone(c.blast_radius_cap, op_kind)

    def test_risk_classes_constant_matches_build_side_vocabulary(self):
        """external_write.contracts.RISK_CLASSES must never silently diverge from the
        authoritative vocabulary defined in wizard/scripts/lib/dependency_projection.py
        (B1-1). This is the cross-file seam test named in the B1-3 brief."""
        self.assertEqual(set(EXTERNAL_WRITE_RISK_CLASSES), set(dp.RISK_CLASSES))

    def test_delete_record_contract_is_the_first_irreversible_op(self):
        c = get_contract("delete_record")
        self.assertIsInstance(c, OperationContract)
        self.assertEqual(c.op_kind, "delete_record")
        self.assertEqual(c.risk_class, "irreversible_external")
        self.assertTrue(c.requires_accepted_phase)
        self.assertEqual(c.blast_radius_cap, 5)
        self.assertGreater(c.blast_radius_cap, 0)
        self.assertFalse(c.introduces_persistent_binding)
        self.assertEqual(c.verifier_set, ("prestate_snapshot_diff_v1",))
        self.assertTrue(len(c.writes) >= 1)
        self.assertIn("adapters.py", c.dependency_set)

    def test_delete_record_risk_class_is_in_the_mirrored_vocabulary(self):
        self.assertIn(get_contract("delete_record").risk_class, EXTERNAL_WRITE_RISK_CLASSES)

    def test_delete_record_verifier_is_registered(self):
        c = get_contract("delete_record")
        for vid in c.verifier_set:
            self.assertIn(vid, VERIFIER_REGISTRY)


if __name__ == "__main__":
    unittest.main()
