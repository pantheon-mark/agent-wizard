---
fixture_id: s05-multi-user-datastore-clean
schema_version: fixture-replay-v1
fixture_class: shape
target_shape: multi-user-datastore
expected_confidence: medium
expected_emit_step: 02
expected_halt: false
notes: Multi-user-datastore without web UI — collaborative data system where users access via existing client tools (Notion-like / Airtable-like behavior pattern).
---

# Fixture s05 — multi-user-datastore (clean signal)

## Synthetic operator inputs

**P1-1 (project name):** "Project pipeline tracker"

**P1-2 (core purpose):** "I need a shared system where my team and I can track the status of all our active projects. Each person should see what they're working on; the system should remember everything between sessions. We mostly access through Claude Code on our own machines."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | no | strong-positive for markdown-agents (no) — but multi-user signal will rule that out |
| P1-5 multi-user | yes | strong-positive for node-ui / multi-user-datastore |
| P1-6 thinking-partner | unsure | neutral signal |
| P1-7 external-software | no | strong-positive for standalone-friendly |

**Step 02 fallback probes fire** (MEDIUM confidence at step 01):

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory | yes | strong-positive for datastore signal |
| P02-FB-2 regular-pattern | no | weak signal |
| P02-FB-3 operator-confirm | no | weak signal |
| P02-FB-4 document-output | no | weak signal |

**Step 03 UP-6 regulatory exposure:** None.

## Expected classifier emit

```yaml
shape_hypothesis:
  shape: multi-user-datastore
  confidence: medium
  detected_at_step: 02
  v1_supported: false
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals: # 8 probes filled
  forward_offered_signals_at_step_01: ["shared system where my team and I can track", "remember everything between sessions"]
  fallback_mode_offered: not_offered
```

## Expected pre-step-05 re-check

- Initial emit MEDIUM → re-check is NOT forced (forced_recheck_at_step_05: false) but the unsupported-shape transition fires because shape is non-markdown
- Operator picks scope-out or foundation-only

## Discrimination note

MEDIUM confidence is appropriate here — signals are not as clean as s04 (no continuous-runtime → less specific shape). If operator picked foundation-only and downstream steps revealed continuous-runtime or web-UI signals, pre-step-08 re-check would revise to node-ui or hosted-cloud.
