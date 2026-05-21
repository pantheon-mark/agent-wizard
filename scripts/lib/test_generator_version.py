"""Unit tests for wizard.scripts.lib.generator_version (F-9 emission helper).

Exercises:
    - clean-worktree SHA retrieval (positive case)
    - dirty-worktree fail-fast when require_clean=True (F5 negative case)
    - dirty-worktree SHA return when require_clean=False (permissive mode)
    - not-in-git-repo failure
    - is_worktree_dirty() returns False on clean, True on dirty

Stdlib-only test (unittest + tempfile + subprocess); creates ephemeral git
repos under tempfile.TemporaryDirectory for isolated testing.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from wizard.scripts.lib.generator_version import (
    GeneratorVersionError,
    current_generator_version,
    is_worktree_dirty,
)


def _git(repo: Path, *args: str) -> None:
    """Run a git command in repo; fail the test on non-zero exit."""
    subprocess.run(
        ["git"] + list(args),
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


def _init_repo_with_commit(repo: Path) -> str:
    """Initialize a git repo with one commit; return the HEAD SHA (lowercase)."""
    _git(repo, "init", "--quiet")
    # Configure user for the commit (required by git).
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    # Create a tracked file + commit.
    (repo / "seed.txt").write_text("seed\n")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "--quiet", "-m", "seed commit")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().lower()
    return sha


class TestCurrentGeneratorVersion(unittest.TestCase):

    def test_clean_worktree_returns_sha(self):
        """Clean worktree → current_generator_version returns 40-char hex."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            expected_sha = _init_repo_with_commit(repo)

            sha = current_generator_version(repo, require_clean=True)

            self.assertEqual(sha, expected_sha)
            self.assertEqual(len(sha), 40)
            self.assertTrue(all(c in "0123456789abcdef" for c in sha))

    def test_dirty_worktree_raises_when_require_clean(self):
        """Dirty worktree + require_clean=True → GeneratorVersionError.

        This is the F-9 emission-time contract: refuse to emit a dirty SHA.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_repo_with_commit(repo)
            # Make the worktree dirty by modifying the tracked file.
            (repo / "seed.txt").write_text("modified\n")

            with self.assertRaises(GeneratorVersionError) as ctx:
                current_generator_version(repo, require_clean=True)
            self.assertIn("dirty", str(ctx.exception).lower())

    def test_dirty_worktree_with_untracked_file_raises(self):
        """Untracked file also counts as dirty (per `git status --porcelain`)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_repo_with_commit(repo)
            # Create an untracked file (no `git add`).
            (repo / "new_file.txt").write_text("new\n")

            with self.assertRaises(GeneratorVersionError):
                current_generator_version(repo, require_clean=True)

    def test_dirty_worktree_returns_sha_when_permissive(self):
        """Dirty worktree + require_clean=False → returns SHA (permissive mode)."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            expected_sha = _init_repo_with_commit(repo)
            (repo / "seed.txt").write_text("modified\n")

            sha = current_generator_version(repo, require_clean=False)
            # SHA reflects HEAD; dirty state is up to caller to check via
            # is_worktree_dirty().
            self.assertEqual(sha, expected_sha)

    def test_not_in_git_repo_raises(self):
        """Non-git directory → GeneratorVersionError."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            # Do NOT init a git repo. Some git installs auto-discover parent
            # repos; that's why we test in a tempdir.

            with self.assertRaises(GeneratorVersionError):
                current_generator_version(repo, require_clean=True)


class TestIsWorktreeDirty(unittest.TestCase):

    def test_clean_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_repo_with_commit(repo)
            self.assertFalse(is_worktree_dirty(repo))

    def test_modified_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_repo_with_commit(repo)
            (repo / "seed.txt").write_text("modified\n")
            self.assertTrue(is_worktree_dirty(repo))

    def test_untracked_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_repo_with_commit(repo)
            (repo / "untracked.txt").write_text("new\n")
            self.assertTrue(is_worktree_dirty(repo))

    def test_staged_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_repo_with_commit(repo)
            (repo / "staged.txt").write_text("staged\n")
            _git(repo, "add", "staged.txt")
            self.assertTrue(is_worktree_dirty(repo))


if __name__ == "__main__":
    unittest.main()
