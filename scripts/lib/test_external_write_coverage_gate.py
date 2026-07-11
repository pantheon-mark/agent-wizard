"""Tests for the B1-5/B2-T1 descriptor-coverage gate (external_write.coverage_gate).

The coverage gate is the SECOND deterministic build-time safety gate, run in MA-REV
ALONGSIDE the AST bypass scanner (scan.py) but SEPARATE from it. scan.py answers "does any
write bypass the adapter package?"; this gate answers "is every guarded mutator covered by a
DECLARED, structurally-valid descriptor of the right risk class?"

As of B2-T1, ACCEPTANCE is NOT checked here — a descriptor's ``accepted`` field is irrelevant to
this gate. ACCEPTANCE for live writes is enforced at RUNTIME by the sibling ``write_gate`` (a
capability runs against its declared test target until a covering phase is accepted). This split
exists because descriptors are always emitted ``accepted: false`` and only become accepted after
an operator accepts the BUILT capability — requiring acceptance at build time would deadlock the
operator-originated-enhancement flow (a capability can't be accepted until built, but a
build-time acceptance requirement would block the build until accepted).

The OVERRIDING property under test is fail-closed EVERYWHERE: an absent / unreadable / malformed
descriptor set, a join MISS for a real mutator, or any ambiguity must NEVER pass the gate. A
write-shaped (gated) mutator with no DECLARED covering descriptor always FAILS. read_only_local
NEVER trips.

Uses synthetic descriptor-set + contract fixtures (the physical descriptor emission is B2);
scan.py is imported and called, never modified.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.scan import Violation  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write import contracts as contracts_mod  # noqa: E402
from external_write.coverage_gate import (  # noqa: E402
    evaluate_coverage_gate,
    run_coverage_gate,
    covering_declared_descriptor,
    CoverageDecision,
    CoverageFailure,
    GATED_RISK_CLASSES,
    READ_ONLY_LOCAL,
    FAIL_SAFE_RISK_CLASS,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURES = _REPO_ROOT / "wizard" / "test_fixtures" / "external_write_scan"


# ---------------------------------------------------------------------------
# Fixture builders (synthetic descriptor entries + contracts)
# ---------------------------------------------------------------------------

def _desc(id="google_sheets", risk_class="irreversible_external", accepted=False, **kw):
    """A B1-2-shaped machine-readable descriptor entry (render_descriptor_registry_json shape)."""
    e = {
        "id": id,
        "name": id,
        "action_class": "delete",
        "risk_class": risk_class,
        "recovery_profile_ref": None,
        "declared_test_target": "copy",
        "blast_radius_cap": None,
        "accepted": accepted,
    }
    e.update(kw)
    return e


def _contract(op_kind="delete_record", risk_class="irreversible_external",
              requires_accepted_phase=True):
    return OperationContract(
        op_kind=op_kind, writes=("__record__",), produces=(),
        dependency_set=(), verifier_set=(), introduces_persistent_binding=False,
        risk_class=risk_class, requires_accepted_phase=requires_accepted_phase,
    )


_GATED = {"delete_record": _contract()}


def _kinds(decision):
    return sorted({f.kind for f in decision.failures})


# ---------------------------------------------------------------------------
# The single explicit op -> descriptor join function
# ---------------------------------------------------------------------------

class TestJoinFunction(unittest.TestCase):
    def test_join_matches_on_risk_class_when_accepted(self):
        ds = [_desc(risk_class="irreversible_external", accepted=True)]
        self.assertIsNotNone(covering_declared_descriptor("irreversible_external", ds))

    def test_join_matches_on_risk_class_when_unaccepted(self):
        # B2-T1 NEW behavior: the join no longer checks ``accepted`` at all. A DECLARED entry of
        # the matching risk_class covers the mutator regardless of acceptance status.
        ds = [_desc(risk_class="irreversible_external", accepted=False)]
        self.assertIsNotNone(covering_declared_descriptor("irreversible_external", ds))

    def test_join_miss_on_risk_class_mismatch_returns_none(self):
        # A real mutator (irreversible) against a descriptor of a DIFFERENT risk class:
        # join MISS => must return None so the caller fails closed (carried req #2).
        ds = [_desc(risk_class="reversible_external", accepted=True)]
        self.assertIsNone(covering_declared_descriptor("irreversible_external", ds))


# ---------------------------------------------------------------------------
# The verdict — each FAIL leg + the PASS case
# ---------------------------------------------------------------------------

class TestCoverageVerdict(unittest.TestCase):
    def test_covered_capability_passes(self):
        # Gated mutator + an ACCEPTED covering descriptor of the right risk + clean scan => PASS.
        d = evaluate_coverage_gate(
            scan_violations=[],
            descriptor_set=[_desc(risk_class="irreversible_external", accepted=True)],
            contracts_map=_GATED,
        )
        self.assertTrue(d.passed, d.failures)
        self.assertEqual(d.failures, [])

    def test_declared_but_unaccepted_descriptor_covers_and_passes(self):
        # B2-T1 NEW/INTENTIONAL behavior change: a descriptor that is DECLARED (well-formed,
        # matching risk_class) but NOT accepted (accepted: false — the state every descriptor is
        # emitted in) now COVERS the guarded mutator and the gate PASSES. Under the prior
        # (pre-B2-T1) semantics this same input FAILED with unaccepted_acceptance_requiring_
        # descriptor / uncovered_mutator. Acceptance for live writes is now runtime's job
        # (write_gate), not this build-time gate's.
        d = evaluate_coverage_gate(
            scan_violations=[],
            descriptor_set=[_desc(risk_class="irreversible_external", accepted=False)],
            contracts_map=_GATED,
        )
        self.assertTrue(d.passed, d.failures)
        self.assertEqual(d.failures, [])

    def test_scan_bypass_violation_fails(self):
        # (a) ANY scan_paths() bypass violation fails the gate, even with full coverage.
        d = evaluate_coverage_gate(
            scan_violations=[Violation(path="x.py", lineno=3, kind="forbidden_import")],
            descriptor_set=[_desc(risk_class="irreversible_external", accepted=True)],
            contracts_map=_GATED,
        )
        self.assertFalse(d.passed)
        self.assertIn("bypass_scan_violation", _kinds(d))

    def test_write_shaped_capability_with_no_descriptor_fails(self):
        # Carried req #1: a write-shaped (gated) mutator with NO covering descriptor entry FAILS.
        # The set has descriptors, just none covering the irreversible mutator.
        d = evaluate_coverage_gate(
            scan_violations=[],
            descriptor_set=[_desc(risk_class="reversible_external", accepted=True)],
            contracts_map=_GATED,
        )
        self.assertFalse(d.passed)
        self.assertIn("uncovered_mutator", _kinds(d))

    def test_join_miss_for_real_mutator_fails(self):
        # Carried req #2: the join misses for a real mutator => fail-closed (never fall through).
        d = evaluate_coverage_gate(
            scan_violations=[],
            descriptor_set=[_desc(risk_class="reversible_external", accepted=True)],
            contracts_map={"delete_record": _contract(risk_class="irreversible_external")},
        )
        self.assertFalse(d.passed)
        self.assertIn("uncovered_mutator", _kinds(d))

    def test_declared_unaccepted_standing_automation_descriptor_does_not_fail_alone(self):
        # B2-T1 REMOVED leg (c): a standing_automation descriptor present in the set with
        # accepted:false must NOT, by itself, fail the gate anymore (the old
        # unaccepted_acceptance_requiring_descriptor leg is gone; acceptance is runtime's job).
        # The irreversible mutator is covered by its own declared-but-unaccepted descriptor too.
        d = evaluate_coverage_gate(
            scan_violations=[],
            descriptor_set=[
                _desc(risk_class="irreversible_external", accepted=False),
                _desc(id="cron_job", risk_class="standing_automation", accepted=False),
            ],
            contracts_map=_GATED,
        )
        self.assertTrue(d.passed, d.failures)
        self.assertEqual(d.failures, [])

    def test_read_only_local_descriptor_with_no_accepted_phase_passes(self):
        # read_only_local NEVER trips: a read_only_local descriptor needs no declared/accepted
        # phase at all.
        d = evaluate_coverage_gate(
            scan_violations=[],
            descriptor_set=[
                _desc(id="ingest", risk_class="read_only_local", accepted=False),
                _desc(risk_class="irreversible_external", accepted=True),
            ],
            contracts_map=_GATED,
        )
        self.assertTrue(d.passed, d.failures)

    def test_reversible_external_descriptor_with_no_accepted_phase_passes(self):
        # reversible_external is not acceptance-requiring even under the OLD semantics (broker +
        # copy_run_proof enforce it); under B2-T1 acceptance is irrelevant here regardless of
        # risk class, so a reversible descriptor with accepted:false is unaffected either way.
        d = evaluate_coverage_gate(
            scan_violations=[],
            descriptor_set=[
                _desc(id="tracker", risk_class="reversible_external", accepted=False),
                _desc(risk_class="irreversible_external", accepted=True),
            ],
            contracts_map=_GATED,
        )
        self.assertTrue(d.passed, d.failures)


# ---------------------------------------------------------------------------
# Fail-closed on every missing / malformed input
# ---------------------------------------------------------------------------

class TestFailClosed(unittest.TestCase):
    def test_absent_descriptor_set_fails_closed(self):
        # An empty set (the loader's absent/unreadable return) leaves the gated mutator uncovered.
        d = evaluate_coverage_gate(
            scan_violations=[], descriptor_set=[], contracts_map=_GATED,
        )
        self.assertFalse(d.passed)
        self.assertIn("uncovered_mutator", _kinds(d))

    def test_malformed_entry_bad_risk_class_fails_closed(self):
        # A descriptor whose risk_class is outside the vocabulary is malformed. It must NOT be
        # fail-safe-resolved into a covering entry (that would be fail-OPEN) — it fails the gate.
        d = evaluate_coverage_gate(
            scan_violations=[],
            descriptor_set=[{"id": "x", "name": "x", "risk_class": "not_a_class",
                             "accepted": True}],
            contracts_map=_GATED,
        )
        self.assertFalse(d.passed)
        self.assertIn("malformed_descriptor_entry", _kinds(d))

    def test_malformed_entry_non_dict_fails_closed(self):
        d = evaluate_coverage_gate(
            scan_violations=[], descriptor_set=["not a dict"], contracts_map=_GATED,
        )
        self.assertFalse(d.passed)
        self.assertIn("malformed_descriptor_entry", _kinds(d))

    def test_malformed_entry_missing_risk_class_fails_closed(self):
        d = evaluate_coverage_gate(
            scan_violations=[],
            descriptor_set=[{"id": "x", "name": "x", "accepted": True}],
            contracts_map=_GATED,
        )
        self.assertFalse(d.passed)
        self.assertIn("malformed_descriptor_entry", _kinds(d))


# ---------------------------------------------------------------------------
# read_only_local mutator side + real-contract demand side
# ---------------------------------------------------------------------------

class TestMutatorSide(unittest.TestCase):
    def test_read_only_local_mutator_needs_no_coverage(self):
        # A read_only_local op_kind is NOT a guarded mutator: it needs no descriptor at all.
        d = evaluate_coverage_gate(
            scan_violations=[], descriptor_set=[],
            contracts_map={"ingest": _contract(
                op_kind="ingest", risk_class="read_only_local", requires_accepted_phase=False)},
        )
        self.assertTrue(d.passed, d.failures)

    def test_reversible_external_mutator_needs_no_descriptor(self):
        # A reversible_external, non-requires-accepted op (the seeded status ops) is enforced by
        # the broker + copy_run_proof, not by the descriptor mechanism, so it demands no descriptor.
        d = evaluate_coverage_gate(
            scan_violations=[], descriptor_set=[],
            contracts_map={"set_status": _contract(
                op_kind="set_status", risk_class="reversible_external",
                requires_accepted_phase=False)},
        )
        self.assertTrue(d.passed, d.failures)

    def test_requires_accepted_phase_on_non_gated_risk_is_gated(self):
        # A contract flagged requires_accepted_phase=True is a guarded mutator even at a
        # non-gated risk class — it must be covered by an accepted descriptor of that risk.
        c = {"weird": _contract(op_kind="weird", risk_class="reversible_external",
                                requires_accepted_phase=True)}
        d_fail = evaluate_coverage_gate(scan_violations=[], descriptor_set=[], contracts_map=c)
        self.assertFalse(d_fail.passed)
        self.assertIn("uncovered_mutator", _kinds(d_fail))
        d_ok = evaluate_coverage_gate(
            scan_violations=[],
            descriptor_set=[_desc(risk_class="reversible_external", accepted=True)],
            contracts_map=c)
        self.assertTrue(d_ok.passed, d_ok.failures)

    def test_default_real_contracts_treat_delete_record_as_gated(self):
        # With the REAL OPERATION_CONTRACTS (default), delete_record is a gated mutator, so an
        # empty descriptor set fails closed and names delete_record.
        d = evaluate_coverage_gate(scan_violations=[], descriptor_set=[])
        self.assertFalse(d.passed)
        self.assertIn("uncovered_mutator", _kinds(d))
        self.assertTrue(any("delete_record" in f.detail for f in d.failures), d.failures)


# ---------------------------------------------------------------------------
# CLI helper — calls scan_paths, loads the set fail-closed, reads real contracts
# ---------------------------------------------------------------------------

class TestRunCoverageGate(unittest.TestCase):
    def _write_set(self, tmpdir, entries):
        import json
        p = Path(tmpdir) / "accepted_descriptor_set.json"
        p.write_text(json.dumps(entries), encoding="utf-8")
        return str(p)

    def test_clean_scan_and_covering_set_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            set_path = self._write_set(
                tmp, [_desc(risk_class="irreversible_external", accepted=True)])
            d = run_coverage_gate([_FIXTURES / "benign_local.py"],
                                  descriptor_set_path=set_path)
            self.assertTrue(d.passed, d.failures)

    def test_scan_bypass_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            set_path = self._write_set(
                tmp, [_desc(risk_class="irreversible_external", accepted=True)])
            d = run_coverage_gate([_FIXTURES / "forbidden_import.py"],
                                  descriptor_set_path=set_path)
            self.assertFalse(d.passed)
            self.assertIn("bypass_scan_violation", _kinds(d))

    def test_missing_descriptor_set_file_fails_closed(self):
        # A non-existent path => the fail-safe loader returns [] => gated delete_record uncovered.
        d = run_coverage_gate([_FIXTURES / "benign_local.py"],
                              descriptor_set_path="/no/such/descriptor/set.json")
        self.assertFalse(d.passed)
        self.assertIn("uncovered_mutator", _kinds(d))

    def test_adapter_profile_paths_passthrough_reaches_scan_paths(self):
        # Task 5: this gate does not re-implement the zone taxonomy -- it
        # consumes it exclusively via scan_paths. Proves adapter_profile_paths
        # / allowed_root passed to run_coverage_gate actually reach scan_paths:
        # an unregistered "vendor_adapter.py" trips bypass_scan_violation;
        # registering it as adapter-profile removes that failure kind.
        kernel_root = _FIXTURES / "zones" / "kernel_root"
        unregistered = run_coverage_gate(
            [kernel_root / "vendor_adapter.py"],
            descriptor_set_path="/no/such/descriptor/set.json",
            allowed_root=kernel_root,
        )
        self.assertIn("bypass_scan_violation", _kinds(unregistered))

        registered = run_coverage_gate(
            [kernel_root / "vendor_adapter.py"],
            descriptor_set_path="/no/such/descriptor/set.json",
            allowed_root=kernel_root,
            adapter_profile_paths=frozenset({"vendor_adapter.py"}),
        )
        self.assertNotIn("bypass_scan_violation", _kinds(registered))


if __name__ == "__main__":
    unittest.main()
