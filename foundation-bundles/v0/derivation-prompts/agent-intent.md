# Agent-Intent Derivation Prompt

## Class + target fields

Agent-intent is a synthesis-style derivation applied specifically to the operator's agent roster answers. For each agent the operator described, it produces a narrow, structured intent object that captures what the agent is for and what resources it claims — nothing more. Downstream processes use this intent to make binding decisions about model, permissions, cron schedule, and filesystem paths. This prompt derives the input to those decisions; it does not make the decisions itself.

This class produces one intent object per agent. All intent objects together form the `AGENT_ROSTER_ROWS` field (the agent-intent layer of it). Each object contains:

| Sub-field | Description |
|---|---|
| `display_name` | The agent's name, verbatim from the operator's answer |
| `function_summary` | One sentence: what this agent does |
| `role_intent` | Two to four sentences: why this agent exists in the system and what problem it solves for the operator |
| `acceptance_signals` | What "done well" looks like for this agent — drawn from the operator's language |
| `output_purpose` | What the agent's output is used for (by a human, another agent, or a downstream system) |
| `criticality_tier` | One of the allowed criticality values defined in the field manifest |
| `resource_claims` | Whether the agent must run on a schedule (`requires_cron`). This is the only resource claim recorded for this system shape — an agent's relationship to external systems (and any login or key it needs) is captured separately at the dependencies step, not as a per-agent claim here. |
| `confidence` | `high`, `medium`, or `low` — your confidence that this intent object accurately reflects what the operator described |
| `insufficiency_flags` | List of sub-fields where operator input was too thin to produce a reliable value |
| `source_spans` | For each sub-field, the question ID(s) the value was drawn from |

## Inputs

Primary sources: AP-2, AP-3, ARCH-2, ARCH-3. Also draw from: `VISION_PURPOSE`, `VISION_GOALS`, `VISION_SCOPE_BOUNDARY`, `CORE_PURPOSE`, and any early-mention captures tagged to the approach or architecture steps.

For each agent, trace `source_spans` field-by-field — do not apply a single blanket source to the whole intent object.

## Output contract

Produce one intent object per agent the operator named. If the operator's answers describe an agent's purpose only vaguely, produce what you can and flag the gaps in `insufficiency_flags` — do not invent detail to fill out a thinly described agent.

**Critical constraint — scope of this derivation.** The wizard derives INTENT and resource CLAIMS only. It must NEVER invent or assign:
- Filesystem paths (which directories the agent reads or writes)
- Model selection (which Claude model runs this agent)
- Cron cadence (the specific schedule for a scheduled agent)
- Permission grants (which tools or capabilities the agent is allowed)

Those four items are determined downstream from the system's overall policy and shape. Assigning them here would pre-empt those decisions with guesses. If the operator volunteers a specific value for any of these — for example, "I want this agent to run every morning" — capture it verbatim in `source_spans` as operator input to pass forward, but do not populate a cron cadence field in the intent object itself.

Audit envelope requirements (for the `AGENT_ROSTER_ROWS` field as a whole):
- `_source`: `claude-derived-operator-confirmed`
- `_derivation_class`: `synthesis` (agent-intent is a sub-type of synthesis)
- `_decision_field`: `false` (the intent objects are input to decisions, not decisions themselves — except criticality tier, which is a classification)
- `_decision_kind`: `none`
- `_derivation_inputs`: non-empty list of the prior **payload field keys** combined — the derived vision fields used (`VISION_PURPOSE`, `VISION_GOALS`, `VISION_SCOPE_BOUNDARY`, `CORE_PURPOSE`). The validator rejects anything that is not a payload key, so the raw roster question IDs (AP-2, AP-3, ARCH-2, ARCH-3) do NOT go here — those are recorded per sub-field in `source_spans` (and as the field's `_source_question_ids` provenance), never in `_derivation_inputs`

**Never fabricate.** If an agent is named but its purpose is not described, produce a skeleton object with `confidence: low` and all substantive sub-fields in `insufficiency_flags`. Do not invent a plausible role.

## Confirmation hooks

Show the operator one agent at a time (or all agents together if the roster is small — three or fewer):
1. The intent object — formatted readably, not as raw data.
2. The answers it was drawn from — one line per sub-field showing the source.
3. Whether it runs on a schedule — if the agent must wake and run on its own (rather than only when the operator asks), call that out explicitly: "I'm flagging this agent as one that runs on a schedule based on what you described. Is that right?"
4. The impact if it is wrong — for example: "The function summary and role intent are what the agent reads at the start of every session to understand its own job. If they are off, the agent will make misaligned decisions from the very first run."

**Forced confirmation when criticality is at the highest tier.** If any agent's `criticality_tier` is set to the highest allowed value (as defined in the manifest), do not proceed past that agent's confirmation without an explicit operator acknowledgment. State clearly: "I have marked [agent name] as your most critical agent. That means failures here have the highest business impact. Please confirm you agree before we move on."

## Discipline guards

- **Operator lists are examples, not exhaustive.** When the operator names agents, they are naming the ones they thought of — not necessarily every agent their system will need. Before finalizing the roster, ask yourself: given the goals and scope the operator described, is there a function they clearly need that is not covered by any named agent? If yes, surface it: "You described [goal] but I don't see an agent responsible for [function] — did you intend to leave that out, or should we add one?"

- **No fabrication.** Every sub-field in every intent object must trace to operator input. A well-structured intent object that is partly invented is worse than a sparse one that is entirely honest — downstream processes treat these objects as authoritative operator input.

- **Epistemic status.** Set `confidence` accurately. `high` means the operator described this agent clearly and in enough detail. `medium` means the intent object is plausible but some sub-fields involved inference. `low` means the operator barely described this agent and the intent object is mostly a structural placeholder. Surface low-confidence agents explicitly at confirmation time rather than hoping the operator will notice.
