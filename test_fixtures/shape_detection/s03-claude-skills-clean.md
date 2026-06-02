---
fixture_id: s03-claude-skills-clean
schema_version: fixture-replay-v1
fixture_class: shape
target_shape: claude-skills
expected_confidence: high
expected_emit_step: 02
expected_halt: false
notes: Canonical Claude-skills fixture — operator wants a reusable thinking-partner capability packaged for use across many conversations. F6 (2026-06-02) field-rename + the markdown-vs-skills guard on § 3 branch (c) — the claude-skills packaging/reuse signal suppresses branch (c) at step 01, so the discrimination resolves at step-02 fallback exactly as before F6.
---

# Fixture s03 — claude-skills (clean signal)

## Synthetic operator inputs

**P1-1 (project name):** "Brief drafter"

**P1-2 (core purpose):** "I want to package up my way of writing client briefs so I can pull it into different Claude conversations. It's a thinking partner I bring to any client engagement — I want it to ask the right questions, produce a draft, and let me decide whether to send."

**Step 01 capabilities beat:**

| Question | Answer | F6 signal |
|---|---|---|
| thinking-partner (`probe_3`) | yes | strong-positive for markdown-agents OR claude-skills (they tie) |
| runtime (leveled) → `runtime_mode` | on-demand ("when I pull it into a conversation") | `probe_1_scheduled_cadence = no`, `probe_9_always_on = no` |
| multi-user (`probe_2`) | no | single-user |
| outbound (`probe_4`) | no | shape-neutral |
| inbound (`probe_10_inbound_serve`) | no | not a non-markdown trigger |

**Forward-offered packaging/reuse signal captured at P1-2:** "package up my way of writing" + "pull it into different Claude conversations" → selects `claude-skills` over `markdown-agents` (the markdown-vs-skills discriminator).

## Expected behavior at end of step 01 (deferred emit)

`markdown-agents` and `claude-skills` both match `probe_3` yes (1 strong-positive each) — they tie. § 3 branch (c) does NOT fire because a claude-skills packaging/reuse signal is present (the guard). No unique top shape → MEDIUM confidence; defer emit to step 02.

```yaml
schema_versions:
  schema_major: 1
  schema_minor: 0
  shape_taxonomy_version: 0
  stop_condition_set_version: 0
  control_matrix_schema_version: 0

handoff_phase: provisional_shape_emit

shape_hypothesis:
  status: pending_step_02_fallback
  step_01_signals:
    probe_1_scheduled_cadence: no
    probe_2_multi_user: no
    probe_3_thinking_partner: yes
    probe_4_external_software: no
    probe_9_always_on: no
    probe_10_inbound_serve: no
  step_01_provisional_confidence: medium
  forward_offered_signals_at_step_01: ["package up my way of writing", "pull it into different Claude conversations"]
```

**Step 02 fallback probes fire:**

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory (`probe_5`) | no | stateless-friendly (markdown / skills) |
| P02-FB-2 regular-pattern (`probe_6`) | no | on-demand-friendly (markdown-friendly under F6) |
| P02-FB-3 operator-confirm (`probe_7`) | yes | strong-positive for markdown-agents AND claude-skills |
| P02-FB-4 document-output (`probe_8`) | yes | strong-positive for markdown-agents AND claude-skills |

**Step 02 emit:** markdown and skills tie on probe positives (3 each: probe_3/7/8); the forward-offered "package up / reuse across conversations" signal is the discriminator → `claude-skills` over `markdown-agents`. Confidence HIGH.

```yaml
shape_hypothesis:
  shape: claude-skills
  confidence: high
  detected_at_step: 02
  v1_supported: false
  fallback_mode_offered: not_offered
  # operator_signals: all 10 probes; probe_9_always_on: no, probe_10_inbound_serve: no
```

## Expected pre-step-05 re-check

Initial shape is non-markdown at HIGH confidence → unsupported-shape transition fires. Same handling as s02 (operator picks scope-out OR foundation-only).

## Confidence rationale + F6 note

This fixture exercises the markdown-agents-vs-claude-skills ambiguity, which F6 deliberately preserves. The two shapes share their entire positive set, so they tie on probe counts; the forward-offered packaging/reuse signal is the discriminator. The § 3 branch (c) claude-skills guard is what keeps markdown from prematurely winning at step 01 (without the guard, branch (c) would fire markdown HIGH at step 01 and skip the skills discrimination — and skills is also v1-unsupported, so that mis-selection still matters). Resolution lands at step 02, exactly as before F6.
