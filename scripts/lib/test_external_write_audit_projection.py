"""Tests for the Task E1 (Cut 1.1 Cluster E / F-73) redacted, committable
audit projection -- ``agents/lib/external_write/audit_projection.py``.

Covers:
  * The projection contains counts + digests + the consent timestamp + the
    final claim level, and is written to a COMMITTABLE path (not gitignored)
    -- distinct from ``run_envelope.DEFAULT_ENVELOPE_DIR`` (gitignored,
    local-only).
  * PRIVACY CRUX: a fixture envelope whose reviewed_set/tranches carry
    realistic PII-shaped raw ids/subjects/account identifiers is projected,
    and NONE of those raw values appear anywhere in the redacted output.
  * Consent is sourced from the ONE run-level ``run_consent_receipt`` (D3's
    honest ``approved_at``), never a per-chunk operation receipt.
  * The three-way claim level (recoverable_all / recoverable_partial /
    not_recoverable_by_system), including the irreversible-tier and
    zero-applied edge cases.
  * Op-kind-agnostic: exercised on divergent op_kinds (a reversible field op
    and an irreversible op) with no vendor-specific branching.
  * scan.py reports this module clean -- READ-ONLY by construction.
  * ``agent_emitter._EXTERNAL_WRITE_LIB_FILES`` enrollment (see
    test_build_operate_emit.py's own dedicated test for the count-pin).

Stdlib unittest; pip-install-free.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.run_envelope import (  # noqa: E402
    RUN_STATE_EXECUTING,
    RUN_STATE_PENDING,
    Tranche,
    append_tranche,
    load_run_envelope,
    mint_run_envelope,
)
from external_write.scan import scan_paths  # noqa: E402

from external_write.audit_projection import (  # noqa: E402
    AUDIT_PROJECTION_SCHEMA,
    DEFAULT_AUDIT_PROJECTION_DIR,
    NOT_RECOVERABLE_BY_SYSTEM,
    RECOVERABLE_ALL,
    RECOVERABLE_PARTIAL,
    project_redacted_audit,
)

_AUDIT_PROJECTION_MODULE_PATH = str(_AGENTS_LIB / "external_write" / "audit_projection.py")

# A reversible, dotted, GENERIC op_kind (never "gmail") -- proves action_type
# / external_system_class derive from the op_kind's own shape / contract,
# never a hardcoded vendor mapping. Multi-field `writes` exercises the "+"
# join in `_external_system_class`.
DOTTED_FIELD_OP = "tracker.task.archive"
# A non-dotted, irreversible, GENERIC op_kind -- the divergent second op_kind
# (anti-overfit: exercised on >=2 divergent op_kinds).
IRREVERSIBLE_OP = "_audit_projection_irreversible_probe"


def _register_dotted_field_contract():
    contracts_mod.OPERATION_CONTRACTS[DOTTED_FIELD_OP] = OperationContract(
        op_kind=DOTTED_FIELD_OP, writes=("labels", "notes"), produces=(),
        dependency_set=(), verifier_set=(), introduces_persistent_binding=False,
        risk_class="reversible_external", read_only_scope="fixture.readonly")


def _unregister_dotted_field_contract():
    contracts_mod.OPERATION_CONTRACTS.pop(DOTTED_FIELD_OP, None)


def _register_irreversible_contract():
    contracts_mod.OPERATION_CONTRACTS[IRREVERSIBLE_OP] = OperationContract(
        op_kind=IRREVERSIBLE_OP, writes=("__record__",), produces=(),
        dependency_set=(), verifier_set=(), introduces_persistent_binding=False,
        risk_class="irreversible_external")


def _unregister_irreversible_contract():
    contracts_mod.OPERATION_CONTRACTS.pop(IRREVERSIBLE_OP, None)


def _reviewed_set(n=3, prefix="row"):
    return [
        {"unit_id": f"{prefix}{i}", "prestate_digest": f"d{i}",
         "intended_mutation": {"value": "Complete"},
         "category": "status_change", "protected_status": False}
        for i in range(n)
    ]


def _mint(d, *, run_id="run-1", op_kind=DOTTED_FIELD_OP, reviewed_set=None,
          population=100, approved_at="2026-07-19T22:45:48Z",
          operator_approval_verbatim="yes, apply these changes"):
    return mint_run_envelope(
        run_id=run_id, capability_id="cap:test", op_kind=op_kind,
        contract_hash="ch-abc", implementation_hash="ih-abc",
        reviewed_set=reviewed_set if reviewed_set is not None else _reviewed_set(3),
        population_count=population,
        operator_approval_verbatim=operator_approval_verbatim,
        consent_sentence_shown="Apply changes.",
        approved_at=approved_at, envelope_dir=d)


def _apply(env, unit_ids, *, d, verification_status="verified"):
    tranche = Tranche(
        applied_unit_ids=tuple(unit_ids),
        per_unit_result={uid: "written" for uid in unit_ids},
        verification_status=verification_status)
    return append_tranche(env, tranche, envelope_dir=d)


class TestCommittablePathAndSchema(unittest.TestCase):
    def setUp(self):
        _register_dotted_field_contract()

    def tearDown(self):
        _unregister_dotted_field_contract()

    def test_default_audit_dir_is_the_committable_security_audit_path(self):
        # Proves the REAL default (no audit_dir passed) resolves under
        # DEFAULT_AUDIT_PROJECTION_DIR -- exercised inside a throwaway cwd
        # (chdir'd for the duration of this test only, always restored) so
        # nothing is written outside a tempdir even though `audit_dir` is
        # deliberately omitted here.
        import os
        with tempfile.TemporaryDirectory() as project_root, \
                tempfile.TemporaryDirectory() as d:
            original_cwd = os.getcwd()
            os.chdir(project_root)
            try:
                _mint(d)
                env = load_run_envelope("run-1", envelope_dir=d)
                _apply(env, ["row0", "row1"], d=d)
                result = project_redacted_audit("run-1", envelope_dir=d)
                # Resolve to an absolute path WHILE still chdir'd -- `result.path`
                # is relative (its own default), so resolving it after restoring
                # cwd below would silently resolve against the WRONG directory.
                absolute_written_path = Path(result.path).resolve()
            finally:
                os.chdir(original_cwd)

            expected_dir = Path(project_root).resolve() / DEFAULT_AUDIT_PROJECTION_DIR
            self.assertEqual(absolute_written_path.parent, expected_dir)
            self.assertTrue((expected_dir / "run-1.redacted_audit.json").is_file())

    def test_projection_is_written_to_the_given_committable_audit_dir(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d)
            env = load_run_envelope("run-1", envelope_dir=d)
            _apply(env, ["row0", "row1"], d=d)

            result = project_redacted_audit("run-1", envelope_dir=d, audit_dir=audit_d)

            self.assertEqual(Path(result.path).parent, Path(audit_d))
            self.assertNotIn("run_envelopes", result.path)
            self.assertNotIn("invocation_ledgers", result.path)

    def test_committable_path_does_not_match_any_gitignore_template_pattern(self):
        # The emitted root .gitignore's consent/runtime-artifact block is
        # scoped to four EXACT raw-record paths (never a broad `/security/`
        # catch-all) -- see wizard/templates/root/gitignore_template. Read
        # the REAL template and prove DEFAULT_AUDIT_PROJECTION_DIR is not one
        # of the ignored literal path prefixes it lists.
        template_path = (
            Path(__file__).resolve().parents[2] / "templates" / "root" / "gitignore_template")
        content = template_path.read_text(encoding="utf-8")
        ignored_paths = [
            line.strip() for line in content.splitlines()
            if line.strip().startswith("/security/")
        ]
        self.assertTrue(ignored_paths, "expected at least one ignored /security/ path")
        for pattern in ignored_paths:
            bare = pattern.strip("/")
            self.assertFalse(
                DEFAULT_AUDIT_PROJECTION_DIR.startswith(bare) or bare.startswith(
                    DEFAULT_AUDIT_PROJECTION_DIR),
                f"{DEFAULT_AUDIT_PROJECTION_DIR!r} collides with gitignored pattern {pattern!r}")

    def test_raw_envelope_stays_at_the_gitignored_local_only_path(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d)
            env = load_run_envelope("run-1", envelope_dir=d)
            _apply(env, ["row0"], d=d)
            project_redacted_audit("run-1", envelope_dir=d, audit_dir=audit_d)
            # The raw envelope file (reviewed_set + consent verbatim) is
            # exactly where run_envelope.py always puts it -- untouched,
            # unmoved, unredacted -- this module never edits it.
            self.assertTrue((Path(d) / "run-1.json").is_file())
            raw = json.loads((Path(d) / "run-1.json").read_text())
            self.assertEqual(raw["reviewed_set"][0]["unit_id"], "row0")

    def test_projection_round_trips_through_disk_identically(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d)
            env = load_run_envelope("run-1", envelope_dir=d)
            _apply(env, ["row0"], d=d)
            result = project_redacted_audit("run-1", envelope_dir=d, audit_dir=audit_d)
            on_disk = json.loads(Path(result.path).read_text(encoding="utf-8"))
            self.assertEqual(on_disk, result.projection)

    def test_projection_carries_the_required_field_set(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d)
            env = load_run_envelope("run-1", envelope_dir=d)
            _apply(env, ["row0", "row1"], d=d)
            result = project_redacted_audit(
                "run-1", envelope_dir=d, audit_dir=audit_d,
                system_version="sys-1", bundle_version="v0.14.0",
                git_version="deadbeef", parent_run_id="parent-run-0")
            p = result.projection
            self.assertEqual(p["audit_schema_version"], AUDIT_PROJECTION_SCHEMA)
            self.assertEqual(p["system_version"], "sys-1")
            self.assertEqual(p["bundle_version"], "v0.14.0")
            self.assertEqual(p["git_version"], "deadbeef")
            self.assertEqual(p["capability_id"], "cap:test")
            self.assertEqual(p["op_kind"], DOTTED_FIELD_OP)
            self.assertEqual(p["run_id"], "run-1")
            self.assertEqual(p["parent_run_id"], "parent-run-0")
            self.assertEqual(p["action_type"], "archive")  # last dotted segment
            self.assertEqual(p["external_system_class"], "labels+notes")
            self.assertEqual(p["adapter_contract_version"], "ch-abc")
            self.assertEqual(p["reviewed_set_count"], 3)
            self.assertTrue(p["reviewed_set_digest"])
            self.assertTrue(p["consent_receipt_digest"])
            self.assertEqual(p["consent_timestamp"], "2026-07-19T22:45:48Z")
            self.assertIn("run_state", p)
            self.assertIn("counts_by_status", p)
            self.assertIn("recovery_manifest_digest", p)
            self.assertIn("recovery_manifest_count", p)
            self.assertIn("claim_level", p)


class TestClaimLevel(unittest.TestCase):
    def setUp(self):
        _register_dotted_field_contract()
        _register_irreversible_contract()

    def tearDown(self):
        _unregister_dotted_field_contract()
        _unregister_irreversible_contract()

    def test_claim_level_recoverable_all_when_every_applied_id_is_recoverable(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d, run_id="run-all", op_kind=DOTTED_FIELD_OP)
            env = load_run_envelope("run-all", envelope_dir=d)
            _apply(env, ["row0", "row1", "row2"], d=d)
            result = project_redacted_audit("run-all", envelope_dir=d, audit_dir=audit_d)
            self.assertEqual(result.projection["claim_level"], RECOVERABLE_ALL)
            self.assertEqual(result.projection["recovery_manifest_count"], 3)

    def test_claim_level_recoverable_partial_when_some_applied_ids_recover(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d, run_id="run-partial", op_kind=DOTTED_FIELD_OP)
            env = load_run_envelope("run-partial", envelope_dir=d)
            # row0/row1 are in the reviewed_set (recoverable basis); "row9" is
            # NOT in the reviewed_set, so it is applied but not recoverable --
            # a genuine partial-recovery shape.
            _apply(env, ["row0", "row1", "row9"], d=d)
            result = project_redacted_audit("run-partial", envelope_dir=d, audit_dir=audit_d)
            self.assertEqual(result.projection["claim_level"], RECOVERABLE_PARTIAL)
            self.assertEqual(result.projection["recovery_manifest_count"], 2)

    def test_claim_level_not_recoverable_for_an_irreversible_tier_op(self):
        # Anti-overfit: a DIVERGENT (irreversible, non-dotted) op_kind. Even
        # though the applied ids ARE in the reviewed_set, the recovery tier
        # is irreversible, so report_run_recoverability's is_reversible gate
        # refuses to call any of them recoverable -- never assumed, never
        # sampled-around.
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d, run_id="run-irrev", op_kind=IRREVERSIBLE_OP,
                  reviewed_set=_reviewed_set(2, prefix="rec"))
            env = load_run_envelope("run-irrev", envelope_dir=d)
            _apply(env, ["rec0", "rec1"], d=d)
            result = project_redacted_audit("run-irrev", envelope_dir=d, audit_dir=audit_d)
            self.assertEqual(result.projection["claim_level"], NOT_RECOVERABLE_BY_SYSTEM)
            self.assertEqual(result.projection["recovery_manifest_count"], 0)

    def test_claim_level_not_recoverable_when_nothing_was_applied(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d, run_id="run-none", op_kind=DOTTED_FIELD_OP)
            # No append_tranche call -- run stays PENDING, nothing applied.
            result = project_redacted_audit("run-none", envelope_dir=d, audit_dir=audit_d)
            self.assertEqual(result.projection["claim_level"], NOT_RECOVERABLE_BY_SYSTEM)
            self.assertEqual(result.projection["recovery_manifest_count"], 0)
            self.assertEqual(result.projection["run_state"], RUN_STATE_PENDING)

    def test_run_state_reflects_execution_after_a_tranche_lands(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d, run_id="run-exec", op_kind=DOTTED_FIELD_OP)
            env = load_run_envelope("run-exec", envelope_dir=d)
            _apply(env, ["row0"], d=d)
            result = project_redacted_audit("run-exec", envelope_dir=d, audit_dir=audit_d)
            self.assertEqual(result.projection["run_state"], RUN_STATE_EXECUTING)


class TestNeverRaisesOnAbsentRun(unittest.TestCase):
    def test_absent_run_id_reports_fail_closed_empty_shape_without_raising(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            result = project_redacted_audit(
                "never-minted-run", envelope_dir=d, audit_dir=audit_d)
            p = result.projection
            self.assertEqual(p["claim_level"], NOT_RECOVERABLE_BY_SYSTEM)
            self.assertEqual(p["reviewed_set_count"], 0)
            self.assertEqual(p["consent_receipt_digest"], "")
            self.assertEqual(p["consent_timestamp"], "")
            self.assertEqual(p["recovery_manifest_count"], 0)


class TestConsentSourceIsTheRunLevelReceipt(unittest.TestCase):
    """Task D3/F-80: the consent digest + timestamp must come from the ONE
    run-level run_consent_receipt (minted once, bound to the real
    operator-utterance approved_at), never fabricated, never a per-chunk
    receipt substitute."""

    def setUp(self):
        _register_dotted_field_contract()

    def tearDown(self):
        _unregister_dotted_field_contract()

    def test_consent_timestamp_is_the_exact_operator_utterance_time_passed_at_mint(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            exact_utterance_time = "2026-03-14T09:26:53Z"
            _mint(d, run_id="run-consent", op_kind=DOTTED_FIELD_OP,
                  approved_at=exact_utterance_time)
            result = project_redacted_audit("run-consent", envelope_dir=d, audit_dir=audit_d)
            self.assertEqual(result.projection["consent_timestamp"], exact_utterance_time)

    def test_consent_receipt_digest_is_stable_for_the_same_receipt_and_differs_across_runs(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d, run_id="run-a", op_kind=DOTTED_FIELD_OP,
                  approved_at="2026-01-01T00:00:00Z")
            _mint(d, run_id="run-b", op_kind=DOTTED_FIELD_OP,
                  approved_at="2026-02-02T00:00:00Z")
            first = project_redacted_audit("run-a", envelope_dir=d, audit_dir=audit_d)
            second = project_redacted_audit("run-b", envelope_dir=d, audit_dir=audit_d)
            self.assertTrue(first.projection["consent_receipt_digest"])
            self.assertNotEqual(
                first.projection["consent_receipt_digest"],
                second.projection["consent_receipt_digest"])
            # Re-projecting the SAME run reproduces the SAME digest --
            # deterministic, not time-of-call-dependent.
            again = project_redacted_audit("run-a", envelope_dir=d, audit_dir=audit_d)
            self.assertEqual(
                first.projection["consent_receipt_digest"],
                again.projection["consent_receipt_digest"])


class TestPrivacyCrux(unittest.TestCase):
    """The load-bearing test: a fixture envelope whose reviewed_set/tranches
    carry REALISTIC PII-shaped raw ids/subjects/account identifiers must
    never leak any of those raw values into the redacted projection -- a
    test that would actually catch a leak, not merely assert a shape."""

    def setUp(self):
        _register_dotted_field_contract()

    def tearDown(self):
        _unregister_dotted_field_contract()

    def test_zero_raw_pii_survives_into_the_redacted_projection(self):
        pii_shaped_reviewed_set = [
            {
                "unit_id": "18f2a9c7b3d4e5f6",  # realistic Gmail-style message id
                "prestate_digest": "d0",
                "intended_mutation": {
                    "subject": "Re: Wire transfer confirmation - Jane Q. Doe",
                    "from_address": "jane.doe.private@example.com",
                    "account_id": "acct-9284710",
                },
                "category": "status_change", "protected_status": False,
            },
            {
                "unit_id": "18f2a9c7b3d4e600",
                "prestate_digest": "d1",
                "intended_mutation": {
                    "subject": "Your prescription refill - Dr. Alan Smith",
                    "from_address": "pharmacy-notifications@example-health.com",
                    "account_id": "acct-9284710",
                },
                "category": "contains_exceptions", "protected_status": True,
            },
        ]
        secret_operator_utterance = (
            "yes, trash the two messages from jane.doe.private@example.com and "
            "the health pharmacy notice, account acct-9284710"
        )
        pii_raw_values = [
            "18f2a9c7b3d4e5f6", "18f2a9c7b3d4e600",
            "Jane Q. Doe", "jane.doe.private@example.com", "acct-9284710",
            "Dr. Alan Smith", "pharmacy-notifications@example-health.com",
            "Wire transfer confirmation", "prescription refill",
            secret_operator_utterance,
        ]

        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(
                d, run_id="run-pii", op_kind=DOTTED_FIELD_OP,
                reviewed_set=pii_shaped_reviewed_set,
                operator_approval_verbatim=secret_operator_utterance)
            env = load_run_envelope("run-pii", envelope_dir=d)
            _apply(env, ["18f2a9c7b3d4e5f6", "18f2a9c7b3d4e600"], d=d)

            result = project_redacted_audit("run-pii", envelope_dir=d, audit_dir=audit_d)
            serialized = json.dumps(result.projection)

            for raw_value in pii_raw_values:
                self.assertNotIn(
                    raw_value, serialized,
                    f"raw PII-shaped value {raw_value!r} leaked into the redacted "
                    "audit projection")

            # Sanity: the fixture actually WAS recoverable (both applied ids are
            # in the reviewed_set, reversible tier) -- proving the digests/counts
            # are computed from real data, not incidentally empty/vacuous.
            self.assertEqual(result.projection["claim_level"], RECOVERABLE_ALL)
            self.assertEqual(result.projection["recovery_manifest_count"], 2)
            self.assertEqual(result.projection["reviewed_set_count"], 2)

    def test_reviewer_can_prove_scale_and_consent_from_the_committed_artifact_alone(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as audit_d:
            _mint(d, run_id="run-scale", op_kind=DOTTED_FIELD_OP,
                  reviewed_set=_reviewed_set(5, prefix="msg"),
                  approved_at="2026-05-05T05:05:05Z")
            env = load_run_envelope("run-scale", envelope_dir=d)
            _apply(env, ["msg0", "msg1", "msg2", "msg3", "msg4"], d=d)
            written = project_redacted_audit("run-scale", envelope_dir=d, audit_dir=audit_d)

            # Simulate a reviewer who has ONLY the committed artifact on disk
            # -- no access to security/run_envelopes/ at all.
            committed_only = json.loads(Path(written.path).read_text(encoding="utf-8"))

            # SCALE: proven by counts alone.
            self.assertEqual(committed_only["reviewed_set_count"], 5)
            self.assertEqual(committed_only["recovery_manifest_count"], 5)
            self.assertEqual(committed_only["claim_level"], RECOVERABLE_ALL)
            # CONSENT: proven by one digest + the real operator-utterance time.
            self.assertTrue(committed_only["consent_receipt_digest"])
            self.assertEqual(committed_only["consent_timestamp"], "2026-05-05T05:05:05Z")


class TestReadOnlyScanClean(unittest.TestCase):
    def test_scans_clean(self):
        violations = scan_paths([_AUDIT_PROJECTION_MODULE_PATH])
        self.assertEqual(violations, [], violations)


if __name__ == "__main__":
    unittest.main()
