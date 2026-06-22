"""Tests for the upgrade-scaffold emitter (stdlib unittest; pip-install-free).

emit_upgrade_scaffold computes the operator-project `.wizard/` upgrade scaffold
(manifest-v2 full-tree manifest + folded corpus authority + control-file
inventory + upgrade policy + history + command surface) over a STAGING tree that
has already been rendered. These tests assert: manifest-v2 covers the full tree
(not just foundation docs); hashes are sha256:-prefixed AND drift-clean through
the real compute_drift_report consumer; the corpus_authority sidecar is folded in
and retired; control files are inventoried but not merge-managed; unclassified
staged files fail closed; the scaffold is emitted deterministically; and
source_commit is resolved from the registry.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upgrade_scaffold_emitter import (  # noqa: E402
    emit_upgrade_scaffold, build_operator_manifest, classify_lifecycle,
    UpgradeScaffoldError, MANIFEST_SCHEMA_VERSION, LIFECYCLE_POLICY,
)
from emission_plan import load_contract, default_contract_path, validate_emission_plan  # noqa: E402
from corpus_loader import load_corpus_pack  # noqa: E402
from corpus_emitter import (  # noqa: E402
    render_claude_md_block, emit_rules_library, emit_decisions, inject_target_hooks,
)
from scaffold_emitter import emit_scaffold  # noqa: E402
from agent_emitter import emit_agent_layer  # noqa: E402
from upgrade import compute_drift_report  # noqa: E402
from test_emission_plan import _valid_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def _emit_base_tree(plan, staging, repo, records):
    """Render the operator system MINUS the upgrade scaffold (the orchestrator's
    pre-scaffold steps), so the scaffold emitter has a real tree to inventory."""
    block = render_claude_md_block(plan, records)
    emit_scaffold(plan, staging, repo, extra_inputs={"INHERITED_OPERATING_PRINCIPLES": block})
    emit_agent_layer(plan, staging, repo)
    emit_rules_library(plan, staging, repo, records=records)
    emit_decisions(plan, staging, repo)
    inject_target_hooks(plan, staging, records=records)


class UpgradeScaffoldEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())
        cls.records = load_corpus_pack()

    def _emit(self, into=None):
        plan = validate_emission_plan(_valid_plan(), self.contract)
        if into is None:
            self._tmp = tempfile.TemporaryDirectory()
            into = Path(self._tmp.name)
        _emit_base_tree(plan, into, REPO_ROOT, self.records)
        written = emit_upgrade_scaffold(plan, into, REPO_ROOT, records=self.records)
        return plan, into, written

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def _manifest(self, staging):
        import json
        return json.loads((staging / ".wizard/manifest.json").read_text())

    def test_manifest_emitted_as_v2_with_provenance(self):
        plan, staging, _ = self._emit()
        m = self._manifest(staging)
        self.assertEqual(m["manifest_schema_version"], MANIFEST_SCHEMA_VERSION)
        self.assertEqual(m["foundation_bundle_version"], plan.bundle_version)
        self.assertEqual(m["generator_version"], plan.generator_version)
        self.assertEqual(m["project_name"], plan.project_name)
        self.assertEqual(m["system_shape"], plan.system_shape)
        self.assertIn("source_commit", m)

    def test_manifest_covers_full_tree_not_just_foundation_docs(self):
        _, staging, _ = self._emit()
        managed = self._manifest(staging)["managed_files"]
        for rel in ["CLAUDE.md", "quality/rules_library.md", "SESSION_STATE.md",
                    "agents/prompts/orchestrator_prompt.md", "agents/scripts/researcher.sh",
                    "logs/audit_log.md", "decisions/decision_record_template.md",
                    ".wizard/UPGRADING.md"]:
            self.assertIn(rel, managed, f"manifest does not cover {rel}")

    def test_hashes_sha256_prefixed_and_drift_clean_through_consumer(self):
        # The critical producer/consumer-seam test: every base_hash must be
        # sha256:-prefixed AND match the actual staged bytes when read back through
        # the REAL drift consumer (bare hex would make every file report drift).
        _, staging, _ = self._emit()
        m = self._manifest(staging)
        for rel, meta in m["managed_files"].items():
            self.assertTrue(meta["base_hash"].startswith("sha256:"), f"{rel} base_hash not prefixed")
            self.assertEqual(meta["base_hash"], meta["current_hash_last_seen"], rel)
        report = compute_drift_report(staging, m)
        self.assertFalse(report.has_drift,
                         f"manifest reports drift on freshly-emitted tree: "
                         f"{[e.path for e in report.entries if e.status != 'no_drift']}")

    def test_managed_files_carry_live_lineage_version_at_emit(self):
        # Lineage guard: at emit the live file IS the current render, so every
        # managed file's live_lineage_version == the emitted bundle version. The
        # text-merge driver only auto-merges a file whose live descends from the
        # current render (live_lineage_version == current_version); a freshly emitted
        # tree must therefore be uniformly eligible.
        plan, staging, _ = self._emit()
        m = self._manifest(staging)
        self.assertTrue(m["managed_files"], "no managed files emitted")
        for rel, meta in m["managed_files"].items():
            self.assertEqual(
                meta.get("live_lineage_version"), plan.bundle_version,
                f"{rel}: live_lineage_version not stamped to the emitted bundle version",
            )

    def test_corpus_authority_folded_in_and_sidecar_retired(self):
        _, staging, _ = self._emit()
        m = self._manifest(staging)
        self.assertIn("corpus_authority", m)
        self.assertIn("cells", m["corpus_authority"])
        self.assertTrue(len(m["corpus_authority"]["cells"]) > 0)
        self.assertNotIn("_absorption_note", m["corpus_authority"])  # stale once embedded
        self.assertFalse((staging / ".wizard/corpus_authority.json").exists(),
                         "standalone corpus_authority.json sidecar should be retired")

    def test_control_files_inventoried_not_merge_managed(self):
        _, staging, _ = self._emit()
        m = self._manifest(staging)
        for cf in [".wizard/manifest.json", ".wizard/upgrade-policy.yaml",
                   ".wizard/upgrade-history.log"]:
            self.assertIn(cf, m["control_files"], f"{cf} not in control inventory")
            self.assertNotIn(cf, m["managed_files"], f"{cf} must not be merge-managed")

    def test_fail_closed_on_unclassified_staged_file(self):
        plan = validate_emission_plan(_valid_plan(), self.contract)
        self._tmp = tempfile.TemporaryDirectory()
        staging = Path(self._tmp.name)
        _emit_base_tree(plan, staging, REPO_ROOT, self.records)
        (staging / "MYSTERY_UNCLASSIFIED.md").write_text("stray\n")
        with self.assertRaises(UpgradeScaffoldError):
            emit_upgrade_scaffold(plan, staging, REPO_ROOT, records=self.records)

    def test_policy_history_and_command_surface_emitted(self):
        _, staging, _ = self._emit()
        for rel in [".wizard/upgrade-policy.yaml", ".wizard/upgrade-history.log",
                    ".wizard/UPGRADING.md"]:
            self.assertTrue((staging / rel).exists(), f"missing scaffold artifact: {rel}")

    def test_source_commit_resolved_from_registry(self):
        _, staging, _ = self._emit()
        # plan.bundle_version == v0.6.0 -> registry source_commit 7ba3f48
        self.assertEqual(self._manifest(staging)["source_commit"], "7ba3f48")

    def test_emission_deterministic(self):
        a = Path(tempfile.mkdtemp())
        b = Path(tempfile.mkdtemp())
        self._emit(into=a)
        self._emit(into=b)
        self.assertEqual((a / ".wizard/manifest.json").read_bytes(),
                         (b / ".wizard/manifest.json").read_bytes())

    def test_classify_lifecycle_fail_closed(self):
        self.assertEqual(classify_lifecycle("logs/audit_log.md"), "runtime_state")
        self.assertEqual(classify_lifecycle("CLAUDE.md"), "inherited_content")
        self.assertEqual(classify_lifecycle("security/credentials_registry.md"), "operator_config")
        with self.assertRaises(UpgradeScaffoldError):
            classify_lifecycle("totally_unknown_root_file.md")

    def test_operator_owned_files_classify_to_operator_review(self):
        """Operator-state clobber fix: a file the operator or the system WRITES during operation must
        stamp merge_strategy=operator_review in the fresh-emit manifest (single source
        of truth with the bundle contract) so a global --ack can never clobber it.
        Principle: operator/system-written -> not warn_on_drift."""
        operator_owned = (
            "quality/rules_library.md",
            "quality/source_registry.md",
            "quality/advisor_knowledge_base.md",
            "quality/validation_gate_config.md",
            "quality/co-protected-workflows.md",
            "quality/human_review_queue.md",
            "docs/future_items.md",
            "docs/architectural_review_staging.md",
            "docs/document_impact_map.md",
            "agents/cron/cron_config.md",
        )
        for rel in operator_owned:
            lifecycle = classify_lifecycle(rel)
            self.assertEqual(
                LIFECYCLE_POLICY[lifecycle]["merge_strategy"], "operator_review",
                f"{rel} classifies to {lifecycle!r} (merge_strategy="
                f"{LIFECYCLE_POLICY[lifecycle]['merge_strategy']!r}); operator/system-written "
                f"files must resolve to operator_review, not warn_on_drift",
            )


class ScaffoldGuardTests(unittest.TestCase):
    """Fail-closed guards: empty source_commit + symlinks in the staged tree."""

    def test_resolve_source_commit_fails_closed_on_empty(self):
        from upgrade_scaffold_emitter import _resolve_source_commit  # noqa: E402
        import json
        contract = load_contract(default_contract_path())
        plan = validate_emission_plan(_valid_plan(), contract)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        reg = root / "wizard" / "registry"
        reg.mkdir(parents=True)
        # registry entry for the plan's bundle_version with NO source_commit
        (reg / "foundation-bundles.json").write_text(json.dumps({
            "bundles": [{"foundation_bundle_version": plan.bundle_version, "path": "x"}]
        }), encoding="utf-8")
        with self.assertRaises(UpgradeScaffoldError):
            _resolve_source_commit(plan, root)

    def test_staged_walk_rejects_symlink(self):
        from upgrade_scaffold_emitter import _staged_content_files  # noqa: E402
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name)
        (staging / "real.md").write_text("ok", encoding="utf-8")
        (staging / "link.md").symlink_to(staging / "real.md")
        with self.assertRaises(UpgradeScaffoldError):
            _staged_content_files(staging)


class FoundationDocLifecycleTests(unittest.TestCase):
    """The 4-bucket foundation-doc lifecycle classification faithfully reproduces
    the hash-baseline contract's per-doc policy (vision is shared/EXPECTED, but
    approach/technical_architecture are shared/ALLOWED — distinct buckets)."""

    EXPECTED = {
        "vision.md": "foundation_shared_expected",
        "approach.md": "foundation_shared_allowed",
        "technical_architecture.md": "foundation_shared_allowed",
        "prd.md": "foundation_operator",
        "execution_plan.md": "foundation_operator",
        "test_cases.md": "foundation_operator",
        "audit_framework.md": "foundation_wizard",
    }

    def test_each_foundation_doc_classifies(self):
        for doc, lifecycle in self.EXPECTED.items():
            self.assertEqual(classify_lifecycle(doc), lifecycle, doc)

    def test_policy_parity_with_hash_baseline_contract(self):
        """The classifier's resolved foundation-doc policy must equal the
        hash-baseline contract per doc (guards transcription drift — NOT the
        deferred plan-policy integration; a drift guard)."""
        import json
        contract = json.loads(
            (REPO_ROOT / "wizard" / "foundation-bundles" / "v0" / "contracts"
             / "foundation-manifest-hash-baseline-v1.json").read_text(encoding="utf-8")
        )
        for d in contract["required_foundation_docs"]:
            doc = d["path"][len("foundation/"):]  # "foundation/vision.md" -> "vision.md"
            policy = LIFECYCLE_POLICY[classify_lifecycle(doc)]
            self.assertEqual(policy["managed_by"], d["managed_by"], doc)
            self.assertEqual(policy["local_modifications"], d["local_modifications"], doc)
            self.assertEqual(policy["merge_strategy"], d["merge_strategy"], doc)


if __name__ == "__main__":
    unittest.main()
