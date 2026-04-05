# 15 — Closing Sequence

## What this file does
Complete the wizard interview. Assemble all project files from templates and staging data (CLOSE-ASSEMBLY), including the system guide written to disk. Initialize git and make the initial commit (CLOSE-4). Set up the GitHub remote backup (GH-1). Deliver a tight, action-oriented closing (CLOSE-13) with the first build prompt front and center (CLOSE-14), and point the user to the system guide and manual for reference. This is the final interview file.

## When this file runs
After `14_document_review.md` completes. All configuration is confirmed. All documents are written to disk.

## Prerequisites
OPERATIONS_CONFIGURED = true in the staging file. All wizard-produced documents exist on disk in the project directory.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 15_close.md. All configuration is complete. All documents are on disk. Read the staging file and the project directory, then continue from where you left off."

Do not begin CLOSE-ASSEMBLY until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_15_*` (e.g., `step_15_CLOSE-ASSEMBLY: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_15: complete`) is not, proceed directly to the success condition.

---

## Step opening — progress and preview

**Say:**

> **Step 16 of 16 — Wrapping up**
> We'll assemble your project, set up your backup, and hand you the keys to start building.

---

## How to run this phase

The closing sequence has four parts:

1. **Project assembly** (CLOSE-ASSEMBLY, internal) — read the staging file and all templates, write every output file to the project directory, including the system guide.
2. **Initial commit** (CLOSE-4, internal) — initialize git and commit the completed wizard setup.
3. **GitHub remote setup** (GH-1) — optional backup to a private GitHub repository.
4. **Closing and handoff** (CLOSE-13, CLOSE-14) — tight action-oriented closing with the first build prompt front and center.

Work through these in order without skipping.

---

## Part 1 — Project assembly (CLOSE-ASSEMBLY) [INTERNAL]

This step is internal. The user does not need to see the assembly process — they see one plain-language progress message. This is where every wizard-gathered value becomes a real file on disk.

**Say:**

> I'm now setting up your project files. This takes a moment.

### What this step does

Read the staging file (`session_bootstrap.md` in the project directory). Read every template in `wizard/templates/`. For each template, substitute the gathered values from the staging file and write the output file to the correct location in the project directory. Create all required directories first, then write files.

### Directory creation

Create the following directories in the project directory if they do not already exist:

```
agents/
agents/prompts/
agents/scripts/
agents/cron/
agents/handoffs/
agents/failed_queue/
agents/checkpoints/
quality/
work/
logs/
docs/
security/
archive/
archive/advisor-guides/
archive/logs/
digests/
wizard/
wizard/build_prompts/
wizard/review_prompts/
wizard/skills/
advisor/
advisor/interview-guides/
```

**Conditional directory:** Create `security/session_cookies/` only if the staging file indicates any username/password credentials were configured (path 09b — `SESSION_COOKIES_NEEDED = true`).

### File assembly — complete manifest

For each file below: read the template, substitute values from the staging file, and write to the target path. If a template field has no value in the staging file (e.g., the user skipped an optional section), write the template default or leave the placeholder with a note that it will be populated at runtime.

**Root-level files:**

| Template | Target | Value source |
|----------|--------|-------------|
| `wizard/templates/root/CLAUDE.md` | `CLAUDE.md` | P1-1, P1-2, autonomy level (Level 2) |
| `wizard/templates/root/project_instructions.md` | `project_instructions.md` | UP-1–5, FIN-1–2, NOTIF-1–5, ERR-1–2, QA-1–4, CONC-1–2, START-1–2, DRIFT-1, SCALE-1–4, CRED-1–5, GATE-1–2, model tier mapping |
| `wizard/templates/root/session_bootstrap.md` | `session_bootstrap.md` | All phases — initial state populated, queues at zero |
| `wizard/templates/root/pending_decisions.md` | `pending_decisions.md` | Empty structure |
| `wizard/templates/root/manual.md` | `manual.md` | Static content — copy as-is |
| `wizard/templates/root/gitignore_template` | `.gitignore` | Static baseline + CRED-2 entries |

**`SESSION_STATE.md`** — not from a template. Create this file directly in the project root with the following content:

```
# Session State

CLEAR
```

This file is required by Addition 7 (session close enforcement). The orchestrator updates it at every session close with current task state. Initial state is "CLEAR" — no task in progress. The health check (Check 2) verifies this file exists.

**`.env`** — not from a template. Create an empty `.env` file. If credentials were configured during step 09, write the environment variable names as comments (no values — values were entered during CRED-2 and should already be in the file if the credential onboarding step wrote them). Verify `.gitignore` includes `.env` before this file is created.

**`start-session.sh`** — copied from `wizard/scripts/start-session.sh`. Ensure it is executable (`chmod +x`).

**Foundation documents:**

| Template | Target | Value source |
|----------|--------|-------------|
| `wizard/templates/documents/vision.md` | `vision.md` | V-1 through V-8 — already written to disk during step 05; verify it exists, do not overwrite |
| `wizard/templates/documents/approach.md` | `approach.md` | Already written to disk during step 06; verify it exists, do not overwrite |
| `wizard/templates/documents/technical_architecture.md` | `technical_architecture.md` | ARCH-1–5, SCALE-4, CRED registry, model tier mapping |
| `wizard/templates/documents/execution_plan.md` | `execution_plan.md` | Vision goals, ARCH orchestration model, agent roster, build phases |
| `wizard/templates/documents/test_cases.md` | `test_cases.md` | Accumulator 6 entries; agent-specific tests added during build |
| `wizard/templates/documents/audit_framework.md` | `audit_framework.md` | DRIFT-1 cadence, architectural review settings |

**Note on vision.md and approach.md:** These documents are written to disk during their respective interview steps (05 and 06). Do not regenerate them from templates — verify they exist on disk and are intact. If either is missing (should not happen), regenerate from staging file answers using the template.

**Agent files:**

| Template | Target | Value source |
|----------|--------|-------------|
| `wizard/templates/agents/roster.md` | `agents/roster.md` | ARCH-2, ARCH-3 — agent names, roles, criticality tiers |
| `wizard/templates/agents/cron_config.md` | `agents/cron/cron_config.md` | Empty structure — entries added during agent build phase |

**Per-agent prompt and script files** are not generated at assembly time. They are produced during the agent build phase (after the wizard completes). The assembly step only creates the directory structure they will live in.

**Quality files:**

| Template | Target | Value source |
|----------|--------|-------------|
| `wizard/templates/quality/rules_library.md` | `quality/rules_library.md` | Empty structure |
| `wizard/templates/quality/human_review_queue.md` | `quality/human_review_queue.md` | Empty structure |
| `wizard/templates/quality/source_registry.md` | `quality/source_registry.md` | QA-3 confirmed sources |
| `wizard/templates/quality/validation_gate_config.md` | `quality/validation_gate_config.md` | GATE-1, GATE-2 answers |
| `wizard/templates/quality/co-protected-workflows.md` | `quality/co-protected-workflows.md` | Pre-populated from Tier 1 categories |
| `wizard/templates/quality/advisor_knowledge_base.md` | `quality/advisor_knowledge_base.md` | ADV-1 confirmed advisors (header entries) |

**Conditional — zero-advisors branch:** If the staging file shows zero confirmed advisors (`ADVISOR_COUNT = 0`), still create `quality/advisor_knowledge_base.md` with the empty structure from the template (advisors can be added later). Do not populate advisor header entries.

**Work files:**

| Template | Target | Value source |
|----------|--------|-------------|
| `wizard/templates/work/work_queue.md` | `work/work_queue.md` | Empty structure |
| `wizard/templates/work/issues_log.md` | `work/issues_log.md` | Empty structure |
| `wizard/templates/work/stub_tracker.md` | `work/stub_tracker.md` | Any stubs identified during interview (credentials pending, sources TBD) |
| `wizard/templates/work/execution_plan_state.md` | `work/execution_plan_state.md` | Empty structure |

**Log files:**

| Template | Target | Value source |
|----------|--------|-------------|
| `wizard/templates/logs/audit_log.md` | `logs/audit_log.md` | Header and structure |
| `wizard/templates/logs/session_log.md` | `logs/session_log.md` | Header and structure |
| `wizard/templates/logs/error_log.md` | `logs/error_log.md` | Header and structure |
| `wizard/templates/logs/qa_log.md` | `logs/qa_log.md` | Header and structure |
| `wizard/templates/logs/source_health_log.md` | `logs/source_health_log.md` | Header and structure |
| `wizard/templates/logs/drift_log.md` | `logs/drift_log.md` | Header and structure |
| `wizard/templates/logs/advisor_log.md` | `logs/advisor_log.md` | Header and structure |
| `wizard/templates/logs/notification_log.md` | `logs/notification_log.md` | Header and structure |
| `wizard/templates/logs/validation_log.md` | `logs/validation_log.md` | Header and structure |
| `wizard/templates/logs/cost_efficiency_log.md` | `logs/cost_efficiency_log.md` | Header and structure |

**Docs files:**

| Template | Target | Value source |
|----------|--------|-------------|
| `wizard/templates/docs/document_impact_map.md` | `docs/document_impact_map.md` | Standard change event taxonomy + project-specific categories from agent roster |
| `wizard/templates/docs/architectural_review_staging.md` | `docs/architectural_review_staging.md` | Empty structure |
| `wizard/templates/docs/future_items.md` | `docs/future_items.md` | Monitoring cadence from wizard answers; deferred items from staging file (see WI-013 below) |
| `wizard/templates/docs/voice_and_style.md` | `docs/voice_and_style.md` | Seeded from UP-1–5, ERR-1, QA-1, vision document voice (see below) |
| `wizard/templates/docs/how_your_system_works.md` | `docs/how_your_system_works.md` | Static content — copy as-is |

**Security files:**

| Template | Target | Value source |
|----------|--------|-------------|
| `wizard/templates/security/credentials_registry.md` | `security/credentials_registry.md` | CRED-1, CRED-2 confirmed credentials |
| `wizard/templates/security/gitignore_manifest.md` | `security/gitignore_manifest.md` | Baseline .gitignore entries |

**Conditional — zero-credentials branch:** If the staging file shows zero confirmed credentials (`CREDENTIAL_COUNT = 0`), still create `security/credentials_registry.md` with the empty structure (credentials can be added later). Skip credential reference rows in `project_instructions.md`.

**Archive files:**

| Template | Target | Value source |
|----------|--------|-------------|
| `wizard/templates/archive/decisions_archive.md` | `archive/decisions_archive.md` | Empty structure |
| `wizard/templates/archive/work_archive.md` | `archive/work_archive.md` | Empty structure |
| `wizard/templates/archive/review_queue_archive.md` | `archive/review_queue_archive.md` | Empty structure |
| `wizard/templates/archive/notification_archive.md` | `archive/notification_archive.md` | Empty structure |

**Review prompts:** Copy the three review prompt files from `wizard/review_prompts/` to the project's `wizard/review_prompts/` directory:
- `post_wizard_review.md`
- `per_agent_review.md`
- `phase_gate_review.md`

**Skill templates:** Copy the three skill template files from `wizard/skills/` to the project's `wizard/skills/` directory (create the directory first):
- `_index.md`
- `skill_template_external.md`
- `skill_template_internal.md`

These templates are referenced by the system CLAUDE.md and used during agent build sessions to create skills. The `_index.md` file serves as the skill registry; the two template files define the structure for external-facing and internal skills respectively.

### Name consistency — all personal names from staging data

**This rule applies to every file written during assembly.** All personal names — the user's name, family member names, team member names, advisor names, any name that appears in any output file — must be read from the confirmed values in the staging file. Never generate or infer a name independently for any individual file. If a name appears in the vision document answers, the user profile, the advisor list, or any other staging data section, use that exact spelling everywhere.

Before writing each file: read the relevant name values from the staging file. After writing each file: verify that every personal name in the file matches the staging data exactly. If a template contains a placeholder like `{{USER_NAME}}` or `{{FAMILY_MEMBER_1}}`, the substituted value must come from one source — the staging file — never from the model's own generation.

This prevents the systematic name inconsistency where foundation documents get correct names but derived/operational documents get hallucinated alternatives (e.g., "Matt" instead of "Mark", "Sarah" instead of "Lauren").

### WI-011 — Constraint elevation to project_instructions.md

During assembly, before writing `project_instructions.md`, scan the vision document answers in the staging file for critical constraints. Look for:

- **Privacy constraints** — statements like "nothing leaves my computer," "no external sharing," "data stays local"
- **Data locality constraints** — restrictions on where data can be stored or processed
- **External communication prohibitions** — rules about what the system must never send, post, or share externally
- **Absolute prohibitions** — "never" statements about actions the system must not take

For each critical constraint found, write it as an enforced rule in `project_instructions.md` under the "What the system always asks first — User additions to Tier 1" section. Format each as a plain-language rule:

> - [Constraint from vision document] — elevated from vision document, enforced as Tier 1

This ensures that constraints the user stated during the vision interview become system-level enforcement rules, not just documentation.

### WI-013 — Populate future_items.md with deferred items

During assembly, before writing `docs/future_items.md`, scan the staging file for deferred items. These are requests the user made during the interview that the wizard noted for later rather than acting on immediately. Common patterns:

- "We'll revisit that after the first agents are running"
- Items flagged as `DEFERRED` or `FUTURE` in the staging file
- Agent capabilities the user requested that were scoped out of the initial build
- Features or integrations noted as "not yet" or "later"

For each deferred item found:
- If it has a natural trigger date (e.g., "after the first month"): write it as a **date-triggered item**
- If it has a natural condition (e.g., "when the first agent is running"): write it as a **condition-triggered item**
- If it is an ongoing concern: add it to the **monitoring cadence register**

This ensures that nothing the user asked for is silently dropped — every deferred request has a structured home that the system will check at every session close.

### Voice and style seeding

When writing `docs/voice_and_style.md`, derive initial values from existing wizard answers — do not ask new questions:

- **Explanation depth:** derived from UP-1 (technical literacy) — higher literacy → more concise; lower literacy → more explanatory
- **Tone:** derived from UP-2 (information preference) — "just the bottom line" → direct; "understand the reasoning" → conversational
- **Technical level:** derived from UP-1 — maps directly
- **Notification verbosity:** use ERR-1 answer (Minimal/Standard/Detailed)
- **QA reporting style:** use QA-1 answer (funneled/direct)
- **Vision document voice:** read the user's own words from the vision document answers in the staging file — note their natural writing style (formal vs. casual, brief vs. detailed, direct vs. explanatory) and use it as the basis for approved examples

### Assembly verification

After all files are written, run a quick verification:

1. **Count check:** verify the number of files created matches the expected count from the manifest above (adjust for conditional branches).
2. **Critical file check:** verify these files exist and are non-empty: `CLAUDE.md`, `project_instructions.md`, `session_bootstrap.md`, `SESSION_STATE.md`, `vision.md`, `approach.md`, `technical_architecture.md`, `.gitignore`, `.env`, `docs/how_your_system_works.md`.
3. **Conditional check:** if `SESSION_COOKIES_NEEDED = true`, verify `security/session_cookies/` directory exists. If `CREDENTIAL_COUNT = 0`, verify `security/credentials_registry.md` exists but has no credential rows.
4. **Model flag check:** verify `start-session.sh` contains `--model` with a resolved model name (not a placeholder). Verify the model name matches the High tier value in `project_instructions.md`.

If any verification fails: stop, identify what is missing, and fix it before proceeding to CLOSE-4.

**Say:**

> Your project files are set up. Everything from the interview has been written to your project directory. Let me save a snapshot.

Proceed to Part 2 (CLOSE-4).

Write sub-step marker: Append `step_15_CLOSE-ASSEMBLY: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Part 2 — Initial commit (CLOSE-4) [INTERNAL]

This step is internal. Do not narrate it to the user in technical terms. One plain-language confirmation line is sufficient.

**Before committing:**

1. Verify that `.gitignore` is in place and excludes `.env`. Do not proceed if `.gitignore` is absent — generate it now if missing (see `09_credentials.md`).
2. Create `wizard_feedback.md` in the project root from `wizard/templates/root/wizard_feedback.md`. This file is the bridge from system runtime back to wizard improvement — it stays in the user's project for agents to write to when they encounter wizard-related issues.

Run the following commands in the project directory:

```bash
git init -b main
git add .
git commit -m "Wizard setup complete — [PROJECT_NAME] initial commit"
```

**Say:**

> I've saved a snapshot of everything we've set up. Your project is now under version control — every change from here will be tracked.

Write sub-step marker: Append `step_15_CLOSE-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Part 3 — GitHub remote setup (GH-1) [FIXED — topic]

GH-1 is optional but strongly recommended. It protects the user's work against hardware failure. A private GitHub repository is the default recommendation.

**Say:**

> Your project is saved locally on your computer. Would you like to also back it up to GitHub? This protects your work if something ever happens to your computer. It takes about five minutes and the repository will be private — only you can see it.

**Wait for answer.**

---

**If the user says no:**

> That's fine — your work is saved locally and every change is tracked in version control. You can connect to GitHub any time in the future by telling me "set up GitHub backup" at the start of a session.

Record in staging file: `GITHUB_REMOTE = false`. Proceed to Part 4.

---

**If the user says yes:** Work through the following steps in order.

**Step 1 — Check for GitHub CLI:**

Run: `gh --version`

- If installed: proceed to Step 2.
- If not installed: **Say:** *"We need one more tool to connect to GitHub. Run this command:"*
  ```
  brew install gh
  ```
  Wait for confirmation that it completed. Re-run `gh --version` to verify. Then proceed to Step 2.

**Step 2 — Check authentication:**

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

**Step 3 — Check for a GitHub account:**

If the user authenticated in Step 2, they have an account. If they indicated they don't have one, direct them to `github.com` to create a free account before continuing.

**Step 4 — Create the repository and connect:**

**Say:** *"Creating your private repository now."*

Run:
```bash
gh repo create [PROJECT_FOLDER_NAME] --private --source=. --remote=origin --push
```

This creates the private repository, connects it as `origin`, and pushes the initial commit in a single command.

**Step 5 — Confirm:**

Run: `git remote -v`

Show the user their repository URL.

**Say:**

> Your project is now backed up to GitHub at [URL]. Every time your system saves a checkpoint, it will push to GitHub automatically — so your backup stays current.

Record in staging file: `GITHUB_REMOTE = true` and `GITHUB_REMOTE_URL = [URL]`.

Write `GITHUB_REMOTE_URL` to `project_instructions.md` under the system configuration section.

Write sub-step marker: Append `step_15_GH-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Part 4 — Closing and handoff (CLOSE-13, CLOSE-14)

### CLOSE-13 — Layered closing [EXPLANATION]

**This step is mandatory. It cannot be skipped or abbreviated.**

The closing has three layers. Deliver them in order. The first layer is what matters most — the user's immediate next action. Keep it tight.

---

**Layer 1 — Immediate: what to do next**

**Say:**

> **Your wizard setup is complete.**
>
> Your project is at:
> `~/[PROJECT_FOLDER_NAME]/`
>
> **Here is the prompt to start your first agent build.** It's also saved at `wizard/build_prompts/agent_01_build_prompt.md` — so if you close this window, you won't lose it.

Then deliver CLOSE-14 immediately (the build prompt).

---

### CLOSE-14 — First build prompt [INTERNAL]

**Before producing the prompt:** Read the confirmed agent roster from `technical_architecture.md`. Identify the first agent to build — this should be the agent at the foundation of the system (typically the orchestrator or the primary data-access agent, whichever the roster designates as the starting point).

**Produce the following prompt** (exact wording — this becomes the paste-ready content):

---

> **First agent build — [AGENT NAME]**
>
> Read these files in the project directory before doing anything:
> - `vision.md`
> - `approach.md`
> - `technical_architecture.md`
> - `project_instructions.md`
> - `session_bootstrap.md`
>
> You are building the **[AGENT NAME]** agent. This agent's role is: [one sentence from the roster].
>
> Using the documents above as your specification:
>
> 1. Confirm your understanding of this agent's role, permissions, and completion criteria before writing anything.
> 2. Build the agent file at `/agents/[agent_filename].md` — including role definition, operating instructions, permission boundary, and task completion checklist.
> 3. Verify the agent file is complete and internally consistent with the technical architecture.
> 4. Confirm completion and tell me what to review before the next agent is built.
>
> **To start this session:** Run `./start-session.sh` from your project directory — it is already configured to use the correct model. Do not build any other agents in this session — one agent at a time.

---

**Write this prompt to disk:** `[PROJECT_DIR]/wizard/build_prompts/agent_01_build_prompt.md`

---

**After the build prompt, continue with Layer 2.**

---

**Layer 2 — Reference: the build arc and where to look**

**Say:**

> **Here's the road ahead:** Your agent roster has **[n] agents** planned. We build them one at a time — each agent is its own session, and you'll review each one before the next begins. Once all [n] are built and tested, the system moves into regular operation and you'll start receiving your digests.
>
> **Three things to know:**
>
> - All your build prompts are saved at `wizard/build_prompts/` — if you ever close a session before copying a prompt, you'll find it there.
> - Your project's `manual.md` covers setup basics and troubleshooting if you need them later.
> - `docs/how_your_system_works.md` explains everything your system does automatically — how it handles errors, updates, security, and more. Read it whenever you're curious.
>
> You're ready to go. Paste the prompt above into a new session to start building your first agent.

---

**Layer 3 — Deep dive: on disk, not verbal**

There is no Layer 3 delivery. The system guide (`docs/how_your_system_works.md`) is already on disk from the assembly step. The user reads it at their own pace. The wizard does not deliver behavior briefings verbally — they are written to disk where they can be referenced any time, rather than delivered in a moment when the user has just finished a long interview and is ready to act.

---

Write an audit trail entry: `Wizard setup complete. First build prompt written for [AGENT NAME]. System guide written to docs/how_your_system_works.md. Closing sequence delivered.`

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

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

CLOSE-ASSEMBLY project assembly complete — all files written to disk, verification passed, system guide written to `docs/how_your_system_works.md`. CLOSE-4 git initialized and initial commit made. GH-1 complete (remote connected or user opted out, preference recorded). CLOSE-13 layered closing delivered — build prompt front and center, reference pointers provided, briefings on disk. First build prompt written to `/wizard/build_prompts/agent_01_build_prompt.md` and handed off to user. Audit trail entry written.

Update staging file: `WIZARD_COMPLETE = true`

**Write completion marker:** Append `step_15: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

The interview sequence is complete. The wizard has produced a running project directory, a configured system, and the user's first build prompt. The user's next action is to paste the first build prompt into Claude Code.
