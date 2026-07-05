# Wizard Changes — Public Release Notes

This file is the canonical public release-notes + provenance manifest for the `wizard/` subtree distributed via the public `pantheon-mark/agent-wizard` repository.

Each entry records:

- A short public-facing change note
- `Source-Meta-Commit:` — the commit SHA in the private build repo at the moment of publication
- The public repo commit SHA after the publication is complete (filled in after subtree push)

Entries appear newest-first.

---

## 2026-07-04 — groundwork for a coming "add a new capability" feature (no operator-facing change yet)

**Public-facing change:** None yet. This publishes the internal safety groundwork for a feature that is still being built: the ability to add a brand-new capability to your system *after* it is already built, with the same care and guardrails as the original build. The groundwork is dormant — nothing about how your system is built or operated changes, and there is no new version to apply. The feature itself, and the version that turns it on, arrive in a later update.

- Behind the scenes, the machinery that will keep a newly-added capability safe was put in place: a plain description of exactly what a new capability may and may not do; a check that refuses to run a risky action against your real data until you have accepted it (a copy or a small test batch goes first); a limit on how much an irreversible action can touch at once; and a save-your-work helper so that "undo" is always real rather than assumed.
- All of it is inactive until the feature ships. Your files, data, rules, credentials, and logs are untouched.

`Source-Meta-Commit:` `cbda1fd` (private build repo) · public repo commit `35e4fa2`

---

## 2026-06-30 — clearer setup and orientation documents (documentation only)

**Public-facing change:** The about and manual documents were rewritten to be clearer and more accurate. This is a documentation update only. Nothing changes about how a system is built or operated, and there is no new version to apply.

- **A rewritten manual** covering the three things you do yourself: installing the tools, the interview, and building your system one capability at a time. It describes what the interview is like and the kinds of things it asks about, notes that you may be offered an optional system update at the start of a session, and gives troubleshooting for the situations most likely to come up while setting up.
- **A rewritten about document** that sets expectations plainly: what this is, what it protects you from, what it asks of you, and what it cannot do yet.
- **A small accuracy fix** in the setup questions: the note about Node.js now correctly says it is only how Claude Code is delivered, not something your finished system runs on.

`Source-Meta-Commit:` `6875073` (private build repo) · public repo commit `abfefb7`

---

## 2026-06-27 — changes your system makes to data outside itself now carry an integrity contract (v0.9.0)

**Public-facing change:** When your system writes back to an outside destination, it now confirms that the write actually did what it was supposed to — through an independent check, not by re-reading its own output. New write logic is proven on a copy of your real data before it is used live, and undo is shown to restore your data before the feature is accepted.

- **Independent confirmation.** After any write to an outside destination, the system confirms the result through a separate, declared route — not by reading what it just wrote. If it cannot check independently, it says so and uses cautious wording instead of claiming success.
- **Copy-run proof before live use.** Before a new write capability is accepted, it must be run on a copy of your real data class, shown to apply and then to undo, with the restoration confirmed. A write phase is not accepted until that proof is recorded.
- **No absolute claims without evidence.** The system does not say "never," "zero," or "proven" about a new capability's effect on your data unless it checked through an independent route and the check passed. Otherwise it tells you exactly what it confirmed, in plain language.
- **Operator contradictions are taken seriously.** If you tell the system something contradicts a check it just reported as fine, it does not reassure you or explain your report away. It pulls fresh ground truth through an independent route and shows you what it finds.

This is a feature addition (`v0.9.0`, operator-explicit as always). Foundation documents are byte-identical to `v0.8.0`. Your own files, data, rules, credentials, and logs are untouched; a backup is taken before anything is applied.

`Source-Meta-Commit:` `84cc910` (private build repo) · public repo commit `dc6ef61`

---

## 2026-06-26 — writes back to outside destinations now go through a checked, approved path (v0.8.0)

**Public-facing change:** If your system sends data back out — to a spreadsheet, a tracker, or another outside service — it now does so through a checked path instead of writing directly. This protects against malformed or unapproved writes leaving your system.

- **Values are checked before they leave.** Each value written to an external destination is validated against the set of values you allow, so an out-of-range or mistyped value is caught before it goes out, not after.
- **Significant writes are proposed and approved.** Before a significant external write happens, your system describes it to you in plain language and records your approval, with a per-write receipt — so nothing meaningful goes out unseen.
- **A build-time check flags anything trying to go around the safe path.** When you build or extend your system, a check scans for any write that bypasses the approved path and stops the step if it finds one.
- **A single audit view of who can write where.** Each agent's permitted write destinations are derived automatically and shown in one audit table.

Systems that do not write back to anything carry none of this — it is added only where it is needed. This is a feature addition (`v0.8.0`, operator-explicit as always). Your own files, data, rules, credentials, and logs are untouched; a backup is taken before anything is applied. Foundation documents are byte-identical to `v0.7.0`.

`Source-Meta-Commit:` `5984ca2` (private build repo) · public repo commit `2b69fd3`

---

## 2026-06-25 — outputs land in a predictable place, and messages are formatted right before they go out (v0.7.0)

**Public-facing change:** Your system now puts its outputs in a consistent, named location and formats them correctly for the channel — email looks like email, SMS is the right length, and significant messages get a check before they are sent.

- **A home for your outputs.** Your deliverables now go into a `deliverables/` folder with a naming convention agreed at setup, so you always know where to look for what the system produced.
- **Built-in output quality guidance.** Your system ships a maintained voice-and-style spec covering tone, technical level, formatting, and channel-specific rendering (email, SMS, digest). Your agents consult it when producing anything you will read or send — so outputs read consistently and look right in the channel they are going to.
- **Design pass before significant messages go out.** A new skill runs before any substantial outbound message — it reads your preferences, checks formatting and organization for the target channel, and returns the message ready to send rather than asking you to review a rough draft.

This is a feature addition (`v0.7.0`, operator-explicit as always). Your own files and customizations are untouched; a backup is taken before anything is applied. Foundation documents are byte-identical to `v0.6.9`.

`Source-Meta-Commit:` `72b9f70` (private build repo) · public repo commit `08a4adc`

---

## 2026-06-24 — updates never trip over "command not found" (v0.6.9)

**Public-facing change:** A small reliability fix so checking for and applying an update never fails with a "command not found" message.

- **Always uses the full path.** When your system checks for or applies an update, it now always runs the update tool by its full path instead of a short name that was sometimes not recognized. The step that occasionally reported "command not found" no longer happens.
- **Optional convenience for you.** If you would like to type just `wizard` in Terminal yourself, there is now an optional one-time setup command (`wizard install-path`); it is documented in the manual and is entirely optional — the system works the same either way.

This is a small fix-only change (`v0.6.9`, operator-explicit as always). Your own files and customizations are untouched; a backup is taken before anything is applied. Foundation documents are byte-identical to `v0.6.8`.

`Source-Meta-Commit:` `44638d8` (private build repo) · public repo commit `5dfd8bd`

---

## 2026-06-24 — one consistent update path (v0.6.8)

**Public-facing change:** A small consistency fix so checking for and applying an update works the same way every time.

- **One clear path.** When an update is available, your system checks it (which already tells you what's new and its recommendation), and once you approve, the assistant applies it for you. A separate preview step that the system's own instructions didn't actually use has been removed, so the flow no longer depends on which instruction the system happened to follow.

This is a small fix-only change (`v0.6.8`, operator-explicit as always). Your own files and customizations are untouched; a backup is taken before anything is applied.

`Source-Meta-Commit:` `6d04776` (private build repo) · public repo commit `pending`

---

## 2026-06-24 — updates are smoother: you keep your choices, and the system does the typing (v0.6.7)

**Public-facing change:** When an update is available you keep the full set of choices, and once you approve one, your system runs it for you instead of asking you to type commands.

- **Your choices come back.** Even if you've asked your system to lead with a single next step, an available update still offers all four options — see what's new, remind me later, skip this version, or not now. "Remind me later" and "skip" are now remembered, so the reminder actually pauses instead of returning every session.
- **The system does the typing.** Once you approve an update, the assistant runs the update commands itself — you no longer have to paste anything into a terminal. It also resolves where the update tool lives, so the command can't fail with "command not found."

This is a small fix-only change (`v0.6.7`, operator-explicit as always). Your own files and customizations are untouched; a backup is taken before anything is applied.

`Source-Meta-Commit:` `3cc28a7` (private build repo) · public repo commit `pending`

---

## 2026-06-24 — you can preview an update before applying it (v0.6.6)

**Public-facing change:** Your system now shows you a read-only preview of exactly what an update would change before anything is applied, and the apply installs exactly what you previewed.

- **Preview first, always.** When an update is available, your system runs a read-only preview that lists what would change and the recommendation — without touching anything. This preview works even when the update tool itself is behind, so it can never wrongly report there is "nothing to show."
- **You apply exactly what you previewed.** After you approve, the apply installs precisely the version you just saw. If the official source happened to move between your preview and your approval, the apply stops and re-previews rather than quietly installing something different.
- **The apply step stays simple.** The command your system runs to apply the update is kept short, so it can't break when pasted into a terminal.

This is a small fix-only change (`v0.6.6`, operator-explicit as always). Your own files and customizations are untouched; a backup is taken before anything is applied.

`Source-Meta-Commit:` `a6bc510` (private build repo) · public repo commit `pending`

---

## 2026-06-24 — your system no longer talks you out of safe updates (v0.6.5)

**Public-facing change:** Fixes the update flow so your system stops discouraging updates that are safe to take. When you ask "what's new?", you now always get a real answer.

- **"What's new?" always has an answer.** Instead of a vague walkthrough, your system now runs the update check and tells you exactly what it found: a plain-language summary of the change, the system's own recommendation, and the one command to apply it. It reports that recommendation rather than inventing its own opinion — and it will never steer you away from a safe fix.
- **A "prerelease" label is not a warning.** Every current version — including the one you already have installed — is labeled "prerelease" while the system stabilizes. Your system will no longer treat that label, or the absence of detailed notes, as a reason to wait.
- **If your update tool is behind, it routes you to the one-step fix.** When the tool that applies updates is older than the version on offer, that is expected — not an error. Your system now sends you straight to the single refresh-and-apply step instead of stalling.

This is a small fix-only change (`v0.6.5`, operator-explicit as always). Your own files and customizations are untouched; a backup is taken before anything is applied.

`Source-Meta-Commit:` `7ba1dbf` (private build repo) · public repo commit `pending`

---

## 2026-06-24 — the safety check no longer interrupts your ordinary edits (v0.6.4)

**Public-facing change:** Fixes a bug where your system's safety check would stop you to approve everyday edits to your own notes and documents — because plain words like "firm" or "High" were being mistaken for risky commands.

- **It now decides by what an action actually does, not by the words you write.** Editing your own files (notes, logs, drafts) never triggers an approval prompt, no matter what they say. The system still pauses — as it always has — before anything that goes out in your name or can't be undone (sending email, writing to a shared sheet, deleting files, calling an outside service).
- **Why this matters for your safety.** A check that interrupts you constantly trains you to click "approve" without reading — so when a genuinely risky action finally appears, it gets waved through too. Making the check quiet on ordinary work is what keeps your attention available for the moments that actually need it.
- **A small note added.** Your operating guide now explains in plain language why "auto" mode still pauses before sending, sharing, or deleting — that pause is intentional and can't be switched off.

This is a small fix-only change (`v0.6.4`, operator-explicit as always). Your own files and customizations are untouched; a backup is taken before anything is applied.

`Source-Meta-Commit:` `5b1213f` (private build repo) · public repo commit `e1a5263`

---

## 2026-06-23 — updating your system is now one safe step (v0.6.3)

**Public-facing change:** When you ask your system to update itself, it now does the whole thing in one safe, operator-approved step — instead of you running two separate commands.

- **One "yes" does it.** Say "update my system," review what would change, and approve. Your system then refreshes the update tool to the exact approved version and applies the update in one go (behind the scenes: `wizard self-upgrade --to <version> --apply`). You no longer have to refresh the tool first as a separate manual step.
- **You approve an exact, verified version.** Before anything is applied, your system records exactly what you approved — the precise published version, down to the specific code commit and the content fingerprints of the update — and refuses to apply anything that doesn't match. If it can't verify the update against the official source, it changes nothing and tells you the status is unknown (never a false "you're up to date").
- **Your data is always protected.** Your task lists, rules, credentials, and logs are never touched; a backup is taken first, and a file you've edited yourself is only ever updated after that backup is made.
- **Two safety details are hardened.** The record of an approved update can no longer be altered (so the "approve one thing, apply exactly that" guarantee holds even if something tries to tamper with it), and the start-of-session "an update is available" notice now checks the same trusted source as the manual check, so the two always agree.

Honest limit (unchanged): this verifies the expected official source, the version lineage, the exact commit, and the content fingerprints — it is **not** a cryptographic signature check.

This is a small additive change (`v0.6.3`, operator-explicit as always). Your own files and customizations are untouched.

`Source-Meta-Commit:` `3eacd9d` (private build repo) · public repo commit `cf1a0ac`

---

## 2026-06-22 — the approval drill now matches what your system actually does (v0.6.2)

**Public-facing change:** When your system demonstrates its one-time approval "drill" before you accept a build phase, the example it uses is now grounded in what *that phase's agents actually do* — it no longer invents an unrelated or off-topic action.

- If a phase's agents perform a real action that goes out in your name or can't be undone, the drill names *that* action.
- If a phase only reads and saves to your own files (low-risk, like a research helper), the drill now says so plainly and shows the approval prompt as a clear "if I ever were to…" example — instead of inventing an action that agent would never take.

This is a small wording/behavior fix (`v0.6.2`, applied with `wizard upgrade --to v0.6.2` — operator-explicit as always). Your own files and customizations are untouched.

`Source-Meta-Commit:` `f8ff0ba` (private build repo) · public repo commit `842845c`

---

## 2026-06-22 — your system can now check for and safely apply its own updates

**Public-facing change:** Your built system can now find out when a newer version is available and, with your explicit OK, apply it — through its own update channel, in plain language. Previously the update machinery worked but your system had no way to reach it.

- **Just ask.** Say "check for updates" (or "update my system") and your system checks and reports in plain words: an update is available (and what it would change), you're already current, or — honestly — it could not check. It will never tell you that you're up to date when it actually could not check.
- **Nothing happens without your OK.** It shows you what an update would change and what is protected, and applies only after you say yes. Your own data — task lists, rules, credentials, logs — is never touched, and a backup is made first.
- **Keeping the update tool itself current is a separate, careful step.** A guarded "update the tool" command refreshes the tool only when you ask: it verifies the update comes from the expected official source, backs the tool up first, can be undone, and only ever touches the tool — never your project. (Honest limit: this verifies the expected origin, version lineage, and integrity — it is not a cryptographic signature check.)
- **The published tool now runs as distributed.** A path issue that prevented the publicly distributed copy from running an upgrade has been fixed.
- **"Check for updates" works from inside your project.** The tool now finds the version list on its own when run from your own project folder (it previously looked in the wrong place and reported, honestly, that it could not check).
- **Your upgrade instructions stay current.** The in-system upgrade guide is refreshed automatically when you upgrade (no more stale version numbers or commands that don't exist), and a new "check for updates" skill is included.

**Operator-facing notes:**

- These additions are part of the `v0.6.1` minor release (operator-explicit; nothing updates on its own).
- Updating the tool itself is the one step that, the very first time, you start by refreshing your copy of the wizard; after that your system can guide it.

`Source-Meta-Commit:` `e0e711d` (private build repo) · public repo commit `f018c8f`

---

## 2026-06-22 — your built system can now receive operating-layer improvements through an upgrade

**Public-facing change:** Until now, an upgrade could only refresh your foundation documents (vision, approach, plan, and the like). It can now also deliver improvements to the *operating layer* of your system — the working instructions, skills, and safety routines that govern how your agents run (for example your `CLAUDE.md`, the operating-discipline doctrine, the orientation and pause skills, and the agent prompt scaffolding). An existing system no longer has to be rebuilt to pick these up.

- **Your edits are still protected.** Operating-layer files you have changed are merged with the new version where they don't overlap, and set aside for your review where they do — never silently overwritten, never with confusing merge markers (the same safety model as foundation-document upgrades).
- **Install-and-go files update cleanly.** Files you aren't expected to edit (skills, helper scripts, settings) adopt the new version directly; if you did edit one, the upgrade pauses and asks you to confirm replacing it.
- **A system built before this capability existed is brought up to date in one step** the first time it upgrades — your credentials, your progress, and your documents are left untouched.
- **Your accumulated knowledge is protected.** The files your system builds up as it runs — your rules library, your source and advisor registries, your validation and protected-workflow settings, your review queue — are now treated as yours: an upgrade never overwrites them, even when you confirm replacing other files. (Previously a confirmed upgrade could have overwritten them.)
- **What this release adds:** a startup version-check that lets your system tell you, in plain language, when an update is available (and route you to apply it); a new "health-check" skill; an addition to the operating-discipline doctrine; and a small refinement to the pause skill.

**Operator-facing notes:**

- This is a minor, additive release (`v0.6.1`). Apply it with `wizard upgrade --to v0.6.1` (it stays operator-explicit; nothing upgrades on its own).
- A detailed per-file upgrade preview ("what changes and why") is included; making your system keep its own upgrade toolkit current is a follow-on refinement in a subsequent release.

`Source-Meta-Commit:` `5cf3c79` (private build repo) · public repo commit `e1b6ecb`

---

## 2026-06-19 — your system now keeps you oriented and protects risky actions

**Public-facing change:** Your system is now clearer about where you are, and more careful before it does anything that can't be undone.

- **It always tells you the next step.** At any point you can type "what now", "I'm stuck", "what's next", "pause", or "resume", and the system tells you in plain language where things stand and the single recommended next thing to do — never a bare menu. It also will not quietly stop while it is waiting on a decision from you (such as accepting a build phase); it says exactly what to type to continue.
- **Pause and resume cleanly.** Say "pause" or "I'm stopping for the day" and the system saves a short note of where you left off, so a later session picks up exactly there.
- **Risky actions get a protective routine.** Before anything that cannot be undone — sending a message, updating live data, a payment, deleting something — the system backs up what it can, checks the real state instead of assuming, tells you the plan, asks your approval, and verifies afterward. It states a fact about your live data or permissions only if it actually checked; otherwise it says so plainly and asks you to confirm it yourself. It writes a small checkpoint before acting, and a built-in check holds the action until that checkpoint is in place.
- **It gets less wordy as it earns your trust — but never less careful.** After it has done a kind of action successfully on your real work a few times, it explains less as it goes. The safety steps (back up, check, your approval, verify) never go away, and it tells you when it starts being briefer.

**Operator-facing notes:**

- Existing built systems gain this the next time they are generated. A system already running can have it added without rebuilding.
- No foundation-document version change ships in this release.

`Source-Meta-Commit:` `dbe7ac7` (private build repo) · public repo commit `7b9cb8a`

---

## 2026-06-17 — upgrades now merge your edits with the new version automatically

**Public-facing change:** When you apply a foundation-document upgrade, the wizard now *combines* a new version's changes with your own edits automatically, as long as the two don't touch the same section. Previously, editing any part of a document meant the whole new version was set aside in the review folder for you to copy across by hand — even when the new version only added a section somewhere else.

Now, when you upgrade an editable document (such as your vision):

- **Non-overlapping changes are merged for you.** If the new version adds or changes one section and you edited a *different* section, the upgrade keeps your section and folds in the new one — in place, with no hand-copying. The result is reported as "merged."
- **Overlapping changes are still kept safe.** If your edit and the new version change the *same* section, the wizard does not guess: it keeps your version exactly as-is and saves the new version (plus a side-by-side comparison) in the `.wizard/upgrade-review/` folder for you to reconcile by hand. Your live file is never overwritten and never contains confusing merge markers.
- **It only merges documents that came from the current version.** If a document was previously set aside for review and not reconciled, the wizard keeps setting it aside (rather than risk merging against the wrong starting point) until you've brought it back in line.
- **A release can switch automatic merging off** for a large, restructuring update, in which case the new versions are saved for review instead — so a major rewrite never gets silently blended into your edits.

**Operator-facing notes:**

- Existing built systems gain this the next time they are generated; there is no action for you to take.
- No foundation-document version change ships to operators in this release (an internal test version was used to validate the upgrade path end to end).

**Source-Meta-Commit:** c6ecaaa
**Public repo commit:** adef69d

## 2026-06-16 — foundation-document upgrades are now repeatable, quieter, and clearer

**Public-facing change:** Running the brand-new upgrade ability end-to-end against a real built system surfaced three rough edges, now fixed before any of this reaches you:

- **You can keep upgrading.** Previously, the first upgrade that set any document aside for your review could leave your system unable to take the *next* upgrade at all — its self-check would refuse from then on. Upgrades are now repeatable: applying one version no longer blocks the one after it.
- **A routine update won't ask you to review documents you never touched.** A new version often bumps an internal version stamp on every document even when the words on the page are identical. The upgrade now compares the actual content, so documents whose wording hasn't changed are updated quietly in place — you're only asked to review a document when its real content changed *and* you had edited it.
- **Clearer status, no jargon.** The upgrade status line now reads `requires_operator_approval` (every upgrade needs your explicit go-ahead) instead of an internal code, and a confusing technical `WARNING:` line that could appear during setup and upgrades — listing internal field names — no longer shows up when nothing is actually wrong.

**Operator-facing notes:**

- Existing built systems pick these improvements up the next time they are generated; there is no action for you to take.
- No foundation-document version change ships to operators in this release (an internal test version was used to validate the upgrade path end to end).

**Source-Meta-Commit:** 5c5ee4e
**Public repo commit:** 3cc81f7

## 2026-06-16 — your built system can now apply foundation-document upgrades (not just detect them) (v0.5.0)

**Public-facing change:** When the wizard releases a newer version of its foundation-document set, your built system could already tell you an upgrade was available and whether you'd edited any of the managed documents — but it could not actually take the upgrade. It can now, with `wizard upgrade --to <version> --apply`. The upgrade is always something you ask for explicitly; nothing upgrades itself in the background.

The upgrade is careful with your work:

- **It never overwrites your edits.** If you've changed one of the managed documents, the upgrade does not touch your live file. Instead it places the new version (and a side-by-side comparison) in a `.wizard/upgrade-review/` folder and tells you where to look, so you can copy across anything you want to keep. Documents you haven't edited get the new version applied cleanly.
- **It checks itself before it changes anything.** Before applying, it re-creates your documents exactly as they were first built and confirms they still match — if anything is out of sync, it refuses and changes nothing. It also takes a full backup of the affected files first, and applies all the changes together or not at all.
- **It only touches the foundation documents** a new version actually changes; your agents, scripts, and other files are left alone.

To make faithful upgrade previews possible, every newly built system now also saves a small local file, `.wizard/replay-capsule.json`, holding the answers you gave during setup so the wizard can show you what a new version of each document would look like *for your system*. This file stays on your machine only (it is git-ignored by default), and the wizard refuses to write it if any of your answers look like a password or key — credentials belong in your `.env` file, never in setup answers.

**Operator-facing notes:**

- Existing built systems gain the replay-capsule file and the upgrade ability the next time they are generated; there is no action for you to take.
- No foundation-document version change ships to operators in this release (a test version was used internally to validate the upgrade path end to end).

**Source-Meta-Commit:** 0c622db
**Public repo commit:** 3d4f04e

## 2026-06-16 — clearer agent-handoff records, a name-collision guard, and honest "reserved section" wording

**Public-facing change:** Three fixes surfaced by running a real built system end to end:

- **Your coordinator now records correctly how each agent's run ended.** Previously, when an agent stopped early on purpose — because it chose to defer work, or hit its usage budget — the run could still be recorded as a plain "completed," hiding the situation from the coordinator. The record of how a run ended is now written once, by the script that ran the agent, from the agent's own report plus whether the run actually succeeded. So "deferred" and "budget reached" are no longer silently turned into "completed," and a crash is always recorded as a failure. The coordinator reads these records to decide what to do next, so the fix restores its ability to continue, escalate, or review as intended.
- **You can't accidentally name one of your helpers after a built-in control agent.** Every system has two built-in agents — an Orchestrator (the coordinator) and a QA agent. If you named one of your own helpers "Orchestrator" or "QA," the wizard now stops and asks you to choose a different name instead of silently overwriting the built-in one. Names that merely resemble these — for example "Coordinator" or "QA Reviewer" — are still allowed.
- **Two reserved sections in `technical_architecture.md` now say plainly that your system doesn't use them.** They used to carry developer-facing "deferred / will be filled in later" wording that read like an unfinished document. They now state, in plain terms, that the real information lives in `approach.md` and `execution_plan.md` (and the agents' own prompt files), that there is nothing for you or the system to add, and that the section should be left as is. The skill that builds each later phase no longer treats these reserved sections as gaps to fill.

**Operator-facing notes:**

- These are correctness and clarity fixes to the systems the wizard builds; nothing you do changes.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** bcdf105
**Public repo commit:** ffa79b3

---

## 2026-06-16 — internal cleanup (no functional change)

**Public-facing change:** Documentation-only hygiene in the wizard's own instructions file (`wizard/CLAUDE.md`): removed two internal build-tracking identifiers from the advisor-consultation rule's provenance notes while preserving the rule and its configuration guidance verbatim. No behavior change for the wizard or any system it builds.

**Operator-facing notes:**

- Nothing you do or receive changes.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 725eec7
**Public repo commit:** f12851c

---

## 2026-06-16 — you now build and run your system one capability at a time, and accept each before building the next (v0.6.0)

**Public-facing change:** The end of the wizard used to hand you a plan to build every agent first and "review each one" before the system started operating. That asked you to judge things only a builder can judge, and it never let you do the one thing that actually matters: watch the system do your real work before you commit to it. This release replaces that with a single build-and-operate loop:

- **Build one capability, run it, accept it, then build the next.** Your system is built in phases (the order is in `execution_plan.md`). For each phase, the system is brought up, run on your real work *while you watch*, and only moves forward once you say the result is right.
- **You run it against a copy first.** Until you have accepted a phase, it runs against a copy or stand-in of your real data (your live spreadsheet, email, and so on are never touched), because those actions cannot be undone. It goes live only after you accept it.
- **You see the guardrails work.** During the supervised run, the system pauses on a clearly-labelled practice action (a drill, never a real action) so you can see it stop and ask for your approval before doing anything significant.
- **You make one acceptance decision per phase.** The system's own technical checks run first, behind the scenes; then you judge the business result using a short, plain-language acceptance checklist for that phase. Your "yes" is what moves the system forward.
- **A progress ledger tracks it.** A new `build_progress.md` file records each phase's status. The system will not start the next phase until the previous one is accepted.
- **New onboarding docs.** `manual.md` is now your Operating Manual ("what you do"), and `how_your_system_works.md` explains "what the system does on its own." A reusable skill drives building each later phase, reading your own living documents each time.

**Operator-facing notes:**

- This is about how you bring your system into operation. What the agents do is unchanged; how you build up to a running system is now performable by a non-technical operator.
- Honest limit: because this is a markdown-and-Claude-Code system, the "don't start the next phase until this one is accepted" rule is a strong guided check, not an unbreakable lock. A future system type could make it a hard block.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** d1929e9
**Public repo commit:** 1096049

---

## 2026-06-15 — your system now launches and runs its agents on the first try

**Public-facing change:** The first time a built system was run for real, it could not start: the session launcher and every agent script passed command-line options the Claude CLI does not accept, so the launcher failed with an "unknown option" error and no agent could run. This release fixes the commands the wizard generates:

- **Session launcher (`start-session.sh`)** now launches cleanly and runs your session at high reasoning effort (it previously passed a setting the CLI doesn't have).
- **Agent scripts** now load each agent's instructions correctly, have the agent read your foundation documents from disk, run from your project folder so file paths resolve, and are allowed to write their working files without stopping for a prompt that no one is there to answer.
- **Each agent's permitted-write list** now covers every place its own instructions tell it to write — its task checkpoints, its handoff notes, and its error/issue logs — not just its output folder. Previously the agent would have been halted by its own safety gate the first time it tried to save a checkpoint.
- **The autonomy level in your system-config file (`project_instructions.md`)** now matches the level set everywhere else and lists, in plain language, what the system may do without asking. Previously it showed a fixed default that could disagree with your actual level, and the "may do without asking" list was blank.

**Operator-facing notes:**

- These are launch-and-run reliability fixes. What your built system *does* is unchanged — it now actually starts and runs its agents.
- The wizard's own release checks now validate every command it generates against the *real* Claude CLI (not a stand-in that accepts anything), confirm each agent's permissions cover everything its instructions require it to write, and confirm the autonomy level is consistent across all of your system's documents — so this class of "passes the wizard's checks but won't run on your machine" problem is caught before release.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 564389e
**Public repo commit:** 2c47963

---

## 2026-06-15 — the closing build prompt now points at your generated agent files

**Public-facing change:** At the very end, the wizard hands you a prompt to start building your first agent. That prompt referred to a file location the system does not actually use and described writing the agent from scratch — but the wizard now generates a complete starting prompt for every agent during the build step. The closing prompt now points at the real generated file (`agents/prompts/<agent>_prompt.md`) and frames your first session as reviewing that agent and bringing it into operation against your foundation documents, rather than authoring it from a blank file. It also creates the build-prompts folder if it is missing, and reads your agent roster from the approach document, where it is the canonical list.

**Operator-facing notes:**

- This affects only the closing handoff. Nothing about your built system changes.
- Internal cleanup also shipped in this release (documentation-comment tidy-up in the wizard's own files); no functional effect.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** a8e4803
**Public repo commit:** e1f1ac9

---

## 2026-06-15 — a reliability fix so building your project at the very end always completes

**Public-facing change:** The final step of the wizard — where it builds your whole project from your interview and writes it to disk — could stop before writing anything the first time it ran end to end on a real interview. A handful of internal setup values the build needs (your system's type, the wizard version, today's date, and whether this is an initial build or a foundation-only build) were not being supplied at that step. The wizard now supplies them automatically at build time, so the final step completes and your project is written. The same fix makes the "foundation documents only" path build correctly too — that choice is now passed explicitly when you build.

**Operator-facing notes:**

- Nothing about your built system changes. This corrects the build step itself so it does not fail at the very end; everything your interview produced is written exactly as before.
- The wizard's own build step now has an end-to-end safety check that runs a full recorded interview all the way through to a built project, so this class of last-step failure is caught before release rather than on your machine.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 3f77292
**Public repo commit:** ac0adc7

---

## 2026-06-11 — a reliability fix (and a small simplification) for how helpers that use outside systems are set up

**Public-facing change:** A fix to how the wizard records each helper (agent) during the architecture step, plus a small simplification to what it asks you. Previously, when the wizard noted that a helper works with an outside system — like keeping a spreadsheet in sync or researching from the web — it could mark that helper in a way that (a) prevented your system from being built at the very end, and (b) asked you to confirm technical capabilities ("needs network access," "needs broad file access") you had no real basis to judge. Now the wizard records only whether a helper runs on a schedule; a helper's connection to an outside system is captured once, in plain language, at the dependencies step. This removes a way the final build step could fail and drops a confusing confirmation.

**Operator-facing notes:**

- Your system behaves the same once built; this corrects an internal mismatch between the interview and the build step, and removes one question you couldn't meaningfully answer.
- The systems your helpers connect to are still captured — at the "System boundaries & external dependencies" step, where you describe each one once.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 085175a
**Public repo commit:** e52d302

---

## 2026-06-11 — clearer money limits, an MVP-and-roadmap view, and lighter reviews near the end

**Public-facing change:** A set of improvements to the final stretch of the interview (the operations and document-review steps):

- **Your spending limits are now shown to you plainly.** From the plan you told it about, the wizard works out how much of your monthly automation allowance this project may use and the point at which it flags a costly operation, and shows you a short summary ("here's how this came out from your setup; adjustable anytime") instead of asking you to approve numbers you have no basis to set. When the month's allowance runs low, the system does what you chose earlier — check with you, wait until next month, or use paid overflow up to your cap.
- **Your execution plan now spells out what comes first versus later.** A new "MVP and Roadmap Boundary" section states plainly what the system delivers first (the smallest version worth trusting), what is in scope but planned for after that (your roadmap), and what is only a possibility for later — and points to your vision document for what is out of scope entirely. The build-phase list and the first-version description are now generated from one source, so they cannot disagree.
- **The plan's work-tracking section is now accurate.** It describes the real files your system uses to track open work and to resume a task it was partway through, replacing an earlier section that referred to a "sprint plan" file the system never actually created.
- **Reviews near the end are lighter and clearer.** The "what it does on its own versus what it checks with you about first" review is now a plain walk-through with a single question, not a permissions table to audit. The technical testing and audit documents are no longer put in front of you to review — they are still generated for your built system, but since there is nothing in them a non-technical operator can meaningfully change, the wizard simply tells you in one line how your system will be tested and how often it re-checks itself against your vision.
- **A reliability fix** so the operations step always completes cleanly regardless of which spending option you chose.

**Operator-facing notes:**

- No foundation-bundle version change in this release.
- The dollar figures the system computes are shown for transparency, not for you to set — you choose the plan and the sharing / overflow behavior; the wizard does the arithmetic.

**Source-Meta-Commit:** 597f0fd
**Public repo commit:** dd3a5fa

---

## 2026-06-10 — your interview now asks about your outside systems once, in plain language

**Public-facing change:** The interview used to ask about the systems you connect to in three separate places — once for logins, once for what it checks coming in, once for what it monitors — so you described the same spreadsheet or service several times, and those lists could drift apart. Now there is a single **"System boundaries & external dependencies"** step: you describe each outside system **once** and say how your system uses it — it takes data in; your system sends out through it (a notification channel, outgoing mail, a sheet it writes back to); its health is watched; and/or it needs a login. Later steps reuse that one list instead of re-asking, and the validation checklist, the monitored-source registry, and the credentials checklist your built system ships with are all generated from it, so they stay consistent with each other. A system you depend on only to send things out (like push notifications) stays on the list even if you choose not to monitor it.

Two interview-experience improvements came with this: the dependency questions are asked in plain language (no internal jargon), and the quality-settings questions are now asked one at a time rather than all at once.

**Operator-facing notes:**

- You describe each outside system once, with the role(s) it plays; the wizard proposes the list from what you've already told it, and you confirm or adjust.
- "Don't monitor this one" narrows how the system treats it — it does not drop it from your setup.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 5929c9b
**Public repo commit:** 02ed9df

---

## 2026-06-10 — credentials: set them up after the build, with the system walking you through each one

**Public-facing change:** The credentials step of the interview is now **capture-only**. It still identifies every credential your system will need and notes what each one is (which service, what type), but it no longer creates files or asks you to paste secrets during the interview. Instead, your built system ships with secrets already protected (an empty, git-ignored `.env`) plus a **credential checklist**, and at first boot a new **credential-setup helper walks you through getting each credential one at a time** — pointing you to the provider's official instructions, telling you exactly where the value goes, verifying it where it can, and stopping to help (or drafting a request to your account admin) if a screen doesn't match or a provider needs admin access. For tricky providers (work email, Google sign-ins) it leads with the provider's current official page rather than guessing at steps that may be out of date.

Two credential-upkeep preferences you set — how many days before expiry to warn you, and how often to re-check credentials that don't expire — now actually drive the built system (previously they were collected but had no effect). The system tracks each credential's expiry and warns you ahead of time, so you never have to track it yourself.

**Operator-facing notes:**

- You now add your credential values at first-boot setup (guided, one at a time), not during the interview.
- Mid-interview, your only credential actions are confirming the credential list and two upkeep preferences.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 5929c9b
**Public repo commit:** 02ed9df

---

## 2026-06-09 — internal: corrected a leftover cost-model reference in an internal test-criteria template (no operator-facing change)

**Public-facing change:** none — an internal, build-side test-criteria template had a single leftover reference to the wizard's previous cost model (a fixed "spend ceiling") in a row about per-agent work budgets. That model was already replaced by the monthly automation-credit model, so the row's wording is now consistent. No effect on what you see, what you do, or the system the wizard builds.

**Operator-facing notes:**

- No operator action required.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 1807a57
**Public repo commit:** a13fdae

---

## 2026-06-09 — internal: derivation-guide citation correctness + test-suite hygiene (no operator-facing change)

**Public-facing change:** none — these are internal correctness and hygiene fixes with no effect on what you see, what you do, or the system the wizard builds.

- For its own records, the wizard tracks how each value in your documents is worked out and which earlier material it draws on. Two of the internal guides that direct this had described citing the wrong kind of reference for a worked-out value — a raw interview question instead of an already-worked-out field — which the wizard's own internal check would reject. That guidance is now correct and consistent across all of the guides.
- An internal test inconsistency was corrected so the wizard's full self-test suite runs in a single standard command.

**Operator-facing notes:**

- No operator action required.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 14a5816
**Public repo commit:** f1ae866

---

## 2026-06-08 — your documents stay consistent when you change an answer; you review a clean draft of each before confirming

**Public-facing change:** Two things got better about how the wizard keeps your documents right.

First, your documents are now kept consistent with each other. Your answers build on each other — your vision shapes your approach, which shapes what your helpers do. If you go back and change an earlier answer, the wizard now works out exactly what that affects later on, brings you each affected item showing what it says now and what it would become, and lets you decide each one: accept it, reword it, decide later, keep the two different on purpose, or stop. It never changes your vision or goals on its own, and it will not build your system while a change that affects how your helpers behave is left undecided. The next-to-last interview step is where any leftover changes get settled.

Second, before you confirm any document, you now reliably see a clean, readable draft of it — the actual document, opened in a viewer — instead of raw internal text or a wall of separate fields. You see the real draft and then confirm it; drafts and re-drafts are always shown the same way.

Also in this release: your approach summary and helper roster are written more completely (every part your answers support is developed, while genuinely brief answers stay brief), some architecture questions that a non-technical operator can't reasonably answer are now worked out and shown to you rather than asked, and the wizard's questions throughout are plainer, grounded in what you already told it, and free of filler and "most people prefer…" nudges.

**Operator-facing notes:**

- No operator action required; these improve the build experience and the consistency of what the wizard produces.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** f23bb3e
**Public repo commit:** 0b1a829

---

## 2026-06-07 — internal: provenance-tag correctness (no operator-facing change)

**Public-facing change:** none — this is an internal correctness fix with no effect on what you see, what you do, or the system the wizard builds. For its own records, the wizard tags how each value in your documents was produced (your own words versus something the wizard worked out for you). One derived value — your plan's included monthly automation credit — was being tagged as if you'd typed it, when the wizard actually looks it up from your plan. That internal tag is now correct.

**Operator-facing notes:**

- No operator action required.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 3e490fe
**Public repo commit:** bc38193

---

## 2026-06-07 — your vision document is written as a narrative, in your system's voice

**Public-facing change:** the vision step now produces a vision document that is genuinely *written for you* — a short narrative in your system's voice that tells the story of what your system is for, drawn from what you told the wizard — rather than your answers slotted flatly under headings. The wizard drafts it from your answers, shows you the rendered document to review, and gives you one round of changes.

- **It stays honest.** It never adds details you didn't give, keeps thin parts thin instead of padding them, and uses a list only where you genuinely have several items.
- **You review it as a document, not raw text.** When the wizard shows you the draft vision, it now opens as a file you can read in a markdown viewer, instead of scrolling raw text in the terminal.
- Your project name and core purpose are still kept exactly as you said them.

**Operator-facing notes:**

- No operator action required.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 9405e2b
**Public repo commit:** 592b72c

---

## 2026-06-07 — vision step restates your existing rules in plain words

**Public-facing change:** in the vision step, when the wizard reminds you of rules you already set, it now restates them in plain words — rather than referring to them by an internal name ("the always-ask rules") or by which earlier step they came from, which assumed you'd be holding the wizard's own labels. The example wording is plainer too.

**Operator-facing notes:**

- No operator action required.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** e145b59
**Public repo commit:** e2bad9a

---

## 2026-06-07 — notifications step builds on what you've told the wizard; shorter alert-channel name; clearer, honest email step

**Public-facing change:** the notifications step is more personal, plainer, and more honest.

- **It builds on what you already said.** Who's involved, your digest rhythm, and the "always ask me first" actions now open from your earlier answers (e.g. "you mentioned a daily summary early, easing to weekly") instead of asking from scratch.
- **Your private alert-channel name is now short enough to type on a phone** — e.g. `estate-a3f8c21d` instead of a long full-project-name string — while staying unique and recognizable.
- **The email step is honest and plain.** It no longer claims to send a test email (it doesn't yet — email sending is set up when your system is built); it simply confirms your address, without technical jargon.
- **Removed a needless nudge** ("most people find that works well").

**Operator-facing notes:**

- No operator action required.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 08dd2d0
**Public repo commit:** 66b35af

---

## 2026-06-07 — clearer "how reversible is the work?" question; removed an inert "second assistant" question

**Public-facing change:** two refinements to the safety questions in the getting-to-know-you step.

- **The reversibility question is now concrete and factual.** Instead of an abstract "how easy is it to undo?" (which read like a preference — and was genuinely hard to answer), it now asks what's actually *true* of the work your system does: are its actions **mostly permanent, a mix, or mostly reversible** — with examples drawn from your own project — and it states plainly what your answer changes (the more permanent, the more the system checks with you before acting). You still choose directly; on this safety setting the wizard does *not* propose an answer for you.
- **Removed a question that didn't do anything yet.** A question asking whether you have a second AI assistant (ChatGPT/Gemini) for reviews has been removed: it didn't yet affect the generated system, and asking it implied the system would use that assistant. It will return — asking the details that actually matter (which assistant and plan) — in the release that builds the review feature it feeds.

**Operator-facing notes:**

- No operator action required.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** a7bc0e7
**Public repo commit:** 3a35423

---

## 2026-06-07 — spending & limits rebuilt around Claude's automation credit; clearer, more reliable "getting to know you" questions

**Public-facing change:** the **Spending and limits** step has been rebuilt to match how Claude actually bills automated work, and several questions in the **getting-to-know-you** step are clearer and more dependable.

- **The money step now matches reality.** From mid-June 2026, the work your system does on its own (scheduled/background runs) draws a **monthly "automation allowance" included with your Claude plan** — separate from your normal interactive use. The wizard now **works out all the dollar figures for you** from your plan; you just make plain choices: which plan you're on, whether this is your only system or one of a few (so it shares the allowance sensibly), and what it should do if it ever uses the allowance up — **wait** until next month, **keep helping when you're around** (no extra cost), or **keep going on its own** (which you cap, and it always warns you before spending). You set an actual dollar figure only at that one real-money point.
- **Corrected plan facts.** Plan prices and limits are now accurate across Pro / Max 5x / Max 20x / Team Standard / Team Premium, and a previous incorrect statement that Team-plan limits are shared across the team has been removed — **Team usage limits are per member.**
- **On a Team plan, turning on paid overflow needs an account admin.** If you're not the billing admin the wizard won't get stuck — it explains this and lets you pick one of the no-extra-cost options instead, noting that an admin can switch it on later.
- **Clearer "getting to know you" questions.** Plain-language wording throughout; questions now draw on what you've already told the wizard (with examples from your own project) while still letting you answer freely. The "how high-stakes is the work" question now leads with what actually matters — could a mistake be costly or hard to undo — rather than only money.
- **A reliability fix:** the short set of questions about how independently the system should act now **always runs**; previously, if you said your project handles no regulated data, the interview could skip past them.
- **The wrap-up now reflects your safety choices.** When the wizard summarizes your preferences, it acknowledges the safety settings you just made and tells you they'll be confirmed — as concrete "ask-first" rules — when it lays out the plan.

**Operator-facing notes:**

- No operator action required. As before, your system is generated into a **staging location for your review** before it becomes a live project.
- A couple of working-style inputs (whether you have a second AI assistant available, and how it could be used) are **recorded now and used in a later release** — they don't yet change a generated file.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** e5a7db2
**Public repo commit:** a7fe298

---

## 2026-05-31 — the wizard now tailors how independently your system works to YOUR preferences

**Public-facing change:** the wizard now asks a short, plain-language set of questions about **how you want to work with your system** and uses your answers to set how much the agent team does on its own versus checks with you first — instead of always falling back to the most cautious "ask me about everything" placeholder. This is the operator-facing half of the setup that earlier releases had stubbed out.

- **A few questions about working style.** Around the user-profile step, the wizard now asks: how hands-on/technical you are; how independently you want the team to act; how easy it is to undo its work; how quickly you're usually available to approve things; how risky the work is (money / regulated / safety vs. day-to-day vs. experimental); and whether you have a second AI assistant available for reviews. The wizard **proposes a sensible answer from what you've already told it** and you confirm or adjust — except the two highest-stakes questions (how risky the work is, and how reversible it is), which ask you to make an **active choice** rather than accept a silent default.
- **Your answers set the team's independence level and its act-on-its-own vs. ask-first policy.** The result is one of three levels — *ask me before each step* / *check in on the bigger moves* / *act on its own* — plus a clear policy for which kinds of work the team handles automatically and which it brings to you first.
- **It only ever gets MORE cautious, never less, than what you asked for.** High-risk work, hard-to-undo work, or a brand-new (not-yet-trusted) system make it more cautious; they can never push it past the independence you chose. Routine housekeeping (keeping documents tidy, session upkeep) always stays automatic, so it is never literally "ask before everything"; and anything touching security, your data, or irreversible actions always asks you first.
- **Less-technical operators get one extra protection:** the system won't take it upon itself to change its own working conventions without asking.
- **Honest record.** The generated system now records that its independence settings came from *your* answers (previously it shipped a provisional placeholder noting your preferences hadn't been captured yet).

**Operator-facing notes:**

- No operator action required for existing setups. As with recent releases, a generated system is produced into a **staging location for your review** before it becomes a live project; these new questions simply appear during the interview.
- Two of the working-style inputs you give — how reachable you are for approvals, and whether you have a second reviewer available — are **recorded now and used in a later release**; they don't yet change a generated file.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** 099a40b
**Public repo commit:** 02ec922

---

## 2026-05-30 — the interview now drives the generator end-to-end (one build path); scheduled runs carry their schedule; plan-type question covers all current plans

**Public-facing change:** the biggest change yet to *how* a system is built, plus two operator-visible fixes. The wizard's **live interview and its deterministic generator are now a single path.** The interview records your answers, derives the foundation-document content in logical groups, **shows you a rendered preview of each group's documents to confirm**, and at the end generates the **complete system through the one generator** in a single pass. The previous end-of-interview "close assembly" (a separate way of building the files) is **retired**. Nothing is written to your project mid-interview — the documents appear at the end, generated from exactly what you confirmed.

- **One build path, confirmed by you.** Foundation documents are no longer written piecemeal during the interview. Each logical group — your vision; your approach + agent roster; how the agents coordinate; what you approve vs. what runs on its own; testing + audit — is derived, **previewed as rendered documents for your confirmation**, and only then locked. The whole system is emitted at the end from your confirmed answers.
- **Resume + edit safety.** An interrupted interview resumes cleanly from disk. If you go back and change an earlier answer that fed a group you had already confirmed, that group is flagged and re-confirmed — so the system is never built on a superseded answer. The final generation **refuses to run** if any confirmed group has gone stale, or if a group recorded answers but was never confirmed.
- **Scheduled runs now carry their schedule.** When an agent is meant to run on a schedule, the generated cron configuration produces a real entry that wakes the **Orchestrator** on your chosen cadence **and tells it which agent's scheduled work is due** — so a scheduled run actually does that work instead of waking with no context. (Scheduled runs invoke the Orchestrator, which routes to the agent; directly scheduling a single agent remains an advanced exception.)
- **Plan-type question now covers every current plan.** The financial step lists **Pro, Max 5x ($100), Max 20x ($200), Team Standard, Team Premium, and Free**, so operators on a Team plan can select their actual plan. Budget calibration is tailored per tier — Team Standard is calibrated like Max 5x, Team Premium like Max 20x.
- **Interview guidance updated** to describe the new record → derive → confirm-by-preview → generate flow.

**Operator-facing notes:**

- No operator action required for existing setups. This is part of the in-progress generation pipeline; a generated system is produced into a **staging location for your review** before it becomes a live project.
- How document correctness is checked: by **your confirmation of the rendered previews** during the interview, plus internal checks that the documents are structurally complete and that your derived answers actually appear in them. A full automatic comparison against the old build path is not available, because that path has been retired.
- No foundation-bundle version change in this release.

**Source-Meta-Commit:** c5cb0b4
**Public repo commit:** ab7a4b1

---

## 2026-05-29 — derivation-mechanism substrate: a derived-record contract + validator + event-sourced replay (internal; no operator-facing change yet)

**Public-facing change:** internal plumbing only — no change to how a generated system looks or behaves yet. The wizard gains the substrate for a **designed, testable derivation mechanism** — the part that will turn your interview answers into the system's foundation-document fields in a repeatable, checkable way. These pieces are **not yet wired into the interview** (that integration arrives in a later release), so there is **no operator action and no behavior change** at this version.

- A **`derived-record` contract** (`wizard/foundation-bundles/v0/contracts/derived-record-contract-v1.json`): enforces the shape + provenance of a derived record — for each field, where it came from, how it was produced, whether it is an operator decision, and whether it has been confirmed — without fixing a closed list of field names.
- **Validation + replay libraries** (`wizard/scripts/lib/derived_record.py`, `derivation_replay.py`): a fail-closed validator plus an event-sourced replay-and-drift mechanism that make the derivation repeatable and let the wizard detect when a re-run would change an earlier answer.

**Operator-facing notes:**

- No operator action required. This is internal substrate; the interview step that uses it — and any operator-visible behavior — arrives in a later release.

**Source-Meta-Commit:** 864fe1b
**Public repo commit:** 60a31d1

---

## 2026-05-29 — generated systems now inherit a base operating scaffold + a curated operating-principles corpus

**Public-facing change:** the wizard's deterministic generator can now emit a complete operator-system layout — not just the foundation documents. A generated project now includes its **base operating scaffold** (the root `CLAUDE.md`, `project_instructions.md` with the resolved model-tier map, `start-session.sh`, and the operational directories `logs/` / `quality/` / `work/` / `docs/` / `security/` / `archive/`), the **agent execution layer** (the orchestrator + QA + specialist prompts and their invocation scripts), and a **curated corpus of inherited operating principles**.

- **Inherited operating principles, single-homed in `quality/rules_library.md`.** A set of operating principles (identified `OP-…`) is installed as structured Rule entries — covering change management, epistemic discipline, contract integrity, decision-making, verification, operator interaction, estimation, controls, and more. Each principle lives in exactly one place; other files (the root `CLAUDE.md`, the agent prompts, the validation-gate config, the audit log) carry a short cross-reference or enforcement pointer back to it rather than a duplicate copy.
- **A `decisions/` decision-record core.** Generated systems ship a decision-record template — with an explicit **Operator actions** field for load-bearing manual steps — plus an index, so the system records its own architectural decisions over time.
- **Model selection stays programmatic.** The generator resolves the model-tier → model mapping into `project_instructions.md` and `start-session.sh`; the operator never has to pick a model by hand.
- **Provisional authority handling, recorded honestly.** Principles that depend on the operator's authority preferences are installed under a conservative, operator-approval-first default. These authority stamps are now recorded directly in the project's `.wizard/manifest.json` (see below), so they can be revisited automatically once the operator's authority profile is captured.
- **A foundation-upgrade manifest, tracking the whole project.** Generated systems now carry a `.wizard/manifest.json` that records every file the system was set up with and its content fingerprint — not just the foundation documents, but the full operating scaffold, agent layer, and inherited principles. This lets the wizard tell which files an operator has customized and protect those edits during a future upgrade. The project also gets a `.wizard/upgrade-policy.yaml` (upgrade preferences; pinned by default), a `.wizard/upgrade-history.log` (append-only), and a `.wizard/UPGRADING.md` guide.
- **A `SESSION_STATE.md` task-state file.** Generated systems ship the current-task-state file the system updates at every session close, so a new session can resume cleanly after an interruption.
- **The foundation documents are now emitted as part of the same one-plan generation.** The six foundation documents (`vision.md`, `approach.md`, `execution_plan.md`, `technical_architecture.md`, `test_cases.md`, `audit_framework.md`) plus the operator-authored `prd.md` stub are emitted at the project root alongside the scaffold, agent layer, corpus, and upgrade scaffold — so one validated plan produces the **complete runnable system** into the staging location in a single pass. The generation is guarded: it refuses to write anything unless the worktree provenance, the source bundle, every required template, and every required document input check out first.

**Operator-facing notes:**

- No operator action required. This is part of the in-progress generation pipeline; the end-to-end generate-and-hand-off flow is still being completed, and a generated system is produced into a staging location for review before it becomes a live project.
- The installed operating principles are designed to be read at session start — the generated `CLAUDE.md` points to them and inlines the few that matter most at the start of every session.
- Foundation upgrades are **plan-only** at this version: the wizard can tell you what a newer foundation bundle would change, but applying changes automatically is not yet available (it arrives in a later release). `.wizard/UPGRADING.md` in the generated project explains how to check for updates.

**Source-Meta-Commit:** 6985d11
**Public repo commit:** a7aa5d2

---

## 2026-05-28 — foundation bundle v0.4.0: technical_architecture template refactor (single-home + cross-reference + extended-info + deferred-state rendering)

**Public-facing change:** foundation bundle releases its first major-breaking schema refactor in the v0.x prerelease series (v0.3.0 → v0.4.0). The `technical_architecture.md` template now follows a **single-home + cross-reference + extended-info + deferred-state rendering** discipline for content that crosses doc boundaries.

- **Two section-schema refactors:** `technical_architecture.agent_roster` removed (canonical home now `approach.md § Agent Roster`); `technical_architecture.permission_boundaries` removed (canonical home now `execution_plan.md § Human-in-the-Loop Map`). Two new sections added: `agent_architecture_detail` + `permission_boundary_architecture`, both with `population_status: deferred` + concrete `undefer_trigger`.
- **Cross-reference convention:** downstream sections start with an italic note containing a **live Markdown link** to the canonical home + a projection description + an extension-purpose statement + a non-duplication assertion. This is the canonical discipline going forward for any field that crosses doc boundaries.
- **Deferred-state rendering:** new sections without populated content carry a fixed deferred-state stub text directly in the template (no placeholder substitution at deferred state). When the `undefer_trigger` fires, a future minor-additive release introduces the corresponding placeholder + flips the section to `populated`.
- **No new placeholders at v0.4.0** — three placeholders REMOVED (`{{AGENT_ROSTER_ROWS}}`, `{{AUTONOMOUS_ACTIONS}}`, `{{ASKS_FIRST_ACTIONS}}`); zero added.
- **Upgrade-plan tier reporting fix:** `wizard upgrade-plan` + `wizard upgrade-check` now correctly report `tier: major-breaking` for v0.3.0 → v0.4.0 by reading the target-owned migration manifest's `class:` field instead of inferring tier from naive semver arithmetic (which would mis-classify a minor-version bump as `minor-additive`).

**Operator-facing notes:**

- No operator action required. Per the foundation-versioning pre-v1 stabilization clause, the v0.3.0 → v0.4.0 migration carries `stabilization_exemption: pre-v1-no-operator-project-dependency` — no operator project depends on v0.3.0, so no operator-project migration runbook is required.
- `wizard upgrade-plan --to v0.4.0` reports the migration as `tier: major-breaking` end-to-end.
- The two NEW deferred sections in `technical_architecture.md` will render as honest stub text describing why the content is not yet captured + when it will be. Operators should NOT author content into these sections at this version.

**Source-Meta-Commit:** d4fbf73
**Public repo commit:** 1599d9b

---

## 2026-05-28 — foundation-bundle upgrade lifecycle: plan-only CLI + drift detection + content-addressed strict-receipt provenance

**Public-facing change:** the wizard ships its first operator-facing upgrade lifecycle: two new CLI commands (`wizard upgrade-check` + `wizard upgrade --to <version> --plan-only` / `wizard upgrade-plan --to <version>`) plus a content-addressed strict-receipt provenance file emitted alongside each foundation bundle. At this release the lifecycle is **plan-only** — the CLI describes what an upgrade would do but does not apply changes. The apply path lands at the next release that ships the per-operator-project state files.

- **Two new CLI commands operationalize what the foundation-versioning policy described.**
  - `wizard upgrade-check` reads an operator project's `.wizard/manifest.json` plus the public bundle registry and reports: available newer versions, per-target upgrade tier, per-managed-file drift status, and the current standing-approval status.
  - `wizard upgrade --to <version> --plan-only` produces a written upgrade plan (planned migration steps, planned drift handling per merge strategy, planned post-validation). `wizard upgrade-plan --to <version>` is the same thing with a tidier subcommand name.
  - At this release **`--plan-only` is mandatory** on `wizard upgrade --to <version>`; calling without it produces a clear error pointing to the next release. The apply path itself ships at the release that adds operator-project state files.
- **Standing auto-approval is disabled at this release.** Every upgrade requires explicit operator approval, including clean patch-mechanical ones. The CLI reports `standing_approval_status: requires_operator_approval`. There is no path by which an upgrade applies without you deciding to apply it; profile-gated standing approval is deferred at v0 and activates in a later release per the documented rules.
- **Hash-based drift detection** runs in **non-destructive planning mode** at this release. The engine reports candidate diffs + plan actions per merge strategy (`three_way` / `operator_review` / `warn_on_drift` / `frozen`) but does not write merged content. The real merge algorithm + write semantics ship at a later release.
- **New `foundation-bundle.provenance.json` ships alongside each foundation bundle.** An 11-field content-addressed strict receipt records what was in the bundle + how it was generated, with a separate `generated_at` timestamp that is metadata-only (not in any content hash) so byte-level reproducibility holds across re-emissions. The receipt also names its own schema_version + hash_algorithm + canonicalization_version so future changes are explicit.
- **JSON sidecars** (`manifest.json` + `migration-manifest.json`) now ship alongside their YAML companions in each `wizard/foundation-bundles/<version>/` directory. The wizard's runtime CLI consumes the JSON; the YAML stays the human-facing copy. No third-party Python dependencies introduced.

**Operator-facing notes:**

- No operator action required at this release. There is no operator-project apply path yet — the upgrade CLI is plan-only.
- If you experiment with the CLI against a test operator project, expect the standing-approval status to show `requires_operator_approval`. `wizard upgrade --to <version>` requires you to choose a mode: `--plan-only` previews the change without touching any files, and `--apply` performs the upgrade (operator-explicit every time). Running it with neither flag stops with a message telling you to pick one.
- No version bump on the policy itself; this is the implementation of the previously-shipped foundation-versioning policy (minor-additive update to the implementation document).

- Source-Meta-Commit: `dafaee0`
- Public repo commit: `64448af`

---

## 2026-05-27 — clearer, more honest execution model for generated multi-agent systems (+ a session-lock fix)

**Public-facing change:** the wizard's generated markdown-agent systems now carry a clearer and more honest description of *how they run*, plus a real fix to the session lock that coordinates them.

- **Coordination model made explicit.** Every generated system has one **Orchestrator** that coordinates the work (selects from the queue, routes work, tracks session state); the **specialist agents** do the domain work. You interact with the work queue and the Claude Code session the Orchestrator runs in — not with individual agents directly. The `technical_architecture.md` template now states this up front.
- **Honest autonomy.** The `execution_plan.md` template now makes clear the system **runs when invoked** — either when you start a Claude Code session, or when a scheduled job starts the Orchestrator on a cadence you set. It is not an always-on background service and does not act while no session is open. "Operating on a cadence" means a scheduled run starts, completes its work, and exits.
- **Session-lock fix (important).** The single session lock (`maintenance_mode.md`) is now owned by the Orchestrator and lives in one place (the project root). Previously a path mismatch — plus a leftover check inside the specialist invocation script — could have caused scheduled or Orchestrator-spawned agent work to be skipped even though the system looked configured. Scheduled jobs now invoke the Orchestrator (which routes to agents); directly scheduling a single agent is an advanced exception. The agent handoff record now always includes a `stop_reason`.
- Default execution is **sequential for tasks that share files** (parallel only when write scopes are clearly separate), to avoid two agents clobbering the same file.

No schema, manifest, placeholder-key, or generated-output *structure* changes — template wording + the invocation script's session-lock handling.

**Operator-facing notes:**

- No operator action required for existing setups. If you regenerate or re-read your foundation docs, you'll see the clearer coordination + autonomy wording. The session-lock fix prevents a "configured but does nothing on schedule" failure mode.
- No version bump (clarifying wording + a corrective fix; no compatibility-affecting structural change).

- Source-Meta-Commit: `9dda645`
- Public repo commit: `8fa6702`

---

## 2026-05-27 — internal documentation hygiene (continued): remaining build-process references removed

**Public-facing change:** a follow-on to the prior hygiene pass that finishes removing short citations to the wizard's *private* build-process design records from the public files. Covered: two interview-step modules, several foundation-bundle docs (a migration manifest, a README, two section schemas, two hash baselines), one generator unit test, and eleven test fixtures. Each citation was either deleted (where the surrounding text already carried the meaning) or replaced with a plain-language description of the rule/behavior it pointed at (e.g. "the foundation-versioning policy", "the validation evidence storage convention"). The build-side reference checker that guards the public files was extended to catch the remaining identifier forms, plus a new advisory (non-blocking) review pass for the few ambiguous forms that can also be legitimate public wording. No code, schema, manifest, template, placeholder-key, or generated-output changes — wording only.

**Operator-facing notes:**

- No operator action required. Wizard behavior and every generated output are unchanged; this only finishes tidying internal references out of the public files.
- No version bump.

- Source-Meta-Commit: `719b5f9`
- Public repo commit: `d13834a`

---

## 2026-05-27 — internal documentation hygiene: removed build-process references from public files

**Public-facing change:** several public wizard files (interview-step modules, the bundle-generator script, and two foundation-bundle docs) carried short citations pointing at the wizard's *private* build-process design records — identifiers that an operator has no access to and does not need. Those citations were removed or replaced with plain-language descriptions of the rule/behavior they pointed at (e.g. "the honest-characterization rule", "the foundation-versioning policy"). No code, schema, manifest, template, placeholder-key, or generated-output changes — wording only.

**Operator-facing notes:**

- No operator action required. Wizard behavior and every generated output are unchanged; this only tidies internal references out of the public files.
- No version bump.

- Source-Meta-Commit: `77e365f`
- Public repo commit: `e506719`

---

## 2026-05-26 — stop-condition test fixture: pre-step-08 late-emergence regulated-data case

**Public-facing change:** one new test fixture is added to the stop-condition re-evaluate-loop fixture set (`test_fixtures/stop_condition_reevaluate_loop/`), covering the case where regulated-data exposure surfaces late (at the pre-architecture re-check) via an advisor the operator added, with the specific framework not yet identified — then resolves to foundation-only mode. No code, schema, manifest, template, or placeholder-key changes; test-fixture content only.

**Operator-facing notes:**

- No operator action required. This is an internal test-coverage addition; it does not change wizard behavior or any generated output.
- No version bump.

- Source-Meta-Commit: `3ad51d4`
- Public repo commit: `3d08afb`

---

## 2026-05-26 — foundation-bundle templates: lifecycle + maintenance completeness

**Public-facing change:** two of the `v0.3.0` foundation-bundle templates gain more complete coverage of system-lifecycle and maintenance topics, surfaced while walking a real-operator-generated bundle. No code, schema, manifest, or placeholder-key changes — template prose only; generated bundles continue to render from the same keys.

- **Audit-framework template:** the autonomy framing is generalized so it applies across every autonomy level rather than implying only a subset is defined; a new **Rules library** section consolidates rule definitions already used elsewhere in the wizard; and a new **System lifecycle** section adds **Maintenance** and **Upgrades** subsections so an operator-facing bundle documents how the system is kept healthy and how it is upgraded over time.
- **Test-cases template:** an introductory note now makes explicit that some test cases reference mechanisms defined in the broader foundation documents (not all mechanisms are defined inside the test file itself), and a new **Test maintenance** section covers how the test suite is maintained and evolved as the system changes.

**Operator-facing notes:**

- No operator action required. These are template-content improvements; operator projects generated from earlier template states are unaffected unless regenerated.
- No version bump (the templates remain part of the `v0.3.0` prerelease bundle); no generator or schema change.

- Source-Meta-Commit: `a6f00c5`
- Public repo commit: `b6c28d4`

---

## 2026-05-22 — foundation-bundle generator first real-operator generation event (structural anonymization)

**Public-facing change:** the wizard distribution exercises the foundation-bundle generator pipeline against real-operator content for the first time. The release ships no code changes to the generator itself (the pipeline is unchanged from the prior `2026-05-22` internal first-generation event); what changes is the addition of a durable real-operator-content fixture under the wizard's test directory, exercising the same generator against operator answers from an actual real-world project rather than synthetic placeholders.

**Honest characterization.** This is a real-operator-content first-capture milestone, NOT operator-fit validation, NOT arms-length operator review, and NOT a stability commitment for v1.0.0 promotion. The operator for this capture is the wizard's primary author (operator role and build-session lead role collapse in this release); arms-length operator validation remains forthcoming.

**Privacy discipline.** All identifying entities in the real-operator content (entity identifiers across multiple categories — people, organizations, accounts, dates, amounts, locations, contact information) are captured using STABLE PLACEHOLDER LABELS rather than real values. The committed fixture preserves the operator content's STRUCTURAL SHAPE (scope / agents / orchestration / autonomy / phases) verbatim while keeping all third-party identifying information out of the distributed artifact. A real-label-to-placeholder mapping file lives on the operator's local disk outside any distributed repository. Operators using the wizard for sensitive content can adopt the same structural-anonymization discipline.

**Operator-facing notes:**

- The same generator pipeline (`wizard/scripts/generate_bundle.py` + `wizard/scripts/lib/generator.py`) is exercised; no version bump, no API change.
- The wizard's `wizard-proposes-user-confirms` operating principle (per `wizard/CLAUDE.md` rule 5) is exercised at both the derivation surface (operator answers → Claude proposes derived content → operator confirms/adjusts) and the review surface (operator reviews generated documents → Claude proposes per-document verdict + surprises → operator confirms/adjusts). Both surfaces are bootstrap-grade (Claude-facilitated, ad-hoc); designed-mechanism implementation of the interview surface is forthcoming in a later release.
- No operator action required at this release. Operator projects produced via earlier paths continue to be unaffected.

- Source-Meta-Commit: `ca22c00`
- Public repo commit: `5f2fe67`

---

## 2026-05-22 — foundation-bundle generator pipeline + first internal generation event

**Public-facing change:** the wizard distribution now includes a foundation-bundle generator pipeline. A new library at `wizard/scripts/lib/generator.py` and a new CLI at `wizard/scripts/generate_bundle.py` together emit an operator-project bundle from a source foundation bundle plus a set of operator inputs supplied as JSON. The first internal generation event used the existing `v0.3.0` prerelease bundle as the source and synthetic placeholder inputs; the run produced seven foundation documents (`vision.md`, `prd.md` as a schema-only stub, `approach.md`, `execution_plan.md`, `technical_architecture.md`, `test_cases.md`, `audit_framework.md`) plus an operator manifest at `.wizard/manifest.yaml` carrying the foundation-bundle version, the source bundle's published commit, and the wizard generator code identity at emission time.

**Honest characterization.** This release is an INTERNAL first-fire milestone. The synthetic inputs do not represent a real operator system, and this release does not constitute operator-fit validation, known-tester recruitment, or a stability commitment. v1.0.0 promotion remains deferred until interview-driven generation and additional shape support (markdown agents, other system shapes) land in subsequent releases.

**Operator-facing notes:**

- The generator is stdlib-only — no Python package installation is required on the operator side to run it.
- The generator emits its operator manifest as deterministic text with a tight field set: `foundation_bundle_version`, `source_commit`, `generator_version`, and a per-file `files:` map carrying `managed:` / `base_hash:` / `current_hash_last_seen:` / `local_modifications:` / `merge_strategy:` per file. Package-side fields stay in the foundation-bundle's own `manifest.yaml`; the operator manifest is deliberately disjoint so downstream validators can detect operator vs. package context unambiguously.
- The wizard generator code identity is recorded automatically at generation time. The generator refuses to emit when the wizard build state is not clean, so the recorded identity always points to a published wizard state. A `--permissive-dirty` flag exists for development use and should not be used to produce v1.0.0+ bundles.
- The `prd.md` template ships as a schema-only stub at this prerelease: the operator authors content for the four canonical sections (Vision Link, Persona / JTBD, Functional Requirements, Non-Functional Requirements) per the section schema shipped at `wizard/foundation-bundles/v0.3.0/schemas/section-schema.yaml`. A full `prd.md` template is deferred to a future release when interview-driven PRD authoring lands.

No operator action required at this release. Operator projects produced via earlier paths continue to be unaffected.

- Source-Meta-Commit: `c37067f`
- Public repo commit: `6de09d7`

---

## 2026-05-21 — foundation-bundle-v0.3.0 prerelease package

**Public-facing change:** first concrete per-version foundation-bundle package activated at `wizard/foundation-bundles/v0.3.0/` with `status: prerelease` in the public registry. The package is self-contained: own `schemas/section-schema.yaml`, `templates/` (six foundation-doc `.md` files: vision, approach, technical_architecture, execution_plan, test_cases, audit_framework), `baselines/` (six per-template hash baselines), `manifest.yaml`, and `migration-manifest.yaml`. Section schema content is unchanged from the prior `v0/` schema-layer state — the package is a new layout/addressability layer over the same schema, not a schema revision.

The wizard's foundation-bundle layout convention is also updated in this release: per-version package directories (`v0.3.0/`, eventually `v1.0.0/`) may exist for pre-v1 prerelease packages as well as stable v1.0.0+ releases, decoupling directory layout from v1.0.0 stability commitment. The `v0/` schema-layer canonical directory continues to track rolling schema migration history. v1.0.0 promotion remains the explicit stability-commitment trigger and is deferred until the wizard's foundation-bundle generator + generator-version-identity mechanism are wired in subsequent releases.

No operator action required at this prerelease — the package is a structural prerelease ahead of the wizard's foundation-bundle generation pipeline going live. Operator projects continue to be unaffected.

- Source-Meta-Commit: `15757c5`
- Public repo commit: `eb3ce61`

---

## 2026-05-20 — Templates root + docs _index.md inventory updates (operator-impact minimal)

**Public-facing change:** two `_index.md` template-inventory files brought current. Specifically: `wizard/templates/root/_index.md` now lists `wizard_feedback.md` (template was already in the directory; the inventory pointer was just stale); `wizard/templates/docs/_index.md` now lists `how_your_system_works.md` (same shape — template existed, inventory was stale). No template content changed; no behavior change for operators running the wizard. This release accompanies build-side standup of operating-doc template variant/readiness policy (build-side governance work; not exposed in this distribution beyond the inventory fixes named above).

- Source-Meta-Commit: `ef84afd`
- Public repo commit: `c919e8a`

---

## 2026-05-20 — Distribution boundary v1 + cumulative interview content updates (since 2026-05-04)

**Public-facing change:** the wizard distribution now ships with cleaner internal language across the interview flow and supporting modules. Build-side provenance references (slice IDs, issue identifiers, internal governance paths) have been removed from operator-facing content; where references were load-bearing for semantic clarity, neutral version IDs (e.g., `foundation-bundle-v0.1`) replace them. This release also adds:

- A new `foundation-bundles/v0/` directory with the canonical `schemas/section-schema.yaml` (machine-readable section schema for the seven foundation doc types, with shape-extension metadata), `migration_manifest.yaml` (target-owned migration manifest stub), `baselines/<template>.hash.yaml` (per-template drift-detection hashes), and `README.md` describing the directory.
- A new `handoff_contracts/shape_detection_v0.md` defining the shape-detection handoff structure that downstream wizard surfaces consume.
- A new `shape_detection.md` canonical implementation spec for the shape-detection module (probe inventory, confidence rubric, lifecycle phases, stop conditions, control matrix).
- New interview helper modules: `_foundation_only_mode_gate.md`, `_pre_step_05_recheck.md`, `_pre_step_08_recheck.md`, `_stop_condition_reevaluate_loop.md`.
- A new `registry/` directory with `foundation-bundles.json` (version index) + README.
- A new `scripts/` directory with `bundle_hash.py` (hash-baseline tool for foundation-bundle drift detection) + supporting library.
- A new `templates/documents/` directory with the foundation-doc templates the wizard uses to generate operator-project artifacts.
- A new `test_fixtures/` directory with synthetic fixtures the wizard's internal validation surfaces exercise (operator-relevant for understanding the foundation-only-mode behavior + stop-condition reevaluate loop).
- Source-Meta-Commit: `9d6299f`
- Public repo commit: `247a264`

This release covers cumulative changes since the prior subtree publication at `2d28da0` (2026-05-19). The intervening build-side work that materialized in this distribution was substantial; the operator-facing summary above focuses on what changes for someone running the wizard.

---

## 2026-05-04 — v0 license + IP posture ratified

**Public-facing change:** added `LICENSE` (MIT, copyright 2026 Mark Tobias), `GENERATED_OUTPUTS.md` (operator's free-use grant for wizard-generated project content), and this `CHANGES.md` (canonical public release-notes + provenance manifest). Closes the prior "all rights reserved" default state for the public repository.

- Source-Meta-Commit: `7703dd7`
- Public repo commit: `bfc327e`

---

## Provenance discipline

- Every change to `wizard/` that reaches the public repo via `git subtree push` should be recorded above.
- The canonical authority is this file; commit messages may copy the same information but never replace it.
- For substantial structural changes, include a public-facing summary only. Do not reference private build-project governance, review records, or local paths.
- This file lives inside the public subtree. Its content is public-readable; treat all entries accordingly.
