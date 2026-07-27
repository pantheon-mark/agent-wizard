"""Declaration topology: which module declares support for which op_kind.

SHARED CORE — this region is duplicated VERBATIM into
``wizard/scripts/lib/topology.py`` and held byte-identical by
``test_topology_cross_tree_pin.py``. Change one, change both, same commit.

Why this module exists: every consumer used to answer "which module serves
capability Y?" by deriving a filename from an id (``read_facades_{id}.py``,
``adapters_{id}.py``). Operator projects predate those conventions, so the
derivation missed real modules and the miss was silent. The modules already
declare what they serve -- ``register_adapter(op_kind, ...)`` and
``register_read_facade(op_kind, ...)`` at module scope. This module reads
those declarations and joins on ``op_kind``. Filenames are never inputs.

Deliberately AST-only: it never imports the modules it reads, so it is safe
in the toolkit process (a different interpreter from the operator's venv)
and cannot execute operator code as a side effect of resolution.

Every ``register_adapter`` / ``register_read_facade`` call ANYWHERE in the
module is found -- the whole tree is walked, not just its top level. Three
shapes RESOLVE to a concrete op_kind: a bare call at the top level of the
file with the operation name given positionally or by the ``op_kind=``
keyword; the same, folded from a same-module string constant; and a ``for``
loop, at the top level of the file, over a literal tuple/list or a
same-module tuple/list constant, whose elements are string literals or
same-module string constants. Every other call site -- nested inside an
``if``/``try``/function/loop body, missing a required argument, or with an
operation name in a form this module cannot read -- is REPORTED as a
Declaration with ``op_kind=None`` and a plain-language ``unresolved_reason``
naming the file and line. A declaration is never dropped: a call site this
module cannot resolve is surfaced as unresolved, never silently skipped,
because a silent skip is the exact mechanism that hid the read-facade
defect this module exists to fix.
"""

# SHARED CORE
# Everything from this line through the matching end-of-region marker near
# the bottom of this file is copied verbatim into the toolkit's own copy of
# this module and kept byte-identical there. The module docstring above
# this line is the one part allowed to differ between the two copies;
# nothing below this line may.

import ast
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

#: Registration functions this module understands, mapped to their role.
_REGISTRARS = {
    "register_adapter": "adapter",
    "register_read_facade": "read_facade",
}

#: The keyword name each registrar uses for its second (symbol) argument --
#: read off the real signatures (`adapter_registry.register_adapter(op_kind,
#: adapter)`, `read_facade.register_read_facade(op_kind, facade_cls)`).
_SYMBOL_KEYWORDS = {
    "register_adapter": "adapter",
    "register_read_facade": "facade_cls",
}

_NESTED_REASON = (
    "{relpath} registers something on line {lineno}, but it is inside an "
    "if/try/function/loop body rather than at the top level of the file, so "
    "what it provides cannot be determined"
)
_UNREADABLE_OP_KIND_REASON = (
    "{relpath} registers something on line {lineno} but the operation name "
    "and the class/adapter it applies to are not both written in a form "
    "this check can read (expected a plain text name, or a name defined at "
    "the top of the same file, for each)"
)
_UNFOLDABLE_LOOP_REASON = (
    "{relpath} registers something on line {lineno} but it is inside a loop "
    "whose values this check cannot read, so what it provides cannot be "
    "determined"
)


@dataclass(frozen=True)
class Declaration:
    """One ``register_*(op_kind, Symbol)`` call found in one module."""
    role: str                          # "adapter" | "read_facade"
    module_stem: str
    relpath: str
    op_kind: Optional[str]             # None iff unresolved_reason is set
    symbol: Optional[str]
    unresolved_reason: Optional[str]   # plain-language, names the file


def _string_consts(tree: ast.Module) -> Dict[str, str]:
    """Module-level ``NAME = "literal"`` bindings, for constant folding."""
    out: Dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant) \
                and isinstance(value.value, str):
            out[target.id] = value.value
    return out


def _module_seq_nodes(tree: ast.Module) -> Dict[str, ast.AST]:
    """Module-level ``NAME = (...)`` / ``NAME = [...]`` bindings, so a
    ``for`` loop over ``NAME`` can be folded the same way as a loop over an
    inline tuple/list -- a loop iterable one level of indirection away from
    the loop itself is still a same-module constant."""
    out: Dict[str, ast.AST] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if isinstance(target, ast.Name) and isinstance(value, (ast.Tuple, ast.List)):
            out[target.id] = value
    return out


def _resolve_str(node: Optional[ast.AST], consts: Dict[str, str]) -> Optional[str]:
    """A string value from a literal or a same-module string constant; None
    for anything else (never guessed at)."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    return None


def _symbol_name(node: Optional[ast.AST]) -> Optional[str]:
    """Class name from ``Cls`` or ``Cls()``; None if not a plain name."""
    if node is None:
        return None
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _registrar_name(func: ast.AST) -> Optional[str]:
    """The registrar function name (``register_adapter`` /
    ``register_read_facade``) a Call's ``func`` node refers to, whether
    called as a bare name or as an attribute; None if it is neither."""
    if isinstance(func, ast.Name) and func.id in _REGISTRARS:
        return func.id
    if isinstance(func, ast.Attribute) and func.attr in _REGISTRARS:
        return func.attr
    return None


def _op_kind_node(call: ast.Call) -> Optional[ast.AST]:
    """The AST node supplying ``op_kind`` -- first positional arg, else the
    ``op_kind=`` keyword; None if neither is present."""
    if call.args:
        return call.args[0]
    for kw in call.keywords:
        if kw.arg == "op_kind":
            return kw.value
    return None


def _symbol_node(call: ast.Call, registrar_name: str) -> Optional[ast.AST]:
    """The AST node supplying the symbol -- second positional arg, else the
    registrar's own symbol keyword (``facade_cls`` / ``adapter``); None if
    neither is present."""
    if len(call.args) >= 2:
        return call.args[1]
    kw_name = _SYMBOL_KEYWORDS[registrar_name]
    for kw in call.keywords:
        if kw.arg == kw_name:
            return kw.value
    return None


def _foldable_elements(iter_node: ast.AST, seq_nodes: Dict[str, ast.AST]) -> Optional[List[ast.AST]]:
    """The element nodes of a loop's iterable, if it is a literal tuple/list
    or a Name bound at module level to one; None if it cannot be folded."""
    if isinstance(iter_node, (ast.Tuple, ast.List)):
        return iter_node.elts
    if isinstance(iter_node, ast.Name) and iter_node.id in seq_nodes:
        return seq_nodes[iter_node.id].elts
    return None


def _declaration(role: str, stem: str, relpath: str, op_kind: Optional[str],
                  symbol: Optional[str], reason: Optional[str]) -> Declaration:
    return Declaration(role=role, module_stem=stem, relpath=relpath,
                        op_kind=op_kind, symbol=symbol, unresolved_reason=reason)


def _resolve_call(call: ast.Call, stem: str, relpath: str,
                   consts: Dict[str, str]) -> Declaration:
    """Resolve ONE call at a resolvable top-level position (a bare call, or
    a call inside a top-level loop whose op_kind does not depend on the loop
    variable) to a single Declaration -- concrete op_kind on success, a
    named ``unresolved_reason`` when either required value is missing or
    unreadable. Never raises, never drops the call site."""
    registrar_name = _registrar_name(call.func)
    role = _REGISTRARS[registrar_name]
    op_node = _op_kind_node(call)
    sym_node = _symbol_node(call, registrar_name)
    symbol = _symbol_name(sym_node)
    op_kind = _resolve_str(op_node, consts)
    if op_node is not None and sym_node is not None and op_kind is not None:
        return _declaration(role, stem, relpath, op_kind, symbol, None)
    return _declaration(
        role, stem, relpath, None, symbol,
        _UNREADABLE_OP_KIND_REASON.format(relpath=relpath, lineno=call.lineno))


def _resolve_loop_call(call: ast.Call, for_node: ast.For, stem: str, relpath: str,
                        consts: Dict[str, str],
                        seq_nodes: Dict[str, ast.AST]) -> List[Declaration]:
    """Resolve ONE ``register_*`` call that sits directly in the body of a
    top-level ``for`` loop. When the call's op_kind IS the loop variable, the
    loop's iterable is folded (shape 3) and one Declaration is emitted
    per element -- or, if the iterable cannot be folded, ONE Declaration
    reports the whole call site as unresolved. When the call's op_kind does
    NOT depend on the loop variable, the loop is irrelevant to it and it is
    resolved exactly like any other top-level call."""
    registrar_name = _registrar_name(call.func)
    role = _REGISTRARS[registrar_name]
    op_node = _op_kind_node(call)
    sym_node = _symbol_node(call, registrar_name)
    symbol = _symbol_name(sym_node)

    loop_var = for_node.target.id if isinstance(for_node.target, ast.Name) else None
    depends_on_loop_var = (loop_var is not None and isinstance(op_node, ast.Name)
                            and op_node.id == loop_var)

    if not depends_on_loop_var:
        return [_resolve_call(call, stem, relpath, consts)]

    elements = _foldable_elements(for_node.iter, seq_nodes)
    if elements is not None:
        values = [_resolve_str(e, consts) for e in elements]
        if all(v is not None for v in values):
            return [_declaration(role, stem, relpath, v, symbol, None) for v in values]

    return [_declaration(
        role, stem, relpath, None, symbol,
        _UNFOLDABLE_LOOP_REASON.format(relpath=relpath, lineno=call.lineno))]


def _nested_declaration(call: ast.Call, stem: str, relpath: str) -> Declaration:
    """A ``register_*`` call found anywhere that is NOT at a resolvable
    top-level position (module top level, or directly in a top-level loop's
    body). REPORTED, never dropped -- this is the exact shape (a call one
    structural level away from the top of the file) that used to vanish."""
    registrar_name = _registrar_name(call.func)
    role = _REGISTRARS[registrar_name]
    symbol = _symbol_name(_symbol_node(call, registrar_name))
    return _declaration(
        role, stem, relpath, None, symbol,
        _NESTED_REASON.format(relpath=relpath, lineno=call.lineno))


def discover_declarations(source: str, relpath: str) -> Tuple[Declaration, ...]:
    """Every ``register_adapter`` / ``register_read_facade`` call site in
    ``source``, wherever in the module it appears, resolved to a concrete
    op_kind where the shape allows.

    RESOLVES to a concrete op_kind, at the top level of the file only:
      1. ``register_x("literal", Cls)`` -- or the same written with the
         ``op_kind=`` / ``facade_cls=`` / ``adapter=`` keywords.
      2. ``register_x(MODULE_CONST, Cls)`` -- folded from a module-level
         string constant.
      3. ``for v in (A, B, C): register_x(v, Cls)`` -- the tuple/list may be
         written inline or be itself a module-level constant; every element
         must be a string literal or a module-level string constant.

    Every other call site -- nested inside an ``if``/``try``/function/loop
    body, missing a required argument, or with an operation name this check
    cannot read -- is REPORTED as a Declaration with ``op_kind=None`` and a
    plain-language ``unresolved_reason`` naming the file and line. Nothing
    is ever dropped: every syntactic ``register_*`` call site in the module
    produces at least one Declaration.
    """
    stem = relpath.rsplit("/", 1)[-1]
    if stem.endswith(".py"):
        stem = stem[:-3]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return (Declaration(
            role="unknown", module_stem=stem, relpath=relpath, op_kind=None,
            symbol=None,
            unresolved_reason=(
                f"{relpath} could not be read as Python ({exc.msg}), so what it "
                "provides cannot be determined"),
        ),)

    consts = _string_consts(tree)
    seq_nodes = _module_seq_nodes(tree)

    # Location classification -- ONLY these two shapes are resolvable; every
    # other register_* call site, found below via ast.walk, is reported.
    top_level_calls: List[ast.Call] = []
    loop_calls: List[Tuple[ast.Call, ast.For]] = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and _registrar_name(node.value.func) is not None:
            top_level_calls.append(node.value)
        elif isinstance(node, ast.For):
            for body_node in node.body:
                if isinstance(body_node, ast.Expr) and isinstance(body_node.value, ast.Call) \
                        and _registrar_name(body_node.value.func) is not None:
                    loop_calls.append((body_node.value, node))

    found: List[Declaration] = []
    handled_ids = set()

    for call in top_level_calls:
        found.append(_resolve_call(call, stem, relpath, consts))
        handled_ids.add(id(call))

    for call, for_node in loop_calls:
        found.extend(_resolve_loop_call(call, for_node, stem, relpath, consts, seq_nodes))
        handled_ids.add(id(call))

    # Every register_* call ANYWHERE ELSE in the module (nested inside an
    # if/try/function/loop body, or any other shape not classified above)
    # is reported, never dropped.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _registrar_name(node.func) is not None \
                and id(node) not in handled_ids:
            found.append(_nested_declaration(node, stem, relpath))

    return tuple(found)


class TopologyError(Exception):
    """Fail-closed resolution failure. Message is operator-readable."""


class Topology:
    """Resolved declarations, queryable by op_kind."""

    def __init__(self, declarations: Tuple[Declaration, ...]):
        self.declarations = tuple(declarations)

    def unresolved(self) -> Tuple[Declaration, ...]:
        return tuple(d for d in self.declarations if d.unresolved_reason)

    def _find(self, role: str, op_kind: str) -> Declaration:
        hits = [d for d in self.declarations
                if d.role == role and d.op_kind == op_kind]
        if not hits:
            what = "a read-only reader" if role == "read_facade" else "an adapter"
            unresolved = self.unresolved()
            if unresolved:
                reasons = " / ".join(d.unresolved_reason for d in unresolved)
                raise TopologyError(
                    f"cannot tell whether anything in this project provides "
                    f"{what} for the operation '{op_kind}', because some "
                    f"files could not be fully read, so what they provide "
                    f"is unknown: {reasons}")
            raise TopologyError(
                f"nothing in this project provides {what} for the operation "
                f"'{op_kind}'. A module has to declare it by calling "
                f"register_{role}('{op_kind}', ...) at the top level.")
        stems = sorted({d.module_stem for d in hits})
        if len(stems) > 1:
            raise TopologyError(
                f"more than one module claims the operation '{op_kind}': "
                f"{', '.join(stems)}. Exactly one has to provide it -- refusing "
                "to guess which.")
        # Many-to-one (one module, one symbol, several op_kinds) is legitimate.
        return hits[0]

    def find_read_facade(self, op_kind: str) -> Declaration:
        return self._find("read_facade", op_kind)

    def find_adapter(self, op_kind: str) -> Declaration:
        return self._find("adapter", op_kind)


def build_topology(lib_dir) -> Topology:
    """Read every ``*.py`` in ``lib_dir`` and collect its declarations.

    AST-only: nothing here imports the modules it reads.
    """
    from pathlib import Path
    found: List[Declaration] = []
    for path in sorted(Path(lib_dir).glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            found.append(Declaration(
                role="unknown", module_stem=path.stem, relpath=path.name,
                op_kind=None, symbol=None,
                unresolved_reason=f"{path.name} could not be opened ({exc})"))
            continue
        found.extend(discover_declarations(source, path.name))
    return Topology(tuple(found))

# END SHARED CORE
