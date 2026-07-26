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

import ast
import contextlib
import hashlib
import io
import json
import re
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import upgrade_reconcile  # noqa: E402
from upgrade_reconcile import (  # noqa: E402
    CAPABILITY_DESCRIPTOR_SET_REL,
    MIGRATION_QUEUE_REL,
    PAUSED_MECHANISMS_DIR_REL,
    MechanismReport,
    PredicateStubRemediation,
    ReconcileResult,
    discover_external_write_importers,
    reconcile_missing_evidence_predicates,
    reconcile_upgrade,
    render_impact_notice,
    render_reconcile_result,
    resolve_paused_op_kinds,
    scan_operator_mechanisms,
    _append_migration_request,
    _derive_owning_capability_at_reconcile,
    _missing_evidence_predicates_for_adapter,
    _write_paused_live_write_state,
    _GUARD_BEGIN,
    _guard_block,
    _relative_prefix,
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

_LEGACY_MODULE_LEVEL = (
    "from typing import Any\n"
    "from external_write.adapter_registry import register_adapter\n"
    "\n"
    "OP_KIND = 'inbox.labels.modify'\n"
    "\n"
    "\n"
    "def build_read_only_client() -> Any:\n"
    "    return object()\n"
    "\n"
    "\n"
    "class InboxLabelsAdapter:\n"
    "    def apply_one(self, raw_client, unit):\n"
    "        return None\n"
    "\n"
    "\n"
    "register_adapter(OP_KIND, InboxLabelsAdapter())\n"
)


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


def _iter_queue(queue):
    """Flatten whatever shape ``pending_migrations.json`` uses into individual
    entries. The real shape today (see ``_append_migration_request``) is a flat
    JSON list of dicts, but this stays defensive against a dict-wrapped or
    nested shape so the test doesn't silently pass by iterating over the wrong
    thing if that shape ever changes."""
    if isinstance(queue, dict):
        queue = queue.get("entries") or queue.get("migrations") or list(queue.values())
    for entry in (queue or []):
        if isinstance(entry, list):
            yield from entry
        else:
            yield entry


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def _project_with_capability(self, *, canonical_id, op_kind,
                                adapter_name, adapter_source):
        """A minimal operator project: one capability declaring op_kind, one
        adapter module registering it, and the adapter enrolled in the manifest
        under a name the filename convention cannot produce."""
        root = self.tmp / f"proj_{canonical_id}"
        lib = root / "agents" / "lib" / "external_write"
        caps = root / "agents" / "capabilities"
        lib.mkdir(parents=True, exist_ok=True)
        caps.mkdir(parents=True, exist_ok=True)
        (lib / adapter_name).write_text(adapter_source, encoding="utf-8")
        (lib / "operator_adapters.json").write_text(
            json.dumps([Path(adapter_name).stem]), encoding="utf-8")
        (caps / f"{canonical_id}_capability.py").write_text(
            f"OP_KIND = {op_kind!r}\n\n\ndef propose_operations(facade, batch_id):\n"
            "    return []\n", encoding="utf-8")
        return root


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

    def test_reconcile_detects_bulk_runner_outside_capability_dirs(self):
        # V15-3a: the estate's runner lived at agents/inbox/runner.py -- OUTSIDE
        # the fixed OPERATOR_CODE_DIRS. It must now be discovered via the import
        # graph (B-opt2), not just the fixed dir list.
        proj = self.tmp
        runner = proj / "agents" / "inbox" / "runner.py"
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text(
            "from external_write.run_envelope import mint_run_envelope, new_bulk_run_id\n"
            "def run_batches(batches):\n"
            "    for b in batches:\n"
            "        rid = new_bulk_run_id('x')\n"
            "        mint_run_envelope(run_id=rid)  # hand-rolled per-batch loop\n",
            encoding="utf-8")
        found = scan_operator_mechanisms(proj, _REAL_REPO)
        self.assertIn("agents/inbox/runner.py", found)
        kinds = {v.kind for v in found["agents/inbox/runner.py"]}
        self.assertIn("sealed_kernel_import", kinds)

    def test_discovery_excludes_the_sealed_lib_and_venv(self):
        proj = self.tmp
        sealed = proj / "agents" / "lib" / "external_write"
        sealed.mkdir(parents=True, exist_ok=True)
        (sealed / "x_probe.py").write_text(
            "from external_write.run_envelope import mint_run_envelope\n", encoding="utf-8")
        venv_pkg = proj / ".venv" / "lib" / "pkg.py"
        venv_pkg.parent.mkdir(parents=True, exist_ok=True)
        venv_pkg.write_text("import external_write\n", encoding="utf-8")
        files = {p.as_posix() for p in discover_external_write_importers(proj)}
        self.assertFalse(any("agents/lib/external_write" in f for f in files))
        self.assertFalse(any(".venv" in f for f in files))

    def test_discovery_catches_comma_list_import_regardless_of_ordering(self):
        # B' finding: external_write named SECOND (or later) in a comma-list
        # import must still be discovered -- under-inclusion here re-opens
        # V15-3 (a hand-rolled bulk runner written as `import os, external_write`
        # would otherwise go unscanned).
        proj = self.tmp
        runner = proj / "agents" / "inbox" / "runner.py"
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text("import os, external_write\n", encoding="utf-8")
        files = {p.as_posix() for p in discover_external_write_importers(proj)}
        self.assertTrue(any(f.endswith("agents/inbox/runner.py") for f in files))

    def test_discovery_catches_sys_path_hack_with_bare_import_no_prefix(self):
        # Final-review Finding 1: a hand-authored runner that (a) sys.path-hacks
        # straight into agents/lib/external_write and (b) bare-imports
        # `from run_envelope import mint_run_envelope` (no "external_write."
        # prefix anywhere on the import line) used to be invisible to the old
        # import-line-anchored regex -- even though it hand-rolls the bulk core
        # exactly like the runner.py case above. The sys.path literal still
        # names "external_write" somewhere in the file, so a token-anywhere
        # match must catch it.
        proj = self.tmp
        sneaky = proj / "agents" / "inbox" / "sneaky.py"
        sneaky.parent.mkdir(parents=True, exist_ok=True)
        sneaky.write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.join(os.path.dirname(__file__), "
            "\"..\", \"lib\", \"external_write\"))\n"
            "from run_envelope import mint_run_envelope   "
            "# bare import, no external_write. prefix\n",
            encoding="utf-8")
        files = {p.as_posix() for p in discover_external_write_importers(proj)}
        self.assertTrue(
            any(f.endswith("agents/inbox/sneaky.py") for f in files),
            f"sys.path-hack + bare-import runner must be discovered; got {files}")


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

        # 3. A pause marker + state record exist. (F-3A, build-lead decision) This
        # bespoke writer's stem does not collide with any other bespoke writer in
        # this project, so the marker/state FILENAME and its own "mechanism_id"
        # field keep the bare "estate_upkeep" stem -- see _migration_identity's
        # colliding-stem-only docstring.
        marker = proj / PAUSED_MECHANISMS_DIR_REL / "estate_upkeep.pause"
        state = proj / PAUSED_MECHANISMS_DIR_REL / "estate_upkeep.json"
        self.assertTrue(marker.exists())
        state_data = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(state_data["mechanism_id"], "estate_upkeep")
        self.assertTrue(state_data["credentials_preserved"])
        self.assertEqual(state_data["from_version"], "v0.10.2")
        self.assertEqual(state_data["to_version"], "v0.11.0")

        # (F-3B, anti-deadlock) The pause marker records a content hash of the
        # paused file -- scan.py's hash-bound quarantine (the coupled fix that
        # keeps the NEXT rebuild's real scan gate from deadlocking on a file
        # this same pass just safe-paused) reads this to verify the file has
        # not been edited since pause-time.
        expected_hash = hashlib.sha256(
            writer_path.read_bytes()).hexdigest()
        self.assertEqual(state_data["paused_content_sha256"], expected_hash)

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
        # (F-3A) queue entry mechanism_id matches the marker filename above --
        # the bare stem, since this writer's stem does not collide.
        self.assertIsNotNone(result.migration_queue_path)
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["mechanism_id"], "estate_upkeep")
        self.assertEqual(queue[0]["writer_relpath"], "agents/cron/estate_upkeep.py")
        self.assertEqual(queue[0]["status"], "pending")

        # (F-3B, anti-deadlock) The migration-queue entry ALSO carries the same
        # content hash as the pause marker -- both records must agree so
        # scan.py's quarantine (keyed off the queue entry) matches what the
        # marker itself recorded.
        self.assertEqual(queue[0]["paused_content_sha256"], expected_hash)

    def test_migration_queue_entry_routes_to_rebuild_flow_not_add_capability(self):
        # Task B4 / F-77: a naive operator (or agent) reading this entry must be
        # routed at the dedicated rebuild-paused-capability flow, never at
        # add-capability -- add-capability's own scope is new capabilities only
        # and dead-ends on an existing paused one.
        proj = _write_project(self.tmp, writer_body=_DIRECT_WRITER)

        reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.10.2", to_version="v0.11.0",
        )

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        # (F-3A) this writer's stem does not collide, so mechanism_id stays the
        # bare "estate_upkeep" stem -- see _migration_identity's colliding-stem-
        # only docstring.
        entry = next(e for e in queue if e["mechanism_id"] == "estate_upkeep")
        self.assertIn("rebuild-paused-capability", entry["suggested_next_step"])
        self.assertNotIn("add-capability", entry["suggested_next_step"])

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

    def test_full_reconcile_queues_migration_for_hand_rolled_bulk_runner(self):
        # V15-3 end-to-end: the estate's hand-rolled bulk runner lived at
        # agents/inbox/runner.py -- OUTSIDE the operator-capability directory,
        # with no run_<stem>.sh wrapper and not Orchestrator-scheduled. Tasks 1+2
        # made it DISCOVERABLE (import-graph-scoped scan) and scanner-red
        # (sealed_kernel_import). This proves the full reconcile_upgrade also
        # classifies it as a real migration case -- not the "no schedule found,
        # review by hand" fallback -- and durably queues it for the operator's
        # rebuild flow, same as any other scanner-red mechanism.
        proj = self.tmp
        runner = proj / "agents" / "inbox" / "runner.py"
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text(
            "from external_write.run_envelope import mint_run_envelope, new_bulk_run_id\n"
            "def run_batches(batches):\n"
            "    for b in batches:\n"
            "        mint_run_envelope(run_id=new_bulk_run_id('x'))\n",
            encoding="utf-8")
        (proj / ".wizard").mkdir(parents=True, exist_ok=True)
        reports = reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.15.0", to_version="v0.16.0",
        ).mechanisms
        runner_reports = [r for r in reports if r.writer_relpath == "agents/inbox/runner.py"]
        self.assertTrue(runner_reports, "the hand-rolled bulk runner was not reconciled")
        r = runner_reports[0]
        self.assertIn(r.state, {"broken_requires_migration", "paused_live_write"})
        self.assertNotEqual(r.state, "manual_review")
        # migration was queued for the operator to act on
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertTrue(any("runner.py" in str(entry) for entry in _iter_queue(queue)))

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


# ===================================================================================
# F-3A (validation stop): two bespoke (non-agents/capabilities/) writers sharing a
# file STEM in different directories must never collide on migration-queue identity
# or pause-marker filename. Pre-fix, `_capability_mechanism_id` keyed a bespoke
# writer on its bare stem alone -- `agents/inbox/runner.py` and
# `agents/upkeep/runner.py` both normalized to mechanism_id "runner", so the second
# one processed in a single `reconcile_upgrade` pass silently REPLACED the first's
# `pending_migrations.json` entry (`_append_migration_request`'s own dedup-by-
# mechanism_id convention) and both wrappers' pause markers pointed at the exact
# same `.wizard/paused-mechanisms/runner.{pause,json}` pair, clobbering whichever
# state was written second. This is the real estate-tracker shape
# (`agents/inbox/runner.py`) generalized to the case the original fix never
# exercised: a SECOND bespoke bulk runner sharing that same stem elsewhere.
# ===================================================================================

_BULK_RUNNER_BODY = (
    "from external_write.run_envelope import mint_run_envelope, new_bulk_run_id\n"
    "def run_batches(batches):\n"
    "    for b in batches:\n"
    "        mint_run_envelope(run_id=new_bulk_run_id('x'))\n"
)

_BULK_RUNNER_WRAPPER_TEMPLATE = """#!/usr/bin/env bash
# Wrapper for agents/{dirname}/runner.py.
export PATH="/usr/bin:/bin:/usr/local/bin"
cd "$(dirname "$0")/../.." || exit 1
/usr/bin/python3 "agents/{dirname}/runner.py"
"""


def _write_bulk_runner(proj: Path, dirname: str) -> Path:
    """A bespoke (non-capability) bulk runner at ``agents/<dirname>/runner.py``,
    WITH its conventional ``run_<stem>.sh`` wrapper -- the entrypoint-paused
    shape (not the wrapper-less broken_requires_migration shape), which is what
    actually exercises ``_pause_marker_path``/``_pause_state_path`` collision."""
    d = proj / "agents" / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "runner.py").write_text(_BULK_RUNNER_BODY, encoding="utf-8")
    wrapper = d / "run_runner.sh"
    wrapper.write_text(
        _BULK_RUNNER_WRAPPER_TEMPLATE.format(dirname=dirname), encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    return d / "runner.py"


class BespokeWriterRelpathKeyingTests(_Base):
    def test_two_same_stem_bespoke_runners_get_distinct_queue_entries_and_markers(self):
        proj = self.tmp
        _write_bulk_runner(proj, "inbox")
        _write_bulk_runner(proj, "upkeep")
        (proj / ".wizard").mkdir(parents=True, exist_ok=True)

        reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.16.0", to_version="v0.17.0")

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual(
            len(queue), 2,
            f"expected two distinct migration-queue entries, one per file; got {queue}")
        by_relpath = {e["writer_relpath"]: e for e in queue}
        self.assertIn("agents/inbox/runner.py", by_relpath)
        self.assertIn("agents/upkeep/runner.py", by_relpath)
        inbox_id = by_relpath["agents/inbox/runner.py"]["mechanism_id"]
        upkeep_id = by_relpath["agents/upkeep/runner.py"]["mechanism_id"]
        self.assertNotEqual(
            inbox_id, upkeep_id,
            "distinct writer_relpaths sharing a stem must get distinct mechanism_ids")

        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        inbox_marker = marker_dir / f"{inbox_id}.pause"
        upkeep_marker = marker_dir / f"{upkeep_id}.pause"
        self.assertTrue(inbox_marker.exists(), f"missing {inbox_marker}")
        self.assertTrue(upkeep_marker.exists(), f"missing {upkeep_marker}")
        self.assertNotEqual(inbox_marker, upkeep_marker, "pause markers must not clobber")

        inbox_state = json.loads(
            (marker_dir / f"{inbox_id}.json").read_text(encoding="utf-8"))
        upkeep_state = json.loads(
            (marker_dir / f"{upkeep_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(inbox_state["writer_relpath"], "agents/inbox/runner.py")
        self.assertEqual(upkeep_state["writer_relpath"], "agents/upkeep/runner.py")

    def test_capability_dir_mechanism_id_unaffected_by_relpath_keying(self):
        # (Step 4) Invariance guard: a real agents/capabilities/<id>_capability.py
        # writer must still yield mechanism_id == capability_id, byte-unchanged --
        # this fix must never touch the capability-dir identity/marker/queue path.
        proj = self.tmp
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)
        capability_id = "inbox_management"
        (capdir / f"{capability_id}_capability.py").write_text(
            "from external_write.capability_api import run_operation\n"
            "def go():\n    return run_operation(None, None)\n", encoding="utf-8")

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.16.0", to_version="v0.17.0")

        m = result.mechanisms[0]
        self.assertEqual(m.mechanism_id, capability_id)
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual(queue[0]["mechanism_id"], capability_id)
        # B2's lifecycle_state.reconcile_state writes its own marker/state pair
        # for this (pre-existing, unrelated to this fix) -- it must still be
        # keyed on the bare capability_id, never a relpath-derived id, since
        # this fix must not touch capability-dir identity at all.
        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        self.assertTrue((marker_dir / f"{capability_id}.json").exists())
        self.assertFalse((marker_dir / "agents_capabilities_inbox_management_capability.json"
                          ).exists())

    def test_single_bespoke_writer_no_collision_keeps_bare_stem(self):
        # (IMPORTANT, build-lead decision) Relpath-keying is a real cost -- a
        # lone bespoke writer (no stem collision in this project) must NOT pay
        # it: its migration-queue entry and pause-marker filename keep the
        # clean bare stem, exactly as before F-3A. Only a writer whose stem
        # actually collides with another bespoke writer in the SAME discovered
        # set gets relpath-keyed (see the two-same-stem test above).
        proj = _write_project(self.tmp, writer_body=_DIRECT_WRITER)  # agents/cron/estate_upkeep.py

        reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.16.0", to_version="v0.17.0")

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["mechanism_id"], "estate_upkeep")
        self.assertEqual(queue[0]["writer_relpath"], "agents/cron/estate_upkeep.py")

        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        self.assertTrue((marker_dir / "estate_upkeep.pause").exists())
        self.assertFalse((marker_dir / "agents_cron_estate_upkeep.pause").exists())

    def test_legacy_stem_keyed_marker_and_queue_entry_migrated_with_no_orphan(self):
        # (Step 5) Legacy-marker cleanup: a project that ran reconcile BEFORE this
        # fix existed carries a pause marker/state pair and a pending-migrations
        # entry keyed on the OLD bare stem ("runner") for a bespoke writer. A
        # SECOND bespoke writer sharing that same stem ("agents/upkeep/runner.py")
        # is also present this pass, so "runner" collides and the inbox writer's
        # CURRENT migration identity is now relpath-derived, differing from its
        # legacy bare-stem key. The upgrade must carry the pause state FORWARD
        # onto the new key and leave no orphaned legacy artifact behind (queue
        # entry OR marker/state file) -- and must not disturb the upkeep writer's
        # own, independently-created entry.
        proj = self.tmp
        writer_path = _write_bulk_runner(proj, "inbox")
        _write_bulk_runner(proj, "upkeep")  # forces the "runner" stem to collide this pass
        writer_relpath = "agents/inbox/runner.py"
        (proj / ".wizard").mkdir(parents=True, exist_ok=True)

        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "runner.pause").write_text("", encoding="utf-8")
        legacy_state = {
            "mechanism_id": "runner",
            "writer_relpath": writer_relpath,
            "entrypoint_relpath": "agents/inbox/run_runner.sh",
            "paused_at": "2026-01-01T00:00:00Z",
            "from_version": "v0.15.0",
            "to_version": "v0.16.0",
            "reason": "external-write gate violation detected on upgrade",
            "violations": [],
            "credentials_preserved": True,
            "migration_status": "pending",
        }
        (marker_dir / "runner.json").write_text(
            json.dumps(legacy_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        queue_path = proj / MIGRATION_QUEUE_REL
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_entry = {
            "mechanism_id": "runner",
            "writer_relpath": writer_relpath,
            "entrypoint_relpath": "agents/inbox/run_runner.sh",
            "requested_at": "2026-01-01T00:00:00Z",
            "from_version": "v0.15.0",
            "to_version": "v0.16.0",
            "reason": "flagged non-conformant with the external-write gate on upgrade",
            "violations": [],
            "suggested_next_step": "Use the rebuild-paused-capability flow ...",
            "status": "pending",
        }
        queue_path.write_text(
            json.dumps([legacy_entry], indent=2, sort_keys=True) + "\n", encoding="utf-8")

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.16.0", to_version="v0.17.0")

        runner_reports = [
            r for r in result.mechanisms if r.writer_relpath == writer_relpath]
        self.assertTrue(runner_reports)
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        self.assertEqual(
            len(queue), 2,
            f"expected the inbox writer's migrated entry PLUS the upkeep "
            f"writer's own independent entry, no orphan; got {queue}")
        inbox_entry = next(e for e in queue if e["writer_relpath"] == writer_relpath)
        new_id = inbox_entry["mechanism_id"]
        self.assertNotEqual(new_id, "runner")

        # No orphaned legacy artifacts remain.
        self.assertFalse((marker_dir / "runner.pause").exists())
        self.assertFalse((marker_dir / "runner.json").exists())
        self.assertEqual(inbox_entry["mechanism_id"], new_id)
        self.assertEqual(inbox_entry["writer_relpath"], writer_relpath)

        # The new-keyed marker exists (pause state carried forward, not dropped).
        self.assertTrue((marker_dir / f"{new_id}.pause").exists())
        _ = writer_path  # fixture side-effect only (file must exist for the scan)

    def test_already_paused_bespoke_writer_stays_paused_after_relpath_rekey(self):
        # CRITICAL regression: a writer safe-paused under the OLD bare-stem
        # scheme (wrapper already carries the guard block + a legacy `.pause`
        # marker exists), reconciled again once a colliding sibling appears and
        # its migration identity is rekeyed to a relpath-derived id, must NOT be
        # silently un-paused. Before the fix, `_migrate_legacy_bespoke_identity`
        # deleted the legacy `.pause`/`.json` pair unconditionally (even as a
        # sibling of the writer_relpath match-check), while the wrapper's
        # ALREADY-INSERTED guard is a frozen string that still names the legacy
        # marker filename (`_safe_pause_entrypoint` never rewrites an existing
        # guard) -- so the guard's `-e` check found nothing and the wrapper
        # would run the paused script again.
        proj = self.tmp
        _write_bulk_runner(proj, "inbox")
        _write_bulk_runner(proj, "upkeep")  # forces the "runner" stem to collide this pass
        writer_relpath = "agents/inbox/runner.py"
        entrypoint_relpath = "agents/inbox/run_runner.sh"
        legacy_id = "runner"

        # Simulate a PRIOR reconcile pass having already safe-paused this
        # writer under the old bare-stem id: the wrapper carries the real guard
        # block (built with the same `_guard_block` the module itself uses),
        # and the legacy-keyed marker/state pair exists on disk.
        wrapper_path = proj / entrypoint_relpath
        original = wrapper_path.read_text(encoding="utf-8")
        prefix = _relative_prefix(entrypoint_relpath)
        marker_from_wrapper = f"{prefix}/{PAUSED_MECHANISMS_DIR_REL}/{legacy_id}.pause"
        guard = _guard_block(
            legacy_id, writer_relpath, marker_from_wrapper, "v0.15.0", "v0.16.0")
        lines = original.splitlines(keepends=True)
        gated = lines[0] + guard + "".join(lines[1:])
        wrapper_path.write_text(gated, encoding="utf-8")

        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / f"{legacy_id}.pause").write_text("", encoding="utf-8")
        legacy_state = {
            "mechanism_id": legacy_id,
            "writer_relpath": writer_relpath,
            "entrypoint_relpath": entrypoint_relpath,
            "paused_at": "2026-01-01T00:00:00Z",
            "from_version": "v0.15.0",
            "to_version": "v0.16.0",
            "reason": "external-write gate violation detected on upgrade",
            "violations": [],
            "credentials_preserved": True,
            "migration_status": "pending",
        }
        (marker_dir / f"{legacy_id}.json").write_text(
            json.dumps(legacy_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        queue_path = proj / MIGRATION_QUEUE_REL
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(json.dumps([{
            "mechanism_id": legacy_id,
            "writer_relpath": writer_relpath,
            "entrypoint_relpath": entrypoint_relpath,
            "requested_at": "2026-01-01T00:00:00Z",
            "from_version": "v0.15.0",
            "to_version": "v0.16.0",
            "reason": "flagged non-conformant with the external-write gate on upgrade",
            "violations": [],
            "suggested_next_step": "Use the rebuild-paused-capability flow ...",
            "status": "pending",
        }], indent=2, sort_keys=True) + "\n", encoding="utf-8")

        reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.16.0", to_version="v0.17.0")

        # The writer must STILL be paused: the wrapper's guard must reference a
        # marker file that actually exists on disk (whatever id it was rekeyed
        # to) -- the guard and the marker must agree.
        wrapper_text = wrapper_path.read_text(encoding="utf-8")
        self.assertIn(_GUARD_BEGIN, wrapper_text)
        match = re.search(r'if \[ -e "\$_RECONCILE_HERE/([^"]+)" \]', wrapper_text)
        self.assertIsNotNone(
            match, "expected the safe-pause guard's marker-existence check line")
        # `_RECONCILE_HERE` is the wrapper's OWN directory (see `_guard_block`'s
        # `cd "$(dirname "$0")"`), not the project root -- resolve relative to
        # the wrapper's parent, matching what the shell guard actually checks.
        referenced_marker = (wrapper_path.parent / match.group(1)).resolve()
        self.assertTrue(
            referenced_marker.is_file(),
            f"guard references {referenced_marker}, which does not exist on disk -- "
            "the writer was silently un-paused")

    def test_failed_guard_rewrite_keeps_legacy_marker_so_writer_stays_paused(self):
        # (F-3A residual fix) The prior fix (see the test above) made
        # `_migrate_legacy_bespoke_identity` call `_rewrite_wrapper_guard_marker_id`
        # BEFORE deleting the legacy marker, so the guard and the marker stay in
        # agreement on the happy path. But the legacy-marker unlink loop still ran
        # UNCONDITIONALLY afterwards, discarding the rewrite's own return value --
        # so if the rewrite does NOT succeed (an OSError re-reading the wrapper
        # mid-migration, or the guard's embedded reference no longer matching the
        # reconstructed legacy path) while the wrapper's ALREADY-INSERTED guard
        # still names the legacy `.pause` file, the legacy marker got deleted out
        # from under a still-live guard reference anyway -- the guard's `-e` check
        # then finds nothing on disk and silently un-pauses the writer. This must
        # fail closed: when the rewrite does not succeed and the guard still names
        # the legacy marker, the legacy `.pause` file must be LEFT ALONE (an
        # orphan is acceptable; a silent un-pause is not).
        proj = self.tmp
        _write_bulk_runner(proj, "inbox")
        _write_bulk_runner(proj, "upkeep")  # forces the "runner" stem to collide this pass
        writer_relpath = "agents/inbox/runner.py"
        entrypoint_relpath = "agents/inbox/run_runner.sh"
        legacy_id = "runner"

        # Simulate a PRIOR reconcile pass having already safe-paused this writer
        # under the old bare-stem id, exactly as in the test above: the wrapper
        # carries the real guard block (built with the same `_guard_block` the
        # module itself uses), naming the legacy marker file, and the
        # legacy-keyed marker/state pair exists on disk.
        wrapper_path = proj / entrypoint_relpath
        original = wrapper_path.read_text(encoding="utf-8")
        prefix = _relative_prefix(entrypoint_relpath)
        marker_from_wrapper = f"{prefix}/{PAUSED_MECHANISMS_DIR_REL}/{legacy_id}.pause"
        guard = _guard_block(
            legacy_id, writer_relpath, marker_from_wrapper, "v0.15.0", "v0.16.0")
        lines = original.splitlines(keepends=True)
        gated = lines[0] + guard + "".join(lines[1:])
        wrapper_path.write_text(gated, encoding="utf-8")

        marker_dir = proj / PAUSED_MECHANISMS_DIR_REL
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / f"{legacy_id}.pause").write_text("", encoding="utf-8")
        legacy_state = {
            "mechanism_id": legacy_id,
            "writer_relpath": writer_relpath,
            "entrypoint_relpath": entrypoint_relpath,
            "paused_at": "2026-01-01T00:00:00Z",
            "from_version": "v0.15.0",
            "to_version": "v0.16.0",
            "reason": "external-write gate violation detected on upgrade",
            "violations": [],
            "credentials_preserved": True,
            "migration_status": "pending",
        }
        (marker_dir / f"{legacy_id}.json").write_text(
            json.dumps(legacy_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        queue_path = proj / MIGRATION_QUEUE_REL
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(json.dumps([{
            "mechanism_id": legacy_id,
            "writer_relpath": writer_relpath,
            "entrypoint_relpath": entrypoint_relpath,
            "requested_at": "2026-01-01T00:00:00Z",
            "from_version": "v0.15.0",
            "to_version": "v0.16.0",
            "reason": "flagged non-conformant with the external-write gate on upgrade",
            "violations": [],
            "suggested_next_step": "Use the rebuild-paused-capability flow ...",
            "status": "pending",
        }], indent=2, sort_keys=True) + "\n", encoding="utf-8")

        # Force the rewrite step to NOT succeed, exactly as
        # `_rewrite_wrapper_guard_marker_id` itself would if e.g. the wrapper
        # read raised OSError or the guard's embedded marker text didn't match
        # the reconstructed legacy reference -- while the guard block, in fact,
        # still names the legacy marker on disk (built above).
        with mock.patch.object(
                upgrade_reconcile, "_rewrite_wrapper_guard_marker_id", return_value=False):
            reconcile_upgrade(
                proj, _REAL_REPO, from_version="v0.16.0", to_version="v0.17.0")

        self.assertTrue(
            (marker_dir / f"{legacy_id}.pause").exists(),
            "the legacy pause marker was deleted even though the guard-rewrite "
            "did not succeed and the wrapper's guard still names it -- the "
            "writer was silently un-paused")

    def test_dotted_and_dashed_relpaths_disambiguate_via_sha1_suffix(self):
        # (MINOR, fold-in) `agents/a.b/runner.py` and `agents/a-b/runner.py`
        # collide on the bare stem "runner" AND -- per `_migration_identity`'s
        # own docstring -- both normalize to the identical `agents_a_b_runner`
        # prefix once `_NON_IDENTITY_CHARS_RE` collapses the `.` and `-` to
        # `_`. Only the appended `sha1(writer_relpath)[:8]` suffix can tell
        # them apart; assert it actually does.
        proj = self.tmp
        _write_bulk_runner(proj, "a.b")
        _write_bulk_runner(proj, "a-b")

        reconcile_upgrade(
            proj, _REAL_REPO, from_version="v0.16.0", to_version="v0.17.0")

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        by_relpath = {e["writer_relpath"]: e["mechanism_id"] for e in queue}
        dotted_id = by_relpath["agents/a.b/runner.py"]
        dashed_id = by_relpath["agents/a-b/runner.py"]
        self.assertTrue(dotted_id.startswith("agents_a_b_runner_"), dotted_id)
        self.assertTrue(dashed_id.startswith("agents_a_b_runner_"), dashed_id)
        self.assertNotEqual(
            dotted_id, dashed_id,
            "relpaths that collide on both the bare stem AND the normalized "
            "prefix must still get distinct migration ids via the sha1 suffix")


# ===================================================================================
# Task E (Cut 1.5 / v0.19.0): ADVISORY owning-capability link, stamped onto a bespoke-writer
# migration entry AT THE MOMENT IT IS QUEUED (`_append_migration_request`). UX ONLY -- see
# `_ext_write_state.derive_owning_capability`'s own docstring (this is its duplicated-by-value
# build-side twin, per this module's never-import-across-the-build/runtime-boundary discipline)
# for the full ranked-evidence contract and the hard "never a safety input" boundary. The
# corresponding safety-independence proof lives in
# wizard/agents/lib/external_write/test_owning_capability_advisory.py (this module never reads
# these fields for a block decision -- reconcile_upgrade's own scanner-violation-driven queueing
# is completely unaffected by whether an owner resolves).
# ===================================================================================

def _write_capability_module(proj: Path, cap_id: str, op_kind=None) -> Path:
    d = proj / "agents" / "capabilities"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{cap_id}_capability.py"
    lines = [f'"""{cap_id} -- fixture capability module (Task E test)."""', ""]
    if op_kind is not None:
        lines.append(f'OP_KIND = "{op_kind}"')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_bespoke_writer_source(proj: Path, relpath: str, source: str) -> Path:
    p = proj / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source, encoding="utf-8")
    return p


class DeriveOwningCapabilityAtReconcileTests(_Base):
    """Direct unit coverage of the build-side ranked-evidence helper itself, mirroring
    test_owning_capability_advisory.py's coverage of its runtime twin."""

    def test_envelope_capability_id_literal_resolves(self):
        proj = self.tmp
        _write_capability_module(proj, "google_sheets")
        _write_bespoke_writer_source(
            proj, "agents/inbox/runner.py", 'ENVELOPE_CAPABILITY_ID = "google_sheets"\n')

        owner, status = _derive_owning_capability_at_reconcile(proj, "agents/inbox/runner.py")

        self.assertEqual(status, "resolved")
        self.assertEqual(owner, "google_sheets")

    def test_two_distinct_strong_owners_is_ambiguous(self):
        proj = self.tmp
        _write_capability_module(proj, "google_sheets")
        _write_capability_module(proj, "gmail")
        _write_bespoke_writer_source(
            proj, "agents/inbox/runner.py",
            "from agents.capabilities import google_sheets_capability\n"
            "from agents.capabilities import gmail_capability\n")

        owner, status = _derive_owning_capability_at_reconcile(proj, "agents/inbox/runner.py")

        self.assertEqual(status, "ambiguous")
        self.assertIsNone(owner)

    def test_no_evidence_is_unresolved(self):
        proj = self.tmp
        _write_capability_module(proj, "google_sheets")
        _write_bespoke_writer_source(
            proj, "agents/inbox/runner.py",
            "from external_write.run_envelope import mint_run_envelope\n"
            "def run_all(chunks):\n    return [mint_run_envelope(c) for c in chunks]\n")

        owner, status = _derive_owning_capability_at_reconcile(proj, "agents/inbox/runner.py")

        self.assertEqual(status, "unresolved")
        self.assertIsNone(owner)


class AppendMigrationRequestOwnershipStampTests(_Base):
    """`_append_migration_request` stamps the advisory owning_capability_id / ownership_status
    fields onto the queued entry -- resolved/ambiguous/unresolved, matching the ranked-evidence
    contract exactly."""

    def test_resolved_owner_is_stamped_onto_the_queued_entry(self):
        proj = self.tmp
        _write_capability_module(proj, "google_sheets")
        _write_bespoke_writer_source(
            proj, "agents/inbox/runner.py", 'ENVELOPE_CAPABILITY_ID = "google_sheets"\n')

        _append_migration_request(
            proj, "runner", "agents/inbox/runner.py", None, [], "v0.18.0", "v0.19.0")

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        entry = next(e for e in queue if e["mechanism_id"] == "runner")
        self.assertEqual(entry["ownership_status"], "resolved")
        self.assertEqual(entry["owning_capability_id"], "google_sheets")
        # Untouched: every pre-existing field this fix must never alter.
        self.assertEqual(entry["writer_relpath"], "agents/inbox/runner.py")
        self.assertEqual(entry["status"], "pending")

    def test_ambiguous_owner_is_stamped_with_no_id(self):
        proj = self.tmp
        _write_capability_module(proj, "google_sheets")
        _write_capability_module(proj, "gmail")
        _write_bespoke_writer_source(
            proj, "agents/inbox/runner.py",
            "from agents.capabilities import google_sheets_capability\n"
            "from agents.capabilities import gmail_capability\n")

        _append_migration_request(
            proj, "runner", "agents/inbox/runner.py", None, [], "v0.18.0", "v0.19.0")

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        entry = next(e for e in queue if e["mechanism_id"] == "runner")
        self.assertEqual(entry["ownership_status"], "ambiguous")
        self.assertIsNone(entry["owning_capability_id"])

    def test_unresolved_owner_is_stamped_with_no_id(self):
        proj = self.tmp
        _write_bespoke_writer_source(
            proj, "agents/inbox/runner.py",
            "from external_write.run_envelope import mint_run_envelope\n")

        _append_migration_request(
            proj, "runner", "agents/inbox/runner.py", None, [], "v0.18.0", "v0.19.0")

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        entry = next(e for e in queue if e["mechanism_id"] == "runner")
        self.assertEqual(entry["ownership_status"], "unresolved")
        self.assertIsNone(entry["owning_capability_id"])


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


class RenderReconcileResultRemediationTests(_Base):
    """The pre-existing handoff hole this closes: the guard set
    ``migration_queue_path`` when predicate stubs were scaffolded but rendered
    nothing unless ``mechanisms`` or ``stale_acceptance_reset`` were also
    populated -- an upgrade could rewrite an operator's adapter, queue a
    repair task, and print no handoff at all."""

    def test_render_reports_scaffolded_predicate_stubs(self):
        """The pre-existing handoff hole: the upgrade could rewrite an operator's
        adapter, queue a repair task, set the queue path -- and print nothing.
        The neighbouring field was explicitly protected against exactly this."""
        from upgrade_reconcile import (
            PredicateStubRemediation, ReconcileResult, render_reconcile_result,
        )
        result = ReconcileResult(
            operator_project_path="/tmp/p", from_version="v0.20.0",
            to_version="v0.21.0",
            migration_queue_path="/tmp/p/agents/handoffs/pending_migrations.json",
            predicate_stubs_scaffolded=[PredicateStubRemediation(
                canonical_id="inbox_management",
                adapter_relpath="agents/lib/external_write/adapters_inbox.py",
                missing_predicates=["verify_apply_landed"])],
        )
        out = render_reconcile_result(result)
        self.assertTrue(out, "must not render empty when real work was done")
        self.assertIn("inbox_management", out)
        self.assertIn("pending_migrations.json", out)

    def test_render_reports_read_provisioner_violations(self):
        from upgrade_reconcile import (
            ReadProvisionerViolation, ReconcileResult, render_reconcile_result,
        )
        result = ReconcileResult(
            operator_project_path="/tmp/p", from_version="v0.20.0",
            to_version="v0.21.0",
            read_provisioner_violations=[ReadProvisionerViolation(
                capability_id="inbox_management", op_kind="inbox.labels.modify",
                adapter_relpath="agents/lib/external_write/adapters_inbox.py",
                kind="read_provisioner_missing", reason="no read-only reader")],
        )
        out = render_reconcile_result(result)
        self.assertIn("inbox_management", out)
        self.assertNotIn("rebuild the capability", out.lower())

    def test_render_is_still_empty_when_there_is_genuinely_nothing(self):
        from upgrade_reconcile import ReconcileResult, render_reconcile_result
        self.assertEqual(render_reconcile_result(ReconcileResult(
            operator_project_path="/tmp/p", from_version="v0.20.0",
            to_version="v0.21.0")), "")


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

        # (F-3B, anti-deadlock) The paused_live_write state ALSO records a
        # content hash of the paused writer file -- scan.py's hash-bound
        # quarantine reads this the same way it reads the entrypoint-pause
        # marker's hash.
        expected_hash = hashlib.sha256(
            (proj / relpath).read_bytes()).hexdigest()
        self.assertEqual(state["paused_content_sha256"], expected_hash)

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
# Task 4 (F-2): heal-at-source for a same-id descriptor twin -- a data-integrity defect
# (the registry never enforces `id` as a primary key), NOT normal ambiguity. Like
# ConformantRebuildStalenessTests just above, this is SCANNER-STATUS-INDEPENDENT: it runs
# every reconcile pass regardless of whether anything was scanner-flagged, so a corrupted
# registry self-heals without the operator ever having to dedup it by hand.
# ===================================================================================

class SameIdDescriptorTwinHealingTests(_Base):
    def _write_descriptor_set(self, proj, entries):
        path = proj / CAPABILITY_DESCRIPTOR_SET_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    def _entries(self, proj):
        return json.loads((proj / CAPABILITY_DESCRIPTOR_SET_REL).read_text(encoding="utf-8"))

    def test_two_unaccepted_same_id_entries_dedup_to_one(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        self._write_descriptor_set(proj, [
            {"id": "dup_cap", "name": "dup_cap", "accepted": False, "phase_id": "phase-1"},
            {"id": "dup_cap", "name": "dup_cap", "accepted": False, "phase_id": "phase-1"},
        ])

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.17.0", to_version="0.18.0")

        self.assertEqual(result.mechanisms, [])  # scanner-status-independent -- no findings
        self.assertEqual(result.same_id_twins_healed, ["dup_cap"])
        dup_entries = [e for e in self._entries(proj) if e["id"] == "dup_cap"]
        self.assertEqual(len(dup_entries), 1)

    def test_accepted_entry_kept_unaccepted_duplicates_stripped(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        self._write_descriptor_set(proj, [
            {"id": "dup_cap", "name": "dup_cap", "accepted": True, "phase_id": "phase-1"},
            {"id": "dup_cap", "name": "dup_cap", "accepted": False, "phase_id": "phase-1"},
            {"id": "dup_cap", "name": "dup_cap", "accepted": False, "phase_id": "phase-1"},
        ])

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.17.0", to_version="0.18.0")

        dup_entries = [e for e in self._entries(proj) if e["id"] == "dup_cap"]
        self.assertEqual(len(dup_entries), 1)
        self.assertTrue(dup_entries[0]["accepted"])
        self.assertEqual(result.same_id_twins_healed, ["dup_cap"])

    def test_other_entries_untouched(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        self._write_descriptor_set(proj, [
            {"id": "solo_cap", "name": "solo_cap", "accepted": False, "phase_id": "phase-1"},
            {"id": "dup_cap", "name": "dup_cap", "accepted": False, "phase_id": "phase-1"},
            {"id": "dup_cap", "name": "dup_cap", "accepted": False, "phase_id": "phase-1"},
        ])

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.17.0", to_version="0.18.0")

        self.assertEqual(result.same_id_twins_healed, ["dup_cap"])
        ids = [e["id"] for e in self._entries(proj)]
        self.assertEqual(ids.count("solo_cap"), 1)
        self.assertEqual(ids.count("dup_cap"), 1)

    def test_single_entry_for_an_id_is_never_touched(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        self._write_descriptor_set(proj, [
            {"id": "solo_cap", "name": "solo_cap", "accepted": False, "phase_id": "phase-1"},
        ])

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.17.0", to_version="0.18.0")

        self.assertEqual(result.same_id_twins_healed, [])
        self.assertEqual(len(self._entries(proj)), 1)

    def test_two_accepted_rows_sharing_an_id_left_untouched_needs_a_human(self):
        # A genuinely contradictory shape (2+ ACCEPTED rows sharing an id) is not this
        # check's concern (it only acts on groups with >1 UNACCEPTED entries) -- left alone
        # rather than guessed at, exactly like capability_health's own same-id trigger.
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        self._write_descriptor_set(proj, [
            {"id": "dup_cap", "name": "dup_cap", "accepted": True, "phase_id": "phase-1"},
            {"id": "dup_cap", "name": "dup_cap", "accepted": True, "phase_id": "phase-2"},
        ])

        result = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.17.0", to_version="0.18.0")

        self.assertEqual(result.same_id_twins_healed, [])
        self.assertEqual(len(self._entries(proj)), 2)

    def test_idempotent_rerun_does_not_re_touch(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        self._write_descriptor_set(proj, [
            {"id": "dup_cap", "name": "dup_cap", "accepted": False, "phase_id": "phase-1"},
            {"id": "dup_cap", "name": "dup_cap", "accepted": False, "phase_id": "phase-1"},
        ])

        reconcile_upgrade(proj, _REAL_REPO, from_version="0.17.0", to_version="0.18.0")
        first = (proj / CAPABILITY_DESCRIPTOR_SET_REL).read_bytes()
        result2 = reconcile_upgrade(
            proj, _REAL_REPO, from_version="0.17.0", to_version="0.18.0")
        second = (proj / CAPABILITY_DESCRIPTOR_SET_REL).read_bytes()

        self.assertEqual(first, second)
        self.assertEqual(result2.same_id_twins_healed, [])


# ===================================================================================
# Task B2 (F-75): migrator auto-scaffolds a FAILING predicate stub for a capability
# whose adapter does not declare a required evidence predicate. Like B2b's
# `ConformantRebuildStalenessTests` just above, this is SCANNER-STATUS-INDEPENDENT --
# a fully gate-conformant capability (never touched by the AST bypass scanner at all)
# can still fall out of compliance purely because the SHARED CONTRACT
# (`evidence.REQUIRED_EVIDENCE_PREDICATES`, Task B1/F-74) grew a new required name.
# ===================================================================================

class ReconcileMissingEvidencePredicatesTests(_Base):
    _ADAPTER_SOURCE_FULL_CURRENT_PAIR = '''"""Fixture adapter for Task B2 tests -- declares BOTH predicates required by
the contract AS OF TODAY, simulating a capability correctly built/accepted
under the OLDER contract, before a later upgrade adds a new one."""
from external_write.adapter_registry import register_adapter
from external_write.contracts import OperationContract, WRITE_AFFECTING_MODULES, register_contract

OP_KIND = "acme.widget.tidy"

register_contract(OperationContract(
    op_kind=OP_KIND, writes=("Status",), produces=(), dependency_set=WRITE_AFFECTING_MODULES,
    verifier_set=("operator_attested_v1",), introduces_persistent_binding=False,
    risk_class="reversible_external", requires_accepted_phase=True, blast_radius_cap=5,
    read_only_scope="acme.readonly",
))


class AcmeWidgetTidyAdapter:
    def build_write_client(self, op):
        raise NotImplementedError

    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        return {}

    def verify_apply_landed(self, evidence):
        return True

    def verify_undo_restored(self, evidence):
        return True


register_adapter(OP_KIND, AcmeWidgetTidyAdapter())
'''

    def setUp(self):
        super().setUp()
        self._agents_lib = _REAL_REPO / "wizard" / "agents" / "lib"
        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]
        if str(self._agents_lib) not in sys.path:
            sys.path.insert(0, str(self._agents_lib))
        from external_write import evidence  # noqa: E402
        self._evidence = evidence

    def _write_capability_with_adapter(self, proj, capability_id, adapter_source):
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True, exist_ok=True)
        (capdir / f"{capability_id}_capability.py").write_text(
            '"""fixture capability module (Task B2 test) -- content irrelevant, '
            'only its presence matters for capability_identity enumeration."""\n',
            encoding="utf-8",
        )
        ext_dir = proj / "agents" / "lib" / "external_write"
        ext_dir.mkdir(parents=True, exist_ok=True)
        adapter_path = ext_dir / f"adapters_{capability_id}.py"
        adapter_path.write_text(adapter_source, encoding="utf-8")
        return adapter_path

    def test_no_missing_predicates_scaffolds_nothing(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        self._write_capability_with_adapter(
            proj, "acme_widget_tidy", self._ADAPTER_SOURCE_FULL_CURRENT_PAIR)

        result = reconcile_missing_evidence_predicates(
            proj, _REAL_REPO, from_version="0.13.1", to_version="0.13.1")

        self.assertEqual(result, [])
        self.assertFalse((proj / MIGRATION_QUEUE_REL).exists())

    def test_new_required_predicate_gets_failing_stub_and_repair_task(self):
        # Simulate a contract-changing upgrade: `evidence.
        # REQUIRED_EVIDENCE_PREDICATES` grows a NEW name this fixture adapter
        # (built to satisfy only the CURRENT pair) does not declare.
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        adapter_path = self._write_capability_with_adapter(
            proj, "acme_widget_tidy", self._ADAPTER_SOURCE_FULL_CURRENT_PAIR)

        new_required = self._evidence.REQUIRED_EVIDENCE_PREDICATES + (
            "verify_b2_new_predicate_probe",)
        with mock.patch.object(self._evidence, "REQUIRED_EVIDENCE_PREDICATES", new_required):
            result = reconcile_missing_evidence_predicates(
                proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")

        self.assertEqual(len(result), 1)
        remediation = result[0]
        self.assertIsInstance(remediation, PredicateStubRemediation)
        self.assertEqual(remediation.canonical_id, "acme_widget_tidy")
        self.assertEqual(remediation.missing_predicates, ["verify_b2_new_predicate_probe"])

        # (a) FAILING NotImplementedError stub scaffolded, with the plain-
        # language message, and it stays syntactically valid Python.
        new_source = adapter_path.read_text(encoding="utf-8")
        tree = ast.parse(new_source)
        class_node = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        stub = next(
            n for n in class_node.body
            if isinstance(n, ast.FunctionDef) and n.name == "verify_b2_new_predicate_probe")
        self.assertEqual(len(stub.body), 1, "must be a SINGLE raise -- never a passing stub")
        self.assertIsInstance(stub.body[0], ast.Raise)
        self.assertEqual(stub.body[0].exc.func.id, "NotImplementedError")
        message = stub.body[0].exc.args[0].value
        self.assertIn("stays paused", message)
        self.assertIn("implemented and proved", message)
        # The EXISTING, already-correct predicates are untouched.
        self.assertIn("def verify_apply_landed(self, evidence):\n        return True", new_source)
        self.assertIn("def verify_undo_restored(self, evidence):\n        return True", new_source)

        # (b) a repair task landed in the SAME pending-migrations queue the
        # rebuild-paused-capability skill reads (Task B4, F-77 -- NOT
        # add-capability's generic Step A; that skill's scope is new
        # capabilities only and dead-ends on an existing paused one).
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        entry = next(e for e in queue if e["mechanism_id"] == "acme_widget_tidy")
        self.assertEqual(entry["kind"], "missing_evidence_predicates")
        self.assertEqual(entry["missing_predicates"], ["verify_b2_new_predicate_probe"])
        self.assertEqual(entry["status"], "pending")
        self.assertNotIn("violations", entry)
        self.assertIn("verify_b2_new_predicate_probe", entry["suggested_next_step"])
        # (c) F-77 routing fix: names the rebuild flow, never add-capability.
        self.assertIn("rebuild-paused-capability", entry["suggested_next_step"])
        self.assertNotIn("add-capability", entry["suggested_next_step"])

    def test_wired_into_reconcile_upgrade_end_to_end(self):
        # The migrator's own real entrypoint (reconcile_upgrade), not just the
        # standalone helper -- proves this pass is actually WIRED IN, not a
        # dangling function nothing calls.
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        self._write_capability_with_adapter(
            proj, "acme_widget_tidy", self._ADAPTER_SOURCE_FULL_CURRENT_PAIR)

        new_required = self._evidence.REQUIRED_EVIDENCE_PREDICATES + (
            "verify_b2_new_predicate_probe",)
        with mock.patch.object(self._evidence, "REQUIRED_EVIDENCE_PREDICATES", new_required):
            result = reconcile_upgrade(
                proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")

        self.assertIsInstance(result, ReconcileResult)
        self.assertEqual(len(result.predicate_stubs_scaffolded), 1)
        self.assertEqual(
            result.predicate_stubs_scaffolded[0].canonical_id, "acme_widget_tidy")
        # A scanner-conformant capability with no scanner violations at all --
        # `mechanisms` stays empty, exactly like B2b's conformant-rebuild path --
        # yet the migration queue still gets created because THIS pass wrote to it.
        self.assertEqual(result.mechanisms, [])
        self.assertIsNotNone(result.migration_queue_path)

    def test_idempotent_rerun_replaces_rather_than_duplicates(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        self._write_capability_with_adapter(
            proj, "acme_widget_tidy", self._ADAPTER_SOURCE_FULL_CURRENT_PAIR)
        new_required = self._evidence.REQUIRED_EVIDENCE_PREDICATES + (
            "verify_b2_new_predicate_probe",)
        with mock.patch.object(self._evidence, "REQUIRED_EVIDENCE_PREDICATES", new_required):
            reconcile_missing_evidence_predicates(
                proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")
            # Second call is idempotent: same missing predicate, no longer
            # missing text to insert TWICE -- but the queue entry must still be
            # exactly one, replaced not duplicated.
            reconcile_missing_evidence_predicates(
                proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        matching = [e for e in queue if e["mechanism_id"] == "acme_widget_tidy"]
        self.assertEqual(len(matching), 1)

    def test_no_adapter_module_on_disk_is_skipped_not_a_failure(self):
        # A capability whose op_kind has no registered adapter at all (the six
        # seeded field op_kinds' own permanent shape) has no adapters_<id>.py
        # file on disk -- this pass must skip it silently, mirroring Check 7 /
        # copy_run_proof's identical "N/A when no registered adapter" scope note.
        proj = self.tmp / "operator_proj"
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True)
        (capdir / "no_adapter_cap_capability.py").write_text(
            '"""fixture -- no adapter module for this one."""\n', encoding="utf-8")

        new_required = self._evidence.REQUIRED_EVIDENCE_PREDICATES + (
            "verify_b2_new_predicate_probe",)
        with mock.patch.object(self._evidence, "REQUIRED_EVIDENCE_PREDICATES", new_required):
            result = reconcile_missing_evidence_predicates(
                proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")
        self.assertEqual(result, [])

    def test_unparseable_adapter_source_is_skipped_never_guessed_at(self):
        proj = self.tmp / "operator_proj"
        adapter_path = self._write_capability_with_adapter(
            proj, "acme_broken_syntax", "def broken(:\n")

        new_required = self._evidence.REQUIRED_EVIDENCE_PREDICATES + (
            "verify_b2_new_predicate_probe",)
        with mock.patch.object(self._evidence, "REQUIRED_EVIDENCE_PREDICATES", new_required):
            result = reconcile_missing_evidence_predicates(
                proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")
        self.assertEqual(result, [])
        # Never touched -- a fail-closed skip, not a corrupting edit attempt.
        self.assertEqual(adapter_path.read_text(encoding="utf-8"), "def broken(:\n")

    def test_missing_predicates_helper_returns_none_when_no_class_present(self):
        # Direct unit coverage of the never-guess primitive itself.
        self.assertIsNone(_missing_evidence_predicates_for_adapter(
            "OP_KIND = 'x'\n", ("verify_apply_landed",)))
        self.assertIsNone(_missing_evidence_predicates_for_adapter(
            "def not (:\n", ("verify_apply_landed",)))
        self.assertEqual(
            _missing_evidence_predicates_for_adapter(
                "class X:\n    def verify_apply_landed(self, e):\n        return True\n",
                ("verify_apply_landed", "verify_undo_restored"),
            ),
            ["verify_undo_restored"],
        )


# ---------------------------------------------------------------------------
# F-1: AST registration-aware evidence-predicate migrator -- never shadow a
# working predicate. Regression coverage for a MULTI-adapter module (the real
# adapters_gmail.py shape: several classes, each registered via its own
# register_adapter(...) call). Pre-fix, detection inspected only the FIRST
# top-level ClassDef and insertion spliced before the FIRST register_adapter(
# call (i.e. right after the LAST class textually, no dedup) -- so a
# predicate correctly implemented on a non-first registered class was
# invisible to detection, AND liable to be shadowed by a duplicate stub
# landing on an already-complete class instead of the one that genuinely
# needed it.
# ---------------------------------------------------------------------------

_MULTI_CLASS_ADAPTER_SOURCE = '''"""Fixture multi-adapter module (F-1 test) -- mirrors adapters_gmail.py's
real shape: several classes, each registered via its OWN register_adapter(...)
call."""
from external_write.adapter_registry import register_adapter

OP_ONE = "acme.multi.one"
OP_TWO = "acme.multi.two"
OP_THREE = "acme.multi.three"


class AcmeMultiOneAdapter:
    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        return {}

    def verify_apply_landed(self, evidence):
        return True

    def verify_undo_restored(self, evidence):
        return True


class AcmeMultiTwoAdapter:
    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        return {}


class AcmeMultiThreeAdapter:
    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        return {}

    def verify_apply_landed(self, evidence):
        return True

    def verify_undo_restored(self, evidence):
        return True


register_adapter(OP_ONE, AcmeMultiOneAdapter())
register_adapter(OP_TWO, AcmeMultiTwoAdapter())
register_adapter(OP_THREE, AcmeMultiThreeAdapter())
'''

_AMBIGUOUS_ADAPTER_SOURCE = '''"""Fixture adapter module whose single registration cannot be resolved to a
unique class (F-1 ambiguity test) -- the instance is built by a FACTORY
FUNCTION, not a direct ClassName() constructor call."""
from external_write.adapter_registry import register_adapter

OP_KIND = "acme.ambiguous.op"


class AcmeAmbiguousAdapter:
    def plan(self, params):
        return []

    def apply_one(self, raw_client, unit):
        pass

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        return {}


def _build_adapter():
    return AcmeAmbiguousAdapter()


register_adapter(OP_KIND, _build_adapter())
'''


class ReconcileMissingEvidencePredicatesMultiClassTests(_Base):
    """F-1: detection + insertion must agree on the SAME registered target
    class(es), resolved from each register_adapter(...) call's own AST
    argument -- never "first ClassDef", never text position."""

    def setUp(self):
        super().setUp()
        self._agents_lib = _REAL_REPO / "wizard" / "agents" / "lib"
        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]
        if str(self._agents_lib) not in sys.path:
            sys.path.insert(0, str(self._agents_lib))

    def _write_capability_with_adapter(self, proj, capability_id, adapter_source):
        capdir = proj / "agents" / "capabilities"
        capdir.mkdir(parents=True, exist_ok=True)
        (capdir / f"{capability_id}_capability.py").write_text(
            '"""fixture capability module (F-1 test) -- content irrelevant, '
            'only its presence matters for capability_identity enumeration."""\n',
            encoding="utf-8",
        )
        ext_dir = proj / "agents" / "lib" / "external_write"
        ext_dir.mkdir(parents=True, exist_ok=True)
        adapter_path = ext_dir / f"adapters_{capability_id}.py"
        adapter_path.write_text(adapter_source, encoding="utf-8")
        return adapter_path

    def test_missing_predicates_helper_is_per_registered_class_not_first_class(self):
        # Direct unit proof that detection is NOT "first ClassDef only":
        # AcmeMultiOneAdapter (the first class) already has both predicates,
        # yet the union must still surface both names because
        # AcmeMultiTwoAdapter (a DIFFERENT registered class) lacks them.
        self.assertEqual(
            sorted(_missing_evidence_predicates_for_adapter(
                _MULTI_CLASS_ADAPTER_SOURCE,
                ("verify_apply_landed", "verify_undo_restored"))),
            ["verify_apply_landed", "verify_undo_restored"])

    def test_multi_class_module_no_shadow_when_first_class_already_complete(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        adapter_path = self._write_capability_with_adapter(
            proj, "acme_multi", _MULTI_CLASS_ADAPTER_SOURCE)

        result = reconcile_missing_evidence_predicates(
            proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")

        self.assertEqual(len(result), 1)
        remediation = result[0]
        self.assertEqual(remediation.canonical_id, "acme_multi")
        self.assertEqual(
            sorted(remediation.missing_predicates),
            ["verify_apply_landed", "verify_undo_restored"])

        new_source = adapter_path.read_text(encoding="utf-8")
        tree = ast.parse(new_source)  # must stay syntactically valid

        def method_name_list(class_name):
            class_node = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                              and n.name == class_name)
            return [n.name for n in class_node.body if isinstance(n, ast.FunctionDef)]

        # The two ALREADY-CORRECT classes must be untouched -- no
        # duplicate/shadowing stub landed on either of them.
        for class_name in ("AcmeMultiOneAdapter", "AcmeMultiThreeAdapter"):
            names = method_name_list(class_name)
            self.assertEqual(names.count("verify_apply_landed"), 1)
            self.assertEqual(names.count("verify_undo_restored"), 1)

    def test_multi_class_module_genuinely_missing_class_gets_own_stub(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        adapter_path = self._write_capability_with_adapter(
            proj, "acme_multi", _MULTI_CLASS_ADAPTER_SOURCE)

        reconcile_missing_evidence_predicates(
            proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")

        new_source = adapter_path.read_text(encoding="utf-8")
        tree = ast.parse(new_source)
        class_two = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                         and n.name == "AcmeMultiTwoAdapter")
        method_names = [n.name for n in class_two.body if isinstance(n, ast.FunctionDef)]
        self.assertIn("verify_apply_landed", method_names)
        self.assertIn("verify_undo_restored", method_names)

        for predicate_name in ("verify_apply_landed", "verify_undo_restored"):
            stub = next(n for n in class_two.body
                       if isinstance(n, ast.FunctionDef) and n.name == predicate_name)
            self.assertEqual(len(stub.body), 1, "must be a SINGLE raise -- never a passing stub")
            self.assertIsInstance(stub.body[0], ast.Raise)
            self.assertEqual(stub.body[0].exc.func.id, "NotImplementedError")

        # Exactly 3 total definitions of each name across the whole module:
        # AcmeMultiOne (pre-existing) + AcmeMultiTwo (newly scaffolded) +
        # AcmeMultiThree (pre-existing) -- never a shadowing 4th.
        self.assertEqual(new_source.count("def verify_apply_landed"), 3)
        self.assertEqual(new_source.count("def verify_undo_restored"), 3)

        # The migration queue records the real missing set for the capability
        # as a whole, keyed on the correct kind.
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        entry = next(e for e in queue if e["mechanism_id"] == "acme_multi")
        self.assertEqual(entry["kind"], "missing_evidence_predicates")
        self.assertEqual(
            sorted(entry["missing_predicates"]),
            ["verify_apply_landed", "verify_undo_restored"])

    def test_ambiguous_registration_scaffolds_nothing_and_queues_manual_repair(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        adapter_path = self._write_capability_with_adapter(
            proj, "acme_ambiguous", _AMBIGUOUS_ADAPTER_SOURCE)
        original_source = adapter_path.read_text(encoding="utf-8")

        result = reconcile_missing_evidence_predicates(
            proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")

        self.assertEqual(result, [])
        self.assertEqual(
            adapter_path.read_text(encoding="utf-8"), original_source,
            "an ambiguous registration must never be guessed at -- the "
            "source must stay byte-unchanged")

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        entry = next(e for e in queue if e["mechanism_id"] == "acme_ambiguous")
        self.assertEqual(entry["kind"], "ambiguous_adapter_registration")
        self.assertEqual(entry["status"], "pending")
        self.assertIn("register_adapter", entry["reason"])

    def test_ambiguous_registration_is_idempotent_rerun_replaces_not_duplicates(self):
        proj = self.tmp / "operator_proj"
        proj.mkdir(parents=True)
        self._write_capability_with_adapter(
            proj, "acme_ambiguous", _AMBIGUOUS_ADAPTER_SOURCE)

        reconcile_missing_evidence_predicates(
            proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")
        reconcile_missing_evidence_predicates(
            proj, _REAL_REPO, from_version="0.13.1", to_version="0.14.0")

        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        matching = [e for e in queue if e["mechanism_id"] == "acme_ambiguous"]
        self.assertEqual(len(matching), 1)


class ReconcileMissingEvidencePredicatesAntiTrustTheaterTests(_Base):
    """Task B2's own hard requirement, proved end-to-end (not just at the
    scaffold-string level): a scaffolded FAILING stub must NEVER let a
    capability's proof/acceptance attempt pass -- only a REAL implementation
    that replaces the stub can. Exercises the REAL `copy_run_proof.
    validate_copy_run_proof` gate (Task B2's own fix to it: an adapter
    predicate that RAISES must fail closed with a plain-language reason,
    never an uncaught traceback) against the REAL scaffolded stub text."""

    def setUp(self):
        super().setUp()
        self._agents_lib = _REAL_REPO / "wizard" / "agents" / "lib"
        for mod_name in list(sys.modules):
            if mod_name == "external_write" or mod_name.startswith("external_write."):
                del sys.modules[mod_name]
        if str(self._agents_lib) not in sys.path:
            sys.path.insert(0, str(self._agents_lib))
        from external_write.contracts import (  # noqa: E402
            OperationContract, OPERATION_CONTRACTS, register_contract,
        )
        from external_write.adapter_registry import (  # noqa: E402
            register_adapter, unregister_adapter,
        )
        from external_write.copy_run_proof import (  # noqa: E402
            COPY_RUN_PROOF_SCHEMA, validate_copy_run_proof,
        )
        from external_write.verifiers import POSTWRITE_VERIFICATION_SCHEMA  # noqa: E402
        from external_write.proof_hash import SHA256_HEX_LEN  # noqa: E402
        self._OPERATION_CONTRACTS = OPERATION_CONTRACTS
        self._register_contract = register_contract
        self._OperationContract = OperationContract
        self._register_adapter = register_adapter
        self._unregister_adapter = unregister_adapter
        self._validate_copy_run_proof = validate_copy_run_proof
        self._COPY_RUN_PROOF_SCHEMA = COPY_RUN_PROOF_SCHEMA
        self._POSTWRITE_VERIFICATION_SCHEMA = POSTWRITE_VERIFICATION_SCHEMA
        self._SHA256_HEX_LEN = SHA256_HEX_LEN

        self.OP_KIND = "_b2_anti_trust_theater_probe"
        self._register_contract(self._OperationContract(
            op_kind=self.OP_KIND, writes=("Status",), produces=(), dependency_set=(),
            verifier_set=("prestate_snapshot_diff_v1",),
            introduces_persistent_binding=False, risk_class="reversible_external",
        ))

    def tearDown(self):
        self._unregister_adapter(self.OP_KIND)
        self._OPERATION_CONTRACTS.pop(self.OP_KIND, None)
        super().tearDown()

    def _verification(self):
        return {
            "schema": self._POSTWRITE_VERIFICATION_SCHEMA,
            "verification_mode": "prestate_snapshot_diff",
            "claim_strength": "verified",
            "verifier_id": "prestate_snapshot_diff_v1",
            "source_lineage": {
                "pre_write_sources": ["prewrite_csv_backup"],
                "post_write_sources": ["live_surface_read"],
                "forbidden_sources": [
                    "writer_generated_id_map", "live_id_column_as_truth", "apply_report",
                ],
            },
            "invariant_checked": "value stable", "evidence_ref": "agents/handoffs/.ev.txt",
        }

    def _proof(self):
        return {
            "schema": self._COPY_RUN_PROOF_SCHEMA, "operation_id": "op-b2-1",
            "op_kind": self.OP_KIND, "data_class": "test_rows",
            "copy_source_ref": "copies/copy.csv",
            "prestate_snapshot_ref": "copies/copy.prestate.csv",
            "copy_apply_proof": {
                "apply_receipt_ref": "agents/handoffs/.apply_receipt.json",
                "apply_verification": self._verification(),
                "apply_evidence": {
                    "unit_id": "row1", "prestate": {"value": "Open"},
                    "poststate": {"value": "Done", "intended_value": "Done"},
                },
            },
            "copy_undo_proof": {
                "undo_receipt_ref": "agents/handoffs/.undo_receipt.json",
                "undo_verification": self._verification(),
                "undo_evidence": {
                    "unit_id": "row1", "prestate": {"value": "Open"},
                    "poststate": {"value": "Open"},
                },
            },
            "durability_checks": [], "accepted_for_live_use": True,
            "implementation_hash": "a" * self._SHA256_HEX_LEN,
            "contract_hash": "b" * self._SHA256_HEX_LEN,
        }

    def _build_and_load_stub_adapter(self, missing_predicates):
        """Real end-to-end use of the production scaffold helper: base source
        with NEITHER predicate declared, run through `capability_code_
        scaffold.insert_missing_evidence_predicate_stubs` for real, then
        actually imported (not just AST-inspected) so the REAL scaffolded
        `raise NotImplementedError` executes when copy_run_proof calls it."""
        import importlib.util
        import capability_code_scaffold as ccs
        base_source = (
            '"""fixture adapter -- stub-scaffold target."""\n'
            "from external_write.adapter_registry import register_adapter\n\n"
            f'OP_KIND = "{self.OP_KIND}"\n\n\n'
            "class _B2AntiTrustTheaterAdapter:\n"
            "    def plan(self, params):\n        return []\n\n"
            "    def apply_one(self, raw_client, unit):\n        pass\n\n"
            "    def undo_one(self, raw_client, unit):\n        pass\n\n"
            "    def verify_one(self, observer, unit):\n        return {}\n\n\n"
            "register_adapter(OP_KIND, _B2AntiTrustTheaterAdapter())\n"
        )
        new_source = ccs.insert_missing_evidence_predicate_stubs(
            base_source, missing_predicates)
        mod_path = self.tmp / "adapters__b2_anti_trust_theater_probe.py"
        mod_path.write_text(new_source, encoding="utf-8")
        module_spec = importlib.util.spec_from_file_location(
            "adapters__b2_anti_trust_theater_probe", mod_path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)  # fires register_adapter(OP_KIND, ...)
        return module

    def test_scaffolded_stub_refuses_the_proof_no_traceback_leaks(self):
        self._build_and_load_stub_adapter(
            ["verify_apply_landed", "verify_undo_restored"])
        result = self._validate_copy_run_proof(self._proof())
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.reason)
        self.assertNotIn("Traceback", result.reason)
        self.assertIn("verify_apply_landed raised", result.reason)
        self.assertIn("stays paused", result.reason)

    def test_only_a_real_implementation_replacing_the_stub_can_pass(self):
        self._build_and_load_stub_adapter(["verify_apply_landed", "verify_undo_restored"])
        stub_result = self._validate_copy_run_proof(self._proof())
        self.assertFalse(stub_result.ok)

        # Replace the stub with a REAL implementation for the SAME op_kind --
        # never editing the adapter file, just re-registering (proves the
        # refusal above was caused by the stub, not some other fixture bug).
        class _RealAdapter:
            def plan(self, params):
                return []

            def apply_one(self, raw_client, unit):
                pass

            def undo_one(self, raw_client, unit):
                pass

            def verify_one(self, observer, unit):
                return {}

            def verify_apply_landed(self, evidence):
                return (evidence.poststate.get("value") == "Done"
                        and evidence.prestate.get("value") != "Done")

            def verify_undo_restored(self, evidence):
                return evidence.poststate.get("value") == evidence.prestate.get("value")

        self._unregister_adapter(self.OP_KIND)
        self._register_adapter(self.OP_KIND, _RealAdapter())
        real_result = self._validate_copy_run_proof(self._proof())
        self.assertTrue(real_result.ok, real_result.reason)


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
        # (F-3A, build-lead decision) This bespoke (non-capability-dir) writer's
        # stem does not collide with any other bespoke writer in this project --
        # it keeps its clean bare-stem id, unchanged from pre-F-3A behavior. See
        # _migration_identity's colliding-stem-only docstring.
        self.assertTrue(
            (proj / PAUSED_MECHANISMS_DIR_REL / "estate_upkeep.pause").exists())
        queue = json.loads((proj / MIGRATION_QUEUE_REL).read_text(encoding="utf-8"))
        self.assertEqual(queue[0]["mechanism_id"], "estate_upkeep")
        self.assertEqual(queue[0]["writer_relpath"], "agents/cron/estate_upkeep.py")

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


class ResolveAdapterMigrationTargetsTests(_Base):

    def test_adapter_targets_union_manifest_and_convention(self):
        """The manifest is authoritative when present; the filename convention
        is kept for installs that predate it. Neither alone is enough -- the
        estate's own inbox adapter is enrolled in the manifest under a name the
        convention cannot produce."""
        from upgrade_reconcile import resolve_adapter_migration_targets
        root = Path(self.tmp)
        lib = root / "agents" / "lib" / "external_write"
        lib.mkdir(parents=True, exist_ok=True)
        (lib / "adapters_inbox.py").write_text("# enrolled only\n", encoding="utf-8")
        (lib / "adapters_estate_upkeep.py").write_text("# both\n", encoding="utf-8")
        (lib / "operator_adapters.json").write_text(
            '["adapters_inbox", "adapters_estate_upkeep"]', encoding="utf-8")
        targets = resolve_adapter_migration_targets(
            root, ["estate_upkeep", "inbox_management"])
        self.assertIsNone(targets.manifest_blocking_reason)
        self.assertIn("agents/lib/external_write/adapters_inbox.py", targets.relpaths)
        self.assertIn("agents/lib/external_write/adapters_estate_upkeep.py",
                      targets.relpaths)

    def test_a_malformed_manifest_blocks_and_never_falls_back_silently(self):
        """A present-but-unparseable enrolment manifest must fail closed. Falling
        back to the filename convention would migrate a SUBSET and report
        success -- an upgrade that says it worked while an enrolled adapter was
        skipped is the failure this cut exists to close."""
        from upgrade_reconcile import resolve_adapter_migration_targets
        root = Path(self.tmp)
        lib = root / "agents" / "lib" / "external_write"
        lib.mkdir(parents=True, exist_ok=True)
        (lib / "adapters_estate_upkeep.py").write_text("# x\n", encoding="utf-8")
        (lib / "operator_adapters.json").write_text("{not json", encoding="utf-8")
        targets = resolve_adapter_migration_targets(root, ["estate_upkeep"])
        self.assertIsNotNone(targets.manifest_blocking_reason)
        self.assertEqual(targets.relpaths, (),
                         "a blocking manifest problem must yield NO targets, "
                         "never a partial set")

    def test_an_absent_manifest_is_not_a_problem(self):
        """Most installs predate the manifest. Absent is a clean no-op."""
        from upgrade_reconcile import resolve_adapter_migration_targets
        root = Path(self.tmp)
        lib = root / "agents" / "lib" / "external_write"
        lib.mkdir(parents=True, exist_ok=True)
        (lib / "adapters_estate_upkeep.py").write_text("# x\n", encoding="utf-8")
        targets = resolve_adapter_migration_targets(root, ["estate_upkeep"])
        self.assertIsNone(targets.manifest_blocking_reason)
        self.assertEqual(targets.relpaths,
                         ("agents/lib/external_write/adapters_estate_upkeep.py",))

    def test_shipped_baseline_adapters_are_never_migration_targets(self):
        """The migration set REWRITES its targets. A shipped baseline adapter is
        wizard-emitted library code, refreshed by the upgrade's own file
        delivery, so it must never be rewritten in an operator's project --
        scaffolding a failing stub into one would break a working adapter.

        The shipped names are enrolled in the manifest here ON PURPOSE: that is
        the only way they can become candidates at all, so it is the only way
        this test can reach the exclusion it exists to pin. With the exclusion
        removed, this test must fail.
        """
        from upgrade_reconcile import resolve_adapter_migration_targets
        root = Path(self.tmp)
        lib = root / "agents" / "lib" / "external_write"
        lib.mkdir(parents=True, exist_ok=True)
        (lib / "adapters.py").write_text("# reference adapter\n", encoding="utf-8")
        (lib / "adapters_gmail.py").write_text("# shipped baseline\n", encoding="utf-8")
        (lib / "adapters_estate_upkeep.py").write_text("# operator\n", encoding="utf-8")
        (lib / "operator_adapters.json").write_text(
            json.dumps(["adapters", "adapters_gmail", "adapters_estate_upkeep"]),
            encoding="utf-8")
        targets = resolve_adapter_migration_targets(root, ["estate_upkeep"])
        self.assertNotIn("agents/lib/external_write/adapters.py", targets.relpaths)
        self.assertNotIn("agents/lib/external_write/adapters_gmail.py",
                         targets.relpaths)
        self.assertEqual(
            targets.relpaths,
            ("agents/lib/external_write/adapters_estate_upkeep.py",),
            "the operator's own adapter must be the ONLY target")

    _BOTH_MIGRATIONS_NEEDED = (
        "from typing import Any\n"
        "from external_write.adapter_registry import register_adapter\n"
        "\n"
        "OP_KIND = 'demo.op'\n"
        "\n"
        "\n"
        "def build_read_only_client() -> Any:\n"
        "    return object()\n"
        "\n"
        "\n"
        "class DemoAdapter:\n"
        "    def apply_one(self, raw_client, unit):\n"
        "        return None\n"
        "\n"
        "\n"
        "register_adapter(OP_KIND, DemoAdapter())\n"
    )

    def test_both_migrations_land_on_the_same_adapter_module(self):
        """The divergent case the default masks: a module needing BOTH a
        predicate stub AND the provisioner move. Two passes that each read and
        write would have the second clobber the first from stale text, and the
        upgrade would report success with one migration silently lost."""
        from upgrade_reconcile import reconcile_adapter_migrations
        root = self._project_with_capability(
            canonical_id="demo", op_kind="demo.op",
            adapter_name="adapters_demo.py",
            adapter_source=self._BOTH_MIGRATIONS_NEEDED)
        remediated, outcomes, blocking = reconcile_adapter_migrations(
            root, _REAL_REPO, from_version="v0.20.0", to_version="v0.21.0")
        self.assertIsNone(blocking)
        src = (root / "agents" / "lib" / "external_write"
               / "adapters_demo.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "DemoAdapter")
        methods = {b.name for b in cls.body if isinstance(b, ast.FunctionDef)}
        self.assertIn("build_read_only_client", methods,
                      "the provisioner move must have landed")
        self.assertTrue(
            methods & {"verify_apply_landed", "verify_undo_restored"},
            f"the evidence-predicate stub must have landed too: {methods}")
        self.assertFalse(
            any(isinstance(n, ast.FunctionDef)
                and n.name == "build_read_only_client" for n in tree.body),
            "the module-level provisioner must be gone")
        self.assertTrue(remediated, "the predicate scaffold must be reported")
        names = {o.migration_name for o in outcomes if o.changed}
        self.assertEqual(names, {"missing_evidence_predicates",
                                 "module_level_provisioner"})

    def test_the_module_is_written_exactly_once(self):
        """Single-read/single-write is the shipped form, not sequencing."""
        from upgrade_reconcile import reconcile_adapter_migrations
        import upgrade_reconcile as ur
        root = self._project_with_capability(
            canonical_id="demo", op_kind="demo.op",
            adapter_name="adapters_demo.py",
            adapter_source=self._BOTH_MIGRATIONS_NEEDED)
        target = (root / "agents" / "lib" / "external_write" / "adapters_demo.py")
        writes = []
        real_write = ur._atomic_write

        def counting_write(path, text):
            if Path(path) == target:
                writes.append(text)
            return real_write(path, text)

        ur._atomic_write = counting_write
        try:
            reconcile_adapter_migrations(
                root, _REAL_REPO,
                from_version="v0.20.0", to_version="v0.21.0")
        finally:
            ur._atomic_write = real_write
        self.assertEqual(len(writes), 1,
                         f"expected exactly one write, got {len(writes)}")


# ===================================================================================
# The read-provisioner conformance POST-CONDITION — asserted against the END STATE,
# after any migrations have run, so a gap in what they enumerated cannot produce a
# green upgrade with a broken read path.
# ===================================================================================

class ReadProvisionerConformanceTests(_Base):
    def test_post_condition_catches_an_unmigrated_provisioner(self):
        """The observed failure, reproduced: the read-client builder sits at
        module level, so the registry's class lookup finds nothing and the read
        path cannot work. Whatever the migration did or did not enumerate, the
        post-condition sees the end state."""
        from upgrade_reconcile import check_read_provisioner_conformance
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py",
            adapter_source=_LEGACY_MODULE_LEVEL)
        violations = check_read_provisioner_conformance(root)
        self.assertEqual(len(violations), 1, violations)
        self.assertEqual(violations[0].kind, "read_provisioner_missing")
        self.assertEqual(violations[0].op_kind, "inbox.labels.modify")
        self.assertEqual(violations[0].adapter_relpath,
                         "agents/lib/external_write/adapters_inbox.py")

    def test_post_condition_passes_once_the_method_is_on_the_class(self):
        from upgrade_reconcile import check_read_provisioner_conformance
        migrated = _LEGACY_MODULE_LEVEL.replace(
            "def build_read_only_client() -> Any:\n    return object()\n\n\n", ""
        ).replace(
            "class InboxLabelsAdapter:\n",
            "class InboxLabelsAdapter:\n"
            "    def build_read_only_client(self, op) -> Any:\n"
            "        return object()\n\n")
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py", adapter_source=migrated)
        self.assertEqual(check_read_provisioner_conformance(root), [])

    def test_post_condition_finds_the_adapter_by_registration_not_by_filename(self):
        """Immunity to the resolution defect: the adapter filename does not match
        the capability's canonical id, and the post-condition still finds it --
        it globs the adapter directory and reads registrations, never a filename
        convention or a manifest."""
        from upgrade_reconcile import check_read_provisioner_conformance
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py",
            adapter_source=_LEGACY_MODULE_LEVEL)
        (root / "agents" / "lib" / "external_write"
         / "operator_adapters.json").unlink()
        violations = check_read_provisioner_conformance(root)
        self.assertEqual(len(violations), 1,
                         "no manifest and a non-matching filename must not hide it")

    def test_post_condition_does_not_fire_on_shipped_adapters_with_no_capability(self):
        """The over-firing guard. Shipped baseline adapters register op_kinds no
        capability declares and legitimately have no read-client builder. A gate
        that flagged them would fire in every project including every fresh
        build, and a guard that always fires trains people to ignore it."""
        from upgrade_reconcile import check_read_provisioner_conformance
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py",
            adapter_source=_LEGACY_MODULE_LEVEL.replace(
                "def build_read_only_client() -> Any:\n    return object()\n\n\n", ""
            ).replace(
                "class InboxLabelsAdapter:\n",
                "class InboxLabelsAdapter:\n"
                "    def build_read_only_client(self, op):\n"
                "        return object()\n\n"))
        lib = root / "agents" / "lib" / "external_write"
        (lib / "adapters_gmail.py").write_text(
            "from external_write.adapter_registry import register_adapter\n"
            "\n"
            "OP_TRASH = 'gmail.message.trash'\n"
            "OP_UNTRASH = 'gmail.message.untrash'\n"
            "\n"
            "\n"
            "class GmailMessageTrashAdapter:\n"
            "    pass\n"
            "\n"
            "\n"
            "class GmailMessageUntrashAdapter:\n"
            "    pass\n"
            "\n"
            "\n"
            "register_adapter(OP_TRASH, GmailMessageTrashAdapter())\n"
            "register_adapter(OP_UNTRASH, GmailMessageUntrashAdapter())\n",
            encoding="utf-8")
        self.assertEqual(check_read_provisioner_conformance(root), [],
                         "a registered op_kind that no capability declares must "
                         "not be flagged")

    def test_post_condition_reports_a_capability_with_no_registered_adapter(self):
        from upgrade_reconcile import check_read_provisioner_conformance
        root = self._project_with_capability(
            canonical_id="orphan", op_kind="orphan.op",
            adapter_name="adapters_orphan.py",
            adapter_source="# no registration at all\n")
        violations = check_read_provisioner_conformance(root)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].kind, "no_registered_adapter")

    def test_post_condition_accepts_an_inherited_provisioner(self):
        """An adapter may inherit the builder from a base class in the same
        module. Flagging that would be a false red."""
        from upgrade_reconcile import check_read_provisioner_conformance
        root = self._project_with_capability(
            canonical_id="demo", op_kind="demo.op",
            adapter_name="adapters_demo.py",
            adapter_source=(
                "from external_write.adapter_registry import register_adapter\n"
                "\n"
                "OP_KIND = 'demo.op'\n"
                "\n"
                "\n"
                "class BaseAdapter:\n"
                "    def build_read_only_client(self, op):\n"
                "        return object()\n"
                "\n"
                "\n"
                "class DemoAdapter(BaseAdapter):\n"
                "    def apply_one(self, raw_client, unit):\n"
                "        return None\n"
                "\n"
                "\n"
                "register_adapter(OP_KIND, DemoAdapter())\n"))
        self.assertEqual(check_read_provisioner_conformance(root), [])


class ReadProvisionerConformanceRecordingTests(_Base):
    def test_a_violation_becomes_a_blocking_queue_entry(self):
        """A printed note is not a safety state. The violation must land in the
        pending-migrations queue with a non-empty writer_relpath and pending
        status, which is exactly what the project-wide safety predicate selects
        on -- so it blocks live-enable without any new blocking channel."""
        import json
        from upgrade_reconcile import (
            check_read_provisioner_conformance, record_read_provisioner_conformance,
        )
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py",
            adapter_source=_LEGACY_MODULE_LEVEL)
        violations = check_read_provisioner_conformance(root)
        record_read_provisioner_conformance(
            root, violations, from_version="v0.20.0", to_version="v0.21.0")
        queue = json.loads(
            (root / "agents" / "handoffs" / "pending_migrations.json")
            .read_text(encoding="utf-8"))
        entries = [e for e in queue if e.get("kind") == "read_provisioner_missing"]
        self.assertEqual(len(entries), 1, queue)
        entry = entries[0]
        self.assertTrue(entry["writer_relpath"])
        self.assertEqual(entry["status"], "pending")
        self.assertTrue(entry["reason"])
        self.assertTrue(entry["suggested_next_step"])

    def test_a_violation_entry_records_no_content_hash(self):
        """Deliberate omission. The auto-reaper clears an entry whose file's hash
        changed and which now scans clean -- so recording a hash here would let
        an unrelated edit to the adapter un-block a still-missing reader. This
        entry kind is cleared by re-running the check, never by a hash."""
        import json
        from upgrade_reconcile import (
            check_read_provisioner_conformance, record_read_provisioner_conformance,
        )
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py",
            adapter_source=_LEGACY_MODULE_LEVEL)
        record_read_provisioner_conformance(
            root, check_read_provisioner_conformance(root),
            from_version="v0.20.0", to_version="v0.21.0")
        entry = [e for e in json.loads(
            (root / "agents" / "handoffs" / "pending_migrations.json")
            .read_text(encoding="utf-8"))
            if e.get("kind") == "read_provisioner_missing"][0]
        self.assertIsNone(entry.get("paused_content_sha256"))

    def test_recording_is_idempotent_and_clears_when_conformant(self):
        """Re-running must replace, not duplicate; and once the adapter is fixed
        the entry must go, or a repaired project stays blocked forever."""
        import json
        from upgrade_reconcile import (
            check_read_provisioner_conformance, record_read_provisioner_conformance,
        )
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py",
            adapter_source=_LEGACY_MODULE_LEVEL)
        queue_path = root / "agents" / "handoffs" / "pending_migrations.json"
        for _ in range(3):
            record_read_provisioner_conformance(
                root, check_read_provisioner_conformance(root),
                from_version="v0.20.0", to_version="v0.21.0")
        entries = [e for e in json.loads(queue_path.read_text(encoding="utf-8"))
                   if e.get("kind") == "read_provisioner_missing"]
        self.assertEqual(len(entries), 1, "must replace, never duplicate")

        record_read_provisioner_conformance(
            root, [], from_version="v0.20.0", to_version="v0.21.0")
        entries = [e for e in json.loads(queue_path.read_text(encoding="utf-8"))
                   if e.get("kind") == "read_provisioner_missing"]
        self.assertEqual(entries, [], "a conformant project must be unblocked")

    def test_recording_never_touches_another_entry_kind(self):
        """One authority per fact. This writer owns its own entry kinds only --
        a second authority over somebody else's entry is the duplicated-inference
        defect this package guards against.

        A real violation is recorded here ON PURPOSE: with nothing to record the
        writer returns before writing at all, so the foreign entry would survive
        even a writer that clobbered it. The write path has to actually run for
        this to prove anything.
        """
        import json
        from upgrade_reconcile import (
            check_read_provisioner_conformance, record_read_provisioner_conformance,
        )
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py",
            adapter_source=_LEGACY_MODULE_LEVEL)
        queue_path = root / "agents" / "handoffs" / "pending_migrations.json"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        foreign = {
            "mechanism_id": "agents_inbox_runner",
            "writer_relpath": "agents/inbox/runner.py",
            "kind": "external_write_bypass", "status": "pending",
            "paused_content_sha256": "deadbeef",
        }
        queue_path.write_text(json.dumps([foreign]), encoding="utf-8")

        violations = check_read_provisioner_conformance(root)
        self.assertTrue(violations, "fixture must produce a real violation, or "
                                    "this test cannot exercise the write path")
        record_read_provisioner_conformance(
            root, violations, from_version="v0.20.0", to_version="v0.21.0")

        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        self.assertIn(foreign, queue, "a foreign entry must survive untouched")
        self.assertTrue([e for e in queue
                         if e.get("kind") == "read_provisioner_missing"],
                        "the writer must actually have written")

    def test_a_missing_registration_records_a_blocking_entry_with_a_real_path(self):
        """The fallback path matters: an entry with an empty writer_relpath is
        invisible to the project-wide safety check, so a capability with no
        registered adapter would silently fail to block."""
        import json
        from upgrade_reconcile import (
            check_read_provisioner_conformance, record_read_provisioner_conformance,
        )
        root = self._project_with_capability(
            canonical_id="orphan", op_kind="orphan.op",
            adapter_name="adapters_orphan.py",
            adapter_source="# no registration at all\n")
        violations = check_read_provisioner_conformance(root)
        self.assertEqual([v.kind for v in violations], ["no_registered_adapter"])
        record_read_provisioner_conformance(
            root, violations, from_version="v0.20.0", to_version="v0.21.0")
        entry = [e for e in json.loads(
            (root / "agents" / "handoffs" / "pending_migrations.json")
            .read_text(encoding="utf-8"))
            if e.get("kind") == "no_registered_adapter"][0]
        self.assertEqual(entry["writer_relpath"],
                         "agents/capabilities/orphan_capability.py")
        self.assertTrue(entry["writer_relpath"], "must never be empty")
        self.assertEqual(entry["status"], "pending")
        self.assertIsNone(entry.get("paused_content_sha256"))
        self.assertIn("rebuild", entry["suggested_next_step"].lower())


class ReconcileUpgradeReadProvisionerConformanceTests(_Base):
    def test_reconcile_upgrade_runs_the_post_condition(self):
        """Bound at the engine entrypoint, not at a sub-function: this is the one
        funnel every upgrade path and the standalone reconcile command go
        through."""
        from upgrade_reconcile import reconcile_upgrade
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py",
            adapter_source=_LEGACY_MODULE_LEVEL)
        result = reconcile_upgrade(
            root, _REAL_REPO,
            from_version="v0.20.0", to_version="v0.21.0")
        self.assertEqual(result.read_provisioner_violations, [],
                         "the declared migration set should have fixed it, so "
                         "the post-condition must come back clean")

    def test_reconcile_upgrade_blocks_when_the_migration_cannot_fix_it(self):
        """The property that makes an enumeration bug non-fatal: with the module
        unmigratable (two registered classes, so the migration correctly
        refuses), the upgrade must end blocking rather than green."""
        import json
        from upgrade_reconcile import reconcile_upgrade
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py",
            adapter_source=_LEGACY_MODULE_LEVEL.replace(
                "register_adapter(OP_KIND, InboxLabelsAdapter())\n",
                "class OtherAdapter:\n    pass\n\n\n"
                "register_adapter(OP_KIND, InboxLabelsAdapter())\n"
                "register_adapter('other.op', OtherAdapter())\n"))
        result = reconcile_upgrade(
            root, _REAL_REPO,
            from_version="v0.20.0", to_version="v0.21.0")
        self.assertEqual(len(result.read_provisioner_violations), 1)
        queue = json.loads(
            (root / "agents" / "handoffs" / "pending_migrations.json")
            .read_text(encoding="utf-8"))
        self.assertTrue([e for e in queue
                         if e.get("kind") == "read_provisioner_missing"])


class AdapterMigrationRefusalRoutingTests(_Base):
    """A migration that DECLINES to act must say so somewhere durable. Before
    this, a refusal existed only as an in-memory ``AdapterMigrationOutcome``
    -- the reason that matters most, "found more than one registered adapter
    class, move it by hand", was a dead end for a non-technical operator
    unless it landed somewhere durable and visible."""

    def test_a_migration_refusal_reaches_the_repair_queue(self):
        """A migration that declines to act must say so somewhere durable. The
        refusal that mattered most here -- 'found 2 registered classes, move it
        by hand' -- is a dead end at the non-technical bar if it only ever
        existed as a return value nobody recorded."""
        import json
        from upgrade_reconcile import reconcile_upgrade
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py",
            adapter_source=_LEGACY_MODULE_LEVEL.replace(
                "register_adapter(OP_KIND, InboxLabelsAdapter())\n",
                "class OtherAdapter:\n    pass\n\n\n"
                "register_adapter(OP_KIND, InboxLabelsAdapter())\n"
                "register_adapter('other.op', OtherAdapter())\n"))
        reconcile_upgrade(root, _REAL_REPO,
                          from_version="v0.20.0", to_version="v0.21.0")
        queue = json.loads(
            (root / "agents" / "handoffs" / "pending_migrations.json")
            .read_text(encoding="utf-8"))
        refusals = [e for e in queue
                    if e.get("kind") == "adapter_migration_refused"]
        self.assertTrue(refusals, f"no refusal recorded: {queue}")
        self.assertIn("module_level_provisioner", refusals[0]["migration_name"])
        self.assertTrue(refusals[0]["reason"])
        self.assertEqual(refusals[0]["status"], "pending")

    def test_a_nothing_to_do_outcome_is_not_queued_as_a_refusal(self):
        """'Nothing to do' is not a refusal. Queueing it would put a blocking
        entry in every already-correct project -- a guard that always fires."""
        import json
        from upgrade_reconcile import reconcile_upgrade
        migrated = _LEGACY_MODULE_LEVEL.replace(
            "def build_read_only_client() -> Any:\n    return object()\n\n\n", ""
        ).replace(
            "class InboxLabelsAdapter:\n",
            "class InboxLabelsAdapter:\n"
            "    def build_read_only_client(self, op) -> Any:\n"
            "        return object()\n\n")
        root = self._project_with_capability(
            canonical_id="inbox_management", op_kind="inbox.labels.modify",
            adapter_name="adapters_inbox.py", adapter_source=migrated)
        reconcile_upgrade(root, _REAL_REPO,
                          from_version="v0.20.0", to_version="v0.21.0")
        queue_path = (root / "agents" / "handoffs" / "pending_migrations.json")
        queue = json.loads(queue_path.read_text(encoding="utf-8")) \
            if queue_path.exists() else []
        self.assertEqual(
            [e for e in queue if e.get("kind") == "adapter_migration_refused"],
            [])


if __name__ == "__main__":
    unittest.main()
