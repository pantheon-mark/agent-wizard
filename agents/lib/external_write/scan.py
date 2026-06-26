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
                         anywhere outside the allowed module. Both ``import x``
                         and ``from x import y`` forms; submodules
                         (urllib.request) match the banned top-level package.
  direct_api_call     -- referencing a known external-surface mutation method
                         by name (values().update, batchUpdate, append,
                         update_cells, ...). Caught whether the mutation verb is
                         the immediate func of a Call OR merely loaded as an
                         attribute and called indirectly (``fn = svc...update;
                         fn(...)``). Caught wherever it appears, including inside
                         a local helper function (so helper indirection is
                         covered: the forbidden reference inside the helper is
                         itself reported).
  dynamic_import      -- importlib.import_module('requests') / __import__(...)
                         with a banned literal module name (defeats static
                         ``import`` detection).
  subprocess_network  -- subprocess.run/Popen/call/... or os.system / os.popen
                         whose command invokes a network tool (curl, wget,
                         http, httpie, ...). Detected from list/str literal
                         arguments.

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

------------------------------------------------------------------------------
Allowed-module identity (anchored, NOT a floating directory name)
------------------------------------------------------------------------------
  Exemption is anchored to a single canonical absolute location: the real,
  installed adapter directory. By default that is ``scan.py``'s own directory
  (``Path(__file__).resolve().parent``) — scan.py lives INSIDE the allowed
  module, so its location IS the adapter directory and cannot be spoofed by a
  look-alike directory an author recreates elsewhere. A scanned file is exempt
  IFF its resolved path is that anchor directory or a descendant of it. The
  caller may override the anchor explicitly (``scan_paths(..., allowed_root=)``)
  so build wiring can pass the canonical adapter dir. The dotted
  ``allowed_module`` string is used for messaging only — it is NOT the exemption
  credential. (Earlier versions keyed exemption on the directory NAME appearing
  anywhere in the path; that was spoofable — a file under an attacker-created
  ``.../agents/lib/external_write/`` anywhere on disk was silently exempted.
  Fixed: identity is the absolute anchor, not a floating name.)
"""

import ast
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Union


class Violation(NamedTuple):
    """One detected bypass.

    path:   the file the violation was found in.
    lineno: the line of the offending AST node.
    kind:   what was caught — one of:
              'direct_api_call', 'forbidden_import',
              'dynamic_import', 'subprocess_network'.
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


# ---------------------------------------------------------------------------
# Allowed-module identity (anchored to ONE absolute location — NOT a name the
# script controls and NOT a directory name that can be recreated elsewhere)
# ---------------------------------------------------------------------------

def _default_allowed_root() -> Path:
    """The canonical allowed-module directory: scan.py's OWN installed location.

    scan.py lives INSIDE the allowed module (``agents/lib/external_write/``), so
    its parent directory IS the real adapter directory. This anchor cannot be
    spoofed by a look-alike directory an author recreates somewhere else —
    identity is the absolute installed path, not a floating name.
    """
    return Path(__file__).resolve().parent


def _is_inside_allowed_module(file_path: Path, allowed_root: Path) -> bool:
    """A file is INSIDE the allowed module iff its resolved path is the anchor
    directory or a descendant of it.

    Identity is decided by absolute location, not by any name a script could
    spoof: a file under an attacker-recreated ``.../agents/lib/external_write/``
    directory ELSEWHERE on disk is NOT exempt, and a malicious
    ``# agents.lib.external_write`` comment or import string is irrelevant.
    """
    resolved = file_path.resolve()
    try:
        # Path.is_relative_to is available in Python 3.9+. is_relative_to(self)
        # is True, so the anchor directory itself is also exempt.
        return resolved.is_relative_to(allowed_root)
    except AttributeError:  # pragma: no cover - py<3.9 fallback
        try:
            resolved.relative_to(allowed_root)
            return True
        except ValueError:
            return False


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

    def __init__(self, path: str):
        self.path = path
        self.violations: List[Violation] = []

    def _add(self, lineno: int, kind: str) -> None:
        self.violations.append(Violation(path=self.path, lineno=lineno, kind=kind))

    # --- imports -----------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in _FORBIDDEN_IMPORT_ROOTS:
                self._add(node.lineno, "forbidden_import")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # node.module is None for "from . import x" (relative) — never forbidden.
        if node.module:
            root = node.module.split(".")[0]
            if root in _FORBIDDEN_IMPORT_ROOTS:
                self._add(node.lineno, "forbidden_import")
        self.generic_visit(node)

    # --- calls -------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        self._check_dynamic_import(node)
        self._check_subprocess_network(node)
        # NOTE: surface-mutation detection is done in visit_Attribute, NOT here.
        # That way a mutation verb is caught whether it is the immediate func of
        # a Call (svc...update(...)) OR merely loaded and called indirectly
        # (fn = svc...update; fn(...)). The Attribute node exists in BOTH shapes
        # and the visitor reaches it via generic_visit, so there is exactly one
        # detection path and no double-count.
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._check_surface_mutation(node)
        self.generic_visit(node)

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
        """
        method = node.attr

        # Unambiguous external-surface verbs: flagged on name alone (single
        # path — no separate later branch). These are not English collection
        # methods, so there is no benign-collision risk.
        if method in _UNAMBIGUOUS_SURFACE_VERBS:
            self._add(node.lineno, "direct_api_call")
            return

        # Ambiguous verbs (update/append/clear) collide with dict/list methods;
        # flag only when the attribute sits on a sheets-style surface chain.
        if method in _FORBIDDEN_SHEETS_VERBS:
            chain = _attr_chain_names(node)
            if "values" in chain or "spreadsheets" in chain or "sheet" in chain:
                self._add(node.lineno, "direct_api_call")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _scan_file(file_path: Path, allowed_root: Path) -> List[Violation]:
    if file_path.suffix != ".py":
        return []
    if _is_inside_allowed_module(file_path, allowed_root):
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
    scanner = _Scanner(str(file_path))
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
) -> List[Violation]:
    """Scan ``paths`` (files and/or directories) for external-write bypasses.

    Code WITHIN the allowed module (the external_write package) is exempt — that
    is where the real network calls legitimately live. Exemption is anchored to
    a single absolute location, NOT to a directory name that can be recreated
    elsewhere:

      * ``allowed_root`` (when given) is the canonical adapter directory. A
        scanned file is exempt iff its resolved path is that directory or a
        descendant of it. Build wiring should pass the real adapter dir here.
      * When ``allowed_root`` is None, the anchor defaults to scan.py's OWN
        installed directory (``Path(__file__).resolve().parent``), which IS the
        real adapter directory and cannot be spoofed by a look-alike directory.

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
        else _default_allowed_root()
    )
    violations: List[Violation] = []
    for raw in paths:
        p = Path(raw)
        for f in _iter_py_files(p):
            violations.extend(_scan_file(f, anchor))
    violations.sort(key=lambda v: (v.path, v.lineno, v.kind))
    return violations
