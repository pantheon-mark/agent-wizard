"""Tests for the emitted capability health-check module
(external_write.capability_health — F-55 C).

This is the deterministic, composite per-capability health signal an agent's
session-start orientation (T5) reads BEFORE inviting the operator into a
capability, so it can refuse to invite the operator into one that is broken
(import-broken or scanner-red) or paused/pending-migration — the remedy for
the estate finding that inviting the operator into an import-broken
capability was never caught by anything deterministic.

AST-FIRST, IMPORT-SECOND is the safety property under direct test: a
scanner-red capability (one referencing the raw kernel write primitive,
``run_operation``) must NEVER be imported by this checker, even though
importing it might otherwise "work" -- proven here by having the red fixture
write a side-effect marker file at module scope and asserting it is never
created.

ANTI-OVERFIT (v0.13.0 T7 lesson): every fixture in this file is written at
the REAL emitted relative path (``agents/capabilities/<id>_capability.py``)
inside a fresh temp project tree -- never a ``copytree`` of the dev tree,
which previously masked a real-emit-path bug. At least two distinct
capability_ids are exercised at that real path (see
``test_multiple_capabilities_enumerated_at_real_relpath``).

Uses stub/synthetic capability source only; no network, no real vendor SDK.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (canonical
# location) -- mirrors test_external_write_write_gate.py's own convention.
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import capability_health  # noqa: E402
from external_write import write_gate  # noqa: E402

# Build-side owners of the four values capability_health.py duplicates by
# value (see TestPathConstantsAntiDrift below) -- both importable here
# because this test file, run from wizard/scripts/lib, can see both the
# agents/lib/external_write tree (inserted above) and the scripts/lib tree
# (its own directory, already on sys.path under ``python3 -m unittest``).
import capability_code_scaffold  # noqa: E402
import upgrade_reconcile  # noqa: E402


CAPABILITIES_DIR_REL = capability_health.CAPABILITIES_DIR_REL
DESCRIPTOR_SET_REL = capability_health.DESCRIPTOR_SET_REL
PAUSED_MECHANISMS_DIR_REL = capability_health.PAUSED_MECHANISMS_DIR_REL
MIGRATION_QUEUE_REL = capability_health.MIGRATION_QUEUE_REL

_CLEAN_CAPABILITY_SOURCE = '''"""{display_name} -- trivial, gate-clean capability module (test fixture)."""

from typing import Any


def describe() -> str:
    return "{display_name} ready"


def propose_operations(facade: Any, batch_id: str):
    return []
'''

_RETIRED_SURFACE_SOURCE = '''"""{display_name} -- retired-surface capability (test fixture).

References the raw kernel write primitive directly -- the shape
external_write.scan's raw_run_operation_reference rule exists to catch. Also
writes a side-effect marker file at MODULE SCOPE so a test can prove this
module was never actually imported/executed by the health checker.
"""

from pathlib import Path

Path(r"{marker_path}").write_text("imported", encoding="utf-8")

from external_write.adapters import run_operation


def run():
    return run_operation
'''

_BROKEN_IMPORT_SOURCE = '''"""{display_name} -- static-clean but raises on import (test fixture)."""

raise ImportError("simulated broken dependency for {display_name}")
'''


class CapabilityHealthTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _capabilities_dir(self) -> Path:
        d = self.project_root / CAPABILITIES_DIR_REL
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_capability(self, capability_id: str, source: str) -> Path:
        path = self._capabilities_dir() / f"{capability_id}_capability.py"
        path.write_text(source, encoding="utf-8")
        return path

    def _write_descriptor_set(self, entries):
        path = self.project_root / DESCRIPTOR_SET_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries), encoding="utf-8")

    def _write_pause_marker(self, capability_id: str):
        d = self.project_root / PAUSED_MECHANISMS_DIR_REL
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{capability_id}.pause").write_text("", encoding="utf-8")

    def _write_pending_migration(self, capability_id: str):
        path = self.project_root / MIGRATION_QUEUE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([{"mechanism_id": capability_id, "reason": "test fixture"}]),
            encoding="utf-8",
        )

    def _record_for(self, records, capability_id):
        matches = [r for r in records if r["capability_id"] == capability_id]
        self.assertEqual(
            len(matches), 1,
            f"expected exactly one record for {capability_id!r}, got {matches!r}",
        )
        return matches[0]


class TestCleanCapabilityGreen(CapabilityHealthTestBase):
    def test_clean_capability_green(self):
        self._write_capability(
            "clean_cap", _CLEAN_CAPABILITY_SOURCE.format(display_name="Clean Cap"))

        records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "clean_cap")

        self.assertTrue(record["importable"])
        self.assertTrue(record["scanner_clean"])
        self.assertEqual(record["violations"], [])
        self.assertFalse(record["paused"])
        self.assertFalse(record["pending_migration"])
        self.assertEqual(record["health"], "green")


class TestScannerRedNotImported(CapabilityHealthTestBase):
    def test_scanner_red_capability_is_red_and_not_imported(self):
        marker_path = self.project_root / "side_effect_marker.txt"
        self._write_capability(
            "retired_cap",
            _RETIRED_SURFACE_SOURCE.format(
                display_name="Retired Cap", marker_path=str(marker_path)),
        )

        records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "retired_cap")

        self.assertEqual(record["health"], "red")
        self.assertFalse(record["scanner_clean"])
        self.assertFalse(record["importable"])
        self.assertTrue(
            any(v.startswith("raw_run_operation_reference:") for v in record["violations"]),
            f"expected a raw_run_operation_reference violation, got {record['violations']!r}",
        )
        # The decisive assertion: a scanner-red module must NEVER be
        # imported, so its module-scope side effect must never have run.
        self.assertFalse(
            marker_path.exists(),
            "checker imported a scanner-red capability module (side-effect marker was written)",
        )


class TestBrokenImportDoesNotCrash(CapabilityHealthTestBase):
    def test_broken_import_does_not_crash_checker(self):
        self._write_capability(
            "broken_cap",
            _BROKEN_IMPORT_SOURCE.format(display_name="Broken Cap"),
        )

        # Must not raise.
        records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "broken_cap")

        self.assertTrue(record["scanner_clean"])
        self.assertEqual(record["violations"], [])
        self.assertFalse(record["importable"])
        self.assertEqual(record["health"], "red")


class TestPausedCapabilityRed(CapabilityHealthTestBase):
    def test_paused_capability_is_red(self):
        self._write_capability(
            "paused_cap", _CLEAN_CAPABILITY_SOURCE.format(display_name="Paused Cap"))
        self._write_pause_marker("paused_cap")

        records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "paused_cap")

        # Otherwise-healthy on every OTHER axis -- paused alone must flip it red.
        self.assertTrue(record["importable"])
        self.assertTrue(record["scanner_clean"])
        self.assertTrue(record["paused"])
        self.assertFalse(record["pending_migration"])
        self.assertEqual(record["health"], "red")


class TestPendingMigrationCapabilityRed(CapabilityHealthTestBase):
    def test_pending_migration_capability_is_red(self):
        self._write_capability(
            "pending_cap", _CLEAN_CAPABILITY_SOURCE.format(display_name="Pending Cap"))
        self._write_pending_migration("pending_cap")

        records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "pending_cap")

        self.assertTrue(record["importable"])
        self.assertTrue(record["scanner_clean"])
        self.assertFalse(record["paused"])
        self.assertTrue(record["pending_migration"])
        self.assertEqual(record["health"], "red")


class TestDescriptorOnlyCapabilityWithNoSourceFile(CapabilityHealthTestBase):
    def test_descriptor_only_capability_with_no_source_file_is_red_not_crashed(self):
        # Declared in the descriptor set but never written to disk -- e.g.
        # removed after being declared, or declared ahead of code landing.
        self._write_descriptor_set([{"id": "ghost_cap", "name": "ghost_cap"}])

        records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "ghost_cap")

        self.assertFalse(record["importable"])
        self.assertFalse(record["scanner_clean"])
        self.assertEqual(record["health"], "red")


class TestMultipleCapabilitiesEnumeratedAtRealRelpath(CapabilityHealthTestBase):
    def test_multiple_capabilities_enumerated_at_real_relpath(self):
        # ANTI-OVERFIT: >=2 distinct capability_ids, both written at the REAL
        # emitted relative path inside a fresh tree built from scratch (never
        # a copytree of the dev tree -- see the v0.13.0 T7 lesson cited in
        # this module's docstring).
        self._write_capability(
            "alpha_cap", _CLEAN_CAPABILITY_SOURCE.format(display_name="Alpha Cap"))
        self._write_capability(
            "bravo_cap", _CLEAN_CAPABILITY_SOURCE.format(display_name="Bravo Cap"))

        records = capability_health.check_capabilities(self.project_root)
        ids = {r["capability_id"] for r in records}
        self.assertIn("alpha_cap", ids)
        self.assertIn("bravo_cap", ids)

        alpha = self._record_for(records, "alpha_cap")
        bravo = self._record_for(records, "bravo_cap")
        for rec in (alpha, bravo):
            self.assertEqual(rec["health"], "green")
            self.assertTrue(rec["importable"])
            self.assertTrue(rec["scanner_clean"])

        # Verify the source really did land at the real emitted relpath (not
        # some other fixture layout this test could have accidentally used).
        self.assertTrue(
            (self.project_root / CAPABILITIES_DIR_REL / "alpha_cap_capability.py").is_file())
        self.assertTrue(
            (self.project_root / CAPABILITIES_DIR_REL / "bravo_cap_capability.py").is_file())


class TestEmptyProjectYieldsNoRecords(CapabilityHealthTestBase):
    def test_empty_project_yields_empty_list_no_crash(self):
        records = capability_health.check_capabilities(self.project_root)
        self.assertEqual(records, [])


class TestPathConstantsAntiDrift(unittest.TestCase):
    """BUILD<->RUNTIME value contract (FINAL-review Fix 1). capability_health.py
    is emitted runtime code and cannot import its four canonical owners
    across the build/runtime boundary, so each of its four path constants is
    duplicated BY VALUE from its owner instead. Nothing previously pinned
    those duplicates to their owners, so a real drift (the owner's value
    changing without this module's copy changing too) would go undetected
    until an operator hit it live. These four tests are that pin -- this
    test file, run from wizard/scripts/lib, can import all four owners,
    mirroring test_external_write_write_gate.py's own
    TestPausedMechanismsDirAntiDrift::test_matches_upgrade_reconcile_constant_by_value
    pattern for write_gate.PAUSED_MECHANISMS_DIR."""

    def test_capabilities_dir_rel_matches_capability_code_scaffold(self):
        self.assertEqual(
            capability_health.CAPABILITIES_DIR_REL,
            capability_code_scaffold.DEFAULT_CAPABILITIES_REL.as_posix(),
        )

    def test_descriptor_set_rel_matches_write_gate_descriptor_set_path(self):
        self.assertEqual(
            capability_health.DESCRIPTOR_SET_REL,
            write_gate.DESCRIPTOR_SET_PATH,
        )

    def test_paused_mechanisms_dir_rel_matches_write_gate_paused_mechanisms_dir(self):
        self.assertEqual(
            capability_health.PAUSED_MECHANISMS_DIR_REL,
            write_gate.PAUSED_MECHANISMS_DIR,
        )

    def test_migration_queue_rel_matches_upgrade_reconcile_constant(self):
        self.assertEqual(
            capability_health.MIGRATION_QUEUE_REL,
            upgrade_reconcile.MIGRATION_QUEUE_REL,
        )


if __name__ == "__main__":
    unittest.main()
