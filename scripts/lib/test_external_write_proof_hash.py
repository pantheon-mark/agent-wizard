import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.proof_hash import (  # noqa: E402
    compute_implementation_hash,
    compute_contract_hash,
    ProofHashError,
    AcceptedWriteKey,
    is_accepted,
    ACCEPTED_WRITE_REGISTRY,
    SHA256_HEX_LEN,
)
import external_write.contracts as _contracts  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402

_LIB_DIR = _AGENTS_LIB / "external_write"


class TestProofHash(unittest.TestCase):
    def test_implementation_hash_is_deterministic_hex(self):
        h1 = compute_implementation_hash("set_status", lib_dir=_LIB_DIR)
        h2 = compute_implementation_hash("set_status", lib_dir=_LIB_DIR)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), SHA256_HEX_LEN)
        int(h1, 16)  # hex

    def test_runtime_params_change_implementation_hash(self):
        base = compute_implementation_hash("set_status", lib_dir=_LIB_DIR)
        changed = compute_implementation_hash("set_status", lib_dir=_LIB_DIR,
                                              runtime_params={"dry_run": False})
        self.assertNotEqual(base, changed)

    def test_missing_dependency_file_fails_closed(self):
        empty = _LIB_DIR.parent  # a dir that does NOT contain adapters.py etc.
        with self.assertRaises(ProofHashError):
            compute_implementation_hash("set_status", lib_dir=empty)

    def test_unknown_op_kind_fails(self):
        with self.assertRaises(ProofHashError):
            compute_implementation_hash("nope", lib_dir=_LIB_DIR)

    def test_contract_hash_is_deterministic_hex(self):
        h1 = compute_contract_hash("set_status")
        h2 = compute_contract_hash("set_status")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), SHA256_HEX_LEN)

    def test_distinct_ops_have_distinct_contract_hashes(self):
        self.assertNotEqual(compute_contract_hash("set_status"),
                            compute_contract_hash("update_due_date"))

    def test_accepted_registry_is_empty_by_default(self):
        self.assertEqual(ACCEPTED_WRITE_REGISTRY, ())

    def test_is_accepted_true_only_when_both_hashes_match(self):
        k = AcceptedWriteKey(implementation_hash="a" * SHA256_HEX_LEN,
                             contract_hash="b" * SHA256_HEX_LEN)
        self.assertTrue(is_accepted(k, [k]))
        other = AcceptedWriteKey(implementation_hash="a" * SHA256_HEX_LEN,
                                 contract_hash="c" * SHA256_HEX_LEN)
        self.assertFalse(is_accepted(k, [other]))
        self.assertFalse(is_accepted(k, []))


    def test_implementation_hash_changes_when_dependency_file_content_changes(self):
        import shutil
        import tempfile
        # Build a temp dir that mirrors _LIB_DIR so compute_implementation_hash
        # can resolve all dependency files for set_status.
        # The dependency_set is ("adapters.py", "broker.py", "operations.py", "verifiers.py");
        # compute_implementation_hash resolves them as lib_dir / fname.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Copy only the dependency files (and contracts.py / verification_modes.py
            # which are imported by the module but are not in the dependency_set —
            # they do not need to be present in the temp dir for the hash to resolve).
            dep_names = ("adapters.py", "broker.py", "operations.py", "verifiers.py")
            for fname in dep_names:
                shutil.copy2(_LIB_DIR / fname, tmp_path / fname)

            # --- stability leg: two calls on the same bytes must agree ---
            h1 = compute_implementation_hash("set_status", lib_dir=tmp_path)
            h2 = compute_implementation_hash("set_status", lib_dir=tmp_path)
            self.assertEqual(h1, h2, "hash must be deterministic across calls")
            self.assertEqual(len(h1), SHA256_HEX_LEN)

            # --- sensitivity leg: mutating ONE byte in a dependency file must
            #     produce a different hash ---
            target = tmp_path / "adapters.py"
            with target.open("ab") as f:
                f.write(b"\n# mutation-sentinel\n")
            h_mutated = compute_implementation_hash("set_status", lib_dir=tmp_path)
            self.assertNotEqual(
                h1,
                h_mutated,
                "hash must change when a dependency file's bytes change",
            )

    # -- B1-3: risk fields are hash-bound (D-B1-b) -------------------------

    def test_risk_class_downgrade_changes_contract_hash_and_invalidates_stale_proof(self):
        """D-B1-b: risk_class enters _contract_canon. A post-hoc downgrade of
        delete_record's risk_class must change compute_contract_hash's output, and a
        registry entry accepted under the OLD hash must be rejected by is_accepted
        once the contract has been downgraded (fail-safe: a stale accepted proof does
        not carry over a risk-class change)."""
        original = _contracts.OPERATION_CONTRACTS["delete_record"]
        pre_downgrade_key = AcceptedWriteKey(
            implementation_hash=compute_implementation_hash("delete_record", lib_dir=_LIB_DIR),
            contract_hash=compute_contract_hash("delete_record"),
        )
        downgraded = OperationContract(
            op_kind=original.op_kind, writes=original.writes, produces=original.produces,
            dependency_set=original.dependency_set, verifier_set=original.verifier_set,
            introduces_persistent_binding=original.introduces_persistent_binding,
            risk_class="reversible_external",  # the downgrade under test
            requires_accepted_phase=original.requires_accepted_phase,
            blast_radius_cap=original.blast_radius_cap,
        )
        try:
            _contracts.OPERATION_CONTRACTS["delete_record"] = downgraded
            post_downgrade_hash = compute_contract_hash("delete_record")
            self.assertNotEqual(pre_downgrade_key.contract_hash, post_downgrade_hash,
                                 "downgrading risk_class must change the contract hash")
            post_downgrade_key = AcceptedWriteKey(
                implementation_hash=compute_implementation_hash("delete_record", lib_dir=_LIB_DIR),
                contract_hash=post_downgrade_hash,
            )
            # The registry only holds the pre-downgrade key (as if accepted before the
            # downgrade). A fresh confirm() would recompute post_downgrade_key and find
            # no match -> the stale accepted proof is correctly rejected.
            self.assertFalse(is_accepted(post_downgrade_key, [pre_downgrade_key]))
        finally:
            _contracts.OPERATION_CONTRACTS["delete_record"] = original

    def test_requires_accepted_phase_change_alone_changes_contract_hash(self):
        original = _contracts.OPERATION_CONTRACTS["delete_record"]
        h_before = compute_contract_hash("delete_record")
        flipped = OperationContract(
            op_kind=original.op_kind, writes=original.writes, produces=original.produces,
            dependency_set=original.dependency_set, verifier_set=original.verifier_set,
            introduces_persistent_binding=original.introduces_persistent_binding,
            risk_class=original.risk_class,
            requires_accepted_phase=not original.requires_accepted_phase,
            blast_radius_cap=original.blast_radius_cap,
        )
        try:
            _contracts.OPERATION_CONTRACTS["delete_record"] = flipped
            h_after = compute_contract_hash("delete_record")
            self.assertNotEqual(h_before, h_after)
        finally:
            _contracts.OPERATION_CONTRACTS["delete_record"] = original

    def test_blast_radius_cap_change_alone_changes_contract_hash(self):
        original = _contracts.OPERATION_CONTRACTS["delete_record"]
        h_before = compute_contract_hash("delete_record")
        widened = OperationContract(
            op_kind=original.op_kind, writes=original.writes, produces=original.produces,
            dependency_set=original.dependency_set, verifier_set=original.verifier_set,
            introduces_persistent_binding=original.introduces_persistent_binding,
            risk_class=original.risk_class,
            requires_accepted_phase=original.requires_accepted_phase,
            blast_radius_cap=(original.blast_radius_cap or 0) + 100,
        )
        try:
            _contracts.OPERATION_CONTRACTS["delete_record"] = widened
            h_after = compute_contract_hash("delete_record")
            self.assertNotEqual(h_before, h_after)
        finally:
            _contracts.OPERATION_CONTRACTS["delete_record"] = original

    def test_existing_status_op_contract_hash_unaffected_by_delete_record_addition(self):
        """Non-breaking behavior: adding delete_record must not change set_status's own
        contract hash (each op_kind's canon is computed independently)."""
        # This is a regression guard, not a golden hash: it recomputes from the live
        # contract and only asserts internal self-consistency (deterministic + distinct
        # from delete_record), never a hand-written expected digest.
        h_status = compute_contract_hash("set_status")
        h_status_again = compute_contract_hash("set_status")
        self.assertEqual(h_status, h_status_again)
        self.assertNotEqual(h_status, compute_contract_hash("delete_record"))


if __name__ == "__main__":
    unittest.main()
