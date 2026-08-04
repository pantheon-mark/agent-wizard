"""The State->Action registry: for every state this project can be stuck in, the
declared way out -- and the ONE place any surface renders that instruction from.

Why this module exists
----------------------
Two blocking states in this package had a real, working, tested exit that no
surface an operator or their assistant reads ever named:

  * a writer the safety check found needs a person could be left as it is by a
    recorded operator decision -- and that decision existed only as a Python
    function, with no command anywhere;
  * a trial unit a crash left mid-flight could be put back by a real command --
    and the only thing that printed that command was the trial's own refusal,
    which is produced by code a crash prevents from running.

A mechanism nobody can discover is not reachable. "The command exists" is not the
bar: someone sitting in the state has to be able to find the way out WITHOUT
already knowing to look. That is what this registry is for, and it is why every
operator-facing instruction about leaving a state is rendered FROM here rather than
written again at each surface. Two independently-authored copies of the same
guidance is a recorded finding in this package, and the copies drifted.

What it is NOT
--------------
Not a gate, and not an authority. It declares what to run; it decides nothing. In
particular it does NOT re-implement any eligibility question: whether a given
writer may actually be acknowledged is answered in exactly one place (the command
layer's guard, over `writer_state_core.ACKNOWLEDGEABLE_WRITER_STATES`), and a
second implementation here -- even as a "precondition predicate" -- would be the
"two paths that must agree" shape this package's worst defects have taken. So
`precondition` below is a plain-language SENTENCE, deliberately not a callable.

SEALED. Closed to operator and to agent authorship
--------------------------------------------------
The action set is a module-level tuple of frozen records. There is no function that
adds to it, no file it reads, and no environment variable it consults -- asserted
structurally over this module's own source, because "we would never do that" is not
a property. That is not fussiness: what this registry hands an operator is a command
to run, so a registry an agent could extend would be a way to get an operator to run
something. It is enrolled in `zones.SEALED_KERNEL_MODULE_PATHS`, and that membership
is load-bearing rather than decorative (scanned as CAPABILITY it trips the
sealed-kernel module boundary on its ordinary internal kernel imports).

Two state vocabularies, and they are NAMESPACED
-----------------------------------------------
This registry spans two independent vocabularies: the bespoke-writer states
(`writer_state_core.WriterState`) and the trial-unit states
(`trial_journal.TRIAL_UNIT_STATES`). They do not collide today. Keying on the bare
state string is how they would -- a name added to one vocabulary that happens to
match a name in the other would silently inherit the other's action, which is the
"never infer identity from incidental structure" trap in its purest form. So every
key here is `state_key(domain, state)`, and a bare state string does not resolve.

Completeness is a GATE, not a claim
-----------------------------------
`GATED_STATE_KEYS` is derived from the two declaring modules' OWN blocking sets --
`BLOCKING_WRITER_STATES` and `RECOVERY_DRIVEN_STATES` -- never from the actions
declared here. Derived the other way round the check would be a tautology and a
deleted action would pass it. Three properties are checked, all of them over
declared sets:

  * every gated state has at least one action (`unactionable_gated_state_keys`);
  * every state in either vocabulary is EITHER gated OR explicitly marked an
    intentional disposition (`unclassified_state_keys`) -- a terminal state is
    permitted only when someone said so, because a state that is terminal by
    OMISSION is exactly the bug this cut exists to remove;
  * no action lands the operator in a state that has no exit
    (`actions_landing_in_a_dead_end`).

Enforcement ceiling (disclosure): build-time + operator-as-approver, NOT a runtime
or OS sandbox -- the same ceiling every module in this package discloses. Naming a
repair does not perform it, and refusing to name one does not prevent anything.

Stdlib only -- no third-party dependencies. The only non-stdlib imports are sibling
modules of this same trusted package.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, Mapping, Tuple

# Spelled `import external_write.<submodule> as _x` rather than the
# `from external_write import <submodule>` form: both mean the same thing to
# Python, but only this one is a form the sibling bypass scanner's sealed-kernel
# module-boundary rule matches -- so this module's SEALED_KERNEL membership is
# load-bearing rather than decorative, and the counterfactual is pinned by test.
import external_write.scan as _scan
import external_write.trial_journal as _journal
import external_write.trial_recovery as _recovery
import external_write.writer_acknowledgement as _acknowledgement
import external_write.writer_state_core as _core


class StateActionError(ValueError):
    """Raised for a state key this registry does not carry, and for an action
    record whose own declared fields are not well-formed.

    An exception rather than an empty result: an empty action list for an unknown
    key reads identically to "this state needs nothing done", and those are the two
    answers that must never be confusable here.
    """


# ---------------------------------------------------------------------------
# Domains and keys
# ---------------------------------------------------------------------------

DOMAIN_BESPOKE_WRITER = "bespoke_writer"
DOMAIN_TRIAL_UNIT = "trial_unit"

DOMAINS: Tuple[str, ...] = (DOMAIN_BESPOKE_WRITER, DOMAIN_TRIAL_UNIT)

#: Separator between domain and state in a key. A colon appears in neither
#: vocabulary, so no state value can spell a key by accident.
KEY_SEPARATOR = ":"


def state_key(domain: str, state: str) -> str:
    """The registry key for `state` in `domain`.

    Refuses an unknown domain rather than minting a key nothing can resolve: a key
    built from a typo'd domain would look exactly like a state nobody classified,
    and those need to be distinguishable.
    """
    if domain not in DOMAINS:
        raise StateActionError(
            f"{domain!r} is not one of this registry's declared domains "
            f"{list(DOMAINS)}")
    if not (isinstance(state, str) and state.strip()):
        raise StateActionError(f"a state must be a non-blank string; got {state!r}")
    return f"{domain}{KEY_SEPARATOR}{state}"


def writer_state_key(state: str) -> str:
    """The key for a bespoke-writer state. One spelling of the domain, used by
    every caller inside and outside this module."""
    return state_key(DOMAIN_BESPOKE_WRITER, state)


def trial_unit_state_key(state: str) -> str:
    """The key for a trial-unit state."""
    return state_key(DOMAIN_TRIAL_UNIT, state)


def _declared_writer_states() -> Tuple[str, ...]:
    """The bespoke-writer vocabulary, read off the declaring class rather than
    re-listed here, so a state added to it appears in the partition below (and
    then fails the classification gate) instead of being invisible."""
    return tuple(sorted(v for k, v in vars(_core.WriterState).items()
                        if not k.startswith("_") and isinstance(v, str)))


#: Every state either vocabulary declares, as keys. DERIVED from the declaring
#: modules -- this is the set the classification gate quantifies over.
DECLARED_STATE_KEYS = frozenset(
    [writer_state_key(s) for s in _declared_writer_states()]
    + [trial_unit_state_key(s) for s in _journal.TRIAL_UNIT_STATES])

#: The states that BLOCK -- the ones that must have a way out. DERIVED from each
#: declaring module's own blocking set, never from the actions below: derived from
#: the actions, the completeness check would be a tautology.
GATED_STATE_KEYS = frozenset(
    [writer_state_key(s) for s in _core.BLOCKING_WRITER_STATES]
    + [trial_unit_state_key(s) for s in _journal.RECOVERY_DRIVEN_STATES])


# ---------------------------------------------------------------------------
# Actors
# ---------------------------------------------------------------------------

#: The operator themself performs it. Everything the operator's own consent is the
#: content of belongs here, and nothing else does: a machine performing one of
#: these on the operator's behalf would be forging what only they can give.
ACTOR_OPERATOR = "operator"

#: The operator's assistant performs it, with the operator watching. Code repair
#: belongs here -- it is work, not consent.
ACTOR_ASSISTANT = "assistant"

ACTORS: Tuple[str, ...] = (ACTOR_OPERATOR, ACTOR_ASSISTANT)


# ---------------------------------------------------------------------------
# The action record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StateAction:
    """ONE declared way out of one or more states.

    action_id:       stable identifier, unique within the registry. Named after
                      what the operator does, not after the module that does it.
    from_states:     the state key(s) this action leaves. Every one must be a
                      GATED key: an action declared for a state that does not
                      block is either a mistake or a sign the upstream blocking
                      set moved.
    actor:           who performs it -- see ACTOR_OPERATOR / ACTOR_ASSISTANT.
    command_builder: callable taking ONE positional subject (the writer relpath,
                      the trial id -- whatever the action is about) and returning
                      the exact, paste-ready, single-physical-line command. Always
                      the OWNING module's own renderer, never a string built here:
                      the command's path is declared once, where the entrypoint
                      lives, and a re-spelling is how a named repair comes to name
                      a path that no longer exists.
    precondition:    a plain-language sentence stating what must hold for this
                      action to succeed. DELIBERATELY NOT A PREDICATE. The
                      condition is already enforced in exactly one place, and a
                      callable here would be a second implementation of the same
                      authorization question -- the shape of four of the last five
                      defects in this family. It is documentation for whoever
                      renders the action, and it is never consulted as a gate.
    expected_state:  the state key this action establishes when it succeeds -- the
                      action's post-condition. Checked to be either an intentional
                      disposition or a state that itself has an action, so no
                      action can land the operator somewhere with no exit.
    instruction:     the operator-facing text, as a template over `{subject}` and
                      `{command}`. A template rather than a fixed prefix because
                      the two shapes differ honestly: one command PERFORMS the
                      action, another CONFIRMS a repair the assistant performed,
                      and a renderer that assumed one shape would misdescribe the
                      other.
    """

    action_id: str
    from_states: Tuple[str, ...]
    actor: str
    command_builder: Callable[[str], str]
    precondition: str
    expected_state: str
    instruction: str

    def __post_init__(self) -> None:
        if not (isinstance(self.action_id, str) and self.action_id.strip()):
            raise StateActionError(f"an action needs an id; got {self.action_id!r}")
        if not self.from_states:
            raise StateActionError(
                f"action {self.action_id!r} declares no from_states -- an action "
                "nothing can reach is not an exit from anything")
        for key in self.from_states:
            if key not in DECLARED_STATE_KEYS:
                raise StateActionError(
                    f"action {self.action_id!r} declares from_state {key!r}, "
                    "which is not a declared state of either vocabulary")
        if self.actor not in ACTORS:
            raise StateActionError(
                f"action {self.action_id!r} declares actor {self.actor!r}, which "
                f"is not one of {list(ACTORS)}")
        if not callable(self.command_builder):
            raise StateActionError(
                f"action {self.action_id!r} has no command builder -- a declared "
                "action with no executable entrypoint is a verdict the operator "
                "cannot act on")
        if not (isinstance(self.precondition, str) and self.precondition.strip()):
            raise StateActionError(
                f"action {self.action_id!r} states no precondition")
        if self.expected_state not in DECLARED_STATE_KEYS:
            raise StateActionError(
                f"action {self.action_id!r} declares expected_state "
                f"{self.expected_state!r}, which is not a declared state")
        for field in ("{subject}", "{command}"):
            if field not in self.instruction:
                raise StateActionError(
                    f"action {self.action_id!r}'s instruction does not carry "
                    f"{field} -- an instruction that names neither the thing nor "
                    "the command is not actionable")


# ---------------------------------------------------------------------------
# The declared actions
# ---------------------------------------------------------------------------

#: The rebuildable-writer instruction. Its first clause is the core's own single
#: declaration of that sentence, formatted with the registry's placeholder so the
#: template comes back with `{subject}` in place -- bound, never re-spelled. The
#: second clause is this registry's addition: the command CONFIRMS the repair, and
#: says so, because it does not perform it.
_REBUILD_INSTRUCTION = (
    _core.BYPASS_UNREPAIRED_TEMPLATE.format(relpath="{subject}")
    + ". Once it is rebuilt, confirm it with: {command}")

ACTIONS: Tuple[StateAction, ...] = (
    StateAction(
        action_id="record_accepted_risk",
        from_states=tuple(writer_state_key(s)
                          for s in sorted(_core.ACKNOWLEDGEABLE_WRITER_STATES)),
        actor=ACTOR_OPERATOR,
        command_builder=_acknowledgement.acknowledgement_command,
        precondition=(
            "the safety check has established that this file needs a person -- our "
            "own rebuild cannot rewrite it -- and the operator has said, in their "
            "own words, that they accept leaving it as it is. Both are enforced by "
            "the command itself, which refuses any other state; this sentence is "
            "what to tell the operator, not a second check"),
        expected_state=writer_state_key(_core.WriterState.ACKNOWLEDGED_RISK),
        instruction=(
            "this cannot be fixed automatically and needs a person: `{subject}` -- "
            "it does something the rebuild flow cannot rewrite for you, so either "
            "change it by hand until it passes the check, or record that you "
            "accept the risk of leaving it as it is (that decision is kept on file "
            "and shown again whenever the file changes) by running this from your "
            "project's top folder, with your own words in place of the last part: "
            "{command}"),
    ),
    StateAction(
        action_id="rebuild_onto_the_sanctioned_path",
        from_states=(writer_state_key(_core.WriterState.BLOCKING_LIVE_ENABLE),),
        actor=ACTOR_ASSISTANT,
        precondition=(
            "every violation recorded against this writer is one our own "
            "remediator covers, which is what put it in this state -- so the "
            "rebuild genuinely clears it"),
        # The check that CONFIRMS the rebuild, not a command that performs it: the
        # rebuild itself is code authoring, which is why its actor is the
        # assistant. The entry clears on its own once the check passes.
        command_builder=_scan.scan_command,
        expected_state=writer_state_key(_core.WriterState.RESOLVED),
        instruction=_REBUILD_INSTRUCTION,
    ),
    StateAction(
        action_id="recover_interrupted_trial",
        # EVERY state a resumed trial must drive to a verdict, declared from the
        # journal's own set rather than listed here. A state added to that set
        # arrives here automatically instead of falling out of the registry.
        from_states=tuple(trial_unit_state_key(s)
                          for s in _journal.RECOVERY_DRIVEN_STATES),
        actor=ACTOR_OPERATOR,
        command_builder=_recovery.recovery_command,
        precondition=(
            "the trial's own durable record is on disk and readable -- it is what "
            "carries the reversal for every unit. The command reads it, refuses if "
            "it cannot, and never re-does the change it is reversing"),
        expected_state=trial_unit_state_key(_journal.STATE_RESTORED_VERIFIED),
        instruction=(
            "a trial run was interrupted before it could put everything back, so a "
            "change it made may still be live on your real record -- trial "
            "`{subject}`. Put it back and confirm it by running this from your "
            "project's top folder: {command}"),
    ),
)


# ---------------------------------------------------------------------------
# States that need NO action, declared POSITIVELY with the reason
# ---------------------------------------------------------------------------

#: Every declared state that is NOT gated, each with the plain-language reason no
#: action is required and the sentence a surface renders for it.
#:
#: This map is the other half of the completeness gate, and it is what makes
#: "terminal" a decision rather than an omission. A state reaches this map only by
#: someone writing a reason down; a state in neither this map nor
#: `GATED_STATE_KEYS` fails `unclassified_state_keys()`. That is the difference
#: between a genuinely settled state and a state nobody thought about -- and the
#: second one, rendered as "nothing to do", is how an operator stops looking.
INTENTIONAL_DISPOSITIONS: Mapping[str, str] = MappingProxyType({
    # Not in the blocking set at all: the file is a test module nothing in the
    # running system invokes, so there is nothing being held back and no risk to
    # accept. Recording a decision about it would put an audit record on file
    # about a non-event.
    writer_state_key(_core.WriterState.NON_LIVE): (
        "`{subject}` was found to be a test file that nothing in your running "
        "system uses, so it is not holding anything back and no action is needed "
        "for it"),
    # The operator has already decided. Deliberately NOT described as finished:
    # the decision is hash-bound, so it voids and the file returns to needing a
    # person the moment its bytes change.
    writer_state_key(_core.WriterState.ACKNOWLEDGED_RISK): (
        "you have already recorded that you accept the risk of leaving `{subject}` "
        "as it is -- that decision stays on file and is put back in front of you "
        "the moment the file changes, so no action is needed right now"),
    # The reaper's state: the writer passed the check and its entry is closed.
    writer_state_key(_core.WriterState.RESOLVED): (
        "`{subject}` now passes the safety check and its item is closed, so no "
        "action is needed for it"),
    # Provably never applied: the intent record is fsynced -- contents and
    # directory entry -- before the mutation is attempted, so a unit still
    # recorded `planned` was never applied and has nothing outstanding.
    trial_unit_state_key(_journal.STATE_PLANNED): (
        "unit `{subject}` was written down before anything was attempted on it, so "
        "nothing was changed on your real record and no action is needed for it"),
    # The settled end of the protocol: observed back at its prior state.
    trial_unit_state_key(_journal.STATE_RESTORED_VERIFIED): (
        "unit `{subject}` was put back and confirmed at the state it was in "
        "before, so this one is settled and no action is needed for it"),
})


#: What to say about a state this registry does not carry -- the branch a state
#: added to either vocabulary without being classified would land on. It REFUSES
#: to characterise the state and routes to a person. It deliberately does not say
#: "no action is needed", because that is the one thing that cannot be established
#: about a state nobody classified: it may be a unit holding a live, unreversed
#: change on the operator's real record.
_UNCLASSIFIED_ROUTE = (
    "`{subject}` is in a state this system has no recorded way out of, so nothing "
    "here can safely tell you what to do about it -- ask your assistant to look at "
    "it with you before treating anything as finished")

#: What to say about a durable trial record that could not be read at all. The
#: trial cannot be identified from it, so no command can be rendered for it; the
#: route is a person. It claims nothing about whether anything is outstanding,
#: because an unreadable recovery record is precisely the thing that cannot
#: establish that nothing is.
_UNIDENTIFIED_RECORD_ROUTE = (
    "a record of a trial run at `{subject}` could not be read, so the trial it "
    "belongs to cannot be identified from it -- a change that trial made may still "
    "be live on your real record. Ask your assistant to look at that file with you "
    "before treating anything as finished")

#: What to say about a scheduled run still being stopped by a pause record that no
#: open item explains. Names the artifact, the actor, and the condition under which
#: clearing it is right -- see ``route_for_stale_pause_record`` for what it
#: deliberately does NOT assert.
_STALE_PAUSE_RECORD_ROUTE = (
    "`{subject}` is still switched off and will not run: it is held by the pause "
    "record at `{record}`, and there is no open item left that explains why. That "
    "means the scheduled work it does is not happening. Ask your assistant to look "
    "at that record with you -- once they have confirmed the script it protects now "
    "passes the safety check, clearing that record is what starts it running again")

#: What to say about an unreadable record of SUPPRESSED SCHEDULED RUNS -- a
#: separate declared route, not a reuse of the one above.
#:
#: WHY IT IS ITS OWN CONSTANT. The trial route above was rendered for this record
#: kind for one commit, and every word of it was false here: it named "a trial run"
#: where no trial exists, and it warned that "a change that trial made may still be
#: live on your real record" when NOTHING WAS WRITTEN -- the whole point of a
#: suppressed invocation is that work did not happen. The branch that renders it
#: withholds the all-clear, so the operator was guaranteed to be shown it. Two
#: callers needing two different true sentences is two declared routes; one string
#: with a hedge bolted on would have made both of them vaguer instead.
#:
#: What it must and must not claim: it cannot say how many runs were stopped (the
#: record that would say is the unreadable one), and it must not imply anything was
#: changed. It routes to a person and claims neither.
_UNREADABLE_SUPPRESSION_RECORD_ROUTE = (
    "the record at `{subject}` of scheduled runs that were stopped could not be "
    "read, so it is not possible to tell from it which scheduled work has been "
    "stopped, or how many times. Nothing was changed by the runs it covers -- they "
    "did not happen -- but something of yours may not be running. Ask your "
    "assistant to look at that file with you before treating anything as finished")


# ---------------------------------------------------------------------------
# The index, and the read API
# ---------------------------------------------------------------------------

def _build_index() -> Mapping[str, Tuple[StateAction, ...]]:
    index: Dict[str, Tuple[StateAction, ...]] = {}
    for action in ACTIONS:
        for key in action.from_states:
            index[key] = index.get(key, ()) + (action,)
    return MappingProxyType(index)


_ACTIONS_BY_STATE = _build_index()


def actions_for_state(key: str) -> Tuple[StateAction, ...]:
    """Every declared action that leaves `key`, in registry order.

    FAIL-CLOSED on an unrecognized key: raises `StateActionError` rather than
    returning `()`. An empty tuple is a real answer here -- it is what a declared
    intentional disposition returns -- so an unknown key must not be able to
    produce the same answer as a state someone decided needs nothing.
    """
    if key not in DECLARED_STATE_KEYS:
        raise StateActionError(
            f"{key!r} is not a state this registry carries. Build a key with "
            "state_key(domain, state); a bare state name does not resolve, "
            "because the two vocabularies this registry spans are namespaced")
    return _ACTIONS_BY_STATE.get(key, ())


def render_action(action: StateAction, subject: str) -> str:
    """`action`'s operator-facing instruction for `subject`, with the exact command
    rendered in place by the owning module's own builder."""
    return action.instruction.format(subject=subject,
                                     command=action.command_builder(subject))


def instruction_for_state(key: str, subject: str) -> str:
    """The whole operator-facing instruction for `subject` in state `key` -- the
    ONE renderer every surface uses.

    NEVER RAISES, and always returns a route. This is the function an acceptance
    refusal, a health report and a skill all call while an operator is waiting, so
    a raise here would turn a state with an exit into a crash. The three outcomes:

      * gated with actions   -> every action's instruction, joined;
      * a declared intentional disposition -> its declared reason, which says no
        action is needed and why;
      * anything else -> `_UNCLASSIFIED_ROUTE`, which routes to a person and
        claims nothing. That covers both a state nobody classified and the
        should-be-impossible case of a gated state with no action, and it is the
        fail-closed direction: the one answer it will not give is "nothing to do".
    """
    if key in DECLARED_STATE_KEYS:
        actions = _ACTIONS_BY_STATE.get(key, ())
        if actions:
            return " ".join(render_action(a, subject) for a in actions)
        disposition = INTENTIONAL_DISPOSITIONS.get(key)
        if disposition:
            return disposition.format(subject=subject)
    return _UNCLASSIFIED_ROUTE.format(subject=subject)


def route_for_unclassified_state(subject: str) -> str:
    """What to tell the operator about `subject` when it is in a state this
    registry does not carry a way out of.

    Exposed as its own function, rather than reached by handing
    `instruction_for_state` a key it will not recognize, because a caller that is
    ALREADY inside a refusal needs this answer and must not be able to get a
    "no action is needed" sentence instead. A declared-but-non-blocking state
    would produce exactly that, and printing it inside a refusal would contradict
    the refusal it is part of.
    """
    return _UNCLASSIFIED_ROUTE.format(subject=subject)


def route_for_unidentified_record(path: str) -> str:
    """What to tell the operator about an unreadable durable record of a TRIAL RUN
    -- one whose trial cannot be identified from it, and which may therefore be
    holding a live, unreversed change on their real record.

    TRIAL RECORDS ONLY. There is a sibling route for an unreadable record of
    suppressed scheduled runs (``route_for_unreadable_suppression_record``), because
    this sentence's two central claims -- that a trial is involved, and that a change
    may still be live -- are both FALSE for that record kind. Reusing this one there
    put a guaranteed-to-be-seen false sentence in front of the operator; the fix was
    a second declared route, not a vaguer shared one. A future caller with a third
    record kind needs a third route, not this one.
    """
    return _UNIDENTIFIED_RECORD_ROUTE.format(subject=path)


def route_for_stale_pause_record(entrypoint_relpath: str,
                                 pause_record_location: str) -> str:
    """What to tell the operator about a scheduled run that is STILL being stopped
    by a pause record for which no open item exists.

    A DECLARED ROUTE, not the generic "no recorded way out". It is reached when the
    guard on ``entrypoint_relpath`` is still firing while the writer's
    migration item has been closed -- which happens for real: the auto-reap closes
    the item once the file has changed and passes the check, and nothing then clears
    the pause record for a writer that is not a capability. Rendered generically,
    the operator was told the state had "no recorded way out", which named neither
    the thing to change nor anyone who could change it.

    ``pause_record_location`` is passed IN rather than composed here: this module has
    no business spelling that path, which is already duplicated-by-value at each
    side of the build/emitted boundary that needs it. The caller has the constant.

    WHAT IT DOES AND DOES NOT ASSERT. It does not say the script is now correct --
    this state is also reachable for a writer whose item was never opened, so
    "your script is fixed" would be false in that case. It says what IS established:
    the run is stopped, no open item explains it, the record that stops it is at a
    named location, and the named actor can clear it once they have confirmed the
    script is right. Performing that does clear it.

    DISCLOSED: this hands over an artifact and an actor, not a paste-ready command,
    because no sanctioned command clears a pause record for a non-capability
    mechanism today (``lifecycle_state.complete_migration`` covers capabilities and
    requires a canonical id, an acceptance receipt and a copy-run proof). That gap is
    recorded rather than papered over with an invented invocation.
    """
    return _STALE_PAUSE_RECORD_ROUTE.format(
        subject=entrypoint_relpath, record=pause_record_location)


def route_for_unreadable_suppression_record(path: str) -> str:
    """What to tell the operator about an unreadable record of SUPPRESSED SCHEDULED
    RUNS -- one that cannot say which work was stopped, or how many times.

    Claims nothing about anything having been changed, because nothing was: a
    suppressed run is one that did not happen. See
    ``_UNREADABLE_SUPPRESSION_RECORD_ROUTE`` for why this is its own constant.
    """
    return _UNREADABLE_SUPPRESSION_RECORD_ROUTE.format(subject=path)


# ---------------------------------------------------------------------------
# The completeness gate
# ---------------------------------------------------------------------------

def unactionable_gated_state_keys() -> Tuple[str, ...]:
    """Every BLOCKING state with no declared action. Must be empty.

    Quantified over `GATED_STATE_KEYS`, which is derived from the two declaring
    modules' own blocking sets -- so adding a blocking state upstream fails this,
    and deleting an action here fails this. Quantified over the actions instead, it
    would be a tautology.
    """
    return tuple(sorted(key for key in GATED_STATE_KEYS
                        if not _ACTIONS_BY_STATE.get(key)))


def unclassified_state_keys() -> Tuple[str, ...]:
    """Every declared state that is neither gated nor an explicitly declared
    intentional disposition. Must be empty.

    This is the assertion that makes a terminal state a DECISION. A state that is
    terminal by omission lands here; a state someone wrote a reason for does not.
    """
    return tuple(sorted(DECLARED_STATE_KEYS - GATED_STATE_KEYS
                        - set(INTENTIONAL_DISPOSITIONS)))


def doubly_classified_state_keys() -> Tuple[str, ...]:
    """Every state declared BOTH blocking and needing no action. Must be empty --
    the two answers are contradictory, and a renderer would have to pick one."""
    return tuple(sorted(GATED_STATE_KEYS & set(INTENTIONAL_DISPOSITIONS)))


def actions_landing_in_a_dead_end() -> Tuple[str, ...]:
    """Every action whose `expected_state` has neither an action of its own nor a
    declared intentional disposition. Must be empty.

    An exit into a state with no exit is not an exit. This cut exists to close two
    unreachable states; an action that landed in a third would defeat it.
    """
    stuck = []
    for action in ACTIONS:
        target = action.expected_state
        if _ACTIONS_BY_STATE.get(target):
            continue
        if target in INTENTIONAL_DISPOSITIONS:
            continue
        stuck.append(action.action_id)
    return tuple(sorted(stuck))
