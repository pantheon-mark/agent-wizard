"""The upgrade impact notice must describe each affected file HONESTLY for what
that file actually is.

Three defects observed together in one real notice, all covered here:

1. STATE-BLIND. Seven affected files rendered a byte-identical sentence,
   including four test modules each told that "its ability to make changes
   outside your project has been switched off until it is rebuilt" and that "it
   will be rebuilt through the same reviewed process used for any new
   capability". Three of the seven really did need rebuilding; four did not; and
   one of the three could not be fixed by a rebuild at all.
2. DISPLAY-LEVEL NAME COLLISION. ``agents/inbox/runner.py`` and
   ``agents/upkeep/runner.py`` both rendered as the same bold ``runner``, with
   the distinguishing path only in parentheses.
3. HARDCODED WORKED EXAMPLE. The single "for example" the notice offered named
   one specific writer in EVERY project, and on the real project it named
   precisely the writer a rebuild cannot fix.

Assertion discipline (this is load-bearing). Defect 3's obvious test -- search
``upgrade_reconcile.py``'s SOURCE for the hardcoded example string -- passes
VACUOUSLY against the live defect, because the string is split across two source
lines and no substring search over source can ever match it. Every assertion
below is therefore made against the RENDERED notice text, which is the artifact
the operator actually reads. The one exception is the vocabulary pin, which
compares VALUES against the emitted classifier, never text.

Run: python3 -m unittest discover -s wizard/scripts/lib \
        -p test_impact_notice_kind_aware.py
"""

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import upgrade_reconcile  # noqa: E402
from upgrade_reconcile import (  # noqa: E402
    MechanismReport,
    ReconcileResult,
    reconcile_upgrade,
    render_impact_notice,
    render_reconcile_result,
)

_REAL_REPO = Path(__file__).resolve().parents[3]

# The three real shapes, kept as module constants so every test below argues
# about the same fixture the real project produced.
_BLOCKING = "blocking_live_enable"
_NEEDS_PERSON = "needs_person"
_NON_LIVE = "non_live"
_ACKNOWLEDGED = "acknowledged_risk"


def _mechanism(writer_relpath, writer_state, **overrides):
    """A ``MechanismReport`` in the shape the real reconcile produced for all
    seven affected files: no conventional wrapper was found, so nothing was
    entrypoint-paused and each one landed in ``broken_requires_migration``.

    NOTE the two DIFFERENT state vocabularies deliberately in play here.
    ``MechanismReport.state`` ("broken_requires_migration", "paused_live_write",
    ...) says what this upgrade DID to the file. ``writer_state``
    ("blocking_live_enable", "needs_person", "non_live", ...) is the emitted
    classifier's separate answer to what it would TAKE to clear the file. They
    are orthogonal and not interchangeable.
    """
    base = dict(
        mechanism_id=Path(writer_relpath).stem,
        writer_relpath=writer_relpath,
        violation_summaries=["sealed_kernel_import:1"],
        entrypoint_relpath=None,
        paused=False,
        state="broken_requires_migration",
        writer_state=writer_state,
    )
    base.update(overrides)
    return MechanismReport(**base)


def _bullet_for(text, writer_relpath):
    """Just the one operator-facing bullet block describing ``writer_relpath``
    -- its own header line plus every indented sub-line under it, and nothing
    belonging to any other file. Asserting per-file is the whole point: the
    defect was that seven files shared one sentence, so a whole-document
    substring assertion cannot tell a fixed notice from a broken one."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines)
                 if ln.startswith("- ") and writer_relpath in ln)
    block = [lines[start]]
    for ln in lines[start + 1:]:
        if ln.startswith("  "):
            block.append(ln)
        else:
            break
    return "\n".join(block)


class WriterStateVocabularyPinTests(unittest.TestCase):
    """The notice renderer branches on the emitted classifier's own state
    strings. It holds them as its own constants so the renderer stays a pure
    function of its arguments (no import, no filesystem), which means there are
    two copies of that vocabulary -- exactly the "two paths that must agree"
    shape. This pins them, in BOTH directions."""

    def _writer_state_class(self):
        ext_state = upgrade_reconcile._external_write_module(
            _REAL_REPO, "_ext_write_state")
        return ext_state.WriterState

    def test_each_constant_equals_the_emitted_classifiers_own_value(self):
        ws = self._writer_state_class()
        self.assertEqual(upgrade_reconcile._WRITER_STATE_BLOCKING_LIVE_ENABLE,
                         ws.BLOCKING_LIVE_ENABLE)
        self.assertEqual(upgrade_reconcile._WRITER_STATE_NEEDS_PERSON, ws.NEEDS_PERSON)
        self.assertEqual(upgrade_reconcile._WRITER_STATE_NON_LIVE, ws.NON_LIVE)
        self.assertEqual(upgrade_reconcile._WRITER_STATE_ACKNOWLEDGED_RISK,
                         ws.ACKNOWLEDGED_RISK)
        self.assertEqual(upgrade_reconcile._WRITER_STATE_RESOLVED, ws.RESOLVED)

    def test_the_precedence_order_covers_every_state_that_exists(self):
        # END-STATE check, not an enumeration: a NEW state added to the emitted
        # classifier must not be able to land silently in the notice's
        # fall-through bucket without someone deciding what it should say.
        ws = self._writer_state_class()
        declared = {v for k, v in vars(ws).items()
                    if not k.startswith("_") and isinstance(v, str)}
        self.assertEqual(
            declared, set(upgrade_reconcile._WRITER_STATE_NOTICE_PRECEDENCE),
            "the notice's state precedence must cover exactly the states the "
            "emitted classifier can return -- no more, no fewer")


class TestFileIsNeverToldItWillBeRebuiltTests(unittest.TestCase):

    def test_a_test_file_is_not_told_its_writes_were_switched_off_or_rebuilt(self):
        text = render_impact_notice(
            [_mechanism("agents/inbox/test_inbox_bulk.py", _NON_LIVE)],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/inbox/test_inbox_bulk.py")
        self.assertNotIn("it will be rebuilt", bullet)
        self.assertNotIn("has been switched off until", bullet)
        self.assertNotIn("do not rely on it being blocked", bullet)
        self.assertNotIn("The fix has been queued", bullet)

    def test_a_test_file_is_told_plainly_that_it_is_a_test_needing_no_action(self):
        text = render_impact_notice(
            [_mechanism("agents/inbox/test_inbox_bulk.py", _NON_LIVE)],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/inbox/test_inbox_bulk.py")
        self.assertIn("test file", bullet.lower())
        self.assertIn("no action is needed", bullet.lower())
        self.assertIn("outside this project", bullet.lower())

    def test_a_test_file_is_not_described_as_changing_information_outside(self):
        # The header line itself was part of the defect: a test module was told
        # it "changes information outside the project directly".
        text = render_impact_notice(
            [_mechanism("agents/inbox/test_inbox_bulk.py", _NON_LIVE)],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/inbox/test_inbox_bulk.py")
        self.assertNotIn("this changes information outside the project directly", bullet)

    def test_an_all_test_file_notice_does_not_tell_the_operator_to_fix_anything(self):
        text = render_impact_notice(
            [_mechanism("agents/inbox/test_inbox_bulk.py", _NON_LIVE),
             _mechanism("agents/inbox/test_inbox_runner.py", _NON_LIVE)],
            from_version="v0.21.0", to_version="v0.22.0")
        self.assertNotIn("To fix this, just tell your assistant", text)
        self.assertIn("needs anything from you", text.lower())


class NeedsPersonIsNotOfferedARebuildTests(unittest.TestCase):

    def test_a_needs_person_writer_is_told_it_needs_a_person(self):
        text = render_impact_notice(
            [_mechanism("agents/upkeep/runner.py", _NEEDS_PERSON)],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/upkeep/runner.py")
        self.assertIn("needs a person", bullet.lower())
        self.assertIn("cannot be fixed automatically", bullet.lower())

    def test_a_needs_person_writer_is_never_promised_a_rebuild(self):
        text = render_impact_notice(
            [_mechanism("agents/upkeep/runner.py", _NEEDS_PERSON)],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/upkeep/runner.py")
        self.assertNotIn("it will be rebuilt", bullet)
        self.assertNotIn("until it is rebuilt", bullet)
        self.assertNotIn("same reviewed process used for any new capability", bullet)

    def test_a_paused_needs_person_writer_is_not_promised_a_rebuild_either(self):
        # The entrypoint-paused shape reaches its wording through a DIFFERENT
        # branch (_pause_notice_lines), which also carried rebuild phrasing.
        text = render_impact_notice(
            [_mechanism("agents/upkeep/runner.py", _NEEDS_PERSON,
                        paused=True, state="entrypoint_paused",
                        entrypoint_relpath="agents/upkeep/run_runner.sh",
                        carries_read_outputs=True,
                        entangled_read_outputs=["digest", "alert"])],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/upkeep/runner.py")
        self.assertNotIn("rebuilt", bullet)
        self.assertIn("needs a person", bullet.lower())


class BlockingWriterKeepsItsAccurateWordingTests(unittest.TestCase):

    def test_a_blocking_writer_still_gets_the_switched_off_pending_rebuild_wording(self):
        text = render_impact_notice(
            [_mechanism("agents/inbox/runner.py", _BLOCKING)],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/inbox/runner.py")
        self.assertIn("has been switched off until it is rebuilt", bullet)
        self.assertIn("it will be rebuilt through the same reviewed process", bullet)

    def test_an_unset_writer_state_falls_back_to_the_cautious_wording(self):
        # Fail-closed: if the classifier could not be consulted at all, the
        # notice must keep today's demand-action wording rather than quietly
        # reassuring the operator.
        text = render_impact_notice(
            [_mechanism("agents/inbox/runner.py", "")],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/inbox/runner.py")
        self.assertIn("has been switched off until it is rebuilt", bullet)
        self.assertNotIn("no action is needed", bullet.lower())

    def test_an_unrecognised_writer_state_also_falls_back_to_cautious_wording(self):
        text = render_impact_notice(
            [_mechanism("agents/inbox/runner.py", "some_state_invented_later")],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/inbox/runner.py")
        self.assertIn("has been switched off until it is rebuilt", bullet)
        self.assertNotIn("no action is needed", bullet.lower())
        self.assertNotIn("some_state_invented_later", text)

    def test_an_acknowledged_writer_is_not_told_it_will_be_rebuilt(self):
        # The operator has recorded a decision to LEAVE this one as it is. Any
        # sentence promising it comes back when rebuilt promises a rebuild they
        # have already declined.
        text = render_impact_notice(
            [_mechanism("agents/upkeep/runner.py", _ACKNOWLEDGED)],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/upkeep/runner.py")
        self.assertNotIn("rebuilt", bullet)
        self.assertIn("already looked at this one", bullet.lower())

    def test_the_acknowledged_bullet_reconciles_its_two_true_facts(self):
        # ESTABLISHED BY EXECUTION: an acknowledgement does NOT restore the live
        # external-write path (the runtime gate refuses identically before and
        # after); what it does is drop the writer out of the blocking set, so it
        # stops holding back live-enable. Both facts are true, so the bullet must
        # not leave them adjacent reading like a contradiction -- it has to say
        # out loud that the decision did not switch anything back on.
        text = render_impact_notice(
            [_mechanism("agents/upkeep/runner.py", _ACKNOWLEDGED,
                        paused_op_kinds=["acme.widget.delete"])],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/upkeep/runner.py")
        self.assertIn("did not switch anything back on", bullet)
        self.assertIn("no longer holding up the rest of your system", bullet)
        self.assertIn(
            "changes things outside this project stays switched off", bullet)

    def test_the_acknowledged_bullet_does_not_claim_a_block_that_does_not_exist(self):
        # The mirror case: no gated runner and no runtime block on its changes.
        # The line above has already told the operator plainly NOT to rely on it
        # being blocked, so claiming here that it "stays switched off" would
        # contradict the notice's own caveat two sentences earlier.
        text = render_impact_notice(
            [_mechanism("agents/upkeep/runner.py", _ACKNOWLEDGED)],
            from_version="v0.21.0", to_version="v0.22.0")
        bullet = _bullet_for(text, "agents/upkeep/runner.py")
        self.assertIn("do not rely on it being blocked", bullet)
        self.assertNotIn("stays switched off", bullet)
        self.assertIn("did not switch anything back on", bullet)


class DisplayNameCollisionTests(unittest.TestCase):

    def test_two_files_sharing_a_filename_are_distinguishable(self):
        text = render_impact_notice(
            [_mechanism("agents/inbox/runner.py", _BLOCKING),
             _mechanism("agents/upkeep/runner.py", _NEEDS_PERSON)],
            from_version="v0.21.0", to_version="v0.22.0")
        self.assertIn("agents/inbox/runner.py", text)
        self.assertIn("agents/upkeep/runner.py", text)
        self.assertNotIn("**runner**", text)

    def test_the_bold_display_name_is_the_full_path(self):
        text = render_impact_notice(
            [_mechanism("agents/inbox/runner.py", _BLOCKING)],
            from_version="v0.21.0", to_version="v0.22.0")
        self.assertIn("- **agents/inbox/runner.py**", text)

    def test_the_two_same_named_files_do_not_share_one_sentence(self):
        # The literal defect: byte-identical text under both. With one blocking
        # and one needing a person, their bullets must differ.
        text = render_impact_notice(
            [_mechanism("agents/inbox/runner.py", _BLOCKING),
             _mechanism("agents/upkeep/runner.py", _NEEDS_PERSON)],
            from_version="v0.21.0", to_version="v0.22.0")
        inbox = _bullet_for(text, "agents/inbox/runner.py")
        upkeep = _bullet_for(text, "agents/upkeep/runner.py")
        self.assertNotEqual(
            inbox.replace("agents/inbox/", ""), upkeep.replace("agents/upkeep/", ""),
            "two files in different states must not render the same sentence")


class WorkedExampleIsDerivedNotHardcodedTests(unittest.TestCase):

    def test_the_example_names_a_writer_the_advice_actually_fits(self):
        text = render_impact_notice(
            [_mechanism("agents/upkeep/runner.py", _NEEDS_PERSON),
             _mechanism("agents/inbox/runner.py", _BLOCKING),
             _mechanism("agents/inbox/test_inbox_bulk.py", _NON_LIVE)],
            from_version="v0.21.0", to_version="v0.22.0")
        example = next(ln for ln in text.splitlines() if "for example" in ln)
        self.assertIn("agents/inbox/runner.py", example)
        self.assertNotIn("agents/upkeep/runner.py", example)
        self.assertNotIn("test_inbox_bulk", example)

    def test_the_example_is_omitted_entirely_when_no_writer_it_fits_exists(self):
        text = render_impact_notice(
            [_mechanism("agents/upkeep/runner.py", _NEEDS_PERSON),
             _mechanism("agents/inbox/test_inbox_bulk.py", _NON_LIVE)],
            from_version="v0.21.0", to_version="v0.22.0")
        self.assertNotIn("for example", text)
        # ... but the operator is not left without a route.
        self.assertIn("needs a person", text.lower())

    def test_no_writer_is_named_in_the_rendered_notice_unless_it_is_present(self):
        # The hardcoded example named "the upkeep writer" in EVERY project,
        # including projects with no such file. Asserted against the RENDERED
        # text: the equivalent source-level substring search is vacuous,
        # because the hardcoded string was split across two source lines.
        text = render_impact_notice(
            [_mechanism("agents/inbox/runner.py", _BLOCKING)],
            from_version="v0.21.0", to_version="v0.22.0")
        self.assertNotIn("upkeep", text.lower())

    def test_the_needs_person_route_appears_in_what_happens_next(self):
        text = render_impact_notice(
            [_mechanism("agents/inbox/runner.py", _BLOCKING),
             _mechanism("agents/upkeep/runner.py", _NEEDS_PERSON)],
            from_version="v0.21.0", to_version="v0.22.0")
        next_section = text.split("## What happens next", 1)[1]
        self.assertIn("needs a person", next_section.lower())


class NoticeStaysNonTechnicalTests(unittest.TestCase):

    def test_no_state_identifiers_or_internal_field_names_leak(self):
        text = render_impact_notice(
            [_mechanism("agents/inbox/runner.py", _BLOCKING),
             _mechanism("agents/upkeep/runner.py", _NEEDS_PERSON),
             _mechanism("agents/inbox/test_inbox_bulk.py", _NON_LIVE),
             _mechanism("agents/capabilities/acme_capability.py", _BLOCKING,
                        state="paused_live_write", paused_op_kinds=["acme.widget.delete"])],
            from_version="v0.21.0", to_version="v0.22.0")
        for token in ("non_live", "needs_person", "blocking_live_enable",
                      "acknowledged_risk", "writer_state", "WriterState",
                      "broken_requires_migration", "paused_live_write",
                      "mechanism_id", "op_kind", "sealed_kernel_import",
                      "acme.widget.delete", "Traceback", "AST"):
            self.assertNotIn(token, text, f"internal token {token!r} leaked to the operator")


class ReconcileWiresTheClassifierInTests(unittest.TestCase):
    """The renderer being kind-aware is worth nothing if nothing ever supplies
    the kind. This drives the REAL ``reconcile_upgrade`` entrypoint over a
    project carrying all three shapes and reads the notice it actually wrote to
    disk."""

    _BLOCKING_RUNNER = (
        "from external_write.run_envelope import mint_run_envelope, new_bulk_run_id\n"
        "def run_batches(batches):\n"
        "    for b in batches:\n"
        "        mint_run_envelope(run_id=new_bulk_run_id('x'))\n"
    )
    # urllib is a forbidden import root, and no remediation of ours rewrites
    # it -- the real shape behind the one writer a rebuild cannot fix.
    _NEEDS_PERSON_RUNNER = (
        "import urllib.request\n"
        "from external_write.run_envelope import mint_run_envelope, new_bulk_run_id\n"
        "def run_batches(batches):\n"
        "    for b in batches:\n"
        "        mint_run_envelope(run_id=new_bulk_run_id('x'))\n"
    )
    _TEST_MODULE = (
        "import unittest\n"
        "from external_write.run_envelope import mint_run_envelope\n"
        "\n"
        "\n"
        "class BulkTests(unittest.TestCase):\n"
        "    def test_mints(self):\n"
        "        self.assertIsNotNone(mint_run_envelope)\n"
    )

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        for rel, body in (
            ("agents/inbox/runner.py", self._BLOCKING_RUNNER),
            ("agents/upkeep/runner.py", self._NEEDS_PERSON_RUNNER),
            ("agents/inbox/test_inbox_bulk.py", self._TEST_MODULE),
        ):
            p = self.proj / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        self.result = reconcile_upgrade(
            self.proj, _REAL_REPO, from_version="v0.21.0", to_version="v0.22.0",
            upgrade_id="v0.21.0-to-v0.22.0")
        self.notice = Path(self.result.notice_path).read_text(encoding="utf-8")

    def test_the_reconcile_classified_all_three_shapes(self):
        by_relpath = {m.writer_relpath: m.writer_state for m in self.result.mechanisms}
        self.assertEqual(by_relpath.get("agents/inbox/runner.py"), _BLOCKING)
        self.assertEqual(by_relpath.get("agents/upkeep/runner.py"), _NEEDS_PERSON)
        self.assertEqual(by_relpath.get("agents/inbox/test_inbox_bulk.py"), _NON_LIVE)

    def test_the_notice_on_disk_is_kind_aware_per_file(self):
        test_bullet = _bullet_for(self.notice, "agents/inbox/test_inbox_bulk.py")
        self.assertIn("test file", test_bullet.lower())
        self.assertNotIn("it will be rebuilt", test_bullet)

        person_bullet = _bullet_for(self.notice, "agents/upkeep/runner.py")
        self.assertIn("needs a person", person_bullet.lower())
        self.assertNotIn("it will be rebuilt", person_bullet)

        blocking_bullet = _bullet_for(self.notice, "agents/inbox/runner.py")
        self.assertIn("it will be rebuilt", blocking_bullet)

    def test_the_notice_on_disk_derives_its_example_from_a_real_fitting_writer(self):
        example = next(ln for ln in self.notice.splitlines() if "for example" in ln)
        self.assertIn("agents/inbox/runner.py", example)
        self.assertNotIn("agents/upkeep/runner.py", example)

    def test_the_notice_on_disk_distinguishes_the_two_runner_files(self):
        self.assertNotIn("**runner**", self.notice)
        self.assertIn("- **agents/inbox/runner.py**", self.notice)
        self.assertIn("- **agents/upkeep/runner.py**", self.notice)

    def test_the_queue_the_classifier_read_really_carried_all_three(self):
        # Guards the ordering the wiring depends on: the migration queue must
        # already be written when the notice is rendered, or the classifier
        # would see nothing and every file would silently fall back.
        queue = json.loads(
            (self.proj / upgrade_reconcile.MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        relpaths = {e.get("writer_relpath") for e in queue if isinstance(e, dict)}
        self.assertEqual(
            relpaths,
            {"agents/inbox/runner.py", "agents/upkeep/runner.py",
             "agents/inbox/test_inbox_bulk.py"})

    def test_the_cli_summary_is_kind_aware_and_collision_free(self):
        out = render_reconcile_result(self.result)
        self.assertIn("agents/inbox/runner.py", out)
        self.assertIn("agents/upkeep/runner.py", out)
        self.assertIn("agents/inbox/test_inbox_bulk.py", out)
        summary_lines = {
            ln.split(":", 1)[0].strip(): ln.split(":", 1)[1].strip()
            for ln in out.splitlines() if ln.startswith("  - ") and ":" in ln
        }
        self.assertNotIn(
            "queued for rebuild",
            summary_lines.get("- agents/inbox/test_inbox_bulk.py", ""))


def _cli_status_for(out, writer_relpath):
    """The one status clause the CLI summary printed for ``writer_relpath``."""
    line = next(ln for ln in out.splitlines()
                if ln.strip().startswith(f"- {writer_relpath}:"))
    return line.split(":", 1)[1].strip()


class CliSummaryAgreesWithTheNoticeTests(unittest.TestCase):
    """The CLI summary prints at the terminal; the notice is a file the operator
    opens afterwards. Anything the CLI says that the notice contradicts is worse
    than either surface being wrong alone, because the operator sees both."""

    def _both(self, mechanisms):
        notice = render_impact_notice(
            mechanisms, from_version="v0.21.0", to_version="v0.22.0")
        cli = render_reconcile_result(ReconcileResult(
            operator_project_path="/tmp/x", from_version="v0.21.0",
            to_version="v0.22.0", mechanisms=mechanisms,
            notice_path="/tmp/x/.wizard/upgrade-review/u1/impact-notice.md"))
        return notice, cli

    def test_a_paused_test_module_is_not_told_nothing_was_switched_off(self):
        # The CLI said "nothing switched off" while the notice said the script
        # that runs it WAS switched off, about the same file, in the same run.
        m = _mechanism("agents/inbox/test_nightly_sync.py", _NON_LIVE,
                       paused=True, state="entrypoint_paused",
                       entrypoint_relpath="agents/inbox/run_test_nightly_sync.sh")
        notice, cli = self._both([m])
        status = _cli_status_for(cli, "agents/inbox/test_nightly_sync.py")
        self.assertNotIn("nothing switched off", status)
        self.assertIn("switched off as a precaution", status)
        self.assertIn("test file", status)
        self.assertIn("no action needed", status)
        # ... and the notice agrees, naming the same wrapper.
        bullet = _bullet_for(notice, "agents/inbox/test_nightly_sync.py")
        self.assertIn("agents/inbox/run_test_nightly_sync.sh", bullet)
        self.assertIn("switched off as", bullet)

    def test_an_unpaused_test_module_still_says_nothing_was_switched_off(self):
        # Guard the conditional the other way -- the common case must keep the
        # plainer, and true, wording.
        m = _mechanism("agents/inbox/test_inbox_bulk.py", _NON_LIVE)
        _notice, cli = self._both([m])
        status = _cli_status_for(cli, "agents/inbox/test_inbox_bulk.py")
        self.assertIn("nothing switched off, no action needed", status)
        self.assertNotIn("precaution", status)

    def test_kind_composes_with_pause_rather_than_swallowing_it(self):
        # An entrypoint-paused writer that needs a person: the operator must keep
        # BOTH signals. Losing "paused" loses the fact that a whole scheduled job
        # went dark -- which the notice for the same file does tell them.
        m = _mechanism("agents/cron/estate_upkeep.py", _NEEDS_PERSON,
                       paused=True, state="entrypoint_paused",
                       entrypoint_relpath="agents/cron/run_estate_upkeep.sh",
                       carries_read_outputs=True,
                       entangled_read_outputs=["digest", "alert", "backup"])
        notice, cli = self._both([m])
        status = _cli_status_for(cli, "agents/cron/estate_upkeep.py")
        self.assertIn("paused", status)
        self.assertIn("needs a person to look at it", status)
        self.assertNotIn("queued for rebuild", status)
        bullet = _bullet_for(notice, "agents/cron/estate_upkeep.py")
        self.assertIn("paused too", bullet.lower())
        self.assertIn("needs a person", bullet.lower())

    def test_a_paused_live_write_writer_keeps_its_mechanical_clause(self):
        m = _mechanism("agents/capabilities/acme_capability.py", _NEEDS_PERSON,
                       state="paused_live_write",
                       paused_op_kinds=["acme.widget.delete"])
        _notice, cli = self._both([m])
        status = _cli_status_for(cli, "agents/capabilities/acme_capability.py")
        self.assertIn("live-write blocked pending migration", status)
        self.assertIn("needs a person to look at it", status)

    def test_the_mechanical_clause_no_longer_welds_in_the_rebuild_route(self):
        # `broken_requires_migration` used to hardcode "queued for rebuild" INTO
        # its mechanical string, which is what made it impossible to state the
        # mechanical fact without also promising a rebuild.
        # The trailing parenthetical is the no-runtime-block caveat, which
        # travels with the mechanical claim on BOTH surfaces -- see
        # ``test_the_no_runtime_block_caveat_reaches_the_cli_too``.
        person = _mechanism("agents/upkeep/runner.py", _NEEDS_PERSON)
        blocking = _mechanism("agents/inbox/runner.py", _BLOCKING)
        _notice, cli = self._both([person, blocking])
        self.assertEqual(
            _cli_status_for(cli, "agents/upkeep/runner.py"),
            "external writes switched off -- needs a person to look at it "
            "(a runtime block could not be automatically installed for it, so "
            "do not rely on it being blocked until it is fixed)")
        self.assertEqual(
            _cli_status_for(cli, "agents/inbox/runner.py"),
            "external writes switched off -- queued for rebuild "
            "(a runtime block could not be automatically installed for it, so "
            "do not rely on it being blocked until it is rebuilt)")

    def test_the_no_runtime_block_caveat_reaches_the_cli_too(self):
        # The notice said "do not rely on it being blocked until it is
        # rebuilt" while this surface -- the one the operator reads FIRST --
        # said "external writes switched off" flatly. Whether anything is
        # actually holding the writes off is the whole question, so the two
        # surfaces may not answer it differently.
        m = _mechanism("agents/inbox/runner.py", _BLOCKING)
        notice, cli = self._both([m])
        caveat = "do not rely on it being blocked until it is rebuilt"
        self.assertIn(caveat, _bullet_for(notice, "agents/inbox/runner.py"))
        self.assertIn(caveat, _cli_status_for(cli, "agents/inbox/runner.py"))

    def test_a_resolved_op_kind_carries_the_caveat_on_NEITHER_surface(self):
        # The inverse, so the caveat cannot become unconditional: when an
        # op_kind WAS resolved a runtime block really was installed, and
        # telling the operator not to rely on it would be false the other way.
        m = _mechanism("agents/inbox/runner.py", _BLOCKING,
                       paused_op_kinds=["inbox.message.send"])
        notice, cli = self._both([m])
        caveat = "do not rely on it being blocked"
        self.assertNotIn(caveat, _bullet_for(notice, "agents/inbox/runner.py"))
        self.assertNotIn(caveat, _cli_status_for(cli, "agents/inbox/runner.py"))

    def test_an_acknowledged_writer_keeps_its_mechanical_clause_too(self):
        m = _mechanism("agents/legacy/notifier.py", _ACKNOWLEDGED, paused=True,
                       state="entrypoint_paused",
                       entrypoint_relpath="agents/legacy/run_notifier.sh")
        _notice, cli = self._both([m])
        status = _cli_status_for(cli, "agents/legacy/notifier.py")
        self.assertIn("paused", status)
        self.assertIn("your own recorded decision", status)
        self.assertNotIn("queued for rebuild", status)

    def test_neither_surface_names_a_file_by_its_bare_filename(self):
        notice, cli = self._both([
            _mechanism("agents/inbox/runner.py", _BLOCKING),
            _mechanism("agents/upkeep/runner.py", _NEEDS_PERSON),
        ])
        for surface, label in ((notice, "notice"), (cli, "cli")):
            self.assertIn("agents/inbox/runner.py", surface, label)
            self.assertIn("agents/upkeep/runner.py", surface, label)
        self.assertNotIn("- runner:", cli)


class AcknowledgementIsReachableEndToEndTests(unittest.TestCase):
    """``acknowledged_risk`` is not reachable from the scanner alone, but it IS
    reachable through the emitted public acknowledgement API -- so the branch that
    renders it is a real operator path, not scaffolding, and is covered as one."""

    _NEEDS_PERSON_RUNNER = (
        "import urllib.request\n"
        "from external_write.run_envelope import mint_run_envelope, new_bulk_run_id\n"
        "def run_batches(batches):\n"
        "    for b in batches:\n"
        "        mint_run_envelope(run_id=new_bulk_run_id('x'))\n"
    )

    def test_reconcile_then_acknowledge_reclassifies_and_rewords(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            relpath = "agents/upkeep/runner.py"
            p = proj / relpath
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(self._NEEDS_PERSON_RUNNER, encoding="utf-8")

            first = reconcile_upgrade(
                proj, _REAL_REPO, from_version="v0.21.0", to_version="v0.22.0",
                upgrade_id="u1")
            self.assertEqual(first.mechanisms[0].writer_state, _NEEDS_PERSON)

            ack = upgrade_reconcile._external_write_module(
                _REAL_REPO, "writer_acknowledgement")
            ack.acknowledge_writer(
                str(proj), relpath,
                operator_confirmation="I accept the risk of leaving this as it is.")

            states = upgrade_reconcile._writer_states_by_relpath(proj, _REAL_REPO)
            self.assertEqual(states.get(relpath), _ACKNOWLEDGED)

            first.mechanisms[0].writer_state = states[relpath]
            text = render_impact_notice(
                first.mechanisms, from_version="v0.21.0", to_version="v0.22.0")
            bullet = _bullet_for(text, relpath)
            self.assertIn("did not switch anything back on", bullet)
            self.assertNotIn("needs a person", bullet.lower())
            self.assertNotIn("rebuilt", bullet)


class ClassifierFailureIsFailClosedTests(unittest.TestCase):

    def test_an_unavailable_classifier_yields_no_states_rather_than_raising(self):
        # A toolkit layout that cannot supply the classifier must not abort the
        # upgrade's notice -- it must degrade to today's cautious wording.
        with tempfile.TemporaryDirectory() as empty:
            states = upgrade_reconcile._writer_states_by_relpath(
                Path(empty), Path(empty))
        self.assertEqual(states, {})

    def test_a_project_with_no_queue_yields_no_states(self):
        with tempfile.TemporaryDirectory() as proj:
            states = upgrade_reconcile._writer_states_by_relpath(
                Path(proj), _REAL_REPO)
        self.assertEqual(states, {})

    def test_a_malformed_queue_does_not_abort_the_notice(self):
        with tempfile.TemporaryDirectory() as proj:
            q = Path(proj) / upgrade_reconcile.MIGRATION_QUEUE_REL
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_text("{not json at all", encoding="utf-8")
            states = upgrade_reconcile._writer_states_by_relpath(
                Path(proj), _REAL_REPO)
        self.assertEqual(states, {})

    def test_the_most_cautious_state_wins_a_same_file_conflict(self):
        # Two open entries naming one file must never let the reassuring state
        # talk the notice down out of the demanding one.
        order = upgrade_reconcile._WRITER_STATE_NOTICE_PRECEDENCE
        self.assertLess(order.index(_NEEDS_PERSON), order.index(_NON_LIVE))
        self.assertLess(order.index(_BLOCKING), order.index(_NON_LIVE))
        self.assertLess(order.index(_BLOCKING), order.index(_ACKNOWLEDGED))


if __name__ == "__main__":
    unittest.main()
