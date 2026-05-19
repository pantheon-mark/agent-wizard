# Pre-step-05 re-check — shape-detection re-evaluation + 4 stop conditions

## What this file does

Re-evaluates the provisional `shape_hypothesis` produced at step 01 or step 02 against accumulated context (steps 02-04 answers + step 03 UP-6 regulatory exposure). Evaluates the 4 stop conditions (regulation × shape mismatch). Halts the wizard if a stop condition fires (foundation state preserved). Triggers the unsupported-shape transition if shape revises to non-v1-supported.

## When this file runs

Reached from `wizard/interview/05_vision.md` opening, BEFORE any step-05 user-facing question fires. This is the **hard stop point** per PRD § 5.2 F-1 — shape detection must be resolved here before vision generation begins.

## Prerequisites

- `~/claude-wizard-draft/wizard_session_draft.md` contains `shape_hypothesis` (emitted at end of step 01 or step 02) AND `regulatory_exposure` (populated at step 03 UP-6)
- Steps 02 (financial) + 03 (user profile) + 04 (notifications) all marked `complete` in `~/claude-wizard-draft/wizard_progress.md`

**If prerequisites are NOT met (per advisor R1 C-001 disposition):** this is a wizard-internal state error, NOT a recoverable condition. PRD § 5.2 F-1 mandates a hard stop before step 05 vision generation; silently defaulting to markdown-agents would violate that contract. Halt with internal-error message; foundation state preserved:

```yaml
internal_error:
  fired_at: pre_step_05_recheck_prereq_check
  reason: <which prerequisite missing — e.g., "shape_hypothesis missing from staging file" / "regulatory_exposure missing — step 03 UP-6 not completed" / "step 04 incomplete">
  timestamp: <ISO 8601>
  recovery: operator should resume from the highest incomplete step per ~/claude-wizard-draft/wizard_progress.md
```

Tell operator: "I hit an internal state error in the wizard before the vision phase. Your project file is saved at `~/claude-wizard-draft/wizard_session_draft.md`. Specific issue: [reason]. Please resume the wizard; it'll pick up at the right step." Exit cleanly; do NOT proceed to step 05.

## Reference spec

`wizard/shape_detection.md` § 5.1 (pre-step-05 re-check) + § 8.3 (stop conditions) + § 8.4 (halt behavior).

---

## Step 1 — Read accumulated context

Read these in order:

1. `~/claude-wizard-draft/wizard_session_draft.md` — full file
2. `shape_hypothesis` block in particular — note initial shape + confidence + forced_recheck_at_step_05 flag
3. `regulatory_exposure` block — note all framework applicability fields + no_compliance_claim_framework_identification
4. Captured answers for UP-1 through UP-5 (step 03) — note any signals contradicting initial shape (e.g., "running 24/7" / "team uses it" / domain expertise areas)
5. Captured answers for NTFY + email channels (step 04) — note any cron-pattern / continuous-runtime signals
6. FIN-1 + FIN-2 (step 02) — note plan type + spend ceiling (high scale ceiling may correlate with non-markdown shape; not load-bearing)

---

## Step 2 — Stop-condition evaluation (CAPABILITY-BASED per advisor R1 C-002 disposition; HALT-vs-DOCUMENT split per advisor R1 C-003 disposition)

Evaluate the 4 stop conditions from `wizard/shape_detection.md` § 8.3 against shape **capabilities** (the `control_matrix_active` block) rather than shape labels. This handles `mixed` shapes correctly and is robust to future shape additions.

**Read the active `control_matrix_active` block from staging file.** If the block is not populated yet (i.e., the classifier emitted shape but did not populate control_matrix_active), populate it now per `wizard/shape_detection.md` § 7 — read D1 § 2.2 column for the active shape; for `mixed` shapes, take the LEAST-restrictive (weakest) status across constituent components per § 8.3 mixed-shape handling.

**Condition 1 (HIPAA):** `regulatory_exposure.hipaa_applicable == yes` AND `control_matrix_active.audit_trail_crud != enforced` (i.e., status is `advisory` / `operator-manual` / `provider-enforced` / `not-applicable` / `deferred-until-shape`)

**Condition 2 (GDPR):** `regulatory_exposure.gdpr_applicable == yes` AND `control_matrix_active.access_control_authn != enforced` (proxy for DSR workflow capability; at v0 only enforced access_control supports defensible DSR endpoints)

**Condition 3 (PCI-DSS):** `regulatory_exposure.pci_dss_applicable == yes` AND `control_matrix_active.encryption_at_rest != enforced` (status is anything other than `enforced`)

**Condition 4 (regulated + no framework):** ANY of (`regulatory_exposure.hipaa_applicable == yes` / `gdpr_applicable == yes` / `pci_dss_applicable == yes` / `sox_applicable == yes` / `coppa_or_gdpr_k_applicable == yes` / `other_sector_specific` non-empty with `applicable == yes`) AND `regulatory_exposure.no_compliance_claim_framework_identification == unknown`

**Outcome path branches on `shape_hypothesis.fallback_mode_offered`:**

### 2a — HALT path (operator on full-system-generation path)

If `shape_hypothesis.fallback_mode_offered == not_offered` (operator never hit the unsupported-shape transition at step 01/02; shape is markdown-agents) AND any condition fires:

Append to staging file:

```yaml
shape_hypothesis:
  recheck_log:
    - step: 05
      timestamp: <current ISO 8601>
      outcome: halted
      stop_condition_fired: <condition number 1-4>
      halt_message: <verbatim from § 8.3 table; substitute `<actual status>` from control_matrix_active>

stop_conditions:
  evaluated_at: 05_pre_vision
  fired: [<list of fired conditions>]
  halted: true
  halt_message: <verbatim>
```

Say the halt message verbatim to operator. Substitute the actual capability status (e.g., "audit trail at `advisory`" or "encryption-at-rest at `provider-enforced + operator-manual`").

Then say:

> Two choices:
>
> **(a) Save progress and exit** — your project file is saved at `~/claude-wizard-draft/wizard_session_draft.md`. Complete an operator-side compliance review, then resume the wizard.
>
> **(b) Change the shape and re-evaluate** — I'll loop back to the shape probes with this regulatory exposure in mind. Note: v1 of the wizard supports only the markdown-agents shape for complete system generation — alternative shapes are deferred. The re-evaluation may end with foundation-only mode or scope-out.

**If operator picks (a):** Append `scope_out_at_halt: <timestamp>`. Say: "Saved. Re-run the wizard when you're ready." Exit cleanly.

**If operator picks (b):** Loop-back implementation is OUT of S2.1 scope per decision G. For now, say:

> Loop-back-to-shape-probes is on the roadmap (a separate slice will implement it). For now, your options are:
>
> - Exit and re-run the wizard with revised understanding of regulatory exposure
> - Choose foundation-only mode (I generate planning documents; you implement separately) — note that this produces docs that EXPLICITLY state the regulatory exposure mismatch
>
> Which would you like?

If operator picks foundation-only: update `shape_hypothesis.fallback_mode_offered: foundation-only`; restart Step 2 (now in 2b path); evaluate conditions again with DOCUMENT-path semantics.

### 2b — DOCUMENT path (operator on foundation-only-mode path)

If `shape_hypothesis.fallback_mode_offered == foundation-only` (operator chose foundation-only at step 01/02 unsupported-shape transition) AND conditions 1-3 fire:

**No HALT fires for conditions 1-3.** Operator already accepted the foundation-only path knowingly at the step 01/02 transition. Record:

```yaml
stop_conditions:
  evaluated_at: 05_pre_vision
  fired: [<list of fired conditions, including 1-3>]
  halted: false
  documented_in_foundation: [<list of 1-3 conditions>]
shape_hypothesis:
  recheck_log:
    - step: 05
      timestamp: <current ISO 8601>
      outcome: documented_in_foundation
      stop_conditions_recorded: [<list>]
```

Downstream foundation-only-mode implementation slice (per decision F) will insert honest compliance-mismatch text into generated foundation docs. At S2.1, the recording is the deliverable; the foundation-doc-insertion is downstream.

**Exception — condition 4 (regulated + no framework) DOES HALT in foundation-only mode:** foundation docs cannot be written honestly without framework identification. If condition 4 fires regardless of `fallback_mode_offered`, fall through to 2a HALT path (a/b two-choice path) with the condition-4-specific halt message.

### 2c — No condition fires

If NO condition fires in either path: proceed to Step 3.

---

## Step 3 — Re-check triggers

Evaluate whether re-check is warranted (any single condition triggers re-check):

1. `shape_hypothesis.forced_recheck_at_step_05 == true` (always re-check)
2. Step 03 UP-1 through UP-5 answer contains signal contradicting initial shape — examples:
   - "I need this running 24/7" + initial shape `markdown-agents` → contradicts (Probe-1 implication)
   - "Our team uses it" + initial shape NOT `node-ui` / `multi-user-datastore` → may contradict (Probe-2 implication)
   - "It needs to call our CRM automatically" + initial shape `markdown-agents` → contradicts (Probe-4 implication)
3. Step 04 NTFY notification choices include cron-pattern triggers (e.g., daily/weekly cron) + initial shape `markdown-agents` → may contradict (Probe-6 implication)
4. Initial emit confidence was MEDIUM or LOW (`shape_hypothesis.confidence in [medium, low]`)

**If NO re-check triggered:** append confirmed-recheck entry; proceed to step 05.

```yaml
shape_hypothesis:
  recheck_log:
    - step: 05
      timestamp: <current ISO 8601>
      outcome: confirmed
```

Proceed to step 05.

**If re-check triggered:** continue to Step 4.

---

## Step 4 — Re-check resolution

Tell the operator what triggered the re-check (plain language; surface the signal honestly):

> Quick check before we move into the vision document. When you described [X — quote the contradicting signal verbatim], that suggests your project might actually be a [revised shape] rather than the [initial shape] I'd estimated. Let me make sure we have this right.

Then ask 1-3 confirmation questions specific to the contradicting signal. Examples:

- For continuous-runtime signal: "Does the system actually need to keep running on its own, even when you're not at your computer or Claude isn't open?"
- For multi-user signal: "Will other people need their own logins or different access levels?"
- For external-software signal: "Does the system need to talk to other software directly — calling APIs, sending emails, accessing databases — without you in the loop?"

Based on operator's answers, classify outcome:

**Outcome A — confirmed initial shape (signal was a false positive):**

```yaml
shape_hypothesis:
  recheck_log:
    - step: 05
      timestamp: <current ISO 8601>
      outcome: confirmed
      notes: signal_reconsidered_via_targeted_question
```

Proceed to step 05.

**Outcome B — revised shape, still v1-supported (i.e., still `markdown-agents`):**

This is rare because v1 supports only markdown-agents. Most revisions move AWAY from markdown-agents. If this outcome fires, update the hypothesis:

```yaml
shape_hypothesis:
  shape: markdown-agents  # unchanged
  confidence: high  # upgrade from medium/low
  recheck_log:
    - step: 05
      timestamp: <current ISO 8601>
      outcome: revised
      revised_shape: markdown-agents
      revised_confidence: high
```

Proceed to step 05.

**Outcome C — revised shape, no longer v1-supported (most common revision):**

Trigger unsupported-shape transition (next section). Append:

```yaml
shape_hypothesis:
  shape: <revised non-markdown shape>
  confidence: <revised confidence>
  v1_supported: false
  recheck_log:
    - step: 05
      timestamp: <current ISO 8601>
      outcome: revised
      revised_shape: <non-markdown shape>
      revised_confidence: <confidence>
```

Proceed to unsupported-shape transition.

---

## Step 5 — Unsupported-shape transition (per `wizard/shape_detection.md` § 6)

Say the operator-facing text verbatim:

> Your project looks like [revised shape — e.g., "a Python service that needs to keep running on its own" / "a system with multiple users and shared data"]. v1 of the wizard generates complete systems for markdown-agents-on-Claude-Code only.
>
> Two options:
>
> **(a) Stop here — wait for v2 / future versions.** Your project file is saved. When the wizard adds [revised shape] support, we can pick up. The roadmap for what triggers that addition lives in `prd.md` § 4.5.
>
> **(b) Foundation-only mode.** I can produce a foundation-doc set for your project — the planning documents (vision, approach, technical architecture, etc.) abstracted from implementation shape. You'd take those docs to Claude Code directly to build the implementation, OR wait for v2 shape support. We won't generate the system implementation itself.
>
> Which would you like? (Say "a" or "b".)

**If operator picks (a) — scope-out:**

Append to shape_hypothesis:

```yaml
shape_hypothesis:
  fallback_mode_offered: scope-out
  scope_out_timestamp: <current ISO 8601>
```

Say: "Saved. Re-run the wizard later when you're ready or when [shape] support is added." Exit cleanly. Do NOT proceed to step 05.

**If operator picks (b) — foundation-only:**

Append to shape_hypothesis:

```yaml
shape_hypothesis:
  fallback_mode_offered: foundation-only
  foundation_only_offered_timestamp: <current ISO 8601>
```

Say: "Foundation-only mode confirmed. I'll generate the planning documents for your project — vision, approach, technical architecture, and so on — abstracted from the implementation shape. You'll take those docs to Claude Code directly to build the implementation. We won't generate the actual agents, scripts, or run files."

**Note for downstream slices:** the steps-05-15 foundation-only-mode behavior (skip implementation generation; only produce foundation docs) is OUT of S2.1 scope per decision F. At S2.1, the wizard proceeds to step 05 with `fallback_mode_offered: foundation-only` set; downstream interview-steps-rebuild slice implements the actual foundation-only path. For S2.1's purposes, marking the state is the deliverable.

Proceed to step 05 (with foundation-only flag set; downstream slices will branch behavior).

---

## Step 6 — Completion

Once Step 2 (stop-condition check), Step 3 (re-check trigger evaluation), Step 4 (re-check resolution if triggered), and Step 5 (unsupported-shape transition if triggered) are complete:

**Per advisor R2 C-009 disposition: update `handoff_phase` to `pre_step_05_evaluated`** in the staging file so downstream consumers (notably pre-step-08 re-check and the eventual rebuild slices) know the pre-step-05 lifecycle phase is satisfied. Locate the existing line (currently `handoff_phase: regulatory_exposure_populated`) and rewrite to:

```yaml
handoff_phase: pre_step_05_evaluated
```

If terminal state (HALT path with `stop_conditions.halted: true` OR scope-out): the handoff_phase still updates to `pre_step_05_evaluated` because the lifecycle phase was satisfied (re-check evaluated; outcome was terminal). Downstream consumers check `stop_conditions.halted` separately.

Append step-marker to `~/claude-wizard-draft/wizard_progress.md`:

```
step_05_pre_recheck: complete | <timestamp>
```

Proceed to `wizard/interview/05_vision.md`.

---

## Cross-references

- `wizard/shape_detection.md` § 5.1 + § 8.3 + § 8.4 + § 6 — canonical spec
- `wizard/handoff_contracts/shape_detection_v0.md` — handoff schema
- `governance/generated_system_data_defaults.md` § 6.3 — 4 stop conditions canonical
- PRD v1 § 5.2 F-1 / § 4.3 — requirements
- S2.1 slice spec § A.4 + § A.5 + § A.7 — design provenance
