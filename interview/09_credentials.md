# 09 — System boundaries & external dependencies

## What this file does
**Capture-only.** Identify every external dependency the system relies on — anything it receives data from, sends data to, monitors the health of, or needs a login/key for — and capture each one ONCE with the role(s) it plays. Claude proposes the full dependency inventory from the confirmed vision, approach, and architecture content; the operator confirms and adjusts but is never asked to enumerate dependencies from scratch. For the dependencies that need a login or key, a short credential sub-pass captures light metadata (type, provider, expiry behavior). The operator also sets two global credential-expiry preferences (warning lead time, no-expiry check cadence).

This is the single place the operator describes their external dependencies. Later steps (input validation, QA monitoring) reuse this same list — they confirm which dependencies play their role and add a detail, but they never re-ask "what are your external systems."

No files are created here and no credential values are collected. The deterministic generator emits everything at close from the confirmed inventory: the validation gate, the source registry, the credentials registry (`Status: Pending` rows), the protection files (`.gitignore`, an empty `.env`, `/security/gitignore_manifest.md`). The operator obtains, pastes, and verifies each credential value **after the build, at first boot**, guided by the generated system's credential-setup skill — the right place for it, where the `.env` exists and the system can verify interactively.

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

Do not begin DEP-1 until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_09_*` (e.g., `step_09_DEP-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

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

Before the questions below, read `wizard/interview/_operator_interaction_contract.md` and apply it — propose the dependency inventory grounded in the operator's vision and architecture, plain voice, no filler. This step has copy-paste-exact commands and file contents (`.env`, `.gitignore`) that stay verbatim per rule #3; the contract's "intent, not script" latitude covers conversational wording only.

---

## Step opening — progress and preview

**Say:**

> **Step 10 of 16 — System boundaries & external dependencies**
> Every system touches the outside world somewhere — a spreadsheet it reads, a service it sends mail through, a site it logs into. Let's list those once, so the rest of the setup can reuse the list instead of asking you again.

---

## How to run this phase

Read the confirmed vision and approach/architecture content from the transcript before speaking (those foundation documents are emitted at close, not on disk yet). Build ONE complete candidate list of external dependencies from everything you find — data sources, files, APIs, integrations, outbound services, any system the agents connect to, monitor, or sign into.

**The operator does not design this list.** You propose it — the dependencies, what each one is for, and which relationship(s) the system has with it. They confirm, remove, or add.

For each dependency, the relationship is one or more of four **roles**:

- **It sends data in** — the system reads from it, so what comes in needs checking (a spreadsheet of tasks, an inbound form, a file upload).
- **The system sends out through it** — the system depends on it to deliver something outward (a push-notification channel, an outbound mail server, a sheet it writes back to). This holds even when there is nothing to check coming in and nothing to monitor.
- **Its health is watched** — the system depends on it staying up and behaving, so it's worth monitoring (an API that can go down, a feed that can go stale).
- **It needs a login or key** — the system has to authenticate to use it (an API key, a username/password login).

A dependency can play several roles (an inbound CRM API sends data in, is watched, and needs a login) or just one (a manual file upload only sends data in; a push-notification channel the operator is happy to assume works only sends out; an outbound mail server sends out, is watched, and needs a login but takes no input). You propose the roles from what the dependency is; the operator corrects. Every dependency the system relies on belongs on the list, even one that is only a delivery channel — "we don't need to monitor it" removes the watch role, not the dependency.

Do NOT ask the operator to state a provider's expiry rules or anything technical they can't know — ask only what they can actually know (which service, whether they have an account, whether it's a key or a login).

---

## DEP-1 — External-dependency inventory [DYNAMIC]

Present the proposed dependency inventory. For each: a plain-language name, what it is, what the system uses it for, what stops without it, and which role(s) it plays.

**Say:**

> Based on your vision, approach, and architecture, here's every outside thing I think your system depends on — so nothing surprises you later:
>
> **[Dependency plain-language name]**
> [What it is and what your system uses it for, in one or two plain sentences, ending with what stops or degrades without it. Work the relationship into those sentences in plain words — whether the system takes data in from it, signs into it with a login or key, keeps an eye on whether it stays up, or some combination — instead of labeling it. For example: "reads your task list and writes updates back, and signs in with your Google account to do it; it also watches the connection, since a changed format would quietly throw the list off," or "only sends mail out, and keeps an eye on whether sending is working."]
>
> **[Repeat for each dependency.]**
>
> Does this list look complete? Anything here you don't actually use, or anything missing you'd expect to need? And for each one — did I get how your system uses it right?

**Wait for answer.**

- If the operator confirms: proceed to the writes-back ownership sub-pass, then the credential sub-pass.
- If the operator removes a dependency: note what capability is affected, confirm, and remove it.
- If the operator adds one: add it with a proposed name, purpose, impact, and role(s). Confirm before proceeding.
- If the operator corrects a role: use their correction. Every dependency must end with at least one role.
- If the operator doesn't have a dependency set up yet: that's expected — nothing is obtained during the interview. Just confirm it belongs on the list.

Store: DEPENDENCY_COUNT = number of confirmed dependencies. For each, hold its name, type (use "Unknown" if unclear), purpose, what-stops, confirmed role(s), and — for a writes-back (`boundary_output`-with-mutation) dependency — the owning agent confirmed in the writes-back ownership sub-pass.

Write sub-step marker: Append `step_09_DEP-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**If zero dependencies confirmed (the system is fully self-contained):** Skip the credential sub-pass and the CRED-3/CRED-4 prompts. Store DEPENDENCY_COUNT = 0 and CREDENTIALS_CONFIRMED = true. The generator still emits the protection files (`.gitignore` + empty `.env`) and empty registries at close. In the Recording section below, record DEP-1 = `"none"`, CRED-3 = `"14"`, CRED-4 = `"quarterly"` (defaults; they only matter if a dependency is added later), skip CRED-5, and derive `EXTERNAL_DEPENDENCY_IDENTITY` as an empty list (`[]`). Say:

> No outside dependencies right now — that's fine. Your system still ships with secrets protected, in case you add one later. You can add a dependency at any time by telling the system about it.

Then run the Recording section with those values and proceed to the success condition.

---

## Writes-back ownership sub-pass [DYNAMIC]

*Run this only for the dependencies the operator confirmed the system **sends data out through by writing back to it** — a sheet it updates, a tracker it writes rows into, a record it changes (the `boundary_output` role where the system mutates the surface, not a fire-and-forget notification channel). Skip it entirely if none do.*

For each such dependency, exactly one agent should own writing to it — the agent whose job includes updating that surface. The system routes every write to that surface through that owner (plus the coordinator, which is always allowed to write on the system's behalf). Knowing the owner is what lets the system grant the right agent permission to write there and refuse writes from anywhere else.

**You propose the owner from the agent roster and what each agent does; the operator confirms.** Do not ask the operator to design this — name the agent you believe owns the write and why, and let them correct.

**For each writes-back dependency, one at a time, say:**

> **[Dependency name]** — your system writes back to this one. From the roster, the agent that does that work looks like **[proposed agent display name]** ([one plain phrase on why — e.g. "it's the one that updates your task statuses"]).
>
> Is that the right agent to own writing to **[dependency name]**? If another agent should own it, tell me which.

**Wait for answer.** Record the confirmed owning agent's display name against that dependency. If the operator names a different agent, use their choice. If genuinely no single agent owns it yet, record the owner as unset — the coordinator still writes to it, but no specialist is granted the surface (the safe default).

Write sub-step marker: Append `step_09_WRITES-BACK: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Credential sub-pass [DYNAMIC]

*Run this only for the dependencies the operator confirmed play the **needs a login or key** role. Skip it entirely if none do.*

Work through each login/key dependency in turn and capture its credential metadata. **No obtaining, no pasting, no testing here** — all of that happens at first boot, walked by the credential-setup skill. For each you propose the metadata and the operator confirms or corrects:

- **ENV-variable name** — the name the system reads it from (e.g. `CALENDAR_API_KEY`). Propose a clear one.
- **Type** — API key / OAuth token / username+password login / other. You can usually tell from the provider; confirm only the part the operator would actually know (e.g. "you sign into this one with a username and password, right?").
- **Provider** — the service it comes from.
- **Expiry behavior (PROVISIONAL — your proposal, never an assertion).** From what you know about the provider, propose whether it expires and how it renews, said honestly. **Default to Unknown when unsure.** Never ask the operator to state a provider's expiry rules.

**For each login/key dependency, say:**

> **[Dependency name]** — this comes from [provider], and it's [a key the system uses / a login you sign into].
> The system will store it under the name `[ENV_VAR_NAME]`.
> [Provisional expiry, said honestly — e.g. "I believe this kind of key doesn't expire on its own; I haven't checked your account, so the system will keep an eye on it and tell you if that changes." OR "I'm not certain how this one expires — the system will watch it and confirm."]
>
> Does that look right? Anything to correct?

**Wait for answer.** Record the confirmed metadata (ENV-variable name, type, provider, provisional expiry) against that dependency. You are NOT collecting the value and NOT testing anything here. If the operator corrects the type, provider, or expiry, use their correction; if they don't know, leave expiry as Unknown.

This metadata is what pre-populates the credentials registry (`Status: Pending`, no values) at close, and what the first-boot credential-setup skill uses to walk the operator through obtaining each value.

Write sub-step marker: Append `step_09_CRED-META: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## CRED-3 — Rotation lead time [FIXED — topic]

*Skip if no dependency needs a login or key.*

**Say:**

> For credentials that expire, I can warn you before they stop working — so you have time to rotate them without anything breaking.
>
> How many days' notice do you want before a credential expires?
>
> I'd suggest **14 days** — enough time to handle it without urgency, even if you're busy. But if you want more or less buffer, tell me.

**Wait for answer.**

- If the user accepts the default: confirm "14 days it is" and proceed.
- If the user chooses a different value: confirm the chosen value, note the rationale briefly if they gave one, and proceed.

Write the configured value to the staging file: `ROTATION_LEAD_TIME_DAYS = [n]`.

Write sub-step marker: Append `step_09_CRED-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## CRED-4 — No-expiry confirmation cadence [FIXED — topic]

*Skip if no dependency needs a login or key.*

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

*Show this section only if the confirmed login/key dependencies include any username/password login.*

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

## Protection files (emitted at close — nothing is written here)

The protection files are NOT created during the interview (there is no project directory yet — the system is assembled at close). At close, the deterministic generator emits, in the correct order: `.gitignore` (with `.env` and `/security/session_cookies/` excluded), an empty `.env`, the pre-populated `/security/credentials_registry.md` (rows ship `Status: Pending`, derived from the login/key dependencies), and `/security/gitignore_manifest.md`. The `.env`-is-gitignored guarantee holds structurally: the generator emits `.gitignore` (excluding `.env`) and the empty `.env` together, and the operator only adds real values later, at first-boot setup. **Do not write any of these files now.**

---

## Capture complete (nothing written to disk)

After DEP-1, the credential sub-pass, and CRED-3/4/5, there are no files to write or verify here — the generator emits the protection files and the pre-populated registries at close. Confirm the capture is complete and summarize for the operator.

Update staging file: CREDENTIALS_CONFIRMED = true

**Say:**

> Your external dependencies are captured — once, with the role each one plays. When your system is built, this one list becomes everything that needs it: what the system checks on the way in, what it keeps an eye on, and what it needs a login or key for. Here's what we captured:
>
> - **[n] external dependencies**, each tagged with how your system uses it
> - **[m] of them need a login or key** — you'll add the actual values at first-boot setup, and the system walks you through getting each one
> - Expiry warnings set to **[n] days** before a credential expires
> - Credentials that don't expire re-checked **[cadence]**
>
> Next we'll set up the input validation layer — the guardrails that check what comes into your system.

Write sub-step marker: Append `step_09_WRITE: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Recording answers (event transcript)

Record the dependency inventory + global credential prefs to `~/claude-wizard-draft/wizard_transcript.jsonl`, then derive and confirm the canonical identity record and close the dependency group. DEP-1 (the role-tagged inventory) is the single source the canonical record is built from; it also feeds the validation (step 11) and QA (step 13) groups so a later edit re-flags them. CRED-3 feeds `ROTATION_LEAD_TIME_DAYS`, CRED-4 feeds `CREDENTIAL_CHECK_CADENCE` (both derived at the step-13 `orchestration_build` barrier). CRED-5 (the session-lifetime explanation) carries no derivation source and is recorded as a skip.

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid DEP-1 --group dependency_inventory --value "<the role-tagged external-dependency inventory: per dependency, name / what it is / purpose / what stops without it / role(s) / login-or-key metadata>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid CRED-3 --group orchestration_build --value "<rotation warning lead time in days, e.g. 14>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid CRED-4 --group orchestration_build --value "<no-expiry check cadence: monthly / quarterly / biannual>"
python3 wizard/scripts/interview_cli.py skip-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid CRED-5 --group orchestration_build --reason "session-lifetime explanation; no derivation source content"
```

Now derive the canonical identity record — a JSON array, one object per confirmed dependency: `id` (a short stable slug, e.g. `google_sheet`), `name`, `type` (or `"Unknown"`), `roles` (the confirmed subset of `boundary_input` / `boundary_output` / `health_monitored` / `needs_credential` — `boundary_output` is a dependency the system sends data out through, e.g. a sheet it writes back to or a notification channel it assumes works), a `credential_facet` (`env_var` / `cred_type` / `provider` / `provisional_expiry`) for the `needs_credential` ones, and — for each `boundary_output` dependency the system writes back to — an `owner_agent_id` set to the **slug of the owning agent confirmed in the writes-back ownership sub-pass** (the same slug form used for the agent roster: lowercase, non-alphanumeric characters replaced with `-`; e.g. the agent "Status Updater" becomes `status-updater`). Omit `owner_agent_id` for a writes-back dependency whose owner was left unset, and for every dependency that is not `boundary_output`. Then confirm it (the operator already confirmed the inventory inline above) and close the dependency group so step 09 can complete:

```
python3 wizard/scripts/interview_cli.py derive-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field EXTERNAL_DEPENDENCY_IDENTITY --sources DEP-1 --value '<JSON array of {id, name, type, roles, credential_facet?, owner_agent_id?}>'
python3 wizard/scripts/interview_cli.py confirm-field --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --field EXTERNAL_DEPENDENCY_IDENTITY --group dependency_inventory --state accepted
python3 wizard/scripts/interview_cli.py close-group --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --progress ~/claude-wizard-draft/wizard_progress.md --group dependency_inventory
```

The annotation (purpose / what-stops / per-role detail) and the three tabular registries are NOT derived here — they are built later: the annotation closes at step 13 after the validation and QA steps enrich its per-role detail, and the registries are deterministic projections computed at close. This step's job is the canonical identity record.

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

DEP-1, the credential sub-pass, and CRED-3/4/5 complete — **captured, not written to disk** (the protection files + the pre-populated registries emit at close). DEP-1 is recorded as a `dependency_inventory` source answer; CRED-3/CRED-4 as `orchestration_build` source answers; CRED-5 as a skip. `EXTERNAL_DEPENDENCY_IDENTITY` is derived, confirmed, and the `dependency_inventory` group is closed (`group_dependency_inventory_confirmed` recorded). CREDENTIALS_CONFIRMED = true in the staging file.

**Write completion marker:** Append `step_09: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`. (This is refused upstream unless `group_dependency_inventory_confirmed` is recorded first — close the group before marking the step.)

Proceed to `10_validation.md`.

---

## Foundation-only adapted path

**Disposition: ADAPT — capture the external-dependency inventory as a foundation section; skip implementation file writes.**

Conduct the dependency identification interview from the existing step content above (DEP-1 + the credential sub-pass; Claude proposes the inventory from vision + approach + architecture; operator confirms / adjusts).

**Difference from normal behavior:**

DO NOT:

- Walk the operator through obtaining each credential (no `.env` to populate in foundation-only mode)
- Write `.env` to disk
- Write `.gitignore` to disk (no git init in foundation-only mode)
- Write `/security/credentials_registry.md` (security directory is implementation-specific)
- Write `/security/gitignore_manifest.md` (security directory is implementation-specific)

DO:

- Conduct the dependency identification (name + purpose + role(s) + acquisition path per dependency)
- Append the captured inventory to the staging file under `## Foundation-only-mode captures > External dependency inventory` (dependency NAMES + purposes + roles + acquisition paths only; NOT actual credential values)

At step 15 close, the captured inventory extracts to `technical_architecture.md` § "Operational requirements" > "External dependencies" per `_foundation_only_mode_gate.md` § 5.

**Important note for the operator (deliver verbatim):**

> In foundation-only mode, I'm capturing your external-dependency inventory as a foundation-level list — what a future implementation will connect to, monitor, and need credentials for. I'm not walking you through obtaining each credential or generating a `.env` file. Those steps happen at implementation time, either when you take these foundation docs to Claude Code directly OR when you re-run the wizard once v2 adds support for your project's shape.

**Write completion marker:** Append `step_09: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `10_validation.md`.
