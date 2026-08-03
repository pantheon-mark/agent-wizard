"""Anti-drift: every declared migration is reachable from the real upgrade entry
point, and every remediation mechanism has a test that proves its branch runs.

The failure this prevents
-------------------------
A migration was written, was correct, and nothing called it. Every unit test of
the migration passed. The defect was not in the migration -- it was in the
absence of any assertion that a real flow reaches it. So these tests bind to
``reconcile_upgrade``, the entry point every upgrade path and the standalone
reconcile command funnel through. Binding to the sub-function that iterates the
set would pass even if the entry point stopped calling it, which is exactly the
bug.

The general rule this file enforces, for any remediation added later: the
PRODUCER creates the bad shape, the REAL path runs, and the CONSUMER proves the
branch executed. A mechanism whose consuming branch has never once executed is
indistinguishable from a mechanism that does not exist.

Run:  python3 -m unittest discover -s wizard/scripts/lib \\
          -p test_migration_set_antidrift.py
"""

import ast
import inspect
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_WIZARD = Path(__file__).resolve().parents[2]
_SCRIPTS_LIB = _WIZARD / "scripts" / "lib"
_AGENTS_LIB = _WIZARD / "agents" / "lib"
for _p in (str(_SCRIPTS_LIB), str(_AGENTS_LIB)):
    if _p not in sys.path:
        sys.path.insert(0, str(_p))

import upgrade_reconcile  # noqa: E402
from adapter_migrations import ADAPTER_MIGRATIONS  # noqa: E402


class MigrationSetIsReachableFromTheRealEntryPoint(unittest.TestCase):

    def test_reconcile_upgrade_calls_the_migration_pass(self):
        """Static binding at the ENTRY POINT. Not at the sub-function: that would
        pass even if the entry point stopped calling it."""
        source = inspect.getsource(upgrade_reconcile.reconcile_upgrade)
        self.assertIn("reconcile_adapter_migrations", source,
                      "the upgrade entry point must invoke the migration pass")

    def test_reconcile_upgrade_calls_the_post_condition(self):
        source = inspect.getsource(upgrade_reconcile.reconcile_upgrade)
        self.assertIn("check_read_provisioner_conformance", source)
        self.assertIn("record_read_provisioner_conformance", source,
                      "the post-condition's verdict must be recorded durably, "
                      "not merely computed")

    def test_reconcile_upgrade_calls_the_undo_declaration_post_condition(self):
        """Cut 1.9's clause-(c) post-condition. Bound at the ENTRY POINT for the
        same reason as the one above: a check the entry point stopped calling is
        indistinguishable from a check that does not exist."""
        source = inspect.getsource(upgrade_reconcile.reconcile_upgrade)
        self.assertIn("check_undo_declaration_conformance", source)
        self.assertIn("record_undo_declaration_conformance", source,
                      "the post-condition's verdict must be recorded durably, "
                      "not merely computed")

    def test_the_upgrade_cli_calls_the_engine_entry_point(self):
        """One funnel. Every CLI path goes through this helper, so binding here
        covers apply, re-apply, and the standalone reconcile command."""
        cli = (_WIZARD / "scripts" / "wizard_upgrade.py").read_text(encoding="utf-8")
        tree = ast.parse(cli)
        called = {
            n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        self.assertIn("reconcile_upgrade", called)
        self.assertIn("record_reconcile_incomplete", called,
                      "a reconcile failure must leave durable state")

    def test_every_declared_migration_is_exercised_by_the_pass(self):
        """Not just declared -- actually applied. Runs the REAL pass against a
        module that needs every migration and asserts each one reported an
        outcome. A member nothing applies is a member that does not exist."""
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name) / "project"
        lib = root / "agents" / "lib" / "external_write"
        lib.parent.mkdir(parents=True)
        shutil.copytree(_AGENTS_LIB / "external_write", lib,
                        ignore=shutil.ignore_patterns("__pycache__", "test_*.py"))
        caps = root / "agents" / "capabilities"
        caps.mkdir(parents=True)
        (lib / "adapters_probe.py").write_text(
            "from typing import Any\n"
            "from external_write.adapter_registry import register_adapter\n"
            "\n"
            "OP_KIND = 'probe.op'\n"
            "\n"
            "\n"
            "def build_read_only_client() -> Any:\n"
            "    return object()\n"
            "\n"
            "\n"
            "class ProbeAdapter:\n"
            "    def apply_one(self, raw_client, unit):\n"
            "        return None\n"
            "\n"
            "\n"
            "register_adapter(OP_KIND, ProbeAdapter())\n",
            encoding="utf-8")
        (lib / "operator_adapters.json").write_text(
            json.dumps(["adapters_probe"]), encoding="utf-8")
        (caps / "probe_capability.py").write_text(
            "OP_KIND = 'probe.op'\n\n\ndef propose_operations(facade, batch_id):\n"
            "    return []\n", encoding="utf-8")

        _remediated, outcomes, blocking = \
            upgrade_reconcile.reconcile_adapter_migrations(
                root, _WIZARD.parent,
                from_version="v0.20.0", to_version="v0.21.0")
        self.assertIsNone(blocking)
        reported = {o.migration_name for o in outcomes}
        for migration in ADAPTER_MIGRATIONS:
            self.assertIn(migration.name, reported,
                          f"{migration.name} is declared but was never applied")


class UnreachableMechanismRule(unittest.TestCase):
    """The process rule, mechanised: for each remediation this cut adds, the
    producer creates the bad shape, the real path runs, and the consumer proves
    the branch executed."""

    def _project(self, adapter_source, *, op_kind="probe.op"):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name) / "project"
        lib = root / "agents" / "lib" / "external_write"
        lib.parent.mkdir(parents=True)
        shutil.copytree(_AGENTS_LIB / "external_write", lib,
                        ignore=shutil.ignore_patterns("__pycache__", "test_*.py"))
        caps = root / "agents" / "capabilities"
        caps.mkdir(parents=True)
        (lib / "adapters_probe.py").write_text(adapter_source, encoding="utf-8")
        (lib / "operator_adapters.json").write_text(
            json.dumps(["adapters_probe"]), encoding="utf-8")
        (caps / "probe_capability.py").write_text(
            f"OP_KIND = {op_kind!r}\n\n\n"
            "def propose_operations(facade, batch_id):\n    return []\n",
            encoding="utf-8")
        return root

    def _queue(self, root):
        path = root / "agents" / "handoffs" / "pending_migrations.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def test_the_read_provisioner_blocking_branch_executes(self):
        root = self._project(
            "from external_write.adapter_registry import register_adapter\n"
            "\n"
            "OP_KIND = 'probe.op'\n"
            "\n"
            "\n"
            "class A:\n    pass\n"
            "\n"
            "\n"
            "class B:\n    pass\n"
            "\n"
            "\n"
            "register_adapter(OP_KIND, A())\n"
            "register_adapter('other.op', B())\n")
        upgrade_reconcile.reconcile_upgrade(
            root, _WIZARD.parent, from_version="v0.20.0", to_version="v0.21.0")
        self.assertTrue(
            [e for e in self._queue(root)
             if e.get("kind") == "read_provisioner_missing"],
            "the post-condition's blocking branch has never executed")

    def test_the_migration_refusal_branch_executes(self):
        root = self._project(
            "from typing import Any\n"
            "from external_write.adapter_registry import register_adapter\n"
            "\n"
            "OP_KIND = 'probe.op'\n"
            "\n"
            "\n"
            "def build_read_only_client() -> Any:\n"
            "    return object()\n"
            "\n"
            "\n"
            "class A:\n    pass\n"
            "\n"
            "\n"
            "class B:\n    pass\n"
            "\n"
            "\n"
            "register_adapter(OP_KIND, A())\n"
            "register_adapter('other.op', B())\n")
        upgrade_reconcile.reconcile_upgrade(
            root, _WIZARD.parent, from_version="v0.20.0", to_version="v0.21.0")
        self.assertTrue(
            [e for e in self._queue(root)
             if e.get("kind") == "adapter_migration_refused"],
            "the refusal-routing branch has never executed")

    def test_the_undo_declaration_blocking_branch_executes(self):
        """Cut 1.9 clause (c). The producer creates a capability-declared op_kind
        whose adapter declares nothing AND defines no in-module ``undo_one``, so
        the migration correctly leaves it alone (declaring next to an undo step
        that is not there would be a guess); the REAL entry point runs; the
        consumer proves a durable blocking entry landed. That division of labour
        IS the design -- the migration is best-effort delivery, the
        post-condition is the fail-closed keystone."""
        root = self._project(
            "from external_write.adapter_registry import register_adapter\n"
            "\n"
            "OP_KIND = 'probe.op'\n"
            "\n"
            "\n"
            "class A:\n"
            "    def build_read_only_client(self, op):\n"
            "        return object()\n"
            "\n"
            "\n"
            "register_adapter(OP_KIND, A())\n")
        upgrade_reconcile.reconcile_upgrade(
            root, _WIZARD.parent, from_version="v0.22.0", to_version="v0.23.0")
        self.assertTrue(
            [e for e in self._queue(root)
             if e.get("kind", "").startswith("undo_declaration")],
            "the undo-declaration post-condition's blocking branch has never "
            "executed")

    def test_the_undo_declaration_migration_branch_executes(self):
        """The other half: an adapter that CAN be migrated must actually be
        migrated by the real entry point, and must then not also be blocked."""
        root = self._project(
            "from external_write.adapter_registry import register_adapter\n"
            "\n"
            "OP_KIND = 'probe.op'\n"
            "\n"
            "\n"
            "class A:\n"
            "    def build_read_only_client(self, op):\n"
            "        return object()\n"
            "\n"
            "    def undo_one(self, raw_client, unit):\n"
            "        return None\n"
            "\n"
            "\n"
            "register_adapter(OP_KIND, A())\n")
        upgrade_reconcile.reconcile_upgrade(
            root, _WIZARD.parent, from_version="v0.22.0", to_version="v0.23.0")
        migrated = (root / "agents" / "lib" / "external_write"
                    / "adapters_probe.py").read_text(encoding="utf-8")
        self.assertIn("UNDO_IS_ABSOLUTE_STATE_RESTORE = False", migrated)
        self.assertEqual(
            [e for e in self._queue(root)
             if e.get("kind", "").startswith("undo_declaration")], [],
            "a successfully migrated adapter must not also be blocked")

    def test_the_unreadable_enrolment_blocking_branch_executes(self):
        root = self._project(
            "from external_write.adapter_registry import register_adapter\n"
            "\n"
            "OP_KIND = 'probe.op'\n"
            "\n"
            "\n"
            "class A:\n"
            "    def build_read_only_client(self, op):\n"
            "        return object()\n"
            "\n"
            "\n"
            "register_adapter(OP_KIND, A())\n")
        (root / "agents" / "lib" / "external_write"
         / "operator_adapters.json").write_text("{not json", encoding="utf-8")
        upgrade_reconcile.reconcile_upgrade(
            root, _WIZARD.parent, from_version="v0.20.0", to_version="v0.21.0")
        self.assertTrue(
            [e for e in self._queue(root)
             if e.get("kind") == "adapter_enrolment_unreadable"],
            "the fail-closed enrolment branch has never executed")


if __name__ == "__main__":
    unittest.main()
