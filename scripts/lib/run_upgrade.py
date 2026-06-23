"""Two-phase A+ upgrade orchestration (across the os.execv boundary).

The operator-facing `wizard upgrade --apply` flow drives this. It runs in TWO phases separated
by a process self-replacement (os.execv), so the foundation-doc/operating-layer merge is always
performed by the NEWLY-installed engine, never the old bytecode that was loaded before checkout:

  PHASE 1 (toolkit not yet at the approved commit): under the upgrade lock, run the self-update
    transaction (apply_self_update_with_resolution). On success, re-exec (exec_fn, default
    os.execv) the SAME command so the new engine starts fresh and re-enters this function.
  PHASE 2 (toolkit already at the approved commit — we ARE the re-exec'd engine): under the
    lock, RE-VALIDATE the content gate (fetched bytes == approved) and run the apply step.

Locking is per-phase (not held across the exec — os.execv would drop it). The per-phase lock
plus the phase-2 content-gate re-validation together cover the brief gap during the exec: a
concurrent self-update is locked out, and a stale/tampered toolkit is caught by re-validation
(or returns CHECKED_CURRENT, benign). exec_fn + apply_fn are injectable for tests; production
binds exec_fn=os.execv and apply_fn=<call apply_upgrade against the operator project>.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from self_update import apply_self_update_with_resolution, _rev_parse  # type: ignore
from resolution_verify import verify_fetched_against_resolution  # type: ignore
from update_resolution import UpdateResolutionError, load_update_resolution  # type: ignore
from upgrade_lock import upgrade_lock  # type: ignore

# (status, detail) — status in {"refused", "execed", or whatever apply_fn returns}.
Result = Tuple[Any, Any]


def _default_exec(executable: str, argv: List[str]) -> None:  # pragma: no cover - replaces process
    os.execv(executable, argv)


def run_resolution_upgrade(
    operator_project_dir: Path,
    toolkit_dir: Path,
    *,
    argv: List[str],
    apply_fn: Callable[[Any], Result],
    exec_fn: Callable[[str, List[str]], None] = _default_exec,
    fetch_remote: str = "origin",
    lock_kwargs: Optional[dict] = None,
) -> Result:
    """Drive the two-phase upgrade. `argv` is the wizard subcommand argv to re-exec (without the
    python executable). Returns ("refused", detail) on any fail-closed refusal, ("execed",
    new_commit) after a phase-1 self-update + re-exec (only observed in tests; in production the
    process is replaced), or whatever `apply_fn` returns in phase 2."""
    try:
        resolution = load_update_resolution(operator_project_dir)
    except UpdateResolutionError as e:
        return ("refused", f"no approved update to apply: {e}")

    registry_path = toolkit_dir / "registry" / "foundation-bundles.json"
    head = _rev_parse(toolkit_dir, "HEAD") or ""
    lk = lock_kwargs or {}

    if head == resolution.target_public_commit_sha:
        # PHASE 2 — the toolkit already IS the approved engine; re-validate + apply.
        with upgrade_lock(operator_project_dir, **lk):
            vr = verify_fetched_against_resolution(registry_path, operator_project_dir, resolution)
            if not vr.ok:
                return ("refused", "content gate failed at apply: " + "; ".join(vr.failures))
            return apply_fn(resolution)

    # PHASE 1 — self-update the toolkit to the approved commit, then re-exec.
    with upgrade_lock(operator_project_dir, **lk):
        res = apply_self_update_with_resolution(
            toolkit_dir, operator_project_dir, fetch_remote=fetch_remote)
    if not res.applied:
        return ("refused", res.reason_code)
    exec_fn(sys.executable, [sys.executable, *argv])
    # Reached only when exec_fn is a test stub (production os.execv replaces the process image).
    return ("execed", res.new_commit)
