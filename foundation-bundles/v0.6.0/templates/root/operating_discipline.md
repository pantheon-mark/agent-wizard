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
5. **Checks afterward** that the action did what it was supposed to.

### Telling you facts only when it has checked

The system states a fact about your live data, your permissions, or what an action will do ONLY if it actually checked that fact this session. If it has not checked, it says so plainly: "I haven't verified this." It does not present a guess as a fact.

If it cannot check a fact from here, it does not pretend to know. It uses the label `UNVERIFIABLE_LOCALLY` to mark that fact, and it asks you to confirm the fact yourself in the tool or service where the fact lives.

### Before anything irreversible

Before any action that cannot be undone, the system shows you a per-fact status line so you can see exactly what it knows and how it knows it. Each fact it is relying on is marked as one of:

- **Verified** — it checked this fact this session and confirmed it.
- **Not verified** — it has not confirmed this yet.
- **Not observable** — it cannot check this from here (the same situation it labels `UNVERIFIABLE_LOCALLY`); you need to confirm it yourself.

You should not approve an irreversible action until you are comfortable with what each line says.

---

## Pre-write receipt (machine-checkable)

The protections above are not just prose the agents are asked to follow. Before any high-risk action, the agent must write a small record to disk — a **pre-write receipt** — that captures the backup, the evidence-bound verification, the plan, and your verbatim approval. A check built into the system (a hook that runs before the action's tool call) looks for a fresh, valid receipt; if one is not present, the system stops and asks you to approve the action in a dialog rather than letting it run silently. This makes the four protections enforceable rather than advisory.

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
