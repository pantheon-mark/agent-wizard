"""Parity scaffold for the unified interview->generator path (stdlib unittest).

R7 parity bar: NOT byte-identity to System-A output, but a valid, complete,
equivalent-or-better operator system — structural + manifest coverage, the
special-behavior CARRIER fields present, no unresolved placeholders, the
foundation-only boundary preserved, and no build provenance in the emitted tree.

Scope (Phase 2a): the scaffold + the assertions on the assembled plan and the
emitted tree. The full live-System-A baseline comparison + the special-behavior
DERIVATION outputs (WI-011/WI-013/voice/name producing values) complete in
Phase 2b/3 once close-assembly is retired.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_emission_plan import _FOUNDATION_DOC_INPUTS  # noqa: E402
from build_intent import BuildIntent, AgentIntent, ResourceClaims  # noqa: E402
from scaffold_plan import load_scaffold_plan  # noqa: E402
from corpus_loader import load_corpus_pack  # noqa: E402
from emission_plan import validate_emission_plan, load_contract, default_contract_path  # noqa: E402
from emission_plan_assembler import assemble_emission_plan  # noqa: E402
from operator_system_emitter import generate_operator_system  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
EP_CONTRACT = load_contract(default_contract_path())


def _rec(foundation_only=False):
    inp = dict(_FOUNDATION_DOC_INPUTS)
    if foundation_only:
        inp["FOUNDATION_ONLY_MODE"] = "true"
    audit = {k: {"_source": "operator-content", "_derivation_class": "extraction", "_decision_field": False,
                 "_decision_kind": "none", "_confirmation_state": "accepted", "_confirmed_at": "2026-05-30"}
             for k in inp}
    r = dict(inp)
    r["_audit"] = audit
    return r


def _agent():
    return AgentIntent(display_name="Researcher", function_summary="Gathers source material.",
                       role_intent="Gathers source material.", acceptance_signals=["non-empty summary"],
                       output_purpose="summary", criticality_tier="standard", resource_claims=ResourceClaims(),
                       confidence="high", insufficiency_flags=[], source_spans=["ARCH-2#1"])


def _plan(foundation_only=False):
    sp = load_scaffold_plan("markdown-CC")
    bi = BuildIntent(derived_record=_rec(foundation_only),
                     agent_intents=([] if foundation_only else [_agent()]))
    d = assemble_emission_plan(bi, sp, load_corpus_pack(), model_tiers=sp.model_tiers)
    return validate_emission_plan(d, EP_CONTRACT)


class ParityScaffoldTests(unittest.TestCase):
    def test_manifest_coverage_no_uncovered_paths(self):          # R7: manifest coverage + I9
        plan = _plan()
        covered = {f.path for f in plan.emitted_files} | set(plan.control_plane_runtime_created)
        for ar in plan.agents:
            self.assertIn(ar.output_directory, covered)
        for cp_path in (plan.control_plane.queue_path, plan.control_plane.session_log_path,
                        plan.control_plane.cron_config_path):
            self.assertIn(cp_path, covered)

    def test_special_behavior_carrier_fields_present(self):       # R7: WI-011/HITL/autonomy carriers
        fdi = _plan().foundation_doc_inputs
        for key in ("VISION_CONSTRAINTS", "HITL_MAP_ROWS", "AUTONOMY_LEVEL"):
            self.assertIn(key, fdi)
            self.assertTrue(str(fdi[key]).strip())

    def test_no_unresolved_placeholders_in_inputs(self):          # R7: no {{KEY}} survives
        for v in _plan().foundation_doc_inputs.values():
            self.assertNotIn("{{", str(v))

    def test_foundation_only_boundary(self):                      # R7: foundation-only preserved
        plan = _plan(foundation_only=True)
        self.assertTrue(plan.foundation_only_mode)
        self.assertEqual(plan.agents, [])

    def test_end_to_end_emit_parity(self):                        # R7: complete tree + paths + no leak
        plan = _plan()
        with tempfile.TemporaryDirectory() as td:
            generate_operator_system(plan, Path(td), REPO_ROOT, generator_version_override=plan.generator_version)
            files = [p for p in Path(td).rglob("*") if p.is_file()]
            tree = {str(p.relative_to(td)) for p in files}
            # actual emitted artifact set (mirrors test_operator_system_emitter expectations)
            for rel in ("CLAUDE.md", "agents/prompts/researcher_prompt.md", "agents/scripts/researcher.sh",
                        "vision.md", "approach.md", "technical_architecture.md", "prd.md",
                        ".wizard/manifest.json", "quality/rules_library.md"):
                self.assertIn(rel, tree, f"missing emitted artifact: {rel}")
            # No unresolved placeholders anywhere in the emitted tree — EXCEPT the operator-fill
            # templates (review prompts / skill templates), which are emitted verbatim and
            # intentionally retain {{}} placeholders for the operator to complete during build.
            from operator_fill_emitter import is_operator_fill_path
            for p in files:
                if p.suffix in (".md", ".sh", ".json", ".log", ".yaml"):
                    if is_operator_fill_path(str(p.relative_to(td))):
                        continue
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    self.assertNotIn("{{", text, f"unresolved placeholder in {p.name}")
            # (Build-provenance-leak scanning of the emitted tree is covered by the emitter
            #  integration tests + the public-boundary scanner; it is intentionally NOT duplicated
            #  here, because the forbidden-reference token literals must not appear in this
            #  publicly-distributed file — the scanner correctly flags them if they do.)


if __name__ == "__main__":
    unittest.main()
