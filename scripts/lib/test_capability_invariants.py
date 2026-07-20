"""Tests for the emitted deterministic capability-invariant battery
(external_write.capability_invariants -- Task D1-1, D-Layer-1).

This is the AWB-authored, non-LLM half of the operator project's own self-QA
(cluster D): five composed checks (routing, test-target enum, id coherence,
contract registered, post-acceptance audit) reusing existing signals from
scan.py / write_gate.py / capability_identity.py / contracts.py /
acceptance_ceremony.py -- see that module's own docstring for exactly which
existing primitive backs each check.

ANTI-OVERFIT (v0.13.0 T7 lesson, reused throughout this package's own test
suite): every fixture is written at the REAL emitted relative path
(``agents/capabilities/<capability_id>_capability.py``,
``security/capability_descriptors.json``,
``security/capability_acceptance_log.jsonl``) inside a fresh
``tempfile.TemporaryDirectory()`` -- never a ``copytree`` of the dev tree.
At least two distinct capability_ids are exercised across this file.

Each of checks 1-4 is proven to fail INDEPENDENTLY (only the one input under
test is violated; everything else in the fixture is valid), and a
fully-valid capability is proven to pass all five.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Single-home: import from wizard/agents/lib/external_write (canonical location) -- mirrors
# test_capability_health.py / test_external_write_acceptance_ceremony.py's own convention.
_AGENTS_LIB = Path(__file__).resolve().parents[2] / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import capability_invariants  # noqa: E402
from external_write.acceptance_ceremony import DEFAULT_AUDIT_LOG_PATH  # noqa: E402
# (Task B1, F-74) The shared canonical required-predicate source + the two
# gates that must both consume it -- see capability_invariants.py's Check 7
# docstring and evidence.py's REQUIRED_EVIDENCE_PREDICATES docstring.
from external_write import contracts as contracts_mod  # noqa: E402
from external_write import evidence  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.adapter_registry import register_adapter, unregister_adapter  # noqa: E402
from external_write.copy_run_proof import (  # noqa: E402
    COPY_RUN_PROOF_SCHEMA,
    validate_copy_run_proof,
)
from external_write.proof_hash import SHA256_HEX_LEN  # noqa: E402
from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA  # noqa: E402


CAPABILITIES_DIR_REL = "agents/capabilities"
DESCRIPTOR_SET_REL = "security/capability_descriptors.json"

# An op_kind already seeded/registered in contracts.OPERATION_CONTRACTS at import time (no
# adapter module required) -- reused so fixtures need no adapter-registration setup at all.
VALID_OP_KIND = "set_status"
# Never registered anywhere -- the deliberate check-4 violation.
UNREGISTERED_OP_KIND = "_d1_1_unregistered_probe_op"

# (Task B1, F-74) An op_kind with a registered CONTRACT + (per-test) a registered ADAPTER --
# the deliberate Check-7 fixture. Distinct from VALID_OP_KIND/UNREGISTERED_OP_KIND above:
# those two are permanent module-level constants seeded before this test file ever runs; this
# one's adapter is registered/unregistered per test (setUp/tearDown below) since Check 7 is
# about the ADAPTER's declared predicates, not merely the contract's existence.
_B1_ADAPTER_OP_KIND = "_b1_evidence_predicate_probe_op"


def _register_b1_contract() -> None:
    """Register a minimal, valid OperationContract for `_B1_ADAPTER_OP_KIND` -- mirrors
    `contracts._status_contract`'s shape (a single writes field, the already-registered
    `prestate_snapshot_diff_v1` verifier) so a copy_run_proof built against it can pass
    Clause A independent verification (`verifiers.validate_postwrite_verification`) exactly
    like every seeded field op_kind's proof already does."""
    contracts_mod.register_contract(OperationContract(
        op_kind=_B1_ADAPTER_OP_KIND,
        writes=("value",),
        produces=(),
        dependency_set=(),
        verifier_set=("prestate_snapshot_diff_v1",),
        introduces_persistent_binding=False,
    ))


class _B1FullPredicateAdapter:
    """Test-fixture adapter (Task B1, F-74) declaring BOTH required evidence
    predicates (`evidence.REQUIRED_EVIDENCE_PREDICATES`, as of this task:
    verify_apply_landed + verify_undo_restored) -- the 'clean' case. Defines
    every member of `adapter_registry.Adapter`'s protocol as a bare no-op so
    `register_adapter` (which captures the class's methods directly, with no
    getattr default) has something real to capture."""

    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return {}

    def verify_apply_landed(self, evidence):
        return True

    def verify_undo_restored(self, evidence):
        return True


class _B1MissingUndoPredicateAdapter:
    """Test-fixture adapter (Task B1, F-74) declaring ONLY `verify_apply_landed` --
    missing the required `verify_undo_restored` -- the deliberate F-74 violation this
    task's Check 7 exists to catch before a live trial, not merely mid-proof."""

    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return {}

    def verify_apply_landed(self, evidence):
        return True


def _b1_verification():
    """A postwrite-verification-v1 record that passes Clause A against the
    `prestate_snapshot_diff_v1` verifier `_register_b1_contract` registers --
    mirrors `test_external_write_copy_run_proof_evidence.py`'s own `_verification()`
    helper exactly (same verifier, same lineage shape)."""
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
        "invariant_checked": "b1 probe value stable",
        "evidence_ref": "agents/handoffs/.b1_probe_ev.txt",
    }


def _b1_copy_run_proof():
    """A copy_run_proof-v1 artifact for `_B1_ADAPTER_OP_KIND`, complete with
    apply/undo evidence content -- so `validate_copy_run_proof` reaches the
    evidence-predicate gate (Task 2, A2 proof-time) rather than failing earlier
    on a structural/record check unrelated to this task."""
    return {
        "schema": COPY_RUN_PROOF_SCHEMA,
        "operation_id": "b1-op-001",
        "op_kind": _B1_ADAPTER_OP_KIND,
        "data_class": "test_rows",
        "copy_source_ref": "copies/copy.csv",
        "prestate_snapshot_ref": "copies/copy.prestate.csv",
        "copy_apply_proof": {
            "apply_receipt_ref": "agents/handoffs/.apply_receipt.json",
            "apply_verification": _b1_verification(),
            "apply_evidence": {"unit_id": "u1", "poststate": {}},
        },
        "copy_undo_proof": {
            "undo_receipt_ref": "agents/handoffs/.undo_receipt.json",
            "undo_verification": _b1_verification(),
            "undo_evidence": {"unit_id": "u1", "poststate": {}},
        },
        "durability_checks": [],
        "accepted_for_live_use": True,
        "implementation_hash": "a" * SHA256_HEX_LEN,
        "contract_hash": "b" * SHA256_HEX_LEN,
    }


_CLEAN_SOURCE = '''"""{name} -- gate-clean capability module (test fixture)."""

from typing import Any

OP_KIND = "{op_kind}"


def describe() -> str:
    return "{name} ready"


def propose_operations(facade: Any, batch_id: str):
    return []
'''

_CLEAN_SOURCE_WITH_SURFACE = '''"""{name} -- gate-clean capability module with a declared SURFACE (test fixture)."""

from typing import Any

OP_KIND = "{op_kind}"
SURFACE = "{surface}"


def describe() -> str:
    return "{name} ready"


def propose_operations(facade: Any, batch_id: str):
    return []
'''

_ROUTING_VIOLATION_SOURCE = '''"""{name} -- capability wired to the raw kernel write primitive (test fixture)."""

from typing import Any

OP_KIND = "{op_kind}"

from external_write.adapters import run_operation


def propose_operations(facade: Any, batch_id: str):
    return []


def run():
    return run_operation
'''


def _base_descriptor_entry(capability_id, **overrides):
    entry = {
        "id": capability_id,
        "name": capability_id,
        "action_class": "in_place_edit",
        "risk_class": "reversible_external",
        "recovery_profile_ref": None,
        "declared_test_target": "copy",
        "blast_radius_cap": 5,
        "accepted": False,
    }
    entry.update(overrides)
    return entry


class CapabilityInvariantsTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_capability(self, capability_id: str, source: str) -> Path:
        d = self.project_root / CAPABILITIES_DIR_REL
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{capability_id}_capability.py"
        path.write_text(source, encoding="utf-8")
        return path

    def _write_descriptor_set(self, entries):
        path = self.project_root / DESCRIPTOR_SET_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries), encoding="utf-8")

    def _write_paused_marker(self, capability_id: str) -> None:
        # (Task A2, F-70) A hand-planted pause marker -- mirrors
        # capability_health.py's own test fixture helper of the same name. A bare ``.pause``
        # touch-file is sufficient evidence of residue for check 6 (see that check's own
        # "any existing path counts, regardless of shape" fail-closed convention).
        d = self.project_root / capability_invariants.PAUSED_MECHANISMS_DIR_REL
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{capability_id}.pause").write_text("", encoding="utf-8")

    def _write_audit_record(self, capability_id, phase_id, **extra):
        # (R-3, cross-vendor review fix) A real ceremony append always carries a non-empty
        # `implementation_hash` + `op_kind` (see acceptance_ceremony.is_valid_acceptance_record) --
        # this fixture defaults to a WELL-FORMED record shape so it exercises this test suite's
        # own "real, complete audit record" cases; a caller can still override either field via
        # `**extra` to build a deliberately-junk record for a negative test.
        path = self.project_root / DEFAULT_AUDIT_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "capability_acceptance_record-v1",
            "capability_id": capability_id,
            "phase_id": phase_id,
            "implementation_hash": "test-fixture-implementation-hash",
            "op_kind": VALID_OP_KIND,
        }
        record.update(extra)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def _check(self, capability_id):
        return capability_invariants.check_capability_invariants(
            str(self.project_root), capability_id)

    def _write_project_file(self, relpath: str, content: str) -> Path:
        """Write ``content`` at ``relpath`` under ``self.project_root`` -- used
        by the D1-2 test-quality fixtures to place a capability's test file at
        a real-shaped relative path (there is no fixed convention for WHERE a
        capability's test lives -- see capability_invariants.py's D1-2 module
        docstring -- so discovery must find it, not assume it)."""
        path = self.project_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _check_quality(self, capability_id):
        return capability_invariants.check_test_quality(
            str(self.project_root), capability_id)

    def _stage_real_external_write(self) -> None:
        """Copy the REAL, shipped ``external_write`` package into this fixture
        project's own ``agents/lib/`` -- this is exactly what a real operator
        project actually has (``agents/lib/external_write`` ships verbatim
        into every operator project; see that package's own "Stdlib only --
        this module ships into the operator's own runtime" docstring notes).
        Needed so a fixture whose test imports ``run_enveloped_operation`` has
        something REAL to import at subprocess-run time -- a genuinely
        runnable baseline, not just an AST-only reference (review finding:
        the known-bad-fails probe's baseline-green check would otherwise be
        exercised only by an import that can never actually succeed)."""
        dest = self.project_root / "agents" / "lib" / "external_write"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(_AGENTS_LIB / "external_write", dest)

    def _assert_no_traceback(self, result):
        self.assertNotIn("Traceback", result.operator_message)


class TestFullyValidCapabilityPassesAll(CapabilityInvariantsTestBase):
    def test_fully_valid_capability_passes_all_checks(self):
        cap_id = "acme_status_sync"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Acme Status Sync", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")
        self.assertEqual(result.failures, [])
        self._assert_no_traceback(result)

    def test_second_distinct_capability_also_passes_all_checks(self):
        # A second, differently-named capability_id -- proves the battery is not
        # accidentally keyed to the first fixture's id.
        cap_id = "beta_priority_sync"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Beta Priority Sync", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")
        self._assert_no_traceback(result)


class TestRoutingCheckIndependent(CapabilityInvariantsTestBase):
    def test_raw_run_operation_reference_fails_only_routing(self):
        cap_id = "routing_violation_cap"
        self._write_capability(
            cap_id,
            _ROUTING_VIOLATION_SOURCE.format(name="Routing Violation Cap", op_kind=VALID_OP_KIND),
        )
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Routing:") for f in result.failures),
            f"expected a Routing failure, got {result.failures!r}",
        )
        self.assertFalse(
            any(f.startswith("Test target:") for f in result.failures),
            f"test-target check should not fail for this fixture: {result.failures!r}",
        )
        self.assertFalse(
            any(f.startswith("Contract registered:") for f in result.failures),
            f"contract-registered check should not fail for this fixture: {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_missing_source_file_fails_routing(self):
        cap_id = "no_source_cap"
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])
        # No capability source file is written at all.

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(any(f.startswith("Routing:") for f in result.failures))
        self._assert_no_traceback(result)


class TestTestTargetEnumCheckIndependent(CapabilityInvariantsTestBase):
    def test_out_of_vocabulary_test_target_fails_only_test_target(self):
        cap_id = "bad_test_target_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Bad Test Target Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, declared_test_target="banana")])

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Test target:") for f in result.failures),
            f"expected a Test target failure, got {result.failures!r}",
        )
        self.assertFalse(any(f.startswith("Routing:") for f in result.failures))
        self.assertFalse(any(f.startswith("Id coherence:") for f in result.failures))
        self.assertFalse(any(f.startswith("Contract registered:") for f in result.failures))
        self._assert_no_traceback(result)

    def test_each_valid_test_target_value_passes(self):
        for target in ("copy", "dry_run", "bounded_sample", "native_undo"):
            with self.subTest(target=target):
                cap_id = f"valid_target_{target}_cap"
                self._write_capability(
                    cap_id, _CLEAN_SOURCE.format(name=cap_id, op_kind=VALID_OP_KIND))
                self._write_descriptor_set(
                    [_base_descriptor_entry(cap_id, declared_test_target=target)])

                result = self._check(cap_id)

                self.assertFalse(
                    any(f.startswith("Test target:") for f in result.failures),
                    f"declared_test_target={target!r} should be valid: {result.failures!r}",
                )


class TestIdCoherenceCheckIndependent(CapabilityInvariantsTestBase):
    def test_descriptor_id_set_to_surface_fails_only_id_coherence(self):
        cap_id = "acme_crm_sync"
        surface = "acme_crm"
        self._write_capability(
            cap_id,
            _CLEAN_SOURCE_WITH_SURFACE.format(
                name="Acme CRM Sync", op_kind=VALID_OP_KIND, surface=surface),
        )
        # The descriptor's "id" is wrongly set to the capability's own SURFACE value instead
        # of its capability_id -- the estate-class drift assert_identity_coherent exists to
        # catch even though build_capability_index's own surface-corroboration would otherwise
        # resolve it.
        self._write_descriptor_set([_base_descriptor_entry(surface)])

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Id coherence:") for f in result.failures),
            f"expected an Id coherence failure, got {result.failures!r}",
        )
        self.assertFalse(any(f.startswith("Routing:") for f in result.failures))
        self._assert_no_traceback(result)

    def test_coherent_descriptor_id_passes_id_coherence(self):
        cap_id = "coherent_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Coherent Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(any(f.startswith("Id coherence:") for f in result.failures))


class TestContractRegisteredCheckIndependent(CapabilityInvariantsTestBase):
    def test_unregistered_op_kind_fails_only_contract_registered(self):
        cap_id = "unregistered_op_kind_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Unregistered Op Kind Cap",
                                          op_kind=UNREGISTERED_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Contract registered:") for f in result.failures),
            f"expected a Contract registered failure, got {result.failures!r}",
        )
        self.assertFalse(any(f.startswith("Routing:") for f in result.failures))
        self.assertFalse(any(f.startswith("Test target:") for f in result.failures))
        self.assertFalse(any(f.startswith("Id coherence:") for f in result.failures))
        self._assert_no_traceback(result)

    def test_registered_op_kind_passes_contract_registered(self):
        cap_id = "registered_op_kind_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Registered Op Kind Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(any(f.startswith("Contract registered:") for f in result.failures))


class TestOpKindLiteralLastAssignmentWins(CapabilityInvariantsTestBase):
    # (DR-4, mirrors the xvendor R-6 fix already landed for capability_identity's
    # sibling _extract_surface) A capability module that assigns OP_KIND more than
    # once at module level must be read by its LAST assignment -- mirroring Python's
    # own runtime last-assignment-wins semantics. Returning the FIRST assignment (the
    # prior behavior) decouples this AST-only static read from what the module
    # actually holds at runtime.
    _REASSIGNED_OP_KIND_SOURCE = '''"""{name} -- OP_KIND reassigned at module level (test fixture)."""

from typing import Any

OP_KIND = "{first_op_kind}"
# some code in between
OP_KIND = "{second_op_kind}"


def describe() -> str:
    return "{name} ready"


def propose_operations(facade: Any, batch_id: str):
    return []
'''

    def test_last_op_kind_assignment_is_used_when_it_is_registered(self):
        # FIRST assignment is the unregistered op_kind, LAST is the registered one --
        # the check must pass (using the last assignment), proving last-wins.
        cap_id = "reassigned_op_kind_registered_last"
        self._write_capability(
            cap_id,
            self._REASSIGNED_OP_KIND_SOURCE.format(
                name="Reassigned Op Kind Registered Last",
                first_op_kind=UNREGISTERED_OP_KIND,
                second_op_kind=VALID_OP_KIND,
            ),
        )
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(
            any(f.startswith("Contract registered:") for f in result.failures),
            f"expected the LAST (registered) OP_KIND assignment to be used, got "
            f"{result.failures!r}",
        )

    def test_last_op_kind_assignment_is_used_when_it_is_unregistered(self):
        # FIRST assignment is the registered op_kind, LAST is the unregistered one --
        # the check must FAIL (still using the last assignment), proving this isn't
        # merely "whichever one happens to be registered."
        cap_id = "reassigned_op_kind_unregistered_last"
        self._write_capability(
            cap_id,
            self._REASSIGNED_OP_KIND_SOURCE.format(
                name="Reassigned Op Kind Unregistered Last",
                first_op_kind=VALID_OP_KIND,
                second_op_kind=UNREGISTERED_OP_KIND,
            ),
        )
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertTrue(
            any(f.startswith("Contract registered:") for f in result.failures),
            f"expected the LAST (unregistered) OP_KIND assignment to be used, got "
            f"{result.failures!r}",
        )


class TestAdapterEvidencePredicatesCheckIndependent(CapabilityInvariantsTestBase):
    """Task B1, F-74: Check 7 -- does this capability's registered adapter declare
    every REQUIRED evidence predicate (`external_write.evidence.
    REQUIRED_EVIDENCE_PREDICATES`) -- the SAME canonical list
    `copy_run_proof.validate_copy_run_proof` reads at proof/run time. Before this
    check existed, a capability whose adapter was missing a required predicate
    passed this self-QA and only failed mid-trial in copy_run_proof (see
    test_external_write_copy_run_proof_evidence.py's
    TestAdapterWithNoPredicateFailsClosed for that same gap's proof/run-time half)."""

    def setUp(self):
        super().setUp()
        _register_b1_contract()

    def tearDown(self):
        unregister_adapter(_B1_ADAPTER_OP_KIND)
        super().tearDown()

    def test_missing_required_predicate_fails_only_adapter_evidence_predicates(self):
        register_adapter(_B1_ADAPTER_OP_KIND, _B1MissingUndoPredicateAdapter())
        cap_id = "b1_missing_undo_predicate_cap"
        self._write_capability(
            cap_id,
            _CLEAN_SOURCE.format(
                name="B1 Missing Undo Predicate Cap", op_kind=_B1_ADAPTER_OP_KIND),
        )
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Adapter evidence predicates:") for f in result.failures),
            f"expected an Adapter evidence predicates failure, got {result.failures!r}",
        )
        adapter_failure = next(
            f for f in result.failures if f.startswith("Adapter evidence predicates:"))
        self.assertIn("verify_undo_restored", adapter_failure)
        self.assertNotIn("verify_apply_landed", adapter_failure)
        # The locked plain-language design (F-74's own wording): "this capability's
        # adapter must define how it verifies its write landed / can be undone; it
        # stays paused until it does."
        self.assertIn("stays paused until it does", adapter_failure)
        # Independent of every other check -- the fixture is otherwise clean.
        self.assertFalse(any(f.startswith("Routing:") for f in result.failures))
        self.assertFalse(any(f.startswith("Test target:") for f in result.failures))
        self.assertFalse(any(f.startswith("Id coherence:") for f in result.failures))
        self.assertFalse(any(f.startswith("Contract registered:") for f in result.failures))
        self._assert_no_traceback(result)

    def test_full_predicates_declared_passes_adapter_evidence_predicates(self):
        register_adapter(_B1_ADAPTER_OP_KIND, _B1FullPredicateAdapter())
        cap_id = "b1_full_predicates_cap"
        self._write_capability(
            cap_id,
            _CLEAN_SOURCE.format(name="B1 Full Predicates Cap", op_kind=_B1_ADAPTER_OP_KIND),
        )
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")
        self.assertEqual(result.failures, [])
        self._assert_no_traceback(result)

    def test_unregistered_adapter_op_kind_is_na_not_a_failure(self):
        # set_status (VALID_OP_KIND) has NO registered adapter at all, by permanent
        # design (adapter_registry.py) -- this check must never fire for it, mirroring
        # copy_run_proof.validate_copy_run_proof's identical scope note.
        cap_id = "b1_unregistered_adapter_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="B1 Unregistered Adapter Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(
            any(f.startswith("Adapter evidence predicates:") for f in result.failures))


class _B1RaisingPredicateAdapter:
    """Task B2, F-75: mirrors `capability_code_scaffold.render_missing_
    evidence_predicate_stub`'s own auto-scaffolded shape verbatim -- BOTH
    required predicates are DECLARED (present, callable), but each RAISES
    `NotImplementedError` rather than doing a real check. This is the
    anti-trust-theater crux documented here directly: Check 7 only checks
    structural PRESENCE (`getattr(...) is None or not callable(...)`), so it
    has no way to know a declared predicate merely raises -- that is
    `copy_run_proof.validate_copy_run_proof`'s job (see Task B2's own fix
    there, exercised end-to-end by
    test_external_write_copy_run_proof_evidence.py's
    TestAutoScaffoldedStubFailsClosedNotUncaughtTraceback). Check 7 passing
    here is NOT a gap: it is one deliberate half of a two-gate design where
    the OTHER gate is the one that actually calls the predicate and can
    therefore catch a raise."""

    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return {}

    def verify_apply_landed(self, evidence):
        raise NotImplementedError(
            "this adapter must define how it verifies the external write landed; "
            "the capability stays paused until this is implemented and proved")

    def verify_undo_restored(self, evidence):
        raise NotImplementedError(
            "this adapter must define how it verifies the external write can be "
            "undone; the capability stays paused until this is implemented and proved")


class TestAdapterEvidencePredicatesCheck7StructuralOnly(CapabilityInvariantsTestBase):
    """Task B2, F-75: documents (does not merely assume) exactly what Check 7
    does and does not catch about an auto-scaffolded `NotImplementedError`
    stub -- the crux this task's fix relies on. Check 7 is a structural
    presence/callability check; it does not invoke the predicate, so a stub
    that raises when called still satisfies it. The capability is NOT thereby
    live-safe: `copy_run_proof.validate_copy_run_proof` (proof time) DOES
    call it, and Task B2 fixed that gate to fail closed on the raise (see
    test_external_write_copy_run_proof_evidence.py). Together, the two gates
    still guarantee the capability cannot go live on a stub alone."""

    def setUp(self):
        super().setUp()
        _register_b1_contract()

    def tearDown(self):
        unregister_adapter(_B1_ADAPTER_OP_KIND)
        super().tearDown()

    def test_check_7_passes_a_present_but_raising_stub_by_structural_design(self):
        register_adapter(_B1_ADAPTER_OP_KIND, _B1RaisingPredicateAdapter())
        cap_id = "b2_raising_stub_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="B2 Raising Stub Cap", op_kind=_B1_ADAPTER_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertTrue(
            result.ok,
            "Check 7 checks structural presence/callability only -- a stub that "
            f"raises when called must still satisfy it; got failures: {result.failures!r}")
        self._assert_no_traceback(result)

        # BUT the same stub still fails the OTHER gate (proof time) that
        # actually calls it -- the capability cannot go live on Check 7 alone.
        proof_result = validate_copy_run_proof(_b1_copy_run_proof())
        self.assertFalse(
            proof_result.ok,
            "a present-but-raising predicate must still fail the proof/run-time "
            "gate -- Check 7 passing must never be read as 'safe to go live'")
        self.assertIn("verify_apply_landed raised", proof_result.reason)


class TestAdapterEvidencePredicatesSharedContractCoupling(CapabilityInvariantsTestBase):
    """Task B1, F-74: proves SINGLE-SOURCE coupling, not two drifting lists --
    adding a name to `evidence.REQUIRED_EVIDENCE_PREDICATES` makes BOTH the
    self-QA gate (`capability_invariants.check_capability_invariants`) AND the
    proof/run-time gate (`copy_run_proof.validate_copy_run_proof`) require it,
    against the SAME registered adapter/contract fixture, with no code change
    to either gate."""

    def setUp(self):
        super().setUp()
        _register_b1_contract()
        register_adapter(_B1_ADAPTER_OP_KIND, _B1FullPredicateAdapter())

    def tearDown(self):
        unregister_adapter(_B1_ADAPTER_OP_KIND)
        super().tearDown()

    def test_baseline_both_gates_pass_with_current_required_set(self):
        cap_id = "b1_coupling_baseline_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="B1 Coupling Baseline Cap", op_kind=_B1_ADAPTER_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        selfqa_result = self._check(cap_id)
        proof_result = validate_copy_run_proof(_b1_copy_run_proof())

        self.assertTrue(selfqa_result.ok, selfqa_result.failures)
        self.assertTrue(proof_result.ok, proof_result.reason)

    def test_adding_required_predicate_to_shared_contract_requires_it_in_both_gates(self):
        cap_id = "b1_coupling_new_predicate_cap"
        self._write_capability(
            cap_id,
            _CLEAN_SOURCE.format(
                name="B1 Coupling New Predicate Cap", op_kind=_B1_ADAPTER_OP_KIND),
        )
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        # `_B1FullPredicateAdapter` declares neither this fictitious predicate nor
        # anything else beyond the CURRENT required pair -- adding it to the shared
        # contract, with no other change, must make it required by BOTH gates.
        new_required = evidence.REQUIRED_EVIDENCE_PREDICATES + ("verify_b1_new_predicate_probe",)
        with mock.patch.object(evidence, "REQUIRED_EVIDENCE_PREDICATES", new_required):
            selfqa_result = self._check(cap_id)
            proof_result = validate_copy_run_proof(_b1_copy_run_proof())

        self.assertFalse(
            selfqa_result.ok, "expected self-QA to require the newly-added predicate too")
        self.assertTrue(
            any("verify_b1_new_predicate_probe" in f for f in selfqa_result.failures),
            f"expected the new predicate name in the failure, got {selfqa_result.failures!r}",
        )
        self.assertFalse(
            proof_result.ok,
            "expected the proof/run-time gate to require the newly-added predicate too",
        )
        self.assertIn("verify_b1_new_predicate_probe", proof_result.reason)

        # After the patch is undone, the SAME fixture (adapter unchanged) passes again --
        # proves the failure above was caused by the shared contract, not a permanent
        # side effect of this test leaking into the next one.
        selfqa_after = self._check(cap_id)
        proof_after = validate_copy_run_proof(_b1_copy_run_proof())
        self.assertTrue(selfqa_after.ok, selfqa_after.failures)
        self.assertTrue(proof_after.ok, proof_after.reason)


class TestAuditCheckPostAcceptanceOnly(CapabilityInvariantsTestBase):
    PHASE_ID = "phase_d1_1_test"

    def test_not_yet_accepted_capability_does_not_fail_audit(self):
        cap_id = "not_accepted_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Not Accepted Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, accepted=False, phase_id=self.PHASE_ID)])
        # No audit log at all -- must still not fail, since acceptance itself is False.

        result = self._check(cap_id)

        self.assertFalse(any(f.startswith("Audit record:") for f in result.failures))

    def test_accepted_capability_missing_audit_record_fails_audit(self):
        cap_id = "accepted_missing_audit_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Accepted Missing Audit Cap",
                                          op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, accepted=True, phase_id=self.PHASE_ID)])
        # Accepted, but no audit log file/entry exists at all.

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Audit record:") for f in result.failures),
            f"expected an Audit record failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_accepted_capability_with_matching_audit_record_passes_audit(self):
        cap_id = "accepted_with_audit_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Accepted With Audit Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, accepted=True, phase_id=self.PHASE_ID)])
        self._write_audit_record(cap_id, self.PHASE_ID)

        result = self._check(cap_id)

        self.assertFalse(
            any(f.startswith("Audit record:") for f in result.failures),
            f"expected no Audit record failure, got {result.failures!r}",
        )
        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")


class TestMarkerResidueCheckIndependent(CapabilityInvariantsTestBase):
    """Task A2 / F-70 (crash-safety half) -- the 6th deterministic check: an ACCEPTED
    capability must carry no residual ``paused_live_write`` marker. This is the emitted self-QA's
    own independent catch for exactly the F-70 defect class (reconcile-on-accept / reconcile-on-
    read both exist to clear this marker; this check fires if either is ever bypassed)."""

    PHASE_ID = "phase_a2_invariants_test"

    def test_accepted_capability_with_residual_marker_fails_marker_residue(self):
        cap_id = "accepted_with_marker_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Accepted With Marker Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, accepted=True, phase_id=self.PHASE_ID)])
        self._write_audit_record(cap_id, self.PHASE_ID)
        self._write_paused_marker(cap_id)

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Marker residue:") for f in result.failures),
            f"expected a Marker residue failure, got {result.failures!r}",
        )
        # Independent: every OTHER check for this otherwise-valid, accepted capability still
        # passes -- only the marker-residue check fires.
        self.assertFalse(any(f.startswith("Routing:") for f in result.failures))
        self.assertFalse(any(f.startswith("Test target:") for f in result.failures))
        self.assertFalse(any(f.startswith("Id coherence:") for f in result.failures))
        self.assertFalse(any(f.startswith("Contract registered:") for f in result.failures))
        self.assertFalse(any(f.startswith("Audit record:") for f in result.failures))
        self._assert_no_traceback(result)

    def test_accepted_capability_without_marker_passes_marker_residue(self):
        cap_id = "accepted_clear_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Accepted Clear Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, accepted=True, phase_id=self.PHASE_ID)])
        self._write_audit_record(cap_id, self.PHASE_ID)
        # No marker written at all.

        result = self._check(cap_id)

        self.assertFalse(any(f.startswith("Marker residue:") for f in result.failures))
        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")

    def test_not_yet_accepted_capability_with_marker_does_not_fail_marker_residue(self):
        # A pause marker on a NOT-yet-accepted capability is the NORMAL paused/pending-migration
        # state, not a defect -- N/A here, mirroring the audit check's own pre-acceptance N/A.
        cap_id = "not_accepted_with_marker_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Not Accepted With Marker Cap",
                                          op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id, accepted=False)])
        self._write_paused_marker(cap_id)

        result = self._check(cap_id)

        self.assertFalse(any(f.startswith("Marker residue:") for f in result.failures))

    def test_marker_present_as_unreadable_json_still_fails_marker_residue(self):
        # Fail-closed: a ``.json`` marker present in an unexpected/unreadable shape (here, a
        # directory instead of a regular file) still counts as residue -- mirrors
        # capability_health's own "unexpected shape is never silently read as absent" doctrine.
        cap_id = "accepted_weird_marker_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Accepted Weird Marker Cap",
                                          op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, accepted=True, phase_id=self.PHASE_ID)])
        self._write_audit_record(cap_id, self.PHASE_ID)
        marker_dir = self.project_root / capability_invariants.PAUSED_MECHANISMS_DIR_REL
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / f"{cap_id}.json").mkdir()

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(any(f.startswith("Marker residue:") for f in result.failures))


class TestPausedMechanismsDirAntiDrift(unittest.TestCase):
    """(Task A2, F-70) Pins ``capability_invariants.PAUSED_MECHANISMS_DIR_REL`` -- duplicated by
    value, never imported -- against ``capability_health.py``'s own same-named constant, mirroring
    ``test_capability_health.py``'s own ``TestPathConstantsAntiDrift`` pattern for that module's
    four duplicated path constants."""

    def test_paused_mechanisms_dir_rel_matches_capability_health_constant(self):
        from external_write import capability_health
        self.assertEqual(
            capability_invariants.PAUSED_MECHANISMS_DIR_REL,
            capability_health.PAUSED_MECHANISMS_DIR_REL,
        )


# =============================================================================
# Task D1-2: deterministic test-quality probes (check_test_quality)
# =============================================================================
#
# ANTI-OVERFIT: every capability module here is written at the real emitted
# relpath (``agents/capabilities/<capability_id>_capability.py``); each
# fixture's OWN test file is written at a real-shaped relpath
# (``agents/capabilities/tests/test_<capability_id>_capability.py``) inside a
# fresh ``tempfile.TemporaryDirectory()`` -- never a copytree of this dev
# tree. Five distinct capability_ids are exercised across this section.
#
# Because ``check_test_quality`` always runs BOTH probes together, a fixture
# built to exercise probe 1 (producer-entrypoint, AST-only -- does not
# execute the test file) is deliberately kept SELF-CONTAINED with respect to
# probe 2 (known-bad-fails, which DOES actually execute the discovered test
# file(s) via a real subprocess against a temp copy): the "genuine"/"inert"
# fixtures below import ONLY their own capability module (never
# ``external_write``, which is not present in these minimal fixture trees),
# so that whether they fail when run is driven ENTIRELY by the deliberate
# mutation this task's own docstring describes -- not by an unrelated import
# error. This was verified manually before writing these tests: an
# unmutated capability module's test passes; the exact same test, run
# against the mutated copy ``check_test_quality`` builds internally, fails
# with the mutation's own ``RuntimeError`` -- proving the mechanism (not just
# the assertion) actually works.


class TestProducerEntrypointProbe(CapabilityInvariantsTestBase):
    def test_handrolled_standin_test_is_flagged(self):
        # Required test (a): a test that builds a hand-rolled Operation stand-in
        # (drives a fake instead of the real producer) must be FLAGGED.
        cap_id = "standin_flagged_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Standin Flagged Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: hand-rolled Operation stand-in test (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}  # noqa: F401 -- present so discovery finds this file


class Operation:
    """Hand-rolled stand-in -- NOT external_write.operations.Operation."""

    def __init__(self, surface, op_kind):
        self.surface = surface
        self.op_kind = op_kind


def _fake_run(op):
    return "fake-ok"


class TestStandinFlaggedCap(unittest.TestCase):
    def test_fake_operation_flow(self):
        op = Operation(surface="acme", op_kind="set_status")
        self.assertEqual(_fake_run(op), "fake-ok")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Producer entrypoint:") and "stand-in" in f for f in result.failures),
            f"expected a Producer entrypoint stand-in failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_real_producer_entrypoint_reference_passes(self):
        # Required test (b): a test that references the real producer entrypoint
        # (the capability module + run_enveloped_operation) must PASS the
        # producer-entrypoint probe -- no "stand-in" / "none of this
        # capability's test file(s)" failure line.
        #
        # (Review finding fix) The real ``external_write`` package is STAGED
        # into this fixture project so the import actually resolves and the
        # test genuinely runs at subprocess time -- a fixture whose
        # ``run_enveloped_operation`` import can never succeed would die with
        # an unrelated ModuleNotFoundError before ever exercising anything,
        # which is exactly the never-ran/baseline-not-green gap this task
        # fixes. With a genuine, runnable baseline, this fixture now proves
        # BOTH probes pass -- assert full ``result.ok``, not just the
        # producer-entrypoint line.
        cap_id = "real_entrypoint_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Real Entrypoint Cap", op_kind=VALID_OP_KIND))
        self._stage_real_external_write()
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: real producer-entrypoint reference test (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

from external_write.capability_api import run_enveloped_operation  # noqa: F401

if False:  # AST-only guarded call (DR-2 fix) -- never executed; proves this test
           # file's entrypoint reference is a genuine ast.Call, not merely an
           # import, without ever performing a live write when discovered/collected.
    run_enveloped_operation()


class TestRealEntrypointCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "Real Entrypoint Cap ready")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")
        self.assertEqual(result.failures, [])
        self._assert_no_traceback(result)

    def test_import_only_no_call_entrypoint_reference_is_flagged(self):
        # (DR-2 required test) A test file that IMPORTS the real entrypoint but
        # never actually CALLS it must be FLAGGED -- an import-only reference
        # proves the test file merely names the entrypoint, not that any test
        # method actually exercises it.
        cap_id = "import_only_no_call_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Import Only No Call Cap", op_kind=VALID_OP_KIND))
        self._stage_real_external_write()
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: imports the real entrypoint but never calls it (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

from external_write.capability_api import run_enveloped_operation  # noqa: F401 -- imported, never called


class TestImportOnlyNoCallCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "Import Only No Call Cap ready")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Producer entrypoint:") for f in result.failures),
            f"expected a Producer entrypoint failure for an import-only, never-called "
            f"entrypoint reference, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_attribute_access_call_to_entrypoint_passes(self):
        # (DR-2 required test) A legitimate attribute-access call
        # (``import external_write.capability_api`` ... ``capability_api.
        # run_enveloped_operation(...)``) must PASS -- the probe must not
        # require the specific ``from ... import run_enveloped_operation``
        # then bare-call shape.
        cap_id = "attr_access_call_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Attr Access Call Cap", op_kind=VALID_OP_KIND))
        self._stage_real_external_write()
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: module import + attribute-access CALL to the real entrypoint (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

import external_write.capability_api


class TestAttrAccessCallCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "Attr Access Call Cap ready")

    def test_attribute_access_call_shape(self):
        if False:  # AST-only guarded call -- never executed; this test file
                   # never performs a live write, but the AST still carries a
                   # genuine ast.Call node reaching the real entrypoint via
                   # attribute access, exactly the shape DR-2 must accept.
            external_write.capability_api.run_enveloped_operation()


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")
        self.assertEqual(result.failures, [])
        self._assert_no_traceback(result)

    def test_from_package_import_module_then_attribute_call_passes(self):
        # (selfqa idiom fix) `from external_write import capability_api` (an
        # ast.ImportFrom importing the MODULE capability_api from the PACKAGE
        # external_write) followed by `capability_api.run_enveloped_operation(...)`
        # must PASS -- this is a common, honest idiom distinct from both
        # `from external_write.capability_api import run_enveloped_operation`
        # (covered above) and `import external_write.capability_api` (covered
        # by test_attribute_access_call_to_entrypoint_passes). Before this
        # fix, the ImportFrom branch only ever added a name to `module_refs`
        # via the `import`-statement branch, so `capability_api` was never
        # recognized as an imported real module here and the attribute call's
        # base never traced back to it -- a reachable honest-code false-block.
        cap_id = "from_package_import_module_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="From Package Import Module Cap", op_kind=VALID_OP_KIND))
        self._stage_real_external_write()
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: `from external_write import capability_api` + attribute-access CALL (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

from external_write import capability_api


class TestFromPackageImportModuleCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "From Package Import Module Cap ready")

    def test_attribute_access_call_shape(self):
        if False:  # AST-only guarded call -- never executed; this test file
                   # never performs a live write, but the AST still carries a
                   # genuine ast.Call node reaching the real entrypoint via
                   # attribute access, exactly the shape this fix must accept.
            capability_api.run_enveloped_operation()


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")
        self.assertEqual(result.failures, [])
        self._assert_no_traceback(result)

    def test_local_fake_entrypoint_def_and_bare_call_no_import_is_flagged(self):
        # (Critical fix, task review) A test file that defines its OWN local
        # `def run_enveloped_operation(): ...` and calls it -- importing the
        # REAL entrypoint from NOWHERE -- must be FLAGGED. Before the fix,
        # `_ast_references_entrypoint` seeded `call_names` with the entrypoint
        # name UNCONDITIONALLY, so this local fake's bare call satisfied the
        # probe even though the real entrypoint was never imported.
        cap_id = "local_fake_entrypoint_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Local Fake Entrypoint Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: locally-defined fake entrypoint, no real import (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}  # noqa: F401 -- present so discovery finds this file


def run_enveloped_operation():
    """Locally-defined FAKE -- NOT external_write.capability_api's real one."""
    return "fake-ok"


class TestLocalFakeEntrypointCap(unittest.TestCase):
    def test_fake_entrypoint_flow(self):
        self.assertEqual(run_enveloped_operation(), "fake-ok")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Producer entrypoint:") for f in result.failures),
            f"expected a Producer entrypoint failure for a local fake entrypoint def+call with "
            f"no real import, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_fake_object_attribute_call_no_import_is_flagged(self):
        # (Critical fix, task review) `FakeThing().run_enveloped_operation()` --
        # an attribute-access CALL on an object that was never imported as the
        # real entrypoint's module -- must be FLAGGED. Before the fix, the
        # attribute branch matched on `func.attr in _ENTRYPOINT_IMPORT_NAMES`
        # alone, accepting ANY object's `.run_enveloped_operation(...)` call
        # regardless of what (if anything) was actually imported.
        cap_id = "fake_object_attr_call_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Fake Object Attr Call Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: attribute-access call on a never-imported fake object (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}  # noqa: F401 -- present so discovery finds this file


class FakeThing:
    """A locally-defined object with NO relation to the real capability_api module."""

    def run_enveloped_operation(self):
        return "fake-ok"


class TestFakeObjectAttrCallCap(unittest.TestCase):
    def test_fake_attr_call_flow(self):
        self.assertEqual(FakeThing().run_enveloped_operation(), "fake-ok")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Producer entrypoint:") for f in result.failures),
            f"expected a Producer entrypoint failure for a fake object's attribute-access call "
            f"with no real module import, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_acceptance_cli_module_reference_only_passes(self):
        # (CHEAP closer, task review) A test file that imports the
        # `operator_acceptance` acceptance-CLI module (import/module-reference
        # only, no in-process call -- it is invoked as a subprocess, not
        # called in-process, per _ast_references_entrypoint's own DECISION
        # note) must PASS the producer-entrypoint probe.
        cap_id = "acceptance_cli_ref_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Acceptance Cli Ref Cap", op_kind=VALID_OP_KIND))
        self._stage_real_external_write()
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: import/module-reference of the acceptance CLI, no call (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

import external_write.operator_acceptance  # noqa: F401 -- reference only, invoked as a CLI subprocess


class TestAcceptanceCliRefCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "Acceptance Cli Ref Cap ready")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(
            any(f.startswith("Producer entrypoint:") for f in result.failures),
            f"expected no Producer entrypoint failure for an acceptance-CLI module reference, "
            f"got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_no_discoverable_test_file_flags_producer_entrypoint(self):
        cap_id = "no_test_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="No Test Cap", op_kind=VALID_OP_KIND))
        # Deliberately no test file written anywhere.

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Producer entrypoint:") and "no test file" in f
                for f in result.failures),
            f"expected a 'no test file' Producer entrypoint failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)


class TestKnownBadFailsProbe(CapabilityInvariantsTestBase):
    def test_inert_always_green_suite_is_caught(self):
        # Required test (c): an inert (always-passes) test suite is caught by
        # the known-bad-fails probe -- it stays green even against a
        # deliberately broken copy, so the probe FAILS this capability.
        cap_id = "inert_suite_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Inert Suite Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: inert (always-green) test suite (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}  # noqa: F401 -- imported but never called: inert by design


class TestInertSuiteCap(unittest.TestCase):
    def test_always_true(self):
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Known-bad-fails:") for f in result.failures),
            f"expected a Known-bad-fails failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_genuine_suite_that_fails_against_broken_impl_passes(self):
        # Required test (d): a genuine test suite that DOES fail against a
        # broken impl passes the known-bad-fails probe.
        cap_id = "genuine_suite_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Genuine Suite Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: genuine test suite that really exercises the capability (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}


class TestGenuineSuiteCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "Genuine Suite Cap ready")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(
            any(f.startswith("Known-bad-fails:") for f in result.failures),
            f"expected no Known-bad-fails failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_pytest_style_zero_unittest_test_suite_gets_actionable_stop_message(self):
        # (DR-1 required test, gemini#1 false-positive/dead-end fix) A suite written
        # pytest-style -- a bare `def test_...` FUNCTION, never inside a
        # unittest.TestCase class -- collects ZERO real tests under `unittest
        # discover`. The OLD implementation scored a clean (returncode 0) baseline
        # run as "green" regardless of how many tests actually ran, so this honest,
        # functionally-correct-but-wrong-style suite fell through to the mutated run,
        # ALSO collected zero tests there (nothing calls the broken implementation),
        # and was reported as the generic "still reported all tests passing... these
        # tests are not actually verifying its behavior" inert-suite dead-end -- wrong
        # and unhelpful for a competent operator who simply used the wrong test
        # style. The fix must recognize testsRun == 0 at baseline and STOP with a
        # plain-language, actionable message (write real unittest.TestCase tests),
        # BEFORE ever reaching the mutated run -- not scored as "effective" (there is
        # nothing to be effective) and not the generic inert-suite dead-end message.
        cap_id = "pytest_style_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Pytest Style Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: pytest-style suite -- bare functions, no unittest.TestCase (test fixture)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}


def test_describe_reports_ready():
    assert {module_name}.describe() == "Pytest Style Cap ready"
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        known_bad_fails_failures = [f for f in result.failures if f.startswith("Known-bad-fails:")]
        self.assertTrue(
            known_bad_fails_failures,
            f"expected a Known-bad-fails failure, got {result.failures!r}",
        )
        self.assertTrue(
            any("unittest.TestCase" in f and "def test_" in f for f in known_bad_fails_failures),
            f"expected the actionable 'write as unittest.TestCase' STOP message, got "
            f"{known_bad_fails_failures!r}",
        )
        self.assertFalse(
            any("still reported all tests passing" in f for f in known_bad_fails_failures),
            f"a pytest-style suite must not be dead-ended with the generic inert-suite "
            f"message: {known_bad_fails_failures!r}",
        )
        self._assert_no_traceback(result)

    def test_module_level_assert_suite_mutation_import_crash_not_scored_effective(self):
        # (DR-1 required test, gpt#2 false-negative fix) A "suite" made entirely of
        # MODULE-LEVEL assertions (never inside a unittest.TestCase method) collects
        # ZERO real tests, exactly like the pytest-style case above -- but its
        # failure mode under the OLD implementation was worse: at baseline the
        # module-level assert calls the REAL (working) capability and passes
        # silently at import time (clean exit, zero tests collected -- scored
        # "green" by the old bare-returncode check). Once this capability's
        # implementation is deliberately mutated so every function raises, that SAME
        # module-level line now raises DURING IMPORT, crashing the whole test file
        # before a single real test could ever run -- a non-zero exit the OLD
        # implementation could not distinguish from "a real test caught the break",
        # so it was scored ok=True (false assurance) even though ZERO real tests
        # ever ran. The fix must recognize testsRun == 0 at baseline (an import
        # crash is not a real test) and STOP there -- so this capability is never
        # scored "effective", and never reaches the mutated run at all.
        cap_id = "module_level_assert_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Module Level Assert Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: module-level assertions, no unittest.TestCase (test fixture)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

# Module-level assertion -- executed at IMPORT time, not inside any
# unittest.TestCase method. At baseline it calls the real (working)
# implementation and passes silently. Once this capability's own
# implementation is mutated so every function raises, this SAME line
# crashes on import instead -- zero real tests ever run either way.
assert {module_name}.describe() == "Module Level Assert Cap ready"
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertFalse(
            result.ok,
            "an import-time crash (zero real tests ever ran) must NOT be scored as "
            f"'caught the mutation' -- got ok=True, failures={result.failures!r}",
        )
        known_bad_fails_failures = [f for f in result.failures if f.startswith("Known-bad-fails:")]
        self.assertTrue(
            known_bad_fails_failures,
            f"expected a Known-bad-fails failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_unrelated_crash_that_never_runs_is_not_treated_as_caught(self):
        # Review finding (reproduced): a suite that CANNOT EVEN IMPORT/RUN --
        # for an UNRELATED reason, nothing to do with the deliberate mutation
        # -- still exits non-zero. The OLD implementation reduced every run to
        # a bare ``returncode != 0`` check, so this counted as "caught the
        # mutation" and the capability was reported ok=True. A suite that
        # never actually ran proves NOTHING about whether it would catch a
        # real break -- this must FAIL closed, the same as an inert suite.
        # Reproduces the reviewer's exact repro: a test that references the
        # real producer entrypoint (so it PASSES probe 1, producer-entrypoint,
        # by static AST alone) but whose ``external_write`` import can never
        # actually resolve at subprocess-run time because it is deliberately
        # NOT staged into this fixture (unlike the sibling
        # ``real_entrypoint_cap`` fixture above) -- so the suite dies with an
        # unrelated ``ModuleNotFoundError`` before running a single test, for
        # a reason that has nothing to do with the capability's own
        # implementation being broken.
        cap_id = "never_runs_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Never Runs Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: test suite that never runs -- unrelated import error (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

from external_write.capability_api import run_enveloped_operation  # noqa: F401 -- never staged

if False:  # AST-only guarded call (DR-2 fix) -- never executed; keeps this
           # fixture passing probe 1 (producer-entrypoint) on a genuine Call
           # node, independent of the ModuleNotFoundError this fixture is
           # deliberately built to hit at subprocess-run time.
    run_enveloped_operation()


class TestNeverRunsCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "Never Runs Cap ready")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(
            any(f.startswith("Producer entrypoint:") for f in result.failures),
            f"this fixture should pass producer-entrypoint (AST-only) so the failure under "
            f"test is isolated to known-bad-fails: got {result.failures!r}",
        )
        self.assertFalse(
            result.ok,
            "an unrelated crash (the suite never actually ran) must NOT be treated as "
            f"'caught the mutation' -- got ok=True, failures={result.failures!r}",
        )
        self.assertTrue(
            any(f.startswith("Known-bad-fails:") for f in result.failures),
            f"expected a Known-bad-fails failure for a suite that never runs, got "
            f"{result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_mixed_suite_mutated_import_crash_branch_scored_not_effective(self):
        # (Important fix, task review) The branch in `_check_known_bad_fails`
        # that folds a MUTATED-run import/collection crash into "not
        # effective" (the `not real_failure` path, reached only once baseline
        # is green) had ZERO test coverage: the sibling
        # `module_level_assert_cap` fixture above is intercepted EARLIER, at
        # the BASELINE `tests_run == 0` gate (it defines no unittest.TestCase
        # at all, so baseline itself never collects a real test) -- it never
        # reaches the mutated stage this test targets.
        #
        # This fixture is a MIXED suite: a real, passing `unittest.TestCase`
        # test (so BASELINE runs >0 real tests and is fully green) PLUS
        # module-level code that CALLS a capability function at import time.
        # At baseline (the real, unmutated implementation) that call succeeds
        # silently and the TestCase test runs and passes -- green,
        # tests_run > 0. Once this capability's own module is mutated (every
        # function body replaced with a raise), that SAME module-level call
        # now raises DURING IMPORT, crashing collection of this file before
        # the TestCase test ever runs -- an import/collection crash, not a
        # real test failure -- so the probe must NOT score this as
        # "effective" (caught the break); it must fail closed, plain
        # language, same as an inert suite.
        cap_id = "mixed_suite_import_crash_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Mixed Suite Import Crash Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: mixed suite -- real TestCase test + module-level call (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

# Module-level call at IMPORT time -- succeeds silently against the real
# (baseline) implementation (so baseline collection completes and the
# TestCase test below runs and passes). Once this capability's own
# implementation is mutated so every function raises, this SAME line raises
# DURING IMPORT, crashing this file's collection before the TestCase test
# below ever runs.
{module_name}.describe()


class TestMixedSuiteImportCrashCap(unittest.TestCase):
    def test_always_true(self):
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        known_bad_fails_failures = [f for f in result.failures if f.startswith("Known-bad-fails:")]
        self.assertTrue(
            known_bad_fails_failures,
            f"expected a Known-bad-fails failure, got {result.failures!r}",
        )
        # Must have reached the MUTATED-run branch (proving baseline was green,
        # tests_run > 0) -- NOT the baseline zero-real-tests gate, which would
        # produce the distinct "did not run as unittest tests" message instead.
        self.assertTrue(
            any("still reported all tests passing" in f for f in known_bad_fails_failures),
            f"expected this fixture to reach the mutated-run 'not effective' branch (proving "
            f"baseline was green with real tests > 0), got {known_bad_fails_failures!r}",
        )
        self.assertFalse(
            any("did not run as unittest tests" in f for f in known_bad_fails_failures),
            f"this fixture's baseline must be green (real TestCase test, tests_run > 0) -- it "
            f"must not be intercepted at the baseline zero-real-tests gate: "
            f"{known_bad_fails_failures!r}",
        )
        self._assert_no_traceback(result)

    def test_missing_capability_source_fails_closed(self):
        cap_id = "missing_source_quality_cap"
        # No capability source file written at all.

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(any(f.startswith("Test quality:") for f in result.failures))
        self._assert_no_traceback(result)


# =============================================================================
# Task D1-3: CLI entrypoint -- runs BOTH D1-1 + D1-2 batteries together
# =============================================================================
#
# This is the exact command next-phase.md's Step 4 runs (see that skill's own
# "Technical verification" step). Exercised here via a REAL subprocess
# invocation of the module's own ``__main__`` -- never a simulation of it --
# mirroring ``CheckCompletionCLITests`` in ``test_lifecycle_state.py``, the
# same "bypass the LLM for critical I/O" discipline: the command's own exit
# code is the deterministic gate, not an agent's interpretation of its
# output.


class CapabilityInvariantsCLITests(CapabilityInvariantsTestBase):
    CLI_SCRIPT = (
        Path(__file__).resolve().parents[2] / "agents" / "lib" / "external_write"
        / "capability_invariants.py"
    )

    def _run_cli(self, root, canonical_id):
        return subprocess.run(
            [sys.executable, str(self.CLI_SCRIPT), str(root), canonical_id],
            capture_output=True, text=True, timeout=90,
        )

    def test_cli_exits_zero_when_both_batteries_pass(self):
        cap_id = "cli_all_pass_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Cli All Pass Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])
        self._stage_real_external_write()
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: real producer-entrypoint reference test (CLI fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

from external_write.capability_api import run_enveloped_operation  # noqa: F401

if False:  # AST-only guarded call (DR-2 fix) -- never executed; proves this test
           # file's entrypoint reference is a genuine ast.Call, not merely an
           # import, without ever performing a live write when discovered/collected.
    run_enveloped_operation()


class TestCliAllPassCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "Cli All Pass Cap ready")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._run_cli(self.project_root, cap_id)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_exits_one_when_structural_invariants_fail(self):
        cap_id = "cli_routing_violation_cap"
        self._write_capability(
            cap_id,
            _ROUTING_VIOLATION_SOURCE.format(name="Cli Routing Violation Cap", op_kind=VALID_OP_KIND),
        )
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])
        # No test file at all -- irrelevant here; the routing failure alone must exit 1.

        result = self._run_cli(self.project_root, cap_id)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Routing:", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_exits_one_when_test_quality_fails(self):
        cap_id = "cli_no_test_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Cli No Test Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])
        # Structurally valid capability, but no discoverable test file anywhere.

        result = self._run_cli(self.project_root, cap_id)

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Producer entrypoint:", result.stdout)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_missing_arguments_exits_nonzero_without_traceback(self):
        result = subprocess.run(
            [sys.executable, str(self.CLI_SCRIPT)],
            capture_output=True, text=True, timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


class TestLifecycleHermeticityProbeASTUnits(unittest.TestCase):
    """Direct, fast unit tests of the two AST-only detection functions Task A3's lifecycle-
    hermeticity probe is built from (``_ast_calls_write_gate_without_paused_root`` and
    ``_ast_touches_ambient_paused_mechanisms_path``) -- exercised in isolation, without going
    through a full project fixture + ``check_test_quality`` run, so each detection shape and
    documented limit from that probe's module-level "Detection shape + its limits" section is
    pinned precisely."""

    def _calls_without_paused_root(self, source: str):
        import ast
        return capability_invariants._ast_calls_write_gate_without_paused_root(ast.parse(source))

    def _touches_ambient_path(self, source: str) -> bool:
        import ast
        return capability_invariants._ast_touches_ambient_paused_mechanisms_path(ast.parse(source))

    def test_bare_name_import_call_without_paused_root_is_flagged(self):
        hits = self._calls_without_paused_root(
            "from external_write.write_gate import evaluate_write_gate\n"
            "d = evaluate_write_gate(op, target='live')\n"
        )
        self.assertEqual(len(hits), 1)

    def test_bare_name_import_call_with_paused_root_is_not_flagged(self):
        hits = self._calls_without_paused_root(
            "from external_write.write_gate import evaluate_write_gate\n"
            "d = evaluate_write_gate(op, target='live', paused_root=some_temp_dir)\n"
        )
        self.assertEqual(hits, [])

    def test_module_attribute_access_call_without_paused_root_is_flagged(self):
        hits = self._calls_without_paused_root(
            "from external_write import write_gate\n"
            "d = write_gate.evaluate_write_gate(op, target='live')\n"
        )
        self.assertEqual(len(hits), 1)

    def test_plain_import_module_attribute_call_without_paused_root_is_flagged(self):
        hits = self._calls_without_paused_root(
            "import external_write.write_gate\n"
            "d = external_write.write_gate.evaluate_write_gate(op, target='live')\n"
        )
        self.assertEqual(len(hits), 1)

    def test_kwargs_unpack_is_not_flagged_documented_limit(self):
        # (Documented LIMIT) A call that hides paused_root inside a **mapping unpack is
        # UNDECIDABLE from source text alone -- must not be flagged.
        hits = self._calls_without_paused_root(
            "from external_write.write_gate import evaluate_write_gate\n"
            "extra = {'paused_root': some_temp_dir}\n"
            "d = evaluate_write_gate(op, target='live', **extra)\n"
        )
        self.assertEqual(hits, [])

    def test_explicit_paused_root_none_is_not_flagged_documented_limit(self):
        # (Documented LIMIT) paused_root=None is behaviorally identical to omitting the keyword,
        # but this checks the keyword's PRESENCE, not its value -- not flagged.
        hits = self._calls_without_paused_root(
            "from external_write.write_gate import evaluate_write_gate\n"
            "d = evaluate_write_gate(op, target='live', paused_root=None)\n"
        )
        self.assertEqual(hits, [])

    def test_unrelated_call_of_the_same_name_from_no_import_is_not_flagged(self):
        # A LOCALLY-defined function that happens to share the name, never imported from
        # write_gate at all, must not be treated as the real entrypoint.
        hits = self._calls_without_paused_root(
            "def evaluate_write_gate(op, target=None):\n"
            "    return 'fake'\n"
            "d = evaluate_write_gate(op, target='live')\n"
        )
        self.assertEqual(hits, [])

    def test_ambient_literal_in_open_call_is_flagged(self):
        self.assertTrue(self._touches_ambient_path(
            "open('.wizard/paused-mechanisms/x.json', 'w')\n"
        ))

    def test_ambient_literal_in_path_construction_is_flagged(self):
        self.assertTrue(self._touches_ambient_path(
            "from pathlib import Path\n"
            "p = Path('.wizard/paused-mechanisms')\n"
            "p.mkdir()\n"
        ))

    def test_ambient_literal_nested_in_os_path_join_is_flagged(self):
        self.assertTrue(self._touches_ambient_path(
            "import os\n"
            "p = os.path.join(root, '.wizard/paused-mechanisms', 'x.json')\n"
        ))

    def test_literal_reference_outside_a_filesystem_call_is_not_flagged(self):
        # A test that merely pins the CONSTANT's value (no filesystem call in sight) must not
        # be flagged -- anchored to "argument inside a recognized fs call", not a bare substring.
        self.assertFalse(self._touches_ambient_path(
            "from external_write import write_gate\n"
            "assert write_gate.PAUSED_MECHANISMS_DIR == '.wizard/paused-mechanisms'\n"
        ))

    def test_unrelated_path_literal_in_a_filesystem_call_is_not_flagged(self):
        self.assertFalse(self._touches_ambient_path(
            "open('some/unrelated/path.json', 'w')\n"
        ))


class TestLifecycleHermeticityProbeIntegration(CapabilityInvariantsTestBase):
    """Integration tests of the lifecycle-hermeticity probe through the real
    ``check_test_quality`` entrypoint (Task A3, F-71) -- the exact regression class this test
    suite must guard against: a capability test whose verdict depends on this project's own
    ambient, changes-over-time pause state."""

    def test_ambient_write_gate_call_without_paused_root_is_flagged(self):
        # This IS the F-71 shape: a test class asserting paused-refusal by calling
        # evaluate_write_gate with no paused_root at all, relying on the gate's own ambient
        # default.
        cap_id = "ambient_pause_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Ambient Pause Cap", op_kind=VALID_OP_KIND))
        self._stage_real_external_write()
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: F-71 shape -- ambient-state-dependent paused-refusal test (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}  # noqa: F401

from external_write.write_gate import evaluate_write_gate
from external_write.operations import Operation


class TestWriteGatePausedPendingMigration(unittest.TestCase):
    def test_gate_live_refused_while_paused(self):
        op = Operation(surface="test_surface", op_kind="{VALID_OP_KIND}", object_id="obj:1", batch_id="b1")
        # No paused_root= passed at all -- falls through to the real ambient default.
        d = evaluate_write_gate(op, target="live")
        # Outcome deliberately not asserted on further -- the defect is the missing kwarg,
        # not any particular result.


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Lifecycle hermeticity:") for f in result.failures),
            f"expected a Lifecycle hermeticity failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_direct_ambient_path_touch_without_write_gate_call_is_flagged(self):
        # The OTHER shape this probe catches: a test that never calls evaluate_write_gate at
        # all, but reads/writes the ambient pause-marker path directly.
        cap_id = "ambient_touch_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Ambient Touch Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: direct ambient pause-marker path touch, no write_gate call (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}  # noqa: F401


class TestDirectAmbientTouch(unittest.TestCase):
    def test_reads_ambient_marker_directory(self):
        p = Path(".wizard/paused-mechanisms")
        self.assertTrue(True)  # the reference above is the defect, not this assertion


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Lifecycle hermeticity:") for f in result.failures),
            f"expected a Lifecycle hermeticity failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_hermetic_fixture_rewrite_passes_the_full_battery(self):
        # The SAME test intent as the F-71 shape above (prove paused-refusal), rewritten to use
        # the hermetic fixture instead of the ambient default -- must pass ALL THREE probes,
        # not merely avoid the lifecycle-hermeticity failure.
        cap_id = "hermetic_pause_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Hermetic Pause Cap", op_kind=VALID_OP_KIND))
        self._stage_real_external_write()
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: hermetic paused-refusal test, real entrypoint reference (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

from external_write.capability_api import run_enveloped_operation  # noqa: F401
from external_write.write_gate import evaluate_write_gate
from external_write.operations import Operation
from external_write.lifecycle_test_fixtures import hermetic_paused_mechanisms

if False:  # AST-only guarded call (mirrors the real-entrypoint fixture pattern elsewhere in
           # this suite) -- proves this file's producer-entrypoint reference is a genuine
           # ast.Call, never executed here.
    run_enveloped_operation()


class TestRealEntrypointHermeticPauseCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "Hermetic Pause Cap ready")


class TestPausedRefusalHermetic(unittest.TestCase):
    def test_gate_live_refused_while_paused(self):
        op = Operation(surface="test_surface", op_kind="{VALID_OP_KIND}", object_id="obj:1", batch_id="b1")
        with hermetic_paused_mechanisms(["{VALID_OP_KIND}"]) as paused_root:
            d = evaluate_write_gate(op, target="live", paused_root=paused_root)
        self.assertFalse(d.permitted)


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")
        self.assertEqual(result.failures, [])
        self._assert_no_traceback(result)

    def test_probe_verdict_identical_regardless_of_real_ambient_marker_state(self):
        # (Idempotence across accept -> reconcile, the exact F-71 regression property) The
        # probe's verdict must be IDENTICAL whether or not a real pause marker happens to exist
        # under this project's own ambient .wizard/paused-mechanisms/ at the moment the check
        # runs -- unlike the OLD ambient-reading test, which flipped between the two. Exercised
        # for BOTH the flagged (ambient-reliant) test and the clean (hermetic) test.
        ambient_cap_id = "ambient_pause_idempotence_cap"
        self._write_capability(
            ambient_cap_id,
            _CLEAN_SOURCE.format(name="Ambient Pause Idempotence Cap", op_kind=VALID_OP_KIND))
        self._stage_real_external_write()
        module_name = f"{ambient_cap_id}_capability"
        ambient_test_source = f'''"""Fixture: ambient-reliant paused test (idempotence probe fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}  # noqa: F401

from external_write.write_gate import evaluate_write_gate
from external_write.operations import Operation


class TestAmbientIdempotence(unittest.TestCase):
    def test_gate_live_refused_while_paused(self):
        op = Operation(surface="test_surface", op_kind="{VALID_OP_KIND}", object_id="obj:1", batch_id="b1")
        d = evaluate_write_gate(op, target="live")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{ambient_cap_id}_capability.py",
            ambient_test_source)

        def _lifecycle_failure_present(cap_id):
            result = self._check_quality(cap_id)
            return any(f.startswith("Lifecycle hermeticity:") for f in result.failures)

        # "Before reconcile": a real pause marker sits under the project's own ambient path.
        marker_dir = self.project_root / capability_invariants.PAUSED_MECHANISMS_DIR_REL
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / f"{ambient_cap_id}.json").write_text(
            json.dumps({"paused_op_kinds": [VALID_OP_KIND]}), encoding="utf-8")
        before = _lifecycle_failure_present(ambient_cap_id)

        # "After reconcile": the marker is cleared (Task A1/A2's own effect).
        (marker_dir / f"{ambient_cap_id}.json").unlink()
        after = _lifecycle_failure_present(ambient_cap_id)

        self.assertTrue(before, "expected the ambient-reliant test to be flagged before reconcile")
        self.assertTrue(after, "expected the ambient-reliant test to STILL be flagged after "
                                "reconcile -- the probe is static and must not depend on ambient "
                                "marker state the way the old runtime test did")
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
