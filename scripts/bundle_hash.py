#!/usr/bin/env python3
"""Foundation bundle hash-baseline manifest writer.

Produces base-hash manifest snippets for a foundation bundle at authoring time.
Stdlib-only — no PyYAML dependency. YAML manifest snippet emitted as
deterministic text. Keeps wizard distribution pip-install-free for
operator-projects.

Required filenames + per-file defaults + closed enums + manifest field list
are loaded from the wizard-distributed JSON manifest contract at
`wizard/foundation-bundles/v0/contracts/foundation-manifest-hash-baseline-v1.json`
via the loader at `wizard/scripts/lib/manifest_contract.py`.

Library function `hash_bundle()` raises `BundleHashError` on
missing-required-file (NOT `sys.exit`); CLI `main()` translates exception to
exit code 1.

Usage as CLI:
    wizard/scripts/bundle_hash.py <bundle-dir>           # emit manifest snippet to stdout
    wizard/scripts/bundle_hash.py <bundle-dir> -o <out>  # write to file

Usage as library:
    from bundle_hash import hash_bundle, format_manifest_snippet, BundleHashError
    files = hash_bundle(Path("path/to/bundle"))           # may raise BundleHashError
    snippet = format_manifest_snippet(files)

Bundle directory layout:
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

Exit codes (CLI):
    0 — success
    1 — bundle has missing required files OR contract load fails
    2 — tooling error (bundle path doesn't exist, etc.)
"""

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Resolve sibling-package import without requiring PYTHONPATH gymnastics.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lib.manifest_contract import (  # noqa: E402
    ManifestContractError,
    default_contract_path,
    load_manifest_contract,
)


class BundleHashError(Exception):
    """Raised when bundle hashing fails (e.g., missing required files).

    Library functions raise this exception; the CLI shim catches it and
    translates to exit code 1. Library callers must handle the exception
    directly — sys.exit is reserved for the CLI boundary.
    """


def sha256_file(path: Path) -> str:
    """Compute SHA-256 of file content; return hex digest."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_bundle(
    bundle_dir: Path,
    contract: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Walk bundle dir; return per-file hash + metadata as ordered list.

    Returns a list of dicts (ordering preserved from manifest contract) — each
    entry contains:
        {
            "path": "foundation/vision.md",
            "managed": "true",
            "base_hash": "sha256:<hex>",
            "current_hash_last_seen": "sha256:<hex>",
            "local_modifications": "<allowed|expected|not_recommended>",
            "merge_strategy": "<three_way|operator_review|warn_on_drift|frozen>",
        }

    Args:
        bundle_dir: foundation bundle root directory.
        contract: pre-loaded manifest contract; if None, loaded from default path.

    Raises:
        BundleHashError: if any required foundation-doc file is missing.
        ManifestContractError: if contract path provided is invalid (load failure).
    """
    if contract is None:
        contract = load_manifest_contract(default_contract_path())

    result: List[Dict[str, str]] = []
    missing = []
    invalid = []
    for record in contract["required_foundation_docs"]:
        rel_path = record["path"]
        abs_path = bundle_dir / rel_path
        if not abs_path.exists():
            missing.append(rel_path)
            continue
        if not abs_path.is_file():
            invalid.append(rel_path)
            continue
        h = sha256_file(abs_path)
        result.append({
            "path": rel_path,
            "managed": "true",
            "base_hash": f"sha256:{h}",
            "current_hash_last_seen": f"sha256:{h}",
            "local_modifications": record["local_modifications"],
            "merge_strategy": record["merge_strategy"],
        })
    if missing or invalid:
        problems = []
        if missing:
            problems.append(f"missing required foundation-doc files: {missing}")
        if invalid:
            problems.append(f"required foundation-doc paths are not regular files: {invalid}")
        raise BundleHashError("; ".join(problems))
    return result


def format_manifest_snippet(files: List[Dict[str, str]]) -> str:
    """Format the `files:` block of a `.wizard/manifest.yaml` per the manifest contract.

    Emits deterministic YAML text — no PyYAML dependency. Iterates entries in
    the order the manifest contract supplied (no incidental sort).
    """
    lines = ["files:"]
    for entry in files:
        lines.append(f"  {entry['path']}:")
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
    parser.add_argument(
        "--contract",
        type=Path,
        default=None,
        help=(
            "Optional override path to manifest contract JSON. Default: "
            "wizard/foundation-bundles/v0/contracts/foundation-manifest-hash-baseline-v1.json"
        ),
    )
    args = parser.parse_args()

    if not args.bundle_dir.exists() or not args.bundle_dir.is_dir():
        print(
            f"ERROR: bundle_dir {args.bundle_dir} does not exist or is not a directory",
            file=sys.stderr,
        )
        return 2

    try:
        contract_path = args.contract if args.contract else default_contract_path()
        contract = load_manifest_contract(contract_path)
    except ManifestContractError as e:
        print(f"ERROR: manifest contract load failed: {e}", file=sys.stderr)
        return 1

    try:
        files = hash_bundle(args.bundle_dir, contract=contract)
    except BundleHashError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

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
