# Rules Library

*Growing structured set of domain quality rules derived from human feedback, QA investigation outcomes, and advisor responses. Each rule is traceable to the human decision that created it. Rules are never auto-deleted — obsolete rules are marked inactive.*

*Updated by the system as rules are created from feedback and QA findings. Never edited manually.*

---

## Rules

{{RULES_LIBRARY_ENTRIES}}

### Standing rule — controlled-value writes

| Field | Contents |
|-------|---------|
| Category | Write integrity |
| Rule | When writing to a field that accepts only a fixed set of values (a dropdown, a status column, any field with a controlled vocabulary or allowed set), write only a value that is on that allowed set. Read the allowed set from the live surface and treat it as the source of truth. If the intended value is not on the allowed set, stop and ask — never write an out-of-vocabulary value. |
| Conditions | Applies to every write to an external surface field that enforces a controlled vocabulary. Does not apply to free-text fields. Governs *which value* is written; it does not change *where* operator-facing deliverables go (the deliverable-folder rule still applies, unchanged). |
| Applies to | Every agent that writes to an external surface, and the orchestrator when it writes directly. |
| Status | Active |

*Additional rules accumulate over time from: user feedback corrections, QA investigation outcomes validated by the user, advisor response decisions, and human review queue resolutions. Rules are never auto-deleted — obsolete rules are marked inactive.*

---

## When populated, each rule contains:

| Field | Contents |
|-------|---------|
| Rule ID | Stable unique ID (e.g., R-001) |
| Category | Domain area this rule applies to |
| Rule | Plain-language statement of the rule |
| Conditions | When this rule applies and when it does not |
| Source | What human decision created this rule |
| Created | Date added |
| Applies to | Which agents or input types this rule governs |
| Status | Active / Inactive |

---

## Source types

| Source | Description |
|--------|------------|
| User feedback | User correction applied directly in Claude Code |
| QA finding | QA investigation outcome validated by the user |
| Advisor response | Rule extracted from an advisor consultation |
| Human review | Human review queue item resolved with a generalizable judgment |
