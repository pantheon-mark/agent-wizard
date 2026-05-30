"""Tests for the interview->generator projection gate + dispatcher (stdlib unittest).

The 5 acceptance tests (the fail-closed gate is real — no direct staging->output path):
  (i)   an invalid derived record cannot project (fails at validation);
  (ii)  a deferred field never reaches foundation_doc_inputs;
  (iii) there is NO parameter to inject raw foundation_doc_inputs (structural);
  (iv)  the receipt records the derived-record + transcript hashes;
  (v)   routing: full path -> full sink; foundation-only -> foundation sink.
Plus a real-sink end-to-end test through the whole gate (not only spies).
"""

import inspect
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_emission_plan import _FOUNDATION_DOC_INPUTS  # noqa: E402
from build_intent import AgentIntent, ResourceClaims  # noqa: E402
from derived_record import DerivedRecordError  # noqa: E402
import interview_bridge as ib  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def _events(inputs=None, foundation_only=False):
    """An ordered transcript that compile_transcript() -> a contract-valid record."""
    inp = dict(_FOUNDATION_DOC_INPUTS) if inputs is None else dict(inputs)
    if foundation_only:
        inp["FOUNDATION_ONLY_MODE"] = "true"
    evs, seq = [], 0
    for k, v in inp.items():
        evs.append({"event_seq": seq, "field": k, "event_type": "derivation", "value": v,
                    "envelope": {"_source": "operator-content", "_derivation_class": "extraction",
                                 "_decision_field": False, "_decision_kind": "none"}})
        seq += 1
        evs.append({"event_seq": seq, "field": k, "event_type": "confirmation",
                    "confirmation_state": "accepted", "confirmed_at": "2026-05-30"})
        seq += 1
    return evs


def _ai():
    return AgentIntent(display_name="Researcher", function_summary="Gathers source material.",
                       role_intent="Gathers source material.", acceptance_signals=["non-empty summary"],
                       output_purpose="summary", criticality_tier="standard", resource_claims=ResourceClaims(),
                       confidence="high", insufficiency_flags=[], source_spans=["ARCH-2#1"])


class GateAcceptanceTests(unittest.TestCase):
    def setUp(self):
        # Spy the two sinks so routing is asserted without a real emit.
        self.calls = {"full": 0, "foundation": 0}
        self._full, self._found = ib._dispatch_full_system, ib._dispatch_foundation_only
        ib._dispatch_full_system = lambda plan, **kw: (self.calls.__setitem__("full", self.calls["full"] + 1), "FULL")[1]
        ib._dispatch_foundation_only = lambda plan, **kw: (self.calls.__setitem__("foundation", self.calls["foundation"] + 1), "FOUND")[1]

    def tearDown(self):
        ib._dispatch_full_system, ib._dispatch_foundation_only = self._full, self._found

    def test_i_invalid_derived_record_cannot_project(self):
        bad = _events()
        # break DR-3: a claude-derived value with no confirmation event
        bad.append({"event_seq": 9999, "field": "BROKEN", "event_type": "derivation", "value": "x",
                    "envelope": {"_source": "claude-derived-operator-confirmed", "_derivation_class": "extraction",
                                 "_decision_field": False, "_decision_kind": "none"}})
        with self.assertRaises(DerivedRecordError):
            ib.build_operator_system_from_transcript(bad, [_ai()], system_shape="markdown-CC",
                                                     generator_version_override="0" * 40)

    def test_ii_deferred_field_never_reaches_foundation_doc_inputs(self):
        evs = _events()
        evs.append({"event_seq": 8000, "field": "DEFER_ME", "event_type": "derivation", "value": "x",
                    "envelope": {"_source": "operator-content", "_derivation_class": "extraction",
                                 "_decision_field": False, "_decision_kind": "none"}})
        evs.append({"event_seq": 8001, "field": "DEFER_ME", "event_type": "confirmation",
                    "confirmation_state": "deferred_not_emittable"})
        res = ib.build_operator_system_from_transcript(evs, [_ai()], system_shape="markdown-CC",
                                                       generator_version_override="0" * 40)
        self.assertNotIn("DEFER_ME", res.plan.foundation_doc_inputs)

    def test_iii_no_raw_inputs_injection_path(self):
        sig = inspect.signature(ib.build_operator_system_from_transcript)
        self.assertNotIn("foundation_doc_inputs", sig.parameters)

    def test_iv_receipt_records_record_and_transcript_hashes(self):
        res = ib.build_operator_system_from_transcript(_events(), [_ai()], system_shape="markdown-CC",
                                                       generator_version_override="0" * 40)
        self.assertTrue(res.derived_record_hash.startswith("sha256:"))
        self.assertTrue(res.transcript_hash.startswith("sha256:"))

    def test_v_full_path_routes_to_full_sink(self):
        ib.build_operator_system_from_transcript(_events(), [_ai()], system_shape="markdown-CC",
                                                 generator_version_override="0" * 40)
        self.assertEqual(self.calls, {"full": 1, "foundation": 0})

    def test_v_foundation_only_routes_to_foundation_sink(self):
        ib.build_operator_system_from_transcript(_events(foundation_only=True), [], system_shape="markdown-CC",
                                                 generator_version_override="0" * 40)
        self.assertEqual(self.calls, {"full": 0, "foundation": 1})

    def test_model_tiers_resolve_to_real_models_by_default(self):
        # The gate resolves the maintained tier->model registry (real Claude ids), NOT the
        # scaffold-plan's shape-correct placeholders, so the emitted --model is real.
        res = ib.build_operator_system_from_transcript(_events(), [_ai()], system_shape="markdown-CC",
                                                       generator_version_override="0" * 40)
        for tier in ("high", "standard", "fast"):
            v = res.plan.model_tiers[tier]
            self.assertFalse(v.startswith("model-"), f"{tier} is a placeholder {v!r}")
            self.assertTrue(v.startswith("claude-"), f"{tier}={v!r} is not a Claude model id")

    def test_model_tiers_override_wins(self):
        # The override seam (tests / special cases) still takes precedence over the registry.
        custom = {"high": "claude-x-hi", "standard": "claude-x-std", "fast": "claude-x-fast"}
        res = ib.build_operator_system_from_transcript(_events(), [_ai()], system_shape="markdown-CC",
                                                       generator_version_override="0" * 40,
                                                       model_tiers_override=custom)
        self.assertEqual(res.plan.model_tiers, custom)


class GateRealSinkTest(unittest.TestCase):
    def test_full_gate_emits_a_runnable_tree(self):
        # No spies: exercise the WHOLE gate through the real generate_operator_system sink
        # (generator_version_override skips the clean-worktree computation; preconditions still run).
        with tempfile.TemporaryDirectory() as td:
            res = ib.build_operator_system_from_transcript(
                _events(), [_ai()], system_shape="markdown-CC",
                target_dir=Path(td), build_repo_root=REPO_ROOT, generator_version_override="0" * 40,
            )
            self.assertFalse(res.plan.foundation_only_mode)
            tree = {str(p.relative_to(td)) for p in Path(td).rglob("*") if p.is_file()}
            self.assertTrue(any(t.endswith("CLAUDE.md") for t in tree))
            self.assertIn("agents/prompts/researcher_prompt.md", tree)
            self.assertIn("agents/scripts/researcher.sh", tree)
            self.assertIn(".wizard/manifest.json", tree)


if __name__ == "__main__":
    unittest.main()
