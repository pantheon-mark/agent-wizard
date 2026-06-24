# Agent Roster

*All agents in this system — their roles, criticality tiers, and current status. Pre-populated from the wizard interview (ARCH-2, ARCH-3). Updated when agents are added, modified, or decommissioned.*

*Changes to this file require deliberate architectural review. Never edited manually outside that process.*

---

| Agent name | Role | What it does | Criticality tier | Status | Prompt file | Script file |
|-----------|------|-------------|-----------------|--------|-------------|------------|
{{AGENT_ROSTER_ROWS}}

---

## Criticality tiers

| Tier | Meaning | Failure behavior |
|------|---------|-----------------|
| Critical | System cannot function without this agent | Immediate stop-the-system alert; no fallback |
| Standard | Important but system can operate in degraded mode | High-severity alert; system continues with limitations noted |
| Supporting | Enhances operation but not required for core function | Warning alert; system continues normally |

## Status values

| Status | Meaning |
|--------|---------|
| Active | Built, tested, and running |
| Pending build | Approved in wizard but not yet built |
| Paused | Built but not currently scheduled to run |
| Decommissioned | Removed from active operation |
