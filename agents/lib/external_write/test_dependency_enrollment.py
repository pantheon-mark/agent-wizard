"""Tests for capability third-party dependency enrollment (Cut 1.4, Task 5 /
F-9). Stdlib unittest, pip-install-free -- every pip/network call is
injected via a stub `installer`/`version_resolver`, never a real subprocess
or network round trip.

Requires Python 3.10+ (``sys.stdlib_module_names``) -- this project's own
``.venv`` floor is 3.11 (see ``start_session_template.sh``), well above it.
Run explicitly with a modern interpreter if the ambient `python3` is older,
e.g.: `python3.12 -m unittest test_dependency_enrollment`.
"""

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

_EXTERNAL_WRITE_DIR = Path(__file__).resolve().parent
_LIB_DIR = _EXTERNAL_WRITE_DIR.parent  # agents/lib -- external_write is a package under here
sys.path.insert(0, str(_LIB_DIR))

from external_write import dependency_enrollment as de  # type: ignore  # noqa: E402


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _stub_resolver(fixed_version="2.149.0"):
    return lambda package_name: fixed_version


class EnrollDependencyTests(unittest.TestCase):
    """Step 1 -- the enrollment test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_googleapiclient_resolves_to_google_api_python_client(self):
        self.assertEqual(
            de.resolve_package_name("googleapiclient"), "google-api-python-client")

    def test_enroll_writes_manifest_entry_with_pinned_version(self):
        result = de.enroll_dependency(
            self.project_root, "googleapiclient", "acme_gcal_sync",
            version_resolver=_stub_resolver("2.149.0"))

        self.assertEqual(result.package_name, "google-api-python-client")
        self.assertEqual(result.version, "2.149.0")
        self.assertTrue(result.manifest_path.is_file())

        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 1)
        entry = manifest[0]
        self.assertEqual(entry["import_name"], "googleapiclient")
        self.assertEqual(entry["package_name"], "google-api-python-client")
        self.assertEqual(entry["version"], "2.149.0")
        self.assertEqual(entry["capability_id"], "acme_gcal_sync")

    def test_enroll_re_renders_requirements_txt_containing_the_package(self):
        result = de.enroll_dependency(
            self.project_root, "googleapiclient", "acme_gcal_sync",
            version_resolver=_stub_resolver("2.149.0"))

        text = result.requirements_path.read_text(encoding="utf-8")
        self.assertIn("google-api-python-client==2.149.0", text)
        # The static preamble must still be present, verbatim, at the top.
        self.assertTrue(text.startswith(de.DEFAULT_PREAMBLE))

    def test_enroll_preserves_pre_existing_operator_added_package_line(self):
        """No-clobber: an operator-added package line already in
        requirements.txt survives a re-render untouched (Locked design #4)."""
        requirements_path = self.project_root / "requirements.txt"
        requirements_path.write_text(
            de.DEFAULT_PREAMBLE + "\nrequests==2.32.3\n", encoding="utf-8")

        result = de.enroll_dependency(
            self.project_root, "googleapiclient", "acme_gcal_sync",
            version_resolver=_stub_resolver("2.149.0"))

        text = result.requirements_path.read_text(encoding="utf-8")
        self.assertIn("requests==2.32.3", text)
        self.assertIn("google-api-python-client==2.149.0", text)

    def test_enroll_manifest_wins_when_operator_line_names_the_same_package(self):
        """If the operator already hand-added the SAME package the manifest
        also enrolls, the manifest's own pin wins -- no duplicate line."""
        requirements_path = self.project_root / "requirements.txt"
        requirements_path.write_text(
            de.DEFAULT_PREAMBLE + "\ngoogle-api-python-client==2.100.0\n",
            encoding="utf-8")

        result = de.enroll_dependency(
            self.project_root, "googleapiclient", "acme_gcal_sync",
            version_resolver=_stub_resolver("2.149.0"))

        text = result.requirements_path.read_text(encoding="utf-8")
        self.assertEqual(text.count("google-api-python-client=="), 1)
        self.assertIn("google-api-python-client==2.149.0", text)
        self.assertNotIn("2.100.0", text)

    def test_re_enrolling_same_import_replaces_not_duplicates(self):
        de.enroll_dependency(self.project_root, "googleapiclient", "acme_gcal_sync",
                             version_resolver=_stub_resolver("2.140.0"))
        result = de.enroll_dependency(self.project_root, "googleapiclient", "acme_gcal_sync",
                                      version_resolver=_stub_resolver("2.149.0"))

        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["version"], "2.149.0")

    def test_unmapped_import_defaults_to_identity_package_name(self):
        result = de.enroll_dependency(
            self.project_root, "requests", "some_capability",
            version_resolver=_stub_resolver("2.32.3"))
        self.assertEqual(result.package_name, "requests")


class SaveManifestAtomicWriteTests(unittest.TestCase):
    """Cut 1.4 fold (Finding #2 -- non-blocking minor): `save_manifest` must
    write ``operator_requirements.json`` atomically (temp file in the same
    directory, then ``os.replace``) so a crash mid-write can never leave a
    truncated/partial manifest on disk -- the operator's durable F-9
    dependency record either fully updates or is left exactly as it was."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.external_write_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_uses_a_temp_file_in_the_same_directory_then_replaces(self):
        """A real crash mid-write is exercised below by forcing os.replace to
        raise; this test pins the mechanism itself -- a temp file is created
        in the SAME directory as the manifest (never elsewhere, so the final
        `os.replace` is guaranteed same-filesystem/atomic) and no temp file
        survives a successful write."""
        seen_tmp_names = []
        real_mkstemp = tempfile.mkstemp

        def _spying_mkstemp(*args, **kwargs):
            fd, name = real_mkstemp(*args, **kwargs)
            seen_tmp_names.append(name)
            return fd, name

        with unittest.mock.patch.object(de.tempfile, "mkstemp", _spying_mkstemp):
            de.save_manifest(self.external_write_dir, [
                de.DependencyEntry("googleapiclient", "google-api-python-client",
                                    "2.149.0", "acme_gcal_sync"),
            ])

        self.assertEqual(len(seen_tmp_names), 1)
        tmp_path = Path(seen_tmp_names[0])
        self.assertEqual(
            tmp_path.parent.resolve(), self.external_write_dir.resolve(),
            "the temp file must be created in the SAME directory as the "
            "final manifest so os.replace is atomic (same filesystem)")
        self.assertFalse(
            tmp_path.exists(),
            "the temp file must not survive a successful write -- it is "
            "renamed onto the final manifest path by os.replace")

    def test_interrupted_write_leaves_prior_manifest_intact(self):
        """Simulate a crash AFTER the temp file is fully written but BEFORE
        the atomic rename lands (os.replace raises) -- the prior manifest
        content must be completely untouched, never partially overwritten or
        truncated."""
        de.save_manifest(self.external_write_dir, [
            de.DependencyEntry("googleapiclient", "google-api-python-client",
                                "2.140.0", "acme_gcal_sync"),
        ])
        manifest_path = self.external_write_dir / de.MANIFEST_BASENAME
        original_text = manifest_path.read_text(encoding="utf-8")

        with unittest.mock.patch.object(
            de.os, "replace", side_effect=OSError("simulated crash mid-write"),
        ):
            with self.assertRaises(OSError):
                de.save_manifest(self.external_write_dir, [
                    de.DependencyEntry("googleapiclient", "google-api-python-client",
                                        "2.149.0", "acme_gcal_sync"),
                ])

        self.assertEqual(
            manifest_path.read_text(encoding="utf-8"), original_text,
            "an interrupted write (crash before the atomic rename lands) "
            "must leave the prior manifest completely intact")

        leftover_tmp_files = [
            p for p in self.external_write_dir.iterdir()
            if p.name != de.MANIFEST_BASENAME
        ]
        self.assertEqual(
            leftover_tmp_files, [],
            "the temp file must be cleaned up even when the replace itself "
            f"fails; found leftover: {leftover_tmp_files}")


class RequirementsTxtEmptyManifestBackCompatTests(unittest.TestCase):
    """render_requirements_txt with no entries and no pre-existing extra
    lines must be byte-identical to the preamble alone."""

    def test_empty_manifest_byte_identical_to_preamble(self):
        rendered = de.render_requirements_txt(de.DEFAULT_PREAMBLE, [])
        self.assertEqual(rendered, de.DEFAULT_PREAMBLE)

    def test_empty_manifest_with_only_preamble_existing_text_stays_identical(self):
        rendered = de.render_requirements_txt(de.DEFAULT_PREAMBLE, [],
                                              existing_text=de.DEFAULT_PREAMBLE)
        self.assertEqual(rendered, de.DEFAULT_PREAMBLE)


class IdempotentInstallFailureTests(unittest.TestCase):
    """Step 3 -- a simulated pip failure yields an "enrolled but unsatisfied"
    state that a clean retry resolves; enrollment is never lost."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmp.name)
        (self.project_root / ".venv" / "bin").mkdir(parents=True)
        (self.project_root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_pip_failure_reports_enrolled_but_unsatisfied(self):
        failing_installer = lambda args: _FakeProc(returncode=1, stderr="No matching distribution found")  # noqa: E731

        status = de.enroll_and_install(
            self.project_root, "googleapiclient", "acme_gcal_sync",
            version_resolver=_stub_resolver("2.149.0"), installer=failing_installer)

        self.assertTrue(status.enrolled)
        self.assertFalse(status.environment_satisfied)
        self.assertIn("dependency enrolled, environment unsatisfied", status.message)
        self.assertIn("No matching distribution found", status.message)

        # The manifest write is NOT lost -- it happened before install ran.
        manifest = json.loads(status.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["import_name"], "googleapiclient")

    def test_retry_after_fixing_environment_resolves_cleanly_without_duplication(self):
        failing_installer = lambda args: _FakeProc(returncode=1, stderr="network unreachable")  # noqa: E731
        first = de.enroll_and_install(
            self.project_root, "googleapiclient", "acme_gcal_sync",
            version_resolver=_stub_resolver("2.149.0"), installer=failing_installer)
        self.assertFalse(first.environment_satisfied)

        succeeding_installer = lambda args: _FakeProc(returncode=0, stdout="")  # noqa: E731
        second = de.enroll_and_install(
            self.project_root, "googleapiclient", "acme_gcal_sync",
            version_resolver=_stub_resolver("2.149.0"), installer=succeeding_installer)

        self.assertTrue(second.enrolled)
        self.assertTrue(second.environment_satisfied)
        self.assertIn("installed", second.message)

        manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(manifest), 1, "the retry must not duplicate the manifest entry")

    def test_missing_venv_reports_unsatisfied_with_fix_instruction(self):
        project_root = Path(tempfile.mkdtemp())  # no .venv at all
        try:
            status = de.enroll_and_install(
                project_root, "googleapiclient", "acme_gcal_sync",
                version_resolver=_stub_resolver("2.149.0"))
            self.assertFalse(status.environment_satisfied)
            self.assertIn("start-session.sh", status.message)
        finally:
            import shutil
            shutil.rmtree(project_root, ignore_errors=True)

    def test_successful_install_writes_lock_file_from_pip_freeze(self):
        calls = []

        def installer(args):
            calls.append(args)
            if "freeze" in args:
                return _FakeProc(returncode=0,
                                 stdout="google-api-python-client==2.149.0\ncertifi==2024.8.30\n")
            return _FakeProc(returncode=0)

        status = de.enroll_and_install(
            self.project_root, "googleapiclient", "acme_gcal_sync",
            version_resolver=_stub_resolver("2.149.0"), installer=installer)

        self.assertTrue(status.environment_satisfied)
        self.assertIsNotNone(status.lock_path)
        lock_text = status.lock_path.read_text(encoding="utf-8")
        self.assertIn("google-api-python-client==2.149.0", lock_text)
        self.assertIn("certifi==2024.8.30", lock_text)

    def test_audit_note_records_what_and_when(self):
        succeeding_installer = lambda args: _FakeProc(returncode=0)  # noqa: E731
        status = de.enroll_and_install(
            self.project_root, "googleapiclient", "acme_gcal_sync",
            version_resolver=_stub_resolver("2.149.0"), installer=succeeding_installer)

        audit_path = (self.project_root / de.DEFAULT_EXTERNAL_WRITE_REL
                     / de.AUDIT_LOG_BASENAME)
        self.assertTrue(audit_path.is_file())
        text = audit_path.read_text(encoding="utf-8")
        self.assertIn("google-api-python-client==2.149.0", text)
        self.assertIn("acme_gcal_sync", text)
        self.assertIn(status.message.split(":")[0], "dependency enrolled and installed")


class StdlibLintTests(unittest.TestCase):
    """Step 4 -- the build-time stdlib lint (reliability flag, not a gate)."""

    def test_non_stdlib_unenrolled_import_is_flagged(self):
        source = "import requests\n\ndef f():\n    return requests.get('x')\n"
        flagged = de.lint_adapter_imports(source, enrolled_import_names=[])
        self.assertEqual(flagged, ["requests"])

    def test_stdlib_import_is_not_flagged(self):
        source = "import json\nimport os\nfrom pathlib import Path\n"
        flagged = de.lint_adapter_imports(source, enrolled_import_names=[])
        self.assertEqual(flagged, [])

    def test_enrolled_package_import_is_not_flagged(self):
        source = "import googleapiclient.discovery\n"
        flagged = de.lint_adapter_imports(source, enrolled_import_names=["googleapiclient"])
        self.assertEqual(flagged, [])

    def test_mixed_source_flags_only_the_unenrolled_non_stdlib_name(self):
        source = (
            "import json\n"
            "import requests\n"
            "import googleapiclient.discovery\n"
            "from external_write.adapter_registry import register_adapter\n"
        )
        flagged = de.lint_adapter_imports(source, enrolled_import_names=["googleapiclient"])
        self.assertEqual(flagged, ["requests"],
                         "a sibling project import (external_write.*) is local first-party, "
                         "never a vendor dependency, so it must never be flagged")

    def test_lint_adapter_file_reads_manifest_from_external_write_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            external_write_dir = project_root / de.DEFAULT_EXTERNAL_WRITE_REL
            external_write_dir.mkdir(parents=True)
            de.save_manifest(external_write_dir, [
                de.DependencyEntry(import_name="googleapiclient",
                                   package_name="google-api-python-client",
                                   version="2.149.0", capability_id="acme_gcal_sync"),
            ])
            adapter_path = external_write_dir / "adapters_acme_gcal_sync.py"
            adapter_path.write_text(
                "import googleapiclient.discovery\nimport requests\n", encoding="utf-8")

            flagged = de.lint_adapter_file(adapter_path, external_write_dir)
            self.assertEqual(flagged, ["requests"])


class ManifestLoadFailIsolationTests(unittest.TestCase):
    """Missing manifest = clean empty list; corrupt manifest = warned, salvaged."""

    def test_missing_manifest_is_empty_no_warning_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(de.load_manifest(Path(tmp)), [])

    def test_corrupt_manifest_degrades_to_empty_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / de.MANIFEST_BASENAME
            manifest_path.write_text("{ not valid json", encoding="utf-8")
            entries = de.load_manifest(Path(tmp))
            self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
