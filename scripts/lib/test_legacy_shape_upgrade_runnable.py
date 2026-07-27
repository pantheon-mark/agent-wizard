"""PERMANENT GATE: a project carrying the LEGACY adapter shape is scan-clean AND
runnable AFTER a real upgrade.

Why this exists, and why it is not the fresh-emit gate
-----------------------------------------------------
The fresh-emit gate asserts a newly scaffolded read-dependent capability is
scan-clean AND runnable. Fresh emit is correct, so that gate is green -- and
blind. Nothing asserted that a project carrying the OLDER adapter shape is
runnable after an upgrade, which is the one surface every already-built system
lives on. A migration was written for exactly that shape, was correct, was tested
against copies of real operator adapters, and nothing in any real flow called it:
every existing install stayed broken while every gate stayed green.

Do not split this into separate scan and run tests, and do not simplify the
fixture. Each of the four divergences below independently hid the defect:

  * the read-client builder at MODULE level, not on the registered class;
  * an adapter filename that does NOT match adapters_<capability_id>.py, so
    filename-convention resolution cannot find it;
  * that adapter enrolled in the explicit adapter list, so manifest resolution
    is the only thing that can;
  * one module needing BOTH migrations, so a composition that clobbers one of
    them fails here rather than in production.

Run:  python3 -m unittest discover -s wizard/scripts/lib \\
          -p test_legacy_shape_upgrade_runnable.py
"""

import ast
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_WIZARD = Path(__file__).resolve().parents[2]
_SCRIPTS_LIB = _WIZARD / "scripts" / "lib"
_AGENTS_LIB = _WIZARD / "agents" / "lib"
for _p in (str(_SCRIPTS_LIB), str(_AGENTS_LIB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from upgrade_reconcile import reconcile_upgrade  # noqa: E402

_CAPABILITY_ID = "vendor_cleanup"
_OP_KIND = "archive_vendor_record"

#: The adapter as an OLDER build left it: read-client builder at module level,
#: and one required evidence predicate absent so BOTH migrations are needed.
#: Filename is deliberately adapters_legacy_vendor.py -- NOT
#: adapters_vendor_cleanup.py -- so the filename convention cannot resolve it.
_LEGACY_ADAPTER = '''\
"""An adapter as an older build left it."""

from typing import Any

from external_write.adapter_registry import register_adapter
from external_write.contracts import OperationContract, register_contract

OP_KIND = "archive_vendor_record"

register_contract(OperationContract(
    op_kind=OP_KIND,
    writes=(),
    produces=(),
    dependency_set=(),
    verifier_set=(),
    introduces_persistent_binding=False,
    read_only_scope="acme.records.readonly",
))


def build_read_only_client() -> Any:
    """Module level, which is where older builds put it."""
    class _C:
        def list_records(self):
            return ["r1", "r2"]
    return _C()


class LegacyVendorAdapter:
    def plan(self, params: Any) -> Any:
        return []

    def apply_one(self, raw_client: Any, unit: Any) -> Any:
        return None

    def undo_one(self, raw_client: Any, unit: Any) -> Any:
        return None

    def verify_one(self, observer: Any, unit: Any) -> Any:
        return None

    def verify_apply_landed(self, observer: Any, unit: Any) -> bool:
        return True


register_adapter(OP_KIND, LegacyVendorAdapter())
'''

_CAPABILITY = '''\
"""A read-dependent capability, run by the kernel."""

OP_KIND = "archive_vendor_record"


def propose_operations(facade, batch_id, context=None):
    return list(facade.list_records())
'''

#: The sibling read-facade module a real legacy project already carries --
#: this predates and is orthogonal to both migrations under test (any adapter
#: that could ever actually read has always needed a registered contract +
#: a registered ReadFacade class; that is not part of what
#: ADAPTER_MIGRATIONS scaffolds). Named from the CAPABILITY id, which is what
#: an older build's scaffolding did -- never from the adapter's own
#: (non-standard) filename. The kernel no longer cares whether a facade's
#: filename matches the capability id or not; this fixture keeps the
#: id-matching name to prove the conforming case still resolves correctly
#: too, not just the mismatched one.
_LEGACY_READ_FACADE = '''\
"""Read-only facade for vendor_cleanup, as an older build left it."""

from typing import Any

from external_write.read_facade import ReadFacade, register_read_facade

OP_KIND = "archive_vendor_record"


class LegacyVendorReadFacade(ReadFacade):
    read_methods = ("list_records",)

    def list_records(self) -> Any:
        return self._read("list_records")


register_read_facade(OP_KIND, LegacyVendorReadFacade)
'''


class LegacyShapeUpgradeGate(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name) / "project"
        lib = self.root / "agents" / "lib" / "external_write"
        lib.parent.mkdir(parents=True)
        shutil.copytree(_AGENTS_LIB / "external_write", lib,
                        ignore=shutil.ignore_patterns("__pycache__", "test_*.py"))
        caps = self.root / "agents" / "capabilities"
        caps.mkdir(parents=True)

        # Divergence 1 + 4: module-level provisioner, one predicate missing.
        # Divergence 2: filename does not match the capability id.
        (lib / "adapters_legacy_vendor.py").write_text(
            _LEGACY_ADAPTER, encoding="utf-8")
        # Divergence 3: enrolled in the explicit list, which is the ONLY way to
        # resolve it.
        (lib / "operator_adapters.json").write_text(
            json.dumps(["adapters_legacy_vendor"]), encoding="utf-8")
        (caps / f"{_CAPABILITY_ID}_capability.py").write_text(
            _CAPABILITY, encoding="utf-8")
        # The sibling read-facade module -- see _LEGACY_READ_FACADE's own
        # comment for why this is baseline scaffolding, not a fifth divergence.
        (lib / f"read_facades_{_CAPABILITY_ID}.py").write_text(
            _LEGACY_READ_FACADE, encoding="utf-8")

        # Through the REAL upgrade path, not a sub-function.
        self.result = reconcile_upgrade(
            self.root, _WIZARD.parent,
            from_version="v0.20.0", to_version="v0.21.0")

    def _adapter_src(self):
        return (self.root / "agents" / "lib" / "external_write"
                / "adapters_legacy_vendor.py").read_text(encoding="utf-8")

    # ------------------------------------------ property 1: BOTH MIGRATIONS LANDED

    def test_the_provisioner_moved_onto_the_registered_class(self):
        tree = ast.parse(self._adapter_src())
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "LegacyVendorAdapter")
        self.assertIn("build_read_only_client",
                      {b.name for b in cls.body if isinstance(b, ast.FunctionDef)},
                      "the read-client builder must be a method on the class the "
                      "registry actually captures from")
        self.assertFalse(
            any(isinstance(n, ast.FunctionDef)
                and n.name == "build_read_only_client" for n in tree.body),
            "the module-level function must be gone, not duplicated")

    def test_the_missing_evidence_predicate_was_scaffolded(self):
        tree = ast.parse(self._adapter_src())
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "LegacyVendorAdapter")
        methods = {b.name for b in cls.body if isinstance(b, ast.FunctionDef)}
        self.assertIn("verify_undo_restored", methods,
                      "the other migration must have landed on the same module")
        self.assertIn("NotImplementedError", self._adapter_src(),
                      "a scaffolded check must FAIL until someone writes it")

    # ----------------------------------------------- property 2: POST-CONDITION

    def test_the_post_condition_comes_back_clean(self):
        self.assertEqual(
            self.result.read_provisioner_violations, [],
            "after a real upgrade of a legacy-shape project the read path must "
            "be conformant")

    def test_no_blocking_read_provisioner_entry_remains(self):
        queue_path = (self.root / "agents" / "handoffs"
                      / "pending_migrations.json")
        queue = json.loads(queue_path.read_text(encoding="utf-8")) \
            if queue_path.exists() else []
        self.assertEqual(
            [e for e in queue if e.get("kind") == "read_provisioner_missing"], [])

    # ---------------------------------------------------- property 3: SCAN-CLEAN

    def test_the_upgraded_project_is_scan_clean(self):
        result = subprocess.run(
            [sys.executable, "agents/lib/external_write/scan.py", "agents/"],
            cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         f"upgraded project must be scan-clean:\n"
                         f"{result.stdout}{result.stderr}")

    # ------------------------------------------------------ property 4: RUNNABLE

    def test_the_upgraded_project_can_actually_read(self):
        """The property nothing checked. Runs in a subprocess against the
        upgraded tree so the emitted lib is what executes."""
        harness = self.root / "_gate_probe.py"
        harness.write_text(
            "import sys\n"
            "sys.path.insert(0, 'agents/lib')\n"
            "from external_write import registered_adapters  # noqa: F401\n"
            "from external_write import adapters_legacy_vendor  # noqa: F401\n"
            "from external_write import capability_runner as CR\n"
            f"facade = CR.build_capability_read_facade('.', {_CAPABILITY_ID!r})\n"
            "print('READ_OK', list(facade.list_records()))\n",
            encoding="utf-8")
        result = subprocess.run([sys.executable, "_gate_probe.py"],
                                cwd=self.root, capture_output=True, text=True)
        self.assertIn("READ_OK", result.stdout,
                      "a legacy-shape project must be able to obtain a WORKING "
                      "read facade after a real upgrade:\n"
                      f"{result.stdout}{result.stderr}")
        self.assertIn("r1", result.stdout)


if __name__ == "__main__":
    unittest.main()
