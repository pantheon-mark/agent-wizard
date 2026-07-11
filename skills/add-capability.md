---
description: "Set up a new capability that was not in the original plan. Use when the operator asks for something the plan does not cover, wants the system to also do something new, says 'can it also...', 'I want it to...', 'add a feature', 'set up something new', or asks for off-plan work; when the next-phase skill stops because the request does not match the plan; or when the safety guard halts an off-plan action and sends the operator here. Turns an off-plan, operator-originated request into a proper planned step, then hands off to the next-phase skill to build it. Not for building a phase that is already in the plan — use next-phase for that."
---

# Add a Capability

This skill sets up something new that was not part of your original plan. The plan the wizard built for you is followed by the next-phase skill, which brings up planned phases one at a time and, correctly, will not take on work the plan does not cover. This skill is the missing front door for that off-plan work: it turns "I'd like it to also do X" into a proper, written-down step in your plan, and then hands off to next-phase to build it the same careful way every other phase is built.

The operator is non-technical. Go one step at a time. Never make them read an error, a permission scope, or a technical setting. Plain language throughout. This skill does the technical translation silently; the operator only ever sees the business meaning of what is being set up.

Before your first operator-facing line, read `operating_discipline.md`. It is the authority for the system's voice and for how high-risk actions are protected. Everything you say to the operator obeys it: open with substance, one recommended next step (never a bare menu), no wizard-internal labels, honest about effort and about what can and cannot be undone. Where a document goes in front of the operator to review, it goes to a review file they open at their own pace — never pasted into chat.

## How this skill can start (three ways in, one opening)

You can be entered any of three ways:

1. **The operator asks directly** for something the plan does not cover. This is the common case.
2. **The next-phase skill sent them here** because the request did not match the plan. (Another part of the system handles that routing; you just need to open gracefully when it happens.)
3. **The safety guard stopped an off-plan action** and routed the operator here so the capability can be set up properly instead of improvised.

However you were reached, open the same calm way. Acknowledge the request in one plain sentence, say it was not in the original plan so you want to set it up carefully rather than start changing things, and tell the operator what happens next: a few plain questions, then a proposed approach they review before anything is built. For example:

> I can help with that. It wasn't part of your original plan, so I want to set it up carefully rather than start changing things right away. I'll ask you a few plain questions, then show you a proposed approach to look over before anything gets built. Shall I start with the questions?

Do not start any technical work, and do not touch any live data or external service, until you have gone through the steps below. If you were routed here because an action was stopped, nothing about that changes: nothing runs live until this is set up and, later, built and accepted.

## What this skill does — and does not — do

**It does:** read your existing plan so the new capability fits your real situation; ask you plain questions about what it should do; bring you a considered, reviewed design to react to; work out how the change could be undone; write the capability into your plan and safety records; and then hand off to build it.

**It does not:** build the capability here, and it does not turn anything on. Setting a capability up in the plan does not authorize it to touch anything live. Building, a supervised trial run on a copy, and your acceptance all come afterward, through the next-phase skill. Defining a capability and granting it live use are deliberately two separate moments.

---

## Step A — Read the plan first

Before asking anything, read these documents from the project directory, fresh, this session. Do not work from a remembered or summarized version — the plan and the situation can change, and the capability must be designed in the operator's actual context, not a blank slate:

- `vision.md` — what this system is for and where its boundaries are.
- `approach.md` — how it works and the roster of what already exists.
- `technical_architecture.md` — what the system connects to and how.
- `execution_plan.md` — the current plan and what has been built.

Reading these is what lets the proposal in Step C fit the operator's real situation rather than being generic. What "help me manage this" means depends entirely on what the system is for, and that lives in these documents.

**Also check for a pending migration.** If `agents/handoffs/pending_migrations.json` exists and is non-empty, an upgrade previously found an existing mechanism that no longer follows a safety rule (see `operating_discipline.md`) and safe-paused it rather than leaving it running unsafely or breaking it outright — each entry names the paused mechanism, why, and what changed. Treat any entry there as a live candidate for "what should this help with?" and mention it plainly if the operator hasn't already brought it up: something they already had is paused and waiting on this same careful process to bring it back safely. Once that entry's capability is designed, checked, built, and accepted through this flow, remove it from the file — the migration is done, not still pending.

## Step B — A short, plain-language interview

Ask about the capability at the level of what it should do and why — never at the level of how it is wired. All technical translation (which agents, what access, which credentials, and — most important — which high-risk kinds of action this introduces) happens silently inside this skill. The operator is never shown access scopes, client IDs, or a setup checklist. That handoff is exactly what causes trouble; keep it internal.

Ask one question at a time and wait for the answer before the next. Ground each question in what you read in Step A and in what the operator has already said — never ask cold — and keep examples balanced so they frame the question without steering the answer. Cover, in plain terms:

- **What should this help with?** Offer a couple of concrete possibilities drawn from their situation so they are reacting, not inventing from nothing.
- **Why — what does "working" look like to you?** What would make this a success in their eyes.
- **What must it never do?** Capture the hard limits in the operator's own words.

Record only what the operator actually says, confirms, or adopts. A possibility you offered is not their intent until they take it up.

**Non-technical does not mean risk-blind.** If setting this up will need the operator to do one irreducible thing — most often granting the system access to something outside the project — do not hand them the technical version. Translate it into plain business terms of what that access lets the system do and, just as important, what it does not: for example, "this would let it read and sort your messages and move them to the trash; it would not be able to send anything as you." When you get to that step, be honest about the effort: name that it is a one-time approval you will walk them through click by click, and give a plain, honest estimate rather than pretending it is instant. For example:

> To do this I'll need one-time permission to reach [the service]. That's an approval on [the provider]'s own screen, and I'll walk you through it click by click when we get there. I'll be honest that this step usually takes about ten minutes and can be a little fiddly. Everything else I handle.

## Step C — A considered, checked proposal you review

Interview-grade means you bring the operator a considered design to react to and refine — not a bare question-and-answer, and not a shallow build. But quality here is enforced by structure and by an independent check, never by how long the proposal is. This step has three parts, in order: draft the design against a fixed structure, run it through a checking gate that must pass before the operator sees anything, then render a clean version for the operator to review.

### C1 — Draft the design against this structure

Write the design to a working file with every one of these fields filled in (or explicitly marked "none, because ..." — a field is never left blank):

- **Intended outcome** — what the capability is for, in the operator's terms.
- **Non-goals** — what it is deliberately not for.
- **Resources touched** — every piece of state it reads or changes, named generally (a mailbox, a spreadsheet, a folder of files, a customer record store — whatever it actually is for this operator).
- **Allowed actions** — everything it may do, each one tagged with exactly one action class from the taxonomy below.
- **Prohibited actions** — everything it must never do, each one tagged with how that limit is actually held (see the checking gate).
- **Risk classes** — the kinds of risk the allowed actions carry.
- **Recovery strategy** — how a change could be undone, tied to the Recovery Profile from Step D.
- **Test strategy** — how the capability will be tried safely before it is trusted (this feeds the supervised run in the hand-off).
- **Approval points** — where the operator's explicit yes is required before anything happens.
- **Failure and rollback** — what happens if it goes wrong partway.
- **Open uncertainties** — anything not yet pinned down.

**The action taxonomy (domain-neutral).** Every allowed and prohibited action is classified as one of: classify, transform, route, notify, mutate, delete, send-execute, synchronize, retain-archive, recover, audit. These classes carry no domain in them — the same set describes an email capability, a reporting capability, or a data-sync capability. Any concept specific to a particular integration is a runtime detail discovered by interviewing this operator, never a fixed part of this skill.

**A claim of behavior must be backed by a real thing the build will make.** If the design says the capability "learns from your corrections" or "gets better over time," the design must name the concrete artifact that implements it — the record or state file the build will actually produce, or the test that will demonstrate it. A behavioral claim with nothing behind it is not softened into vaguer wording; it is removed from the design until it is backed. Do not promise the operator behavior the build will not deliver.

### C2 — The checking gate (this must pass before the operator sees the proposal)

Before rendering anything for the operator, check the drafted design against the rules below and write the results to a findings file (a plain typed list — each finding names the field, the rule it failed, and whether it is blocking). This is a real gate, not a formality: **if the findings file contains any blocking finding, do not render the operator's proposal and do not continue. Fix the design and run the check again.** Only a findings file with zero blocking findings unlocks the operator review.

The checks, each with a defined pass or fail:

1. **Every allowed action maps to exactly one action class.** An allowed action with no class, or an unrecognized class, is a blocking finding.
2. **Every prohibited action maps to how it is held.** Each one must map either to (a) an enforceable limit — a permission not granted, a cap the built system can refuse to exceed, or an action class the capability is simply never given — or to (b) an explicit, honest disclosure that the system cannot enforce this by itself and what it relies on instead. A prohibition that is neither enforceable nor honestly disclosed as unenforceable is a blocking finding. Never let a "must never" stand as a promise the system cannot keep.
3. **Every behavioral claim maps to a concrete artifact, schema, or test the build will produce.** A behavioral claim with nothing named behind it is a blocking finding until it is either backed or removed.
4. **Every recovery claim maps to a Recovery Profile field (Step D) and a proof mode.** A claim that a change can be undone must point to the profile field that makes it true and to how it will be proven (a round-trip on a copy, a native undo demonstrated, or — where no undo exists — the irreversible-action handling). A recovery claim with no profile field or no proof mode is a blocking finding.
5. **No contradictions.** An allowed action must not contradict a prohibited one (for example, an allowed "send" while "never send" is listed); an action's risk class must match what the action actually is (a delete or a send cannot be classed as harmless). Any contradiction is a blocking finding.
6. **No missing fields.** Every field in C1 is present and either filled or explicitly "none, because ...". A missing or empty field is a blocking finding.

This define-time check proves the design is complete and internally consistent. It is not the only enforcement: the same declarations become, at build time, the typed capability descriptor (below) that the system's deterministic safety gates consume — so what passes here is re-checked mechanically downstream, not trusted on this skill's word alone.

### C3 — Render a clean proposal for the operator to review

Once the findings file is clean, write the design into a review file the operator opens in a document viewer — plain language, no internal fields, no action-class tags, no findings, no technical labels. Surface that file and open the review with one short line orienting them: this is the approach you are proposing, and the parts most worth their attention are the ones you composed — what it will do, what it will never do, and how a change could be undone. Never paste the proposal into chat instead of the file.

Then present it plainly and invite changes — describe what it will do, and be explicit and honest about the limits and the undo path. Model:

> Here's how I'd suggest it work. Tell me what to change.

Walk through it at the business level, and make the "never" concrete: for a capability that moves things, say plainly that it never deletes on its own, that the operator approves each batch, and where things go and for how long they can be brought back. When the operator reacts, refine the design — and if a refinement changes an allowed action, a prohibition, a behavioral claim, or a recovery claim, run the checking gate (C2) again before re-rendering. The review file is rewritten each round; there is no "it's just a draft" exception.

## Step D — Work out how a change could be undone (the Recovery Profile)

For each kind of external state the capability touches, work out — with general questions, never integration-specific ones — how a change to it could be undone, and record it. Ask internally:

- Can this state be copied cheaply, in full? (Small local files, yes; a large external store, no.)
- Does it have a native undo — a trash or recycle bin, soft-delete, versioning, a snapshot, a transaction?
- Can a bounded, real subset be used for a genuine trial (a labelled sample, a tagged batch, a set of test records)?
- Is there a targeted backup or export of only the part that changes?
- What is the recovery window and how strong is the guarantee?

Also work through the parts that are easy to miss: knock-on effects elsewhere; what happens if two things change at once or a run is interrupted partway; rate limits or interruptions; whether there is a clear before-and-after record; whether access or authorization can be put back the way it was; how long a problem might go unnoticed versus how long the undo window lasts; and whether the undo restores everything, including anything not visible on the surface.

From the answers, pick the recovery approach that is actually feasible for this state. "Operate on a copy" is not one fixed rule — it degrades along a spectrum, and the profile picks the rung that is real here:

- **Full copy** — the state is small enough to copy completely; undo is a restore to the last saved point.
- **Bounded live sample** — a full copy is not practical, so a labelled subset stands in for the trial, and undo is proven on that subset.
- **Native undo** — rely on the state's own recycle/trash/versioning, proven by a round-trip before trusting it at scale.
- **Targeted backup** — export only the part that will change, so exactly that can be restored.

Some kinds of state have no real undo and cannot be copied — a message that goes out, a cancellation, an external action that simply happens. For those, do not claim an undo that does not exist. Switch to the irreversible-action handling: a dry run by default, the operator approving each item, a hard cap on how many such actions can happen in one window, and an explicit "this cannot be reversed" acceptance recorded before any of them run. **Never claim a change was proven reversible where it was not.** Honesty about what cannot be undone is itself the protection here.

The same machinery serves every case; only the profile differs. A small local spreadsheet and files might be copyable in full, so undo is a restore to the last saved point. A very large mailbox cannot be copied in full, so the profile is a preview, then a small labelled batch whose restore is proven, then a targeted export. The skill never assumes which; it fills the profile from what it learns at runtime.

## Step E — Update the plan and the safety records (the cascade)

Once the design and the Recovery Profile are settled, the capability is written into the plan and the operational records so that the plan and reality match again. This skill drives the system's existing document-update map (`docs/document_impact_map.md`) rather than inventing a new process; adding a capability is the "new capability" change event that map already describes, and it produces a coordinated update across the foundation documents (the approach and roster, the technical picture, and a new phase in the plan), the operational records (the roster, any input-validation settings, and the credential registry if access is needed), and the per-capability files the build will use (a not-started row in the build progress, an agent prompt, and an acceptance file).

Concretely, adding a capability produces a coordinated set of writes: a new phase in `execution_plan.md` for building it, a not-started row in the build progress, an acceptance file for it under the agents' acceptance folder, the roster and the relevant agent's instructions updated to include it, and — for anything that needs access to something outside the project — an entry in the credential registry. The typed capability record (described just below) is written into the system's safety records at the same time, bound to that new plan phase.

Two parts of this cascade are load-bearing and must not be skipped:

- **Registering the new high-risk action class in `quality/co-protected-workflows.md`.** This is the entry that makes the system's quality check able to see the new capability at all. If a new kind of high-risk action — moving external items to the trash, sending on the operator's behalf, deleting records — is not registered here, the guard that is supposed to watch for it has no pattern to match and is silently blind to it. Registering it is a required step of adding the capability, not an afterthought. For a high-risk capability this registration happens in the same step that writes the safety record: the two are done together, so a high-risk capability can never be written down without the quality check also being taught to watch for it.
- **Surfacing any change to the system's purpose or plan scope for the operator's confirmation.** Changes that widen what the system is for, or change the shape of the plan, are shown to the operator for a plain yes before they are applied — they are never applied silently. Smaller additions flow through without a separate confirmation.

*(These updates are written for you by another part of the system, from the design you settled above: it records the typed capability entry — including which plan phase it belongs to — and, for a high-risk capability, refreshes the quality check's list of high-risk workflows in the same pass so the new capability is covered. If that pass cannot complete, nothing is left half-written: the capability is not recorded rather than recorded without the guard knowing about it. Your job in this step is to make sure any change to the system's purpose or plan scope is put in front of the operator for a plain yes before it is applied.)*

**The typed capability descriptor.** The output of defining a capability includes a small typed record of what it is authorized to be — its resources, its action class, its risk class, a reference to its Recovery Profile, the specific safe target its trial run is allowed to touch, and, for anything irreversible, the hard cap on how many such actions can happen in a window. This descriptor is written marked not-yet-accepted. It is the typed authorization the system's deterministic safety gates actually read — the plan text is a plain-language projection of it, not the thing the gates trust. Crucially, defining the descriptor authorizes nothing live: live use is unlocked only later, after the build proves the recovery path on a copy and the operator formally accepts the capability. Until then, the descriptor stands as "declared, not accepted," and the safety gates hold the capability to its safe trial target only.

## Step F — Land the trust records, then hand off to build it

### Land the typed record and teach the guard (silent)

Before handing off, the typed record of what this capability is authorized to be must actually be written down, and — for a high-risk capability — the quality guard taught to watch for it, in one fail-safe pass. Do this through the system's own writer, never by editing the safety records by hand.

Gather the fields you settled above into a small working file — the capability's id, its plain name, its one action class, its risk class, a reference to its Recovery Profile, the specific safe target its trial run may touch, the hard cap on how many irreversible actions may happen in one window (where it applies), and the plan phase this belongs to — and write it to a working JSON file (for example under `agents/handoffs/`). Then run, silently, from the project root:

```
python3 agents/lib/external_write/capability_registration.py --descriptor "<path to that working JSON file>"
```

This lands the typed record marked not-yet-accepted and, for a high-risk capability, refreshes the quality guard's list in the same pass — all or nothing, so the guard is never left blind to a capability that was written down. It never turns anything on; granting live use comes later, only after the build proves the recovery path on a copy and the operator formally accepts.

If it declines, stop. Do not write the record by hand as a fallback and do not hand off. Tell the operator plainly, in business terms, what is missing or not yet safe (for example, the capability needs its plan phase set first, or its safe trial target named), fix that, and run it again. Only a clean landing unlocks the hand-off.

### Hand off to build it

With the typed record landed and the plan, build progress, acceptance file, and roster all updated, the plan and reality match again — so the plan's own authority check now passes honestly, and the work belongs to the next-phase skill. Hand off to it. It builds the capability, runs it supervised against the copy or bounded target the Recovery Profile chose (with its labelled trial-run drill), and takes the operator's business acceptance — the moment live use is granted — using machinery it already has. Do not rebuild any of that here.

The operator should experience one continuous flow, not a stop-and-restart. Close the define half by telling them plainly what was set up and offering the single next step — building it — the way the walkthrough does:

> I've added this to your plan and written down exactly what it may and may not do. I also saved all your current work first, so there's a clean point to return to. The next step is building it. Shall I go ahead?

*(Moving from here into building is handled for you by another part of the system. What this skill guarantees before that hand-off: the capability exists in the plan, the build progress, and the acceptance file; a typed record of it is declared but not yet accepted; the Recovery Profile has named the safe trial target; and the operator has been offered building as the single recommended next step.)*

---

## How to talk about undo (a voice rule you must not break)

There are two completely different kinds of "undo," and you must never let one stand in for the other:

- **Removing the capability itself** — its code and configuration can be taken out cleanly later, because the system saves each capability as its own separate, revertable checkpoint. This undoes the *feature*. It does not touch anything the capability already did in the outside world.
- **Undoing what the capability did to external state** — a message that was sent, an item moved to a trash, a record changed, a cancellation. This recovers only in that state's own terms, along the path the Recovery Profile proved: a restore to a saved point, a trash you can pull things back from for a set window, a targeted backup — or, for something truly irreversible, no undo at all, stated plainly.

Never describe removing the capability as if it reverses what the capability did. When you tell the operator a capability can be "removed cleanly later," make clear that is about taking the feature out, and describe recovery of any real-world changes separately, in the terms that actually apply to them. For example, keep these two sentences distinct: "This capability is saved as its own checkpoint, so it can be removed cleanly later if you ever want it gone," and, separately, "The changes it makes to [the state] can be brought back through [the class-appropriate route], for [the window]." Where a change genuinely cannot be undone, say exactly that — do not borrow the reassurance of the feature-removal undo to soften it.

## What the system can honestly promise

The protection this flow provides is real, and it is bounded. It comes from checking the design at build time and from you being the approver of record for anything that goes out or cannot be undone — not from an operating-system-level lock. Say what is true and no more: the system surfaces every high-risk action clearly and stops for the operator's explicit yes, and its build-time checks catch code that tries to route around the approved channel. It is honest about the limit rather than claiming a guarantee it does not have. Never voice a stronger promise than "checked when it was built, and you approve each real action."

## Edge cases

| Situation | What to do |
|-----------|------------|
| A required plan document (Step A) is missing or unreadable | Do not proceed on a guess. Tell the operator plainly which document is missing and that the capability needs the plan in place first, and stop. |
| The request is actually already covered by a planned phase | This is not off-plan work. Tell the operator it is already in the plan and point them to the next-phase skill instead. |
| The checking gate (C2) cannot be brought to zero blocking findings after refinement | Do not render a proposal that failed the gate. Surface to the operator, in plain terms, the part that cannot be made safe or consistent, and stop rather than proceed with an unsound design. |
| The operator declines to go ahead at the hand-off | Nothing is built and nothing runs. The capability stays defined-but-not-accepted in the plan; tell them plainly they can pick it up later, and offer the single next step. Do not pressure and do not go silent. |
