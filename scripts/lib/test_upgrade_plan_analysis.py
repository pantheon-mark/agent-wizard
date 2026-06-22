"""Tests for the per-artifact upgrade analysis (compute_upgrade_analysis).

Each changed artifact in the upgrade plan is enriched with:
  - what    : new | modified | unchanged
  - kind    : render | copy
  - benefit : plain-language why-this-helps (from migration-manifest artifact_notes,
              or a neutral default)
  - risk    : clean adopt | will merge your edits | saved for your review |
              will warn -- needs your OK (--ack) to replace | installed as-is
  - how     : same action phrased as what will happen

These tests use SYNTHETIC fixtures only -- no real estate, no real disk project.
Fixtures are built inline to avoid coupling to a particular operator project.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upgrade import (  # noqa: E402
    DRIFT_DETECTED,
    DRIFT_NONE,
    DRIFT_MISSING_FILE,
    MERGE_STRATEGY_THREE_WAY,
    MERGE_STRATEGY_OPERATOR_REVIEW,
    MERGE_STRATEGY_WARN_ON_DRIFT,
    MERGE_STRATEGY_FROZEN,
    DriftReport,
    DriftReportEntry,
    MigrationEntry,
    UpgradePlan,
    STANDING_APPROVAL_STATUS_UNAVAILABLE,
    upgrade_plan_to_dict,
    render_upgrade_plan,
    compute_upgrade_analysis,
    ArtifactAnalysis,
)


# ===== Shared fixtures =====

def _make_drift_entry(
    path: str,
    merge_strategy: str,
    status: str = DRIFT_NONE,
) -> DriftReportEntry:
    base = "sha256:aabbcc"
    current = base if status == DRIFT_NONE else "sha256:ddeeff"
    return DriftReportEntry(
        path=path,
        base_hash=base,
        current_hash=current,
        status=status,
        merge_strategy=merge_strategy,
        local_modifications="expected",
        plan_action="plan action placeholder",
    )


def _make_plan(
    entries: list,
    migration_manifest: dict = None,
) -> UpgradePlan:
    """Build a synthetic UpgradePlan with the given drift entries."""
    drift = DriftReport(
        operator_project_path="/fake/project",
        bundle_version="v0.6.0",
        target_bundle_version="v0.6.1",
        entries=entries,
    )
    me = MigrationEntry(
        from_version="v0.6.0",
        migration_class="minor-additive",
        requires_operator_approval=True,
        stop_condition="not_applicable",
        breaking_changes_summary="",
        supported=True,
    )
    return UpgradePlan(
        operator_project_path="/fake/project",
        from_version="v0.6.0",
        to_version="v0.6.1",
        tier="minor-additive",
        drift_report=drift,
        standing_approval_status=STANDING_APPROVAL_STATUS_UNAVAILABLE,
        migration_entry=me,
        planned_steps=[],
        requires_review=True,
        plan_only=True,
    )


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


def _make_contract_entries() -> dict:
    """Minimal system-artifacts entries for the three v0.6.1-changed files."""
    return {
        "wizard/skills/health-check.md": {
            "render_kind": "copy",
            "merge_strategy": MERGE_STRATEGY_WARN_ON_DRIFT,
            "delivery": "wizard",
        },
        "operating_discipline.md": {
            "render_kind": "render",
            "merge_strategy": MERGE_STRATEGY_THREE_WAY,
            "delivery": "wizard",
        },
        "wizard/skills/pause.md": {
            "render_kind": "copy",
            "merge_strategy": MERGE_STRATEGY_WARN_ON_DRIFT,
            "delivery": "wizard",
        },
    }


# ===== Tests =====

class TestAnalysisPerArtifactFields(unittest.TestCase):
    """compute_upgrade_analysis returns one ArtifactAnalysis per surface file,
    each with all five required fields populated."""

    def setUp(self):
        # health-check.md is NEW (not in operator manifest / no drift entry)
        # operating_discipline.md is MODIFIED (three_way, no operator drift)
        # pause.md is MODIFIED (warn_on_drift, no operator drift)
        self.entries = [
            _make_drift_entry("operating_discipline.md", MERGE_STRATEGY_THREE_WAY),
            _make_drift_entry("wizard/skills/pause.md", MERGE_STRATEGY_WARN_ON_DRIFT),
        ]
        self.plan = _make_plan(self.entries)
        self.migration_manifest = _make_migration_manifest_with_notes()
        self.contract_entries = _make_contract_entries()

    def test_analysis_lists_per_artifact_fields(self):
        """Each analysis entry carries all five fields; benefit for health-check.md
        comes from the migration-manifest artifact_notes."""
        items = compute_upgrade_analysis(
            self.plan,
            self.migration_manifest,
            self.contract_entries,
            new_files=["wizard/skills/health-check.md"],
        )
        relpaths = [a.relpath for a in items]
        # All three changed files must appear
        self.assertIn("wizard/skills/health-check.md", relpaths)
        self.assertIn("operating_discipline.md", relpaths)
        self.assertIn("wizard/skills/pause.md", relpaths)

        # All five fields must be non-empty on every entry
        for a in items:
            with self.subTest(relpath=a.relpath):
                self.assertIn(a.what, ("new", "modified", "unchanged"),
                              msg=f"what={a.what!r} not a valid value")
                self.assertIn(a.kind, ("render", "copy"),
                              msg=f"kind={a.kind!r} not a valid value")
                self.assertTrue(a.benefit, msg="benefit must not be empty")
                self.assertTrue(a.risk, msg="risk must not be empty")
                self.assertTrue(a.how, msg="how must not be empty")

        # health-check.md: benefit must come from the manifest notes
        hc = next(a for a in items if a.relpath == "wizard/skills/health-check.md")
        self.assertIn("healthy", hc.benefit.lower(),
                      msg="health-check.md benefit must include manifest note text")

        # health-check.md is new, not modified
        self.assertEqual(hc.what, "new")

        # operating_discipline.md is modified
        od = next(a for a in items if a.relpath == "operating_discipline.md")
        self.assertEqual(od.what, "modified")

    def test_benefit_default_when_no_note(self):
        """When no artifact_notes entry exists for a file, benefit is a neutral default
        that mentions the filename."""
        entries = [
            _make_drift_entry("vision.md", MERGE_STRATEGY_THREE_WAY),
        ]
        plan = _make_plan(entries)
        contract = {
            "vision.md": {
                "render_kind": "render",
                "merge_strategy": MERGE_STRATEGY_THREE_WAY,
                "delivery": "wizard",
            }
        }
        manifest_no_notes = {
            "target_version": "v0.6.1",
            "migrations": [],
        }
        items = compute_upgrade_analysis(plan, manifest_no_notes, contract, new_files=[])
        self.assertEqual(len(items), 1)
        a = items[0]
        self.assertIn("vision.md", a.benefit.lower(),
                      msg="default benefit must mention the filename")


class TestAnalysisFlagsAckReplacementDestructive(unittest.TestCase):
    """A warn_on_drift file the operator has edited is flagged as needing --ack."""

    def test_analysis_flags_ack_replacement_destructive(self):
        """warn_on_drift + operator drift => risk mentions '--ack' and is not 'clean adopt'."""
        entries = [
            _make_drift_entry("wizard/skills/pause.md", MERGE_STRATEGY_WARN_ON_DRIFT,
                              status=DRIFT_DETECTED),
        ]
        plan = _make_plan(entries)
        manifest = _make_migration_manifest_with_notes()
        contract = {
            "wizard/skills/pause.md": {
                "render_kind": "copy",
                "merge_strategy": MERGE_STRATEGY_WARN_ON_DRIFT,
                "delivery": "wizard",
            }
        }
        items = compute_upgrade_analysis(plan, manifest, contract, new_files=[])
        self.assertEqual(len(items), 1)
        a = items[0]
        # Must flag as needing explicit operator OK (--ack)
        combined = (a.risk + " " + a.how).lower()
        self.assertIn("--ack", combined,
                      msg="warn_on_drift + drift must mention --ack in risk or how")
        self.assertNotEqual(a.risk.lower(), "clean adopt",
                            msg="warn_on_drift + drift must not be 'clean adopt'")

    def test_three_way_no_drift_is_clean_adopt(self):
        """three_way + no drift => risk is 'clean adopt'."""
        entries = [
            _make_drift_entry("operating_discipline.md", MERGE_STRATEGY_THREE_WAY,
                              status=DRIFT_NONE),
        ]
        plan = _make_plan(entries)
        manifest = _make_migration_manifest_with_notes()
        contract = {
            "operating_discipline.md": {
                "render_kind": "render",
                "merge_strategy": MERGE_STRATEGY_THREE_WAY,
                "delivery": "wizard",
            }
        }
        items = compute_upgrade_analysis(plan, manifest, contract, new_files=[])
        self.assertEqual(len(items), 1)
        a = items[0]
        self.assertIn("clean adopt", a.risk.lower(),
                      msg="three_way + no drift must be 'clean adopt'")

    def test_three_way_with_drift_will_merge(self):
        """three_way + drift => risk mentions merging edits."""
        entries = [
            _make_drift_entry("operating_discipline.md", MERGE_STRATEGY_THREE_WAY,
                              status=DRIFT_DETECTED),
        ]
        plan = _make_plan(entries)
        manifest = _make_migration_manifest_with_notes()
        contract = {
            "operating_discipline.md": {
                "render_kind": "render",
                "merge_strategy": MERGE_STRATEGY_THREE_WAY,
                "delivery": "wizard",
            }
        }
        items = compute_upgrade_analysis(plan, manifest, contract, new_files=[])
        self.assertEqual(len(items), 1)
        a = items[0]
        # Should mention merging edits
        self.assertIn("merge", a.risk.lower(),
                      msg="three_way + drift must mention merging edits in risk")

    def test_operator_review_is_saved_for_review(self):
        """operator_review => risk says saved for your review."""
        entries = [
            _make_drift_entry("vision.md", MERGE_STRATEGY_OPERATOR_REVIEW,
                              status=DRIFT_DETECTED),
        ]
        plan = _make_plan(entries)
        manifest = {"target_version": "v0.6.1", "migrations": []}
        contract = {
            "vision.md": {
                "render_kind": "render",
                "merge_strategy": MERGE_STRATEGY_OPERATOR_REVIEW,
                "delivery": "wizard",
            }
        }
        items = compute_upgrade_analysis(plan, manifest, contract, new_files=[])
        self.assertEqual(len(items), 1)
        a = items[0]
        self.assertIn("review", a.risk.lower(),
                      msg="operator_review must mention 'review' in risk")


class TestAnalysisJsonShape(unittest.TestCase):
    """The --json output (upgrade_plan_to_dict) carries the per-artifact analysis
    structure with stable keys."""

    def test_analysis_json_shape(self):
        """upgrade_plan_to_dict includes 'artifact_analysis' list with stable keys."""
        entries = [
            _make_drift_entry("operating_discipline.md", MERGE_STRATEGY_THREE_WAY),
            _make_drift_entry("wizard/skills/pause.md", MERGE_STRATEGY_WARN_ON_DRIFT),
        ]
        plan = _make_plan(entries)
        manifest = _make_migration_manifest_with_notes()
        contract = _make_contract_entries()

        # Attach analysis to plan
        items = compute_upgrade_analysis(
            plan, manifest, contract, new_files=["wizard/skills/health-check.md"]
        )
        plan.artifact_analysis = items

        d = upgrade_plan_to_dict(plan)
        self.assertIn("artifact_analysis", d,
                      msg="upgrade_plan_to_dict must include 'artifact_analysis' key")
        analysis_list = d["artifact_analysis"]
        self.assertIsInstance(analysis_list, list)
        self.assertGreater(len(analysis_list), 0)

        # Each entry must have the five stable keys plus relpath
        required_keys = {"relpath", "what", "kind", "benefit", "risk", "how"}
        for entry in analysis_list:
            with self.subTest(entry=entry.get("relpath")):
                missing = required_keys - set(entry.keys())
                self.assertFalse(missing,
                                 msg=f"analysis entry missing keys: {missing}")

    def test_analysis_in_render_output(self):
        """render_upgrade_plan includes the per-artifact analysis section."""
        entries = [
            _make_drift_entry("operating_discipline.md", MERGE_STRATEGY_THREE_WAY),
        ]
        plan = _make_plan(entries)
        manifest = _make_migration_manifest_with_notes()
        contract = {
            "operating_discipline.md": {
                "render_kind": "render",
                "merge_strategy": MERGE_STRATEGY_THREE_WAY,
                "delivery": "wizard",
            }
        }
        items = compute_upgrade_analysis(plan, manifest, contract, new_files=[])
        plan.artifact_analysis = items

        output = render_upgrade_plan(plan)
        # The rendered output must include the per-artifact section
        self.assertIn("operating_discipline.md", output,
                      msg="render_upgrade_plan must list analyzed artifacts")
        self.assertIn("clean adopt", output.lower(),
                      msg="render_upgrade_plan must show the risk label")


class TestAnalysisRiskMapping(unittest.TestCase):
    """Exhaustive coverage of all merge-strategy + drift combinations."""

    def _single(self, merge_strategy: str, drift_status: str,
                is_new: bool = False) -> "ArtifactAnalysis":
        relpath = "some_file.md"
        entries = [] if is_new else [_make_drift_entry(relpath, merge_strategy, drift_status)]
        plan = _make_plan(entries)
        contract = {
            relpath: {
                "render_kind": "copy",
                "merge_strategy": merge_strategy,
                "delivery": "wizard",
            }
        }
        manifest = {"target_version": "v0.6.1", "migrations": []}
        new_files = [relpath] if is_new else []
        items = compute_upgrade_analysis(plan, manifest, contract, new_files=new_files)
        self.assertEqual(len(items), 1)
        return items[0]

    def test_warn_no_drift_is_installed_as_is(self):
        a = self._single(MERGE_STRATEGY_WARN_ON_DRIFT, DRIFT_NONE)
        combined = (a.risk + " " + a.how).lower()
        self.assertIn("installed", combined)

    def test_new_file_what_is_new(self):
        a = self._single(MERGE_STRATEGY_WARN_ON_DRIFT, DRIFT_NONE, is_new=True)
        self.assertEqual(a.what, "new")

    def test_frozen_no_drift_is_clean_adopt(self):
        a = self._single(MERGE_STRATEGY_FROZEN, DRIFT_NONE)
        self.assertIn("clean adopt", a.risk.lower())

    def test_operator_review_no_drift(self):
        a = self._single(MERGE_STRATEGY_OPERATOR_REVIEW, DRIFT_NONE)
        self.assertIn("review", a.risk.lower())


if __name__ == "__main__":
    unittest.main()
