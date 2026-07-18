"""Build-time lint: aggregates the C-structural cluster's three build-time lints --
command shapes (C2), safety-notice fidelity (C3), and `.gitignore` source-template
token coverage (C1) -- into a single deterministic gate.

Why this exists
----------------
C1/C2/C3 each landed a structural fix plus a reusable, importable check. This
module is Task C4: pure composition. It imports and calls each sub-check's real
function -- it does NOT reimplement any of their logic -- and flattens their
results into one category-prefixed violation list, so a single gate catches any
C-structural regression across all three at once.

Scope (deliberately narrow -- AR-004 weakest-sufficient)
----------------------------------------------------------
This is a BUILD-TIME lint, not a runtime guard. It is meant to be run as part of
the build/test pipeline (e.g. via `python3 -m wizard.scripts.lib.build_structural_lint`
or its unittest suite) -- never wired into any agent's runtime decision path.

Stdlib only.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from command_shape_lint import check_skill_files  # noqa: E402
from notice_fidelity_lint import check_safety_notice_text  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# The SOURCE template this module checks for `.gitignore` coverage of the four
# consent/runtime artifact locations (relative to repo_root).
#
# C1 left only a *test* (test_emit_gitignore.py, REQUIRED_TOKENS at :49-54) that
# asserts against the EMITTED `.gitignore` (post-emit output, in a fixture built
# from the already-cut v0.13.1 bundle overlaid with dev-tree templates) -- it has
# no reusable check function. This module adds one, at a different layer: a
# direct static read of the SOURCE template that feeds that emission. Checking
# both is deliberate, documented duplication across layers, not harmful overlap
# -- this module does not touch or refactor C1's test.
GITIGNORE_TEMPLATE_RELPATH = "wizard/templates/root/gitignore_template"

# The four consent/runtime artifact-path tokens required in the source template,
# substring-matched (leading-slash-agnostic) -- same four locations C1's test
# checks in the emitted output: /security/acceptance_receipts/,
# /security/run_envelopes/, /security/invocation_ledgers/,
# /security/capability_acceptance_log.jsonl.
REQUIRED_GITIGNORE_TOKENS: Sequence[str] = (
    "security/acceptance_receipts",
    "run_envelopes",
    "invocation_ledgers",
    "capability_acceptance_log",
)


def check_gitignore_coverage(
    repo_root: Optional[Path] = None,
    template_relpath: str = GITIGNORE_TEMPLATE_RELPATH,
    required_tokens: Optional[Sequence[str]] = None,
) -> List[str]:
    """Return the required `.gitignore`-coverage tokens MISSING from the SOURCE
    template (default: ``wizard/templates/root/gitignore_template``). An empty
    list means every required token is present -- clean.

    Reads the REAL template from disk (anti-overfit: this must assert against
    the actual source template, never a hand-copied snippet)."""
    root = repo_root if repo_root is not None else REPO_ROOT
    tokens = required_tokens if required_tokens is not None else REQUIRED_GITIGNORE_TOKENS
    full_path = root / template_relpath
    text = full_path.read_text(encoding="utf-8")
    return [token for token in tokens if token not in text]


def run_structural_lint(repo_root: Path = REPO_ROOT) -> List[str]:
    """Run all three C-structural build-time lints and return one FLAT,
    category-prefixed violation list. An empty list means every sub-check is
    clean.

    Violation shapes, one category per sub-check:
      - ``"command-shape: <relpath>: <offending line>"``       (C2, command_shape_lint)
      - ``"notice-fidelity: missing caveat: <substring>"``      (C3, notice_fidelity_lint)
      - ``"gitignore-coverage: missing token: <token>"``        (C1, this module)

    Pure composition: imports and calls each sub-check's real function against
    ``repo_root`` (default: the real repo). Does not reimplement any sub-check's
    logic."""
    violations: List[str] = []

    shape_violations = check_skill_files(repo_root=repo_root)
    for relpath, offending_lines in shape_violations.items():
        for line in offending_lines:
            violations.append(f"command-shape: {relpath}: {line}")

    missing_caveats = check_safety_notice_text(repo_root=repo_root)
    for substring in missing_caveats:
        violations.append(f"notice-fidelity: missing caveat: {substring}")

    missing_tokens = check_gitignore_coverage(repo_root=repo_root)
    for token in missing_tokens:
        violations.append(f"gitignore-coverage: missing token: {token}")

    return violations


if __name__ == "__main__":
    found = run_structural_lint()
    if found:
        for violation in found:
            print(violation)
        sys.exit(1)
    print("structural lint: clean")
    sys.exit(0)
