"""Tests for post-apply RUN-TIME verification wired into the common adapter
execution path (Task 3, A2 run-time — v0.12.0 Slice 1): the exact F-41
regression.

Before this task, `adapters._run_adapter_operation` looped `apply_one` and
returned `Result(status="written", detail={"units_applied": N})` — it NEVER
called `verify_one`, which `adapter_registry.py` documented as "not
invoked...reserved for a later task." So the substrate reported "written"
without ever checking the REAL external surface: the estate dogfood's
"verified" claim came from the substrate's own manifest, and a 118-vs-120
divergence surfaced only because the operator counted the Trash by hand. That
is F-41.

The fix (design §2, run-time half): after the apply loop, for each applied
unit the KERNEL OBSERVES the real surface through the READ-ONLY FACADE
(`read_facade.build_read_facade`, built from a read-only-scoped client — NEVER
the write-capable client `apply_one` used; credential isolation), constructs
an `evidence.AdapterEvidence` from that real observation, and evaluates the
adapter's OWN captured `verify_apply_landed` predicate. A per-unit
`verification_status` is recorded into `Result.detail["verification"]`. If the
real surface cannot be queried, or the predicate does not confirm, the status
is the HONEST `applied_not_verified` — NEVER "verified".

Anti-overfit (Global Constraint #3) — proven on ≥2 DIVERGENT op_kinds:

  1. A field/spreadsheet-shaped throwaway fixture (reversible_external,
     ungated) with a FIXTURE read path — driven end-to-end through
     `run_operation`, so the whole kernel wiring (apply -> verify -> detail)
     is exercised, including the credential-isolation dual-object proof (the
     write-capable client is used ONLY for the write; the verification read
     goes to a SEPARATE read-only client).
  2. gmail.message.trash — the REAL production adapter (adapters_gmail.py)
     with its REAL registered read facade (read_facades_gmail.GmailReadFacade),
     driven through the kernel verification function `_verify_applied_units`
     directly (OP_TRASH is a gated sensitive_data op_kind; this test isolates
     the run-time-verification mechanism from the separate write-gate).

Runner: unittest, from wizard/scripts.
"""

import hashlib
import inspect
import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.operations import Operation, EffectUnit  # noqa: E402
from external_write.adapters import run_operation, _verify_applied_units  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    register_adapter, unregister_adapter, get_dispatch,
)
from external_write.read_facade import (  # noqa: E402
    ReadFacade, register_read_facade, unregister_read_facade,
)
# Importing this module populates the kernel read-facade registry for the four
# real Gmail op_kinds (register_read_facade at module scope) AND registers the
# real Gmail adapters — the "real read facade" half of anti-overfit exemplar 2.
import external_write.read_facades_gmail  # noqa: E402,F401
import external_write.adapters_gmail  # noqa: E402,F401
from external_write.adapters_gmail import OP_TRASH, GmailMessageTrashAdapter  # noqa: E402


def _receipt(op):
    """A minimal, valid receipt for `op` (mirrors the receipt contract used
    across the external_write suite: approved_operation_digest == op.digest(),
    expires_at in the future)."""
    from datetime import datetime, timedelta, timezone
    digest = hashlib.sha256(op.canonical_repr().encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=900)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    return {"approved_operation_digest": digest, "expires_at": expires_at}


# ===========================================================================
# Exemplar 1: field/spreadsheet-shaped fixture, end-to-end through
# run_operation, with a FIXTURE read path.
# ===========================================================================

class _FieldWriteClient:
    """The WRITE-CAPABLE client — the object apply_one mutates. Deliberately
    exposes NO read method the field verify_one needs (`read_row`): if the
    kernel ever wrongly handed THIS to verify_one as the observer, the read
    would AttributeError -> applied_not_verified, never a false 'verified'.
    Records every write so a test can assert it was used ONLY for the write."""

    def __init__(self, store):
        self._store = store
        self.write_calls = []

    def write_row(self, row_id, value):
        self.write_calls.append((row_id, value))
        self._store[row_id] = {"value": value}


class _FieldReadOnlyClient:
    """The READ-ONLY-scoped client the ReadFacade wraps. A SEPARATE object
    from the write client — the credential-isolation crux: the verification
    read reaches the surface through THIS, never the write client. Records
    every read so a test can assert the verify read landed here."""

    def __init__(self, store):
        self._store = store
        self.read_calls = []

    def read_row(self, row_id):
        self.read_calls.append(row_id)
        return dict(self._store.get(row_id, {}))


class _FieldReadFacade(ReadFacade):
    read_methods = ("read_row",)

    def read_row(self, row_id):
        return self._read("read_row", row_id)


class _FieldAdapter:
    """Verb-shaped field adapter. `land` controls whether apply_one actually
    mutates the surface: land=False simulates the F-41 shape — apply_one
    returns WITHOUT raising, but the real surface never changed, so an honest
    real-surface check must report applied_not_verified, not 'verified'."""

    def __init__(self, land=True):
        self._land = land

    def plan(self, params):
        params = params or {}
        return [EffectUnit(unit_id=r["row_id"], target_ref=r)
                for r in params.get("rows", [])]

    def apply_one(self, raw_client, unit):
        if self._land:
            raw_client.write_row(unit.unit_id, unit.target_ref["intended_value"])
        # land=False: return without raising and WITHOUT writing — the surface
        # is untouched despite apply_one "succeeding".

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        """READ-ONLY observer: reads the row via the facade (never a
        write-capable client), returns the observed value alongside the
        intended value so verify_apply_landed can compare them."""
        observed = observer.read_row(unit.unit_id)
        return {"value": observed.get("value"),
                "intended_value": unit.target_ref["intended_value"]}

    def verify_apply_landed(self, evidence):
        """Landed iff the OBSERVED poststate value equals the intended value."""
        return evidence.poststate.get("value") == evidence.poststate.get("intended_value")


class TestFieldOpRunTimeVerification(unittest.TestCase):

    OP_KIND = "_run_time_verify_field_probe"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="reversible_external",  # ungated — isolates run-time verification
            read_only_scope="fixture.readonly",
        )
        register_read_facade(self.OP_KIND, _FieldReadFacade)

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)
        unregister_read_facade(self.OP_KIND)

    def _op(self, batch_id="rt-1"):
        return Operation(
            surface="fixture_surface",
            op_kind=self.OP_KIND,
            batch_id=batch_id,
            params={"rows": [{"row_id": "row1", "intended_value": "Complete"}]},
        )

    def test_applied_and_confirmed_is_verified(self):
        store = {"row1": {"value": "Open"}}
        write_client = _FieldWriteClient(store)
        read_only_client = _FieldReadOnlyClient(store)
        register_adapter(self.OP_KIND, _FieldAdapter(land=True))

        op = self._op()
        result = run_operation(op, _receipt(op), write_client,
                               read_only_client=read_only_client)

        self.assertEqual(result.status, "written")
        per_unit = result.detail["verification"]["per_unit"]
        self.assertEqual(per_unit["row1"]["status"], "verified")
        self.assertEqual(result.detail["verification"]["verified_count"], 1)
        self.assertEqual(result.detail["verification"]["applied_not_verified_count"], 0)

    def test_applied_but_unverifiable_no_read_only_client_is_applied_not_verified(self):
        """No read-only client supplied => the real surface cannot be queried
        => honest applied_not_verified, NEVER 'verified' (the apply still
        happened; verification is reported separately and honestly)."""
        store = {"row1": {"value": "Open"}}
        write_client = _FieldWriteClient(store)
        register_adapter(self.OP_KIND, _FieldAdapter(land=True))

        op = self._op()
        result = run_operation(op, _receipt(op), write_client)  # no read_only_client

        self.assertEqual(result.status, "written")  # apply itself succeeded
        per_unit = result.detail["verification"]["per_unit"]
        self.assertEqual(per_unit["row1"]["status"], "applied_not_verified")
        self.assertNotEqual(per_unit["row1"]["status"], "verified")
        self.assertEqual(result.detail["verification"]["verified_count"], 0)
        # The apply genuinely happened even though it could not be verified.
        self.assertEqual(write_client.write_calls, [("row1", "Complete")])

    def test_apply_returned_ok_but_surface_did_not_change_is_applied_not_verified(self):
        """The F-41 heart: apply_one returns WITHOUT raising, but the real
        surface never changed. A real-surface check must catch this and report
        applied_not_verified, not the self-reported 'verified' F-41 produced."""
        store = {"row1": {"value": "Open"}}
        write_client = _FieldWriteClient(store)
        read_only_client = _FieldReadOnlyClient(store)
        register_adapter(self.OP_KIND, _FieldAdapter(land=False))  # apply is a silent no-op

        op = self._op()
        result = run_operation(op, _receipt(op), write_client,
                               read_only_client=read_only_client)

        self.assertEqual(result.status, "written")
        per_unit = result.detail["verification"]["per_unit"]
        self.assertEqual(per_unit["row1"]["status"], "applied_not_verified")
        # The read genuinely reached the real (read-only) surface and found the
        # value unchanged — not a fabricated pass.
        self.assertIn("row1", read_only_client.read_calls)

    def test_verification_read_uses_read_only_client_never_the_write_client(self):
        """Credential isolation: the write-capable client is used ONLY for the
        write; the verification read goes to the SEPARATE read-only client.
        A 'verified' result at all proves the read reached the read-only path,
        because the write client exposes no read_row (verify_one would have
        AttributeError'd into applied_not_verified if it were handed the write
        client)."""
        store = {"row1": {"value": "Open"}}
        write_client = _FieldWriteClient(store)
        read_only_client = _FieldReadOnlyClient(store)
        register_adapter(self.OP_KIND, _FieldAdapter(land=True))

        op = self._op()
        result = run_operation(op, _receipt(op), write_client,
                               read_only_client=read_only_client)

        self.assertEqual(result.detail["verification"]["per_unit"]["row1"]["status"],
                         "verified")
        # Write client: used ONLY for the write.
        self.assertEqual(write_client.write_calls, [("row1", "Complete")])
        self.assertFalse(hasattr(write_client, "read_calls"))
        # Read-only client: used for the verification read.
        self.assertEqual(read_only_client.read_calls, ["row1"])


# ===========================================================================
# Exemplar 2: gmail.message.trash — the REAL adapter + its REAL read facade,
# driven through the kernel verification function directly.
# ===========================================================================

class _MockReq:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _MockMessages:
    def __init__(self, mailbox):
        self._mailbox = mailbox

    def get(self, userId, id, format=None):
        return _MockReq(lambda: {"id": id, "labelIds": sorted(self._mailbox[id])})

    def modify(self, userId, id, body):
        def _exec():
            labels = set(self._mailbox[id])
            for l in (body.get("addLabelIds") or []):
                labels.add(l)
            for l in (body.get("removeLabelIds") or []):
                labels.discard(l)
            self._mailbox[id] = labels
            return {"id": id, "labelIds": sorted(labels)}
        return _MockReq(_exec)


class _MockUsers:
    def __init__(self, mailbox):
        self._messages = _MockMessages(mailbox)

    def messages(self):
        return self._messages


class _MockGmailService:
    """In-memory Gmail mailbox (message_id -> set(labelIds)) behind the real
    discovery-API chain shape (users().messages().modify(...).execute()). The
    WRITE-capable surface: apply_one mutates it. Deliberately does NOT expose
    the flat `get_message` the GmailReadFacade declares — so it cannot stand
    in as the read observer, mirroring real credential separation."""

    def __init__(self, messages=None):
        self.mailbox = {m: set(l) for m, l in (messages or {}).items()}
        self._users = _MockUsers(self.mailbox)

    def users(self):
        return self._users


class _GmailReadOnlyClient:
    """The read-only-scoped client the real GmailReadFacade wraps — exposes the
    flat read_methods the facade declares (get_message/...). Records reads so a
    test can confirm the verification read reached HERE, not the write surface.
    Backed by the SAME mailbox the write client mutated (shared surface, but a
    distinct, read-only-scoped client object)."""

    def __init__(self, svc):
        self._svc = svc
        self.read_calls = []

    def list_messages(self, query=None, max_results=None):
        return {"messages": [{"id": m} for m in sorted(self._svc.mailbox)]}

    def get_message(self, message_id):
        self.read_calls.append(message_id)
        return {"id": message_id, "labelIds": sorted(self._svc.mailbox[message_id])}

    def list_labels(self):
        return {"labels": []}

    def list_filters(self):
        return {"filter": []}

    def get_filter(self, filter_id):
        raise KeyError(filter_id)


class TestGmailTrashRunTimeVerification(unittest.TestCase):
    """The real Gmail trash adapter + the real registered GmailReadFacade,
    exercised through the kernel's `_verify_applied_units`."""

    def _plan_and_apply(self, svc):
        adapter = GmailMessageTrashAdapter()
        units = adapter.plan({"messages": [
            {"message_id": "m1", "prior_label_ids": ["INBOX", "IMPORTANT"]},
        ]})
        return adapter, units

    def _op(self):
        return Operation(surface="gmail", op_kind=OP_TRASH, batch_id="g1",
                         params={"messages": [{"message_id": "m1"}]})

    def test_applied_and_confirmed_is_verified(self):
        svc = _MockGmailService(messages={"m1": {"INBOX", "IMPORTANT"}})
        read_only_client = _GmailReadOnlyClient(svc)
        adapter, units = self._plan_and_apply(svc)
        adapter.apply_one(svc, units[0])  # real trash via the write surface

        result = _verify_applied_units(self._op(), get_dispatch(OP_TRASH),
                                       units, read_only_client)

        self.assertEqual(result["per_unit"]["m1"]["status"], "verified")
        self.assertEqual(result["verified_count"], 1)
        # The verification read genuinely reached the read-only client.
        self.assertIn("m1", read_only_client.read_calls)

    def test_apply_that_did_not_land_is_applied_not_verified(self):
        """The message was NEVER actually trashed (still in INBOX) — the real
        read facade reports is_trashed=False, so the predicate returns False
        and the kernel records applied_not_verified, never 'verified'."""
        svc = _MockGmailService(messages={"m1": {"INBOX", "IMPORTANT"}})
        read_only_client = _GmailReadOnlyClient(svc)
        adapter, units = self._plan_and_apply(svc)
        # DELIBERATELY do not apply — the surface still shows INBOX.

        result = _verify_applied_units(self._op(), get_dispatch(OP_TRASH),
                                       units, read_only_client)

        self.assertEqual(result["per_unit"]["m1"]["status"], "applied_not_verified")
        self.assertEqual(result["verified_count"], 0)
        self.assertIn("m1", read_only_client.read_calls)

    def test_no_read_only_client_is_applied_not_verified(self):
        svc = _MockGmailService(messages={"m1": {"INBOX"}})
        adapter, units = self._plan_and_apply(svc)
        adapter.apply_one(svc, units[0])

        result = _verify_applied_units(self._op(), get_dispatch(OP_TRASH),
                                       units, read_only_client=None)

        self.assertEqual(result["per_unit"]["m1"]["status"], "applied_not_verified")
        self.assertIn("read-only client", result["per_unit"]["m1"]["reason"])


# ===========================================================================
# Cross-cutting: fail-closed structural guarantees.
# ===========================================================================

class TestRunTimeVerificationFailsClosed(unittest.TestCase):

    OP_KIND = "_run_time_verify_no_predicate_probe"

    class _NoPredicateAdapter:
        """A registered adapter that declares NO verify_apply_landed predicate
        — the kernel cannot earn a 'verified' claim, so every unit must be
        applied_not_verified (fail-closed, never open)."""

        def plan(self, params):
            return [EffectUnit(unit_id="u1", target_ref=(params or {}))]

        def apply_one(self, raw_client, unit):
            pass

        def undo_one(self, raw_client, unit):
            pass

        def verify_one(self, observer, unit):
            return {"anything": True}

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="reversible_external",
            read_only_scope="fixture.readonly",
        )
        register_adapter(self.OP_KIND, self._NoPredicateAdapter())

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)

    def test_adapter_without_predicate_is_applied_not_verified(self):
        op = Operation(surface="fixture", op_kind=self.OP_KIND, batch_id="np-1",
                       params={"x": 1})
        result = run_operation(op, _receipt(op), object(), read_only_client=object())
        self.assertEqual(result.status, "written")
        per_unit = result.detail["verification"]["per_unit"]
        self.assertEqual(per_unit["u1"]["status"], "applied_not_verified")
        self.assertNotEqual(per_unit["u1"]["status"], "verified")

    def test_provisioner_or_facade_failure_degrades_to_applied_not_verified_never_raises(self):
        """Fail-safe: the apply already succeeded, so a verification-side
        failure (here, a read-only client whose facade build fails because the
        op_kind declares no read_only_scope) must degrade to
        applied_not_verified — never propagate an exception that would turn a
        successful write into a crash."""
        op_kind = "_run_time_verify_no_scope_probe"
        contracts_mod.OPERATION_CONTRACTS[op_kind] = OperationContract(
            op_kind=op_kind, writes=("Status",), produces=(), dependency_set=(),
            verifier_set=(), introduces_persistent_binding=False,
            risk_class="reversible_external",
            read_only_scope=None,  # ineligible for the read-only-facade model
        )

        class _P:
            def plan(self, params):
                return [EffectUnit(unit_id="u1", target_ref=(params or {}))]
            def apply_one(self, raw_client, unit):
                pass
            def undo_one(self, raw_client, unit):
                pass
            def verify_one(self, observer, unit):
                return {"ok": True}
            def verify_apply_landed(self, evidence):
                return True

        register_adapter(op_kind, _P())
        try:
            op = Operation(surface="fixture", op_kind=op_kind, batch_id="ns-1",
                           params={"x": 1})
            result = run_operation(op, _receipt(op), object(),
                                   read_only_client=object())
            self.assertEqual(result.status, "written")  # did NOT raise
            per_unit = result.detail["verification"]["per_unit"]
            self.assertEqual(per_unit["u1"]["status"], "applied_not_verified")
        finally:
            contracts_mod.OPERATION_CONTRACTS.pop(op_kind, None)
            unregister_adapter(op_kind)

    def test_kernel_verification_function_takes_read_only_client_not_write_client(self):
        """Structural credential-isolation guarantee: the run-time verification
        function's signature carries a `read_only_client` parameter and NO
        write-capable client parameter — the write client is structurally
        unavailable to the verification read."""
        params = list(inspect.signature(_verify_applied_units).parameters)
        self.assertIn("read_only_client", params)
        self.assertNotIn("raw_client", params)
        self.assertNotIn("write_client", params)


if __name__ == "__main__":
    unittest.main()
