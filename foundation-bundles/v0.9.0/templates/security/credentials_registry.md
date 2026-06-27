# Credentials Registry

*Metadata for all credentials used by this system. Never contains values — values live in `.env` only. This file is committed to git; `.env` is not.*

*Updated by the system when credentials are added, rotated, or verified. Never edited manually.*

---

| Name | ENV variable | Type | Provider | Expiry type | Expiry date | Rotation method | Last verified | Status |
|------|-------------|------|----------|------------|------------|----------------|--------------|--------|
{{CREDENTIAL_REGISTRY_ROWS}}

*Pre-populated from the interview as `Pending` rows — metadata only, never values. At first boot the credential-setup skill walks you through obtaining each one, you paste the value into `.env`, the system verifies it, and the row moves to `Active`. The `ENV variable` column is the join key between this metadata and the matching line in `.env`.*

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
| Active | Verified working |
| Expiring | Within rotation lead-time window — rotation in progress |
| Expired | Past expiry — system cannot use this credential until rotated |
| Pending | Identified during wizard setup but not yet configured |
