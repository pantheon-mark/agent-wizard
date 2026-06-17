"""Adversarial test suite for the pure section-aware 3-way merge function.

Written test-first (TDD). Covers the property invariants and the case matrix
from the resolved design (mechanism = section-aware merge, NOT line-level diff3).

The merge parses base/ours/theirs into ordered blocks by ATX headings, then does
a 3-way merge at block granularity keyed by heading text (preamble keyed
positionally). All-or-nothing: any conflict or structural ambiguity yields
clean=False, merged=None, conflict_reason set. Never emits git conflict markers.
"""

import unittest

from section_merge import section_three_way_merge


class TestPropertyInvariants(unittest.TestCase):
    """Property invariants that must hold for any inputs (design property set)."""

    def test_base_base_theirs_yields_theirs(self):
        # merge(B, B, T) == T : ours unchanged, take theirs wholesale.
        base = "# Title\n\nIntro.\n\n## A\n\nAlpha body.\n"
        theirs = "# Title\n\nIntro changed.\n\n## A\n\nAlpha body changed.\n"
        result = section_three_way_merge(base, base, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged, theirs)

    def test_base_ours_base_yields_ours(self):
        # merge(B, O, B) == O : theirs unchanged, take ours wholesale.
        base = "# Title\n\nIntro.\n\n## A\n\nAlpha body.\n"
        ours = "# Title\n\nIntro mine.\n\n## A\n\nAlpha body mine.\n"
        result = section_three_way_merge(base, ours, base)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged, ours)

    def test_base_x_x_yields_x(self):
        # merge(B, X, X) == X : both changed identically, take once.
        base = "# Title\n\nIntro.\n\n## A\n\nAlpha body.\n"
        x = "# Title\n\nIntro both.\n\n## A\n\nAlpha both.\n"
        result = section_three_way_merge(base, x, x)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged, x)

    def test_conflict_yields_none_merged_never_partial(self):
        base = "# T\n\npre\n\n## A\n\nbody\n"
        ours = "# T\n\npre\n\n## A\n\nbody OURS\n"
        theirs = "# T\n\npre\n\n## A\n\nbody THEIRS\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertFalse(result.clean)
        self.assertIsNone(result.merged)
        self.assertTrue(result.conflict_reason)

    def test_clean_merge_contains_each_nonoverlapping_edit_exactly_once(self):
        base = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB body\n"
        ours = "# T\n\npre\n\n## A\n\nA EDITED\n\n## B\n\nB body\n"
        theirs = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB EDITED\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged.count("A EDITED"), 1)
        self.assertEqual(result.merged.count("B EDITED"), 1)

    def test_deterministic_same_inputs_same_bytes(self):
        base = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB body\n"
        ours = "# T\n\npre\n\n## A\n\nA EDITED\n\n## B\n\nB body\n\n## C\n\nnew C\n"
        theirs = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB EDITED\n"
        r1 = section_three_way_merge(base, ours, theirs)
        r2 = section_three_way_merge(base, ours, theirs)
        self.assertEqual(r1.clean, r2.clean)
        self.assertEqual(r1.merged, r2.merged)
        self.assertEqual(r1.conflict_reason, r2.conflict_reason)

    def test_conflict_never_contains_git_markers(self):
        base = "# T\n\npre\n\n## A\n\nbody\n"
        ours = "# T\n\npre\n\n## A\n\nbody OURS\n"
        theirs = "# T\n\npre\n\n## A\n\nbody THEIRS\n"
        result = section_three_way_merge(base, ours, theirs)
        # merged is None on conflict; assert no marker leakage even in any field.
        self.assertIsNone(result.merged)
        self.assertNotIn("<<<<<<<", result.conflict_reason)
        self.assertNotIn(">>>>>>>", result.conflict_reason)
        self.assertNotIn("=======", result.conflict_reason)

    def test_clean_merge_never_contains_git_markers(self):
        base = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB body\n"
        ours = "# T\n\npre\n\n## A\n\nA EDITED\n\n## B\n\nB body\n"
        theirs = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB EDITED\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertNotIn("<<<<<<<", result.merged)
        self.assertNotIn(">>>>>>>", result.merged)
        self.assertNotIn("=======", result.merged)


class TestCleanCases(unittest.TestCase):
    """Cases that MUST merge clean (design §7)."""

    def test_operator_edits_A_target_edits_B_both_land(self):
        base = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB body\n"
        ours = "# T\n\npre\n\n## A\n\nA OURS\n\n## B\n\nB body\n"
        theirs = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB THEIRS\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertIn("A OURS", result.merged)
        self.assertIn("B THEIRS", result.merged)

    def test_both_edit_same_section_identically(self):
        base = "# T\n\npre\n\n## A\n\nold\n"
        edited = "# T\n\npre\n\n## A\n\nnew identical\n"
        result = section_three_way_merge(base, edited, edited)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged, edited)

    def test_target_adds_new_section_operator_untouched(self):
        base = "# T\n\npre\n\n## A\n\nA body\n"
        ours = base
        theirs = "# T\n\npre\n\n## A\n\nA body\n\n## NEW\n\nnew body\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged, theirs)

    def test_operator_adds_new_section_target_untouched(self):
        base = "# T\n\npre\n\n## A\n\nA body\n"
        ours = "# T\n\npre\n\n## A\n\nA body\n\n## MINE\n\nmine body\n"
        theirs = base
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertIn("## MINE", result.merged)
        self.assertIn("mine body", result.merged)
        # ours-only added section preserved exactly once.
        self.assertEqual(result.merged.count("## MINE"), 1)

    def test_both_add_identical_named_section_with_identical_body(self):
        base = "# T\n\npre\n\n## A\n\nA body\n"
        added = "# T\n\npre\n\n## A\n\nA body\n\n## SAME\n\nsame body\n"
        result = section_three_way_merge(base, added, added)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged.count("## SAME"), 1)

    def test_operator_edit_plus_target_add_both_land(self):
        # ours edits A; theirs adds C. Non-overlapping → clean.
        base = "# T\n\npre\n\n## A\n\nA body\n"
        ours = "# T\n\npre\n\n## A\n\nA OURS\n"
        theirs = "# T\n\npre\n\n## A\n\nA body\n\n## C\n\nC body\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertIn("A OURS", result.merged)
        self.assertIn("## C", result.merged)


class TestConflictCases(unittest.TestCase):
    """Cases that MUST be flagged as conflict / ambiguity (design §7)."""

    def test_both_edit_same_section_differently(self):
        base = "# T\n\npre\n\n## A\n\nbody\n"
        ours = "# T\n\npre\n\n## A\n\nbody OURS\n"
        theirs = "# T\n\npre\n\n## A\n\nbody THEIRS\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertFalse(result.clean)
        self.assertIsNone(result.merged)

    def test_operator_edits_section_target_deletes(self):
        base = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB body\n"
        ours = "# T\n\npre\n\n## A\n\nA EDITED\n\n## B\n\nB body\n"
        theirs = "# T\n\npre\n\n## B\n\nB body\n"  # A deleted
        result = section_three_way_merge(base, ours, theirs)
        self.assertFalse(result.clean)
        self.assertIsNone(result.merged)

    def test_operator_deletes_section_target_edits(self):
        base = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB body\n"
        ours = "# T\n\npre\n\n## B\n\nB body\n"  # A deleted
        theirs = "# T\n\npre\n\n## A\n\nA EDITED\n\n## B\n\nB body\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertFalse(result.clean)
        self.assertIsNone(result.merged)

    def test_both_add_same_named_section_different_body(self):
        base = "# T\n\npre\n\n## A\n\nA body\n"
        ours = "# T\n\npre\n\n## A\n\nA body\n\n## NEW\n\nours new\n"
        theirs = "# T\n\npre\n\n## A\n\nA body\n\n## NEW\n\ntheirs new\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertFalse(result.clean)
        self.assertIsNone(result.merged)

    def test_duplicate_heading_identity_in_ours(self):
        base = "# T\n\npre\n\n## A\n\nA body\n"
        ours = "# T\n\npre\n\n## A\n\nfirst\n\n## A\n\nsecond\n"
        theirs = base
        result = section_three_way_merge(base, ours, theirs)
        self.assertFalse(result.clean)
        self.assertIsNone(result.merged)
        self.assertIn("## A", result.conflict_reason)

    def test_duplicate_heading_identity_in_base(self):
        base = "# T\n\npre\n\n## A\n\nfirst\n\n## A\n\nsecond\n"
        result = section_three_way_merge(base, base, base)
        self.assertFalse(result.clean)
        self.assertIsNone(result.merged)

    def test_duplicate_heading_identity_in_theirs(self):
        base = "# T\n\npre\n\n## A\n\nA body\n"
        theirs = "# T\n\npre\n\n## A\n\nfirst\n\n## A\n\nsecond\n"
        result = section_three_way_merge(base, base, theirs)
        self.assertFalse(result.clean)
        self.assertIsNone(result.merged)


class TestNaiveLineMergeCorruption(unittest.TestCase):
    """Prove section-aware approach does NOT corrupt repetitive markdown that
    would fool a naive line-level (difflib) merge."""

    def test_repeated_bullets_and_blank_lines_no_corruption(self):
        # Highly repetitive: identical bullet lines + blank lines across sections.
        # A line-level diff3 would false-align the repeated "- item" lines.
        base = (
            "# T\n\n"
            "intro\n\n"
            "## A\n\n"
            "- item\n"
            "- item\n"
            "- item\n\n"
            "## B\n\n"
            "- item\n"
            "- item\n"
            "- item\n"
        )
        # ours edits ONLY section A (adds a 4th bullet); B untouched.
        ours = (
            "# T\n\n"
            "intro\n\n"
            "## A\n\n"
            "- item\n"
            "- item\n"
            "- item\n"
            "- item\n\n"
            "## B\n\n"
            "- item\n"
            "- item\n"
            "- item\n"
        )
        # theirs edits ONLY section B (adds a 4th bullet); A untouched.
        theirs = (
            "# T\n\n"
            "intro\n\n"
            "## A\n\n"
            "- item\n"
            "- item\n"
            "- item\n\n"
            "## B\n\n"
            "- item\n"
            "- item\n"
            "- item\n"
            "- item\n"
        )
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        # Expected merged: A has 4 bullets, B has 4 bullets, structure intact.
        expected = (
            "# T\n\n"
            "intro\n\n"
            "## A\n\n"
            "- item\n"
            "- item\n"
            "- item\n"
            "- item\n\n"
            "## B\n\n"
            "- item\n"
            "- item\n"
            "- item\n"
            "- item\n"
        )
        self.assertEqual(result.merged, expected)
        # No duplicated or dropped headings.
        self.assertEqual(result.merged.count("## A"), 1)
        self.assertEqual(result.merged.count("## B"), 1)
        # Both sections grew to 4 bullets — neither dropped nor interleaved.
        a_block = result.merged.split("## A")[1].split("## B")[0]
        b_block = result.merged.split("## B")[1]
        self.assertEqual(a_block.count("- item"), 4)
        self.assertEqual(b_block.count("- item"), 4)


class TestSeparatorSemantics(unittest.TestCase):
    """The blank-line separator between sections is non-semantic (an edge gap),
    so an edit-A + add-C (which only shifts A's trailing separator) is clean,
    not a false conflict — and the assembled gap is well-formed."""

    def test_add_add_same_core_only_whitespace_trailer_differs_is_clean(self):
        # Both sides add an identical NEW section; theirs differs only by a
        # trailing EOF blank line. Core identical -> taken once, no conflict.
        base = "# T\n\npre\n\n## A\n\nA body\n"
        ours = "# T\n\npre\n\n## A\n\nA body\n\n## NEW\n\nnew\n"
        theirs = "# T\n\npre\n\n## A\n\nA body\n\n## NEW\n\nnew\n\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged.count("## NEW"), 1)

    def test_edit_A_add_C_produces_blank_separator_between_them(self):
        # ours edits A to its last block (no trailing gap); theirs adds C after A.
        # The A->C gap exists in theirs, so the merged output must have a blank
        # line between edited A and added C (no glued "A OURS\n## C").
        base = "# T\n\npre\n\n## A\n\nA body\n"
        ours = "# T\n\npre\n\n## A\n\nA OURS\n"
        theirs = "# T\n\npre\n\n## A\n\nA body\n\n## C\n\nC body\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertIn("A OURS\n\n## C", result.merged)
        self.assertNotIn("A OURS\n## C", result.merged)


class TestEdgeCases(unittest.TestCase):
    """Edge cases: newlines, CRLF, BOM, empty preamble, no headings."""

    def test_no_final_newline_preserved_clean_merge(self):
        # No trailing newline on the only-changed side; must not gain/lose bytes.
        base = "# T\n\npre\n\n## A\n\nbody"
        theirs = "# T\n\npre\n\n## A\n\nbody EDITED"
        result = section_three_way_merge(base, base, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged, theirs)
        self.assertFalse(result.merged.endswith("\n"))

    def test_final_newline_preserved_when_present(self):
        base = "# T\n\npre\n\n## A\n\nbody\n"
        theirs = "# T\n\npre\n\n## A\n\nbody EDITED\n"
        result = section_three_way_merge(base, base, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertTrue(result.merged.endswith("\n"))
        self.assertEqual(result.merged, theirs)

    def test_no_headings_single_preamble_one_side_changed_clean(self):
        # Whole-doc 3-way: at most one side changed → clean.
        base = "just prose\nno headings here\n"
        ours = base
        theirs = "just prose CHANGED\nno headings here\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged, theirs)

    def test_no_headings_both_sides_changed_differently_conflict(self):
        base = "just prose\nno headings\n"
        ours = "just prose OURS\nno headings\n"
        theirs = "just prose THEIRS\nno headings\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertFalse(result.clean)
        self.assertIsNone(result.merged)

    def test_no_headings_both_changed_identically_clean(self):
        base = "just prose\nno headings\n"
        same = "just prose SAME\nno headings\n"
        result = section_three_way_merge(base, same, same)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged, same)

    def test_empty_preamble_heading_first(self):
        # Document starts directly with a heading (empty preamble).
        base = "## A\n\nA body\n\n## B\n\nB body\n"
        ours = "## A\n\nA OURS\n\n## B\n\nB body\n"
        theirs = "## A\n\nA body\n\n## B\n\nB THEIRS\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertIn("A OURS", result.merged)
        self.assertIn("B THEIRS", result.merged)

    def test_crlf_inputs_not_corrupted(self):
        # CRLF line endings: merge must not silently produce mixed/garbled endings.
        base = "# T\r\n\r\npre\r\n\r\n## A\r\n\r\nbody\r\n"
        theirs = "# T\r\n\r\npre\r\n\r\n## A\r\n\r\nbody EDITED\r\n"
        result = section_three_way_merge(base, base, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        # merge(B,B,T) == T must hold regardless of line endings: byte-identical.
        self.assertEqual(result.merged, theirs)

    def test_crlf_section_aware_merge_both_sides(self):
        base = "# T\r\n\r\npre\r\n\r\n## A\r\n\r\nA body\r\n\r\n## B\r\n\r\nB body\r\n"
        ours = "# T\r\n\r\npre\r\n\r\n## A\r\n\r\nA OURS\r\n\r\n## B\r\n\r\nB body\r\n"
        theirs = "# T\r\n\r\npre\r\n\r\n## A\r\n\r\nA body\r\n\r\n## B\r\n\r\nB THEIRS\r\n"
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertIn("A OURS", result.merged)
        self.assertIn("B THEIRS", result.merged)
        # CRLF preserved, not silently converted to LF.
        self.assertIn("\r\n", result.merged)

    def test_bom_input_preserved_byte_identical_on_take_theirs(self):
        # BOM at file start: merge(B,B,T) == T must remain byte-identical
        # (BOM preserved in the preamble, not stripped).
        bom = "﻿"
        base = bom + "# T\n\npre\n\n## A\n\nbody\n"
        theirs = bom + "# T\n\npre\n\n## A\n\nbody EDITED\n"
        result = section_three_way_merge(base, base, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        self.assertEqual(result.merged, theirs)
        self.assertTrue(result.merged.startswith(bom))

    def test_idempotent_remerge_of_clean_result(self):
        # Re-running the merge with the merged result as ours and base=theirs'
        # render is exercised at integration; here assert determinism holds
        # when feeding the merged output back as both ours and theirs.
        base = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB body\n"
        ours = "# T\n\npre\n\n## A\n\nA OURS\n\n## B\n\nB body\n"
        theirs = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB THEIRS\n"
        merged = section_three_way_merge(base, ours, theirs).merged
        # merge(merged, merged, merged) == merged (X,X,X invariant).
        r = section_three_way_merge(merged, merged, merged)
        self.assertTrue(r.clean, r.conflict_reason)
        self.assertEqual(r.merged, merged)


class TestOursOnlyAddOrdering(unittest.TestCase):
    """Ordering rule for ours-only-added blocks: anchored after the ours-side
    preceding neighbor's key in the merged (theirs-ordered) output; appended at
    end if the neighbor is not present."""

    def test_ours_only_add_anchored_after_preceding_neighbor(self):
        # ours adds NEW right after A; theirs untouched. Merged should place NEW
        # after A (its ours-side predecessor), before B.
        base = "# T\n\npre\n\n## A\n\nA body\n\n## B\n\nB body\n"
        ours = "# T\n\npre\n\n## A\n\nA body\n\n## NEW\n\nnew body\n\n## B\n\nB body\n"
        theirs = base
        result = section_three_way_merge(base, ours, theirs)
        self.assertTrue(result.clean, result.conflict_reason)
        a_idx = result.merged.index("## A")
        new_idx = result.merged.index("## NEW")
        b_idx = result.merged.index("## B")
        self.assertLess(a_idx, new_idx)
        self.assertLess(new_idx, b_idx)


if __name__ == "__main__":
    unittest.main()
