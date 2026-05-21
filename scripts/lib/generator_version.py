"""Wizard-side helper for F-9 generator-version identity emission.

Computes the wizard generator code identity (build-repo HEAD git SHA) for
inclusion in foundation-bundle manifests at generation time. Enforces
worktree cleanliness at emission time per the F-9 generator-version identity
mechanism contract: dirty worktree state makes HEAD provenance false, so the
helper refuses to emit a dirty-SHA manifest when require_clean=True.

Stdlib-only: subprocess + pathlib + typing. No PyYAML, no third-party deps.
Wizard distribution stays pip-install-free per the wizard-side stdlib-only
discipline.

Responsibility boundary (per F-9 mechanism design):
    - Worktree-cleanliness enforcement is EMISSION-TIME responsibility (this
      helper). The helper refuses to return a SHA when require_clean=True and
      the worktree is dirty.
    - Recorded-SHA format validation is READ-TIME responsibility (manifest
      validators). Validators cannot prove historical worktree cleanliness
      from a manifest alone; they only see the recorded SHA, not the worktree
      state at SHA-generation time.

Public API:
    current_generator_version(repo_root, require_clean=True) -> str
        Returns 40-char lowercase hex git SHA of repo_root's HEAD.
        Raises GeneratorVersionError if:
            - repo_root is not a git repository
            - git is not installed / not on PATH
            - require_clean=True AND the worktree is dirty
            - git rev-parse HEAD returns non-standard output

    is_worktree_dirty(repo_root) -> bool
        Returns True if `git status --porcelain` reports any modified,
        untracked, or staged-but-unrecorded changes. Returns False on clean
        worktree.

Usage (manifest authoring at generation event):
    from wizard.scripts.lib.generator_version import current_generator_version
    sha = current_generator_version(Path("/path/to/agent-wizard-build"))
    manifest["generator_version"] = sha

Permissive mode (manual invocations / debugging):
    from wizard.scripts.lib.generator_version import (
        current_generator_version, is_worktree_dirty,
    )
    sha = current_generator_version(repo_root, require_clean=False)
    if is_worktree_dirty(repo_root):
        print(f"WARNING: SHA {sha} reflects HEAD, but worktree is dirty.")
"""

import re
import subprocess
from pathlib import Path
from typing import List


SHA_FORMAT_RE = re.compile(r"^[0-9a-f]{40}$")


class GeneratorVersionError(Exception):
    """Raised when generator-version identity computation fails."""


def _run_git(args: List[str], repo_root: Path) -> str:
    """Run a git command in repo_root; return stripped stdout.

    Raises GeneratorVersionError with a specific message on:
        - git not installed (FileNotFoundError on subprocess)
        - non-zero exit code (CalledProcessError; includes stderr in message)
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(repo_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise GeneratorVersionError(
            f"git executable not found on PATH; cannot compute generator-version identity for {repo_root}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise GeneratorVersionError(
            f"git {' '.join(args)} failed in {repo_root}: exit {exc.returncode}; stderr={exc.stderr.strip()!r}"
        ) from exc
    return result.stdout.strip()


def is_worktree_dirty(repo_root: Path) -> bool:
    """Return True if the worktree at repo_root has uncommitted changes.

    Considers any of: modified tracked files, staged changes, untracked files.
    Returns False on a fully clean worktree.

    Raises GeneratorVersionError if repo_root is not a git repository or git
    is not available.
    """
    # `git status --porcelain` emits one line per non-clean path; empty stdout
    # means the worktree is fully clean (no modified, staged, or untracked
    # files).
    status_output = _run_git(["status", "--porcelain"], repo_root)
    return status_output != ""


def current_generator_version(
    repo_root: Path, require_clean: bool = True
) -> str:
    """Return the 40-char lowercase hex git SHA of repo_root's HEAD.

    Args:
        repo_root: path to the build-repo root.
        require_clean: when True (default; E-β / v1.0.0 emission contract),
            raises GeneratorVersionError if the worktree is dirty. When False
            (permissive mode for manual invocations / debugging), returns the
            SHA regardless of worktree state. Callers in permissive mode
            should consult is_worktree_dirty() separately if cleanliness
            matters.

    Returns:
        40-char lowercase hex string.

    Raises:
        GeneratorVersionError on:
            - repo_root not a git repository
            - git not installed
            - require_clean=True AND worktree is dirty
            - git rev-parse HEAD output not 40-char lowercase hex
    """
    # Verify repo_root is a git repository. `git rev-parse --is-inside-work-tree`
    # exits non-zero if not in a worktree; _run_git surfaces that as a
    # GeneratorVersionError.
    inside = _run_git(["rev-parse", "--is-inside-work-tree"], repo_root)
    if inside != "true":
        raise GeneratorVersionError(
            f"{repo_root} is not inside a git worktree (rev-parse returned {inside!r})"
        )

    # Enforce worktree cleanliness at emission time when require_clean=True.
    # This is the F-9 emission-time responsibility: a dirty worktree makes the
    # HEAD SHA false provenance.
    if require_clean and is_worktree_dirty(repo_root):
        raise GeneratorVersionError(
            f"worktree at {repo_root} is dirty; refusing to emit generator-version "
            "identity (require_clean=True). Commit or stash changes, or pass "
            "require_clean=False for permissive-mode SHA retrieval."
        )

    sha = _run_git(["rev-parse", "HEAD"], repo_root)
    # Normalize to lowercase per the F-9 contract value-format requirement.
    sha = sha.lower()

    if not SHA_FORMAT_RE.match(sha):
        raise GeneratorVersionError(
            f"git rev-parse HEAD returned {sha!r}; expected 40-char lowercase hex"
        )

    return sha


if __name__ == "__main__":
    # Smoke entry point: print the current generator-version identity for the
    # build-repo containing this script. Useful for manifest authoring.
    import sys

    # Locate the build-repo root: walk up from this file's parent until
    # finding a directory containing .git.
    here = Path(__file__).resolve()
    for candidate in [here] + list(here.parents):
        if (candidate / ".git").exists():
            repo_root = candidate
            break
    else:
        sys.stderr.write("ERROR: cannot locate .git ancestor of this script\n")
        sys.exit(1)

    try:
        # Default to require_clean=True; the smoke entry point models the
        # production contract.
        sha = current_generator_version(repo_root, require_clean=True)
        sys.stdout.write(sha + "\n")
        sys.exit(0)
    except GeneratorVersionError as exc:
        sys.stderr.write(f"GeneratorVersionError: {exc}\n")
        sys.exit(2)
