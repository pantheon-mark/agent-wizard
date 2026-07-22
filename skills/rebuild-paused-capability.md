---
description: "Rebuild an existing capability that a contract-changing upgrade paused and queued for migration. Use when `agents/handoffs/pending_migrations.json` has a pending entry, when a `capability_health` check reports a capability red because it is paused or waiting on a pending migration, when the operator asks why something stopped working after an update or says 'it says this needs to be rebuilt', or when the add-capability or next-phase skill hands off here because the request is a paused-capability rebuild rather than something new. Not for setting up a capability that never existed before — use add-capability for that. Not for bringing up a phase already in the plan — use next-phase for that."
---

# Rebuild a Paused Capability

An upgrade found that one of the operator's existing capabilities no longer matches a safety rule the system now enforces, and safe-paused it rather than leave it running unsafely or break it outright. This skill is the one, guided path back from that: it does not redesign what the capability is for, it repairs the one technical thing that changed, proves the repair really works, and gets the operator's go-ahead before anything runs live again.

The operator is non-technical. Go one step at a time. Never make them read a raw error message or a technical setting — translate everything into plain business terms. This skill does not ask the operator what the capability should do, why it matters, or what it must never do — none of that changed. It only asks for the one thing only the operator can give: their go-ahead once the repair is proven safe.

## What this skill does — and does not — do

**It does:** find the exact capability and the exact thing that changed; make the one repair that entry calls for; prove the repair on a copy; walk the operator through accepting it live again; confirm the capability is healthy afterward.

**It does not:** run an interview about what the capability is for, redesign its scope, or change its business purpose. If the operator wants something genuinely new added, that is add-capability's job, not this one.

## Step 1 — Find what's paused and why

Read `agents/handoffs/pending_migrations.json`. It is a JSON array; each entry names the paused capability (`mechanism_id`), why it was paused (`reason`), what an upgrade changed (`from_version`/`to_version`), and what to do about it (`suggested_next_step`). Find the entry that matches what the operator is asking about.

- **If the operator named the capability plainly** ("the thing that sorts my inbox," "the sheet updater"), match it to the entry whose `mechanism_id` corresponds to that capability — check `security/capability_descriptors.json` if the plain name doesn't obviously match an id.
- **If more than one entry could plausibly be what the operator means**, do not guess — name each candidate in plain language and ask which one, the same way next-phase does before touching anything that turns on live use.
- **Also check `capability_health`** (`python3 agents/lib/external_write/capability_health.py .`, run silently) even when a queue entry exists — it is the same deterministic check add-capability's own Step A runs, and it can catch a capability the queue itself missed (a reconcile pass that ran before this capability existed, or scoped over a different part of the project). Treat a `"health": "red"` result with `pending_migration: true` or `paused: true` and no matching queue entry exactly like a queued one.
- **If nothing matches** — no queue entry, and `capability_health` reports this capability green — tell the operator plainly there is nothing to rebuild here, and stop.

Once you have the entry, read its `reason` and `suggested_next_step` — that is what actually needs to happen next, not a guess.

## Step 2 — Make the one repair the entry calls for

The repair is bounded and specific to what changed. Do not touch anything about the capability beyond what the entry names.

**If the entry's `kind` is `missing_evidence_predicates`:** an upgrade added a new required check for how this capability proves a write landed or undid, and the migrator already auto-scaffolded a stub for it that fails on purpose — the entry's `missing_predicates` names which one(s), and `writer_relpath` names the adapter file they live in. Open that file, find the method(s) that currently just raise `NotImplementedError` with a plain-language message, and replace each with a real implementation that actually checks whether the write landed (or undid) — never a stub that only returns `True`, and never anything that merely silences the error. If you cannot implement a real check yet, leave the stub raising `NotImplementedError` rather than fake a passing one: a capability that honestly stays paused is the correct outcome, never a capability that quietly stopped proving anything. This is the only code-authoring this skill ever asks for.

**If the entry has no `kind` field** (a direct-write violation an upgrade caught, not a missing-predicate gap): the capability's write path needs to be routed through a registered external-write adapter instead of writing directly. Reuse the same deterministic scaffold add-capability's own Step F already runs — `python3 agents/lib/external_write/capability_code_scaffold.py --spec <spec> --project-root .` — but build the spec from this capability's OWN existing descriptor and roster entry (`security/capability_descriptors.json`, `agents/roster.md`), never from a fresh interview: what this capability is for has not changed, only how its write is wired.

## Step 3 — Prove it

**Self-QA (silent, fail-closed).** Run the same deterministic check next-phase's Step 4 runs, for this capability's id:

```
python3 agents/lib/external_write/capability_invariants.py . "<the capability's id>"
```

If it exits non-zero, do not continue — fix what it names and re-run until it exits `0`. Never advance past a red result.

**Supervised trial on a copy.** Once self-QA is clean, run the same supervised copy-run trial next-phase's Step 5 describes: set up a copy of any external state this repair touches, carry the change all the way through on the copy (apply → undo → verify-restored), and record that trial as `agents/handoffs/<capability_id>.copy_run_proof.json`. If the copy run cannot be carried through to a verified restore, tell the operator plainly it is not ready yet, and stop — do not proceed to acceptance on an unproven repair.

## Step 4 — Get the operator's go-ahead

Tell the operator plainly what was wrong, what was fixed, and that it has been proven safe on a copy — never the technical detail, always the business meaning (for example: "the check that made sure a change to your sheet actually went through had gotten out of date after the last update — I've brought it up to date and tested it on a copy"). Ask for their explicit go-ahead the same way next-phase does:

> Here's what needed fixing, and I've proven it works on a copy. Shall I turn it back on?

Capture their answer in their own words — never supply it for them. Once they say yes, run the same acceptance step next-phase's Step 6 uses. The command derives the phase and the copy-run proof path from the capability id, so it is a single line with no file paths to mistype:

```
python3 agents/lib/external_write/operator_acceptance.py --capability-id "<the capability's id>" --operator-confirmation "<the operator's go-ahead, verbatim>"
```

If it reports it could not determine the phase (more than one capability is pending), re-run adding `--phase-id "<its owning phase>"`.

Because this capability keeps the SAME id as the pending entry's `mechanism_id` — this is a rebuild, not a redeclaration — a successful acceptance here closes that entry on its own. You never edit `pending_migrations.json` by hand, and you never need to remember to remove the entry yourself.

If it declines, tell the operator plainly what is not yet satisfied and treat the capability as still not accepted until it succeeds — never claim it is live when the acceptance step refused.

## Step 5 — Confirm it's live and healthy again

Run `capability_health` once more (`python3 agents/lib/external_write/capability_health.py .`) and confirm this capability now reports green, no longer paused and no longer pending a migration. Tell the operator plainly that it is back to normal — what it does, and, if it touches anything that cannot be undone, the same honest terms next-phase uses for that: what can be brought back and how, or that a change genuinely cannot be undone, stated plainly rather than softened.

## Edge cases

| Situation | What to do |
|-----------|-------------|
| No pending entry AND `capability_health` reports this capability green | Tell the operator plainly there is nothing to rebuild. Nothing to fix, nothing to run. |
| More than one pending entry could match what the operator described | Do not guess. Name each candidate in plain language and ask which one. |
| Self-QA (`capability_invariants.py`) will not pass after the repair | Do not proceed to a trial. Tell the operator plainly, from the check's own plain-language message, what still needs fixing, and stay here until it clears. |
| The copy-run trial cannot be carried through to a verified restore | Stop before acceptance. Tell the operator plainly the fix is not proven safe yet; do not offer it as ready. |
| The required predicate cannot be implemented yet | Leave the auto-scaffolded stub raising `NotImplementedError`. A capability that honestly stays paused is correct — never fake a passing check. Tell the operator plainly this one needs more work before it can go live again. |
| The operator declines at the go-ahead | Nothing is turned back on. Tell them plainly the capability stays paused and they can come back to this any time. |
| The acceptance step refuses | Surface its plain-language reason and stop there. Never hand-edit a safety record to force it through. |
