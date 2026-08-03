"""LOAD-BEARING GATE: production source may not work out which module provides
a capability by deriving that module's name from an identifier. Resolution goes
through the declaration topology, or it does not happen.

Three releases in a row shipped a FIXTURE-based gate for this class, and each
one was green and blind to the very next instance, because a fixture only proves
the paths it exercises. This gate is STATIC: it fails when someone WRITES a new
id-derived lookup, whether or not any test ever runs that line.

WHY THIS IS AST-BASED, NOT TEXT-BASED
--------------------------------------
The defect signature is NOT "an f-string inside ``import_module``". ALL THREE of
this tree's real ``import_module(f"...")`` call sites are the SANCTIONED resolver
and its relatives -- they interpolate a stem that came from a DECLARATION
(``declaration.module_stem``) or from the enrolment list (``_stem``) or is a
first-party literal, which is precisely the shape this gate exists to require.
(There is a FOURTH textual occurrence, inside the emitter's template string. It
is not a call site at all -- see "the emitter's TEMPLATE TEXT" below.) A text
rule that banned the syntax would ban the resolver it is here to mandate, and
the only way to get such a rule green would be to allowlist whole files --
including the two files most likely to regress. That is not a gate.

The signature this gate bans is an IDENTIFIER interpolated into a sibling
module's name or filename:

  ``id_derived_module_name``       an id-shaped value interpolated into a name
                                   handed to a dynamic module import.
  ``interpolated_sibling_prefix``  a sibling-name prefix (``adapters_``,
                                   ``read_facades_``) with an interpolation
                                   spliced straight onto it, anywhere in code.
  ``filename_stem_used_as_id``     the same mistake in the other direction --
                                   a filename stem assigned to an id-shaped
                                   name, so a file's name silently becomes an
                                   identity.
  ``silent_resolution_swallow``    a broad handler that discards the outcome of
                                   a resolution (a constructed dynamic import,
                                   or a topology/registry lookup) without
                                   reporting anything. A resolution that fails
                                   in silence is the same operator dead end as
                                   a resolution that guessed wrong.

Because the rules read the AST, PROSE IS NOT CODE: a docstring or a comment
that names ``read_facades_{id}.py`` in order to document the banned shape is
never flagged. The resolver module's own docstring does exactly that.

An id does not escape by being parked in a local first. When a dynamic import's
argument is a plain local name, that name is resolved to its last binding in the
SAME scope and the rules are applied to what was bound -- so a module name built
one line before the import that consumes it is still flagged, reported at the
line that BUILT it, which is the line that has to change.

WHAT THIS GATE DOES NOT SEE
----------------------------
Stated plainly, because the whole reason this gate exists is that three previous
gates were green and blind, and an undisclosed boundary is the likeliest place
for the next instance to arrive.

  * An id LAUNDERED through a name that is not id-shaped, over more than one
    step (``label = capability_id``, then ``stem = f"...{label}"``). The alias
    resolution above is ONE step, over a plain local, inside one scope. There is
    no general value-flow analysis here, and a name reaching an import as a
    function PARAMETER has no binding in scope to resolve at all.
  * A CLOSURE. The alias step reads one scope's own bindings, so an id-derived
    local bound in an OUTER function and read as a free variable by a nested
    function that imports it is not resolved. (This is the inverse of the
    boundary the alias step deliberately enforces in the other direction -- an
    inner function's local is never mistaken for an outer one's -- and neither
    case is covered by the other.)
  * A name built with a prefix this gate does not police. ``adapters_`` and
    ``read_facades_`` are the two prefixes that actually carried this defect. A
    future ``writers_<id>`` is caught only if the id-shaped rule reaches it --
    as a direct import argument, or through the one alias step. Measured, for
    honesty: 36 sites in these two trees build a name or a path by interpolating
    an id-shaped value, and this gate polices 4 of them -- the three with a
    policed prefix, plus the capability-module stem the alias step reaches. The
    pinned exempt surface therefore describes the POLICED surface, not the whole
    identity-to-name surface, and should not be read as the latter.
  * The emitter's TEMPLATE TEXT. ``capability_code_scaffold.py`` carries the
    source it emits inside string literals, so its own
    ``import_module(f"external_write.{_stem}")`` is one Constant node to the AST
    and no rule here can reach it. A banned shape planted inside that emitted
    text stays green. There is no live exposure today -- the current templates
    resolve either a literal or a stem from the enrolment list -- but it is a
    real boundary. Emitted operator projects are not scanned by this gate
    either; what protects them is that the templates producing them are.
  * A broad handler whose no-op body is more than one statement. The swallow
    rule requires a single ``pass`` / ``...`` / ``continue`` / ``break`` /
    ``return None``; two statements that together do nothing evade it.
  * A filename stem spelled another way -- slicing ``.name``, hand-stripping a
    ``.py`` suffix -- is not matched by the stem rule.
  * A WAY OF LOADING A MODULE that is not one of the three this gate names.
    ``_DYNAMIC_IMPORT_ATTRS`` / ``_DYNAMIC_IMPORT_NAMES`` recognise
    ``import_module``, ``find_spec`` and ``__import__``, and nothing else.
    ``importlib.util.spec_from_file_location``, ``SourceFileLoader``,
    ``runpy.run_module`` and ``exec(compile(...))`` all load a module from a
    computed name or path and reach NO rule here. Checked against each of those
    four forms rather than assumed: an id interpolated into them is reported
    only if the string it builds happens to carry a policed sibling prefix, and
    is missed outright otherwise.
  * ``op_kind`` IS NOT ID-SHAPED TO THIS GATE, and that is the boundary most
    worth knowing. ``_is_id_shaped`` matches a name that is exactly one of
    ``_ID_NAMES`` (``id`` / ``capability_id`` / ``canonical_id`` /
    ``mechanism_id``) or ends in ``_id``. ``op_kind`` matches neither -- nor do
    ``vendor`` or ``slug`` -- so ``import_module(f"external_write.x_{op_kind}")``
    passes this gate cleanly, confirmed by running the rules over exactly that
    line. The operation name is now the value every consumer joins on, which
    makes it the most natural identifier for someone to build a module name out
    of next, and the rules here would not see it. Widening the id rule is a
    design change, not a tightening: ``module_stem`` and ``_stem`` are absent
    from that set deliberately (see the note on ``_ID_NAMES``), and the
    sanctioned resolver interpolates a stem. So this is DISCLOSED rather than
    quietly extended.

WHAT IS EXEMPT, AND HOW
------------------------
There are NO file-level exemptions. Every exemption is one line, carrying its
own justification, at the site:

    # resolver-monopoly-exempt: <why this name is chosen and not guessed>

The marker is recognised on any physical line of the offending expression, or
in the comment block immediately above it.

``test_the_exemption_surface_is_pinned`` pins the STRUCTURAL identity of every
exempted finding -- ``file::kind::enclosing symbol`` -- and not how many markers
exist, nor where they sit on the page.

Two weaker versions of this pin were each defeated, which is why it is shaped
this way. Counting MARKERS failed: a marker exempts every finding on the lines it
covers, so splicing a new banned shape onto an already-exempt line held the count
constant and the gate stayed green. Keying on ``file::kind`` failed too, one step
removed: neutralising a legitimate exemption and adding a fabricated one of the
SAME kind in the same file held the total, and the gate stayed green again. The
enclosing symbol closes that, because a substituted construction lives in a
different function or property. Line numbers are deliberately NOT part of the
identity -- they drift on any unrelated edit above, which would force edits to
this gate for changes that have nothing to do with it, and train the reflexive
marker-adding the gate exists to resist.

The same test rejects a marker whose justification is a stub, and a marker that
exempts nothing (so one cannot be planted ahead of a shape it will later cover).
Widening the exempt surface to make the violation list shorter is the exact
reflex this gate exists to catch.

SCOPE
------
The two live source trees are scanned: the emitted external-write lib and the
toolkit lib. ``test_*.py`` files are not production source and are skipped.
Released bundle copies under ``foundation-bundles/`` are frozen historical
artifacts -- they are deliberately NOT scanned, because a released version is
immutable and several of them still carry the shape this gate bans.

Run: python3 -m unittest discover -s wizard/scripts/lib -p test_resolver_monopoly_gate.py
"""
import ast
import sys
import unittest
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

_WIZARD = Path(__file__).resolve().parents[2]
_SCAN_ROOTS = (
    _WIZARD / "agents" / "lib" / "external_write",
    _WIZARD / "scripts" / "lib",
)

#: Sibling-module name prefixes whose only purpose was to encode an id in a
#: filename. A literal prefix with an interpolation spliced onto it is the
#: banned construction, wherever it appears in code.
_SIBLING_PREFIXES = ("adapters_", "read_facades_")

#: Attribute / bare-name forms that resolve a module at run time from a name.
_DYNAMIC_IMPORT_ATTRS = frozenset({"import_module", "find_spec"})
_DYNAMIC_IMPORT_NAMES = frozenset({"__import__", "import_module", "find_spec"})

#: The SANCTIONED way to answer "which module provides this operation" -- asking
#: the declaration topology, or the registry a declaration populated. Named here
#: so the "never discarded in silence" rule can find these call sites.
_RESOLUTION_LOOKUPS = frozenset(
    {
        "find_adapter",
        "find_read_facade",
        "build_topology",
        "get_read_facade_class",
        "get_adapter",
        "get_dispatch",
    }
)

#: Names whose value is an IDENTITY, never a module name. ``module_stem``,
#: ``_stem`` and ``module_name`` are deliberately absent: a stem that came from
#: a declaration or from the enrolment list is exactly what the sanctioned
#: resolver interpolates, and banning that would ban the resolver.
_ID_NAMES = frozenset({"id", "capability_id", "canonical_id", "mechanism_id"})

_EXEMPTION_MARKER = "resolver-monopoly-exempt:"

_GUIDANCE = {
    "id_derived_module_name": (
        "builds a module name by interpolating the identifier {detail}. Ask "
        "the declaration topology which module provides the operation "
        "(topology.find_adapter / topology.find_read_facade) and import the "
        "module_stem it returns"
    ),
    "interpolated_sibling_prefix": (
        "splices an interpolation onto the sibling-name prefix {detail!r}, "
        "which encodes an identity in a filename. Resolve the module by its "
        "declaration instead of by its name"
    ),
    "filename_stem_used_as_id": (
        "assigns a filename stem to {detail}, turning a file's name into an "
        "identity. Read the identity from what the module declares"
    ),
    "silent_resolution_swallow": (
        "discards the outcome of a resolution ({detail}) without reporting "
        "anything, so a failure to resolve is indistinguishable from nothing "
        "needing to be resolved. Report it"
    ),
}


class _Finding(NamedTuple):
    relpath: str
    lineno: int
    end_lineno: int
    kind: str
    symbol: str          # enclosing function/method/property qualname, or "<module>"
    detail: str

    @property
    def identity(self) -> str:
        """The finding's STABLE identity: where it is in the module's structure,
        not where it is on the page. Invariant under an unrelated edit above it,
        and different the moment the exempted construction is replaced by a
        different one."""
        return "{}::{}::{}".format(self.relpath, self.kind, self.symbol)

    def render(self) -> str:
        return "{}:{}: {} in {} -- {}; or mark the line '# {} <why>'".format(
            self.relpath, self.lineno, self.kind, self.symbol,
            _GUIDANCE[self.kind].format(detail=self.detail),
            _EXEMPTION_MARKER)


class _StringBuild(NamedTuple):
    """One string-construction expression: its literal template (None for an
    f-string, whose literal parts are held in the node itself) and the value
    nodes interpolated into it."""

    template: Optional[str]
    values: Tuple[ast.AST, ...]
    node: ast.AST


# ---------------------------------------------------------------------------
# Shape helpers
# ---------------------------------------------------------------------------

def _leaf_name(node: Optional[ast.AST]) -> Optional[str]:
    """The name an interpolated value is known by: a bare name, an attribute's
    final component, or a constant string subscript key (``entry["x"]``)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        key = node.slice
        if key.__class__.__name__ == "Index":  # py<3.9 spelling; harmless here
            key = getattr(key, "value", None)
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value
    return None


def _is_id_shaped(name: Optional[str]) -> bool:
    if not name:
        return False
    bare = name.lstrip("_").lower()
    return bare in _ID_NAMES or bare.endswith("_id")


def _string_builds(node: ast.AST):
    """Every string-construction expression at or under ``node``.

    Covers the f-string, ``%``, ``+`` and ``"...".format(...)`` forms, so that
    switching away from an f-string is not a way around this gate."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.JoinedStr):
            values = tuple(v.value for v in sub.values
                           if isinstance(v, ast.FormattedValue))
            yield _StringBuild(None, values, sub)
        elif isinstance(sub, ast.BinOp) and isinstance(sub.op, (ast.Add, ast.Mod)):
            for literal, other in ((sub.left, sub.right), (sub.right, sub.left)):
                if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                    yield _StringBuild(literal.value, (other,), sub)
        elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr == "format" \
                and isinstance(sub.func.value, ast.Constant) \
                and isinstance(sub.func.value.value, str):
            values = tuple(list(sub.args) + [kw.value for kw in sub.keywords])
            yield _StringBuild(sub.func.value.value, values, sub)


def _interpolated_id_names(node: ast.AST) -> List[str]:
    found = []
    for build in _string_builds(node):
        for value in build.values:
            name = _leaf_name(value)
            if _is_id_shaped(name):
                found.append(name)
    return found


def _is_dynamic_import(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in _DYNAMIC_IMPORT_ATTRS:
        return True
    return isinstance(func, ast.Name) and func.id in _DYNAMIC_IMPORT_NAMES


def _is_resolution_lookup(call: ast.Call) -> bool:
    return _leaf_name(call.func) in _RESOLUTION_LOOKUPS


def _constructed_argument(call: ast.Call) -> Optional[ast.AST]:
    """The first argument that is BUILT rather than written out -- a plain
    string literal module name is not a derivation and never flagged."""
    for arg in list(call.args) + [kw.value for kw in call.keywords]:
        for _build in _string_builds(arg):
            return arg
    return None


def _looks_like_filename_stem(node: ast.AST) -> Optional[str]:
    """A ``.stem`` attribute or an ``os.path.splitext`` call in ``node``.

    Bound, stated rather than assumed covered: other spellings of the same idea
    (slicing ``.name``, stripping a ``.py`` suffix by hand) are not matched."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr == "stem":
            return "a path's .stem"
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr == "splitext":
            return "os.path.splitext"
    return None


def _handler_reports_nothing(handler: ast.ExceptHandler) -> bool:
    """A handler that neither raises, records, nor returns a value the caller
    can act on. Broader than ``pass`` alone, so ``return None`` / ``continue``
    is not a way around the rule."""
    if len(handler.body) != 1:
        return False
    stmt = handler.body[0]
    if isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
            and stmt.value.value is Ellipsis:
        return True
    if isinstance(stmt, ast.Return):
        if stmt.value is None:
            return True
        if isinstance(stmt.value, ast.Constant) and stmt.value.value is None:
            return True
    return False


def _handler_is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    return _leaf_name(handler.type) in ("Exception", "BaseException")


# ---------------------------------------------------------------------------
# One-step alias resolution: an id parked in a local before its import
# ---------------------------------------------------------------------------

_SCOPE_TYPES: Tuple[type, ...] = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _own_nodes(scope: ast.AST) -> List[ast.AST]:
    """Every node belonging to ``scope`` itself, stopping at a nested function --
    an inner function's locals are not the outer one's."""
    collected: List[ast.AST] = []

    def descend(node: ast.AST, is_root: bool) -> None:
        if not is_root and isinstance(node, _SCOPE_TYPES):
            return
        collected.append(node)
        for child in ast.iter_child_nodes(node):
            descend(child, False)

    descend(scope, True)
    return collected


def _scopes(tree: ast.Module):
    """The module, then every function in it."""
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, _SCOPE_TYPES):
            yield node


def _local_bindings(own: List[ast.AST]) -> Dict[str, List[Tuple[int, ast.AST]]]:
    """``name -> [(lineno, bound expression)]`` for plain single-name bindings in
    one scope, in source order. A ``for`` target is deliberately absent: it binds
    an ELEMENT of the iterable, not the iterable, so treating the iterable as the
    bound value would be wrong."""
    bound: Dict[str, List[Tuple[int, ast.AST]]] = {}
    named_expr = getattr(ast, "NamedExpr", None)
    for node in own:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif named_expr is not None and isinstance(node, named_expr):
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bound.setdefault(target.id, []).append((node.lineno, value))
    return bound


_DEF_TYPES: Tuple[type, ...] = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _symbol_spans(tree: ast.Module) -> List[Tuple[int, int, str]]:
    """``(first line, last line, qualified name)`` for every class, function,
    method and property in the module, innermost resolvable by span width."""
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


def _symbol_at(spans: List[Tuple[int, int, str]], lineno: int) -> str:
    """The innermost enclosing symbol's qualified name, or ``"<module>"``."""
    enclosing = [span for span in spans if span[0] <= lineno <= span[1]]
    if not enclosing:
        return "<module>"
    enclosing.sort(key=lambda span: span[1] - span[0])
    return enclosing[0][2]


def _last_binding_before(bindings: List[Tuple[int, ast.AST]],
                         lineno: int) -> Optional[Tuple[int, ast.AST]]:
    """The last binding at or above ``lineno``; failing that, the last binding
    anywhere in the scope -- a gate prefers looking than not looking."""
    earlier = [pair for pair in bindings if pair[0] <= lineno]
    if earlier:
        return earlier[-1]
    return bindings[-1] if bindings else None


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

def _scan_source(source: str, relpath: str) -> List[_Finding]:
    """Every banned shape in ``source``. Never raises."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [_Finding(relpath, getattr(exc, "lineno", 0) or 0,
                         getattr(exc, "lineno", 0) or 0,
                         "id_derived_module_name", "<module>",
                         "unreadable as Python ({})".format(exc.msg))]

    found: List[_Finding] = []
    claimed = set()
    spans = _symbol_spans(tree)

    def add(node: ast.AST, kind: str, detail: str) -> None:
        found.append(_Finding(
            relpath, node.lineno, getattr(node, "end_lineno", None) or node.lineno,
            kind, _symbol_at(spans, node.lineno), detail))

    for node in ast.walk(tree):
        # id_derived_module_name -- an identity interpolated into a name handed
        # to a dynamic module import.
        if isinstance(node, ast.Call) and _is_dynamic_import(node):
            arg = _constructed_argument(node)
            if arg is not None:
                names = _interpolated_id_names(arg)
                if names:
                    add(node, "id_derived_module_name",
                        ", ".join(repr(n) for n in sorted(set(names))))

        # interpolated_sibling_prefix -- a sibling-name prefix with an
        # interpolation spliced straight onto it, anywhere in code.
        if isinstance(node, ast.JoinedStr):
            parts = node.values
            for index, part in enumerate(parts):
                if not (isinstance(part, ast.Constant)
                        and isinstance(part.value, str)
                        and index + 1 < len(parts)
                        and isinstance(parts[index + 1], ast.FormattedValue)):
                    continue
                for prefix in _SIBLING_PREFIXES:
                    if part.value.endswith(prefix) and id(node) not in claimed:
                        claimed.add(id(node))
                        add(node, "interpolated_sibling_prefix", prefix)
        for build in _string_builds(node):
            if not build.template or id(build.node) in claimed:
                continue
            for prefix in _SIBLING_PREFIXES:
                if any(marker in build.template
                       for marker in (prefix + "{", prefix + "%")) \
                        or build.template.endswith(prefix):
                    claimed.add(id(build.node))
                    add(build.node, "interpolated_sibling_prefix", prefix)

        # filename_stem_used_as_id -- the same mistake, other direction.
        targets, value = _assignment_parts(node)
        if value is not None:
            names = [n for n in targets if _is_id_shaped(n)]
            if names:
                how = _looks_like_filename_stem(value)
                if how:
                    add(node, "filename_stem_used_as_id",
                        "{} (from {})".format(", ".join(sorted(names)), how))

        # silent_resolution_swallow -- a resolution whose failure is discarded.
        if isinstance(node, ast.Try):
            why = _resolution_in_body(node)
            if why:
                for handler in node.handlers:
                    if _handler_is_broad(handler) and _handler_reports_nothing(handler):
                        add(handler, "silent_resolution_swallow", why)

    # id_derived_module_name, one alias step -- a name BUILT from an id and then
    # handed to a dynamic import as a plain local, which no rule above reaches
    # because neither the construction nor the import mentions both halves.
    # Reported at the line that built the name; that is the line to change.
    for scope in _scopes(tree):
        own = _own_nodes(scope)
        bindings = _local_bindings(own)
        if not bindings:
            continue
        for node in own:
            if not (isinstance(node, ast.Call) and _is_dynamic_import(node)):
                continue
            args = list(node.args) + [kw.value for kw in node.keywords]
            for arg in args:
                if not isinstance(arg, ast.Name) or arg.id not in bindings:
                    continue
                resolved = _last_binding_before(bindings[arg.id], node.lineno)
                if resolved is None:
                    continue
                names = _interpolated_id_names(resolved[1])
                if names:
                    add(resolved[1], "id_derived_module_name",
                        "{}, which a module import in the same scope then "
                        "consumes".format(
                            ", ".join(repr(n) for n in sorted(set(names)))))

    return sorted(set(found))


def _assignment_parts(node: ast.AST) -> Tuple[List[str], Optional[ast.AST]]:
    """The bound names and the bound expression of an assignment-like node."""
    if isinstance(node, ast.Assign):
        targets, value = node.targets, node.value
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets, value = [node.target], node.value
    elif isinstance(node, ast.For):
        targets, value = [node.target], node.iter
    elif hasattr(ast, "NamedExpr") and isinstance(node, getattr(ast, "NamedExpr")):
        targets, value = [node.target], node.value
    else:
        return [], None
    names = []
    for target in targets:
        for sub in ast.walk(target):
            if isinstance(sub, ast.Name):
                names.append(sub.id)
    return names, value


def _resolution_in_body(try_node: ast.Try) -> Optional[str]:
    """What resolution, if any, the ``try`` body performs. A dynamic import of
    a plain literal module name is NOT a resolution in this sense -- nothing
    was derived, so nothing can have been derived wrongly."""
    for stmt in try_node.body:
        for sub in ast.walk(stmt):
            if not isinstance(sub, ast.Call):
                continue
            if _is_dynamic_import(sub) and _constructed_argument(sub) is not None:
                return "a module import built from a constructed name, line {}".format(
                    sub.lineno)
            if _is_resolution_lookup(sub):
                return "{} on line {}".format(_leaf_name(sub.func), sub.lineno)
    return None


# ---------------------------------------------------------------------------
# Per-line exemptions
# ---------------------------------------------------------------------------

def _marker_sites(source: str) -> List[Tuple[int, str]]:
    """Every ``resolver-monopoly-exempt:`` marker, with its justification."""
    sites = []
    for number, line in enumerate(source.splitlines(), start=1):
        _, sep, tail = line.partition(_EXEMPTION_MARKER)
        if not sep:
            continue
        if "#" not in line.split(_EXEMPTION_MARKER)[0]:
            continue  # the marker only counts inside a comment
        sites.append((number, tail.strip()))
    return sites


def _exempt_lines(source: str) -> Dict[int, str]:
    return {number: why for number, why in _marker_sites(source)}


def _exempting_marker(finding: _Finding, source: str,
                      marked: Dict[int, str]) -> Optional[int]:
    """The line number of the marker that exempts ``finding``, if any -- a marker
    on a physical line of the offending expression, or in the comment block
    immediately above it. Returned rather than a bool so the census can tell
    which markers are actually doing work."""
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


def _is_exempt(finding: _Finding, source: str, marked: Dict[int, str]) -> bool:
    return _exempting_marker(finding, source, marked) is not None


class ResolverMonopolyGateTests(unittest.TestCase):

    def _production_files(self):
        for root in _SCAN_ROOTS:
            for path in sorted(root.rglob("*.py")):
                if path.name.startswith("test_"):
                    continue
                yield path

    def test_no_id_derived_sibling_lookups_in_production_source(self):
        violations = []
        for path in self._production_files():
            source = path.read_text(encoding="utf-8", errors="replace")
            marked = _exempt_lines(source)
            relpath = path.relative_to(_WIZARD).as_posix()
            for finding in _scan_source(source, relpath):
                if not _is_exempt(finding, source, marked):
                    violations.append(finding.render())
        self.assertEqual(
            violations, [],
            "a module's name may not be derived from an identifier:\n  "
            + "\n  ".join(violations))

    def test_every_registration_in_shipped_source_is_STATICALLY_RESOLVABLE(self):
        """Our own emitted lib must stay readable by the resolver. A shape the
        topology cannot read would fail closed in every deployment.

        ``test_*.py`` is deliberately out of subject: the emitted lib never
        ships a test file, so a registration inside one could never be resolved
        in a deployment and must not pressure anyone into widening this gate."""
        lib_path = str(_WIZARD / "scripts" / "lib")
        inserted = lib_path not in sys.path
        if inserted:
            sys.path.insert(0, lib_path)
            self.addCleanup(sys.path.remove, lib_path)
        from topology import discover_declarations

        unresolved = []
        lib = _WIZARD / "agents" / "lib" / "external_write"
        for path in sorted(lib.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            for declaration in discover_declarations(
                    path.read_text(encoding="utf-8"), path.name):
                if declaration.unresolved_reason:
                    unresolved.append(declaration.unresolved_reason)
        self.assertEqual(unresolved, [],
                         "shipped modules the resolver cannot read:\n  "
                         + "\n  ".join(unresolved))

    def test_the_gate_itself_detects_a_planted_violation(self):
        """A gate that cannot fail is not a gate. One planted instance per
        rule, plus the sanctioned shapes and the prose forms, which must stay
        clean."""
        planted = {
            "id_derived_module_name":
                'importlib.import_module(f"external_write.{canonical_id}")\n',
            "interpolated_sibling_prefix":
                'path = f"{lib}/adapters_{vendor}.py"\n',
            "filename_stem_used_as_id":
                "capability_id = adapter_path.stem\n",
            "silent_resolution_swallow":
                "try:\n"
                '    importlib.import_module(f"external_write.{stem}")\n'
                "except Exception:\n"
                "    pass\n",
        }
        for kind, source in planted.items():
            with self.subTest(kind=kind):
                kinds = [f.kind for f in _scan_source(source, "planted.py")]
                self.assertIn(kind, kinds,
                              "the gate did not flag a planted {}".format(kind))

        # An id parked in a local first, then imported -- the shape that
        # mentions neither a policed prefix at the construction site nor an id
        # at the import site, so only the alias step reaches it. Reported at the
        # line that BUILT the name.
        laundered = (
            "def go(project_root, capability_id):\n"
            '    stem = f"{capability_id}_writer"\n'
            "    return importlib.import_module(stem)\n"
        )
        aliased = _scan_source(laundered, "planted.py")
        self.assertEqual([(f.kind, f.lineno) for f in aliased],
                         [("id_derived_module_name", 2)])

        # The same shape as the capability runner's own module import.
        runner_shape = (
            "def _import_capability_module(project_root, capability_id):\n"
            '    module_stem = f"{capability_id}{CAPABILITY_MODULE_SUFFIX}"\n'
            "    if str(d) not in sys.path:\n"
            "        sys.path.insert(0, str(d))\n"
            "    return importlib.import_module(module_stem)\n"
        )
        self.assertEqual([(f.kind, f.lineno) for f in _scan_source(runner_shape, "p.py")],
                         [("id_derived_module_name", 2)])

        # A local built from a DECLARATION is the sanctioned shape and must stay
        # clean through the alias step too, or the gate bans its own mechanism.
        declared_local = (
            "def go(declaration):\n"
            '    stem = f"{EXTERNAL_WRITE_PKG}.{declaration.module_stem}"\n'
            "    return importlib.import_module(stem)\n"
        )
        self.assertEqual(_scan_source(declared_local, "clean.py"), [])

        # A local bound in an INNER function is not the outer function's local:
        # the alias step must not reach across a scope boundary.
        other_scope = (
            "def outer(capability_id):\n"
            "    def inner():\n"
            '        stem = f"{capability_id}_writer"\n'
            "        return stem\n"
            "    return importlib.import_module(stem)\n"
        )
        self.assertEqual(
            [f.kind for f in _scan_source(other_scope, "p.py")], [],
            "the alias step reached into another scope's locals")

        # The real shape this gate replaced -- an id spliced onto a read-facade
        # module name -- trips both name rules at once.
        deleted_shape = (
            'importlib.import_module(f"{EXTERNAL_WRITE_PKG}.'
            'read_facades_{capability_id}")\n')
        self.assertEqual(
            sorted({f.kind for f in _scan_source(deleted_shape, "planted.py")}),
            ["id_derived_module_name", "interpolated_sibling_prefix"])

        # The SANCTIONED resolver and its relatives must stay clean, or this
        # gate would ban the mechanism it exists to require.
        for sanctioned in (
            'importlib.import_module(f"{PKG}.{declaration.module_stem}")\n',
            'importlib.import_module(f"external_write.{_stem}")\n',
            'importlib.import_module(f"external_write.{module_name}")\n',
            'importlib.import_module("external_write.lifecycle_state")\n',
            "d = topology.find_read_facade(op_kind)\n",
        ):
            with self.subTest(sanctioned=sanctioned.strip()):
                self.assertEqual(_scan_source(sanctioned, "clean.py"), [])

        # Prose is not code: documenting the banned shape is not committing it.
        for prose in (
            '"""derives read_facades_{id}.py and adapters_{id}.py."""\n',
            "# never build adapters_{canonical_id} from an id\n",
        ):
            with self.subTest(prose=prose.strip()):
                self.assertEqual(_scan_source(prose, "clean.py"), [])

        # The structural identity a finding carries: the qualified name of the
        # enclosing symbol, which is what makes a same-kind substitution in a
        # DIFFERENT symbol visible to the exemption census.
        nested = (
            "class Spec:\n"
            "    @property\n"
            "    def adapter_module_stem(self):\n"
            '        return f"adapters_{self.capability_id}"\n'
            "\n"
            "    @property\n"
            "    def rogue_alias(self):\n"
            '        return f"adapters_{self.capability_id}"\n'
            "\n"
            "\n"
            'TOP = f"adapters_{some_id}"\n'
        )
        self.assertEqual(
            [(f.symbol, f.identity.split("::")[-1])
             for f in _scan_source(nested, "p.py")],
            [("Spec.adapter_module_stem", "Spec.adapter_module_stem"),
             ("Spec.rogue_alias", "Spec.rogue_alias"),
             ("<module>", "<module>")],
            "the enclosing symbol must distinguish two same-kind findings in "
            "the same file, and name the module when there is no symbol")

        # A reporting handler around a resolution is the correct shape.
        reporting = (
            "try:\n"
            '    importlib.import_module(f"external_write.{stem}")\n'
            "except Exception as exc:\n"
            "    raise RuntimeError(str(exc)) from exc\n"
        )
        self.assertEqual(_scan_source(reporting, "clean.py"), [])

    def test_the_exemption_surface_is_pinned(self):
        """There are no file-level exemptions -- only single lines carrying
        their own justification.

        What is pinned is the STRUCTURAL identity of every exempted finding --
        ``file::kind::enclosing symbol`` -- not how many markers exist and not
        where they sit on the page.

        Counting markers was not enough: a marker exempts every finding on the
        lines it covers, so splicing a new banned shape onto an already-exempt
        line kept the count constant and turned the whole gate green. Keying on
        ``file::kind`` alone was still one level too coarse: neutralising a
        legitimate exemption and adding a fabricated one of the SAME kind in the
        same file held the total, and the gate stayed green again. The enclosing
        symbol closes that, because a substituted construction lives in a
        different function or property. Line numbers are deliberately NOT part of
        the identity: they drift on any unrelated edit above, which would force
        gate edits for changes that have nothing to do with this and train the
        reflexive marker-adding this gate exists to resist."""
        expected = {
            # The one place an id may reach a module name: a CAPABILITY module's
            # stem, which a build-time check pins to its canonical identity.
            "agents/lib/external_write/capability_runner.py"
            "::id_derived_module_name::_import_capability_module": 1,
            # The emitter: it CHOOSES the name a new module will be written
            # under, which is the one place a name is authored, not resolved.
            "scripts/lib/capability_code_scaffold.py"
            "::interpolated_sibling_prefix::CapabilityCodeSpec.adapter_module_stem": 1,
            "scripts/lib/capability_code_scaffold.py"
            "::interpolated_sibling_prefix::CapabilityCodeSpec.read_facade_module_stem": 1,
            # One filename convention deliberately kept alongside the declared
            # adapter list, and one identity a capability module's own stem is
            # DEFINED to carry.
            "scripts/lib/upgrade_reconcile.py"
            "::interpolated_sibling_prefix::resolve_adapter_migration_targets": 1,
            # Moved (not added) when a SECOND conformance post-condition needed
            # the same quantifier: the capability-declared-op_kind reader was
            # extracted so both checks share it, which keeps this surface at ONE
            # entry instead of one per post-condition.
            "scripts/lib/upgrade_reconcile.py"
            "::filename_stem_used_as_id::_capability_declared_op_kinds": 1,
        }
        actual: Dict[str, int] = {}
        unjustified = []
        dead = []
        for path in self._production_files():
            source = path.read_text(encoding="utf-8", errors="replace")
            marked = _exempt_lines(source)
            if not marked:
                continue
            relpath = path.relative_to(_WIZARD).as_posix()
            working = set()
            for finding in _scan_source(source, relpath):
                marker = _exempting_marker(finding, source, marked)
                if marker is None:
                    continue
                actual[finding.identity] = actual.get(finding.identity, 0) + 1
                working.add(marker)
            for number, why in _marker_sites(source):
                if len(why) < 20:
                    unjustified.append("{}:{}".format(relpath, number))
                if number not in working:
                    dead.append("{}:{}".format(relpath, number))
        self.assertEqual(
            actual, expected,
            "the exempt surface changed. Every exempted finding must be a name "
            "that is authored, not resolved -- if a new one is here to shorten "
            "the violation list, resolve by declaration instead")
        self.assertEqual(unjustified, [],
                         "an exemption marker with no real justification: "
                         + ", ".join(unjustified))
        self.assertEqual(dead, [],
                         "an exemption marker that exempts nothing -- remove it "
                         "rather than leaving it to cover a future shape: "
                         + ", ".join(dead))


if __name__ == "__main__":
    unittest.main()
