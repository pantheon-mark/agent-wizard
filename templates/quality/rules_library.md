# Rules Library

*Growing structured set of domain quality rules derived from human feedback, QA investigation outcomes, and advisor responses. Each rule is traceable to the human decision that created it. Rules are never auto-deleted — obsolete rules are marked inactive.*

*Updated by the system as rules are created from feedback and QA findings. Never edited manually.*

---

## Rules

*No rules yet. Rules are added from: user feedback corrections, QA investigation outcomes validated by the user, advisor response decisions, and human review queue resolutions.*

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
