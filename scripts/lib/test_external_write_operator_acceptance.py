"""B2-T6 — end-to-end tests for the operator-acceptance helper
(external_write.operator_acceptance), the deterministic Step-6 step that mints the
operator_acceptance_receipt-v1 from the operator's verbatim confirmation and drives the
acceptance ceremony.

The headline test is the BUILD->LIVE-AUTHORIZATION seam end to end: a real copy_run_proof (real
proof hashes, matching capability_id) + a real minted receipt + the real ceremony must flip the
descriptor, after which the runtime write_gate PERMITS a live write for that surface and still
REFUSES an unaccepted one. No mocks of the units under test.
"""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operator_acceptance import (  # noqa: E402
    record_operator_acceptance,
    OperatorAcceptanceResult,
    DEFAULT_RECEIPT_DIR,
)
from external_write.acceptance_ceremony import OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA  # noqa: E402
from external_write.copy_run_proof import COPY_RUN_PROOF_SCHEMA  # noqa: E402
from external_write.proof_hash import (  # noqa: E402
    compute_contract_hash,
    compute_implementation_hash,
)
from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA  # noqa: E402
from external_write.operations import Operation  # noqa: E402
from external_write.write_gate import (  # noqa: E402
    InvocationLedger,
    load_descriptor_set,
    evaluate_write_gate,
    LIVE_TARGET,
)


PHASE = "phase_02"
OP_KIND = "delete_record"  # irreversible_external; gated; non-binding


def _verification():
    return {
        "schema": POSTWRITE_VERIFICATION_SCHEMA,
        "verification_mode": "prestate_snapshot_diff",
        "claim_strength": "verified",
        "verifier_id": "prestate_snapshot_diff_v1",
        "source_lineage": {
            "pre_write_sources": ["prewrite_csv_backup"],
            "post_write_sources": ["live_surface_read"],
            "forbidden_sources": [
                "writer_generated_id_map", "live_id_column_as_truth", "apply_report",
            ],
        },
        "invariant_checked": "record absent after delete",
        "evidence_ref": "agents/handoffs/.ev.txt",
    }


def _proof(capability_id="google_sheets", op_kind=OP_KIND):
    return {
        "schema": COPY_RUN_PROOF_SCHEMA,
        "operation_id": "op-001",
        "op_kind": op_kind,
        "capability_id": capability_id,
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
        "durability_checks": [],
        "accepted_for_live_use": True,
        "implementation_hash": compute_implementation_hash(op_kind),
        "contract_hash": compute_contract_hash(op_kind),
    }


def _descriptor(id="google_sheets", *, risk_class="irreversible_external", phase_id=PHASE,
                blast_radius_cap=5, accepted=False, action_class="delete"):
    return {
        "id": id, "name": id, "action_class": action_class, "risk_class": risk_class,
        "recovery_profile_ref": None, "declared_test_target": "copy",
        "blast_radius_cap": blast_radius_cap, "accepted": accepted, "phase_id": phase_id,
    }


class OperatorAcceptanceE2ETest(unittest.TestCase):

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.security = self.tmp / "security"
        self.security.mkdir(parents=True, exist_ok=True)
        self.set_path = self.security / "capability_descriptors.json"
        self.proof_path = self.tmp / "proof.json"
        self.receipt_path = self.security / "acceptance_receipts" / "google_sheets.receipt.json"
        self.audit_path = self.security / "capability_acceptance_log.jsonl"

    def tearDown(self):
        self._td.cleanup()

    def _write_set(self, descriptors):
        self.set_path.write_text(json.dumps(descriptors, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")

    def _write_proof(self, proof=None):
        self.proof_path.write_text(json.dumps(proof if proof is not None else _proof()),
                                   encoding="utf-8")

    def _call(self, *, capability_id="google_sheets", phase_id=PHASE,
              operator_confirmation="Yes — I accept this capability for live use.", **kw):
        return record_operator_acceptance(
            capability_id, phase_id, str(self.proof_path), operator_confirmation,
            receipt_path=str(self.receipt_path),
            descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path), **kw)

    def _accepted_flag(self, id):
        for e in json.loads(self.set_path.read_text(encoding="utf-8")):
            if e.get("id") == id:
                return e.get("accepted")
        return None

    # -- The headline end-to-end seam -------------------------------------

    def test_write_gate_permits_live_only_after_real_acceptance(self):
        # Two gated descriptors, both unaccepted. Before acceptance, the live write is refused.
        self._write_set([_descriptor(id="google_sheets"), _descriptor(id="asana")])
        self._write_proof()

        ds_before = load_descriptor_set(str(self.set_path))
        live_op = Operation(surface="google_sheets", object_id="row:1", field="__record__",
                            new_value="<x>", op_kind=OP_KIND, batch_id="b1")
        before = evaluate_write_gate(live_op, target=LIVE_TARGET, descriptor_set=ds_before,
                                     cap_ledger=InvocationLedger())
        self.assertFalse(before.permitted, "live write must be refused BEFORE acceptance")

        # The operator confirms; the helper mints the receipt + drives the ceremony.
        res = self._call()
        self.assertIsInstance(res, OperatorAcceptanceResult)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(self._accepted_flag("google_sheets"), True)
        self.assertEqual(self._accepted_flag("asana"), False)

        # A real receipt was minted on disk, matching the ceremony's schema + verbatim text.
        self.assertTrue(Path(res.receipt_ref).exists())
        receipt = json.loads(Path(res.receipt_ref).read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema"], OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA)
        self.assertEqual(receipt["capability_id"], "google_sheets")
        self.assertEqual(receipt["operator_confirmation"],
                         "Yes — I accept this capability for live use.")

        # AFTER acceptance: write_gate PERMITS the live write for the accepted surface...
        ds_after = load_descriptor_set(str(self.set_path))
        after = evaluate_write_gate(live_op, target=LIVE_TARGET, descriptor_set=ds_after,
                                    cap_ledger=InvocationLedger())
        self.assertTrue(after.permitted, after.refusal)

        # ...and still REFUSES the unaccepted surface (asana never went through acceptance).
        other_op = Operation(surface="asana", object_id="row:1", field="__record__",
                             new_value="<x>", op_kind=OP_KIND, batch_id="b1")
        other = evaluate_write_gate(other_op, target=LIVE_TARGET, descriptor_set=ds_after,
                                    cap_ledger=InvocationLedger())
        self.assertFalse(other.permitted, "unaccepted surface must stay refused")

    # -- Honest capture: never fabricate the operator's yes ---------------

    def test_empty_confirmation_refuses_and_accepts_nothing(self):
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof()
        res = self._call(operator_confirmation="   ")
        self.assertFalse(res.accepted)
        self.assertIsNone(res.acceptance, "ceremony must not even be invoked without a yes")
        self.assertEqual(self._accepted_flag("google_sheets"), False)
        # No receipt was minted for a non-confirmation.
        self.assertFalse(self.receipt_path.exists())

    # -- The helper is not a second authority: ceremony still refuses -----

    def test_proof_for_other_capability_is_refused_by_ceremony(self):
        # A valid proof produced for a DIFFERENT capability must not cross-authorize, even though
        # the helper mints a well-formed receipt: the ceremony asserts proof.capability_id.
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof(_proof(capability_id="asana"))
        res = self._call(capability_id="google_sheets")
        self.assertFalse(res.accepted)
        self.assertIsNotNone(res.acceptance)
        self.assertFalse(res.acceptance.accepted)
        self.assertEqual(self._accepted_flag("google_sheets"), False)

    def test_default_receipt_dir_constant(self):
        self.assertEqual(DEFAULT_RECEIPT_DIR, "security/acceptance_receipts")


if __name__ == "__main__":
    unittest.main()
