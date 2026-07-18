# Credentials Registry

*Metadata for all credentials used by this system. Never contains values — values live in `.env` only. This file is committed to git; `.env` is not.*

*Updated by the system when credentials are added, rotated, or verified. Never edited manually.*

---

| Name | ENV variable | Type | Provider | Expiry type | Expiry date | Rotation method | Last verified | Status | Declared scope | Needs admin grant | Scope status |
|------|-------------|------|----------|------------|------------|----------------|--------------|--------|---------------|-------------------|--------------|
{{CREDENTIAL_REGISTRY_ROWS}}

*Pre-populated from the interview as `Pending` rows — metadata only, never values. At first boot the credential-setup skill walks you through obtaining each one, you paste the value into `.env`, the system verifies it, and the row moves to `Active`. The `ENV variable` column is the join key between this metadata and the matching line in `.env`.*

*The three right-hand columns only mean something for an OAuth-scoped credential; every other type carries `N/A` in all three, always.*

---

## Credential types

| Type | Description |
|------|------------|
| API key | Static key issued by a provider |
| OAuth token | Access token from OAuth flow — may auto-refresh |
| Session cookie | Username/password site session — managed by Playwright |
| Password | Direct credential — stored in `.env`, used by Playwright |
| No-expiry | Credential with no known expiry — confirmed on configured cadence |

## Status values

| Status | Meaning |
|--------|---------|
| Active | The credential value is stored and reachable. For an OAuth credential this is a SEPARATE axis from whether the specific scope this system needs actually works — that is tracked on its own in the `Scope status` column, never folded into `Active`. A credential can be `Active` while its `Scope status` is still `granted, not yet exercised` (or even `not granted`): the value is in place, but the scope's real use is proven separately. |
| Expiring | Within rotation lead-time window — rotation in progress |
| Expired | Past expiry — system cannot use this credential until rotated |
| Pending | Identified during wizard setup but not yet configured |

## Declared scope, Needs admin grant, and Scope status (OAuth credentials only)

*`Status` above says whether the credential VALUE is stored and usable. It is a separate claim from whether the specific OAuth scope this system actually needs has been checked and proven to work — that is what these three columns track, deliberately kept apart so one is never mistaken for the other. This is the fix for a real incident: a credential was once recorded as working from a check against a broader scope than the one the system actually used, and the mismatch was only discovered when a real run failed.*

- **Declared scope** — the exact OAuth scope this credential's use requires (e.g. `gmail.readonly`). `N/A` for a non-OAuth credential (API key, session cookie, password) — there is no scope concept to check.
- **Needs admin grant** — `Yes` if obtaining or granting this scope needs an organization admin (a Google Workspace or Microsoft 365 admin, a domain-wide-delegation grant, or similar) rather than something the operator can do themselves. Known and recorded up front, at setup — never discovered for the first time mid-way through a live trial.
- **Scope status** — deny-by-default: this is `verified` **only** when a real, recorded use of exactly this scope has actually succeeded. Never write `verified` for any other reason, including a working check against a *different*, broader scope.

| Scope status | Meaning |
|--------------|---------|
| N/A | This credential has no OAuth-scope concept (`Declared scope` is `N/A` too). |
| (set at runtime) | Not yet checked. |
| not granted | An offline check found the token does **not** currently carry this exact declared scope. A live trial that needs this scope is blocked until this is fixed — the rest of the system stays buildable and usable. |
| granted, not yet exercised | An offline check confirmed the token carries this scope, but no real call using it has succeeded yet. Honest and normal — never upgrade this to `verified` without an actual successful use. |
| verified | A real call using exactly this declared scope has succeeded, and that use is on record. The only status that means "this scope actually works." |
