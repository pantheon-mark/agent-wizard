"""Tests for capability_projection — the deterministic MVP<->roadmap projections."""

import json
import unittest

import capability_projection as cap


def _incr(capability, bucket, phase=None, agents="", depends_on="", rationale="", condition=""):
    row = {"capability": capability, "release_bucket": bucket}
    if phase is not None:
        row["phase"] = phase
    if agents:
        row["agents"] = agents
    if depends_on:
        row["depends_on"] = depends_on
    if rationale:
        row["rationale"] = rationale
    if condition:
        row["condition"] = condition
    return row


def _json(rows):
    return json.dumps(rows)


class DerivationInputsTest(unittest.TestCase):
    def test_both_fields_read_only_capability_increments(self):
        self.assertEqual(cap.derivation_inputs_for("BUILD_PHASES_ROWS"), ["CAPABILITY_INCREMENTS"])
        self.assertEqual(cap.derivation_inputs_for("MVP_ROADMAP_BOUNDARY"), ["CAPABILITY_INCREMENTS"])

    def test_unknown_field_fails(self):
        with self.assertRaises(cap.CapabilityProjectionError):
            cap.derivation_inputs_for("NOPE")

    def test_projection_fields_set(self):
        self.assertEqual(cap.PROJECTION_FIELDS, frozenset({"BUILD_PHASES_ROWS", "MVP_ROADMAP_BOUNDARY"}))


class BuildPhasesProjectionTest(unittest.TestCase):
    def _project(self, rows):
        return cap.project("BUILD_PHASES_ROWS", {"CAPABILITY_INCREMENTS": _json(rows)})

    def test_groups_by_phase_ascending(self):
        rows = [
            _incr("B", "mvp", phase=2, agents="Helper"),
            _incr("A", "mvp", phase=1, agents="Coordinator"),
        ]
        body = self._project(rows)
        lines = body.splitlines()
        self.assertEqual(lines[0], "| 1 | Coordinator | A | — |")
        self.assertEqual(lines[1], "| 2 | Helper | B | — |")

    def test_excludes_candidate_conditional(self):
        rows = [
            _incr("Spine", "mvp", phase=1, agents="Coordinator"),
            _incr("Maybe CRM", "candidate_conditional", condition="volume grows"),
        ]
        body = self._project(rows)
        self.assertIn("Spine", body)
        self.assertNotIn("Maybe CRM", body)
        self.assertEqual(len(body.splitlines()), 1)

    def test_partial_phase_lists_both_buckets_capabilities(self):
        # A single phase carrying both an mvp capability and a roadmap capability.
        rows = [
            _incr("Task spine", "mvp", phase=1, agents="Coordinator"),
            _incr("Drafting", "post_mvp_roadmap", phase=1, agents="Drafter"),
        ]
        body = self._project(rows)
        self.assertEqual(len(body.splitlines()), 1)
        self.assertIn("Task spine; Drafting", body)
        self.assertIn("Coordinator, Drafter", body)

    def test_depends_on_fallback_dash(self):
        rows = [_incr("X", "mvp", phase=1)]
        self.assertIn("| 1 |  | X | — |", self._project(rows))

    def test_depends_on_first_nonempty(self):
        rows = [
            _incr("X", "mvp", phase=2, depends_on="Phase 1"),
        ]
        self.assertIn("| 2 |  | X | Phase 1 |", self._project(rows))

    def test_empty_record_empty_body(self):
        self.assertEqual(self._project([]), "")


class BoundaryProjectionTest(unittest.TestCase):
    def _project(self, rows):
        return cap.project("MVP_ROADMAP_BOUNDARY", {"CAPABILITY_INCREMENTS": _json(rows)})

    def test_three_buckets_render(self):
        rows = [
            _incr("Task spine", "mvp", phase=1, agents="Coordinator"),
            _incr("Drafting", "post_mvp_roadmap", phase=2, agents="Drafter", rationale="after the spine works"),
            _incr("CRM sync", "candidate_conditional", condition="volume grows"),
        ]
        block = self._project(rows)
        self.assertIn("**Delivered in the MVP**", block)
        self.assertIn("- Task spine (Coordinator)", block)
        self.assertIn("**On the roadmap — in scope, planned after the MVP**", block)
        self.assertIn("- Drafting (Drafter) — after the spine works", block)
        self.assertIn("**Possible later — not committed**", block)
        self.assertIn("- CRM sync — only if volume grows", block)

    def test_no_tail_state(self):
        rows = [_incr("Everything", "mvp", phase=1, agents="Solo")]
        block = self._project(rows)
        self.assertIn("Nothing is deferred", block)
        self.assertNotIn("**Possible later", block)

    def test_candidate_section_omitted_when_none(self):
        rows = [
            _incr("A", "mvp", phase=1),
            _incr("B", "post_mvp_roadmap", phase=2),
        ]
        block = self._project(rows)
        self.assertNotIn("Possible later", block)

    def test_label_without_agents(self):
        rows = [_incr("Bare capability", "mvp", phase=1)]
        self.assertIn("- Bare capability\n", self._project(rows) + "\n")


class AntiContradictionRegressionTest(unittest.TestCase):
    """The verified estate_executor_001 failure: an MVP that SPANS phases 1-4. Under the old
    independent-derivation model, 'roadmap = phases after phase 1' contradicted the MVP. With the
    single CAPABILITY_INCREMENTS source, the MVP bucket and the phase table are BOTH views of the
    same record, so the MVP can span phases without any contradiction being representable."""

    def setUp(self):
        # MVP capabilities deliberately spread across phases 1-4; one genuinely-deferred roadmap item.
        self.rows = [
            _incr("Task tracker spine", "mvp", phase=1, agents="Operations"),
            _incr("Shared-spreadsheet propagation", "mvp", phase=2, agents="Communication"),
            _incr("Verified research briefs", "mvp", phase=3, agents="Research"),
            _incr("Drift-analysis cadence", "mvp", phase=4, agents="Review"),
            _incr("Supplier follow-up automation", "post_mvp_roadmap", phase=5, agents="Review",
                  rationale="after the MVP has run for a while"),
        ]

    def test_mvp_spans_multiple_phases_in_boundary(self):
        block = cap.project("MVP_ROADMAP_BOUNDARY", {"CAPABILITY_INCREMENTS": _json(self.rows)})
        mvp_section = block.split("**On the roadmap")[0]
        # All four MVP capabilities are in the MVP bucket — not falsely truncated to phase 1.
        self.assertIn("Task tracker spine", mvp_section)
        self.assertIn("Shared-spreadsheet propagation", mvp_section)
        self.assertIn("Verified research briefs", mvp_section)
        self.assertIn("Drift-analysis cadence", mvp_section)
        # The genuinely-deferred item is NOT in the MVP bucket.
        self.assertNotIn("Supplier follow-up automation", mvp_section)

    def test_phase_table_shows_all_committed_phases(self):
        body = cap.project("BUILD_PHASES_ROWS", {"CAPABILITY_INCREMENTS": _json(self.rows)})
        phases = [line.split("|")[1].strip() for line in body.splitlines()]
        self.assertEqual(phases, ["1", "2", "3", "4", "5"])

    def test_roadmap_bucket_holds_only_deferred(self):
        block = cap.project("MVP_ROADMAP_BOUNDARY", {"CAPABILITY_INCREMENTS": _json(self.rows)})
        roadmap_section = block.split("**On the roadmap")[1]
        self.assertIn("Supplier follow-up automation", roadmap_section)


class DeterminismTest(unittest.TestCase):
    def test_byte_identical_across_calls(self):
        rows = [
            _incr("A", "mvp", phase=1, agents="X"),
            _incr("B", "post_mvp_roadmap", phase=2, agents="Y"),
            _incr("C", "candidate_conditional", condition="later"),
        ]
        for fld in ("BUILD_PHASES_ROWS", "MVP_ROADMAP_BOUNDARY"):
            a = cap.project(fld, {"CAPABILITY_INCREMENTS": _json(rows)})
            b = cap.project(fld, {"CAPABILITY_INCREMENTS": _json(rows)})
            self.assertEqual(a, b)


class FailClosedTest(unittest.TestCase):
    def _err(self, raw):
        with self.assertRaises(cap.CapabilityProjectionError):
            cap.project("MVP_ROADMAP_BOUNDARY", {"CAPABILITY_INCREMENTS": raw})

    def test_missing_input(self):
        with self.assertRaises(cap.CapabilityProjectionError):
            cap.project("BUILD_PHASES_ROWS", {})

    def test_not_json(self):
        self._err("not json")

    def test_not_a_list(self):
        self._err(json.dumps({"capability": "x"}))

    def test_missing_capability(self):
        self._err(_json([{"release_bucket": "mvp", "phase": 1}]))

    def test_bad_bucket(self):
        self._err(_json([{"capability": "x", "release_bucket": "someday", "phase": 1}]))

    def test_committed_without_phase(self):
        self._err(_json([{"capability": "x", "release_bucket": "mvp"}]))

    def test_candidate_without_condition(self):
        self._err(_json([{"capability": "x", "release_bucket": "candidate_conditional"}]))

    def test_phase_bool_rejected(self):
        # bool is an int subclass in Python — must be rejected as a phase.
        self._err(_json([{"capability": "x", "release_bucket": "mvp", "phase": True}]))

    def test_empty_string(self):
        self._err("")


if __name__ == "__main__":
    unittest.main()
