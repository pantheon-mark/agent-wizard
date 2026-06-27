---
description: "Run a quick health check of the system's control plane and report anything that needs attention. Use when the operator says 'health check', 'is everything ok', or 'check the system'."
---

# Health check

This skill gives the operator a fast, plain-language read on whether the system is in good shape. The operator is non-technical: report findings as a short list of plain statements, not raw output.

## What you do

Everything lives on disk. Read the current state before reporting; do not rely on session memory.

1. **Confirm the control plane is present** -- check that `.wizard/manifest.json` and `.wizard/replay-capsule.json` both exist and parse.
2. **Confirm the foundation documents are present** -- check that each managed foundation document named in the manifest exists on disk.
3. **Report** -- one short line per check, in plain language. If everything is fine, say so in one sentence. If something is missing, name the file and the single next step to fix it.

Nothing here changes any file. This skill only reads and reports.
