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

### If the plan no longer matches what has been built

If you open `execution_plan.md` and find that the phases, agent names, or scope no longer match what `build_progress.md` shows as already built or accepted, do not improvise a fix. Stop and tell the operator:

> The build plan in `execution_plan.md` no longer matches what has already been built. This skill brings up phases as they were planned. It does not redesign the plan. To continue, either re-run the wizard to produce a new plan that reflects what you want to build, or use the system's upgrade flow if one has been set up. Come back to this skill after the plan is updated.

Do not attempt to reconcile or re-architect mid-session. The plan is the authority.

## Step 3: Credential check

Read `security/credentials_registry.md`. If any credential needed by this phase's agents has `Status: Pending`, do not run the phase yet.

Tell the operator:

> Before running this phase, one or more credentials need to be set up. Run the Credential Setup skill, then come back here.

Once all credentials the phase needs are in place, continue.

## Step 4: Technical verification (silent)

Read each agent prompt file for this phase at `agents/prompts/<agent>_prompt.md`. Verify each one is complete and consistent with the live foundation docs: the roster and approach in `approach.md`, the orchestration model and integrations in `technical_architecture.md`, and the autonomy boundary in `execution_plan.md`. If anything is missing or misaligned, fix it before running.

Some `technical_architecture.md` sections are intentionally reserved and say so ("Your system does not use this section ... Leave this section as is"). Those are not gaps -- do not populate them or treat them as inconsistencies. Verify only against the populated sections.

Do not surface the technical details to the operator -- bring the agents to a runnable state quietly.

## Step 5: Supervised run against a copy

Set up a copy or dummy version of any external state the agents in this phase will write to (for example, a copy of any external data the phase writes to -- the goal is that the first run never touches the live version of anything that cannot be undone from git). External state is not git-revertable. Run the agents with the operator present.

Narrate what each agent is doing and why as it runs, in plain terms. The operator should understand what is happening without needing to interpret logs.

During the run, inject one clearly labelled, inert dummy Tier-1 action, using this exact format:

> [DRILL -- NOT A REAL ACTION] I am pausing here to show you how approval works. In a real run, I would need your sign-off before taking this action: [brief description of what kind of action this is, for example "send this message" or "update this live record"]. This is a drill. No action was taken. Please confirm you see the approval prompt and type "continue drill" to proceed.

The drill must be unmistakably labelled. Its purpose is to demonstrate the guardrail once, visibly, before the operator accepts the phase. Use it exactly once per phase, early in the run.

## Step 6: Business acceptance

Read `agents/acceptance/phase_NN_acceptance.md` (the file for this phase). Walk the operator through each question in that file. Do not re-list or rephrase the questions here -- read them from the file and follow them. The acceptance file is the single source for what to ask.

Capture the operator's answers as you go.

### If the operator accepts

Record the verdict to `build_progress.md` with today's date and a one-sentence summary of what was accepted. Set the State column to `accepted`, Layer-A and Layer-B to their verdicts.

Tell the operator plainly: this phase is done. If there are more phases in `execution_plan.md`, let them know they can run this skill again when they are ready to continue.

### If the operator provisionally accepts (a core check was deferred)

Record the verdict to `build_progress.md`: State = `provisionally-accepted`, with the deferred core check recorded in the "Deferred core precondition" column. This phase is usable. When the operator does have real work to exercise the deferred check, they run this skill for the next phase -- and Step 1 of that run will confirm the precondition has been cleared before continuing.

### If the operator does not accept

Note what needs to change. Fix it in this session if possible, then re-run the supervised cycle (Step 5) before asking again. Do not move to the next phase until this one is accepted.

### The defer option

The acceptance file includes a "If you can't try this yet" section. If the operator has no real work to exercise this phase's capability on yet, follow those instructions. Non-core deferred checks are recorded for later and revisited at first real use. Core deferred checks make the phase provisionally-accepted (see above).
