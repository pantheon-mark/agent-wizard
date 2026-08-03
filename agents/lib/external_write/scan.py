"""Deterministic AST bypass scanner — the build-time root-of-trust.

Every external write in a wizard-generated operator system must route through
the emitted named-operation adapters in the external_write package. This module
is the deterministic, build-time check that FAILS THE BUILD if any other script
mutates an external surface OUTSIDE those adapters.

It is the real enforcement. The runtime PreToolUse hook is a disclosed backstop
only: it classifies by command shape and is structurally blind to per-project
interpreter-script writes. A grep is trivially defeated (helper indirection,
dynamic import, subprocess curl). This gate is therefore deliberately
deterministic AST + call-graph analysis, NOT grep and NOT LLM judgment.
Treat every bypass below as adversarial: assume a
script author (or a confused agent) is trying to reach an external surface
without going through the adapter, and catch it.

Stdlib only (``ast``); no third-party dependencies.

------------------------------------------------------------------------------
Bypass classes CAUGHT at v0
------------------------------------------------------------------------------
  forbidden_import    -- importing a network / external-write client
                         (requests, urllib, http.client, googleapiclient,
                         gspread, httpx, aiohttp, boto3, psycopg2, pycurl, ...)
                         anywhere outside the ADAPTER_PROFILE zone (see
                         "Trust zones" below). Both ``import x`` and
                         ``from x import y`` forms; submodules
                         (urllib.request) match the banned top-level package.
  direct_api_call     -- referencing a known external-surface mutation method
                         by name (values().update, batchUpdate, append,
                         update_cells, ...; and Gmail's
                         trash/untrash on name alone, and modify/send/create/
                         delete gated on a Gmail surface handle -- messages/
                         drafts/threads/labels/filters/settings/users -- in the
                         attribute chain, mirroring the Sheets ambiguous-verb
                         design; see ``_check_surface_mutation``). Caught
                         whether the mutation verb is the immediate func of a
                         Call OR merely loaded as an attribute and called
                         indirectly (``fn = svc...update; fn(...)``). Caught
                         wherever it appears, including inside a local helper
                         function (so helper indirection is covered: the
                         forbidden reference inside the helper is itself
                         reported).
  dynamic_import      -- importlib.import_module('requests') / __import__(...)
                         with a banned literal module name (defeats static
                         ``import`` detection).
  subprocess_network  -- subprocess.run/Popen/call/... or os.system / os.popen
                         whose command invokes a network tool (curl, wget,
                         http, httpie, ...). Detected from list/str literal
                         arguments.
  credential_construction -- obtaining or widening a write-capable credential:
                         constructing/loading one via a curated set of factory
                         names (``Credentials``/``ServiceAccountCredentials``
                         construction, ``from_service_account_file``,
                         ``from_service_account_info``,
                         ``from_authorized_user_file``,
                         ``from_authorized_user_info``) or widening an
                         existing credential's authority (``.with_subject(...)``
                         domain-wide-delegation impersonation). Flagged
                         anywhere outside the ADAPTER_PROFILE zone, regardless
                         of whether the vendor SDK was itself imported in this
                         file (see "Trust zones" below). The symbol
                         set is CURATED, not exhaustive (a known, tracked
                         limitation) -- the same disclosed-bound spirit as
                         ``_FORBIDDEN_IMPORT_ROOTS``. Two further evasions of
                         this curated symbol check are disclosed, not closed
                         (same "no silent caps" spirit as the
                         ``build_write_client`` getattr bound documented under
                         ``credential_provider_reference`` below): (i) a
                         string-literal ``getattr(creds, "with_subject")(user)``
                         resolves a curated factory/authority method via a
                         Constant node, invisible to this attribute-NAME check
                         -- the identical shape already disclosed for
                         ``build_write_client``; (ii) an aliased import
                         (``from google.oauth2.credentials import Credentials
                         as X``) evades the bare-name construction check, since
                         ``_CREDENTIAL_CLASS_NAMES`` matches the LOCAL bound
                         name (``X``), not the original symbol -- though the
                         import statement itself usually still trips
                         ``forbidden_import`` (the ``google`` root is banned
                         regardless of the ``as`` alias), so this residual is
                         Low severity, not a silent full bypass.
  credential_provider_reference -- naming an ADAPTER_PROFILE write-credential
                         PROVIDER symbol anywhere outside the ADAPTER_PROFILE
                         zone: importing it (``from external_write.adapters_x
                         import write_credential_provider``), referencing it as a
                         bare name, or accessing it as an attribute. TWO reach
                         paths are guarded: the retired module-level provider
                         name (``write_credential_provider``) AND the Adapter
                         method that provisions the write client
                         (``build_write_client`` — so a capability-zone
                         ``get_adapter(op_kind).build_write_client(op)`` attribute
                         reference is flagged too). The credential-
                         isolation keystone: capability/proposal-zone code must be
                         UNABLE TO OBTAIN the write-credential provider (the
                         callable that returns the write client), not merely
                         "does not call it" by convention. The provider
                         legitimately lives ONLY in the ADAPTER_PROFILE zone
                         (exempt from every check), where a concrete adapter
                         DEFINES ``build_write_client`` and provisions its own
                         write client. Curated set, same disclosed-bound spirit
                         as the credential-construction surface: a string-literal
                         ``getattr(adapter, "build_write_client", None)`` resolves
                         the method via a Constant node invisible to the symbol
                         check — an aliased/dynamic reach that stays a disclosed
                         deterministic-scanner limitation, not closed here.
  adapter_module_import,
  adapter_registry_reference -- (defense-in-
                         depth, sealing the architecture built above)
                         CAPABILITY-zone-ONLY bans (see "Trust zones" below —
                         unlike every rule above, these two do NOT apply to
                         SEALED_KERNEL: ``adapters.py`` and
                         ``effects_manifest.py`` legitimately import and call
                         ``get_dispatch``/``get_adapter`` — that is the
                         registry's own intended kernel-side consumer. Nor do
                         they apply to ADAPTER_PROFILE, already exempt from
                         every check before the scanner runs — see
                         ``_scan_file``'s early return):
                           * ``adapter_module_import`` — importing the adapter
                             registry module itself (``import
                             external_write.adapter_registry`` / ``from
                             external_write.adapter_registry import ...``) or
                             an adapter-PROFILE module (``import
                             external_write.adapters_<vendor>`` / ``from
                             external_write.adapters_<vendor> import ...``).
                             Matched by the module's trailing two dotted
                             components (``external_write.adapter_registry`` /
                             ``external_write.adapters_`` + a non-empty
                             suffix) so a package-path prefix in front (e.g. a
                             hypothetical ``pkg.external_write.adapters_x``)
                             does not evade the match. CRITICAL distinction:
                             the bare kernel dispatch module
                             ``external_write.adapters`` (where
                             ``run_operation`` lives — the one legitimate
                             CAPABILITY-facing entrypoint, re-exported again by
                             ``capability_api.py``) is NEVER matched — the
                             ``adapters_`` prefix requires a trailing
                             underscore + a non-empty suffix, so "adapters"
                             alone never collides with "adapters_gmail" etc.
                             NOTE (v0.12.0 S1): importing the bare
                             ``external_write.adapters`` MODULE is still not an
                             ``adapter_module_import`` violation, BUT naming the
                             ``run_operation`` SYMBOL it exports now IS a
                             separate ``raw_run_operation_reference`` violation
                             in the CAPABILITY zone (see that rule below) — the
                             sanctioned CAPABILITY live-write entrypoint is
                             ``capability_api.run_enveloped_operation``, not raw
                             ``run_operation``.
                             This additionally
                             matches the PACKAGE-LEVEL import shape — ``from
                             external_write import adapters_<vendor>`` / ``from
                             external_write import adapter_registry`` — where
                             the profile/registry name sits in the import's
                             alias rather than in a dotted module path
                             (``node.module`` there is just the bare
                             ``external_write`` package, which the
                             trailing-two-components match above does not by
                             itself reach). Matched by the SAME name rule
                             (registry exact-name OR ``adapters_`` prefix),
                             applied per-alias when the import's module is the
                             ``external_write`` package itself (see
                             ``_module_is_external_write_package``); the bare
                             ``adapters`` alias is excluded on identical
                             grounds — ``"adapters".startswith("adapters_")``
                             is False. A further check
                             additionally matches the RELATIVE import forms —
                             ``from .adapters_<vendor> import X`` / ``from
                             .adapter_registry import Y`` (dotted-relative,
                             ``node.level > 0`` with ``node.module`` set to
                             the bare submodule name and no
                             ``external_write.`` prefix at all, since a
                             relative import never spells the package it is
                             relative to) and ``from . import adapters_
                             <vendor>`` / ``from . import adapter_registry``
                             (bare-relative, ``node.level > 0`` with
                             ``node.module is None`` and the submodule name in
                             the import's alias instead). Neither shape is
                             reached by the absolute dotted-module match above
                             (which requires an ``external_write.`` prefix)
                             or the package-level match (which requires
                             ``node.module == "external_write"`` exactly).
                             Matched by the SAME name rule as the other two
                             forms (registry exact-name OR ``adapters_``
                             prefix), gated on the module/alias name alone —
                             not on the relative level — so an up-package
                             relative import of an unrelated module (``from
                             ..something import x``) is not incidentally
                             flagged, and the bare kernel dispatch module is
                             excluded via both relative spellings (``from
                             .adapters import run_operation`` / ``from .
                             import adapters``) on the identical
                             trailing-underscore ground as the other forms.
                             A further check
                             additionally matches the BARE, NON-RELATIVE
                             import forms — ``import adapters_<vendor>`` /
                             ``import adapter_registry`` (via
                             ``visit_Import``, which has no ``level`` concept
                             at all — a plain ``import`` statement is always
                             absolute) and ``from adapters_<vendor> import
                             X`` / ``from adapter_registry import Y`` at
                             ``node.level == 0`` — where the module name has
                             NO ``external_write.`` prefix and no relative
                             dot either, the one combination none of the
                             absolute/package-level/relative checks above
                             reach (see ``_bare_first_component_matches_adapter``).
                             Gated on ``node.level == 0`` in the ``from``
                             form specifically so it does not double-fire
                             alongside the relative-bare check above, which
                             independently matches the identical bare module
                             name at ``node.level > 0``. This
                             also generalizes the absolute dotted-module
                             match itself (``_module_matches_adapter_registry``
                             / ``_module_matches_adapter_profile``) from
                             "the registry/profile name is the LAST
                             component" to "the registry/profile name is ANY
                             component immediately following an
                             ``external_write`` component" — closing a
                             nested-package gap: ``external_write.
                             adapters_acme.client`` or ``external_write.
                             adapter_registry.sub`` (a profile/registry
                             package one level deeper than the previously-
                             caught two-component form) is now matched too
                             (see ``_has_adapter_component_after_external_write``).
                             Both additions above preserve the bare kernel
                             dispatch module's exclusion on the same
                             trailing-underscore / exact-name grounds as
                             every prior form.
                           * ``adapter_registry_reference`` — naming a
                             registry symbol (``get_adapter``, ``get_dispatch``,
                             ``register_adapter``, ``unregister_adapter``,
                             ``_REGISTRY``, ``AdapterDispatch``,
                             ``_DISPATCH_REGISTRY``, ``provision_write_client``)
                             as an import alias, a bare name, or an attribute
                             — regardless of which module the capability
                             claims to import it from (so a re-export shape,
                             e.g. ``from external_write.adapters import
                             get_adapter``, is caught on the NAME even though
                             the bare ``adapters`` module import itself is
                             legal). ``_DISPATCH_REGISTRY`` and
                             ``provision_write_client`` were added alongside
                             the function-object-internals ban above:
                             ``_DISPATCH_REGISTRY`` is the dispatch-keyed
                             dict backing ``get_dispatch``, the same role
                             ``_REGISTRY`` plays for ``get_adapter``; and
                             ``provision_write_client`` is the write-client
                             provisioner reachable off a dispatch object, the
                             same role ``build_write_client`` plays off an
                             adapter object. Modeled directly on
                             ``credential_provider_reference`` above
                             (visit_ImportFrom / visit_Name / visit_Attribute
                             against a curated symbol set).
                         Together these make the mutable Adapter instance and
                         the adapter-profile modules that define
                         ``build_write_client`` STATICALLY unreachable from
                         capability code — closing the reach path the
                         ``AdapterDispatch`` capture defends at runtime
                         (reassigning an instance attribute after obtaining it
                         via ``get_adapter`` no longer hijacks dispatch — see
                         ``adapter_registry.AdapterDispatch``) by removing the
                         capability's ability to even NAME ``get_adapter`` in
                         the first place.
  introspection_escape_hatch -- (CAPABILITY-zone-ONLY, same
                         zone-scoping rationale as the two rules above —
                         ``read_facade.py``'s own ``__init_subclass__``
                         legitimately calls ``vars(cls)`` in SEALED_KERNEL)
                         a clear dynamic-reach escape hatch that could
                         otherwise reach a banned module or object WITHOUT a
                         static ``import`` the checks above would see:
                         ``sys.modules`` (attribute access gated on a ``sys``
                         base), ``X.__subclasses__`` (attribute, any base —
                         unambiguous, no benign-collision risk, unlike
                         ``__class__``/``__dict__``/``__mro__``/``__module__``
                         below), ``importlib.import_module`` (attribute gated
                         on an ``importlib`` base) and the bare ``import
                         importlib`` / ``from importlib import ...`` statement
                         itself (root-matched, mirroring
                         ``_FORBIDDEN_IMPORT_ROOTS``'s convention), and the
                         bare builtins ``__import__`` / ``globals`` / ``vars``
                         referenced by name. Deliberately BROADER than
                         ``dynamic_import`` above: ``dynamic_import`` only
                         fires when a literal argument names a KNOWN-forbidden
                         import root; ``importlib.import_module("external_write.
                         adapter_registry")`` — an internal module name, not a
                         network/vendor client — would evade that check
                         entirely, which is exactly why this rule fires on the
                         attribute/name reference itself, regardless of any
                         argument. Deliberately NOT banned (disclosed instead,
                         not silently assumed covered — see "Bounds NOT
                         covered" below): ``__class__``, ``__dict__``,
                         ``__mro__``, ``__module__`` — these appear in
                         ordinary code (``type(x)``, isinstance idioms,
                         dataclasses) constantly, and banning them would
                         over-fire on unremarkable Python. Also flagged, any
                         base, name alone: the function/method-object
                         internals ``__globals__``, ``__code__``,
                         ``__closure__``, ``__func__``, and ``__self__``. A
                         real function object (such as the one legitimate
                         capability-facing entrypoint into this gate) carries
                         its own defining module's global namespace on
                         ``__globals__`` — naming that attribute is a way to
                         reach outside the function entirely, into whatever
                         module defined it, without a static ``import``
                         statement this scanner's other checks would see.
                         ``__code__``/``__closure__``/``__func__``/``__self__``
                         are the same class of reach: internals of a function
                         or bound-method object that let code walk sideways
                         into state it was never handed directly. Like
                         ``__subclasses__``, none of these five appear in
                         ordinary capability code, so banning them carries the
                         same no-over-fire guarantee.
  raw_run_operation_reference -- (CAPABILITY-zone-ONLY, v0.12.0 S1 — RunEnvelope
                         trust core) naming the RAW kernel write primitive
                         ``run_operation`` — as an import alias, a bare Name, or
                         an Attribute — regardless of the module a capability
                         claims to reach it through (``external_write.adapters``,
                         a relative/bare ``adapters`` import,
                         ``external_write.capability_api``, or any re-export).
                         The run-level trust protections (disk-authoritative
                         envelope spendability, consent-receipt binding,
                         APPLY-BY-ID against the frozen ``reviewed_set``, and the
                         AGGREGATE CEILING) live ONLY inside
                         ``run_enveloped_operation`` (run_envelope.py), which
                         calls ``run_operation`` ONCE per approved op; a
                         CAPABILITY module that reaches ``run_operation``
                         directly can loop it and bypass every one of them.
                         This REVERSES the prior explicit allowance of the
                         bare-adapters / capability_api ``run_operation``
                         entrypoint for CAPABILITY code — the sanctioned
                         CAPABILITY live-write entrypoint is now
                         ``capability_api.run_enveloped_operation``.
                         ``run_operation``'s own signature/contract is
                         deliberately UNCHANGED (a "refuse >1 unit" guard was
                         rejected — it breaks already-accepted operator
                         capabilities); the enforcement is this build-time rule
                         plus the sanctioned surface. CAPABILITY-zone-ONLY like
                         the three rules above: SEALED_KERNEL ``run_envelope.py``
                         (wraps ``run_operation``) and ``adapters.py`` (defines
                         it) stay exempt. Exact-name match, so the sanctioned
                         ``run_enveloped_operation`` is never mistaken for it.
                         Curated single-name surface — a string-literal
                         ``getattr(mod, "run_operation")`` resolves via a
                         Constant node invisible to this attribute-NAME check,
                         the same disclosed residual as ``build_write_client`` /
                         the registry symbols, not closed here.
  baked_operator_confirmation -- a command line built in code that carries the
                         operator-confirmation flag with a STRING LITERAL as its
                         value: the words that get recorded as the operator's own
                         acceptance were written by the machine. ANTI-DRIFT ONLY,
                         NOT A CONSENT ORACLE — see the bound disclosed below and
                         ``_Scanner._check_baked_operator_confirmation``.

------------------------------------------------------------------------------
Bounds NOT covered at v0 (disclosed — no silent caps)
------------------------------------------------------------------------------
  * A MANUFACTURED operator confirmation that is not spelled as a literal
    element of a list or tuple. ``baked_operator_confirmation`` sees ONE shape,
    and both halves of what escapes it need saying, because naming only the
    first invites the wrong inference:

      (a) COMPUTED values. A variable, a module constant, an f-string, a
          ``join``, a ``format``, a value read from a file, or any other
          computation reaches the same command carrying the same manufactured
          words and is NOT flagged.
      (b) LITERAL values in a container this rule does not inspect — and these
          are literal to the last character, so "anything literal is caught" is
          FALSE. A whole shell command line as one string
          (``subprocess.run("… --operator-confirmation 'yes'", shell=True)``)
          is not a list or tuple. Neither is a mapping of flag to value
          (``{"--operator-confirmation": "yes"}``) later expanded into argv,
          even though the flag and its value are spelled adjacently there too.
      (c) A NON-PYTHON caller. This scanner reads ``.py`` files only, so the
          same command in a shell script, a Makefile, a scheduler entry or a
          notebook is invisible to it — the same "Non-Python entrypoints" bound
          this list already discloses for every other rule, restated here
          because for THIS rule a shell wrapper is the likeliest home.

    Nothing static can decide whether text a program supplied came from a
    person, so this rule does not attempt it and must never be read as having
    closed consent forgery. What it closes is DRIFT: the shape an agent or a
    convenience script actually reaches for first, caught before it spreads.
    The deeper point — that a consent model whose consent is a command-line flag
    is weak by construction — is a design question this check does not answer.
  * Cross-FILE call-graph. Reachability is computed WITHIN a single file. A
    forbidden op physically lives in some file and is reported THERE, so a
    bypass cannot hide merely by being called from another file — the op's own
    file is still flagged. What is not modeled is "file A calls a tainted
    helper imported from file B": file B is flagged on its own, so the build
    still fails, but the violation is attributed to B, not A.
  * Aliased / fully-dynamic module names. A banned module loaded via a NON-
    literal name (importlib.import_module(var)) is not resolved. A non-literal
    subprocess command (built from variables) is likewise not inspected. These
    are deliberately out of scope for a deterministic v0; the conservative
    forbidden-import / direct-call surfaces catch the common shapes. (For a
    trust gate we prefer false positives to false negatives, but we do not
    attempt to symbolically execute the program.)
  * Non-Python entrypoints (JS / shell). The consult names these as eventual
    targets; this v0 scans Python only. A non-.py file is skipped.
  * Import denylist is CURATED, not exhaustive. The forbidden-import roots are a
    maintained list of known network / external-write clients. An unlisted
    network client (a niche or future HTTP/DB library not yet enumerated in
    ``_FORBIDDEN_IMPORT_ROOTS``) is a KNOWN false negative for the import check.
    The direct-call, dynamic-import, and subprocess-network surfaces still apply
    regardless of which client library is used, so an unlisted import alone does
    not silently grant a clean bypass for the common mutation/shell-out shapes —
    but the import-name denylist itself must be kept current as new clients
    appear. This bound is disclosed; it is not a silent cap.
  * Static re-stashing of a wrapped client onto a new attribute (e.g. a
    ReadFacade subclass's ``__init__`` doing ``self._x = read_only_client``
    under a different name than the base class expects). This is NOT
    detected HERE: distinguishing "a benign attribute assignment" from "a
    client being re-stashed to dodge the runtime allowlist" from AST shape
    alone is not reliably decidable without false-positive-prone heuristics
    (any ``self.<name> = <param>`` assignment would have to be flagged,
    which fires on ordinary, legitimate constructors constantly). This class
    of bypass is instead closed at RUNTIME, in depth, by
    ``read_facade.ReadFacade`` itself (reconciled with the read_facade
    hardening below, which this bullet previously undersold):

      (a) CLOSED for normal attribute access. ``__setattr__``
          refuses to set ANY instance attribute other than a dunder — public
          or underscore-prefixed alike — so a re-stash never even lands in
          instance state. And even a value that somehow got in would be moot:
          ``__getattribute__`` enforces a FIXED allowlist (dunders, the
          internal ``read_methods``/``_read`` names, and declared
          ``read_methods``) on every instance access, so a novel
          underscore-prefixed attribute — successfully smuggled or not — is
          unreachable via ``facade.<name>`` / ``getattr(facade, name)``.

      (b) NOT closed — disclosed reach-beneath residuals, honesty over
          overclaim, matching read_facade.py's own "Disclosed residual
          bypasses" section: code that imports the module-private
          ``_WRAPPED_CLIENTS`` weak-key dict directly can still read the
          wrapped client out of it (the runtime allowlist governs attribute
          access on a ReadFacade INSTANCE, not access to the module's own
          private state); and code that calls
          ``object.__getattribute__(self, name)`` (or otherwise reaches
          beneath the class's own hook — e.g. ``inspect``/``ctypes``-level
          introspection) bypasses ``ReadFacade.__getattribute__`` entirely,
          since it never goes through the instance's own attribute protocol.
          Neither residual is caught by scan.py itself — this module does
          not attempt to flag either shape — and neither is closed by
          read_facade.py either; both sit OUTSIDE the deterministic
          guarantee and INSIDE this project's actual enforcement ceiling:
          build-time + operator-as-approver, not runtime/OS. Disclosed here
          as a documented limitation of the static gate, not silently
          assumed covered.
  * ``direct_api_call`` is NOT a claim of method-reference completeness
    (an earlier version of this section overclaimed otherwise; corrected
    here). Two known false negatives,
    disclosed rather than chased, because closing either would require
    undecidable data-flow analysis, not a deterministic AST shape check:
      (a) a BROKEN variable chain — ``u = client.users(); m =
          u.messages(); m.send(...)`` — splits the attribute chain across
          several assignments. ``_attr_chain_names`` walks a single
          Call/Attribute expression and stops at the first ``ast.Name`` it
          hits (here, the local variable ``m``), so it never sees the
          ``users``/``messages`` surface handles that would have gated the
          ambiguous verb — the chain-gating this module relies on
          (``_check_surface_mutation``) is a SINGLE-EXPRESSION analysis, not
          a local data-flow/alias tracker.
      (b) a LITERAL ``getattr(x, "send")(...)`` — the mutation verb is a
          ``ast.Constant`` string, not an ``ast.Attribute`` node with
          ``.attr == "send"``; it is invisible to the same attribute-name
          check, the identical Constant-node blind spot already disclosed
          above for ``build_write_client`` / the credential-factory
          surfaces.
    Both are disclosed deterministic-scanner bounds, not silently assumed
    covered. ``direct_api_call`` is defense-in-depth here, not the primary
    guarantee: CAPABILITY-zone code has no write-capable client to call a
    verb ON in the first place unless the credential-isolation keystone
    is itself breached — and the
    ``adapter_registry_reference`` / ``adapter_module_import`` /
    ``introspection_escape_hatch`` rules are precisely what closes the
    static reach paths to that keystone. This module does not attempt to
    chase every conceivable indirection into value-flow analysis; it
    catches the common, single-expression shapes and discloses the rest.
  * Introspection beneath ``get_adapter``/``build_write_client`` via
    ``__class__``/``__dict__``/``__mro__``/``__module__``.
    These four dunders are deliberately NOT banned — see
    ``introspection_escape_hatch`` above — because they appear in ordinary
    code (``type(x)``, isinstance idioms, dataclasses) constantly; banning
    them would over-fire on unremarkable Python. A determined capability
    could still chain ``obj.__class__.__mro__[...]`` or
    ``type(x).__dict__["build_write_client"]`` to resolve a class-level
    method by a STRING key — a ``ast.Constant`` node, invisible to every
    symbol check in this module, the same Constant-node blind spot
    disclosed throughout this section. This residual is OUTSIDE the
    deterministic guarantee and INSIDE this project's actual enforcement
    ceiling (build-time + operator-as-approver, not runtime/OS) — disclosed
    here, not silently assumed covered. In practice this residual is
    defanged by the rules above: the entry point into it (``get_adapter``,
    to obtain an adapter instance to introspect at all) is itself a banned
    ``adapter_registry_reference`` in the CAPABILITY zone, so a capability
    module that never names ``get_adapter`` has no adapter instance to
    reach beneath in the first place.
  * Aliased ``sys`` / ``importlib`` names in introspection-escape-hatch
    checks. The ``sys.modules`` and ``importlib.import_module``
    checks in ``_check_introspection_attribute`` anchor on a bare Name node
    (``base.id == "sys"`` / ``"importlib"``). An aliased import
    (``import sys as s``) reference to ``s.modules[...]`` evades the check
    because the base name is "s", not "sys" — a disclosed deterministic-
    scanner bound, not a silent gap. Consistent with the credential-isolation
    keystone being the real guarantee; this module discloses
    what it does not deterministically catch.
  * A read facade's own internal read-dispatch method is reachable by any
    code holding a reference to the facade object, with an arbitrary
    method-name argument — not limited to whatever the facade's own
    declared read methods actually call. This is a property of the read
    facade's own runtime design (documented in full in that module), not
    something this static scanner additionally restricts; noted here only
    so this module's list of disclosed bounds is complete.
  * A registered adapter's ``plan()`` purity is an ADAPTER-AUTHOR invariant,
    not something this scanner machine-verifies. ``adapters.py``'s ``run_operation`` calls
    a registered adapter's ``dispatch.plan(dispatch.instance, op.params)``
    ONCE, BEFORE the write gate runs, purely to count effect units for the
    blast-radius cap (see that function's "n_units / plan-once" docstring
    section). That ordering means ``plan()`` MUST be pure — no external
    write, no other I/O, no credential use — for the gate's "refuses before
    any write is attempted" guarantee to hold: an adapter whose ``plan()``
    performed a write would execute that write BEFORE the gate ever ran,
    regardless of what the gate later decides. This scanner does not, and
    structurally cannot, verify that purity: every concrete adapter's
    ``plan()`` implementation lives in an ADAPTER_PROFILE module, and
    ADAPTER_PROFILE is the ONE zone exempt from every check in this file —
    see "Trust zones" below and ``_scan_file``'s early return. So the
    guarantee behind ``plan()`` purity is the same as everywhere else this
    project relies on the ADAPTER_PROFILE zone: a human operator reviewing
    the trusted adapter module before it is registered, not a deterministic
    proof that the function body has no side effects. Disclosed here
    plainly, not silently assumed covered.

------------------------------------------------------------------------------
Enforcement ceiling — what this scanner guarantees, and what it does not
------------------------------------------------------------------------------
  This scanner is a build-time guard against capability code drifting into
  an ungated external-write path, or reaching one through an obvious,
  nameable bypass. It runs once, before a build is accepted, over the
  generated source files in a project, and it fails that build if anything
  it checks for is present.

  It is NOT a runtime sandbox, and it is not designed to defend against a
  determined, adversarial use of Python's own reflection machinery from
  inside a capability module. Concretely, this scanner does not attempt to
  catch every way a piece of code could reach into another object's internal
  state at runtime: walking through a function or method object's own
  internals to reach the module that defines it, reassigning an attribute on
  an object by calling the built-in attribute-setting machinery directly
  instead of using ordinary attribute-assignment syntax, or resolving a name
  through a string value computed at runtime instead of writing that name
  literally in the source. Some of the clearest, most obvious instances of
  that kind of reach are closed directly by the checks above (see the
  function-object-internals additions to the introspection-escape-hatch
  check, and the adapter-registry symbol list). Reflection paths beyond
  those remain possible in principle. That is a disclosed limit of this
  check, stated here plainly rather than left as a silent gap.

  This limit is acceptable given what this scanner is actually built to
  protect against. The capability code it scans is written by an AI
  assistant working for the operator, inside the operator's own project,
  against the operator's own credentials — it is not code written by an
  outside party trying to defeat this check on purpose. The realistic
  failure this scanner guards against is an assistant accidentally
  producing a capability that reaches an external surface it should not:
  an ordinary import of a network client, an ordinary call to a mutating
  method, an ordinary reference to a credential or registry symbol it
  should never have been able to name — not a hostile author deliberately
  hand-crafting a reflection-based bypass to get past this specific check.
  Within that scope, this scanner together with the operator reviewing what
  gets built is the intended safeguard: a deterministic check at build time,
  backed by a person approving the result, rather than a runtime or
  operating-system-level sandbox. Every reflection path this scanner does
  not close is disclosed above, in "Bounds NOT covered", and in this
  section — never silently assumed covered.

------------------------------------------------------------------------------
Trust zones (replaces the old blanket "whole external_write/ tree is exempt"
rule — see ``zones.py`` for the full rationale and the canonical taxonomy)
------------------------------------------------------------------------------
  Every scanned file is classified into exactly one of three zones
  (``zones.classify_zone``):

    SEALED_KERNEL    -- the gate machinery (run_operation, write_gate,
                        broker, receipt validation, the invocation ledger,
                        operations/contracts/proof_hash/effects_manifest,
                        the adapter registry, the read facade, the RunEnvelope
                        trust core (run_envelope.py), this scanner
                        and the coverage gate). Held to the SAME checks as
                        capability code below — it simply never trips them,
                        because none of this code needs a vendor SDK import
                        or a write-capable credential. ONE deliberate
                        exception: the adapter_module_import /
                        adapter_registry_reference / introspection_escape_hatch /
                        raw_run_operation_reference
                        rules are CAPABILITY-zone-ONLY and do NOT apply here —
                        adapters.py and effects_manifest.py are the registry's
                        own intended kernel-side consumers (get_dispatch /
                        get_adapter), read_facade.py legitimately calls
                        vars(cls), and run_envelope.py legitimately wraps
                        run_operation (the one place a run-level envelope is
                        enforced around it) — see those rules' docstring
                        sections.
    ADAPTER_PROFILE  -- registered per-vendor adapter modules. The ONLY zone
                        exempt from every check this module enforces —
                        importing a vendor SDK, calling a mutation verb, and
                        constructing/obtaining a write-capable credential are
                        all legitimate here.
    CAPABILITY       -- everything else, including any module that is not
                        EXPLICITLY enumerated as SEALED_KERNEL or
                        ADAPTER_PROFILE — even one that physically lives
                        inside the installed package directory. This is the
                        fail-closed default zone: an unclassifiable module is
                        always the most restrictive zone, never a silent
                        pass.

  Zone membership is anchored to a single canonical absolute location — by
  default ``scan.py``'s own directory (``Path(__file__).resolve().parent``),
  which cannot be spoofed by a look-alike directory an author recreates
  elsewhere — but, critically, being located under that anchor is NECESSARY,
  not SUFFICIENT, for SEALED_KERNEL or ADAPTER_PROFILE membership: the file's
  path relative to the anchor must ALSO be explicitly listed in
  ``zones.SEALED_KERNEL_MODULE_PATHS`` / ``zones.ADAPTER_PROFILE_MODULE_PATHS``
  (or an equivalent explicit set passed by the caller). A new file dropped
  under the package directory — including a whole new adapter directory — is
  therefore NOT automatically exempted from anything; exemption requires a
  deliberate, reviewable addition to one of those two allowlists. (Earlier
  versions keyed exemption on the directory NAME appearing anywhere in the
  path, which was spoofable — fixed by anchoring to the absolute location.
  This task closes a second, more subtle version of the same failure mode:
  even WITHIN the anchor, a directory alone was never meant to be sufficient
  for exemption.)

------------------------------------------------------------------------------
Hash-bound migration quarantine (F-3B, anti-deadlock)
------------------------------------------------------------------------------
upgrade_reconcile.py's safe-pause/migration-queue step gates a scanner-red
writer's ENTRYPOINT (or installs a runtime block) but deliberately never
touches the flagged ``.py`` file itself, then records it in
``agents/handoffs/pending_migrations.json`` for the operator's rebuild flow.
Left unaddressed, the NEXT real build-time run of this scanner
(``python3 agents/lib/external_write/scan.py agents/``, recursively) would
re-flag that SAME still-unmigrated file and fail the build — a hard deadlock
for a non-technical operator, since the fix genuinely requires a future
rebuild, not an immediate edit.

This is closed by a narrow, DENY-BY-DEFAULT quarantine, consulted per file
after its violations are computed: a violation is exempted ONLY when ALL of
the following hold —

  (a) the scanned file is listed in ``pending_migrations.json`` (relative to
      ``project_root``) with a matching ``writer_relpath`` and
      ``status: "pending"``;
  (b) the file's CURRENT sha256 equals that entry's recorded
      ``paused_content_sha256`` (an edit since pause-time voids the
      quarantine — the file is no longer the known-inert artifact that was
      paused);
  (c) the specific violation (path/line/kind) is itself present in that
      entry's recorded ``violations`` list (a NEW violation, not seen at
      pause-time, is never silently swallowed).

Any other case — the file is not listed, ``pending_migrations.json`` is
absent/unreadable/malformed, the hash does not match, or a violation was not
among those recorded — is NOT exempt and reports normally; see
``_quarantined_violations`` below. This is a build-time anti-drift narrowing
of what a *known, already-detected, already-queued* violation reports as; it
grants no new runtime capability and is not a substitute for the runtime
sandbox this scanner has never claimed to be.

This quarantine applies ONLY in the paused/not-yet-accepted window — it is
independent of, and must never weaken,
``capability_invariants.py``'s separate Check 6 (marker residue), which
fails an ACCEPTED capability that still carries a pause marker on disk. The
two checks share no code path; they are simply consistent about the same
underlying paused state.
"""

import ast
import hashlib
import json
import os
import stat as _stat
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, NamedTuple, Optional, Sequence, Union

# sys.path bootstrap: scan.py is designed to also be run directly as a script
# (see the CLI entrypoint at the bottom of this file), in which case Python
# puts THIS file's own directory on sys.path, not its parent — so
# ``import external_write.zones`` would fail unresolved. Make the package
# parent (``agents/lib``) importable if it is not already (a no-op under the
# test harness / normal package import, which puts it on the path itself).
# Anchored to __file__, not cwd. Mirrors coverage_gate.py's identical need.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.zones import (  # noqa: E402
    ADAPTER_PROFILE_MODULE_PATHS,
    SEALED_KERNEL_MODULE_PATHS,
    Zone,
    classify_zone,
)
# The ONE declaration in this package of "directory names that are never
# operator code" — vendored dependency trees, VCS internals, derived caches.
# Imported rather than re-spelled: the consent sweep below needs exactly that
# set to bound its own input, and a second copy is how two sweeps that must
# agree drift apart. ``writer_state_core`` imports no sibling here, so this edge
# adds no cycle; its own docstring records why it stays a leaf.
from external_write.writer_state_core import NON_PROJECT_DIRS  # noqa: E402


# ---------------------------------------------------------------------------
# The operator-invocable entrypoint, and the ONE renderer of the command that
# names it.
#
# Spelled once, here, because two surfaces outside this module have to name the
# same command: the operator-invocable command manifest, and the state->action
# registry, which renders the check that CONFIRMS a rebuilt writer now routes
# through the sanctioned path. A re-spelling is how a named repair comes to name a
# path that no longer exists; the manifest's own agreement with this constant is
# pinned by a build-time test rather than by an import, because the module the
# PreToolUse hook loads must not pull this scanner in for a string.
# ---------------------------------------------------------------------------

SCAN_ENTRYPOINT_REL = "agents/lib/external_write/scan.py"

#: Declares that an invocation is about ONE named writer, and is therefore the
#: per-writer REPAIR CONFIRMATION rather than the project-wide build gate. The
#: two surfaces share this entrypoint but owe the operator opposite things (see
#: the CLI section at the bottom of this file), and they are told apart by this
#: explicit declaration — never by guessing intent from whether the argument
#: happens to be a file or a directory.
#:
#: Deliberately the SAME word the acknowledgement command uses for the same
#: thing, so an operator meets one name for a flagged writer across both
#: commands. Spelled here rather than imported for the reason the confirmation
#: flag below gives; the agreement is pinned by a build-time test.
FLAG_WRITER = "--writer"

#: The command-line flag that carries the operator's own words into the two
#: commands that record a consent decision. This is the ONE thing the
#: baked-consent rule keys on, and it is the declared value, not an inference
#: from a filename or a directory.
#:
#: Spelled here rather than imported from the module that declares it, for the
#: same reason the command manifest hand-spells the entrypoint paths it names:
#: the acknowledgement facade reaches the writer-state service, which imports
#: THIS module, so an import would close a cycle. The agreement is pinned at
#: build time instead — see ``test_external_write_scan``'s
#: ``test_the_flag_is_the_one_the_consent_command_itself_declares``, which fails
#: if the two ever diverge.
OPERATOR_CONFIRMATION_FLAG = "--operator-confirmation"


def scan_command(path: str) -> str:
    """The exact, paste-ready command that scans `path` for bypasses.

    Deliberately a single physical line with the argument `shlex.quote`'d: a
    writer relpath is data from a queue entry on disk, and an unquoted path
    containing a space would silently split into two arguments so the
    "paste-ready" command would scan the wrong thing (or nothing).

    It CONFIRMS a repair; it never performs one. The caller that renders it into
    operator-facing text is responsible for saying so -- see the registry's own
    instruction text for the rebuildable state.

    Renders ``FLAG_WRITER`` rather than a bare positional path, because that is
    what makes this the PER-WRITER surface and not the project-wide build gate.
    The distinction is load-bearing and it is an operator-safety one: this
    command's whole promise is "the file you just repaired is now clean", so a
    finding somewhere else in the project must not come back as a failure of the
    repair. Declared explicitly here rather than inferred downstream from
    whether the argument happens to name a file -- the gate is invoked on a
    single file too, and guessing between the two from argument shape is the
    infer-identity-from-incidental-structure mistake this package refuses.
    """
    import shlex as _shlex
    return f"python3 {SCAN_ENTRYPOINT_REL} {FLAG_WRITER} {_shlex.quote(path)}"


class Violation(NamedTuple):
    """One detected bypass.

    path:   the file the violation was found in.
    lineno: the line of the offending AST node.
    kind:   what was caught — one of:
              'direct_api_call', 'forbidden_import',
              'dynamic_import', 'subprocess_network',
              'credential_construction', 'credential_provider_reference',
              'adapter_module_import', 'adapter_registry_reference',
              'introspection_escape_hatch', 'raw_run_operation_reference',
              'sealed_kernel_import', 'baked_operator_confirmation',
              'unparseable'.
            Specific enough that a build-failure message tells the operator or
            agent WHAT to fix.
    """

    path: str
    lineno: int
    kind: str


# ---------------------------------------------------------------------------
# Denylists (deterministic; the same call elsewhere that is legal inside the
# allowed module is a violation here).
# ---------------------------------------------------------------------------

# Top-level package names whose import gives a direct path to an external
# surface. Submodules (e.g. urllib.request, http.client) match by top-level.
_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "requests",
        "urllib",
        "urllib2",
        "urllib3",
        "http",          # http.client
        "httplib",
        "httpx",
        "aiohttp",
        "pycurl",
        "treq",
        "tornado",
        "googleapiclient",
        "gspread",
        "google",        # google.cloud.*, google-api-python-client surfaces
        "boto3",
        "botocore",
        "psycopg2",
        "psycopg",
        "pymysql",
        "mysql",
        "sqlalchemy",
        "pymongo",
        "redis",
        "smtplib",
        "ftplib",
        "paramiko",
        "socket",
    }
)

# Ambiguous mutation verbs that collide with builtin collection methods
# (dict.values(), list.append()). Flagged ONLY when they terminate a
# sheets-style surface chain (values()/spreadsheets()/sheet) — see
# _check_surface_mutation.
_FORBIDDEN_SHEETS_VERBS = frozenset({"update", "append", "clear"})

# Unambiguous external-surface mutation method names — not English collection
# methods, so flagged on name alone, in a single detection path (this replaces
# the prior double-handling where batchUpdate was both a "sheets verb" and a
# trailing special case).
_UNAMBIGUOUS_SURFACE_VERBS = frozenset({"batchUpdate", "update_cells"})

# Gmail mutation
# verbs, added as a first-class defense-in-depth detection layer following the
# SAME ambiguous-vs-unambiguous discipline as the Sheets verbs above. A direct
# Gmail mutation was already indirectly caught via forbidden_import (the
# googleapiclient/google import) + credential_construction (obtaining the
# write-capable credential); this closes the surface-mutation gap directly,
# the same way _FORBIDDEN_SHEETS_VERBS / _UNAMBIGUOUS_SURFACE_VERBS close it
# for Sheets. Kept as a PARALLEL set (not merged into the Sheets sets) so each
# vendor's verb list stays independently readable and the Sheets set is left
# untouched.
#
#   _UNAMBIGUOUS_GMAIL_VERBS -- Gmail-specific verbs that rarely collide with
#     ordinary method names on an arbitrary object -- flagged on name alone,
#     exactly like _UNAMBIGUOUS_SURFACE_VERBS.
#   _FORBIDDEN_GMAIL_VERBS -- verbs that collide with common English method
#     names (a dict/service/store can easily have its own .create()/
#     .delete()/.send()/.modify()) -- flagged ONLY when the attribute chain
#     shows a Gmail surface handle (_GMAIL_SURFACE_HANDLES below), the same
#     chain-gating _FORBIDDEN_SHEETS_VERBS uses for update/append/clear.
_UNAMBIGUOUS_GMAIL_VERBS = frozenset({"trash", "untrash"})
_FORBIDDEN_GMAIL_VERBS = frozenset({"modify", "send", "create", "delete"})

# Gmail resource/surface handles: the resource-collection names that appear in
# the attribute chain of a real Gmail API call shape (``service.users()
# .messages().trash(...)``, ``...drafts().create(...)``,
# ``...settings().filters().create(...)``). These are RESOURCE handles, not
# verbs themselves — mirrors how "values"/"spreadsheets"/"sheet" gate the
# Sheets ambiguous verbs in _check_surface_mutation.
_GMAIL_SURFACE_HANDLES = frozenset(
    {"messages", "drafts", "threads", "labels", "filters", "settings", "users"}
)

# Functions that perform a dynamic import.
_DYNAMIC_IMPORT_FUNCS = frozenset({"__import__"})
# importlib.import_module is matched as a (module='importlib', attr) pair below.

# Subprocess / shell entrypoints.
_SUBPROCESS_FUNCS = frozenset({"run", "Popen", "call", "check_call", "check_output"})
_OS_SHELL_FUNCS = frozenset({"system", "popen"})

# Network command-line tools that, when invoked via a shell-out, mutate an
# external surface.
_NETWORK_CLI_TOOLS = frozenset(
    {"curl", "wget", "http", "https", "httpie", "scp", "sftp", "rsync"}
)

# Credential-access surface (the credential-isolation build-time half).
# Curated, NOT exhaustive (a known, tracked limitation) — same disclosed-bound
# spirit as _FORBIDDEN_IMPORT_ROOTS. Matched structurally (attribute name /
# call target) so detection does not depend on how — or whether — the vendor
# SDK was imported in THIS file (an aliased import, an object handed in as a
# parameter, or a name never statically resolvable at all still trips this).
#
#   _CREDENTIAL_FACTORY_METHODS -- attribute names that construct or widen a
#     write-capable credential when called: the Google service-account /
#     authorized-user factory constructors, and ``with_subject`` (domain-wide
#     delegation impersonation — turns a service-account credential into one
#     that can act as an arbitrary user). Flagged on the attribute REFERENCE,
#     the same structural approach _check_surface_mutation already uses for
#     unambiguous mutation verbs, so a bound-and-called-later reference
#     (``fn = creds.with_subject; fn(user)``) is caught too.
#   _CREDENTIAL_CLASS_NAMES -- class names that, when CALLED (constructed),
#     produce a credential object. Checked only at the Call site (not every
#     attribute reference) because these names are common enough as bare
#     identifiers that flagging every reference would be noisy; constructing
#     one is the operative act.
#
# Disclosed bounds, not closed here -- see the module docstring's
# ``credential_construction`` section for the full disclosure: (i) a
# string-literal ``getattr(creds, "with_subject")(user)`` resolves a curated
# name via a Constant node, invisible to both frozensets above; (ii) an
# aliased ``from google... import Credentials as X`` evades
# _CREDENTIAL_CLASS_NAMES (which matches the local bound name, not the
# original symbol) -- though ``forbidden_import`` usually still fires on the
# banned ``google`` root regardless of the alias, so this is Low severity.
_CREDENTIAL_FACTORY_METHODS = frozenset(
    {
        "from_service_account_file",
        "from_service_account_info",
        "from_authorized_user_file",
        "from_authorized_user_info",
        "with_subject",
    }
)
_CREDENTIAL_CLASS_NAMES = frozenset({"Credentials", "ServiceAccountCredentials"})

# Adapter-profile credential-PROVIDER symbols — the
# credential-isolation keystone. A write-capable credential is
# provisioned ONLY inside the trusted ADAPTER_PROFILE zone. The emitted
# CAPABILITY zone must be UNABLE TO OBTAIN that provider — not merely "declines
# to call it". So naming an adapter-profile credential-provider symbol at all
# (importing it, referencing it as a bare name, or accessing it as an
# attribute) is a violation everywhere the scanner runs; it is legal ONLY in
# the ADAPTER_PROFILE zone, which is exempt from every check before this fires
# (see _scan_file's early return). Curated, NOT exhaustive — same disclosed-
# bound spirit as _FORBIDDEN_IMPORT_ROOTS / the credential-construction surface.
_CREDENTIAL_PROVIDER_SYMBOLS = frozenset(
    {
        # The retired module-level provider name (an earlier emitted shape).
        "write_credential_provider",
        # The Adapter method that provisions the write-capable client
        # (``build_write_client(op)``). Residual: after the provider was
        # moved onto the adapter, capability-zone code could still reach the
        # write client via ``get_adapter(op_kind).build_write_client(op)`` — an
        # attribute reference the symbol check now flags. The concrete adapter
        # legitimately DEFINES ``def build_write_client`` in the ADAPTER_PROFILE
        # zone, which is exempt before this rule fires (see _scan_file's early
        # return), so the definition is not self-tripped; only a reference from
        # a non-adapter zone is. NOTE: a string-literal ``getattr(adapter,
        # "build_write_client", None)`` resolves the method by a Constant node
        # invisible to this symbol check — that aliased/dynamic reach is the
        # same disclosed deterministic-scanner bound documented above, not
        # closed here.
        "build_write_client",
    }
)

# ---------------------------------------------------------------------------
# CAPABILITY-zone-ONLY bans (defense-in-
# depth, sealing the architecture built above). Unlike every rule
# above, these three checks are gated on zone == Zone.CAPABILITY and do NOT
# fire in SEALED_KERNEL: ``adapters.py`` legitimately imports/calls
# ``get_dispatch``, ``effects_manifest.py`` legitimately imports/calls
# ``get_adapter``, and ``read_facade.py`` legitimately calls ``vars(cls)`` in
# ``__init_subclass__`` — see the module docstring's
# ``adapter_registry_reference`` / ``introspection_escape_hatch`` sections for
# the full rationale and zone-scoping discipline.
# ---------------------------------------------------------------------------

# The adapter registry module itself — banned by module identity, matched by
# its trailing two dotted components (see _module_matches_adapter_registry)
# so a package-path prefix in front does not evade the match.
_ADAPTER_REGISTRY_MODULE_NAME = "adapter_registry"

# Adapter-PROFILE modules (``adapters_<vendor>.py``) — banned by module
# identity. CRITICAL: the prefix below REQUIRES the trailing underscore, so
# the bare kernel dispatch module ``external_write.adapters`` (where
# ``run_operation`` lives) never matches — see _module_matches_adapter_profile.
_ADAPTER_PROFILE_MODULE_PREFIX = "adapters_"

# Adapter-registry symbols — banned by NAME (import alias, bare Name, or
# Attribute), regardless of which module a capability claims to import them
# from (so a re-export shape, e.g. ``from external_write.adapters import
# get_adapter``, is caught on the name even though the bare ``adapters``
# module import itself is legal). Modeled directly on
# _CREDENTIAL_PROVIDER_SYMBOLS's visit_ImportFrom / visit_Name /
# visit_Attribute pattern. Curated, NOT exhaustive — same disclosed-bound
# spirit as every other curated symbol surface in this module.
#
# This adds the two symbols a review
# found unguarded: ``_DISPATCH_REGISTRY`` (the dispatch-keyed dict
# ``get_dispatch`` reads from — parallel to the already-banned ``_REGISTRY``,
# the adapter-keyed dict ``get_adapter`` reads from) and
# ``provision_write_client`` (the write-client provisioner on an
# ``AdapterDispatch``/dispatch object — parallel to the already-banned
# ``build_write_client``, the provisioner on an ``Adapter``). Same curated,
# disclosed-bound discipline as every other symbol set in this module.
_ADAPTER_REGISTRY_SYMBOLS = frozenset(
    {
        "get_adapter",
        "get_dispatch",
        "register_adapter",
        "unregister_adapter",
        "_REGISTRY",
        "AdapterDispatch",
        "_DISPATCH_REGISTRY",
        "provision_write_client",
    }
)

# Dynamic-reach escape hatches — bare builtin names banned by NAME (Name
# node). Unambiguous enough (unlike, say, a hypothetical "update"/"delete")
# that flagging every bare reference does not risk the noisy false-positive
# collision _CREDENTIAL_CLASS_NAMES's design note warns about.
_INTROSPECTION_BARE_NAMES = frozenset({"__import__", "globals", "vars"})

# The RAW kernel write primitive (v0.12.0 S1 — RunEnvelope trust core). Banned
# by NAME in the CAPABILITY zone — as an import alias, a bare Name, or an
# Attribute — regardless of which module a capability claims to reach it
# through (``external_write.adapters``, a relative/bare ``adapters`` import,
# ``external_write.capability_api``, or any re-export). Modeled directly on
# _ADAPTER_REGISTRY_SYMBOLS / _CREDENTIAL_PROVIDER_SYMBOLS (visit_ImportFrom /
# visit_Name / visit_Attribute against a curated name).
#
# WHY this reverses the prior explicit allowance of the bare-adapters/
# capability_api ``run_operation`` entrypoint for CAPABILITY code: the
# run-level trust protections — disk-authoritative envelope spendability,
# consent-receipt binding, APPLY-BY-ID against the frozen ``reviewed_set``, and
# the AGGREGATE CEILING — live ONLY inside ``run_enveloped_operation``
# (run_envelope.py), which then calls this raw primitive ONCE per approved op.
# A CAPABILITY-zone module that reaches ``run_operation`` directly can loop it
# and bypass every one of those run-level checks (the per-op write gate alone
# does not cap a reversible bulk run). ``run_operation``'s own contract is
# deliberately NOT changed (a "refuse >1 unit" guard was rejected — it breaks
# already-accepted operator capabilities); the enforcement is this build-time
# scanner rule plus the sanctioned surface. The sanctioned CAPABILITY
# live-write entrypoint is now ``capability_api.run_enveloped_operation``.
#
# SEALED_KERNEL stays exempt (this rule is CAPABILITY-zone-ONLY, like
# adapter_module_import / adapter_registry_reference / introspection_escape_hatch):
# ``run_envelope.py`` (the trust core that legitimately wraps ``run_operation``)
# and ``adapters.py`` (which DEFINES it) are SEALED_KERNEL members, so naming
# ``run_operation`` there never trips this. Exact-name match, so the sanctioned
# ``run_enveloped_operation`` is never mistaken for it (not a substring check).
# Curated single-name surface, same disclosed-bound spirit as every other
# symbol set in this module (a string-literal ``getattr(mod, "run_operation")``
# resolves via a Constant node invisible to this attribute-NAME check — the
# identical disclosed residual as ``build_write_client`` / the registry symbols).
_RAW_RUN_OPERATION_SYMBOL = "run_operation"

# v0.16.0 Cut 1.2 (A' / V15-3b) — CAPABILITY-zone import boundary. The sanctioned
# external_write surface a capability/operator module may import is this small
# allowlist; ANY other external_write submodule import (e.g.
# `from external_write.run_envelope import mint_run_envelope`) is a
# `sealed_kernel_import` bypass. This is the STRUCTURAL closure of the routing-
# invariant class (V15-3): the estate hand-rolled a per-batch bulk loop by
# importing mint_run_envelope directly from run_envelope. A symbol-by-symbol ban
# only closes the symbols we remember; the module allowlist closes the class.
# DERIVED from what the scaffold emits into CAPABILITY-zone files (capability
# module: capability_api + operations; read-facade module: read_facade) and
# pinned to that set by test_scaffold_emitted_imports_are_all_allowlisted.
_CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES: FrozenSet[str] = frozenset(
    {"capability_api", "operations", "read_facade"}
)

# The raw bulk-run mint primitives (v0.15.0 trust core), banned by NAME in the
# CAPABILITY zone exactly like _RAW_RUN_OPERATION_SYMBOL — so a bare/relative
# reach (`from run_envelope import mint_run_envelope`; `x = mint_run_envelope`)
# is caught even though it carries no `external_write.` prefix for the module
# boundary rule to match. These live in run_envelope.py (SEALED_KERNEL), which
# stays exempt (CAPABILITY-zone-only). Exact-name match.
_RAW_BULK_MINT_SYMBOLS: FrozenSet[str] = frozenset(
    {"mint_run_envelope", "new_bulk_run_id"}
)


def _external_write_submodule(dotted: str) -> Optional[str]:
    """If ``dotted`` names an external_write SUBMODULE
    (``external_write.<submod>`` or ``<pkg>.external_write.<submod>``), return
    ``<submod>`` (the first component AFTER ``external_write``); else None.
    Anchored on the ``external_write`` component, same spoof-resistant
    convention as ``_module_is_external_write_package`` (which handles the
    package-level ``external_write`` form with no submodule component)."""
    parts = dotted.split(".")
    if "external_write" in parts:
        i = parts.index("external_write")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


# Function/method-object internals — attribute names banned by NAME alone,
# any base. ``run_operation`` is
# the real function object defined in the sealed kernel module, so its
# ``__globals__`` bridges directly into that module's namespace; a string-
# keyed lookup through it (``run_operation.__globals__["get_dispatch"]``) is
# invisible to every symbol check in this module, because the lookup key is
# an ``ast.Constant``, not a Name/Attribute. Banning the attribute reference
# itself closes the bridge deterministically: capability code can no longer
# NAME ``.__globals__`` (or the sibling internals below) at all, regardless
# of what it would do with the result. Unlike ``__class__``/``__dict__``/
# ``__mro__``/``__module__`` (deliberately NOT banned — see the module
# docstring), ordinary capability code has no legitimate reason to ever
# touch a function/method object's own internals, so this set does not
# over-fire on ``type(x)``, isinstance idioms, or dataclasses:
#   * ``__globals__``  -- the function's global-namespace dict.
#   * ``__code__``     -- the function's code object.
#   * ``__closure__``  -- captured free-variable cells.
#   * ``__func__``     -- the underlying function behind a bound method.
#   * ``__self__``     -- the bound instance behind a bound method.
_FUNCTION_INTROSPECTION_ATTRS = frozenset(
    {"__globals__", "__code__", "__closure__", "__func__", "__self__"}
)


def _has_adapter_component_after_external_write(dotted: str, predicate) -> bool:
    """True iff some component
    of ``dotted`` equals ``"external_write"`` and the component IMMEDIATELY
    FOLLOWING it satisfies ``predicate``.

    Generalizes the prior trailing-two-components match (which only checked
    ``parts[-2] == "external_write"`` — i.e. the adapter/registry name had to
    be the very LAST component) to ANY position in the dotted path. That
    closes a nested-package gap: a package one
    level deeper than the previously-caught two-component absolute form —
    ``external_write.adapters_acme.client`` or ``external_write.
    adapter_registry.sub`` — has the profile/registry name sandwiched
    between ``external_write`` and a further submodule, not trailing, so the
    old ``parts[-2]``-only check missed it. The trailing case is still
    covered here as the special case where the matching index is
    ``len(parts) - 2``, so nothing that matched before stops matching now —
    this is a strict superset, not a behavior change for the old shapes. A
    package-path prefix in front (e.g. ``pkg.external_write.adapter_registry``)
    still does not evade the match, since the scan is for the LITERAL
    ``"external_write"`` component wherever it occurs, not just at index 0.
    """
    parts = dotted.split(".")
    for i in range(len(parts) - 1):
        if parts[i] == "external_write" and predicate(parts[i + 1]):
            return True
    return False


def _module_matches_adapter_registry(dotted: str) -> bool:
    """True iff ``dotted`` (an import's module path) names the adapter
    registry module, anchored on an ``external_write`` component anywhere in
    the path (see ``_has_adapter_component_after_external_write``, which
    generalized this from a trailing-two-components-only match to
    ANY nesting depth). Does NOT match a BARE ``adapter_registry`` module
    with no ``external_write`` component at all — see
    ``_bare_first_component_matches_adapter`` for that
    shape, kept as a separate, narrowly-scoped check so the two do not
    double-fire on the same import (see callers)."""
    return _has_adapter_component_after_external_write(
        dotted, lambda name: name == _ADAPTER_REGISTRY_MODULE_NAME
    )


def _module_matches_adapter_profile(dotted: str) -> bool:
    """True iff ``dotted`` names an adapter-PROFILE module
    (``external_write.adapters_<vendor>``, at ANY nesting depth following the
    ``external_write`` component). The bare kernel dispatch
    module ``external_write.adapters`` never matches: ``"adapters".
    startswith("adapters_")`` is False (the prefix requires the trailing
    underscore). Does NOT match a BARE ``adapters_<vendor>`` module with no
    ``external_write`` component — see ``_bare_first_component_matches_adapter``
    for that shape."""
    return _has_adapter_component_after_external_write(
        dotted, lambda name: name.startswith(_ADAPTER_PROFILE_MODULE_PREFIX)
    )


def _bare_first_component_matches_adapter(dotted: str) -> bool:
    """True iff ``dotted``'s
    FIRST component alone — with NO ``external_write.`` prefix anywhere in
    the path — is the registry module name or an adapter-profile module name.

    Catches the bare, non-relative import shapes invisible to every existing
    check: ``import adapters_gmail`` / ``import adapter_registry`` (visited
    via ``visit_Import``, which has no ``level`` concept at all — a plain
    ``import`` statement can never be relative) and ``from adapters_gmail
    import X`` / ``from adapter_registry import Y`` at ``node.level == 0``
    (the absolute ``from`` form; the RELATIVE bare/dotted forms at
    ``node.level > 0`` are already caught by the checks above, which this
    function's callers gate around to avoid a double-count — see
    ``visit_ImportFrom``).

    The bare kernel dispatch module (``adapters``) and other legitimate bare
    capability-facing names (``operations``, ``capability_api``,
    ``read_facades_<cap>``) never match, on the identical trailing-underscore
    / exact-name grounds every other check in this module uses.
    """
    first = dotted.split(".")[0]
    return (
        first == _ADAPTER_REGISTRY_MODULE_NAME
        or first.startswith(_ADAPTER_PROFILE_MODULE_PREFIX)
    )


def _module_is_external_write_package(dotted: str) -> bool:
    """True iff ``dotted`` names the ``external_write`` package itself (not a
    submodule) — the shape a ``from external_write import X`` import produces
    (``node.module == "external_write"``). Matched by the trailing
    component, so a package-path prefix in front (e.g. a hypothetical
    ``pkg.external_write``) does not evade the match — same convention as
    ``_module_matches_adapter_registry`` / ``_module_matches_adapter_profile``
    above, one component shorter because there is no submodule component
    here at all.

    Used to catch the package-level import gap: ``from external_write import adapters_gmail`` puts the
    profile submodule name in ``alias.name`` ("adapters_gmail") rather than
    in ``node.module`` (which is just ``"external_write"``, a bare kernel
    package name never matched by the two dotted-module checks above). The
    caller pairs this predicate with a per-alias name check against
    ``_ADAPTER_REGISTRY_MODULE_NAME`` / ``_ADAPTER_PROFILE_MODULE_PREFIX`` —
    see ``visit_ImportFrom``.
    """
    parts = dotted.split(".")
    return parts[-1] == "external_write"


# ---------------------------------------------------------------------------
# Trust-zone anchor (see zones.py for the full taxonomy). Anchored to ONE
# absolute location — NOT a name the script controls and NOT a directory name
# that can be recreated elsewhere.
# ---------------------------------------------------------------------------

def _default_kernel_anchor() -> Path:
    """The canonical package anchor: scan.py's OWN installed location.

    scan.py lives INSIDE the package (``agents/lib/external_write/``), so its
    parent directory IS the real package directory. This anchor cannot be
    spoofed by a look-alike directory an author recreates somewhere else —
    identity is the absolute installed path, not a floating name. Zone
    membership itself is decided by ``zones.classify_zone`` (location under
    this anchor is necessary but not sufficient — see zones.py).
    """
    return Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _attr_chain_names(node: ast.AST) -> List[str]:
    """Return the attribute-access name chain for a Call/Attribute node, root
    last. e.g. service.spreadsheets().values().update -> the attribute names
    encountered walking the chain: ['update', 'values', 'spreadsheets'].

    Used to recognize surface-mutation chains structurally rather than by text.
    """
    names: List[str] = []
    cur = node
    while True:
        if isinstance(cur, ast.Call):
            cur = cur.func
        elif isinstance(cur, ast.Attribute):
            names.append(cur.attr)
            cur = cur.value
        else:
            break
    return names


def _leading_str(node: ast.AST) -> Union[str, None]:
    """Return a leading string literal for a node, seeing through a left-nested
    ``+`` concatenation (os.system("curl ... " + url) -> "curl ... "). This lets
    the scanner read the command name even when the rest is built at runtime."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _leading_str(node.left)
    return None


def _literal_str_args(call: ast.Call) -> List[str]:
    """Collect string literals from a call's positional args, including those
    nested one level inside a list/tuple literal (subprocess.run(['curl', ...]))
    and the leading literal of a ``+`` concatenation (os.system('curl '+url))."""
    out: List[str] = []
    for arg in call.args:
        s = _leading_str(arg)
        if s is not None:
            out.append(s)
        elif isinstance(arg, (ast.List, ast.Tuple)):
            for elt in arg.elts:
                es = _leading_str(elt)
                if es is not None:
                    out.append(es)
    return out


def _first_token(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    return text.split()[0]


# ---------------------------------------------------------------------------
# Per-file scan
# ---------------------------------------------------------------------------

class _Scanner(ast.NodeVisitor):
    """Walks one module's AST and records violations.

    Reachability for helper-indirection: the scanner reports a forbidden op at
    the AST node where it physically occurs, regardless of nesting depth inside
    a local helper function. Because the forbidden op exists somewhere in the
    file, hiding it behind a helper does not escape detection — the helper's
    body is part of the same module tree this visitor walks. (Cross-file reach
    is bounded; see module docstring.)
    """

    def __init__(self, path: str, zone: Zone = Zone.CAPABILITY):
        self.path = path
        self.violations: List[Violation] = []
        # Four rules (adapter_module_import,
        # adapter_registry_reference, introspection_escape_hatch, and
        # raw_run_operation_reference) are
        # CAPABILITY-zone-ONLY — see the module docstring's zone-scoping
        # rationale (SEALED_KERNEL legitimately imports/calls
        # get_dispatch/get_adapter/vars(cls), and run_envelope.py legitimately
        # wraps run_operation). Every other rule in this class
        # is unconditional (SEALED_KERNEL + CAPABILITY both scanned in full;
        # ADAPTER_PROFILE never reaches this class at all — see _scan_file's
        # early return).
        self._capability_zone = zone is Zone.CAPABILITY

    def _add(self, lineno: int, kind: str) -> None:
        self.violations.append(Violation(path=self.path, lineno=lineno, kind=kind))

    # --- imports -----------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _FORBIDDEN_IMPORT_ROOTS:
                self._add(node.lineno, "forbidden_import")
            if self._capability_zone:
                if (
                    _module_matches_adapter_registry(alias.name)
                    or _module_matches_adapter_profile(alias.name)
                    # A plain ``import`` statement is
                    # always absolute (no relative ``import`` syntax exists
                    # in Python), so this bare check is safe unconditionally
                    # here — no relative-import special case to avoid
                    # double-counting against.
                    or _bare_first_component_matches_adapter(alias.name)
                ):
                    self._add(node.lineno, "adapter_module_import")
                # ``import importlib`` (or any importlib submodule) itself —
                # root-matched, mirroring _FORBIDDEN_IMPORT_ROOTS's convention.
                if root == "importlib":
                    self._add(node.lineno, "introspection_escape_hatch")
                # A' module boundary, plain-import form: `import
                # external_write.run_envelope`.
                _submod = _external_write_submodule(alias.name)
                if (
                    _submod is not None
                    and _submod not in _CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES
                ):
                    self._add(node.lineno, "sealed_kernel_import")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # node.module is None for "from . import x" (relative) — never forbidden
        # (forbidden_import only bans absolute known-vendor package roots, and a
        # relative import can never spell one of those roots).
        if node.module:
            root = node.module.split(".")[0]
            if root in _FORBIDDEN_IMPORT_ROOTS:
                self._add(node.lineno, "forbidden_import")
            if self._capability_zone:
                if (
                    _module_matches_adapter_registry(node.module)
                    or _module_matches_adapter_profile(node.module)
                    # The bare, ABSOLUTE form -- ``from
                    # adapters_gmail import X`` / ``from adapter_registry
                    # import Y`` -- has node.level == 0 and node.module set
                    # to the bare name with no "external_write." prefix at
                    # all. Gated on node.level == 0 so this does not
                    # double-fire alongside the relative-specific
                    # block below (gated on node.level > 0), which already
                    # catches the identical bare-name shape for a RELATIVE
                    # import (``from .adapters_gmail import X``).
                    or (
                        node.level == 0
                        and _bare_first_component_matches_adapter(node.module)
                    )
                ):
                    self._add(node.lineno, "adapter_module_import")
                if root == "importlib":
                    self._add(node.lineno, "introspection_escape_hatch")
        # A RELATIVE import of an
        # adapter/registry submodule -- ``from .adapters_gmail import X`` /
        # ``from .adapter_registry import Y`` -- has ``node.level > 0`` and
        # ``node.module`` set to the bare submodule name, with NO
        # "external_write." prefix at all (a relative import never spells the
        # package name it is relative to). This is invisible to both the
        # absolute dotted-module check above (which requires an
        # "external_write." prefix on ``node.module``) and the package-level
        # check below (which requires ``node.module == "external_write"``
        # exactly). A file physically inside external_write/ is
        # CAPABILITY-classified by fail-closed zoning unless explicitly
        # listed as SEALED_KERNEL/ADAPTER_PROFILE, so a sibling relative
        # import is a plausible drift shape reaching adapter-profile code.
        # Gated on the module NAME alone (registry exact-name OR profile
        # prefix), not on the relative level, so an up-package relative
        # import of an unrelated module (``from ..something import x``,
        # level 2) is not incidentally flagged -- and the bare kernel
        # dispatch module (``from .adapters import run_operation``) is
        # excluded on the same grounds as the absolute/package-level checks:
        # "adapters".startswith("adapters_") is False.
        if (
            self._capability_zone
            and node.level > 0
            and node.module
            and (
                node.module == _ADAPTER_REGISTRY_MODULE_NAME
                or node.module.startswith(_ADAPTER_PROFILE_MODULE_PREFIX)
            )
        ):
            self._add(node.lineno, "adapter_module_import")
        # Importing an adapter-profile credential-provider symbol into a
        # non-adapter zone is itself the bypass: the emitted capability
        # must be UNABLE to name the provider.
        is_package_level = bool(node.module) and _module_is_external_write_package(node.module)
        # A' module boundary: CAPABILITY code may import from external_write ONLY
        # the sanctioned allowlist; `from external_write.run_envelope import ...`
        # (submod not allowlisted) is the estate's exact bypass shape.
        if self._capability_zone and node.module:
            _submod = _external_write_submodule(node.module)
            if (
                _submod is not None
                and _submod not in _CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES
            ):
                self._add(node.lineno, "sealed_kernel_import")
        # The RELATIVE bare-import
        # form -- ``from . import adapters_gmail`` / ``from . import
        # adapter_registry`` -- has ``node.level > 0`` AND ``node.module is
        # None`` (a bare "from . import" carries no module string at all),
        # with the profile/registry submodule name sitting in `alias.name`
        # instead -- the relative sibling of the package-level gap above.
        is_relative_bare = node.level > 0 and node.module is None
        for alias in node.names:
            if alias.name in _CREDENTIAL_PROVIDER_SYMBOLS:
                self._add(node.lineno, "credential_provider_reference")
            # Adapter-registry symbols are banned by NAME regardless of which
            # module the import claims to come from — e.g. a re-export shape
            # (``from external_write.adapters import get_adapter``) is caught
            # here even though the ``adapters`` module import itself is legal
            # (CAPABILITY-only — see class docstring / module docstring).
            if self._capability_zone and alias.name in _ADAPTER_REGISTRY_SYMBOLS:
                self._add(node.lineno, "adapter_registry_reference")
            # Raw kernel write primitive banned by NAME in CAPABILITY zone,
            # regardless of the source module (bare adapters, capability_api,
            # a relative/bare adapters import, or any re-export) — v0.12.0 S1.
            if self._capability_zone and alias.name == _RAW_RUN_OPERATION_SYMBOL:
                self._add(node.lineno, "raw_run_operation_reference")
            # Raw bulk-run mint primitives banned by NAME in CAPABILITY zone,
            # regardless of source module — v0.16.0 Cut 1.2 (A' / V15-3b).
            if self._capability_zone and alias.name in _RAW_BULK_MINT_SYMBOLS:
                self._add(node.lineno, "sealed_kernel_import")
            # The PACKAGE-LEVEL import
            # form -- ``from external_write import adapters_gmail`` /
            # ``from external_write import adapter_registry`` -- puts the
            # profile/registry submodule name in `alias.name`, not in
            # `node.module` (which is just "external_write" here), so it is
            # invisible to the two dotted-module checks above. Same name
            # rule as those checks (registry exact-name OR profile prefix),
            # applied to the alias instead of the module string. Bare
            # "adapters" is naturally excluded: it is neither
            # "adapter_registry" nor does it start with "adapters_".
            if (
                self._capability_zone
                and is_package_level
                and (
                    alias.name == _ADAPTER_REGISTRY_MODULE_NAME
                    or alias.name.startswith(_ADAPTER_PROFILE_MODULE_PREFIX)
                )
            ):
                self._add(node.lineno, "adapter_module_import")
            # Same name rule applied to the RELATIVE bare-import
            # form (``from . import adapters_gmail`` / ``from . import
            # adapter_registry``). Bare "adapters" / "operations" /
            # "capability_api" / "read_facades_<cap>" are naturally excluded:
            # none is "adapter_registry" nor starts with "adapters_".
            if (
                self._capability_zone
                and is_relative_bare
                and (
                    alias.name == _ADAPTER_REGISTRY_MODULE_NAME
                    or alias.name.startswith(_ADAPTER_PROFILE_MODULE_PREFIX)
                )
            ):
                self._add(node.lineno, "adapter_module_import")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # A bare-name reference to the write-credential provider (e.g. passing
        # it through to run_operation, or calling it directly). Caught on the
        # reference itself, so "holds it by reference only" is no defense.
        if node.id in _CREDENTIAL_PROVIDER_SYMBOLS:
            self._add(node.lineno, "credential_provider_reference")
        if self._capability_zone:
            if node.id in _ADAPTER_REGISTRY_SYMBOLS:
                self._add(node.lineno, "adapter_registry_reference")
            if node.id in _INTROSPECTION_BARE_NAMES:
                self._add(node.lineno, "introspection_escape_hatch")
            # Bare-name reference to the raw kernel write primitive (holding
            # it by reference, or calling it after a `from ... import
            # run_operation`) — naming it at all is the bypass. v0.12.0 S1.
            if node.id == _RAW_RUN_OPERATION_SYMBOL:
                self._add(node.lineno, "raw_run_operation_reference")
            # Bare-name reference to a raw bulk-run mint primitive — v0.16.0
            # Cut 1.2 (A' / V15-3b).
            if node.id in _RAW_BULK_MINT_SYMBOLS:
                self._add(node.lineno, "sealed_kernel_import")
        self.generic_visit(node)

    # --- calls -------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        self._check_dynamic_import(node)
        self._check_subprocess_network(node)
        self._check_credential_construction_call(node)
        # NOTE: surface-mutation detection is done in visit_Attribute, NOT here.
        # That way a mutation verb is caught whether it is the immediate func of
        # a Call (svc...update(...)) OR merely loaded and called indirectly
        # (fn = svc...update; fn(...)). The Attribute node exists in BOTH shapes
        # and the visitor reaches it via generic_visit, so there is exactly one
        # detection path and no double-count.
        self.generic_visit(node)

    # --- sequences ----------------------------------------------------------
    #
    # Checked at the LIST/TUPLE node rather than at a Call, so the argv does not
    # have to be spelled inline at the call site: ``CMD = [...]`` followed by
    # ``subprocess.run(CMD)`` is the same defect and is caught the same way, and
    # nothing here depends on WHICH function eventually receives the sequence.
    # Keying on the callee would be inferring identity from incidental structure
    # — ``run`` vs ``Popen`` vs ``check_call`` vs a local ``_sh`` helper are all
    # the same argv.

    def visit_List(self, node: ast.List) -> None:
        self._check_baked_operator_confirmation(node.elts)
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        self._check_baked_operator_confirmation(node.elts)
        self.generic_visit(node)

    def _check_baked_operator_confirmation(self, elts: List[ast.expr]) -> None:
        """A literal sitting where the operator's own words belong.

        The shape: a sequence the source spells out, one element of which is the
        confirmation flag, with a STRING LITERAL immediately after it. That is a
        command line built to record an acceptance the operator never gave — a
        machine manufacturing the one thing only a person can supply.

        ★ CEILING — ANTI-DRIFT, NOT A CONSENT ORACLE. This is an AST literal
        check on ONE container shape, and nothing more. What escapes it is not
        only computation, and saying only "computation" would leave a reader
        believing anything literal is caught. It is not:

          * COMPUTED — a variable, a module constant, an f-string, a ``join``,
            a ``format``, a value read off disk. Nothing static can decide
            whether text a program computed originated with a person.
          * LITERAL, WRONG CONTAINER — a whole shell command line passed as one
            string (``shell=True``), or a mapping of flag to value later
            expanded into argv. Every character of those is written in the
            source, and neither is a list or tuple, so neither is seen here.
          * NON-PYTHON — this scanner reads ``.py`` files only. The same
            command in a shell wrapper, a Makefile or a scheduler entry is
            invisible to it, and a shell wrapper is the likeliest home of all.

        Those are DISCLOSED RESIDUALS of this rule, not gaps someone forgot to
        close, and they are asserted by fixtures rather than only described
        here. Read a clean result as "no literal confirmation is spelled in a
        sequence in this Python file", never as "the consent here is genuine".

        Unconditional across trust zones. The kernel renders this command from
        operator text and never from a literal, so it has nothing to fear from
        the rule; a literal appearing INSIDE the kernel would be the worse
        version of the same defect, and zone-scoping the check would exempt
        exactly the code with the most authority.
        """
        for i in range(len(elts) - 1):
            if _leading_str(elts[i]) != OPERATOR_CONFIRMATION_FLAG:
                continue
            # ``_leading_str`` is this module's ONE reader of "the literal text
            # this expression starts with" — reused rather than re-implemented,
            # so a left-literal concatenation (``"yes, " + suffix``) is treated
            # here exactly as it is everywhere else in this scanner. A value
            # whose leading part is not a literal at all yields None and is the
            # disclosed residual above.
            if _leading_str(elts[i + 1]) is not None:
                self._add(elts[i + 1].lineno, "baked_operator_confirmation")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._check_surface_mutation(node)
        self._check_credential_attribute(node)
        # ``adapters_x.write_credential_provider`` — reaching the provider via
        # an attribute access on the imported adapter module.
        if node.attr in _CREDENTIAL_PROVIDER_SYMBOLS:
            self._add(node.lineno, "credential_provider_reference")
        if self._capability_zone:
            self._check_adapter_registry_attribute(node)
            self._check_introspection_attribute(node)
            # Attribute reach to the raw kernel write primitive —
            # `adapters.run_operation` / `capability_api.run_operation` /
            # `mod.run_operation` — regardless of the base expression. v0.12.0 S1.
            if node.attr == _RAW_RUN_OPERATION_SYMBOL:
                self._add(node.lineno, "raw_run_operation_reference")
            # Attribute reach to a raw bulk-run mint primitive — v0.16.0 Cut 1.2
            # (A' / V15-3b).
            if node.attr in _RAW_BULK_MINT_SYMBOLS:
                self._add(node.lineno, "sealed_kernel_import")
        self.generic_visit(node)

    def _check_adapter_registry_attribute(self, node: ast.Attribute) -> None:
        """CAPABILITY-only: an attribute reference naming an adapter-registry
        symbol (e.g. ``adapter_registry.get_adapter``, or
        ``mod.AdapterDispatch``), regardless of the base expression."""
        if node.attr in _ADAPTER_REGISTRY_SYMBOLS:
            self._add(node.lineno, "adapter_registry_reference")

    def _check_introspection_attribute(self, node: ast.Attribute) -> None:
        """CAPABILITY-only: clear dynamic-reach escape hatches reached via
        attribute access — ``sys.modules`` (base-gated on a ``sys`` Name, so
        an unrelated ``.modules`` attribute on some other object is not
        flagged) and ``importlib.import_module`` (base-gated on an
        ``importlib`` Name). ``__subclasses__`` is flagged on the attribute
        name alone, any base — unlike ``__class__``/``__dict__``/``__mro__``/
        ``__module__`` (deliberately NOT banned; see module docstring),
        ``__subclasses__`` has no ordinary-code collision risk. This
        adds the same any-base, name-alone treatment for the function/method-
        object internals in ``_FUNCTION_INTROSPECTION_ATTRS`` (``__globals__``/
        ``__code__``/``__closure__``/``__func__``/``__self__``) — see that
        set's docstring for why these do not over-fire either."""
        if node.attr == "__subclasses__" or node.attr in _FUNCTION_INTROSPECTION_ATTRS:
            self._add(node.lineno, "introspection_escape_hatch")
            return
        base = node.value
        if isinstance(base, ast.Name):
            if base.id == "sys" and node.attr == "modules":
                self._add(node.lineno, "introspection_escape_hatch")
            elif base.id == "importlib" and node.attr == "import_module":
                self._add(node.lineno, "introspection_escape_hatch")

    def _check_dynamic_import(self, node: ast.Call) -> None:
        func = node.func
        # __import__('requests')
        if isinstance(func, ast.Name) and func.id in _DYNAMIC_IMPORT_FUNCS:
            for s in _literal_str_args(node):
                if s.split(".")[0] in _FORBIDDEN_IMPORT_ROOTS:
                    self._add(node.lineno, "dynamic_import")
                    return
            # __import__ of ANY module via a dynamic mechanism is suspicious for
            # a trust gate, but we only flag known-forbidden literals to keep
            # the legal cases clean. A non-literal name is a disclosed bound.
            return
        # importlib.import_module('requests')
        if isinstance(func, ast.Attribute) and func.attr == "import_module":
            base = func.value
            if isinstance(base, ast.Name) and base.id == "importlib":
                for s in _literal_str_args(node):
                    if s.split(".")[0] in _FORBIDDEN_IMPORT_ROOTS:
                        self._add(node.lineno, "dynamic_import")
                        return

    def _check_subprocess_network(self, node: ast.Call) -> None:
        func = node.func
        is_subprocess = False
        is_os_shell = False
        if isinstance(func, ast.Attribute):
            base = func.value
            if isinstance(base, ast.Name):
                if base.id == "subprocess" and func.attr in _SUBPROCESS_FUNCS:
                    is_subprocess = True
                elif base.id == "os" and func.attr in _OS_SHELL_FUNCS:
                    is_os_shell = True
        elif isinstance(func, ast.Name):
            # bare run(...) / Popen(...) (from subprocess import run) or bare
            # system(...) / popen(...) (from os import system). Treated as a
            # shell-out entrypoint here; whether it is flagged depends entirely
            # on the network-tool literal check below — a run()/system() with no
            # network CLI literal is NOT flagged.
            if func.id in _SUBPROCESS_FUNCS:
                is_subprocess = True
            elif func.id in _OS_SHELL_FUNCS:
                is_os_shell = True

        if not (is_subprocess or is_os_shell):
            return

        # Flag only when a string-literal argument names a network CLI tool.
        for s in _literal_str_args(node):
            tool = _first_token(s)
            tool_base = Path(tool).name  # handle /usr/bin/curl
            if tool_base in _NETWORK_CLI_TOOLS:
                self._add(node.lineno, "subprocess_network")
                return

    def _check_surface_mutation(self, node: ast.Attribute) -> None:
        """Flag a surface-mutation attribute REFERENCE.

        This fires for an ``ast.Attribute`` whose ``.attr`` is a known
        external-surface mutation verb, regardless of whether the attribute is
        the immediate func of a Call (``svc...update(...)``) or merely loaded
        and invoked indirectly (``fn = svc...update; fn(...)``). Detecting at the
        attribute load — not at the Call — closes the method-reference bypass.

        Chain gating is preserved to avoid false positives on benign
        ``dict.values()`` / ``list.append()``: the ambiguous verbs
        (update/append/clear) are flagged only when the attribute chain shows a
        sheets-style surface handle. The unambiguous verbs (batchUpdate,
        update_cells) are flagged on name alone.

        The same discipline applies for Gmail: ``trash``/
        ``untrash`` are flagged on name alone (unambiguous); ``modify``/
        ``send``/``create``/``delete`` collide with common method names, so
        they are flagged only when the attribute chain shows a Gmail surface
        handle (``messages``/``drafts``/``threads``/``labels``/``filters``/
        ``settings``/``users`` — see ``_GMAIL_SURFACE_HANDLES``).
        """
        method = node.attr

        # Unambiguous external-surface verbs: flagged on name alone (single
        # path — no separate later branch). These are not English collection
        # methods, so there is no benign-collision risk.
        if method in _UNAMBIGUOUS_SURFACE_VERBS or method in _UNAMBIGUOUS_GMAIL_VERBS:
            self._add(node.lineno, "direct_api_call")
            return

        # Ambiguous verbs (update/append/clear) collide with dict/list methods;
        # flag only when the attribute sits on a sheets-style surface chain.
        if method in _FORBIDDEN_SHEETS_VERBS:
            chain = _attr_chain_names(node)
            if "values" in chain or "spreadsheets" in chain or "sheet" in chain:
                self._add(node.lineno, "direct_api_call")
            return

        # Ambiguous Gmail verbs (modify/send/create/delete) collide with
        # common method names on an arbitrary object; flag only when the
        # attribute chain shows a Gmail resource/surface handle.
        if method in _FORBIDDEN_GMAIL_VERBS:
            chain = _attr_chain_names(node)
            if any(handle in chain for handle in _GMAIL_SURFACE_HANDLES):
                self._add(node.lineno, "direct_api_call")

    def _check_credential_attribute(self, node: ast.Attribute) -> None:
        """Flag a credential-construction/widening attribute REFERENCE (the
        build-time half of credential isolation).

        Fires for an ``ast.Attribute`` whose ``.attr`` is a curated
        credential-factory/widening name (``from_service_account_file``,
        ``with_subject``, ...) — same structural approach as
        ``_check_surface_mutation``: caught whether the attribute is the
        immediate func of a Call or merely loaded and invoked indirectly
        (``fn = creds.with_subject; fn(user)``), and regardless of whether
        the vendor SDK that defines it was imported in THIS file (capability
        code can obtain a credential-shaped object via an argument, a helper
        import, or any other indirection — the credential-isolation property
        this closes is that capability code must never be able to CALL one of
        these, not merely that it must not import a specific package).
        """
        if node.attr in _CREDENTIAL_FACTORY_METHODS:
            self._add(node.lineno, "credential_construction")

    def _check_credential_construction_call(self, node: ast.Call) -> None:
        """Flag construction of a curated credential CLASS
        (``Credentials(...)``, ``ServiceAccountCredentials(...)``), whether
        called as a bare name (``Credentials(...)``) or via an attribute
        chain (``service_account.Credentials(...)``). Checked only at the
        Call site (constructing one is the operative act) — unlike the
        factory-method attributes above, these class names are common enough
        as bare identifiers that flagging every reference (not just
        construction) would be noisy.
        """
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name in _CREDENTIAL_CLASS_NAMES:
            self._add(node.lineno, "credential_construction")


# ---------------------------------------------------------------------------
# F-3B — hash-bound migration quarantine (anti-deadlock; see module docstring
# "Hash-bound migration quarantine" section above for the full contract).
# ---------------------------------------------------------------------------

_PENDING_MIGRATIONS_REL = "agents/handoffs/pending_migrations.json"


def _load_pending_migrations(project_root: Path) -> Optional[List[Dict[str, Any]]]:
    """Load ``agents/handoffs/pending_migrations.json`` relative to
    ``project_root``. Returns ``None`` — deliberately distinct from ``[]`` —
    on ANY failure to positively load a well-formed list (absent, unreadable,
    invalid JSON, or a non-list JSON value): the caller treats ``None`` as
    "no quarantine record available at all" and exempts nothing, per this
    quarantine's fail-closed contract. Never raises."""
    path = Path(project_root) / _PENDING_MIGRATIONS_REL
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _pending_entry_for_writer(
    entries: List[Dict[str, Any]], writer_relpath: str,
) -> Optional[Dict[str, Any]]:
    """The pending-migrations entry for ``writer_relpath``, only if its
    ``status`` is still ``"pending"`` — an entry some other status (e.g. a
    future ``"resolved"``/``"rebuilt"`` value written back by the rebuild
    flow) is not a live quarantine candidate. Returns ``None`` (no match) on
    anything else, including a malformed entry."""
    for entry in entries:
        if (
            isinstance(entry, dict)
            and entry.get("writer_relpath") == writer_relpath
            and entry.get("status") == "pending"
        ):
            return entry
    return None


def _quarantined_violations(
    file_path: Path,
    project_root: Optional[Path],
    violations: List[Violation],
) -> List[Violation]:
    """Filter OUT of ``violations`` any that are hash-bound-quarantined per
    ``pending_migrations.json`` — see the module docstring's "Hash-bound
    migration quarantine" section for the full (a)/(b)/(c) contract. Deny-by-
    default throughout: any step that cannot be positively verified leaves
    the ORIGINAL ``violations`` list untouched (reported in full), never a
    partial or best-guess exemption.
    """
    if not violations or project_root is None:
        return violations
    root = Path(project_root)
    try:
        writer_relpath = file_path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        # Not resolvable under project_root at all -- cannot key a relpath,
        # so there is nothing to look up. No exemption.
        return violations
    entries = _load_pending_migrations(root)
    if entries is None:
        return violations  # absent/unreadable/malformed -- fail-closed.
    entry = _pending_entry_for_writer(entries, writer_relpath)
    if entry is None:
        return violations  # this file is not a listed, queued quarantine candidate.
    recorded_hash = entry.get("paused_content_sha256")
    if not isinstance(recorded_hash, str) or not recorded_hash:
        # A pre-F-3B pending-migrations entry (queued before this hash-bound
        # quarantine existed) never recorded a paused_content_sha256 at all --
        # this is CORRECTLY, fail-closed, not exempt: with no hash to bind the
        # quarantine to, there is nothing to positively verify against. It
        # self-heals on the next `--apply` reconcile pass, which re-pauses the
        # estate fresh (recording a hash this time) rather than leaving it
        # stuck unexempted. A one-time backfill of paused_content_sha256 onto
        # existing pre-F-3B entries is deferred -- speculative, since the
        # self-heal already resolves it without one.
        return violations  # no hash recorded -- never guess, no exemption.
    try:
        current_bytes = file_path.read_bytes()
    except OSError:
        return violations
    if hashlib.sha256(current_bytes).hexdigest() != recorded_hash:
        return violations  # edited since pause-time -- no longer inert.
    recorded_raw = entry.get("violations")
    if not isinstance(recorded_raw, list):
        return violations
    recorded_set = {
        (r.get("path"), r.get("line"), r.get("kind"))
        for r in recorded_raw
        if isinstance(r, dict) and r.get("path") == writer_relpath
    }
    return [
        v for v in violations
        if (writer_relpath, v.lineno, v.kind) not in recorded_set
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _scan_file(
    file_path: Path,
    kernel_anchor: Path,
    sealed_kernel_paths: FrozenSet[str],
    adapter_profile_paths: FrozenSet[str],
    project_root: Optional[Path] = None,
) -> List[Violation]:
    if file_path.suffix != ".py":
        return []
    zone = classify_zone(
        file_path,
        kernel_anchor,
        sealed_kernel_paths=sealed_kernel_paths,
        adapter_profile_paths=adapter_profile_paths,
    )
    if zone is Zone.ADAPTER_PROFILE:
        # The ONLY zone exempt from every check below — see "Trust zones" in
        # the module docstring and zones.py for the full rationale. Zone
        # membership itself is never "anything under this path" (classify_zone
        # requires an explicit relative-path listing), so this exemption
        # cannot be obtained merely by location.
        return []
    try:
        source = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # A file whose bytes are not valid UTF-8 cannot be statically verified
        # safe, for exactly the reason the SyntaxError branch below gives. This
        # used to share that branch's `return []`, and the two answers "this file
        # passes" and "this file could not be read" were the same answer -- pure
        # fail-open, inside the trust scanner, with silence passing.
        #
        # The trigger is ordinary, not adversarial: a source saved latin-1 or
        # cp1252 (accented content, a Windows-authored file) is valid Python and
        # was invisible here. A measured consequence was a forbidden import
        # sitting in such a file and being reported by nothing, in either
        # direction -- the build-side reconcile never FLAGGED the writer, and the
        # reap treated "scan clean" as proof a flagged one had been fixed and
        # CLOSED its entry.
        #
        # Reported as `unparseable`, deliberately reusing the existing kind
        # rather than minting a second one: every consumer already handles it,
        # and what it means to a reader -- this file could not be statically
        # verified, look at it -- is exactly right for this case.
        return [Violation(path=str(file_path), lineno=1, kind="unparseable")]
    except OSError:
        # An ACCESS failure, which is a different question and is deliberately
        # NOT treated as a violation here. A permission-denied or transiently
        # unreadable `.py` anywhere in a swept tree would fail every build that
        # contains one, and this function is called with whole directories. That
        # is the fail-closed-check-that-bricks-everything shape, so closing this
        # half needs its input set scoped first rather than a matching `return`.
        # Tracked as a known gap with a named clearing authority; the entry-point
        # readers that MUST distinguish absent from inaccessible already do so on
        # their own read's exception type rather than relying on this one.
        return []
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        # An unparseable file cannot be statically verified safe. For a trust
        # gate, treat that as a violation so the build does not pass blind.
        return [Violation(path=str(file_path), lineno=1, kind="unparseable")]
    scanner = _Scanner(str(file_path), zone)
    scanner.visit(tree)
    return _quarantined_violations(file_path, project_root, scanner.violations)


def _iter_py_files(path: Path):
    if path.is_dir():
        yield from sorted(path.rglob("*.py"))
    else:
        yield path


def scan_paths(
    paths: Sequence[Union[str, Path]],
    allowed_module: str = "agents.lib.external_write",
    allowed_root: Optional[Union[str, Path]] = None,
    adapter_profile_paths: Optional[FrozenSet[str]] = None,
    sealed_kernel_paths: Optional[FrozenSet[str]] = None,
    project_root: Optional[Union[str, Path]] = None,
) -> List[Violation]:
    """Scan ``paths`` (files and/or directories) for external-write bypasses.

    Every scanned file is classified into one of three trust zones
    (``zones.classify_zone`` — see zones.py and this module's "Trust zones"
    docstring section for the full taxonomy and rationale). Only the
    ADAPTER_PROFILE zone is exempt from the checks below; SEALED_KERNEL and
    CAPABILITY code are both scanned in full.

      * ``allowed_root`` (when given) is the canonical package anchor — the
        real, installed ``external_write`` directory. Location under this
        anchor is NECESSARY but not SUFFICIENT for SEALED_KERNEL or
        ADAPTER_PROFILE membership; see below.
      * When ``allowed_root`` is None, the anchor defaults to scan.py's OWN
        installed directory (``Path(__file__).resolve().parent``), which IS the
        real package directory and cannot be spoofed by a look-alike directory.
      * ``sealed_kernel_paths`` / ``adapter_profile_paths`` (when given)
        override ``zones.SEALED_KERNEL_MODULE_PATHS`` /
        ``zones.ADAPTER_PROFILE_MODULE_PATHS`` — the explicit, relative-path
        allowlists a scanned file's path (relative to ``allowed_root``) must
        appear in to be classified SEALED_KERNEL / ADAPTER_PROFILE. A file
        that is neither listed is CAPABILITY — the most restrictive zone —
        even if it is physically located under ``allowed_root``. This is
        deliberate: a new file (or a whole new adapter directory) dropped
        under the package is NOT automatically exempted from anything merely
        by its location; build wiring / tests that need a different explicit
        set pass it here rather than the caller relying on directory
        placement alone.
      * ``project_root`` (F-3B) anchors the hash-bound migration quarantine —
        see the module docstring's "Hash-bound migration quarantine" section.
        ``agents/handoffs/pending_migrations.json`` is read relative to this
        path. Deliberately EXPLICIT OPT-IN, default ``None`` — when omitted,
        the quarantine plays NO part in this scan at all (every violation
        reports exactly as it did before this feature existed). This matters
        because `scan_paths` is also called internally as a SUB-CHECK by
        other gates (``capability_invariants.py``'s routing check,
        ``capability_health.py``, ``acceptance_ceremony.py``,
        ``coverage_gate.py``) that must keep their existing strict,
        unconditional behavior — the anti-deadlock quarantine is narrowly
        scoped to THIS module's own standalone build-time gate (the CLI
        entrypoint below, invoked as ``python3
        agents/lib/external_write/scan.py agents/`` from the operator
        project root), not silently inherited by every other consumer of
        this function merely because their own cwd happens to be the
        project root too. Distinct from ``allowed_root``: that anchors ZONE
        classification (this package's own installed location); this
        anchors the SCANNED PROJECT's own root, which is a different
        directory in every real deployment.

    ``allowed_module`` is the dotted name used for human-facing messaging only;
    it is deliberately NOT the exemption credential (keying on the name was
    spoofable — a file under an attacker-created ``.../agents/lib/external_write/``
    anywhere on disk was silently exempted).

    Returns a list of :class:`Violation`, ordered by file path then line number.
    An empty list means the build passes this gate.
    """
    anchor = (
        Path(allowed_root).resolve()
        if allowed_root is not None
        else _default_kernel_anchor()
    )
    resolved_sealed_kernel_paths = (
        sealed_kernel_paths if sealed_kernel_paths is not None
        else SEALED_KERNEL_MODULE_PATHS
    )
    resolved_adapter_profile_paths = (
        adapter_profile_paths if adapter_profile_paths is not None
        else ADAPTER_PROFILE_MODULE_PATHS
    )
    resolved_project_root = (
        Path(project_root) if project_root is not None else None
    )
    violations: List[Violation] = []
    for raw in paths:
        p = Path(raw)
        for f in _iter_py_files(p):
            violations.extend(
                _scan_file(
                    f, anchor,
                    resolved_sealed_kernel_paths,
                    resolved_adapter_profile_paths,
                    resolved_project_root,
                )
            )
    violations.sort(key=lambda v: (v.path, v.lineno, v.kind))
    return violations


# ---------------------------------------------------------------------------
# The whole-project consent sweep
#
# The baked-consent rule above is only as useful as the set of files it is
# pointed at, and the one real instance of this defect did NOT live under
# ``agents/`` — it was a top-level maintenance script. A sweep scoped to the
# directory the build gate happens to be invoked with would have been green and
# blind to the exact file it exists for; that is this family's signature
# failure and it is the reason this sweep is whole-project.
#
# Whole-project is not the same as unbounded, and an unbounded fail-closed check
# is its own failure mode — one unreadable vendored module and every build in
# the project fails. The input set is bounded twice over:
#
#   1. By the DECLARED value. A file can only trip the rule by spelling
#      ``OPERATOR_CONFIRMATION_FLAG`` as a literal, so a file whose bytes do not
#      contain that flag cannot be a violation and is never parsed. The bound is
#      derived from the rule itself, not from a guess about where code lives.
#   2. By ``NON_PROJECT_DIRS`` — this package's one declaration of the directory
#      names that are never the project's own code (imported, not re-spelled).
#      Real case: a ``.venv`` carrying third-party modules that are
#      intentionally unparseable.
#
# The prefilter reads BYTES, and of the files the walk reaches it may only
# EXCLUDE one it positively read and positively found clean. A FILE it cannot
# read stays a candidate and goes to the scanner, which answers for it —
# anything else would rebuild, one layer up, the "could not read it" == "it
# passes" conflation the read path already fixed.
#
# Stated with its limit, because the absolute form of that claim is not true:
# ``Path.rglob`` swallows a PermissionError on a DIRECTORY, so every ``.py``
# under an unreadable directory is never offered to the prefilter at all and is
# therefore excluded without being read. That is the existing behaviour of every
# walk in this package rather than anything new here, and it is a disclosed
# residual of this sweep, not a property it closes.
# ---------------------------------------------------------------------------

#: What the consent sweep is scoped to ask, and therefore all it may report.
#: A candidate file is in the sweep because it names the confirmation flag;
#: reporting every OTHER bypass class found in it would quantify the sweep over
#: a question no caller asked it — and would silently turn one narrow check into
#: a second, wider scan of files the build gate was never pointed at.
#: ``unparseable`` is in the set because silence must not read as clean: a
#: candidate that cannot be statically verified is reported, not skipped.
CONSENT_SWEEP_KINDS = frozenset({"baked_operator_confirmation", "unparseable"})


def consent_sweep_candidates(project_root: Union[str, Path]) -> List[Path]:
    """Every ``.py`` under ``project_root`` that could carry a baked operator
    confirmation — see this section's header for how the bound is derived.

    Over-inclusion is safe here (an extra clean file yields no violation);
    under-inclusion is the whole failure this sweep exists to prevent, so a file
    the walk reaches but cannot READ is INCLUDED rather than quietly dropped. A
    file under a directory the walk cannot ENTER is a different case and is not
    reached at all — see this section's header.

    To be exact about what that buys, since it would be easy to over-read: an
    INACCESSIBLE candidate is handed to ``_scan_file``, which answers ``[]`` for
    an access failure — the package's recorded, deliberately deferred gap, not
    something this function closes. What including it does buy is that the
    prefilter contributes NO SECOND fail-open of its own, and that the sweep
    becomes correct for free on the day that gap is discharged.
    """
    root = Path(project_root)
    token = OPERATOR_CONFIRMATION_FLAG.encode("ascii")
    out: List[Path] = []
    for p in sorted(root.rglob("*.py")):
        try:
            rel_parts = p.relative_to(root).parts
        except ValueError:  # pragma: no cover - defensive
            continue
        if set(rel_parts) & NON_PROJECT_DIRS:
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            # Not positively cleared. Stays in, and the scanner decides.
            out.append(p)
            continue
        # Bytes, not text: the flag is pure ASCII, so its bytes are identical
        # under utf-8, latin-1 and cp1252 alike. Decoding here would make a
        # perfectly ordinary non-utf-8 source invisible to the sweep — which is
        # the same fail-open, one layer earlier, that the read path already had.
        if token in raw:
            out.append(p)
    return out


def consent_sweep(project_root: Union[str, Path]) -> List[Violation]:
    """Scan the project for manufactured operator confirmations.

    Runs the SAME ``_scan_file`` every other caller runs — there is no second
    implementation of the rule, of zone classification, or of the migration
    quarantine — and reports only the kinds this sweep is scoped to ask about
    (``CONSENT_SWEEP_KINDS``).

    ``project_root`` is both the tree that is swept and the anchor for the
    hash-bound migration quarantine, because for this function they are the same
    directory by definition: the scanned project's own root.
    """
    root = Path(project_root)
    candidates = consent_sweep_candidates(root)
    if not candidates:
        return []
    return [v for v in scan_paths(candidates, project_root=root)
            if v.kind in CONSENT_SWEEP_KINDS]


# ---------------------------------------------------------------------------
# CLI entrypoint — run from its installed location inside the operator project
# so that the __file__-anchored allowed-module exemption is correct.
#
# TWO SURFACES, ONE ENTRYPOINT, OPPOSITE OBLIGATIONS
# ---------------------------------------------------
# Usage:
#   python3 agents/lib/external_write/scan.py <path> [<path> ...]   (build gate)
#   python3 agents/lib/external_write/scan.py --writer <relpath>    (confirm one)
#
# BUILD GATE (positional paths). Scans them, AND sweeps the whole project for a
# manufactured operator confirmation — see "The whole-project consent sweep"
# above. Deliberately not bounded by the argument: the documented invocation of
# this gate names ``agents/``, and the one real manufactured-consent script
# lived outside it. Any violation, named-path or swept, FAILS (exit 1).
#
# PER-WRITER REPAIR CONFIRMATION (``--writer``). The command ``scan_command()``
# renders into an acceptance refusal and into the state->action registry, run by
# an operator who has just repaired ONE file and is asking whether that worked.
# Its result reflects THAT FILE ONLY. A manufactured confirmation elsewhere in
# the project is still reported, loudly and by name, but as a separate finding
# that explicitly does not change the answer about the repaired file.
#
# Why the split is not a hole: this project's safety doctrine is that a coarse
# fail-closed gate blocks the dangerous TRANSITION, never the REPAIR. The
# transition surfaces — the build gate here, acceptance, completion — all keep
# the project-wide block. What this avoids is telling an operator their repair
# failed because of a file they were not repairing, which is how a gate creates
# a state nobody can leave. The hash-bound quarantine cannot absorb that case
# by construction: it exempts only a violation already recorded in that entry,
# and this kind did not exist when any entry was written.
#
# The two are told apart by the DECLARATION in the command, never by guessing
# from whether the argument names a file or a directory — the gate is legitimately
# run on a single file too.
#
# The sweep's root is the CWD, the same anchor this entrypoint already uses for
# the migration quarantine and for the same reason: the documented invocation is
# run from the operator project's top folder. Deliberately NOT ``__file__``-
# derived, even though that would be cwd-independent — this scanner also lives
# inside the toolkit that BUILDS operator projects, whose tree necessarily
# contains the rule's own fixtures, and a gate that fires on its own fixture in
# 100% of runs is a gate nobody can keep. Measured cost on a ~1000-file tree:
# well under two seconds, since only files whose bytes carry the flag are parsed.
# ---------------------------------------------------------------------------

#: Kinds for which "route this write through the approved adapters" is a TRUE
#: instruction. It is false for the other two the scanner can report -- a
#: manufactured confirmation has no write to route, and a file that would not
#: parse has nothing to read. A remediation instruction that does not fit its
#: finding is worse than none: it sends the operator to repair something that is
#: not wrong, and this gate's own text said it to every kind until now.
_ROUTING_REPAIR_EXEMPT_KINDS = frozenset({"baked_operator_confirmation", "unparseable"})

#: Prefix on a finding line that does NOT decide this invocation's result. Two
#: classes of line on one stream that look identical are two classes of line an
#: operator cannot tell apart, and the whole point of the per-writer surface is
#: that they can. Only the per-writer surface emits marked lines; the gate
#: blocks on everything it finds, so nothing there is unmarked-by-contrast.
ELSEWHERE_MARKER = "[elsewhere]"


def writer_target_refusal(writer: str):
    """Why this ``--writer`` target cannot be confirmed, or ``None`` if it can.

    Returns ``(exit_code, message)``. A per-file surface may never issue a
    positive per-file verdict about a file it did not read: "this file is clean"
    is a claim about one file, and it is false the moment the file was not
    opened. The likeliest way in is mundane — the rendered command run from the
    wrong folder, the relative path resolving to nothing.

    ABSENT and INACCESSIBLE are deliberately different answers, and the read is
    a POSITIVE one (``os.stat`` for the shape, then an actual ``open``+read for
    the permission), because a stat that succeeds proves nothing about whether
    the bytes can be got at.

    This does NOT touch, and does not need, the package's carried access-failure
    gap in ``_scan_file``. That gap is deferred because refusing inside a
    whole-DIRECTORY walk would fail every build containing one unreadable file;
    a single named target is not a directory walk, so none of that argument
    applies here and the deferral is left exactly as it is.
    """
    try:
        st = os.stat(writer)
    except (FileNotFoundError, NotADirectoryError):
        return (2, f"there is no file at {writer!r}, so nothing was checked. "
                   "Check the path, and run this from your project's top folder "
                   "— the path is read relative to where you are.")
    except OSError as exc:
        return (1, f"{writer!r} could not be read ({exc.strerror}), so NOTHING "
                   "about it was checked. This is not a clean result. It clears "
                   "once the file can be read, then run this again.")
    if _stat.S_ISDIR(st.st_mode):
        return (2, f"{FLAG_WRITER} confirms ONE repaired file, and {writer!r} is "
                   "a folder. Name the file, or run the whole-project check "
                   "instead by giving the folder with no flag.")
    if not _stat.S_ISREG(st.st_mode):
        return (2, f"{writer!r} is not an ordinary file, so nothing was checked.")
    try:
        with open(writer, "rb") as _fh:
            _fh.read(1)
    except OSError as exc:
        return (1, f"{writer!r} could not be read ({exc.strerror}), so NOTHING "
                   "about it was checked. This is not a clean result. It clears "
                   "once the file can be read, then run this again.")
    return None


def parse_cli_args(argv: Sequence[str]):
    """Strict, fail-closed parse of this entrypoint's argv.

    Returns ``(writer, paths, error)``: exactly one of ``writer`` / ``paths`` is
    set on success, and ``error`` is a message on any other input.

    DENY BY DEFAULT, following this package's CLI convention: there is no branch
    that ignores an argument it does not recognise and proceeds anyway. Mixing
    ``--writer`` with positional paths is refused rather than resolved, because
    the two shapes ask for different things and there is no correct guess.
    """
    args = list(argv)
    if not args:
        return None, [], "no path given"
    if args[0] == FLAG_WRITER:
        if len(args) != 2 or args[1].startswith("--"):
            return None, [], (
                f"{FLAG_WRITER} takes exactly one file, and cannot be combined "
                "with other paths")
        return args[1], [], None
    for a in args:
        if a.startswith("--"):
            return None, [], f"unrecognised option {a!r}"
    return None, args, None


def cli_findings(writer: Optional[str], paths: Sequence[str], project_root: Path):
    """``(blocking, elsewhere)`` for one invocation.

    ``blocking`` decides the exit status. ``elsewhere`` is the project-wide
    consent finding that a per-writer confirmation must report without failing
    on -- always empty for the build gate, which blocks on everything.

    The argument the gate is given is relative and the sweep's paths are
    absolute, so both the deduplication and the is-this-my-target test compare
    RESOLVED file identity rather than the raw ``path`` string.
    """
    if writer is not None:
        blocking = scan_paths([writer], project_root=project_root)
        target = str(Path(writer).resolve())
        elsewhere = [v for v in consent_sweep(project_root)
                     if str(Path(v.path).resolve()) != target]
        return blocking, elsewhere

    blocking = list(scan_paths(list(paths), project_root=project_root))
    seen = {(str(Path(v.path).resolve()), v.lineno, v.kind) for v in blocking}
    for v in consent_sweep(project_root):
        key = (str(Path(v.path).resolve()), v.lineno, v.kind)
        if key not in seen:
            seen.add(key)
            blocking.append(v)
    blocking.sort(key=lambda v: (v.path, v.lineno, v.kind))
    return blocking, []


_CONSENT_NOTE = (
    "hardcode an operator confirmation: the words that get recorded as the "
    "operator's own acceptance are written into the file, not said by them. "
    "Text a file supplies is not the operator's, whatever it says. "
    "The phase FAILS while any of them stands, and each one "
    "clears once its file no longer carries that text and the operator gives "
    "the confirmation themselves. Note the reach of this check honestly: it "
    "sees only a confirmation spelled out as a literal in a Python file, so a "
    "clean result means no such literal was found -- it is not evidence that "
    "the acceptances in this project are genuine."
)

_UNPARSEABLE_NOTE = (
    "could not be read as Python at all, so nothing about them was checked. "
    "There is no write to reroute here. The phase FAILS while any of them "
    "stands, and each one clears when its file parses."
)


if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _writer, _paths, _err = parse_cli_args(_sys.argv[1:])
    if _err is not None:
        print(
            f"{_err}\n"
            "Usage: python3 scan.py <path> [<path> ...]      (check these paths, "
            "and the whole project for a manufactured operator confirmation)\n"
            f"   or: python3 scan.py {FLAG_WRITER} <file>    (confirm ONE repaired "
            "file; its result is about that file only)\n"
            "Run it from your project's top folder.",
            file=_sys.stderr)
        _sys.exit(2)

    if _writer is not None:
        # Before any verdict about this one file, prove it IS one file and that
        # its bytes can actually be got at. A positive per-file claim about a
        # file nobody opened is the failure this surface exists to avoid.
        _refusal = writer_target_refusal(_writer)
        if _refusal is not None:
            _code, _why = _refusal
            print(_why, file=_sys.stderr)
            _sys.exit(_code)

    # (F-3B) This standalone CLI invocation IS the anti-deadlock target the
    # hash-bound migration quarantine exists for -- the operator's real
    # rebuild-time gate, conventionally run FROM the project root
    # (``python3 agents/lib/external_write/scan.py agents/``). Opts in
    # explicitly by passing the real cwd as project_root; every OTHER
    # scan_paths() caller in this package (capability_invariants.py,
    # capability_health.py, acceptance_ceremony.py, coverage_gate.py) omits
    # project_root and keeps its existing strict, unconditional behavior --
    # see scan_paths's own docstring for why that is deliberate.
    _violations, _elsewhere = cli_findings(_writer, _paths, Path.cwd())

    for _v in _violations:
        print(f"{_v.path}:{_v.lineno}: {_v.kind}")

    # Each note goes only to the findings it is TRUE of.
    _routing = [_v for _v in _violations
                if _v.kind not in _ROUTING_REPAIR_EXEMPT_KINDS]
    _baked = [_v for _v in _violations if _v.kind == "baked_operator_confirmation"]
    _broken = [_v for _v in _violations if _v.kind == "unparseable"]
    if _routing:
        print(
            f"\n{len(_routing)} violation(s) found. "
            "Every external write must route through the approved adapters "
            "in agents/lib/external_write/. "
            "The phase FAILS and cannot be accepted until every flagged write "
            "is routed through the approved external-write operations.",
            file=_sys.stderr,
        )
    if _baked:
        print(f"\n{len(_baked)} of these {_CONSENT_NOTE}", file=_sys.stderr)
    if _broken:
        print(f"\n{len(_broken)} of these {_UNPARSEABLE_NOTE}", file=_sys.stderr)

    if _elsewhere:
        # A per-writer confirmation. Say the project-wide finding out loud, and
        # say just as plainly that it is not about the file being confirmed --
        # an operator who repaired exactly what they were told to repair must
        # never read this as their repair having failed.
        #
        # Every reference here is to a MARKER or to a named line, never to a
        # position. These lines go to stdout and the note goes to stderr; stderr
        # is unbuffered, so "above" and "below" describe an order that does not
        # survive a pipe, and when the target is itself dirty there is no
        # "below" at all.
        for _v in _elsewhere:
            print(f"{ELSEWHERE_MARKER} {_v.path}:{_v.lineno}: {_v.kind}")
        print(
            f"\nSeparately, and NOT about {_writer}: {len(_elsewhere)} finding(s) "
            f"elsewhere in this project, each on a line marked "
            f"{ELSEWHERE_MARKER}. They do not change the result for {_writer}, "
            f"which is given on its own line starting '{_writer}: '. They still "
            "need attention in their own right.",
            file=_sys.stderr,
        )

    if _writer is not None:
        # Exactly one result line about the target, whichever way it went. The
        # note above promises one; a promise kept only on the passing branch is
        # the branch an operator never sees when it matters.
        _own = len(_violations)
        if _own:
            print(f"{_writer}: NOT clean -- {_own} finding(s) in this file.")
        else:
            print(f"{_writer}: clean -- no findings in this file.")
        _sys.exit(1 if _own else 0)

    if _violations:
        _sys.exit(1)
    print("Bypass scan passed — no violations found.")
    _sys.exit(0)
