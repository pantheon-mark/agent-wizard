# 07 — Advisor Identification

## What this file does
Identify the advisors the system will route decisions to. Claude proposes a list of relevant advisor types based on the vision document, the user confirms or adjusts, and each confirmed advisor is recorded with their domain. Explain the two-path advisor workflow in plain language. Seed the advisor knowledge base with a header entry for each confirmed advisor. Generate a first interview guide for each confirmed advisor.

## When this file runs
After `06_approach.md` completes and the approach document is confirmed on disk.

## Prerequisites
APPROACH_CONFIRMED = true in the staging file. Vision document on disk at `[PROJECT_DIR]/vision.md`.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 07_advisors.md. APPROACH_CONFIRMED = true. Read the vision document, approach document, and staging file at `~/claude-wizard-draft/wizard_session_draft.md`, then begin ADV-1."

Do not begin ADV-1 until you are confident the full phase will complete before compaction risk.

---

## ADV-1 — Propose advisor types [DYNAMIC]

Before speaking, read the confirmed vision document. Identify the domain, industry, data sources, and business activities the system will handle. Use this to generate a list of advisor types most likely to come up as the system makes decisions. Always include financial and legal advisors unless the vision document explicitly rules them out. Add one or two domain-specific advisors based on what the system is actually doing.

**Say:**

> Based on what you've described, here are the types of advisors who are likely to come up as your system makes decisions:
>
> - **Accountant or bookkeeper** — financial decisions, tax treatment, expense categorization
> - **Lawyer** — contracts, compliance, anything with legal exposure
> - **[Domain-specific advisor 1]** — [domain and decision type]
> - **[Domain-specific advisor 2, if applicable]** — [domain and decision type]
>
> Do any of these not apply? Is there anyone missing? You can also say "not sure" for any of them.

**Wait for answer.**

- If the user confirms the list as-is: proceed with the full list.
- If the user removes an advisor: remove it. Do not push back.
- If the user adds an advisor: add it to the list with the domain they describe.
- If the user says "not sure" for an advisor: keep it on the list, note it as unconfirmed. It can be updated when the system is live.
- If the user asks what an advisor type means: answer plainly and let them decide.

For each confirmed or unconfirmed advisor, collect:
- **Role or name** — the user may know the actual person ("my accountant Sarah") or just the role ("accountant"). Either is fine. Record whichever they provide.
- **Domain** — what kinds of decisions this advisor weighs in on

Store: ADVISORS = list of confirmed advisors, each with role/name and domain

Update staging file.

---

## ADV-2 — Explain the two-path workflow [FIXED — topic]

After the advisor list is confirmed, explain how the system will work with those advisors.

**Say:**

> When your system reaches a decision that needs outside expertise — something your accountant, lawyer, or another advisor should weigh in on — there are two ways to handle it.
>
> **The quick way:** you ask your advisor, get their answer, and just tell me what they said. I'll record it and move on. This works fine for simple questions with clear answers.
>
> **The better way** — and the one I'll suggest for anything significant: before you talk to them, I'll prepare a set of questions so the conversation covers everything relevant. You have the meeting, bring me the transcript, and I'll pull out not just the answers but the reasoning behind them — the rules your advisor is actually applying — and save those so your system can use that judgment automatically in the future. Over time, this means you need to consult advisors less often because the system already knows how they think.
>
> I'll always tell you which approach I'm recommending for each decision.

No answer required. This is informational only. If the user has questions, answer them and move on.

---

## ADV-3 — Seed the advisor knowledge base [DYNAMIC]

For each confirmed advisor, write a header entry to the advisor knowledge base.

**File:** `[PROJECT_DIR]/quality/advisor_knowledge_base.md`

Each header entry format:

```
## [Advisor Role or Name]

**Domain:** [what decisions this advisor covers]
**Status:** Active
**First identified:** [wizard setup date]
**Notes:** [any initial notes the user provided, or "None"]

<!-- Guidance entries will be added here as consultations occur -->
```

Write all header entries to the file before proceeding. If the file does not exist, create it with a brief preamble:

```
# Advisor Knowledge Base

This file records guidance extracted from advisor consultations.
Each entry captures the rule, the reasoning behind it, the conditions
under which it applies, and when it should be reviewed. Agents read
and apply these entries at Level 3 and above.

---
```

Then write the header entries below the separator.

Update the staging file with the number of advisors seeded.

---

## ADV-4 — Generate first interview guides [DYNAMIC]

For each confirmed advisor, generate a first interview guide seeded with questions relevant to the system being built.

**File location:** `[PROJECT_DIR]/advisor/interview-guides/[advisor-role-slug]-interview-guide.md`

Use the advisor's role as the filename slug (e.g., `accountant-interview-guide.md`, `lawyer-interview-guide.md`).

Each interview guide format:

```
# Interview Guide — [Advisor Role or Name]

**Purpose:** Help [Advisor Role] understand the system and provide
guidance on the decisions it will face in their domain.

**How to use this guide:** Share the relevant sections with your
advisor before or during your meeting. Bring back their answers —
or a transcript if possible — and Claude will extract the rules
and record them in the advisor knowledge base.

---

## About the system

[2–3 sentences drawn from the vision document describing what the
system does, in plain language the advisor can understand. No
technical details.]

## Questions for [Advisor Role]

[5–8 questions tailored to the advisor's domain and the specific
decisions the system will face. Ground these in the vision document
and approach document. Questions should surface rules and reasoning,
not just yes/no answers.]

1. [Question]
2. [Question]
...

## Follow-up areas if time allows

[2–3 additional questions for deeper coverage — lower priority than
the main list above.]
```

Write each guide to disk before proceeding.

Write an audit log entry for each advisor identified:

> Advisor identified during wizard setup — role/name: [role or name], domain: [domain], knowledge base header entry seeded, interview guide written to [file path]

Update staging file: ADVISORS_SEEDED = true

---

## Success condition

ADV-1 through ADV-4 complete. All confirmed advisors recorded in the staging file. Advisor knowledge base seeded with a header entry for each advisor at `[PROJECT_DIR]/quality/advisor_knowledge_base.md`. First interview guide written for each advisor at `[PROJECT_DIR]/advisor/interview-guides/`. ADVISORS_SEEDED = true in the staging file. Proceed to `08_architecture.md`.
