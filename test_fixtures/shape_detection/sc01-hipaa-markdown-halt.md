---
fixture_id: sc01-hipaa-markdown-halt
fixture_class: stop-condition
target_stop_condition: 1
expected_shape: markdown-agents
expected_confidence: high
expected_emit_step: 01
expected_recheck_outcome: halted
expected_halt: true
notes: Stop condition 1 — HIPAA-applicable AND shape == markdown-agents. Halt at pre-step-05.
---

# Fixture sc01 — HIPAA + markdown-agents halt

## Synthetic operator inputs

**P1-1 (project name):** "Patient note assistant"

**P1-2 (core purpose):** "I'm a primary care physician. I want to use Claude to help me write up patient encounter notes from my dictation — review my drafts, fix terminology, generate the SOAP-format version, and let me sign off before anything gets stored back to my EMR. Just me using it on my laptop."

**Step 01 probes:**

| Probe | Answer | Signal |
|---|---|---|
| P1-4 continuous-runtime | no | strong-positive for markdown-agents (no) |
| P1-5 multi-user | no | strong-positive for markdown-agents (no) |
| P1-6 thinking-partner | yes | strong-positive for markdown-agents |
| P1-7 external-software | no | strong-positive for markdown-agents (no) |

**Step 02 probes:** not fired (HIGH confidence at step 01; same signal profile as s01).

**Step 03 UP-6 regulatory exposure:**

UP-6.1: operator marks #1 (Health information about identifiable people).
UP-6.2 follow-up for #1: "I'm a healthcare provider (primary care physician). I'd be a covered entity under HIPAA."

Store `hipaa_applicable: yes`.

## Expected classifier emit (at end of step 01)

```yaml
shape_hypothesis:
  shape: markdown-agents
  confidence: high
  detected_at_step: 01
  v1_supported: true
  # ... etc
```

## Expected pre-step-05 re-check

**Stop-condition evaluation fires:**

- Condition 1: `hipaa_applicable == yes` AND `shape == markdown-agents` → **HALT**

Append to staging file:

```yaml
shape_hypothesis:
  recheck_log:
    - step: 05
      timestamp: <ISO 8601>
      outcome: halted
      stop_condition_fired: 1
      halt_message: "This system as designed does not meet HIPAA compliance. Markdown agents on Claude Code provide audit trail at `advisory` only; HIPAA requires enforced audit-trail. Either change the shape (Python service is on the roadmap but not in v1), change the regulatory exposure, OR commit to an operator-side compliance review before generating."
```

Wizard says the halt message to operator. Offers two paths per `_pre_step_05_recheck.md` Step 2:

- (a) Save progress and exit (operator-side compliance review)
- (b) Change the shape and re-evaluate (v0: loop-back NOT implemented; offers exit or foundation-only with explicit compliance-exposure-recorded-in-docs caveat)

## Expected wizard behavior

If operator picks (a): scope-out cleanly; staging file preserved; halt log recorded.
If operator picks foundation-only fallback: generates foundation docs that EXPLICITLY state the HIPAA + markdown-agents mismatch. (Foundation-only-mode behavior across steps 05-15 is OUT of S2.1 scope per decision F.)

## Discrimination + foundation note

The honest characterization rule (D1 § 2.3) is the structural reason for this halt: markdown agents on Claude Code provide audit trail at `advisory` only (no native log; operator must capture explicitly). HIPAA Security Rule § 164.312(b) requires audit controls — implementation of mechanisms that "record and examine activity in information systems." Advisory ≠ implemented audit control. Halt prevents silent generation of a compliance-incompatible system.

Important: the halt is HONEST, not punitive. The wizard surfaces the structural mismatch the operator may not have understood; offers explicit choices including scope-out (operator-side compliance review before resuming). This is the wizard's product proposition working as designed — it doesn't pretend competence it doesn't have.
