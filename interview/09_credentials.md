# 09 — Credentials

## What this file does
**Capture-only.** Identify every credential the system will need, capture light metadata for each (type, provider, expiry behavior), and capture the operator's two global expiry preferences (warning lead time, no-expiry check cadence). Claude proposes the full credential inventory + per-credential metadata from the confirmed vision, approach, and architecture content — the operator confirms and adjusts but is never asked to enumerate credentials from scratch, and is never asked to know each provider's expiry rules.

No files are created here and no credential values are collected. The deterministic generator emits the protection files at close (`.gitignore`, an empty `.env`, the pre-populated `/security/credentials_registry.md` with `Status: Pending` rows, `/security/gitignore_manifest.md`). The operator obtains, pastes, and verifies each value **after the build, at first boot**, guided by the generated system's credential-setup skill — that is the right place for it: the `.env` exists, the system can verify, and the operator is walked through it interactively rather than left with static instructions. This step's job is to capture what the build + first-boot setup need.

## When this file runs
After `08_architecture.md` completes: `step_08: complete` is in `~/claude-wizard-draft/wizard_progress.md` and `group_approach_roster_confirmed` is recorded in the transcript. These are the authoritative completion signals; the staging-file `ARCHITECTURE_CONFIRMED` mirror is a human-readable convenience, not the gate.

## Prerequisites
`step_08: complete` in `~/claude-wizard-draft/wizard_progress.md`, and `group_vision_confirmed` + `group_approach_roster_confirmed` recorded in `~/claude-wizard-draft/wizard_transcript.jsonl`. The vision and approach/architecture content is confirmed in the transcript; the foundation documents themselves are emitted by the generator at close (`15_close.md`), so they are not on disk yet — read the confirmed content from the transcript, not from disk files.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 09_credentials.md. Step 9 (architecture) is complete. Read the staging file and the confirmed interview transcript, then continue from where you left off."

Do not begin CRED-1 until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_09_*` (e.g., `step_09_CRED-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_09: complete`) is not, proceed directly to the success condition.

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

Before the credential questions below, read `wizard/interview/_operator_interaction_contract.md` and apply it — propose the credential inventory grounded in the operator's vision and architecture, plain voice, no filler. This step has copy-paste-exact commands and file contents (`.env`, `.gitignore`) that stay verbatim per rule #3; the contract's "intent, not script" latitude covers conversational wording only.

---

## Step opening — progress and preview

**Say:**

> **Step 10 of 16 — Credentials**
> We'll set up the keys and logins your system needs to connect to external services.

---

## How to run this phase

Read the confirmed vision and approach/architecture content from the transcript before speaking (those foundation documents are emitted at close, not on disk yet). Build a complete candidate credential list from everything you find — data sources, APIs, integrations, external services, any system the agents will connect to.

**The operator does not design the credential list.** You propose it — the inventory and the per-credential metadata. They confirm, remove, or add.

No credential value is collected here; values are pasted at first boot, not during the interview. For each credential you capture metadata only: plain-language name, ENV-variable name, type, provider, and provisional expiry behavior. Expiry behavior you PROPOSE from what you know about the provider, **marked as provisional** ("I believe this is a key that doesn't expire on its own — I haven't checked your account; the system will confirm by watching it"); **default to Unknown when you're not sure**. Never ask the operator to state a provider's expiry rules — ask only what they can actually know (which service, whether they have an account / admin access, whether it's a key vs. a login).

---

## CRED-1 — Credential inventory [DYNAMIC]

Present the proposed credential inventory. For each credential: what it is, what the system needs it for, and what stops working without it.

**Say:**

> Before we start collecting anything, I want to show you every credential your system will need — so nothing surprises you later.
>
> Based on your vision, approach, and architecture documents, here's what I'm seeing:
>
> **[Credential plain-language name]**
> [What it is — one sentence in plain language.] Your system needs it to [what it does]. Without it, [what stops or degrades].
>
> **[Repeat for each credential.]**
>
> Does this list look complete? Is there anything here you know you don't have access to yet, or anything missing that you'd expect to need?

**Wait for answer.**

- If the operator confirms: proceed to CRED-2.
- If the operator removes a credential: note what capability is affected, confirm, and remove it from the list.
- If the operator adds a credential: add it with a proposed name, function, and impact statement. Confirm before proceeding.
- If the operator doesn't have a credential yet: that's expected — none are obtained during the interview. Every credential is obtained at first-boot setup; just confirm it belongs on the list.

Store: CREDENTIAL_COUNT = number of confirmed credentials.

Write sub-step marker: Append `step_09_CRED-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**If zero credentials confirmed (operator removed all proposed credentials or none are needed):** Skip the CRED-2 metadata pass and the CRED-3/CRED-4 prompts. Store CREDENTIAL_COUNT = 0 and CREDENTIALS_CONFIRMED = true in the staging file. The generator still emits the protection files (`.gitignore` + empty `.env`) at close regardless. **Still record the group inputs so the `orchestration_build` group can close** — in the Recording section below, record CRED-1 = `"none"`, CRED-2 = `"none (no credentials)"`, CRED-3 = `"14"`, CRED-4 = `"quarterly"` (defaults; they only matter if a credential is added later), and skip CRED-5. Say:

> No credentials needed right now — that's fine. Your system still ships with secrets protected, in case you add a credential later. You can add one at any time by telling the system "add a credential."

Then run the Recording section with those values and proceed to the success condition.

---

## Protection files (emitted at close — nothing is written here)

The protection files are NOT created during the interview (there is no project directory yet — the system is assembled at close). At close, the deterministic generator emits, in the correct order: `.gitignore` (with `.env` and `/security/session_cookies/` excluded), an empty `.env`, the pre-populated `/security/credentials_registry.md` (rows ship `Status: Pending`, derived from the inventory + per-credential metadata captured below), and `/security/gitignore_manifest.md`. The `.env`-is-gitignored guarantee holds structurally: the generator emits `.gitignore` (excluding `.env`) and the empty `.env` together, and the operator only adds real values later, at first-boot setup. **Do not write any of these files now.** Proceed to CRED-2 to capture the per-credential metadata.

---

## CRED-2 — Per-credential metadata [DYNAMIC]

Work through each confirmed credential in turn and capture its metadata. **No obtaining, no pasting, no testing here** — all of that happens at first-boot setup, walked by the credential-setup skill. For each credential you propose the metadata and the operator confirms or corrects:

- **ENV-variable name** — the name the system reads it from (e.g. `CALENDAR_API_KEY`). Propose a clear one.
- **Type** — API key / OAuth token / username+password login / other. You can usually tell from the provider; confirm with the operator only the part they'd actually know (e.g. "you sign into this one with a username and password, right?").
- **Provider** — the service it comes from.
- **Expiry behavior (PROVISIONAL — your proposal, never an assertion).** From what you know about the provider, propose whether it expires and how it renews, said honestly. **Default to Unknown when unsure.** Never ask the operator to state a provider's expiry rules — that's not something they can know.

**For each credential, say:**

> **[Credential plain-language name]** — this comes from [provider], and it's [a key the system uses / a login you sign into].
> The system will store it under the name `[ENV_VAR_NAME]`.
> [Provisional expiry, said honestly — e.g. "I believe this kind of key doesn't expire on its own; I haven't checked your account, so the system will keep an eye on it and tell you if that changes." OR "I'm not certain how this one expires — the system will watch it and confirm."]
>
> Does that look right? Anything to correct?

**Wait for answer.** Record the confirmed metadata (ENV-variable name, type, provider, provisional expiry). You are NOT collecting the value and NOT testing anything here — that is the first-boot setup step. If the operator corrects the type, provider, or expiry, use their correction; if they don't know, leave expiry as Unknown.

This metadata is what pre-populates the credentials registry (`Status: Pending`, no values) at close, and what the first-boot credential-setup skill uses to walk the operator through obtaining each value. Capture it for every confirmed credential, then proceed to CRED-3.

Write sub-step marker: Append `step_09_CRED-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## CRED-3 — Rotation lead time [FIXED — topic]

**Say:**

> For credentials that expire, I can warn you before they stop working — so you have time to rotate them without anything breaking.
>
> How many days' notice do you want before a credential expires?
>
> I'd suggest **14 days** — that's enough time to handle it without urgency, even if you're busy. But if you want more or less buffer, tell me.

**Wait for answer.**

- If the user accepts the default: confirm "14 days it is" and proceed.
- If the user chooses a different value: confirm the chosen value, note the rationale briefly if they gave one, and proceed.

Write the configured value to the staging file: `ROTATION_LEAD_TIME_DAYS = [n]`.

Write sub-step marker: Append `step_09_CRED-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## CRED-4 — No-expiry confirmation cadence [FIXED — topic]

**Say:**

> Some credentials don't expire — API keys from providers that don't rotate them automatically. For those, I'll check in with you on a schedule to confirm they're still valid, so nothing quietly breaks without warning.
>
> How often should I do that check?
>
> **Quarterly** is the default — once every three months. That's a reasonable interval for permanent credentials.
>
> You can choose: monthly, quarterly, or twice a year.

**Wait for answer.**

- If the user accepts the default: confirm "Quarterly check-ins for permanent credentials" and proceed.
- If the user chooses a different cadence: confirm the choice and proceed.

Write the configured value to the staging file: `NO_EXPIRY_CADENCE = [monthly / quarterly / biannual]`.

Write sub-step marker: Append `step_09_CRED-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## CRED-5 — Session lifetime [EXPLANATION]

*Show this section only if the confirmed credential list includes any username/password credentials.*

**Say:**

> For sites where you log in with a username and password, the system works differently. Instead of an API key, it logs in like a person would — fills in the form, gets a session, and remembers it.
>
> Sessions don't last forever. The system will learn how long each session stays valid and refresh it automatically before it expires. You don't need to configure anything for this — I just want you to know how it works.
>
> If a session fails and can't be refreshed automatically, the system will stop and tell you what to do.
>
> Does that make sense?

**Wait for confirmation.** If the user has questions, answer them in plain language. Then proceed.

Write sub-step marker: Append `step_09_CRED-5: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Capture complete (nothing written to disk)

After CRED-1 through CRED-5, there are no files to write or verify here — the generator emits the protection files (`.gitignore`, empty `.env`, `/security/gitignore_manifest.md`) and the pre-populated `/security/credentials_registry.md` (rows `Status: Pending`) at close. Confirm the capture is complete and summarize for the operator.

Update staging file: CREDENTIALS_CONFIRMED = true

**Say:**

> Your credentials are captured. When your system is built, it ships with secrets already protected — an empty, git-excluded `.env`, and a credential checklist that lists exactly what's needed.
>
> Here's what we captured:
>
> - **[n] credentials** your system will need — you'll add the actual values at first-boot setup, and the system walks you through getting each one
> - Expiry warnings set to **[n] days** before a credential expires
> - Credentials that don't expire re-checked **[cadence]**
>
> Next we'll set up the input validation layer — the guardrails that check what goes into your system.

Write sub-step marker: Append `step_09_WRITE: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Recording answers (event transcript)

Record the credential captures to `~/claude-wizard-draft/wizard_transcript.jsonl` as `orchestration_build` source answers. CRED-1 (inventory) + CRED-2 (per-credential metadata) feed `INTEGRATIONS` + the pre-populated `CREDENTIAL_REGISTRY_ROWS`; CRED-3 feeds `ROTATION_LEAD_TIME_DAYS`; CRED-4 feeds `CREDENTIAL_CHECK_CADENCE` — all derived at the step-13 `orchestration_build` barrier. CRED-5 (the session-lifetime explanation) carries no derivation source and is recorded as a skip:

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid CRED-1 --group orchestration_build --value "<the credential / integration inventory>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid CRED-2 --group orchestration_build --value "<per-credential metadata: ENV variable / type / provider / provisional expiry, one block per credential>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid CRED-3 --group orchestration_build --value "<rotation warning lead time in days, e.g. 14>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid CRED-4 --group orchestration_build --value "<no-expiry check cadence: monthly / quarterly / biannual>"
python3 wizard/scripts/interview_cli.py skip-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid CRED-5 --group orchestration_build --reason "session-lifetime explanation; no derivation source content"
```

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 09.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 09.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

CRED-1 through CRED-5 complete — **captured, not written to disk** (the protection files + the pre-populated registry emit at close). The inventory (CRED-1) + per-credential metadata (CRED-2) + rotation lead time (CRED-3) + no-expiry cadence (CRED-4) are recorded as `orchestration_build` source answers; CRED-5 recorded as a skip. CREDENTIALS_CONFIRMED = true in the staging file.

**Write completion marker:** Append `step_09: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `10_validation.md`.

---

## Foundation-only adapted path

**Disposition: ADAPT — capture credential inventory as foundation section; skip implementation file writes.**

Conduct the credential identification interview from the existing step content above (CRED-1 through CRED-5; Claude proposes credential inventory from vision + approach + architecture; operator confirms / adjusts).

**Difference from normal behavior:**

DO NOT:

- Walk operator through obtaining each credential (no `.env` to populate in foundation-only mode)
- Write `.env` to disk
- Write `.gitignore` to disk (no git init in foundation-only mode)
- Write `/security/credentials_registry.md` (security directory is implementation-specific)
- Write `/security/gitignore_manifest.md` (security directory is implementation-specific)

DO:

- Conduct the credential identification (name + purpose + acquisition path per credential)
- Append captured credential inventory to the staging file under `## Foundation-only-mode captures > Credential inventory` (credential NAMES + purposes + acquisition paths only; NOT actual credential values)

At step 15 close, the captured credential inventory extracts to `technical_architecture.md` § "Operational requirements" > "Credential inventory" per `_foundation_only_mode_gate.md` § 5.

**Important note for the operator (deliver verbatim):**

> In foundation-only mode, I'm capturing your credential inventory as a foundation-level list — what credentials a future implementation will need. I'm not walking you through obtaining each credential or generating a `.env` file. Those steps happen at implementation time, either when you take these foundation docs to Claude Code directly OR when you re-run the wizard once v2 adds support for your project's shape.

**Write completion marker:** Append `step_09: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `10_validation.md`.
