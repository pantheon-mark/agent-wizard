# 08 — Architecture

## What this file does
Present the system architecture for user confirmation in five steps: orchestration model, agent roster, criticality tier assignments, permission summary, and task completion checklists. Claude derives all of these from the vision document, approach document, and advisor list — the user confirms and adjusts, but does not design. Produces the technical architecture foundation document.

## When this file runs
After `07_advisors.md` completes and ADVISORS_SEEDED = true in the staging file.

## Prerequisites
APPROACH_CONFIRMED = true and ADVISORS_SEEDED = true in the staging file. Vision document and approach document confirmed on disk.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 08_architecture.md. APPROACH_CONFIRMED = true and ADVISORS_SEEDED = true. Read the vision document, approach document, advisor knowledge base, and staging file at `~/claude-wizard-draft/wizard_session_draft.md`, then begin ARCH-1."

**Important:** The architecture phase involves reading multiple documents and producing a substantial confirmation artifact. Do not begin it unless you are confident the full phase — all five ARCH steps and the disk write — will complete before compaction risk.

---

## How to run this phase

All five steps in this phase follow the same pattern: Claude derives and presents, the user confirms or adjusts. The user is not asked to make architectural decisions — only to confirm that Claude's understanding of their work matches reality. When the user corrects something, update the model and continue.

Maintain a running architecture document internally as each step is confirmed. Write to disk after ARCH-5.

---

## Pre-ARCH — Cross-step conflict detection [INTERNAL]

Before presenting any architecture, compare the user's answers across steps 05 (vision), 06 (approach), and the current architecture context. Look for scope drift or contradictions — for example, a user whose vision describes a full-lifecycle system, whose approach focused on one narrow area, and whose architecture questions suggest yet another direction.

**If the vision scope, approach focus, and implied architecture are aligned:** proceed to ARCH-1 without comment.

**If they suggest different systems:** name the discrepancy in plain language before proceeding. Do not ask the user to reconcile the contradiction themselves — propose the most coherent starting point.

**Say:**

> Before we set up the architecture, I want to flag something I noticed across your earlier answers.
>
> Your vision described [summary of vision scope]. Your approach focused on [summary of approach focus]. And the direction we're heading architecturally would build [summary of implied system].
>
> These aren't necessarily in conflict — but they suggest we should start with [proposed starting point] because [one-sentence rationale]. The other directions aren't lost — they become future agents once the core system is running.
>
> Does that starting point make sense to you?

**Wait for answer.**

- If the user confirms: proceed to ARCH-1 with the confirmed scope as the basis for the agent roster.
- If the user redirects: update your understanding to match their preference and proceed.
- If the user asks what the difference means: explain in plain terms which system each direction would produce and what would be deferred.

This check ensures the architecture is built from a coherent foundation rather than silently inheriting unresolved contradictions from earlier steps.

---

## ARCH-1 — Orchestration model [DYNAMIC]

Before speaking, read the vision document and approach document. Identify:
- Which workflows are independent — tasks that different agents can run without waiting on each other
- Which workflows are dependency-linked — tasks where one agent must finish before another can start

**Do not ask the user to make an architectural call.** Present your reading of how their work flows, and ask them to confirm whether it's accurate.

**Say:**

> Before we go through the agents themselves, I want to show you how they'll be organized.
>
> Based on what you've described, here's how the work will flow:
>
> **[Workflow name or description]:** [Plain-language description — e.g., "These steps can run at the same time — each agent works independently and doesn't need to wait for the others."]
>
> **[Workflow name or description]:** [Plain-language description — e.g., "These steps run in sequence — [Agent A] finishes first, then [Agent B] picks up from where it left off."]
>
> Does that match how you'd expect the work to happen?

**Wait for answer.**

- If the user confirms: note the orchestration model as confirmed and proceed.
- If the user corrects the workflow description: update your model to match, restate the corrected description, confirm, and proceed.
- If the user asks what the difference matters: explain in plain terms — independent workflows run faster because agents work simultaneously; sequential workflows ensure earlier results are available when later steps need them.

The architectural conclusion (whether a scoped orchestrator is needed, which workflows it manages) follows from the confirmed workflow description. Do not present this conclusion to the user — it is an internal implementation detail. The user only confirms the workflow description.

---

## ARCH-2 — Agent roster [DYNAMIC]

Present the proposed agent roster derived from the vision document, approach document, and confirmed orchestration model. The user did not design this roster — Claude did. Present it for genuine review, not rubber-stamp approval.

**Say:**

> Here are the agents your system will need. For each one I'll tell you what it does, why it exists, and what would break without it.
>
> **[Agent name]**
> [One sentence: what it does.] It exists because [why — what gap it fills]. Without it, [what would break or be missing].
>
> **[Agent name]**
> [Repeat for each agent.]
>
> Do any of these not make sense? Is there anything you'd expect the system to do that isn't covered here?

**Wait for answer.**

- If the user confirms: proceed.
- If the user questions an agent's inclusion: explain the tradeoff. If the user wants to remove it, remove it and note the implication.
- If the user requests an addition: add it with a proposed name, function, and rationale. Confirm before proceeding.
- If the user asks a question about how an agent works: answer in plain language. Do not go into implementation detail unless asked.

Update the internal roster before proceeding to ARCH-3.

---

## ARCH-3 — Criticality tier assignment [DYNAMIC]

Assign each confirmed agent a criticality tier. Present the assignments with a plain-language explanation of what each tier means.

**Say:**

> Each agent has a criticality level — this tells the system how to handle it if something goes wrong.
>
> - **Critical** — if this agent doesn't finish completely, the system stops. The work it does is required before anything else can continue.
> - **Standard** — if this agent hits a problem, it flags it and the system keeps going where it can. Gaps are noted but don't stop everything.
> - **Supporting** — partial results are fine. This agent adds value but the main work completes without it.
>
> Here's what I'm proposing for your system:
>
> | Agent | Tier | Why |
> |-------|------|-----|
> | [Agent name] | Critical | [One sentence reason] |
> | [Agent name] | Standard | [One sentence reason] |
> | [Agent name] | Supporting | [One sentence reason] |
>
> Does this match your expectations? If any of these feel off, let me know.

**Wait for answer.**

- If the user confirms: proceed.
- If the user disagrees with a tier: discuss the implication (e.g., moving an agent to Critical means the system halts if it fails), update the assignment, confirm.

---

## ARCH-4 — Permission summary [FIXED — topic]

Present what the system will and will not be able to do on its own, in plain language. Do not use technical permission categories.

**Say:**

> Here's what your system will be able to do on its own, and what it will always stop and ask you about first.
>
> **On its own, without asking:**
> [List: read access to specific data sources, write to project files, generate reports, send digests, apply advisor rules already in the knowledge base, etc. — derived from the confirmed agent roster and vision document.]
>
> **Always asks you first:**
> [List: spending money, sending messages on your behalf, irreversible actions, guardrail violations, anything flagged as Tier 1 during notifications setup — plus any additions the user made in NOTIF-3.]
>
> Does this match what you'd expect?

**Wait for answer.**

- If the user confirms: proceed.
- If the user wants to add something to the "always ask" list: note it as an additional Tier 1 item. Update the staging file.
- If the user wants to remove a "always ask" item: the baseline Tier 1 items (spending, external messaging, irreversible actions, guardrail violations, legal/compliance, contradictions) cannot be removed. Explain this clearly and move on.

---

## ARCH-5 — Task completion checklists [DYNAMIC]

For each agent in the confirmed roster, present how the system will know when that agent has finished its work.

**Say:**

> Last step in the architecture review. For each agent, here's how the system will know its work is done. Tell me if any of these don't match what you'd expect.

For each agent:

> **[Agent name]:** [Agent name]'s work is done when [plain-language completion condition — e.g., "the report has been generated and saved, all data sources have been checked, and no errors were flagged."]. Does that sound right?

**Wait for answer after each agent, or present the full list and ask for any corrections.**

- If the user confirms: note the checklist as confirmed.
- If the user adjusts a completion condition: update it and confirm.

---

## Write architecture to disk

After ARCH-5, write the technical architecture foundation document.

**File:** `[PROJECT_DIR]/technical_architecture.md`

**Structure:**

```
# Technical Architecture

## Orchestration Model
[Plain-language description of the confirmed workflow structure —
which workflows are independent, which are sequential, and why.]

## Agent Roster
[Table or list: each confirmed agent with its function, rationale,
and criticality tier.]

| Agent | Function | Criticality |
|-------|----------|-------------|
| [name] | [one sentence] | Critical / Standard / Supporting |

## Permission Boundaries
[What the system can do autonomously. What it always asks before doing.
Tier 1 items confirmed during setup, including any user additions.]

## Task Completion Checklists
[For each agent: the confirmed completion condition.]

**[Agent name]:** [Completion condition]
```

**Say:**

> Architecture confirmed and saved. That covers the structure of your system — how it's organized, what each part does, and how it behaves. Next we'll go through the technical setup: credentials, integrations, and the build sequence.

Update staging file: ARCHITECTURE_CONFIRMED = true

Also update `[PROJECT_DIR]/approach.md` — replace the preliminary agent roster section with the confirmed roster from ARCH-2 and ARCH-3 (agents, functions, criticality tiers).

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 08.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 08.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

ARCH-1 through ARCH-5 complete. Technical architecture document confirmed and written to `[PROJECT_DIR]/technical_architecture.md`. Approach document updated with confirmed agent roster. ARCHITECTURE_CONFIRMED = true in the staging file.

**Write completion marker:** Append `step_08: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `09_credentials.md`.
