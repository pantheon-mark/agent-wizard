"""Content tests for Task 10 (external-write-gate-generalization slice)'s changes to
wizard/skills/add-capability.md:

  1. F-33 fix: any option this skill offers must be phrased in the operator's own
     voice ("Have the assistant ...") never in the assistant's first person ("I ...") —
     because a downstream harness classifier misreads first-person "I" as the operator
     volunteering to do the action themselves (the real dogfood failure this closes).
  2. Task 9's pending-migration paragraph (Step A) must still be present (Task 10 must
     not undo it) and must now describe the id-matching convention that lets
     acceptance auto-close the entry, rather than a manual "remove it from the file"
     instruction.
  3. Step F must instruct emitting the gate-wired-by-construction code scaffold
     (capability_code_scaffold.py) for any capability with an externally-touching
     allowed action, BEFORE landing the typed descriptor / handing off to next-phase.
  4. Task B4 (F-77, Cut 1.1 Cluster B): a pending-migration entry is a rebuild of an
     EXISTING capability, not a new one -- this skill's Step A must redirect it (and a
     health-probe-caught red capability with no matching entry) to the dedicated
     rebuild-paused-capability skill rather than absorbing it into this skill's own
     "what should this help with?" interview, which is the exact dead-end F-77 named.
     This supersedes item 2's id-matching-for-a-new-declaration framing: the id-matching
     / auto-close mechanic itself is unchanged (still documented here, since Step A is
     where the operator first learns about it), but it now describes the
     rebuild-paused-capability skill keeping the SAME id, not this skill's interview
     producing a redeclared one.

These are content-presence assertions against the live skill source, mirroring the
established convention in test_task7_design_outbound_message.py.
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "wizard" / "skills"
ADD_CAPABILITY_PATH = SKILLS_DIR / "add-capability.md"


def _text() -> str:
    return ADD_CAPABILITY_PATH.read_text(encoding="utf-8")


class TestSkillExists(unittest.TestCase):
    def test_add_capability_skill_exists(self):
        self.assertTrue(ADD_CAPABILITY_PATH.is_file())


class TestUserVoiceGuidance(unittest.TestCase):
    """F-33: emitted/asked options must be phrased in the operator's voice."""

    def test_f33_reference_present(self):
        self.assertIn("F-33", _text())

    def test_user_voice_example_present(self):
        text = _text()
        self.assertIn("Have the assistant find and label them", text)

    def test_forbids_first_person_option_phrasing(self):
        text = _text()
        self.assertIn("never in the assistant's first person", text)
        # The canonical bad example this rule exists to prevent must be named explicitly,
        # so the guidance is concrete rather than abstract.
        self.assertIn('"I find and label them"', text)

    def test_explains_why_not_a_style_preference(self):
        text = _text()
        self.assertIn("classifier", text)
        self.assertIn("safety classifier", text)

    def test_guidance_scoped_to_every_option_not_just_the_interview(self):
        text = _text()
        self.assertIn("Step B's possibilities", text)
        self.assertIn("Step C proposal", text)

    def test_guidance_lives_in_step_b(self):
        text = _text()
        step_b_idx = text.index("## Step B")
        step_c_idx = text.index("## Step C")
        voice_idx = text.index("F-33")
        self.assertTrue(step_b_idx < voice_idx < step_c_idx,
                        "the user-voice rule should live in Step B, where options are "
                        "first offered")


class TestPendingMigrationAutoClose(unittest.TestCase):
    """Task 9's Step-A addition must survive (not be undone) and now describe
    automatic closure via id-matching, not a manual file edit."""

    def test_step_a_pending_migration_check_still_present(self):
        text = _text()
        self.assertIn("agents/handoffs/pending_migrations.json", text)
        self.assertIn("Also check for a pending migration.", text)

    def test_id_matching_convention_documented(self):
        text = _text()
        self.assertIn("mechanism_id", text)
        self.assertIn("same id", text)

    def test_no_longer_instructs_manual_file_removal(self):
        # The old Task-9 instruction told the skill-runner to hand-edit the queue file;
        # Task 10 replaces that with automatic closure at acceptance time.
        text = _text()
        self.assertNotIn("remove it from the file — the migration is done, not still pending",
                        text)

    def test_explains_automatic_closure(self):
        text = _text()
        self.assertIn("close itself automatically", text)
        self.assertIn("never edit `pending_migrations.json` by hand", text)


class TestRebuildPausedCapabilityRouting(unittest.TestCase):
    """Task B4 (F-77): add-capability's scope is a genuinely new capability
    only. A pending-migration entry (or a health-probe-caught red capability
    with no matching entry) must redirect to the dedicated
    rebuild-paused-capability skill rather than being absorbed into this
    skill's own "what should this help with?" interview -- the exact
    dead-end F-77 named."""

    def test_frontmatter_names_the_rebuild_flow_as_out_of_scope(self):
        text = _text()
        frontmatter = text[: text.index("---", 3)]
        self.assertIn("rebuild-paused-capability", frontmatter)

    def test_does_not_section_excludes_rebuilding_a_paused_capability(self):
        text = _text()
        does_not_idx = text.index("**It does not:**")
        step_a_idx = text.index("## Step A")
        does_not_section = text[does_not_idx:step_a_idx]
        self.assertIn("rebuild-paused-capability", does_not_section)

    def test_step_a_hands_off_to_the_rebuild_flow(self):
        text = _text()
        step_a_idx = text.index("## Step A")
        step_b_idx = text.index("## Step B")
        step_a_text = text[step_a_idx:step_b_idx]
        self.assertIn("rebuild-paused-capability", step_a_text)
        # Both the queue-entry path and the health-probe-only path must
        # redirect the same way -- neither is absorbed into this interview.
        self.assertEqual(step_a_text.count("rebuild-paused-capability"), 2)

    def test_no_longer_treats_a_pending_migration_as_an_interview_candidate(self):
        # The exact F-77 bug shape: routing a paused/migration-flagged
        # capability into this skill's own "what should this help with?"
        # interview must not reappear.
        text = _text()
        self.assertNotIn('live candidate for "what should this help with?"', text)


class TestGateWiredScaffoldEmission(unittest.TestCase):
    """Step F must run the deterministic code emitter for any capability with an
    externally-touching allowed action, before the typed descriptor is landed."""

    def test_scaffold_emitter_invocation_present(self):
        text = _text()
        self.assertIn("capability_code_scaffold.py", text)
        self.assertIn("--spec", text)
        self.assertIn("--project-root", text)

    def test_action_classes_that_trigger_scaffold_emission_are_named(self):
        text = _text()
        for action_class in ("mutate", "delete", "send-execute", "synchronize",
                             "retain-archive"):
            self.assertIn(action_class, text)

    def test_explains_why_not_freehand(self):
        text = _text()
        self.assertIn("gate-wired", text)
        self.assertIn("freehand", text)

    def test_scaffold_step_precedes_landing_the_typed_record(self):
        text = _text()
        scaffold_idx = text.index("capability_code_scaffold.py")
        land_idx = text.index("Land the typed record and teach the guard")
        self.assertLess(scaffold_idx, land_idx,
                        "gate-wired code must be emitted before (or as part of the same "
                        "cascade as) landing the typed descriptor, never after")

    def test_read_only_skip_case_documented(self):
        text = _text()
        self.assertIn("skip this step", text)


if __name__ == "__main__":
    unittest.main()
