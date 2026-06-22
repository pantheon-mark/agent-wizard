"""Held-out END-TO-END safety proof for the operating-layer upgrade path.

This is the synthetic-but-real gate that must pass BEFORE the operating-layer
upgrade mechanism is pointed at a live operator project. Nothing here is mocked:
the bundles, their managed-artifacts contracts, the replay capsule, the manifest,
and the merge/apply transaction are all the real artifacts the wizard ships. The
test exercises two regimes on real emits:

  Regime A — additive delivery to a "lacking" foundation-only (v1-capsule) system:
    emit a foundation-only system on v0.4.0 (v1 capsule), then apply the full
    v0.6.0 system bundle (foundation docs + operating layer + managed-artifacts
    contract). The operating layer is NEW to this system, so it must be delivered
    additively where it can be (copy-kind files: scripts/settings/skills) and
    SURFACED-not-crashed where it cannot (render-kind operating files that need an
    operating block the v1 capsule does not carry -> needs_capsule_upgrade).

  Regime B — full delivery + edit-protection + tamper-refusal on a v2-capsule
    system: emit a full v0.6.0 system (v2 capsule) then apply v0.6.1 (an
    operating-layer-only delta: an additive section in an operating render doc, a
    one-line copy-skill change, and a brand-new skill).

ANTI-FALSE-GREEN: every delivery assertion checks the EXACT filesystem path SET
(new copy files created; render files surfaced-not-written; foundation docs
byte-identical), never merely `classification == applied`. A silent drop fails the
test.

============================================================================
FINDING (surfaced by this proof; see the slice report) — the operating-layer
upgrade does NOT yet deliver on a real v2->v2 emit. The v2 replay capsule's
`operating` block carries only the PERSISTED render inputs (by design it excludes
`derived` keys, meaning to re-derive them at upgrade time) — but the apply path's
operating-layer render loop (step 4c) does NOT re-derive them; it substitutes from
the capsule alone. So ~half the in-manifest operating render files (.gitignore,
CLAUDE.md, project_instructions.md, session_bootstrap.md, ...) reference keys the
capsule lacks, and the apply REFUSES (fail-closed) the moment step 4c reaches the
first such file. The positive Regime-B delivery + edit-protection properties
therefore CANNOT yet be proven on a real emit; this test asserts the CURRENT real
behavior (a clean refusal with ZERO writes) and is marked with explicit FINDING
docstrings so the gap is not mistaken for a passing delivery path. Closing the gap
(persist the full resolved render-input map in the capsule, or wire re-derivation
into step 4c) is a follow-on slice; the tamper-refusal property is independent of
the gap and IS proven here.
============================================================================
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # wizard/scripts (interview_cli)

import interview_cli as cli  # noqa: E402
from upgrade import (  # noqa: E402
    load_operator_manifest,
    load_registry,
)
from upgrade_apply import (  # noqa: E402
    apply_upgrade,
    UpgradeApplyError,
    APPLY_RESULT_APPLIED,
    APPLY_RESULT_PARTIAL,
    SURFACE_NEW,
    SURFACE_NEEDS_CAPSULE,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"
TRANSCRIPT = Path.home() / "wizard-pilot-2026-06-01" / "wizard_transcript.jsonl"
SHAPE = "markdown-CC"
FOUNDATION_ONLY_VERSION = "v0.4.0"   # v1 capsule (no operating block)
FULL_VERSION = "v0.6.0"              # v2 capsule (operating block)
OPERATING_DELTA_VERSION = "v0.6.1"   # operating-layer-only delta over v0.6.0
# A real 40-char SHA so emit does not require a clean worktree (the bundle cut leaves
# the tree dirty). Opaque to the assertions; only a stable generator identity.
_GEN_OVERRIDE = "c3b5609fbbe566d73f3097ff0d1cd087dfe19245"

# The six classic foundation documents — must be byte-identical across an operating
# upgrade (a foundation-bundle delta is byte-identical to v0.4.0 in v0.6.x).
_FOUNDATION_DOCS = (
    "vision.md", "approach.md", "technical_architecture.md",
    "execution_plan.md", "test_cases.md", "audit_framework.md",
)

# Operating-layer render files the v0.6.0 contract carries that a v1-capsule (v0.4.0)
# system CANNOT replay -> must be surfaced needs_capsule_upgrade, never written.
_RENDER_OPERATING_SAMPLE = (
    "CLAUDE.md", "operating_discipline.md", "project_instructions.md",
)

# Copy-kind operating files the v0.6.0 contract carries that ARE deliverable additively
# to a v0.4.0 system (verbatim from the bundle; no operator inputs to replay).
_COPY_OPERATING_SH = (
    ".claude/context_monitor.sh", ".claude/receipt_gate.sh", ".claude/statusline.sh",
)
_COPY_OPERATING_OTHER = (".claude/settings.json",)
_COPY_OPERATING_SKILLS = (
    "wizard/skills/_index.md", "wizard/skills/credential-setup.md",
    "wizard/skills/next-phase.md", "wizard/skills/orientation.md",
    "wizard/skills/pause.md", "wizard/skills/skill_template_external.md",
    "wizard/skills/skill_template_internal.md",
)


def _have_prereqs() -> bool:
    if not TRANSCRIPT.exists():
        return False
    try:
        reg = load_registry(REGISTRY_PATH)
    except Exception:
        return False
    versions = {e.get("foundation_bundle_version") for e in reg.get("bundles", [])}
    return {FOUNDATION_ONLY_VERSION, FULL_VERSION, OPERATING_DELTA_VERSION} <= versions


@unittest.skipUnless(
    _have_prereqs(),
    f"requires the preserved pilot transcript at {TRANSCRIPT} and the "
    f"{FOUNDATION_ONLY_VERSION} + {FULL_VERSION} + {OPERATING_DELTA_VERSION} bundles",
)
class OperatingLayerUpgradeE2E(unittest.TestCase):
    """Real emit -> real apply over the operating-layer upgrade path."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    # ---- helpers ----------------------------------------------------------

    def _emit(self, name: str, version: str) -> Path:
        proj = self.tmp / name
        cli.cmd_emit_system(
            str(TRANSCRIPT), SHAPE, str(proj), str(REPO_ROOT),
            bundle_version=version,
            generator_version_override=_GEN_OVERRIDE,
        )
        self.assertTrue((proj / ".wizard" / "manifest.json").exists())
        self.assertTrue((proj / ".wizard" / "replay-capsule.json").exists())
        m = json.loads((proj / ".wizard" / "manifest.json").read_text())
        self.assertEqual(m["foundation_bundle_version"], version)
        return proj

    def _apply(self, proj: Path, target: str, *, ack=False):
        mp = proj / ".wizard" / "manifest.json"
        return apply_upgrade(
            proj, target, REPO_ROOT,
            registry=load_registry(REGISTRY_PATH), registry_path=REGISTRY_PATH,
            manifest=load_operator_manifest(mp), manifest_path=mp,
            ack=ack,
        )

    def _file_bytes(self, proj: Path) -> dict:
        """Map relpath -> bytes for every file, excluding the backup subtree (its
        contents are an implementation detail of the transaction)."""
        return {
            str(p.relative_to(proj)): p.read_bytes()
            for p in proj.rglob("*")
            if p.is_file() and ".wizard/backups" not in str(p)
        }

    def _capsule_schema(self, proj: Path) -> str:
        return json.loads(
            (proj / ".wizard" / "replay-capsule.json").read_text()
        )["schema_version"]

    # ======================================================================
    # Regime A — additive delivery to a foundation-only (v1-capsule) system.
    # ======================================================================

    def test_regimeA_additive_operating_delivery_to_v1_capsule_system(self):
        """A v0.4.0 (foundation-only, v1-capsule) system upgrading to v0.6.0:
        - copy-kind operating files are CREATED additively (exact set; .sh mode 0755);
        - render-kind operating files are SURFACED needs_capsule_upgrade, NOT written;
        - foundation docs are byte-identical;
        - the outcome is PARTIAL (not a false `applied`) because render-kind operating
          files went undelivered."""
        proj = self._emit("estate-v1", FOUNDATION_ONLY_VERSION)
        self.assertEqual(self._capsule_schema(proj),
                         "replay-capsule-v1",
                         "v0.4.0 emit must produce a v1 (foundation-only) capsule")

        before = self._file_bytes(proj)
        res = self._apply(proj, FULL_VERSION)

        self.assertNotEqual(res.classification, "refused", res.refusal_reason)
        after = self._file_bytes(proj)
        created = {
            f for f in (set(after) - set(before))
            if not f.startswith(".wizard/upgrade-review")
        }

        # ---- copy-kind operating files CREATED additively: EXACT path set ----
        expected_new_copy = (
            set(_COPY_OPERATING_SH) | set(_COPY_OPERATING_OTHER)
            | set(_COPY_OPERATING_SKILLS)
        )
        self.assertTrue(
            expected_new_copy <= created,
            f"copy operating files NOT all created additively; missing: "
            f"{sorted(expected_new_copy - created)}",
        )
        # Each created .sh is executable (0755).
        for sh in _COPY_OPERATING_SH:
            self.assertIn(sh, created)
            mode = stat.S_IMODE(os.stat(proj / sh).st_mode)
            self.assertEqual(mode, 0o755, f"{sh} not mode 0755 (got {oct(mode)})")
        # And those copy files are in files_written, not in review.
        for rel in expected_new_copy:
            self.assertIn(rel, res.files_written, f"{rel} not reported written")
            self.assertNotIn(rel, res.files_in_review)

        # ---- render-kind operating files SURFACED needs_capsule_upgrade, NOT written.
        needs_capsule = {
            se.relpath for se in res.surface
            if se.classification == SURFACE_NEEDS_CAPSULE
        }
        for rel in _RENDER_OPERATING_SAMPLE:
            self.assertIn(
                rel, needs_capsule,
                f"{rel} should be surfaced needs_capsule_upgrade on a v1-capsule system",
            )
            self.assertNotIn(rel, created, f"{rel} was written despite needing a capsule")
            self.assertFalse((proj / rel).exists(),
                             f"{rel} must NOT be on disk (no operating block to replay)")
            self.assertNotIn(rel, res.files_written)
        # Per-agent prompt render files are also surfaced, not written.
        agent_needs = [r for r in needs_capsule if r.startswith("agents/prompts/")]
        self.assertTrue(agent_needs, "agent prompt render files not surfaced needs_capsule")
        for rel in agent_needs:
            self.assertFalse((proj / rel).exists(), f"{rel} written despite needs_capsule")

        # ---- foundation docs byte-identical pre/post ----
        for rel in _FOUNDATION_DOCS:
            self.assertIn(rel, before)
            self.assertEqual(after.get(rel), before.get(rel),
                             f"foundation doc {rel} changed during operating upgrade")

        # ---- outcome reflects PARTIAL delivery (not a false applied) ----
        self.assertEqual(
            res.classification, APPLY_RESULT_PARTIAL,
            "delivering only the copy layer while render-kind operating files go "
            "undelivered must classify partial, not applied (false-green guard)",
        )

    def test_regimeA_control_plane_only_entry_does_not_block_the_whole_upgrade(self):
        """REGRESSION (FINDING, fixed in this slice). A `source: control_plane`
        contract entry (e.g. `.wizard/UPGRADING.md`) carries NO bundle template — it is
        produced by the Python emitter at setup, not bundle-sourced. The copy-write path
        must SKIP it; before the fix it tried to read a non-existent bundle template and
        refused the WHOLE v0.4.0 -> v0.6.0 upgrade, delivering nothing."""
        proj = self._emit("estate-cp", FOUNDATION_ONLY_VERSION)
        upgrading = proj / ".wizard" / "UPGRADING.md"
        before_upgrading = upgrading.read_bytes() if upgrading.exists() else None

        res = self._apply(proj, FULL_VERSION)  # must NOT raise
        self.assertNotEqual(res.classification, "refused", res.refusal_reason)
        # The control-plane file is left exactly as the emitter wrote it (not adopted,
        # not clobbered by a bundle read).
        if before_upgrading is not None:
            self.assertEqual(upgrading.read_bytes(), before_upgrading)
        # It is not reported as a written/bundle-sourced copy file.
        self.assertNotIn(".wizard/UPGRADING.md", res.files_written)

    # ======================================================================
    # Regime B — operating-layer delta on a full (v2-capsule) system.
    # ======================================================================

    def test_regimeB_v2_capsule_emit_is_v2_and_carries_operating_block(self):
        """Premise check for Regime B: a v0.6.0 emit is a FULL system with a v2 capsule
        (the operating block), and the operating layer is on disk (CLAUDE.md,
        operating_discipline.md, the new-target skills' siblings)."""
        proj = self._emit("estate-v2", FULL_VERSION)
        self.assertEqual(self._capsule_schema(proj), "replay-capsule-v2")
        cap = json.loads((proj / ".wizard" / "replay-capsule.json").read_text())
        self.assertIn("operating", cap)
        self.assertTrue((proj / "CLAUDE.md").exists())
        self.assertTrue((proj / "operating_discipline.md").exists())
        # The v0.6.1-new skill does NOT exist yet on a v0.6.0 emit (it is new in target).
        self.assertFalse((proj / "wizard" / "skills" / "health-check.md").exists())

    def test_regimeB_FINDING_operating_render_replay_gap_refuses_with_zero_writes(self):
        """FINDING (headline). On a real v0.6.0 -> v0.6.1 (v2 -> v2) apply, the operating
        upgrade REFUSES because the v2 capsule's operating block does not carry every key
        the in-manifest operating RENDER files reference (the apply path does not
        re-derive `derived` keys at step 4c). The refusal is fail-closed: ZERO writes,
        rollback clean, no review sidecars. This asserts the CURRENT real behavior; the
        positive delivery/edit-protection properties cannot be proven until the capsule
        gap is closed (follow-on slice).

        ANTI-FALSE-GREEN for the slice: this test would START FAILING (the refusal would
        no longer fire) once the gap is fixed — at which point the positive-delivery
        assertions below it must be enabled. It is the canary on the gap, not a claim the
        path works."""
        proj = self._emit("estate-gap", FULL_VERSION)
        before = self._file_bytes(proj)

        with self.assertRaises(UpgradeApplyError) as ctx:
            self._apply(proj, OPERATING_DELTA_VERSION)
        msg = str(ctx.exception).lower()
        # The refusal is the capsule-replay gap on an operating render file (placeholder
        # key not in the capsule), NOT a generic failure.
        self.assertIn("placeholder", msg)

        after = self._file_bytes(proj)
        self.assertEqual(set(before), set(after), "refusal created/removed files")
        for rel, b in before.items():
            self.assertEqual(after[rel], b, f"refusal mutated {rel}")
        self.assertFalse(
            (proj / ".wizard" / "upgrade-review").exists(),
            "refusal wrote review sidecars",
        )

    def test_regimeB_new_target_skill_is_classified_new_on_the_surface(self):
        """Even though the apply refuses before committing (FINDING above), the computed
        surface MUST classify the brand-new v0.6.1 skill as `new` (a delivery the upgrade
        WOULD make additively once the render-replay gap is closed). This proves the new
        operating file is SEEN, not silently dropped from the surface."""
        proj = self._emit("estate-surface", FULL_VERSION)
        # Compute the surface directly (the refusal happens later, in the write loop).
        import upgrade_apply as ua
        from upgrade import find_bundle_entry
        registry = load_registry(REGISTRY_PATH)
        manifest = load_operator_manifest(proj / ".wizard" / "manifest.json")
        capsule = ua.load_replay_capsule(proj)
        ci = capsule["foundation_doc_inputs"]
        base = ua._render_version(FULL_VERSION, ci, REPO_ROOT)
        theirs = ua._render_version(OPERATING_DELTA_VERSION, ci, REPO_ROOT)
        target_entry = find_bundle_entry(registry, OPERATING_DELTA_VERSION)
        target_dir = (REPO_ROOT / target_entry.get("path", "")).resolve()
        target_contract = ua._load_target_contract(target_dir)
        surface = ua.compute_merge_surface(
            manifest, target_contract, base, theirs, proj, capsule)

        new_skill = "wizard/skills/health-check.md"
        entry = next((se for se in surface if se.relpath == new_skill), None)
        self.assertIsNotNone(entry, f"{new_skill} absent from the merge surface (dropped!)")
        self.assertEqual(entry.classification, SURFACE_NEW,
                         f"{new_skill} should be classified new on a v0.6.0->v0.6.1 surface")
        self.assertEqual(entry.render_kind, "copy")

    def test_regimeB_tampered_base_hash_refuses_before_any_operating_work(self):
        """TAMPER REFUSAL (independent of the capsule gap). Corrupting a managed
        foundation doc's base_hash fails the replay-conformance gate at step 2b — BEFORE
        any operating-layer rendering or writing. apply_upgrade refuses with ZERO writes
        and a clean rollback."""
        proj = self._emit("estate-tamper", FULL_VERSION)
        mp = proj / ".wizard" / "manifest.json"
        m = json.loads(mp.read_text())
        m["managed_files"]["vision.md"]["base_hash"] = "sha256:" + ("0" * 64)
        mp.write_text(json.dumps(m, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        before = self._file_bytes(proj)
        with self.assertRaises(UpgradeApplyError) as ctx:
            self._apply(proj, OPERATING_DELTA_VERSION)
        self.assertIn("replay-conformance", str(ctx.exception).lower())

        after = self._file_bytes(proj)
        self.assertEqual(set(before), set(after), "tamper-refusal created/removed files")
        for rel, b in before.items():
            self.assertEqual(after[rel], b, f"tamper-refusal mutated {rel}")
        self.assertFalse(
            (proj / ".wizard" / "upgrade-review").exists(),
            "tamper-refusal wrote review sidecars",
        )


if __name__ == "__main__":
    unittest.main()
