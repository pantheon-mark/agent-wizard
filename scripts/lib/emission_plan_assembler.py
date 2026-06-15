"""Deterministic EmissionPlan assembler (stdlib-only).

Projects a BuildIntent (a validated derived record + agent intents) into a complete
emission-plan dict — the bridge between the interview's semantics and the generator's
contract. Assembly is DETERMINISTIC projection/filtering ONLY: it never discovers
policy or rewrites prose (that is the upstream Claude-derivation layer's job). The
plan it returns is NOT yet validated — the single sanctioned validation point is
validate_emission_plan, applied by the projection gate (interview_bridge).

Fail-closed by construction:
  - the derived record is validated INSIDE this function (validate_derived_record),
    so the projector-produced guarantee holds no matter who calls it — there is no
    parameter to inject raw foundation_doc_inputs;
  - foundation_doc_inputs comes ONLY from project() (the whitelist excludes deferred /
    unconfirmed fields), and routing (foundation-only vs full) reads ONLY the projected
    inputs — a deferred FOUNDATION_ONLY_MODE cannot route the build;
  - agent assembly is fail-loud (a forbidden/unmapped resource claim raises), never
    silent-default;
  - emitted_files coverage of every control-plane path + agent output directory (the
    plan's I9 invariant) is asserted here, before validation, with a clear error.

The Day-2 `current_state` parameter is a forward-compatibility seam only: it is always
None at v0 (a non-None value raises). The deterministic three-way merge that consumes a
prior plan lands in the later mutator slice; the signature exists so that slice extends
this assembler rather than rewriting it.

Stdlib-only, pip-install-free.
"""

from typing import Any, Dict, List, Optional

import derived_record  # type: ignore
from derivation_replay import project  # type: ignore
from build_intent import BuildIntent, ConstraintViolation, validate_build_intent  # type: ignore
from scaffold_plan import ScaffoldPlan  # type: ignore
from agent_record_assembler import assemble_agent_records  # type: ignore
from corpus_loader import resolve_for_shape, to_plan_corpus_cells  # type: ignore

_SCHEMA_VERSION = "emission-plan-v1"
_TEST_GENERATOR_VERSION = "0" * 40  # placeholder for unit tests; the gate supplies the real identity


def assemble_emission_plan(
    intent: BuildIntent,
    scaffold_plan: ScaffoldPlan,
    corpus_records: List[Any],
    *,
    model_tiers: Optional[Dict[str, str]] = None,
    current_state: Optional[Any] = None,
    project_name: str = "operator-system",
    bundle_version: str = "v0.4.0",
    generator_version: str = _TEST_GENERATOR_VERSION,
    auto_values: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Assemble a complete emission-plan dict from a BuildIntent. See module docstring.

    `auto_values` is the bounded auto-global overlay (the `auto` derivation class — machine
    -determined config the operator never answers: SYSTEM_SHAPE / FOUNDATION_ONLY_MODE /
    WIZARD_VERSION / LAST_UPDATED_DATE / LAST_UPDATED_TRIGGER). It is NOT a raw foundation_doc_inputs
    injection: every key is restricted to the shape's declared `auto_global_fields` (fail-closed on
    any other key), and it only FILLS GAPS — a value project() produced from the transcript always
    wins. This mirrors the preview path's auto_values (group_barrier.build_preview_inputs, where the
    projected/confirmed value wins over an auto default of the same name). It exists because no
    interview step records these globals, so a real transcript reaches emit without them; the
    emission boundary supplies them (inject-at-emit, the same model as the preview overlay).

    Raises NotImplementedError if current_state is not None (Day-2 merge is a later slice);
    DerivedRecordError if the derived record is invalid; ConstraintViolation on an
    unmappable agent intent or an uncovered control-plane/agent path; ValueError on an
    auto_values key that is not a declared auto-global for the shape.
    """
    # Day-2 seam (R11): merge-from-prior-state is a later slice; v0 builds from scratch only.
    if current_state is not None:
        raise NotImplementedError(
            "assemble_emission_plan does not merge a current_state at v0; the three-way "
            "merge-apply lands in the later mutator slice. Pass current_state=None."
        )

    # Validate the intent layer + the derived record INTERNALLY — caller-independent safety
    # (this function is public; the projector-produced guarantee must not rely on the gate).
    validate_build_intent(intent)
    dr_contract = derived_record.load_contract(derived_record.default_contract_path())
    derived_record.validate_derived_record(intent.derived_record, dr_contract)

    # foundation_doc_inputs is projector-produced by construction (whitelist excludes deferred).
    fdi = project(intent.derived_record)

    # Bounded auto-global overlay: fill the machine-determined config globals the operator never
    # answers and no step records. Keys are restricted to the shape's declared auto_global_fields
    # (fail-closed) so this can never become the retired raw-fdi injection backdoor; and a value
    # project() already produced from the transcript wins (gap-fill only), mirroring the preview
    # path. So FOUNDATION_ONLY_MODE routing below still reads a single source — the projected value
    # if a step ever recorded it, else the emit-supplied default.
    if auto_values:
        from derivation_groups import load_derivation_groups  # type: ignore  # canonical registry
        legal = set(load_derivation_groups(scaffold_plan.system_shape).auto_global_fields)
        for k, v in auto_values.items():
            if k not in legal:
                raise ValueError(
                    f"auto_values key {k!r} is not a declared auto-global for shape "
                    f"{scaffold_plan.system_shape!r} (legal: {sorted(legal)}) — refusing to inject "
                    "a non-auto field into foundation_doc_inputs")
            if k not in fdi:
                fdi[k] = str(v)

    # Routing reads ONLY the projected inputs (a deferred FOUNDATION_ONLY_MODE must not route).
    foundation_only = str(fdi.get("FOUNDATION_ONLY_MODE", "false")).strip().lower() == "true"

    shape = scaffold_plan.system_shape
    tiers = dict(model_tiers) if model_tiers else dict(scaffold_plan.model_tiers)

    # Agents: none in foundation-only mode (I7); else fail-loud assembly (R8/R9).
    agents = [] if foundation_only else assemble_agent_records(intent.agent_intents, scaffold_plan)

    # Corpus cells projected for this shape (all inline_payload -> template_variants stays empty).
    corpus_cells = to_plan_corpus_cells(resolve_for_shape(corpus_records, shape))

    # emitted_files = the shape's I9-coverage declaration + per-agent prompt/script paths.
    # NOTE: this is NOT the full output manifest (the emitters write far more); it exists only
    # to satisfy I4 (uniqueness) + I9 (control-plane + agent-output coverage). The real manifest
    # is computed post-hoc by scanning the staged tree (upgrade_scaffold_emitter).
    defaults = scaffold_plan.emitted_file_defaults
    paths: List[str] = list(scaffold_plan.i9_coverage_files)
    for a in agents:
        paths.append(f"{scaffold_plan.agent_prompt_dir}/{a['id']}_prompt.md")
        paths.append(f"{scaffold_plan.agent_scripts_dir}/{a['id']}.sh")
    seen = set()
    unique_paths: List[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)
    emitted_files = [
        {"path": p, "managed_by": defaults["managed_by"],
         "local_modifications": defaults["local_modifications"],
         "merge_strategy": defaults["merge_strategy"], "source_refs": list(defaults["source_refs"])}
        for p in unique_paths
    ]

    # I9 coverage guard (fail-loud, BEFORE validation): every control-plane path and every agent
    # output directory must be a covered emitted file OR a declared runtime-created path.
    covered = set(unique_paths) | set(scaffold_plan.control_plane_runtime_created)
    for cp_name, cp_path in scaffold_plan.control_plane.items():
        if cp_path not in covered:
            raise ConstraintViolation(
                kind="uncovered_path", subject=f"control_plane.{cp_name}",
                detail=f"path {cp_path!r} is neither an emitted file nor runtime-created",
                operator_options=["add it to the shape's i9_coverage_files or control_plane_runtime_created"],
            )
    for a in agents:
        if a["output_directory"] not in covered:
            raise ConstraintViolation(
                kind="uncovered_path", subject=f"agent.{a['id']}",
                detail=f"output_directory {a['output_directory']!r} is neither emitted nor runtime-created",
                operator_options=["add the agent output directory to control_plane_runtime_created"],
            )

    return {
        "schema_version": _SCHEMA_VERSION,
        "system_shape": shape,
        "foundation_only_mode": foundation_only,
        "project_name": project_name,
        "bundle_version": bundle_version,
        "generator_version": generator_version,
        "authority_profile": dict(scaffold_plan.authority_profile),
        "model_tiers": tiers,
        "control_plane": dict(scaffold_plan.control_plane),
        "control_plane_runtime_created": list(scaffold_plan.control_plane_runtime_created),
        "orchestrator": dict(scaffold_plan.orchestrator),
        "agents": agents,
        "foundation_doc_inputs": dict(fdi),
        "corpus_cells": corpus_cells,
        "emitted_files": emitted_files,
        "template_variants": [],
    }
