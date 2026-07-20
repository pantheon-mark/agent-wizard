---
description: "Build the next phase, start the next phase, bring up the next phase, continue building after a phase is accepted, run the next group of agents, proceed to the next build step. Use after a phase is accepted (or provisionally-accepted with its precondition cleared) and the operator is ready to build more."
---

# Next Phase

This skill builds and operates the next phase of your system, one phase at a time. Each phase adds a new capability on top of what you have already accepted. The wizard set up the plan; this skill follows it.

The operator is non-technical. Go one step at a time. Never make them read an error or guess. Plain language throughout.

## What this skill reads

Before doing anything, read these files from the project directory. Read them fresh every time. Do not rely on a remembered or summarized version from a prior session -- the plan and the architecture can change, and the skill must follow the current state of these files, not a recalled one:

- `execution_plan.md` -- the build order and what each phase covers
- `approach.md` -- how the system works and why
- `technical_architecture.md` -- what the agents connect to and how
- `build_progress.md` -- which phases are already accepted

Then, once you have identified the next unbuilt phase, read:

- `agents/acceptance/phase_NN_acceptance.md` (the acceptance file for that phase, where NN is the phase number) -- the operator questions for this specific phase

Read all of these now, before any other step.

## Step 1: Check whether the prior phase is accepted

Read `build_progress.md`. Find the phase just before the one you are about to build. Check its State column.

**Do not start the next phase unless one of these is true:**

- The prior phase shows `accepted`.
- The prior phase shows `provisionally-accepted` AND the "Deferred core precondition" column for that phase is now cleared (the deferred check has been exercised on real work).

If neither is true, stop here. Tell the operator plainly:

> The prior phase is not fully accepted yet. Before starting the next phase, run the prior phase on real work and complete its acceptance walkthrough. Come back to this skill once `build_progress.md` shows `accepted` (or `provisionally-accepted` with its deferred precondition cleared) for that phase.

This is a real check. It is not a hard system lock -- it is a guardrail to make sure you are not building on an unconfirmed foundation.

## Step 2: Identify the next unbuilt phase

Read `execution_plan.md` and find the first phase in the build order that does not have a row in `build_progress.md` showing `accepted` or `provisionally-accepted`. That is the phase you are building now.

State plainly to the operator: which phase this is, what capability it adds, and which agents are involved (one or two sentences from `execution_plan.md` -- no architecture details).

### If the request is for something the plan does not cover

If the operator is asking you to build or bring up something that `execution_plan.md` does not describe anywhere -- a new capability the plan simply never had, not a build-order mismatch -- this is not a broken plan to send back to the wizard. It is a new, off-plan request, and it has a proper front door. Do not dead-end here. Tell the operator plainly and route them there:

> This isn't in your plan yet -- let's set it up properly.

Then hand off to the add-capability skill. Do not attempt to define, scope, or design the new capability yourself here -- that is entirely add-capability's job; your role is only to recognize that the request is off-plan and route it. Once add-capability has written the capability into the plan, the plan and reality match again, so this skill's own check above passes honestly and you build it the same careful way as every other phase, next time you are asked to continue.

### If the plan itself no longer matches what has been built

If, instead, you open `execution_plan.md` and find that the phases, agent names, or scope described there no longer match what `build_progress.md` shows as already built or accepted -- a genuine drift between the plan and reality, not a new request -- do not improvise a fix. Stop and tell the operator:

> The build plan in `execution_plan.md` no longer matches what has already been built. This skill brings up phases as they were planned. It does not redesign the plan. To continue, either re-run the wizard to produce a new plan that reflects what you want to build, or use the system's upgrade flow if one has been set up. Come back to this skill after the plan is updated.

Do not attempt to reconcile or re-architect mid-session. The plan is the authority.

### Finding this phase's pending capability entry (used throughout this skill)

Several steps below need this phase's capability `id` and `phase_id` from
`security/capability_descriptors.json` -- the deterministic self-check (Step 4), the
copy-run-proof recording (Step 5), and the acceptance command (Step 6) all point back
to this lookup rather than repeating it.

Read `security/capability_descriptors.json` yourself, directly, with your own
file-reading tool -- never by piping it through a shell filter, and never through
any other shell command (never `cat ... | jq`, `| grep`, or a one-off script of your
own). It is a JSON array of capability entries. Find the one entry whose `accepted`
is still `false` and that matches the phase you identified in Step 2 -- by its
`phase_id` where that is already set, or otherwise by matching its description to
the capability this phase adds. That entry's `id` and `phase_id` fields are the two
values every step below fills in. You do not need a shell command at all to do this
-- read the file and reason over it directly.

If no entry matches -- there is nothing pending for this phase -- do not guess, and
do not run anything that could fail with a raw error on empty input. Stop and tell
the operator plainly:

> This phase doesn't have a capability recorded yet in your project's safety
> records. Before I can continue, this needs to be set up properly. Re-run the
> add-capability skill for this phase (or check with whoever set up your project if
> this is unexpected), then come back here.

**If more than one entry has `accepted` still `false`:** do not guess, and never
silently pick one -- even if one looks like the obvious match. This id feeds
directly into the step that turns on live use of a real capability later in this
skill, and picking the wrong one would authorize the wrong thing to go live. Only
proceed on your own judgment if exactly one of the not-yet-accepted entries clearly
matches the phase you identified in Step 2 (by its `phase_id` or its description)
and none of the others plausibly could. If you cannot tell which one this phase
built -- more than one plausibly matches, or you are not sure -- stop here and ask
the operator directly, by name, in plain language:

> I found more than one capability waiting to be confirmed in your project's safety
> records: <name each candidate in plain language -- what it does, not its internal
> id>. Which one is this phase? I don't want to guess, because picking the wrong one
> would turn on the wrong capability.

Use exactly the one the operator names, and do not continue until they have told
you. Never proceed past this point on a guess.

## Step 3: Credential check

Read `security/credentials_registry.md`. If any credential needed by this phase's agents has `Status: Pending`, do not run the phase yet.

Tell the operator:

> Before running this phase, one or more credentials need to be set up. Run the Credential Setup skill, then come back here.

Once all credentials the phase needs are in place, continue.

### Live-trial-readiness gate (offline scope-preflight — blocks the trial, never the build)

This is the pre-live-trial checkpoint: it is checked here, in Step 3, because this is the last gate before the build-and-run steps below — nothing past this point should discover a missing scope for the first time by trying it live. It gates ONLY Step 5's supervised trial (and, downstream, live authorization) — it never blocks Steps 1–4, and it never blocks this phase's build.

For each credential this phase's agents actually use that carries a `Declared scope` other than `N/A` in `security/credentials_registry.md`, check that credential's `Scope status` column:

- **`verified` or `granted, not yet exercised`:** this scope is ready. Continue.
- **`N/A`, `(set at runtime)` never having been checked, or `not granted`:** this scope is NOT confirmed ready. Do the following:
  1. Run the Credential Setup skill's Step 4 offline check for this exact credential (re-running the same `python3 agents/lib/external_write/adapters.py --op-kind ... --token-info-json ...` check) to get its current, real state — never rely on a stale registry cell without re-checking.
  2. If it now reports `granted, not yet exercised` or better, the registry was stale — update it and continue with this phase normally.
  3. If it still reports `not_granted` (or `n/a` for a credential this phase genuinely needs a scope for), the phase may still be BUILT — you continue through Steps 4 (technical verification / bringing the agents to a runnable state) as normal — but its Step 5 supervised trial and everything downstream of it (the drill, the copy-run proof, business acceptance, live authorization) are withheld. Add an entry to `/work/stub_tracker.md` (Type: `Credential`) naming: the exact dependency and declared scope, the current grant state (`not granted`), the ONE validation command from Credential Setup Step 4 to re-check it, and that this phase's live trial is what depends on it. Tell the operator plainly:

     > This phase is built and ready, but before I can run it live against your real [dependency name], one credential's permission ([declared scope, plain language]) isn't confirmed yet. Nothing else is affected — the rest of your system stays exactly as it is. Run the Credential Setup skill to fix this one credential, then come back and run this phase again — I'll re-check automatically and pick up right where we left off.
  4. Do NOT begin Step 5 (the supervised live/copy trial) for this phase until the stub above is cleared, and do NOT treat this as a reason to fail or roll back the build itself — the phase's code stays built and intact; only its live trial and downstream live authorization are withheld. Steps 1–4 are never blocked by this gate.

This check reads the registry only — it does not itself call any provider. If a credential's `Scope status` cell looks stale (e.g. it was last checked before a scope was re-granted), re-run Credential Setup's Step 4 rather than trusting the cell blindly.

## Clean baseline before building (do this before Step 4)

Before you build anything, make sure there is a clean, committed baseline to fall back to.
Building on top of a pile of uncommitted changes means that if this phase goes wrong, there
is no single clean point to revert to — the safety net that makes this reversible depends on
a clean starting commit.

Check the working tree: run `git status --porcelain`. If it reports nothing, the tree is
clean — continue to Step 4. If it reports uncommitted changes, do not start building yet.
First resolve them: commit the ones that are real code/docs/state (never data or secrets —
see `security/gitignore_manifest.md`), or set aside anything that is genuinely
work-in-progress, so the tree is clean before this phase begins. Only then continue.

## Step 4: Technical verification (silent)

Read each agent prompt file for this phase at `agents/prompts/<agent>_prompt.md`. Verify each one is complete and consistent with the live foundation docs: the roster and approach in `approach.md`, the orchestration model and integrations in `technical_architecture.md`, and the autonomy boundary in `execution_plan.md`. If anything is missing or misaligned, fix it before running.

Some `technical_architecture.md` sections are intentionally reserved and say so ("Your system does not use this section ... Leave this section as is"). Those are not gaps -- do not populate them or treat them as inconsistencies. Verify only against the populated sections.

Do not surface the technical details to the operator -- bring the agents to a runnable state quietly.

### What this capability's own test should (and should not) cover

When you write or update this capability's own test file, keep it scoped to what this
capability itself is responsible for: its own logic, its own declared operation, its own real
acceptance/gate entrypoint. Two things are NOT this capability's own test's job:

- **Whether a paused mechanism is refused.** The write gate (the one entrypoint every gated
  write already routes through) refuses any op_kind that a pause marker names, and that
  refusal is already proven by the gate's own test suite -- once, for every capability, not
  once per capability. Do not add a test to this capability that asserts the gate refuses it
  while paused. If you do, that test's pass/fail will depend on this project's OWN real
  `.wizard/paused-mechanisms/` state at whatever moment the test happens to run -- green today,
  silently red tomorrow once the operator re-accepts this very capability and the pause marker
  is cleared -- even though nothing about the capability's own correctness changed. That is not
  a real regression signal; it is exactly the kind of test that must not exist.
- **Any other lifecycle-phase-dependent state that isn't this capability's own.** The same
  rule holds for anything else that reads the project's real, ambient, changes-over-time state
  (a pending-migration queue entry, an acceptance record, and so on) rather than something the
  test itself sets up.

If a test genuinely needs to exercise paused/lifecycle-dependent behavior (rare -- most
capabilities never need to), it must do so hermetically, never against the real project state:
import `hermetic_paused_mechanisms` from `external_write.lifecycle_test_fixtures` and pass its
returned temporary directory as the write gate's `paused_root=` argument. That gives the test
its own throwaway pause state, so its outcome never depends on this project's real, changing
lifecycle state. The deterministic self-check below (Step 4's next subsection) will flag, and
send you back here to fix, any test that skips this and reads or writes the project's own
pause-marker path directly.

### Deterministic self-check (silent, fail-closed before Step 5)

Once this phase's agents are at a runnable state, run this exact check for the phase's capability, silently, from the project root, before doing anything else in this step:

```
python3 agents/lib/external_write/capability_invariants.py . "<the capability's id from security/capability_descriptors.json>"
```

Get the capability's id using the lookup in "Finding this phase's pending capability entry" above (Step 2). This command runs a set of plain, deterministic checks against the capability's own code and its own tests: whether it is wired correctly, whether its identity is consistent, and whether its own tests actually prove anything (rather than always passing no matter what the code does). It never asks a model to judge any of this -- it is a fixed check, run the same way every time.

This command exits with `0` when every check passes, and a non-zero exit code when any check does not. Do not surface the command, its output, or any technical detail to the operator -- run it silently and act only on the result:

- **If it exits `0`:** every check passed. Continue to Step 5.
- **If it exits non-zero:** do NOT continue to Step 5. Stop here and tell the operator plainly, in your own words from the command's plain-language message -- never the raw output, and never a traceback:

  > This isn't ready to trial yet -- <the plain-language reason>. Next: <the plain-language fix>. I'll re-run this check once that's fixed.

  Fix the issue if you can in this session, then re-run the same command. Only move on to Step 5 once it exits `0`.

## Step 5: Supervised run against a copy

Set up a copy or dummy version of any external state the agents in this phase will write to (for example, a copy of any external data the phase writes to -- the goal is that the first run never touches the live version of anything that cannot be undone from git). External state is not git-revertable. Run the agents with the operator present.

Narrate what each agent is doing and why as it runs, in plain terms. The operator should understand what is happening without needing to interpret logs.

Any high-risk action during the run follows the protective sequence in `operating_discipline.md` (back up, confirm real state, plan, get approval, verify afterward).

During the run, inject one clearly labelled, inert dummy Tier-1 action. Use it exactly once per phase, early in the run, and label it unmistakably so the operator never thinks a real action was attempted.

The action you name in the drill must be one the agents in THIS phase are actually configured to perform. Before writing the drill, check this phase's agents -- the roster plus each agent's prompt file (its declared actions and its output profile) -- and pick a REAL irreversible or outbound action one of them actually does: something that goes out in the operator's name (a message, an email, a post, a write to an external system) or that cannot be undone from git. Name THAT action. Do not invent an action no agent in this phase performs, and do not borrow an example from another project or domain.

If NO agent in this phase performs any irreversible or outbound action -- for example a research or helper agent that only reads and saves findings to the operator's own files -- do not invent one. Say plainly that the work is low-risk, and demonstrate the approval prompt hypothetically:

> [DRILL -- NOT A REAL ACTION] I am pausing to show you how approval works. The work in this phase only saves to your own files and changes nothing that can't be undone, so it is low-risk. But so you can see the guardrail: if I were ever about to do something that goes out in your name or cannot be undone, I would stop and need your explicit sign-off first. This is a drill. No action was taken. Please type "continue drill" to proceed.

When the phase DOES include a real irreversible or outbound action, name it:

> [DRILL -- NOT A REAL ACTION] I am pausing to show you how approval works. In a real run, before <the real action, named from this phase's agents> I would stop and need your explicit sign-off first. This is a drill. No action was taken. Please type "continue drill" to proceed.

The drill must be unmistakably labelled. Its purpose is to demonstrate the guardrail once, visibly, before the operator accepts the phase.

### Recording the trial as proof (silent — only when this phase writes to external state)

If this phase introduces a capability that writes to external state that is not undoable from git — anything the safety records mark as needing live authorization — the supervised trial is not just narrated, it is recorded, because the operator's acceptance later depends on a real, checked trial having happened.

During the copy run, carry the change all the way through on the copy: make the change, undo it, and independently confirm the copy came back to exactly its starting state (apply → undo → verify-restored). Record that trial as the capability's copy-run proof at `agents/handoffs/<capability_id>.copy_run_proof.json`, and record inside it the id of the exact capability it proves — a proof stands only for the one capability it was run for, never for a similar one. Get the capability's id and its owning phase using the lookup in "Finding this phase's pending capability entry" (Step 2). Do not surface any of this to the operator; it is the evidence the acceptance step checks, not something they read.

If the copy run cannot be carried through to a verified restore, do not proceed to acceptance. Tell the operator plainly, in business terms, that the trial did not come back cleanly and the capability is not ready to be turned on, and stop.

## Step 6: Business acceptance

Read `agents/acceptance/phase_NN_acceptance.md` (the file for this phase). Walk the operator through each question in that file. Do not re-list or rephrase the questions here -- read them from the file and follow them. The acceptance file is the single source for what to ask.

Capture the operator's answers as you go.

### If the operator accepts

Capture the operator's acceptance in their own words, exactly as they gave it — do not paraphrase it, and never supply it for them. Their explicit "yes" is what authorizes everything that follows; if they did not clearly say yes, they have not accepted.

**Authorize live use (only for a capability that writes to external state).** If this phase introduced a capability that needs live authorization — the one you recorded a copy-run proof for in Step 5 — the operator's acceptance is the moment it becomes allowed to touch the live version of that external state. Until this moment the safety records hold it to its safe trial target only; turning it on for real is a deliberate, separate act, gated on a real trial having passed and on the operator's explicit yes.

Do this through the system's acceptance step rather than by editing any safety record by hand — hand-editing the record that grants live use is never an acceptable shortcut. Get the capability's id and its owning phase using the lookup in "Finding this phase's pending capability entry" (Step 2), then run, silently, from the project root:

```
python3 agents/lib/external_write/operator_acceptance.py \
  --capability-id "<the capability's id from the Step 2 lookup>" \
  --phase-id "<its owning phase from the Step 2 lookup>" \
  --copy-run-proof "agents/handoffs/<capability_id>.copy_run_proof.json" \
  --operator-confirmation "<the operator's acceptance, verbatim>"
```

This mints the acceptance record from the operator's exact words and runs the one deterministic step that grants live use, but only if every safety condition still holds — the trial proof is valid and belongs to this exact capability, the risk level has not been quietly lowered since the trial, and the phase matches. If it declines, do not claim the capability is live. Tell the operator plainly, in business terms, what is not yet satisfied (for example, the safe trial needs to be re-run), and treat the phase as not accepted until it succeeds. Never present a capability as turned on when the acceptance step refused.

When it succeeds, tell the operator plainly that the capability is now live and what that means for the external state it touches, in the terms that actually apply to it: if a change it makes can be brought back — a restore to a saved point, a trash it can be pulled from for a set window, a targeted backup — say so and say for how long; and where a change genuinely cannot be undone, say exactly that rather than borrowing reassurance from the fact that the capability itself can be removed later. Removing the capability is a separate thing from undoing what it did; never let one stand in for the other.

Record the verdict to `build_progress.md` with today's date and a one-sentence summary of what was accepted. Set the State column to `accepted`, Layer-A and Layer-B to their verdicts.

**Commit this phase as its own revertable unit.** Once the phase is accepted, commit its work as a single, self-contained commit — the code, docs, and state this phase produced (never data or secrets — see `security/gitignore_manifest.md`), with a message naming the phase, for example `Phase NN accepted: <one-line capability>`. Keeping each accepted capability in its own commit means any one phase can be reverted cleanly on its own without unwinding the others. Do not let one commit blend two phases' work together.

Tell the operator plainly: this phase is done. If there are more phases in `execution_plan.md`, let them know they can run this skill again when they are ready to continue.

### If the operator provisionally accepts (a core check was deferred)

Record the verdict to `build_progress.md`: State = `provisionally-accepted`, with the deferred core check recorded in the "Deferred core precondition" column. This phase is usable. When the operator does have real work to exercise the deferred check, they run this skill for the next phase -- and Step 1 of that run will confirm the precondition has been cleared before continuing.

### If the operator does not accept

Note what needs to change. Fix it in this session if possible, then re-run the supervised cycle (Step 5) before asking again. Do not move to the next phase until this one is accepted.

### The defer option

The acceptance file includes a "If you can't try this yet" section. If the operator has no real work to exercise this phase's capability on yet, follow those instructions. Non-core deferred checks are recorded for later and revisited at first real use. Core deferred checks make the phase provisionally-accepted (see above).
