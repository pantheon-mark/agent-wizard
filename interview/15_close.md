# 15: Closing Sequence

## What this file does
Complete the wizard interview. Emit the entire operator system from the recorded interview transcript via the deterministic generator (CLOSE-EMIT). The transcript is the single source, the generator the single assembler. Initialize git and make the initial commit (CLOSE-4). Set up the GitHub remote backup (GH-1). Deliver a tight, action-oriented closing (CLOSE-13) with the first build prompt front and center (CLOSE-14), and point the user to the system guide and manual for reference. This is the final interview file.

## When this file runs
After `14_document_review.md` completes. All configuration is confirmed. Every answer is recorded in the event transcript; every foundation-doc field is derived and confirmed at its group barrier.

## Prerequisites
OPERATIONS_CONFIGURED = true in the staging file. All five logical groups are confirmed (`group_vision_confirmed` … `group_tests_audit_confirmed` markers present); the event transcript at `~/claude-wizard-draft/wizard_transcript.jsonl` carries every confirmed field + agent intent.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: the transcript is already on disk (nothing is lost), give the user the following instruction, and stop:

> Your project is saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 15_close.md. All configuration is complete. The interview transcript is on disk. Read the staging file and continue from where you left off."

Do not begin CLOSE-EMIT until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_15_*` (e.g., `step_15_CLOSE-EMIT: complete`), this step was partially completed in a prior session. Skip to the first section below that does NOT have a corresponding completion marker.

If all sub-step markers for this step are present but the step-level marker (`step_15: complete`) is not, proceed directly to the success condition.

---

## Foundation-only-mode entry guard

Before doing anything else in this step:

1. **Schema-version check (per handoff contract consumer rule).** Read `~/claude-wizard-draft/wizard_session_draft.md`; locate the `schema_versions` block under shape_hypothesis. Verify `schema_major == 1`. If `schema_major` mismatches the consumer expected major (currently `1`), abort with operator-facing internal-state error: "I hit a wizard-internal version mismatch. The staging file's shape-detection schema major is `<actual>`, but this version of the wizard expects major `1`. Your project file is saved. Please update the wizard OR resume with the matching wizard version." Exit cleanly; do NOT proceed.

2. Locate the `shape_hypothesis.fallback_mode_offered` field.

3. Consult `wizard/interview/_foundation_only_mode_gate.md` § 2 derivation rule. Determine:
 - `produce_foundation_docs` (boolean)
 - `produce_system_implementation` (boolean)
 - `capture_implementation_inputs` (boolean)
 - `honest_characterization_disclosure` (enum value)

4. Branch:
 - If `produce_system_implementation == true` (label is `complete` OR `not_offered`): follow the rest of this file's existing step content below this entry guard (the wizard's normal behavior for this step).
 - If `produce_system_implementation == false` AND `produce_foundation_docs == true` (label is `foundation-only`): skip the existing step content and follow the section titled `## Foundation-only adapted path` at the end of this file.
 - If `produce_foundation_docs == false` (label is `scope-out`): wizard-internal-state error. The wizard should have exited at the unsupported-shape transition; do NOT proceed past this step. Halt with internal-error message; foundation state preserved.

5. If `fallback_mode_offered` is missing from staging file entirely: wizard-internal-state error. Halt with internal-error message; foundation state preserved. Tell operator: "I hit an internal state error in the wizard. The shape hypothesis is missing. Your project file is saved at `~/claude-wizard-draft/wizard_session_draft.md`. Please resume the wizard; it'll pick up at the right step." Exit cleanly.

---

## Step opening: progress and preview

**Say:**

> **Step 16 of 16: Wrapping up**
> We'll build your project, set up your backup, and hand you the keys to start building.

---

## How to run this phase

The closing sequence has four parts:

1. **Emit the operator system** (CLOSE-EMIT, internal): run the generator over the recorded transcript; it writes the complete project to disk in one deterministic pass.
2. **Initial commit** (CLOSE-4, internal): initialize git and commit the completed wizard setup.
3. **GitHub remote setup** (GH-1): optional backup to a private GitHub repository.
4. **Closing and handoff** (CLOSE-13, CLOSE-14): tight action-oriented closing with the first build prompt front and center.

Work through these in order without skipping.

---

## Part 1: Emit the operator system (CLOSE-EMIT) [INTERNAL]

This step is internal. The user sees one plain-language progress message. This is where the recorded interview becomes a complete operator system on disk, emitted by the deterministic generator from the event transcript, NOT hand-assembled template-by-template.

**Say:**

> I'm now building your project files. This takes a moment.

### What this step does

The whole interview was recorded to an event transcript (`~/claude-wizard-draft/wizard_transcript.jsonl`): every confirmed answer, every derived foundation-doc field, every agent intent. One deterministic pass turns that transcript into the complete runnable operator system. There is no hand-assembly here. The transcript is the single source; the generator is the single assembler. (This replaces the legacy template-by-template close-assembly: the directory tree, every file, the model-flag resolution, and the special behaviors below are all produced by the generator from the transcript.)

### Run the unified emit

The project directory MUST NOT already exist (or must be empty). The generator creates and populates it fresh from the transcript. Run, from the wizard directory:

```bash
python3 wizard/scripts/interview_cli.py emit-system \
  --transcript ~/claude-wizard-draft/wizard_transcript.jsonl \
  --shape markdown-CC \
  --target-dir ~/[PROJECT_FOLDER_NAME] \
  --build-repo-root <the wizard directory root> \
  --project-name [PROJECT_NAME]
```

Internally this is the fail-closed bridge `build_operator_system_from_transcript`: it compiles the transcript to the derived record + agent intents, assembles a validated `EmissionPlan` (resolving the maintained tier→model map, so `start-session.sh` carries a real `--model`, not a tier name), and dispatches to the generator, which emits the complete tree: the foundation docs at the project root, the `/agents/` execution layer (orchestrator + per-agent prompts and scripts), the inherited corpus (`quality/rules_library.md` + the `decisions/` ADR core), every operational directory (`logs/`, `work/`, `docs/`, `security/`, `archive/`), the build-session helper templates (`wizard/review_prompts/`, `wizard/skills/`), an empty `.env`, and the `.wizard/` upgrade scaffold. The generator FAILS CLOSED before any file is written on a missing or empty derived input, a stale generator identity, or a non-empty target directory. **If the command raises, STOP and surface the error. Do NOT hand-assemble.**

### The legacy close-time scans are now derivations: do NOT redo them

The special behaviors the legacy close-assembly performed by hand are DERIVATIONS recorded in the transcript at their group barriers and emitted by the generator. Do NOT re-scan or re-assemble any of these here:

- **WI-011 constraint elevation** (vision constraints → Tier-1 always-ask policy) → the `TIER_1_ADDITIONS` policy derivation at the vision barrier.
- **WI-013 deferred items** → `docs/future_items.md` (the deferred-items derivation; empty when none were deferred).
- **Voice-and-style seeding** → carried inside the synthesis derivations' prose (not a separate close-time scan).
- **Name-consistency** → structural: the projector uses the operator's confirmed values verbatim everywhere, which eliminates the name-drift class without a close-time scan.

### Per-advisor interview guides (post-emission)

The generator does not emit the per-advisor interview guides. They are tailored prose, not a deterministic template. After the system is emitted, for each confirmed advisor (from the `ADV-1` answer in the transcript), write a first interview guide to `~/[PROJECT_FOLDER_NAME]/advisor/interview-guides/[advisor-role-slug]-interview-guide.md` using the guide format defined in `07_advisors.md` ADV-4 (purpose / about the system / 5 to 8 tailored questions / follow-ups, grounded in the vision + approach). If no advisors were confirmed, skip this. There are no guides to write.

### Verification

After the emit, verify (the generator's own fail-closed guards already enforce most of this, confirm it held):

1. The project directory exists and is non-empty.
2. Critical files present and non-empty: `CLAUDE.md`, `project_instructions.md`, `session_bootstrap.md`, `SESSION_STATE.md`, `vision.md`, `approach.md`, `technical_architecture.md`, `.gitignore`, `docs/how_your_system_works.md`. (`.env` is present but intentionally empty. Credentials are added at setup.)
3. `start-session.sh` is executable and contains `--model` with a real model name (not a tier name or placeholder).
4. No unresolved `{{...}}` placeholders survive, EXCEPT inside the operator-fill templates under `wizard/review_prompts/` and `wizard/skills/`, which intentionally keep their placeholders for the operator to complete during build sessions.

If any check fails: STOP, surface what is missing, and do not proceed to CLOSE-4.

**Say:**

> Your project files are built. Everything from the interview has been written to your project directory. Let me save a snapshot.

Proceed to Part 2 (CLOSE-4).

Write sub-step marker: Append `step_15_CLOSE-EMIT: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Part 2: Initial commit (CLOSE-4) [INTERNAL]

This step is internal. Do not narrate it to the user in technical terms. One plain-language confirmation line is sufficient.

**Before committing:**

1. Verify that `.gitignore` is in place and excludes `.env` (the generator emits both; confirm). Do not proceed if `.gitignore` is absent.
2. Verify `wizard_feedback.md` is present in the project root (the generator emits it from the inherited corpus: it is the bridge from system runtime back to wizard improvement; agents write to it when they hit wizard-related issues). It is no longer created by hand here.

Run the following commands in the project directory:

```bash
git init -b main
git add .
git commit -m "Wizard setup complete — [PROJECT_NAME] initial commit"
```

**Say:**

> I've saved a snapshot of everything we've set up. Your project is now under version control. Every change from here will be tracked.

Write sub-step marker: Append `step_15_CLOSE-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Part 3: GitHub remote setup (GH-1) [FIXED: topic]

GH-1 is optional but strongly recommended. It protects the user's work against hardware failure. A private GitHub repository is the default recommendation.

**Say:**

> Your project is saved locally on your computer. Would you like to also back it up to GitHub? This protects your work if something ever happens to your computer. It takes about five minutes and the repository will be private. Only you can see it.

**Wait for answer.**

---

**If the user says no:**

> That's fine. Your work is saved locally and every change is tracked in version control. You can connect to GitHub any time in the future by telling me "set up GitHub backup" at the start of a session.

Record in staging file: `GITHUB_REMOTE = false`. Proceed to Part 4.

---

**If the user says yes:** Work through the following steps in order.

**Step 1. Check for GitHub CLI:**

Run: `gh --version`

- If installed: proceed to Step 2.
- If not installed: **Say:** *"We need one more tool to connect to GitHub. Run this command:"*
 ```
 brew install gh
 ```
 Wait for confirmation that it completed. Re-run `gh --version` to verify. Then proceed to Step 2.

**Step 2. Check authentication:**

Run: `gh auth status`

- If authenticated: proceed to Step 3.
- If not authenticated: **Say:** *"Now we need to connect Claude Code to your GitHub account. Run this command:"*
 ```
 gh auth login
 ```
 Walk the user through the prompts in plain language:
 1. Select **GitHub.com**
 2. Select **HTTPS**
 3. Select **Login with a web browser**
 4. The terminal will show a one-time code and a URL. Open the URL in your browser, sign in to GitHub if prompted, and paste the code when asked.
 5. Authorize the application.

 Wait for *"Logged in to github.com"* to appear in the terminal. Then proceed to Step 3.

**Step 3. Check for a GitHub account:**

If the user authenticated in Step 2, they have an account. If they indicated they don't have one, direct them to `github.com` to create a free account before continuing.

**Step 4. Create the repository and connect:**

**Say:** *"Creating your private repository now."*

Run:
```bash
gh repo create [PROJECT_FOLDER_NAME] --private --source=. --remote=origin --push
```

This creates the private repository, connects it as `origin`, and pushes the initial commit in a single command.

**Step 5. Confirm:**

Run: `git remote -v`

Show the user their repository URL.

**Say:**

> Your project is now backed up to GitHub at [URL]. Every time your system saves a checkpoint, it will push to GitHub automatically, so your backup stays current.

Record in staging file: `GITHUB_REMOTE = true` and `GITHUB_REMOTE_URL = [URL]`.

Write `GITHUB_REMOTE_URL` to `project_instructions.md` under the system configuration section.

Write sub-step marker: Append `step_15_GH-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Part 4: Closing and handoff (CLOSE-13, CLOSE-14)

### CLOSE-13: Layered closing [EXPLANATION]

**This step is mandatory. It cannot be skipped or abbreviated.**

The closing has three layers. Deliver them in order. The first layer is what matters most: the user's immediate next action. Keep it tight.

---

**Layer 1. Immediate: what to do next**

**Say:**

> **Your wizard setup is complete.**
>
> Your project is at:
> `~/[PROJECT_FOLDER_NAME]/`
>
> **Here is the prompt to bring your first phase into operation.** It's also saved at `wizard/build_prompts/phase_01_build_prompt.md`, so if you close this window you won't lose it.
>
> Before running it: the prompt will walk you through setting up your credentials first (if any are pending). That step needs to happen before the first supervised run.

Then deliver CLOSE-14 immediately (the build prompt).

---

### CLOSE-14: Phase-1 build-and-operate prompt [INTERNAL]

**Before producing the prompt:** Read `execution_plan.md` in the project directory and identify the first phase in the build order. Note the agent(s) that belong to Phase 1. The generator has already written a complete prompt file for every agent at `agents/prompts/<agent>_prompt.md`. Phase 1 means bringing those already-emitted agents into operation and running them supervised against a copy of external state, then getting operator acceptance on the business result. There is no authoring from a blank file.

**Produce the following prompt** (exact wording, this becomes the paste-ready content):

---

> **Phase 1 build and operate: [PHASE-1 NAME from execution_plan.md]**
>
> Read these files in the project directory before doing anything:
> - `vision.md`
> - `approach.md`
> - `technical_architecture.md`
> - `project_instructions.md`
> - `session_bootstrap.md`
> - `execution_plan.md`
>
> You are bringing **Phase 1** into operation. Phase 1 is: [one sentence from execution_plan.md describing what Phase 1 covers and its agents].
>
> The wizard already generated prompt files for every Phase 1 agent at `agents/prompts/`. This session does NOT author agents from scratch. It brings what was generated into operation and confirms the business result works.
>
> Work through these steps in order:
>
> **Step 1: Credential Setup (if any credentials are pending)**
>
> Read `security/credentials_registry.md`. If any row has `Status: Pending`, run the Credential Setup skill before going further. That skill walks through pasting and verifying each credential so the system can reach its external dependencies. Do not proceed to the supervised run until all credentials the Phase 1 agents need are in place.
>
> **Step 2: Technical verification (silent)**
>
> Read each Phase 1 agent's prompt file at `agents/prompts/<agent>_prompt.md`. Verify that each one is complete and consistent with the foundation docs you read above. If anything is missing or misaligned, fix it silently before running. Do not surface technical architecture details to the operator; bring the agents to a runnable state on your own.
>
> Run the bypass scanner over the Phase 1 code to confirm every external write routes through the approved adapters:
>
> ```
> python3 agents/lib/external_write/scan.py agents/
> ```
>
> If the scanner reports any violation, the phase FAILS. Fix every flagged write by routing it through the approved external-write operations before continuing. Do not proceed to the supervised run until the scanner exits clean.
>
> **Step 3: Supervised run against a copy**
>
> Set up a copy or dummy target of any external state the agents will write to (for example, a copy of the master-list Sheet, not the live one). External state is not git-revertable, so the first run always goes against a copy. Run the Phase 1 agents with the operator present, narrating what each agent is doing and why.
>
> During this run, inject one clearly labelled, inert dummy Tier-1 action, exactly once and early in the run. The action you name in the drill must be one the Phase 1 agents are actually configured to perform. Before writing the drill, check Phase 1's agents -- the roster plus each agent's prompt file (its declared actions and its output profile) -- and pick a REAL irreversible or outbound action one of them actually does: something that goes out in the operator's name (a message, an email, a post, a write to an external system) or that cannot be undone from git. Name THAT action. Do not invent an action no Phase 1 agent performs, and do not borrow an example from another project or domain.
>
> If NO Phase 1 agent performs any irreversible or outbound action -- for example a research or helper agent that only reads and saves findings to the operator's own files -- do not invent one. Say plainly that the work is low-risk and demonstrate the approval prompt hypothetically:
>
> > [DRILL -- NOT A REAL ACTION] I am pausing to show you how approval works. The work in this phase only saves to your own files and changes nothing that can't be undone, so it is low-risk. But so you can see the guardrail: if I were ever about to do something that goes out in your name or cannot be undone, I would stop and need your explicit sign-off first. This is a drill. No action was taken. Please type "continue drill" to proceed.
>
> When Phase 1 DOES include a real irreversible or outbound action, name it:
>
> > [DRILL -- NOT A REAL ACTION] I am pausing to show you how approval works. In a real run, before <the real action, named from Phase 1's agents> I would stop and need your explicit sign-off first. This is a drill. No action was taken. Please type "continue drill" to proceed.
>
> The drill must be unmistakably labelled so the operator never thinks a real action was attempted. Its purpose is to demonstrate the guardrail once, visibly, before the operator accepts Phase 1.
>
> **Step 4: Business acceptance**
>
> Read `agents/acceptance/phase_01_acceptance.md`. Walk the operator through each question in that file (what the phase did, what changed, what it held back, residual risks, artifacts touched). Do not re-list the questions here; read and follow the acceptance packet. Capture the operator's answers as you go.
>
> If the operator accepts: record the verdict to `build_progress.md` in the project root with the date and a one-sentence summary of what was accepted.
>
> If the operator does not accept: note what needs to change, fix it in this session if possible, and re-run the supervised cycle before asking again. Do not move to Phase 2 until Phase 1 is accepted.
>
> **To start this session:** Run `./start-session.sh` from your project directory. The script is already configured to use the correct model.

---

**Write this prompt to disk:** `[PROJECT_DIR]/wizard/build_prompts/phase_01_build_prompt.md`. The generator does not create this directory, so create `[PROJECT_DIR]/wizard/build_prompts/` first if it does not exist (`mkdir -p`).

---

**After the build prompt, continue with Layer 2.**

---

**Layer 2. Reference: the build arc and where to look**

**Say:**

> **Here's how building works:** You bring one phase into operation at a time. For each phase: run it supervised against a copy of your data, confirm the business result looks right, then accept it. Only after you accept a phase do you move to the next one. Your `execution_plan.md` lists the phases in order.
>
> Phase 1 is covered by the prompt above. Phases 2 and later are driven by a "next phase" skill that lives in `wizard/skills/` in your project directory, so you always have it on hand.
>
> **Three things to know:**
>
> - Your Phase 1 build prompt is saved at `wizard/build_prompts/phase_01_build_prompt.md`. If you close this window before copying it, open that file.
> - Your project's `manual.md` covers setup, troubleshooting, and what to do if something goes wrong.
> - `docs/how_your_system_works.md` explains what your system does automatically: how it handles errors, what it holds for your approval, and more. Read it whenever you're curious.
>
> You're ready. Paste the prompt above into a new Claude Code session to bring Phase 1 into operation.

---

**Layer 3. Deep dive: on disk, not verbal**

There is no Layer 3 delivery. The system guide (`docs/how_your_system_works.md`) is already on disk from the emit step. The user reads it at their own pace. The wizard does not deliver behavior briefings verbally. They are written to disk where they can be referenced any time, rather than delivered in a moment when the user has just finished a long interview and is ready to act.

---

Write an audit trail entry: `Wizard setup complete. Phase 1 build-and-operate prompt written to wizard/build_prompts/phase_01_build_prompt.md. System guide written to docs/how_your_system_works.md. Closing sequence delivered.`

Write sub-step marker: Append `step_15_CLOSE-14: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 15.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 15.

**If neither condition is true:** Skip this section entirely. Do not show any prompt.

---

## Success condition

CLOSE-EMIT complete. The generator emitted the complete operator system from the transcript to the project directory, verification passed (critical files present, real `--model`, no stray placeholders), the system guide is at `docs/how_your_system_works.md`, and any per-advisor interview guides were written post-emission. CLOSE-4 git initialized and initial commit made. GH-1 complete (remote connected or user opted out, preference recorded). CLOSE-13 layered closing delivered: Phase-1 build-and-operate prompt front and center, loop framing provided, briefings on disk. Phase-1 build-and-operate prompt written to `/wizard/build_prompts/phase_01_build_prompt.md` and handed off to user. Audit trail entry written.

Update staging file: `WIZARD_COMPLETE = true`

**Write completion marker:** Append `step_15: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

The interview sequence is complete. The wizard has produced a running project directory, a configured system, and the Phase-1 build-and-operate prompt. The user's next action is to paste that prompt into a new Claude Code session.

---

## Foundation-only adapted path

**Disposition: ADAPT. Emit foundation docs via the dispatcher; foundation-only close ceremony.**

In foundation-only mode, step 15 close does NOT execute the full normal close path (no git init, no first build prompt, no implementation files). The foundation-doc emission STILL goes through the unified generator. The bridge dispatches to the foundation-only branch from the `--foundation-only` flag you pass on the emit command (it sets `FOUNDATION_ONLY_MODE = true`; no separate hand-assembly), and the foundation-only-specific ceremony docs are written post-emission.

### CLOSE-EMIT (foundation-only)

Run the same emit command as the normal path, plus the `--foundation-only` flag (this is what tells the generator to take the foundation-only branch; you determined `produce_system_implementation == false` at the entry guard above):

```bash
python3 wizard/scripts/interview_cli.py emit-system \
  --transcript ~/claude-wizard-draft/wizard_transcript.jsonl \
  --shape markdown-CC \
  --target-dir ~/[PROJECT_FOLDER_NAME] \
  --build-repo-root <the wizard directory root> \
  --project-name [PROJECT_NAME] \
  --foundation-only
```

Because you pass `--foundation-only` (it sets `FOUNDATION_ONLY_MODE = true` at the emission boundary), the bridge dispatches to the generator's foundation-only branch: it emits the foundation doc set (`vision.md`, `approach.md`, `technical_architecture.md`, `execution_plan.md`) and the operator manifest, and SKIPS the agent layer, permission-tier files, and per-agent task checklists (`agents == []`). If the command raises, STOP and surface the error.

### Post-emission foundation-only ceremony (write by hand, these are not generator artifacts)

After the foundation docs are emitted, write the foundation-only-specific ceremony docs to the project directory (the generator does not produce these):

| File | Source | Voice / content |
|---|---|---|
| `project_instructions.md` | Foundation-only voice template | ASSEMBLE per `_foundation_only_mode_gate.md` § 4; opening section MUST surface verbatim: "These foundation docs describe your project at the system-blueprint level. They are implementation-agnostic. Implementation NOT included in this output." |
| `manual.md` | Pointer doc | MUST surface a pointer to `next_steps.md`; no claim of "operating manual" semantics implying a running system |
| `next_steps.md` | NEW | Per the "next_steps.md content (template)" below |

Confirm `technical_architecture.md` carries the captured operational requirements per `_foundation_only_mode_gate.md` § 5 + § 6 (the captured `## Foundation-only-mode captures > *` sections were recorded into the transcript and emitted into `technical_architecture.md`; verify, do not re-assemble).

### next_steps.md content (template)

Write `[PROJECT_DIR]/next_steps.md` with the structure below. Substitute `[SHAPE]` with the detected shape from `shape_hypothesis.shape` and `[PROJECT_DIR]` with the operator's actual project directory.

```markdown
# Next steps: Foundation-only mode

## What was produced

This wizard run produced foundation documents describing your project at the system-blueprint level. They are implementation-agnostic.

Documents written to this directory:

- `vision.md`: project vision
- `approach.md`: project approach / methodology
- `technical_architecture.md`: shape-agnostic technical architecture (including operational requirements + any regulatory/compliance gaps identified at pre-step-05 re-check)
- `execution_plan.md`: foundation-level execution sequencing
- `project_instructions.md`: foundation-doc voice; describes what these docs are and are not
- `manual.md`: pointer to this file (`next_steps.md`)
- `next_steps.md`: this file

## What was NOT produced (and why)

Foundation-only mode does NOT generate system implementation. The wizard makes this distinction explicit because your project's system shape ([SHAPE]) is not yet supported by v1 of the wizard for full system generation.

NOT produced:

- Agent prompt files, scripts, or runtime configuration
- `.env`, `.gitignore`, `start-session.sh`, `session_bootstrap.md`
- Directory structure for agents, quality, work, logs, security
- Git repository initialization or GitHub remote setup
- First-build prompt for executing in Claude Code

## Two paths forward

**(a) Direct Claude Code build.** Take these foundation docs to Claude Code directly. Open Claude Code in this project directory and ask it to read the foundation docs and help you build the implementation in your chosen shape ([SHAPE]). The foundation docs are designed to be sufficient for an experienced operator (or Claude Code) to build from.

**(b) Wait for a future wizard release.** The wizard's roadmap for adding [SHAPE] support is on the build side; it is not bundled in the public wizard distribution today. Your staging file at `~/claude-wizard-draft/wizard_session_draft.md` is preserved on disk. **Concrete resume-to-full-build tooling is NOT implemented in this wizard version.** Only the data is preserved. A future wizard version may implement automated resume; when that version ships, the preserved staging file should be readable by it. Until then, path (a) direct Claude Code build is the available path; path (b) is "wait and re-evaluate when a future release ships."

## Honest characterization

> Foundation-only mode. Implementation deferred. Take these docs to Claude Code directly OR wait for v2 wizard shape support.

This output reflects the wizard's intentional implementation-agnostic stance. The foundation docs are designed to outlive any single implementation shape; what you build from them is your choice.
```

### Steps SKIPPED in foundation-only mode

- CLOSE-4 (git init): SKIP. Foundation docs are portable; operator decides repo strategy.
- GH-1 (GitHub remote): SKIP. Same reason.
- CLOSE-14 (first build prompt): SKIP. No markdown-agents to build; path forward lives in `next_steps.md`.
- The agent layer + implementation files, agent prompts, scripts, `.env`, `.gitignore`, `start-session.sh`, `session_bootstrap.md`, `/agents/`, the operational dirs: the foundation-only dispatch already skips emitting these (`agents == []`); do not write them by hand either.

### CLOSE-13 (closing message) adaptation

Tell operator (verbatim):

> Foundation-only mode complete. I've written 7 foundation documents to your project directory at `[PROJECT_DIR]/`. The key file to read next is `next_steps.md`. It walks you through what was produced, what was NOT produced (and why), and your two paths forward (direct Claude Code build OR wait for v2 wizard shape support).
>
> **Foundation-only mode. Implementation deferred. Take these docs to Claude Code directly OR wait for v2 wizard shape support.**
>
> Your project file at `~/claude-wizard-draft/wizard_session_draft.md` is preserved. We are NOT implementing resume tooling in this version of the wizard. Concrete resume-to-full-build support is deferred. What this means: your staging-file inputs are preserved on disk for a future implementation, but you cannot today re-run this wizard and have it pick up automatically. The available path today is direct Claude Code build using the foundation docs.

### Step 15 close write progression (foundation-only)

1. Run `emit-system` (above, with `--foundation-only`): the bridge dispatches to the foundation-only branch from that flag; the foundation docs + operator manifest are emitted, the agent layer skipped.
2. Write `project_instructions.md` in foundation-only voice per `_foundation_only_mode_gate.md` § 4 (post-emission)
3. Write `manual.md` as a pointer doc (post-emission)
4. Write `next_steps.md` per the content template above (post-emission)
5. Verify `vision.md` + `approach.md` + `technical_architecture.md` + `execution_plan.md` are present (emitted)
6. Update staging file: `WIZARD_COMPLETE = true`
7. Append step-marker to `~/claude-wizard-draft/wizard_progress.md`:
 ```
 step_15: complete | <timestamp>
 ```
8. Deliver CLOSE-13 closing message

The wizard exits cleanly after the closing message. NO first-build-prompt; NO git init; NO GitHub remote.
