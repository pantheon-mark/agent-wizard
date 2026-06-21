#!/usr/bin/env python3
"""Interview CLI — the live driver between the wizard's interview carriers and the
derivation/transcript/barrier infrastructure (stdlib-only).

The interview carriers (the numbered interview files) call these subcommands so the wizard
runtime never hand-writes the audit envelope or the event-sequence bookkeeping — it supplies
only the field VALUE and the source question-IDs (or prior field keys) it used, and the CLI
assembles a well-formed event from the field manifest + the class derivation prompt.

Subcommands:
  record-answer   record an operator's answer to an interview question (a source event)
  skip-answer     record a validly-skipped (conditional) question
  derive-field    record a derived field — the audit envelope is assembled from the field
                  manifest (class / decision coupling) + the class prompt (version hash)
  derive-projection  derive a projection-class field DETERMINISTICALLY (pure code) from the
                  confirmed canonical record — the wizard computes it, the model never authors it
  confirm-field   record the operator's confirmation of a derived field
  preview-group   render a group's foundation-doc preview(s) in memory and print them (the
                  operator validates rendered prose, not JSON)
  close-group     close a group barrier: append the group_confirmed event + the control-flow
                  marker (carrying the source hash) once the group is ready
  mark-step       append a step-completion marker (refused upstream by the marker invariant
                  unless every group closing at that step is confirmed)
  resume          print the resume cursor (highest completed step + confirmed groups)
  check-shape-state  read-only assert that the session draft's shape-lifecycle state
                  (handoff_phase + recheck_log) was persisted — the fail-closed consumer
                  check the re-check entry guards + completion receipts call

The transcript (an event log) is the derivation+emission authority; the progress file
(wizard_progress.md markers) is the control-flow cursor only.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_LIB = Path(__file__).resolve().parent / "lib"
sys.path.insert(0, str(_LIB))

from transcript_recorder import TranscriptRecorder, read_derived_replay_events, read_agent_intents  # type: ignore  # noqa: E402
from build_intent import AgentIntent, ResourceClaims, CRITICALITY_TIERS  # type: ignore  # noqa: E402
from field_manifest import load_field_manifest, FieldSpec  # type: ignore  # noqa: E402
from derivation_prompts import load_derivation_prompt  # type: ignore  # noqa: E402
from derivation_groups import (  # type: ignore  # noqa: E402
    load_derivation_groups, parse_progress_markers, resume_point, validate_marker_invariant,
)
from group_barrier import render_group_previews, close_group  # type: ignore  # noqa: E402


class InterviewCLIError(Exception):
    """A carrier-facing failure: wrong inputs for a field's class, a not-ready group, etc."""


# --- envelope assembly -------------------------------------------------------

def _envelope_for(spec: FieldSpec, prompt_version: str,
                  sources: Optional[List[str]], inputs: Optional[List[str]]) -> Dict[str, Any]:
    """Assemble the audit envelope for a derived field from its manifest spec + the class
    prompt version. Picks _source + the input-citation key by class, fail-loud if the
    carrier supplied the wrong kind of input (the contract's input rules made executable)."""
    cls = spec.derivation_class
    # The class picks a DEFAULT `_source`, but the manifest may DECLARE an explicit `source` to
    # override it (provenance is its own axis in the derived-record contract). Example:
    # a lookup-extraction field (AUTOMATION_CREDIT_POOL) is `extraction`-class but its value is
    # plan-derived, so it declares `source: claude-derived-operator-confirmed`, not operator-content.
    # A nonsensical override (e.g. operator-preference on a synthesis field) is caught downstream by
    # the derived-record validator's DR rules (fail-closed); this assembler only picks the value.
    override = spec.source
    env: Dict[str, Any] = {
        "_derivation_class": cls,
        "_decision_field": spec.decision_field,
        "_decision_kind": spec.decision_kind,
        "_prompt_version": prompt_version,
    }
    if cls == "auto":
        env["_source"] = override or "auto"
        return env
    if cls in ("synthesis", "policy"):
        if not inputs:
            raise InterviewCLIError(
                f"{spec.field}: a {cls} field is derived from prior fields — pass --inputs "
                f"(prior field keys), not --sources"
            )
        env["_source"] = override or "claude-derived-operator-confirmed"
        env["_derivation_inputs"] = list(inputs)
        return env
    if cls == "extraction":
        if not sources:
            raise InterviewCLIError(
                f"{spec.field}: an extraction field is pulled from the operator's answers — "
                f"pass --sources (question-IDs)"
            )
        env["_source"] = override or "operator-content"
        env["_source_question_ids"] = list(sources)
        return env
    if cls == "authoring":
        # An authored field is written in the system voice, grounded in the operator's answers.
        # Honest provenance: claude-derived-operator-confirmed (DR-3 forces confirmation + timestamp).
        # Answer-only at v0: cite question-IDs, never prior payload fields (DR-5 enforces).
        if not sources:
            raise InterviewCLIError(
                f"{spec.field}: an authoring field is written in the system voice, grounded in "
                f"the operator's answers — pass --sources (question-IDs)"
            )
        env["_source"] = override or "claude-derived-operator-confirmed"
        env["_source_question_ids"] = list(sources)
        return env
    if cls == "classification":
        # operator-preference cites question-IDs; a claude-derived classification cites prior fields.
        if inputs:
            env["_source"] = override or "claude-derived-operator-confirmed"
            env["_derivation_inputs"] = list(inputs)
        elif sources:
            env["_source"] = override or "operator-preference"
            env["_source_question_ids"] = list(sources)
        else:
            raise InterviewCLIError(f"{spec.field}: a classification field requires --sources or --inputs")
        return env
    if cls == "projection":
        # A projection is a deterministic role-filter/reshape of PRIOR payload fields (the canonical
        # record). It derives from fields (like synthesis) but is pure code, not model authoring, so
        # its provenance is `auto` ("mechanically computed from trusted prior fields"). Forbids
        # source-question citation (DR-5); requires _derivation_inputs (the canonical field keys).
        if not inputs:
            raise InterviewCLIError(
                f"{spec.field}: a projection field is a deterministic view of prior fields — "
                f"pass --inputs (prior field keys), not --sources"
            )
        env["_source"] = override or "auto"
        env["_derivation_inputs"] = list(inputs)
        return env
    raise InterviewCLIError(f"{spec.field}: unhandled derivation_class {cls!r}")


# --- command functions (importable; the argparse layer is a thin wrapper) ----

def cmd_record_answer(transcript: str, qid: str, group: str, value: str,
                      clock: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    return TranscriptRecorder(Path(transcript), clock=clock).record_source_answer(qid, group, value)


def cmd_skip_answer(transcript: str, qid: str, group: str, reason: str = "",
                    clock: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    return TranscriptRecorder(Path(transcript), clock=clock).record_source_skip(qid, group, reason=reason)


def cmd_derive_field(transcript: str, shape: str, field: str, value: str, *,
                     sources: Optional[List[str]] = None, inputs: Optional[List[str]] = None,
                     clock: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    spec = load_field_manifest(shape).spec_for(field)   # raises FieldManifestError on unknown field
    prompt = load_derivation_prompt(spec.derivation_class)
    envelope = _envelope_for(spec, prompt.prompt_version, sources, inputs)
    return TranscriptRecorder(Path(transcript), clock=clock).record_derived_field(
        field, spec.group_id, value, envelope)


def cmd_derive_projection(transcript: str, shape: str, field: str, *,
                          clock: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    """Derive a `projection`-class field DETERMINISTICALLY from prior confirmed payload fields.

    A projection is pure code (filter/reshape or arithmetic over prior payload fields), not a
    judgment call: the value is COMPUTED here, never authored by the model. This keeps
    determinism_kind=pure_code honest (an unchanged subset auto-halts in the change-propagation
    engine). Dispatch is by field: the external-dependency role-filter views go to
    `dependency_projection`; the financial safety-envelope arithmetic (budget / intensive-op
    threshold) goes to `financial_projection`. Fail-loud if the field is not a projection, if a
    required prior field is not yet derived, or if a record is malformed."""
    from derivation_replay import compile_transcript  # type: ignore
    import dependency_projection as dep  # type: ignore
    import financial_projection as fin  # type: ignore
    import capability_projection as cap  # type: ignore
    spec = load_field_manifest(shape).spec_for(field)
    if spec.derivation_class != "projection":
        raise InterviewCLIError(
            f"{field}: derive-projection is only for projection-class fields "
            f"(this field is {spec.derivation_class!r})")
    recorder = TranscriptRecorder(Path(transcript), clock=clock)
    record = compile_transcript(read_derived_replay_events(recorder.events()))

    if field in fin.PROJECTION_FIELDS:
        # Financial safety-envelope arithmetic: pure-code over prior CONFIRMED money fields.
        inputs = fin.derivation_inputs_for(field)
        input_values: Dict[str, str] = {}
        for key in inputs:
            val = record.get(key)
            if val is None:
                raise InterviewCLIError(
                    f"{field}: required input {key!r} is not yet derived — derive its prior fields "
                    f"(plan pool / sharing posture / budget) before projecting")
            input_values[key] = val
        try:
            value = fin.project(field, input_values)
        except fin.FinancialProjectionError as e:
            raise InterviewCLIError(f"{field}: financial projection failed: {e}") from e
    elif field in dep.PROJECTION_FIELDS:
        # External-dependency role-filter view: pure-code over the canonical dependency record.
        inputs = dep.derivation_inputs_for(field)
        identity = record.get(dep.IDENTITY_FIELD)
        if identity is None:
            raise InterviewCLIError(
                f"{field}: {dep.IDENTITY_FIELD} is not yet derived — capture + confirm the canonical "
                f"dependency record (step 09) before projecting")
        annotation = record.get(dep.ANNOTATION_FIELD, "[]") if dep.ANNOTATION_FIELD in inputs else "[]"
        try:
            value = dep.project(field, identity, annotation)
        except dep.DependencyProjectionError as e:
            raise InterviewCLIError(f"{field}: projection failed: {e}") from e
    elif field in cap.PROJECTION_FIELDS:
        # MVP<->roadmap views: pure-code over the canonical CAPABILITY_INCREMENTS record (the
        # phase table + the MVP/roadmap boundary are deterministic views of the one confirmed
        # source, so the emitted execution_plan cannot contradict itself).
        inputs = cap.derivation_inputs_for(field)
        input_values = {}
        for key in inputs:
            val = record.get(key)
            if val is None:
                raise InterviewCLIError(
                    f"{field}: required input {key!r} is not yet derived — derive + confirm "
                    f"CAPABILITY_INCREMENTS before projecting the phase table / roadmap boundary")
            input_values[key] = val
        try:
            value = cap.project(field, input_values)
        except cap.CapabilityProjectionError as e:
            raise InterviewCLIError(f"{field}: capability projection failed: {e}") from e
    else:
        raise InterviewCLIError(
            f"{field}: no projector registered for this projection field "
            f"(known: {sorted(set(fin.PROJECTION_FIELDS) | set(dep.PROJECTION_FIELDS) | set(cap.PROJECTION_FIELDS))})")

    prompt = load_derivation_prompt(spec.derivation_class)   # "projection"
    envelope = _envelope_for(spec, prompt.prompt_version, None, inputs)
    return recorder.record_derived_field(field, spec.group_id, value, envelope)


def cmd_confirm_field(transcript: str, field: str, group: str, state: str, *,
                      value: Optional[str] = None, revisit_trigger: Optional[str] = None,
                      clock: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    if state == "accepted_uncertain_for_now" and not revisit_trigger:
        raise InterviewCLIError(
            f"{field}: confirmation state accepted_uncertain_for_now requires a --revisit-trigger"
        )
    return TranscriptRecorder(Path(transcript), clock=clock).record_field_confirmation(
        field, group, state, value=value, revisit_trigger=revisit_trigger)


_CONFIDENCE = ("high", "medium", "low")


def cmd_record_agent_intent(transcript: str, group: str, *,
                            display_name: str, function_summary: str, role_intent: str,
                            output_purpose: str, criticality_tier: str,
                            acceptance_signals: Optional[List[str]] = None,
                            requires_cron: bool = False, requires_external_network: bool = False,
                            requires_broad_fs_read: bool = False, confidence: str = "high",
                            insufficiency_flags: Optional[List[str]] = None,
                            source_spans: Optional[List[str]] = None,
                            clock: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    """Record one structured AgentIntent (the agent-intent derivation; approach_roster). The
    intent carries operator-meaning + resource CLAIMS only — no fs/model/cron/permission values
    (the assembler decides those). Fail-loud on a bad criticality tier or confidence value."""
    if criticality_tier not in CRITICALITY_TIERS:
        raise InterviewCLIError(
            f"agent {display_name!r}: criticality_tier must be one of {CRITICALITY_TIERS}; "
            f"got {criticality_tier!r}")
    if confidence not in _CONFIDENCE:
        raise InterviewCLIError(
            f"agent {display_name!r}: confidence must be one of {_CONFIDENCE}; got {confidence!r}")
    intent = AgentIntent(
        display_name=display_name, function_summary=function_summary, role_intent=role_intent,
        acceptance_signals=list(acceptance_signals or []), output_purpose=output_purpose,
        criticality_tier=criticality_tier,
        resource_claims=ResourceClaims(requires_cron=requires_cron,
                                       requires_external_network=requires_external_network,
                                       requires_broad_fs_read=requires_broad_fs_read),
        confidence=confidence, insufficiency_flags=list(insufficiency_flags or []),
        source_spans=list(source_spans or []))
    return TranscriptRecorder(Path(transcript), clock=clock).record_agent_intent(group, intent)


def cmd_preview_group(transcript: str, shape: str, group_id: str, source_version: str,
                      build_repo_root, *, auto_values: Dict[str, str],
                      include_unconfirmed: bool = False, out_file: Optional[str] = None) -> List:
    """Render a group's preview doc(s). `include_unconfirmed` shows the DERIVED draft before
    confirmation (preview-the-draft). `out_file`, when given, writes the OPERATOR-CLEAN render (CLI separators
    + YAML frontmatter stripped) to that file so the operator opens a clean markdown file
    (Operator Interaction Contract § 4) rather than reading raw CLI stdout."""
    events = TranscriptRecorder(Path(transcript)).events()
    dg = load_derivation_groups(shape)
    arts = render_group_previews(events, dg.group_by_id(group_id), dg, source_version,
                                 Path(build_repo_root), auto_values=auto_values,
                                 include_unconfirmed=include_unconfirmed)
    pairs = [(a.doc_name, a.content) for a in arts]
    if out_file:
        from generator import operator_clean_preview  # type: ignore
        body = "\n\n".join(operator_clean_preview(c) for _, c in pairs)
        Path(out_file).write_text(body + "\n", encoding="utf-8")
    return pairs


def _append_marker(progress: str, line: str) -> None:
    with Path(progress).open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def cmd_close_group(transcript: str, progress: str, shape: str, group_id: str,
                    clock: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    recorder = TranscriptRecorder(Path(transcript), clock=clock)
    group = load_derivation_groups(shape).group_by_id(group_id)
    ev = close_group(recorder, group, confirmed_at=(clock() if clock else None))  # raises BarrierError if not ready
    lo, hi = ev["source_event_range"]
    ts = ev.get("confirmed_at", "")
    _append_marker(progress,
                   f"{group.confirmation_marker}: complete | source_range={lo}:{hi} "
                   f"| source_hash={ev['source_hash']} | {ts}")
    return ev


def cmd_mark_step(progress: str, step_name: str,
                  clock: Optional[Callable[[], str]] = None) -> None:
    ts = clock() if clock else ""
    _append_marker(progress, f"{step_name}: complete | {ts}")


def cmd_resume(progress: str, shape: str) -> Dict[str, Any]:
    text = Path(progress).read_text(encoding="utf-8") if Path(progress).exists() else ""
    dg = load_derivation_groups(shape)
    return resume_point(parse_progress_markers(text), dg)


def cmd_check_shape_state(draft: str, *, expect_phase: Optional[str] = None,
                          expect_recheck_step: Optional[int] = None,
                          require_fields: Optional[List[str]] = None) -> Dict[str, Any]:
    """Read-only fail-closed check on the session draft's shape-lifecycle state. Raises
    InterviewCLIError (-> non-zero exit, the carrier-visible receipt) when an expectation is
    unmet — e.g. a re-check's handoff_phase advance / recheck_log entry never persisted."""
    from shape_state import check_shape_state  # type: ignore
    path = Path(draft)
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        raise InterviewCLIError(f"session draft not found or empty: {draft}")
    failures, state = check_shape_state(
        path.read_text(encoding="utf-8"), expect_phase=expect_phase,
        expect_recheck_step=expect_recheck_step, require_fields=tuple(require_fields or ()))
    if failures:
        raise InterviewCLIError("shape-state check failed:\n  - " + "\n  - ".join(failures))
    return state  # type: ignore[return-value]


def cmd_emit_system(transcript: str, shape: str, target_dir: str, build_repo_root: str, *,
                    project_name: str = "operator-system",
                    foundation_only_mode: bool = False,
                    bundle_version: str = "v0.6.0",
                    clock: Optional[Callable[[], str]] = None,
                    generator_version_override: Optional[str] = None) -> Dict[str, Any]:
    """Emit the complete operator system from the recorded transcript via the fail-closed bridge
    (compile -> assemble -> validate -> dispatch -> generator). The recorder stores the rich event
    vocabulary; map it to the replay view the bridge compiles (read_derived_replay_events) and read
    the agent intents from the same store. The bridge resolves the maintained tier->model map (real
    --model) and fails closed BEFORE any write on a stale generator identity / non-empty target /
    missing-or-empty derived input. Returns the receipt (foundation-only flag + the two hashes).

    The six `auto`-class config globals are supplied HERE at the emission boundary, because no
    interview step records them (inject-at-emit, the same model as the preview overlay): SYSTEM_SHAPE
    from --shape; WIZARD_VERSION from the bundle the generator runs from; LAST_UPDATED_DATE and
    MANUAL_LAST_UPDATED from the clock; LAST_UPDATED_TRIGGER = "initial build" (this IS the initial build); FOUNDATION_ONLY_MODE
    from the explicit `foundation_only_mode` decision the carrier already computed at the step-15
    entry guard (so foundation-only routing is an explicit command-boundary input, not a transcript
    field nothing writes). The bridge gap-fills these, restricted to the shape's auto_global_fields;
    a value a step ever recorded wins. Mirrors `preview-group --auto`."""
    from interview_bridge import build_operator_system_from_transcript  # type: ignore
    from datetime import date  # local: only the emit boundary stamps the build date

    last_updated = clock() if clock else date.today().isoformat()
    auto_values = {
        "SYSTEM_SHAPE": shape,
        "FOUNDATION_ONLY_MODE": "true" if foundation_only_mode else "false",
        "WIZARD_VERSION": bundle_version,
        "LAST_UPDATED_DATE": last_updated,
        "LAST_UPDATED_TRIGGER": "initial build",
        "MANUAL_LAST_UPDATED": last_updated,
    }
    from derivation_groups import group_confirmation_is_stale  # type: ignore
    from transcript_recorder import group_source_hash  # type: ignore
    from change_impact import pending_from_events  # type: ignore
    events = TranscriptRecorder(Path(transcript)).events()
    # Fail-closed (defense-in-depth): a group confirmed earlier whose upstream source answers
    # changed since (stale group_source_hash) must NOT emit stale derived content. The carrier
    # re-confirms stale groups interactively on resume; this is the independent emit-time guard,
    # so a carrier gap can never silently emit content derived from superseded answers.
    _markers = {e["group_id"]: e for e in events if e.get("event_type") == "group_confirmed"}
    _sourced = {e.get("group_id") for e in events
                if e.get("event_type") in ("source_answer", "source_skip")}
    for _g in load_derivation_groups(shape).groups:
        _m = _markers.get(_g.group_id)
        if _g.group_id in _sourced and not _m:
            # a LIVE group (it recorded source answers) with no confirmation marker means the
            # carrier skipped the operator's rendered-preview confirmation — never emit unconfirmed
            # content. (Groups with no source events — field-only / foundation-only transcripts —
            # are tolerated; field-level confirmation gates those.)
            raise InterviewCLIError(
                f"cannot emit: group {_g.group_id!r} recorded answers but has no confirmation "
                f"marker — confirm the group (rendered preview) before emitting")
        if _m and group_confirmation_is_stale(_m, group_source_hash(events, _g.input_question_ids)):
            raise InterviewCLIError(
                f"cannot emit: group {_g.group_id!r} confirmation is stale — an upstream answer "
                f"changed after the group was confirmed; re-confirm the group before emitting")
    # Fail-closed (the change-propagation enforcement dimension): refuse to emit while any
    # detected change implies a rule/decision node that the operator has not dispositioned.
    # content-only implications are guided (non-blocking); only blocking-class ones gate emit.
    _pending = pending_from_events(events)
    if _pending:
        _names = ", ".join(sorted({"{}:{}".format(p.node.kind, p.node.id) for p in _pending}))
        raise InterviewCLIError(
            "cannot emit: {} change implication(s) on a rule/decision node are un-dispositioned "
            "({}) — disposition each (apply / revise / intentional_divergence / freeze) before "
            "emitting".format(len(_pending), _names))
    res = build_operator_system_from_transcript(
        read_derived_replay_events(events), read_agent_intents(events),
        system_shape=shape, target_dir=Path(target_dir), build_repo_root=Path(build_repo_root),
        project_name=project_name, bundle_version=bundle_version,
        auto_values=auto_values, generator_version_override=generator_version_override,
    )
    return {"foundation_only_mode": res.plan.foundation_only_mode, "target_dir": str(target_dir),
            "derived_record_hash": res.derived_record_hash, "transcript_hash": res.transcript_hash}


def cmd_record_impact_change(transcript: str, change_id: str, impacts: List[Dict[str, Any]],
                             *, fingerprint: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Record a detected change + its surfaced impacts (the change-propagation engine output)."""
    return TranscriptRecorder(Path(transcript)).record_impact_change(change_id, impacts, fingerprint)


def cmd_record_impact_disposition(transcript: str, change_id: str, node_kind: str, node_id: str,
                                  disposition: str) -> Dict[str, Any]:
    """Record the operator's disposition of one surfaced impact. Fail-closed on an unknown
    disposition (only the contract's options are accepted)."""
    from change_impact import DISPOSITION_OPTIONS  # type: ignore
    if disposition not in DISPOSITION_OPTIONS:
        raise InterviewCLIError(
            "unknown disposition {!r}; must be one of {}".format(
                disposition, ", ".join(DISPOSITION_OPTIONS)))
    return TranscriptRecorder(Path(transcript)).record_impact_disposition(
        change_id, node_kind, node_id, disposition)


# --- argparse layer ----------------------------------------------------------

def _split(csv: Optional[str]) -> Optional[List[str]]:
    if not csv:
        return None
    return [x.strip() for x in csv.split(",") if x.strip()]


def _split_semi(s: Optional[str]) -> List[str]:
    """Split a ';'-separated list arg (used for agent-intent fields whose values may contain
    commas — acceptance signals, source spans, insufficiency flags)."""
    if not s:
        return []
    return [x.strip() for x in s.split(";") if x.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="interview_cli", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_transcript(sp):
        sp.add_argument("--transcript", required=True)

    sp = sub.add_parser("record-answer"); add_transcript(sp)
    sp.add_argument("--qid", required=True); sp.add_argument("--group", required=True)
    sp.add_argument("--value", required=True)

    sp = sub.add_parser("skip-answer"); add_transcript(sp)
    sp.add_argument("--qid", required=True); sp.add_argument("--group", required=True)
    sp.add_argument("--reason", default="")

    sp = sub.add_parser("derive-field"); add_transcript(sp)
    sp.add_argument("--shape", default="markdown-CC"); sp.add_argument("--field", required=True)
    sp.add_argument("--value", required=True); sp.add_argument("--sources"); sp.add_argument("--inputs")

    sp = sub.add_parser("derive-projection"); add_transcript(sp)
    sp.add_argument("--shape", default="markdown-CC"); sp.add_argument("--field", required=True)

    sp = sub.add_parser("confirm-field"); add_transcript(sp)
    sp.add_argument("--field", required=True); sp.add_argument("--group", required=True)
    sp.add_argument("--state", default="accepted"); sp.add_argument("--value")
    sp.add_argument("--revisit-trigger", dest="revisit_trigger")

    sp = sub.add_parser("record-agent-intent"); add_transcript(sp)
    sp.add_argument("--group", required=True)
    sp.add_argument("--display-name", dest="display_name", required=True)
    sp.add_argument("--function-summary", dest="function_summary", required=True)
    sp.add_argument("--role-intent", dest="role_intent", required=True)
    sp.add_argument("--output-purpose", dest="output_purpose", required=True)
    sp.add_argument("--criticality-tier", dest="criticality_tier", required=True)
    sp.add_argument("--acceptance-signals", dest="acceptance_signals", help="';'-separated")
    sp.add_argument("--requires-cron", dest="requires_cron", action="store_true")
    sp.add_argument("--confidence", default="high")
    sp.add_argument("--insufficiency-flags", dest="insufficiency_flags", help="';'-separated")
    sp.add_argument("--source-spans", dest="source_spans", help="';'-separated")

    sp = sub.add_parser("preview-group"); add_transcript(sp)
    sp.add_argument("--shape", default="markdown-CC"); sp.add_argument("--group", required=True)
    sp.add_argument("--source-version", required=True); sp.add_argument("--build-repo-root", required=True)
    sp.add_argument("--auto", action="append", default=[], help="auto-global as KEY=VALUE (repeatable)")
    sp.add_argument("--include-unconfirmed", action="store_true",
                    help="preview the DERIVED draft before confirmation; never used for emit")
    sp.add_argument("--out-file", dest="out_file",
                    help="write the operator-clean preview (frontmatter/separators stripped) here")

    sp = sub.add_parser("close-group"); add_transcript(sp)
    sp.add_argument("--progress", required=True); sp.add_argument("--shape", default="markdown-CC")
    sp.add_argument("--group", required=True)

    sp = sub.add_parser("mark-step")
    sp.add_argument("--progress", required=True); sp.add_argument("--step", required=True)

    sp = sub.add_parser("resume")
    sp.add_argument("--progress", required=True); sp.add_argument("--shape", default="markdown-CC")

    sp = sub.add_parser("check-shape-state")
    sp.add_argument("--draft", required=True)
    sp.add_argument("--expect-phase", dest="expect_phase")
    sp.add_argument("--expect-recheck-step", dest="expect_recheck_step", type=int)
    sp.add_argument("--require-field", dest="require_fields", action="append", default=[])

    sp = sub.add_parser("record-impact-change"); add_transcript(sp)
    sp.add_argument("--change-id", dest="change_id", required=True)
    sp.add_argument("--impacts", required=True, help="JSON list of {node_kind,node_id,impact_class}")
    sp.add_argument("--fingerprint", help="optional JSON fingerprint object")

    sp = sub.add_parser("record-impact-disposition"); add_transcript(sp)
    sp.add_argument("--change-id", dest="change_id", required=True)
    sp.add_argument("--node-kind", dest="node_kind", required=True)
    sp.add_argument("--node-id", dest="node_id", required=True)
    sp.add_argument("--disposition", required=True)

    sp = sub.add_parser("emit-system"); add_transcript(sp)
    sp.add_argument("--shape", default="markdown-CC")
    sp.add_argument("--target-dir", dest="target_dir", required=True)
    sp.add_argument("--build-repo-root", dest="build_repo_root", required=True)
    sp.add_argument("--project-name", dest="project_name", default="operator-system")
    sp.add_argument("--foundation-only", dest="foundation_only_mode", action="store_true",
                    help="emit the foundation-only branch (carrier sets this from the step-15 "
                         "entry guard; supplies FOUNDATION_ONLY_MODE=true)")
    sp.add_argument("--bundle-version", dest="bundle_version", default="v0.6.0",
                    help="the foundation bundle to emit from; also stamped as WIZARD_VERSION")
    sp.add_argument("--generator-version-override", dest="generator_version_override")

    args = p.parse_args(argv)
    try:
        if args.cmd == "record-answer":
            cmd_record_answer(args.transcript, args.qid, args.group, args.value)
        elif args.cmd == "skip-answer":
            cmd_skip_answer(args.transcript, args.qid, args.group, reason=args.reason)
        elif args.cmd == "derive-field":
            cmd_derive_field(args.transcript, args.shape, args.field, args.value,
                             sources=_split(args.sources), inputs=_split(args.inputs))
        elif args.cmd == "derive-projection":
            ev = cmd_derive_projection(args.transcript, args.shape, args.field)
            sys.stdout.write(json.dumps(ev, sort_keys=True) + "\n")
        elif args.cmd == "confirm-field":
            cmd_confirm_field(args.transcript, args.field, args.group, args.state,
                              value=args.value, revisit_trigger=args.revisit_trigger)
        elif args.cmd == "record-agent-intent":
            cmd_record_agent_intent(
                args.transcript, args.group,
                display_name=args.display_name, function_summary=args.function_summary,
                role_intent=args.role_intent, output_purpose=args.output_purpose,
                criticality_tier=args.criticality_tier,
                acceptance_signals=_split_semi(args.acceptance_signals),
                requires_cron=args.requires_cron,
                confidence=args.confidence,
                insufficiency_flags=_split_semi(args.insufficiency_flags),
                source_spans=_split_semi(args.source_spans))
        elif args.cmd == "preview-group":
            autos = dict(kv.split("=", 1) for kv in args.auto)
            pairs = cmd_preview_group(args.transcript, args.shape, args.group,
                                      args.source_version, args.build_repo_root, auto_values=autos,
                                      include_unconfirmed=args.include_unconfirmed,
                                      out_file=args.out_file)
            if args.out_file:
                sys.stdout.write(f"wrote operator-clean preview to {args.out_file}\n")
            else:
                for doc, content in pairs:
                    sys.stdout.write(f"===== {doc} =====\n{content}\n")
        elif args.cmd == "close-group":
            ev = cmd_close_group(args.transcript, args.progress, args.shape, args.group)
            sys.stdout.write(json.dumps(ev, sort_keys=True) + "\n")
        elif args.cmd == "mark-step":
            cmd_mark_step(args.progress, args.step)
        elif args.cmd == "resume":
            rp = cmd_resume(args.progress, args.shape)
            rp = {**rp, "confirmed_groups": sorted(rp["confirmed_groups"])}
            sys.stdout.write(json.dumps(rp, sort_keys=True) + "\n")
        elif args.cmd == "check-shape-state":
            state = cmd_check_shape_state(
                args.draft, expect_phase=args.expect_phase,
                expect_recheck_step=args.expect_recheck_step, require_fields=args.require_fields)
            sys.stdout.write("shape-state OK: " + json.dumps(state, sort_keys=True) + "\n")
        elif args.cmd == "record-impact-change":
            fp = json.loads(args.fingerprint) if args.fingerprint else None
            cmd_record_impact_change(args.transcript, args.change_id,
                                     json.loads(args.impacts), fingerprint=fp)
        elif args.cmd == "record-impact-disposition":
            cmd_record_impact_disposition(args.transcript, args.change_id,
                                          args.node_kind, args.node_id, args.disposition)
        elif args.cmd == "emit-system":
            rec = cmd_emit_system(args.transcript, args.shape, args.target_dir, args.build_repo_root,
                                  project_name=args.project_name,
                                  foundation_only_mode=args.foundation_only_mode,
                                  bundle_version=args.bundle_version,
                                  generator_version_override=args.generator_version_override)
            sys.stdout.write(json.dumps(rec, sort_keys=True) + "\n")
    except InterviewCLIError as e:
        sys.stderr.write(f"FAIL: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
