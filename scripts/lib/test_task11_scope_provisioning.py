"""Tests for Task 11 (B3 / F-52,F-47 -- v0.13.0 Slice 2) -- "scope provisioning
at the non-technical bar".

Ground truth this closes: a live dogfood recorded a Gmail credential
"read-verified" from a check against the broader `gmail.modify` scope, while
the DECLARED read-only scope (`gmail.readonly`) had never actually been
checked or exercised. At live-trial time, a real read using that narrower
scope failed `unauthorized_client ... not authorized for any of the scopes
requested` -- with no offline signal ahead of it -- and the emitted flow then
routed the unassisted operator into a Google Workspace super-admin
domain-wide-delegation edit, mid-trial, right after a raw ~10-frame Python
traceback: a ~15-hour stall.

Five spec items, each with its own test group below:
  1. grant-check (offline, safe) -- adapter_registry.check_scope_grant +
     adapters.scope_preflight (TestCheckScopeGrantGeneric, TestScopePreflightJoin).
  2. exercise-record / deny-by-default "verified" --
     adapter_registry.resolve_scope_status (TestResolveScopeStatusDenyByDefault).
  3. live-trial-readiness gate (blocks the trial, not the build) --
     content assertions on next-phase.md (TestNextPhaseReadinessGateContent).
  4. IAM/DWD edits as a first-class, pre-checked, sequenced onboarding task --
     content assertions on credential-setup.md + 09_credentials.md
     (TestCredentialSetupAdminGrantContent, TestInterviewScopeCaptureContent).
  5. plain-language auth errors, never a traceback --
     adapters.describe_auth_failure (TestDescribeAuthFailure); the runner-side
     wiring itself is tested in test_external_write_standing_automation.py's
     TestLiveModeAuthFailureHandling.

Anti-overfit (mandatory): check_scope_grant / scope_preflight are proven over
TWO divergent op_kinds -- the real Gmail reference adapter (gmail.readonly,
a space-delimited tokeninfo "scope" string) AND a fixture "second
integration" (a Sheets-like op_kind, a LIST-shaped introspection response
under a "scopes" key) -- plus a non-OAuth auth type (an op_kind whose
contract declares no read_only_scope) proven to resolve N/A, never a false
failure.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AGENTS_LIB = _REPO_ROOT / "wizard" / "agents" / "lib"
_ADAPTERS_PY = _AGENTS_LIB / "external_write" / "adapters.py"
_WIZARD_DIR = _REPO_ROOT / "wizard"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.adapter_registry import (  # noqa: E402
    register_adapter,
    unregister_adapter,
    check_scope_grant,
    resolve_scope_status,
    GRANT_STATUS_GRANTED,
    GRANT_STATUS_NOT_GRANTED,
    GRANT_STATUS_NA,
    SCOPE_STATUS_NA,
    SCOPE_STATUS_NOT_GRANTED,
    SCOPE_STATUS_GRANTED_NOT_EXERCISED,
    SCOPE_STATUS_VERIFIED,
)
from external_write.contracts import (  # noqa: E402
    OperationContract,
    register_contract,
    _WRITE_AFFECTING_MODULES,
)
from external_write.adapters import scope_preflight, describe_auth_failure  # noqa: E402
from external_write.adapters_gmail import GmailMessageTrashAdapter  # noqa: E402


# ---------------------------------------------------------------------------
# Anti-overfit fixture: a "second integration" (Sheets-like) op_kind whose
# introspection response is shaped DIFFERENTLY from Gmail's (a LIST under
# "scopes", not a space-delimited string under "scope") -- proving
# check_scope_grant/scope_preflight are integration-agnostic: the kernel
# never inspects token_info shape itself, it only dispatches to whatever the
# adapter defines.
# ---------------------------------------------------------------------------

_FIXTURE_SHEETS_OP_KIND = "_task11_fixture.sheets.read_row"
_FIXTURE_SHEETS_SCOPE = "spreadsheets.readonly"

# A non-OAuth op_kind: reuse the real seeded "set_status" contract, which
# declares NO read_only_scope (it is an API-key-style field write) and has NO
# registered adapter -- the two independent reasons check_scope_grant/
# scope_preflight must resolve N/A.
_NON_OAUTH_OP_KIND = "set_status"


class _FixtureSheetsAdapter:
    """Minimal Adapter-protocol stub for the second-integration fixture.
    Deliberately duck-types plan/apply_one/undo_one/verify_one (never
    invoked by these tests) and defines grant_preflight against a LIST-
    shaped introspection response, unlike adapters_gmail's space-delimited
    string -- the anti-overfit shape divergence."""

    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        raise AssertionError("must never be called by an offline preflight test")

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, raw_client, unit):
        return {}

    def grant_preflight(self, token_info):
        if not isinstance(token_info, dict):
            return False
        return _FIXTURE_SHEETS_SCOPE in (token_info.get("scopes") or [])


def _register_fixture_sheets_integration():
    register_contract(OperationContract(
        op_kind=_FIXTURE_SHEETS_OP_KIND,
        writes=("row",),
        produces=(),
        dependency_set=_WRITE_AFFECTING_MODULES,
        verifier_set=("prestate_snapshot_diff_v1",),
        introduces_persistent_binding=False,
        read_only_scope=_FIXTURE_SHEETS_SCOPE,
    ))
    register_adapter(_FIXTURE_SHEETS_OP_KIND, _FixtureSheetsAdapter())


class TestCheckScopeGrantGeneric(unittest.TestCase):
    """Item 1 (grant-check) -- adapter_registry.check_scope_grant, the pure
    kernel primitive: declared_scope + token_info in, one of
    granted/not_granted/n/a out. Never touches contracts.py itself (see the
    module's own division-of-concerns docstring) -- declared_scope is always
    passed in explicitly here, exactly like adapters.scope_preflight
    (tested separately below) resolves it from contracts.get_contract."""

    def setUp(self):
        _register_fixture_sheets_integration()

    def tearDown(self):
        unregister_adapter(_FIXTURE_SHEETS_OP_KIND)

    def test_na_when_declared_scope_is_falsy(self):
        self.assertEqual(
            check_scope_grant(_NON_OAUTH_OP_KIND, None, {"scope": "anything"}),
            GRANT_STATUS_NA)
        self.assertEqual(
            check_scope_grant(_NON_OAUTH_OP_KIND, "", {"scope": "anything"}),
            GRANT_STATUS_NA)

    def test_na_when_op_kind_unregistered(self):
        self.assertEqual(
            check_scope_grant("_no_such_op_kind", "some.scope", {"scope": "some.scope"}),
            GRANT_STATUS_NA)

    def test_na_when_registered_adapter_defines_no_grant_preflight(self):
        class _NoGrantPreflightAdapter:
            def plan(self, params):
                return []

            def apply_one(self, raw_client, unit):
                pass

            def undo_one(self, raw_client, unit):
                pass

            def verify_one(self, raw_client, unit):
                return {}

        register_adapter("_task11_no_grant_preflight", _NoGrantPreflightAdapter())
        try:
            self.assertEqual(
                check_scope_grant("_task11_no_grant_preflight", "some.scope", {}),
                GRANT_STATUS_NA)
        finally:
            unregister_adapter("_task11_no_grant_preflight")

    def test_gmail_scope_granted_space_delimited_shape(self):
        register_adapter("gmail.message.trash", GmailMessageTrashAdapter())
        token_info = {"scope": "https://www.googleapis.com/auth/gmail.readonly other.scope"}
        self.assertEqual(
            check_scope_grant("gmail.message.trash", "gmail.readonly", token_info),
            GRANT_STATUS_GRANTED)

    def test_gmail_scope_not_granted_reproduces_the_incident(self):
        """The EXACT incident shape: the token carries the BROADER
        gmail.modify scope but NOT the declared gmail.readonly scope. Before
        this task, nothing checked this offline; the read failed live. This
        pins that check_scope_grant now catches it, offline, before any live
        trial."""
        register_adapter("gmail.message.trash", GmailMessageTrashAdapter())
        token_info = {"scope": "https://www.googleapis.com/auth/gmail.modify"}
        self.assertEqual(
            check_scope_grant("gmail.message.trash", "gmail.readonly", token_info),
            GRANT_STATUS_NOT_GRANTED)

    def test_second_integration_scope_granted_list_shape(self):
        """Anti-overfit: a DIFFERENT op_kind, a DIFFERENT scope string, and a
        DIFFERENT token_info shape (a list under "scopes", not a
        space-delimited "scope" string) -- check_scope_grant does not care;
        it only dispatches to the adapter's own grant_preflight."""
        token_info = {"scopes": ["spreadsheets.readonly", "drive.metadata.readonly"]}
        self.assertEqual(
            check_scope_grant(_FIXTURE_SHEETS_OP_KIND, _FIXTURE_SHEETS_SCOPE, token_info),
            GRANT_STATUS_GRANTED)

    def test_second_integration_scope_not_granted_list_shape(self):
        token_info = {"scopes": ["drive.metadata.readonly"]}
        self.assertEqual(
            check_scope_grant(_FIXTURE_SHEETS_OP_KIND, _FIXTURE_SHEETS_SCOPE, token_info),
            GRANT_STATUS_NOT_GRANTED)

    def test_grant_preflight_raising_resolves_not_granted_fail_safe(self):
        class _RaisingAdapter:
            def plan(self, params):
                return []

            def apply_one(self, raw_client, unit):
                pass

            def undo_one(self, raw_client, unit):
                pass

            def verify_one(self, raw_client, unit):
                return {}

            def grant_preflight(self, token_info):
                raise RuntimeError("malformed token_info")

        register_adapter("_task11_raising", _RaisingAdapter())
        try:
            self.assertEqual(
                check_scope_grant("_task11_raising", "some.scope", {"bad": True}),
                GRANT_STATUS_NOT_GRANTED)
        finally:
            unregister_adapter("_task11_raising")


class TestScopePreflightJoin(unittest.TestCase):
    """Item 1's contracts-join (adapters.scope_preflight) -- resolves
    op_kind's declared read_only_scope from its REGISTERED CONTRACT, then
    delegates to check_scope_grant. Proven over the same anti-overfit set:
    real Gmail op_kind, fixture second-integration op_kind, non-OAuth
    seeded op_kind."""

    def setUp(self):
        _register_fixture_sheets_integration()
        register_adapter("gmail.message.trash", GmailMessageTrashAdapter())

    def tearDown(self):
        unregister_adapter(_FIXTURE_SHEETS_OP_KIND)

    def test_non_oauth_op_kind_resolves_na(self):
        """set_status's contract declares no read_only_scope at all (an
        API-key-style field write) -- N/A, never a false failure."""
        self.assertEqual(scope_preflight(_NON_OAUTH_OP_KIND, {"scope": "irrelevant"}), GRANT_STATUS_NA)

    def test_unregistered_op_kind_resolves_na(self):
        self.assertEqual(scope_preflight("_no_such_op_kind_at_all", {}), GRANT_STATUS_NA)

    def test_gmail_op_kind_granted(self):
        token_info = {"scope": "https://www.googleapis.com/auth/gmail.readonly"}
        self.assertEqual(scope_preflight("gmail.message.trash", token_info), GRANT_STATUS_GRANTED)

    def test_gmail_op_kind_not_granted_incident_shape(self):
        token_info = {"scope": "https://www.googleapis.com/auth/gmail.modify"}
        self.assertEqual(scope_preflight("gmail.message.trash", token_info), GRANT_STATUS_NOT_GRANTED)

    def test_second_integration_op_kind_granted(self):
        token_info = {"scopes": ["spreadsheets.readonly"]}
        self.assertEqual(scope_preflight(_FIXTURE_SHEETS_OP_KIND, token_info), GRANT_STATUS_GRANTED)

    def test_second_integration_op_kind_not_granted(self):
        token_info = {"scopes": []}
        self.assertEqual(scope_preflight(_FIXTURE_SHEETS_OP_KIND, token_info), GRANT_STATUS_NOT_GRANTED)


class TestResolveScopeStatusDenyByDefault(unittest.TestCase):
    """Item 2 -- deny-by-default "verified". RED (what this pins against):
    a naive resolver that returns "verified" whenever grant_status is
    GRANTED, regardless of whether anything was ever actually exercised.
    GREEN: SCOPE_STATUS_VERIFIED is reachable ONLY via (GRANTED, exercised=True)."""

    def test_na_passthrough(self):
        self.assertEqual(resolve_scope_status(GRANT_STATUS_NA, exercised=False), SCOPE_STATUS_NA)
        self.assertEqual(resolve_scope_status(GRANT_STATUS_NA, exercised=True), SCOPE_STATUS_NA)

    def test_not_granted_never_verified_even_if_exercised_flag_is_true(self):
        """Deny-by-default beyond the naive case: even a caller bug that
        passes exercised=True alongside a not-granted grant-check must
        never be promoted to verified."""
        self.assertEqual(
            resolve_scope_status(GRANT_STATUS_NOT_GRANTED, exercised=True),
            SCOPE_STATUS_NOT_GRANTED)
        self.assertEqual(
            resolve_scope_status(GRANT_STATUS_NOT_GRANTED, exercised=False),
            SCOPE_STATUS_NOT_GRANTED)

    def test_granted_but_not_exercised_is_the_honest_intermediate_state_never_verified(self):
        self.assertEqual(
            resolve_scope_status(GRANT_STATUS_GRANTED, exercised=False),
            SCOPE_STATUS_GRANTED_NOT_EXERCISED)

    def test_granted_and_exercised_is_the_only_path_to_verified(self):
        self.assertEqual(
            resolve_scope_status(GRANT_STATUS_GRANTED, exercised=True),
            SCOPE_STATUS_VERIFIED)

    def test_verified_is_unreachable_without_both_conditions(self):
        """Exhaustive sweep: SCOPE_STATUS_VERIFIED must appear for exactly
        ONE of the four (grant_status, exercised) combinations exercised
        above."""
        combos = [
            (GRANT_STATUS_NA, False), (GRANT_STATUS_NA, True),
            (GRANT_STATUS_NOT_GRANTED, False), (GRANT_STATUS_NOT_GRANTED, True),
            (GRANT_STATUS_GRANTED, False), (GRANT_STATUS_GRANTED, True),
        ]
        verified_count = sum(
            1 for gs, ex in combos if resolve_scope_status(gs, exercised=ex) == SCOPE_STATUS_VERIFIED)
        self.assertEqual(verified_count, 1)


class TestDescribeAuthFailure(unittest.TestCase):
    """Item 5 -- the classifier `adapters.describe_auth_failure` used by the
    runner-side fix. Never a traceback, never an internal label leaked;
    non-auth-shaped exceptions return None (caller must re-raise)."""

    def test_unauthorized_client_classified_plain_language(self):
        exc = RuntimeError(
            "unauthorized_client: Client is not authorized for any of the scopes requested.")
        message = describe_auth_failure(exc)
        self.assertIsNotNone(message)
        self.assertNotIn("RuntimeError", message)
        self.assertNotIn("Traceback", message)
        self.assertIn("Credential Setup", message)

    def test_insufficient_scope_classified(self):
        self.assertIsNotNone(describe_auth_failure(PermissionError("insufficient_scope")))

    def test_http_403_classified(self):
        self.assertIsNotNone(describe_auth_failure(Exception("403 Client Error: Forbidden")))

    def test_http_401_classified(self):
        self.assertIsNotNone(describe_auth_failure(Exception("401 Unauthorized")))

    def test_invalid_grant_classified(self):
        self.assertIsNotNone(describe_auth_failure(Exception("invalid_grant: Token has been expired")))

    def test_non_auth_exception_returns_none(self):
        self.assertIsNone(describe_auth_failure(ValueError("the recipient list was empty")))
        self.assertIsNone(describe_auth_failure(KeyError("message_id")))

    def test_bare_status_number_without_auth_context_is_not_misclassified(self):
        """The over-firing guard: a non-auth exception that merely mentions
        the number 401/403 (a record count, an amount) must NOT be swallowed
        as an auth failure -- otherwise a genuine bug hides behind a 'check
        your credentials' message."""
        self.assertIsNone(describe_auth_failure(ValueError("processed 401 records successfully")))
        self.assertIsNone(describe_auth_failure(RuntimeError("row 403 had a malformed date")))

    def test_bare_forbidden_word_without_status_or_token_is_not_misclassified(self):
        """A plain business 'forbidden'/'unauthorized' word with no auth
        status code and no OAuth token must not be reclassified as auth."""
        self.assertIsNone(
            describe_auth_failure(ValueError("that combination is forbidden by the workflow rules")))

    def test_http_status_with_auth_context_still_classified(self):
        """The legitimate HTTP-auth case still fires: a 401/403 alongside an
        auth-context word (the real googleapiclient / requests shapes)."""
        self.assertIsNotNone(
            describe_auth_failure(Exception("HttpError 403 ... insufficient authentication scopes")))
        self.assertIsNotNone(
            describe_auth_failure(Exception("401 Client Error: Unauthorized for url")))

    def test_returned_message_is_a_single_plain_line_no_internal_labels(self):
        message = describe_auth_failure(RuntimeError("unauthorized_client"))
        self.assertNotIn("op_kind", message)
        self.assertNotIn("risk_class", message)
        self.assertNotIn("gmail.readonly", message)


class TestScopePreflightCLI(unittest.TestCase):
    """The "ONE validation command" (item 3's onboarding-task requirement) --
    adapters.py's __main__ CLI. Prints exactly one recognized status word,
    never a traceback, even on malformed input."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(_ADAPTERS_PY), *args],
            capture_output=True, text=True, cwd=str(_AGENTS_LIB),
            env={"PYTHONPATH": str(_AGENTS_LIB)})

    def test_granted_prints_granted_and_exits_zero(self):
        token_info = json.dumps({"scope": "https://www.googleapis.com/auth/gmail.readonly"})
        result = self._run("--op-kind", "gmail.message.trash", "--token-info-json", token_info)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "granted")

    def test_not_granted_prints_not_granted_and_exits_one(self):
        token_info = json.dumps({"scope": "https://www.googleapis.com/auth/gmail.modify"})
        result = self._run("--op-kind", "gmail.message.trash", "--token-info-json", token_info)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "not_granted")

    def test_non_oauth_op_kind_prints_na_and_exits_zero(self):
        result = self._run("--op-kind", "set_status", "--token-info-json", "{}")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "n/a")

    def test_malformed_json_never_a_traceback(self):
        result = self._run("--op-kind", "gmail.message.trash", "--token-info-json", "{not valid json")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("Traceback", result.stdout)

    def test_missing_argument_never_a_traceback(self):
        result = self._run("--op-kind", "gmail.message.trash")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


# ---------------------------------------------------------------------------
# Content assertions -- items 2, 3, 4 (the markdown/skill surfaces).
# ---------------------------------------------------------------------------

class TestCredentialsRegistryTemplateContent(unittest.TestCase):
    def _read(self):
        return (_WIZARD_DIR / "templates" / "security" / "credentials_registry.md").read_text(encoding="utf-8")

    def test_header_carries_the_three_new_columns(self):
        text = self._read()
        self.assertIn("Declared scope", text)
        self.assertIn("Needs admin grant", text)
        self.assertIn("Scope status", text)

    def test_deny_by_default_vocabulary_documented(self):
        text = self._read()
        self.assertIn("verified", text)
        self.assertIn("granted, not yet exercised", text)
        self.assertIn("not granted", text)
        # The deny-by-default rule itself must be stated in words, not just implied.
        self.assertIn("only", text.lower())


class TestCredentialSetupAdminGrantContent(unittest.TestCase):
    """Item 4 -- IAM/DWD edits must be a first-class, pre-checked, SEQUENCED
    onboarding task in credential-setup.md, before any obtaining/live step,
    never a mid-flow discovery."""

    def _read(self):
        return (_WIZARD_DIR / "skills" / "credential-setup.md").read_text(encoding="utf-8")

    def test_step_0_admin_grant_task_exists_and_precedes_step_1(self):
        text = self._read()
        step0_idx = text.find("### 0. Org-admin grant first")
        step1_idx = text.find("### 1. Explain it")
        self.assertNotEqual(step0_idx, -1, "Step 0 (admin-grant-first) task not found")
        self.assertNotEqual(step1_idx, -1)
        self.assertLess(step0_idx, step1_idx, "admin-grant task must be sequenced BEFORE Step 1")

    def test_admin_grant_task_names_domain_wide_delegation_and_admin_consent(self):
        text = self._read()
        self.assertIn("domain-wide-delegation", text)
        self.assertIn("admin consent", text)

    def test_offline_grant_check_documented_before_verified_claim(self):
        text = self._read()
        self.assertIn("tokeninfo", text)
        self.assertIn("granted, not yet exercised", text)
        self.assertIn("never `verified`", text.replace("**never**", "never"))

    def test_never_a_traceback_guidance_present(self):
        text = self._read()
        self.assertIn("never a traceback", text.lower())


class TestInterviewScopeCaptureContent(unittest.TestCase):
    """Item 4/1 -- the interview must capture declared scope + admin-grant
    need UP FRONT, so credential-setup never discovers it mid-flow."""

    def _read(self):
        return (_WIZARD_DIR / "interview" / "09_credentials.md").read_text(encoding="utf-8")

    def test_declared_scope_capture_present(self):
        text = self._read()
        self.assertIn("Declared scope", text)
        self.assertIn("narrowest scope", text)

    def test_admin_grant_capture_present(self):
        text = self._read()
        self.assertIn("org admin", text.lower())


class TestNextPhaseReadinessGateContent(unittest.TestCase):
    """Item 3 -- the offline scope-preflight readiness gate blocks ONLY the
    live trial, never the build, and emits a resumable onboarding task."""

    def _read(self):
        return (_WIZARD_DIR / "skills" / "next-phase.md").read_text(encoding="utf-8")

    def test_readiness_gate_present_in_step_3_before_build_steps(self):
        text = self._read()
        step3_idx = text.find("## Step 3: Credential check")
        gate_idx = text.find("Live-trial-readiness gate")
        step4_idx = text.find("## Step 4: Technical verification")
        self.assertNotEqual(step3_idx, -1)
        self.assertNotEqual(gate_idx, -1)
        self.assertNotEqual(step4_idx, -1)
        self.assertLess(step3_idx, gate_idx)
        self.assertLess(gate_idx, step4_idx)

    def test_gate_blocks_trial_not_build(self):
        text = self._read()
        self.assertIn("never blocks Steps 1", text.replace("1–4", "1-4").replace("–", "-"))

    def test_gate_stop_instruction_does_not_halt_step_4_build_verification(self):
        """Regression pin (self-review Finding 1): the gate's STOP/withhold
        instruction must name ONLY Step 5 (the supervised live trial), never
        Step 4 (technical verification / bringing agents to a runnable
        state) -- withholding Step 4 would block the build, contradicting
        the gate's own stated 'never blocks the build' design."""
        text = self._read()
        gate_start = text.find("### Live-trial-readiness gate")
        gate_end = text.find("\n## ", gate_start)
        gate_text = text[gate_start:gate_end if gate_end != -1 else len(text)]
        # The gate must not instruct halting/withholding Step 4.
        self.assertNotIn("do not proceed to Step 4", gate_text)
        self.assertNotIn("Step 4 or Step 5", gate_text)
        # It must explicitly permit Steps 1-4.
        self.assertIn("Steps 1", gate_text.replace("1–4", "1-4").replace("–", "-"))

    def test_gate_emits_resumable_onboarding_task_via_stub_tracker(self):
        text = self._read()
        self.assertIn("stub_tracker.md", text)
        self.assertIn("Type: `Credential`", text)

    def test_gate_names_the_one_validation_command(self):
        text = self._read()
        self.assertIn("adapters.py", text)


if __name__ == "__main__":
    unittest.main()
