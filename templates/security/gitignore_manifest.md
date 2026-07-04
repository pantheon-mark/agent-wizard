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

---

## Code-vs-data classification (what the commit-hygiene guard enforces)

`.gitignore` above says what to *exclude*. This section states the positive rule the
always-on commit-hygiene guard (`.claude/commit_hygiene.sh`) applies at every session
close, so "reversible because it is git-tracked" is enforced, not merely assumed.

| Class | Examples | Committed? |
|-------|----------|-----------|
| **Code / docs / state** | source (`.py`, `.sh`), documents (`.md`), configuration and small state files (`.json`, `.txt`) that define how the system works | **Yes — committed automatically** |
| **Data** | datasets and record exports (`.csv`, `.tsv`, `.xlsx`, `.xls`, `.sqlite`, `.db`, `.parquet`) | **Never committed** |
| **Secrets** | `.env`, private keys (`*.pem`, `*.key`, `id_rsa*`), credential/service-account JSON, session cookies | **Never committed** |

The guard classifies a path as *never-commit* if it is git-ignored by this project's
`.gitignore` **or** matches a built-in secret/data pattern — the built-in set is a
defense-in-depth backstop, so a `.gitignore` that forgets to list a secret still cannot
leak it. It errs toward *not* committing data: a data file you genuinely want tracked,
you commit yourself.

**Already-tracked detection (the `.gitignore` illusory-protection gap).** `.gitignore`
only stops files that are *not yet tracked*. A data or secret file that was committed
**before** its ignore rule existed stays tracked forever — the policy is stated but never
enforced. At every session start and close the guard scans the tracked files for any that
are now git-ignored or match a sensitive pattern; when it finds one it untracks it
(`git rm --cached`, which leaves your working copy on disk) and surfaces a **history-scrub
prompt** — because untracking stops future commits, but the file still lives in the
repository's past history until history is scrubbed (`git filter-repo` / BFG) and any
exposed secret is rotated. It never silently leaves a tracked secret in place.
