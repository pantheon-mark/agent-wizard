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
> "Resume wizard from 03_user_profile.md. FIN-1 and FIN-2 are complete. Read the staging file at `~/claude-wizard-draft/wizard_session_draft.md`, then continue from where you left off."

Do not begin UP-1 until you are confident the full phase will complete before compaction risk.

---

## Sub-step resume check

Read `~/claude-wizard-draft/wizard_progress.md`. If it contains any sub-step markers matching `step_03_*` (e.g., `step_03_UP-1: complete`), this step was partially completed in a prior session. Skip to the first question section below that does NOT have a corresponding completion marker — do not re-ask completed questions, as their answers are already stored in the staging file.

If all sub-step markers for this step are present but the step-level marker (`step_03: complete`) is not, proceed directly to the success condition.

---

## Step opening — progress, preview, and orientation

**Say:**

> **Step 4 of 16 — Getting to know you**
> I'll learn how you like to work so the system matches your style.
>
> Before we dive in — two things to know:
>
> This whole process takes about an hour, though it can vary. The wizard saves everything as we go — you can close it and come back anytime without losing your progress. Feel free to take a break whenever you need one.
>
> Also — these are conversation starters, not a form. Feel free to ask me to clarify anything, push back on something, or share more than what I asked. We'll work through it together.

---

## How to conduct this section

These are five conversational questions, not a form. Ask them in order, but let the user's answers flow naturally — they may volunteer information that covers multiple dimensions in one response. If that happens, note what was captured and confirm before moving on.

The goal is a genuine sense of this person: how they think, what they need, where they want to be hands-on vs. hands-off. Listen for signals beyond the literal answer — someone who describes a complex multi-stakeholder operation probably has high domain expertise even if they say they're "not technical."

**If the user says "I don't know" or gives a vague/uncertain answer to any question:** propose a reasonable default based on what you know so far — their project purpose, their answers to earlier questions, and the context from Phase 1. Say: "Based on what you've told me so far, I'd suggest [proposed characterization]. Does that sound about right, or would you describe it differently?" This follows the wizard question design principle: Claude proposes, user confirms. No question should stall because the user can't articulate a preference from scratch.

---

## UP-1 — Technical literacy

**Ask the user:**

> When it comes to technical tools and systems — things like software, automation, code — how would you describe your comfort level? Not what you know, but how you like to be talked to about it.
>
> For example: do you prefer plain language and no jargon, or are you comfortable with technical terms if they're useful? There's no right answer — I'm just calibrating how I explain things to you.

**Wait for answer.** Use their response to calibrate language complexity throughout all subsequent wizard steps. If they say "plain language, no jargon," use no unexplained technical terms from here forward. If they're comfortable with technical detail, you can be more precise. Confirm your interpretation in one sentence.

Store: UP_TECHNICAL_LITERACY = brief characterization (e.g. "plain language only", "comfortable with technical terms", "mixed — technical okay for system stuff but not code")

Update staging file.

Write sub-step marker: Append `step_03_UP-1: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## UP-2 — Information preference

**Ask the user:**

> When the system tells you something happened — like an agent completed a task or something needed attention — do you generally want to know the reasoning and context, or do you prefer the short version: what happened and what to do?

**Wait for answer.** Common responses: "short version", "I like to understand why", "depends on the situation". If "depends," ask a quick follow-up: "When does the longer version feel useful to you?"

Store: UP_INFORMATION_PREFERENCE = brief characterization (e.g. "bottom-line-up-front", "context-first", "situational — detail for decisions, summary for routine")

Update staging file.

Write sub-step marker: Append `step_03_UP-2: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## UP-3 — Decision preference

**Ask the user:**

> When the system is about to do something significant — not routine tasks, but things like sending a message on your behalf, making a change to an important document, or spending more than usual — do you want it to ask you first, or tell you after it's done?
>
> You can have different preferences for different types of actions — just tell me how you think about it.

**Wait for answer.** Most users will want "ask first" for significant actions and "tell me after" for routine ones. Note any specific distinctions they make (e.g. "ask first for anything external, auto for internal stuff").

Store: UP_DECISION_PREFERENCE = brief characterization (e.g. "ask-first for significant actions", "auto-with-summary", "ask-first always")

Update staging file.

Write sub-step marker: Append `step_03_UP-3: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## UP-4 — Domain expertise

**Ask the user:**

> What areas do you know really well — where your judgment is the authority? And are there areas where you'd rely on outside advisors or where you think having a dedicated specialist agent would be valuable?
>
> Think about the kind of work this system will be doing. What parts of that do you know cold, and what parts are less certain?

**Wait for answer.** This is one of the most important questions — it directly informs which domains the system treats with high sensitivity (inputs in areas the user knows well get more scrutiny; inputs in areas of uncertainty may need advisor routing). Listen for both explicit expertise ("I know finance inside out") and implicit expertise revealed by how they describe their work.

Store: UP_DOMAIN_EXPERTISE = list of strong-expertise areas and uncertain/advisor-dependent areas

Update staging file.

Write sub-step marker: Append `step_03_UP-4: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## UP-5 — Involvement appetite

**Ask the user:**

> How hands-on do you want to be once the system is up and running? Some people want to review everything the system does for the first few months. Others want to hand things off quickly and only get involved when something needs a decision. Most are somewhere in between.
>
> What sounds right for you?

**Wait for answer.** This determines the starting autonomy level and how aggressively the system escalates to the user vs. handles things independently. Be concrete in your follow-up: if they say "fairly hands-off," confirm what that means to them (weekly digest? only for high-priority items?).

Store: UP_INVOLVEMENT_APPETITE = brief characterization (e.g. "review-everything initially", "high-level oversight", "hands-off except for decisions")

Update staging file.

Write sub-step marker: Append `step_03_UP-5: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

---

## UP-6 — Regulatory-applicability probe

Per `wizard/shape_detection.md` § 8.1 (canonical two-step probe pattern) two-step probe pattern. The probe captures whether the operator's project has regulatory exposure (GDPR / HIPAA / PCI-DSS / SOX / COPPA-or-GDPR-K / sector-specific) and which framework specifically applies. Used by pre-step-05 re-check to evaluate the 4 stop conditions per D1 § 6.3.

### UP-6.1 — Data-type question (lead-in + propositional list)

**Say:**

> Two more questions about the data your system will handle. These help me check whether your project's regulatory exposure is compatible with the system shape we've detected — so I don't generate something that won't work for your actual needs.
>
> Will the system handle any of the following on a regular basis?
>
> 1. **Health information about identifiable people** — patient records, medical histories, insurance claims
> 2. **Personal data of people in the EU/EEA** — names, contact info, behavioral data, etc.
> 3. **Credit card or payment card numbers**
> 4. **Financial reporting data subject to audit** — for publicly-traded companies or their auditors
> 5. **Data from children under 13** (or under 16 in the EU)
> 6. **Other regulated data** — government records, education records, sector-specific (energy, telecoms, etc.)
> 7. **None of the above** — no regulated data
>
> Which of these apply? (You can say "none," one item, or multiple items.)

**Wait for answer.**

**If operator says "none" / "#7" / equivalent:**

Store:
```yaml
regulatory_exposure:
  gdpr_applicable: no
  hipaa_applicable: no
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific: []
  no_compliance_claim: yes
  no_compliance_claim_framework_identification: no
  probed_at_step: 03_up6
  probed_timestamp: <ISO 8601>
```

Append the `## Regulatory exposure` section to staging file with the above content. Skip UP-6.2 (no follow-up needed). Proceed to synthesis step.

**If operator says any of #1-#6 apply:** continue to UP-6.2.

**If operator's answer is unclear / "I don't know" / "maybe":**

Propose a default per the conversation context (per the wizard's question-design principle: propose, user confirms). If their project description and step 02-03 answers give no signal of regulated data: propose "I'll assume none of these apply unless you correct me." If signals point to potential regulation (e.g., they mentioned customers / payments / health context during P1-2): propose specific candidates and ask them to confirm or remove items.

### UP-6.2 — Role/scope question (per matched framework)

For EACH framework operator marked applicable in UP-6.1, ask the corresponding role/scope question per D1 § 6.1:

**If #1 (health information):**

> Are you (or the system) acting as a healthcare provider, insurance plan, clearinghouse, OR a business associate processing health data on their behalf? Or is this more like your own personal notes or a tool for your own use?

If operator-role = covered entity / business associate: `hipaa_applicable: yes`. If personal use only: `hipaa_applicable: no` (no covered entity status → HIPAA doesn't apply to personal data of self).

**If #2 (EU/EEA personal data):**

> Are you (or your organization) acting as a data controller or data processor of that personal data? Or are you handling only your own personal data?

If controller/processor: `gdpr_applicable: yes`. If only own data: `gdpr_applicable: no`.

**If #3 (payment card numbers):**

> Are you (or the system) subject to a card brand's PCI-DSS contractual scope — for example, accepting card payments as a merchant or processor?

If yes: `pci_dss_applicable: yes`. If no (e.g., reading card numbers from operator's own statements for personal budget tracking, not processing payments): `pci_dss_applicable: no`.

**If #4 (financial reporting subject to audit):**

> Are you a publicly-traded company OR an auditor with internal-control-over-financial-reporting (ICFR) responsibility?

If yes: `sox_applicable: yes`. If no: `sox_applicable: no`.

**If #5 (children's data):**

> Does the system specifically collect data FROM the children (not data about minors collected through parents/guardians)? AND does the system fall within the regulation's directed-to-children scope?

If both yes: `coppa_or_gdpr_k_applicable: yes`. If no: `coppa_or_gdpr_k_applicable: no`.

**If #6 (other regulated data):**

> Which framework applies? Common ones: FERPA (education records), GLBA (financial institutions), FedRAMP (US federal cloud), NIS2 (EU critical infrastructure), sector-specific regulations.

If operator names a specific framework: store under `other_sector_specific`:
```yaml
other_sector_specific:
  - framework: <named framework>
    applicable: yes
```

If operator says "I know it's regulated but I don't know which framework": store `no_compliance_claim_framework_identification: unknown` — this is the trigger for stop condition #4 at pre-step-05 re-check.

### UP-6.3 — Final emit

After UP-6.1 + UP-6.2 complete, write the full `## Regulatory exposure` section to staging file. **Per advisor R2 C-009 disposition: also update `handoff_phase` from `provisional_shape_emit` to `regulatory_exposure_populated`** so downstream consumers know the regulatory data is now available.

Example for an operator who marked #1 (health) + #6 (sector-specific):

```yaml
## Regulatory exposure

regulatory_exposure:
  gdpr_applicable: no
  hipaa_applicable: yes
  pci_dss_applicable: no
  sox_applicable: no
  coppa_or_gdpr_k_applicable: no
  other_sector_specific:
    - framework: HIPAA Privacy Rule (same as #1; redundant unless operator named a different sector-specific framework)
      applicable: yes
  no_compliance_claim: no
  no_compliance_claim_framework_identification: no
  probed_at_step: 03_up6
  probed_timestamp: <ISO 8601>
```

**Then update `handoff_phase` field** (locate the existing line in the staging file's `## Shape detection` section — it currently reads `handoff_phase: provisional_shape_emit`; rewrite to):

```yaml
handoff_phase: regulatory_exposure_populated
```

Write sub-step marker: Append `step_03_UP-6: complete | <timestamp>` to `~/claude-wizard-draft/wizard_progress.md`.

**Note on stop-condition surfacing:** The 4 stop conditions are evaluated at pre-step-05 re-check (`wizard/interview/_pre_step_05_recheck.md`), NOT here. UP-6 captures the data; the stop conditions consume it. This separation keeps step 03 focused on data capture and avoids surfacing "your shape is incompatible with HIPAA" as a step-03 surprise before the shape itself has been re-checked against accumulated context.

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
