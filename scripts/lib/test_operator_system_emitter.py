"""Integration tests for the operator-system orchestrator (stdlib unittest).

emit_operator_system composes the scaffold + agent layer + corpus into one
complete runnable operator system in a staging dir. These tests assert the full
tree is present, the corpus block landed in CLAUDE.md (not the standalone stub),
hooks were injected, NO {{KEY}} survives anywhere, the emitted tree carries no
build provenance, and the whole emission is deterministic (emit twice ->
byte-identical).
"""

import shutil
import subprocess
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

    def test_project_purpose_filled_from_core_purpose(self):
        # Identity fix: CLAUDE.md + session_bootstrap Purpose must be FILLED from the
        # vision's CORE_PURPOSE, not left as the operator-fill placeholder. The placeholder
        # made a fresh operator session report its own identity as unconfigured.
        raw = _valid_plan()
        raw["foundation_doc_inputs"]["CORE_PURPOSE"] = "SENTINEL keep the estate on track."
        plan = validate_emission_plan(raw, self.contract)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name)
        emit_operator_system(plan, staging, REPO_ROOT)
        claude = (staging / "CLAUDE.md").read_text()
        boot = (staging / "session_bootstrap.md").read_text()
        self.assertIn("SENTINEL keep the estate on track.", claude,
                      "CLAUDE.md Purpose not filled from CORE_PURPOSE")
        self.assertIn("SENTINEL keep the estate on track.", boot,
                      "session_bootstrap Purpose not filled from CORE_PURPOSE")
        self.assertNotIn("describe what this system is for", claude,
                         "CLAUDE.md still carries the unfilled purpose placeholder")

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
        import json
        plan = self._plan()
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        # Provide a system-artifacts.json so the bundle is recognized as having an
        # operating layer, but leave all template files absent -> should raise.
        bundle_dir = root / "wizard" / "foundation-bundles" / plan.bundle_version
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "system-artifacts.json").write_text(
            json.dumps({"artifacts": []}), encoding="utf-8")
        with self.assertRaises(GeneratorError):
            _verify_template_dependencies(plan, root)  # bundle present but templates absent

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


# ============================================================================
# Unused-input warning — accurate ("consumed by NO emitter"), full-system-only.
# ============================================================================

import contextlib  # noqa: E402
import io  # noqa: E402

# A few of the ~19 keys that were FALSELY flagged before the fix — each IS consumed
# by some emitter (scaffold template substitution, capability/dependency projection,
# or a direct read), so none must appear in any unused-input warning.
_KNOWN_CONSUMED_KEYS = [
    "PROJECT_NAME", "CORE_PURPOSE", "BUILD_PROGRESS_ROWS", "CAPABILITY_INCREMENTS",
    "ADVISOR_ENTRIES", "CREDENTIAL_REGISTRY_ROWS", "INPUT_TYPE_INVENTORY",
    "SOURCE_REGISTRY_ROWS", "EXTERNAL_DEPENDENCY_IDENTITY", "EXTERNAL_DEPENDENCY_ANNOTATION",
]

_UNUSED_WARNING_FRAGMENT = "not referenced by any template"


def _emit_capturing_stderr(emit_callable):
    """Run an emit callable, returning its captured stderr text."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        emit_callable()
    return buf.getvalue()


class RenderFoundationDocsDoesNotWarn(unittest.TestCase):
    """The unused-input warning is no longer render_foundation_docs' job — it must
    NOT fire there (it would fire spuriously on the upgrade-apply / foundation-only
    paths that reuse the renderer)."""

    def test_render_foundation_docs_emits_no_unused_warning(self):
        from generator import render_foundation_docs  # noqa: E402
        from test_emission_plan import _FOUNDATION_DOC_INPUTS  # noqa: E402
        # Add a key the foundation templates do NOT reference (but the full system would
        # consume). render_foundation_docs must stay SILENT regardless.
        inputs = dict(_FOUNDATION_DOC_INPUTS)
        inputs["CAPABILITY_INCREMENTS"] = "[]"
        inputs["TOTALLY_UNUSED_TYPO_KEY"] = "x"
        err = _emit_capturing_stderr(
            lambda: render_foundation_docs("v0.4.0", inputs, REPO_ROOT)
        )
        self.assertNotIn(_UNUSED_WARNING_FRAGMENT, err,
                         "render_foundation_docs must not emit the unused-input warning")


class FullSystemUnusedInputWarning(unittest.TestCase):
    """The warning fires ONLY at full-system emit, means 'consumed by NO emitter',
    and still flags a genuinely-unconsumed key."""

    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _emit(self, plan, capture=True):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name) / "out"
        run = lambda: emit_operator_system(plan, staging, REPO_ROOT)
        if capture:
            return _emit_capturing_stderr(run)
        run()
        return ""

    def test_planted_unconsumed_key_still_warns(self):
        """An injected key no emitter consumes MUST still warn (proves the warning
        was made accurate, not deleted)."""
        p = _valid_plan()
        p["foundation_doc_inputs"]["TOTALLY_UNUSED_TYPO_KEY"] = "stale-value"
        plan = validate_emission_plan(p, self.contract)
        err = self._emit(plan)
        self.assertIn(_UNUSED_WARNING_FRAGMENT, err)
        self.assertIn("TOTALLY_UNUSED_TYPO_KEY", err)

    def test_consumed_keys_never_warn_synthetic(self):
        """Keys consumed via scaffold/projection/direct-read are NOT flagged even when
        present alongside a genuinely-unused one."""
        p = _valid_plan()
        # Inject a representative consumed set + one genuine typo.
        p["foundation_doc_inputs"]["CORE_PURPOSE"] = "Keep the demo on track."
        p["foundation_doc_inputs"]["CAPABILITY_INCREMENTS"] = "[]"
        p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = "[]"
        p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_ANNOTATION"] = "[]"
        p["foundation_doc_inputs"]["TOTALLY_UNUSED_TYPO_KEY"] = "stale"
        plan = validate_emission_plan(p, self.contract)
        err = self._emit(plan)
        for k in ("CORE_PURPOSE", "CAPABILITY_INCREMENTS", "EXTERNAL_DEPENDENCY_IDENTITY",
                  "EXTERNAL_DEPENDENCY_ANNOTATION", "PROJECT_NAME"):
            self.assertNotIn(k, err, f"consumed key {k} was falsely flagged as unused")
        # but the genuine typo is still surfaced
        self.assertIn("TOTALLY_UNUSED_TYPO_KEY", err)


# Real-transcript end-to-end: emit the whole real operator system on the preserved
# pilot transcript (v0.4.0) via the emit path + generator_version_override seam, and
# assert NO known-consumed key appears in any unused-input warning. This is the RED
# test pre-fix: the warning fired from render_foundation_docs over the foundation-doc
# templates only, falsely flagging the consumed keys below.
_TRANSCRIPT = Path.home() / "wizard-pilot-2026-06-01" / "wizard_transcript.jsonl"
_GEN_OVERRIDE = "c3b5609fbbe566d73f3097ff0d1cd087dfe19245"


def _e2e_prereqs() -> bool:
    if not _TRANSCRIPT.exists():
        return False
    reg = REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"
    if not reg.exists():
        return False
    import json
    versions = {b.get("foundation_bundle_version")
                for b in json.loads(reg.read_text()).get("bundles", [])}
    return "v0.4.0" in versions


@unittest.skipUnless(_e2e_prereqs(),
                     f"requires the preserved pilot transcript at {_TRANSCRIPT} and the v0.4.0 bundle")
class RealTranscriptUnusedInputWarning(unittest.TestCase):
    """Full real emission must not falsely flag any consumed fdi key."""

    def test_no_known_consumed_key_warns_on_real_emit(self):
        scripts_dir = REPO_ROOT / "wizard" / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import interview_cli as cli  # noqa: E402
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        proj = Path(tmp.name) / "estate"
        err = _emit_capturing_stderr(lambda: cli.cmd_emit_system(
            str(_TRANSCRIPT), "markdown-CC", str(proj), str(REPO_ROOT),
            bundle_version="v0.4.0", generator_version_override=_GEN_OVERRIDE,
        ))
        # Sanity: a real system was emitted.
        self.assertTrue((proj / "vision.md").exists())
        # The crux: none of the legitimately-consumed keys may appear in any warning.
        warning_lines = [ln for ln in err.splitlines() if _UNUSED_WARNING_FRAGMENT in ln]
        for ln in warning_lines:
            for k in _KNOWN_CONSUMED_KEYS:
                self.assertNotIn(k, ln,
                    f"consumed key {k} falsely flagged as unused in: {ln!r}")
        # On this real transcript every fdi key IS consumed, so ideally no warning at all.
        self.assertEqual(warning_lines, [],
                         f"unexpected unused-input warning(s) on real emit: {warning_lines}")


class ExternalWriteLibEmitDecisionTests(unittest.TestCase):
    """Task 7 (D): the emitter includes the external_write lib files in its emit-set when
    (and only when) the plan has a writes-back (boundary_output) dependency.

    Tested at the DECISION/FILE-SELECTION level. The full emit-from-registered-bundle
    assertion is deferred to post-Task-8 (the bundle carrying these lib files is cut in
    Task 8); see ExternalWriteLibDeferredEmitTests below.
    """

    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    _LIB_FILES = (
        "agents/lib/external_write/operations.py",
        "agents/lib/external_write/adapters.py",
        "agents/lib/external_write/broker.py",
        "agents/lib/external_write/scan.py",
    )

    def _plan_with_deps(self, deps_json):
        import copy
        from test_emission_plan import _valid_plan
        p = copy.deepcopy(_valid_plan())
        p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = deps_json
        return validate_emission_plan(p, self.contract)

    def test_writes_back_plan_emits_lib(self):
        import json
        from agent_emitter import external_write_lib_emit_set
        deps = json.dumps([{"id": "t", "name": "company_tracker", "type": "Sheet",
                            "roles": ["boundary_output"], "owner_agent_id": "researcher"}])
        plan = self._plan_with_deps(deps)
        emit_set = set(external_write_lib_emit_set(plan))
        for f in self._LIB_FILES:
            self.assertIn(f, emit_set, f"writes-back plan must emit {f}")

    def test_non_writes_back_plan_emits_no_lib(self):
        import json
        from agent_emitter import external_write_lib_emit_set
        deps = json.dumps([{"id": "f", "name": "rss_feed", "type": "RSS",
                            "roles": ["boundary_input"]}])
        plan = self._plan_with_deps(deps)
        self.assertEqual(external_write_lib_emit_set(plan), [],
                         "a read-only plan must emit NONE of the external_write lib (no dead code)")

    def test_no_dependencies_emits_no_lib(self):
        from agent_emitter import external_write_lib_emit_set
        from test_emission_plan import _valid_plan
        plan = validate_emission_plan(_valid_plan(), self.contract)
        self.assertEqual(external_write_lib_emit_set(plan), [],
                         "a plan with no dependency record must emit NONE of the external_write lib")

    def test_foundation_only_emits_no_lib(self):
        import copy, json
        from agent_emitter import external_write_lib_emit_set
        from test_emission_plan import _valid_plan
        p = copy.deepcopy(_valid_plan())
        p["foundation_only_mode"] = True
        p["agents"] = []
        p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = json.dumps(
            [{"id": "t", "name": "company_tracker", "type": "Sheet", "roles": ["boundary_output"]}])
        plan = validate_emission_plan(p, self.contract)
        self.assertEqual(external_write_lib_emit_set(plan), [],
                         "foundation-only systems have no agent layer -> no external_write lib")


class ExternalWriteLibRegistryEnrollmentTests(unittest.TestCase):
    """CRITICAL regression (Task 7 code-review finding): `registered_adapters.py`
    must be enrolled in `_EXTERNAL_WRITE_LIB_FILES`, or a freshly-emitted
    writes-back system ships `operator_acceptance.py` (which hard-imports
    `external_write.registered_adapters` at module scope) WITHOUT the module it
    imports -- a raw ModuleNotFoundError at import time in a real operator
    project, before the operator's first add-capability ever creates the file.

    No bundle has cut the current external_write/ yet (the physical bundle copy
    lands at the v0.13.0 bundle cut -- this task is enrollment-only and must not
    touch foundation-bundles/). So this test builds an isolated FIXTURE
    build-repo-root: a full copy of the real, already-cut v0.10.2 bundle (has the
    operating-layer contract, predates the F-35 requirements.txt template so it
    stays clear of that unrelated/pre-existing lifecycle-classifier gap), with
    its `agents/lib/external_write/` template subdir overlaid by the CURRENT
    dev-tree `wizard/agents/lib/external_write/` (which already carries both
    `operator_acceptance.py`'s hard top-level import and `registered_adapters.py`)
    -- reproducing exactly what the v0.13.0 bundle cut will ship for this
    subdir -- and drives the REAL production emit surface (`emit_operator_system`,
    which calls `agent_emitter._emit_external_write_lib`) against it.

    Deliberately NOT the dev-tree `shutil.copytree` the existing e2e acceptance
    test (`test_external_write_operator_acceptance.py`) uses to build its temp
    project -- that copies the whole directory regardless of the manifest, so it
    can never catch a manifest-enrollment gap. This test exercises the same
    file-by-file, manifest-gated copy loop (`_EXTERNAL_WRITE_LIB_FILES`)
    production emission actually uses -- the production emit surface the review
    finding says the e2e test missed.
    """

    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _fixture_build_repo_root(self) -> Path:
        """A synthetic build_repo_root that mirrors the real toolkit layout (so
        every OTHER bundle/registry/contract lookup the full emit pipeline makes
        resolves exactly as it would against REPO_ROOT), except that the v0.10.2
        bundle's `agents/lib/external_write/` template subdir is overlaid by the
        CURRENT dev-tree `wizard/agents/lib/external_write/` -- simulating the
        not-yet-cut v0.13.0 bundle state without touching foundation-bundles/."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fixture_root = Path(tmp.name)
        # Mirror the real BUILD-REPO layout (fixture_root/wizard/...) -- some
        # resolvers (e.g. upgrade_scaffold_emitter._resolve_source_commit) hardcode
        # `build_repo_root / "wizard" / "registry"` rather than going through the
        # layout-agnostic wizard_subroot() helper, so the fixture must match that
        # layout exactly. Whole registry + foundation-bundles trees (cheap: ~14MB),
        # so every version-independent contract/registry lookup the full emit
        # pipeline makes (foundation-doc rendering, corpus, scaffold, etc.) resolves
        # exactly as it would against REPO_ROOT -- only the v0.10.2 bundle's
        # external_write subdir is overlaid below.
        shutil.copytree(
            REPO_ROOT / "wizard" / "registry", fixture_root / "wizard" / "registry")
        shutil.copytree(
            REPO_ROOT / "wizard" / "foundation-bundles",
            fixture_root / "wizard" / "foundation-bundles")

        fixture_bundle_dir = fixture_root / "wizard" / "foundation-bundles" / "v0.10.2"
        ew_template_dir = fixture_bundle_dir / "templates" / "agents" / "lib" / "external_write"
        shutil.rmtree(ew_template_dir)
        dev_tree_ew = REPO_ROOT / "wizard" / "agents" / "lib" / "external_write"
        shutil.copytree(dev_tree_ew, ew_template_dir)

        # Package marker one level up (agents/lib/__init__.py) -- mirrors the real
        # dev-tree layout _emit_external_write_lib reads via
        # `pkg_init_src = src_dir.parent / "__init__.py"`.
        dev_lib_init = REPO_ROOT / "wizard" / "agents" / "lib" / "__init__.py"
        if dev_lib_init.is_file():
            shutil.copy(
                dev_lib_init,
                fixture_bundle_dir / "templates" / "agents" / "lib" / "__init__.py")
        return fixture_root

    def _plan(self):
        import copy
        import json
        from test_emission_plan import _valid_plan
        p = copy.deepcopy(_valid_plan())
        p["bundle_version"] = "v0.10.2"
        p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = json.dumps(
            [{"id": "t", "name": "company_tracker", "type": "Sheet",
              "roles": ["boundary_output"], "owner_agent_id": "researcher"}])
        return validate_emission_plan(p, self.contract)

    def test_emitted_external_write_package_imports_cleanly(self):
        plan = self._plan()
        fixture_build_repo_root = self._fixture_build_repo_root()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name)

        emit_operator_system(plan, staging, fixture_build_repo_root)

        registered_adapters_path = (
            staging / "agents" / "lib" / "external_write" / "registered_adapters.py")
        self.assertTrue(
            registered_adapters_path.is_file(),
            "registered_adapters.py must be enrolled in _EXTERNAL_WRITE_LIB_FILES "
            "and physically emitted -- operator_acceptance.py hard-imports it at "
            "module scope")

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'agents/lib'); "
             "import external_write.operator_acceptance"],
            cwd=str(staging), capture_output=True, text=True)
        self.assertEqual(
            result.returncode, 0,
            "emitted external_write.operator_acceptance must import cleanly in a "
            f"fresh operator project (before the operator's first add-capability "
            f"ever runs); stderr:\n{result.stderr}")

    def test_emitted_triage_module_is_physically_present_and_imports_cleanly(self):
        # Task 8 (A3 / F-48, v0.13.0 Slice 2): triage.py must be enrolled in
        # _EXTERNAL_WRITE_LIB_FILES AND physically emitted, or a freshly-emitted
        # writes-back system's operator-facing triage skill has no module to
        # import at all. Nothing else in the lib imports it at module scope (it
        # is a standalone read-only primitive), so this proves both the
        # enrollment and that the module imports cleanly standalone in a fresh
        # operator project.
        plan = self._plan()
        fixture_build_repo_root = self._fixture_build_repo_root()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name)

        emit_operator_system(plan, staging, fixture_build_repo_root)

        triage_path = staging / "agents" / "lib" / "external_write" / "triage.py"
        self.assertTrue(
            triage_path.is_file(),
            "triage.py must be enrolled in _EXTERNAL_WRITE_LIB_FILES and "
            "physically emitted -- the operator-facing triage skill has no "
            "module to import without it")

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'agents/lib'); "
             "import external_write.triage"],
            cwd=str(staging), capture_output=True, text=True)
        self.assertEqual(
            result.returncode, 0,
            "emitted external_write.triage must import cleanly in a fresh "
            f"operator project; stderr:\n{result.stderr}")

    def test_emitted_standing_automation_module_is_physically_present_and_imports_cleanly(self):
        # Task 9 (B2 / F-42, v0.13.0 Slice 2): standing_automation.py must be enrolled in
        # _EXTERNAL_WRITE_LIB_FILES AND physically emitted, or a freshly-emitted
        # writes-back system's standing-automation runners have no safe primitive to
        # import at all -- the F-42 fail-open defect this primitive closes would have
        # nothing to route through. Nothing else in the lib imports it at module scope
        # (it is a standalone dispatcher a standing-automation runner calls directly),
        # so this proves both the enrollment and that the module imports cleanly
        # standalone in a fresh operator project.
        plan = self._plan()
        fixture_build_repo_root = self._fixture_build_repo_root()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name)

        emit_operator_system(plan, staging, fixture_build_repo_root)

        standing_automation_path = (
            staging / "agents" / "lib" / "external_write" / "standing_automation.py")
        self.assertTrue(
            standing_automation_path.is_file(),
            "standing_automation.py must be enrolled in _EXTERNAL_WRITE_LIB_FILES and "
            "physically emitted -- a standing-automation runner has no safe primitive "
            "to import without it")

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'agents/lib'); "
             "import external_write.standing_automation"],
            cwd=str(staging), capture_output=True, text=True)
        self.assertEqual(
            result.returncode, 0,
            "emitted external_write.standing_automation must import cleanly in a fresh "
            f"operator project; stderr:\n{result.stderr}")


class ExternalWriteLibEmitFromBundleTests(unittest.TestCase):
    """Task 7 (D): end-to-end assertion that a writes-back plan built from the bundle
    that ships the external_write lib (v0.8.0) actually writes
    agents/lib/external_write/*.py into the emitted tree.

    Emission copies these source files from the REGISTERED frozen bundle; v0.8.0 is the
    bundle that ships the lib. A full emit of a writes-back plan from v0.8.0 must land
    all four lib files (plus the package __init__ markers) so the emitted system can
    import and run the checked write substrate. A read-only plan (no boundary_output
    dependency) from the SAME bundle must land NONE of the lib (no dead code) — proving
    the emit is gated on the writes-back signal, not merely on the bundle carrying the
    source. The emit DECISION logic is also covered by ExternalWriteLibEmitDecisionTests;
    this is the from-bundle physical-emit proof.
    """

    _BUNDLE = "v0.8.0"
    _LIB_FILES = (
        "agents/lib/external_write/operations.py",
        "agents/lib/external_write/adapters.py",
        "agents/lib/external_write/broker.py",
        "agents/lib/external_write/scan.py",
    )

    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _plan(self, deps_json):
        import copy
        from test_emission_plan import _valid_plan
        p = copy.deepcopy(_valid_plan())
        p["bundle_version"] = self._BUNDLE
        p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = deps_json
        return validate_emission_plan(p, self.contract)

    def test_writes_back_plan_emits_lib_files(self):
        import json
        deps = json.dumps([{"id": "t", "name": "company_tracker", "type": "Sheet",
                            "roles": ["boundary_output"], "owner_agent_id": "researcher"}])
        plan = self._plan(deps)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name)
        emit_operator_system(plan, staging, REPO_ROOT)
        for rel in self._LIB_FILES:
            self.assertTrue((staging / rel).is_file(),
                            f"writes-back plan from {self._BUNDLE} must physically emit {rel}")
        # Package markers so the lib imports cleanly from the emitted tree.
        self.assertTrue((staging / "agents/lib/__init__.py").is_file(),
                        "agents/lib/__init__.py package marker must be emitted")
        self.assertTrue((staging / "agents/lib/external_write/__init__.py").is_file(),
                        "agents/lib/external_write/__init__.py package marker must be emitted")

    def test_read_only_plan_emits_no_lib_files(self):
        import json
        deps = json.dumps([{"id": "f", "name": "rss_feed", "type": "RSS",
                            "roles": ["boundary_input"]}])
        plan = self._plan(deps)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name)
        emit_operator_system(plan, staging, REPO_ROOT)
        for rel in self._LIB_FILES:
            self.assertFalse((staging / rel).exists(),
                             f"read-only plan must emit NONE of the lib (no dead code); {rel} present")


if __name__ == "__main__":
    unittest.main()
