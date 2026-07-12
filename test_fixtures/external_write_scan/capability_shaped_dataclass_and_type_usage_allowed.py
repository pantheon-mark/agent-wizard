"""Legal (Task R8-T1 negative guard): the new function-introspection dunder
ban (`__globals__`/`__code__`/`__func__`/`__self__`/`__closure__`) must NOT
over-fire on ordinary emitted-capability-shaped code. This fixture combines
everything the ban must stay clean on in one place: importing the curated
`capability_api` surface, `type(x)` / `x.__class__` idioms, and a dataclass
-- none of these reference any of the newly-banned dunders or the new
adapter-registry symbols. Must NOT be flagged.
"""

from dataclasses import dataclass

from external_write.capability_api import run_operation


@dataclass
class RecordShape:
    op_kind: str
    payload: dict


def describe(x):
    return type(x).__name__


def same_type(a, b):
    return a.__class__ == b.__class__


def run_approved(op, receipt, client):
    return run_operation(op, receipt, client)
