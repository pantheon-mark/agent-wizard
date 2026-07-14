# Operating Manual — {{PROJECT_NAME}}

*What you do, how the system works, and what to expect day to day.*

---

## Getting started

The wizard has finished. Your system is ready.

Start your first session from your project folder:

```
./start-session.sh
```

You build your system capability by capability. The session startup script orients the system and walks you through what comes next. You do not need to plan ahead — just run it.

---

## The build-and-operate loop

You build your system one capability at a time. Each capability follows the same loop:

1. **Build it.** A build session adds one piece of functionality to your system.
2. **Run it on your real work.** Use it with actual work, not test data.
3. **Confirm it does what you need.** Judge the output yourself. Did it do the right thing?
4. **Fix anything that's off.** If something is wrong, address it in the same session before moving on.
5. **Build the next capability.** Only move forward after you've confirmed the current one works.

You always have a working system. You never leave something half-done and move on.

This approach means your system earns your trust step by step, and problems get caught early when they're easy to fix.

---

## Your role

**What you do:**

- Run sessions when you want work done.
- Use each capability and judge whether it did your work right. You are the quality check — not because the system can't produce good output, but because only you know what "right" looks like for your work.
- Make decisions that only you can make. The system will stop and ask you before it spends money, sends anything outside your system, or does anything that can't be undone. You approve or decline.
- Tell the system when something is off. Clear feedback gets addressed directly.

**What the system does:**

- Handles the routine, repeatable work.
- Tells you what it did, what it found, and what needs your input.
- Stops when it's uncertain rather than guessing.
- Keeps a record of everything it has done.

You are in charge. The system does not act beyond what you've authorized.

---

## Operating rhythm

**Starting a session:**

Run this from your project folder:

```
./start-session.sh
```

The system reads its current state, checks for anything that needs your attention, and tells you what's ready. You do not need to remember where you left off — it does.

**Reading digests:**

Your system sends you a digest on the schedule you configured during setup. The digest covers what was done since the last session, anything that needs a decision, and any alerts. Read it before starting a session if one arrived.

**Responding to alerts:**

When the system encounters something that needs your input outside of a session, it sends an alert. To respond:

```
./start-session.sh --resume --alert
```

The system will tell you what triggered the alert and what it needs from you.

**Approving items:**

Some actions require your explicit approval before the system proceeds — anything involving money, anything leaving your system, anything irreversible. The system surfaces these as approval requests during sessions. Read each one, make your call, and the session continues.

**Resuming after a pause:**

If you close a session mid-way and want to pick up where you left off:

```
./start-session.sh --resume
```

---

## Appendix: First-time setup and troubleshooting

This section covers installing the tools your system requires. If you've already completed setup, you can ignore this. Come back here if you're setting up on a second machine or need to reinstall.

### What you're installing

Your agent team runs through a tool called Claude Code. To use it, your Mac needs a few programs installed first. This appendix walks you through installing them in the right order.

**You will install:**

1. **Homebrew** — a tool that installs other tools. Think of it as an app store for developer tools. You use it once to install the other items on this list.
2. **Git** — version control. Every change your agents make is tracked and reversible.
3. **Node.js** — a runtime that Claude Code depends on to operate.
4. **Python** — a current copy, used by the parts of your system (if any) that write information back into another service. Your Mac already has an old copy of Python built in for its own use; this installs a current one that your system points to directly, so it never depends on whatever `python3` happens to mean on your Mac.
5. **Claude Code** — the tool your agents run through.

**Time required:** About 20-30 minutes, most of which is waiting for downloads.

**What you'll need:** A Mac running macOS 12 or later, an internet connection, and a Claude Pro, Max, or Teams subscription.

---

### Before you start

Open the **Terminal** application on your Mac.

**To find Terminal:**
1. Press `Command + Space` to open Spotlight
2. Type "Terminal"
3. Press Enter

You'll see a window with a cursor waiting for input. This is where you'll type the commands in this appendix.

**Important:** Type each command exactly as shown, or copy and paste it. Capitalization matters.

---

### About permission prompts

As your agent team runs, you will regularly see prompts like this in your Terminal window:

> **Allow Claude Code to edit files in your project?**
> **Allow Claude Code to run this command?**

These are safety features built into Claude Code. Before your agents do anything significant — edit a file, run a command, connect to a service — Claude Code stops and asks you to approve it first.

**What to do:**

- **Allow** (or **Yes**) — when the prompt describes something related to your project or its setup. Your agents will tell you what they're about to do before they do it.
- **Deny** (or **No**) — if a prompt asks for access to something outside your project directory, or asks to do something that wasn't described to you. If this happens, note what triggered the prompt and tell your agent team.

You'll see these prompts often when you're first setting up and building your agents. Once your system is running, they become less frequent. They are not errors — they are the system working as designed.

---

### Step 1 — Install Homebrew

Homebrew is installed by running a single command in Terminal. Copy and paste the line below, then press Enter:

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

The installer will ask for your Mac password (the same one you use to log in). Type it and press Enter — you won't see any characters appear while you type. That's normal.

The installation takes a few minutes. You'll see a lot of output scroll by. When it finishes, you'll see your prompt (the `%` or `$` cursor) return.

**Verify it worked:** Type this and press Enter:

```
brew --version
```

You should see something like `Homebrew 4.x.x`. If you do, Homebrew is installed.

---

### Step 2 — Install Git

Git is often already installed on Macs. Run this to check:

```
git --version
```

If you see a version number, Git is already installed — skip to Step 3.

If you see an error, install Git with Homebrew:

```
brew install git
```

Wait for it to finish, then run `git --version` again to confirm.

---

### Step 3 — Install Node.js

Install Node.js with Homebrew:

```
brew install node
```

This takes a few minutes. When it finishes, verify:

```
node --version
```

You should see a version number starting with `v18` or higher.

---

### Step 4 — Install Python

Install a current Python with Homebrew:

```
brew install python@3.12
```

This takes a few minutes. When it finishes, verify:

```
$(brew --prefix python@3.12)/bin/python3.12 --version
```

You should see `Python 3.12.x`. If your system has a part that runs Python code (see `requirements.txt` in this project folder — if it's not there, this system has none), your session startup script (`start-session.sh`) uses this copy automatically the first time you run it, setting up a project-local copy your system always points to. You never need to run a Python command yourself.

---

### Step 5 — Install Claude Code

Install Claude Code with this command:

```
npm install -g @anthropic-ai/claude-code
```

When it finishes, verify:

```
claude --version
```

You should see a version number. Claude Code is now installed.

---

### Keeping your tools current

Your agent team checks for updates automatically and will tell you if anything needs attention. If you ever need to update manually:

```
brew upgrade git node python@3.12
npm install -g @anthropic-ai/claude-code
```

---

### Troubleshooting

#### "Command not found: brew"

Homebrew wasn't added to your path. Close Terminal, open it again, and try `brew --version`. If it still fails, re-run the Homebrew install command from Step 1.

#### "Permission denied" when running a command

You may need to add `sudo` before the command. For example: `sudo npm install -g @anthropic-ai/claude-code`. Your Mac will ask for your password.

#### "node: command not found" after installing Node.js

Close Terminal, open it again, and try `node --version`. Opening a new Terminal window refreshes the path.

#### Claude Code opens but asks me to log in

You need an active Claude Pro, Max, or Teams subscription. Log in at claude.ai first, then try `claude` again. If you're already logged in, run `claude logout` and then `claude login` to refresh your session.

#### The wizard started but something went wrong mid-way

Your progress is saved. Open Terminal, navigate to your project folder, run `claude`, and paste the resume prompt your wizard provided. If you don't have it, look in your project folder at `~/claude-wizard-draft/wizard_session_draft.md` — your progress is there.

#### I see an error I don't recognize

Copy the full error message and share it with your agent team at the start of your next session. Say: "I got this error when setting up — can you help me understand what happened?" They'll diagnose it from the message.

---

*Last updated: {{MANUAL_LAST_UPDATED}}*
