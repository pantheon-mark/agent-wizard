---
fixture_id: s01-markdown-agents-clean
fixture_class: shape
target_shape: markdown-agents
expected_confidence: high
expected_emit_step: 01
expected_halt: false
notes: Canonical markdown-agents fixture — Mark-class operator using Claude Code as thinking partner with operator-confirm gating.
---

# Fixture s01 — markdown-agents (clean signal)

## Synthetic operator inputs

**P1-1 (project name):** "Workflow assistant"

**P1-2 (core purpose):** "I want a system I can use with Claude to help me think through business decisions — reviewing documents, brainstorming responses, and making sure I don't miss things in my client engagements. I work alone, mostly on my own laptop."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | no | strong-positive for markdown-agents (no) |
| P1-5 multi-user | no | strong-positive for markdown-agents (no) |
| P1-6 thinking-partner | yes | strong-positive for markdown-agents |
| P1-7 external-software | no | strong-positive for markdown-agents (no) |

**Step 02 probes:** not fired (HIGH confidence at step 01).

**Step 03 UP-6 regulatory exposure:** None (operator says #7 "None of the above").

## Expected classifier emit

```yaml
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  detected_at_step: 01
  v1_supported: true
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals:
    probe_1_continuous_runtime: no
    probe_2_multi_user: no
    probe_3_thinking_partner: yes
    probe_4_external_software: no
    probe_5_state_memory: not_asked
    probe_6_regular_pattern: not_asked
    probe_7_operator_confirm: not_asked
    probe_8_document_output: not_asked
  forward_offered_signals_at_step_01: []
  fallback_mode_offered: not_offered
```

## Expected pre-step-05 re-check

Outcome: `confirmed`. No stop conditions fire (no regulatory exposure). No contradicting signals from step 02-04.

## Expected pre-step-08 re-check

Outcome: `confirmed` (assuming vision + approach + advisors content does not contradict markdown-agents).

## Expected wizard behavior

Wizard proceeds normally through all 16 steps. Generates complete markdown-agents system at step 15.

## Confidence rationale

Per `wizard/shape_detection.md` § 3: top shape (markdown-agents) has 3 strong-positives (Probes 3 + Probes 1/4/5 as "no") AND 0 strong-negatives AND no other shape has ≥2 strong-positives → HIGH.
