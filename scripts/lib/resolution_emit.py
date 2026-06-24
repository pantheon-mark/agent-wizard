"""Check-side orchestration: emit the immutable approved-resolution for an available target.

When `upgrade-check` finds a newer version available, this resolves the EXACT public commit
the target lives at (Option A+), fetches the registry AT that commit (so registry_sha256 is
reproducible against the registry self-update sees after checkout), binds the EXPECTED bundle
hashes the entry declares, and writes the immutable UpdateResolution the operator approves and
self-update later verifies the fetched toolkit+bundle against.

Fail-closed: any unresolved step (no pin / git can't resolve the commit / registry unfetchable
at that commit / target absent in the commit-pinned registry) returns None and writes NOTHING,
so the check renders a could-not-determine status — never a partial or false approved contract.

git + network are injected (commit_resolver / fetcher) so this is fully testable offline.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from registry_fetch import fetch_registry_at_commit  # type: ignore
from self_update import resolve_remote_commit  # type: ignore
from update_resolution import (  # type: ignore
    UpdateResolution,
    build_update_resolution,
    write_update_resolution,
)
from update_source import load_update_source, UpdateSourceError  # type: ignore
from upgrade import find_bundle_entry  # type: ignore

CommitResolver = Callable[..., Optional[str]]
Fetcher = Callable[[str, int], Optional[str]]


@dataclass(frozen=True)
class ResolutionPlan:
    """The computed (not-yet-persisted) approved-resolution plus the commit-pinned registry
    metadata needed to render an operator preview. `.resolution` is the EXACT object that
    persist/apply would write — a read-only `--plan-only` preview renders from THIS so it can
    never drift from what `--apply` later binds (the compute-vs-persist safety guard)."""
    resolution: UpdateResolution
    entry: Dict[str, Any]
    source_url: str


def compute_update_resolution_for_target(
    operator_project_dir: Path,
    toolkit_dir: Path,
    target_version: str,
    *,
    from_version: str,
    checked_at: str,
    min_engine_version: str = "",
    checked_engine_version: str = "",
    commit_resolver: CommitResolver = resolve_remote_commit,
    fetcher: Optional[Fetcher] = None,
) -> Optional["ResolutionPlan"]:
    """Resolve commit -> fetch registry@commit -> BIND the immutable resolution. READ-ONLY:
    writes NOTHING (the caller decides whether to persist). Returns a `ResolutionPlan`, or None
    (touching nothing) on any unresolved step (no pin / git can't resolve the commit / registry
    unfetchable at that commit / target absent / entry lacks bundle hashes) — so a read-only
    preview renders a could-not-determine status, never a partial/false approved contract."""
    try:
        source = load_update_source(operator_project_dir)
    except UpdateSourceError:
        return None  # no/invalid pin -> could-not-determine

    https_url = source.get("https_url")
    ref = source.get("branch")
    owner, repo = source.get("repo_owner"), source.get("repo_name")
    if not (https_url and ref and owner and repo):
        return None

    # 1. EXACT public commit the ref points to (read-only ls-remote; Option A+).
    commit = commit_resolver(toolkit_dir, https_url, ref)
    if not commit:
        return None

    # 2. registry AT that commit (commit-pinned; origin-pin-only, no env override).
    fetch = fetch_registry_at_commit(operator_project_dir, commit, fetcher=fetcher)
    if not (fetch.ok and fetch.registry and fetch.raw_text is not None):
        return None

    # 3. the target entry IN the commit-pinned registry (re-find by version).
    entry: Optional[Dict[str, Any]] = find_bundle_entry(fetch.registry, target_version)
    if entry is None:
        return None

    # 4. bind the immutable resolution (fail-closed if the entry lacks bundle hashes). No write.
    try:
        resolution = build_update_resolution(
            operator_project_dir=operator_project_dir,
            registry_raw_text=fetch.raw_text,
            source_url=fetch.source_url,
            source_origin_id=f"github:{owner}/{repo}",
            source_ref=ref,
            entry=entry,
            from_version=from_version,
            target_public_commit_sha=commit,
            min_engine_version=min_engine_version,
            checked_engine_version=checked_engine_version,
            checked_at=checked_at,
        )
    except Exception:
        return None
    return ResolutionPlan(resolution=resolution, entry=entry, source_url=fetch.source_url)


def emit_update_resolution_for_target(
    operator_project_dir: Path,
    toolkit_dir: Path,
    target_version: str,
    *,
    from_version: str,
    checked_at: str,
    min_engine_version: str = "",
    checked_engine_version: str = "",
    commit_resolver: CommitResolver = resolve_remote_commit,
    fetcher: Optional[Fetcher] = None,
) -> Optional[UpdateResolution]:
    """Compute + PERSIST the approved resolution (the approve step). Returns the written
    UpdateResolution, or None (writing nothing) on any unresolved step. The written JSON is
    exactly `compute_update_resolution_for_target(...).resolution` — preview and binding share
    one source of truth."""
    plan = compute_update_resolution_for_target(
        operator_project_dir,
        toolkit_dir,
        target_version,
        from_version=from_version,
        checked_at=checked_at,
        min_engine_version=min_engine_version,
        checked_engine_version=checked_engine_version,
        commit_resolver=commit_resolver,
        fetcher=fetcher,
    )
    if plan is None:
        return None
    write_update_resolution(operator_project_dir, plan.resolution)
    return plan.resolution
