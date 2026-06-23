"""The immutable UpdateResolution — the operator-approved upgrade contract.

When an operator runs `upgrade-check` and approves, the system records EXACTLY what was
checked + approved into `.wizard/update-resolution.json`. Later, in a SEPARATE invocation,
the guarded `self-update` fetches the toolkit + bundle and verifies that what it fetched
matches this approved resolution BEFORE applying anything. This closes the "approve one thing,
apply another" gap: the operator approves a concrete set of content hashes + an exact commit,
not a moving version label.

What it binds (Option A+):
  * `registry_sha256`               — the EXACT fetched registry bytes (canonicalized)
  * `target_entry_sha256`           — the target registry entry as approved
  * `target_bundle_tree_sha256`     — EXPECTED bundle dir hash, COPIED from the registry entry
  * `target_bundle_manifest_sha256` — EXPECTED manifest hash, COPIED from the registry entry
  * `target_public_commit_sha`      — the exact public-repo commit self-update must check out
  * `operator_manifest_sha256`      — the operator's manifest at approve time (state-binding)
  * `min_engine_version` / `checked_engine_version` — the engine-version envelope

All hashing is CANONICALIZED (line-ending normalized) so a remote HTTP body at check time and
a git checkout of identical content at self-update time compare EQUAL — a raw-byte hash would
fail closed on a benign transport/checkout difference (e.g. Windows autocrlf).

SAFETY: this file is READ-ONLY to the assistant — it is added to `.claude/settings.json`
`permissions.deny`, the same anti-self-bypass pattern that protects `.wizard/update-source.json`.
Were it writable, a prompt-injection could rewrite the approved hashes to match a malicious
payload and survive self-update's re-validation. Only the check (which the operator drives) and
the guarded self-update legitimately touch it.

Stdlib-only, pip-install-free. JSON is the runtime contract surface.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict

from upgrade import sha256_bytes, sha256_file  # type: ignore

UPDATE_RESOLUTION_REL = ".wizard/update-resolution.json"
UPDATE_RESOLUTION_SCHEMA_VERSION = "update-resolution-v1"

# Operator manifest the resolution binds (state at approve time).
_MANIFEST_REL = ".wizard/manifest.json"


class UpdateResolutionError(Exception):
    """Raised when an UpdateResolution cannot be built, loaded, or validated. Fail-closed:
    a missing / malformed / wrong-schema / incomplete resolution is an error, never a silent
    default, because the wrong answer here is a supply-chain hazard."""


@dataclass(frozen=True)
class UpdateResolution:
    resolution_schema_version: str
    source_origin_id: str
    source_ref: str
    source_url: str
    registry_sha256: str
    target_version: str
    from_version: str
    target_entry_sha256: str
    target_bundle_tree_sha256: str
    target_bundle_manifest_sha256: str
    target_public_commit_sha: str
    operator_manifest_sha256: str
    min_engine_version: str
    checked_engine_version: str
    checked_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        """Canonical serialized body: sorted keys, 2-space indent, trailing newline —
        deterministic so a re-render reads back byte-identical."""
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UpdateResolution":
        if not isinstance(data, dict):
            raise UpdateResolutionError("update-resolution must be a JSON object")
        schema = data.get("resolution_schema_version")
        if schema != UPDATE_RESOLUTION_SCHEMA_VERSION:
            raise UpdateResolutionError(
                f"update-resolution schema_version {schema!r} != expected "
                f"{UPDATE_RESOLUTION_SCHEMA_VERSION!r} (fail-closed)"
            )
        names = [f.name for f in fields(cls)]
        missing = [n for n in names if not (isinstance(data.get(n), str) and data.get(n))]
        if missing:
            raise UpdateResolutionError(
                f"update-resolution missing/empty required field(s): {missing}"
            )
        return cls(**{n: data[n] for n in names})


def registry_text_sha256(text: str) -> str:
    """Canonical content hash of the fetched registry body. Canonicalized (line-ending
    normalized) so the remote HTTP body and a later git checkout of identical content match."""
    return "sha256:" + sha256_bytes(text.encode("utf-8"))


def canonical_entry_sha256(entry: Dict[str, Any]) -> str:
    """Canonical content hash of a registry entry (sorted-key, separator-stable JSON), so the
    same entry hashes identically regardless of key order / incidental whitespace."""
    canon = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256_bytes(canon.encode("utf-8"))


def operator_manifest_sha256(operator_project_dir: Path) -> str:
    """Canonical content hash of the operator's `.wizard/manifest.json` (state-binding). Fails
    closed if absent — a resolution cannot bind state that does not exist."""
    manifest_path = operator_project_dir / _MANIFEST_REL
    if not manifest_path.is_file():
        raise UpdateResolutionError(
            f"operator manifest not found at {manifest_path}; cannot build a resolution for a "
            "non-managed project"
        )
    return "sha256:" + sha256_file(manifest_path)


def build_update_resolution(
    *,
    operator_project_dir: Path,
    registry_raw_text: str,
    source_url: str,
    source_origin_id: str,
    source_ref: str,
    entry: Dict[str, Any],
    from_version: str,
    target_public_commit_sha: str,
    min_engine_version: str,
    checked_engine_version: str,
    checked_at: str,
) -> UpdateResolution:
    """Construct the immutable resolution from what check fetched + verified. Pure (no clock,
    no network); the caller supplies `checked_at` so the result is deterministic + testable.

    The EXPECTED bundle hashes are COPIED from the (declared) registry entry — check cannot
    compute them (the target bundle is not local at check time); self-update verifies the
    FETCHED bundle against these expected values."""
    target_version = entry.get("foundation_bundle_version")
    declared_tree = entry.get("bundle_tree_sha256")
    declared_manifest = entry.get("bundle_manifest_sha256")
    for label, value in (("foundation_bundle_version", target_version),
                         ("bundle_tree_sha256", declared_tree),
                         ("bundle_manifest_sha256", declared_manifest)):
        if not (isinstance(value, str) and value):
            raise UpdateResolutionError(
                f"registry entry is missing required field {label!r}; cannot bind a resolution "
                "(the registry must declare bundle content hashes)"
            )
    return UpdateResolution(
        resolution_schema_version=UPDATE_RESOLUTION_SCHEMA_VERSION,
        source_origin_id=source_origin_id,
        source_ref=source_ref,
        source_url=source_url,
        registry_sha256=registry_text_sha256(registry_raw_text),
        target_version=target_version,
        from_version=from_version,
        target_entry_sha256=canonical_entry_sha256(entry),
        target_bundle_tree_sha256=declared_tree,
        target_bundle_manifest_sha256=declared_manifest,
        target_public_commit_sha=target_public_commit_sha,
        operator_manifest_sha256=operator_manifest_sha256(operator_project_dir),
        min_engine_version=min_engine_version,
        checked_engine_version=checked_engine_version,
        checked_at=checked_at,
    )


def write_update_resolution(operator_project_dir: Path, resolution: UpdateResolution) -> Path:
    """Atomically write the resolution (temp + os.replace) so a crash mid-write never leaves a
    truncated/half-valid approved contract on disk. Returns the path written."""
    dest = operator_project_dir / UPDATE_RESOLUTION_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(resolution.to_json(), encoding="utf-8")
    os.replace(str(tmp), str(dest))
    return dest


def load_update_resolution(operator_project_dir: Path) -> UpdateResolution:
    """Load + validate the approved resolution. Fail-closed (UpdateResolutionError) on missing
    file, non-regular file, malformed JSON, wrong schema, or any missing/empty required field."""
    path = operator_project_dir / UPDATE_RESOLUTION_REL
    if not path.exists():
        raise UpdateResolutionError(
            f"no approved update-resolution at {path}; run `upgrade-check` and approve first"
        )
    if not path.is_file():
        raise UpdateResolutionError(f"update-resolution path is not a regular file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise UpdateResolutionError(f"update-resolution at {path} is not valid JSON: {e}") from e
    return UpdateResolution.from_dict(data)
