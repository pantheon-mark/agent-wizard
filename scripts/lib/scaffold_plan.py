"""Typed scaffold-plan loader (stdlib-only).

Loads a per-shape scaffold-plan JSON file from the wizard-distributed
foundation-bundles directory, validates it against the scaffold-plan-v1
contract, and returns a frozen ScaffoldPlan dataclass. FAIL-fast on any
invariant violation.

The scaffold plan carries the fixed defaults a generator uses to assemble
a system of a given shape — control-plane paths, model-tier mappings,
agent output profile, criticality policy, and allowed resource claims.
Shape-specific overrides supplied at generation time take precedence over
these defaults; the plan itself is shape-correct and distribution-ready.

Wizard distribution stays pip-install-free: no PyYAML, no jsonschema,
no third-party deps. JSON via stdlib json is the wizard-runtime data format.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


EXPECTED_CONTRACT_ID = "scaffold-plan"
EXPECTED_CONTRACT_VERSIONS = {"scaffold-plan-v1"}

# All 13 fields that must be present as top-level keys in the scaffold-plan JSON.
REQUIRED_FIELDS = (
    "system_shape",
    "authority_profile",
    "model_tiers",
    "control_plane",
    "control_plane_runtime_created",
    "orchestrator",
    "i9_coverage_files",
    "emitted_file_defaults",
    "agent_prompt_dir",
    "agent_scripts_dir",
    "agent_output_profile",
    "criticality_model_policy",
    "allowed_resource_claims",
)


class ScaffoldPlanError(Exception):
    """Raised when scaffold-plan load or validation fails. Message names the failed check."""


@dataclass(frozen=True)
class ScaffoldPlan:
    """Immutable, validated scaffold plan for a single system shape."""
    system_shape: str
    authority_profile: Dict[str, Any]
    model_tiers: Dict[str, str]
    control_plane: Dict[str, str]
    control_plane_runtime_created: List[str]
    orchestrator: Dict[str, Any]
    i9_coverage_files: List[str]
    emitted_file_defaults: Dict[str, Any]
    agent_prompt_dir: str
    agent_scripts_dir: str
    agent_output_profile: Dict[str, Any]
    criticality_model_policy: Dict[str, Any]
    allowed_resource_claims: List[str]


# --- helpers -----------------------------------------------------------------

def _require(cond: bool, invariant: str, detail: str) -> None:
    if not cond:
        raise ScaffoldPlanError(f"{invariant} FAIL: {detail}")


# --- path resolution ---------------------------------------------------------

def default_scaffold_plans_dir() -> Path:
    """Resolve wizard/foundation-bundles/v0/scaffold-plans/ from this module's location.

    This module lives at wizard/scripts/lib/scaffold_plan.py. Three .parent
    steps reach the wizard root, matching the same resolution used by the
    emission-plan loader for its contract path.
    """
    here = Path(__file__).resolve()
    wizard_root = here.parent.parent.parent   # lib -> scripts -> wizard
    return wizard_root / "foundation-bundles" / "v0" / "scaffold-plans"


# --- loader ------------------------------------------------------------------

def load_scaffold_plan(
    system_shape: str,
    scaffold_plans_dir: Optional[Path] = None,
) -> ScaffoldPlan:
    """Load and validate the scaffold plan for the given system shape.

    Resolves <scaffold_plans_dir>/<system_shape>.json. A missing file is a
    hard failure — there is no silent fallback or default shape substitution.

    Parameters
    ----------
    system_shape:
        The shape identifier, e.g. "markdown-CC". Must match the
        system_shape field inside the JSON file.
    scaffold_plans_dir:
        Override directory to search. Defaults to the wizard-distributed
        foundation-bundles/v0/scaffold-plans/ directory resolved relative
        to this module's location.

    Returns
    -------
    ScaffoldPlan
        A frozen, validated ScaffoldPlan dataclass.

    Raises
    ------
    ScaffoldPlanError
        On any file-not-found, JSON parse error, contract mismatch, missing
        field, or system_shape mismatch.
    """
    plans_dir = scaffold_plans_dir or default_scaffold_plans_dir()
    plan_path = Path(plans_dir) / f"{system_shape}.json"

    # File must exist — no silent default for an unknown shape.
    if not plan_path.exists():
        raise ScaffoldPlanError(
            f"scaffold-plan file not found for shape '{system_shape}': {plan_path}"
        )

    try:
        with plan_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ScaffoldPlanError(
            f"scaffold-plan file is not valid JSON: {plan_path}: {e}"
        ) from e

    _require(isinstance(data, dict), "contract", "top-level value must be a JSON object")

    # contract_id check
    _require(
        data.get("contract_id") == EXPECTED_CONTRACT_ID,
        "contract_id",
        f"expected '{EXPECTED_CONTRACT_ID}', got {data.get('contract_id')!r}",
    )

    # contract_version check
    cv = data.get("contract_version")
    _require(
        isinstance(cv, str) and cv in EXPECTED_CONTRACT_VERSIONS,
        "contract_version",
        f"must be one of {sorted(EXPECTED_CONTRACT_VERSIONS)}; got {cv!r}",
    )

    # required fields present
    for field_name in REQUIRED_FIELDS:
        _require(
            field_name in data,
            "required_field",
            f"missing required field '{field_name}'",
        )

    # system_shape in file must match the requested shape
    _require(
        data["system_shape"] == system_shape,
        "system_shape_match",
        f"file declares system_shape={data['system_shape']!r} but loader "
        f"was asked for {system_shape!r}",
    )

    # structural type checks
    _require(isinstance(data["authority_profile"], dict), "authority_profile", "must be an object")
    _require(isinstance(data["model_tiers"], dict) and data["model_tiers"], "model_tiers", "must be a non-empty object")
    _require(isinstance(data["control_plane"], dict), "control_plane", "must be an object")
    _require(isinstance(data["control_plane_runtime_created"], list), "control_plane_runtime_created", "must be a list")
    _require(isinstance(data["orchestrator"], dict), "orchestrator", "must be an object")
    _require(isinstance(data["i9_coverage_files"], list) and data["i9_coverage_files"], "i9_coverage_files", "must be a non-empty list")
    _require(isinstance(data["emitted_file_defaults"], dict), "emitted_file_defaults", "must be an object")
    _require(isinstance(data["agent_prompt_dir"], str) and data["agent_prompt_dir"], "agent_prompt_dir", "must be a non-empty string")
    _require(isinstance(data["agent_scripts_dir"], str) and data["agent_scripts_dir"], "agent_scripts_dir", "must be a non-empty string")
    _require(isinstance(data["agent_output_profile"], dict), "agent_output_profile", "must be an object")
    _require(isinstance(data["criticality_model_policy"], dict), "criticality_model_policy", "must be an object")
    _require(isinstance(data["allowed_resource_claims"], list), "allowed_resource_claims", "must be a list")

    return ScaffoldPlan(
        system_shape=data["system_shape"],
        authority_profile=dict(data["authority_profile"]),
        model_tiers=dict(data["model_tiers"]),
        control_plane=dict(data["control_plane"]),
        control_plane_runtime_created=list(data["control_plane_runtime_created"]),
        orchestrator=dict(data["orchestrator"]),
        i9_coverage_files=list(data["i9_coverage_files"]),
        emitted_file_defaults=dict(data["emitted_file_defaults"]),
        agent_prompt_dir=data["agent_prompt_dir"],
        agent_scripts_dir=data["agent_scripts_dir"],
        agent_output_profile=dict(data["agent_output_profile"]),
        criticality_model_policy=dict(data["criticality_model_policy"]),
        allowed_resource_claims=list(data["allowed_resource_claims"]),
    )


def main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("usage: scaffold_plan.py <system-shape> [scaffold-plans-dir]", file=sys.stderr)
        return 2
    plans_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        sp = load_scaffold_plan(sys.argv[1], plans_dir)
    except ScaffoldPlanError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(f"OK: validated scaffold plan for shape {sp.system_shape!r}")
    print(f"  model_tiers: {sp.model_tiers}")
    print(f"  control_plane paths: {len(sp.control_plane)}")
    print(f"  i9_coverage_files: {len(sp.i9_coverage_files)}")
    print(f"  allowed_resource_claims: {sp.allowed_resource_claims}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
