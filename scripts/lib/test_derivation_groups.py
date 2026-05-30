"""Tests for the derivation-groups registry loader + marker invariant (T0).

RED→GREEN: this file is written before derivation_groups.py exists (ModuleNotFound
is the first RED), then again before the registry JSON exists (load failure), then
green once both land. Covers: fail-closed loading, the group-complete predicate
(valid-skips count as satisfied), marker parsing, the marker-ordering invariant
(a step_NN completion is illegal unless every group closing at step_NN is confirmed),
the resume helper, and stale-confirmation detection.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from derivation_groups import (  # noqa: E402
    load_derivation_groups,
    DerivationGroups,
    DerivationGroup,
    DerivationGroupsError,
    group_inputs_complete,
    parse_progress_markers,
    validate_marker_invariant,
    resume_point,
    group_confirmation_is_stale,
)

SHAPE = "markdown-CC"
EXPECTED_GROUP_IDS = {
    "vision", "approach_roster", "orchestration_build", "hitl_autonomy", "tests_audit",
}


class LoaderTests(unittest.TestCase):
    def test_loads_five_groups(self):
        dg = load_derivation_groups(SHAPE)
        self.assertIsInstance(dg, DerivationGroups)
        self.assertEqual(dg.system_shape, SHAPE)
        self.assertEqual({g.group_id for g in dg.groups}, EXPECTED_GROUP_IDS)
        for g in dg.groups:
            self.assertIsInstance(g, DerivationGroup)
            self.assertTrue(g.input_question_ids, f"{g.group_id} has no input qids")
            self.assertTrue(g.target_fields, f"{g.group_id} has no target fields")
            self.assertTrue(g.close_after.startswith("step_"), g.close_after)
            self.assertEqual(g.confirmation_marker, f"group_{g.group_id}_confirmed")
            self.assertTrue(g.preview_docs, f"{g.group_id} has no preview_docs")

    def test_unknown_shape_fails_closed(self):
        with self.assertRaises(DerivationGroupsError):
            load_derivation_groups("no-such-shape-xyz")

    def test_group_by_id_unknown_fails_closed(self):
        dg = load_derivation_groups(SHAPE)
        self.assertEqual(dg.group_by_id("vision").group_id, "vision")
        with self.assertRaises(DerivationGroupsError):
            dg.group_by_id("not-a-group")

    def test_auto_global_fields_present(self):
        dg = load_derivation_groups(SHAPE)
        for f in ("SYSTEM_SHAPE", "FOUNDATION_ONLY_MODE", "WIZARD_VERSION"):
            self.assertIn(f, dg.auto_global_fields)

    def test_vision_and_approach_preview_docs(self):
        dg = load_derivation_groups(SHAPE)
        self.assertEqual(dg.group_by_id("vision").preview_docs, ["vision.md"])
        self.assertEqual(dg.group_by_id("approach_roster").preview_docs, ["approach.md"])

    def test_preview_docs_fully_covered_by_cumulative_fields(self):
        # Every placeholder a group's preview_docs reference (minus auto-globals) must be
        # produced by that group OR an earlier group — else the strict single-doc renderer
        # would fail-fast at the barrier. Uses the real v0.4.0 template placeholder sets.
        dg = load_derivation_groups(SHAPE)
        repo_root = Path(__file__).resolve().parents[3]
        tdir = repo_root / "wizard" / "foundation-bundles" / "v0.4.0" / "templates"
        import re
        ph_re = re.compile(r"\{\{([A-Z][A-Z0-9_]+)\}\}")
        cumulative = set(dg.auto_global_fields)
        for g in dg.groups:                       # registry order = derivation order
            cumulative |= set(g.target_fields)
            for doc in g.preview_docs:
                placeholders = set(ph_re.findall((tdir / doc).read_text(encoding="utf-8")))
                missing = placeholders - cumulative
                self.assertFalse(
                    missing,
                    f"group {g.group_id} previews {doc} but these placeholders are not yet "
                    f"derived by it or an earlier group: {sorted(missing)}",
                )


class GroupCompletePredicateTests(unittest.TestCase):
    def _vision(self):
        return load_derivation_groups(SHAPE).group_by_id("vision")

    def test_complete_when_all_answered(self):
        g = self._vision()
        answered = set(g.input_question_ids)
        self.assertTrue(group_inputs_complete(g, answered, set()))

    def test_valid_skip_counts_as_satisfied(self):
        g = DerivationGroup(
            group_id="t", input_question_ids=["A", "B", "C"], target_fields=["X"],
            close_after="step_01", confirmation_marker="group_t_confirmed",
            preview_docs=["vision.md"], skip_satisfied_if=["C"],
        )
        self.assertTrue(group_inputs_complete(g, {"A", "B"}, {"C"}))   # C validly skipped
        self.assertFalse(group_inputs_complete(g, {"A", "B"}, set()))  # C neither answered nor skipped

    def test_unexpected_skip_does_not_satisfy(self):
        g = DerivationGroup(
            group_id="t", input_question_ids=["A", "B"], target_fields=["X"],
            close_after="step_01", confirmation_marker="group_t_confirmed",
            preview_docs=["vision.md"], skip_satisfied_if=[],
        )
        self.assertFalse(group_inputs_complete(g, {"A"}, {"B"}))  # B skipped but not skip-eligible


class MarkerTests(unittest.TestCase):
    PROGRESS = (
        "step_00: complete | 2026-05-30T10:00:00\n"
        "step_04_NOTIF-2: complete | 2026-05-30T10:05:00\n"
        "step_05: complete | 2026-05-30T10:10:00\n"
        "group_vision_confirmed: complete | source_range=0:12 | source_hash=sha256:abc | 2026-05-30T10:11:00\n"
    )

    def test_parse_markers(self):
        m = parse_progress_markers(self.PROGRESS)
        self.assertIn("step_05", m)
        self.assertEqual(m["step_05"]["status"], "complete")
        self.assertIn("step_04_NOTIF-2", m)            # sub-step markers parse too
        gv = m["group_vision_confirmed"]
        self.assertEqual(gv["source_hash"], "sha256:abc")
        self.assertEqual(gv["source_range"], "0:12")

    def test_invariant_blocks_step_without_group_confirm(self):
        dg = load_derivation_groups(SHAPE)
        # step_05 complete but group_vision_confirmed ABSENT -> violation
        markers = {"step_05": {"status": "complete"}}
        violations = validate_marker_invariant(markers, dg)
        self.assertTrue(any("vision" in v for v in violations))

    def test_invariant_passes_when_group_confirmed(self):
        dg = load_derivation_groups(SHAPE)
        markers = {
            "step_05": {"status": "complete"},
            "group_vision_confirmed": {"status": "complete", "source_hash": "sha256:abc"},
        }
        self.assertEqual(validate_marker_invariant(markers, dg), [])

    def test_invariant_multiple_groups_one_step(self):
        dg = load_derivation_groups(SHAPE)
        step13_groups = [g for g in dg.groups if g.close_after == "step_13"]
        self.assertGreaterEqual(len(step13_groups), 2)   # several operational groups close at 13
        # step_13 complete, only ONE of its groups confirmed -> still a violation for the rest.
        markers = {"step_13": {"status": "complete"},
                   step13_groups[0].confirmation_marker: {"status": "complete"}}
        violations = validate_marker_invariant(markers, dg)
        self.assertTrue(violations)
        # all of them confirmed -> clean
        markers2 = {"step_13": {"status": "complete"}}
        for g in step13_groups:
            markers2[g.confirmation_marker] = {"status": "complete"}
        # earlier-step groups must also be satisfied for a fully clean result; check only step_13 here
        v2 = [v for v in validate_marker_invariant(markers2, dg) if "step_13" in v or
              any(g.group_id in v for g in step13_groups)]
        self.assertEqual(v2, [])

    def test_resume_point(self):
        dg = load_derivation_groups(SHAPE)
        rp = resume_point(parse_progress_markers(self.PROGRESS), dg)
        self.assertEqual(rp["highest_completed_step"], 5)
        self.assertIn("vision", rp["confirmed_groups"])

    def test_stale_confirmation_detection(self):
        marker = {"status": "complete", "source_hash": "sha256:OLD"}
        self.assertTrue(group_confirmation_is_stale(marker, "sha256:NEW"))
        self.assertFalse(group_confirmation_is_stale(marker, "sha256:OLD"))


class ContractEnvelopeTests(unittest.TestCase):
    def test_contract_mismatch_fails_closed(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / f"{SHAPE}.json"
            bad.write_text(json.dumps({"contract_id": "wrong", "system_shape": SHAPE}), encoding="utf-8")
            with self.assertRaises(DerivationGroupsError):
                load_derivation_groups(SHAPE, registry_dir=Path(td))


if __name__ == "__main__":
    unittest.main()
