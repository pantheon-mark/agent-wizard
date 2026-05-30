# Policy Derivation Prompt

## Class + target fields

Policy derives a behavior rule or permission boundary for the system. Every policy value has two sides: what the system is permitted to do, and what the system must NOT do. The negative side is not optional — a policy that only states permissions without stating prohibitions is incomplete.

Example target fields this class produces: `HITL_MAP_ROWS` (a table of Action / System behavior / Rationale rows), autonomous-action lists, asks-first action lists, and any constraint elevated to a top-level permission rule (such as scope boundaries from `VISION_CONSTRAINTS`).

## Inputs

Policy fields draw primarily from the operator's autonomy and oversight answers, financial guardrails, and stated constraints.

For `HITL_MAP_ROWS`: draw from UP-1, UP-2, UP-3, UP-5, FIN-1, FIN-2, NOTIF-1, NOTIF-2, NOTIF-3, ARCH-4, ERR-1, ERR-2, CONC-1, and the derived `AUTONOMY_LEVEL`.

For autonomous-action lists and asks-first lists: draw from the same sources, plus START-1, START-2, QA-2.

For vision-originated constraints elevated to policy: draw from `VISION_CONSTRAINTS` (derived) and V-6, V-7.

List every input used in `_derivation_inputs` — policy fields have the strictest traceability requirement because a wrong rule causes real-world harm.

## Output contract

For `HITL_MAP_ROWS`, produce a structured table with three columns per row:
- **Action** — the specific thing the system might do (plain language, not code)
- **System behavior** — what happens: does the system act autonomously, ask the operator first, or never do this action at all
- **Rationale** — one sentence connecting the rule back to what the operator said

Every policy output must include:
- At least one explicit negative permission ("the system must NOT [action] under any circumstances") for every domain where the operator expressed a limit or risk concern.
- A row for "no matching rule" — what the system does when an action falls outside all defined rows. This is the fail-safe default.

Audit envelope requirements:
- `_source`: `claude-derived-operator-confirmed`
- `_derivation_class`: `policy`
- `_decision_field`: `true`
- `_decision_kind`: `policy_rule`
- `_derivation_inputs`: non-empty
- `_confirmation_state`: set after the operator confirms (forced — see below)

**Never fabricate.** Do not add a permission rule that the operator did not express, imply, or authorize. If an action type is not addressed in the inputs, do not assign it a behavior — add it as an open row flagged for operator input.

**If inputs are insufficient:** produce the rows that are supported, leave unsupported action types as explicitly flagged gaps, and set `_revisit_trigger` for each gap.

## Confirmation hooks

Show the operator:
1. The full policy table — every row, formatted clearly.
2. For each row: the answer or constraint that it came from, cited briefly.
3. The explicit negative permissions — call these out separately so the operator sees what the system will refuse to do.
4. The fail-safe default row — make sure the operator consciously approves what happens for uncovered actions.
5. The impact if it is wrong — stated plainly: "A permission rule that is too loose means agents may take actions you did not intend. A rule that is too strict means the system will stop and ask you about things it could handle on its own."

**Forced confirmation.** Policy fields always require explicit operator sign-off. Do not proceed past a policy derivation without a clear "yes, this is right" — not just a lack of objection. If the operator says "looks fine" without reading it, ask them to confirm the negative permissions specifically before accepting.

## Discipline guards

- **Operator lists are examples, not exhaustive.** The operator will name specific actions they want to control — but they will not name every action the system might take. Before finalizing the policy table, ask yourself: given this system's described behavior, what actions could it take that are not yet covered by a rule? Surface the gaps rather than leaving them to implicit defaults.

- **No fabrication.** Every rule must trace to something the operator said, implied, or explicitly authorized. A plausible-sounding rule that has no basis in the operator's answers does not belong in the policy table. When in doubt, leave the row as a flagged gap.

- **Epistemic status.** When a rule is inferred from general principles rather than a direct operator statement — for example, "no external data writes" inferred from a general caution about data safety — mark it explicitly: "(inferred from your answer to [question] — confirm this is the rule you intend)." Do not present an inferred rule as if the operator said it directly.
