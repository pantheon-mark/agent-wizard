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

import json
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
            migrations_1 = Path(root, lifecycle_state.MIGRATION_QUEUE_REL).read_bytes()

            second = lifecycle_state.reconcile_state(root, "acme_widget_deleter")
            self.assertFalse(second.changed)
            self.assertEqual(second.marker_present, first.marker_present)
            self.assertEqual(second.migration_open, first.migration_open)

            marker_snapshot_2 = _marker_dir_snapshot(root)
            migrations_2 = Path(root, lifecycle_state.MIGRATION_QUEUE_REL).read_bytes()
            self.assertEqual(marker_snapshot_1, marker_snapshot_2)
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


if __name__ == "__main__":
    unittest.main()
