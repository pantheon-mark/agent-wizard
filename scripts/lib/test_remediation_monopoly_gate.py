"""LOAD-BEARING GATE: an operator-facing surface may not hand-author a REMEDIATION
INSTRUCTION about a state the state->action registry declares a way out of. The
instruction is rendered from the registry, or it does not exist.

Why this gate exists at all
---------------------------
A completeness gate over a registry proves nothing if a surface can simply BYPASS
the registry and write its own instruction. That is not hypothetical here: the
composite health surface's per-file descriptions and the upgrade impact notice
drifted into two independently-authored copies of the same guidance, and the copies
disagreed -- one of them told an operator to rebuild a file that no rebuild of ours
can rewrite, which is a dead end dressed as a next step. The registry removed the
duplication that existed; this gate is what stops the next copy being written.

WHAT THIS RULE GOVERNS, AND WHAT IT DOES NOT
--------------------------------------------
Stated here so the next author does not have to guess, and so nobody has to widen
the rule to find out.

  GOVERNED -- a REMEDIATION INSTRUCTION: text that tells the operator (or their
  assistant) what to DO in order to LEAVE a state the registry declares an action
  for. That includes a paste-ready command for one of the registry's declared
  entrypoints, and any imperative naming one of the registry's declared repairs.

  NOT GOVERNED -- a DIAGNOSIS or a DESCRIPTION: what was found, what state
  something is in, what a past notice got wrong. A surface may say what happened
  in its own words; a HISTORICAL CORRECTION of an earlier notice is a description
  of what was wrong, not an instruction, and is likewise not governed. The moment
  such text says what to do about it, that sentence comes from the registry.

  NOT GOVERNED -- a refusal's own REASON. A command may say in its own words why it
  refused. What it may not do is author the repair; see "the one structural
  exception" below for the single place where that boundary is load-bearing.

WHY THIS IS AST-BASED, NOT TEXT-BASED
-------------------------------------
A plain text search cannot answer this question. The registry's OWN instruction
text contains every phrase a text rule would ban, so a text rule would flag the
one place the sentence is supposed to live -- and the only way to get it green
would be to allowlist whole files, including the files most likely to regress.
That is not a gate. Three properties here are structural and none of them is
visible to a text search:

  * PROSE IS NOT CODE. A docstring or a comment that quotes a banned sentence in
    order to explain it is never flagged, because docstrings are identified as
    docstrings and comments are not in the tree at all. Several modules here
    document the wording at length; none of them is a violation.
  * A SENTENCE SPLIT ACROSS PIECES IS STILL ONE SENTENCE. The unit of text is the
    maximal string-valued EXPRESSION -- f-string, implicit concatenation, ``+``,
    ``%``, ``"...".format(...)`` -- with every literal part inside it joined. So
    splitting a banned sentence over two literals, or switching away from an
    f-string, is not a way around this.

    STATED EXACTLY, because a looser version of this claim was defeated by a
    five-line probe: the *literal* parts are always joined, and for the command
    rule the text is additionally resolved through ONE HOP over module-level
    string constants (``resolved_text``), so naming a path constant instead of
    spelling the path is caught in the three forms an author actually reaches for
    -- ``+ REL``, ``f"…{REL}"`` and ``"…{}".format(REL)``. That list is
    ILLUSTRATIVE, NOT EXHAUSTIVE. What is NOT resolved: a value arriving as a
    function parameter, a local variable, the return of a call, an attribute of an
    object, or a name reached through two hops of anything other than
    module-level constants. There is no data-flow analysis here and none is
    intended. The perverse edge is worth naming: the standing "single source,
    never re-spelled" rule pushes an author toward indirection, which is exactly
    the direction this hop had to be added to cover, and it covers one hop only.
  * A SANCTIONED SENTENCE IS RECOGNISED BY DERIVATION, NOT BY AN ALLOWLIST. A
    literal outside the registry is permitted only when BOTH hold: the registry
    itself declares that text (checked against its own declared and rendered
    instructions at run time), AND the registry's own source reads that text out
    of THIS module by name (``registry_bound_constants``). Membership in the
    imported set is deliberately not sufficient -- it was, in the first version of
    this gate, and a verbatim second copy of any declared instruction template
    then passed in five different modules. Nothing is exempted for being in a
    particular file.

THE FIVE BANNED SHAPES
----------------------
  ``copied_registry_text``         an authored text that CARRIES a whole sentence
                                   the registry declares, where the registry does
                                   not read that text out of this module. The
                                   mirror image of the permit rule above, and it is
                                   here because the two containment directions
                                   catch different things: a literal that is PART
                                   of a declared sentence may be the one clause the
                                   registry composes from, while a literal that
                                   CONTAINS one is a copy. Without it the TEMPLATE
                                   form of an action whose instruction carries
                                   neither a repair verb nor a spelled path -- the
                                   accept-the-risk and recover-a-trial ones -- was
                                   invisible to every other signature, which is
                                   exactly the form a second author would paste.
  ``authored_repair_directive``    an authored text carrying a repair imperative
                                   with an object (``rebuild it`` / ``rebuild the
                                   ...``) together with the sanctioned write
                                   path as its destination -- the one repair in
                                   this package that has no command of its own and
                                   so can only be recognised by what it names.
                                   Permitted only where the registry declares that
                                   exact text.
  ``authored_registry_command``    an authored text that embeds one of the
                                   registry's DECLARED entrypoint paths in prose.
                                   The paths are derived from the registry's own
                                   actions, never listed here. A bare command
                                   prefix or a module's own declaration of its
                                   entrypoint path is not prose and is not
                                   flagged; a sentence that hands the operator the
                                   command is.
  ``state_selected_authored_text`` an authored text SELECTED BY a state of either
                                   vocabulary the registry covers -- a mapping
                                   keyed on that state, or an equality/membership
                                   branch on it. This shape is wording-independent
                                   on purpose: the question "what do I say about
                                   this state" has exactly one answer, and a
                                   second answer is the defect whatever words it
                                   uses.
  ``authored_repair_render``       a module other than the registry FORMATTING a
                                   declared repair clause into a sentence of its
                                   own. Declaring the clause outside the registry is
                                   sometimes forced -- two consumers need it and
                                   only one of them can import the registry -- so
                                   declaration is permitted and composition of one
                                   declared clause into another is still
                                   declaration. Rendering is not: it is exactly what
                                   made the deepest layer's entry description
                                   state-blind. It had the sentence to hand and no
                                   way to know which state it was describing, so it
                                   told a file that needs a person to rebuild
                                   itself. The bearing constants are DERIVED by
                                   resolving each module's own module-level string
                                   constants, never listed.

WHAT THIS GATE DOES NOT SEE
---------------------------
Disclosed rather than left to be discovered, because an undisclosed boundary is
the likeliest place for the next instance to arrive. Each of these was checked
against the real tree, not assumed.

  * TEXT THAT IS NOT IN THE SCANNED SET. The scanned set is the modules the
    emitter DECLARES it ships into an operator project (see ``_scanned_files``).
    Three populations are therefore outside it, each for its own reason:
      - the toolkit's own build-side modules, including the one that writes the
        post-upgrade impact notice and the one that writes each queue entry's
        recorded next step. Those texts reach an operator, and the notice is half
        of the drift that motivated this gate -- but they are produced by code that
        runs against a project which may be several versions behind, so routing
        them through "the registry" first requires deciding WHICH copy of the
        registry is authoritative at upgrade time. That is a version-skew decision
        this gate must not settle by fiat. Measured with these same three
        signatures, the toolkit tree has exactly one hit today and it is inside an
        emitter template's docstring.
      - the emitted skill documents. They are markdown, so there is no expression
        to inspect; what protects them is that each command they show is pinned
        byte-for-byte against the builder that renders it.
      - the released bundle copies. A released version is immutable and several of
        them still carry text this gate bans; scanning them would make the gate
        red for history nobody may edit.
  * A REMEDIATION THAT NAMES NEITHER THE SANCTIONED PATH NOR A DECLARED COMMAND.
    An instruction phrased purely as advice -- "change it by hand", "ask someone to
    look at it" -- reaches no rule here. Measured, for honesty: the accept-the-risk
    repair was the one declared action whose instruction could be written without
    either anchor, and the reason it is caught today is that its declared
    instruction carries the command;
    ``test_the_signature_recognises_every_instruction_the_registry_DECLARES`` is
    what keeps that true as the registry changes, rather than leaving it to luck.
  * TEXT ASSEMBLED AT RUN TIME FROM DATA. An instruction read out of a JSON queue
    entry is not a literal in any module here. That is deliberate -- an entry
    speaking in its own recorded words is the one thing the registry cannot know --
    but it means the words themselves were authored somewhere this gate does not
    look.
  * A STATE-SELECTED TEXT REACHED BY A SHAPE OTHER THAN A MAPPING OR AN
    EQUALITY/MEMBERSHIP BRANCH. A dispatch table built at run time, a ternary, or a
    ``match`` statement is not matched. Inequality branches are deliberately
    excluded: ``if state != STATE_UNDO_INTENT`` is a guard reporting what went
    wrong, not an answer about a state.
  * THE OPERATOR'S OWN PROJECT. Nothing here runs in an emitted project and
    nothing here reads project state; this is a build-time control over this
    repository's own sources, which is the whole enforcement ceiling this package
    claims for itself.

WHAT IS EXEMPT, AND HOW
-----------------------
There are NO file-level exemptions. Every exemption is one line carrying its own
justification, at the site:

    # remediation-monopoly-exempt: <why this text is authored here and not rendered>

The marker is recognised on any physical line of the offending expression, or in
the comment block immediately above it.
``test_the_exemption_surface_is_pinned`` pins the STRUCTURAL identity of every
exempted finding -- ``file::kind::enclosing symbol`` -- with its count, and not how
many markers exist nor where they sit on the page. Line numbers are deliberately
not part of the identity: they drift on any unrelated edit above, which would force
edits to this gate for changes that have nothing to do with it and train the
reflexive marker-adding this gate exists to resist. The same test rejects a marker
whose justification is a stub, and a marker that exempts nothing, so one cannot be
planted ahead of a shape it will later cover.

THE ONE STRUCTURAL EXCEPTION, AND WHY IT IS NOT A DRIFT RISK
------------------------------------------------------------
The command layer that records an operator's accepted-risk decision refuses a
writer that is not in the one state such a decision applies to, and it says why in
its own words, keyed on the state it found. It CANNOT render that from the
registry: the registry imports the command layer's own facade, so the reverse edge
would be a cycle, and the registry also reaches the trial modules, whose
pre-existing two-module cycle would then land inside the writer-state cluster's
acyclicity closure -- an invariant proved separately and deliberately kept narrow.
So that map is exempted, by two pinned lines, as ``state_selected_authored_text``.

The exemption covers the refusal's FRAMING only. The one clause it shares with the
registry's rebuild instruction is BOUND from the single declaration both can reach,
not re-spelled -- so the two cannot drift, and
``test_the_repair_clause_has_exactly_one_home_in_the_package`` is what proves it.
That is the difference between an exemption and a hole.

Run: python3 -m unittest discover -s wizard/scripts/lib \\
         -p test_remediation_monopoly_gate.py
"""
import ast
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

_WIZARD = Path(__file__).resolve().parents[2]
_AGENTS_LIB = _WIZARD / "agents" / "lib"
_EMITTED_LIB_REL = "agents/lib/external_write"
_EMITTED_LIB = _WIZARD / _EMITTED_LIB_REL

for _p in (str(_AGENTS_LIB), str(_WIZARD / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_emitter                                          # noqa: E402
from external_write import state_actions                      # noqa: E402
from external_write import trial_journal                      # noqa: E402
from external_write import writer_state_core                  # noqa: E402

_EXEMPTION_MARKER = "remediation-monopoly-exempt:"

#: A repair verb, in the shape that makes it an INSTRUCTION rather than a
#: description: an imperative with an object. ``rebuild it`` is an instruction;
#: ``is rebuilt`` and ``it routes through`` are statements about what happened or
#: what is true, and this package's operator-facing surfaces legitimately contain
#: both. Kept as a verb set x an object set rather than a phrase list so a new
#: object word does not need a new entry.
_REPAIR_VERBS = ("rebuild", "re-build", "reroute", "re-route", "route", "move")
_REPAIR_OBJECTS = ("it", "this", "that", "the", "these", "those", "each", "every",
                   "all", "any", "your", "its")

#: The destination that makes a repair imperative THE declared bypass repair, as
#: opposed to repair advice about some other subject entirely. Without this second
#: half the rule would fire on every "then run this check again" in the package and
#: refuse every build, which is the failure mode a fail-closed check has to be
#: designed against rather than discovered in.
_SANCTIONED_DESTINATIONS = ("sanctioned", "safe write path",
                            "safe, tracked write path",
                            "safety-gated write surface", "gated write surface")

#: Placeholder used when rendering a declared instruction for comparison.
_PLACEHOLDER_SUBJECT = "{subject}"

#: How much of a registry-declared sentence a literal must carry before it counts as
#: a COPY of it. A short fragment of a long sentence is a coincidence -- "no action
#: is needed for it" appears in several unrelated places -- while forty normalised
#: characters of one is not. Disclosed bound: a copy of a declared sentence shorter
#: than this is not seen as a copy, and the shortest sentence the registry declares
#: is asserted to be longer than it.
_COPY_MIN_CHARS = 40


# ---------------------------------------------------------------------------
# The scanned set -- DERIVED from the producer that ships these files
# ---------------------------------------------------------------------------

def _declared_emitted_basenames() -> Tuple[str, ...]:
    """The external-write lib files the agent-layer emitter DECLARES it ships.

    Derived from the emitter rather than from a directory walk, deliberately: what
    this gate is about is text that reaches an operator, and the emitter's
    enrolment list -- not the shape of a folder -- is what decides that. A module
    sitting in the folder unenrolled reaches nobody; a module enrolled but missing
    is a real defect, and it is reported as one below rather than silently skipped.
    """
    return tuple(agent_emitter._EXTERNAL_WRITE_LIB_FILES)


class ScannedSetError(RuntimeError):
    """The producer's declared set could not be resolved to readable files."""


def _scanned_files() -> List[Path]:
    """The producer's declared set, resolved against this repository's live source
    tree, fail-closed on anything it cannot positively read.

    ``os.stat`` rather than ``exists()``: an ABSENT file and an INACCESSIBLE one are
    different defects and a gate that cannot tell them apart reports the wrong one.
    """
    names = _declared_emitted_basenames()
    if not names:
        raise ScannedSetError(
            "the emitter declares no external-write lib files, so this gate would "
            "quantify over nothing and pass vacuously")
    resolved: List[Path] = []
    problems: List[str] = []
    for name in names:
        path = _EMITTED_LIB / name
        try:
            os.stat(str(path))
        except FileNotFoundError:
            problems.append(f"{_EMITTED_LIB_REL}/{name}: enrolled for emission but "
                            "absent from the source tree")
            continue
        except OSError as exc:
            problems.append(f"{_EMITTED_LIB_REL}/{name}: present but not readable "
                            f"({exc.strerror})")
            continue
        resolved.append(path)
    if problems:
        raise ScannedSetError("; ".join(problems))
    return sorted(resolved)


# ---------------------------------------------------------------------------
# What the registry DECLARES -- derived, never listed
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Comparable form: every ``{placeholder}`` collapsed to one token, whitespace
    collapsed, case dropped. Placeholders are collapsed because the same sentence
    is legitimately spelled with different field names by the module that declares
    it and the registry that formats it."""
    return re.sub(r"\s+", " ", re.sub(r"\{[^{}]*\}", "{}", text)).strip().lower()


def registry_declared_texts() -> Tuple[str, ...]:
    """Every operator-facing text the registry itself declares, normalised.

    Both the TEMPLATE and the fully RENDERED form of each action's instruction, so
    a module that declares a clause the registry composes into an instruction is
    recognised either way.
    """
    texts: List[str] = []
    for action in state_actions.ACTIONS:
        texts.append(action.instruction)
        texts.append(state_actions.render_action(action, _PLACEHOLDER_SUBJECT))
    texts.extend(state_actions.INTENTIONAL_DISPOSITIONS.values())
    texts.append(state_actions.route_for_unclassified_state(_PLACEHOLDER_SUBJECT))
    texts.append(state_actions.route_for_unidentified_record(_PLACEHOLDER_SUBJECT))
    texts.append(
        state_actions.route_for_unreadable_suppression_record(_PLACEHOLDER_SUBJECT))
    texts.append(state_actions.route_for_stale_pause_record(
        _PLACEHOLDER_SUBJECT, [_PLACEHOLDER_SUBJECT]))
    return tuple(_normalise(t) for t in texts)


def registry_entrypoint_relpaths() -> Tuple[str, ...]:
    """The project-relative script paths the registry's own actions render.

    Derived by asking each action's command builder for a command and reading the
    script out of it -- so an action whose entrypoint moves is policed at its new
    path without anyone remembering to update a list here.
    """
    found = set()
    for action in state_actions.ACTIONS:
        for token in action.command_builder(_PLACEHOLDER_SUBJECT).split():
            if token.endswith(".py"):
                found.add(token)
    return tuple(sorted(found))


def registry_bound_modules() -> frozenset:
    """The registry module plus every sibling it imports.

    A declared text is permitted OUTSIDE the registry only in a module the registry
    imports, because that is what makes the registry the binder rather than a
    second author. Read off the registry's own source, so adding an import to
    launder a copy is a visible edit to the registry itself.
    """
    tree = ast.parse((_EMITTED_LIB / "state_actions.py").read_text(encoding="utf-8"))
    found = {"state_actions"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if "external_write" in parts:
                    index = parts.index("external_write")
                    if index + 1 < len(parts):
                        found.add(parts[index + 1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if "external_write" in parts:
                index = parts.index("external_write")
                if index + 1 < len(parts):
                    found.add(parts[index + 1])
                else:
                    found.update(a.name for a in node.names)
    return frozenset(found)


def registry_covered_state_values() -> frozenset:
    """Every state value of either vocabulary the registry spans, read off the
    declaring modules rather than re-listed -- so a state added upstream is policed
    without an edit here."""
    writer = {v for k, v in vars(writer_state_core.WriterState).items()
              if not k.startswith("_") and isinstance(v, str)}
    return frozenset(writer | set(trial_journal.TRIAL_UNIT_STATES))


def distinctive_state_values() -> frozenset:
    """The covered state values a BARE STRING LITERAL may be joined on.

    A literal that happens to equal a state's value is not evidence that it IS that
    state, and inferring identity from an incidental match is the trap this package
    has shipped repeatedly. Two of the covered values -- ``resolved`` and
    ``planned`` -- are ordinary English words that other vocabularies here use for
    other things (an ownership lookup's outcome, for one), so joining a bare literal
    on them would flag text that has nothing to do with a writer or a trial unit.
    A multi-word snake_case token is a vocabulary identifier and cannot collide by
    accident; a single lowercase word can. The named-constant forms
    (``WriterState.RESOLVED``, ``STATE_PLANNED``) are unaffected -- naming the
    vocabulary IS the declaration, and those are matched in full.
    """
    return frozenset(v for v in registry_covered_state_values() if "_" in v)


#: An authored operator-facing sentence, as distinct from an identifier, a dict key,
#: a field name or a status token. The state-selected rule is wording-independent,
#: so without this it would flag every string that happens to sit inside a
#: state-keyed structure -- including the field names a lookup reads. Disclosed
#: bound: a remediation phrased in four words or fewer is not seen as prose.
_PROSE_MIN_WORDS = 5


def _is_operator_prose(text: str) -> bool:
    return len(_normalise(text).split()) >= _PROSE_MIN_WORDS


def _writer_state_member_names() -> frozenset:
    return frozenset(k for k, v in vars(writer_state_core.WriterState).items()
                     if not k.startswith("_") and isinstance(v, str))


def _trial_state_constant_names() -> frozenset:
    return frozenset(k for k, v in vars(trial_journal).items()
                     if k.startswith("STATE_") and isinstance(v, str))


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

class Finding(NamedTuple):
    relpath: str
    lineno: int
    end_lineno: int
    kind: str
    symbol: str          # enclosing function/method/class qualname, or "<module>"
    detail: str

    @property
    def identity(self) -> str:
        """The finding's STABLE identity: where it sits in the module's structure,
        not where it sits on the page. Invariant under an unrelated edit above it,
        and different the moment the exempted construction is replaced by another
        one somewhere else."""
        return "{}::{}::{}".format(self.relpath, self.kind, self.symbol)

    def render(self) -> str:
        return "{}:{}: {} in {} -- {}; render it from the state->action registry " \
               "(state_actions.instruction_for_state), or mark the line " \
               "'# {} <why>'".format(self.relpath, self.lineno, self.kind,
                                     self.symbol, self.detail, _EXEMPTION_MARKER)


_DEF_TYPES: Tuple[type, ...] = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _symbol_spans(tree: ast.Module) -> List[Tuple[int, int, str]]:
    spans: List[Tuple[int, int, str]] = []

    def descend(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _DEF_TYPES):
                qualname = prefix + child.name
                spans.append((child.lineno,
                              getattr(child, "end_lineno", None) or child.lineno,
                              qualname))
                descend(child, qualname + ".")
            else:
                descend(child, prefix)

    descend(tree, "")
    return spans


def _symbol_at(spans: Sequence[Tuple[int, int, str]], lineno: int) -> str:
    enclosing = [s for s in spans if s[0] <= lineno <= s[1]]
    if not enclosing:
        return "<module>"
    return min(enclosing, key=lambda s: s[1] - s[0])[2]


# ---------------------------------------------------------------------------
# Authored text: the maximal string EXPRESSION, with its literal parts joined
# ---------------------------------------------------------------------------

def _docstring_nodes(tree: ast.Module) -> frozenset:
    """Every docstring Constant in the module. Prose explaining a banned sentence
    is not the sentence."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            found.add(id(body[0].value))
    return frozenset(found)


def _is_string_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return any(_is_string_expression(s) for s in (node.left, node.right))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "format" \
            and _is_string_expression(node.func.value):
        return True
    return False


def _joined_literal_text(node: ast.AST, docstrings: frozenset) -> str:
    parts = [sub.value for sub in ast.walk(node)
             if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
             and id(sub) not in docstrings]
    return " ".join(parts)


def _referenced_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def resolved_text(node: ast.AST, constants: Mapping[str, str]) -> str:
    """``node``'s text with its parts IN SOURCE ORDER, substituting the text of any
    module-level string constant it names.

    Order matters: a constant composed as ``DIAGNOSIS + " -- " + REPAIR`` has almost
    no literal content of its own, and joining its parts out of order would make a
    containment test against it meaningless.

    ONE HOP, and the bound is disclosed rather than discovered: ``constants`` holds
    module-level string constants only, so a value that arrives as a function
    parameter, as a local, from a call, or through a name this map does not carry is
    NOT substituted. There is no data-flow analysis here.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else ""
    if isinstance(node, ast.JoinedStr):
        return "".join(resolved_text(part, constants) for part in node.values)
    if isinstance(node, ast.FormattedValue):
        return resolved_text(node.value, constants)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return (resolved_text(node.left, constants)
                + resolved_text(node.right, constants))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        # The template, then whatever is interpolated into it. Appended rather than
        # substituted into the placeholders: this text is only ever tested for
        # CONTAINMENT, and appending can only ever add, never lose.
        return (resolved_text(node.left, constants) + " "
                + resolved_text(node.right, constants))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "format":
        parts = [resolved_text(node.func.value, constants)]
        parts.extend(resolved_text(a, constants) for a in node.args)
        parts.extend(resolved_text(k.value, constants) for k in node.keywords)
        return " ".join(p for p in parts if p)
    name = _referenced_name(node)
    if name is not None:
        return constants.get(name, "")
    return ""


def authored_texts_in(roots: Sequence[ast.AST],
                      docstrings: frozenset) -> List[Tuple[ast.AST, str]]:
    """Every MAXIMAL string-valued expression under ``roots``, paired with its
    joined literal text. Maximal, so one authored sentence is one unit however it is
    spelled; and per-expression rather than per-statement, so a container holding
    many independent sentences does not have their words mixed together.

    ``docstrings`` is always computed over the REAL module tree and passed in, so a
    branch body examined on its own can never have its first statement mistaken for
    a docstring."""
    nested = set()
    for root in roots:
        for node in ast.walk(root):
            if not _is_string_expression(node):
                continue
            for sub in ast.walk(node):
                if sub is not node:
                    nested.add(id(sub))
    out: List[Tuple[ast.AST, str]] = []
    seen = set()
    for root in roots:
        for node in ast.walk(root):
            if not _is_string_expression(node) or id(node) in nested:
                continue
            if id(node) in docstrings or id(node) in seen:
                continue
            seen.add(id(node))
            text = _joined_literal_text(node, docstrings)
            if text.strip():
                out.append((node, text))
    return out


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

def repair_imperative(text: str) -> Optional[str]:
    """The repair imperative in ``text``, if it carries one: a repair verb with an
    object. Returns the matched phrase so a finding can say what it matched."""
    padded = " " + _normalise(text) + " "
    for verb in _REPAIR_VERBS:
        for obj in _REPAIR_OBJECTS:
            phrase = "{} {} ".format(verb, obj)
            if " " + phrase in padded:
                return phrase.strip()
    return None


def sanctioned_destination(text: str) -> Optional[str]:
    low = _normalise(text)
    for dest in _SANCTIONED_DESTINATIONS:
        if dest in low:
            return dest
    return None


def module_level_string_constants(tree: ast.Module,
                                  docstrings: frozenset) -> Dict[str, str]:
    """``NAME -> the text it resolves to`` for every module-level string constant,
    with references to earlier module-level constants substituted in.

    Needed because a constant can be COMPOSED from others -- the declared repair
    clause plus the declared diagnosis -- so its own literal parts may be nothing
    but punctuation while its value carries a full instruction.
    """
    bound: Dict[str, str] = {}
    for _pass in range(2):  # two passes so a composition of a composition resolves
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None \
                    and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            else:
                continue
            if not _is_string_expression(value):
                continue
            if id(value) in docstrings:
                continue
            bound[target] = resolved_text(value, bound)
    return bound


def _module_constants(module_stem: str) -> Dict[str, str]:
    """One module's module-level string constants, resolved."""
    path = _EMITTED_LIB / (module_stem + ".py")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return {}
    return module_level_string_constants(tree, _docstring_nodes(tree))


def _registry_sibling_aliases() -> Dict[str, str]:
    """``local name -> sibling module stem`` for every sibling the registry imports,
    in either import form. This is how ``_core.BYPASS_UNREPAIRED_REPAIR`` is known to
    be a reference into ``writer_state_core`` rather than a bare attribute."""
    tree = ast.parse((_EMITTED_LIB / "state_actions.py").read_text(encoding="utf-8"))
    aliases: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if "external_write" in parts:
                    index = parts.index("external_write")
                    if index + 1 < len(parts):
                        aliases[alias.asname or parts[index + 1]] = parts[index + 1]
        elif isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if "external_write" in parts and parts[-1] == "external_write":
                for alias in node.names:
                    aliases[alias.asname or alias.name] = alias.name
    return aliases


def registry_bound_constants() -> Mapping[str, Mapping[str, str]]:
    """``module stem -> {constant name -> its resolved text}`` for every sibling
    string constant the REGISTRY'S OWN SOURCE references.

    This is the difference between a module the registry *imports* and a module the
    registry *binds a sentence out of*, and the first version of this gate conflated
    them: it permitted any declared text anywhere in an imported module, so a
    verbatim second copy of a declared instruction could be written into any of five
    modules and stay green. Membership is not binding. What is checked now is that
    the registry reads THIS text out of THIS module by name.

    Read off the registry's own AST, so laundering a copy means adding a visible
    reference to the registry itself.
    """
    global _BOUND_CONSTANTS_CACHE
    if _BOUND_CONSTANTS_CACHE is None:
        aliases = _registry_sibling_aliases()
        tree = ast.parse((_EMITTED_LIB / "state_actions.py").read_text(
            encoding="utf-8"))
        wanted: Dict[str, set] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            if isinstance(base, ast.Name) and base.id in aliases:
                wanted.setdefault(aliases[base.id], set()).add(node.attr)
        resolved: Dict[str, Dict[str, str]] = {}
        for stem, names in wanted.items():
            constants = _module_constants(stem)
            found = {n: constants[n] for n in names if n in constants}
            if found:
                resolved[stem] = found
        _BOUND_CONSTANTS_CACHE = resolved
    return _BOUND_CONSTANTS_CACHE


_BOUND_CONSTANTS_CACHE = None


def entrypoint_declaring_modules() -> Mapping[str, frozenset]:
    """``module stem -> the declared entrypoint relpath(s) it DECLARES as a
    module-level string constant``.

    The declaring module is allowed to spell its own path in prose -- its usage line
    is not a second author of anything. Joined on the DECLARED constant value, never
    on the module's filename: inferring "this is your entrypoint" from a name match
    is the shape this package has shipped five variants of.
    """
    global _DECLARING_CACHE
    if _DECLARING_CACHE is None:
        entrypoints = registry_entrypoint_relpaths()
        out: Dict[str, set] = {}
        for path in _scanned_files():
            stem = path.stem
            for _name, text in _module_constants(stem).items():
                for relpath in entrypoints:
                    if text.strip() == relpath:
                        out.setdefault(stem, set()).add(relpath)
        _DECLARING_CACHE = {k: frozenset(v) for k, v in out.items()}
    return _DECLARING_CACHE


_DECLARING_CACHE = None


def registry_renderer_names() -> frozenset:
    """The registry's own declared operator-facing renderers.

    READ FROM THE REGISTRY, not listed here. This set was hardcoded in two places
    that shared one literal, so two routes added to the registry were invisible to
    BOTH -- including the "computed a second way" test whose whole job is to catch
    the first one being narrowed. A surface rendering only a new route would have
    passed a gate that was not looking, which is the green-and-blind shape this
    family has shipped repeatedly. ``test_the_registrys_declared_renderer_set_is_
    complete`` is what keeps the registry's declaration honest in turn.
    """
    return frozenset(state_actions.OPERATOR_TEXT_RENDERERS)


def registry_rendering_surfaces() -> frozenset:
    """Every module in the scanned set that RENDERS from the registry -- it imports
    the registry and calls one of its renderers.

    Derived rather than listed because these are the modules whose operator-facing
    text must stay finding-free, and the population grows: this task added two to it.
    A hardcoded sample would keep proving the property for the two surfaces least
    likely to regress.
    """
    renderers = set(registry_renderer_names())
    found = set()
    for path in _scanned_files():
        if path.stem == "state_actions":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        source_names = {_referenced_name(n) for n in ast.walk(tree)
                        if isinstance(n, (ast.Name, ast.Attribute))}
        if "state_actions" not in {a for a in _sibling_imports(tree)}:
            continue
        if source_names & renderers:
            found.add(path.stem)
    return frozenset(found)


def _sibling_imports(tree: ast.Module) -> frozenset:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if "external_write" in parts:
                    index = parts.index("external_write")
                    if index + 1 < len(parts):
                        found.add(parts[index + 1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if "external_write" in parts:
                index = parts.index("external_write")
                if index + 1 < len(parts):
                    found.add(parts[index + 1])
                else:
                    found.update(a.name for a in node.names)
    return frozenset(found)


def entrypoint_constant_texts() -> Mapping[str, str]:
    """``constant name -> its resolved text``, for every module-level string constant
    in the scanned set that CARRIES a declared entrypoint relpath.

    This is the one-hop alias map the command rule substitutes through. Deliberately
    narrow -- only entrypoint-bearing names -- so the hop closes the measured evasion
    and changes nothing else. Keyed by NAME, so a name used for two different paths
    in two modules would collide; there is exactly one declaring module per path
    today, asserted by test.
    """
    global _ENTRYPOINT_CONST_CACHE
    if _ENTRYPOINT_CONST_CACHE is None:
        entrypoints = registry_entrypoint_relpaths()
        out: Dict[str, str] = {}
        for path in _scanned_files():
            for name, text in _module_constants(path.stem).items():
                if any(relpath in text for relpath in entrypoints):
                    out[name] = text
        _ENTRYPOINT_CONST_CACHE = out
    return _ENTRYPOINT_CONST_CACHE


_ENTRYPOINT_CONST_CACHE = None


def repair_bearing_constant_names() -> frozenset:
    """Every module-level constant NAME, anywhere in the scanned set, whose value
    carries a repair imperative onto the sanctioned write path.

    These are the names a module may DECLARE -- some of them must be declared
    outside the registry, because two consumers need the same clause and only one of
    them can import the registry -- but may not RENDER. Derived from the tree, never
    listed, so a second declaration is policed the moment it is written.
    """
    global _REPAIR_BEARING_CACHE
    if _REPAIR_BEARING_CACHE is None:
        found = set()
        for path in _scanned_files():
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            docstrings = _docstring_nodes(tree)
            for name, text in module_level_string_constants(tree, docstrings).items():
                if repair_imperative(text) and sanctioned_destination(text):
                    found.add(name)
        _REPAIR_BEARING_CACHE = frozenset(found)
    return _REPAIR_BEARING_CACHE


_REPAIR_BEARING_CACHE = None


def _declaration_reference_ids(tree: ast.Module, bearing: frozenset) -> frozenset:
    """Node ids of every name reference that sits inside a MODULE-LEVEL assignment
    whose own target is a repair-bearing constant.

    Composing one declared clause into another declared constant is still
    declaration -- it is how the diagnosis and the repair become the whole sentence.
    Using the clause anywhere else is rendering.
    """
    ids = set()
    for node in tree.body:
        targets: List[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id in bearing for t in targets):
            continue
        for sub in ast.walk(node):
            ids.add(id(sub))
    return frozenset(ids)


def _is_bare_command(text: str, relpath: str) -> bool:
    """A literal that IS the entrypoint path, or the bare command prefix for it, is
    a declaration or a manifest entry -- not a sentence handing the operator a
    command. Whitespace-tolerant and nothing else: any surrounding prose makes it
    an instruction."""
    stripped = text.strip()
    return stripped in (relpath, "python3 " + relpath)


def _state_selected_value_nodes(tree: ast.Module, docstrings: frozenset):
    """``(key node, value expression, state name)`` for every authored text SELECTED
    BY a registry-covered state.

    Two shapes: a mapping entry whose key is such a state, and the body of an
    equality/membership branch on one. Inequality is excluded on purpose -- a
    ``!=`` guard reports what went wrong rather than answering "what do I say about
    this state"."""
    values = distinctive_state_values()
    members = _writer_state_member_names()
    trial_consts = _trial_state_constant_names()

    def resolves(node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Attribute) and node.attr in members:
            base = node.value
            name = base.attr if isinstance(base, ast.Attribute) \
                else getattr(base, "id", "")
            if name.endswith("WriterState"):
                return node.attr
        if isinstance(node, ast.Attribute) and node.attr in trial_consts:
            return node.attr
        if isinstance(node, ast.Name) and node.id in trial_consts:
            return node.id
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value in values:
            return node.value
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if key is None:
                    continue
                state = resolves(key)
                if state and _is_string_expression(value):
                    yield key, value, state
                elif state and isinstance(value, (ast.Tuple, ast.List)):
                    for element in value.elts:
                        if _is_string_expression(element):
                            yield key, element, state
        elif isinstance(node, ast.If):
            states = []
            for test in ast.walk(node.test):
                if not isinstance(test, ast.Compare):
                    continue
                if not any(isinstance(op, (ast.Eq, ast.In)) for op in test.ops):
                    continue
                for operand in [test.left] + list(test.comparators):
                    state = resolves(operand)
                    if state:
                        states.append(state)
            if not states:
                continue
            # The branch BODY only -- never the `else`, which is by definition
            # about some other state.
            for value, _text in authored_texts_in(list(node.body), docstrings):
                yield node.test, value, states[0]


def scan_source(source: str, relpath: str) -> List[Finding]:
    """Every banned shape in ``source``. Never raises: an unparseable production
    module is itself reported, because a module this gate cannot read is a module
    it cannot vouch for."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        line = getattr(exc, "lineno", 0) or 0
        return [Finding(relpath, line, line, "authored_repair_directive", "<module>",
                        "unreadable as Python ({})".format(exc.msg))]

    module_stem = relpath.rsplit("/", 1)[-1][:-3]
    declared = registry_declared_texts()
    entrypoints = registry_entrypoint_relpaths()
    spans = _symbol_spans(tree)
    docstrings = _docstring_nodes(tree)
    local_constants = module_level_string_constants(tree, docstrings)
    # The one-hop alias map for the command rule: this module's own module-level
    # string constants, plus every entrypoint-bearing constant name in the scanned
    # set (a path is usually declared in the module that owns the entrypoint and
    # referenced from elsewhere).
    command_constants = dict(entrypoint_constant_texts())
    command_constants.update(local_constants)
    declares_own = entrypoint_declaring_modules().get(module_stem, frozenset())
    bound_here = registry_bound_constants().get(module_stem, {})
    found: List[Finding] = []

    def add(node: ast.AST, kind: str, detail: str) -> None:
        found.append(Finding(
            relpath, node.lineno,
            getattr(node, "end_lineno", None) or node.lineno,
            kind, _symbol_at(spans, node.lineno), detail))

    def registry_declares(text: str) -> bool:
        """The registry declares this text AND reads it out of THIS module by name --
        so the registry is provably the binder, not a second author who happens to sit
        in a module the registry imports.

        Membership in the imported set is deliberately NOT sufficient: it was, in the
        first version of this gate, and a verbatim second copy of any declared
        instruction template then passed in five different modules.
        """
        if module_stem == "state_actions":
            return True          # the registry is the author, by construction
        low = _normalise(text)
        if not any(low in whole for whole in declared):
            return False
        return any(low in _normalise(value) for value in bound_here.values())

    def copied_declared_text(text: str) -> Optional[str]:
        """A registry-declared sentence this text CARRIES, if any.

        The mirror image of `registry_declares`, and it exists because the two
        containment directions catch different things. A literal that is PART of a
        declared sentence may be the single clause the registry composes from; a
        literal that CONTAINS a whole declared sentence is a copy of it. Without this,
        the template form of an action whose instruction carries no repair verb and no
        spelled path -- the accept-the-risk and recover-a-trial ones -- was invisible
        to every other signature, which is precisely the form a second author copies.
        """
        low = _normalise(text)
        for whole in declared:
            if len(whole) >= _COPY_MIN_CHARS and whole in low:
                return whole
        return None

    for node, text in authored_texts_in([tree], docstrings):
        verb = repair_imperative(text)
        dest = sanctioned_destination(text)
        if verb and dest and not registry_declares(text):
            add(node, "authored_repair_directive",
                "directs a repair ({!r}) onto the {!r} write path in words the "
                "registry does not declare".format(verb, dest))
        copied = copied_declared_text(text)
        if copied and not registry_declares(text):
            add(node, "copied_registry_text",
                "carries a sentence the registry declares, verbatim, without the "
                "registry binding it from here: {!r}".format(
                    copied[:60] + ("..." if len(copied) > 60 else "")))
        # The command rule reads the ONE-HOP resolved text, because keying on the
        # path being spelled meant that naming it evaded the rule -- and the standing
        # "single source, never re-spelled" rule pushes an author toward exactly that
        # indirection.
        command_text = resolved_text(node, command_constants) or text
        for entrypoint in entrypoints:
            if entrypoint in declares_own:
                continue     # its own usage line; the path is declared here
            if entrypoint in command_text \
                    and not _is_bare_command(command_text, entrypoint) \
                    and not registry_declares(command_text) \
                    and not registry_declares(text):
                add(node, "authored_registry_command",
                    "hands the operator a command for {!r} in prose".format(
                        entrypoint))
                break

    # authored_repair_render -- a module other than the registry FORMATTING a
    # declared repair clause into an operator-facing sentence. Declaring the clause
    # outside the registry is sometimes forced (two consumers, only one of which can
    # import the registry); rendering it is not, and rendering it is what made the
    # deepest layer's entry description state-blind: it had the sentence to hand and
    # no way to know which state it was describing.
    if module_stem != "state_actions":
        bearing = set(repair_bearing_constant_names())
        for name, text in module_level_string_constants(tree, docstrings).items():
            if repair_imperative(text) and sanctioned_destination(text):
                bearing.add(name)
        declaration_refs = _declaration_reference_ids(tree, frozenset(bearing))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            else:
                continue
            if name in bearing and id(node) not in declaration_refs:
                add(node, "authored_repair_render",
                    "renders the declared repair clause {!r} into a sentence of its "
                    "own; the registry is the one renderer".format(name))

    for key, value, state in _state_selected_value_nodes(tree, docstrings):
        text = _joined_literal_text(value, docstrings)
        if not _is_operator_prose(text):
            continue
        if registry_declares(text):
            continue
        add(key, "state_selected_authored_text",
            "answers what to say about state {!r} without the registry".format(
                state))

    return sorted(set(found))


# ---------------------------------------------------------------------------
# Per-line exemptions
# ---------------------------------------------------------------------------

def marker_sites(source: str) -> List[Tuple[int, str]]:
    sites = []
    for number, line in enumerate(source.splitlines(), start=1):
        head, sep, tail = line.partition(_EXEMPTION_MARKER)
        if not sep:
            continue
        if "#" not in head:
            continue  # the marker only counts inside a comment
        sites.append((number, tail.strip()))
    return sites


def exempting_marker(finding: Finding, source: str,
                     marked: Dict[int, str]) -> Optional[int]:
    for number in range(finding.lineno, finding.end_lineno + 1):
        if number in marked:
            return number
    lines = source.splitlines()
    index = finding.lineno - 2
    while index >= 0 and lines[index].strip().startswith("#"):
        if index + 1 in marked:
            return index + 1
        index -= 1
    return None


# ===========================================================================
# THE GATE
# ===========================================================================

class RemediationMonopolyGateTests(unittest.TestCase):

    def _sources(self):
        for path in _scanned_files():
            yield (path.relative_to(_WIZARD).as_posix(),
                   path.read_text(encoding="utf-8", errors="replace"))

    def test_no_hand_authored_remediation_instruction_in_the_emitted_surface(self):
        violations = []
        for relpath, source in self._sources():
            marked = {n: why for n, why in marker_sites(source)}
            for finding in scan_source(source, relpath):
                if exempting_marker(finding, source, marked) is None:
                    violations.append(finding.render())
        self.assertEqual(
            violations, [],
            "an operator-facing remediation instruction must be rendered from the "
            "state->action registry, never written again at the surface:\n  "
            + "\n  ".join(violations))


class TheScannedSetComesFromTheProducerTests(unittest.TestCase):
    """A fail-closed check whose input set is wrong can refuse every build, and a
    check quantified over the wrong population is the trap this package has
    corrected repeatedly. So the set is derived, non-empty, and every member is
    positively readable."""

    def test_the_set_is_the_emitters_own_declared_enrolment_list(self):
        """Bound to the PUBLIC producer, not only to the private tuple: the
        emit-set function must be reading the same list."""
        source = (_WIZARD / "scripts" / "lib" / "agent_emitter.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        target = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == "external_write_lib_emit_set":
                target = node
        self.assertIsNotNone(
            target, "the emitter no longer declares an external-write emit set")
        names = {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
        self.assertIn(
            "_EXTERNAL_WRITE_LIB_FILES", names,
            "this gate's scanned set is derived from the enrolment tuple; if the "
            "public emit-set function no longer reads that tuple, the derivation "
            "is measuring the wrong population")

    def test_the_set_is_non_empty_and_every_member_is_readable(self):
        files = _scanned_files()
        self.assertGreater(len(files), 1)
        self.assertEqual(len(files), len(_declared_emitted_basenames()))

    def test_an_enrolled_but_absent_module_is_reported_not_skipped(self):
        real = agent_emitter._EXTERNAL_WRITE_LIB_FILES
        agent_emitter._EXTERNAL_WRITE_LIB_FILES = real + ("no_such_module.py",)
        self.addCleanup(setattr, agent_emitter, "_EXTERNAL_WRITE_LIB_FILES", real)
        with self.assertRaises(ScannedSetError) as raised:
            _scanned_files()
        self.assertIn("absent from the source tree", str(raised.exception))

    def test_an_empty_producer_set_refuses_rather_than_passing_vacuously(self):
        real = agent_emitter._EXTERNAL_WRITE_LIB_FILES
        agent_emitter._EXTERNAL_WRITE_LIB_FILES = ()
        self.addCleanup(setattr, agent_emitter, "_EXTERNAL_WRITE_LIB_FILES", real)
        with self.assertRaises(ScannedSetError):
            _scanned_files()

    def test_the_gate_reads_nothing_but_this_repositorys_own_sources(self):
        """No project root, no environment, no argv -- so the verdict is the same
        on every build and cannot be turned red by anything an operator has on
        disk. A gate that fires on a fresh build refuses every deployment, and
        that has shipped here before."""
        source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(node.attr, "environ")
                self.assertNotEqual(node.attr, "argv")
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                self.assertNotIn(name, ("getenv", "expanduser", "home", "cwd"))


class TheGateDetectsAPlantedViolationTests(unittest.TestCase):
    """A gate that cannot fail is not a gate. One planted instance per banned
    shape, plus the sanctioned and prose forms, which must stay clean."""

    def _kinds(self, source, relpath="planted.py"):
        return [f.kind for f in scan_source(source, relpath)]

    def test_a_planted_repair_directive_is_flagged(self):
        source = ('MESSAGE = "Rebuild the flagged file through the sanctioned '
                  'write path, then run this check again."\n')
        self.assertIn("authored_repair_directive", self._kinds(source))

    def test_a_planted_repair_directive_split_across_literals_is_flagged(self):
        """Splitting the sentence is not a way out: the unit is the whole
        expression, and every literal part in it is joined."""
        source = ('MESSAGE = ("rebuild it so it routes through the "\n'
                  '           "sanctioned bulk path")\n')
        self.assertIn("authored_repair_directive", self._kinds(source))
        concatenated = ('MESSAGE = "rebuild it so it routes through the " + '
                        '"sanctioned bulk path"\n')
        self.assertIn("authored_repair_directive", self._kinds(concatenated))

    def test_a_planted_command_instruction_is_flagged(self):
        entrypoint = registry_entrypoint_relpaths()[0]
        source = ('MESSAGE = "Put it right by running this from your project\'s '
                  'top folder: python3 {}"\n'.format(entrypoint))
        self.assertIn("authored_registry_command", self._kinds(source))

    def test_a_planted_state_selected_text_is_flagged(self):
        source = ("REASONS = {\n"
                  "    WriterState.NEEDS_PERSON: 'talk to somebody about it',\n"
                  "}\n")
        self.assertIn("state_selected_authored_text", self._kinds(source))

    def test_a_planted_state_selected_branch_is_flagged(self):
        source = ("def describe(state):\n"
                  "    if state == WriterState.BLOCKING_LIVE_ENABLE:\n"
                  "        return 'here is what you should do about it instead'\n"
                  "    return ''\n")
        self.assertIn("state_selected_authored_text", self._kinds(source))

    def test_a_bare_state_value_string_key_is_flagged_too(self):
        """Keyed on the state's VALUE rather than the constant -- the same defect
        spelled without naming the vocabulary."""
        source = ('REASONS = {"needs_person": "go and ask somebody about it"}\n')
        self.assertIn("state_selected_authored_text", self._kinds(source))

    def test_a_bare_english_word_that_HAPPENS_to_be_a_state_value_is_not_joined_on(self):
        """``resolved`` and ``planned`` are covered state values AND ordinary words
        other vocabularies here use for other things. A literal that merely equals
        one is not evidence it IS that state, and this gate refuses to infer
        identity from the coincidence. Measured on the real shape that exposed it:
        an ownership lookup whose OUTCOME is the string ``resolved``."""
        collision = ('def go(derived, out, rel):\n'
                     '    if derived.get("ownership_status") == "resolved":\n'
                     '        out[rel] = derived["owning_capability_id"]\n')
        self.assertEqual(scan_source(collision, "clean.py"), [])
        for word in ("resolved", "planned"):
            with self.subTest(word=word):
                self.assertNotIn(word, distinctive_state_values())
                self.assertIn(word, registry_covered_state_values())
        # The NAMED-CONSTANT form of the very same states is still matched: naming
        # the vocabulary is the declaration, so there is nothing to infer.
        named = ("REASONS = {WriterState.RESOLVED: "
                 "'this one is finished and needs nothing from you now'}\n")
        self.assertIn("state_selected_authored_text", self._kinds(named))

    def test_an_identifier_sitting_in_a_state_keyed_structure_is_not_prose(self):
        """The state-selected rule is wording-independent, so without a
        prose/identifier discriminator it would flag every field name a
        state-keyed branch reads."""
        source = ("def go(entry, out):\n"
                  "    if entry['state'] == WriterState.NEEDS_PERSON:\n"
                  "        out['writer_relpath'] = entry['writer_relpath']\n")
        self.assertEqual(scan_source(source, "clean.py"), [])

    def test_a_planted_repair_RENDER_is_flagged(self):
        """The shape that made the deepest layer's entry description state-blind: it
        DECLARED the sentence (legitimately -- two consumers need it and only one can
        import the registry) and then formatted it into an operator-facing answer
        itself, with no way to know which state it was describing."""
        source = ('TEMPLATE = "an external-write bypass is unrepaired: `{relpath}` '
                  '-- rebuild it so it routes through the sanctioned bulk path"\n'
                  "\n"
                  "\n"
                  "def describe(entry):\n"
                  "    return TEMPLATE.format(relpath=entry['writer_relpath'])\n")
        kinds = self._kinds(source)
        self.assertIn("authored_repair_render", kinds)

    def test_composing_one_declared_clause_into_another_is_declaration(self):
        """Declaration is not rendering. The diagnosis and the repair become the whole
        sentence by composition at module scope, and that must stay clean or the rule
        bans the single-declaration pattern it depends on."""
        source = ('DIAGNOSIS = "an external-write bypass is unrepaired: `{relpath}`"\n'
                  'REPAIR = "rebuild it so it routes through the sanctioned bulk path"\n'
                  'TEMPLATE = DIAGNOSIS + " -- " + REPAIR\n')
        self.assertEqual(
            [f.kind for f in scan_source(
                source, "agents/lib/external_write/writer_state_core.py")],
            [], "composing declared clauses at module scope was treated as rendering")

    def test_formatting_the_DIAGNOSIS_alone_is_not_rendering_a_repair(self):
        """The corrected shape: a module that cannot know the state may still say what
        was FOUND. Only the repair is the registry's."""
        source = ('DIAGNOSIS = "an external-write bypass is unrepaired: `{relpath}`"\n'
                  'REPAIR = "rebuild it so it routes through the sanctioned bulk path"\n'
                  'TEMPLATE = DIAGNOSIS + " -- " + REPAIR\n'
                  "\n"
                  "\n"
                  "def describe(entry):\n"
                  "    return DIAGNOSIS.format(relpath=entry['writer_relpath'])\n")
        self.assertEqual(
            [f.kind for f in scan_source(
                source, "agents/lib/external_write/writer_state_core.py")], [])

    def test_the_registry_may_render_what_it_declares(self):
        """The registry is the renderer, so this rule does not apply to it -- and that
        is decided by which module it is, not by a marker."""
        source = ("INSTRUCTION = ('an external-write bypass is unrepaired: "
                  "`{subject}` -- rebuild it so it routes through the sanctioned "
                  "bulk path')\n"
                  "\n"
                  "\n"
                  "def render(subject):\n"
                  "    return INSTRUCTION.format(subject=subject)\n")
        self.assertEqual(
            [f.kind for f in scan_source(
                source, "agents/lib/external_write/state_actions.py")], [])
        self.assertIn(
            "authored_repair_render",
            [f.kind for f in scan_source(
                source, "agents/lib/external_write/lifecycle_state.py")],
            "any other module rendering the same clause must still be flagged")

    def test_prose_is_not_code(self):
        for prose in (
            '"""rebuild it so it routes through the sanctioned bulk path."""\n',
            "# never author 'rebuild it ... sanctioned bulk path' at a surface\n",
            'def f():\n    """Rebuild the file through the sanctioned write path."""\n',
        ):
            with self.subTest(prose=prose.strip()[:40]):
                self.assertEqual(scan_source(prose, "clean.py"), [])

    def test_a_description_of_what_happened_is_not_an_instruction(self):
        """The boundary, asserted rather than only described: a passive or
        third-person statement about the sanctioned write path is a diagnosis."""
        for clean in (
            'M = "this project has a file that writes by a path that bypasses the '
            'sanctioned, safety-gated write surface, so nothing here is done until '
            'that is rebuilt."\n',
            'M = "every check passed: it routes through the safe write path."\n',
            'M = "an earlier notice said this had been switched off through the '
            'sanctioned write path; that was not true when it was written."\n',
        ):
            with self.subTest(clean=clean[:48]):
                self.assertEqual(scan_source(clean, "clean.py"), [])

    def test_a_bare_command_prefix_is_not_an_instruction(self):
        entrypoint = registry_entrypoint_relpaths()[0]
        for bare in ('REL = "{}"\n'.format(entrypoint),
                     'PREFIX = "python3 {}"\n'.format(entrypoint)):
            with self.subTest(bare=bare.strip()):
                self.assertEqual(scan_source(bare, "clean.py"), [])

    def test_an_inequality_guard_is_not_a_state_selected_answer(self):
        source = ("def go(state):\n"
                  "    if state != WriterState.NEEDS_PERSON:\n"
                  "        return 'the durable record is not where it should be'\n")
        self.assertEqual(scan_source(source, "clean.py"), [])

    def test_the_registrys_own_declared_text_is_clean_where_the_registry_binds_it(self):
        """The gate must not ban the sentence it exists to require. The registry's
        declared rebuild instruction, planted in a module the registry imports,
        must stay clean -- and the SAME text in a module the registry does not
        import must not."""
        declared = writer_state_core.BYPASS_UNREPAIRED_TEMPLATE
        source = "T = {!r}\n".format(declared)
        self.assertEqual(
            scan_source(source, "agents/lib/external_write/writer_state_core.py"),
            [], "the registry's own declared text was flagged at its single home")
        elsewhere = scan_source(
            source, "agents/lib/external_write/lifecycle_state.py")
        self.assertEqual([f.kind for f in elsewhere],
                         ["authored_repair_directive"],
                         "a verbatim copy in a module the registry does not import "
                         "must still be a violation")

    def test_a_verbatim_TEMPLATE_COPY_is_flagged_in_every_module_the_registry_does_not_bind_it_from(self):
        """Being a module the registry IMPORTS is not being the module the registry
        binds the sentence FROM, and the first version of this gate conflated them:
        a verbatim copy of any declared instruction template passed in all five
        imported modules. Measured per module x per action, so the property is pinned
        for every bound module rather than demonstrated on one pair.

        The one legitimate case is the single clause the registry genuinely composes
        its own instruction from -- that clause, in the module the registry reads it
        out of. Everything else, including the FULL template of the very action that
        clause belongs to, is a second copy."""
        bound = sorted(registry_bound_modules() - {"state_actions"})
        self.assertGreaterEqual(len(bound), 4, bound)
        for action in state_actions.ACTIONS:
            for module in bound:
                with self.subTest(action=action.action_id, module=module):
                    source = "COPY = {!r}\n".format(action.instruction)
                    kinds = self._kinds(
                        source, "agents/lib/external_write/{}.py".format(module))
                    self.assertNotEqual(
                        kinds, [],
                        "a verbatim copy of a declared instruction template is a "
                        "second, independently-maintained author of the same "
                        "guidance, wherever it sits")

    def test_the_ONE_clause_the_registry_binds_is_still_clean_at_its_own_home(self):
        """The other direction, and the reason the check is containment rather than
        equality: the clause the registry reads out of the leaf layer must stay
        clean there, or the gate bans the single-declaration pattern it depends on --
        and it must NOT be clean in a module the registry does not read it from."""
        source = "CLAUSE = {!r}\n".format(writer_state_core.BYPASS_UNREPAIRED_REPAIR)
        self.assertEqual(
            scan_source(source,
                        "agents/lib/external_write/writer_state_core.py"), [])
        for elsewhere in ("scan", "trial_journal", "trial_recovery",
                          "writer_acknowledgement", "lifecycle_state"):
            with self.subTest(module=elsewhere):
                self.assertNotEqual(
                    self._kinds(source,
                                "agents/lib/external_write/{}.py".format(elsewhere)),
                    [], "the registry does not read this clause out of that module")

    def test_a_declared_command_reached_through_a_CONSTANT_is_still_a_command(self):
        """The rule keyed on the path being SPELLED, so naming it evaded -- and the
        standing "single source, never re-spelled" rule actively pushes an author
        toward exactly that indirection. One alias hop over module-level string
        constants closes the three forms an author would actually reach for."""
        relpath = registry_entrypoint_relpaths()[0]
        forms = {
            "spelled inline (the control)":
                'MSG = "Put it right by running this: python3 {}"\n'.format(relpath),
            "pulled from a module-level constant":
                'REL = "{}"\nMSG = "Put it right by running this: python3 " + REL\n'.format(relpath),
            "interpolated from a constant in an f-string":
                'REL = "{}"\nMSG = f"Put it right by running this: python3 {{REL}}"\n'.format(relpath),
            "interpolated from a constant via .format":
                'REL = "{}"\nMSG = "Put it right by running this: python3 {{}}".format(REL)\n'.format(relpath),
        }
        for label, source in forms.items():
            with self.subTest(form=label):
                self.assertIn(
                    "authored_registry_command",
                    self._kinds(source,
                                "agents/lib/external_write/lifecycle_state.py"),
                    "naming the entrypoint is not a way around this rule")

    def test_the_module_that_DECLARES_an_entrypoint_may_spell_its_own_usage(self):
        """The over-firing direction of the alias hop, and it is not hypothetical:
        the acknowledgement entrypoint's own module renders a usage line that
        interpolates its declared path. That module is where the path is declared,
        so it is not a second author of anything -- joined on the DECLARED constant,
        never on the filename."""
        for module, relpaths in entrypoint_declaring_modules().items():
            for relpath in sorted(relpaths):
                with self.subTest(module=module, relpath=relpath):
                    source = ('REL = "{}"\n'
                              'USAGE = f"Usage: python3 {{REL}} --flag <value>"\n'
                              ).format(relpath)
                    self.assertEqual(
                        [f.kind for f in scan_source(
                            source,
                            "agents/lib/external_write/{}.py".format(module))],
                        [], "the declaring module's own usage line was flagged")

    def test_resolved_text_preserves_SOURCE_ORDER(self):
        """Order is the whole basis of the containment checks: a constant composed as
        ``DIAGNOSIS + " -- " + REPAIR`` has almost no literal content of its own, so a
        resolution that returned its parts in any other order would make a containment
        test against it meaningless -- it would match texts that are not in it and
        miss texts that are. Asserted directly, for each form, because a mutation that
        scrambled the f-string order left every other test in this file green."""
        constants = {"REL": "path/to/thing.py", "A": "alpha", "B": "beta"}
        self.assertEqual(
            resolved_text(ast.parse('f"go {REL} now"').body[0].value, constants),
            "go path/to/thing.py now")
        self.assertEqual(
            resolved_text(ast.parse('A + " -- " + B').body[0].value, constants),
            "alpha -- beta")
        self.assertEqual(
            resolved_text(ast.parse('"head {} tail".format(REL)').body[0].value,
                          constants),
            "head {} tail path/to/thing.py")

    def test_every_declared_entrypoint_has_exactly_one_declaring_module(self):
        """The carve-out above is only safe if the declaring module is unambiguous:
        two modules declaring the same path would each be excused for the other's
        prose."""
        owners: Dict[str, List[str]] = {}
        for module, relpaths in entrypoint_declaring_modules().items():
            for relpath in relpaths:
                owners.setdefault(relpath, []).append(module)
        for relpath in registry_entrypoint_relpaths():
            with self.subTest(relpath=relpath):
                self.assertEqual(
                    len(owners.get(relpath, [])), 1,
                    "a declared entrypoint must have exactly one declaring module; "
                    "got {}".format(owners.get(relpath)))

    def test_the_enclosing_symbol_distinguishes_two_findings_in_one_file(self):
        source = ("class Spec:\n"
                  "    @property\n"
                  "    def advice(self):\n"
                  "        return 'rebuild it onto the sanctioned bulk path'\n"
                  "\n"
                  "    @property\n"
                  "    def rogue(self):\n"
                  "        return 'rebuild it onto the sanctioned bulk path'\n"
                  "\n"
                  "\n"
                  "TOP = 'rebuild it onto the sanctioned bulk path'\n")
        self.assertEqual(
            [f.symbol for f in scan_source(source, "p.py")],
            ["Spec.advice", "Spec.rogue", "<module>"])

    def test_an_unparseable_module_is_reported_not_skipped(self):
        self.assertEqual([f.detail[:11] for f in scan_source("def (:\n", "p.py")],
                         ["unreadable "])


class TheSignatureIsBoundToTheRegistryTests(unittest.TestCase):
    """The vocabularies above are short lists, and a short list is exactly how a
    gate goes green and blind. These bind them to the producer: every instruction
    the registry declares must be one this gate's own signatures RECOGNISE, so an
    action added or reworded in a shape the gate cannot see fails here rather than
    passing silently."""

    def test_the_signature_recognises_every_instruction_the_registry_DECLARES(self):
        entrypoints = registry_entrypoint_relpaths()
        for action in state_actions.ACTIONS:
            with self.subTest(action=action.action_id):
                rendered = state_actions.render_action(action, "the-subject")
                by_repair = bool(repair_imperative(rendered)
                                 and sanctioned_destination(rendered))
                by_command = any(
                    e in rendered and not _is_bare_command(rendered, e)
                    for e in entrypoints)
                self.assertTrue(
                    by_repair or by_command,
                    "this action's operator-facing instruction is in a shape none "
                    "of this gate's signatures recognises, so a hand-authored "
                    "copy of it would pass the build. Widen the signature (and say "
                    "what it now polices) or keep the instruction in a shape it "
                    "sees")

    def test_the_entrypoints_are_derived_from_the_actions_not_listed(self):
        derived = registry_entrypoint_relpaths()
        self.assertEqual(len(derived), len(state_actions.ACTIONS),
                         "one declared entrypoint per action; if that stops being "
                         "true the derivation needs re-checking, not a list")
        for relpath in derived:
            with self.subTest(relpath=relpath):
                self.assertTrue((_WIZARD / relpath).is_file(),
                                "a declared entrypoint that does not exist")

    def test_every_covered_state_comes_from_a_declaring_module(self):
        covered = registry_covered_state_values()
        self.assertTrue(covered)
        self.assertLessEqual(
            {s.split(":", 1)[1] for s in state_actions.DECLARED_STATE_KEYS},
            set(covered),
            "the registry declares a state this gate's own vocabulary does not "
            "cover, so a text keyed on it would not be policed")

    def test_the_registry_module_is_in_the_bound_set(self):
        self.assertIn("state_actions", registry_bound_modules())
        self.assertIn("writer_state_core", registry_bound_modules())

    def test_every_declared_sentence_is_long_enough_to_be_seen_as_a_COPY(self):
        """`_COPY_MIN_CHARS` is a disclosed bound, so it has to be checked against the
        producer rather than assumed comfortable: a declared sentence shorter than it
        could be pasted anywhere and the copy rule would not see it."""
        shortest = min(len(t) for t in registry_declared_texts())
        self.assertGreater(
            shortest, _COPY_MIN_CHARS,
            "the registry now declares a sentence short enough to slip under the "
            "copy rule's floor; lower the floor or say which sentence is unseen")

    def test_the_registry_binds_the_leaf_layers_clause_BY_NAME(self):
        """The permit rule's whole basis. If the registry stopped reading this
        constant, the clause would no longer be permitted at its own home -- which is
        the correct consequence, and the reason the check is a derivation rather than
        a list of blessed modules."""
        bound = registry_bound_constants()
        self.assertIn("writer_state_core", bound)
        self.assertIn("BYPASS_UNREPAIRED_TEMPLATE", bound["writer_state_core"])
        self.assertIn(writer_state_core.BYPASS_UNREPAIRED_REPAIR,
                      bound["writer_state_core"]["BYPASS_UNREPAIRED_TEMPLATE"])


class ASurfaceThatRendersFromTheRegistryPassesTests(unittest.TestCase):
    """The over-firing direction, and the reason it is a test rather than a hope: a
    fail-closed check that refuses a legitimate surface refuses every build."""

    def test_a_registry_rendering_surface_has_no_findings_at_all(self):
        """The sample is DERIVED, not listed: every module in the scanned set that
        actually calls the registry's renderer. A hardcoded pair would silently stop
        covering the third and fourth surfaces that started rendering from the
        registry in this very task, and those are the population most likely to
        regress. Asserted non-empty and asserted to have grown past the original two,
        so the derivation cannot quietly resolve to nothing."""
        surfaces = registry_rendering_surfaces()
        self.assertGreaterEqual(len(surfaces), 2, sorted(surfaces))
        for name in ("capability_health", "operator_acceptance"):
            self.assertIn(name, surfaces,
                          "a surface known to render from the registry is not "
                          "being detected as one, so this sample proves nothing")
        for stem in sorted(surfaces):
            with self.subTest(module=stem):
                path = _EMITTED_LIB / (stem + ".py")
                findings = scan_source(
                    path.read_text(encoding="utf-8"),
                    "{}/{}.py".format(_EMITTED_LIB_REL, stem))
                self.assertEqual([f.render() for f in findings], [])

    def test_the_derived_sample_is_the_same_set_computed_a_SECOND_way(self):
        """The derivation's own falsifiability. The test above CONSUMES it, so a
        stubbed derivation would merely shrink the sample and stay green; this asks the
        same question independently and compares. It is also what would catch the
        sample being narrowed back to a hardcoded pair -- the population grew by two in
        the very task that derived it."""
        renderers = set(registry_renderer_names())
        independently = set()
        for path in _scanned_files():
            if path.stem == "state_actions":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            imports_registry = any(
                isinstance(n, ast.Import)
                and any(a.name.endswith(".state_actions") for a in n.names)
                for n in ast.walk(tree)) or any(
                isinstance(n, ast.ImportFrom)
                and (n.module or "").endswith("external_write")
                and any(a.name == "state_actions" for a in n.names)
                for n in ast.walk(tree))
            calls_renderer = any(
                isinstance(n, ast.Attribute) and n.attr in renderers
                for n in ast.walk(tree))
            if imports_registry and calls_renderer:
                independently.add(path.stem)
        self.assertEqual(registry_rendering_surfaces(), frozenset(independently),
                         "the derivation and the same question asked here disagree")
        self.assertGreater(
            len(independently), 2,
            "two modules rendered from the registry before this gate existed and two "
            "more do now; a sample that has stopped growing with the population is no "
            "longer proving the over-firing property for the modules at risk")

    def test_the_registry_itself_has_no_findings(self):
        path = _EMITTED_LIB / "state_actions.py"
        findings = scan_source(path.read_text(encoding="utf-8"),
                              "{}/state_actions.py".format(_EMITTED_LIB_REL))
        self.assertEqual([f.render() for f in findings], [],
                         "the gate flagged the one module that is supposed to "
                         "author these sentences")


class TheExemptionSurfaceIsPinnedTests(unittest.TestCase):

    #: ``file::kind::enclosing symbol`` -> how many exempted findings carry that
    #: identity. Structural, not positional: an unrelated edit above a marker does
    #: not move it, and a substituted construction in another symbol does.
    EXPECTED = {
        # The accepted-risk command's refusal, keyed on the state it found. It
        # cannot render from the registry: the registry imports this layer's own
        # facade, so the reverse edge is a cycle, and the registry also reaches the
        # trial modules whose pre-existing cycle would then sit inside the
        # writer-state cluster's proved acyclicity closure. Two entries -- the
        # rebuildable state and the non-live one. The one clause shared with the
        # registry's instruction is BOUND from the single declaration, not
        # re-spelled, so nothing here can drift away from it.
        "agents/lib/external_write/writer_commands.py"
        "::state_selected_authored_text::<module>": 2,
        # The same site, seen by the other rule: it also RENDERS the declared repair
        # clause into its own sentence. Pinned separately and deliberately, so the
        # exemption records the whole truth about this site rather than the half of it
        # one rule happens to see.
        "agents/lib/external_write/writer_commands.py"
        "::authored_repair_render::<module>": 1,
    }

    def test_the_exemption_surface_is_pinned(self):
        actual: Dict[str, int] = {}
        unjustified: List[str] = []
        dead: List[str] = []
        for path in _scanned_files():
            source = path.read_text(encoding="utf-8", errors="replace")
            sites = marker_sites(source)
            if not sites:
                continue
            marked = {n: why for n, why in sites}
            relpath = path.relative_to(_WIZARD).as_posix()
            working = set()
            for finding in scan_source(source, relpath):
                marker = exempting_marker(finding, source, marked)
                if marker is None:
                    continue
                actual[finding.identity] = actual.get(finding.identity, 0) + 1
                working.add(marker)
            for number, why in sites:
                if len(why) < 20:
                    unjustified.append("{}:{}".format(relpath, number))
                if number not in working:
                    dead.append("{}:{}".format(relpath, number))
        self.assertEqual(
            actual, self.EXPECTED,
            "the exempt surface changed. An exemption is for a text that CANNOT "
            "reach the registry for a structural reason -- if a new one is here to "
            "shorten the violation list, render from the registry instead")
        self.assertEqual(unjustified, [],
                         "an exemption marker with no real justification: "
                         + ", ".join(unjustified))
        self.assertEqual(dead, [],
                         "an exemption marker that exempts nothing -- remove it "
                         "rather than leaving it to cover a future shape: "
                         + ", ".join(dead))


class TheRegistrysDeclaredRendererSetIsCompleteTests(unittest.TestCase):
    """The declaration this gate now reads has to stay honest, or deriving from it is
    just a slower way of being blind.

    The failure this closes: the renderer set was hardcoded here, in two places
    sharing one literal, and two routes added to the registry appeared in neither --
    so a surface rendering ONLY a new route was invisible to a gate reporting PASS.
    Deriving from the registry fixes that only if the registry's own list cannot
    silently fall behind either. So this asks the registry's SOURCE, by AST, which
    functions render one of its declared route templates, and requires each to be
    declared. A fifth route added without listing itself fails here.

    Membership is deliberately not inferred from a ``route_for_*`` name prefix: a
    naming convention is incidental structure, and this package's standing rule is
    not to infer identity from that. The structural fact used instead is "this
    function formats one of this module's own ``_..._ROUTE`` templates", which is
    what actually makes something a renderer of registry-declared text.
    """

    _SOURCE = _EMITTED_LIB / "state_actions.py"

    #: What makes a module-level string constant an operator-text TEMPLATE: it
    #: carries the placeholder every declared route renders. Derived from the
    #: contract, not from a name.
    _TEMPLATE_PLACEHOLDER = "{subject}"

    def _route_template_names(self, tree):
        """Every module-level string constant that is an operator-text template.

        Keyed on CONTENT (it carries `{subject}`), and accepting BOTH `x = ...` and
        `x: str = ...`. The first version keyed on a `_ROUTE` name suffix and on
        `ast.Assign` alone, and four shapes escaped it silently -- an annotated
        assignment (a form this very module uses for five of its own constants,
        including the declaration this gate reads), an f-string render, a
        `%`-format, and a template named anything else. A gate that only sees the
        shape already shipped is the green-and-blind pattern it exists to prevent.
        """
        found = set()
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            # PAIRS, not just whole values. `a, b = "...", "..."` has a Tuple target
            # AND a Tuple value, so a whole-value string test never matched it and the
            # name escaped -- measured. Each name is checked against the value that
            # actually binds to it.
            for target in targets:
                if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                    pairs = list(zip(target.elts, node.value.elts))
                else:
                    pairs = [(t, node.value) for t in (
                        target.elts if isinstance(target, ast.Tuple) else [target])]
                for name, value in pairs:
                    if not isinstance(name, ast.Name):
                        continue
                    if (isinstance(value, ast.Constant)
                            and isinstance(value.value, str)
                            and self._TEMPLATE_PLACEHOLDER in value.value):
                        found.add(name.id)
        return found

    def _functions_formatting_a_route_template(self, tree, templates):
        """Every module-level function that RENDERS one of those templates.

        "Mentions it at all", deliberately: matching only `template.format(...)`
        missed an f-string, a `%`-format and a direct return. A function that names
        an operator-text template is rendering it, whatever mechanism it uses, and
        that is the question this gate needs answered.
        """
        found = set()
        for node in tree.body:
            # `async def` too: a renderer declared async escaped a FunctionDef-only
            # sweep silently, and nothing stops a future one being written that way.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Name) and inner.id in templates:
                    found.add(node.name)
                    break
        return found

    def test_the_source_carries_route_templates_to_find(self):
        """Guards the sweep below against passing vacuously if the templates are ever
        renamed out from under it."""
        tree = ast.parse(self._SOURCE.read_text(encoding="utf-8"))
        templates = self._route_template_names(tree)
        self.assertGreaterEqual(len(templates), 3, sorted(templates))

    def test_every_route_renderer_in_the_registry_is_declared(self):
        tree = ast.parse(self._SOURCE.read_text(encoding="utf-8"))
        templates = self._route_template_names(tree)
        rendering = self._functions_formatting_a_route_template(tree, templates)
        self.assertTrue(rendering, "the AST sweep must find something")
        undeclared = sorted(rendering - registry_renderer_names())
        self.assertEqual(
            undeclared, [],
            "state_actions renders operator-facing text from these functions and "
            "does not declare them in OPERATOR_TEXT_RENDERERS, so this gate cannot "
            "see a surface that renders only them: " + ", ".join(undeclared))

    def test_every_declared_renderer_exists_and_is_callable(self):
        """The other direction: a declaration naming something that is gone would
        make the derived set quietly wrong in the permissive direction."""
        for name in sorted(registry_renderer_names()):
            self.assertTrue(callable(getattr(state_actions, name, None)),
                            f"OPERATOR_TEXT_RENDERERS names {name!r}, which is not a "
                            "callable on the registry")

    #: Every form a fifth route could plausibly take, with the mechanism it renders
    #: by. Four of these escaped the first version of the sweep SILENTLY -- including
    #: the annotated assignment, which is the form `state_actions` already uses for
    #: five of its own module constants, so it was the likeliest shape for the next
    #: route to take. Pinned as a table so narrowing the sweep fails here.
    _ROUTE_SHAPES = {
        "plain assign, .format": (
            '_FIFTH_ROUTE = "hello `{subject}` there, at some length"\n'
            'def route_for_fifth(s):\n    return _FIFTH_ROUTE.format(subject=s)\n'),
        "ANNOTATED assign, .format": (
            '_FIFTH_ROUTE: str = "hello `{subject}` there, at some length"\n'
            'def route_for_fifth(s):\n    return _FIFTH_ROUTE.format(subject=s)\n'),
        "f-string render": (
            '_FIFTH_ROUTE = "hello `{subject}` there, at some length"\n'
            'def route_for_fifth(s):\n    return f"{_FIFTH_ROUTE}"\n'),
        "percent-format render": (
            '_FIFTH_ROUTE = "hello `{subject}` there, at some length"\n'
            'def route_for_fifth(s):\n    return _FIFTH_ROUTE % s\n'),
        "async def renderer": (
            '_FIFTH_ROUTE = "hello `{subject}` there, at some length"\n'
            'async def route_for_fifth(s):\n'
            '    return _FIFTH_ROUTE.format(subject=s)\n'),
        "tuple-unpacking assignment": (
            '_FIFTH_ROUTE, _OTHER = "hello `{subject}` there, at length", "x"\n'
            'def route_for_fifth(s):\n    return _FIFTH_ROUTE.format(subject=s)\n'),
        "plus-concatenation render": (
            '_FIFTH_ROUTE = "hello `{subject}` there, at some length"\n'
            'def route_for_fifth(s):\n    return _FIFTH_ROUTE + s\n'),
        "template not named *_ROUTE": (
            '_FIFTH_SENTENCE = "hello `{subject}` there, at some length"\n'
            'def route_for_fifth(s):\n'
            '    return _FIFTH_SENTENCE.format(subject=s)\n'),
    }

    def test_the_sweep_sees_every_shape_a_route_could_take(self):
        missed = []
        for label, source in self._ROUTE_SHAPES.items():
            tree = ast.parse(source)
            templates = self._route_template_names(tree)
            rendering = self._functions_formatting_a_route_template(tree, templates)
            if "route_for_fifth" not in rendering:
                missed.append(label)
        self.assertEqual(
            missed, [],
            "an undeclared fifth route in these shapes would be invisible to this "
            "gate, which would report PASS while a surface rendering only it went "
            "unchecked: " + ", ".join(missed))

    def test_the_sweep_does_not_flag_a_function_touching_no_template(self):
        """The negative control. A sweep that answered "yes" for everything would
        pass the test above and mean nothing."""
        tree = ast.parse(
            '_FIFTH_ROUTE = "hello `{subject}` there, at some length"\n'
            'def unrelated(s):\n    return s.upper()\n')
        templates = self._route_template_names(tree)
        self.assertEqual(templates, {"_FIFTH_ROUTE"})
        self.assertEqual(
            self._functions_formatting_a_route_template(tree, templates), set())

    def test_the_sweeps_disclosed_limits_are_declared_by_the_registry(self):
        """The reach is stated where the declaration is, so a reader of
        `OPERATOR_TEXT_RENDERERS` sees what backs it without coming here."""
        self.assertTrue(state_actions.OPERATOR_TEXT_RENDERERS_SWEEP_LIMITS)
        for limit in state_actions.OPERATOR_TEXT_RENDERERS_SWEEP_LIMITS:
            self.assertIsInstance(limit, str)
            self.assertTrue(limit.strip())

    def test_the_two_routes_added_for_the_suppression_surface_are_covered(self):
        """Named explicitly, because these two are the ones that were missing and the
        reason this class exists."""
        for name in ("route_for_unreadable_suppression_record",
                     "route_for_stale_pause_record"):
            self.assertIn(name, registry_renderer_names())


if __name__ == "__main__":
    unittest.main()
