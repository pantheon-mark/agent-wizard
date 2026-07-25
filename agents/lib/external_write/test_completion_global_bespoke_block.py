"""Task A / Cut 1.5 (bundle v0.19.0) -- KEYSTONE regression test for the V15-3
false-green: an operator project carrying an OPEN "bespoke writer" migration
entry (a hand-rolled per-chunk bulk loop that bypasses the sanctioned
run_sanctioned_bulk path) must make the completion gate go NON-GREEN
PROJECT-WIDE, INDEPENDENT of whether that entry resolves to the capability
being checked.

Root cause this closes (source-verified): the three safety views
(``capability_health._is_pending_migration`` / ``--overall`` and
``lifecycle_state.check_completion``) all key on the capability's CANONICAL id,
but a bespoke-writer entry is keyed on a relpath-derived ``mechanism_id`` with
NO owning-capability field -- so it was structurally invisible to them, and a
project with an open bypass reported green/done anyway.

A "bespoke writer" entry = an entry in ``agents/handoffs/pending_migrations.json``
where ``writer_relpath`` is set (non-null) AND ``status == "pending"``.
Canonical-capability entries have ``writer_relpath is None`` and are NOT bespoke
writers -- those must NOT trip the global block (no over-firing).

ANTI-OVERFIT: the baseline capability (``inbox_management``) is built through the
REAL, full acceptance ceremony (reusing test_lifecycle_state's own fixture
mixin), so absent the bespoke entry it is genuinely accepted/clean -> done=True /
normal_status_allowed=True. The RED signal is therefore a true false-green: only
the presence of the open bespoke-writer entry flips it non-green.

Run:  python3 -m unittest discover -s wizard/agents/lib/external_write \\
          -p test_completion_global_bespoke_block.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

_EXTERNAL_WRITE_DIR = Path(__file__).resolve().parent
_AGENTS_LIB = _EXTERNAL_WRITE_DIR.parent  # agents/lib -- external_write is a package under here
_SCRIPTS_LIB = _EXTERNAL_WRITE_DIR.parents[2] / "scripts" / "lib"  # wizard/scripts/lib
for _p in (str(_AGENTS_LIB), str(_SCRIPTS_LIB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from external_write import lifecycle_state  # noqa: E402
from external_write import capability_health  # noqa: E402

# Reuse the REAL full-ceremony fixture mixin -- never a hand-authored accepted/audit stand-in.
import test_lifecycle_state as _ls_fixtures  # noqa: E402


CAP_ID = "inbox_management"
BESPOKE_WRITER_RELPATH = "agents/inbox/runner.py"


def _write_pending_migrations(root, entries):
    d = Path(root) / "agents" / "handoffs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pending_migrations.json").write_text(
        json.dumps(entries, indent=2), encoding="utf-8")


def _bespoke_entry(writer_relpath=BESPOKE_WRITER_RELPATH, status="pending"):
    """A bespoke-writer migration entry, keyed on a relpath-derived mechanism_id
    with NO owning-capability field -- exactly the estate shape (the hand-rolled
    agents/inbox/runner.py bulk loop) that was invisible to the id-keyed views."""
    return {
        "mechanism_id": "runner",  # relpath-derived stem, NOT a capability id
        "writer_relpath": writer_relpath,
        "entrypoint_relpath": None,
        "status": status,
        "reason": "flagged non-conformant with the external-write gate on upgrade",
    }


def _canonical_entry(mechanism_id="some_other_capability", status="pending"):
    """A canonical-capability migration entry: writer_relpath is None. Must NOT
    trip the project-wide bespoke-writer block."""
    return {
        "mechanism_id": mechanism_id,
        "writer_relpath": None,
        "entrypoint_relpath": None,
        "status": status,
    }


class GlobalBespokeWriterBlockTests(_ls_fixtures._CheckCompletionFixtureMixin, unittest.TestCase):

    # -- RED / keystone: an open bespoke-writer entry blocks project-wide -------------------------

    def test_open_bespoke_writer_blocks_completion_and_overall(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # inbox_management is otherwise fully accepted/clean -> would be done/green.
            self._accept_real_capability(root, CAP_ID)
            _write_pending_migrations(root, [_bespoke_entry()])

            # capability_health --overall: NOT allowed, and names the bypass + writer path.
            overall = capability_health.overall_status(str(root))
            self.assertFalse(
                overall["normal_status_allowed"],
                f"an open bespoke-writer bypass must forbid normal status; got {overall}")
            blob = json.dumps(overall)
            self.assertIn("open_external_write_bypass", blob)
            self.assertIn(BESPOKE_WRITER_RELPATH, blob)

            # check_completion(inbox_management): NOT done, even though the bypass entry does not
            # resolve to inbox_management at all (attribution-free, project-wide).
            result = lifecycle_state.check_completion(str(root), CAP_ID)
            self.assertFalse(
                result.done,
                "an open bespoke-writer bypass must make check_completion non-done project-wide")
            self.assertIn("open_external_write_bypass", result.failed_conjuncts)
            self.assertIn(BESPOKE_WRITER_RELPATH, result.operator_message)
            self.assertNotIn("Traceback", result.operator_message)

    # -- GREEN / no over-firing: absent / canonical / closed entries do NOT block -----------------

    def test_no_bespoke_entry_is_green_and_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)
            # No pending_migrations.json at all.
            overall = capability_health.overall_status(str(root))
            self.assertTrue(overall["normal_status_allowed"], overall)
            self.assertNotIn("open_external_write_bypass", overall.get("red_capabilities", []))
            result = lifecycle_state.check_completion(str(root), CAP_ID)
            self.assertTrue(result.done, result.operator_message)
            self.assertNotIn("open_external_write_bypass", result.failed_conjuncts)

    def test_canonical_capability_entry_does_not_trip_global_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)
            # A canonical-capability entry (writer_relpath is None) for an unrelated mechanism must
            # NOT trigger the bespoke-writer project-wide block.
            _write_pending_migrations(root, [_canonical_entry()])
            overall = capability_health.overall_status(str(root))
            self.assertTrue(overall["normal_status_allowed"], overall)
            result = lifecycle_state.check_completion(str(root), CAP_ID)
            self.assertTrue(result.done, result.operator_message)
            self.assertNotIn("open_external_write_bypass", result.failed_conjuncts)

    def test_closed_bespoke_writer_entry_does_not_trip_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)
            # A bespoke-writer entry that is already resolved (status != "pending") is closed --
            # it must NOT keep the project non-green forever.
            _write_pending_migrations(root, [_bespoke_entry(status="resolved")])
            overall = capability_health.overall_status(str(root))
            self.assertTrue(overall["normal_status_allowed"], overall)
            result = lifecycle_state.check_completion(str(root), CAP_ID)
            self.assertTrue(result.done, result.operator_message)
            self.assertNotIn("open_external_write_bypass", result.failed_conjuncts)


if __name__ == "__main__":
    unittest.main()
