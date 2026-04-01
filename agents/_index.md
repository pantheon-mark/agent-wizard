# Agent Prompt File Templates

Templates used to generate per-agent prompt files in the user's System `/agents/prompts/` directory.

## Files in this directory

| Template file | Purpose |
|--------------|---------|
| `orchestrator_prompt.md` | Template for the orchestrator agent — every system has one; manages the work queue, spawns specialist agents, coordinates handoffs |
| `qa_agent_prompt.md` | Template for the QA agent — every system has one; observes and challenges, never modifies production outputs, runs security audits |
| `agent_prompt_template.md` | Generic template for dynamically-generated specialist agents; the wizard populates this with the specific agent's role, permissions, and completion criteria from ARCH-2 and ARCH-3 answers |

## Required elements in every agent prompt template

All three templates must include:
- Role and identity statement
- Explicit permission boundary (what the agent can and cannot do)
- Step-level and task-level completion criteria
- The foundational document integrity constraint verbatim
- PII redaction rule (no raw personal data in any log entry)
- Three-strikes escalation behavior
- Tier-language model references (High / Standard / Fast) — no specific model strings
- Blast radius scope declaration requirement (before any file write, declare intended write directories)
