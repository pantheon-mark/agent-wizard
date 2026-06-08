# 04 — Notification Channels

## What this file does
Determine who should receive notifications, set up the notification channels — NTFY for real-time alerts and email for the operations digest — configure the tiered digest cadence and decision-aging thresholds. NTFY is verified with a live test notification before proceeding; the email channel has its address verified (actual email sending is set up later, at build time). Neither channel is optional.

## When this file runs
After `03_user_profile.md` completes and the user profile is confirmed.

## Prerequisites
User profile (UP-1 through UP-5) confirmed and stored in the staging file.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 04_notifications.md. The user profile is complete. Read the staging file at `~/claude-wizard-draft/wizard_session_draft.md`, then continue from where you left off."

Do not begin NOTIF-7 until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_04_*` (e.g., `step_04_NOTIF-7: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_04: complete`) is not, proceed directly to the success condition.

---

## Step opening — progress and preview

**Say:**

> **Step 5 of 16 — Notifications**
> We'll set up how your system reaches you — alerts for urgent things, digests for everything else.

---

## Grounding — open every question from what you already know

Apply the Operator Interaction Contract § 2 (Grounding) to every question in this step (`wizard/interview/_operator_interaction_contract.md`; read it now if you have not this session). **Do not ask these questions cold** — before each one, check the working definition, `## Early mentions`, and prior steps' answers, and open from that context:
- **NOTIF-7** from any co-executor / partner / advisor already named — e.g. "you mentioned [name/role] earlier — should the system send them their own updates, or is it just you (and you keep them in the loop the way you do now)?"
- **NOTIF-1** from the digest cadence the operator described at UP-5 — e.g. "you said you'd want a daily summary early, easing to weekly as it earns your trust — here's how I'd set that up."
- **NOTIF-3** from the always-ask actions they already gave at UP-3 (money / external comms / deletions) — acknowledge those are already in the baseline rather than re-presenting them as new.

Keep the ask balanced and fall back to a question's neutral phrasing only when nothing relevant was mentioned earlier — the question texts below are content plus fallback wording, not a script (contract § 2).

---

## NOTIF-7 — Stakeholder identification

**Ask the user** (ground per the step-level rule above — open from any co-executor/partner/advisor already named):

> Before we set up notifications, a quick question: is anyone else involved in this project who should receive updates — a family member, a teammate, a business partner?
>
> It's fine if it's just you. But if other people need to stay informed, I want to know now so we set things up correctly.

**Wait for answer.**

**If just the user (single stakeholder):**

> Got it — just you. I'll set everything up for a single recipient.

Store: NOTIFICATION_MODE = "single"
Store: STAKEHOLDERS = [primary user only]

**If others are involved:**

For each person mentioned, ask:

> What kind of updates does [name/role] need? For example:
>
> - **Operational** — errors, system problems, things that need fixing (typically for whoever manages the system)
> - **Content** — decisions needed, deadlines, deliverables, progress (for people who use what the system produces)
> - **Both** — they want the full picture

**Wait for answer.** Capture for each stakeholder: name or role, notification type (operational / content / both), preferred channel if mentioned.

> I'll keep track of who gets what. For now, we'll set up your channels first — the primary operator always gets everything. We can add other people's channels during the build phase once the system is running.

Store: NOTIFICATION_MODE = "multi"
Store: STAKEHOLDERS = list of all stakeholders with their notification types

Update staging file.

Write sub-step marker: Append `step_04_NOTIF-7: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## NOTIF-1 — Tiered digest cadence

**Propose the tiered digest structure:**

> Your system will send you regular summaries at three different levels. Here's what I recommend:
>
> - **Daily digest** — Actions needed: decisions waiting for you, errors that happened, anything blocked. This is your "what do I need to do today" summary. Takes about two minutes to read.
> - **Weekly digest** — Progress report: what your agents accomplished this week, what's planned for next week, any patterns worth noting. This is your "how's the system doing" summary.
> - **Monthly digest** — Big picture: system health trends, goal progress, whether the system is still aligned with what you set out to build. This is your "is this still working for me" summary.
>
> The daily digest is the most important one early on — it keeps you in the loop while you're learning how the system operates. As things settle in, you might find you only need the weekly and monthly.
>
> Does this structure work for you, or would you like to adjust any of the cadences?

**Wait for answer.**

- If they confirm the structure as-is: store all three defaults.
- If they want to adjust (e.g., "make the daily one every other day"): accept the adjustment and confirm.
- If they want fewer tiers (e.g., "just weekly is fine"): accept, but note gently that daily action items will still arrive as real-time alerts if they're urgent — the daily digest catches the non-urgent ones. Confirm they're comfortable with that.

Store:
- DIGEST_CADENCE_ACTIONS = the confirmed cadence for action items (default: "daily")
- DIGEST_CADENCE_PROGRESS = the confirmed cadence for progress summaries (default: "weekly")
- DIGEST_CADENCE_BIG_PICTURE = the confirmed cadence for big-picture review (default: "monthly")

Update staging file.

Write sub-step marker: Append `step_04_NOTIF-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## NOTIF-2 — Stale decision threshold

**Ask the user:**

> Sometimes a decision needs your attention — a question from an advisor, an issue your system flagged, or a choice that's been sitting in the queue. If you haven't gotten to it after a while, the system will remind you.
>
> **How many days should pass before the system nudges you about an unresolved decision?**
>
> The default is 7 days; you can change it anytime.

**Wait for answer.** If they accept the default or give a number, store it. If they say "I'll figure it out" or similar, use the default.

Store: STALE_DECISION_THRESHOLD_DAYS = the confirmed number (default: 7)

Update staging file.

Write sub-step marker: Append `step_04_NOTIF-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## NOTIF-3 — Tier 1 decision confirmation

**Explain and confirm:**

> The system handles most things on its own, but there are some actions it will always stop and ask you about first — no matter what. These are things where the wrong move could be hard to undo or could have consequences outside your project.
>
> Here's the list:
>
> - **Spending money** — any financial transaction or commitment
> - **Sending messages on your behalf** — emails, messages, posts, or any external communication
> - **Irreversible actions** — deleting files, removing data, actions that can't be undone
> - **Guardrail violations** — anything that would cross a rule your system is configured to follow
> - **Legal or compliance actions** — anything that could create a legal obligation or compliance issue
> - **Contradictions** — when what the system is about to do conflicts with something in your vision document or your rules
>
> The system will never do any of these without asking first. You can add things to this list during setup or at any time. You cannot remove the items above — they're the baseline.
>
> Does this list make sense? Is there anything you'd like to add?

**Wait for answer.**

- If they confirm without additions: note as confirmed.
- If they want to add items: record each addition as a Tier 1 item.
- If they question or push back on an item: explain why it's a baseline (irreversibility, external impact, etc.). The baseline items cannot be removed — explain this clearly and move on.

Store: TIER_1_ADDITIONS = any items the user added (empty list if none)

Update staging file.

Write sub-step marker: Append `step_04_NOTIF-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## NOTIF-4 — NTFY setup [HARD GATE]

Do not proceed past this step until the user has confirmed receipt of a test notification on their phone.

**First, explain what NTFY is:**

> For urgent alerts — things that need your attention right away, like an error that stopped the system or an action waiting for your approval — the system sends a push notification to your phone. This happens instantly, even when you're not at your computer.
>
> We use a free app called NTFY for this. It's simple: you install the app, subscribe to a private channel we create just for you, and alerts arrive on your phone.

**Generate a unique topic string:**

Derive the project name slug from P1-1 (stored in staging file): lowercase the project name, replace spaces and special characters with hyphens, strip leading/trailing hyphens, then **shorten it for typeability** — keep whole hyphen-separated words only, up to ~12 characters total (drop the later words rather than cutting mid-word; if even the first word exceeds 12 characters, truncate that word to 12). The operator has to TYPE this on their phone to subscribe, so a short, recognizable slug beats a complete one.

Run: `openssl rand -hex 4`

This produces an 8-character random hex string. Combine with the slug: `[project-name-slug]-[hex]` (e.g., "Jacob's College Adventure" → slug `jacobs` → topic `jacobs-a3f8c21d`; "Estate Settlement Tracker" → `estate-a3f8c21d`). Short enough to type on a phone, still recognizable in the NTFY app and distinguishable across projects. The 8-hex suffix keeps the topic unguessable (it functions as a private key — anyone who knows it can read/send), so do not shorten the hex.

**Store:** NTFY_TOPIC = the generated slug-hex string

**Say:**

> Your private notification channel is: `[NTFY_TOPIC]`
>
> Here's how to set it up — it takes about two minutes:
>
> **On your iPhone or iPad:**
> 1. Open the App Store and search for "ntfy"
> 2. Install the app (it's free, made by Philipp Heckel)
> 3. Open the app and tap the **+** button
> 4. Type your channel name: `[NTFY_TOPIC]`
> 5. Tap **Subscribe**
>
> **On Android:**
> 1. Open Google Play and search for "ntfy"
> 2. Install the app (it's free)
> 3. Open the app and tap the **+** button
> 4. Type your channel name: `[NTFY_TOPIC]`
> 5. Tap **Subscribe**
>
> Let me know when you've subscribed and I'll send a test notification.

**Wait for user to confirm they have subscribed.** Then send the test notification:

Run: `curl -s -o /dev/null -w "%{http_code}" -d "Test from your Agent Team Wizard — setup is working." https://ntfy.sh/[NTFY_TOPIC]`

If the curl command returns `200`: the notification was sent successfully.

**Say:**

> I've sent a test notification to your channel. You should see it on your phone now. Did it arrive?

**HARD GATE: Do not proceed until the user confirms they received the notification.**

- If received: say "Great — that channel is confirmed. Your urgent alerts will come through there." Update staging file.
- If not received after 2–3 minutes: troubleshoot before proceeding.
  - Ask: "Did you subscribe to exactly `[NTFY_TOPIC]`?" (copy-paste errors are common)
  - Ask: "Do you have notifications enabled for the NTFY app in your phone's settings?"
  - Re-send the test notification.
  - Do not proceed until the test notification is confirmed received.

Store: NTFY_CONFIRMED = true (only set after user confirms receipt)

Update staging file.

Write sub-step marker: Append `step_04_NOTIF-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## NOTIF-5 — Email address verification

Do not proceed past this step until the user has confirmed the email address is correct.

**Say:**

> The other channel is email — that's where your regular digest arrives. It's a summary of what the system has done, what's waiting for your attention, and anything coming up.
>
> What email address should the digest go to?

**Wait for answer.** Store the email address.

**Store:** DIGEST_EMAIL = the email address provided

**Say:**

> I won't send a test email just yet — your system starts emailing you once it's built. Right now I just want to make sure I've got your address exactly right.

(No live email is sent at this step — sending is set up later, when the system is built, using the address captured here. This step only verifies the address is correct. Do NOT tell the operator to watch their inbox.)

**Say:**

> Can you read the email address back to me so I can check it matches what I recorded, character for character? A digest is no use if one letter's off.

Wait for the user to confirm the address matches. If they correct it, update DIGEST_EMAIL and confirm again.

**Store:** EMAIL_CONFIRMED = true

**Say:**

> Confirmed — your digests will go to [DIGEST_EMAIL] once your system is up and running. I've noted setting that up as a step for when we build the system.

Update staging file with DIGEST_EMAIL and a note that email delivery setup is deferred to the build phase.

**Do not proceed until the email address is confirmed correct.** Email delivery setup is deferred to the build phase — this step verifies the address only.

Write sub-step marker: Append `step_04_NOTIF-5: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## NOTIF-6 — Production path note

**Say:**

> One thing to know for later: when your system is ready for full production, there's an option to add SMS text alerts for the most critical notifications. That's a future upgrade — nothing you need to think about now. I'll remind you when the time comes.

No answer required. This is informational only.

Write sub-step marker: Append `step_04_NOTIF-6: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## Recording answers (event transcript)

Record this step's `hitl_autonomy` source answers to `~/claude-wizard-draft/wizard_transcript.jsonl`. NOTIF-1/2/3 carry operator content (cadence, stale-decision threshold, and the confirmed Tier-1 always-ask baseline — the latter feeds the HITL policy); NOTIF-4/5/6/7 are channel setup/verification steps with no derivation source content, recorded as skips (the registry treats them as skip-satisfied):

```
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid NOTIF-1 --group hitl_autonomy --value "<tiered digest cadence>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid NOTIF-2 --group hitl_autonomy --value "<stale decision threshold>"
python3 wizard/scripts/interview_cli.py record-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid NOTIF-3 --group hitl_autonomy --value "<confirmed Tier-1 always-ask baseline + any additions>"
python3 wizard/scripts/interview_cli.py skip-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid NOTIF-4 --group hitl_autonomy --reason "NTFY channel setup; no derivation source content"
python3 wizard/scripts/interview_cli.py skip-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid NOTIF-5 --group hitl_autonomy --reason "email verification; no derivation source content"
python3 wizard/scripts/interview_cli.py skip-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid NOTIF-6 --group hitl_autonomy --reason "production path note; no derivation source content"
python3 wizard/scripts/interview_cli.py skip-answer --transcript ~/claude-wizard-draft/wizard_transcript.jsonl --qid NOTIF-7 --group hitl_autonomy --reason "stakeholder identification; no derivation source content"
```

---

## Step-boundary capture (testing mode only)

*This section runs only during test sessions. In normal wizard operation, skip directly to the success condition.*

**If Mark stated "this is a test run" at session start (Mode 2):**

> Notes on this step before continuing? (or skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 04.

**If a `test_mode_active` file exists in the wizard directory (Mode 3):**

> Testing note: anything unclear or confusing about this step? (Enter to skip)

Write the response (or "skipped") to `wizard_test_notes.md` in the project directory, tagged with step 04.

**If neither condition is true:** Skip this section entirely — do not show any prompt.

---

## Success condition

NOTIF-7 (stakeholder identification), NOTIF-1 through NOTIF-6 complete. NTFY channel confirmed (test notification received). Email address confirmed.

**Write completion marker:** Append `step_04: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

Proceed to `05_vision.md`.
