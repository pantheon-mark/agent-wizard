"""Contract tests for the REAL published registry (`wizard/registry/foundation-bundles.json`).

The registry is hand-maintained. A live operator-channel walk showed an operator system
fetching the public registry and 404-ing on bundle files because the entry `path` carried
the build-repo `wizard/` prefix that the subtree publish strips. The resolver
(`resolve_bundle_dir`) supports a toolkit-relative V2 schema; these tests pin the SHIPPED
registry to V2 so its paths are correct for the public clone, and require a per-entry
`changelog` so an upgrade preview has real "what's new" content.

These guard the data file itself (a future hand-edit re-introducing a V1 / `wizard/`-prefixed
path, or adding a bundle with no changelog, fails here).
"""

import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upgrade import (  # noqa: E402
    REGISTRY_SCHEMA_V2,
    load_registry,
    resolve_bundle_dir,
    resolve_toolkit_root,
    _registry_schema_version,
)

# wizard/scripts/lib/ -> parents[2] == wizard/ (the toolkit root in the build repo)
_TOOLKIT_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _TOOLKIT_ROOT / "registry" / "foundation-bundles.json"


class PublishedRegistryContractTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(_REGISTRY_PATH.is_file(), f"registry not found at {_REGISTRY_PATH}")
        self.registry = load_registry(_REGISTRY_PATH)
        self.bundles = self.registry.get("bundles") or []
        self.assertTrue(self.bundles, "published registry has no bundles")

    def test_registry_is_schema_v2(self):
        """The shipped registry declares V2 so the resolver treats paths as toolkit-relative."""
        self.assertEqual(_registry_schema_version(self.registry), REGISTRY_SCHEMA_V2)

    def test_every_entry_path_is_toolkit_relative(self):
        """No `wizard/` build-repo prefix (it 404s on the subtree-published public clone),
        not absolute, and rooted at `foundation-bundles/`."""
        for entry in self.bundles:
            version = entry.get("foundation_bundle_version", "<unknown>")
            path = entry.get("path", "")
            with self.subTest(version=version):
                self.assertTrue(path, f"{version}: empty path")
                self.assertFalse(
                    path.startswith("wizard/"),
                    f"{version}: path {path!r} carries the build-repo `wizard/` prefix "
                    f"(404s on the public clone); use toolkit-relative `foundation-bundles/...`",
                )
                self.assertFalse(path.startswith("/"), f"{version}: path {path!r} is absolute")
                self.assertTrue(
                    path.startswith("foundation-bundles/"),
                    f"{version}: path {path!r} must be rooted at `foundation-bundles/`",
                )
                manifest = entry.get("manifest", "")
                self.assertFalse(
                    manifest.startswith("wizard/"),
                    f"{version}: manifest {manifest!r} carries the `wizard/` prefix",
                )

    def test_every_entry_has_changelog(self):
        """An upgrade preview reads `changelog` from the entry; without it 'what's new' is empty."""
        for entry in self.bundles:
            version = entry.get("foundation_bundle_version", "<unknown>")
            with self.subTest(version=version):
                changelog = entry.get("changelog")
                self.assertIsInstance(changelog, str, f"{version}: missing `changelog` string")
                self.assertTrue(changelog.strip(), f"{version}: empty `changelog`")

    def test_v2_paths_resolve_to_real_bundle_dirs_in_build_repo(self):
        """Sanity: the V2 toolkit-relative paths resolve (build-repo layout) to dirs that exist."""
        toolkit_root = resolve_toolkit_root(_REGISTRY_PATH)
        self.assertEqual(toolkit_root, _TOOLKIT_ROOT)
        for entry in self.bundles:
            version = entry.get("foundation_bundle_version", "<unknown>")
            with self.subTest(version=version):
                resolved = resolve_bundle_dir(_REGISTRY_PATH, self.registry, entry)
                self.assertTrue(
                    resolved.is_dir(),
                    f"{version}: resolved bundle dir {resolved} does not exist",
                )


if __name__ == "__main__":
    unittest.main()
