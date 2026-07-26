"""Deterministic migrator: module-level ``build_read_only_client()`` -> adapter
CLASS method (Cut 1.6 / Task 4, F-STEP0-1).

The defect
----------
``adapter_registry.py`` captures the read-client provisioner with
``getattr(cls, "build_read_only_client", None)`` -- a CLASS-attribute lookup --
and documents the contract as ``build_read_only_client(self, op)``. But every
emitter that ever existed produced a MODULE-LEVEL, zero-argument
``build_read_only_client()``, so ``AdapterDispatch.provision_read_only_client``
was ``None`` in 100% of deployments and the kernel branch consuming it had never
once executed. Verified 2026-07-25 against the scaffold template, both live
estate adapters, and the reference adapter (which defines neither, by design --
it is a demo adapter relying on caller-supplied clients).

A1, NOT a dual-shape fallback
-----------------------------
Both cross-vendor advisors independently rejected a class-then-module runtime
fallback: it would institutionalise a FOURTH consecutive incidental-inference
defect in this project (stem-keying -> relpath-keying -> an unpopulated getattr
hook -> "try the class, then infer a module-level function by module name").
The documented class-method contract is the ONLY runtime shape. Existing
adapters are MIGRATED here, deterministically, at build time -- never
accommodated by a silent runtime guess.

What this does
--------------
Reuses the registration-aware-migrator discipline: ONE shared AST resolver drives detection and
duplicate-safe insertion, keyed on the class actually passed to
``register_adapter(...)`` -- never "the first ClassDef in the file", which is the
same incidental-structure inference the F-1 finding closed.

Refuses (never guesses) when the target class cannot be resolved, when the class
already defines the method, or when the module-level function is absent. A
refusal returns a plain-language reason for the operator; it never rewrites a
file it does not fully understand and never emits a passing stub.

Stdlib only. Build-side toolkit code -- ships via ``wizard self-update``, never
into the operator project's emitted lib.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

PROVISIONER_NAME = "build_read_only_client"


@dataclass(frozen=True)
class MigrationResult:
    """Outcome for ONE adapter module."""

    path: str
    migrated: bool
    reason: str


def resolve_registered_adapter_classes(tree: ast.AST) -> List[str]:
    """Names of the classes actually passed to ``register_adapter(...)`` at
    module scope -- e.g. ``register_adapter(OP_KIND, InboxAdapter())`` yields
    ``["InboxAdapter"]``.

    Keyed on real registration, NOT on ClassDef order (inferring
    the target from incidental structure is the defect class this project keeps
    re-finding). A registration whose argument is not a plain ``Name()`` call is
    deliberately not resolved -- the caller then refuses rather than guessing."""
    names: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if fname != "register_adapter":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                if arg.func.id not in names:
                    names.append(arg.func.id)
    return names


def _module_level_provisioner(tree: ast.AST) -> Optional[ast.FunctionDef]:
    """The module-level ``def build_read_only_client(...)``, if present. Only
    module scope -- a method of the same name inside a class is the TARGET
    shape, not the thing being migrated."""
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.FunctionDef) and node.name == PROVISIONER_NAME:
            return node
    return None


def _class_defines(tree: ast.AST, class_name: str, method_name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return any(isinstance(b, ast.FunctionDef) and b.name == method_name
                       for b in node.body)
    return False


def _class_node(tree: ast.AST, class_name: str) -> Optional[ast.ClassDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def migrate_module_level_provisioner(path: Path) -> MigrationResult:
    """Rewrite ONE adapter module's module-level ``build_read_only_client()``
    into a method on its registered adapter class.

    Idempotent: a module already carrying the method (and no module-level
    function) reports ``migrated=False`` with a "nothing to do" reason rather
    than duplicating anything."""
    path = Path(path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return MigrationResult(str(path), False,
                               f"could not be read ({exc.__class__.__name__})")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return MigrationResult(str(path), False,
                               "could not be parsed, so it was left untouched")

    func = _module_level_provisioner(tree)
    if func is None:
        return MigrationResult(str(path), False,
                               "no module-level build_read_only_client -- nothing to do")

    classes = resolve_registered_adapter_classes(tree)
    if len(classes) != 1:
        return MigrationResult(
            str(path), False,
            f"expected exactly one registered adapter class, found {len(classes)} "
            "-- left untouched; move the read-client builder onto the right "
            "adapter class by hand")

    class_name = classes[0]
    if _class_defines(tree, class_name, PROVISIONER_NAME):
        return MigrationResult(
            str(path), False,
            f"{class_name} already defines {PROVISIONER_NAME} -- left untouched "
            "(never shadow a working method)")

    cls = _class_node(tree, class_name)
    if cls is None or not getattr(cls, "end_lineno", None):
        return MigrationResult(str(path), False,
                               f"could not locate the body of {class_name} -- left untouched")

    lines = source.splitlines(keepends=True)

    # Excise the module-level function (including any decorators above it).
    start = min([d.lineno for d in func.decorator_list] + [func.lineno]) - 1
    end = func.end_lineno            # inclusive 1-based -> exclusive 0-based
    body_src = "".join(lines[start:end])

    # Re-indent one level and give it the documented (self, op) signature.
    reindented = []
    for line in body_src.splitlines():
        reindented.append(("    " + line) if line.strip() else line)
    method_src = "\n".join(reindented)
    method_src = method_src.replace(
        f"def {PROVISIONER_NAME}()", f"def {PROVISIONER_NAME}(self, op)", 1)
    method_src = method_src.replace(
        f"def {PROVISIONER_NAME}() ->", f"def {PROVISIONER_NAME}(self, op) ->", 1)

    remaining = lines[:start] + lines[end:]
    # The class end line shifts if the excised function sat above it.
    insert_at = cls.end_lineno - (end - start if end <= cls.end_lineno else 0)

    migrated_lines = (
        remaining[:insert_at]
        + ["\n", method_src.rstrip("\n") + "\n"]
        + remaining[insert_at:]
    )
    migrated = "".join(migrated_lines)

    try:
        new_tree = ast.parse(migrated)
    except SyntaxError:
        return MigrationResult(
            str(path), False,
            "the rewrite would not have parsed, so nothing was changed")
    if not _class_defines(new_tree, class_name, PROVISIONER_NAME):
        return MigrationResult(
            str(path), False,
            "the rewrite did not land the method on the adapter class, so nothing was changed")
    if _module_level_provisioner(new_tree) is not None:
        return MigrationResult(
            str(path), False,
            "the module-level function survived the rewrite, so nothing was changed")

    path.write_text(migrated, encoding="utf-8")
    return MigrationResult(str(path), True,
                           f"moved {PROVISIONER_NAME} onto {class_name}")
