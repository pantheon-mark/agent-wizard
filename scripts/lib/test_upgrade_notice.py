"""Tests for wizard/templates/claude_config/upgrade_notice.sh (stdlib unittest; pip-free).

Drives the script directly via subprocess with synthetic .wizard/manifest.json files
and a local fixture file as the registry source (via UPGRADE_NOTICE_REGISTRY_URL env
override pointing at a file:// URL, or UPGRADE_NOTICE_REGISTRY_FILE for a plain path).

Test seam: the script honours the env var UPGRADE_NOTICE_REGISTRY_URL to override the
default public registry URL. By pointing it at an unreachable URL or a file:// path,
the tests run deterministically without a real network connection.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Repo root for resolving the script path.
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "wizard" / "templates" / "claude_config" / "upgrade_notice.sh"


def _run_script(project_dir: Path, env_overrides: dict) -> subprocess.CompletedProcess:
    """Run upgrade_notice.sh with the given project dir and env overrides."""
    env = {**os.environ, "HOME": str(project_dir), **env_overrides}
    # The script reads .wizard/manifest.json relative to its working dir.
    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        cwd=str(project_dir),
        env=env,
    )


def _write_manifest(project_dir: Path, version: str) -> None:
    wizard_dir = project_dir / ".wizard"
    wizard_dir.mkdir(exist_ok=True)
    (wizard_dir / "manifest.json").write_text(
        json.dumps({"foundation_bundle_version": version}),
        encoding="utf-8",
    )


def _write_registry_fixture(registry_dir: Path, versions: list) -> Path:
    """Write a local registry JSON fixture. Returns the file path.

    Uses the SAME key the live public registry uses (`foundation_bundle_version`);
    a fixture keyed differently would let the script silently never fire against
    the real registry while the test passed (a false-green). The
    RegistryShapeGuardTest below pins this to the real registry on disk.
    """
    bundles = [{"foundation_bundle_version": v} for v in versions]
    registry = {"bundles": bundles}
    p = registry_dir / "foundation-bundles.json"
    p.write_text(json.dumps(registry), encoding="utf-8")
    return p


def _project_files(project_dir: Path) -> set:
    """Return the set of file paths inside project_dir, excluding Python bytecode
    caches that Python itself writes under Library/Caches when HOME is set to tmpdir."""
    result = set()
    for f in project_dir.rglob("*"):
        if not f.is_file():
            continue
        # Skip __pycache__ and .pyc files — Python cache files written by the
        # interpreter, not by the script under test.
        parts = f.parts
        if "__pycache__" in parts or f.suffix == ".pyc":
            continue
        # Skip Apple-style python bytecode cache under Library/Caches.
        if "Library" in parts and "Caches" in parts:
            continue
        result.add(str(f))
    return result


class UpgradeNoticeOfflineTest(unittest.TestCase):
    """Script exits 0 silently when the network is unavailable."""

    def test_notice_graceful_offline(self):
        """Pointing at an unreachable URL: exits 0 with no output and no file changes."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_manifest(project_dir, "v0.6.0")
            # Use an invalid/unreachable URL to simulate offline.
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": "http://127.0.0.1:19999/unreachable.json",
            })
            self.assertEqual(result.returncode, 0,
                             f"script should exit 0 on network failure; got {result.returncode}. "
                             f"stderr: {result.stderr}")
            self.assertEqual(result.stdout.strip(), "",
                             f"script should print nothing on failure; got: {result.stdout!r}")
            # No new files written (excluding python bytecode caches).
            non_manifest = [
                p for p in _project_files(project_dir)
                if not p.endswith("manifest.json")
            ]
            self.assertEqual(non_manifest, [],
                             f"script wrote unexpected files: {non_manifest}")


class UpgradeNoticeNewerAvailableTest(unittest.TestCase):
    """Script prints a plain-language notice when a newer version is available."""

    def test_notice_prints_when_newer_available(self):
        """With a mock registry showing v0.6.1 and local at v0.6.0, prints a notice."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            registry_dir = Path(td)
            _write_manifest(project_dir, "v0.6.0")
            registry_file = _write_registry_fixture(registry_dir, ["v0.6.0", "v0.6.1"])
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": f"file://{registry_file}",
            })
            self.assertEqual(result.returncode, 0,
                             f"unexpected exit code {result.returncode}; stderr: {result.stderr}")
            output = result.stdout.strip()
            self.assertNotEqual(output, "",
                                "expected a notice but got no output")
            # Must name the newer version.
            self.assertIn("v0.6.1", output,
                          f"notice should name the newer version; got: {output!r}")
            # Must not be technical jargon — check for plain-language cues.
            lower = output.lower()
            self.assertTrue(
                any(phrase in lower for phrase in (
                    "newer version", "new version", "update available", "upgrade available"
                )),
                f"notice should mention 'newer version' or similar; got: {output!r}",
            )
            # Must tell the operator what to do next (review command mention).
            self.assertIn("upgrade", lower,
                          f"notice should mention how to review/apply the upgrade; got: {output!r}")

    def test_notice_includes_review_command(self):
        """The notice includes a concrete command the operator can copy-paste."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            registry_dir = Path(td)
            _write_manifest(project_dir, "v0.6.0")
            registry_file = _write_registry_fixture(registry_dir, ["v0.6.0", "v0.6.1"])
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": f"file://{registry_file}",
            })
            output = result.stdout.strip()
            # The notice should show a wizard_upgrade.py command.
            self.assertIn("wizard_upgrade.py", output,
                          f"notice should include the review command; got: {output!r}")


class UpgradeNoticeCurrentTest(unittest.TestCase):
    """Script exits 0 silently when the local version is current."""

    def test_notice_silent_when_current(self):
        """When registry latest == local version, exits 0 with no output."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            registry_dir = Path(td)
            _write_manifest(project_dir, "v0.6.0")
            registry_file = _write_registry_fixture(registry_dir, ["v0.6.0"])
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": f"file://{registry_file}",
            })
            self.assertEqual(result.returncode, 0,
                             f"unexpected exit code {result.returncode}; stderr: {result.stderr}")
            self.assertEqual(result.stdout.strip(), "",
                             f"should be silent when current; got: {result.stdout!r}")

    def test_notice_silent_when_local_is_newer(self):
        """When local version is ahead of registry, exits 0 with no output."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            registry_dir = Path(td)
            _write_manifest(project_dir, "v0.6.1")
            registry_file = _write_registry_fixture(registry_dir, ["v0.6.0"])
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": f"file://{registry_file}",
            })
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "",
                             f"should be silent when local is newer; got: {result.stdout!r}")


class UpgradeNoticeReadOnlyTest(unittest.TestCase):
    """Script never writes files and never eval's fetched content."""

    def test_notice_read_only(self):
        """After running with a newer version available, no files are changed or created."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            registry_dir = Path(td)
            _write_manifest(project_dir, "v0.6.0")
            registry_file = _write_registry_fixture(registry_dir, ["v0.6.0", "v0.6.1"])
            # Record files before (excluding Python bytecode caches).
            files_before = {p: Path(p).read_bytes() for p in _project_files(project_dir)}
            _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": f"file://{registry_file}",
            })
            # Check no new files were written (beyond what existed before, excl. caches).
            files_after = _project_files(project_dir)
            new_files = files_after - set(files_before.keys())
            self.assertEqual(new_files, set(),
                             f"script wrote new files: {new_files}")
            # Check existing files were not modified.
            for path_str, before_bytes in files_before.items():
                p = Path(path_str)
                if not p.is_file():
                    continue
                after_bytes = p.read_bytes()
                self.assertEqual(before_bytes, after_bytes,
                                 f"script modified file: {path_str}")

    def test_script_contains_no_eval_of_fetched_content(self):
        """The script source must not exec/eval fetched network content."""
        script_text = SCRIPT_PATH.read_text(encoding="utf-8")
        # 'eval' of fetched content would be a security issue. We permit 'eval'
        # as a keyword only if not being used on fetched data. The safest check:
        # the script must not pass the fetched body to eval/exec directly.
        # We grep for the dangerous pattern rather than banning 'eval' entirely
        # (it may appear in comments/strings).
        lower = script_text.lower()
        # Check there is no "eval $(...curl...)" or "eval $fetch" pattern.
        import re
        # Match eval followed by something that resembles a fetch variable.
        dangerous_eval = re.search(r'\beval\s+\$\(?.*?(?:curl|wget|fetch|registry)\b',
                                   script_text, re.IGNORECASE | re.DOTALL)
        self.assertIsNone(dangerous_eval,
                          "script appears to eval fetched content — security issue")


class UpgradeNoticeMissingManifestTest(unittest.TestCase):
    """Script exits 0 silently when .wizard/manifest.json is absent or unreadable."""

    def test_graceful_when_no_manifest(self):
        """When .wizard/manifest.json is absent, exits 0 silently."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            # No manifest written.
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": "http://127.0.0.1:19999/unreachable.json",
            })
            self.assertEqual(result.returncode, 0,
                             f"should exit 0 when manifest absent; stderr: {result.stderr}")
            self.assertEqual(result.stdout.strip(), "")

    def test_graceful_when_manifest_has_no_version_field(self):
        """When manifest.json exists but lacks foundation_bundle_version, exits 0 silently."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            wizard_dir = project_dir / ".wizard"
            wizard_dir.mkdir()
            (wizard_dir / "manifest.json").write_text(
                json.dumps({"other_field": "value"}), encoding="utf-8"
            )
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": "http://127.0.0.1:19999/unreachable.json",
            })
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")


class UpgradeNoticeScriptSyntaxTest(unittest.TestCase):
    """The script must pass bash -n (syntax check) cleanly."""

    def test_bash_syntax_clean(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT_PATH)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0,
                         f"bash -n failed on upgrade_notice.sh: {result.stderr}")


class RegistryShapeGuardTest(unittest.TestCase):
    """Pin the notice to the REAL on-disk registry shape, not a hand-built fixture.

    The notice reads each bundle's version from `foundation_bundle_version` (the live
    registry key). If the script ever reverts to a different key, this test fails
    because the notice would silently never fire against the real registry — a
    false-green that a same-shape mock fixture cannot catch.
    """

    REAL_REGISTRY = REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"

    def test_real_registry_uses_expected_version_key(self):
        reg = json.loads(self.REAL_REGISTRY.read_text(encoding="utf-8"))
        bundles = reg.get("bundles") or []
        self.assertTrue(bundles, "real registry has no bundles")
        for b in bundles:
            self.assertIn("foundation_bundle_version", b,
                          "real registry bundle entry lacks foundation_bundle_version — "
                          "the notice's version-key read must match this shape")

    def test_notice_fires_against_the_real_registry(self):
        """Run the notice against the real registry file with a below-all local version;
        it must fire and name a newer version (proves the real key is read)."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_manifest(project_dir, "v0.0.1")
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": "file://" + str(self.REAL_REGISTRY),
            })
            self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
            self.assertIn("newer version", result.stdout,
                          f"notice did not fire against the real registry (key mismatch?); "
                          f"stdout: {result.stdout!r}")


if __name__ == "__main__":
    unittest.main()
