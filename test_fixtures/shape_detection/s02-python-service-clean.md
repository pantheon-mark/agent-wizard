---
fixture_id: s02-python-service-clean
schema_version: fixture-replay-v1
fixture_class: shape
target_shape: python-service-operator-facing
expected_confidence: high
expected_emit_step: 01
expected_halt: false
notes: Canonical Python-service fixture — RE-AUTHORED at F6 (2026-06-02). The old scenario (scheduled inventory check + outbound email) is now correctly markdown under F6, so python-service intent is preserved via genuine non-markdown triggers — an ALWAYS-ON service that receives live inbound events. Detected non-markdown; unsupported-shape transition fires.
---

# Fixture s02 — python-service-operator-facing (clean signal)

## Synthetic operator inputs

**P1-1 (project name):** "Order watcher"

**P1-2 (core purpose):** "I need something that stays running all the time and reacts the moment an order comes in from our store — our store's system pushes each order to it live, and it has to respond within a second or two to reserve stock. It can't just check every few minutes; it has to be connected and listening."

**Step 01 capabilities beat:**

| Question | Answer | F6 signal |
|---|---|---|
| thinking-partner (`probe_3`) | no | strong-negative for markdown-agents / claude-skills |
| runtime (leveled) → `runtime_mode` | **all the time** ("stays running, reacts within a second or two") | `probe_1_scheduled_cadence = no`, `probe_9_always_on = yes` (the non-markdown RUNTIME trigger) |
| multi-user (`probe_2`) | no | single-operator |
| outbound (`probe_4`) | yes ("reserve stock in our system") | shape-neutral |
| inbound (`probe_10_inbound_serve`) | yes ("our store pushes each order to it live; it has to be connected and listening") | non-markdown integration trigger |

**Step 02 probes:** not fired (HIGH confidence at step 01).

**Step 03 UP-6 regulatory exposure:** None.

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
  shape: python-service-operator-facing
  confidence: high
  detected_at_step: 01
  v1_supported: false
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals:
    probe_1_scheduled_cadence: no
    probe_2_multi_user: no
    probe_3_thinking_partner: no
    probe_4_external_software: yes
    probe_5_state_memory: not_asked
    probe_6_regular_pattern: not_asked
    probe_7_operator_confirm: not_asked
    probe_8_document_output: not_asked
    probe_9_always_on: yes
    probe_10_inbound_serve: yes
  forward_offered_signals_at_step_01: ["stays running all the time", "reacts the moment an order comes in", "connected and listening"]
  fallback_mode_offered: not_offered
```

Also recorded to the event transcript: qid `P1-4`, group `orchestration_build`, value `runtime_mode: always-on`.

## Expected pre-step-05 re-check

- No stop conditions fire (no regulatory exposure)
- Initial shape is non-markdown at HIGH confidence → unsupported-shape transition fires per `wizard/shape_detection.md` § 6
- Wizard offers (a) scope-out / (b) foundation-only
- Foundation state preserved

## Confidence rationale (F6)

Top shape (python-service-operator-facing) has 2 strong-positives (`probe_9_always_on` + `probe_10_inbound_serve`) AND a strong-negative for markdown-agents/claude-skills (`probe_3` no) AND no markdown branch (c) eligibility (`probe_9`/`probe_10` are positively fired disqualifiers) → HIGH via § 3 branch (b) (the always-on + inbound positives subsume markdown). **The non-markdown signal is now genuine** — always-on/daemonized + live inbound serving are forbidden for v1 markdown per the markdown-agents execution model. (Contrast s09: scheduled + outbound with the same `probe_4=yes` is markdown, because neither scheduled nor outbound is a non-markdown trigger.)
