# Wizard Changes — Public Release Notes

This file is the canonical public release-notes + provenance manifest for the `wizard/` subtree distributed via the public `pantheon-mark/agent-wizard` repository.

Each entry records:

- A short public-facing change note
- `Source-Meta-Commit:` — the commit SHA in the private build repo at the moment of publication
- The public repo commit SHA after the publication is complete (filled in after subtree push)

Entries appear newest-first.

---

## 2026-05-04 — v0 license + IP posture ratified

**Public-facing change:** added `LICENSE` (MIT, copyright 2026 Mark Tobias), `GENERATED_OUTPUTS.md` (operator's free-use grant for wizard-generated project content), and this `CHANGES.md` (canonical public release-notes + provenance manifest). Closes the prior "all rights reserved" default state for the public repository.

- Source-Meta-Commit: `7703dd7`
- Public repo commit: `bfc327e`

---

## Provenance discipline

- Every change to `wizard/` that reaches the public repo via `git subtree push` should be recorded above.
- The canonical authority is this file; commit messages may copy the same information but never replace it.
- For substantial structural changes, include a public-facing summary only. Do not reference private build-project governance, review records, or local paths.
- This file lives inside the public subtree. Its content is public-readable; treat all entries accordingly.
