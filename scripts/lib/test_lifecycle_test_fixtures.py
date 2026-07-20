"""Tests for the hermetic lifecycle-state test fixture (external_write.lifecycle_test_fixtures --
Task A3, F-71).

These tests prove the fixture's own contract: it never touches a real project's ambient
``.wizard/paused-mechanisms/`` directory, it round-trips cleanly through the REAL
``write_gate._load_paused_op_kinds`` reader (the same function ``evaluate_write_gate`` calls),
and it cleans up after itself unconditionally, including when the caller's ``with`` block
raises. Op-kind-agnostic throughout -- no Gmail/estate-specific text, per this module's own
"generalizable common-layer" contract.
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (canonical location) -- mirrors
# test_capability_invariants.py / test_external_write_write_gate.py's own convention.
_AGENTS_LIB = Path(__file__).resolve().parents[2] / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.lifecycle_test_fixtures import hermetic_paused_mechanisms  # noqa: E402
from external_write.write_gate import _load_paused_op_kinds  # noqa: E402


class TestHermeticPausedMechanismsEmpty(unittest.TestCase):
    def test_no_op_kinds_yields_empty_paused_set(self):
        with hermetic_paused_mechanisms() as paused_root:
            self.assertEqual(_load_paused_op_kinds(paused_root), frozenset())

    def test_empty_directory_still_exists_and_is_listable(self):
        # (Anti-overfit) An empty hermetic root reads through _load_paused_op_kinds as the
        # EXISTING-but-empty branch (frozenset()), never the absent/unreadable branches -- proves
        # the fixture always creates the directory, even with nothing to put in it.
        with hermetic_paused_mechanisms() as paused_root:
            self.assertTrue(Path(paused_root).is_dir())
            self.assertEqual(list(Path(paused_root).iterdir()), [])


class TestHermeticPausedMechanismsWithOpKinds(unittest.TestCase):
    def test_named_op_kinds_round_trip_through_the_real_gate_reader(self):
        with hermetic_paused_mechanisms(["some_op_kind", "another_op_kind"]) as paused_root:
            self.assertEqual(
                _load_paused_op_kinds(paused_root),
                frozenset({"some_op_kind", "another_op_kind"}),
            )

    def test_unrelated_op_kind_not_reported_as_paused(self):
        # Anti-overfit: a DIFFERENT op_kind, never named to the fixture, must not show up in
        # the paused set -- proves the fixture writes exactly what it was asked for, nothing
        # broader.
        with hermetic_paused_mechanisms(["only_this_op_kind"]) as paused_root:
            paused = _load_paused_op_kinds(paused_root)
            self.assertIn("only_this_op_kind", paused)
            self.assertNotIn("unrelated_op_kind", paused)

    def test_two_calls_use_distinct_marker_names_without_colliding(self):
        with hermetic_paused_mechanisms(["op_a"], marker_name="first") as root_a, \
             hermetic_paused_mechanisms(["op_b"], marker_name="second") as root_b:
            self.assertNotEqual(root_a, root_b)
            self.assertEqual(_load_paused_op_kinds(root_a), frozenset({"op_a"}))
            self.assertEqual(_load_paused_op_kinds(root_b), frozenset({"op_b"}))


class TestHermeticPausedMechanismsIsolationAndCleanup(unittest.TestCase):
    def test_yielded_root_is_a_fresh_tempdir_not_any_real_project_path(self):
        with hermetic_paused_mechanisms(["op_kind"]) as paused_root:
            # A genuine OS temp directory, not a path constructed under any caller-supplied
            # project root (the fixture takes no project_root argument at all -- it has no way
            # to reach the real ambient path even if it wanted to).
            self.assertTrue(str(Path(paused_root).resolve()).startswith(
                str(Path(tempfile.gettempdir()).resolve())))

    def test_directory_removed_after_the_with_block_exits_cleanly(self):
        with hermetic_paused_mechanisms(["op_kind"]) as paused_root:
            recorded_root = paused_root
            self.assertTrue(Path(recorded_root).is_dir())
        self.assertFalse(Path(recorded_root).exists())

    def test_directory_removed_even_when_the_with_block_raises(self):
        recorded_root = None
        with self.assertRaises(ValueError):
            with hermetic_paused_mechanisms(["op_kind"]) as paused_root:
                recorded_root = paused_root
                self.assertTrue(Path(recorded_root).is_dir())
                raise ValueError("simulated test failure inside the with-block")
        self.assertIsNotNone(recorded_root)
        self.assertFalse(Path(recorded_root).exists())

    def test_repeated_use_never_reuses_a_stale_directory(self):
        # Anti-overfit: two SEPARATE hermetic contexts (as a real accept -> reconcile ->
        # re-test cycle would produce) never share a directory or leak state between them.
        with hermetic_paused_mechanisms(["op_kind"]) as first_root:
            first_paused = _load_paused_op_kinds(first_root)
        with hermetic_paused_mechanisms() as second_root:
            second_paused = _load_paused_op_kinds(second_root)
        self.assertNotEqual(first_root, second_root)
        self.assertEqual(first_paused, frozenset({"op_kind"}))
        self.assertEqual(second_paused, frozenset())


if __name__ == "__main__":
    unittest.main()
