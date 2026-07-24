---
description: "{{SKILL_DESCRIPTION_ROUTING_SIGNAL}}"
---

# {{SKILL_NAME}}

*This skill is wizard-generated. It reads and writes local files only — no external calls, no MCP servers. No degradation logic is required. Internal skills have no external dependency and no degradation path.*

*The description field above is a routing signal — not a human-readable label. It must contain the exact phrases an orchestrating agent will generate when it needs this skill. Maximum 1,024 characters. Must be a single YAML line.*

---

## Purpose

{{SKILL_PURPOSE_ONE_PARAGRAPH}}

---

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| {{INPUT_FIELD_1}} | {{TYPE}} | {{YES/NO}} | {{DESCRIPTION}} |
| {{INPUT_FIELD_2}} | {{TYPE}} | {{YES/NO}} | {{DESCRIPTION}} |

*Add or remove rows as needed. Every input field must have a type and a clear description.*

---

## Execution

### Step 1 — Pre-flight

Before any file operation:
1. Verify all required inputs are present and of the correct type. If any required input is missing or malformed: return `ERR_MISSING_INPUT` with the field name. Do not proceed.
2. Verify all input files exist at their specified paths. If a required input file is missing: return `ERR_INPUT_FILE_MISSING` with the file path. Do not proceed.
3. Declare your blast radius: list every file you will read from and write to in this operation.

### Step 2 — Read inputs

{{INPUT_READ_DESCRIPTION}}

Source files:
- `{{INPUT_FILE_1}}` — {{PURPOSE}}
- `{{INPUT_FILE_2}}` — {{PURPOSE}}

### Step 3 — Process

{{PROCESSING_DESCRIPTION}}

### Step 4 — Write output (atomic write pattern)

Write output to a temp file first, then rename to the final path. Never write directly to the final path.

Output path: `{{OUTPUT_PATH}}`

---

## Output format

*Every field must be exactly as specified. Downstream agents consume this output structurally — prose summaries are not acceptable.*

```{{OUTPUT_FORMAT}}
{{OUTPUT_FIELD_1}}: {{TYPE_AND_DESCRIPTION}}
{{OUTPUT_FIELD_2}}: {{TYPE_AND_DESCRIPTION}}
{{OUTPUT_FIELD_3}}: {{TYPE_AND_DESCRIPTION}}
status: "COMPLETE | FAILED"
timestamp: "{{ISO_8601_TIMESTAMP}}"
```

---

## Edge cases and error codes

| Error code | Condition | Behavior |
|------------|-----------|----------|
| `ERR_MISSING_INPUT` | Required input field absent or null | Return error immediately. Include field name. Do not proceed. |
| `ERR_MALFORMED_INPUT` | Input present but wrong type or schema | Return error with field name and expected type. Do not proceed. |
| `ERR_INPUT_FILE_MISSING` | Required source file not found at specified path | Return error with file path. Do not proceed. |
| `ERR_INPUT_FILE_UNREADABLE` | Source file exists but cannot be read | Log to `/logs/error_log.md`. Return error with file path. |
| `ERR_OUTPUT_WRITE_FAILED` | Cannot write to output path (permissions, disk full, etc.) | Log to `/logs/error_log.md`. Send High severity alert. Return error. |
| `ERR_PROCESSING_FAILED` | Logic error during processing — unexpected input structure or content | Log to `/logs/error_log.md`. Return error with plain-language description. |

---

## Agent-readiness checklist

Before this skill is used in a production agent pipeline, verify all four criteria:

- [ ] **Description as routing signal** — the `description` field contains the exact phrases an orchestrating agent will generate when it needs this skill type (not a human-readable label)
- [ ] **Completely specified output format** — all output fields are named exactly, with types specified; no "a summary" or "a structured response"
- [ ] **Deterministic edge case handling** — every error code has a defined behavior; no "note it if missing" or "handle gracefully"
- [ ] **Composable output** — another skill can consume this skill's output without parsing prose; structured fields only

Any "no" on any criterion is a pipeline failure waiting to surface. Do not ship until all four are met.
