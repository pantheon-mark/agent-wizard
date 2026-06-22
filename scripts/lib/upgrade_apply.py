"""Foundation-bundle merge-apply mutator — turns the plan-only upgrade path into an
apply-capable transaction for the foundation documents.

This is the disk-mutating sibling of the plan-only engine in `upgrade.py`. It
consumes the existing plan-only records (`compute_upgrade_plan` /
`compute_drift_report`) plus the operator's `.wizard/replay-capsule.json`, and
applies a foundation-bundle version bump to an operator project.

Scope (verified, do NOT exceed): a foundation-BUNDLE version bump only changes the
foundation documents the versioned bundle carries (the six template-backed docs the
generator renders for a version). Corpus / scaffold / agent files come from the
shared infra bundle and are NOT changed by a foundation-bundle bump, so they are
left untouched. The merge surface is exactly the foundation docs that
`generator.render_foundation_docs(version, inputs, build_repo_root)` produces and
that the manifest declares as managed.

Safety model (operator is non-technical):
  - REPLAY-CONFORMANCE GATE (fail-closed). Before any write, re-render the CURRENT
    version from the capsule's foundation_doc_inputs and confirm each rendered doc
    hashes identically to the manifest base_hash. If ANY foundation doc fails, the
    whole upgrade is refused — the capsule/manifest/generator are out of sync and
    re-rendering "theirs" cannot be trusted.
  - PER-FILE merge by merge_strategy (no bespoke line-merge engine at v0):
      frozen          -> drift hard-blocks; clean adopts theirs.
      three_way       -> clean (ours==base) adopts theirs; drift writes an overlay
                         sidecar and LEAVES the live file = ours (no git markers).
      operator_review -> always routes theirs to a review sidecar; live file = ours.
      warn_on_drift   -> drift without ack refuses; ack (or no drift) adopts theirs.
    A target template referencing a placeholder KEY absent from the capsule refuses
    the whole upgrade (migration-required; never emit a raw `{{...}}`).
  - TRANSACTION. Snapshot-backup the touched files + the whole `.wizard/` to
    `.wizard/backups/pre-<target>/`; stage every write to a temp dir; re-hash the
    staged bytes (post-validation); per-file atomic os.replace into the live tree;
    touch ONLY declared managed + control files. On any staged-validation failure,
    restore from backup and refuse (no live writes survive).
  - Standing auto-approval stays fully disabled; every apply is operator-explicit.

Stdlib-only, pip-install-free (operator/runtime path). No PyYAML, no third-party
deps; the build-side render-contract validator (which imports PyYAML) is NOT on
this path — post-validation re-hashes the staged bytes instead.
"""

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from bundle_templates import (  # type: ignore
    read_bundle_template,
    derive_scaffold_render_inputs,
    BundleTemplateError,
)
from generator import render_foundation_docs  # type: ignore
from replay_capsule import REPLAY_CAPSULE_REL, capsule_supports_operating_replay  # type: ignore
from section_merge import section_three_way_merge  # type: ignore
from upgrade import (  # type: ignore
    MERGE_STRATEGY_FROZEN,
    MERGE_STRATEGY_OPERATOR_REVIEW,
    MERGE_STRATEGY_THREE_WAY,
    MERGE_STRATEGY_WARN_ON_DRIFT,
    TIER_MAJOR_BREAKING,
    UpgradeError,
    classify_tier,
    find_bundle_entry,
    find_migration_entry,
    load_migration_manifest,
    normalize_for_content_hash,
    resolve_merge_strategy,
    sha256_bytes,
    sha256_file,
)


def _content_hash(text: str) -> str:
    """`sha256:`-prefixed hash of the CONTENT-normalized text (write-only
    foundation_schema_version value blanked). Used for change-detection + drift, NOT
    for the replay-conformance gate (which stays on the full-file base_hash)."""
    return "sha256:" + sha256_bytes(normalize_for_content_hash(text).encode("utf-8"))


# ===== Result classification =====

APPLY_RESULT_APPLIED = "applied"      # all touched files adopted theirs cleanly
APPLY_RESULT_PARTIAL = "partial"      # some files routed to review (live left = ours)
APPLY_RESULT_REFUSED = "refused"      # no live writes (gate failed / rollback)

# Per-file dispositions.
FILE_ADOPTED = "adopted"              # live file replaced with theirs
FILE_MERGED = "merged"               # live replaced with a clean section-aware 3-way merge
FILE_UNCHANGED = "unchanged"          # theirs == base; nothing to do
FILE_REVIEW = "routed_to_review"      # theirs written to sidecar; live left = ours

# Operator-manifest per-file field: the bundle version whose render the LIVE file
# descends from (set to target on clean adopt/merge; left unchanged on a route). The
# lineage guard merges a drifted three_way file ONLY when this == the current version.
LIVE_LINEAGE_VERSION_FIELD = "live_lineage_version"

UPGRADE_REVIEW_DIR_REL = ".wizard/upgrade-review"
BACKUPS_DIR_REL = ".wizard/backups"
UPGRADE_HISTORY_REL = ".wizard/upgrade-history.log"
MANIFEST_REL = ".wizard/manifest.json"

MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME = "migration-manifest.json"


class UpgradeApplyError(UpgradeError):
    """Raised when the apply transaction cannot proceed for a reason the caller
    should surface verbatim (refusal). Carries an actionable, operator-readable
    message. The CLI translates this to a non-zero exit code."""


@dataclass
class FileDecision:
    """Per-file apply decision."""
    relpath: str
    merge_strategy: str
    disposition: str            # FILE_ADOPTED | FILE_UNCHANGED | FILE_REVIEW
    drifted: bool
    note: str = ""
    review_paths: List[str] = field(default_factory=list)


@dataclass
class UpgradeApplyResult:
    """Outcome of apply_upgrade."""
    operator_project_path: str
    from_version: str
    to_version: str
    classification: str         # applied | partial | refused
    decisions: List[FileDecision] = field(default_factory=list)
    refusal_reason: str = ""
    backup_dir: str = ""
    upgrade_id: str = ""
    files_written: List[str] = field(default_factory=list)
    files_in_review: List[str] = field(default_factory=list)
    files_merged: List[str] = field(default_factory=list)
    # The classified merge surface sourced from the TARGET contract. Carries the
    # new/collision/dropped/needs-capsule files the foundation-doc loop alone never saw.
    # The copy-write path for `new` files is a follow-on task.
    surface: List["SurfaceEntry"] = field(default_factory=list)

    @property
    def applied(self) -> bool:
        return self.classification == APPLY_RESULT_APPLIED

    @property
    def refused(self) -> bool:
        return self.classification == APPLY_RESULT_REFUSED


# ===== Capsule loading =====

def load_replay_capsule(operator_project_dir: Path) -> Dict[str, Any]:
    """Load + minimally validate the operator project's `.wizard/replay-capsule.json`.

    Fail-closed: the apply path cannot run a faithful replay without the capsule,
    so its absence / malformation is a refusal."""
    path = operator_project_dir / REPLAY_CAPSULE_REL
    if not path.exists():
        raise UpgradeApplyError(
            f"replay capsule not found at {path}; the upgrade cannot re-render this "
            "system's foundation documents without it. (It is written when the system "
            "is first set up and is local-only by default.) Cannot apply."
        )
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise UpgradeApplyError(f"replay capsule at {path} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise UpgradeApplyError(f"replay capsule at {path} must be a JSON object")
    inputs = data.get("foundation_doc_inputs")
    if not isinstance(inputs, dict):
        raise UpgradeApplyError(
            f"replay capsule at {path} missing a `foundation_doc_inputs` object; "
            "cannot re-render foundation documents. Cannot apply."
        )
    return data


# ===== Foundation-doc render surface =====

def _foundation_managed_entries(manifest: Dict[str, Any], relpaths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Return the manifest managed_files entries for the given foundation-doc
    relpaths. A foundation doc the render surface produces but the manifest does
    not declare as managed is skipped (e.g. an operator-authored stub that carries
    no template). Returns {relpath: meta}."""
    files_block = manifest.get("managed_files") or manifest.get("files") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for rel in relpaths:
        meta = files_block.get(rel)
        if isinstance(meta, dict):
            out[rel] = meta
    return out


def _render_version(version: str, inputs: Dict[str, Any], build_repo_root: Path) -> Dict[str, str]:
    """Render the foundation docs for a version. Returns {operator_relpath: content}.

    A target template referencing a placeholder KEY absent from `inputs` raises a
    GeneratorError inside render_foundation_docs; the caller translates that to a
    fail-closed refusal (migration-required; never emit a raw placeholder)."""
    records = render_foundation_docs(version, inputs, build_repo_root)
    return {rec.operator_relpath: rec.content for rec in records}


_OL_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


def _render_operating_layer(
    version: str,
    relpaths: List[str],
    *,
    capsule: Dict[str, Any],
    capsule_inputs: Dict[str, Any],
    project_name: str,
    build_repo_root: Path,
) -> Dict[str, str]:
    """Render the operating-layer `render_kind:render` files (NOT the classic foundation
    docs) for `version`, byte-faithfully reproducing what the emitter produced.

    This is the CANONICAL operating-layer render used both for the conformance-gate
    "reproduce CURRENT" check and step 4c's "render THEIRS". It assembles the FULL input
    set the emitter used:

      - scaffold/root render files: re-derived DERIVED inputs (defaults + corpus block +
        autonomy body + resolved model tiers + rules-library body) from the relevant
        bundle/corpus/registry, overlaid with the capsule's PERSISTED inputs
        (foundation_doc_inputs + operating.resolved_scaffold_inputs). Then the bundle's
        deterministic target-hook injection post-pass is replayed over the rendered tree —
        exactly the emitter's step-5 transform.
      - agent-layer render files: the capsule's `operating.by_relpath[rel]` map is fully
        self-contained (already resolved at emit), so it is used verbatim.

    Fail-closed: a placeholder key that resolves nowhere raises UpgradeApplyError (the
    capsule/bundle are out of sync; never emit a raw `{{...}}`). The capsule-only
    substitution this replaces is the operating-layer-upgrade delivery gap — persisted
    inputs alone leave DERIVED placeholders unresolved.

    Returns {relpath: rendered content}. Stdlib-only / pip-free.
    """
    from corpus_emitter import inject_target_hooks  # type: ignore

    operating_block = capsule.get("operating") if isinstance(capsule, dict) else None
    by_relpath: Dict[str, Dict[str, str]] = {}
    persisted_scaffold: Dict[str, str] = {}
    if isinstance(operating_block, dict):
        _rsi = operating_block.get("resolved_scaffold_inputs") or {}
        if isinstance(_rsi, dict):
            persisted_scaffold = {k: str(v) for k, v in _rsi.items()}
        _byr = operating_block.get("by_relpath") or {}
        if isinstance(_byr, dict):
            by_relpath = {
                k: {kk: str(vv) for kk, vv in v.items()}
                for k, v in _byr.items()
                if isinstance(v, dict)
            }

    system_shape = str(capsule.get("system_shape", "")) if isinstance(capsule, dict) else ""
    # Re-derived base map for the scaffold/root render files (NOT agent files), assembled
    # from the TARGET bundle's deterministic derivations + the capsule's persisted inputs.
    scaffold_base = derive_scaffold_render_inputs(
        system_shape=system_shape,
        foundation_doc_inputs=dict(capsule_inputs),
        project_name=project_name,
        target_version=version,
        build_repo_root=build_repo_root,
    )
    # Persisted scaffold inputs are layered on top (they are persisted, not derived).
    scaffold_inputs = dict(scaffold_base)
    scaffold_inputs.update(persisted_scaffold)

    import tempfile
    out: Dict[str, str] = {}
    with tempfile.TemporaryDirectory() as _td:
        staging = Path(_td)
        # The shim carries only what inject_target_hooks reads (system_shape).
        from bundle_templates import _DerivationShim  # type: ignore
        shim = _DerivationShim(system_shape, dict(capsule_inputs))
        scaffold_relpaths: List[str] = []
        for rel in relpaths:
            try:
                template_text = read_bundle_template(version, rel, build_repo_root)
            except BundleTemplateError as e:
                raise UpgradeApplyError(
                    f"cannot read the target bundle template for operating-layer file "
                    f"{rel!r}: {e}. No files were changed."
                ) from e
            if rel in by_relpath:
                # Agent-layer file: the capsule's resolved dict is self-contained.
                sub_inputs = dict(by_relpath[rel])
            else:
                sub_inputs = scaffold_inputs
            missing_keys: List[str] = []

            def _replace(m: "re.Match", _sub=sub_inputs, _missing=missing_keys) -> str:
                key = m.group(1)
                if key not in _sub:
                    _missing.append(key)
                    return m.group(0)
                return _sub[key]

            rendered = _OL_PLACEHOLDER_RE.sub(_replace, template_text)
            if missing_keys:
                raise UpgradeApplyError(
                    f"the target bundle template for {rel!r} references placeholder(s) "
                    f"{sorted(set(missing_keys))} that could not be resolved from the "
                    f"recorded setup values or the target bundle. A setup-record (capsule) "
                    f"upgrade may be required. No files were changed."
                )
            sp = staging / rel
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(rendered, encoding="utf-8")
            if rel not in by_relpath:
                scaffold_relpaths.append(rel)

        # Replay the emitter's deterministic target-hook injection post-pass over the
        # staged tree (the hooks are corpus-derived from the bundle, not operator input).
        # This is the same transform the emitter runs at step 5, so the re-rendered bytes
        # match the emitted file exactly.
        inject_target_hooks(shim, staging)

        for rel in relpaths:
            out[rel] = (staging / rel).read_text(encoding="utf-8")
    return out


def _inject_hooks_for_copy_file(
    relpath: str, content: str, capsule: Dict[str, Any], build_repo_root: Path
) -> str:
    """Replay the bundle's deterministic target-hook injection for a single copy-kind
    file. The emitter injects corpus hooks (OP-… cross-reference regions) into hook-target
    files AFTER copying them, so the emitted bytes = template + hook region. Reproduce that
    here so a hook-target copy file's `theirs` matches what was emitted (otherwise drift
    detection false-positives on an unchanged file).

    Non-hook-target files are returned unchanged (inject_target_hooks skips them).
    Stdlib-only / pip-free; corpus hooks are bundle-derived, not operator input."""
    from corpus_emitter import inject_target_hooks  # type: ignore
    from bundle_templates import _DerivationShim  # type: ignore

    system_shape = str(capsule.get("system_shape", "")) if isinstance(capsule, dict) else ""
    fdi = capsule.get("foundation_doc_inputs") if isinstance(capsule, dict) else {}
    shim = _DerivationShim(system_shape, dict(fdi) if isinstance(fdi, dict) else {})
    import tempfile
    with tempfile.TemporaryDirectory() as _td:
        staging = Path(_td)
        sp = staging / relpath
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(content, encoding="utf-8")
        inject_target_hooks(shim, staging)
        return sp.read_text(encoding="utf-8")


# ===== Merge-surface computation + classification =====
#
# The merge surface MUST be sourced from the TARGET bundle's
# managed-artifacts contract (system-artifacts.json, delivery=="wizard"), NOT from
# what the CURRENT version happens to render. A system whose current bundle predates
# the operating layer (e.g. estate on v0.4.0) renders only foundation docs; sourcing
# the surface from that render silently drops every operating-layer file the target
# adds, so the upgrade reports `applied` while delivering nothing. Sourcing from the
# target contract is what lets a `new` file in the target be seen + staged.

# Surface entry classification.
SURFACE_NEW = "new"                  # in target, not in operator manifest/disk -> stage for create
SURFACE_MODIFIED = "modified"        # in both; content or render differs
SURFACE_UNCHANGED = "unchanged"      # in both; identical
SURFACE_DROPPED = "dropped"          # in manifest, not in target contract
SURFACE_COLLISION = "collision"      # `new` target path, but an UNMANAGED file already on disk
SURFACE_NEEDS_CAPSULE = "needs_capsule_upgrade"  # render-kind operating file, v1 capsule can't replay

# Render kinds (from the contract).
RENDER_KIND_RENDER = "render"
RENDER_KIND_COPY = "copy"

CONTRACT_BASENAME = "system-artifacts.json"


@dataclass
class SurfaceEntry:
    """One file on the computed merge surface."""
    relpath: str
    classification: str          # SURFACE_* above
    render_kind: str             # render | copy | "" (foundation-doc-from-render / dropped)
    merge_strategy: str
    in_manifest: bool
    on_disk: bool
    reason: str = ""             # operator-facing note (collision / needs-capsule / dropped)


def _load_target_contract(target_bundle_dir: Path) -> Optional[Dict[str, Any]]:
    """Load the target bundle's managed-artifacts contract, or None if the target is a
    foundation-only bundle (no system-artifacts.json). Stdlib-only; this is the
    operator/runtime path so it does NOT import the PyYAML-backed build validator."""
    contract_path = target_bundle_dir / CONTRACT_BASENAME
    if not contract_path.is_file():
        return None
    try:
        return json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise UpgradeApplyError(
            f"the target version's managed-artifacts contract at {contract_path} is not "
            f"valid JSON: {e}. Cannot apply."
        ) from e


def _manifest_managed_relpaths(manifest: Dict[str, Any]) -> set:
    block = manifest.get("managed_files") or manifest.get("files") or {}
    return set(block.keys()) if isinstance(block, dict) else set()


def compute_merge_surface(
    manifest: Dict[str, Any],
    target_contract: Optional[Dict[str, Any]],
    base_rendered: Dict[str, str],
    theirs_rendered: Dict[str, str],
    operator_project_dir: Path,
    capsule: Dict[str, Any],
) -> List[SurfaceEntry]:
    """Compute the upgrade merge surface from the TARGET bundle's contract.

    Surface = union(base_rendered keys, theirs_rendered keys, target wizard-delivery
    relpaths). Foundation docs flow through base/theirs render; copy-artifacts +
    operating-layer render files come from the contract. Each file is classified:

      new        -> in target contract, not in the operator manifest AND not on disk.
                    UNLESS an UNMANAGED file already exists at that path -> collision
                    (refuse/sidecar, never silently adopt/overwrite).
      modified   -> in both manifest and target; content/render differs (best-effort
                    for render-from-foundation files where we have theirs text).
      unchanged  -> in both; identical (or no signal to call it modified).
      dropped    -> in the manifest, not in the target contract / not rendered by target.
      needs_capsule_upgrade -> a render-kind operating-layer file whose `theirs` needs
                    the capsule's operating block, but the capsule is v1 (no operating
                    block). Surfaced + skipped with a reason; NOT a crash (a follow-on task upgrades
                    the capsule; this is graceful handling only).

    This function does NOT write anything. The actual copy-write path for new/copy
    files is a follow-on task; this is surface + classification only.
    """
    managed = _manifest_managed_relpaths(manifest)

    # Target wizard-delivery contract entries (relpath -> entry). Foundation-only
    # target (no contract) => empty; the surface then reduces to the rendered docs,
    # i.e. the pre-existing behavior (graceful).
    target_entries: Dict[str, Dict[str, Any]] = {}
    if target_contract:
        for entry in target_contract.get("artifacts", []):
            if entry.get("delivery") != "wizard":
                continue
            rel = entry.get("relpath")
            if rel:
                target_entries[rel] = entry

    operating_replay_ok = capsule_supports_operating_replay(capsule)

    # Foundation-doc render files (those produced by render_foundation_docs) are the
    # set we have rendered text for. The contract may mark a foundation doc render-kind
    # "render" too; we treat any relpath present in theirs_rendered/base_rendered as a
    # foundation-doc render file (replay handled by the existing engine, no operating
    # block needed).
    rendered_relpaths = set(base_rendered) | set(theirs_rendered)

    surface_relpaths = rendered_relpaths | set(target_entries) | managed
    out: List[SurfaceEntry] = []

    for rel in sorted(surface_relpaths):
        entry = target_entries.get(rel)
        in_target = rel in target_entries or rel in theirs_rendered
        in_manifest = rel in managed
        disk_path = operator_project_dir / rel
        on_disk = disk_path.exists()
        render_kind = str(entry.get("render_kind", "")) if entry else ""
        # Shared resolver (Fork 1(c)): target-contract precedence, then the manifest's
        # recorded strategy — the SAME function the plan/drift-report uses, so the apply
        # and the operator-facing plan can never diverge on what will happen to a file.
        _meta_strategy = ""
        if in_manifest:
            meta = (manifest.get("managed_files") or manifest.get("files") or {}).get(rel, {})
            _meta_strategy = str(meta.get("merge_strategy", ""))
        strategy = resolve_merge_strategy(entry, _meta_strategy, default="")

        # DROPPED: managed by the operator, but the target no longer carries it.
        if in_manifest and not in_target:
            out.append(SurfaceEntry(
                rel, SURFACE_DROPPED, render_kind, strategy, in_manifest, on_disk,
                reason="the new version no longer carries this file; left in place"))
            continue

        # In target. Decide new vs modified/unchanged.
        is_foundation_render = rel in rendered_relpaths
        if not in_manifest:
            # The operator does not manage this file yet -> NEW (or a collision).
            if on_disk:
                # An unmanaged file already exists here -> never silently overwrite.
                out.append(SurfaceEntry(
                    rel, SURFACE_COLLISION, render_kind, strategy, in_manifest, on_disk,
                    reason="a file already exists at this path that the system does not "
                           "manage; the new version was NOT applied over it"))
                continue
            # Render-kind operating-layer file needing the capsule operating block, but
            # the capsule is v1 -> surface as needing a capsule upgrade, do not crash.
            if (render_kind == RENDER_KIND_RENDER
                    and not is_foundation_render
                    and not operating_replay_ok):
                out.append(SurfaceEntry(
                    rel, SURFACE_NEEDS_CAPSULE, render_kind, strategy, in_manifest, on_disk,
                    reason="this new file is built from recorded setup values that this "
                           "system's setup record does not yet carry; it will be available "
                           "after the setup record is upgraded"))
                continue
            out.append(SurfaceEntry(
                rel, SURFACE_NEW, render_kind, strategy, in_manifest, on_disk))
            continue

        # In both manifest and target. For foundation-doc render files we have theirs
        # text and can detect modification by content hash; for contract-only files we
        # lack rendered theirs here (produced by a follow-on task), so default to unchanged-with-signal.
        if is_foundation_render and rel in theirs_rendered and rel in base_rendered:
            differs = (_content_hash(theirs_rendered[rel]) != _content_hash(base_rendered[rel]))
            out.append(SurfaceEntry(
                rel,
                SURFACE_MODIFIED if differs else SURFACE_UNCHANGED,
                render_kind, strategy, in_manifest, on_disk))
        else:
            out.append(SurfaceEntry(
                rel, SURFACE_UNCHANGED, render_kind, strategy, in_manifest, on_disk,
                reason="copy/operating-layer file; disposition computed by the per-file "
                       "engine (write path is a follow-on task)"))
    return out


# ===== Target-change set (READ-ONLY; consumed by the plan path) =====
#
# The upgrade PLAN must show the operator what the TARGET version changes — the
# artifacts the target bundle ADDS or MODIFIES versus the operator's current
# installed version — NOT the operator's local drift. This is the complement of the
# drift report ("your local changes"): the change set is "what the new version
# changes for you, and why".
#
# It is computed by REUSING the apply engine's surface computation read-only:
#   - render the CURRENT version (base) and the TARGET version (theirs) for the
#     classic foundation docs (_render_version);
#   - render the CURRENT + TARGET operating-layer render-kind files
#     (_render_operating_layer) so a modified operating doc (e.g.
#     operating_discipline.md) is detected by content hash, not silently dropped;
#   - read the TARGET bundle template for each copy-kind file (+ replay the
#     deterministic hook injection) so a modified/new copy file (e.g. a new
#     health-check skill) is detected;
#   - classify each surface entry new / modified / unchanged.
#
# It performs NO writes and mutates nothing on disk. It is fail-soft: a v1 capsule
# that cannot replay the operating layer degrades to "" (the caller treats that as
# an empty change set + the drift report still shows) rather than refusing.


@dataclass
class TargetChangeEntry:
    """One artifact the target version adds or modifies vs the current version.

    Read-only planning record; the plan path joins these with the migration-manifest
    benefit text + the operator's drift state to build the operator-facing analysis.

    Fields:
        relpath        -- artifact path inside the operator project
        what           -- "new" | "modified"
        render_kind    -- "render" | "copy"
        merge_strategy -- the file's merge strategy (drives the at-risk label)
        drift_status   -- the operator's local drift on this file (DRIFT_NONE for a
                          new file, or the manifest-derived drift state for a modified
                          one). Drives whether applying touches an operator-edited file.
    """
    relpath: str
    what: str            # "new" | "modified"
    render_kind: str     # render | copy
    merge_strategy: str
    drift_status: str


def _drift_status_for(
    operator_project_dir: Path,
    manifest: Dict[str, Any],
    relpath: str,
) -> str:
    """Operator-local drift status for one managed file (content-hash based), used to
    label whether applying a target change touches a file the operator has edited.
    Returns DRIFT_NONE / DRIFT_DETECTED / DRIFT_MISSING_FILE. A file not in the
    manifest (a brand-new target file) has no recorded baseline -> DRIFT_NONE."""
    from upgrade import DRIFT_NONE, DRIFT_DETECTED, DRIFT_MISSING_FILE  # type: ignore

    files_block = manifest.get("managed_files") or manifest.get("files") or {}
    meta = files_block.get(relpath)
    if not isinstance(meta, dict):
        return DRIFT_NONE
    abs_path = operator_project_dir / relpath
    if not abs_path.exists():
        return DRIFT_MISSING_FILE
    base_content = str(meta.get("base_content_hash", "")) or str(meta.get("base_hash", ""))
    if not base_content.startswith("sha256:"):
        return DRIFT_NONE
    live = abs_path.read_text(encoding="utf-8")
    return DRIFT_NONE if _content_hash(live) == base_content else DRIFT_DETECTED


def compute_target_change_set(
    operator_project_dir: Path,
    target_version: str,
    build_repo_root: Path,
    *,
    registry: Dict[str, Any],
    manifest: Dict[str, Any],
) -> List[TargetChangeEntry]:
    """Compute the read-only set of artifacts the TARGET version adds/modifies vs the
    operator's current version. NO disk writes; mutates nothing.

    Reuses the apply engine's render + surface computation:
      _render_version (foundation docs), _render_operating_layer (operating-layer
      render files), read_bundle_template + _inject_hooks_for_copy_file (copy files),
      compute_merge_surface (new/modified/unchanged classification).

    Fail-soft: if the change set cannot be computed (e.g. a legacy v1 capsule that
    cannot replay the operating layer, or a missing capsule/contract), returns [] so
    the plan still renders (the drift report remains the complementary view). For a
    v2-capsule system this populates the full new+modified set.

    Returns the NEW + MODIFIED entries only (unchanged + dropped are excluded — the
    operator reviews only what changes).
    """
    current_version = str(manifest.get("foundation_bundle_version", ""))
    target_entry = find_bundle_entry(registry, target_version)
    if target_entry is None:
        return []

    try:
        capsule = load_replay_capsule(operator_project_dir)
        capsule_inputs = capsule["foundation_doc_inputs"]
    except UpgradeApplyError:
        # No / malformed capsule -> cannot re-render -> empty change set (fail-soft).
        return []

    target_bundle_dir = (build_repo_root / target_entry.get("path", "")).resolve()

    # 1. Foundation-doc base + theirs (the classic 6 docs render_foundation_docs produces).
    try:
        base_rendered = _render_version(current_version, capsule_inputs, build_repo_root)
        theirs_rendered = _render_version(target_version, capsule_inputs, build_repo_root)
    except Exception:
        # A placeholder the capsule cannot resolve (e.g. the target adds a question this
        # system never answered) -> degrade to empty (the plan + drift report still show).
        return []

    target_contract = _load_target_contract(target_bundle_dir)

    # 2. Compute the surface (new/modified/unchanged per artifact) from the TARGET
    #    contract — the same read-only classification the apply path uses.
    try:
        surface = compute_merge_surface(
            manifest, target_contract, base_rendered, theirs_rendered,
            operator_project_dir, capsule,
        )
    except UpgradeApplyError:
        return []

    foundation_relpaths = set(base_rendered) | set(theirs_rendered)

    # 3. For operating-layer render-kind files + copy-kind files, compute_merge_surface
    #    lacks `theirs` text and defaults them to UNCHANGED-with-signal. Render those
    #    `theirs` here so a genuine modification is detected by content hash. This mirrors
    #    the apply path's step-4b (copy) + step-4c (operating render) `theirs` computation,
    #    but read-only.
    files_block = manifest.get("managed_files") or manifest.get("files") or {}

    # Operating-layer render files that are managed + surviving.
    ol_render_rels = [
        se.relpath for se in surface
        if se.render_kind == RENDER_KIND_RENDER
        and se.relpath not in foundation_relpaths
        and se.classification not in (SURFACE_DROPPED, SURFACE_COLLISION, SURFACE_NEEDS_CAPSULE)
        and se.in_manifest
    ]
    project_name = str(manifest.get("project_name", "")) or str(
        capsule_inputs.get("PROJECT_NAME", "")
    )
    theirs_ol: Dict[str, str] = {}
    if ol_render_rels:
        try:
            theirs_ol = _render_operating_layer(
                target_version, ol_render_rels,
                capsule=capsule, capsule_inputs=capsule_inputs,
                project_name=project_name, build_repo_root=build_repo_root,
            )
        except UpgradeApplyError:
            # Operating layer not replayable (v1 capsule) -> those files stay unclassified
            # for modification (fail-soft); foundation + copy deltas still surface.
            theirs_ol = {}

    # Copy-kind files (with a real bundle template) that are managed + surviving.
    contract_entries_map: Dict[str, Dict[str, Any]] = {}
    if target_contract:
        for _art in target_contract.get("artifacts", []):
            if _art.get("relpath"):
                contract_entries_map[_art["relpath"]] = _art

    from upgrade import DRIFT_NONE  # type: ignore

    out: List[TargetChangeEntry] = []
    for se in surface:
        rel = se.relpath
        cls = se.classification
        if cls in (SURFACE_DROPPED, SURFACE_COLLISION, SURFACE_NEEDS_CAPSULE):
            # Not a clean target add/modify the operator can simply review-and-apply.
            continue

        is_foundation = rel in foundation_relpaths

        if cls == SURFACE_NEW:
            out.append(TargetChangeEntry(
                relpath=rel, what="new",
                render_kind=se.render_kind or RENDER_KIND_COPY,
                merge_strategy=se.merge_strategy,
                drift_status=DRIFT_NONE,
            ))
            continue

        # MODIFIED / UNCHANGED in-manifest entry: decide modified vs unchanged by
        # comparing target `theirs` to the manifest's recorded base_content_hash.
        meta = files_block.get(rel, {}) if isinstance(files_block, dict) else {}
        base_content = str(meta.get("base_content_hash", "")) or str(meta.get("base_hash", ""))

        theirs_text: Optional[str] = None
        if is_foundation and rel in theirs_rendered:
            theirs_text = theirs_rendered[rel]
        elif rel in theirs_ol:
            theirs_text = theirs_ol[rel]
        elif se.render_kind == RENDER_KIND_COPY and rel in contract_entries_map \
                and contract_entries_map[rel].get("template_path") is not None:
            try:
                copy_text = read_bundle_template(target_version, rel, build_repo_root)
                theirs_text = _inject_hooks_for_copy_file(
                    rel, copy_text, capsule, build_repo_root
                )
            except (BundleTemplateError, UpgradeApplyError):
                theirs_text = None

        if theirs_text is None:
            # No `theirs` signal (e.g. control-plane-emitted file, or unrenderable) ->
            # cannot assert a modification; fall back on the surface classification.
            if cls == SURFACE_MODIFIED:
                out.append(TargetChangeEntry(
                    relpath=rel, what="modified",
                    render_kind=se.render_kind or RENDER_KIND_COPY,
                    merge_strategy=se.merge_strategy,
                    drift_status=_drift_status_for(operator_project_dir, manifest, rel),
                ))
            continue

        if base_content.startswith("sha256:") and _content_hash(theirs_text) == base_content:
            continue  # unchanged — not part of the change set

        out.append(TargetChangeEntry(
            relpath=rel, what="modified",
            render_kind=se.render_kind or RENDER_KIND_COPY,
            merge_strategy=se.merge_strategy,
            drift_status=_drift_status_for(operator_project_dir, manifest, rel),
        ))

    out.sort(key=lambda e: e.relpath)
    return out


# ===== Replay-conformance gate =====

def _operating_render_relpaths(
    current_version: str,
    build_repo_root: Path,
    manifest: Dict[str, Any],
    foundation_entries: Dict[str, Dict[str, Any]],
) -> List[str]:
    """The managed operating-layer `render_kind:render` relpaths to verify at the
    CURRENT bundle (NOT the classic foundation docs, which the foundation leg covers).
    Identified from the CURRENT bundle's contract (the manifest carries no render_kind),
    intersected with the manifest's managed entries. Empty for a foundation-only current
    bundle (no contract)."""
    contract_path = (build_repo_root / "wizard" / "foundation-bundles"
                     / current_version / CONTRACT_BASENAME)
    if not contract_path.is_file():
        return []
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    managed = _manifest_managed_relpaths(manifest)
    out: List[str] = []
    for entry in contract.get("artifacts", []):
        if entry.get("delivery") != "wizard" or entry.get("render_kind") != RENDER_KIND_RENDER:
            continue
        rel = entry.get("relpath")
        if rel and rel not in foundation_entries and rel in managed:
            out.append(rel)
    return sorted(out)


def _replay_conformance_check(
    current_version: str,
    capsule_inputs: Dict[str, Any],
    build_repo_root: Path,
    foundation_entries: Dict[str, Dict[str, Any]],
    *,
    capsule: Optional[Dict[str, Any]] = None,
    manifest: Optional[Dict[str, Any]] = None,
    project_name: str = "",
) -> None:
    """Fail-closed gate: re-render the CURRENT version from the capsule inputs and
    confirm each foundation doc hashes identically to the manifest base_hash.

    Operating-layer leg (when `capsule` + `manifest` are supplied): ALSO re-render the
    current bundle's managed operating-layer `render_kind:render` files through the
    CANONICAL render (capsule persisted inputs + current-bundle-DERIVED inputs +
    target-hook injection) and confirm each reproduces the manifest base_hash. This is the
    symmetric counterpart to step 4c's TARGET render: if the canonical render cannot
    reproduce CURRENT, the merge base it computes for a drifted three_way file is untrusted,
    so the upgrade is refused. (Proven a no-false-fail leg: all current operating render
    files reproduce their recorded base_hash.)

    Uses the SAME hashing scheme the manifest base_hash was produced with:
    `sha256:` + sha256_bytes(rendered.encode("utf-8")). sha256_bytes applies the
    canonical (LF/UTF-8/no-BOM/no-trailing-ws) transform — identical to
    upgrade_scaffold_emitter.build_operator_manifest, which does
    `f"sha256:{sha256_file(...)}"` and sha256_file = sha256 over canonicalize_bytes.

    On ANY mismatch the whole upgrade is refused: the capsule no longer faithfully
    reproduces what was emitted, so re-rendering 'theirs' cannot be trusted."""
    base_rendered = _render_version(current_version, capsule_inputs, build_repo_root)
    mismatches: List[str] = []
    for rel, meta in foundation_entries.items():
        if rel not in base_rendered:
            mismatches.append(f"{rel} (not produced by the current-version render surface)")
            continue
        expected = str(meta.get("base_hash", ""))
        actual = "sha256:" + sha256_bytes(base_rendered[rel].encode("utf-8"))
        if actual != expected:
            mismatches.append(f"{rel} (manifest base_hash != re-rendered hash)")

    # Operating-layer leg: verify the canonical CURRENT render of the managed operating
    # render files reproduces their recorded base_hash (symmetric to step 4c).
    if capsule is not None and manifest is not None:
        ol_rels = _operating_render_relpaths(
            current_version, build_repo_root, manifest, foundation_entries
        )
        if ol_rels:
            files_block = manifest.get("managed_files") or manifest.get("files") or {}
            try:
                ol_rendered = _render_operating_layer(
                    current_version, ol_rels,
                    capsule=capsule, capsule_inputs=capsule_inputs,
                    project_name=project_name, build_repo_root=build_repo_root,
                )
            except UpgradeApplyError as e:
                mismatches.append(f"operating layer (render failed: {e})")
                ol_rendered = {}
            for rel in ol_rels:
                if rel not in ol_rendered:
                    continue
                expected = str(files_block.get(rel, {}).get("base_hash", ""))
                actual = "sha256:" + sha256_bytes(ol_rendered[rel].encode("utf-8"))
                if actual != expected:
                    mismatches.append(f"{rel} (manifest base_hash != re-rendered hash)")
    if mismatches:
        raise UpgradeApplyError(
            "replay-conformance gate FAILED: the recorded build inputs no longer "
            "reproduce the foundation documents this system was set up with "
            f"({'; '.join(sorted(mismatches))}). The replay capsule, the manifest, "
            "and the document generator are out of sync, so an upgrade cannot be "
            "applied safely. No files were changed. (This usually means the capsule "
            "or manifest was edited by hand, or the generator changed.)"
        )


# ===== Diff (plain-language, no git markers) =====

def _unified_diff(ours: str, theirs: str, relpath: str) -> str:
    """A simple unified diff of ours vs theirs. Uses difflib (stdlib). Never emits
    git conflict markers — this is a side-by-side review aid, not a merge result."""
    import difflib
    diff = difflib.unified_diff(
        ours.splitlines(keepends=True),
        theirs.splitlines(keepends=True),
        fromfile=f"{relpath} (your current version)",
        tofile=f"{relpath} (new version)",
    )
    return "".join(diff)


_OVERLAY_NOTE = (
    "# The upgrade did NOT change your file\n"
    "#\n"
    "# Your current version of this document was kept exactly as-is. A newer\n"
    "# version is shown below for reference. If you want any of the new wording,\n"
    "# copy it from the new version into your file by hand. Nothing here is applied\n"
    "# automatically. The matching `.diff` file shows what changed line by line.\n"
    "#\n"
    "# ---- new version below this line ----\n"
)


def _write_review_sidecar(
    review_dir: Path,
    relpath: str,
    ours: str,
    theirs: str,
    *,
    overlay_note: bool,
) -> List[str]:
    """Write the review sidecar files for one file. Returns the relpaths written
    (relative to the operator project). Writes:
      <relpath>.new   — theirs (optionally preceded by a plain-language overlay note)
      <relpath>.ours  — the operator's current version (for side-by-side)
      <relpath>.diff  — unified diff ours -> theirs
    Never writes git conflict markers into anything."""
    base = review_dir / relpath
    base.parent.mkdir(parents=True, exist_ok=True)
    new_path = base.with_name(base.name + ".new")
    ours_path = base.with_name(base.name + ".ours")
    diff_path = base.with_name(base.name + ".diff")
    new_body = (_OVERLAY_NOTE + theirs) if overlay_note else theirs
    new_path.write_text(new_body, encoding="utf-8")
    ours_path.write_text(ours, encoding="utf-8")
    diff_path.write_text(_unified_diff(ours, theirs, relpath), encoding="utf-8")
    proj_root = review_dir.parents[2]  # <proj>/.wizard/upgrade-review/<id> -> <proj>
    return [str(p.relative_to(proj_root)) for p in (new_path, ours_path, diff_path)]


# ===== The transaction =====

def _read_live(operator_project_dir: Path, relpath: str) -> Optional[str]:
    p = operator_project_dir / relpath
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def _snapshot_backup(
    operator_project_dir: Path,
    target_version: str,
    touched_relpaths: List[str],
) -> Path:
    """Snapshot the files that will be touched + the whole `.wizard/` control plane
    into `.wizard/backups/pre-<target>/`. Returns the backup dir.

    `.wizard/` is copied wholesale so the manifest/history/capsule can be restored;
    the touched managed files (foundation docs) are copied under the same relpath."""
    backup_dir = operator_project_dir / BACKUPS_DIR_REL / f"pre-{target_version}"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    # Back up the whole .wizard/ EXCEPT the backups subtree itself (no recursion).
    wizard_dir = operator_project_dir / ".wizard"
    if wizard_dir.exists():
        dest_wizard = backup_dir / ".wizard"
        shutil.copytree(
            wizard_dir,
            dest_wizard,
            ignore=shutil.ignore_patterns("backups"),
        )
    for rel in touched_relpaths:
        src = operator_project_dir / rel
        if src.exists():
            dest = backup_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    return backup_dir


def _restore_backup(operator_project_dir: Path, backup_dir: Path, touched_relpaths: List[str]) -> None:
    """Restore the touched files + `.wizard/` from a snapshot backup."""
    backup_wizard = backup_dir / ".wizard"
    if backup_wizard.exists():
        live_wizard = operator_project_dir / ".wizard"
        # Restore each backed-up control file in place (do not blow away backups/).
        for p in backup_wizard.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(backup_wizard)
            dest = live_wizard / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
    for rel in touched_relpaths:
        bsrc = backup_dir / rel
        if bsrc.exists():
            dest = operator_project_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bsrc, dest)


def apply_upgrade(
    operator_project_dir: Path,
    target_version: str,
    build_repo_root: Path,
    *,
    registry: Dict[str, Any],
    registry_path: Path,
    manifest: Dict[str, Any],
    manifest_path: Path,
    ack: bool = False,
    backup: bool = True,
) -> UpgradeApplyResult:
    """Apply a foundation-bundle version bump to an operator project.

    Returns an UpgradeApplyResult classified applied / partial / refused. A refusal
    performs NO live writes (a failed staged-validation rolls back from the backup).
    A partial (some files routed to review) is NOT success.

    The caller (CLI) loads + validates the manifest + registry; this function takes
    them in so the loaders' fail-closed validation is the single source of truth.
    """
    operator_project_dir = Path(operator_project_dir)
    current_version = str(manifest.get("foundation_bundle_version", ""))

    # --- 1. Target + migration gate -------------------------------------------
    target_entry = find_bundle_entry(registry, target_version)
    if target_entry is None:
        raise UpgradeApplyError(
            f"target version {target_version!r} is not in the registry; cannot apply."
        )
    if target_version == current_version:
        raise UpgradeApplyError(
            f"this system is already on {current_version!r}; nothing to apply."
        )

    target_bundle_dir = (build_repo_root / target_entry.get("path", "")).resolve()
    migration_json = target_bundle_dir / MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME
    if not migration_json.exists():
        raise UpgradeApplyError(
            f"target version {target_version!r} has no migration manifest at "
            f"{migration_json}; cannot apply (migration metadata is required)."
        )
    migration_manifest = load_migration_manifest(migration_json)
    migration = find_migration_entry(migration_manifest, current_version)
    if migration is None:
        raise UpgradeApplyError(
            f"target version {target_version!r} declares no migration path FROM this "
            f"system's current version {current_version!r}; cannot apply. (A migration "
            "entry with a matching `from:` is required.)"
        )
    stop_condition = str(migration.get("stop_condition", "")).strip()
    if stop_condition and stop_condition.lower() not in ("", "none", "not_applicable", "n/a"):
        raise UpgradeApplyError(
            f"this upgrade declares a stop condition that must be handled before it can "
            f"be applied automatically: {stop_condition}. No files were changed."
        )

    capsule = load_replay_capsule(operator_project_dir)
    capsule_inputs = capsule["foundation_doc_inputs"]

    # --- 2. Determine the foundation-doc merge surface ------------------------
    # Render the current version once to learn which foundation docs the version
    # carries; intersect with the manifest's managed entries (the merge surface).
    base_rendered = _render_version(current_version, capsule_inputs, build_repo_root)
    foundation_entries = _foundation_managed_entries(manifest, list(base_rendered.keys()))
    if not foundation_entries:
        raise UpgradeApplyError(
            "no foundation documents are declared managed in this system's manifest; "
            "there is nothing for a foundation-bundle upgrade to apply."
        )

    # --- 2b. Replay-conformance gate (fail-closed) ----------------------------
    # Includes the operating-layer leg: the canonical CURRENT render of managed operating
    # render files must reproduce their recorded base_hash (symmetric to step 4c's TARGET
    # render). project_name (structural; the project's directory-derived name) is the
    # PROJECT_NAME the emitter substituted — sourced from the manifest, not foundation_doc_inputs.
    project_name = str(manifest.get("project_name", "")) or str(
        capsule_inputs.get("PROJECT_NAME", "")
    )
    _replay_conformance_check(
        current_version, capsule_inputs, build_repo_root, foundation_entries,
        capsule=capsule, manifest=manifest, project_name=project_name,
    )

    # --- 3. Render theirs (fail-closed on missing placeholder) ----------------
    target_generator_version = _read_target_generator_version(build_repo_root, target_entry)
    try:
        theirs_rendered = _render_version(target_version, capsule_inputs, build_repo_root)
    except Exception as e:  # GeneratorError on undefined placeholder, etc.
        raise UpgradeApplyError(
            f"the target version {target_version!r} could not be rendered from the "
            f"recorded build inputs: {e}. This usually means the new version adds a "
            "question this system never answered; an upgrade for it is not available "
            "yet. No files were changed."
        ) from e

    # Auto-merge is permitted for this release unless the migration opts out (e.g. a
    # major/structural release that renames/reorders sections). Wired in Phase 4.
    auto_merge_enabled = _auto_merge_enabled(migration, current_version, target_version)

    # --- 3b. Compute the merge surface from the TARGET contract -----
    # Source-of-truth = the target bundle's system-artifacts.json (delivery=="wizard"),
    # NOT _render_version(current).keys(). This is what surfaces operating-layer + copy
    # files the current bundle never rendered, so a system upgrading FROM a
    # pre-operating-layer bundle (e.g. estate on v0.4.0) actually sees them instead of
    # silently delivering nothing. This classifies the surface; the write path
    # for new/copy/operating-layer files.
    target_contract = _load_target_contract(target_bundle_dir)
    surface = compute_merge_surface(
        manifest, target_contract, base_rendered, theirs_rendered,
        operator_project_dir, capsule,
    )

    # --- 4. Per-file decisions ------------------------------------------------
    decisions: List[FileDecision] = []
    upgrade_id = f"{current_version}-to-{target_version}"

    # Plan the staged writes: relpath -> bytes-to-write-into-live.
    staged_writes: Dict[str, str] = {}
    review_writes: List[tuple] = []  # (relpath, ours, theirs, overlay_note)
    frozen_blocks: List[str] = []

    for rel, meta in sorted(foundation_entries.items()):
        strategy = str(meta.get("merge_strategy", MERGE_STRATEGY_OPERATOR_REVIEW))
        live = _read_live(operator_project_dir, rel)
        if live is None:
            # A declared managed foundation doc missing on disk is a refusal — we
            # cannot determine drift, and silently re-creating it could clobber an
            # operator-intended deletion.
            raise UpgradeApplyError(
                f"managed foundation document {rel!r} is missing on disk; cannot "
                "apply an upgrade over a missing file. Restore it (or run an upgrade "
                "check) first. No files were changed."
            )
        # Change-detection + drift use CONTENT hashes (write-only schema-version field
        # blanked) so a pure foundation_schema_version bump is not a content change.
        # base_content = manifest base_content_hash, OR back-compat backfill from the
        # current-version re-render (SAFE: the replay-conformance gate just verified
        # base_rendered reproduces the full-file base_hash).
        base_content = str(meta.get("base_content_hash", "")) or _content_hash(base_rendered[rel])
        ours_content = _content_hash(live)
        drifted = (ours_content != base_content)
        theirs = theirs_rendered.get(rel)
        if theirs is None:
            # Target version dropped this doc from its render surface. v0 leaves it
            # in place (no destructive removal); treat as unchanged.
            decisions.append(FileDecision(rel, strategy, FILE_UNCHANGED, drifted,
                                          note="target version no longer renders this doc; left in place"))
            continue

        theirs_content = _content_hash(theirs)
        target_changed = (theirs_content != base_content)

        if not target_changed:
            decisions.append(FileDecision(rel, strategy, FILE_UNCHANGED, drifted,
                                          note="target version is identical to the installed version"))
            continue

        if strategy == MERGE_STRATEGY_FROZEN:
            if drifted:
                frozen_blocks.append(rel)
                continue
            staged_writes[rel] = theirs
            decisions.append(FileDecision(rel, strategy, FILE_ADOPTED, drifted,
                                          note="frozen file, no operator edits; adopted the new version"))
        elif strategy == MERGE_STRATEGY_THREE_WAY:
            if not drifted:
                staged_writes[rel] = theirs
                decisions.append(FileDecision(rel, strategy, FILE_ADOPTED, drifted,
                                              note="no operator edits; adopted the new version"))
            else:
                # Drifted three_way: attempt a SECTION-AWARE 3-way merge, but ONLY when
                # the live file descends from the current render (lineage guard) AND the
                # release permits auto-merge. base = the current-version re-render the
                # replay-conformance gate already verified (base_rendered[rel]); ours =
                # live; theirs = the target render. A clean merge writes the merged
                # content live (adopt-like); a conflict / structural ambiguity, an
                # ineligible lineage, or a disabled release falls back to the review
                # sidecar with the live file left exactly as the operator left it
                # (NEVER git conflict markers).
                eligible = str(meta.get(LIVE_LINEAGE_VERSION_FIELD, "")) == current_version
                merge = (section_three_way_merge(base_rendered[rel], live, theirs)
                         if (eligible and auto_merge_enabled) else None)
                if merge is not None and merge.clean:
                    staged_writes[rel] = merge.merged
                    decisions.append(FileDecision(rel, strategy, FILE_MERGED, drifted,
                                                  note="your edits were merged with the new version"))
                else:
                    if merge is not None and not merge.clean:
                        note = ("your edits overlap with the new version, so they could not "
                                "be merged automatically; your version was kept and the new "
                                "version was saved for review")
                    else:
                        note = ("you edited this file; your version was kept and the new "
                                "version was saved for review")
                    review_writes.append((rel, live, theirs, True))
                    decisions.append(FileDecision(rel, strategy, FILE_REVIEW, drifted, note=note))
        elif strategy == MERGE_STRATEGY_OPERATOR_REVIEW:
            review_writes.append((rel, live, theirs, False))
            decisions.append(FileDecision(rel, strategy, FILE_REVIEW, drifted,
                                          note="this file is operator-reviewed; the new version was saved for review and your version kept"))
        elif strategy == MERGE_STRATEGY_WARN_ON_DRIFT:
            if drifted and not ack:
                raise UpgradeApplyError(
                    f"{rel!r} has local edits and its upgrade rule requires you to "
                    "acknowledge replacing them. Re-run the upgrade with --ack to "
                    "adopt the new version (your current version is backed up first). "
                    "No files were changed."
                )
            staged_writes[rel] = theirs
            decisions.append(FileDecision(rel, strategy, FILE_ADOPTED, drifted,
                                          note=("acknowledged; adopted the new version" if drifted
                                                else "no operator edits; adopted the new version")))
        else:
            raise UpgradeApplyError(
                f"{rel!r} has an unrecognized merge strategy {strategy!r}; refusing to "
                "apply rather than guess. No files were changed."
            )

    if frozen_blocks:
        raise UpgradeApplyError(
            "this upgrade is blocked because protected file(s) have local edits: "
            f"{', '.join(sorted(frozen_blocks))}. These files are not meant to be edited "
            "and cannot be upgraded while they differ from their original. Restore them "
            "to continue. No files were changed."
        )

    # --- 4b. Copy-kind + new-in-target write path --------------------------------
    # Walk the surface entries for copy-kind wizard-delivery files. Foundation-doc
    # render files are already handled above (steps 4a); skip them here. Also skip
    # needs_capsule_upgrade (deferred to the capsule-upgrade task), dropped, and collision entries.
    #
    # For each copy-kind entry:
    #   - Read theirs from the frozen bundle template (NOT from live templates/).
    #   - Detect drift (live hash vs manifest base_content_hash / base_hash).
    #   - Apply merge_strategy (warn_on_drift / operator_review / three_way / frozen).
    #     Copy-kind files skip ONLY the replay-conformance gate (no operator-specific
    #     content to reproduce); all other transaction stages apply.
    #   - Track file mode from the contract (0755 for .sh, else 0644).
    #   - new-in-target: create additively; add to manifest.

    # staged_modes: relpath -> octal int — mode to apply at atomic-replace time.
    staged_modes: Dict[str, int] = {}
    # new_copy_manifest_entries: relpath -> manifest entry dict for newly created files.
    new_copy_manifest_entries: Dict[str, Dict[str, Any]] = {}

    # Build the contract entries map once for mode resolution.
    _contract_entries_map: Dict[str, Dict[str, Any]] = {}
    if target_contract:
        for _art in target_contract.get("artifacts", []):
            if _art.get("relpath"):
                _contract_entries_map[_art["relpath"]] = _art

    for se in surface:
        rel = se.relpath
        rk = se.render_kind
        strategy = se.merge_strategy
        cls = se.classification

        # Only process copy-kind wizard-delivery files on this path.
        if rk != RENDER_KIND_COPY:
            continue
        # Foundation-doc render files that happen to be copy-kind are handled above.
        if rel in foundation_entries:
            continue
        # Skipped classifications.
        if cls in (SURFACE_DROPPED, SURFACE_COLLISION, SURFACE_NEEDS_CAPSULE):
            continue
        # Only new + modified/unchanged (in-manifest) processed here.
        if cls not in (SURFACE_NEW, SURFACE_MODIFIED, SURFACE_UNCHANGED):
            continue
        # Control-plane-emitted entries (contract `source: control_plane`, no
        # `template_path`) are produced by the Python emitter at setup time, NOT from a
        # bundle template. They are not bundle-sourced and must never be read from the
        # bundle here — doing so fails closed on a missing template and refuses the WHOLE
        # upgrade (e.g. `.wizard/UPGRADING.md`). They are runtime control-plane files; the
        # copy-write path leaves them to the control plane and skips them.
        if _contract_entries_map.get(rel, {}).get("template_path") is None:
            continue

        # Read the frozen template (fail-closed; BundleTemplateError -> refusal).
        try:
            theirs_copy = read_bundle_template(target_version, rel, build_repo_root)
        except BundleTemplateError as e:
            raise UpgradeApplyError(
                f"cannot read the bundle template for {rel!r}: {e}. No files were changed."
            ) from e

        # Replay the emitter's deterministic target-hook injection over copy files that
        # are corpus hook targets (e.g. logs/audit_log.md carries the OP-06 hook). The
        # emitted file = template + injected hook region, so comparing the RAW template
        # against the hook-injected base would spuriously flag an unchanged file as
        # changed and route it to review. Non-hook-target copy files pass through
        # unchanged. (The same transform the render-kind path replays in
        # _render_operating_layer.)
        theirs_copy = _inject_hooks_for_copy_file(
            rel, theirs_copy, capsule, build_repo_root
        )

        # Resolve mode from the contract entry (default 0644).
        mode_str = str(_contract_entries_map.get(rel, {}).get("mode", "0644"))
        try:
            mode_int = int(mode_str, 8)
        except ValueError:
            mode_int = 0o644

        theirs_hash = "sha256:" + sha256_bytes(theirs_copy.encode("utf-8"))

        if cls == SURFACE_NEW:
            # Additive creation — no existing managed entry, no existing disk file.
            staged_writes[rel] = theirs_copy
            staged_modes[rel] = mode_int
            new_copy_manifest_entries[rel] = {
                "managed": "true",
                "managed_by": "shared",
                "base_hash": theirs_hash,
                "base_content_hash": theirs_hash,
                "current_hash_last_seen": theirs_hash,
                "local_modifications": "expected",
                "merge_strategy": strategy,
                "mode": mode_str,
                "render_kind": rk,
                "source_refs": [],
                "live_lineage_version": target_version,
            }
            decisions.append(FileDecision(rel, strategy, FILE_ADOPTED, False,
                                          note="new file in target; created additively"))
            continue

        # In-manifest copy-kind file: detect drift, apply strategy.
        files_block = manifest.get("managed_files") or manifest.get("files") or {}
        meta = files_block.get(rel, {})
        base_content_hash = str(meta.get("base_content_hash", "")) or str(meta.get("base_hash", ""))
        live = _read_live(operator_project_dir, rel)
        if live is None:
            # Managed copy file missing on disk — refuse (same as foundation docs).
            raise UpgradeApplyError(
                f"managed copy file {rel!r} is missing on disk; cannot apply an upgrade "
                "over a missing file. No files were changed."
            )
        live_hash = "sha256:" + sha256_bytes(live.encode("utf-8"))
        drifted = (live_hash != base_content_hash)
        target_changed = (theirs_hash != base_content_hash)

        if not target_changed:
            decisions.append(FileDecision(rel, strategy, FILE_UNCHANGED, drifted,
                                          note="target copy is identical to the installed version"))
            # Advance manifest base hashes even if content unchanged (lineage/version bump).
            new_copy_manifest_entries[rel] = dict(meta)
            new_copy_manifest_entries[rel]["base_hash"] = theirs_hash
            new_copy_manifest_entries[rel]["base_content_hash"] = theirs_hash
            new_copy_manifest_entries[rel]["live_lineage_version"] = target_version
            continue

        if strategy == MERGE_STRATEGY_FROZEN:
            if drifted:
                frozen_blocks.append(rel)
                continue
            staged_writes[rel] = theirs_copy
            staged_modes[rel] = mode_int
            decisions.append(FileDecision(rel, strategy, FILE_ADOPTED, drifted,
                                          note="frozen copy file, no operator edits; adopted the new version"))
        elif strategy == MERGE_STRATEGY_THREE_WAY:
            if not drifted:
                staged_writes[rel] = theirs_copy
                staged_modes[rel] = mode_int
                decisions.append(FileDecision(rel, strategy, FILE_ADOPTED, drifted,
                                              note="no operator edits; adopted the new version"))
            else:
                # Copy-kind files have no section-merge semantics; route drifted three_way
                # to the review sidecar (no text structure to auto-merge).
                review_writes.append((rel, live, theirs_copy, True))
                decisions.append(FileDecision(rel, strategy, FILE_REVIEW, drifted,
                                              note="you edited this file; your version was kept and the new version was saved for review"))
        elif strategy == MERGE_STRATEGY_OPERATOR_REVIEW:
            review_writes.append((rel, live, theirs_copy, False))
            decisions.append(FileDecision(rel, strategy, FILE_REVIEW, drifted,
                                          note="this file is operator-reviewed; the new version was saved for review and your version kept"))
        elif strategy == MERGE_STRATEGY_WARN_ON_DRIFT:
            if drifted and not ack:
                raise UpgradeApplyError(
                    f"{rel!r} has local edits and its upgrade rule requires you to "
                    "acknowledge replacing them. Re-run the upgrade with --ack to "
                    "adopt the new version (your current version is backed up first). "
                    "No files were changed."
                )
            staged_writes[rel] = theirs_copy
            staged_modes[rel] = mode_int
            decisions.append(FileDecision(rel, strategy, FILE_ADOPTED, drifted,
                                          note=("acknowledged; adopted the new version" if drifted
                                                else "no operator edits; adopted the new version")))
        else:
            raise UpgradeApplyError(
                f"{rel!r} has an unrecognized merge strategy {strategy!r}; refusing to "
                "apply rather than guess. No files were changed."
            )

        # For every completed in-manifest copy-kind branch (not frozen-blocked, not raised),
        # advance the manifest base_hash + base_content_hash + lineage to the target. The
        # current_hash_last_seen advances only for adopted files (via staged_writes check in
        # _recompute_manifest). Routed files keep their prior merge-ancestor pointer.
        copy_entry_update: Dict[str, Any] = dict(meta)
        copy_entry_update["base_hash"] = theirs_hash
        copy_entry_update["base_content_hash"] = theirs_hash
        if rel not in {d.relpath for d in decisions if d.disposition == FILE_REVIEW}:
            copy_entry_update[LIVE_LINEAGE_VERSION_FIELD] = target_version
        new_copy_manifest_entries[rel] = copy_entry_update

    # Re-check frozen_blocks in case copy-kind files added to it.
    if frozen_blocks:
        raise UpgradeApplyError(
            "this upgrade is blocked because protected file(s) have local edits: "
            f"{', '.join(sorted(frozen_blocks))}. These files are not meant to be edited "
            "and cannot be upgraded while they differ from their original. Restore them "
            "to continue. No files were changed."
        )

    # --- 4c. Operating-layer render-kind files (already managed) -------------
    # These are `render_kind="render"` files whose content is built from capsule inputs
    # (not from the foundation-doc render surface) and that are ALREADY tracked in the
    # manifest. Examples: CLAUDE.md, operating_discipline.md, project_instructions.md,
    # per-agent prompt files. They are NOT in foundation_entries (render_foundation_docs
    # only produces the 6 classic foundation docs), so the step-4a loop skips them.
    # They are NOT copy-kind, so the step-4b loop skips them.
    #
    # Render "theirs" by substituting the capsule's operating block inputs into the
    # frozen target-bundle template:
    #   - `operating.resolved_scaffold_inputs` covers root-level files
    #     (CLAUDE.md, operating_discipline.md, etc.) — combined with
    #     `foundation_doc_inputs` (PROJECT_NAME etc.) into one lookup dict.
    #   - `operating.by_relpath[rel]` covers per-agent render files (if present).
    # Capsule must be v2 (operating_replay_ok); if not, the surface already marks these
    # as SURFACE_NEEDS_CAPSULE and they never appear as in-manifest here.
    #
    # Merge strategy applied identically to the foundation-doc three_way path:
    #   three_way + no drift      -> adopt theirs
    #   three_way + drift + elig  -> section_merge; clean -> FILE_MERGED; conflict -> sidecar
    #   three_way + drift + inelig -> sidecar
    #   operator_review           -> always sidecar
    #   warn_on_drift             -> ack-or-refuse
    #   frozen                    -> block on drift; adopt clean

    # Canonical operating-layer render (closes the delivery gap). The capsule stores only
    # PERSISTED inputs; the DERIVED inputs (scaffold defaults, corpus inherited-principles
    # block, autonomy-derived actions, resolved model tiers, rules-library body) are
    # re-derived from the TARGET bundle and the persisted inputs overlaid, then the bundle's
    # target-hook injection post-pass is replayed. The earlier capsule-only substitution
    # left DERIVED placeholders unresolved and refused the whole upgrade.
    # (project_name computed at step 2b — the structural PROJECT_NAME the emitter used.)
    files_block_ol = manifest.get("managed_files") or manifest.get("files") or {}
    # Track manifest entry updates for operating-layer render files.
    new_ol_manifest_entries: Dict[str, Dict[str, Any]] = {}

    # Eligible operating-layer render relpaths: render-kind, not a classic foundation doc,
    # already managed, and surviving (not dropped/collision/needs-capsule).
    ol_relpaths = [
        se.relpath for se in surface
        if se.render_kind == RENDER_KIND_RENDER
        and se.relpath not in foundation_entries
        and se.in_manifest
        and se.classification not in (SURFACE_DROPPED, SURFACE_COLLISION, SURFACE_NEEDS_CAPSULE)
    ]
    theirs_ol_map = _render_operating_layer(
        target_version, ol_relpaths,
        capsule=capsule, capsule_inputs=capsule_inputs,
        project_name=project_name, build_repo_root=build_repo_root,
    ) if ol_relpaths else {}
    # Base = the CURRENT-version render of the SAME files (same canonical assembly). The
    # section-aware 3-way merge for a drifted three_way file needs this as its merge base;
    # the replay-conformance gate (step 2b operating leg) verified it reproduces the manifest
    # base_hash, so it is a trustworthy merge ancestor.
    base_ol_map = _render_operating_layer(
        current_version, ol_relpaths,
        capsule=capsule, capsule_inputs=capsule_inputs,
        project_name=project_name, build_repo_root=build_repo_root,
    ) if ol_relpaths else {}

    for se in surface:
        rel = se.relpath
        rk = se.render_kind
        strategy = se.merge_strategy
        cls = se.classification

        # Only render-kind operating-layer files not in foundation_entries.
        if rk != RENDER_KIND_RENDER:
            continue
        if rel in foundation_entries:
            continue
        # Skip non-managed / non-surviving surface entries (new files are a
        # separate follow-on task; needs_capsule / dropped / collision are no-ops here).
        if not se.in_manifest:
            continue
        if cls in (SURFACE_DROPPED, SURFACE_COLLISION, SURFACE_NEEDS_CAPSULE):
            continue

        theirs_ol = theirs_ol_map[rel]

        # Read the live file.
        live_ol = _read_live(operator_project_dir, rel)
        if live_ol is None:
            raise UpgradeApplyError(
                f"managed operating-layer file {rel!r} is missing on disk; cannot "
                "apply an upgrade over a missing file. No files were changed."
            )

        # Drift detection uses content hashes (same as the foundation-doc path).
        meta_ol = files_block_ol.get(rel, {})
        base_content_ol = str(meta_ol.get("base_content_hash", "")) or \
                          str(meta_ol.get("base_hash", ""))
        ours_content_ol = _content_hash(live_ol)
        drifted_ol = (ours_content_ol != base_content_ol)
        theirs_content_ol = _content_hash(theirs_ol)
        target_changed_ol = (theirs_content_ol != base_content_ol)

        if not target_changed_ol:
            decisions.append(FileDecision(rel, strategy, FILE_UNCHANGED, drifted_ol,
                                          note="target version is identical to the installed version"))
            # Advance lineage even for content-unchanged files.
            upd = dict(meta_ol)
            upd["live_lineage_version"] = target_version
            new_ol_manifest_entries[rel] = upd
            continue

        if strategy == MERGE_STRATEGY_FROZEN:
            if drifted_ol:
                frozen_blocks.append(rel)
                continue
            staged_writes[rel] = theirs_ol
            decisions.append(FileDecision(rel, strategy, FILE_ADOPTED, drifted_ol,
                                          note="frozen file, no operator edits; adopted the new version"))
        elif strategy == MERGE_STRATEGY_THREE_WAY:
            if not drifted_ol:
                staged_writes[rel] = theirs_ol
                decisions.append(FileDecision(rel, strategy, FILE_ADOPTED, drifted_ol,
                                              note="no operator edits; adopted the new version"))
            else:
                # Section-aware merge: same logic as the foundation-doc three_way path.
                # Base = the canonical CURRENT-version render (same full input assembly as
                # theirs), which the conformance gate verified reproduces the recorded
                # base_hash — a trustworthy merge ancestor. Fall back to live (no-op merge
                # base -> sidecar) only if the file was not renderable at the base version.
                base_ol_rendered = base_ol_map.get(rel, live_ol)

                eligible = str(meta_ol.get(LIVE_LINEAGE_VERSION_FIELD, "")) == current_version
                merge = (section_three_way_merge(base_ol_rendered, live_ol, theirs_ol)
                         if (eligible and auto_merge_enabled) else None)
                if merge is not None and merge.clean:
                    staged_writes[rel] = merge.merged
                    decisions.append(FileDecision(rel, strategy, FILE_MERGED, drifted_ol,
                                                  note="your edits were merged with the new version"))
                else:
                    if merge is not None and not merge.clean:
                        note = ("your edits overlap with the new version, so they could not "
                                "be merged automatically; your version was kept and the new "
                                "version was saved for review")
                    else:
                        note = ("you edited this file; your version was kept and the new "
                                "version was saved for review")
                    review_writes.append((rel, live_ol, theirs_ol, True))
                    decisions.append(FileDecision(rel, strategy, FILE_REVIEW, drifted_ol, note=note))
        elif strategy == MERGE_STRATEGY_OPERATOR_REVIEW:
            review_writes.append((rel, live_ol, theirs_ol, False))
            decisions.append(FileDecision(rel, strategy, FILE_REVIEW, drifted_ol,
                                          note="this file is operator-reviewed; the new version was saved for review and your version kept"))
        elif strategy == MERGE_STRATEGY_WARN_ON_DRIFT:
            if drifted_ol and not ack:
                raise UpgradeApplyError(
                    f"{rel!r} has local edits and its upgrade rule requires you to "
                    "acknowledge replacing them. Re-run the upgrade with --ack to "
                    "adopt the new version (your current version is backed up first). "
                    "No files were changed."
                )
            staged_writes[rel] = theirs_ol
            decisions.append(FileDecision(rel, strategy, FILE_ADOPTED, drifted_ol,
                                          note=("acknowledged; adopted the new version" if drifted_ol
                                                else "no operator edits; adopted the new version")))
        else:
            raise UpgradeApplyError(
                f"{rel!r} has an unrecognized merge strategy {strategy!r}; refusing to "
                "apply rather than guess. No files were changed."
            )

        # Advance manifest base hashes for this operating-layer file.
        theirs_hash_ol = "sha256:" + sha256_bytes(theirs_ol.encode("utf-8"))
        ol_entry_update: Dict[str, Any] = dict(meta_ol)
        ol_entry_update["base_hash"] = theirs_hash_ol
        ol_entry_update["base_content_hash"] = theirs_content_ol
        if rel in staged_writes:
            ol_entry_update["current_hash_last_seen"] = "sha256:" + sha256_bytes(
                staged_writes[rel].encode("utf-8")
            )
        if rel not in {d.relpath for d in decisions if d.disposition == FILE_REVIEW}:
            ol_entry_update[LIVE_LINEAGE_VERSION_FIELD] = target_version
        new_ol_manifest_entries[rel] = ol_entry_update

    # Final frozen-blocks check (operating-layer files may have added to it).
    if frozen_blocks:
        raise UpgradeApplyError(
            "this upgrade is blocked because protected file(s) have local edits: "
            f"{', '.join(sorted(frozen_blocks))}. These files are not meant to be edited "
            "and cannot be upgraded while they differ from their original. Restore them "
            "to continue. No files were changed."
        )

    # --- 5. Transaction: backup -> stage -> validate -> atomic replace --------
    touched_relpaths = sorted(set(staged_writes) | {MANIFEST_REL, UPGRADE_HISTORY_REL})
    backup_dir = ""
    if backup:
        backup_dir = str(_snapshot_backup(operator_project_dir, target_version,
                                          sorted(staged_writes)))

    # Stage all content writes + the new manifest + the history line into a temp dir,
    # then re-hash to confirm the staged bytes are exactly what we intend.
    import tempfile
    review_paths_written: List[str] = []
    try:
        with tempfile.TemporaryDirectory() as td:
            staging = Path(td)
            for rel, content in staged_writes.items():
                sp = staging / rel
                sp.parent.mkdir(parents=True, exist_ok=True)
                sp.write_text(content, encoding="utf-8")

            routed_relpaths = {d.relpath for d in decisions if d.disposition == FILE_REVIEW}
            new_manifest = _recompute_manifest(
                manifest, target_entry, target_version, staged_writes,
                foundation_entries, target_generator_version,
                theirs_rendered=theirs_rendered,
                routed_relpaths=routed_relpaths,
                new_copy_entries=new_copy_manifest_entries,
                new_ol_entries=new_ol_manifest_entries,
                target_contract_by_relpath={
                    e["relpath"]: e for e in (target_contract or {}).get("artifacts", [])
                    if e.get("delivery") == "wizard" and e.get("relpath")
                },
            )
            sm = staging / MANIFEST_REL
            sm.parent.mkdir(parents=True, exist_ok=True)
            sm.write_text(json.dumps(new_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            history_line = (
                f"{current_version} -> {target_version} "
                f"class={migration.get('class', 'unknown')} "
                f"applied={len(staged_writes)} review={len(review_writes)}\n"
            )

            # Post-validation: re-hash each staged content file == intended theirs hash.
            for rel, content in staged_writes.items():
                want = "sha256:" + sha256_bytes(content.encode("utf-8"))
                got = "sha256:" + sha256_file(staging / rel)
                if want != got:
                    raise UpgradeApplyError(
                        f"staged-validation failed for {rel!r} (the file written to the "
                        "staging area did not match what was intended). Rolling back; no "
                        "files were changed."
                    )

            # Stage the review sidecars into the temp tree too (hardening, design §5): a
            # sidecar write failure then happens in staging, never in the live tree. The
            # staged review dir mirrors the operator layout, so the returned relpaths are
            # the live relpaths to os.replace into place during commit.
            staging_review_dir = staging / UPGRADE_REVIEW_DIR_REL / upgrade_id
            review_rel_paths: List[str] = []
            for rel, ours, theirs, overlay in review_writes:
                review_rel_paths.extend(
                    _write_review_sidecar(staging_review_dir, rel, ours, theirs, overlay_note=overlay)
                )

            # All staged + validated. Commit: per-file atomic os.replace of content +
            # sidecars + manifest, then append history. Any OSError here triggers the
            # broadened rollback below.
            for rel in staged_writes:
                _atomic_replace(staging / rel, operator_project_dir / rel)
                if rel in staged_modes:
                    os.chmod(operator_project_dir / rel, staged_modes[rel])
            for rrel in review_rel_paths:
                _atomic_replace(staging / rrel, operator_project_dir / rrel)
                review_paths_written.append(rrel)
            _atomic_replace(staging / MANIFEST_REL, manifest_path)

            hist = operator_project_dir / UPGRADE_HISTORY_REL
            with hist.open("a", encoding="utf-8") as f:
                f.write(history_line)

    except (UpgradeApplyError, OSError) as e:
        if backup and backup_dir:
            _restore_backup(operator_project_dir, Path(backup_dir),
                            sorted(staged_writes))
        # Remove any review sidecars committed before the failure — they did not exist
        # before this upgrade and are not part of the backup snapshot.
        live_review = operator_project_dir / UPGRADE_REVIEW_DIR_REL / upgrade_id
        if live_review.exists():
            shutil.rmtree(live_review, ignore_errors=True)
        review_parent = operator_project_dir / UPGRADE_REVIEW_DIR_REL
        if review_parent.exists() and not any(review_parent.iterdir()):
            shutil.rmtree(review_parent, ignore_errors=True)
        if isinstance(e, UpgradeApplyError):
            raise
        raise UpgradeApplyError(
            f"the upgrade could not be completed due to a filesystem error: {e}. Your "
            "files were restored from the pre-upgrade backup; no changes were kept."
        ) from e

    # --- 6. Classify ----------------------------------------------------------
    files_written = sorted(staged_writes)
    files_in_review = sorted(d.relpath for d in decisions if d.disposition == FILE_REVIEW)
    files_merged = sorted(d.relpath for d in decisions if d.disposition == FILE_MERGED)
    # A `needs_capsule_upgrade` surface entry is a target file the upgrade COULD NOT
    # deliver (a render-kind operating-layer file whose replay needs an operating block
    # this system's v1 capsule does not carry). It is surfaced, not written. Reporting
    # `applied` while such files went undelivered is a false-green: the operator would
    # believe the whole new version landed. Treat any undelivered surface entry the same
    # as a routed file -> partial. (Collisions are likewise undelivered.)
    undelivered = [
        se.relpath for se in surface
        if se.classification in (SURFACE_NEEDS_CAPSULE, SURFACE_COLLISION)
    ]
    classification = (
        APPLY_RESULT_PARTIAL if (files_in_review or undelivered) else APPLY_RESULT_APPLIED
    )

    return UpgradeApplyResult(
        operator_project_path=str(operator_project_dir),
        from_version=current_version,
        to_version=target_version,
        classification=classification,
        decisions=decisions,
        backup_dir=backup_dir,
        upgrade_id=upgrade_id,
        files_written=files_written,
        files_in_review=files_in_review,
        files_merged=files_merged,
        surface=surface,
    )


def render_apply_result(result: UpgradeApplyResult) -> str:
    """Human-readable CLI output for a completed apply (plain language for a
    non-technical operator)."""
    lines = [
        "Foundation upgrade applied",
        f"  project:      {result.operator_project_path}",
        f"  from version: {result.from_version}",
        f"  to version:   {result.to_version}",
        f"  result:       {result.classification}",
    ]
    if result.backup_dir:
        lines.append(f"  backup:       {result.backup_dir}")
    lines.append("")
    merged_set = set(result.files_merged)
    adopted = [rel for rel in result.files_written if rel not in merged_set]
    if adopted:
        lines.append("Updated to the new version:")
        for rel in adopted:
            lines.append(f"  - {rel}")
    if result.files_merged:
        if adopted:
            lines.append("")
        lines.append("Merged your edits with the new version (your changes were kept "
                     "and the new wording added around them):")
        for rel in result.files_merged:
            lines.append(f"  - {rel}")
    if result.files_in_review:
        lines.append("")
        lines.append(
            "Kept your version (the new version was saved for you to review under "
            f".wizard/upgrade-review/{result.upgrade_id}/):"
        )
        for rel in result.files_in_review:
            lines.append(f"  - {rel}  (see {rel}.new and {rel}.diff)")
        lines.append("")
        lines.append(
            "Nothing in the review folder is applied automatically. Open each .diff "
            "to see what changed, then copy anything you want into your own file by hand."
        )
    if not result.files_written and not result.files_in_review:
        lines.append("No files needed changing for this version.")
    return "\n".join(lines) + "\n"


def _auto_merge_enabled(migration: Dict[str, Any], current_version: str, target_version: str) -> bool:
    """Whether the section-aware text-merge driver may auto-merge drifted three_way docs
    for this release.

    An explicit migration `auto_merge` flag wins (a release can force sidecar-only with
    `auto_merge: false`, or force merging on with `auto_merge: true`). With no explicit
    flag, the default is ON for minor/patch releases and OFF for major-breaking releases —
    a major/structural release may rename/reorder/rewrite sections, where a section-keyed
    merge could silently combine content across a structural change; routing theirs to the
    review sidecar is the safe default there. The operator can still hand-apply from the
    sidecar."""
    flag = migration.get("auto_merge")
    if isinstance(flag, bool):
        return flag
    return classify_tier(current_version, target_version) != TIER_MAJOR_BREAKING


def _atomic_replace(src: Path, dest: Path) -> None:
    """Atomic per-file install from staging into the live tree."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(str(src), str(dest))


def _read_target_generator_version(build_repo_root: Path, target_entry: Dict[str, Any]) -> Optional[str]:
    """Read the target bundle's generator_version from its provenance sidecar (the
    canonical source the original manifest's generator_version came from — not
    re-derived). Returns None if the sidecar is absent or carries no value (the
    manifest then keeps its existing generator_version)."""
    bundle_dir = (build_repo_root / target_entry.get("path", "")).resolve()
    prov = bundle_dir / "foundation-bundle.provenance.json"
    if not prov.exists():
        return None
    try:
        data = json.loads(prov.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    gv = data.get("generator_version")
    return gv if isinstance(gv, str) and gv else None


def _recompute_manifest(
    manifest: Dict[str, Any],
    target_entry: Dict[str, Any],
    target_version: str,
    staged_writes: Dict[str, str],
    foundation_entries: Dict[str, Dict[str, Any]],
    target_generator_version: Optional[str],
    *,
    theirs_rendered: Dict[str, str],
    routed_relpaths: Optional[set] = None,
    new_copy_entries: Optional[Dict[str, Dict[str, Any]]] = None,
    new_ol_entries: Optional[Dict[str, Dict[str, Any]]] = None,
    target_contract_by_relpath: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return a NEW manifest dict reflecting the apply (Finding A dual-hash fix).

    - bump foundation_bundle_version + generator_version (+ source_commit) to the
      target bundle's provenance.
    - DROPPED file (a managed foundation doc absent from theirs_rendered, i.e. the
      target no longer renders it): POP it from managed_files. Leaving it stale would
      fail the NEXT replay-conformance gate on "not produced by the current render
      surface".
    - SURVIVING file (still rendered by the target): advance BOTH base_hash (full
      canonical render) AND base_content_hash (content-normalized) to the TARGET
      render — for EVERY managed foundation doc (adopted, routed, AND
      content-unchanged). This is what un-sticks the upgrade chain: the
      replay-conformance gate verifies the capsule+generator reproduce the recorded
      canonical bytes at current_version, not that the live file equals canonical, so
      advancing routed files is correct.
    - current_hash_last_seen advances ONLY for cleanly written files (staged_writes —
      adopted OR section-merged), preserving the true merge-ancestor pointer for
      routed/unchanged files.
    - live_lineage_version: advances to the target for every surviving file
      EXCEPT those routed to the review sidecar. A routed file keeps its prior lineage
      so it stays ineligible (keeps routing) until the operator reconciles it — its live
      content does NOT descend from render(target). Adopted / merged / content-unchanged
      live content DOES descend from render(target), so its lineage advances.
    """
    routed = routed_relpaths or set()
    new_manifest = json.loads(json.dumps(manifest))  # deep copy, JSON-clean
    new_manifest["foundation_bundle_version"] = target_version
    if target_entry.get("source_commit"):
        new_manifest["source_commit"] = target_entry["source_commit"]
    if target_generator_version:
        new_manifest["generator_version"] = target_generator_version
    files_block = new_manifest.get("managed_files")
    if not isinstance(files_block, dict):
        files_block = new_manifest.get("files")

    for rel in list(foundation_entries.keys()):
        target_text = theirs_rendered.get(rel)
        if target_text is None:
            # Dropped from the target's render surface — no longer managed.
            files_block.pop(rel, None)
            continue
        entry = files_block.get(rel, {})
        entry["base_hash"] = "sha256:" + sha256_bytes(target_text.encode("utf-8"))
        entry["base_content_hash"] = _content_hash(target_text)
        if rel in staged_writes:
            # Cleanly written (adopted or section-merged): the live file now equals the
            # staged bytes; advance the merge-ancestor pointer to what we actually wrote
            # (== target render for adopted; == merged content for a clean merge).
            entry["current_hash_last_seen"] = "sha256:" + sha256_bytes(
                staged_writes[rel].encode("utf-8")
            )
        if rel not in routed:
            # Live content descends from render(target) (adopted / merged / unchanged) —
            # restore lineage to current so a future drift is merge-eligible. A routed
            # file keeps its prior lineage (left absent if it had none) and stays
            # ineligible until reconciled.
            entry[LIVE_LINEAGE_VERSION_FIELD] = target_version
        files_block[rel] = entry

    # Copy-kind + new-in-target file entries: merge advanced entries for existing managed
    # copy files (base_hash / base_content_hash / lineage) and add new-file entries.
    if new_copy_entries:
        for rel, entry in new_copy_entries.items():
            existing = files_block.get(rel)
            if existing is not None:
                # Already-managed copy file: update hashes + lineage, preserve other fields.
                merged = dict(existing)
                merged.update(entry)
                files_block[rel] = merged
            else:
                # Genuinely new file: add the full entry.
                files_block[rel] = dict(entry)

    # Operating-layer render-kind entries (step 4c): advance base hashes + lineage.
    # Same semantics as copy-kind — all already-managed files; no new-file creation here
    # (that is a separate follow-on task for SURFACE_NEW render-kind operating files).
    if new_ol_entries:
        for rel, entry in new_ol_entries.items():
            existing = files_block.get(rel)
            if existing is not None:
                updated = dict(existing)
                updated.update(entry)
                files_block[rel] = updated
            else:
                files_block[rel] = dict(entry)

    # Fork 1(c) hygiene: refresh merge_strategy for every surviving managed file from the
    # TARGET contract (same target-contract precedence the apply + plan resolve with), so a
    # stale manifest value (e.g. an older emit's warn_on_drift on a file later reclassified
    # operator_review) does not persist past the upgrade and keep mislabeling the file.
    # Files absent from the target contract keep their recorded strategy.
    if target_contract_by_relpath and isinstance(files_block, dict):
        for rel, entry in files_block.items():
            if isinstance(entry, dict):
                entry["merge_strategy"] = resolve_merge_strategy(
                    target_contract_by_relpath.get(rel), entry.get("merge_strategy", ""))

    return new_manifest
