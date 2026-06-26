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

    def test_explicit_allowed_root_override_exempts_only_that_tree(self):
        # Caller can override the anchor. Passing the spoof tree's adapter dir as
        # the explicit allowed_root exempts it; the real adapter dir is then NOT
        # the anchor, but a file under the override IS exempt.
        spoof_root = (
            _FIXTURES / "fake_anchor" / "agents" / "lib" / "external_write"
        )
        spoof_file = spoof_root / "sneaky.py"
        v = scan_paths([spoof_file], allowed_root=spoof_root)
        self.assertEqual(
            v, [], "file under the explicit allowed_root must be exempt"
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


if __name__ == "__main__":
    unittest.main()
