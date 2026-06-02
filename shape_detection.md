# Shape Detection — canonical implementation spec

**Mechanism ID:** `mech-shape-detection-v0`
**Mechanism class:** Skill, pure markdown (advisory or guided).
**Status:** v1 active. Two amendments this cycle (2026): (1) the *elicitation* revision (experiential capabilities beat; classifier/rubric/emit/contract UNCHANGED); (2) the **runtime+integration reconciliation with the markdown-agents execution model (2026-06-02)** — this one DELIBERATELY changes the classifier (§ 2.3), the confidence rubric (§ 3 branch (c)), the emit schema (§ 4), and the handoff contract (`schema_major` 0→1): scheduled execution + outbound integration are markdown-fine, so the non-markdown triggers are now `probe_9_always_on` / `probe_10_inbound_serve` / `probe_2`. Cross-vendor advisor review complete; merge pending operator approval + the step-02 re-walk.
**Authority:** This file is canonical for the wizard's shape-detection logic. Interview files (`wizard/interview/*.md`) reference this file as the spec for the probes they fire and the emit they produce.
**Cross-references:** `wizard/handoff_contracts/shape_detection_v0.md` / `wizard/CLAUDE.md` § 9 (Forward-offered information capture).

---

## 1. What this does

The wizard's shape-detection logic emits a **provisional shape hypothesis with confidence** at step 01 (target) or step 02 (latest acceptable) of the operator interview. It re-checks the hypothesis before step 05 (vision generation) and before step 08 (architecture generation). It evaluates 4 stop conditions (regulation × shape mismatch) at pre-step-05 and halts the wizard with a foundation-state-preserved message if a stop condition fires. It produces a handoff contract artifact that downstream rebuild slices consume.

Shape categories: `markdown-agents` (v1 supported) / `python-service-operator-facing` (deferred) / `claude-skills` (deferred) / `node-ui` (deferred) / `multi-user-datastore` (deferred) / `hosted-cloud` (deferred) / `mixed` (deferred) / `unknown` (classifier output for insufficient signal).

The logic is **behavior-based** — operators are NOT asked "do you want Python service or markdown agents?" That would recreate the technical-knob-mismatch failure. Probes use plain-English business-side vocabulary; wizard-internal signal classifications are routing hints only, never surfaced to the operator.

## 2. Probe inventory + signal-to-shape mapping

### 2.1 Step 01 — capabilities beat (experiential; 5 questions across 4 dimensions; always asked)

The shape dimensions are elicited as **one grouped, experiential capabilities beat** — sub-steps P1-4 through P1-7b of `wizard/interview/01_phase1_capture.md`, presented to the operator as a single beat (NOT separate cold ceremonial questions). The beat runs after the purpose → working-definition → name → staging-file beats (P1-2 → definition pass → P1-1 → P1-3). The questions are asked **independently** (the runtime question is one *leveled* pick across an ordinal dimension; the rest are 3-state yes / no / **not sure**), **framed by** the working definition from the definition pass but **never pre-filled** from it.

The operator-facing text is **experiential** (what the system will do for them in plain terms), not technical. Each question resolves to the `probe_N` value(s) the classifier consumes — only the framing changed.

| Question | Operator-facing text (experiential) | Resolves to | Signal classification |
|---|---|---|---|
| **thinking-partner** | "Will you want to chat with it or ask it questions directly — bring it things to think through?" | `probe_3` | yes → markdown-agents OR Claude-skills signal; no → automated-systems signal |
| **runtime** (leveled — 3 contrastive levels; "not sure" allowed) | "How does this need to run? — **(a) Only when you come to it** (you open it and ask); **(b) On a schedule** (wakes at set times — each morning or a few times a day — does its work, sends you what it found, done until next time); **(c) All the time** (stays on constantly and reacts *within seconds* when something happens)" | `probe_1_scheduled_cadence` + `probe_9_always_on` (both derived from the level; see below) | (a) on-demand → markdown-friendly; (b) scheduled → **markdown-friendly** (cron→Orchestrator per the markdown-agents execution model); (c) all-the-time → `probe_9_always_on` yes = non-markdown |
| **multi-user** | "Will other people use it, with their own access?" | `probe_2` | yes → Node+UI + multi-user-datastore signal; no → single-user-friendly |
| **outbound integration** | "Does it need to **reach out to your apps or accounts when it runs** — read your calendar, update your sheet, send an email? (**read or write**)" | `probe_4` | **shape-NEUTRAL** (markdown reaches out via scripts + step-09 credentials per the markdown-agents execution model); captured for the integration inventory |
| **inbound integration** | "Does it need to **receive things from other systems live** — let other people or apps connect to it, receive live updates/webhooks, or have people sign in to it as part of normal use? (one-time account setup does NOT count)" | `probe_10` | yes → non-markdown (live-serving / Event-Bound = future shapes per the markdown-agents execution model); no → markdown-friendly |

**Runtime-level → flag derivation (runtime+integration reconciliation).** The operator's single runtime answer is recorded RAW to the transcript and derives the two staging flags:

| Operator picks | transcript qid `P1-4` value (`runtime_mode`) | `probe_1_scheduled_cadence` | `probe_9_always_on` | Shape effect |
|---|---|---|---|---|
| (a) Only when you come to it | `on-demand` | no | no | markdown-friendly |
| (b) On a schedule | `scheduled` | yes | no | markdown-friendly (orchestration cadence) |
| (c) All the time | `always-on` | no | yes | non-markdown (`probe_9_always_on` is the only non-markdown runtime trigger) |
| Not sure | `unsure` | unsure | unsure | neutral → fallback / recheck |

Operator answers are stored under `shape_hypothesis.operator_signals` (`probe_1_scheduled_cadence`, `probe_2_multi_user`, `probe_3_thinking_partner`, `probe_4_external_software`, `probe_9_always_on`, `probe_10_inbound_serve`) — the same field surface the classifier (§ 2.3), confidence rubric (§ 3), pre-step-05/08 re-checks (§ 5), control matrix (§ 7), and stop conditions (§ 8) consume. `unsure` is treated as neutral signal (no strong-positive OR strong-negative) and is a **first-class answer, NOT "unchecked = no."** The **runtime answer is recorded RAW to the event transcript** under qid `P1-4`, group `orchestration_build`, as `runtime_mode = on-demand | scheduled | always-on | unsure` (it feeds the step-13 orchestration / execution-cadence derivation, which benefits from the on-demand-vs-scheduled distinction; `probe_1_scheduled_cadence` + `probe_9_always_on` are derived from it for the classifier). The other dimensions resolve to staging-file probe values only. The `probe_N` ↔ marker mapping: `P1-4`↔runtime (`runtime_mode` → `probe_1_scheduled_cadence` + `probe_9_always_on`), `P1-5`↔`probe_2` (multi-user), `P1-6`↔`probe_3` (thinking-partner), `P1-7`↔`probe_4` (outbound), `P1-7b`↔`probe_10` (inbound).

**Beat rules (the elicitation contract; see § 9 decision-E):**

- **Independent, not mutually exclusive.** Each question is answered on its own. Genuine mixed use is expressible — e.g., chat = yes AND scheduled routes through the classifier's `mixed` path (§ 2.3) or, when not yet ≥2 clusters, defers to the step-02 fallback. The runtime question is the one *leveled* pick (an ordinal dimension — runtime intensity); it does NOT re-trip the rejected v2 radio-button (which forced a pick across *orthogonal* needs). There is NO radio-button "pick the closest" across the dimensions.
- **No inference-hiding.** All questions are ALWAYS asked. Forward-offered signals from the purpose / working definition (§ 9) may *contextualize the framing* ("based on what you described…") but MUST NEVER pre-fill an answer or skip a question.
- **Preserve "not sure."** 3-state (and a "not sure" runtime level), never a binary checkbox. "Unsure" is the neutral signal the § 3 confidence rubric and the step-05/08 re-checks need; collapsing it to "no" would inflate confidence and skip the safety net.
- **Read OR write** in the outbound question — a read-only integration must not falsely map to `probe_4 = no`.
- **One-time setup is NOT inbound.** The inbound question's non-markdown trigger is *live serving / others connecting to it / per-user sign-in as normal operation* — explicitly NOT one-time account or credential setup (markdown handles that via stored credentials + token refresh per the markdown-agents execution model).
- **Frequency sentinel (light).** If the operator picks "On a schedule," capture a rough cadence in one short clarifier; if it implies sub-hourly / near-real-time wakeups, surface a gentle cost/feasibility note (an LLM-Orchestrator cron every few minutes burns budget and hits rate limits) — this stays markdown (NOT a shape off-ramp). Fuller volume/SLA modeling is out of scope here (tracked as F7 / step-13 scale).

### 2.2 Step 02 — conditional fallback probes (fire only if step 01 yields MEDIUM or LOW confidence)

Up to 4 additional probes from the relevant product spec section candidate set. Fire at end of step 02 (after FIN-1 + FIN-2 complete; before step-02 success condition).

| Probe | Operator-facing text | Signal classification |
|---|---|---|
| **Probe-5 (state-memory)** | "Should the system remember things between times you use it?" | yes → datastore signal; no → stateless-friendly |
| **Probe-6 (regular-pattern)** | "Does it need to do something automatically, on a regular pattern — like every day, every Monday morning, every hour?" | yes → **markdown-friendly** (scheduled cron→Orchestrator per the markdown-agents execution model; F6 reconciliation — scheduled is NOT a non-markdown signal); no → on-demand-friendly. (The non-markdown runtime trigger is `probe_9_always_on`, not regular-pattern scheduling.) |
| **Probe-7 (operator-confirm)** | "Should the system ask you before doing anything important — like making a booking, sending money, or contacting someone?" | yes → markdown-agents-friendly (human-gate aligns); no → autonomous-action implies stronger guardrails |
| **Probe-8 (document-output)** | "Does it produce a document, packet, or report that you'll review or share?" | yes → markdown-agents OR Claude-skills; no → service-output-friendly |

Fallback probes are drawn from a wizard-internal candidate set; not all fire on every operator session. The wizard chooses which fallback probes to fire based on which signals from step 01 are weakest.

### 2.3 Signal-to-shape decision table

Cumulative across all fired probes. Strong-positive / strong-negative are tallied per shape. **(F6 reconciliation — see § 9.)** Per the markdown-agents execution model, scheduled execution and outbound integration are things v1 markdown DOES, so `probe_1_scheduled_cadence` and `probe_4` (outbound) are **shape-NEUTRAL** — they appear in NO strong-positive/strong-negative column (captured for the orchestration / integration inventory only). The genuine non-markdown triggers are `probe_9_always_on` (daemonized/always-on), `probe_10_inbound_serve` (live-serving/inbound), and `probe_2` (multi-user).

| Shape | Strong-positive signals | Strong-negative signals |
|---|---|---|
| `markdown-agents` (Claude Code, Mac) | Probe-3 yes / Probe-7 yes / Probe-8 yes | `probe_9_always_on` yes / `probe_10_inbound_serve` yes / Probe-2 yes |
| `python-service-operator-facing` (deferred) | `probe_9_always_on` yes / `probe_10_inbound_serve` yes | Probe-3 yes |
| `claude-skills` (deferred) | Probe-3 yes / Probe-8 yes / Probe-7 yes | `probe_9_always_on` yes / `probe_10_inbound_serve` yes / Probe-2 yes |
| `node-ui` (deferred) | Probe-2 yes / `probe_10_inbound_serve` yes | Probe-3 yes |
| `multi-user-datastore` (deferred) | Probe-2 yes / Probe-5 yes | Probe-3 yes |
| `hosted-cloud` (deferred) | `probe_9_always_on` yes / Probe-2 yes / Probe-5 yes | Probe-3 yes |
| `mixed` (deferred) | ≥2 shape clusters each have ≥2 strong-positives AND no shape's signals subsume another | n/a |
| `unknown` | Insufficient signal density (no shape has ≥2 strong-positives) | n/a |

**F6 note — markdown-agents and claude-skills share Probe-3/7/8 positives** (both are thinking-partner-shaped); the markdown-vs-skills tiebreak is pre-existing and unchanged by F6 (skills is deferred; both route through the same v1-supported-vs-not gate only for markdown). The decisive F6 change is that a *scheduled + outbound* system (the estate-executor case) no longer accrues any non-markdown signal and so resolves to `markdown-agents` via the absence-of-disqualifiers HIGH branch (§ 3 branch (c)).

## 3. Confidence rubric

Computed after each probe-set fires.

| Confidence | Criteria |
|---|---|
| **HIGH** | (a) Top shape has ≥3 strong-positives AND 0 strong-negatives AND no other shape has ≥2 strong-positives; OR (b) Top shape has 2 strong-positives AND the same answers produce ≥2 strong-negatives for the next-closest competing shape (subsumption-by-strong-negatives ruling out alternatives) AND no other shape has ≥2 strong-positives; OR **(c) [`markdown-agents` only — absence-of-disqualifiers] `markdown-agents` has ≥1 strong-positive AND 0 strong-negatives AND every non-markdown trigger (`probe_9_always_on`, `probe_10_inbound_serve`, `probe_2`) is no/unsure AND no other shape has ≥2 strong-positives AND no `claude-skills` packaging/reuse signal is present** (a forward-offered "package this up / reuse across multiple conversations" signal selects `claude-skills` over `markdown-agents`; when present, branch (c) does NOT fire — defer to step-02 fallback for the markdown-vs-skills discrimination) |
| **MEDIUM** | Top shape has 2 strong-positives AND 0-1 strong-negatives AND neither HIGH branch (b) nor (c) applies. OR HIGH-like signal density but with 1 conflicting strong-negative. |
| **LOW** | Top shape has 1 strong-positive AND signals scattered AND branch (c) does NOT apply (i.e., the 1-positive shape is non-markdown, OR a non-markdown trigger fired). OR ≥2 shapes tied with strong-positives. OR insufficient signal density (`mixed` / `unknown` emit). |

**Rubric note.** Branch (b) captures "2 strong-positives + clean discrimination via strong-negatives ruling out alternatives" — e.g., a fixture where `python-service-operator-facing` has 2 strong-positives (`probe_9_always_on` + `probe_10_inbound_serve`) AND the same answers produce strong-negatives for `markdown-agents`/`claude-skills` (those two triggers). Branch **(c)** (F6) captures the asymmetry that `markdown-agents` is the v1-supported, conservative *default* shape: it is viable whenever no non-markdown trigger positively fires, so it reaches HIGH with even a single behavior positive (thinking-partner / operator-confirm / document-output) provided the disqualifiers are all absent and no deferred shape has accrued ≥2 positives. Deferred shapes do NOT get branch (c) — they require their triggers to be positively present. Without (c), the estate-executor case (thinking-partner=yes, scheduled, outbound, no always_on/inbound/multi-user) would emit MEDIUM/LOW and fire step-02 fallback unnecessarily even though markdown is the only viable shape. **The claude-skills guard on branch (c)** is load-bearing: `markdown-agents` and `claude-skills` share their entire positive set (probe_3/7/8), so they tie on probe counts and the discriminator is the forward-offered "package up / reuse across conversations" signal that points to skills. Branch (c) treats `markdown-agents` as the floor only when no such skills signal is present; when it IS present (e.g., fixture `s03`), markdown-vs-skills is resolved at the step-02 fallback via that interpretive prior, exactly as before F6. (Both are thinking-partner shapes; the distinction matters because `claude-skills` is v1-unsupported, so mis-selecting it would wrongly fire the unsupported-shape transition.)

**Elicitation note (v1) + runtime+integration amendment (2026-06-02).** Each dimension's explicit answer IS the `probe_N` value fed to this rubric — there is no separate "confirm an inferred answer" step (the rejected v0-candidate "infer-and-confirm" shape), so a beat answer and a probe answer are the same input. `unsure` counts as a neutral signal; preserving it (rather than collapsing to "no") keeps the MEDIUM/LOW → step-02-fallback and `forced_recheck_at_step_05` safety nets honest. **This reconciliation DID change this rubric** (unlike the elicitation revision, which left it untouched): branch (c) was added so the reconciled neutral treatment of scheduled+outbound still lets `markdown-agents` reach confidence by absence of disqualifiers. The runtime question is leveled (§ 2.1) but still resolves to discrete `probe_1_scheduled_cadence` (neutral) + `probe_9_always_on` (negative-trigger) signals the rubric reads.

**Promotion logic:**

1. Compute confidence after step 01 probes (Probe-1 through Probe-4).
2. If HIGH: emit hypothesis at end of step 01.
3. If MEDIUM or LOW: defer emit; fire step 02 fallback probes (Probe-5 through Probe-8) at end of step 02; recompute confidence.
4. If still LOW after step 02: emit `shape: unknown` with `confidence: low` AND set `forced_recheck_at_step_05: true`. Operator continues; pre-step-05 re-check re-evaluates with accumulated steps 02-04 context.

## 4. Provisional hypothesis emission contract

At classifier emit, write the following structure to `~/claude-wizard-draft/wizard_session_draft.md` under a new `## Shape detection` section (after the `## Captured answers` section). Every finalized emit MUST include `status: emitted` (to disambiguate from deferred-emit placeholder), `schema_versions` block, AND `handoff_phase: provisional_shape_emit` field. These are the consumer-visible markers required by `wizard/handoff_contracts/shape_detection_v0.md`.

```yaml
## Shape detection

schema_versions:
  schema_major: 1 # bumped 0 → 1 at F6 (2026-06-02): breaking — `probe_1_continuous_runtime` renamed to `probe_1_scheduled_cadence`; `probe_9_always_on` + `probe_10_inbound_serve` added. Field rename ⇒ major bump per handoff contract § 6.
  schema_minor: 0 # reset to 0 on the major bump. (The major-0 lineage's additive features — `shape_revision` block, `stop_conditions.resolved_during_loop` — carry forward under major 1.)
  shape_taxonomy_version: 0
  stop_condition_set_version: 0
  control_matrix_schema_version: 0

handoff_phase: provisional_shape_emit

shape_hypothesis:
  status: emitted # 'emitted' for finalized; 'pending_step_02_fallback' for deferred at step 01
  shape: markdown-agents | python-service-operator-facing | claude-skills | node-ui | multi-user-datastore | hosted-cloud | mixed | unknown
  confidence: high | medium | low
  detected_at_step: 01 | 02
  v1_supported: true | false # markdown-agents only = true at v1
  rechecks_due: [05, 08]
  forced_recheck_at_step_05: true | false # true when emit was LOW
  operator_signals:
  probe_1_scheduled_cadence: yes | no | unsure # F6: derived from the runtime level (yes only for "On a schedule"). SHAPE-NEUTRAL; the raw runtime answer is recorded to transcript qid P1-4 as runtime_mode.
  probe_2_multi_user: yes | no | unsure
  probe_3_thinking_partner: yes | no | unsure
  probe_4_external_software: yes | no | unsure # F6: outbound integration. SHAPE-NEUTRAL (markdown reaches out via scripts + step-09 creds per the markdown-agents execution model).
  probe_5_state_memory: yes | no | unsure | not_asked
  probe_6_regular_pattern: yes | no | unsure | not_asked
  probe_7_operator_confirm: yes | no | unsure | not_asked
  probe_8_document_output: yes | no | unsure | not_asked
  probe_9_always_on: yes | no | unsure # F6 NEW: derived from the runtime level (yes only for "All the time"). The only non-markdown RUNTIME trigger.
  probe_10_inbound_serve: yes | no | unsure # F6 NEW: inbound/live-serving integration. Non-markdown trigger.
  forward_offered_signals_at_step_01:
  - "<verbatim phrase from operator's P1-2 core-purpose answer per wizard/CLAUDE.md § 9>"
  mixed_component_basis: [] # ONLY populated when shape == mixed; lists component shapes detected in the operator's input
  fallback_mode_offered: complete | foundation-only | scope-out | not_offered
  emit_timestamp: <ISO 8601>
```

**`status` field semantics:**

- `status: emitted` — classifier has produced a finalized hypothesis at this step; downstream triggers (P1-9, P02-FB-6, pre-step-05 re-check) read this as the entry condition.
- `status: pending_step_02_fallback` — classifier deferred emit at step 01 because confidence was MEDIUM or LOW; step 02 fallback will finalize.

**`mixed_component_basis` field semantics:**

- ONLY populated when `shape == mixed`.
- Lists the component shapes detected in the operator's inputs (e.g., `["markdown-agents", "python-service-operator-facing"]` for a mixed system with a markdown thinking-partner component AND a python automation component).
- Downstream consumers reading `control_matrix_active` for a mixed shape can audit the basis: the weakest-path-across-components computation in § 8.3 takes its input from this list.
- For v0, `mixed_component_basis` is the wizard's classification of which constituent shapes are present; precision is limited but the field provides an auditable record. Component-level capability tracking (per-component matrix blocks) is reserved for v1+.

**Lifecycle-phase update rule:**

When downstream interview steps advance the handoff to a later lifecycle phase, they MUST update the `handoff_phase` field. Specifically:

- Step 03 UP-6 completion → `handoff_phase: regulatory_exposure_populated`
- Pre-step-05 re-check success path → `handoff_phase: pre_step_05_evaluated`
- Pre-step-08 re-check success path → `handoff_phase: pre_step_08_evaluated`

Terminal states retain their pre-terminal `handoff_phase` value (scope-out at step 01/02 keeps `provisional_shape_emit`; HALT at pre-step-05 keeps `pre_step_05_evaluated` with `stop_conditions.halted: true`).

**Append-only update rule.** After emit, re-checks at step 05 and step 08 append entries to a `recheck_log:` list rather than mutating prior entries:

```yaml
shape_hypothesis:
  # ... emit fields ...
  recheck_log:
  - step: 05
  timestamp: <ISO 8601>
  outcome: confirmed | revised | halted
  revised_shape: <if outcome == revised>
  revised_confidence: <if outcome == revised>
  stop_condition_fired: <if outcome == halted>
  - step: 08
  timestamp: <ISO 8601>
  outcome: confirmed | revised | halted
  # ... etc
```

## 5. Re-check protocol

### 5.1 Pre-step-05 re-check

Reachable from `wizard/interview/05_vision.md` opening. Implementation lives at `wizard/interview/_pre_step_05_recheck.md`.

Before step 05's first user-facing question, classifier re-reads:

1. The provisional `shape_hypothesis` from staging file
2. All operator answers captured in step 02 (financial) + step 03 (user profile; including regulatory-applicability probe UP-6) + step 04 (notifications)
3. The `regulatory_exposure` field populated at step 03 UP-6

**Re-check triggers** (any single condition fires re-check):

- Step 03 user-profile answer (UP-1 through UP-5) indicates operator role / availability / domain contradicting the initial shape signal (heuristic; e.g., "I need this running 24/7 for our team" contradicts `markdown-agents`)
- Step 04 notifications choices imply runtime shape (e.g., NTFY cron-pattern notifications imply service shape)
- Initial emit confidence was MEDIUM or LOW (always re-check when forced_recheck_at_step_05 = true)
- 4 stop conditions need evaluation (regulatory_exposure now populated)

**Re-check outcome paths:**

| Outcome | Action |
|---|---|
| `confirmed` | Append recheck entry `outcome: confirmed`; proceed to step 05 |
| `revised` (still v1-supported) | Update `shape_hypothesis.shape` + `confidence`; append recheck entry `outcome: revised` + `revised_shape:` + `revised_confidence:`; proceed to step 05 |
| `revised` (no longer v1-supported) | § 6 unsupported-shape transition fires (operator chooses scope-out vs foundation-only) |
| `halted` (stop condition fired) | § 7 halt fires; foundation state preserved; operator offered three paths — (a) save-and-exit / (b) change shape and re-evaluate / (c) re-evaluate regulatory exposure |

### 5.2 Pre-step-08 re-check

Reachable from `wizard/interview/08_architecture.md` opening. Implementation lives at `wizard/interview/_pre_step_08_recheck.md`.

Same structural pattern as pre-step-05 but reads accumulated steps 05 (vision) + 06 (approach) + 07 (advisors). Especially important for emergent-architecture projects (the relevant product spec section; J6 anchored).

Stop conditions are NOT re-evaluated at pre-step-08 (already evaluated at pre-step-05; regulatory exposure does not change between steps 03 and 08 under normal conditions). However, if pre-step-05 was `confirmed` but pre-step-08 reads emerging-architecture content that newly implicates a stop condition (rare; flagged for v1 monitoring), the re-check halts and the wizard surfaces the new evidence to the operator.

## 6. Unsupported-shape transition (foundation state preserved)

**Triggered when** (surface at the EARLIEST detection point):

- Initial detection at step 01 (P1-8) emits a non-markdown shape with HIGH confidence → transition fires NOW at end of step 01; operator chooses scope-out OR foundation-only BEFORE step 02.
- OR initial detection at step 02 fallback (P02-FB-5) emits a non-markdown shape with HIGH or MEDIUM confidence → transition fires NOW at end of step 02; operator chooses scope-out OR foundation-only BEFORE step 03.
- OR pre-step-05 re-check revises shape to non-markdown → transition fires at pre-step-05 (revision case; previously confirmed markdown but accumulated context contradicts).
- OR pre-step-08 re-check revises shape to non-markdown → transition fires at pre-step-08 (late revision case).

**Step-01-or-02 transition is the canonical operator-facing surface.** Pre-step-05 and pre-step-08 transitions are revision-case backstops — they fire only when shape revises AFTER step 02 emit.

**Operator-facing text (verbatim):**

> Your project looks like [shape X — Python service / Node+UI / etc.]. v1 of the wizard generates complete systems for markdown-agents-on-Claude-Code only.
>
> Two options:
>
> **(a) Stop here — wait for a future wizard release.** Your project file is saved. When the wizard adds [shape X] support, we can pick up.
>
> **(b) Foundation-only mode.** I can produce a foundation-doc set for your project — the planning documents abstracted from implementation shape. You'd take those docs to Claude Code directly to build the implementation, OR wait for v2 shape support. We won't generate the system implementation itself.
>
> Which would you like? (Say "a" or "b".)

**Foundation state preservation:**

`~/claude-wizard-draft/wizard_session_draft.md` is unchanged by the transition; all captured answers remain. The `shape_hypothesis.fallback_mode_offered` field updates to `scope-out` (operator picks a) or `foundation-only` (operator picks b). Transition does NOT delete the staging file OR force operator restart.

**Per-path behavior:**

- **(a) scope-out:** wizard appends `scope_out: <timestamp>` marker to staging file under the shape_hypothesis section; says: "Saved. Re-run the wizard later when you're ready or when [shape X] support is added." Exits cleanly.
- **(b) foundation-only:** wizard proceeds with steps 05-15 in foundation-doc-only mode (NO system implementation generated). See `wizard/interview/_foundation_only_mode_gate.md` for the capability-field derivation rule + per-step entry-guard pattern + close-ceremony adaptation pointer. Each of `wizard/interview/05_vision.md` through `15_close.md` has a `## Foundation-only adapted path` section at file end implementing the steps-05-15 foundation-only-mode behavior per `_foundation_only_mode_gate.md` § 5 four-file foundation doc set + § 6 DOCUMENT-path gap integration + § 7 close-ceremony adaptation pointer.

Foundation-only mode is NOT counted as "system implementation served"; the disclosure is explicit at shape-diagnosis moment. NOT silent fallback.

## 7. Per-shape control matrix wiring

The classifier reads the per-shape control matrix at startup (the matrix is defined as a wizard-internal data structure; see § 7.x below). On hypothesis emit, populate `control_matrix_active` for the detected shape:

**For `markdown-agents` (v1 supported):**

```yaml
control_matrix_active:
  shape: markdown-agents
  encryption_in_transit: provider-enforced
  encryption_at_rest: provider-enforced + operator-manual
  access_control_authn: not-applicable
  audit_trail_crud: advisory
  backup_restore: not-applicable
  data_handling_sla: operator-manual
  regulatory_framework_adherence: operator-manual
  no_secrets_input_boundary: operator-manual
  no_secrets_repo_boundary: enforced-after-mandatory-hook-trigger
  audit_log_retention: not-applicable
```

**For all other (deferred) shapes:** every control row populates to `deferred-until-shape` for extension-readiness:

```yaml
control_matrix_active:
  shape: python-service-operator-facing
  encryption_in_transit: deferred-until-shape
  encryption_at_rest: deferred-until-shape
  # ... etc per the control matrix column for this shape
```

**Honest characterization rule wired:** when shape detection emits `markdown-agents`, the wizard's eventual README + foundation-doc output must include a "Controls applied per chosen shape" section listing the matrix status values for operator transparency. Implementation of this output is downstream of shape detection; the contract surface here defines what downstream consumers receive.

## 8. 4 stop conditions implementation

### 8.1 Regulatory-applicability probe placement

**Step 03 (user profile)** as sub-step UP-6, after UP-5 (involvement appetite) and before the synthesis step. The probe uses a two-step pattern (data-type question, then operator-role question), abbreviated for step-03 conversational fit.

The probe is asked with this lead-in:

> Two more questions about the data your system will handle. These help me check whether your project's regulatory exposure is compatible with the system shape we've detected — so I don't generate something that won't work for your actual needs.

For each framework (GDPR / HIPAA / PCI-DSS / SOX / COPPA-or-GDPR-K / other-sector-specific), the wizard asks the two-step pattern from D1 § 6.1: (a) data-type question + (b) operator-role question. Both yes = framework applicable.

To minimize friction with non-technical operators, the wizard asks the framework questions PROPOSITIONALLY in plain language (not as a checklist of acronyms). Example combined prompt:

> Will the system handle any of the following on a regular basis?
>
> 1. **Health information about identifiable people** — patient records, medical histories, insurance claims
> 2. **Personal data of people in the EU/EEA** — names, contact info, behavioral data, etc.
> 3. **Credit card or payment card numbers**
> 4. **Financial reporting data subject to audit** — for publicly-traded companies or their auditors
> 5. **Data from children under 13** (or under 16 in the EU)
> 6. **Other regulated data** — government records, education records, sector-specific (energy, telecoms, etc.)
> 7. **None of the above** — no regulated data

For any "yes" answer, wizard asks the follow-up role question (the operator-role step (b)) to determine actual applicability. Example for #1: "Are you (or the system) acting as a healthcare provider, insurance plan, clearinghouse, OR a business associate processing health data on their behalf?"

If operator says "regulated" (any yes) but cannot identify which specific framework, store `no_compliance_claim_framework_identification: unknown` — this fires stop condition #4 at pre-step-05 re-check.

If operator says "none of the above," store `no_compliance_claim: yes` and proceed; the wizard's eventual foundation-doc set will EXPLICITLY state "this system makes NO compliance claim under GDPR / HIPAA / PCI / SOX / etc."

### 8.2 regulatory_exposure schema

Stored in staging file under `## Regulatory exposure` section:

```yaml
## Regulatory exposure

regulatory_exposure:
  gdpr_applicable: yes | no | unknown
  hipaa_applicable: yes | no | unknown
  pci_dss_applicable: yes | no | unknown
  sox_applicable: yes | no | unknown
  coppa_or_gdpr_k_applicable: yes | no | unknown
  other_sector_specific:
  - { framework: <name>, applicable: yes | no | unknown }
  no_compliance_claim: yes | no | unknown
  no_compliance_claim_framework_identification: yes | no | unknown
  probed_at_step: 03_up6
  probed_timestamp: <ISO 8601>
```

### 8.3 Stop conditions lookup (CAPABILITY-BASED)

Evaluated at pre-step-05 re-check (per § 5.1). Conditions are evaluated against shape **capabilities** (the per-shape control matrix `control_matrix_active` block values) rather than shape labels. This handles `mixed` shapes correctly (mixed includes markdown-agents component providing certain controls at advisory-only) and is robust to future shape additions.

**Outcome split.** When a stop condition matches:

- If `shape_hypothesis.fallback_mode_offered == not_offered` (operator is on full-system-generation path; shape == markdown-agents): **HALT** per § 8.4
- If `shape_hypothesis.fallback_mode_offered == foundation-only` (operator chose foundation-only-mode at step 01/02 unsupported-shape transition): **DOCUMENT** per § 8.5 — record the matched condition; downstream foundation-only slice inserts honest text into generated foundation docs. Condition 4 is an EXCEPTION (see footnote).

| # | Capability condition | Operator-facing message (HALT or DOCUMENT path applies per above) |
|---|---|---|
| 1 | `regulatory_exposure.hipaa_applicable == yes` AND `control_matrix_active.audit_trail_crud != enforced` (status is `advisory` / `operator-manual` / `provider-enforced` / `not-applicable` / `deferred-until-shape`) | "This system as designed does not meet HIPAA compliance. The chosen shape provides audit trail at `<actual status from control_matrix_active>`; HIPAA requires enforced audit-trail. Either change the shape (Python service is on the roadmap but not in v1), change the regulatory exposure, OR commit to an operator-side compliance review before generating." |
| 2 | `regulatory_exposure.gdpr_applicable == yes` AND `control_matrix_active.access_control_authn != enforced` (proxy for DSR workflow capability; at v0 only enforced access_control supports defensible DSR endpoints) | "This system as designed does not meet GDPR compliance. The chosen shape provides access control at `<actual status>` — it does not have enforceable DSR (Data Subject Request) workflow primitives. GDPR Article 12-23 require enforceable DSR endpoints. Either change the shape OR commit to an operator-side compliance review." |
| 3 | `regulatory_exposure.pci_dss_applicable == yes` AND `control_matrix_active.encryption_at_rest != enforced` | "This system as designed does not meet PCI-DSS compliance. The chosen shape provides encryption-at-rest at `<actual status>`, not `enforced`. PCI-DSS requires deterministic encryption-at-rest. Either change the shape OR commit to an operator-side compliance review." |
| 4 | `regulatory_exposure.no_compliance_claim == no` AND `regulatory_exposure.no_compliance_claim_framework_identification == unknown` | "You've indicated this system handles regulated data, but we haven't identified which specific framework (HIPAA / GDPR / PCI / sector-specific). Before generating, please complete an operator-side compliance review to identify the applicable framework; the wizard will halt here." |

**Footnote on condition 4 + foundation-only path:** condition 4 fires HALT even in foundation-only-mode because foundation docs cannot be written honestly without framework identification — "regulated data but unknown which framework" is an operator-side resolution gap, not a documentation gap. Operator must complete compliance review and resume.

**Footnote on condition 4 predicate:** the predicate above uses `no_compliance_claim == no AND framework_identification == unknown`. The condition fires when the operator marks the regulated bucket at UP-6.1 but can't name a specific framework. If a specific framework were `applicable: yes` (or `other_sector_specific[].applicable: yes`), framework identification would NOT be `unknown` per UP-6 source semantics at `03_user_profile.md`.

**Mixed-shape handling:** when `shape_hypothesis.shape == mixed`, the `control_matrix_active` block reflects the **union of components' capabilities** — for each control row, the LEAST-restrictive status across constituent components wins. Concretely: if the mixed system has a markdown-agents component (audit trail `advisory`) AND a python-service component (audit trail `enforced`), the matrix records `audit_trail_crud: advisory` because the markdown component's path can carry regulated data with only advisory audit trail. Condition 1 fires on the weakest path. This is the conservative correct behavior — regulated data MUST be handled by the enforced-audit-trail path; if any component fails, the system fails.

For future revisions: when downstream slices implement component-level capability tracking, the matrix evolves to per-component blocks (`control_matrix_active.components[<id>].audit_trail_crud: <status>`). v0 records the weakest-path conservatively in the single block. Component-level surface is reserved for v1+ per `wizard/handoff_contracts/shape_detection_v0.md` § 4.

### 8.4 Halt behavior (HALT path; full-system-generation)

When a stop condition fires AND `shape_hypothesis.fallback_mode_offered == not_offered` (operator is on full-system-generation path):

1. Wizard appends to staging file:
 ```yaml
 shape_hypothesis:
 recheck_log:
 - step: 05
 outcome: halted
 stop_condition_fired: <# from § 8.3>
 halt_timestamp: <ISO 8601>
 halt_message: <verbatim message; with `<actual status>` substituted from control_matrix_active>
 ```
2. Wizard says the halt message verbatim to operator (with capability status substituted).
3. Wizard offers three paths:
 > Three choices:
 > **(a) Save progress and exit** — your project file is saved; you can complete a compliance review and resume.
 > **(b) Change the shape and re-evaluate** — I'll re-run the shape probes with this regulatory exposure in mind.
 > **(c) Re-evaluate regulatory exposure** — I'll re-ask the step 03 regulatory questions with the stop condition surfaced; if your project actually doesn't fall under [framework] scope, the stop condition won't fire on re-evaluation.
4. If operator picks (b): invoke `wizard/interview/_stop_condition_reevaluate_loop.md` § 2 loop entry; loop sub-module runs probe re-ask + classifier re-emit + stop-condition re-evaluation. **Loop semantics canonical at `_stop_condition_reevaluate_loop.md`** — see that file for state machine + iteration cap (default 2) + terminal-state branching. Producer-visible terminal outcomes are the CLOSED 4-value enum: `continued` / `foundation_only` / `scope_out` / `next_iteration` (internal-only branch states like `forced_terminal` are never recorded in the producer-visible outcome; the module maps them to `foundation_only` or `scope_out` with `terminal_reason: iteration_cap_reached`). § 8.4 stays a summary; the canonical implementation lives in the sub-module.
5. If operator picks (c) "Re-evaluate regulatory exposure": invoke `wizard/interview/_stop_condition_reevaluate_loop.md` § 4 regulatory-exposure entry; loop sub-module re-asks step 03 UP-6 probes + mutates `regulatory_exposure` if operator clarifies + re-evaluates stop conditions against unchanged shape.

Foundation state IS preserved through halt (staging file unchanged except for halt-log entries).

### 8.5 Documentation behavior (DOCUMENT path; foundation-only mode)

When a stop condition fires AND `shape_hypothesis.fallback_mode_offered == foundation-only` (operator chose foundation-only-mode at step 01/02 unsupported-shape transition):

For conditions 1-3 (capability mismatches that operator already accepted by choosing foundation-only):

1. Wizard appends to staging file:
 ```yaml
 stop_conditions:
 evaluated_at: 05_pre_vision
 fired: [<list of fired condition numbers>]
 halted: false
 documented_in_foundation: [<same list>]
 shape_hypothesis:
 recheck_log:
 - step: 05
 outcome: documented_in_foundation
 stop_conditions_recorded: [<list>]
 ```
2. No halt fires. Wizard proceeds to step 05.
3. **Foundation-only-mode implementation** (per `wizard/interview/_foundation_only_mode_gate.md` § 6). Documented stop-condition gaps land in `technical_architecture.md` § "Regulatory & compliance gaps (foundation-only mode)" at step 15 close, with one section per gap (framework name + capability gap + recommended resolution path; read from staging `stop_conditions.documented_in_foundation` + `control_matrix_active`). If `stop_conditions.documented_in_foundation` is empty, the section is omitted entirely (no empty header).

For condition 4 (regulated + no framework identified): **HALT fires even in foundation-only mode** — foundation docs cannot be written honestly without framework identification. Operator must complete operator-side compliance review and resume. Halt behavior per § 8.4 (a/b paths).

This split (HALT for full-system, DOCUMENT for foundation-only with condition 4 exception) is the structural resolution of "operator chose foundation-only knowingly; don't re-halt them; do faithfully record" without compromising honest characterization.

## 9. Forward-offered information capture integration

Per wizard CLAUDE.md § 9. At P1-2 (core purpose), operators frequently volunteer shape signals embedded in their answer:

- "an automated newsletter that goes out every Monday morning" — scheduled (`probe_1_scheduled_cadence` yes) + outbound (`probe_4` yes) signals embedded. **F6 note:** both are now markdown-NEUTRAL — a scheduled, outbound newsletter is markdown-deliverable (cron→Orchestrator + send-script per the markdown-agents execution model), NOT a non-markdown signal.
- "a thinking partner for legal research" — `probe_3` yes signal embedded
- "a customer portal where my team can log in and update records" — `probe_2` yes (multi-user) + `probe_10_inbound_serve` yes ("log in" = others connecting live) signals embedded → non-markdown

**Classifier integration (decision-E, amended v0→v1 — experiential capabilities beat):**

> **Amendment note (decision-E reversal).** The original v0 decision-E forced the four shape dimensions to fire as **cold, blank technical questions** and held inferred signals as NON-authoritative interpretive priors only. Under v1, shape is elicited via the **experiential capabilities beat** (§ 2.1) — post-definition, grouped, 3-state, experientially phrased. **The operator's explicit per-dimension answer IS the authoritative probe value.** This reverses decision-E's "cold probes always fire / inference never authoritative" stance, but preserves its *intent* (shape must rest on an explicit operator answer, never on misread prose): the operator still answers each dimension explicitly; only the FORM changes from cold-technical to experiential, and inference is now allowed to *frame* a question without ever *answering* it. Safe because the four dimensions are orthogonal, each is explicitly answered, and `unsure` is preserved as a first-class neutral signal. Resolved via cross-vendor design review (the v0-candidates "infer-and-confirm" and "radio forced-choice" were both rejected) plus an independent cross-vendor backstop; full provenance in the build-side decision records.

1. At the purpose (P1-2) answer and during the working-definition pass, the wizard scans the operator's free-text for shape-signal phrases heuristically. (Match patterns are spec-only at v0; precise inventory deferred to first-real-operator-data observation.)
2. Matched signals populate `shape_hypothesis.forward_offered_signals_at_step_01` as verbatim phrases.
3. All four capability dimensions are ALWAYS asked (§ 2.1) — forward-offered signals do NOT substitute for, pre-fill, or skip any dimension's answer.
4. Forward-offered signals may **contextualize the framing** of a question — e.g., "You mentioned a newsletter that goes out every Monday; should the system run on its own / on a schedule to do that, even when you're not there?" — but the operator still gives a clean yes/no/unsure, and that answer (not the inferred prior) is what is recorded. Inference colors the framing; it never decides the answer. (This is stricter than the v0 "resolve an ambiguous answer toward the inferred value" behavior, which is now removed.)

**Anti-pattern to avoid (sharpened under v1):** pre-filling a dimension's answer from inference, hiding/skipping a dimension because the purpose "already implied" it, or collapsing "unsure" into "no." Both rejected v0-candidates failed here — "infer-and-confirm" for automation-bias and a false confirm==answer equivalence; "infer-and-hide" for suppressing dimensions the operator never actually answered. Every dimension gets an explicit, un-pre-filled 3-state answer.

## 10. Mechanism stack record

| Field | Value |
|---|---|
| **mechanism_id** | `mech-shape-detection-v0` |
| **mechanism_name** | Shape-detection classifier |
| **mechanism_class** | Skill, pure markdown (advisory or guided) |
| **primary** | Step 01 experiential capabilities beat (5 questions across 4 dimensions: thinking-partner + leveled runtime + multi-user + outbound + inbound → `probe_1_scheduled_cadence` / `probe_2` / `probe_3` / `probe_4` / `probe_9_always_on` / `probe_10_inbound_serve`; sub-steps P1-4–P1-7b of `01_phase1_capture.md`, presented as one grouped beat) + (conditional) step 02 fallback probes + classifier emit logic in `wizard/shape_detection.md` |
| **reinforcing** | Pre-step-05 re-check + pre-step-08 re-check; forward-offered signal capture at P1-2 (interpretive prior) |
| **detection-recovery** | Pre-step-05 stop-condition evaluation → halt with foundation state preserved; unsupported-shape transition → scope-out OR foundation-only; pre-step-05/08 re-check revise path |
| **rationale** | Behavior-based detection (not shape-name probing) prevents the technical-knob-mismatch failure. Pre-step-05 + pre-step-08 re-check catches signal drift from accumulated interview context. Stop conditions prevent silently generating a system the operator's regulatory exposure can't accept. Unsupported-shape transition preserves operator's foundation state so a future wizard release can resume without restart. Forward-offered signal capture acts as interpretive prior only — probes remain canonical. |
| **hybrid_contract_status** | n/a (not skill-calls-script) |
| **contract_fields_complete** | n/a |
| **health_check_last_run** | 2026-05-19 (initial fixture-replay) |
| **fallback_verified** | yes for the v0 classifier logic (synthetic-fixture replay). The experiential-elicitation revision is validated against the same fixtures (probe values unchanged). The **runtime+integration reconciliation** DELIBERATELY changes classifier output, so the shape-detection fixtures were re-derived (`s02`/`s04`/`s06`/`s07`/`fo01` re-authored to preserve non-markdown intent via `always_on`/`inbound_serve`; new positive `s09-scheduled-outbound-agent`); validated by hand re-derivation (cross-vendor advisor review). Real-operator validation bound to the step-02 re-walk. |

## 11. Versioning

This is **v1** (was v0 through the prior slice). The mechanism evolves through:

- **Probes refined** (calibration) — small revision; v0 → v0.1 amend.
- **Stop conditions added** (e.g., a 5th condition) — substantive revision; v0 → v1.
- **Schema field added to handoff contract** — substantive revision; coordinate with `wizard/handoff_contracts/shape_detection_v0.md` → v1.
- **Foundation-shaping change** (e.g., shape taxonomy revised; classifier rewritten as non-markdown mechanism) — foundation-shaping; new mechanism_id.

**v1 amendment (2026-06-01) — elicitation revised; no contract/classifier change.** The four shape dimensions are now elicited via the experiential capabilities beat (§ 2.1) instead of cold technical probes, and § 9 decision-E is reversed accordingly (the explicit per-dimension answer is now authoritative). This is a substantive elicitation revision (v0 → v1), NOT a foundation-shaping change: the shape taxonomy is unchanged, the classifier (§ 2.3) and confidence rubric (§ 3) are unchanged, and the emit schema (§ 4) and handoff-contract surface (`wizard/handoff_contracts/shape_detection_v0.md`) are unchanged — `probe_1..4` values + the four lifecycle phases are identical. Therefore the **`mechanism_id` stays `mech-shape-detection-v0`** (the `-v0` suffix is the mechanism-generation identifier, distinct from this spec version) and the handoff-contract filename + `schema_versions` are NOT bumped. The handoff contract's own version is untouched because no field name, value enum, or phase changed. Cross-vendor advisor backstop owed before merge per the build-side ledger.

**Runtime + integration reconciliation amendment (2026-06-02) — with the markdown-agents execution model; classifier + contract DO change (cross-vendor advisor-backstopped).** Distinct from the elicitation amendment above: this one DELIBERATELY changes the downstream invariant the elicitation slice preserved. (a) Runtime probe → one leveled question deriving `probe_1_continuous_runtime`→**`probe_1_scheduled_cadence`** (renamed; shape-NEUTRAL — scheduled is markdown-fine per the markdown-agents execution model) + new **`probe_9_always_on`** (the only non-markdown runtime trigger). (b) Integration split: `probe_4` kept but re-mapped **shape-NEUTRAL** (outbound is markdown-fine) + new **`probe_10_inbound_serve`** (non-markdown trigger). (c) §2.3 decision table + §3 confidence rubric rewritten (new HIGH branch (c), absence-of-disqualifiers); §2.2 `probe_6` fixed. (d) The runtime answer is recorded RAW to transcript qid `P1-4` as `runtime_mode` (the cross-vendor-recommended wiring — a durable always-on record without a new qid; orchestration_build manifest UNCHANGED). **Handoff contract `schema_major` bumped 0 → 1** (field rename = breaking per contract § 6); `schema_minor` reset to 0. **12 consumer abort-checks** (05_vision / 06_approach / 07_advisors / 08_architecture / 09_credentials / 10_validation / 11_error_handling / 12_qa_settings / 13_operations / 14_document_review / 15_close / _foundation_only_mode_gate) updated to expect major `1`. Shape taxonomy + 4 stop conditions + control-matrix status values are UNCHANGED, so this is NOT a foundation-shaping change (`mechanism_id` stays `mech-shape-detection-v0`; the change is a substantive within-generation revision). Advisor: cross-vendor design critique + an independent cross-vendor backstop (full provenance in the build-side decision records).

## 12. Cross-references

- `wizard/handoff_contracts/shape_detection_v0.md` — handoff contract for downstream consumers.
- `wizard/interview/01_phase1_capture.md` — P1-4 through P1-7b capabilities-beat sub-steps (runtime / multi-user / thinking-partner / outbound / inbound).
- `wizard/interview/02_financial.md` — P02-end fallback hook.
- `wizard/interview/03_user_profile.md` — UP-6 regulatory-applicability probe.
- `wizard/interview/_pre_step_05_recheck.md` — pre-step-05 re-check module.
- `wizard/interview/_pre_step_08_recheck.md` — pre-step-08 re-check module.
- `wizard/CLAUDE.md` § 9 (Forward-offered information capture) — integration source.
