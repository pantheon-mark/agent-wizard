"""Deterministic AST bypass scanner — the build-time root-of-trust.

Every external write in a wizard-generated operator system must route through
the emitted named-operation adapters in the external_write package. This module
is the deterministic, build-time check that FAILS THE BUILD if any other script
mutates an external surface OUTSIDE those adapters.

It is the real enforcement. The runtime PreToolUse hook is a disclosed backstop
only: it classifies by command shape and is structurally blind to per-project
interpreter-script writes. A grep is trivially defeated (helper indirection,
dynamic import, subprocess curl). Therefore the cross-vendor design consult was
explicit that this gate MUST be deterministic AST + call-graph analysis, NOT
grep and NOT LLM judgment. Treat every bypass below as adversarial: assume a
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
                         update_cells, ...; and, as of Task R2/NF1, Gmail's
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
                         file (Task 5 -- see "Trust zones" below). The symbol
                         set is CURATED, not exhaustive (a known, tracked
                         limitation) -- the same disclosed-bound spirit as
                         ``_FORBIDDEN_IMPORT_ROOTS``. Two further evasions of
                         this curated symbol check are disclosed, not closed
                         (T5 -- Task R2, same "no silent caps" spirit as the
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
                         reference is flagged too). The BL-1 / F-33 credential-
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
  adapter_registry_reference -- (Task R7-T4 — cross-vendor-ratified defense-in-
                         depth, sealing the architecture Tasks R7-T1..T3 built)
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
                           * ``adapter_registry_reference`` — naming a
                             registry symbol (``get_adapter``, ``get_dispatch``,
                             ``register_adapter``, ``unregister_adapter``,
                             ``_REGISTRY``, ``AdapterDispatch``) as an import
                             alias, a bare name, or an attribute — regardless
                             of which module the capability claims to import
                             it from (so a re-export shape, e.g. ``from
                             external_write.adapters import get_adapter``,
                             is caught on the NAME even though the bare
                             ``adapters`` module import itself is legal).
                             Modeled directly on ``credential_provider_reference``
                             above (visit_ImportFrom / visit_Name /
                             visit_Attribute against a curated symbol set).
                         Together these make the mutable Adapter instance and
                         the adapter-profile modules that define
                         ``build_write_client`` STATICALLY unreachable from
                         capability code — closing the reach path Task R7-T2's
                         ``AdapterDispatch`` capture defends at runtime
                         (reassigning an instance attribute after obtaining it
                         via ``get_adapter`` no longer hijacks dispatch — see
                         ``adapter_registry.AdapterDispatch``) by removing the
                         capability's ability to even NAME ``get_adapter`` in
                         the first place.
  introspection_escape_hatch -- (Task R7-T4, CAPABILITY-zone-ONLY, same
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
                         over-fire on unremarkable Python.

------------------------------------------------------------------------------
Bounds NOT covered at v0 (disclosed — no silent caps)
------------------------------------------------------------------------------
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
    ``read_facade.ReadFacade`` itself (NF2 — external-write-gate-
    generalization fix-wave, Task R2: reconciled with R4's read_facade
    hardening below, which this bullet previously undersold):

      (a) CLOSED for normal attribute access, as of R4. ``__setattr__``
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
    (Task R7-T4 — correcting an overclaim (NF1) a cross-vendor review
    flagged in this section's prior wording). Two known false negatives,
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
    (BL-1 / F-33) is itself breached — and Task R7-T4's
    ``adapter_registry_reference`` / ``adapter_module_import`` /
    ``introspection_escape_hatch`` rules are precisely what closes the
    static reach paths to that keystone. This module does not attempt to
    chase every conceivable indirection into value-flow analysis; it
    catches the common, single-expression shapes and discloses the rest.
  * Introspection beneath ``get_adapter``/``build_write_client`` via
    ``__class__``/``__dict__``/``__mro__``/``__module__`` (Task R7-T4).
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
    checks (Task R7-T4). The ``sys.modules`` and ``importlib.import_module``
    checks in ``_check_introspection_attribute`` anchor on a bare Name node
    (``base.id == "sys"`` / ``"importlib"``). An aliased import
    (``import sys as s``) reference to ``s.modules[...]`` evades the check
    because the base name is "s", not "sys" — a disclosed deterministic-
    scanner bound, not a silent gap. Consistent with the credential-isolation
    keystone (BL-1 / F-33) being the real guarantee; this module discloses
    what it does not deterministically catch.
  * ``external_write.adapter_registry`` reached via ``from external_write
    import adapter_registry`` (importing the SUBMODULE NAME off the
    package, rather than a dotted ``external_write.adapter_registry``
    path) is NOT matched by ``adapter_module_import``'s module-string
    check, and ``adapter_registry`` is not itself in the
    ``adapter_registry_reference`` symbol set (only names reachable
    THROUGH the module — ``get_adapter``, ``get_dispatch``, etc. — are).
    A curated, disclosed gap (same spirit as every other curated symbol
    surface in this module) rather than a silently assumed closure; every
    real caller in this codebase (kernel, adapter-profile, and every
    fixture in this task) uses the dotted ``external_write.X`` form this
    check does match.

------------------------------------------------------------------------------
Trust zones (replaces the old blanket "whole external_write/ tree is exempt"
rule — see ``zones.py`` for the full rationale and the canonical taxonomy)
------------------------------------------------------------------------------
  Every scanned file is classified into exactly one of three zones
  (``zones.classify_zone``):

    SEALED_KERNEL    -- the gate machinery (run_operation, write_gate,
                        broker, receipt validation, the invocation ledger,
                        operations/contracts/proof_hash/effects_manifest,
                        the adapter registry, the read facade, this scanner
                        and the coverage gate). Held to the SAME checks as
                        capability code below — it simply never trips them,
                        because none of this code needs a vendor SDK import
                        or a write-capable credential. ONE deliberate
                        exception (Task R7-T4): the adapter_module_import /
                        adapter_registry_reference / introspection_escape_hatch
                        rules are CAPABILITY-zone-ONLY and do NOT apply here —
                        adapters.py and effects_manifest.py are the registry's
                        own intended kernel-side consumers (get_dispatch /
                        get_adapter), and read_facade.py legitimately calls
                        vars(cls) — see those rules' docstring sections.
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
"""

import ast
from pathlib import Path
from typing import FrozenSet, List, NamedTuple, Optional, Sequence, Union

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


class Violation(NamedTuple):
    """One detected bypass.

    path:   the file the violation was found in.
    lineno: the line of the offending AST node.
    kind:   what was caught — one of:
              'direct_api_call', 'forbidden_import',
              'dynamic_import', 'subprocess_network',
              'credential_construction', 'credential_provider_reference',
              'adapter_module_import', 'adapter_registry_reference',
              'introspection_escape_hatch',
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

# NF1 (external-write-gate-generalization fix-wave, Task R2) — Gmail mutation
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

# Credential-access surface (Task 5 — credential-isolation build-time half).
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
# T5 (Task R2) disclosed bounds, not closed here -- see the module docstring's
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

# Adapter-profile credential-PROVIDER symbols (Task R1 / BL-1 — the
# credential-isolation keystone, finding F-33). A write-capable credential is
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
        # The retired module-level provider name (pre-BL-1 emitted shape).
        "write_credential_provider",
        # The Adapter method that provisions the write-capable client
        # (``build_write_client(op)``). BL-1 residual: after the provider was
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
# CAPABILITY-zone-ONLY bans (Task R7-T4 — cross-vendor-ratified defense-in-
# depth, sealing the architecture Tasks R7-T1..T3 built). Unlike every rule
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
_ADAPTER_REGISTRY_SYMBOLS = frozenset(
    {
        "get_adapter",
        "get_dispatch",
        "register_adapter",
        "unregister_adapter",
        "_REGISTRY",
        "AdapterDispatch",
    }
)

# Dynamic-reach escape hatches — bare builtin names banned by NAME (Name
# node). Unambiguous enough (unlike, say, a hypothetical "update"/"delete")
# that flagging every bare reference does not risk the noisy false-positive
# collision _CREDENTIAL_CLASS_NAMES's design note warns about.
_INTROSPECTION_BARE_NAMES = frozenset({"__import__", "globals", "vars"})


def _module_matches_adapter_registry(dotted: str) -> bool:
    """True iff ``dotted`` (an import's module path) names the adapter
    registry module — matched by its trailing two dotted components, so a
    package-path prefix in front (e.g. a hypothetical
    ``pkg.external_write.adapter_registry``) does not evade the match."""
    parts = dotted.split(".")
    return len(parts) >= 2 and parts[-2] == "external_write" and parts[-1] == _ADAPTER_REGISTRY_MODULE_NAME


def _module_matches_adapter_profile(dotted: str) -> bool:
    """True iff ``dotted`` names an adapter-PROFILE module
    (``external_write.adapters_<vendor>``) — same trailing-two-components
    match as above. The bare kernel dispatch module
    ``external_write.adapters`` never matches: ``"adapters".startswith(
    "adapters_")`` is False (the prefix requires the trailing underscore)."""
    parts = dotted.split(".")
    return (
        len(parts) >= 2
        and parts[-2] == "external_write"
        and parts[-1].startswith(_ADAPTER_PROFILE_MODULE_PREFIX)
    )


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
        # Task R7-T4: three rules (adapter_module_import,
        # adapter_registry_reference, introspection_escape_hatch) are
        # CAPABILITY-zone-ONLY — see the module docstring's zone-scoping
        # rationale (SEALED_KERNEL legitimately imports/calls
        # get_dispatch/get_adapter/vars(cls)). Every other rule in this class
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
                ):
                    self._add(node.lineno, "adapter_module_import")
                # ``import importlib`` (or any importlib submodule) itself —
                # root-matched, mirroring _FORBIDDEN_IMPORT_ROOTS's convention.
                if root == "importlib":
                    self._add(node.lineno, "introspection_escape_hatch")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # node.module is None for "from . import x" (relative) — never forbidden.
        if node.module:
            root = node.module.split(".")[0]
            if root in _FORBIDDEN_IMPORT_ROOTS:
                self._add(node.lineno, "forbidden_import")
            if self._capability_zone:
                if (
                    _module_matches_adapter_registry(node.module)
                    or _module_matches_adapter_profile(node.module)
                ):
                    self._add(node.lineno, "adapter_module_import")
                if root == "importlib":
                    self._add(node.lineno, "introspection_escape_hatch")
        # Importing an adapter-profile credential-provider symbol into a
        # non-adapter zone is itself the bypass (BL-1): the emitted capability
        # must be UNABLE to name the provider.
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
        ``__subclasses__`` has no ordinary-code collision risk."""
        if node.attr == "__subclasses__":
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

        NF1 (Task R2) adds the same discipline for Gmail: ``trash``/
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
        """Flag a credential-construction/widening attribute REFERENCE (Task 5
        — the build-time half of credential isolation).

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
# Public API
# ---------------------------------------------------------------------------

def _scan_file(
    file_path: Path,
    kernel_anchor: Path,
    sealed_kernel_paths: FrozenSet[str],
    adapter_profile_paths: FrozenSet[str],
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
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        # An unparseable file cannot be statically verified safe. For a trust
        # gate, treat that as a violation so the build does not pass blind.
        return [Violation(path=str(file_path), lineno=1, kind="unparseable")]
    scanner = _Scanner(str(file_path), zone)
    scanner.visit(tree)
    return scanner.violations


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
    violations: List[Violation] = []
    for raw in paths:
        p = Path(raw)
        for f in _iter_py_files(p):
            violations.extend(
                _scan_file(
                    f, anchor,
                    resolved_sealed_kernel_paths,
                    resolved_adapter_profile_paths,
                )
            )
    violations.sort(key=lambda v: (v.path, v.lineno, v.kind))
    return violations


# ---------------------------------------------------------------------------
# CLI entrypoint — run from its installed location inside the operator project
# so that the __file__-anchored allowed-module exemption is correct.
#
# Usage:
#   python3 agents/lib/external_write/scan.py <path> [<path> ...]
#
# Scans the given paths (files or directories) for external-write bypasses.
# Exits 0 if no violations are found (build passes this gate).
# Exits 1 and prints each violation if any are found (build FAILS).
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _paths = _sys.argv[1:]
    if not _paths:
        print("Usage: python3 scan.py <path> [<path> ...]", file=_sys.stderr)
        _sys.exit(2)

    _violations = scan_paths(_paths)
    if _violations:
        for _v in _violations:
            print(f"{_v.path}:{_v.lineno}: {_v.kind}")
        print(
            f"\n{len(_violations)} violation(s) found. "
            "Every external write must route through the approved adapters "
            "in agents/lib/external_write/. "
            "The phase FAILS and cannot be accepted until every flagged write "
            "is routed through the approved external-write operations.",
            file=_sys.stderr,
        )
        _sys.exit(1)
    else:
        print("Bypass scan passed — no violations found.")
        _sys.exit(0)
