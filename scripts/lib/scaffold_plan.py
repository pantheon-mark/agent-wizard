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
from typing import Any, Dict, List, Optional, Set


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


# Role constant for a dependency the system writes back to (symmetric partner to
# boundary_input).  A dependency with this role causes its surface name to be added
# to the owning agent's permitted-write set AND to the orchestrator's permitted set
# (the bound-orchestrator carve-out: the orchestrator is the legal invoker of the
# named external-write operations for that surface).
_ROLE_BOUNDARY_OUTPUT = "boundary_output"

# The reserved id for the orchestrator in every emitted system.  The orchestrator
# is always present in the permission map so callers can read its permitted set
# without a special-case existence check.
_ORCHESTRATOR_ID = "orchestrator"


def derive_permission_map(
    scaffold_plan: "ScaffoldPlan",
    agent_records: List[Dict[str, Any]],
    dependencies: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Derive the permission map — agent id -> ordered list of permitted paths/surfaces.

    Rules applied (in this order; applied to each agent in agent_records plus the
    orchestrator, which is always present):

    1. **Base paths** — every agent starts with its existing
       ``permitted_write_directories`` list from its agent record (the paths the
       scaffold policy already granted).

    2. **Deliverable folder** — if the agent record has ``operator_facing=True``
       its ``deliverable_root`` is added to its permitted set (so operator-facing
       deliverables are never written off-map).

    3. **External-write surface (owning agent)** — for each dependency in
       *dependencies* that carries the ``boundary_output`` role AND nominates an
       ``owner_agent_id``, that dependency's ``name`` is added to the owning
       agent's permitted set.  The ``name`` field is the external-surface
       identifier (e.g. ``"company_tracker"``, ``"budget_sheet"``).

    4. **External-write surface (orchestrator carve-out)** — the same surface name
       is also added to the orchestrator's permitted set.  The orchestrator is the
       single bound writer that may invoke the named external-write operations for
       that surface; the grant makes this explicit and lets the blast-radius gate
       check both the owning agent AND the orchestrator against the map.

    Only ``boundary_output`` dependencies generate write grants.  A
    ``boundary_input``-only dependency (the system reads from it) never yields a
    write grant to any agent.  A dependency with no ``owner_agent_id`` still gets
    the orchestrator carve-out (the orchestrator remains the single legal invoker)
    but no specialist agent is granted the surface.

    Parameters
    ----------
    scaffold_plan:
        The loaded, validated scaffold plan for this system shape.  Carried here
        for future shape-specific policy hooks; not yet queried beyond its
        presence.
    agent_records:
        List of agent record dicts — each must contain ``id`` (str) and
        ``permitted_write_directories`` (list of str).  Optionally carries
        ``operator_facing`` (bool) and ``deliverable_root`` (str).  These are the
        same records produced by ``agent_record_assembler.assemble_agent_records``.
    dependencies:
        List of dependency dicts — each must contain ``name`` (str) and ``roles``
        (list of str).  Optionally carries ``owner_agent_id`` (str) — the id of
        the specialist agent responsible for this write.  These are the dependency
        identity records produced by the wizard's interview capture (step 09 in the
        interview sequence; Task 7 wires them in; the derivation here is
        independent of the wiring and can be tested with fixture data in advance).

    Returns
    -------
    Dict[str, List[str]]
        Mapping of agent id -> deduplicated, order-preserving list of permitted
        paths/surfaces.  Always includes an ``"orchestrator"`` key even when no
        writes-back dependency exists (the orchestrator has base control-plane
        paths; callers can rely on the key existing without an existence check).
        The orchestrator's base paths are the control-plane paths from the
        scaffold plan's ``control_plane`` dict values.
    """
    # Collect the writes-back dependencies: (surface_name, owner_agent_id | None)
    writes_back: List[tuple] = []
    for dep in dependencies:
        if _ROLE_BOUNDARY_OUTPUT in dep.get("roles", []):
            surface_name = dep.get("name", "")
            owner = dep.get("owner_agent_id")  # May be None if not yet wired.
            writes_back.append((surface_name, owner))

    # Build a working dict: agent_id -> ordered set (insertion-order-preserving).
    pmap: Dict[str, list] = {}

    def _add(agent_id: str, paths: List[str]) -> None:
        if agent_id not in pmap:
            pmap[agent_id] = []
        seen: Set[str] = set(pmap[agent_id])
        for p in paths:
            if p and p not in seen:
                pmap[agent_id].append(p)
                seen.add(p)

    # Seed each agent from its existing permitted_write_directories.
    for rec in agent_records:
        agent_id = rec["id"]
        base = list(rec.get("permitted_write_directories") or [])
        _add(agent_id, base)
        # Rule 2: operator-facing agents add their deliverable_root.
        if rec.get("operator_facing"):
            dr = rec.get("deliverable_root")
            if dr:
                _add(agent_id, [dr])

    # Seed the orchestrator from the control-plane paths.
    orch_base = list(scaffold_plan.control_plane.values())
    _add(_ORCHESTRATOR_ID, orch_base)

    # Rules 3 + 4: writes-back grants.
    for surface_name, owner_agent_id in writes_back:
        if not surface_name:
            continue
        # Rule 3: owning agent gets the surface.
        if owner_agent_id:
            _add(owner_agent_id, [surface_name])
        # Rule 4: orchestrator always gets the surface (bound carve-out).
        _add(_ORCHESTRATOR_ID, [surface_name])

    return pmap


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
