"""Tests for build_structural_lint (Task C4): aggregates the C-structural cluster's
three build-time lints -- command shapes (C2, command_shape_lint), safety-notice
fidelity (C3, notice_fidelity_lint), and .gitignore SOURCE-template token coverage
(C1, new here) -- into one deterministic, category-prefixed violation list.

Anti-inert: each negative test below breaks exactly ONE artifact in an isolated
fixture repo_root (never the real dev tree) and drives the REAL sub-check function
through the aggregator, proving run_structural_lint() actually wires all three
checks rather than vacuously returning [] regardless of input.

Stdlib unittest; pip-install-free.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_structural_lint import (  # noqa: E402
    REPO_ROOT,
    REQUIRED_GITIGNORE_TOKENS,
    check_gitignore_coverage,
    run_structural_lint,
)
from notice_fidelity_lint import REQUIRED_CAVEAT_SUBSTRINGS  # noqa: E402


# ---- shared fixture content -------------------------------------------------
# Each negative test needs all three artifacts present (the aggregator's three
# sub-checks each read a fixed default relpath under repo_root), but only ONE of
# them genuinely broken -- these are the "everything else is fine" baselines.

_CLEAN_SKILL_MD = (
    "# Sample skill\n\n"
    "```bash\n"
    'python3 agents/lib/external_write/operator_acceptance.py --capability-id "x"\n'
    "```\n"
)

_BROKEN_SKILL_MD = (
    "# Sample skill\n\n"
    "```bash\n"
    "cat security/capability_descriptors.json | jq '.id'\n"
    "```\n"
)

_CLEAN_NOTICE_PY = (
    "# fixture deterministic notice source\n"
    "CAVEAT = (\n"
    "    \"do not rely on it being blocked until it is rebuilt\"\n"
    ")\n"
)

_BROKEN_NOTICE_PY = (
    "# fixture deterministic notice source with the caveat softened away\n"
    "CAVEAT = \"it has been switched off until it is rebuilt.\"\n"
)

_CLEAN_GITIGNORE = (
    "/security/acceptance_receipts/\n"
    "/security/run_envelopes/\n"
    "/security/invocation_ledgers/\n"
    "/security/capability_acceptance_log.jsonl\n"
)

_BROKEN_GITIGNORE = (
    # run_envelopes token dropped
    "/security/acceptance_receipts/\n"
    "/security/invocation_ledgers/\n"
    "/security/capability_acceptance_log.jsonl\n"
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_fixture_repo_root(*, broken: str) -> Path:
    """Build an isolated fixture repo_root with all three C-structural artifacts
    present and clean, except the ONE named by `broken` ("command-shape",
    "notice-fidelity", or "gitignore-coverage"), which is genuinely broken. Never
    touches the real dev tree -- caller is responsible for temp-dir cleanup being
    unnecessary (tempfile.mkdtemp under the OS temp dir, process-lifetime only)."""
    tmp = tempfile.mkdtemp(prefix="build_structural_lint_fixture_")
    root = Path(tmp)

    _write(root / "wizard/skills/next-phase.md",
           _BROKEN_SKILL_MD if broken == "command-shape" else _CLEAN_SKILL_MD)
    _write(root / "wizard/skills/add-capability.md", _CLEAN_SKILL_MD)

    _write(root / "wizard/scripts/lib/upgrade_reconcile.py",
           _BROKEN_NOTICE_PY if broken == "notice-fidelity" else _CLEAN_NOTICE_PY)

    _write(root / "wizard/templates/root/gitignore_template",
           _BROKEN_GITIGNORE if broken == "gitignore-coverage" else _CLEAN_GITIGNORE)

    return root


class RunStructuralLintPositiveTests(unittest.TestCase):
    """Anti-overfit: assert against the REAL repo source, not a hand-copied
    snippet -- this is the assertion that actually catches a C-structural
    regression across any of the three sub-checks."""

    def test_real_repo_source_is_clean(self):
        violations = run_structural_lint()
        self.assertEqual(
            violations, [],
            f"run_structural_lint() found violation(s) against the real repo "
            f"source, which should be clean now that C1/C2/C3 have landed: "
            f"{violations}",
        )

    def test_default_repo_root_is_the_real_repo(self):
        # Guards against a silently-misconfigured default that would make the
        # positive test above vacuous (e.g. an empty/wrong REPO_ROOT that just
        # never finds anything to scan).
        self.assertTrue((REPO_ROOT / "wizard" / "skills" / "next-phase.md").is_file())
        self.assertTrue(
            (REPO_ROOT / "wizard" / "templates" / "root" / "gitignore_template").is_file())


class RunStructuralLintNegativeTests(unittest.TestCase):
    """Each test breaks exactly ONE artifact in an isolated fixture repo_root and
    asserts the aggregate surfaces THAT category's prefix -- proving the
    aggregator actually routes each sub-check, not just returns [] by
    construction. Drives the REAL sub-check functions (check_skill_files,
    check_safety_notice_text, check_gitignore_coverage) against a genuinely
    broken fixture -- no mocking of the checks themselves."""

    def test_broken_command_shape_is_surfaced(self):
        fixture_root = _build_fixture_repo_root(broken="command-shape")
        violations = run_structural_lint(repo_root=fixture_root)
        self.assertTrue(
            any(v.startswith("command-shape:") for v in violations),
            f"a genuinely fragile-piped skill command was not surfaced as "
            f"command-shape: {violations}",
        )
        self.assertFalse(any(v.startswith("notice-fidelity:") for v in violations))
        self.assertFalse(any(v.startswith("gitignore-coverage:") for v in violations))

    def test_broken_notice_fidelity_is_surfaced(self):
        fixture_root = _build_fixture_repo_root(broken="notice-fidelity")
        violations = run_structural_lint(repo_root=fixture_root)
        self.assertTrue(
            any(v.startswith("notice-fidelity:") for v in violations),
            f"a genuinely stripped safety caveat was not surfaced as "
            f"notice-fidelity: {violations}",
        )
        self.assertIn(
            f"notice-fidelity: missing caveat: {REQUIRED_CAVEAT_SUBSTRINGS[0]}",
            violations,
        )
        self.assertFalse(any(v.startswith("command-shape:") for v in violations))
        self.assertFalse(any(v.startswith("gitignore-coverage:") for v in violations))

    def test_broken_gitignore_coverage_is_surfaced(self):
        fixture_root = _build_fixture_repo_root(broken="gitignore-coverage")
        violations = run_structural_lint(repo_root=fixture_root)
        self.assertTrue(
            any(v.startswith("gitignore-coverage:") for v in violations),
            f"a genuinely token-missing gitignore template was not surfaced as "
            f"gitignore-coverage: {violations}",
        )
        self.assertIn("gitignore-coverage: missing token: run_envelopes", violations)
        self.assertFalse(any(v.startswith("command-shape:") for v in violations))
        self.assertFalse(any(v.startswith("notice-fidelity:") for v in violations))


class CheckGitignoreCoverageUnitTests(unittest.TestCase):
    """Direct unit tests of the new check_gitignore_coverage(), independent of the
    aggregator -- mirrors the sibling checks' own direct-unit-test convention."""

    def test_real_source_template_is_clean(self):
        missing = check_gitignore_coverage()
        self.assertEqual(missing, [])

    def test_flags_missing_token_against_a_stripped_copy(self):
        fixture_root = _build_fixture_repo_root(broken="gitignore-coverage")
        missing = check_gitignore_coverage(repo_root=fixture_root)
        self.assertEqual(missing, ["run_envelopes"])

    def test_required_tokens_match_c1s_documented_token_set(self):
        # Documented, deliberate duplication across layers (this checks the
        # SOURCE template; C1's test_emit_gitignore.py checks the EMITTED
        # .gitignore) -- not a refactor target. This just pins that the two
        # independently-defined token sets stay in agreement.
        self.assertEqual(
            set(REQUIRED_GITIGNORE_TOKENS),
            {"security/acceptance_receipts", "run_envelopes", "invocation_ledgers",
             "capability_acceptance_log"},
        )


if __name__ == "__main__":
    unittest.main()
