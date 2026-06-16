"""Acceptance-contract emitter — writes per-phase acceptance markdown files.

Called from operator_system_emitter as step 6c (after foundation docs, before
the upgrade scaffold). Writes plan.acceptance_contracts (pre-rendered path +
content pairs) directly to disk — single source of truth, no re-derivation.

The assembler (emission_plan_assembler._assemble_acceptance_contracts) renders
the full content including core_checks from agent acceptance_signals at plan-
assembly time and stores it in plan["acceptance_contracts"]. validate_emission_plan
carries that content into EmissionPlan.acceptance_contracts. This emitter writes
those records verbatim; it never re-derives content from the typed EmissionPlan.

Stdlib-only, pip-install-free.
"""

from pathlib import Path
from typing import List

from emission_plan import EmissionPlan  # type: ignore
from emission_plan_assembler import _ACCEPTANCE_DIR  # type: ignore


def emit_acceptance_contracts(
    plan: EmissionPlan,
    staging_dir: Path,
) -> List[Path]:
    """Write per-phase acceptance markdown files into staging_dir.

    Reads plan.acceptance_contracts (AcceptanceContractFile records carrying
    pre-rendered path + content from the assembler) and writes each file to
    staging_dir / entry.path. Returns every path written.

    Returns an empty list when plan.acceptance_contracts is empty (no committed
    phases, or foundation-only mode).
    """
    if not plan.acceptance_contracts:
        return []

    accept_dir = staging_dir / _ACCEPTANCE_DIR
    accept_dir.mkdir(parents=True, exist_ok=True)

    written: List[Path] = []
    for entry in plan.acceptance_contracts:
        out_path = staging_dir / entry.path
        out_path.write_text(entry.content, encoding="utf-8")
        written.append(out_path)

    return written
