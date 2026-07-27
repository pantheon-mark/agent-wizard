"""The kernel must resolve a read facade whose FILENAME does not match the
capability id. Run:
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


class ReadFacadeResolutionByDeclarationTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        caps = self.root / "agents" / "capabilities"
        caps.mkdir(parents=True)
        (caps / "inbox_management_capability.py").write_text(
            'OP_KIND = "inbox.labels.modify"\n\n'
            'def propose_operations(facade, batch_id):\n    return []\n',
            encoding="utf-8")

        # The kernel resolves a read facade by scanning the directory its own
        # module file lives in, then importing whichever file it finds there
        # that declares the op_kind it needs. For this test only,
        # `capability_runner`'s own reported location and `external_write`'s
        # own import search path both point at a scratch directory carrying
        # the ONE declaration this test cares about -- restored in
        # tearDown, via addCleanup, regardless of how the test ends.
        orig_cr_file = cr.__file__
        cr.__file__ = str(self.root / "capability_runner.py")
        self.addCleanup(setattr, cr, "__file__", orig_cr_file)
        _ew.__path__.append(str(self.root))
        self.addCleanup(_ew.__path__.remove, str(self.root))

        # DELIBERATE: filename does NOT match the capability id.
        (self.root / "read_facades_inbox.py").write_text(
            'from external_write.read_facade import ReadFacade, register_read_facade\n'
            'OP_KIND = "inbox.labels.modify"\n'
            'class InboxReadFacade(ReadFacade):\n'
            '    _ALLOWED = ("list_messages",)\n'
            'register_read_facade(OP_KIND, InboxReadFacade)\n',
            encoding="utf-8")

    def test_facade_resolves_when_filename_does_not_match_capability_id(self):
        facade_cls_name = cr.resolve_read_facade_class(
            str(self.root), "inbox_management")
        self.assertEqual(facade_cls_name.__name__, "InboxReadFacade")


if __name__ == "__main__":
    unittest.main()
