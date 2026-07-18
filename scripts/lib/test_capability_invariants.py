"""Tests for the emitted deterministic capability-invariant battery
(external_write.capability_invariants -- Task D1-1, D-Layer-1).

This is the AWB-authored, non-LLM half of the operator project's own self-QA
(cluster D): five composed checks (routing, test-target enum, id coherence,
contract registered, post-acceptance audit) reusing existing signals from
scan.py / write_gate.py / capability_identity.py / contracts.py /
acceptance_ceremony.py -- see that module's own docstring for exactly which
existing primitive backs each check.

ANTI-OVERFIT (v0.13.0 T7 lesson, reused throughout this package's own test
suite): every fixture is written at the REAL emitted relative path
(``agents/capabilities/<capability_id>_capability.py``,
``security/capability_descriptors.json``,
``security/capability_acceptance_log.jsonl``) inside a fresh
``tempfile.TemporaryDirectory()`` -- never a ``copytree`` of the dev tree.
At least two distinct capability_ids are exercised across this file.

Each of checks 1-4 is proven to fail INDEPENDENTLY (only the one input under
test is violated; everything else in the fixture is valid), and a
fully-valid capability is proven to pass all five.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (canonical location) -- mirrors
# test_capability_health.py / test_external_write_acceptance_ceremony.py's own convention.
_AGENTS_LIB = Path(__file__).resolve().parents[2] / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import capability_invariants  # noqa: E402
from external_write.acceptance_ceremony import DEFAULT_AUDIT_LOG_PATH  # noqa: E402


CAPABILITIES_DIR_REL = "agents/capabilities"
DESCRIPTOR_SET_REL = "security/capability_descriptors.json"

# An op_kind already seeded/registered in contracts.OPERATION_CONTRACTS at import time (no
# adapter module required) -- reused so fixtures need no adapter-registration setup at all.
VALID_OP_KIND = "set_status"
# Never registered anywhere -- the deliberate check-4 violation.
UNREGISTERED_OP_KIND = "_d1_1_unregistered_probe_op"


_CLEAN_SOURCE = '''"""{name} -- gate-clean capability module (test fixture)."""

from typing import Any

OP_KIND = "{op_kind}"


def describe() -> str:
    return "{name} ready"


def propose_operations(facade: Any, batch_id: str):
    return []
'''

_CLEAN_SOURCE_WITH_SURFACE = '''"""{name} -- gate-clean capability module with a declared SURFACE (test fixture)."""

from typing import Any

OP_KIND = "{op_kind}"
SURFACE = "{surface}"


def describe() -> str:
    return "{name} ready"


def propose_operations(facade: Any, batch_id: str):
    return []
'''

_ROUTING_VIOLATION_SOURCE = '''"""{name} -- capability wired to the raw kernel write primitive (test fixture)."""

from typing import Any

OP_KIND = "{op_kind}"

from external_write.adapters import run_operation


def propose_operations(facade: Any, batch_id: str):
    return []


def run():
    return run_operation
'''


def _base_descriptor_entry(capability_id, **overrides):
    entry = {
        "id": capability_id,
        "name": capability_id,
        "action_class": "in_place_edit",
        "risk_class": "reversible_external",
        "recovery_profile_ref": None,
        "declared_test_target": "copy",
        "blast_radius_cap": 5,
        "accepted": False,
    }
    entry.update(overrides)
    return entry


class CapabilityInvariantsTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_capability(self, capability_id: str, source: str) -> Path:
        d = self.project_root / CAPABILITIES_DIR_REL
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{capability_id}_capability.py"
        path.write_text(source, encoding="utf-8")
        return path

    def _write_descriptor_set(self, entries):
        path = self.project_root / DESCRIPTOR_SET_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries), encoding="utf-8")

    def _write_audit_record(self, capability_id, phase_id, **extra):
        path = self.project_root / DEFAULT_AUDIT_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": "capability_acceptance_record-v1",
            "capability_id": capability_id,
            "phase_id": phase_id,
        }
        record.update(extra)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def _check(self, capability_id):
        return capability_invariants.check_capability_invariants(
            str(self.project_root), capability_id)

    def _write_project_file(self, relpath: str, content: str) -> Path:
        """Write ``content`` at ``relpath`` under ``self.project_root`` -- used
        by the D1-2 test-quality fixtures to place a capability's test file at
        a real-shaped relative path (there is no fixed convention for WHERE a
        capability's test lives -- see capability_invariants.py's D1-2 module
        docstring -- so discovery must find it, not assume it)."""
        path = self.project_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _check_quality(self, capability_id):
        return capability_invariants.check_test_quality(
            str(self.project_root), capability_id)

    def _assert_no_traceback(self, result):
        self.assertNotIn("Traceback", result.operator_message)


class TestFullyValidCapabilityPassesAll(CapabilityInvariantsTestBase):
    def test_fully_valid_capability_passes_all_checks(self):
        cap_id = "acme_status_sync"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Acme Status Sync", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")
        self.assertEqual(result.failures, [])
        self._assert_no_traceback(result)

    def test_second_distinct_capability_also_passes_all_checks(self):
        # A second, differently-named capability_id -- proves the battery is not
        # accidentally keyed to the first fixture's id.
        cap_id = "beta_priority_sync"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Beta Priority Sync", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")
        self._assert_no_traceback(result)


class TestRoutingCheckIndependent(CapabilityInvariantsTestBase):
    def test_raw_run_operation_reference_fails_only_routing(self):
        cap_id = "routing_violation_cap"
        self._write_capability(
            cap_id,
            _ROUTING_VIOLATION_SOURCE.format(name="Routing Violation Cap", op_kind=VALID_OP_KIND),
        )
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Routing:") for f in result.failures),
            f"expected a Routing failure, got {result.failures!r}",
        )
        self.assertFalse(
            any(f.startswith("Test target:") for f in result.failures),
            f"test-target check should not fail for this fixture: {result.failures!r}",
        )
        self.assertFalse(
            any(f.startswith("Contract registered:") for f in result.failures),
            f"contract-registered check should not fail for this fixture: {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_missing_source_file_fails_routing(self):
        cap_id = "no_source_cap"
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])
        # No capability source file is written at all.

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(any(f.startswith("Routing:") for f in result.failures))
        self._assert_no_traceback(result)


class TestTestTargetEnumCheckIndependent(CapabilityInvariantsTestBase):
    def test_out_of_vocabulary_test_target_fails_only_test_target(self):
        cap_id = "bad_test_target_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Bad Test Target Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, declared_test_target="banana")])

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Test target:") for f in result.failures),
            f"expected a Test target failure, got {result.failures!r}",
        )
        self.assertFalse(any(f.startswith("Routing:") for f in result.failures))
        self.assertFalse(any(f.startswith("Id coherence:") for f in result.failures))
        self.assertFalse(any(f.startswith("Contract registered:") for f in result.failures))
        self._assert_no_traceback(result)

    def test_each_valid_test_target_value_passes(self):
        for target in ("copy", "dry_run", "bounded_sample", "native_undo"):
            with self.subTest(target=target):
                cap_id = f"valid_target_{target}_cap"
                self._write_capability(
                    cap_id, _CLEAN_SOURCE.format(name=cap_id, op_kind=VALID_OP_KIND))
                self._write_descriptor_set(
                    [_base_descriptor_entry(cap_id, declared_test_target=target)])

                result = self._check(cap_id)

                self.assertFalse(
                    any(f.startswith("Test target:") for f in result.failures),
                    f"declared_test_target={target!r} should be valid: {result.failures!r}",
                )


class TestIdCoherenceCheckIndependent(CapabilityInvariantsTestBase):
    def test_descriptor_id_set_to_surface_fails_only_id_coherence(self):
        cap_id = "acme_crm_sync"
        surface = "acme_crm"
        self._write_capability(
            cap_id,
            _CLEAN_SOURCE_WITH_SURFACE.format(
                name="Acme CRM Sync", op_kind=VALID_OP_KIND, surface=surface),
        )
        # The descriptor's "id" is wrongly set to the capability's own SURFACE value instead
        # of its capability_id -- the estate-class drift assert_identity_coherent exists to
        # catch even though build_capability_index's own surface-corroboration would otherwise
        # resolve it.
        self._write_descriptor_set([_base_descriptor_entry(surface)])

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Id coherence:") for f in result.failures),
            f"expected an Id coherence failure, got {result.failures!r}",
        )
        self.assertFalse(any(f.startswith("Routing:") for f in result.failures))
        self._assert_no_traceback(result)

    def test_coherent_descriptor_id_passes_id_coherence(self):
        cap_id = "coherent_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Coherent Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(any(f.startswith("Id coherence:") for f in result.failures))


class TestContractRegisteredCheckIndependent(CapabilityInvariantsTestBase):
    def test_unregistered_op_kind_fails_only_contract_registered(self):
        cap_id = "unregistered_op_kind_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Unregistered Op Kind Cap",
                                          op_kind=UNREGISTERED_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Contract registered:") for f in result.failures),
            f"expected a Contract registered failure, got {result.failures!r}",
        )
        self.assertFalse(any(f.startswith("Routing:") for f in result.failures))
        self.assertFalse(any(f.startswith("Test target:") for f in result.failures))
        self.assertFalse(any(f.startswith("Id coherence:") for f in result.failures))
        self._assert_no_traceback(result)

    def test_registered_op_kind_passes_contract_registered(self):
        cap_id = "registered_op_kind_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Registered Op Kind Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set([_base_descriptor_entry(cap_id)])

        result = self._check(cap_id)

        self.assertFalse(any(f.startswith("Contract registered:") for f in result.failures))


class TestAuditCheckPostAcceptanceOnly(CapabilityInvariantsTestBase):
    PHASE_ID = "phase_d1_1_test"

    def test_not_yet_accepted_capability_does_not_fail_audit(self):
        cap_id = "not_accepted_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Not Accepted Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, accepted=False, phase_id=self.PHASE_ID)])
        # No audit log at all -- must still not fail, since acceptance itself is False.

        result = self._check(cap_id)

        self.assertFalse(any(f.startswith("Audit record:") for f in result.failures))

    def test_accepted_capability_missing_audit_record_fails_audit(self):
        cap_id = "accepted_missing_audit_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Accepted Missing Audit Cap",
                                          op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, accepted=True, phase_id=self.PHASE_ID)])
        # Accepted, but no audit log file/entry exists at all.

        result = self._check(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Audit record:") for f in result.failures),
            f"expected an Audit record failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_accepted_capability_with_matching_audit_record_passes_audit(self):
        cap_id = "accepted_with_audit_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Accepted With Audit Cap", op_kind=VALID_OP_KIND))
        self._write_descriptor_set(
            [_base_descriptor_entry(cap_id, accepted=True, phase_id=self.PHASE_ID)])
        self._write_audit_record(cap_id, self.PHASE_ID)

        result = self._check(cap_id)

        self.assertFalse(
            any(f.startswith("Audit record:") for f in result.failures),
            f"expected no Audit record failure, got {result.failures!r}",
        )
        self.assertTrue(result.ok, f"expected ok, got failures: {result.failures!r}")



# =============================================================================
# Task D1-2: deterministic test-quality probes (check_test_quality)
# =============================================================================
#
# ANTI-OVERFIT: every capability module here is written at the real emitted
# relpath (``agents/capabilities/<capability_id>_capability.py``); each
# fixture's OWN test file is written at a real-shaped relpath
# (``agents/capabilities/tests/test_<capability_id>_capability.py``) inside a
# fresh ``tempfile.TemporaryDirectory()`` -- never a copytree of this dev
# tree. Five distinct capability_ids are exercised across this section.
#
# Because ``check_test_quality`` always runs BOTH probes together, a fixture
# built to exercise probe 1 (producer-entrypoint, AST-only -- does not
# execute the test file) is deliberately kept SELF-CONTAINED with respect to
# probe 2 (known-bad-fails, which DOES actually execute the discovered test
# file(s) via a real subprocess against a temp copy): the "genuine"/"inert"
# fixtures below import ONLY their own capability module (never
# ``external_write``, which is not present in these minimal fixture trees),
# so that whether they fail when run is driven ENTIRELY by the deliberate
# mutation this task's own docstring describes -- not by an unrelated import
# error. This was verified manually before writing these tests: an
# unmutated capability module's test passes; the exact same test, run
# against the mutated copy ``check_test_quality`` builds internally, fails
# with the mutation's own ``RuntimeError`` -- proving the mechanism (not just
# the assertion) actually works.


class TestProducerEntrypointProbe(CapabilityInvariantsTestBase):
    def test_handrolled_standin_test_is_flagged(self):
        # Required test (a): a test that builds a hand-rolled Operation stand-in
        # (drives a fake instead of the real producer) must be FLAGGED.
        cap_id = "standin_flagged_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Standin Flagged Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: hand-rolled Operation stand-in test (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}  # noqa: F401 -- present so discovery finds this file


class Operation:
    """Hand-rolled stand-in -- NOT external_write.operations.Operation."""

    def __init__(self, surface, op_kind):
        self.surface = surface
        self.op_kind = op_kind


def _fake_run(op):
    return "fake-ok"


class TestStandinFlaggedCap(unittest.TestCase):
    def test_fake_operation_flow(self):
        op = Operation(surface="acme", op_kind="set_status")
        self.assertEqual(_fake_run(op), "fake-ok")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Producer entrypoint:") and "stand-in" in f for f in result.failures),
            f"expected a Producer entrypoint stand-in failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_real_producer_entrypoint_reference_passes(self):
        # Required test (b): a test that references the real producer entrypoint
        # (the capability module + run_enveloped_operation) must PASS the
        # producer-entrypoint probe -- no "stand-in" / "none of this
        # capability's test file(s)" failure line.
        cap_id = "real_entrypoint_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Real Entrypoint Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: real producer-entrypoint reference test (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}

from external_write.capability_api import run_enveloped_operation  # noqa: F401


class TestRealEntrypointCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "Real Entrypoint Cap ready")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(
            any(f.startswith("Producer entrypoint:") for f in result.failures),
            f"expected no Producer entrypoint failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_no_discoverable_test_file_flags_producer_entrypoint(self):
        cap_id = "no_test_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="No Test Cap", op_kind=VALID_OP_KIND))
        # Deliberately no test file written anywhere.

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Producer entrypoint:") and "no test file" in f
                for f in result.failures),
            f"expected a 'no test file' Producer entrypoint failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)


class TestKnownBadFailsProbe(CapabilityInvariantsTestBase):
    def test_inert_always_green_suite_is_caught(self):
        # Required test (c): an inert (always-passes) test suite is caught by
        # the known-bad-fails probe -- it stays green even against a
        # deliberately broken copy, so the probe FAILS this capability.
        cap_id = "inert_suite_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Inert Suite Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: inert (always-green) test suite (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}  # noqa: F401 -- imported but never called: inert by design


class TestInertSuiteCap(unittest.TestCase):
    def test_always_true(self):
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(f.startswith("Known-bad-fails:") for f in result.failures),
            f"expected a Known-bad-fails failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_genuine_suite_that_fails_against_broken_impl_passes(self):
        # Required test (d): a genuine test suite that DOES fail against a
        # broken impl passes the known-bad-fails probe.
        cap_id = "genuine_suite_cap"
        self._write_capability(
            cap_id, _CLEAN_SOURCE.format(name="Genuine Suite Cap", op_kind=VALID_OP_KIND))
        module_name = f"{cap_id}_capability"
        test_source = f'''"""Fixture: genuine test suite that really exercises the capability (test fixture)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import {module_name}


class TestGenuineSuiteCap(unittest.TestCase):
    def test_describe_reports_ready(self):
        self.assertEqual({module_name}.describe(), "Genuine Suite Cap ready")


if __name__ == "__main__":
    unittest.main()
'''
        self._write_project_file(
            f"{CAPABILITIES_DIR_REL}/tests/test_{cap_id}_capability.py", test_source)

        result = self._check_quality(cap_id)

        self.assertFalse(
            any(f.startswith("Known-bad-fails:") for f in result.failures),
            f"expected no Known-bad-fails failure, got {result.failures!r}",
        )
        self._assert_no_traceback(result)

    def test_missing_capability_source_fails_closed(self):
        cap_id = "missing_source_quality_cap"
        # No capability source file written at all.

        result = self._check_quality(cap_id)

        self.assertFalse(result.ok)
        self.assertTrue(any(f.startswith("Test quality:") for f in result.failures))
        self._assert_no_traceback(result)


if __name__ == "__main__":
    unittest.main()
