"""Task 3 / Cut 1.6 (bundle v0.20.0) -- the operator acknowledgement that is the
ONE sanctioned exit from ``WriterState.NEEDS_PERSON``.

The mechanism only stays honest if all four properties hold, so each has a test:
explicit (never automatic), HASH-BOUND (void the moment the file changes),
visible (still reported, still withholds the all-clear), and audited (a
committable record carrying the operator's own words).

``test_editing_the_file_voids_the_acknowledgement`` is the load-bearing one: it
is what stops an acknowledgement from laundering a FUTURE change to the file.

A fifth property was added later, after the four above were found not to be
enough on their own: **ELIGIBLE**. The decision is the exit from exactly one
structural state, and it is refused everywhere else and inert everywhere else --
two separate enforcements, because a record can reach the store without passing
through the command. See the section header further down for what went wrong
without it; in short, all four properties above held perfectly while a decision
recorded against a REBUILDABLE writer skipped its rebuild.

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
from external_write import writer_ack_store as store        # noqa: E402
from external_write import writer_acknowledgement as ack    # noqa: E402

QUEUE_REL = "agents/handoffs/pending_migrations.json"
WRITER = "agents/upkeep/runner.py"
CONFIRMATION = "Yes -- I understand this one can't be fixed automatically and I accept the risk."

#: A writer whose every recorded violation IS one our own remediator covers, so
#: the honest answer is "we can fix this" -- it is REBUILDABLE, and a rebuild is
#: its exit, not a recorded decision to leave it alone.
REBUILDABLE = "agents/inbox/runner.py"

#: A test module nothing in the running system invokes -- non_live, already out of
#: the blocking set, so there is nothing for a decision to release.
NON_LIVE_WRITER = "agents/inbox/test_bulk_writer.py"

_UNREPAIRABLE_SRC = '''"""Daily upkeep -- also delivers the operator's phone alert."""
import urllib.request
'''

_REBUILDABLE_SRC = '''"""A hand-rolled per-chunk bulk write loop."""
from external_write.adapters_thing import build_read_only_client
'''

_NON_LIVE_SRC = '''"""Tests for the write path."""
import unittest


class TestWritePath(unittest.TestCase):
    def test_apply(self):
        self.assertTrue(True)
'''


def _entry(relpath, kinds):
    """A pending bespoke-writer queue entry in the reconcile's real on-disk
    shape. The recorded violation KINDS are what drive the structural state."""
    return {
        "mechanism_id": relpath.replace("/", "_").replace(".py", ""),
        "writer_relpath": relpath,
        "status": "pending",
        "paused_content_sha256": "0" * 64,
        "violations": [{"kind": k, "line": 2, "path": relpath} for k in kinds],
    }


def _needs_person_entry(relpath=WRITER):
    """``forbidden_import`` is recorded against it and no remediator of ours
    rewrites that, which is what makes the structural state ``needs_person``."""
    return _entry(relpath, ["forbidden_import"])


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

    def write_bytes(self, relpath, raw):
        p = self.root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        return p

    def write_queue(self, entries):
        (self.root / QUEUE_REL).write_text(json.dumps(entries, indent=2),
                                           encoding="utf-8")

    def queue_needs_person(self):
        self.write_queue([_needs_person_entry()])

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


# ---------------------------------------------------------------------------
# ELIGIBILITY: the decision applies to ONE structural state, and to nothing else.
#
# The bug this closes was an authorization bypass with entirely GENUINE operator
# consent, which is why no consent guard could ever have caught it: the command
# gated on membership in the OPEN set, and the classifier tested the record FIRST,
# short-circuiting every other state. So a decision recorded against a fully
# REBUILDABLE writer removed it from the blocking set and the rebuild never had to
# happen. It never fired in the field only because the command had no operator
# surface -- an undiscoverable mechanism cannot be misused, which meant a
# discoverability gap was the only thing standing in for an authorization rule.
#
# BOTH halves are needed and neither substitutes for the other:
#   * the COMMAND refuses to record a decision about a writer that is not in the
#     one state the decision is for;
#   * the CLASSIFIER applies a recorded decision only to that same state, so a
#     record that arrived some other way is INERT rather than trusted.
# Guard-only would leave a hand-written record able to move the blocking set;
# classifier-only would let the surface write a record it then quietly ignores.
# ---------------------------------------------------------------------------

class EligibilityIsNeedsPersonOnlyTests(unittest.TestCase):
    """The command records a decision only where a decision is the exit."""

    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)

    def _root(self):
        return str(self.p.root)

    def _state(self, relpath):
        entry = [e for e in ews.open_bespoke_writer_migrations(self._root())
                 if e.get("writer_relpath") == relpath][0]
        return ews.classify_bespoke_writer_entry(self._root(), entry)

    def _refusal(self, relpath, confirmation=CONFIRMATION):
        with self.assertRaises(ack.WriterAcknowledgementError) as raised:
            ack.acknowledge_writer(self._root(), relpath,
                                   operator_confirmation=confirmation)
        self.assertFalse((self.p.root / ack.ACKNOWLEDGEMENTS_REL).exists(),
                         "a refused acknowledgement must write NOTHING")
        return str(raised.exception)

    # ------------------------------------------------- the eligible state works

    def test_a_needs_person_writer_is_still_acknowledgeable(self):
        """The legitimate path, unchanged: the operator whose writer genuinely
        needs a person is who this mechanism exists for."""
        self.p.write_file(WRITER, _UNREPAIRABLE_SRC)
        self.p.queue_needs_person()
        self.assertEqual(self._state(WRITER), ews.WriterState.NEEDS_PERSON)

        record = ack.acknowledge_writer(self._root(), WRITER,
                                        operator_confirmation=CONFIRMATION)
        self.assertEqual(record["writer_relpath"], WRITER)
        self.assertEqual(self._state(WRITER), ews.WriterState.ACKNOWLEDGED_RISK)
        self.assertEqual(ews.blocking_bespoke_writer_migrations(self._root()), [])

    # -------------------------------------------------- every other state refuses

    def test_a_rebuildable_writer_cannot_be_acknowledged(self):
        """THE BYPASS. Every violation recorded against this writer is one our own
        remediator covers, so a rebuild WILL clear it -- and accepting the risk
        instead would skip the rebuild entirely with the operator's real consent."""
        self.p.write_file(REBUILDABLE, _REBUILDABLE_SRC)
        self.p.write_queue([_entry(REBUILDABLE, ["sealed_kernel_import",
                                                 "adapter_module_import"])])
        self.assertEqual(self._state(REBUILDABLE),
                         ews.WriterState.BLOCKING_LIVE_ENABLE)

        reason = self._refusal(REBUILDABLE)
        self.assertIn("nothing was recorded", reason)
        self.assertIn("sanctioned bulk path", reason,
                      "the refusal must name the repair that DOES clear this one")
        self.assertEqual(len(ews.blocking_bespoke_writer_migrations(self._root())), 1,
                         "it must still be blocking after the refusal")

    def test_a_non_live_writer_cannot_be_acknowledged(self):
        """A test module nothing invokes is already out of the blocking set, so
        there is no risk to accept and nothing to release. Recording a decision
        here would be an audit record about a non-event."""
        self.p.write_file(NON_LIVE_WRITER, _NON_LIVE_SRC)
        self.p.write_queue([_entry(NON_LIVE_WRITER, ["sealed_kernel_import"])])
        self.assertEqual(self._state(NON_LIVE_WRITER), ews.WriterState.NON_LIVE)

        reason = self._refusal(NON_LIVE_WRITER)
        self.assertIn("nothing was recorded", reason)
        self.assertIn("test file", reason)

    def test_an_entry_recording_no_violations_cannot_be_acknowledged(self):
        """Nothing recorded means nothing established -- the state is fail-closed
        BLOCKING, not "a person is needed". A decision must not be the exit from a
        state we could not classify."""
        self.p.write_file(REBUILDABLE, _REBUILDABLE_SRC)
        self.p.write_queue([_entry(REBUILDABLE, [])])
        self.assertEqual(self._state(REBUILDABLE),
                         ews.WriterState.BLOCKING_LIVE_ENABLE)
        self._refusal(REBUILDABLE)

    def test_a_writer_readable_as_bytes_but_not_as_text_cannot_be_acknowledged(self):
        """The case that separates the two halves. The file reads as BYTES, so a
        hash can be bound to it and the command's own hash check passes -- but the
        classifier cannot read it as text, so it could never honour the record.
        Without the guard the surface writes a record it then silently ignores."""
        self.p.write_bytes(WRITER,
                           b'"""upkeep"""\nimport urllib.request\n# \xff\xfe\n')
        self.p.queue_needs_person()
        self.assertEqual(self._state(WRITER), ews.WriterState.BLOCKING_LIVE_ENABLE)
        self._refusal(WRITER)

    # -------------------------------------------------------- ORDER is preserved

    def test_an_unusable_confirmation_is_still_reported_before_eligibility(self):
        """What the operator reads about their own paste must not depend on what
        state the file turned out to be in."""
        self.p.write_file(REBUILDABLE, _REBUILDABLE_SRC)
        self.p.write_queue([_entry(REBUILDABLE, ["sealed_kernel_import"])])
        self.assertIn("in your own words", self._refusal(REBUILDABLE, "   "))
        self.assertIn("split across lines",
                      self._refusal(REBUILDABLE, "Yes I accept\nthe risk"))


class AmbiguousMultiEntryTests(unittest.TestCase):
    """``open_bespoke_writer_migrations`` guarantees NO uniqueness on the writer
    relpath, and two entries naming one file can record different violations and
    therefore land in different states. A decision is keyed on the PATH, so it
    cannot say which of them it accepted -- refuse, fail-closed, rather than
    picking a best or first match."""

    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)
        self.p.write_file(WRITER, _UNREPAIRABLE_SRC)

    def _root(self):
        return str(self.p.root)

    def _refuses(self):
        with self.assertRaises(ack.WriterAcknowledgementError) as raised:
            ack.acknowledge_writer(self._root(), WRITER,
                                   operator_confirmation=CONFIRMATION)
        self.assertFalse((self.p.root / ack.ACKNOWLEDGEMENTS_REL).exists())
        return str(raised.exception)

    def test_a_mixed_pair_refuses_with_the_eligible_entry_first(self):
        self.p.write_queue([_needs_person_entry(),
                            _entry(WRITER, ["sealed_kernel_import"])])
        self.assertEqual(len(ews.open_bespoke_writer_migrations(self._root())), 2)
        self.assertIn("more than one", self._refuses())

    def test_a_mixed_pair_refuses_with_the_eligible_entry_second(self):
        """The same pair in the other order. A first-match or best-match rule
        passes exactly one of these two tests, which is why both exist."""
        self.p.write_queue([_entry(WRITER, ["sealed_kernel_import"]),
                            _needs_person_entry()])
        self.assertIn("more than one", self._refuses())

    def test_a_matching_pair_that_agrees_is_still_accepted(self):
        """No over-firing: duplicate entries that agree are not ambiguous, and
        refusing them would strand the operator with no exit at all."""
        self.p.write_queue([_needs_person_entry(),
                            _entry(WRITER, ["forbidden_import",
                                            "introspection_escape_hatch"])])
        ack.acknowledge_writer(self._root(), WRITER,
                               operator_confirmation=CONFIRMATION)
        self.assertEqual(ews.blocking_bespoke_writer_migrations(self._root()), [])

    def test_an_unrelated_second_entry_does_not_make_it_ambiguous(self):
        """Only entries naming THIS file are consulted. A different writer's
        entry, in any state, is none of this decision's business."""
        self.p.write_file(REBUILDABLE, _REBUILDABLE_SRC)
        self.p.write_queue([_needs_person_entry(),
                            _entry(REBUILDABLE, ["sealed_kernel_import"])])
        ack.acknowledge_writer(self._root(), WRITER,
                               operator_confirmation=CONFIRMATION)
        self.assertEqual([e["writer_relpath"]
                          for e in ews.blocking_bespoke_writer_migrations(self._root())],
                         [REBUILDABLE])


class ForgedRecordIsInertTests(unittest.TestCase):
    """The half the command's guard cannot provide. A record written STRAIGHT TO
    THE STORE never passes through the command, so the guard is not in its path at
    all -- and a record can arrive that way (the store is a plain JSON file in the
    project, and the sibling-import boundary check does not catch every route to
    it). The classifier is therefore the thing that has to make such a record
    inert, and this is the test that proves the two halves compose."""

    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)

    def _root(self):
        return str(self.p.root)

    def _forge(self, relpath):
        """Write a fully VALID, hash-matching record with no command involved."""
        record = store.put_acknowledgement_record(
            self._root(), relpath,
            content_sha256=store.require_writer_content_hash(self._root(), relpath),
            operator_confirmation="recorded without going through the command",
        )
        self.assertIn(relpath, store.active_acknowledgements(self._root()),
                      "the forged record must really be ACTIVE, or this test "
                      "would pass for the wrong reason")
        return record

    def _state(self, relpath):
        entry = [e for e in ews.open_bespoke_writer_migrations(self._root())
                 if e.get("writer_relpath") == relpath][0]
        return ews.classify_bespoke_writer_entry(self._root(), entry)

    def test_a_forged_record_does_not_release_a_rebuildable_writer(self):
        self.p.write_file(REBUILDABLE, _REBUILDABLE_SRC)
        self.p.write_queue([_entry(REBUILDABLE, ["sealed_kernel_import"])])
        self._forge(REBUILDABLE)

        self.assertEqual(self._state(REBUILDABLE),
                         ews.WriterState.BLOCKING_LIVE_ENABLE,
                         "a record against a rebuildable writer must be inert")
        self.assertEqual(len(ews.blocking_bespoke_writer_migrations(self._root())), 1,
                         "the blocking predicate must ignore it too")

    def test_the_health_view_still_blocks_on_a_forged_record(self):
        """End to end through the surface an operator actually reads."""
        from external_write import capability_health as ch
        self.p.write_file(REBUILDABLE, _REBUILDABLE_SRC)
        self.p.write_queue([_entry(REBUILDABLE, ["sealed_kernel_import"])])
        self._forge(REBUILDABLE)

        status = ch.overall_status(self._root())
        self.assertTrue(status["open_external_write_bypass"]["blocking"])
        self.assertEqual(status["open_external_write_bypass"]["writer_states"][REBUILDABLE],
                         ews.WriterState.BLOCKING_LIVE_ENABLE)

    def test_a_forged_record_does_not_relabel_a_non_live_writer(self):
        """Not a safety hole (non_live is already non-blocking) but the same rule:
        the report must say what the file IS, not what a record claims about it."""
        self.p.write_file(NON_LIVE_WRITER, _NON_LIVE_SRC)
        self.p.write_queue([_entry(NON_LIVE_WRITER, ["sealed_kernel_import"])])
        self._forge(NON_LIVE_WRITER)
        self.assertEqual(self._state(NON_LIVE_WRITER), ews.WriterState.NON_LIVE)

    def test_a_hand_written_json_record_is_inert_for_a_rebuildable_writer(self):
        """The truest form of the threat, with no module of ours involved at all.
        The store is a plain JSON file inside the project, so anything that can
        write a file can put a well-formed, hash-matching record there -- and the
        command's guard is not on that path by construction. Only the classifier's
        own restriction can make it inert."""
        import hashlib
        self.p.write_file(REBUILDABLE, _REBUILDABLE_SRC)
        self.p.write_queue([_entry(REBUILDABLE, ["sealed_kernel_import"])])
        digest = hashlib.sha256(
            (self.p.root / REBUILDABLE).read_bytes()).hexdigest()
        self.p.write_file(ack.ACKNOWLEDGEMENTS_REL, json.dumps([{
            "schema": ack.ACKNOWLEDGEMENT_SCHEMA,
            "writer_relpath": REBUILDABLE,
            "content_sha256": digest,
            "operator_confirmation": "hand-written straight into the store",
            "acknowledged_at": "2026-01-01T00:00:00Z",
        }], indent=2))
        self.assertIn(REBUILDABLE, store.active_acknowledgements(self._root()),
                      "the hand-written record must really be ACTIVE, or this "
                      "test would pass for the wrong reason")

        self.assertEqual(self._state(REBUILDABLE),
                         ews.WriterState.BLOCKING_LIVE_ENABLE)
        self.assertEqual(len(ews.blocking_bespoke_writer_migrations(self._root())), 1)

    def test_a_forged_record_DOES_work_for_a_needs_person_writer(self):
        """The positive control. Forging is a real route to the store, so the
        three tests above are about the CLASSIFIER refusing to honour the record
        -- not about the forgery having failed."""
        self.p.write_file(WRITER, _UNREPAIRABLE_SRC)
        self.p.queue_needs_person()
        self._forge(WRITER)
        self.assertEqual(self._state(WRITER), ews.WriterState.ACKNOWLEDGED_RISK)


if __name__ == "__main__":
    unittest.main()
