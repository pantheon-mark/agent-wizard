"""Tests for the inherited-corpus emitter (stdlib unittest; pip-install-free).

Renders the distributed corpus pack into operator-project artifacts in a temp
staging dir against the REAL pack + templates, and asserts:
  - rules_library single-home: all 20 corpus-body cells become Rule entries with
    the NEUTRAL Source label and no build provenance (no "AWB" / "seed principle P-n");
  - decisions/ ADR template authored (Nygard + operator-actions field) + _index.md;
  - target-hook injection into agent prompts / validation_gate_config / audit_log,
    idempotent (re-run -> byte-identical);
  - .wizard/corpus_authority.json carries authority stamps for ALL gated cells
    (across realization classes) and is NOT operator-file frontmatter;
  - placeholder exhaustion across emitted corpus artifacts.
"""

import json
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus_emitter import (  # noqa: E402
    emit_rules_library, emit_decisions, inject_target_hooks, render_claude_md_block,
    emit_corpus_authority, build_corpus_authority_doc,
)
from corpus_loader import load_corpus_pack, resolve_for_shape  # noqa: E402
from scaffold_emitter import emit_scaffold  # noqa: E402
from agent_emitter import emit_agent_layer  # noqa: E402
from emission_plan import load_contract, default_contract_path, validate_emission_plan  # noqa: E402
from generator import PLACEHOLDER_RE  # noqa: E402
from test_emission_plan import _valid_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


class CorpusEmitterRulesLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())
        cls.records = load_corpus_pack()
        cls.body_ids = [r.cell_id for r in cls.records if r.realization == "corpus-body"]

    def _emit(self):
        plan = validate_emission_plan(_valid_plan(), self.contract)
        self._tmp = tempfile.TemporaryDirectory()
        staging = Path(self._tmp.name)
        written = emit_rules_library(plan, staging, REPO_ROOT, records=self.records)
        return staging, written

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_corpus_has_twenty_body_cells(self):
        self.assertEqual(len(self.body_ids), 20)

    def test_rules_library_emitted(self):
        staging, _ = self._emit()
        self.assertTrue((staging / "quality/rules_library.md").exists())

    def test_all_body_cells_become_rules(self):
        staging, _ = self._emit()
        text = (staging / "quality/rules_library.md").read_text()
        for cid in self.body_ids:
            self.assertIn(cid, text, f"rules_library missing rule {cid}")

    def test_neutral_source_no_build_provenance(self):
        staging, _ = self._emit()
        text = (staging / "quality/rules_library.md").read_text()
        self.assertIn("inherited operating principle", text)
        self.assertNotIn("AWB", text)
        self.assertNotIn("seed principle P-", text)

    def test_rule_body_content_present(self):
        # A known fragment from OP-06 (change-management consult-before-modify body).
        staging, _ = self._emit()
        text = (staging / "quality/rules_library.md").read_text()
        self.assertIn("stricter, not looser", text)

    def test_rules_marked_active(self):
        staging, _ = self._emit()
        text = (staging / "quality/rules_library.md").read_text()
        self.assertIn("Active", text)

    def test_placeholder_exhaustion(self):
        staging, written = self._emit()
        for p in written:
            text = p.read_text(encoding="utf-8")
            leftover = PLACEHOLDER_RE.findall(text)
            self.assertEqual(leftover, [], f"unsubstituted placeholder(s) in {p.name}: {leftover}")


class CorpusEmitterDecisionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _emit(self):
        plan = validate_emission_plan(_valid_plan(), self.contract)
        self._tmp = tempfile.TemporaryDirectory()
        staging = Path(self._tmp.name)
        written = emit_decisions(plan, staging, REPO_ROOT)
        return staging, written

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_emits_decision_record_template_and_index(self):
        staging, _ = self._emit()
        self.assertTrue((staging / "decisions/decision_record_template.md").exists())
        self.assertTrue((staging / "decisions/_index.md").exists())

    def test_template_has_nygard_sections(self):
        staging, _ = self._emit()
        t = (staging / "decisions/decision_record_template.md").read_text()
        for section in ["Status", "Context", "Decision", "Consequences"]:
            self.assertIn(section, t, f"decision record template missing Nygard section: {section}")

    def test_template_has_operator_actions_field(self):
        # C-ref-3: load-bearing manual steps must have an explicit home in the record.
        staging, _ = self._emit()
        t = (staging / "decisions/decision_record_template.md").read_text()
        self.assertIn("Operator actions", t)

    def test_decisions_artifacts_are_operator_clean(self):
        staging, _ = self._emit()
        for rel in ["decisions/decision_record_template.md", "decisions/_index.md"]:
            text = (staging / rel).read_text()
            self.assertNotIn("AWB", text)
            self.assertEqual(PLACEHOLDER_RE.findall(text), [], f"unsubstituted placeholder in {rel}")


class CorpusEmitterClaudeBlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())
        cls.records = load_corpus_pack()

    def _block(self):
        plan = validate_emission_plan(_valid_plan(), self.contract)
        return render_claude_md_block(plan, self.records)

    def test_block_points_to_rules_library(self):
        block = self._block()
        self.assertIn("rules_library.md", block)

    def test_block_inlines_session_start_posture_trio(self):
        # claim-level epistemic (OP-08) + lists-are-examples (OP-24) + context-integrity (OP-25)
        block = self._block()
        for op in ["OP-08", "OP-24", "OP-25"]:
            self.assertIn(op, block, f"session-start posture short-list missing {op}")

    def test_block_is_operator_clean(self):
        block = self._block()
        self.assertNotIn("AWB", block)
        self.assertEqual(PLACEHOLDER_RE.findall(block), [])


class CorpusEmitterHookInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())
        cls.records = load_corpus_pack()

    def _staged(self):
        plan = validate_emission_plan(_valid_plan(), self.contract)
        self._tmp = tempfile.TemporaryDirectory()
        staging = Path(self._tmp.name)
        # Emit the files the hooks attach to (scaffold + agent layer) first.
        emit_scaffold(plan, staging, REPO_ROOT)
        emit_agent_layer(plan, staging, REPO_ROOT)
        return plan, staging

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_validation_gate_hooks_injected(self):
        plan, staging = self._staged()
        inject_target_hooks(plan, staging, records=self.records)
        text = (staging / "quality/validation_gate_config.md").read_text()
        for op in ["OP-30", "OP-32", "OP-35"]:
            self.assertIn(op, text, f"validation_gate_config missing hook {op}")

    def test_audit_log_hook_injected(self):
        plan, staging = self._staged()
        inject_target_hooks(plan, staging, records=self.records)
        self.assertIn("OP-06", (staging / "logs/audit_log.md").read_text())

    def test_agent_prompt_glob_and_specific_hooks(self):
        plan, staging = self._staged()
        inject_target_hooks(plan, staging, records=self.records)
        qa = (staging / "agents/prompts/qa_agent_prompt.md").read_text()
        self.assertIn("OP-22", qa)   # qa-specific agent_prompt_line hook
        self.assertIn("OP-34", qa)   # glob agents/*_prompt.md hook reaches qa too
        researcher = (staging / "agents/prompts/researcher_prompt.md").read_text()
        self.assertIn("OP-34", researcher)   # glob fan-out reaches specialists

    def test_claude_md_not_double_injected(self):
        # CLAUDE.md inherited principles are handled by the rendered block, not this
        # post-pass; the injection must not add a second managed region to CLAUDE.md.
        plan, staging = self._staged()
        inject_target_hooks(plan, staging, records=self.records)
        claude = (staging / "CLAUDE.md").read_text()
        self.assertNotIn("BEGIN inherited-operating-principles", claude)

    def test_injection_is_idempotent(self):
        plan, staging = self._staged()
        first = inject_target_hooks(plan, staging, records=self.records)
        before = {p: Path(p).read_text() for p in first}
        inject_target_hooks(plan, staging, records=self.records)
        for p, content in before.items():
            self.assertEqual(Path(p).read_text(), content, f"injection not idempotent for {p}")


class CorpusEmitterAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())
        cls.records = load_corpus_pack()
        resolved = resolve_for_shape(cls.records, "markdown-CC")
        cls.gated_ids = sorted(r.cell_id for r in resolved if r.authority_gate != "applies-all")

    def _emit(self):
        plan = validate_emission_plan(_valid_plan(), self.contract)
        self._tmp = tempfile.TemporaryDirectory()
        staging = Path(self._tmp.name)
        written = emit_corpus_authority(plan, staging, records=self.records)
        return staging, written

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_authority_sidecar_emitted_as_versioned_subdoc(self):
        staging, _ = self._emit()
        path = staging / ".wizard/corpus_authority.json"
        self.assertTrue(path.exists())
        doc = json.loads(path.read_text())
        self.assertIn("version", doc)
        self.assertIn("_absorption_note", doc)         # folds into the upgrade-scaffold manifest
        self.assertIn("authority_profile", doc)

    def test_all_gated_cells_stamped_across_realization_classes(self):
        staging, _ = self._emit()
        doc = json.loads((staging / ".wizard/corpus_authority.json").read_text())
        stamped = sorted(c["cell_id"] for c in doc["cells"])
        self.assertEqual(stamped, self.gated_ids)
        # spot-check one of each realization class is present
        for cid in ("OP-06", "OP-01", "OP-13"):
            self.assertIn(cid, stamped, f"gated {cid} missing from authority sidecar")

    def test_applies_all_cells_absent(self):
        staging, _ = self._emit()
        doc = json.loads((staging / ".wizard/corpus_authority.json").read_text())
        stamped = {c["cell_id"] for c in doc["cells"]}
        self.assertNotIn("OP-02", stamped)  # applies-all -> not authority-gated

    def test_each_gated_cell_has_profile_derived_basis_and_concrete_source(self):
        staging, _ = self._emit()
        doc = json.loads((staging / ".wizard/corpus_authority.json").read_text())
        for c in doc["cells"]:
            self.assertEqual(c["authority_basis"], "operator-profile-derived", c["cell_id"])
            self.assertIn(c["authority_source"],
                          ("delegated", "wizard-default", "hard-control", "operator-configured"),
                          c["cell_id"])
            # the IDQ re-emit obligation is discharged: no pending expiry trigger.
            self.assertEqual(c["expires_on_trigger"], "none", c["cell_id"])

    def test_build_corpus_authority_doc_returns_embeddable_dict(self):
        # The dict-returning fold-in source: same gated cells + authority_profile as the
        # sidecar, but WITHOUT the standalone-sidecar-only fields (schema / _absorption_note)
        # — once embedded in the manifest the absorption note is stale (the manifest fold-in).
        plan = validate_emission_plan(_valid_plan(), self.contract)
        doc = build_corpus_authority_doc(plan, self.records)
        self.assertIn("version", doc)
        self.assertIn("authority_profile", doc)
        self.assertEqual(sorted(c["cell_id"] for c in doc["cells"]), self.gated_ids)
        self.assertNotIn("_absorption_note", doc)
        self.assertNotIn("schema", doc)

    def test_stamps_not_in_operator_file_frontmatter(self):
        # Authority provenance lives in the sidecar, never in the operator rule files.
        plan = validate_emission_plan(_valid_plan(), self.contract)
        self._tmp = tempfile.TemporaryDirectory()
        staging = Path(self._tmp.name)
        emit_rules_library(plan, staging, REPO_ROOT, records=self.records)
        emit_corpus_authority(plan, staging, records=self.records)
        rules = (staging / "quality/rules_library.md").read_text()
        self.assertNotIn("authority_basis", rules)
        self.assertNotIn("provisional_default", rules)

    def test_deterministic(self):
        staging, _ = self._emit()
        first = (staging / ".wizard/corpus_authority.json").read_text()
        emit_corpus_authority(
            validate_emission_plan(_valid_plan(), self.contract), staging, records=self.records)
        self.assertEqual((staging / ".wizard/corpus_authority.json").read_text(), first)


if __name__ == "__main__":
    unittest.main()
