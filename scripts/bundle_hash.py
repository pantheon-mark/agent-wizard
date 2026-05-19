#!/usr/bin/env python3
"""Foundation bundle hash-baseline manifest writer.

Per S2.5 spec § 2 + Decision G (Option 1 — CLI + library function).
Per governance/foundation_versioning.md (D3) § 4.1 hash-based drift detection.
Mechanism: mech-hash-baseline-v0.

At v0 this tool produces base-hash manifest snippets for a foundation bundle
at AUTHORING TIME (per stage_2_planning.md § 2.4 sequencing clarification —
manifest-time hash-baselining is separate from runtime drift detection;
runtime `wizard upgrade-check` engine is deferred to E-β-firing slice or
subsequent slice).

Stdlib-only — no PyYAML dependency. YAML manifest snippet emitted as
deterministic text. Keeps wizard distribution pip-install-free for
operator-projects.

Usage as CLI:
    wizard/scripts/bundle_hash.py <bundle-dir>           # emit manifest snippet to stdout
    wizard/scripts/bundle_hash.py <bundle-dir> -o <out>  # write to file

Usage as library:
    from bundle_hash import hash_bundle, format_manifest_snippet
    files = hash_bundle(Path("path/to/bundle"))
    snippet = format_manifest_snippet(files)

Bundle directory layout (per D3 § 1.1 + § 5):
    bundle-dir/
    ├── foundation/
    │   ├── vision.md
    │   ├── prd.md
    │   ├── approach.md
    │   ├── execution_plan.md
    │   ├── technical_architecture.md
    │   ├── test_cases.md
    │   └── audit_framework.md
    └── ...

Each foundation/*.md file gets a base_hash entry per D3 § 4.1 schema.

Exit codes:
    0 — success
    1 — bundle directory has missing required files (per D3 § 1.1)
    2 — tooling error (path doesn't exist, etc.)
"""

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Dict, List

# Per D3 § 1.1 required filenames + default merge_strategy per file
# (merge_strategy defaults reflect typical wizard-vs-operator authority per D3 § 4.1)
REQUIRED_FOUNDATION_DOCS = {
    "foundation/vision.md": {
        "managed_by": "shared",
        "local_modifications": "expected",
        "merge_strategy": "three_way",
    },
    "foundation/prd.md": {
        "managed_by": "operator",
        "local_modifications": "expected",
        "merge_strategy": "operator_review",
    },
    "foundation/approach.md": {
        "managed_by": "shared",
        "local_modifications": "allowed",
        "merge_strategy": "three_way",
    },
    "foundation/execution_plan.md": {
        "managed_by": "operator",
        "local_modifications": "expected",
        "merge_strategy": "operator_review",
    },
    "foundation/technical_architecture.md": {
        "managed_by": "shared",
        "local_modifications": "allowed",
        "merge_strategy": "three_way",
    },
    "foundation/test_cases.md": {
        "managed_by": "operator",
        "local_modifications": "expected",
        "merge_strategy": "operator_review",
    },
    "foundation/audit_framework.md": {
        "managed_by": "wizard",
        "local_modifications": "not_recommended",
        "merge_strategy": "warn_on_drift",
    },
}


def sha256_file(path: Path) -> str:
    """Compute SHA-256 of file content; return hex digest."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_bundle(bundle_dir: Path) -> Dict[str, Dict[str, str]]:
    """Walk bundle dir; return per-file hash + metadata dict.

    Returns a dict keyed by relative file path (e.g. 'foundation/vision.md') with values:
        {
            "managed": "true",
            "base_hash": "sha256:<hex>",
            "current_hash_last_seen": "sha256:<hex>",
            "local_modifications": "<allowed|expected|not_recommended>",
            "merge_strategy": "<three_way|operator_review|warn_on_drift|frozen>",
        }
    """
    result: Dict[str, Dict[str, str]] = {}
    missing = []
    for rel_path, defaults in REQUIRED_FOUNDATION_DOCS.items():
        abs_path = bundle_dir / rel_path
        if not abs_path.exists():
            missing.append(rel_path)
            continue
        h = sha256_file(abs_path)
        result[rel_path] = {
            "managed": "true",
            "base_hash": f"sha256:{h}",
            "current_hash_last_seen": f"sha256:{h}",
            "local_modifications": defaults["local_modifications"],
            "merge_strategy": defaults["merge_strategy"],
        }
    if missing:
        print(
            f"ERROR: bundle is missing required foundation-doc files per D3 § 1.1: {missing}",
            file=sys.stderr,
        )
        sys.exit(1)
    return result


def format_manifest_snippet(files: Dict[str, Dict[str, str]]) -> str:
    """Format the `files:` block of a `.wizard/manifest.yaml` per D3 § 4.1 schema.

    Emits deterministic YAML text — no PyYAML dependency.
    """
    lines = ["files:"]
    for rel_path in sorted(files.keys()):
        entry = files[rel_path]
        lines.append(f"  {rel_path}:")
        lines.append(f"    managed: {entry['managed']}")
        lines.append(f"    base_hash: {entry['base_hash']}")
        lines.append(f"    current_hash_last_seen: {entry['current_hash_last_seen']}")
        lines.append(f"    local_modifications: {entry['local_modifications']}")
        lines.append(f"    merge_strategy: {entry['merge_strategy']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "bundle_dir",
        type=Path,
        help="Foundation bundle directory (contains `foundation/` subdir)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--with-frontmatter",
        action="store_true",
        help="Emit complete `.wizard/manifest.yaml` document including foundation_bundle_version + source_commit placeholders (default: emit `files:` block only)",
    )
    parser.add_argument(
        "--bundle-version",
        default="vUNSET",
        help="foundation_bundle_version field (used with --with-frontmatter)",
    )
    parser.add_argument(
        "--source-commit",
        default="UNSET",
        help="source_commit field (used with --with-frontmatter)",
    )
    args = parser.parse_args()

    if not args.bundle_dir.exists() or not args.bundle_dir.is_dir():
        print(
            f"ERROR: bundle_dir {args.bundle_dir} does not exist or is not a directory",
            file=sys.stderr,
        )
        return 2

    files = hash_bundle(args.bundle_dir)
    snippet = format_manifest_snippet(files)

    if args.with_frontmatter:
        header = (
            f"foundation_bundle_version: {args.bundle_version}\n"
            f"source_commit: {args.source_commit}\n"
        )
        output = header + snippet
    else:
        output = snippet

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote manifest snippet to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
