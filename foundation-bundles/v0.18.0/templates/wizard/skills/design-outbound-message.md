---
description: "Design pass for outbound messages — run before any email send, external-audience message, or operator digest to render and organize it for the channel. Never for internal artifacts or machine-to-machine handoffs."
---

# Design Pass — Outbound Messages

Run this before any message goes to a person outside the system. It reads your voice and style spec, checks the draft against a short checklist, and returns the message ready to send.

The operator is non-technical. Keep any questions or prompts plain. No jargon.

## When to run this

**Always run before:**
- Any email you are about to send (any recipient, any subject).
- Any message going to an external audience — a client, a stakeholder, anyone outside the system.
- Any operator digest (scheduled or on-demand summary for the operator).

**Never run for:**
- Internal `work/` artifacts, notes, or logs.
- Machine-to-machine handoffs (one agent passing structured output to another).

The trigger is structural — keyed to the channel and audience (email / external / digest), not to a judgment call about whether a message is "important enough."

## What you read first

1. `docs/voice_and_style.md` — the voice, tone, channel-rendering rules, and information architecture for this system. This is the authority for what "well-rendered" means here. Read it before evaluating the draft.

## The checklist

Run each item against the draft in order:

### 1. Rendered correctly for the channel?
- **Email:** HTML-rendered. No raw `#`, `*`, or `—` characters visible. Headings are headings, bold is bold, lists are lists.
- **SMS / push:** Plain text only. No markdown syntax at all.
- **Digest:** Match the format defined in `docs/voice_and_style.md`. If a format is not defined, ask the operator once before proceeding.

If the draft's format does not match its channel, fix it now — do not pass it through as-is.

### 2. Leads with what needs action?
The first thing a reader sees should tell them what (if anything) they need to do. Background and context come after, not before.

If the draft buries the action item, reorder it.

### 3. Noise suppressed and low-value lists collapsed?
Lists that restate the obvious, repeat information already in the subject or header, or itemize things the reader cannot act on individually should be collapsed into a single plain sentence, or removed.

Every item in a list should earn its place.

### 4. Deltas shown — "since last time"?
Where the message covers recurring information (a weekly digest, a status update, a recurring report), surface what changed. A reader who already knows the background does not need it repeated — they need to know what is different now.

If nothing has changed, say so briefly. Do not send a full repeat.

## Output

Return the message, designed. Do not return a critique or a list of changes — return the message itself, ready to send.

If a channel format question came up in step 1 and the operator needs to answer before you can render (e.g., digest format is not defined in `docs/voice_and_style.md`), ask that one question and wait for the answer before returning the message.

## Edge cases

| Condition | Behavior |
|-----------|----------|
| `docs/voice_and_style.md` is missing | Note it plainly, apply reasonable defaults, flag the gap. Do not fail silently. |
| Draft is for an internal artifact (no external recipient) | Tell the operator this skill does not apply and stop. |
| Channel is unclear (no recipient or context given) | Ask one question to clarify the channel before proceeding. |
| Draft is already well-rendered | Return it as-is with a one-line confirmation. Do not pad. |
