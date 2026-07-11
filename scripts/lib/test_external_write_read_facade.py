"""Tests for the read-only facade + write-credential injection seam (Task 4 —
external-write-gate-generalization slice). This is the keystone safety
property from the cross-vendor round-2 finding: capability/proposal code
must PHYSICALLY be unable to obtain a write-capable credential.

Four groups:
  1. TestReadFacadeDenyByDefaultAllowlist — ReadFacade exposes zero mutating
     methods; a subclass that defines an undeclared public method is refused
     at class-definition time (build-time refusal), not by a name-pattern
     scan (that is Task 5's job, exercised elsewhere).
  2. TestCredentialInjectionSeam — run_operation obtains the write-capable
     raw client from `write_credential_provider`, INSIDE the adapter
     execution path, and passes it to `adapter.apply_one`; the `client`
     argument (the pre-Task-4 stand-in) is never touched when a provider is
     supplied.
  3. TestCapabilityContextNeverCarriesWriteCredential — a capability-context
     object graph (holding only a ReadFacade + an Operation-building method)
     has no reachable attribute that is the write-capable credential.
  4. TestVendorEligibility — an op_kind with no declared read_only_scope is
     refused (ReadFacadeEligibilityError), fail-closed.

Uses fixture read-only clients / fixture write-credential providers only;
no vendor specifics (Gmail is Task 7).
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (the canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import Operation, EffectUnit  # noqa: E402
from external_write.adapters import run_operation  # noqa: E402
from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    register_adapter,
    unregister_adapter,
)
from external_write.read_facade import (  # noqa: E402
    ReadFacade,
    ReadFacadeEligibilityError,
    build_read_facade,
    get_read_only_scope,
    require_read_only_scope,
)


def _now():
    return datetime.now(timezone.utc)


def _receipt(op):
    import hashlib
    digest = hashlib.sha256(op.canonical_repr().encode()).hexdigest()
    expires_at = (_now() + timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"approved_operation_digest": digest, "expires_at": expires_at}


# ---------------------------------------------------------------------------
# Group 1: ReadFacade deny-by-default allowlist
# ---------------------------------------------------------------------------

class TestReadFacadeDenyByDefaultAllowlist(unittest.TestCase):

    def test_base_class_exposes_zero_public_methods(self):
        facade = ReadFacade(read_only_client=object())
        public_methods = [n for n in dir(facade)
                         if not n.startswith("_") and n != "read_methods"
                         and callable(getattr(facade, n))]
        self.assertEqual(public_methods, [],
                         "ReadFacade base class must expose zero public methods")

    def test_conforming_subclass_exposes_exactly_its_declared_read_methods(self):
        class _FixtureFacade(ReadFacade):
            read_methods = ("get_item", "list_items")

            def get_item(self, item_id):
                return self._read("get_item", item_id)

            def list_items(self):
                return self._read("list_items")

        class _FixtureReadOnlyClient:
            def get_item(self, item_id):
                return {"id": item_id}

            def list_items(self):
                return ["a", "b"]

        facade = _FixtureFacade(_FixtureReadOnlyClient())
        public_methods = sorted(n for n in dir(facade)
                                if not n.startswith("_") and n != "read_methods"
                                and callable(getattr(facade, n)))
        self.assertEqual(public_methods, ["get_item", "list_items"])
        self.assertEqual(facade.get_item("x"), {"id": "x"})
        self.assertEqual(facade.list_items(), ["a", "b"])

    def test_subclass_with_undeclared_public_method_is_refused_at_class_definition_time(self):
        """The deny-by-default allowlist: a subclass may not define ANY public
        method that is not listed in read_methods. This fires at class
        DEFINITION time (import time in a real module) — before a single
        instance could ever be constructed."""

        def _define_bad_subclass():
            class _BadFacade(ReadFacade):
                read_methods = ("get_item",)

                def get_item(self, item_id):
                    return self._read("get_item", item_id)

                def delete_item(self, item_id):  # undeclared -- must be refused
                    return self._read("delete_item", item_id)

            return _BadFacade

        with self.assertRaises(TypeError):
            _define_bad_subclass()

    def test_subclass_declaring_a_method_it_does_not_define_is_unaffected(self):
        """read_methods is an allowlist ceiling, not a completeness requirement
        of THIS check — declaring a name that is never implemented is a
        separate (interface-completeness) concern, not what this guard polices."""

        class _PartialFacade(ReadFacade):
            read_methods = ("get_item", "list_items")

            def get_item(self, item_id):
                return self._read("get_item", item_id)

        # Must not raise at class-definition time.
        facade = _PartialFacade(read_only_client=object())
        self.assertTrue(hasattr(facade, "get_item"))


# ---------------------------------------------------------------------------
# Fixtures shared by the credential-injection-seam tests
# ---------------------------------------------------------------------------

class _RecordingAdapter:
    """Adapter whose apply_one records exactly WHICH raw_client object it was
    called with, so a test can assert identity (not just "some call happened")."""

    def __init__(self):
        self.apply_calls = []

    def plan(self, params):
        return [EffectUnit(unit_id="u1", target_ref=params)]

    def apply_one(self, raw_client, unit):
        self.apply_calls.append(raw_client)
        raw_client.record(unit)

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return True


class _RaisingCapabilitySideClient:
    """Stands in for whatever object capability/proposal-side code passes as
    the `client` argument. Its .record RAISES if ever invoked -- proving the
    adapter path never falls back to it when a write_credential_provider is
    supplied."""

    def record(self, unit):
        raise AssertionError(
            "the capability-side client must NEVER be used for apply_one "
            "when a write_credential_provider is supplied"
        )


class _WriteCapableFake:
    """The real write-capable object -- only ever handed out by the
    write_credential_provider, INSIDE the adapter execution path."""

    def __init__(self):
        self.recorded = []

    def record(self, unit):
        self.recorded.append(unit)


class TestCredentialInjectionSeam(unittest.TestCase):

    OP_KIND = "_credential_seam_probe_op"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="reversible_external",  # ungated -- isolates the seam
        )

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        unregister_adapter(self.OP_KIND)

    def _op(self, batch_id="seam-1"):
        return Operation(
            surface="fixture_surface",
            op_kind=self.OP_KIND,
            batch_id=batch_id,
            params={"target": "x"},
        )

    def test_provider_supplied_raw_client_is_the_one_passed_to_apply_one(self):
        adapter = _RecordingAdapter()
        register_adapter(self.OP_KIND, adapter)
        op = self._op()
        write_capable = _WriteCapableFake()
        capability_side_client = _RaisingCapabilitySideClient()

        result = run_operation(
            op, _receipt(op), capability_side_client,
            write_credential_provider=lambda o: write_capable,
        )

        self.assertEqual(result.status, "written")
        self.assertEqual(len(adapter.apply_calls), 1)
        self.assertIs(adapter.apply_calls[0], write_capable)
        self.assertEqual(len(write_capable.recorded), 1)

    def test_provider_is_called_with_the_operation_being_run(self):
        adapter = _RecordingAdapter()
        register_adapter(self.OP_KIND, adapter)
        op = self._op(batch_id="seam-2")
        received = []

        def provider(passed_op):
            received.append(passed_op)
            return _WriteCapableFake()

        run_operation(op, _receipt(op), _RaisingCapabilitySideClient(),
                      write_credential_provider=provider)

        self.assertEqual(len(received), 1)
        self.assertIs(received[0], op)

    def test_no_provider_falls_back_to_client_argument_unchanged(self):
        """Backward-compatible with Task 2: when no write_credential_provider
        is supplied, the `client` argument is used as the raw client for
        apply_one -- unchanged from before this task."""
        adapter = _RecordingAdapter()
        register_adapter(self.OP_KIND, adapter)
        op = self._op(batch_id="seam-3")
        client = _WriteCapableFake()

        result = run_operation(op, _receipt(op), client)

        self.assertEqual(result.status, "written")
        self.assertIs(adapter.apply_calls[0], client)
        self.assertEqual(len(client.recorded), 1)


# ---------------------------------------------------------------------------
# Group 3: a capability-context object graph never carries the write credential
# ---------------------------------------------------------------------------

def _reachable_values(root, max_depth=4):
    """Bounded BFS over `root`'s instance-attribute graph (vars()-reachable
    only). Used to prove an object was never wired into a capability-context
    object graph -- an IDENTITY check, not a name-pattern scan."""
    seen = []
    seen_ids = set()
    frontier = [(root, 0)]
    while frontier:
        obj, depth = frontier.pop()
        if id(obj) in seen_ids:
            continue
        seen_ids.add(id(obj))
        seen.append(obj)
        if depth >= max_depth:
            continue
        try:
            attrs = vars(obj)
        except TypeError:
            continue
        for value in attrs.values():
            if callable(value) or value is None or isinstance(value, (str, int, float, bool)):
                continue
            frontier.append((value, depth + 1))
    return seen


class _FixtureReadOnlyClient:
    def get_status(self, object_id):
        return "Open"


class _FixtureReadFacade(ReadFacade):
    read_methods = ("get_status",)

    def get_status(self, object_id):
        return self._read("get_status", object_id)


class CapabilityContext:
    """Stands in for the object capability/proposal-side code actually
    holds: a ReadFacade to look things up, plus a method to PROPOSE an
    Operation. It is never given the write-capable credential or the
    write_credential_provider -- those live only in the adapter execution
    path (run_operation), a completely separate call."""

    def __init__(self, read_facade):
        self.read_facade = read_facade

    def propose_set_status(self, object_id, new_value, batch_id):
        return Operation(
            surface="fixture_surface",
            object_id=object_id,
            field="Status",
            new_value=new_value,
            op_kind="set_status",
            batch_id=batch_id,
        )


class TestCapabilityContextNeverCarriesWriteCredential(unittest.TestCase):

    def test_capability_context_graph_has_no_reachable_write_credential(self):
        write_capable = _WriteCapableFake()  # never handed to anything below
        facade = _FixtureReadFacade(_FixtureReadOnlyClient())
        ctx = CapabilityContext(facade)

        # The context can still do its job: build proposals via its facade.
        self.assertEqual(ctx.read_facade.get_status("obj-1"), "Open")
        op = ctx.propose_set_status("obj-1", "Complete", "batch-x")
        self.assertIsInstance(op, Operation)

        reachable = _reachable_values(ctx)
        self.assertTrue(all(obj is not write_capable for obj in reachable),
                        "the write-capable credential must not be reachable from "
                        "the capability-context object graph")

    def test_read_facade_wraps_only_the_read_only_client_never_a_write_capable_one(self):
        write_capable = _WriteCapableFake()
        read_only = _FixtureReadOnlyClient()
        facade = _FixtureReadFacade(read_only)

        self.assertIs(facade._read_only_client, read_only)
        self.assertIsNot(facade._read_only_client, write_capable)


# ---------------------------------------------------------------------------
# Group 4: vendor eligibility -- no declared read_only_scope is refused
# ---------------------------------------------------------------------------

class TestVendorEligibility(unittest.TestCase):

    OP_KIND = "_eligibility_probe_op"

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)

    def test_existing_seeded_op_kind_has_no_declared_scope_and_is_ineligible(self):
        # None of the seeded status ops have declared a read_only_scope --
        # they predate this field and default to None.
        self.assertIsNone(get_read_only_scope("set_status"))
        with self.assertRaises(ReadFacadeEligibilityError):
            require_read_only_scope("set_status")
        with self.assertRaises(ReadFacadeEligibilityError):
            build_read_facade("set_status", read_only_client=object())

    def test_unregistered_op_kind_fails_closed(self):
        with self.assertRaises(ReadFacadeEligibilityError):
            require_read_only_scope("_no_such_op_kind_at_all")

    def test_op_kind_with_declared_read_only_scope_is_eligible(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("__fixture__",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            read_only_scope="fixture.readonly",
        )

        self.assertEqual(get_read_only_scope(self.OP_KIND), "fixture.readonly")
        self.assertEqual(require_read_only_scope(self.OP_KIND), "fixture.readonly")

        read_only_client = _FixtureReadOnlyClient()
        facade = build_read_facade(self.OP_KIND, read_only_client, _FixtureReadFacade)
        self.assertIsInstance(facade, _FixtureReadFacade)
        self.assertIs(facade._read_only_client, read_only_client)
        self.assertEqual(facade.get_status("obj-1"), "Open")

    def test_build_read_facade_defaults_to_bare_read_facade_class(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("__fixture__",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            read_only_scope="fixture.readonly",
        )
        facade = build_read_facade(self.OP_KIND, read_only_client=object())
        self.assertIsInstance(facade, ReadFacade)


if __name__ == "__main__":
    unittest.main()
