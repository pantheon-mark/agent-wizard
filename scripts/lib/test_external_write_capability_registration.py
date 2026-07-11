"""Tests for B2-T5 capability_registration — the operate-time deterministic writer that lands a
newly-declared (accepted:false) capability descriptor in security/capability_descriptors.json AND,
in the SAME fail-safe operation, regenerates the QA-visible co-protected-workflows.md table so a
gated capability can never be landed while the guard stays blind to it.

Trust-critical. The OVERRIDING properties under test:
  * fail-safe: any missing / malformed / ambiguous input REFUSES and writes NOTHING;
  * accepted:false only — this helper is NEVER a path to accepted:true (that is the ceremony's
    sole job);
  * mandatory-by-construction co-protected registration for a GATED capability: if the co-protected
    table cannot be regenerated, the descriptor is NOT landed (no half-registration);
  * phase_id round-trips: a descriptor this helper lands is accepted-eligible by the ceremony.

Placed in wizard/scripts/lib (not agents/lib) so it can import BOTH trees for the cross-tree
drift pins, exactly as test_external_write_acceptance_ceremony.py does.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_write import capability_registration as cr  # noqa: E402
from external_write.capability_registration import (  # noqa: E402
    register_declared_capability,
    RegistrationResult,
    REGISTERED_ENTRY_KEYS,
    CO_PROTECTED_RISK_CLASSES,
)
from external_write.write_gate import (  # noqa: E402
    GATED_RISK_CLASSES,
    load_descriptor_set,
    evaluate_write_gate,
    InvocationLedger,
    LIVE_TARGET,
)
from external_write.coverage_gate import evaluate_coverage_gate  # noqa: E402
from external_write.operations import Operation  # noqa: E402

# Build-side modules (cross-tree pins — this test lives in scripts/lib and may import agents/lib).
import capability_descriptor_registry as cdr  # noqa: E402
import co_protected_workflows as cpw  # noqa: E402


PHASE = "phase_07"

# A minimal but structurally-faithful rendered co-protected-workflows.md — the header/separator/
# blank/section-rule shape the emit produces (placeholder already substituted to empty).
CO_PROTECTED_MD = """# Co-Protected Workflows

## Registered capability workflows

*Per-capability high-risk workflows.*

| Capability | Action class | Risk class | What's protected |
|-----------|-------------|-----------|------------------|


---

## How protection works

1. The QA agent reads this file at every security audit invocation.
"""


def _declared(id="mailbox_cleanup", *, name=None, action_class="delete",
              risk_class="irreversible_external", recovery_profile_ref="rp-1",
              declared_test_target="copy", blast_radius_cap=5, phase_id=PHASE,
              accepted=False):
    d = {
        "id": id,
        "name": name if name is not None else id,
        "action_class": action_class,
        "risk_class": risk_class,
        "recovery_profile_ref": recovery_profile_ref,
        "declared_test_target": declared_test_target,
        "blast_radius_cap": blast_radius_cap,
        "phase_id": phase_id,
        "accepted": accepted,
    }
    return d


class _Project:
    """A materialised operator project on disk: security/ descriptor set + a co-protected md."""

    def __init__(self, tmp, *, descriptors, co_protected_text=CO_PROTECTED_MD):
        self.tmp = Path(tmp)
        self.security = self.tmp / "security"
        self.security.mkdir(parents=True, exist_ok=True)
        self.quality = self.tmp / "quality"
        self.quality.mkdir(parents=True, exist_ok=True)
        self.set_path = self.security / "capability_descriptors.json"
        self.co_path = self.quality / "co-protected-workflows.md"
        self.set_path.write_text(json.dumps(descriptors, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        if co_protected_text is not None:
            self.co_path.write_text(co_protected_text, encoding="utf-8")

    def set_bytes(self):
        return self.set_path.read_bytes()

    def co_bytes(self):
        return self.co_path.read_bytes() if self.co_path.exists() else None

    def entries(self):
        return json.loads(self.set_path.read_text(encoding="utf-8"))

    def call(self, declared, **kw):
        return register_declared_capability(
            declared,
            descriptor_set_path=str(self.set_path),
            co_protected_path=str(self.co_path),
            **kw)


def _base():
    """The base declared descriptor set every writes-back system carries (build-side producer)."""
    return cdr.base_declared_descriptors()


class DriftPinTest(unittest.TestCase):
    """Cross-tree pins: the operate-time helper duplicates build-side constants (D-B1-a — it may
    not import the build tree) and MUST stay equal to them, exactly as write_gate pins its
    vocabulary."""

    def test_registered_entry_keys_equal_build_side_entry_keys(self):
        self.assertEqual(set(REGISTERED_ENTRY_KEYS), set(cdr.ENTRY_KEYS))

    def test_entry_key_order_matches_build_side(self):
        self.assertEqual(tuple(REGISTERED_ENTRY_KEYS), tuple(cdr.ENTRY_KEYS))

    def test_co_protected_risk_classes_equal_gated_and_protected(self):
        self.assertEqual(set(CO_PROTECTED_RISK_CLASSES), set(GATED_RISK_CLASSES))
        self.assertEqual(set(CO_PROTECTED_RISK_CLASSES), set(cpw.PROTECTED_RISK_CLASSES))

    def test_base_prefix_matches_build_side(self):
        self.assertEqual(cr.BASE_DESCRIPTOR_ID_PREFIX, cdr.BASE_DESCRIPTOR_ID_PREFIX)

    def test_protection_notes_match_build_side(self):
        self.assertEqual(cr._PROTECTION_NOTE, cpw._PROTECTION_NOTE)
        self.assertEqual(cr.STANDING_AUTOMATION_FLOOR_NOTE, cpw.STANDING_AUTOMATION_FLOOR_NOTE)

    def test_table_header_matches_real_template_file(self):
        # CO_PROTECTED_TABLE_HEADER is the anchor _rewrite_co_protected_table locates the table by.
        # It is a literal duplicate of the emitted template's header row; if a future template
        # reword changes that row without this constant following, every GATED registration would
        # hit "no table header" and refuse forever. Read the REAL template file (not a fixture) so
        # a reword can't silently drift past this test.
        template_path = (Path(__file__).resolve().parents[3] / "wizard" / "templates" /
                         "quality" / "co-protected-workflows.md")
        self.assertTrue(template_path.is_file(), f"template not found at {template_path}")
        template_text = template_path.read_text(encoding="utf-8")
        header_lines = [line for line in template_text.split("\n")
                        if line.strip() == cr.CO_PROTECTED_TABLE_HEADER]
        self.assertEqual(
            len(header_lines), 1,
            "CO_PROTECTED_TABLE_HEADER must match exactly one line in the real template — a "
            "template reword has drifted from the duplicated constant in capability_registration.py")


class HappyPathTest(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def test_gated_capability_lands_and_registers_co_protected(self):
        p = _Project(self.tmp, descriptors=_base())
        res = p.call(_declared(id="mailbox_cleanup", name="Mailbox cleanup"))
        self.assertIsInstance(res, RegistrationResult)
        self.assertTrue(res.registered, res.reason)
        self.assertTrue(res.co_protected_updated)
        # descriptor set now carries the new entry, accepted:false, phase_id populated.
        by_id = {e["id"]: e for e in p.entries()}
        self.assertIn("mailbox_cleanup", by_id)
        e = by_id["mailbox_cleanup"]
        self.assertIs(e["accepted"], False)
        self.assertEqual(e["phase_id"], PHASE)
        self.assertEqual(set(e.keys()), set(REGISTERED_ENTRY_KEYS))
        # co-protected table now names the capability (guard is no longer blind).
        co = p.co_path.read_text(encoding="utf-8")
        self.assertIn("Mailbox cleanup", co)
        self.assertIn("irreversible_external", co)

    def test_base_builtin_entries_never_appear_in_co_protected(self):
        p = _Project(self.tmp, descriptors=_base())
        p.call(_declared(id="mailbox_cleanup", name="Mailbox cleanup"))
        co = p.co_path.read_text(encoding="utf-8")
        self.assertNotIn(cr.BASE_DESCRIPTOR_ID_PREFIX, co)

    def test_standing_automation_row_states_non_graduating_floor(self):
        p = _Project(self.tmp, descriptors=_base())
        p.call(_declared(id="auto_filter", name="Auto filter", action_class="route",
                         risk_class="standing_automation"))
        co = p.co_path.read_text(encoding="utf-8")
        self.assertIn("Auto filter", co)
        self.assertIn("NON-GRADUATING", co)

    def test_non_gated_capability_lands_without_co_protected_row(self):
        p = _Project(self.tmp, descriptors=_base())
        res = p.call(_declared(id="status_sync", name="Status sync", action_class="mutate",
                               risk_class="reversible_external"))
        self.assertTrue(res.registered, res.reason)
        self.assertIn("status_sync", {e["id"] for e in p.entries()})
        co = p.co_path.read_text(encoding="utf-8")
        self.assertNotIn("Status sync", co)

    def test_co_protected_regeneration_is_idempotent_in_shape(self):
        p = _Project(self.tmp, descriptors=_base())
        p.call(_declared(id="mailbox_cleanup", name="Mailbox cleanup"))
        first = p.co_path.read_text(encoding="utf-8")
        # A second, different capability regenerates from the full set; the first row survives.
        p.call(_declared(id="purge_records", name="Purge records"))
        second = p.co_path.read_text(encoding="utf-8")
        self.assertIn("Mailbox cleanup", second)
        self.assertIn("Purge records", second)
        # The static prose + section rule are preserved across regenerations.
        self.assertIn("## How protection works", second)
        self.assertIn("## Registered capability workflows", first)

    def test_coverage_gate_stays_green_after_registration(self):
        p = _Project(self.tmp, descriptors=_base())
        p.call(_declared(id="mailbox_cleanup", name="Mailbox cleanup"))
        ds = load_descriptor_set(str(p.set_path))
        decision = evaluate_coverage_gate(scan_violations=[], descriptor_set=ds)
        self.assertTrue(decision.passed, decision.failures)


class FailSafeTest(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def test_missing_descriptor_set_refuses_and_writes_nothing(self):
        p = _Project(self.tmp, descriptors=_base())
        p.set_path.unlink()
        res = p.call(_declared())
        self.assertFalse(res.registered)
        self.assertFalse(p.set_path.exists())

    def test_malformed_descriptor_set_refuses(self):
        p = _Project(self.tmp, descriptors=_base())
        p.set_path.write_text("{not json", encoding="utf-8")
        orig = p.set_bytes()
        res = p.call(_declared())
        self.assertFalse(res.registered)
        self.assertEqual(p.set_bytes(), orig)

    def test_non_list_descriptor_set_refuses(self):
        p = _Project(self.tmp, descriptors=_base())
        p.set_path.write_text(json.dumps({"id": "x"}), encoding="utf-8")
        orig = p.set_bytes()
        res = p.call(_declared())
        self.assertFalse(res.registered)
        self.assertEqual(p.set_bytes(), orig)

    def test_missing_phase_id_refuses(self):
        p = _Project(self.tmp, descriptors=_base())
        orig = p.set_bytes()
        res = p.call(_declared(phase_id=None))
        self.assertFalse(res.registered)
        self.assertEqual(p.set_bytes(), orig)

    def test_empty_phase_id_refuses(self):
        p = _Project(self.tmp, descriptors=_base())
        res = p.call(_declared(phase_id="   "))
        self.assertFalse(res.registered)

    def test_accepted_true_input_refuses(self):
        # The helper is NEVER a path to accepted:true.
        p = _Project(self.tmp, descriptors=_base())
        orig = p.set_bytes()
        res = p.call(_declared(accepted=True))
        self.assertFalse(res.registered)
        self.assertEqual(p.set_bytes(), orig)

    def test_missing_id_refuses(self):
        p = _Project(self.tmp, descriptors=_base())
        res = p.call(_declared(id=""))
        self.assertFalse(res.registered)

    def test_reserved_builtin_id_refuses(self):
        p = _Project(self.tmp, descriptors=_base())
        res = p.call(_declared(id="__builtin__:irreversible_external"))
        self.assertFalse(res.registered)

    def test_duplicate_id_refuses(self):
        p = _Project(self.tmp, descriptors=_base())
        p.call(_declared(id="mailbox_cleanup", name="Mailbox cleanup"))
        set_after_first = p.set_bytes()
        res = p.call(_declared(id="mailbox_cleanup", name="Mailbox cleanup"))
        self.assertFalse(res.registered)
        # No duplicate appended.
        self.assertEqual(p.set_bytes(), set_after_first)

    def test_gated_with_unlocatable_co_protected_table_refuses_and_does_not_land(self):
        # Mandatory-by-construction: if the guard-visibility table cannot be found/regenerated,
        # a GATED descriptor is NOT landed (no half-registration).
        p = _Project(self.tmp, descriptors=_base(),
                     co_protected_text="# Co-Protected Workflows\n\n(no table here)\n")
        orig = p.set_bytes()
        res = p.call(_declared(id="mailbox_cleanup"))
        self.assertFalse(res.registered)
        self.assertEqual(p.set_bytes(), orig)
        self.assertNotIn("mailbox_cleanup", {e["id"] for e in p.entries()})

    def test_gated_with_missing_co_protected_file_refuses(self):
        p = _Project(self.tmp, descriptors=_base())
        p.co_path.unlink()
        orig = p.set_bytes()
        res = p.call(_declared(id="mailbox_cleanup"))
        self.assertFalse(res.registered)
        self.assertEqual(p.set_bytes(), orig)

    def test_unknown_risk_class_resolves_fail_safe_and_registers_protected(self):
        # F-28: an out-of-vocabulary/absent risk_class is resolved to the most-protected class,
        # never silently treated as safe — so it lands gated AND co-protected-registered.
        p = _Project(self.tmp, descriptors=_base())
        res = p.call(_declared(id="mystery", name="Mystery", risk_class=None))
        self.assertTrue(res.registered, res.reason)
        e = {x["id"]: x for x in p.entries()}["mystery"]
        self.assertIn(e["risk_class"], GATED_RISK_CLASSES)
        self.assertTrue(res.co_protected_updated)

    def test_co_protected_rolled_back_if_descriptor_set_write_fails(self):
        # All-or-nothing, REVERSED order: the co-protected table is written FIRST; if the
        # descriptor-set write (SECOND) then fails, the co-protected table is rolled back to its
        # exact prior text — never left with a phantom row for an unregistered capability.
        p = _Project(self.tmp, descriptors=_base())
        orig_set = p.set_bytes()
        orig_co = p.co_bytes()
        real_replace = os.replace
        calls = {"n": 0}

        def _second_replace_boom(src, dst):
            calls["n"] += 1
            if calls["n"] >= 2:  # first replace = co-protected table; second = descriptor set
                raise OSError("simulated descriptor-set write failure")
            return real_replace(src, dst)

        cr.os.replace = _second_replace_boom
        try:
            res = p.call(_declared(id="mailbox_cleanup"))
        finally:
            cr.os.replace = real_replace
        self.assertFalse(res.registered)
        self.assertEqual(p.set_bytes(), orig_set,
                         "descriptor set must be untouched when its own write fails")
        self.assertEqual(p.co_bytes(), orig_co,
                         "co-protected table must be rolled back on descriptor-set failure")
        self.assertNotIn("mailbox_cleanup", {e["id"] for e in p.entries()})
        self.assertNotIn("Mailbox cleanup", p.co_path.read_text(encoding="utf-8"))

    def test_co_protected_is_written_before_descriptor_set_for_gated_capability(self):
        # Crash-window proof: for a GATED capability the co-protected table's write MUST be
        # ordered before the descriptor set's write, so a crash between the two leaves at worst a
        # harmless phantom guard row (fail-safe) rather than a live descriptor with no guard row
        # (fail-open / blind). Monkeypatch the atomic writer to record call order by path.
        p = _Project(self.tmp, descriptors=_base())
        order = []
        real_atomic_write = cr._atomic_write_text

        def _recording_write(path, text):
            order.append(path)
            return real_atomic_write(path, text)

        cr._atomic_write_text = _recording_write
        try:
            res = p.call(_declared(id="mailbox_cleanup"))
        finally:
            cr._atomic_write_text = real_atomic_write
        self.assertTrue(res.registered, res.reason)
        self.assertEqual(len(order), 2)
        self.assertEqual(order[0], str(p.co_path),
                         "co-protected table must be written before the descriptor set")
        self.assertEqual(order[1], str(p.set_path))

    def test_retry_after_phantom_guard_row_self_heals(self):
        # Self-healing property: if a phantom guard row exists (as it would after a crash in the
        # window between the two writes) but the descriptor was never landed, a retry is NOT
        # blocked by the duplicate-id refusal (the descriptor doesn't exist yet) and regenerates
        # the co-protected table from the full set, reconciling the phantom row.
        p = _Project(self.tmp, descriptors=_base())
        phantom_co_text = cr._rewrite_co_protected_table(
            p.co_path.read_text(encoding="utf-8"),
            cr.co_protected_rows_from_entries([_declared(id="mailbox_cleanup",
                                                          name="Mailbox cleanup")]))
        p.co_path.write_text(phantom_co_text, encoding="utf-8")
        self.assertNotIn("mailbox_cleanup", {e["id"] for e in p.entries()})

        retry = p.call(_declared(id="mailbox_cleanup", name="Mailbox cleanup"))
        self.assertTrue(retry.registered, retry.reason)
        self.assertIn("mailbox_cleanup", {e["id"] for e in p.entries()})
        self.assertIn("Mailbox cleanup", p.co_path.read_text(encoding="utf-8"))


class CeremonyRoundTripTest(unittest.TestCase):
    """Integration: a descriptor this helper lands (with phase_id) is accepted-eligible by the
    B2-T3 acceptance ceremony — the phase_id obligation is satisfied end-to-end."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def _proof(self):
        from external_write.copy_run_proof import COPY_RUN_PROOF_SCHEMA
        from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA
        from external_write.proof_hash import compute_contract_hash, compute_implementation_hash
        verification = {
            "schema": POSTWRITE_VERIFICATION_SCHEMA,
            "verification_mode": "prestate_snapshot_diff",
            "claim_strength": "verified",
            "verifier_id": "prestate_snapshot_diff_v1",
            "source_lineage": {
                "pre_write_sources": ["prewrite_csv_backup"],
                "post_write_sources": ["live_surface_read"],
                "forbidden_sources": ["writer_generated_id_map", "live_id_column_as_truth",
                                      "apply_report"],
            },
            "invariant_checked": "record absent after delete",
            "evidence_ref": "agents/handoffs/.ev.txt",
        }
        return {
            "schema": COPY_RUN_PROOF_SCHEMA,
            "operation_id": "op-001",
            "op_kind": "delete_record",
            "capability_id": "google_sheets",
            "data_class": "rows",
            "copy_source_ref": "copies/copy.csv",
            "prestate_snapshot_ref": "copies/copy.prestate.csv",
            "copy_apply_proof": {"apply_receipt_ref": "agents/handoffs/.a.json",
                                 "apply_verification": verification},
            "copy_undo_proof": {"undo_receipt_ref": "agents/handoffs/.u.json",
                                "undo_verification": verification},
            "durability_checks": [],
            "accepted_for_live_use": True,
            "implementation_hash": compute_implementation_hash("delete_record"),
            "contract_hash": compute_contract_hash("delete_record"),
            # Task 6 (F-34 wire-verification): a real, clean, on-disk capability module — the
            # SAME fixture the Task-5 scanner test suite proves scans to zero violations.
            "capability_module_paths": [str(
                Path(__file__).resolve().parents[2] / "test_fixtures" / "external_write_scan"
                / "legal_through_adapter.py"
            )],
        }

    def test_registered_descriptor_is_accepted_by_ceremony(self):
        from external_write.acceptance_ceremony import (
            accept_capability_for_live_use, OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA)
        p = _Project(self.tmp, descriptors=_base())
        reg = p.call(_declared(id="google_sheets", name="google_sheets",
                               risk_class="irreversible_external", blast_radius_cap=5))
        self.assertTrue(reg.registered, reg.reason)

        proof_path = self.tmp + "/proof.json"
        Path(proof_path).write_text(json.dumps(self._proof()), encoding="utf-8")
        receipt_path = self.tmp + "/receipt.json"
        Path(receipt_path).write_text(json.dumps({
            "schema": OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA,
            "capability_id": "google_sheets",
            "phase_id": PHASE,
            "copy_run_proof_ref": proof_path,
            "operator_confirmation": "Yes, accept for live use.",
            "accepted_at": "2026-07-04T12:00:00Z",
        }), encoding="utf-8")

        res = accept_capability_for_live_use(
            "google_sheets", PHASE, proof_path, receipt_path,
            descriptor_set_path=str(p.set_path),
            audit_log_path=str(p.security / "acc.jsonl"))
        self.assertTrue(res.accepted, res.reason)
        # The ceremony flipped exactly this descriptor.
        flipped = {e["id"]: e for e in p.entries()}["google_sheets"]
        self.assertIs(flipped["accepted"], True)


if __name__ == "__main__":
    unittest.main()
