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
  * A SANCTIONED SENTENCE IS RECOGNISED BY DERIVATION, NOT BY AN ALLOWLIST. A
    literal is permitted when the registry ITSELF declares that text (checked
    against the registry's own declared and rendered instructions at run time) AND
    it lives in a module the registry imports -- i.e. the registry provably binds
    it rather than a second author having re-spelled it. Nothing is exempted for
    being in a particular file.

THE FOUR BANNED SHAPES
----------------------
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
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

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


def authored_texts(tree: ast.Module) -> List[Tuple[ast.AST, str]]:
    """The module's authored texts."""
    return authored_texts_in([tree], _docstring_nodes(tree))


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
            parts = [_joined_literal_text(value, docstrings)]
            for sub in ast.walk(value):
                name = sub.id if isinstance(sub, ast.Name) else (
                    sub.attr if isinstance(sub, ast.Attribute) else None)
                if name and name in bound:
                    parts.append(bound[name])
            bound[target] = " ".join(p for p in parts if p)
    return bound


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
    bound_modules = registry_bound_modules()
    entrypoints = registry_entrypoint_relpaths()
    spans = _symbol_spans(tree)
    docstrings = _docstring_nodes(tree)
    found: List[Finding] = []

    def add(node: ast.AST, kind: str, detail: str) -> None:
        found.append(Finding(
            relpath, node.lineno,
            getattr(node, "end_lineno", None) or node.lineno,
            kind, _symbol_at(spans, node.lineno), detail))

    def registry_declares(text: str) -> bool:
        """The registry itself declares this text, and this module is one the
        registry imports -- so the registry is the binder, not a second author."""
        if module_stem not in bound_modules:
            return False
        low = _normalise(text)
        return any(low in whole for whole in declared)

    for node, text in authored_texts_in([tree], docstrings):
        verb = repair_imperative(text)
        dest = sanctioned_destination(text)
        if verb and dest and not registry_declares(text):
            add(node, "authored_repair_directive",
                "directs a repair ({!r}) onto the {!r} write path in words the "
                "registry does not declare".format(verb, dest))
        for entrypoint in entrypoints:
            if entrypoint in text and not _is_bare_command(text, entrypoint) \
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


class ASurfaceThatRendersFromTheRegistryPassesTests(unittest.TestCase):
    """The over-firing direction, and the reason it is a test rather than a hope: a
    fail-closed check that refuses a legitimate surface refuses every build."""

    #: The two surfaces that already render every state-dependent instruction from
    #: the registry. They are full of operator-facing text, and none of it may be a
    #: finding.
    RENDERING_SURFACES = ("capability_health.py", "operator_acceptance.py")

    def test_a_registry_rendering_surface_has_no_findings_at_all(self):
        for name in self.RENDERING_SURFACES:
            with self.subTest(module=name):
                path = _EMITTED_LIB / name
                findings = scan_source(
                    path.read_text(encoding="utf-8"),
                    "{}/{}".format(_EMITTED_LIB_REL, name))
                self.assertEqual([f.render() for f in findings], [])

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


if __name__ == "__main__":
    unittest.main()
