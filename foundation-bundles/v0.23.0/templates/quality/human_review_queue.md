# Human Review Queue

*Items flagged for user judgment that do not match any existing rule in the rules library. The system surfaces these when human domain judgment is required. Resolved items are moved to `/archive/review_queue_archive.md` immediately on resolution.*

*Updated by the system. Never edited manually.*

---

## Open Items

| Item ID | Raised | Severity | Type | Agent | Item description | Status | User judgment | Rule created |
|---------|--------|----------|------|-------|-----------------|--------|--------------|-------------|

*No open items.*

---

## Item types

| Type | Description |
|------|------------|
| QA finding | Agent output flagged by the QA agent — no matching rule in the rules library |
| Confidence flag | Agent output flagged with low confidence — domain check needed |
| Semantic validation | Input reached the validation gate with no applicable rule to apply |
| Tier 2 decision | Decision at current maturity level requiring human judgment |
| Drift decision | Drift analysis finding requiring human direction |
| Vision conflict | Agent output conflicts with the vision document or rules library |
| Consultant brief | Decision deferred — expert input being gathered before proceeding |
