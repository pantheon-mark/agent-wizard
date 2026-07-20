"""Cluster isolation validation: a composition regression net proving that the accept-time
lifecycle reconcile, the read-time self-heal, the write-time identity-collision guard + twin
health classification, and the lifecycle-hermeticity test-quality probe all hold together over
one project fixture -- not re-testing any one of their edges (each already has its own
per-task test suite), only that composing them end to end reaches the coherent state each was
designed to guarantee.

Scenarios
---------
1. A paused capability accepted through the NORMAL accept path (``record_operator_acceptance``,
   never ``complete_migration``) ends accepted, with no residual pause marker, and the write
   gate permits its op_kind -- AND a capability whose accept-path reconcile is skipped (a
   simulated crash between the accept write and its own reconcile step) self-heals to the same
   coherent state the next time anything reads its health.
2. That same self-heal is fail-safe: on a marker directory it cannot write to, it reports the
   orphaned marker honestly rather than crashing or silently pretending it healed.
3. A descriptor id that normalizes to an already-built capability's id is refused at write time;
   an existing case/separator twin with no recorded state of its own classifies as safe-to-retire
   (``pending``), never a red phantom; the same twin carrying real state classifies as
   ``identity_conflict``, also never red.
4. The lifecycle-hermeticity test-quality probe fails a capability test that reads the write
   gate's ambient pause state directly, and passes the identical check rewritten hermetically
   through the emitted ``hermetic_paused_mechanisms`` fixture.

ANTI-OVERFIT: every fixture lives at the real emitted relative path
(``agents/capabilities/<id>_capability.py``, ``security/capability_descriptors.json``, ...)
inside a fresh ``tempfile.TemporaryDirectory()`` -- never a copytree of a whole prior project.
Ids are generic and op-kind-agnostic (``cap_alpha`` / ``cap-alpha`` / ...), never product- or
domain-specific text. The one exception is staging the small, real ``external_write`` runtime
package itself into a fixture project's own ``agents/lib/`` (Scenario 4) -- required so the
dynamic, subprocess-isolated probes this suite composes have something real to import at run
time, the same established convention this package's own per-task test suites already use.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[2] / "agents" / "lib"
if str(_AGENTS_LIB) not in sys.path:
    sys.path.insert(0, str(_AGENTS_LIB))

from external_write import capability_health  # noqa: E402
from external_write import capability_invariants  # noqa: E402
from external_write import lifecycle_state  # noqa: E402
from external_write.capability_identity import (  # noqa: E402
    assert_no_normalized_collision,
    CanonicalIdentityError,
)
from external_write.capability_registration import register_declared_capability  # noqa: E402
from external_write.copy_run_proof import COPY_RUN_PROOF_SCHEMA  # noqa: E402
from external_write.operations import Operation  # noqa: E402
from external_write.operator_acceptance import record_operator_acceptance  # noqa: E402
from external_write.proof_hash import compute_contract_hash, compute_implementation_hash  # noqa: E402,E501
from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA  # noqa: E402
from external_write.write_gate import (  # noqa: E402
    evaluate_write_gate,
    InvocationLedger,
    LIVE_TARGET,
    load_descriptor_set,
)


CAPABILITIES_DIR_REL = "agents/capabilities"
CAPABILITY_FILE_SUFFIX = "_capability.py"
DESCRIPTOR_SET_REL = "security/capability_descriptors.json"
MIGRATION_QUEUE_REL = "agents/handoffs/pending_migrations.json"
PAUSED_MECHANISMS_DIR_REL = ".wizard/paused-mechanisms"
ACCEPTANCE_LOG_REL = "security/capability_acceptance_log.jsonl"

PHASE_ID = "phase-1"
# Generic, adapter-free, gated op_kind already registered in contracts.OPERATION_CONTRACTS --
# no product/vendor text. risk_class "irreversible_external" / requires_accepted_phase=True.
OP_KIND = "delete_record"

# A real, on-disk, scanner-clean capability module (shared across the whole scan test suite) --
# reused here as the copy_run_proof's wire-verified capability_module_paths entry, exactly like
# the operator-acceptance end-to-end test does.
_SCANNER_CLEAN_MODULE_FIXTURE = (
    Path(__file__).resolve().parents[2] / "test_fixtures" / "external_write_scan"
    / "legal_through_adapter.py"
)


def _clean_capability_source(cap_id: str, op_kind: str = OP_KIND) -> str:
    return f'''"""{cap_id} -- gate-clean capability module (isolation-validation fixture)."""

from typing import Any

OP_KIND = "{op_kind}"


def describe() -> str:
    return "{cap_id} ready"


def propose_operations(facade: Any, batch_id: str):
    return []
'''


def _verification():
    return {
        "schema": POSTWRITE_VERIFICATION_SCHEMA,
        "verification_mode": "prestate_snapshot_diff",
        "claim_strength": "verified",
        "verifier_id": "prestate_snapshot_diff_v1",
        "source_lineage": {
            "pre_write_sources": ["prewrite_snapshot"],
            "post_write_sources": ["live_surface_read"],
            "forbidden_sources": [
                "writer_generated_id_map", "live_id_column_as_truth", "apply_report",
            ],
        },
        "invariant_checked": "record absent after delete",
        "evidence_ref": "agents/handoffs/.ev.txt",
    }


def _copy_run_proof(cap_id: str, op_kind: str = OP_KIND) -> dict:
    return {
        "schema": COPY_RUN_PROOF_SCHEMA,
        "operation_id": "op-001",
        "op_kind": op_kind,
        "capability_id": cap_id,
        "data_class": "generic_test_rows",
        "copy_source_ref": "copies/test_copy.csv",
        "prestate_snapshot_ref": "copies/test_copy.prestate.csv",
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
        "capability_module_paths": [str(_SCANNER_CLEAN_MODULE_FIXTURE)],
    }


def _descriptor_entry(cap_id: str, **overrides) -> dict:
    entry = {
        "id": cap_id, "name": cap_id, "action_class": "delete",
        "risk_class": "irreversible_external", "recovery_profile_ref": None,
        "declared_test_target": "copy", "blast_radius_cap": 5, "accepted": False,
        "phase_id": PHASE_ID,
    }
    entry.update(overrides)
    return entry


class _IsolationFixtureBase(unittest.TestCase):
    """Shared fixture plumbing: one fresh temp project tree per test, populated only with the
    real emitted relative paths this test actually needs."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.descriptor_path = self.root / DESCRIPTOR_SET_REL
        self.migration_queue_path = self.root / MIGRATION_QUEUE_REL
        self.audit_log_path = self.root / ACCEPTANCE_LOG_REL
        self.marker_dir = self.root / PAUSED_MECHANISMS_DIR_REL

    # -- fixture writers -----------------------------------------------------------------

    def _write_capability(self, cap_id: str, op_kind: str = OP_KIND) -> Path:
        d = self.root / CAPABILITIES_DIR_REL
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{cap_id}{CAPABILITY_FILE_SUFFIX}"
        path.write_text(_clean_capability_source(cap_id, op_kind), encoding="utf-8")
        return path

    def _write_descriptor_set(self, entries) -> None:
        self.descriptor_path.parent.mkdir(parents=True, exist_ok=True)
        self.descriptor_path.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _read_descriptor_set(self):
        return json.loads(self.descriptor_path.read_text(encoding="utf-8"))

    def _accepted_flag(self, cap_id: str):
        for e in self._read_descriptor_set():
            if e.get("id") == cap_id:
                return e.get("accepted")
        return None

    def _write_migration_queue(self, entries) -> None:
        self.migration_queue_path.parent.mkdir(parents=True, exist_ok=True)
        self.migration_queue_path.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _write_proof(self, cap_id: str, op_kind: str = OP_KIND) -> Path:
        path = self.root / f"{cap_id}.proof.json"
        path.write_text(json.dumps(_copy_run_proof(cap_id, op_kind)), encoding="utf-8")
        return path

    def _accept(self, cap_id: str, op_kind: str = OP_KIND, phase_id: str = PHASE_ID):
        """Drive the REAL, normal accept path -- ``record_operator_acceptance`` -- exactly as an
        operator's project does at the business-acceptance step. Never ``complete_migration``."""
        proof_path = self._write_proof(cap_id, op_kind)
        return record_operator_acceptance(
            cap_id, phase_id, str(proof_path),
            "Yes -- I accept this capability for live use.",
            receipt_path=str(self.root / "security" / "acceptance_receipts"
                              / f"{cap_id}.receipt.json"),
            descriptor_set_path=str(self.descriptor_path),
            audit_log_path=str(self.audit_log_path),
            pending_migrations_path=str(self.migration_queue_path),
            project_root=str(self.root),
        )

    def _marker_files(self, cap_id: str):
        return (self.marker_dir / f"{cap_id}.pause", self.marker_dir / f"{cap_id}.json")

    def _marker_present(self, cap_id: str) -> bool:
        pause, state = self._marker_files(cap_id)
        return pause.exists() or state.exists()

    def _plant_residual_marker(self, cap_id: str) -> None:
        """Hand-plant a bare ``.pause`` touch-file for ``cap_id`` -- the same minimal residue
        evidence ``capability_health.check_capabilities``'s own pause check accepts (any existing
        ``.pause`` path counts, regardless of shape). Simulates the orphaned-marker shape a crash
        between an accept write and its own reconcile call leaves behind."""
        self.marker_dir.mkdir(parents=True, exist_ok=True)
        pause, _state = self._marker_files(cap_id)
        pause.write_text("", encoding="utf-8")

    def _permits_live_write(self, cap_id: str, op_kind: str = OP_KIND) -> bool:
        descriptor_set = load_descriptor_set(str(self.descriptor_path))
        op = Operation(surface=cap_id, object_id="row:1", field="__record__",
                       new_value="<x>", op_kind=op_kind, batch_id="b1")
        decision = evaluate_write_gate(
            op, target=LIVE_TARGET, descriptor_set=descriptor_set,
            cap_ledger=InvocationLedger(), paused_root=str(self.marker_dir))
        return decision.permitted


# =============================================================================
# Scenario 1 -- accept-time reconcile and read-time self-heal converge
# =============================================================================

class AcceptAndReadReconcileConvergeTest(_IsolationFixtureBase):
    """The normal accept path clears a real, pre-existing pause marker on its own; a capability
    whose accept-path reconcile was skipped (simulated crash) self-heals on the next health
    read. Both reach the same coherent end state: accepted, no residual marker."""

    def test_normal_accept_clears_a_preexisting_pause_marker_and_gate_permits(self):
        cap_id = "cap_alpha"
        self._write_capability(cap_id)
        self._write_descriptor_set([_descriptor_entry(cap_id)])

        # Seed the paused-pending-migration precondition through the real reconciler itself
        # (never a hand-crafted marker file): a migration queued against an unaccepted
        # capability is exactly how a real pause marker forms.
        self._write_migration_queue([{"mechanism_id": cap_id}])
        seed = lifecycle_state.reconcile_state(str(self.root), cap_id)
        self.assertTrue(seed.marker_present)
        self.assertTrue(self._marker_present(cap_id))
        self.assertFalse(self._permits_live_write(cap_id), "must be refused while paused")

        result = self._accept(cap_id)

        self.assertTrue(result.accepted, result.reason)
        self.assertIsNone(result.reconcile_note, "the accept-path reconcile must finish cleanly")
        self.assertEqual(self._accepted_flag(cap_id), True)
        self.assertFalse(self._marker_present(cap_id), "no residual paused_live_write marker")
        self.assertTrue(self._permits_live_write(cap_id), "write gate must now permit this op_kind")

    def test_crash_between_accept_and_reconcile_self_heals_on_next_health_read(self):
        cap_id = "cap_beta"
        self._write_capability(cap_id)
        self._write_descriptor_set([_descriptor_entry(cap_id)])

        result = self._accept(cap_id)
        self.assertTrue(result.accepted, result.reason)
        self.assertIsNone(result.reconcile_note)
        self.assertFalse(self._marker_present(cap_id))

        # Simulate a crash BETWEEN the accept write and its own reconcile step: force a
        # residual pause marker back onto an already-accepted capability, as if the
        # accept-path reconcile that would normally have cleared it never ran.
        self._plant_residual_marker(cap_id)
        self.assertTrue(self._marker_present(cap_id))

        before = capability_health.check_capabilities(str(self.root))
        before_record = next(r for r in before if r["capability_id"] == cap_id)
        self.assertTrue(before_record["paused"])
        self.assertEqual(before_record["health"], "red")

        after = capability_health.check_capabilities_with_self_heal(str(self.root))
        after_record = next(r for r in after if r["capability_id"] == cap_id)

        self.assertFalse(after_record["paused"])
        self.assertEqual(after_record["health"], "green", after_record)
        self.assertFalse(self._marker_present(cap_id), "self-heal must clear the orphaned marker")


# =============================================================================
# Scenario 2 -- self-heal is fail-safe: reports, never crashes, never fabricates a heal
# =============================================================================

class SelfHealFailSafeTest(_IsolationFixtureBase):
    def test_orphaned_marker_on_a_read_only_directory_is_reported_not_crashed(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("permission-denied behavior cannot be exercised while running as root")

        cap_id = "cap_gamma"
        self._write_capability(cap_id)
        self._write_descriptor_set([_descriptor_entry(cap_id)])
        result = self._accept(cap_id)
        self.assertTrue(result.accepted, result.reason)

        self._plant_residual_marker(cap_id)
        self.assertTrue(self._marker_present(cap_id))

        original_mode = self.marker_dir.stat().st_mode
        # Read + execute only, no write: os.unlink() of an entry inside this directory (what the
        # self-heal's own marker-clear does) requires write permission on the DIRECTORY, not the
        # file -- this reproduces a read-only filesystem's refusal without needing a real mount.
        os.chmod(self.marker_dir, 0o555)
        self.addCleanup(os.chmod, self.marker_dir, original_mode)

        # Must not raise, even though the self-heal attempt cannot write here.
        records = capability_health.check_capabilities_with_self_heal(str(self.root))

        record = next(r for r in records if r["capability_id"] == cap_id)
        self.assertTrue(record["paused"], "the orphan must be REPORTED, not silently cleared")
        self.assertEqual(record["health"], "red")
        self.assertTrue(self._marker_present(cap_id))


# =============================================================================
# Scenario 3 -- write-time identity-collision guard + twin health classification
# =============================================================================

class IdentityTwinTest(_IsolationFixtureBase):
    """Generic, op-kind-agnostic ids throughout: ``cap_alpha`` (underscore) is the real, built
    canonical capability; ``cap-alpha`` (hyphen) is its case/separator twin under test."""

    def test_write_time_collision_guard_raises_on_a_normalized_twin(self):
        with self.assertRaises(CanonicalIdentityError):
            assert_no_normalized_collision("cap-alpha", ["cap_alpha"])

    def test_registering_a_normalized_twin_id_is_refused_not_landed(self):
        self._write_descriptor_set([{"id": "cap_alpha", "name": "cap_alpha", "accepted": False}])

        result = register_declared_capability(
            {"id": "cap-alpha", "name": "cap-alpha", "phase_id": PHASE_ID, "accepted": False},
            descriptor_set_path=str(self.descriptor_path), project_root=str(self.root),
        )

        self.assertFalse(result.registered)
        self.assertIn("cap_alpha", result.reason or "")
        self.assertEqual(len(self._read_descriptor_set()), 1, "nothing was landed")

    def test_never_built_never_accepted_twin_is_pending_not_red(self):
        self._write_capability("cap_alpha")
        self._write_descriptor_set([
            {"id": "cap-alpha", "name": "cap-alpha", "accepted": False},
        ])

        records = capability_health.check_capabilities(str(self.root))
        twin = next(r for r in records if r["capability_id"] == "cap-alpha")

        self.assertEqual(twin["health"], "pending")
        self.assertEqual(twin["identity_twin_of"], "cap_alpha")
        self.assertIsNotNone(twin["operator_message"])

        # The real, built capability is completely unaffected.
        real = next(r for r in records if r["capability_id"] == "cap_alpha")
        self.assertEqual(real["health"], "green")

    def test_twin_carrying_real_state_is_identity_conflict_not_red(self):
        self._write_capability("cap_alpha")
        self._write_descriptor_set([
            {"id": "cap-alpha", "name": "cap-alpha", "accepted": False},
        ])
        # Real recorded state of its own -- an acceptance-audit record -- so it cannot simply be
        # discarded, unlike the state-free twin above.
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"capability_id": "cap-alpha", "note": "test fixture"}) + "\n")

        records = capability_health.check_capabilities(str(self.root))
        twin = next(r for r in records if r["capability_id"] == "cap-alpha")

        self.assertEqual(twin["health"], "identity_conflict")
        self.assertEqual(twin["identity_twin_of"], "cap_alpha")
        self.assertIsNotNone(twin["operator_message"])


# =============================================================================
# Scenario 4 -- lifecycle-hermeticity test-quality probe
# =============================================================================

_AMBIENT_TEST_SOURCE = '''"""Fixture: a capability test that reads the write gate's ambient pause state directly
(isolation-validation fixture -- deliberately the shape the lifecycle-hermeticity probe exists
to catch)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

import external_write.capability_api
from external_write.operations import Operation
from external_write.write_gate import evaluate_write_gate

if False:  # AST-only guarded reference -- never executed; the probe this fixture exists to
           # trip is a purely structural AST check, independent of whether this call path is
           # actually reachable at runtime.
    external_write.capability_api.run_enveloped_operation()


class Test{class_suffix}Ambient(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "{cap_id} ready")

    def test_reads_ambient_pause_state(self):
        if False:  # AST-only guarded call -- never executed.
            op = Operation(surface="{cap_id}", object_id="row:1", field="__record__",
                           new_value="<x>", op_kind="{op_kind}", batch_id="b1")
            evaluate_write_gate(op, target="live")


if __name__ == "__main__":
    unittest.main()
'''

_HERMETIC_TEST_SOURCE = '''"""Fixture: the identical paused-behavior check, rewritten hermetically through the emitted
``hermetic_paused_mechanisms`` fixture (isolation-validation fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

import external_write.capability_api
from external_write.lifecycle_test_fixtures import hermetic_paused_mechanisms
from external_write.operations import Operation
from external_write.write_gate import evaluate_write_gate

if False:  # AST-only guarded reference -- never executed.
    external_write.capability_api.run_enveloped_operation()


class Test{class_suffix}Hermetic(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "{cap_id} ready")

    def test_paused_behavior_is_exercised_hermetically(self):
        if False:  # AST-only guarded call -- never executed.
            op = Operation(surface="{cap_id}", object_id="row:1", field="__record__",
                           new_value="<x>", op_kind="{op_kind}", batch_id="b1")
            with hermetic_paused_mechanisms(["{op_kind}"]) as paused_root:
                evaluate_write_gate(op, target="live", paused_root=paused_root)


if __name__ == "__main__":
    unittest.main()
'''


class LifecycleHermeticityProbeTest(_IsolationFixtureBase):
    """The lifecycle-hermeticity test-quality probe (Task A3), composed against two real,
    fully-runnable capability test suites: one that reads the write gate's ambient pause state
    directly, one that rewrites the identical check hermetically."""

    def setUp(self):
        super().setUp()
        # This scenario's dynamic known-bad-fails probe runs the discovered test file(s) against
        # an ISOLATED COPY of the whole project tree, so this fixture project needs a real,
        # importable ``external_write`` package under its own ``agents/lib/`` for that
        # subprocess run's imports to succeed -- the same staging convention this package's own
        # per-task test suite already uses (never a copytree of a whole prior/estate project;
        # this copies only the small runtime library package itself).
        dest = self.root / "agents" / "lib" / "external_write"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(_AGENTS_LIB / "external_write", dest)

    def _write_test_file(self, cap_id: str, source_template: str) -> None:
        module_name = f"{cap_id}_capability"
        source = source_template.format(
            module_name=module_name, cap_id=cap_id, op_kind=OP_KIND,
            class_suffix="".join(part.capitalize() for part in cap_id.split("_")),
        )
        path = self.root / CAPABILITIES_DIR_REL / "tests" / f"test_{cap_id}_capability.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def test_ambient_pause_read_fails_the_hermeticity_probe(self):
        cap_id = "cap_epsilon"
        self._write_capability(cap_id)
        self._write_test_file(cap_id, _AMBIENT_TEST_SOURCE)

        result = capability_invariants.check_test_quality(str(self.root), cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Lifecycle hermeticity") for f in result.failures),
            result.failures,
        )

    def test_hermetic_rewrite_passes_the_full_battery(self):
        cap_id = "cap_zeta"
        self._write_capability(cap_id)
        self._write_test_file(cap_id, _HERMETIC_TEST_SOURCE)

        result = capability_invariants.check_test_quality(str(self.root), cap_id)

        self.assertTrue(result.ok, result.failures)
        self.assertEqual(result.failures, [])


if __name__ == "__main__":
    unittest.main()
