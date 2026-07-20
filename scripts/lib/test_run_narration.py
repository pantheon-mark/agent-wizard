"""Tests for the Task E3 (Cut 1.1 Cluster E / F-85) honest bulk-run outcome
narration -- ``agents/lib/external_write/run_narration.py``.

Covers:
  * ``classify_bulk_run_status`` derives COMPLETED / PARTIAL / REFUSED purely
    from a ``BulkRunSummary``'s own typed fields (never a caller-supplied
    claim) across a real ``run_sanctioned_bulk`` completion, a real
    aggregate-ceiling partial refusal, and a real fresh-mint refusal.
  * ``render_bulk_run_outcome`` never renders the COMPLETED branch's
    "done"/finalized success wording for a partial or refused summary --
    exercised both on real fixtures and on a synthetic matrix over every
    reachable (completed, finalized, refused, ever_applied) combination
    (the STRUCTURAL-impossibility guarantee: the function has exactly one
    parameter, so there is no way to override the rendered verb).
  * "Recoverable" is asserted ONLY for the counts the durable
    ``report_run_recoverability`` dict attaches -- never invented, never
    drawn from the completion fields.
  * scan.py reports this module clean -- READ-ONLY by construction; an
    AST-level check independently pins that no write/mint entrypoint is
    ever referenced in code (not merely discussed in the docstring).

Stdlib unittest; pip-install-free.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    register_adapter,
    unregister_adapter,
)
from external_write.read_facade import (  # noqa: E402
    ReadFacade,
    register_read_facade,
    unregister_read_facade,
)
from external_write.operations import Operation, EffectUnit  # noqa: E402
from external_write.run_envelope import (  # noqa: E402
    NOT_RECOVERABLE_BY_SYSTEM,
    RECOVERABLE_BY_SYSTEM,
    run_sanctioned_bulk,
)
from external_write.audit_projection import (  # noqa: E402
    RECOVERABLE_ALL,
    RECOVERABLE_PARTIAL,
)
from external_write.scan import scan_paths  # noqa: E402

from external_write.run_narration import (  # noqa: E402
    BULK_RUN_COMPLETED,
    BULK_RUN_PARTIAL,
    BULK_RUN_REFUSED,
    classify_bulk_run_status,
    render_bulk_run_outcome,
)

_RUN_NARRATION_MODULE_PATH = str(_AGENTS_LIB / "external_write" / "run_narration.py")

FIELD_OP = "_run_narration_field_probe"


def _register_field_contract():
    contracts_mod.OPERATION_CONTRACTS[FIELD_OP] = OperationContract(
        op_kind=FIELD_OP, writes=("Status",), produces=(), dependency_set=(),
        verifier_set=(), introduces_persistent_binding=False,
        risk_class="reversible_external", read_only_scope="fixture.readonly")


def _unregister_field_contract():
    contracts_mod.OPERATION_CONTRACTS.pop(FIELD_OP, None)


def _reviewed_set(n, prefix="row"):
    return [
        {"unit_id": f"{prefix}{i}", "prestate_digest": f"d{i}",
         "intended_mutation": {"value": "Complete"},
         "category": "status_change", "protected_status": False}
        for i in range(n)
    ]


def _op_builder(chunk_ids, value="Complete"):
    return Operation(
        surface="fixture_surface", op_kind=FIELD_OP, batch_id="narration-bulk",
        params={"rows": [{"row_id": uid, "intended_value": value} for uid in chunk_ids]})


class _FieldWriteClient:
    def __init__(self, store):
        self._store = store

    def write_row(self, row_id, value):
        self._store[row_id] = {"value": value}


class _FieldReadOnlyClient:
    def __init__(self, store):
        self._store = store

    def read_row(self, row_id):
        return dict(self._store.get(row_id, {}))


class _FieldReadFacade(ReadFacade):
    read_methods = ("read_row",)

    def read_row(self, row_id):
        return self._read("read_row", row_id)


class _FieldAdapter:
    def plan(self, params):
        params = params or {}
        return [EffectUnit(unit_id=r["row_id"], target_ref=r)
                for r in params.get("rows", [])]

    def apply_one(self, raw_client, unit):
        raw_client.write_row(unit.unit_id, unit.target_ref["intended_value"])

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        observed = observer.read_row(unit.unit_id)
        return {"value": observed.get("value"),
                "intended_value": unit.target_ref["intended_value"]}

    def verify_apply_landed(self, evidence):
        return evidence.poststate.get("value") == evidence.poststate.get("intended_value")


def _fresh_kwargs(d, n, chunk_size, run_label, approved_at="2026-07-19T22:45:48Z"):
    return dict(
        op_builder=_op_builder, run_label=run_label, capability_id="cap:test",
        op_kind=FIELD_OP, contract_hash="ch", implementation_hash="ih",
        reviewed_set=_reviewed_set(n), operator_approval_verbatim="yes apply these",
        consent_sentence_shown=f"Apply {n}.", approved_at=approved_at,
        chunk_size=chunk_size, envelope_dir=d,
        ledger_dir=os.path.join(d, "ledger"), receipt_dir=d)


class _RealFixturesMixin:
    """Real, typed ``BulkRunSummary`` fixtures produced by the actual
    ``run_sanctioned_bulk`` entrypoint -- never hand-constructed, so the
    tests exercise the genuine typed result this module renders from."""

    def setUp(self):
        _register_field_contract()
        register_read_facade(FIELD_OP, _FieldReadFacade)
        register_adapter(FIELD_OP, _FieldAdapter())

    def tearDown(self):
        _unregister_field_contract()
        unregister_adapter(FIELD_OP)
        unregister_read_facade(FIELD_OP)

    def _completed_summary(self, d):
        store = {f"row{i}": {"value": "Open"} for i in range(6)}
        return run_sanctioned_bulk(
            **_fresh_kwargs(d, n=6, chunk_size=2, run_label="completed"),
            client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))

    def _partial_summary(self, d):
        # population 30, reversible tier -> Knob B ceiling clamps to 25. Five
        # chunks of 5 apply (25 total); the sixth chunk's aggregate ceiling
        # check refuses BEFORE it writes -- a real, honest PARTIAL: some
        # progress, not finalized, a chunk refused. Mirrors
        # test_external_write_run_envelope.py's own
        # test_resume_without_fresh_consent_refuses_and_writes_nothing fixture.
        n = 30
        store = {f"row{i}": {"value": "Open"} for i in range(n)}
        return run_sanctioned_bulk(
            **_fresh_kwargs(d, n=n, chunk_size=5, run_label="partial"),
            client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))

    def _refused_summary(self, d):
        # No approved_at (F-80 guard) -- refuses before anything is minted;
        # nothing has EVER gone live for this attempt.
        kwargs = _fresh_kwargs(d, n=6, chunk_size=2, run_label="refused")
        kwargs["approved_at"] = None
        return run_sanctioned_bulk(**kwargs)


# ---------------------------------------------------------------------------
# 1. classify_bulk_run_status -- real fixtures
# ---------------------------------------------------------------------------

class TestClassifyRealFixtures(_RealFixturesMixin, unittest.TestCase):

    def test_completed_run_classifies_completed(self):
        with tempfile.TemporaryDirectory() as d:
            summary = self._completed_summary(d)
            self.assertTrue(summary.completed, summary.refusal_reason)
            self.assertEqual(classify_bulk_run_status(summary), BULK_RUN_COMPLETED)

    def test_aggregate_ceiling_partial_run_classifies_partial(self):
        with tempfile.TemporaryDirectory() as d:
            summary = self._partial_summary(d)
            self.assertTrue(summary.refused)
            self.assertFalse(summary.finalized)
            self.assertTrue(len(summary.applied_unit_ids) > 0)  # real progress happened
            self.assertEqual(classify_bulk_run_status(summary), BULK_RUN_PARTIAL)

    def test_fresh_mint_refusal_classifies_refused(self):
        with tempfile.TemporaryDirectory() as d:
            summary = self._refused_summary(d)
            self.assertTrue(summary.refused)
            self.assertEqual(summary.applied_unit_ids, ())
            self.assertEqual(summary.skipped_already_applied, ())
            self.assertEqual(classify_bulk_run_status(summary), BULK_RUN_REFUSED)

    def test_resume_refusal_after_prior_progress_classifies_partial_not_refused(self):
        # A resume attempt that itself applies nothing new (refused before any
        # chunk in THIS call) must still classify PARTIAL, not REFUSED,
        # because the durable recoverability counts show something already
        # went live in an earlier call -- "never went live" must be judged
        # over the WHOLE run, not just this call's own tuples.
        with tempfile.TemporaryDirectory() as d:
            first = self._partial_summary(d)
            self.assertTrue(first.refused)
            resumed = run_sanctioned_bulk(
                op_builder=_op_builder, resume_run_id=first.run_id, chunk_size=5,
                envelope_dir=d, ledger_dir=os.path.join(d, "ledger"), receipt_dir=d,
                client=_FieldWriteClient({f"row{i}": {"value": "Open"} for i in range(30)}),
                read_only_client=_FieldReadOnlyClient(
                    {f"row{i}": {"value": "Open"} for i in range(30)}))
            self.assertTrue(resumed.refused)  # no fresh consent given -> refuses
            self.assertEqual(resumed.applied_unit_ids, ())  # nothing new THIS call
            self.assertEqual(classify_bulk_run_status(resumed), BULK_RUN_PARTIAL)


# ---------------------------------------------------------------------------
# 2. render_bulk_run_outcome -- honest text, real fixtures
# ---------------------------------------------------------------------------

class TestRenderRealFixtures(_RealFixturesMixin, unittest.TestCase):

    def test_completed_text_says_completed_never_partial_or_refused(self):
        with tempfile.TemporaryDirectory() as d:
            text = render_bulk_run_outcome(self._completed_summary(d))
            self.assertIn("COMPLETED", text)
            self.assertNotIn("PARTIAL", text)
            self.assertNotIn("REFUSED", text)
            self.assertIn("6 item(s) applied", text)

    def test_partial_text_says_partial_never_completed_or_applied_as_success(self):
        with tempfile.TemporaryDirectory() as d:
            summary = self._partial_summary(d)
            text = render_bulk_run_outcome(summary)
            self.assertIn("PARTIAL", text)
            self.assertNotIn("COMPLETED", text)
            self.assertNotIn("REFUSED", text)
            self.assertNotIn("finalized. ", text)  # the COMPLETED branch's exact phrase
            self.assertIn("has NOT finished", text)
            self.assertIn(f"{len(summary.applied_unit_ids)} item(s) applied", text)

    def test_refused_text_says_refused_never_says_applied(self):
        with tempfile.TemporaryDirectory() as d:
            text = render_bulk_run_outcome(self._refused_summary(d))
            self.assertIn("REFUSED", text)
            self.assertNotIn("COMPLETED", text)
            self.assertNotIn("PARTIAL", text)
            self.assertIn("Nothing was applied", text)
            self.assertIn("never went live", text)

    def test_recoverable_only_for_recoverable_ids_by_the_durable_report(self):
        # The completed run's ids are all reversible/applied -> ALL recoverable;
        # the aggregate-ceiling partial run's applied ids are the same
        # (reversible field op) -> recoverable too, but the count must equal
        # EXACTLY what report_run_recoverability attached, never a number
        # invented from completion fields.
        with tempfile.TemporaryDirectory() as d:
            summary = self._completed_summary(d)
            counts = summary.recoverability["counts"]
            text = render_bulk_run_outcome(summary)
            self.assertIn(f"Recoverable by this system: {counts['recoverable_by_system']}", text)
            self.assertIn(
                f"NOT recoverable by this system: {counts['not_recoverable_by_system']}", text)

    def test_refused_never_asserts_recoverable(self):
        with tempfile.TemporaryDirectory() as d:
            summary = self._refused_summary(d)
            text = render_bulk_run_outcome(summary)
            self.assertIn("Recoverable by this system: 0", text)
            self.assertIn(f"Overall recoverability: {NOT_RECOVERABLE_BY_SYSTEM}", text)

    def test_partial_run_recoverability_is_applied_scoped_not_reviewed_scoped(self):
        # Cluster-E isolation-net Finding 1 fix: the aggregate-ceiling
        # partial run reviews 30 ids but only applies 25 -- the raw
        # ``summary.recoverability["counts"]`` dict (queried with no
        # candidate ids, i.e. over the reviewed-union-applied set) reports
        # 25 recoverable / 5 not-recoverable, folding the 5 never-applied
        # ids in as "not recoverable". The rendered narration must NOT use
        # that wider figure -- it must report 25 recoverable / 0 not, and
        # claim RECOVERABLE_ALL, exactly the applied-only scope
        # ``audit_projection.project_redacted_audit`` uses for the same run
        # (this is the coherence fix; see test_audit_narration_isolation.py
        # for the direct cross-module proof against the real committed
        # artifact).
        with tempfile.TemporaryDirectory() as d:
            summary = self._partial_summary(d)
            raw_counts = summary.recoverability["counts"]
            self.assertEqual(raw_counts["recoverable_by_system"], 25)
            self.assertEqual(raw_counts["not_recoverable_by_system"], 5)

            text = render_bulk_run_outcome(summary)
            self.assertIn("Recoverable by this system: 25", text)
            self.assertIn("NOT recoverable by this system: 0", text)
            self.assertIn(f"Overall recoverability: {RECOVERABLE_ALL}", text)


class TestAppliedScopedRecoverabilityMatrix(unittest.TestCase):
    """Cluster-E isolation-net Finding 1 fix, synthetic-matrix half: proves
    the applied-scoped recoverability claim stays honest for every shape a
    real run's ``per_id`` claims could take, not just the all-reversible
    fixture above -- a MIX of applied ids where some are NOT recoverable
    (``recoverable_partial`` OF THE APPLIED), and an all-not-recoverable
    applied set (``not_recoverable``) -- using ``_FakeSummary`` so a
    same-tier-only real fixture is not the only case exercised."""

    def _summary(self, *, applied, skipped=(), per_id):
        return _FakeSummary(
            completed=False, finalized=False, refused=True,
            applied_unit_ids=applied, skipped_already_applied=skipped,
            recoverability={"per_id": per_id})

    def test_mix_of_applied_ids_yields_recoverable_partial_of_the_applied(self):
        # 2 of the 3 applied ids are recoverable, one is not -- a real mix.
        # A FOURTH id is reviewed-but-never-applied and marked NOT
        # recoverable in per_id (as report_run_recoverability's default,
        # unscoped query would do) -- it must be IGNORED by the applied
        # scope, never dilute the claim about what was actually applied.
        summary = self._summary(
            applied=("a", "b", "c"),
            per_id={
                "a": RECOVERABLE_BY_SYSTEM, "b": RECOVERABLE_BY_SYSTEM,
                "c": NOT_RECOVERABLE_BY_SYSTEM,
                "never-applied-reviewed-id": NOT_RECOVERABLE_BY_SYSTEM,
            })
        text = render_bulk_run_outcome(summary)
        self.assertIn("Recoverable by this system: 2", text)
        self.assertIn("NOT recoverable by this system: 1", text)
        self.assertIn(f"Overall recoverability: {RECOVERABLE_PARTIAL}", text)

    def test_all_irreversible_applied_yields_not_recoverable(self):
        summary = self._summary(
            applied=("a", "b"),
            per_id={"a": NOT_RECOVERABLE_BY_SYSTEM, "b": NOT_RECOVERABLE_BY_SYSTEM})
        text = render_bulk_run_outcome(summary)
        self.assertIn("Recoverable by this system: 0", text)
        self.assertIn("NOT recoverable by this system: 2", text)
        self.assertIn(f"Overall recoverability: {NOT_RECOVERABLE_BY_SYSTEM}", text)

    def test_all_applied_recoverable_yields_recoverable_all(self):
        summary = self._summary(
            applied=("a",), skipped=("b",),
            per_id={"a": RECOVERABLE_BY_SYSTEM, "b": RECOVERABLE_BY_SYSTEM,
                    "never-applied": NOT_RECOVERABLE_BY_SYSTEM})
        text = render_bulk_run_outcome(summary)
        self.assertIn("Recoverable by this system: 2", text)
        self.assertIn("NOT recoverable by this system: 0", text)
        self.assertIn(f"Overall recoverability: {RECOVERABLE_ALL}", text)

    def test_applied_id_missing_from_per_id_fails_safe_to_not_recoverable(self):
        # An applied id with no attached claim at all (should not happen in
        # practice -- report_run_recoverability's default query always
        # includes every applied id -- but never assumed recoverable if it
        # somehow were missing).
        summary = self._summary(applied=("a", "b"), per_id={"a": RECOVERABLE_BY_SYSTEM})
        text = render_bulk_run_outcome(summary)
        self.assertIn("Recoverable by this system: 1", text)
        self.assertIn("NOT recoverable by this system: 1", text)


# ---------------------------------------------------------------------------
# 3. Structural impossibility -- no override parameter; pure over a synthetic
#    matrix of every reachable typed-field combination.
# ---------------------------------------------------------------------------

class _FakeSummary:
    """A minimal stand-in exposing ONLY the attributes
    ``classify_bulk_run_status``/``render_bulk_run_outcome`` read -- proves
    those functions work off the typed SHAPE, not a concrete dataclass
    identity, and lets the matrix test below reach combinations a real
    ``run_sanctioned_bulk`` call would be slow to reproduce for every case."""

    def __init__(self, *, completed, finalized, refused, applied_unit_ids=(),
                skipped_already_applied=(), refusal_reason=None, recoverability=None):
        self.run_id = "fake-run"
        self.completed = completed
        self.finalized = finalized
        self.refused = refused
        self.applied_unit_ids = applied_unit_ids
        self.skipped_already_applied = skipped_already_applied
        self.refusal_reason = refusal_reason
        self.recoverability = recoverability or {}


class TestStructuralImpossibility(unittest.TestCase):

    def test_render_takes_exactly_one_argument(self):
        # No status/claim/force_success override parameter exists at all --
        # the only way to change the rendered verb is to change the typed
        # summary's own fields.
        import inspect
        sig = inspect.signature(render_bulk_run_outcome)
        self.assertEqual(len(sig.parameters), 1)

    def test_classify_takes_exactly_one_argument(self):
        import inspect
        sig = inspect.signature(classify_bulk_run_status)
        self.assertEqual(len(sig.parameters), 1)

    def test_matrix_never_renders_completed_wording_unless_truly_completed(self):
        bool_values = (False, True)
        applied_options = ((), ("row0",))
        skipped_options = ((), ("row1",))
        rec_options = (
            {},
            {"counts": {"recoverable_by_system": 0, "not_recoverable_by_system": 0,
                        "applied_total": 0}},
            {"counts": {"recoverable_by_system": 1, "not_recoverable_by_system": 0,
                        "applied_total": 1}},
            {"counts": {"recoverable_by_system": 0, "not_recoverable_by_system": 1,
                        "applied_total": 1}},
        )
        for completed in bool_values:
            for finalized in bool_values:
                for refused in bool_values:
                    for applied in applied_options:
                        for skipped in skipped_options:
                            for rec in rec_options:
                                summary = _FakeSummary(
                                    completed=completed, finalized=finalized,
                                    refused=refused, applied_unit_ids=applied,
                                    skipped_already_applied=skipped, recoverability=rec)
                                status = classify_bulk_run_status(summary)
                                text = render_bulk_run_outcome(summary)
                                with self.subTest(
                                    completed=completed, finalized=finalized,
                                    refused=refused, applied=applied, skipped=skipped,
                                    rec=rec,
                                ):
                                    is_truly_completed = (
                                        completed and finalized and not refused)
                                    self.assertEqual(
                                        status == BULK_RUN_COMPLETED, is_truly_completed)
                                    if not is_truly_completed:
                                        self.assertNotIn("COMPLETED", text)
                                        self.assertNotIn(
                                            "every planned item went through", text)
                                    else:
                                        self.assertIn("COMPLETED", text)

    def test_classification_is_independent_of_recoverability_counts_alone(self):
        # A COMPLETED summary with a recoverability dict claiming ZERO
        # recoverable must still classify COMPLETED (completion and
        # recoverability are separate axes -- recoverability counts alone
        # never downgrade a genuinely completed/finalized run, and can never
        # upgrade a genuinely refused-with-nothing-applied one either).
        summary = _FakeSummary(
            completed=True, finalized=True, refused=False,
            recoverability={"counts": {"recoverable_by_system": 0,
                                       "not_recoverable_by_system": 0,
                                       "applied_total": 0}})
        self.assertEqual(classify_bulk_run_status(summary), BULK_RUN_COMPLETED)

    def test_nonempty_recoverability_applied_total_alone_yields_partial_not_refused(self):
        # Even with empty applied_unit_ids/skipped_already_applied tuples on
        # THIS summary, a durable applied_total > 0 is enough to prove the
        # run has gone live at some point -- REFUSED must never be claimed.
        summary = _FakeSummary(
            completed=False, finalized=False, refused=True,
            recoverability={"counts": {"recoverable_by_system": 1,
                                       "not_recoverable_by_system": 0,
                                       "applied_total": 1}})
        self.assertEqual(classify_bulk_run_status(summary), BULK_RUN_PARTIAL)


# ---------------------------------------------------------------------------
# 4. READ-ONLY proof
# ---------------------------------------------------------------------------

class TestReadOnlyProof(unittest.TestCase):
    def test_scans_clean(self):
        violations = scan_paths([_RUN_NARRATION_MODULE_PATH])
        self.assertEqual(violations, [], violations)

    def test_never_references_a_write_or_mint_entrypoint_in_code(self):
        import ast
        tree = ast.parse(Path(_RUN_NARRATION_MODULE_PATH).read_text(encoding="utf-8"))
        forbidden_names = {
            "adapter_registry", "run_operation", "run_enveloped_operation",
            "run_sanctioned_bulk", "build_write_client", "write_credential_provider",
            "mint_run_envelope",
        }
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {a.name.split(".")[-1] for a in node.names} & forbidden_names
            elif isinstance(node, ast.ImportFrom):
                found |= {(node.module or "").split(".")[-1]} & forbidden_names
                found |= {a.name for a in node.names} & forbidden_names
            elif isinstance(node, ast.Name):
                found |= {node.id} & forbidden_names
            elif isinstance(node, ast.Attribute):
                found |= {node.attr} & forbidden_names
        self.assertEqual(found, set(), found)


if __name__ == "__main__":
    unittest.main()
