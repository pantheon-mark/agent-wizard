---
fixture_id: s08-unknown-low-signal
schema_version: fixture-replay-v1
fixture_class: shape
target_shape: unknown
expected_confidence: low
expected_emit_step: 02
expected_halt: false
expected_recheck_outcome: confirmed_or_revised_via_step_05_context
notes: Insufficient signal density — operator can't yet articulate what kind of system they want. forced_recheck_at_step_05 = true.
---

# Fixture s08 — unknown (low signal density)

## Synthetic operator inputs

**P1-1 (project name):** "Something to help"

**P1-2 (core purpose):** "I'm not sure exactly what I need — something that helps me get my work done better. I work in real estate; lots of moving parts, lots of paperwork, lots of communication. I just want to be more organized and less stressed."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | unsure | neutral |
| P1-5 multi-user | unsure | neutral |
| P1-6 thinking-partner | unsure | neutral |
| P1-7 external-software | unsure | neutral |

**Step 02 fallback probes fire** (LOW confidence at step 01):

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory | unsure | neutral |
| P02-FB-2 regular-pattern | unsure | neutral |
| P02-FB-3 operator-confirm | yes | strong-positive for markdown-agents-friendly |
| P02-FB-4 document-output | yes | strong-positive for markdown-agents / claude-skills |

After step 02: markdown-agents has 2 strong-positives (Probes 7 + 8); no other shape has any strong-positives → signals scattered but markdown-friendly. Confidence = LOW (only 2 strong-positives + 6 unsure answers = scattered signal density).

**Step 03 UP-6 regulatory exposure:** None.

## Expected classifier emit

```yaml
shape_hypothesis:
  shape: unknown
  confidence: low
  detected_at_step: 02
  v1_supported: false
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: true
  operator_signals: # 8 probes; 6 unsure
  forward_offered_signals_at_step_01: []
  fallback_mode_offered: not_offered
```

**Design note (anticipated IDQ-055):** when operator emits `unknown` + `forced_recheck_at_step_05: true`, this is the "operator doesn't know shape yet" case anticipated at Stage 2 planning. IDQ-055 calls for a discovery path — interrogating the operator more deeply at this point to surface what kind of system they want. At S2.1 v0, the discovery path is NOT implemented; classifier emits `unknown` and pre-step-05 re-check re-evaluates with accumulated step 02-04 context. If signals remain insufficient at pre-step-05, the wizard may need to pause and ask operator to describe a similar existing system OR to walk through a typical day where the system would help. Real-data signal on this case binds IDQ-055 to a future slice.

## Expected pre-step-05 re-check

- `forced_recheck_at_step_05: true` → re-check fires regardless of other triggers
- Reads accumulated steps 02 (financial) + 03 (UP-1 to UP-5 + UP-6) + 04 (notifications)
- If step 03 UP-4 (domain expertise) and UP-5 (involvement appetite) signal a single-operator markdown-agents pattern: classifier revises to `markdown-agents` with `confidence: medium`
- If signals remain insufficient: classifier may surface to operator: "Looking at what we've discussed, I'm having trouble pinning down what shape of system to build. Can you describe a similar existing tool you've seen — or walk me through a typical day where this system would be helpful?"
- This open-ended discovery interaction is currently AD-HOC at S2.1 (no canonical mechanism); IDQ-055 captures the gap

## Discrimination note

This fixture exercises the LOW-confidence emit path + forced re-check at step 05. Real-operator data on this case may surface during a known-tester slice (E-α) or during the first non-self operator engagement post-S2.1.
