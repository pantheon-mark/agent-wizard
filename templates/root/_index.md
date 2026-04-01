# Templates — Project Root Files

Templates for files generated in the root of the user's System project. Values in `{{DOUBLE_BRACES}}` are filled in from wizard interview answers before writing to the user's project.

## Files in this directory

| Template file | Generates | Populated from |
|--------------|-----------|---------------|
| `project_instructions.md` | `project_instructions.md` | UP-1–5, FIN-2, NOTIF-1–5, ERR-2, QA-4, START-1–2, DRIFT-1, SCALE-4, Item 16 model mapping |
| `session_bootstrap.md` | `session_bootstrap.md` | All phases — living orientation file |
| `pending_decisions.md` | `pending_decisions.md` | Empty structure — populated at runtime |
| `manual.md` | `manual.md` | Static — Mac installation guide |
| `gitignore_template` | `.gitignore` | Static baseline + credential entries from CRED-2 |

`start-session.sh` is in `/wizard/scripts/` — it is a shell script, not a document template.
`.env` is not templated — created empty; values added during CRED-2.
