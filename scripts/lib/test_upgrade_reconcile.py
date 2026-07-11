"""Tests for the upgrade impact-review + reconcile engine (ADR-0042, Task 9).

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

import json
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upgrade_reconcile import (  # noqa: E402
    MIGRATION_QUEUE_REL,
    PAUSED_MECHANISMS_DIR_REL,
    ReconcileResult,
    reconcile_upgrade,
    render_reconcile_result,
    scan_operator_mechanisms,
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

_CONFORMANT_WRITER = '''"""Conformant capability: routes writes through run_operation (the gate)."""
from agents.lib.external_write.adapters import run_operation
from agents.lib.external_write.operations import Operation


def do_tidy_status():
    op = Operation(op_kind="sheets.status.tidy", params={})
    return run_operation(op)


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


class ReconcileEndToEndTests(_Base):
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


class RenderReconcileResultTests(unittest.TestCase):
    def test_empty_when_nothing_affected(self):
        result = ReconcileResult(
            operator_project_path="/tmp/x", from_version="v1", to_version="v2")
        self.assertEqual(render_reconcile_result(result), "")

    def test_summarizes_paused_mechanism(self):
        from upgrade_reconcile import MechanismReport
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


if __name__ == "__main__":
    unittest.main()
