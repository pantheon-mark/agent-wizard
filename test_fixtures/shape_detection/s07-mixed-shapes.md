---
fixture_id: s07-mixed-shapes
fixture_class: shape
target_shape: mixed
expected_confidence: medium
expected_emit_step: 02
expected_halt: false   # Fixture expected path: operator picks foundation-only at P02-FB-6 → DOCUMENT path, not HALT
expected_stop_conditions_fired: [1]   # Per R3 advisor C-011 cleanup; distinguishes "condition fires" from "wizard halts"
expected_documented_in_foundation: [1]
notes: |
  Mixed shapes — operator wants both a thinking partner AND a background automation. Genuinely two-shape signal. Post-R1+R2 dispositions: capability-based condition 1 fires for mixed shapes with weakest-path audit_trail_crud == advisory; on foundation-only path, condition is DOCUMENTED not HALTED. IDQ-057 candidate CLOSED.
---

# Fixture s07 — mixed (genuine multi-shape signal)

## Synthetic operator inputs

**P1-1 (project name):** "Practice operations"

**P1-2 (core purpose):** "I want two things in one — a thinking partner I can use to review case notes and draft client communications, AND a background system that monitors my email for new client inquiries and triages them while I sleep. The thinking partner is the main thing; the background piece is a helper."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | yes | strong-positive for python-service / hosted-cloud — but contradicts Probe-3 yes signal |
| P1-5 multi-user | no | strong-positive for single-user-friendly |
| P1-6 thinking-partner | yes | strong-positive for markdown-agents / claude-skills |
| P1-7 external-software | yes | strong-positive for python-service |

**Step 02 fallback probes fire** (≥2 shapes have ≥2 strong-positives at step 01):

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory | no | strong-positive for stateless-friendly |
| P02-FB-2 regular-pattern | yes | strong-positive for service signal |
| P02-FB-3 operator-confirm | yes | strong-positive for markdown-agents-friendly |
| P02-FB-4 document-output | yes | strong-positive for markdown-agents / claude-skills |

After step 02: markdown-agents has 4 strong-positives (Probes 3 + 5 no + 7 + 8) but ALSO 2 strong-negatives (Probes 1 + 4 yes). Python-service has 2 strong-positives (Probes 1 + 4) but also 1 strong-negative (Probe 3 yes).

→ Two shape clusters both have ≥2 strong-positives AND neither subsumes the other → `mixed` per § 2.3 decision table.

**Step 03 UP-6 regulatory exposure:** Health information possible (case notes); depends on synthetic setup. For this fixture, set: `hipaa_applicable: yes` (operator is a covered entity — therapist).

## Expected classifier emit (post-R1+R2; includes schema_versions + handoff_phase + status + mixed_component_basis)

```yaml
schema_versions:
  schema_major: 0
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
  operator_signals: # 8 probes
  forward_offered_signals_at_step_01: ["thinking partner I can use", "background system that monitors my email", "while I sleep"]
  mixed_component_basis: ["markdown-agents", "python-service-operator-facing"]   # per advisor R2 C-010
  fallback_mode_offered: not_offered

regulatory_exposure:
  hipaa_applicable: yes
  # ... other frameworks no ...
```

## Expected step 02 unsupported-shape transition (P02-FB-6; post-R1 C-003 disposition)

Shape is non-markdown MEDIUM confidence → P02-FB-6 fires at end of step 02. Operator picks scope-out OR foundation-only.

This fixture's expected path: operator picks foundation-only. `fallback_mode_offered: foundation-only`; wizard proceeds to step 03.

## Expected pre-step-05 re-check (post-R1+R2 capability-based logic; IDQ-057 RESOLVED)

`control_matrix_active` for `mixed` shape uses weakest-path-across-components per `wizard/shape_detection.md` § 8.3:

- markdown-agents component: audit_trail_crud = advisory; encryption_at_rest = provider-enforced + operator-manual
- python-service component: audit_trail_crud = enforced; encryption_at_rest = operator-manual
- **Weakest-path result for mixed: audit_trail_crud = advisory; encryption_at_rest = operator-manual**

Condition 1 evaluation:

- `regulatory_exposure.hipaa_applicable == yes` AND `control_matrix_active.audit_trail_crud != enforced` (it's advisory) → **condition 1 FIRES**

Outcome path (operator chose foundation-only): DOCUMENT path per shape_detection.md § 8.5. Condition 1 recorded under `stop_conditions.documented_in_foundation: [1]`. Downstream foundation-only slice will insert honest HIPAA mismatch text into generated foundation docs. No HALT.

If operator had been on full-system-generation path (theoretical; markdown shape only): HALT path with condition 1 message verbatim.

## Discrimination note (IDQ-057 RESOLVED)

`mixed` shape was the test case for the IDQ-057 candidate (stop-condition exact-match vs capability-match). The capability-based stop conditions (per advisor R1 C-002 disposition) resolve it cleanly: condition 1 fires on `audit_trail_crud != enforced` regardless of shape label. For `mixed` shapes, weakest-path-across-components ensures the system fails on the most-permissive constituent path. This is the conservative correct behavior — regulated data MUST flow through enforced-audit-trail components; if any component is below enforced, the system fails.

**IDQ-057 candidate CLOSED at S2.1 R2 advisor pass.** No standalone IDQ filing needed.
