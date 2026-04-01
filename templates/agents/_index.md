# Templates — Agents Directory

Templates for files in the user's System `/agents/` directory that are generated at wizard setup time.

## Files in this directory

| Template file | Generates | Notes |
|--------------|-----------|-------|
| `roster.md` | `/agents/roster.md` | Pre-populated from ARCH-2 and ARCH-3 answers — agent names, roles, criticality tiers |
| `cron_config.md` | `/agents/cron/cron_config.md` | Structure only at setup; cron entries added during the closing sequence as agent schedules are confirmed |

Per-agent prompt files are generated from `/wizard/agents/` templates — not from here.
Per-agent invocation scripts are generated from `/wizard/scripts/` templates — not from here.

Runtime-only directories (no templates needed — wizard creates empty directories):
- `/agents/handoffs/` — handoff envelope JSON files written at runtime
- `/agents/failed_queue/` — quarantined tasks written at runtime
- `/agents/prompts/` — populated by wizard from `/wizard/agents/` templates
- `/agents/scripts/` — populated by wizard from `/wizard/scripts/` templates
- `/agents/checkpoints/` — checkpoint files written at runtime
