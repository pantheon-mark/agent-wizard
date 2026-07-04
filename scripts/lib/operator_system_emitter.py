"""Operator-system orchestrator — composes the full runnable operator system.

A thin orchestration layer over the typed emitters: it emits the base scaffold,
the agent-execution layer, and the inherited-corpus artifacts into a single
STAGING directory, in the order their dependencies require:

  1. render the inherited-principles block for CLAUDE.md;
  2. emit the base scaffold (root + operational dirs), feeding it that block;
  3. emit the /agents/ execution layer (reuse the agent-layer emitter);
  4. emit the corpus single home (rules_library) and the decisions/ ADR core;
  5. inject per-target operational hooks into the now-emitted files (idempotent);
  6. emit the foundation docs (vision/approach/.../prd) at the operator-project
     root, via the foundation-doc emitter (shared canonical renderer);
  7. emit the .wizard/ upgrade scaffold LAST — the manifest-v2 full-tree manifest
     (which folds the corpus authority stamps in and hashes the now-final tree,
     foundation docs included), the upgrade policy + history, and the command surface.

Steps 3-5 depend on step 2's files existing (hooks attach to scaffold + agent
files), which is why the corpus hook pass runs before the scaffold. Step 7 runs
strictly last so its per-file base_hashes cover the final tree, and so the corpus
authority (folded into the manifest) replaces the separate sidecar. The corpus pack
is loaded once and shared across the corpus emitters for consistency.

Foundation docs are now part of this orchestration (step 6) — emitted at the
operator-project root from the same validated EmissionPlan, so ONE plan produces a
complete runnable operator system. The guarded top-level entry point
(generate_operator_system) validates the plan + reverifies clean-worktree provenance
before calling this composer. Output is a staging dir, never a live operator root —
so the result is hash/diff-testable and feeds a later upgrade step cleanly.

Stdlib-only, pip-install-free.
"""

from pathlib import Path
from typing import List, NamedTuple, Optional

from emission_plan import EmissionPlan  # type: ignore
from generator import (  # type: ignore
    GeneratorError, required_foundation_placeholders, warn_unused_inputs,
)
from corpus_loader import load_corpus_pack  # type: ignore
from scaffold_emitter import emit_scaffold, scaffold_template_placeholders  # type: ignore
from authority_profile import autonomous_actions_summary  # type: ignore
from voice_settings import voice_settings_inputs  # type: ignore
from agent_emitter import emit_agent_layer  # type: ignore
from foundation_doc_emitter import emit_foundation_docs  # type: ignore
from operator_fill_emitter import emit_operator_fill_templates  # type: ignore
from corpus_emitter import (  # type: ignore
    render_claude_md_block, emit_rules_library, emit_decisions, inject_target_hooks,
)
from upgrade_scaffold_emitter import emit_upgrade_scaffold, MANIFEST_REL  # type: ignore
from replay_capsule import emit_replay_capsule  # type: ignore
from acceptance_contract_emitter import emit_acceptance_contracts  # type: ignore


class OperatorSystemResult(NamedTuple):
    staging_dir: Path
    paths_written: List[Path]
    manifest_path: Path


def _verify_template_dependencies(plan: EmissionPlan, build_repo_root: Path) -> None:
    """Fail-fast (BEFORE any write) if a required template dependency is absent.

    Closes the silent-skip gap: scaffold_emitter._scaffold_sources skips a missing
    template subdir without error, which would drop control-plane files from the
    emitted tree while the manifest still reports drift-clean.

    For bundles WITH an operating layer (system-artifacts.json present), verify the
    bundle's required template directories exist (the bundle is the single template
    home). For foundation-only bundles (no system-artifacts.json), skip — those files
    are simply absent from the emitted tree."""
    from bundle_templates import bundle_has_operating_layer, _bundle_dir  # type: ignore
    if not bundle_has_operating_layer(plan.bundle_version, build_repo_root):
        return  # foundation-only bundle: no operating-layer dependencies to verify

    # For operating-layer bundles, verify required bundle template subdirs exist.
    from scaffold_emitter import SCAFFOLD_SUBDIRS, OPTIONAL_SCAFFOLD_SUBDIRS  # type: ignore
    from agent_emitter import (  # type: ignore
        _BUNDLE_ORCHESTRATOR_REL, _BUNDLE_SPECIALIST_REL, _BUNDLE_QA_REL,
        _BUNDLE_INVOCATION_REL, _BUNDLE_CRON_REL,
    )
    from scaffold_emitter import _BUNDLE_START_SESSION_REL  # type: ignore
    bundle_templates = _bundle_dir(plan.bundle_version, build_repo_root) / "templates"
    missing: List[str] = []
    for rel in (_BUNDLE_ORCHESTRATOR_REL, _BUNDLE_SPECIALIST_REL, _BUNDLE_QA_REL,
                _BUNDLE_INVOCATION_REL, _BUNDLE_CRON_REL, _BUNDLE_START_SESSION_REL):
        if not (bundle_templates / rel).is_file():
            missing.append(f"bundle/{plan.bundle_version}/templates/{rel}")
    for sub in SCAFFOLD_SUBDIRS:
        if sub in OPTIONAL_SCAFFOLD_SUBDIRS:
            continue  # optional dirs are legitimately absent from older bundles; skip
        if not (bundle_templates / sub).exists():
            missing.append(f"bundle/{plan.bundle_version}/templates/{sub}")
    if missing:
        raise GeneratorError(
            f"missing required bundle template dependencies (cannot emit a complete system): {missing}"
        )


def _verify_foundation_inputs_complete(plan: EmissionPlan, build_repo_root: Path) -> None:
    """Derivation-input fail-fast guard.

    Every placeholder the foundation templates require must be supplied NON-EMPTY by
    the plan's foundation_doc_inputs, validated BEFORE any file is written. This
    catches a MISSING input (which the renderer would otherwise raise on mid-emission,
    after a partial tree is written) AND a silently-EMPTY/whitespace-only input
    (which the renderer treats as a valid substitution — the silent-data-loss surface
    where a derived field returns empty and no error fires).

    This emission stage consumes RESOLVED foundation_doc_inputs (every template field
    is a direct placeholder), so completeness + non-emptiness IS the emission-layer
    derivation-input guard. The deeper non-placeholder derivation-input validation
    (fields that feed a derived value without being a direct placeholder) belongs to
    the upstream derivation stage, which is out of this stage's scope."""
    from generator import required_foundation_placeholders  # type: ignore
    required = required_foundation_placeholders(plan.bundle_version, build_repo_root)
    inputs = plan.foundation_doc_inputs
    missing = sorted(k for k in required if k not in inputs)
    empty = sorted(k for k in required if k in inputs and not str(inputs[k]).strip())
    if missing or empty:
        raise GeneratorError(
            f"derivation-input fail-fast: foundation_doc_inputs is incomplete — "
            f"missing={missing} empty={empty}"
        )


def _verify_foundation_bundle_dependencies(plan: EmissionPlan, build_repo_root: Path) -> None:
    """Prewrite guard: the source bundle's registry entry carries a non-empty
    source_commit AND every required foundation template exists — validated BEFORE
    any write. Previously source_commit was resolved only at manifest-build (the last
    step) and foundation-template existence only mid-render, so a false provenance or a
    missing template surfaced only after a partial tree had been written. This makes the
    'all preconditions before any write' contract literally true for those two surfaces."""
    from generator import _resolve_source_bundle, required_foundation_placeholders  # type: ignore
    entry = _resolve_source_bundle(plan.bundle_version, build_repo_root)
    if not entry.get("source_commit"):
        raise GeneratorError(
            f"registry entry for bundle {plan.bundle_version!r} has empty/missing source_commit "
            f"(false provenance); fix the registry before emitting"
        )
    required_foundation_placeholders(plan.bundle_version, build_repo_root)  # raises on a missing template


def generate_operator_system(plan: EmissionPlan, target_dir: Path, build_repo_root: Path,
                             generator_version_override: Optional[str] = None) -> OperatorSystemResult:
    """Guarded top-level orchestration entry: validate provenance + dependencies,
    then emit the complete operator system for `plan` into `target_dir` (staging).

    Preconditions, ALL checked before any file is written (fail-fast — a partial
    staging tree is worse than a clean refusal):

      1. NOT foundation_only_mode — the full-system path rejects foundation-only;
         foundation-only stays the legacy generator.generate_bundle path at v0.
      2. target_dir absent or empty — a non-empty staging dir would enroll stale
         files into the full-tree manifest.
      3. strict clean-worktree reverify + generator_version reconcile — the
         emission-time generator identity (computed from a CLEAN worktree unless
         overridden for tests) must equal plan.generator_version. A dirty worktree
         (false provenance) or a stale plan (identity skew) fails closed. Pinned-
         derivation-record contract: a plan may only be emitted by the exact clean
         generator that authored it; regenerate the plan after generator changes.
      4. source-bundle dependencies present + provenance non-empty (see
         _verify_foundation_bundle_dependencies — non-empty source_commit + every
         required foundation template exists).
      5. required template dependencies present (see _verify_template_dependencies).
      6. derivation-input fail-fast — every foundation-template placeholder is supplied
         non-empty by plan.foundation_doc_inputs (see _verify_foundation_inputs_complete);
         catches a missing OR silently-empty derived input before any write.

    `plan` MUST be a validated EmissionPlan (the only sanctioned constructors are
    emission_plan.validate_emission_plan / load_emission_plan, which enforce I1-I10);
    the dataclass type IS the validated-plan contract.

    `generator_version_override` (tests only) supplies the expected identity directly
    and skips the live clean-worktree computation; it does NOT relax the reconcile.
    The clean-worktree requirement is SEALED — there is no require_clean=False escape on
    this guarded entry (real emission always reverifies against a clean worktree); use
    the override seam for tests, never a dirty-worktree emission.
    """
    if plan.foundation_only_mode:
        raise GeneratorError(
            "generate_operator_system does not emit foundation-only plans; use "
            "generator.generate_bundle for the foundation-only path"
        )
    if target_dir.exists() and any(target_dir.iterdir()):
        raise GeneratorError(
            f"staging dir {target_dir} is not empty; emit into a fresh/absent directory"
        )

    if generator_version_override is not None:
        expected_gv = generator_version_override
    else:
        from generator_version import current_generator_version  # type: ignore
        # SEALED clean-worktree requirement — no require_clean=False escape on the
        # guarded entry (a dirty worktree would record false provenance).
        expected_gv = current_generator_version(build_repo_root, require_clean=True)
    if plan.generator_version != expected_gv:
        raise GeneratorError(
            f"plan.generator_version {plan.generator_version!r} != emission-time generator "
            f"identity {expected_gv!r}; the plan is stale — regenerate it from a clean worktree"
        )

    _verify_foundation_bundle_dependencies(plan, build_repo_root)
    _verify_template_dependencies(plan, build_repo_root)
    _verify_foundation_inputs_complete(plan, build_repo_root)

    written = emit_operator_system(plan, target_dir, build_repo_root)
    return OperatorSystemResult(
        staging_dir=target_dir,
        paths_written=written,
        manifest_path=target_dir / MANIFEST_REL,
    )


def _full_system_consumed_keys(plan: EmissionPlan, build_repo_root: Path) -> set:
    """The set of foundation_doc_inputs keys SOME emitter in the full-system emission
    consumes. Aggregated across every consumption surface so the unused-input warning
    means "consumed by NO emitter," not "absent from the foundation-doc templates."

    Three sources, unioned:
      1. foundation-doc template placeholders (the foundation_doc_emitter render),
      2. scaffold template placeholders (emit_scaffold merges fdi into its substitution
         map, so any fdi key matching a scaffold-template placeholder is consumed),
      3. an explicit DECLARED set of assembler-/direct-consumed keys — fdi keys that are
         legitimately consumed OUTSIDE template substitution and so would otherwise be
         falsely flagged. Each is sourced to its canonical consumer's constant where one
         exists (capability/dependency projections), with derivation-source fields and
         direct emitter reads named explicitly:
           - CAPABILITY_INCREMENTS  -> capability_projection.INCREMENTS_FIELD
             (the assembler derives BUILD_PROGRESS_ROWS + per-phase acceptance contracts
             from it; it is not itself a template placeholder),
           - EXTERNAL_DEPENDENCY_IDENTITY / EXTERNAL_DEPENDENCY_ANNOTATION
             -> dependency_projection.IDENTITY_FIELD / ANNOTATION_FIELD
             (consumed to project INPUT_TYPE_INVENTORY / SOURCE_REGISTRY_ROWS /
             CREDENTIAL_REGISTRY_ROWS, which ARE scaffold placeholders),
           - CORE_PURPOSE: a vision-group extraction source field (feeds the derivation
             of the VISION_* fields); recorded in fdi but rendered into no doc directly,
           - CORPUS_INSTALLED_DATE / AUTONOMY_LEVEL / PROJECT_NAME: read directly by an
             emitter/orchestrator (corpus_emitter install marker; the autonomy summary;
             plan.project_name) rather than substituted from a template body,
           - CAPABILITY_DESCRIPTOR_REGISTRY_ROWS (B1-2): capability_descriptor_registry.py's
             QA-view row body. Declared here (not left to source 2) because its template
             (wizard/templates/quality/capability_descriptor_registry.md) is canonical-only at
             B1 (D-B1-a — no bundle cut yet), so scaffold_template_placeholders() cannot see its
             {{CAPABILITY_DESCRIPTOR_REGISTRY_ROWS}} placeholder until the template is bundled
             at B2; this declaration prevents a false unused-input warning the moment an
             assembler starts populating the key, ahead of that bundle cut.

    Source 3 is intentionally a small, named declared set rather than threading a
    consumed-key return through every emitter — see the slice's mechanism note. A
    genuinely-unconsumed key (a typo / stale input) is in none of the three and STILL warns."""
    from capability_projection import INCREMENTS_FIELD  # type: ignore
    from dependency_projection import IDENTITY_FIELD, ANNOTATION_FIELD  # type: ignore
    from corpus_emitter import INSTALLED_DATE_KEY  # type: ignore
    from capability_descriptor_registry import MARKDOWN_FIELD as DESCRIPTOR_REGISTRY_ROWS_FIELD  # type: ignore

    consumed: set = set()
    consumed |= required_foundation_placeholders(plan.bundle_version, build_repo_root)
    consumed |= scaffold_template_placeholders(build_repo_root)
    consumed |= {
        INCREMENTS_FIELD,            # CAPABILITY_INCREMENTS (assembler derivation source)
        IDENTITY_FIELD,              # EXTERNAL_DEPENDENCY_IDENTITY (dependency projection input)
        ANNOTATION_FIELD,            # EXTERNAL_DEPENDENCY_ANNOTATION (dependency projection input)
        INSTALLED_DATE_KEY,          # CORPUS_INSTALLED_DATE (corpus_emitter direct read)
        "CORE_PURPOSE",              # vision-group extraction source (renders into no doc directly)
        "AUTONOMY_LEVEL",            # orchestrator direct read (autonomy summary) + scaffold placeholder
        "PROJECT_NAME",              # plan.project_name + scaffold/agent structural field
        DESCRIPTOR_REGISTRY_ROWS_FIELD,  # CAPABILITY_DESCRIPTOR_REGISTRY_ROWS (B1-2; see above)
    }
    return consumed


def emit_operator_system(plan: EmissionPlan, staging_dir: Path,
                         build_repo_root: Path) -> List[Path]:
    """Emit the complete runnable operator system for `plan` into `staging_dir`.
    Returns every path written (hook injection mutates existing paths in place).

    This is the composer; the GUARDED entry point is generate_operator_system,
    which validates provenance + dependencies before calling this."""
    records = load_corpus_pack()
    written: List[Path] = []

    # 1-2. base scaffold, with the rendered inherited-principles block fed into
    # CLAUDE.md's {{INHERITED_OPERATING_PRINCIPLES}} placeholder, and the autonomy "may do
    # without asking" body DERIVED from the plan's AUTONOMY_LEVEL (so project_instructions.md's
    # autonomy section agrees with the derived level instead of shipping a hardcoded default).
    block = render_claude_md_block(plan, records)
    autonomy_level = plan.foundation_doc_inputs.get("AUTONOMY_LEVEL", "1")
    # PROJECT_PURPOSE (CLAUDE.md + session_bootstrap "Purpose") is FILLED from the vision's
    # concise CORE_PURPOSE when captured, so a freshly emitted system states what it is for
    # instead of shipping the operator-fill placeholder (which made a fresh operator session
    # report its own identity as unconfigured). Absent/empty CORE_PURPOSE keeps the
    # scaffold's placeholder default.
    scaffold_extra = {
        "INHERITED_OPERATING_PRINCIPLES": block,
        "AUTONOMOUS_ACTIONS": autonomous_actions_summary(autonomy_level),
        **voice_settings_inputs(plan.foundation_doc_inputs),
    }
    core_purpose = str(plan.foundation_doc_inputs.get("CORE_PURPOSE", "")).strip()
    if core_purpose:
        scaffold_extra["PROJECT_PURPOSE"] = core_purpose
    written += emit_scaffold(plan, staging_dir, build_repo_root, extra_inputs=scaffold_extra)

    # 3. agent execution layer.
    written += emit_agent_layer(plan, staging_dir, build_repo_root)

    # 4. corpus single home + decisions core (authority folds into the manifest at step 6).
    written += emit_rules_library(plan, staging_dir, build_repo_root, records=records)
    written += emit_decisions(plan, staging_dir, build_repo_root)

    # 5. per-target hooks (idempotent) into the now-emitted scaffold + agent files.
    inject_target_hooks(plan, staging_dir, records=records)

    # 6. foundation docs at the operator-project ROOT (vision/approach/.../prd).
    #    Emitted before the upgrade scaffold so the manifest's full-tree walk
    #    enrolls them (full-tree ownership). Hooks do not target foundation docs,
    #    so this may run after hook injection without interaction.
    written += emit_foundation_docs(plan, staging_dir, build_repo_root)

    # 6b. operator-fill build-session helpers (review prompts + skill templates, copied
    #     verbatim with their operator-fill {{}} intact) + an empty .env — parity with the
    #     legacy close-assembly. Before the upgrade scaffold so the full-tree manifest enrolls them.
    written += emit_operator_fill_templates(plan, staging_dir, build_repo_root)

    # 6c. per-phase acceptance contracts — one markdown file per committed phase, written
    #     into agents/acceptance/. Paths are registered in emitted_files by the assembler;
    #     content is pre-rendered ONCE by the assembler and carried on plan.acceptance_contracts
    #     (single source) — the emitter writes it verbatim, it is NOT re-derived here.
    written += emit_acceptance_contracts(plan, staging_dir)

    # 6d. replay capsule — persist the operator's foundation-doc inputs + provenance
    #     so a future upgrade can deterministically re-render the foundation docs.
    #     Fail-closed secret scan runs before the write; the capsule is a control file
    #     (inventoried by the manifest, excluded from the hashed managed set) so it must
    #     exist BEFORE the upgrade scaffold (which writes the manifest LAST).
    written.append(emit_replay_capsule(plan, staging_dir, build_repo_root))

    # 7. upgrade scaffold LAST — manifest-v2 (folds corpus authority + hashes the
    #    final tree, foundation docs included) + upgrade policy/history + command surface.
    written += emit_upgrade_scaffold(plan, staging_dir, build_repo_root, records=records)

    # Accurate unused-input warning — fires ONCE, at full-system emit, where the full
    # consumed-key set across ALL emitters is knowable. (The foundation-doc renderer no
    # longer warns; on its own it sees only the foundation-doc templates and would falsely
    # flag the many fdi keys consumed by the scaffold / projections / direct reads.) A
    # genuinely-unconsumed key still warns; a consumed one never does.
    warn_unused_inputs(
        dict(plan.foundation_doc_inputs),
        _full_system_consumed_keys(plan, build_repo_root),
    )

    return written
