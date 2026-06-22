"""Tests for the typed honest-status contract at the upgrade-check surface.

This is the C6' typed-status honesty contract: every upgrade-check outcome carries a
typed `UpdateStatus` + a `reason_code` + structured fields, maps to a distinct CLI
exit code, and renders through an EXHAUSTIVE renderer that must raise on any unhandled
status. The load-bearing invariant: NO status other than CHECKED_CURRENT may render an
"up to date" message — a "could not check" outcome must never be reported as
"you're up to date".

Anti-overfit posture: the up-to-date invariant is asserted by enumerating ALL enum
members (not one fixture), and the exit-code mapping is asserted exhaustive + injective
per class. Failure-path classification is exercised across divergent broken inputs
(missing registry, unparseable registry, absent update source) so a single happy-path
fixture cannot mask a collapse-to-"current" bug.
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # wizard/scripts (CLI)

from upgrade import (  # noqa: E402
    UpdateStatus,
    UpdateCheckOutcome,
    status_exit_code,
    render_update_status,
    EXIT_CHECKED_CURRENT,
    EXIT_UPDATE_AVAILABLE,
    classify_update_status,
    UpgradeCheckResult,
    DriftReport,
)


# Phrases that assert the system is current. NO status but CHECKED_CURRENT may emit one.
_UP_TO_DATE_PHRASES = (
    "up to date",
    "up-to-date",
    "fully up to date",
    "nothing to do",
    "no updates",
    "latest version",
    "you're current",
    "youre current",
    "already current",
)

# Phrases a "could not check / unknown" status must carry so the operator is not
# falsely reassured.
_COULD_NOT_CHECK_PHRASES = (
    "could not check",
    "couldn't check",
    "status unknown",
    "unable to check",
    "can't check",
    "cannot check",
)

_REQUIRED_STATUSES = {
    "UPDATE_AVAILABLE",
    "CHECKED_CURRENT",
    "COULD_NOT_CHECK",
    "TOOLKIT_UNVERIFIED",
    "SOURCE_UNCONFIGURED",
    "ENGINE_TOO_OLD",
    "NETWORK_UNAVAILABLE",
    "REGISTRY_INVALID",
    "CANDIDATE_UNVERIFIED",
    "UPDATE_SOURCE_TAMPERED",
}

# The "could not determine" class: statuses that mean the system FAILED to establish
# whether an update exists. None of these may render up-to-date. This is the full set
# used for the exit-code-distinctness assertion.
_COULD_NOT_DETERMINE = {
    UpdateStatus.COULD_NOT_CHECK,
    UpdateStatus.TOOLKIT_UNVERIFIED,
    UpdateStatus.SOURCE_UNCONFIGURED,
    UpdateStatus.NETWORK_UNAVAILABLE,
    UpdateStatus.REGISTRY_INVALID,
    UpdateStatus.CANDIDATE_UNVERIFIED,
    UpdateStatus.UPDATE_SOURCE_TAMPERED,
    UpdateStatus.ENGINE_TOO_OLD,
}

# The subset that must render an explicit "could not check / status unknown" message
# (per the task spec). ENGINE_TOO_OLD / CANDIDATE_UNVERIFIED / UPDATE_SOURCE_TAMPERED
# render their own distinct honest message; they only must NOT be up-to-date.
_MUST_RENDER_COULD_NOT_CHECK = {
    UpdateStatus.COULD_NOT_CHECK,
    UpdateStatus.TOOLKIT_UNVERIFIED,
    UpdateStatus.SOURCE_UNCONFIGURED,
    UpdateStatus.NETWORK_UNAVAILABLE,
    UpdateStatus.REGISTRY_INVALID,
}


class TestEnumShape(unittest.TestCase):
    def test_enum_carries_all_required_statuses(self):
        names = {m.name for m in UpdateStatus}
        missing = _REQUIRED_STATUSES - names
        self.assertEqual(missing, set(), f"UpdateStatus missing required members: {missing}")


class TestExhaustiveRenderer(unittest.TestCase):
    def test_renderer_handles_every_status(self):
        """The renderer is EXHAUSTIVE: every status renders a non-empty string."""
        for status in UpdateStatus:
            outcome = UpdateCheckOutcome(status=status, reason_code="r_test")
            msg = render_update_status(outcome)
            self.assertTrue(msg and msg.strip(), f"empty render for {status}")

    def test_renderer_raises_on_unhandled_status(self):
        """A status the renderer does not explicitly handle must RAISE, never silently
        fall through to a default. We simulate an unhandled member by passing a
        sentinel object the renderer does not know."""
        class _Bogus:
            name = "BOGUS_UNHANDLED"
        outcome = UpdateCheckOutcome(status=_Bogus(), reason_code="r_x")
        with self.assertRaises((ValueError, AssertionError, KeyError)):
            render_update_status(outcome)


class TestUpToDateInvariant(unittest.TestCase):
    def test_only_checked_current_renders_up_to_date(self):
        """LOAD-BEARING invariant across ALL statuses: only CHECKED_CURRENT may emit an
        up-to-date phrase. Every other status must NOT."""
        for status in UpdateStatus:
            outcome = UpdateCheckOutcome(status=status, reason_code="r_test")
            msg = render_update_status(outcome).lower()
            has_uptodate = any(p in msg for p in _UP_TO_DATE_PHRASES)
            if status == UpdateStatus.CHECKED_CURRENT:
                self.assertTrue(
                    has_uptodate,
                    f"CHECKED_CURRENT must render an up-to-date message; got {msg!r}",
                )
            else:
                self.assertFalse(
                    has_uptodate,
                    f"{status} must NOT render an up-to-date message; got {msg!r}",
                )

    def test_could_not_determine_statuses_render_unknown(self):
        """The named could-not-check statuses must render a 'could not check / status
        unknown' message (never silence, never up-to-date)."""
        for status in _MUST_RENDER_COULD_NOT_CHECK:
            outcome = UpdateCheckOutcome(status=status, reason_code="r_test")
            msg = render_update_status(outcome).lower()
            self.assertTrue(
                any(p in msg for p in _COULD_NOT_CHECK_PHRASES),
                f"{status} must render a could-not-check message; got {msg!r}",
            )


class TestExitCodeMapping(unittest.TestCase):
    def test_every_status_has_an_exit_code(self):
        for status in UpdateStatus:
            code = status_exit_code(status)
            self.assertIsInstance(code, int)

    def test_exit_code_raises_on_unhandled(self):
        class _Bogus:
            name = "BOGUS"
        with self.assertRaises((ValueError, AssertionError, KeyError)):
            status_exit_code(_Bogus())

    def test_checked_current_is_zero(self):
        self.assertEqual(status_exit_code(UpdateStatus.CHECKED_CURRENT), EXIT_CHECKED_CURRENT)
        self.assertEqual(EXIT_CHECKED_CURRENT, 0)

    def test_update_available_has_distinct_nonzero_code(self):
        code = status_exit_code(UpdateStatus.UPDATE_AVAILABLE)
        self.assertEqual(code, EXIT_UPDATE_AVAILABLE)
        self.assertNotEqual(code, 0)

    def test_could_not_determine_codes_are_distinct_nonzero(self):
        """Each could-not-determine class gets its own distinct non-zero exit code so a
        caller can branch on WHY the check failed (not collapse to a single 1)."""
        codes = {}
        for status in _COULD_NOT_DETERMINE:
            code = status_exit_code(status)
            self.assertNotEqual(code, 0, f"{status} must not map to 0 (success)")
            self.assertNotEqual(
                code, EXIT_UPDATE_AVAILABLE,
                f"{status} must not share the update-available code",
            )
            codes[status] = code
        # Distinct per status (injective across the could-not-determine class).
        self.assertEqual(
            len(set(codes.values())), len(codes),
            f"could-not-determine exit codes must be distinct; got {codes}",
        )


class TestClassifyUpdateStatus(unittest.TestCase):
    """classify_update_status maps a (legacy) UpgradeCheckResult-or-failure into the
    typed outcome. A missing/unparseable registry must classify REGISTRY_INVALID (not
    "no updates"); an absent update source SOURCE_UNCONFIGURED; a clean check with
    targets UPDATE_AVAILABLE; a clean check with none CHECKED_CURRENT."""

    def _result(self, targets):
        return UpgradeCheckResult(
            operator_project_path="/x",
            current_version="v0.6.0",
            available_targets=targets,
            drift_report=DriftReport(operator_project_path="/x", bundle_version="v0.6.0",
                                     target_bundle_version=None, entries=[]),
        )

    def test_targets_present_is_update_available(self):
        outcome = classify_update_status(self._result([{"foundation_bundle_version": "v0.6.1"}]))
        self.assertEqual(outcome.status, UpdateStatus.UPDATE_AVAILABLE)

    def test_no_targets_is_checked_current(self):
        outcome = classify_update_status(self._result([]))
        self.assertEqual(outcome.status, UpdateStatus.CHECKED_CURRENT)

    def test_registry_error_is_registry_invalid_not_current(self):
        from upgrade import RegistryError
        outcome = classify_update_status(RegistryError("registry not found at /x"))
        self.assertEqual(outcome.status, UpdateStatus.REGISTRY_INVALID)
        # Must NOT render up-to-date.
        msg = render_update_status(outcome).lower()
        self.assertFalse(any(p in msg for p in _UP_TO_DATE_PHRASES))

    def test_source_unconfigured_is_not_current(self):
        outcome = classify_update_status(None)  # no source/result at all
        self.assertEqual(outcome.status, UpdateStatus.SOURCE_UNCONFIGURED)
        msg = render_update_status(outcome).lower()
        self.assertFalse(any(p in msg for p in _UP_TO_DATE_PHRASES))


_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_REGISTRY = _REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"


def _make_operator_manifest(proj: Path, version: str) -> Path:
    """Minimal manifest-v1 (foundation-docs-only) operator project. Enough for
    upgrade-check to compute available targets + drift (empty managed_files)."""
    (proj / ".wizard").mkdir(parents=True, exist_ok=True)
    manifest = {
        "foundation_bundle_version": version,
        "managed_files": {},
    }
    mp = proj / ".wizard" / "manifest.json"
    mp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return mp


class CliTypedStatusTest(unittest.TestCase):
    """The `upgrade-check` CLI emits the typed status + reason_code under --json and
    returns the status-mapped exit code. NO failure path may exit 0 (current)."""

    def _run(self, argv):
        import wizard_upgrade as wu  # heavy module; local import
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = wu.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_update_available_exit_code_and_json(self):
        from upgrade import EXIT_UPDATE_AVAILABLE
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            mp = _make_operator_manifest(proj, "v0.6.0")  # v0.6.1 is newer in the real registry
            rc, out, err = self._run([
                "upgrade-check",
                "--manifest-path", str(mp),
                "--registry-path", str(_REAL_REGISTRY),
                "--json",
            ])
            self.assertEqual(rc, EXIT_UPDATE_AVAILABLE, f"stderr={err}")
            data = json.loads(out)
            self.assertEqual(data["status"], "update_available")
            self.assertIn("reason_code", data)

    def test_checked_current_exit_zero(self):
        from upgrade import EXIT_CHECKED_CURRENT, load_registry
        reg = load_registry(_REAL_REGISTRY)
        latest = sorted(
            (e["foundation_bundle_version"] for e in reg["bundles"]),
        )[-1]
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            mp = _make_operator_manifest(proj, latest)  # already latest -> current
            rc, out, err = self._run([
                "upgrade-check",
                "--manifest-path", str(mp),
                "--registry-path", str(_REAL_REGISTRY),
                "--json",
            ])
            self.assertEqual(rc, EXIT_CHECKED_CURRENT, f"stderr={err}")
            data = json.loads(out)
            self.assertEqual(data["status"], "checked_current")

    def test_missing_registry_is_registry_invalid_not_current(self):
        from upgrade import EXIT_REGISTRY_INVALID
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            mp = _make_operator_manifest(proj, "v0.6.0")
            missing = proj / "no-such-registry.json"
            rc, out, err = self._run([
                "upgrade-check",
                "--manifest-path", str(mp),
                "--registry-path", str(missing),
                "--json",
            ])
            # MUST NOT be 0 (current) and MUST be the registry-invalid code.
            self.assertEqual(rc, EXIT_REGISTRY_INVALID, f"out={out} err={err}")
            data = json.loads(out)
            self.assertEqual(data["status"], "registry_invalid")
            self.assertNotIn("up to date", data["message"].lower())


if __name__ == "__main__":
    unittest.main()
