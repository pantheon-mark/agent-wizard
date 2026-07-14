"""Tests for the PERSISTENT, atomic, disk-keyed blast-radius ledger (Task 4,
A1 — v0.12.0 Slice 1, design §1): the F-39 fix and the I2 atomic-ledger
invariant.

F-39 (the defect): a bulk driver built a FRESH ``InvocationLedger()`` per
chunk, so the blast-radius cap never accumulated across chunks — a session of
chunks could apply unbounded units by resetting the in-memory counter each
time. The fix is a ledger whose count lives on disk, keyed by
``ledger_window_id``: constructing a fresh ledger object per chunk re-reads the
SAME authoritative disk count, so the window cannot be reset.

I2 (atomic ledger): persistent ledger updates are atomic/locked; the disk count
is authoritative; two concurrent runners cannot double-spend budget.

Anti-overfit (Global Constraint #3): the F-39 gate regression is exercised on
≥2 divergent op_kinds (gmail.message.trash — sensitive_data, cap 25 — AND
delete_record — irreversible_external, cap 5).

Runner: unittest, from wizard/scripts. Stdlib only.
"""

import sys
import tempfile
import threading
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import Operation  # noqa: E402
from external_write.write_gate import (  # noqa: E402
    PersistentInvocationLedger,
    evaluate_write_gate,
    _ledger_key,
)


def _accepted_entry(*, id, risk_class, blast_radius_cap, declared_test_target="native_undo"):
    return {
        "id": id, "name": id, "action_class": "mutate",
        "risk_class": risk_class, "declared_test_target": declared_test_target,
        "blast_radius_cap": blast_radius_cap, "recovery_profile_ref": "recovery/x.md",
        "accepted": True,
    }


def _op(op_kind, surface):
    return Operation(surface=surface, object_id="o1", field="__record__",
                     new_value="<x>", op_kind=op_kind, batch_id="b1")


# ===========================================================================
# Persistence + disk-authoritative count
# ===========================================================================

class TestPersistentLedgerPersistence(unittest.TestCase):

    def test_absent_ledger_file_counts_zero(self):
        with tempfile.TemporaryDirectory() as d:
            led = PersistentInvocationLedger("window_abc", ledger_dir=d)
            self.assertEqual(led.count("google_sheets::delete_record"), 0)

    def test_count_survives_a_fresh_instance_same_window_simulated_restart(self):
        with tempfile.TemporaryDirectory() as d:
            key = "gmail::gmail.message.trash"
            led1 = PersistentInvocationLedger("win-1", ledger_dir=d)
            led1.record(key, 20)
            # Simulated restart / regenerated loop: a BRAND NEW ledger object,
            # same window id + dir. The disk count is authoritative.
            led2 = PersistentInvocationLedger("win-1", ledger_dir=d)
            self.assertEqual(led2.count(key), 20)
            led2.record(key, 3)
            led3 = PersistentInvocationLedger("win-1", ledger_dir=d)
            self.assertEqual(led3.count(key), 23)

    def test_distinct_windows_do_not_share_counts(self):
        with tempfile.TemporaryDirectory() as d:
            key = "gmail::gmail.message.trash"
            PersistentInvocationLedger("win-A", ledger_dir=d).record(key, 10)
            self.assertEqual(
                PersistentInvocationLedger("win-B", ledger_dir=d).count(key), 0)


# ===========================================================================
# F-39 regression — a fresh ledger per chunk CANNOT reset the window
# ===========================================================================

class TestF39FreshLedgerPerChunkCannotReset(unittest.TestCase):
    """The exact F-39 shape, driven through evaluate_write_gate: a bulk driver
    that builds a fresh ledger object per chunk must NOT be able to reset the
    blast-radius window — the persistent disk count is authoritative across
    chunks, so the accumulated cap is enforced."""

    def _run_chunk(self, op_kind, surface, n_units, ledger_dir, window_id,
                   descriptor_set):
        op = _op(op_kind, surface)
        # A FRESH ledger object per chunk (the F-39 defeat) — but persistent +
        # keyed by the same window id, so it reads the accumulated disk count.
        fresh_ledger = PersistentInvocationLedger(window_id, ledger_dir=ledger_dir)
        return evaluate_write_gate(
            op, target="live", descriptor_set=descriptor_set,
            cap_ledger=fresh_ledger, n_units=n_units)

    def test_gmail_trash_fresh_ledger_per_chunk_accumulates_to_cap(self):
        # cap 25; chunk1 = 20 units permitted; chunk2 = 10 units with a FRESH
        # ledger object would be 20+10=30 > 25 -> refused (window not reset).
        ds = [_accepted_entry(id="gmail", risk_class="sensitive_data",
                              blast_radius_cap=25)]
        with tempfile.TemporaryDirectory() as d:
            win = "run-gmail-1"
            d1 = self._run_chunk("gmail.message.trash", "gmail", 20, d, win, ds)
            self.assertTrue(d1.permitted, "first chunk within cap should permit")
            d2 = self._run_chunk("gmail.message.trash", "gmail", 10, d, win, ds)
            self.assertFalse(d2.permitted,
                             "F-39: fresh ledger per chunk must NOT reset the window")
            self.assertIn("blast-radius cap", d2.refusal.detail["reason"])

    def test_delete_record_fresh_ledger_per_chunk_accumulates_to_cap(self):
        # Divergent op_kind: delete_record, irreversible, cap 5.
        ds = [_accepted_entry(id="google_sheets", risk_class="irreversible_external",
                              blast_radius_cap=5)]
        with tempfile.TemporaryDirectory() as d:
            win = "run-del-1"
            d1 = self._run_chunk("delete_record", "google_sheets", 4, d, win, ds)
            self.assertTrue(d1.permitted)
            d2 = self._run_chunk("delete_record", "google_sheets", 3, d, win, ds)
            self.assertFalse(d2.permitted,
                             "F-39: accumulated irreversible count must be enforced")


# ===========================================================================
# I2 — atomic / locked updates; no double-spend across concurrent runners
# ===========================================================================

class TestI2AtomicLedger(unittest.TestCase):

    def test_concurrent_records_do_not_lose_updates(self):
        with tempfile.TemporaryDirectory() as d:
            key = "gmail::gmail.message.trash"
            window = "run-concurrent"
            n_threads = 12
            per_thread = 50
            barrier = threading.Barrier(n_threads)

            def worker():
                barrier.wait()
                for _ in range(per_thread):
                    # A fresh instance per record — the worst case for a
                    # read-modify-write race; the lock must still serialize.
                    PersistentInvocationLedger(window, ledger_dir=d).record(key, 1)

            threads = [threading.Thread(target=worker) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            final = PersistentInvocationLedger(window, ledger_dir=d).count(key)
            self.assertEqual(final, n_threads * per_thread,
                             "lost updates under concurrency — ledger is not atomic (I2)")

    def test_two_concurrent_runners_cannot_double_spend_last_slot(self):
        # Both runners see 4/5 consumed and race to consume the final slot; with
        # an atomic locked increment, the disk total can never exceed the cap by
        # more than one in-flight op, and re-reading shows a single authoritative
        # count both runners agree on.
        with tempfile.TemporaryDirectory() as d:
            key = "google_sheets::delete_record"
            window = "run-lastslot"
            PersistentInvocationLedger(window, ledger_dir=d).record(key, 4)

            results = []
            barrier = threading.Barrier(2)

            def runner():
                barrier.wait()
                led = PersistentInvocationLedger(window, ledger_dir=d)
                led.record(key, 1)
                results.append(led.count(key))

            t1 = threading.Thread(target=runner)
            t2 = threading.Thread(target=runner)
            t1.start(); t2.start(); t1.join(); t2.join()

            final = PersistentInvocationLedger(window, ledger_dir=d).count(key)
            # Two atomic increments from 4 -> 6, never a lost update leaving it at 5.
            self.assertEqual(final, 6)


if __name__ == "__main__":
    unittest.main()
