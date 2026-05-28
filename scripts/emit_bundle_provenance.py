#!/usr/bin/env python3
"""Emit content-addressed strict-receipt provenance for a build-side bundle directory.

Build-side tool (NOT generate_bundle.py — that one emits INTO operator projects).
Reads an existing `wizard/foundation-bundles/<version>/` directory and emits
`foundation-bundle.provenance.json` (11-field content-addressed strict-receipt schema).

The 11-field schema is content-addressed: re-running this tool against the same
source-tree state produces matching content fields across runs; only `generated_at`
differs (it is metadata-only and excluded from content reproducibility).

Usage:
    python3 wizard/scripts/emit_bundle_provenance.py <bundle-dir> [--registry <path>] [--strict] [--dry-run]

Exit codes:
    0  success
    1  emission error (path issue / hash failure)
    2  usage error
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lib.upgrade import (  # noqa: E402
    PROVENANCE_FILENAME,
    emit_provenance,
    hash_bundle_files,
)


def _git_head_sha(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _worktree_clean(repo_root: Path) -> bool:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() == ""
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _detect_repo_root(start: Path) -> Path:
    for c in [start] + list(start.parents):
        if (c / ".git").exists():
            return c
    return start


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="emit_bundle_provenance",
        description=(
            "Emit foundation-bundle.provenance.json for a build-side bundle directory "
            "(11-field content-addressed strict-receipt schema)."
        ),
    )
    parser.add_argument("bundle_dir", help="Path to wizard/foundation-bundles/<version>/")
    parser.add_argument("--registry", default="wizard/registry/foundation-bundles.json",
                        help="Path to registry (default: wizard/registry/foundation-bundles.json)")
    parser.add_argument("--templates", default="wizard/templates",
                        help="Path to template tree (default: wizard/templates)")
    parser.add_argument("--strict", action="store_true",
                        help="Require clean worktree (strict_mode=True; generator-version identity precedent)")
    parser.add_argument("--strict-mode-source", default="cli_flag", choices=["cli_flag", "config", "default"])
    parser.add_argument("--dry-run", action="store_true",
                        help="Print provenance dict to stdout; do NOT write to disk")
    parser.add_argument("--out", default=None,
                        help="Override output path (default: <bundle_dir>/foundation-bundle.provenance.json)")
    args = parser.parse_args(argv)

    bundle_dir = Path(args.bundle_dir).resolve()
    if not bundle_dir.exists() or not bundle_dir.is_dir():
        print(f"error: bundle directory not found: {bundle_dir}", file=sys.stderr)
        return 2

    repo_root = _detect_repo_root(bundle_dir)
    registry_path = Path(args.registry)
    if not registry_path.is_absolute():
        registry_path = repo_root / registry_path
    templates_dir = Path(args.templates)
    if not templates_dir.is_absolute():
        templates_dir = repo_root / templates_dir

    bundle_version = bundle_dir.name  # the directory name encodes the version (e.g., v0.3.0)
    bundle_file_manifest = hash_bundle_files(bundle_dir, exclude=[PROVENANCE_FILENAME])
    worktree_clean = _worktree_clean(repo_root)
    generator_commit = _git_head_sha(repo_root)

    if args.strict and not worktree_clean:
        print(
            f"error: --strict requires clean worktree but found dirty state at {repo_root}",
            file=sys.stderr,
        )
        return 1

    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    provenance = emit_provenance(
        bundle_dir=bundle_dir,
        source_bundle_version=bundle_version,
        bundle_file_manifest=bundle_file_manifest,
        registry_path=registry_path,
        template_tree_dir=templates_dir,
        generator_commit_sha=generator_commit,
        worktree_clean=worktree_clean,
        strict_mode=args.strict,
        strict_mode_source=args.strict_mode_source,
        generated_at_iso=generated_at,
    )

    payload = json.dumps(provenance, sort_keys=True, indent=2, ensure_ascii=False) + "\n"

    if args.dry_run:
        print(payload, end="")
        return 0

    out_path = Path(args.out) if args.out else (bundle_dir / PROVENANCE_FILENAME)
    out_path.write_text(payload, encoding="utf-8")
    print(f"emitted {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
