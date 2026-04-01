# Templates — Project Root Files

Templates for files generated in the root of the user's System project. Values in `{{DOUBLE_BRACES}}` are filled in from wizard interview answers before writing to the user's project.

## Files in this directory

| Template file | Generates | Populated from | Status |
|--------------|-----------|---------------|--------|
| `CLAUDE.md` | `CLAUDE.md` | P1-1 (project name), P1-2 (project purpose), autonomy level (Level 2 at wizard completion) | ✅ Complete (2026-04-01) |
| `project_instructions.md` | `project_instructions.md` | UP-1–5, FIN-1–2, NOTIF-1–5, ERR-2, QA-4, CONC-1–2, START-1–2, DRIFT-1, SCALE-4, Item 16 model mapping | ✅ Complete (2026-04-01) |
| `session_bootstrap.md` | `session_bootstrap.md` | All phases — living orientation file | ✅ Complete (2026-04-01) |
| `pending_decisions.md` | `pending_decisions.md` | Empty structure — populated at runtime | Pending |
| `manual.md` | `manual.md` | Static — Mac installation guide | Pending |
| `gitignore_template` | `.gitignore` | Static baseline + credential entries from CRED-2 | Pending |

`start-session.sh` is in `/wizard/scripts/` — it is a shell script, not a document template.
`.env` is not templated — created empty; values added during CRED-2.
