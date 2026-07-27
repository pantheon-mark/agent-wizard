"""The kernel must resolve a read facade by declaration -- never by deriving
a filename from the capability id, and never by handing back an unvalidated
object when a declaration is malformed. Run:
  python3 -m unittest discover -s wizard/agents/lib/external_write \
      -p test_capability_runner_topology.py
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[1]
if str(_AGENTS_LIB) not in sys.path:
    sys.path.insert(0, str(_AGENTS_LIB))

import external_write as _ew                            # noqa: E402
from external_write import capability_runner as cr       # noqa: E402
from external_write.read_facade import ReadFacade        # noqa: E402


class _ScratchKernelDirTestCase(unittest.TestCase):
    """Shared fixture: for the duration of one test, `capability_runner`'s
    own reported location and `external_write`'s own import search path both
    point at a scratch directory -- what a real project's kernel install
    looks like, without needing to copy every kernel file to get it."""

    OP_KIND = "inbox.labels.modify"
    CAPABILITY_ID = "inbox_management"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        caps = self.root / "agents" / "capabilities"
        caps.mkdir(parents=True)
        (caps / f"{self.CAPABILITY_ID}_capability.py").write_text(
            f'OP_KIND = "{self.OP_KIND}"\n\n'
            'def propose_operations(facade, batch_id):\n    return []\n',
            encoding="utf-8")

        orig_cr_file = cr.__file__
        cr.__file__ = str(self.root / "capability_runner.py")
        self.addCleanup(setattr, cr, "__file__", orig_cr_file)
        _ew.__path__.append(str(self.root))
        self.addCleanup(_ew.__path__.remove, str(self.root))

    def _write_facade_module(self, filename, source):
        (self.root / filename).write_text(source, encoding="utf-8")

    def _resolve(self):
        return cr.resolve_read_facade_class(str(self.root), self.CAPABILITY_ID)


class ReadFacadeResolutionByDeclarationTests(_ScratchKernelDirTestCase):

    def test_facade_resolves_when_filename_does_not_match_capability_id(self):
        # DELIBERATE: filename does NOT match capability id.
        self._write_facade_module(
            "read_facades_inbox.py",
            'from external_write.read_facade import ReadFacade, register_read_facade\n'
            f'OP_KIND = "{self.OP_KIND}"\n'
            'class InboxReadFacade(ReadFacade):\n'
            '    read_methods = ("list_messages",)\n'
            'register_read_facade(OP_KIND, InboxReadFacade)\n')

        facade_cls = self._resolve()

        self.assertEqual(facade_cls.__name__, "InboxReadFacade")
        self.assertEqual(facade_cls.__module__, "external_write.read_facades_inbox")
        self.assertTrue(issubclass(facade_cls, ReadFacade))


class ReadFacadeResolutionRefusalTests(_ScratchKernelDirTestCase):
    """The replacement for the deleted bare `except: pass` has to REPORT
    every way resolution can fail -- in plain language, naming the file
    where one exists, never a raw traceback -- rather than silently handing
    back nothing (the old defect) or an unvalidated object (a new one)."""

    def test_no_declaration_anywhere_is_fail_closed_and_actionable(self):
        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            self._resolve()
        message = str(ctx.exception)
        self.assertIn("rebuilt", message)
        self.assertNotIn("register_read_facade", message)
        self.assertNotIn("Traceback", message)

    def test_two_files_claiming_the_same_operation_names_them_not_a_rebuild(self):
        for suffix in ("one", "two"):
            self._write_facade_module(
                f"read_facades_{suffix}.py",
                'from external_write.read_facade import ReadFacade, register_read_facade\n'
                f'OP_KIND = "{self.OP_KIND}"\n'
                f'class Facade{suffix.title()}(ReadFacade):\n'
                '    read_methods = ()\n'
                f'register_read_facade(OP_KIND, Facade{suffix.title()})\n')

        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            self._resolve()
        message = str(ctx.exception)
        self.assertNotIn("rebuilt", message)
        self.assertIn("read_facades_one.py", message)
        self.assertIn("read_facades_two.py", message)
        self.assertNotIn("Traceback", message)

    def test_a_declaring_file_that_raises_on_import_names_the_file(self):
        # The op_kind is declared (topology's static read finds the call
        # textually), but running the file top-to-bottom raises before that
        # call is ever reached -- an import failure, not a missing
        # declaration.
        self._write_facade_module(
            "read_facades_broken.py",
            'raise RuntimeError("boom")\n'
            'from external_write.read_facade import ReadFacade, register_read_facade\n'
            f'OP_KIND = "{self.OP_KIND}"\n'
            'class BrokenFacade(ReadFacade):\n'
            '    read_methods = ()\n'
            'register_read_facade(OP_KIND, BrokenFacade)\n')

        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            self._resolve()
        message = str(ctx.exception)
        self.assertIn("read_facades_broken.py", message)
        self.assertNotIn("Traceback", message)

    def test_a_file_that_imports_but_registers_nothing_is_refused_not_none(self):
        # The declaration resolves and the module imports cleanly, but it
        # takes its own registration back before finishing -- so the
        # registry ends up without an entry for this op_kind despite a
        # successful import. This has to be reported, not treated as if
        # nothing were declared.
        self._write_facade_module(
            "read_facades_selfundoing.py",
            'from external_write.read_facade import (ReadFacade, register_read_facade,\n'
            '    unregister_read_facade)\n'
            f'OP_KIND = "{self.OP_KIND}"\n'
            'class SelfUndoingFacade(ReadFacade):\n'
            '    read_methods = ()\n'
            'register_read_facade(OP_KIND, SelfUndoingFacade)\n'
            'unregister_read_facade(OP_KIND)\n')

        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            self._resolve()
        message = str(ctx.exception)
        self.assertIn("read_facades_selfundoing.py", message)
        self.assertNotIn("Traceback", message)

    def test_an_unreadable_declaring_file_is_named_not_treated_as_a_rebuild(self):
        # Nothing resolvably declares THIS op_kind, but a DIFFERENT
        # declaration in the project sits inside a function body, which
        # cannot be resolved -- so it is unknown whether that file might
        # have been the one providing it. Saying "rebuilt" here would send
        # the operator to create a brand new file instead of fixing the one
        # that already exists but could not be read.
        self._write_facade_module(
            "read_facades_unreadable.py",
            'from external_write.read_facade import ReadFacade, register_read_facade\n\n'
            'def _register_late():\n'
            '    class NestedFacade(ReadFacade):\n'
            '        read_methods = ()\n'
            '    register_read_facade("something.unrelated", NestedFacade)\n')

        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            self._resolve()
        message = str(ctx.exception)
        self.assertNotIn("rebuilt", message)
        self.assertIn("read_facades_unreadable.py", message)
        self.assertNotIn("Traceback", message)

    def test_the_kernel_classifies_from_the_exception_not_by_re_deriving(self):
        # The kernel has to branch on TopologyError's own attributes, never
        # by re-inspecting Topology's declarations itself. Proven by making
        # the two disagree: the exception claims a conflict between two
        # files that do not exist anywhere on disk, while nothing on disk
        # declares anything at all. If the kernel were re-deriving its own
        # filter over the declarations, it could not possibly reproduce
        # this conflict, because there would be nothing to find it in.
        from external_write.topology import Topology, TopologyError

        def _fake_find_read_facade(self, op_kind):
            raise TopologyError(
                "a build-time message, not read by the kernel",
                op_kind=op_kind, role="read_facade",
                conflicting_relpaths=("totally_fake_a.py", "totally_fake_b.py"))

        orig = Topology.find_read_facade
        Topology.find_read_facade = _fake_find_read_facade
        self.addCleanup(setattr, Topology, "find_read_facade", orig)

        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            self._resolve()
        message = str(ctx.exception)
        self.assertIn("totally_fake_a.py", message)
        self.assertIn("totally_fake_b.py", message)
        self.assertNotIn("rebuilt", message)


class ReadFacadeResolutionNeverReturnsAnUnvalidatedObjectTests(_ScratchKernelDirTestCase):
    """The class has to come from the registry accessor `register_read_facade`
    itself already validated, never from a raw `getattr` on the declaring
    module's namespace -- so a malformed declaration is refused (or, where
    the registry can still answer correctly, resolves correctly) instead of
    handing an unchecked value to the caller."""

    def test_a_non_class_named_by_a_declaration_is_refused_not_called(self):
        # register_read_facade's own validation
        # (isinstance(x, type) and issubclass(x, ReadFacade)) refuses a
        # plain function at import time, long before anything downstream
        # could try to use it as though it were a class.
        self._write_facade_module(
            "read_facades_funcshape.py",
            f'OP_KIND = "{self.OP_KIND}"\n'
            'def _make():\n'
            '    pass\n'
            'from external_write.read_facade import register_read_facade\n'
            'register_read_facade(OP_KIND, _make)\n')

        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            self._resolve()
        message = str(ctx.exception)
        self.assertNotIn("Traceback", message)
        self.assertNotIn("positional argument", message)

    def test_a_non_readfacade_class_named_by_a_declaration_is_refused_not_leaked(self):
        # A declaration whose named symbol is a real class, but not a
        # ReadFacade subclass, must never reach the caller -- that would be
        # the raw read-only client (or something equally uncontrolled)
        # handed straight to capability code. register_read_facade's own
        # validation refuses to ever put such a thing in the registry, so
        # the file's own import fails instead of the object leaking out.
        self._write_facade_module(
            "read_facades_notafacade.py",
            f'OP_KIND = "{self.OP_KIND}"\n'
            'class _RawClient:\n'
            '    pass\n'
            'from external_write.read_facade import register_read_facade\n'
            'register_read_facade(OP_KIND, _RawClient)\n')

        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            self._resolve()
        message = str(ctx.exception)
        self.assertNotIn("Traceback", message)

    def test_a_symbol_topology_cannot_name_still_resolves_via_the_registry(self):
        # register_read_facade(OP_KIND, _FACADES["widget"]) resolves the
        # op_kind, but the symbol argument is a subscript, not a plain name
        # -- topology cannot say what it is called (declaration.symbol is
        # None). The class still comes from the registry, which never
        # needed a name for it in the first place, so this resolves
        # correctly instead of failing on an unreadable symbol.
        self._write_facade_module(
            "read_facades_subscriptshape.py",
            'from external_write.read_facade import ReadFacade, register_read_facade\n'
            f'OP_KIND = "{self.OP_KIND}"\n'
            'class _RealFacade(ReadFacade):\n'
            '    read_methods = ()\n'
            '_FACADES = {"widget": _RealFacade}\n'
            'register_read_facade(OP_KIND, _FACADES["widget"])\n')

        facade_cls = self._resolve()

        self.assertEqual(facade_cls.__name__, "_RealFacade")
        self.assertTrue(issubclass(facade_cls, ReadFacade))


if __name__ == "__main__":
    unittest.main()
