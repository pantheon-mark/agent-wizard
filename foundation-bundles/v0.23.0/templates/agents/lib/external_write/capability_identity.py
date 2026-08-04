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
``inbox_management``) is attributed to a canonical via exactly ONE
remaining avenue, exact string equality, and NEVER by any other means:

  SURFACE-CORROBORATED: the raw value exactly equals the ``SURFACE`` some
  canonical module itself declares (the estate case: descriptor id
  ``inbox-labels`` equals ``inbox_management``'s own declared ``SURFACE``).
  This directly identifies the ONE SPECIFIC canonical the raw value
  corroborates -- not "whichever canonical happens to be the only one in
  the project" -- so it applies regardless of how many OTHER unmatched raw
  ids or canonicals exist in the same project. If two different canonicals
  both declare that same surface, the raw value maps to both and
  ``resolve`` correctly reports it ambiguous (same rule as a direct
  ``surface`` lookup -- see above).

(Coordinator review, round 2, CRITICAL fix) There is DELIBERATELY no
cardinality-based fallback ("this project only has one capability, so an
otherwise-unmatched id must mean that one"). An earlier revision had exactly
such a fallback, scoped to fire only when a raw id was the SOLE unmatched id
in its namespace and the project had exactly one canonical -- narrower than
the very first version, but still a GUESS with zero corroborating evidence,
and it produced two real downstream bugs: ``capability_health.py`` folded a
genuinely-unrelated, stale descriptor entry into the sole capability's row
(making a real broken/orphaned entry silently vanish from the health report
instead of reporting red), and ``operator_acceptance.py`` silently deleted an
unrelated ``pending_migrations.json`` entry the moment the sole capability
was accepted. Cardinality is not evidence, full stop -- an id with no
corroboration signal is unresolved regardless of how many capabilities exist
in the project, one or one hundred.

The moment SURFACE-CORROBORATION does not apply, an unmatched
descriptor/mechanism id has no unambiguous default target and is left
unresolved (never silently guessed) until something disambiguates it
(typically: the descriptor set gets corrected to use the real capability_id,
per ``wizard/skills/add-capability.md``'s own convention that
``mechanism_id == capability_id``).

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
from typing import Dict, FrozenSet, Iterable, List, Literal, Optional, Set, Tuple

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


class IdentityCoherenceError(Exception):
    """Raised by ``assert_identity_coherent`` (Task A2 / A3.1) when a capability's
    descriptor_id, capability_id, mechanism_id, and module_stem are not ALL the same string.
    Plain-language message, no traceback text."""


def normalize_capability_id(raw: str) -> str:
    """Case/separator-folded normalization of a capability-shaped id string (Task A4 / F-72):
    stripped of surrounding whitespace, lower-cased, then every hyphen folded to underscore.

    This folds toward the SEPARATOR the scaffold's own canonical ids already use -- a module stem
    is a Python identifier, always underscore-separated, never hyphenated -- so a genuinely
    canonical id normalizes to itself, unchanged. It is deliberately NOT the identity resolver
    above (``CapabilityIndex.resolve``): it never consults ``SURFACE``, module stems, or any
    project state; it is a pure string fold, used ONLY to catch a case/separator TWIN of an id
    string before it is ever written (``assert_no_normalized_collision`` below) or to classify one
    already on disk (``capability_health.py``'s identity-twin classification)."""
    return raw.strip().lower().replace("-", "_")


class CanonicalIdentityError(Exception):
    """Raised by ``assert_no_normalized_collision`` (Task A4 / F-72) when a candidate descriptor
    id normalizes (case/separator-folded -- see ``normalize_capability_id``) to the SAME identity
    as an id that already exists, whether or not the two strings are byte-identical.

    This is the estate finding this check exists to make impossible going forward: a stale
    descriptor ``"inbox-management"`` (hyphen, never built, never accepted) coexisting with the
    canonical, live, accepted descriptor ``"inbox_management"`` (underscore) -- two descriptor rows
    for what is really ONE capability identity, differing only by separator, which broke
    ``capability_health``'s health classification for the never-built twin (reported RED, a
    phantom-broken capability, rather than the distinct non-issue it actually was).

    Plain-language message, no traceback text -- read by a non-technical operator's project the
    same way every other identity error in this module is."""


def assert_no_normalized_collision(new_id: str, existing_ids: Iterable[str]) -> None:
    """Raise ``CanonicalIdentityError`` iff ``new_id`` normalizes (``normalize_capability_id``) to
    the same identity as any id already present in ``existing_ids`` -- an exact byte-identical
    match trivially normalizes equal to itself too, so this SUBSUMES a plain duplicate-id check; a
    caller does not need a separate exact-match check alongside this one.

    This is the WRITE-TIME collision guard (Task A4 / F-72): call it before a new descriptor id is
    ever landed in ``security/capability_descriptors.json``, so a case/separator twin of an
    existing descriptor id can never form going forward. It says nothing, by itself, about an
    EXISTING twin already on disk (one that formed before this guard existed) -- classifying that
    (tombstone-eligible ``pending`` vs. a distinct ``identity_conflict`` health state) is
    ``capability_health.py``'s job, not this write-time refusal's.

    Non-string / empty entries in ``existing_ids`` are skipped, never a collision candidate. Never
    raises for any input shape other than an actual normalized collision."""
    normalized_new = normalize_capability_id(new_id)
    for existing in existing_ids:
        if not isinstance(existing, str) or not existing:
            continue
        if normalize_capability_id(existing) == normalized_new:
            if existing == new_id:
                raise CanonicalIdentityError(
                    f'A descriptor with id "{new_id}" already exists -- refusing to register a '
                    "duplicate.")
            raise CanonicalIdentityError(
                f'The id "{new_id}" is not a new identity -- it differs from the existing '
                f'descriptor id "{existing}" only by letter case or separator style (hyphen vs. '
                "underscore), which this system treats as the exact SAME capability identity. "
                "Landing both would silently split one capability into two descriptor rows (the "
                f'exact problem this check exists to prevent). Use "{existing}" directly instead, '
                "or retire it first (if it is a stale, never-built entry) before registering a "
                "new one under this name.")


def assert_identity_coherent(descriptor_id: str, capability_id: str, mechanism_id: str,
                              module_stem: str) -> None:
    """Raise ``IdentityCoherenceError`` unless ``descriptor_id``, ``capability_id``,
    ``mechanism_id``, and ``module_stem`` are ALL the exact same string -- the four-way
    build-time identity invariant (Task A2 / A3.1) that makes a capability's identity split (the
    estate bug: descriptor id ``"inbox-labels"`` vs. capability_id/module_stem
    ``"inbox_management"``) impossible to re-create by construction.

    OPERATE-TIME DUPLICATE of ``wizard/scripts/lib/capability_code_scaffold.py``'s
    ``assert_identity_coherent`` -- capability_registration.py (this package) MUST NOT import the
    build-side tree, and capability_code_scaffold.py (build-side) MUST NOT import this
    ``external_write`` package (see each module's own boundary-discipline docstring), so this is
    the SAME duplicate-plus-cross-tree-pin convention this codebase already uses for
    ``REGISTERED_ENTRY_KEYS`` / ``BASE_DESCRIPTOR_ID_PREFIX`` / etc. -- pinned byte-equal (message
    included) by ``test_capability_code_scaffold.TestAssertIdentityCoherentCrossTreePin``. Keep
    the two copies' bodies identical (bar the exception class name) if either changes.

    ``surface`` (the external-system identifier a capability talks to, e.g. ``"acme_crm"`` for
    capability_id ``"acme_crm_sync"``) is DELIBERATELY NOT a parameter here and is NEVER checked
    against the other three -- two different capabilities may legitimately share a surface, and
    one capability's own surface legitimately differs from its capability_id (see this module's
    own "Surface is excluded from identity" section above). Checking it here would re-introduce
    exactly the false-positive class this correction exists to rule out (``surface !=
    capability_id`` MUST be allowed).

    ``module_stem`` here means the CANONICAL form -- the module stem with any trailing
    ``_capability`` suffix already stripped; every caller is responsible for canonicalizing
    before calling.

    Fail-closed: raises on ANY inequality among the four, with a plain-language message (no
    traceback) naming every value and the likely cause, so a non-technical operator's project
    never lands a capability whose identity is split across these four surfaces.
    """
    values = {
        "descriptor_id": descriptor_id,
        "capability_id": capability_id,
        "mechanism_id": mechanism_id,
        "module_stem": module_stem,
    }
    if len(set(values.values())) > 1:
        detail = "; ".join(f"{k}={v!r}" for k, v in values.items())
        raise IdentityCoherenceError(
            "This capability's identity is not consistent across the system -- its descriptor "
            "id, capability_id, mechanism_id, and module name must all be the exact SAME "
            f"identifier, but they are not ({detail}). This is very likely because one of these "
            "was set to the capability's external-system SURFACE (e.g. the vendor name) instead "
            "of its capability_id -- surface is a separate field and is allowed to differ; these "
            "four identity fields are not allowed to differ. Fix: make all four the same value "
            "as the capability's capability_id.")


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

    ``state_read_error`` (review finding, IMPORTANT): True iff the index
    this error came from was built while a present-but-unreadable/malformed
    descriptor set or migration queue file was encountered (see
    ``CapabilityIndex.state_read_error`` / ``_load_descriptor_ids`` /
    ``_load_mechanism_ids``). When True, ``operator_message`` says the
    lookup could NOT be fully verified because a state file is broken --
    never "does not exist" -- so the operator is pointed at repairing the
    file, not at recreating a capability that may well still exist.
    """

    def __init__(self, kind: ErrorKind, raw: str, namespace: Namespace,
                 candidates: Optional[List[str]] = None,
                 state_read_error: bool = False) -> None:
        self.kind = kind
        self.raw = raw
        self.namespace = namespace
        self.candidates = list(candidates) if candidates else []
        self.state_read_error = state_read_error
        self.operator_message = _build_operator_message(
            kind, raw, namespace, self.candidates, state_read_error)
        super().__init__(self.operator_message)


def _build_operator_message(kind: ErrorKind, raw: str, namespace: Namespace, candidates: List[str],
                             state_read_error: bool = False) -> str:
    ns_label = "an unspecified" if namespace == "unknown" else f'a "{namespace}"'
    if kind == "ambiguous":
        joined = ", ".join(sorted(candidates))
        message = (
            f'The value "{raw}" (looked up as {ns_label} identifier) matches more than '
            f"one capability ({joined}) and cannot be resolved automatically. This usually "
            f'means two different capabilities share the same external identifier. Use '
            f"each capability's own capability_id directly instead of \"{raw}\"."
        )
        if state_read_error:
            message += (
                " Note: a project state file (the capability descriptor list or the "
                "pending-migrations queue) also could not be fully read, so this list of "
                "matches may be incomplete -- repair that file before relying on this result."
            )
        return message
    if state_read_error:
        return (
            f'Could not verify whether "{raw}" (looked up as {ns_label} identifier) matches a '
            f"known capability, because a project state file -- the capability descriptor list "
            f"or the pending-migrations queue -- exists but could not be read or is corrupted. "
            f'This is NOT a confirmation that "{raw}" does not exist. Repair or restore that '
            f"file, then check again."
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

    ``descriptor_id`` / ``mechanism_id`` caveat: when MORE THAN ONE alias
    unambiguously maps to this same canonical (e.g. two differently-named
    descriptor entries both corroborated as this capability), each of these
    two fields holds only ONE representative alias (the alphabetically first
    -- an arbitrary but deterministic pick), not the full set. ``aliases``
    is the authoritative membership set for "every name known to resolve to
    this canonical" -- always consult it, never assume ``descriptor_id`` /
    ``mechanism_id`` are exhaustive.
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
    convention simply has no recorded surface, not a build failure.

    Matches both plain ``SURFACE = "..."`` (``ast.Assign`` -- the form
    ``capability_code_scaffold.py`` actually emits today) and annotated
    ``SURFACE: str = "..."`` (``ast.AnnAssign``) -- the annotated form isn't
    emitted by anything in this codebase yet, but recognizing it too costs
    nothing and avoids a silent ``surface=None`` if a capability module is
    ever hand-written or generated with a type annotation on the constant.

    (xvendor R-6 fix) If ``SURFACE`` is assigned MORE THAN ONCE at module
    level, the LAST valid string-literal assignment wins -- mirroring
    Python's own runtime last-assignment-wins semantics for a re-bound
    module-level name. Returning the first assignment (the prior behavior)
    would decouple this AST-only static read from what the module actually
    holds at runtime for a module that reassigns ``SURFACE``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return None
    surface: Optional[str] = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if not any(isinstance(t, ast.Name) and t.id == "SURFACE" for t in node.targets):
                continue
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if not (isinstance(target, ast.Name) and target.id == "SURFACE"):
                continue
            value = node.value
        else:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            surface = value.value
    return surface


def _load_descriptor_ids(project_root: Path) -> Tuple[Set[str], bool]:
    """The set of capability_ids declared in
    ``security/capability_descriptors.json``, plus whether reading it hit a
    state-read error. Returns ``(ids, read_error)``.

    An ABSENT file is a normal, non-error input: ``(set(), False)`` --
    nothing has been declared yet, not a problem.

    (review finding, IMPORTANT) An EXISTING-but-unreadable-or-malformed file
    is NOT the same as absent, and must not be silently collapsed into the
    same "no descriptors" outcome with no signal at all: without a
    distinguishable ``read_error=True``, a ``resolve()`` failure caused by a
    broken state file would report "does not exist" to the operator --
    misdirecting them toward recreating a capability that may still be
    perfectly fine, instead of toward repairing the actual broken file
    (mirrors capability_health.py's own distinction between a genuinely
    absent marker and an inaccessible one). Such a file returns
    ``(set(), True)``; ``build_capability_index`` folds this into
    ``CapabilityIndex.state_read_error``, which ``resolve()`` uses to pick
    the correct ``operator_message`` wording."""
    path = project_root / DESCRIPTOR_SET_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return set(), False
    except OSError:
        return set(), True
    try:
        data = json.loads(text)
    except ValueError:
        return set(), True
    if not isinstance(data, list):
        return set(), True
    ids: Set[str] = set()
    for entry in data:
        if isinstance(entry, dict):
            cap_id = entry.get("id")
            if isinstance(cap_id, str) and cap_id:
                ids.add(cap_id)
    return ids, False


def _load_mechanism_ids(project_root: Path) -> Tuple[Set[str], bool]:
    """The set of ``mechanism_id`` values declared in
    ``agents/handoffs/pending_migrations.json``, plus whether reading it hit
    a state-read error. Returns ``(ids, read_error)`` -- same absent-vs.
    -unreadable/malformed distinction as ``_load_descriptor_ids`` above."""
    path = project_root / MIGRATION_QUEUE_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return set(), False
    except OSError:
        return set(), True
    try:
        data = json.loads(text)
    except ValueError:
        return set(), True
    if not isinstance(data, list):
        return set(), True
    ids: Set[str] = set()
    for entry in data:
        if isinstance(entry, dict):
            mech_id = entry.get("mechanism_id")
            if isinstance(mech_id, str) and mech_id:
                ids.add(mech_id)
    return ids, False


def _build_name_alias_map(raw_ids: Set[str], canonical_ids: Set[str],
                           surface_by_canonical: Dict[str, Optional[str]]) -> Dict[str, Set[str]]:
    """Build a ``raw_token -> {canonical_ids}`` map for a name-shaped
    namespace (``descriptor_id`` / ``mechanism_id``). Exact-match only, no
    fuzzy matching, no cardinality guessing -- see the module docstring's
    "How aliases are discovered" section for the full rationale. Summary:

      * a raw id that EXACTLY EQUALS an existing canonical maps to that
        canonical directly -- unambiguous by construction.
      * an unmatched raw id maps via SURFACE-CORROBORATED: it exactly
        equals some canonical's own declared ``SURFACE`` -- identifies that
        SPECIFIC canonical regardless of what else is unmatched or how many
        other canonicals exist.
      * anything else stays out of the map entirely -- unresolved, never
        guessed.

    (Coordinator review, round 2, CRITICAL) There is DELIBERATELY no third,
    cardinality-based fallback here anymore. An earlier revision resolved a
    raw id with NEITHER an exact match NOR a surface match to "the sole
    capability in the project" whenever there was exactly one unmatched raw
    id and exactly one canonical -- "there's only one capability, so this
    stray must mean that one". That is a fuzzy/heuristic GUESS with zero
    corroborating evidence, exactly the class of resolution this module's
    fail-closed design forbids (see "Fail-closed, no fuzzy matching" above).
    It also produced two real, silent-masking bugs downstream: (1)
    ``capability_health.py`` folded a genuinely-unrelated, stale descriptor
    entry into the sole capability's row, making the stale/broken entry
    VANISH from the health report instead of being reported red; (2)
    ``operator_acceptance.py`` silently deleted an unrelated
    ``pending_migrations.json`` entry the moment the sole capability was
    accepted, purely because it was the only entry and the only capability
    around. Removing the fallback closes both: an id with no corroboration
    signal is simply ``unresolved``, regardless of how many (or how few)
    capabilities exist in the project -- cardinality is not evidence.
    """
    alias_map: Dict[str, Set[str]] = {}
    unmatched: Set[str] = set()
    for raw_id in raw_ids:
        if raw_id in canonical_ids:
            alias_map.setdefault(raw_id, set()).add(raw_id)
        else:
            unmatched.add(raw_id)

    for raw_id in unmatched:
        surface_matches = {c for c, s in surface_by_canonical.items() if s == raw_id}
        if surface_matches:
            alias_map.setdefault(raw_id, set()).update(surface_matches)
    return alias_map


class CapabilityIndex:
    """One project's capability identity index. Build with
    ``build_capability_index(project_root)``; look up with
    ``.resolve(raw, namespace)``.

    ``state_read_error`` (review finding, IMPORTANT): True iff building this
    index encountered a present-but-unreadable-or-malformed descriptor set
    or migration queue file (see ``_load_descriptor_ids`` /
    ``_load_mechanism_ids``). This does NOT mean the index is empty or
    unusable -- it means the picture may be INCOMPLETE, so a subsequent
    ``resolve()`` failure is reported with a "could not verify" message
    rather than a "does not exist" one (see ``_build_operator_message``)."""

    def __init__(self, identities: Dict[str, CapabilityIdentity],
                 maps: Dict[str, Dict[str, Set[str]]],
                 state_read_error: bool = False) -> None:
        self._identities = identities
        self._maps = maps
        self.state_read_error = state_read_error

    @property
    def canonical_ids(self) -> FrozenSet[str]:
        """The full set of canonical capability ids known to this index (one per
        ``agents/capabilities/<id>_capability.py`` module on disk). Public so a caller can
        reason about project cardinality (e.g. "is this the project's only capability") without
        reaching into the private ``_identities`` map."""
        return frozenset(self._identities)

    def resolve(self, raw: str, namespace: Namespace) -> CapabilityIdentity:
        """Resolve ``raw`` (a value observed under ``namespace`` --
        ``"module_stem"``, ``"descriptor_id"``, ``"mechanism_id"``,
        ``"surface"``, or ``"unknown"`` if the caller does not know which
        namespace it came from) to its ``CapabilityIdentity``. Exact-alias
        lookup only -- see module docstring. Raises
        ``IdentityResolutionError`` (``kind="unresolved"`` or
        ``kind="ambiguous"``) rather than ever guessing.

        ``namespace="unknown"`` precedence (coordinator review fix): surface-corroboration to
        some OTHER capability must NEVER outrank ``raw`` being an exact canonical id / own module
        stem in its own right. Before this fix, ``"unknown"`` unioned all four namespace maps
        flatly -- so a BRAND NEW capability whose ``capability_id`` happened to equal an UNRELATED
        existing capability's own declared ``SURFACE`` was reported ambiguous (matching both
        itself AND the unrelated capability), a false refusal for a perfectly legitimate id. Tiers
        are tried in order, each ONLY if the previous is empty:

          1. exact canonical id / own module stem (``raw`` IS a real capability, full stop);
          2. exact ``descriptor_id`` / ``mechanism_id`` alias (each entry here already resolves to
             exactly one canonical -- possibly itself already surface-corroborated or
             sole-candidate-resolved, see ``_build_name_alias_map`` -- but always ONE canonical
             per raw token, so tier 2 cannot itself introduce an ambiguity across tiers);
          3. surface corroboration to some OTHER capability's own declared surface -- the
             lowest-precedence, most indirect signal, only consulted once 1 and 2 found nothing.
        """
        if namespace == "unknown":
            matched: Set[str] = self._maps["module_stem"].get(raw, set())
            if not matched:
                matched = (self._maps["descriptor_id"].get(raw, set())
                           | self._maps["mechanism_id"].get(raw, set()))
            if not matched:
                matched = self._maps["surface"].get(raw, set())
        else:
            matched = self._maps.get(namespace, {}).get(raw, set())

        if not matched:
            raise IdentityResolutionError(
                kind="unresolved", raw=raw, namespace=namespace,
                state_read_error=self.state_read_error)
        if len(matched) > 1:
            raise IdentityResolutionError(
                kind="ambiguous", raw=raw, namespace=namespace, candidates=sorted(matched),
                state_read_error=self.state_read_error)
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

    ``CapabilityIndex.state_read_error`` is True iff the descriptor set or
    the migration queue file EXISTS but could not be read/parsed (never for
    an absent file -- see ``_load_descriptor_ids`` / ``_load_mechanism_ids``
    and the review-finding note on ``CapabilityIndex``).
    """
    root = Path(project_root)
    source_files = _capability_source_files(root)
    canonical_ids: Set[str] = set(source_files)

    descriptor_ids, descriptor_read_error = _load_descriptor_ids(root)
    mechanism_ids, mechanism_read_error = _load_mechanism_ids(root)
    state_read_error = descriptor_read_error or mechanism_read_error

    # Surface: read directly from each module's own declaration -- never an
    # elimination/fallback attribution like the name namespaces below (see
    # module docstring). Two modules declaring the same surface value is
    # exactly the case that must fail closed as ambiguous on lookup. Built
    # BEFORE the name-alias maps because they consult it (avenue (A),
    # surface-corroboration -- see ``_build_name_alias_map``).
    surface_by_canonical: Dict[str, Optional[str]] = {}
    surface_map: Dict[str, Set[str]] = {}
    for cap_id, path in source_files.items():
        surface = _extract_surface(path)
        surface_by_canonical[cap_id] = surface
        if surface is not None:
            surface_map.setdefault(surface, set()).add(cap_id)

    module_stem_map: Dict[str, Set[str]] = {c: {c} for c in canonical_ids}
    descriptor_map = _build_name_alias_map(descriptor_ids, canonical_ids, surface_by_canonical)
    mechanism_map = _build_name_alias_map(mechanism_ids, canonical_ids, surface_by_canonical)

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

    return CapabilityIndex(identities, maps, state_read_error=state_read_error)
