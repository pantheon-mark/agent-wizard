"""Cluster-B isolation validation: a composition regression net proving that the
contract-kernel + upgrade-carries-forward behaviors hold TOGETHER, not merely in
isolation -- the "upgrade carries a paused capability forward" gauntlet.

This module is TEST-ONLY: it composes the REAL, already-shipped entrypoints
(``external_write.capability_invariants.check_capability_invariants``,
``upgrade_reconcile.reconcile_missing_evidence_predicates`` /
``reconcile_upgrade``, ``capability_code_scaffold.emit_capability_code_scaffold``,
``external_write.copy_run_proof.validate_copy_run_proof``, the
``external_write.registered_adapters`` operator-enrollment union) over fresh,
op-kind-agnostic fixture projects. It never re-tests every edge those modules'
own dedicated test files already cover in depth -- it proves the four behaviors
compose: a capability carried forward by an upgrade is (1) still checked by the
shared adapter-evidence-predicate contract at self-QA time, BEFORE any trial;
(2) automatically given a failing, honest stub (never a silent pass) plus a
queued repair when the contract adds a requirement it lacks; (3) never loses an
operator-added adapter enrollment when the baseline import list is regenerated;
and (4) routed at the dedicated rebuild flow, never at the new-capability flow.

Anti-overfit posture (mirrors this package's own established convention): every
fixture is written at a REAL emitted relative path inside a fresh
``tempfile.TemporaryDirectory()`` -- never a ``copytree`` of the dev tree (the
one exception, scenario 3 below, copies the REAL shipped ``external_write``
package itself, which is exactly what ships into every operator project
verbatim -- there is no fixture substitute for "the real baseline file a bundle
upgrade re-copies").

Generic, op-kind-agnostic throughout: capability ids, op_kinds, and mechanism
names below are all synthetic probes, never tied to any one real-world
integration.
"""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------------------
# Path setup -- mirrors the "single-home canonical location" convention every
# sibling test file in this package already uses.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent                       # wizard/scripts/lib
_AGENTS_LIB = _HERE.parents[1] / "agents" / "lib"              # wizard/agents/lib
_REAL_REPO = _HERE.parents[2]                                  # repo root

sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_AGENTS_LIB))

from capability_code_scaffold import (  # noqa: E402
    CapabilityCodeSpec,
    emit_capability_code_scaffold,
)
from upgrade_reconcile import (  # noqa: E402
    MIGRATION_QUEUE_REL,
    PredicateStubRemediation,
    reconcile_missing_evidence_predicates,
    reconcile_upgrade,
)

from external_write import capability_invariants  # noqa: E402
from external_write import contracts as contracts_mod  # noqa: E402
from external_write import evidence  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    register_adapter,
    unregister_adapter,
)
from external_write.contracts import OperationContract  # noqa: E402
from external_write.copy_run_proof import (  # noqa: E402
    COPY_RUN_PROOF_SCHEMA,
    validate_copy_run_proof,
)
from external_write.proof_hash import SHA256_HEX_LEN  # noqa: E402
from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA  # noqa: E402


CAPABILITIES_DIR_REL = "agents/capabilities"
DESCRIPTOR_SET_REL = "security/capability_descriptors.json"


# =============================================================================
# Scenario 1: the shared adapter-evidence-predicate contract fails self-QA
# fast, BEFORE any trial -- and the required set is read from the ONE shared
# canonical source, never a local hardcoded copy.
# =============================================================================

_CLEAN_CAPABILITY_SOURCE = '''"""{name} -- gate-clean capability module (isolation test fixture)."""

from typing import Any

OP_KIND = "{op_kind}"


def describe() -> str:
    return "{name} ready"


def propose_operations(facade: Any, batch_id: str):
    return []
'''


class _MissingUndoPredicateAdapter:
    """Declares only ``verify_apply_landed`` -- the deliberate violation this
    scenario's Check 7 exists to catch before any trial."""

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


class _FullPredicatePairAdapter:
    """Declares BOTH currently-required predicates -- the clean case."""

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


class ContractKernelSelfQAFailFastTests(unittest.TestCase):
    """A capability whose registered adapter is missing a required evidence
    predicate fails the emitted self-QA (capability_invariants' Step-4 check)
    BEFORE any trial is ever attempted -- never merely mid-proof -- and the
    required set is read from the one shared canonical source
    (``evidence.REQUIRED_EVIDENCE_PREDICATES``), not a hardcoded local list."""

    OP_KIND = "widget.tidy.b_iso_probe_1"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.capability_id = "b_iso_missing_predicate_widget"
        self.addCleanup(self._unregister)

        contracts_mod.register_contract(OperationContract(
            op_kind=self.OP_KIND, writes=("value",), produces=(), dependency_set=(),
            verifier_set=("operator_attested_v1",), introduces_persistent_binding=False,
            risk_class="reversible_external",
        ))

        cap_dir = self.project_root / CAPABILITIES_DIR_REL
        cap_dir.mkdir(parents=True)
        (cap_dir / f"{self.capability_id}_capability.py").write_text(
            _CLEAN_CAPABILITY_SOURCE.format(name=self.capability_id, op_kind=self.OP_KIND),
            encoding="utf-8",
        )
        descriptor_path = self.project_root / DESCRIPTOR_SET_REL
        descriptor_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor_path.write_text(json.dumps([{
            "id": self.capability_id,
            "name": self.capability_id,
            "action_class": "in_place_edit",
            "risk_class": "reversible_external",
            "recovery_profile_ref": None,
            "declared_test_target": "copy",
            "blast_radius_cap": 5,
            "accepted": False,
        }]), encoding="utf-8")

    def _unregister(self):
        unregister_adapter(self.OP_KIND)
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)

    def _check(self):
        return capability_invariants.check_capability_invariants(
            str(self.project_root), self.capability_id)

    def test_missing_predicate_fails_fast_before_any_trial(self):
        register_adapter(self.OP_KIND, _MissingUndoPredicateAdapter())
        result = self._check()

        self.assertFalse(result.ok)
        self.assertEqual(
            len(result.failures), 1,
            f"only the adapter-evidence-predicate check should fail here: {result.failures!r}",
        )
        failure = result.failures[0]
        self.assertTrue(failure.startswith("Adapter evidence predicates:"))
        self.assertIn("verify_undo_restored", failure)
        self.assertIn("stays paused", failure)
        self.assertNotIn("Traceback", result.operator_message)

    def test_full_predicate_pair_passes_every_check(self):
        register_adapter(self.OP_KIND, _FullPredicatePairAdapter())
        result = self._check()
        self.assertTrue(result.ok, result.operator_message)

    def test_required_set_is_read_from_the_one_shared_source(self):
        # Even a currently-full adapter must fail once the SHARED contract grows a
        # new required name -- proving Check 7 reads the shared tuple live, at call
        # time, rather than a frozen/local copy of today's two names.
        register_adapter(self.OP_KIND, _FullPredicatePairAdapter())
        self.assertTrue(self._check().ok)

        new_required = evidence.REQUIRED_EVIDENCE_PREDICATES + (
            "verify_b_iso_new_predicate_probe",)
        with mock.patch.object(evidence, "REQUIRED_EVIDENCE_PREDICATES", new_required):
            result = self._check()
        self.assertFalse(result.ok)
        self.assertTrue(any("verify_b_iso_new_predicate_probe" in f for f in result.failures))


# =============================================================================
# Scenario 2: the migrator auto-scaffolds a FAILING stub for a required
# predicate a paused capability's adapter lacks -- never a passing stub -- and
# the capability's proof still refuses until a real implementation replaces it.
# =============================================================================

_ADAPTER_SOURCE_MISSING_UNDO_PREDICATE = '''"""Fixture adapter (isolation test) -- built under an EARLIER version of the
shared contract that required only verify_apply_landed; verify_undo_restored
is not yet declared, simulating a capability that predates a later-added
requirement."""
from external_write.adapter_registry import register_adapter
from external_write.contracts import OperationContract, WRITE_AFFECTING_MODULES, register_contract

OP_KIND = "widget.tidy.b_iso_probe_2"

register_contract(OperationContract(
    op_kind=OP_KIND, writes=("Status",), produces=(), dependency_set=WRITE_AFFECTING_MODULES,
    verifier_set=("prestate_snapshot_diff_v1",), introduces_persistent_binding=False,
    risk_class="reversible_external", requires_accepted_phase=True, blast_radius_cap=5,
    read_only_scope="generic_widget.readonly",
))


class WidgetTidyIsoProbeAdapter:
    def build_write_client(self, op):
        raise NotImplementedError

    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        return {}

    def verify_apply_landed(self, evidence):
        return True


register_adapter(OP_KIND, WidgetTidyIsoProbeAdapter())
'''

_B2_OP_KIND = "widget.tidy.b_iso_probe_2"
_B2_CAPABILITY_ID = "b_iso_stub_scaffold_widget"


def _verification_record():
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
        "invariant_checked": "value stable",
        "evidence_ref": "agents/handoffs/.b_iso_probe_2_ev.txt",
    }


def _copy_run_proof_for(op_kind):
    return {
        "schema": COPY_RUN_PROOF_SCHEMA,
        "operation_id": "b-iso-probe-2-op-001",
        "op_kind": op_kind,
        "data_class": "test_rows",
        "copy_source_ref": "copies/copy.csv",
        "prestate_snapshot_ref": "copies/copy.prestate.csv",
        "copy_apply_proof": {
            "apply_receipt_ref": "agents/handoffs/.apply_receipt.json",
            "apply_verification": _verification_record(),
            "apply_evidence": {
                "unit_id": "row1", "prestate": {"value": "Open"},
                "poststate": {"value": "Done", "intended_value": "Done"},
            },
        },
        "copy_undo_proof": {
            "undo_receipt_ref": "agents/handoffs/.undo_receipt.json",
            "undo_verification": _verification_record(),
            "undo_evidence": {
                "unit_id": "row1", "prestate": {"value": "Open"},
                "poststate": {"value": "Open"},
            },
        },
        "durability_checks": [],
        "accepted_for_live_use": True,
        "implementation_hash": "a" * SHA256_HEX_LEN,
        "contract_hash": "b" * SHA256_HEX_LEN,
    }


class MigratorScaffoldsFailingStubTests(unittest.TestCase):
    """An upgrade whose changed contract requires a predicate an existing,
    already-gate-conformant capability's adapter does not declare gets a
    FAILING ``NotImplementedError`` stub auto-scaffolded onto it (never a
    passing stub) plus a queued repair task; the capability's proof attempt
    still REFUSES with the stub in place, and only a real implementation for
    the same op_kind can pass."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.proj = Path(self._tmp.name) / "operator_project"
        self.addCleanup(self._unregister)

        cap_dir = self.proj / "agents" / "capabilities"
        cap_dir.mkdir(parents=True)
        (cap_dir / f"{_B2_CAPABILITY_ID}_capability.py").write_text(
            '"""fixture capability module (isolation test) -- only presence matters '
            'for capability enumeration."""\n',
            encoding="utf-8",
        )
        ext_dir = self.proj / "agents" / "lib" / "external_write"
        ext_dir.mkdir(parents=True)
        self.adapter_path = ext_dir / f"adapters_{_B2_CAPABILITY_ID}.py"
        self.adapter_path.write_text(
            _ADAPTER_SOURCE_MISSING_UNDO_PREDICATE, encoding="utf-8")

    def _unregister(self):
        unregister_adapter(_B2_OP_KIND)
        contracts_mod.OPERATION_CONTRACTS.pop(_B2_OP_KIND, None)

    def test_scaffolds_failing_stub_and_queues_repair_for_missing_predicate(self):
        result = reconcile_missing_evidence_predicates(
            self.proj, _REAL_REPO, from_version="1.0.0", to_version="1.1.0")

        self.assertEqual(len(result), 1)
        remediation = result[0]
        self.assertIsInstance(remediation, PredicateStubRemediation)
        self.assertEqual(remediation.canonical_id, _B2_CAPABILITY_ID)
        self.assertIn("verify_undo_restored", remediation.missing_predicates)
        self.assertNotIn("verify_apply_landed", remediation.missing_predicates)

        new_source = self.adapter_path.read_text(encoding="utf-8")
        self.assertIn("def verify_undo_restored(self, evidence) -> bool:", new_source)
        self.assertIn("raise NotImplementedError(", new_source)
        self.assertIn("stays paused", new_source)
        # The existing, already-correct predicate is left untouched.
        self.assertIn(
            "def verify_apply_landed(self, evidence):\n        return True", new_source)

        queue = json.loads((self.proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        entry = next(e for e in queue if e["mechanism_id"] == _B2_CAPABILITY_ID)
        self.assertEqual(entry["kind"], "missing_evidence_predicates")
        self.assertIn("verify_undo_restored", entry["missing_predicates"])
        self.assertEqual(entry["status"], "pending")

    def test_scaffolded_stub_refuses_the_proof_only_a_real_impl_passes(self):
        reconcile_missing_evidence_predicates(
            self.proj, _REAL_REPO, from_version="1.0.0", to_version="1.1.0")

        # Actually IMPORT the real, on-disk, scaffolded adapter module -- not
        # merely inspect its text -- so the real `raise` executes when the proof
        # gate calls the stub. A module name that cannot collide with anything
        # else already imported in this process.
        module_spec = importlib.util.spec_from_file_location(
            "adapters_b_iso_stub_scaffold_widget_isotest", self.adapter_path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)  # fires register_adapter/register_contract

        proof = _copy_run_proof_for(_B2_OP_KIND)
        stub_result = validate_copy_run_proof(proof)
        self.assertFalse(stub_result.ok)
        self.assertNotIn("Traceback", stub_result.reason or "")
        self.assertIn("verify_undo_restored raised", stub_result.reason)
        self.assertIn("stays paused", stub_result.reason)

        class _RealAdapter:
            def plan(self, params):
                return []

            def apply_one(self, raw_client, unit):
                pass

            def undo_one(self, raw_client, unit):
                pass

            def verify_one(self, observer, unit):
                return {}

            def verify_apply_landed(self, ev):
                return (ev.poststate.get("value") == "Done"
                        and ev.prestate.get("value") != "Done")

            def verify_undo_restored(self, ev):
                return ev.poststate.get("value") == ev.prestate.get("value")

        unregister_adapter(_B2_OP_KIND)
        register_adapter(_B2_OP_KIND, _RealAdapter())
        real_result = validate_copy_run_proof(proof)
        self.assertTrue(real_result.ok, real_result.reason)


# =============================================================================
# Scenario 3: an operator-added adapter enrollment survives a wholesale
# regeneration of the baseline import list -- the exact mechanism a
# contract-changing bundle upgrade performs on that one file. A dropped
# enrollment must be impossible by construction, never dependent on a
# text/AST merge.
# =============================================================================

class OperatorEnrollmentSurvivesBaselineRegenTests(unittest.TestCase):
    """An operator-added adapter, recorded in the segregated operator-adapter
    manifest, is still resolvable through the adapter registry AFTER the
    baseline import-list file is wholesale regenerated/re-copied -- never
    dropped, and never dependent on a merge that could fail."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name) / "operator_project"

        # Isolate the interpreter's shared `external_write` module cache: this
        # test imports a FRESH copy of the package rooted at a temp project
        # path, which must never be confused with (or leak into) the real
        # repo's canonical copy every other test in this same process relies
        # on. Snapshot-and-restore, regardless of what this test does.
        self._saved_sys_path = list(sys.path)
        self._saved_ew_modules = {
            name: mod for name, mod in sys.modules.items()
            if name == "external_write" or name.startswith("external_write.")
        }
        self.addCleanup(self._restore_external_write_state)

    def _restore_external_write_state(self):
        sys.path[:] = self._saved_sys_path
        for name in list(sys.modules):
            if name == "external_write" or name.startswith("external_write."):
                del sys.modules[name]
        sys.modules.update(self._saved_ew_modules)

    def test_operator_adapter_survives_baseline_regeneration(self):
        external_write_dir = self.project_root / "agents" / "lib" / "external_write"
        shutil.copytree(_AGENTS_LIB / "external_write", external_write_dir)

        spec = CapabilityCodeSpec(
            capability_id="b_iso_enrollment_widget",
            display_name="Isolation-test enrollment widget",
            op_kind="widget.tidy.b_iso_probe_3",
            surface="generic_widget_system",
            read_only_scope="generic_widget.readonly",
            blast_radius_cap=5,
        )
        emit_capability_code_scaffold(spec, self.project_root)

        operator_manifest = json.loads(
            (external_write_dir / "operator_adapters.json").read_text(encoding="utf-8"))
        self.assertIn(spec.adapter_module_stem, operator_manifest)

        # Simulate the upgrade mechanism: a contract-changing bundle upgrade
        # WHOLESALE RE-COPIES the baseline import-list file from the new bundle
        # version's template -- it never merges, it overwrites. Reuses the REAL
        # shipped file's own text (not a hand-authored stand-in) as "the new
        # template being re-copied."
        shipped_text = (_AGENTS_LIB / "external_write" / "registered_adapters.py").read_text(
            encoding="utf-8")
        (external_write_dir / "registered_adapters.py").write_text(
            shipped_text, encoding="utf-8")

        # Fresh, post-"upgrade" import of THIS PROJECT's own external_write
        # copy (never the real repo's) -- proves resolution survives the
        # regen, not merely that it worked before the regen ever happened.
        for name in list(sys.modules):
            if name == "external_write" or name.startswith("external_write."):
                del sys.modules[name]
        sys.path.insert(0, str(external_write_dir.parent))
        import external_write.registered_adapters  # noqa: F401 -- fires the union import
        from external_write.adapter_registry import get_dispatch

        dispatch = get_dispatch(spec.op_kind)
        self.assertIsNotNone(
            dispatch,
            "an operator-enrolled adapter must resolve after the baseline import "
            "list is regenerated -- a dropped enrollment must be impossible by "
            "construction",
        )


# =============================================================================
# Scenario 4: a pending-migration entry routes the operator at the dedicated
# rebuild-paused-capability flow, never at the new-capability flow.
# =============================================================================

_GENERIC_DIRECT_WRITER = '''"""Generic sync job -- writes directly to an external system, bypassing the
safe write path (isolation test fixture; no wrapper script exists for this
mechanism)."""
from googleapiclient.discovery import build


def apply_fixes(svc, sheet_id, fixes):
    body = {"valueInputOption": "RAW", "data": fixes}
    svc.spreadsheets().values().batchUpdate(spreadsheetId=sheet_id, body=body).execute()


def main():
    return 0


if __name__ == "__main__":
    main()
'''


class RebuildRoutingTests(unittest.TestCase):
    """A pending-migration entry's suggested next step names the dedicated
    rebuild-paused-capability flow, never the new-capability flow -- the
    latter's own scope is a genuinely new capability only and dead-ends on an
    existing paused one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_migration_entry_routes_to_rebuild_flow_not_new_capability_flow(self):
        proj = self.tmp / "operator_project"
        cron_dir = proj / "agents" / "cron"
        cron_dir.mkdir(parents=True)
        (cron_dir / "generic_row_sync.py").write_text(_GENERIC_DIRECT_WRITER, encoding="utf-8")
        # No run_generic_row_sync.sh wrapper -- exercises the "no conventional
        # entrypoint" migration-queue path, distinct from scenario 2's
        # predicate-stub queue path above.

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="1.0.0", to_version="1.1.0")

        self.assertTrue(result.any_affected)
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        entry = next(e for e in queue if e["mechanism_id"] == "generic_row_sync")
        self.assertIn("rebuild-paused-capability", entry["suggested_next_step"])
        self.assertNotIn("add-capability", entry["suggested_next_step"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
