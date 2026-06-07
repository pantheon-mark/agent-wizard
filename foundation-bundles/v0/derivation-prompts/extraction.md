# Extraction Derivation Prompt

## Class + target fields

Extraction pulls the operator's own words directly into a field with as little transformation as possible. The goal is faithful capture, not rewriting or polishing. The operator's phrasing, emphasis, and voice are preserved intact.

Example target fields this class produces: `PROJECT_NAME`, `CORE_PURPOSE`, `VISION_PURPOSE`, `VISION_GOALS`, `VISION_SCOPE_BOUNDARY`, `VISION_CONSTRAINTS`, `INTEGRATIONS`, `AUTOMATION_CREDIT_POOL`.

**Lookup-extraction special case (`AUTOMATION_CREDIT_POOL`).** A few extraction fields are not the operator's words but a fixed value the stated answer maps to. `AUTOMATION_CREDIT_POOL` is the included monthly Agent-SDK automation-credit dollar pool, looked up from the operator's plan (FIN-1) via this table (verified 2026-06-07, effective 2026-06-15, `support.claude.com/articles/15036540` — VOLATILE; re-verify before relying):

| Plan (FIN-1 / `PLAN_TYPE`) | `AUTOMATION_CREDIT_POOL` |
|---|---|
| pro (or unknown → treat as pro) | `$20` |
| max + `MAX_TIER` $100 | `$100` |
| max + `MAX_TIER` $200 | `$200` |
| team + `TEAM_TIER` standard | `$20` |
| team + `TEAM_TIER` premium | `$100` |

For a lookup-extraction field, set `_source: claude-derived-operator-confirmed` (the value is derived from the plan, not quoted), `_source_question_ids: ["FIN-1"]`, and confirm it at the barrier (`_confirmation_state` + `_confirmed_at`). All other extraction fields keep `_source: operator-content`.

## Inputs

Read the interview answer for the question IDs that feed this field. For vision-group fields, the primary sources are: V-1, V-2, V-3, V-4, V-5, V-6, V-7, V-8, P1-1, P1-2. For integrations, the primary sources are: CRED-1, CRED-2, CRED-3, ARCH-2.

When a field maps to a single question, pull from that question directly. When a field spans multiple questions (such as goals that appeared across V-2 and V-3), combine the answers in the order they were given — do not reorder or prioritize.

**Name-consistency rule:** every name the operator gives — for the project, for agents, for third-party tools — must be copied verbatim into the extracted value. Never normalize, abbreviate, or paraphrase a name.

## Output contract

Produce the field value as a direct quote or lightly formatted version of the operator's exact words. Light formatting means: turning a run-on answer into a short bulleted list if it naturally contains multiple items, or splitting a compound answer into sentences. It does NOT mean rephrasing, summarizing, or improving the language.

Audit envelope requirements for each extracted field:
- `_source`: `operator-content`
- `_derivation_class`: `extraction`
- `_decision_field`: `false`
- `_decision_kind`: `none`
- `_source_question_ids`: the list of question IDs the value was drawn from

**Never guess or fabricate.** If the operator's answer is ambiguous or incomplete, do not fill in the gap — mark `_source` as `ambiguous` and populate `_source_candidates` with the plausible interpretations. If the input is insufficient to fill the field at all, leave the field value as a clearly labeled placeholder and set `_revisit_trigger` to the condition under which it can be resolved.

## Confirmation hooks

Show the operator:
1. The extracted value — formatted exactly as it will appear in the foundation document.
2. The question(s) it was drawn from — quoted briefly so the operator can verify the match.
3. The impact if it is wrong — for example: "This is the project name that will appear on every agent file and every document header. If it is misspelled or not quite right, everything will need to be updated."

Keep the confirmation light for extraction fields — these are the operator's own words coming back to them, so the error risk is low. A single "Does this look right?" pass is sufficient.

## Discipline guards

- **Operator lists are examples, not exhaustive.** When the operator lists items — tools, goals, constraints, integrations — treat that list as a starting point, not a complete inventory. Before finalizing the field, ask yourself: given what the operator described, is there something obvious that is missing from what they said? If yes, surface it as a question rather than adding it silently.

- **No fabrication.** Every word in the extracted value must trace to something the operator actually said. If a word or phrase is not in the operator's answers, it does not belong in the extracted value. When in doubt, leave a gap and flag it rather than filling it with an assumption.

- **Epistemic status.** If a portion of the extracted value is your interpretation of an ambiguous answer rather than a direct pull, mark it explicitly at that point — for example: "(inferred from V-3 — confirm this is what you meant)". Do not present an interpretation as if it were a direct quote.
