"""Foundation-doc emitter — writes the foundation docs at the operator-project
ROOT from a validated EmissionPlan into a STAGING dir.

Delegates rendering to generator.render_foundation_docs — the single canonical
foundation-doc render authority, shared with the legacy generate_bundle path — and
writes each artifact at its operator_relpath (root-level: "vision.md", NOT
"foundation/vision.md"). Root placement is operator-correct: the agent layer
references foundation docs as `$PROJECT_ROOT/<doc>` (e.g. additional_context_files
= ["approach.md"]), and the wizard's documented operator layout puts foundation
docs at root. The `foundation/` subdir is a legacy generate_bundle layout only.

This emitter only PLACES the files; the v2 full-tree manifest enrolls them via its
post-render tree walk (upgrade_scaffold_emitter), classifying each by its
foundation_* lifecycle. The plan's foundation_doc_inputs is the complete content
map (one value per template placeholder) — passed through verbatim, no Python-side
adaptation (per the typed-plan / conditional-templating discipline).

Stdlib-only, pip-install-free.
"""

from pathlib import Path
from typing import List

from emission_plan import EmissionPlan  # type: ignore
from generator import render_foundation_docs  # type: ignore


def emit_foundation_docs(plan: EmissionPlan, staging_dir: Path,
                         build_repo_root: Path) -> List[Path]:
    """Render + write the foundation docs at the operator-project root in
    `staging_dir`. Returns the paths written, in contract order. Fail-fast (via
    the renderer) on any template placeholder the plan's foundation_doc_inputs
    does not supply."""
    records = render_foundation_docs(
        plan.bundle_version, dict(plan.foundation_doc_inputs), build_repo_root
    )
    written: List[Path] = []
    for rec in records:
        out_path = staging_dir / rec.operator_relpath
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rec.content, encoding="utf-8")
        written.append(out_path)
    return written
