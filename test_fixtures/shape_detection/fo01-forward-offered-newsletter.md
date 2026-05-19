---
fixture_id: fo01-forward-offered-newsletter
fixture_class: forward-offered
target_shape: python-service-operator-facing
expected_confidence: high
expected_emit_step: 01
expected_halt: false
notes: Operator's P1-2 answer contains strong forward-offered shape signals — wizard captures them; probes confirm the same shape independently.
---

# Fixture fo01 — Forward-offered signal (newsletter automation)

## Synthetic operator inputs

**P1-1 (project name):** "Weekly newsletter"

**P1-2 (core purpose):** "I want an automated newsletter that goes out every Monday morning to my email list. The system should pull this week's relevant articles from a few sources I'd point it at, summarize them, format the issue, and send it without me lifting a finger. I'm subscribed to 12 sources I follow."

**Forward-offered signals captured at P1-2** (per `wizard/shape_detection.md` § 9; classifier scans operator's free-text answer):

- "automated newsletter that goes out every Monday morning" — implies Probe-1 yes (continuous-runtime; scheduled) + Probe-6 yes (regular pattern)
- "pull ... articles from a few sources" — implies Probe-4 yes (talks to other software)
- "without me lifting a finger" — implies Probe-7 no (does NOT ask operator before each action)

**Step 01 probes (asked despite forward-offered signals per S2.1 decision E — probes still fire):**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | yes | strong-positive python-service / hosted-cloud / node-ui |
| P1-5 multi-user | no | strong-positive single-user-friendly |
| P1-6 thinking-partner | no | strong-negative markdown-agents / claude-skills |
| P1-7 external-software | yes | strong-positive python-service |

**Step 02 probes:** Step 01 emits HIGH confidence for python-service-operator-facing — 2 strong-positives (Probes 1+4) + 2 strong-negatives ruling out markdown — fallback not strictly needed but classifier may still fire if MEDIUM threshold not met. For this fixture, classifier emits HIGH at step 01 with forward-offered signals as discriminator confirming the shape.

**Step 03 UP-6 regulatory exposure:** GDPR potentially applicable (newsletter subscribers may include EU residents). Follow-up: "Are you/your organization a data controller of subscriber personal data?" → yes (operator controls subscriber list). Store `gdpr_applicable: yes`.

## Expected classifier emit (at end of step 01)

```yaml
shape_hypothesis:
  shape: python-service-operator-facing
  confidence: high
  detected_at_step: 01
  v1_supported: false
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: false
  operator_signals:
    probe_1_continuous_runtime: yes
    probe_2_multi_user: no
    probe_3_thinking_partner: no
    probe_4_external_software: yes
    probe_5_state_memory: not_asked
    probe_6_regular_pattern: not_asked
    probe_7_operator_confirm: not_asked
    probe_8_document_output: not_asked
  forward_offered_signals_at_step_01:
    - "automated newsletter that goes out every Monday morning"
    - "pull this week's relevant articles from a few sources I'd point it at"
    - "send it without me lifting a finger"
    - "subscribed to 12 sources I follow"
  fallback_mode_offered: not_offered

regulatory_exposure:
  gdpr_applicable: yes
  hipaa_applicable: no
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: no
  no_compliance_claim_framework_identification: no
```

## Expected pre-step-05 re-check

- Stop conditions: GDPR-applicable + shape is `python-service-operator-facing` (not markdown-agents) → condition 2 does NOT fire (condition 2 requires markdown-agents)
- Shape is non-markdown → unsupported-shape transition fires
- Operator picks scope-out or foundation-only

If foundation-only: the generated foundation-doc set includes GDPR-applicable + python-service-deferred posture explicitly per D1 § 6.2 honest characterization rule.

## Discrimination note

Forward-offered signals from P1-2 alone (without probes) would already strongly suggest python-service-operator-facing. The probes confirm independently. The classifier treats forward-offered signals as interpretive prior only (per decision E) — probes are canonical. In this fixture, both data sources agree, which is the easy case. The harder case (forward-offered signals contradict probes — operator's free-text vs. their explicit answers) is NOT tested at v0; bind to first-real-operator-data signal.

This fixture also exercises the forward-offered signal capture mechanism (per wizard CLAUDE.md § 9 + `wizard/shape_detection.md` § 9 integration). Classifier should populate `forward_offered_signals_at_step_01` with verbatim phrases from operator's P1-2 answer.
