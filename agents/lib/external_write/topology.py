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

An unresolvable declaration is REPORTED with a named reason, never skipped.
A silent skip is how the read-facade defect stayed hidden.
"""

import ast
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

#: Registration functions this module understands, mapped to their role.
_REGISTRARS = {
    "register_adapter": "adapter",
    "register_read_facade": "read_facade",
}


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


def _symbol_name(node: ast.AST) -> Optional[str]:
    """Class name from ``Cls`` or ``Cls()``; None if not a plain name."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _registrar_call(node: ast.AST) -> Optional[ast.Call]:
    """The ``register_*`` Call in an expression statement, if any."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return None
    call = node.value
    func = call.func
    name = func.id if isinstance(func, ast.Name) else (
        func.attr if isinstance(func, ast.Attribute) else None)
    if name in _REGISTRARS and len(call.args) >= 2:
        return call
    return None


def _registrar_role(call: ast.Call) -> str:
    func = call.func
    name = func.id if isinstance(func, ast.Name) else func.attr
    return _REGISTRARS[name]


def discover_declarations(source: str, relpath: str) -> Tuple[Declaration, ...]:
    """Every ``register_adapter`` / ``register_read_facade`` declaration in
    ``source``, resolved to concrete op_kinds where the shape allows.

    Handles three shapes, which together cover every module the wizard emits
    and every operator module observed in the field:
      1. ``register_x("literal", Cls)``
      2. ``register_x(MODULE_CONST, Cls)`` -- folded from module-level strings
      3. ``for v in (A, B, C): register_x(v, Cls)`` -- the shipped Gmail shape

    Any other shape yields a Declaration with ``op_kind=None`` and a
    plain-language ``unresolved_reason`` naming the file. It is never dropped.
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
    found: List[Declaration] = []

    def _emit(call: ast.Call, op_node: ast.AST) -> None:
        role = _registrar_role(call)
        symbol = _symbol_name(call.args[1])
        op_kind: Optional[str] = None
        if isinstance(op_node, ast.Constant) and isinstance(op_node.value, str):
            op_kind = op_node.value
        elif isinstance(op_node, ast.Name) and op_node.id in consts:
            op_kind = consts[op_node.id]
        if op_kind is None:
            found.append(Declaration(
                role=role, module_stem=stem, relpath=relpath, op_kind=None,
                symbol=symbol,
                unresolved_reason=(
                    f"{relpath} registers something on line {call.lineno} but the "
                    "operation name is not written in a form this check can read "
                    "(expected a plain text name, or a name defined at the top of "
                    "the same file)"),
            ))
        else:
            found.append(Declaration(
                role=role, module_stem=stem, relpath=relpath, op_kind=op_kind,
                symbol=symbol, unresolved_reason=None))

    for node in tree.body:
        call = _registrar_call(node)
        if call is not None:
            _emit(call, call.args[0])
            continue
        # Shape 3: a loop over a tuple/list of names or literals.
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) \
                and isinstance(node.iter, (ast.Tuple, ast.List)):
            loop_var = node.target.id
            for body_node in node.body:
                inner = _registrar_call(body_node)
                if inner is None:
                    continue
                arg0 = inner.args[0]
                if isinstance(arg0, ast.Name) and arg0.id == loop_var:
                    for element in node.iter.elts:
                        _emit(inner, element)
                else:
                    _emit(inner, arg0)

    return tuple(found)
