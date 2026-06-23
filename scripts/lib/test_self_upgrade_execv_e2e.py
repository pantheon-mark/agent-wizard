"""REAL end-to-end test of `wizard self-upgrade --to <v> --apply` ACROSS the os.execv re-exec.

What makes this test different from the other self-upgrade tests in this suite: it does NOT
inject `exec_fn` / `apply_fn` stubs. It drives the ACTUAL command through `subprocess.run`, so the
real `os.execv` re-execution runs. That exec replaces the spawned CHILD process (the subprocess),
NOT this test runner, so it is completely safe — and it is the whole point. The child process is
the running engine that re-execs itself; the test observes the result after the child exits.

It runs FULLY OFFLINE against a LOCAL git upstream (no network is touched):

  * The upstream is a real local git repo with two commits. BOTH commits carry a complete copy of
    the real wizard toolkit (`scripts/` engine + `lib/`, `registry/`, and `foundation-bundles/`),
    so the engine that runs in phase 1 AND the engine that runs in the re-exec'd phase 2 both
    contain the `self-upgrade` code and can resolve every bundle. The second commit additionally
    carries a trivial marker file, so it is a distinct descendant commit and the self-update's
    lineage gate is satisfied.
  * The toolkit is a clone of the upstream with `origin` set to the canonical public URL (the
    self-update verify gate compares to it), a `local` remote pointing at the upstream (the
    `--fetch-remote local` source), checked out at the BASE commit so the upgrade is "available".
  * The operator project is a REAL emit of a complete system on the FROM version, with its update
    source pinned (last-known-good = base) and the approved `.wizard/update-resolution.json`
    PRE-SEEDED so phase 1's emit step is SKIPPED and no `git ls-remote` / network registry fetch
    happens. The resolution is built directly from the upstream-target registry text + the target
    bundle entry, so the content gate's recomputed hashes match what was approved.

The two-phase flow exercised end-to-end:
  PHASE 1 (toolkit at base): matching resolution already present -> emit skipped -> self-update the
    toolkit to the exact approved commit -> os.execv re-runs the SAME argv with a fresh process.
  PHASE 2 (the re-exec'd child, toolkit now at the approved commit): matching resolution present ->
    emit skipped -> content gate re-validated -> apply_upgrade runs with the freshly-checked-out
    engine and the target bundle.

COVERAGE — honest statement of what this proves:
  * The real `os.execv` crossing happens in a fresh child process and phase 2 is RE-ENTERED by the
    re-exec'd engine. This is the must-have, and it is proven directly: the toolkit HEAD advances to
    the approved commit (phase 1 self-update ran) AND the operator system is genuinely upgraded by
    the phase-2 engine (manifest foundation_bundle_version advances to the target, upgrade history is
    appended, a pre-upgrade backup exists) — none of which a phase-1-only run could produce.
  * The phase-2 `apply_upgrade` returns the `applied` result on a clean, unedited emit: the
    operating-layer delta lands, every foundation document the target does not change stays
    byte-identical to its pre-upgrade content, and the command exits 0. The foundation docs being
    byte-identical pre/post is asserted on the live operator files, so a silent corruption would
    fail the test.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # wizard/scripts (interview_cli)

import interview_cli as cli  # noqa: E402
from update_source import (  # noqa: E402
    UPDATE_SOURCE_REL,
    CANONICAL_HTTPS_URL,
    render_update_source_json,
)
from update_resolution import (  # noqa: E402
    UPDATE_RESOLUTION_REL,
    build_update_resolution,
    write_update_resolution,
)
from upgrade import (  # noqa: E402
    load_registry,
    find_bundle_entry,
    load_operator_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
WIZARD_DIR = REPO_ROOT / "wizard"
REGISTRY_PATH = WIZARD_DIR / "registry" / "foundation-bundles.json"
TRANSCRIPT = Path.home() / "wizard-pilot-2026-06-01" / "wizard_transcript.jsonl"
SHAPE = "markdown-CC"

FROM_VERSION = "v0.6.0"     # the operator starts here (a full v2-capsule emit)
TARGET_VERSION = "v0.6.1"   # the operating-layer delta the operator upgrades to

# A real 40-char SHA so the emit does not require a clean build worktree (opaque to the
# assertions; only a stable generator identity recorded in the emitted manifest + capsule).
_GEN_OVERRIDE = "c3b5609fbbe566d73f3097ff0d1cd087dfe19245"

# The six classic foundation documents — byte-identical across an operating-layer-only delta.
_FOUNDATION_DOCS = (
    "vision.md", "approach.md", "technical_architecture.md",
    "execution_plan.md", "test_cases.md", "audit_framework.md",
)


def _run(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True)


def _git(cwd, *args):
    return _run(cwd, "git", *args)


def _head(repo):
    return _run(repo, "git", "rev-parse", "HEAD").stdout.strip()


def _copy_toolkit(dest: Path) -> None:
    """Copy the real wizard toolkit (engine + lib + registry + foundation bundles) into `dest`,
    excluding bytecode caches so the child process imports the copied source, not stale bytecode."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for sub in ("scripts", "registry", "foundation-bundles"):
        shutil.copytree(WIZARD_DIR / sub, dest / sub, ignore=ignore)


def _have_prereqs() -> bool:
    if not TRANSCRIPT.exists():
        return False
    try:
        reg = load_registry(REGISTRY_PATH)
    except Exception:
        return False
    versions = {e.get("foundation_bundle_version") for e in reg.get("bundles", [])}
    return {FROM_VERSION, TARGET_VERSION} <= versions


@unittest.skipUnless(
    _have_prereqs(),
    f"requires the preserved pilot transcript at {TRANSCRIPT} and both "
    f"{FROM_VERSION} + {TARGET_VERSION} registered bundles",
)
class SelfUpgradeExecvE2E(unittest.TestCase):
    """Drive `wizard self-upgrade --to <v> --apply` through a subprocess so the REAL os.execv
    re-exec is exercised, fully offline against a local git upstream."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

        # --- upstream: a local git repo carrying the full toolkit at BOTH commits. ---
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        _git(self.upstream, "init", "-q")
        _git(self.upstream, "config", "user.email", "t@t.t")
        _git(self.upstream, "config", "user.name", "t")
        _git(self.upstream, "checkout", "-q", "-b", "main")
        _copy_toolkit(self.upstream)
        _git(self.upstream, "add", "-A")
        _git(self.upstream, "commit", "-q", "-m", "base toolkit")
        self.base_commit = _head(self.upstream)

        # Target commit = a distinct descendant (a trivial marker change). The toolkit content is
        # identical to base, so both the base and target engines carry self-upgrade + every bundle.
        (self.upstream / "TARGET_MARKER.txt").write_text("target\n", encoding="utf-8")
        _git(self.upstream, "add", "-A")
        _git(self.upstream, "commit", "-q", "-m", "target marker")
        self.target_commit = _head(self.upstream)

        # The TARGET registry text + entry the resolution binds (read from the upstream target).
        target_reg_path = self.upstream / "registry" / "foundation-bundles.json"
        self.target_reg_text = target_reg_path.read_text(encoding="utf-8")
        self.target_entry = find_bundle_entry(
            json.loads(self.target_reg_text), TARGET_VERSION)
        self.assertIsNotNone(self.target_entry, "target bundle absent from the upstream registry")

        # --- toolkit: clone of upstream; origin = canonical (verify compares to it), local remote
        #     = upstream, checked out at BASE so the update is "available". ---
        self.toolkit = self.root / "agent-wizard"
        _git(self.root, "clone", "-q", str(self.upstream), str(self.toolkit))
        _git(self.toolkit, "config", "user.email", "t@t.t")
        _git(self.toolkit, "config", "user.name", "t")
        _git(self.toolkit, "remote", "add", "local", str(self.upstream))
        _git(self.toolkit, "remote", "set-url", "origin", CANONICAL_HTTPS_URL)
        _git(self.toolkit, "checkout", "-q", self.base_commit)
        self.assertEqual(_head(self.toolkit), self.base_commit)

        # --- operator: a REAL emit on the FROM version. ---
        self.operator = self.root / "estate"
        cli.cmd_emit_system(
            str(TRANSCRIPT), SHAPE, str(self.operator), str(REPO_ROOT),
            bundle_version=FROM_VERSION,
            generator_version_override=_GEN_OVERRIDE,
        )
        manifest_path = self.operator / ".wizard" / "manifest.json"
        self.assertTrue(manifest_path.exists())
        self.assertTrue((self.operator / ".wizard" / "replay-capsule.json").exists())
        m = json.loads(manifest_path.read_text())
        self.assertEqual(m["foundation_bundle_version"], FROM_VERSION)

        # Pin the operator's update source (last-known-good = base commit).
        (self.operator / UPDATE_SOURCE_REL).write_text(
            render_update_source_json(last_known_good_commit=self.base_commit),
            encoding="utf-8")

        # PRE-SEED the approved resolution, built from the TARGET registry text + entry and the
        # operator's CURRENT manifest. Phase 1 will find this matching resolution and SKIP the emit
        # step (no git ls-remote, no network registry fetch). The content gate at phase 2 recomputes
        # the registry/bundle/manifest hashes and matches them against this resolution.
        resolution = build_update_resolution(
            operator_project_dir=self.operator,
            registry_raw_text=self.target_reg_text,
            source_url="https://x/registry/foundation-bundles.json",
            source_origin_id="github:pantheon-mark/agent-wizard",
            source_ref="main",
            entry=self.target_entry,
            from_version=FROM_VERSION,
            target_public_commit_sha=self.target_commit,
            min_engine_version="", checked_engine_version="",
            checked_at="2026-06-23T00:00:00Z",
        )
        write_update_resolution(self.operator, resolution)

    def tearDown(self):
        self._tmp.cleanup()

    def _file_bytes(self, root: Path) -> dict:
        """relpath -> bytes for every file, excluding the backup subtree (a transaction detail)."""
        return {
            str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*")
            if p.is_file() and ".wizard/backups" not in str(p)
        }

    def _invoke(self):
        """Invoke the TOOLKIT's own engine (the one that re-execs itself) via subprocess."""
        engine = self.toolkit / "scripts" / "wizard_upgrade.py"
        manifest_path = self.operator / ".wizard" / "manifest.json"
        registry_path = self.toolkit / "registry" / "foundation-bundles.json"
        return subprocess.run(
            [
                sys.executable, str(engine),
                "self-upgrade", "--to", TARGET_VERSION, "--apply",
                "--fetch-remote", "local",
                "--toolkit-dir", str(self.toolkit),
                "--operator-dir", str(self.operator),
                "--manifest-path", str(manifest_path),
                "--registry-path", str(registry_path),
            ],
            capture_output=True, text=True, timeout=120,
            # A clean environment with no inherited PYTHONPATH so the child resolves its imports
            # from the toolkit copy's own scripts/ + lib/ (the engine wires both onto sys.path).
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        )

    def test_real_execv_crosses_phases_and_apply_succeeds(self):
        """The command, driven via subprocess, really os.execv re-execs and the re-exec'd phase-2
        engine applies the upgrade. Asserts the full crossing AND a genuine `applied` outcome."""
        manifest_path = self.operator / ".wizard" / "manifest.json"

        # Snapshot the operator's foundation docs before the upgrade (live bytes).
        before = self._file_bytes(self.operator)
        for rel in _FOUNDATION_DOCS:
            self.assertIn(rel, before, f"{rel} missing from the emitted operator project")

        proc = self._invoke()

        # Exit 0 = the phase-2 apply completed cleanly (NOT the phase-1 `execed` stub path, which
        # never runs in production — the real os.execv replaced the child process image).
        self.assertEqual(
            proc.returncode, 0,
            f"self-upgrade did not exit 0.\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        # PHASE 1 ran: the toolkit was self-updated to the EXACT approved commit (only phase 1
        # advances HEAD; a phase-1-only failure would have refused before exec and left HEAD here).
        self.assertEqual(
            _head(self.toolkit), self.target_commit,
            f"toolkit HEAD did not advance to the approved commit.\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )

        # PHASE 2 ran in the re-exec'd engine: the operator system was genuinely UPGRADED. None of
        # these observables can be produced by phase 1 (which only touches the toolkit dir).
        m_after = json.loads(manifest_path.read_text())
        self.assertEqual(
            m_after["foundation_bundle_version"], TARGET_VERSION,
            f"operator manifest not advanced to the target (phase 2 did not apply).\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )
        history = self.operator / ".wizard" / "upgrade-history.log"
        self.assertTrue(history.exists(), "no upgrade history written (phase 2 apply did not run)")
        self.assertIn(f"{FROM_VERSION} -> {TARGET_VERSION}", history.read_text())
        self.assertTrue(
            (self.operator / ".wizard" / "backups" / f"pre-{TARGET_VERSION}").exists(),
            "no pre-upgrade backup (phase 2 apply did not run)",
        )

        # The apply genuinely DELIVERED: the operating-layer delta the target carries landed on disk
        # (the new operating skill that does not exist on a FROM-version emit).
        self.assertTrue(
            (self.operator / "wizard" / "skills" / "check-for-updates.md").exists(),
            "the target's new operating skill was not delivered (phase 2 apply incomplete)",
        )

        # The foundation documents the operating-layer delta does NOT change are byte-identical
        # to their pre-upgrade content on the LIVE operator files (a silent corruption fails here).
        after = self._file_bytes(self.operator)
        for rel in _FOUNDATION_DOCS:
            self.assertEqual(
                after.get(rel), before.get(rel),
                f"foundation doc {rel} changed during the operating-layer upgrade",
            )

    def test_rerun_after_apply_fails_closed_without_regressing(self):
        """Safety / re-run behavior: after a successful upgrade, the toolkit is already at the
        approved commit, so a SECOND invocation enters phase 2 directly (no second self-update, no
        os.execv). The content gate then correctly REFUSES — the approved resolution bound the
        operator's manifest state at approve time, and that state legitimately changed when the first
        apply advanced the operator to the target. This is the desired fail-closed behavior, not a
        bug: re-applying a stale approval must not proceed. The point proven here is that the refusal
        is CLEAN — the operator system is left at the target version (the first apply stands) and the
        toolkit HEAD does not regress. (A fresh re-approval would mint a new resolution bound to the
        new state; that re-approval cycle is exercised elsewhere in the suite.)"""
        manifest_path = self.operator / ".wizard" / "manifest.json"

        first = self._invoke()
        self.assertEqual(first.returncode, 0, f"first run failed.\n{first.stdout}\n{first.stderr}")
        self.assertEqual(_head(self.toolkit), self.target_commit)
        self.assertEqual(
            json.loads(manifest_path.read_text())["foundation_bundle_version"], TARGET_VERSION)

        # Second run: toolkit already at target -> phase 2 directly. The content gate refuses on the
        # changed operator state. Refusal is exit 1; nothing regresses.
        second = self._invoke()
        self.assertEqual(
            second.returncode, 1,
            f"expected a clean fail-closed refusal (exit 1) on the stale-resolution re-run.\n"
            f"STDOUT:\n{second.stdout}\nSTDERR:\n{second.stderr}",
        )
        self.assertIn("content gate failed", second.stderr,
                      "refusal was not the content-gate fail-closed path")
        # Nothing regressed: the first apply stands, the toolkit HEAD is unchanged.
        self.assertEqual(_head(self.toolkit), self.target_commit,
                         "toolkit HEAD regressed on the refused re-run")
        self.assertEqual(
            json.loads(manifest_path.read_text())["foundation_bundle_version"], TARGET_VERSION,
            "operator manifest regressed on the refused re-run")


if __name__ == "__main__":
    unittest.main()
