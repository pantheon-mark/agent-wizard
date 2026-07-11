# Agent Team Wizard Manual

*Installing the wizard, running the interview, and building your system. Running your system day to day is covered by the User Guide that lives inside your project.*

---

## What this covers

The about document told you what this is and whether it is for you. This manual is the how, for the first three parts of the path:

1. **Install** the tools, once.
2. **Interview**, where the wizard asks about what you need.
3. **Build**, where you and the wizard add your system one capability at a time.

After that you **operate** your system, and a separate User Guide inside your project takes over from here. You do not need any technical background. Every command below is written out for you to copy and paste exactly.

---

## What you'll need

- **A Mac.** This setup is Mac only.
- **A paid Claude account** at claude.ai (Pro or higher). The free tier does not support the tools the wizard uses.
- **An internet connection.**

A word on time, so it is not a surprise. Installing the tools takes about an hour, most of it waiting for downloads. The interview is one sitting. Building your system out to where you trust it runs over days and weeks, and the early part wants daily attention while you check its work. That is the nature of what you are setting up, not a sign anything is wrong.

---

## Installing the tools

You install five programs, then download the wizard. Each step is one command you copy and paste into Terminal, followed by a quick check.

Open Terminal first: press Command and Space together, type "Terminal", and press Enter. You will see a window with a blinking cursor. That is where every command below goes.

### Step 1: Install Homebrew

Homebrew installs and manages the other tools. Paste this and press Enter:

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

It may ask for your Mac password (the one you log in with). Type it and press Enter. You will not see the characters as you type, which is normal. The install takes a few minutes and prints a lot of text. When it finishes you will see a message like "Installation successful."

If a box asks to install Xcode Command Line Tools, click Install. It is a Mac component Homebrew needs, it is safe, and it takes a few minutes.

Check it:

```
brew --version
```

You should see something like `Homebrew 4.x.x`.

### Step 2: Install Git

Git keeps a version history of your project, so changes can be undone. Paste this and press Enter:

```
brew install git
```

Check it:

```
git --version
```

You should see a version number like `git version 2.39.0`.

**A note about GitHub.** Git runs on your computer. GitHub is a separate online service that stores a backup copy of your project's history in the cloud. The wizard offers to set up GitHub backup during the interview. You do not need a GitHub account now. If you want one ahead of time, it is free at github.com. This is optional and your project works without it.

### Step 3: Install Node.js

Claude Code is delivered as a Node package, so you need Node installed before you can install Claude Code in the next step. (Your finished system does not run on Node itself. This is only how Claude Code is delivered.) Paste this and press Enter:

```
brew install node
```

Check it:

```
node --version
```

You should see a version number starting with `v18` or higher.

### Step 4: Install Python

Some systems the wizard can build include parts that run Python code — for example, a part that writes information back into another service. Your Mac already has a `python3` command, but it's often an old copy Apple ships for its own use, not one meant to be relied on for this. Installing a current copy now means you never have to think about this again; the wizard always points at this exact copy, never at whatever `python3` happens to mean on your Mac. Paste this and press Enter:

```
brew install python@3.12
```

Check it:

```
$(brew --prefix python@3.12)/bin/python3.12 --version
```

You should see `Python 3.12.x`.

### Step 5: Install Claude Code

Claude Code is the tool the wizard runs inside. Paste this and press Enter:

```
npm install -g @anthropic-ai/claude-code
```

Check it:

```
claude --version
```

You should see a version number.

### Step 6: Log in to Claude Code

Paste this and press Enter:

```
claude
```

The first time, Claude Code opens a browser window to log in to your Claude account. Follow the prompts, then you are returned to Terminal. Type `/exit` and press Enter to close it for now.

### Step 7: Download the wizard

Paste this and press Enter:

```
git clone https://github.com/pantheon-mark/agent-wizard.git ~/agent-wizard
```

This downloads the wizard into a folder called `agent-wizard` in your home folder. It only runs once.

### Step 8: Launch the wizard

Paste these two commands, pressing Enter after each:

```
cd ~/agent-wizard
```

```
claude
```

Claude Code opens, reads the wizard's instructions, and begins. The first thing it does is quietly confirm your tools are installed and current. If anything needs attention, it tells you exactly what to do. From here, the wizard leads.

You start the wizard this same way every time: `cd ~/agent-wizard`, then `claude`.

---

## What permission prompts mean

While the wizard works, Claude Code asks permission before it creates a file or runs a command. You will see prompts like *"Claude wants to edit a file"* or *"Claude wants to run a command."*

During setup, click **Allow**. These are the wizard doing the work you asked for. Click **Deny** only if a prompt asks for something outside your project or something that was not described to you, and if that happens, note what it said and tell the wizard.

When you click **Always allow** for a kind of action, Claude Code stops asking for that same action. The prompts taper off as you go.

---

## The interview

The interview is a single sitting, and it feels like a conversation. The wizard asks focused questions, proposes a starting point from your answers, and you confirm, adjust, or redirect. Every answer saves to disk as you go, so you can stop and pick up later without losing anything or repeating yourself.

Over the sitting it works through a handful of areas: what you want it to do, a spending limit and what to do if it is reached, how you want it to reach you, any outside services it should connect to, and how much you want it to do on its own before it checks with you. You do not need to prepare any of this in advance.

Two things make it go well. Point it at one real, specific thing you do over and over ("warn me before a client deliverable slips," not "help me get organized"), and say what a good result looks like in concrete terms ("a short morning email listing what is due this week and what is already late," not "just keep me informed"). The more concrete you are, the better it builds. Vague answers leave it guessing.

If the conversation drifts from what you meant, say so. Redirecting now is free. After something is built, it is less so.

**Stopping partway is safe.** If you close the window, nothing is lost. To pick back up, reopen the wizard the usual way:

```
cd ~/agent-wizard
```

```
claude
```

It notices where you stopped and continues from the next question. You do not need to tell it where you were.

---

## Building your system

When the interview finishes, you build your system one capability at a time. This is where your answers turn into something that runs.

**Starting a build session.** The wizard gives you your first build instruction at the end of the interview, and also saves it in your project at `wizard/build_prompts/phase_01_build_prompt.md` in case you close the window. To run a build session, go to your project folder and start it:

```
./start-session.sh
```

**Your first capability.** The session builds the first capability and runs it for you under supervision, on a copy of anything real, so nothing that matters is touched on the first run. It explains what each part is doing in plain language as it goes.

**You will see one approval drill.** Early in that first run, the wizard pauses and shows you a clearly labeled practice prompt, something like *"[DRILL, NOT A REAL ACTION] this is how I would stop and ask before doing something that goes out in your name or cannot be undone."* It is a one-time demonstration of the guardrail. No real action is taken.

**Then you accept it.** The wizard walks you through a few plain questions about whether the capability did what you need. If it did, you accept it and that capability is done. If something is off, you say so and it fixes it before moving on. You always have something working.

**Each next capability.** When you are ready to add the next one, start a session the same way (`./start-session.sh`) and tell it you want to build the next phase. It checks that the previous capability was accepted, builds the next one the same way (supervised, on a copy, with the same acceptance questions), and stops when you accept it. You add capabilities at your own pace until your system does what you set out to build.

**Stopping and coming back.** When you are done for now, tell the wizard "pause" (or "I'm done for now"). It saves where you are and the single next step to disk, and confirms you can close. To come back later, from your project folder run:

```
./start-session.sh --resume
```

It reads its own notes and picks up where you left off. You never have to remember where you were.

**You may be offered an update.** Once your system exists, it does a quiet version check at the start of each session, build sessions included, to see whether a newer version is available. If one is, the wizard tells you in plain language which version you are on and what is newer, and asks whether you want it. It is always optional, nothing changes without your okay, and the wizard does the work for you if you say yes. During a build you can say "not now" and keep going. Your User Guide covers updates in full.

---

## Reading your project documents

The wizard produces plain-text documents: your vision, your approach, your agent roster, and more. They read best in a Markdown viewer rather than a plain text editor.

A good free one for Mac is [One Markdown](https://apps.apple.com/us/app/one-markdown/id1507139439), on the App Store. You do not need it before running the wizard. It is useful once your documents exist.

---

## Troubleshooting

These are the situations most likely to come up while installing, interviewing, and building. If something else happens, copy the exact text of any error and paste it into a Claude Code session with: *"I got this error setting up the Agent Team Wizard. Can you tell me what happened and exactly how to fix it?"*

### The wizard window closed or crashed during the interview

Nothing is lost. Reopen it the usual way:

```
cd ~/agent-wizard
```

```
claude
```

It finds where you stopped and continues from the next question. If it seems to want to start over, tell it you already completed the earlier steps and it will re-check its progress.

### It won't let you build the next capability

Each capability has to be accepted before the next one starts. Run the current one on your real work and finish its acceptance questions, then ask to build the next phase again.

### It says the build plan no longer matches what has been built

Do not force it. This happens when the plan and what is already built have drifted apart. Re-run the wizard so it can produce an updated plan, then continue building. The wizard will tell you this in plain language if it comes up.

### A capability needs a login or key you have not set up

Some capabilities connect to outside services. When one needs a connection you have not set up yet, the wizard stops and walks you through setting it up first, then continues.

### You are told you are near a usage or context limit

The wizard saves your place and hands you a short instruction to start fresh and pick back up. This is normal housekeeping, not a failure. Follow the instruction it gives you.

### A permission prompt asks for something you did not expect

Click **Deny**, note what the prompt said, and tell the wizard. Anything outside your project or not described to you should be declined.

### Tool install problems

- **The Homebrew installer asks about Xcode Command Line Tools.** Expected. Click Install, let it finish, then continue.
- **`npm install` fails with "EACCES" or "permission denied."** Try `sudo npm install -g @anthropic-ai/claude-code`. You will be asked for your Mac password (the characters will not show as you type).
- **Claude Code asks you to log in every time.** Run `claude auth login` and follow the prompts. The login should then persist.

---

## Where to go next

Your system is built. From here, your project comes with its own **User Guide** that covers running it day to day: starting and pausing sessions, reading the updates it sends you, approving actions, and keeping it current. It lives in your project folder. That is the document to keep close from now on.
