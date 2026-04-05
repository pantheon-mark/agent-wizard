# How Your System Works

*This guide explains how your agent team manages itself. Everything described here is already configured and will happen automatically once your agents are built and running. Read it at your own pace — there's nothing you need to do right now.*

---

## When the system finds a problem

When the system encounters an issue, it will fix it if it safely can, ask for your approval if the fix touches something important, or ask you one specific question if it needs your judgment. It will never just tell you something is broken and leave you to figure out what to do.

---

## Log management

Your system keeps detailed logs of everything it does. It will automatically manage those files — keeping them from getting too large and cleaning up old ones periodically. It will always ask you before permanently deleting anything. You'll see a note in your digest when any of this happens.

---

## Recovering from problems

If something goes wrong and a previous state needs to be restored, the system will identify what needs to change and walk you through it. For anything significant, it will always ask for approval before making changes.

---

## Session management

If you ever need to start a new session, the system will tell you exactly what to do — it keeps everything needed to pick up right where you left off.

---

## Model management

The AI models your agents use are kept current automatically — you don't need to manage this.

---

## Keeping tools up to date

The tools your system depends on are kept up to date automatically. If anything needs your attention, you'll hear about it in your digest.

---

## Document updates

Every time the system updates your documents, your digest will explain what happened, why it changed, and what's different — so you always know what your documents say and why.

---

## Quality checking

Your QA agent automatically checks the work your other agents produce. If it flags something, it will tell you in plain language what it found and wait for your decision before anything moves forward.

---

## Security

Your QA agent also checks whether integrations and connections your agents build are set up safely — that they only access what they need to, and that they handle any personal information carefully.

---

## Personal information in logs

Your agents keep detailed logs of everything they do — but they're instructed never to write personal information into those logs. If they're working with customer records, they log something like "processed record [ID:4782]" — not the person's name or email.

---

## Pre-flight checks

Before your agents do anything, they first declare exactly what they're planning to change. If the plan looks unusually broad for that agent, the system pauses and asks you to confirm before a single file is touched.
