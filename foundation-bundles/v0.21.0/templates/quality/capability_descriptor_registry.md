# Capability Descriptor Registry

*Human/QA view of every external-dependency capability that carries a typed capability descriptor — the action it takes, the risk-enforcement class it is governed under, the test target it may run against, its blast-radius cap, its recovery profile, and whether it is currently accepted for live use.*

*Pre-populated from the confirmed external-dependency identity record at wizard setup. This is the QA/read view only — the machine-readable set that runtime enforcement actually consumes is a separate emitted artifact (`security/capability_descriptors.json`). A dependency that declares no capability descriptor (a bare data source, not an action) does not appear here. The Risk class column always shows the fail-safe-resolved value — a capability with a missing or unrecognized risk class shows as `irreversible_external`, never `read_only_local`. The Accepted column is `No` until a later runtime step explicitly accepts a capability for live use; nothing is accepted by default.*

---

| Capability | Action class | Risk class | Test target | Blast-radius cap | Recovery profile | Accepted |
|-----------|-------------|-----------|-------------|------------------|------------------|---------|
{{CAPABILITY_DESCRIPTOR_REGISTRY_ROWS}}

---

## Action classes

| Class | Meaning |
|------|---------|
| classify | Categorizes or labels data without changing it |
| transform | Reshapes or converts data |
| route | Directs data or work to a destination |
| notify | Sends an informational message |
| mutate | Changes existing data in place |
| delete | Removes data |
| send_execute | Sends or executes an action with an external, outward effect |
| synchronize | Keeps two systems' state aligned |
| retain_archive | Stores or archives data for later reference |
| recover | Restores from a prior state |
| audit | Records or reviews an action for accountability |
| read_only | Reads data only — no side effect |

## Risk classes

| Class | Meaning |
|------|---------|
| read_only_local | Reads local data only — no external effect, nothing to reverse |
| reversible_external | Has an external effect, but it can be undone |
| irreversible_external | Has an external effect that cannot be undone |
| sensitive_data | Touches data that requires extra care (personal, financial, confidential) |
| standing_automation | Runs on a recurring or unattended basis, not a single confirmed action |

A capability with no declared risk class, or one that does not match this list, is always shown as `irreversible_external` — the most protected class, never `read_only_local`. An unclassified action is never assumed safe.

## Accepted values

| Value | Meaning |
|------|---------|
| No | Not yet accepted for live use — enforcement refuses to run this capability live |
| Yes | Explicitly accepted for live use |

Every capability starts as `No`. Accepting a capability for live use is a deliberate runtime step, not a wizard-setup default.
