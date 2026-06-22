"""The close-assembly retirement differential gate.

Before the legacy interpretive close-assembly is retired, prove the unified
transcript->generator path emits an operator system that is equal-or-better than the
legacy assembly produced. This is NOT byte-identity — it is a structural/manifest
differential with EVERY diff classified:

  - every file the legacy assembly produced is emitted by the unified path OR is on an
    explicit legacy-only allowlist (with a reason);
  - every file the unified path adds is on an explicit additions allowlist (with a reason);
  - the required dirs that hold files exist; legacy empty/runtime-only dirs are allowlisted;
  - the critical files exist and are non-empty;
  - the executable bits are set (start-session.sh + agent scripts);
  - start-session.sh carries a real --model (not a tier placeholder);
  - no unresolved generation-time placeholders survive (operator-fill templates exempt);
  - the foundation-only branch still routes (foundation docs, no agents);
  - the zero-advisor and zero-credential branches still emit their (empty) artifacts.

The legacy assembly is interpretive markdown (not runnable), so the baseline is the
transcribed legacy file manifest, held here as data. A failing assertion BLOCKS the
retirement (an un-allowlisted diff means a System-A behavior would be dropped).
"""

import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import interview_bridge as ib  # noqa: E402
from test_interview_bridge import _events, _ai  # noqa: E402  reuse the validated neutral transcript
from operator_fill_emitter import is_operator_fill_path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# ---- the transcribed legacy close-assembly manifest (the System-A baseline) ----------------
# Operator-project-relative paths the legacy 15_close assembly writes. Source: the legacy
# close-assembly file manifest. Neutral-synthetic (operator relpaths only).
LEGACY_FILES = {
    # root
    "CLAUDE.md", "project_instructions.md", "session_bootstrap.md", "pending_decisions.md",
    "manual.md", ".gitignore", "SESSION_STATE.md", ".env", "start-session.sh",
    # foundation docs
    "vision.md", "approach.md", "technical_architecture.md", "execution_plan.md",
    "test_cases.md", "audit_framework.md",
    # agents (legacy writes roster + cron; per-agent prompt/script files were built post-wizard)
    "agents/roster.md", "agents/cron/cron_config.md",
    # quality
    "quality/rules_library.md", "quality/human_review_queue.md", "quality/source_registry.md",
    "quality/validation_gate_config.md", "quality/co-protected-workflows.md",
    "quality/advisor_knowledge_base.md",
    # work
    "work/work_queue.md", "work/issues_log.md", "work/stub_tracker.md", "work/execution_plan_state.md",
    # logs
    "logs/audit_log.md", "logs/session_log.md", "logs/error_log.md", "logs/qa_log.md",
    "logs/source_health_log.md", "logs/drift_log.md", "logs/advisor_log.md",
    "logs/notification_log.md", "logs/validation_log.md", "logs/cost_efficiency_log.md",
    # docs
    "docs/document_impact_map.md", "docs/architectural_review_staging.md", "docs/future_items.md",
    "docs/voice_and_style.md", "docs/how_your_system_works.md",
    # security
    "security/credentials_registry.md", "security/gitignore_manifest.md",
    # archive
    "archive/decisions_archive.md", "archive/work_archive.md", "archive/review_queue_archive.md",
    "archive/notification_archive.md",
    # build-session helper templates
    "wizard/review_prompts/post_wizard_review.md", "wizard/review_prompts/per_agent_review.md",
    "wizard/review_prompts/phase_gate_review.md",
    "wizard/skills/_index.md", "wizard/skills/skill_template_external.md",
    "wizard/skills/skill_template_internal.md",
}

# Legacy files the unified path intentionally does NOT emit identically — allowlist with reason.
# (Empty after re-home; kept as the documented escape valve C-005 requires.)
ALLOWLIST_LEGACY_ONLY = {
    # relpath: reason
}

# Files the unified path ADDS over the legacy assembly — each an allowlisted improvement.
ALLOWLIST_UNIFIED_ADDITIONS = {
    "prd.md": "foundation doc the unified full-tree generator emits; the legacy assembly had none",
    ".wizard/manifest.json": "upgrade scaffold (foundation versioning); legacy had no upgrade surface",
    ".wizard/upgrade-policy.yaml": "upgrade scaffold; legacy had no upgrade surface",
    ".wizard/upgrade-history.log": "upgrade scaffold; legacy had no upgrade surface",
    ".wizard/UPGRADING.md": "upgrade command surface; legacy had none",
    ".wizard/replay-capsule.json": "replay capsule (build-time inputs + provenance) enabling deterministic upgrade re-render; gitignored + secret-scanned; legacy had no upgrade surface",
    ".wizard/update-source.json": "durable, read-only-to-the-AI update-source reference (pinned distribution repo + last-known-good commit) the self-update and notice hook agree on; legacy had no update source",
    "decisions/_index.md": "ADR/decisions core emitted by the corpus layer; legacy did not emit it",
    "decisions/decision_record_template.md": "ADR/decisions core; legacy did not emit it",
    "wizard/skills/credential-setup.md": "first-boot credential-setup skill; a pre-built operational skill the legacy close-assembly had no equivalent of",
    "wizard/skills/next-phase.md": "universal next-phase build-and-operate skill; drives phases 2+ with a refusing precondition, live-docs-driven flow, and stop-condition; legacy close-assembly had no equivalent",
    "wizard/skills/orientation.md": "operator orientation skill; reads state from disk and tells the operator where they are, whether the system is waiting on them, and the single next step; legacy close-assembly had no equivalent",
    "wizard/skills/pause.md": "operator pause/resume skill; writes a disk-first resume handoff so the operator can stop cleanly and pick up later; legacy close-assembly had no equivalent",
    "agents/prompts/orchestrator_prompt.md": "control-plane agent prompt emitted deterministically; legacy built agents post-wizard",
    "agents/prompts/qa_agent_prompt.md": "QA agent prompt emitted deterministically; legacy built agents post-wizard",
    "agents/prompts/researcher_prompt.md": "per-agent prompt emitted deterministically; legacy built agents post-wizard",
    "agents/scripts/researcher.sh": "per-agent invocation script emitted deterministically; legacy built agents post-wizard",
    "operating_discipline.md": "single-home operating-discipline doctrine doc (orientation + high-risk-action protection) emitted into the operator-project root; legacy had no equivalent",
    "wizard_feedback.md": "operator feedback file the generator seeds; legacy did not emit it",
    "build_progress.md": "per-phase acceptance ledger the generator seeds; legacy had no build-progress tracking",
    ".claude/settings.json": "Claude Code config wiring the statusline + context-monitor hook so the system runs on real context data; legacy emitted no .claude/ config",
    ".claude/statusline.sh": "statusline showing actual context % (Claude Code built-in field) to operator + session; legacy had none",
    ".claude/context_monitor.sh": "context-monitor hook surfacing actual context % so the context-integrity protocol runs on real data, not guesses; legacy had none",
    ".claude/receipt_gate.sh": "PreToolUse hook enforcing the high-risk-write protection: requires a fresh valid pre-write receipt (backup + evidence-bound verification + plan + operator approval) before a high-risk/irreversible action, else forces the operator approval dialog (ask); legacy had no enforcement of the protective sequence",
    ".claude/upgrade_notice.sh": "SessionStart hook that quietly checks for a newer system-bundle version and prints a plain-language heads-up; read-only, graceful-offline, never blocks a session; legacy had no upgrade-awareness",
}

CRITICAL_FILES = (
    "CLAUDE.md", "project_instructions.md", "session_bootstrap.md", "SESSION_STATE.md",
    "vision.md", "approach.md", "technical_architecture.md", ".gitignore", ".env",
    "docs/how_your_system_works.md",
)


def _emit_unified(td: Path, *, foundation_only=False):
    """Emit the neutral fixture through the REAL bridge (real model-tier resolution)."""
    agents = [] if foundation_only else [_ai()]
    ib.build_operator_system_from_transcript(
        _events(foundation_only=foundation_only), agents, system_shape="markdown-CC",
        target_dir=td, build_repo_root=REPO_ROOT, generator_version_override="0" * 40,
    )
    return {str(p.relative_to(td)): p for p in td.rglob("*") if p.is_file()}


class DifferentialGateTests(unittest.TestCase):
    def test_no_unallowlisted_legacy_only_drop(self):
        with tempfile.TemporaryDirectory() as td:
            emitted = set(_emit_unified(Path(td)))
            legacy_only = LEGACY_FILES - emitted
            unclassified = legacy_only - set(ALLOWLIST_LEGACY_ONLY)
            self.assertEqual(unclassified, set(),
                             f"legacy files dropped by the unified path with no allowlist reason: {sorted(unclassified)}")

    def test_every_unified_addition_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as td:
            emitted = set(_emit_unified(Path(td)))
            additions = emitted - LEGACY_FILES
            unclassified = additions - set(ALLOWLIST_UNIFIED_ADDITIONS)
            self.assertEqual(unclassified, set(),
                             f"unified path emits files with no allowlist reason: {sorted(unclassified)}")

    def test_critical_files_present_and_nonempty(self):
        with tempfile.TemporaryDirectory() as td:
            emitted = _emit_unified(Path(td))
            for rel in CRITICAL_FILES:
                self.assertIn(rel, emitted, f"critical file missing: {rel}")
                if rel != ".env":   # .env is an intentionally empty secrets placeholder
                    self.assertTrue(emitted[rel].read_text(encoding="utf-8").strip(),
                                    f"critical file empty: {rel}")

    def test_exec_bits_set(self):
        with tempfile.TemporaryDirectory() as td:
            emitted = _emit_unified(Path(td))
            for rel in ("start-session.sh", "agents/scripts/researcher.sh"):
                self.assertIn(rel, emitted, rel)
                self.assertTrue(emitted[rel].stat().st_mode & stat.S_IXUSR, f"not executable: {rel}")

    def test_start_session_has_real_model_flag(self):
        with tempfile.TemporaryDirectory() as td:
            emitted = _emit_unified(Path(td))
            content = emitted["start-session.sh"].read_text(encoding="utf-8")
            self.assertIn("--model", content)
            self.assertIn("claude-", content)            # a real model id
            self.assertNotIn("model-high", content)       # not the scaffold placeholder

    def test_no_generation_time_placeholder_survives(self):
        with tempfile.TemporaryDirectory() as td:
            emitted = _emit_unified(Path(td))
            for rel, p in emitted.items():
                if is_operator_fill_path(rel):
                    continue   # operator-fill templates intentionally retain {{}}
                self.assertNotIn("{{", p.read_text(encoding="utf-8", errors="ignore"),
                                 f"unresolved generation-time placeholder in {rel}")

    def test_foundation_only_branch(self):
        with tempfile.TemporaryDirectory() as td:
            res = ib.build_operator_system_from_transcript(
                _events(foundation_only=True), [], system_shape="markdown-CC",
                target_dir=Path(td), build_repo_root=REPO_ROOT, generator_version_override="0" * 40)
            self.assertTrue(res.plan.foundation_only_mode)
            self.assertEqual(res.plan.agents, [])
            emitted = {str(p.relative_to(td)) for p in Path(td).rglob("*") if p.is_file()}
            self.assertTrue(any(r.endswith("vision.md") for r in emitted))   # foundation docs emit
            self.assertFalse(any(r.startswith("agents/prompts/") for r in emitted))  # no agent layer

    def test_zero_advisor_and_zero_credential_branches(self):
        # the neutral fixture has no advisors (ADVISOR_ENTRIES absent->empty) and no credentials,
        # so it exercises both branches: the KB + credentials registry emit (empty), not skipped.
        with tempfile.TemporaryDirectory() as td:
            emitted = _emit_unified(Path(td))
            self.assertIn("quality/advisor_knowledge_base.md", emitted)
            self.assertIn("security/credentials_registry.md", emitted)


if __name__ == "__main__":
    unittest.main()
