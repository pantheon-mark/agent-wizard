"""Legal (Task R7-T4 negative guard): ordinary `type(x)` / `.__class__` /
`.__dict__` / `.__mro__` / `.__module__` introspection idioms that are common
in unremarkable Python and must NOT be banned -- see scan.py's module
docstring for why these four dunders are disclosed, not closed (unlike
`__subclasses__`, which IS banned in the CAPABILITY zone). Must NOT be
flagged.
"""


def describe(x):
    return type(x).__name__


def is_same_type(a, b):
    return a.__class__ == b.__class__


def declared_fields(obj):
    return list(obj.__dict__.keys())


def mro_names(cls):
    return [c.__name__ for c in cls.__mro__]


def module_name(obj):
    return type(obj).__module__
