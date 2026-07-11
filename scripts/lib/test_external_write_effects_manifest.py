"""Tests for the per-op_kind effects manifest (Task 3 —
external-write-gate-generalization slice).

Closes dogfood finding F-34: `implementation_hash` used to hash a FIXED module
tuple (`contracts._WRITE_AFFECTING_MODULES`) that structurally excluded any
op_kind's own registered adapter module. These tests prove the fix generically,
using a throwaway fixture adapter (`wizard/test_fixtures/effects_manifest/
fixture_adapter.py`) — the real Gmail verb adapter is Task 7 and does not exist
yet; nothing here hard-codes Gmail specifics.
"""

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

_LIB_DIR = _AGENTS_LIB / "external_write"
_FIXTURE_SRC = (
    Path(__file__).resolve().parents[2] / "test_fixtures" / "effects_manifest" / "fixture_adapter.py"
)

from external_write.contracts import OperationContract  # noqa: E402
import external_write.contracts as _contracts  # noqa: E402
from external_write.adapter_registry import register_adapter, unregister_adapter  # noqa: E402
from external_write.proof_hash import compute_implementation_hash, SHA256_HEX_LEN  # noqa: E402
from external_write.effects_manifest import (  # noqa: E402
    EffectsManifest,
    ManifestBuildError,
    build_manifest,
    resolve_dependency_files,
    validate_manifest,
)

_FIXTURE_OP_KIND = "_effects_manifest_fixture_op"
_FIXTURE_MODULE_NAME = "_effects_manifest_fixture_adapter_module"


def _load_adapter_module(path: Path, module_name: str):
    """Load `path` as a fresh module named `module_name`, registering it in
    sys.modules so `type(instance).__module__` resolves back to this exact
    file (mirroring how a real adapter module registers itself at import
    time)."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _FixtureContractMixin:
    """Registers a throwaway op_kind + contract with an EMPTY dependency_set,
    so the only way a write-affecting file can enter its dependency_files is
    via a registered adapter — isolates the F-34 mechanism from the
    pre-existing static dependency_set path."""

    def setUp(self):
        super().setUp()
        self._prior_contract = _contracts.OPERATION_CONTRACTS.get(_FIXTURE_OP_KIND)
        _contracts.OPERATION_CONTRACTS[_FIXTURE_OP_KIND] = OperationContract(
            op_kind=_FIXTURE_OP_KIND,
            writes=("__fixture__",),
            produces=(),
            dependency_set=(),  # deliberately empty — see class docstring
            verifier_set=("operator_attested_v1",),
            introduces_persistent_binding=False,
            requires_accepted_phase=True,  # "gated op_kind" per the brief's acceptance wording
        )

    def tearDown(self):
        unregister_adapter(_FIXTURE_OP_KIND)
        if self._prior_contract is None:
            _contracts.OPERATION_CONTRACTS.pop(_FIXTURE_OP_KIND, None)
        else:
            _contracts.OPERATION_CONTRACTS[_FIXTURE_OP_KIND] = self._prior_contract
        sys.modules.pop(_FIXTURE_MODULE_NAME, None)
        super().tearDown()


class TestResolveDependencyFilesIncludesAdapter(_FixtureContractMixin, unittest.TestCase):
    def test_unregistered_op_kind_uses_only_the_declared_dependency_set(self):
        # No adapter registered for set_status (Task 2 scope note: the six seeded
        # field op_kinds are not migrated onto the registry until Task 8).
        self.assertEqual(
            resolve_dependency_files("set_status"),
            tuple(sorted(_contracts.get_contract("set_status").dependency_set)),
        )

    def test_unknown_op_kind_fails_closed(self):
        with self.assertRaises(ManifestBuildError):
            resolve_dependency_files("_no_such_op_kind_at_all")

    def test_dependency_files_includes_registered_adapter_module_for_gated_op_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter_path = Path(tmp) / "fixture_adapter.py"
            shutil.copy2(_FIXTURE_SRC, adapter_path)
            module = _load_adapter_module(adapter_path, _FIXTURE_MODULE_NAME)
            register_adapter(_FIXTURE_OP_KIND, module.FixtureAdapter())

            dep_files = resolve_dependency_files(_FIXTURE_OP_KIND)

            self.assertIn(str(adapter_path.resolve()), dep_files)


class TestImplementationHashBindsTheRealAdapter(_FixtureContractMixin, unittest.TestCase):
    """The F-34 acceptance test: mutating the registered adapter's bytes must
    change the op_kind's implementation_hash."""

    def test_changing_a_byte_in_the_adapter_module_changes_implementation_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter_path = Path(tmp) / "fixture_adapter.py"
            shutil.copy2(_FIXTURE_SRC, adapter_path)
            module = _load_adapter_module(adapter_path, _FIXTURE_MODULE_NAME)
            register_adapter(_FIXTURE_OP_KIND, module.FixtureAdapter())

            h_before = compute_implementation_hash(_FIXTURE_OP_KIND, lib_dir=_LIB_DIR)

            with adapter_path.open("ab") as f:
                f.write(b"\n# mutation-sentinel\n")

            h_after = compute_implementation_hash(_FIXTURE_OP_KIND, lib_dir=_LIB_DIR)

            self.assertNotEqual(
                h_before, h_after,
                "implementation_hash must change when the registered adapter "
                "module's bytes change (F-34)",
            )

    def test_no_registered_adapter_means_hash_is_unaffected_by_an_unrelated_file(self):
        """Control: with NO adapter registered and an empty dependency_set, the
        fixture op_kind's hash must be stable across calls (nothing to bind to)."""
        h1 = compute_implementation_hash(_FIXTURE_OP_KIND, lib_dir=_LIB_DIR)
        h2 = compute_implementation_hash(_FIXTURE_OP_KIND, lib_dir=_LIB_DIR)
        self.assertEqual(h1, h2)


class TestBuildManifest(_FixtureContractMixin, unittest.TestCase):
    def test_build_manifest_for_existing_op_kind_matches_contract_fields(self):
        m = build_manifest("set_status", lib_dir=_LIB_DIR)
        c = _contracts.get_contract("set_status")
        self.assertIsInstance(m, EffectsManifest)
        self.assertEqual(m.op_kind, "set_status")
        self.assertEqual(m.allowed_mutations, tuple(c.writes))
        self.assertEqual(m.cap_default, c.blast_radius_cap)
        self.assertEqual(m.verifiers, tuple(c.verifier_set))
        self.assertEqual(m.dependency_files, resolve_dependency_files("set_status"))
        self.assertEqual(len(m.implementation_hash), SHA256_HEX_LEN)

    def test_build_manifest_implementation_hash_equals_compute_implementation_hash(self):
        """DRY / equivalence: the manifest must not reinvent hashing — its
        implementation_hash is exactly what compute_implementation_hash(op_kind)
        produces for the same lib_dir/runtime_params."""
        m = build_manifest("delete_record", lib_dir=_LIB_DIR)
        direct = compute_implementation_hash("delete_record", lib_dir=_LIB_DIR)
        self.assertEqual(m.implementation_hash, direct)

    def test_build_manifest_unknown_op_kind_fails_closed(self):
        with self.assertRaises(ManifestBuildError):
            build_manifest("_no_such_op_kind_at_all", lib_dir=_LIB_DIR)

    def test_build_manifest_for_gated_op_kind_includes_its_adapter_in_dependency_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter_path = Path(tmp) / "fixture_adapter.py"
            shutil.copy2(_FIXTURE_SRC, adapter_path)
            module = _load_adapter_module(adapter_path, _FIXTURE_MODULE_NAME)
            register_adapter(_FIXTURE_OP_KIND, module.FixtureAdapter())

            m = build_manifest(_FIXTURE_OP_KIND, lib_dir=_LIB_DIR)

            self.assertIn(str(adapter_path.resolve()), m.dependency_files)
            self.assertTrue(m.effect_unit_path)
            self.assertIn("FixtureAdapter", m.effect_unit_path)


class TestValidateManifest(_FixtureContractMixin, unittest.TestCase):
    def test_valid_manifest_passes(self):
        m = build_manifest("set_status", lib_dir=_LIB_DIR)
        validate_manifest(m)  # must not raise

    def test_manifest_with_no_dependency_files_fails_closed(self):
        m = EffectsManifest(
            op_kind="set_status",
            params_schema=None,
            effect_unit_path=None,
            cap_default=None,
            allowed_mutations=("Status",),
            undo=None,
            verifiers=("prestate_snapshot_diff_v1",),
            dependency_files=(),  # coverage-incomplete — must fail closed
            implementation_hash="a" * SHA256_HEX_LEN,
        )
        with self.assertRaises(ManifestBuildError):
            validate_manifest(m)

    def test_manifest_referencing_unregistered_verifier_fails_closed(self):
        m = EffectsManifest(
            op_kind="set_status",
            params_schema=None,
            effect_unit_path=None,
            cap_default=None,
            allowed_mutations=("Status",),
            undo=None,
            verifiers=("not_a_real_verifier",),
            dependency_files=("adapters.py",),
            implementation_hash="a" * SHA256_HEX_LEN,
        )
        with self.assertRaises(ManifestBuildError):
            validate_manifest(m)

    def test_manifest_with_malformed_implementation_hash_fails_closed(self):
        m = EffectsManifest(
            op_kind="set_status",
            params_schema=None,
            effect_unit_path=None,
            cap_default=None,
            allowed_mutations=("Status",),
            undo=None,
            verifiers=("prestate_snapshot_diff_v1",),
            dependency_files=("adapters.py",),
            implementation_hash="not-hex",
        )
        with self.assertRaises(ManifestBuildError):
            validate_manifest(m)


if __name__ == "__main__":
    unittest.main()
