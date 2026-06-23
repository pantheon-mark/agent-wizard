"""Tests for the shared remote-registry fetch routine (registry_fetch.fetch_remote_registry).

Pins the typed failure mapping that lets the check fail CLOSED (never a false "up to date")
and the notice fail OPEN over the SAME routine. The fetcher is injected so no test touches
the network.
"""
import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from registry_fetch import fetch_remote_registry, registry_url_from_source  # noqa: E402
from update_source import emit_update_source  # noqa: E402
from upgrade import UpdateStatus  # noqa: E402

_GOOD_REGISTRY = json.dumps({
    "registry_schema_version": "v2",
    "bundles": [
        {"foundation_bundle_version": "v0.6.1", "path": "foundation-bundles/v0.6.1/"},
        {"foundation_bundle_version": "v0.6.2", "path": "foundation-bundles/v0.6.2/"},
    ],
})


def _project_with_pin(tmp: Path) -> Path:
    """A temp operator project carrying a valid `.wizard/update-source.json` pin."""
    emit_update_source(tmp)
    return tmp


class FetchRemoteRegistryTest(unittest.TestCase):
    def test_ok_returns_parsed_registry(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project_with_pin(Path(td))
            res = fetch_remote_registry(proj, fetcher=lambda url, t: _GOOD_REGISTRY)
            self.assertTrue(res.ok)
            self.assertIsNone(res.failure_status)
            self.assertEqual(
                [b["foundation_bundle_version"] for b in res.registry["bundles"]],
                ["v0.6.1", "v0.6.2"],
            )
            # the fetched URL is the pinned raw base + the registry relpath
            self.assertTrue(res.source_url.endswith("/registry/foundation-bundles.json"))
            self.assertTrue(res.source_url.startswith("https://"))

    def test_network_failure_is_network_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project_with_pin(Path(td))
            res = fetch_remote_registry(proj, fetcher=lambda url, t: None)
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_status, UpdateStatus.NETWORK_UNAVAILABLE)
            self.assertIsNone(res.registry)

    def test_non_json_body_is_registry_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project_with_pin(Path(td))
            res = fetch_remote_registry(proj, fetcher=lambda url, t: "<html>404</html>")
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_status, UpdateStatus.REGISTRY_INVALID)

    def test_json_without_bundles_is_registry_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project_with_pin(Path(td))
            res = fetch_remote_registry(proj, fetcher=lambda url, t: json.dumps({"bundles": []}))
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_status, UpdateStatus.REGISTRY_INVALID)

    def test_missing_update_source_is_source_unconfigured(self):
        with tempfile.TemporaryDirectory() as td:
            # No pin written.
            res = fetch_remote_registry(Path(td), fetcher=lambda url, t: _GOOD_REGISTRY)
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_status, UpdateStatus.SOURCE_UNCONFIGURED)

    def test_fetcher_is_not_called_when_source_missing(self):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            fetch_remote_registry(Path(td), fetcher=lambda url, t: calls.append(url) or _GOOD_REGISTRY)
            self.assertEqual(calls, [], "must not attempt a fetch with no configured source")


class RegistryUrlFromSourceTest(unittest.TestCase):
    def test_prefers_raw_base_url(self):
        url = registry_url_from_source({"raw_base_url": "https://example/raw/o/r/main"})
        self.assertEqual(url, "https://example/raw/o/r/main/registry/foundation-bundles.json")

    def test_falls_back_to_owner_repo_branch(self):
        url = registry_url_from_source({"repo_owner": "o", "repo_name": "r", "branch": "main"})
        self.assertEqual(
            url, "https://raw.githubusercontent.com/o/r/main/registry/foundation-bundles.json"
        )

    def test_non_https_base_returns_none(self):
        self.assertIsNone(registry_url_from_source({"raw_base_url": "http://insecure/x"}))
        self.assertIsNone(registry_url_from_source({}))


if __name__ == "__main__":
    unittest.main()
