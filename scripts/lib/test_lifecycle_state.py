"""Tests for the emitted lifecycle-state reconciler (external_write.lifecycle_state — Task B1,
Phase 3 Cut 1).

The property under test: ``descriptor.accepted`` is the single source of truth, and
``reconcile_state`` is the ONE idempotent function that makes the pause marker
(``.wizard/paused-mechanisms/<canonical_id>.{pause,json}``) and the pending-migration queue
(``agents/handoffs/pending_migrations.json``) agree with it -- never the reverse, and never a
silent no-op that leaves "accepted:true but still paused" limbo.

ANTI-OVERFIT (v0.13.0 T7 lesson, reused per this task's brief): every fixture is written at the
REAL emitted relative path (``agents/capabilities/<capability_id>_capability.py``,
``security/capability_descriptors.json``, ``agents/handoffs/pending_migrations.json``) inside a
fresh ``tempfile.TemporaryDirectory()`` -- never a ``copytree`` of the dev tree. At least two
distinct capability_ids are exercised in every fixture below.

Uses stub/synthetic capability source only; no network.
"""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (canonical location) -- mirrors
# test_external_write_write_gate.py / test_capability_health.py's own convention.
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import lifecycle_state  # noqa: E402
from external_write.capability_identity import IdentityResolutionError  # noqa: E402
from external_write.acceptance_ceremony import ACCEPTANCE_RECORD_SCHEMA  # noqa: E402
from external_write.proof_hash import compute_implementation_hash  # noqa: E402
import external_write.contracts as _contracts  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.adapter_registry import register_adapter, unregister_adapter  # noqa: E402

# The throwaway op_kind + fixture adapter this file's staleness tests mutate to flip a hash --
# SAME reuse pattern as test_external_write_effects_manifest.py's own fixture (a real,
# genuinely-hashed file on disk; never a mocked/stubbed hash).
_STALE_FIXTURE_OP_KIND = "_lifecycle_state_fixture_stale_op"
_STALE_FIXTURE_MODULE_PREFIX = "_lifecycle_state_fixture_adapter_module"
_FIXTURE_ADAPTER_SRC = (
    Path(__file__).resolve().parents[2] / "test_fixtures" / "effects_manifest" / "fixture_adapter.py"
)
# A SECOND capability's op_kind that carries NO registered adapter and an EMPTY dependency_set --
# its implementation_hash is therefore stable across every mutation the fixture-adapter tests
# make to the FIRST (fixture) op_kind's adapter, proving an unrelated accepted capability is never
# disturbed.
_STABLE_FIXTURE_OP_KIND = "_lifecycle_state_fixture_stable_op"


def _load_adapter_module(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_capability(root, cap_id, op_kind=None, surface=None):
    d = Path(root) / "agents" / "capabilities"
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    if surface:
        lines.append(f'SURFACE = "{surface}"')
    if op_kind:
        lines.append(f'OP_KIND = "{op_kind}"')
    lines.append(f"# capability {cap_id}")
    (d / f"{cap_id}_capability.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_descriptors(root, entries):
    d = Path(root) / "security"
    d.mkdir(parents=True, exist_ok=True)
    (d / "capability_descriptors.json").write_text(
        json.dumps(entries, indent=2), encoding="utf-8")


def _write_pending_migrations(root, entries):
    d = Path(root) / "agents" / "handoffs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pending_migrations.json").write_text(
        json.dumps(entries, indent=2), encoding="utf-8")


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _marker_dir_snapshot(root):
    """{relpath: bytes} for every file under .wizard/paused-mechanisms/, for a byte-identical
    comparison across two reconcile_state calls."""
    marker_dir = Path(root) / lifecycle_state.PAUSED_MECHANISMS_DIR_REL
    if not marker_dir.is_dir():
        return {}
    return {
        str(p.relative_to(marker_dir)): p.read_bytes()
        for p in sorted(marker_dir.rglob("*")) if p.is_file()
    }


class ReconcilePausedIsCoherentTests(unittest.TestCase):
    def test_reconcile_paused_is_coherent(self):
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "acme_widget_deleter", op_kind="acme.widget.delete")
            _write_capability(root, "acme_report_reader")  # second, unrelated capability_id
            _write_descriptors(root, [
                {"id": "acme_widget_deleter", "accepted": False},
                {"id": "acme_report_reader", "accepted": True},
            ])
            _write_pending_migrations(root, [
                {"mechanism_id": "acme_widget_deleter", "status": "pending"},
            ])

            result = lifecycle_state.reconcile_state(root, "acme_widget_deleter")

            self.assertEqual(result.canonical_id, "acme_widget_deleter")
            self.assertFalse(result.accepted)
            self.assertTrue(result.marker_present)
            self.assertTrue(result.migration_open)
            self.assertTrue(result.changed)

            marker_dir = Path(root) / lifecycle_state.PAUSED_MECHANISMS_DIR_REL
            self.assertTrue((marker_dir / "acme_widget_deleter.pause").is_file())
            state = _read_json(marker_dir / "acme_widget_deleter.json")
            self.assertEqual(state["canonical_id"], "acme_widget_deleter")
            self.assertEqual(state["mechanism_id"], "acme_widget_deleter")
            self.assertEqual(state["paused_op_kinds"], ["acme.widget.delete"])
            self.assertEqual(state["state"], "paused_live_write")

            # The migration entry is left queued (this branch never fabricates or removes a
            # queue entry -- it only ensures the marker matches the pre-existing migration).
            queue = _read_json(Path(root) / lifecycle_state.MIGRATION_QUEUE_REL)
            self.assertEqual(len(queue), 1)
            self.assertEqual(queue[0]["mechanism_id"], "acme_widget_deleter")

            # No unrelated capability's descriptor got touched.
            descriptors = _read_json(Path(root) / lifecycle_state.DESCRIPTOR_SET_REL)
            self.assertTrue(any(
                e["id"] == "acme_report_reader" and e["accepted"] is True for e in descriptors))
            self.assertFalse(
                (marker_dir / "acme_report_reader.pause").exists())


class ReconcilePreservesUpgradeDiagnosticsTests(unittest.TestCase):
    """(Coordinator review, must-fix #1) A capability paused at UPGRADE time by
    ``upgrade_reconcile._write_paused_live_write_state`` carries diagnostic fields
    (``from_version``, ``to_version``, ``violations``, a specific ``reason``) that
    ``lifecycle_state._ensure_paused_marker`` must never discard on a later
    ``reconcile_state`` call -- it must MERGE (add/repair ``canonical_id`` and
    ``paused_op_kinds`` if stale) rather than replace the whole record."""

    def test_ensure_marker_merges_not_replaces_upgrade_time_marker(self):
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "acme_widget_deleter", op_kind="acme.widget.delete")
            _write_capability(root, "acme_report_reader")
            _write_descriptors(root, [
                {"id": "acme_widget_deleter", "accepted": False},
                {"id": "acme_report_reader", "accepted": True},
            ])
            _write_pending_migrations(root, [
                {"mechanism_id": "acme_widget_deleter", "status": "pending"},
            ])

            # Seed a marker shaped exactly like upgrade_reconcile._write_paused_live_write_state's
            # real output -- no `canonical_id` (the pre-B1 shape), plus upgrade-time-only
            # diagnostic fields this fix must not discard.
            marker_dir = Path(root) / lifecycle_state.PAUSED_MECHANISMS_DIR_REL
            marker_dir.mkdir(parents=True, exist_ok=True)
            (marker_dir / "acme_widget_deleter.pause").write_text("", encoding="utf-8")
            upgrade_time_state = {
                "mechanism_id": "acme_widget_deleter",
                "writer_relpath": "agents/capabilities/acme_widget_deleter.py",
                "entrypoint_relpath": None,
                "state": "paused_live_write",
                "paused_op_kinds": ["acme.widget.delete"],
                "paused_at": "2026-01-01T00:00:00Z",
                "from_version": "v0.13.0",
                "to_version": "v0.13.1",
                "reason": "external-write gate violation detected on upgrade",
                "violations": [{"path": "agents/capabilities/acme_widget_deleter.py",
                                 "line": 12, "kind": "raw_kernel_write"}],
                "credentials_preserved": True,
                "migration_status": "pending",
            }
            (marker_dir / "acme_widget_deleter.json").write_text(
                json.dumps(upgrade_time_state, indent=2, sort_keys=True), encoding="utf-8")

            result = lifecycle_state.reconcile_state(root, "acme_widget_deleter")
            self.assertTrue(result.changed)

            state = _read_json(marker_dir / "acme_widget_deleter.json")
            # The new field, back-filled.
            self.assertEqual(state["canonical_id"], "acme_widget_deleter")
            # Every upgrade-time diagnostic field survives UNCHANGED.
            self.assertEqual(state["from_version"], "v0.13.0")
            self.assertEqual(state["to_version"], "v0.13.1")
            self.assertEqual(state["reason"], "external-write gate violation detected on upgrade")
            self.assertEqual(state["violations"], upgrade_time_state["violations"])
            self.assertEqual(state["paused_at"], "2026-01-01T00:00:00Z")
            self.assertEqual(state["paused_op_kinds"], ["acme.widget.delete"])
            self.assertEqual(state["mechanism_id"], "acme_widget_deleter")

            # Idempotent: a second call performs no further write.
            second = lifecycle_state.reconcile_state(root, "acme_widget_deleter")
            self.assertFalse(second.changed)
            state_after_second = _read_json(marker_dir / "acme_widget_deleter.json")
            self.assertEqual(state, state_after_second)

    def test_ensure_marker_merge_updates_stale_op_kinds_without_losing_other_fields(self):
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "acme_widget_deleter", op_kind="acme.widget.delete")
            _write_capability(root, "acme_report_reader")
            _write_descriptors(root, [{"id": "acme_widget_deleter", "accepted": False}])
            _write_pending_migrations(root, [
                {"mechanism_id": "acme_widget_deleter", "status": "pending"},
            ])
            marker_dir = Path(root) / lifecycle_state.PAUSED_MECHANISMS_DIR_REL
            marker_dir.mkdir(parents=True, exist_ok=True)
            (marker_dir / "acme_widget_deleter.pause").write_text("", encoding="utf-8")
            stale_state = {
                "mechanism_id": "acme_widget_deleter",
                "writer_relpath": "agents/capabilities/acme_widget_deleter.py",
                "entrypoint_relpath": None,
                "state": "paused_live_write",
                "paused_op_kinds": ["acme.widget.delete_stale_kind"],
                "paused_at": "2026-01-01T00:00:00Z",
                "from_version": "v0.12.0",
                "to_version": "v0.12.1",
                "reason": "external-write gate violation detected on upgrade",
                "violations": [],
                "credentials_preserved": True,
                "migration_status": "pending",
            }
            (marker_dir / "acme_widget_deleter.json").write_text(
                json.dumps(stale_state, indent=2, sort_keys=True), encoding="utf-8")

            result = lifecycle_state.reconcile_state(root, "acme_widget_deleter")
            self.assertTrue(result.changed)
            state = _read_json(marker_dir / "acme_widget_deleter.json")
            self.assertEqual(state["paused_op_kinds"], ["acme.widget.delete"])
            self.assertEqual(state["canonical_id"], "acme_widget_deleter")
            # Upgrade diagnostics from the ORIGINAL (stale-op-kind) writer still survive.
            self.assertEqual(state["from_version"], "v0.12.0")
            self.assertEqual(state["to_version"], "v0.12.1")


class ReconcileAcceptedClearsViewsTests(unittest.TestCase):
    def test_reconcile_accepted_clears_views(self):
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "acme_widget_deleter", op_kind="acme.widget.delete")
            _write_capability(root, "acme_report_reader")
            _write_descriptors(root, [
                {"id": "acme_widget_deleter", "accepted": True},
                {"id": "acme_report_reader", "accepted": False},
            ])
            _write_pending_migrations(root, [
                {"mechanism_id": "acme_widget_deleter", "status": "pending"},
            ])
            # A stale marker left over from a prior not-accepted state -- reconcile_state must
            # clear it now that the descriptor says accepted:true (no "accepted but paused" limbo).
            marker_dir = Path(root) / lifecycle_state.PAUSED_MECHANISMS_DIR_REL
            marker_dir.mkdir(parents=True, exist_ok=True)
            (marker_dir / "acme_widget_deleter.pause").write_text("", encoding="utf-8")
            (marker_dir / "acme_widget_deleter.json").write_text(
                json.dumps({"mechanism_id": "acme_widget_deleter",
                            "paused_op_kinds": ["acme.widget.delete"]}),
                encoding="utf-8")

            result = lifecycle_state.reconcile_state(root, "acme_widget_deleter")

            self.assertTrue(result.accepted)
            self.assertFalse(result.marker_present)
            self.assertFalse(result.migration_open)
            self.assertTrue(result.changed)

            self.assertFalse((marker_dir / "acme_widget_deleter.pause").exists())
            self.assertFalse((marker_dir / "acme_widget_deleter.json").exists())

            queue = _read_json(Path(root) / lifecycle_state.MIGRATION_QUEUE_REL)
            self.assertEqual(queue, [])


class ReconcileIsIdempotentTests(unittest.TestCase):
    def test_reconcile_is_idempotent_paused_branch(self):
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "acme_widget_deleter", op_kind="acme.widget.delete")
            _write_capability(root, "acme_report_reader")
            _write_descriptors(root, [
                {"id": "acme_widget_deleter", "accepted": False},
                {"id": "acme_report_reader", "accepted": True},
            ])
            _write_pending_migrations(root, [
                {"mechanism_id": "acme_widget_deleter", "status": "pending"},
            ])

            first = lifecycle_state.reconcile_state(root, "acme_widget_deleter")
            self.assertTrue(first.changed)
            marker_snapshot_1 = _marker_dir_snapshot(root)
            descriptors_1 = Path(root, lifecycle_state.DESCRIPTOR_SET_REL).read_bytes()
            migrations_1 = Path(root, lifecycle_state.MIGRATION_QUEUE_REL).read_bytes()

            second = lifecycle_state.reconcile_state(root, "acme_widget_deleter")
            self.assertFalse(second.changed)
            self.assertEqual(second.marker_present, first.marker_present)
            self.assertEqual(second.migration_open, first.migration_open)
            self.assertEqual(second.accepted, first.accepted)

            marker_snapshot_2 = _marker_dir_snapshot(root)
            descriptors_2 = Path(root, lifecycle_state.DESCRIPTOR_SET_REL).read_bytes()
            migrations_2 = Path(root, lifecycle_state.MIGRATION_QUEUE_REL).read_bytes()

            self.assertEqual(marker_snapshot_1, marker_snapshot_2)
            self.assertEqual(descriptors_1, descriptors_2)
            self.assertEqual(migrations_1, migrations_2)

    def test_reconcile_is_idempotent_accepted_branch(self):
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "acme_widget_deleter", op_kind="acme.widget.delete")
            _write_capability(root, "acme_report_reader")
            _write_descriptors(root, [
                {"id": "acme_widget_deleter", "accepted": True},
                {"id": "acme_report_reader", "accepted": False},
            ])
            _write_pending_migrations(root, [])

            first = lifecycle_state.reconcile_state(root, "acme_widget_deleter")
            marker_snapshot_1 = _marker_dir_snapshot(root)
            descriptors_1 = Path(root, lifecycle_state.DESCRIPTOR_SET_REL).read_bytes()
            migrations_1 = Path(root, lifecycle_state.MIGRATION_QUEUE_REL).read_bytes()

            second = lifecycle_state.reconcile_state(root, "acme_widget_deleter")
            self.assertFalse(second.changed)
            self.assertEqual(second.marker_present, first.marker_present)
            self.assertEqual(second.migration_open, first.migration_open)

            marker_snapshot_2 = _marker_dir_snapshot(root)
            descriptors_2 = Path(root, lifecycle_state.DESCRIPTOR_SET_REL).read_bytes()
            migrations_2 = Path(root, lifecycle_state.MIGRATION_QUEUE_REL).read_bytes()
            self.assertEqual(marker_snapshot_1, marker_snapshot_2)
            self.assertEqual(descriptors_1, descriptors_2)
            self.assertEqual(migrations_1, migrations_2)


class ReconcileNeverAcceptedNoMigrationTests(unittest.TestCase):
    def test_not_accepted_with_no_migration_is_a_no_op(self):
        # A brand-new capability that has simply never been accepted yet is NOT "paused" --
        # no marker should be invented for it.
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "acme_widget_deleter", op_kind="acme.widget.delete")
            _write_capability(root, "acme_report_reader")
            _write_descriptors(root, [
                {"id": "acme_widget_deleter", "accepted": False},
                {"id": "acme_report_reader", "accepted": True},
            ])
            _write_pending_migrations(root, [])

            result = lifecycle_state.reconcile_state(root, "acme_widget_deleter")
            self.assertFalse(result.accepted)
            self.assertFalse(result.marker_present)
            self.assertFalse(result.migration_open)
            self.assertFalse(result.changed)
            marker_dir = Path(root) / lifecycle_state.PAUSED_MECHANISMS_DIR_REL
            self.assertFalse(marker_dir.exists())


class ReconcileFailClosedTests(unittest.TestCase):
    def test_unresolvable_canonical_id_raises_identity_error(self):
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "acme_widget_deleter")
            _write_capability(root, "acme_report_reader")
            _write_descriptors(root, [{"id": "acme_widget_deleter", "accepted": False}])
            with self.assertRaises(IdentityResolutionError) as cm:
                lifecycle_state.reconcile_state(root, "does_not_exist")
            self.assertEqual(cm.exception.kind, "unresolved")
            self.assertTrue(cm.exception.operator_message)
            self.assertNotIn("Traceback", cm.exception.operator_message)

    def test_broken_descriptor_set_refuses_to_reconcile(self):
        with tempfile.TemporaryDirectory() as root:
            _write_capability(root, "acme_widget_deleter")
            _write_capability(root, "acme_report_reader")
            d = Path(root) / "security"
            d.mkdir(parents=True, exist_ok=True)
            (d / "capability_descriptors.json").write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(lifecycle_state.ReconcileStateError) as cm:
                lifecycle_state.reconcile_state(root, "acme_widget_deleter")
            self.assertTrue(cm.exception.operator_message)
            self.assertNotIn("Traceback", cm.exception.operator_message)


class MarkerShapeParityTests(unittest.TestCase):
    """(Minor, coordinator review) ``upgrade_reconcile._write_paused_live_write_state``
    (build-side) and ``lifecycle_state._ensure_paused_marker`` (this module) are two
    BY-VALUE-DUPLICATED writers of the same on-disk marker shape (see
    ``lifecycle_state.py``'s own "Reuse, not duplication" docstring section on why this pair
    is duplicated rather than imported across the build/runtime boundary). Pins the shared
    key subset present in BOTH real outputs, so a future rename or removal in either writer
    is caught here rather than silently drifting the two shapes apart."""

    SHARED_KEYS = (
        "mechanism_id", "paused_op_kinds", "writer_relpath", "entrypoint_relpath",
        "state", "credentials_preserved", "migration_status",
    )

    def test_shared_marker_keys_present_in_both_writers(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import upgrade_reconcile  # noqa: E402

        with tempfile.TemporaryDirectory() as ur_root:
            proj = Path(ur_root)
            relpath = "agents/capabilities/acme_widget_deleter.py"
            (proj / "agents" / "capabilities").mkdir(parents=True)
            (proj / relpath).write_text("OP_KIND = 'acme.widget.delete'\n", encoding="utf-8")
            upgrade_reconcile._write_paused_live_write_state(
                proj, "acme_widget_deleter", relpath, violations=[],
                from_version="v0.13.0", to_version="v0.13.1",
                paused_op_kinds=["acme.widget.delete"],
            )
            ur_state = _read_json(
                proj / upgrade_reconcile.PAUSED_MECHANISMS_DIR_REL / "acme_widget_deleter.json")

        with tempfile.TemporaryDirectory() as ls_root:
            _write_capability(ls_root, "acme_widget_deleter", op_kind="acme.widget.delete")
            _write_capability(ls_root, "acme_report_reader")
            _write_descriptors(ls_root, [{"id": "acme_widget_deleter", "accepted": False}])
            _write_pending_migrations(ls_root, [
                {"mechanism_id": "acme_widget_deleter", "status": "pending"}])
            lifecycle_state.reconcile_state(ls_root, "acme_widget_deleter")
            ls_state = _read_json(
                Path(ls_root) / lifecycle_state.PAUSED_MECHANISMS_DIR_REL /
                "acme_widget_deleter.json")

        for key in self.SHARED_KEYS:
            self.assertIn(key, ur_state, f"upgrade_reconcile's writer dropped {key!r}")
            self.assertIn(key, ls_state, f"lifecycle_state's writer dropped {key!r}")


# ===================================================================================
# Task B2b (Phase 3 Cut 1): conformant-rebuild acceptance-hash staleness detection +
# revocation. The F-62 half B2 does NOT close: a capability whose code changed since
# acceptance but stayed SCANNER-CLEAN (never enters the AST scanner's violation set at
# all) must not keep accepted:true forever, because write_gate authorizes on
# accepted-is-True alone and never re-checks implementation_hash.
#
# Uses a REAL registered throwaway op_kind + a REAL, genuinely-hashed adapter module
# file on disk (the SAME reuse pattern as test_external_write_effects_manifest.py's
# own fixture) -- mutating the fixture adapter's actual bytes is what flips
# proof_hash.compute_implementation_hash, never a mocked/stubbed hash value. A SECOND,
# unrelated capability_id (a stable op_kind with an empty dependency_set and no
# adapter) proves an unaffected accepted capability is never disturbed.
# ===================================================================================

class _StaleHashFixtureMixin:
    def setUp(self):
        super().setUp()
        self._prior_stale_contract = _contracts.OPERATION_CONTRACTS.get(_STALE_FIXTURE_OP_KIND)
        _contracts.OPERATION_CONTRACTS[_STALE_FIXTURE_OP_KIND] = OperationContract(
            op_kind=_STALE_FIXTURE_OP_KIND,
            writes=("__fixture__",),
            produces=(),
            dependency_set=(),  # only the registered adapter can contribute a dependency file
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="irreversible_external",
            requires_accepted_phase=True,
        )
        self._prior_stable_contract = _contracts.OPERATION_CONTRACTS.get(_STABLE_FIXTURE_OP_KIND)
        _contracts.OPERATION_CONTRACTS[_STABLE_FIXTURE_OP_KIND] = OperationContract(
            op_kind=_STABLE_FIXTURE_OP_KIND,
            writes=("__fixture__",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="irreversible_external",
            requires_accepted_phase=True,
        )
        self._loaded_modules = []

    def tearDown(self):
        unregister_adapter(_STALE_FIXTURE_OP_KIND)
        unregister_adapter(_STABLE_FIXTURE_OP_KIND)
        for op_kind, prior in (
            (_STALE_FIXTURE_OP_KIND, self._prior_stale_contract),
            (_STABLE_FIXTURE_OP_KIND, self._prior_stable_contract),
        ):
            if prior is None:
                _contracts.OPERATION_CONTRACTS.pop(op_kind, None)
            else:
                _contracts.OPERATION_CONTRACTS[op_kind] = prior
        for name in self._loaded_modules:
            sys.modules.pop(name, None)
        super().tearDown()

    def _register_fixture_adapter(self, adapter_dir, suffix, op_kind=_STALE_FIXTURE_OP_KIND):
        adapter_path = Path(adapter_dir) / f"fixture_adapter_{suffix}.py"
        shutil.copy2(_FIXTURE_ADAPTER_SRC, adapter_path)
        module_name = f"{_STALE_FIXTURE_MODULE_PREFIX}_{suffix}"
        module = _load_adapter_module(adapter_path, module_name)
        self._loaded_modules.append(module_name)
        register_adapter(op_kind, module.FixtureAdapter())
        return adapter_path

    def _write_acceptance_record(self, root, cap_id, phase_id, implementation_hash, op_kind,
                                 audit_log_rel=None):
        log_path = Path(root) / (audit_log_rel or lifecycle_state.ACCEPTANCE_LOG_REL)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": ACCEPTANCE_RECORD_SCHEMA,
            "capability_id": cap_id,
            "phase_id": phase_id,
            "risk_class": "irreversible_external",
            "op_kind": op_kind,
            "copy_run_proof_ref": "proof.json",
            "operator_receipt_ref": "receipt.json",
            "contract_hash": "0" * 64,
            "implementation_hash": implementation_hash,
            "operator_confirmation": "Yes, accept this capability for live use.",
            "receipt_accepted_at": "2026-01-01T00:00:00Z",
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return record


class AcceptanceHashIsStaleTests(_StaleHashFixtureMixin, unittest.TestCase):
    def _two_capability_project(self, tmp, *, phase_id="phase-1"):
        root = Path(tmp)
        _write_capability(root, "acme_widget_deleter", op_kind=_STALE_FIXTURE_OP_KIND)
        _write_capability(root, "acme_report_reader", op_kind=_STABLE_FIXTURE_OP_KIND)
        _write_descriptors(root, [
            {"id": "acme_widget_deleter", "accepted": True, "phase_id": phase_id},
            {"id": "acme_report_reader", "accepted": True, "phase_id": phase_id},
        ])
        return root

    def test_matching_hashes_are_not_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp)
            self._register_fixture_adapter(tmp, "a")
            accepted_hash = compute_implementation_hash(_STALE_FIXTURE_OP_KIND)
            self._write_acceptance_record(
                root, "acme_widget_deleter", "phase-1", accepted_hash, _STALE_FIXTURE_OP_KIND)

            self.assertFalse(
                lifecycle_state.acceptance_hash_is_stale(root, "acme_widget_deleter"))

    def test_code_change_via_registered_adapter_is_detected_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp)
            adapter_path = self._register_fixture_adapter(tmp, "a")
            accepted_hash = compute_implementation_hash(_STALE_FIXTURE_OP_KIND)
            self._write_acceptance_record(
                root, "acme_widget_deleter", "phase-1", accepted_hash, _STALE_FIXTURE_OP_KIND)
            stable_hash = compute_implementation_hash(_STABLE_FIXTURE_OP_KIND)
            self._write_acceptance_record(
                root, "acme_report_reader", "phase-1", stable_hash, _STABLE_FIXTURE_OP_KIND)

            self.assertFalse(
                lifecycle_state.acceptance_hash_is_stale(root, "acme_widget_deleter"))

            # Simulate a conformant rebuild: the capability's own write-affecting code (its
            # registered adapter module) changed bytes, while its capability-zone file never
            # touched anything the AST bypass scanner would flag -- it stays scanner-clean.
            with adapter_path.open("ab") as f:
                f.write(b"\n# rebuilt\n")

            self.assertTrue(
                lifecycle_state.acceptance_hash_is_stale(root, "acme_widget_deleter"))
            # The unrelated, untouched second capability is unaffected.
            self.assertFalse(
                lifecycle_state.acceptance_hash_is_stale(root, "acme_report_reader"))

    def test_not_accepted_is_never_stale_regardless_of_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_capability(root, "acme_widget_deleter", op_kind=_STALE_FIXTURE_OP_KIND)
            _write_capability(root, "acme_report_reader", op_kind=_STABLE_FIXTURE_OP_KIND)
            _write_descriptors(root, [
                {"id": "acme_widget_deleter", "accepted": False, "phase_id": "phase-1"},
                {"id": "acme_report_reader", "accepted": True, "phase_id": "phase-1"},
            ])
            # No acceptance record at all -- would fail-safe to "stale" IF accepted, but this
            # capability is not accepted, so nothing to be stale about.
            self.assertFalse(
                lifecycle_state.acceptance_hash_is_stale(root, "acme_widget_deleter"))

    def test_prefers_the_record_matching_the_current_accepted_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp, phase_id="phase-2")
            self._register_fixture_adapter(tmp, "a")
            current_hash = compute_implementation_hash(_STALE_FIXTURE_OP_KIND)
            # An OLDER record from a prior phase, deliberately carrying a WRONG hash -- must be
            # ignored in favor of the record matching the descriptor's CURRENT phase_id.
            self._write_acceptance_record(
                root, "acme_widget_deleter", "phase-1", "f" * 64, _STALE_FIXTURE_OP_KIND)
            self._write_acceptance_record(
                root, "acme_widget_deleter", "phase-2", current_hash, _STALE_FIXTURE_OP_KIND)

            self.assertFalse(
                lifecycle_state.acceptance_hash_is_stale(root, "acme_widget_deleter"))

    # -- Fail-safe direction: never silently keep accepted:true unverified ----------------

    def test_no_acceptance_record_at_all_fails_safe_to_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp)
            self._register_fixture_adapter(tmp, "a")
            # Deliberately no acceptance log written at all.
            self.assertTrue(
                lifecycle_state.acceptance_hash_is_stale(root, "acme_widget_deleter"))

    def test_unreadable_audit_log_fails_safe_to_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp)
            self._register_fixture_adapter(tmp, "a")
            log_path = root / lifecycle_state.ACCEPTANCE_LOG_REL
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("", encoding="utf-8")
            log_path.chmod(0o000)
            try:
                self.assertTrue(
                    lifecycle_state.acceptance_hash_is_stale(root, "acme_widget_deleter"))
            finally:
                log_path.chmod(0o644)  # restore so tempdir cleanup can remove it

    def test_record_missing_implementation_hash_fails_safe_to_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp)
            self._register_fixture_adapter(tmp, "a")
            log_path = root / lifecycle_state.ACCEPTANCE_LOG_REL
            log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "schema": ACCEPTANCE_RECORD_SCHEMA, "capability_id": "acme_widget_deleter",
                "phase_id": "phase-1", "op_kind": _STALE_FIXTURE_OP_KIND,
                # implementation_hash deliberately absent
            }
            log_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            self.assertTrue(
                lifecycle_state.acceptance_hash_is_stale(root, "acme_widget_deleter"))

    def test_unrecomputable_current_hash_fails_safe_to_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp)
            self._register_fixture_adapter(tmp, "a")
            # An op_kind with no registered contract at all -- compute_implementation_hash
            # raises ProofHashError.
            self._write_acceptance_record(
                root, "acme_widget_deleter", "phase-1", "a" * 64,
                "_no_such_op_kind_registered_anywhere")
            self.assertTrue(
                lifecycle_state.acceptance_hash_is_stale(root, "acme_widget_deleter"))


class RevokeStaleAcceptanceTests(_StaleHashFixtureMixin, unittest.TestCase):
    def _two_capability_project(self, tmp, *, phase_id="phase-1"):
        root = Path(tmp)
        _write_capability(root, "acme_widget_deleter", op_kind=_STALE_FIXTURE_OP_KIND)
        _write_capability(root, "acme_report_reader", op_kind=_STABLE_FIXTURE_OP_KIND)
        _write_descriptors(root, [
            {"id": "acme_widget_deleter", "accepted": True, "phase_id": phase_id},
            {"id": "acme_report_reader", "accepted": True, "phase_id": phase_id},
        ])
        return root

    def test_stale_capability_is_revoked_retrial_queued_and_reconciled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp)
            adapter_path = self._register_fixture_adapter(tmp, "a")
            accepted_hash = compute_implementation_hash(_STALE_FIXTURE_OP_KIND)
            self._write_acceptance_record(
                root, "acme_widget_deleter", "phase-1", accepted_hash, _STALE_FIXTURE_OP_KIND)
            stable_hash = compute_implementation_hash(_STABLE_FIXTURE_OP_KIND)
            self._write_acceptance_record(
                root, "acme_report_reader", "phase-1", stable_hash, _STABLE_FIXTURE_OP_KIND)

            with adapter_path.open("ab") as f:
                f.write(b"\n# rebuilt\n")

            result = lifecycle_state.revoke_stale_acceptance(root, "acme_widget_deleter")

            self.assertTrue(result.stale)
            self.assertTrue(result.revoked)
            self.assertEqual(result.note, lifecycle_state.STALE_ACCEPTANCE_NOTE)
            self.assertNotIn("Traceback", result.note)
            self.assertIn("changed", result.note)
            self.assertIn("approve", result.note)

            entries = {e["id"]: e for e in _read_json(root / lifecycle_state.DESCRIPTOR_SET_REL)}
            self.assertFalse(entries["acme_widget_deleter"]["accepted"])
            # The unrelated, untouched capability keeps its acceptance.
            self.assertTrue(entries["acme_report_reader"]["accepted"])

            queue = _read_json(root / lifecycle_state.MIGRATION_QUEUE_REL)
            self.assertEqual({e["mechanism_id"] for e in queue}, {"acme_widget_deleter"})

            # reconcile_state's own effect: coherent pause marker for the now-unaccepted
            # capability, keyed by canonical_id.
            marker_dir = root / lifecycle_state.PAUSED_MECHANISMS_DIR_REL
            self.assertTrue((marker_dir / "acme_widget_deleter.pause").is_file())
            state = _read_json(marker_dir / "acme_widget_deleter.json")
            self.assertEqual(state["canonical_id"], "acme_widget_deleter")
            self.assertFalse((marker_dir / "acme_report_reader.pause").exists())

            self.assertEqual(result.reconcile.canonical_id, "acme_widget_deleter")
            self.assertFalse(result.reconcile.accepted)
            self.assertTrue(result.reconcile.migration_open)

    def test_matching_hash_is_idempotent_and_leaves_clean_acceptance_undisturbed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp)
            self._register_fixture_adapter(tmp, "a")
            accepted_hash = compute_implementation_hash(_STALE_FIXTURE_OP_KIND)
            self._write_acceptance_record(
                root, "acme_widget_deleter", "phase-1", accepted_hash, _STALE_FIXTURE_OP_KIND)

            before = (root / lifecycle_state.DESCRIPTOR_SET_REL).read_bytes()
            result = lifecycle_state.revoke_stale_acceptance(root, "acme_widget_deleter")
            after = (root / lifecycle_state.DESCRIPTOR_SET_REL).read_bytes()

            self.assertFalse(result.stale)
            self.assertFalse(result.revoked)
            self.assertIsNone(result.note)
            self.assertEqual(before, after)
            # No migration was ever queued for a clean, matching-hash acceptance -- the
            # queue file is not even created.
            self.assertFalse((root / lifecycle_state.MIGRATION_QUEUE_REL).exists())

    def test_idempotent_rerun_after_revocation_does_not_re_flip_or_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp)
            adapter_path = self._register_fixture_adapter(tmp, "a")
            accepted_hash = compute_implementation_hash(_STALE_FIXTURE_OP_KIND)
            self._write_acceptance_record(
                root, "acme_widget_deleter", "phase-1", accepted_hash, _STALE_FIXTURE_OP_KIND)
            with adapter_path.open("ab") as f:
                f.write(b"\n# rebuilt\n")

            first = lifecycle_state.revoke_stale_acceptance(root, "acme_widget_deleter")
            self.assertTrue(first.revoked)
            descriptors_1 = (root / lifecycle_state.DESCRIPTOR_SET_REL).read_bytes()
            queue_1 = (root / lifecycle_state.MIGRATION_QUEUE_REL).read_bytes()

            second = lifecycle_state.revoke_stale_acceptance(root, "acme_widget_deleter")
            self.assertFalse(second.stale)
            self.assertFalse(second.revoked)
            self.assertIsNone(second.note)
            descriptors_2 = (root / lifecycle_state.DESCRIPTOR_SET_REL).read_bytes()
            queue_2 = (root / lifecycle_state.MIGRATION_QUEUE_REL).read_bytes()
            self.assertEqual(descriptors_1, descriptors_2)
            self.assertEqual(queue_1, queue_2)

    def test_fail_safe_revocation_has_no_traceback_and_is_plain_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._two_capability_project(tmp)
            self._register_fixture_adapter(tmp, "a")
            # No acceptance record at all -- fail-safe stale, per acceptance_hash_is_stale's own
            # tests above.
            result = lifecycle_state.revoke_stale_acceptance(root, "acme_widget_deleter")
            self.assertTrue(result.revoked)
            self.assertNotIn("Traceback", result.note)
            self.assertNotIn("Error", result.note)
            entries = {e["id"]: e for e in _read_json(root / lifecycle_state.DESCRIPTOR_SET_REL)}
            self.assertFalse(entries["acme_widget_deleter"]["accepted"])


if __name__ == "__main__":
    unittest.main()
