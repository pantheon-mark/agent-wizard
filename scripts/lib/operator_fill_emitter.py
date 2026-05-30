"""Operator-fill template emitter (stdlib-only).

Copies the build-session helper templates — the review prompts and the skill
templates — verbatim into the operator project, and writes an empty `.env`
placeholder. The legacy close-assembly copied all of these; the unified generator
emits them here so the operator project ships complete (parity).

These are STATIC OPERATOR-FILL templates: emitted byte-for-byte, intentionally
retaining their `{{KEY}}` placeholders for the operator to complete during
agent-build / review sessions. Their placeholder vocabulary is DISJOINT from the
generation-time foundation/scaffold keys, so:
  - they are NOT substituted here (a verbatim copy);
  - the key-set-aware placeholder check already ignores them (it only flags KNOWN
    generation-time keys leaking into output);
  - the ONLY gate that must exempt them is a blanket "no `{{` in the emitted tree"
    assertion — callers exempt the OPERATOR_FILL_DIRS paths.

`.env` is the operator's secrets file: emitted empty (the credential/setup step
fills it). It carries no placeholders.

Stdlib-only, pip-install-free.
"""

from pathlib import Path
from typing import List

from emission_plan import EmissionPlan  # type: ignore

# (build-repo source dir, operator-project dest dir) — copied VERBATIM (no substitution).
OPERATOR_FILL_SOURCES = (
    ("wizard/review_prompts", "wizard/review_prompts"),
    ("wizard/skills", "wizard/skills"),
)

# Operator-project dirs that hold operator-fill templates (intentional `{{}}`). A
# blanket no-unresolved-placeholder check must exempt paths under these.
OPERATOR_FILL_DIRS = ("wizard/review_prompts", "wizard/skills")

ENV_RELPATH = ".env"


def is_operator_fill_path(relpath: str) -> bool:
    """True when relpath is an operator-fill template (intentional placeholders);
    such files are exempt from the blanket no-unresolved-placeholder parity check."""
    rp = relpath.replace("\\", "/")
    return any(rp == d or rp.startswith(d + "/") for d in OPERATOR_FILL_DIRS)


def emit_operator_fill_templates(plan: EmissionPlan, staging_dir: Path,
                                 build_repo_root: Path) -> List[Path]:
    """Copy the operator-fill helper templates verbatim + write an empty .env.
    Returns the paths written."""
    written: List[Path] = []
    for src_rel, dest_rel in OPERATOR_FILL_SOURCES:
        src_dir = build_repo_root / src_rel
        if not src_dir.exists():
            continue
        dest_dir = staging_dir / dest_rel
        dest_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(src_dir.iterdir()):
            if f.is_file() and f.suffix == ".md":
                dest = dest_dir / f.name
                # VERBATIM — no _substitute_placeholders; the {{KEY}} are operator-fill.
                dest.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                written.append(dest)
    env = staging_dir / ENV_RELPATH
    env.write_text("", encoding="utf-8")
    written.append(env)
    return written
