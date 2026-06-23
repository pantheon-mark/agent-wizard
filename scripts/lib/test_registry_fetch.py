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

from registry_fetch import (  # noqa: E402
    fetch_remote_registry,
    fetch_registry_at_commit,
    registry_url_from_source,
    commit_pinned_registry_url,
)
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


class RawTextAndOverrideGateTest(unittest.TestCase):
    """The resolution-creation path needs the EXACT fetched bytes (for registry_sha256) and
    must NOT honor an env-pointed source override (that would let a non-origin URL seed an
    approved resolution). The notice/check keep the override as a test/advanced seam."""

    def test_ok_carries_exact_raw_body(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project_with_pin(Path(td))
            body = _GOOD_REGISTRY + "\n   "  # exact bytes, incl. trailing whitespace
            res = fetch_remote_registry(proj, fetcher=lambda url, t: body)
            self.assertTrue(res.ok)
            self.assertEqual(res.raw_text, body,
                             "raw_text must be the exact fetched body (for registry_sha256), "
                             "not a re-serialization of the parsed dict")

    def test_url_override_honored_by_default(self):
        import os
        calls = []
        with tempfile.TemporaryDirectory() as td:
            proj = _project_with_pin(Path(td))
            os.environ["WIZARD_UPDATE_REGISTRY_URL"] = "https://override.example/x.json"
            try:
                fetch_remote_registry(
                    proj, fetcher=lambda url, t: calls.append(url) or _GOOD_REGISTRY)
            finally:
                del os.environ["WIZARD_UPDATE_REGISTRY_URL"]
            self.assertEqual(calls, ["https://override.example/x.json"],
                             "default behavior keeps the override seam for notice/check")

    def test_url_override_ignored_when_disallowed(self):
        import os
        calls = []
        with tempfile.TemporaryDirectory() as td:
            proj = _project_with_pin(Path(td))
            os.environ["WIZARD_UPDATE_REGISTRY_URL"] = "https://override.example/x.json"
            try:
                fetch_remote_registry(
                    proj, fetcher=lambda url, t: calls.append(url) or _GOOD_REGISTRY,
                    allow_url_override=False)
            finally:
                del os.environ["WIZARD_UPDATE_REGISTRY_URL"]
            self.assertEqual(len(calls), 1)
            self.assertTrue(
                calls[0].endswith("/registry/foundation-bundles.json")
                and calls[0].startswith("https://") and "override.example" not in calls[0],
                f"resolution-creation must resolve ONLY from the origin pin, not the env "
                f"override; got {calls[0]!r}")


class FetchRegistryAtCommitTest(unittest.TestCase):
    """Option A+: the resolution must hash the registry AT the resolved commit (a commit-pinned
    raw URL), so registry_sha256 is reproducible against the local registry self-update sees
    after `git checkout <commit>` — a bare @branch fetch could desync if the branch advances."""

    _COMMIT = "deadbeef" * 5  # 40-hex

    def test_builds_commit_pinned_url_and_carries_raw(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _project_with_pin(Path(td))  # pin -> pantheon-mark/agent-wizard
            seen = []
            res = fetch_registry_at_commit(
                proj, self._COMMIT,
                fetcher=lambda url, t: seen.append(url) or _GOOD_REGISTRY)
            self.assertTrue(res.ok)
            self.assertEqual(res.raw_text, _GOOD_REGISTRY)
            self.assertEqual(
                seen,
                [f"https://raw.githubusercontent.com/pantheon-mark/agent-wizard/"
                 f"{self._COMMIT}/registry/foundation-bundles.json"])

    def test_ignores_url_override_env(self):
        """Commit-pinned fetch is a resolution-creation path: it must NOT honor the env seam."""
        import os
        seen = []
        with tempfile.TemporaryDirectory() as td:
            proj = _project_with_pin(Path(td))
            os.environ["WIZARD_UPDATE_REGISTRY_URL"] = "https://override.example/x.json"
            try:
                fetch_registry_at_commit(
                    proj, self._COMMIT, fetcher=lambda url, t: seen.append(url) or _GOOD_REGISTRY)
            finally:
                del os.environ["WIZARD_UPDATE_REGISTRY_URL"]
            self.assertIn(self._COMMIT, seen[0])
            self.assertNotIn("override.example", seen[0])

    def test_no_pin_is_source_unconfigured(self):
        with tempfile.TemporaryDirectory() as td:
            res = fetch_registry_at_commit(Path(td), self._COMMIT, fetcher=lambda url, t: _GOOD_REGISTRY)
            self.assertFalse(res.ok)
            self.assertEqual(res.failure_status, UpdateStatus.SOURCE_UNCONFIGURED)


class CommitPinnedUrlTest(unittest.TestCase):
    def test_builds_from_owner_repo_commit(self):
        url = commit_pinned_registry_url({"repo_owner": "o", "repo_name": "r"}, "abc123")
        self.assertEqual(
            url, "https://raw.githubusercontent.com/o/r/abc123/registry/foundation-bundles.json")

    def test_missing_fields_returns_none(self):
        self.assertIsNone(commit_pinned_registry_url({"repo_owner": "o"}, "abc"))
        self.assertIsNone(commit_pinned_registry_url({"repo_owner": "o", "repo_name": "r"}, ""))


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
