---
fixture_id: s04-node-ui-clean
schema_version: fixture-replay-v1
fixture_class: shape
target_shape: node-ui
expected_confidence: high
expected_emit_step: 02
expected_halt: false
notes: Canonical Node+UI fixture — multi-user system with logins and a browser interface. RE-DERIVED at F6 (2026-06-02) — non-markdown intent now carried by multi-user + inbound (people sign in / connect live), NOT by the old "continuous-runtime" probe.
---

# Fixture s04 — node-ui (clean signal)

## Synthetic operator inputs

**P1-1 (project name):** "Client portal"

**P1-2 (core purpose):** "I want a website where my clients can log in, see their account status, upload documents, and message us. My team and I would also log in to manage everything."

**Step 01 capabilities beat:**

| Question | Answer | F6 signal |
|---|---|---|
| thinking-partner (`probe_3`) | no | strong-negative for markdown-agents / claude-skills |
| runtime (leveled) → `runtime_mode` | all the time ("it's a site people use whenever; it stays up") | `probe_1_scheduled_cadence = no`, `probe_9_always_on = yes` |
| multi-user (`probe_2`) | yes ("clients and my team each log in with their own access") | strong-positive for node-ui / multi-user-datastore (non-markdown trigger) |
| outbound (`probe_4`) | no | shape-neutral |
| inbound (`probe_10_inbound_serve`) | yes ("clients log in and connect to it as the normal way they use it") | non-markdown integration trigger; node-ui signal |

**Step 02 fallback probes fire** (node-ui has 2 strong-positives at step 01 — `probe_2` + `probe_10` — but so does hosted-cloud via `probe_9` + `probe_2`; ambiguous top → MEDIUM):

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory (`probe_5`) | yes | datastore — supports node-ui AND multi-user-datastore |
| P02-FB-2 regular-pattern (`probe_6`) | no | weak |
| P02-FB-3 operator-confirm (`probe_7`) | no | weak |
| P02-FB-4 document-output (`probe_8`) | no | weak |

After step 02: node-ui has 3 strong-positives (`probe_2` + `probe_10` + `probe_5`) → HIGH.

**Step 03 UP-6 regulatory exposure:** domestic clients assumed → `gdpr_applicable: no`; `no_compliance_claim: yes`.

## Expected classifier emit (step 02)

```yaml
shape_hypothesis:
  shape: node-ui
  confidence: high
  detected_at_step: 02
  v1_supported: false
  fallback_mode_offered: not_offered
  # operator_signals (10 probes): probe_1_scheduled_cadence no, probe_2_multi_user yes,
  # probe_3_thinking_partner no, probe_4_external_software no, probe_5_state_memory yes,
  # probe_9_always_on yes, probe_10_inbound_serve yes
  forward_offered_signals_at_step_01: ["website where my clients can log in"]
```

## Expected pre-step-05 re-check

Unsupported-shape transition fires (node-ui not v1-supported). Operator picks scope-out or foundation-only.

## Discrimination note (F6)

The node-ui signal is now carried by **multi-user (`probe_2`) + inbound/serving (`probe_10`)** — people sign in and connect to it as the normal way they use it, which is exactly the live-serving that markdown can't do (the markdown-agents execution model). `probe_9_always_on` reinforces it. node-ui vs multi-user-datastore is resolved by `probe_10` (a served UI). Pre-F6 this fixture leaned on `probe_1=yes` "continuous-runtime" as the discriminator; that signal is now shape-neutral, so the non-markdown intent is correctly expressed through the live-serving/multi-user triggers instead.
