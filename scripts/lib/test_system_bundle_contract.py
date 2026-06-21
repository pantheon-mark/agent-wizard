"""Tests for the system-bundle managed-artifacts contract (system-artifacts.json).

The bundle's `system-artifacts.json` is the SUPPLY-SIDE contract that declares, for
every emitted operator-project file, how an upgrade should produce it: its
render_kind (copy/render), the bundle-resident template it renders from, the merge
strategy, the file mode, and (for render files) which inputs are persisted in the
replay capsule vs derived from the target bundle.

The closed expected file set below is transcribed from the build-side artifact
inventory (the closed list of every emitted operator-project file) — the 87 MANAGED
operator-project files (91 emitted minus the 4 control files, which are upgrade
machinery, not delivered content). The contract is CLOSED + fail-closed: every
managed file must have exactly one entry; no file omitted; no extra entries.

Stdlib unittest; pip-install-free.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parents[3]
BUNDLE_VERSION = "v0.5.0"
BUNDLE_DIR = REPO_ROOT / "wizard" / "foundation-bundles" / BUNDLE_VERSION
CONTRACT_PATH = BUNDLE_DIR / "system-artifacts.json"

VALID_RENDER_KIND = {"copy", "render"}
VALID_MERGE_STRATEGY = {"three_way", "operator_review", "warn_on_drift", "frozen"}
VALID_MODE = {"0644", "0755"}
VALID_DELIVERY = {"wizard", "operator_derived"}

# operator_derived files (operator-owned content) — tracked for drift only, NEVER
# delivered/overwritten by an upgrade; they keep their existing Python emit path and
# are NOT bundle-template-sourced. They must carry merge_strategy=operator_review.
EXPECTED_OPERATOR_DERIVED = frozenset({
    "prd.md",
    "agents/roster.md",
    "agents/acceptance/phase_01_acceptance.md",
    "agents/acceptance/phase_02_acceptance.md",
    "agents/acceptance/phase_03_acceptance.md",
    "agents/acceptance/phase_04_acceptance.md",
})

# Entries whose body is produced by a Python control-plane emitter (not a bundle
# template) — they carry source="control_plane" and have NO resolving template_path.
CONTROL_PLANE_RELPATHS = frozenset({".wizard/UPGRADING.md"})

# ---------------------------------------------------------------------------
# Closed expected managed-file set — transcribed from the build-side artifact
# inventory (the closed list of emitted operator-project files). 87 managed files.
# The 4 control files (.wizard/manifest.json, .wizard/replay-capsule.json,
# .wizard/upgrade-history.log, .wizard/upgrade-policy.yaml) are EXCLUDED — they
# are upgrade machinery, not delivered content.
# ---------------------------------------------------------------------------
EXPECTED_MANAGED_FILES = frozenset({
    # Foundation docs (pre-existing upgrade surface)
    "vision.md",
    "approach.md",
    "technical_architecture.md",
    "execution_plan.md",
    "test_cases.md",
    "audit_framework.md",
    "prd.md",
    # Root-level scaffold
    "CLAUDE.md",
    "project_instructions.md",
    "manual.md",
    "operating_discipline.md",
    "session_bootstrap.md",
    "pending_decisions.md",
    "build_progress.md",
    ".gitignore",
    "start-session.sh",
    ".env",
    "SESSION_STATE.md",
    "wizard_feedback.md",
    # .claude/ config
    ".claude/settings.json",
    ".claude/statusline.sh",
    ".claude/context_monitor.sh",
    ".claude/receipt_gate.sh",
    # agents/ prompts
    "agents/prompts/orchestrator_prompt.md",
    "agents/prompts/qa_agent_prompt.md",
    "agents/prompts/coordinator_prompt.md",
    "agents/prompts/call-notes-helper_prompt.md",
    "agents/prompts/drafting-helper_prompt.md",
    "agents/prompts/master-list-keeper_prompt.md",
    "agents/prompts/prep-helper_prompt.md",
    "agents/prompts/research-helper_prompt.md",
    # agents/ scripts
    "agents/scripts/coordinator.sh",
    "agents/scripts/call-notes-helper.sh",
    "agents/scripts/drafting-helper.sh",
    "agents/scripts/master-list-keeper.sh",
    "agents/scripts/prep-helper.sh",
    "agents/scripts/research-helper.sh",
    # agents/ other
    "agents/cron/cron_config.md",
    "agents/roster.md",
    "agents/acceptance/phase_01_acceptance.md",
    "agents/acceptance/phase_02_acceptance.md",
    "agents/acceptance/phase_03_acceptance.md",
    "agents/acceptance/phase_04_acceptance.md",
    # docs/
    "docs/future_items.md",
    "docs/voice_and_style.md",
    "docs/architectural_review_staging.md",
    "docs/document_impact_map.md",
    "docs/how_your_system_works.md",
    # logs/
    "logs/cost_efficiency_log.md",
    "logs/advisor_log.md",
    "logs/audit_log.md",
    "logs/drift_log.md",
    "logs/error_log.md",
    "logs/notification_log.md",
    "logs/qa_log.md",
    "logs/session_log.md",
    "logs/source_health_log.md",
    "logs/validation_log.md",
    # quality/
    "quality/rules_library.md",
    "quality/advisor_knowledge_base.md",
    "quality/source_registry.md",
    "quality/validation_gate_config.md",
    "quality/co-protected-workflows.md",
    "quality/human_review_queue.md",
    # security/
    "security/credentials_registry.md",
    "security/gitignore_manifest.md",
    # work/
    "work/stub_tracker.md",
    "work/execution_plan_state.md",
    "work/issues_log.md",
    "work/work_queue.md",
    # archive/
    "archive/decisions_archive.md",
    "archive/notification_archive.md",
    "archive/review_queue_archive.md",
    "archive/work_archive.md",
    # decisions/
    "decisions/_index.md",
    "decisions/decision_record_template.md",
    # wizard/ (operator_fill + review prompts + skills)
    "wizard/review_prompts/per_agent_review.md",
    "wizard/review_prompts/phase_gate_review.md",
    "wizard/review_prompts/post_wizard_review.md",
    "wizard/skills/_index.md",
    "wizard/skills/credential-setup.md",
    "wizard/skills/next-phase.md",
    "wizard/skills/orientation.md",
    "wizard/skills/pause.md",
    "wizard/skills/skill_template_external.md",
    "wizard/skills/skill_template_internal.md",
    # .wizard/ upgrade scaffold (managed; control files excluded)
    ".wizard/UPGRADING.md",
})


class SystemArtifactsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.artifacts = cls.contract["artifacts"]
        cls.by_relpath = {a["relpath"]: a for a in cls.artifacts}

    def test_system_artifacts_contract_covers_full_inventory(self):
        """(a) parses; (b) declares an entry for EVERY managed file in the A0
        inventory (closed — no file omitted, no extra entry); (c) each entry has
        required keys with valid enum values; (d) every render entry has non-empty
        inputs.persisted + inputs.derived; (e) every template_path resolves to an
        existing file inside the bundle."""
        # (a) parses + basic shape
        self.assertEqual(self.contract.get("contract_id"), "system-artifacts")
        self.assertEqual(self.contract.get("bundle_version"), BUNDLE_VERSION)
        self.assertIsInstance(self.artifacts, list)

        declared = set(self.by_relpath)
        # No duplicate relpaths
        self.assertEqual(
            len(self.artifacts), len(declared),
            "duplicate relpath entries in system-artifacts.json",
        )

        # (b) CLOSED coverage: declared == expected (fail-closed both directions)
        missing = EXPECTED_MANAGED_FILES - declared
        extra = declared - EXPECTED_MANAGED_FILES
        self.assertEqual(missing, set(), f"inventory files MISSING from contract: {sorted(missing)}")
        self.assertEqual(extra, set(), f"contract has EXTRA files not in inventory: {sorted(extra)}")

        for relpath, entry in self.by_relpath.items():
            control_plane = relpath in CONTROL_PLANE_RELPATHS
            # (c) required keys + valid enums. delivery is required on every entry.
            required_keys = ["relpath", "render_kind", "merge_strategy", "mode", "delivery"]
            if not control_plane:
                required_keys.append("template_path")
            for key in required_keys:
                self.assertIn(key, entry, f"{relpath}: missing key {key!r}")
            self.assertEqual(entry["relpath"], relpath)
            self.assertIn(entry["render_kind"], VALID_RENDER_KIND, f"{relpath}: bad render_kind")
            self.assertIn(entry["merge_strategy"], VALID_MERGE_STRATEGY, f"{relpath}: bad merge_strategy")
            self.assertIn(entry["mode"], VALID_MODE, f"{relpath}: bad mode")
            self.assertIn(entry["delivery"], VALID_DELIVERY, f"{relpath}: bad delivery")

            # control-plane entries are Python-emitted, not template-sourced: they carry
            # source="control_plane" and no template_path.
            if control_plane:
                self.assertEqual(entry.get("source"), "control_plane",
                                 f"{relpath}: control-plane entry must declare source=control_plane")
                self.assertNotIn("template_path", entry,
                                 f"{relpath}: control-plane entry must not carry a template_path")

            # (d) render entries declare non-empty persisted + derived
            if entry["render_kind"] == "render":
                inputs = entry.get("inputs")
                self.assertIsInstance(inputs, dict, f"{relpath}: render entry missing inputs")
                persisted = inputs.get("persisted")
                derived = inputs.get("derived")
                self.assertIsInstance(persisted, list, f"{relpath}: inputs.persisted not a list")
                self.assertIsInstance(derived, list, f"{relpath}: inputs.derived not a list")
                self.assertTrue(persisted, f"{relpath}: render entry has empty inputs.persisted")
                self.assertTrue(derived, f"{relpath}: render entry has empty inputs.derived")

            # (e) template_path resolves inside the bundle (skip control-plane entries).
            if not control_plane:
                tpl = BUNDLE_DIR / entry["template_path"]
                self.assertTrue(
                    tpl.is_file(),
                    f"{relpath}: template_path {entry['template_path']!r} does not resolve to a "
                    f"file inside the bundle ({tpl})",
                )
                # template_path must be inside the bundle (no traversal)
                self.assertTrue(
                    str(tpl.resolve()).startswith(str(BUNDLE_DIR.resolve()) + "/"),
                    f"{relpath}: template_path escapes the bundle",
                )

    def test_executable_scripts_have_0755_mode(self):
        """.sh hooks/scripts carry 0755; everything else 0644 (file-mode metadata)."""
        for relpath, entry in self.by_relpath.items():
            expected = "0755" if relpath.endswith(".sh") else "0644"
            self.assertEqual(
                entry["mode"], expected,
                f"{relpath}: mode should be {expected} (got {entry['mode']})",
            )

    def test_delivery_field_partitions_wizard_vs_operator_derived(self):
        """Every entry carries a valid `delivery`; the operator_derived set is exactly
        the expected operator-owned files; operator_derived ⟹ merge_strategy=operator_review
        (operator content is tracked for drift only, never delivered/overwritten); and
        every other (wizard-authored) entry is delivery=wizard (IN the upgrade surface)."""
        declared_operator_derived = {
            r for r, e in self.by_relpath.items() if e.get("delivery") == "operator_derived"
        }
        self.assertEqual(
            declared_operator_derived, set(EXPECTED_OPERATOR_DERIVED),
            "operator_derived set diverges from the controller-declared set "
            f"(only-in-contract={sorted(declared_operator_derived - EXPECTED_OPERATOR_DERIVED)}, "
            f"only-expected={sorted(EXPECTED_OPERATOR_DERIVED - declared_operator_derived)})",
        )
        for relpath, entry in self.by_relpath.items():
            self.assertIn(entry.get("delivery"), VALID_DELIVERY, f"{relpath}: bad/missing delivery")
            if entry["delivery"] == "operator_derived":
                self.assertEqual(
                    entry["merge_strategy"], "operator_review",
                    f"{relpath}: operator_derived MUST be merge_strategy=operator_review",
                )
            else:
                self.assertEqual(entry["delivery"], "wizard",
                                 f"{relpath}: non-operator_derived must be delivery=wizard")

    def test_copy_entries_have_no_render_inputs(self):
        """copy entries do not carry render inputs (or carry empty input lists)."""
        for relpath, entry in self.by_relpath.items():
            if entry["render_kind"] == "copy":
                inputs = entry.get("inputs", {})
                self.assertFalse(
                    inputs.get("persisted") or inputs.get("derived"),
                    f"{relpath}: copy entry should not declare render inputs",
                )

    def test_render_templates_contain_at_least_one_placeholder(self):
        """Every render entry's template must contain at least one {{ placeholder.

        A render_kind='render' entry with no {{ in its template has nothing to
        substitute — the distinction from 'copy' is incoherent and will confuse
        the upgrade engine.  If a template has no placeholders, the entry must
        be reclassified to render_kind='copy'.
        """
        for relpath, entry in self.by_relpath.items():
            if entry["render_kind"] == "render":
                tpl_path = BUNDLE_DIR / entry["template_path"]
                content = tpl_path.read_text(encoding="utf-8")
                self.assertIn(
                    "{{",
                    content,
                    f"{relpath}: render_kind='render' but template "
                    f"{entry['template_path']!r} contains no '{{{{' placeholder — "
                    f"reclassify to render_kind='copy' and remove the inputs block",
                )


if __name__ == "__main__":
    unittest.main()
