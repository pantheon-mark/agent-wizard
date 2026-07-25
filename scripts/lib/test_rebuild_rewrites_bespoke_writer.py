"""Task D / Cut 1.5 (bundle v0.19.0) -- the rebuild remediation must rewrite the
ACTUAL flagged bespoke WRITER onto ``run_sanctioned_bulk`` (not just regenerate
the capability wrapper), so Task B's stateless auto-reap then clears the
migration entry and Task C's acceptance gate lets the capability go live again.

The gap this closes (source-verified, F-VAL18-1 recurrence): a contract-changing
upgrade safe-pauses a hand-authored bespoke writer (the estate shape:
``agents/inbox/runner.py`` with a per-chunk ``mint_run_envelope`` bulk loop) and
queues a migration entry keyed on its ``writer_relpath``. The rebuild skill's
no-``kind`` branch used to only re-run ``capability_code_scaffold.py --spec``,
which REGENERATES THE CAPABILITY WRAPPER MODULE -- a DIFFERENT file. The flagged
bespoke writer was never touched, so after a "faithful" rebuild the per-chunk
mint loop was STILL there and V15-3 stayed open.

The fork (resolved -> agent-driven rewrite + deterministic tested support): a
bespoke writer is HAND-AUTHORED, so a spec-driven full regeneration (or a blind
surgical AST rewrite) would DESTROY its custom domain logic. Instead the SKILL
instructs the agent to rewrite the flagged writer file's BULK PATH onto the
sanctioned entrypoint (exactly as the ``missing_evidence_predicates`` branch has
the agent author real code), and ``capability_code_scaffold.py`` provides the
DETERMINISTIC, UNIT-TESTABLE canonical pattern the skill points at:
``render_sanctioned_bulk_writer_reference``.

This test encodes the acceptance criteria against that deterministic surface:
given a fixture bespoke writer with a per-chunk mint loop, the rendered
remediation reference (a) calls ``run_sanctioned_bulk``, (b) has NO residual
``mint_run_envelope`` per-chunk loop, (c) passes the NON-quarantined
``scan_paths`` -- the exact predicate Task B's reap uses -- and, end-to-end,
Task B's reap actually clears the entry once the writer is that shape. Plus the
F-VAL18-2 fold: the rebuild skill runs dependency enrollment BEFORE its proof.

Run:  python3 -m unittest -v \\
          wizard.scripts.lib.test_rebuild_rewrites_bespoke_writer
      (or discover -s wizard/scripts/lib -p test_rebuild_rewrites_bespoke_writer.py)
"""

import ast
import hashlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AGENTS_LIB = _REPO_ROOT / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from external_write import scan  # noqa: E402
from external_write import _ext_write_state  # noqa: E402

import capability_code_scaffold as ccs  # noqa: E402
from capability_code_scaffold import (  # noqa: E402
    CapabilityCodeSpec,
    render_capability_module,
    render_sanctioned_bulk_writer_reference,
)

SKILL_PATH = _REPO_ROOT / "wizard" / "skills" / "rebuild-paused-capability.md"

# The estate's real shape: a hand-rolled per-chunk mint loop OUTSIDE
# agents/capabilities/, importing mint_run_envelope directly from run_envelope
# (a SEALED_KERNEL submodule NOT on the CAPABILITY allowlist) -- doubly
# scanner-RED (sealed_kernel_import + the raw bulk-mint name ban). Kept
# byte-aligned with test_writer_migration_autoreap.py's own fixture.
BESPOKE_WRITER_RELPATH = "agents/inbox/runner.py"
BESPOKE_MECHANISM_ID = "runner"
_BESPOKE_WRITER_SRC = '''"""Hand-rolled per-chunk bulk writer -- bypasses run_sanctioned_bulk."""
from external_write.run_envelope import mint_run_envelope


def run_all(chunks):
    results = []
    for chunk in chunks:
        env = mint_run_envelope(chunk)
        results.append(env)
    return results
'''


def _sample_spec(**overrides) -> CapabilityCodeSpec:
    kwargs = dict(
        capability_id="record_sync",
        display_name="Record sync",
        op_kind="record.archive",
        surface="record_store",
        read_only_scope="record_store.readonly",
        blast_radius_cap=10,
        read_methods=("list_records", "get_record"),
    )
    kwargs.update(overrides)
    return CapabilityCodeSpec(**kwargs)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run_sanctioned_bulk_call_kwargs(module_source: str):
    """The set of keyword-argument NAMES the module's single
    ``run_sanctioned_bulk(...)`` call passes -- used to pin the reference's
    canonical call against the capability wrapper's own so the two can never
    silently drift apart."""
    tree = ast.parse(module_source)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "run_sanctioned_bulk"):
            return {kw.arg for kw in node.keywords if kw.arg is not None}
    return None


class TestSanctionedBulkWriterReferenceRenders(unittest.TestCase):
    """The deterministic surface: render_sanctioned_bulk_writer_reference."""

    def setUp(self):
        self.spec = _sample_spec()
        self.reference = render_sanctioned_bulk_writer_reference(self.spec)

    def test_reference_parses_as_valid_python(self):
        ast.parse(self.reference)

    # -- acceptance (a): the produced writer CALLS run_sanctioned_bulk --------

    def test_a_calls_run_sanctioned_bulk(self):
        self.assertIn("run_sanctioned_bulk(", self.reference)
        tree = ast.parse(self.reference)
        called = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "run_sanctioned_bulk"
            for n in ast.walk(tree))
        self.assertTrue(called, "the rendered writer must call run_sanctioned_bulk")
        # ...reached via the curated CAPABILITY-zone surface, never the raw kernel.
        self.assertIn("from external_write.capability_api import run_sanctioned_bulk",
                      self.reference)

    # -- acceptance (b): NO residual per-chunk mint loop ----------------------

    def test_b_no_residual_mint_run_envelope_per_chunk_loop(self):
        # The whole bypass class is the per-chunk mint loop. The rendered writer
        # must not name the raw bulk-mint primitives at all -- so no loop can
        # re-create it.
        self.assertNotIn("mint_run_envelope", self.reference)
        self.assertNotIn("new_bulk_run_id", self.reference)
        # ...and it must not import the sealed-kernel run_envelope submodule the
        # estate hand-rolled its loop from.
        self.assertNotIn("external_write.run_envelope", self.reference)

    # -- acceptance (c): passes the NON-quarantined scan_paths ----------------

    def test_c_produced_writer_passes_non_quarantined_scan(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer_path = root / BESPOKE_WRITER_RELPATH
            _write(writer_path, self.reference)
            # Mirror the reap's EXACT call: defaults (no project_root => the
            # F-3B quarantine plays no part; strict, unconditional scan).
            violations = scan.scan_paths([str(writer_path)])
            self.assertEqual(
                violations, [],
                f"rendered writer must pass the non-quarantined scan, got: {violations}")

    def test_c_baseline_bespoke_writer_FAILS_the_same_scan(self):
        # Proves the transform is meaningful: the fixture it replaces is RED on
        # the same scan the produced writer passes.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer_path = root / BESPOKE_WRITER_RELPATH
            _write(writer_path, _BESPOKE_WRITER_SRC)
            violations = scan.scan_paths([str(writer_path)])
            self.assertTrue(
                violations,
                "the per-chunk-mint bespoke writer must be scanner-RED (else this "
                "test proves nothing about the transform)")

    # -- end-to-end: Task B's reap actually clears the entry for this shape ----

    def test_reap_clears_entry_once_writer_is_this_shape(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / BESPOKE_WRITER_RELPATH, self.reference)
            entry = {
                "mechanism_id": BESPOKE_MECHANISM_ID,
                "writer_relpath": BESPOKE_WRITER_RELPATH,
                "entrypoint_relpath": None,
                "status": "pending",
                "reason": "flagged non-conformant with the external-write gate on upgrade",
                # pause-time hash is the OLD bespoke content: current != recorded
                # AND the file now scans clean -> reaped.
                "paused_content_sha256": _sha256(_BESPOKE_WRITER_SRC),
            }
            _write(root / "agents" / "handoffs" / "pending_migrations.json",
                   json.dumps([entry], indent=2))
            self.assertEqual(len(_ext_write_state.open_bespoke_writer_migrations(str(root))), 1)

            reaped = _ext_write_state.reap_resolved_writer_migrations(str(root))

            self.assertEqual(reaped, [BESPOKE_MECHANISM_ID])
            self.assertEqual(
                len(_ext_write_state.open_bespoke_writer_migrations(str(root))), 0,
                "once the flagged writer is rewritten onto the rendered sanctioned-bulk "
                "shape, Task B's reap must clear its migration entry")

    # -- no-drift guard: reference's canonical call == capability wrapper's ----

    def test_reference_bulk_call_matches_capability_wrapper(self):
        ref_kwargs = _run_sanctioned_bulk_call_kwargs(self.reference)
        cap_kwargs = _run_sanctioned_bulk_call_kwargs(render_capability_module(self.spec))
        self.assertIsNotNone(ref_kwargs, "reference must contain a run_sanctioned_bulk call")
        self.assertIsNotNone(cap_kwargs, "capability wrapper must contain a run_sanctioned_bulk call")
        self.assertEqual(
            ref_kwargs, cap_kwargs,
            "the remediation reference and the emitted capability wrapper must pass the "
            "IDENTICAL run_sanctioned_bulk call shape -- if they drift, the pattern the "
            "skill points the agent at stops matching the one the gate proves clean")


class TestRebuildSkillWiring(unittest.TestCase):
    """Skill-content acceptance: the no-kind branch rewrites the flagged WRITER
    file, and dependency enrollment runs BEFORE the proof (F-VAL18-2)."""

    def setUp(self):
        self.assertTrue(SKILL_PATH.is_file(), f"expected {SKILL_PATH} to exist")
        self.text = SKILL_PATH.read_text(encoding="utf-8")

    def test_no_kind_branch_rewrites_the_flagged_writer_file(self):
        # Must name the writer FILE (from the entry's writer_relpath), route it
        # onto run_sanctioned_bulk, and remove the per-chunk mint loop.
        self.assertIn("writer_relpath", self.text)
        self.assertIn("run_sanctioned_bulk", self.text)
        lower = self.text.lower()
        self.assertIn("mint", lower,
                      "the branch must name the per-chunk mint loop it removes")

    def test_dependency_enrollment_runs_before_the_proof(self):
        self.assertIn("dependency_enrollment.py", self.text)
        idx_dep = self.text.index("dependency_enrollment.py")
        idx_proof = self.text.index("copy_run_proof")
        self.assertLess(
            idx_dep, idx_proof,
            "dependency enrollment must run BEFORE the copy-run proof (F-VAL18-2), "
            "so a clean-session proof imports the vendor SDK -- mirroring next-phase")


if __name__ == "__main__":
    unittest.main()
