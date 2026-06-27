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
    get_contract,
    get_verifier,
    accepted_verifier_ids,
)


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


if __name__ == "__main__":
    unittest.main()
