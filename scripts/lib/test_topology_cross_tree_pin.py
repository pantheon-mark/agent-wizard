"""The emitted-lib and toolkit copies of the topology SHARED CORE must be
byte-identical. Two paths that must agree is the shape of most of the defects
this module exists to close -- so it is pinned, not trusted.

Run: python3 -m unittest discover -s wizard/scripts/lib -p test_topology_cross_tree_pin.py
"""
import unittest
from pathlib import Path

_WIZARD = Path(__file__).resolve().parents[2]
_EMITTED = _WIZARD / "agents" / "lib" / "external_write" / "topology.py"
_TOOLKIT = _WIZARD / "scripts" / "lib" / "topology.py"

_START = "# SHARED CORE"
_END = "# END SHARED CORE"


def _core(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(_START)
    end = text.index(_END) + len(_END)
    return text[start:end]


class TopologyCrossTreePinTests(unittest.TestCase):

    def test_both_copies_exist(self):
        self.assertTrue(_EMITTED.is_file(), f"missing {_EMITTED}")
        self.assertTrue(_TOOLKIT.is_file(), f"missing {_TOOLKIT}")

    def test_shared_core_is_byte_identical(self):
        self.assertEqual(
            _core(_EMITTED), _core(_TOOLKIT),
            "topology SHARED CORE has drifted between the emitted-lib and "
            "toolkit trees -- change one, change both, same commit")


if __name__ == "__main__":
    unittest.main()
