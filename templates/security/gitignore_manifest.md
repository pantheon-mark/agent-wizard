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

**The guard is fail-safe (deny-by-default).** It auto-commits *only* what it can
**positively** classify as safe. Anything it cannot — data-shaped files, unknown file
types, ambiguous paths, a `.json` that is not a known config file — is **never
auto-committed**; instead it is **surfaced for your decision** (never silently committed,
never silently discarded). A brand-new data extension nobody enumerated is refused because
it is not on the safe list, not allowed because it is not on a deny list.

| Class | Examples | Auto-committed? |
|-------|----------|-----------------|
| **Code / docs** | source (`.py`, `.sh`, `.js`, …), documents (`.md`, `.rst`), configuration source (`.yml`, `.yaml`, `.toml`, `.cfg`, `.ini`), and known config files by name (`.gitignore`, `Makefile`, `requirements.txt`) | **Yes — committed automatically** |
| **System config / state by known path** | `.claude/settings.json`, `.wizard/manifest.json`, and the system's own state/tracker files under its config directories | **Yes — committed automatically** |
| **Data** | datasets, record exports, and dumps — `.csv`, `.tsv`, `.xlsx`, `.sqlite`, `.db`, `.parquet`, `.jsonl`, `.ndjson`, `.pkl`, `.npy`, `.dat`, **a `.json` that is a data export rather than a known config file**, and any unknown / data-shaped extension | **No — surfaced for your decision, never auto-committed** |
| **Secrets** | `.env`, private keys (`*.pem`, `*.key`, `id_rsa*`), credential/service-account JSON, session cookies | **No — never committed** |

**Config vs. data — the `.json` / `.txt` rule.** A `.json` is committed only when it sits
at a **known configuration path** (for example `.claude/settings.json` or
`.wizard/manifest.json`). A `.json` anywhere else — or any data-shaped file such as
`client_export.json`, a `.jsonl` event log, or a `.pkl` model dump — is treated as data:
the guard will not auto-commit it and will surface it so you can decide. `.txt` is likewise
**not** blanket-committable: a `.txt` is committed only when it is a known config file by
name (e.g. `requirements.txt`); a `.txt` data dump is surfaced, not committed.

The never-commit set is enforced two ways: a path is refused if it is git-ignored by this
project's `.gitignore` **or** if it matches a built-in secret/data pattern — the built-in
set is a defense-in-depth backstop, so a `.gitignore` that forgets to list a secret still
cannot leak it, and a data file is refused even if it is placed under a known config path.
Because classification is deny-by-default, the guard errs firmly toward *not* committing: a
data file you genuinely want tracked, you commit yourself.

**Already-tracked detection (the `.gitignore` illusory-protection gap).** `.gitignore`
only stops files that are *not yet tracked*. A data or secret file that was committed
**before** its ignore rule existed stays tracked forever — the policy is stated but never
enforced. At every session start and close the guard scans the tracked files for any that
are now git-ignored or match a sensitive pattern; when it finds one it untracks it
(`git rm --cached`, which leaves your working copy on disk) and surfaces a **history-scrub
prompt** — because untracking stops future commits, but the file still lives in the
repository's past history until history is scrubbed (`git filter-repo` / BFG) and any
exposed secret is rotated. It never silently leaves a tracked secret in place.
