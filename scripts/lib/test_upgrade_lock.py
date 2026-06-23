"""Tests for the interprocess upgrade lock (F-G TOCTOU protection).

The A+ upgrade is a multi-step disk transaction (self-update -> os.execv -> apply). An
interprocess lock held across it prevents a concurrent upgrade of the SAME operator system from
interleaving (verify in one, mutate in another). A crashed holder must not block forever, so a
stale lock (older than the threshold) is broken. Clock is injected for determinism.
"""

import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upgrade_lock import upgrade_lock, UpgradeLockBusy, UPGRADE_LOCK_REL  # noqa: E402


class UpgradeLockTest(unittest.TestCase):
    def test_acquire_and_release(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            lock_path = proj / UPGRADE_LOCK_REL
            with upgrade_lock(proj):
                self.assertTrue(lock_path.is_file(), "lock file present while held")
            self.assertFalse(lock_path.exists(), "lock file removed on release")

    def test_concurrent_acquire_is_busy(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            with upgrade_lock(proj):
                with self.assertRaises(UpgradeLockBusy):
                    with upgrade_lock(proj):
                        pass

    def test_released_lock_can_be_reacquired(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            with upgrade_lock(proj):
                pass
            with upgrade_lock(proj):  # must not raise
                pass

    def test_stale_lock_is_broken(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            # a held lock at t=0 ...
            clock = [1000.0]
            with upgrade_lock(proj, stale_after_seconds=300, now=lambda: clock[0]):
                # ... a SECOND attempt far in the future sees it as stale and breaks it.
                with upgrade_lock(proj, stale_after_seconds=300, now=lambda: clock[0] + 10_000):
                    self.assertTrue((proj / UPGRADE_LOCK_REL).is_file())

    def test_fresh_lock_not_broken(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            clock = [1000.0]
            with upgrade_lock(proj, stale_after_seconds=300, now=lambda: clock[0]):
                with self.assertRaises(UpgradeLockBusy):
                    with upgrade_lock(proj, stale_after_seconds=300, now=lambda: clock[0] + 60):
                        pass

    def test_lock_release_even_on_exception(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            with self.assertRaises(ValueError):
                with upgrade_lock(proj):
                    raise ValueError("boom")
            self.assertFalse((proj / UPGRADE_LOCK_REL).exists(),
                             "lock must release even when the body raises")


if __name__ == "__main__":
    unittest.main()
