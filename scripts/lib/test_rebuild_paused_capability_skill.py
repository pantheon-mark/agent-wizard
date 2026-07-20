"""Content-presence test for rebuild-paused-capability.md (Task B4 — Cut 1.1
Cluster B, F-77).

Root cause this guards against (F-77): a contract-changing upgrade pauses an
existing operator capability and queues a migration, but the reconcile
queue's `suggested_next_step` used to point the operator at the
`add-capability` skill — whose own scope is new capabilities only. A naive
operator (or agent) following that pointer hits add-capability's Step B
interview ("what should this help with?") for something that already has a
business purpose and doesn't need re-designing, and dead-ends.

The fix is a dedicated `rebuild-paused-capability` skill the queue now points
at instead: it reads the pending-migration entry and drives reconcile ->
(B2 stub repair if needed) -> proof -> accept (`record_operator_acceptance`,
via `operator_acceptance.py`) -> live-readiness, composing already-landed
machinery rather than rebuilding any of it, and never re-running a business
interview on an existing capability.

This test locks the skill's content, not its exact wording — mirrors the
content-presence style of test_triage_review_guidance.py (D6b) and
test_task10_add_capability_gate_wired.py.

Stdlib unittest; pip-install-free.
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "wizard" / "skills"
REBUILD_SKILL_PATH = SKILLS_DIR / "rebuild-paused-capability.md"


class RebuildPausedCapabilitySkillTests(unittest.TestCase):

    def setUp(self):
        self.assertTrue(
            REBUILD_SKILL_PATH.is_file(),
            f"expected {REBUILD_SKILL_PATH} to exist",
        )
        self.text = REBUILD_SKILL_PATH.read_text(encoding="utf-8")

    # -- frontmatter is a routing signal -----------------------------------

    def test_has_single_line_yaml_frontmatter_description(self):
        lines = self.text.splitlines()
        self.assertEqual(lines[0], "---")
        # description must be entirely on ONE line (multi-line silently
        # disappears -- same convention every other emitted skill follows).
        desc_line = next(l for l in lines[1:6] if l.startswith("description:"))
        self.assertIn('"', desc_line)

    def test_description_names_the_pending_migrations_trigger(self):
        self.assertIn("pending_migrations.json", self.text)

    def test_description_names_capability_health_trigger(self):
        self.assertIn("capability_health", self.text)

    def test_description_excludes_new_capability_scope(self):
        # Routing signal must be clearly distinguished from add-capability's
        # scope, so an orchestrator does not pick the wrong skill. This must
        # assert the actual EXCLUSION sentence, not just that "add-capability"
        # appears somewhere in the frontmatter -- a bare mention (e.g. "hands
        # off here from add-capability") would satisfy assertIn without ever
        # stating the scope boundary, and this test would then pass even if
        # the exclusion sentence itself were deleted.
        frontmatter_end = self.text.index("---", 3)
        frontmatter = self.text[: frontmatter_end]
        self.assertIn(
            "Not for setting up a capability that never existed before", frontmatter,
            "frontmatter must explicitly say this flow is NOT for a new capability "
            "and must direct that case to add-capability instead",
        )
        self.assertIn("use add-capability for that", frontmatter)
        self.assertIn("next-phase", frontmatter)

    # -- (a) covers reconcile -> stub-repair -> proof -> accept ->
    # live-readiness, composing already-landed machinery -------------------

    def test_reads_the_pending_migrations_queue(self):
        self.assertIn("agents/handoffs/pending_migrations.json", self.text)
        self.assertIn("mechanism_id", self.text)

    def test_covers_the_b2_stub_repair_conditionally(self):
        self.assertIn("missing_evidence_predicates", self.text)
        self.assertIn("NotImplementedError", self.text)

    def test_never_instructs_a_fake_passing_stub(self):
        # Same anti-trust-theater rule B2's scaffold itself follows: a stall
        # (honestly still paused) is correct; a fake passing check is not.
        lower = self.text.lower()
        self.assertIn("never fake a passing", lower)
        self.assertIn("stays paused is correct", lower)

    def test_references_the_self_qa_check(self):
        self.assertIn("capability_invariants.py", self.text)

    def test_references_the_copy_run_proof(self):
        self.assertIn("copy_run_proof", self.text)
        self.assertIn("apply", self.text.lower())
        self.assertIn("undo", self.text.lower())

    def test_references_operator_acceptance_and_record_operator_acceptance_path(self):
        self.assertIn("operator_acceptance.py", self.text)
        self.assertIn("--operator-confirmation", self.text)

    def test_explains_the_entry_closes_itself_via_matching_id(self):
        self.assertIn("mechanism_id", self.text)
        self.assertIn("closes", self.text.lower())
        self.assertIn("never edit", self.text.lower())

    def test_references_live_readiness_confirmation(self):
        self.assertIn("capability_health", self.text)
        self.assertIn("green", self.text.lower())

    def test_document_order_is_reconcile_then_repair_then_proof_then_accept_then_health(self):
        find = self.text.index
        idx_reconcile = find("pending_migrations.json")
        idx_repair = find("missing_evidence_predicates")
        idx_proof = find("copy_run_proof")
        idx_accept = find("operator_acceptance.py")
        idx_health_final = self.text.rindex("capability_health")
        self.assertLess(idx_reconcile, idx_repair)
        self.assertLess(idx_repair, idx_proof)
        self.assertLess(idx_proof, idx_accept)
        self.assertLess(idx_accept, idx_health_final)

    # -- (b) plain language -- no jargon, no traceback ----------------------

    def test_states_operator_is_non_technical(self):
        self.assertIn("non-technical", self.text)

    def test_no_traceback_or_raw_error_language_directed_at_operator(self):
        for jargon in ("traceback", "stack trace", "exit code", "AST"):
            self.assertNotIn(jargon, self.text)

    def test_no_bare_menu_language(self):
        # This flow makes exactly one ask of the operator (the go-ahead) --
        # it must not turn into a menu of technical choices.
        self.assertNotIn("choose one of the following", self.text.lower())

    # -- (c) generalizable / shape-neutral -- no domain-specific text -------

    def test_no_domain_specific_examples(self):
        lower = self.text.lower()
        for banned in ("gmail", "estate", "inbox_management", "acme_widget"):
            self.assertNotIn(banned, lower)

    # -- does not re-run a business interview -------------------------------

    def test_explicitly_scoped_away_from_redesign_interview(self):
        lower = self.text.lower()
        self.assertIn("does not", lower)
        self.assertIn("interview", lower)


if __name__ == "__main__":
    unittest.main()
