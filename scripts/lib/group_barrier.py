"""Group-close barrier — deterministic orchestration over the interview's logical groups.

The barrier ORCHESTRATES ONLY. It holds NO hardcoded field knowledge: the derivation-groups
registry (which fields a group derives, which docs it previews) and the transcript event store
(the recorded sources / derivations / confirmations) are separate modules it composes.

Derivation itself (Claude-in-the-loop, per class) and confirmation (the operator) are the
non-deterministic steps the carrier markdown drives + records via the transcript recorder. The
barrier provides the DETERMINISTIC services around them:

  - build_preview_inputs  — the inputs for a barrier render: every field confirmed so far
                            (projected from the transcript) plus the auto/global fields. Cumulative,
                            not just this group's, so a multi-contributor doc (e.g. execution_plan.md,
                            fed by orchestration_build AND hitl_autonomy) renders fully at the last
                            contributing group's barrier.
  - render_group_previews — the Partial Artifact Render: pipe those inputs through each of the
                            group's preview_docs IN MEMORY (no disk write) and return rendered
                            markdown to SHOW the operator (validates prose, not JSON).
  - ready_to_close        — the group is closable: its source inputs are complete (valid skips count)
                            AND every target field is confirmed (projects).
  - close_group           — append the group_confirmed marker carrying the source hash + event range
                            (the stale-confirmation signal): refuses (fail-loud) if not ready.

Sequence per group:  sources -> derive -> [barrier render preview] -> confirm
                      -> [barrier append group_confirmed marker].

Stdlib-only, pip-install-free.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from derivation_replay import compile_transcript, project  # type: ignore
from transcript_recorder import (  # type: ignore
    read_derived_replay_events, answered_and_skipped, group_source_hash, source_event_range,
)
from derivation_groups import DerivationGroup, DerivationGroups, group_inputs_complete  # type: ignore
from generator import render_foundation_doc_preview, FoundationDocArtifact  # type: ignore


class BarrierError(Exception):
    """Raised when a group cannot be closed (fail-loud; never silently mark a group confirmed)."""


def _projected_so_far(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every field confirmed (or auto) up to now, value-only — the cumulative confirmed surface."""
    return project(compile_transcript(read_derived_replay_events(events)))


def build_preview_inputs(
    events: List[Dict[str, Any]],
    dg: DerivationGroups,
    *,
    auto_values: Dict[str, str],
) -> Dict[str, str]:
    """Inputs for a barrier render: the auto/global fields overlaid by every field confirmed so
    far (confirmed fields win over an auto default of the same name). Stringified for placeholder
    substitution. The strict single-doc renderer scopes this down to each preview doc and fail-fasts
    on anything that doc needs but this set lacks."""
    inputs: Dict[str, str] = {k: str(v) for k, v in auto_values.items() if k in set(dg.auto_global_fields)}
    for k, v in _projected_so_far(events).items():
        inputs[k] = str(v)
    return inputs


def render_group_previews(
    events: List[Dict[str, Any]],
    group: DerivationGroup,
    dg: DerivationGroups,
    source_version: str,
    build_repo_root: Path,
    *,
    auto_values: Dict[str, str],
) -> List[FoundationDocArtifact]:
    """The Partial Artifact Render. Render each of the group's preview_docs in memory from the
    cumulative-confirmed + auto inputs, and return the artifacts to SHOW the operator. No disk write.
    Fail-loud (GeneratorError) if a preview doc needs a field not yet derived — that is a barrier or
    registry misconfiguration, never a silently half-filled draft."""
    inputs = build_preview_inputs(events, dg, auto_values=auto_values)
    return [
        render_foundation_doc_preview(source_version, doc_name, inputs, build_repo_root)
        for doc_name in group.preview_docs
    ]


def ready_to_close(
    events: List[Dict[str, Any]],
    group: DerivationGroup,
) -> Tuple[bool, List[str]]:
    """(ready, reasons). A group is closable when its source inputs are complete (validly-skipped
    conditional questions count as satisfied) AND every target field is confirmed (projects). The
    reasons list names what is still missing (empty when ready)."""
    reasons: List[str] = []
    answered, skipped = answered_and_skipped(events)
    if not group_inputs_complete(group, answered, skipped):
        outstanding = [q for q in group.input_question_ids
                       if q not in answered and not (q in set(group.skip_satisfied_if) and q in skipped)]
        reasons.append(f"source inputs incomplete: {outstanding}")
    projected = _projected_so_far(events)
    for f in group.target_fields:
        if f not in projected:
            reasons.append(f"target field {f} is not confirmed/projected")
    return (not reasons, reasons)


def close_group(
    recorder,
    group: DerivationGroup,
    *,
    confirmed_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Append the group_confirmed marker (carrying the source hash + event range) once the group is
    ready. Fail-loud (BarrierError) if not ready — the marker invariant (a step completes only after
    its groups confirm) depends on this never marking an unready group confirmed."""
    events = recorder.events()
    ready, reasons = ready_to_close(events, group)
    if not ready:
        raise BarrierError(f"cannot close group {group.group_id!r}: {reasons}")
    src_hash = group_source_hash(events, group.input_question_ids)
    rng = source_event_range(events, group.input_question_ids)
    return recorder.record_group_confirmed(group.group_id, rng, src_hash, confirmed_at=confirmed_at)
