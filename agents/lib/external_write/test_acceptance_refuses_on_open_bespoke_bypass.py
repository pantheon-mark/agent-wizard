"""Task C / Cut 1.5 (bundle v0.19.0) -- live-enable-only acceptance gate.

Task A (KEYSTONE) makes an OPEN bespoke-writer entry block the whole project
non-green; Task B reaps such an entry once the writer is genuinely fixed. Task C
is the acceptance-time enforcement: BEFORE the ceremony flips ``accepted:true``,
``record_operator_acceptance`` REFUSES to live-enable a capability while ANY open
bespoke-writer bypass exists in the project (attribution-free -- it fires on the
mere existence of an open entry, regardless of which capability it belongs to).

The gate sits AHEAD of the atomic flip, so a refusal leaves NO partial state:
``accepted`` stays False, no receipt is minted, no acceptance record is written.
This ordering IS the anti-deadlock property -- edit/scan/prove/repair are never
blocked (they do not run through this helper), so repair is always available
while the capability is paused. Once Task B reaps the entry (writer fixed -> gone
from the queue), the SAME acceptance call succeeds.

Run:  python3 -m unittest discover -s wizard/agents/lib/external_write \\
          -p test_acceptance_refuses_on_open_bespoke_bypass.py
"""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_EXTERNAL_WRITE_DIR = Path(__file__).resolve().parent
_AGENTS_LIB = _EXTERNAL_WRITE_DIR.parent  # agents/lib -- external_write is a package under here
if str(_AGENTS_LIB) not in sys.path:
    sys.path.insert(0, str(_AGENTS_LIB))
_WIZARD_DIR = _EXTERNAL_WRITE_DIR.parents[2]  # .../wizard

# Name-form imports (NOT the dotted-submodule form): the whole-package bypass scan
# (test_external_write_scan) asserts every .py under this dir -- test files included -- is
# violation-free, and the dotted-submodule form trips the CAPABILITY-zone sealed_kernel_import
# rule. Every other test file in this dir uses the same name form for the same reason.
from external_write import operator_acceptance  # noqa: E402
from external_write import acceptance_ceremony  # noqa: E402
from external_write import copy_run_proof  # noqa: E402
from external_write import verifiers  # noqa: E402
from external_write import proof_hash  # noqa: E402
from external_write import scan  # noqa: E402
from external_write import state_actions  # noqa: E402
from external_write import writer_acknowledgement  # noqa: E402
from external_write import _ext_write_state  # noqa: E402

record_operator_acceptance = operator_acceptance.record_operator_acceptance
OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA = acceptance_ceremony.OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA
COPY_RUN_PROOF_SCHEMA = copy_run_proof.COPY_RUN_PROOF_SCHEMA
POSTWRITE_VERIFICATION_SCHEMA = verifiers.POSTWRITE_VERIFICATION_SCHEMA

PHASE = "phase_02"
OP_KIND = "delete_record"  # irreversible_external; gated; non-binding
CAP_ID = "google_sheets"

# The estate's real shape: a hand-rolled bulk runner OUTSIDE agents/capabilities/, keyed on a
# relpath-derived mechanism_id with no owning capability -- an OPEN bespoke-writer bypass.
BESPOKE_WRITER_RELPATH = "agents/inbox/runner.py"


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


def _proof(capability_id=CAP_ID, op_kind=OP_KIND):
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
        "implementation_hash": proof_hash.compute_implementation_hash(op_kind),
        "contract_hash": proof_hash.compute_contract_hash(op_kind),
        # A real, clean, on-disk capability module fixture (the same one the scanner test suite
        # proves scans to zero violations).
        "capability_module_paths": [str(
            _WIZARD_DIR / "test_fixtures" / "external_write_scan" / "legal_through_adapter.py"
        )],
    }


def _descriptor(id=CAP_ID, *, risk_class="irreversible_external", phase_id=PHASE,
                blast_radius_cap=5, accepted=False, action_class="delete"):
    return {
        "id": id, "name": id, "action_class": action_class, "risk_class": risk_class,
        "recovery_profile_ref": None, "declared_test_target": "copy",
        "blast_radius_cap": blast_radius_cap, "accepted": accepted, "phase_id": phase_id,
    }


class AcceptanceRefusesOnOpenBespokeBypassTest(unittest.TestCase):
    """The Task-C gate, end to end through the real ceremony (no mocks of the unit under test).

    project_root is the temp tree so ``open_bespoke_writer_migrations(root)`` reads THIS test's
    controlled ``agents/handoffs/pending_migrations.json`` -- with no ``agents/capabilities``
    tree the identity index falls back to the literal id (the pre-A1 no-capabilities case),
    exactly like ``test_no_capabilities_dir_at_all_falls_back_to_literal_unaffected``."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.security = self.tmp / "security"
        self.security.mkdir(parents=True, exist_ok=True)
        self.set_path = self.security / "capability_descriptors.json"
        self.proof_path = self.tmp / "proof.json"
        self.receipt_path = self.security / "acceptance_receipts" / f"{CAP_ID}.receipt.json"
        self.audit_path = self.security / "capability_acceptance_log.jsonl"
        # The open-bespoke-writer gate reads the queue at the project-root-relative default
        # location (agents/handoffs/pending_migrations.json), NOT the pending_migrations_path
        # kwarg (that param feeds only the best-effort close_pending_migration_if_matched tidy).
        self.queue_path = self.tmp / "agents" / "handoffs" / "pending_migrations.json"
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)

        self.set_path.write_text(
            json.dumps([_descriptor()], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.proof_path.write_text(json.dumps(_proof()), encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def _write_open_bespoke_queue(self):
        self.queue_path.write_text(json.dumps([
            {"mechanism_id": "runner", "writer_relpath": BESPOKE_WRITER_RELPATH,
             "entrypoint_relpath": "agents/inbox/run_runner.sh", "violations": ["bespoke bulk"],
             "suggested_next_step": "migrate via add-capability",
             "paused_content_sha256": "deadbeef", "status": "pending"},
        ], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _call(self, operator_confirmation="Yes -- I accept this capability for live use."):
        return record_operator_acceptance(
            CAP_ID, PHASE, str(self.proof_path), operator_confirmation,
            receipt_path=str(self.receipt_path),
            descriptor_set_path=str(self.set_path),
            audit_log_path=str(self.audit_path),
            project_root=str(self.tmp))

    def _accepted_flag(self):
        for e in json.loads(self.set_path.read_text(encoding="utf-8")):
            if e.get("id") == CAP_ID:
                return e.get("accepted")
        return None

    # -- Cut 1.6: the gate now blocks on the BLOCKING SUBSET, not every open entry ---------------

    def _write_queue(self, entries):
        self.queue_path.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _write_file(self, relpath, text):
        p = self.tmp / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def test_non_live_test_module_entry_does_not_block_acceptance(self):
        """Cut 1.6 / Task 2. A test module is not a live write path. Before this
        cut its presence in the queue blocked acceptance for the ENTIRE project
        forever (4 of the estate's 7 real entries were exactly this). It must
        still be VISIBLE, but it must not block."""
        self._write_file(
            "agents/inbox/test_inbox_bulk.py",
            "import unittest\n"
            "from external_write.adapters_inbox import InboxAdapter\n\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_x(self):\n        self.assertTrue(InboxAdapter)\n")
        self._write_queue([{
            "mechanism_id": "agents_inbox_test_inbox_bulk",
            "writer_relpath": "agents/inbox/test_inbox_bulk.py",
            "status": "pending",
            "paused_content_sha256": "deadbeef",
            "violations": [{"kind": "sealed_kernel_import", "line": 2,
                            "path": "agents/inbox/test_inbox_bulk.py"}],
        }])

        res = self._call()

        self.assertTrue(res.accepted,
                        f"a non-live test module must not block acceptance: {res.reason}")
        self.assertTrue(self._accepted_flag())

    def test_needs_person_entry_still_refuses_and_names_the_person_path(self):
        """THE GUARD (see _ext_write_state's Task 1 section). A live writer whose
        violations our remediator cannot fix stays BLOCKING -- letting it through
        silently would re-open F-VAL18-1. The refusal must also stop telling a
        non-technical operator to 'rebuild it', which is the dead end that
        stalled the real estate (F-VAL19-1): it must name the acknowledgement
        path instead."""
        self._write_file(
            "agents/upkeep/runner.py",
            '"""Daily upkeep."""\nimport urllib.request\n')
        self._write_queue([{
            "mechanism_id": "agents_upkeep_runner",
            "writer_relpath": "agents/upkeep/runner.py",
            "status": "pending",
            "paused_content_sha256": "deadbeef",
            "violations": [{"kind": "forbidden_import", "line": 2,
                            "path": "agents/upkeep/runner.py"}],
        }])

        res = self._call()

        self.assertFalse(res.accepted, "a needs-a-person writer must still refuse live-enable")
        self.assertFalse(self._accepted_flag())
        self.assertIn("agents/upkeep/runner.py", res.reason)
        reason = res.reason.lower()
        self.assertTrue(
            "acknowledge" in reason or "cannot be fixed automatically" in reason,
            f"refusal must name the person/acknowledgement path, not just 'rebuild it': {res.reason}")

    # -- Part 1: an OPEN bespoke-writer entry present -> live-enable REFUSED, no partial state ---

    def test_open_bespoke_bypass_refuses_live_enable_with_no_partial_state(self):
        self._write_open_bespoke_queue()

        res = self._call()

        # Refused (never live-enabled).
        self.assertFalse(res.accepted, "an open bespoke-writer bypass must refuse live-enable")
        # The refusal names the specific writer path + the rebuild next step.
        self.assertIsNotNone(res.reason)
        self.assertIn(BESPOKE_WRITER_RELPATH, res.reason)
        self.assertIn("bypass", res.reason)
        self.assertIn("re-run acceptance", res.reason)
        self.assertNotIn("Traceback", res.reason)
        # The ceremony was never even invoked -- the gate is AHEAD of the atomic flip.
        self.assertIsNone(res.acceptance)
        # NO inconsistent state on the refusal path: accepted stays False, no receipt, no record.
        self.assertEqual(self._accepted_flag(), False)
        self.assertIsNone(res.receipt_ref)
        self.assertFalse(self.receipt_path.exists(), "a refusal must mint no receipt")
        self.assertFalse(self.audit_path.exists(), "a refusal must write no acceptance record")

    # -- Kind-aware rendering: a queue entry that is NOT a bespoke-writer bypass must not be
    # described as one, even though it still refuses live-enable exactly like a real bypass ------

    def _write_reconcile_incomplete_queue(self):
        """The shape ``upgrade_reconcile.record_reconcile_incomplete`` writes when the upgrade
        safety check itself could not finish. Its ``writer_relpath`` deliberately points at the
        pending-migrations queue file itself (so the non-empty-``writer_relpath`` blocking
        predicate still fires on it) -- it is not a bespoke writer to rebuild."""
        self._write_queue([{
            "mechanism_id": "upgrade_safety_check",
            "writer_relpath": "agents/handoffs/pending_migrations.json",
            "entrypoint_relpath": None,
            "from_version": "v0.20.0",
            "to_version": "v0.21.0",
            "kind": "reconcile_incomplete",
            "reason": (
                "the upgrade safety check could not finish, so this project has not "
                "been confirmed safe to run (RuntimeError)"),
            "suggested_next_step": (
                "Ask your assistant to run `wizard reconcile`. That re-runs the same "
                "safety check against what is installed now. This entry clears by "
                "itself once the check completes."),
            "status": "pending",
        }])

    def test_a_reconcile_incomplete_marker_still_refuses_but_speaks_for_itself(self):
        """The marker's ``writer_relpath`` is the queue file, not a writer -- describing it with
        the generic bypass sentence ("rebuild it so it routes through the sanctioned bulk path")
        would tell the operator to do something meaningless. It must still refuse (blocking is
        unaffected by kind), but the refusal must carry the entry's own next step instead."""
        self._write_reconcile_incomplete_queue()

        res = self._call()

        self.assertFalse(res.accepted,
                         "an incomplete upgrade safety check must still refuse live-enable")
        self.assertNotIn("routes through the sanctioned bulk path", res.reason)
        self.assertNotIn("an external-write bypass is unrepaired", res.reason)
        self.assertIn("wizard reconcile", res.reason)
        self.assertNotIn("Traceback", res.reason)
        self.assertIsNone(res.acceptance)
        self.assertEqual(self._accepted_flag(), False)

    def test_a_genuine_bypass_entrys_wording_is_unchanged(self):
        """Regression guard for the fix above: a REAL bespoke-writer bypass entry (no ``kind``
        field at all -- see ``upgrade_reconcile._append_migration_request``) must keep the exact
        rebuild wording it has always had; the kind-aware split must not touch this path."""
        self._write_open_bespoke_queue()

        res = self._call()

        self.assertFalse(res.accepted)
        self.assertIn(
            "an external-write bypass is unrepaired: `agents/inbox/runner.py` "
            "-- rebuild it so it routes through the sanctioned bulk path",
            res.reason)

    # -- Part 2: writer fixed + entry reaped away -> the SAME call now SUCCEEDS -----------------

    def test_after_reap_same_call_succeeds(self):
        # Simulate Task B reaping the resolved entry (writer fixed -> gone from the queue). The
        # anti-deadlock property: with the bypass cleared, the identical acceptance call now
        # live-enables the capability -- repair was always available while it was paused.
        self.queue_path.write_text(json.dumps([]) + "\n", encoding="utf-8")

        res = self._call()

        self.assertTrue(res.accepted, res.reason)
        self.assertEqual(self._accepted_flag(), True)
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema"], OPERATOR_ACCEPTANCE_RECEIPT_SCHEMA)
        self.assertEqual(receipt["capability_id"], CAP_ID)

    # -- Fail-closed: an unreadable queue is a REFUSAL (cannot verify safety) --------------------

    def test_unreadable_queue_fails_closed_to_refusal(self):
        # An EXISTING-but-malformed queue must NEVER fall through to acceptance (the exact false
        # green this whole cut closes). open_bespoke_writer_migrations raises
        # ExternalWriteStateReadError; the gate treats that raise as a refusal, plain-language,
        # never a crash and never a live-enable.
        self.queue_path.write_text("{ not valid json", encoding="utf-8")

        res = self._call()

        self.assertFalse(res.accepted, "an unreadable queue must fail closed to a refusal")
        self.assertIsNotNone(res.reason)
        self.assertNotIn("Traceback", res.reason)
        self.assertIsNone(res.acceptance)
        self.assertEqual(self._accepted_flag(), False)
        self.assertFalse(self.receipt_path.exists())
        self.assertFalse(self.audit_path.exists())

    # -- The refusal ADVERTISES the way out, and it renders it from ONE place ------------------

    def test_the_needs_person_refusal_names_the_exact_command(self):
        """The original finding, closed at the surface that advertises the route.
        This refusal has always told the operator they may "record that you accept
        the risk" -- and named no way to do it. A route nothing names is a route only
        someone who already knew to look can take, which is the same shape as no
        route at all."""
        self._write_file(
            "agents/upkeep/runner.py",
            '"""Daily upkeep -- also delivers the phone alert."""\n'
            "import urllib.request\n")
        self._write_queue([{
            "mechanism_id": "agents_upkeep_runner",
            "writer_relpath": "agents/upkeep/runner.py",
            "status": "pending",
            "paused_content_sha256": "deadbeef",
            "violations": [{"kind": "forbidden_import", "line": 2,
                            "path": "agents/upkeep/runner.py"}],
        }])

        res = self._call()

        self.assertFalse(res.accepted)
        self.assertIn("cannot be fixed automatically and needs a person", res.reason)
        self.assertIn(
            writer_acknowledgement.acknowledgement_command("agents/upkeep/runner.py"),
            res.reason,
            f"the surface that advertises the route must NAME the command: {res.reason}")
        self.assertNotIn("Traceback", res.reason)

    def test_the_rebuildable_refusal_names_the_check_that_confirms_it(self):
        """Unchanged sentence, now with the command that confirms the rebuild
        actually landed -- the entry clears on its own once that check passes, so an
        operator who cannot run the check cannot tell whether they are done."""
        self._write_open_bespoke_queue()

        res = self._call()

        self.assertFalse(res.accepted)
        self.assertIn(scan.scan_command(BESPOKE_WRITER_RELPATH), res.reason)

    def test_the_refusal_is_rendered_by_the_state_action_registry(self):
        """Not "text that happens to match": the exact string the registry renders.
        The wording used to exist here AND in the writer-state core, and the copies
        drifted -- one of them naming a repair the other did not."""
        self._write_open_bespoke_queue()

        res = self._call()

        self.assertIn(
            state_actions.instruction_for_state(
                state_actions.writer_state_key(
                    _ext_write_state.WriterState.BLOCKING_LIVE_ENABLE),
                BESPOKE_WRITER_RELPATH),
            res.reason)

    def test_a_blocking_state_nobody_classified_is_not_told_to_rebuild_it(self):
        """The `else`-catch-all's real consequence, driven rather than argued.

        The split used to read `needs_person if state == NEEDS_PERSON else
        rebuildable`, so a blocking state added to the vocabulary later would be
        handed the rebuild instruction by nobody having thought about it -- on the
        very surface that advertises the accept-the-risk route. It now classifies by
        POSITIVE membership, and anything else routes to a person."""
        self._write_open_bespoke_queue()
        original = operator_acceptance.classify_bespoke_writer_entry
        try:
            operator_acceptance.classify_bespoke_writer_entry = (
                lambda root, entry: "invented_blocking_state")
            res = self._call()
        finally:
            operator_acceptance.classify_bespoke_writer_entry = original

        self.assertFalse(res.accepted, "it must still refuse")
        self.assertNotIn("rebuild it so it routes through the sanctioned bulk path",
                         res.reason)
        self.assertIn("ask your assistant", res.reason.lower())
        self.assertIn(BESPOKE_WRITER_RELPATH, res.reason)
        self.assertEqual(self._accepted_flag(), False)

    def test_a_classifier_that_RAISES_routes_to_a_person_not_to_a_rebuild(self):
        """An entry the classifier cannot classify at all. It used to be ASSIGNED
        `blocking_live_enable` and handed the rebuild instruction -- an inference
        from a failure, on the surface that advertises the accept-the-risk route,
        and the last permissive-direction assignment left after the `else`-catch-all
        was removed. It must still refuse (the block direction was never in doubt)
        and it must route to a person."""
        self._write_open_bespoke_queue()
        original = operator_acceptance.classify_bespoke_writer_entry

        def _raises(root, entry):
            raise RuntimeError("the classifier could not read the writer")

        try:
            operator_acceptance.classify_bespoke_writer_entry = _raises
            res = self._call()
        finally:
            operator_acceptance.classify_bespoke_writer_entry = original

        self.assertFalse(res.accepted, "it must still refuse")
        self.assertEqual(self._accepted_flag(), False)
        self.assertNotIn("rebuild it so it routes through the sanctioned bulk path",
                         res.reason)
        self.assertIn("ask your assistant", res.reason.lower())
        self.assertIn(BESPOKE_WRITER_RELPATH, res.reason)
        self.assertNotIn("Traceback", res.reason)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
