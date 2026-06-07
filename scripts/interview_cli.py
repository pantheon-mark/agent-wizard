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
  confirm-field   record the operator's confirmation of a derived field
  preview-group   render a group's foundation-doc preview(s) in memory and print them (the
                  operator validates rendered prose, not JSON)
  close-group     close a group barrier: append the group_confirmed event + the control-flow
                  marker (carrying the source hash) once the group is ready
  mark-step       append a step-completion marker (refused upstream by the marker invariant
                  unless every group closing at that step is confirmed)
  resume          print the resume cursor (highest completed step + confirmed groups)

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
    env: Dict[str, Any] = {
        "_derivation_class": cls,
        "_decision_field": spec.decision_field,
        "_decision_kind": spec.decision_kind,
        "_prompt_version": prompt_version,
    }
    if cls == "auto":
        env["_source"] = "auto"
        return env
    if cls in ("synthesis", "policy"):
        if not inputs:
            raise InterviewCLIError(
                f"{spec.field}: a {cls} field is derived from prior fields — pass --inputs "
                f"(prior field keys), not --sources"
            )
        env["_source"] = "claude-derived-operator-confirmed"
        env["_derivation_inputs"] = list(inputs)
        return env
    if cls == "extraction":
        if not sources:
            raise InterviewCLIError(
                f"{spec.field}: an extraction field is pulled from the operator's answers — "
                f"pass --sources (question-IDs)"
            )
        env["_source"] = "operator-content"
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
        env["_source"] = "claude-derived-operator-confirmed"
        env["_source_question_ids"] = list(sources)
        return env
    if cls == "classification":
        # operator-preference cites question-IDs; a claude-derived classification cites prior fields.
        if inputs:
            env["_source"] = "claude-derived-operator-confirmed"
            env["_derivation_inputs"] = list(inputs)
        elif sources:
            env["_source"] = "operator-preference"
            env["_source_question_ids"] = list(sources)
        else:
            raise InterviewCLIError(f"{spec.field}: a classification field requires --sources or --inputs")
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
                      build_repo_root, *, auto_values: Dict[str, str]) -> List:
    events = TranscriptRecorder(Path(transcript)).events()
    dg = load_derivation_groups(shape)
    arts = render_group_previews(events, dg.group_by_id(group_id), dg, source_version,
                                 Path(build_repo_root), auto_values=auto_values)
    return [(a.doc_name, a.content) for a in arts]


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


def cmd_emit_system(transcript: str, shape: str, target_dir: str, build_repo_root: str, *,
                    project_name: str = "operator-system",
                    generator_version_override: Optional[str] = None) -> Dict[str, Any]:
    """Emit the complete operator system from the recorded transcript via the fail-closed bridge
    (compile -> assemble -> validate -> dispatch -> generator). The recorder stores the rich event
    vocabulary; map it to the replay view the bridge compiles (read_derived_replay_events) and read
    the agent intents from the same store. The bridge resolves the maintained tier->model map (real
    --model) and fails closed BEFORE any write on a stale generator identity / non-empty target /
    missing-or-empty derived input. Returns the receipt (foundation-only flag + the two hashes)."""
    from interview_bridge import build_operator_system_from_transcript  # type: ignore
    from derivation_groups import group_confirmation_is_stale  # type: ignore
    from transcript_recorder import group_source_hash  # type: ignore
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
    res = build_operator_system_from_transcript(
        read_derived_replay_events(events), read_agent_intents(events),
        system_shape=shape, target_dir=Path(target_dir), build_repo_root=Path(build_repo_root),
        project_name=project_name, generator_version_override=generator_version_override,
    )
    return {"foundation_only_mode": res.plan.foundation_only_mode, "target_dir": str(target_dir),
            "derived_record_hash": res.derived_record_hash, "transcript_hash": res.transcript_hash}


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
    sp.add_argument("--requires-external-network", dest="requires_external_network", action="store_true")
    sp.add_argument("--requires-broad-fs-read", dest="requires_broad_fs_read", action="store_true")
    sp.add_argument("--confidence", default="high")
    sp.add_argument("--insufficiency-flags", dest="insufficiency_flags", help="';'-separated")
    sp.add_argument("--source-spans", dest="source_spans", help="';'-separated")

    sp = sub.add_parser("preview-group"); add_transcript(sp)
    sp.add_argument("--shape", default="markdown-CC"); sp.add_argument("--group", required=True)
    sp.add_argument("--source-version", required=True); sp.add_argument("--build-repo-root", required=True)
    sp.add_argument("--auto", action="append", default=[], help="auto-global as KEY=VALUE (repeatable)")

    sp = sub.add_parser("close-group"); add_transcript(sp)
    sp.add_argument("--progress", required=True); sp.add_argument("--shape", default="markdown-CC")
    sp.add_argument("--group", required=True)

    sp = sub.add_parser("mark-step")
    sp.add_argument("--progress", required=True); sp.add_argument("--step", required=True)

    sp = sub.add_parser("resume")
    sp.add_argument("--progress", required=True); sp.add_argument("--shape", default="markdown-CC")

    sp = sub.add_parser("emit-system"); add_transcript(sp)
    sp.add_argument("--shape", default="markdown-CC")
    sp.add_argument("--target-dir", dest="target_dir", required=True)
    sp.add_argument("--build-repo-root", dest="build_repo_root", required=True)
    sp.add_argument("--project-name", dest="project_name", default="operator-system")
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
                requires_external_network=args.requires_external_network,
                requires_broad_fs_read=args.requires_broad_fs_read,
                confidence=args.confidence,
                insufficiency_flags=_split_semi(args.insufficiency_flags),
                source_spans=_split_semi(args.source_spans))
        elif args.cmd == "preview-group":
            autos = dict(kv.split("=", 1) for kv in args.auto)
            for doc, content in cmd_preview_group(args.transcript, args.shape, args.group,
                                                  args.source_version, args.build_repo_root,
                                                  auto_values=autos):
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
        elif args.cmd == "emit-system":
            rec = cmd_emit_system(args.transcript, args.shape, args.target_dir, args.build_repo_root,
                                  project_name=args.project_name,
                                  generator_version_override=args.generator_version_override)
            sys.stdout.write(json.dumps(rec, sort_keys=True) + "\n")
    except InterviewCLIError as e:
        sys.stderr.write(f"FAIL: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
