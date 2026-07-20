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
import shutil
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
    assert_identity_coherent,
    canonical_id_from_module_stem,
)
from external_write.capability_registration import register_declared_capability  # noqa: E402


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


class TestAssertIdentityCoherent(unittest.TestCase):
    """Task A2 / A3.1: the build-time 4-way identity invariant. `surface` is deliberately NOT a
    parameter -- these tests lock that exclusion as the keystone correction (a capability's
    external-system surface legitimately differs from its identity; only descriptor_id,
    capability_id, mechanism_id, and module_stem must all agree)."""

    def test_four_way_match_passes(self):
        assert_identity_coherent(descriptor_id="acme_crm_sync", capability_id="acme_crm_sync",
                                 mechanism_id="acme_crm_sync", module_stem="acme_crm_sync")

    def test_surface_differing_from_capability_id_is_allowed(self):
        # The keystone correction: surface is the external-system id, not the identity.
        assert_identity_coherent(descriptor_id="acme_crm_sync", capability_id="acme_crm_sync",
                                 mechanism_id="acme_crm_sync", module_stem="acme_crm_sync")  # no raise

    def test_descriptor_id_set_to_surface_is_rejected(self):
        # The estate anti-pattern: descriptor id == surface ("inbox-labels") != capability_id ("inbox_management")
        with self.assertRaises(CapabilityCodeScaffoldError):
            assert_identity_coherent(descriptor_id="inbox-labels", capability_id="inbox_management",
                                     mechanism_id="inbox_management", module_stem="inbox_management")

    def test_mechanism_id_mismatch_is_rejected(self):
        with self.assertRaises(CapabilityCodeScaffoldError):
            assert_identity_coherent(descriptor_id="acme_crm_sync", capability_id="acme_crm_sync",
                                     mechanism_id="stale_mechanism_id", module_stem="acme_crm_sync")

    def test_module_stem_mismatch_is_rejected(self):
        with self.assertRaises(CapabilityCodeScaffoldError):
            assert_identity_coherent(descriptor_id="acme_crm_sync", capability_id="acme_crm_sync",
                                     mechanism_id="acme_crm_sync", module_stem="a_different_stem")

    def test_all_four_different_is_rejected(self):
        with self.assertRaises(CapabilityCodeScaffoldError):
            assert_identity_coherent(descriptor_id="a", capability_id="b",
                                     mechanism_id="c", module_stem="d")

    def test_error_message_is_plain_language_not_a_traceback(self):
        try:
            assert_identity_coherent(descriptor_id="inbox-labels", capability_id="inbox_management",
                                     mechanism_id="inbox_management", module_stem="inbox_management")
            self.fail("expected CapabilityCodeScaffoldError")
        except CapabilityCodeScaffoldError as e:
            msg = str(e)
            self.assertNotIn("Traceback", msg)
            self.assertIn("inbox-labels", msg)
            self.assertIn("inbox_management", msg)

    def test_canonical_id_from_module_stem_strips_suffix(self):
        self.assertEqual(canonical_id_from_module_stem("acme_crm_sync_capability"), "acme_crm_sync")

    def test_canonical_id_from_module_stem_leaves_already_canonical_unchanged(self):
        self.assertEqual(canonical_id_from_module_stem("acme_crm_sync"), "acme_crm_sync")

    def test_capability_code_spec_canonical_id_matches_capability_id(self):
        self.assertEqual(_sample_spec().canonical_id, _sample_spec().capability_id)


class TestAssertIdentityCoherentCrossTreePin(unittest.TestCase):
    """capability_registration.py (operate-time; MUST NOT import the build-side tree) cannot
    import this module's `assert_identity_coherent` directly, so `capability_identity.py` (same
    package as capability_registration.py) carries its own duplicate -- exactly the established
    duplicate-plus-cross-tree-pin convention this codebase already uses for
    REGISTERED_ENTRY_KEYS / BASE_DESCRIPTOR_ID_PREFIX / etc. This pins the two copies' behavior
    (and message wording) equal, so a future edit to one without the other fails closed here
    instead of silently drifting."""

    def test_pass_fail_decisions_match_across_a_battery_of_inputs(self):
        from external_write.capability_identity import (
            assert_identity_coherent as operate_time_assert,
            IdentityCoherenceError,
        )
        cases = [
            dict(descriptor_id="acme_crm_sync", capability_id="acme_crm_sync",
                mechanism_id="acme_crm_sync", module_stem="acme_crm_sync"),
            dict(descriptor_id="inbox-labels", capability_id="inbox_management",
                mechanism_id="inbox_management", module_stem="inbox_management"),
            dict(descriptor_id="a", capability_id="b", mechanism_id="c", module_stem="d"),
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                build_raised = None
                try:
                    assert_identity_coherent(**kwargs)
                except CapabilityCodeScaffoldError as e:
                    build_raised = str(e)
                operate_raised = None
                try:
                    operate_time_assert(**kwargs)
                except IdentityCoherenceError as e:
                    operate_raised = str(e)
                self.assertEqual(build_raised is None, operate_raised is None,
                                 "the two copies must agree on pass/fail")
                if build_raised is not None:
                    self.assertEqual(build_raised, operate_raised,
                                     "the two copies' messages must stay byte-identical")


class TestCapabilityRegistrationIdentityCoherence(unittest.TestCase):
    """A2 / A3.1 integration: capability_registration.register_declared_capability refuses to
    land a descriptor whose id does not match the canonical id of the capability module it
    registers -- catching the estate anti-pattern (descriptor id set to the capability's
    SURFACE) before it ever lands, while never firing on a legitimate surface != capability_id."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.project_root = Path(self._td.name)
        (self.project_root / "security").mkdir(parents=True, exist_ok=True)
        self.descriptor_set_path = self.project_root / "security" / "capability_descriptors.json"
        self.descriptor_set_path.write_text("[]\n", encoding="utf-8")
        self.co_protected_path = self.project_root / "quality" / "co-protected-workflows.md"

    def tearDown(self):
        self._td.cleanup()

    def _register(self, cap_id, **overrides):
        declared = dict(
            id=cap_id,
            name=cap_id,
            action_class="mutate",
            risk_class="reversible_external",  # non-gated: no co-protected table needed
            recovery_profile_ref="rp-1",
            declared_test_target="copy",
            blast_radius_cap=5,
            phase_id="phase_01",
            accepted=False,
        )
        declared.update(overrides)
        return register_declared_capability(
            declared,
            descriptor_set_path=str(self.descriptor_set_path),
            co_protected_path=str(self.co_protected_path),
            project_root=str(self.project_root),
        )

    def test_capability_id_differing_from_its_own_surface_is_allowed(self):
        # The keystone regression: surface != capability_id must never itself trigger a refusal.
        # (Also doubles as the ordinary happy-path case: a descriptor id that matches its own
        # emitted module registers normally.)
        spec = _sample_spec(capability_id="acme_crm_sync", surface="acme_crm")
        emit_capability_code_scaffold(spec, self.project_root)
        res = self._register("acme_crm_sync")
        self.assertTrue(res.registered, res.reason)

    def test_descriptor_id_set_to_a_different_capabilitys_surface_is_refused(self):
        spec = _sample_spec(capability_id="inbox_management", surface="inbox-labels",
                            op_kind="inbox.label.apply")
        emit_capability_code_scaffold(spec, self.project_root)
        res = self._register("inbox-labels")
        self.assertFalse(res.registered)
        self.assertIn("inbox_management", res.reason)
        # No half-registration: nothing was landed under the bad id.
        entries = json.loads(self.descriptor_set_path.read_text(encoding="utf-8"))
        self.assertEqual(entries, [])

    def test_refusal_goes_through_assert_identity_coherent_primitive(self):
        # CRITICAL regression (coordinator review): assert_identity_coherent must be a REAL
        # production caller on the registration path, not a zero-caller trust primitive that
        # only its own unit tests exercise. Proves it two ways: (a) monkeypatching
        # capability_registration's imported reference and observing it is actually invoked
        # with the real four values (descriptor_id, capability_id, mechanism_id, module_stem);
        # (b) the refusal message carries assert_identity_coherent's own distinctive wording,
        # not just a bespoke registration-layer string.
        from external_write import capability_registration as cr

        spec = _sample_spec(capability_id="inbox_management", surface="inbox-labels",
                            op_kind="inbox.label.apply2")
        emit_capability_code_scaffold(spec, self.project_root)

        calls = []
        real_assert = cr.assert_identity_coherent

        def _spy(**kwargs):
            calls.append(kwargs)
            return real_assert(**kwargs)

        cr.assert_identity_coherent = _spy
        try:
            res = self._register("inbox-labels")
        finally:
            cr.assert_identity_coherent = real_assert

        self.assertFalse(res.registered)
        self.assertEqual(len(calls), 1, "assert_identity_coherent must be called exactly once "
                         "on the registration path")
        self.assertEqual(calls[0]["descriptor_id"], "inbox-labels")
        self.assertEqual(calls[0]["capability_id"], "inbox_management")
        self.assertEqual(calls[0]["module_stem"], "inbox_management")
        self.assertEqual(calls[0]["mechanism_id"], "inbox_management")
        self.assertIn(
            "must all be the exact SAME identifier", res.reason,
            "refusal message must carry assert_identity_coherent's own wording -- proving the "
            "primitive, not a bespoke bypassing check, decided the refusal")

    def test_not_yet_emitted_capability_id_registers_normally(self):
        # No capability module has been emitted anywhere yet under this id -- a legitimate,
        # not-yet-built capability (e.g. read-only, which skips the code-scaffold step entirely)
        # must not be refused merely for having no module on disk yet.
        res = self._register("status_sync")
        self.assertTrue(res.registered, res.reason)

    def test_registering_a_surface_shared_by_no_module_is_unaffected(self):
        # A surface string that doesn't collide with anything is just an ordinary new id.
        spec = _sample_spec()
        emit_capability_code_scaffold(spec, self.project_root)
        res = self._register("some_other_new_capability")
        self.assertTrue(res.registered, res.reason)

    def test_stale_mechanism_alias_does_not_block_a_correct_registration(self):
        # Coordinator review fix (2nd pass): capability_id, mechanism_id, and module_stem are
        # all the CANONICAL id BY CONSTRUCTION at registration time (the scaffold derives module
        # + mechanism from capability_id) -- the only INDEPENDENT input under test is
        # descriptor_id. A stale agents/handoffs/pending_migrations.json entry recording a
        # NON-canonical mechanism_id alias for this capability (e.g. "inbox-labels" for canonical
        # "inbox_management" -- a real, tolerated A1 alias, not a new violation) must NOT block
        # re-registering the capability's OWN correct descriptor (descriptor_id ==
        # capability_id == canonical). Before the fix, identity.mechanism_id (the raw alias) was
        # fed into assert_identity_coherent verbatim, so a perfectly legitimate, self-consistent
        # registration was falsely refused.
        spec = _sample_spec(capability_id="inbox_management", surface="inbox-labels",
                            op_kind="inbox.label.apply3")
        emit_capability_code_scaffold(spec, self.project_root)
        handoffs_dir = self.project_root / "agents" / "handoffs"
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        (handoffs_dir / "pending_migrations.json").write_text(
            json.dumps([{"mechanism_id": "inbox-labels"}]), encoding="utf-8")
        res = self._register("inbox_management")
        self.assertTrue(res.registered, res.reason)

    def test_new_capability_id_matching_an_unrelated_surface_is_allowed(self):
        # Coordinator review fix (resolve() precedence): registering "foo" must not be refused
        # merely because some OTHER already-emitted capability's own SURFACE happens to equal
        # "foo" -- an exact canonical-id / own-module-stem match must always win.
        foo_spec = _sample_spec(capability_id="foo", surface="foo_surface_unused",
                                op_kind="foo.op.kind")
        bar_spec = _sample_spec(capability_id="bar_sync", surface="foo",
                                op_kind="bar.op.kind")
        emit_capability_code_scaffold(foo_spec, self.project_root)
        emit_capability_code_scaffold(bar_spec, self.project_root)
        res = self._register("foo")
        self.assertTrue(res.registered, res.reason)


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
        for v0.12.0 S1; extended by D6c for the sanctioned bulk-run helper):
        the emitted capability module's `external_write` imports are EXACTLY
        `capability_api` (run_enveloped_operation, run_sanctioned_bulk,
        build_read_facade) and `operations`
        (whatever symbols it actually uses) -- nothing else. In particular
        it must NOT import adapters_<cap>, adapter_registry, get_adapter,
        read_facades_<cap>, external_write.read_facade, mint_run_envelope, or
        the raw run_operation primitive at all."""
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
            {"run_enveloped_operation", "run_sanctioned_bulk", "build_read_facade"},
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


class TestGoldenEmitBulkWrapper(unittest.TestCase):
    """D6c: the scaffold emits a `run_bulk_approved` wrapper (symmetric to
    the existing single-op `run_approved`) that delegates to
    `capability_api.run_sanctioned_bulk` and NEVER mints -- the emitted
    capability zone must be UNABLE to hand-roll a per-batch mint loop (the
    F-79/F-80 anti-pattern), by construction, not by convention."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.project_root = Path(self._td.name)
        self.spec = _sample_spec()
        self.written = emit_capability_code_scaffold(self.spec, self.project_root)
        (self.adapter_path, self.read_facade_path, self.capability_path,
         self.registry_path, self.registered_adapters_path) = self.written
        self.lib_dir = self.project_root / "agents" / "lib" / "external_write"
        self.cap_dir = self.project_root / "agents" / "capabilities"
        self.source = self.capability_path.read_text(encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def test_emitted_capability_defines_run_bulk_approved(self):
        self.assertIn("def run_bulk_approved(", self.source)

    def test_run_bulk_approved_delegates_to_run_sanctioned_bulk(self):
        self.assertIn("run_sanctioned_bulk(", self.source)

    def test_emitted_capability_never_mints(self):
        # The whole point of D6c: the emitted CAPABILITY zone cannot even
        # NAME mint_run_envelope -- the helper owns the mint (Decision 1).
        self.assertNotIn("mint_run_envelope", self.source)

    def test_run_bulk_approved_is_valid_python_and_never_names_run_operation(self):
        tree = ast.parse(self.source)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                offenders += [a.name for a in node.names if a.name == "run_operation"]
            elif isinstance(node, ast.Name) and node.id == "run_operation":
                offenders.append(node.id)
            elif isinstance(node, ast.Attribute) and node.attr == "run_operation":
                offenders.append(node.attr)
        self.assertEqual(offenders, [])

    def test_all_three_emitted_files_still_scan_clean(self):
        effective = zones.effective_adapter_profile_paths(self.lib_dir)
        violations = scan.scan_paths(
            [self.lib_dir, self.cap_dir],
            allowed_root=self.lib_dir,
            adapter_profile_paths=effective,
        )
        self.assertEqual(violations, [], f"expected zone-clean emit, got: {violations}")


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
            _, _, _, registry_path, oa_path = emit_capability_code_scaffold(spec, project_root)
            entries = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(entries, ["adapters_idem_test_cap.py"])
            # operator_adapters.json (Task B3 / F-76): re-emitting the same
            # capability's own module must not duplicate its manifest entry.
            oa_entries = json.loads(oa_path.read_text(encoding="utf-8"))
            self.assertEqual(oa_entries.count("adapters_idem_test_cap"), 1)

    def test_reemit_preserves_other_capabilities_already_registered(self):
        with TemporaryDirectory() as td:
            project_root = Path(td)
            first = _sample_spec(capability_id="first_cap")
            second = _sample_spec(capability_id="second_cap",
                                  op_kind="second_cap.record.archive")
            emit_capability_code_scaffold(first, project_root)
            _, _, _, registry_path, oa_path = emit_capability_code_scaffold(second, project_root)
            entries = set(json.loads(registry_path.read_text(encoding="utf-8")))
            self.assertEqual(entries, {"adapters_first_cap.py", "adapters_second_cap.py"})
            oa_entries = set(json.loads(oa_path.read_text(encoding="utf-8")))
            self.assertEqual(oa_entries, {"adapters_first_cap", "adapters_second_cap"})

    def test_reemit_never_adds_the_read_facade_module_to_the_registry(self):
        with TemporaryDirectory() as td:
            project_root = Path(td)
            spec = _sample_spec(capability_id="idem_test_cap_rf")
            emit_capability_code_scaffold(spec, project_root)
            _, _, _, registry_path, oa_path = emit_capability_code_scaffold(spec, project_root)
            entries = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(entries, ["adapters_idem_test_cap_rf.py"])
            oa_content = oa_path.read_text(encoding="utf-8")
            self.assertNotIn("read_facades_idem_test_cap_rf", oa_content)

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

    def test_new_capability_colliding_with_baseline_gmail_op_kind_refuses(self):
        """B3 review fix (Fix 3c, F-76): only an operator-vs-operator
        collision was covered before -- an operator-vs-BASELINE (shipped
        Gmail) op_kind collision must be caught by
        `_assert_no_duplicate_op_kind` too. Uses the real, shipped
        `adapters_gmail.py` copied alongside a fresh project's
        `external_write_dir` (mirrors what a real project actually has on
        disk); no `registered_adapters.py` is present locally, so the
        baseline module list falls back to `_REGISTERED_ADAPTERS_BASELINE`
        (byte-pinned to the real shipped file elsewhere in this suite)."""
        with TemporaryDirectory() as td:
            project_root = Path(td)
            external_write_dir = project_root / "agents" / "lib" / "external_write"
            external_write_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_AGENTS_LIB / "external_write" / "adapters_gmail.py",
                        external_write_dir / "adapters_gmail.py")

            colliding = _sample_spec(capability_id="gmail_collider_cap",
                                     op_kind="gmail.message.trash")
            with self.assertRaises(CapabilityCodeScaffoldError) as ctx:
                emit_capability_code_scaffold(colliding, project_root)
            msg = str(ctx.exception)
            self.assertIn("gmail.message.trash", msg)
            self.assertIn("adapters_gmail.py", msg)


class TestRegisteredAdaptersBaselineMatchesShippedFile(unittest.TestCase):
    """MINOR regression (Task 7 code-review finding): `_REGISTERED_ADAPTERS_BASELINE`
    (the fallback content used ONLY when a target project's registered_adapters.py
    does not exist yet) is a hand-duplicated second source of truth for the real,
    shipped `agents/lib/external_write/registered_adapters.py` -- previously it
    carried a ~2-line stub docstring against the real file's ~40-line one, already
    drifted. Both files now carry an explicit cross-reference comment pointing at
    each other; this test is the enforcement half of that discipline -- it pins
    BYTE equality between the baseline constant and the real shipped file, so a
    future edit to one without the other fails closed here instead of silently
    drifting again."""

    def test_baseline_constant_is_byte_identical_to_shipped_file(self):
        shipped_path = (
            Path(__file__).resolve().parents[2]
            / "agents" / "lib" / "external_write" / "registered_adapters.py")
        shipped_content = shipped_path.read_text(encoding="utf-8")
        self.assertEqual(
            ccs._REGISTERED_ADAPTERS_BASELINE, shipped_content,
            "capability_code_scaffold._REGISTERED_ADAPTERS_BASELINE has drifted "
            "from the real agents/lib/external_write/registered_adapters.py -- "
            "update the baseline constant to match (see the cross-reference "
            "comment above the constant, and in that file's own docstring)")


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


class TestMissingEvidencePredicateStubScaffold(unittest.TestCase):
    """Task B2, F-75: the migrator's auto-scaffold for a required adapter
    evidence predicate an EXISTING adapter module does not declare (e.g.
    because a contract-changing upgrade added a NEW name to `evidence.
    REQUIRED_EVIDENCE_PREDICATES` after this adapter was already built).

    NEVER a passing stub -- the locked, hard anti-trust-theater requirement:
    the scaffolded method body must be exactly `raise NotImplementedError
    (...)`, never `return True`/`pass`/anything that could look like a real
    check. These tests assert that structurally (AST), not just by string
    search, so a future edit that adds so much as a second statement to the
    stub body would fail here."""

    def test_render_stub_defines_exactly_one_method(self):
        src = ccs.render_missing_evidence_predicate_stub("verify_apply_landed")
        tree = ast.parse(f"class _X:\n{src}")
        class_node = tree.body[0]
        self.assertIsInstance(class_node, ast.ClassDef)
        funcs = [n for n in class_node.body if isinstance(n, ast.FunctionDef)]
        self.assertEqual([f.name for f in funcs], ["verify_apply_landed"])

    def test_stub_body_is_only_a_raise_not_implemented_error(self):
        # NEVER a passing stub -- structural proof, not a string search: the
        # rendered method's body must be exactly ONE statement, and that
        # statement must be `raise NotImplementedError(...)`.
        for predicate_name in ("verify_apply_landed", "verify_undo_restored",
                                "verify_some_future_predicate"):
            with self.subTest(predicate_name=predicate_name):
                src = ccs.render_missing_evidence_predicate_stub(predicate_name)
                tree = ast.parse(f"class _X:\n{src}")
                func = tree.body[0].body[0]
                self.assertEqual(func.name, predicate_name)
                self.assertEqual(len(func.body), 1, "stub must be a SINGLE statement")
                stmt = func.body[0]
                self.assertIsInstance(stmt, ast.Raise)
                self.assertIsInstance(stmt.exc, ast.Call)
                self.assertEqual(stmt.exc.func.id, "NotImplementedError")
                message = stmt.exc.args[0].value
                self.assertIn("stays paused", message)
                self.assertIn("implemented and proved", message)

    def test_named_predicates_get_their_own_plain_language_wording(self):
        landed_msg = ccs._MISSING_EVIDENCE_PREDICATE_MESSAGES["verify_apply_landed"]
        undo_msg = ccs._MISSING_EVIDENCE_PREDICATE_MESSAGES["verify_undo_restored"]
        self.assertIn("landed", landed_msg)
        self.assertIn("undone", undo_msg)
        self.assertNotEqual(landed_msg, undo_msg)

    def test_stub_never_annotates_evidence_as_any(self):
        # A stub is inserted into an EXISTING adapter module this function never
        # inspects the imports of -- annotating the parameter `evidence: Any`
        # would silently assume that module already imports `Any` from typing
        # and raise NameError at import time for one that does not.
        src = ccs.render_missing_evidence_predicate_stub("verify_apply_landed")
        self.assertNotIn(": Any", src)
        self.assertIn("def verify_apply_landed(self, evidence)", src)

    def test_insert_adds_missing_methods_before_register_adapter(self):
        spec = _sample_spec()
        base_source = render_adapter_module(spec)
        # Sanity on the fixture: a FRESH scaffold declares neither predicate at
        # all (see render_adapter_module's own turnkey-honesty TODO).
        self.assertNotIn("def verify_apply_landed", base_source)
        self.assertNotIn("def verify_undo_restored", base_source)

        new_source = ccs.insert_missing_evidence_predicate_stubs(
            base_source, ["verify_apply_landed", "verify_undo_restored"])
        ast.parse(new_source)  # must stay syntactically valid Python

        self.assertIn("def verify_apply_landed(self, evidence)", new_source)
        self.assertIn("def verify_undo_restored(self, evidence)", new_source)
        register_idx = new_source.index("register_adapter(OP_KIND")
        self.assertLess(new_source.index("def verify_apply_landed"), register_idx)
        self.assertLess(new_source.index("def verify_undo_restored"), register_idx)

        # Both stubs land as METHODS on the adapter class (indented inside it),
        # never as free module-level functions -- confirm via AST that they are
        # both members of the SAME class the base module already declares.
        tree = ast.parse(new_source)
        class_node = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        method_names = {n.name for n in class_node.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("verify_apply_landed", method_names)
        self.assertIn("verify_undo_restored", method_names)

    def test_insert_is_a_noop_for_an_empty_missing_list(self):
        base_source = render_adapter_module(_sample_spec())
        self.assertEqual(
            ccs.insert_missing_evidence_predicate_stubs(base_source, []), base_source)

    def test_insert_refuses_to_guess_when_no_register_adapter_call_present(self):
        with self.assertRaises(CapabilityCodeScaffoldError):
            ccs.insert_missing_evidence_predicate_stubs(
                "class X:\n    pass\n", ["verify_apply_landed"])

    def test_scaffolded_adapter_is_actually_importable_without_a_typing_import(self):
        # End-to-end: a hand-written-style adapter module with NO `from typing
        # import Any` at all must still import cleanly after the stub is
        # inserted -- this is the real regression this task's own fix guards
        # (a `: Any`-annotated stub would NameError on import for exactly this
        # shape of module).
        source = (
            '"""fixture adapter -- deliberately no typing import."""\n'
            "from external_write.adapter_registry import register_adapter\n\n"
            'OP_KIND = "_ccs_b2_import_probe"\n\n\n'
            "class _CcsB2ImportProbeAdapter:\n"
            "    def plan(self, params):\n"
            "        return []\n\n"
            "    def apply_one(self, raw_client, unit):\n"
            "        pass\n\n"
            "    def undo_one(self, raw_client, unit):\n"
            "        pass\n\n"
            "    def verify_one(self, observer, unit):\n"
            "        return {}\n\n\n"
            "register_adapter(OP_KIND, _CcsB2ImportProbeAdapter())\n"
        )
        new_source = ccs.insert_missing_evidence_predicate_stubs(
            source, ["verify_apply_landed", "verify_undo_restored"])
        with TemporaryDirectory() as td:
            mod_path = Path(td) / "adapters__ccs_b2_import_probe.py"
            mod_path.write_text(new_source, encoding="utf-8")
            module_spec = importlib.util.spec_from_file_location(
                "adapters__ccs_b2_import_probe", mod_path)
            module = importlib.util.module_from_spec(module_spec)
            try:
                module_spec.loader.exec_module(module)
            finally:
                unregister_adapter("_ccs_b2_import_probe")
            instance = module._CcsB2ImportProbeAdapter()
            with self.assertRaises(NotImplementedError):
                instance.verify_apply_landed(None)
            with self.assertRaises(NotImplementedError):
                instance.verify_undo_restored(None)


if __name__ == "__main__":
    unittest.main()
