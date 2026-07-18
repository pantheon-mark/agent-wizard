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
