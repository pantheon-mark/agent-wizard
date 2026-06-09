"""Unit tests for wizard.scripts.lib.manifest_validator (F-9 strict-subset
validator).

Exercises the wizard-side strict-subset validator against the shared fixture
corpus at tools/fixtures/foundation_bundle_manifest/. Per the documented
strict-subset asymmetry contract (per (M-2) drift mitigation), some fixtures
that FAIL build-side intentionally PASS wizard-side because wizard-side does
not enforce cross-field invariants (PyYAML-territory rules). The test
asserts that wizard-side outcomes match documented expectations.

Stdlib-only test (unittest + pathlib). Fixtures loaded from disk; no
PyYAML required (the validator is stdlib-only by design).
"""

import os
import sys
import unittest
from pathlib import Path

# Self-contained import (matches the other lib test modules): put this file's dir on
# sys.path so the bare module import resolves under `python3 -m unittest discover -s lib`
# (there is no importable `wizard` namespace package on the path in that mode). This still
# works under the repo-root `python3 -m unittest wizard.scripts.lib.test_manifest_validator`
# invocation. The module under test is stdlib-only, so it has no `wizard.scripts` dependency
# that would require the absolute-root import.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from manifest_validator import (
    ManifestValidatorError,
    validate_manifest,
)


# Compute fixtures dir relative to this file.
#   __file__: agent-wizard-build/wizard/scripts/lib/test_manifest_validator.py
#   parent x4 = agent-wizard-build/
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parent.parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tools" / "fixtures" / "foundation_bundle_manifest"


class TestManifestValidatorAgainstFixtureCorpus(unittest.TestCase):
    """Test wizard-side validator against the shared fixture corpus.

    Expected outcomes per fixture (wizard-side column only; build-side
    expectations are exercised in tools/test_validator_parity.py):

        F1 positive v1.0.0 package → PASS
        F2 negative v1.0.0 package missing → PASS (subset asymmetry; wizard
            does NOT enforce cross-field "required at v1.0.0+" invariant)
        F3 positive operator manifest → PASS
        F4 negative operator missing → FAIL (operator-context unconditional rule)
        F6 positive prerelease carve-out → PASS (trivially; no wizard-side rule
            fires; build-side does the carve-out verification)
        F7a malformed empty value → FAIL
        F7b malformed short value → FAIL
        F7c malformed non-hex value → FAIL
    """

    def _validate_fixture(self, fixture_name: str):
        path = FIXTURES_DIR / fixture_name
        self.assertTrue(path.exists(), f"fixture not found: {path}")
        return validate_manifest(path)

    def test_F1_positive_v1_0_0_package_passes(self):
        result = self._validate_fixture("F1_positive_v1_0_0_package.yaml")
        self.assertTrue(
            result.passed,
            f"expected wizard-side PASS on F1; got failures: {result.failures}",
        )
        self.assertEqual(result.context, "package")

    def test_F2_negative_v1_0_0_package_missing_passes_wizard_subset_asymmetry(self):
        """F2 is the canonical strict-subset asymmetry case: build-side FAILs
        (enforces cross-field "required at v1.0.0+" invariant) but wizard-side
        PASSes (does not enforce that cross-field invariant — strict-subset
        boundary). Per (M-2) drift mitigation, this divergence is documented
        and expected."""
        result = self._validate_fixture(
            "F2_negative_v1_0_0_package_missing.yaml"
        )
        self.assertTrue(
            result.passed,
            "expected wizard-side PASS on F2 per documented strict-subset "
            "asymmetry (cross-field 'required at v1.0.0+' invariant is "
            f"build-side-only); got failures: {result.failures}",
        )
        self.assertEqual(result.context, "package")

    def test_F3_positive_operator_manifest_passes(self):
        result = self._validate_fixture("F3_positive_operator_manifest.yaml")
        self.assertTrue(
            result.passed,
            f"expected wizard-side PASS on F3; got failures: {result.failures}",
        )
        self.assertEqual(result.context, "operator")

    def test_F4_negative_operator_missing_fails(self):
        """Wizard-side CAN enforce the operator-context rule because it's
        unconditional ('REQUIRED unconditionally' per F-9 contract scope).
        Both validators fail in lockstep on F4."""
        result = self._validate_fixture(
            "F4_negative_operator_manifest_missing.yaml"
        )
        self.assertFalse(
            result.passed,
            "expected wizard-side FAIL on F4 (operator-context unconditional rule)",
        )
        self.assertEqual(result.context, "operator")
        # Confirm the failure mentions generator_version + operator semantics.
        joined = " ".join(result.failures).lower()
        self.assertIn("generator_version", joined)

    def test_F6_positive_prerelease_carve_out_passes(self):
        """F6 passes wizard-side trivially (no wizard-side rule fires on
        package-context missing field; that's build-side territory). Build-side
        verifies the 3 carve-out conditions; same final outcome, different
        rationale per documented asymmetry."""
        result = self._validate_fixture(
            "F6_positive_prerelease_carve_out.yaml"
        )
        self.assertTrue(
            result.passed,
            f"expected wizard-side PASS on F6 (prerelease carve-out trivially "
            f"passes wizard-side subset); got failures: {result.failures}",
        )
        self.assertEqual(result.context, "package")

    def test_F7a_empty_value_fails(self):
        result = self._validate_fixture(
            "F7a_negative_generator_version_empty.yaml"
        )
        self.assertFalse(
            result.passed,
            "expected wizard-side FAIL on F7a (empty generator_version value)",
        )

    def test_F7b_short_value_fails(self):
        result = self._validate_fixture(
            "F7b_negative_generator_version_short.yaml"
        )
        self.assertFalse(
            result.passed,
            "expected wizard-side FAIL on F7b (short generator_version value)",
        )

    def test_F7c_non_hex_value_fails(self):
        result = self._validate_fixture(
            "F7c_negative_generator_version_non_hex.yaml"
        )
        self.assertFalse(
            result.passed,
            "expected wizard-side FAIL on F7c (non-hex generator_version value)",
        )


class TestManifestValidatorEdgeCases(unittest.TestCase):
    """Edge cases independent of fixture corpus."""

    def test_nonexistent_file_raises_io_error(self):
        with self.assertRaises(ManifestValidatorError):
            validate_manifest(FIXTURES_DIR / "DOES_NOT_EXIST.yaml")

    def test_duplicate_top_level_key_fails(self):
        # Write a tiny manifest with a duplicate top-level key.
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                "foundation_bundle_version: v1.0.0\n"
                "generator_version: a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4\n"
                "generator_version: b1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4\n"
                "included_templates:\n"
                "  foundation_docs: []\n"
            )
            tmp_path = Path(f.name)
        try:
            result = validate_manifest(tmp_path)
            self.assertFalse(result.passed, "expected FAIL on duplicate top-level key")
            self.assertTrue(any("duplicate" in f.lower() for f in result.failures))
        finally:
            tmp_path.unlink()

    def test_nested_generator_version_fails(self):
        """Nested `generator_version:` (not at top level) flagged as misplacement."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(
                "foundation_bundle_version: v1.0.0\n"
                "managed_files:\n"
                "  foundation/vision.md:\n"
                "    generator_version: a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4\n"
                "included_templates:\n"
                "  foundation_docs: []\n"
            )
            tmp_path = Path(f.name)
        try:
            result = validate_manifest(tmp_path)
            self.assertFalse(result.passed, "expected FAIL on nested generator_version")
            self.assertTrue(any("nested" in f.lower() for f in result.failures))
        finally:
            tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()
