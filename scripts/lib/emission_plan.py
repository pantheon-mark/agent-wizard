"""Typed emission-plan loader + validator (stdlib-only).

Loads the wizard-distributed emission-plan contract (JSON) as canonical authority
for enums + field lists, then validates an emission-plan dict (parsed from an
extended inputs.json) against it and returns a typed EmissionPlan. FAIL-fast on
any invariant violation.

The generator builds the plan dict (resolving content at authoring time so the
plan is self-contained — downstream emitters read ONLY the plan, never any
build-side source), then calls validate_emission_plan() before emitting any file.

Wizard distribution stays pip-install-free: no PyYAML, no jsonschema, no third-party
deps. JSON via stdlib `json` is the wizard-runtime contract format. Shape-specific
adaptation is handled by per-shape template-variant selection, not by logic here.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


EXPECTED_CONTRACT_ID = "emission-plan"
EXPECTED_CONTRACT_VERSIONS = {"emission-plan-v1"}
MODEL_TIER_KEYS = ("high", "standard", "fast")


class EmissionPlanError(Exception):
    """Raised when emission-plan load or validation fails. Message names the invariant."""


# --- typed records -----------------------------------------------------------

@dataclass(frozen=True)
class AuthorityProfile:
    id: str
    posture: str
    source: str
    expires_on_trigger: str


@dataclass(frozen=True)
class ControlPlane:
    queue_path: str
    lock_path: str
    handoff_dir: str
    checkpoint_dir: str
    cron_config_path: str
    session_state_path: str
    session_bootstrap_path: str
    session_log_path: str
    error_log_path: str
    notification_log_path: str


@dataclass(frozen=True)
class AgentRecord:
    id: str
    role_description: str
    criticality_tier: str
    primary_model_tier: str
    status_model_tier: str
    permitted_write_directories: List[str]
    additional_context_files: List[str]
    step_completion_criteria: str
    task_completion_criteria: str
    output_format_specification: str
    output_directory: str
    cron_cadence: Optional[str] = None


@dataclass(frozen=True)
class CorpusCell:
    cell_id: str
    emission_target: List[str]
    emission_posture: str
    authority_gate: str
    authority_basis: str
    authority_source: str
    source_type: str
    payload: Optional[str] = None
    template_variant_key: Optional[str] = None


@dataclass(frozen=True)
class EmittedFile:
    path: str
    managed_by: str
    local_modifications: str
    merge_strategy: str
    source_refs: List[str]


@dataclass(frozen=True)
class TemplateVariant:
    cell_id: str
    system_shape: str
    template_path: str


@dataclass(frozen=True)
class EmissionPlan:
    schema_version: str
    system_shape: str
    foundation_only_mode: bool
    project_name: str
    bundle_version: str
    generator_version: str
    authority_profile: AuthorityProfile
    model_tiers: Dict[str, str]
    control_plane: ControlPlane
    orchestrator: Dict[str, Any]
    agents: List[AgentRecord]
    foundation_doc_inputs: Dict[str, Any]
    corpus_cells: List[CorpusCell]
    emitted_files: List[EmittedFile]
    template_variants: List[TemplateVariant]
    control_plane_runtime_created: List[str] = field(default_factory=list)


# --- contract loading --------------------------------------------------------

def load_contract(contract_path: Path) -> Dict[str, Any]:
    """Load + lightly validate the emission-plan contract JSON."""
    try:
        with contract_path.open("r", encoding="utf-8") as f:
            contract = json.load(f)
    except FileNotFoundError as e:
        raise EmissionPlanError(f"Contract file not found: {contract_path}") from e
    except json.JSONDecodeError as e:
        raise EmissionPlanError(f"Contract file is not valid JSON: {contract_path}: {e}") from e
    if not isinstance(contract, dict):
        raise EmissionPlanError("Contract top-level value must be a JSON object")
    if contract.get("contract_id") != EXPECTED_CONTRACT_ID:
        raise EmissionPlanError(
            f"contract_id mismatch — expected '{EXPECTED_CONTRACT_ID}', got '{contract.get('contract_id')}'"
        )
    cv = contract.get("contract_version")
    if not isinstance(cv, str) or cv not in EXPECTED_CONTRACT_VERSIONS:
        raise EmissionPlanError(
            f"contract_version must be one of {sorted(EXPECTED_CONTRACT_VERSIONS)}; got {cv!r}"
        )
    for key in ("enums", "required_top_level_fields", "agent_record_fields",
                "corpus_cell_fields", "emitted_file_fields", "control_plane_fields"):
        if key not in contract:
            raise EmissionPlanError(f"contract missing required section '{key}'")
    return contract


def default_contract_path() -> Path:
    here = Path(__file__).resolve()
    wizard_root = here.parent.parent.parent
    return wizard_root / "foundation-bundles" / "v0" / "contracts" / "emission-plan-contract-v1.json"


# --- helpers -----------------------------------------------------------------

def _require(cond: bool, invariant: str, detail: str) -> None:
    if not cond:
        raise EmissionPlanError(f"{invariant} FAIL: {detail}")


def _enum_member(enums: Dict[str, List[str]], enum_name: str, value: Any, where: str) -> None:
    members = enums.get(enum_name, [])
    _require(value in members, "I5", f"{where} value {value!r} not in closed enum {enum_name}={members}")


def _str_field(record: Dict[str, Any], name: str, where: str) -> str:
    val = record.get(name)
    _require(isinstance(val, str) and val != "", "I1", f"{where}.{name} must be a non-empty string")
    return val


# --- plan validation ---------------------------------------------------------

def validate_emission_plan(plan: Dict[str, Any], contract: Dict[str, Any]) -> EmissionPlan:
    """Validate a plan dict against the contract (I1-I10); return a typed EmissionPlan."""
    enums = contract["enums"]

    # I1 — required top-level fields present
    for f_name in contract["required_top_level_fields"]:
        _require(f_name in plan, "I1", f"missing required top-level field '{f_name}'")

    _require(plan["schema_version"] == "emission-plan-v1", "I1",
             f"schema_version must be 'emission-plan-v1'; got {plan['schema_version']!r}")
    _enum_member(enums, "system_shape", plan["system_shape"], "system_shape")
    _require(isinstance(plan["foundation_only_mode"], bool), "I1", "foundation_only_mode must be a bool")

    # authority_profile (I2)
    ap = plan["authority_profile"]
    _require(isinstance(ap, dict), "I1", "authority_profile must be an object")
    for f_name in contract["authority_profile_fields"]:
        _str_field(ap, f_name, "authority_profile")
    _enum_member(enums, "authority_posture", ap["posture"], "authority_profile.posture")  # I2

    # model_tiers (I6 partial — keys + resolved strings)
    mt = plan["model_tiers"]
    _require(isinstance(mt, dict) and mt, "I1", "model_tiers must be a non-empty object")
    for k, v in mt.items():
        _require(k in MODEL_TIER_KEYS, "I6", f"model_tiers key '{k}' is not a valid tier key {MODEL_TIER_KEYS}")
        _require(isinstance(v, str) and v != "", "I6",
                 f"model_tiers['{k}'] must be a non-empty resolved model string")

    # control_plane
    cp = plan["control_plane"]
    _require(isinstance(cp, dict), "I1", "control_plane must be an object")
    for f_name in contract["control_plane_fields"]:
        _str_field(cp, f_name, "control_plane")
    runtime_created = plan.get("control_plane_runtime_created", [])
    _require(isinstance(runtime_created, list), "I1", "control_plane_runtime_created must be a list")

    # orchestrator (I6 — tier references are tier keys)
    orch = plan["orchestrator"]
    _require(isinstance(orch, dict), "I1", "orchestrator must be an object")
    for tier_field in ("model_tier_high", "model_tier_standard", "model_tier_fast"):
        _require(orch.get(tier_field) in MODEL_TIER_KEYS, "I6",
                 f"orchestrator.{tier_field} must be a tier key {MODEL_TIER_KEYS}, "
                 f"not a literal model string; got {orch.get(tier_field)!r}")
        _require(orch[tier_field] in mt, "I10",
                 f"orchestrator.{tier_field} tier '{orch[tier_field]}' is not a key in model_tiers")

    # agents (I1, I5, I6/I10, I7)
    agents = plan["agents"]
    _require(isinstance(agents, list), "I1", "agents must be a list")
    if plan["foundation_only_mode"]:
        _require(len(agents) == 0, "I7", "foundation_only_mode is true but agents is non-empty")
    agent_records: List[AgentRecord] = []
    for i, a in enumerate(agents):
        where = f"agents[{i}]"
        _require(isinstance(a, dict), "I1", f"{where} must be an object")
        for f_name in contract["agent_record_fields"]:
            _require(f_name in a, "I1", f"{where} missing field '{f_name}'")
        _enum_member(enums, "criticality_tier", a["criticality_tier"], f"{where}.criticality_tier")
        for tier_field in ("primary_model_tier", "status_model_tier"):
            _require(a[tier_field] in MODEL_TIER_KEYS, "I6",
                     f"{where}.{tier_field} must be a tier key {MODEL_TIER_KEYS}, not a model string; got {a[tier_field]!r}")
            _require(a[tier_field] in mt, "I10", f"{where}.{tier_field} '{a[tier_field]}' is not a key in model_tiers")
        agent_records.append(AgentRecord(
            id=a["id"], role_description=a["role_description"], criticality_tier=a["criticality_tier"],
            primary_model_tier=a["primary_model_tier"], status_model_tier=a["status_model_tier"],
            permitted_write_directories=list(a["permitted_write_directories"]),
            additional_context_files=list(a["additional_context_files"]),
            step_completion_criteria=a["step_completion_criteria"],
            task_completion_criteria=a["task_completion_criteria"],
            output_format_specification=a["output_format_specification"],
            output_directory=a["output_directory"], cron_cadence=a.get("cron_cadence"),
        ))

    # template_variants registry (for I8)
    variants = plan["template_variants"]
    _require(isinstance(variants, list), "I1", "template_variants must be a list")
    variant_index = set()
    variant_records: List[TemplateVariant] = []
    for i, v in enumerate(variants):
        for f_name in contract["template_variant_fields"]:
            _require(f_name in v, "I1", f"template_variants[{i}] missing field '{f_name}'")
        _enum_member(enums, "system_shape", v["system_shape"], f"template_variants[{i}].system_shape")
        variant_index.add((v["cell_id"], v["system_shape"]))
        variant_records.append(TemplateVariant(cell_id=v["cell_id"], system_shape=v["system_shape"],
                                               template_path=v["template_path"]))

    # corpus_cells (I3 authority invariant, I5, I8 source invariant)
    cells = plan["corpus_cells"]
    _require(isinstance(cells, list), "I1", "corpus_cells must be a list")
    cell_records: List[CorpusCell] = []
    for i, c in enumerate(cells):
        where = f"corpus_cells[{i}]"
        for f_name in contract["corpus_cell_fields"]:
            _require(f_name in c, "I1", f"{where} missing field '{f_name}'")
        _enum_member(enums, "emission_posture", c["emission_posture"], f"{where}.emission_posture")
        _enum_member(enums, "authority_basis", c["authority_basis"], f"{where}.authority_basis")
        _enum_member(enums, "authority_source", c["authority_source"], f"{where}.authority_source")
        gate = c["authority_gate"]
        _require(gate == "applies-all" or gate in enums["authority_posture"], "I5",
                 f"{where}.authority_gate {gate!r} not 'applies-all' or an authority_posture member")
        # I3 — fail-closed authority basis/source coupling
        if gate == "applies-all":
            _require(c["authority_basis"] == "not_applicable", "I3",
                     f"{where} authority_gate=applies-all requires authority_basis=not_applicable")
            _require(c["authority_source"] == "not_applicable", "I3",
                     f"{where} authority_gate=applies-all requires authority_source=not_applicable")
        else:
            _require(c["authority_basis"] in ("provisional_default", "operator-profile-derived"), "I3",
                     f"{where} authority_gate={gate} requires authority_basis in (provisional_default, operator-profile-derived)")
            _require(c["authority_source"] in ("delegated", "wizard-default", "hard-control", "operator-configured"),
                     "I3", f"{where} authority_gate={gate} requires a concrete authority_source")
        # I8 — source self-containment
        _enum_member(enums, "source_type", c["source_type"], f"{where}.source_type")
        if c["source_type"] == "inline_payload":
            _require(isinstance(c.get("payload"), str) and c.get("payload") != "", "I8",
                     f"{where} source_type=inline_payload requires a non-empty payload")
        elif c["source_type"] == "template_variant":
            _require((c["cell_id"], plan["system_shape"]) in variant_index, "I8",
                     f"{where} source_type=template_variant has no template_variants entry for "
                     f"({c['cell_id']}, {plan['system_shape']})")
        cell_records.append(CorpusCell(
            cell_id=c["cell_id"], emission_target=list(c["emission_target"]),
            emission_posture=c["emission_posture"], authority_gate=gate,
            authority_basis=c["authority_basis"], authority_source=c["authority_source"],
            source_type=c["source_type"], payload=c.get("payload"),
            template_variant_key=c.get("template_variant_key"),
        ))

    # emitted_files (I4 uniqueness, I5)
    files = plan["emitted_files"]
    _require(isinstance(files, list) and files, "I1", "emitted_files must be a non-empty list")
    seen_paths = set()
    emitted_paths = set()
    file_records: List[EmittedFile] = []
    for i, ef in enumerate(files):
        where = f"emitted_files[{i}]"
        for f_name in contract["emitted_file_fields"]:
            _require(f_name in ef, "I1", f"{where} missing field '{f_name}'")
        p = _str_field(ef, "path", where)
        _require(p not in seen_paths, "I4", f"duplicate emitted_files path: {p}")
        seen_paths.add(p)
        emitted_paths.add(p)
        _enum_member(enums, "managed_by", ef["managed_by"], f"{where}.managed_by")
        _enum_member(enums, "local_modifications", ef["local_modifications"], f"{where}.local_modifications")
        _enum_member(enums, "merge_strategy", ef["merge_strategy"], f"{where}.merge_strategy")
        _require("base_hash" not in ef, "I1",
                 f"{where} must NOT carry base_hash (output-manifest field, not input-plan field)")
        file_records.append(EmittedFile(path=p, managed_by=ef["managed_by"],
                                        local_modifications=ef["local_modifications"],
                                        merge_strategy=ef["merge_strategy"],
                                        source_refs=list(ef["source_refs"])))

    # I9 — control-plane + agent output dirs covered by emitted_files or runtime-created
    covered = emitted_paths | set(runtime_created)
    for f_name in contract["control_plane_fields"]:
        path_val = cp[f_name]
        _require(path_val in covered, "I9",
                 f"control_plane.{f_name} path {path_val!r} is neither emitted nor in control_plane_runtime_created")
    for ar in agent_records:
        _require(ar.output_directory in covered, "I9",
                 f"agent {ar.id!r} output_directory {ar.output_directory!r} is neither emitted nor runtime-created")

    return EmissionPlan(
        schema_version=plan["schema_version"], system_shape=plan["system_shape"],
        foundation_only_mode=plan["foundation_only_mode"], project_name=plan["project_name"],
        bundle_version=plan["bundle_version"], generator_version=plan["generator_version"],
        authority_profile=AuthorityProfile(id=ap["id"], posture=ap["posture"], source=ap["source"],
                                           expires_on_trigger=ap["expires_on_trigger"]),
        model_tiers=dict(mt),
        control_plane=ControlPlane(**{k: cp[k] for k in contract["control_plane_fields"]}),
        orchestrator=dict(orch), agents=agent_records, foundation_doc_inputs=dict(plan["foundation_doc_inputs"]),
        corpus_cells=cell_records, emitted_files=file_records, template_variants=variant_records,
        control_plane_runtime_created=list(runtime_created),
    )


def load_emission_plan(plan_path: Path, contract_path: Optional[Path] = None) -> EmissionPlan:
    """Load a plan JSON file + the contract; validate; return a typed EmissionPlan."""
    contract = load_contract(contract_path or default_contract_path())
    try:
        with Path(plan_path).open("r", encoding="utf-8") as f:
            plan = json.load(f)
    except FileNotFoundError as e:
        raise EmissionPlanError(f"Plan file not found: {plan_path}") from e
    except json.JSONDecodeError as e:
        raise EmissionPlanError(f"Plan file is not valid JSON: {plan_path}: {e}") from e
    if not isinstance(plan, dict):
        raise EmissionPlanError("Plan top-level value must be a JSON object")
    return validate_emission_plan(plan, contract)


def main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("usage: emission_plan.py <plan.json> [contract.json]", file=sys.stderr)
        return 2
    contract_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        ep = load_emission_plan(Path(sys.argv[1]), contract_path)
    except EmissionPlanError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(f"OK: validated emission plan for {ep.project_name!r}")
    print(f"  system_shape: {ep.system_shape}; agents: {len(ep.agents)}; "
          f"corpus_cells: {len(ep.corpus_cells)}; emitted_files: {len(ep.emitted_files)}")
    print(f"  authority_profile.posture: {ep.authority_profile.posture}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
