"""Integration tests for the operator-system orchestrator (stdlib unittest).

emit_operator_system composes the scaffold + agent layer + corpus into one
complete runnable operator system in a staging dir. These tests assert the full
tree is present, the corpus block landed in CLAUDE.md (not the standalone stub),
hooks were injected, NO {{KEY}} survives anywhere, the emitted tree carries no
build provenance, and the whole emission is deterministic (emit twice ->
byte-identical).
"""

import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from operator_system_emitter import emit_operator_system  # noqa: E402
from emission_plan import load_contract, default_contract_path, validate_emission_plan  # noqa: E402
from generator import PLACEHOLDER_RE  # noqa: E402
from test_emission_plan import _valid_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# Build-provenance markers that must never appear in a distributed operator
# system. Assembled from fragments so this test file — itself distributed under
# wizard/ — does not trip the public-boundary scanner on its own assertion data.
FORBIDDEN_PROVENANCE = [
    "governance" + "/", "external_review" + "/", "ADR" + "-", "IDQ" + "-",
    "S2" + ".", "AWB",
]


class OperatorSystemEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _emit(self, into=None):
        plan = validate_emission_plan(_valid_plan(), self.contract)
        if into is None:
            self._tmp = tempfile.TemporaryDirectory()
            into = Path(self._tmp.name)
        written = emit_operator_system(plan, into, REPO_ROOT)
        return into, written

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_full_runnable_tree_present(self):
        staging, _ = self._emit()
        for rel in [
            "CLAUDE.md", "project_instructions.md", "start-session.sh", "SESSION_STATE.md",
            "quality/rules_library.md", "quality/validation_gate_config.md",
            "decisions/decision_record_template.md", "decisions/_index.md",
            ".wizard/manifest.json", ".wizard/upgrade-policy.yaml",
            ".wizard/upgrade-history.log", ".wizard/UPGRADING.md",
            "agents/prompts/orchestrator_prompt.md", "agents/prompts/qa_agent_prompt.md",
            "agents/prompts/researcher_prompt.md", "agents/scripts/researcher.sh",
            "logs/audit_log.md",
            # foundation docs at ROOT (wired in via emit_foundation_docs)
            "vision.md", "approach.md", "execution_plan.md", "technical_architecture.md",
            "test_cases.md", "audit_framework.md", "prd.md",
        ]:
            self.assertTrue((staging / rel).exists(), f"missing emitted artifact: {rel}")

    def test_upgrade_scaffold_folds_authority_and_retires_sidecar(self):
        from upgrade import load_operator_manifest, compute_drift_report  # noqa: E402
        staging, _ = self._emit()
        # the standalone corpus_authority.json sidecar is retired (folded into manifest)
        self.assertFalse((staging / ".wizard/corpus_authority.json").exists())
        m = load_operator_manifest(staging / ".wizard/manifest.json")  # loads through v2 consumer
        self.assertEqual(m["manifest_schema_version"], "manifest-v2")
        self.assertIn("corpus_authority", m)
        self.assertTrue(len(m["corpus_authority"]["cells"]) > 0)
        # the composed system's manifest is drift-clean through the real consumer
        self.assertFalse(compute_drift_report(staging, m).has_drift)

    def test_manifest_covers_foundation_docs_with_contract_policy(self):
        from upgrade import load_operator_manifest  # noqa: E402
        staging, _ = self._emit()
        m = load_operator_manifest(staging / ".wizard/manifest.json")
        mf = m["managed_files"]
        # foundation docs are enrolled in the full-tree manifest at root
        for doc in ["vision.md", "approach.md", "prd.md", "audit_framework.md"]:
            self.assertIn(doc, mf, f"foundation doc {doc} missing from managed_files")
        # vision = shared/expected/three_way; approach = shared/allowed/three_way;
        # prd = operator/operator_review; audit_framework = wizard/warn_on_drift
        self.assertEqual(mf["vision.md"]["merge_strategy"], "three_way")
        self.assertEqual(mf["vision.md"]["managed_by"], "shared")
        self.assertEqual(mf["vision.md"]["local_modifications"], "expected")
        self.assertEqual(mf["approach.md"]["local_modifications"], "allowed")
        self.assertEqual(mf["prd.md"]["merge_strategy"], "operator_review")
        self.assertEqual(mf["audit_framework.md"]["merge_strategy"], "warn_on_drift")

    def test_claude_md_carries_rendered_corpus_block(self):
        staging, _ = self._emit()
        claude = (staging / "CLAUDE.md").read_text()
        self.assertIn("Load-bearing at session start", claude)  # the rendered block, not the stub
        self.assertIn("OP-08", claude)

    def test_hooks_injected_across_targets(self):
        staging, _ = self._emit()
        self.assertIn("OP-30", (staging / "quality/validation_gate_config.md").read_text())
        self.assertIn("OP-06", (staging / "logs/audit_log.md").read_text())
        self.assertIn("OP-22", (staging / "agents/prompts/qa_agent_prompt.md").read_text())
        self.assertIn("OP-26", (staging / "project_instructions.md").read_text())  # cross_ref hook
        self.assertIn("OP-19", (staging / "pending_decisions.md").read_text())     # cross_ref hook

    def test_no_placeholder_survives_anywhere(self):
        from operator_fill_emitter import is_operator_fill_path
        staging, _ = self._emit()
        offenders = []
        for p in staging.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(staging)
            # operator-fill templates (review prompts / skill templates) are emitted verbatim
            # and intentionally retain {{}} placeholders for the operator to complete — exempt.
            if is_operator_fill_path(str(rel)):
                continue
            leftover = PLACEHOLDER_RE.findall(p.read_text(encoding="utf-8", errors="ignore"))
            if leftover:
                offenders.append((rel, leftover))
        self.assertEqual(offenders, [], f"unsubstituted placeholders survived: {offenders}")

    def test_emitted_tree_has_no_build_provenance(self):
        staging, _ = self._emit()
        offenders = []
        for p in staging.rglob("*"):
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for marker in FORBIDDEN_PROVENANCE:
                if marker in text:
                    offenders.append((p.relative_to(staging), marker))
        self.assertEqual(offenders, [], f"build provenance leaked into operator system: {offenders}")

    def test_emission_is_deterministic(self):
        a = Path(tempfile.mkdtemp())
        b = Path(tempfile.mkdtemp())
        self._emit(into=a)
        self._emit(into=b)
        files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
        files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
        self.assertEqual(files_a, files_b, "emitted file set differs between runs")
        for rel in files_a:
            self.assertEqual((a / rel).read_bytes(), (b / rel).read_bytes(),
                             f"non-deterministic content: {rel}")


class GenerateOperatorSystemTests(unittest.TestCase):
    """The guarded top-level orchestration entry: one validated EmissionPlan ->
    complete runnable system in a staging dir, behind fail-fast preconditions
    (foundation-only rejection / empty-staging / clean-worktree generator_version
    reconcile / template-dependency check)."""

    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _plan(self, **over):
        p = _valid_plan()
        p.update(over)
        return validate_emission_plan(p, self.contract)

    def test_happy_path_emits_full_tree_and_manifest(self):
        from operator_system_emitter import generate_operator_system  # noqa: E402
        from upgrade import compute_drift_report, load_operator_manifest  # noqa: E402
        plan = self._plan()
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name) / "out"  # absent -> created
        result = generate_operator_system(
            plan, staging, REPO_ROOT, generator_version_override="0" * 40,
        )
        self.assertTrue(result.manifest_path.exists())
        self.assertTrue((staging / "vision.md").exists())
        self.assertTrue((staging / "agents/prompts/orchestrator_prompt.md").exists())
        m = load_operator_manifest(result.manifest_path)
        self.assertFalse(compute_drift_report(staging, m).has_drift)

    def test_rejects_foundation_only_mode(self):
        from operator_system_emitter import generate_operator_system  # noqa: E402
        from generator import GeneratorError  # noqa: E402
        plan = self._plan(foundation_only_mode=True, agents=[])
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        with self.assertRaises(GeneratorError):
            generate_operator_system(plan, Path(tmp.name) / "o", REPO_ROOT,
                                     generator_version_override="0" * 40)

    def test_generator_version_mismatch_fails_closed(self):
        from operator_system_emitter import generate_operator_system  # noqa: E402
        from generator import GeneratorError  # noqa: E402
        plan = self._plan()  # plan.generator_version == "0"*40
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        with self.assertRaises(GeneratorError):
            generate_operator_system(plan, Path(tmp.name) / "o", REPO_ROOT,
                                     generator_version_override="f" * 40)

    def test_non_empty_staging_fails_closed(self):
        from operator_system_emitter import generate_operator_system  # noqa: E402
        from generator import GeneratorError  # noqa: E402
        plan = self._plan()
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name)  # exists + we put a file in it
        (staging / "leftover.txt").write_text("stale", encoding="utf-8")
        with self.assertRaises(GeneratorError):
            generate_operator_system(plan, staging, REPO_ROOT,
                                     generator_version_override="0" * 40)

    def test_missing_foundation_input_fails_fast_before_any_write(self):
        """Derivation-input fail-fast: a missing foundation placeholder is caught
        BEFORE emission — no partial staging tree."""
        from operator_system_emitter import generate_operator_system  # noqa: E402
        from generator import GeneratorError  # noqa: E402
        p = _valid_plan()
        del p["foundation_doc_inputs"]["VISION_PURPOSE"]  # drop a required placeholder
        plan = validate_emission_plan(p, self.contract)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name) / "out"
        with self.assertRaises(GeneratorError):
            generate_operator_system(plan, staging, REPO_ROOT, generator_version_override="0" * 40)
        # fail-fast: no partial tree written
        self.assertFalse((staging / "CLAUDE.md").exists(), "partial tree written before fail-fast")

    def test_empty_foundation_input_fails_fast(self):
        """A silently-EMPTY derived input (the silent-data-loss surface) fails closed."""
        from operator_system_emitter import generate_operator_system  # noqa: E402
        from generator import GeneratorError  # noqa: E402
        p = _valid_plan()
        p["foundation_doc_inputs"]["VISION_PURPOSE"] = "   "  # present but whitespace-only
        plan = validate_emission_plan(p, self.contract)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        with self.assertRaises(GeneratorError):
            generate_operator_system(plan, Path(tmp.name) / "o", REPO_ROOT,
                                     generator_version_override="0" * 40)

    def test_missing_template_dependency_fails_closed(self):
        from operator_system_emitter import _verify_template_dependencies  # noqa: E402
        from generator import GeneratorError  # noqa: E402
        plan = self._plan()
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        with self.assertRaises(GeneratorError):
            _verify_template_dependencies(plan, Path(tmp.name))  # empty fake repo -> no templates

    def test_empty_source_commit_fails_fast_prewrite(self):
        """source_commit guard moved PREWRITE (close-review F2): empty source_commit
        in the registry fails before any emission, not at manifest-build."""
        import json
        from operator_system_emitter import _verify_foundation_bundle_dependencies  # noqa: E402
        from generator import GeneratorError  # noqa: E402
        plan = self._plan()
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        reg = root / "wizard" / "registry"; reg.mkdir(parents=True)
        (reg / "foundation-bundles.json").write_text(json.dumps({
            "bundles": [{"foundation_bundle_version": plan.bundle_version, "path": "wizard/x", "source_commit": ""}]
        }), encoding="utf-8")
        with self.assertRaises(GeneratorError):
            _verify_foundation_bundle_dependencies(plan, root)

    def test_missing_foundation_template_fails_fast_prewrite(self):
        """foundation-template existence guard moved PREWRITE (close-review F1): a
        missing foundation template fails before any emission, not mid-render."""
        import json
        from operator_system_emitter import _verify_foundation_bundle_dependencies  # noqa: E402
        from generator import GeneratorError  # noqa: E402
        import shutil
        plan = self._plan()
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        reg = root / "wizard" / "registry"; reg.mkdir(parents=True)
        (reg / "foundation-bundles.json").write_text(json.dumps({
            "bundles": [{"foundation_bundle_version": plan.bundle_version,
                         "path": "wizard/bundle", "source_commit": "abc1234"}]
        }), encoding="utf-8")
        # provide the real hash-baseline contract so the failure isolates the
        # MISSING TEMPLATE (not a missing contract)
        contract_dst = root / "wizard" / "foundation-bundles" / "v0" / "contracts"
        contract_dst.mkdir(parents=True)
        shutil.copy(
            REPO_ROOT / "wizard" / "foundation-bundles" / "v0" / "contracts" / "foundation-manifest-hash-baseline-v1.json",
            contract_dst / "foundation-manifest-hash-baseline-v1.json",
        )
        (root / "wizard" / "bundle" / "templates").mkdir(parents=True)  # dir exists but EMPTY -> templates missing
        with self.assertRaises(GeneratorError):
            _verify_foundation_bundle_dependencies(plan, root)


class GenerateBundleCliFullSystemTests(unittest.TestCase):
    """The generate_bundle.py CLI --emission-plan mode routes to the guarded
    full-system orchestration. The full-system mode enforces clean-worktree
    provenance (no --permissive-dirty escape), so a fixture plan whose
    generator_version cannot match a real generator identity fails closed (exit 1)."""

    def test_cli_emission_plan_mode_enforces_provenance_guard(self):
        import json
        scripts_dir = REPO_ROOT / "wizard" / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import generate_bundle as cli  # noqa: E402
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        plan_file = Path(tmp.name) / "plan.json"
        plan_file.write_text(json.dumps(_valid_plan()), encoding="utf-8")
        staging = Path(tmp.name) / "out"
        argv = ["generate_bundle.py", "--emission-plan", str(plan_file),
                "--target", str(staging), "--build-repo-root", str(REPO_ROOT)]
        old = sys.argv
        sys.argv = argv
        try:
            rc = cli.main()
        finally:
            sys.argv = old
        self.assertEqual(rc, 1, "full-system CLI must fail closed on provenance mismatch")


if __name__ == "__main__":
    unittest.main()
