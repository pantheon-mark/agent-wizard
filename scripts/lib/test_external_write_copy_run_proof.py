import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.copy_run_proof import (  # noqa: E402
    COPY_RUN_PROOF_SCHEMA,
    DURABILITY_ACTIONS,
    validate_copy_run_proof,
    ProofResult,
)
from external_write.proof_hash import SHA256_HEX_LEN  # noqa: E402
from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA  # noqa: E402


def _verification():
    return {
        "schema": POSTWRITE_VERIFICATION_SCHEMA,
        "verification_mode": "prestate_snapshot_diff",
        "claim_strength": "verified",
        "verifier_id": "prestate_snapshot_diff_v1",
        "source_lineage": {
            "pre_write_sources": ["prewrite_csv_backup"],
            "post_write_sources": ["live_surface_read"],
            # Must cover the registry's forbidden_verification_inputs for this verifier.
            "forbidden_sources": [
                "writer_generated_id_map",
                "live_id_column_as_truth",
                "apply_report",
            ],
        },
        "invariant_checked": "rows stable",
        "evidence_ref": "agents/handoffs/.ev.txt",
    }


def _proof(op_kind="set_status", durability=None):
    return {
        "schema": COPY_RUN_PROOF_SCHEMA,
        "operation_id": "op-001",
        "op_kind": op_kind,
        "data_class": "estate_tracker_rows",
        "copy_source_ref": "copies/estate_copy.csv",
        "prestate_snapshot_ref": "copies/estate_copy.prestate.csv",
        "copy_apply_proof": {
            "apply_receipt_ref": "agents/handoffs/.apply_receipt.json",
            "apply_verification": _verification(),
        },
        "copy_undo_proof": {
            "undo_receipt_ref": "agents/handoffs/.undo_receipt.json",
            "undo_verification": _verification(),
        },
        "durability_checks": [] if durability is None else durability,
        "accepted_for_live_use": True,
        "implementation_hash": "a" * SHA256_HEX_LEN,
        "contract_hash": "b" * SHA256_HEX_LEN,
    }


class TestCopyRunProof(unittest.TestCase):
    def test_valid_non_binding_proof_passes(self):
        r = validate_copy_run_proof(_proof())
        self.assertIsInstance(r, ProofResult)
        self.assertTrue(r.ok, r.reason)

    def test_missing_proof_fails(self):
        self.assertFalse(validate_copy_run_proof({}).ok)

    def test_wrong_schema_fails(self):
        p = _proof(); p["schema"] = "x"
        self.assertFalse(validate_copy_run_proof(p).ok)

    def test_missing_field_fails(self):
        p = _proof(); del p["copy_undo_proof"]
        self.assertFalse(validate_copy_run_proof(p).ok)

    def test_apply_verification_must_pass_clause_a(self):
        p = _proof()
        p["copy_apply_proof"]["apply_verification"]["source_lineage"][
            "post_write_sources"] = ["apply_report"]
        r = validate_copy_run_proof(p)
        self.assertFalse(r.ok)
        self.assertIn("apply_report", r.reason)

    def test_undo_verification_must_pass_clause_a(self):
        p = _proof()
        p["copy_undo_proof"]["undo_verification"]["claim_strength"] = "verified"
        p["copy_undo_proof"]["undo_verification"]["evidence_ref"] = "operator_attested"
        self.assertFalse(validate_copy_run_proof(p).ok)

    def test_missing_undo_receipt_ref_fails(self):
        p = _proof(); p["copy_undo_proof"]["undo_receipt_ref"] = ""
        self.assertFalse(validate_copy_run_proof(p).ok)

    def test_non_binding_op_must_have_empty_durability(self):
        p = _proof(durability=[{"action": "sort", "binding_survived": True}])
        # set_status does NOT introduce persistent binding -> durability must be []
        self.assertFalse(validate_copy_run_proof(p).ok)

    def test_durability_actions_constant(self):
        self.assertEqual(DURABILITY_ACTIONS,
                         ("sort", "filter", "insert", "delete", "move"))

    def test_binding_op_requires_nonempty_surviving_durability(self):
        import external_write.contracts as contracts
        from external_write.contracts import OperationContract
        original = contracts.OPERATION_CONTRACTS["set_status"]
        contracts.OPERATION_CONTRACTS["set_status"] = OperationContract(
            op_kind="set_status", writes=("Status",), produces=(),
            dependency_set=original.dependency_set, verifier_set=original.verifier_set,
            introduces_persistent_binding=True,
        )
        try:
            # empty durability on a binding op -> fail
            self.assertFalse(validate_copy_run_proof(_proof(durability=[])).ok)
            # surviving durability on a binding op -> pass
            ok = _proof(durability=[
                {"action": "sort", "binding_survived": True},
                {"action": "insert", "binding_survived": True},
            ])
            self.assertTrue(validate_copy_run_proof(ok).ok)
            # a broken binding -> fail
            bad = _proof(durability=[{"action": "delete", "binding_survived": False}])
            self.assertFalse(validate_copy_run_proof(bad).ok)
        finally:
            contracts.OPERATION_CONTRACTS["set_status"] = original


if __name__ == "__main__":
    unittest.main()
