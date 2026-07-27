"""Attribution must come from the declaration join, not from a filename
convention. Run:
  python3 -m unittest discover -s wizard/scripts/lib -p test_upgrade_reconcile_topology.py
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import upgrade_reconcile


class AdapterAttributionByDeclarationTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.lib = self.root / "agents" / "lib" / "external_write"
        self.lib.mkdir(parents=True)
        caps = self.root / "agents" / "capabilities"
        caps.mkdir(parents=True)
        (caps / "inbox_management_capability.py").write_text(
            'OP_KIND = "inbox.labels.modify"\n', encoding="utf-8")
        # Filename deliberately does NOT match the canonical id.
        (self.lib / "adapters_inbox.py").write_text(
            'OP_KIND = "inbox.labels.modify"\n'
            'class InboxLabelsAdapter: pass\n'
            'register_adapter(OP_KIND, InboxLabelsAdapter())\n',
            encoding="utf-8")

    def test_capability_scoped_attribution_uses_the_CAPABILITY_id(self):
        attribution = upgrade_reconcile.attribute_adapter_to_capability(
            self.root, "agents/lib/external_write/adapters_inbox.py")
        self.assertEqual(attribution, "inbox_management",
                         "attribution must join on op_kind, not on the filename")

    def test_canonical_by_relpath_no_longer_exists(self):
        src = Path(upgrade_reconcile.__file__).read_text(encoding="utf-8")
        self.assertNotIn("canonical_by_relpath", src)

    def test_no_matching_capability_returns_none_not_a_guess(self):
        # An adapter that registers an op_kind no capability declares serves
        # no capability -- None is the honest answer, never a fallback guess
        # dressed up as a capability id.
        (self.lib / "adapters_orphan.py").write_text(
            'OP_KIND = "orphan.op.nothing_declares_this"\n'
            'class OrphanAdapter: pass\n'
            'register_adapter(OP_KIND, OrphanAdapter())\n',
            encoding="utf-8")
        attribution = upgrade_reconcile.attribute_adapter_to_capability(
            self.root, "agents/lib/external_write/adapters_orphan.py")
        self.assertIsNone(attribution)

    def test_unresolved_adapter_declaration_does_not_false_match_unresolved_capability(self):
        # Regression guard for the None-can't-become-a-WRONG-id requirement:
        # an adapter whose op_kind this checker cannot read (nested inside a
        # function -- topology.py reports this with op_kind=None, never
        # drops it) must not spuriously "match" a capability module whose own
        # OP_KIND also fails to resolve. Both sides being None must never
        # look like agreement.
        (caps_bad := self.root / "agents" / "capabilities" / "unreadable_capability.py").write_text(
            "def f():\n    OP_KIND = 'nested.not.module.level'\n", encoding="utf-8")
        (self.lib / "adapters_nested.py").write_text(
            "class NestedAdapter: pass\n"
            "def setup():\n"
            "    register_adapter('some.op', NestedAdapter())\n",
            encoding="utf-8")
        attribution = upgrade_reconcile.attribute_adapter_to_capability(
            self.root, "agents/lib/external_write/adapters_nested.py")
        self.assertIsNone(attribution)


if __name__ == "__main__":
    unittest.main()
