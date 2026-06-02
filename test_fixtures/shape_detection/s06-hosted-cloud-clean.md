---
fixture_id: s06-hosted-cloud-clean
schema_version: fixture-replay-v1
fixture_class: shape
target_shape: hosted-cloud
expected_confidence: high
expected_emit_step: 02
expected_halt: false
notes: Hosted-cloud fixture — multi-user web product, always-on, database, integrations. RE-DERIVED at F6 (2026-06-02) — non-markdown intent now carried by always-on + multi-user + datastore + live sign-in, NOT by the old "continuous-runtime" probe alone.
---

# Fixture s06 — hosted-cloud (clean signal)

## Synthetic operator inputs

**P1-1 (project name):** "Booking SaaS"

**P1-2 (core purpose):** "I want a hosted product where therapists sign up, manage their client bookings, send automated reminders by SMS, and integrate with Google Calendar. Multiple therapists per practice, multiple practices, all running 24/7 in the cloud."

**Step 01 capabilities beat:**

| Question | Answer | F6 signal |
|---|---|---|
| thinking-partner (`probe_3`) | no | strong-negative for markdown-agents / claude-skills |
| runtime (leveled) → `runtime_mode` | all the time ("running 24/7 in the cloud; therapists hit it anytime") | `probe_1_scheduled_cadence = no`, `probe_9_always_on = yes` |
| multi-user (`probe_2`) | yes ("multiple therapists per practice, multiple practices, each with their own access") | non-markdown trigger |
| outbound (`probe_4`) | yes ("integrate with Google Calendar; send SMS") | shape-neutral |
| inbound (`probe_10_inbound_serve`) | yes ("therapists sign up and log in; it serves them live") | non-markdown trigger |

**Step 02 fallback probes fire** (multiple non-markdown shapes have ≥2 strong-positives → MEDIUM):

| Probe | Answer | Signal |
|---|---|---|
| P02-FB-1 state-memory (`probe_5`) | yes | datastore — supports hosted-cloud / node-ui / multi-user-datastore |
| P02-FB-2 regular-pattern (`probe_6`) | yes | scheduled reminders (markdown-neutral under F6, but consistent with a service that also runs jobs) |
| P02-FB-3 operator-confirm (`probe_7`) | no | weak |
| P02-FB-4 document-output (`probe_8`) | no | weak |

After step 02: hosted-cloud has 3 strong-positives (`probe_9_always_on` + `probe_2` + `probe_5`) plus `probe_10` reinforcing → HIGH (highest signal density of the deferred shapes).

**Step 03 UP-6 regulatory exposure:** "Health information about identifiable people" (#1) — therapist client data. Follow-up: business associate processing ePHI → `hipaa_applicable: yes`.

## Expected classifier emit

```yaml
shape_hypothesis:
  shape: hosted-cloud
  confidence: high
  detected_at_step: 02
  v1_supported: false
  fallback_mode_offered: not_offered
  # operator_signals (10 probes): probe_2 yes, probe_3 no, probe_4 yes, probe_5 yes,
  # probe_9_always_on yes, probe_10_inbound_serve yes; probe_1_scheduled_cadence no
  forward_offered_signals_at_step_01: ["hosted product", "automated reminders by SMS", "integrate with Google Calendar", "all running 24/7 in the cloud"]

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
- Shape is non-markdown → unsupported-shape transition fires
- Operator picks scope-out or foundation-only (foundation docs record HIPAA-applicable + hosted-cloud-deferred posture)

## Discrimination note (F6)

Cleanest non-markdown signal density. Under F6 the non-markdown intent is carried by **always-on (`probe_9`) + multi-user (`probe_2`) + live sign-in (`probe_10`) + datastore (`probe_5`)** — all genuine triggers per the markdown-agents execution model. The outbound Calendar/SMS integration (`probe_4`) is shape-neutral and is NOT what disqualifies markdown here; the always-on/multi-user/serving character is. HIPAA + non-markdown remains the most-common compliance-class pattern; v1 ships with this scope explicitly deferred.
