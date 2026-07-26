"""Tests for the pure adapter-provisioner migration transform.

``plan_provisioner_migration`` is a pure function of source text: it never
reads or writes a file, so the upgrade engine can compose it with other
adapter migrations on one in-memory copy of a module and write once.
``migrate_module_level_provisioner`` remains the standalone single-module path
used directly against a file on disk.
"""

import unittest


class ProvisionerMigrationTests(unittest.TestCase):

    def test_has_register_adapter_call_distinguishes_real_registration(self):
        """The shared resolver has a one-class fallback for modules with no
        registration at all. The provisioner migration must NOT inherit it --
        inferring the target from incidental structure is the defect class this
        migrator exists to avoid. This predicate is how it opts out."""
        import ast
        from capability_code_scaffold import has_register_adapter_call
        registered = ast.parse(
            "class A:\n    pass\n\nregister_adapter(OP, A())\n")
        self.assertTrue(has_register_adapter_call(registered))
        lone_class = ast.parse("class A:\n    pass\n")
        self.assertFalse(has_register_adapter_call(lone_class))

    _LEGACY_ADAPTER = (
        "from typing import Any\n"
        "from external_write.adapter_registry import register_adapter\n"
        "\n"
        "OP_KIND = 'demo.op'\n"
        "\n"
        "\n"
        "def build_read_only_client() -> Any:\n"
        "    return object()\n"
        "\n"
        "\n"
        "class DemoAdapter:\n"
        "    def apply_one(self, raw_client, unit):\n"
        "        return None\n"
        "\n"
        "\n"
        "register_adapter(OP_KIND, DemoAdapter())\n"
    )

    def test_plan_provisioner_migration_is_pure_and_moves_the_method(self):
        """A pure transform: source in, source out, no filesystem access."""
        import ast
        from provisioner_migration import plan_provisioner_migration
        result = plan_provisioner_migration(self._LEGACY_ADAPTER)
        self.assertTrue(result.changed, result.reason)
        tree = ast.parse(result.source)
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "DemoAdapter")
        self.assertIn("build_read_only_client",
                      {b.name for b in cls.body if isinstance(b, ast.FunctionDef)})
        self.assertFalse(any(isinstance(n, ast.FunctionDef)
                             and n.name == "build_read_only_client"
                             for n in tree.body),
                         "the module-level function must be gone")
        self.assertIn("def build_read_only_client(self, op)", result.source)

    def test_plan_provisioner_migration_refuses_without_a_real_registration(self):
        """A module with a lone class and no register_adapter(...) call must be
        refused, not silently rewritten against an inferred target."""
        from provisioner_migration import plan_provisioner_migration
        source = (
            "from typing import Any\n"
            "\n"
            "def build_read_only_client() -> Any:\n"
            "    return object()\n"
            "\n"
            "class DemoAdapter:\n"
            "    pass\n"
        )
        result = plan_provisioner_migration(source)
        self.assertFalse(result.changed)
        self.assertEqual(result.source, source, "source must be untouched")
        self.assertIn("register_adapter", result.reason)

    def test_a_decoy_nested_registration_does_not_authorise_a_rewrite(self):
        """The guard and the resolver's fallback trigger must be the same test.
        A registration call that is not a module-level statement does not make a
        lone class the registered target -- rewriting it anyway is exactly the
        incidental-structure inference this migration refuses."""
        from provisioner_migration import plan_provisioner_migration
        source = (
            "from typing import Any\n"
            "\n"
            "def build_read_only_client() -> Any:\n"
            "    return object()\n"
            "\n"
            "def _setup():\n"
            "    register_adapter('unrelated.op', SomeOtherThing())\n"
            "\n"
            "class DemoAdapter:\n"
            "    pass\n"
        )
        result = plan_provisioner_migration(source)
        self.assertFalse(result.changed)
        self.assertEqual(result.source, source, "source must be untouched")
        self.assertIn("register_adapter", result.reason)


if __name__ == "__main__":
    unittest.main()
