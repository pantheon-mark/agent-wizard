# 02 — Financial Guardrails

## What this file does
Establish the financial guardrails that govern all autonomous spending by the system. Three elements: plan type identification (which determines rate limits and billing behavior), monthly spend ceiling, and calibration guidance tailored to the user's specific plan. These answers are stored in `project_instructions.md` and enforced by the system from the first day of operation.

## When this file runs
After `01_phase1_capture.md` completes. The staging file exists and is being updated after each answer.

## Prerequisites
Staging file at `~/claude-wizard-draft/wizard_session_draft.md` has been created and contains the P1-1 and P1-2 answers.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 02_financial.md. The staging file is at `~/claude-wizard-draft/wizard_session_draft.md` — read it, then begin FIN-1."

Do not begin FIN-1 until you are confident the full phase will complete before compaction risk.

---

## FIN-1 — Plan type identification

**Ask the user:**

> Before we set up your system's spending limits, I need to know which Claude plan you're on. Different plans have different rate limits and billing — and that affects how much your agents can do.
>
> Which best describes your plan?
>
> - **Pro** ($20/month) — The standard paid plan for individuals. Fixed monthly cost with a daily message cap.
> - **Max** ($100 or $200/month) — The highest personal tier. Much more generous limits, designed for heavy use.
> - **Team** ($25–30/user/month) — A business plan shared across a team. Has its own billing structure and shared rate limits.
> - **Free** — You use Claude without paying.
>
> If you're not sure, check claude.ai/settings/billing — it shows your current plan.

**Wait for answer.**

**If Free:**

> The wizard needs a paid Claude plan — Pro at minimum — to build and run an agent system. The free tier doesn't provide enough capacity for agents to operate reliably.
>
> You can upgrade at claude.ai/settings/billing. Pro ($20/month) is enough to get started. Come back and resume when you've upgraded — everything you've told me so far is saved.

Store: PLAN_TYPE = "free"

**HARD GATE: Do not proceed. The wizard cannot continue on a Free plan.**

**If Pro:**

> Great — Pro is the most common plan for running a system like this. Here's how it works with agents:
>
> - Your cost is fixed at $20/month — agent activity doesn't add extra charges on top of your subscription.
> - Pro has a daily message cap. When you or your agents approach it, Claude slows down (rate-limiting) rather than stopping entirely. Your agents still work, just more slowly during high-usage periods.
> - The system I'll build for you manages its workload to stay within your limits — it spreads tasks across the day rather than doing everything at once.

Store: PLAN_TYPE = "pro"
Store: OVERAGE_PLAN_TYPE = "rate-limited"

**If Max:**

> Max gives you the most room to work with — your agents will rarely hit capacity constraints.

**Ask:** "Is your Max plan the $100/month tier or the $200/month tier?"

**Wait for answer.** Store: MAX_TIER = "$100" or "$200"

> Here's how Max works with agents:
>
> - Your cost is fixed at $[MAX_TIER]/month. No surprise charges from agent activity.
> - Max has significantly higher rate limits and priority access. Your system can handle more concurrent work and intensive tasks without slowing down.
> - Rate-limiting is rare on Max — you'd need sustained heavy use before it kicks in.

Store: PLAN_TYPE = "max"
Store: OVERAGE_PLAN_TYPE = "rate-limited"

**If Team:**

> Team plans work a bit differently. Let me ask two quick follow-ups.
>
> **First:** Do you have access to your team's billing settings at claude.ai/settings/billing, or does someone else manage that?

**Wait for answer.** Store: TEAM_BILLING_ACCESS = true or false

> **Second:** How many people are on your team plan?

**Wait for answer.** Store: TEAM_SIZE = the number given

> Here's what matters for your system on a Team plan:
>
> - Rate limits are shared across everyone on the plan. Your agents' activity counts toward the team's total usage.
> - I'll configure the system to be mindful of shared limits so your agents don't crowd out your teammates.
> - If someone else manages billing, you may want to let them know you're setting up an agent system — they'll see the usage.

Store: PLAN_TYPE = "team"
Store: OVERAGE_PLAN_TYPE = "team-managed"

**If unsure or can't determine:**

> No problem. Check claude.ai/settings/billing when you get a chance — it shows your plan right at the top. For now, I'll assume Pro-level limits, which is the safest starting point. You can update this any time.

Store: PLAN_TYPE = "unknown"
Store: OVERAGE_PLAN_TYPE = "unknown"

Update staging file with all stored values.

---

## FIN-2 — Monthly spend ceiling

**Ask the user:**

> Now let's set a monthly ceiling — the point where the system stops all autonomous work and checks in with you. This isn't a prediction of what you'll spend — it's a safety net.
>
> Your [PLAN_TYPE] plan has a fixed subscription cost, so this ceiling is about how much of your plan's capacity the system is allowed to use. If it hits this limit, it pauses and waits for you to decide what to do next.
>
> Some people start at $20 and adjust up. Others set $100 from day one. Your system won't use anywhere near this in the early weeks.
>
> What number feels right to start?

**Wait for answer.** Accept any dollar amount. If the user gives a range (e.g. "maybe $50 to $100"), pick the lower end and note it.

**Once you have a number:**

Calculate the intensive operation threshold at 10% of the ceiling (e.g. if ceiling is $50, threshold is $5.00).

**Say this:**

> Got it — I'll set your ceiling at $[SPEND_CEILING]. Any time a single operation is estimated to cost more than $[INTENSIVE_THRESHOLD] on its own, the system will pause and ask for your approval before proceeding. You can raise or lower these at any time.

Store:
- SPEND_CEILING = the dollar amount
- INTENSIVE_OPERATION_THRESHOLD = 10% of SPEND_CEILING (rounded to two decimal places)

Update staging file with both values.

### Calibration guidance (after FIN-2, before proceeding)

After storing the ceiling, provide calibration guidance based on the user's plan type (FIN-1) and ceiling amount. This helps the user understand what their budget can support — framed in terms of both what the system can do and the usage limits of their plan.

**If PLAN_TYPE = "pro":**

> A few things worth knowing about your ceiling and your Pro plan together:
>
> **Usage limits:** Pro gives you a daily message cap. Your agents share this cap with your personal Claude use. The system manages its workload to stay under the cap, but on days when you also use Claude heavily, agents may slow down.
>
> **What your ceiling supports:**
> - **Under $20/month:** Light, focused work — checking a few things regularly and alerting you when something needs attention. You'll want to keep your agent team small (1–2 agents) and run them on a schedule rather than continuously.
> - **$20–$50/month:** Comfortable range for a small team of agents handling regular tasks — monitoring, summarizing, and flagging things for your review. Enough headroom for occasional intensive operations.
> - **$50–$100/month:** Room for a more active system — multiple agents running frequently, handling more complex work.
> - **Over $100/month:** Your ceiling gives plenty of room. Budget won't be a constraint in normal operation.
>
> Since your Pro subscription is a fixed $20/month, the ceiling is about how much of your plan's capacity the system uses — not about surprise charges. If agents regularly bump against the ceiling or the daily message cap, that's a signal to either raise the ceiling, spread tasks across off-peak hours, or consider upgrading to Max.

**If PLAN_TYPE = "max":**

> A few things worth knowing about your ceiling and your Max plan together:
>
> **Usage limits:** Max has significantly higher rate limits and priority access. Rate-limiting is rare — you'd need sustained heavy concurrent use before it kicks in. Your agents and personal use share the same generous allocation.
>
> **What your ceiling supports:**
> - **Under $50/month:** Conservative — leaves most of your Max capacity for personal use. Fine if your system is doing light, focused work.
> - **$50–$100/month:** Comfortable range for a moderately active system with several agents.
> - **$100–$200/month:** Room for a fully active system — multiple agents running frequently, handling complex work, with budget for intensive operations.
> - **Over $200/month:** Your ceiling gives the system full room to operate. Combined with Max's generous rate limits, budget and capacity won't be constraints.
>
> Your Max subscription is a fixed monthly cost — the ceiling is about how much capacity the system uses, not about surprise charges.

**If PLAN_TYPE = "team":**

> A few things worth knowing about your ceiling and your Team plan together:
>
> **Usage limits:** Your team's rate limits are shared across all [TEAM_SIZE] members. Your agents' activity counts toward the team total. Setting the ceiling conservatively is especially important here — you don't want agent activity to crowd out your teammates.
>
> **What your ceiling supports:**
> - **Under $20/month:** Conservative and team-friendly. Light, focused work — good for starting out while you see how agent activity affects your team's shared usage.
> - **$20–$50/month:** A reasonable range for a small agent team, as long as your team's total usage has headroom.
> - **Over $50/month:** Make sure your team's plan can support this level of agent activity alongside everyone else's usage. Consider discussing with your team admin.
>
> The key constraint on a Team plan is shared capacity — the ceiling protects both your budget and your teammates' access. If agents are bumping against limits, the first step is checking whether it's a team-wide capacity issue or just your allocation.

**If PLAN_TYPE = "unknown":**

Use the Pro guidance above. Add:

> Once you've confirmed your plan type (check claude.ai/settings/billing), let me know and I can adjust these settings to match.

**Note for step 13 cross-reference:** When SCALE-1 through SCALE-4 are answered in step 13 (operations), the wizard should compare the declared scale/velocity against the FIN-2 ceiling. If the scale suggests higher usage than the ceiling comfortably supports (e.g., Large scale tier with a $10 ceiling), surface the discrepancy to the user in plain language and ask if they'd like to adjust either the ceiling or the scale expectation. This check happens in step 13, not here — record `FIN_CALIBRATION_DELIVERED = true` in the staging file so step 13 knows to run the cross-reference.

Store: FIN_CALIBRATION_DELIVERED = true in staging file.

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 02.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 02.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

FIN-1 (plan type identified — or hard-gated on Free) and FIN-2 (spend ceiling set) answered and stored.

**Write completion marker:** Append `step_02: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `03_user_profile.md`.
