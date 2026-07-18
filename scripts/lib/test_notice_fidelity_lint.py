"""Tests for notice_fidelity_lint (F-65): the deterministic safety notice's honest
caveat text must be locked against silent removal or softening.

F-65 was reclassified as a safety/honesty notice-fidelity failure, not UX: during
the estate dogfood, the agent SUMMARIZED the deterministic
``broken_requires_migration`` pause/migration notice and FLATTENED its honest
caveat -- "do not rely on it being blocked until it is rebuilt". That caveat
already exists in ``wizard/scripts/lib/upgrade_reconcile.py``; this test does not
author new prose, it locks the existing caveat text in place with a reusable,
build-time-importable check (``check_safety_notice_text``) so a future edit to the
deterministic layer cannot silently drop or soften it.

Stdlib unittest; pip-install-free.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from notice_fidelity_lint import (  # noqa: E402
    REPO_ROOT,
    REQUIRED_CAVEAT_SUBSTRINGS,
    check_safety_notice_text,
)


class CheckSafetyNoticeTextTests(unittest.TestCase):
    """check_safety_notice_text() against the REAL upgrade_reconcile.py source --
    anti-overfit: this must read the actual deterministic file on disk, never a
    hand-copied snippet."""

    def test_real_upgrade_reconcile_carries_the_caveat(self):
        """The honest caveat already lives in upgrade_reconcile.py (ground truth
        confirmed pre-implementation) -- the check must find it present and report
        no missing substrings against the real repo file."""
        missing = check_safety_notice_text(repo_root=REPO_ROOT)
        self.assertEqual(
            missing, [],
            "check_safety_notice_text reports missing caveat substring(s) against "
            f"the real upgrade_reconcile.py: {missing!r}",
        )

    def test_flags_missing_substring_against_a_stripped_copy(self):
        """If the caveat text were removed from the source, the check must flag it
        -- proves this is a real lock, not a check that always passes."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            relpath = "wizard/scripts/lib/upgrade_reconcile.py"
            stripped_file = tmp_root / relpath
            stripped_file.parent.mkdir(parents=True, exist_ok=True)
            stripped_file.write_text(
                "# a version of the notice with the caveat softened away\n"
                "lines.append('it has been switched off until it is rebuilt.')\n",
                encoding="utf-8",
            )
            missing = check_safety_notice_text(repo_root=tmp_root, notice_relpath=relpath)
            self.assertEqual(
                missing, list(REQUIRED_CAVEAT_SUBSTRINGS),
                "check_safety_notice_text failed to flag a stripped/softened copy "
                "that no longer carries the caveat verbatim",
            )

    def test_flags_caveat_present_only_in_a_comment(self):
        """(DR-3 fix) A required caveat surviving ONLY in a code comment -- never in
        an actual string literal the deterministic notice source would print -- must
        be treated as MISSING. The prior implementation was a raw substring-in-
        file-text check, so a caveat softened out of the real notice string but left
        behind in a nearby comment would incorrectly report as present. The fixed
        check parses the source with ast and requires the caveat text to live inside
        an actual ast.Constant string literal, not merely somewhere in the file."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            relpath = "wizard/scripts/lib/upgrade_reconcile.py"
            comment_only_file = tmp_root / relpath
            comment_only_file.parent.mkdir(parents=True, exist_ok=True)
            comment_only_file.write_text(
                "# do not rely on it being blocked until it is rebuilt "
                "(comment only -- never a real string literal)\n"
                "lines.append('it has been switched off until it is rebuilt.')\n",
                encoding="utf-8",
            )
            missing = check_safety_notice_text(repo_root=tmp_root, notice_relpath=relpath)
            self.assertEqual(
                missing, list(REQUIRED_CAVEAT_SUBSTRINGS),
                "check_safety_notice_text must NOT be satisfied by a caveat that "
                f"survives only in a code comment: {missing!r}",
            )

    def test_real_notice_caveat_lives_in_a_string_literal_not_a_comment(self):
        """Sanity check on the fix's own positive case: the real caveat in
        upgrade_reconcile.py must be found INSIDE an actual string literal (not
        merely present as raw file text, e.g. in a comment) -- proves the ast-based
        check is not accidentally degenerate (always failing, or still just doing a
        raw text scan)."""
        missing = check_safety_notice_text(repo_root=REPO_ROOT)
        self.assertEqual(missing, [])

    def test_unparsable_source_fails_closed(self):
        """(DR-3) A source file that cannot even be parsed must never be silently
        treated as carrying the caveat -- fail-closed, not fail-open."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            relpath = "wizard/scripts/lib/upgrade_reconcile.py"
            unparsable_file = tmp_root / relpath
            unparsable_file.parent.mkdir(parents=True, exist_ok=True)
            unparsable_file.write_text("def broken(:\n    pass\n", encoding="utf-8")
            missing = check_safety_notice_text(repo_root=tmp_root, notice_relpath=relpath)
            self.assertEqual(missing, list(REQUIRED_CAVEAT_SUBSTRINGS))

    def test_required_caveat_substrings_names_the_exact_text(self):
        """Lock-guard sanity: the module's required substring is the exact ground-
        truth caveat text, not a paraphrase that would let a softened rewrite slip
        through."""
        self.assertIn(
            "do not rely on it being blocked until it is rebuilt",
            REQUIRED_CAVEAT_SUBSTRINGS,
        )


if __name__ == "__main__":
    unittest.main()
