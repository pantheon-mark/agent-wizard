"""Tests for the per-artifact upgrade analysis (compute_upgrade_analysis).

The analysis is over the TARGET-CHANGE SET (what the new version adds/modifies vs the
operator's current version) -- NOT the operator's local drift. compute_upgrade_analysis
is the presentation JOIN that enriches each change-set entry with:
  - what    : new | modified
  - kind    : render | copy
  - benefit : plain-language why-this-helps (from migration-manifest artifact_notes,
              or a neutral default)
  - risk    : clean adopt | will merge your edits | saved for your review |
              will warn -- needs your OK (--ack) to replace | installed as-is
  - how     : same action phrased as what will happen

These tests use SYNTHETIC change-set entries built inline. The REAL-path coverage --
emitting a real v0.6.0 system and computing the plan via the same function path the CLI
uses -- lives in test_upgrade_plan_analysis_real.py (these synthetic tests are NOT the
only coverage; a prior build passed synthetic tests while the real path produced nothing).
"""

import unittest
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upgrade import (  # noqa: E402
    DRIFT_DETECTED,
    DRIFT_NONE,
    MERGE_STRATEGY_THREE_WAY,
    MERGE_STRATEGY_OPERATOR_REVIEW,
    MERGE_STRATEGY_WARN_ON_DRIFT,
    MERGE_STRATEGY_FROZEN,
    MigrationEntry,
    UpgradePlan,
    DriftReport,
    STANDING_APPROVAL_STATUS_UNAVAILABLE,
    upgrade_plan_to_dict,
    render_upgrade_plan,
    compute_upgrade_analysis,
    ArtifactAnalysis,
)


# ===== Shared fixtures =====


@dataclass
class _ChangeEntry:
    """Stand-in for upgrade_apply.TargetChangeEntry (duck-typed by relpath / what /
    render_kind / merge_strategy / drift_status). Lets these unit tests stay decoupled
    from the apply engine while exercising the same JOIN the real path uses."""
    relpath: str
    what: str
    render_kind: str
    merge_strategy: str
    drift_status: str = DRIFT_NONE


def _change(relpath, what, render_kind, merge_strategy, drift_status=DRIFT_NONE):
    return _ChangeEntry(relpath, what, render_kind, merge_strategy, drift_status)


def _make_migration_manifest_with_notes() -> dict:
    """Synthetic migration manifest with artifact_notes for v0.6.1 changed files."""
    return {
        "target_version": "v0.6.1",
        "migrations": [
            {
                "from": "v0.6.0",
                "class": "minor-additive",
                "requires_operator_approval": True,
                "stop_condition": "not_applicable",
                "breaking_changes_summary": "",
                "supported": True,
            }
        ],
        "artifact_notes": {
            "wizard/skills/health-check.md": {
                "benefit": "Adds a quick 'is my system healthy?' check you can run any time."
            },
            "operating_discipline.md": {
                "benefit": "Updates the operating guidelines your system follows day to day."
            },
            "wizard/skills/pause.md": {
                "benefit": "Improves the pause skill so your system handles interruptions more reliably."
            },
        },
    }


# ===== Tests =====


class TestAnalysisPerArtifactFields(unittest.TestCase):
    """compute_upgrade_analysis returns one ArtifactAnalysis per change-set entry,
    each with all five required fields populated."""

    def setUp(self):
        # The v0.6.1 target-change set: health-check.md is NEW (copy), operating_discipline.md
        # is MODIFIED (render, no operator drift), pause.md is MODIFIED (copy, no drift).
        self.change_set = [
            _change("wizard/skills/health-check.md", "new", "copy", MERGE_STRATEGY_WARN_ON_DRIFT),
            _change("operating_discipline.md", "modified", "render", MERGE_STRATEGY_THREE_WAY),
            _change("wizard/skills/pause.md", "modified", "copy", MERGE_STRATEGY_WARN_ON_DRIFT),
        ]
        self.migration_manifest = _make_migration_manifest_with_notes()

    def test_analysis_lists_per_artifact_fields(self):
        """Each analysis entry carries all five fields; benefit comes from the
        migration-manifest artifact_notes."""
        items = compute_upgrade_analysis(self.change_set, self.migration_manifest)
        relpaths = [a.relpath for a in items]
        self.assertIn("wizard/skills/health-check.md", relpaths)
        self.assertIn("operating_discipline.md", relpaths)
        self.assertIn("wizard/skills/pause.md", relpaths)

        for a in items:
            with self.subTest(relpath=a.relpath):
                self.assertIn(a.what, ("new", "modified"),
                              msg=f"what={a.what!r} not a valid value")
                self.assertIn(a.kind, ("render", "copy"),
                              msg=f"kind={a.kind!r} not a valid value")
                self.assertTrue(a.benefit, msg="benefit must not be empty")
                self.assertTrue(a.risk, msg="risk must not be empty")
                self.assertTrue(a.how, msg="how must not be empty")

        hc = next(a for a in items if a.relpath == "wizard/skills/health-check.md")
        self.assertIn("healthy", hc.benefit.lower(),
                      msg="health-check.md benefit must include manifest note text")
        self.assertEqual(hc.what, "new")

        od = next(a for a in items if a.relpath == "operating_discipline.md")
        self.assertEqual(od.what, "modified")

    def test_only_change_set_files_appear(self):
        """Files NOT in the change set never appear (drift on un-changed files is NOT
        the basis -- that is the complementary drift report's job)."""
        items = compute_upgrade_analysis(self.change_set, self.migration_manifest)
        self.assertEqual(len(items), 3)
        # A drifted-but-unchanged-by-target file (e.g. vision.md) is absent.
        self.assertNotIn("vision.md", [a.relpath for a in items])

    def test_benefit_default_when_no_note(self):
        """When no artifact_notes entry exists for a file, benefit is a neutral default
        that mentions the filename."""
        change_set = [_change("vision.md", "modified", "render", MERGE_STRATEGY_THREE_WAY)]
        manifest_no_notes = {"target_version": "v0.6.1", "migrations": []}
        items = compute_upgrade_analysis(change_set, manifest_no_notes)
        self.assertEqual(len(items), 1)
        self.assertIn("vision.md", items[0].benefit.lower(),
                      msg="default benefit must mention the filename")


class TestAnalysisRiskFromDrift(unittest.TestCase):
    """The at-risk label is derived from merge_strategy + the operator's drift state on
    the file (whether applying the target change touches an operator-edited file)."""

    def test_analysis_flags_ack_replacement_destructive(self):
        """warn_on_drift + operator drift => risk mentions '--ack' and is not 'clean adopt'."""
        change_set = [
            _change("wizard/skills/pause.md", "modified", "copy",
                    MERGE_STRATEGY_WARN_ON_DRIFT, drift_status=DRIFT_DETECTED),
        ]
        items = compute_upgrade_analysis(change_set, _make_migration_manifest_with_notes())
        self.assertEqual(len(items), 1)
        a = items[0]
        combined = (a.risk + " " + a.how).lower()
        self.assertIn("--ack", combined,
                      msg="warn_on_drift + drift must mention --ack in risk or how")
        self.assertNotEqual(a.risk.lower(), "clean adopt")

    def test_three_way_no_drift_is_clean_adopt(self):
        change_set = [
            _change("operating_discipline.md", "modified", "render",
                    MERGE_STRATEGY_THREE_WAY, drift_status=DRIFT_NONE),
        ]
        items = compute_upgrade_analysis(change_set, _make_migration_manifest_with_notes())
        self.assertEqual(len(items), 1)
        self.assertIn("clean adopt", items[0].risk.lower())

    def test_three_way_with_drift_will_merge(self):
        change_set = [
            _change("operating_discipline.md", "modified", "render",
                    MERGE_STRATEGY_THREE_WAY, drift_status=DRIFT_DETECTED),
        ]
        items = compute_upgrade_analysis(change_set, _make_migration_manifest_with_notes())
        self.assertEqual(len(items), 1)
        self.assertIn("merge", items[0].risk.lower())

    def test_operator_review_is_saved_for_review(self):
        change_set = [
            _change("vision.md", "modified", "render",
                    MERGE_STRATEGY_OPERATOR_REVIEW, drift_status=DRIFT_DETECTED),
        ]
        items = compute_upgrade_analysis(change_set, {"target_version": "v0.6.1", "migrations": []})
        self.assertEqual(len(items), 1)
        self.assertIn("review", items[0].risk.lower())

    def test_new_file_installed_as_is(self):
        change_set = [
            _change("wizard/skills/health-check.md", "new", "copy", MERGE_STRATEGY_WARN_ON_DRIFT),
        ]
        items = compute_upgrade_analysis(change_set, _make_migration_manifest_with_notes())
        self.assertEqual(len(items), 1)
        a = items[0]
        self.assertEqual(a.what, "new")
        self.assertIn("installed", (a.risk + " " + a.how).lower())

    def test_frozen_no_drift_is_clean_adopt(self):
        change_set = [_change("some.md", "modified", "copy", MERGE_STRATEGY_FROZEN, DRIFT_NONE)]
        items = compute_upgrade_analysis(change_set, {})
        self.assertIn("clean adopt", items[0].risk.lower())


class TestAnalysisJsonAndRenderShape(unittest.TestCase):
    """The --json output + human render carry the per-artifact analysis."""

    def _plan_with_analysis(self):
        change_set = [
            _change("operating_discipline.md", "modified", "render", MERGE_STRATEGY_THREE_WAY),
            _change("wizard/skills/health-check.md", "new", "copy", MERGE_STRATEGY_WARN_ON_DRIFT),
        ]
        items = compute_upgrade_analysis(change_set, _make_migration_manifest_with_notes())
        me = MigrationEntry(
            from_version="v0.6.0", migration_class="minor-additive",
            requires_operator_approval=True, stop_condition="not_applicable",
            breaking_changes_summary="", supported=True,
        )
        plan = UpgradePlan(
            operator_project_path="/fake/project",
            from_version="v0.6.0", to_version="v0.6.1", tier="minor-additive",
            drift_report=DriftReport("/fake/project", "v0.6.0", "v0.6.1", entries=[]),
            standing_approval_status=STANDING_APPROVAL_STATUS_UNAVAILABLE,
            migration_entry=me, planned_steps=[], requires_review=True, plan_only=True,
        )
        plan.artifact_analysis = items
        return plan

    def test_analysis_json_shape(self):
        d = upgrade_plan_to_dict(self._plan_with_analysis())
        self.assertIn("artifact_analysis", d)
        analysis_list = d["artifact_analysis"]
        self.assertIsInstance(analysis_list, list)
        self.assertGreater(len(analysis_list), 0)
        required_keys = {"relpath", "what", "kind", "benefit", "risk", "how"}
        for entry in analysis_list:
            with self.subTest(entry=entry.get("relpath")):
                self.assertFalse(required_keys - set(entry.keys()))

    def test_analysis_in_render_output(self):
        output = render_upgrade_plan(self._plan_with_analysis())
        self.assertIn("operating_discipline.md", output)
        self.assertIn("wizard/skills/health-check.md", output)
        self.assertIn("clean adopt", output.lower())


if __name__ == "__main__":
    unittest.main()
