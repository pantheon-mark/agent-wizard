# Synthesis Derivation Prompt

## Class + target fields

Synthesis combines two or more already-derived fields — plus relevant general knowledge — into a new, coherent piece of prose or structured output. The result is something the operator did not say word-for-word but that follows logically from what they said. The operator's voice and style are carried through so the synthesized text feels like them, not like a form letter.

Example target fields this class produces: `APPROACH_SOLUTION_BRIEF`, `MVP_CORE_FUNCTION`, `SCALE_TIER_RATIONALE`, voice-and-style fields, and each agent's role description inside `AGENT_ROSTER_ROWS`.

## Inputs

Always cite the specific prior field keys you are combining. Do not synthesize from raw interview answers directly when a derived field already captures that content — use the derived field.

Common input combinations:
- `PROJECT_AUTOMATION_BUDGET` — `_derivation_inputs`: `AUTOMATION_CREDIT_POOL`, `PROJECT_SHARE_POSTURE`. Compute = pool × share fraction, where `sole` → ~0.9 and `one-of-several` → ~0.4 (conservative, leaves room for the operator's other systems). Round to a sensible dollar figure (e.g. pool `$20` + `sole` → `$18`). This is the enforceable monthly automation budget.
- `INTENSIVE_OPERATION_THRESHOLD` — `_derivation_inputs`: `PROJECT_AUTOMATION_BUDGET`. Compute = ~10% of the budget (e.g. budget `$18` → `$1.80`); one estimated-expensive single operation above this pauses for operator approval. Both are wizard-computed (the operator never sets a dollar) and confirmed plainly at the barrier; `_decision_field: false`.
- `APPROACH_SOLUTION_BRIEF` — draws from `VISION_PURPOSE`, `VISION_GOALS`, `VISION_SCOPE_BOUNDARY`, and answers to AP-1, AP-2, AP-3.
- `MVP_CORE_FUNCTION` — draws from `CORE_PURPOSE`, `VISION_GOALS`, and answers to ARCH-1, SCALE-1.
- `SCALE_TIER_RATIONALE` — draws from SCALE-1, SCALE-2, SCALE-3, SCALE-4 and the derived `SCALE_TIER` value.
- Voice-and-style fields — draw from the operator's answers to UP-4, ADV-1, and the prose register visible in V-1 through V-5.
- Per-agent role description — draws from AP-2, AP-3, ARCH-2, ARCH-3, and the corresponding rows in `AGENT_ROSTER_ROWS`.

List every input field key or question ID used in `_derivation_inputs` so the chain of evidence is auditable.

## Output contract

Produce a value that:
1. Accurately represents the combined inputs — no content is added that contradicts or exceeds what the inputs support.
2. Is written in the operator's voice — match the level of formality, the sentence length, and the word choices visible in their vision answers.
3. Is self-contained — a reader who has not seen the interview answers can understand what the field says without needing to cross-reference other fields.

Audit envelope requirements:
- `_source`: `claude-derived-operator-confirmed`
- `_derivation_class`: `synthesis`
- `_decision_field`: `false` (unless the field is also a decision — if so, follow the policy prompt rules instead)
- `_decision_kind`: `none`
- `_derivation_inputs`: non-empty list of the field keys and question IDs combined
- `_confirmation_state`: set after the operator confirms

**Never fabricate.** If the inputs do not provide enough information to synthesize a complete value, do not invent the missing parts. Instead, write the value up to the point where evidence runs out, mark the gap with "(insufficient input — needs operator input on: [what is missing])", and set `_revisit_trigger` accordingly.

## Confirmation hooks

Show the operator:
1. The synthesized value — formatted as it will appear in the foundation document.
2. The fields and answers it was built from — list them briefly so the operator can see the reasoning chain.
3. The impact if it is wrong — for example: "This is the summary that every agent reads at the start of a session to understand what the system is for. If it is off, agents will make misaligned decisions."

Targeted confirmation: do not ask generically "does this look right?" — ask specifically about the parts that required the most inference. For example: "I combined your goal of [X] with your scope boundary of [Y] to write this — does that connection accurately reflect what you have in mind?"

## Discipline guards

- **Operator lists are examples, not exhaustive.** When synthesizing from a list the operator gave — agents they named, goals they mentioned, tools they use — treat that list as illustrative. Before finalizing, ask: is there something the operator's description implies that they did not explicitly name? If yes, surface it as a question rather than silently adding it to the synthesis.

- **No fabrication.** Every claim in the synthesized value must trace to at least one input field or question answer. If a phrase cannot be traced, remove it or flag it as an assumption. Do not add plausible-sounding context that the operator did not supply.

- **Epistemic status.** When a synthesized sentence connects two inputs that the operator did not explicitly connect themselves, note that connection at confirmation time — "I inferred that [X] implies [Y] — is that right?" Do not present an inference as a fact.
