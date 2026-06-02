---
fixture_id: s09-scheduled-outbound-agent
schema_version: fixture-replay-v1
fixture_class: shape
target_shape: markdown-agents
expected_confidence: high
expected_emit_step: 01
expected_halt: false
notes: F6 positive fixture (2026-06-02) — a SCHEDULED + OUTBOUND thinking-partner agent (the estate-executor walk-through case). Pre-F6 this mis-classified python-service / MEDIUM and fired the unsupported-shape off-ramp; post-F6 scheduled execution + outbound integration are markdown-fine (the markdown-agents execution model), so it classifies markdown-agents HIGH via § 3 branch (c) absence-of-disqualifiers.
---

# Fixture s09 — scheduled + outbound markdown agent (F6 reconciliation)

## Synthetic operator inputs

**P1-1 (project name):** "Estate helper"

**P1-2 (core purpose):** "I'm co-executor of my mom's estate with my brother. I want something to keep a master task list so nothing slips, capture notes from calls with the lawyer and bank, help me figure out next steps and draft the letters I have to send, remind me about deadlines when I'm not paying attention, and read and update the spreadsheet I already keep the accounts in."

**Step 01 capabilities beat:**

| Question | Answer | F6 signal |
|---|---|---|
| thinking-partner (`probe_3`) | yes | strong-positive for markdown-agents |
| runtime (leveled) → `runtime_mode` | **scheduled** ("it should wake up, check deadlines, and send me reminders, then be done") | `probe_1_scheduled_cadence = yes` (SHAPE-NEUTRAL — markdown-fine, cron→Orchestrator per the markdown-agents execution model), `probe_9_always_on = no` |
| multi-user (`probe_2`) | no ("just me — my brother reads the spreadsheet, but he doesn't log into the system") | not a non-markdown trigger |
| outbound (`probe_4`) | yes ("read and write my Google Sheet, send emails") | SHAPE-NEUTRAL (markdown reaches out via scripts + step-09 creds) |
| inbound (`probe_10_inbound_serve`) | no ("nobody else connects to it; it doesn't receive live pushes") | not a non-markdown trigger |

Frequency clarifier (runtime = scheduled): "a couple of times a day" — low-frequency, no cost note needed.

**Step 02 probes:** not fired (HIGH confidence at step 01).

**Step 03 UP-6 regulatory exposure:** None (operator says #7 "None of the above").

## Expected classifier emit

```yaml
schema_versions:
  schema_major: 1
  schema_minor: 0
  shape_taxonomy_version: 0
  stop_condition_set_version: 0
  control_matrix_schema_version: 0

handoff_phase: provisional_shape_emit

shape_hypothesis:
  status: emitted
  shape: markdown-agents
  confidence: high
  detected_at_step: 01
  v1_supported: true
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals:
    probe_1_scheduled_cadence: yes
    probe_2_multi_user: no
    probe_3_thinking_partner: yes
    probe_4_external_software: yes
    probe_5_state_memory: not_asked
    probe_6_regular_pattern: not_asked
    probe_7_operator_confirm: not_asked
    probe_8_document_output: not_asked
    probe_9_always_on: no
    probe_10_inbound_serve: no
  forward_offered_signals_at_step_01: ["remind me about deadlines", "read and update the spreadsheet I already keep the accounts in"]
  fallback_mode_offered: not_offered
```

Also recorded to the event transcript: qid `P1-4`, group `orchestration_build`, value `runtime_mode: scheduled`.

## Expected pre-step-05 re-check

Outcome: `confirmed`. No stop conditions fire (no regulatory exposure). No contradicting signals from steps 02-04.

## Expected wizard behavior

Wizard proceeds normally through all 16 steps and generates a complete markdown-agents system at step 15: an Orchestrator invoked on a cron schedule (deadline reminders) that reads/writes the Google Sheet and drafts emails via step-09-credentialed scripts, plus the operator-invoked thinking-partner path.

## Confidence rationale (F6 branch (c))

Per `wizard/shape_detection.md` § 3 HIGH branch (c): `markdown-agents` has 1 strong-positive (`probe_3` thinking-partner) AND 0 strong-negatives (`probe_9_always_on` / `probe_10_inbound_serve` / `probe_2` all no) AND no other shape has ≥2 strong-positives AND no claude-skills packaging/reuse signal is present → HIGH at step 01. `probe_1_scheduled_cadence` (scheduled) and `probe_4` (outbound) are shape-neutral and do NOT push the system off markdown — this is the whole point of the F6 reconciliation. **Pre-F6, `probe_1=yes`/`probe_4=yes` made this python-service/MEDIUM and fired the unsupported-shape transition; that was the drift from the markdown-agents execution model this fixture guards against.**
