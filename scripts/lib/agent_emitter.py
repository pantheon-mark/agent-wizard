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

# The external-write substrate (single home: wizard/agents/lib/external_write/). These files
# are emitted into a system ONLY when its plan has a writes-back (boundary_output) dependency —
# a system that writes back to nothing carries none of this lib (no dead code for non-writing
# systems). Bundle-relative subpaths (inside <bundle>/templates/agents/lib/external_write/);
# the ship target is agents/lib/external_write/ in the emitted tree.
_EXTERNAL_WRITE_LIB_FILES = (
    "operations.py",
    "adapters.py",
    "broker.py",
    "scan.py",
    "verification_modes.py",
    "contracts.py",
    "verifiers.py",
    "boundary.py",
    "proof_hash.py",
    "copy_run_proof.py",
    "coverage_gate.py",
    "write_gate.py",
    # B2-T9a: the operator-originated-enhancement flow runtime + build-time machinery. Without
    # these three the flow's substrate ships but the flow itself is dead — a built capability
    # can never be accepted (ceremony), a new capability can never be registered (registration),
    # and the operator can never act on an acceptance (operator_acceptance).
    "acceptance_ceremony.py",
    "capability_registration.py",
    "operator_acceptance.py",
)
_EXTERNAL_WRITE_LIB_REL = "agents/lib/external_write"
_BUNDLE_EXTERNAL_WRITE_LIB_REL = "agents/lib/external_write"

# B2-T9a — the initial machine-readable descriptor set the build-time coverage gate reads. Its
# emitted-tree relpath, and the bundle-relative subpath of the JSON template (a full-body
# {{CAPABILITY_DESCRIPTORS_JSON}} placeholder) that fills it. Emitted ONLY for a writes-back plan
# and source-gated on the bundle carrying the template (canonical-only at T9a; the bundle copy +
# system-artifacts.json entry + parity are T9b) — inert until then, mirroring the lib emit.
_CAPABILITY_DESCRIPTOR_SET_REL = "security/capability_descriptors.json"
_BUNDLE_CAPABILITY_DESCRIPTOR_TEMPLATE_REL = "security/capability_descriptors.json"


def _plan_has_writes_back(plan: "EmissionPlan") -> bool:
    """True iff the plan's external-dependency identity record contains at least one
    dependency that plays the boundary_output (writes-back) role.

    Single source: reads the same EXTERNAL_DEPENDENCY_IDENTITY field the permission
    derivation reads (the canonical identity record produced by interview step 09).
    A foundation-only plan never writes back (no agent layer)."""
    if plan.foundation_only_mode:
        return False
    import json
    from dependency_projection import IDENTITY_FIELD, ROLE_BOUNDARY_OUTPUT  # type: ignore
    raw = plan.foundation_doc_inputs.get(IDENTITY_FIELD)
    if not raw or not str(raw).strip():
        return False
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, list):
        return False
    for dep in data:
        if isinstance(dep, dict) and ROLE_BOUNDARY_OUTPUT in (dep.get("roles") or []):
            return True
    return False


def external_write_lib_emit_set(plan: "EmissionPlan") -> List[str]:
    """The emitted-tree relpaths of the external_write lib files this plan should emit.

    Returns all fifteen lib files under agents/lib/external_write/ when the plan has a
    writes-back dependency: the original four substrate files (operations, adapters,
    broker, scan), the six contract-and-verification modules (verification_modes,
    contracts, verifiers, boundary, proof_hash, copy_run_proof), the two B1-4/B1-5
    safety-gate modules (coverage_gate — build-time descriptor-coverage gate; write_gate —
    runtime pre-write gate) enrolled at B2-T2, and the three B2 operator-originated-enhancement
    flow modules (acceptance_ceremony, capability_registration, operator_acceptance) enrolled at
    B2-T9a (canonical enrollment only; the physical bundle copy + system-artifacts.json + parity
    entries land at B2-T9b — the copy below is already source-gated on the bundle carrying the
    file, so this enrollment is a no-op until then).

    Returns [] when the plan has no writes-back (boundary_output) dependency — no dead
    code for read-only systems, and none for foundation-only plans (which have no agent
    layer at all).

    This is the DECISION + file-selection function the agent-layer emitter consults; the
    actual file copy depends on the source bundle carrying the lib."""
    if not _plan_has_writes_back(plan):
        return []
    return [f"{_EXTERNAL_WRITE_LIB_REL}/{f}" for f in _EXTERNAL_WRITE_LIB_FILES]


def _emit_external_write_lib(plan: "EmissionPlan", staging_dir: Path,
                             build_repo_root: Path) -> List[Path]:
    """Copy the external_write lib files into the staging tree when the plan writes back.

    Sources from the frozen bundle templates tree (single home; same bundle the agent
    templates come from). A bundle that does not yet carry the lib files (the lib ships in
    a later bundle cut) yields no copy — the emit-set decision still reports them via
    external_write_lib_emit_set; the physical emit is gated on the source existing."""
    targets = external_write_lib_emit_set(plan)
    if not targets:
        return []
    bt = _bundle_agent_templates_root(build_repo_root, plan.bundle_version)
    src_dir = bt / _BUNDLE_EXTERNAL_WRITE_LIB_REL
    written: List[Path] = []
    out_dir = staging_dir / _EXTERNAL_WRITE_LIB_REL
    init_src = src_dir / "__init__.py"
    pkg_init_src = src_dir.parent / "__init__.py"
    # Only emit when the source bundle actually carries the lib (deferred until the bundle
    # cut ships it). The decision is reported regardless; the copy is source-gated.
    if not src_dir.is_dir():
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    # Package markers so the lib imports cleanly from the emitted tree.
    if pkg_init_src.is_file():
        dst = staging_dir / "agents" / "lib" / "__init__.py"
        dst.write_text(pkg_init_src.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(dst)
    if init_src.is_file():
        dst = out_dir / "__init__.py"
        dst.write_text(init_src.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(dst)
    for fname in _EXTERNAL_WRITE_LIB_FILES:
        src = src_dir / fname
        if not src.is_file():
            continue
        dst = out_dir / fname
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(dst)
    return written


def _emit_capability_descriptor_set(plan: "EmissionPlan", staging_dir: Path,
                                    build_repo_root: Path) -> List[Path]:
    """Emit security/capability_descriptors.json — the INITIAL machine-readable descriptor set
    the build-time coverage gate reads back — for a writes-back plan (B2-T9a).

    Gated IDENTICALLY to the external_write lib (via _plan_has_writes_back): a read-only or
    foundation-only system carries no descriptor set — no dead artifact, and its coverage gate
    never runs. Source-gated on the emitted bundle carrying the JSON template (canonical-only at
    T9a; the bundle copy + system-artifacts.json entry + parity land at T9b), so this is inert
    until then — the same source-gating as _emit_external_write_lib.

    The emitted content is the COMPLETE initial set: base_declared_descriptors() (ALWAYS present,
    so a fresh writes-back build passes the coverage gate and is not dead-on-arrival) + the
    operator's declared-capability descriptors, every entry accepted:false. Filled into the
    template's full-body {{CAPABILITY_DESCRIPTORS_JSON}} placeholder via the same strict,
    fail-fast substitution every other template uses (JSON single-braces are not {{KEY}}
    placeholders, so the JSON body passes through cleanly). The value is a producer projection
    over the canonical EXTERNAL_DEPENDENCY_IDENTITY record: a value already projected into
    foundation_doc_inputs under EMIT_FIELD wins (forward-compat with a persisted-field wiring at
    T9b), else it is computed here — so the set is GUARANTEED present for every writes-back build
    regardless of interview-carrier state (the reachability property T9a delivers)."""
    if not _plan_has_writes_back(plan):
        return []
    import capability_descriptor_registry as cdr  # type: ignore  # sibling under lib/
    from dependency_projection import IDENTITY_FIELD  # type: ignore
    bt = _bundle_agent_templates_root(build_repo_root, plan.bundle_version)
    template_path = bt / _BUNDLE_CAPABILITY_DESCRIPTOR_TEMPLATE_REL
    if not template_path.is_file():
        # Source-gated: the bundle does not carry the template yet (T9b's copy). Inert until then.
        return []
    fdi = plan.foundation_doc_inputs or {}
    value = fdi.get(cdr.EMIT_FIELD)
    if value is None or not str(value).strip():
        identity_json = fdi.get(IDENTITY_FIELD) or "[]"
        value = cdr.render_initial_descriptor_set_json(str(identity_json))
    out_path = staging_dir / _CAPABILITY_DESCRIPTOR_SET_REL
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return [_emit_from_template(template_path, out_path, {cdr.EMIT_FIELD: str(value)},
                                "capability_descriptors.json")]


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


def _orchestrator_resolved_inputs(plan: EmissionPlan) -> Dict[str, str]:
    """The EXACT substitution map emit_agent_layer feeds the orchestrator prompt."""
    orch = plan.orchestrator
    return {
        "PROJECT_NAME": plan.project_name,
        "MODEL_TIER_HIGH": orch["model_tier_high"],
        "MODEL_TIER_STANDARD": orch["model_tier_standard"],
        "MODEL_TIER_FAST": orch["model_tier_fast"],
    }


def _qa_resolved_inputs(plan: EmissionPlan) -> Dict[str, str]:
    """The EXACT substitution map emit_agent_layer feeds the QA prompt."""
    return {
        "PROJECT_NAME": plan.project_name,
        "MODEL_TIER_HIGH": "high",
        "MODEL_TIER_STANDARD": "standard",
        "MODEL_TIER_FAST": "fast",
    }


_OPERATOR_OUTPUT_POINTER_TEXT = (
    "For any operator-facing deliverable, follow the deliverable location, naming, and "
    "voice/channel rules in `project_instructions.md` and `docs/voice_and_style.md`."
)


def _operator_output_pointer(a) -> str:
    """Return the operator-output routing pointer for a specialist agent.

    operator-facing agents get the full pointer text; internal agents get an
    empty string so the placeholder resolves without adding any content.
    Mirrors how PERMITTED_WRITE_DIRECTORIES is set per-agent from the record."""
    return _OPERATOR_OUTPUT_POINTER_TEXT if getattr(a, "operator_facing", False) else ""


def _agent_prompt_resolved_inputs(plan: EmissionPlan, a) -> Dict[str, str]:
    """The EXACT substitution map emit_agent_layer feeds a specialist prompt."""
    return {
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
        "OPERATOR_OUTPUT_POINTER": _operator_output_pointer(a),
        "MODEL_TIER": a.primary_model_tier,
        "MODEL_TIER_FAST": a.status_model_tier,
    }


def _agent_script_resolved_inputs(plan: EmissionPlan, a) -> Dict[str, str]:
    """The EXACT substitution map emit_agent_layer feeds a specialist invocation script."""
    return {
        "AGENT_NAME": a.id,
        "AGENT_MODEL": plan.model_tiers[a.primary_model_tier],
        "OUTPUT_DIRECTORY": a.output_directory,
        "ADDITIONAL_CONTEXT_FILES": _bash_context_array(a.additional_context_files),
    }


def _cron_resolved_inputs(plan: EmissionPlan) -> Dict[str, str]:
    """The EXACT substitution map emit_agent_layer feeds cron_config.md."""
    return {"CRON_ENTRIES": _render_cron_entries(plan)}


def build_agent_resolved_inputs(plan: EmissionPlan) -> Dict[str, object]:
    """Return the resolved substitution dicts the agent layer feeds every
    `delivery:wizard render` agent-layer file, keyed by emitted relpath. Used by the
    replay capsule so a future upgrade can re-render each agent file as a pure
    template substitution from persisted values (no re-derivation from upstream
    facts). Reuses the SAME helpers emit_agent_layer substitutes from, so the values
    are identical to what was emitted.

    Empty when foundation_only_mode (no agent layer is emitted)."""
    if plan.foundation_only_mode:
        return {}
    by_relpath: Dict[str, Dict[str, str]] = {
        "agents/prompts/orchestrator_prompt.md": _orchestrator_resolved_inputs(plan),
        "agents/prompts/qa_agent_prompt.md": _qa_resolved_inputs(plan),
        "agents/cron/cron_config.md": _cron_resolved_inputs(plan),
    }
    for a in plan.agents:
        by_relpath[f"agents/prompts/{a.id}_prompt.md"] = _agent_prompt_resolved_inputs(plan, a)
        by_relpath[f"agents/scripts/{a.id}.sh"] = _agent_script_resolved_inputs(plan, a)
    return {"by_relpath": by_relpath}


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
    written.append(_emit_from_template(
        bt / _BUNDLE_ORCHESTRATOR_REL,
        prompts_dir / "orchestrator_prompt.md",
        _orchestrator_resolved_inputs(plan),
        "orchestrator_prompt.md",
    ))

    # --- QA agent (every system gets exactly one) — tier NAMES ---
    written.append(_emit_from_template(
        bt / _BUNDLE_QA_REL,
        prompts_dir / "qa_agent_prompt.md",
        _qa_resolved_inputs(plan),
        "qa_agent_prompt.md",
    ))

    # --- Specialist agents (data plane) ---
    for a in plan.agents:
        # Prompt: tier NAMES (a.primary_model_tier / a.status_model_tier)
        written.append(_emit_from_template(
            bt / _BUNDLE_SPECIALIST_REL,
            prompts_dir / f"{a.id}_prompt.md",
            _agent_prompt_resolved_inputs(plan, a),
            f"{a.id}_prompt.md",
        ))
        # Invocation script: RESOLVED model string (programmatic --model)
        script_path = _emit_from_template(
            bt / _BUNDLE_INVOCATION_REL,
            scripts_dir / f"{a.id}.sh",
            _agent_script_resolved_inputs(plan, a),
            f"{a.id}.sh",
        )
        script_path.chmod(SCRIPT_MODE)
        written.append(script_path)

    # --- Cron config — scheduled agents become Orchestrator-invoked entries (control-plane default) ---
    cron_out = cron_dir / "cron_config.md"
    written.append(_emit_from_template(
        bt / _BUNDLE_CRON_REL,
        cron_out,
        _cron_resolved_inputs(plan),
        "cron_config.md",
    ))

    # --- External-write lib (emitted ONLY when the plan writes back to an external surface) ---
    # A system that writes back to nothing carries none of this lib (no dead code). The copy is
    # source-gated on the bundle carrying the lib files (decision reported by
    # external_write_lib_emit_set; physical emit lands once the bundle ships them).
    written += _emit_external_write_lib(plan, staging_dir, build_repo_root)

    # --- Initial capability-descriptor set (writes-back only) — the build-time coverage gate
    # reads security/capability_descriptors.json; without it a fresh writes-back build fails
    # closed (dead on arrival). Same writes-back + source gating as the lib emit above. ---
    written += _emit_capability_descriptor_set(plan, staging_dir, build_repo_root)

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
