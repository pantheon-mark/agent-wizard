# Advisor Knowledge Base

*Professional guidance with full provenance — rules extracted from advisor consultations, attributed to the named advisor with the date, originating context, conditions, and a review flag indicating when the entry should be reconfirmed.*

*Pre-populated during wizard setup (ADV-1) with a header entry for each confirmed advisor. Knowledge entries are added after each consultation — either via the quick path (user forwards advisor reply, Claude extracts rules) or the enhanced path (structured interview guide with follow-up extraction).*

*Applied autonomously by agents at Level 3+. Review-flagged entries surface in the operations digest when their review date arrives.*

---

{{ADVISOR_ENTRIES}}

---

## Entry format

Each advisor section follows this structure:

---

**[Advisor name or role] — [Domain]**

*Added: [date] | Review cycle: [e.g., every 6 months]*

| Entry ID | Date | Rule | Conditions | Source decision | Review flag |
|----------|------|------|-----------|----------------|------------|

---

## Path reference

| Path | When to use |
|------|------------|
| Quick path | Advisor gave a direct response — user forwards it to Claude; Claude extracts rules and writes entries; pending decision closed |
| Enhanced path | Structured consultation planned — wizard generates an interview guide with tailored questions; entries written after guide is used |

## Review flags

Entries can be flagged for periodic reconfirmation. When an entry's review date arrives, it surfaces in the operations digest:

*"[Advisor name]'s guidance on [topic] was added [N months] ago. If you have consulted with them recently, forward the conversation and I'll update it. If not, confirm whether it still applies."*
