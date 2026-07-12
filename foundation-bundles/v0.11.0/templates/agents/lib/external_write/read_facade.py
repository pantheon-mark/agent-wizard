"""Read-only facade + write-credential injection seam — the KEYSTONE
credential-isolation property (Task 4 — external-write-gate-generalization
slice; cross-vendor round-2 finding; hardened per a code-review finding that
live-reproduced three working bypasses of the class-definition-time-only
guard — see "Runtime enforcement" below; hardened AGAIN per a re-review that
live-reproduced a fourth bypass, requiring no subclassing at all — see
"Client storage" below; hardened AGAIN (R4, carried defense-in-depth finding)
per a novel single-underscore re-stash residual and to make the docstrings
here stop overclaiming — see "Runtime enforcement" and "Disclosed residual
bypasses" below).

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
     against every instance, a FIXED allowlist (R4 — not a blanket
     underscore passthrough): dunders (`__class__`, `__weakref__`,
     `__hash__`, `__eq__`, and the rest of Python/object machinery), a
     fixed internal set (`read_methods`, `_read`), and declared
     `read_methods` names. Any other name — including a NOVEL
     single-underscore instance attribute a subclass method might stash
     (e.g. `self._stash = X`), however it was set — raises AttributeError.
     `ReadFacade.__setattr__` is symmetrically tightened: it refuses, at
     set-time, any attempt to set an instance attribute other than a
     dunder (public OR a novel single-underscore name alike), so a smuggled
     value never even makes it into instance state in the first place —
     nothing in ReadFacade legitimately sets an instance attribute at all.
     Because subclasses cannot override any of these three hooks (forbidden
     above), a subclass cannot re-open this runtime allowlist through
     normal attribute access.

     Disclosed residual bypasses (honesty over overclaim — these are NOT
     closed by the above, and this module does not claim they are): (a)
     code that imports the module-private `_WRAPPED_CLIENTS` directly can
     still read the wrapped read-only client out of it — the runtime
     allowlist governs attribute access on a ReadFacade INSTANCE, not
     access to this module's own private state; (b) code that calls
     `object.__getattribute__(self, name)` (or otherwise reaches into
     object machinery beneath the class hook, e.g. via `self.__dict__` —
     empty though it always is — or `inspect`/`ctypes`-level introspection)
     bypasses `ReadFacade.__getattribute__` entirely, because it never goes
     through the instance's own `__getattribute__` call. Both of these are
     OUTSIDE the deterministic guarantee this class provides and INSIDE
     this module's actual enforcement ceiling — build-time + operator-as-
     approver, not runtime/OS (see "Enforcement ceiling" below). Ordinary
     capability/proposal code has no reason to do either, and scan.py's
     static rules (Task 5) are the complementary mechanism that polices
     source text for that kind of reach-in; this class's guarantee is that
     NORMAL attribute access — `facade.<name>` / `getattr(facade, name)` —
     cannot reach the wrapped client, not that no Python code anywhere ever
     could by deliberately reaching beneath the language's own attribute
     protocol.

     Client storage: the runtime allowlist above is necessary but was not
     sufficient — the base class itself used to store the wrapped client as
     a plain instance attribute (`self._read_only_client`), and
     `__getattribute__`'s underscore passthrough (needed for legitimate
     internal/dunder access) returned it to ANY caller who accessed
     `facade._read_only_client` — no subclassing or trickery required. The
     wrapped client is therefore never assigned to an instance attribute at
     all: `__init__` stores it in `_WRAPPED_CLIENTS`, a module-private
     `weakref.WeakKeyDictionary` keyed by the facade instance, and `_read`
     looks it up there instead. There is consequently no attribute name —
     guessed, underscore-prefixed, or otherwise — that any attribute access
     on a ReadFacade instance can resolve to the wrapped client.

  2. The credential-provider seam — `run_operation` (adapters.py) resolves the
     write-capable raw client INTERNALLY, keyed by the registered adapter: when
     an adapter self-provisions (defines `build_write_client(op)`), the adapter
     execution path calls it itself, INSIDE that path, to obtain the raw client
     passed to `adapter.apply_one(raw_client, unit)`. `run_operation` takes NO
     caller-supplied provider (BL-1 / F-33): capability/proposal code that
     builds an Operation and holds a ReadFacade cannot even NAME a credential
     provider (enforced deterministically by scan.py's
     credential_provider_reference rule), let alone pass one in or see the
     credential it returns.

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
import weakref
from typing import Any, Optional, Tuple

from external_write.contracts import get_contract

# The three attribute-access hooks a subclass could use to re-open the
# runtime allowlist enforced by ReadFacade.__getattribute__ / __setattr__
# below. Forbidding subclasses from defining any of these is what makes the
# runtime enforcement un-defeatable from a subclass.
_FORBIDDEN_ACCESS_HOOKS = ("__getattr__", "__getattribute__", "__setattr__")

# The wrapped read-only client, keyed by facade instance. This is
# deliberately NOT an instance attribute — it is module-private state that
# no attribute access on a ReadFacade instance can name or resolve to. See
# "Client storage" in the module docstring.
_WRAPPED_CLIENTS: "weakref.WeakKeyDictionary[ReadFacade, Any]" = weakref.WeakKeyDictionary()

# The FIXED internal allowlist for ReadFacade.__getattribute__ (R4): names
# other than dunders and declared read_methods entries that legitimately
# need to be reachable via `self.<name>` from inside a ReadFacade subclass's
# own methods. `read_methods` is the class-level declaration tuple itself;
# `_read` is the dispatch method every declared read method calls. Nothing
# else — including any NOVEL single-underscore name a subclass might stash
# on an instance — is reachable through this hook. See the module/class
# docstrings' "Runtime enforcement" sections for what this closes and what
# it deliberately does not (residual bypasses are disclosed there, not
# hidden).
_INTERNAL_ALLOWLIST = frozenset({"read_methods", "_read"})


def _is_dunder(name: str) -> bool:
    """True for names of the form `__x__` — Python/object machinery
    (`__class__`, `__weakref__`, `__hash__`, `__eq__`, `__repr__`, etc.)
    that ReadFacade's runtime allowlist must never deny, or ordinary object
    behavior (hashing, weakref-keying, repr, equality) would break."""
    return name.startswith("__") and name.endswith("__")


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
    ALSO enforces a FIXED allowlist at runtime, on every instance, via
    `__getattribute__` (R4: not a blanket underscore passthrough — only
    dunders, a fixed internal set {`read_methods`, `_read`}, and a declared
    `read_methods` name are reachable from outside; a NOVEL
    single-underscore instance attribute, however it got set, is denied)
    and `__setattr__` (no instance attribute other than a dunder can be set
    at all — public or single-underscore alike). Subclasses cannot override
    either hook to re-open this through normal attribute access.

    The wrapped client itself is never stored as an instance attribute at
    all — not even an underscore-prefixed one. `__init__` keeps it in a
    module-private `weakref.WeakKeyDictionary` keyed by instance, so there
    is no attribute name whatsoever (guessed or otherwise) that resolves to
    it from outside via normal attribute access.

    Disclosed residual (honesty over overclaim — NOT closed here, and not
    claimed to be): code that imports this module's private
    `_WRAPPED_CLIENTS` directly, or that calls
    `object.__getattribute__(self, name)` / otherwise reaches beneath the
    class's own `__getattribute__`, bypasses the runtime allowlist above —
    those are not `facade.<name>` / `getattr(facade, name)` attribute
    access, so this class's hook never runs. That residual sits outside
    this class's deterministic guarantee, inside this module's actual
    enforcement ceiling (build-time + operator-as-approver, not runtime/OS
    — see the module docstring's "Enforcement ceiling"). What IS guaranteed
    here: ordinary attribute access on a ReadFacade instance cannot reach
    the wrapped client. The value protected by this class is the READ-ONLY
    client specifically — the write-capable credential is a separate
    object this class never even sees, isolated by the credential-provider
    seam (mechanism 2 in the module docstring), not by anything in this
    class.

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
        # Deliberately NOT `self._read_only_client = read_only_client` — see
        # "Client storage" in the module docstring. The client is held in
        # module-private closure/weak-reference state, never as an instance
        # attribute, so no attribute access (of any name) can return it.
        _WRAPPED_CLIENTS[self] = read_only_client

    def __getattribute__(self, name: str) -> Any:
        # R4: a FIXED allowlist, not a blanket underscore passthrough —
        # dunders (object/Python machinery: __class__, __weakref__,
        # __hash__, __eq__, ...), the fixed internal set {read_methods,
        # _read}, and declared read_methods names. Any OTHER name —
        # including a NOVEL single-underscore instance attribute a subclass
        # might stash (e.g. `self._stash = X` in an overridden method) — is
        # denied. Note the wrapped client is never reachable through any of
        # this regardless of name, because it is never stored as an
        # instance attribute in the first place (see __init__).
        if _is_dunder(name) or name in _INTERNAL_ALLOWLIST:
            return object.__getattribute__(self, name)
        read_methods = object.__getattribute__(self, "read_methods")
        if name in read_methods:
            return object.__getattribute__(self, name)
        raise AttributeError(
            f"{type(self).__name__!r} object has no externally reachable "
            f"attribute {name!r} — only its declared read_methods "
            f"{tuple(read_methods)!r} (plus a fixed internal allowlist of "
            f"{tuple(sorted(_INTERNAL_ALLOWLIST))!r} and dunders) are "
            "reachable on a ReadFacade instance. This is enforced at "
            "runtime, not just at class-definition time, and denies any "
            "novel single-underscore name — not only undeclared public "
            "names."
        )

    def __setattr__(self, name: str, value: Any) -> None:
        # R4: symmetric tightening — dunder slot machinery aside, nothing
        # in ReadFacade legitimately sets an instance attribute at all
        # (__init__ stores the wrapped client in the module-private
        # _WRAPPED_CLIENTS, never as `self.<anything>`). So every non-dunder
        # set is refused at set-time, public OR a novel single-underscore
        # name alike — there is no attribute name a smuggled value could be
        # stashed under in the first place.
        if _is_dunder(name):
            object.__setattr__(self, name, value)
            return
        raise AttributeError(
            f"{type(self).__name__} may not set the instance attribute "
            f"{name!r} — a ReadFacade instance sets no instance attribute "
            "of any name (public or underscore-prefixed); its only "
            "externally reachable state is its declared read methods, and "
            "the wrapped client lives in module-private state, never on "
            "the instance. Smuggling anything onto instance state is "
            "refused at set-time, not just detected afterward."
        )

    def _read(self, method_name: str, *args, **kwargs) -> Any:
        """Dispatch a declared read method's implementation to the wrapped
        read-only client. Subclasses use this so they never need to store or
        re-expose the raw client themselves. Looks the client up in the
        module-private `_WRAPPED_CLIENTS` store — see __init__ — never via a
        `self.<something>` instance attribute."""
        client = _WRAPPED_CLIENTS[self]
        method = getattr(client, method_name)
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
