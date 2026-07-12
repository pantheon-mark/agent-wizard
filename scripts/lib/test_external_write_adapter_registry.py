"""Tests for the static per-op_kind adapter registry (Task 2 —
external-write-gate-generalization).

Three tests:
  1. register_adapter + get_adapter round-trips a registration.
  2. an unregistered op_kind resolves to None (fail-open to the field path is
     run_operation's job, not the registry's -- the registry just answers
     "is anything registered for this op_kind").
  3. re-registering an op_kind overwrites the prior registration (last-registered
     wins; the registry does not silently keep the first one nor raise).

Uses a minimal stub Adapter; no real surface.
"""

import sys
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (the canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import EffectUnit  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    register_adapter,
    get_adapter,
    get_dispatch,
    unregister_adapter,
    AdapterDispatch,
)


class _StubAdapter:
    """Minimal Adapter-protocol-conforming stub. Records apply_one calls."""

    def __init__(self):
        self.applied = []

    def plan(self, params):
        return [EffectUnit(unit_id="u1", target_ref=params)]

    def apply_one(self, raw_client, unit):
        self.applied.append(unit)

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return True


class _BuildClientStubAdapter(_StubAdapter):
    """Stub adapter whose CLASS defines build_write_client -- for proving
    AdapterDispatch auto-captures it off the class (Task R7-T2)."""

    def build_write_client(self, op):
        return "fake-write-client"


class TestAdapterRegistry(unittest.TestCase):

    def tearDown(self):
        unregister_adapter("_registry_probe_a")
        unregister_adapter("_registry_probe_b")

    def test_register_and_lookup_round_trips(self):
        adapter = _StubAdapter()
        register_adapter("_registry_probe_a", adapter)
        self.assertIs(get_adapter("_registry_probe_a"), adapter)

    def test_unregistered_op_kind_resolves_to_none(self):
        self.assertIsNone(get_adapter("_no_such_op_kind_registered"))

    def test_reregistration_overwrites_prior_entry(self):
        first = _StubAdapter()
        second = _StubAdapter()
        register_adapter("_registry_probe_b", first)
        register_adapter("_registry_probe_b", second)
        self.assertIs(get_adapter("_registry_probe_b"), second)


class TestAdapterDispatchCapture(unittest.TestCase):
    """Task R7-T2 — cross-vendor-ratified defense-in-depth fix. register_adapter
    must ALSO capture a frozen AdapterDispatch off the adapter's CLASS
    (type(adapter)), not merely register the mutable instance. This is the
    registry-level half of the monkey-patch-inert guarantee; the run_operation-
    level half (proving a hijacked instance.apply_one/build_write_client never
    actually runs, and the write client is never leaked to it) is in
    test_external_write_adapters.py's TestCapturedDispatchMonkeyPatchIsInert."""

    def tearDown(self):
        unregister_adapter("_dispatch_probe_a")
        unregister_adapter("_dispatch_probe_b")

    def test_register_adapter_populates_get_dispatch(self):
        adapter = _StubAdapter()
        register_adapter("_dispatch_probe_a", adapter)
        dispatch = get_dispatch("_dispatch_probe_a")
        self.assertIsInstance(dispatch, AdapterDispatch)
        self.assertIs(dispatch.instance, adapter)

    def test_dispatch_methods_are_captured_off_the_class_not_the_instance(self):
        adapter = _StubAdapter()
        register_adapter("_dispatch_probe_a", adapter)
        dispatch = get_dispatch("_dispatch_probe_a")
        self.assertIs(dispatch.plan, _StubAdapter.plan)
        self.assertIs(dispatch.apply_one, _StubAdapter.apply_one)
        self.assertIs(dispatch.undo_one, _StubAdapter.undo_one)
        self.assertIs(dispatch.verify_one, _StubAdapter.verify_one)

    def test_dispatch_provision_write_client_is_none_when_class_does_not_define_it(self):
        adapter = _StubAdapter()
        register_adapter("_dispatch_probe_a", adapter)
        dispatch = get_dispatch("_dispatch_probe_a")
        self.assertIsNone(dispatch.provision_write_client)

    def test_dispatch_provision_write_client_auto_captured_when_class_defines_build_write_client(self):
        adapter = _BuildClientStubAdapter()
        register_adapter("_dispatch_probe_b", adapter)
        dispatch = get_dispatch("_dispatch_probe_b")
        self.assertIs(dispatch.provision_write_client, _BuildClientStubAdapter.build_write_client)

    def test_instance_apply_one_reassignment_does_not_change_the_captured_dispatch(self):
        """The core registry-level monkey-patch-inert proof: reassigning
        adapter.apply_one AFTER registration (an ordinary instance-attribute
        shadow -- exactly what a capability with a reference to the adapter
        instance could do) must not be visible through get_dispatch. The
        dispatch record is frozen at registration time, off the class."""
        adapter = _StubAdapter()
        register_adapter("_dispatch_probe_a", adapter)
        original_apply_one = get_dispatch("_dispatch_probe_a").apply_one

        adapter.apply_one = lambda raw_client, unit: None  # instance-level monkey-patch

        dispatch_after = get_dispatch("_dispatch_probe_a")
        self.assertIs(dispatch_after.apply_one, original_apply_one)
        self.assertIs(dispatch_after.apply_one, _StubAdapter.apply_one)

    def test_get_dispatch_unregistered_op_kind_resolves_to_none(self):
        self.assertIsNone(get_dispatch("_no_such_op_kind_registered"))

    def test_unregister_adapter_removes_both_get_adapter_and_get_dispatch(self):
        adapter = _StubAdapter()
        register_adapter("_dispatch_probe_a", adapter)
        unregister_adapter("_dispatch_probe_a")
        self.assertIsNone(get_adapter("_dispatch_probe_a"))
        self.assertIsNone(get_dispatch("_dispatch_probe_a"))


if __name__ == "__main__":
    unittest.main()
