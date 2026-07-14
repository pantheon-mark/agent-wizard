"""Tests for the safe standing-automation entrypoint primitive (Task 9, B2 / F-42 --
v0.13.0 Slice 2).

Ground truth this closes (log-confirmed, estate-tracker v0.11.0): an emitted
standing-automation runner had no dry-run/check mode, and its own hand-rolled
argv handling silently ignored an unrecognized flag (a `--checkonly` probe --
a flag that does not exist) and ran the full live job anyway -- a real,
unapproved, off-schedule email + digest went out. See
external_review/estate-tracker_dogfood_finding_B2-safe-standing-automation_2026-07-13.md.

Test intents:
  1. parse_standing_automation_args -- strict, fail-closed shapes only.
  2. run_standing_automation -- unrecognized flag => non-zero exit, NO call to
     build_operation / run_live / client (mocked; assert never called).
  3. run_standing_automation -- --check / --dry-run => zero external calls
     (client.write/client.read spy that raises if ever touched), proven on
     TWO divergent op_kinds (a v1 field-write op and a v2 Gmail verb op) --
     anti-overfit.
  4. run_standing_automation -- empty argv => the live path runs (run_live
     called exactly once; build_operation is NOT called by the primitive
     itself for a live run -- that is the caller's own job logic).
  5. The --check refusal branch (receipt expired) is exercised deterministically
     via an injected stale clock -- proven to still make zero external calls.
  6. No-bypass: a "generated wrapper" whose entire main() delegates ONLY to
     run_standing_automation cannot reproduce the F-42 defect -- fed the exact
     historical bad flag, it fails closed.
  7. Documentation propagation: agents/cron/cron_config.md's scaffold guidance
     mandates routing standing automation through this primitive.
  8. Enrollment: standing_automation.py is classified SEALED_KERNEL in zones.py
     and its real module scans clean under the CAPABILITY-only
     raw_run_operation_reference rule.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (the canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import Operation, SCHEMA_V2_ACTION  # noqa: E402
from external_write.standing_automation import (  # noqa: E402
    EXIT_BAD_ARGS,
    EXIT_OK,
    MODE_CHECK,
    MODE_LIVE,
    MODE_REFUSED,
    RECOGNIZED_FLAGS,
    parse_standing_automation_args,
    run_standing_automation,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER_DIR = _REPO_ROOT / "wizard" / "agents" / "lib" / "external_write"


# ---------------------------------------------------------------------------
# Fixture Operations -- anti-overfit: a v1 field-write op AND a v2 Gmail verb op.
# ---------------------------------------------------------------------------

def _sheet_status_op(batch_id="sweep-1"):
    """A seeded, ungated spreadsheet/field op_kind (schema v1)."""
    return Operation(
        surface="google_sheets",
        object_id="sheet:abc123",
        field="Status",
        new_value="Complete",
        op_kind="set_status",
        batch_id=batch_id,
    )


def _gmail_filter_op(batch_id="digest-1"):
    """A registered, GATED (standing_automation risk class) Gmail verb op_kind
    (schema v2). Its adapter's plan() is never called for a dry_run preview
    (run_operation's plan-hoist is skipped entirely for target="dry_run"), so
    minimal params suffice here -- proving the check path needs no real
    vendor-shaped payload."""
    return Operation(
        surface="gmail",
        op_kind="gmail.filter.create",
        batch_id=batch_id,
        schema=SCHEMA_V2_ACTION,
        params={"criteria": {}, "action": {}},
        undo_descriptor={"filter_id": None},
    )


# ---------------------------------------------------------------------------
# Spy client -- proves client.write / client.read are NEVER reached.
# ---------------------------------------------------------------------------

class _RaisingClient:
    """A spy client whose write/read RAISE if ever called -- the same
    no-mutation proof test_external_write_adapters.py's TestDryRunNoMutation
    uses, re-proven at this primitive's own boundary."""

    def write(self, object_id, field, value):
        raise AssertionError(
            "client.write must NEVER be called for a --check/--dry-run "
            f"standing-automation run (called with object_id={object_id!r}, "
            f"field={field!r}, value={value!r})")

    def read(self, object_id, field):
        raise AssertionError(
            "client.read must NEVER be called for a --check/--dry-run "
            f"standing-automation run (called with object_id={object_id!r}, "
            f"field={field!r})")


class _CountingCallable:
    """A hand-rolled call spy (this codebase does not use unittest.mock):
    records every call's args and a running count; returns a fixed value."""

    def __init__(self, return_value=None):
        self.return_value = return_value
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.return_value

    @property
    def call_count(self):
        return len(self.calls)


def _never_call(*_args, **_kwargs):
    raise AssertionError("this callable must NEVER be invoked for this code path")


# ---------------------------------------------------------------------------
# 1. parse_standing_automation_args -- strict, fail-closed shapes.
# ---------------------------------------------------------------------------

class TestParseStandingAutomationArgs(unittest.TestCase):
    def test_empty_argv_is_live(self):
        mode, error = parse_standing_automation_args([])
        self.assertEqual(mode, MODE_LIVE)
        self.assertIsNone(error)

    def test_check_flag_is_check(self):
        mode, error = parse_standing_automation_args(["--check"])
        self.assertEqual(mode, MODE_CHECK)
        self.assertIsNone(error)

    def test_dry_run_flag_is_check(self):
        mode, error = parse_standing_automation_args(["--dry-run"])
        self.assertEqual(mode, MODE_CHECK)
        self.assertIsNone(error)

    def test_unrecognized_flag_is_refused(self):
        # The exact historical F-42 defect: a --checkonly probe (a flag that
        # does not exist) must be refused, never silently ignored.
        mode, error = parse_standing_automation_args(["--checkonly"])
        self.assertIsNone(mode)
        self.assertIn("--checkonly", error)
        self.assertIn("Usage", error)

    def test_unrecognized_flag_message_never_a_traceback(self):
        _mode, error = parse_standing_automation_args(["--bogus"])
        self.assertNotIn("Traceback", error)
        self.assertNotIn("Exception", error)

    def test_two_recognized_flags_together_is_refused(self):
        # Deny-by-default: combining recognized flags is still not the one
        # shape this parser accepts.
        mode, error = parse_standing_automation_args(["--check", "--dry-run"])
        self.assertIsNone(mode)
        self.assertIsNotNone(error)

    def test_recognized_flag_plus_garbage_is_refused_and_names_the_garbage(self):
        mode, error = parse_standing_automation_args(["--check", "--foo"])
        self.assertIsNone(mode)
        self.assertIn("--foo", error)

    def test_stray_positional_argument_is_refused(self):
        mode, error = parse_standing_automation_args(["extra"])
        self.assertIsNone(mode)
        self.assertIn("extra", error)

    def test_recognized_flags_tuple_is_exactly_check_and_dry_run(self):
        self.assertEqual(set(RECOGNIZED_FLAGS), {"--check", "--dry-run"})


# ---------------------------------------------------------------------------
# 2 + 3. run_standing_automation -- the acceptance criteria.
# ---------------------------------------------------------------------------

class TestUnknownFlagRefusesWithNoSideEffect(unittest.TestCase):
    """Acceptance: unknown flag => exit non-zero + NO client call (mocked;
    assert no write/send) -- build_operation and run_live must ALSO never be
    reached; a parse failure returns before any of the three are touched."""

    def _run(self, argv):
        build_operation = _CountingCallable(return_value=_sheet_status_op())
        run_live = _CountingCallable(return_value="sent")
        client = _RaisingClient()
        outcome = run_standing_automation(
            argv, build_operation=build_operation, run_live=run_live, client=client)
        return outcome, build_operation, run_live

    def test_checkonly_probe_refuses_and_never_reaches_the_live_job(self):
        # The EXACT historical F-42 flag.
        outcome, build_operation, run_live = self._run(["--checkonly"])
        self.assertEqual(outcome.mode, MODE_REFUSED)
        self.assertEqual(outcome.exit_code, EXIT_BAD_ARGS)
        self.assertNotEqual(outcome.exit_code, 0)
        self.assertEqual(build_operation.call_count, 0)
        self.assertEqual(run_live.call_count, 0)

    def test_unrecognized_flag_message_is_plain_and_resumable(self):
        outcome, _b, _r = self._run(["--checkonly"])
        self.assertIn("--checkonly", outcome.message)
        self.assertIn("Usage", outcome.message)
        self.assertNotIn("Traceback", outcome.message)

    def test_garbage_flag_never_touches_client(self):
        # client is a _RaisingClient -- if the primitive ever called
        # client.write/read this test would raise instead of passing.
        outcome, _b, _r = self._run(["--frobnicate"])
        self.assertEqual(outcome.mode, MODE_REFUSED)
        self.assertNotEqual(outcome.exit_code, 0)


class TestCheckModeMakesZeroExternalCalls(unittest.TestCase):
    """Acceptance: --check => zero external calls. Proven on TWO divergent
    op_kinds (anti-overfit): a v1 spreadsheet field op and a v2 Gmail verb op,
    including one that is GATED (standing_automation risk class, normally
    refused live without an accepted descriptor) -- the dry_run preview must
    still make no external call regardless."""

    def _assert_zero_external_calls(self, op_builder, flag):
        build_operation = _CountingCallable(return_value=op_builder())
        client = _RaisingClient()
        outcome = run_standing_automation(
            [flag], build_operation=build_operation,
            run_live=_never_call, client=client)
        self.assertEqual(outcome.mode, MODE_CHECK)
        self.assertEqual(outcome.exit_code, EXIT_OK)
        self.assertEqual(build_operation.call_count, 1)
        return outcome

    def test_check_flag_sheet_field_op_zero_external_calls(self):
        self._assert_zero_external_calls(_sheet_status_op, "--check")

    def test_dry_run_flag_sheet_field_op_zero_external_calls(self):
        self._assert_zero_external_calls(_sheet_status_op, "--dry-run")

    def test_check_flag_gmail_verb_op_zero_external_calls(self):
        # Second, divergent op_kind (verb-shaped, v2 schema, standing_automation
        # risk class) -- proves the primitive is op_kind-agnostic.
        self._assert_zero_external_calls(_gmail_filter_op, "--check")

    def test_dry_run_flag_gmail_verb_op_zero_external_calls(self):
        self._assert_zero_external_calls(_gmail_filter_op, "--dry-run")

    def test_check_reports_permitted_outcome_in_plain_language(self):
        outcome = self._assert_zero_external_calls(_sheet_status_op, "--check")
        self.assertIn("nothing was sent, written, or changed", outcome.message)
        self.assertNotIn("Traceback", outcome.message)

    def test_check_never_invokes_run_live(self):
        build_operation = _CountingCallable(return_value=_sheet_status_op())
        run_live = _CountingCallable(return_value="should never happen")
        outcome = run_standing_automation(
            ["--check"], build_operation=build_operation,
            run_live=run_live, client=_RaisingClient())
        self.assertEqual(outcome.mode, MODE_CHECK)
        self.assertEqual(run_live.call_count, 0)


class TestCheckModeRefusalBranch(unittest.TestCase):
    """The underlying dry_run call can still be refused (e.g. an expired
    receipt) -- exercised deterministically via an injected stale clock so
    this branch is not a never-exercised latent path. Zero external calls
    either way: refusal happens at receipt validation, strictly before the
    no-mutation preview step -- client is never touched regardless of outcome."""

    def test_stale_clock_produces_a_refused_check_with_no_external_call(self):
        stale_clock = lambda: datetime(2000, 1, 1, tzinfo=timezone.utc)  # noqa: E731
        build_operation = _CountingCallable(return_value=_sheet_status_op())
        outcome = run_standing_automation(
            ["--check"], build_operation=build_operation,
            run_live=_never_call, client=_RaisingClient(), clock=stale_clock)
        self.assertEqual(outcome.mode, MODE_CHECK)
        self.assertEqual(outcome.exit_code, EXIT_OK)
        self.assertIn("NOT be allowed", outcome.message)
        self.assertIsNotNone(outcome.result)
        self.assertEqual(outcome.result.status, "refused")


class TestLiveModeRunsExactlyOnce(unittest.TestCase):
    """Baseline: the primitive does not break the ordinary path. Empty argv
    invokes run_live exactly once with `client`; build_operation is NOT called
    by the primitive itself for a live run (that is the caller's own job)."""

    def test_empty_argv_invokes_run_live_once(self):
        run_live = _CountingCallable(return_value="sent")
        client = object()
        outcome = run_standing_automation(
            [], build_operation=_never_call, run_live=run_live, client=client)
        self.assertEqual(outcome.mode, MODE_LIVE)
        self.assertEqual(outcome.exit_code, EXIT_OK)
        self.assertEqual(run_live.call_count, 1)
        self.assertEqual(run_live.calls[0][0], (client,))
        self.assertEqual(outcome.result, "sent")


# ---------------------------------------------------------------------------
# 6. No-bypass: a "generated wrapper" that delegates ENTIRELY to the primitive.
# ---------------------------------------------------------------------------

class _GeneratedStandingAutomationWrapper:
    """Models what a build session emits for a concrete standing automation
    (mirrors the real dogfood shape of a per-agent runner script) -- its ENTIRE
    argv decision is delegated to run_standing_automation. It has no branch of
    its own left to get wrong: there is no local flag check, no local
    "if unknown: proceed anyway" fallback -- exactly the shape that closes the
    F-42 defect structurally rather than by convention."""

    def __init__(self, build_operation, run_live, client):
        self._build_operation = build_operation
        self._run_live = run_live
        self._client = client

    def main(self, argv):
        outcome = run_standing_automation(
            argv, build_operation=self._build_operation,
            run_live=self._run_live, client=self._client)
        return outcome.exit_code, outcome.message


class TestGeneratedWrapperCannotBypassThePrimitive(unittest.TestCase):
    """The no-bypass acceptance criterion: a generated standing-automation
    wrapper built on this primitive cannot reach the live path on an
    unrecognized flag -- reproducing the exact historical F-42 scenario and
    proving it now fails closed instead."""

    def _wrapper(self):
        build_operation = _CountingCallable(return_value=_sheet_status_op())
        run_live = _CountingCallable(return_value="sent")
        client = _RaisingClient()
        wrapper = _GeneratedStandingAutomationWrapper(build_operation, run_live, client)
        return wrapper, build_operation, run_live

    def test_historical_checkonly_probe_no_longer_runs_live(self):
        wrapper, build_operation, run_live = self._wrapper()
        exit_code, message = wrapper.main(["--checkonly"])
        self.assertNotEqual(exit_code, 0)
        self.assertEqual(run_live.call_count, 0,
                         "a generated wrapper built on the primitive must never run the "
                         "live job for an unrecognized flag -- the exact F-42 regression")
        self.assertEqual(build_operation.call_count, 0)
        self.assertIn("--checkonly", message)

    def test_no_argv_permutation_other_than_recognized_shapes_reaches_live(self):
        garbage_permutations = [
            ["--Check"], ["-check"], ["--check="], ["--check", "extra"],
            ["--dry_run"], ["--verbose"], ["run"], [""],
        ]
        for argv in garbage_permutations:
            with self.subTest(argv=argv):
                wrapper, _build_operation, run_live = self._wrapper()
                exit_code, _message = wrapper.main(argv)
                self.assertNotEqual(exit_code, 0, f"argv {argv!r} unexpectedly succeeded")
                self.assertEqual(
                    run_live.call_count, 0,
                    f"argv {argv!r} unexpectedly reached the live job")

    def test_true_empty_argv_still_reaches_live_exactly_once(self):
        # Differential control: the wrapper is not merely refusing everything --
        # the one recognized live shape still works.
        wrapper, _build_operation, run_live = self._wrapper()
        exit_code, _message = wrapper.main([])
        self.assertEqual(exit_code, 0)
        self.assertEqual(run_live.call_count, 1)

    def test_check_flag_still_reaches_check_not_live(self):
        wrapper, build_operation, run_live = self._wrapper()
        exit_code, message = wrapper.main(["--check"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(run_live.call_count, 0)
        self.assertEqual(build_operation.call_count, 1)
        self.assertIn("nothing was sent, written, or changed", message)


# ---------------------------------------------------------------------------
# 7. Documentation propagation -- the enforcement-locus mandate.
# ---------------------------------------------------------------------------

class TestCronConfigDocumentsThePrimitive(unittest.TestCase):
    """cron_config.md's scaffold guidance (the wizard-authored source template,
    NOT a frozen foundation-bundles/ copy) must mandate routing every
    standing-automation runner through this primitive -- the documented half
    of the R1 F-R1.5 enforcement-locus decision (mechanism = this module;
    enforcement = the single scheduled-invocation routing boundary documented
    here, per cron_config.md's own single-coordination-point rule)."""

    def _text(self):
        path = (_REPO_ROOT / "wizard" / "templates" / "agents" / "cron_config.md")
        return path.read_text(encoding="utf-8")

    def test_mandates_the_safe_primitive_by_name(self):
        text = self._text()
        self.assertIn("standing_automation.py", text)
        self.assertIn("run_standing_automation", text)

    def test_states_fail_closed_and_check_behavior(self):
        text = self._text()
        self.assertIn("--check", text)
        self.assertIn("--dry-run", text)
        self.assertIn("never falls through to a live run", text)

    def test_never_bypassed_language_present(self):
        text = self._text()
        self.assertIn("never bypassed", text)


# ---------------------------------------------------------------------------
# 8. Zone classification -- standing_automation.py must be SEALED_KERNEL and
#    scan clean under the CAPABILITY-only raw_run_operation_reference rule.
# ---------------------------------------------------------------------------

class TestStandingAutomationZoneClassification(unittest.TestCase):
    def test_standing_automation_is_registered_sealed_kernel(self):
        from external_write.zones import SEALED_KERNEL_MODULE_PATHS
        self.assertIn("standing_automation.py", SEALED_KERNEL_MODULE_PATHS)

    def test_real_standing_automation_module_scans_clean(self):
        from external_write.scan import scan_paths
        v = scan_paths([_ADAPTER_DIR / "standing_automation.py"])
        self.assertEqual(v, [], f"real standing_automation.py must scan clean; got {v}")


if __name__ == "__main__":
    unittest.main()
