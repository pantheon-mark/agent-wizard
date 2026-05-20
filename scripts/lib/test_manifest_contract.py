"""Tests for wizard-side manifest contract loader + bundle_hash refactor.

Covers:
    T-1  positive integration: load valid contract + hash synthetic bundle
    T-2  gate 2 negative:      missing contract_version field
    T-3  gate 2 negative:      wrong contract_version value
    T-4  gate 1 negative:      wrong contract_id value
    T-5  gate 5 negative:      enums.merge_strategy missing canonical `frozen`
    T-6  gate 6 negative:      default enum reference not in closed set
    T-7  gate 3 negative:      required_foundation_docs record missing a field
    T-8  gate 0 in-memory:     top-level JSON array (not object)
    T-9  gate 4 in-memory:     duplicate path
    T-10 gate 7 in-memory:     wrong manifest_file_fields shape
    T-11 boundary library:     hash_bundle raises BundleHashError on missing bundle
    T-12 boundary CLI:         CLI returns exit code 1 on missing bundle

Stdlib unittest (no pytest dep; keeps wizard distribution pip-install-free).

Run: python3 -m unittest discover -s wizard/scripts/lib -p "test_*.py"
"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_WIZARD_ROOT = _HERE.parent.parent
_REPO_ROOT = _WIZARD_ROOT.parent
_SCRIPTS_DIR = _HERE.parent

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.manifest_contract import (  # noqa: E402
    EXPECTED_CONTRACT_ID,
    EXPECTED_CONTRACT_VERSIONS,
    EXPECTED_ENUMS,
    EXPECTED_MANIFEST_FILE_FIELDS,
    ManifestContractError,
    default_contract_path,
    load_manifest_contract,
)
from bundle_hash import (  # noqa: E402
    BundleHashError,
    format_manifest_snippet,
    hash_bundle,
)


SYNTHETIC_BUNDLE = _WIZARD_ROOT / "test_fixtures" / "_synthetic_bundle"
NEG_FIXTURES = _WIZARD_ROOT / "test_fixtures" / "_negative" / "manifest_contract"

# Authoritative path ordering for the synthetic bundle test (matches live contract)
EXPECTED_PATH_ORDER = [
    "foundation/vision.md",
    "foundation/prd.md",
    "foundation/approach.md",
    "foundation/execution_plan.md",
    "foundation/technical_architecture.md",
    "foundation/test_cases.md",
    "foundation/audit_framework.md",
]


def _write_tmp_contract(contract_dict, tmpdir):
    """Helper: write contract dict to tmpfile + return path."""
    path = Path(tmpdir) / "tmp_contract.json"
    path.write_text(json.dumps(contract_dict), encoding="utf-8")
    return path


def _minimal_valid_contract():
    """Helper: returns a minimal-but-valid contract dict that passes all gates."""
    return {
        "contract_id": EXPECTED_CONTRACT_ID,
        "contract_version": "manifest-v1",
        "schema_authorities": ["foundation_manifest_hash_baseline.file_fields"],
        "description": "minimal contract for in-memory mutation tests",
        "required_foundation_docs": [
            {"path": "foundation/vision.md", "managed_by": "shared",
             "local_modifications": "expected", "merge_strategy": "three_way"},
        ],
        "enums": copy.deepcopy(EXPECTED_ENUMS),
        "manifest_file_fields": list(EXPECTED_MANIFEST_FILE_FIELDS),
    }


class T01_PositiveIntegration(unittest.TestCase):
    """T-1: valid contract + synthetic bundle → expected manifest snippet."""

    def test_load_default_contract(self):
        contract = load_manifest_contract(default_contract_path())
        self.assertEqual(contract["contract_id"], EXPECTED_CONTRACT_ID)
        self.assertIn(contract["contract_version"], EXPECTED_CONTRACT_VERSIONS)
        self.assertEqual(
            [r["path"] for r in contract["required_foundation_docs"]],
            EXPECTED_PATH_ORDER,
            "Contract required_foundation_docs ordering drifted from EXPECTED_PATH_ORDER",
        )
        self.assertEqual(contract["manifest_file_fields"], EXPECTED_MANIFEST_FILE_FIELDS)

    def test_hash_synthetic_bundle_produces_expected_snippet(self):
        contract = load_manifest_contract(default_contract_path())
        files = hash_bundle(SYNTHETIC_BUNDLE, contract=contract)
        # Full path sequence must match contract list order exactly (not alphabetical)
        self.assertEqual(
            [entry["path"] for entry in files],
            EXPECTED_PATH_ORDER,
            "hash_bundle output ordering drifted; deterministic order is part of the contract",
        )
        snippet = format_manifest_snippet(files)
        self.assertTrue(snippet.startswith("files:\n"))
        self.assertIn("base_hash: sha256:", snippet)
        self.assertIn("merge_strategy: three_way", snippet)
        self.assertIn("merge_strategy: warn_on_drift", snippet)


class T02_MissingVersion_Gate2(unittest.TestCase):
    def test_raises(self):
        with self.assertRaises(ManifestContractError) as ctx:
            load_manifest_contract(NEG_FIXTURES / "missing_version.json")
        self.assertIn("Gate 2", str(ctx.exception))


class T03_WrongVersion_Gate2(unittest.TestCase):
    def test_raises(self):
        with self.assertRaises(ManifestContractError) as ctx:
            load_manifest_contract(NEG_FIXTURES / "wrong_version.json")
        self.assertIn("Gate 2", str(ctx.exception))
        self.assertIn("manifest-v99", str(ctx.exception))


class T04_WrongId_Gate1(unittest.TestCase):
    def test_raises(self):
        with self.assertRaises(ManifestContractError) as ctx:
            load_manifest_contract(NEG_FIXTURES / "wrong_id.json")
        self.assertIn("Gate 1", str(ctx.exception))
        self.assertIn("some-other-contract", str(ctx.exception))


class T05_EnumMissingFrozen_Gate5(unittest.TestCase):
    def test_raises(self):
        with self.assertRaises(ManifestContractError) as ctx:
            load_manifest_contract(NEG_FIXTURES / "enum_missing_frozen.json")
        self.assertIn("Gate 5", str(ctx.exception))
        self.assertIn("merge_strategy", str(ctx.exception))


class T06_DefaultUnknownEnum_Gate6(unittest.TestCase):
    def test_raises(self):
        with self.assertRaises(ManifestContractError) as ctx:
            load_manifest_contract(NEG_FIXTURES / "default_unknown_enum.json")
        self.assertIn("Gate 6", str(ctx.exception))
        self.assertIn("unknown_strategy", str(ctx.exception))


class T07_MissingRecordField_Gate3(unittest.TestCase):
    """T-7: required_foundation_docs record missing required field → gate 3 FAIL."""

    def test_raises(self):
        with self.assertRaises(ManifestContractError) as ctx:
            load_manifest_contract(NEG_FIXTURES / "missing_record_field.json")
        self.assertIn("Gate 3", str(ctx.exception))
        self.assertIn("merge_strategy", str(ctx.exception))


class T08_TopLevelArray_Gate0(unittest.TestCase):
    """T-8 in-memory: top-level JSON array (not object) → gate 0 FAIL.

    Exercised in-memory because a top-level array isn't a useful on-disk fixture.
    """

    def test_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tmp.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(ManifestContractError) as ctx:
                load_manifest_contract(path)
            self.assertIn("Gate 0", str(ctx.exception))


class T09_DuplicatePath_Gate4(unittest.TestCase):
    """T-9 in-memory: duplicate path in required_foundation_docs → gate 4 FAIL."""

    def test_raises(self):
        contract = _minimal_valid_contract()
        contract["required_foundation_docs"].append(dict(contract["required_foundation_docs"][0]))
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_tmp_contract(contract, tmp)
            with self.assertRaises(ManifestContractError) as ctx:
                load_manifest_contract(path)
            self.assertIn("Gate 4", str(ctx.exception))


class T10_ManifestFileFields_Gate7(unittest.TestCase):
    """T-10 in-memory: manifest_file_fields drift → gate 7 FAIL."""

    def test_raises_on_missing_field(self):
        contract = _minimal_valid_contract()
        contract["manifest_file_fields"] = ["managed", "base_hash"]  # missing fields
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_tmp_contract(contract, tmp)
            with self.assertRaises(ManifestContractError) as ctx:
                load_manifest_contract(path)
            self.assertIn("Gate 7", str(ctx.exception))

    def test_raises_on_extra_field(self):
        contract = _minimal_valid_contract()
        contract["manifest_file_fields"] = EXPECTED_MANIFEST_FILE_FIELDS + ["bonus_field"]
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_tmp_contract(contract, tmp)
            with self.assertRaises(ManifestContractError) as ctx:
                load_manifest_contract(path)
            self.assertIn("Gate 7", str(ctx.exception))


class T10b_EnumExtraValue_Gate5(unittest.TestCase):
    """Gate 5 must reject EXTRA values, not just missing — confirms exact-match semantics."""

    def test_raises_on_extra_enum_value(self):
        contract = _minimal_valid_contract()
        contract["enums"]["merge_strategy"] = (
            list(EXPECTED_ENUMS["merge_strategy"]) + ["nonsense_value"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_tmp_contract(contract, tmp)
            with self.assertRaises(ManifestContractError) as ctx:
                load_manifest_contract(path)
            self.assertIn("Gate 5", str(ctx.exception))


class T11_HashBundleLibraryRaise(unittest.TestCase):
    """T-11: hash_bundle on missing bundle raises BundleHashError, NOT SystemExit."""

    def test_raises_typed_exception(self):
        contract = load_manifest_contract(default_contract_path())
        with tempfile.TemporaryDirectory() as tmp:
            empty_bundle = Path(tmp)  # no foundation/ subdir → all required files missing
            with self.assertRaises(BundleHashError) as ctx:
                hash_bundle(empty_bundle, contract=contract)
            self.assertIn("foundation/vision.md", str(ctx.exception))

    def test_does_not_call_sys_exit(self):
        contract = load_manifest_contract(default_contract_path())
        with tempfile.TemporaryDirectory() as tmp:
            empty_bundle = Path(tmp)
            try:
                hash_bundle(empty_bundle, contract=contract)
            except BundleHashError:
                pass  # expected
            except SystemExit:  # pragma: no cover
                self.fail("hash_bundle called sys.exit; library anti-pattern not removed")

    def test_directory_in_place_of_required_file(self):
        """If a foundation-doc path is a directory, raise BundleHashError not raw IsADirectoryError."""
        contract = load_manifest_contract(default_contract_path())
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            (bundle / "foundation").mkdir()
            # Replace foundation/vision.md with a directory (not a regular file)
            (bundle / "foundation" / "vision.md").mkdir()
            # Other required files still missing → expect missing-list, not crash
            with self.assertRaises(BundleHashError) as ctx:
                hash_bundle(bundle, contract=contract)
            msg = str(ctx.exception)
            # Either reported as missing (regular file absent) or invalid (dir in place of file);
            # both surface via BundleHashError, not raw IsADirectoryError.
            self.assertTrue(
                "vision.md" in msg
                or "not regular files" in msg
                or "not a regular file" in msg,
                f"Expected vision.md to surface in error; got: {msg}",
            )


class T12_CliExitCode(unittest.TestCase):
    """T-12: CLI invoked on missing bundle → exit code 1 (NOT crash, NOT 0)."""

    def test_missing_bundle_returns_exit_1(self):
        bundle_hash_script = _SCRIPTS_DIR / "bundle_hash.py"
        with tempfile.TemporaryDirectory() as tmp:
            empty_bundle = Path(tmp)
            result = subprocess.run(
                [sys.executable, str(bundle_hash_script), str(empty_bundle)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                1,
                msg=f"Expected exit code 1; got {result.returncode}. "
                    f"stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            self.assertIn("missing", result.stderr.lower())

    def test_nonexistent_bundle_path_returns_exit_2(self):
        bundle_hash_script = _SCRIPTS_DIR / "bundle_hash.py"
        result = subprocess.run(
            [sys.executable, str(bundle_hash_script), "/nonexistent/path/that/will/never/exist"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
