"""The operate-time capability-REGISTRATION helper: the deterministic writer the
add-capability cascade invokes to land a newly-DECLARED (never accepted) capability descriptor in
``security/capability_descriptors.json`` AND, in the SAME fail-safe operation, regenerate the
QA-visible ``quality/co-protected-workflows.md`` table.

Why this is its own trust-critical unit
---------------------------------------
The whole reason the operator-originated-enhancement flow exists is that an off-plan capability the
plan never anticipated was invisible to the QA guard: nothing registered its high-risk action class
in ``co-protected-workflows.md``, so the guard had no pattern to match and was silently blind to it.
This helper closes that seam BY CONSTRUCTION: a GATED capability cannot be landed in the descriptor
set unless its high-risk class is registered in the co-protected table in the same call. If the
table cannot be regenerated, the descriptor is NOT written (no half-registration) — the guard is
never left blind to a live-eligible capability.

Fail-safe / fail-closed properties (every branch defaults to refuse + write nothing):
  * the descriptor set must load as a JSON list; else refuse;
  * a declared descriptor MUST carry a non-empty ``phase_id`` (the acceptance ceremony refuses
    without it — a capability with no phase binding can never be accepted); else refuse;
  * ``accepted`` must be false — this helper is NEVER a path to ``accepted: true`` (the acceptance
    ceremony is the SOLE writer of that field); an accepted:true input is refused;
  * the id must be free-form and unique, never the reserved ``__builtin__:`` base sentinel;
  * an absent / out-of-vocabulary ``risk_class`` is resolved FAIL-SAFE to the most-protected class
    (never silently treated as safe), so an unclassified writer lands GATED and
    co-protected-registered, not invisible;
  * for a GATED capability the co-protected table MUST be present and locatable; if it is not, the
    descriptor is not landed;
  * for a GATED capability the co-protected table is written FIRST, the descriptor set SECOND —
    reversed from the naive order — so a hard crash (SIGKILL / power loss) between the two
    ``os.replace`` calls is fail-SAFE, not fail-open: it leaves at worst a harmless PHANTOM guard
    row with no matching descriptor (over-protective, never blind), and a retry regenerates the
    co-protected table from the FULL descriptor set (reconciling the phantom row away) and lands
    the descriptor idempotently — self-healing. The opposite order (descriptor first) would leave
    a live gated descriptor with NO guard row on crash — the exact blindness this helper exists to
    prevent — and could never self-heal, because a retry would hit the duplicate-id refusal
    forever with the guard still blind;
  * if the descriptor-set write fails AFTER the co-protected write, the co-protected table is
    rolled back to its exact prior text — the pair is all-or-nothing.

Boundary discipline: this module lives in the external_write package (emitted into the
operator system) and MUST NOT import the build-side tree. The few build-side constants it needs
(the descriptor-entry key order, the reserved base prefix, the protection-note prose, the
protection-requiring risk-class set) are DUPLICATED here and pinned equal to their build-side
originals by cross-tree tests — exactly as ``write_gate`` pins its risk-class vocabulary. The
co-protected registration rule is the SAME set the runtime write gate gates on
(``write_gate.GATED_RISK_CLASSES``), imported directly, so the guard-visible half and the
enforced half can never diverge on what counts as high-risk.

Stdlib only — no third-party dependencies.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# sys.path bootstrap (mirrors acceptance_ceremony.py): make the package parent importable when run
# as a direct script from the project root, so the sibling ``external_write.*`` imports resolve.
if __package__ in (None, ""):  # pragma: no cover - only true when run as a script
    import sys as _bootstrap_sys
    _pkg_parent = str(Path(__file__).resolve().parent.parent)
    if _pkg_parent not in _bootstrap_sys.path:
        _bootstrap_sys.path.insert(0, _pkg_parent)

from external_write.contracts import RISK_CLASSES
from external_write.write_gate import (
    GATED_RISK_CLASSES,
    FAIL_SAFE_RISK_CLASS,
    DESCRIPTOR_SET_PATH,
)


# The default operate-time location of the QA-visible co-protected table (project-root-relative).
DEFAULT_CO_PROTECTED_PATH = "quality/co-protected-workflows.md"

# The descriptor-entry key order — DUPLICATED from capability_descriptor_registry.ENTRY_KEYS
# (build-side; not importable here) and pinned equal by
# test_external_write_capability_registration.DriftPinTest. A landed entry carries EXACTLY these
# keys, in this order, so the on-disk descriptor set stays a single uniform shape whether an entry
# came from the build-time producer or from this operate-time helper.
REGISTERED_ENTRY_KEYS = (
    "id", "name", "action_class", "risk_class", "recovery_profile_ref",
    "declared_test_target", "blast_radius_cap", "accepted", "phase_id",
)

# Reserved base-descriptor id/name prefix — DUPLICATED from
# capability_descriptor_registry.BASE_DESCRIPTOR_ID_PREFIX (not importable here) and pinned equal by test. A
# base entry is a placeholder describing that a built-in op EXISTS and is unaccepted; it is never a
# real declarable capability, and it never appears as a QA-matchable co-protected row.
BASE_DESCRIPTOR_ID_PREFIX = "__builtin__:"

# The co-protected registration rule: the protection-requiring risk classes. This is the SAME set
# the runtime write gate gates on (imported directly, not re-declared) — and it equals the
# build-side co_protected_workflows.PROTECTED_RISK_CLASSES (pinned by test). A capability whose
# resolved risk class is in this set MUST be registered in the co-protected table (guard
# visibility); read_only_local / reversible_external are deliberately excluded (no over-firing).
CO_PROTECTED_RISK_CLASSES = GATED_RISK_CLASSES

# The literal header row of the co-protected "Registered capability workflows" table — the anchor
# used to locate the region to regenerate. Must match the emitted template's header exactly.
CO_PROTECTED_TABLE_HEADER = "| Capability | Action class | Risk class | What's protected |"

# The per-risk-class "What's protected" prose — DUPLICATED verbatim from
# co_protected_workflows._PROTECTION_NOTE / STANDING_AUTOMATION_FLOOR_NOTE (not importable here) and pinned
# equal by test, so an operate-time-registered row reads identically to a build-time-projected one.
STANDING_AUTOMATION_FLOOR_NOTE = (
    "Runs on a recurring or unattended basis (a server-side filter, rule, or scheduled job), not "
    "a single confirmed action. It may enter the ceremony-maturity ladder — starting supervised "
    "and earning autonomy over a run of clean outcomes — but its recovery floor is "
    "NON-GRADUATING: maturity graduates supervision and narration, never the backup/recover "
    "safety net."
)
_PROTECTION_NOTE = {
    "irreversible_external": (
        "Has an external effect that cannot be undone without a backup or restore operation."
    ),
    "sensitive_data": (
        "Touches data that requires extra care (personal, financial, or confidential)."
    ),
    "standing_automation": STANDING_AUTOMATION_FLOOR_NOTE,
}


class CapabilityRegistrationError(Exception):
    """Raised internally when the co-protected table cannot be located/regenerated. Callers turn
    it into a refusal (never a partial write)."""


@dataclass(frozen=True)
class RegistrationResult:
    """Outcome of an operate-time capability registration.

    registered:           True IFF the descriptor was landed (and, for a gated capability, the
                          co-protected table regenerated) successfully.
    reason:               On refusal, a specific human-readable reason (None on success).
    capability_id:        The target capability id (echoed for the caller).
    co_protected_updated: True IFF the co-protected table was regenerated in this call (always
                          True for a gated capability that registered; False for a non-gated one).
    descriptor_set_path:  The descriptor-set file written (None on refusal).
    co_protected_path:    The co-protected file written (None if not updated).
    """
    registered: bool
    reason: Optional[str] = None
    capability_id: Optional[str] = None
    co_protected_updated: bool = False
    descriptor_set_path: Optional[str] = None
    co_protected_path: Optional[str] = None


def _refuse(reason: str, capability_id: Optional[str]) -> RegistrationResult:
    return RegistrationResult(registered=False, reason=reason, capability_id=capability_id)


def _resolve_risk_class(value: Any) -> str:
    """Fail-safe risk-class resolution (mirrors dependency_projection.resolve_risk_class /
    write_gate._effective_risk_class): a present, in-vocabulary value is honored (including
    read_only_local); anything absent/None/out-of-vocabulary resolves to the MOST-protected class
    (never silently to read_only_local)."""
    if isinstance(value, str) and value in RISK_CLASSES:
        return value
    return FAIL_SAFE_RISK_CLASS


def _md_cell(text: Any) -> str:
    # Markdown table cells cannot contain a raw pipe; escape defensively (mirrors the build-side
    # _md_cell in co_protected_workflows.py / capability_descriptor_registry.py).
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _strict_load_descriptor_set(path: str) -> List[Any]:
    """Read + parse the descriptor set STRICTLY (raises on unreadable / malformed / non-list)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("descriptor set is not a JSON array")
    return data


def _atomic_write_text(path: str, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file in the same dir + os.replace). Mirrors the
    acceptance ceremony's atomic writer, so a crash can never corrupt a trust file."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".capreg.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _descriptor_set_text(entries: List[Any]) -> str:
    """Canonical descriptor-set JSON text — the SAME formatting the build-side
    render_descriptor_registry_json and the acceptance ceremony emit (indent=2, ensure_ascii=
    False, trailing newline), so re-emit / parity stays reproducible."""
    return json.dumps(entries, indent=2, ensure_ascii=False) + "\n"


def co_protected_rows_from_entries(entries: List[Any]) -> List[str]:
    """The co-protected "Registered capability workflows" table rows for a descriptor set: one row
    per GATED (protection-requiring), non-base entry, in input order. Base ``__builtin__:``
    placeholders never appear (they are not real capabilities); non-gated entries are excluded (no
    over-firing). Risk class is resolved fail-safe, so an unclassified writer still shows up."""
    rows: List[str] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        ident = str(e.get("id", ""))
        if ident.startswith(BASE_DESCRIPTOR_ID_PREFIX):
            continue
        risk_class = _resolve_risk_class(e.get("risk_class"))
        if risk_class not in CO_PROTECTED_RISK_CLASSES:
            continue
        action_class = e.get("action_class")
        action_class = action_class if action_class is not None else "Unknown"
        note = _PROTECTION_NOTE.get(risk_class, "Protected — see risk class.")
        cells = [_md_cell(e.get("name")), _md_cell(action_class), _md_cell(risk_class),
                 _md_cell(note)]
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def _rewrite_co_protected_table(text: str, rows: List[str]) -> str:
    """Regenerate the co-protected "Registered capability workflows" table BODY, preserving all
    surrounding prose. Locates the header + separator lines, then replaces the region up to the
    next section rule (``---``) or heading (``## ``) with ``rows`` + one trailing blank line.

    Raises CapabilityRegistrationError if the table cannot be located — the caller turns that into
    a refusal, so a gated capability is never landed against a file whose guard table is missing."""
    lines = text.split("\n")
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip() == CO_PROTECTED_TABLE_HEADER:
            header_idx = i
            break
    if header_idx is None:
        raise CapabilityRegistrationError(
            "co-protected-workflows.md has no 'Registered capability workflows' table header — "
            "cannot register the capability's high-risk class for QA visibility")
    sep_idx = header_idx + 1
    if sep_idx >= len(lines) or not (
            lines[sep_idx].strip().startswith("|") and "---" in lines[sep_idx]):
        raise CapabilityRegistrationError(
            "co-protected-workflows.md table header is not followed by a separator row")
    # End of the body region: the first subsequent section rule or heading (exclusive).
    end_idx = len(lines)
    for i in range(sep_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped == "---" or stripped.startswith("## "):
            end_idx = i
            break
    new_lines = lines[:sep_idx + 1] + list(rows) + [""] + lines[end_idx:]
    return "\n".join(new_lines)


def register_declared_capability(
    declared: Dict[str, Any],
    *,
    descriptor_set_path: Optional[str] = None,
    co_protected_path: Optional[str] = None,
) -> RegistrationResult:
    """Land one newly-DECLARED (accepted:false) capability descriptor in the descriptor set and, for
    a GATED capability, regenerate the co-protected table in the same fail-safe operation.

    Fail-safe: on any missing / malformed / ambiguous input, refuse and write nothing. See the
    module docstring for the full set of guaranteed properties.

    Parameters
    ----------
    declared:            The declared-capability fields (a dict): id, name, action_class,
                        risk_class, recovery_profile_ref, declared_test_target, blast_radius_cap,
                        phase_id. ``accepted`` must be absent or false.
    descriptor_set_path: The descriptor-set file (default write_gate.DESCRIPTOR_SET_PATH).
    co_protected_path:   The co-protected table file (default DEFAULT_CO_PROTECTED_PATH).
    """
    if not isinstance(declared, dict):
        return _refuse("declared capability is not an object", None)

    cap_id = declared.get("id")
    if not (isinstance(cap_id, str) and cap_id.strip()):
        return _refuse("declared capability has no non-empty id", None)
    cap_id = cap_id.strip()
    if cap_id.startswith(BASE_DESCRIPTOR_ID_PREFIX):
        return _refuse(
            f"{cap_id!r} uses the reserved base-descriptor prefix and is not a declarable "
            "capability", cap_id)

    name = declared.get("name")
    if not (isinstance(name, str) and name.strip()):
        return _refuse("declared capability has no non-empty name", cap_id)

    phase_id = declared.get("phase_id")
    if not (isinstance(phase_id, str) and phase_id.strip()):
        return _refuse(
            "declared capability carries no non-empty phase_id — it could never be accepted; "
            "the cascade must bind it to its plan phase before registering it", cap_id)

    # This helper is never a path to accepted:true.
    if declared.get("accepted") is True:
        return _refuse(
            "declared capability is marked accepted:true — registration only ever lands "
            "accepted:false; acceptance is the acceptance ceremony's sole job", cap_id)

    # blast_radius_cap, if present, must be a positive integer (a gated capability needs one before
    # the ceremony will ever accept it, but declaration may legitimately leave it null for now).
    cap = declared.get("blast_radius_cap")
    if cap is not None and not (isinstance(cap, int) and not isinstance(cap, bool) and cap > 0):
        return _refuse(
            f"blast_radius_cap must be a positive integer or null (got {cap!r})", cap_id)

    risk_class = _resolve_risk_class(declared.get("risk_class"))

    if descriptor_set_path is None:
        descriptor_set_path = DESCRIPTOR_SET_PATH
    if not descriptor_set_path:
        return _refuse("no descriptor-set path configured", cap_id)
    if co_protected_path is None:
        co_protected_path = DEFAULT_CO_PROTECTED_PATH

    # --- load the descriptor set (strict, fail-closed) ---
    try:
        entries = _strict_load_descriptor_set(descriptor_set_path)
    except Exception as e:
        return _refuse(
            f"descriptor set is unreadable / malformed / not a JSON array: {e}", cap_id)

    for e in entries:
        if isinstance(e, dict) and e.get("id") == cap_id:
            return _refuse(
                f"a descriptor with id {cap_id!r} already exists — refusing to register a "
                "duplicate", cap_id)

    new_entry = {
        "id": cap_id,
        "name": name.strip(),
        "action_class": declared.get("action_class"),
        "risk_class": risk_class,
        "recovery_profile_ref": declared.get("recovery_profile_ref"),
        "declared_test_target": declared.get("declared_test_target"),
        "blast_radius_cap": cap,
        "accepted": False,
        "phase_id": phase_id.strip(),
    }
    new_entries = list(entries) + [new_entry]

    gated = risk_class in CO_PROTECTED_RISK_CLASSES

    if not gated:
        # No co-protected step for a non-gated capability — the descriptor set is the only write.
        try:
            _atomic_write_text(descriptor_set_path, _descriptor_set_text(new_entries))
        except Exception as e:
            return _refuse(f"could not write the descriptor set; no change made: {e}", cap_id)
        return RegistrationResult(
            registered=True, reason=None, capability_id=cap_id, co_protected_updated=False,
            descriptor_set_path=descriptor_set_path, co_protected_path=None)

    # --- GATED: regenerate the co-protected table from the FULL descriptor set (mandatory-by-
    # construction), then write it FIRST — before the descriptor set. See the module docstring for
    # why this order (not the reverse) is the fail-safe one: a crash between the two ``os.replace``
    # calls leaves at worst a harmless phantom guard row (never a blind guard on a live descriptor),
    # and a retry reconciles the phantom and lands the descriptor idempotently.
    try:
        with open(co_protected_path, encoding="utf-8") as f:
            original_co_text = f.read()
    except Exception as e:
        return _refuse(
            f"the co-protected-workflows table is missing / unreadable ({e}); a high-risk "
            "capability is not registered while the QA guard would stay blind to it", cap_id)
    try:
        rows = co_protected_rows_from_entries(new_entries)
        new_co_text = _rewrite_co_protected_table(original_co_text, rows)
    except CapabilityRegistrationError as e:
        return _refuse(str(e), cap_id)

    try:
        _atomic_write_text(co_protected_path, new_co_text)
    except Exception as e:
        return _refuse(
            f"could not write the co-protected guard table; no change made: {e}", cap_id)

    # --- write the descriptor set; roll the co-protected table back on failure (all-or-nothing) ---
    try:
        _atomic_write_text(descriptor_set_path, _descriptor_set_text(new_entries))
    except Exception as e:
        # Roll back the co-protected table to its exact prior text (a direct write, independent of
        # the atomic replace that just failed) so the guard table never carries a phantom row for a
        # capability that was never actually registered.
        try:
            Path(co_protected_path).write_text(original_co_text, encoding="utf-8")
        except Exception as rb:  # pragma: no cover - defensive
            return _refuse(
                f"descriptor-set write failed ({e}) AND co-protected rollback failed ({rb}); the "
                "co-protected table may carry a phantom guard row for an unregistered capability — "
                "resolve manually", cap_id)
        return _refuse(
            f"could not write the descriptor set ({e}); rolled the co-protected guard table back — "
            "the capability was NOT registered", cap_id)

    return RegistrationResult(
        registered=True, reason=None, capability_id=cap_id, co_protected_updated=True,
        descriptor_set_path=descriptor_set_path, co_protected_path=co_protected_path)


# ---------------------------------------------------------------------------
# CLI wrapper — the add-capability cascade writes the declared-capability fields to a JSON file
# (the design it already produced) and invokes this; the helper is the SOLE validating writer, so
# no free-form JSON editing of the trust file happens. Run from the operator project root so the
# default paths resolve. Exits 0 on registration, 1 on refusal, 2 on usage.
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys as _sys

    _args = _sys.argv[1:]
    _opts: Dict[str, Optional[str]] = {
        "--descriptor": None, "--descriptor-set": None, "--co-protected": None,
    }
    _usage = ("Usage: capability_registration.py --descriptor <declared.json> "
              "[--descriptor-set <path>] [--co-protected <path>]")
    _i = 0
    while _i < len(_args):
        _a = _args[_i]
        if _a in _opts:
            if _i + 1 >= len(_args):
                print(_usage, file=_sys.stderr)
                _sys.exit(2)
            _opts[_a] = _args[_i + 1]
            _i += 2
        else:
            print(f"unknown argument {_a!r}\n{_usage}", file=_sys.stderr)
            _sys.exit(2)

    if not _opts["--descriptor"]:
        print(f"missing required --descriptor\n{_usage}", file=_sys.stderr)
        _sys.exit(2)

    try:
        with open(_opts["--descriptor"], encoding="utf-8") as _f:
            _declared = json.load(_f)
    except Exception as _e:
        print(f"REFUSED: could not read the declared-capability file: {_e}", file=_sys.stderr)
        _sys.exit(1)

    _res = register_declared_capability(
        _declared,
        descriptor_set_path=_opts["--descriptor-set"],
        co_protected_path=_opts["--co-protected"])
    if _res.registered:
        _msg = f"REGISTERED: capability {_res.capability_id!r} declared (accepted:false)."
        if _res.co_protected_updated:
            _msg += " Its high-risk class is now registered in the co-protected guard table."
        print(_msg)
        _sys.exit(0)
    else:
        print(f"REFUSED: {_res.reason}", file=_sys.stderr)
        _sys.exit(1)
