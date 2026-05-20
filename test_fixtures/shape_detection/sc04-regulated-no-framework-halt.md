---
fixture_id: sc04-regulated-no-framework-halt
schema_version: fixture-replay-v1
fixture_class: stop-condition
target_stop_condition: 4
expected_shape: markdown-agents
expected_confidence: high
expected_emit_step: 01
expected_recheck_outcome: halted
expected_halt: true
notes: Stop condition 4 — Operator says "regulated" but cannot identify which framework. Halt at pre-step-05 for operator-side compliance review.
---

# Fixture sc04 — Regulated but no framework identification halt

## Synthetic operator inputs

**P1-1 (project name):** "Compliance helper"

**P1-2 (core purpose):** "I work in financial services. I want Claude to help me review client communications before they go out — make sure they're compliant with the rules. The rules are complicated; I'm not always sure which ones apply, but I know there's a lot of regulation in my industry."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | no | strong-positive markdown |
| P1-5 multi-user | no | strong-positive markdown |
| P1-6 thinking-partner | yes | strong-positive markdown |
| P1-7 external-software | no | strong-positive markdown |

**Step 02 probes:** not fired.

**Step 03 UP-6 regulatory exposure:**

UP-6.1: operator marks #6 (Other regulated data) — financial services, regulation is "complicated."
UP-6.2 follow-up: "Which framework applies? Common ones: FERPA, GLBA, FedRAMP, NIS2, sector-specific..." → operator answer: "I know there are rules but I'm not sure which apply specifically — SEC stuff for our broker-dealer side, FINRA rules, maybe state-level regulations."

Store: `other_sector_specific: [{framework: "Multiple — SEC / FINRA / state-level; not yet identified", applicable: yes}]` AND `no_compliance_claim_framework_identification: unknown`.

## Expected classifier emit (at end of step 01)

```yaml
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  detected_at_step: 01
  v1_supported: true
```

## Expected pre-step-05 re-check

**Stop-condition evaluation fires:**

- Condition 4: ANY framework marked applicable AND `no_compliance_claim_framework_identification == unknown` → **HALT**

Append:

```yaml
shape_hypothesis:
  recheck_log:
    - step: 05
      outcome: halted
      stop_condition_fired: 4
      halt_message: "You've indicated this system handles regulated data, but we haven't identified which specific framework (HIPAA / GDPR / PCI / sector-specific). Before generating, please complete an operator-side compliance review to identify the applicable framework; the wizard will halt here."
```

## Discrimination note

Stop condition 4 is the "no compliance claim by default" safety net per D1 § 6.2. The wizard MUST NOT silently produce a system that LOOKS compliant without an operator commitment.

When operator can't identify the framework specifically, the wizard halts to force operator-side resolution. Path forward:

- Operator returns later with framework identified → wizard re-runs, this time the specific framework is captured, and conditions 1-3 evaluate as normal (likely also halt for markdown shape if framework is one of the heavy-hitters)
- Operator concludes after review that no specific framework applies (e.g., the financial-services rules don't actually impose tech-stack requirements for this particular use case) → wizard re-runs with `no_compliance_claim: yes`; proceeds without halt

This is the most-operator-friendly halt because it surfaces a question the operator should answer outside the wizard — getting professional compliance review — rather than asking the wizard to assert applicability the operator themselves doesn't yet know.

## Discrimination note (v0 vs operator self-categorization)

A risk of this stop condition: operator may bypass it by saying "none of the above" at UP-6.1 even when their domain implies regulation. The wizard cannot force operator self-knowledge. The honest characterization rule (D1 § 2.3) is the upstream protection — the generated system's documents will EXPLICITLY state "this system makes NO compliance claim" so operator + downstream reviewers see the gap.
