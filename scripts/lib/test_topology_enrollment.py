"""topology.py must reach every generated project. An unenrolled emitted
module is silently absent -- the kernel would then fail closed everywhere.

Run: python3 -m unittest discover -s wizard/scripts/lib -p test_topology_enrollment.py
"""
import unittest
from pathlib import Path

import agent_emitter

_WIZARD = Path(__file__).resolve().parents[2]


class TopologyEnrollmentTests(unittest.TestCase):

    def test_topology_is_in_the_emitted_lib_file_list(self):
        self.assertIn("topology.py", agent_emitter._EXTERNAL_WRITE_LIB_FILES)

    def test_every_listed_lib_file_actually_exists(self):
        lib = _WIZARD / "agents" / "lib" / "external_write"
        missing = [f for f in agent_emitter._EXTERNAL_WRITE_LIB_FILES
                   if not (lib / f).is_file()]
        self.assertEqual(missing, [], f"listed but absent: {missing}")

    def test_every_emitted_lib_module_is_listed(self):
        """Derive from the real tree, never a hand-maintained list."""
        lib = _WIZARD / "agents" / "lib" / "external_write"
        on_disk = {p.name for p in lib.glob("*.py")
                   if not p.name.startswith("test_") and p.name != "__init__.py"}
        unlisted = sorted(on_disk - set(agent_emitter._EXTERNAL_WRITE_LIB_FILES))
        self.assertEqual(unlisted, [], f"emitted but never shipped: {unlisted}")


if __name__ == "__main__":
    unittest.main()
