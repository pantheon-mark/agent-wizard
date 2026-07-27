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
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from adapter_migrations import MigrationContext, TransformResult
from capability_code_scaffold import (
    has_register_adapter_call, resolve_registered_adapter_classes,
)

PROVISIONER_NAME = "build_read_only_client"


def _atomic_write(path: Path, text: str) -> None:
    """Temp file + fsync + ``os.replace``, preserving the destination's mode.

    Mirrors the engine's own writer exactly rather than introducing a second,
    weaker write path for the same class of file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    preserved_mode = path.stat().st_mode if path.exists() else None
    fd, tmp = tempfile.mkstemp(prefix=".provisioner.", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    if preserved_mode is not None:
        try:
            os.chmod(str(path), preserved_mode)
        except OSError:
            pass


@dataclass(frozen=True)
class MigrationResult:
    """Outcome for ONE adapter module."""

    path: str
    migrated: bool
    reason: str


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


def plan_provisioner_migration(source: str,
                               context: "MigrationContext | None" = None) -> TransformResult:
    """Move a module-level ``build_read_only_client()`` onto the adapter class
    that is actually registered, and return the replacement source.

    PURE: no filesystem access, so the engine can compose this with other
    migrations on one in-memory copy of the module and write once.

    Refuses -- returning the source unchanged with a plain-language reason --
    when the module cannot be parsed, has no module-level provisioner, makes no
    ``register_adapter(...)`` call, resolves to anything other than exactly one
    registered class, already defines the method on that class, or when the
    rewrite would not have parsed. It never rewrites a file it does not fully
    understand.
    """
    del context  # this migration needs nothing beyond the source text
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return TransformResult(source, False,
                               "could not be parsed, so it was left untouched")

    func = _module_level_provisioner(tree)
    if func is None:
        return TransformResult(
            source, False,
            "no module-level read-client builder -- nothing to do",
            benign=True)

    if not has_register_adapter_call(tree):
        return TransformResult(
            source, False,
            "this module registers no adapter with register_adapter(...), so "
            "there is no class to move the read-client builder onto -- left "
            "untouched")

    resolved, ambiguous_count = resolve_registered_adapter_classes(tree)
    if ambiguous_count or len(resolved) != 1:
        return TransformResult(
            source, False,
            f"expected exactly one registered adapter class, found "
            f"{len(resolved) + ambiguous_count} -- left untouched; the "
            "read-client builder has to be moved onto the right adapter class "
            "by someone who knows which one it belongs to")

    class_name = next(iter(resolved))
    if _class_defines(tree, class_name, PROVISIONER_NAME):
        # Benign: the target class already carries the read-client builder --
        # exactly the shape an operator produces by hand-applying this same
        # migration's own remediation guidance, which leaves the now-redundant
        # module-level function behind. That is a correctly-finished project,
        # not a refusal a human still owes work on.
        return TransformResult(
            source, False,
            f"{class_name} already defines {PROVISIONER_NAME} -- left untouched "
            "(never shadow a working method)",
            benign=True)

    cls = _class_node(tree, class_name)
    if cls is None or not getattr(cls, "end_lineno", None):
        return TransformResult(
            source, False,
            f"could not locate the body of {class_name} -- left untouched")

    lines = source.splitlines(keepends=True)
    start = min([d.lineno for d in func.decorator_list] + [func.lineno]) - 1
    end = func.end_lineno
    body_src = "".join(lines[start:end])

    reindented = []
    for line in body_src.splitlines():
        reindented.append(("    " + line) if line.strip() else line)
    method_src = "\n".join(reindented)
    method_src = method_src.replace(
        f"def {PROVISIONER_NAME}()", f"def {PROVISIONER_NAME}(self, op)", 1)
    method_src = method_src.replace(
        f"def {PROVISIONER_NAME}() ->", f"def {PROVISIONER_NAME}(self, op) ->", 1)

    remaining = lines[:start] + lines[end:]
    insert_at = cls.end_lineno - (end - start if end <= cls.end_lineno else 0)
    migrated = "".join(
        remaining[:insert_at]
        + ["\n", method_src.rstrip("\n") + "\n"]
        + remaining[insert_at:]
    )

    try:
        new_tree = ast.parse(migrated)
    except SyntaxError:
        return TransformResult(
            source, False,
            "the rewrite would not have parsed, so nothing was changed")
    if not _class_defines(new_tree, class_name, PROVISIONER_NAME):
        return TransformResult(
            source, False,
            "the rewrite did not land the method on the adapter class, so "
            "nothing was changed")
    if _module_level_provisioner(new_tree) is not None:
        return TransformResult(
            source, False,
            "the module-level function survived the rewrite, so nothing was "
            "changed")

    return TransformResult(migrated, True,
                           f"moved {PROVISIONER_NAME} onto {class_name}")


def migrate_module_level_provisioner(path: Path) -> MigrationResult:
    """Apply :func:`plan_provisioner_migration` to ONE adapter module on disk.

    The upgrade engine does NOT use this -- it composes the pure transform with
    every other adapter migration and writes once (see ``adapter_migrations``).
    This wrapper is the standalone single-module path. It writes atomically:
    a plain ``write_text`` here would leave a truncated adapter module behind if
    the process died mid-write, which for the one file holding an operator's
    external-write credentials is not an acceptable failure mode.
    """
    path = Path(path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return MigrationResult(str(path), False,
                               f"could not be read ({exc.__class__.__name__})")
    result = plan_provisioner_migration(source)
    if not result.changed:
        return MigrationResult(str(path), False, result.reason)
    _atomic_write(path, result.source)
    return MigrationResult(str(path), True, result.reason)
