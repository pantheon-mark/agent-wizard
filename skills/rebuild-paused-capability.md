---
description: "Rebuild an existing capability that a contract-changing upgrade paused and queued for migration. Use when `agents/handoffs/pending_migrations.json` has a pending entry, when a `capability_health` check reports a capability red because it is paused or waiting on a pending migration, when the operator asks why something stopped working after an update or says 'it says this needs to be rebuilt', or when the add-capability or next-phase skill hands off here because the request is a paused-capability rebuild rather than something new. Not for setting up a capability that never existed before — use add-capability for that. Not for bringing up a phase already in the plan — use next-phase for that."
---

# Rebuild a Paused Capability

One of the operator's existing capabilities is switched off and queued, and this skill is the one, guided path back. Entries arrive here for more than one reason — an upgrade found the capability no longer matches a safety rule and safe-paused it; its code changed after it was approved; or the operator took their own approval back. **The entry says which, in its `kind` field, and that is what decides what happens next.** Not all of them need a repair: some need nothing changed at all, only a fresh proof and a fresh go-ahead. What this skill never does is redesign what the capability is for. What it always does is prove the capability works before anything runs live again, and get the operator's go-ahead.

The operator is non-technical. Go one step at a time. Never make them read a raw error message or a technical setting — translate everything into plain business terms. This skill does not ask the operator what the capability should do, why it matters, or what it must never do — none of that changed. It only asks for the one thing only the operator can give: their go-ahead once the repair is proven safe.

## What this skill does — and does not — do

**It does:** find the exact capability and the exact thing that changed; make the one repair that entry calls for; prove the repair on a copy; walk the operator through accepting it live again; confirm the capability is healthy afterward.

**It does not:** run an interview about what the capability is for, redesign its scope, or change its business purpose. If the operator wants something genuinely new added, that is add-capability's job, not this one.

## Step 1 — Find what's paused and why

Read `agents/handoffs/pending_migrations.json`. It is a JSON array; each entry names the paused capability (`mechanism_id`), why it was paused (`reason`), what an upgrade changed (`from_version`/`to_version`), and what to do about it (`suggested_next_step`). Find the entry that matches what the operator is asking about.

- **If the operator named the capability plainly** ("the thing that sorts my inbox," "the sheet updater"), match it to the entry whose `mechanism_id` corresponds to that capability — check `security/capability_descriptors.json` if the plain name doesn't obviously match an id.
- **If more than one entry could plausibly be what the operator means**, do not guess — name each candidate in plain language and ask which one, the same way next-phase does before touching anything that turns on live use.
- **Also check `capability_health`** (`python3 agents/lib/external_write/capability_health.py . --overall`, run silently) even when a queue entry exists — it is the same deterministic check add-capability's own Step A runs, and it can catch a capability the queue itself missed (a reconcile pass that ran before this capability existed, or scoped over a different part of the project). Treat a `"health": "red"` result with `pending_migration: true` or `paused: true` and no matching queue entry exactly like a queued one.
- **If nothing matches** — no queue entry, and `capability_health` reports this capability green — tell the operator plainly there is nothing to rebuild here, and stop.

Once you have the entry, read its `kind`, its `reason`, and its `suggested_next_step` — that is what actually needs to happen next, not a guess. **If it carries a `kind` you do not recognise, and it names no `writer_relpath`, do not assume it is a code problem.** Tell the operator plainly what the `reason` says, follow the `suggested_next_step`, and if that is not enough to act on, stop and say so rather than repairing something nobody reported broken.

## Step 2 — Make the one repair the entry calls for

The repair is bounded and specific to what changed. Do not touch anything about the capability beyond what the entry names.

**If the entry's `kind` is `missing_evidence_predicates`:** an upgrade added a new required check for how this capability proves a write landed or undid, and the migrator already auto-scaffolded a stub for it that fails on purpose — the entry's `missing_predicates` names which one(s), and `writer_relpath` names the adapter file they live in. Open that file, find the method(s) that currently just raise `NotImplementedError` with a plain-language message, and replace each with a real implementation that actually checks whether the write landed (or undid) — never a stub that only returns `True`, and never anything that merely silences the error. If you cannot implement a real check yet, leave the stub raising `NotImplementedError` rather than fake a passing one: a capability that honestly stays paused is the correct outcome, never a capability that quietly stopped proving anything. This is the only code-authoring this skill ever asks for.

**If the entry's `kind` is `acceptance_repudiated`:** the operator took their own approval back. **Nothing about this capability's code changed, and there may be nothing wrong with it at all** — do not open its files looking for a fault, and do not tell the operator something is broken. There is no repair step for this one: skip straight to Step 3 and prove it again, then Step 4 for a fresh go-ahead. Before you do, check they actually want it back: if they do not, say plainly that leaving it off is a complete answer, and stop — the entry stays, visible, and the capability stays off.

**If the entry's `kind` is `acceptance_stale`:** the capability's code changed after it was approved, so the approval no longer covers what is on disk. This does **not** mean a safety rule was broken and it does not name a specific defect to fix — the entry exists because approval must cover the current code, not because the current code is known bad. Do not invent a repair. Read the `reason`, and if the operator knows what they changed, confirm it is what they intended; then go to Step 3 and prove the capability as it now stands, and Step 4 for a fresh go-ahead.

**If the entry's `kind` is `external_write_gate_violation`, or it carries a `writer_relpath` and `violations` but no `kind` at all** (an older entry of that same family, written before the field existed): the capability's write path needs to be routed through the sanctioned bulk entrypoint instead of writing directly. This is a two-part repair — do BOTH, in this order:

1. **Regenerate the capability's wrapper.** Reuse the same deterministic scaffold add-capability's own Step F already runs — `python3 "${WIZARD_HOME:-$HOME/agent-wizard}/scripts/lib/capability_code_scaffold.py" --spec <spec> --project-root .` (this tool is part of the wizard toolkit and lives in the wizard's own home directory — it is NOT inside this project, and looking for it under `agents/lib/external_write/` will not find it) — but build the spec from this capability's OWN existing descriptor and roster entry (`security/capability_descriptors.json`, `agents/roster.md`), never from a fresh interview: what this capability is for has not changed, only how its write is wired. This regenerates the wrapper module, whose `run_bulk_approved` helper is the canonical, safe shape — it routes the whole approved set through `run_sanctioned_bulk` in one run, with no per-chunk envelope loop.

2. **Rewrite the flagged writer file itself.** The regenerated wrapper is a *different* file from the one that was flagged. The entry names the actual file that needs fixing in its `writer_relpath` — a hand-authored writer that does its own bulk writing by looping and minting a fresh run-envelope for every chunk (`mint_run_envelope`), which is exactly the bypass the pause is about. Open that file (the path in `writer_relpath`) and rewrite its bulk-write path so it goes through the sanctioned `run_sanctioned_bulk` entrypoint — the same shape the regenerated wrapper's `run_bulk_approved` helper shows — and remove the per-chunk `mint_run_envelope` loop entirely. This file is hand-authored, so keep everything else it does (how it decides what to write, how it reads and builds each item) exactly as it is; change only the one thing that was flagged — the bulk-write path. This is the same kind of real-code authoring the missing-check branch above asks for: you are making the one bounded repair the entry calls for, not redesigning the writer. Do not simply regenerate the wrapper and stop — the writer file the entry named must itself end up going through `run_sanctioned_bulk`, or the capability stays paused.

## Step 3 — Prove it

**Enroll any third-party dependency the repair needs (silent, before the proof).** If the writer or its adapter imports a real third-party vendor SDK, enroll it now — before the proof below — the same way next-phase's Step 4 does, so a clean-session proof can import it. Run, silently, from the project root, for each vendor import the repaired code needs:

```
python3 agents/lib/external_write/dependency_enrollment.py --import-name "<the vendor import, e.g. googleapiclient>" --capability-id "<the capability's id>" --project-root .
```

This resolves the import to its real pip package, pins a version, records it in the project's segregated dependency manifest, re-renders `requirements.txt`, and installs it into the project's own `.venv`. It exits `0` when the package is enrolled and installed. If it exits non-zero, read what it printed (commonly no network, or `.venv` not created yet — run `./start-session.sh` once first), fix that, and re-run the same command; do not proceed to the proof until it exits `0` for every vendor import the repaired code needs. Do not hand-edit `requirements.txt` or run `pip install` yourself — always go through this command.

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

If it can't uniquely determine the phase, it never asks you to fix or extend the command yourself — it prints exactly what to do next, always as something you can paste as-is: a plain "nothing to do" message when nothing matches or it's already accepted, a plain data-integrity note (pointing at the upgrade/reconcile step, never at hand-editing) if the same capability is recorded twice, or one complete, ready-to-run command per capability if more than one is currently pending. Read whatever it prints and follow it exactly; never hand-edit or extend the command yourself.

The order here runs the other way round from how it used to. Acceptance does **not** close the pending entry — the entry has to be clear *before* acceptance can even be reached. Once the flagged file genuinely passes the check, the system clears its entry automatically on the next health or reconcile read, and only then will acceptance go through. If acceptance still refuses, that is the system telling you the flagged file is not actually fixed yet — go back and finish the repair rather than trying to force the acceptance. You never edit `pending_migrations.json` by hand.

If the refusal says the file **cannot be fixed automatically and needs a person**, that is a different situation: the flagged file does something no rebuild of ours can rewrite for it (for example, it also sends the operator's daily email or phone alert). Do not pretend to fix it and do not weaken the check. Explain plainly what it does and why it cannot be rewritten automatically, and let the operator decide whether to accept the risk of leaving it as it is — that decision is recorded, stays visible, and is asked again the moment the file changes.

**Only if the operator says yes to that**, record their decision with this one command, run from the project root. Use their answer word for word in place of the last part — never write it for them, and never run this on their behalf without asking:

```
python3 agents/lib/external_write/writer_acknowledgement.py --writer '<the flagged file, exactly as the check named it>' --operator-confirmation '<what you said, word for word>'
```

It exits `0` when the decision is recorded, and `1` with a plain-language reason when it refuses. It refuses for every file except one the safety check has established needs a person — so if it refuses, the file is not in that situation and the answer is the repair above, not this command. Recording the decision does not make the file safe and does not switch anything on; it stops that one file holding up the rest of the system, stays visible in `capability_health`, and comes back the moment the file changes. The refusal you read a moment ago also prints this exact command, so you never have to assemble it yourself.

If it declines, tell the operator plainly what is not yet satisfied and treat the capability as still not accepted until it succeeds — never claim it is live when the acceptance step refused.

## Step 5 — Confirm it's live and healthy again

Run `capability_health` once more (`python3 agents/lib/external_write/capability_health.py . --overall`) and confirm this capability now reports green, no longer paused and no longer pending a migration. Tell the operator plainly that it is back to normal — what it does, and, if it touches anything that cannot be undone, the same honest terms next-phase uses for that: what can be brought back and how, or that a change genuinely cannot be undone, stated plainly rather than softened.

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
