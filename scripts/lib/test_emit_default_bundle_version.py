"""Regression: emit-system must default to the registry's LATEST bundle, not a stale hardcode.

Before this fix `cmd_emit_system` defaulted `bundle_version` to a hardcoded "v0.6.0", so a
by-the-book emit (the documented 15_close.md command passes no --bundle-version) sourced the
stale v0.6.0 bundle even though the registry had advanced to v0.9.0 — making "a new build gets
the current bundle by construction" false. The upgrade path already selects the latest registry
entry; emit must reuse that so the two paths cannot drift.

RED->GREEN.
"""

import sys
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parent
_SCRIPTS = _LIB.parent
sys.path.insert(0, str(_LIB))
sys.path.insert(0, str(_SCRIPTS))

import interview_cli as cli  # noqa: E402
from bundle_templates import wizard_subroot  # noqa: E402
from upgrade import load_registry, latest_bundle_version  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


class LatestBundleVersionHelper(unittest.TestCase):
    def test_picks_semver_max_regardless_of_registry_order(self):
        # v0.10.0 > v0.9.0 by SEMVER but < by string sort — discriminates a real semver compare
        # from a naive lexical max, and from "just take bundles[-1]" if order were unsorted.
        reg = {"bundles": [
            {"foundation_bundle_version": "v0.9.0", "path": "x"},
            {"foundation_bundle_version": "v0.10.0", "path": "x"},
            {"foundation_bundle_version": "v0.6.0", "path": "x"},
        ]}
        self.assertEqual(latest_bundle_version(reg), "v0.10.0")

    def test_empty_registry_fails_closed(self):
        from upgrade import RegistryError
        with self.assertRaises(RegistryError):
            latest_bundle_version({"bundles": []})


class EmitBundleVersionResolution(unittest.TestCase):
    def test_explicit_version_is_honored(self):
        self.assertEqual(
            cli._resolve_emit_bundle_version("v0.7.0", str(REPO_ROOT)), "v0.7.0")

    def test_default_resolves_to_registry_latest_not_stale_hardcode(self):
        reg = load_registry(wizard_subroot(REPO_ROOT) / "registry" / "foundation-bundles.json")
        expected_latest = latest_bundle_version(reg)
        resolved = cli._resolve_emit_bundle_version(None, str(REPO_ROOT))
        self.assertEqual(resolved, expected_latest)
        self.assertNotEqual(resolved, "v0.6.0")  # the stale default this fix removes


if __name__ == "__main__":
    unittest.main()
