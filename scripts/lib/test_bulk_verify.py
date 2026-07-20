"""Tests for the Task C3 (Cut 1.1 Cluster C / F-78) ``bulk-verify`` command --
`agents/lib/external_write/bulk_verify.py`.

Covers:
  * Durable-records reconciliation (``verify_bulk_run``) reads reconciled
    totals + per-id recoverability from ``run_envelope.report_run_recoverability``
    -- never a live re-scrape, never hand-authored python.
  * Final-state confirmation via the read-only facade is a SEPARATE, honestly
    -bounded best-effort: no client supplied, an ineligible op_kind, an
    ambiguous facade surface (the real, shipped Gmail facade's own surface --
    ``get_message``/``get_filter`` both qualify as single-id lookups), and a
    genuinely-confirmable unambiguous single-method facade are all exercised,
    and NONE of them ever raises to the caller (the ``.users``-style crash
    this task exists to close).
  * The CLI entrypoint: real subprocess invocation, missing-argument usage
    error, and a successful report -- never a Python traceback either way.
  * command_manifest cross-reference: the reserved "bulk-verify" prefix
    matches this module's real, physical path.
  * scan.py reports this module clean -- READ-ONLY by construction (no
    adapter_registry / run_operation / credential reference of any kind).
"""

import subprocess
import sys
import tempfile
import unittest
import unittest.mock
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
from external_write.run_envelope import mint_run_envelope, run_enveloped_operation  # noqa: E402
from external_write.scan import scan_paths  # noqa: E402
from external_write.command_manifest import find_command  # noqa: E402

from external_write.bulk_verify import (  # noqa: E402
    BulkVerifyResult,
    _confirm_via_read_facade,
    _single_id_lookup_candidates,
    verify_bulk_run,
)

_BULK_VERIFY_MODULE_PATH = str(_AGENTS_LIB / "external_write" / "bulk_verify.py")


# ---------------------------------------------------------------------------
# Fixtures -- mirrors test_external_write_run_envelope.py's own
# _FieldReadFacade/_FieldReadOnlyClient/_FieldAdapter/_FieldWriteClient
# convention (a small, reversible, field-shaped op_kind), duplicated here
# rather than imported: a three/four-class test fixture is not worth a
# cross-test-module dependency.
# ---------------------------------------------------------------------------

class _FieldWriteClient:
    def __init__(self, store):
        self._store = store

    def write_row(self, row_id, value):
        self._store[row_id] = {"value": value}


class _FieldReadOnlyClient:
    """Single unambiguous by-id lookup -- exactly one read method, one
    required parameter -- so this facade's surface is NOT ambiguous."""

    def __init__(self, store, raise_for=()):
        self._store = store
        self._raise_for = set(raise_for)

    def read_row(self, row_id):
        if row_id in self._raise_for:
            raise RuntimeError(f"fixture: {row_id} not reachable")
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


# An ambiguous fixture facade -- TWO single-id-lookup candidates, mirroring
# the real, shipped GmailReadFacade's own actually-ambiguous surface
# (get_message/get_filter both qualify) without depending on Gmail specifics.
class _AmbiguousReadOnlyClient:
    def get_a(self, a_id):
        return {"id": a_id}

    def get_b(self, b_id):
        return {"id": b_id}


class _AmbiguousReadFacade(ReadFacade):
    read_methods = ("get_a", "get_b")

    def get_a(self, a_id):
        return self._read("get_a", a_id)

    def get_b(self, b_id):
        return self._read("get_b", b_id)


def _receipt(op):
    import hashlib
    from datetime import datetime, timedelta, timezone
    digest = hashlib.sha256(op.canonical_repr().encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=900)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    return {"approved_operation_digest": digest, "expires_at": expires_at}


# ---------------------------------------------------------------------------
# 1. Facade confirmation -- honest degradation, never a crash
# ---------------------------------------------------------------------------

class TestConfirmationNoClientSupplied(unittest.TestCase):
    def test_no_read_only_client_is_honestly_not_attempted(self):
        result = _confirm_via_read_facade("anything", None, ("row1",))
        self.assertFalse(result["attempted"])
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["per_id"], {})
        self.assertIn("durable run records only", result["note"])


class TestConfirmationIneligibleOpKind(unittest.TestCase):
    def test_op_kind_with_no_contract_is_honestly_reported(self):
        result = _confirm_via_read_facade("_bv_never_registered_op_kind", object(), ("x",))
        self.assertTrue(result["attempted"])
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["per_id"], {})
        self.assertIn("no read-only confirmation channel", result["note"])

    def test_op_kind_with_no_declared_read_only_scope_is_honestly_reported(self):
        op_kind = "_bv_no_scope_op_kind"
        contracts_mod.OPERATION_CONTRACTS[op_kind] = OperationContract(
            op_kind=op_kind, writes=("X",), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="reversible_external", read_only_scope=None)
        try:
            result = _confirm_via_read_facade(op_kind, object(), ("x",))
            self.assertTrue(result["attempted"])
            self.assertFalse(result["confirmed"])
            self.assertIn("no read-only confirmation channel", result["note"])
        finally:
            contracts_mod.OPERATION_CONTRACTS.pop(op_kind, None)


class TestConfirmationAmbiguousSurface(unittest.TestCase):
    OP_KIND = "_bv_ambiguous_op_kind"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND, writes=("X",), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="reversible_external", read_only_scope="fixture.readonly")
        register_read_facade(self.OP_KIND, _AmbiguousReadFacade)

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_read_facade(self.OP_KIND)

    def test_ambiguous_surface_never_guesses_never_crashes(self):
        result = _confirm_via_read_facade(
            self.OP_KIND, _AmbiguousReadOnlyClient(), ("x",))
        self.assertTrue(result["attempted"])
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["per_id"], {})
        self.assertEqual(sorted(result["available_read_methods"]), ["get_a", "get_b"])
        self.assertIn("no single unambiguous", result["note"])

    def test_single_id_lookup_candidates_finds_both_ambiguous_methods(self):
        facade = _AmbiguousReadFacade(_AmbiguousReadOnlyClient())
        candidates = _single_id_lookup_candidates(facade, facade.read_methods)
        self.assertEqual(sorted(candidates), ["get_a", "get_b"])


class TestConfirmationRealGmailFacadeAmbiguity(unittest.TestCase):
    """Fix 1 (C3 review, Important): pins the honest-degradation claim
    against the REAL, shipped ``GmailReadFacade`` (read_facades_gmail.py) --
    not only the hand-built ``_AmbiguousReadFacade`` look-alike above. The
    module's own docstring leans on "the real, shipped Gmail facade's
    surface IS ambiguous: get_message/get_filter both qualify" as its
    motivating case; until this test, that claim was only exercised against
    a fixture that merely resembled it. This builds the REAL facade through
    the SAME sanctioned ``capability_api.build_read_facade`` two-arg path
    every capability uses (via ``_confirm_via_read_facade``, which calls it
    internally), against a minimal read-only stub client (no write method of
    any kind), and asserts it degrades HONESTLY: reports ambiguous /
    could-not-confirm, never crashes, never guesses. If a future
    GmailReadFacade surface change ever resolves the ambiguity (or
    introduces a crash), this test -- not just the fixture-based one above --
    catches it.
    """

    OP_KIND = "gmail.message.trash"  # real, contracts.py-declared Gmail op_kind

    class _StubGmailReadOnlyClient:
        """Minimal read-only stub shaped like a real gmail.readonly-scoped
        client -- methods only, no write/mutate capability of any kind, and
        NOT the real Google API client. ``_confirm_via_read_facade`` never
        actually calls a method on this client in the ambiguous-surface case
        (candidates != 1), so these method bodies are never exercised; they
        are still real, plain read-shaped methods rather than an empty
        placeholder, so this stub is honestly read-only, not merely inert."""

        def list_messages(self, query=None, max_results=None):
            return []

        def get_message(self, message_id):
            return {"id": message_id}

        def list_labels(self):
            return []

        def list_filters(self):
            return []

        def get_filter(self, filter_id):
            return {"id": filter_id}

    def test_real_gmail_read_facade_surface_degrades_honestly_not_crash(self):
        # Import (not just reference) read_facades_gmail so its module-scope
        # registration loop actually runs and populates the kernel
        # ReadFacade registry for every real Gmail op_kind -- the SAME
        # side effect a real capability's import graph triggers. Safe to
        # import even if another test module already triggered it: repeated
        # registration is idempotent (last-registered wins, same class).
        import external_write.read_facades_gmail as real_gmail_facades

        result = _confirm_via_read_facade(
            self.OP_KIND, self._StubGmailReadOnlyClient(), ("msg-1",))

        self.assertTrue(result["attempted"])
        self.assertFalse(result["confirmed"])
        self.assertEqual(result["per_id"], {})
        self.assertEqual(
            sorted(result["available_read_methods"]),
            ["get_filter", "get_message", "list_filters", "list_labels", "list_messages"],
        )
        self.assertIn("no single unambiguous", result["note"])
        self.assertNotIn("Traceback", result["note"])

        # Pin that the facade actually resolved is the REAL GmailReadFacade
        # class -- not a look-alike -- via the exact capability-facing
        # two-arg call shape (``capability_api.build_read_facade``), so this
        # test cannot silently degrade into testing something else if the
        # registry or import surface ever changes.
        from external_write.capability_api import build_read_facade as real_build_read_facade
        facade = real_build_read_facade(self.OP_KIND, self._StubGmailReadOnlyClient())
        self.assertIsInstance(facade, real_gmail_facades.GmailReadFacade)

        # And the same real facade's own introspected candidates are exactly
        # the two ambiguous methods the module docstring names.
        candidates = _single_id_lookup_candidates(facade, facade.read_methods)
        self.assertEqual(sorted(candidates), ["get_filter", "get_message"])


class TestConfirmationUnambiguousSurface(unittest.TestCase):
    OP_KIND = "_bv_unambiguous_op_kind"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND, writes=("X",), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="reversible_external", read_only_scope="fixture.readonly")
        register_read_facade(self.OP_KIND, _FieldReadFacade)

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_read_facade(self.OP_KIND)

    def test_unambiguous_single_method_is_used_to_confirm_each_id(self):
        store = {"row1": {"value": "Open"}, "row2": {"value": "Complete"}}
        client = _FieldReadOnlyClient(store, raise_for={"row2"})
        result = _confirm_via_read_facade(self.OP_KIND, client, ("row1", "row2"))
        self.assertTrue(result["attempted"])
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["available_read_methods"], ["read_row"])
        self.assertTrue(result["per_id"]["row1"]["reachable"])
        self.assertFalse(result["per_id"]["row2"]["reachable"])
        self.assertIn("not reachable", result["per_id"]["row2"]["detail"])

    def test_facade_build_failure_is_honestly_reported_not_raised(self):
        # Force a failure OTHER than ReadFacadeEligibilityError somewhere in the
        # build_read_facade chain -- proves the broad, fail-closed except-clause
        # (never a bare ReadFacadeEligibilityError-only catch) actually degrades
        # honestly instead of letting an unexpected exception reach the operator.
        with unittest.mock.patch(
            "external_write.bulk_verify.build_read_facade",
            side_effect=RuntimeError("fixture: facade construction blew up"),
        ):
            result = _confirm_via_read_facade(self.OP_KIND, object(), ("row1",))
        self.assertTrue(result["attempted"])
        self.assertFalse(result["confirmed"])
        self.assertIn("Could not build a read-only confirmation channel", result["note"])


# ---------------------------------------------------------------------------
# 2. verify_bulk_run -- durable-records reconciliation + plain-language report
# ---------------------------------------------------------------------------

class TestVerifyBulkRunDurableRecords(unittest.TestCase):
    OP_KIND = "_bv_integration_op_kind"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND, writes=("Status",), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="reversible_external", read_only_scope="fixture.readonly")
        register_read_facade(self.OP_KIND, _FieldReadFacade)
        register_adapter(self.OP_KIND, _FieldAdapter())

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)
        unregister_read_facade(self.OP_KIND)

    def _mint(self, d, run_id="bv-run-1"):
        return mint_run_envelope(
            run_id=run_id, capability_id="cap:test", op_kind=self.OP_KIND,
            contract_hash="ch", implementation_hash="ih",
            reviewed_set=[{"unit_id": "row1", "prestate_digest": "d",
                           "intended_mutation": {"value": "Complete"},
                           "category": "status", "protected_status": False}],
            population_count=50, stratification_summary={},
            operator_approval_verbatim="yes", consent_sentence_shown="Apply 1 change.",
            approved_at="2026-07-19T22:45:48Z", envelope_dir=d).envelope

    def _op(self):
        return Operation(surface="fixture_surface", op_kind=self.OP_KIND,
                         batch_id="bv-1",
                         params={"rows": [{"row_id": "row1", "intended_value": "Complete"}]})

    def test_reports_reconciled_totals_with_no_read_only_client(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            store = {"row1": {"value": "Open"}}
            op = self._op()
            run_enveloped_operation(env, op, _receipt(op), _FieldWriteClient(store),
                                    envelope_dir=d, ledger_dir=d)

            result = verify_bulk_run("bv-run-1", envelope_dir=d)

            self.assertIsInstance(result, BulkVerifyResult)
            self.assertEqual(result.counts["reviewed"], 1)
            self.assertEqual(result.counts["applied"], 1)
            self.assertEqual(result.counts["recoverable_by_system"], 1)
            self.assertFalse(result.facade_confirmation["attempted"])
            self.assertIn("reviewed:", result.operator_message)
            self.assertIn("recoverable by this system: 1", result.operator_message)
            self.assertNotIn("Traceback", result.operator_message)

    def test_reports_confirmed_final_state_when_client_supplied(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            store = {"row1": {"value": "Open"}}
            op = self._op()
            run_enveloped_operation(env, op, _receipt(op), _FieldWriteClient(store),
                                    read_only_client=_FieldReadOnlyClient(store),
                                    envelope_dir=d, ledger_dir=d)

            result = verify_bulk_run(
                "bv-run-1", envelope_dir=d,
                read_only_client=_FieldReadOnlyClient(store))

            self.assertTrue(result.facade_confirmation["attempted"])
            self.assertTrue(result.facade_confirmation["confirmed"])
            self.assertTrue(result.facade_confirmation["per_id"]["row1"]["reachable"])
            self.assertIn("Final-state confirmation", result.operator_message)

    def test_absent_run_id_reports_honest_zero_counts_no_crash(self):
        with tempfile.TemporaryDirectory() as d:
            result = verify_bulk_run("bv-never-minted", envelope_dir=d)
            self.assertEqual(result.counts["reviewed"], 0)
            self.assertEqual(result.counts["applied"], 0)
            self.assertEqual(result.counts["recoverable_by_system"], 0)
            self.assertFalse(result.facade_confirmation["attempted"])
            self.assertNotIn("Traceback", result.operator_message)

    def test_operator_message_states_whole_command_is_read_only_up_front(self):
        # Fix 2 (C3 review, self-describing gap): the plan's Task C3
        # requires each operator-facing command to be self-describing
        # (states read-only / blast-radius in plain language). Before this
        # fix, "read-only" only appeared inside the facade-confirmation
        # sub-note -- easy to miss, and silent when facade confirmation
        # isn't attempted at all. This asserts a clear, plain-language
        # WHOLE-COMMAND read-only statement is the very FIRST line of the
        # operator_message banner, regardless of facade-confirmation outcome.
        with tempfile.TemporaryDirectory() as d:
            result = verify_bulk_run("bv-never-minted-either", envelope_dir=d)
            first_line = result.operator_message.splitlines()[0]
            self.assertIn("read-only", first_line.lower())
            self.assertIn("no changes", first_line.lower())
            self.assertNotIn("Traceback", result.operator_message)

    def test_candidate_unit_ids_scopes_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            env = self._mint(d)
            store = {"row1": {"value": "Open"}}
            op = self._op()
            run_enveloped_operation(env, op, _receipt(op), _FieldWriteClient(store),
                                    envelope_dir=d, ledger_dir=d)

            result = verify_bulk_run(
                "bv-run-1", envelope_dir=d, candidate_unit_ids=["row1", "ghost"])

            self.assertEqual(result.per_id["row1"], "recoverable_by_system")
            self.assertEqual(result.per_id["ghost"], "not_recoverable_by_system")
            self.assertEqual(result.counts["recoverable_by_system"], 1)
            self.assertEqual(result.counts["not_recoverable_by_system"], 1)


# ---------------------------------------------------------------------------
# 3. command_manifest cross-reference -- the reserved prefix matches reality
# ---------------------------------------------------------------------------

class TestCommandManifestCrossReference(unittest.TestCase):
    def test_reserved_bulk_verify_prefix_matches_this_modules_real_path(self):
        entry = find_command("bulk-verify")
        self.assertIsNotNone(entry)
        self.assertEqual(
            entry.command_prefix,
            "python3 agents/lib/external_write/bulk_verify.py")
        # And the file genuinely exists at exactly that relative path from the
        # canonical single-home root.
        real_path = _AGENTS_LIB / "external_write" / "bulk_verify.py"
        self.assertTrue(real_path.is_file(), real_path)

    def test_bulk_verify_is_allowlist_eligible(self):
        from external_write.command_manifest import is_allowlist_eligible
        entry = find_command("bulk-verify")
        self.assertTrue(is_allowlist_eligible(entry))


# ---------------------------------------------------------------------------
# 4. READ-ONLY proof
# ---------------------------------------------------------------------------

class TestReadOnlyProof(unittest.TestCase):
    def test_scans_clean(self):
        violations = scan_paths([_BULK_VERIFY_MODULE_PATH])
        self.assertEqual(violations, [], violations)

    def test_never_imports_adapter_registry_or_the_envelope_write_entrypoints(self):
        # AST-level, not a docstring substring search -- this module's own
        # docstring legitimately DISCUSSES run_operation/run_enveloped_operation
        # in prose (explaining what it deliberately does not do), so a bare
        # substring ban would false-positive on its own documentation. What
        # actually matters -- proven here -- is that no ast.Import/ImportFrom
        # names adapter_registry, and no ast.Name/Attribute anywhere in the
        # code (not the docstring) resolves to run_operation /
        # run_enveloped_operation / run_sanctioned_bulk / build_write_client /
        # write_credential_provider. scan.py's own clean-scan test above is
        # the authoritative, deterministic proof of this; this test pins the
        # same guarantee independently, in case scan.py's own rule set ever
        # narrows.
        import ast
        tree = ast.parse(Path(_BULK_VERIFY_MODULE_PATH).read_text(encoding="utf-8"))
        forbidden_names = {
            "adapter_registry", "run_operation", "run_enveloped_operation",
            "run_sanctioned_bulk", "build_write_client", "write_credential_provider",
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


# ---------------------------------------------------------------------------
# 5. CLI entrypoint -- real subprocess, never a traceback
# ---------------------------------------------------------------------------

class BulkVerifyCLITests(unittest.TestCase):
    OP_KIND = "_bv_cli_op_kind"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND, writes=("Status",), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="reversible_external", read_only_scope="fixture.readonly")
        register_read_facade(self.OP_KIND, _FieldReadFacade)
        register_adapter(self.OP_KIND, _FieldAdapter())

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)
        unregister_read_facade(self.OP_KIND)

    def _run_cli(self, *args, timeout=30):
        return subprocess.run(
            [sys.executable, _BULK_VERIFY_MODULE_PATH, *args],
            capture_output=True, text=True, timeout=timeout,
        )

    def test_missing_run_id_exits_nonzero_without_traceback(self):
        result = self._run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage", result.stdout.lower())
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_absent_run_reports_honest_zero_counts_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            result = self._run_cli("cli-never-minted", d)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("reviewed:", result.stdout)
            self.assertNotIn("Traceback", result.stdout)
            self.assertNotIn("Traceback", result.stderr)

    def test_real_run_reports_reconciled_totals_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            env = mint_run_envelope(
                run_id="cli-run-1", capability_id="cap:test", op_kind=self.OP_KIND,
                contract_hash="ch", implementation_hash="ih",
                reviewed_set=[{"unit_id": "row1", "prestate_digest": "d",
                               "intended_mutation": {"value": "Complete"},
                               "category": "status", "protected_status": False}],
                population_count=50, stratification_summary={},
                operator_approval_verbatim="yes", consent_sentence_shown="Apply 1 change.",
                approved_at="2026-07-19T22:45:48Z", envelope_dir=d)
            self.assertTrue(env.accepted, env.reason)
            store = {"row1": {"value": "Open"}}
            op = Operation(surface="fixture_surface", op_kind=self.OP_KIND,
                           batch_id="cli-1",
                           params={"rows": [{"row_id": "row1", "intended_value": "Complete"}]})
            run_enveloped_operation(env.envelope, op, _receipt(op), _FieldWriteClient(store),
                                    envelope_dir=d, ledger_dir=d)

            result = self._run_cli("cli-run-1", d)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("recoverable by this system: 1", result.stdout)
            self.assertIn("durable run records only", result.stdout)
            self.assertNotIn("Traceback", result.stdout)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
