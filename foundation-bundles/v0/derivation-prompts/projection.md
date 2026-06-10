# Projection Derivation Prompt

## Class + target fields

A projection is a **deterministic role-filtered view** of one or more prior payload fields — the same facts, reshaped into a specific surface's columns. It is **pure code over already-confirmed inputs**, not a judgment call and not authored prose. The operator never edits a projection directly: it is a generated, non-authoritative cache. If a projected table looks wrong, the fix goes to the canonical record it was projected from (or the answer behind it), never to the projection itself.

Example target fields this class produces: the tabular external-dependency views — the validation-gate input inventory, the QA source registry, and the credentials registry. Each is the subset of the system's external dependencies that plays a particular role (an input that crosses the boundary; a source whose health is monitored; a dependency that needs a login or key), reshaped into that surface's columns.

## Inputs

A projection reads **prior payload fields only** — the canonical record(s) it filters and reshapes. List every canonical field key it reads in `_derivation_inputs`. A projection never reads raw interview answers and never carries `_source_question_ids` (the canonical record already captured and confirmed the answers).

For the external-dependency views the inputs are the canonical dependency record: the identity field (each dependency's id, name, type, and the roles it plays) and the annotation field (each dependency's purpose, what stops without it, and the per-role detail). Each view filters to the dependencies that play its role and maps the canonical fields into its own columns.

## How it is produced

Deterministically, by rule — not by interpretation:

1. **Filter** the canonical records to those that play this surface's role.
2. **Reshape** each surviving record into this surface's columns, copying values straight from the canonical fields. Do not rewrite, summarize, or embellish.
3. **Hold setup-time honesty.** Cells that describe *observed runtime health* are not known at setup. Never synthesize them. Set status to `Pending` and emit an explicit placeholder (for example `(set at runtime)`) for any expected-behavior, last-verified, or health-flag cell.
4. If no record plays this role, the view is an **empty table body** (the surface still emits, with no rows).

Because step 2 copies and step 3 uses fixed literals, the same canonical record always yields the same view. That is what makes a projection safe to recompute silently: when the canonical record changes in a way that does not touch this role's subset, the recomputed view is identical and nothing needs to re-surface to the operator.

## Output contract

Produce the table body exactly as the filter-and-reshape rule yields it. Do not interpret, infer, or normalize beyond the column mapping.

Audit envelope requirements:
- `_source`: `auto` (mechanically computed from trusted prior fields — not the operator's words, not authored)
- `_derivation_class`: `projection`
- `_derivation_inputs`: non-empty list of the prior **payload field keys** it reshaped (the validator rejects anything that is not a payload key)
- `_source_question_ids`: **must not be present** — a projection derives from prior fields, never raw answers
- `_decision_field`: follows the projected content. For the external-dependency views it is `false`: the decision surface is the canonical identity record (where adding, dropping, renaming, or re-roling a dependency is the integration-boundary decision), and these views are non-authoritative caches of it.
- `_decision_kind`: `none` when `_decision_field` is `false`

**Never fabricate.** A projection adds nothing that is not already in its inputs. If a canonical record is missing a value a column needs, leave the mapped cell as the canonical record left it (or its honest placeholder) — do not invent it.

## Confirmation

A projection is not separately confirmed by the operator: it is recorded as part of the generation run, like the mechanically-filled fields. The review that matters happened upstream — when the operator confirmed the canonical record the projection reads. If the canonical record changes after a view was projected, the view is recomputed; an unchanged role-subset recomputes identically and does not re-surface, while a changed one is shown as part of the canonical record's change review.
