# Templates — Work Directory

Templates for files in the user's System `/work/` directory.

## Files in this directory

| Template file | Generates | Notes |
|--------------|-----------|-------|
| `work_queue.md` | `/work/work_queue.md` | Empty structure at setup — populated at runtime; contains only open items |
| `issues_log.md` | `/work/issues_log.md` | Empty structure at setup — populated at runtime from Critical and High severity events |
| `stub_tracker.md` | `/work/stub_tracker.md` | Pre-populated at setup with any stubs identified during the wizard interview (credentials pending, sources TBD, etc.) |
| `execution_plan_state.md` | `/work/execution_plan_state.md` | Empty structure at setup — written and cleared at runtime during chunked execution |

`maintenance_mode.md` is a flag file with no template — the wizard documents its existence in `project_instructions.md` and the session entry script handles it. It is created and deleted at runtime.
