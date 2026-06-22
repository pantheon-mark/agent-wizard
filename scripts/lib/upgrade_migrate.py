"""Pre-v2 upgrade MIGRATION preflight — reconcile a manually-patched operator system
so a subsequent normal `apply_upgrade` runs safely.

THE SAFETY HOLE THIS CLOSES (codex C5 / gemini G-C). A system can receive a newer
operating layer by a MANUAL, additive apply AFTER its original foundation-only emit
(the estate received its operating-layer files this way). When that happens the
project's `.wizard/manifest.json` does NOT correctly track those operating-layer files:
either there is no managed_files entry at all (the manually-dropped file), or the entry
carries a stale foundation-era base_hash / a stale `live_lineage_version`. If the normal
upgrade ran in that state it could not distinguish OUR known wizard payload from an
OPERATOR edit — it would either mis-baseline (silently adopt over the operator's edits)
or sidecar everything. A tested preflight migration must reconcile manifest + capsule
FIRST, before `apply_upgrade`.

WHAT THE PREFLIGHT DOES (general; not estate-specific):

  1. Baseline reconciliation (per managed operating-layer `render_kind:render` file the
     `source_version` bundle carries):
       - Compute the KNOWN wizard payload = the operating-layer file rendered at
         `source_version` (the version the manual layer came from) via the CANONICAL
         operating-layer render (`upgrade_apply._render_operating_layer`, which itself
         uses `bundle_templates.derive_scaffold_render_inputs`) against the operator's
         resolved inputs in the (reconciled) v2 capsule.
       - live == known payload  -> ADOPT the correct base_hash + base_content_hash AND
         advance `live_lineage_version` to `source_version`, WITHOUT changing live bytes.
         (gemini G-C: lineage MUST advance, or every future drifted-three_way merge stays
         permanently disabled by the lineage guard.)
       - manifest base already == live (already reconciled) -> LEAVE untouched (idempotent).
       - live != known payload  -> OPERATOR DRIFT: do NOT rewrite the baseline. Preserve the
         operator's edit signal so the normal upgrade routes it to review rather than
         clobbering it.
       - file absent on disk      -> create ONLY if it is additive (not already managed) AND
         collision-free (no unmanaged file already there). Otherwise leave it alone.

  2. Capsule upgrade v1 -> v2. A pre-operating-layer system carries a v1 capsule
     (foundation_doc_inputs only); it cannot replay the operating layer (no operating
     block). Regenerate a v2 capsule from the operator's preserved transcript (reusing the
     real emit pipeline, which builds the v2 `operating` block) and adopt it.

  3. Idempotent + fail-closed. A second run is a no-op. If a file cannot be reconciled
     safely it is LEFT as operator-drift (never silently rewritten). The preflight performs
     NO content writes to managed operating-layer files — it only adjusts manifest metadata
     and replaces the capsule.

Stdlib-only, pip-install-free (operator/runtime path) EXCEPT the capsule-regeneration leg,
which re-runs the wizard emit pipeline (the same code the wizard ships) into a throwaway
temp dir and lifts the resulting v2 capsule. No live bytes of the operator system are ever
written by capsule regeneration — the temp emit is discarded.
"""

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from bundle_templates import bundle_has_operating_layer  # type: ignore
from replay_capsule import (  # type: ignore
    REPLAY_CAPSULE_REL,
    capsule_supports_operating_replay,
)
from upgrade import sha256_bytes, normalize_for_content_hash  # type: ignore
from upgrade_apply import (  # type: ignore
    UpgradeApplyError,
    RENDER_KIND_RENDER,
    RENDER_KIND_COPY,
    CONTRACT_BASENAME,
    LIVE_LINEAGE_VERSION_FIELD,
    _render_operating_layer,
    _inject_hooks_for_copy_file,
    _manifest_managed_relpaths,
)
from bundle_templates import read_bundle_template, BundleTemplateError  # type: ignore

MANIFEST_REL = ".wizard/manifest.json"

# Volatile per-build globals the emit pipeline stamps at emit time from the clock + the
# bundle version (see interview_cli.cmd_emit_system auto_values). On a capsule REGENERATION
# these would otherwise be RE-stamped with the regeneration-time date + version, so the
# regenerated foundation_doc_inputs would render foundation docs that no longer reproduce
# the manifest's recorded base_hashes (the replay-conformance foundation leg false-fails).
# The migration carries the ORIGINAL build's values forward from the system's existing
# capsule instead, so a regeneration on any later date reproduces what was first emitted.
_VOLATILE_BUILD_INPUT_KEYS = ("LAST_UPDATED_DATE", "MANUAL_LAST_UPDATED", "WIZARD_VERSION")


# Per-file reconciliation dispositions.
MIGRATE_RECONCILED = "reconciled"          # adopted base_hash + advanced lineage; bytes unchanged
MIGRATE_ALREADY = "already_reconciled"      # manifest base already == live; left untouched
MIGRATE_OPERATOR_DRIFT = "operator_drift"   # live != known payload; baseline NOT rewritten
MIGRATE_CREATED = "created"                # absent + additive + collision-free; created from known payload
MIGRATE_ABSENT_SKIPPED = "absent_skipped"   # absent but not safely creatable; left alone
MIGRATE_COLLISION = "collision"            # absent in manifest but an unmanaged file exists; left alone


@dataclass
class FileReconcileDecision:
    relpath: str
    disposition: str
    note: str = ""


@dataclass
class MigrateResult:
    operator_project_path: str
    source_version: str
    decisions: List[FileReconcileDecision] = field(default_factory=list)
    capsule_upgraded_to_v2: bool = False
    manifest_changed: bool = False
    capsule_changed: bool = False
    noop: bool = False

    @property
    def reconciled(self) -> List[str]:
        return sorted(d.relpath for d in self.decisions if d.disposition == MIGRATE_RECONCILED)

    @property
    def operator_drift(self) -> List[str]:
        return sorted(d.relpath for d in self.decisions if d.disposition == MIGRATE_OPERATOR_DRIFT)

    @property
    def created(self) -> List[str]:
        return sorted(d.relpath for d in self.decisions if d.disposition == MIGRATE_CREATED)


def _content_hash(text: str) -> str:
    return "sha256:" + sha256_bytes(normalize_for_content_hash(text).encode("utf-8"))


def _full_hash(text: str) -> str:
    return "sha256:" + sha256_bytes(text.encode("utf-8"))


def _operating_render_relpaths_for(source_version: str, build_repo_root: Path) -> List[str]:
    """The operating-layer `render_kind:render` relpaths the `source_version` bundle
    carries (delivery == wizard). Empty if the bundle has no contract (foundation-only)."""
    contract_path = (build_repo_root / "wizard" / "foundation-bundles"
                     / source_version / CONTRACT_BASENAME)
    if not contract_path.is_file():
        return []
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    rels: List[str] = []
    for entry in contract.get("artifacts", []):
        if entry.get("delivery") == "wizard" and entry.get("render_kind") == RENDER_KIND_RENDER:
            rel = entry.get("relpath")
            if rel:
                rels.append(rel)
    return sorted(rels)


def _operating_copy_entries_for(source_version: str, build_repo_root: Path) -> Dict[str, Dict[str, Any]]:
    """The operating-layer `render_kind:copy` entries the `source_version` bundle carries
    that are bundle-sourced (delivery == wizard AND a real `template_path`). Returns
    {relpath: contract_entry}. Control-plane-emitted copy entries (no template_path, e.g.
    `.wizard/UPGRADING.md`) are excluded — they are upgrade-machinery, produced by the
    Python emitter, not adoptable from a frozen template. Empty if the bundle is
    foundation-only (no contract)."""
    contract_path = (build_repo_root / "wizard" / "foundation-bundles"
                     / source_version / CONTRACT_BASENAME)
    if not contract_path.is_file():
        return {}
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    out: Dict[str, Dict[str, Any]] = {}
    for entry in contract.get("artifacts", []):
        if (entry.get("delivery") == "wizard"
                and entry.get("render_kind") == RENDER_KIND_COPY
                and entry.get("template_path") is not None):
            rel = entry.get("relpath")
            if rel:
                out[rel] = entry
    return out


def _known_copy_payload(
    source_version: str, relpath: str, capsule: Dict[str, Any], build_repo_root: Path
) -> str:
    """The KNOWN wizard payload for a copy-kind operating-layer file = the verbatim
    `source_version` bundle template bytes (NO render), with the emitter's deterministic
    target-hook injection replayed (a no-op for non-hook-target files). This is exactly
    what apply_upgrade compares against for a copy file, so an adopted copy baseline is
    what a subsequent upgrade reproduces."""
    raw = read_bundle_template(source_version, relpath, build_repo_root)
    return _inject_hooks_for_copy_file(relpath, raw, capsule, build_repo_root)


def build_v2_capsule_from_transcript(
    transcript_path: Path,
    source_version: str,
    build_repo_root: Path,
    *,
    system_shape: str,
    project_name: str,
    generator_version_override: Optional[str] = None,
    preserve_volatile_from: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Regenerate a v2 replay capsule (carrying the `operating` block) from the operator's
    preserved transcript, by re-running the real wizard emit pipeline into a THROWAWAY temp
    dir and lifting the emitted `.wizard/replay-capsule.json`. NOTHING is written to the
    operator project here.

    The emitted system is full (not foundation-only) at `source_version`, so its capsule is
    schema v2 with the resolved operating inputs the operating-layer render needs. Fail-closed:
    if the emit does not produce a v2 capsule, raise (a v1 result would leave the operating
    layer un-replayable and is never silently accepted).

    `preserve_volatile_from` (the ORIGINAL build's foundation_doc_inputs): the emit pipeline
    re-stamps the per-build volatile globals (the build date + the bundle version) at
    regeneration time. Those render into the foundation docs, so a regeneration on a later
    date / a different bundle version would no longer reproduce the manifest's recorded
    foundation base_hashes. We overlay the ORIGINAL values for `_VOLATILE_BUILD_INPUT_KEYS`
    back into the regenerated foundation_doc_inputs, so the regenerated capsule reproduces
    exactly what was first emitted regardless of when the regeneration runs."""
    import sys
    scripts_dir = build_repo_root / "wizard" / "scripts"
    for p in (str(scripts_dir / "lib"), str(scripts_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import interview_cli as cli  # type: ignore

    if not bundle_has_operating_layer(source_version, build_repo_root):
        raise UpgradeApplyError(
            f"source version {source_version!r} carries no operating layer, so a v2 capsule "
            "cannot be regenerated from it. Choose the bundle version the manual operating "
            "layer came from."
        )

    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "capsule-regen"
        cli.cmd_emit_system(
            str(transcript_path), system_shape, str(proj), str(build_repo_root),
            project_name=project_name,
            bundle_version=source_version,
            generator_version_override=generator_version_override,
        )
        cap_path = proj / REPLAY_CAPSULE_REL
        if not cap_path.exists():
            raise UpgradeApplyError(
                "capsule regeneration emitted no replay capsule; cannot upgrade the setup "
                "record. No files were changed."
            )
        capsule = json.loads(cap_path.read_text(encoding="utf-8"))
    if not capsule_supports_operating_replay(capsule):
        raise UpgradeApplyError(
            "capsule regeneration did not produce a v2 (operating-layer) capsule; the "
            f"source version {source_version!r} emit must carry an operating block. No files "
            "were changed."
        )

    # Carry the ORIGINAL build's volatile globals forward (date + version) so the
    # regenerated capsule reproduces the recorded foundation base_hashes regardless of the
    # regeneration date / target bundle version. Only keys the original actually carried are
    # overlaid (a missing key is left as the regeneration emitted it).
    if preserve_volatile_from:
        regen_fdi = capsule.get("foundation_doc_inputs")
        if isinstance(regen_fdi, dict):
            for k in _VOLATILE_BUILD_INPUT_KEYS:
                if k in preserve_volatile_from:
                    regen_fdi[k] = preserve_volatile_from[k]
    return capsule


def migrate_pre_v2_system(
    operator_project_dir: Path,
    source_version: str,
    build_repo_root: Path,
    *,
    transcript_path: Path,
    system_shape: str,
    project_name: str,
    generator_version_override: Optional[str] = None,
    capsule: Optional[Dict[str, Any]] = None,
    write: bool = True,
) -> MigrateResult:
    """Run the pre-v2 migration preflight on `operator_project_dir`. See module docstring.

    `source_version` is the bundle version the MANUAL operating layer came from (the version
    whose render is the KNOWN wizard payload, e.g. v0.6.0 for the estate). `capsule` may be a
    pre-built v2 capsule (test seam); otherwise it is regenerated from the transcript.

    When `write` is True the reconciled manifest + the v2 capsule are written into the project.
    When False, nothing is written (the result still reports the decisions that WOULD be made) —
    used by the idempotence check and by tests that operate on a copy.

    Reconciliation NEVER writes managed operating-layer file bytes; it only adjusts manifest
    metadata and (for the one safely-creatable absent-additive case) creates a missing file
    from its known payload. Fail-closed: a file that cannot be reconciled safely is left as
    operator-drift.
    """
    operator_project_dir = Path(operator_project_dir)
    manifest_path = operator_project_dir / MANIFEST_REL
    if not manifest_path.exists():
        raise UpgradeApplyError(
            f"no manifest at {manifest_path}; cannot run the pre-v2 migration."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # --- 1. Capsule v1 -> v2 -------------------------------------------------
    existing_capsule_path = operator_project_dir / REPLAY_CAPSULE_REL
    existing_capsule: Optional[Dict[str, Any]] = None
    if existing_capsule_path.exists():
        existing_capsule = json.loads(existing_capsule_path.read_text(encoding="utf-8"))

    capsule_upgraded = False
    if capsule is None:
        if existing_capsule is not None and capsule_supports_operating_replay(existing_capsule):
            # Already v2: reuse it (idempotent; no regeneration needed).
            capsule = existing_capsule
        else:
            # Carry the ORIGINAL build's volatile globals (date + version) forward from the
            # system's existing capsule, so the regenerated foundation_doc_inputs still
            # reproduce the manifest's recorded foundation base_hashes (the regeneration runs
            # on a later date / possibly a different target version than the original build).
            preserve_from: Optional[Dict[str, Any]] = None
            if isinstance(existing_capsule, dict):
                _efdi = existing_capsule.get("foundation_doc_inputs")
                if isinstance(_efdi, dict):
                    preserve_from = _efdi
            capsule = build_v2_capsule_from_transcript(
                transcript_path, source_version, build_repo_root,
                system_shape=system_shape, project_name=project_name,
                generator_version_override=generator_version_override,
                preserve_volatile_from=preserve_from,
            )
            capsule_upgraded = True

    capsule_inputs = capsule.get("foundation_doc_inputs")
    if not isinstance(capsule_inputs, dict):
        raise UpgradeApplyError(
            "the regenerated capsule has no foundation_doc_inputs; cannot reconcile."
        )

    # --- 2. Baseline reconciliation -----------------------------------------
    files_block = manifest.get("managed_files")
    if not isinstance(files_block, dict):
        files_block = manifest.get("files")
    if not isinstance(files_block, dict):
        raise UpgradeApplyError("manifest has no managed_files block; cannot reconcile.")
    managed = _manifest_managed_relpaths(manifest)

    ol_rels = _operating_render_relpaths_for(source_version, build_repo_root)
    if not ol_rels:
        raise UpgradeApplyError(
            f"source version {source_version!r} declares no operating-layer render files; "
            "nothing to reconcile (is this the version the manual layer came from?)."
        )

    # Compute the KNOWN wizard payload for every source-version operating render file via the
    # canonical render (capsule persisted inputs + source-bundle-DERIVED inputs + target-hook
    # injection). This is the SAME render apply_upgrade uses, so a reconciled baseline is exactly
    # what a subsequent upgrade's conformance gate will reproduce.
    known = _render_operating_layer(
        source_version, ol_rels,
        capsule=capsule, capsule_inputs=capsule_inputs,
        project_name=project_name, build_repo_root=build_repo_root,
    )

    decisions: List[FileReconcileDecision] = []
    manifest_changed = False
    created_writes: Dict[str, str] = {}

    for rel in ol_rels:
        known_text = known.get(rel)
        if known_text is None:
            continue  # not produced by the source render (should not happen for ol_rels)
        known_content_hash = _content_hash(known_text)
        known_full_hash = _full_hash(known_text)
        live_path = operator_project_dir / rel
        in_manifest = rel in managed
        meta = files_block.get(rel) if in_manifest else None

        if not live_path.exists():
            # Absent on disk.
            if in_manifest:
                # Managed but missing — do not silently recreate (could clobber an operator
                # deletion). Leave for the normal upgrade's missing-file refusal.
                decisions.append(FileReconcileDecision(
                    rel, MIGRATE_ABSENT_SKIPPED,
                    note="managed but missing on disk; left for the normal upgrade to handle"))
                continue
            # Not managed + not on disk -> additive, collision-free -> create from known payload.
            created_writes[rel] = known_text
            files_block[rel] = {
                "managed": "true",
                "managed_by": "shared",
                "base_hash": known_full_hash,
                "base_content_hash": known_content_hash,
                "current_hash_last_seen": known_full_hash,
                "local_modifications": "expected",
                "merge_strategy": "three_way",
                "render_kind": RENDER_KIND_RENDER,
                "source_refs": [],
                LIVE_LINEAGE_VERSION_FIELD: source_version,
            }
            manifest_changed = True
            decisions.append(FileReconcileDecision(
                rel, MIGRATE_CREATED,
                note="absent + additive + collision-free; created from the known wizard payload"))
            continue

        live_text = live_path.read_text(encoding="utf-8")
        live_content_hash = _content_hash(live_text)

        if live_content_hash != known_content_hash:
            # OPERATOR DRIFT — preserve the edit signal; never rewrite the baseline.
            decisions.append(FileReconcileDecision(
                rel, MIGRATE_OPERATOR_DRIFT,
                note="live content differs from the known wizard payload; baseline left "
                     "untouched so the upgrade preserves the operator's edit"))
            continue

        # live == known payload. Reconcile baseline + lineage if not already correct.
        cur_base_content = str(meta.get("base_content_hash", "")) if meta else ""
        cur_base_hash = str(meta.get("base_hash", "")) if meta else ""
        cur_lineage = str(meta.get(LIVE_LINEAGE_VERSION_FIELD, "")) if meta else ""
        already = (
            in_manifest
            and cur_base_content == known_content_hash
            and cur_base_hash == known_full_hash
            and cur_lineage == source_version
        )
        if already:
            decisions.append(FileReconcileDecision(
                rel, MIGRATE_ALREADY, note="manifest baseline already reconciled; left untouched"))
            continue

        new_meta = dict(meta) if meta else {
            "managed": "true",
            "managed_by": "shared",
            "local_modifications": "expected",
            "merge_strategy": "three_way",
            "render_kind": RENDER_KIND_RENDER,
            "source_refs": [],
        }
        new_meta["base_hash"] = known_full_hash
        new_meta["base_content_hash"] = known_content_hash
        # current_hash_last_seen: the live file equals the known payload, so the observed
        # baseline pointer also descends from the source render.
        new_meta["current_hash_last_seen"] = known_full_hash
        new_meta[LIVE_LINEAGE_VERSION_FIELD] = source_version
        files_block[rel] = new_meta
        manifest_changed = True
        decisions.append(FileReconcileDecision(
            rel, MIGRATE_RECONCILED,
            note="live == known payload; adopted base_hash/base_content_hash + advanced "
                 "lineage; live bytes UNCHANGED"))

    # --- 2b. Copy-kind operating-layer reconciliation -----------------------
    # The estate's manually-applied `.claude/*` + skills files are render_kind:copy and
    # UNMANAGED (no manifest entry). On upgrade they hit the new-file collision rule
    # instead of being delivered/adopted. Mirror the render reconciliation for copy files:
    # the KNOWN payload is the VERBATIM source-bundle template bytes (NO render), with the
    # emitter's deterministic hook-injection replayed. Same dispositions, same invariant —
    # adoption only ADDS a manifest entry; live bytes are NEVER rewritten (except the one
    # additive-create-when-absent-and-collision-free case, matching the render policy).
    copy_entries = _operating_copy_entries_for(source_version, build_repo_root)
    for rel, entry in sorted(copy_entries.items()):
        try:
            known_text = _known_copy_payload(source_version, rel, capsule, build_repo_root)
        except BundleTemplateError as e:
            raise UpgradeApplyError(
                f"cannot read the source bundle template for copy file {rel!r}: {e}. "
                "No files were changed."
            ) from e
        known_content_hash = _content_hash(known_text)
        known_full_hash = _full_hash(known_text)
        live_path = operator_project_dir / rel
        in_manifest = rel in managed
        meta = files_block.get(rel) if in_manifest else None
        strategy = str(entry.get("merge_strategy", "warn_on_drift")) or "warn_on_drift"
        mode = str(entry.get("mode", "0644"))

        if not live_path.exists():
            if in_manifest:
                decisions.append(FileReconcileDecision(
                    rel, MIGRATE_ABSENT_SKIPPED,
                    note="managed copy file but missing on disk; left for the normal upgrade"))
                continue
            # Absent + unmanaged -> additive, collision-free -> create from known payload.
            created_writes[rel] = known_text
            files_block[rel] = {
                "managed": "true",
                "managed_by": "shared",
                "base_hash": known_full_hash,
                "base_content_hash": known_full_hash,
                "current_hash_last_seen": known_full_hash,
                "local_modifications": "expected",
                "merge_strategy": strategy,
                "mode": mode,
                "render_kind": RENDER_KIND_COPY,
                "source_refs": [],
                LIVE_LINEAGE_VERSION_FIELD: source_version,
            }
            manifest_changed = True
            decisions.append(FileReconcileDecision(
                rel, MIGRATE_CREATED,
                note="absent + additive + collision-free; created from the known copy payload"))
            continue

        live_text = live_path.read_text(encoding="utf-8")
        live_content_hash = _content_hash(live_text)

        if live_content_hash != known_content_hash:
            # OPERATOR DRIFT (or operator-authored file at this path) — never adopt over it;
            # leave it for the upgrade's collision/sidecar rule to protect.
            decisions.append(FileReconcileDecision(
                rel, MIGRATE_OPERATOR_DRIFT,
                note="live copy differs from the known wizard payload; left unmanaged so the "
                     "upgrade's collision/sidecar rule protects the operator's file"))
            continue

        # live == known payload. The copy-kind base_hash and base_content_hash are BOTH the
        # full-file hash (copy files carry no content-normalized write-only field; this
        # matches apply_upgrade's new-copy entry, which sets both to the full hash).
        cur_base_content = str(meta.get("base_content_hash", "")) if meta else ""
        cur_base_hash = str(meta.get("base_hash", "")) if meta else ""
        cur_lineage = str(meta.get(LIVE_LINEAGE_VERSION_FIELD, "")) if meta else ""
        already = (
            in_manifest
            and cur_base_content == known_full_hash
            and cur_base_hash == known_full_hash
            and cur_lineage == source_version
        )
        if already:
            decisions.append(FileReconcileDecision(
                rel, MIGRATE_ALREADY, note="manifest copy baseline already reconciled; left untouched"))
            continue

        new_meta = dict(meta) if meta else {
            "managed": "true",
            "managed_by": "shared",
            "local_modifications": "expected",
            "merge_strategy": strategy,
            "mode": mode,
            "render_kind": RENDER_KIND_COPY,
            "source_refs": [],
        }
        new_meta["base_hash"] = known_full_hash
        new_meta["base_content_hash"] = known_full_hash
        new_meta["current_hash_last_seen"] = known_full_hash
        new_meta[LIVE_LINEAGE_VERSION_FIELD] = source_version
        files_block[rel] = new_meta
        manifest_changed = True
        decisions.append(FileReconcileDecision(
            rel, MIGRATE_RECONCILED,
            note="live == known copy payload; adopted base_hash/base_content_hash + advanced "
                 "lineage; live bytes UNCHANGED"))

    # --- 3. Write (transactional-ish: capsule + manifest + any created files) ----
    capsule_changed = capsule_upgraded
    if write:
        if created_writes:
            for rel, text in created_writes.items():
                dest = operator_project_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
        if capsule_upgraded:
            existing_capsule_path.parent.mkdir(parents=True, exist_ok=True)
            existing_capsule_path.write_text(
                json.dumps(capsule, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if manifest_changed:
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    noop = (not manifest_changed) and (not capsule_changed) and (not created_writes)

    return MigrateResult(
        operator_project_path=str(operator_project_dir),
        source_version=source_version,
        decisions=decisions,
        capsule_upgraded_to_v2=capsule_upgraded,
        manifest_changed=manifest_changed,
        capsule_changed=capsule_changed,
        noop=noop,
    )
