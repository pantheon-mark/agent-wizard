# Auto Derivation Prompt

## Class + target fields

Auto fields are filled mechanically at generation time. Their values come from system state or fixed constants — not from the operator's answers and not from any judgment call. Once recorded, they are not re-evaluated or re-confirmed.

Example target fields this class produces: `WIZARD_VERSION`, `LAST_UPDATED_DATE`, `LAST_UPDATED_TRIGGER`, `FOUNDATION_ONLY_MODE`, `SYSTEM_SHAPE`.

## Inputs

Auto fields do not read interview answers. They read:
- The wizard's own version identifier (constant at generation time).
- The current date and time (from the system clock at the moment the record is generated).
- The trigger event that caused the generation run (passed in by the calling process — for example: "initial-derivation", "operator-edit", "periodic-refresh").
- Fixed configuration values determined by the system shape selected earlier in the interview (for example, `FOUNDATION_ONLY_MODE` is set based on whether the operator chose a foundation-only path or a full-build path).

No operator input is read. No prior derived fields are read.

## Output contract

Produce the value exactly as the system state provides it. Do not interpret, adjust, or normalize.

Audit envelope requirements:
- `_source`: `auto`
- `_derivation_class`: `auto`
- `_decision_field`: `false`
- `_decision_kind`: `none`

Confirmation is not required for auto fields. They are recorded silently as part of the generation run and do not appear in the operator confirmation flow.

If the required system state value is unavailable at generation time (for example, the version identifier cannot be read), record the field as an explicitly labeled placeholder and log the failure — do not silently omit the field or substitute a guess.

## Confirmation hooks

No confirmation is shown to the operator for auto fields. These values are bookkeeping metadata, not decisions. If an auto field ever needs to be visible to the operator (for example, in a document header), it is displayed as a read-only fact, not as something to confirm.

## Discipline guards

- **Operator lists are examples, not exhaustive.** Not applicable to auto fields — they do not originate from operator input.

- **No fabrication.** The value must come from actual system state at generation time. Do not substitute a default, a placeholder guess, or a remembered value from a prior run. If the value cannot be determined, flag it explicitly rather than inventing it.

- **Epistemic status.** Auto fields carry no uncertainty — they are either correct (drawn from system state) or flagged as unavailable. There is no middle ground. Never record an auto field with a hedged or approximate value.
