"""Task 1 / Cut 1.6 (bundle v0.20.0) -- deterministic state classes for open
bespoke-writer migration entries.

WHY THIS EXISTS. the coarse safety gate's coarse, attribution-free gate WORKED (v0.19.0
ship-criterion #1 passed live) and is NOT being undone: safety still keys on the
PRESENCE of an unresolved violation, never on attributing it to an owner. What
the v0.19.0 real-operator validation found (F-VAL19-1 / F-VAL19-5) is that
*every* open entry blocking *everything* means one unrepairable writer bricks
acceptance for the whole project, permanently, with no operator-reachable exit.

This task refines WHICH entries enter the blocking set. ``open_bespoke_writer_
migrations`` is untouched (still the attribution-free superset); the new
``blocking_bespoke_writer_migrations`` is a FILTER over it.

THE DECIDABILITY MOVE (this is the load-bearing idea -- read before editing).
"Does a reachable remediation exist?" is undecidable in general: proving a
behaviour-preserving rewrite to scan-clean code exists is exactly the semantic
judgement the coarse gate exists to keep out. So we do not ask it. We ask a
question we CAN answer: **does OUR OWN deterministic remediator cover every
violation recorded on this entry?** That is decidable because we know what the
remediator does. It keys on the scanner's recorded violation RULE NAMES, which
the reconcile already persists on the entry.

  REMEDIABLE (the rebuild flow + Cut 1.6's kernel-runner injection fix these):
      adapter_module_import, adapter_registry_reference, sealed_kernel_import,
      raw_run_operation_reference, credential_provider_reference
  NOT REMEDIABLE BY OUR TOOLING (a person must decide):
      forbidden_import, introspection_escape_hatch, unparseable

VALIDATED AGAINST ALL 7 REAL ESTATE ENTRIES (2026-07-25, read-only):
  agents/inbox/runner.py .................. all remediable -> BLOCKING_LIVE_ENABLE
  agents/upkeep/runner.py ................. has forbidden_import -> NEEDS_PERSON
  4x agents/**/test_*.py .................. test modules -> NON_LIVE
  scripts/finish_estate_cleanup.py ........ all remediable -> BLOCKING_LIVE_ENABLE

DELIBERATE DEVIATION FROM THE CROSS-VENDOR ADVISOR OUTPUT -- DO NOT "SIMPLIFY"
THIS BACK. gpt-5.5's proposed state table listed ``needs_person`` as NON-blocking.
That silently re-opens F-VAL18-1: acceptance would go green around an unmigrated
LIVE writer with no human in the loop, which is the exact false-green the coarse safety gate
exists to prevent. Here NEEDS_PERSON REMAINS BLOCKING. Its only sanctioned exit
is an explicit, hash-bound operator acknowledgement (Task 3) -- a recorded human
decision, never a classifier's silent judgement.
``test_needs_person_without_acknowledgement_is_blocking`` is the guard.

Run:  python3 -m unittest discover -s wizard/agents/lib/external_write \\
          -p test_writer_state_classes.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

_EXTERNAL_WRITE_DIR = Path(__file__).resolve().parent
_AGENTS_LIB = _EXTERNAL_WRITE_DIR.parent  # agents/lib -- external_write is a package under here
if str(_AGENTS_LIB) not in sys.path:
    sys.path.insert(0, str(_AGENTS_LIB))

from external_write import _ext_write_state as ews  # noqa: E402

QUEUE_REL = "agents/handoffs/pending_migrations.json"


def _v(kind, path, line=1):
    """A recorded violation object in the reconcile's real on-disk shape."""
    return {"kind": kind, "line": line, "path": path}


def _entry(writer_relpath, kinds, status="pending", **extra):
    """A pending bespoke-writer queue entry in the reconcile's real shape."""
    e = {
        "mechanism_id": writer_relpath.replace("/", "_").replace(".py", "") if writer_relpath else None,
        "writer_relpath": writer_relpath,
        "status": status,
        "paused_content_sha256": "0" * 64,
        "violations": [_v(k, writer_relpath) for k in kinds],
    }
    e.update(extra)
    return e


class _Project:
    """A throwaway operator project on disk."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "agents" / "handoffs").mkdir(parents=True)

    def write_queue(self, entries):
        (self.root / QUEUE_REL).write_text(
            json.dumps(entries, indent=2), encoding="utf-8")

    def write_file(self, relpath, text):
        p = self.root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def close(self):
        self._tmp.cleanup()


_LIVE_WRITER_SRC = '''"""A bespoke bulk writer."""
from external_write.adapters_thing import build_read_only_client
'''

_TEST_MODULE_SRC = '''"""Tests for the write path."""
import unittest
from external_write.adapters_thing import ThingAdapter


class TestWritePath(unittest.TestCase):
    def test_apply(self):
        self.assertTrue(ThingAdapter)
'''


class StateClassifierTests(unittest.TestCase):

    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)

    # ---------------------------------------------------------------- BLOCKING

    def test_live_writer_with_only_remediable_violations_is_blocking(self):
        """agents/inbox/runner.py's real shape: every recorded violation is one
        our own remediator covers, so the honest answer is 'we can fix this' ->
        it blocks live-enable until we do."""
        self.p.write_file("agents/inbox/runner.py", _LIVE_WRITER_SRC)
        self.p.write_queue([_entry("agents/inbox/runner.py",
                                   ["adapter_module_import",
                                    "credential_provider_reference",
                                    "sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertEqual(state, ews.WriterState.BLOCKING_LIVE_ENABLE)
        self.assertEqual(len(ews.blocking_bespoke_writer_migrations(str(self.p.root))), 1)

    def test_non_test_script_outside_agents_with_remediable_violation_is_blocking(self):
        """scripts/finish_estate_cleanup.py's real shape -- not a test module,
        so 'lives outside agents/' must NOT buy it an exemption."""
        self.p.write_file("scripts/finish_estate_cleanup.py", _LIVE_WRITER_SRC)
        self.p.write_queue([_entry("scripts/finish_estate_cleanup.py",
                                   ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertEqual(state, ews.WriterState.BLOCKING_LIVE_ENABLE)

    # ------------------------------------------------------------ NEEDS_PERSON

    def test_forbidden_import_makes_it_needs_person(self):
        """agents/upkeep/runner.py's real shape (F-VAL19-1): a network client
        imported for the module's OWN delivery (ntfy/Graph), which no
        remediator of ours rewrites."""
        self.p.write_file("agents/upkeep/runner.py", _LIVE_WRITER_SRC)
        self.p.write_queue([_entry("agents/upkeep/runner.py",
                                   ["adapter_module_import",
                                    "credential_provider_reference",
                                    "forbidden_import",
                                    "sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertEqual(state, ews.WriterState.NEEDS_PERSON)

    def test_needs_person_without_acknowledgement_is_blocking(self):
        """THE GUARD (see module docstring). NEEDS_PERSON must stay in the
        blocking set. If this test ever fails, F-VAL18-1 has been re-opened:
        acceptance would go green around an unmigrated LIVE writer with no
        human in the loop."""
        self.p.write_file("agents/upkeep/runner.py", _LIVE_WRITER_SRC)
        self.p.write_queue([_entry("agents/upkeep/runner.py",
                                   ["forbidden_import", "sealed_kernel_import"])])
        blocking = ews.blocking_bespoke_writer_migrations(str(self.p.root))
        self.assertEqual(len(blocking), 1,
                         "NEEDS_PERSON must block until a human acknowledges it")

    # ----------------------------------------------------------------- NON_LIVE

    def test_unreferenced_test_module_is_non_live(self):
        """The 4 real estate test-file entries: violations intrinsic to testing
        the write path, on a module nothing in the running system invokes."""
        self.p.write_file("agents/inbox/test_inbox_runner.py", _TEST_MODULE_SRC)
        self.p.write_queue([_entry("agents/inbox/test_inbox_runner.py",
                                   ["adapter_module_import",
                                    "raw_run_operation_reference",
                                    "sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertEqual(state, ews.WriterState.NON_LIVE)
        self.assertEqual(ews.blocking_bespoke_writer_migrations(str(self.p.root)), [])

    def test_test_named_module_referenced_by_cron_is_not_non_live(self):
        """ANTI-OVERFIT. The rule is reachability + test structure, NOT the
        filename. A module named test_*.py that a declared invocation surface
        actually schedules is live, and must still block."""
        self.p.write_file("agents/inbox/test_inbox_runner.py", _TEST_MODULE_SRC)
        self.p.write_file("agents/cron/cron_config.md",
                          "| daily | python3 agents/inbox/test_inbox_runner.py |\n")
        self.p.write_queue([_entry("agents/inbox/test_inbox_runner.py",
                                   ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertNotEqual(state, ews.WriterState.NON_LIVE)
        self.assertEqual(len(ews.blocking_bespoke_writer_migrations(str(self.p.root))), 1)

    def test_test_named_module_without_test_structure_is_not_non_live(self):
        """ANTI-OVERFIT, second signal. A file called test_*.py that contains no
        test-framework structure is not a test module."""
        self.p.write_file("agents/inbox/test_inbox_runner.py", _LIVE_WRITER_SRC)
        self.p.write_queue([_entry("agents/inbox/test_inbox_runner.py",
                                   ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertNotEqual(state, ews.WriterState.NON_LIVE)

    def test_comment_mention_does_not_make_a_test_module_live(self):
        """REAL-DATA REGRESSION (estate, 2026-07-25). agents/inbox/runner.py
        contains only the COMMENT `# Header / From parsing (pure -- see
        test_inbox_runner.py)`. A comment is not an invocation. An earlier
        text-grep implementation of the reference check treated it as one and
        misclassified the test module as live -- the same infer-from-incidental-
        text defect class the typed-identity rule exists to close. Reference detection is
        AST-based for Python, so comments (absent from the AST) cannot
        disqualify, while string literals (how subprocess actually invokes)
        still can."""
        self.p.write_file("agents/inbox/test_inbox_runner.py", _TEST_MODULE_SRC)
        self.p.write_file(
            "agents/inbox/runner.py",
            '"""A writer."""\n# Header / From parsing (pure -- see test_inbox_runner.py)\n')
        self.p.write_queue([_entry("agents/inbox/test_inbox_runner.py",
                                   ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertEqual(state, ews.WriterState.NON_LIVE)

    def test_real_import_does_make_a_test_module_live(self):
        """The other side of the same rule: a genuine import IS a reference."""
        self.p.write_file("agents/inbox/test_inbox_runner.py", _TEST_MODULE_SRC)
        self.p.write_file("agents/inbox/runner.py",
                          '"""A writer."""\nimport test_inbox_runner\n')
        self.p.write_queue([_entry("agents/inbox/test_inbox_runner.py",
                                   ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertNotEqual(state, ews.WriterState.NON_LIVE)

    def test_subprocess_string_literal_does_make_a_test_module_live(self):
        """A string literal naming the relpath is how subprocess/cron actually
        invokes a module -- it must still count, unlike a comment."""
        self.p.write_file("agents/inbox/test_inbox_runner.py", _TEST_MODULE_SRC)
        self.p.write_file(
            "agents/inbox/runner.py",
            '"""A writer."""\nimport subprocess\n'
            'subprocess.run(["python3", "agents/inbox/test_inbox_runner.py"])\n')
        self.p.write_queue([_entry("agents/inbox/test_inbox_runner.py",
                                   ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertNotEqual(state, ews.WriterState.NON_LIVE)

    def test_unparseable_module_that_mentions_it_fails_closed(self):
        """A module that MENTIONS the writer but will not parse cannot be
        adjudicated -- fail CLOSED (disqualify non_live), never open."""
        self.p.write_file("agents/inbox/test_inbox_runner.py", _TEST_MODULE_SRC)
        self.p.write_file("agents/inbox/runner.py",
                          "def broken( :\n  test_inbox_runner\n")
        self.p.write_queue([_entry("agents/inbox/test_inbox_runner.py",
                                   ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertNotEqual(state, ews.WriterState.NON_LIVE)

    def test_unrelated_unparseable_module_does_not_disqualify(self):
        """REAL-DATA REGRESSION (estate, 2026-07-25). An unparseable file that
        does not mention this writer at all is irrelevant to it, and must not
        drag it into the blocking set. Reference detection therefore
        text-PRE-FILTERS (over-inclusive, cheap) and only AST-adjudicates the
        files that actually mention it. Without this, one unparseable file
        anywhere would brick every non_live classification -- reproducing, in
        miniature, the exact 'one bad file bricks the project' fault this cut
        exists to fix."""
        self.p.write_file("agents/inbox/test_inbox_runner.py", _TEST_MODULE_SRC)
        self.p.write_file("agents/other/unrelated.py", "def broken( :\n")
        self.p.write_queue([_entry("agents/inbox/test_inbox_runner.py",
                                   ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertEqual(state, ews.WriterState.NON_LIVE)

    def test_vendored_dependency_tree_is_not_an_invocation_surface(self):
        """REAL-DATA REGRESSION (estate, 2026-07-25). The estate's `.venv`
        contains third-party pycparser modules that are intentionally
        unparseable. A vendored dependency tree is not operator code and not an
        invocation surface -- it must be excluded from the scan entirely."""
        self.p.write_file("agents/inbox/test_inbox_runner.py", _TEST_MODULE_SRC)
        self.p.write_file(".venv/lib/python3.12/site-packages/pycparser/c_lexer.py",
                          "def broken( :\n  test_inbox_runner\n")
        self.p.write_queue([_entry("agents/inbox/test_inbox_runner.py",
                                   ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertEqual(state, ews.WriterState.NON_LIVE)

    def test_non_test_named_module_with_test_structure_is_not_non_live(self):
        """ANTI-OVERFIT, third signal. Test structure alone is not enough
        either -- all three signals must agree."""
        self.p.write_file("agents/inbox/runner.py", _TEST_MODULE_SRC)
        self.p.write_queue([_entry("agents/inbox/runner.py", ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertNotEqual(state, ews.WriterState.NON_LIVE)

    # -------------------------------------------------------------- FAIL-CLOSED

    def test_unclassifiable_entry_is_blocking(self):
        """Fail-closed: a writer that still EXISTS but records no violations
        cannot be proven remediable and cannot be proven non-live, so it
        blocks. (An ABSENT writer is a different case -- see below.)"""
        self.p.write_file("agents/odd/writer.py", _LIVE_WRITER_SRC)
        self.p.write_queue([_entry("agents/odd/writer.py", [])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertEqual(state, ews.WriterState.BLOCKING_LIVE_ENABLE)

    def test_absent_writer_still_blocks_because_the_reaper_owns_resolution(self):
        """The classifier must NOT re-derive "resolved". reap_resolved_writer_
        migrations is the single authority (its predicate is absent OR
        hash-changed-AND-scan-clean, and it REMOVES the entry). A second,
        weaker rule here would be two authorities over one fact -- the
        duplicated-inference class the typed-identity rule exists to close -- and would
        un-block an entry the reaper has not cleared. Fail closed instead; the
        reaper clears it via reconcile-on-read moments later."""
        self.p.write_queue([_entry("agents/gone/missing.py", ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertEqual(state, ews.WriterState.BLOCKING_LIVE_ENABLE)

    def test_inaccessible_writer_is_blocking_not_resolved(self):
        """os.stat-style distinction (memory: fail-closed fs checks must
        distinguish absent from inaccessible). A directory where a file is
        expected reads as present-but-unreadable -> cannot verify -> blocks."""
        (self.p.root / "agents" / "weird").mkdir(parents=True)
        (self.p.root / "agents" / "weird" / "writer.py").mkdir()
        self.p.write_queue([_entry("agents/weird/writer.py", ["sealed_kernel_import"])])
        state = ews.classify_bespoke_writer_entry(
            str(self.p.root), ews.open_bespoke_writer_migrations(str(self.p.root))[0])
        self.assertEqual(state, ews.WriterState.BLOCKING_LIVE_ENABLE)

    def test_unreadable_queue_still_raises(self):
        """The the coarse safety gate fail-closed contract is preserved: a read failure must
        never present as 'nothing blocking'."""
        (self.p.root / QUEUE_REL).write_text("{not json", encoding="utf-8")
        with self.assertRaises(ews.ExternalWriteStateReadError):
            ews.blocking_bespoke_writer_migrations(str(self.p.root))

    # ------------------------------------------------------------- INVARIANTS

    def test_blocking_is_always_a_subset_of_open(self):
        """The the coarse safety gate keystone stays intact: the blocking set is a FILTER over
        the attribution-free superset, never a different query."""
        self.p.write_file("agents/inbox/runner.py", _LIVE_WRITER_SRC)
        self.p.write_file("agents/inbox/test_inbox_runner.py", _TEST_MODULE_SRC)
        self.p.write_file("agents/upkeep/runner.py", _LIVE_WRITER_SRC)
        self.p.write_queue([
            _entry("agents/inbox/runner.py", ["sealed_kernel_import"]),
            _entry("agents/inbox/test_inbox_runner.py", ["sealed_kernel_import"]),
            _entry("agents/upkeep/runner.py", ["forbidden_import"]),
        ])
        root = str(self.p.root)
        open_paths = {e["writer_relpath"] for e in ews.open_bespoke_writer_migrations(root)}
        blocking_paths = {e["writer_relpath"] for e in ews.blocking_bespoke_writer_migrations(root)}
        self.assertTrue(blocking_paths <= open_paths)
        self.assertEqual(len(open_paths), 3)
        self.assertEqual(blocking_paths,
                         {"agents/inbox/runner.py", "agents/upkeep/runner.py"})

    def test_state_report_accounts_for_every_open_entry(self):
        """Nothing becomes invisible: every open entry appears in exactly one
        bucket of the report, so a non-blocking entry is still surfaced."""
        self.p.write_file("agents/inbox/runner.py", _LIVE_WRITER_SRC)
        self.p.write_file("agents/inbox/test_inbox_runner.py", _TEST_MODULE_SRC)
        self.p.write_file("agents/upkeep/runner.py", _LIVE_WRITER_SRC)
        self.p.write_queue([
            _entry("agents/inbox/runner.py", ["sealed_kernel_import"]),
            _entry("agents/inbox/test_inbox_runner.py", ["sealed_kernel_import"]),
            _entry("agents/upkeep/runner.py", ["forbidden_import"]),
        ])
        report = ews.bespoke_writer_state_report(str(self.p.root))
        counted = sum(len(v) for v in report.values())
        self.assertEqual(counted, 3)
        self.assertEqual(len(report[ews.WriterState.BLOCKING_LIVE_ENABLE]), 1)
        self.assertEqual(len(report[ews.WriterState.NEEDS_PERSON]), 1)
        self.assertEqual(len(report[ews.WriterState.NON_LIVE]), 1)


if __name__ == "__main__":
    unittest.main()


class ConsumerWiringTests(unittest.TestCase):
    """Task 2 / Cut 1.6 -- the three safety consumers block on the BLOCKING
    SUBSET, while still REPORTING every open entry.

    The distinction matters for a non-technical operator: a non-blocking entry
    must never become invisible just because it stopped blocking. Visibility is
    not gated on blocking."""

    def setUp(self):
        self.p = _Project()
        self.addCleanup(self.p.close)

    def _non_live_entry(self):
        self.p.write_file("agents/inbox/test_inbox_bulk.py", _TEST_MODULE_SRC)
        self.p.write_queue([_entry("agents/inbox/test_inbox_bulk.py",
                                   ["sealed_kernel_import"])])

    def _blocking_entry(self):
        self.p.write_file("agents/inbox/runner.py", _LIVE_WRITER_SRC)
        self.p.write_queue([_entry("agents/inbox/runner.py",
                                   ["sealed_kernel_import"])])

    # ------------------------------------------------------------ health view

    def test_health_does_not_block_on_a_non_live_entry(self):
        from external_write import capability_health as ch
        self._non_live_entry()
        status = ch.overall_status(str(self.p.root))
        self.assertFalse(status["open_external_write_bypass"]["blocking"])

    def test_health_still_reports_a_non_live_entry_and_withholds_the_all_clear(self):
        """Not blocking != invisible. `normal_status_allowed` stays False while
        ANY open entry exists in any non-resolved state, so the operator is
        still told about it -- it simply no longer bricks acceptance."""
        from external_write import capability_health as ch
        self._non_live_entry()
        status = ch.overall_status(str(self.p.root))
        self.assertFalse(status["normal_status_allowed"],
                         "an open non-live entry must still withhold the all-clear")
        self.assertIn("agents/inbox/test_inbox_bulk.py",
                      status["open_external_write_bypass"]["writer_relpaths"])
        states = status["open_external_write_bypass"]["writer_states"]
        self.assertEqual(states["agents/inbox/test_inbox_bulk.py"], ews.WriterState.NON_LIVE)

    def test_health_blocks_on_a_blocking_entry(self):
        from external_write import capability_health as ch
        self._blocking_entry()
        status = ch.overall_status(str(self.p.root))
        self.assertTrue(status["open_external_write_bypass"]["blocking"])
        self.assertFalse(status["normal_status_allowed"])

    def test_health_fails_closed_on_an_unreadable_queue(self):
        from external_write import capability_health as ch
        (self.p.root / QUEUE_REL).write_text("{not json", encoding="utf-8")
        status = ch.overall_status(str(self.p.root))
        self.assertTrue(status["open_external_write_bypass"]["blocking"])
        self.assertTrue(status["open_external_write_bypass"]["read_error"])
        self.assertFalse(status["normal_status_allowed"])
