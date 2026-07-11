"""Tests for the Task 10 (external-write-gate-generalization) extension to
zones.py: a capability added AFTER the initial build (via add-capability's
gate-wired-by-construction scaffold emitter) registers its adapter module in
the ADAPTER_PROFILE trust zone by writing a sibling JSON registry file,
rather than by hand-editing zones.py's ADAPTER_PROFILE_MODULE_PATHS literal.

Covers:
  * _load_extra_adapter_profile_paths is fail-closed on every malformed shape
    (missing file, unreadable, not JSON, not a list, non-string entries).
  * effective_adapter_profile_paths unions the hardcoded base set with the
    registry file's contents, parameterized by an arbitrary lib_dir (so a
    test can point it at a temp project without touching the real installed
    package's own registry).
  * The real module-level ADAPTER_PROFILE_MODULE_PATHS constant (computed at
    import time, anchored to zones.py's OWN installed directory) is
    unaffected when no registry file exists there — no behavior change for
    the base case (adapters_gmail.py only).
"""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import zones  # noqa: E402
from external_write.zones import (  # noqa: E402
    ADAPTER_PROFILE_MODULE_PATHS,
    _BASE_ADAPTER_PROFILE_MODULE_PATHS,
    _ADAPTER_PROFILE_REGISTRY_FILENAME,
    _load_extra_adapter_profile_paths,
    effective_adapter_profile_paths,
)


class TestBaseConstantUnaffectedByDefault(unittest.TestCase):
    def test_module_level_constant_is_base_set_when_no_registry_present(self):
        # zones.py's own installed directory carries no adapter_profile_registry.json
        # in this repo -- the real module-level constant must equal the hardcoded
        # base set exactly, same as before this task (no behavior change).
        self.assertEqual(ADAPTER_PROFILE_MODULE_PATHS, _BASE_ADAPTER_PROFILE_MODULE_PATHS)
        self.assertIn("adapters_gmail.py", ADAPTER_PROFILE_MODULE_PATHS)


class TestLoadExtraAdapterProfilePathsFailClosed(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.lib_dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _registry_path(self):
        return self.lib_dir / _ADAPTER_PROFILE_REGISTRY_FILENAME

    def test_missing_file_yields_empty_set(self):
        self.assertEqual(_load_extra_adapter_profile_paths(self.lib_dir), frozenset())

    def test_valid_list_is_loaded(self):
        self._registry_path().write_text(json.dumps(["adapters_acme.py"]), encoding="utf-8")
        self.assertEqual(_load_extra_adapter_profile_paths(self.lib_dir),
                         frozenset({"adapters_acme.py"}))

    def test_multiple_entries_all_loaded(self):
        self._registry_path().write_text(
            json.dumps(["adapters_a.py", "adapters_b.py"]), encoding="utf-8")
        self.assertEqual(_load_extra_adapter_profile_paths(self.lib_dir),
                         frozenset({"adapters_a.py", "adapters_b.py"}))

    def test_not_valid_json_yields_empty_set(self):
        self._registry_path().write_text("{not json", encoding="utf-8")
        self.assertEqual(_load_extra_adapter_profile_paths(self.lib_dir), frozenset())

    def test_non_list_json_yields_empty_set(self):
        self._registry_path().write_text(json.dumps({"a": "adapters_acme.py"}),
                                         encoding="utf-8")
        self.assertEqual(_load_extra_adapter_profile_paths(self.lib_dir), frozenset())

    def test_non_string_entries_are_skipped_not_fatal(self):
        self._registry_path().write_text(
            json.dumps(["adapters_acme.py", 42, None, ""]), encoding="utf-8")
        self.assertEqual(_load_extra_adapter_profile_paths(self.lib_dir),
                         frozenset({"adapters_acme.py"}))

    def test_empty_list_yields_empty_set(self):
        self._registry_path().write_text(json.dumps([]), encoding="utf-8")
        self.assertEqual(_load_extra_adapter_profile_paths(self.lib_dir), frozenset())


class TestEffectiveAdapterProfilePaths(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.lib_dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_unions_base_set_with_registry_contents(self):
        (self.lib_dir / _ADAPTER_PROFILE_REGISTRY_FILENAME).write_text(
            json.dumps(["adapters_acme.py"]), encoding="utf-8")
        result = effective_adapter_profile_paths(self.lib_dir)
        self.assertEqual(result, frozenset({"adapters_gmail.py", "adapters_acme.py"}))

    def test_no_registry_file_yields_just_base_set(self):
        result = effective_adapter_profile_paths(self.lib_dir)
        self.assertEqual(result, _BASE_ADAPTER_PROFILE_MODULE_PATHS)

    def test_defaults_to_this_modules_own_installed_directory(self):
        # No-arg call must match the module-level constant exactly (same anchor).
        self.assertEqual(effective_adapter_profile_paths(), ADAPTER_PROFILE_MODULE_PATHS)


if __name__ == "__main__":
    unittest.main()
