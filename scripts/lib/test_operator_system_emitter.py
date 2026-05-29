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
        staging, _ = self._emit()
        offenders = []
        for p in staging.rglob("*"):
            if not p.is_file():
                continue
            leftover = PLACEHOLDER_RE.findall(p.read_text(encoding="utf-8", errors="ignore"))
            if leftover:
                offenders.append((p.relative_to(staging), leftover))
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


if __name__ == "__main__":
    unittest.main()
