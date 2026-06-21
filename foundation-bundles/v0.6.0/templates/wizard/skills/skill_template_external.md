---
description: "{{SKILL_DESCRIPTION_ROUTING_SIGNAL}}"
---

# {{SKILL_NAME}}

*This skill is wizard-generated. It makes one or more external MCP or API calls. A degradation path is baked in: if the external call fails, the skill completes its logic locally and produces a plain-language action prompt so the user can act manually. No external call failure should produce a silent result or a raw error message.*

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

Before any external call:
1. Verify all required inputs are present and of the correct type. If any required input is missing or malformed: return `ERR_MISSING_INPUT` with the field name. Do not proceed.
2. Declare your blast radius: list the external endpoint you will call and the local file you will write to if the call succeeds or fails.

### Step 2 — External call

{{EXTERNAL_CALL_DESCRIPTION}}

MCP server: `{{MCP_SERVER_NAME}}`
Method / endpoint: `{{MCP_METHOD_OR_ENDPOINT}}`
Expected response schema: `{{EXPECTED_RESPONSE_SCHEMA}}`

### Step 3 — Process result

{{RESULT_PROCESSING_DESCRIPTION}}

### Step 4 — Write output (atomic write pattern)

Write output to a temp file first, then rename to the final path. Never write directly to the final path.

Success output path: `{{SUCCESS_OUTPUT_PATH}}`
Fallback output path: `{{FALLBACK_OUTPUT_PATH}}`

---

## Output format

*Every field must be exactly as specified. Downstream agents consume this output structurally — prose summaries are not acceptable.*

### On success

```{{OUTPUT_FORMAT}}
{{OUTPUT_FIELD_1}}: {{TYPE_AND_DESCRIPTION}}
{{OUTPUT_FIELD_2}}: {{TYPE_AND_DESCRIPTION}}
{{OUTPUT_FIELD_3}}: {{TYPE_AND_DESCRIPTION}}
status: "SUCCESS"
source: "{{MCP_SERVER_NAME}}"
timestamp: "{{ISO_8601_TIMESTAMP}}"
```

### On MCP failure (degradation path — local output)

When the external call fails or the MCP server is unreachable, the skill completes its logic using available local context and writes to the fallback output path.

```{{OUTPUT_FORMAT}}
{{OUTPUT_FIELD_1}}: {{TYPE_AND_DESCRIPTION — populated from local logic}}
status: "DEGRADED"
source: "local"
degradation_reason: "{{PLAIN_LANGUAGE_DESCRIPTION_OF_WHAT_FAILED}}"
manual_action_prompt: "{{PLAIN_LANGUAGE_INSTRUCTIONS_FOR_USER}}"
timestamp: "{{ISO_8601_TIMESTAMP}}"
```

The `manual_action_prompt` field must be written in plain language a non-technical user can act on. It must state: what was found, why it could not be delivered automatically, and what the user should do with it.

---

## Edge cases and error codes

| Error code | Condition | Behavior |
|------------|-----------|----------|
| `ERR_MISSING_INPUT` | Required input field absent or null | Return error immediately. Do not proceed. Do not call external service. |
| `ERR_MALFORMED_INPUT` | Input present but wrong type or schema | Return error with field name and expected type. Do not proceed. |
| `ERR_MCP_UNAVAILABLE` | MCP server unreachable or timed out | Execute degradation path. Write local output. Write Informational digest entry. If this is the 3rd failure from this source within 24 hours, send a High severity real-time alert. |
| `ERR_UNEXPECTED_RESPONSE` | MCP server returned unexpected schema | Execute degradation path. Write local output with `degradation_reason` describing the schema mismatch. |
| `ERR_OUTPUT_WRITE_FAILED` | Cannot write to output path | Log to `/logs/error_log.md`. Send High severity alert. Return error. |

---

## MCP degradation — alert escalation

- **First failure in a session:** Write an Informational digest entry. Include local output and manual action prompt.
- **3rd failure from the same MCP source within 24 hours:** Send a High severity real-time alert. Include source name, failure count, and plain-language action prompt. Flag the integration as degraded in `/quality/source_registry.md`.

The failure window (default: 3 failures / 24 hours) is a Claude-owned default — not user-configurable.

---

## Agent-readiness checklist

Before this skill is used in a production agent pipeline, verify all four criteria:

- [ ] **Description as routing signal** — the `description` field contains the exact phrases an orchestrating agent will generate when it needs this skill type (not a human-readable label)
- [ ] **Completely specified output format** — all output fields are named exactly, with types specified; no "a summary" or "a structured response"
- [ ] **Deterministic edge case handling** — every error code has a defined behavior; no "note it if missing" or "handle gracefully"
- [ ] **Composable output** — another skill can consume this skill's output without parsing prose; structured fields only

Any "no" on any criterion is a pipeline failure waiting to surface. Do not ship until all four are met.
