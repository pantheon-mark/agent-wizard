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

If the operator is resuming or picking up where they left off, read the "Resume here" note in `session_bootstrap.md` first -- the pause skill wrote it precisely so this skill can find it.

## What you tell the operator

After reading, tell the operator in one short paragraph -- plain language, no jargon:

1. **Where they are** -- which phase is current and what has already been accepted, in a sentence.
2. **Whether the system is blocked or waiting on them** -- if a phase acceptance is pending, name it explicitly. For example:

   > Your system is waiting for you to accept Phase 2 -- say "I accept", or tell me what's wrong.

   If a decision in `pending_decisions.md` is open and blocking, name that decision and what it's waiting for.
3. **The one recommended next step** -- a single concrete action they can take right now. Not a list. Not "you could do A, B, or C." One step.

Never present a bare menu of options. If there genuinely is more than one reasonable next step, pick the one you recommend, say why in a few words, and mention the others are available if they prefer -- but lead with the single recommendation.

If nothing is blocked and the system is simply ready for the next thing, say so plainly and give them the one next step (for example, building the next phase).
