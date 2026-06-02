---
fixture_id: s07-mixed-shapes
schema_version: fixture-replay-v1
fixture_class: shape
target_shape: mixed
expected_confidence: medium
expected_emit_step: 02
expected_halt: false   # Fixture expected path: operator picks foundation-only at P02-FB-6 → DOCUMENT path, not HALT
expected_stop_conditions_fired: [1]
expected_documented_in_foundation: [1]
notes: |
  Mixed shapes — a thinking partner (markdown) AND a live always-on email responder (non-markdown). RE-DERIVED at F6 (2026-06-02): the automation component must carry a GENUINE non-markdown trigger (always-on + inbound) to stay mixed — a merely scheduled+outbound helper would now be markdown under F6 and the system would NOT be mixed. Capability-based condition 1 fires for the markdown component (weakest-path audit_trail_crud == advisory); on foundation-only path the condition is DOCUMENTED not HALTED.
---

# Fixture s07 — mixed (genuine multi-shape signal)

## Synthetic operator inputs

**P1-1 (project name):** "Practice operations"

**P1-2 (core purpose):** "I want two things in one — a thinking partner I can use to review case notes and draft client communications, AND a piece that watches my email inbox constantly and replies to new client inquiries within seconds, day and night, while I sleep. The thinking partner is the main thing; the always-on responder is a helper."

**Step 01 capabilities beat:**

| Question | Answer | F6 signal |
|---|---|---|
| thinking-partner (`probe_3`) | yes | strong-positive for markdown-agents / claude-skills |
| runtime (leveled) → `runtime_mode` | all the time ("watches my inbox constantly, replies within seconds, day and night") | `probe_1_scheduled_cadence = no`, `probe_9_always_on = yes` (non-markdown trigger — the always-on responder) |
| multi-user (`probe_2`) | no | single-user |
| outbound (`probe_4`) | yes ("send replies") | shape-neutral |
| inbound (`probe_10_inbound_serve`) | yes ("react to each incoming email live") | non-markdown trigger |

**Step 02 fallback probes fire** (markdown has 1 positive (`probe_3`) + 2 strong-negatives (`probe_9` + `probe_10`); the service cluster has 2 positives — ambiguous, neither cluster yet ≥2 markdown positives → MEDIUM):

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory (`probe_5`) | no | stateless-friendly |
| P02-FB-2 regular-pattern (`probe_6`) | no | (the responder is always-on/reactive, not a fixed schedule) |
| P02-FB-3 operator-confirm (`probe_7`) | yes | strong-positive for markdown-agents-friendly |
| P02-FB-4 document-output (`probe_8`) | yes | strong-positive for markdown-agents / claude-skills |

After step 02: **markdown-agents cluster** has 3 strong-positives (`probe_3` + `probe_7` + `probe_8`); **service cluster** (python-service-operator-facing) has 2 strong-positives (`probe_9_always_on` + `probe_10_inbound_serve`). Two clusters each ≥2 strong-positives AND neither subsumes the other → `mixed` per § 2.3.

**Step 03 UP-6 regulatory exposure:** Health information (case notes) → operator is a covered entity (therapist) → `hipaa_applicable: yes`.

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
  shape: mixed
  confidence: medium
  detected_at_step: 02
  v1_supported: false
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals: # 10 probes; probe_3 yes, probe_7 yes, probe_8 yes, probe_9_always_on yes, probe_10_inbound_serve yes, probe_2 no, probe_4 yes, probe_1_scheduled_cadence no, probe_5 no, probe_6 no
  forward_offered_signals_at_step_01: ["thinking partner I can use", "watches my email inbox constantly", "replies ... within seconds, day and night"]
  mixed_component_basis: ["markdown-agents", "python-service-operator-facing"]
  fallback_mode_offered: not_offered

regulatory_exposure:
  hipaa_applicable: yes
  # ... other frameworks no ...
```

## Expected step 02 unsupported-shape transition (P02-FB-6)

Shape is non-markdown (`mixed`) MEDIUM confidence → P02-FB-6 fires at end of step 02. Operator picks scope-out OR foundation-only. This fixture's path: foundation-only. `fallback_mode_offered: foundation-only`; wizard proceeds to step 03.

## Expected pre-step-05 re-check (capability-based)

`control_matrix_active` for `mixed` uses weakest-path-across-components per § 8.3:

- markdown-agents component: audit_trail_crud = advisory; encryption_at_rest = provider-enforced + operator-manual
- python-service component: audit_trail_crud = enforced; encryption_at_rest = operator-manual
- **Weakest-path: audit_trail_crud = advisory; encryption_at_rest = operator-manual**

Condition 1: `hipaa_applicable == yes` AND `audit_trail_crud != enforced` (advisory) → **fires**. Operator on foundation-only path → DOCUMENT path (§ 8.5); recorded under `stop_conditions.documented_in_foundation: [1]`; no HALT.

## Discrimination note (F6)

The F6 reconciliation makes this fixture's mixed-ness depend on a genuine non-markdown trigger: the email responder is **always-on + inbound** (`probe_9` + `probe_10`), which markdown cannot do (the markdown-agents execution model). A merely *scheduled* inbox check that drafts outbound replies would, post-F6, be markdown — and the system would then be wholly markdown, not mixed. The capability-based condition 1 still fires on the weakest (markdown) component's advisory audit trail.
