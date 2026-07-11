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
    unregister_adapter,
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


if __name__ == "__main__":
    unittest.main()
