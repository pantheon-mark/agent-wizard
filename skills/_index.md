# Skill File Templates

Skill file templates the wizard uses when generating skills for the user's System during the build phase.

## Files in this directory

| Template file | Purpose |
|--------------|---------|
| `skill_template_external.md` | Template for skills that make external MCP or API calls. Includes the degradation path baked in: local output fallback write location and plain-language action prompt template for when the MCP call fails. |
| `skill_template_internal.md` | Template for internal-only skills that only read/write local files. No degradation logic — internal skills have no external dependency. |

## Skill requirements (both templates)

All generated skill files must pass the four agent-readiness criteria:
1. **Description as routing signal** — contains exact phrases an orchestrator will generate when needing this skill (not a human-readable label)
2. **Completely specified output format** — exact JSON field names or exact markdown section names
3. **Deterministic edge case handling** — explicit error codes and defined failure modes
4. **Composable output** — structured for machine consumption, not prose

Both templates enforce:
- YAML frontmatter with single-line description field (1,024 char maximum — multi-line causes silent disappearance)
- Output format specification section
- Edge case and error code section
- No user-facing jargon

## OB1 skills

The OB1 knowledge-work skills library (github.com/NateBJones-Projects/OB1/tree/main/skills) is the first place to check before generating a custom skill. If an existing OB1 skill covers the need, adapt it rather than build from scratch. The integrity gate applies — verify the skill meets the four agent-readiness criteria before incorporating.
