"""Deterministic projections over the canonical CAPABILITY_INCREMENTS record (pure code).

CAPABILITY_INCREMENTS is the SINGLE structured source the operator confirms (the MVP<->roadmap
release-boundary decision): a JSON array, one object per capability increment, each tagged with a
release_bucket. The build-phase table and the MVP/roadmap boundary view are DETERMINISTIC
projections of it — never authored by the model — so the emitted execution_plan cannot contradict
itself. (Before this, MVP_* prose and BUILD_PHASES_ROWS were synthesized INDEPENDENTLY from
different answers, so "MVP = Phase 1, roadmap = later phases" was derivation-luck and could
contradict an MVP that actually spanned multiple phases. Verified failure: a generated bundle whose
MVP required capabilities its phase table deferred to phases 2-4.)

Two `projection`-class fields (deterministic views of a prior confirmed payload field — same class
the dependency + financial projections use; see derived-record-contract DR-5 + projection.md):

  BUILD_PHASES_ROWS     <- the committed increments (mvp + post_mvp_roadmap), grouped by phase
  MVP_ROADMAP_BOUNDARY  <- the increments split into MVP / roadmap / candidate buckets

A `candidate_conditional` increment is NOT committed (no phase) — it appears only in the boundary
view's "possible later" bucket, never in the build sequence.

Determinism: stable ordering (phases ascending; increment input-order within a phase and bucket),
so identical input yields byte-identical output — the property the change-propagation engine relies
on to auto-halt an unchanged subset. Fail-closed: a malformed record (not a list, missing capability
or release_bucket, an out-of-enum bucket, a committed increment with no phase, or a candidate with
no condition) is a hard error, never silently dropped.

Stdlib-only, pip-install-free.
"""

import json
from typing import Any, Dict, List


# --- canonical source field (the projections' single _derivation_input) ------
INCREMENTS_FIELD = "CAPABILITY_INCREMENTS"
BUILD_PHASES_FIELD = "BUILD_PHASES_ROWS"
BOUNDARY_FIELD = "MVP_ROADMAP_BOUNDARY"

# Release buckets (closed enum; fail-closed on anything else).
BUCKET_MVP = "mvp"
BUCKET_ROADMAP = "post_mvp_roadmap"
BUCKET_CANDIDATE = "candidate_conditional"
_BUCKETS = (BUCKET_MVP, BUCKET_ROADMAP, BUCKET_CANDIDATE)

# Each capability projection field and the prior confirmed field key(s) it reshapes.
_INPUTS: Dict[str, List[str]] = {
    BUILD_PHASES_FIELD: [INCREMENTS_FIELD],
    BOUNDARY_FIELD: [INCREMENTS_FIELD],
}

PROJECTION_FIELDS = frozenset(_INPUTS)


class CapabilityProjectionError(Exception):
    """Raised on a malformed CAPABILITY_INCREMENTS record (fail-closed)."""


def derivation_inputs_for(field: str) -> List[str]:
    """The canonical field key(s) a given capability projection reshapes (its `_derivation_inputs`)."""
    try:
        return list(_INPUTS[field])
    except KeyError:
        raise CapabilityProjectionError(
            f"unknown capability projection field {field!r}; known: {sorted(_INPUTS)}")


def parse_increments(raw: str) -> List[Dict[str, Any]]:
    """Parse + validate the CAPABILITY_INCREMENTS JSON array. Fail-closed on any malformation."""
    if not isinstance(raw, str) or not raw.strip():
        raise CapabilityProjectionError(f"{INCREMENTS_FIELD}: missing JSON value (got {raw!r})")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CapabilityProjectionError(f"{INCREMENTS_FIELD}: not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise CapabilityProjectionError(
            f"{INCREMENTS_FIELD}: must be a JSON array (got {type(data).__name__})")
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(data):
        where = f"{INCREMENTS_FIELD}[{i}]"
        if not isinstance(row, dict):
            raise CapabilityProjectionError(f"{where}: each increment must be an object")
        cap = row.get("capability")
        if not isinstance(cap, str) or not cap.strip():
            raise CapabilityProjectionError(f"{where}: 'capability' must be a non-empty string")
        bucket = row.get("release_bucket")
        if bucket not in _BUCKETS:
            raise CapabilityProjectionError(
                f"{where}: 'release_bucket' {bucket!r} not in {list(_BUCKETS)}")
        phase = row.get("phase")
        if bucket in (BUCKET_MVP, BUCKET_ROADMAP):
            if not isinstance(phase, int) or isinstance(phase, bool):
                raise CapabilityProjectionError(
                    f"{where}: committed increment ({bucket}) requires an integer 'phase'")
        if bucket == BUCKET_CANDIDATE:
            cond = row.get("condition")
            if not isinstance(cond, str) or not cond.strip():
                raise CapabilityProjectionError(
                    f"{where}: candidate_conditional increment requires a non-empty 'condition'")
        out.append(row)
    return out


def _committed(increments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in increments if r["release_bucket"] in (BUCKET_MVP, BUCKET_ROADMAP)]


def _label(row: Dict[str, Any]) -> str:
    """A capability line with its agent(s) in parentheses when present."""
    cap = row["capability"].strip()
    agents = str(row.get("agents", "")).strip()
    return f"{cap} ({agents})" if agents else cap


def _build_phases_rows(increments: List[Dict[str, Any]]) -> str:
    """Markdown table BODY (rows only; the template owns the header): the committed increments
    grouped by phase, phases ascending. A phase that mixes mvp + roadmap capabilities lists both —
    the MVP/roadmap split is shown per-capability in the boundary view, not here."""
    committed = _committed(increments)
    phases: List[int] = []
    for r in committed:
        if r["phase"] not in phases:
            phases.append(r["phase"])
    phases.sort()
    lines: List[str] = []
    for phase in phases:
        rows = [r for r in committed if r["phase"] == phase]
        agents: List[str] = []
        for r in rows:
            a = str(r.get("agents", "")).strip()
            if a and a not in agents:
                agents.append(a)
        caps = "; ".join(r["capability"].strip() for r in rows)
        depends = next((str(r["depends_on"]).strip() for r in rows
                        if str(r.get("depends_on", "")).strip()), "—")
        lines.append(f"| {phase} | {', '.join(agents)} | {caps} | {depends} |")
    return "\n".join(lines)


def _boundary_block(increments: List[Dict[str, Any]]) -> str:
    """Markdown block: the increments split into MVP / roadmap / candidate buckets. The static
    'Not included -> Vision Scope Boundary' cross-reference is owned by the template, not here."""
    mvp = [r for r in increments if r["release_bucket"] == BUCKET_MVP]
    roadmap = [r for r in increments if r["release_bucket"] == BUCKET_ROADMAP]
    candidate = [r for r in increments if r["release_bucket"] == BUCKET_CANDIDATE]

    parts: List[str] = []

    parts.append("**Delivered in the MVP**")
    if mvp:
        parts.extend(f"- {_label(r)}" for r in mvp)
    else:
        parts.append("- (the MVP scope is still being defined)")

    parts.append("")
    parts.append("**On the roadmap — in scope, planned after the MVP**")
    if roadmap:
        for r in roadmap:
            rationale = str(r.get("rationale", "")).strip()
            parts.append(f"- {_label(r)}" + (f" — {rationale}" if rationale else ""))
    else:
        parts.append("- Nothing is deferred — everything currently in scope is delivered in the MVP.")

    if candidate:
        parts.append("")
        parts.append("**Possible later — not committed**")
        for r in candidate:
            parts.append(f"- {r['capability'].strip()} — only if {str(r['condition']).strip()}")

    return "\n".join(parts)


def project(field: str, inputs: Dict[str, str]) -> str:
    """Compute one capability projection value from the prior confirmed CAPABILITY_INCREMENTS value.

    `inputs` maps each canonical input field key (per derivation_inputs_for) to its confirmed string
    value from the transcript. Fail-closed on a missing input or a malformed record."""
    if field not in _INPUTS:
        raise CapabilityProjectionError(
            f"unknown capability projection field {field!r}; known: {sorted(_INPUTS)}")
    for key in _INPUTS[field]:
        if key not in inputs:
            raise CapabilityProjectionError(f"{field}: missing required input {key!r}")

    increments = parse_increments(inputs[INCREMENTS_FIELD])
    if field == BUILD_PHASES_FIELD:
        return _build_phases_rows(increments)
    return _boundary_block(increments)


def main() -> int:
    import sys
    if len(sys.argv) < 3 or sys.argv[1] not in _INPUTS:
        print("usage: capability_projection.py <FIELD> <CAPABILITY_INCREMENTS_JSON>", file=sys.stderr)
        print(f"  FIELD one of: {sorted(_INPUTS)}", file=sys.stderr)
        return 2
    try:
        print(project(sys.argv[1], {INCREMENTS_FIELD: sys.argv[2]}))
    except CapabilityProjectionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
