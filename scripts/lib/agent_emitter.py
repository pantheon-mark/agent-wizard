"""Agent-layer emitter — emits the /agents/ execution tree from a validated EmissionPlan.

Reuses generator._substitute_placeholders (strict {{KEY}}, fail-fast). Stdlib-only,
pip-install-free. Emits to a STAGING directory (never a live operator root), so the
output is hash/diff-testable and a later upgrade step can diff staging against reality.

Realizes the ADR-derived Control-Plane / Data-Plane execution model: one Orchestrator
(control plane) + N specialist agents (data plane) + one QA agent. Per-shape adaptation
is by template selection, not by logic here (markdown-CC shape at v1).

Tier discipline (the model-tier split): agent/orchestrator PROMPTS receive tier NAMES
(`high`/`standard`/`fast`) — they never carry literal model strings; the tier->model
mapping lives in project_instructions.md (emitted by the scaffold layer). Specialist
INVOCATION SCRIPTS receive the RESOLVED model string (programmatic --model selection;
the operator never picks a model).
"""

from pathlib import Path
from typing import Dict, List, Optional

from emission_plan import EmissionPlan  # type: ignore
from generator import _substitute_placeholders  # type: ignore
from bundle_templates import (  # type: ignore
    operating_layer_source_version, _bundle_dir, bundle_has_operating_layer,
)


# Template locations (build-repo-relative) — retained for the operator_system_emitter
# prewrite dependency check. EMISSION sources these from the frozen bundle templates/
# tree (single home), via the _bundle_agent_template paths below.
ORCHESTRATOR_TEMPLATE = "wizard/agents/orchestrator_prompt.md"
SPECIALIST_TEMPLATE = "wizard/agents/agent_prompt_template.md"
QA_TEMPLATE = "wizard/agents/qa_agent_prompt.md"
INVOCATION_TEMPLATE = "wizard/scripts/agent_invocation_template.sh"
CRON_TEMPLATE = "wizard/templates/agents/cron_config.md"

# Bundle-relative subpaths (inside <bundle>/templates/) for the agent-layer templates.
_BUNDLE_ORCHESTRATOR_REL = "agents/orchestrator_prompt.md"
_BUNDLE_SPECIALIST_REL = "agents/agent_prompt_template.md"
_BUNDLE_QA_REL = "agents/qa_agent_prompt.md"
_BUNDLE_INVOCATION_REL = "scripts/agent_invocation_template.sh"
_BUNDLE_CRON_REL = "agents/cron_config.md"

SCRIPT_MODE = 0o755


def _bundle_agent_templates_root(build_repo_root: Path, version: Optional[str] = None) -> Path:
    """The frozen bundle templates/ tree that homes the agent-layer templates.

    `version` pins the bundle to use; if omitted the legacy
    operating_layer_source_version() discovery is used."""
    if version is None:
        version = operating_layer_source_version(str(build_repo_root))
    return _bundle_dir(version, build_repo_root) / "templates"


def _emit_from_template(template_path: Path, out_path: Path, inputs: Dict[str, str],
                        name: str) -> Path:
    """Substitute placeholders in a template and write the result. Fail-fast on
    any unsubstituted {{KEY}} (delegates to generator._substitute_placeholders)."""
    content = template_path.read_text(encoding="utf-8")
    result, _seen = _substitute_placeholders(content, inputs, template_name=name)
    out_path.write_text(result, encoding="utf-8")
    return out_path


def _md_bullets(items: List[str], empty_text: str) -> str:
    """Render a list as continuation bullets for a markdown template line that
    already begins with '- ' / '  - '. Empty -> a single honest 'none' line."""
    if not items:
        return empty_text
    return "\n- ".join(items)


def _md_bullets_indented(items: List[str], empty_text: str) -> str:
    if not items:
        return empty_text
    return "\n  - ".join(items)


def _bash_context_array(items: List[str]) -> str:
    """Render additional-context files as bash array entries (one per line),
    each resolved under $PROJECT_ROOT. Empty -> empty (the array stays empty)."""
    return "\n  ".join(f'"$PROJECT_ROOT/{f}"' for f in items)


# Human-readable schedule labels — mirror the cron_config.md "Schedule reference" table.
_CRON_HUMAN = {
    "0 6 * * *": "Every day at 6 AM",
    "0 0 * * *": "Every day at midnight",
    "0 * * * *": "Every hour",
    "0 9 * * 1-5": "Every weekday at 9 AM",
    "0 20 * * 0": "Every Sunday at 8 PM",
}

# Empty-state note. The leading newline reproduces the blank line the static template
# carried between the table separator and the note, so the no-cron case stays
# byte-equivalent to the prior verbatim copy (preserves the retirement differential).
_CRON_EMPTY_NOTE = "\n*No entries yet. Cron entries are added during the wizard closing sequence.*"


def _orchestrator_invocation(plan: EmissionPlan, agent_id: str, cadence: str) -> str:
    """The default scheduled-run command (the control plane): invoke the Orchestrator
    headlessly at the resolved high tier, carrying the schedule TRIGGER (which agent, what
    cadence) so the Orchestrator knows which scheduled work is due — NOT a specialist
    invocation script. The Orchestrator reads the work queue and routes to the specialist;
    directly scheduling a specialist is the declared advanced exception, not the default."""
    model = plan.model_tiers[plan.orchestrator["model_tier_high"]]
    return (f'claude --model {model} --print "Act as the Orchestrator (agents/prompts/'
            f'orchestrator_prompt.md). Scheduled trigger: agent={agent_id} cadence={cadence}. '
            f'Read the work queue + agents/cron/cron_config.md and run or enqueue the due '
            f'scheduled work for that agent through normal routing."')


def _render_cron_entries(plan: EmissionPlan) -> str:
    """Render the cron_config.md table body from agents carrying a cron_cadence.

    Each scheduled agent (the requires_cron path: the assembler stamps
    orchestrator.schedule onto cron_cadence) becomes one row whose invocation targets
    the Orchestrator by default. With no scheduled agent, the honest empty-state note
    is preserved."""
    rows: List[str] = []
    for a in plan.agents:
        if not a.cron_cadence:
            continue
        first_line = (a.role_description.replace("|", "\\|").splitlines() or [""])
        what = first_line[0] if first_line else ""
        human = _CRON_HUMAN.get(a.cron_cadence, "Custom schedule")
        invocation = _orchestrator_invocation(plan, a.id, a.cron_cadence)  # per-agent trigger
        rows.append(f"| {a.id} | {what} | {human} | `{a.cron_cadence}` | {invocation} | — | — |")
    return "\n".join(rows) if rows else _CRON_EMPTY_NOTE


def emit_agent_layer(plan: EmissionPlan, staging_dir: Path, build_repo_root: Path) -> List[Path]:
    """Emit the /agents/ tree for `plan` into `staging_dir`. Returns paths written.

    Skips the agent IMPLEMENTATION layer entirely when foundation_only_mode is set
    (only the foundation-doc set is produced in that mode; this matches the loader's
    I7 invariant which forbids agents in foundation-only mode).

    Also skips when the emitted bundle_version carries no operating-layer templates (no
    system-artifacts.json — e.g. v0.4.0 or v0.5.0), producing a foundation-only system
    where agent files are absent."""
    written: List[Path] = []
    if plan.foundation_only_mode:
        return written  # no implementation layer in foundation-only mode
    if not bundle_has_operating_layer(plan.bundle_version, build_repo_root):
        return written  # foundation-only bundle: agent files absent

    agents_dir = staging_dir / "agents"
    prompts_dir = agents_dir / "prompts"
    scripts_dir = agents_dir / "scripts"
    cron_dir = agents_dir / "cron"
    for d in (prompts_dir, scripts_dir, cron_dir):
        d.mkdir(parents=True, exist_ok=True)

    bt = _bundle_agent_templates_root(build_repo_root, plan.bundle_version)

    # --- Orchestrator (control plane) — tier NAMES in the prompt ---
    orch = plan.orchestrator
    written.append(_emit_from_template(
        bt / _BUNDLE_ORCHESTRATOR_REL,
        prompts_dir / "orchestrator_prompt.md",
        {
            "PROJECT_NAME": plan.project_name,
            "MODEL_TIER_HIGH": orch["model_tier_high"],
            "MODEL_TIER_STANDARD": orch["model_tier_standard"],
            "MODEL_TIER_FAST": orch["model_tier_fast"],
        },
        "orchestrator_prompt.md",
    ))

    # --- QA agent (every system gets exactly one) — tier NAMES ---
    written.append(_emit_from_template(
        bt / _BUNDLE_QA_REL,
        prompts_dir / "qa_agent_prompt.md",
        {
            "PROJECT_NAME": plan.project_name,
            "MODEL_TIER_HIGH": "high",
            "MODEL_TIER_STANDARD": "standard",
            "MODEL_TIER_FAST": "fast",
        },
        "qa_agent_prompt.md",
    ))

    # --- Specialist agents (data plane) ---
    for a in plan.agents:
        # Prompt: tier NAMES (a.primary_model_tier / a.status_model_tier)
        written.append(_emit_from_template(
            bt / _BUNDLE_SPECIALIST_REL,
            prompts_dir / f"{a.id}_prompt.md",
            {
                "PROJECT_NAME": plan.project_name,
                "AGENT_NAME": a.id,
                "AGENT_ROLE_DESCRIPTION": a.role_description,
                "CRITICALITY_TIER": a.criticality_tier,
                "ADDITIONAL_CONTEXT_FILES": _md_bullets(
                    a.additional_context_files, "(none beyond the foundational documents)"),
                "PERMITTED_WRITE_DIRECTORIES": _md_bullets_indented(
                    a.permitted_write_directories, "(none)"),
                "STEP_COMPLETION_CRITERIA": a.step_completion_criteria,
                "TASK_COMPLETION_CRITERIA": a.task_completion_criteria,
                "OUTPUT_FORMAT_SPECIFICATION": a.output_format_specification,
                "MODEL_TIER": a.primary_model_tier,
                "MODEL_TIER_FAST": a.status_model_tier,
            },
            f"{a.id}_prompt.md",
        ))
        # Invocation script: RESOLVED model string (programmatic --model)
        script_path = _emit_from_template(
            bt / _BUNDLE_INVOCATION_REL,
            scripts_dir / f"{a.id}.sh",
            {
                "AGENT_NAME": a.id,
                "AGENT_MODEL": plan.model_tiers[a.primary_model_tier],
                "OUTPUT_DIRECTORY": a.output_directory,
                "ADDITIONAL_CONTEXT_FILES": _bash_context_array(a.additional_context_files),
            },
            f"{a.id}.sh",
        )
        script_path.chmod(SCRIPT_MODE)
        written.append(script_path)

    # --- Cron config — scheduled agents become Orchestrator-invoked entries (control-plane default) ---
    cron_out = cron_dir / "cron_config.md"
    written.append(_emit_from_template(
        bt / _BUNDLE_CRON_REL,
        cron_out,
        {"CRON_ENTRIES": _render_cron_entries(plan)},
        "cron_config.md",
    ))

    # --- Roster (generated; the Orchestrator health check reads this) ---
    roster_out = agents_dir / "roster.md"
    roster_out.write_text(_render_roster(plan), encoding="utf-8")
    written.append(roster_out)

    return written


def _render_roster(plan: EmissionPlan) -> str:
    """Generate agents/roster.md — the agent registry the Orchestrator verifies at startup."""
    lines = [
        f"# {plan.project_name} — Agent Roster",
        "",
        "*Wizard-generated. The Orchestrator verifies every listed prompt file exists at startup.*",
        "",
        "| Agent | Role | Criticality | Prompt file |",
        "|-------|------|-------------|-------------|",
        "| Orchestrator | Control plane — work-queue + routing | critical | agents/prompts/orchestrator_prompt.md |",
        "| QA | Observe / challenge / verify (never modifies production) | critical | agents/prompts/qa_agent_prompt.md |",
    ]
    for a in plan.agents:
        role = a.role_description.replace("|", "\\|").splitlines()[0] if a.role_description else ""
        lines.append(f"| {a.id} | {role} | {a.criticality_tier} | agents/prompts/{a.id}_prompt.md |")
    return "\n".join(lines) + "\n"
