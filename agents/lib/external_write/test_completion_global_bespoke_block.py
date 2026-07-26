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


# A still-bespoke per-chunk mint loop -- the REAL writer an open bespoke-writer entry points at.
# (Cut 1.5 / v0.19.0, Task B composition) The Task-B auto-reap runs inside reconcile_state (which
# capability_health.overall_status / check_completion drive fail-safe), and it treats a
# bespoke-writer entry whose writer file NO LONGER EXISTS as resolved -> reaped. So an "open
# bypass" fixture must put the writer file ON DISK, or the composed system correctly reaps it and
# reports green. This entry carries no paused_content_sha256, so the reap's fail-closed
# "no pause-time baseline -> keep" branch holds the entry regardless of the file's content; the
# still-bespoke content below keeps it realistic (a genuine, unmigrated bypass writer).
_BESPOKE_RUNNER_SRC = '''"""Hand-rolled per-chunk bulk writer -- bypasses run_sanctioned_bulk."""
from external_write.run_envelope import mint_run_envelope


def run_all(chunks):
    return [mint_run_envelope(chunk) for chunk in chunks]
'''


def _write_bespoke_writer_file(root, writer_relpath=BESPOKE_WRITER_RELPATH):
    """Put the entry's writer file on disk so the fixture models a REAL open bypass (see
    _BESPOKE_RUNNER_SRC) rather than an entry pointing at a vanished file (which Task B's reap
    correctly clears)."""
    p = Path(root) / writer_relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_BESPOKE_RUNNER_SRC, encoding="utf-8")


def _canonical_entry(mechanism_id="some_other_capability", status="pending"):
    """A canonical-capability migration entry: writer_relpath is None. Must NOT
    trip the project-wide bespoke-writer block."""
    return {
        "mechanism_id": mechanism_id,
        "writer_relpath": None,
        "entrypoint_relpath": None,
        "status": status,
    }


RECONCILE_INCOMPLETE_RELPATH = "agents/handoffs/pending_migrations.json"


def _reconcile_incomplete_entry():
    """The shape ``upgrade_reconcile.record_reconcile_incomplete`` writes when the upgrade
    safety check itself could not finish. Its ``writer_relpath`` deliberately points at the
    pending-migrations queue file itself (so it still trips the non-empty-``writer_relpath``
    blocking predicate) -- it is not a bespoke writer to rebuild, and must not be described
    as one."""
    return {
        "mechanism_id": "upgrade_safety_check",
        "writer_relpath": RECONCILE_INCOMPLETE_RELPATH,
        "entrypoint_relpath": None,
        "kind": "reconcile_incomplete",
        "reason": (
            "the upgrade safety check could not finish, so this project has not been "
            "confirmed safe to run (RuntimeError)"),
        "suggested_next_step": (
            "Ask your assistant to run `wizard reconcile`. That re-runs the same safety "
            "check against what is installed now. This entry clears by itself once the "
            "check completes."),
        "status": "pending",
    }


class GlobalBespokeWriterBlockTests(_ls_fixtures._CheckCompletionFixtureMixin, unittest.TestCase):

    # -- RED / keystone: an open bespoke-writer entry blocks project-wide -------------------------

    def test_open_bespoke_writer_blocks_completion_and_overall(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # inbox_management is otherwise fully accepted/clean -> would be done/green.
            self._accept_real_capability(root, CAP_ID)
            # A REAL open bypass: the writer file exists on disk and is still bespoke (see
            # _write_bespoke_writer_file) -- so the Task-B auto-reap does NOT clear it.
            _write_bespoke_writer_file(root)
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

    # -- Kind-aware rendering: an entry that is not a bespoke-writer bypass must still
    # block (blocking stays kind-free), but must not be DESCRIBED as one ----------------

    def test_reconcile_incomplete_marker_blocks_but_is_not_described_as_a_bypass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)
            _write_pending_migrations(root, [_reconcile_incomplete_entry()])

            overall = capability_health.overall_status(str(root))

            # Blocking is unaffected by kind: this still forbids normal status, exactly like a
            # real bypass would.
            self.assertFalse(
                overall["normal_status_allowed"],
                f"an incomplete upgrade safety check must forbid normal status; got {overall}")
            bypass = overall["open_external_write_bypass"]
            self.assertTrue(bypass["blocking"])
            self.assertIn(RECONCILE_INCOMPLETE_RELPATH, bypass["writer_relpaths"])

            # But the TEXT must speak for itself, not the generic bypass sentence -- rebuilding
            # the queue file itself "so it routes through the sanctioned bulk path" is meaningless.
            description = bypass["descriptions"][RECONCILE_INCOMPLETE_RELPATH]
            self.assertNotIn("routes through the sanctioned bulk path", description)
            self.assertNotIn("an external-write bypass is unrepaired", description)
            self.assertIn("wizard reconcile", description)

    def test_a_genuine_bypass_descriptions_wording_is_unchanged(self):
        """Regression guard: a REAL bespoke-writer bypass entry must keep the exact rebuild
        wording it has always had in the new ``descriptions`` field too."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)
            _write_bespoke_writer_file(root)
            _write_pending_migrations(root, [_bespoke_entry()])

            overall = capability_health.overall_status(str(root))

            description = overall["open_external_write_bypass"]["descriptions"][
                BESPOKE_WRITER_RELPATH]
            self.assertEqual(
                description,
                "an external-write bypass is unrepaired: `agents/inbox/runner.py` -- rebuild "
                "it so it routes through the sanctioned bulk path")


if __name__ == "__main__":
    unittest.main()


class BlockingSubsetTests(_ls_fixtures._CheckCompletionFixtureMixin, unittest.TestCase):
    """Cut 1.6 / Task 2 -- completion and health key on the BLOCKING SUBSET.

    The keystone above is unchanged: presence of an unresolved LIVE bypass still
    blocks project-wide, attribution-free. What changes is which entries are
    ADMITTED to the blocking set. Before this cut, a test module -- whose
    violations are intrinsic to testing the write path -- blocked acceptance for
    every capability in the project, forever (4 of the estate's 7 real entries
    were exactly this, and none of them could ever be reaped)."""

    _NON_LIVE_RELPATH = "agents/inbox/test_inbox_bulk.py"

    def _write_non_live_test_module(self, root):
        p = root / self._NON_LIVE_RELPATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "import unittest\n"
            "from external_write.adapters_inbox import InboxAdapter\n\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_x(self):\n        self.assertTrue(InboxAdapter)\n",
            encoding="utf-8")

    def test_non_live_test_module_does_not_block_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)
            self._write_non_live_test_module(root)
            _write_pending_migrations(root, [
                _bespoke_entry(writer_relpath=self._NON_LIVE_RELPATH)])

            result = lifecycle_state.check_completion(str(root), CAP_ID)
            self.assertTrue(
                result.done,
                f"a non-live test module must not block completion: {result.operator_message}")
            self.assertNotIn("open_external_write_bypass", result.failed_conjuncts)

    def test_non_live_test_module_is_still_reported_and_withholds_the_all_clear(self):
        """Not blocking must never mean invisible. The operator is still told."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)
            self._write_non_live_test_module(root)
            _write_pending_migrations(root, [
                _bespoke_entry(writer_relpath=self._NON_LIVE_RELPATH)])

            overall = capability_health.overall_status(str(root))
            self.assertFalse(overall["normal_status_allowed"],
                             "an open non-live entry must still withhold the all-clear")
            self.assertFalse(overall["open_external_write_bypass"]["blocking"])
            self.assertIn(self._NON_LIVE_RELPATH,
                          overall["open_external_write_bypass"]["writer_relpaths"])
            self.assertEqual(
                overall["open_external_write_bypass"]["writer_states"][self._NON_LIVE_RELPATH],
                "non_live")

    def test_a_real_live_writer_alongside_it_still_blocks(self):
        """No over-correction: adding a non-live entry must not mask a real one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)
            self._write_non_live_test_module(root)
            _write_bespoke_writer_file(root)
            _write_pending_migrations(root, [
                _bespoke_entry(writer_relpath=self._NON_LIVE_RELPATH),
                _bespoke_entry(),
            ])

            result = lifecycle_state.check_completion(str(root), CAP_ID)
            self.assertFalse(result.done)
            self.assertIn("open_external_write_bypass", result.failed_conjuncts)
            overall = capability_health.overall_status(str(root))
            self.assertTrue(overall["open_external_write_bypass"]["blocking"])
            self.assertIn(BESPOKE_WRITER_RELPATH,
                          overall["open_external_write_bypass"]["blocking_writer_relpaths"])
            self.assertNotIn(self._NON_LIVE_RELPATH,
                             overall["open_external_write_bypass"]["blocking_writer_relpaths"])
