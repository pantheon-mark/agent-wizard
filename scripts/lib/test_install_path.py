"""Tests for the best-effort `wizard install-path` shim linker (install_path.py).

All filesystem state is built in a temp dir; PATH and HOME are injected so the real
environment is never touched. Covers: links into a writable on-PATH dir; idempotent
re-run; never clobbers a real file or a foreign symlink named `wizard`; graceful no-op
when no writable PATH dir exists; preference ordering; missing-shim error.

Stdlib unittest; pip-install-free.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from install_path import install_wizard_on_path, LINK_NAME  # noqa: E402


class InstallPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # A realistic toolkit layout: $WIZARD_HOME/scripts/wizard
        self.scripts = self.root / "agent-wizard" / "scripts"
        self.scripts.mkdir(parents=True)
        self.shim = self.scripts / "wizard"
        self.shim.write_text("#!/usr/bin/env bash\n")
        self.shim.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def _bindir(self, name="bin", make=True):
        d = self.root / name
        if make:
            d.mkdir(parents=True, exist_ok=True)
        return d

    def test_links_into_writable_on_path_dir(self):
        d = self._bindir()
        res = install_wizard_on_path(str(self.shim), path_value=str(d), home=str(self.root))
        self.assertEqual(res.status, "installed")
        link = d / LINK_NAME
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), self.shim.resolve())

    def test_idempotent_rerun_reports_already_installed(self):
        d = self._bindir()
        install_wizard_on_path(str(self.shim), path_value=str(d), home=str(self.root))
        res = install_wizard_on_path(str(self.shim), path_value=str(d), home=str(self.root))
        self.assertEqual(res.status, "already_installed")
        # still exactly one link, still correct
        self.assertEqual((d / LINK_NAME).resolve(), self.shim.resolve())

    def test_never_clobbers_a_real_file_named_wizard(self):
        d = self._bindir()
        foreign = d / LINK_NAME
        foreign.write_text("i am someone else's wizard\n")
        res = install_wizard_on_path(str(self.shim), path_value=str(d), home=str(self.root))
        self.assertEqual(res.status, "conflict_skipped")
        # untouched: still a regular file with its original contents
        self.assertFalse(foreign.is_symlink())
        self.assertEqual(foreign.read_text(), "i am someone else's wizard\n")
        self.assertIn(str(foreign), res.conflicts)

    def test_never_clobbers_a_foreign_symlink(self):
        d = self._bindir()
        other = self.root / "some-other-tool"
        other.write_text("#!/bin/sh\n")
        foreign = d / LINK_NAME
        os.symlink(other, foreign)
        res = install_wizard_on_path(str(self.shim), path_value=str(d), home=str(self.root))
        self.assertEqual(res.status, "conflict_skipped")
        self.assertEqual(foreign.resolve(), other.resolve())  # still points where it did

    def test_no_writable_path_dir_is_graceful_noop(self):
        # PATH dir does not exist -> not writable -> graceful no-op, not an error
        missing = self.root / "does-not-exist"
        res = install_wizard_on_path(str(self.shim), path_value=str(missing), home=str(self.root))
        self.assertEqual(res.status, "no_writable_path_dir")
        self.assertEqual(res.conflicts, [])

    def test_prefers_local_bin_over_other_writable_dirs(self):
        local = self.root / ".local" / "bin"
        local.mkdir(parents=True)
        other = self._bindir("opt-bin")
        # other listed first in PATH, but ~/.local/bin should win by preference rank
        path_value = os.pathsep.join([str(other), str(local)])
        res = install_wizard_on_path(str(self.shim), path_value=path_value, home=str(self.root))
        self.assertEqual(res.status, "installed")
        self.assertEqual(Path(res.link_path).parent, local)
        self.assertFalse((other / LINK_NAME).exists())

    def test_already_installed_anywhere_short_circuits(self):
        # A correct link in a NON-writable-context dir still counts as already available.
        d = self._bindir()
        os.symlink(self.shim, d / LINK_NAME)
        # add a second writable dir; we must NOT create a duplicate
        d2 = self._bindir("bin2")
        path_value = os.pathsep.join([str(d), str(d2)])
        res = install_wizard_on_path(str(self.shim), path_value=path_value, home=str(self.root))
        self.assertEqual(res.status, "already_installed")
        self.assertFalse((d2 / LINK_NAME).exists())

    def test_missing_shim_is_error(self):
        d = self._bindir()
        res = install_wizard_on_path(str(self.scripts / "nope"), path_value=str(d), home=str(self.root))
        self.assertEqual(res.status, "error")


if __name__ == "__main__":
    unittest.main()
