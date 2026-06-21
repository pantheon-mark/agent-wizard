# .gitignore Manifest

*Plain-language record of every entry in `.gitignore` — what it protects, why, and which category it belongs to. This file is the human-readable explanation; `.gitignore` is the enforcement.*

*Updated automatically by the system when new entries are added. Never edited manually.*

---

## Baseline entries (written at project initialization)

| Pattern | Category | What it protects | Why |
|---------|----------|-----------------|-----|
| `.env` | Secrets | All credential values | Prevents secrets from being committed to git |
| `/security/session_cookies/` | Secrets | Session cookie files written by Playwright | Ephemeral auth tokens — must not be committed |
| `/logs/` | Privacy | All log files | Logs may contain opaque record IDs; permanently excluded per PII protection rule |
| `node_modules/` | Dependencies | Installed packages | Regenerated from package.json — not part of the project artifact |

---

## Project-specific entries

*Added during wizard setup and at runtime when new file types requiring protection are identified.*

| Pattern | Category | What it protects | Why | Added |
|---------|----------|-----------------|-----|-------|

*No project-specific entries yet. Entries are added here when the system identifies a new file type that should not be committed.*

---

## Categories

| Category | Description |
|----------|------------|
| Secrets | Credential values, tokens, keys — never committed under any circumstances |
| Privacy | Data that may identify individuals — permanently excluded |
| Dependencies | Generated files that can be recreated from a manifest |
| Cache | Temporary or generated files that should not be versioned |
