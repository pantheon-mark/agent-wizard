"""Tests for layout-agnostic registry->bundle path resolution (operator-reach C1').

The toolkit ships two ways:

  * BUILD-REPO layout: the toolkit lives under a `wizard/` subdirectory of the repo
    root, so the registry is at `<root>/wizard/registry/foundation-bundles.json` and
    a bundle is at `<root>/wizard/foundation-bundles/<v>/`. The registry entries carry
    build-repo-rooted `path` values (`"wizard/foundation-bundles/<v>/"`).
  * PUBLIC-CLONE layout: the public distribution is a `git subtree --prefix=wizard`
    split, so in a fresh clone the SAME files sit at `<clone>/registry/...` and
    `<clone>/foundation-bundles/<v>/` with NO `wizard/` directory. The registry's
    `path` values STILL carry the build-repo `wizard/` prefix (the publish does not
    rewrite them).

These tests pin that bundle-directory resolution is registry-relative and resolves to
the SAME on-disk bundle directory in BOTH layouts, plus that resolution fails closed
when a resolved path would escape the toolkit root or when the layout is ambiguous.
"""

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Optional
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # wizard/scripts (CLI + interview_cli)

from upgrade import (  # noqa: E402
    RegistryError,
    load_registry,
    find_bundle_entry,
    resolve_bundle_dir,
    resolve_toolkit_root,
)

_VERSION = "v0.6.1"
_LEGACY_ENTRY_PATH = "wizard/foundation-bundles/v0.6.1/"


def _write_registry(registry_path: Path, *, schema_version: Optional[str], entry_path: str) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "bundles": [
            {
                "foundation_bundle_version": _VERSION,
                "path": entry_path,
                "release_date": "2026-06-21",
                "manifest": f"{entry_path}manifest.yaml",
                "status": "prerelease",
            }
        ]
    }
    if schema_version is not None:
        data["schema_version"] = schema_version
    registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_bundle_dir(toolkit_root: Path) -> Path:
    """Create the on-disk bundle directory under the toolkit root + return it."""
    bundle_dir = toolkit_root / "foundation-bundles" / _VERSION
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "manifest.yaml").write_text("foundation_bundle_version: v0.6.1\n", encoding="utf-8")
    return bundle_dir


class BuildRepoLayoutTest(unittest.TestCase):
    """The toolkit lives under `<root>/wizard/`; entry path is `wizard/`-prefixed (legacy)."""

    def test_resolves_bundle_dir_in_build_repo_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            toolkit_root = root / "wizard"
            registry_path = toolkit_root / "registry" / "foundation-bundles.json"
            _write_registry(registry_path, schema_version="v1", entry_path=_LEGACY_ENTRY_PATH)
            bundle_dir = _make_bundle_dir(toolkit_root)

            registry = load_registry(registry_path)
            entry = find_bundle_entry(registry, _VERSION)
            resolved = resolve_bundle_dir(registry_path, registry, entry)

            self.assertEqual(resolved.resolve(), bundle_dir.resolve())
            self.assertTrue(resolved.is_dir())

    def test_toolkit_root_is_registry_grandparent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            toolkit_root = root / "wizard"
            registry_path = toolkit_root / "registry" / "foundation-bundles.json"
            _write_registry(registry_path, schema_version="v1", entry_path=_LEGACY_ENTRY_PATH)
            self.assertEqual(
                resolve_toolkit_root(registry_path).resolve(), toolkit_root.resolve()
            )


class PublicCloneLayoutTest(unittest.TestCase):
    """The subtree-split clone has NO `wizard/` dir; registry + bundles sit at the clone root.

    This is the F-OR-4 layout that was un-runnable before C1': the legacy resolver
    re-prepended a `wizard/` prefix that does not exist in the public clone.
    """

    def test_resolves_bundle_dir_in_public_clone_layout(self):
        with tempfile.TemporaryDirectory() as td:
            clone_root = Path(td)  # the subtree split strips the `wizard/` prefix
            registry_path = clone_root / "registry" / "foundation-bundles.json"
            # The published registry STILL carries the build-repo `wizard/`-prefixed path.
            _write_registry(registry_path, schema_version="v1", entry_path=_LEGACY_ENTRY_PATH)
            bundle_dir = _make_bundle_dir(clone_root)

            registry = load_registry(registry_path)
            entry = find_bundle_entry(registry, _VERSION)
            resolved = resolve_bundle_dir(registry_path, registry, entry)

            self.assertEqual(resolved.resolve(), bundle_dir.resolve())
            self.assertTrue(
                resolved.is_dir(),
                f"public-clone bundle dir not found at {resolved} (F-OR-4 regression)",
            )

    def test_toolkit_root_is_clone_root(self):
        with tempfile.TemporaryDirectory() as td:
            clone_root = Path(td)
            registry_path = clone_root / "registry" / "foundation-bundles.json"
            _write_registry(registry_path, schema_version="v1", entry_path=_LEGACY_ENTRY_PATH)
            self.assertEqual(
                resolve_toolkit_root(registry_path).resolve(), clone_root.resolve()
            )


class RegistryRelativeSchemaTest(unittest.TestCase):
    """New-schema registry: bundle paths are registry-relative (no `wizard/` prefix)."""

    def test_registry_relative_path_resolves_identically_both_layouts(self):
        for layout_subdir in ("", "wizard"):
            with self.subTest(layout=layout_subdir or "public-clone"):
                with tempfile.TemporaryDirectory() as td:
                    toolkit_root = Path(td) / layout_subdir if layout_subdir else Path(td)
                    registry_path = toolkit_root / "registry" / "foundation-bundles.json"
                    _write_registry(
                        registry_path,
                        schema_version="v2",
                        entry_path=f"foundation-bundles/{_VERSION}/",
                    )
                    bundle_dir = _make_bundle_dir(toolkit_root)

                    registry = load_registry(registry_path)
                    entry = find_bundle_entry(registry, _VERSION)
                    resolved = resolve_bundle_dir(registry_path, registry, entry)
                    self.assertEqual(resolved.resolve(), bundle_dir.resolve())


class FailClosedTest(unittest.TestCase):
    """Resolution must fail closed when a resolved path escapes the toolkit root."""

    def test_escape_outside_toolkit_root_raises(self):
        with tempfile.TemporaryDirectory() as td:
            clone_root = Path(td)
            registry_path = clone_root / "registry" / "foundation-bundles.json"
            # A malicious / malformed entry that climbs out of the toolkit root.
            _write_registry(
                registry_path,
                schema_version="v1",
                entry_path="wizard/../../etc/foundation-bundles/v0.6.1/",
            )
            registry = load_registry(registry_path)
            entry = find_bundle_entry(registry, _VERSION)
            with self.assertRaises(RegistryError):
                resolve_bundle_dir(registry_path, registry, entry)

    def test_absolute_entry_path_raises(self):
        with tempfile.TemporaryDirectory() as td:
            clone_root = Path(td)
            registry_path = clone_root / "registry" / "foundation-bundles.json"
            _write_registry(
                registry_path,
                schema_version="v1",
                entry_path="/etc/foundation-bundles/v0.6.1/",
            )
            registry = load_registry(registry_path)
            entry = find_bundle_entry(registry, _VERSION)
            with self.assertRaises(RegistryError):
                resolve_bundle_dir(registry_path, registry, entry)


class RealRegistryRoundTripTest(unittest.TestCase):
    """The real shipped registry resolves under the real build-repo toolkit root."""

    def test_real_registry_resolves_real_bundle(self):
        repo_root = Path(__file__).resolve().parents[3]
        registry_path = repo_root / "wizard" / "registry" / "foundation-bundles.json"
        registry = load_registry(registry_path)
        for entry in registry["bundles"]:
            resolved = resolve_bundle_dir(registry_path, registry, entry)
            self.assertTrue(
                resolved.is_dir(),
                f"bundle {entry['foundation_bundle_version']} dir missing at {resolved}",
            )


# ===== End-to-end: the upgrade CLI runs against a real PUBLIC-CLONE toolkit =====

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_REGISTRY = _REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"
_REAL_BUNDLES = _REPO_ROOT / "wizard" / "foundation-bundles"
_TRANSCRIPT = Path.home() / "wizard-pilot-2026-06-01" / "wizard_transcript.jsonl"
_SHAPE = "markdown-CC"
_FULL_VERSION = "v0.6.0"
_TARGET_VERSION = "v0.6.1"
_GEN_OVERRIDE = "c3b5609fbbe566d73f3097ff0d1cd087dfe19245"
_PROJECT_NAME = "operator-system"


def _e2e_prereqs() -> bool:
    if not _TRANSCRIPT.exists():
        return False
    try:
        reg = load_registry(_REAL_REGISTRY)
    except Exception:
        return False
    versions = {e.get("foundation_bundle_version") for e in reg.get("bundles", [])}
    return {_FULL_VERSION, _TARGET_VERSION} <= versions


@unittest.skipUnless(
    _e2e_prereqs(),
    f"requires the preserved pilot transcript at {_TRANSCRIPT} and the "
    f"{_FULL_VERSION} + {_TARGET_VERSION} bundles",
)
class PublicCloneCliE2ETest(unittest.TestCase):
    """The real `wizard_upgrade` CLI must run against a PUBLIC-CLONE toolkit layout.

    This is the genuine F-OR-4 closure: a `git subtree --prefix=wizard` split has the
    registry at `<clone>/registry/...` and bundles at `<clone>/foundation-bundles/...`
    with NO `wizard/` directory. Before C1' the CLI re-prepended the build-repo `wizard/`
    prefix and died with `registry not found` / `bundle directory missing`. Here we build
    a real public-clone toolkit (copy registry + foundation-bundles WITHOUT the prefix),
    emit a real v0.6.0 operator project, and run the actual plan CLI against the
    public-clone registry.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _make_public_clone_toolkit(self) -> Path:
        """Mirror the subtree split: registry + bundles at the clone root, NO `wizard/`."""
        clone = self.tmp / "public-clone"
        (clone / "registry").mkdir(parents=True)
        shutil.copy2(_REAL_REGISTRY, clone / "registry" / "foundation-bundles.json")
        shutil.copytree(_REAL_BUNDLES, clone / "foundation-bundles")
        # Belt-and-braces: there must be NO `wizard/` directory in the clone.
        self.assertFalse((clone / "wizard").exists())
        return clone

    def _emit_operator_project(self) -> Path:
        import interview_cli as cli  # local import; heavy module
        proj = self.tmp / _PROJECT_NAME
        cli.cmd_emit_system(
            str(_TRANSCRIPT), _SHAPE, str(proj), str(_REPO_ROOT),
            project_name=_PROJECT_NAME, bundle_version=_FULL_VERSION,
            generator_version_override=_GEN_OVERRIDE,
        )
        return proj

    def test_plan_cli_runs_against_public_clone_registry(self):
        import wizard_upgrade as wu  # local import; heavy module
        clone = self._make_public_clone_toolkit()
        proj = self._emit_operator_project()
        public_registry = clone / "registry" / "foundation-bundles.json"
        manifest_path = proj / ".wizard" / "manifest.json"

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = wu.main([
                "upgrade", "--to", _TARGET_VERSION, "--plan-only",
                "--manifest-path", str(manifest_path),
                "--registry-path", str(public_registry),
                "--json",
            ])
        stderr = err.getvalue()
        self.assertEqual(
            rc, 0,
            f"plan CLI failed against public clone (rc={rc}); stderr:\n{stderr}",
        )
        self.assertNotIn("registry not found", stderr)
        self.assertNotIn("bundle directory", stderr.lower())
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["from_version"], _FULL_VERSION)
        self.assertEqual(payload["to_version"], _TARGET_VERSION)
        # The target-change analysis must be populated (proves the bundle dir resolved:
        # an unresolved bundle would leave artifact_analysis empty via the fail-soft path).
        self.assertTrue(
            payload.get("artifact_analysis"),
            "artifact_analysis empty -> public-clone bundle dir did not resolve",
        )

    def test_apply_cli_runs_against_public_clone_registry(self):
        """The mutating apply path also resolves + runs from the public clone (operator
        state preserved; this is the path the operator-reach skill ultimately drives)."""
        import wizard_upgrade as wu  # local import; heavy module
        clone = self._make_public_clone_toolkit()
        proj = self._emit_operator_project()
        public_registry = clone / "registry" / "foundation-bundles.json"
        manifest_path = proj / ".wizard" / "manifest.json"

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = wu.main([
                "upgrade", "--to", _TARGET_VERSION, "--apply", "--ack",
                "--manifest-path", str(manifest_path),
                "--registry-path", str(public_registry),
            ])
        stderr = err.getvalue()
        self.assertEqual(
            rc, 0,
            f"apply CLI failed against public clone (rc={rc}); stderr:\n{stderr}",
        )
        self.assertNotIn("registry not found", stderr)
        self.assertNotIn("bundle directory", stderr.lower())
        # The manifest must have advanced to the target version (apply ran to completion).
        applied = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(applied.get("foundation_bundle_version"), _TARGET_VERSION)


if __name__ == "__main__":
    unittest.main()


class RegistryDefaultIsToolkitRelativeTest(unittest.TestCase):
    """The default registry path must resolve to the TOOLKIT's own registry (engine-relative),
    so an operator running the tool from their OWN project directory (cwd != toolkit) still
    finds the version list. A cwd-relative default was the operator-channel bug."""

    def test_default_registry_resolves_to_toolkit_regardless_of_cwd(self):
        import os
        import wizard_upgrade as wu
        toolkit_root = Path(wu.__file__).resolve().parent.parent
        expected = toolkit_root / "registry" / "foundation-bundles.json"
        with tempfile.TemporaryDirectory() as d:
            old = Path.cwd()
            try:
                os.chdir(d)  # simulate the operator's own project dir (has no registry/)
                got = wu._resolve_registry_path(None)
            finally:
                os.chdir(old)
        self.assertEqual(got, expected)
        self.assertTrue(got.exists(), "default registry must point at the real toolkit registry")

    def test_explicit_registry_arg_still_wins(self):
        import wizard_upgrade as wu
        self.assertEqual(wu._resolve_registry_path("/tmp/x/y.json"), Path("/tmp/x/y.json"))
