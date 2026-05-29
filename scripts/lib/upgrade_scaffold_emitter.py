"""Upgrade-scaffold emitter — emits the operator-project `.wizard/` upgrade
scaffold into a STAGING directory, computed AFTER the rest of the operator system
has been rendered.

What it emits (the SCAFFOLD only — the real three-way merge-apply mutator is a
later slice, NOT here):

  - .wizard/manifest.json     — the operator-project manifest (manifest-v2:
    full-tree ownership). Records foundation_bundle_version / source_commit /
    generator_version + per-file managed/base_hash/current_hash_last_seen/
    local_modifications/merge_strategy over the WHOLE emitted tree (not just the
    foundation docs). Folds the corpus authority stamps in under `corpus_authority`
    (the standalone sidecar is retired). Inventories the control files under
    `control_files`.
  - .wizard/upgrade-policy.yaml  — operator's standing-approval config (conservative
    v0 defaults: pinned-by-default; standing approval disabled).
  - .wizard/upgrade-history.log  — append-only upgrade history (seeded empty).
  - .wizard/UPGRADING.md         — operator-facing command surface (plan-only at v0).

Per-file MERGE POLICY is assigned by a small lifecycle taxonomy, classified
FAIL-CLOSED: every staged file is mapped to a lifecycle (by exact-path override,
else directory prefix); any staged file that matches no rule RAISES rather than
silently defaulting. At v0 every merge_strategy is NON-DESTRUCTIVE (the apply path
is a later slice), so the lifecycle assignment only affects drift-report wording,
not behaviour. Plan-declared per-file policy + emitter-sourced lifecycle records
are a later-slice refinement; the classifier is the v0 coverage authority.

Hashes are sha256:-prefixed via the shared upgrade.sha256_file canonicalization,
so a freshly-emitted manifest reads back drift-clean through compute_drift_report.

Determinism: sorted POSIX relpaths; json.dumps(sort_keys=True, indent=2)+"\n"; no
clock / no randomness; the manifest is written + hashed LAST (after every other
file exists), and excludes itself + the control files from the hashed set.

Stdlib-only, pip-install-free.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from emission_plan import EmissionPlan  # type: ignore
from corpus_loader import CorpusCellRecord, load_corpus_pack  # type: ignore
from corpus_emitter import build_corpus_authority_doc  # type: ignore
from upgrade import sha256_file  # type: ignore


class UpgradeScaffoldError(Exception):
    """Raised when the upgrade scaffold cannot be emitted (e.g. an unclassifiable
    staged file, or a bundle version absent from the registry). Fail-closed."""


MANIFEST_SCHEMA_VERSION = "manifest-v2"

MANIFEST_REL = ".wizard/manifest.json"
UPGRADE_POLICY_REL = ".wizard/upgrade-policy.yaml"
UPGRADE_HISTORY_REL = ".wizard/upgrade-history.log"
COMMAND_SURFACE_REL = ".wizard/UPGRADING.md"

# Files present on disk but NOT merge-managed content (the control plane). They are
# inventoried under the manifest's `control_files` block but excluded from
# `managed_files` (and from the hashed set — manifest.json self-exclusion avoids a
# circular self-hash; policy/history are operator/runtime state).
CONTROL_FILES = (MANIFEST_REL, UPGRADE_POLICY_REL, UPGRADE_HISTORY_REL)
_CONTROL_SET = set(CONTROL_FILES)

# Lifecycle taxonomy -> non-destructive v0 merge policy.
LIFECYCLE_POLICY = {
    "inherited_content": {  # wizard-authored best-practice content; operator should not freely edit
        "managed_by": "wizard", "local_modifications": "not_recommended", "merge_strategy": "warn_on_drift",
    },
    "runtime_state": {  # rewritten by the system/operator at runtime; drift is expected
        "managed_by": "operator", "local_modifications": "expected", "merge_strategy": "operator_review",
    },
    "operator_config": {  # operator-owned configuration seeded once
        "managed_by": "operator", "local_modifications": "expected", "merge_strategy": "operator_review",
    },
}

# Exact-path lifecycle overrides (relative to the operator-project root).
_EXACT_LIFECYCLE = {
    "CLAUDE.md": "inherited_content",
    "project_instructions.md": "inherited_content",
    "manual.md": "inherited_content",
    "start-session.sh": "inherited_content",
    "session_bootstrap.md": "runtime_state",
    "pending_decisions.md": "runtime_state",
    "wizard_feedback.md": "runtime_state",
    "SESSION_STATE.md": "runtime_state",
    ".gitignore": "operator_config",
    COMMAND_SURFACE_REL: "inherited_content",
}

# Directory-prefix lifecycle rules (mirror the template tree's own semantics).
_DIR_LIFECYCLE = {
    "logs/": "runtime_state",
    "work/": "runtime_state",
    "archive/": "runtime_state",
    "agents/": "inherited_content",
    "decisions/": "inherited_content",
    "docs/": "inherited_content",
    "quality/": "inherited_content",
    "security/": "operator_config",
}


def classify_lifecycle(rel_path: str) -> str:
    """Map an operator-root-relative path to a lifecycle. FAIL-CLOSED: a path that
    matches no exact override and no directory prefix raises UpgradeScaffoldError
    rather than silently defaulting (so a new emitted file can never slip in
    untracked)."""
    if rel_path in _EXACT_LIFECYCLE:
        return _EXACT_LIFECYCLE[rel_path]
    for prefix, lifecycle in _DIR_LIFECYCLE.items():
        if rel_path.startswith(prefix):
            return lifecycle
    raise UpgradeScaffoldError(
        f"unclassified staged file {rel_path!r}: no lifecycle rule matches. Add an "
        f"exact override or directory rule in upgrade_scaffold_emitter before emitting."
    )


def _resolve_source_commit(plan: EmissionPlan, build_repo_root: Path) -> str:
    """Resolve source_commit (the published commit of the foundation bundle the
    operator installed) from the registry by plan.bundle_version. Fail-closed."""
    registry_path = build_repo_root / "wizard" / "registry" / "foundation-bundles.json"
    if not registry_path.exists():
        raise UpgradeScaffoldError(f"registry not found at {registry_path}")
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise UpgradeScaffoldError(f"registry is not valid JSON: {registry_path}: {e}") from e
    for entry in registry.get("bundles", []):
        if entry.get("foundation_bundle_version") == plan.bundle_version:
            return entry.get("source_commit", "")
    raise UpgradeScaffoldError(
        f"bundle version {plan.bundle_version!r} not in registry {registry_path}"
    )


def _staged_content_files(staging_dir: Path) -> List[str]:
    """Sorted POSIX relpaths of every staged file EXCEPT the control files (which
    are inventoried separately and excluded from the hashed managed set)."""
    rels: List[str] = []
    for p in sorted(staging_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(staging_dir).as_posix()
        if rel in _CONTROL_SET:
            continue
        rels.append(rel)
    return sorted(rels)


def build_operator_manifest(plan: EmissionPlan, staging_dir: Path, build_repo_root: Path,
                            records: Optional[List[CorpusCellRecord]] = None) -> dict:
    """Build the manifest-v2 dict over the full staged tree (post-render). Pure
    function of the staged bytes + plan + registry; deterministic."""
    recs = records if records is not None else load_corpus_pack()
    source_commit = _resolve_source_commit(plan, build_repo_root)

    managed_files: Dict[str, dict] = {}
    for rel in _staged_content_files(staging_dir):
        lifecycle = classify_lifecycle(rel)  # fail-closed
        policy = LIFECYCLE_POLICY[lifecycle]
        digest = f"sha256:{sha256_file(staging_dir / rel)}"
        managed_files[rel] = {
            "managed": "true",
            "managed_by": policy["managed_by"],
            "lifecycle": lifecycle,
            "base_hash": digest,
            "current_hash_last_seen": digest,  # equals base_hash at emission (observational baseline)
            "local_modifications": policy["local_modifications"],
            "merge_strategy": policy["merge_strategy"],
            "source_refs": [],
        }

    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "foundation_bundle_version": plan.bundle_version,
        "source_commit": source_commit,
        "generator_version": plan.generator_version,
        "project_name": plan.project_name,
        "system_shape": plan.system_shape,
        "managed_files": managed_files,
        "control_files": sorted(CONTROL_FILES),
        "corpus_authority": build_corpus_authority_doc(plan, recs),
    }


def _write_json(dest: Path, doc: dict) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest


def emit_upgrade_policy(plan: EmissionPlan, staging_dir: Path) -> Path:
    """Emit .wizard/upgrade-policy.yaml — conservative v0 standing-approval config
    (deterministic text; no PyYAML)."""
    ap = plan.authority_profile
    lines = [
        "# Operator standing-approval policy for foundation-bundle upgrades.",
        "# v0: pinned by default; standing approval is disabled until the operator",
        "# authority profile is available. The operator may tighten, never loosen.",
        "upgrade_policy:",
        "  default: pinned",
        "  standing_approval:",
        "    patch_mechanical: false",
        "    patch_behavioral: false",
        "    minor_additive: false",
        "    major_breaking: false",
        "  standing_approval_constraints:",
        "    requires_clean_git: true",
        "    requires_backup_ready: true",
        "    requires_preflight_pass: true",
        "    excluded_when:",
        "      trust_posture: probationary",
        "      desired_autonomy: low",
        "      domain_risk: high",
        "      regulated_data: true",
        f"  authority_profile_ref: {ap.id}",
    ]
    dest = staging_dir / UPGRADE_POLICY_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def emit_upgrade_history(plan: EmissionPlan, staging_dir: Path) -> Path:
    """Emit .wizard/upgrade-history.log — append-only; seeded with a header only
    (deterministic; no clock)."""
    lines = [
        "# Foundation bundle upgrade history (append-only).",
        "# Each applied upgrade appends one entry: <date> <from> -> <to> <tier> <result>.",
        "# No upgrades applied yet.",
    ]
    dest = staging_dir / UPGRADE_HISTORY_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def emit_command_surface(plan: EmissionPlan, staging_dir: Path) -> Path:
    """Emit .wizard/UPGRADING.md — the operator-facing command surface. v0 is
    plan-only: checking for updates is supported; applying them is not yet."""
    lines = [
        "# Upgrading this system's foundation",
        "",
        f"This system was set up from foundation bundle **{plan.bundle_version}**. The wizard",
        "can tell you when a newer bundle is available and what would change.",
        "",
        "## Checking for updates",
        "",
        "Ask the wizard to run an upgrade check against this project. It reports the",
        "available versions, what would change, and whether any files you have edited",
        "would be affected — without changing anything.",
        "",
        "```",
        "wizard upgrade-check",
        "```",
        "",
        "To preview the plan for a specific version:",
        "",
        "```",
        "wizard upgrade-plan --to <version>",
        "```",
        "",
        "## Applying updates",
        "",
        "At this version, upgrades are **plan-only**: the wizard shows you exactly what",
        "would change, but does not modify your files. Applying an upgrade automatically",
        "is not yet available and will arrive in a later wizard release. Until then, any",
        "change the plan recommends is applied with your explicit confirmation.",
        "",
        "## What the wizard tracks",
        "",
        "`.wizard/manifest.json` records every file this system was set up with and its",
        "content fingerprint, so the wizard can tell which files you have customized and",
        "protect those edits during an upgrade. `.wizard/upgrade-policy.yaml` holds your",
        "upgrade preferences. `.wizard/upgrade-history.log` records upgrades over time.",
    ]
    dest = staging_dir / COMMAND_SURFACE_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def emit_manifest(plan: EmissionPlan, staging_dir: Path, build_repo_root: Path,
                  records: Optional[List[CorpusCellRecord]] = None) -> Path:
    """Build + write .wizard/manifest.json (manifest-v2). Must run LAST — after every
    other file (including the other control files) exists on disk."""
    doc = build_operator_manifest(plan, staging_dir, build_repo_root, records=records)
    return _write_json(staging_dir / MANIFEST_REL, doc)


def emit_upgrade_scaffold(plan: EmissionPlan, staging_dir: Path, build_repo_root: Path,
                          records: Optional[List[CorpusCellRecord]] = None) -> List[Path]:
    """Emit the full `.wizard/` upgrade scaffold into `staging_dir`. Order matters:
    policy + history + command surface FIRST (so the command surface is part of the
    hashed tree), then the manifest LAST (so it inventories the now-final tree and
    self-excludes). Returns every path written."""
    recs = records if records is not None else load_corpus_pack()
    written: List[Path] = []
    written.append(emit_upgrade_policy(plan, staging_dir))
    written.append(emit_upgrade_history(plan, staging_dir))
    written.append(emit_command_surface(plan, staging_dir))
    written.append(emit_manifest(plan, staging_dir, build_repo_root, records=recs))
    return written
