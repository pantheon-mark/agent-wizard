"""Integration tests for the `wizard self-update` CLI subcommand + the `wizard` shim.

Exercises the argparse wiring (wizard_upgrade.py self-update) and the bash `wizard`
shim end to end against a real temp git repo: --check verifies without changing; --apply
performs the guarded swap; a tampered remote fails closed via the CLI with a non-zero
exit code; the shim resolves the engine relative to itself.

Stdlib unittest; pip-install-free.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from update_source import CANONICAL_HTTPS_URL, UPDATE_SOURCE_REL, render_update_source_json  # noqa: E402
from upgrade import EXIT_UPDATE_AVAILABLE, EXIT_UPDATE_SOURCE_TAMPERED, EXIT_CHECKED_CURRENT  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parents[1]   # wizard/scripts
ENGINE = SCRIPTS_DIR / "wizard_upgrade.py"
SHIM = SCRIPTS_DIR / "wizard"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _commit(repo, msg, content="x"):
    (repo / "file.txt").write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                          capture_output=True, text=True, check=True).stdout.strip()


class WizardSelfUpdateCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        _git(self.upstream, "init", "-q")
        _git(self.upstream, "config", "user.email", "t@t.t")
        _git(self.upstream, "config", "user.name", "t")
        _git(self.upstream, "checkout", "-q", "-b", "main")
        self.base = _commit(self.upstream, "base")

        self.toolkit = self.root / "agent-wizard"
        _git(self.root, "clone", "-q", str(self.upstream), str(self.toolkit))
        _git(self.toolkit, "config", "user.email", "t@t.t")
        _git(self.toolkit, "config", "user.name", "t")
        _git(self.toolkit, "remote", "add", "local", str(self.upstream))
        _git(self.toolkit, "remote", "set-url", "origin", CANONICAL_HTTPS_URL)

        self.operator = self.root / "estate"
        (self.operator / ".wizard").mkdir(parents=True)
        (self.operator / UPDATE_SOURCE_REL).write_text(
            render_update_source_json(last_known_good_commit=self.base), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _newer(self):
        new = _commit(self.upstream, "newer", content="y")
        _git(self.toolkit, "fetch", "-q", "local")
        return new

    def _run_cli(self, *args, via_shim=False):
        if via_shim:
            cmd = ["bash", str(SHIM), *args]
        else:
            cmd = [sys.executable, str(ENGINE), *args]
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_check_reports_update_available_nonmutating(self):
        new = self._newer()
        head_before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.toolkit),
                                      capture_output=True, text=True).stdout.strip()
        proc = self._run_cli(
            "self-update", "--check",
            "--toolkit-dir", str(self.toolkit),
            "--operator-dir", str(self.operator),
            "--to-commit", new,
        )
        self.assertEqual(proc.returncode, EXIT_UPDATE_AVAILABLE, proc.stderr + proc.stdout)
        self.assertIn("NOT a cryptographic signature", proc.stdout)
        head_after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.toolkit),
                                     capture_output=True, text=True).stdout.strip()
        self.assertEqual(head_before, head_after)  # unchanged

    def test_apply_swaps_and_exit_code(self):
        new = self._newer()
        proc = self._run_cli(
            "self-update", "--apply",
            "--toolkit-dir", str(self.toolkit),
            "--operator-dir", str(self.operator),
            "--to-commit", new,
        )
        self.assertEqual(proc.returncode, EXIT_UPDATE_AVAILABLE, proc.stderr + proc.stdout)
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.toolkit),
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, new)

    def test_tampered_remote_fails_closed_via_cli(self):
        _git(self.toolkit, "remote", "set-url", "origin", "https://github.com/attacker/evil.git")
        new = self._newer()
        proc = self._run_cli(
            "self-update", "--apply",
            "--toolkit-dir", str(self.toolkit),
            "--operator-dir", str(self.operator),
            "--to-commit", new,
        )
        self.assertEqual(proc.returncode, EXIT_UPDATE_SOURCE_TAMPERED, proc.stderr + proc.stdout)

    def test_shim_resolves_engine_and_runs(self):
        # The bash shim must resolve the engine relative to itself and run a subcommand.
        proc = self._run_cli(
            "self-update", "--check",
            "--toolkit-dir", str(self.toolkit),
            "--operator-dir", str(self.operator),
            "--to-commit", self.base,
            via_shim=True,
        )
        # candidate == HEAD == base -> already current
        self.assertEqual(proc.returncode, EXIT_CHECKED_CURRENT, proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
