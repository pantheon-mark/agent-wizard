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
import hashlib
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
        # (xvendor round-2, R2-1) Filenames use the REAL scaffold convention
        # (``<capability_id>_capability.py``) — mechanism_id must normalize
        # to the bare capability_id (see _capability_mechanism_id), NOT the
        # raw file stem.
        proj = Path(self._tmpdir.name)
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)
        for capability_id in ("inbox_management", "estate_upkeep"):
            (capdir / f"{capability_id}_capability.py").write_text(
                "from external_write.capability_api import run_operation\n"
                "def go():\n    return run_operation(None, None)\n", encoding="utf-8")
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.11.0", to_version="0.13.1")
        states = {m.mechanism_id: m.state for m in result.mechanisms}
        self.assertEqual(states["inbox_management"], "broken_requires_migration")
        self.assertEqual(states["estate_upkeep"], "broken_requires_migration")
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text())
        self.assertEqual({e["mechanism_id"] for e in queue},
                          {"inbox_management", "estate_upkeep"})
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

    def test_from_equals_to_version_uses_recheck_wording_not_upgrade_wording(self):
        # (review fix, F-55 D) `wizard reconcile` re-checks the CURRENTLY
        # installed version -- from_version == to_version by construction, no
        # upgrade happened. "upgraded from v0.13.1 to v0.13.1" would be
        # misleading; this must read as a safety re-check of the current
        # version instead.
        m = self._paused()
        text = render_impact_notice([m], "0.13.1", "0.13.1")
        self.assertNotIn("upgraded from", text.lower())
        self.assertIn("0.13.1", text)
        self.assertIn("checked", text.lower())

    def test_differing_versions_still_use_upgrade_wording(self):
        # Guard the conditional both ways: a real version change must keep the
        # existing upgrade-wording opener untouched.
        m = self._paused()
        text = render_impact_notice([m], "v0.11.0", "v0.12.0")
        self.assertIn("upgraded from v0.11.0 to v0.12.0", text)

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

    def test_stale_acceptance_only_revocation_still_prints_a_plain_language_note(self):
        # (Task B2b-fix, Important) A conformant-rebuild revocation that never touched
        # `mechanisms` at all (the scanner never flagged anything -- see
        # ConformantRebuildStalenessTests above) must NOT be a silent switch-off just
        # because `mechanisms` is empty.
        result = ReconcileResult(
            operator_project_path="/tmp/x", from_version="v1", to_version="v2",
            stale_acceptance_reset=["acme_widget_sync"],
        )
        out = render_reconcile_result(result)
        self.assertNotEqual(out, "", "a stale-acceptance-only revocation must not print nothing")
        self.assertIn("acme_widget_sync", out)
        self.assertNotIn("Traceback", out)
        self.assertNotIn("Exception", out)

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

    def test_broken_requires_migration_gets_honest_status_not_manual_review(self):
        # (review fix, F-55 D) A broken_requires_migration mechanism never had a
        # schedule to review by hand -- it is import-broken and the fix is
        # already auto-queued. It must NOT fall into the generic "needs manual
        # review (no schedule found)" bucket; it gets its own honest one-liner
        # matching the impact-notice's framing (nothing to review, fix queued).
        result = ReconcileResult(
            operator_project_path="/tmp/x", from_version="v1", to_version="v2",
            mechanisms=[MechanismReport(
                mechanism_id="inbox_management_capability",
                writer_relpath="agents/capabilities/inbox_management_capability.py",
                violation_summaries=[], entrypoint_relpath=None, paused=False,
                state="broken_requires_migration",
            )],
            notice_path="/tmp/x/.wizard/upgrade-review/u1/impact-notice.md",
        )
        out = render_reconcile_result(result)
        self.assertIn("inbox_management_capability", out)
        self.assertIn("queued for rebuild", out.lower())
        self.assertNotIn("no schedule found", out)
        # (xvendor round-2, R2-2) the CLI summary must not overclaim
        # importability ("cannot run as-is") -- it must match the honest,
        # already-fixed impact-notice wording instead.
        self.assertNotIn("cannot run as-is", out.lower())
        self.assertIn("switched off", out.lower())


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
# xvendor Finding-1 -- a scanner-red capability-dir writer must be RUNTIME-BLOCKED
# (a paused_op_kinds marker written) whenever its op_kind is resolvable, closing the
# safety gap where a PREVIOUSLY-ACCEPTED, scanner-red-but-importable capability was
# classified broken_requires_migration + migration-queued but NOT runtime-blocked
# (no marker was ever written for that classification pre-fix) -- so write_gate's
# accepted-descriptor branch still permitted its live writes. Also covers the honest
# reword of the broken_requires_migration notice branch (no more "cannot run as-is"
# overclaim).
# ===================================================================================

class ScannerRedCapabilityRuntimeBlockTests(_Base):
    CAP_SOURCE_WITH_OP_KIND = (
        '"""Widget-delete capability (scanner-red + OP_KIND literal, xvendor '
        'Finding-1 test fixture)."""\n'
        'from external_write.capability_api import run_operation\n'
        '\n'
        'OP_KIND = "acme.widget.delete"\n'
        '\n'
        'def go():\n'
        '    return run_operation(None, None)\n'
    )
    CAP_SOURCE_NO_OP_KIND = (
        '"""Widget-delete capability (scanner-red, NO OP_KIND literal, xvendor '
        'Finding-1 test fixture)."""\n'
        'from external_write.capability_api import run_operation\n'
        '\n'
        'def go():\n'
        '    return run_operation(None, None)\n'
    )

    def _project_with_scanner_red_capability(self, *, capability_id="acme_widget_deleter",
                                             with_op_kind=True):
        proj = self.tmp / "operator_proj"
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)
        relpath = f"agents/capabilities/{capability_id}.py"
        source = self.CAP_SOURCE_WITH_OP_KIND if with_op_kind else self.CAP_SOURCE_NO_OP_KIND
        (proj / relpath).write_text(source, encoding="utf-8")
        secdir = proj / "security"
        secdir.mkdir(parents=True, exist_ok=True)
        # accepted: True -- a PREVIOUSLY-ACCEPTED capability. Pre-fix, this is
        # exactly the shape write_gate's accepted-descriptor branch would
        # still permit a live write for, since no paused_op_kinds marker was
        # ever written for a broken_requires_migration classification.
        descriptor_set = [{
            "id": capability_id, "name": capability_id, "action_class": "delete",
            "risk_class": "irreversible_external", "recovery_profile_ref": None,
            "declared_test_target": "copy", "blast_radius_cap": 3,
            "accepted": True, "phase_id": "phase-1",
        }]
        (secdir / "capability_descriptors.json").write_text(
            json.dumps(descriptor_set), encoding="utf-8")
        return proj, relpath, descriptor_set

    def test_resolvable_op_kind_writes_marker_and_write_gate_refuses_even_when_accepted(self):
        proj, relpath, descriptor_set = self._project_with_scanner_red_capability()
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")
        m = result.mechanisms[0]
        self.assertEqual(m.mechanism_id, "acme_widget_deleter")
        # The STATE NAME is unchanged by this fix -- only whether a runtime
        # block got installed varies with op_kind resolvability.
        self.assertEqual(m.state, "broken_requires_migration")
        self.assertEqual(m.paused_op_kinds, ["acme.widget.delete"])

        marker_path = proj / PAUSED_MECHANISMS_DIR_REL / "acme_widget_deleter.json"
        self.assertTrue(marker_path.exists(), "expected a paused_op_kinds marker to be written")
        state = json.loads(marker_path.read_text(encoding="utf-8"))
        self.assertEqual(state["paused_op_kinds"], ["acme.widget.delete"])

        # THE SAFETY-GAP REGRESSION, end-to-end: the descriptor entry above
        # is accepted:true at risk_class irreversible_external -- pre-fix,
        # write_gate's covering-ACCEPTED-descriptor branch would PERMIT a
        # live write for this op_kind despite the capability being
        # scanner-red and migration-queued (no marker existed to refuse it).
        # The marker reconcile just wrote must refuse it regardless of the
        # accepted descriptor being present.
        #
        # Force a FRESH import of the real agents/lib/external_write package
        # from its canonical location: CliWiringTests (which runs earlier,
        # alphabetically, in this same test module/process) copies a
        # TEMPORARY external_write package into a build_root that gets
        # cleaned up in its own tearDown, and Python caches that under
        # sys.modules["external_write"] -- a stale reference whose __path__
        # points at an already-deleted directory. Purging any cached
        # external_write* modules and putting the real agents_lib first on
        # sys.path guarantees this import resolves to the REAL package,
        # regardless of what ran earlier in this process.
        agents_lib = _REAL_REPO / "wizard" / "agents" / "lib"
        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]
        sys.path.insert(0, str(agents_lib))
        from external_write.write_gate import (  # noqa: E402
            evaluate_write_gate, InvocationLedger, LIVE_TARGET,
        )
        from external_write.operations import Operation  # noqa: E402

        op = Operation(surface="acme_widget_deleter", object_id="obj:1", field="__record__",
                       new_value="<x>", op_kind="acme.widget.delete", batch_id="b1")
        decision = evaluate_write_gate(
            op, target=LIVE_TARGET, descriptor_set=descriptor_set,
            cap_ledger=InvocationLedger(),
            paused_root=str(proj / PAUSED_MECHANISMS_DIR_REL))
        self.assertFalse(
            decision.permitted,
            "write_gate must REFUSE this op_kind even with an accepted descriptor present")
        self.assertIn("paused", decision.refusal.detail["reason"])

    def test_notice_drops_cannot_run_as_is_and_states_switched_off_until_rebuilt(self):
        proj, relpath, _ = self._project_with_scanner_red_capability()
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")
        notice = (proj / result.notice_path).read_text() if result.notice_path else ""
        self.assertNotIn("cannot run as-is", notice)
        self.assertIn("switched off", notice)
        self.assertIn("until it is rebuilt", notice)

    def test_unresolvable_op_kind_writes_no_marker_and_says_could_not_auto_install(self):
        proj, relpath, _ = self._project_with_scanner_red_capability(
            capability_id="acme_widget_deleter_2", with_op_kind=False)
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")
        m = result.mechanisms[0]
        self.assertEqual(m.state, "broken_requires_migration")
        self.assertEqual(m.paused_op_kinds, [])

        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        self.assertFalse((marker_dir / f"{m.mechanism_id}.json").exists())
        self.assertFalse((marker_dir / f"{m.mechanism_id}.pause").exists())

        notice = (proj / result.notice_path).read_text() if result.notice_path else ""
        self.assertNotIn("cannot run as-is", notice)
        self.assertIn("could not be automatically installed", notice)


# ===================================================================================
# xvendor round-2, R2-1 -- the durable regression guard: the filename↔descriptor-id
# join must work for a REAL scaffolded capability, not the earlier overfit fixture
# (ScannerRedCapabilityRuntimeBlockTests above uses a bare "<id>.py" filename with NO
# "_capability" suffix -- exactly the shape that missed this bug, because it never
# forces the mechanism_id normalization this fix adds). This class uses the ACTUAL
# production filename convention capability_code_scaffold.py's capability_module_stem
# emits: "agents/capabilities/<capability_id>_capability.py", with a descriptor id ==
# the bare capability_id (no suffix) -- and proves BOTH that reconcile writes the
# correctly-normalized pause marker AND that write_gate actually refuses the op_kind
# at runtime even with an accepted descriptor present.
# ===================================================================================

class RealScaffoldFilenameMechanismIdJoinTests(_Base):
    CAP_SOURCE_WITH_OP_KIND = (
        '"""Widget-delete capability (REAL scaffold filename convention, xvendor '
        'round-2 R2-1 regression fixture)."""\n'
        'from external_write.capability_api import run_operation\n'
        '\n'
        'OP_KIND = "acme.widget.delete"\n'
        '\n'
        'def go():\n'
        '    return run_operation(None, None)\n'
    )

    def _project_with_real_scaffolded_capability(self, *, capability_id="acme_widget_deleter"):
        proj = self.tmp / "operator_proj"
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)
        # THE REAL convention: capability_code_scaffold.capability_module_stem
        # returns f"{capability_id}_capability" -- the file stem carries the
        # suffix; the descriptor id below does NOT.
        relpath = f"agents/capabilities/{capability_id}_capability.py"
        (proj / relpath).write_text(self.CAP_SOURCE_WITH_OP_KIND, encoding="utf-8")
        secdir = proj / "security"
        secdir.mkdir(parents=True, exist_ok=True)
        # accepted: True -- a previously-accepted real capability. Descriptor
        # id == capability_id, WITHOUT the "_capability" suffix -- exactly
        # what add-capability's own convention declares (descriptor id ==
        # capability_id == mechanism_id/re-declared id), and exactly what a
        # RAW (unnormalized) file-stem mechanism_id could never join against.
        descriptor_set = [{
            "id": capability_id, "name": capability_id, "action_class": "delete",
            "risk_class": "irreversible_external", "recovery_profile_ref": None,
            "declared_test_target": "copy", "blast_radius_cap": 3,
            "accepted": True, "phase_id": "phase-1",
        }]
        (secdir / "capability_descriptors.json").write_text(
            json.dumps(descriptor_set), encoding="utf-8")
        return proj, relpath, descriptor_set

    def test_real_filename_joins_descriptor_and_writes_normalized_marker(self):
        capability_id = "acme_widget_deleter"
        proj, relpath, descriptor_set = self._project_with_real_scaffolded_capability(
            capability_id=capability_id)
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")
        m = result.mechanisms[0]

        # The mechanism_id must normalize to the BARE capability_id -- equal
        # to the descriptor's own "id" -- not the raw "<id>_capability" stem.
        self.assertEqual(m.mechanism_id, capability_id)
        self.assertEqual(m.state, "broken_requires_migration")
        self.assertEqual(m.paused_op_kinds, ["acme.widget.delete"])

        # The pause marker filename is keyed on the NORMALIZED mechanism_id
        # (proves the join actually resolved an op_kind and wrote a marker --
        # pre-fix, this join silently failed and no marker was ever written
        # for a real "<id>_capability.py" filename).
        marker_path = proj / PAUSED_MECHANISMS_DIR_REL / f"{capability_id}.json"
        self.assertTrue(
            marker_path.exists(),
            "expected a paused_op_kinds marker keyed on the bare capability_id "
            "-- the filename<->descriptor-id join must succeed for a REAL "
            "scaffolded '<id>_capability.py' capability")
        state = json.loads(marker_path.read_text(encoding="utf-8"))
        self.assertEqual(state["mechanism_id"], capability_id)
        self.assertEqual(state["paused_op_kinds"], ["acme.widget.delete"])

        # The migration-queue entry also carries the normalized id -- so the
        # operator re-declaring this SAME capability_id through add-capability
        # auto-closes the SAME queue entry (the migration-queue<->add-capability
        # coherence this fix must preserve).
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual({e["mechanism_id"] for e in queue}, {capability_id})

    def test_write_gate_refuses_the_resolved_op_kind_even_with_accepted_descriptor(self):
        capability_id = "acme_widget_deleter"
        proj, relpath, descriptor_set = self._project_with_real_scaffolded_capability(
            capability_id=capability_id)
        reconcile_upgrade(proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")

        # Force a FRESH import of the real agents/lib/external_write package
        # (see ScannerRedCapabilityRuntimeBlockTests's own test for why this
        # purge-and-reinsert is needed -- an earlier test in this same process
        # may have cached a stale external_write module under a deleted
        # temporary build_root).
        agents_lib = _REAL_REPO / "wizard" / "agents" / "lib"
        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]
        sys.path.insert(0, str(agents_lib))
        from external_write.write_gate import (  # noqa: E402
            evaluate_write_gate, InvocationLedger, LIVE_TARGET,
        )
        from external_write.operations import Operation  # noqa: E402

        op = Operation(surface=capability_id, object_id="obj:1", field="__record__",
                       new_value="<x>", op_kind="acme.widget.delete", batch_id="b1")
        decision = evaluate_write_gate(
            op, target=LIVE_TARGET, descriptor_set=descriptor_set,
            cap_ledger=InvocationLedger(),
            paused_root=str(proj / PAUSED_MECHANISMS_DIR_REL))
        self.assertFalse(
            decision.permitted,
            "write_gate must REFUSE this op_kind for a REAL '<id>_capability.py' "
            "scaffolded capability even with an accepted descriptor present -- "
            "this is exactly the safety gap R2-1 closes: pre-fix, the marker "
            "was never written at all for this real filename shape, so this "
            "assertion would have failed (decision.permitted would be True).")
        self.assertIn("paused", decision.refusal.detail["reason"])


# ===================================================================================
# Phase 3 Cut 1, Task B2 -- rebuild/migration forces accepted:false until re-trial
# (never inherit prior acceptance; F-62 fix). A scanner-red capability-dir writer
# that was PREVIOUSLY accepted:true must have that flipped back to accepted:false
# by reconcile_upgrade itself, and lifecycle_state.reconcile_state must then be
# called so the marker/migration materialized views are coherent with the
# now-unaccepted state (B1's own merge behavior backfills canonical_id onto the
# marker this same pass already wrote via _write_paused_live_write_state).
#
# Uses the REAL scaffold filename convention (`<capability_id>_capability.py`) --
# the same shape RealScaffoldFilenameMechanismIdJoinTests above uses -- and TWO
# distinct capability_ids in the descriptor set: one scanner-red (must be reset)
# and one conformant/untouched (must NOT be touched).
# ===================================================================================

class RebuildForcesAcceptedFalseTests(_Base):
    CAP_SOURCE_WITH_OP_KIND = (
        '"""Widget-delete capability (scanner-red, rebuilt-onto-a-changed-gate '
        'fixture, Task B2)."""\n'
        'from external_write.capability_api import run_operation\n'
        '\n'
        'OP_KIND = "acme.widget.delete"\n'
        '\n'
        'def go():\n'
        '    return run_operation(None, None)\n'
    )

    def setUp(self):
        super().setUp()
        # Purge any cached external_write* modules so this test always resolves
        # against the REAL agents/lib/external_write package, never a stale
        # reference left over from another test's temporary build_root (see the
        # identical purge in ScannerRedCapabilityRuntimeBlockTests /
        # RealScaffoldFilenameMechanismIdJoinTests above).
        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]

    def _write_conformant_acceptance_record(self, proj, capability_id, phase_id):
        """(Task B2b) A REAL, hash-matching acceptance-audit record for an untouched,
        still-accepted capability. B2b's staleness pass (``_reconcile_conformant_rebuild_
        staleness``) now checks EVERY capability-dir capability's acceptance, not only the
        scanner-flagged ones -- so a capability this suite expects to STAY accepted needs a
        genuine record on disk (exactly what a REAL ceremony-accepted capability always has),
        or B2b's own fail-safe posture ("no record -> can't verify -> treat as stale") would
        revoke it too, for reasons entirely unrelated to what THIS suite (B2, scanner-red-only)
        is testing. Uses the real, already-registered ``delete_record`` op_kind (no adapter, a
        static dependency_set) so its ``implementation_hash`` is genuinely stable and never
        touched by anything these tests do."""
        agents_lib = _REAL_REPO / "wizard" / "agents" / "lib"
        if str(agents_lib) not in sys.path:
            sys.path.insert(0, str(agents_lib))
        from external_write.proof_hash import compute_implementation_hash  # noqa: E402
        from external_write.acceptance_ceremony import ACCEPTANCE_RECORD_SCHEMA  # noqa: E402

        # (Task B2b-fix, Critical 1) A matching capability_module_hash too -- otherwise this
        # capability's OWN record would fail the new signal-2 check (a record with no/mismatched
        # capability_module_hash fails safe to stale), reverting the untouched capability
        # anyway, for reasons unrelated to what THIS suite tests.
        cap_module_path = proj / "agents" / "capabilities" / f"{capability_id}_capability.py"
        capability_module_hash = hashlib.sha256(cap_module_path.read_bytes()).hexdigest()

        log_path = proj / "security" / "capability_acceptance_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": ACCEPTANCE_RECORD_SCHEMA,
            "capability_id": capability_id,
            "phase_id": phase_id,
            "risk_class": "read_only_local",
            "op_kind": "delete_record",
            "copy_run_proof_ref": "proof.json",
            "operator_receipt_ref": "receipt.json",
            "contract_hash": "0" * 64,
            "implementation_hash": compute_implementation_hash("delete_record"),
            "capability_module_hash": capability_module_hash,
            "operator_confirmation": "Yes, accept this capability for live use.",
            "receipt_accepted_at": "2026-01-01T00:00:00Z",
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def _project_with_two_capabilities(self):
        proj = self.tmp / "operator_proj"
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)

        # Capability 1: scanner-red, previously accepted:true -- must be reset.
        rebuilt_relpath = "agents/capabilities/acme_widget_deleter_capability.py"
        (proj / rebuilt_relpath).write_text(self.CAP_SOURCE_WITH_OP_KIND, encoding="utf-8")

        # Capability 2: conformant (no scan violations), previously accepted:true --
        # never enters `by_relpath` at all, so it must stay untouched.
        clean_relpath = "agents/capabilities/acme_report_reader_capability.py"
        (proj / clean_relpath).write_text(_READ_ONLY_REPORT, encoding="utf-8")

        secdir = proj / "security"
        secdir.mkdir(parents=True, exist_ok=True)
        descriptor_set = [
            {
                "id": "acme_widget_deleter", "name": "Widget deleter",
                "action_class": "delete", "risk_class": "irreversible_external",
                "recovery_profile_ref": None, "declared_test_target": "copy",
                "blast_radius_cap": 3, "accepted": True, "phase_id": "phase-1",
            },
            {
                "id": "acme_report_reader", "name": "Report reader",
                "action_class": "read", "risk_class": "read_only_local",
                "recovery_profile_ref": None, "declared_test_target": "copy",
                "blast_radius_cap": None, "accepted": True, "phase_id": "phase-1",
            },
        ]
        (secdir / "capability_descriptors.json").write_text(
            json.dumps(descriptor_set), encoding="utf-8")
        # See _write_conformant_acceptance_record's own docstring for why this is needed now
        # that B2b's staleness pass checks every accepted capability-dir capability.
        self._write_conformant_acceptance_record(proj, "acme_report_reader", "phase-1")
        return proj

    def _read_descriptor_set(self, proj):
        return json.loads(
            (proj / CAPABILITY_DESCRIPTOR_SET_REL).read_text(encoding="utf-8"))

    def test_previously_accepted_rebuilt_capability_is_reset_to_unaccepted(self):
        proj = self._project_with_two_capabilities()
        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")

        self.assertEqual(len(result.mechanisms), 1)
        self.assertEqual(result.mechanisms[0].mechanism_id, "acme_widget_deleter")

        entries = {e["id"]: e for e in self._read_descriptor_set(proj)}
        self.assertFalse(
            entries["acme_widget_deleter"]["accepted"],
            "a rebuilt/scanner-red capability must never keep a prior accepted:true")
        # The unrelated, conformant capability's acceptance is never touched.
        self.assertTrue(entries["acme_report_reader"]["accepted"])

    def test_reconcile_state_runs_and_marker_is_coherent(self):
        proj = self._project_with_two_capabilities()
        reconcile_upgrade(proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")

        # _write_paused_live_write_state (this module, upgrade-time) already wrote a
        # marker with no `canonical_id` field -- proving lifecycle_state.reconcile_state
        # (B1) actually ran requires that field to now be present, MERGED onto the
        # existing marker rather than losing its upgrade-time diagnostics.
        marker_path = proj / PAUSED_MECHANISMS_DIR_REL / "acme_widget_deleter.json"
        self.assertTrue(marker_path.is_file())
        state = json.loads(marker_path.read_text(encoding="utf-8"))
        self.assertEqual(state["canonical_id"], "acme_widget_deleter")
        self.assertEqual(state["mechanism_id"], "acme_widget_deleter")
        self.assertEqual(state["paused_op_kinds"], ["acme.widget.delete"])
        # Upgrade-time diagnostics this module itself wrote must survive the merge.
        self.assertEqual(state["from_version"], "0.13.0")
        self.assertEqual(state["to_version"], "0.13.1")

        # The pending-migration queue carries the entry reconcile_state's own
        # "not accepted AND migration pending" branch needed to see, to ensure the
        # marker (rather than treating this as "never accepted, nothing to do").
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual({e["mechanism_id"] for e in queue}, {"acme_widget_deleter"})

    def test_idempotent_rerun_does_not_flip_accepted_or_duplicate_markers(self):
        proj = self._project_with_two_capabilities()
        reconcile_upgrade(proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")
        first_entries = self._read_descriptor_set(proj)

        # Purge again -- a second reconcile_upgrade call in the SAME test process
        # is exactly the "stale external_write module" risk the setUp purge guards.
        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]
        reconcile_upgrade(proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")
        second_entries = self._read_descriptor_set(proj)

        self.assertEqual(first_entries, second_entries)
        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        self.assertEqual(len(list(marker_dir.glob("acme_widget_deleter.*"))), 2)

    def test_conformant_capability_never_scanned_stays_accepted(self):
        # A capability that never appears in by_relpath at all (no scan violations)
        # must never be visited by the B2 reset logic in the first place.
        proj = self._project_with_two_capabilities()
        reconcile_upgrade(proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")
        entries = {e["id"]: e for e in self._read_descriptor_set(proj)}
        self.assertTrue(entries["acme_report_reader"]["accepted"])
        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        self.assertFalse((marker_dir / "acme_report_reader.json").exists())
        self.assertFalse((marker_dir / "acme_report_reader.pause").exists())


# ===================================================================================
# Task B2b (Phase 3 Cut 1): conformant-rebuild acceptance-hash staleness -- the
# SCANNER-CLEAN half of the F-62 trust gap RebuildForcesAcceptedFalseTests above does NOT
# cover. A capability that stays conformant (never enters `by_relpath` -- the scanner-red
# reset above never even looks at it) but whose registered adapter's bytes changed since
# acceptance must still lose `accepted: true`, because `write_gate` authorizes on
# `accepted is True` alone and never re-checks `implementation_hash`.
#
# Uses a REAL registered throwaway op_kind + a REAL, genuinely-hashed adapter module file on
# disk (same reuse pattern as test_external_write_effects_manifest.py's own fixture and this
# task's own test_lifecycle_state.py additions) -- mutating the fixture adapter's actual bytes
# is what flips proof_hash.compute_implementation_hash, never a mocked/stubbed hash value.
# ===================================================================================

class ConformantRebuildStalenessTests(_Base):
    _FIXTURE_OP_KIND = "_upgrade_reconcile_b2b_fixture_op"
    _FIXTURE_MODULE_NAME = "_upgrade_reconcile_b2b_fixture_adapter_module"
    _FIXTURE_ADAPTER_SRC = (
        Path(__file__).resolve().parents[2] / "test_fixtures" / "effects_manifest"
        / "fixture_adapter.py"
    )

    def setUp(self):
        super().setUp()
        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]
        self._agents_lib = _REAL_REPO / "wizard" / "agents" / "lib"
        if str(self._agents_lib) not in sys.path:
            sys.path.insert(0, str(self._agents_lib))
        import external_write.contracts as _contracts  # noqa: E402
        from external_write.contracts import OperationContract  # noqa: E402
        from external_write.adapter_registry import (  # noqa: E402
            register_adapter, unregister_adapter,
        )
        self._contracts = _contracts
        self._register_adapter = register_adapter
        self._unregister_adapter = unregister_adapter
        self._prior_contract = _contracts.OPERATION_CONTRACTS.get(self._FIXTURE_OP_KIND)
        _contracts.OPERATION_CONTRACTS[self._FIXTURE_OP_KIND] = OperationContract(
            op_kind=self._FIXTURE_OP_KIND, writes=("__fixture__",), produces=(),
            dependency_set=(), verifier_set=(), introduces_persistent_binding=False,
            risk_class="irreversible_external", requires_accepted_phase=True,
        )

    def tearDown(self):
        self._unregister_adapter(self._FIXTURE_OP_KIND)
        if self._prior_contract is None:
            self._contracts.OPERATION_CONTRACTS.pop(self._FIXTURE_OP_KIND, None)
        else:
            self._contracts.OPERATION_CONTRACTS[self._FIXTURE_OP_KIND] = self._prior_contract
        sys.modules.pop(self._FIXTURE_MODULE_NAME, None)
        super().tearDown()

    def _register_fixture_adapter(self):
        import importlib.util
        adapter_path = self.tmp / "b2b_fixture_adapter.py"
        shutil.copy2(self._FIXTURE_ADAPTER_SRC, adapter_path)
        spec = importlib.util.spec_from_file_location(self._FIXTURE_MODULE_NAME, adapter_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[self._FIXTURE_MODULE_NAME] = module
        spec.loader.exec_module(module)
        self._register_adapter(self._FIXTURE_OP_KIND, module.FixtureAdapter())
        return adapter_path

    def _write_acceptance_record(self, proj, capability_id, phase_id, implementation_hash,
                                 capability_module_hash="__auto__"):
        """``capability_module_hash="__auto__"`` (default) hashes the capability's CURRENT
        module file on disk -- matches acceptance_ceremony's own algorithm (Task B2b-fix,
        Critical 1); a record missing/mismatching this field now fails safe to stale too."""
        from external_write.acceptance_ceremony import ACCEPTANCE_RECORD_SCHEMA  # noqa: E402
        if capability_module_hash == "__auto__":
            cap_module_path = proj / "agents" / "capabilities" / f"{capability_id}_capability.py"
            capability_module_hash = hashlib.sha256(cap_module_path.read_bytes()).hexdigest()
        log_path = proj / "security" / "capability_acceptance_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema": ACCEPTANCE_RECORD_SCHEMA, "capability_id": capability_id,
            "phase_id": phase_id, "risk_class": "irreversible_external",
            "op_kind": self._FIXTURE_OP_KIND, "copy_run_proof_ref": "proof.json",
            "operator_receipt_ref": "receipt.json", "contract_hash": "0" * 64,
            "implementation_hash": implementation_hash,
            "capability_module_hash": capability_module_hash,
            "operator_confirmation": "Yes, accept this capability for live use.",
            "receipt_accepted_at": "2026-01-01T00:00:00Z",
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def _project_with_conformant_capability(self, *, capability_id="acme_widget_sync"):
        proj = self.tmp / "operator_proj"
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)
        relpath = f"agents/capabilities/{capability_id}_capability.py"
        # _CONFORMANT_WRITER (module-level fixture above) routes through
        # run_enveloped_operation -- already proven scanner-clean by
        # DetectTests.test_conformant_writer_triggers_no_detection. Its own embedded op_kind
        # string ("sheets.status.tidy") is irrelevant here: the B2b detector reads op_kind
        # from the ACCEPTANCE RECORD, never from the capability's own source.
        (proj / relpath).write_text(_CONFORMANT_WRITER, encoding="utf-8")
        secdir = proj / "security"
        secdir.mkdir(parents=True, exist_ok=True)
        descriptor_set = [{
            "id": capability_id, "name": capability_id, "action_class": "sync",
            "risk_class": "irreversible_external", "recovery_profile_ref": None,
            "declared_test_target": "copy", "blast_radius_cap": 3,
            "accepted": True, "phase_id": "phase-1",
        }]
        (secdir / "capability_descriptors.json").write_text(
            json.dumps(descriptor_set), encoding="utf-8")
        return proj

    def test_conformant_rebuild_never_scanned_still_gets_acceptance_revoked(self):
        from external_write.proof_hash import compute_implementation_hash  # noqa: E402
        proj = self._project_with_conformant_capability()
        adapter_path = self._register_fixture_adapter()
        accepted_hash = compute_implementation_hash(self._FIXTURE_OP_KIND)
        self._write_acceptance_record(proj, "acme_widget_sync", "phase-1", accepted_hash)

        # Rebuild: mutate the registered adapter's bytes -- the capability's own file never
        # changes and never enters the AST scanner's violation set (by_relpath).
        with adapter_path.open("ab") as f:
            f.write(b"\n# rebuilt\n")

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")

        # Never scanner-flagged -- proves this is genuinely the scanner-CLEAN path.
        self.assertEqual(result.mechanisms, [])
        self.assertEqual(result.stale_acceptance_reset, ["acme_widget_sync"])

        entries = {e["id"]: e for e in json.loads(
            (proj / CAPABILITY_DESCRIPTOR_SET_REL).read_text(encoding="utf-8"))}
        self.assertFalse(entries["acme_widget_sync"]["accepted"])

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual({e["mechanism_id"] for e in queue}, {"acme_widget_sync"})

        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        self.assertTrue((marker_dir / "acme_widget_sync.pause").is_file())

    def test_matching_hash_leaves_conformant_capability_accepted(self):
        from external_write.proof_hash import compute_implementation_hash  # noqa: E402
        proj = self._project_with_conformant_capability()
        self._register_fixture_adapter()
        accepted_hash = compute_implementation_hash(self._FIXTURE_OP_KIND)
        self._write_acceptance_record(proj, "acme_widget_sync", "phase-1", accepted_hash)

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")

        self.assertEqual(result.stale_acceptance_reset, [])
        entries = {e["id"]: e for e in json.loads(
            (proj / CAPABILITY_DESCRIPTOR_SET_REL).read_text(encoding="utf-8"))}
        self.assertTrue(entries["acme_widget_sync"]["accepted"])
        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        self.assertFalse((marker_dir / "acme_widget_sync.pause").exists())

    def test_idempotent_rerun_does_not_re_flip_or_duplicate(self):
        from external_write.proof_hash import compute_implementation_hash  # noqa: E402
        proj = self._project_with_conformant_capability()
        adapter_path = self._register_fixture_adapter()
        accepted_hash = compute_implementation_hash(self._FIXTURE_OP_KIND)
        self._write_acceptance_record(proj, "acme_widget_sync", "phase-1", accepted_hash)
        with adapter_path.open("ab") as f:
            f.write(b"\n# rebuilt\n")

        reconcile_upgrade(proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")
        descriptors_1 = (proj / CAPABILITY_DESCRIPTOR_SET_REL).read_bytes()
        queue_1 = (proj / MIGRATION_QUEUE_REL).read_bytes()

        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]
        reconcile_upgrade(proj, _REAL_REPO, from_version="0.13.0", to_version="0.13.1")
        descriptors_2 = (proj / CAPABILITY_DESCRIPTOR_SET_REL).read_bytes()
        queue_2 = (proj / MIGRATION_QUEUE_REL).read_bytes()

        self.assertEqual(descriptors_1, descriptors_2)
        self.assertEqual(queue_1, queue_2)


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

    def test_cmd_apply_prints_plain_language_note_for_a_stale_acceptance_only_revocation(self):
        # (Task B2b-fix, Important) End-to-end: `wizard upgrade --apply` on a capability
        # revoked ONLY by hash staleness (never scanner-flagged -- it never enters
        # `mechanisms`) must still print a plain-language note, not silently switch it off.
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

        capability_id = "acme_widget_sync"
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True, exist_ok=True)
        cap_path = capdir / f"{capability_id}_capability.py"
        cap_path.write_text(_CONFORMANT_WRITER, encoding="utf-8")

        secdir = proj / "security"
        secdir.mkdir(parents=True, exist_ok=True)
        (secdir / "capability_descriptors.json").write_text(json.dumps([{
            "id": capability_id, "name": capability_id, "action_class": "sync",
            "risk_class": "irreversible_external", "recovery_profile_ref": None,
            "declared_test_target": "copy", "blast_radius_cap": 5,
            "accepted": True, "phase_id": "phase-1",
        }]), encoding="utf-8")

        # A REAL, hash-matching acceptance record (delete_record -- registered, no adapter,
        # so genuinely stable). Purge first so this resolves the REAL repo's own package,
        # never a stale reference some earlier test in this process cached.
        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]
        sys.path.insert(0, str(real_lib.parent))
        from external_write.proof_hash import compute_implementation_hash  # noqa: E402
        from external_write.acceptance_ceremony import ACCEPTANCE_RECORD_SCHEMA  # noqa: E402

        module_hash = hashlib.sha256(cap_path.read_bytes()).hexdigest()
        record = {
            "schema": ACCEPTANCE_RECORD_SCHEMA, "capability_id": capability_id,
            "phase_id": "phase-1", "risk_class": "irreversible_external",
            "op_kind": "delete_record", "copy_run_proof_ref": "proof.json",
            "operator_receipt_ref": "receipt.json", "contract_hash": "0" * 64,
            "implementation_hash": compute_implementation_hash("delete_record"),
            "capability_module_hash": module_hash,
            "operator_confirmation": "Yes, accept this capability for live use.",
            "receipt_accepted_at": "2026-01-01T00:00:00Z",
        }
        (secdir / "capability_acceptance_log.jsonl").write_text(
            json.dumps(record) + "\n", encoding="utf-8")

        # Rebuild: edit the capability's OWN code after acceptance. Adapter/call shape
        # (run_enveloped_operation) stays intact -- this capability NEVER enters `by_relpath`.
        cap_path.write_text(_CONFORMANT_WRITER + "\n# rebuilt\n", encoding="utf-8")

        # Purge again -- the CLI's own reconcile pass must resolve the SYNTHETIC dest_lib
        # copy, not whatever we just imported above from the real repo path.
        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main([
                "upgrade", "--to", "v0.5.0", "--apply",
                "--manifest-path", str(manifest_path),
                "--registry-path", str(registry_path),
            ])
        self.assertEqual(rc, 0)
        printed = buf.getvalue()

        # Never scanner-flagged -- proves this is genuinely the "stale_acceptance_reset only,
        # mechanisms empty" path, and the plain-language note still printed.
        self.assertIn(capability_id, printed)
        self.assertIn("switched", printed)
        self.assertNotIn("Traceback", printed)
        self.assertNotIn("Exception", printed)

        entries = json.loads(
            (secdir / "capability_descriptors.json").read_text(encoding="utf-8"))
        self.assertFalse(entries[0]["accepted"])

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

        # (xvendor round-2, R2-1) filename is the REAL scaffold convention
        # ("inbox_management_capability.py" == "<capability_id>_capability.py"
        # for capability_id "inbox_management") -- mechanism_id normalizes to
        # the bare capability_id, not the raw file stem.
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual({e["mechanism_id"] for e in queue},
                          {"inbox_management"})

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
