"""Read-only facade + write-credential injection seam — the KEYSTONE
credential-isolation property (Task 4 — external-write-gate-generalization
slice; cross-vendor round-2 finding; hardened per a code-review finding that
live-reproduced three working bypasses of the class-definition-time-only
guard — see "Runtime enforcement" below).

The property this module exists to guarantee:

    Capability/proposal code must PHYSICALLY be unable to obtain a
    write-capable credential. It reads only through a read-only facade; the
    write credential is held only in the adapter execution path and injected
    per-effect by run_operation.

Two independent mechanisms implement that, and neither relies on scanning
source text for suspicious names (that heuristic is a DIFFERENT,
complementary mechanism — Task 5's job):

  1. ReadFacade — a deny-by-default method allowlist, enforced BOTH at
     class-definition time and at runtime (see "Runtime enforcement"
     below). A ReadFacade subclass declares its read methods in the
     `read_methods` class tuple; `__init_subclass__` refuses (raises
     TypeError) at class-DEFINITION time — i.e. at import, before a single
     instance exists — if the subclass defines any other public class
     attribute (callable or not — this also catches `property` objects,
     which are not `callable()`), or if the subclass overrides
     `__getattr__`/`__getattribute__`/`__setattr__` (which would otherwise
     let it re-open the attribute surface the runtime guard closes). There
     is no way to add a mutating method — or any other reachable attribute
     — to a ReadFacade subclass without it being refused; the guarantee is
     structural (every method must be deliberately declared), not a pattern
     match against verbs like "write"/"delete".

     Runtime enforcement: a class-definition-time-only check is not enough
     — instance state set in an overridden `__init__` (e.g.
     `self.client = read_only_client`) is invisible to `__init_subclass__`,
     which only inspects `vars(cls)` at class-definition time. So
     `ReadFacade.__getattribute__` ALSO enforces, on every attribute access
     against every instance, that only a declared `read_methods` name (or
     an underscore-prefixed/dunder internal) is reachable — any other name,
     however it was set, raises AttributeError. `ReadFacade.__setattr__`
     additionally refuses, at set-time, any attempt to set a non-
     underscore-prefixed instance attribute, so a smuggled public attribute
     never even makes it into instance state. Because subclasses cannot
     override any of these three hooks (forbidden above), this enforcement
     cannot be re-opened by a subclass.

  2. The credential-provider seam — `run_operation` (adapters.py) accepts an
     optional `write_credential_provider` and calls it itself, INSIDE the
     adapter-dispatch execution path, to obtain the write-capable raw client
     passed to `adapter.apply_one(raw_client, unit)`. Capability/proposal
     code that builds an Operation and holds a ReadFacade never receives
     that provider and never sees the credential it returns.

Vendor eligibility: an op_kind may only use this safety model if its
contract declares a `read_only_scope` (contracts.OperationContract). An
op_kind with no declared read-only scope is refused fail-closed
(ReadFacadeEligibilityError) — build-time refusal, never a silent
downgrade to "read facade not required here".

T4/T7 boundary: the concrete Gmail read facade + real OAuth scopes
(gmail.readonly vs gmail.modify) are Task 7. This module is generic and is
proven against a fixture read-only client + a fixture write-credential
provider — never against Gmail specifics.

Enforcement ceiling: build-time + operator-as-approver, NOT a runtime/OS
guarantee (same ceiling as proof_hash.py / contracts.py / effects_manifest.py).

Stdlib only — no third-party dependencies.
"""

import inspect
from typing import Any, Optional, Tuple

from external_write.contracts import get_contract

# The three attribute-access hooks a subclass could use to re-open the
# runtime allowlist enforced by ReadFacade.__getattribute__ / __setattr__
# below. Forbidding subclasses from defining any of these is what makes the
# runtime enforcement un-defeatable from a subclass.
_FORBIDDEN_ACCESS_HOOKS = ("__getattr__", "__getattribute__", "__setattr__")


class ReadFacadeEligibilityError(Exception):
    """Raised when an op_kind has no declared read_only_scope — ineligible
    for the ReadFacade credential-isolation safety model. Fail-closed: raised
    BEFORE any ReadFacade is constructed, never after."""


class ReadFacade:
    """Base class for a read-only facade wrapping a read-only-scoped client.

    Subclasses declare EVERY public attribute they expose in the class-level
    `read_methods` tuple. `__init_subclass__` enforces — at class-definition
    time, so a bad subclass fails to even import — that no OTHER public
    class attribute is defined on the subclass (callable or not — this also
    catches non-callable objects like `property`), and that the subclass
    does not override `__getattr__`/`__getattribute__`/`__setattr__`. This
    is a deny-by-default allowlist: nothing reaches a ReadFacade's public
    surface without being deliberately declared safe. It is not a
    name-pattern scan for mutating verbs.

    That class-definition-time check alone is not sufficient — instance
    state set in an overridden `__init__` is invisible to it. So this class
    ALSO enforces the allowlist at runtime, on every instance, via
    `__getattribute__` (only a declared `read_methods` name, or an
    underscore-prefixed/dunder internal, is reachable from outside) and
    `__setattr__` (no non-underscore-prefixed instance attribute can be set
    at all). Subclasses cannot override either hook to re-open this.

    A conforming subclass implements its declared read methods via `_read`,
    which dispatches to the wrapped read-only client:

        class MyReadFacade(ReadFacade):
            read_methods = ("list_items",)

            def list_items(self):
                return self._read("list_items")

    `ReadFacade` itself declares zero read methods and therefore exposes
    zero public methods — it is not usable directly except as a base class.
    """

    read_methods: Tuple[str, ...] = ()

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        declared = set(cls.read_methods)
        class_vars = vars(cls)

        for hook_name in _FORBIDDEN_ACCESS_HOOKS:
            if hook_name in class_vars:
                raise TypeError(
                    f"{cls.__name__} may not define {hook_name} — overriding "
                    "one of ReadFacade's attribute-access hooks "
                    f"{_FORBIDDEN_ACCESS_HOOKS!r} would let a subclass "
                    "re-open attribute access that ReadFacade's runtime "
                    "allowlist deliberately closes, defeating the "
                    "credential-isolation guarantee this class exists to "
                    "provide."
                )

        for name, value in class_vars.items():
            if name == "read_methods":
                continue
            if name.startswith("_"):
                # Private/dunder/protected names (other than the forbidden
                # access hooks checked above) are never part of the public
                # read-method surface being policed here.
                continue
            if name not in declared:
                raise TypeError(
                    f"{cls.__name__}.{name} is a public attribute that is not "
                    f"listed in {cls.__name__}.read_methods {tuple(sorted(declared))!r}. "
                    "A ReadFacade subclass may not define ANY public "
                    "attribute — callable or not, which also catches "
                    "property objects standing in for a method — that is "
                    "not explicitly declared as a read method. This is a "
                    "deny-by-default allowlist, refused at class-definition "
                    "time (build-time refusal), not a runtime name-pattern "
                    "scan."
                )
            if not inspect.isfunction(value):
                raise TypeError(
                    f"{cls.__name__}.{name} is declared in read_methods but "
                    "is not a plain method — it is "
                    f"{type(value).__name__!r}. A declared read method must "
                    "be implemented as a plain method (e.g. via `def`), not "
                    "a property or other descriptor that could return "
                    "something other than the result of a genuine method "
                    "call (such as the wrapped client itself)."
                )

    def __init__(self, read_only_client: Any):
        self._read_only_client = read_only_client

    def __getattribute__(self, name: str) -> Any:
        # Underscore-prefixed/dunder names are internal machinery (this
        # base class's own `_read_only_client`/`_read`, plus whatever
        # `object` itself needs) and are never part of the externally
        # reachable public surface being policed here.
        if name.startswith("_") or name == "read_methods":
            return object.__getattribute__(self, name)
        read_methods = object.__getattribute__(self, "read_methods")
        if name in read_methods:
            return object.__getattribute__(self, name)
        raise AttributeError(
            f"{type(self).__name__!r} object has no externally reachable "
            f"attribute {name!r} — only its declared read_methods "
            f"{tuple(read_methods)!r} (plus internal/private state) are "
            "reachable from outside a ReadFacade instance. This is enforced "
            "at runtime, not just at class-definition time."
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if not name.startswith("_"):
            raise AttributeError(
                f"{type(self).__name__} may not set the public instance "
                f"attribute {name!r} — a ReadFacade instance's only "
                "externally reachable state is its declared read methods; "
                "smuggling a client (or anything else) onto a public "
                "instance attribute is refused at set-time, not just "
                "detected afterward."
            )
        object.__setattr__(self, name, value)

    def _read(self, method_name: str, *args, **kwargs) -> Any:
        """Dispatch a declared read method's implementation to the wrapped
        read-only client. Subclasses use this so they never need to store or
        re-expose the raw client themselves."""
        method = getattr(self._read_only_client, method_name)
        return method(*args, **kwargs)


def get_read_only_scope(op_kind: str) -> Optional[str]:
    """Return op_kind's declared read_only_scope, or None if it has no
    contract or has not declared one."""
    c = get_contract(op_kind)
    if c is None:
        return None
    return c.read_only_scope


def require_read_only_scope(op_kind: str) -> str:
    """Fail-closed vendor-eligibility check (acceptance criterion c): return
    op_kind's declared read_only_scope, or raise ReadFacadeEligibilityError
    if op_kind has no contract or has not declared one. An op_kind that has
    never declared a read-only scope is INELIGIBLE for the ReadFacade
    credential-isolation safety model — this is a build-time refusal, not a
    warning."""
    c = get_contract(op_kind)
    if c is None:
        raise ReadFacadeEligibilityError(
            f"operation kind {op_kind!r} has no registered contract — "
            "cannot determine read-only-scope eligibility"
        )
    if not c.read_only_scope:
        raise ReadFacadeEligibilityError(
            f"operation kind {op_kind!r} has no declared read_only_scope — "
            "ineligible for the ReadFacade credential-isolation safety model "
            "(contracts.OperationContract.read_only_scope is None/empty)"
        )
    return c.read_only_scope


def build_read_facade(op_kind: str, read_only_client: Any,
                       facade_cls: Optional[type] = None) -> ReadFacade:
    """Build a ReadFacade for op_kind, refusing fail-closed if op_kind has no
    declared read_only_scope (require_read_only_scope). `read_only_client`
    must already be scoped read-only by its caller (the real vendor-specific
    scoping — e.g. requesting gmail.readonly rather than gmail.modify — is
    Task 7's concern; this function only enforces that a scope was
    DECLARED, it cannot verify the client object it is handed actually holds
    a read-only-scoped credential).

    facade_cls defaults to the bare ReadFacade base class (read_methods=());
    callers building a real facade pass their own ReadFacade subclass.
    """
    require_read_only_scope(op_kind)
    cls = facade_cls if facade_cls is not None else ReadFacade
    return cls(read_only_client)
