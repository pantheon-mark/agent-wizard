# 03 — User Profile

## What this file does
Establish the user profile across five dimensions. These answers calibrate how the system communicates with this specific user — the language it uses, how much detail it provides, when it asks for approval versus acts on its own, and how involved the user wants to be day-to-day. The profile governs all downstream communication and involvement calibration.

## When this file runs
After `02_financial.md` completes.

## Prerequisites
FIN-1 and FIN-2 answered and stored in the staging file.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 03_user_profile.md. FIN-1 and FIN-2 are complete. Read the staging file at `~/claude-wizard-draft/wizard_session_draft.md`, then begin UP-1."

Do not begin UP-1 until you are confident the full phase will complete before compaction risk.

---

## How to conduct this section

These are five conversational questions, not a form. Ask them in order, but let the user's answers flow naturally — they may volunteer information that covers multiple dimensions in one response. If that happens, note what was captured and confirm before moving on.

The goal is a genuine sense of this person: how they think, what they need, where they want to be hands-on vs. hands-off. Listen for signals beyond the literal answer — someone who describes a complex multi-stakeholder operation probably has high domain expertise even if they say they're "not technical."

---

## UP-1 — Technical literacy

**Ask the user:**

> When it comes to technical tools and systems — things like software, automation, code — how would you describe your comfort level? Not what you know, but how you like to be talked to about it.
>
> For example: do you prefer plain language and no jargon, or are you comfortable with technical terms if they're useful? There's no right answer — I'm just calibrating how I explain things to you.

**Wait for answer.** Use their response to calibrate language complexity throughout all subsequent wizard steps. If they say "plain language, no jargon," use no unexplained technical terms from here forward. If they're comfortable with technical detail, you can be more precise. Confirm your interpretation in one sentence.

Store: UP_TECHNICAL_LITERACY = brief characterization (e.g. "plain language only", "comfortable with technical terms", "mixed — technical okay for system stuff but not code")

Update staging file.

---

## UP-2 — Information preference

**Ask the user:**

> When the system tells you something happened — like an agent completed a task or something needed attention — do you generally want to know the reasoning and context, or do you prefer the short version: what happened and what to do?

**Wait for answer.** Common responses: "short version", "I like to understand why", "depends on the situation". If "depends," ask a quick follow-up: "When does the longer version feel useful to you?"

Store: UP_INFORMATION_PREFERENCE = brief characterization (e.g. "bottom-line-up-front", "context-first", "situational — detail for decisions, summary for routine")

Update staging file.

---

## UP-3 — Decision preference

**Ask the user:**

> When the system is about to do something significant — not routine tasks, but things like sending a message on your behalf, making a change to an important document, or spending more than usual — do you want it to ask you first, or tell you after it's done?
>
> You can have different preferences for different types of actions — just tell me how you think about it.

**Wait for answer.** Most users will want "ask first" for significant actions and "tell me after" for routine ones. Note any specific distinctions they make (e.g. "ask first for anything external, auto for internal stuff").

Store: UP_DECISION_PREFERENCE = brief characterization (e.g. "ask-first for significant actions", "auto-with-summary", "ask-first always")

Update staging file.

---

## UP-4 — Domain expertise

**Ask the user:**

> What areas do you know really well — where your judgment is the authority? And are there areas where you'd rely on outside advisors or where you think having a dedicated specialist agent would be valuable?
>
> Think about the kind of work this system will be doing. What parts of that do you know cold, and what parts are less certain?

**Wait for answer.** This is one of the most important questions — it directly informs which domains the system treats with high sensitivity (inputs in areas the user knows well get more scrutiny; inputs in areas of uncertainty may need advisor routing). Listen for both explicit expertise ("I know finance inside out") and implicit expertise revealed by how they describe their work.

Store: UP_DOMAIN_EXPERTISE = list of strong-expertise areas and uncertain/advisor-dependent areas

Update staging file.

---

## UP-5 — Involvement appetite

**Ask the user:**

> How hands-on do you want to be once the system is up and running? Some people want to review everything the system does for the first few months. Others want to hand things off quickly and only get involved when something needs a decision. Most are somewhere in between.
>
> What sounds right for you?

**Wait for answer.** This determines the starting autonomy level and how aggressively the system escalates to the user vs. handles things independently. Be concrete in your follow-up: if they say "fairly hands-off," confirm what that means to them (weekly digest? only for high-priority items?).

Store: UP_INVOLVEMENT_APPETITE = brief characterization (e.g. "review-everything initially", "high-level oversight", "hands-off except for decisions")

Update staging file.

---

## Synthesis step [INTERNAL]

After all five answers are recorded, synthesize a one-paragraph user profile and confirm it with the user before proceeding.

**Say:**

> Before we continue, here's how I've understood your preferences — I want to make sure I've got this right:
>
> [One paragraph synthesizing UP-1 through UP-5 in plain language. Cover: how they like to receive information, how much detail they want, when they want to be asked vs. informed, their areas of expertise, and how hands-on they expect to be. Write this as a description of the person, not a list of attributes.]
>
> Does that sound right? Anything to adjust?

**Wait for confirmation.** If they correct something, update the relevant UP field and re-state only the corrected part. Once confirmed, store the synthesized profile summary.

Store: UP_PROFILE_SUMMARY = the confirmed paragraph

Update staging file with the confirmed summary.

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 03.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 03.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

All five dimensions answered and confirmed. Profile summary stored.

**Write completion marker:** Append `step_03: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `04_notifications.md`.
