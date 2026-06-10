---
description: "First-boot credential setup — walk the operator through obtaining, pasting, and verifying each credential the system needs, one at a time, then record it. Use at first boot, when credentials are pending, or when the operator says 'set up credentials' / 'add a credential' / a credential check reports a missing or invalid key."
---

# Credential Setup

This skill walks the operator through getting each credential the system needs into place — **after the system is built**, not during the wizard interview. The wizard captured *what* credentials are needed; this is where the operator gets and pastes the actual values.

The operator is non-technical. Go one credential at a time. Never make them read an error or guess. Plain language throughout.

## When to run this

- **At first boot**, if `/security/credentials_registry.md` has any rows with `Status: Pending`.
- When the operator says "set up credentials", "add a credential", or similar.
- When a credential check reports a missing or invalid key (rotate/replace flow — same steps, one credential).

If the registry has **no** `Pending` rows and no credential is reported broken, there is nothing to do — tell the operator their credentials are already set up and stop.

## What you read first

1. `/security/credentials_registry.md` — the worklist. Each `Pending` row is one credential to set up: it carries the plain-language **Name**, the **ENV variable** (the line in `.env` the value goes next to), **Type**, **Provider**, and a **provisional Expiry type** (treat it as a guess, not a fact — see "Honesty" below).
2. `technical_architecture.md` — what each credential is *for* (which part of the system uses it), so you can explain it in the operator's own terms.
3. `.env` — the file the operator pastes values into. It is gitignored; values never leave the machine and never go in chat or any log.

## The loop — one credential at a time

For each `Pending` credential, in order:

### 1. Explain it (plain, grounded)
One or two sentences: what this credential is, which provider it comes from, and what part of *their* system stops working without it. Use what `technical_architecture.md` says it's for — name their actual workflow, not "the integration."

### 2. Give followable obtaining instructions
Point the operator at the provider's **official documentation page** for creating this credential — a link they can open — rather than click-by-click UI steps (provider screens change often, and a stale click-path is a dead end). Alongside the link, give them this short checklist in plain language:

- **Where to go:** the provider's name + a link to its credential/API-key documentation (search the provider's docs for "create API key" / "create credential" if you don't have the exact URL — and tell the operator that's what you searched, so they can too).
- **What account you need:** whether they need their own account, and whether they need to be an **admin / owner** of it (some keys can only be made by an account owner — if so, say it up front so they don't hit a wall).
- **What to name it:** suggest a clear name, e.g. the system's name.
- **What access to give it:** the specific permission/scope the system needs, if the provider asks — and keep it to the minimum.
- **Where the value goes:** the exact line in `.env` — next to `{the ENV variable from the registry}=`. Tell them to paste it **into the file**, never into the chat.
- **What success looks like:** what they should see when it worked (e.g. "the page shows a long string starting with `sk-`").
- **If something looks different:** "If the screen doesn't match, or you can't find where to create it, or it asks for something I haven't mentioned — stop and tell me what you see, and I'll help. Don't guess."

**For OAuth logins and managed or enterprise accounts** (e.g. Microsoft 365 / Outlook for work, Google Workspace, anything behind an organization's admin): do **not** improvise the auth steps from memory. These vary by account and tenant, they change often, and older methods (basic SMTP passwords, "app passwords") are frequently deprecated or switched off — guidance from memory is likely to be wrong and send the operator down a dead end. Instead: lead with the provider's **current official documentation link**, tell the operator to follow that page over anything you describe from memory, and prefer the simplest method the provider documents today. Surface the "this may need your account's admin, or a few minutes with someone technical" path **early** — and offer to draft the exact request they can send their admin — rather than after they're stuck. Improvised click-paths are for simple, stable, self-service key creation only.

### 3. Wait for them to paste it into `.env`
They edit `.env` directly and tell you when it's in. Do not accept the value in chat; if they paste it in chat, tell them plainly to remove it and put it in the file instead, and do not record or repeat it.

### 4. Verify — honestly
- **If you can check it cheaply** (a basic reachability or format check, or a small test call the built system already supports for this provider), do so and tell them the result plainly.
- **If you cannot fully verify it yet** (the part of the system that uses this credential isn't built, or the provider has no cheap check), say so honestly: *"I've stored it. I can't fully test it until the part of your system that uses it runs for the first time — at that point the system will confirm it works and tell you if anything's wrong."* Do not claim it's verified when it isn't.

### 5. Record it
Update this credential's row in `/security/credentials_registry.md`:
- `Status`: `Active` if verified, otherwise `Pending` stays until first real use confirms it (note "stored, awaiting first-use verification").
- `Last verified`: today's date if you verified it, otherwise leave it.
- `Expiry type` / `Expiry date`: fill in only what you now actually know (e.g. the provider's page told you it expires on a date). If you still don't know, leave it `Unknown` — the system tracks it and re-checks on the configured cadence.

Never write the credential **value** into the registry or any other file — `.env` only.

### 6. Move on
Tell them that one's done, and go to the next `Pending` row. Keep momentum but don't rush them.

## Honesty about expiry (important)

The registry's expiry guess came from general knowledge of the provider, not from the operator's account — it can be wrong or out of date. Never state a provider's expiry rules as fact to the operator. If you're unsure, say so, leave it `Unknown`, and rely on the system's scheduled credential check to confirm by watching. The system already warns the operator ahead of any expiry it knows about and re-checks the permanent ones on a set cadence — so the operator does not have to track this themselves.

## When all credentials are done

Summarize plainly: how many are set up, any that are stored-but-not-yet-verified (and that the system will confirm on first use), and what happens next (the operator's first agent build, per the build prompt the wizard produced). Update `/work/stub_tracker.md` to clear the "credentials pending" stub for each one now in place.
