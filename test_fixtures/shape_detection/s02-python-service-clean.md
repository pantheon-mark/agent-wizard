---
fixture_id: s02-python-service-clean
schema_version: fixture-replay-v1
fixture_class: shape
target_shape: python-service-operator-facing
expected_confidence: high
expected_emit_step: 01
expected_halt: false
notes: Canonical Python-service-operator-facing fixture — operator wants a continuous-runtime automation that talks to external services. Detected as non-markdown; unsupported-shape transition fires at pre-step-05.
---

# Fixture s02 — python-service-operator-facing (clean signal)

## Synthetic operator inputs

**P1-1 (project name):** "Inventory monitor"

**P1-2 (core purpose):** "I need a system that checks our supplier inventory feeds every hour, flags shortages, and emails our purchasing team. Runs on its own — I shouldn't have to be involved unless something needs my decision."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | yes | strong-positive for python-service / node-ui / hosted-cloud; strong-negative for markdown-agents |
| P1-5 multi-user | no | strong-positive for markdown-agents (no) — neutral here since markdown ruled out |
| P1-6 thinking-partner | no | strong-negative for markdown-agents / claude-skills |
| P1-7 external-software | yes | strong-positive for python-service |

**Step 02 probes:** not fired (HIGH confidence at step 01).

**Step 03 UP-6 regulatory exposure:** None.

## Expected classifier emit

```yaml
shape_hypothesis:
  shape: python-service-operator-facing
  confidence: high
  detected_at_step: 01
  v1_supported: false
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals:
    probe_1_continuous_runtime: yes
    probe_2_multi_user: no
    probe_3_thinking_partner: no
    probe_4_external_software: yes
    probe_5_state_memory: not_asked
    probe_6_regular_pattern: not_asked
    probe_7_operator_confirm: not_asked
    probe_8_document_output: not_asked
  forward_offered_signals_at_step_01: ["checks our supplier inventory feeds every hour", "runs on its own"]
  fallback_mode_offered: not_offered
```

## Expected pre-step-05 re-check

- No stop conditions fire (no regulatory exposure)
- Initial shape is non-markdown at HIGH confidence → unsupported-shape transition fires per `wizard/shape_detection.md` § 6
- Wizard offers (a) scope-out / (b) foundation-only
- Foundation state preserved

## Expected wizard behavior

- If operator picks (a) scope-out: wizard exits cleanly with staging file preserved; `scope_out: <timestamp>` recorded
- If operator picks (b) foundation-only: wizard proceeds with `fallback_mode_offered: foundation-only` flag set (downstream slice implements actual foundation-only behavior across steps 05-15; at a prior slice, the flag is set but the behavior is NOT implemented per decision F)

## Confidence rationale

Top shape (python-service-operator-facing) has 2 strong-positives (Probes 1 + 4) AND 0 strong-negatives AND no other non-markdown shape has ≥2 strong-positives → HIGH. (Markdown-agents has 2 strong-negatives from Probes 1 + 4 yes, ruling it out.)

**Note:** technically by the rubric this is MEDIUM (2 strong-positives, not 3) — but Probe-3 "no" also acts as strong-negative for markdown-agents and claude-skills, which removes those candidates. v0 may need calibration of the HIGH threshold for non-markdown shapes; flagged for first-real-operator-data signal. Recording as HIGH per the discrimination clarity in this fixture.
