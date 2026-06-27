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


if __name__ == "__main__":
    unittest.main()
