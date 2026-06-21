"""Inherited-corpus emitter — renders the distributed corpus pack into the
operator-project scaffold (the "renderers" layer).

Consumes the validated corpus records (from corpus_loader) and emits:
  - quality/rules_library.md   — the SINGLE HOME for the operating-principle
    corpus: every corpus-body cell becomes a structured Rule entry (Rule ID = the
    cell's neutral OP-NN identifier; Source = the cell's neutral public label).
  - decisions/decision_record_template.md + decisions/_index.md — the ADR core.
  - per-target operational HOOKS injected into already-emitted scaffold files
    (agent prompts / validation_gate_config / audit_log / CLAUDE.md): short
    enforcement / cross-reference text in marked, idempotent regions — NOT body
    copies (single-home + cross-reference discipline).
  - .wizard/corpus_authority.json — a versioned authority sidecar recording the
    provisional authority stamp for every gated cell. Authority provenance lives
    in this sidecar, never in operator-file frontmatter.

Single-home discipline: a principle's canonical text lives in exactly one place
(rules_library); every other target gets a cross-reference or a short operational
hook that points back to it. This avoids the cross-doc redundancy that the
foundation-bundle templates were refactored to eliminate.

Stdlib-only, pip-install-free. Reuses generator._substitute_placeholders.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from emission_plan import EmissionPlan  # type: ignore
from generator import _substitute_placeholders  # type: ignore
from corpus_loader import CorpusCellRecord, load_corpus_pack, resolve_for_shape  # type: ignore
from bundle_templates import read_bundle_template  # type: ignore


RULES_LIBRARY_TEMPLATE = "wizard/templates/quality/rules_library.md"
RULES_LIBRARY_DEST = "quality/rules_library.md"

# Operating-layer corpus templates are sourced from the frozen system bundle (single
# home) by their operator-project relpath, via the managed-artifacts contract.
RULES_LIBRARY_RELPATH = "quality/rules_library.md"

# decisions/ ADR core (the OP-01 scaffold-template cell). Static operator-facing
# templates with <...> operator-fill markers (no {{KEY}} substitution). Keyed by
# operator-project relpath (the bundle-source path comes from the contract).
DECISIONS_RELPATHS = (
    "decisions/decision_record_template.md",
    "decisions/_index.md",
)

# Deterministic install marker (no clock; replay-safe). Operator-overridable via
# the plan's free-form foundation_doc_inputs map.
DEFAULT_INSTALLED_MARKER = "(installed at operator setup)"
INSTALLED_DATE_KEY = "CORPUS_INSTALLED_DATE"
DEFAULT_APPLIES_TO = "All agents and the orchestrator"

# The principles worth inlining at the top of CLAUDE.md (load-bearing at session
# start), in addition to the general pointer at rules_library: claim-level
# epistemic discipline, lists-are-examples, context-integrity.
SESSION_START_POSTURE_IDS = ("OP-08", "OP-24", "OP-25")

# Idempotent injected-region markers for hook targets that are not CLAUDE.md
# (CLAUDE.md is handled by the rendered {{INHERITED_OPERATING_PRINCIPLES}} block).
HOOK_BEGIN = "<!-- BEGIN inherited-operating-principles (wizard-managed) -->"
HOOK_END = "<!-- END inherited-operating-principles -->"
_HOOK_RE = re.compile(re.escape(HOOK_BEGIN) + ".*?" + re.escape(HOOK_END), re.DOTALL)

AGENT_PROMPTS_DIR = "agents/prompts"

# Authority sidecar (M3): a versioned subdocument carrying the provisional
# authority stamp for every gated cell. Authority provenance lives here, NEVER in
# operator-file frontmatter. Designed to be folded into the upgrade-scaffold
# manifest when that lands (the _absorption_note records the intent).
CORPUS_AUTHORITY_DEST = ".wizard/corpus_authority.json"
CORPUS_AUTHORITY_SCHEMA = "corpus-authority"
CORPUS_AUTHORITY_VERSION = "corpus-authority-v0"
CORPUS_AUTHORITY_ABSORPTION_NOTE = (
    "Versioned authority sidecar. When the operator-upgrade scaffold lands, fold "
    "these per-cell authority stamps into .wizard/manifest.json and retire this file.")


def _resolved_records(plan: EmissionPlan, records: Optional[List[CorpusCellRecord]]) -> List[CorpusCellRecord]:
    recs = records if records is not None else load_corpus_pack()
    return resolve_for_shape(recs, plan.system_shape)


def _conditions_for(cell: CorpusCellRecord) -> str:
    if cell.applicability_gate:
        return f"Applies only when: {cell.applicability_gate}."
    return "Applies at all times."


def _render_rule_block(cell: CorpusCellRecord, created: str) -> str:
    """Render one corpus-body cell as a structured Rule entry."""
    c = cell.canonical
    assert c is not None  # guaranteed for realization == corpus-body (loader C4)
    lines = [
        f"### {cell.cell_id} — {c.category}",
        "",
        c.body,
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Rule ID | {cell.cell_id} |",
        f"| Category | {c.category} |",
        f"| Conditions | {_conditions_for(cell)} |",
        f"| Source | {cell.public_source_label} |",
        f"| Created | {created} |",
        f"| Applies to | {DEFAULT_APPLIES_TO} |",
        "| Status | Active |",
    ]
    return "\n".join(lines)


def render_rules_library_entries(cells: List[CorpusCellRecord], created: str) -> str:
    """Render all corpus-body cells (sorted by cell_id) into the rules_library body."""
    body_cells = sorted(
        (c for c in cells if c.realization == "corpus-body" and c.canonical is not None),
        key=lambda c: c.cell_id,
    )
    return "\n\n".join(_render_rule_block(c, created) for c in body_cells)


def emit_rules_library(plan: EmissionPlan, staging_dir: Path, build_repo_root: Path,
                       records: Optional[List[CorpusCellRecord]] = None) -> List[Path]:
    """Emit quality/rules_library.md (the corpus single home) into staging.

    When the emitted bundle_version carries no operating-layer templates (no
    system-artifacts.json), rules_library.md is absent (foundation-only fallback)."""
    from bundle_templates import bundle_has_operating_layer  # type: ignore
    if not bundle_has_operating_layer(plan.bundle_version, build_repo_root):
        return []  # foundation-only bundle: rules_library absent

    resolved = _resolved_records(plan, records)
    created = str((plan.foundation_doc_inputs or {}).get(INSTALLED_DATE_KEY, DEFAULT_INSTALLED_MARKER))
    entries = render_rules_library_entries(resolved, created)

    version = plan.bundle_version
    template = read_bundle_template(version, RULES_LIBRARY_RELPATH, build_repo_root)
    result, _seen = _substitute_placeholders(
        template, {"RULES_LIBRARY_ENTRIES": entries}, template_name="rules_library.md")

    dest = staging_dir / RULES_LIBRARY_DEST
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result, encoding="utf-8")
    return [dest]


def _first_sentence(text: str) -> str:
    head = text.split(". ", 1)[0].rstrip(".")
    return head + "."


def render_claude_md_block(plan: EmissionPlan,
                           records: Optional[List[CorpusCellRecord]] = None) -> str:
    """Render the value for CLAUDE.md's {{INHERITED_OPERATING_PRINCIPLES}} section.

    Single-home: a general pointer to rules_library (covers every principle,
    including those whose cells carry a cross_ref hook to CLAUDE.md) PLUS a short
    inline list of the few principles that are load-bearing at session start."""
    resolved = _resolved_records(plan, records)
    by_id = {r.cell_id: r for r in resolved}
    lines = [
        "The inherited operating principles in `quality/rules_library.md` "
        "(rules `OP-…`) govern how this system works. Read them before acting.",
        "",
        "**Load-bearing at session start:**",
    ]
    for op in SESSION_START_POSTURE_IDS:
        r = by_id.get(op)
        if r is None or r.canonical is None:
            continue
        lines.append(f"- **{r.canonical.category}** (`{op}`): "
                     f"{_first_sentence(r.canonical.body)} See `quality/rules_library.md`.")
    return "\n".join(lines)


def _collect_hooks(resolved: List[CorpusCellRecord]) -> List[Tuple[str, str, str]]:
    """Flatten target hooks across corpus-body cells into (cell_id, target, text),
    sorted by cell_id for deterministic ordering. CLAUDE.md targets are dropped —
    they are handled by the rendered block, not by post-pass injection."""
    out: List[Tuple[str, str, str]] = []
    for r in sorted(resolved, key=lambda c: c.cell_id):
        for h in r.target_hooks:
            base = h.target.split()[0]  # strip descriptive suffixes / parentheticals
            if base == "CLAUDE.md":
                continue
            out.append((r.cell_id, base, h.text))
    return out


def _resolve_hook_target_paths(base: str, staging_dir: Path) -> List[Path]:
    """Map a normalized hook target to concrete staged file path(s). Agent-prompt
    targets resolve under agents/prompts/ (glob '*' fans out to all prompts)."""
    if base.startswith("agents/") and base.endswith("_prompt.md"):
        name = base[len("agents/"):]
        prompts = staging_dir / AGENT_PROMPTS_DIR
        if "*" in name:
            return sorted(prompts.glob(name))
        return [prompts / name]
    return [staging_dir / base]


def _inject_region(text: str, body: str) -> str:
    """Insert or replace the wizard-managed hook region (idempotent)."""
    region = f"{HOOK_BEGIN}\n{body}\n{HOOK_END}"
    if _HOOK_RE.search(text):
        return _HOOK_RE.sub(lambda _m: region, text)
    prefix = text if text.endswith("\n") else text + "\n"
    return f"{prefix}\n{region}\n"


def inject_target_hooks(plan: EmissionPlan, staging_dir: Path,
                        records: Optional[List[CorpusCellRecord]] = None) -> List[Path]:
    """Inject per-target operational hooks into already-emitted staged files.

    Single-home + cross-reference: each hook is a short pointer/enforcement line
    placed in a marked, idempotent region — never a copy of the principle body.
    Targets that do not exist in staging are skipped (the orchestrator emits the
    scaffold + agent layer before calling this). Returns the modified paths."""
    resolved = _resolved_records(plan, records)
    # path -> ordered, de-duplicated list of hook texts
    per_file: Dict[Path, List[str]] = {}
    for _cid, base, text in _collect_hooks(resolved):
        for path in _resolve_hook_target_paths(base, staging_dir):
            bucket = per_file.setdefault(path, [])
            if text not in bucket:
                bucket.append(text)

    modified: List[Path] = []
    for path in sorted(per_file, key=lambda p: str(p)):
        if not path.exists():
            continue  # orchestrator guarantees emission order; skip if absent
        body = ("**Inherited operating principles** — canonical text in "
                "`quality/rules_library.md`:\n"
                + "\n".join(f"- {t}" for t in per_file[path]))
        path.write_text(_inject_region(path.read_text(encoding="utf-8"), body), encoding="utf-8")
        modified.append(path)
    return modified


def build_corpus_authority_doc(plan: EmissionPlan,
                               records: Optional[List[CorpusCellRecord]] = None) -> dict:
    """Build the canonical authority doc (the provisional authority stamp for every
    gated cell across ALL realization classes) as an embeddable dict.

    This is the FOLD-IN SOURCE consumed by the upgrade-scaffold manifest emitter,
    which embeds it under .wizard/manifest.json's `corpus_authority` block. It
    deliberately omits the standalone-sidecar-only fields (`schema` /
    `_absorption_note`): once embedded in the manifest, an absorption note pointing
    at the manifest is stale. `emit_corpus_authority` re-adds those for the legacy
    standalone-sidecar form."""
    resolved = _resolved_records(plan, records)
    ap = plan.authority_profile
    cells = [
        {
            "cell_id": r.cell_id,
            "realization": r.realization,
            "authority_gate": r.authority_gate,
            "authority_basis": r.authority_basis_default,
            "authority_source": r.authority_source_default,
            "expires_on_trigger": ap.expires_on_trigger,
        }
        for r in sorted(resolved, key=lambda c: c.cell_id)
        if r.authority_gate != "applies-all"
    ]
    return {
        "version": CORPUS_AUTHORITY_VERSION,
        "authority_profile": {
            "id": ap.id, "posture": ap.posture, "source": ap.source,
            "expires_on_trigger": ap.expires_on_trigger,
        },
        "cells": cells,
    }


def emit_corpus_authority(plan: EmissionPlan, staging_dir: Path,
                          records: Optional[List[CorpusCellRecord]] = None) -> List[Path]:
    """Emit .wizard/corpus_authority.json — the standalone authority sidecar.

    Standalone form: wraps build_corpus_authority_doc() with the sidecar-only
    `schema` + `_absorption_note` fields. NOTE: the composed operator system folds
    this content into .wizard/manifest.json instead (see upgrade_scaffold_emitter);
    the orchestrator no longer emits this separate sidecar. Retained as a standalone
    capability + for the migration trigger semantics: under the provisional authority
    profile the stamp is machine-visible and carries the expires_on_trigger; when the
    real operator authority profile arrives, gated cells re-emit."""
    doc = {
        "schema": CORPUS_AUTHORITY_SCHEMA,
        "_absorption_note": CORPUS_AUTHORITY_ABSORPTION_NOTE,
        **build_corpus_authority_doc(plan, records),
    }
    dest = staging_dir / CORPUS_AUTHORITY_DEST
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return [dest]


def emit_decisions(plan: EmissionPlan, staging_dir: Path, build_repo_root: Path) -> List[Path]:
    """Emit the decisions/ ADR core (record template + index) into staging.

    The templates are static and operator-fill (<...> markers, not {{KEY}}); they
    are copied verbatim. _substitute_placeholders runs with no inputs purely as a
    fail-fast guard against an accidental {{KEY}} ever being introduced.

    When the emitted bundle_version carries no operating-layer templates (no
    system-artifacts.json), the decisions/ tree is absent (foundation-only fallback)."""
    from bundle_templates import bundle_has_operating_layer  # type: ignore
    if not bundle_has_operating_layer(plan.bundle_version, build_repo_root):
        return []  # foundation-only bundle: decisions/ absent

    version = plan.bundle_version
    written: List[Path] = []
    for dest_rel in DECISIONS_RELPATHS:
        content = read_bundle_template(version, dest_rel, build_repo_root)
        result, _seen = _substitute_placeholders(content, {}, template_name=Path(dest_rel).name)
        dest = staging_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(result, encoding="utf-8")
        written.append(dest)
    return written
