"""Tests for the upgrade impact-review + reconcile engine (Task 9).

Anti-overfit posture: the module-level unit tests build a small synthetic
operator-project tree (no real bundle/registry machinery needed — reconcile only
needs ``agents/cron`` / ``agents/scripts`` + the real Task-5 scanner) and use the
REAL repo's ``agents/lib/external_write`` as the scanner source (the same
"single-home canonical location" pattern ``test_external_write_scan.py`` uses).

The CLI-wiring test at the bottom proves ``wizard_upgrade.py``'s ``--apply`` path
actually invokes reconcile after a real ``apply_upgrade`` (reusing the existing
synthetic-build-repo fixture helpers from ``test_upgrade_apply.py``, with the real
``agents/lib/external_write`` package copied in so the scanner resolves).
"""

import contextlib
import io
import json
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upgrade_reconcile import (  # noqa: E402
    CAPABILITY_DESCRIPTOR_SET_REL,
    MIGRATION_QUEUE_REL,
    PAUSED_MECHANISMS_DIR_REL,
    MechanismReport,
    ReconcileResult,
    reconcile_upgrade,
    render_impact_notice,
    render_reconcile_result,
    resolve_paused_op_kinds,
    scan_operator_mechanisms,
    _write_paused_live_write_state,
)

_REAL_REPO = Path(__file__).resolve().parents[3]

_DIRECT_WRITER = '''"""Daily upkeep — writes a Status tidy directly to the sheet (no gate)."""
from googleapiclient.discovery import build


def apply_status_tidy(svc, sheet_id, title, fixes):
    body = {"valueInputOption": "RAW", "data": fixes}
    svc.spreadsheets().values().batchUpdate(spreadsheetId=sheet_id, body=body).execute()


def main():
    return 0


if __name__ == "__main__":
    main()
'''

_READ_ONLY_REPORT = '''"""Read-only reporting: builds a digest, never mutates anything."""

def build_digest(rows):
    return "\\n".join(str(r) for r in rows)


def main():
    return 0


if __name__ == "__main__":
    main()
'''

_CONFORMANT_WRITER = '''"""Conformant capability: routes writes through the sanctioned
run-envelope entrypoint (run_enveloped_operation), never raw run_operation (v0.12.0 S1)."""
from agents.lib.external_write.capability_api import run_enveloped_operation
from agents.lib.external_write.operations import Operation


def do_tidy_status(envelope):
    op = Operation(op_kind="sheets.status.tidy", params={})
    return run_enveloped_operation(envelope, op, None, None)


def main():
    return 0


if __name__ == "__main__":
    main()
'''

_WRAPPER_TEMPLATE = """#!/usr/bin/env bash
# Cron wrapper for {name}.
export PATH="/usr/bin:/bin:/usr/local/bin"
cd "$(dirname "$0")/../.." || exit 1
/usr/bin/python3 "agents/cron/{name}.py"
"""


def _write_project(tmp: Path, *, writer_body: str, writer_name: str = "estate_upkeep",
                   with_read_only: bool = True, with_wrapper: bool = True) -> Path:
    proj = tmp / f"operator_{writer_name}"
    cron = proj / "agents" / "cron"
    cron.mkdir(parents=True, exist_ok=True)
    (cron / f"{writer_name}.py").write_text(writer_body, encoding="utf-8")
    if with_wrapper:
        wrapper = cron / f"run_{writer_name}.sh"
        wrapper.write_text(_WRAPPER_TEMPLATE.format(name=writer_name), encoding="utf-8")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    if with_read_only:
        (cron / "estate_report.py").write_text(_READ_ONLY_REPORT, encoding="utf-8")
        report_wrapper = cron / "run_estate_report.sh"
        report_wrapper.write_text(_WRAPPER_TEMPLATE.format(name="estate_report"),
                                  encoding="utf-8")
        report_wrapper.chmod(report_wrapper.stat().st_mode | stat.S_IEXEC)
    (proj / ".wizard").mkdir(parents=True, exist_ok=True)
    return proj


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)


class DetectTests(_Base):
    def test_direct_writer_is_detected(self):
        proj = _write_project(self.tmp, writer_body=_DIRECT_WRITER)
        by_relpath = scan_operator_mechanisms(proj, _REAL_REPO)
        self.assertIn("agents/cron/estate_upkeep.py", by_relpath)
        kinds = {v.kind for v in by_relpath["agents/cron/estate_upkeep.py"]}
        self.assertIn("direct_api_call", kinds)
        # The read-only report is untouched — no violations for it.
        self.assertNotIn("agents/cron/estate_report.py", by_relpath)

    def test_conformant_writer_triggers_no_detection(self):
        proj = _write_project(self.tmp, writer_body=_CONFORMANT_WRITER)
        by_relpath = scan_operator_mechanisms(proj, _REAL_REPO)
        self.assertEqual(by_relpath, {})

    def test_emitted_gate_machinery_itself_is_never_scanned(self):
        # agents/lib/external_write is not in OPERATOR_CODE_DIRS -- even if it were
        # physically present under the operator project, scan_operator_mechanisms
        # never looks there.
        proj = _write_project(self.tmp, writer_body=_DIRECT_WRITER)
        lib_dir = proj / "agents" / "lib" / "external_write"
        lib_dir.mkdir(parents=True, exist_ok=True)
        (lib_dir / "adapters.py").write_text(
            "from googleapiclient.discovery import build\n", encoding="utf-8")
        by_relpath = scan_operator_mechanisms(proj, _REAL_REPO)
        self.assertNotIn("agents/lib/external_write/adapters.py", by_relpath)

    def test_scan_scope_covers_capabilities_dir_derived_from_emitter(self):
        # anti-drift: the scanned set must CONTAIN the emitter's real output dir
        import capability_code_scaffold as ccs
        from upgrade_reconcile import OPERATOR_CODE_DIRS
        self.assertIn(ccs.DEFAULT_CAPABILITIES_REL.as_posix(), OPERATOR_CODE_DIRS)

    def test_retired_surface_capability_detected(self):
        proj = self.tmp
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)
        (capdir / "inbox_management_capability.py").write_text(
            "from external_write.capability_api import build_read_facade, run_operation\n"
            "def go():\n    return run_operation(None, None)\n", encoding="utf-8")
        by_relpath = scan_operator_mechanisms(proj, _REAL_REPO)
        self.assertIn("agents/capabilities/inbox_management_capability.py", by_relpath)


class ReconcileEndToEndTests(_Base):
    def test_capabilities_broken_requires_migration_two_locations(self):
        # F-55 B1: a retired-surface capability under agents/capabilities/ has no
        # run_<stem>.sh wrapper and is not orchestrator-scheduled, so the existing
        # entrypoint-level safe-pause does not structurally apply to it. It is
        # import-broken and scanner-red -- it cannot run -- so it must classify as
        # broken_requires_migration, not manual_review, and the notice must never
        # claim it "keeps running exactly as before". Two distinct capability ids
        # (anti-overfit) prove this isn't keyed on a single hardcoded id.
        proj = Path(self._tmpdir.name)
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)
        for cid in ("inbox_management_capability", "estate_upkeep_capability"):
            (capdir / f"{cid}.py").write_text(
                "from external_write.capability_api import run_operation\n"
                "def go():\n    return run_operation(None, None)\n", encoding="utf-8")
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.11.0", to_version="0.13.1")
        states = {m.mechanism_id: m.state for m in result.mechanisms}
        self.assertEqual(states["inbox_management_capability"], "broken_requires_migration")
        self.assertEqual(states["estate_upkeep_capability"], "broken_requires_migration")
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text())
        self.assertEqual({e["mechanism_id"] for e in queue},
                          {"inbox_management_capability", "estate_upkeep_capability"})
        notice = (proj / result.notice_path).read_text() if result.notice_path else ""
        self.assertNotIn("keeps running exactly as before", notice)

    def test_direct_writer_paused_read_only_untouched_notice_and_queue_written(self):
        proj = _write_project(self.tmp, writer_body=_DIRECT_WRITER)
        writer_path = proj / "agents" / "cron" / "estate_upkeep.py"
        original_writer_bytes = writer_path.read_text(encoding="utf-8")
        report_wrapper = proj / "agents" / "cron" / "run_estate_report.sh"
        original_report_wrapper = report_wrapper.read_text(encoding="utf-8")

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.10.2", to_version="v0.11.0",
            upgrade_id="up-20260711-01",
        )

        self.assertIsInstance(result, ReconcileResult)
        self.assertTrue(result.any_affected)
        self.assertTrue(result.any_paused)
        self.assertEqual(len(result.mechanisms), 1)
        m = result.mechanisms[0]
        self.assertEqual(m.mechanism_id, "estate_upkeep")
        self.assertEqual(m.writer_relpath, "agents/cron/estate_upkeep.py")
        self.assertEqual(m.entrypoint_relpath, "agents/cron/run_estate_upkeep.sh")
        self.assertTrue(m.paused)

        # 1. The flagged Python file is NEVER touched (no surgical rewrite).
        self.assertEqual(writer_path.read_text(encoding="utf-8"), original_writer_bytes)

        # 2. The mutating entrypoint is gated + still executable.
        wrapper_path = proj / "agents" / "cron" / "run_estate_upkeep.sh"
        wrapper_text = wrapper_path.read_text(encoding="utf-8")
        self.assertIn("paused pending migration", wrapper_text)
        self.assertTrue(wrapper_text.startswith("#!/usr/bin/env bash\n"))
        self.assertTrue(wrapper_path.stat().st_mode & stat.S_IEXEC)

        # 3. A pause marker + state record exist.
        marker = proj / PAUSED_MECHANISMS_DIR_REL / "estate_upkeep.pause"
        state = proj / PAUSED_MECHANISMS_DIR_REL / "estate_upkeep.json"
        self.assertTrue(marker.exists())
        state_data = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(state_data["mechanism_id"], "estate_upkeep")
        self.assertTrue(state_data["credentials_preserved"])
        self.assertEqual(state_data["from_version"], "v0.10.2")
        self.assertEqual(state_data["to_version"], "v0.11.0")

        # 4. The read-only entrypoint + its wrapper are completely untouched.
        self.assertEqual(report_wrapper.read_text(encoding="utf-8"), original_report_wrapper)
        self.assertNotIn("paused pending migration", original_report_wrapper)

        # 5. Plain-language notice written, no jargon like "AST" or "op_kind".
        self.assertIsNotNone(result.notice_path)
        notice_text = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertIn("estate_upkeep", notice_text)
        self.assertIn("paused", notice_text.lower())
        for jargon in ("AST", "op_kind", "run_operation(", "bypass scanner"):
            self.assertNotIn(jargon, notice_text)

        # F-43: entanglement with estate_upkeep's OWN read outputs is unverified
        # here (no naming-convention companion exists) -- deny-by-default means
        # NO continuity promise, even though a wholly separate, unflagged
        # mechanism (estate_report.py) happens to sit alongside it untouched.
        self.assertIsNone(m.carries_read_outputs)
        self.assertIsNone(m.separate_readonly_entrypoint)
        self.assertNotIn("keeps running exactly as before", notice_text)
        self.assertIn("not been confirmed", notice_text.lower())

        # 6. Migration handed to the enhancement flow via the durable queue file.
        self.assertIsNotNone(result.migration_queue_path)
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["mechanism_id"], "estate_upkeep")
        self.assertEqual(queue[0]["status"], "pending")

    def test_conformant_system_triggers_no_pause(self):
        proj = _write_project(self.tmp, writer_body=_CONFORMANT_WRITER)
        wrapper_path = proj / "agents" / "cron" / "run_estate_upkeep.sh"
        original_wrapper = wrapper_path.read_text(encoding="utf-8")

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.10.2", to_version="v0.11.0",
        )

        self.assertFalse(result.any_affected)
        self.assertFalse(result.any_paused)
        self.assertIsNone(result.notice_path)
        self.assertIsNone(result.migration_queue_path)
        self.assertEqual(wrapper_path.read_text(encoding="utf-8"), original_wrapper)
        self.assertFalse((proj / PAUSED_MECHANISMS_DIR_REL).exists())
        self.assertFalse((proj / MIGRATION_QUEUE_REL).exists())

    def test_no_conventional_entrypoint_reports_unpaused_but_still_detected(self):
        proj = _write_project(self.tmp, writer_body=_DIRECT_WRITER, with_wrapper=False)
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.10.2", to_version="v0.11.0",
        )
        self.assertTrue(result.any_affected)
        self.assertFalse(result.any_paused)
        m = result.mechanisms[0]
        self.assertIsNone(m.entrypoint_relpath)
        self.assertFalse(m.paused)
        # Still queued for migration even though it couldn't be auto-paused.
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual(queue[0]["entrypoint_relpath"], None)

    def test_idempotent_rerun_does_not_double_guard_or_duplicate_queue_entry(self):
        proj = _write_project(self.tmp, writer_body=_DIRECT_WRITER)
        reconcile_upgrade(proj, _REAL_REPO, from_version="v0.10.2", to_version="v0.11.0")
        first_wrapper = (proj / "agents" / "cron" / "run_estate_upkeep.sh").read_text(
            encoding="utf-8")
        reconcile_upgrade(proj, _REAL_REPO, from_version="v0.10.2", to_version="v0.11.0")
        second_wrapper = (proj / "agents" / "cron" / "run_estate_upkeep.sh").read_text(
            encoding="utf-8")
        self.assertEqual(first_wrapper, second_wrapper)
        self.assertEqual(first_wrapper.count("paused pending migration"), 1)
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual(len(queue), 1)

    def test_entangled_read_and_write_in_one_file_still_pauses_the_whole_mechanism(self):
        # Disclosed bound: a mechanism that entangles read + write in one script
        # cannot be cleanly split, so the whole shared entrypoint is paused rather
        # than leaving the write path live (paused-and-safe beats running-ungated).
        entangled = _DIRECT_WRITER + "\n\ndef digest():\n    return 'read-only summary'\n"
        proj = _write_project(self.tmp, writer_body=entangled, with_read_only=False)
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.10.2", to_version="v0.11.0",
        )
        self.assertTrue(result.any_paused)
        wrapper = (proj / "agents" / "cron" / "run_estate_upkeep.sh").read_text(
            encoding="utf-8")
        self.assertIn("paused pending migration", wrapper)

        # F-43 (the live estate dogfood defect): the SAME entrypoint that was just
        # paused is ALSO where the digest comes from -- this must be DETECTED as
        # entangled, and the notice must tell the truth about it: no unconditional
        # "keeps running exactly as before" claim, name what's dark (the digest),
        # and say it stays dark until rebuilt.
        m = result.mechanisms[0]
        self.assertTrue(m.carries_read_outputs)
        self.assertIsNone(m.separate_readonly_entrypoint)
        self.assertIn("digest", m.entangled_read_outputs)

        notice_text = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertNotIn("keeps running exactly as before", notice_text)
        self.assertIn("digest", notice_text.lower())
        self.assertIn("paused too", notice_text.lower())
        self.assertIn("rebuilt", notice_text.lower())

    def test_split_read_write_agent_verified_separate_gets_continuity_promise(self):
        # Anti-overfit shape 2: read and write are cleanly split into two
        # entrypoints for the SAME mechanism. The read-only companion is
        # positively verified -- it exists, carries no violations of its own,
        # and its own wrapper is neither missing nor already gated -- so (and
        # ONLY so) the notice may promise continuity for that specific part.
        proj = _write_project(self.tmp, writer_body=_DIRECT_WRITER, with_read_only=False)
        cron = proj / "agents" / "cron"
        (cron / "estate_upkeep_digest.py").write_text(_READ_ONLY_REPORT, encoding="utf-8")
        digest_wrapper = cron / "run_estate_upkeep_digest.sh"
        digest_wrapper.write_text(
            _WRAPPER_TEMPLATE.format(name="estate_upkeep_digest"), encoding="utf-8")
        digest_wrapper.chmod(digest_wrapper.stat().st_mode | stat.S_IEXEC)
        original_digest_wrapper = digest_wrapper.read_text(encoding="utf-8")

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.10.2", to_version="v0.11.0",
        )
        self.assertTrue(result.any_paused)
        m = result.mechanisms[0]
        self.assertEqual(m.mechanism_id, "estate_upkeep")
        self.assertFalse(m.carries_read_outputs)
        self.assertEqual(
            m.separate_readonly_entrypoint, "agents/cron/run_estate_upkeep_digest.sh")

        notice_text = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertIn("keeps running exactly as before", notice_text)
        self.assertIn("run_estate_upkeep_digest.sh", notice_text)

        # The verified companion wrapper was never touched or gated.
        self.assertEqual(digest_wrapper.read_text(encoding="utf-8"), original_digest_wrapper)
        self.assertNotIn("paused pending migration", original_digest_wrapper)

    def test_unverified_entanglement_fails_toward_paused_too_not_reassurance(self):
        # Deny-by-default honesty: no entangled keyword in the writer's own
        # file, and no positively verified separate companion either -- must
        # fail toward "paused too", never a false continuity promise.
        proj = _write_project(self.tmp, writer_body=_DIRECT_WRITER, with_read_only=False)
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.10.2", to_version="v0.11.0",
        )
        m = result.mechanisms[0]
        self.assertIsNone(m.carries_read_outputs)
        self.assertIsNone(m.separate_readonly_entrypoint)
        notice_text = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertNotIn("keeps running exactly as before", notice_text)
        self.assertIn("not been confirmed", notice_text.lower())

    def test_orchestrator_routed_shape_is_detected_and_notice_is_honest_about_it(self):
        # Anti-overfit shape 3: the mechanism is scheduled through the
        # Orchestrator (agent_emitter._orchestrator_invocation's convention --
        # a literal "agent=<id> cadence=..." trigger embedded in
        # cron_config.md), not a dedicated run_<stem>.sh wrapper. There is no
        # per-mechanism wrapper file to gate, so it cannot be auto-paused --
        # but the notice must still be honest about that (no continuity claim,
        # no generic "review at your leisure" framing) rather than silently
        # falling into the same bucket as "nothing scheduled at all."
        proj = self.tmp / "operator_orchestrator_routed"
        scripts = proj / "agents" / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "estate_upkeep.py").write_text(_DIRECT_WRITER, encoding="utf-8")
        cron = proj / "agents" / "cron"
        cron.mkdir(parents=True, exist_ok=True)
        (cron / "cron_config.md").write_text(
            "| estate_upkeep | Daily upkeep | Every day at 6 AM | `0 6 * * *` | "
            "claude --model opus --print \"Act as the Orchestrator "
            "(agents/prompts/orchestrator_prompt.md). Scheduled trigger: "
            "agent=estate_upkeep cadence=0 6 * * *. Read the work queue...\" | "
            "— | — |\n",
            encoding="utf-8",
        )
        (proj / ".wizard").mkdir(parents=True, exist_ok=True)

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.10.2", to_version="v0.11.0",
        )
        self.assertTrue(result.any_affected)
        self.assertFalse(result.any_paused)  # no wrapper file exists to gate
        m = result.mechanisms[0]
        self.assertEqual(m.mechanism_id, "estate_upkeep")
        self.assertIn("Orchestrator", m.pause_note)
        self.assertTrue(m.orchestrator_routed)

        notice_text = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertNotIn("keeps running exactly as before", notice_text)
        self.assertIn("assistant", notice_text.lower())


class RenderImpactNoticeTests(unittest.TestCase):
    """Direct unit coverage of the F-43 notice-honesty branching in
    ``render_impact_notice`` / ``_pause_notice_lines`` -- no filesystem or
    scanner involved, just the ``MechanismReport`` data model driving the text.
    """

    def _paused(self, **overrides):
        base = dict(
            mechanism_id="estate_upkeep",
            writer_relpath="agents/cron/estate_upkeep.py",
            violation_summaries=["direct_api_call:10"],
            entrypoint_relpath="agents/cron/run_estate_upkeep.sh",
            paused=True,
        )
        base.update(overrides)
        return MechanismReport(**base)

    def test_entangled_true_never_promises_continuity(self):
        m = self._paused(carries_read_outputs=True, entangled_read_outputs=["digest", "alert"])
        text = render_impact_notice([m], "v0.11.0", "v0.12.0")
        self.assertNotIn("keeps running exactly as before", text)
        self.assertIn("digest and alert", text)
        self.assertIn("paused too", text.lower())
        self.assertIn("rebuilt", text.lower())

    def test_paused_live_write_state_is_honest_and_jargon_free(self):
        # (F-55 B2) Distinct wording from both "paused" (entrypoint switched
        # off) and "broken_requires_migration" (cannot run at all): this state
        # keeps running, only its specific write(s) are blocked. No internal
        # identifiers (raw op_kind strings) leak into operator-facing text.
        m = self._paused(paused=False, entrypoint_relpath=None, state="paused_live_write",
                         paused_op_kinds=["acme.widget.delete"])
        text = render_impact_notice([m], "v0.13.0", "v0.13.1")
        self.assertIn("keeps running", text.lower())
        self.assertNotIn("keeps running exactly as before", text)
        self.assertNotIn("cannot run as-is", text.lower())
        self.assertNotIn("acme.widget.delete", text)
        for jargon in ("op_kind", "AST"):
            self.assertNotIn(jargon, text)

    def test_unknown_entanglement_never_promises_continuity(self):
        m = self._paused(carries_read_outputs=None, separate_readonly_entrypoint=None)
        text = render_impact_notice([m], "v0.11.0", "v0.12.0")
        self.assertNotIn("keeps running exactly as before", text)
        self.assertIn("not been confirmed", text.lower())

    def test_verified_separate_allows_continuity_promise(self):
        m = self._paused(
            carries_read_outputs=False,
            separate_readonly_entrypoint="agents/cron/run_estate_digest.sh",
        )
        text = render_impact_notice([m], "v0.11.0", "v0.12.0")
        self.assertIn("keeps running exactly as before", text)
        self.assertIn("agents/cron/run_estate_digest.sh", text)

    def test_separate_entrypoint_without_verified_false_does_not_promise(self):
        # carries_read_outputs left at its default (None/unknown) even though a
        # separate_readonly_entrypoint string is present -- must NOT be treated
        # as verified. Only carries_read_outputs is False AND a companion is
        # set together count as verified (belt-and-suspenders on the deny-by-
        # default rule -- guards against a future caller setting one field but
        # not the other).
        m = self._paused(
            carries_read_outputs=None,
            separate_readonly_entrypoint="agents/cron/run_estate_digest.sh",
        )
        text = render_impact_notice([m], "v0.11.0", "v0.12.0")
        self.assertNotIn("keeps running exactly as before", text)

    def test_not_paused_no_entrypoint_never_promises_continuity(self):
        m = self._paused(paused=False, entrypoint_relpath=None,
                          pause_note="no conventional schedule/entrypoint file was found")
        text = render_impact_notice([m], "v0.11.0", "v0.12.0")
        self.assertNotIn("keeps running exactly as before", text)
        self.assertIn("review it by hand", text.lower())

    def test_orchestrator_routed_flag_never_promises_continuity(self):
        m = self._paused(paused=False, entrypoint_relpath=None,
                          orchestrator_routed=True,
                          pause_note="scheduled through your assistant (the Orchestrator)")
        text = render_impact_notice([m], "v0.11.0", "v0.12.0")
        self.assertNotIn("keeps running exactly as before", text)
        self.assertIn("assistant", text.lower())
        self.assertNotIn("no automatic schedule was found", text.lower())

    def test_no_unconditional_continuity_line_remains_in_source(self):
        # Guard against regression at the source level -- the OLD unconditional
        # line must not exist anywhere in the module, under ANY MechanismReport
        # shape (paused, unpaused, orchestrator-routed, entangled, separate).
        import upgrade_reconcile
        src = Path(upgrade_reconcile.__file__).read_text(encoding="utf-8")
        self.assertNotIn(
            "Anything that only reads and reports to you was not touched", src)


class RenderReconcileResultTests(unittest.TestCase):
    def test_empty_when_nothing_affected(self):
        result = ReconcileResult(
            operator_project_path="/tmp/x", from_version="v1", to_version="v2")
        self.assertEqual(render_reconcile_result(result), "")

    def test_summarizes_paused_mechanism(self):
        result = ReconcileResult(
            operator_project_path="/tmp/x", from_version="v1", to_version="v2",
            mechanisms=[MechanismReport(
                mechanism_id="estate_upkeep", writer_relpath="agents/cron/estate_upkeep.py",
                violation_summaries=["direct_api_call:10"],
                entrypoint_relpath="agents/cron/run_estate_upkeep.sh", paused=True,
            )],
            notice_path="/tmp/x/.wizard/upgrade-review/u1/impact-notice.md",
        )
        out = render_reconcile_result(result)
        self.assertIn("estate_upkeep", out)
        self.assertIn("paused", out)
        self.assertIn("impact-notice.md", out)

    def test_paused_live_write_state_gets_honest_status_not_manual_review(self):
        # (review fix) A mechanism whose state is "paused_live_write" (not the
        # entrypoint-pause boolean `paused`) must NOT fall into the generic
        # "needs manual review (no schedule found)" bucket -- that mislabels
        # it. It gets its own short, accurate one-liner.
        result = ReconcileResult(
            operator_project_path="/tmp/x", from_version="v1", to_version="v2",
            mechanisms=[MechanismReport(
                mechanism_id="acme_widget_deleter",
                writer_relpath="agents/capabilities/acme_widget_deleter.py",
                violation_summaries=[], entrypoint_relpath=None, paused=False,
                state="paused_live_write",
            )],
            notice_path="/tmp/x/.wizard/upgrade-review/u1/impact-notice.md",
        )
        out = render_reconcile_result(result)
        self.assertIn("acme_widget_deleter", out)
        self.assertIn("paused (live-write blocked pending migration)", out)
        self.assertNotIn("no schedule found", out)


# ===================================================================================
# F-55 B2 — paused_op_kinds resolution + writer, exercised at the HELPER level
# directly (constructed inputs), not by forcing an unreachable reconcile_upgrade
# path -- see resolve_paused_op_kinds's own docstring for why the real
# scanner-driven reconcile_upgrade path can never reach scan_clean=True today.
# ===================================================================================

class ResolvePausedOpKindsTests(_Base):
    CAP_SOURCE = (
        '"""Widget-delete capability (CAPABILITY zone)."""\n'
        'from external_write.capability_api import build_read_facade, run_enveloped_operation\n'
        '\n'
        'OP_KIND = "acme.widget.delete"\n'
        'SURFACE = "acme_widgets"\n'
    )

    def _project_with_capability(self, *, capability_id="acme_widget_deleter",
                                 with_descriptor=True):
        proj = self.tmp / "operator_proj"
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)
        relpath = f"agents/capabilities/{capability_id}.py"
        (proj / relpath).write_text(self.CAP_SOURCE, encoding="utf-8")
        descriptor_set = []
        if with_descriptor:
            secdir = proj / "security"
            secdir.mkdir(parents=True, exist_ok=True)
            descriptor_set = [{
                "id": capability_id, "name": capability_id, "action_class": "delete",
                "risk_class": "irreversible_external", "recovery_profile_ref": None,
                "declared_test_target": "copy", "blast_radius_cap": 3,
                "accepted": False, "phase_id": "phase-1",
            }]
            (secdir / "capability_descriptors.json").write_text(
                json.dumps(descriptor_set), encoding="utf-8")
        return proj, relpath, descriptor_set

    def test_resolves_op_kind_from_writer_source_when_descriptor_exists(self):
        proj, relpath, ds = self._project_with_capability()
        kinds = resolve_paused_op_kinds(proj, "acme_widget_deleter", relpath, ds)
        self.assertEqual(kinds, ["acme.widget.delete"])

    def test_empty_when_no_matching_descriptor_entry(self):
        # Fail-closed/empty-safe: even though the writer's own source carries a
        # perfectly good OP_KIND literal, an UNDECLARED capability (no
        # descriptor entry with id == mechanism_id) resolves to [] -- never
        # guesses at an op_kind for something never declared.
        proj, relpath, _ = self._project_with_capability(with_descriptor=False)
        kinds = resolve_paused_op_kinds(proj, "acme_widget_deleter", relpath, [])
        self.assertEqual(kinds, [])

    def test_empty_when_writer_source_has_no_op_kind_literal(self):
        proj, relpath, ds = self._project_with_capability()
        (proj / relpath).write_text('"""No OP_KIND constant here."""\n', encoding="utf-8")
        kinds = resolve_paused_op_kinds(proj, "acme_widget_deleter", relpath, ds)
        self.assertEqual(kinds, [])

    def test_empty_when_writer_file_is_missing(self):
        proj, relpath, ds = self._project_with_capability()
        (proj / relpath).unlink()
        kinds = resolve_paused_op_kinds(proj, "acme_widget_deleter", relpath, ds)
        self.assertEqual(kinds, [])

    def test_descriptor_set_path_constant_matches_write_gate_convention(self):
        # Same value as write_gate.DESCRIPTOR_SET_PATH ("security/
        # capability_descriptors.json") -- duplicated (not imported) per this
        # module's own boundary discipline; pinned here so it can't drift.
        self.assertEqual(CAPABILITY_DESCRIPTOR_SET_REL, "security/capability_descriptors.json")


class WritePausedLiveWriteStateTests(_Base):
    def test_writer_produces_state_json_with_resolved_op_kind(self):
        # (f) unit test the paused_op_kinds WRITER directly -- constructed
        # inputs, no reconcile_upgrade call.
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        relpath = "agents/capabilities/acme_widget_deleter.py"
        (proj / "agents" / "capabilities").mkdir(parents=True)
        (proj / relpath).write_text("OP_KIND = 'acme.widget.delete'\n", encoding="utf-8")

        _write_paused_live_write_state(
            proj, "acme_widget_deleter", relpath, violations=[],
            from_version="v0.13.0", to_version="v0.13.1",
            paused_op_kinds=["acme.widget.delete"],
        )

        state_path = proj / PAUSED_MECHANISMS_DIR_REL / "acme_widget_deleter.json"
        marker_path = proj / PAUSED_MECHANISMS_DIR_REL / "acme_widget_deleter.pause"
        self.assertTrue(marker_path.exists())
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["mechanism_id"], "acme_widget_deleter")
        self.assertEqual(state["state"], "paused_live_write")
        self.assertEqual(state["paused_op_kinds"], ["acme.widget.delete"])
        self.assertIsNone(state["entrypoint_relpath"])
        self.assertTrue(state["credentials_preserved"])
        self.assertEqual(state["from_version"], "v0.13.0")
        self.assertEqual(state["to_version"], "v0.13.1")

        # This state file is exactly what write_gate.evaluate_write_gate's
        # runtime deny-branch globs for (*.json under PAUSED_MECHANISMS_DIR) --
        # cross-check it parses back with a non-empty paused_op_kinds union,
        # the same shape the runtime loader expects.
        self.assertIsInstance(state["paused_op_kinds"], list)
        self.assertTrue(all(isinstance(k, str) for k in state["paused_op_kinds"]))

    def test_idempotent_rerun_does_not_duplicate_marker(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        relpath = "agents/capabilities/acme_widget_deleter.py"
        (proj / "agents" / "capabilities").mkdir(parents=True)
        (proj / relpath).write_text("OP_KIND = 'acme.widget.delete'\n", encoding="utf-8")
        for _ in range(2):
            _write_paused_live_write_state(
                proj, "acme_widget_deleter", relpath, violations=[],
                from_version="v0.13.0", to_version="v0.13.1",
                paused_op_kinds=["acme.widget.delete"],
            )
        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        self.assertEqual(len(list(marker_dir.glob("acme_widget_deleter.*"))), 2)


class ReconcileUpgradePausedLiveWriteWiringTests(_Base):
    def test_real_scanner_path_never_reaches_paused_live_write(self):
        # Documents the honest scaffolding claim made in MechanismReport.state's
        # docstring and resolve_paused_op_kinds's: every relpath the REAL
        # scanner-driven reconcile_upgrade loop sees is scanner-red by
        # construction (that's how it entered by_relpath), so scan_clean is
        # always False and this capability-dir mechanism must still classify
        # as broken_requires_migration, exactly as before this task -- T1/T2
        # behavior is unchanged.
        proj = self.tmp
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)
        (capdir / "still_broken_capability.py").write_text(
            "from external_write.capability_api import run_operation\n"
            "def go():\n    return run_operation(None, None)\n", encoding="utf-8")
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")
        m = result.mechanisms[0]
        self.assertEqual(m.state, "broken_requires_migration")
        self.assertEqual(m.paused_op_kinds, [])


# ===================================================================================
# CLI-wiring test: prove `wizard upgrade --to V --apply` actually invokes reconcile
# after a real apply_upgrade. Reuses the synthetic-build-repo fixture helpers from
# test_upgrade_apply.py (same anti-overfit posture), with the real
# agents/lib/external_write package copied in so the scanner resolves.
# ===================================================================================

class CliWiringTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_cmd_apply_runs_reconcile_and_pauses_a_flagged_writer(self):
        from test_upgrade_apply import _write_build_repo, _build_operator_project
        _scripts_dir = str(Path(__file__).resolve().parents[1])  # wizard/scripts
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        import wizard_upgrade as cli  # noqa: E402

        build_root, registry_path = _write_build_repo(self.tmp)
        # Copy the REAL scanner package into the synthetic build repo so
        # reconcile's build_repo_root (the same one apply_upgrade uses) resolves
        # agents/lib/external_write -- mirrors how a real toolkit ships both the
        # bundles and the gate machinery together.
        real_lib = _REAL_REPO / "wizard" / "agents" / "lib" / "external_write"
        dest_lib = build_root / "wizard" / "agents" / "lib" / "external_write"
        dest_lib.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(real_lib, dest_lib)

        proj, manifest_path, _ = _build_operator_project(self.tmp, build_root)
        cron = proj / "agents" / "cron"
        cron.mkdir(parents=True, exist_ok=True)
        (cron / "estate_upkeep.py").write_text(_DIRECT_WRITER, encoding="utf-8")
        wrapper = cron / "run_estate_upkeep.sh"
        wrapper.write_text(_WRAPPER_TEMPLATE.format(name="estate_upkeep"), encoding="utf-8")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)

        rc = cli.main([
            "upgrade", "--to", "v0.5.0", "--apply",
            "--manifest-path", str(manifest_path),
            "--registry-path", str(registry_path),
        ])
        self.assertEqual(rc, 0)

        wrapper_text = wrapper.read_text(encoding="utf-8")
        self.assertIn("paused pending migration", wrapper_text)
        self.assertTrue((proj / PAUSED_MECHANISMS_DIR_REL / "estate_upkeep.pause").exists())
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual(queue[0]["mechanism_id"], "estate_upkeep")

    def test_cmd_reconcile_detects_retired_surface_on_already_upgraded_project(self):
        # F-55 D: the estate already upgraded across the retired-surface boundary
        # BEFORE this fix existed, so no `--apply` run will ever invoke reconcile
        # for them. `wizard reconcile` is the standalone recovery entry point --
        # it re-runs DETECT/NOTICE/SAFE-PAUSE/GUIDE-MIGRATE against the CURRENTLY
        # installed version (from_version == to_version == current manifest
        # version), with no apply attempted and no newer target required.
        from test_upgrade_apply import _write_build_repo, _build_operator_project
        _scripts_dir = str(Path(__file__).resolve().parents[1])  # wizard/scripts
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        import wizard_upgrade as cli  # noqa: E402

        build_root, registry_path = _write_build_repo(self.tmp)
        real_lib = _REAL_REPO / "wizard" / "agents" / "lib" / "external_write"
        dest_lib = build_root / "wizard" / "agents" / "lib" / "external_write"
        dest_lib.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(real_lib, dest_lib)

        proj, manifest_path, _ = _build_operator_project(self.tmp, build_root)

        # Simulate an estate that already upgraded to the current version
        # (foundation_bundle_version is at the current version; a retired-surface
        # capability was added under agents/capabilities/, which the pre-fix
        # apply-time reconcile never saw).
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["foundation_bundle_version"] = "v0.13.1"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")

        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True, exist_ok=True)
        (capdir / "inbox_management_capability.py").write_text(
            "from external_write.capability_api import run_operation\n"
            "def go():\n    return run_operation(None, None)\n", encoding="utf-8")

        rc = cli.main([
            "reconcile",
            "--manifest-path", str(manifest_path),
            "--registry-path", str(registry_path),
        ])
        self.assertEqual(rc, 0)

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual({e["mechanism_id"] for e in queue},
                          {"inbox_management_capability"})

    def test_reconcile_fallback_message_lists_all_operator_code_dirs(self):
        # F-55 review fix: the except-branch fallback message used to hardcode
        # "agents/cron and agents/scripts" -- a second, independent copy of the
        # scan scope that went blind to agents/capabilities/ exactly like the
        # pre-fix OPERATOR_CODE_DIRS did. Force the except branch and assert every
        # OPERATOR_CODE_DIRS entry is named in the operator-facing message, so this
        # can't silently re-drift from the single source of truth again.
        _scripts_dir = str(Path(__file__).resolve().parents[1])  # wizard/scripts
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        import wizard_upgrade as cli  # noqa: E402

        def _boom(*args, **kwargs):
            raise RuntimeError("synthetic reconcile failure")

        original = cli.reconcile_upgrade
        cli.reconcile_upgrade = _boom
        try:
            result = SimpleNamespace(from_version="v1", to_version="v2", upgrade_id="u1")
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                cli._run_reconcile_best_effort(self.tmp, self.tmp, result)
        finally:
            cli.reconcile_upgrade = original

        message = buf.getvalue()
        for code_dir in cli.OPERATOR_CODE_DIRS:
            self.assertIn(code_dir, message)


if __name__ == "__main__":
    unittest.main()
