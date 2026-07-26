"""The declared adapter-migration set: membership is the only way a migration
exists, so a migration nothing calls cannot be written."""

import sys
import unittest
from pathlib import Path

_SCRIPTS_LIB = Path(__file__).resolve().parent
if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))

from adapter_migrations import (  # noqa: E402
    ADAPTER_MIGRATIONS, MigrationContext, TransformResult,
)


class DeclaredMigrationSet(unittest.TestCase):

    def test_the_set_is_not_empty(self):
        self.assertTrue(ADAPTER_MIGRATIONS)

    def test_every_member_has_a_unique_name(self):
        names = [m.name for m in ADAPTER_MIGRATIONS]
        self.assertEqual(len(names), len(set(names)), f"duplicate names: {names}")

    def test_the_provisioner_migration_is_a_member(self):
        """The specific regression: this migration existed, worked, was tested
        against copies of real operator adapters -- and nothing called it."""
        self.assertIn("module_level_provisioner",
                      [m.name for m in ADAPTER_MIGRATIONS])

    def test_every_member_is_pure_and_returns_a_transform_result(self):
        """A migration must not touch the filesystem: the engine reads once,
        threads the text through every member, and writes once."""
        source = "OP_KIND = 'x'\n"
        context = MigrationContext(required_predicates=())
        for migration in ADAPTER_MIGRATIONS:
            with self.subTest(migration=migration.name):
                result = migration.plan(source, context)
                self.assertIsInstance(result, TransformResult)
                self.assertIsInstance(result.source, str)
                self.assertIsInstance(result.changed, bool)
                self.assertTrue(result.reason,
                                "a migration must always give a reason, "
                                "including when it changes nothing")

    def test_a_member_that_changes_nothing_returns_the_source_verbatim(self):
        source = "OP_KIND = 'x'\n"
        context = MigrationContext(required_predicates=())
        for migration in ADAPTER_MIGRATIONS:
            with self.subTest(migration=migration.name):
                result = migration.plan(source, context)
                if not result.changed:
                    self.assertEqual(result.source, source)


if __name__ == "__main__":
    unittest.main()
