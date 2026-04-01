# Script Templates

Shell script templates installed into the user's System project during wizard setup.

## Files in this directory

| Template file | Generates | Purpose |
|--------------|-----------|---------|
| `start_session_template.sh` | `start-session.sh` in System root | Session entry script — handles all three flag variants: standard start, `--resume`, `--resume --alert`. Reads state files, sets maintenance mode, coordinates startup sequence. Wizard-generated and verified before closing sequence proceeds. |
| `agent_invocation_template.sh` | `/agents/scripts/[agent_name].sh` per agent | Per-agent invocation script — loads the agent's prompt file from `/agents/prompts/`, loads required context from disk, invokes Claude CLI, writes outputs to defined disk locations using atomic write pattern, captures exit status, logs completion or failure. |

## Script requirements

Both templates must:
- Use atomic write pattern for all outputs (write to temp file, rename to final location)
- Load the agent prompt file before any invocation — abort if prompt file is missing
- Capture and handle Claude CLI exit status
- Write a log entry on completion (success or failure)
- Be executable (`chmod +x`) — the wizard sets permissions when generating
