"""Behavioral proof that `wizard upgrade-check` is REMOTE-AUTHORITATIVE and fails closed.

The headline test is `test_stale_local_mirror_does_not_mask_remote_update`: a stale LOCAL
registry that lists no newer version must NOT produce "up to date" when the AUTHORITATIVE
remote lists a newer one — the exact false "up to date" the live operator walk exposed.

The remote source is driven through the documented `WIZARD_UPDATE_REGISTRY_URL` seam pointed
at a `file://` path (no network, no real origin pin needed for the reachable cases).
"""
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # wizard/scripts (CLI)

from registry_fetch import REGISTRY_URL_OVERRIDE_ENV  # noqa: E402
from upgrade import (  # noqa: E402
    EXIT_CHECKED_CURRENT,
    EXIT_UPDATE_AVAILABLE,
    EXIT_CURRENCY_UNCONFIRMED,
    EXIT_SOURCE_UNCONFIGURED,
)

_FIXTURE = (
    Path(__file__).resolve().parents[2]  # wizard/  (lib -> scripts -> wizard)
    / "test_fixtures" / "operator_project_upgrade" / "pinned_at_older"  # current = v0.2.0
)


def _registry(*versions: str) -> str:
    return json.dumps({
        "registry_schema_version": "v2",
        "bundles": [
            {"foundation_bundle_version": v, "path": f"foundation-bundles/{v}/", "status": "prerelease"}
            for v in versions
        ],
    })


class UpgradeCheckRemoteAuthorityTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self.tmp = Path(self._td)
        # operator project (current = v0.2.0) copied from the fixture
        self.proj = self.tmp / "proj"
        shutil.copytree(_FIXTURE, self.proj)
        self.manifest_path = self.proj / ".wizard" / "manifest.json"
        # a STALE local registry mirror that knows ONLY the operator's current version
        self.stale_local = self.tmp / "stale_registry.json"
        self.stale_local.write_text(_registry("v0.2.0"), encoding="utf-8")
        self._saved_env = os.environ.get(REGISTRY_URL_OVERRIDE_ENV)

    def tearDown(self):
        if self._saved_env is None:
            os.environ.pop(REGISTRY_URL_OVERRIDE_ENV, None)
        else:
            os.environ[REGISTRY_URL_OVERRIDE_ENV] = self._saved_env
        shutil.rmtree(self._td, ignore_errors=True)

    def _set_remote(self, *versions: str) -> None:
        remote = self.tmp / "remote_registry.json"
        remote.write_text(_registry(*versions), encoding="utf-8")
        os.environ[REGISTRY_URL_OVERRIDE_ENV] = "file://" + str(remote)

    def _run_check(self) -> int:
        import wizard_upgrade as wu  # heavy module; local import
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = wu.main([
                "upgrade-check",
                "--manifest-path", str(self.manifest_path),
                "--registry-path", str(self.stale_local),
                "--json",
            ])
        self._last_out = out.getvalue()
        return rc

    def test_stale_local_mirror_does_not_mask_remote_update(self):
        """F2 headline: stale local says 'no newer', remote says v0.3.0 exists → UPDATE_AVAILABLE,
        NEVER CHECKED_CURRENT. The check trusts the authoritative remote, not the stale mirror."""
        self._set_remote("v0.2.0", "v0.3.0")
        rc = self._run_check()
        self.assertEqual(rc, EXIT_UPDATE_AVAILABLE, f"expected UPDATE_AVAILABLE; out={self._last_out}")
        self.assertNotEqual(rc, EXIT_CHECKED_CURRENT)

    def test_remote_shows_current_is_checked_current(self):
        """Remote confirms the operator's version is the latest → CHECKED_CURRENT (the ONLY
        status allowed to say 'up to date'), reached only via the remote."""
        self._set_remote("v0.2.0")
        rc = self._run_check()
        self.assertEqual(rc, EXIT_CHECKED_CURRENT, f"expected CHECKED_CURRENT; out={self._last_out}")

    def test_remote_unreachable_with_local_mirror_is_currency_unconfirmed(self):
        """Remote unreachable but a local catalog exists → CURRENCY_UNCONFIRMED (currency
        unknown), NEVER a false CHECKED_CURRENT off the stale mirror."""
        os.environ[REGISTRY_URL_OVERRIDE_ENV] = "file://" + str(self.tmp / "does_not_exist.json")
        rc = self._run_check()
        self.assertEqual(rc, EXIT_CURRENCY_UNCONFIRMED, f"expected CURRENCY_UNCONFIRMED; out={self._last_out}")
        self.assertNotEqual(rc, EXIT_CHECKED_CURRENT)

    def test_no_source_configured_is_source_unconfigured(self):
        """No override and no update-source pin in the project → SOURCE_UNCONFIGURED (cannot
        determine; never 'up to date')."""
        os.environ.pop(REGISTRY_URL_OVERRIDE_ENV, None)
        # the fixture has no .wizard/update-source.json
        rc = self._run_check()
        self.assertEqual(rc, EXIT_SOURCE_UNCONFIGURED, f"expected SOURCE_UNCONFIGURED; out={self._last_out}")


if __name__ == "__main__":
    unittest.main()
