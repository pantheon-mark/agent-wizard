"""Task 3 / Cut 1.6 (bundle v0.20.0) -- the operator acknowledgement that is the
ONE sanctioned exit from ``WriterState.NEEDS_PERSON``.

The mechanism only stays honest if all four properties hold, so each has a test:
explicit (never automatic), HASH-BOUND (void the moment the file changes),
visible (still reported, still withholds the all-clear), and audited (a
committable record carrying the operator's own words).

``test_editing_the_file_voids_the_acknowledgement`` is the load-bearing one: it
is what stops an acknowledgement from laundering a FUTURE change to the file.

Run:  python3 -m unittest discover -s wizard/agents/lib/external_write \\
          -p test_writer_acknowledgement.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

_EXTERNAL_WRITE_DIR = Path(__file__).resolve().parent
_AGENTS_LIB = _EXTERNAL_WRITE_DIR.parent
if str(_AGENTS_LIB) not in sys.path:
    sys.path.insert(0, str(_AGENTS_LIB))

from external_write import _ext_write_state as ews          # noqa: E402
from external_write import writer_acknowledgement as ack    # noqa: E402

QUEUE_REL = "agents/handoffs/pending_migrations.json"
WRITER = "agents/upkeep/runner.py"
CONFIRMATION = "Yes -- I understand this one can't be fixed automatically and I accept the risk."

_UNREPAIRABLE_SRC = '''"""Daily upkeep -- also delivers the operator's phone alert."""
import urllib.request
'''


class _Project:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "agents" / "handoffs").mkdir(parents=True)

    def write_file(self, relpath, text):
        p = self.root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def queue_needs_person(self):
        (self.root / QUEUE_REL).write_text(json.dumps([{
            "mechanism_id": "agents_upkeep_runner",
            "writer_relpath": WRITER,
            "status": "pending",
            "paused_content_sha256": "0" * 64,
            "violations": [{"kind": "forbidden_import", "line": 2, "path": WRITER}],
        }], indent=2), encoding="utf-8")

    def close(self):
        self._tmp.cleanup()


class WriterAcknowledgementTests(unittest.TestCase):

    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)
        self.p.write_file(WRITER, _UNREPAIRABLE_SRC)
        self.p.queue_needs_person()

    def _root(self):
        return str(self.p.root)

    # ------------------------------------------------------- the happy path

    def test_acknowledging_moves_it_out_of_the_blocking_set(self):
        self.assertEqual(
            ews.classify_bespoke_writer_entry(
                self._root(), ews.open_bespoke_writer_migrations(self._root())[0]),
            ews.WriterState.NEEDS_PERSON)
        self.assertEqual(len(ews.blocking_bespoke_writer_migrations(self._root())), 1)

        ack.acknowledge_writer(self._root(), WRITER, operator_confirmation=CONFIRMATION)

        self.assertEqual(
            ews.classify_bespoke_writer_entry(
                self._root(), ews.open_bespoke_writer_migrations(self._root())[0]),
            ews.WriterState.ACKNOWLEDGED_RISK)
        self.assertEqual(ews.blocking_bespoke_writer_migrations(self._root()), [])

    def test_the_record_is_audited_and_carries_the_operators_own_words(self):
        ack.acknowledge_writer(self._root(), WRITER, operator_confirmation=CONFIRMATION)
        stored = json.loads(
            (self.p.root / ack.ACKNOWLEDGEMENTS_REL).read_text(encoding="utf-8"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["writer_relpath"], WRITER)
        self.assertEqual(stored[0]["operator_confirmation"], CONFIRMATION)
        self.assertTrue(stored[0]["content_sha256"])
        self.assertTrue(stored[0]["acknowledged_at"])

    def test_acknowledging_is_idempotent_per_writer(self):
        ack.acknowledge_writer(self._root(), WRITER, operator_confirmation=CONFIRMATION)
        ack.acknowledge_writer(self._root(), WRITER, operator_confirmation="Yes, still fine.")
        stored = json.loads(
            (self.p.root / ack.ACKNOWLEDGEMENTS_REL).read_text(encoding="utf-8"))
        self.assertEqual(len(stored), 1, "re-acknowledging must replace, not accumulate")
        self.assertEqual(stored[0]["operator_confirmation"], "Yes, still fine.")

    # ------------------------------------------- HASH-BOUND (load-bearing)

    def test_editing_the_file_voids_the_acknowledgement(self):
        """THE LOAD-BEARING TEST. An acknowledgement must never launder a FUTURE
        change: the operator accepted the risk of THIS file as it stood. Change
        the bytes and it blocks again until a person looks afresh."""
        ack.acknowledge_writer(self._root(), WRITER, operator_confirmation=CONFIRMATION)
        self.assertEqual(ews.blocking_bespoke_writer_migrations(self._root()), [])

        self.p.write_file(WRITER, _UNREPAIRABLE_SRC + "\n# something new happens here\n")

        self.assertEqual(
            ews.classify_bespoke_writer_entry(
                self._root(), ews.open_bespoke_writer_migrations(self._root())[0]),
            ews.WriterState.NEEDS_PERSON,
            "an edited file must fall back to needs_person")
        self.assertEqual(len(ews.blocking_bespoke_writer_migrations(self._root())), 1)

    def test_a_voided_record_is_kept_on_disk_as_audit_history(self):
        ack.acknowledge_writer(self._root(), WRITER, operator_confirmation=CONFIRMATION)
        self.p.write_file(WRITER, _UNREPAIRABLE_SRC + "\n# changed\n")
        stored = json.loads(
            (self.p.root / ack.ACKNOWLEDGEMENTS_REL).read_text(encoding="utf-8"))
        self.assertEqual(len(stored), 1, "history is kept, not silently deleted")
        self.assertEqual(ack.active_acknowledgements(self._root()), {},
                         "but it is no longer ACTIVE")

    # ------------------------------------------------------- VISIBLE, not gone

    def test_an_acknowledged_writer_is_still_open_and_still_withholds_the_all_clear(self):
        from external_write import capability_health as ch
        ack.acknowledge_writer(self._root(), WRITER, operator_confirmation=CONFIRMATION)

        self.assertEqual(len(ews.open_bespoke_writer_migrations(self._root())), 1,
                         "acknowledged is not resolved -- the entry stays open")
        status = ch.overall_status(self._root())
        self.assertFalse(status["open_external_write_bypass"]["blocking"])
        self.assertFalse(status["normal_status_allowed"],
                         "an acknowledged risk must still withhold the all-clear")
        self.assertEqual(
            status["open_external_write_bypass"]["writer_states"][WRITER],
            ews.WriterState.ACKNOWLEDGED_RISK)

    # ------------------------------------------------------------ FAIL CLOSED

    def test_blank_confirmation_refuses_and_writes_nothing(self):
        for blank in ("", "   ", "\t"):
            with self.assertRaises(ack.WriterAcknowledgementError):
                ack.acknowledge_writer(self._root(), WRITER, operator_confirmation=blank)
        self.assertFalse((self.p.root / ack.ACKNOWLEDGEMENTS_REL).exists())
        self.assertEqual(len(ews.blocking_bespoke_writer_migrations(self._root())), 1)

    def test_multiline_confirmation_refuses(self):
        """Paste-safety, mirroring the typed-identity rule's F-2 acceptance rule: a line-split
        paste may be truncated, so what the operator 'said' cannot be trusted."""
        with self.assertRaises(ack.WriterAcknowledgementError):
            ack.acknowledge_writer(self._root(), WRITER,
                                   operator_confirmation="Yes I accept\nthe risk")
        self.assertFalse((self.p.root / ack.ACKNOWLEDGEMENTS_REL).exists())

    def test_acknowledging_an_unflagged_file_refuses(self):
        """No orphan records, and no pre-acknowledging a file that is not
        flagged -- that would be a standing waiver for future violations."""
        self.p.write_file("agents/other/thing.py", "x = 1\n")
        with self.assertRaises(ack.WriterAcknowledgementError):
            ack.acknowledge_writer(self._root(), "agents/other/thing.py",
                                   operator_confirmation=CONFIRMATION)

    def test_acknowledging_an_unreadable_file_refuses(self):
        with self.assertRaises(ack.WriterAcknowledgementError):
            ack.acknowledge_writer(self._root(), "agents/gone/missing.py",
                                   operator_confirmation=CONFIRMATION)

    def test_a_corrupt_record_store_keeps_it_blocking(self):
        """Fail-closed: an unreadable acknowledgement store must never present
        as 'acknowledged'."""
        (self.p.root / ack.ACKNOWLEDGEMENTS_REL).parent.mkdir(parents=True, exist_ok=True)
        (self.p.root / ack.ACKNOWLEDGEMENTS_REL).write_text("{not json", encoding="utf-8")
        self.assertEqual(len(ews.blocking_bespoke_writer_migrations(self._root())), 1)

    def test_the_wiring_into_the_classifier_is_live(self):
        """Guards the lazy import in ``_ext_write_state._active_acknowledgement_
        relpaths``: if this module were renamed or dropped, that ImportError
        fallback would silently return 'no acknowledgements' forever and this
        exit would quietly stop working."""
        self.assertEqual(ews._active_acknowledgement_relpaths(self._root()), set())
        ack.acknowledge_writer(self._root(), WRITER, operator_confirmation=CONFIRMATION)
        self.assertEqual(ews._active_acknowledgement_relpaths(self._root()), {WRITER})


if __name__ == "__main__":
    unittest.main()
