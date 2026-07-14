"""Tests for the read-only judgment-path triage tool (Task 8, A3 / F-48 —
v0.13.0 Slice 2).

Invariants under test:
  * GROUPING — candidates are grouped by a GENERIC ``entity_key``; discovery
    is DEDUPED (exactly one row per entity_key, never N-rows-per-unit).
  * CLASSIFICATION — every group lands in exactly one of ``uniformly_safe``,
    ``contains_exceptions``, ``requires_review``, ``protected``.
  * BUCKETING IS A SAFETY SURFACE — a protected/destructive unit never lands
    in ``uniformly_safe``, however the rest of its group looks.
  * READ-ONLY — the module performs no external writes and imports nothing
    from the adapter/credential surface.
  * NO INBOX VOCABULARY — nothing in ``triage.py`` itself names "sender",
    "promo", "newsletter", etc. Those are a Gmail-adapter INSTANTIATION
    supplied by the caller, proven here with a non-Gmail candidate set (a
    sheet-row cleanup keyed on a key-column value).

Anti-overfit (Global Constraint #3): divergent rosters (all-safe / all-review
/ mixed) AND a non-Gmail candidate set, per the task brief.

Runner: unittest, from wizard/scripts. Stdlib only.
"""

import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.triage import (  # noqa: E402
    CATEGORY_CONTAINS_EXCEPTIONS,
    CATEGORY_PROTECTED,
    CATEGORY_REQUIRES_REVIEW,
    CATEGORY_UNIFORMLY_SAFE,
    triage_candidates,
    triage_discovery,
)


def _candidate(unit_id, entity_key, reason_shown="flagged", digest=None,
              protected=False, safe=False):
    return {
        "unit_id": unit_id,
        "entity_key": entity_key,
        "reason_shown": reason_shown,
        "source_snapshot_digest": digest if digest is not None else f"snap-{unit_id}",
        "protected_status": protected,
        "is_safe": safe,
    }


# ===========================================================================
# 0. No inbox vocabulary / import hygiene (read-only, generic)
# ===========================================================================

class TestReadOnlyAndVocabularyHygiene(unittest.TestCase):

    def test_module_source_carries_no_inbox_vocabulary(self):
        import external_write.triage as triage_mod
        src = Path(triage_mod.__file__).read_text(encoding="utf-8").lower()
        for banned in ("sender", "promo", "newsletter", "inbox", "unread", "gmail"):
            self.assertNotIn(banned, src,
                             f"triage.py must be generic -- found {banned!r} in source")

    def test_module_imports_no_adapter_or_credential_surface(self):
        import ast
        import external_write.triage as triage_mod
        tree = ast.parse(Path(triage_mod.__file__).read_text(encoding="utf-8"))
        banned_roots = {"adapters", "adapter_registry", "run_operation",
                        "requests", "urllib", "googleapiclient", "gspread"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], banned_roots)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn(node.module.split(".")[0], banned_roots)


# ===========================================================================
# 1. Grouping + deduped discovery (generic entity_key)
# ===========================================================================

class TestGroupingAndDedup(unittest.TestCase):

    def test_discovery_is_one_row_per_entity_key_never_n_rows_per_unit(self):
        candidates = [
            _candidate("u1", "key-A", safe=True),
            _candidate("u2", "key-A", safe=True),
            _candidate("u3", "key-A", safe=True),
            _candidate("u4", "key-B", safe=True),
        ]
        discovery = triage_discovery(candidates)
        self.assertEqual(len(discovery), 2)
        keys = {row["entity_key"] for row in discovery}
        self.assertEqual(keys, {"key-A", "key-B"})
        by_key = {row["entity_key"]: row for row in discovery}
        self.assertEqual(by_key["key-A"]["unit_count"], 3)
        self.assertEqual(by_key["key-B"]["unit_count"], 1)

    def test_per_candidate_output_preserves_one_row_per_unit(self):
        # triage_candidates (the OTHER altitude) is per-unit, not deduped --
        # both outputs coexist deliberately.
        candidates = [_candidate("u1", "key-A", safe=True), _candidate("u2", "key-A", safe=True)]
        rows = triage_candidates(candidates)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["unit_id"] for r in rows}, {"u1", "u2"})

    def test_malformed_candidate_is_dropped_not_guessed_into_a_bucket(self):
        candidates = [
            _candidate("u1", "key-A", safe=True),
            {"unit_id": "u2"},  # missing entity_key / reason_shown / digest
            "not-a-dict",
            None,
        ]
        rows = triage_candidates(candidates)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["unit_id"], "u1")

    def test_output_shape_matches_reviewed_set_v2_fields(self):
        rows = triage_candidates([_candidate("u1", "key-A", reason_shown="r", safe=True)])
        self.assertEqual(
            set(rows[0].keys()),
            {"unit_id", "entity_key", "reason_shown", "category",
             "protected_status", "source_snapshot_digest"})


# ===========================================================================
# 2. Classification vocabulary — divergent rosters (anti-overfit)
# ===========================================================================

class TestClassificationDivergentRosters(unittest.TestCase):

    def test_all_safe_roster_classifies_uniformly_safe(self):
        candidates = [_candidate(f"u{i}", "key-A", safe=True) for i in range(5)]
        discovery = triage_discovery(candidates)
        self.assertEqual(discovery[0]["category"], CATEGORY_UNIFORMLY_SAFE)
        rows = triage_candidates(candidates)
        self.assertTrue(all(r["category"] == CATEGORY_UNIFORMLY_SAFE for r in rows))

    def test_all_review_roster_classifies_requires_review(self):
        # Nothing marked safe, nothing protected -- ambiguous, needs a human look.
        candidates = [_candidate(f"u{i}", "key-A", reason_shown="unclear", safe=False)
                     for i in range(4)]
        discovery = triage_discovery(candidates)
        self.assertEqual(discovery[0]["category"], CATEGORY_REQUIRES_REVIEW)
        self.assertEqual(discovery[0]["reason_shown"], "unclear")

    def test_mixed_roster_classifies_contains_exceptions_and_itemizes_them(self):
        candidates = [
            _candidate("u1", "key-A", reason_shown="fine", safe=True),
            _candidate("u2", "key-A", reason_shown="fine", safe=True),
            _candidate("u3", "key-A", reason_shown="looks off", safe=False),
        ]
        discovery = triage_discovery(candidates)
        row = discovery[0]
        self.assertEqual(row["category"], CATEGORY_CONTAINS_EXCEPTIONS)
        self.assertEqual(row["exceptions"], [{"unit_id": "u3", "reason_shown": "looks off"}])

    def test_uniformly_safe_and_requires_review_show_no_top_level_reason_or_exceptions_mismatch(self):
        safe_row = triage_discovery(
            [_candidate("u1", "key-A", reason_shown="fine", safe=True)])[0]
        self.assertEqual(safe_row["reason_shown"], "")
        self.assertEqual(safe_row["exceptions"], [])


# ===========================================================================
# 3. Bucketing is a safety surface
# ===========================================================================

class TestBucketingSafetySurface(unittest.TestCase):

    def test_protected_unit_never_lands_in_uniformly_safe(self):
        # Even sharing an entity_key with otherwise-safe items, a protected
        # member must force the WHOLE group to `protected`, never
        # `uniformly_safe`.
        candidates = [
            _candidate("u1", "key-A", safe=True),
            _candidate("u2", "key-A", safe=True),
            _candidate("u3", "key-A", reason_shown="do not touch", protected=True),
        ]
        discovery = triage_discovery(candidates)
        self.assertEqual(discovery[0]["category"], CATEGORY_PROTECTED)
        rows = triage_candidates(candidates)
        for r in rows:
            self.assertNotEqual(r["category"], CATEGORY_UNIFORMLY_SAFE)
            self.assertEqual(r["category"], CATEGORY_PROTECTED)

    def test_protected_check_wins_over_all_safe_even_when_only_member(self):
        candidates = [_candidate("u1", "key-A", reason_shown="never", protected=True, safe=True)]
        discovery = triage_discovery(candidates)
        self.assertEqual(discovery[0]["category"], CATEGORY_PROTECTED)
        self.assertEqual(discovery[0]["reason_shown"], "never")

    def test_no_row_across_any_roster_ever_marks_a_protected_unit_safe(self):
        # A property-style sweep: across many synthetic rosters, no candidate
        # with protected_status=True is ever emitted with category
        # uniformly_safe.
        import random
        rng = random.Random(42)
        for trial in range(30):
            candidates = []
            for i in range(rng.randint(1, 8)):
                key = f"key-{i % 3}"
                candidates.append(_candidate(
                    f"u{trial}-{i}", key,
                    protected=rng.random() < 0.3,
                    safe=rng.random() < 0.5))
            rows = triage_candidates(candidates)
            for r in rows:
                if r["protected_status"]:
                    self.assertNotEqual(r["category"], CATEGORY_UNIFORMLY_SAFE)


# ===========================================================================
# 4. Anti-overfit: a non-Gmail candidate set (sheet-row cleanup)
# ===========================================================================

class TestNonGmailSheetRowCleanup(unittest.TestCase):
    """entity_key here is a spreadsheet KEY-COLUMN value (e.g. a SKU), never
    a sender/mailbox concept -- proves the primitive is genuinely generic."""

    def _row(self, unit_id, sku, reason, safe=False, protected=False):
        return _candidate(unit_id, entity_key=sku, reason_shown=reason,
                          digest=f"rowsnap-{unit_id}", safe=safe, protected=protected)

    def test_sheet_rows_grouped_by_sku_key_column(self):
        candidates = [
            self._row("row-1", "SKU-100", "duplicate row", safe=True),
            self._row("row-2", "SKU-100", "duplicate row", safe=True),
            self._row("row-3", "SKU-200", "stale price", safe=False),
        ]
        discovery = triage_discovery(candidates)
        self.assertEqual(len(discovery), 2)
        by_key = {row["entity_key"]: row for row in discovery}
        self.assertEqual(by_key["SKU-100"]["category"], CATEGORY_UNIFORMLY_SAFE)
        self.assertEqual(by_key["SKU-100"]["unit_count"], 2)
        self.assertEqual(by_key["SKU-200"]["category"], CATEGORY_REQUIRES_REVIEW)

    def test_sheet_row_marked_protected_is_never_uniformly_safe(self):
        candidates = [
            self._row("row-1", "SKU-900", "locked master record", safe=True, protected=True),
        ]
        rows = triage_candidates(candidates)
        self.assertEqual(rows[0]["category"], CATEGORY_PROTECTED)


if __name__ == "__main__":
    unittest.main()
