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

1. `/security/credentials_registry.md` — the worklist. Each `Pending` row is one credential to set up: it carries the plain-language **Name**, the **ENV variable** (the line in `.env` the value goes next to), **Type**, **Provider**, and a **provisional Expiry type** (treat it as a guess, not a fact — see "Honesty" below). For an OAuth-token row it also carries **Declared scope** (the exact permission the system needs — never a broader one), **Needs admin grant** (Yes/No), and **Scope status** — read all three now, before you say anything to the operator about this credential, since they change what Step 0 and Step 4 below do for this one.
2. `technical_architecture.md` — what each credential is *for* (which part of the system uses it), so you can explain it in the operator's own terms.
3. `.env` — the file the operator pastes values into. It is gitignored; values never leave the machine and never go in chat or any log.

## The loop — one credential at a time

For each `Pending` credential, in order:

### 0. Org-admin grant first, if this one needs it (OAuth only — a first-class, pre-checked task, never a mid-flow surprise)

*Skip entirely if `Needs admin grant` is `No`, or the credential is not an OAuth token.*

If the registry's `Needs admin grant` column says `Yes` for this credential, handle the admin grant **before** doing anything else for it — before Step 1's explanation, before any value is obtained, and long before any live trial. This is deliberate: discovering an admin-grant requirement mid-trial, after something has already failed, is exactly the failure this step exists to prevent.

Tell the operator plainly:

> **[Dependency name]** needs a grant from your organization's admin before it can work — this is [a Google Workspace domain-wide-delegation grant / a Microsoft 365 admin consent / the equivalent for this provider], not something a personal account can do alone.
>
> Here's exactly what to ask for: [the specific scope, named in the registry's `Declared scope` column, described in plain language — e.g. "read-only access to Gmail messages, scope `gmail.readonly`, for the account `[ENV variable]` is stored against"].
>
> I can draft the exact request to send your admin now, or you can send this yourself: [draft a copy-pasteable request naming the provider, the exact scope, and the account/client ID the grant applies to — do not improvise the admin console click-path from memory; point at the provider's current official documentation page for granting it, the same way Step 2 below does for a self-service key].
>
> Let me know once the grant is confirmed on your admin's end — we'll pick this credential back up from here.

Do **not** proceed to Step 1 for this credential until the operator confirms the grant is in place. If the operator wants to move on to a different `Pending` credential in the meantime, let them — this only blocks this ONE credential, not the rest of the setup.

### 1. Explain it (plain, grounded)
One or two sentences: what this credential is, which provider it comes from, and what part of *their* system stops working without it. Use what `technical_architecture.md` says it's for — name their actual workflow, not "the integration."

### 2. Give followable obtaining instructions
Point the operator at the provider's **official documentation page** for creating this credential — a link they can open — rather than click-by-click UI steps (provider screens change often, and a stale click-path is a dead end). Alongside the link, give them this short checklist in plain language:

- **Where to go:** the provider's name + a link to its credential/API-key documentation (search the provider's docs for "create API key" / "create credential" if you don't have the exact URL — and tell the operator that's what you searched, so they can too).
- **What account you need:** whether they need their own account, and whether they need to be an **admin / owner** of it (some keys can only be made by an account owner — if so, say it up front so they don't hit a wall).
- **What to name it:** suggest a clear name, e.g. the system's name.
- **What access to give it:** the specific permission/scope the system needs — for an OAuth token, this is exactly the registry's `Declared scope` (never a broader one "to be safe" — a broader scope can pass a check while the narrower scope the system actually uses is still missing, which is the exact failure this skill's Step 4 now exists to catch offline instead of during a live run).
- **Where the value goes:** the exact line in `.env` — next to `{the ENV variable from the registry}=`. Tell them to paste it **into the file**, never into the chat.
- **What success looks like:** what they should see when it worked (e.g. "the page shows a long string starting with `sk-`").
- **If something looks different:** "If the screen doesn't match, or you can't find where to create it, or it asks for something I haven't mentioned — stop and tell me what you see, and I'll help. Don't guess."

**For OAuth logins and managed or enterprise accounts** (e.g. Microsoft 365 / Outlook for work, Google Workspace): do **not** improvise the auth steps from memory. These vary by account and tenant, they change often, and older methods (basic SMTP passwords, "app passwords") are frequently deprecated or switched off — guidance from memory is likely to be wrong and send the operator down a dead end. Instead: lead with the provider's **current official documentation link**, tell the operator to follow that page over anything you describe from memory, and prefer the simplest method the provider documents today. (The admin/domain-wide-delegation path itself is handled up front in Step 0 above, not here — by the time you reach this step for a credential that needed it, the grant is already confirmed.) Improvised click-paths are for simple, stable, self-service key creation only.

### 3. Wait for them to paste it into `.env`
They edit `.env` directly and tell you when it's in. Do not accept the value in chat; if they paste it in chat, tell them plainly to remove it and put it in the file instead, and do not record or repeat it.

### 4. Verify — honestly, and offline first for a declared scope

**For a credential with a `Declared scope` of `N/A` (API key / basic / cookie — no scope concept):**
- **If you can check it cheaply** (a basic reachability or format check, or a small test call the built system already supports for this provider), do so and tell them the result plainly.
- **If you cannot fully verify it yet** (the part of the system that uses this credential isn't built, or the provider has no cheap check), say so honestly: *"I've stored it. I can't fully test it until the part of your system that uses it runs for the first time — at that point the system will confirm it works and tell you if anything's wrong."* Do not claim it's verified when it isn't.

**For a credential with an actual `Declared scope` (an OAuth token) — run the offline scope grant-check BEFORE anything else, and never skip straight to "Active":**

1. Get the token-introspection response for the credential's provider (the "ONE validation command" — for a Google OAuth token, this is `curl "https://oauth2.googleapis.com/tokeninfo?access_token=$YOUR_TOKEN"`, substituting the actual value; for another provider, use its equivalent tokeninfo/introspection endpoint — this is a safe, read-only call about the token itself, never a call against real data).
2. Run, from the project root: `python3 agents/lib/external_write/adapters.py --op-kind "<the op_kind this credential's scope belongs to>" --token-info-json '<the JSON response from step 1>'`. This prints exactly one of `granted`, `not_granted`, or `n/a` — never a traceback, and it never touches the real vendor surface (no read, no write; see the printed word itself, not any other output, as the result).
3. **If it prints `granted`:** the token currently carries the declared scope. Set `Scope status` to `granted, not yet exercised` — **never** `verified` yet; nothing has actually used this scope successfully. If this is a **read-only** scope and the built system already has a safe, benign read that uses exactly this scope, you may run that ONE benign read now, and if it succeeds, that IS the exercise — set `Scope status` to `verified` and record today's date. If this is a **write** scope, do **not** try to exercise it here: its exercise is the first bounded, gated live apply during the phase's own supervised trial (already gated by the rest of this system's safety machinery) — leave it `granted, not yet exercised` until that happens.
4. **If it prints `not_granted`:** stop. Tell the operator plainly: *"The [provider] credential is stored, but it doesn't yet have the specific permission ([declared scope, in plain language]) this system needs — a broader-looking permission isn't the same thing. Nothing failed on your end; this is a normal part of setup. To fix it: [name the exact place to grant the specific scope — re-run Step 2's obtaining instructions, or Step 0's admin-grant request if `Needs admin grant` is `Yes`]. Once that's done, come back here and I'll re-check automatically."* Set `Scope status` to `not granted`. Do **not** mark the credential `Active` while this is `not granted` — the credential row's overall `Status` may still show the value is stored, but this scope is not yet usable, and any phase that needs it stays blocked from its live trial (see the next-phase skill's Step 3) until this is fixed — the rest of the build is never blocked by this.
5. **If it prints `n/a`:** this op_kind declares no read-only scope to check (or has no grant-check support) — treat it the same as the non-scope-credential path above.

### 5. Record it
Update this credential's row in `/security/credentials_registry.md`:
- `Status`: `Active` if the credential itself is stored and (for a scoped credential) its declared scope is at minimum `granted, not yet exercised`; otherwise `Pending` stays until that's true (note "stored, awaiting first-use verification").
- `Last verified`: today's date if you verified it, otherwise leave it.
- `Expiry type` / `Expiry date`: fill in only what you now actually know (e.g. the provider's page told you it expires on a date). If you still don't know, leave it `Unknown` — the system tracks it and re-checks on the configured cadence.
- `Scope status` (OAuth only): exactly one of `N/A` / `not granted` / `granted, not yet exercised` / `verified`, per Step 4 above. **Deny-by-default: never write `verified` without an actual exercise having succeeded** — a working check against a different, broader scope, or a grant-check that merely printed `granted`, is never enough on its own.

Never write the credential **value** into the registry or any other file — `.env` only.

### 6. Move on
Tell them that one's done, and go to the next `Pending` row. Keep momentum but don't rush them.

## If a later run reports a credential or permission problem

Some steps in this system (a scheduled job, a phase's live run) are built to catch an auth or setup failure themselves and report it as one plain line — never a raw error dump. If the operator shows you a message like that, or asks about one, it means exactly what it says: come back to this skill, find the credential it names, and re-run Step 4's offline check before anything else — do not guess at a fix, and do not walk the operator into an admin-console change that Step 4 has not actually pointed them at.

## Honesty about expiry (important)

The registry's expiry guess came from general knowledge of the provider, not from the operator's account — it can be wrong or out of date. Never state a provider's expiry rules as fact to the operator. If you're unsure, say so, leave it `Unknown`, and rely on the system's scheduled credential check to confirm by watching. The system already warns the operator ahead of any expiry it knows about and re-checks the permanent ones on a set cadence — so the operator does not have to track this themselves.

## When all credentials are done

Summarize plainly: how many are set up, any that are stored-but-not-yet-verified (and that the system will confirm on first use), and what happens next (the operator's first agent build, per the build prompt the wizard produced). Update `/work/stub_tracker.md` to clear the "credentials pending" stub for each one now in place.
