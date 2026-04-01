# Setup Guide — Agent Team System

*This guide walks you through installing everything you need to run your agent team system on a Mac. No technical experience required — every step is written in plain language. If something goes wrong, the troubleshooting section at the end covers the most common issues.*

*This document is kept current by your system. If a setup step changes, the system will update this guide and note what changed in your next digest.*

---

## What you're installing

Your agent team runs through a tool called Claude Code. To use it, your Mac needs a few programs installed first. This guide walks you through installing them in the right order.

**You will install:**

1. **Homebrew** — a tool that installs other tools. Think of it as an app store for developer tools. You use it once to install the other items on this list.
2. **Git** — version control. Every change your agents make is tracked and reversible.
3. **Node.js** — a runtime that Claude Code depends on to operate.
4. **Claude Code** — the tool your agents run through.

**Time required:** About 20-30 minutes, most of which is waiting for downloads.

**What you'll need:** A Mac running macOS 12 or later, an internet connection, and a Claude Pro, Max, or Teams subscription.

---

## Before you start

Open the **Terminal** application on your Mac.

**To find Terminal:**
1. Press `Command + Space` to open Spotlight
2. Type "Terminal"
3. Press Enter

You'll see a window with a cursor waiting for input. This is where you'll type the commands in this guide.

**Important:** Type each command exactly as shown, or copy and paste it. Capitalization matters.

---

## About permission prompts

As your agent team runs, you will regularly see prompts like this in your Terminal window:

> **Allow Claude Code to edit files in your project?**
> **Allow Claude Code to run this command?**

These are safety features built into Claude Code. Before your agents do anything significant — edit a file, run a command, connect to a service — Claude Code stops and asks you to approve it first.

**What to do:**

- **Allow** (or **Yes**) — when the prompt describes something related to your project or its setup. Your agents will tell you what they're about to do before they do it.
- **Deny** (or **No**) — if a prompt asks for access to something outside your project directory, or asks to do something that wasn't described to you. If this happens, note what triggered the prompt and tell your agent team.

You'll see these prompts often when you're first setting up and building your agents. Once your system is running, they become less frequent. They are not errors — they are the system working as designed.

---

## Step 1 — Install Homebrew

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

## Step 2 — Install Git

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

## Step 3 — Install Node.js

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

## Step 4 — Install Claude Code

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

## Step 5 — Create your project folder

Your agent team lives in a folder in your home directory. Create it with this command (replace `my-project` with your project's folder name — use hyphens instead of spaces):

```
mkdir ~/my-project
```

Navigate into it:

```
cd ~/my-project
```

Your project will live here. All your agent files, documents, and logs will be in this folder.

---

## Step 6 — Start the wizard

The wizard guides you through the full setup — building your vision document, agent roster, and system configuration. You only run it once.

Make sure you're in your project folder, then run:

```
claude
```

Claude Code will open. When it does, paste the wizard launch prompt you received at purchase. The wizard will take it from there.

---

## Running your system after setup

After the wizard is complete, you'll start sessions using the startup script the wizard installs. From your project folder:

**Normal start:**
```
./start-session.sh
```

**Resume after a pause:**
```
./start-session.sh --resume
```

**Respond to an alert:**
```
./start-session.sh --resume --alert
```

---

## Keeping your tools current

Your agent team checks for updates automatically and will tell you if anything needs attention. If you ever need to update manually:

```
brew upgrade git node
npm install -g @anthropic-ai/claude-code
```

---

## Troubleshooting

### "Command not found: brew"

Homebrew wasn't added to your path. Close Terminal, open it again, and try `brew --version`. If it still fails, re-run the Homebrew install command from Step 1.

### "Permission denied" when running a command

You may need to add `sudo` before the command. For example: `sudo npm install -g @anthropic-ai/claude-code`. Your Mac will ask for your password.

### "node: command not found" after installing Node.js

Close Terminal, open it again, and try `node --version`. Opening a new Terminal window refreshes the path.

### Claude Code opens but asks me to log in

You need an active Claude Pro, Max, or Teams subscription. Log in at claude.ai first, then try `claude` again. If you're already logged in, run `claude logout` and then `claude login` to refresh your session.

### The wizard started but something went wrong mid-way

Your progress is saved. Open Terminal, navigate to your project folder, run `claude`, and paste the resume prompt your wizard provided. If you don't have it, look in your project folder at `~/claude-wizard-draft/wizard_session_draft.md` — your progress is there.

### I see an error I don't recognize

Copy the full error message and share it with your agent team at the start of your next session. Say: "I got this error when setting up — can you help me understand what happened?" They'll diagnose it from the message.

---

*This guide was generated during your wizard setup. Last updated: {{MANUAL_LAST_UPDATED}}*
