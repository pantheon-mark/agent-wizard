# Document Impact Map

*Claude-owned and Claude-maintained map of which documents must be updated when each type of change occurs. This map is the primary mechanism for triggered document updates. Updated when new change categories are identified in operation.*

*Updated by the system. Never edited manually by the user.*

---

## How this works

When a change event occurs, the system consults this map to identify which documents must be updated before the change is logged as done. For each affected document, it generates a three-part change summary: (1) what triggered the update, (2) what Claude assessed, and (3) what changed.

**Exceptions:** Vision document and execution plan scope updates are surfaced to the user rather than applied automatically — these require user confirmation before any changes are made.

---

## Standard change event taxonomy

| Change event | Foundation documents to update | Operational documents to update | Notes |
|-------------|-------------------------------|--------------------------------|-------|
| New agent added | `approach.md` (roster section), `technical_architecture.md`, `execution_plan.md` (work plan) | `/agents/roster.md`, `/quality/validation_gate_config.md` if new input types identified | All documents updated before agent goes live |
| Agent modified (role or permissions) | `approach.md` (roster section), `technical_architecture.md` | `/agents/roster.md` | |
| Agent decommissioned | `approach.md`, `technical_architecture.md`, `execution_plan.md` | `/agents/roster.md` | |
| New data source added | `technical_architecture.md` (data sources section), `execution_plan.md` | `/quality/source_registry.md`, `/security/credentials_registry.md` if credential required | |
| Data source removed or changed | `technical_architecture.md`, `execution_plan.md` | `/quality/source_registry.md` | |
| Autonomy level changed | `project_instructions.md` | Agent prompt files as applicable | User must explicitly authorize |
| Spend ceiling or threshold changed | `project_instructions.md` | | User must explicitly authorize |
| New credential added | `project_instructions.md` (reference only — no values) | `/security/credentials_registry.md`, `/security/gitignore_manifest.md` if new file type | `.env` updated directly — never committed |
| Credential changed or removed | | `/security/credentials_registry.md` | |
| Validation gate config changed | `project_instructions.md` (if sensitivity thresholds updated) | `/quality/validation_gate_config.md` | User must authorize sensitivity changes |
| User profile updated | `project_instructions.md` | | |
| Model tier mapping updated | `project_instructions.md` | | User must explicitly authorize |
| Context window limit updated | `project_instructions.md` | | User must explicitly authorize |
| Scale tier updated | `technical_architecture.md`, `project_instructions.md` | | User must explicitly authorize |
| System architecture changed (significant) | All five foundation documents as applicable | All affected operational files | Triggers architectural review |
| Phase advancement | `execution_plan.md`, `project_instructions.md` | | User must explicitly authorize |
| Document impact map updated | | This file | Meta-update: logged in audit trail |
| `manual.md` update required | | `manual.md` | Triggered when setup steps or commands change |

---

## Project-specific change categories

*Added by the system when the standard taxonomy does not cover a change event encountered in operation.*

| Change event | Foundation documents to update | Operational documents to update | Notes |
|-------------|-------------------------------|--------------------------------|-------|

*No project-specific categories yet.*
