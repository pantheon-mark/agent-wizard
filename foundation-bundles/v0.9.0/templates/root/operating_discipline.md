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

You can always type any of these, in your own words, and the system will respond:

- **what now** — tell me where things stand and what to do next
- **I'm stuck** — I don't understand what's happening or what to do
- **pause** — stop here cleanly so I can step away
- **resume** — pick up where we left off
- **what's next** — what is coming after this

The system never goes quiet while it is waiting on a decision from you. If it needs something from you, it says so and tells you exactly what it needs.

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
