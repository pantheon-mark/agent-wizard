"""Apply-side integrity gate (Option A+): verify the FETCHED toolkit + operator state match the
operator-APPROVED resolution before anything is applied.

After self-update fetches + checks out the approved commit, this recomputes — over the LOCAL
(checked-out) registry + bundle dir + operator manifest — the same content hashes the resolution
recorded at approve time, and confirms each matches. Any mismatch means the fetched bytes are NOT
what the operator approved (branch moved, wrong bundle, corruption, tamper) → fail closed, refuse
to apply. Pure: reads only, mutates nothing. Commit-HEAD verification (HEAD == approved commit)
is a git check done by the self-update wiring; this module verifies CONTENT.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from update_resolution import (  # type: ignore
    UpdateResolution,
    canonical_entry_sha256,
    operator_manifest_sha256,
    registry_text_sha256,
)
from upgrade import (  # type: ignore
    compute_bundle_manifest_sha256,
    compute_bundle_tree_sha256,
    find_bundle_entry,
    resolve_bundle_dir,
)


@dataclass
class ResolutionVerifyResult:
    ok: bool
    failures: List[str] = field(default_factory=list)


def verify_fetched_against_resolution(
    registry_path: Path,
    operator_project_dir: Path,
    resolution: UpdateResolution,
) -> ResolutionVerifyResult:
    """Recompute the resolution's content hashes over the local checked-out state and confirm
    they match. Returns ok=False (with named failures) on ANY mismatch or read error — never
    raises, so the caller fails closed with an actionable message."""
    failures: List[str] = []

    # 1. the local registry bytes must hash to the approved registry_sha256.
    try:
        reg_text = registry_path.read_text(encoding="utf-8")
    except OSError as e:
        return ResolutionVerifyResult(False, [f"local registry unreadable: {e}"])
    if registry_text_sha256(reg_text) != resolution.registry_sha256:
        failures.append("registry_sha256 mismatch (local registry != approved)")
    try:
        registry = json.loads(reg_text)
    except json.JSONDecodeError as e:
        return ResolutionVerifyResult(False, failures + [f"local registry not JSON: {e}"])

    # 2. the target entry must be present + hash to the approved target_entry_sha256.
    entry = find_bundle_entry(registry, resolution.target_version)
    if entry is None:
        return ResolutionVerifyResult(
            False, failures + [f"target entry {resolution.target_version} absent in local registry"]
        )
    if canonical_entry_sha256(entry) != resolution.target_entry_sha256:
        failures.append("target_entry_sha256 mismatch (registry entry changed since approve)")

    # 3. the checked-out bundle dir must hash to the approved bundle tree + manifest hashes.
    try:
        bundle_dir = resolve_bundle_dir(registry_path, registry, entry)
        if compute_bundle_tree_sha256(bundle_dir) != resolution.target_bundle_tree_sha256:
            failures.append("bundle_tree_sha256 mismatch (fetched bundle != approved)")
        if compute_bundle_manifest_sha256(bundle_dir) != resolution.target_bundle_manifest_sha256:
            failures.append("bundle_manifest_sha256 mismatch (fetched manifest != approved)")
    except Exception as e:  # noqa: BLE001 — any resolution/hash failure is a fail-closed signal.
        failures.append(f"bundle hash verification error: {e}")

    # 4. the operator's manifest must be unchanged since approve (state binding).
    try:
        if operator_manifest_sha256(operator_project_dir) != resolution.operator_manifest_sha256:
            failures.append("operator_manifest_sha256 mismatch (operator state changed since approve)")
    except Exception as e:  # noqa: BLE001
        failures.append(f"operator manifest verification error: {e}")

    return ResolutionVerifyResult(ok=not failures, failures=failures)
