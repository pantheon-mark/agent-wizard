"""Tests for the deterministic AgentRecordAssembler (stdlib unittest).

Covers: AgentIntent -> agent-record-dict (code owns id/dirs/tiers/cron, not Claude);
the claim-vs-policy fail-fast — forbidden (R9) and allowed-but-unmapped (R8-class) —
and the duplicate / critical-insufficiency lints. Validates against the REAL
distributed scaffold plan (markdown-CC.json).
"""

import re
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scaffold_plan import load_scaffold_plan  # noqa: E402
from build_intent import AgentIntent, ResourceClaims, ConstraintViolation  # noqa: E402
from agent_record_assembler import assemble_agent_records  # noqa: E402

SP = load_scaffold_plan("markdown-CC")
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROMPT_TEMPLATE = _REPO_ROOT / "wizard" / "agents" / "agent_prompt_template.md"


def mandated_writes(prompt_text):
    """The backtick-quoted write targets a prompt MANDATES (a write/log verb followed,
    on the same line, by a backtick path). Parsed from the prompt text itself — NOT a
    hardcoded dir list — so the invariant is rule-based and holds for any agent. Leading
    slashes are normalized away; runtime placeholders ({{AGENT_NAME}}, [task_id]) are kept
    (they sit inside a permitted directory, so directory coverage still holds)."""
    out = set()
    for m in re.finditer(r"\b(?:write|log)\b[^`\n]*`([^`]+)`", prompt_text, re.I):
        p = m.group(1).strip()
        if "/" in p:  # a path, not a bare token/filename mention
            out.add(p.lstrip("/"))
    return out


def write_target_covered(target, permitted):
    """A mandated write target is covered if it equals a permitted file or sits within a
    permitted directory (both normalized: leading/trailing slashes stripped)."""
    t = target.lstrip("/").rstrip("/")
    for p in permitted:
        pp = p.lstrip("/").rstrip("/")
        if t == pp or t.startswith(pp + "/"):
            return True
    return False


def _ai(**kw):
    base = dict(
        display_name="Researcher", function_summary="Gathers source material.",
        role_intent="Produce verified research briefs.", acceptance_signals=["brief has citations"],
        output_purpose="research brief", criticality_tier="standard",
        resource_claims=ResourceClaims(), confidence="high",
        insufficiency_flags=[], source_spans=["ARCH-2#1"],
    )
    base.update(kw)
    return AgentIntent(**base)


class AgentRecordAssemblerTests(unittest.TestCase):
    def test_happy_path_maps_intent_to_record(self):
        recs = assemble_agent_records([_ai()], SP)
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["id"], "researcher")                       # code-owned: slugified
        self.assertEqual(r["role_description"], "Produce verified research briefs.")
        self.assertEqual(r["criticality_tier"], "standard")
        self.assertEqual(r["primary_model_tier"], "standard")         # code-owned: criticality policy
        self.assertEqual(r["status_model_tier"], "fast")
        self.assertEqual(r["output_directory"], "work/agent_outputs")
        self.assertEqual(r["permitted_write_directories"], [
            "work/agent_outputs", "agents/checkpoints", "agents/handoffs",
            "logs/error_log.md", "logs/session_log.md", "logs/audit_log.md",
            "work/issues_log.md",
        ])  # output dir + the control-plane operational paths the prompt mandates
        self.assertEqual(r["additional_context_files"], ["approach.md"])
        self.assertEqual(r["output_format_specification"], "markdown")
        self.assertTrue(r["step_completion_criteria"])
        self.assertTrue(r["task_completion_criteria"])
        self.assertNotIn("requires_external_network", r)              # claims never leak into the record
        self.assertNotIn("cron_cadence", r)                          # not claimed

    def test_cron_only_when_claimed_and_allowed(self):
        recs = assemble_agent_records([_ai(resource_claims=ResourceClaims(requires_cron=True))], SP)
        self.assertIn("cron_cadence", recs[0])
        self.assertTrue(recs[0]["cron_cadence"])

    def test_forbidden_claim_rejected_fail_fast(self):               # R9
        with self.assertRaises(ConstraintViolation) as ctx:
            assemble_agent_records([_ai(resource_claims=ResourceClaims(requires_external_network=True))], SP)
        self.assertEqual(ctx.exception.kind, "resource_claim_forbidden")

    def test_allowed_but_unmapped_claim_rejected(self):              # R8-class
        # a shape that ALLOWS a claim with no deterministic effect must reject, not silently drop
        sp2 = replace(SP, allowed_resource_claims=["requires_cron", "requires_broad_fs_read"])
        with self.assertRaises(ConstraintViolation) as ctx:
            assemble_agent_records([_ai(resource_claims=ResourceClaims(requires_broad_fs_read=True))], sp2)
        self.assertEqual(ctx.exception.kind, "resource_claim_unmapped")

    def test_duplicate_agent_id_rejected(self):
        with self.assertRaises(ConstraintViolation) as ctx:
            assemble_agent_records([_ai(), _ai(function_summary="dup")], SP)
        self.assertEqual(ctx.exception.kind, "duplicate_agent_id")

    def test_reserved_control_plane_name_rejected(self):
        """RESERVED-NAME GUARD: a specialist whose id collides with a control-plane agent
        (the emitter always writes an Orchestrator at orchestrator_prompt.md and a QA agent)
        must fail loud — otherwise the specialist's emitted prompt OVERWRITES the control-plane
        orchestrator prompt (slug 'orchestrator') or duplicates the built-in QA roster row.
        Checked on the SLUG (not the raw string) so case/format variants are all caught."""
        for name in ["Orchestrator", "orchestrator", "ORCHESTRATOR", "QA", "qa"]:
            with self.assertRaises(ConstraintViolation) as ctx:
                assemble_agent_records([_ai(display_name=name)], SP)
            self.assertEqual(ctx.exception.kind, "reserved_agent_id",
                             f"{name!r} should be rejected as a reserved control-plane id")

    def test_non_reserved_lookalike_names_allowed(self):
        """ANTI-OVERFIT: names that merely RESEMBLE a control-plane role but do NOT slug to a
        reserved id must still be allowed — the guard keys on the exact slug, never a substring.
        Includes 'Coordinator' (a legitimate operator-chosen specialist name that merely sounds
        control-plane-ish — not a collision), 'QA Reviewer' -> 'qa-reviewer', 'Orchestration Helper'."""
        for name in ["Coordinator", "QA Reviewer", "Orchestration Helper", "Data QA"]:
            recs = assemble_agent_records([_ai(display_name=name)], SP)
            self.assertEqual(len(recs), 1, f"{name!r} should be allowed (not a reserved slug)")

    def test_critical_agent_with_insufficiency_rejected(self):
        with self.assertRaises(ConstraintViolation) as ctx:
            assemble_agent_records([_ai(criticality_tier="critical", insufficiency_flags=["missing_output_format"])], SP)
        self.assertEqual(ctx.exception.kind, "critical_agent_insufficient")

    def test_records_sorted_by_id(self):
        recs = assemble_agent_records([_ai(display_name="Zeta"), _ai(display_name="Alpha")], SP)
        self.assertEqual([r["id"] for r in recs], ["alpha", "zeta"])

    def test_permitted_writes_cover_every_prompt_mandated_write(self):
        """PERMISSION-BOUNDARY GUARD (anti-overfit, derivation-level): every write the agent
        PROMPT TEMPLATE mandates (checkpoints / handoffs / logs / issues_log) must be inside
        the permitted-write set the assembler produces — otherwise the agent's own blast-radius
        hard gate halts it on its first checkpoint write. The mandated set is parsed from the
        template (the rule), and the check runs across DIVERGENT agents so it can't pass by
        matching one roster's dirs."""
        mandated = mandated_writes(_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
        self.assertTrue(mandated, "expected the prompt template to mandate operational writes")
        for ai in [_ai(display_name="Researcher", criticality_tier="standard"),
                   _ai(display_name="Notifier", criticality_tier="supporting"),
                   _ai(display_name="Master List Keeper", criticality_tier="critical")]:
            rec = assemble_agent_records([ai], SP)[0]
            permitted = rec["permitted_write_directories"]
            uncovered = sorted(m for m in mandated if not write_target_covered(m, permitted))
            self.assertEqual(
                uncovered, [],
                f"agent {rec['id']!r}: prompt mandates writes outside its permitted set: "
                f"{uncovered}; permitted={permitted}")


if __name__ == "__main__":
    unittest.main()
