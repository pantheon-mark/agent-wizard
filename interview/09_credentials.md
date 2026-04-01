# 09 — Credentials

## What this file does
Identify every credential the system needs, walk the user through obtaining each one, write them safely to disk, and configure expiry and rotation preferences. Claude proposes the full credential inventory from the vision, approach, and architecture documents — the user confirms and adjusts but is never asked to enumerate credentials from scratch. Produces `.gitignore`, `.env`, `/security/credentials_registry.md`, and `/security/gitignore_manifest.md`.

## When this file runs
After `08_architecture.md` completes and ARCHITECTURE_CONFIRMED = true in the staging file.

## Prerequisites
ARCHITECTURE_CONFIRMED = true in the staging file. Vision document, approach document, and technical architecture document confirmed on disk.

---

## Context check

Before beginning this phase, assess whether your context window is near the autocompaction threshold.

If it is: write the current staging file to disk, give the user the following instruction, and stop:

> Your project files are saved. Before we continue, run `/clear` in Claude Code, then paste this prompt to resume:
>
> "Resume wizard from 09_credentials.md. ARCHITECTURE_CONFIRMED = true. Read the staging file and technical architecture document, then begin the credentials phase."

Do not begin CRED-1 until you are confident the full phase will complete before compaction risk.

---

## How to run this phase

Read the vision document, approach document, and technical architecture document before speaking. Build a complete candidate credential list from everything you find — data sources, APIs, integrations, external services, any system the agents will connect to.

**The user does not design the credential list.** You propose it. They confirm, remove, or add.

No credential value ever appears in the conversation. Values go directly into `.env`. The registry stores metadata only: name, type, provider, expiry behavior, refresh method.

---

## CRED-1 — Credential inventory [DYNAMIC]

Present the proposed credential inventory. For each credential: what it is, what the system needs it for, and what stops working without it.

**Say:**

> Before we start collecting anything, I want to show you every credential your system will need — so nothing surprises you later.
>
> Based on your vision, approach, and architecture documents, here's what I'm seeing:
>
> **[Credential plain-language name]**
> [What it is — one sentence in plain language.] Your system needs it to [what it does]. Without it, [what stops or degrades].
>
> **[Repeat for each credential.]**
>
> Does this list look complete? Is there anything here you know you don't have access to yet, or anything missing that you'd expect to need?

**Wait for answer.**

- If the user confirms: proceed to CRED-1a.
- If the user removes a credential: note what capability is affected, confirm, and remove it from the list.
- If the user adds a credential: add it with a proposed name, function, and impact statement. Confirm before proceeding.
- If the user doesn't have a credential yet: mark it as pending. It must be obtained before the system can run fully. Note it clearly.

---

## CRED-1a — Create .gitignore and .env [INTERNAL]

After the credential inventory is confirmed and before any values are collected, create the protection files. This sequence is non-negotiable: `.gitignore` is written before `.env` exists.

**Step 1 — Create `.gitignore`**

Write `[PROJECT_DIR]/.gitignore`. Include at minimum:

```
# Secrets — never committed
.env

# Logs — operational data, stays local
/logs/

# Session cookies — ephemeral, never committed
/security/session_cookies/

# OS artifacts
.DS_Store
```

**Step 2 — Create `/security/gitignore_manifest.md`**

Write a plain-language record of every entry in `.gitignore`:

```markdown
# .gitignore Manifest

| Entry | What it protects | Why | Category |
|-------|-----------------|-----|----------|
| `.env` | All credential values | Secrets must never leave the local machine via git | Secrets |
| `/logs/` | All operational logs | Logs may contain PII; they are local-only data | Logs |
| `/security/session_cookies/` | Session cookies for username/password sites | Ephemeral credentials; never committed | Secrets |
| `.DS_Store` | macOS folder metadata | Not project content | OS artifacts |
```

**Step 3 — Create `.env`**

Write `[PROJECT_DIR]/.env` as an empty file with a header comment only:

```
# Credentials — values added during wizard setup
# This file is gitignore-protected. Never commit it.
```

Write an audit trail entry: `.gitignore created before .env — sequence confirmed`.

**Say:**

> Before we collect any credentials, I've set up the protection files. Your credentials will be stored in a file that's permanently excluded from git — they'll never end up in your version history by accident.
>
> Ready to go through each one?

**Wait for confirmation, then proceed to CRED-2.**

---

## CRED-2 — Provider-specific onboarding [DYNAMIC]

Work through each confirmed credential in turn. For each one:

1. Explain what it is and where it comes from — in plain language for someone who has never seen an API key.
2. Give exact step-by-step instructions to obtain it (register, navigate, generate, copy permissions).
3. Write a placeholder line to `.env` (e.g., `OPENAI_API_KEY=`).
4. Ask the user to add the value directly to `.env` — never to paste it in the conversation.
5. Test that the credential works.
6. If it passes: write the metadata entry to `/security/credentials_registry.md`. Write an audit trail entry.
7. If it fails: give a specific diagnosis and the exact fix. Do not move on until the credential is verified.

**For each credential, say:**

> **[Credential plain-language name]**
>
> [What it is — one sentence.] Here's how to get it:
>
> 1. [Exact step — e.g., "Go to [provider] and sign in or create an account."]
> 2. [Exact step — e.g., "Open your account settings and find the API section."]
> 3. [Exact step — e.g., "Click 'Create new key.' Give it a name like '[project-name]-system'."]
> 4. [Exact step — permissions to select, where applicable.]
> 5. [Exact step — e.g., "Copy the key. You'll only see it once."]
>
> When you have it: open your `.env` file (it's at `[PROJECT_DIR]/.env`) and add the value next to `[ENV_VAR_NAME]=`. Don't paste it here — add it directly to the file.
>
> Tell me when it's in the file and I'll verify it.

**Wait for confirmation, then test the credential.**

- If verification passes: say "That one's working. Moving on." Write the metadata entry to the registry. Write the audit trail entry.
- If verification fails: give a specific diagnosis. "This usually means [X]. Check [exact location] and [exact fix]. Try again when you're ready."

Do not proceed to the next credential until the current one is verified or explicitly marked as pending by the user.

**`/security/credentials_registry.md` entry format:**

```markdown
| Name | Type | Provider | Expiry | Refresh Method | Last Verified |
|------|------|----------|--------|----------------|---------------|
| [Plain-language name] | [API key / OAuth token / Username+password / Other] | [Provider name] | [Date or "No expiry"] | [Auto / Manual / N/A] | [Date] |
```

After all credentials are verified (or pending status confirmed), proceed to CRED-3.

---

## CRED-3 — Rotation lead time [FIXED — topic]

**Say:**

> For credentials that expire, I can warn you before they stop working — so you have time to rotate them without anything breaking.
>
> How many days' notice do you want before a credential expires?
>
> I'd suggest **14 days** — that's enough time to handle it without urgency, even if you're busy. But if you want more or less buffer, tell me.

**Wait for answer.**

- If the user accepts the default: confirm "14 days it is" and proceed.
- If the user chooses a different value: confirm the chosen value, note the rationale briefly if they gave one, and proceed.

Write the configured value to the staging file: `ROTATION_LEAD_TIME_DAYS = [n]`.

---

## CRED-4 — No-expiry confirmation cadence [FIXED — topic]

**Say:**

> Some credentials don't expire — API keys from providers that don't rotate them automatically. For those, I'll check in with you on a schedule to confirm they're still valid, so nothing quietly breaks without warning.
>
> How often should I do that check?
>
> **Quarterly** is the default — once every three months. That's a reasonable interval for permanent credentials.
>
> You can choose: monthly, quarterly, or twice a year.

**Wait for answer.**

- If the user accepts the default: confirm "Quarterly check-ins for permanent credentials" and proceed.
- If the user chooses a different cadence: confirm the choice and proceed.

Write the configured value to the staging file: `NO_EXPIRY_CADENCE = [monthly / quarterly / biannual]`.

---

## CRED-5 — Session lifetime [EXPLANATION]

*Show this section only if the confirmed credential list includes any username/password credentials.*

**Say:**

> For sites where you log in with a username and password, the system works differently. Instead of an API key, it logs in like a person would — fills in the form, gets a session, and remembers it.
>
> Sessions don't last forever. The system will learn how long each session stays valid and refresh it automatically before it expires. You don't need to configure anything for this — I just want you to know how it works.
>
> If a session fails and can't be refreshed automatically, the system will stop and tell you what to do.
>
> Does that make sense?

**Wait for confirmation.** If the user has questions, answer them in plain language. Then proceed.

---

## Write credentials setup to disk

After CRED-1 through CRED-5 are complete:

1. Verify `.gitignore` has `.env` listed and the `.env` file exists.
2. Verify `/security/credentials_registry.md` has an entry for every confirmed credential.
3. Verify `/security/gitignore_manifest.md` is current.
4. Create `/security/session_cookies/` directory if any username/password credentials exist. Add it to the gitignore manifest if not already present.

Write an audit trail entry: `Credentials registry initialized — [n] credentials onboarded, [n] pending`.

**Say:**

> Credentials are set up. Every key is stored safely on your machine, protected from version control.
>
> Here's a summary of what we configured:
>
> - **[n] credentials** active and verified
> - [**[n] credentials** pending — still need to be obtained] *(omit line if none pending)*
> - Expiry alerts set to **[n] days** before expiry
> - No-expiry check-ins every **[cadence]**
>
> Next we'll set up the input validation layer — the guardrails that check what goes into your system.

Update staging file: CREDENTIALS_CONFIRMED = true

---

## Success condition

CRED-1 through CRED-5 complete. `.gitignore` and `.env` on disk. `/security/credentials_registry.md` initialized with all confirmed credentials. `/security/gitignore_manifest.md` current. ROTATION_LEAD_TIME_DAYS and NO_EXPIRY_CADENCE written to staging file. CREDENTIALS_CONFIRMED = true in the staging file. Proceed to `10_validation.md`.
