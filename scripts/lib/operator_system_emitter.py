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
from generator import GeneratorError  # type: ignore
from corpus_loader import load_corpus_pack  # type: ignore
from scaffold_emitter import emit_scaffold  # type: ignore
from agent_emitter import emit_agent_layer  # type: ignore
from foundation_doc_emitter import emit_foundation_docs  # type: ignore
from corpus_emitter import (  # type: ignore
    render_claude_md_block, emit_rules_library, emit_decisions, inject_target_hooks,
)
from upgrade_scaffold_emitter import emit_upgrade_scaffold, MANIFEST_REL  # type: ignore


class OperatorSystemResult(NamedTuple):
    staging_dir: Path
    paths_written: List[Path]
    manifest_path: Path


def _verify_template_dependencies(plan: EmissionPlan, build_repo_root: Path) -> None:
    """Fail-fast (BEFORE any write) if a required template dependency is absent.

    Closes the silent-skip gap: scaffold_emitter._scaffold_sources skips a missing
    template subdir without error, which would drop control-plane files from the
    emitted tree while the manifest still reports drift-clean. The agent + foundation
    templates fail loudly on read, but we check them up front too so the failure
    surfaces before a partial tree is written."""
    from agent_emitter import (  # type: ignore
        ORCHESTRATOR_TEMPLATE, SPECIALIST_TEMPLATE, QA_TEMPLATE,
        INVOCATION_TEMPLATE, CRON_TEMPLATE,
    )
    from scaffold_emitter import (  # type: ignore
        TEMPLATES_REL, START_SESSION_TEMPLATE, SCAFFOLD_SUBDIRS,
    )
    missing: List[str] = []
    for rel in (ORCHESTRATOR_TEMPLATE, SPECIALIST_TEMPLATE, QA_TEMPLATE,
                INVOCATION_TEMPLATE, CRON_TEMPLATE, START_SESSION_TEMPLATE):
        if not (build_repo_root / rel).exists():
            missing.append(rel)
    for sub in SCAFFOLD_SUBDIRS:
        if not (build_repo_root / TEMPLATES_REL / sub).exists():
            missing.append(f"{TEMPLATES_REL}/{sub}")
    if missing:
        raise GeneratorError(
            f"missing required template dependencies (cannot emit a complete system): {missing}"
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


def emit_operator_system(plan: EmissionPlan, staging_dir: Path,
                         build_repo_root: Path) -> List[Path]:
    """Emit the complete runnable operator system for `plan` into `staging_dir`.
    Returns every path written (hook injection mutates existing paths in place).

    This is the composer; the GUARDED entry point is generate_operator_system,
    which validates provenance + dependencies before calling this."""
    records = load_corpus_pack()
    written: List[Path] = []

    # 1-2. base scaffold, with the rendered inherited-principles block fed into
    # CLAUDE.md's {{INHERITED_OPERATING_PRINCIPLES}} placeholder.
    block = render_claude_md_block(plan, records)
    written += emit_scaffold(plan, staging_dir, build_repo_root,
                             extra_inputs={"INHERITED_OPERATING_PRINCIPLES": block})

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

    # 7. upgrade scaffold LAST — manifest-v2 (folds corpus authority + hashes the
    #    final tree, foundation docs included) + upgrade policy/history + command surface.
    written += emit_upgrade_scaffold(plan, staging_dir, build_repo_root, records=records)

    return written
