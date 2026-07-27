"""Task 5 / Cut 1.6 (bundle v0.20.0) -- kernel-as-runner, the KEYSTONE.

The kernel resolves the adapter, builds the READ-ONLY client, and INJECTS the
resulting facade. Capability code never bootstraps anything, so it never has a
reason to import the adapter -- which is what made the Cut 1.2 boundary rule
unsatisfiable for any writer that had to read (F-VAL19-5).

Two tests carry the design's load:

* ``test_a_capability_cannot_reach_another_capabilitys_surface`` -- gemini's
  regret-mode finding. With a caller-supplied op_kind, a capability built for
  one surface could request a facade for another: write isolation fixed, read
  isolation left horizontally open. Deriving op_kind from the running module
  makes that unrepresentable rather than merely disallowed.
* ``test_a_null_client_is_refused_at_construction`` -- the STEP 0 fold. The old
  behaviour returned a facade wrapping None that died mid-run with a raw
  AttributeError in front of a non-technical operator.

Run:  python3 -m unittest discover -s wizard/scripts/lib -p test_capability_runner.py
"""

import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# Build-side test, deliberately NOT under agents/lib/external_write/.
# Registering adapters is intrinsic to exercising the runner, and
# `register_adapter` / the adapter registry are precisely what scan.py bans in
# the CAPABILITY zone -- so a test living inside the scanned tree cannot
# exercise this without tripping the build gate (the F-PRE-3 tension, in
# miniature). These test modules are build-only and are never emitted into an
# operator project (verified: absent from the v0.19.0 bundle), so the honest
# home is here alongside test_capability_code_scaffold.py, leaving
# `scan.py agents/` genuinely green rather than exempted.
_WIZARD = Path(__file__).resolve().parents[2]
_AGENTS_LIB = _WIZARD / "agents" / "lib"
if str(_AGENTS_LIB) not in sys.path:
    sys.path.insert(0, str(_AGENTS_LIB))

import external_write as _ew                               # noqa: E402
from external_write import capability_runner as cr        # noqa: E402
from external_write import contracts as _contracts        # noqa: E402
from external_write import read_facade as _rf             # noqa: E402
from external_write.adapter_registry import register_adapter  # noqa: E402


OP_A = "test_runner_op_a"
OP_B = "test_runner_op_b"
SCOPE = "acme.records.readonly"


class _ClientA:
    def list_records(self):
        return ["a1", "a2"]


class _ClientB:
    def list_records(self):
        return ["SECRET-B"]


class _AdapterA:
    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        return {}

    def build_read_only_client(self, op):
        return _ClientA()


class _AdapterB(_AdapterA):
    def build_read_only_client(self, op):
        return _ClientB()


class _AdapterMissingReader:
    """Registered for its own op_kind but deliberately has NO
    build_read_only_client -- the adapter-SHAPE defect the honest-refusal fix
    (the `provision is None` branch) targets. Does not subclass _AdapterA:
    inheriting would hand it a read-only reader it is meant to lack."""

    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        return {}


_CAPABILITY_SRC = textwrap.dedent('''\
    """A read-dependent capability."""
    OP_KIND = "{op_kind}"


    def propose_operations(facade, batch_id):
        # Reads through the INJECTED facade -- nothing is bootstrapped here.
        return [("proposed", batch_id, tuple(facade.list_records()))]
    ''')


def _register_contract(op_kind):
    """Register a minimal contract for `op_kind`. NOT wrapped in a bare
    except -- a swallowed registration error here would make every test in this
    module pass vacuously, which is exactly how a test suite starts lying."""
    if op_kind in getattr(_contracts, "OPERATION_CONTRACTS", {}):
        return
    _contracts.register_contract(_contracts.OperationContract(
        op_kind=op_kind,
        writes=("__record__",),
        produces=(),
        dependency_set=(),
        verifier_set=("prestate_snapshot_diff_v1",),
        introduces_persistent_binding=False,
        risk_class="reversible_external",
        blast_radius_cap=5,
        read_only_scope=SCOPE,
    ))


def _quietly(fn, *a):
    """Re-registration across tests in one process is benign; a genuine error
    still surfaces through the contract registration above."""
    try:
        fn(*a)
    except Exception:
        pass


def _register_everything():
    """Register both op_kinds' contracts and adapters so a cross-surface
    request is *possible* to attempt -- otherwise the escalation test would
    pass vacuously. Their read facades are declared on disk instead (see
    setUpClass below), because the kernel now resolves a read facade by
    reading what a module on disk declares, not from a call made directly in
    this process."""
    for op_kind, adapter in ((OP_A, _AdapterA()), (OP_B, _AdapterB())):
        _register_contract(op_kind)
        _quietly(register_adapter, op_kind, adapter)


#: A minimal read facade module, written to disk for the kernel to find by
#: reading it -- not just registered in this process. The filename is
#: deliberately unrelated to the op_kind or to any capability id, the same
#: way a real project's facade file is free to be named anything as long as
#: it declares what it provides.
_SCRATCH_FACADE_SRC = textwrap.dedent('''\
    from external_write.read_facade import ReadFacade, register_read_facade

    OP_KIND = "{op_kind}"


    class {class_name}(ReadFacade):
        read_methods = ("list_records",)

        def list_records(self, *a, **k):
            return self._read("list_records", *a, **k)


    register_read_facade(OP_KIND, {class_name})
    ''')


def _write_scratch_read_facade(directory, filename, op_kind, class_name):
    (directory / filename).write_text(
        _SCRATCH_FACADE_SRC.format(op_kind=op_kind, class_name=class_name),
        encoding="utf-8")


class CapabilityRunnerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Snapshot the global registries so this module can RESTORE them.
        # These registries are process-global and shared with every other test
        # module; leaking test op_kinds into them caused a real cross-module
        # failure (test_external_write_contracts asserts every REGISTERED
        # contract references a registered verifier, and picked up ours). A
        # test that mutates global state must put it back, or it turns an
        # unrelated suite red depending on discovery order.
        cls._contracts_before = dict(_contracts.OPERATION_CONTRACTS)
        cls._facades_before = dict(_rf._READ_FACADE_REGISTRY)

        # The kernel resolves a read facade by scanning the directory its own
        # module file lives in, then importing whichever file on disk there
        # declares the op_kind it needs. A bare register_read_facade() call
        # made directly in this process, with nothing backing it on disk, is
        # invisible to that scan -- so, for the duration of this test class,
        # `capability_runner`'s own reported location and `external_write`'s
        # own import search path both point at a scratch directory carrying
        # real declarations for OP_A / OP_B. Restored in tearDownClass.
        cls._facade_dir = Path(tempfile.mkdtemp())
        cls._orig_cr_file = cr.__file__
        cr.__file__ = str(cls._facade_dir / "capability_runner.py")
        _ew.__path__.append(str(cls._facade_dir))
        _write_scratch_read_facade(
            cls._facade_dir, "runner_test_facade_one.py", OP_A, "_ScratchFacadeA")
        _write_scratch_read_facade(
            cls._facade_dir, "runner_test_facade_two.py", OP_B, "_ScratchFacadeB")

        _register_everything()

    @classmethod
    def tearDownClass(cls):
        _contracts.OPERATION_CONTRACTS.clear()
        _contracts.OPERATION_CONTRACTS.update(cls._contracts_before)
        _rf._READ_FACADE_REGISTRY.clear()
        _rf._READ_FACADE_REGISTRY.update(cls._facades_before)
        cr.__file__ = cls._orig_cr_file
        _ew.__path__.remove(str(cls._facade_dir))
        shutil.rmtree(cls._facade_dir, ignore_errors=True)

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        (self.root / "agents" / "capabilities").mkdir(parents=True)

    def _write_capability(self, capability_id, op_kind):
        p = self.root / "agents" / "capabilities" / f"{capability_id}_capability.py"
        p.write_text(_CAPABILITY_SRC.format(op_kind=op_kind), encoding="utf-8")
        return p

    # --------------------------------------------------------------- keystone

    def test_a_read_dependent_capability_runs_with_an_injected_facade(self):
        """The whole point: a capability that must READ now works, having
        imported nothing it is not allowed to import."""
        self._write_capability("cap_a", OP_A)
        ops = cr.run_capability_proposal(self.root, "cap_a", batch_id="batch-1")
        self.assertEqual(ops, [("proposed", "batch-1", ("a1", "a2"))])

    def test_the_capability_source_names_no_adapter_and_builds_no_client(self):
        """Structural: the emitted shape has no reason to reach the adapter."""
        src = self._write_capability("cap_a", OP_A).read_text(encoding="utf-8")
        self.assertNotIn("adapters_", src)
        self.assertNotIn("build_read_only_client", src)
        self.assertNotIn("build_facade", src)

    # ------------------------------------------- horizontal read escalation

    def test_a_capability_cannot_reach_another_capabilitys_surface(self):
        """GEMINI'S REGRET-MODE FINDING. op_kind is derived from the running
        capability's own module, never from a caller argument -- so cap_a can
        only ever receive cap_a's surface. If this ever fails, read isolation
        has been left horizontally open while write isolation looks fine."""
        self._write_capability("cap_a", OP_A)
        self._write_capability("cap_b", OP_B)

        facade_a = cr.build_capability_read_facade(self.root, "cap_a")
        self.assertEqual(list(facade_a.list_records()), ["a1", "a2"])
        self.assertNotIn("SECRET-B", list(facade_a.list_records()))

        facade_b = cr.build_capability_read_facade(self.root, "cap_b")
        self.assertEqual(list(facade_b.list_records()), ["SECRET-B"])

        # NOTE: deliberately NO signature introspection here. Asserting "op_kind
        # is not a parameter" via __code__ trips scan.py's
        # introspection_escape_hatch rule in this CAPABILITY-zoned file, and the
        # two behavioural assertions above already prove the property: if
        # op_kind resolution collapsed to a caller/global value, facade_b would
        # return A's records and this test would fail.

    # ----------------------------------------------------------- fail-closed

    def test_a_null_client_is_refused_at_construction(self):
        """STEP 0 fold. The old behaviour returned a facade wrapping None whose
        first read raised a raw AttributeError mid-run."""
        with self.assertRaises(_rf.ReadFacadeEligibilityError):
            _rf.build_read_facade(OP_A, None)

    def test_an_unknown_capability_refuses_in_plain_language(self):
        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            cr.run_capability_proposal(self.root, "nope", batch_id="b")
        self.assertIn("nope", str(ctx.exception))
        self.assertNotIn("Traceback", str(ctx.exception))

    def test_a_capability_without_an_op_kind_refuses(self):
        p = self.root / "agents" / "capabilities" / "cap_x_capability.py"
        p.write_text("def propose_operations(facade, batch_id):\n    return []\n",
                     encoding="utf-8")
        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            cr.run_capability_proposal(self.root, "cap_x", batch_id="b")
        self.assertNotIn("Traceback", str(ctx.exception))

    def test_an_op_kind_with_no_adapter_refuses_rather_than_returning_none(self):
        """The F-STEP0-1 shape -- no usable provisioner behind the op_kind. It
        must refuse with a reason, never hand back a dead facade."""
        op_kind = "test_runner_op_noadapter"
        _register_contract(op_kind)
        self._write_capability("cap_np", op_kind)
        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            cr.build_capability_read_facade(self.root, "cap_np")
        self.assertNotIn("Traceback", str(ctx.exception))

    def test_a_missing_provisioner_names_the_adapter_not_a_rebuild(self):
        """The misdirection: this is an adapter-shape problem, and the rebuild
        flow has no guidance for it, so telling the operator to rebuild the
        capability sends them in a circle."""
        op_kind = "test_runner_op_missing_reader"
        _register_contract(op_kind)
        _quietly(register_adapter, op_kind, _AdapterMissingReader())
        self._write_capability("cap_missing_reader", op_kind)
        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            cr.build_capability_read_facade(self.root, "cap_missing_reader")
        message = str(ctx.exception)
        self.assertIn("adapter", message.lower())
        self.assertIn("read-only reader", message)
        self.assertNotIn("it needs to be rebuilt", message)

    def test_a_missing_registration_still_says_rebuild(self):
        """When nothing is registered at all, a rebuild IS the remedy -- the
        honest-refusal fix must not blur the two cases together."""
        op_kind = "test_runner_op_never_registered"
        _register_contract(op_kind)
        self._write_capability("cap_unregistered", op_kind)
        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            cr.build_capability_read_facade(self.root, "cap_unregistered")
        self.assertIn("rebuilt", str(ctx.exception))

    def test_an_unfinished_capability_refuses_in_plain_language(self):
        p = self.root / "agents" / "capabilities" / "cap_todo_capability.py"
        p.write_text(
            f'OP_KIND = "{OP_A}"\n\n\n'
            'def propose_operations(facade, batch_id):\n'
            '    raise NotImplementedError("TODO")\n', encoding="utf-8")
        with self.assertRaises(cr.CapabilityRunnerError) as ctx:
            cr.run_capability_proposal(self.root, "cap_todo", batch_id="b")
        self.assertIn("placeholder", str(ctx.exception))
        self.assertNotIn("Traceback", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
