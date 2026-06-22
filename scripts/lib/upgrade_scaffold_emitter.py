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
from upgrade import sha256_bytes, sha256_file, normalize_for_content_hash  # type: ignore


class UpgradeScaffoldError(Exception):
    """Raised when the upgrade scaffold cannot be emitted (e.g. an unclassifiable
    staged file, or a bundle version absent from the registry). Fail-closed."""


MANIFEST_SCHEMA_VERSION = "manifest-v2"

MANIFEST_REL = ".wizard/manifest.json"
UPGRADE_POLICY_REL = ".wizard/upgrade-policy.yaml"
UPGRADE_HISTORY_REL = ".wizard/upgrade-history.log"
COMMAND_SURFACE_REL = ".wizard/UPGRADING.md"

# Imported (not re-declared) so there is ONE canonical relpath for the capsule.
from replay_capsule import REPLAY_CAPSULE_REL  # type: ignore  # noqa: E402

# Files present on disk but NOT merge-managed content (the control plane). They are
# inventoried under the manifest's `control_files` block but excluded from
# `managed_files` (and from the hashed set — manifest.json self-exclusion avoids a
# circular self-hash; policy/history are operator/runtime state; the replay capsule
# holds the build-time inputs, not managed content, and is gitignored by default).
CONTROL_FILES = (MANIFEST_REL, UPGRADE_POLICY_REL, UPGRADE_HISTORY_REL, REPLAY_CAPSULE_REL)
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
    "operator_fill_template": {  # wizard-seeded build-session template the operator FILLS in
        # (review prompts / skill templates): provided once, completed + edited by the operator;
        # upgrades must not clobber the operator's fills. Intentionally retains {{}} placeholders.
        "managed_by": "operator", "local_modifications": "expected", "merge_strategy": "operator_review",
    },
    # Foundation docs carry per-doc policy from the hash-baseline contract
    # (foundation-manifest-hash-baseline-v1.json). The contract is the canonical
    # authority; these four buckets transcribe it faithfully (the parity test in
    # test_upgrade_scaffold_emitter guards against transcription drift). Note vision
    # is shared/EXPECTED while approach + technical_architecture are shared/ALLOWED —
    # distinct buckets, not one. Replaced by contract-/plan-sourced policy at the
    # mutator slice (plan.emitted_files policy integration); classifier is the v0 home.
    "foundation_shared_expected": {  # vision.md
        "managed_by": "shared", "local_modifications": "expected", "merge_strategy": "three_way",
    },
    "foundation_shared_allowed": {  # approach.md, technical_architecture.md
        "managed_by": "shared", "local_modifications": "allowed", "merge_strategy": "three_way",
    },
    "foundation_operator": {  # prd.md, execution_plan.md, test_cases.md (operator-authored)
        "managed_by": "operator", "local_modifications": "expected", "merge_strategy": "operator_review",
    },
    "foundation_wizard": {  # audit_framework.md
        "managed_by": "wizard", "local_modifications": "not_recommended", "merge_strategy": "warn_on_drift",
    },
}

# Exact-path lifecycle overrides (relative to the operator-project root).
_EXACT_LIFECYCLE = {
    "CLAUDE.md": "inherited_content",
    "project_instructions.md": "inherited_content",
    "manual.md": "inherited_content",
    "operating_discipline.md": "inherited_content",
    "start-session.sh": "inherited_content",
    "session_bootstrap.md": "runtime_state",
    "pending_decisions.md": "runtime_state",
    "wizard_feedback.md": "runtime_state",
    "SESSION_STATE.md": "runtime_state",
    "build_progress.md": "runtime_state",  # acceptance ledger; operator updates after each phase
    # System-mutated docs (templates self-declare "Updated by the system. Never edited
    # manually") — runtime state, NOT wizard guidance. operator_review so a global --ack
    # never clobbers what the agents have written here (operator-state clobber fix). The other
    # docs/ files (how_your_system_works.md, voice_and_style.md) stay inherited_content
    # via the docs/ prefix — they are wizard guidance the operator only reads.
    "docs/future_items.md": "runtime_state",
    "docs/architectural_review_staging.md": "runtime_state",
    "docs/document_impact_map.md": "runtime_state",
    "agents/cron/cron_config.md": "runtime_state",
    ".gitignore": "operator_config",
    ".env": "operator_config",   # operator-owned secrets file, emitted empty; never wizard-overwritten
    COMMAND_SURFACE_REL: "inherited_content",
    # Foundation docs (root-level in the operator project; per-doc policy from the
    # hash-baseline contract — see the foundation_* lifecycles above).
    "vision.md": "foundation_shared_expected",
    "approach.md": "foundation_shared_allowed",
    "technical_architecture.md": "foundation_shared_allowed",
    "prd.md": "foundation_operator",
    "execution_plan.md": "foundation_operator",
    "test_cases.md": "foundation_operator",
    "audit_framework.md": "foundation_wizard",
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
    "quality/": "operator_config",   # operator's QA knowledge base + config (rules library,
                                      # source/advisor registries, validation + protected-workflow
                                      # config, review queue) — operator/system-written, NOT wizard
                                      # guidance. operator_review so a global --ack never clobbers it
                                      # (operator-state clobber fix).
    "security/": "operator_config",
    "wizard/": "operator_fill_template",   # operator's build-session materials (review prompts / skill templates)
    ".claude/": "inherited_content",       # Claude Code config (statusline + context-monitor hook + settings); wizard-authored
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
            source_commit = entry.get("source_commit")
            if not source_commit:
                raise UpgradeScaffoldError(
                    f"registry entry for bundle {plan.bundle_version!r} has no source_commit "
                    f"(false provenance); fix the registry before emitting"
                )
            return source_commit
    raise UpgradeScaffoldError(
        f"bundle version {plan.bundle_version!r} not in registry {registry_path}"
    )


def _staged_content_files(staging_dir: Path) -> List[str]:
    """Sorted POSIX relpaths of every staged file EXCEPT the control files (which
    are inventoried separately and excluded from the hashed managed set)."""
    rels: List[str] = []
    for p in sorted(staging_dir.rglob("*")):
        # Fail closed on symlinks: a symlink could hash content outside the staging
        # tree (non-deterministic + unsafe). Our emitters only write regular files.
        if p.is_symlink():
            raise UpgradeScaffoldError(
                f"refusing to hash symlink in staging: {p.relative_to(staging_dir).as_posix()}"
            )
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
        rendered = (staging_dir / rel).read_text(encoding="utf-8")
        digest = f"sha256:{sha256_file(staging_dir / rel)}"
        # base_content_hash = normalized hash (write-only foundation_schema_version
        # value blanked) — the change-detection / drift surface. base_hash stays the
        # full canonical render hash used by the replay-conformance gate. See
        # upgrade.normalize_for_content_hash (single shared normalizer).
        content_digest = "sha256:" + sha256_bytes(
            normalize_for_content_hash(rendered).encode("utf-8")
        )
        managed_files[rel] = {
            "managed": "true",
            "managed_by": policy["managed_by"],
            "lifecycle": lifecycle,
            "base_hash": digest,
            "base_content_hash": content_digest,
            "current_hash_last_seen": digest,  # equals base_hash at emission (observational baseline)
            # live_lineage_version (lineage guard): the bundle version whose render
            # the LIVE file descends from. At emit the live file IS the current render, so
            # it equals the emitted bundle version. The text-merge driver only auto-merges
            # a drifted three_way file whose live_lineage_version == the current version
            # (otherwise the live file no longer descends from render(current) and a merge
            # would run against the wrong base). Advanced to target on clean adopt/merge;
            # left unchanged on a sidecar route (so a routed file keeps routing).
            "live_lineage_version": plan.bundle_version,
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


def render_command_surface() -> str:
    """Return the operator-facing command-surface text for `.wizard/UPGRADING.md`.

    Single source of truth for the command surface, shared by the setup-time emitter
    (`emit_command_surface`) AND the upgrade-time refresh (the apply path re-renders this
    so an operator's copy stays current as the commands/scope evolve). Carries NO baked
    version number — the operator's current version lives in `.wizard/manifest.json` and
    is reported by the upgrade check — so the text never goes stale on a version bump."""
    lines = [
        "# Upgrading this system's foundation",
        "",
        "The wizard can tell you when a newer version of your system is available and what",
        "would change. To see the version you are on now and any available updates, run the",
        "upgrade check below (your current version is also recorded in `.wizard/manifest.json`).",
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
        "When you are ready to apply an update, run the apply command for a specific",
        "version. It updates the parts of your system the new version improves — your",
        "foundation documents and shared operating files — and never runs on its own: you",
        "have to ask for it each time.",
        "",
        "```",
        "wizard upgrade --to <version> --apply",
        "```",
        "",
        "Before it changes anything, the wizard makes a backup of your files. Any file you",
        "have edited yourself is kept exactly as-is; the new version of that file is saved",
        "next to it in a review folder (`.wizard/upgrade-review/`) so you can open it, see",
        "what changed, and copy over anything you want by hand. Nothing in the review folder",
        "is applied automatically.",
        "",
        "If you have edited a file that the wizard would normally just replace, it stops and",
        "asks you to confirm. Re-run the same command with `--ack` added to tell it you are",
        "okay replacing your edited version (your old version is still backed up first):",
        "",
        "```",
        "wizard upgrade --to <version> --apply --ack",
        "```",
        "",
        "To preview an update without changing anything, use `--plan-only` instead of",
        "`--apply` (or the `wizard upgrade-plan` command shown above).",
        "",
        "## What the wizard tracks",
        "",
        "`.wizard/manifest.json` records every file this system was set up with and its",
        "content fingerprint, so the wizard can tell which files you have customized and",
        "protect those edits during an upgrade. `.wizard/upgrade-policy.yaml` holds your",
        "upgrade preferences. `.wizard/upgrade-history.log` records upgrades over time.",
    ]
    return "\n".join(lines) + "\n"


def emit_command_surface(plan: EmissionPlan, staging_dir: Path) -> Path:
    """Emit .wizard/UPGRADING.md — the operator-facing command surface, from the single
    canonical body in `render_command_surface`."""
    dest = staging_dir / COMMAND_SURFACE_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_command_surface(), encoding="utf-8")
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
