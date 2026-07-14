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

    def test_atomic_reserve_under_cap_refuses_without_incrementing(self):
        # A direct reserve at the cap edge: reserving the last slot succeeds, a
        # further reserve is refused WITHOUT incrementing (the disk count stays at
        # the cap, not one past it) — the atomic check-and-consume (I-1).
        with tempfile.TemporaryDirectory() as d:
            key = "google_sheets::delete_record"
            window = "run-reserve"
            led = PersistentInvocationLedger(window, ledger_dir=d)
            led.record(key, 4)
            ok = led.reserve(key, 1, 5)      # 4 -> 5, at the cap
            self.assertTrue(ok.reserved)
            self.assertEqual(led.count(key), 5)
            over = led.reserve(key, 1, 5)     # would be 6 > 5 -> refuse, no write
            self.assertFalse(over.reserved)
            self.assertEqual(over.refusal, "cap")
            self.assertEqual(led.count(key), 5,
                             "a refused reserve must NOT increment the count (I-1)")


# ===========================================================================
# I-1 — double-spend TOCTOU closed THROUGH evaluate_write_gate (the real path)
# ===========================================================================

class TestI1NoDoubleSpendThroughGate(unittest.TestCase):
    """The check-then-consume TOCTOU, exercised through the REAL gate path. Two
    concurrent gate evaluations racing for the final slot of a cap must NOT both
    permit: exactly one permits, the other refuses, and the authoritative disk
    count never exceeds the cap. (The prior test recorded directly, off the gate,
    and asserted the count reaching 6 vs cap 5 as DESIRED — a false green; it is
    deleted in favor of this one.)"""

    def test_two_concurrent_gate_evaluations_cannot_double_spend_the_last_slot(self):
        ds = [_accepted_entry(id="google_sheets", risk_class="irreversible_external",
                              blast_radius_cap=5)]
        with tempfile.TemporaryDirectory() as d:
            window = "run-gate-race"
            op = _op("delete_record", "google_sheets")
            key = _ledger_key(op)
            # Pre-consume 4 of 5 so both racers contend for the single last slot.
            PersistentInvocationLedger(window, ledger_dir=d).record(key, 4)

            results = []
            barrier = threading.Barrier(2)

            def runner():
                led = PersistentInvocationLedger(window, ledger_dir=d)
                barrier.wait()
                dec = evaluate_write_gate(op, target="live", descriptor_set=ds,
                                          cap_ledger=led, n_units=1)
                results.append(dec.permitted)

            t1 = threading.Thread(target=runner)
            t2 = threading.Thread(target=runner)
            t1.start(); t2.start(); t1.join(); t2.join()

            self.assertEqual(sorted(results), [False, True],
                             "exactly one of two racing gate evaluations may take the "
                             "last slot — the other must refuse (I-1)")
            final = PersistentInvocationLedger(window, ledger_dir=d).count(key)
            self.assertEqual(final, 5,
                             "atomic reserve-under-cap must never let the count exceed the cap")


# ===========================================================================
# I-2 — non-POSIX lock fails CLOSED (gated consume refuses, never proceeds unlocked)
# ===========================================================================

class TestI2LockUnavailableFailsClosed(unittest.TestCase):

    def test_gated_consume_refuses_when_lock_unavailable(self):
        import external_write.write_gate as wg
        ds = [_accepted_entry(id="google_sheets", risk_class="irreversible_external",
                              blast_radius_cap=5)]
        with tempfile.TemporaryDirectory() as d:
            op = _op("delete_record", "google_sheets")
            led = PersistentInvocationLedger("run-nolock", ledger_dir=d)
            orig = wg._fcntl
            wg._fcntl = None  # simulate a non-POSIX platform (no cross-process lock)
            try:
                dec = evaluate_write_gate(op, target="live", descriptor_set=ds,
                                          cap_ledger=led, n_units=1)
            finally:
                wg._fcntl = orig
            self.assertFalse(dec.permitted,
                             "a gated consume must fail CLOSED when the lock is unavailable")
            self.assertEqual(
                PersistentInvocationLedger("run-nolock", ledger_dir=d).count(_ledger_key(op)),
                0, "nothing may be consumed when the lock is unavailable (I-2)")


if __name__ == "__main__":
    unittest.main()
