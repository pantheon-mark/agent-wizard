"""Pure section-aware 3-way merge for managed foundation docs.

This is a SECTION-AWARE merge, deliberately NOT a line-level diff3. A line-level
diff over difflib's Ratcliff/Obershelp matcher false-aligns on repetitive
markdown (blank lines, repeated bullets, repeated headings) and silently
corrupts the document by interleaving, dropping, or duplicating content. That
approach is rejected. Instead the document is parsed into ordered blocks keyed by
ATX heading text (with a positional leading preamble), and the 3-way merge runs
at block granularity by exact-string comparison of each block's CORE.

The function is pure, deterministic, idempotent, and stdlib-only. It never emits
git conflict markers. Any block-level conflict or structural ambiguity (duplicate
heading identity, a block deleted on one side and edited on the other, an
add/add of the same heading with different bodies) yields an all-or-nothing
failure: clean=False, merged=None, conflict_reason set. There is never a partial
merged result.

Byte fidelity. Three document-level identity fast paths run BEFORE any block
logic: ours==base -> take theirs; theirs==base -> take ours; ours==theirs -> take
that. Each returns one side's exact bytes, so the property invariants
merge(B,B,T)==T, merge(B,O,B)==O, merge(B,X,X)==X hold byte-for-byte regardless
of line endings, BOM, or final newline. Blocks are split with
str.splitlines(keepends=True), so original line endings (LF/CRLF), a leading BOM,
and the EOF newline (or its absence) are preserved exactly through the block
text.

Separator model (edges, not block trailers). The blank/whitespace-only lines that
separate two sections are NOT part of either section's semantic content. They are
modelled as a GAP edge between adjacent blocks. Each block carries a `core` (its
heading + body with trailing blank/whitespace-only lines removed) and the parse
records `gap_after[key]` (the exact separator bytes that followed that block in
that document). The 3-way merge compares blocks by `core` only, so editing
section A in ours while target appends a new section C (which only changes A's
trailing separator) is correctly clean, not a false conflict. The EOF trailer of
the final block is tracked separately and is owned by the side that supplies the
final block.

Gap-emit rule (deterministic). For each adjacent pair X -> Y in the assembled
output, the separator between them is taken from the first side in which that
exact adjacency already exists: theirs, then ours, then base. If no side has that
adjacency, a minimal separator is synthesized matching the preceding block's line
ending ("\\r\\n\\r\\n" if it ends CRLF, else "\\n\\n"). The trailing EOF bytes
come from the side that supplied the final block.

Ordering rule for ours-only-added blocks (deterministic, documented). The merged
document follows THEIRS block ordering for every key present in theirs. A block
added only in ours is anchored immediately after its ours-side preceding-neighbour
key if that neighbour key survives into the merged output; otherwise it is
appended at the end, in ours-order. The preamble (positional key) always sorts
first.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

__all__ = ["SectionMergeResult", "section_three_way_merge"]

# ATX heading: 1-6 leading '#', a space, then a non-space char.
_HEADING_RE = re.compile(r"^#{1,6} \S.*$")

# Positional key for the leading preamble block (text before the first heading).
_PREAMBLE_KEY = ("__preamble__",)


def _strip_eol(line: str) -> str:
    """Strip a trailing line ending (\\r\\n or \\n or \\r)."""
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1]
    return line


def _is_heading(line: str) -> bool:
    return _HEADING_RE.match(_strip_eol(line)) is not None


def _is_blank(line: str) -> bool:
    """True if a physical line is blank/whitespace-only (after EOL strip)."""
    return _strip_eol(line).strip() == ""


@dataclass
class _ParsedDoc:
    order: List[object]              # ordered block keys
    core: Dict[object, str]          # key -> core text (no trailing blank lines)
    gap_after: Dict[object, str]     # key -> separator bytes before the NEXT block
    eof_trailer: str                 # trailing blank-line bytes after the LAST block
    adjacency: Dict[object, object]  # key -> the key that immediately follows it
    duplicate_key: Optional[str]


def _parse(text: str) -> _ParsedDoc:
    """Parse a document into ordered heading-keyed blocks with edge gaps.

    Preserves exact bytes. A heading text appearing more than once sets
    duplicate_key (ambiguous section identity -> caller fails closed).
    """
    lines = text.splitlines(keepends=True)

    # First pass: split into raw blocks (key + full line list incl. separators).
    raw_order: List[object] = []
    raw_blocks: Dict[object, List[str]] = {}
    duplicate_key: Optional[str] = None

    current_key: object = _PREAMBLE_KEY
    current_lines: List[str] = []

    def record(key: object, buf: List[str]) -> None:
        nonlocal duplicate_key
        if key in raw_blocks:
            if duplicate_key is None and key is not _PREAMBLE_KEY:
                duplicate_key = key  # type: ignore[assignment]
            return
        raw_order.append(key)
        raw_blocks[key] = list(buf)

    for line in lines:
        if _is_heading(line):
            if current_key is _PREAMBLE_KEY:
                if current_lines:  # no preamble block if doc starts with a heading
                    record(_PREAMBLE_KEY, current_lines)
            else:
                record(current_key, current_lines)
            current_key = _strip_eol(line)
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_key is _PREAMBLE_KEY:
        if current_lines:
            record(_PREAMBLE_KEY, current_lines)
    else:
        record(current_key, current_lines)

    # Second pass: split each block into core + trailing separator. For a
    # non-final block the trailing blank lines are the gap to the next block;
    # for the final block they are the EOF trailer.
    core: Dict[object, str] = {}
    gap_after: Dict[object, str] = {}
    adjacency: Dict[object, object] = {}
    eof_trailer = ""

    for i, key in enumerate(raw_order):
        buf = raw_blocks[key]
        # Find the boundary: trailing run of blank/whitespace-only lines.
        split = len(buf)
        while split > 0 and _is_blank(buf[split - 1]):
            split -= 1
        core_text = "".join(buf[:split])
        trailer_text = "".join(buf[split:])
        core[key] = core_text
        is_final = i == len(raw_order) - 1
        if is_final:
            eof_trailer = trailer_text
        else:
            gap_after[key] = trailer_text
            adjacency[key] = raw_order[i + 1]

    return _ParsedDoc(
        order=raw_order,
        core=core,
        gap_after=gap_after,
        eof_trailer=eof_trailer,
        adjacency=adjacency,
        duplicate_key=duplicate_key,
    )


@dataclass
class SectionMergeResult:
    clean: bool
    merged: Optional[str]
    conflict_reason: str


def _ok(merged: str) -> SectionMergeResult:
    return SectionMergeResult(clean=True, merged=merged, conflict_reason="")


def _conflict(reason: str) -> SectionMergeResult:
    return SectionMergeResult(clean=False, merged=None, conflict_reason=reason)


def _key_label(key: object) -> str:
    return "(preamble)" if key is _PREAMBLE_KEY else str(key)


def _synth_gap(prev_core: str) -> str:
    """Minimal separator matching the preceding block's line ending."""
    if prev_core.endswith("\r\n"):
        return "\r\n\r\n"
    return "\n\n"


def section_three_way_merge(base: str, ours: str, theirs: str) -> SectionMergeResult:
    """Section-aware 3-way merge. See module docstring for the full contract."""
    if not isinstance(base, str) or not isinstance(ours, str) or not isinstance(theirs, str):
        raise TypeError("section_three_way_merge requires str inputs")

    pb = _parse(base)
    po = _parse(ours)
    pt = _parse(theirs)

    # Structural ambiguity is checked BEFORE the identity fast paths: a document
    # with duplicate heading identity must always fail closed (route to sidecar),
    # even when one side is byte-identical to base and the merge would otherwise
    # be trivially clean. We must never emit an ambiguous-identity doc as a
    # "merged" result the apply step would then try to track.
    for label, parsed in (("base", pb), ("ours", po), ("theirs", pt)):
        if parsed.duplicate_key is not None:
            return _conflict(
                "duplicate heading identity in %s: %s appears more than once"
                % (label, _key_label(parsed.duplicate_key))
            )

    # ---- Document-level identity fast paths (byte-exact). --------------------
    if ours == base:
        return _ok(theirs)
    if theirs == base:
        return _ok(ours)
    if ours == theirs:
        return _ok(ours)

    bc, oc, tc = pb.core, po.core, pt.core
    all_keys = set(bc) | set(oc) | set(tc)

    # resolved[key] = chosen core text. Absent => block deleted from output.
    resolved: Dict[object, str] = {}

    for key in all_keys:
        in_base = key in bc
        in_ours = key in oc
        in_theirs = key in tc
        b = bc.get(key)
        o = oc.get(key)
        t = tc.get(key)

        if in_base:
            ours_deleted = not in_ours
            theirs_deleted = not in_theirs
            ours_changed = in_ours and o != b
            theirs_changed = in_theirs and t != b

            if ours_deleted and theirs_deleted:
                continue
            if ours_deleted:
                if theirs_changed:
                    return _conflict(
                        "section deleted in ours but edited in theirs: %s"
                        % _key_label(key)
                    )
                continue  # theirs unchanged -> honour deletion
            if theirs_deleted:
                if ours_changed:
                    return _conflict(
                        "section deleted in theirs but edited in ours: %s"
                        % _key_label(key)
                    )
                continue  # ours unchanged -> honour deletion

            if o == b:
                resolved[key] = t          # base==ours -> take theirs
            elif t == b:
                resolved[key] = o          # base==theirs -> take ours
            elif o == t:
                resolved[key] = o          # both changed identically -> take once
            else:
                return _conflict(
                    "section edited differently in ours and theirs: %s"
                    % _key_label(key)
                )
        else:
            if in_ours and in_theirs:
                if o == t:
                    resolved[key] = o      # both added identically -> take once
                else:
                    return _conflict(
                        "section added in both ours and theirs with different "
                        "bodies: %s" % _key_label(key)
                    )
            elif in_ours:
                resolved[key] = o          # ours-only addition
            else:
                resolved[key] = t          # theirs-only addition

    surviving = set(resolved)

    # ours-only-added keys (absent from base and theirs).
    ours_only_added = [
        k for k in po.order if k in resolved and k not in bc and k not in tc
    ]

    # Theirs ordering for surviving keys present in theirs.
    theirs_order = [k for k in pt.order if k in surviving]

    ours_index = {k: i for i, k in enumerate(po.order)}

    def preceding_anchor(added_key: object) -> Optional[object]:
        idx = ours_index[added_key]
        for j in range(idx - 1, -1, -1):
            cand = po.order[j]
            if cand in surviving and cand not in ours_only_added:
                return cand
        return None

    anchored: Dict[object, List[object]] = {}
    tail: List[object] = []
    for added in ours_only_added:
        anchor = preceding_anchor(added)
        if anchor is None:
            tail.append(added)
        else:
            anchored.setdefault(anchor, []).append(added)

    final_order: List[object] = []
    for key in theirs_order:
        final_order.append(key)
        for added in anchored.get(key, []):
            final_order.append(added)

    placed = set(final_order)
    # Any ours-only addition whose anchor did not survive into theirs_order
    # (e.g. anchor was deleted on theirs side) falls back to the tail so it is
    # never silently dropped.
    for added in ours_only_added:
        if added not in placed:
            tail.append(added)
            placed.add(added)
    for added in tail:
        if added not in final_order:
            final_order.append(added)

    # ---- Assemble: emit each core, with gap edges between adjacent blocks. ----
    def gap_for(x: object, y: object) -> str:
        # Take the separator from the first side where adjacency x->y exists.
        for parsed in (pt, po, pb):
            if parsed.adjacency.get(x) is y:
                return parsed.gap_after.get(x, "")
        return _synth_gap(resolved[x])

    # EOF trailer comes from the side that supplied the final block.
    last_key = final_order[-1] if final_order else None

    def eof_for(key: object) -> str:
        # Prefer the side that actually contributed this block's core text.
        chosen = resolved.get(key)
        for parsed in (pt, po, pb):
            if parsed.core.get(key) == chosen and key == (parsed.order[-1] if parsed.order else None):
                return parsed.eof_trailer
        # Otherwise: no recorded EOF trailer for this block as a final block.
        return ""

    parts: List[str] = []
    for i, key in enumerate(final_order):
        parts.append(resolved[key])
        if i < len(final_order) - 1:
            parts.append(gap_for(key, final_order[i + 1]))
    if last_key is not None:
        parts.append(eof_for(last_key))

    return _ok("".join(parts))
