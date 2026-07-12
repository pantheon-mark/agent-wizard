"""Tests for the deterministic AST bypass scanner — the build-time root-of-trust.

The scanner fails the build if any operator-system script mutates an external
surface OUTSIDE the emitted named-operation adapters. It is deterministic AST +
within-file call-graph analysis, NOT grep and NOT LLM judgment, because the
bypass classes below (helper indirection, dynamic import, subprocess curl)
are invisible to a textual scan.

Fixtures live under wizard/test_fixtures/external_write_scan/.

Test intents:
  1. legal_through_adapter.py        -> 0 violations (must not false-positive)
  2. benign_local.py                 -> 0 violations (local data work, non-net subprocess)
  3. direct_api_call.py              -> direct_api_call violation(s)
  4. forbidden_import.py             -> forbidden_import violation(s)
  5. helper_indirection.py           -> violation (call-graph reach, not surface-only)
  6. dynamic_import.py               -> dynamic_import violation(s)
  7. subprocess_curl.py              -> subprocess_network violation(s)
  8. scanning a directory aggregates violations across files
  9. code INSIDE the allowed module (adapters.py) is exempt
  10. Task 5 — credential-access is flagged independent of forbidden_import
  11. Task 5 — trust-zone split: sealed-kernel is not blanket-exempt,
      adapter-profile requires EXPLICIT registration (not directory location)
"""

import sys
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.scan import scan_paths, Violation  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES = _REPO_ROOT / "wizard" / "test_fixtures" / "external_write_scan"
_ADAPTER_DIR = _REPO_ROOT / "wizard" / "agents" / "lib" / "external_write"


def _kinds(violations):
    return sorted({v.kind for v in violations})


class TestLegalCases(unittest.TestCase):
    def test_routing_through_adapter_is_clean(self):
        v = scan_paths([_FIXTURES / "legal_through_adapter.py"])
        self.assertEqual(v, [], "legal adapter-routing script must not be flagged")

    def test_benign_local_work_is_clean(self):
        v = scan_paths([_FIXTURES / "benign_local.py"])
        self.assertEqual(v, [], "local-only data work must not be flagged")

    def test_allowed_module_code_is_exempt(self):
        # The real adapters/broker make legitimate surface calls; scanning the
        # allowed module itself must yield zero violations.
        v = scan_paths([_ADAPTER_DIR])
        self.assertEqual(v, [], "code inside the allowed module must be exempt")


class TestDirectApiCall(unittest.TestCase):
    def test_direct_sheets_mutation_flagged(self):
        v = scan_paths([_FIXTURES / "direct_api_call.py"])
        self.assertTrue(v, "direct mutation API calls must be flagged")
        self.assertIn("direct_api_call", _kinds(v))
        # update, batchUpdate, append -> three distinct call sites.
        direct = [x for x in v if x.kind == "direct_api_call"]
        self.assertGreaterEqual(len(direct), 3)
        for viol in direct:
            self.assertIsInstance(viol.lineno, int)
            self.assertGreater(viol.lineno, 0)


class TestGmailDirectApiCall(unittest.TestCase):
    """NF1 (external-write-gate-generalization fix-wave, Task R2) — Gmail
    mutation verbs added to ``direct_api_call`` as a defense-in-depth layer
    (a direct Gmail mutation is already indirectly caught via
    forbidden_import + credential_construction; this adds a first-class
    surface-mutation detection mirroring the Sheets design)."""

    def test_gmail_mutation_verbs_flagged_in_capability_zone(self):
        v = scan_paths([_FIXTURES / "gmail_direct_api_call.py"])
        self.assertTrue(v, "direct Gmail mutation calls must be flagged")
        kinds = _kinds(v)
        self.assertIn("direct_api_call", kinds)
        direct = [x for x in v if x.kind == "direct_api_call"]
        # trash, untrash, create(drafts), modify, send, create(filters),
        # delete(filters), trash (bound-and-called-later) -> 8 sites.
        self.assertGreaterEqual(len(direct), 8)
        for viol in direct:
            self.assertIsInstance(viol.lineno, int)
            self.assertGreater(viol.lineno, 0)

    def test_benign_non_gmail_verbs_not_flagged(self):
        # False-positive guard: create/delete/send/modify are common method
        # names. With no Gmail surface handle in the attribute chain, a
        # benign non-Gmail call must NOT be flagged.
        v = scan_paths([_FIXTURES / "gmail_benign_non_gmail_verbs.py"])
        self.assertEqual(
            v, [], "non-Gmail create/delete/send/modify must not be flagged"
        )

    def test_gmail_adapter_module_is_exempt(self):
        # The real Gmail adapter (ADAPTER_PROFILE zone, registered in
        # zones.ADAPTER_PROFILE_MODULE_PATHS) legitimately calls these same
        # verbs (messages().modify, settings().filters().create/delete) --
        # it must not be flagged. Uses the default anchor/adapter-profile
        # allowlist, exactly as a real build would.
        v = scan_paths([_ADAPTER_DIR / "adapters_gmail.py"])
        self.assertEqual(
            v, [], "the ADAPTER_PROFILE Gmail adapter must scan clean"
        )


class TestForbiddenImport(unittest.TestCase):
    def test_network_client_imports_flagged(self):
        v = scan_paths([_FIXTURES / "forbidden_import.py"])
        self.assertIn("forbidden_import", _kinds(v))
        imports = [x for x in v if x.kind == "forbidden_import"]
        # requests, urllib, googleapiclient, gspread.
        self.assertGreaterEqual(len(imports), 4)


class TestHelperIndirection(unittest.TestCase):
    def test_helper_buried_mutation_flagged(self):
        v = scan_paths([_FIXTURES / "helper_indirection.py"])
        self.assertTrue(v, "mutation hidden behind a local helper must be flagged")
        # The forbidden surface call inside the helper is itself caught.
        self.assertIn("direct_api_call", _kinds(v))


class TestDynamicImport(unittest.TestCase):
    def test_dynamic_import_flagged(self):
        v = scan_paths([_FIXTURES / "dynamic_import.py"])
        self.assertIn("dynamic_import", _kinds(v))
        dyn = [x for x in v if x.kind == "dynamic_import"]
        # importlib.import_module('requests') + __import__('urllib.request').
        self.assertGreaterEqual(len(dyn), 2)


class TestSubprocessCurl(unittest.TestCase):
    def test_subprocess_network_flagged(self):
        v = scan_paths([_FIXTURES / "subprocess_curl.py"])
        self.assertIn("subprocess_network", _kinds(v))
        net = [x for x in v if x.kind == "subprocess_network"]
        # curl via subprocess.run, curl via os.system, wget via subprocess.run.
        self.assertGreaterEqual(len(net), 3)


class TestSpoofedAnchor(unittest.TestCase):
    def test_fake_allowed_module_dir_outside_anchor_is_flagged(self):
        # A directory recreating the allowed module's NAME
        # (agents/lib/external_write) somewhere OUTSIDE the real installed
        # adapter location must NOT be exempted. Exemption is anchored to the
        # real adapter dir (scan.py's own location), not to a floating name.
        spoof = (
            _FIXTURES
            / "fake_anchor"
            / "agents"
            / "lib"
            / "external_write"
            / "sneaky.py"
        )
        v = scan_paths([spoof])
        self.assertTrue(
            v, "a spoofed look-alike adapter dir must NOT be exempted"
        )
        self.assertIn("forbidden_import", _kinds(v))

    def test_root_override_alone_does_not_exempt_an_unregistered_module(self):
        # Task 5: zone membership is EXPLICIT, never "anything under this
        # path". Overriding the anchor to the spoof tree's directory is NOT,
        # by itself, enough to exempt a file inside it — sneaky.py's relative
        # path is not listed in either the sealed-kernel or adapter-profile
        # allowlist, so it is classified CAPABILITY (fail-closed default) and
        # still flagged, even though it is now "inside" the overridden root.
        spoof_root = (
            _FIXTURES / "fake_anchor" / "agents" / "lib" / "external_write"
        )
        spoof_file = spoof_root / "sneaky.py"
        v = scan_paths([spoof_file], allowed_root=spoof_root)
        self.assertTrue(
            v,
            "a bare root override must NOT exempt a module that is not "
            "explicitly registered in a zone allowlist",
        )
        self.assertIn("forbidden_import", _kinds(v))

    def test_root_override_plus_explicit_adapter_profile_registration_exempts_it(self):
        # The explicit registration this task requires: overriding the anchor
        # AND naming the module's relative path in adapter_profile_paths is
        # what exempts it — never the directory override alone (see test
        # above). This is the reviewable, one-line-diff mechanism zones.py
        # documents in place of the old blanket exemption.
        spoof_root = (
            _FIXTURES / "fake_anchor" / "agents" / "lib" / "external_write"
        )
        spoof_file = spoof_root / "sneaky.py"
        v = scan_paths(
            [spoof_file],
            allowed_root=spoof_root,
            adapter_profile_paths=frozenset({"sneaky.py"}),
        )
        self.assertEqual(
            v, [],
            "a module explicitly registered as adapter-profile under the "
            "overridden anchor must be exempt",
        )

    def test_real_adapter_dir_is_default_anchor(self):
        # With no override, the default anchor is scan.py's own dir (the real
        # adapter dir), so real adapter code stays exempt.
        v = scan_paths([_ADAPTER_DIR])
        self.assertEqual(v, [], "real adapter code must be exempt by default")


class TestMethodReferenceBypass(unittest.TestCase):
    def test_mutation_method_referenced_not_called_is_flagged(self):
        # fn = service.spreadsheets().values().update ; fn(...)  -- the mutation
        # surface is referenced as an attribute load, not the immediate func of
        # a Call. It must still be flagged.
        v = scan_paths([_FIXTURES / "method_reference.py"])
        self.assertTrue(v, "method-reference mutation bypass must be flagged")
        self.assertIn("direct_api_call", _kinds(v))
        direct = [x for x in v if x.kind == "direct_api_call"]
        # update reference + batchUpdate reference.
        self.assertGreaterEqual(len(direct), 2)


class TestDenylistPycurl(unittest.TestCase):
    def test_pycurl_import_flagged(self):
        v = scan_paths([_FIXTURES / "forbidden_import_pycurl.py"])
        self.assertIn("forbidden_import", _kinds(v))


class TestDirectoryAggregation(unittest.TestCase):
    def test_directory_scan_aggregates_violations(self):
        v = scan_paths([_FIXTURES])
        kinds = _kinds(v)
        for expected in (
            "direct_api_call",
            "forbidden_import",
            "dynamic_import",
            "subprocess_network",
        ):
            self.assertIn(expected, kinds)
        # Legal fixtures must contribute no violations even in a dir scan.
        flagged_files = {Path(x.path).name for x in v}
        self.assertNotIn("legal_through_adapter.py", flagged_files)
        self.assertNotIn("benign_local.py", flagged_files)

    def test_violation_carries_path_lineno_kind(self):
        v = scan_paths([_FIXTURES / "direct_api_call.py"])
        first = v[0]
        self.assertIsInstance(first, Violation)
        self.assertTrue(str(first.path).endswith("direct_api_call.py"))
        self.assertIsInstance(first.lineno, int)
        self.assertIsInstance(first.kind, str)


class TestCredentialAccess(unittest.TestCase):
    """Task 5 — capability code obtaining/widening a write-capable credential
    is a violation, independent of the forbidden_import check."""

    def test_with_subject_scope_widening_flagged_with_no_forbidden_import(self):
        v = scan_paths([_FIXTURES / "credential_construction.py"])
        self.assertIn("credential_construction", _kinds(v))
        # No vendor SDK is imported in this fixture at all.
        self.assertNotIn("forbidden_import", _kinds(v))
        cred = [x for x in v if x.kind == "credential_construction"]
        # Direct call + bound-and-called-later reference -> two sites.
        self.assertGreaterEqual(len(cred), 2)

    def test_factory_and_direct_construction_flagged(self):
        v = scan_paths([_FIXTURES / "credential_construction_factory.py"])
        kinds = _kinds(v)
        self.assertIn("credential_construction", kinds)
        cred = [x for x in v if x.kind == "credential_construction"]
        # from_service_account_file, from_service_account_info,
        # bare Credentials(...), bare ServiceAccountCredentials(...).
        self.assertGreaterEqual(len(cred), 4)
        # The fixture's import is deliberately not a denylisted root, so the
        # credential check is proven independent of the import check here too.
        self.assertNotIn("forbidden_import", kinds)


class TestCredentialProviderReference(unittest.TestCase):
    """Task R1 / BL-1 — a CAPABILITY-zone import or reference of an
    adapter-profile write-credential provider symbol
    (``write_credential_provider``) is a VIOLATION. The emitted capability
    module must be UNABLE TO OBTAIN the provider, not merely "does not call
    it". The provider legitimately lives only in the ADAPTER_PROFILE zone."""

    _FIX = _FIXTURES / "capability_holds_write_credential_provider.py"

    def test_capability_holding_provider_is_flagged(self):
        v = scan_paths([self._FIX])
        self.assertIn(
            "credential_provider_reference", _kinds(v),
            "a CAPABILITY-zone module that imports/references "
            "write_credential_provider must be flagged",
        )
        refs = [x for x in v if x.kind == "credential_provider_reference"]
        # The import alias AND the by-reference pass-through are both caught.
        self.assertGreaterEqual(len(refs), 2)

    def test_provider_reference_is_exempt_in_adapter_profile_zone(self):
        # The SAME file, explicitly registered as ADAPTER_PROFILE by its
        # relative path, is exempt from every check -- the provider legitimately
        # lives in this zone.
        v = scan_paths(
            [self._FIX],
            allowed_root=self._FIX.parent,
            adapter_profile_paths=frozenset({self._FIX.name}),
        )
        self.assertEqual(
            v, [],
            "an adapter-profile module may legitimately hold the credential "
            "provider symbol",
        )


class TestBuildWriteClientReachPath(unittest.TestCase):
    """Task R1 / BL-1 residual — after the keystone fix moved credential
    provisioning onto an Adapter method, the write-capable client was STILL
    reachable from CAPABILITY-zone code via
    ``get_adapter(op_kind).build_write_client(op)``. The scanner must flag that
    ``build_write_client`` reach path as ``credential_provider_reference``, just
    as it flags the retired ``write_credential_provider`` name. The concrete
    adapter's own ``def build_write_client`` (ADAPTER_PROFILE zone) and the
    sealed-kernel execution path (which resolves the method by a STRING literal)
    must both still scan clean."""

    _CAP_FIX = _FIXTURES / "capability_reaches_build_write_client.py"
    _ADAPTER_FIX = _FIXTURES / "adapter_defines_build_write_client.py"
    _KERNEL_ADAPTERS = _ADAPTER_DIR / "adapters.py"

    def test_capability_build_write_client_reach_is_flagged(self):
        # A CAPABILITY-zone module doing get_adapter(OP_KIND).build_write_client(op)
        # must be flagged -- the attribute reference to the provisioner is the
        # bypass the residual left open.
        v = scan_paths([self._CAP_FIX])
        self.assertIn(
            "credential_provider_reference", _kinds(v),
            "a CAPABILITY-zone module that reaches the write client via "
            ".build_write_client must be flagged credential_provider_reference",
        )
        refs = [x for x in v if x.kind == "credential_provider_reference"]
        self.assertGreaterEqual(
            len(refs), 1,
            f"the .build_write_client attribute reference must be caught; got {v}",
        )

    def test_adapter_defining_build_write_client_scans_clean(self):
        # The concrete adapter's OWN method definition, in the ADAPTER_PROFILE
        # zone, must NOT be flagged -- defining the provisioner is legal exactly
        # where it should live.
        v = scan_paths(
            [self._ADAPTER_FIX],
            allowed_root=self._ADAPTER_FIX.parent,
            adapter_profile_paths=frozenset({self._ADAPTER_FIX.name}),
        )
        self.assertEqual(
            v, [],
            "an ADAPTER_PROFILE adapter that DEFINES build_write_client must "
            f"scan clean; got {v}",
        )

    def test_sealed_kernel_adapters_module_scans_clean(self):
        # The real SEALED_KERNEL adapters.py resolves the adapter method by a
        # STRING literal (getattr(adapter, "build_write_client", None)) and names
        # its local `_provision`, NOT `build_write_client` -- so the sealed
        # kernel (which is NOT exempt from the provider-reference rule) does not
        # self-trip. Regression guard for the rename.
        v = scan_paths([self._KERNEL_ADAPTERS], allowed_root=_ADAPTER_DIR)
        self.assertNotIn(
            "credential_provider_reference", _kinds(v),
            "the sealed-kernel adapters.py must not self-trip the "
            f"credential_provider_reference rule; got {v}",
        )


class TestTrustZoneSplit(unittest.TestCase):
    """Task 5 — the trust boundary is split into SEALED_KERNEL /
    ADAPTER_PROFILE / CAPABILITY zones; the old "whole external_write/ tree is
    exempt" rule is replaced by explicit, relative-path zone membership."""

    _KERNEL_ROOT = _FIXTURES / "zones" / "kernel_root"

    def test_sealed_kernel_zone_is_not_a_blanket_exemption(self):
        # "adapters.py" is a real SEALED_KERNEL_MODULE_PATHS entry, but that
        # zone is held to the same checks as capability code -- it must not
        # get a free pass merely by matching the kernel's module name.
        v = scan_paths(
            [self._KERNEL_ROOT / "adapters.py"], allowed_root=self._KERNEL_ROOT
        )
        self.assertTrue(v, "sealed-kernel zone must not be blanket-exempt")
        self.assertIn("forbidden_import", _kinds(v))

    def test_unregistered_module_under_kernel_root_is_capability_fail_closed(self):
        # vendor_adapter.py physically lives under the (overridden) kernel
        # anchor but is not listed in either zone allowlist -- classified
        # CAPABILITY, the fail-closed default, and fully flagged.
        v = scan_paths(
            [self._KERNEL_ROOT / "vendor_adapter.py"],
            allowed_root=self._KERNEL_ROOT,
        )
        self.assertTrue(
            v, "an unregistered module under the anchor must fail closed as "
            "CAPABILITY, not be silently exempted by location"
        )
        kinds = _kinds(v)
        self.assertIn("forbidden_import", kinds)
        self.assertIn("credential_construction", kinds)
        self.assertIn("direct_api_call", kinds)

    def test_explicit_adapter_profile_registration_exempts_conformant_module(self):
        # The SAME file, now explicitly registered as ADAPTER_PROFILE by its
        # relative path -- the reviewable, one-line mechanism this task
        # requires in place of a directory rule. A conformant adapter-profile
        # module doing legitimate vendor import + credential construction +
        # raw mutation passes cleanly.
        v = scan_paths(
            [self._KERNEL_ROOT / "vendor_adapter.py"],
            allowed_root=self._KERNEL_ROOT,
            adapter_profile_paths=frozenset({"vendor_adapter.py"}),
        )
        self.assertEqual(
            v, [],
            "an explicitly-registered adapter-profile module must be exempt",
        )


class TestAdapterRegistryCapabilityBan(unittest.TestCase):
    """Task R7-T4 — CAPABILITY-zone code must be STATICALLY unable to reach
    the adapter registry or an adapter-PROFILE module (sealing the
    architecture Tasks R7-T1..T3 built: it can neither monkey-patch the
    registered adapter nor string-reach build_write_client, because it
    cannot even NAME get_adapter/the profile modules). These two new rules
    are CAPABILITY-zone-ONLY — see TestAdapterRegistryKernelStaysClean below
    for the SEALED_KERNEL/ADAPTER_PROFILE exemption."""

    def test_capability_importing_adapter_registry_module_is_flagged(self):
        v = scan_paths([_FIXTURES / "capability_adapter_registry_import.py"])
        kinds = _kinds(v)
        self.assertIn("adapter_module_import", kinds)
        self.assertIn("adapter_registry_reference", kinds)

    def test_capability_reexported_get_adapter_name_is_flagged(self):
        # from external_write.adapters import get_adapter -- the MODULE is
        # the allowed bare kernel dispatch module, but naming get_adapter at
        # all is itself the bypass.
        v = scan_paths(
            [_FIXTURES / "capability_adapters_reexport_get_adapter.py"]
        )
        kinds = _kinds(v)
        self.assertIn("adapter_registry_reference", kinds)
        self.assertNotIn(
            "adapter_module_import", kinds,
            "the bare external_write.adapters module import itself is legal",
        )

    def test_capability_importing_adapter_profile_module_is_flagged(self):
        v = scan_paths(
            [_FIXTURES / "capability_adapters_profile_module_import.py"]
        )
        self.assertIn("adapter_module_import", _kinds(v))

    def test_monkeypatch_class_dict_exploit_shape_is_flagged(self):
        # The get_adapter reference is what closes this fixture -- the
        # __class__.__dict__["build_write_client"] chain is a disclosed,
        # not-closed residual (a Constant-node string key), but there is no
        # adapter instance to reach into without get_adapter first.
        v = scan_paths(
            [_FIXTURES / "capability_monkeypatch_class_dict_exploit.py"]
        )
        self.assertIn("adapter_registry_reference", _kinds(v))

    def test_introspection_dynamic_reach_is_flagged(self):
        v = scan_paths([_FIXTURES / "capability_introspection_dynamic_reach.py"])
        kinds = _kinds(v)
        self.assertIn("introspection_escape_hatch", kinds)
        hatches = [x for x in v if x.kind == "introspection_escape_hatch"]
        # import importlib, sys.modules[...], importlib.import_module(...).
        self.assertGreaterEqual(len(hatches), 3)


class TestAdapterRegistryNegativeGuards(unittest.TestCase):
    """False-positive discipline (Task R7-T4): the curated capability-facing
    surfaces and ordinary introspection idioms must stay clean."""

    def test_bare_kernel_adapters_module_run_operation_not_flagged(self):
        v = scan_paths(
            [_FIXTURES / "capability_bare_adapters_run_operation_allowed.py"]
        )
        self.assertEqual(v, [])

    def test_capability_api_reexport_not_flagged(self):
        v = scan_paths([_FIXTURES / "capability_api_reexport_allowed.py"])
        self.assertEqual(v, [])

    def test_emitted_read_facades_shape_not_flagged(self):
        v = scan_paths(
            [_FIXTURES / "capability_read_facade_emitted_shape_allowed.py"]
        )
        self.assertEqual(v, [])

    def test_ordinary_class_introspection_not_flagged(self):
        v = scan_paths(
            [_FIXTURES / "capability_ordinary_introspection_allowed.py"]
        )
        self.assertEqual(v, [])


class TestAdapterRegistryKernelStaysClean(unittest.TestCase):
    """The zone-scoping requirement (Task R7-T4): adapter_module_import /
    adapter_registry_reference / introspection_escape_hatch must NOT fire in
    SEALED_KERNEL (adapters.py / effects_manifest.py legitimately import and
    call get_dispatch / get_adapter; read_facade.py legitimately calls
    vars(cls)) or ADAPTER_PROFILE (adapters_gmail.py legitimately calls
    register_adapter; already exempt before the scanner runs at all)."""

    def test_adapters_module_scans_clean(self):
        v = scan_paths([_ADAPTER_DIR / "adapters.py"])
        self.assertEqual(
            v, [],
            "SEALED_KERNEL adapters.py legitimately imports/calls "
            f"get_dispatch; must not self-trip the new CAPABILITY-only "
            f"rules; got {v}",
        )

    def test_effects_manifest_module_scans_clean(self):
        v = scan_paths([_ADAPTER_DIR / "effects_manifest.py"])
        self.assertEqual(
            v, [],
            "SEALED_KERNEL effects_manifest.py legitimately imports/calls "
            f"get_adapter; must not self-trip the new CAPABILITY-only "
            f"rules; got {v}",
        )

    def test_read_facade_module_scans_clean(self):
        # read_facade.py's __init_subclass__ legitimately calls vars(cls) --
        # must not self-trip the new introspection_escape_hatch rule.
        v = scan_paths([_ADAPTER_DIR / "read_facade.py"])
        self.assertEqual(v, [])

    def test_write_gate_module_scans_clean(self):
        v = scan_paths([_ADAPTER_DIR / "write_gate.py"])
        self.assertEqual(v, [])

    def test_adapters_gmail_module_still_scans_clean(self):
        # ADAPTER_PROFILE zone's own register_adapter call — exempt before
        # the scanner runs at all (unaffected by this task, regression guard).
        v = scan_paths([_ADAPTER_DIR / "adapters_gmail.py"])
        self.assertEqual(v, [])

    def test_capability_api_module_scans_clean(self):
        # capability_api.py is UNLISTED in either zone allowlist (fail-closed
        # CAPABILITY default), yet imports nothing but run_operation (from the
        # bare adapters module) and build_read_facade (from read_facade) --
        # neither a banned module nor a banned symbol.
        v = scan_paths([_ADAPTER_DIR / "capability_api.py"])
        self.assertEqual(v, [])

    def test_read_facades_gmail_module_scans_clean(self):
        # Also fail-closed CAPABILITY (unlisted), and also clean on its own
        # merits: imports only ReadFacade + register_read_facade.
        v = scan_paths([_ADAPTER_DIR / "read_facades_gmail.py"])
        self.assertEqual(v, [])

    def test_whole_adapter_dir_still_scans_clean(self):
        # Full-directory regression guard: every file in the real package,
        # scanned together under the default zone allowlists, stays clean.
        v = scan_paths([_ADAPTER_DIR])
        self.assertEqual(v, [], f"real kernel/adapter-profile code must stay "
                                f"clean under the new capability-only rules; got {v}")


if __name__ == "__main__":
    unittest.main()
