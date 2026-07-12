"""Bypass fixture (Task R8-T1): further function/method-object internals
that are pure reflection reach and never touched by ordinary capability
code -- `__code__` (the code object backing a function), `__closure__`
(captured free-variable cells), `__func__` / `__self__` (the underlying
function / bound instance behind a bound method). Each is a distinct
attribute reference that must be flagged `introspection_escape_hatch`, the
same discipline as `__subclasses__` -- these dunders have no benign-
collision risk with ordinary code the way `__class__`/`__dict__`/`__mro__`/
`__module__` do (see scan.py's module docstring for why those four stay
unbanned).
"""


def inspect_code(f):
    return f.__code__


def inspect_closure(f):
    return f.__closure__


def inspect_bound_func(m):
    return m.__func__


def inspect_bound_self(m):
    return m.__self__
