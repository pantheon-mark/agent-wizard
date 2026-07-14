"""Golden-emit tests for capability_code_scaffold.py (Task 10, extended by
Task R7-T3 — external-write-gate-generalization slice): add-capability's
build cascade must emit a writes-back capability's code GATE-WIRED BY
CONSTRUCTION, with zero manual wiring by the (non-technical) operator.

Task R7-T3 rewires the emitter to emit THREE modules, not two, mirroring the
Task R7-T1 split proven by read_facades_gmail.py: the capability module must
never import a facade class from the SAME module that defines
`build_write_client` (the adapter module). The `<Prefix>ReadFacade` subclass
now lives in its own `read_facades_<cap>.py` module (SCANNED, not
ADAPTER_PROFILE), registered against the kernel via `register_read_facade`;
the capability module resolves it via `capability_api.build_read_facade`
(two-arg, registry-resolved form) and imports ONLY the curated kernel
surface (`capability_api` + `operations`).

Groups:
  1. TestSpecValidation       -- CapabilityCodeSpec is fail-closed on a
     malformed spec (never renders/emits something structurally unsound).
  2. TestGoldenEmitZoneClean  -- the ACCEPTANCE criterion: emit a sample
     writes-back capability and assert the emitted TRIO passes
     external_write.scan.scan_paths (zone-clean) by construction; the
     adapter module (and ONLY the adapter module) is registered in the
     (effective) ADAPTER_PROFILE set; the capability module has no vendor
     import / no write-credential reference / no adapter-module or
     concrete-facade import (belt-and-suspenders direct AST assertion, on
     top of the scan itself being clean).
  3. TestRuntimeRegistration  -- executing the emitted adapter + read-facade
     modules for real lands a contract with the declared op_kind/
     read_only_scope/blast_radius_cap, registers a real adapter AND a real
     read facade (via the kernel registry), and produces a VALID effects
     manifest (effects_manifest.build_manifest succeeds and its dependency
     set covers the ADAPTER module -- the F-34 property -- but never needs
     the read-facade module to do so).
  4. TestReadFacadeSplitRegistryResolution -- the R7-T3 core property:
     `build_read_facade(op_kind, client)` (two-arg, capability-facing form)
     resolves the EMITTED `<Prefix>ReadFacade` from the kernel registry once
     `read_facades_<cap>.py` has been imported (registration fires at import
     time); it is NOT resolved from -- and the resolved instance's
     `__class__.__module__` is NEVER -- the adapter module. Fail-closed if
     the read-facade module was never imported (nothing registered).
  5. TestRegistryIdempotency  -- re-emitting the same capability does not
     duplicate its entry in adapter_profile_registry.json (and never adds
     the read-facade module to it at all).
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
from external_write.read_facade import (  # noqa: E402
    build_read_facade, unregister_read_facade, ReadFacadeEligibilityError,
)

import capability_code_scaffold as ccs  # noqa: E402
from capability_code_scaffold import (  # noqa: E402
    CapabilityCodeSpec,
    CapabilityCodeScaffoldError,
    render_adapter_module,
    render_read_facade_module,
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

    def test_read_facade_module_stem(self):
        self.assertEqual(_sample_spec().read_facade_module_stem, "read_facades_acme_crm_sync")


class TestGoldenEmitZoneClean(unittest.TestCase):
    """The literal acceptance criterion: golden-emit a sample writes-back
    capability and prove the emitted TRIO passes the T5 scanner by
    construction, and that the capability module's import list is EXACTLY
    the curated kernel surface -- no adapter module, no registry, no
    concrete facade class."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.project_root = Path(self._td.name)
        self.spec = _sample_spec()
        self.written = emit_capability_code_scaffold(self.spec, self.project_root)
        (self.adapter_path, self.read_facade_path, self.capability_path,
         self.registry_path, self.registered_adapters_path) = self.written
        self.lib_dir = self.project_root / "agents" / "lib" / "external_write"
        self.cap_dir = self.project_root / "agents" / "capabilities"

    def tearDown(self):
        self._td.cleanup()

    def test_all_three_files_written_and_parse_as_valid_python(self):
        self.assertTrue(self.adapter_path.is_file())
        self.assertTrue(self.read_facade_path.is_file())
        self.assertTrue(self.capability_path.is_file())
        ast.parse(self.adapter_path.read_text(encoding="utf-8"))
        ast.parse(self.read_facade_path.read_text(encoding="utf-8"))
        ast.parse(self.capability_path.read_text(encoding="utf-8"))

    def test_read_facade_module_written_alongside_adapter_module(self):
        self.assertEqual(self.read_facade_path.parent, self.adapter_path.parent)
        self.assertEqual(self.read_facade_path.name,
                         f"{self.spec.read_facade_module_stem}.py")

    def test_adapter_registered_in_effective_adapter_profile_paths(self):
        effective = zones.effective_adapter_profile_paths(self.lib_dir)
        self.assertIn(f"{self.spec.adapter_module_stem}.py", effective)

    def test_read_facade_module_is_NOT_registered_in_adapter_profile_paths(self):
        # The whole point: the read-facade module is SCANNED, not exempt.
        effective = zones.effective_adapter_profile_paths(self.lib_dir)
        self.assertNotIn(f"{self.spec.read_facade_module_stem}.py", effective)

    def test_registry_file_content_lists_only_the_adapter_module(self):
        entries = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(entries, [f"{self.spec.adapter_module_stem}.py"])

    def test_scan_paths_reports_zero_violations(self):
        # Recursive over lib_dir + cap_dir -- covers all three emitted files.
        effective = zones.effective_adapter_profile_paths(self.lib_dir)
        violations = scan.scan_paths(
            [self.lib_dir, self.cap_dir],
            allowed_root=self.lib_dir,
            adapter_profile_paths=effective,
        )
        self.assertEqual(violations, [], f"expected zone-clean emit, got: {violations}")

    def test_read_facade_module_classifies_as_capability_and_scans_clean_alone(self):
        effective = zones.effective_adapter_profile_paths(self.lib_dir)
        zone = zones.classify_zone(
            self.read_facade_path, self.lib_dir.resolve(),
            adapter_profile_paths=effective,
        )
        self.assertEqual(zone, zones.Zone.CAPABILITY)
        violations = scan.scan_paths(
            [self.read_facade_path],
            allowed_root=self.lib_dir,
            adapter_profile_paths=frozenset(),
            sealed_kernel_paths=frozenset(),
        )
        self.assertEqual(violations, [])

    def test_read_facade_module_has_no_vendor_or_adapter_import(self):
        tree = ast.parse(self.read_facade_path.read_text(encoding="utf-8"))
        roots = set()
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
                modules.add(node.module)
        self.assertEqual(roots, {"typing", "external_write"})
        self.assertEqual(modules, {"typing", "external_write.read_facade"})
        self.assertNotIn(f"external_write.{self.spec.adapter_module_stem}", modules)

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

    def test_capability_module_import_list_is_EXACTLY_the_curated_surface(self):
        """The single most important golden-emit assertion (R7-T3, updated
        for v0.12.0 S1): the
        emitted capability module's `external_write` imports are EXACTLY
        `capability_api` (run_enveloped_operation, build_read_facade) and
        `operations`
        (whatever symbols it actually uses) -- nothing else. In particular
        it must NOT import adapters_<cap>, adapter_registry, get_adapter,
        read_facades_<cap>, external_write.read_facade, or the raw
        run_operation primitive at all."""
        tree = ast.parse(self.capability_path.read_text(encoding="utf-8"))
        imports_by_module = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports_by_module.setdefault(node.module, set()).update(
                    a.name for a in node.names)

        self.assertEqual(
            set(imports_by_module.keys()),
            {"typing", "external_write.capability_api", "external_write.operations"},
            f"capability module must import from EXACTLY these modules, got: "
            f"{sorted(imports_by_module.keys())}",
        )
        self.assertEqual(
            imports_by_module["external_write.capability_api"],
            {"run_enveloped_operation", "build_read_facade"},
        )
        # The raw kernel primitive must NOT be imported through any module.
        for mod, names in imports_by_module.items():
            self.assertNotIn(
                "run_operation", names,
                f"capability module must route through run_enveloped_operation, "
                f"not raw run_operation (found in import from {mod})",
            )
        self.assertTrue(
            imports_by_module["external_write.operations"],
            "must import at least one symbol from external_write.operations",
        )
        # No adapter module, no registry, no concrete facade class, no
        # kernel read_facade module (even the base class) reachable.
        forbidden_modules = {
            f"external_write.{self.spec.adapter_module_stem}",
            f"external_write.{self.spec.read_facade_module_stem}",
            "external_write.adapter_registry",
            "external_write.read_facade",
        }
        self.assertEqual(set(imports_by_module.keys()) & forbidden_modules, set())

    def test_capability_module_cannot_obtain_write_credential_provider(self):
        # BL-1 / F-33: the required property is now UNABLE TO OBTAIN, not merely
        # "does not call". The emitted CAPABILITY module must neither import nor
        # reference `write_credential_provider` ANYWHERE (no import alias, no
        # bare-name reference, no attribute access) -- so there is no provider
        # symbol for capability code to reach at all.
        tree = ast.parse(self.capability_path.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                offenders += [a.name for a in node.names
                              if a.name == "write_credential_provider"]
            elif isinstance(node, ast.Name) and node.id == "write_credential_provider":
                offenders.append(node.id)
            elif isinstance(node, ast.Attribute) and node.attr == "write_credential_provider":
                offenders.append(node.attr)
        self.assertEqual(
            offenders, [],
            "emitted CAPABILITY module must be UNABLE TO OBTAIN the write "
            "credential provider -- it must not import or reference "
            f"write_credential_provider at all (found: {offenders})")

    def test_scanner_flags_a_capability_that_DOES_reference_the_provider(self):
        # The regression guard the emitter change protects: a capability module
        # that (like the PRE-FIX shape) imports/holds write_credential_provider
        # is flagged by scan.scan_paths with credential_provider_reference. This
        # proves the "cannot obtain" property is enforced deterministically by
        # the scanner, not merely by how the current template happens to render.
        offending = self.cap_dir / "offending_capability.py"
        offending.write_text(
            "from external_write.adapters_acme_crm_sync import (\n"
            "    AcmeCrmSyncReadFacade,\n"
            "    write_credential_provider,\n"
            ")\n\n\n"
            "def run_approved(op, receipt):\n"
            "    return write_credential_provider\n",
            encoding="utf-8",
        )
        effective = zones.effective_adapter_profile_paths(self.lib_dir)
        violations = scan.scan_paths(
            [offending],
            allowed_root=self.lib_dir,
            adapter_profile_paths=effective,
        )
        kinds = {v.kind for v in violations}
        self.assertIn("credential_provider_reference", kinds,
                      f"scanner must flag a capability referencing the provider; got {violations}")

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

    def test_adapter_module_has_no_read_facade_class(self):
        # Task R7-T3: the ReadFacade subclass moved OUT of the adapter module.
        source = self.adapter_path.read_text(encoding="utf-8")
        self.assertNotIn(f"class {self.spec.class_prefix}ReadFacade", source)
        self.assertNotIn("register_read_facade", source)

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
    """Executing the emitted adapter + read-facade modules for real must land
    a working contract + adapter registration + read-facade registration and
    a VALID effects manifest whose dependency set covers the ADAPTER module
    (F-34), independent of the read-facade module."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.project_root = Path(self._td.name)
        self.spec = _sample_spec(
            capability_id="acme_crm_sync_rt",
            op_kind="acme_crm_rt.record.archive",
        )
        written = emit_capability_code_scaffold(self.spec, self.project_root)
        self.adapter_path, self.read_facade_path, self.capability_path, _, _ = written

        adapter_modname = "t10_golden_adapter_runtime_test_mod"
        adapter_spec_obj = importlib.util.spec_from_file_location(
            adapter_modname, self.adapter_path)
        adapter_module = importlib.util.module_from_spec(adapter_spec_obj)
        sys.modules[adapter_modname] = adapter_module
        adapter_spec_obj.loader.exec_module(adapter_module)
        self.adapter_module = adapter_module

        read_facade_modname = "t10_golden_read_facade_runtime_test_mod"
        rf_spec_obj = importlib.util.spec_from_file_location(
            read_facade_modname, self.read_facade_path)
        rf_module = importlib.util.module_from_spec(rf_spec_obj)
        sys.modules[read_facade_modname] = rf_module
        rf_spec_obj.loader.exec_module(rf_module)
        self.read_facade_module = rf_module

    def tearDown(self):
        self._td.cleanup()
        unregister_adapter(self.spec.op_kind)
        unregister_read_facade(self.spec.op_kind)
        OPERATION_CONTRACTS.pop(self.spec.op_kind, None)
        sys.modules.pop("t10_golden_adapter_runtime_test_mod", None)
        sys.modules.pop("t10_golden_read_facade_runtime_test_mod", None)

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

    def test_effects_manifest_is_valid_and_covers_the_adapter_module_only(self):
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
        # The read-facade module is NOT part of the hashed dependency set --
        # it carries no write-affecting behavior, only the read-only facade.
        self.assertFalse(
            any(str(self.read_facade_path.resolve()) == f for f in manifest.dependency_files),
            manifest.dependency_files,
        )

    def test_read_facade_declares_only_the_spec_read_methods(self):
        facade_cls = getattr(self.read_facade_module, f"{self.spec.class_prefix}ReadFacade")
        self.assertEqual(set(facade_cls.read_methods), set(self.spec.read_methods))

    def test_read_facade_class_lives_in_the_read_facade_module_not_the_adapter_module(self):
        facade_cls = getattr(self.read_facade_module, f"{self.spec.class_prefix}ReadFacade")
        self.assertEqual(facade_cls.__module__, self.read_facade_module.__name__)
        self.assertFalse(hasattr(self.adapter_module, f"{self.spec.class_prefix}ReadFacade"))


class TestReadFacadeSplitRegistryResolution(unittest.TestCase):
    """The R7-T3 core property: `build_read_facade(op_kind, client)`
    (capability-facing, two-arg form) resolves the EMITTED ReadFacade
    subclass from the KERNEL registry once read_facades_<cap>.py has been
    imported -- never from the adapter module -- and fails closed if it
    hasn't been."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.project_root = Path(self._td.name)
        self.spec = _sample_spec(
            capability_id="acme_crm_sync_reg",
            op_kind="acme_crm_reg.record.archive",
        )
        written = emit_capability_code_scaffold(self.spec, self.project_root)
        self.adapter_path, self.read_facade_path, self.capability_path, _, _ = written

        adapter_modname = "t10_reg_adapter_test_mod"
        adapter_spec_obj = importlib.util.spec_from_file_location(
            adapter_modname, self.adapter_path)
        adapter_module = importlib.util.module_from_spec(adapter_spec_obj)
        sys.modules[adapter_modname] = adapter_module
        adapter_spec_obj.loader.exec_module(adapter_module)
        self.adapter_module = adapter_module

    def tearDown(self):
        self._td.cleanup()
        unregister_adapter(self.spec.op_kind)
        unregister_read_facade(self.spec.op_kind)
        OPERATION_CONTRACTS.pop(self.spec.op_kind, None)
        sys.modules.pop("t10_reg_adapter_test_mod", None)
        sys.modules.pop("t10_reg_read_facade_test_mod", None)

    def test_build_read_facade_two_arg_fails_closed_before_read_facade_module_imported(self):
        # The adapter module (with its contract) is loaded, but the
        # read-facade module has never been imported -- nothing is
        # registered for this op_kind yet. Fail-closed, not a silent
        # fallback to a bare ReadFacade.
        with self.assertRaises(ReadFacadeEligibilityError):
            build_read_facade(self.spec.op_kind, object())

    def test_build_read_facade_two_arg_resolves_the_emitted_subclass_once_registered(self):
        read_facade_modname = "t10_reg_read_facade_test_mod"
        rf_spec_obj = importlib.util.spec_from_file_location(
            read_facade_modname, self.read_facade_path)
        rf_module = importlib.util.module_from_spec(rf_spec_obj)
        sys.modules[read_facade_modname] = rf_module
        rf_spec_obj.loader.exec_module(rf_module)

        facade_cls = getattr(rf_module, f"{self.spec.class_prefix}ReadFacade")
        facade = build_read_facade(self.spec.op_kind, object())
        self.assertIsInstance(facade, facade_cls)

        # The core anti-recovery property: the resolved facade's defining
        # module is the READ-FACADE module, never the adapter module -- a
        # capability that recovers facade.__class__.__module__ gets a
        # credential-free module, by construction.
        self.assertEqual(facade.__class__.__module__, rf_module.__name__)
        self.assertNotEqual(facade.__class__.__module__, self.adapter_module.__name__)
        self.assertFalse(hasattr(self.adapter_module, f"{self.spec.class_prefix}ReadFacade"))


class TestRegistryIdempotency(unittest.TestCase):
    def test_reemit_does_not_duplicate_registry_entry(self):
        with TemporaryDirectory() as td:
            project_root = Path(td)
            spec = _sample_spec(capability_id="idem_test_cap")
            emit_capability_code_scaffold(spec, project_root)
            _, _, _, registry_path, ra_path = emit_capability_code_scaffold(spec, project_root)
            entries = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(entries, ["adapters_idem_test_cap.py"])
            # registered_adapters.py (Task 7 / F-37): re-emitting the same
            # capability's own module must not duplicate its import line.
            ra_content = ra_path.read_text(encoding="utf-8")
            self.assertEqual(ra_content.count("import external_write.adapters_idem_test_cap"), 1)

    def test_reemit_preserves_other_capabilities_already_registered(self):
        with TemporaryDirectory() as td:
            project_root = Path(td)
            first = _sample_spec(capability_id="first_cap")
            second = _sample_spec(capability_id="second_cap",
                                  op_kind="second_cap.record.archive")
            emit_capability_code_scaffold(first, project_root)
            _, _, _, registry_path, ra_path = emit_capability_code_scaffold(second, project_root)
            entries = set(json.loads(registry_path.read_text(encoding="utf-8")))
            self.assertEqual(entries, {"adapters_first_cap.py", "adapters_second_cap.py"})
            ra_content = ra_path.read_text(encoding="utf-8")
            self.assertIn("import external_write.adapters_first_cap", ra_content)
            self.assertIn("import external_write.adapters_second_cap", ra_content)

    def test_reemit_never_adds_the_read_facade_module_to_the_registry(self):
        with TemporaryDirectory() as td:
            project_root = Path(td)
            spec = _sample_spec(capability_id="idem_test_cap_rf")
            emit_capability_code_scaffold(spec, project_root)
            _, _, _, registry_path, ra_path = emit_capability_code_scaffold(spec, project_root)
            entries = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(entries, ["adapters_idem_test_cap_rf.py"])
            ra_content = ra_path.read_text(encoding="utf-8")
            self.assertNotIn("read_facades_idem_test_cap_rf", ra_content)

    def test_reemit_two_different_capabilities_with_colliding_op_kind_refuses(self):
        """AC-T7/BI-1: the scaffold generation asserts the registry's import
        set registers no duplicate op_kind -- a plain, resumable
        CapabilityCodeScaffoldError, not a silent double-registration."""
        with TemporaryDirectory() as td:
            project_root = Path(td)
            first = _sample_spec(capability_id="dup_op_kind_cap_a",
                                 op_kind="dup_test.record.archive")
            second = _sample_spec(capability_id="dup_op_kind_cap_b",
                                  op_kind="dup_test.record.archive")
            emit_capability_code_scaffold(first, project_root)
            with self.assertRaises(CapabilityCodeScaffoldError) as ctx:
                emit_capability_code_scaffold(second, project_root)
            msg = str(ctx.exception)
            self.assertIn("dup_test.record.archive", msg)
            self.assertIn("adapters_dup_op_kind_cap_a.py", msg)


class TestRunEnvelopeSurfaceIsShapeNeutral(unittest.TestCase):
    """v0.12.0 S1 anti-overfit: the surface change (route through
    run_enveloped_operation, never raw run_operation) must be shape-neutral --
    it holds for divergent op_kinds, not just the record/row sample. Exercises
    a Gmail-style VERB op AND a field/row op end-to-end: the emitted capability
    module (1) imports run_enveloped_operation, (2) NEVER references raw
    run_operation anywhere, and (3) scans clean under the new
    raw_run_operation_reference rule (with an EMPTY adapter-profile allowlist,
    so the capability module's cleanliness is on its own CAPABILITY-zone
    merits)."""

    # Two deliberately divergent op_kinds (mirrors the scanner's Sheets/Gmail
    # verb split): a Gmail-style verb op and an Acme field/row op.
    _DIVERGENT_SPECS = (
        dict(capability_id="gmail_message_archiver",
             display_name="Gmail message archiver",
             op_kind="gmail.message.archive",
             surface="gmail",
             read_only_scope="gmail.readonly",
             blast_radius_cap=5,
             read_methods=("list_messages", "get_message")),
        dict(capability_id="acme_field_updater",
             display_name="Acme field updater",
             op_kind="acme_crm.field.update",
             surface="acme_crm",
             read_only_scope="acme_crm.readonly",
             blast_radius_cap=25,
             read_methods=("list_rows", "get_row")),
    )

    def _emit_and_read_capability(self, td, spec_kwargs):
        spec = CapabilityCodeSpec(**spec_kwargs)
        written = emit_capability_code_scaffold(spec, Path(td))
        _adapter, _rf, capability_path, _registry, _reg_adapters = written
        lib_dir = Path(td) / "agents" / "lib" / "external_write"
        return spec, capability_path, lib_dir

    def test_divergent_op_kinds_route_through_envelope_and_scan_clean(self):
        for spec_kwargs in self._DIVERGENT_SPECS:
            with self.subTest(op_kind=spec_kwargs["op_kind"]):
                with TemporaryDirectory() as td:
                    spec, capability_path, lib_dir = self._emit_and_read_capability(
                        td, spec_kwargs)
                    src = capability_path.read_text(encoding="utf-8")

                    # (1) imports the sanctioned enveloped entrypoint...
                    tree = ast.parse(src)
                    imported = set()
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ImportFrom):
                            imported.update(a.name for a in node.names)
                    self.assertIn("run_enveloped_operation", imported)

                    # (2) ...and NEVER references raw run_operation (import,
                    # bare Name, or attribute) anywhere in the module.
                    offenders = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ImportFrom):
                            offenders += [a.name for a in node.names
                                          if a.name == "run_operation"]
                        elif isinstance(node, ast.Name) and node.id == "run_operation":
                            offenders.append(node.id)
                        elif isinstance(node, ast.Attribute) and node.attr == "run_operation":
                            offenders.append(node.attr)
                    self.assertEqual(
                        offenders, [],
                        f"emitted capability for {spec.op_kind} must not name raw "
                        f"run_operation; found {offenders}")

                    # (3) scans clean on its own CAPABILITY-zone merits (empty
                    # adapter-profile + sealed-kernel allowlists), including the
                    # new raw_run_operation_reference rule.
                    violations = scan.scan_paths(
                        [capability_path],
                        allowed_root=lib_dir,
                        adapter_profile_paths=frozenset(),
                        sealed_kernel_paths=frozenset(),
                    )
                    self.assertEqual(
                        violations, [],
                        f"emitted capability for {spec.op_kind} must scan clean; "
                        f"got {violations}")

    def test_whole_divergent_emit_trio_scans_clean(self):
        # End-to-end: emit the full trio for each divergent op_kind and scan
        # the whole lib_dir + cap_dir together under the REAL effective
        # adapter-profile allowlist -- the anti-overfit end-to-end check.
        for spec_kwargs in self._DIVERGENT_SPECS:
            with self.subTest(op_kind=spec_kwargs["op_kind"]):
                with TemporaryDirectory() as td:
                    spec = CapabilityCodeSpec(**spec_kwargs)
                    emit_capability_code_scaffold(spec, Path(td))
                    lib_dir = Path(td) / "agents" / "lib" / "external_write"
                    cap_dir = Path(td) / "agents" / "capabilities"
                    effective = zones.effective_adapter_profile_paths(lib_dir)
                    violations = scan.scan_paths(
                        [lib_dir, cap_dir],
                        allowed_root=lib_dir,
                        adapter_profile_paths=effective,
                    )
                    self.assertEqual(
                        violations, [],
                        f"divergent emit trio for {spec.op_kind} must be "
                        f"zone-clean; got {violations}")


if __name__ == "__main__":
    unittest.main()
