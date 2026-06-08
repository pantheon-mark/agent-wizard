#!/usr/bin/env python3
"""Shape-state verifier — a read-only check that the wizard's prose-only shape-lifecycle
state (handoff_phase + recheck_log in the session draft) was actually persisted.

The shape-detection lifecycle lives in the human-readable session draft as a YAML-ish
`## Shape detection` block that the interview carriers hand-edit — it is NOT written through
the transcript CLI. A carrier that treats a re-check as a pass/fail verification can narrate
it ("gates passed") and skip its state-write, leaving no failing signal. This module is the
fail-closed consumer check: the re-check entry guards call it to assert the expected lifecycle
phase + the expected recheck_log entry are present BEFORE proceeding, and the re-check
completion step calls it as a write receipt (a non-zero exit means the write did not land).

Read-only by design: it parses and asserts, never rewrites the draft (the draft stays
carrier-owned). Parsing is line-oriented — the draft's shape block has intentionally irregular
indentation and the runtime is stdlib-only (no YAML dependency)."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


class ShapeStateError(Exception):
    """The draft's shape-lifecycle state failed an expectation (missing / != expected)."""


def _strip_comment(val: str) -> str:
    """Drop a trailing inline ` # comment` (the draft annotates values inline)."""
    return val.split("#", 1)[0].strip()


def parse_shape_state(text: str) -> Dict[str, object]:
    """Extract the consumer-relevant lifecycle fields from a session-draft's text.

    Returns ``{handoff_phase: str|None, recheck_steps: [int...], fallback_mode_offered: str|None}``.
    Line-oriented: ``handoff_phase`` and ``fallback_mode_offered`` are simple ``key: value`` lines;
    ``recheck_steps`` are the ``- step: N`` list items under a ``recheck_log:`` key. An inline
    ``recheck_log: []`` yields ``[]`` (an empty, present-but-no-entries log)."""
    handoff_phase: Optional[str] = None
    fallback: Optional[str] = None
    recheck_steps: List[int] = []
    in_recheck = False
    recheck_indent = -1

    for raw in text.splitlines():
        line = raw.rstrip("\n")

        m = re.match(r"^\s*handoff_phase:\s*(.+)$", line)
        if m:
            handoff_phase = _strip_comment(m.group(1))
            continue

        m = re.match(r"^\s*fallback_mode_offered:\s*(.+)$", line)
        if m:
            fallback = _strip_comment(m.group(1))
            continue

        m = re.match(r"^(\s*)recheck_log:\s*(.*)$", line)
        if m:
            recheck_indent = len(m.group(1))
            inline = _strip_comment(m.group(2))
            # "" => a block list of entries follows; "[]" => empty log, no entries.
            in_recheck = inline == ""
            continue

        if in_recheck:
            stripped = line.strip()
            if stripped == "":
                continue
            sm = re.match(r"^\s*-\s*step:\s*0*(\d+)", line)
            if sm:
                recheck_steps.append(int(sm.group(1)))
                continue
            indent = len(line) - len(line.lstrip())
            # a non-list, non-blank sibling key at <= the recheck_log indent ends the block
            # (entry continuations — timestamp / outcome / notes — are more deeply indented)
            if indent <= recheck_indent:
                in_recheck = False

    return {
        "handoff_phase": handoff_phase,
        "recheck_steps": recheck_steps,
        "fallback_mode_offered": fallback,
    }


def check_shape_state(text: str, *, expect_phase: Optional[str] = None,
                      expect_recheck_step: Optional[int] = None,
                      require_fields: Tuple[str, ...] = ()) -> Tuple[List[str], Dict[str, object]]:
    """Assert the draft's shape-lifecycle state meets the caller's expectations.

    Returns ``(failures, state)`` — ``failures`` is a list of human-readable messages (empty =
    pass). The caller turns a non-empty list into a non-zero exit (the fail-closed receipt)."""
    state = parse_shape_state(text)
    failures: List[str] = []

    if expect_phase is not None:
        actual = state["handoff_phase"]
        if actual != expect_phase:
            failures.append(
                f"handoff_phase is {actual!r}, expected {expect_phase!r} — the upstream "
                f"state-write did not persist (re-run the step that advances it)"
            )

    if expect_recheck_step is not None:
        steps = state["recheck_steps"]
        if expect_recheck_step not in steps:  # type: ignore[operator]
            failures.append(
                f"recheck_log has no step:{expect_recheck_step} entry (present: {steps}) — "
                f"the re-check did not persist its outcome"
            )

    for f in require_fields:
        if state.get(f) in (None, ""):
            failures.append(f"{f} is missing from the shape_hypothesis block")

    return failures, state
