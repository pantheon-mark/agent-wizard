"""Declaration discovery: resolve op_kind bindings from the modules that
declare them, never from a filename. Run:
  python3 -m unittest discover -s wizard/agents/lib/external_write -p test_topology.py
"""
import unittest
from topology import discover_declarations


class DiscoverDeclarationsTests(unittest.TestCase):

    def test_plain_module_scope_registration_resolves(self):
        src = (
            'OP_KIND = "inbox.labels.modify"\n'
            'class InboxReadFacade: pass\n'
            'register_read_facade(OP_KIND, InboxReadFacade)\n'
        )
        decls = discover_declarations(src, "read_facades_inbox.py")
        self.assertEqual(len(decls), 1)
        self.assertEqual(decls[0].role, "read_facade")
        self.assertEqual(decls[0].op_kind, "inbox.labels.modify")
        self.assertEqual(decls[0].symbol, "InboxReadFacade")
        self.assertIsNone(decls[0].unresolved_reason)

    def test_string_literal_first_arg_resolves(self):
        src = 'register_adapter("x.y", MyAdapter())\n'
        decls = discover_declarations(src, "adapters_x.py")
        self.assertEqual([d.op_kind for d in decls], ["x.y"])
        self.assertEqual(decls[0].role, "adapter")

    def test_LOOP_over_tuple_of_module_constants_resolves_ALL(self):
        """The shipped read_facades_gmail.py shape. A matcher that misses this
        fail-closes on four op_kinds in 100% of deployments."""
        src = (
            'OP_TRASH = "gmail.message.trash"\n'
            'OP_UNTRASH = "gmail.message.untrash"\n'
            'OP_MODIFY_LABELS = "gmail.message.modify_labels"\n'
            'OP_FILTER_CREATE = "gmail.filter.create"\n'
            'class GmailReadFacade: pass\n'
            'for _op_kind in (OP_TRASH, OP_UNTRASH, OP_MODIFY_LABELS, OP_FILTER_CREATE):\n'
            '    register_read_facade(_op_kind, GmailReadFacade)\n'
        )
        decls = discover_declarations(src, "read_facades_gmail.py")
        self.assertEqual(
            sorted(d.op_kind for d in decls),
            ["gmail.filter.create", "gmail.message.modify_labels",
             "gmail.message.trash", "gmail.message.untrash"])
        self.assertTrue(all(d.symbol == "GmailReadFacade" for d in decls))
        self.assertTrue(all(d.unresolved_reason is None for d in decls))

    def test_unresolvable_shape_is_REPORTED_never_silently_skipped(self):
        src = (
            'import os\n'
            'register_read_facade(os.environ["K"], Cls)\n'
        )
        decls = discover_declarations(src, "read_facades_weird.py")
        self.assertEqual(len(decls), 1, "an unresolvable call must still be reported")
        self.assertIsNone(decls[0].op_kind)
        self.assertIsNotNone(decls[0].unresolved_reason)
        self.assertIn("read_facades_weird.py", decls[0].unresolved_reason)

    def test_syntax_error_is_reported_not_raised(self):
        decls = discover_declarations("def (:\n", "broken.py")
        self.assertEqual(len(decls), 1)
        self.assertIsNone(decls[0].op_kind)
        self.assertIn("could not be read", decls[0].unresolved_reason)

    def test_module_with_no_registrations_yields_nothing(self):
        self.assertEqual(discover_declarations("x = 1\n", "helper.py"), ())


if __name__ == "__main__":
    unittest.main()
