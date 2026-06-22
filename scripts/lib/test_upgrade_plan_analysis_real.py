"""REAL-PATH coverage for the per-artifact upgrade analysis.

The prior C1 build passed on synthetic fixtures (test_upgrade_plan_analysis.py) while
the real CLI path produced an EMPTY analysis -- because compute_upgrade_analysis was
never wired into the plan flow, and it was built over the operator's LOCAL drift instead
of the TARGET-CHANGE SET. This test exercises the REAL path end to end:

  1. emit a real v0.6.0 system from the preserved pilot transcript (v2 capsule);
  2. compute the upgrade plan for --to v0.6.1 via the SAME function path the CLI uses
     (compute_upgrade_plan + wizard_upgrade.populate_plan_analysis);
  3. assert plan.artifact_analysis is NON-EMPTY and is EXACTLY the v0.6.1 target-change
     set -- wizard/skills/health-check.md (new), operating_discipline.md (modified),
     wizard/skills/pause.md (modified) -- each with its migration-manifest benefit text,
     NOT the (many) drifted/unchanged operator files.

The live estate is NEVER written: the fixture is emitted into a TemporaryDirectory.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # wizard/scripts

import tempfile

import interview_cli as cli  # noqa: E402
import wizard_upgrade as wu  # noqa: E402
from upgrade import (  # noqa: E402
    compute_upgrade_plan,
    load_operator_manifest,
    load_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"
TRANSCRIPT = Path.home() / "wizard-pilot-2026-06-01" / "wizard_transcript.jsonl"
SHAPE = "markdown-CC"
FULL_VERSION = "v0.6.0"            # v2 capsule (operating block)
TARGET_VERSION = "v0.6.1"          # operating-layer-only delta over v0.6.0
_GEN_OVERRIDE = "c3b5609fbbe566d73f3097ff0d1cd087dfe19245"
PROJECT_NAME = "operator-system"

# The exact v0.6.1 target-change set (per the v0.6.1 migration-manifest artifact_notes).
_NEW_SKILL = "wizard/skills/health-check.md"
_MOD_DISCIPLINE = "operating_discipline.md"
_MOD_PAUSE = "wizard/skills/pause.md"
# C2 operating-layer delta (now a clean v0.6.0 -> v0.6.1 change since C2 lives only in
# v0.6.1): the relay rule in CLAUDE.md, the SessionStart hook in settings.json, and the
# new upgrade_notice.sh hook.
_MOD_CLAUDE_MD = "CLAUDE.md"
_MOD_SETTINGS = ".claude/settings.json"
_NEW_NOTICE = ".claude/upgrade_notice.sh"
_EXPECTED_CHANGE_SET = {_NEW_SKILL, _MOD_DISCIPLINE, _MOD_PAUSE,
                        _MOD_CLAUDE_MD, _MOD_SETTINGS, _NEW_NOTICE}


def _have_prereqs() -> bool:
    if not TRANSCRIPT.exists():
        return False
    try:
        reg = load_registry(REGISTRY_PATH)
    except Exception:
        return False
    versions = {e.get("foundation_bundle_version") for e in reg.get("bundles", [])}
    return {FULL_VERSION, TARGET_VERSION} <= versions


@unittest.skipUnless(
    _have_prereqs(),
    f"requires the preserved pilot transcript at {TRANSCRIPT} and the "
    f"{FULL_VERSION} + {TARGET_VERSION} bundles",
)
class UpgradeAnalysisRealPath(unittest.TestCase):
    """Real emit -> real plan -> populated analysis over the target-change set."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _emit_v060(self, name: str) -> Path:
        proj = self.tmp / name
        cli.cmd_emit_system(
            str(TRANSCRIPT), SHAPE, str(proj), str(REPO_ROOT),
            project_name=PROJECT_NAME, bundle_version=FULL_VERSION,
            generator_version_override=_GEN_OVERRIDE,
        )
        return proj

    def _plan_via_cli_path(self, proj: Path):
        """Compute the plan via the SAME function path the CLI (_run_upgrade_plan) uses:
        compute_upgrade_plan + populate_plan_analysis."""
        mp = proj / ".wizard" / "manifest.json"
        manifest = load_operator_manifest(mp)
        registry = load_registry(REGISTRY_PATH)
        plan = compute_upgrade_plan(
            proj, manifest, TARGET_VERSION, registry, registry_path=REGISTRY_PATH
        )
        wu.populate_plan_analysis(
            plan, proj, TARGET_VERSION, REPO_ROOT, registry, manifest,
        )
        return plan

    def test_analysis_populated_for_real_estate_upgrade(self):
        """The real plan path populates plan.artifact_analysis with EXACTLY the v0.6.1
        target-change set -- not the operator's drifted files.

        To prove the basis is the TARGET-CHANGE SET (not local drift), the operator edits
        a foundation doc the target does NOT change (vision.md). That drift must NOT pull
        vision.md into the analysis, while the three real v0.6.1 deltas DO appear."""
        proj = self._emit_v060("estate-v2")
        # Operator-edit a target-UNCHANGED file so it drifts; it must stay out of the set.
        drifted_unchanged = proj / "vision.md"
        self.assertTrue(drifted_unchanged.exists(), "vision.md should exist on a v0.6.0 emit")
        drifted_unchanged.write_text(
            drifted_unchanged.read_text(encoding="utf-8") + "\n\nOperator note: local edit.\n",
            encoding="utf-8",
        )
        plan = self._plan_via_cli_path(proj)

        # NON-EMPTY (the canary the prior build failed: real path produced 0 entries).
        self.assertTrue(plan.artifact_analysis,
                        "plan.artifact_analysis must be NON-EMPTY on a real v0.6.0->v0.6.1 plan")

        by_rel = {a.relpath: a for a in plan.artifact_analysis}

        # EXACT set: the three v0.6.1 deltas, nothing else.
        self.assertEqual(
            set(by_rel), _EXPECTED_CHANGE_SET,
            f"analysis must be exactly the v0.6.1 target-change set; got {sorted(by_rel)}",
        )

        # what classification.
        self.assertEqual(by_rel[_NEW_SKILL].what, "new",
                         f"{_NEW_SKILL} should be classified new")
        self.assertEqual(by_rel[_MOD_DISCIPLINE].what, "modified",
                         f"{_MOD_DISCIPLINE} should be classified modified")
        self.assertEqual(by_rel[_MOD_PAUSE].what, "modified",
                         f"{_MOD_PAUSE} should be classified modified")

        # benefit comes from the migration-manifest artifact_notes (NOT a default).
        self.assertIn("healthy", by_rel[_NEW_SKILL].benefit.lower())
        self.assertIn("operating guidelines", by_rel[_MOD_DISCIPLINE].benefit.lower())
        self.assertIn("pause", by_rel[_MOD_PAUSE].benefit.lower())

        # All display fields populated on every entry.
        for a in plan.artifact_analysis:
            with self.subTest(relpath=a.relpath):
                self.assertIn(a.kind, ("render", "copy"))
                self.assertTrue(a.risk)
                self.assertTrue(a.how)

        # The operator-drifted file the target does NOT change is NOT in the analysis --
        # the basis is the target-change set, not local drift.
        self.assertGreaterEqual(plan.drift_report.drift_count, 1,
                                "premise: vision.md was edited so the drift report has drift")
        self.assertNotIn(
            "vision.md", by_rel,
            "a drifted-but-target-unchanged file (vision.md) must NOT be in the analysis",
        )

    def test_analysis_render_section_shows_the_three_deltas(self):
        """The human-readable render includes the per-artifact analysis section with the
        three v0.6.1 deltas + their benefit text."""
        from upgrade import render_upgrade_plan  # noqa: E402
        proj = self._emit_v060("estate-render")
        plan = self._plan_via_cli_path(proj)
        out = render_upgrade_plan(plan)
        self.assertIn("Per-file upgrade analysis", out)
        for rel in _EXPECTED_CHANGE_SET:
            self.assertIn(rel, out, f"{rel} missing from rendered analysis")
        self.assertIn("healthy", out.lower())


if __name__ == "__main__":
    unittest.main()
