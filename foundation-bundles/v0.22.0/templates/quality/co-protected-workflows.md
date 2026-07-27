# Co-Protected Workflows

*Global irreversible action backstop. Contains action-type patterns that always trigger the irreversible action gate — regardless of how individual agents or skills are configured. Pre-populated from the Tier 1 decision categories confirmed during wizard setup.*

*Read by the QA agent on every security audit. Any agent-produced artifact matching a pattern here is flagged for human approval before execution, regardless of what the originating agent's configuration says.*

*This file is not user-editable through normal operation. Changes require a deliberate architectural review — the same protection level as Tier 1 decision categories.*

---

## Protected action patterns

### Financial transactions

Any action that initiates, schedules, cancels, or modifies a financial transaction — payment, charge, refund, subscription, invoice, or transfer.

**Examples:** Charging a payment method, canceling a subscription, issuing a refund, initiating a bank transfer, creating or modifying an invoice.

---

### External communications

Any action that sends a message to a person or system outside this project — email, SMS, chat message, social media post, webhook to an external system, or API call that triggers external delivery to a recipient.

**Examples:** Sending an email, posting to social media, sending a Slack or Teams message, triggering a third-party notification, submitting a form to an external service.

---

### Irreversible file or data operations

Any action that permanently deletes, drops, truncates, or overwrites data in a way that cannot be recovered without a backup or restore operation.

**Examples:** Deleting files, dropping database tables, truncating datasets, overwriting a file with no prior version saved, permanently purging records.

---

### Guardrail violations

Any action that modifies, bypasses, or weakens a guardrail, safety rule, or protected file — including this file, `CLAUDE.md`, `project_instructions.md`, agent prompt files in `/agents/prompts/`, or any file in `/security/`.

**Examples:** Modifying this file, editing `CLAUDE.md` without architectural review, changing permission boundaries in any agent prompt file, adding `.gitignore` entries that suppress the credentials check.

---

### Legal or compliance-triggering actions

Any action that could create a legal obligation, regulatory exposure, or compliance event — data sharing, terms of service acceptance, consent collection, or legally binding communications.

**Examples:** Accepting terms of service on behalf of the user, sharing data with a third party under a data agreement, sending a communication that constitutes legal notice, collecting user consent.

---

## Registered capability workflows

*Per-capability high-risk workflows, derived automatically from this system's confirmed external-dependency capability descriptors. Unlike the five categories above (fixed at every wizard setup), this section is generated fresh from what THIS system actually does — so a capability the plan never anticipated still gets a concrete, matchable pattern here instead of staying invisible until someone remembers to add it by hand.*

*Only capabilities whose risk class requires protection are listed: `irreversible_external`, `standing_automation`, and `sensitive_data` — plus any capability with a missing or unrecognized risk class, which is always treated as `irreversible_external` and never silently treated as safe. A capability classified `read_only_local` or `reversible_external` is deliberately NOT listed here — listing every capability regardless of risk would train reviewers to rubber-stamp this table instead of reading it.*

*`standing_automation` capabilities (server-side filters, rules, or scheduled jobs) are recognized here as their own action class. They may enter the ceremony-maturity ladder — starting supervised and earning autonomy over a run of clean outcomes — but their recovery floor NEVER graduates: maturity graduates supervision and narration, never the backup/recover safety net. Every row for this class states that explicitly.*

| Capability | Action class | Risk class | What's protected |
|-----------|-------------|-----------|------------------|
{{CO_PROTECTED_CAPABILITY_ROWS}}

---

## How protection works

1. The QA agent reads this file at every security audit invocation.
2. Every agent-produced artifact is checked against these patterns before promotion to downstream agents or delivery.
3. If an artifact matches any pattern: flagged for human approval. The originating agent's own configuration is irrelevant — this file overrides it.
4. Matching artifacts are not auto-executed at any autonomy level, including Level 4.

---

## Adding or modifying patterns

Changes to this file require a formal architectural review. They cannot be made during normal operation and cannot be authorized by the user alone without that review process.
