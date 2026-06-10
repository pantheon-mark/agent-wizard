"""Deterministic external-dependency projection (pure-code role-filter + reshape).

The wizard captures the system's external dependencies ONCE as a canonical record the operator
confirms — two payload fields:

  EXTERNAL_DEPENDENCY_IDENTITY   (JSON array; the integration-boundary decision surface):
      [{id, name, type, roles:[boundary_input|health_monitored|needs_credential],
        credential_facet?:{env_var, cred_type, provider, provisional_expiry}}]
  EXTERNAL_DEPENDENCY_ANNOTATION (JSON array; content-only):
      [{id, purpose, what_stops, boundary_input_facet?:{input_risk}, health_facet?:{}}]

Three tabular surfaces are DETERMINISTIC role-filtered VIEWS of that record (a `projection`-class
derivation — see the derived-record contract + derivation-prompts/projection.md):
  INPUT_TYPE_INVENTORY     <- the dependencies that play `boundary_input`   (validation gate)
  SOURCE_REGISTRY_ROWS     <- the dependencies that play `health_monitored` (QA source registry)
  CREDENTIAL_REGISTRY_ROWS <- the dependencies that play `needs_credential` (credentials registry)

This module is the pure code that produces those views: filter by role, copy canonical values into
the surface's columns, and hold setup-time honesty — observed-health cells are NEVER synthesized;
they ship as a runtime placeholder or `Pending`. Because the transform is a copy-and-filter with
fixed literals, the same canonical record always yields the same view — the property the
change-propagation engine relies on to silently auto-halt an unchanged role-subset.

The emitted FILES stay distinct (validation gate != source registry != credentials registry): not
every dependency plays every role (an outbound mail server is health_monitored + needs_credential
but not a validated input; a manual upload is boundary_input only). Each view is the subset that
plays its role.

Stdlib-only, pip-install-free.
"""

import json
from typing import Any, Callable, Dict, List, Tuple


ROLE_BOUNDARY_INPUT = "boundary_input"
ROLE_HEALTH_MONITORED = "health_monitored"
ROLE_NEEDS_CREDENTIAL = "needs_credential"
VALID_ROLES = frozenset({ROLE_BOUNDARY_INPUT, ROLE_HEALTH_MONITORED, ROLE_NEEDS_CREDENTIAL})

# Setup-time-honest literals (RW-40 fabrication discipline): nothing about observed runtime health
# is known when the wizard runs, so it is never derived.
RUNTIME_PLACEHOLDER = "(set at runtime)"
STATUS_PENDING = "Pending"
HEALTH_FLAG_PENDING = "Pending"
UNKNOWN = "Unknown"

# The canonical field keys (the projection's _derivation_inputs).
IDENTITY_FIELD = "EXTERNAL_DEPENDENCY_IDENTITY"
ANNOTATION_FIELD = "EXTERNAL_DEPENDENCY_ANNOTATION"


class DependencyProjectionError(Exception):
    """Raised on a malformed canonical record (fail-closed)."""


# --- parsing + validation ----------------------------------------------------

def parse_identity(identity_json: str) -> List[Dict[str, Any]]:
    """Parse + validate the IDENTITY record. Every dependency needs an id, a name, and >=1 role
    drawn from the closed role set (a zero-role record is INVALID — it would project nowhere)."""
    rows = _load_array(identity_json, IDENTITY_FIELD)
    seen_ids = set()
    for r in rows:
        rid = r.get("id")
        if not (isinstance(rid, str) and rid):
            raise DependencyProjectionError(f"{IDENTITY_FIELD}: a dependency is missing a non-empty 'id'")
        if rid in seen_ids:
            raise DependencyProjectionError(f"{IDENTITY_FIELD}: duplicate id {rid!r}")
        seen_ids.add(rid)
        if not (isinstance(r.get("name"), str) and r["name"]):
            raise DependencyProjectionError(f"{IDENTITY_FIELD}: dependency {rid!r} is missing a non-empty 'name'")
        roles = r.get("roles")
        if not (isinstance(roles, list) and len(roles) >= 1):
            raise DependencyProjectionError(
                f"{IDENTITY_FIELD}: dependency {rid!r} must declare at least one role "
                f"(a zero-role dependency is invalid)")
        for role in roles:
            if role not in VALID_ROLES:
                raise DependencyProjectionError(
                    f"{IDENTITY_FIELD}: dependency {rid!r} has unknown role {role!r}; "
                    f"valid roles: {sorted(VALID_ROLES)}")
    return rows


def parse_annotation(annotation_json: str) -> Dict[str, Dict[str, Any]]:
    """Parse the ANNOTATION record into an id -> annotation index (id is the join key)."""
    rows = _load_array(annotation_json, ANNOTATION_FIELD)
    index: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = r.get("id")
        if not (isinstance(rid, str) and rid):
            raise DependencyProjectionError(f"{ANNOTATION_FIELD}: an annotation is missing a non-empty 'id'")
        index[rid] = r
    return index


def _load_array(raw: str, where: str) -> List[Dict[str, Any]]:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as e:
        raise DependencyProjectionError(f"{where}: not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise DependencyProjectionError(f"{where}: must be a JSON array of dependency objects")
    for item in data:
        if not isinstance(item, dict):
            raise DependencyProjectionError(f"{where}: each entry must be an object")
    return data


# --- column specs (one per surface) ------------------------------------------
# Each cell extractor takes the merged dependency dict (identity row + 'ann' = its annotation,
# + 'cred' = its credential_facet) and returns the literal cell text. Runtime/observed-health
# cells return fixed placeholders — never synthesized.

def _ann(dep: Dict[str, Any]) -> Dict[str, Any]:
    return dep.get("ann") or {}

def _cred(dep: Dict[str, Any]) -> Dict[str, Any]:
    return dep.get("credential_facet") or {}

def _boundary_facet(dep: Dict[str, Any]) -> Dict[str, Any]:
    return _ann(dep).get("boundary_input_facet") or {}


def _g(d: Dict[str, Any], key: str, default: str = UNKNOWN) -> str:
    v = d.get(key)
    return v if (isinstance(v, str) and v.strip()) else default


# (role, [(header, extractor)]) per projection field.
_SURFACES: Dict[str, Tuple[str, List[Tuple[str, Callable[[Dict[str, Any]], str]]]]] = {
    "INPUT_TYPE_INVENTORY": (ROLE_BOUNDARY_INPUT, [
        ("Input type", lambda d: _g(d, "name")),
        ("Source", lambda d: _g(d, "type")),
        ("What it is", lambda d: _g(_ann(d), "purpose")),
        ("What stops without it", lambda d: _g(_ann(d), "what_stops")),
        ("Structural rules", lambda d: _g(_boundary_facet(d), "input_risk", RUNTIME_PLACEHOLDER)),
        ("Status", lambda d: STATUS_PENDING),
    ]),
    "SOURCE_REGISTRY_ROWS": (ROLE_HEALTH_MONITORED, [
        ("Source name", lambda d: _g(d, "name")),
        ("Type", lambda d: _g(d, "type")),
        ("Purpose", lambda d: _g(_ann(d), "purpose")),
        ("What stops without it", lambda d: _g(_ann(d), "what_stops")),
        ("Expected behavior", lambda d: RUNTIME_PLACEHOLDER),
        ("Status", lambda d: STATUS_PENDING),
        ("Last verified", lambda d: RUNTIME_PLACEHOLDER),
        ("Health flag", lambda d: HEALTH_FLAG_PENDING),
    ]),
    "CREDENTIAL_REGISTRY_ROWS": (ROLE_NEEDS_CREDENTIAL, [
        ("Name", lambda d: _g(d, "name")),
        ("ENV variable", lambda d: _g(_cred(d), "env_var")),
        ("Type", lambda d: _g(_cred(d), "cred_type")),
        ("Provider", lambda d: _g(_cred(d), "provider")),
        ("Expiry type", lambda d: _g(_cred(d), "provisional_expiry")),
        ("Expiry date", lambda d: RUNTIME_PLACEHOLDER),
        ("Rotation method", lambda d: RUNTIME_PLACEHOLDER),
        ("Last verified", lambda d: RUNTIME_PLACEHOLDER),
        ("Status", lambda d: STATUS_PENDING),
    ]),
}

PROJECTION_FIELDS = frozenset(_SURFACES)


def derivation_inputs_for(field: str) -> List[str]:
    """The canonical field keys a given projection reshapes (its `_derivation_inputs`).

    The credentials registry reads only the IDENTITY credential facet (name + credential metadata);
    the other two also read ANNOTATION (purpose / what-stops / role facet)."""
    if field == "CREDENTIAL_REGISTRY_ROWS":
        return [IDENTITY_FIELD]
    if field in _SURFACES:
        return [IDENTITY_FIELD, ANNOTATION_FIELD]
    raise DependencyProjectionError(f"unknown projection field {field!r}; known: {sorted(_SURFACES)}")


def _md_cell(text: str) -> str:
    # Markdown table cells cannot contain a raw pipe; escape defensively (canonical values are prose).
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def project(field: str, identity_json: str, annotation_json: str = "[]") -> str:
    """Produce the markdown table BODY (rows only; the template owns the header) for one projection
    surface: filter the canonical dependencies to those that play this surface's role, reshape each
    into this surface's columns. Returns "" when no dependency plays the role (valid empty body)."""
    if field not in _SURFACES:
        raise DependencyProjectionError(f"unknown projection field {field!r}; known: {sorted(_SURFACES)}")
    role, columns = _SURFACES[field]
    identity = parse_identity(identity_json)
    annotation = parse_annotation(annotation_json)

    lines: List[str] = []
    for dep in identity:
        if role not in dep.get("roles", []):
            continue
        merged = dict(dep)
        merged["ann"] = annotation.get(dep["id"], {})
        cells = [_md_cell(extract(merged)) for _, extract in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def headers_for(field: str) -> List[str]:
    """The column headers for a surface (for tests / documentation; the live templates own them)."""
    return [h for h, _ in _SURFACES[field][1]]


def main() -> int:
    import sys
    if len(sys.argv) < 3:
        print("usage: dependency_projection.py <FIELD> <identity.json> [annotation.json]", file=sys.stderr)
        print(f"  FIELD one of: {sorted(_SURFACES)}", file=sys.stderr)
        return 2
    field = sys.argv[1]
    identity = open(sys.argv[2], encoding="utf-8").read()
    annotation = open(sys.argv[3], encoding="utf-8").read() if len(sys.argv) > 3 else "[]"
    try:
        print(project(field, identity, annotation))
    except DependencyProjectionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
