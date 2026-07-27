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

    # -- Call sites nested inside control flow: still reported, never dropped --

    def test_conservation_no_call_site_is_ever_dropped(self):
        """For N syntactic register_* call sites, at least N Declarations
        come back -- resolved or reported, but never fewer than N."""
        src = (
            'OP_A = "a.a"\n'
            'class ClsA: pass\n'
            'def _setup():\n'
            '    register_adapter(OP_A, ClsA())\n'
            'if True:\n'
            '    register_adapter(OP_A, ClsA())\n'
            'try:\n'
            '    register_adapter(OP_A, ClsA())\n'
            'except Exception:\n'
            '    pass\n'
            'register_read_facade(OP_A, ClsA)\n'
            'for k in (OP_A,):\n'
            '    register_read_facade(k, ClsA)\n'
        )
        call_sites = src.count("register_adapter(") + src.count("register_read_facade(")
        decls = discover_declarations(src, "conservation.py")
        self.assertGreaterEqual(len(decls), call_sites)

    def test_nested_in_if_is_reported_not_dropped(self):
        src = (
            'OP = "x.y"\n'
            'class C: pass\n'
            'if True:\n'
            '    register_read_facade(OP, C)\n'
        )
        decls = discover_declarations(src, "nested_if.py")
        self.assertEqual(len(decls), 1, "a call inside an if must still be reported")
        self.assertIsNone(decls[0].op_kind)
        self.assertIsNotNone(decls[0].unresolved_reason)
        self.assertIn("nested_if.py", decls[0].unresolved_reason)

    def test_nested_in_function_is_reported_not_dropped(self):
        src = (
            'OP = "x.y"\n'
            'class C: pass\n'
            'def _setup():\n'
            '    register_read_facade(OP, C)\n'
        )
        decls = discover_declarations(src, "nested_def.py")
        self.assertEqual(len(decls), 1, "a call inside a function must still be reported")
        self.assertIsNone(decls[0].op_kind)
        self.assertIsNotNone(decls[0].unresolved_reason)
        self.assertIn("nested_def.py", decls[0].unresolved_reason)

    def test_inside_try_is_reported_not_dropped(self):
        src = (
            'OP = "x.y"\n'
            'class C: pass\n'
            'try:\n'
            '    register_read_facade(OP, C)\n'
            'except Exception:\n'
            '    pass\n'
        )
        decls = discover_declarations(src, "nested_try.py")
        self.assertEqual(len(decls), 1, "a call inside a try must still be reported")
        self.assertIsNone(decls[0].op_kind)
        self.assertIsNotNone(decls[0].unresolved_reason)
        self.assertIn("nested_try.py", decls[0].unresolved_reason)

    def test_keyword_only_form_resolves(self):
        src = (
            'OP = "x.y"\n'
            'class C: pass\n'
            'register_read_facade(op_kind=OP, facade_cls=C)\n'
        )
        decls = discover_declarations(src, "kwonly.py")
        self.assertEqual(len(decls), 1)
        self.assertEqual(decls[0].op_kind, "x.y")
        self.assertEqual(decls[0].symbol, "C")
        self.assertIsNone(decls[0].unresolved_reason)

    def test_single_arg_form_is_reported_not_dropped(self):
        src = (
            'OP = "x.y"\n'
            'register_read_facade(OP)\n'
        )
        decls = discover_declarations(src, "singlearg.py")
        self.assertEqual(len(decls), 1,
                          "a call missing its required second argument must still be reported")
        self.assertIsNone(decls[0].op_kind)
        self.assertIsNotNone(decls[0].unresolved_reason)
        self.assertIn("singlearg.py", decls[0].unresolved_reason)

    def test_loop_over_module_level_tuple_constant_resolves(self):
        src = (
            'OPS = ("a.a", "b.b")\n'
            'class C: pass\n'
            'for k in OPS:\n'
            '    register_read_facade(k, C)\n'
        )
        decls = discover_declarations(src, "loopconst.py")
        self.assertEqual(sorted(d.op_kind for d in decls), ["a.a", "b.b"])
        self.assertTrue(all(d.symbol == "C" for d in decls))
        self.assertTrue(all(d.unresolved_reason is None for d in decls))

    def test_loop_over_unfoldable_iterable_is_reported(self):
        src = (
            'class C: pass\n'
            'for i in range(3):\n'
            '    register_read_facade(i, C)\n'
        )
        decls = discover_declarations(src, "loopbad.py")
        self.assertEqual(len(decls), 1,
                          "an unfoldable loop iterable must still be reported, not dropped")
        self.assertIsNone(decls[0].op_kind)
        self.assertIsNotNone(decls[0].unresolved_reason)
        self.assertIn("loopbad.py", decls[0].unresolved_reason)

    def test_nested_for_loop_is_reported_not_dropped(self):
        """A for loop that is itself nested (here, inside another for loop)
        is not the shipped top-level Gmail shape -- its register call must
        still be reported, never silently dropped."""
        src = (
            'OP = "x.y"\n'
            'class C: pass\n'
            'for _outer in (1, 2):\n'
            '    for _inner in (OP,):\n'
            '        register_read_facade(_inner, C)\n'
        )
        decls = discover_declarations(src, "nested_for.py")
        self.assertEqual(len(decls), 1, "a call inside a nested for loop must still be reported")
        self.assertIsNone(decls[0].op_kind)
        self.assertIsNotNone(decls[0].unresolved_reason)
        self.assertIn("nested_for.py", decls[0].unresolved_reason)


from topology import Topology, TopologyError, build_topology, Declaration


def _d(role, stem, op_kind, symbol="Cls"):
    return Declaration(role=role, module_stem=stem, relpath=stem + ".py",
                       op_kind=op_kind, symbol=symbol, unresolved_reason=None)


class TopologySelectionTests(unittest.TestCase):

    def test_finds_the_module_regardless_of_its_filename(self):
        t = Topology((_d("read_facade", "read_facades_inbox", "inbox.labels.modify"),))
        self.assertEqual(t.find_read_facade("inbox.labels.modify").module_stem,
                         "read_facades_inbox")

    def test_ONE_facade_serving_FOUR_op_kinds_is_legitimate_not_ambiguous(self):
        decls = tuple(_d("read_facade", "read_facades_gmail", k, "GmailReadFacade")
                      for k in ("gmail.message.trash", "gmail.message.untrash",
                                "gmail.message.modify_labels", "gmail.filter.create"))
        t = Topology(decls)
        for k in ("gmail.message.trash", "gmail.filter.create"):
            self.assertEqual(t.find_read_facade(k).symbol, "GmailReadFacade")

    def test_TWO_MODULES_claiming_the_same_op_kind_is_fail_closed(self):
        t = Topology((_d("read_facade", "read_facades_a", "x.y"),
                      _d("read_facade", "read_facades_b", "x.y")))
        with self.assertRaises(TopologyError) as ctx:
            t.find_read_facade("x.y")
        msg = str(ctx.exception)
        self.assertIn("read_facades_a", msg)
        self.assertIn("read_facades_b", msg)

    def test_zero_matches_is_fail_closed_and_names_the_op_kind(self):
        with self.assertRaises(TopologyError) as ctx:
            Topology(()).find_read_facade("nothing.here")
        self.assertIn("nothing.here", str(ctx.exception))

    def test_roles_do_not_collide(self):
        t = Topology((_d("adapter", "adapters_inbox", "x.y", "A"),
                      _d("read_facade", "read_facades_inbox", "x.y", "F")))
        self.assertEqual(t.find_adapter("x.y").symbol, "A")
        self.assertEqual(t.find_read_facade("x.y").symbol, "F")

    def test_zero_declarations_at_all_says_nothing_provides(self):
        with self.assertRaises(TopologyError) as ctx:
            Topology(()).find_read_facade("inbox.labels.modify")
        self.assertIn("nothing in this project provides", str(ctx.exception))

    def test_zero_matches_with_an_unresolved_declaration_names_the_reason_not_nothing_provides(self):
        """A module DID try to register something -- the scanner just could
        not read the shape it used. Telling the operator nothing provides it
        would send them off to write a new module instead of fixing the one
        that already exists."""
        unresolved = Declaration(
            role="read_facade", module_stem="read_facades_weird",
            relpath="read_facades_weird.py", op_kind=None, symbol=None,
            unresolved_reason=(
                "read_facades_weird.py registers something on line 4 but the "
                "operation name and the class/adapter it applies to are not "
                "both written in a form this check can read"))
        t = Topology((unresolved,))
        with self.assertRaises(TopologyError) as ctx:
            t.find_read_facade("inbox.labels.modify")
        msg = str(ctx.exception)
        self.assertIn(unresolved.unresolved_reason, msg)
        self.assertIn("read_facades_weird.py", msg)
        self.assertNotIn("nothing in this project provides", msg)


if __name__ == "__main__":
    unittest.main()
