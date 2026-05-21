---
fixture_id: s03-claude-skills-clean
schema_version: fixture-replay-v1
fixture_class: shape
target_shape: claude-skills
expected_confidence: high
expected_emit_step: 01
expected_halt: false
notes: Canonical Claude-skills fixture — operator wants reusable thinking-partner capability with document output.
---

# Fixture s03 — claude-skills (clean signal)

## Synthetic operator inputs

**P1-1 (project name):** "Brief drafter"

**P1-2 (core purpose):** "I want to package up my way of writing client briefs so I can pull it into different Claude conversations. It's a thinking partner I bring to any client engagement — I want it to ask the right questions, produce a draft, and let me decide whether to send."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | no | strong-positive for markdown-agents / claude-skills (no) |
| P1-5 multi-user | no | strong-positive for markdown-agents / claude-skills (no) |
| P1-6 thinking-partner | yes | strong-positive for markdown-agents OR claude-skills |
| P1-7 external-software | no | strong-positive for markdown-agents (no) |

**Step 02 probes:** not fired (HIGH confidence at step 01).

**Step 03 UP-6 regulatory exposure:** None.

## Expected classifier emit

```yaml
shape_hypothesis:
  shape: claude-skills
  confidence: medium
  detected_at_step: 01
  v1_supported: false
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals:
    probe_1_continuous_runtime: no
    probe_2_multi_user: no
    probe_3_thinking_partner: yes
    probe_4_external_software: no
  forward_offered_signals_at_step_01: ["package up my way of writing", "pull it into different Claude conversations"]
  fallback_mode_offered: not_offered
```

## Expected behavior at end of step 01 (deferred emit)

Per `wizard/shape_detection.md` § 3 promotion logic: signals match both `markdown-agents` AND `claude-skills` clusters strongly → no unique top shape → MEDIUM confidence; defer emit to step 02.

**Step 02 fallback probes fire:**

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory | no | strong-positive for stateless-friendly (markdown-agents) |
| P02-FB-2 regular-pattern | no | strong-positive for on-demand-friendly (markdown-agents) |
| P02-FB-3 operator-confirm | yes | strong-positive for markdown-agents AND claude-skills |
| P02-FB-4 document-output | yes | strong-positive for markdown-agents AND claude-skills |

**Step 02 emit:** Forward-offered signal "package up my way of writing" / "pull it into different Claude conversations" tips classifier toward `claude-skills` (skill packaging) over `markdown-agents` (single-project). Confidence raised to HIGH.

```yaml
shape_hypothesis:
  shape: claude-skills
  confidence: high
  detected_at_step: 02
  v1_supported: false
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals: # all 8 probes
  forward_offered_signals_at_step_01: ["package up my way of writing", "pull it into different Claude conversations"]
  fallback_mode_offered: not_offered
```

## Expected pre-step-05 re-check

Initial shape is non-markdown at HIGH confidence → unsupported-shape transition fires. Same handling as s02 (operator picks scope-out OR foundation-only).

## Confidence rationale + v0 calibration note

This fixture exercises the markdown-agents-vs-claude-skills ambiguity. The forward-offered signal is the discriminator. At v0, the classifier uses the signal as interpretive prior per a prior slice decision E. If this fixture's expected emit doesn't match actual classifier behavior during fixture replay, it's a calibration signal — first instance of forward-offered-signal-as-discriminator landing usefully.
