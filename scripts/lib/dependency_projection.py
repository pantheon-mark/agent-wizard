"""Deterministic external-dependency projection (pure-code role-filter + reshape).

The wizard captures the system's external dependencies ONCE as a canonical record the operator
confirms — two payload fields:

  EXTERNAL_DEPENDENCY_IDENTITY   (JSON array; the integration-boundary decision surface):
      [{id, name, type, roles:[boundary_input|boundary_output|health_monitored|needs_credential],
        credential_facet?:{env_var, cred_type, provider, provisional_expiry},
        action_class?, risk_class?, recovery_profile_ref?, declared_test_target?,
        blast_radius_cap?}]
      The five `action_class?`..`blast_radius_cap?` fields are the typed capability descriptor
      (B1-1; design §5.2 domain-neutral action taxonomy, §4.5/§4.7/F-28/F-29 risk-enforcement
      classes) — OPTIONAL and default-safe when absent. See ACTION_CLASSES / RISK_CLASSES /
      TEST_TARGETS below for their closed vocabularies, and `resolve_risk_class` for the
      fail-safe resolution an absent/unrecognized `risk_class` must get (F-28: NEVER
      read_only_local). They are stored/validated here only — B1-2 projects a descriptor
      registry from them, B1-3 mirrors risk_class into the OperationContract, B1-4 enforces caps.
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

A dependency may also play `boundary_output` (the system sends data/notifications OUT through it —
the symmetric partner to boundary_input; e.g. a push-notification channel the system assumes works,
or a sheet it writes back to). `boundary_output` drives NO emitted registry at v0; it keeps an
output-only dependency in the canonical record and lets it appear in INTEGRATIONS. A dependency
that plays only `boundary_output` is therefore valid even though it projects into none of the three
tables.

Stdlib-only, pip-install-free.
"""

import json
from typing import Any, Callable, Dict, List, Optional, Tuple


ROLE_BOUNDARY_INPUT = "boundary_input"
ROLE_BOUNDARY_OUTPUT = "boundary_output"
ROLE_HEALTH_MONITORED = "health_monitored"
ROLE_NEEDS_CREDENTIAL = "needs_credential"

# Each role is a canonical RELATIONSHIP the system has with a dependency. Most roles drive a
# deterministic projection (an emitted role-subset view); a role mapped to None drives no emitted
# artifact. `boundary_output` (the system sends data/notifications OUT through the dependency — the
# symmetric partner to boundary_input) is such a role at v0: it has no registry of its own, but it
# keeps an output-only dependency in the canonical record and surfaces it in INTEGRATIONS (the
# architecture doc's external-systems list). Validity is "declares >=1 relationship role", NOT
# "projects somewhere" — so a boundary_output-only dependency is valid though it projects nowhere.
ROLE_PROJECTION: Dict[str, Optional[str]] = {
    ROLE_BOUNDARY_INPUT: "INPUT_TYPE_INVENTORY",
    ROLE_HEALTH_MONITORED: "SOURCE_REGISTRY_ROWS",
    ROLE_NEEDS_CREDENTIAL: "CREDENTIAL_REGISTRY_ROWS",
    ROLE_BOUNDARY_OUTPUT: None,
}
VALID_ROLES = frozenset(ROLE_PROJECTION)

# --- typed capability descriptor vocabulary (B1-1) ---------------------------------------------
# Five OPTIONAL per-dependency fields (design §5.2 domain-neutral action taxonomy; §4.5/§4.7/
# F-28/F-29 risk-enforcement classes). Named module constants because B1-3's OperationContract
# reuses the SAME `risk_class` string values verbatim — this module owns the source-of-truth
# spelling for that cross-file seam.

# design §5.2: "classify / transform / route / notify / mutate / delete / send-execute /
# synchronize / retain-archive / recover / audit" plus `read_only` for a capability that only
# reads (no side effect at all — distinct from the read_only_local RISK class below).
ACTION_CLASSES = frozenset({
    "classify", "transform", "route", "notify", "mutate", "delete", "send_execute",
    "synchronize", "retain_archive", "recover", "audit", "read_only",
})

# design §4.5/§4.7/F-28/F-29: the enforcement-relevant risk class. READ_ONLY_LOCAL is the one
# class the downstream guard must NEVER reach by silent fallback — a read-only local ingest must
# not trip the same fail-closed path as an external delete/send, but nothing UNCLASSIFIED may
# ever land here either (see resolve_risk_class / FAIL_SAFE_RISK_CLASS below).
READ_ONLY_LOCAL = "read_only_local"
RISK_CLASSES = frozenset({
    READ_ONLY_LOCAL, "reversible_external", "irreversible_external", "sensitive_data",
    "standing_automation",
})

# The class an absent/unrecognized risk_class resolves to (F-28: the MOST-protected class, never
# the safe one). irreversible_external is the most-protected member of RISK_CLASSES: it is the
# class Leg 3 (design §4.7) gates hardest (recovery-proof + blast-radius cap + per-item approval).
FAIL_SAFE_RISK_CLASS = "irreversible_external"

# design §4.5 ("only against the declared test target (copy / bounded-batch), never live"),
# §4.7 ("dry-run by default" for the irreversible-action mode), §5.1 ("native undo" as a
# Recovery Profile rung) — normalized to snake_case value strings.
TEST_TARGETS = frozenset({"copy", "bounded_sample", "dry_run", "native_undo"})

# Setup-time-honest literals (the fabrication discipline): nothing about observed runtime health
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
    drawn from the closed role set. A zero-role dependency is INVALID — it declares no relationship
    to the system. (Validity is "declares a relationship", NOT "projects into a registry": a
    boundary_output-only dependency projects nowhere yet is valid.)"""
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
                f"{IDENTITY_FIELD}: dependency {rid!r} must declare at least one relationship role "
                f"(a zero-role dependency declares no relationship to the system)")
        for role in roles:
            if role not in VALID_ROLES:
                raise DependencyProjectionError(
                    f"{IDENTITY_FIELD}: dependency {rid!r} has unknown role {role!r}; "
                    f"valid roles: {sorted(VALID_ROLES)}")
        _validate_descriptor_fields(r, rid)
    return rows


def _validate_descriptor_fields(r: Dict[str, Any], rid: str) -> None:
    """Validate the five OPTIONAL typed-capability-descriptor fields (B1-1) on one dependency
    row. Every field is default-safe when absent — this only rejects a field that IS present
    and malformed. Fail loud (DependencyProjectionError), matching the role-validation style
    above, rather than resolving-to-safe: an unknown risk_class is caught here at capture time,
    and resolve_risk_class() below is the runtime defense-in-depth for values that reach it
    without having gone through this validator (F-28)."""
    if "action_class" in r:
        action_class = r.get("action_class")
        if action_class not in ACTION_CLASSES:
            raise DependencyProjectionError(
                f"{IDENTITY_FIELD}: dependency {rid!r} has unknown action_class {action_class!r}; "
                f"valid action classes: {sorted(ACTION_CLASSES)}")
    if "risk_class" in r:
        risk_class = r.get("risk_class")
        if risk_class not in RISK_CLASSES:
            raise DependencyProjectionError(
                f"{IDENTITY_FIELD}: dependency {rid!r} has unknown risk_class {risk_class!r}; "
                f"valid risk classes: {sorted(RISK_CLASSES)}")
    if "recovery_profile_ref" in r:
        ref = r.get("recovery_profile_ref")
        if not (isinstance(ref, str) and ref.strip()):
            raise DependencyProjectionError(
                f"{IDENTITY_FIELD}: dependency {rid!r} has an empty recovery_profile_ref "
                f"(omit the field entirely if there is no Recovery Profile yet)")
    if "declared_test_target" in r:
        target = r.get("declared_test_target")
        if target not in TEST_TARGETS:
            raise DependencyProjectionError(
                f"{IDENTITY_FIELD}: dependency {rid!r} has unknown declared_test_target "
                f"{target!r}; valid test targets: {sorted(TEST_TARGETS)}")
    if "blast_radius_cap" in r:
        cap = r.get("blast_radius_cap")
        if cap is not None:
            if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
                raise DependencyProjectionError(
                    f"{IDENTITY_FIELD}: dependency {rid!r} has invalid blast_radius_cap "
                    f"{cap!r}; must be a positive integer, or null/omitted for no cap set yet")


def resolve_risk_class(dep: Dict[str, Any]) -> str:
    """F-28, the load-bearing safety property: resolve a dependency's effective risk_class,
    FAIL-SAFE. Returns the literal `risk_class` value when it is present AND a member of
    RISK_CLASSES (including READ_ONLY_LOCAL itself — an explicit safe classification is
    honored). Returns FAIL_SAFE_RISK_CLASS (the MOST-protected class) for every other case:
    absent, None, or any value not in RISK_CLASSES. This function must NEVER return
    READ_ONLY_LOCAL for an absent or unrecognized value — that silent downgrade is exactly
    the failure F-28 forbids (an unclassified writer must never be treated as a harmless
    read-only-local ingest). Defense-in-depth alongside the parse_identity-time hard
    validation error above: this also protects a dependency dict that reached this function
    without having gone through parse_identity."""
    risk_class = dep.get("risk_class")
    if isinstance(risk_class, str) and risk_class in RISK_CLASSES:
        return risk_class
    return FAIL_SAFE_RISK_CLASS


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
