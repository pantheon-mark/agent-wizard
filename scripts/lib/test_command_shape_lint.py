"""Tests for command_shape_lint (F-64): emitted consent/acceptance commands must
never rely on fragile pipe-filtering.

F-64's real root cause: `next-phase.md` told the agent to "read the capability's id
from `security/capability_descriptors.json`" at three points but gave it no concrete,
pipe-free way to do that filtered lookup -- so the agent improvised a piped filter
(`cat ... | jq ...`), and that pipe tripped Claude Code's auto-mode classifier,
producing an opaque, off-voice denial mid-walkthrough. There was never an emitted
piped command to "rewrite" -- the fix is (1) give the agent an explicit,
classifier-safe, pipe-free lookup in the skill prose, and (2) a build-time lint
(this module under test) that keeps a fragile pipe from drifting back in.

Stdlib unittest; pip-install-free.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from command_shape_lint import (  # noqa: E402
    REPO_ROOT,
    check_skill_files,
    find_fragile_pipes,
)


class FindFragilePipesUnitTests(unittest.TestCase):
    """Direct unit tests against find_fragile_pipes() with known-bad and known-good
    strings -- isolates the detector's own logic from the real skill files."""

    def test_flags_cat_piped_into_jq(self):
        bad = "cat security/capability_descriptors.json | jq '.id'"
        offending = find_fragile_pipes(bad)
        self.assertEqual(
            offending, [bad],
            "known-bad piped-filter command was not flagged",
        )

    def test_flags_piped_grep(self):
        bad = "python3 some_script.py | grep pending"
        self.assertTrue(
            find_fragile_pipes(bad),
            "known-bad `| grep` command was not flagged",
        )

    def test_flags_each_fragile_filter_word(self):
        # One offending line per fragile-filter command name -- every word in the
        # documented list must actually trip the detector, not just the two above.
        for word in ("grep", "jq", "awk", "sed", "head", "tail", "cut", "tr",
                     "sort", "uniq", "python", "python3", "cat", "xargs", "wc"):
            with self.subTest(word=word):
                bad = f"some_command | {word} something"
                self.assertTrue(
                    find_fragile_pipes(bad),
                    f"fragile filter word {word!r} was not flagged",
                )

    def test_clean_direct_command_not_flagged(self):
        good = (
            'python3 agents/lib/external_write/operator_acceptance.py \\\n'
            '  --capability-id "acme_crm_sync" \\\n'
            '  --phase-id "phase_02" \\\n'
            '  --copy-run-proof "agents/handoffs/acme_crm_sync.copy_run_proof.json" \\\n'
            '  --operator-confirmation "Yes, turn it on"'
        )
        self.assertEqual(
            find_fragile_pipes(good), [],
            "clean, pipe-free direct command was incorrectly flagged",
        )

    def test_markdown_table_row_not_flagged(self):
        # Markdown table column separators use `|` too -- must never be mistaken for
        # a shell pipe into a filter command.
        table_row = "| Situation | What to do |"
        self.assertEqual(
            find_fragile_pipes(table_row), [],
            "markdown table row was incorrectly flagged as a fragile pipe",
        )

    def test_double_pipe_shell_guard_not_flagged(self):
        # `cmd || true` is a shell "or" guard, not a pipe into a filter.
        guard = "some_command || true"
        self.assertEqual(
            find_fragile_pipes(guard), [],
            "`|| true` shell guard was incorrectly flagged as a fragile pipe",
        )

    def test_word_boundary_no_false_positive_on_substring(self):
        # "concatenate" contains "cat"; "sorting" contains "sort" -- neither should
        # trip the detector via a bare substring match.
        text = "| concatenate everything\nsome text about sorting things"
        self.assertEqual(
            find_fragile_pipes(text), [],
            "word-boundary match incorrectly fired on a substring (concatenate/sorting)",
        )


class RealSkillFilesAreCleanTests(unittest.TestCase):
    """Anti-overfit: assert against the REAL emitted consent/acceptance skill files
    on disk, not a hand-copied snippet. This is the assertion that actually catches
    a regression back into a fragile piped lookup in next-phase.md or
    add-capability.md."""

    def test_next_phase_and_add_capability_have_no_fragile_pipes(self):
        violations = check_skill_files()
        self.assertEqual(
            violations, {},
            f"fragile pipe-filtering found in emitted consent/acceptance skill "
            f"file(s): {violations}",
        )

    def test_next_phase_md_exists_and_is_scanned(self):
        # Guards against a silently-empty/misconfigured scan (e.g. a typo'd relpath
        # that just never finds a match).
        next_phase = REPO_ROOT / "wizard" / "skills" / "next-phase.md"
        self.assertTrue(next_phase.exists(), f"not found: {next_phase}")
        text = next_phase.read_text(encoding="utf-8")
        self.assertIn("capability_descriptors.json", text)

    def test_add_capability_md_exists_and_is_scanned(self):
        add_capability = REPO_ROOT / "wizard" / "skills" / "add-capability.md"
        self.assertTrue(add_capability.exists(), f"not found: {add_capability}")


class ScopeExcludesHookScriptsTests(unittest.TestCase):
    """The lint must be scoped to the consent/acceptance skill files ONLY -- the
    harness hook scripts (context_monitor.sh / statusline.sh) legitimately pipe
    stdin into `python3 -c` internally and must never be flagged by this lint."""

    def test_default_scope_does_not_include_hook_scripts(self):
        from command_shape_lint import DEFAULT_SKILL_RELPATHS
        for relpath in DEFAULT_SKILL_RELPATHS:
            self.assertNotIn("context_monitor.sh", relpath)
            self.assertNotIn("statusline.sh", relpath)

    def test_hook_script_pipe_shape_would_be_flagged_if_misscoped(self):
        # Sanity check that the detector itself isn't just vacuously non-matching --
        # confirms find_fragile_pipes() DOES fire on the hook's own internal shape,
        # which is exactly why check_skill_files() must never be pointed at it.
        hook_shape = 'printf \'%s\' "$input" | python3 -c "import sys"'
        self.assertTrue(
            find_fragile_pipes(hook_shape),
            "sanity check failed: hook-internal pipe shape unexpectedly not detected "
            "(scope exclusion would be untestable)",
        )


if __name__ == "__main__":
    unittest.main()
