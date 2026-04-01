# 10 — Input Validation

## What this file does
Configure the validation gate — the layer that checks everything coming into the system before agents act on it. Claude proposes the input type inventory and domain sensitivity settings from the vision, approach, and architecture documents. The user confirms and adjusts but does not design. Produces `/quality/validation_gate_config.md`.

## When this file runs
After `09_credentials.md` completes and CREDENTIALS_CONFIRMED = true in the staging file.

## Prerequisites
CREDENTIALS_CONFIRMED = true in the staging file. Vision document, approach document, and technical architecture document confirmed on disk.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 10_validation.md. CREDENTIALS_CONFIRMED = true. Read the staging file and technical architecture document, then begin the input validation phase."

Do not begin GATE-1 until you are confident the full phase will complete before compaction risk.

---

## How to run this phase

Read the vision document, approach document, and technical architecture document before speaking. Build a complete candidate list of input types and domain areas from everything you find — every source of data, every user action, every external feed the agents will receive.

**The user does not design the validation configuration.** You propose it. They confirm, remove, or adjust.

Note: agent-to-agent handoffs are not routed through the validation gate. This gate governs inputs arriving at the system boundary — from external sources, users, and integrations.

---

## GATE-1 — Input type inventory [DYNAMIC]

Present the proposed input type inventory. For each input: what it is, why it needs to be checked, and what could go wrong without the check.

**Say:**

> Before your agents start working, everything coming into the system gets checked — to catch problems before they cause bad outputs.
>
> Here's every type of input I see your system receiving, based on your vision, approach, and architecture:
>
> **[Input type plain-language name]**
> [What it is — one sentence.] It needs to be checked because [specific risk — e.g., "customer names can contain formatting that breaks downstream reports" or "dates can be ambiguous without a format check"]. Without the check, [what could go wrong].
>
> **[Repeat for each input type.]**
>
> Does this list look complete? Is there anything you'd expect the system to receive that isn't here?

**Wait for answer.**

- If the user confirms: proceed to GATE-2.
- If the user removes an input type: note the implication briefly ("Understood — that source won't be checked on the way in") and update the list.
- If the user adds an input type: add it with a proposed name, description, and check rationale. Confirm before proceeding.
- If an input source is uncertain: mark it as pending. Note it clearly. It must be resolved before the system runs fully.

---

## GATE-2 — Domain sensitivity configuration [DYNAMIC]

For each domain area in the confirmed vision, approach, and agent roster: propose a sensitivity level with a one-sentence rationale. The user confirms, adjusts, or asks questions.

**Sensitivity levels:**
- **Low** — Flag only clear structural problems. Let borderline inputs through with a note.
- **Medium** — Flag structural problems and unusual patterns. Ask the user to confirm anything that looks off.
- **High** — Flag structural problems and anything semantically unexpected. Pause and ask before acting on flagged inputs.

**Say:**

> The system can be more or less cautious depending on the area. Some domains are more sensitive than others — a wrong date in a financial calculation is more dangerous than a wrong date in a blog post draft.
>
> Here's what I'm proposing for your system:
>
> | Domain area | Sensitivity | Why |
> |-------------|-------------|-----|
> | [Domain name] | Low / Medium / High | [One sentence rationale] |
> | [Repeat for each domain area] | | |
>
> Does this match your expectations? If any area feels too strict or too loose, tell me and I'll adjust.

**Wait for answer.**

- If the user confirms: proceed.
- If the user adjusts a sensitivity level: update it and note the user's reasoning in the config. Confirm before proceeding.
- If the user asks what a sensitivity level means in practice: give a concrete example using their domain ("At High, if your system receives a client name that contains characters it hasn't seen before, it will pause and ask you before using it in a report. At Low, it would use it and flag it in the log.").

Write all confirmed settings to `/quality/validation_gate_config.md` after GATE-2 is complete (see disk write section below).

---

## GATE-3 — Override behavior [EXPLANATION]

**Say:**

> When the system flags something and you tell me you meant it, I'll accept it and note it down.
>
> If you find yourself doing that a lot in the same area — the system keeps flagging things you're fine with — that's a signal the sensitivity is set too high for that area. You can lower it any time by just telling me.
>
> Over time, the system learns what you normally accept in each area and gets better at telling the difference between a real problem and a pattern you've already signed off on.

**Wait for any questions, then proceed.**

---

## GATE-4 — Hard vs. soft pushback [EXPLANATION]

**Say:**

> Two types of problems get handled differently.
>
> **Things the system won't accept until fixed:** If something is structurally wrong — the wrong format, a missing required field, data that can't be parsed — the system will stop and tell you what's broken. It won't try to proceed with broken input.
>
> **Things the system flags and asks you about:** If something looks unusual but could be intentional, the system will describe what it found and ask you to confirm before continuing. You can say "yes, I meant that" and it will proceed — and note that you approved it.
>
> The first kind protects you from silent failures. The second keeps you in control without stopping work unnecessarily.

**Wait for any questions, then proceed.**

---

## Write validation configuration to disk

After GATE-1 through GATE-4, write the validation gate configuration file.

**File:** `[PROJECT_DIR]/quality/validation_gate_config.md`

**Structure:**

```markdown
# Validation Gate Configuration

## Input Type Inventory

| Input type | Description | Check rationale | Status |
|------------|-------------|-----------------|--------|
| [name] | [what it is] | [why it's checked] | Active / Pending |

## Domain Sensitivity Settings

| Domain area | Sensitivity | Rationale | Last updated |
|-------------|-------------|-----------|--------------|
| [domain] | Low / Medium / High | [rationale] | [date] |

## Override Log

*Populated at runtime — each user override recorded here with input type, date, and context.*
```

Write an audit trail entry: `Input type inventory confirmed during wizard setup — [n] input types active, [n] pending`.

**Say:**

> Validation is configured. Here's what that means in practice:
>
> - **[n] input types** your system will check before agents act on them
> - [**[n] sources** still pending — those will need to be confirmed before the system runs fully] *(omit if none pending)*
> - Sensitivity settings: [list domains and levels in one line, e.g., "Financial: High, Content: Medium, Admin: Low"]
>
> Next we'll configure how the system handles errors and quality issues.

Update staging file: VALIDATION_CONFIGURED = true

---

## Success condition

GATE-1 through GATE-4 complete. `/quality/validation_gate_config.md` written to disk with confirmed input type inventory and domain sensitivity settings. VALIDATION_CONFIGURED = true in the staging file. Proceed to `11_error_handling.md`.
