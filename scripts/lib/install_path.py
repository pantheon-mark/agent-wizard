#!/usr/bin/env python3
"""Best-effort install of the `wizard` shim onto the operator's PATH.

The operator's built system always invokes the toolkit by its full resolved path
(`$WIZARD_HOME/scripts/wizard`), so this is pure convenience: it lets a human who
opens a terminal type a bare `wizard ...`. It is therefore strictly BEST-EFFORT:

  * never uses sudo and never edits a shell profile,
  * only links into a directory that is ALREADY on PATH and writable by the user,
  * never clobbers an existing `wizard` it did not create,
  * never fails setup — any "couldn't" outcome is reported, not raised.

The toolkit-by-full-path invocation is the floor; this symlink is the optional ceiling.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

LINK_NAME = "wizard"

# Preference order among writable, on-PATH directories. User-owned `~/.local/bin`
# first (never needs elevation), then the common Homebrew/macOS bin dirs.
_PREFERRED_SUFFIXES = (".local/bin", "usr/local/bin", "opt/homebrew/bin")


@dataclass
class InstallPathResult:
    status: str  # installed | already_installed | conflict_skipped | no_writable_path_dir | error
    link_path: Optional[str] = None
    target: Optional[str] = None
    message: str = ""
    conflicts: List[str] = field(default_factory=list)


def _path_dirs(path_value: str) -> List[Path]:
    """Ordered, de-duplicated, ~-expanded directories from a PATH string."""
    out: List[Path] = []
    seen = set()
    for raw in (path_value or "").split(os.pathsep):
        if not raw:
            continue
        try:
            p = Path(raw).expanduser()
        except (RuntimeError, ValueError):
            continue
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _rank(p: Path) -> int:
    s = str(p)
    for i, suffix in enumerate(_PREFERRED_SUFFIXES):
        if s.endswith(suffix):
            return i
    return len(_PREFERRED_SUFFIXES)


def _points_at(link: Path, shim: Path) -> Optional[bool]:
    """True/False if `link` is a symlink resolving to `shim`; None if it can't be read."""
    if not link.is_symlink():
        return None
    try:
        return link.resolve() == shim
    except OSError:
        return False


def install_wizard_on_path(
    shim_path: str,
    *,
    path_value: Optional[str] = None,
    home: Optional[str] = None,
) -> InstallPathResult:
    """Link the `wizard` shim into a writable, on-PATH directory. Best-effort, idempotent."""
    shim = Path(shim_path).expanduser()
    try:
        shim = shim.resolve()
    except OSError:
        pass
    if path_value is None:
        path_value = os.environ.get("PATH", "")

    if not shim.exists():
        return InstallPathResult(
            status="error",
            target=str(shim),
            message=f"The wizard launcher was not found at {shim}; the toolkit may be incomplete.",
        )

    candidates = _path_dirs(path_value)

    # Idempotency / already-available: a correct link anywhere on PATH means we are done.
    for d in candidates:
        link = d / LINK_NAME
        if _points_at(link, shim) is True:
            return InstallPathResult(
                status="already_installed",
                link_path=str(link),
                target=str(shim),
                message=f"`wizard` is already available as a plain command (linked from {link}).",
            )

    writable = [d for d in candidates if d.is_dir() and os.access(d, os.W_OK)]
    writable.sort(key=lambda d: (_rank(d), str(d)))

    conflicts: List[str] = []
    for d in writable:
        link = d / LINK_NAME
        # Never clobber an existing entry we did not create (real file OR foreign symlink).
        if link.is_symlink() or link.exists():
            conflicts.append(str(link))
            continue
        try:
            os.symlink(shim, link)
        except OSError as e:
            conflicts.append(f"{link} ({e})")
            continue
        return InstallPathResult(
            status="installed",
            link_path=str(link),
            target=str(shim),
            message=f"`wizard` is now available as a plain command (linked from {link}).",
        )

    if conflicts:
        return InstallPathResult(
            status="conflict_skipped",
            target=str(shim),
            conflicts=conflicts,
            message=(
                "Left an existing `wizard` on your PATH untouched. This is fine — the "
                "system always uses the full path, so updates work either way."
            ),
        )

    return InstallPathResult(
        status="no_writable_path_dir",
        target=str(shim),
        message=(
            "Couldn't add `wizard` as a plain command automatically (no writable folder "
            "on your PATH). This is optional — the system always uses the full path, so "
            "checking for and applying updates works fine without it."
        ),
    )
