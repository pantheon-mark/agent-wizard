---
fixture_id: s06-hosted-cloud-clean
fixture_class: shape
target_shape: hosted-cloud
expected_confidence: high
expected_emit_step: 02
expected_halt: false
notes: Hosted-cloud fixture — multi-user web product with database, continuous runtime, integrations.
---

# Fixture s06 — hosted-cloud (clean signal)

## Synthetic operator inputs

**P1-1 (project name):** "Booking SaaS"

**P1-2 (core purpose):** "I want a hosted product where therapists can sign up, manage their client bookings, send automated reminders by SMS, and integrate with Google Calendar. Multiple therapists per practice, multiple practices, all running 24/7 in the cloud."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | yes | strong-positive for hosted-cloud / node-ui / python-service |
| P1-5 multi-user | yes | strong-positive for hosted-cloud / node-ui / multi-user-datastore |
| P1-6 thinking-partner | no | strong-negative for markdown-agents / claude-skills |
| P1-7 external-software | yes | strong-positive for python-service / hosted-cloud |

**Step 02 fallback probes fire** (multiple shapes have ≥2 strong-positives at step 01 → MEDIUM):

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory | yes | strong-positive for datastore — supports hosted-cloud / node-ui / multi-user-datastore |
| P02-FB-2 regular-pattern | yes | strong-positive for service signal |
| P02-FB-3 operator-confirm | no | weak signal |
| P02-FB-4 document-output | no | weak signal |

After step 02: hosted-cloud has 5 strong-positives (Probes 1 + 2 + 4 + 5 + 6) → HIGH.

**Step 03 UP-6 regulatory exposure:** "Health information about identifiable people" (#1) — therapist client data implies potential HIPAA exposure. Follow-up: "Are you/the system acting as a healthcare provider, insurance plan, clearinghouse, or business associate?" → answer: yes, business associate (therapists are covered entities; the SaaS processes ePHI on their behalf). Store `hipaa_applicable: yes`.

## Expected classifier emit

```yaml
shape_hypothesis:
  shape: hosted-cloud
  confidence: high
  detected_at_step: 02
  v1_supported: false
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals: # 8 probes
  forward_offered_signals_at_step_01: ["hosted product", "automated reminders by SMS", "integrate with Google Calendar", "all running 24/7 in the cloud"]
  fallback_mode_offered: not_offered

regulatory_exposure:
  hipaa_applicable: yes
  gdpr_applicable: no
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: no
  no_compliance_claim_framework_identification: no
```

## Expected pre-step-05 re-check

- HIPAA applicable + shape is `hosted-cloud` (not markdown-agents) → stop condition 1 does NOT fire (condition 1 requires shape == markdown-agents)
- BUT shape is non-markdown → unsupported-shape transition fires
- Operator picks scope-out or foundation-only

**Foundation-only path note:** if operator picks foundation-only, the generated foundation docs (vision / approach / etc.) should INCLUDE explicit HIPAA-applicable + hosted-cloud-deferred posture, so the operator's downstream Claude Code build conversation has the compliance context. Implementation of this foundation-only-mode behavior is OUT of S2.1 (per decision F).

## Discrimination note

This fixture is the cleanest non-markdown signal density (5 strong-positives for top shape). HIPAA + non-markdown is the most-common compliance-class workload pattern; v1 ships with this scope explicitly deferred per PRD § 4.5 (un-defer trigger = wizard-side end-to-end hosted-cloud production demonstrated for non-technical operators with multi-month operational stability).
