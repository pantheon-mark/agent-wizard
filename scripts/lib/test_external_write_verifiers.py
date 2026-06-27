import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import Operation  # noqa: E402
from external_write.verification_modes import ClaimStrength  # noqa: E402
from external_write.verifiers import (  # noqa: E402
    POSTWRITE_VERIFICATION_SCHEMA,
    VerificationResult,
    validate_postwrite_verification,
)


def _op(op_kind="set_status"):
    return Operation(
        surface="google_sheets", object_id="sheet:abc", field="Status",
        new_value="Complete", op_kind=op_kind, batch_id="b1",
    )


def _good_record():
    return {
        "schema": POSTWRITE_VERIFICATION_SCHEMA,
        "verification_mode": "prestate_snapshot_diff",
        "claim_strength": "verified",
        "verifier_id": "prestate_snapshot_diff_v1",
        "source_lineage": {
            "pre_write_sources": ["prewrite_csv_backup"],
            "post_write_sources": ["live_surface_read"],
            # forbidden_sources must be a superset of the registry's
            # forbidden_verification_inputs for prestate_snapshot_diff_v1.
            "forbidden_sources": [
                "writer_generated_id_map",
                "live_id_column_as_truth",
                "apply_report",
            ],
        },
        "invariant_checked": "every pre-write row keeps its stable id on the same facts",
        "evidence_ref": "agents/handoffs/.postwrite_evidence_001.txt",
    }


class TestPostwriteVerification(unittest.TestCase):
    def test_valid_record_passes(self):
        r = validate_postwrite_verification(_op(), _good_record())
        self.assertIsInstance(r, VerificationResult)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.claim_strength, ClaimStrength.VERIFIED)

    def test_missing_record_fails(self):
        self.assertFalse(validate_postwrite_verification(_op(), {}).ok)
        self.assertFalse(validate_postwrite_verification(_op(), None).ok)

    def test_wrong_schema_fails(self):
        rec = _good_record(); rec["schema"] = "something-else"
        self.assertFalse(validate_postwrite_verification(_op(), rec).ok)

    def test_missing_required_field_fails(self):
        rec = _good_record(); del rec["invariant_checked"]
        self.assertFalse(validate_postwrite_verification(_op(), rec).ok)

    def test_verifier_not_in_op_verifier_set_fails(self):
        rec = _good_record(); rec["verifier_id"] = "operator_attested_v1"
        rec["verification_mode"] = "operator_attested"
        # operator_attested_v1 is NOT in set_status verifier_set -> fail
        self.assertFalse(validate_postwrite_verification(_op(), rec).ok)

    def test_mode_mismatch_with_registered_verifier_fails(self):
        rec = _good_record(); rec["verification_mode"] = "platform_audit_log"
        self.assertFalse(validate_postwrite_verification(_op(), rec).ok)

    def test_claim_exceeds_mode_ceiling_fails(self):
        # operator_attested mode ceiling is ATTESTED — claiming 'verified' must fail
        # at step 7 (ceiling check), NOT at step 5 (verifier-set check).
        # Patch set_status's verifier_set to include operator_attested_v1 so the
        # verifier-set check (step 5) passes and the ceiling check (step 7) is reached.
        import external_write.contracts as _c
        from external_write.contracts import OperationContract
        orig = _c.OPERATION_CONTRACTS["set_status"]
        _c.OPERATION_CONTRACTS["set_status"] = OperationContract(
            op_kind="set_status", writes=orig.writes, produces=orig.produces,
            dependency_set=orig.dependency_set,
            verifier_set=("prestate_snapshot_diff_v1", "operator_attested_v1"),
            introduces_persistent_binding=orig.introduces_persistent_binding,
        )
        try:
            rec = _good_record()
            rec["verifier_id"] = "operator_attested_v1"
            rec["verification_mode"] = "operator_attested"
            rec["claim_strength"] = "verified"  # exceeds ATTESTED ceiling -> step 7 fails
            result = validate_postwrite_verification(_op(), rec)
            self.assertFalse(result.ok)
            self.assertIn("ceiling", result.reason)
        finally:
            _c.OPERATION_CONTRACTS["set_status"] = orig

    def test_lineage_lock_rejects_forbidden_source_overlap(self):
        rec = _good_record()
        rec["source_lineage"]["post_write_sources"] = [
            "live_surface_read", "writer_generated_id_map",
        ]
        r = validate_postwrite_verification(_op(), rec)
        self.assertFalse(r.ok)
        self.assertIn("writer_generated_id_map", r.reason)

    def test_lineage_lock_rejects_apply_report_as_truth(self):
        rec = _good_record()
        rec["source_lineage"]["post_write_sources"] = ["apply_report"]
        r = validate_postwrite_verification(_op(), rec)
        self.assertFalse(r.ok)
        self.assertIn("apply_report", r.reason)

    def test_verified_claim_requires_real_evidence(self):
        rec = _good_record(); rec["evidence_ref"] = "operator_attested"
        self.assertFalse(validate_postwrite_verification(_op(), rec).ok)
        rec2 = _good_record(); rec2["evidence_ref"] = ""
        self.assertFalse(validate_postwrite_verification(_op(), rec2).ok)

    def test_unknown_op_kind_fails(self):
        self.assertFalse(validate_postwrite_verification(_op("nope"), _good_record()).ok)

    def test_forbidden_sources_missing_fails(self):
        # forbidden_sources is a required sub-field of source_lineage.
        rec = _good_record()
        del rec["source_lineage"]["forbidden_sources"]
        self.assertFalse(validate_postwrite_verification(_op(), rec).ok)

    def test_forbidden_sources_must_cover_registry_forbidden(self):
        # The record's forbidden_sources must be a superset (⊇) of the registry
        # verifier's forbidden_verification_inputs.  Omitting one registry-forbidden
        # source makes the record dishonest about what it excluded.
        rec = _good_record()
        # Remove one of the three registry-mandated forbidden sources.
        rec["source_lineage"]["forbidden_sources"] = [
            "writer_generated_id_map",
            "live_id_column_as_truth",
            # "apply_report" intentionally omitted — must fail
        ]
        result = validate_postwrite_verification(_op(), rec)
        self.assertFalse(result.ok)
        self.assertIn("apply_report", result.reason)


if __name__ == "__main__":
    unittest.main()
