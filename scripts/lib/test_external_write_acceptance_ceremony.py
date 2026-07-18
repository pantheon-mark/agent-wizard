"""Tests for the B2-T3 acceptance ceremony (external_write.acceptance_ceremony) — the SOLE
deterministic writer of ``accepted: true`` in security/capability_descriptors.json.

Trust-critical. The OVERRIDING property under test is fail-safe: ANY missing / ambiguous /
invalid input must REFUSE, leaving the descriptor set byte-for-byte unchanged (accepted stays
false). Every invariant is tested INDEPENDENTLY (only the one input under test is violated;
everything else is valid) so a refusal proves that specific invariant is load-bearing.

Uses REAL descriptor-set fixtures on disk + REAL copy_run_proof objects with REAL proof hashes
(compute_contract_hash / compute_implementation_hash over the canonical lib dir), not mocks of
the units under test.
"""

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))
# This file's own dir (wizard/scripts/lib) — for the build-side capability_descriptor_registry
# cross-tree pin tests, which run from wizard/scripts and can import both trees.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_write import acceptance_ceremony as ac  # noqa: E402
from external_write.acceptance_ceremony import (  # noqa: E402
    accept_capability_for_live_use,
    AcceptanceResult,
    OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA,
)
from external_write.adapter_registry import (  # noqa: E402
    get_adapter,
    register_adapter,
    unregister_adapter,
)
import external_write.contracts as _contracts  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.effects_manifest import resolve_dependency_files  # noqa: E402
from external_write.proof_hash import (  # noqa: E402
    compute_contract_hash,
    compute_implementation_hash,
    SHA256_HEX_LEN,
)
from external_write.copy_run_proof import COPY_RUN_PROOF_SCHEMA  # noqa: E402
from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA  # noqa: E402
from external_write.operations import Operation  # noqa: E402
from external_write import write_gate  # noqa: E402
from external_write.write_gate import (  # noqa: E402
    InvocationLedger,
    load_descriptor_set,
    evaluate_write_gate,
    LIVE_TARGET,
    TEST_TARGETS,
)


PHASE = "phase_02"
PROOF_OP_KIND = "delete_record"  # irreversible_external; non-binding; no recovery floor

# Task 6 (F-34 wire-verification) fixtures — real scan.py fixture files, reused verbatim from
# the Task-5 scanner test suite (DRY: not a parallel set of bypass shapes).
_SCAN_FIXTURES = (
    Path(__file__).resolve().parents[2] / "test_fixtures" / "external_write_scan"
)
_CLEAN_MODULE_PATH = str(_SCAN_FIXTURES / "legal_through_adapter.py")


# ---------------------------------------------------------------------------
# Fixture builders — real shapes on disk
# ---------------------------------------------------------------------------

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
                "writer_generated_id_map",
                "live_id_column_as_truth",
                "apply_report",
            ],
        },
        "invariant_checked": "record absent after delete",
        "evidence_ref": "agents/handoffs/.ev.txt",
    }


def _proof(op_kind=PROOF_OP_KIND, *, contract_hash=None, implementation_hash=None,
           durability=None, accepted_for_live_use=True, capability_id="google_sheets",
           include_capability_id=True, module_paths=None, include_module_paths=True):
    p = {
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
        "accepted_for_live_use": accepted_for_live_use,
        "implementation_hash": (implementation_hash
                                if implementation_hash is not None
                                else compute_implementation_hash(op_kind)),
        "contract_hash": (contract_hash if contract_hash is not None
                          else compute_contract_hash(op_kind)),
    }
    if include_capability_id:
        p["capability_id"] = capability_id
    if include_module_paths:
        p["capability_module_paths"] = (
            list(module_paths) if module_paths is not None else [_CLEAN_MODULE_PATH]
        )
    return p


def _receipt(capability_id, *, phase_id=PHASE, copy_run_proof_ref="proof.json",
             operator_confirmation="Yes, accept the delete capability for live use.",
             schema=OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA, accepted_at="2026-07-04T12:00:00Z"):
    r = {
        "schema": schema,
        "capability_id": capability_id,
        "phase_id": phase_id,
        "copy_run_proof_ref": copy_run_proof_ref,
        "operator_confirmation": operator_confirmation,
        "accepted_at": accepted_at,
    }
    return r


def _descriptor(id="google_sheets", *, risk_class="irreversible_external", phase_id=PHASE,
                blast_radius_cap=5, accepted=False, action_class="delete",
                recovery_profile_ref=None, declared_test_target="copy", include_phase=True):
    d = {
        "id": id, "name": id, "action_class": action_class,
        "risk_class": risk_class, "recovery_profile_ref": recovery_profile_ref,
        "declared_test_target": declared_test_target,
        "blast_radius_cap": blast_radius_cap, "accepted": accepted,
    }
    if include_phase:
        d["phase_id"] = phase_id
    return d


class _Case:
    """One materialised on-disk scenario: descriptor set + proof + receipt files."""

    def __init__(self, tmp, *, descriptors, proof=None, receipt=None,
                 write_proof=True, write_receipt=True):
        self.tmp = Path(tmp)
        self.security = self.tmp / "security"
        self.security.mkdir(parents=True, exist_ok=True)
        self.set_path = self.security / "capability_descriptors.json"
        self.proof_path = self.tmp / "proof.json"
        self.receipt_path = self.tmp / "receipt.json"
        self.audit_path = self.security / "capability_acceptance_log.jsonl"

        self.set_path.write_text(json.dumps(descriptors, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        if proof is None:
            proof = _proof()
        if write_proof:
            self.proof_path.write_text(json.dumps(proof), encoding="utf-8")
        if receipt is None:
            receipt = _receipt("google_sheets", copy_run_proof_ref=str(self.proof_path))
        if write_receipt:
            self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    def original_bytes(self):
        return self.set_path.read_bytes()

    def entries(self):
        return json.loads(self.set_path.read_text(encoding="utf-8"))

    def accepted_flag(self, id):
        for e in self.entries():
            if e.get("id") == id:
                return e.get("accepted")
        return None

    def call(self, *, capability_id="google_sheets", phase_id=PHASE, **kw):
        return accept_capability_for_live_use(
            capability_id, phase_id,
            str(self.proof_path), str(self.receipt_path),
            descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path),
            **kw)


class AcceptanceCeremonyTest(unittest.TestCase):

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    # -- Happy path -------------------------------------------------------

    def test_happy_path_flips_target_only(self):
        c = _Case(self.tmp, descriptors=[
            _descriptor(id="google_sheets"),
            _descriptor(id="asana"),  # second gated descriptor
        ])
        res = c.call()
        self.assertIsInstance(res, AcceptanceResult)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(c.accepted_flag("google_sheets"), True)
        # Only the target changed; the other gated descriptor stays false.
        self.assertEqual(c.accepted_flag("asana"), False)
        # File still parses and is a list.
        self.assertIsInstance(c.entries(), list)

    def test_acceptance_record_written(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        res = c.call()
        self.assertTrue(res.accepted, res.reason)
        self.assertTrue(c.audit_path.exists())
        line = c.audit_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        rec = json.loads(line)
        self.assertEqual(rec["capability_id"], "google_sheets")
        self.assertEqual(rec["phase_id"], PHASE)
        self.assertEqual(rec["copy_run_proof_ref"], str(c.proof_path))

    # -- Task B2b-fix, Critical 1: capability_module_hash recorded ---------

    def test_capability_module_hash_recorded_when_module_path_supplied(self):
        # A real, on-disk capability module file -- its bytes must be hashed into the record
        # verbatim (never the shared/scan-fixture capability_module_paths file, a distinct
        # concept: capability_module_paths is what Invariant 7 scans for the bypass check;
        # capability_module_path here is what B2b-fix's own capability_module_hash is over).
        cap_module_path = Path(self.tmp) / "acme_widget_deleter_capability.py"
        cap_module_path.write_text("OP_KIND = 'delete_record'\n", encoding="utf-8")
        expected_hash = hashlib.sha256(cap_module_path.read_bytes()).hexdigest()

        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        res = c.call(capability_module_path=str(cap_module_path))
        self.assertTrue(res.accepted, res.reason)
        line = c.audit_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        rec = json.loads(line)
        self.assertEqual(rec["capability_module_hash"], expected_hash)

    def test_capability_module_hash_null_when_no_module_file_found_never_refuses(self):
        # Additive, backward-compatible: no capability_module_path supplied and no file at the
        # default-derived location either -- the record carries capability_module_hash: null,
        # and acceptance itself is NOT refused (fail-safe applies to the DETECTOR reading this
        # record later, never to the ceremony's own grant decision).
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        res = c.call()
        self.assertTrue(res.accepted, res.reason)
        line = c.audit_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        rec = json.loads(line)
        self.assertIn("capability_module_hash", rec)
        self.assertIsNone(rec["capability_module_hash"])

    def test_capability_module_hash_changes_with_module_bytes(self):
        cap_module_path = Path(self.tmp) / "acme_widget_deleter_capability.py"
        cap_module_path.write_text("OP_KIND = 'delete_record'\n", encoding="utf-8")

        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        res = c.call(capability_module_path=str(cap_module_path))
        self.assertTrue(res.accepted, res.reason)
        first_hash = json.loads(
            c.audit_path.read_text(encoding="utf-8").strip().splitlines()[-1]
        )["capability_module_hash"]

        cap_module_path.write_text(
            "OP_KIND = 'delete_record'\n# rebuilt\n", encoding="utf-8")
        self.assertNotEqual(
            hashlib.sha256(cap_module_path.read_bytes()).hexdigest(), first_hash)

    # -- Invariant 1: descriptor set + target well-formed -----------------

    def test_missing_descriptor_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="asana")])  # no google_sheets
        orig = c.original_bytes()
        res = c.call(capability_id="google_sheets")
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_malformed_descriptor_set_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        c.set_path.write_text("{not json", encoding="utf-8")
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_non_list_descriptor_set_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        c.set_path.write_text(json.dumps({"id": "google_sheets"}), encoding="utf-8")
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_out_of_vocabulary_risk_class_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets", risk_class="banana")])
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_base_sentinel_descriptor_refuses(self):
        # Defense-in-depth: a base __builtin__ placeholder is never a real acceptable capability.
        c = _Case(self.tmp, descriptors=[
            _descriptor(id="__builtin__:irreversible_external")])
        orig = c.original_bytes()
        res = c.call(capability_id="__builtin__:irreversible_external")
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_non_gated_descriptor_refuses(self):
        # The ceremony's scope is gated capabilities only; accepting a reversible one is refused.
        c = _Case(self.tmp, descriptors=[
            _descriptor(id="google_sheets", risk_class="reversible_external")])
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    # -- Invariant 2: no risk downgrade (hash-bound canon) ----------------

    def test_descriptor_risk_inconsistent_with_contract_refuses(self):
        # descriptor claims sensitive_data but the proof's op_kind contract is
        # irreversible_external -> refuse (do not trust the mutable descriptor field).
        c = _Case(self.tmp, descriptors=[
            _descriptor(id="google_sheets", risk_class="sensitive_data")])
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_contract_hash_mismatch_refuses(self):
        # proof.contract_hash does not match the recomputed canon -> a stale / downgraded
        # contract; refuse.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(contract_hash="f" * SHA256_HEX_LEN))
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_implementation_hash_mismatch_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(implementation_hash="0" * SHA256_HEX_LEN))
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    # -- Invariant 3: blast-radius cap present on gated -------------------

    def test_missing_blast_cap_on_gated_refuses(self):
        c = _Case(self.tmp, descriptors=[
            _descriptor(id="google_sheets", blast_radius_cap=None)])
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_nonpositive_blast_cap_refuses(self):
        c = _Case(self.tmp, descriptors=[
            _descriptor(id="google_sheets", blast_radius_cap=0)])
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    # -- Invariant 4: validated copy_run_proof present --------------------

    def test_missing_copy_run_proof_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  write_proof=False)
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_failed_copy_run_proof_refuses(self):
        # A structurally-present but invalid proof (accepted_for_live_use false) must refuse.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(accepted_for_live_use=False))
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_malformed_copy_run_proof_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        c.proof_path.write_text("{not json", encoding="utf-8")
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    # -- Invariant 4b: proof BOUND to the specific capability (T3 Minor) ---

    def test_proof_capability_id_mismatch_refuses(self):
        # A valid copy_run_proof produced for a DIFFERENT capability (even same op_kind /
        # same risk class) must not authorize accepting THIS capability. The proof↔capability
        # join is at the specific-capability altitude, not merely the risk class.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(capability_id="asana"))
        orig = c.original_bytes()
        res = c.call(capability_id="google_sheets")
        self.assertFalse(res.accepted)
        self.assertIn("capability", (res.reason or "").lower())
        self.assertEqual(c.original_bytes(), orig)

    def test_proof_without_capability_id_refuses(self):
        # Fail-safe: a proof that does not name the capability it proves cannot authorize
        # acceptance (an unbound proof is exactly the ambiguity this binding closes).
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(include_capability_id=False))
        orig = c.original_bytes()
        res = c.call(capability_id="google_sheets")
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_proof_capability_id_match_accepts(self):
        # The match case is the happy path: a proof naming this exact capability accepts.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(capability_id="google_sheets"))
        res = c.call(capability_id="google_sheets")
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(c.accepted_flag("google_sheets"), True)

    # -- Invariant 5: operator-acceptance receipt present + bound ---------

    def test_missing_operator_receipt_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  write_receipt=False)
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_receipt_phase_binding_mismatch_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        # receipt written for a different phase than the input phase_id.
        c.receipt_path.write_text(json.dumps(
            _receipt("google_sheets", phase_id="phase_99",
                     copy_run_proof_ref=str(c.proof_path))), encoding="utf-8")
        orig = c.original_bytes()
        res = c.call(phase_id=PHASE)
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_receipt_capability_binding_mismatch_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        c.receipt_path.write_text(json.dumps(
            _receipt("asana", copy_run_proof_ref=str(c.proof_path))), encoding="utf-8")
        orig = c.original_bytes()
        res = c.call(capability_id="google_sheets")
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_receipt_proof_ref_binding_mismatch_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        c.receipt_path.write_text(json.dumps(
            _receipt("google_sheets", copy_run_proof_ref="some/other/proof.json")),
            encoding="utf-8")
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_empty_operator_confirmation_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        c.receipt_path.write_text(json.dumps(
            _receipt("google_sheets", copy_run_proof_ref=str(c.proof_path),
                     operator_confirmation="   ")), encoding="utf-8")
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    # -- Invariant 6: phase binding ---------------------------------------

    def test_descriptor_without_phase_binding_refuses(self):
        # Fail-safe: a descriptor carrying no phase binding cannot be accepted (forward
        # obligation on T4/T5 to populate phase_id).
        c = _Case(self.tmp, descriptors=[
            _descriptor(id="google_sheets", include_phase=False)])
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_phase_mismatch_refuses(self):
        c = _Case(self.tmp, descriptors=[
            _descriptor(id="google_sheets", phase_id="phase_07")])
        # receipt + input agree on PHASE, but the descriptor is owned by phase_07.
        orig = c.original_bytes()
        res = c.call(phase_id=PHASE)
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    # -- Invariant 7: WRITE PATH IS GATED (Task 6 — F-34 wire-verification) ----------------
    # Closes the dogfood finding directly: the ceremony must REFUSE a capability whose own
    # code holds/constructs a write credential, or whose write path bypasses run_operation
    # (a direct surface-mutation call, or a forbidden vendor-SDK import) — reusing the SAME
    # Task-5 zone-aware scanner the build-time gate runs, not a reimplemented check.

    def test_missing_capability_module_paths_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(include_module_paths=False))
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_empty_capability_module_paths_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(module_paths=[]))
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_capability_module_path_pointing_at_missing_file_refuses(self):
        # Fail-safe: a scanner over a nonexistent file silently reports zero violations (it
        # never got to read the file) — the ceremony must not treat that as "clean".
        missing = str(_SCAN_FIXTURES / "_does_not_exist_anywhere.py")
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(module_paths=[missing]))
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_capability_module_holding_write_credential_refuses(self):
        # (a) fixture capability that holds/constructs a write credential.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(module_paths=[
                      str(_SCAN_FIXTURES / "credential_construction.py")]))
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertIn("write-path bypass scan", res.reason)
        self.assertEqual(c.original_bytes(), orig)

    def test_capability_module_direct_api_call_refuses(self):
        # (b) fixture with a write path outside run_operation — a direct surface mutation.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(module_paths=[str(_SCAN_FIXTURES / "direct_api_call.py")]))
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_capability_module_forbidden_import_refuses(self):
        # (b) alternate shape — a forbidden vendor/network import outside run_operation.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(module_paths=[str(_SCAN_FIXTURES / "forbidden_import.py")]))
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_conformant_capability_module_accepts(self):
        # ACCEPTS a fully-conformant fixture: a capability module that routes every mutation
        # through the emitted adapter scans clean, and does not by itself block acceptance.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")],
                  proof=_proof(module_paths=[
                      str(_SCAN_FIXTURES / "legal_through_adapter.py")]))
        res = c.call()
        self.assertTrue(res.accepted, res.reason)

    # -- Invariant 9: declared_test_target is the vocab token, not prose (Task 6 D-i fix) ---

    def test_prose_declared_test_target_refuses(self):
        c = _Case(self.tmp, descriptors=[_descriptor(
            id="google_sheets",
            declared_test_target="Sample of 5 real emails, manually reviewed")])
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_missing_declared_test_target_refuses(self):
        d = _descriptor(id="google_sheets")
        d["declared_test_target"] = None
        c = _Case(self.tmp, descriptors=[d])
        orig = c.original_bytes()
        res = c.call()
        self.assertFalse(res.accepted)
        self.assertEqual(c.original_bytes(), orig)

    def test_each_vocab_test_target_accepts(self):
        for tok in sorted(TEST_TARGETS):
            with self.subTest(tok=tok):
                c = _Case(self.tmp, descriptors=[
                    _descriptor(id="google_sheets", declared_test_target=tok)])
                res = c.call()
                self.assertTrue(res.accepted, res.reason)

    # -- Atomicity --------------------------------------------------------

    def test_write_failure_leaves_original_intact(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        orig = c.original_bytes()

        def _boom(src, dst):
            raise OSError("simulated replace failure")

        real_replace = os.replace
        ac.os.replace = _boom
        try:
            res = c.call()
        finally:
            ac.os.replace = real_replace
        self.assertFalse(res.accepted)
        # The trust file is byte-for-byte the original — no partial / corrupt write.
        self.assertEqual(c.original_bytes(), orig)
        self.assertEqual(c.accepted_flag("google_sheets"), False)
        # No orphaned temp files left in the security dir.
        leftovers = [p.name for p in c.security.iterdir()
                     if p.name != "capability_descriptors.json"]
        self.assertEqual(leftovers, [], f"orphaned temp files: {leftovers}")

    # -- write_gate integration -------------------------------------------

    def test_write_gate_permits_after_flip_and_refuses_other_surface(self):
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets")])
        res = c.call()
        self.assertTrue(res.accepted, res.reason)

        ds = load_descriptor_set(str(c.set_path))
        ledger = InvocationLedger()
        live_op = Operation(surface="google_sheets", object_id="row:1", field="__record__",
                            new_value="<x>", op_kind="delete_record", batch_id="b1")
        decision = evaluate_write_gate(live_op, target=LIVE_TARGET, descriptor_set=ds,
                                       cap_ledger=ledger)
        self.assertTrue(decision.permitted, decision.refusal)

        other_op = Operation(surface="asana", object_id="row:1", field="__record__",
                             new_value="<x>", op_kind="delete_record", batch_id="b1")
        other_decision = evaluate_write_gate(other_op, target=LIVE_TARGET, descriptor_set=ds,
                                             cap_ledger=InvocationLedger())
        self.assertFalse(other_decision.permitted)

    # -- Task B4 (F-59): audit-append fires on every real re-acceptance ---
    # The dogfood finding: re-accepting an already-`accepted: true` descriptor could write NO
    # audit record at all. The fix keys the dedup on (capability_id, phase_id) in the audit log
    # itself, never merely on `accepted is True` — a missing record for that exact pair is always
    # backfilled, an existing one is never duplicated.

    def _accepted_records(self, c):
        if not c.audit_path.exists():
            return []
        return [json.loads(line) for line in
                c.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_real_flip_still_writes_a_single_record(self):
        # Baseline (unchanged behaviour): a genuine false->true flip audits exactly once. This is
        # the B1-paused-then-re-accepted case in spirit (a real flip), just exercised directly —
        # B1's own reconcile-to-paused mechanics are covered elsewhere; here the concern is
        # narrowly the ceremony's own audit-on-flip behaviour.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets", accepted=False)])
        res = c.call()
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(c.accepted_flag("google_sheets"), True)
        recs = self._accepted_records(c)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["capability_id"], "google_sheets")
        self.assertEqual(recs[0]["phase_id"], PHASE)
        self.assertIn("implementation_hash", recs[0])
        self.assertIn("capability_module_hash", recs[0])

    def test_paused_then_real_reacceptance_audits(self):
        # The F-59 scenario end to end: a descriptor that was accepted, then PAUSED (B1 sets
        # accepted:false on pause -- modelled directly here as a false descriptor since B1's own
        # pause mechanics live in lifecycle_state, not this module), re-accepted through the
        # ceremony -- a real false->true flip -- must produce an audit record.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets", accepted=False)])
        res = c.call()
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(len(self._accepted_records(c)), 1)

    def test_already_accepted_with_no_audit_record_backfills_it(self):
        # The F-59 residual this task closes: accepted:true persists but the audit log carries
        # NO record for this (capability_id, phase_id) pair (e.g. an older pre-B4 build, or a
        # prior best-effort append that failed after a real flip). An explicit re-acceptance must
        # not silently no-op -- it appends the missing record now, complete with BOTH hashes.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets", accepted=True)])
        self.assertFalse(c.audit_path.exists())
        res = c.call()
        self.assertTrue(res.accepted, res.reason)
        self.assertIn("backfilled", (res.warning or "").lower())
        recs = self._accepted_records(c)
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual(rec["capability_id"], "google_sheets")
        self.assertEqual(rec["phase_id"], PHASE)
        self.assertEqual(rec["schema"], ac.ACCEPTANCE_RECORD_SCHEMA)
        # Record completeness: BOTH hashes present, computed from the same recomputed canon a
        # real flip would use.
        self.assertEqual(rec["contract_hash"], compute_contract_hash(PROOF_OP_KIND))
        self.assertEqual(rec["implementation_hash"], compute_implementation_hash(PROOF_OP_KIND))
        self.assertIn("capability_module_hash", rec)
        # The descriptor itself is untouched (still accepted:true; no spurious re-flip write).
        self.assertEqual(c.accepted_flag("google_sheets"), True)

    def test_already_accepted_backfill_is_idempotent_no_duplicate(self):
        # A second explicit re-acceptance after the record has been backfilled must NOT add a
        # second record for the same (capability_id, phase_id) pair.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets", accepted=True)])
        first = c.call()
        self.assertTrue(first.accepted, first.reason)
        self.assertEqual(len(self._accepted_records(c)), 1)

        second = c.call()
        self.assertTrue(second.accepted, second.reason)
        self.assertIn("no change written", (second.warning or "").lower())
        recs = self._accepted_records(c)
        self.assertEqual(len(recs), 1, f"expected no duplicate, got: {recs}")

    def test_already_accepted_with_existing_record_for_pair_no_duplicate(self):
        # An existing record for the EXACT (capability_id, phase_id) pair already present in the
        # log (written by some other path, e.g. a prior real flip) must not be duplicated by a
        # subsequent explicit re-acceptance call.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets", accepted=True)])
        c.security.mkdir(parents=True, exist_ok=True)
        pre_existing = {
            "schema": ac.ACCEPTANCE_RECORD_SCHEMA, "capability_id": "google_sheets",
            "phase_id": PHASE, "risk_class": "irreversible_external", "op_kind": PROOF_OP_KIND,
            "copy_run_proof_ref": str(c.proof_path), "operator_receipt_ref": str(c.receipt_path),
            "contract_hash": compute_contract_hash(PROOF_OP_KIND),
            "implementation_hash": compute_implementation_hash(PROOF_OP_KIND),
            "capability_module_hash": None, "operator_confirmation": "prior confirmation",
            "receipt_accepted_at": "2026-01-01T00:00:00Z",
        }
        c.audit_path.write_text(json.dumps(pre_existing) + "\n", encoding="utf-8")

        res = c.call()
        self.assertTrue(res.accepted, res.reason)
        self.assertIn("no change written", (res.warning or "").lower())
        recs = self._accepted_records(c)
        self.assertEqual(len(recs), 1, f"expected no duplicate, got: {recs}")
        self.assertEqual(recs[0]["operator_confirmation"], "prior confirmation")

    def test_record_exists_check_skips_a_different_phase_pair(self):
        # A record for the SAME capability_id but a DIFFERENT phase_id must not be treated as
        # covering this (capability_id, phase_id) pair -- the key is the pair, not just the id.
        c = _Case(self.tmp, descriptors=[_descriptor(id="google_sheets", accepted=True)])
        other_phase_record = {
            "schema": ac.ACCEPTANCE_RECORD_SCHEMA, "capability_id": "google_sheets",
            "phase_id": "phase_99", "risk_class": "irreversible_external",
            "op_kind": PROOF_OP_KIND, "copy_run_proof_ref": str(c.proof_path),
            "operator_receipt_ref": str(c.receipt_path),
            "contract_hash": compute_contract_hash(PROOF_OP_KIND),
            "implementation_hash": compute_implementation_hash(PROOF_OP_KIND),
            "capability_module_hash": None, "operator_confirmation": "other phase",
            "receipt_accepted_at": "2026-01-01T00:00:00Z",
        }
        c.audit_path.write_text(json.dumps(other_phase_record) + "\n", encoding="utf-8")

        res = c.call(phase_id=PHASE)
        self.assertTrue(res.accepted, res.reason)
        self.assertIn("backfilled", (res.warning or "").lower())
        recs = self._accepted_records(c)
        self.assertEqual(len(recs), 2)

    def test_acceptance_record_exists_helper_fail_safe_on_unreadable_log(self):
        # Unit-level check on the dedup helper's own fail-safe branch: an audit-log PATH that
        # exists as a directory (not a file) cannot be opened for read -- the helper must not
        # raise; it returns False (prefer to append -- an extra audit record is safer than a
        # silently missing one, matching this module's own overriding fail-safe property).
        unreadable = Path(self.tmp) / "not_a_file_audit_log.jsonl"
        unreadable.mkdir()
        self.assertFalse(
            ac._acceptance_record_exists(str(unreadable), "google_sheets", PHASE))

    def test_acceptance_record_exists_helper_skips_malformed_lines(self):
        log = Path(self.tmp) / "log.jsonl"
        log.write_text(
            "not json at all\n"
            + json.dumps({"capability_id": "other", "phase_id": PHASE}) + "\n"
            + json.dumps({"capability_id": "google_sheets", "phase_id": PHASE}) + "\n",
            encoding="utf-8")
        self.assertTrue(
            ac._acceptance_record_exists(str(log), "google_sheets", PHASE))
        self.assertFalse(
            ac._acceptance_record_exists(str(log), "nonexistent_capability", PHASE))

    # -- Sole-writer property (documents the invariant) -------------------

    def test_base_prefix_matches_build_side(self):
        # The duplicated base-sentinel prefix must equal the build-side canonical constant
        # (external_write cannot import the build-side tree — D-B1-a — so it is pinned by test).
        from capability_descriptor_registry import BASE_DESCRIPTOR_ID_PREFIX  # type: ignore
        self.assertEqual(ac.BASE_DESCRIPTOR_ID_PREFIX, BASE_DESCRIPTOR_ID_PREFIX)

    def test_producers_only_emit_accepted_false(self):
        # Documents that the OTHER descriptor writers never emit accepted:true — this ceremony
        # is the sole legitimate flipper.
        from capability_descriptor_registry import base_declared_descriptors  # type: ignore
        for e in base_declared_descriptors():
            self.assertIs(e["accepted"], False)

    def test_pending_migrations_path_matches_build_side(self):
        # The duplicated pending-migrations path must equal the build-side canonical constant
        # (the operator-emitted operator_acceptance module cannot import the build-side tree —
        # D-B1-a — so it is pinned equal to the build-side original by a cross-tree test).
        from external_write import operator_acceptance  # type: ignore
        from upgrade_reconcile import MIGRATION_QUEUE_REL  # type: ignore
        self.assertEqual(operator_acceptance.PENDING_MIGRATIONS_REL, MIGRATION_QUEUE_REL)


# ---------------------------------------------------------------------------
# Invariant 8: NO SEAL GAP (Task 6 — F-34 CARRY fix)
# ---------------------------------------------------------------------------
# The central regression this task closes: a registered adapter whose defining module cannot be
# resolved is silently EXCLUDED from the hashed dependency set (effects_manifest._adapter_module_
# file returns None -> resolve_dependency_files skips it). Both the proof's stored hash and the
# ceremony's own freshly-recomputed hash are computed the SAME (blind) way, so they AGREE with
# each other while neither covers the adapter's bytes — Invariant 2's hash-equality check alone
# can never catch this. This must refuse via the new explicit unresolvable_adapter_seal_gap check
# (Invariant 8), not via a hash mismatch.

_SEAL_GAP_OP_KIND = "_t6_seal_gap_fixture_op"


class _UnresolvableSealGapAdapter:
    """Adapter-protocol-conforming stub whose __module__ is deliberately pointed at a name that
    is NOT in sys.modules, so effects_manifest._adapter_module_file cannot resolve it — the
    exact silent-exclusion shape the CARRY note (T3->T6) flags."""

    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return True


_UnresolvableSealGapAdapter.__module__ = "_no_such_module_ever_t6_seal_gap"


class SealGapAcceptanceTest(unittest.TestCase):

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = self._td.name
        self._prior_contract = _contracts.OPERATION_CONTRACTS.get(_SEAL_GAP_OP_KIND)
        _contracts.OPERATION_CONTRACTS[_SEAL_GAP_OP_KIND] = OperationContract(
            op_kind=_SEAL_GAP_OP_KIND,
            writes=("__fixture__",),
            produces=(),
            dependency_set=(),  # deliberately empty — see _FixtureContractMixin in
                                # test_external_write_effects_manifest.py; isolates the adapter
                                # binding from the static declared dependency_set path.
            verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False,
            risk_class="irreversible_external",
            requires_accepted_phase=True,
            blast_radius_cap=5,
        )
        register_adapter(_SEAL_GAP_OP_KIND, _UnresolvableSealGapAdapter())

    def tearDown(self):
        unregister_adapter(_SEAL_GAP_OP_KIND)
        if self._prior_contract is None:
            _contracts.OPERATION_CONTRACTS.pop(_SEAL_GAP_OP_KIND, None)
        else:
            _contracts.OPERATION_CONTRACTS[_SEAL_GAP_OP_KIND] = self._prior_contract
        self._td.cleanup()

    def test_adapter_module_is_actually_unresolvable(self):
        # Sanity on the vulnerability itself (documents the premise, does not exercise the
        # ceremony): the registered adapter contributes NOTHING to the hashed dependency set,
        # so proof_hash is blind to its bytes.
        self.assertEqual(resolve_dependency_files(_SEAL_GAP_OP_KIND), ())
        self.assertIsNotNone(get_adapter(_SEAL_GAP_OP_KIND))

    def test_unresolvable_adapter_module_refuses_despite_matching_hashes(self):
        c = _Case(self.tmp, descriptors=[
            _descriptor(id="google_sheets", risk_class="irreversible_external")],
            proof=_proof(op_kind=_SEAL_GAP_OP_KIND, capability_id="google_sheets"))
        orig = c.original_bytes()
        # The stored hashes and the ceremony's freshly recomputed ones agree (both blind to the
        # adapter) — proving Invariant 2 alone would have accepted this.
        proof_on_disk = json.loads(c.proof_path.read_text(encoding="utf-8"))
        self.assertEqual(
            proof_on_disk["implementation_hash"],
            compute_implementation_hash(_SEAL_GAP_OP_KIND))
        res = c.call(capability_id="google_sheets")
        self.assertFalse(res.accepted)
        self.assertIn("seal", (res.reason or "").lower())
        self.assertEqual(c.original_bytes(), orig)


if __name__ == "__main__":
    unittest.main()
