"""When `upgrade-plan`/`upgrade --to V` misses in the LOCAL toolkit registry,
the CLI must NOT emit a bare 'not in registry' (which the assistant read as 'prerelease / no
notes -> hold off'). It classifies the miss against the AUTHORITATIVE remote and routes:
  - remote HAS V, local lacks it  -> TOOLKIT_BEHIND + route to `self-upgrade`
  - remote lacks V too            -> VERSION_NOT_FOUND (honest)
  - remote unreachable            -> CURRENCY_UNCONFIRMED (never 'not found')

Remote is driven through the documented WIZARD_UPDATE_REGISTRY_URL seam (file://, no network).
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

_FIXTURE = (
    Path(__file__).resolve().parents[2]
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


class PlanMissRoutingTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.mkdtemp()
        self.tmp = Path(self._td)
        self.proj = self.tmp / "proj"
        shutil.copytree(_FIXTURE, self.proj)
        self.manifest_path = self.proj / ".wizard" / "manifest.json"
        # STALE local registry mirror — knows ONLY the operator's current version.
        self.stale_local = self.tmp / "stale_registry.json"
        self.stale_local.write_text(_registry("v0.2.0"), encoding="utf-8")
        self._saved = os.environ.get(REGISTRY_URL_OVERRIDE_ENV)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(REGISTRY_URL_OVERRIDE_ENV, None)
        else:
            os.environ[REGISTRY_URL_OVERRIDE_ENV] = self._saved
        shutil.rmtree(self._td, ignore_errors=True)

    def _set_remote(self, *versions: str) -> None:
        remote = self.tmp / "remote_registry.json"
        remote.write_text(_registry(*versions), encoding="utf-8")
        os.environ[REGISTRY_URL_OVERRIDE_ENV] = "file://" + str(remote)

    def _plan(self, target: str):
        import wizard_upgrade as wu
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = wu.main(["upgrade-plan", "--to", target,
                          "--manifest-path", str(self.manifest_path),
                          "--registry-path", str(self.stale_local)])
        return rc, out.getvalue() + err.getvalue()

    def test_toolkit_behind_routes_to_self_upgrade(self):
        # remote HAS v0.6.4, local mirror does not -> TOOLKIT_BEHIND + self-upgrade route.
        self._set_remote("v0.2.0", "v0.6.4")
        rc, text = self._plan("v0.6.4")
        self.assertNotEqual(rc, 0)
        self.assertIn("TOOLKIT_BEHIND", text)
        self.assertIn("self-upgrade --to v0.6.4 --apply", text)
        self.assertNotIn("not in registry", text)  # the old bare error must be gone

    def test_version_not_found_when_remote_lacks_it(self):
        self._set_remote("v0.2.0", "v0.6.4")
        rc, text = self._plan("v9.9.9")
        self.assertNotEqual(rc, 0)
        self.assertIn("VERSION_NOT_FOUND", text)

    def test_currency_unconfirmed_when_remote_unreachable(self):
        # point the override at a nonexistent file:// so the fetch fails.
        os.environ[REGISTRY_URL_OVERRIDE_ENV] = "file://" + str(self.tmp / "does_not_exist.json")
        rc, text = self._plan("v0.6.4")
        self.assertNotEqual(rc, 0)
        self.assertIn("CURRENCY_UNCONFIRMED", text)
        self.assertNotIn("VERSION_NOT_FOUND", text)  # must NOT claim it doesn't exist


if __name__ == "__main__":
    unittest.main()
