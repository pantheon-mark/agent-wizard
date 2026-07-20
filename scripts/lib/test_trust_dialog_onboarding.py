"""Content-presence test for manual.md's guided trust-dialog onboarding step
(Task C4 -- Cut 1.1 Cluster C, F-78).

Root cause this guards against (F-78): in the estate, recovering from the
permission classifier required Shift+Tab permission-mode coaching -- a
non-technical operator cannot reason about harness permission modes. Task C2's
settings.json allowlist only takes effect after the operator accepts Claude
Code's workspace-TRUST dialog ("Yes, I trust this folder") for a project with
checked-in allow-rules (Q4, docs/superpowers/plans/2026-07-19-cut1.1-C.md).

Q4's design-improving consequence (locked): the safety gating (deny/ask on
live-writes) works WITH OR WITHOUT the operator accepting trust -- declining
trust just means MORE prompts on the safe read-only commands (lost
convenience), NOT less safety. So the onboarding must LEAD the operator
through accepting the dialog in plain language, frame it as a convenience
(not a safety dependency), and never instruct raw Shift+Tab / permission-mode
gymnastics as a recovery path.

Mirrors the content-presence style of test_triage_review_guidance.py (D6b) /
the Cluster A and C guidance tests: read the .md as plain text and assert on
substance, not exact wording (the manual's voice is free to evolve; these
anchors are the load-bearing invariants).

Stdlib unittest; pip-install-free.
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MANUAL_PATH = REPO_ROOT / "wizard" / "templates" / "root" / "manual.md"


class TrustDialogOnboardingGuidanceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        assert MANUAL_PATH.is_file(), f"expected {MANUAL_PATH} to exist"
        cls.text = MANUAL_PATH.read_text(encoding="utf-8")

    # -- (a) plain-language trust-acceptance step is present -----------------

    def test_names_the_trust_dialog_acceptance_phrase(self):
        # The exact button text the plan locks (Q4) -- a non-technical operator
        # gets a literal instruction, not a paraphrase they have to interpret.
        self.assertIn("Yes, I trust this folder", self.text)

    def test_frames_it_as_a_one_time_question_on_first_open(self):
        self.assertRegex(
            self.text,
            r"first time you open this (project|folder)",
        )

    def test_names_claude_code_as_the_thing_asking(self):
        self.assertIn("Claude Code", self.text)

    # -- (b) NO Shift+Tab / permission-mode reasoning -------------------------

    def test_never_instructs_shift_tab(self):
        self.assertNotRegex(self.text, r"[Ss]hift[\s+-]?[Tt]ab")

    def test_never_asks_the_operator_to_reason_about_permission_modes(self):
        self.assertNotRegex(self.text, r"permission mode")
        self.assertNotRegex(self.text, r"bypass\s*permissions?")
        self.assertNotIn("auto-accept edits", self.text)

    # -- (c) convenience-not-safety framing (Q4) ------------------------------

    def test_states_the_system_protects_either_way(self):
        self.assertRegex(
            self.text,
            r"(protects you the same way either way|safe (either way|with or without)|"
            r"same way (whether|either))",
        )

    def test_declining_costs_convenience_not_safety(self):
        # Declining/skipping trust must be framed as "more prompts", never as
        # "less safe" or "unsafe".
        self.assertRegex(self.text, r"(more (of )?those prompts|ask(ed)? more often)")

    def test_never_frames_declining_as_unsafe(self):
        lower = self.text.lower()
        self.assertNotIn("unsafe if you", lower)
        self.assertNotIn("not safe unless", lower)
        self.assertNotIn("must accept to be safe", lower)
        self.assertNotRegex(
            lower,
            r"(unsafe|not safe|less safe) (if|unless|without) you (skip|decline|don't (click|accept))",
        )


if __name__ == "__main__":
    unittest.main()
