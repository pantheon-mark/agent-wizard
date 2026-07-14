---
description: "Pause cleanly for the day and write a disk-first resume note. Use when the operator says 'pause', 'stopping for the day', 'I'm done for now', or 'stop here'."
---

# Pause

This skill lets the operator stop cleanly and come back later without losing their place. When the operator says they're done for now, you write a short resume handoff to disk so the next session -- or the orientation skill -- can pick up exactly where they left off. The operator is non-technical: they should be able to close the window and trust that nothing is lost.

## What you do

Everything lives on disk. Nothing relies on session memory. Before you tell the operator they can close, write the handoff:

1. **Update ALL of `session_bootstrap.md`'s orientation fields** -- not just the next action. A future session (or the orientation skill) reads these to know where things stand, so every one of them must reflect this pause, or the file will misreport the state:
   - **`Next action`** (`NEXT_RECOMMENDED_ACTION`) -- the single next step the operator (or the system) should take when they come back. One concrete action, plain language.
   - **The header `Updated:` line** -- set the date to today's actual system date and the trigger to a pause. Get today's date from the system clock, never guess it: run `date +%Y-%m-%d` and use exactly what it returns.
   - **`Last session`** -- today's date (same system-clock date).
   - **`Last agent run`** -- if an agent ran this session, its name and today's date; otherwise leave the prior value.
   - **The `System status` table and `Current phase`** -- update `Current phase` and any status-table value that changed this session, so the table is not stale.
2. **Append a short "Resume here" note to `session_bootstrap.md`** -- a few lines, dated with today's system-clock date (`date +%Y-%m-%d`), covering:
   - **What's in progress** -- the phase or task that was underway, and how far it got.
   - **The next step** -- what to do first when resuming (this matches `NEXT_RECOMMENDED_ACTION`).
   - **Any open gate** -- anything the system is waiting on: a pending phase acceptance, an open decision in `pending_decisions.md`, a credential still to set up. If there's nothing open, say so.

The orientation skill reads this "Resume here" note first when the operator picks up again, so write it for that reader: short, plain, and specific about the one next step.

## What you tell the operator

Once the handoff is saved, confirm in one sentence -- for example:

> I've saved where we are and what to do next, so you can safely close now. When you come back, just say "what's next" and I'll pick up right here.

Do not start any new work after a pause request. Write the note, confirm, and stop.
