---
fixture_id: sc02-gdpr-markdown-halt
fixture_class: stop-condition
target_stop_condition: 2
expected_shape: markdown-agents
expected_confidence: high
expected_emit_step: 01
expected_recheck_outcome: halted
expected_halt: true
notes: Stop condition 2 — GDPR-applicable AND shape == markdown-agents (no DSR workflow). Halt at pre-step-05.
---

# Fixture sc02 — GDPR + markdown-agents halt

## Synthetic operator inputs

**P1-1 (project name):** "EU customer correspondence drafter"

**P1-2 (core purpose):** "I run a small consultancy with clients across the EU. I want Claude to help me draft client correspondence — review my drafts for clarity and tone, customize per client based on their files I'd give Claude access to. Just me using it; one operator."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | no | strong-positive markdown |
| P1-5 multi-user | no | strong-positive markdown |
| P1-6 thinking-partner | yes | strong-positive markdown |
| P1-7 external-software | no | strong-positive markdown |

**Step 02 probes:** not fired.

**Step 03 UP-6 regulatory exposure:**

UP-6.1: operator marks #2 (Personal data of people in the EU/EEA).
UP-6.2 follow-up: "I'm a data controller — I collect and use my clients' personal data to provide my consulting services."

Store `gdpr_applicable: yes`.

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

- Condition 2: `gdpr_applicable == yes` AND `shape == markdown-agents` (DSR workflow not present) → **HALT**

Append:

```yaml
shape_hypothesis:
  recheck_log:
    - step: 05
      outcome: halted
      stop_condition_fired: 2
      halt_message: "This system as designed does not meet GDPR compliance. The chosen shape (markdown agents) does not have a DSR (Data Subject Request) workflow. GDPR Article 12-23 require enforceable DSR endpoints. Either change the shape OR commit to an operator-side compliance review."
```

## Discrimination note

Markdown agents on Claude Code do not have native DSR endpoints — the system would store EU client data in agent-prompt context + staging files, but the wizard doesn't generate DSR (access / correction / deletion / portability) workflows for that data. Per D1 § 6.4, DSR endpoints require enforceable implementation; markdown-shape doesn't provide them.

Operator-side compliance review path: the operator may commit to manual DSR-handling (e.g., "I'll respond to DSR requests manually within Article 12 deadlines using my own records") — this is an operator-side compliance posture, not a system-level enforcement. The wizard's foundation docs (if foundation-only chosen) capture this commitment honestly.
