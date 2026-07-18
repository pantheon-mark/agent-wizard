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

import hashlib
import importlib.util
import json
import os
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
from external_write import acceptance_ceremony  # noqa: E402
from external_write.capability_identity import IdentityResolutionError  # noqa: E402
from external_write.acceptance_ceremony import ACCEPTANCE_RECORD_SCHEMA  # noqa: E402
from external_write.proof_hash import compute_implementation_hash  # noqa: E402
import external_write.contracts as _contracts  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.adapter_registry import register_adapter, unregister_adapter  # noqa: E402
from external_write.operations import Operation  # noqa: E402
from external_write import write_gate  # noqa: E402

# Reuse test_external_write_acceptance_ceremony.py's own fixture builders (same directory) for
# the REAL, full-ceremony flow this file's CapabilityModuleHashCoverageTests needs -- DRY, never
# a second parallel copy of _proof/_receipt/_descriptor's shapes.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_external_write_acceptance_ceremony as _ace_fixtures  # noqa: E402

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


def _hash_capability_module(root, cap_id):
    """sha256 hex digest of ``agents/capabilities/<cap_id>_capability.py``'s CURRENT bytes --
    matches acceptance_ceremony's own ``_compute_capability_module_hash`` algorithm exactly
    (never reinvented)."""
    path = Path(root) / "agents" / "capabilities" / f"{cap_id}_capability.py"
    return hashlib.sha256(path.read_bytes()).hexdigest()


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

    def _two_capability_project(self, tmp, *, phase_id="phase-1"):
        """(Task B2b-fix, Minor) Moved here from being duplicated verbatim across
        AcceptanceHashIsStaleTests and RevokeStaleAcceptanceTests -- one shared fixture."""
        root = Path(tmp)
        _write_capability(root, "acme_widget_deleter", op_kind=_STALE_FIXTURE_OP_KIND)
        _write_capability(root, "acme_report_reader", op_kind=_STABLE_FIXTURE_OP_KIND)
        _write_descriptors(root, [
            {"id": "acme_widget_deleter", "accepted": True, "phase_id": phase_id},
            {"id": "acme_report_reader", "accepted": True, "phase_id": phase_id},
        ])
        return root

    def _register_fixture_adapter(self, adapter_dir, suffix, op_kind=_STALE_FIXTURE_OP_KIND):
        adapter_path = Path(adapter_dir) / f"fixture_adapter_{suffix}.py"
        shutil.copy2(_FIXTURE_ADAPTER_SRC, adapter_path)
        module_name = f"{_STALE_FIXTURE_MODULE_PREFIX}_{suffix}"
        module = _load_adapter_module(adapter_path, module_name)
        self._loaded_modules.append(module_name)
        register_adapter(op_kind, module.FixtureAdapter())
        return adapter_path

    def _write_acceptance_record(self, root, cap_id, phase_id, implementation_hash, op_kind,
                                 audit_log_rel=None, capability_module_hash="__auto__"):
        """``capability_module_hash="__auto__"`` (the default) hashes the capability's OWN
        module file AS IT EXISTS RIGHT NOW at ``agents/capabilities/<cap_id>_capability.py`` --
        the realistic default (production hashes whatever the file looks like at grant time).
        Pass ``None`` explicitly to simulate a pre-B2b-fix / legacy record that never recorded
        this field at all."""
        log_path = Path(root) / (audit_log_rel or lifecycle_state.ACCEPTANCE_LOG_REL)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if capability_module_hash == "__auto__":
            capability_module_hash = _hash_capability_module(root, cap_id)
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
            "capability_module_hash": capability_module_hash,
            "operator_confirmation": "Yes, accept this capability for live use.",
            "receipt_accepted_at": "2026-01-01T00:00:00Z",
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return record


class AcceptanceHashIsStaleTests(_StaleHashFixtureMixin, unittest.TestCase):
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

    @unittest.skipIf(
        hasattr(os, "getuid") and os.getuid() == 0,
        "running as root ignores file permission bits -- chmod(0o000) would not reproduce "
        "an unreadable file")
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


# ===================================================================================
# Task B2b-fix, Critical 1: capability-module coverage. implementation_hash covers ONLY the
# contract's declared dependency_set + the op_kind's registered ADAPTER module -- it
# structurally never covers agents/capabilities/<canonical_id>_capability.py, the capability's
# OWN propose_operations/plan logic. Reproduces the reviewer's exact scenario end-to-end
# through the REAL acceptance_ceremony flow (not a hand-written record).
# ===================================================================================

_PROPOSE_OPERATIONS_MODULE_TEMPLATE = '''"""{cap_id} capability module (Task B2b-fix RED-test
fixture): routes writes through the sanctioned run-envelope entrypoint. Scans clean under the
AST bypass scanner."""
from agents.lib.external_write.operations import Operation
from agents.lib.external_write.capability_api import run_enveloped_operation

OP_KIND = "delete_record"


def propose_operations(candidates):
    # Guard: only ever propose a delete for records older than {threshold} days.
    return [c for c in candidates if c.get("age_days", 0) > {threshold}]


def go(envelope, task_id, client, receipt):
    op = Operation(
        kind="delete_record",
        object_id=task_id,
        field="__record__",
        new_value=None,
    )
    return run_enveloped_operation(envelope, op, receipt, client)
'''


class CapabilityModuleHashCoverageTests(unittest.TestCase):
    """implementation_hash alone cannot see a capability-zone-only rewrite. Accept a real
    delete_record-backed capability (no adapter registered for delete_record -- its
    implementation_hash is pinned only to the shared, static, never-mutated dependency_set),
    then edit ONLY the capability module's propose_operations guard (">30 days" -> ">7 days"),
    leaving the adapter/call shape (run_enveloped_operation) completely intact. BEFORE this
    fix: acceptance_hash_is_stale reports False (implementation_hash never moved). AFTER: it
    must report True (the new capability_module_hash signal catches it)."""

    CAP_ID = "acme_widget_deleter"
    PHASE_ID = _ace_fixtures.PHASE

    def _write_capability_module(self, path, threshold):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _PROPOSE_OPERATIONS_MODULE_TEMPLATE.format(cap_id=self.CAP_ID, threshold=threshold),
            encoding="utf-8")

    def _accept_real_capability(self, root):
        """Runs the REAL, full acceptance_ceremony flow (never a hand-written record) -- a
        genuine reproduction of what a real accepted capability's audit record looks like."""
        cap_module_path = root / "agents" / "capabilities" / f"{self.CAP_ID}_capability.py"
        self._write_capability_module(cap_module_path, threshold=30)

        secdir = root / "security"
        secdir.mkdir(parents=True, exist_ok=True)
        descriptor_path = secdir / "capability_descriptors.json"
        descriptor_path.write_text(
            json.dumps([_ace_fixtures._descriptor(
                id=self.CAP_ID, risk_class="irreversible_external", phase_id=self.PHASE_ID,
                blast_radius_cap=5, accepted=False, declared_test_target="copy")]),
            encoding="utf-8")

        proof_path = root / "proof.json"
        proof = _ace_fixtures._proof(
            op_kind="delete_record", capability_id=self.CAP_ID,
            module_paths=[str(cap_module_path)])
        proof_path.write_text(json.dumps(proof), encoding="utf-8")

        receipt_path = root / "receipt.json"
        receipt = _ace_fixtures._receipt(
            self.CAP_ID, phase_id=self.PHASE_ID, copy_run_proof_ref=str(proof_path))
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

        audit_path = secdir / "capability_acceptance_log.jsonl"

        result = acceptance_ceremony.accept_capability_for_live_use(
            self.CAP_ID, self.PHASE_ID, str(proof_path), str(receipt_path),
            descriptor_set_path=str(descriptor_path), audit_log_path=str(audit_path),
            capability_module_path=str(cap_module_path))
        self.assertTrue(result.accepted, result.reason)
        return cap_module_path

    def test_capability_module_edit_alone_is_detected_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_module_path = self._accept_real_capability(root)

            # Clean/matching baseline first (nothing edited yet).
            self.assertFalse(lifecycle_state.acceptance_hash_is_stale(root, self.CAP_ID))

            # The reviewer's exact rebuild: edit ONLY the propose_operations guard, leaving
            # the adapter/call shape (run_enveloped_operation) completely intact.
            self._write_capability_module(cap_module_path, threshold=7)

            self.assertTrue(
                lifecycle_state.acceptance_hash_is_stale(root, self.CAP_ID),
                "a capability-zone-only rebuild (its OWN propose_operations code, never its "
                "adapter or the shared dependency_set) must be detected as stale")

    def test_revocation_end_to_end_for_a_capability_module_only_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_module_path = self._accept_real_capability(root)
            self._write_capability_module(cap_module_path, threshold=7)

            result = lifecycle_state.revoke_stale_acceptance(root, self.CAP_ID)
            self.assertTrue(result.revoked)
            entries = {e["id"]: e for e in _read_json(root / lifecycle_state.DESCRIPTOR_SET_REL)}
            self.assertFalse(entries[self.CAP_ID]["accepted"])

    def test_old_record_with_no_capability_module_hash_fails_safe_to_stale(self):
        # A legacy/pre-fix acceptance record recorded no capability_module_hash at all.
        # Fail-safe: treated as stale even though implementation_hash still matches.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_module_path = root / "agents" / "capabilities" / f"{self.CAP_ID}_capability.py"
            self._write_capability_module(cap_module_path, threshold=30)
            _write_descriptors(root, [
                {"id": self.CAP_ID, "accepted": True, "phase_id": self.PHASE_ID}])
            log_path = root / lifecycle_state.ACCEPTANCE_LOG_REL
            log_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_record = {
                "schema": ACCEPTANCE_RECORD_SCHEMA, "capability_id": self.CAP_ID,
                "phase_id": self.PHASE_ID, "op_kind": "delete_record",
                "implementation_hash": compute_implementation_hash("delete_record"),
                # no capability_module_hash key at all -- pre-fix shape
            }
            log_path.write_text(json.dumps(legacy_record) + "\n", encoding="utf-8")

            self.assertTrue(lifecycle_state.acceptance_hash_is_stale(root, self.CAP_ID))


class CompleteMigrationTests(unittest.TestCase):
    """Tests for the Task B3 sanctioned resume/complete-migration tool
    (``lifecycle_state.complete_migration``) -- the F-63 fix that replaces the operator/agent
    hand-``rm`` of a pause marker with ONE call that flips ``accepted`` (through the ceremony,
    never a direct write) and then reconciles the pause marker + migration queue.

    Real-emit-path fixtures throughout: the capability module, descriptor set, migration queue,
    and pause marker are all written/derived at their genuine relative paths inside a fresh
    tempdir (the marker itself is MATERIALIZED via a real ``reconcile_state`` call, never
    hand-authored), reusing ``test_external_write_acceptance_ceremony.py``'s own proof/receipt
    builders (DRY, same convention ``CapabilityModuleHashCoverageTests`` above already
    established). At least two distinct capability_ids are exercised across this class.
    """

    PHASE_ID = _ace_fixtures.PHASE

    def _write_capability_module(self, path, cap_id, threshold=30):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _PROPOSE_OPERATIONS_MODULE_TEMPLATE.format(cap_id=cap_id, threshold=threshold),
            encoding="utf-8")

    def _merge_descriptor(self, root, entry):
        path = root / "security" / "capability_descriptors.json"
        existing = _read_json(path) if path.exists() else []
        existing.append(entry)
        _write_descriptors(root, existing)

    def _merge_migration(self, root, entry):
        path = root / "agents" / "handoffs" / "pending_migrations.json"
        existing = _read_json(path) if path.exists() else []
        existing.append(entry)
        _write_pending_migrations(root, existing)

    def _prepare_paused_capability(self, root, cap_id, blast_radius_cap=5):
        """A gated, declared-but-unaccepted capability with a migration queued, whose pause
        marker is MATERIALIZED via a real ``reconcile_state`` call (never hand-written) --
        exactly the state the F-55 B2 auto-pause / a prior ``reconcile_state`` call would leave
        behind for a capability awaiting migration."""
        cap_module_path = root / "agents" / "capabilities" / f"{cap_id}_capability.py"
        self._write_capability_module(cap_module_path, cap_id)
        self._merge_descriptor(root, _ace_fixtures._descriptor(
            id=cap_id, risk_class="irreversible_external", phase_id=self.PHASE_ID,
            blast_radius_cap=blast_radius_cap, accepted=False, declared_test_target="copy"))
        self._merge_migration(root, {"mechanism_id": cap_id, "status": "pending"})

        result = lifecycle_state.reconcile_state(str(root), cap_id)
        self.assertTrue(result.marker_present, "fixture setup must actually pause the capability")
        return cap_module_path

    def _prepare_unrelated_capability(self, root, cap_id):
        """A second, uninvolved capability: declared + paused + migration-queued the same way,
        but with NO op_kind and never run through ``complete_migration`` -- present solely to
        prove this task's writes never touch an unrelated capability's own state. (No op_kind
        also means its marker's ``paused_op_kinds`` is empty, so it can never pollute the
        write_gate global paused-op_kind union another test in this class checks.)"""
        _write_capability(root, cap_id)
        self._merge_descriptor(root, {"id": cap_id, "accepted": False})
        self._merge_migration(root, {"mechanism_id": cap_id, "status": "pending"})
        lifecycle_state.reconcile_state(str(root), cap_id)

    def _write_proof_and_receipt(self, root, cap_id, module_path, *, copy_run_proof_ref=None):
        proof_path = root / f"proof_{cap_id}.json"
        proof = _ace_fixtures._proof(
            op_kind="delete_record", capability_id=cap_id, module_paths=[str(module_path)])
        proof_path.write_text(json.dumps(proof), encoding="utf-8")

        receipt_path = root / f"receipt_{cap_id}.json"
        receipt = _ace_fixtures._receipt(
            cap_id, phase_id=self.PHASE_ID,
            copy_run_proof_ref=(copy_run_proof_ref if copy_run_proof_ref is not None
                                else str(proof_path)))
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        return proof_path, receipt_path

    def _marker_paths(self, root, cap_id):
        marker_dir = Path(root) / lifecycle_state.PAUSED_MECHANISMS_DIR_REL
        return marker_dir / f"{cap_id}.pause", marker_dir / f"{cap_id}.json"

    def _write_gate_permits_live(self, root, cap_id):
        """True iff ``evaluate_write_gate`` would PERMIT a live delete_record write for ``cap_id``
        right now -- exercises the REAL runtime gate (not just a JSON-field inspection) to prove
        a marker-clear actually re-authorizes the write path, and a marker-present state actually
        denies it."""
        descriptor_set = _read_json(Path(root) / lifecycle_state.DESCRIPTOR_SET_REL)
        op = Operation(surface=cap_id, op_kind="delete_record", batch_id="b1",
                       object_id="row-1", field="__record__", new_value=None)
        decision = write_gate.evaluate_write_gate(
            op, target="live", descriptor_set=descriptor_set,
            cap_ledger=write_gate.InvocationLedger(),
            paused_root=str(Path(root) / lifecycle_state.PAUSED_MECHANISMS_DIR_REL))
        return decision.permitted

    # -- (a) happy path ------------------------------------------------------------------------

    def test_happy_path_completes_and_reauthorizes_the_write_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_id = "acme_widget_deleter"
            other_id = "acme_report_reader"  # second, unrelated capability_id
            module_path = self._prepare_paused_capability(root, cap_id)
            self._prepare_unrelated_capability(root, other_id)
            proof_path, receipt_path = self._write_proof_and_receipt(root, cap_id, module_path)

            self.assertFalse(self._write_gate_permits_live(root, cap_id))

            result = lifecycle_state.complete_migration(
                str(root), cap_id, str(proof_path), str(receipt_path),
                capability_module_path=str(module_path))

            self.assertTrue(result.completed, result.reason)
            self.assertTrue(result.accepted)
            self.assertIsNone(result.reason)
            self.assertEqual(result.canonical_id, cap_id)
            self.assertTrue(result.acceptance.accepted)
            self.assertFalse(result.reconcile.marker_present)
            self.assertFalse(result.reconcile.migration_open)

            descriptors = {e["id"]: e
                          for e in _read_json(Path(root) / lifecycle_state.DESCRIPTOR_SET_REL)}
            self.assertTrue(descriptors[cap_id]["accepted"])
            self.assertFalse(descriptors[other_id]["accepted"])  # unrelated: untouched

            pause_path, state_path = self._marker_paths(root, cap_id)
            self.assertFalse(pause_path.exists())
            self.assertFalse(state_path.exists())
            other_pause, other_state = self._marker_paths(root, other_id)
            self.assertTrue(other_pause.exists())  # unrelated capability's marker: untouched
            self.assertTrue(other_state.exists())

            queue = _read_json(Path(root) / lifecycle_state.MIGRATION_QUEUE_REL)
            self.assertFalse(any(e["mechanism_id"] == cap_id for e in queue))
            self.assertTrue(any(e["mechanism_id"] == other_id for e in queue))

            audit_path = Path(root) / lifecycle_state.ACCEPTANCE_LOG_REL
            log_lines = [ln for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln]
            self.assertEqual(len(log_lines), 1)
            self.assertEqual(json.loads(log_lines[0])["capability_id"], cap_id)

            self.assertTrue(self._write_gate_permits_live(root, cap_id))

    def test_capability_module_path_defaults_to_project_root_not_cwd(self):
        """(coordinator review fix) `capability_module_path`'s own CWD-relative default is
        mirrored from `acceptance_ceremony.accept_capability_for_live_use` -- exactly like
        `descriptor_set_path` / `audit_log_path`, which `complete_migration` already resolves
        against `root` when omitted. Before this fix, `capability_module_path` was passed through
        unresolved: a caller whose process cwd differs from `project_root` (the normal case
        throughout this whole test suite) would silently record `capability_module_hash: null` --
        and `acceptance_hash_is_stale` treats a null value as ALWAYS stale (fail-safe there), so a
        capability just resumed through `complete_migration` would be immediately, wrongly,
        B2b-stale-flagged with no code changed at all. This test drives `complete_migration` from
        a process cwd that is a DIFFERENT directory than `project_root`, omitting
        `capability_module_path`, and asserts the acceptance record's `capability_module_hash` is
        the REAL sha256 of `<root>/agents/capabilities/<cap_id>_capability.py` (never null), and
        that `acceptance_hash_is_stale` reports False right after."""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other_cwd:
            root = Path(tmp)
            cap_id = "acme_widget_deleter"
            module_path = self._prepare_paused_capability(root, cap_id)
            proof_path, receipt_path = self._write_proof_and_receipt(root, cap_id, module_path)

            prior_cwd = os.getcwd()
            os.chdir(other_cwd)
            try:
                result = lifecycle_state.complete_migration(
                    str(root), cap_id, str(proof_path), str(receipt_path))
            finally:
                os.chdir(prior_cwd)

            self.assertTrue(result.completed, result.reason)

            audit_path = root / lifecycle_state.ACCEPTANCE_LOG_REL
            log_lines = [ln for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln]
            record = json.loads(log_lines[-1])
            self.assertEqual(
                record.get("capability_module_hash"), _hash_capability_module(root, cap_id))

            self.assertFalse(lifecycle_state.acceptance_hash_is_stale(str(root), cap_id))

    # -- (b) crash-safety: a refused attempt leaves no partial state; a corrected retry
    # completes fully with no duplicate audit record. -------------------------------------------

    def test_refused_attempt_leaves_no_partial_state_and_retry_completes_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_id = "acme_widget_deleter"
            module_path = self._prepare_paused_capability(root, cap_id)
            proof_path, _ = self._write_proof_and_receipt(root, cap_id, module_path)

            # A receipt bound to the WRONG proof ref -- the ceremony's own Invariant 5 refuses
            # this (receipt copy_run_proof_ref must match the proof supplied). Models a bad/
            # mismatched input arriving at complete_migration, never a hand-rolled duplicate check.
            bad_receipt_path = root / "receipt_bad.json"
            bad_receipt_path.write_text(json.dumps(_ace_fixtures._receipt(
                cap_id, phase_id=self.PHASE_ID, copy_run_proof_ref="some/other/proof.json",
            )), encoding="utf-8")

            first = lifecycle_state.complete_migration(
                str(root), cap_id, str(proof_path), str(bad_receipt_path),
                capability_module_path=str(module_path))

            self.assertFalse(first.completed)
            self.assertFalse(first.accepted)
            self.assertIsNotNone(first.reason)
            self.assertIsNotNone(first.acceptance)
            self.assertFalse(first.acceptance.accepted)

            # No partial state: still paused, still queued, still unaccepted, no audit record.
            descriptors = {e["id"]: e
                          for e in _read_json(Path(root) / lifecycle_state.DESCRIPTOR_SET_REL)}
            self.assertFalse(descriptors[cap_id]["accepted"])
            pause_path, state_path = self._marker_paths(root, cap_id)
            self.assertTrue(pause_path.exists())
            self.assertTrue(state_path.exists())
            queue = _read_json(Path(root) / lifecycle_state.MIGRATION_QUEUE_REL)
            self.assertTrue(any(e["mechanism_id"] == cap_id for e in queue))
            audit_path = Path(root) / lifecycle_state.ACCEPTANCE_LOG_REL
            self.assertFalse(audit_path.exists())

            # Retry with the CORRECT receipt -- converges fully, from the same paused start state.
            _, good_receipt_path = self._write_proof_and_receipt(root, cap_id, module_path)
            second = lifecycle_state.complete_migration(
                str(root), cap_id, str(proof_path), str(good_receipt_path),
                capability_module_path=str(module_path))
            self.assertTrue(second.completed, second.reason)

            log_lines = [ln for ln in audit_path.read_text(encoding="utf-8").splitlines() if ln]
            self.assertEqual(len(log_lines), 1, "the earlier refusal must not have left a record")
            self.assertTrue(self._write_gate_permits_live(root, cap_id))

    def test_crash_between_acceptance_and_marker_clear_converges_on_rerun(self):
        """Simulates a crash exactly between this function's own step 2 (the ceremony flips
        `accepted` + appends the audit record) and step 3 (reconcile_state clears the marker) by
        driving the ceremony DIRECTLY -- bypassing complete_migration -- to reach precisely that
        state, then proves a re-run of complete_migration (idempotent: the ceremony's own
        already-accepted branch fires, no duplicate audit line) converges cleanly, and that a
        bare reconcile_state call converges just as well (the module's own disclosed alternate
        recovery path)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_id = "acme_widget_deleter"
            module_path = self._prepare_paused_capability(root, cap_id)
            proof_path, receipt_path = self._write_proof_and_receipt(root, cap_id, module_path)

            descriptor_set_path = root / lifecycle_state.DESCRIPTOR_SET_REL
            audit_log_path = root / lifecycle_state.ACCEPTANCE_LOG_REL
            crash_result = acceptance_ceremony.accept_capability_for_live_use(
                cap_id, self.PHASE_ID, str(proof_path), str(receipt_path),
                descriptor_set_path=str(descriptor_set_path), audit_log_path=str(audit_log_path),
                capability_module_path=str(module_path))
            self.assertTrue(crash_result.accepted, crash_result.reason)

            # Post-crash state: accepted, but the marker is STILL present -- write_gate must
            # still deny (fail-safe OFF), never a half-open capability.
            descriptors = {e["id"]: e
                          for e in _read_json(Path(root) / lifecycle_state.DESCRIPTOR_SET_REL)}
            self.assertTrue(descriptors[cap_id]["accepted"])
            pause_path, state_path = self._marker_paths(root, cap_id)
            self.assertTrue(pause_path.exists())
            self.assertTrue(state_path.exists())
            self.assertFalse(self._write_gate_permits_live(root, cap_id))
            log_lines_before = [
                ln for ln in audit_log_path.read_text(encoding="utf-8").splitlines() if ln]
            self.assertEqual(len(log_lines_before), 1)

            # Re-run complete_migration with the SAME (still-valid) proof/receipt -- the
            # ceremony's own idempotent already-accepted branch means no duplicate write/audit,
            # and reconcile_state clears the residual marker + closes the migration.
            resumed = lifecycle_state.complete_migration(
                str(root), cap_id, str(proof_path), str(receipt_path),
                capability_module_path=str(module_path))
            self.assertTrue(resumed.completed, resumed.reason)
            self.assertFalse(pause_path.exists())
            self.assertFalse(state_path.exists())
            log_lines_after = [
                ln for ln in audit_log_path.read_text(encoding="utf-8").splitlines() if ln]
            self.assertEqual(len(log_lines_after), 1, "idempotent re-run must not duplicate")
            self.assertTrue(self._write_gate_permits_live(root, cap_id))

    def test_bare_reconcile_state_is_also_a_valid_recovery_path_after_the_crash_point(self):
        """The module's own docstring discloses a SECOND recovery path: once `accepted` already
        holds (post-crash), a bare `reconcile_state` call -- not necessarily `complete_migration`
        again -- converges the views just as well. Proven independently of the test above."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_id = "acme_widget_deleter"
            module_path = self._prepare_paused_capability(root, cap_id)
            proof_path, receipt_path = self._write_proof_and_receipt(root, cap_id, module_path)
            descriptor_set_path = root / lifecycle_state.DESCRIPTOR_SET_REL
            audit_log_path = root / lifecycle_state.ACCEPTANCE_LOG_REL
            acceptance_ceremony.accept_capability_for_live_use(
                cap_id, self.PHASE_ID, str(proof_path), str(receipt_path),
                descriptor_set_path=str(descriptor_set_path), audit_log_path=str(audit_log_path),
                capability_module_path=str(module_path))

            pause_path, state_path = self._marker_paths(root, cap_id)
            self.assertTrue(pause_path.exists())

            reconcile = lifecycle_state.reconcile_state(str(root), cap_id)
            self.assertFalse(reconcile.marker_present)
            self.assertFalse(pause_path.exists())
            self.assertFalse(state_path.exists())
            self.assertTrue(self._write_gate_permits_live(root, cap_id))

    # -- (c) evidence-bound marker clearing --------------------------------------------------

    def test_marker_with_mismatched_canonical_id_is_not_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_x = "acme_widget_deleter"
            cap_y = "acme_second_deleter"  # second, distinct capability_id
            module_x = self._prepare_paused_capability(root, cap_x)
            module_y = self._prepare_paused_capability(root, cap_y)

            # Corrupt cap_y's marker: stamp it with a DIFFERENT capability's canonical_id --
            # simulates a mis-attributed/corrupted marker file, the exact case the A4-fold check
            # exists to catch.
            _, state_path_y = self._marker_paths(root, cap_y)
            state = json.loads(state_path_y.read_text(encoding="utf-8"))
            state["canonical_id"] = cap_x
            state["mechanism_id"] = cap_x
            state_path_y.write_text(json.dumps(state, indent=2), encoding="utf-8")

            proof_x, receipt_x = self._write_proof_and_receipt(root, cap_x, module_x)
            proof_y, receipt_y = self._write_proof_and_receipt(root, cap_y, module_y)

            # The correctly-stamped capability completes fully.
            result_x = lifecycle_state.complete_migration(
                str(root), cap_x, str(proof_x), str(receipt_x),
                capability_module_path=str(module_x))
            self.assertTrue(result_x.completed, result_x.reason)
            pause_x, state_x = self._marker_paths(root, cap_x)
            self.assertFalse(pause_x.exists())
            self.assertFalse(state_x.exists())

            # The mismatched-marker capability: accepted, but its marker is deliberately left in
            # place -- fail-closed, never a blind clear.
            result_y = lifecycle_state.complete_migration(
                str(root), cap_y, str(proof_y), str(receipt_y),
                capability_module_path=str(module_y))
            self.assertFalse(result_y.completed)
            self.assertTrue(result_y.accepted)
            self.assertIsNotNone(result_y.reason)
            self.assertIn(cap_x, result_y.reason)
            pause_y, state_y = self._marker_paths(root, cap_y)
            self.assertTrue(pause_y.exists())
            self.assertTrue(state_y.exists())
            descriptors = {e["id"]: e
                          for e in _read_json(Path(root) / lifecycle_state.DESCRIPTOR_SET_REL)}
            self.assertTrue(descriptors[cap_y]["accepted"])
            # write_gate still denies cap_y live -- accepted:true alone never re-authorizes it
            # while its marker is still present.
            self.assertFalse(self._write_gate_permits_live(root, cap_y))

    def test_marker_with_mismatched_op_kind_is_not_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_id = "acme_widget_deleter"
            module_path = self._prepare_paused_capability(root, cap_id)

            # Corrupt the marker's own paused_op_kinds to a DIFFERENT operation than the one
            # actually being accepted (the proof's real op_kind is "delete_record").
            _, state_path = self._marker_paths(root, cap_id)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["paused_op_kinds"] = ["some.other.op_kind"]
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

            proof_path, receipt_path = self._write_proof_and_receipt(root, cap_id, module_path)
            result = lifecycle_state.complete_migration(
                str(root), cap_id, str(proof_path), str(receipt_path),
                capability_module_path=str(module_path))

            self.assertFalse(result.completed)
            self.assertTrue(result.accepted)
            self.assertIsNotNone(result.reason)
            pause_path, state_path = self._marker_paths(root, cap_id)
            self.assertTrue(pause_path.exists())
            self.assertTrue(state_path.exists())

    def test_marker_state_file_present_but_unreadable_is_not_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_id = "acme_widget_deleter"
            module_path = self._prepare_paused_capability(root, cap_id)

            _, state_path = self._marker_paths(root, cap_id)
            state_path.write_text("{not valid json", encoding="utf-8")

            proof_path, receipt_path = self._write_proof_and_receipt(root, cap_id, module_path)
            result = lifecycle_state.complete_migration(
                str(root), cap_id, str(proof_path), str(receipt_path),
                capability_module_path=str(module_path))

            self.assertFalse(result.completed)
            self.assertTrue(result.accepted)
            self.assertIsNotNone(result.reason)
            pause_path, state_path = self._marker_paths(root, cap_id)
            self.assertTrue(pause_path.exists())
            self.assertTrue(state_path.exists())

    # -- identity / routing refusals ----------------------------------------------------------

    def test_unresolvable_canonical_id_raises_identity_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(IdentityResolutionError):
                lifecycle_state.complete_migration(
                    str(root), "no_such_capability", "proof.json", "receipt.json")

    def test_receipt_naming_a_different_capability_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cap_x = "acme_widget_deleter"
            cap_y = "acme_second_deleter"
            module_x = self._prepare_paused_capability(root, cap_x)
            self._prepare_paused_capability(root, cap_y)
            proof_x, _ = self._write_proof_and_receipt(root, cap_x, module_x)
            # A receipt that legitimately names cap_y, not cap_x.
            receipt_for_y_path = root / "receipt_for_y.json"
            receipt_for_y_path.write_text(json.dumps(_ace_fixtures._receipt(
                cap_y, phase_id=self.PHASE_ID, copy_run_proof_ref=str(proof_x),
            )), encoding="utf-8")

            result = lifecycle_state.complete_migration(
                str(root), cap_x, str(proof_x), str(receipt_for_y_path),
                capability_module_path=str(module_x))

            self.assertFalse(result.completed)
            self.assertFalse(result.accepted)
            self.assertIsNone(result.acceptance)  # refused before ever reaching the ceremony
            descriptors = {e["id"]: e
                          for e in _read_json(Path(root) / lifecycle_state.DESCRIPTOR_SET_REL)}
            self.assertFalse(descriptors[cap_x]["accepted"])


if __name__ == "__main__":
    unittest.main()
