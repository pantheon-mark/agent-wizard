"""Tests for the B1-4 deterministic pre-write gate (external_write.write_gate) and its
wiring into run_operation.

The gate is the runtime-enforcement heart of the safety substrate: the single deterministic
chokepoint enforcing test-target-until-accepted, the blast-radius cap, and the
F-22 / F-28 / F-29 fail-safe properties. Every test here is paired positive/negative and the
OVERRIDING property under test is: a missing input (absent target, absent/unreadable descriptor
set, unknown risk) must NEVER open the gate.

Uses stub clients only; no network.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import Operation, Result  # noqa: E402
from external_write.adapters import run_operation  # noqa: E402
from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract, get_contract  # noqa: E402
from external_write import write_gate  # noqa: E402
from external_write.write_gate import (  # noqa: E402
    InvocationLedger,
    load_descriptor_set,
    evaluate_write_gate,
    resolve_effective_cap,
    system_clock,
    COPY_SURFACE,
    TEST_SURFACES,
    is_test_surface,
    LIVE_TARGET,
    TEST_TARGETS,
    ISOLATED_TEST_TARGETS,
    LIVE_BOUNDED_TEST_TARGETS,
    GATED_RISK_CLASSES,
    FAIL_SAFE_RISK_CLASS,
    READ_ONLY_LOCAL,
)
import dependency_projection as dp  # type: ignore  # noqa: E402


# ---------------------------------------------------------------------------
# Stub client + receipt helpers
# ---------------------------------------------------------------------------

class _AcceptingClient:
    def write(self, object_id, field, value):
        self._store = {(object_id, field): value}

    def read(self, object_id, field):
        return getattr(self, "_store", {}).get((object_id, field))


def _receipt(op):
    import hashlib
    from datetime import timedelta
    digest = hashlib.sha256(op.canonical_repr().encode()).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=900)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    return {"approved_operation_digest": digest, "expires_at": expires_at}


def _op(op_kind, *, surface="google_sheets", object_id="obj:1", field="__record__",
        new_value="<x>", batch_id="b1"):
    return Operation(surface=surface, object_id=object_id, field=field,
                     new_value=new_value, op_kind=op_kind, batch_id=batch_id)


def _accepted_entry(*, id="google_sheets", risk_class="irreversible_external",
                    blast_radius_cap=None, declared_test_target="copy",
                    recovery_profile_ref=None, accepted=True):
    # `accepted` defaults True (the historical name/shape); pass accepted=False to build a
    # DECLARED-only entry for the T1 LIVE_BOUNDED path (_declared_entry does not require it).
    return {
        "id": id, "name": id, "action_class": "delete",
        "risk_class": risk_class, "recovery_profile_ref": recovery_profile_ref,
        "declared_test_target": declared_test_target,
        "blast_radius_cap": blast_radius_cap, "accepted": accepted,
    }


# ---------------------------------------------------------------------------
# Cross-tree vocabulary consistency (mirrors the RISK_CLASSES seam test)
# ---------------------------------------------------------------------------

class TestGateVocabularyMatchesBuildSide(unittest.TestCase):
    def test_test_targets_match_build_side(self):
        self.assertEqual(set(TEST_TARGETS), set(dp.TEST_TARGETS))

    def test_fail_safe_risk_class_matches_build_side(self):
        self.assertEqual(FAIL_SAFE_RISK_CLASS, dp.FAIL_SAFE_RISK_CLASS)

    def test_read_only_local_matches_build_side(self):
        self.assertEqual(READ_ONLY_LOCAL, dp.READ_ONLY_LOCAL)

    def test_gated_risk_classes_are_everything_but_readonly_and_reversible(self):
        self.assertEqual(
            set(GATED_RISK_CLASSES),
            set(dp.RISK_CLASSES) - {dp.READ_ONLY_LOCAL, "reversible_external"})

    def test_copy_surface_matches_copy_run_proof_convention(self):
        # The target signal reuses copy_run_proof's copy-surface convention.
        from external_write.copy_run_proof import _synthetic_op
        self.assertEqual(_synthetic_op("delete_record", "__record__").surface, COPY_SURFACE)

    def test_is_test_surface_recognizes_copy_surface_only(self):
        # I1 predicate: COPY_SURFACE is the sole recognized test/copy surface today; a live
        # surface (and anything unrecognized) is fail-safe NOT a test surface.
        self.assertIn(COPY_SURFACE, TEST_SURFACES)
        self.assertTrue(is_test_surface(COPY_SURFACE))
        self.assertFalse(is_test_surface("google_sheets"))
        self.assertFalse(is_test_surface(""))
        self.assertFalse(is_test_surface(None))


# ---------------------------------------------------------------------------
# Fail-safe loader
# ---------------------------------------------------------------------------

class TestDescriptorSetLoader(unittest.TestCase):
    def test_wired_path_is_the_one_descriptor_set_file(self):
        # B2-T2: the constant is SET (no longer None) to the one canonical descriptor-set file
        # every emitted writes-back system carries — the SAME file the build-time coverage gate
        # reads (project-root-relative; both the coverage-gate CLI and agent invocations run
        # from the operator project root).
        self.assertEqual(write_gate.DESCRIPTOR_SET_PATH, "security/capability_descriptors.json")

    def test_no_path_configured_returns_empty(self):
        # True "absent config" fail-safe: DESCRIPTOR_SET_PATH itself unset (None) must still
        # yield [] even though the module now wires a real default in normal operation.
        original = write_gate.DESCRIPTOR_SET_PATH
        write_gate.DESCRIPTOR_SET_PATH = None
        try:
            self.assertEqual(load_descriptor_set(None), [])
        finally:
            write_gate.DESCRIPTOR_SET_PATH = original

    def test_default_wired_path_absent_on_disk_returns_empty(self):
        # The real wired default resolves relative to cwd; when no such file exists there
        # (the normal case for this test's cwd) the loader still fails safe to [].
        self.assertEqual(load_descriptor_set(None), [])

    def test_absent_file_returns_empty(self):
        self.assertEqual(
            load_descriptor_set("/nonexistent/definitely/missing.json"), [])

    def test_malformed_file_returns_empty(self):
        p = Path(_AGENTS_LIB).parent  # any dir; write to a scratch temp
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{ this is not valid json")
            name = f.name
        self.assertEqual(load_descriptor_set(name), [])

    def test_non_array_payload_returns_empty(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write('{"not": "an array"}')
            name = f.name
        self.assertEqual(load_descriptor_set(name), [])

    def test_valid_array_loads(self):
        import tempfile, json as _json
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            _json.dump([_accepted_entry()], f)
            name = f.name
        loaded = load_descriptor_set(name)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], "google_sheets")


# ---------------------------------------------------------------------------
# Invocation ledger (the blast-radius counter)
# ---------------------------------------------------------------------------

class TestInvocationLedger(unittest.TestCase):
    def test_count_and_record(self):
        led = InvocationLedger()
        self.assertEqual(led.count("k"), 0)
        led.record("k")
        led.record("k")
        self.assertEqual(led.count("k"), 2)
        self.assertEqual(led.count("other"), 0)


# ---------------------------------------------------------------------------
# Non-breaking: the 5 seeded status ops behave EXACTLY as before
# ---------------------------------------------------------------------------

class TestStatusOpsUnchanged(unittest.TestCase):
    def test_status_op_written_with_no_gate_params(self):
        op = _op("set_status", field="Status", new_value="Complete")
        result = run_operation(op, _receipt(op), _AcceptingClient())
        self.assertEqual(result.status, "written")
        self.assertIsNone(result.detail)  # byte-identical: plain written, no detail

    def test_status_op_never_needs_target_or_descriptor(self):
        # A reversible_external status op is a gate no-op even with no target signal.
        for op_kind, field in (("set_status", "Status"), ("add_note", "Note")):
            op = _op(op_kind, field=field, new_value="x")
            result = run_operation(op, _receipt(op), _AcceptingClient())
            self.assertEqual(result.status, "written", op_kind)


# ---------------------------------------------------------------------------
# read_only_local NEVER trips
# ---------------------------------------------------------------------------

class TestReadOnlyLocalNeverTrips(unittest.TestCase):
    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS["_ro_local_probe"] = OperationContract(
            op_kind="_ro_local_probe", writes=("Field",), produces=(),
            dependency_set=("adapters.py",), verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False, risk_class="read_only_local")

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop("_ro_local_probe", None)

    def test_read_only_local_passes_untouched_even_with_no_target(self):
        op = _op("_ro_local_probe", field="Field", new_value="x")
        # No target, no descriptor set, no ledger — must still write (never gated).
        result = run_operation(op, _receipt(op), _AcceptingClient())
        self.assertEqual(result.status, "written")


# ---------------------------------------------------------------------------
# delete_record (irreversible) gating
# ---------------------------------------------------------------------------

class TestDeleteRecordGating(unittest.TestCase):
    def test_live_without_accepted_phase_refused(self):
        op = _op("delete_record")
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               target=LIVE_TARGET, descriptor_set=[],
                               cap_ledger=InvocationLedger())
        self.assertEqual(result.status, "refused")
        self.assertIn("accepted", result.detail["reason"].lower())

    def test_declared_test_target_allowed_without_acceptance(self):
        # A declared test target needs no acceptance — but it is honored only on a recognized
        # test/copy surface (I1). COPY_SURFACE is that surface; the target claim binds to it.
        op = _op("delete_record", surface=COPY_SURFACE, object_id="copy:0")
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               target="copy", descriptor_set=[])
        self.assertEqual(result.status, "written")

    def test_test_target_on_live_surface_refused(self):
        # I1: target="copy" (a declared TEST_TARGET) claimed on a LIVE (non-test) surface must
        # be REFUSED. The target is a caller assertion; it must bind to where the write lands,
        # or client.write would hit the live record with no acceptance / cap / audit.
        op = _op("delete_record", surface="google_sheets", object_id="obj:live")
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               target="copy", descriptor_set=[])
        self.assertEqual(result.status, "refused")
        self.assertIn("surface", result.detail["reason"].lower())

    def test_every_test_target_on_live_surface_refused(self):
        # Every declared test target claimed on a live surface with NOTHING declared/accepted
        # is refused — EXCEPT dry_run (T1): dry_run is ISOLATED and permits unconditionally
        # regardless of surface (no live blast radius; T2's adapter guarantees no client.write).
        # dry_run's unconditional-permit is pinned separately in TestDryRunPermitsUnconditionally.
        for tt in sorted(TEST_TARGETS - {"dry_run"}):
            op = _op("delete_record", surface="google_sheets", object_id=f"obj:{tt}")
            result = run_operation(op, _receipt(op), _AcceptingClient(),
                                   target=tt, descriptor_set=[])
            self.assertEqual(result.status, "refused", tt)

    def test_copy_surface_convention_is_a_test_target(self):
        # Reusing copy_run_proof's copy-surface convention: surface==copy_surface is
        # implicitly a test target even with no explicit target arg.
        op = _op("delete_record", surface=COPY_SURFACE, object_id="copy:0")
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               descriptor_set=[])
        self.assertEqual(result.status, "written")

    def test_accepted_phase_live_allowed(self):
        op = _op("delete_record")
        ds = [_accepted_entry(risk_class="irreversible_external")]
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               target=LIVE_TARGET, descriptor_set=ds,
                               cap_ledger=InvocationLedger())
        self.assertEqual(result.status, "written")

    def test_absent_target_on_gated_op_refused(self):
        # No target arg + non-copy surface = ABSENT target signal -> fail-safe refuse.
        op = _op("delete_record")
        ds = [_accepted_entry(risk_class="irreversible_external")]
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               descriptor_set=ds, cap_ledger=InvocationLedger())
        self.assertEqual(result.status, "refused")
        self.assertIn("target", result.detail["reason"].lower())

    def test_absent_descriptor_set_refuses_live(self):
        # descriptor_set=None -> loader (no path configured) -> [] -> nothing accepted.
        op = _op("delete_record")
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               target=LIVE_TARGET, descriptor_set=None,
                               cap_ledger=InvocationLedger())
        self.assertEqual(result.status, "refused")

    def test_unrecognized_target_string_refused(self):
        op = _op("delete_record")
        ds = [_accepted_entry(risk_class="irreversible_external")]
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               target="production_for_real", descriptor_set=ds,
                               cap_ledger=InvocationLedger())
        self.assertEqual(result.status, "refused")


# ---------------------------------------------------------------------------
# Blast-radius cap (deterministic, outside the LLM)
# ---------------------------------------------------------------------------

class TestBlastRadiusCap(unittest.TestCase):
    def test_cap_boundary_nth_allowed_n_plus_1_refused(self):
        ds = [_accepted_entry(risk_class="irreversible_external")]  # cap from contract = 5
        led = InvocationLedger()
        cap = get_contract("delete_record").blast_radius_cap
        self.assertEqual(cap, 5)
        for i in range(cap):
            op = _op("delete_record", object_id=f"obj:{i}", batch_id=f"b{i}")
            r = run_operation(op, _receipt(op), _AcceptingClient(),
                              target=LIVE_TARGET, descriptor_set=ds, cap_ledger=led)
            self.assertEqual(r.status, "written", f"invocation {i+1} of {cap} must pass")
        # The (cap+1)th must be refused.
        op = _op("delete_record", object_id="obj:overflow", batch_id="bX")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=ds, cap_ledger=led)
        self.assertEqual(r.status, "refused")
        self.assertIn("cap", r.detail["reason"].lower())

    def test_descriptor_cap_overrides_contract_cap_downward(self):
        ds = [_accepted_entry(risk_class="irreversible_external", blast_radius_cap=2)]
        led = InvocationLedger()
        for i in range(2):
            op = _op("delete_record", object_id=f"obj:{i}", batch_id=f"b{i}")
            r = run_operation(op, _receipt(op), _AcceptingClient(),
                              target=LIVE_TARGET, descriptor_set=ds, cap_ledger=led)
            self.assertEqual(r.status, "written")
        op = _op("delete_record", object_id="obj:3", batch_id="b3")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=ds, cap_ledger=led)
        self.assertEqual(r.status, "refused")  # capped at 2, not 5

    def test_absent_ledger_on_live_irreversible_refused(self):
        # Can't enforce the cap without a ledger -> fail-safe refuse.
        op = _op("delete_record")
        ds = [_accepted_entry(risk_class="irreversible_external")]
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               target=LIVE_TARGET, descriptor_set=ds, cap_ledger=None)
        self.assertEqual(result.status, "refused")
        self.assertIn("ledger", result.detail["reason"].lower())

    def test_test_target_irreversible_does_not_consume_cap(self):
        # A copy-target op has no live blast radius; it must not need a ledger nor
        # consume a cap slot.
        led = InvocationLedger()
        for i in range(10):
            op = _op("delete_record", object_id=f"copy:{i}", surface=COPY_SURFACE)
            r = run_operation(op, _receipt(op), _AcceptingClient(), descriptor_set=[])
            self.assertEqual(r.status, "written")
        self.assertEqual(led.count("google_sheets::delete_record"), 0)


class TestResolveEffectiveCapMultipleMatchingEntries(unittest.TestCase):
    """Review fix: resolve_effective_cap must be fail-safe when MULTIPLE descriptor
    entries match the same surface + risk_class — it must take the SMALLEST cap
    across every matching entry (never the first match), matching the same
    "smallest cap wins" convention `_effective_cap` already establishes. A
    too-permissive blast-radius cap picked by first-match order is a security-
    relevant correctness bug."""

    OP_KIND = "_multi_descriptor_cap_probe"

    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS[self.OP_KIND] = OperationContract(
            op_kind=self.OP_KIND,
            writes=("Status",),
            produces=(),
            dependency_set=(),
            verifier_set=(),
            introduces_persistent_binding=False,
            risk_class="irreversible_external",
            blast_radius_cap=20,  # deliberately larger than every descriptor cap below
        )

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop(self.OP_KIND, None)

    def _op(self):
        return Operation(surface="google_sheets", op_kind=self.OP_KIND,
                          object_id="obj:1", field="__record__", new_value="<x>",
                          batch_id="b1")

    def test_multiple_matching_entries_resolve_to_the_smallest_cap(self):
        # Two entries match the SAME surface + risk_class, in an order where the
        # FIRST entry has the LARGER cap. First-match behavior would wrongly
        # return 15 (min(contract=20, first=15)); the fail-safe fix must return 7
        # -- the smallest cap across ALL matching entries (contract=20, 15, 7).
        ds = [
            _accepted_entry(risk_class="irreversible_external", blast_radius_cap=15),
            _accepted_entry(risk_class="irreversible_external", blast_radius_cap=7),
        ]
        cap = resolve_effective_cap(self._op(), ds)
        self.assertEqual(cap, 7)

    def test_descriptor_override_is_sourced_from_the_descriptor_set_not_the_contract(self):
        # Both matching entries' caps are well below the contract's default (20),
        # so a resolved value of 4 can only have come from actually reading and
        # combining the descriptor entries -- not from falling back to the
        # contract cap (which alone would resolve to 20).
        ds = [
            _accepted_entry(risk_class="irreversible_external", blast_radius_cap=12),
            _accepted_entry(risk_class="irreversible_external", blast_radius_cap=4),
        ]
        cap = resolve_effective_cap(self._op(), ds)
        self.assertEqual(cap, 4)
        self.assertLess(cap, 20)


# ---------------------------------------------------------------------------
# F-28: unknown / uncovered risk on a writer -> fail-safe protected
# ---------------------------------------------------------------------------

class TestF28FailSafeClassification(unittest.TestCase):
    def test_unknown_op_kind_live_refused(self):
        # No registered contract -> write-shaped, risk unknown -> PROTECTED, never live.
        op = _op("totally_unregistered_writer")
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               target=LIVE_TARGET, descriptor_set=[],
                               cap_ledger=InvocationLedger())
        self.assertEqual(result.status, "refused")

    def test_unknown_op_kind_resolves_to_fail_safe_risk_class(self):
        decision = evaluate_write_gate(_op("totally_unregistered_writer"),
                                       target=LIVE_TARGET, descriptor_set=[],
                                       cap_ledger=InvocationLedger())
        self.assertFalse(decision.permitted)

    def test_corrupt_risk_class_treated_as_protected(self):
        contracts_mod.OPERATION_CONTRACTS["_corrupt_probe"] = OperationContract(
            op_kind="_corrupt_probe", writes=("Field",), produces=(),
            dependency_set=("adapters.py",), verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False,
            risk_class="not_a_real_risk_class")
        try:
            op = _op("_corrupt_probe", field="Field")
            r = run_operation(op, _receipt(op), _AcceptingClient(),
                              target=LIVE_TARGET, descriptor_set=[],
                              cap_ledger=InvocationLedger())
            self.assertEqual(r.status, "refused")
        finally:
            contracts_mod.OPERATION_CONTRACTS.pop("_corrupt_probe", None)


# ---------------------------------------------------------------------------
# F-29: standing_automation gated + non-graduating recovery floor
# ---------------------------------------------------------------------------

class TestF29StandingAutomation(unittest.TestCase):
    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS["_standing_probe"] = OperationContract(
            op_kind="_standing_probe", writes=("Field",), produces=(),
            dependency_set=("adapters.py",), verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False,
            risk_class="standing_automation")

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop("_standing_probe", None)

    def test_standing_automation_live_without_acceptance_refused(self):
        op = _op("_standing_probe", field="Field")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=[],
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "refused")

    def test_standing_automation_test_target_allowed(self):
        # Honored on a recognized test/copy surface (I1); a live-surface copy claim would refuse.
        op = _op("_standing_probe", field="Field", surface=COPY_SURFACE, object_id="copy:0")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target="copy", descriptor_set=[])
        self.assertEqual(r.status, "written")

    def test_recovery_floor_not_waivable_accepted_but_no_recovery_ref_refused(self):
        # Accepted phase present, but NO recovery_profile_ref -> recovery floor blocks live.
        op = _op("_standing_probe", field="Field")
        ds = [_accepted_entry(id="google_sheets", risk_class="standing_automation",
                              recovery_profile_ref=None)]
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=ds,
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "refused")
        self.assertIn("recover", r.detail["reason"].lower())

    def test_standing_automation_accepted_with_recovery_ref_allowed(self):
        # R5 (T1): a blast-radius cap is now MANDATORY for every gated live risk class, not
        # just irreversible_external — so this entry must carry a cap for the write to permit.
        # (Pre-T1 this passed with no cap at all; that is the exact S-1 gap T1 closes.)
        op = _op("_standing_probe", field="Field")
        ds = [_accepted_entry(id="google_sheets", risk_class="standing_automation",
                              blast_radius_cap=3,
                              recovery_profile_ref="recovery_profiles/backup_v1")]
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=ds,
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "written")


# ---------------------------------------------------------------------------
# F-22: dates written by the gate come from the system clock, not a passed-in string
# ---------------------------------------------------------------------------

class TestF22SystemClock(unittest.TestCase):
    def test_irreversibility_ack_timestamp_from_injected_clock(self):
        fixed = datetime(2031, 3, 9, 12, 0, 0, tzinfo=timezone.utc)
        op = _op("delete_record")
        ds = [_accepted_entry(risk_class="irreversible_external")]
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=ds,
                          cap_ledger=InvocationLedger(), clock=lambda: fixed)
        self.assertEqual(r.status, "written")
        ack = r.detail["irreversibility_acknowledgement"]
        self.assertEqual(ack["recorded_at"], "2031-03-09T12:00:00Z")
        self.assertIs(ack["reversible"], False)

    def test_gate_has_no_passed_in_date_string_param(self):
        # F-22: run_operation must not accept a model-authored 'today'/'date' string.
        import inspect
        sig = inspect.signature(run_operation)
        for bad in ("today", "date", "now", "timestamp", "current_date"):
            self.assertNotIn(bad, sig.parameters,
                             f"run_operation must not take a passed-in {bad!r} string (F-22)")

    def test_default_clock_is_system_clock(self):
        before = datetime.now(timezone.utc)
        val = system_clock()
        after = datetime.now(timezone.utc)
        self.assertTrue(before <= val <= after)


# ---------------------------------------------------------------------------
# T1 (bounded_sample / dry_run / native_undo test surfaces) — vocabulary partition
# ---------------------------------------------------------------------------

class TestR1TestTargetPartition(unittest.TestCase):
    def test_isolated_and_live_bounded_partition_test_targets_exactly(self):
        # The two classes must cover TEST_TARGETS exactly and be disjoint, so a future target
        # string can never silently default into the wrong safety class.
        self.assertEqual(ISOLATED_TEST_TARGETS | LIVE_BOUNDED_TEST_TARGETS, TEST_TARGETS)
        self.assertEqual(ISOLATED_TEST_TARGETS & LIVE_BOUNDED_TEST_TARGETS, frozenset())

    def test_partition_values(self):
        self.assertEqual(ISOLATED_TEST_TARGETS, frozenset({"copy", "dry_run"}))
        self.assertEqual(LIVE_BOUNDED_TEST_TARGETS, frozenset({"bounded_sample", "native_undo"}))


# ---------------------------------------------------------------------------
# T1 — dry_run: ISOLATED, permits unconditionally at the gate
# ---------------------------------------------------------------------------

class TestDryRunPermitsUnconditionally(unittest.TestCase):
    def test_dry_run_permits_with_no_descriptor_cap_or_ledger(self):
        op = _op("delete_record", surface="google_sheets", object_id="obj:dry")
        result = run_operation(op, _receipt(op), _AcceptingClient(), target="dry_run")
        self.assertEqual(result.status, "written")

    def test_dry_run_permits_regardless_of_surface(self):
        # Unlike copy, dry_run carries no surface requirement — it is SAFE only because T2's
        # adapter guarantees dry_run never reaches client.write; the gate authorizes the
        # intent, the adapter enforces no-mutation. This op still targets a "live" surface
        # here (no adapter no-write path exists yet in this task), so the AcceptingClient
        # stub's write is harmless in this test.
        for surface in ("google_sheets", COPY_SURFACE, "asana"):
            op = _op("delete_record", surface=surface, object_id=f"obj:{surface}")
            result = run_operation(op, _receipt(op), _AcceptingClient(), target="dry_run")
            self.assertEqual(result.status, "written", surface)

    def test_dry_run_permits_even_with_empty_descriptor_set_and_no_ledger(self):
        op = _op("delete_record", surface="google_sheets", object_id="obj:dry2")
        result = run_operation(op, _receipt(op), _AcceptingClient(),
                               target="dry_run", descriptor_set=[], cap_ledger=None)
        self.assertEqual(result.status, "written")


# ---------------------------------------------------------------------------
# T1 — bounded_sample: LIVE_BOUNDED, declared (not accepted) + shared funnel
# ---------------------------------------------------------------------------

class TestLiveBoundedSampleGating(unittest.TestCase):
    def test_declared_entry_with_cap_and_ledger_permits(self):
        ds = [_accepted_entry(accepted=False, declared_test_target="bounded_sample",
                              risk_class="irreversible_external", blast_radius_cap=2)]
        led = InvocationLedger()
        op = _op("delete_record", object_id="obj:0")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target="bounded_sample", descriptor_set=ds, cap_ledger=led)
        self.assertEqual(r.status, "written")
        self.assertEqual(led.count("google_sheets::delete_record"), 1)

    def test_cap_boundary_nth_allowed_n_plus_1_refused(self):
        ds = [_accepted_entry(accepted=False, declared_test_target="bounded_sample",
                              risk_class="irreversible_external", blast_radius_cap=2)]
        led = InvocationLedger()
        for i in range(2):
            op = _op("delete_record", object_id=f"obj:{i}", batch_id=f"b{i}")
            r = run_operation(op, _receipt(op), _AcceptingClient(),
                              target="bounded_sample", descriptor_set=ds, cap_ledger=led)
            self.assertEqual(r.status, "written", f"invocation {i+1} of 2 must pass")
        op = _op("delete_record", object_id="obj:overflow", batch_id="bX")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target="bounded_sample", descriptor_set=ds, cap_ledger=led)
        self.assertEqual(r.status, "refused")
        self.assertIn("cap", r.detail["reason"].lower())

    def test_permits_even_when_entry_is_not_accepted(self):
        # The whole point of LIVE_BOUNDED: it needs a DECLARATION, not acceptance.
        ds = [_accepted_entry(accepted=False, declared_test_target="bounded_sample",
                              risk_class="irreversible_external", blast_radius_cap=2)]
        op = _op("delete_record")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target="bounded_sample", descriptor_set=ds,
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "written")

    def test_undeclared_capability_refused(self):
        op = _op("delete_record")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target="bounded_sample", descriptor_set=[],
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "refused")
        self.assertIn("declared", r.detail["reason"].lower())

    def test_declared_test_target_mismatch_refused(self):
        # The entry declares 'copy'; the op requests 'bounded_sample' — exact-match anchor,
        # not membership, so a copy declaration never covers a bounded_sample request.
        ds = [_accepted_entry(accepted=False, declared_test_target="copy",
                              risk_class="irreversible_external", blast_radius_cap=2)]
        op = _op("delete_record")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target="bounded_sample", descriptor_set=ds,
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "refused")

    def test_no_cap_anywhere_refused(self):
        # Neither the contract nor the descriptor entry carries a cap -> mandatory-cap refuse.
        contracts_mod.OPERATION_CONTRACTS["_bounded_probe"] = OperationContract(
            op_kind="_bounded_probe", writes=("Field",), produces=(),
            dependency_set=("adapters.py",), verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False, risk_class="irreversible_external",
            requires_accepted_phase=True, blast_radius_cap=None)
        try:
            ds = [_accepted_entry(accepted=False, declared_test_target="bounded_sample",
                                  risk_class="irreversible_external", blast_radius_cap=None)]
            op = _op("_bounded_probe", field="Field")
            r = run_operation(op, _receipt(op), _AcceptingClient(),
                              target="bounded_sample", descriptor_set=ds,
                              cap_ledger=InvocationLedger())
            self.assertEqual(r.status, "refused")
            self.assertIn("cap", r.detail["reason"].lower())
        finally:
            contracts_mod.OPERATION_CONTRACTS.pop("_bounded_probe", None)

    def test_no_ledger_refused(self):
        ds = [_accepted_entry(accepted=False, declared_test_target="bounded_sample",
                              risk_class="irreversible_external", blast_radius_cap=2)]
        op = _op("delete_record")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target="bounded_sample", descriptor_set=ds, cap_ledger=None)
        self.assertEqual(r.status, "refused")
        self.assertIn("ledger", r.detail["reason"].lower())


# ---------------------------------------------------------------------------
# T1 — native_undo mirrors bounded_sample (same LIVE_BOUNDED class)
# ---------------------------------------------------------------------------

class TestLiveNativeUndoGating(unittest.TestCase):
    def test_declared_entry_permits(self):
        ds = [_accepted_entry(accepted=False, declared_test_target="native_undo",
                              risk_class="irreversible_external", blast_radius_cap=2)]
        op = _op("delete_record")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target="native_undo", descriptor_set=ds,
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "written")

    def test_undeclared_capability_refused(self):
        op = _op("delete_record")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target="native_undo", descriptor_set=[],
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "refused")
        self.assertIn("declared", r.detail["reason"].lower())


# ---------------------------------------------------------------------------
# T1 — R5: mandatory blast-radius cap for EVERY gated risk class on live/live-bounded
# ---------------------------------------------------------------------------

class TestR5MandatoryCapAllGatedClasses(unittest.TestCase):
    def setUp(self):
        contracts_mod.OPERATION_CONTRACTS["_sensitive_probe"] = OperationContract(
            op_kind="_sensitive_probe", writes=("Field",), produces=(),
            dependency_set=("adapters.py",), verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False, risk_class="sensitive_data")
        contracts_mod.OPERATION_CONTRACTS["_standing_cap_probe"] = OperationContract(
            op_kind="_standing_cap_probe", writes=("Field",), produces=(),
            dependency_set=("adapters.py",), verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False, risk_class="standing_automation")

    def tearDown(self):
        contracts_mod.OPERATION_CONTRACTS.pop("_sensitive_probe", None)
        contracts_mod.OPERATION_CONTRACTS.pop("_standing_cap_probe", None)

    def test_sensitive_data_live_no_cap_refused(self):
        op = _op("_sensitive_probe", field="Field")
        ds = [_accepted_entry(risk_class="sensitive_data")]  # accepted, no cap anywhere
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=ds,
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "refused")
        self.assertIn("cap", r.detail["reason"].lower())

    def test_sensitive_data_live_with_cap_permits(self):
        op = _op("_sensitive_probe", field="Field")
        ds = [_accepted_entry(risk_class="sensitive_data", blast_radius_cap=3)]
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=ds,
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "written")

    def test_standing_automation_live_no_cap_refused(self):
        # Recovery floor satisfied, cap absent -> mandatory-cap refuse (S-1).
        op = _op("_standing_cap_probe", field="Field")
        ds = [_accepted_entry(risk_class="standing_automation",
                              recovery_profile_ref="recovery_profiles/backup_v1")]
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=ds,
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "refused")
        self.assertIn("cap", r.detail["reason"].lower())

    def test_standing_automation_live_with_cap_permits(self):
        op = _op("_standing_cap_probe", field="Field")
        ds = [_accepted_entry(risk_class="standing_automation", blast_radius_cap=3,
                              recovery_profile_ref="recovery_profiles/backup_v1")]
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=ds,
                          cap_ledger=InvocationLedger())
        self.assertEqual(r.status, "written")


# ---------------------------------------------------------------------------
# T1 — single-object cap-slot invariant: one Operation = one write = one cap slot
# ---------------------------------------------------------------------------

class TestSingleObjectCapSlotInvariant(unittest.TestCase):
    def test_one_operation_consumes_exactly_one_slot(self):
        ds = [_accepted_entry(risk_class="irreversible_external", blast_radius_cap=5)]
        led = InvocationLedger()
        op = _op("delete_record", object_id="obj:solo")
        r = run_operation(op, _receipt(op), _AcceptingClient(),
                          target=LIVE_TARGET, descriptor_set=ds, cap_ledger=led)
        self.assertEqual(r.status, "written")
        self.assertEqual(led.count("google_sheets::delete_record"), 1)
        # A second run of the SAME Operation object is a second, independent invocation and
        # consumes a second slot — a single Operation never covers a batch (one object_id =
        # one write = one cap slot; Operation carries no query/bulk shape to mutate more).
        r2 = run_operation(op, _receipt(op), _AcceptingClient(),
                           target=LIVE_TARGET, descriptor_set=ds, cap_ledger=led)
        self.assertEqual(r2.status, "written")
        self.assertEqual(led.count("google_sheets::delete_record"), 2)


if __name__ == "__main__":
    unittest.main()
