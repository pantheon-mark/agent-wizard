"""Emitted capability-identity module (Task A1 / A3.2 — cross-vendor design
consult finding: a capability's identity was split across four names in the
field, which broke migration-close, health, and pause markers).

Why this exists
----------------
A single capability has historically been referred to by up to four
different strings, depending on which part of the system is speaking:

  * ``descriptor_id``  -- the ``id`` field in a
    ``security/capability_descriptors.json`` entry.
  * ``mechanism_id``   -- the ``mechanism_id`` field of an entry in
    ``agents/handoffs/pending_migrations.json`` (how upgrade-reconcile
    queues a migration against a capability).
  * ``module_stem``    -- the ``<capability_id>`` in
    ``agents/capabilities/<capability_id>_capability.py``.
  * ``surface``        -- the EXTERNAL SYSTEM the capability talks to (a
    module-level ``SURFACE = "..."`` constant in the capability's own
    source), e.g. ``acme_crm_sync``'s surface is ``acme_crm``.

The estate finding was a capability whose module stem (``inbox_management``)
differed from its descriptor id (``inbox-labels``) -- three names for one
capability, with nothing to say they were the same thing. This module gives
every lifecycle consumer (migration-close, health, pause markers) ONE
canonical identity to resolve any of those names TO:
``build_capability_index(project_root).resolve(raw, namespace)``.

Canonical id
------------
The canonical id is the MODULE-DERIVED ``capability_id`` -- the stem of
``agents/capabilities/<capability_id>_capability.py`` with the
``_capability`` suffix stripped. This is the identity the scaffold itself
owns (``capability_code_scaffold.py`` writes the file at that path), so it
is authoritative regardless of what a descriptor or migration-queue entry
calls the same capability. A descriptor id or mechanism id that differs from
every module stem is an ALIAS to be resolved to the one canonical id it
refers to -- never a second identity in its own right.

Surface is excluded from identity
----------------------------------
``surface`` is a SEPARATE field on ``CapabilityIdentity``, preserved for
callers that need the external-system identifier, but it is NEVER an
identity-equality token: two DIFFERENT capabilities may legitimately declare
the same surface (``gmail_label`` and ``gmail_archive`` both talk to
``gmail``). Resolving a surface string that is shared by two or more
canonicals is therefore fail-closed AMBIGUOUS, never a guess at which
capability was meant -- see ``build_capability_index`` / ``resolve`` below.

Fail-closed, no fuzzy matching
--------------------------------
``resolve`` is exact-alias-only. There is no suffix stripping, no
similarity scoring, no "closest match" fallback of any kind:

  * a raw token that maps to ZERO canonicals raises
    ``IdentityResolutionError(kind="unresolved")``.
  * a raw token that maps to TWO OR MORE DIFFERENT canonicals raises
    ``IdentityResolutionError(kind="ambiguous")``.
  * only a token that maps to EXACTLY ONE canonical resolves.

Both error kinds carry a plain-language ``.operator_message`` (no
traceback text) -- this runs inside a non-technical operator's project, and
whatever reads this module's output (an agent's orientation prose, a
migration-close step) must be able to surface *why* a lookup failed without
ever showing raw Python error text.

How aliases are discovered (still exact, never fuzzy)
-------------------------------------------------------
For each of ``descriptor_id`` and ``mechanism_id``, a raw value that
EXACTLY EQUALS an existing module stem is trivially that stem's own
canonical id -- no ambiguity possible. A raw value that does not match any
module stem (the estate case: descriptor id ``inbox-labels`` vs. module stem
``inbox_management``) can only be safely attributed to a canonical WITHOUT
guessing if there is exactly one canonical in the whole project: with only
one capability that could possibly be meant, there is no fuzzy/similarity
judgement involved in attributing an unmatched name to it -- it is the only
candidate that exists. The moment a project has two or more capabilities,
an unmatched descriptor/mechanism id has no unambiguous default target and
is left unresolved (never silently guessed) until something disambiguates
it (typically: the descriptor set gets corrected to use the real
capability_id, per ``wizard/skills/add-capability.md``'s own convention that
``mechanism_id == capability_id``).

``surface`` never gets this single-canonical fallback: it is read directly
from each module's OWN declared ``SURFACE`` constant, so it is always
directly (not by elimination) attributed to the module that declared it;
what can still make it ambiguous AS A LOOKUP KEY is two different modules
declaring the identical surface value (see above).

AST-only extraction, never import (mirrors capability_health.py's own
AST-first, import-second discipline)
------------------------------------------------------------------------------
``SURFACE`` is extracted by parsing each capability module's source with
``ast`` and reading the value of the first module-level
``SURFACE = <string literal>`` assignment. This module NEVER imports a
capability file to read its constants -- importing runs the module's
top-level code, which this package's identity resolver has no business
triggering (see ``capability_health.py``'s own docstring on why an import
must never be an incidental side effect of introspection). A file that
cannot be parsed, or that declares no ``SURFACE`` constant at all (a legacy
capability written before this convention), simply has ``surface=None`` --
that is a normal, non-error input, not a build failure.

Stdlib only -- this module ships into the operator's own runtime,
``agents/lib/external_write/``.
"""

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Literal, Optional, Set

# The four resolvable identity namespaces, plus "unknown" for a caller that
# does not know which namespace a raw token came from (searches all four).
Namespace = Literal["module_stem", "descriptor_id", "mechanism_id", "surface", "unknown"]
ErrorKind = Literal["ambiguous", "unresolved"]


# ---------------------------------------------------------------------------
# Project-root-relative locations this module reads. Duplicated-by-value from
# capability_health.py's own constants of the same name (never imported
# across modules -- each emitted-runtime module reads these paths
# independently; see capability_health.py's own header comment on this
# convention).
# ---------------------------------------------------------------------------

CAPABILITIES_DIR_REL = "agents/capabilities"
CAPABILITY_FILE_SUFFIX = "_capability.py"
DESCRIPTOR_SET_REL = "security/capability_descriptors.json"
MIGRATION_QUEUE_REL = "agents/handoffs/pending_migrations.json"

# The four NAMED namespaces (excludes "unknown", which is not itself a map --
# it searches all four of these when a caller does not know which namespace
# a raw token came from).
_NAMED_NAMESPACES: tuple = ("module_stem", "descriptor_id", "mechanism_id", "surface")


class IdentityResolutionError(Exception):
    """Raised by ``CapabilityIndex.resolve`` when a raw token cannot be
    resolved to EXACTLY ONE canonical capability id. Fail-closed: this is
    raised for both failure directions (no match, and more-than-one match)
    -- there is no fuzzy/best-effort fallback in either case.

    ``kind`` is ``"unresolved"`` (the raw token matched no canonical) or
    ``"ambiguous"`` (the raw token matched two or more DIFFERENT
    canonicals). ``operator_message`` is plain language describing the
    failure, with no traceback text -- this is read by an agent's
    orientation prose / a migration-close step inside a non-technical
    operator's project, never surfaced as a raw Python exception.
    """

    def __init__(self, kind: ErrorKind, raw: str, namespace: Namespace,
                 candidates: Optional[List[str]] = None) -> None:
        self.kind = kind
        self.raw = raw
        self.namespace = namespace
        self.candidates = list(candidates) if candidates else []
        self.operator_message = _build_operator_message(kind, raw, namespace, self.candidates)
        super().__init__(self.operator_message)


def _build_operator_message(kind: ErrorKind, raw: str, namespace: Namespace, candidates: List[str]) -> str:
    ns_label = "an unspecified" if namespace == "unknown" else f'a "{namespace}"'
    if kind == "ambiguous":
        joined = ", ".join(sorted(candidates))
        return (
            f'The value "{raw}" (looked up as {ns_label} identifier) matches more than '
            f"one capability ({joined}) and cannot be resolved automatically. This usually "
            f'means two different capabilities share the same external identifier. Use '
            f"each capability's own capability_id directly instead of \"{raw}\"."
        )
    return (
        f'The value "{raw}" (looked up as {ns_label} identifier) does not match any '
        f"known capability in this project. It was not found among this project's "
        f"capability modules, capability descriptors, or pending migrations."
    )


@dataclass(frozen=True)
class CapabilityIdentity:
    """One capability's canonical identity, plus every name it is known to
    be reachable by. ``surface`` is preserved here for callers that need
    the external-system identifier, but is deliberately NOT part of
    ``aliases`` and is NEVER used to decide whether two ``CapabilityIdentity``
    values refer to the same capability -- only ``canonical_id`` does that.
    """

    canonical_id: str
    descriptor_id: Optional[str]
    mechanism_id: Optional[str]
    module_stem: Optional[str]
    surface: Optional[str]
    aliases: FrozenSet[str]


def _capability_source_files(project_root: Path) -> Dict[str, Path]:
    """capability_id -> source file path, for every
    ``agents/capabilities/<capability_id>_capability.py`` on disk. Fail-safe:
    an absent capabilities directory yields the empty dict (mirrors
    capability_health.py's own ``_capability_source_files``)."""
    cap_dir = project_root / CAPABILITIES_DIR_REL
    found: Dict[str, Path] = {}
    if not cap_dir.is_dir():
        return found
    for path in sorted(cap_dir.glob(f"*{CAPABILITY_FILE_SUFFIX}")):
        if not path.is_file():
            continue
        cap_id = path.name[: -len(CAPABILITY_FILE_SUFFIX)]
        if cap_id:
            found[cap_id] = path
    return found


def _extract_surface(path: Path) -> Optional[str]:
    """Return the string value of a module-level ``SURFACE = "..."``
    assignment in ``path``, extracted by AST parsing -- NEVER by importing
    the module (see module docstring). Returns ``None`` for any of: the
    file cannot be read, the source cannot be parsed, or no module-level
    ``SURFACE`` string-literal assignment is present. Every one of those is
    a normal, non-error input here -- a capability predating this
    convention simply has no recorded surface, not a build failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "SURFACE" for t in node.targets):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def _load_descriptor_ids(project_root: Path) -> Set[str]:
    """The set of capability_ids declared in
    ``security/capability_descriptors.json``. Fail-safe: an absent file
    yields the empty set; an existing-but-unreadable-or-malformed file also
    yields the empty set here (unlike capability_health.py's own stricter
    treatment of this same file) -- the worst-case consequence of
    under-reading this file is a descriptor alias staying UNRESOLVED
    (fail-closed: never a wrong canonical), not a false positive, so this
    module does not need the sentinel-record escalation capability_health.py
    uses for its own (stronger) "never invite the operator into a red
    capability" guarantee."""
    path = project_root / DESCRIPTOR_SET_REL
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    try:
        data = json.loads(text)
    except ValueError:
        return set()
    if not isinstance(data, list):
        return set()
    ids: Set[str] = set()
    for entry in data:
        if isinstance(entry, dict):
            cap_id = entry.get("id")
            if isinstance(cap_id, str) and cap_id:
                ids.add(cap_id)
    return ids


def _load_mechanism_ids(project_root: Path) -> Set[str]:
    """The set of ``mechanism_id`` values declared in
    ``agents/handoffs/pending_migrations.json``. Fail-safe in the same
    sense as ``_load_descriptor_ids`` above: absent or unreadable/malformed
    both yield the empty set."""
    path = project_root / MIGRATION_QUEUE_REL
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    try:
        data = json.loads(text)
    except ValueError:
        return set()
    if not isinstance(data, list):
        return set()
    ids: Set[str] = set()
    for entry in data:
        if isinstance(entry, dict):
            mech_id = entry.get("mechanism_id")
            if isinstance(mech_id, str) and mech_id:
                ids.add(mech_id)
    return ids


def _build_name_alias_map(raw_ids: Set[str], canonical_ids: Set[str]) -> Dict[str, Set[str]]:
    """Build a ``raw_token -> {canonical_ids}`` map for a name-shaped
    namespace (``descriptor_id`` / ``mechanism_id``). Exact-match only, no
    fuzzy matching:

      * a raw id that EXACTLY EQUALS an existing canonical maps to that
        canonical directly -- unambiguous by construction (canonical ids are
        a set, so at most one canonical can equal any given string).
      * a raw id that matches NO canonical (the estate case) can only be
        attributed to a canonical without guessing if there is EXACTLY ONE
        canonical in the whole project -- with only one capability that
        could possibly be meant, attributing the unmatched name to it is
        not a similarity judgement, it is the only candidate that exists.
        With zero or two-or-more canonicals, an unmatched raw id is left
        out of the map entirely (unresolved, never guessed).
    """
    alias_map: Dict[str, Set[str]] = {}
    unmatched: Set[str] = set()
    for raw_id in raw_ids:
        if raw_id in canonical_ids:
            alias_map.setdefault(raw_id, set()).add(raw_id)
        else:
            unmatched.add(raw_id)
    if unmatched and len(canonical_ids) == 1:
        only_canonical = next(iter(canonical_ids))
        for raw_id in unmatched:
            alias_map.setdefault(raw_id, set()).add(only_canonical)
    return alias_map


class CapabilityIndex:
    """One project's capability identity index. Build with
    ``build_capability_index(project_root)``; look up with
    ``.resolve(raw, namespace)``."""

    def __init__(self, identities: Dict[str, CapabilityIdentity],
                 maps: Dict[str, Dict[str, Set[str]]]) -> None:
        self._identities = identities
        self._maps = maps

    def resolve(self, raw: str, namespace: Namespace) -> CapabilityIdentity:
        """Resolve ``raw`` (a value observed under ``namespace`` --
        ``"module_stem"``, ``"descriptor_id"``, ``"mechanism_id"``,
        ``"surface"``, or ``"unknown"`` if the caller does not know which
        namespace it came from) to its ``CapabilityIdentity``. Exact-alias
        lookup only -- see module docstring. Raises
        ``IdentityResolutionError`` (``kind="unresolved"`` or
        ``kind="ambiguous"``) rather than ever guessing."""
        if namespace == "unknown":
            matched: Set[str] = set()
            for ns in _NAMED_NAMESPACES:
                matched |= self._maps[ns].get(raw, set())
        else:
            matched = self._maps.get(namespace, {}).get(raw, set())

        if not matched:
            raise IdentityResolutionError(kind="unresolved", raw=raw, namespace=namespace)
        if len(matched) > 1:
            raise IdentityResolutionError(
                kind="ambiguous", raw=raw, namespace=namespace, candidates=sorted(matched))
        canonical = next(iter(matched))
        return self._identities[canonical]


def build_capability_index(project_root: str) -> CapabilityIndex:
    """Build the capability identity index for the project at
    ``project_root``.

    Enumerates canonical ids from ``agents/capabilities/<id>_capability.py``
    module stems (the identity the scaffold itself owns), AST-extracts each
    module's own ``SURFACE`` constant, reads descriptor ids from
    ``security/capability_descriptors.json`` and mechanism ids from
    ``agents/handoffs/pending_migrations.json``, and builds one
    alias-name -> canonical map per namespace (``module_stem``,
    ``descriptor_id``, ``mechanism_id``, ``surface``). Never raises: every
    input file is individually fail-safe (see the private loaders above);
    a project with no capabilities yet yields an index that resolves
    nothing (every ``resolve`` call fails closed as ``"unresolved"``).
    """
    root = Path(project_root)
    source_files = _capability_source_files(root)
    canonical_ids: Set[str] = set(source_files)

    descriptor_ids = _load_descriptor_ids(root)
    mechanism_ids = _load_mechanism_ids(root)

    module_stem_map: Dict[str, Set[str]] = {c: {c} for c in canonical_ids}
    descriptor_map = _build_name_alias_map(descriptor_ids, canonical_ids)
    mechanism_map = _build_name_alias_map(mechanism_ids, canonical_ids)

    # Surface: read directly from each module's own declaration -- never an
    # elimination/fallback attribution like the name namespaces above (see
    # module docstring). Two modules declaring the same surface value is
    # exactly the case that must fail closed as ambiguous on lookup.
    surface_by_canonical: Dict[str, Optional[str]] = {}
    surface_map: Dict[str, Set[str]] = {}
    for cap_id, path in source_files.items():
        surface = _extract_surface(path)
        surface_by_canonical[cap_id] = surface
        if surface is not None:
            surface_map.setdefault(surface, set()).add(cap_id)

    maps: Dict[str, Dict[str, Set[str]]] = {
        "module_stem": module_stem_map,
        "descriptor_id": descriptor_map,
        "mechanism_id": mechanism_map,
        "surface": surface_map,
    }

    identities: Dict[str, CapabilityIdentity] = {}
    for cap_id in canonical_ids:
        unambiguous_descriptor_aliases = sorted(
            raw for raw, canons in descriptor_map.items() if canons == {cap_id}
        )
        unambiguous_mechanism_aliases = sorted(
            raw for raw, canons in mechanism_map.items() if canons == {cap_id}
        )
        descriptor_id = cap_id if cap_id in unambiguous_descriptor_aliases else (
            unambiguous_descriptor_aliases[0] if unambiguous_descriptor_aliases else None
        )
        mechanism_id = cap_id if cap_id in unambiguous_mechanism_aliases else (
            unambiguous_mechanism_aliases[0] if unambiguous_mechanism_aliases else None
        )
        aliases = frozenset(
            {cap_id} | set(unambiguous_descriptor_aliases) | set(unambiguous_mechanism_aliases)
        )
        identities[cap_id] = CapabilityIdentity(
            canonical_id=cap_id,
            descriptor_id=descriptor_id,
            mechanism_id=mechanism_id,
            module_stem=cap_id,
            surface=surface_by_canonical.get(cap_id),
            aliases=aliases,
        )

    return CapabilityIndex(identities, maps)
