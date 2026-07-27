"""SECONDARY GATE: a project whose sibling module names share nothing with
its capability id must still resolve end to end.

Every id-derived name diverges AT ONCE -- adapter, read facade, and op_kind.
A prior version of this kind of fixture diverged only the adapter's filename
and left the read facade's filename conforming to the capability id. That
proved the one shape it was built to catch and stayed blind to the very next
instance of the same class, one axis over: a resolver that reads what a
module DECLARES rather than guessing its filename has to be proven against
every id-derived name at once, or it is only proven against the name someone
happened to remember.

The capability module's own name is deliberately NOT scrambled here: that one
name is guaranteed to match the capability id by an enforced identity
invariant, so scrambling it would test an invariant violation, not this
class of defect.

Two things beyond a topology-only check:

  * `test_ADDING_a_new_id_derived_name_without_diverging_it_FAILS` derives the
    set of names it checks from this module's OWN namespace (see
    `_id_derived_constants`) rather than a fixed list -- so a future
    constant, named by the stated convention, is covered automatically
    without anyone having to remember to add it to a check.
  * `HostileNamingRealKernelPathTests` goes through the real runtime entrypoint
    (`capability_runner.build_capability_read_facade` /
    `resolve_read_facade_class`), not just the resolver it is built on --
    proof that the path an operator project actually executes tolerates
    hostile naming, not only the function that reads declarations off disk.

Run: python3 -m unittest discover -s wizard/scripts/lib -p test_hostile_naming_topology.py
"""
import importlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_WIZARD = Path(__file__).resolve().parents[2]
_SCRIPTS_LIB = _WIZARD / "scripts" / "lib"
_AGENTS_LIB = _WIZARD / "agents" / "lib"
for _p in (str(_SCRIPTS_LIB), str(_AGENTS_LIB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_CAPABILITY_ID = "vendor_cleanup"          # invariant-owned: conforms
_OP_KIND = "archive_vendor_record"         # shares nothing with the id
_ADAPTER_STEM = "adapters_legacy_vendor"   # diverges
_FACADE_STEM = "read_facades_inbox"        # diverges, AND collides with a real name


def _id_derived_constants():
    """Every module-level string constant in this fixture that names a
    sibling file or an operation, and therefore must never share a substring
    with the capability id.

    Derived from this module's OWN namespace rather than a fixed list of
    names: any global whose name ends in ``_STEM`` (a filename stem) or
    ``_OP_KIND`` (an operation name) is picked up automatically. NAMING
    CONVENTION for anyone adding a new id-derived constant to this file:
    end its name in one of those two suffixes and it is covered by this
    check with no further edit -- a constant named any other way is exactly
    how the class of defect this file exists to catch slips back in.

    ``_CAPABILITY_ID`` itself is excluded by construction (it does not end
    in either suffix): it is the one name this fixture is not free to
    diverge -- see the module docstring.
    """
    return {
        name: value for name, value in globals().items()
        if (name.endswith("_STEM") or name.endswith("_OP_KIND"))
        and isinstance(value, str)
    }


class HostileNamingTopologyTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.lib = self.root / "agents" / "lib" / "external_write"
        self.lib.mkdir(parents=True)
        caps = self.root / "agents" / "capabilities"
        caps.mkdir(parents=True)
        (caps / f"{_CAPABILITY_ID}_capability.py").write_text(
            f'OP_KIND = "{_OP_KIND}"\n', encoding="utf-8")
        (self.lib / f"{_ADAPTER_STEM}.py").write_text(
            f'OP_KIND = "{_OP_KIND}"\n'
            'class LegacyVendorAdapter: pass\n'
            'register_adapter(OP_KIND, LegacyVendorAdapter())\n', encoding="utf-8")
        (self.lib / f"{_FACADE_STEM}.py").write_text(
            f'OP_KIND = "{_OP_KIND}"\n'
            'class LegacyVendorReadFacade: pass\n'
            'register_read_facade(OP_KIND, LegacyVendorReadFacade)\n',
            encoding="utf-8")

    def test_read_facade_resolves_despite_a_hostile_filename(self):
        from topology import build_topology
        d = build_topology(self.lib).find_read_facade(_OP_KIND)
        self.assertEqual(d.module_stem, _FACADE_STEM)
        self.assertEqual(d.symbol, "LegacyVendorReadFacade")

    def test_adapter_resolves_despite_a_hostile_filename(self):
        from topology import build_topology
        self.assertEqual(build_topology(self.lib).find_adapter(_OP_KIND).symbol,
                         "LegacyVendorAdapter")

    def test_upgrade_attribution_uses_the_capability_id_not_the_adapter_stem(self):
        import upgrade_reconcile
        self.assertEqual(
            upgrade_reconcile.attribute_adapter_to_capability(
                self.root, f"agents/lib/external_write/{_ADAPTER_STEM}.py"),
            _CAPABILITY_ID)

    def test_ADDING_a_new_id_derived_name_without_diverging_it_FAILS(self):
        """Guard on the fixture itself, derived STRUCTURALLY (see
        `_id_derived_constants`) rather than a fixed list of names to check --
        a fixed list only protects the names someone remembered to enter into
        it, which is exactly the shape of the defect this whole file exists
        to close one level up. If a future edit makes any sibling name share
        the capability id, this fixture has stopped testing the class it
        exists to test, and this must fail to say so."""
        constants = _id_derived_constants()
        # Sanity check on the derivation itself: if the naming convention
        # drifted (e.g. every constant got renamed away from *_STEM/*_OP_KIND),
        # an empty dict here would make the loop below vacuously pass without
        # checking anything at all -- silently reintroducing exactly the
        # blindness this test exists to prevent.
        self.assertGreaterEqual(
            len(constants), 3,
            "the structural derivation in _id_derived_constants found fewer "
            "than the 3 known id-derived constants -- has the *_STEM/"
            "*_OP_KIND naming convention drifted?")
        for name, value in constants.items():
            self.assertNotIn(_CAPABILITY_ID, value,
                             f"{name} = {value!r} conforms to the capability "
                             "id -- diverge it")


#: A correctly shaped adapter -- unlike the AST-only fixture above, this one
#: is actually IMPORTED (registering itself, exactly as a real project's
#: module does), so `HostileNamingRealKernelPathTests` exercises the real
#: dispatch registry the kernel reads from, not a hand-built stand-in.
_KERNEL_ADAPTER_SRC = f'''\
"""An adapter filed under a name that shares nothing with the capability it
serves."""
from typing import Any

from external_write.adapter_registry import register_adapter
from external_write.contracts import OperationContract, register_contract

OP_KIND = "{_OP_KIND}"

register_contract(OperationContract(
    op_kind=OP_KIND,
    writes=("__record__",),
    produces=(),
    dependency_set=(),
    verifier_set=("prestate_snapshot_diff_v1",),
    introduces_persistent_binding=False,
    read_only_scope="acme.records.readonly",
))


class HostileNamedAdapter:
    def plan(self, params: Any):
        return []

    def apply_one(self, raw_client: Any, unit: Any) -> None:
        return None

    def undo_one(self, raw_client: Any, unit: Any) -> None:
        return None

    def verify_one(self, observer: Any, unit: Any) -> Any:
        return None

    def build_read_only_client(self, op: Any) -> Any:
        class _Client:
            def list_records(self):
                return ["r1", "r2"]
        return _Client()


register_adapter(OP_KIND, HostileNamedAdapter())
'''

#: A read facade filed under a name that shares nothing with either the
#: capability id or the op_kind it declares.
_KERNEL_FACADE_SRC = f'''\
"""A read-only facade filed under a name that shares nothing with the
capability id or the op_kind it declares."""
from external_write.read_facade import ReadFacade, register_read_facade

OP_KIND = "{_OP_KIND}"


class HostileNamedReadFacade(ReadFacade):
    read_methods = ("list_records",)

    def list_records(self):
        return self._read("list_records")


register_read_facade(OP_KIND, HostileNamedReadFacade)
'''

_KERNEL_CAPABILITY_SRC = f'''\
"""A read-dependent capability, run by the kernel. Its own module name
legitimately conforms to the capability id -- see the module docstring for
why that one name is not part of what this file diverges."""

OP_KIND = "{_OP_KIND}"


def propose_operations(facade, batch_id, context=None):
    return list(facade.list_records())
'''


class HostileNamingRealKernelPathTests(unittest.TestCase):
    """The topology-level tests above prove the RESOLVER can find the right
    declaration by reading what a module says, not what it is named. They do
    not prove the KERNEL actually runs a capability through that resolution.
    This class goes through the real entrypoint
    (`capability_runner.resolve_read_facade_class` /
    `build_capability_read_facade` / `run_capability_proposal`) against the
    same hostile names, so what is under test is the path an operator
    project actually executes, not a stand-in for it.

    Registers into process-global registries (the adapter/contract/read-facade
    registries every real project shares); every mutation made in `setUp` is
    reversed via `addCleanup`, in the same style already established by
    `test_capability_runner.py` in this directory -- a test that leaks a
    global registration here has previously turned an unrelated suite red
    depending on discovery order.
    """

    def setUp(self):
        import external_write as _ew
        from external_write import capability_runner as cr
        from external_write import contracts as _contracts
        from external_write.adapter_registry import unregister_adapter
        from external_write.read_facade import unregister_read_facade

        self._cr = cr

        # A scratch stand-in for a real project's agents/lib/external_write
        # directory, carrying only the hostile-named adapter + read facade
        # modules -- what the kernel scans and imports from for the duration
        # of this test.
        self.facade_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.facade_dir, ignore_errors=True)
        (self.facade_dir / f"{_ADAPTER_STEM}.py").write_text(
            _KERNEL_ADAPTER_SRC, encoding="utf-8")
        (self.facade_dir / f"{_FACADE_STEM}.py").write_text(
            _KERNEL_FACADE_SRC, encoding="utf-8")

        # The kernel resolves a read facade by scanning the directory its own
        # module file lives in, then importing whichever file there declares
        # the op_kind it needs -- so, for the duration of this test,
        # `capability_runner`'s own reported location and `external_write`'s
        # own import search path both point at the scratch directory above.
        orig_cr_file = cr.__file__
        cr.__file__ = str(self.facade_dir / "capability_runner.py")
        self.addCleanup(setattr, cr, "__file__", orig_cr_file)
        _ew.__path__.append(str(self.facade_dir))
        self.addCleanup(_ew.__path__.remove, str(self.facade_dir))

        # The adapter registers itself (a contract + itself) as a side effect
        # of being imported -- exactly as a real project's module does; never
        # called directly by this test.
        importlib.import_module(f"external_write.{_ADAPTER_STEM}")
        self.addCleanup(sys.modules.pop, f"external_write.{_ADAPTER_STEM}", None)
        self.addCleanup(sys.modules.pop, f"external_write.{_FACADE_STEM}", None)
        self.addCleanup(unregister_adapter, _OP_KIND)
        self.addCleanup(unregister_read_facade, _OP_KIND)
        self.addCleanup(_contracts.OPERATION_CONTRACTS.pop, _OP_KIND, None)

        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        caps = self.root / "agents" / "capabilities"
        caps.mkdir(parents=True)
        (caps / f"{_CAPABILITY_ID}_capability.py").write_text(
            _KERNEL_CAPABILITY_SRC, encoding="utf-8")
        self.addCleanup(sys.modules.pop, f"{_CAPABILITY_ID}_capability", None)

    def test_the_kernel_resolves_the_read_facade_class_through_hostile_names(self):
        facade_cls = self._cr.resolve_read_facade_class(self.root, _CAPABILITY_ID)
        self.assertEqual(facade_cls.__name__, "HostileNamedReadFacade")
        self.assertEqual(facade_cls.__module__, f"external_write.{_FACADE_STEM}")

    def test_the_kernel_builds_a_working_read_facade_through_hostile_names(self):
        facade = self._cr.build_capability_read_facade(self.root, _CAPABILITY_ID)
        self.assertEqual(list(facade.list_records()), ["r1", "r2"])

    def test_the_kernel_runs_the_capabilitys_proposal_step_through_hostile_names(self):
        ops = self._cr.run_capability_proposal(
            self.root, _CAPABILITY_ID, batch_id="probe")
        self.assertEqual(ops, ["r1", "r2"])


if __name__ == "__main__":
    unittest.main()
