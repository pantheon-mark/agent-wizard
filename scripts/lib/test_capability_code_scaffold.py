"""Golden-emit tests for capability_code_scaffold.py (Task 10 —
external-write-gate-generalization slice): add-capability's build cascade
must emit a writes-back capability's code GATE-WIRED BY CONSTRUCTION, with
zero manual wiring by the (non-technical) operator.

Groups:
  1. TestSpecValidation       -- CapabilityCodeSpec is fail-closed on a
     malformed spec (never renders/emits something structurally unsound).
  2. TestGoldenEmitZoneClean  -- the ACCEPTANCE criterion: emit a sample
     writes-back capability and assert the emitted files PASS
     external_write.scan.scan_paths (zone-clean) by construction; the
     adapter module is registered in the (effective) ADAPTER_PROFILE set;
     the capability module has no vendor import / no write-credential
     reference (belt-and-suspenders direct AST assertion, on top of the
     scan itself being clean).
  3. TestRuntimeRegistration  -- executing the emitted adapter module for
     real lands a contract with the declared op_kind/read_only_scope/
     blast_radius_cap, registers a real adapter, and produces a VALID
     effects manifest (effects_manifest.build_manifest succeeds and its
     dependency_files cover the adapter's own module — the F-34 property).
  4. TestRegistryIdempotency  -- re-emitting the same capability does not
     duplicate its entry in adapter_profile_registry.json.
"""

import ast
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_write import zones, scan  # noqa: E402
from external_write.contracts import OPERATION_CONTRACTS  # noqa: E402
from external_write.adapter_registry import unregister_adapter  # noqa: E402

import capability_code_scaffold as ccs  # noqa: E402
from capability_code_scaffold import (  # noqa: E402
    CapabilityCodeSpec,
    CapabilityCodeScaffoldError,
    render_adapter_module,
    render_capability_module,
    emit_capability_code_scaffold,
)


def _sample_spec(**overrides) -> CapabilityCodeSpec:
    kwargs = dict(
        capability_id="acme_crm_sync",
        display_name="Acme CRM record sync",
        op_kind="acme_crm.record.archive",
        surface="acme_crm",
        read_only_scope="acme_crm.readonly",
        blast_radius_cap=10,
        read_methods=("list_records", "get_record"),
    )
    kwargs.update(overrides)
    return CapabilityCodeSpec(**kwargs)


class TestSpecValidation(unittest.TestCase):
    def test_bad_capability_id_refused(self):
        with self.assertRaises(CapabilityCodeScaffoldError):
            _sample_spec(capability_id="Not-Valid!")

    def test_empty_read_only_scope_refused(self):
        with self.assertRaises(CapabilityCodeScaffoldError):
            _sample_spec(read_only_scope="")

    def test_zero_blast_radius_cap_refused(self):
        with self.assertRaises(CapabilityCodeScaffoldError):
            _sample_spec(blast_radius_cap=0)

    def test_negative_blast_radius_cap_refused(self):
        with self.assertRaises(CapabilityCodeScaffoldError):
            _sample_spec(blast_radius_cap=-1)

    def test_bool_blast_radius_cap_refused(self):
        with self.assertRaises(CapabilityCodeScaffoldError):
            _sample_spec(blast_radius_cap=True)

    def test_no_read_methods_refused(self):
        with self.assertRaises(CapabilityCodeScaffoldError):
            _sample_spec(read_methods=())

    def test_class_prefix_is_pascal_case(self):
        self.assertEqual(_sample_spec().class_prefix, "AcmeCrmSync")


class TestGoldenEmitZoneClean(unittest.TestCase):
    """The literal acceptance criterion: golden-emit a sample writes-back
    capability and prove the emitted pair passes the T5 scanner by
    construction."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.project_root = Path(self._td.name)
        self.spec = _sample_spec()
        self.written = emit_capability_code_scaffold(self.spec, self.project_root)
        self.adapter_path, self.capability_path, self.registry_path = self.written
        self.lib_dir = self.project_root / "agents" / "lib" / "external_write"
        self.cap_dir = self.project_root / "agents" / "capabilities"

    def tearDown(self):
        self._td.cleanup()

    def test_both_files_written_and_parse_as_valid_python(self):
        self.assertTrue(self.adapter_path.is_file())
        self.assertTrue(self.capability_path.is_file())
        ast.parse(self.adapter_path.read_text(encoding="utf-8"))
        ast.parse(self.capability_path.read_text(encoding="utf-8"))

    def test_adapter_registered_in_effective_adapter_profile_paths(self):
        effective = zones.effective_adapter_profile_paths(self.lib_dir)
        self.assertIn(f"{self.spec.adapter_module_stem}.py", effective)

    def test_registry_file_content(self):
        entries = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(entries, [f"{self.spec.adapter_module_stem}.py"])

    def test_scan_paths_reports_zero_violations(self):
        effective = zones.effective_adapter_profile_paths(self.lib_dir)
        violations = scan.scan_paths(
            [self.lib_dir, self.cap_dir],
            allowed_root=self.lib_dir,
            adapter_profile_paths=effective,
        )
        self.assertEqual(violations, [], f"expected zone-clean emit, got: {violations}")

    def test_capability_module_scans_clean_even_WITHOUT_the_adapter_profile_exemption(self):
        # Stronger check than the union scan above: the capability module alone, scanned
        # against an EMPTY adapter-profile allowlist (so nothing is exempt), must still be
        # clean on its own merits -- proving its safety does not depend on being inside the
        # ADAPTER_PROFILE zone at all (it lives in agents/capabilities/, a different
        # directory, and is CAPABILITY zone regardless).
        violations = scan.scan_paths(
            [self.capability_path],
            allowed_root=self.lib_dir,
            adapter_profile_paths=frozenset(),
            sealed_kernel_paths=frozenset(),
        )
        self.assertEqual(violations, [])

    def test_capability_module_has_no_vendor_sdk_import(self):
        # Direct AST assertion (belt-and-suspenders on top of the scan being clean):
        # every import in the capability module resolves to either stdlib `typing` or
        # the internal `external_write.*` package -- never a third-party vendor root.
        tree = ast.parse(self.capability_path.read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        self.assertEqual(roots, {"typing", "external_write"})

    def test_capability_module_never_calls_write_credential_provider(self):
        # It may hold a REFERENCE to write_credential_provider (imported, passed through
        # to run_operation) but must never CALL it directly.
        tree = ast.parse(self.capability_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotEqual(node.func.id, "write_credential_provider",
                                   "capability module must never CALL the write "
                                   "credential provider directly")

    def test_capability_module_has_no_credential_factory_reference(self):
        tree = ast.parse(self.capability_path.read_text(encoding="utf-8"))
        forbidden = {"from_service_account_file", "from_service_account_info",
                    "from_authorized_user_file", "from_authorized_user_info",
                    "with_subject", "Credentials", "ServiceAccountCredentials"}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                found.add(node.attr)
            if isinstance(node, ast.Name) and node.id in forbidden:
                found.add(node.id)
        self.assertEqual(found, set())

    def test_adapter_module_zone_classifies_adapter_profile(self):
        # classify_zone's callers (scan.py) always pass a RESOLVED anchor (symlinks
        # followed) — mirror that here, since a macOS temp dir is itself a symlink
        # (/var -> /private/var) and an unresolved anchor would spuriously mismatch.
        effective = zones.effective_adapter_profile_paths(self.lib_dir)
        zone = zones.classify_zone(
            self.adapter_path, self.lib_dir.resolve(),
            adapter_profile_paths=effective,
        )
        self.assertEqual(zone, zones.Zone.ADAPTER_PROFILE)


class TestRuntimeRegistration(unittest.TestCase):
    """Executing the emitted adapter module for real must land a working
    contract + adapter registration and a VALID effects manifest."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.project_root = Path(self._td.name)
        self.spec = _sample_spec(
            capability_id="acme_crm_sync_rt",
            op_kind="acme_crm_rt.record.archive",
        )
        written = emit_capability_code_scaffold(self.spec, self.project_root)
        self.adapter_path = written[0]

        modname = "t10_golden_adapter_runtime_test_mod"
        spec_obj = importlib.util.spec_from_file_location(modname, self.adapter_path)
        module = importlib.util.module_from_spec(spec_obj)
        sys.modules[modname] = module
        spec_obj.loader.exec_module(module)
        self.module = module

    def tearDown(self):
        self._td.cleanup()
        unregister_adapter(self.spec.op_kind)
        OPERATION_CONTRACTS.pop(self.spec.op_kind, None)
        sys.modules.pop("t10_golden_adapter_runtime_test_mod", None)

    def test_contract_declares_op_kind_read_only_scope_and_cap(self):
        from external_write.contracts import get_contract
        c = get_contract(self.spec.op_kind)
        self.assertIsNotNone(c)
        self.assertEqual(c.op_kind, self.spec.op_kind)
        self.assertEqual(c.read_only_scope, self.spec.read_only_scope)
        self.assertEqual(c.blast_radius_cap, self.spec.blast_radius_cap)
        self.assertEqual(c.risk_class, self.spec.risk_class)

    def test_adapter_is_registered(self):
        from external_write.adapter_registry import get_adapter
        adapter = get_adapter(self.spec.op_kind)
        self.assertIsNotNone(adapter)

    def test_effects_manifest_is_valid_and_covers_the_adapter_module(self):
        from external_write.effects_manifest import build_manifest
        manifest = build_manifest(self.spec.op_kind)
        self.assertEqual(manifest.cap_default, self.spec.blast_radius_cap)
        self.assertEqual(manifest.allowed_mutations, tuple(self.spec.writes))
        self.assertTrue(len(manifest.implementation_hash) == 64)
        # F-34 property: the adapter's OWN module file is covered by the hash.
        # (dependency_files carries the RESOLVED path — see effects_manifest.
        # _adapter_module_file — so compare against the resolved form too.)
        self.assertTrue(
            any(str(self.adapter_path.resolve()) == f for f in manifest.dependency_files),
            manifest.dependency_files,
        )

    def test_read_facade_declares_only_the_spec_read_methods(self):
        facade_cls = getattr(self.module, f"{self.spec.class_prefix}ReadFacade")
        self.assertEqual(set(facade_cls.read_methods), set(self.spec.read_methods))


class TestRegistryIdempotency(unittest.TestCase):
    def test_reemit_does_not_duplicate_registry_entry(self):
        with TemporaryDirectory() as td:
            project_root = Path(td)
            spec = _sample_spec(capability_id="idem_test_cap")
            emit_capability_code_scaffold(spec, project_root)
            _, _, registry_path = emit_capability_code_scaffold(spec, project_root)
            entries = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(entries, ["adapters_idem_test_cap.py"])

    def test_reemit_preserves_other_capabilities_already_registered(self):
        with TemporaryDirectory() as td:
            project_root = Path(td)
            first = _sample_spec(capability_id="first_cap")
            second = _sample_spec(capability_id="second_cap",
                                  op_kind="second_cap.record.archive")
            emit_capability_code_scaffold(first, project_root)
            _, _, registry_path = emit_capability_code_scaffold(second, project_root)
            entries = set(json.loads(registry_path.read_text(encoding="utf-8")))
            self.assertEqual(entries, {"adapters_first_cap.py", "adapters_second_cap.py"})


if __name__ == "__main__":
    unittest.main()
