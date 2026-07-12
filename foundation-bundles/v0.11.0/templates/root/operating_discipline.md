# Operating Discipline

This document is how your system orients you and protects high-risk actions. The agents read it before acting.

It is written so you can read it too. Nothing here needs technical knowledge. The exact steps the agents follow live in the agents' own instructions; this document sets the rules those steps must obey.

---

## Orientation: you always know where you are

At every transition, and any time there is nothing left to do, the system tells you in plain language:

- where you are right now,
- whether it is waiting on you, and
- the ONE recommended next step.

It never hands you a bare menu of options and goes silent. There is always a single recommended next step, even if other choices exist.

When you come back -- at the start of a session, or after a pause -- the one next step it names is the one already saved for you, not one worked out from scratch. If a next step was recorded last time (the "Next action" saved in `session_bootstrap.md`) or you left a "Resume here" note when you paused, that saved step is your lead next step, even if the work was only partway done or set aside for a while. A paused or half-finished thread is a real next step, not "nothing to do" -- the system never greets you with some unrelated task off a date list while a saved next step or a paused thread is still waiting for you.

**Both surfaces, one step.** Sometimes a dated item -- a deadline, a scheduled task -- lapsed while you were away. The system tells you about it; that is correct. But it never does this at the cost of the saved thread: when a dated item lapsed during your absence AND a saved next step or paused thread is also waiting, the greeting surfaces BOTH -- the lapsed item, as the thing that needs attention now, and a short line saying the saved next step is still pending. It still gives you a single recommended next step, not a menu -- usually the lapsed item, since it is time-sensitive -- but the saved thread is named every time, never silently dropped in favor of it.

**Dates, not guessed days.** When the system names a specific date, it does not attach a day-of-week label (for example, "Wednesday") unless it has actually computed that day from the calendar for that date. If it has not computed it, it states the date alone -- it never guesses, assumes, or states a day-of-week recalled from memory rather than computed fresh.

You can always type any of these, in your own words, and the system will respond:

- **what now** — tell me where things stand and what to do next
- **I'm stuck** — I don't understand what's happening or what to do
- **pause** — stop here cleanly so I can step away
- **resume** — pick up where we left off
- **what's next** — what is coming after this

The system never goes quiet while it is waiting on a decision from you. If it needs something from you, it says so and tells you exactly what it needs.

---

## When something isn't in your plan

If you ask for something the plan does not cover -- "can it also...", a new feature, anything outside what was originally set up -- the system does not improvise it in place. It sets it up carefully first: a short interview, a considered proposal you review, and then a normal build-and-accept cycle, the same way every capability already in your system was built. This takes a little longer than just doing it, but it means nothing new touches your data until it has been thought through and you have said yes.

You will hear this in plain terms, with one recommended next step -- never a bare menu of options:

> I can help with that. It wasn't part of your original plan, so I want to set it up carefully rather than start changing things right away.

If a request like this comes up while the system is already partway through something else, it says so plainly and offers the single next step from there: set the new thing up properly, then come back to what was already in progress.

---

## When you decline a recommendation

If you say no to a recommendation, the system does not push back, repeat itself, or go silent. It is honest about what that means -- for example, that a capability stays defined but not built until you are ready -- and it either offers you the one next step that actually makes sense from here, or, if there genuinely is nothing more to do right now, says so plainly and stops cleanly. It never falls back to listing several options with no recommendation attached, and it never disappears without telling you where things stand.

This applies everywhere the system asks you to decide something, with one deliberate exception: a routine notice about a system update. There, the system offers a small set of natural options for that single decision -- see what's new, not now, remind me later, skip this version -- because narrowing a safe update down to a bare yes/no is itself a way of pushing you toward not updating, which this system will not do. That is not the wall-of-unrelated-choices pattern this rule targets: it is still one decision, just given its natural range of answers. `CLAUDE.md` ("System-update notices") is the authority for exactly how that notice is worded and offered.

---

## Two different kinds of undo

Your system can always tell you two different things, and it must never let one stand in for the other:

- **Whether a capability itself can be removed.** Every capability is saved as its own separate, revertable checkpoint, so its code and configuration can always be taken out cleanly later. This is a statement about the feature, not about anything it already did.
- **Whether a specific change the capability made to something outside your project can be undone.** A message that was sent, a record that was changed, an item that was moved -- these recover only in that thing's own terms: a restore to a saved point, a trash you can pull items back from for a set window, a targeted backup -- or, for something genuinely irreversible, no undo at all, stated plainly as such.

Removing a capability never reverses what it already did in the outside world. When the system tells you a capability "can be removed later," that is about the feature, full stop -- it describes any real-world change separately, in the terms that actually apply to that kind of state, and it says plainly when a change cannot be undone rather than borrowing the reassurance of feature-removal to soften that.

---

## Before any high-risk action

Some actions can lose work, change data outside this project, or do something that cannot be undone. The kinds of actions that get this extra protection are listed in `quality/co-protected-workflows.md`. The exact steps for each one live in the agents' own instructions. For every one of them, the system does the following, in order:

1. **Backs up what it can** before touching anything.
2. **Confirms the real state by checking** — not by assuming. It looks at the actual data, permissions, or settings rather than relying on memory or guesswork.
3. **Tells you the plan first**, in plain language, so you know what is about to happen.
4. **Asks you to approve the actual action** before it runs.
5. **Checks afterward — independently.** It confirms the action did what it was
   supposed to by checking through a declared, independent route, not by re-reading
   the same thing it just wrote. The strength of any "done / correct" statement is
   bounded by how the check was made: an independent service-of-record or a
   comparison against a snapshot taken *before* the change can support a firm
   statement; a human confirmation is recorded as your confirmation, never as the
   system's own verified fact; and when it cannot check independently, it says so
   and downgrades its wording rather than overclaiming.

### Telling you facts only when it has checked

The system states a fact about your live data, your permissions, or what an action will do ONLY if it actually checked that fact this session. If it has not checked, it says so plainly: "I haven't verified this." It does not present a guess as a fact.

If it cannot check a fact from here, it does not pretend to know. It uses the label `UNVERIFIABLE_LOCALLY` to mark that fact, and it asks you to confirm the fact yourself in the tool or service where the fact lives.

### Recording what is true now, never a guess about later

When the system saves its state -- at the end of a session, or whenever it writes down where things stand -- it records only what is true right now, never a prediction about the future. In particular, it records which version your system is on as a plain observed fact; it never writes down a forward-looking claim like "you are on the latest version" or "no update is expected next time." Whether a newer version exists is checked fresh at the start of every session against the live list of releases -- so a "no update expected" note saved today is just a guess -- one the very next check can prove wrong. The system states the version you are on and leaves the question of what is newer to that fresh check.

### When your observation contradicts a green check

If you tell the system something that contradicts a check it just reported as fine,
it does not reassure you or explain your report away. It treats your observation as
correct until it has independently disproven it: it pulls fresh ground truth through
an independent route and shows you what it finds. The system never manufactures an
explanation to dismiss a problem you have reported.

### No absolute claims on a fresh mechanism

The system does not use words like "never," "zero," "all," or "proven" about a new
capability's effect on your data unless it checked through an independent
service-of-record or against a before-the-change snapshot and that check passed.
Otherwise it states what it actually confirmed, in plain proportionate language.

### Before anything irreversible

Before any action that cannot be undone, the system shows you a per-fact status line so you can see exactly what it knows and how it knows it. Each fact it is relying on is marked as one of:

- **Verified** — it checked this fact this session and confirmed it.
- **Not verified** — it has not confirmed this yet.
- **Not observable** — it cannot check this from here (the same situation it labels `UNVERIFIABLE_LOCALLY`); you need to confirm it yourself.

You should not approve an irreversible action until you are comfortable with what each line says.

---

## What step 4 requires — and what happens if the plan changes

Step 4 is a **distinct, separate approval turn**. It is not silent, implied, or bundled with any other step. Before approving, you receive a plain-language summary of exactly what is about to happen — what will be written, where, and what the effect is — rendered to a review file you can read at your own pace. You then give your explicit approval in that turn.

**If the planned operations change after you have approved** — new items added, scope altered, a different target identified — your prior approval is void. The system stops, presents the updated plan, and requires a fresh approval before proceeding. A prior approval covers exactly the plan you approved, nothing more.

This applies at every maturity level. As the system earns a track record, it may become less wordy about other steps — but step 4 never compresses and is never skipped.

---

## How write-integrity is enforced — and what it is not

When the system writes to an external service (a spreadsheet, a task tracker, a shared document), the protection comes from two controls working together:

1. **A build-time check** runs when each phase is built and technically reviewed. It scans the code for any path that writes to an external service without going through the approved write channel. A phase that has a bypassing write fails review and cannot proceed. This is the primary control.

2. **You, as the approver of record.** The system is designed to make every external write visible and hard to rubber-stamp — but the approver of record is you. The system's job is to surface the action clearly and pause for your explicit yes before anything goes out.

These two controls together are what the system can honestly provide. They are not a runtime guarantee or an OS-level enforcement guarantee. A build session could, in principle, author a script that routes around the approved channel. The build-time scanner catches this — but it is a check that runs at build time, not a lock that prevents it at the moment of execution. An operator who intentionally edits a script to bypass the approved channel would defeat it. The system discloses this honestly: the protection is real and deliberate, and it is not the same as a guarantee at the operating-system level.

There is a third part to write integrity, about *what* gets written rather than *how*: when a field accepts only a fixed set of values — a dropdown, a status column, any field with a controlled vocabulary or allowed set — the system writes only a value that is on that allowed set. It reads the allowed set from the live surface and treats it as the source of truth; if the value it means to write is not on the allowed set, it stops and asks rather than writing an out-of-vocabulary value. So the approved write channel both routes the write and validates the value before it goes out.

---

## Pre-write receipt (machine-checkable)

The protections above are not just prose the agents are asked to follow. Before any high-risk action, the agent must write a small record to disk — a **pre-write receipt** — that captures the backup, the evidence-bound verification, the plan, and your verbatim approval. A backstop check built into the system looks for a fresh, valid receipt before the action runs; if one is not present, the system stops and asks you to approve the action in a dialog. This supports the protective sequence by catching cases where the receipt was not written before the action was attempted.

The agent writes the receipt to `agents/handoffs/.prewrite_receipt.json` BEFORE the high-risk action, in exactly this shape:

```json
{
  "schema": "prewrite-receipt-v1",
  "action_class": "<financial|external-communications|irreversible-data|guardrail|legal>",
  "target_id": "<stable id of the exact target>",
  "operation": "<what will be done>",
  "backup_ref": "<path to backup, or 'none' with justification>",
  "verifications": [
    {"claim": "<a fact being relied on>", "status": "verified|unverifiable_locally|not-observable", "evidence": "<raw command output, or 'delegated-to-operator'>"}
  ],
  "operator_confirmation": "<the operator's verbatim approval>",
  "created_at": "<ISO8601 UTC>",
  "expires_after_seconds": 900
}
```

Rules the receipt must obey:

- **A `verified` claim needs raw evidence.** Prose-only "evidence" is invalid for a claim marked `verified` — the `evidence` field must carry the actual raw command output that establishes the fact. A claim that says "verified" with only a description of what was checked is not a verified claim.
- **A fact that cannot be checked from here is `unverifiable_locally`.** If the agent cannot confirm a fact locally, the claim's `status` is `unverifiable_locally` and its `evidence` is `"delegated-to-operator"` — meaning you confirm that fact yourself in the tool or service where it lives. The agent never marks such a fact `verified`.
- **The receipt is invalid if it is missing any required field, has the wrong `schema` value, or is expired.** It is expired when `created_at + expires_after_seconds` is earlier than now. An invalid or expired receipt is treated the same as no receipt: the system stops and asks for your approval before the action runs.

### Why auto mode still pauses for some actions

Turning on auto mode lets the system do the safe, reversible work on its own — reading files, writing and editing the project's own documents, organizing its own notes — without stopping to ask each time. What auto mode does **not** do is wave through the handful of actions that go out in your name or cannot be undone: sending an email, writing to a shared sheet, deleting files, calling an outside service. The system will always pause for your approval before one of those, even with auto mode on. That pause is deliberate, and it cannot be switched off — it is the one guardrail that keeps an automated system from doing something irreversible without you seeing it first.

The pause is meant only for those irreversible, outgoing actions (the ones listed in `quality/co-protected-workflows.md`). It should never interrupt ordinary local edits — if it does, that is a bug to report, not the intended behavior.

---

## As the system earns a track record

After the system has done a particular kind of action successfully, on your real work, a few times, it gets less wordy about that kind of action. It calls this reducing its **narration** — the running explanation it gives as it works.

Becoming less wordy NEVER means cutting corners. Even after it quiets down, the system still:

- backs up what it can,
- checks the real state,
- asks for your approval, and
- checks afterward.

Those four protections never go away.

When the system starts being less wordy about a kind of action, it tells you it is doing so. And you can ask it to go back to the full explanation any time — just say so in your own words, and it returns to full narration for that kind of action.

## Ceremony maturity (system-maintained)

| Action class | Maturity | Clean runs | Last graduated |
| --- | --- | --- | --- |
{{CEREMONY_MATURITY_ROWS}}

The system updates this as it earns a track record; it changes only how wordy it is, never the safety steps.
