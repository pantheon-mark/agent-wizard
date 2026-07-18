"""Build-time lint: deterministic safety notices must keep their honest caveat text
verbatim (F-65).

Why this exists
----------------
F-65 (reclassified safety/honesty, not UX): during the estate dogfood, the agent
SUMMARIZED a deterministic safety notice and FLATTENED its honest caveat --
"do not rely on it being blocked until it is rebuilt" -- when relaying a
``broken_requires_migration`` pause/migration notice to the operator. Softening or
dropping that caveat can lead a non-technical operator to consent to a weaker
boundary than actually exists: the caveat exists precisely because, in that branch,
no runtime block could be installed, so the mechanism is NOT actually blocked even
though its capability was flagged.

The caveat text lives in the deterministic layer
(``wizard/scripts/lib/upgrade_reconcile.py``, the ``broken_requires_migration``
branch gated on ``not m.paused_op_kinds``) -- it is not new prose to author. This
module is the build-time guard that locks it there: it scans the deterministic
notice source for the exact required caveat substring(s) and fails the build if a
future edit silently drops or softens one.

Scope (deliberately narrow -- AR-004 weakest-sufficient)
----------------------------------------------------------
This is a cheap structural/text lint (a substring presence check), not a runtime
guard -- the deterministic layer already OWNS the notice; this only keeps the owning
source file honest over time. Task C4 aggregates this (and sibling notice-fidelity
checks) into the build-time lint suite; this module is written to be imported from
there, not just from its own test.

Stdlib only.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]

# The deterministic source file that owns the broken_requires_migration pause/
# migration notice (relative to repo root).
DEFAULT_NOTICE_RELPATH = "wizard/scripts/lib/upgrade_reconcile.py"

# The required caveat substring(s) that must survive verbatim in the deterministic
# notice source. Exact text, gated on `not m.paused_op_kinds` in the
# `broken_requires_migration` branch of `reconcile_upgrade`: when no runtime block
# could be installed, the operator must be told plainly not to rely on one existing.
REQUIRED_CAVEAT_SUBSTRINGS: Sequence[str] = (
    "do not rely on it being blocked until it is rebuilt",
)


def check_safety_notice_text(
    repo_root: Optional[Path] = None,
    notice_relpath: str = DEFAULT_NOTICE_RELPATH,
    required_substrings: Optional[Sequence[str]] = None,
) -> List[str]:
    """Return the list of required caveat substrings that are MISSING from the
    deterministic notice source file (default: ``upgrade_reconcile.py``). An empty
    list means every required caveat is present verbatim -- clean.

    Reads the REAL file from disk (anti-overfit: this must assert against the
    actual deterministic source, never a hand-copied snippet). Importable by other
    build-time lint aggregation (Task C4) -- not test-only."""
    root = repo_root if repo_root is not None else REPO_ROOT
    substrings = (
        required_substrings if required_substrings is not None else REQUIRED_CAVEAT_SUBSTRINGS
    )
    full_path = root / notice_relpath
    text = full_path.read_text(encoding="utf-8")
    return [substring for substring in substrings if substring not in text]
