---
fixture_id: s04-node-ui-clean
fixture_class: shape
target_shape: node-ui
expected_confidence: high
expected_emit_step: 01
expected_halt: false
notes: Canonical Node+UI fixture — operator wants multi-user system with logins and a browser interface.
---

# Fixture s04 — node-ui (clean signal)

## Synthetic operator inputs

**P1-1 (project name):** "Client portal"

**P1-2 (core purpose):** "I want a website where my clients can log in, see their account status, upload documents, and message us. My team and I would also log in to manage everything."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | yes | strong-positive for python-service / node-ui / hosted-cloud |
| P1-5 multi-user | yes | strong-positive for node-ui / multi-user-datastore |
| P1-6 thinking-partner | no | strong-negative for markdown-agents / claude-skills |
| P1-7 external-software | no | strong-positive for markdown-agents (no) — neutral; markdown ruled out by Probes 1+2 |

**Step 02 probes:** Not fired if step 01 emits HIGH confidence. Given the signals, top shape (node-ui) has 2 strong-positives (Probes 1 + 2); next-closest is multi-user-datastore with 1 (Probe 2). Threshold 2 strong-positives may emit MEDIUM at step 01; fallback fires.

If step 02 fires:

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory | yes | strong-positive for datastore signal — supports node-ui AND multi-user-datastore |
| P02-FB-2 regular-pattern | no | weak signal |
| P02-FB-3 operator-confirm | no | weak signal |
| P02-FB-4 document-output | no | weak signal |

After step 02: node-ui has 3 strong-positives (Probes 1 + 2 + 5) → HIGH confidence emit.

**Step 03 UP-6 regulatory exposure:** Possibly GDPR (operator's clients may include EU residents) — depends on synthetic input setup. For this fixture, set: `gdpr_applicable: no` (clients are domestic-only assumption); `no_compliance_claim: yes`.

## Expected classifier emit (at step 02 if fallback fires; at step 01 if classifier promotes 2-strong-positive non-markdown shapes to HIGH)

```yaml
shape_hypothesis:
  shape: node-ui
  confidence: high
  detected_at_step: 02
  v1_supported: false
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals: # all 8 probes filled
  forward_offered_signals_at_step_01: ["website where my clients can log in"]
  fallback_mode_offered: not_offered
```

## Expected pre-step-05 re-check

Unsupported-shape transition fires (node-ui not v1-supported). Operator picks scope-out or foundation-only.

## Discrimination note

This fixture stress-tests the node-ui-vs-multi-user-datastore boundary. Probe-1 "yes" (continuous-runtime) is the key signal that selects node-ui over plain multi-user-datastore. Without continuous-runtime signal, the system would classify as multi-user-datastore (which is more a datastore-shape descriptor than a complete-system descriptor — node-ui is more specific).
