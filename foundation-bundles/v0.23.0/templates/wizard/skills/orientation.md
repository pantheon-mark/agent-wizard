---
description: "Orient the operator: say where they are, whether the system is waiting on them, and the single next step. Use when the operator says 'what now', 'what's next', 'where am I', 'I'm stuck', 'what should I do', 'resume', or 'pick up where I left off'."
---

# Orientation

This skill tells the operator exactly where they are and what the one next step is. Use it whenever the operator is unsure what to do, has come back after a break, or asks the system to pick up where they left off. The operator is non-technical, so never hand them a menu of options or a status dump -- give them their bearings and a single clear next step.

## What you read first

Read these files from disk, fresh, every time. Do not answer from a remembered or summarized version of a prior session -- the state on disk is the only truth, and it may have changed since you last looked:

- `session_bootstrap.md` -- the current state of the session, including the `NEXT_RECOMMENDED_ACTION` line and any "Resume here" note left by the pause skill.
- `build_progress.md` -- which phases have been built and accepted, and which is next.
- `pending_decisions.md` -- anything the system is waiting on the operator to decide.
- The current loop state from disk (whatever file tracks where an in-progress run or phase left off).
- The capability health check: run `python3 agents/lib/external_write/capability_health.py --overall` and read its JSON `normal_status_allowed` flag. Also read its `interrupted_trial` block and its `open_external_write_bypass` block — each one carries an `action` (or, for a flagged file, `actions` keyed by file) that is the exact next step, already written out. Relay that, rather than composing your own.

If the operator is resuming or picking up where they left off, read the "Resume here" note in `session_bootstrap.md` first -- the pause skill wrote it precisely so this skill can find it.

## What you tell the operator

After reading, tell the operator in one short paragraph -- plain language, no jargon:

1. **Where they are** -- which phase is current and what has already been accepted, in a sentence.
2. **Whether the system is blocked or waiting on them** -- if a phase acceptance is pending, name it explicitly. For example:

   > Your system is waiting for you to accept Phase 2 -- say "I accept", or tell me what's wrong.

   If a decision in `pending_decisions.md` is open and blocking, name that decision and what it's waiting for.
3. **The one recommended next step** -- a single concrete action they can take right now. Not a list. Not "you could do A, B, or C." One step.

Never present a bare menu of options. If there genuinely is more than one reasonable next step, pick the one you recommend, say why in a few words, and mention the others are available if they prefer -- but lead with the single recommendation.

If — and only if — the health check's `normal_status_allowed` is `true` and nothing else is blocked, say plainly that the system is ready and give the one next step. If `normal_status_allowed` is `false`, lead with the pending action it names (a paused/red capability to rebuild, or an interrupted run to resume) in plain language — never report all-clear over a switched-off capability.

## If a trial was interrupted

The health check's `interrupted_trial` block with `"outstanding": true` means a supervised trial was cut off part-way — the machine went to sleep, the session was closed, the process was killed — and a change it made may still be sitting live on the operator's real account or sheet. Nothing was printed when it happened, so this block is the only place it shows up. It is not a warning to note and move past: lead with it.

Tell the operator plainly what it means in their terms — something was part-way through being tested and may not have been put back — and give them the one step, which is the `action` the block already carries for that trial. It is this command with the trial's own id filled in, and it puts every change back and then checks that it worked:

```
python3 agents/lib/external_write/trial_recovery.py --trial-id <trial-id-from-the-health-check>
```

Run it from the project root. It exits `0` when everything is back and confirmed, and non-zero when something still needs attention — in which case read what it printed and follow that, and never tell the operator it is finished. If the block lists something under `unreadable` instead, a record could not be read at all: say so plainly, name the file, and do not tell the operator that nothing is outstanding — that is the one thing an unreadable record cannot establish.
