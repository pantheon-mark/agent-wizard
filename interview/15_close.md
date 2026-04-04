# 15 — Closing Sequence

## What this file does
Complete the wizard interview. Deliver plain-language explanations of system behaviors (CLOSE-1 through CLOSE-12), make the initial git commit (CLOSE-4), set up the GitHub remote backup (GH-1), present the mandatory closing orientation moment (CLOSE-13), and hand off the first agent build prompt (CLOSE-14). This is the final interview file.

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
> "Resume wizard from 15_close.md. All configuration is complete. All documents are on disk. Read the staging file and the project directory, then begin the closing sequence."

Do not begin CLOSE-1 until you are confident the full phase will complete before compaction risk. **This is the longest file in the sequence — assess carefully.** If context is at all uncertain, clear and resume in clean context rather than risk compaction mid-orientation.

---

## How to run this phase

The closing sequence has five parts:

1. **Behavior briefings** (CLOSE-1, CLOSE-2, CLOSE-3) — brief the user on what the system does when things go wrong.
2. **Initial commit** (CLOSE-4, internal) — commit the completed wizard setup to git.
3. **GitHub remote setup** (GH-1) — optional backup to a private GitHub repository.
4. **How the system keeps itself current** (CLOSE-5 through CLOSE-12) — eight brief explanations delivered as a single block.
5. **Orientation and handoff** (CLOSE-13, CLOSE-14) — the mandatory orientation moment and the first build prompt.

Work through these in order without skipping.

---

## Part 1 — Behavior briefings

**Say:**

> Before we finish the setup, I want to walk you through a few things your system will do on its own — so nothing surprises you when it starts running.

Then deliver CLOSE-1, CLOSE-2, and CLOSE-3 in sequence as a flowing briefing. Do not pause for responses between them unless the user interrupts.

---

### CLOSE-1 — Auto-correct behavior [EXPLANATION]

> **When the system finds a problem**, it will fix it if it safely can, ask for your approval if the fix touches something important, or ask you one specific question if it needs your judgment. It will never just tell you something is broken and leave you to figure out what to do.

---

### CLOSE-2 — Log management [EXPLANATION]

> **Your system keeps detailed logs** of everything it does. It will automatically manage those files — keeping them from getting too large and cleaning up old ones periodically. It will always ask you before permanently deleting anything. You'll see a note in your digest when any of this happens.

---

### CLOSE-3 — Rollback [EXPLANATION]

> **If something goes wrong and a previous state needs to be restored**, the system will identify what needs to change and walk you through it. For anything significant, it will always ask for approval before making changes.

---

After CLOSE-3, pause briefly.

**Say:**

> Any questions on any of that before we move on?

- If the user has questions: answer in plain language, drawing on examples specific to their system.
- If they're ready to continue: proceed to CLOSE-4.

---

## Part 2 — Initial commit (CLOSE-4) [INTERNAL]

This step is internal. Do not narrate it to the user in technical terms. One plain-language confirmation line is sufficient.

**Before committing:**

1. Verify that `.gitignore` is in place and excludes `.env`. Do not proceed if `.gitignore` is absent — generate it now if missing (see `09_credentials.md`).
2. Create `wizard_feedback.md` in the project root from `wizard/templates/root/wizard_feedback.md`. This file is the bridge from system runtime back to wizard improvement — it stays in the user's project for agents to write to when they encounter wizard-related issues.

Run the following commands in the project directory:

```bash
git add .
git commit -m "Wizard setup complete — [PROJECT_NAME] initial commit"
```

**Say:**

> I've saved a snapshot of everything we've set up. Your project is now under version control — every change from here will be tracked.

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

---

## Part 4 — How the system keeps itself current (CLOSE-5 through CLOSE-12)

Deliver these eight explanations as a single flowing briefing. Present them together, not as eight separate statements. Group them naturally:

**Say:**

> A few more things your system handles on its own:

---

### CLOSE-5 — Session management [EXPLANATION]

> **If you ever need to start a new session**, the system will tell you exactly what to do — it keeps everything needed to pick up right where you left off.

---

### CLOSE-6 — Model tier management [EXPLANATION]

> **The AI models your agents use** are kept current automatically — you don't need to manage this.

---

### CLOSE-7 — Dependency updates [EXPLANATION]

> **The tools your system depends on** are kept up to date automatically. If anything needs your attention, you'll hear about it in your digest.

---

### CLOSE-8 — Document updates [EXPLANATION]

> **Every time the system updates your documents**, your digest will explain what happened, why it changed, and what's different — so you always know what your documents say and why.

---

### CLOSE-9 — QA behavior [EXPLANATION]

> **Your QA agent automatically checks** the work your other agents produce. If it flags something, it will tell you in plain language what it found and wait for your decision before anything moves forward.

---

### CLOSE-10 — Security audit [EXPLANATION]

> **Your QA agent also checks** whether integrations and connections your agents build are set up safely — that they only access what they need to, and that they handle any personal information carefully.

---

### CLOSE-11 — PII and log protection [EXPLANATION]

> **Your agents keep detailed logs** of everything they do — but they're instructed never to write personal information into those logs. If they're working with customer records, they log something like "processed record [ID:4782]" — not the person's name or email.

---

### CLOSE-12 — Blast radius pre-flight [EXPLANATION]

> **Before your agents do anything**, they first declare exactly what they're planning to change. If the plan looks unusually broad for that agent, the system pauses and asks you to confirm before a single file is touched.

---

After the full block:

**Say:**

> Any questions on any of that?

- If the user has questions: answer in plain language.
- If they're ready: proceed to Part 5.

---

## Part 5 — Orientation moment and first build prompt

### CLOSE-13 — Orientation moment [EXPLANATION]

**This step is mandatory. It cannot be skipped or abbreviated.**

Present the five-part orientation in order. Do not rush it. For a user finishing a 30–60 minute interview, this is the bridge to the next phase — they need to understand where they are and what happens next.

---

**Part 1 — What we built in this session**

**Say:**

> Before we hand off the first build prompt, let me show you where things stand.
>
> **Here's what we built in this session:**

Then list every artifact produced in plain language, no jargon. Derive the list from the actual staging file and project directory. Standard set:

> - Your **vision document** — what this system is for and what it must never do
> - Your **approach document** — how the system will achieve those goals
> - Your **agent roster** — the [n] agents that will form your team, their roles, and how they're organized
> - Your **project configuration** — notification settings, quality thresholds, credential inventory, validation rules, and all operational preferences
> - Your **project directory** — set up and under version control[, backed up to GitHub] at this path:
>   `~/[PROJECT_FOLDER_NAME]/`

---

**Part 2 — What's in your project folder right now**

**Say:**

> **Here's what's on disk right now:**

List the actual files present in the project directory at this moment. Present them as a readable list without explaining every file — just name them simply. Example format:

> - `vision.md` — your vision document
> - `approach.md` — your approach document
> - `technical_architecture.md` — agent roster and system design
> - `project_instructions.md` — system configuration and settings
> - `session_bootstrap.md` — how every session starts
> - `.env` — your credentials (protected, never shared)
> - `.gitignore` — prevents credentials from being committed
> - `/quality/` — QA configuration and source registry
> - `/logs/` — system activity logs

Show the literal project path.

---

**Part 3 — Where to find your prompts**

**Say:**

> **Every prompt I produce for you is saved here:**
>
> `~/[PROJECT_FOLDER_NAME]/wizard/build_prompts/`
>
> If you ever close this window before copying a prompt, open that folder and you'll find it. Nothing is lost if a session ends unexpectedly.

---

**Part 4 — How the build process works from here**

**Say:**

> **Here's the full arc of what happens next:**
>
> From here, we build your agent team one agent at a time. Each agent is its own build session — I'll walk you through it step by step. After each agent is built, you'll review what it can do before we start the next one. Nothing runs automatically until you've confirmed it's ready.
>
> Once all your agents are built and tested, the system moves into regular operation and you'll start receiving your digests.
>
> That's the full journey — one agent at a time, each one reviewed, building toward a complete running team.

---

**Part 5 — Preview of the first build prompt**

**Say:**

> **Here is the prompt to start your first agent build.** Paste this into Claude Code to begin.
>
> *(The prompt is also saved to `wizard/build_prompts/agent_01_build_prompt.md` — open that file any time if you need it again.)*

Then deliver CLOSE-14 immediately below.

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
> Use the **High** tier model for this session. Do not build any other agents in this session — one agent at a time.

---

**Write this prompt to disk:** `[PROJECT_DIR]/wizard/build_prompts/agent_01_build_prompt.md`

Write an audit trail entry: `Wizard setup complete. First build prompt written for [AGENT NAME]. Closing sequence delivered.`

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

All 14 CLOSE entries delivered. CLOSE-4 initial commit made. GH-1 complete (remote connected or user opted out, preference recorded). CLOSE-13 orientation moment delivered in full — all five parts present. First build prompt written to `/wizard/build_prompts/agent_01_build_prompt.md` and handed off to user. Audit trail entry written.

Update staging file: `WIZARD_COMPLETE = true`

The interview sequence is complete. The wizard has produced a running project directory, a configured system, and the user's first build prompt. The user's next action is to paste the first build prompt into Claude Code.
