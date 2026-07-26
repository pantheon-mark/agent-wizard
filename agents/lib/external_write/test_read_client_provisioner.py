"""Task 4 / Cut 1.6 (bundle v0.20.0) -- the SINGLE read-client provisioner
contract (A1), and the migrator that moves legacy module-level definitions onto
the adapter class.

F-STEP0-1: ``adapter_registry.py`` captures the provisioner with
``getattr(cls, "build_read_only_client", None)`` and documents it as
``build_read_only_client(self, op)``, but every emitter ever shipped produced a
MODULE-LEVEL zero-arg function -- so the dispatch field was ``None`` in 100% of
deployments and the kernel branch consuming it had never once executed.

``test_a_freshly_scaffolded_adapter_exposes_the_provisioner_on_the_class`` is
the assertion whose ABSENCE allowed that: a name-grep found
``build_read_only_client`` everywhere and looked wired, while nothing checked
the definition SHAPE. It must exist forever.

NO dual-shape runtime fallback (both cross-vendor advisors rejected it): the
class method is the only runtime contract, and legacy modules are MIGRATED at
build time rather than accommodated by a silent runtime guess.

Run:  python3 -m unittest discover -s wizard/agents/lib/external_write \\
          -p test_read_client_provisioner.py
"""

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_EXTERNAL_WRITE_DIR = Path(__file__).resolve().parent
_AGENTS_LIB = _EXTERNAL_WRITE_DIR.parent
_WIZARD = _AGENTS_LIB.parent.parent
for _p in (str(_AGENTS_LIB), str(_WIZARD / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from capability_code_scaffold import (  # noqa: E402
    CapabilityCodeSpec, emit_capability_code_scaffold, render_adapter_module,
)
import provisioner_migration as pm  # noqa: E402


def _spec():
    return CapabilityCodeSpec(
        capability_id="vendor_cleanup",
        display_name="Vendor Record Cleanup",
        op_kind="archive_vendor_record",
        surface="acme_crm",
        read_only_scope="acme.records.readonly",
        blast_radius_cap=50,
        read_methods=("list_records", "get_record"),
    )


class FreshEmitProvisionerShapeTests(unittest.TestCase):

    def test_a_freshly_scaffolded_adapter_exposes_the_provisioner_on_the_class(self):
        """THE ASSERTION WHOSE ABSENCE CAUSED F-STEP0-1. Checks the definition
        SHAPE, not merely that the name appears somewhere in the file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            emit_capability_code_scaffold(_spec(), root)
            adapter_src = (root / "agents" / "lib" / "external_write"
                           / "adapters_vendor_cleanup.py").read_text(encoding="utf-8")

            ns = {}
            import ast
            tree = ast.parse(adapter_src)
            cls = next(n for n in ast.walk(tree)
                       if isinstance(n, ast.ClassDef) and n.name == "VendorCleanupAdapter")
            methods = {b.name for b in cls.body if isinstance(b, ast.FunctionDef)}
            self.assertIn("build_read_only_client", methods,
                          "the provisioner must be a METHOD on the adapter class -- a "
                          "module-level function leaves the registry hook None")
            self.assertNotIn(
                "\ndef build_read_only_client(", adapter_src,
                "no module-level provisioner may remain")

    def test_the_emitted_method_takes_self_and_op(self):
        """The documented registry contract is (self, op); the legacy shape was
        zero-arg. A method with the wrong arity would be captured by getattr and
        then blow up at call time -- worse than not being there."""
        import ast
        tree = ast.parse(render_adapter_module(_spec()))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "build_read_only_client":
                args = [a.arg for a in node.args.args]
                self.assertEqual(args, ["self", "op"])
                return
        self.fail("no build_read_only_client found in the rendered adapter")


class ProvisionerMigrationTests(unittest.TestCase):
    """The migrator that moves an already-emitted module-level provisioner onto
    its registered adapter class. Keyed on the class actually passed to
    register_adapter (ADR-0045 F-1), never on ClassDef order."""

    LEGACY = textwrap.dedent('''\
        """Legacy adapter."""
        from external_write.adapter_registry import register_adapter

        OP_KIND = "archive_vendor_record"


        class VendorCleanupAdapter:
            def plan(self, params):
                return []


        register_adapter(OP_KIND, VendorCleanupAdapter())


        def build_read_only_client() -> object:
            """Construct a read-only client."""
            return {"scope": "acme.records.readonly"}
        ''')

    def _write(self, text, name="adapters_vendor_cleanup.py"):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = Path(self.tmp.name) / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_it_moves_the_function_onto_the_registered_class(self):
        import ast
        p = self._write(self.LEGACY)
        result = pm.migrate_module_level_provisioner(p)
        self.assertTrue(result.migrated, result.reason)

        tree = ast.parse(p.read_text(encoding="utf-8"))
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "VendorCleanupAdapter")
        methods = {b.name for b in cls.body if isinstance(b, ast.FunctionDef)}
        self.assertIn("build_read_only_client", methods)
        self.assertIsNone(pm._module_level_provisioner(tree),
                          "the module-level function must be gone")
        # the body is preserved, not replaced by a stub
        self.assertIn("acme.records.readonly", p.read_text(encoding="utf-8"))

    def test_it_is_idempotent(self):
        p = self._write(self.LEGACY)
        first = pm.migrate_module_level_provisioner(p)
        self.assertTrue(first.migrated)
        after_first = p.read_text(encoding="utf-8")
        second = pm.migrate_module_level_provisioner(p)
        self.assertFalse(second.migrated)
        self.assertEqual(p.read_text(encoding="utf-8"), after_first,
                         "a second run must not touch the file")

    def test_it_refuses_when_the_registered_class_is_ambiguous(self):
        src = self.LEGACY.replace(
            "register_adapter(OP_KIND, VendorCleanupAdapter())",
            "register_adapter(OP_KIND, VendorCleanupAdapter())\n"
            "register_adapter('other', VendorCleanupAdapter2())\n\n\n"
            "class VendorCleanupAdapter2:\n    pass\n")
        p = self._write(src)
        before = p.read_text(encoding="utf-8")
        result = pm.migrate_module_level_provisioner(p)
        self.assertFalse(result.migrated)
        self.assertIn("exactly one registered adapter class", result.reason)
        self.assertEqual(p.read_text(encoding="utf-8"), before, "a refusal must not write")

    def test_it_never_shadows_an_existing_method(self):
        """ADR-0045 F-1's lesson: an upgrade must never emit a method whose name
        already exists on the target class."""
        src = self.LEGACY.replace(
            "    def plan(self, params):\n        return []",
            "    def plan(self, params):\n        return []\n\n"
            "    def build_read_only_client(self, op):\n        return 'already here'")
        p = self._write(src)
        before = p.read_text(encoding="utf-8")
        result = pm.migrate_module_level_provisioner(p)
        self.assertFalse(result.migrated)
        self.assertIn("already defines", result.reason)
        self.assertEqual(p.read_text(encoding="utf-8"), before)

    def test_it_refuses_an_unparseable_module(self):
        p = self._write("def broken( :\n")
        result = pm.migrate_module_level_provisioner(p)
        self.assertFalse(result.migrated)
        self.assertIn("parsed", result.reason)

    def test_it_reports_nothing_to_do_on_an_already_correct_module(self):
        src = self.LEGACY.replace(
            '\n\ndef build_read_only_client() -> object:\n'
            '    """Construct a read-only client."""\n'
            '    return {"scope": "acme.records.readonly"}\n', "")
        p = self._write(src)
        result = pm.migrate_module_level_provisioner(p)
        self.assertFalse(result.migrated)
        self.assertIn("nothing to do", result.reason)


if __name__ == "__main__":
    unittest.main()
