# Agent Team Wizard — Setup Manual

## What this is

This manual walks you through everything you need to do before the wizard starts. By the time you finish this guide, you will have all the required software installed and the wizard running on your Mac.

The wizard itself will take it from there. It will ask you questions, make recommendations, and set up your complete agent team — step by step, in plain language. You do not need any technical knowledge to complete it.

**What you will have when the wizard finishes:**
- A complete multi-agent Claude Code team, configured for your specific project
- Every agent defined, scripted, and ready to run
- All your project documents written to disk and backed up
- A session startup process so the system picks up exactly where it left off

---

## What you will need

Before you begin, make sure you have:

- **A Mac** — this setup is Mac only
- **A Claude account** at claude.ai — a paid plan (Pro or higher) is required; the free tier does not support the tools the wizard uses
- **An internet connection**
- **About 20 minutes** to complete this guide, plus **30–60 minutes** for the wizard interview itself

---

## Step 1 — Install Homebrew

Homebrew is a tool that manages software on your Mac. The other tools in this guide are installed through it.

Open Terminal. (Press Command + Space, type "Terminal", press Enter.)

Paste this command and press Enter:

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

The installer will walk you through the process. Follow any prompts it shows — you may be asked for your Mac password. This is normal and expected.

When it finishes, you will see a message that says something like "Installation successful."

**If you see a prompt about Xcode Command Line Tools:** Click Install. This is a Mac system component that Homebrew needs — it is safe and expected. It takes a few minutes.

---

## Step 2 — Install Git

Git tracks the history of your project. If something ever goes wrong, it lets you go back to an earlier version.

In Terminal, paste this command and press Enter:

```
brew install git
```

When it finishes, verify the installation:

```
git --version
```

You should see a version number like `git version 2.x.x`. That means it worked.

---

## A note about GitHub

You just installed Git, which tracks your project's history on your computer. **GitHub** is a separate online service that stores a copy of that history in the cloud — think of it as a backup that protects you if anything happens to your Mac.

The wizard will offer to set up GitHub backup for your project during the interview. You do not need a GitHub account right now, but if you would like to get one ahead of time, you can create a free account at github.com.

This is optional. Your project works perfectly fine without it — GitHub just adds an extra layer of protection.

---

## Step 3 — Install Node.js

Node.js allows your agent team to run scheduled tasks and operate in the background.

In Terminal, paste this command and press Enter:

```
brew install node
```

This takes a couple of minutes. When it finishes, verify:

```
node --version
```

You should see a version number starting with `v18` or higher. That means it worked.

---

## Step 4 — Install Claude Code

Claude Code is the tool the wizard runs inside. It is Anthropic's official command-line interface for Claude.

In Terminal, paste this command and press Enter:

```
npm install -g @anthropic-ai/claude-code
```

When it finishes, verify:

```
claude --version
```

You should see a version number. That means it worked.

---

## Step 5 — Log in to Claude Code

Claude Code needs to connect to your Claude account.

In Terminal, run:

```
claude
```

The first time you run this, Claude Code will ask you to log in. Follow the prompts — you will be directed to a browser window to authorize the connection. Once authorized, you will be returned to the terminal.

Type `/exit` and press Enter to close Claude Code for now.

---

## Step 6 — Get the wizard

In Terminal, paste this command and press Enter:

```
git clone https://github.com/pantheon-mark/agent-wizard.git ~/agent-wizard
```

This downloads the wizard to a folder called `agent-wizard` in your home directory. It only needs to run once.

---

## Step 7 — Launch the wizard

In Terminal, paste these two commands and press Enter after each:

```
cd ~/agent-wizard
```

```
claude
```

Claude Code will open, read the wizard instructions, and begin. The first thing it does is quietly verify that all your software is installed and current — if anything needs attention, it will tell you exactly what to do.

**That's it. The wizard takes it from here.**

---

## What to expect: permission prompts

As the wizard sets up your project, Claude Code will occasionally ask for your permission before creating files or running commands. You will see prompts like *"Claude wants to edit a file"* or *"Claude wants to run a command."*

**When you see these: click Allow.** These are expected — they are the wizard doing its work. You will not be asked about anything outside of what you are doing together.

Over time, you will see fewer of these prompts. When you click "Always allow" on a specific type of operation, Claude Code remembers that choice and will not ask again for that same action. The prompts taper off naturally as you go.

---

## Reading your project documents

The wizard produces plain-text documents — your vision document, your approach document, your agent roster, and more. These files display best in a Markdown viewer rather than a plain text editor.

**Recommended:** [One Markdown](https://apps.apple.com/us/app/one-markdown/id1507139439) — a clean, free Markdown viewer for Mac. Available on the App Store.

You do not need to install this before running the wizard. It is useful once your documents are produced.

---

## Keeping the wizard up to date

The wizard checks for updates automatically. When you launch the wizard and an update is available, it will tell you — you do not need to check on your own.

When the wizard tells you an update is available, run these two commands in Terminal:

```
cd ~/agent-wizard
git pull
```

This downloads the latest version. The wizard updates in place — no reinstallation needed. The next time you launch it, you will be running the updated version.

**What updates affect:** Wizard updates improve the setup experience for new projects. If you have already completed the wizard and have a running system, the update applies to future wizard runs. Your existing system continues to work as-is — the wizard does not modify projects it has already built.

---

## Troubleshooting

### The Homebrew installer asks about Xcode Command Line Tools

This is expected. Click Install. Xcode Command Line Tools is a Mac system component that Homebrew requires. The installation takes a few minutes — let it finish, then continue.

### `npm install` fails with a permissions error

If you see an error containing "EACCES" or "permission denied" when running the Claude Code install command, try this instead:

```
sudo npm install -g @anthropic-ai/claude-code
```

You will be asked for your Mac password. Type it and press Enter — you will not see the characters as you type, which is normal.

### Claude Code asks me to log in every time

This means the login session is not being saved between uses. Run:

```
claude auth login
```

Follow the prompts. Once completed, the login should persist between sessions.

### Error not listed here?

If you see an error message not covered above, copy the exact text of the error. Then open a new Claude Code session from any directory and paste it with this message:

> I'm trying to set up the Agent Team Wizard on my Mac and I got this error. Can you tell me what happened and exactly how to fix it?

Claude will diagnose it and give you exact steps to resolve it.

---

## After your wizard session

Once your agent team is running, consider making `/insights` a monthly habit. In any Claude Code session, type:

```
/insights
```

This generates a report of your Claude Code activity over the past 30 days — session patterns, friction points, and suggestions for improving your setup. It covers all your Claude Code work, not just this project, so use your judgment about which suggestions apply here.
