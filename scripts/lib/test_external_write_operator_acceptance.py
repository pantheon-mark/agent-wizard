"""B2-T6 — end-to-end tests for the operator-acceptance helper
(external_write.operator_acceptance), the deterministic Step-6 step that mints the
operator_acceptance_receipt-v1 from the operator's verbatim confirmation and drives the
acceptance ceremony.

The headline test is the BUILD->LIVE-AUTHORIZATION seam end to end: a real copy_run_proof (real
proof hashes, matching capability_id) + a real minted receipt + the real ceremony must flip the
descriptor, after which the runtime write_gate PERMITS a live write for that surface and still
REFUSES an unaccepted one. No mocks of the units under test.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

# Single-home (mirrors test_capability_code_scaffold.py's own sys.path setup):
# import the wizard TOOLKIT emitter by bare name from this directory.
_SCRIPTS_LIB_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB_DIR))

from external_write.operator_acceptance import (  # noqa: E402
    record_operator_acceptance,
    OperatorAcceptanceResult,
    DEFAULT_RECEIPT_DIR,
    PENDING_MIGRATIONS_REL,
    close_pending_migration_if_matched,
)
from external_write.acceptance_ceremony import OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA  # noqa: E402
from external_write.copy_run_proof import COPY_RUN_PROOF_SCHEMA  # noqa: E402
from external_write.lifecycle_state import acceptance_hash_is_stale  # noqa: E402
from external_write.proof_hash import (  # noqa: E402
    compute_contract_hash,
    compute_implementation_hash,
)
from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA  # noqa: E402
from external_write.operations import Operation  # noqa: E402
from external_write.write_gate import (  # noqa: E402
    InvocationLedger,
    load_descriptor_set,
    evaluate_write_gate,
    LIVE_TARGET,
)

from capability_code_scaffold import (  # noqa: E402
    CapabilityCodeSpec,
    emit_capability_code_scaffold,
)


PHASE = "phase_02"
OP_KIND = "delete_record"  # irreversible_external; gated; non-binding


def _verification():
    return {
        "schema": POSTWRITE_VERIFICATION_SCHEMA,
        "verification_mode": "prestate_snapshot_diff",
        "claim_strength": "verified",
        "verifier_id": "prestate_snapshot_diff_v1",
        "source_lineage": {
            "pre_write_sources": ["prewrite_csv_backup"],
            "post_write_sources": ["live_surface_read"],
            "forbidden_sources": [
                "writer_generated_id_map", "live_id_column_as_truth", "apply_report",
            ],
        },
        "invariant_checked": "record absent after delete",
        "evidence_ref": "agents/handoffs/.ev.txt",
    }


def _proof(capability_id="google_sheets", op_kind=OP_KIND):
    return {
        "schema": COPY_RUN_PROOF_SCHEMA,
        "operation_id": "op-001",
        "op_kind": op_kind,
        "capability_id": capability_id,
        "data_class": "estate_tracker_rows",
        "copy_source_ref": "copies/estate_copy.csv",
        "prestate_snapshot_ref": "copies/estate_copy.prestate.csv",
        "copy_apply_proof": {
            "apply_receipt_ref": "agents/handoffs/.apply_receipt.json",
            "apply_verification": _verification(),
        },
        "copy_undo_proof": {
            "undo_receipt_ref": "agents/handoffs/.undo_receipt.json",
            "undo_verification": _verification(),
        },
        "durability_checks": [],
        "accepted_for_live_use": True,
        "implementation_hash": compute_implementation_hash(op_kind),
        "contract_hash": compute_contract_hash(op_kind),
        # Task 6 (F-34 wire-verification): a real, clean, on-disk capability module — the SAME
        # fixture the Task-5 scanner test suite proves scans to zero violations.
        "capability_module_paths": [str(
            Path(__file__).resolve().parents[2] / "test_fixtures" / "external_write_scan"
            / "legal_through_adapter.py"
        )],
    }


def _descriptor(id="google_sheets", *, risk_class="irreversible_external", phase_id=PHASE,
                blast_radius_cap=5, accepted=False, action_class="delete"):
    return {
        "id": id, "name": id, "action_class": action_class, "risk_class": risk_class,
        "recovery_profile_ref": None, "declared_test_target": "copy",
        "blast_radius_cap": blast_radius_cap, "accepted": accepted, "phase_id": phase_id,
    }


class OperatorAcceptanceE2ETest(unittest.TestCase):

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.security = self.tmp / "security"
        self.security.mkdir(parents=True, exist_ok=True)
        self.set_path = self.security / "capability_descriptors.json"
        self.proof_path = self.tmp / "proof.json"
        self.receipt_path = self.security / "acceptance_receipts" / "google_sheets.receipt.json"
        self.audit_path = self.security / "capability_acceptance_log.jsonl"

    def tearDown(self):
        self._td.cleanup()

    def _write_set(self, descriptors):
        self.set_path.write_text(json.dumps(descriptors, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")

    def _write_proof(self, proof=None):
        self.proof_path.write_text(json.dumps(proof if proof is not None else _proof()),
                                   encoding="utf-8")

    def _call(self, *, capability_id="google_sheets", phase_id=PHASE,
              operator_confirmation="Yes — I accept this capability for live use.", **kw):
        return record_operator_acceptance(
            capability_id, phase_id, str(self.proof_path), operator_confirmation,
            receipt_path=str(self.receipt_path),
            descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path), **kw)

    def _accepted_flag(self, id):
        for e in json.loads(self.set_path.read_text(encoding="utf-8")):
            if e.get("id") == id:
                return e.get("accepted")
        return None

    # -- The headline end-to-end seam -------------------------------------

    def test_write_gate_permits_live_only_after_real_acceptance(self):
        # Two gated descriptors, both unaccepted. Before acceptance, the live write is refused.
        self._write_set([_descriptor(id="google_sheets"), _descriptor(id="asana")])
        self._write_proof()

        ds_before = load_descriptor_set(str(self.set_path))
        live_op = Operation(surface="google_sheets", object_id="row:1", field="__record__",
                            new_value="<x>", op_kind=OP_KIND, batch_id="b1")
        before = evaluate_write_gate(live_op, target=LIVE_TARGET, descriptor_set=ds_before,
                                     cap_ledger=InvocationLedger())
        self.assertFalse(before.permitted, "live write must be refused BEFORE acceptance")

        # The operator confirms; the helper mints the receipt + drives the ceremony.
        res = self._call()
        self.assertIsInstance(res, OperatorAcceptanceResult)
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(self._accepted_flag("google_sheets"), True)
        self.assertEqual(self._accepted_flag("asana"), False)

        # A real receipt was minted on disk, matching the ceremony's schema + verbatim text.
        self.assertTrue(Path(res.receipt_ref).exists())
        receipt = json.loads(Path(res.receipt_ref).read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema"], OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA)
        self.assertEqual(receipt["capability_id"], "google_sheets")
        self.assertEqual(receipt["operator_confirmation"],
                         "Yes — I accept this capability for live use.")

        # AFTER acceptance: write_gate PERMITS the live write for the accepted surface...
        ds_after = load_descriptor_set(str(self.set_path))
        after = evaluate_write_gate(live_op, target=LIVE_TARGET, descriptor_set=ds_after,
                                    cap_ledger=InvocationLedger())
        self.assertTrue(after.permitted, after.refusal)

        # ...and still REFUSES the unaccepted surface (asana never went through acceptance).
        other_op = Operation(surface="asana", object_id="row:1", field="__record__",
                             new_value="<x>", op_kind=OP_KIND, batch_id="b1")
        other = evaluate_write_gate(other_op, target=LIVE_TARGET, descriptor_set=ds_after,
                                    cap_ledger=InvocationLedger())
        self.assertFalse(other.permitted, "unaccepted surface must stay refused")

    # -- Honest capture: never fabricate the operator's yes ---------------

    def test_empty_confirmation_refuses_and_accepts_nothing(self):
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof()
        res = self._call(operator_confirmation="   ")
        self.assertFalse(res.accepted)
        self.assertIsNone(res.acceptance, "ceremony must not even be invoked without a yes")
        self.assertEqual(self._accepted_flag("google_sheets"), False)
        # No receipt was minted for a non-confirmation.
        self.assertFalse(self.receipt_path.exists())

    # -- The helper is not a second authority: ceremony still refuses -----

    def test_proof_for_other_capability_is_refused_by_ceremony(self):
        # A valid proof produced for a DIFFERENT capability must not cross-authorize, even though
        # the helper mints a well-formed receipt: the ceremony asserts proof.capability_id.
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof(_proof(capability_id="asana"))
        res = self._call(capability_id="google_sheets")
        self.assertFalse(res.accepted)
        self.assertIsNotNone(res.acceptance)
        self.assertFalse(res.acceptance.accepted)
        self.assertEqual(self._accepted_flag("google_sheets"), False)

    def test_default_receipt_dir_constant(self):
        self.assertEqual(DEFAULT_RECEIPT_DIR, "security/acceptance_receipts")


class SplitInstallCanonicalModulePathTest(unittest.TestCase):
    """R-1 (cross-vendor review fix) — the split-install shape: the descriptor's own id differs
    from its capability module's stem (the estate case: descriptor id "inbox-labels", module
    "inbox_management_capability.py"). Before this fix, ``record_operator_acceptance`` passed
    the RAW ``capability_id`` straight through as the ceremony's ``capability_module_path``
    default, which is WRONG for a split install — the module file at that (wrong) path does not
    exist, so ``capability_module_hash`` was recorded ``null``, and ``lifecycle_state.
    acceptance_hash_is_stale`` treats ``null`` as ALWAYS stale — an immediate, false re-flag right
    after a real, successful acceptance.

    This mirrors ``lifecycle_state.complete_migration``'s own fix for the identical bug
    (``lifecycle_state.py`` ~1120-1132): resolve the canonical id via ``capability_identity.
    build_capability_index(...).resolve(...)`` ONLY to derive the module-hash path — the raw
    ``capability_id`` is still what is passed to the ceremony as the target id (the descriptor
    lookup keys on the literal id, which for a split install IS the alias, never the canonical)."""

    PHASE = "phase_02"

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.security = self.tmp / "security"
        self.security.mkdir(parents=True, exist_ok=True)
        self.set_path = self.security / "capability_descriptors.json"
        self.proof_path = self.tmp / "proof.json"
        self.receipt_path = self.security / "acceptance_receipts" / "receipt.json"
        self.audit_path = self.security / "capability_acceptance_log.jsonl"
        self.capabilities_dir = self.tmp / "agents" / "capabilities"
        self.capabilities_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._td.cleanup()

    def _write_capability_module(self, module_stem, *, surface):
        source = (
            f'"""{module_stem} -- test fixture capability."""\n\n'
            f'SURFACE = "{surface}"\n\n\n'
            "def describe():\n    return \"ready\"\n"
        )
        path = self.capabilities_dir / f"{module_stem}_capability.py"
        path.write_text(source, encoding="utf-8")
        return path

    def _write_set(self, descriptors):
        self.set_path.write_text(json.dumps(descriptors, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")

    def _write_proof(self, capability_id):
        self.proof_path.write_text(json.dumps(_proof(capability_id=capability_id)),
                                   encoding="utf-8")

    def _accept_split_install(self, descriptor_id, module_stem, *, surface=None):
        module_path = self._write_capability_module(
            module_stem, surface=surface if surface is not None else descriptor_id)
        self._write_set([_descriptor(id=descriptor_id, phase_id=self.PHASE)])
        self._write_proof(descriptor_id)

        res = record_operator_acceptance(
            descriptor_id, self.PHASE, str(self.proof_path),
            "Yes — I accept this capability for live use.",
            receipt_path=str(self.receipt_path),
            descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path),
            project_root=str(self.tmp))
        return res, module_path

    def _latest_record(self):
        log_lines = [ln for ln in self.audit_path.read_text(encoding="utf-8").splitlines() if ln]
        return json.loads(log_lines[-1])

    # -- Estate shape #1: descriptor id "inbox-labels" / module "inbox_management" -------------

    def test_split_install_inbox_labels_case_records_real_hash_not_stale(self):
        res, module_path = self._accept_split_install("inbox-labels", "inbox_management")
        self.assertTrue(res.accepted, res.reason)

        # The ceremony must still be keyed on the RAW descriptor id (the alias) — never the
        # canonical — the descriptor lookup is by literal id, not canonical id.
        self.assertEqual(res.acceptance.capability_id, "inbox-labels")

        record = self._latest_record()
        self.assertEqual(record["capability_id"], "inbox-labels")
        expected_hash = hashlib.sha256(module_path.read_bytes()).hexdigest()
        self.assertEqual(record["capability_module_hash"], expected_hash,
                         "capability_module_hash must be the REAL module hash, not null")

        self.assertFalse(
            acceptance_hash_is_stale(str(self.tmp), "inbox_management",
                                     audit_log_path=str(self.audit_path)),
            "a real, undisturbed acceptance must not be immediately re-flagged stale")

    # -- Estate shape #2: a second, differently-named split install ----------------------------

    def test_split_install_second_capability_id_records_real_hash_not_stale(self):
        res, module_path = self._accept_split_install("crm-sync-alias", "acme_crm_connector")
        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(res.acceptance.capability_id, "crm-sync-alias")

        record = self._latest_record()
        expected_hash = hashlib.sha256(module_path.read_bytes()).hexdigest()
        self.assertEqual(record["capability_module_hash"], expected_hash)

        self.assertFalse(
            acceptance_hash_is_stale(str(self.tmp), "acme_crm_connector",
                                     audit_log_path=str(self.audit_path)))

    # -- Negative: a genuinely unresolvable (ambiguous) capability_id fails closed --------------

    def test_genuinely_unresolvable_capability_id_refuses_plain_language(self):
        # Two DIFFERENT capability modules declare the SAME surface as the capability_id under
        # test — a genuinely ambiguous identity resolution. This must fail closed with a plain-
        # language message (never a traceback), not guess a module path either way.
        self._write_capability_module("cap_alpha", surface="ambiguous_surface")
        self._write_capability_module("cap_beta", surface="ambiguous_surface")
        self._write_set([_descriptor(id="ambiguous_surface", phase_id=self.PHASE)])
        self._write_proof("ambiguous_surface")

        res = record_operator_acceptance(
            "ambiguous_surface", self.PHASE, str(self.proof_path),
            "Yes — I accept this capability for live use.",
            receipt_path=str(self.receipt_path),
            descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path),
            project_root=str(self.tmp))

        self.assertFalse(res.accepted)
        self.assertIsNotNone(res.reason)
        self.assertNotIn("Traceback", res.reason)
        self.assertIsNone(res.acceptance, "the ceremony must never be invoked on an ambiguous id")
        self.assertFalse(self.audit_path.exists())
        self.assertFalse(self.receipt_path.exists(), "nothing should be minted on a refusal")

    # -- Regression: a NON-split (ordinary) install still resolves via literal fallback --------

    def test_no_capabilities_dir_at_all_falls_back_to_literal_unaffected(self):
        # No capability module scaffolded at all under this project_root: capability_id is
        # unresolved (not ambiguous) and falls back to the literal id — the SAME behavior as
        # before this fix (matching accept_capability_for_live_use's own cwd-relative default
        # convention when nothing else is known).
        shutil.rmtree(self.capabilities_dir)
        self._write_set([_descriptor(id="google_sheets", phase_id=self.PHASE)])
        self._write_proof("google_sheets")

        res = record_operator_acceptance(
            "google_sheets", self.PHASE, str(self.proof_path),
            "Yes — I accept this capability for live use.",
            receipt_path=str(self.receipt_path),
            descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path),
            project_root=str(self.tmp))
        self.assertTrue(res.accepted, res.reason)
        record = self._latest_record()
        # No module file exists at the (fallback-literal) path — fail-safe null, never a refusal.
        self.assertIsNone(record["capability_module_hash"])


class PendingMigrationAutoCloseTest(unittest.TestCase):
    """Task 10 carry-forward from Task 9: a capability that migrates a mechanism
    upgrade-reconcile (Task 9) safe-paused closes that mechanism's
    pending_migrations.json entry the moment IT is actually accepted through this
    flow — by the documented id-matching convention (capability_id ==
    mechanism_id), never by a schema change to the pinned descriptor shape.

    Reuses the SAME fixture shapes as OperatorAcceptanceE2ETest (real proof,
    real descriptor set) rather than a separate ad hoc setUp — this is still a
    real end-to-end run through the ceremony, not a mock of it."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.security = self.tmp / "security"
        self.security.mkdir(parents=True, exist_ok=True)
        self.set_path = self.security / "capability_descriptors.json"
        self.proof_path = self.tmp / "proof.json"
        self.receipt_path = self.security / "acceptance_receipts" / "google_sheets.receipt.json"
        self.audit_path = self.security / "capability_acceptance_log.jsonl"

    def tearDown(self):
        self._td.cleanup()

    def _write_set(self, descriptors):
        self.set_path.write_text(json.dumps(descriptors, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")

    def _write_proof(self, proof=None):
        self.proof_path.write_text(json.dumps(proof if proof is not None else _proof()),
                                   encoding="utf-8")

    def _write_pending_migrations(self, entries):
        path = self.tmp / "pending_migrations.json"
        path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        return path

    def test_matching_entry_is_closed_on_real_acceptance(self):
        pm_path = self._write_pending_migrations([
            {"mechanism_id": "google_sheets", "writer_relpath": "agents/cron/x.py",
            "entrypoint_relpath": "agents/cron/run_x.sh", "violations": [],
            "suggested_next_step": "migrate via add-capability", "status": "pending"},
        ])
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof()

        res = record_operator_acceptance(
            "google_sheets", PHASE, str(self.proof_path),
            "Yes — I accept this capability for live use.",
            receipt_path=str(self.receipt_path), descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path), pending_migrations_path=str(pm_path))
        self.assertTrue(res.accepted, res.reason)

        remaining = json.loads(pm_path.read_text(encoding="utf-8"))
        self.assertEqual(remaining, [])

    def test_non_matching_entries_are_left_untouched(self):
        pm_path = self._write_pending_migrations([
            {"mechanism_id": "some_other_mechanism", "writer_relpath": "agents/cron/y.py",
            "entrypoint_relpath": "agents/cron/run_y.sh", "violations": [],
            "suggested_next_step": "migrate via add-capability", "status": "pending"},
        ])
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof()

        res = record_operator_acceptance(
            "google_sheets", PHASE, str(self.proof_path),
            "Yes — I accept this capability for live use.",
            receipt_path=str(self.receipt_path), descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path), pending_migrations_path=str(pm_path))
        self.assertTrue(res.accepted, res.reason)

        remaining = json.loads(pm_path.read_text(encoding="utf-8"))
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["mechanism_id"], "some_other_mechanism")

    def test_missing_queue_file_does_not_block_or_fail_acceptance(self):
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof()
        missing_path = str(self.tmp / "does_not_exist" / "pending_migrations.json")

        res = record_operator_acceptance(
            "google_sheets", PHASE, str(self.proof_path),
            "Yes — I accept this capability for live use.",
            receipt_path=str(self.receipt_path), descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path), pending_migrations_path=missing_path)
        self.assertTrue(res.accepted, res.reason)
        # Bookkeeping-only: no queue file materialized just because acceptance ran.
        self.assertFalse(Path(missing_path).exists())

    def test_helper_is_a_noop_on_refused_acceptance(self):
        # Refused (unconfirmed) acceptance must never touch the queue at all.
        pm_path = self._write_pending_migrations([
            {"mechanism_id": "google_sheets", "writer_relpath": "agents/cron/x.py",
            "entrypoint_relpath": "agents/cron/run_x.sh", "violations": [],
            "suggested_next_step": "migrate via add-capability", "status": "pending"},
        ])
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof()

        res = record_operator_acceptance(
            "google_sheets", PHASE, str(self.proof_path), "   ",
            receipt_path=str(self.receipt_path), descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path), pending_migrations_path=str(pm_path))
        self.assertFalse(res.accepted)

        remaining = json.loads(pm_path.read_text(encoding="utf-8"))
        self.assertEqual(len(remaining), 1)

    # -- Task A3 / F-60: the outcome is SURFACED on the full acceptance path, not just the
    #    bare bookkeeping helper in isolation. ANTI-OVERFIT: capability module written at the
    #    real emitted relpath (agents/capabilities/<id>_capability.py) inside a fresh tmp tree.

    def _write_capability_module(self, capability_id, *, surface):
        cap_dir = self.tmp / "agents" / "capabilities"
        cap_dir.mkdir(parents=True, exist_ok=True)
        source = (
            f'"""{capability_id} -- test fixture capability."""\n\n'
            f'SURFACE = "{surface}"\n\n\n'
            "def describe():\n    return \"ready\"\n"
        )
        (cap_dir / f"{capability_id}_capability.py").write_text(source, encoding="utf-8")

    def test_estate_split_stray_entry_closed_via_index_on_full_acceptance(self):
        # The estate shape, driven through the FULL acceptance ceremony (not just the bare
        # helper): accepted capability_id "google_sheets" declares SURFACE "gs-legacy-mechanism"
        # -- a STRAY pending-migration entry keyed by that surface (not the literal
        # capability_id) must still close via canonical resolution, and the outcome must be
        # observable on the returned OperatorAcceptanceResult, not silently swallowed.
        self._write_capability_module("google_sheets", surface="gs-legacy-mechanism")
        pm_path = self.tmp / "agents" / "handoffs" / "pending_migrations.json"
        pm_path.parent.mkdir(parents=True, exist_ok=True)
        pm_path.write_text(json.dumps([
            {"mechanism_id": "gs-legacy-mechanism", "writer_relpath": "agents/cron/x.py",
             "entrypoint_relpath": "agents/cron/run_x.sh", "violations": [],
             "suggested_next_step": "migrate via add-capability", "status": "pending"},
        ], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof()

        res = record_operator_acceptance(
            "google_sheets", PHASE, str(self.proof_path),
            "Yes — I accept this capability for live use.",
            receipt_path=str(self.receipt_path), descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path), pending_migrations_path=str(pm_path),
            project_root=str(self.tmp))
        self.assertTrue(res.accepted, res.reason)

        # Surfaced (Task A3 / F-60): the acceptance result itself carries the closure outcome.
        self.assertIsNotNone(res.migration_close)
        self.assertTrue(res.migration_close.closed, res.migration_close.unresolved_note)
        self.assertEqual(res.migration_close.closed_raw_ids, ("gs-legacy-mechanism",))
        remaining = json.loads(pm_path.read_text(encoding="utf-8"))
        self.assertEqual(remaining, [])

    def test_ambiguous_migration_id_surfaced_on_full_acceptance_not_silent_noop(self):
        # Two DIFFERENT capabilities share a surface -- a queued entry keyed by that shared
        # surface is genuinely ambiguous and must never silently read as "nothing to close".
        # The acceptance itself still succeeds (this is bookkeeping-only), but the returned
        # result must SURFACE the ambiguity.
        self._write_capability_module("google_sheets", surface="shared_surface")
        self._write_capability_module("other_capability", surface="shared_surface")
        pm_path = self.tmp / "agents" / "handoffs" / "pending_migrations.json"
        pm_path.parent.mkdir(parents=True, exist_ok=True)
        pm_path.write_text(json.dumps([
            {"mechanism_id": "shared_surface", "status": "pending"},
        ], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof()

        res = record_operator_acceptance(
            "google_sheets", PHASE, str(self.proof_path),
            "Yes — I accept this capability for live use.",
            receipt_path=str(self.receipt_path), descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path), pending_migrations_path=str(pm_path),
            project_root=str(self.tmp))
        self.assertTrue(res.accepted, res.reason)

        self.assertIsNotNone(res.migration_close)
        self.assertFalse(res.migration_close.closed)
        self.assertIsNotNone(
            res.migration_close.unresolved_note,
            "a genuinely-ambiguous migration id must be surfaced, not a silent no-op")
        remaining = json.loads(pm_path.read_text(encoding="utf-8"))
        self.assertEqual(len(remaining), 1, "the ambiguous entry must be left untouched")

    def test_uncorroborated_stray_entry_in_single_capability_project_not_deleted_and_surfaced(self):
        # CRITICAL regression (coordinator review round 2): the ROOT CAUSE was
        # capability_identity._build_name_alias_map's sole-candidate cardinality fallback --
        # with exactly ONE real capability and ONE unrelated, uncorroborated pending-migration
        # entry, the (removed) guess resolved the stray entry's mechanism_id to the sole
        # capability's canonical purely because it was the only one around, so accepting that
        # ONE real capability silently DELETED the totally-unrelated entry. Now: the entry must
        # NOT be closed, and the miss must be SURFACED (unresolved_note set), not a silent
        # no-op -- an operator must be able to see that a pending-migration entry exists that
        # this acceptance could not confidently account for.
        self._write_capability_module("google_sheets", surface="gs_surface_unused")
        pm_path = self.tmp / "agents" / "handoffs" / "pending_migrations.json"
        pm_path.parent.mkdir(parents=True, exist_ok=True)
        pm_path.write_text(json.dumps([
            {"mechanism_id": "totally_unrelated_mechanism", "status": "pending"},
        ], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self._write_set([_descriptor(id="google_sheets")])
        self._write_proof()

        res = record_operator_acceptance(
            "google_sheets", PHASE, str(self.proof_path),
            "Yes — I accept this capability for live use.",
            receipt_path=str(self.receipt_path), descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path), pending_migrations_path=str(pm_path),
            project_root=str(self.tmp))
        self.assertTrue(res.accepted, res.reason)

        self.assertIsNotNone(res.migration_close)
        self.assertFalse(
            res.migration_close.closed,
            "an unrelated, uncorroborated stray entry must never be deleted just because it is "
            "the only pending entry in a single-capability project")
        self.assertIsNotNone(
            res.migration_close.unresolved_note,
            "an uncorroborated stray migration entry must be surfaced, not a silent no-op")
        remaining = json.loads(pm_path.read_text(encoding="utf-8"))
        self.assertEqual(len(remaining), 1, "the unrelated entry must be left untouched")
        self.assertEqual(remaining[0]["mechanism_id"], "totally_unrelated_mechanism")


class ClosePendingMigrationHelperUnitTest(unittest.TestCase):
    """Direct unit coverage of close_pending_migration_if_matched's fail-soft
    behavior, independent of the full acceptance ceremony.

    Task A3 / F-60: the function now returns a ``MigrationCloseResult`` (not a bare bool) --
    every assertion here checks ``.closed`` explicitly (a dataclass instance is truthy
    regardless of its fields, so ``assertTrue``/``assertFalse`` directly on the return value
    would silently stop verifying anything). These fixtures deliberately build NO
    ``agents/capabilities`` tree, so the identity index resolves nothing and
    ``close_pending_migration_if_matched`` falls back to its pre-A1 literal-id comparison --
    the estate-split (canonical-resolution) path is covered separately below in
    ``ClosePendingMigrationIdentityResolutionTest``."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _path(self):
        return str(self.tmp / "pending_migrations.json")

    def test_matched_entry_removed_returns_true(self):
        p = self._path()
        Path(p).write_text(json.dumps([{"mechanism_id": "cap1"}]), encoding="utf-8")
        result = close_pending_migration_if_matched("cap1", p, project_root=str(self.tmp))
        self.assertTrue(result.closed)
        self.assertEqual(result.closed_raw_ids, ("cap1",))
        self.assertIsNone(result.unresolved_note)
        self.assertEqual(json.loads(Path(p).read_text(encoding="utf-8")), [])

    def test_no_match_returns_false_and_leaves_file_untouched(self):
        p = self._path()
        original = json.dumps([{"mechanism_id": "cap1"}])
        Path(p).write_text(original, encoding="utf-8")
        result = close_pending_migration_if_matched("cap2", p, project_root=str(self.tmp))
        self.assertFalse(result.closed)
        self.assertIsNone(result.unresolved_note)
        self.assertEqual(Path(p).read_text(encoding="utf-8"), original)

    def test_missing_file_returns_false(self):
        result = close_pending_migration_if_matched(
            "cap1", str(self.tmp / "nope.json"), project_root=str(self.tmp))
        self.assertFalse(result.closed)

    def test_malformed_json_returns_false(self):
        p = self._path()
        Path(p).write_text("{not json", encoding="utf-8")
        result = close_pending_migration_if_matched("cap1", p, project_root=str(self.tmp))
        self.assertFalse(result.closed)

    def test_non_list_body_returns_false(self):
        p = self._path()
        Path(p).write_text(json.dumps({"mechanism_id": "cap1"}), encoding="utf-8")
        result = close_pending_migration_if_matched("cap1", p, project_root=str(self.tmp))
        self.assertFalse(result.closed)

    def test_only_matching_entry_removed_among_several(self):
        p = self._path()
        Path(p).write_text(json.dumps([
            {"mechanism_id": "cap1"}, {"mechanism_id": "cap2"}, {"mechanism_id": "cap3"},
        ]), encoding="utf-8")
        result = close_pending_migration_if_matched("cap2", p, project_root=str(self.tmp))
        self.assertTrue(result.closed)
        self.assertEqual(result.closed_raw_ids, ("cap2",))
        remaining = json.loads(Path(p).read_text(encoding="utf-8"))
        self.assertEqual([e["mechanism_id"] for e in remaining], ["cap1", "cap3"])

    def test_default_path_constant(self):
        self.assertEqual(PENDING_MIGRATIONS_REL, "agents/handoffs/pending_migrations.json")


class ClosePendingMigrationIdentityResolutionTest(unittest.TestCase):
    """Task A3 -- the two behaviors this task adds to
    ``close_pending_migration_if_matched``: (1) F-60's headline fix, the estate-split
    canonical-id match; (2) an identity resolution that comes back AMBIGUOUS must be
    SURFACED via ``unresolved_note``, never a silent no-op.

    ANTI-OVERFIT: fixtures are written at the REAL emitted relpaths
    (``agents/capabilities/<id>_capability.py``) inside a fresh temp project tree built from
    scratch -- never a copytree of the dev tree (mirrors the v0.13.0 T7 / test_capability_health
    lesson already applied elsewhere in this package's test suites)."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.project_root = Path(self._td.name)
        self.capabilities_dir = self.project_root / "agents" / "capabilities"
        self.capabilities_dir.mkdir(parents=True, exist_ok=True)
        self.pending_path = self.project_root / "agents" / "handoffs" / "pending_migrations.json"
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._td.cleanup()

    def _write_capability(self, capability_id, *, surface=None):
        surface_line = f'SURFACE = "{surface}"\n' if surface else ""
        source = (
            f'"""{capability_id} -- test fixture capability."""\n\n{surface_line}\n'
            "def describe():\n    return \"ready\"\n"
        )
        (self.capabilities_dir / f"{capability_id}_capability.py").write_text(
            source, encoding="utf-8")

    def _write_pending(self, entries):
        self.pending_path.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def test_estate_split_stray_entry_closes_via_canonical_resolution(self):
        # The estate shape: module stem / accepted capability_id "inbox_management"; a STRAY
        # pending-migration entry keyed by the descriptor id "inbox-labels" (which
        # inbox_management's own module declares as its SURFACE -- corroborated resolution,
        # not a raw string match, since "inbox-labels" != "inbox_management").
        self._write_capability("inbox_management", surface="inbox-labels")
        self._write_pending([{"mechanism_id": "inbox-labels", "status": "pending"}])

        result = close_pending_migration_if_matched(
            "inbox_management", str(self.pending_path), project_root=str(self.project_root))

        self.assertTrue(result.closed, result.unresolved_note)
        self.assertEqual(result.closed_raw_ids, ("inbox-labels",))
        remaining = json.loads(self.pending_path.read_text(encoding="utf-8"))
        self.assertEqual(remaining, [])

    def test_unrelated_capability_present_does_not_cause_a_false_close(self):
        # A second, unrelated capability exists in the same project -- the estate-split
        # resolution must attribute the stray entry to the ONE capability that actually
        # corroborates it (via SURFACE), never to whichever capability happens to be accepted.
        self._write_capability("inbox_management", surface="inbox-labels")
        self._write_capability("asana_sync", surface="asana")
        self._write_pending([{"mechanism_id": "inbox-labels", "status": "pending"}])

        result = close_pending_migration_if_matched(
            "asana_sync", str(self.pending_path), project_root=str(self.project_root))

        self.assertFalse(result.closed)
        remaining = json.loads(self.pending_path.read_text(encoding="utf-8"))
        self.assertEqual(len(remaining), 1)

    def test_ambiguous_migration_id_is_surfaced_not_a_silent_noop(self):
        # Two DIFFERENT capabilities both declare the SAME surface -- a raw id that
        # corroborates via that surface is genuinely ambiguous (matches two canonicals). This
        # must never be silently treated as "no match" with zero signal: the F-60 fix requires
        # it to be surfaced via `unresolved_note`.
        self._write_capability("cap_alpha", surface="shared_surface")
        self._write_capability("cap_beta", surface="shared_surface")
        self._write_pending([{"mechanism_id": "shared_surface", "status": "pending"}])

        result = close_pending_migration_if_matched(
            "cap_alpha", str(self.pending_path), project_root=str(self.project_root))

        self.assertFalse(result.closed)
        self.assertIsNotNone(
            result.unresolved_note,
            "an ambiguous migration-queue identity must be surfaced, not a silent no-op")
        self.assertIn("shared_surface", result.unresolved_note)
        # Bookkeeping-only: the ambiguous entry is left untouched, never guessed at.
        remaining = json.loads(self.pending_path.read_text(encoding="utf-8"))
        self.assertEqual(len(remaining), 1)


def _copy_real_external_write_package(project_root: Path) -> Path:
    """Copy the REAL, committed external_write package (this task's
    registered_adapters.py included) into
    ``<project_root>/agents/lib/external_write/``, so a subprocess run of
    the ACTUAL ``operator_acceptance.py`` CLI against `project_root`
    exercises the real, shipped turnkey-acceptance machinery end to end --
    never a stand-in or a hand-simulated substitute."""
    dest = project_root / "agents" / "lib" / "external_write"
    shutil.copytree(_AGENTS_LIB / "external_write", dest)
    lib_init = _AGENTS_LIB / "__init__.py"
    if lib_init.is_file():
        shutil.copy(lib_init, project_root / "agents" / "lib" / "__init__.py")
    return dest


def _precompute_hashes(project_root: Path, op_kind: str) -> dict:
    """Compute the trust-hash canon for `op_kind` in a FRESH subprocess
    against the temp project's own copy of the package. This guarantees the
    values match EXACTLY what the CLI subprocess (below) will independently
    recompute: both run against the identical on-disk files, in unrelated
    Python processes, so there is no shared sys.modules cache to reason
    about (this test file already has the real dev-tree `external_write.*`
    cached under a DIFFERENT path from this test's own top-of-file imports;
    reusing that cache in-process for the temp copy's own op_kind would be
    unsound)."""
    script = (
        "import sys, json\n"
        "sys.path.insert(0, 'agents/lib')\n"
        "import external_write.registered_adapters\n"
        "from external_write.proof_hash import (\n"
        "    compute_contract_hash, compute_implementation_hash)\n"
        f"op_kind = {op_kind!r}\n"
        "print(json.dumps({'contract_hash': compute_contract_hash(op_kind),\n"
        "                   'implementation_hash': compute_implementation_hash(op_kind)}))\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=str(project_root),
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"hash precompute subprocess failed: {result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


class TurnkeyAcceptanceCLIE2ETest(unittest.TestCase):
    """Task 7 (A4 / F-37) — the emitted e2e smoke test the task brief's spec
    item 3 calls for: declare a FRESH (non-Gmail, never-before-registered)
    op_kind with a real, capability-code-scaffold-emitted adapter module,
    confirm it lands in registered_adapters.py, then run the
    operator-acceptance CLI VERBATIM AS DOCUMENTED in skills/next-phase.md's
    Step 6 (a subprocess of agents/lib/external_write/operator_acceptance.py
    from the project root, the exact argument shape that file prescribes) --
    must succeed turnkey and mint a receipt, with NO hand-import of the
    adapter module anywhere in this test's CLI invocation. This is the RED ->
    GREEN proof for Task 7: before the fix, this exact invocation refused
    with "no registered contract" for any freshly-declared capability."""

    CAPABILITY_ID = "fixture_e2e_cap"
    OP_KIND = "fixture_e2e.record.set_status"
    PHASE = "phase_e2e"

    def setUp(self):
        self._td = TemporaryDirectory()
        self.project_root = Path(self._td.name)
        self.external_write_dir = _copy_real_external_write_package(self.project_root)

        spec = CapabilityCodeSpec(
            capability_id=self.CAPABILITY_ID,
            display_name="Fixture e2e capability",
            op_kind=self.OP_KIND,
            surface="fixture_e2e_surface",
            read_only_scope="fixture_e2e.readonly",
            blast_radius_cap=10,
            risk_class="sensitive_data",
            writes=("Status",),
            read_methods=("list_items", "get_item"),
            verifier_set=("prestate_snapshot_diff_v1",),
        )
        written = emit_capability_code_scaffold(spec, self.project_root)
        (self.adapter_path, self.read_facade_path, self.capability_path,
         self.registry_path, self.registered_adapters_path) = written

        # The scaffold's emitted adapter is a structural STUB (plan/apply_one/
        # undo_one/verify_one only -- see capability_code_scaffold.py's own
        # module docstring: "the actual per-vendor call shape" is a later,
        # human TODO). copy_run_proof.validate_copy_run_proof fail-closes on
        # ANY registered-adapter op_kind with no evidence predicate (Task 1,
        # B4/T1) -- a real capability build would fill these in against the
        # real vendor semantics before its first copy-run proof; this test
        # does the same minimal fill-in (not a scaffold change; out of scope
        # for Task 7) so the e2e proof can validate.
        adapter_text = self.adapter_path.read_text(encoding="utf-8")
        class_name = f"{spec.class_prefix}Adapter"
        fill_in = (
            f"\n\ndef _{spec.capability_id}_verify_apply_landed(self, evidence):\n"
            "    return True\n\n\n"
            f"def _{spec.capability_id}_verify_undo_restored(self, evidence):\n"
            "    return True\n\n\n"
            f"{class_name}.verify_apply_landed = _{spec.capability_id}_verify_apply_landed\n"
            f"{class_name}.verify_undo_restored = _{spec.capability_id}_verify_undo_restored\n\n\n"
        )
        marker = f"register_adapter(OP_KIND, {class_name}())"
        self.assertIn(marker, adapter_text)
        adapter_text = adapter_text.replace(marker, fill_in.strip("\n") + "\n" + marker)
        self.adapter_path.write_text(adapter_text, encoding="utf-8")

        self.security_dir = self.project_root / "security"
        self.security_dir.mkdir(parents=True, exist_ok=True)
        self.descriptor_set_path = self.security_dir / "capability_descriptors.json"
        self.proof_path = (self.project_root / "agents" / "handoffs"
                          / f"{self.CAPABILITY_ID}.copy_run_proof.json")
        self.proof_path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._td.cleanup()

    def test_fresh_op_kind_lands_in_the_generated_registry(self):
        # Spec item 1/3: "ensure it's in the registry" -- both the shipped
        # Gmail baseline AND the fresh capability's own import are present.
        content = self.registered_adapters_path.read_text(encoding="utf-8")
        self.assertIn("import external_write.adapters_gmail", content)
        self.assertIn(f"import external_write.{self.adapter_path.stem}", content)

    def _write_descriptor_and_proof(self):
        hashes = _precompute_hashes(self.project_root, self.OP_KIND)

        descriptor = {
            "id": self.CAPABILITY_ID, "name": self.CAPABILITY_ID,
            "action_class": "update", "risk_class": "sensitive_data",
            "recovery_profile_ref": None, "declared_test_target": "copy",
            "blast_radius_cap": 10, "accepted": False, "phase_id": self.PHASE,
        }
        self.descriptor_set_path.write_text(
            json.dumps([descriptor], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        proof = {
            "schema": COPY_RUN_PROOF_SCHEMA,
            "operation_id": "op-e2e-001",
            "op_kind": self.OP_KIND,
            "capability_id": self.CAPABILITY_ID,
            "data_class": "fixture_e2e_rows",
            "copy_source_ref": "copies/fixture_e2e_copy.csv",
            "prestate_snapshot_ref": "copies/fixture_e2e_copy.prestate.csv",
            "copy_apply_proof": {
                "apply_receipt_ref": "agents/handoffs/.apply_receipt.json",
                "apply_verification": _verification(),
                "apply_evidence": {"unit_id": "row-1", "poststate": {"value": "Done"}},
            },
            "copy_undo_proof": {
                "undo_receipt_ref": "agents/handoffs/.undo_receipt.json",
                "undo_verification": _verification(),
                "undo_evidence": {"unit_id": "row-1", "poststate": {"value": "Todo"}},
            },
            "durability_checks": [],
            "accepted_for_live_use": True,
            "implementation_hash": hashes["implementation_hash"],
            "contract_hash": hashes["contract_hash"],
            # Invariant 7 (wire-verification): the CAPABILITY's own
            # write-affecting module, never the trusted adapter module.
            "capability_module_paths": [str(self.capability_path.resolve())],
        }
        self.proof_path.write_text(json.dumps(proof), encoding="utf-8")

    def _run_cli(self):
        # The EXACT documented invocation shape (skills/next-phase.md, Step
        # 6) -- a fresh subprocess, run from the project root, with no
        # PYTHONPATH and no hand-import of any adapter module by this test.
        cli_path = self.external_write_dir / "operator_acceptance.py"
        return subprocess.run(
            [sys.executable, str(cli_path),
             "--capability-id", self.CAPABILITY_ID,
             "--phase-id", self.PHASE,
             "--copy-run-proof", str(self.proof_path),
             "--operator-confirmation",
             "Yes -- I accept this capability for live use."],
            cwd=str(self.project_root), capture_output=True, text=True,
        )

    def test_cli_verbatim_as_documented_succeeds_turnkey(self):
        self._write_descriptor_and_proof()
        result = self._run_cli()
        self.assertEqual(
            result.returncode, 0,
            msg=f"CLI refused turnkey acceptance for a fresh op_kind -- "
                f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertIn("ACCEPTED", result.stdout)

        receipt_path = (self.security_dir / "acceptance_receipts"
                       / f"{self.CAPABILITY_ID}.receipt.json")
        self.assertTrue(receipt_path.is_file(), "acceptance must mint a receipt")

        entries = json.loads(self.descriptor_set_path.read_text(encoding="utf-8"))
        self.assertTrue(entries[0]["accepted"])

        # IMPORTANT fix (coordinator review round 2): a normal, clean acceptance with nothing
        # to surface about the pending-migration queue must stay quiet at the CLI -- no spurious
        # "NOTE:" line.
        self.assertNotIn("NOTE:", result.stdout)

    def test_cli_prints_surfaced_migration_close_note_on_success(self):
        # IMPORTANT fix (coordinator review round 2): operator_acceptance.py's __main__
        # populated OperatorAcceptanceResult.migration_close but never printed it --
        # wizard/skills/next-phase.md Step 6 invokes exactly this CLI and only sees the
        # ACCEPTED/REFUSED line + exit code, so a real operator would never see a surfaced
        # mismatch. A single real capability + an unrelated, uncorroborated stray
        # pending-migration entry must print a NOTE line on an otherwise-successful acceptance.
        self._write_descriptor_and_proof()
        pm_path = self.project_root / "agents" / "handoffs" / "pending_migrations.json"
        pm_path.parent.mkdir(parents=True, exist_ok=True)
        pm_path.write_text(json.dumps([
            {"mechanism_id": "totally_unrelated_mechanism", "status": "pending"},
        ], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        result = self._run_cli()
        self.assertEqual(
            result.returncode, 0,
            msg=f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertIn("ACCEPTED", result.stdout)
        self.assertIn("NOTE:", result.stdout)
        self.assertIn("totally_unrelated_mechanism", result.stdout)

        # The unrelated entry itself must still not have been deleted.
        remaining = json.loads(pm_path.read_text(encoding="utf-8"))
        self.assertEqual(len(remaining), 1)


if __name__ == "__main__":
    unittest.main()
