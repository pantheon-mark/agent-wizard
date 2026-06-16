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
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from generator import render_foundation_docs  # type: ignore
from replay_capsule import REPLAY_CAPSULE_REL  # type: ignore
from upgrade import (  # type: ignore
    MERGE_STRATEGY_FROZEN,
    MERGE_STRATEGY_OPERATOR_REVIEW,
    MERGE_STRATEGY_THREE_WAY,
    MERGE_STRATEGY_WARN_ON_DRIFT,
    UpgradeError,
    find_bundle_entry,
    find_migration_entry,
    load_migration_manifest,
    sha256_bytes,
    sha256_file,
)


# ===== Result classification =====

APPLY_RESULT_APPLIED = "applied"      # all touched files adopted theirs cleanly
APPLY_RESULT_PARTIAL = "partial"      # some files routed to review (live left = ours)
APPLY_RESULT_REFUSED = "refused"      # no live writes (gate failed / rollback)

# Per-file dispositions.
FILE_ADOPTED = "adopted"              # live file replaced with theirs
FILE_UNCHANGED = "unchanged"          # theirs == base; nothing to do
FILE_REVIEW = "routed_to_review"      # theirs written to sidecar; live left = ours

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


# ===== Replay-conformance gate =====

def _replay_conformance_check(
    current_version: str,
    capsule_inputs: Dict[str, Any],
    build_repo_root: Path,
    foundation_entries: Dict[str, Dict[str, Any]],
) -> None:
    """Fail-closed gate: re-render the CURRENT version from the capsule inputs and
    confirm each foundation doc hashes identically to the manifest base_hash.

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
    _replay_conformance_check(current_version, capsule_inputs, build_repo_root, foundation_entries)

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

    # --- 4. Per-file decisions ------------------------------------------------
    decisions: List[FileDecision] = []
    upgrade_id = f"{current_version}-to-{target_version}"
    review_dir = operator_project_dir / UPGRADE_REVIEW_DIR_REL / upgrade_id

    # Plan the staged writes: relpath -> bytes-to-write-into-live.
    staged_writes: Dict[str, str] = {}
    review_writes: List[tuple] = []  # (relpath, ours, theirs, overlay_note)
    frozen_blocks: List[str] = []

    for rel, meta in sorted(foundation_entries.items()):
        strategy = str(meta.get("merge_strategy", MERGE_STRATEGY_OPERATOR_REVIEW))
        base_hash = str(meta.get("base_hash", ""))
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
        ours_hash = "sha256:" + sha256_bytes(live.encode("utf-8"))
        drifted = (ours_hash != base_hash)
        theirs = theirs_rendered.get(rel)
        if theirs is None:
            # Target version dropped this doc from its render surface. v0 leaves it
            # in place (no destructive removal); treat as unchanged.
            decisions.append(FileDecision(rel, strategy, FILE_UNCHANGED, drifted,
                                          note="target version no longer renders this doc; left in place"))
            continue

        theirs_hash = "sha256:" + sha256_bytes(theirs.encode("utf-8"))
        target_changed = (theirs_hash != base_hash)

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
                review_writes.append((rel, live, theirs, True))
                decisions.append(FileDecision(rel, strategy, FILE_REVIEW, drifted,
                                              note="you edited this file; your version was kept and the new version was saved for review"))
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

            new_manifest = _recompute_manifest(
                manifest, target_entry, target_version, staged_writes,
                foundation_entries, target_generator_version,
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

            # All staged + validated. Commit: write review sidecars, atomic-replace
            # content + manifest, append history.
            for rel, ours, theirs, overlay in review_writes:
                review_paths_written.extend(
                    _write_review_sidecar(review_dir, rel, ours, theirs, overlay_note=overlay)
                )

            for rel in staged_writes:
                _atomic_replace(staging / rel, operator_project_dir / rel)
            _atomic_replace(staging / MANIFEST_REL, manifest_path)

            hist = operator_project_dir / UPGRADE_HISTORY_REL
            with hist.open("a", encoding="utf-8") as f:
                f.write(history_line)

    except UpgradeApplyError:
        if backup and backup_dir:
            _restore_backup(operator_project_dir, Path(backup_dir),
                            sorted(staged_writes))
        raise

    # --- 6. Classify ----------------------------------------------------------
    files_written = sorted(staged_writes)
    files_in_review = sorted(d.relpath for d in decisions if d.disposition == FILE_REVIEW)
    classification = APPLY_RESULT_PARTIAL if files_in_review else APPLY_RESULT_APPLIED

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
    if result.files_written:
        lines.append("Updated to the new version:")
        for rel in result.files_written:
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
) -> Dict[str, Any]:
    """Return a NEW manifest dict reflecting the apply.

    - bump foundation_bundle_version + generator_version (+ source_commit) to the
      target bundle's provenance.
    - for ADOPTED files (in staged_writes) advance base_hash + current_hash_last_seen
      to the newly-written bytes' hash.
    - for files left in review (foundation_entries not in staged_writes) DO NOT
      advance base_hash — they still represent the prior version.
    """
    new_manifest = json.loads(json.dumps(manifest))  # deep copy, JSON-clean
    new_manifest["foundation_bundle_version"] = target_version
    if target_entry.get("source_commit"):
        new_manifest["source_commit"] = target_entry["source_commit"]
    if target_generator_version:
        new_manifest["generator_version"] = target_generator_version
    files_block = new_manifest.get("managed_files")
    if not isinstance(files_block, dict):
        files_block = new_manifest.get("files")
    for rel, content in staged_writes.items():
        digest = "sha256:" + sha256_bytes(content.encode("utf-8"))
        entry = files_block.get(rel, {})
        entry["base_hash"] = digest
        entry["current_hash_last_seen"] = digest
        files_block[rel] = entry
    return new_manifest
