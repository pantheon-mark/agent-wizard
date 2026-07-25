"""Task F / Cut 1.5 (bundle v0.19.0) -- CONSOLIDATED ship-criteria regression fixtures.

These are the acceptance proof of the whole cut: they prove "V15-3 is closed". Each of Tasks
A-E (landed on this branch, all committed) closes one slice of the false green documented in
F-VAL18-1 (source-verified): an operator project could carry an OPEN "bespoke writer" migration
entry -- a hand-rolled per-chunk bulk loop that bypasses the sanctioned ``run_sanctioned_bulk``
path -- while ``check_completion`` / ``capability_health.overall_status`` / ``record_operator_
acceptance`` all reported green/done/accepted anyway, because the entry was keyed on a
relpath-derived ``mechanism_id`` with no owning-capability field and was structurally invisible
to every id-keyed safety view.

This module encodes the 4 STRUCTURAL locked ship criteria from the findings doc / Cut 1.5 plan
(``docs/superpowers/plans/2026-07-25-cut1.5-acceptance-linkage-false-green.md``, Task F) as
explicit, self-contained end-to-end tests. Each test is built to be genuinely falsifiable: the
report accompanying this file states, per test, the ONE assertion that would flip if the
corresponding Task A-E guard were removed or weakened.

  1. false-green closed            -- ``test_criterion1_open_bespoke_writer_blocks_completion_health_and_acceptance``
  2. deletion path                 -- ``test_criterion2_deleting_writer_autoreaps_and_acceptance_succeeds``
  3. unlinked fallback             -- ``test_criterion3_unattributable_writer_still_forces_global_red``
  4. quarantine can't launder      -- ``test_criterion4_quarantine_cannot_launder_completion``

Criterion 5 (EMPIRICAL -- the durable-ledger assertion: ONE ``run_id``/consent/WAL, multiple
chunks written UNDER that one envelope, on the real rebuilt writer) is NOT a build-time fixture.
It requires a real adapter/vendor surface and a real multi-chunk bulk run to observe the ledger
shape empirically; that is out of reach for a stdlib-only, no-network unit test. It is proven in
the Cut 1.5 re-validation runbook on a real estate project (kept in the build repo's private
review area, Task F Step 5 of the plan above), not here. See the deliberately
skipped placeholder at the bottom of this file.

Fixture discipline (ANTI-OVERFIT, matching every Task A-E test module): every fixture reuses the
REAL, full-ceremony helpers those modules already established --
``test_lifecycle_state._CheckCompletionFixtureMixin._accept_real_capability`` (a genuinely
accepted, otherwise-clean capability via the real ``acceptance_ceremony`` flow) and
``test_acceptance_refuses_on_open_bespoke_bypass``'s real descriptor/proof fixtures (a genuinely
valid, not-yet-accepted capability that would otherwise be accepted by ``record_operator_
acceptance``) -- never a hand-authored accepted/audit stand-in. Every "open bespoke-writer bypass"
fixture puts a real writer FILE on disk (not just a queue entry), matching the estate's actual
shape (``agents/inbox/runner.py``).

Run:  python3 -m unittest discover -s wizard/agents/lib/external_write \\
          -p test_v15_3_ship_criteria.py
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

_EXTERNAL_WRITE_DIR = Path(__file__).resolve().parent
_AGENTS_LIB = _EXTERNAL_WRITE_DIR.parent  # agents/lib -- external_write is a package under here
_SCRIPTS_LIB = _EXTERNAL_WRITE_DIR.parents[2] / "scripts" / "lib"  # wizard/scripts/lib
for _p in (str(_EXTERNAL_WRITE_DIR), str(_AGENTS_LIB), str(_SCRIPTS_LIB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Name-form imports (NOT the dotted-submodule form): every other test file in this dir uses this
# convention so the whole-package bypass scan (test_external_write_scan.test_allowed_module_
# code_is_exempt, which scans this ENTIRE directory including test files) never trips on a test
# file's own imports.
from external_write import lifecycle_state  # noqa: E402
from external_write import capability_health  # noqa: E402
from external_write import operator_acceptance  # noqa: E402
from external_write import _ext_write_state as _state  # noqa: E402
from external_write import scan as _scan  # noqa: E402

# Reuse the REAL full-ceremony fixture mixin (genuinely accepted capability + genuine audit
# record) -- the SAME reuse test_completion_global_bespoke_block.py / test_owning_capability_
# advisory.py already establish. Never a hand-authored accepted/audit stand-in.
import test_lifecycle_state as _ls_fixtures  # noqa: E402

# Sibling Task A-E test modules in THIS directory, imported (module-alias form only -- see note
# below) so their fixture helpers are reused rather than re-authored.
import test_completion_global_bespoke_block as _completion_fixtures  # noqa: E402
import test_writer_migration_autoreap as _reap_fixtures  # noqa: E402
import test_acceptance_refuses_on_open_bespoke_bypass as _acc_fixtures  # noqa: E402
import test_owning_capability_advisory as _owner_fixtures  # noqa: E402

# NOTE on the four imports directly above: each is bound ONLY to a module-level alias
# (``import x as y``), never ``from x import SomeTestCase`` -- that keeps every TestCase class
# defined in those sibling files out of THIS module's own namespace, so unittest's
# loadTestsFromModule (invoked via ``-p test_v15_3_ship_criteria.py``, which matches only this
# file) does not accidentally re-collect and re-run their test classes a second time under this
# module. This mirrors how test_completion_global_bespoke_block.py / test_owning_capability_
# advisory.py already import ``test_lifecycle_state`` the same way.

CAP_ID = "inbox_management"  # the genuinely-accepted "otherwise clean" capability under test.


class V153ShipCriteriaTests(_ls_fixtures._CheckCompletionFixtureMixin, unittest.TestCase):
    """The 4 structural locked ship criteria for Cut 1.5 / v0.19.0 (V15-3 closure)."""

    # -- shared fixture helpers -------------------------------------------------------------

    def _seed_second_capability_for_acceptance(self, root):
        """Seed a SEPARATE, not-yet-accepted capability into the SAME project root as the
        already-accepted CAP_ID, reusing Task C's own real descriptor/proof fixtures verbatim
        (``test_acceptance_refuses_on_open_bespoke_bypass._descriptor`` / ``_proof``) -- the
        exact shape that module's own ``test_after_reap_same_call_succeeds`` proves DOES
        succeed via ``record_operator_acceptance`` once no bespoke-writer bypass is open. This
        lets one open bespoke-writer entry in the project be shown to block BOTH an
        already-accepted capability's completion/health view AND a fresh capability's
        acceptance transition, in the same fixture.

        Merges into the SAME descriptor-set file the already-accepted CAP_ID entry lives in
        (never overwrites it) -- ``lifecycle_state.DESCRIPTOR_SET_REL``, the identical path
        constant ``capability_health.overall_status`` / ``check_completion`` read.
        """
        descriptor_path = Path(root) / lifecycle_state.DESCRIPTOR_SET_REL
        existing = (
            json.loads(descriptor_path.read_text(encoding="utf-8"))
            if descriptor_path.exists() else []
        )
        existing.append(_acc_fixtures._descriptor())
        descriptor_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

        proof_path = Path(root) / f"{_acc_fixtures.CAP_ID}.copy_run_proof.json"
        proof_path.write_text(json.dumps(_acc_fixtures._proof()), encoding="utf-8")

        receipt_path = (
            Path(root) / "security" / "acceptance_receipts" / f"{_acc_fixtures.CAP_ID}.receipt.json"
        )
        audit_path = Path(root) / lifecycle_state.ACCEPTANCE_LOG_REL
        return proof_path, receipt_path, descriptor_path, audit_path

    def _attempt_second_capability_acceptance(self, root, proof_path, receipt_path,
                                               descriptor_path, audit_path):
        return operator_acceptance.record_operator_acceptance(
            _acc_fixtures.CAP_ID, _acc_fixtures.PHASE, str(proof_path),
            "Yes -- I accept this capability for live use.",
            receipt_path=str(receipt_path),
            descriptor_set_path=str(descriptor_path),
            audit_log_path=str(audit_path),
            project_root=str(root))

    # =========================================================================================
    # Criterion 1 -- false-green closed: an OPEN bespoke-writer entry makes check_completion /
    # capability_health --overall non-green PROJECT-WIDE, AND record_operator_acceptance refuses
    # to live-enable a DIFFERENT, otherwise-valid capability in the same project.
    # =========================================================================================

    def test_criterion1_open_bespoke_writer_blocks_completion_health_and_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # (a) A genuinely accepted, otherwise-clean capability via the REAL, full acceptance
            # ceremony -- absent the bypass below this would be done=True / normal_status_allowed
            # =True (anti-overfit, matching Task A's own fixture discipline exactly).
            self._accept_real_capability(root, CAP_ID)

            # (b) A REAL open bespoke-writer bypass: the writer file genuinely exists on disk
            # (still bespoke content) AND a "pending" queue entry names it.
            _completion_fixtures._write_bespoke_writer_file(root)
            _completion_fixtures._write_pending_migrations(
                root, [_completion_fixtures._bespoke_entry()])

            overall = capability_health.overall_status(str(root))
            self.assertFalse(
                overall["normal_status_allowed"],
                f"an open bespoke-writer bypass must forbid normal status project-wide; got "
                f"{overall}")
            self.assertTrue(overall["open_external_write_bypass"]["blocking"])

            result = lifecycle_state.check_completion(str(root), CAP_ID)
            self.assertFalse(
                result.done,
                "an open bespoke-writer bypass must make check_completion non-done, even though "
                "it does not resolve to CAP_ID at all (attribution-free, project-wide)")
            self.assertIn("open_external_write_bypass", result.failed_conjuncts)

            # (c) A SEPARATE, not-yet-accepted, otherwise-fully-valid capability -- proves the
            # SAME open entry also refuses a live-enable transition, not just the health views.
            proof_path, receipt_path, descriptor_path, audit_path = (
                self._seed_second_capability_for_acceptance(root))
            # The audit log already carries CAP_ID's own genuine acceptance record from
            # ``_accept_real_capability`` above (it is the SAME shared, project-root-relative
            # log file every capability's acceptance appends to) -- snapshot it here so the
            # refusal-adds-nothing assertion below is a genuine before/after diff, not a
            # (wrong) "the file must not exist at all" check.
            audit_before = audit_path.read_text(encoding="utf-8")

            res = self._attempt_second_capability_acceptance(
                root, proof_path, receipt_path, descriptor_path, audit_path)

            self.assertFalse(
                res.accepted,
                "record_operator_acceptance must refuse to live-enable a DIFFERENT capability "
                "while any open bespoke-writer bypass exists in the project")
            self.assertIsNotNone(res.reason)
            self.assertIn("bypass", res.reason)
            self.assertFalse(receipt_path.exists(), "a refusal must mint no receipt")
            self.assertEqual(
                audit_path.read_text(encoding="utf-8"), audit_before,
                "a refusal must append no new acceptance record")
            self.assertNotIn(_acc_fixtures.CAP_ID, audit_path.read_text(encoding="utf-8"))

    # =========================================================================================
    # Criterion 2 -- deletion path: deleting the bespoke writer file lets reconcile_state
    # auto-reap the entry, and the SAME acceptance call then succeeds. No deadlock.
    # =========================================================================================

    def test_criterion2_deleting_writer_autoreaps_and_acceptance_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)
            _completion_fixtures._write_bespoke_writer_file(root)
            _completion_fixtures._write_pending_migrations(
                root, [_completion_fixtures._bespoke_entry()])

            proof_path, receipt_path, descriptor_path, audit_path = (
                self._seed_second_capability_for_acceptance(root))

            # Establish the "would otherwise deadlock" baseline: currently blocked.
            self.assertEqual(len(_state.open_bespoke_writer_migrations(str(root))), 1)
            res_before = self._attempt_second_capability_acceptance(
                root, proof_path, receipt_path, descriptor_path, audit_path)
            self.assertFalse(res_before.accepted, res_before.reason)

            # The operator DELETES the bespoke writer file (the genuine fix path: a hand-rolled
            # loop the operator removes/replaces rather than patches in place).
            (root / _completion_fixtures.BESPOKE_WRITER_RELPATH).unlink()

            # reconcile_state (Task B's home) runs the stateless auto-reap.
            lifecycle_state.reconcile_state(str(root), CAP_ID)

            self.assertEqual(
                len(_state.open_bespoke_writer_migrations(str(root))), 0,
                "deleting the writer file must let reconcile_state auto-reap the entry")

            # The SAME acceptance call now SUCCEEDS -- repair was always available; no deadlock.
            res_after = self._attempt_second_capability_acceptance(
                root, proof_path, receipt_path, descriptor_path, audit_path)
            self.assertTrue(
                res_after.accepted,
                f"once the bespoke-writer entry is reaped, acceptance must succeed; got "
                f"{res_after.reason}")

            result = lifecycle_state.check_completion(str(root), CAP_ID)
            self.assertFalse(
                "open_external_write_bypass" in result.failed_conjuncts,
                "the bypass conjunct must no longer fire once the entry is reaped")

    # =========================================================================================
    # Criterion 3 -- unlinked fallback: an un-attributable bespoke writer (no derivable owner)
    # still forces check_completion done=False project-wide. Fail-closed, never silent-green.
    # =========================================================================================

    def test_criterion3_unattributable_writer_still_forces_global_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)

            # A writer that carries NO ownership evidence at all (Task E's own no-evidence
            # fixture: no capability import, no ENVELOPE_CAPABILITY_ID literal, no OP_KIND
            # literal) -- genuinely un-attributable, not merely "not looked up".
            _owner_fixtures._write_bespoke_writer(
                root, source=_owner_fixtures._NO_EVIDENCE_WRITER_SRC)
            _completion_fixtures._write_pending_migrations(
                root, [_owner_fixtures._bespoke_entry()])

            entry = _state.open_bespoke_writer_migrations(str(root))[0]
            ownership = _state.derive_owning_capability(str(root), entry)
            self.assertEqual(
                ownership["ownership_status"], "unresolved",
                "fixture must genuinely be unattributable (ownership_status=unresolved), or "
                "this test proves nothing about the unlinked-fallback path")
            self.assertIsNone(ownership["owning_capability_id"])

            overall = capability_health.overall_status(str(root))
            self.assertFalse(overall["normal_status_allowed"], overall)

            result = lifecycle_state.check_completion(str(root), CAP_ID)
            self.assertFalse(
                result.done,
                "an unattributable (unresolved-ownership) bespoke writer must still force "
                "done=False -- fail-closed, never a silent green because attribution failed")
            self.assertIn("open_external_write_bypass", result.failed_conjuncts)
            # The plain-language message still names the file even with no attribution clause
            # (Task E's message-enrichment contract) -- confirms this is the genuine
            # "unresolved" rendering path, not an empty/degenerate message.
            self.assertIn(_owner_fixtures.BESPOKE_WRITER_RELPATH, result.operator_message)
            self.assertNotIn("part of", result.operator_message)

    # =========================================================================================
    # Criterion 4 -- quarantine can't launder completion: a quarantined (listed-paused +
    # hash-matched) pending bespoke writer scans CLEAN under the F-3B quarantine, yet
    # check_completion / acceptance must still see it as an open bypass, because completion
    # inspects migration-entry PRESENCE, independent of the scanner's own (quarantined) verdict.
    # =========================================================================================

    def test_criterion4_quarantine_cannot_launder_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._accept_real_capability(root, CAP_ID)

            writer_relpath = _reap_fixtures.BESPOKE_WRITER_RELPATH
            writer_path = root / writer_relpath
            writer_path.parent.mkdir(parents=True, exist_ok=True)
            writer_path.write_text(_reap_fixtures._BESPOKE_RUNNER_SRC, encoding="utf-8")

            # Compute the file's REAL, un-quarantined scan verdict first -- so the recorded
            # "violations" + hash the quarantine will later match against are this file's true
            # violations, never fabricated. This is the same scanner every build-time gate uses.
            real_violations = _scan.scan_paths([str(writer_path)])
            self.assertTrue(
                real_violations,
                "fixture must genuinely be scan-RED without the quarantine, or this test does "
                "not reproduce a real laundering setup")
            self.assertTrue(
                any(v.kind == "sealed_kernel_import" for v in real_violations),
                "expected the real bypass-import violation this writer is known to trip")

            recorded_hash = hashlib.sha256(
                _reap_fixtures._BESPOKE_RUNNER_SRC.encode("utf-8")).hexdigest()
            recorded_violations = [
                {"path": writer_relpath, "line": v.lineno, "kind": v.kind}
                for v in real_violations
            ]
            entry = {
                "mechanism_id": _reap_fixtures.BESPOKE_MECHANISM_ID,
                "writer_relpath": writer_relpath,
                "entrypoint_relpath": None,
                "status": "pending",
                "reason": "flagged non-conformant with the external-write gate on upgrade",
                "paused_content_sha256": recorded_hash,
                "violations": recorded_violations,
            }
            _completion_fixtures._write_pending_migrations(root, [entry])

            # (i) Genuinely reproduce the quarantine-laundering setup: under the PROJECT-SCOPED
            # quarantine (project_root passed), this exact writer now scans CLEAN -- the F-3B
            # exemption is doing real, verified work here, not merely assumed.
            quarantined_violations = _scan.scan_paths([str(writer_path)], project_root=root)
            self.assertEqual(
                quarantined_violations, [],
                "the fixture must genuinely reproduce the quarantine-clean laundering setup "
                "(scan_paths(..., project_root=root) must report zero violations here)")

            # (ii) Yet completion / health / acceptance must STILL see this as an OPEN bypass:
            # they inspect migration-entry PRESENCE (writer_relpath set + status=='pending'),
            # never the scanner's own (quarantined) verdict for that same file.
            overall = capability_health.overall_status(str(root))
            self.assertFalse(
                overall["normal_status_allowed"],
                "a quarantined-clean bespoke writer must still forbid normal status -- "
                "completion safety must never be laundered through the build-time scan "
                "quarantine")
            result = lifecycle_state.check_completion(str(root), CAP_ID)
            self.assertFalse(
                result.done,
                "a quarantined-clean bespoke writer must still make check_completion "
                "non-done -- completion inspects migration-entry presence, independent of "
                "the scanner's own (quarantined) verdict")
            self.assertIn("open_external_write_bypass", result.failed_conjuncts)

            proof_path, receipt_path, descriptor_path, audit_path = (
                self._seed_second_capability_for_acceptance(root))
            res = self._attempt_second_capability_acceptance(
                root, proof_path, receipt_path, descriptor_path, audit_path)
            self.assertFalse(
                res.accepted,
                "acceptance must refuse even though the writer scans clean under the "
                "project-scoped quarantine")
            self.assertFalse(receipt_path.exists())

    # =========================================================================================
    # Criterion 5 -- EMPIRICAL, not a build-time fixture. See module docstring.
    # =========================================================================================

    @unittest.skip(
        "Criterion 5 (the durable-ledger assertion -- ONE run_id/consent/WAL, multiple chunks "
        "written UNDER that one envelope, on the REAL rebuilt writer against a real adapter/ "
        "vendor surface) is EMPIRICAL: it requires a real multi-chunk bulk run to observe, which "
        "is out of reach for a stdlib-only, no-network unit test. It is proven in the Cut 1.5 "
        "re-validation runbook on a real estate project "
        "(kept in the build repo's private review area, Task F Step 5 of the plan at "
        "docs/superpowers/plans/2026-07-25-cut1.5-acceptance-linkage-false-green.md), not here.")
    def test_criterion5_durable_ledger_is_empirical_see_revalidation_runbook(self):
        raise AssertionError("this criterion is proven empirically, never in the build suite")


if __name__ == "__main__":
    unittest.main()
