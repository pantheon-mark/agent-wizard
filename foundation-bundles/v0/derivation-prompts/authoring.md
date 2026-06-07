# Authoring Derivation Prompt

## Class + target fields

Authoring writes a field value as **narrative prose in the system's own voice**, addressed to the operator, grounded in what the operator said in the interview. The operator answers in the first person ("Help me keep track of…"); an authored field speaks back to them about their system ("Your system keeps track of…"). This is the conversion an authoring step performs — it is NOT a verbatim paste of the operator's words (that is extraction), and it is NOT a combination of prior derived fields (that is synthesis).

Authoring is the right class when a field is a **document the operator reads**, not a slot of captured data. The vision is the primary case: it is a human narrative that tells the story of what the system is for and references everything downstream.

Example target fields this class produces: `VISION_PURPOSE`, `VISION_GOALS`, `VISION_AUDIENCE_OUTPUTS`, `VISION_SCOPE_BOUNDARY`, `VISION_CONSTRAINTS`, `VISION_SUCCESS_CRITERIA`.

`PROJECT_NAME` and `CORE_PURPOSE` are NOT authored — they stay extraction (the name is copied verbatim; the core purpose is the operator's own one-line statement). Authoring applies only to the narrative vision sections.

## Inputs

Read the interview answers for the question IDs that feed this field (named in the field manifest). The vision-section answers are V-1 (purpose), V-2 (goals), V-3 (audience/outputs), V-4 (scope boundary), V-5 (constraints), V-6 (success criteria), plus the V-7/V-7b follow-ups and the P1-2 purpose. Also read the `## Working definition` the operator confirmed at step 01 (carried in the staging file) — it is part of what they told you, even though it is not in the event transcript.

Authoring is grounded in the operator's **raw answers** (question IDs), not in prior derived fields. Cite the question IDs you actually drew from in `_source_question_ids`. Do not cite `_derivation_inputs` — at v0 an authored field is answer-only.

## Output contract

Produce the field value as narrative prose the operator will read in their vision document. The value must:

1. **Be written in the system's voice.** Read `about.md` for the exemplar: plain, direct, calm, second person, grounded in the operator's own facts. Match the operator's level of technical comfort (UP-1) and how they make decisions (UP-2) — write to *this* operator, not a generic one.
2. **Stay strictly grounded in what the operator said.** Every claim must trace to an answer. Do not import specifics the operator did not give (no invented numbers, names, tools, regulations, or scenarios). Do not borrow detail from a reference example.
3. **Keep thin answers honestly thin.** If a category got little, write the little there is plainly. Do not pad a sparse answer into a paragraph, and do not pad a one- or two-item list into a longer one. A short true section beats a long padded one.
4. **Choose prose or a list by the content, not by habit.** Use a list only when there are genuinely several parallel items (several distinct goals, several distinct out-of-scope areas). Otherwise write prose. Do not strip a list where it aids readability; do not manufacture a list where one or two items belong in a sentence.

Audit envelope requirements for each authored field:
- `_source`: `claude-derived-operator-confirmed` (the value is authored from the operator's answers, then confirmed by them)
- `_derivation_class`: `authoring`
- `_decision_field`: `false`
- `_decision_kind`: `none`
- `_source_question_ids`: the list of question IDs the value was authored from
- `_confirmation_state` + `_confirmed_at`: set after the operator confirms (required — an authored value must be confirmed before it can be emitted)

Do NOT set `_derivation_inputs` on an authored field.

## No AI tells

Authored prose must read as written by a careful human, not assembled by a machine. Strip the constructs that pattern-match to "good writing" but are actually AI tells:

- **No em-dashes used for dramatic effect.** Use a period or a comma, or restructure the sentence.
- **No "it's not just X, it's Y" cadence.**
- **No short dramatic sentence fragments for effect** ("That stays with you.", "No small thing.").
- **No rule-of-three triads that pad rather than inform.**
- **No throat-clearing openers** ("Simply put,", "A few things are true here,", "Worth naming up front,").
- **No cutesy bold-lead labels on bullets** ("**No leaks.**"). Prefer plain descriptive leads.
- **No gratuitous semicolons.** Two sentences are fine.
- **Avoid** leverage, seamless, robust, delve, navigate, and similar filler vocabulary.

Polished-looking is not the bar. Plain and direct is the bar.

## Confirmation hooks

Show the operator:
1. The rendered document — the actual vision they will receive, written out (see the step's render-to-a-reviewable-file instruction). Not the raw field values.
2. That it was built from their answers — briefly, without reciting the questions back as a recap (acknowledgment recap reads as filler).
3. The impact if it is wrong — for example: "This is the anchor every other document and every agent reads to understand what your system is for. If it's off, everything downstream drifts with it."

Take one round of changes, then confirm. Because authored prose involves the most interpretation of any class, confirm specifically about the parts where you connected or framed something the operator did not state outright — "I read your goal of X as meaning Y — is that right?" — rather than a generic "does this look right?"

## Discipline guards

- **No fabrication.** Every claim in the authored value must trace to an answer or the confirmed working definition. If a phrase cannot be traced, remove it. Do not add plausible-sounding context the operator did not supply.

- **Operator lists are examples, not exhaustive.** When the operator named a few goals, constraints, or outputs, treat the list as a starting point. Before finalizing, ask whether their description implies something obvious they did not name — and surface it as a question, never add it silently.

- **Epistemic status.** When you connect two things the operator did not explicitly connect, or read an implication into a thin answer, flag that at confirmation time. Do not present an inference as something they said.

- **Honest thinness over false richness.** A vision authored from sparse answers should be short and honest. Do not reach for the quality of a richly-answered example by inventing the missing substance — that is the failure this class exists to prevent, in the opposite direction from the flat-checklist failure that came before it.
