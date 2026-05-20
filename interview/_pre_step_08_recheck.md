# Pre-step-08 re-check — final shape-detection confirmation before architecture generation

## What this file does

Final re-check of the provisional `shape_hypothesis` against accumulated context (steps 05-07 vision + approach + advisors content). Especially important for emergent-architecture projects (the relevant product spec section; J6 anchored) where the architecture phase reveals shape signals that earlier steps did not surface.

## When this file runs

Reached from `wizard/interview/08_architecture.md` opening, BEFORE any step-08 user-facing question fires. This is the second re-check point F-1.

## Prerequisites

- `~/claude-wizard-draft/wizard_session_draft.md` contains `shape_hypothesis` with `recheck_log` showing `step: 05` entry (pre-step-05 re-check completed)
- Steps 05 (vision) + 06 (approach) + 07 (advisors) all marked `complete` in `~/claude-wizard-draft/wizard_progress.md`
- Vision document confirmed on disk; approach document confirmed on disk

## Reference spec

`wizard/shape_detection.md` § 5.2 (pre-step-08 re-check) + § 6 (unsupported-shape transition).

**Note on stop conditions:** Stop conditions are NOT re-evaluated at pre-step-08 (already evaluated at pre-step-05; regulatory exposure does not change between step 03 and step 08 under normal conditions). The exception is if pre-step-05 was `confirmed` BUT step 05-07 content newly implicates a stop condition (rare emergent-architecture case). The logic below covers that exception.

---

## Step 1 — Read accumulated context

Read these in order:

1. `~/claude-wizard-draft/wizard_session_draft.md` — full file (note `shape_hypothesis` current state + `recheck_log`)
2. Vision document on disk (`<project>/vision.md`) — note implementation hints, scale signals, architectural primitives surfaced by operator in step 05
3. Approach document on disk (`<project>/approach.md`) — note technology preferences, integration patterns, deployment topology mentions
4. Advisors knowledge base (step 07 output) — note any advisor identifications that imply shape (e.g., "deployment advisor" / "security operations advisor" imply continuous-runtime shape)

---

## Step 2 — Late-emerging stop-condition check (RARE — only if step 05-07 content surfaces new regulatory exposure)

Scan vision + approach + advisor content for any newly-surfaced regulatory exposure NOT captured at step 03 UP-6. Examples that may surface at this point:

- Vision mentions "patient communication" / "medical records" → potential HIPAA exposure (re-fire applicability probe)
- Approach mentions "European customers" → potential GDPR exposure (re-fire applicability probe)
- Approach mentions "credit card payments" / "Stripe integration with full PAN" → potential PCI-DSS exposure (re-fire applicability probe)
- Advisors list includes "compliance officer" / "DPO" / "audit advisor" → regulatory exposure hinted but framework not pre-identified

**If new regulatory exposure surfaces:**

Re-fire the framework applicability probe for the specific framework, then evaluate stop conditions per `wizard/interview/_pre_step_05_recheck.md` Step 2 logic. If a stop condition fires at this late point, treat it as a halt per the same logic — foundation state preserved (now including vision + approach + advisors on disk); halt message references the late emergence.

Append:

```yaml
shape_hypothesis:
  recheck_log:
  - step: 08
  timestamp: <current ISO 8601>
  outcome: halted
  stop_condition_fired: <number>
  halt_message: <verbatim>
  late_emergence_source: vision | approach | advisors
```

Surface late-emergence to operator with extra care — they may feel "you should have asked earlier." Acknowledge:

> Looking at what we've built so far — the vision and approach documents — I see [specific text]. That suggests [framework] applies, which I didn't pick up on at step 03. Before we generate the architecture, we need to handle this.
>
> Note: vision and approach documents are already on disk — they're abstracted from implementation shape (they describe what your system does, not how), so they stay valid through any shape revision or regulatory revision. We won't lose them.

Then offer the three-choice path (a / b / c) per `_pre_step_05_recheck.md` Step 2a — same operator-facing language; same `_stop_condition_reevaluate_loop.md` invocation pattern; **fresh iteration counter** per the relevant slice decision (pre_step_08 does NOT inherit pre_step_05's iteration count; see `_stop_condition_reevaluate_loop.md` § 3 counter-reset rule).

**If operator picks (b) or (c):** Invoke `wizard/interview/_stop_condition_reevaluate_loop.md` with:
- `entered_from: pre_step_08`
- `late_emergence_source: vision | approach | advisors`
- `pre_iteration_fired_conditions: [<list>]`
- `operator_choice: (b) change_shape` OR `(c) regulatory_exposure_revise`

Loop sub-module runs + returns outcome. Foundation state preservation through loop iterations: vision.md + approach.md remain on disk; loop does NOT touch them. Act per outcome as in pre_step_05 Step 2a; on `foundation_only` outcome, vision + approach roll forward into the foundation doc set `_foundation_only_mode_gate.md` § 5.

**If NO new regulatory exposure:** proceed to Step 3.

---

## Step 3 — Re-check triggers (same logic as pre-step-05 but reading later-step content)

Evaluate whether re-check is warranted:

1. Pre-step-05 re-check outcome was `revised` (revised shapes warrant another confirmation at step 08; the deeper architecture context may reveal whether the revision was correct)
2. Vision document content contains shape-contradicting signal — examples:
 - Vision mentions "platform" / "service" / "users sign in" + initial `markdown-agents` shape → contradicts
 - Vision mentions "thinking partner" / "review with me" + initial non-markdown shape → contradicts
3. Approach document content contains shape-contradicting signal — examples:
 - Approach references frontend framework / SQL database / cloud deployment + initial `markdown-agents` shape → contradicts
 - Approach references "single-file markdown" / "Claude Code as runtime" + initial non-markdown shape → contradicts
4. Initial emit confidence was LOW and the step-05 re-check did NOT raise it to HIGH (continuous LOW through to step 08 warrants final confirmation)

**If NO re-check triggered:** append confirmed-recheck entry; proceed to step 08.

```yaml
shape_hypothesis:
  recheck_log:
  - step: 08
  timestamp: <current ISO 8601>
  outcome: confirmed
```

Proceed to step 08.

**If re-check triggered:** continue to Step 4.

---

## Step 4 — Re-check resolution

Tell the operator honestly what triggered the re-check:

> One more shape check before we move into the architecture phase. Looking at your vision and approach documents, I see [quote contradicting signal verbatim]. That suggests your project might actually be [revised shape], not the [current shape] we've been working with. Let me confirm before generating the architecture — it's the last clean place to course-correct.

Ask 1-3 targeted confirmation questions. Same patterns as pre-step-05 § 4.

Classify outcome:

**Outcome A — confirmed current shape:**

```yaml
shape_hypothesis:
  recheck_log:
  - step: 08
  timestamp: <current ISO 8601>
  outcome: confirmed
  notes: signal_reconsidered_at_architecture_boundary
```

Proceed to step 08.

**Outcome B — revised shape, still v1-supported (i.e., still `markdown-agents`):**

```yaml
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  recheck_log:
  - step: 08
  timestamp: <current ISO 8601>
  outcome: revised
  revised_shape: markdown-agents
  revised_confidence: high
```

Proceed to step 08.

**Outcome C — revised shape, no longer v1-supported:**

This is a high-friction outcome at step 08 because vision + approach are already on disk. The operator has invested time. Acknowledge the friction:

> The shape revision means v1 of the wizard can't generate the implementation for [revised shape]. Vision and approach are already on disk — they're preserved.

Trigger unsupported-shape transition (next section). Append:

```yaml
shape_hypothesis:
  shape: <revised non-markdown shape>
  confidence: <revised confidence>
  v1_supported: false
  recheck_log:
  - step: 08
  timestamp: <current ISO 8601>
  outcome: revised
  revised_shape: <non-markdown shape>
  revised_confidence: <confidence>
  late_revision_at_architecture_boundary: true
```

Proceed to unsupported-shape transition.

---

## Step 5 — Unsupported-shape transition (late-revision variant)

Same two-choice structure as pre-step-05 § 5, with one note added:

> Your project looks like [revised shape]. v1 of the wizard generates complete systems for markdown-agents-on-Claude-Code only.
>
> The good news: we've already built your vision document and approach document, and those are abstracted from implementation shape — they describe what your system does, not how it does it. They stay valid for [revised shape] when v2 adds support.
>
> Two options:
>
> **(a) Stop here — wait for v2 / future versions.** Your project file is saved, including the vision and approach we already wrote. When the wizard adds [revised shape] support, we can pick up from this exact point — you won't lose anything.
>
> **(b) Foundation-only mode.** I can finish generating the remaining foundation docs (technical architecture, execution plan, test cases, audit framework) — abstracted from implementation shape — and you take all of them to Claude Code directly to build the implementation, OR wait for v2 shape support. We won't generate the actual agents, scripts, or run files.
>
> Which would you like? (Say "a" or "b".)

Handle (a) and (b) per pre-step-05 § 5 logic. The late-revision-at-architecture-boundary case is structurally the same; the friction acknowledgement above is the only added behavior.

---

## Step 6 — Completion

**Per advisor R2 C-009 disposition: update `handoff_phase` to `pre_step_08_evaluated`** in the staging file so downstream consumers know the final lifecycle phase is satisfied. Locate the existing line (currently `handoff_phase: pre_step_05_evaluated`) and rewrite to:

```yaml
handoff_phase: pre_step_08_evaluated
```

Append step-marker:

```
step_08_pre_recheck: complete | <timestamp>
```

Proceed to `wizard/interview/08_architecture.md`.

---

## Cross-references

- `wizard/shape_detection.md` § 5.2 + § 6 — canonical spec
- `wizard/handoff_contracts/shape_detection_v0.md` — handoff schema
- `wizard/interview/_pre_step_05_recheck.md` — sibling re-check module
- the relevant product spec section F-1 / § 5.13 F-12 — requirements
- The originating slice spec (build-side; not distributed) — design provenance.
