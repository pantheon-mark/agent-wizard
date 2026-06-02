---
fixture_id: fo01-forward-offered-newsletter
schema_version: fixture-replay-v1
fixture_class: forward-offered
target_shape: markdown-agents
expected_confidence: high
expected_emit_step: 02
expected_halt: false
notes: Forward-offered signals in P1-2 + the F6 reconciliation. RE-CLASSIFIED at F6 (2026-06-02) from python-service to markdown-agents — a scheduled, outbound, document-producing newsletter is exactly what v1 markdown does (cron→Orchestrator + send-script per the markdown-agents execution model). This is the canonical demonstration of the drift F6 fixes (pre-F6 it mis-classified python-service / fired the off-ramp).
---

# Fixture fo01 — Forward-offered signal (newsletter automation) → markdown under F6

## Synthetic operator inputs

**P1-1 (project name):** "Weekly newsletter"

**P1-2 (core purpose):** "I want an automated newsletter that goes out every Monday morning to my email list. The system should pull this week's relevant articles from a few sources I'd point it at, summarize them, format the issue, and send it without me lifting a finger. I'm subscribed to 12 sources I follow."

**Forward-offered signals captured at P1-2** (per `wizard/shape_detection.md` § 9):

- "automated newsletter that goes out every Monday morning" — scheduled (`probe_1_scheduled_cadence` yes) + regular pattern (`probe_6` yes). **F6: both markdown-NEUTRAL** — a scheduled cron→Orchestrator newsletter is markdown.
- "pull ... articles from a few sources" — outbound (`probe_4` yes). **F6: markdown-NEUTRAL** (scripts + step-09 creds).
- "without me lifting a finger" — `probe_7` no (does NOT ask before each action).

**Step 01 capabilities beat:**

| Question | Answer | F6 signal |
|---|---|---|
| thinking-partner (`probe_3`) | no | not a thinking partner |
| runtime (leveled) → `runtime_mode` | scheduled ("goes out every Monday morning") | `probe_1_scheduled_cadence = yes` (neutral), `probe_9_always_on = no` |
| multi-user (`probe_2`) | no | single-operator |
| outbound (`probe_4`) | yes ("pull from sources, send to list") | shape-neutral |
| inbound (`probe_10_inbound_serve`) | no ("nobody connects to it; it just sends") | not a non-markdown trigger |

Frequency clarifier (scheduled): "once a week" — low-frequency, no cost note.

## Expected behavior at end of step 01 (deferred emit)

At step 01 markdown-agents has 0 behavior strong-positives (`probe_3` no; `probe_7`/`probe_8` not yet asked) and 0 strong-negatives (`probe_9`/`probe_10`/`probe_2` all no). Branch (c) needs ≥1 strong-positive → does NOT fire yet. No shape has a positive → LOW/`unknown` provisional → defer to step 02 fallback. (`probe_1_scheduled_cadence` + `probe_4` are shape-neutral, so they contribute nothing for or against any shape.)

**Step 02 fallback probes fire:**

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory (`probe_5`) | no | stateless-friendly |
| P02-FB-2 regular-pattern (`probe_6`) | yes | markdown-friendly under F6 (scheduled cron→Orchestrator), NOT a service signal |
| P02-FB-3 operator-confirm (`probe_7`) | no | autonomous send |
| P02-FB-4 document-output (`probe_8`) | yes | strong-positive for markdown-agents (the newsletter IS a produced document) |

After step 02: markdown-agents has 1 strong-positive (`probe_8` document-output) AND 0 strong-negatives AND every non-markdown trigger is no AND no other shape has ≥2 positives AND no claude-skills reuse signal → **HIGH via § 3 branch (c)**.

## Expected classifier emit (step 02)

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
  detected_at_step: 02
  v1_supported: true
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals:
    probe_1_scheduled_cadence: yes
    probe_2_multi_user: no
    probe_3_thinking_partner: no
    probe_4_external_software: yes
    probe_5_state_memory: no
    probe_6_regular_pattern: yes
    probe_7_operator_confirm: no
    probe_8_document_output: yes
    probe_9_always_on: no
    probe_10_inbound_serve: no
  forward_offered_signals_at_step_01:
    - "automated newsletter that goes out every Monday morning"
    - "pull this week's relevant articles from a few sources I'd point it at"
    - "send it without me lifting a finger"
    - "subscribed to 12 sources I follow"
  fallback_mode_offered: not_offered
```

**Step 03 UP-6 regulatory exposure:** domestic list assumed → `gdpr_applicable: no`; `no_compliance_claim: yes`. (If the operator's list included EU subscribers, GDPR + markdown would fire stop condition 2 at pre-step-05 — see `sc02-gdpr-markdown-halt`.)

## Expected pre-step-05 re-check

Outcome: `confirmed` (markdown-agents, no regulatory exposure). Wizard proceeds; generates a complete markdown-agents system: a cron-invoked Orchestrator that pulls sources, summarizes, formats, and sends the issue via step-09-credentialed scripts.

## Discrimination note (F6)

This fixture is the canonical demonstration of the F6 drift fix. **Pre-F6, `probe_1=yes` (continuous-runtime, scheduled) + `probe_4=yes` (external software) classified this python-service / HIGH and fired the unsupported-shape off-ramp** — wrong, because a scheduled outbound newsletter is exactly what markdown-agents does per the markdown-agents execution model. Post-F6, scheduled + outbound are shape-neutral, and markdown is selected via the document-output positive + absence of disqualifiers. It also exercises the forward-offered capture mechanism (verbatim phrases in `forward_offered_signals_at_step_01`) — which still works; the signals now correctly point at a markdown-deliverable system.
