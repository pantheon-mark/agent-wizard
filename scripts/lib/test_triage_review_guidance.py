"""Content-presence test for triage-review.md (Task D6b — Cut 1.1 Cluster D).

Root cause this guards against (F-79/F-80): the estate's triage-review flow
hand-rolled a per-batch loop that re-minted a run envelope for EVERY batch
(restarting the run_id counter at 1 each invocation) and synthesized one
"yes go ahead" into eleven separate per-batch consent receipts stamped with
machine-paced timestamps -- 225 first-pass manifests were silently
overwritten (F-79) and the operator's single approval was multiplied into a
consent record that never actually happened eleven times (F-80).

D6a closed the mechanism side (`run_sanctioned_bulk` in run_envelope.py --
one call = one mint = one run-level consent = many tranches). This test
locks the PROSE side: the emitted skill guidance must actually point a naive
unassisted agent at that one right thing to call, instead of leaving it to
improvise the broken loop the estate invented.

Mirrors the content-presence style of Cut 1's build_structural_lint /
notice-fidelity tests: read the .md as plain text and assert on substance,
not exact wording (the skill's voice is free to evolve; these anchors are
the load-bearing invariants).

Stdlib unittest; pip-install-free.
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "wizard" / "skills"
TRIAGE_REVIEW_PATH = SKILLS_DIR / "triage-review.md"


class TriageReviewGuidanceTests(unittest.TestCase):

    def setUp(self):
        self.assertTrue(
            TRIAGE_REVIEW_PATH.is_file(),
            f"expected {TRIAGE_REVIEW_PATH} to exist",
        )
        self.text = TRIAGE_REVIEW_PATH.read_text(encoding="utf-8")

    # -- (a) hands off to the sanctioned helper, speaks to the real
    # operator-utterance time, and covers resume ---------------------------

    def test_references_run_sanctioned_bulk(self):
        self.assertIn("run_sanctioned_bulk", self.text)

    def test_references_approved_at(self):
        self.assertIn("approved_at", self.text)

    def test_speaks_to_the_real_operator_utterance_time(self):
        self.assertRegex(
            self.text,
            r"operator-utterance|the real moment|when the operator",
        )

    def test_covers_resume_via_resume_run_id(self):
        self.assertIn("resume_run_id", self.text)

    def test_resume_requires_a_fresh_confirmation(self):
        self.assertIn("fresh_operator_approval_verbatim", self.text)
        self.assertIn("fresh_approved_at", self.text)

    def test_has_an_interrupted_run_subsection(self):
        self.assertRegex(self.text, r"[Ii]f a run is interrupted")

    # -- (b) NO per-batch-mint anti-pattern ---------------------------------

    def test_never_names_the_mint_entrypoint(self):
        # The helper owns the mint now (Decision 1) -- the skill must not
        # instruct calling it itself, per batch or at all.
        self.assertNotIn("mint_run_envelope", self.text)

    def test_never_a_machine_consent_time(self):
        self.assertNotRegex(self.text, r"datetime\.now|time\.time")

    def test_does_not_instruct_a_per_batch_loop(self):
        # Belt-and-suspenders: the estate's exact anti-pattern shape
        # (re-minting inside a per-batch/loop context) must not be
        # reintroduced as an AFFIRMATIVE instruction. Deliberately excludes
        # negated phrasing ("do not ... per batch") -- the skill is expected
        # to say that explicitly; only a positive instruction to do it would
        # be the regression.
        self.assertNotRegex(self.text, r"per[- ]batch (loop|mint)")
        self.assertNotRegex(
            self.text,
            r"(?<!not )(?<!never )mint (a|the|one) (new )?(run )?envelope.{0,20}"
            r"(each|every|per) batch",
        )


if __name__ == "__main__":
    unittest.main()
