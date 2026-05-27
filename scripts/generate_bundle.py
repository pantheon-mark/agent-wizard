#!/usr/bin/env python3
"""CLI entry for the wizard generator pipeline.

Reads operator inputs from a JSON file (stdlib-only; no YAML) and invokes
wizard.scripts.lib.generator.generate_bundle() to produce an operator-project
bundle. See wizard/scripts/lib/generator.py for the underlying library
contract.

Usage:
    python3 wizard/scripts/generate_bundle.py \
      --source-version v0.3.0 \
      --target /path/to/operator-project \
      --inputs /path/to/inputs.json \
      [--build-repo-root /path/to/build-repo] \
      [--permissive-dirty]

Exit codes:
    0  Success
    1  Generation failure (any GeneratorError; including F-9 dirty-worktree)
    2  Usage error (bad CLI args / inputs JSON parse / file missing)
"""

import argparse
import json
import sys
from pathlib import Path

# Import via sys.path manipulation. The wizard tree intentionally has
# __init__.py only at `wizard/scripts/lib/`, not at `wizard/` or
# `wizard/scripts/`. We add the lib directory to sys.path so `import generator`
# works whether this CLI is invoked directly
# (`python3 wizard/scripts/generate_bundle.py`), via unittest, or via subprocess.
_SCRIPTS_LIB = Path(__file__).resolve().parent / "lib"
if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))

from generator import generate_bundle, GeneratorError  # noqa: E402


class _UsageError(Exception):
    """Raised by helpers when a usage-level precondition fails. Caught by main()
    and surfaced as exit code 2 per the documented contract."""


def _detect_build_repo_root(start: Path) -> Path:
    """Walk up from start until finding a directory containing .git.

    Raises _UsageError (caught by main() → exit 2) if no .git ancestor is found.
    """
    for candidate in [start] + list(start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise _UsageError(
        f"cannot locate .git ancestor of {start}; pass --build-repo-root explicitly"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate an operator-project bundle from a source foundation bundle. "
            "Stdlib-only wizard runtime."
        )
    )
    parser.add_argument(
        "--source-version",
        required=True,
        help="foundation_bundle_version of the source bundle (e.g., v0.3.0)",
    )
    parser.add_argument(
        "--target",
        required=True,
        type=Path,
        help="directory to write the operator-project bundle to",
    )
    parser.add_argument(
        "--inputs",
        required=True,
        type=Path,
        help="path to operator inputs JSON file (stdlib-readable; NOT YAML)",
    )
    parser.add_argument(
        "--build-repo-root",
        type=Path,
        default=None,
        help="build-repo root path; auto-detected if omitted by walking up for .git",
    )
    parser.add_argument(
        "--permissive-dirty",
        action="store_true",
        default=False,
        help=(
            "Disable F-9 require_clean check for development/debugging. "
            "Do NOT use for v1.0.0+ generation events."
        ),
    )
    args = parser.parse_args()

    # Resolve build-repo root.
    try:
        if args.build_repo_root is None:
            build_repo_root = _detect_build_repo_root(Path(__file__).resolve())
        else:
            build_repo_root = args.build_repo_root.resolve()
    except _UsageError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2

    # Read and parse inputs.json (stdlib).
    if not args.inputs.exists():
        sys.stderr.write(f"ERROR: inputs file not found: {args.inputs}\n")
        return 2
    try:
        inputs_raw = args.inputs.read_text()
    except OSError as exc:
        sys.stderr.write(f"ERROR: cannot read inputs file {args.inputs}: {exc}\n")
        return 2
    try:
        inputs = json.loads(inputs_raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"ERROR: inputs file {args.inputs} is not valid JSON: {exc}\n"
        )
        return 2
    if not isinstance(inputs, dict):
        sys.stderr.write(
            f"ERROR: inputs file {args.inputs} must contain a JSON object at top level\n"
        )
        return 2

    # Invoke generator.
    try:
        result = generate_bundle(
            source_version=args.source_version,
            target_dir=args.target.resolve(),
            inputs=inputs,
            build_repo_root=build_repo_root,
            require_clean=not args.permissive_dirty,
        )
    except GeneratorError as exc:
        sys.stderr.write(f"FAIL: GeneratorError: {exc}\n")
        return 1
    # F-9 helper raises its own exception class; surface as exit 1.
    except Exception as exc:  # noqa: BLE001 — surface unexpected as exit 1 with message
        sys.stderr.write(f"FAIL: unexpected exception {type(exc).__name__}: {exc}\n")
        return 1

    sys.stdout.write(
        f"PASS: generated bundle at {args.target.resolve()}; "
        f"{len(result.paths_written)} files written\n"
    )
    sys.stdout.write(f"  manifest: {result.manifest_path}\n")
    for p in result.paths_written:
        sys.stdout.write(f"  - {p}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
