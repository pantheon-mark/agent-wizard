"""Operator-system orchestrator — composes the full runnable operator system.

A thin orchestration layer over the typed emitters: it emits the base scaffold,
the agent-execution layer, and the inherited-corpus artifacts into a single
STAGING directory, in the order their dependencies require:

  1. render the inherited-principles block for CLAUDE.md;
  2. emit the base scaffold (root + operational dirs), feeding it that block;
  3. emit the /agents/ execution layer (reuse the agent-layer emitter);
  4. emit the corpus single home (rules_library), the decisions/ ADR core, and
     the authority sidecar;
  5. inject per-target operational hooks into the now-emitted files (idempotent).

Steps 3-5 depend on step 2's files existing (hooks attach to scaffold + agent
files), which is why the corpus hook pass runs last. The corpus pack is loaded
once and shared across the corpus emitters for consistency.

The foundation-doc set (vision/approach/... + operator manifest) is produced by
the foundation-doc generator and wired in separately; it is not part of this
orchestration. Output is a staging dir, never a live operator root — so the
result is hash/diff-testable and feeds a later upgrade step cleanly.

Stdlib-only, pip-install-free.
"""

from pathlib import Path
from typing import List

from emission_plan import EmissionPlan  # type: ignore
from corpus_loader import load_corpus_pack  # type: ignore
from scaffold_emitter import emit_scaffold  # type: ignore
from agent_emitter import emit_agent_layer  # type: ignore
from corpus_emitter import (  # type: ignore
    render_claude_md_block, emit_rules_library, emit_decisions,
    emit_corpus_authority, inject_target_hooks,
)


def emit_operator_system(plan: EmissionPlan, staging_dir: Path,
                         build_repo_root: Path) -> List[Path]:
    """Emit the complete runnable operator system for `plan` into `staging_dir`.
    Returns every path written (hook injection mutates existing paths in place)."""
    records = load_corpus_pack()
    written: List[Path] = []

    # 1-2. base scaffold, with the rendered inherited-principles block fed into
    # CLAUDE.md's {{INHERITED_OPERATING_PRINCIPLES}} placeholder.
    block = render_claude_md_block(plan, records)
    written += emit_scaffold(plan, staging_dir, build_repo_root,
                             extra_inputs={"INHERITED_OPERATING_PRINCIPLES": block})

    # 3. agent execution layer.
    written += emit_agent_layer(plan, staging_dir, build_repo_root)

    # 4. corpus single home + decisions core + authority sidecar.
    written += emit_rules_library(plan, staging_dir, build_repo_root, records=records)
    written += emit_decisions(plan, staging_dir, build_repo_root)
    written += emit_corpus_authority(plan, staging_dir, records=records)

    # 5. per-target hooks (idempotent) into the now-emitted scaffold + agent files.
    inject_target_hooks(plan, staging_dir, records=records)

    return written
