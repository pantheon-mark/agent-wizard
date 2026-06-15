"""Interview -> generator projection gate + dispatcher (stdlib-only).

This is the single sanctioned path from an interview transcript to a generated
operator system. It is fail-closed end to end:

    transcript
      -> compile_transcript            (deterministic record from the event log)
      -> assemble_emission_plan        (validates the derived record INTERNALLY,
                                        projects foundation_doc_inputs, fail-loud on
                                        unmappable agent intent; builds the plan dict)
      -> validate_emission_plan        (I1-I10; the single sanctioned validation point)
      -> DISPATCH                      (foundation-only -> generator.generate_bundle;
                                        else -> generate_operator_system)

There is NO direct staging->output path and NO parameter to inject raw
foundation_doc_inputs — the only field input is the transcript, and the projected
inputs are produced by project() inside the assembler. The single bounded exception is
`auto_values`: the `auto`-class config globals (SYSTEM_SHAPE / FOUNDATION_ONLY_MODE /
WIZARD_VERSION / LAST_UPDATED_DATE / LAST_UPDATED_TRIGGER) that no interview step records.
The assembler restricts these to the shape's declared auto_global_fields (fail-closed) and
only gap-fills them (projected values win), so this is not a raw-fdi backdoor — it mirrors the
preview path's auto_values. The legacy mid-interview / close-assembly path is retired once the
System-A transform inventory is fully re-homed (a later phase); this gate is its replacement.

The dispatch functions are module-level so the assembly path can be tested in
isolation from the (file-writing) sinks.

Stdlib-only, pip-install-free.
"""

from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

from derivation_replay import compile_transcript, content_hash  # type: ignore
from build_intent import BuildIntent, AgentIntent  # type: ignore
from scaffold_plan import load_scaffold_plan  # type: ignore
from model_tiers import load_model_tiers  # type: ignore
from corpus_loader import load_corpus_pack  # type: ignore
from emission_plan_assembler import assemble_emission_plan  # type: ignore
from emission_plan import (  # type: ignore
    EmissionPlan, validate_emission_plan, load_contract, default_contract_path,
)


class BridgeResult(NamedTuple):
    sink_result: Any
    plan: EmissionPlan
    derived_record_hash: str   # the derivation receipt (acceptance iv)
    transcript_hash: str


def _dispatch_full_system(plan: EmissionPlan, *, target_dir: Path, build_repo_root: Path,
                          generator_version_override: Optional[str] = None) -> Any:
    """Emit a complete runnable operator system (the full-system sink)."""
    from operator_system_emitter import generate_operator_system  # type: ignore
    return generate_operator_system(plan, target_dir, build_repo_root,
                                    generator_version_override=generator_version_override)


def _dispatch_foundation_only(plan: EmissionPlan, *, target_dir: Path, build_repo_root: Path,
                              generator_version_override: Optional[str] = None) -> Any:
    """Emit foundation docs only (the foundation-only sink). Pinned arg contract
    (C-009): generate_bundle(source_version, target_dir, inputs, build_repo_root, ...)."""
    from generator import generate_bundle  # type: ignore
    return generate_bundle(
        source_version=plan.bundle_version,
        target_dir=target_dir,
        inputs=dict(plan.foundation_doc_inputs),
        build_repo_root=build_repo_root,
        generator_version_override=generator_version_override,
    )


def build_operator_system_from_transcript(
    events: List[dict],
    agent_intents: List[AgentIntent],
    *,
    system_shape: str = "markdown-CC",
    target_dir: Optional[Path] = None,
    build_repo_root: Optional[Path] = None,
    generator_version_override: Optional[str] = None,
    project_name: str = "operator-system",
    bundle_version: str = "v0.4.0",
    model_tiers_override: Optional[Dict[str, str]] = None,
    auto_values: Optional[Dict[str, str]] = None,
) -> BridgeResult:
    """The fail-closed gate. See module docstring. There is intentionally NO
    foundation_doc_inputs parameter — inputs are projector-produced from the transcript. The one
    bounded exception is `auto_values` (the auto-class config globals the emission boundary
    supplies because no step records them; gap-fill only, restricted to auto_global_fields).

    Tier->model resolution: by default the maintained model-tiers registry for the shape
    (real Claude ids, so the emitted start-session.sh carries a real --model — the
    programmatic-model rule), NOT the scaffold-plan's shape-correct placeholders.
    model_tiers_override is the seam for tests / special cases.

    Raises DerivedRecordError (invalid record), ConstraintViolation (unmappable intent),
    or EmissionPlanError (plan invariant) — failing closed before any file is written.
    """
    record = compile_transcript(events)
    scaffold = load_scaffold_plan(system_shape)
    corpus = load_corpus_pack()
    tiers = dict(model_tiers_override) if model_tiers_override else load_model_tiers(system_shape)

    # generator_version (C-006): real clean-worktree identity unless a test override is supplied.
    if generator_version_override is not None:
        generator_version = generator_version_override
    else:
        from generator_version import current_generator_version  # type: ignore
        generator_version = current_generator_version(build_repo_root, require_clean=True)

    intent = BuildIntent(derived_record=record, agent_intents=list(agent_intents))
    plan_dict = assemble_emission_plan(
        intent, scaffold, corpus,
        model_tiers=tiers,
        project_name=project_name, bundle_version=bundle_version, generator_version=generator_version,
        auto_values=auto_values,
    )
    plan = validate_emission_plan(plan_dict, load_contract(default_contract_path()))

    # Dispatch (R5). Referenced as module globals so tests can spy the sinks.
    if plan.foundation_only_mode:
        sink = _dispatch_foundation_only(plan, target_dir=target_dir, build_repo_root=build_repo_root,
                                         generator_version_override=generator_version_override)
    else:
        sink = _dispatch_full_system(plan, target_dir=target_dir, build_repo_root=build_repo_root,
                                     generator_version_override=generator_version_override)

    return BridgeResult(
        sink_result=sink, plan=plan,
        derived_record_hash=content_hash(record),
        transcript_hash=content_hash(events),
    )
