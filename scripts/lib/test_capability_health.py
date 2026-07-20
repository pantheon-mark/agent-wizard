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

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Single-home: import from wizard/agents/lib/external_write (canonical
# location) -- mirrors test_external_write_write_gate.py's own convention.
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import capability_health  # noqa: E402
from external_write import write_gate  # noqa: E402
from external_write import lifecycle_state  # noqa: E402

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
LEDGER_DIR_REL = capability_health.LEDGER_DIR_REL

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

_SPLIT_IDENTITY_CAPABILITY_SOURCE = '''"""{display_name} -- gate-clean capability whose descriptor id
differs from its module stem (F-61 estate-split fixture)."""

from typing import Any

SURFACE = "{surface}"


def describe() -> str:
    return "{display_name} ready"


def propose_operations(facade: Any, batch_id: str):
    return []
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


class TestAcceptanceStaleCapabilityRed(CapabilityHealthTestBase):
    """(Task B2b-fix, Critical 2) health surfaces -- READ-ONLY -- a capability whose acceptance
    has gone stale (its code changed since it was approved), the same way it already surfaces
    paused/pending-migration. capability_health NEVER itself forces accepted:false -- it only
    reports the SAME verdict lifecycle_state.acceptance_hash_is_stale already computes."""

    def _accept(self, capability_id, phase_id="phase-1"):
        cap_path = self.project_root / CAPABILITIES_DIR_REL / f"{capability_id}_capability.py"
        module_hash = hashlib.sha256(cap_path.read_bytes()).hexdigest()
        from external_write.acceptance_ceremony import ACCEPTANCE_RECORD_SCHEMA
        from external_write.proof_hash import compute_implementation_hash

        log_path = self.project_root / "security" / "capability_acceptance_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": ACCEPTANCE_RECORD_SCHEMA, "capability_id": capability_id,
            "phase_id": phase_id, "risk_class": "irreversible_external",
            "op_kind": "delete_record", "copy_run_proof_ref": "proof.json",
            "operator_receipt_ref": "receipt.json", "contract_hash": "0" * 64,
            "implementation_hash": compute_implementation_hash("delete_record"),
            "capability_module_hash": module_hash,
            "operator_confirmation": "Yes, accept this capability for live use.",
            "receipt_accepted_at": "2026-01-01T00:00:00Z",
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def test_accepted_capability_with_current_hash_stays_green(self):
        self._write_capability(
            "accepted_cap", _CLEAN_CAPABILITY_SOURCE.format(display_name="Accepted Cap"))
        self._write_descriptor_set(
            [{"id": "accepted_cap", "accepted": True, "phase_id": "phase-1"}])
        self._accept("accepted_cap")

        records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "accepted_cap")
        self.assertFalse(record["acceptance_stale"])
        self.assertEqual(record["health"], "green")

    def test_accepted_capability_edited_since_approval_is_red(self):
        cap_path = self._write_capability(
            "accepted_cap", _CLEAN_CAPABILITY_SOURCE.format(display_name="Accepted Cap"))
        self._write_descriptor_set(
            [{"id": "accepted_cap", "accepted": True, "phase_id": "phase-1"}])
        self._accept("accepted_cap")

        # Rebuild: edit the capability's own code AFTER it was approved. Adapter/call shape and
        # scanner-cleanliness are both untouched -- only capability_module_hash catches this.
        cap_path.write_text(
            _CLEAN_CAPABILITY_SOURCE.format(display_name="Accepted Cap Rebuilt"),
            encoding="utf-8")

        records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "accepted_cap")

        # Otherwise-healthy on every OTHER axis -- acceptance staleness alone must flip it red.
        self.assertTrue(record["importable"])
        self.assertTrue(record["scanner_clean"])
        self.assertFalse(record["paused"])
        self.assertFalse(record["pending_migration"])
        self.assertTrue(record["acceptance_stale"])
        self.assertEqual(record["health"], "red")

    def test_health_check_never_writes_the_descriptor_set(self):
        # READ-ONLY, decisively: health never itself forces accepted:false.
        cap_path = self._write_capability(
            "accepted_cap", _CLEAN_CAPABILITY_SOURCE.format(display_name="Accepted Cap"))
        self._write_descriptor_set(
            [{"id": "accepted_cap", "accepted": True, "phase_id": "phase-1"}])
        self._accept("accepted_cap")
        cap_path.write_text(
            _CLEAN_CAPABILITY_SOURCE.format(display_name="Accepted Cap Rebuilt"),
            encoding="utf-8")

        before = (self.project_root / DESCRIPTOR_SET_REL).read_bytes()
        capability_health.check_capabilities(self.project_root)
        after = (self.project_root / DESCRIPTOR_SET_REL).read_bytes()
        self.assertEqual(before, after, "capability_health must never write the descriptor set")


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


class TestDescriptorAliasResolvesToOwningModuleGreen(CapabilityHealthTestBase):
    """F-61 (Task A3) -- the estate split: a descriptor id ("inbox-labels")
    differs from its module stem ("inbox_management"). Before this fix, the
    same-named-file check found no ``inbox-labels_capability.py`` on disk and
    reported the capability RED, even though the module for it is healthy and
    importable under its own (different) name. The health check must resolve
    the descriptor row to its OWNING module via the identity index (surface-
    corroborated: the module's own declared SURFACE equals the descriptor id)
    before that check, and report GREEN."""

    def test_split_identity_capability_reports_green_not_false_red(self):
        self._write_capability(
            "inbox_management",
            _SPLIT_IDENTITY_CAPABILITY_SOURCE.format(
                display_name="Inbox Management", surface="inbox-labels"),
        )
        self._write_descriptor_set([{"id": "inbox-labels", "name": "inbox-labels"}])

        records = capability_health.check_capabilities(self.project_root)

        record = self._record_for(records, "inbox_management")
        self.assertEqual(record["health"], "green")
        self.assertTrue(record["importable"])
        self.assertTrue(record["scanner_clean"])
        self.assertFalse(record["paused"])
        self.assertFalse(record["pending_migration"])

        # The alias id must be resolved away, not ALSO reported as a separate
        # (false-red) row for the same underlying capability.
        self.assertNotIn("inbox-labels", {r["capability_id"] for r in records})


class TestUncorroboratedOrphanDescriptorNotMasked(CapabilityHealthTestBase):
    """CRITICAL regression (coordinator review round 2): the same-cardinality guess that used
    to live in ``capability_identity._build_name_alias_map`` (resolve an unmatched id to the
    sole capability purely because it's the only one around) meant a genuinely-unrelated, stale
    descriptor entry with ZERO corroboration (not the module's own stem, not a declared
    SURFACE) was silently swallowed into the one real capability's row and VANISHED from the
    report entirely -- a real broken/orphaned descriptor entry masked as if it did not exist,
    the opposite of this module's whole purpose. Re-attribution must require CORROBORATED
    resolution only; an uncorroborated orphan must stay its OWN row and get the normal
    no-source-file -> RED treatment, never be folded away."""

    def test_uncorroborated_orphan_descriptor_stays_its_own_red_row(self):
        # Exactly ONE real capability + exactly ONE uncorroborated descriptor entry (the
        # precise cardinality shape the removed guess fired on: "only one capability exists,
        # so this stray must mean that one"). No OTHER descriptor entry is needed for
        # inbox_management itself to resolve GREEN -- it already has its own source file
        # directly on disk (see the union enumeration in the module docstring); this fixture
        # isolates the guess so a 2-unmatched-id fixture (already covered by an earlier,
        # narrower fix) can't accidentally mask this regression.
        self._write_capability(
            "inbox_management",
            _SPLIT_IDENTITY_CAPABILITY_SOURCE.format(
                display_name="Inbox Management", surface="inbox-labels"),
        )
        self._write_descriptor_set([
            {"id": "totally_unrelated_orphan", "name": "orphan"},    # zero corroboration
        ])

        records = capability_health.check_capabilities(self.project_root)
        ids = {r["capability_id"] for r in records}

        # The orphan must NOT vanish -- it must be its own row, reported RED.
        self.assertIn("totally_unrelated_orphan", ids)
        orphan = self._record_for(records, "totally_unrelated_orphan")
        self.assertEqual(orphan["health"], "red")
        self.assertFalse(orphan["importable"])
        self.assertFalse(orphan["scanner_clean"])

        # The genuinely-linked split capability must still resolve and report GREEN.
        healthy = self._record_for(records, "inbox_management")
        self.assertEqual(healthy["health"], "green")


class TestUnreadablePauseMarkerFailsClosedRed(CapabilityHealthTestBase):
    def test_unreadable_pause_marker_is_red_not_green(self):
        # (xvendor Fix B) An otherwise-clean+importable capability whose
        # pause-marker file EXISTS but cannot be stat'd (e.g.
        # permission-denied) must be RED, not GREEN -- the prior
        # Path.is_file()-based check swallowed the OSError into a bare
        # False ("not paused"), a fail-OPEN hole this closes.
        self._write_capability(
            "clean_cap", _CLEAN_CAPABILITY_SOURCE.format(display_name="Clean Cap"))
        marker_dir = self.project_root / PAUSED_MECHANISMS_DIR_REL
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker_path = marker_dir / "clean_cap.pause"
        marker_path.write_text("", encoding="utf-8")

        real_stat = capability_health.os.stat

        def _raising_stat(path, *a, **kw):
            if str(path) == str(marker_path):
                raise PermissionError("permission denied")
            return real_stat(path, *a, **kw)

        with mock.patch.object(capability_health.os, "stat", side_effect=_raising_stat):
            records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "clean_cap")

        self.assertTrue(record["importable"])
        self.assertTrue(record["scanner_clean"])
        self.assertFalse(record["paused"])
        self.assertTrue(record.get("state_read_error"))
        self.assertEqual(record["health"], "red")


class TestPauseMarkerAsDirectoryIsRedNotGreen(CapabilityHealthTestBase):
    def test_pause_marker_as_directory_is_paused_red(self):
        # (xvendor round-2, R2-3) A `.pause` marker existing as a DIRECTORY
        # (the wrong shape -- this module's own writer never creates it that
        # way) must still count as paused: the entrypoint wrapper this marker
        # gates checks for it with a plain shell `[ -e ... ]` test, which
        # pauses on ANY existing path regardless of shape. The prior
        # `stat.S_ISREG`-only check silently read this as "not paused" -- a
        # false green for a capability the wrapper itself would refuse to run.
        self._write_capability(
            "dirpause_cap", _CLEAN_CAPABILITY_SOURCE.format(display_name="Dirpause Cap"))
        marker_dir = self.project_root / PAUSED_MECHANISMS_DIR_REL
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "dirpause_cap.pause").mkdir()

        records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "dirpause_cap")

        # Otherwise-healthy on every other axis -- the directory-shaped
        # `.pause` marker alone must flip it red.
        self.assertTrue(record["importable"])
        self.assertTrue(record["scanner_clean"])
        self.assertTrue(record["paused"])
        self.assertEqual(record["health"], "red")


class TestUnreadableMigrationQueueFailsClosedRed(CapabilityHealthTestBase):
    def test_unreadable_migration_queue_is_red_not_green(self):
        # (xvendor Fix B) An otherwise-clean+importable capability whose
        # pending_migrations.json EXISTS but cannot be read must be RED, not
        # GREEN -- the prior implementation folded any read/parse error into
        # a bare False ("no pending migration").
        self._write_capability(
            "clean_cap2", _CLEAN_CAPABILITY_SOURCE.format(display_name="Clean Cap 2"))
        queue_path = self.project_root / MIGRATION_QUEUE_REL
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text("[]", encoding="utf-8")

        real_read_text = capability_health.Path.read_text

        def _raising_read_text(self, *a, **kw):
            if str(self) == str(queue_path):
                raise PermissionError("permission denied")
            return real_read_text(self, *a, **kw)

        with mock.patch.object(capability_health.Path, "read_text", new=_raising_read_text):
            records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, "clean_cap2")

        self.assertTrue(record["importable"])
        self.assertTrue(record["scanner_clean"])
        self.assertFalse(record["pending_migration"])
        self.assertTrue(record.get("state_read_error"))
        self.assertEqual(record["health"], "red")


class TestDescriptorEnumerationErrorSurfaced(CapabilityHealthTestBase):
    def test_malformed_descriptor_file_surfaces_sentinel_red_not_silently_dropped(self):
        # (xvendor Fix B) A malformed descriptor set (exists, but not valid
        # JSON) must NOT silently collapse to the empty set -- that would
        # DROP a descriptor-only capability_id (no source file) from
        # enumeration with zero signal. The checker itself must report
        # degraded via the sentinel record.
        path = self.project_root / DESCRIPTOR_SET_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not valid json", encoding="utf-8")

        records = capability_health.check_capabilities(self.project_root)
        sentinel = self._record_for(
            records, capability_health.SENTINEL_DESCRIPTOR_ENUMERATION_ERROR_ID)
        self.assertEqual(sentinel["health"], "red")
        self.assertTrue(sentinel["state_read_error"])

    def test_unreadable_descriptor_file_surfaces_sentinel_red_not_silently_dropped(self):
        # Same signal, permission-error flavor rather than malformed-JSON.
        path = self.project_root / DESCRIPTOR_SET_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([{"id": "ghost_cap_2"}]), encoding="utf-8")

        real_read_text = capability_health.Path.read_text

        def _raising_read_text(self, *a, **kw):
            if str(self) == str(path):
                raise PermissionError("permission denied")
            return real_read_text(self, *a, **kw)

        with mock.patch.object(capability_health.Path, "read_text", new=_raising_read_text):
            records = capability_health.check_capabilities(self.project_root)
        sentinel = self._record_for(
            records, capability_health.SENTINEL_DESCRIPTOR_ENUMERATION_ERROR_ID)
        self.assertEqual(sentinel["health"], "red")
        # ghost_cap_2 could not be positively enumerated this run -- it must
        # not silently appear as a normal (implicitly clean) record.
        self.assertNotIn("ghost_cap_2", {r["capability_id"] for r in records})


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


class ReconcileOnReadTestBase(CapabilityHealthTestBase):
    """Task A2 / F-70 (crash-safety half) shared fixtures. ``reconcile_state`` is only ever
    invoked from the normal accept path (Task A1) and ``complete_migration`` -- a crash BETWEEN
    an accept write and its own reconcile call (or any other drift) can leave an accepted
    capability's ``paused_live_write`` marker orphaned on disk forever, with nothing that only
    ever READS health ever clearing it. ``check_capabilities_with_self_heal`` is the fix: the
    read path an agent actually runs before inviting the operator into a capability
    (``operating_discipline.md``) self-heals first, fail-safe."""

    PHASE_ID = "phase_a2_test"

    def _accept(self, capability_id: str, cap_path: Path) -> None:
        # Mirrors TestAcceptanceStaleCapabilityRed._accept above -- a real, well-formed
        # acceptance-audit record whose hashes match the fixture's OWN current source, so
        # `acceptance_stale` reads False and does not mask the marker-residue signal this test
        # is actually isolating.
        from external_write.acceptance_ceremony import ACCEPTANCE_RECORD_SCHEMA
        from external_write.proof_hash import compute_implementation_hash

        module_hash = hashlib.sha256(cap_path.read_bytes()).hexdigest()
        log_path = self.project_root / "security" / "capability_acceptance_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": ACCEPTANCE_RECORD_SCHEMA, "capability_id": capability_id,
            "phase_id": self.PHASE_ID, "risk_class": "irreversible_external",
            "op_kind": "delete_record", "copy_run_proof_ref": "proof.json",
            "operator_receipt_ref": "receipt.json", "contract_hash": "0" * 64,
            "implementation_hash": compute_implementation_hash("delete_record"),
            "capability_module_hash": module_hash,
            "operator_confirmation": "Yes, accept this capability for live use.",
            "receipt_accepted_at": "2026-01-01T00:00:00Z",
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def _write_orphaned_marker(self, capability_id: str) -> None:
        # Mirrors the real on-disk shape a genuine orphaned marker carries (see
        # lifecycle_state._fresh_marker_state) -- the exact estate/F-70 shape, hand-planted here
        # to simulate a crash between an accept write and its own reconcile call.
        d = self.project_root / PAUSED_MECHANISMS_DIR_REL
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{capability_id}.pause").write_text("", encoding="utf-8")
        (d / f"{capability_id}.json").write_text(json.dumps({
            "mechanism_id": capability_id,
            "canonical_id": capability_id,
            "writer_relpath": f"{CAPABILITIES_DIR_REL}/{capability_id}_capability.py",
            "entrypoint_relpath": None,
            "state": "paused_live_write",
            "paused_op_kinds": ["delete_record"],
            "paused_at": "2026-01-01T00:00:00Z",
            "reason": "capability descriptor not accepted; migration pending (reconcile_state)",
            "credentials_preserved": True,
            "migration_status": "pending",
        }), encoding="utf-8")

    def _accept_with_orphaned_marker(self, capability_id: str) -> Path:
        cap_path = self._write_capability(
            capability_id, _CLEAN_CAPABILITY_SOURCE.format(display_name=capability_id))
        self._write_descriptor_set(
            [{"id": capability_id, "accepted": True, "phase_id": self.PHASE_ID}])
        self._accept(capability_id, cap_path)
        self._write_orphaned_marker(capability_id)
        return cap_path


class TestReconcileOnReadSelfHeals(ReconcileOnReadTestBase):
    def test_accepted_capability_with_orphaned_marker_reports_green_after_read(self):
        cap_id = "widget_sync"
        self._accept_with_orphaned_marker(cap_id)
        marker_dir = self.project_root / PAUSED_MECHANISMS_DIR_REL
        self.assertTrue((marker_dir / f"{cap_id}.pause").exists())
        self.assertTrue((marker_dir / f"{cap_id}.json").exists())

        records = capability_health.check_capabilities_with_self_heal(self.project_root)
        record = self._record_for(records, cap_id)

        # The marker is genuinely gone from disk -- not merely reported clear in-memory -- so a
        # subsequent write-gate read (which reads these SAME files) observes the healed state.
        self.assertFalse((marker_dir / f"{cap_id}.pause").exists())
        self.assertFalse((marker_dir / f"{cap_id}.json").exists())
        self.assertFalse(record["paused"])
        self.assertFalse(record["pending_migration"])
        self.assertFalse(record["acceptance_stale"])
        self.assertEqual(record["health"], "green")

    def test_plain_check_capabilities_does_not_self_heal(self):
        # check_capabilities itself stays exactly as it was (no parameter, no side effect) --
        # the self-heal lives ONLY in check_capabilities_with_self_heal. This is what keeps
        # lifecycle_state.check_completion's own explicit "never writes to disk" contract intact:
        # it calls check_capabilities directly, never the self-healing wrapper.
        cap_id = "widget_sync_plain"
        self._accept_with_orphaned_marker(cap_id)
        marker_dir = self.project_root / PAUSED_MECHANISMS_DIR_REL

        records = capability_health.check_capabilities(self.project_root)
        record = self._record_for(records, cap_id)

        self.assertTrue((marker_dir / f"{cap_id}.pause").exists())
        self.assertTrue(record["paused"])
        self.assertEqual(record["health"], "red")


class TestReconcileOnReadNeverUnpausesUnaccepted(ReconcileOnReadTestBase):
    """(A2 review, Important) Pins the safety property at the WRAPPER call site
    (``check_capabilities_with_self_heal``), not just at ``reconcile_state`` (already tested
    directly elsewhere): self-heal-on-read must NEVER unpause a genuinely non-accepted
    capability. A legitimately-paused, NOT-accepted capability -- ``descriptor.accepted`` is
    False AND a migration is queued for it, the real pending-migration/not-yet-rebuilt shape
    ``reconcile_state``'s own not-accepted-and-migration-open branch ensures/preserves a marker
    for -- must still report the marker present and the capability paused AFTER a read through
    the self-healing wrapper. Unpausing it would be a safety regression: a broken/unaccepted
    capability silently unblocked. This test exists so a future edit to ``_attempt_self_heal`` or
    to ``reconcile_state``'s own branching cannot silently reopen that window without a
    wrapper-level test noticing."""

    def _not_accepted_paused_with_pending_migration(self, capability_id: str) -> Path:
        # Same real on-disk shape as `_accept_with_orphaned_marker` above, EXCEPT the descriptor
        # entry is accepted:False (never accepted) and a real migration is queued for it -- this
        # is the LEGITIMATE not-accepted-and-paused state `reconcile_state`'s own
        # not-accepted-and-migration-open branch is meant to preserve, not the crash-orphan case.
        cap_path = self._write_capability(
            capability_id, _CLEAN_CAPABILITY_SOURCE.format(display_name=capability_id))
        self._write_descriptor_set(
            [{"id": capability_id, "accepted": False, "phase_id": self.PHASE_ID}])
        self._write_pending_migration(capability_id)
        self._write_orphaned_marker(capability_id)
        return cap_path

    def test_not_accepted_paused_capability_stays_paused_after_self_heal_read(self):
        cap_id = "widget_sync_pending"
        cap_path = self._not_accepted_paused_with_pending_migration(cap_id)
        marker_dir = self.project_root / PAUSED_MECHANISMS_DIR_REL
        self.assertTrue((marker_dir / f"{cap_id}.pause").exists())
        self.assertTrue((marker_dir / f"{cap_id}.json").exists())

        records = capability_health.check_capabilities_with_self_heal(self.project_root)
        record = self._record_for(records, cap_id)

        # The decisive assertion: self-heal-on-read must NEVER clear a legitimately-paused,
        # not-accepted capability's marker -- it must still be on disk, and the read must still
        # report it paused/red, exactly as it was before the read.
        self.assertTrue((marker_dir / f"{cap_id}.pause").exists())
        self.assertTrue((marker_dir / f"{cap_id}.json").exists())
        self.assertTrue(record["paused"])
        self.assertEqual(record["health"], "red")

        # ANTI-VACUOUS CONTRAST: flip this SAME capability's descriptor to accepted:True (with a
        # matching real acceptance record) -- NOW reconcile-on-read WOULD clear the very same
        # marker. This proves the prior assertions are actually exercising the not-accepted
        # branch's PRESERVE behavior, not merely a checker that never clears any marker at all
        # (which would trivially pass the assertions above for the wrong reason).
        self._write_descriptor_set(
            [{"id": cap_id, "accepted": True, "phase_id": self.PHASE_ID}])
        self._accept(cap_id, cap_path)

        records_after_accept = capability_health.check_capabilities_with_self_heal(
            self.project_root)
        record_after_accept = self._record_for(records_after_accept, cap_id)
        self.assertFalse((marker_dir / f"{cap_id}.pause").exists())
        self.assertFalse((marker_dir / f"{cap_id}.json").exists())
        self.assertFalse(record_after_accept["paused"])


class TestReconcileOnReadFailSafeOnReadOnlyFilesystem(ReconcileOnReadTestBase):
    def test_readonly_paused_mechanisms_dir_reports_orphan_without_crashing(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("running as root -- permission bits do not block the write")

        cap_id = "widget_sync_ro"
        self._accept_with_orphaned_marker(cap_id)
        marker_dir = self.project_root / PAUSED_MECHANISMS_DIR_REL
        original_mode = marker_dir.stat().st_mode

        # Read + execute only, no write -- os.unlink() of an entry INSIDE this directory (what
        # reconcile_state's own marker-clear does) requires write permission on the directory
        # itself, not the file, so this reproduces a read-only filesystem's refusal without
        # needing an actual read-only mount.
        marker_dir.chmod(0o555)
        try:
            records = capability_health.check_capabilities_with_self_heal(
                self.project_root)  # must not raise
        finally:
            marker_dir.chmod(original_mode)

        record = self._record_for(records, cap_id)
        # The write it attempted could not complete -- the orphan is REPORTED honestly, not
        # silently healed and not a crash.
        self.assertTrue(record["paused"])
        self.assertEqual(record["health"], "red")
        self.assertTrue((marker_dir / f"{cap_id}.pause").exists())


class IdentityTwinTestBase(CapabilityHealthTestBase):
    """(Task A4 / F-72) shared fixtures for the identity-twin classification tests -- generic,
    op-kind-agnostic ids (cap_alpha / cap-alpha), never the real estate inbox names, per the
    task's own anti-overfit instruction. ``cap_alpha`` (underscore) is the REAL, built, live
    canonical capability throughout; ``cap-alpha`` (hyphen) is the never-built descriptor-only
    twin whose classification is under test."""

    def _write_audit_record(self, capability_id: str):
        log_path = self.project_root / "security" / "capability_acceptance_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"capability_id": capability_id, "note": "test fixture"}) + "\n")

    def _write_ledger_run(self, surface: str, op_kind: str = "field_write",
                          window_id: str = "test_window", n: int = 1):
        """(Fix 2, A4 post-merge review) Write a persisted blast-radius invocation ledger file in
        the SAME shape ``write_gate.PersistentInvocationLedger`` writes -- a ``counts`` dict keyed
        by ``f"{surface}::{op_kind}"`` (``write_gate._ledger_key``'s own convention) -- so a test
        can simulate a real LIVE_BOUNDED pre-acceptance trial run having happened for a
        capability_id/name without going through the whole write-gate call stack."""
        ledger_dir = self.project_root / LEDGER_DIR_REL
        ledger_dir.mkdir(parents=True, exist_ok=True)
        path = ledger_dir / f"{window_id}.ledger.json"
        payload = {
            "schema": "invocation_ledger-v1",
            "ledger_window_id": window_id,
            "counts": {f"{surface}::{op_kind}": n},
        }
        path.write_text(json.dumps(payload), encoding="utf-8")


class TestIdentityTwinNeverBuiltNeverAcceptedIsPending(IdentityTwinTestBase):
    def test_never_built_never_accepted_twin_reports_pending_not_red(self):
        # The estate F-72 shape, generically: a stale hyphenated descriptor entry that was never
        # built and never accepted, with no state of its own, coexisting with the real,
        # already-built underscore capability. This must NOT be a RED phantom.
        self._write_capability(
            "cap_alpha", _CLEAN_CAPABILITY_SOURCE.format(display_name="Cap Alpha"))
        self._write_descriptor_set([
            {"id": "cap-alpha", "name": "cap-alpha", "accepted": False},
        ])

        records = capability_health.check_capabilities(self.project_root)

        twin = self._record_for(records, "cap-alpha")
        self.assertEqual(twin["health"], "pending")
        self.assertEqual(twin["identity_twin_of"], "cap_alpha")
        self.assertIsNotNone(twin["operator_message"])
        self.assertIn("cap-alpha", twin["operator_message"])
        self.assertIn("cap_alpha", twin["operator_message"])

        # The real, built capability is completely unaffected -- still green.
        real = self._record_for(records, "cap_alpha")
        self.assertEqual(real["health"], "green")

    def test_twin_with_absent_accepted_field_also_reports_pending(self):
        # No "accepted" key at all (not even False) -- must resolve fail-safe to "no accepted
        # state", not crash and not identity_conflict.
        self._write_capability(
            "cap_alpha", _CLEAN_CAPABILITY_SOURCE.format(display_name="Cap Alpha"))
        self._write_descriptor_set([{"id": "cap-alpha", "name": "cap-alpha"}])

        records = capability_health.check_capabilities(self.project_root)
        twin = self._record_for(records, "cap-alpha")
        self.assertEqual(twin["health"], "pending")


class TestIdentityTwinWithStateIsConflict(IdentityTwinTestBase):
    def test_twin_marked_accepted_is_identity_conflict_not_pending(self):
        self._write_capability(
            "cap_alpha", _CLEAN_CAPABILITY_SOURCE.format(display_name="Cap Alpha"))
        self._write_descriptor_set([
            {"id": "cap-alpha", "name": "cap-alpha", "accepted": True},
        ])

        records = capability_health.check_capabilities(self.project_root)
        twin = self._record_for(records, "cap-alpha")
        self.assertEqual(twin["health"], "identity_conflict")
        self.assertEqual(twin["identity_twin_of"], "cap_alpha")
        self.assertIsNotNone(twin["operator_message"])

    def test_twin_with_acceptance_audit_record_is_identity_conflict(self):
        # Never-accepted per its OWN descriptor entry, but a real acceptance-audit record on
        # file for this exact id -- real recorded history, so it cannot be silently tombstoned.
        self._write_capability(
            "cap_alpha", _CLEAN_CAPABILITY_SOURCE.format(display_name="Cap Alpha"))
        self._write_descriptor_set([
            {"id": "cap-alpha", "name": "cap-alpha", "accepted": False},
        ])
        self._write_audit_record("cap-alpha")

        records = capability_health.check_capabilities(self.project_root)
        twin = self._record_for(records, "cap-alpha")
        self.assertEqual(twin["health"], "identity_conflict")

    def test_twin_with_pending_migration_is_identity_conflict(self):
        self._write_capability(
            "cap_alpha", _CLEAN_CAPABILITY_SOURCE.format(display_name="Cap Alpha"))
        self._write_descriptor_set([
            {"id": "cap-alpha", "name": "cap-alpha", "accepted": False},
        ])
        self._write_pending_migration("cap-alpha")

        records = capability_health.check_capabilities(self.project_root)
        twin = self._record_for(records, "cap-alpha")
        self.assertEqual(twin["health"], "identity_conflict")

    def test_twin_with_pause_marker_is_identity_conflict(self):
        self._write_capability(
            "cap_alpha", _CLEAN_CAPABILITY_SOURCE.format(display_name="Cap Alpha"))
        self._write_descriptor_set([
            {"id": "cap-alpha", "name": "cap-alpha", "accepted": False},
        ])
        self._write_pause_marker("cap-alpha")

        records = capability_health.check_capabilities(self.project_root)
        twin = self._record_for(records, "cap-alpha")
        self.assertEqual(twin["health"], "identity_conflict")

    def test_never_accepted_twin_with_ledger_run_history_is_identity_conflict(self):
        # (Fix 2, A4 post-merge review) has_state soundness: a never-accepted twin can still have
        # authorized a REAL bounded-live write via the write-gate's LIVE_BOUNDED pre-acceptance
        # trial path (a DECLARED, not-yet-accepted descriptor entry is enough to authorize that
        # path -- see write_gate.py's `_declared_entry`). Silently tombstoning that would discard
        # genuine run history -- this must be identity_conflict, never pending.
        self._write_capability(
            "cap_alpha", _CLEAN_CAPABILITY_SOURCE.format(display_name="Cap Alpha"))
        self._write_descriptor_set([
            {"id": "cap-alpha", "name": "cap-alpha", "accepted": False},
        ])
        self._write_ledger_run(surface="cap-alpha", op_kind="field_write")

        records = capability_health.check_capabilities(self.project_root)
        twin = self._record_for(records, "cap-alpha")
        self.assertEqual(twin["health"], "identity_conflict")
        self.assertIsNotNone(twin["operator_message"])

        # The real, built capability is completely unaffected -- still green.
        real = self._record_for(records, "cap_alpha")
        self.assertEqual(real["health"], "green")

    def test_never_accepted_twin_with_ledger_run_attributed_by_name_is_identity_conflict(self):
        # The write-gate's own op->capability join matches op.surface against a descriptor
        # entry's `id` OR `name` -- a ledger key attributed via the entry's `name` (rather than
        # its `id`) must be caught too, not just an exact-id match.
        self._write_capability(
            "cap_alpha", _CLEAN_CAPABILITY_SOURCE.format(display_name="Cap Alpha"))
        self._write_descriptor_set([
            {"id": "cap-alpha", "name": "cap-alpha-display-name", "accepted": False},
        ])
        self._write_ledger_run(surface="cap-alpha-display-name", op_kind="bounded_sample")

        records = capability_health.check_capabilities(self.project_root)
        twin = self._record_for(records, "cap-alpha")
        self.assertEqual(twin["health"], "identity_conflict")

    def test_twin_ledger_run_for_a_different_capability_does_not_affect_this_twin(self):
        # Anti-vacuous contrast: a ledger file with run history for an UNRELATED surface must not
        # cause a false identity_conflict for this twin.
        self._write_capability(
            "cap_alpha", _CLEAN_CAPABILITY_SOURCE.format(display_name="Cap Alpha"))
        self._write_descriptor_set([
            {"id": "cap-alpha", "name": "cap-alpha", "accepted": False},
        ])
        self._write_ledger_run(surface="totally_unrelated_surface", op_kind="field_write")

        records = capability_health.check_capabilities(self.project_root)
        twin = self._record_for(records, "cap-alpha")
        self.assertEqual(twin["health"], "pending")


class TestNonTwinDescriptorOnlyEntryUnaffected(IdentityTwinTestBase):
    def test_descriptor_only_entry_with_no_twin_still_reports_red(self):
        # Anti-vacuous contrast (and a direct re-proof of
        # TestDescriptorOnlyCapabilityWithNoSourceFile alongside a REAL, unrelated built
        # capability in the same project): a descriptor-only id that does NOT normalize-collide
        # with anything built must be completely untouched by this task -- still RED, exactly as
        # before Task A4.
        self._write_capability(
            "cap_alpha", _CLEAN_CAPABILITY_SOURCE.format(display_name="Cap Alpha"))
        self._write_descriptor_set([
            {"id": "totally_unrelated_ghost", "name": "totally_unrelated_ghost"},
        ])

        records = capability_health.check_capabilities(self.project_root)
        ghost = self._record_for(records, "totally_unrelated_ghost")
        self.assertEqual(ghost["health"], "red")
        self.assertIsNone(ghost["identity_twin_of"])
        self.assertIsNone(ghost["operator_message"])


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

    def test_acceptance_log_rel_matches_lifecycle_state_constant(self):
        # (Task A4 / F-72) capability_health.ACCEPTANCE_LOG_REL is duplicated-by-value from
        # lifecycle_state.ACCEPTANCE_LOG_REL -- same anti-drift discipline as the four pins above.
        self.assertEqual(
            capability_health.ACCEPTANCE_LOG_REL,
            lifecycle_state.ACCEPTANCE_LOG_REL,
        )

    def test_ledger_dir_rel_matches_write_gate_default_ledger_dir(self):
        # (Fix 2, A4 post-merge review) capability_health.LEDGER_DIR_REL is duplicated-by-value
        # from write_gate.DEFAULT_LEDGER_DIR -- same anti-drift discipline as every other pin in
        # this class.
        self.assertEqual(
            capability_health.LEDGER_DIR_REL,
            write_gate.DEFAULT_LEDGER_DIR,
        )


if __name__ == "__main__":
    unittest.main()
