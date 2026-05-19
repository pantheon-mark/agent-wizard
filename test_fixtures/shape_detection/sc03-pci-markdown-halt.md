---
fixture_id: sc03-pci-markdown-halt
fixture_class: stop-condition
target_stop_condition: 3
expected_shape: markdown-agents
expected_confidence: high
expected_emit_step: 01
expected_recheck_outcome: halted
expected_halt: true
notes: Stop condition 3 — PCI-DSS-applicable AND shape provides encryption-at-rest not at `enforced`. Halt at pre-step-05.
---

# Fixture sc03 — PCI-DSS + markdown-agents halt

## Synthetic operator inputs

**P1-1 (project name):** "Merchant transaction reviewer"

**P1-2 (core purpose):** "I run a small e-commerce site. I want Claude to help me review unusual transactions — when something looks fishy, I want to paste in the transaction details (including the card number we're trying to authorize) and have Claude flag patterns suggesting fraud. Just me using it on my laptop."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | no | strong-positive markdown |
| P1-5 multi-user | no | strong-positive markdown |
| P1-6 thinking-partner | yes | strong-positive markdown |
| P1-7 external-software | no | strong-positive markdown |

**Step 02 probes:** not fired.

**Step 03 UP-6 regulatory exposure:**

UP-6.1: operator marks #3 (Credit card or payment card numbers).
UP-6.2 follow-up: "I'm a merchant accepting card payments — subject to PCI-DSS through my card brand."

Store `pci_dss_applicable: yes`.

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

- Condition 3: `pci_dss_applicable == yes` AND shape provides encryption-at-rest not at `enforced` → **HALT**
- For markdown-agents shape, per D1 § 2.2, encryption-at-rest is `provider-enforced + operator-manual` (NOT `enforced`)

Append:

```yaml
shape_hypothesis:
  recheck_log:
    - step: 05
      outcome: halted
      stop_condition_fired: 3
      halt_message: "This system as designed does not meet PCI-DSS compliance. The chosen shape provides encryption-at-rest at `provider-enforced` or `operator-manual`, not `enforced`. PCI-DSS requires deterministic encryption-at-rest. Either change the shape OR commit to an operator-side compliance review."
```

## Discrimination note

PCI-DSS § 3.5 requires merchants to protect stored cardholder data with "strong cryptography" using documented key management. Markdown-agents shape stores operator input (including any card numbers pasted into Claude prompts) in agent-prompt context + Claude transcripts. Provider-enforced encryption-at-rest (Anthropic infrastructure) is good but not auditable at operator's deterministic level; operator-manual encryption (FileVault for local transcripts) is operator-discretion. Neither meets PCI-DSS deterministic-encryption-at-rest requirement.

**Stronger discriminator alternative:** operator may also fail PCI-DSS § 4 (encryption in transit between operator + Anthropic + back) — but that's provider-enforced (TLS); not the failure point. The audit-trail point (PCI-DSS § 10) is also a failure for markdown-agents (advisory only). Multi-control PCI failures are typical for markdown-shape; the halt message focuses on encryption-at-rest as the most-visible failure.

Operator-side compliance review path: operator may commit to NEVER pasting full PAN (primary account numbers) into Claude prompts — using truncated forms (last 4 digits) for review. This is an operator-side compliance posture; foundation docs capture the commitment.
