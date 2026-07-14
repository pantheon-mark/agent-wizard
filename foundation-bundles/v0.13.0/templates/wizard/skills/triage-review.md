---
description: "Review a batch before a bulk action runs — group flagged items, show what's safe versus what needs a look, and get the operator's approval before anything is queued for a bulk write-back run. Use when a capability has scanned a batch of candidates and needs the operator's judgment before approving them for a bulk action, when the operator asks 'what did you find', 'what's safe to approve', 'show me what needs review', or 'review these before you act', or before minting a run envelope for any multi-item write-back run."
---

# Triage Review

This skill is the judgment step between "a capability scanned a batch of candidates" and "the operator approved a specific set for a bulk action." It groups what was found, shows the operator plainly what's safe, what has exceptions, what needs a look, and what is protected — then builds the exact approved set the bulk run is bound to. It never runs the bulk action itself; that happens afterward, through the run mechanism this skill hands off to.

The operator is non-technical. One decision at a time. Plain language throughout — no internal field names, categories, or digests in anything you say; those stay in the record, not the conversation.

Before your first operator-facing line, read `operating_discipline.md`. It is the authority for this system's voice and for how high-risk actions are protected — open with substance, one recommended step at a time, and phrase any choice you offer in the operator's own voice ("Have the assistant include the safe groups" rather than "I'll include the safe groups"). Where a document goes in front of the operator to review, it goes to a review file they open at their own pace — never pasted into chat.

## When to run this

Run this whenever a capability has a batch of candidates to review before a bulk write-back run — the judgment path upstream of any multi-item approval. Do not run it for a single item the operator is deciding on its own, and do not use it to actually apply anything: it only builds and gets approval for the reviewed set. The run itself happens afterward, through the capability's normal run path.

## What you read first

The capability that scanned this batch already produced its candidates, each shaped as `{unit_id, entity_key, reason_shown, source_snapshot_digest, protected_status, is_safe}` — `entity_key` is whatever this capability naturally groups by (an account, a record key, a batch tag), and `is_safe` / `protected_status` are that capability's own judgment about each item, not something this skill infers. If the capability has not produced that shape yet, that is upstream work for the capability's own code, not this skill.

## Step 1 — Group and classify

Call `triage_discovery` and `triage_candidates` from `agents/lib/external_write/triage.py` against the batch. `triage_discovery` gives you exactly one row per `entity_key` — the deduped summary — and `triage_candidates` gives you the full per-item classification. Every item lands in exactly one of four buckets: safe with no exceptions, mostly safe with specific exceptions itemized, needs a look, or protected (never touched by a bulk action). Trust these buckets as given — do not re-judge an item's safety yourself.

## Step 2 — Show the operator what was found

Summarize the discovery rows plainly, grouped and counted, never one row per raw item. For example, in substance (not verbatim wording):

> I looked through the batch. Of the [N] groups: [X] look safe to include as-is, [Y] are mostly safe but have some specific items worth a second look, [Z] I couldn't classify confidently and want your read on, and [W] are protected — those are never included in a bulk action.

Name the specific exceptions and the reasons for anything needing review or protected, in plain terms drawn from `reason_shown` — never a raw id, category label, or digest.

## Step 3 — Get the operator's decision, one group at a time

Ask the operator which groups to include in this run, one category at a time — never bundle several judgment calls into a single yes/no. Protected items are never offered as includable — do not ask about them, just tell the operator plainly they are excluded and why.

## Step 4 — Build the reviewed set and get it approved

From `triage_candidates`, take only the specific units the operator actually approved — never a whole category the operator did not explicitly confirm, and never "everything not protected." Call `render_review_artifact` (in `agents/lib/external_write/run_envelope.py`) on that exact set. This renders the same deterministic, itemized artifact every time for the same set — it is what the operator's approval binds to.

Write that rendered artifact to a review file the operator opens on their own — never pasted into chat — and ask for their explicit approval of it, plainly:

> Here's the exact list this run would cover. Take a look, and tell me to go ahead if it's right.

## Step 5 — Mint the run envelope

Once approved, call `mint_run_envelope` with `reviewed_set_schema="reviewed_set-v2"`, the approved reviewed set, and `operator_approved_review_artifact` set to the EXACT text the operator just approved (not a summary, not a re-render). If it refuses, do not retry with a different schema or a hand-edited set to make it pass — tell the operator plainly what could not be confirmed, and stop. Nothing is queued for a bulk run without a minted envelope.

## Step 6 — Hand off

With the envelope minted, tell the operator plainly what happens next — the bulk run itself proceeds through the capability's normal run path, applying only the exact set just approved. This skill's job ends here; it does not run the action.

## Edge cases

| Situation | What to do |
|-----------|------------|
| No candidates at all | Tell the operator plainly there is nothing to review this time. Nothing to build, nothing to mint. |
| Every group is protected | Tell the operator plainly nothing in this batch is eligible for a bulk action, and why. Do not mint an empty or protected-only envelope. |
| Operator approves nothing | Stop. Nothing is built or minted. Tell them plainly they can come back to this batch later. |
| `mint_run_envelope` refuses | Surface the plain-language reason and stop. Never fall back to a weaker schema or a hand-built envelope to force it through. |
| The candidate batch is missing a required field | Malformed items are dropped by `triage_candidates`/`triage_discovery` automatically, not guessed into a bucket — if a large share of the batch is dropped this way, tell the operator plainly that some items could not be classified and were left out, rather than silently under-reporting the batch size. |
