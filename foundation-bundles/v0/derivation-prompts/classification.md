# Classification Derivation Prompt

## Class + target fields

Classification maps the operator's intent or preference onto one specific value drawn from a named, closed set of allowed values. The allowed set is defined in the field's manifest entry — it is not open-ended. Only values that appear in that manifest entry are valid outputs. This class always produces a decision field because the operator is choosing between defined options.

Example target fields this class produces: `SCALE_TIER` (allowed values: small / medium / large), `AUTONOMY_LEVEL`, and criticality tiers assigned to agents or operations.

## Inputs

Read the interview answers and any prior derived fields that describe the dimension being classified.

For `SCALE_TIER`: draw from SCALE-1, SCALE-2, SCALE-3, SCALE-4, and the derived `SCALE_TIER_RATIONALE` if it is already produced.

For `AUTONOMY_LEVEL`: draw from UP-1, UP-2, UP-3, FIN-1, FIN-2, and any prior answers that describe how much independent action the operator is comfortable with.

For criticality tiers: draw from the agent-roster answers (AP-2, AP-3, ARCH-2, ARCH-3) and any financial or irreversibility signals from FIN-1, FIN-2, ERR-1.

Always read the manifest entry for the field to confirm which values are in the allowed set before choosing one.

## Output contract

Produce exactly one value from the allowed set for this field. Do not produce a range, a blend, or a value not in the set.

Audit envelope requirements:
- `_source`: `claude-derived-operator-confirmed` when you proposed the value from the inputs and the operator confirmed it; `operator-preference` when the operator stated the choice directly
- `_derivation_class`: `classification`
- `_decision_field`: `true`
- `_decision_kind`: `closed_value`
- inputs (non-empty either way): for an `operator-preference` value cite `_source_question_ids` only — do NOT attach `_derivation_inputs` to an operator-preference value; for a `claude-derived-operator-confirmed` value cite `_derivation_inputs`
- `_confirmation_state`: set after the operator confirms
- `_rationale`: a brief plain-language sentence explaining why this value was chosen over the alternatives

**High-bar rule for classification.** Because the operator is making a decision that shapes system behavior, do not present the classification as a fait accompli. Present it as a proposal with a brief explanation, name the alternatives, and ask for explicit confirmation.

**Never guess.** If the inputs are genuinely ambiguous between two allowed values, do not pick one and move on. Present both options, explain what distinguishes them in plain terms, and ask the operator to choose.

## Confirmation hooks

Show the operator:
1. The proposed value — named clearly (not as a code, but as plain language if the code needs translation).
2. The alternatives that were not chosen — briefly named so the operator knows options exist.
3. The reasoning — one or two sentences explaining which inputs led to this classification.
4. The impact if it is wrong — for example: "Choosing 'small' sets the system up with simpler concurrency limits and lower cost guardrails. If your workload grows faster than expected, you would need to revisit this setting."

Always ask for explicit confirmation on classification fields. A classification that goes unconfirmed is not emittable.

## Discipline guards

- **Operator lists are examples, not exhaustive.** When the operator gives reasons for a preference, treat those reasons as the ones they thought to mention — not a complete list of their concerns. Before confirming a classification, ask yourself: given everything the operator has described, is there a concern about the alternatives they have not raised? If yes, name it briefly so they can factor it in.

- **No fabrication.** The rationale for a classification must come from what the operator actually said or what is directly observable from their answers. Do not invent a justification to make a preferred choice look more confident than it is.

- **Epistemic status.** If the inputs point more strongly toward one value but do not rule out another, say so explicitly at confirmation time: "Based on what you described, [X] fits best — but if [condition] is true for you, [Y] might be the better choice." Give the operator a real decision, not a rubber stamp.
