---
fixture_id: ms01-mixed-signal-resolved-by-fallback
schema_version: fixture-replay-v1
fixture_class: mixed-signal
target_shape: markdown-agents
expected_confidence: medium → high (after step 02 fallback)
expected_emit_step: 02
expected_halt: false
notes: Step 01 produces MEDIUM confidence; step 02 fallback probes raise to HIGH for markdown-agents.
---

# Fixture ms01 — Mixed signal resolved by step 02 fallback

## Synthetic operator inputs

**P1-1 (project name):** "Research summarizer"

**P1-2 (core purpose):** "I'm doing PhD research on labor economics. I want a system that helps me make sense of the papers I'm reading — pulling out arguments, comparing methodologies, helping me see how different papers relate. Some days I'm at it all day; other days not at all."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | unsure | neutral |
| P1-5 multi-user | no | strong-positive markdown (no) |
| P1-6 thinking-partner | yes | strong-positive markdown / claude-skills |
| P1-7 external-software | no | strong-positive markdown (no) |

After step 01: markdown-agents has 3 strong-positives (Probes 2/5 no + 3 yes + 4/7 no) but ALSO 1 neutral (Probe 1 unsure). Other shapes have no strong-positives. → Top shape is markdown-agents at MEDIUM confidence (3 strong-positives but 1 neutral signal).

**Step 02 fallback probes fire** (MEDIUM at step 01):

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory | yes | strong-positive datastore — but other signals dominate |
| P02-FB-2 regular-pattern | no | strong-positive on-demand-friendly |
| P02-FB-3 operator-confirm | yes | strong-positive markdown-friendly |
| P02-FB-4 document-output | yes | strong-positive markdown / claude-skills |

After step 02: markdown-agents has 5 strong-positives + 0 strong-negatives → HIGH confidence.

**Step 03 UP-6 regulatory exposure:** None.

## Expected classifier emit (at end of step 02)

```yaml
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  detected_at_step: 02
  v1_supported: true
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals: # all 8 probes filled
  forward_offered_signals_at_step_01: ["doing PhD research on labor economics", "make sense of the papers I'm reading", "helping me see how different papers relate"]
  fallback_mode_offered: not_offered
```

## Expected pre-step-05 re-check

Outcome: `confirmed`. No stop conditions; no contradicting signals from step 02-04.

## Discrimination note

This fixture confirms hypothesis H-2 from S2.1 spec § 3: when step 01 yields MEDIUM-or-LOW confidence, step 02 fallback probes raise confidence to HIGH ≥60% of residual cases. ms01 is one positive datapoint. Real-operator-data signal on this hypothesis binds to the first operator-facing slice or E-α tester.

State-memory signal (Probe-5 yes) is interesting — operator wants the system to remember accumulated insights across sessions. For markdown-agents, this maps to the staging-file + agent-prompt pattern (memory in disk artifacts, not a datastore). The classifier treats this correctly — datastore-shape is rejected because the other 5 signals all align with markdown.
