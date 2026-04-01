# Validation Gate Configuration

*Input validation settings for this system — the input type inventory, structural rules per input type, and domain sensitivity settings. Pre-populated during wizard setup (GATE-1 and GATE-2).*

*Updated when new input types are identified or sensitivity settings are adjusted. Domain sensitivity changes require user authorization.*

---

## Input type inventory

*Confirmed during wizard setup (GATE-1). The system validates all inputs in this inventory before passing them to agents.*

| Input type | Source | What it is | What stops without it | Structural rules | Status |
|-----------|--------|-----------|----------------------|-----------------|--------|
{{INPUT_TYPE_INVENTORY}}

---

## Domain sensitivity settings

*Configured during wizard setup (GATE-2). Governs how aggressively the system pushes back on semantically suspect inputs in each domain.*

| Domain | Sensitivity level | Rationale | Last reviewed |
|--------|-----------------|-----------|--------------|
{{DOMAIN_SENSITIVITY_SETTINGS}}

---

## Sensitivity levels

| Level | Behavior |
|-------|---------|
| Low | Soft pushback auto-approved at Level 3+ — logged without interruption. At Levels 1–2, soft pushback surfaces for user confirmation. |
| Medium | Soft pushback always surfaces for user confirmation, regardless of autonomy level |
| High | Soft pushback surfaces for user confirmation; a pattern of overrides in this domain is flagged for sensitivity review |

## Override behavior

When the user confirms a soft pushback ("I meant that"): the input is accepted and the override is logged with domain and user rationale. The sensitivity setting is not automatically changed. A pattern of overrides in the same domain is the signal for the user to consider lowering sensitivity if appropriate.
