"""Task B / Cut 1.5 (bundle v0.19.0) -- stateless auto-reap of a RESOLVED
bespoke-writer migration entry.

Task A (KEYSTONE) makes an OPEN bespoke-writer entry block the whole project
non-green. Task B is the mechanism that CLEARS such an entry once the writer is
genuinely fixed, so a resolved project stops being held non-green forever.

Locked design (authoritative): a bespoke-writer entry is reaped (REMOVED from
``agents/handoffs/pending_migrations.json``) iff
    (the writer file no longer exists) OR
    (current file hash != recorded ``paused_content_sha256`` AND the file passes
     ``scan_paths`` run with the pending-migration quarantine DISABLED).
Stateless -- no capability join. Runs inside ``lifecycle_state.reconcile_state``
(fail-safe self-heal on read). The three cases below assert the reap via the
Task-A predicate ``open_bespoke_writer_migrations`` count AFTER a
``reconcile_state`` call.

Run:  python3 -m unittest discover -s wizard/agents/lib/external_write \\
          -p test_writer_migration_autoreap.py
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

_EXTERNAL_WRITE_DIR = Path(__file__).resolve().parent
_AGENTS_LIB = _EXTERNAL_WRITE_DIR.parent  # agents/lib -- external_write is a package under here
if str(_AGENTS_LIB) not in sys.path:
    sys.path.insert(0, str(_AGENTS_LIB))

from external_write import lifecycle_state  # noqa: E402
# Name-form import (NOT ``from external_write._ext_write_state import ...``): the whole-package
# bypass scan (test_external_write_scan) asserts every .py under this dir -- test files included --
# is violation-free, and the dotted-submodule form trips the CAPABILITY-zone sealed_kernel_import
# rule. Every other test file here uses the same name form for the same reason.
from external_write import _ext_write_state  # noqa: E402

open_bespoke_writer_migrations = _ext_write_state.open_bespoke_writer_migrations
reap_resolved_writer_migrations = _ext_write_state.reap_resolved_writer_migrations

# The harness capability the reconcile_state call is keyed on. Its module file just has to EXIST
# so build_capability_index can resolve the module_stem -- the reap it triggers is project-wide
# and attribution-free (independent of this capability).
HARNESS_CAP_ID = "harness"

# The estate's real shape: a hand-rolled bulk runner OUTSIDE agents/capabilities/, keyed on a
# relpath-derived mechanism_id with no owning capability.
BESPOKE_WRITER_RELPATH = "agents/inbox/runner.py"
BESPOKE_MECHANISM_ID = "runner"

# A hand-rolled per-chunk mint loop: imports mint_run_envelope directly from run_envelope
# (a SEALED_KERNEL submodule NOT on the CAPABILITY allowlist) -- doubly scanner-RED
# (sealed_kernel_import + the raw bulk-mint name ban). This is the writer the entry exists for.
_BESPOKE_RUNNER_SRC = '''"""Hand-rolled per-chunk bulk writer -- bypasses run_sanctioned_bulk."""
from external_write.run_envelope import mint_run_envelope


def run_all(chunks):
    results = []
    for chunk in chunks:
        env = mint_run_envelope(chunk)
        results.append(env)
    return results
'''

# The migrated shape: routes the bulk write through the sanctioned run_sanctioned_bulk path,
# imported from capability_api (an allowlisted CAPABILITY-zone submodule) -- scanner-CLEAN.
_SANCTIONED_RUNNER_SRC = '''"""Migrated -- routes the bulk write through the sanctioned path."""
from external_write.capability_api import run_sanctioned_bulk


def run_all(facade, batch_id, operations):
    return run_sanctioned_bulk(facade, batch_id, operations)
'''

_TRIVIAL_CAPABILITY_SRC = '''"""Trivial harness capability -- exists only so reconcile_state can resolve it."""

OP_KIND = "delete_record"


def describe():
    return "harness ready"


def propose_operations(facade, batch_id):
    return []
'''


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_queue(root: Path, entries) -> None:
    _write(root / "agents" / "handoffs" / "pending_migrations.json",
           json.dumps(entries, indent=2))


def _bespoke_entry(paused_content_sha256):
    """A bespoke-writer entry keyed on a relpath-derived mechanism_id with no owning capability
    (exactly the estate shape). ``paused_content_sha256`` is the pause-time content hash the reap
    compares the current file against."""
    return {
        "mechanism_id": BESPOKE_MECHANISM_ID,
        "writer_relpath": BESPOKE_WRITER_RELPATH,
        "entrypoint_relpath": None,
        "status": "pending",
        "reason": "flagged non-conformant with the external-write gate on upgrade",
        "paused_content_sha256": paused_content_sha256,
    }


def _seed_harness(root: Path) -> None:
    """Write the trivial capability module reconcile_state is keyed on."""
    _write(root / "agents" / "capabilities" / f"{HARNESS_CAP_ID}_capability.py",
           _TRIVIAL_CAPABILITY_SRC)


class WriterMigrationAutoReapTests(unittest.TestCase):

    # -- case (a) writer file DELETED -> reaped -------------------------------------------------

    def test_deleted_writer_is_reaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_harness(root)
            # entry present, but the writer file was never created (it is gone).
            _write_queue(root, [_bespoke_entry(paused_content_sha256=_sha256(_BESPOKE_RUNNER_SRC))])
            self.assertEqual(len(open_bespoke_writer_migrations(str(root))), 1)

            lifecycle_state.reconcile_state(str(root), HARNESS_CAP_ID)

            self.assertEqual(
                len(open_bespoke_writer_migrations(str(root))), 0,
                "a bespoke-writer entry whose writer file no longer exists must be reaped")

    # -- case (b) writer REWRITTEN to route through run_sanctioned_bulk -> reaped ----------------

    def test_rewritten_scan_clean_writer_is_reaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_harness(root)
            # The file on disk is the MIGRATED (scan-clean) version; the recorded pause-time hash
            # is the OLD bespoke content, so current hash != recorded AND the file scans clean.
            _write(root / BESPOKE_WRITER_RELPATH, _SANCTIONED_RUNNER_SRC)
            _write_queue(root, [_bespoke_entry(paused_content_sha256=_sha256(_BESPOKE_RUNNER_SRC))])
            self.assertEqual(len(open_bespoke_writer_migrations(str(root))), 1)

            lifecycle_state.reconcile_state(str(root), HARNESS_CAP_ID)

            self.assertEqual(
                len(open_bespoke_writer_migrations(str(root))), 0,
                "a rewritten writer that now passes the (non-quarantined) scan must be reaped")

    # -- case (c) writer UNCHANGED (still per-chunk mint) -> NOT reaped --------------------------

    def test_unchanged_bespoke_writer_is_not_reaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_harness(root)
            # The file on disk is STILL the bespoke per-chunk mint loop; recorded hash matches
            # current hash -> unchanged -> must stay pending (still an open bypass).
            _write(root / BESPOKE_WRITER_RELPATH, _BESPOKE_RUNNER_SRC)
            _write_queue(root, [_bespoke_entry(paused_content_sha256=_sha256(_BESPOKE_RUNNER_SRC))])
            self.assertEqual(len(open_bespoke_writer_migrations(str(root))), 1)

            lifecycle_state.reconcile_state(str(root), HARNESS_CAP_ID)

            still_open = open_bespoke_writer_migrations(str(root))
            self.assertEqual(
                len(still_open), 1,
                "an unchanged, still-bespoke writer must NOT be reaped (it is still a live bypass)")
            self.assertEqual(still_open[0].get("writer_relpath"), BESPOKE_WRITER_RELPATH)

    # -- case (d) writer EDITED but STILL bespoke -> NOT reaped (scan-branch fail-open guard) ------

    def test_edited_but_still_bespoke_writer_is_not_reaped(self):
        """The most safety-critical branch: the operator EDITED the writer (its hash now DIFFERS
        from the recorded paused_content_sha256, so the hash-match short-circuit is bypassed and
        the reap DOES reach the scan branch), but the edit did NOT migrate it -- it is still a
        per-chunk mint_run_envelope bypass (scan-RED). It MUST stay pending. If scan_paths ever
        returned empty for this out-of-package path, this writer would be falsely reaped -- a
        re-introduced false green. This test pins the guard: hash-changed alone never reaps; the
        (non-quarantined) scan must ALSO be clean."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_harness(root)
            # Recorded pause-time hash is the ORIGINAL bespoke content; the file on disk is an
            # EDITED-but-still-bespoke variant (different bytes -> different sha256, but still a
            # scan-RED per-chunk mint loop).
            edited_bespoke = _BESPOKE_RUNNER_SRC.replace(
                "results = []", "results = []  # operator tweaked a comment; still a bypass")
            self.assertNotEqual(_sha256(edited_bespoke), _sha256(_BESPOKE_RUNNER_SRC))
            _write(root / BESPOKE_WRITER_RELPATH, edited_bespoke)
            _write_queue(root, [_bespoke_entry(paused_content_sha256=_sha256(_BESPOKE_RUNNER_SRC))])
            self.assertEqual(len(open_bespoke_writer_migrations(str(root))), 1)

            lifecycle_state.reconcile_state(str(root), HARNESS_CAP_ID)

            still_open = open_bespoke_writer_migrations(str(root))
            self.assertEqual(
                len(still_open), 1,
                "an edited-but-still-bespoke (scan-RED) writer must NOT be reaped even though its "
                "hash changed -- the scan branch must catch it (fail-closed against a false green)")
            self.assertEqual(still_open[0].get("writer_relpath"), BESPOKE_WRITER_RELPATH)

    # -- direct-function coverage of the reaped-id return value ----------------------------------

    def test_reap_returns_reaped_mechanism_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_harness(root)
            _write(root / BESPOKE_WRITER_RELPATH, _SANCTIONED_RUNNER_SRC)
            _write_queue(root, [_bespoke_entry(paused_content_sha256=_sha256(_BESPOKE_RUNNER_SRC))])

            reaped = reap_resolved_writer_migrations(str(root))
            self.assertEqual(reaped, [BESPOKE_MECHANISM_ID])
            # Idempotent: a second reap over the now-empty queue reaps nothing.
            self.assertEqual(reap_resolved_writer_migrations(str(root)), [])


if __name__ == "__main__":
    unittest.main()
