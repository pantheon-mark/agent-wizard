"""Tests for external_write.registered_adapters (Task 7 / F-37 — v0.13.0
Slice 2): the build-emitted static adapter registry that makes the
operator-acceptance CLI turnkey. Importing this ONE module fires every
shipped (and capability-added) adapter module's module-scope
`register_adapter`/`register_contract` call — see the module's own docstring
for the full "why" this exists.

Groups:
  1. TestShippedRegistryImportsGmail — importing the real, committed
     `external_write.registered_adapters` resolves `get_contract` AND
     `get_dispatch` for every shipped Gmail op_kind. This is literally what
     makes the documented operator-acceptance CLI turnkey for the shipped
     reference adapter (AC-T7/BI-1's "get_dispatch(proof.op_kind) non-null
     for every adapter-backed gated op").
  2. TestDivergentNonGmailAdapterResolves — mandatory anti-overfit (Global
     Constraint #3): the SAME op_kind-from-proof resolution mechanism
     (get_contract + get_dispatch) works for a divergent, non-Gmail-shaped
     adapter that registers its OWN contract + adapter AT IMPORT, exactly
     like a capability-code-scaffold-generated adapter module would —
     proving the mechanism is generic, not accidentally Gmail-specific.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.adapter_registry import get_dispatch, unregister_adapter  # noqa: E402
from external_write.contracts import get_contract, OPERATION_CONTRACTS  # noqa: E402


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "test_fixtures" / "registered_adapters"
    / "divergent_fixture_adapter.py"
)


class TestShippedRegistryImportsGmail(unittest.TestCase):
    """Importing the real, committed registered_adapters.py must fire
    adapters_gmail.py's module-scope registration — get_contract AND
    get_dispatch resolve for every shipped Gmail op_kind afterward."""

    GMAIL_OP_KINDS = (
        "gmail.message.trash", "gmail.message.untrash",
        "gmail.message.modify_labels", "gmail.filter.create",
    )

    def test_importing_registered_adapters_registers_every_shipped_gmail_op_kind(self):
        import external_write.registered_adapters  # noqa: F401
        for op_kind in self.GMAIL_OP_KINDS:
            with self.subTest(op_kind=op_kind):
                self.assertIsNotNone(get_contract(op_kind), f"{op_kind} has no contract")
                dispatch = get_dispatch(op_kind)
                self.assertIsNotNone(dispatch, f"{op_kind} has no captured dispatch")


class TestDivergentNonGmailAdapterResolves(unittest.TestCase):
    """Anti-overfit: a divergent, non-Gmail adapter module that registers its
    OWN contract + adapter at import (mirroring a capability-code-scaffold-
    emitted module, and adapters_gmail.py's own convention) resolves through
    the SAME get_contract/get_dispatch mechanism registered_adapters.py
    relies on — proving the turnkey mechanism is generic, not Gmail-shaped."""

    MODNAME = "t7_divergent_fixture_adapter_test_mod"

    def setUp(self):
        spec_obj = importlib.util.spec_from_file_location(self.MODNAME, _FIXTURE_PATH)
        module = importlib.util.module_from_spec(spec_obj)
        sys.modules[self.MODNAME] = module
        spec_obj.loader.exec_module(module)  # fires register_contract + register_adapter
        self.fixture_module = module

    def tearDown(self):
        OPERATION_CONTRACTS.pop(self.fixture_module.OP_KIND, None)
        unregister_adapter(self.fixture_module.OP_KIND)
        sys.modules.pop(self.MODNAME, None)

    def test_divergent_op_kind_contract_and_dispatch_resolve_after_import(self):
        op_kind = self.fixture_module.OP_KIND
        self.assertNotIn(op_kind, TestShippedRegistryImportsGmail.GMAIL_OP_KINDS)
        contract = get_contract(op_kind)
        self.assertIsNotNone(contract)
        dispatch = get_dispatch(op_kind)
        self.assertIsNotNone(dispatch)
        self.assertIs(dispatch.instance.__class__, self.fixture_module.DivergentFixtureAdapter)

    def test_divergent_adapter_is_field_shaped_not_label_shaped(self):
        # A structural anti-overfit sanity check: this fixture's writes
        # surface is a plain field ("Status"), never Gmail's "labels" —
        # distinct evaluation shape from every Gmail op_kind.
        contract = get_contract(self.fixture_module.OP_KIND)
        self.assertEqual(contract.writes, ("Status",))


if __name__ == "__main__":
    unittest.main()
