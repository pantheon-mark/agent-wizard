"""Interprocess upgrade lock (F-G): serialize the A+ upgrade transaction for one operator system.

The upgrade is a multi-step disk transaction (self-update -> os.execv -> apply). Holding this lock
across it prevents a concurrent upgrade of the SAME operator system from interleaving (one process
verifying while another mutates). A presence-based lockfile (O_CREAT|O_EXCL) is used because it
SURVIVES os.execv (a file persists across process-image replacement, unlike an fcntl flock tied to
a file descriptor) — so the re-exec'd apply still sees the lock the pre-exec self-update took.

A crashed holder must not block forever: a lock older than `stale_after_seconds` is broken and
re-acquired. The clock is injected (`now`) for deterministic tests.

Stdlib-only.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

UPGRADE_LOCK_REL = ".wizard/upgrade.lock"
DEFAULT_STALE_AFTER_SECONDS = 1800  # 30 minutes — far longer than any real upgrade.


class UpgradeLockBusy(Exception):
    """Raised when another upgrade of this operator system is already in progress (a live,
    non-stale lock is held). Fail-closed: never proceed concurrently."""


def _try_create(lock_path: Path, now: Callable[[], float]) -> bool:
    """Atomically create the lockfile (O_EXCL). Returns False if it already exists."""
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        os.write(fd, (json.dumps({"pid": os.getpid(), "acquired_at": now()}) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return True


def _is_stale(lock_path: Path, stale_after_seconds: float, now: Callable[[], float]) -> bool:
    """A lock is stale if its recorded acquire time (or, failing that, its mtime) is older than
    the threshold. Unreadable/corrupt lock -> treated as stale (a holder that wrote garbage and
    died must not block forever)."""
    try:
        acquired_at = float(json.loads(lock_path.read_text(encoding="utf-8"))["acquired_at"])
    except Exception:
        try:
            acquired_at = lock_path.stat().st_mtime
        except OSError:
            return True
    return (now() - acquired_at) > stale_after_seconds


@contextmanager
def upgrade_lock(
    operator_project_dir: Path,
    *,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    now: Callable[[], float] = time.time,
) -> Iterator[Path]:
    """Acquire the operator's upgrade lock for the duration of the `with` block. Raises
    UpgradeLockBusy if a live (non-stale) lock is already held. Releases on exit, even if the
    body raises. A stale lock is broken + re-acquired."""
    lock_path = operator_project_dir / UPGRADE_LOCK_REL
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    acquired = _try_create(lock_path, now)
    if not acquired and _is_stale(lock_path, stale_after_seconds, now):
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
        acquired = _try_create(lock_path, now)
    if not acquired:
        raise UpgradeLockBusy(
            f"another upgrade of this system is already in progress (lock: {lock_path})"
        )

    try:
        yield lock_path
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
