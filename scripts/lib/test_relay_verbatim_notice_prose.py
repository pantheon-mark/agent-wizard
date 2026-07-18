"""Tests for the relay-verbatim safety-notice convention in operating_discipline.md
(F-65, deliverable 2).

F-65 was reclassified as a safety/honesty notice-fidelity failure, not UX: during
the estate dogfood, the agent SUMMARIZED a deterministic safety notice (the
``broken_requires_migration`` pause/migration notice) and FLATTENED its honest
"do not rely on it being blocked until it is rebuilt" caveat when relaying it to
the operator. There was, until this task, NO standing convention telling the agent
to relay the system's own deterministic safety notices faithfully -- only
precedent conventions about foundational-document integrity (`CLAUDE.md`, agent
prompts: "do not operate from a recalled or summarized version") and about not
paraphrasing the operator's own acceptance (`next-phase.md:212`). This test asserts
the new convention prose is present in `operating_discipline.md` (mirrors the
content-assertion style of the existing operating_discipline tests in
`test_build_operate_emit.py`, e.g. `test_operating_discipline_states_controlled_vocab_rule`).

Stdlib unittest; pip-install-free.
"""

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(Path(__file__).resolve().parent))


class RelayVerbatimNoticeProseTests(unittest.TestCase):
    """operating_discipline.md carries a precedence-bearing convention: relay a
    deterministic safety notice faithfully, never summarize/soften/drop its
    caveat."""

    @classmethod
    def setUpClass(cls):
        cls.od_path = REPO_ROOT / "wizard" / "templates" / "root" / "operating_discipline.md"
        cls.od_text = cls.od_path.read_text(encoding="utf-8")

    def test_relay_verbatim_convention_present(self):
        """The convention names relaying a deterministic safety notice faithfully,
        without summarizing it away."""
        lower = self.od_text.lower()
        self.assertIn(
            "safety notice", lower,
            "operating_discipline.md must name the deterministic safety notice "
            "this convention governs",
        )
        self.assertTrue(
            ("faithfully" in lower) or ("verbatim" in lower),
            "operating_discipline.md must state a safety notice is relayed "
            "faithfully/verbatim",
        )
        self.assertIn(
            "summariz", lower,
            "operating_discipline.md must explicitly forbid summarizing a safety "
            "notice away",
        )

    def test_relay_verbatim_convention_forbids_softening_or_dropping_caveat(self):
        """The convention explicitly forbids softening or dropping a caveat --
        the exact failure mode observed in the estate dogfood (F-65)."""
        lower = self.od_text.lower()
        self.assertIn(
            "soften", lower,
            "operating_discipline.md must forbid softening a safety notice's caveat",
        )
        self.assertIn(
            "caveat", lower,
            "operating_discipline.md must name 'caveat' as the thing that must not "
            "be dropped or softened",
        )
        self.assertTrue(
            ("do not rely on" in lower) or ("do-not-rely-on" in lower),
            "operating_discipline.md must reference the 'do not rely on ...' style "
            "boundary caveat as the motivating example",
        )

    def test_relay_verbatim_convention_states_operator_terms_why(self):
        """The convention conveys WHY in plain operator terms: softening a caveat
        can lead the operator to consent to a weaker boundary than actually
        exists."""
        lower = self.od_text.lower()
        self.assertIn(
            "weaker", lower,
            "operating_discipline.md must state the operator-terms risk: consenting "
            "to a WEAKER boundary than actually exists",
        )

    def test_relay_verbatim_convention_no_internal_jargon_or_build_ids(self):
        """Public-boundary clean: no internal build IDs (ADR-NNNN, IDQ-NNN, S2.x,
        F-65 itself, private review-transcript path references) leak into the emitted operator prose."""
        pattern = re.compile(
            r'S2\.[0-9]|RW-[0-9]|ADR-[0-9]|IDQ-[0-9]|AR-[0-9]|W-[0-9]|F-65|external_review'
        )
        m = pattern.search(self.od_text)
        self.assertIsNone(m, f"internal build ID/jargon found in operating_discipline.md: {m}")

    def test_relay_verbatim_convention_near_honesty_cluster(self):
        """The convention lives in/near the honesty cluster -- specifically at or
        after the '### No absolute claims on a fresh mechanism' section, its
        natural home (that rule forbids OVER-claiming a mechanism's protection;
        this is its inverse: never UNDER-relay a mechanism's honest caveat)."""
        anchor = "no absolute claims on a fresh mechanism"
        lower = self.od_text.lower()
        anchor_idx = lower.find(anchor)
        self.assertNotEqual(anchor_idx, -1, "anchor section heading not found in operating_discipline.md")
        safety_notice_idx = lower.find("safety notice")
        self.assertNotEqual(safety_notice_idx, -1, "'safety notice' convention text not found")
        self.assertGreater(
            safety_notice_idx, anchor_idx,
            "the relay-verbatim convention must sit at/after the honesty-cluster "
            "anchor section, not scattered elsewhere in the document",
        )


if __name__ == "__main__":
    unittest.main()
