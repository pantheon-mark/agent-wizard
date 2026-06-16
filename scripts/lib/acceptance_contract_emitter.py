"""Acceptance-contract emitter — writes per-phase acceptance markdown files.

Called from operator_system_emitter as step 6c (after foundation docs, before
the upgrade scaffold). Reads the acceptance_contracts list from plan.foundation_doc_inputs
via re-assembly (since the typed EmissionPlan does not carry a separate field for them),
or accepts them passed in directly for efficiency.

Stdlib-only, pip-install-free.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from emission_plan import EmissionPlan  # type: ignore
from capability_projection import parse_increments, CapabilityProjectionError  # type: ignore
from phase_acceptance_assembler import assemble_phase_acceptance  # type: ignore
from emission_plan_assembler import _render_acceptance_contract, _ACCEPTANCE_DIR  # type: ignore


def _rebuild_acceptance_contracts(plan: EmissionPlan) -> List[Dict[str, str]]:
    """Re-derive acceptance contracts from a validated EmissionPlan.

    Used when the typed EmissionPlan is the only available handle (e.g. the emitter
    receives an already-validated plan). Mirrors the logic in
    emission_plan_assembler._assemble_acceptance_contracts — same inputs, same output.
    Returns an empty list when CAPABILITY_INCREMENTS is absent, empty, or all-candidate.
    """
    raw = plan.foundation_doc_inputs.get("CAPABILITY_INCREMENTS")
    if not raw or not str(raw).strip():
        return []

    try:
        increments = parse_increments(str(raw))
    except CapabilityProjectionError:
        return []

    if not increments:
        return []

    # Build agent dicts from the plan's typed AgentRecord list.
    agent_dicts: List[Dict[str, Any]] = [
        {
            "id": a.id,
            # AgentRecord carries role_description but not display_name; use id as the
            # name so phase_acceptance_assembler._agent_name finds it via 'id' fallback.
            "display_name": a.id,
            # acceptance_signals are not stored on AgentRecord (they are folded into
            # step_completion_criteria prose). Emit an empty list — the assembler handles
            # the no-signals case gracefully (defer trigger fires for unmatched agents).
            "acceptance_signals": [],
        }
        for a in plan.agents
    ]

    contracts = assemble_phase_acceptance(increments, agent_dicts)

    result: List[Dict[str, str]] = []
    for c in contracts:
        filename = f"phase_{c.phase:02d}_acceptance.md"
        path = f"{_ACCEPTANCE_DIR}/{filename}"
        content = _render_acceptance_contract(c)
        result.append({"path": path, "content": content})

    return result


def emit_acceptance_contracts(
    plan: EmissionPlan,
    staging_dir: Path,
    *,
    acceptance_contracts: Optional[List[Dict[str, str]]] = None,
) -> List[Path]:
    """Write per-phase acceptance markdown files into staging_dir/agents/acceptance/.

    If `acceptance_contracts` is supplied (from the raw plan dict, where content is
    pre-rendered), uses those directly. Otherwise re-derives them from the typed plan
    via _rebuild_acceptance_contracts. Returns every path written.
    """
    if acceptance_contracts is None:
        acceptance_contracts = _rebuild_acceptance_contracts(plan)

    if not acceptance_contracts:
        return []

    accept_dir = staging_dir / _ACCEPTANCE_DIR
    accept_dir.mkdir(parents=True, exist_ok=True)

    written: List[Path] = []
    for entry in acceptance_contracts:
        out_path = staging_dir / entry["path"]
        out_path.write_text(entry["content"], encoding="utf-8")
        written.append(out_path)

    return written
