"""Build-time lint: emitted consent/acceptance commands must never rely on fragile
pipe-filtering (F-64).

Why this exists
----------------
F-64: `next-phase.md` used to tell the agent to "read the capability's id from
`security/capability_descriptors.json`" without giving it any concrete, pipe-free way
to do that filtered lookup. Left to improvise, the agent reached for something like
`cat security/capability_descriptors.json | jq '.id'` -- and that improvised shell
pipe tripped Claude Code's auto-mode classifier, producing an opaque, off-voice
denial on a step the non-technical operator was watching. The fix for the prose is
in `wizard/skills/next-phase.md` itself (an explicit, classifier-safe, pipe-free
lookup). This module is the build-time guard that keeps it from drifting back: it
scans the emitted consent/acceptance skill files for the pipe-into-filter shape and
fails the build if one reappears.

Scope (deliberately narrow -- weakest-sufficient)
----------------------------------------------------------
This lints the OPERATOR-FACING consent/acceptance skill files only:
`wizard/skills/next-phase.md` and `wizard/skills/add-capability.md`. It must NOT be
pointed at the harness hook scripts (`context_monitor.sh`, `statusline.sh`) -- those
legitimately pipe stdin into `python3 -c` internally (harness-side plumbing, not an
operator-facing command the agent is instructed to type), and flagging them would be
a false positive against a shape this lint has no business judging.

This is a cheap structural/text lint, not a runtime guard -- quality/UX issues are a
low-risk rule class (weakest-sufficient) and get a build-time check, never a runtime apparatus.

Stdlib only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]

# The consent/acceptance skill files this lint is scoped to (relative to repo root).
# Deliberately excludes the hook scripts (context_monitor.sh / statusline.sh) -- see
# module docstring.
DEFAULT_SKILL_RELPATHS: Sequence[str] = (
    "wizard/skills/next-phase.md",
    "wizard/skills/add-capability.md",
)

# Commands that turn a pipe into fragile, improvisation-prone filtering when chained
# after `|`. Matches word-bounded so "concatenate" or "sorting" are never mistaken for
# "cat" / "sort". "python3?" covers both "python" and "python3" in one alternative.
_FRAGILE_FILTER_WORDS = (
    "grep", "jq", "awk", "sed", "head", "tail", "cut", "tr", "sort", "uniq",
    "python3?", "cat", "xargs", "wc",
)

# A single `|` (not `||`, which is a shell "or" guard, e.g. `cmd || true`) followed by
# optional whitespace and one of the fragile filter words, word-bounded. The negative
# lookbehind/lookahead on `|` keeps this from ever matching either half of a `||`.
_FRAGILE_PIPE_RE = re.compile(
    r"(?<!\|)\|(?!\|)\s*(?:" + "|".join(_FRAGILE_FILTER_WORDS) + r")\b"
)


def find_fragile_pipes(text: str) -> List[str]:
    """Return the offending lines of ``text`` that pipe into a fragile filter
    command (``| grep``, ``| jq``, ``| awk``, ``| sed``, ``| head``, ``| tail``,
    ``| cut``, ``| tr``, ``| sort``, ``| uniq``, ``| python`` / ``| python3``,
    ``| cat``, ``| xargs``, ``| wc``). Empty list means clean.

    Deliberately line-based (not a full shell parser) -- this is a cheap structural
    lint (weakest-sufficient), not a shell AST scanner. Markdown table rows
    (``| Column | Column |``) and `` || `` shell-guard chains (``cmd || true``) do not
    match: the word list only fires on real filter-command names, and the `|`/`|`
    lookaround excludes `||` entirely.

    Known blind spot (accepted, not fixed -- see module docstring): a pipe at the end
    of one line continuing into a filter command on the next line (a shell
    line-continued pipe, e.g. ``cat foo.json |\\n  jq '.id'``) is NOT detected, since
    each line is checked independently. A full shell parser could catch this; that is
    out of scope for a weakest-sufficient text lint.
    """
    offending: List[str] = []
    for line in text.splitlines():
        if _FRAGILE_PIPE_RE.search(line):
            offending.append(line)
    return offending


_FENCE_RE = re.compile(r"^```")


def _fenced_code_blocks(markdown_text: str) -> str:
    """Return only the text inside triple-backtick fenced code blocks of a markdown
    document, joined by newlines. Command SHAPES (what this lint judges) live in
    fenced code blocks by this project's own doc convention; prose that merely
    *talks about* a pipe -- e.g. an inline `` `cat foo | jq` `` example of what NOT
    to do -- lives outside a fence and must never be mistaken for an actual emitted
    command. Scoping to fences is what keeps this lint from flagging its own
    cautionary prose."""
    in_fence = False
    kept: List[str] = []
    for line in markdown_text.splitlines():
        if _FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            kept.append(line)
    return "\n".join(kept)


def check_skill_files(
    relpaths: Optional[Sequence[str]] = None,
    repo_root: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """Scan the given consent/acceptance skill files (default: ``DEFAULT_SKILL_RELPATHS``
    -- ``next-phase.md`` + ``add-capability.md``) for fragile pipe-filtering.

    Only the content inside fenced code blocks is scanned (see ``_fenced_code_blocks``)
    -- that is where an actual command SHAPE lives; prose that names a bad example
    pipe as something to avoid is not itself a command emitted to the operator.

    Returns a dict of {relpath: [offending lines]} for every file that has at least
    one violation. An empty dict means every scanned file is clean. Reads the REAL
    files from disk (anti-overfit: this must assert against the actual emitted
    skill content, never a hand-copied snippet)."""
    root = repo_root if repo_root is not None else REPO_ROOT
    paths = relpaths if relpaths is not None else DEFAULT_SKILL_RELPATHS
    violations: Dict[str, List[str]] = {}
    for relpath in paths:
        full_path = root / relpath
        text = full_path.read_text(encoding="utf-8")
        offending = find_fragile_pipes(_fenced_code_blocks(text))
        if offending:
            violations[relpath] = offending
    return violations
