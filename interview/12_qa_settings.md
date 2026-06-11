# 12 — Quality Preferences

## What this file does
Configure how the QA system works: investigation reporting style, preferred future alert channel, the monitored-source health detail, and how often the system checks uncertain outputs with the user. The sources themselves were captured once at step 09 (the dependency record); this step confirms which of them are health-monitored and captures any health detail — it does not re-enumerate. The QA-3 answer is recorded to the transcript and the source registry is emitted as `/quality/source_registry.md` at close (a projection of the canonical record) — nothing is written mid-interview; quality preference values are written to the staging file.

## When this file runs
After `11_error_handling.md` completes: `step_11: complete` is in `~/claude-wizard-draft/wizard_progress.md`. The staging-file `ERROR_HANDLING_CONFIGURED` mirror is a human-readable convenience, not the gate.

## Prerequisites
`step_11: complete` in `~/claude-wizard-draft/wizard_progress.md`.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 12_qa_settings.md. ERROR_HANDLING_CONFIGURED = true. Read the staging file, then continue from where you left off."

Do not begin QA-1 until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_12_*` (e.g., `step_12_QA-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_12: complete`) is not, proceed directly to the success condition.

---

## Foundation-only-mode entry guard

Before doing anything else in this step:

1. **Schema-version check (per handoff contract consumer rule).** Read `~/claude-wizard-draft/wizard_session_draft.md`; locate the `schema_versions` block under shape_hypothesis. Verify `schema_major == 1`. If `schema_major` mismatches the consumer expected major (currently `1`), abort with operator-facing internal-state error: "I hit a wizard-internal version mismatch — the staging file's shape-detection schema major is `<actual>`, but this version of the wizard expects major `1`. Your project file is saved. Please update the wizard OR resume with the matching wizard version." Exit cleanly; do NOT proceed.

2. Locate the `shape_hypothesis.fallback_mode_offered` field.

3. Consult `wizard/interview/_foundation_only_mode_gate.md` § 2 derivation rule. Determine:
   - `produce_foundation_docs` (boolean)
   - `produce_system_implementation` (boolean)
   - `capture_implementation_inputs` (boolean)
   - `honest_characterization_disclosure` (enum value)

4. Branch:
   - If `produce_system_implementation == true` (label is `complete` OR `not_offered`): follow the rest of this file's existing step content below this entry guard (the wizard's normal behavior for this step).
   - If `produce_system_implementation == false` AND `produce_foundation_docs == true` (label is `foundation-only`): skip the existing step content and follow the section titled `## Foundation-only adapted path` at the end of this file.
   - If `produce_foundation_docs == false` (label is `scope-out`): wizard-internal-state error — wizard should have exited at the unsupported-shape transition; do NOT proceed past this step. Halt with internal-error message; foundation state preserved.

5. If `fallback_mode_offered` is missing from staging file entirely: wizard-internal-state error. Halt with internal-error message; foundation state preserved. Tell operator: "I hit an internal state error in the wizard. The shape hypothesis is missing. Your project file is saved at `~/claude-wizard-draft/wizard_session_draft.md`. Please resume the wizard; it'll pick up at the right step." Exit cleanly.

---

## Operator Interaction Contract

Before the QA questions below, read `wizard/interview/_operator_interaction_contract.md` and apply it — ground the examples and the recommendation in the operator's own domain (vision + approach), keep the ask balanced, plain voice, no filler.

---

## Step opening — progress and preview

**Say:**

> **Step 13 of 16 — Quality settings**
> We'll set up your system's quality controls and how it monitors its own work.

---

## How to run this phase

QA-1, QA-3, and QA-4 require specific user choices. QA-2 is a brief preference capture — no action is taken on it now. Work through them in order.

---

## QA-1 — Investigation workflow reporting style [FIXED — topic]

Present the same quality issue handled two ways. **Use the user's actual system context** — pick one agent and a realistic quality issue from the user's domain, grounded in the confirmed vision and approach content read from the transcript (`~/claude-wizard-draft/wizard_transcript.jsonl`); the foundation documents emit at close, so they are not on disk yet. The user makes a better choice when they see how QA notifications will actually look in their system. The examples below are fallback structure — replace with the user's real system context.

**Say:**

> When your QA agent finds something worth investigating, there are two ways it can keep you informed. Here's the same situation handled both ways:

---

> **Option 1 — Summary when done**
>
> You get one message when the investigation is complete:
>
> > **QA finding resolved**
> > I investigated why [specific output from user's system] was [specific quality issue]. [Root cause in plain language]. I've flagged the pattern as a rule so it won't happen again. No action needed — I'll include this in your next digest.
> > Run `./start-session.sh --resume` if you'd like to review the details.

---

> **Option 2 — Updates as it goes**
>
> You get a message at each step of the investigation:
>
> > **QA — investigation started**
> > I noticed [specific quality issue] in [specific output]. Starting investigation now.
>
> > **QA — finding identified**
> > [Root cause in plain language]. Checking whether this is a one-time issue or a pattern.
>
> > **QA — resolved**
> > Confirmed it's a pattern. I've added a rule to catch it. No action needed — I'll include this in your next digest.

---

> Which style do you prefer — summary when done, or updates as it goes?

**Wait for answer.**

- If the user chooses summary: confirm "Summary when done" and proceed.
- If the user chooses updates: confirm "Updates as it goes" and proceed.
- If the user asks if they can change it later: "Yes — tell me at any point."

Write the configured value to the staging file: `QA_REPORTING_STYLE = [Summary / Live]`.

Write sub-step marker: Append `step_12_QA-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## QA-2 — Future feedback channel [FIXED — topic]

**Say:**

> One more preference to record — this one doesn't change anything right now, but it's worth capturing.
>
> Your current alerts run through NTFY and email. As your system grows, you may want to move to a more direct channel for production alerts. When that time comes, what's your preference?
>
> **Options:** SMS, Slack, Teams, or Email (as a primary real-time channel rather than digest only)
>
> This is just recorded for now — we'll revisit it when the system is running and you're thinking about what comes next.

**Wait for answer.** Record the preference. If the user is unsure, note "undecided — revisit at Phase 3."

Write the configured value to the staging file: `FUTURE_ALERT_CHANNEL = [SMS / Slack / Teams / Email / Undecided]`.

Write sub-step marker: Append `step_12_QA-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## QA-3 — Confirm the monitored sources + capture their health detail [DYNAMIC]

The operator already described their external dependencies once, at step 09. Read the confirmed `EXTERNAL_DEPENDENCY_IDENTITY` record from the transcript (`~/claude-wizard-draft/wizard_transcript.jsonl`) and take the dependencies tagged with the **`health_monitored`** role — the ones whose uptime and behavior the QA agent watches. **Do NOT re-enumerate sources from scratch.** This step confirms that subset is complete and captures any health detail worth noting.

**Note:** not every dependency is monitored — a manual file upload can't be pinged, so it carries `boundary_input` but not `health_monitored`. You're confirming the watched subset, not re-listing everything.

**Say:**

> Your QA agent keeps an eye on the outside systems yours depends on — so if a connection breaks or a data format changes, it catches it before it causes problems. From what you told me earlier, these are the ones worth watching:
>
> **[Dependency name — from the step-09 list, the health_monitored ones]**
> [What it is — one sentence.] If it goes down or changes, [what stops or degrades].
>
> **[Repeat for each health_monitored dependency.]**
>
> Did I miss anything your system depends on staying up — or is anything here not really worth monitoring?

**Wait for answer.**

- If the user confirms: capture any health detail (the `health_facet` of the canonical record's annotation) and proceed.
- If the user says something is NOT worth monitoring: that is a role correction — note it (the `health_monitored` role comes off that dependency) and update the list.
- If the user names something to monitor that is NOT in the step-09 list: that is a new dependency (or a new role on an existing one) for the canonical record — capture it (name + what-stops + the `health_monitored` role) so it is added to `EXTERNAL_DEPENDENCY_IDENTITY`; it then flows into the source registry automatically.
- If a source is uncertain: mark it as pending.
- **If no dependency plays the `health_monitored` role** (nothing external is monitored — the system works with internal data only, or its dependencies can't be pinged): confirm with the user ("Based on what you told me, there's no outside source whose health your system needs to watch. Is that right?"). If confirmed, in the Recording section record `QA-3 = "none (no monitored sources)"` (NOT a skip). The `SOURCE_REGISTRY_ROWS` projection then renders a valid EMPTY table (no health_monitored rows). Set `SOURCE_COUNT = 0` in the staging file (a convenience flag). Proceed to QA-4.

**Propagate a role change back to the canonical record before continuing.** When the operator says a source is not worth monitoring, that removes the `health_monitored` role from the step-09 canonical record (`EXTERNAL_DEPENDENCY_IDENTITY`) — it does NOT necessarily remove the dependency. If the dependency still has other roles, keep it with the narrowed set. If `health_monitored` was its only role, confirm whether the system still uses it: a delivery or notification channel the operator simply doesn't monitor is still a dependency (it plays `boundary_output` — the system sends out through it); only drop it from the record if the system genuinely no longer relies on it. "Don't monitor it" means narrow the roles, not delete the dependency. Then re-record `DEP-1` with the change, re-derive + re-confirm `EXTERNAL_DEPENDENCY_IDENTITY`, and re-close the `dependency_inventory` group (the same three commands as step 09's Recording section). Without this, the `SOURCE_REGISTRY_ROWS` projection keeps the old roles and the operator's correction never reaches the emitted registry. (Capturing the health-detail facet is separate and still happens in the Recording section below.)

The confirmed health detail is *recorded* to the transcript in the Recording section below as the QA-3 source answer (it enriches the canonical record's annotation `health_facet`, which the `SOURCE_REGISTRY_ROWS` projection reshapes at the barrier) — nothing is written to a project directory mid-interview. The `quality/source_registry.md` file is generated at close.

Write sub-step marker: Append `step_12_QA-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## QA-4 — Confidence flagging threshold [FIXED — topic]

**Say:**

> Sometimes your system will produce something it's not fully confident about — a report where one figure is uncertain, a summary where a source was ambiguous. You can choose how often it stops to ask you when that happens.
>
> **Most cautious — Ask whenever uncertain:** Any time the system isn't fully confident in an output, it flags it for your review before proceeding.
>
> **Balanced — Ask when it matters:** The system flags uncertainty in high-sensitivity areas and anything that affects a decision or goes to a recipient. Routine outputs in low-sensitivity areas proceed with the uncertainty noted in the log.
>
> **Least cautious — Ask only for significant uncertainty:** The system only surfaces outputs where confidence is materially low. Minor uncertainty is logged but doesn't interrupt work.

Then:

> Based on your domain, I'd recommend **[Balanced / Most cautious]** as a starting point — [one-sentence rationale from the vision document, e.g., "your outputs go to clients, so uncertain figures reaching them would be a problem" or "your domain has high factual sensitivity so catching uncertainty early is worth the interruption"].
>
> Which would you like to start with?

**Wait for answer.**

- If the user accepts the recommendation: confirm and proceed.
- If the user chooses a different level: confirm and proceed.
- If the user wants to discuss what counts as "significant" uncertainty: explain that the system uses its own calibration based on domain sensitivity settings from the validation gate, and that it can be adjusted as patterns emerge.

Write the configured value to the staging file: `CONFIDENCE_FLAGGING_THRESHOLD = [Most cautious / Balanced / Least cautious]`.

Write sub-step marker: Append `step_12_QA-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Confirm quality configuration (no mid-interview disk write)

After QA-1 through QA-4, do NOT write any file to a project directory. The project directory does not exist yet (it is created at close), and writing one here would crash the close-emit's non-empty-target guard. The `quality/source_registry.md` file is generated at close from the QA-3 answer you record in the next section — the `SOURCE_REGISTRY_ROWS` derived field pre-populates the emitted registry's source rows (Source name / Type / Purpose / What stops without it, with Status = Pending). The Expected behavior, Last verified, and Health flag columns fill in at runtime — they describe observed health, which is not known at setup.

**Say:**

> Quality preferences confirmed. Here's what's in place:
>
> - QA reporting: **[Summary when done / Updates as it goes]**
> - Future alert channel preference: **[channel]** — recorded for when the time comes
> - **[n] external sources** your system will monitor
> - Confidence flagging: **[threshold level]**
>
> Next we'll set up the operational behavior settings — how the system handles retries, conflicts, startup, and drift.

Update staging file: QA_CONFIGURED = true

Write sub-step marker: Append `step_12_WRITE: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Recording answers (event transcript)

Record this step's derivation-group source answers to `~/claude-wizard-draft/wizard_transcript.jsonl`. QA-1 (reporting style) + QA-3 (source registry) are `tests_audit` sources; QA-2 (future feedback channel) is a `hitl_autonomy` source; QA-4 (confidence flagging threshold) is recorded as a skip (registry skip-satisfied — not a foundation-doc source):

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid QA-1 --group tests_audit --value "<investigation reporting style>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid QA-2 --group hitl_autonomy --value "<future feedback channel preference>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid QA-3 --group tests_audit --value "<health detail for the health_monitored dependencies from the step-09 record (enriches the annotation health_facet); + any monitored dependency the operator added here. Use 'none (no monitored sources)' if zero. Name/type/purpose/what-stops already live in the canonical record — do NOT re-state them; the SOURCE_REGISTRY_ROWS projection reshapes them.>"
python3 wizard/scripts/interview_cli.py skip-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid QA-4 --group tests_audit --reason "confidence flagging threshold; not a foundation-doc source"
```

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 12.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 12.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

QA-1 through QA-4 complete. QA-3 confirms the `health_monitored` subset of the step-09 dependency record and captures each one's health detail (enriching the annotation that the `SOURCE_REGISTRY_ROWS` projection reshapes at the barrier into the generated `/quality/source_registry.md`); nothing written to a project directory mid-interview. QA_REPORTING_STYLE, FUTURE_ALERT_CHANNEL, and CONFIDENCE_FLAGGING_THRESHOLD written to staging file. QA_CONFIGURED = true in the staging file (a convenience flag).

**Write completion marker:** Append `step_12: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `13_operations.md`.

---

## Foundation-only adapted path

**Disposition: ADAPT — capture QA approach as foundation section; skip implementation config files.**

Conduct the QA interview from the existing step content above (QA-1 through QA-4; investigation reporting style + future alert channel + source registry + confidence flagging cadence).

**Difference from normal behavior:**

DO NOT:

- Emit `/quality/source_registry.md` (the quality directory is implementation-specific; in foundation-only mode it is not emitted at close — and nothing is written mid-interview in any mode)
- Write QA_REPORTING_STYLE, FUTURE_ALERT_CHANNEL, or CONFIDENCE_FLAGGING_THRESHOLD to `project_instructions.md` as wizard-runtime config

DO:

- Conduct the QA questions and capture answers
- Append captured QA approach to the staging file under `## Foundation-only-mode captures > QA approach` (reporting style + source list + confidence flagging cadence + future alert channel preference)

At step 15 close, the captured QA approach extracts to `technical_architecture.md` § "Operational requirements" > "QA approach" per `_foundation_only_mode_gate.md` § 5.

**Write completion marker:** Append `step_12: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `13_operations.md`.
