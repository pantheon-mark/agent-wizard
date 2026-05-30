"""Typed derivation-groups registry loader + marker invariant (stdlib-only).

Loads the per-shape derivation-groups registry — the DATA that makes the wizard's
"logical groups" (vision / approach_roster / orchestration_build / hitl_autonomy /
tests_audit) DATA rather than file layout. Each group declares
which interview question-IDs feed it, which foundation-doc fields it derives, the step
after which all its inputs are captured (close_after), its confirmation marker, which
foundation docs render at its barrier (preview_docs), and which conditional question-IDs
count as satisfied when validly skipped (skip_satisfied_if).

Also provides the control-flow infra the carriers + barriers use:
  - group_inputs_complete  — the group-complete predicate (a validly-skipped conditional
                             question-ID counts as satisfied);
  - parse_progress_markers — parse the disk-first wizard_progress.md markers (step /
                             sub-step / group), preserving a group marker's source_hash /
                             source_range fields;
  - validate_marker_invariant — the marker-ordering invariant: a `step_NN: complete`
                             marker is ILLEGAL unless every group whose close_after ==
                             step_NN is confirmed (closes the "all sub-step markers present
                             but the barrier was skipped" resume path);
  - resume_point           — highest completed step + which groups are confirmed;
  - group_confirmation_is_stale — a stored group source_hash != the current recomputed
                             hash means an upstream answer changed; the confirmation is stale.

Fail-closed: a missing file, contract mismatch, or shape mismatch is a hard error; there
is no silent default-shape substitution (mirrors scaffold_plan.py). The source_hash itself
is computed over the recorded transcript events by the transcript recorder (T1); this module
owns the contract (markers carry the field) and the comparison, not the event store.

Stdlib-only, pip-install-free.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set


EXPECTED_CONTRACT_ID = "derivation-groups"
EXPECTED_CONTRACT_VERSIONS = {"derivation-groups-v1"}

# Top-level required keys in the registry JSON.
REQUIRED_TOP_FIELDS = ("system_shape", "auto_global_fields", "groups")
# Required keys per group entry.
REQUIRED_GROUP_FIELDS = (
    "group_id", "input_question_ids", "target_fields", "close_after",
    "confirmation_marker", "preview_docs", "skip_satisfied_if",
)

_STEP_RE = re.compile(r"^step_(\d+)$")


class DerivationGroupsError(Exception):
    """Raised when registry load/validation fails, or an unknown group is requested.
    The message names the failed check (fail-closed)."""


@dataclass(frozen=True)
class DerivationGroup:
    """One logical interview group (immutable)."""
    group_id: str
    input_question_ids: List[str]
    target_fields: List[str]
    close_after: str
    confirmation_marker: str
    preview_docs: List[str]
    skip_satisfied_if: List[str]


@dataclass(frozen=True)
class DerivationGroups:
    """The validated registry for one system shape."""
    system_shape: str
    auto_global_fields: List[str]
    groups: List[DerivationGroup]

    def group_by_id(self, group_id: str) -> DerivationGroup:
        for g in self.groups:
            if g.group_id == group_id:
                return g
        raise DerivationGroupsError(f"unknown group_id {group_id!r}")

    def groups_closing_at(self, step_marker: str) -> List[DerivationGroup]:
        """Every group whose close_after == step_marker (e.g. 'step_13')."""
        return [g for g in self.groups if g.close_after == step_marker]


# --- helpers -----------------------------------------------------------------

def _require(cond: bool, invariant: str, detail: str) -> None:
    if not cond:
        raise DerivationGroupsError(f"{invariant} FAIL: {detail}")


def default_registry_dir() -> Path:
    """Resolve wizard/foundation-bundles/v0/derivation-groups/ from this module's location
    (lib -> scripts -> wizard), matching the scaffold-plan loader's resolution idiom."""
    here = Path(__file__).resolve()
    wizard_root = here.parent.parent.parent
    return wizard_root / "foundation-bundles" / "v0" / "derivation-groups"


# --- loader ------------------------------------------------------------------

def load_derivation_groups(
    system_shape: str,
    registry_dir: Optional[Path] = None,
) -> DerivationGroups:
    """Load and validate the derivation-groups registry for the given shape.

    Resolves <registry_dir>/<system_shape>.json. A missing file is a hard failure —
    no silent fallback or default-shape substitution.
    """
    reg_dir = registry_dir or default_registry_dir()
    path = Path(reg_dir) / f"{system_shape}.json"

    if not path.exists():
        raise DerivationGroupsError(
            f"derivation-groups registry not found for shape {system_shape!r}: {path}"
        )
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise DerivationGroupsError(f"registry is not valid JSON: {path}: {e}") from e

    _require(isinstance(data, dict), "contract", "top-level value must be a JSON object")
    _require(
        data.get("contract_id") == EXPECTED_CONTRACT_ID,
        "contract_id", f"expected {EXPECTED_CONTRACT_ID!r}, got {data.get('contract_id')!r}",
    )
    cv = data.get("contract_version")
    _require(
        isinstance(cv, str) and cv in EXPECTED_CONTRACT_VERSIONS,
        "contract_version", f"must be one of {sorted(EXPECTED_CONTRACT_VERSIONS)}; got {cv!r}",
    )
    for fld in REQUIRED_TOP_FIELDS:
        _require(fld in data, "required_field", f"missing required top-level field {fld!r}")
    _require(
        data["system_shape"] == system_shape,
        "system_shape_match",
        f"file declares system_shape={data['system_shape']!r} but loader was asked for {system_shape!r}",
    )
    _require(isinstance(data["auto_global_fields"], list), "auto_global_fields", "must be a list")
    _require(isinstance(data["groups"], list) and data["groups"], "groups", "must be a non-empty list")

    groups: List[DerivationGroup] = []
    seen_ids: Set[str] = set()
    seen_markers: Set[str] = set()
    for raw in data["groups"]:
        _require(isinstance(raw, dict), "group", "each group must be an object")
        for gf in REQUIRED_GROUP_FIELDS:
            _require(gf in raw, "group_field", f"group missing required field {gf!r}")
        gid = raw["group_id"]
        _require(isinstance(gid, str) and gid, "group_id", "must be a non-empty string")
        _require(gid not in seen_ids, "group_id_unique", f"duplicate group_id {gid!r}")
        seen_ids.add(gid)
        for list_field in ("input_question_ids", "target_fields", "preview_docs", "skip_satisfied_if"):
            _require(isinstance(raw[list_field], list), list_field, f"{gid}.{list_field} must be a list")
        _require(bool(raw["input_question_ids"]), "input_question_ids", f"{gid} input_question_ids must be non-empty")
        _require(bool(raw["target_fields"]), "target_fields", f"{gid} target_fields must be non-empty")
        _require(bool(raw["preview_docs"]), "preview_docs", f"{gid} preview_docs must be non-empty")
        _require(
            isinstance(raw["close_after"], str) and _STEP_RE.match(raw["close_after"] or ""),
            "close_after", f"{gid}.close_after must look like 'step_NN'; got {raw['close_after']!r}",
        )
        marker = raw["confirmation_marker"]
        _require(isinstance(marker, str) and marker, "confirmation_marker", f"{gid} confirmation_marker must be non-empty")
        # Convention: the confirmation marker is group_<id>_confirmed.
        _require(
            marker == f"group_{gid}_confirmed",
            "confirmation_marker_convention",
            f"{gid} confirmation_marker must be 'group_{gid}_confirmed'; got {marker!r}",
        )
        _require(marker not in seen_markers, "confirmation_marker_unique", f"duplicate marker {marker!r}")
        seen_markers.add(marker)
        # skip_satisfied_if must be a subset of this group's input question-IDs.
        skip_extra = set(raw["skip_satisfied_if"]) - set(raw["input_question_ids"])
        _require(not skip_extra, "skip_satisfied_if_subset",
                 f"{gid}.skip_satisfied_if references non-input question-IDs {sorted(skip_extra)}")
        groups.append(DerivationGroup(
            group_id=gid,
            input_question_ids=list(raw["input_question_ids"]),
            target_fields=list(raw["target_fields"]),
            close_after=raw["close_after"],
            confirmation_marker=marker,
            preview_docs=list(raw["preview_docs"]),
            skip_satisfied_if=list(raw["skip_satisfied_if"]),
        ))

    return DerivationGroups(
        system_shape=data["system_shape"],
        auto_global_fields=list(data["auto_global_fields"]),
        groups=groups,
    )


# --- group-complete predicate ------------------------------------------------

def group_inputs_complete(
    group: DerivationGroup,
    answered_qids: Set[str],
    skipped_qids: Set[str],
) -> bool:
    """True when every input question-ID is satisfied. A question-ID is satisfied if it was
    answered, OR it was validly skipped (in skip_satisfied_if AND in skipped_qids). A skip of
    a question NOT in skip_satisfied_if does NOT satisfy it — that is an unexpected gap."""
    skip_eligible = set(group.skip_satisfied_if)
    answered = set(answered_qids)
    skipped = set(skipped_qids)
    for qid in group.input_question_ids:
        if qid in answered:
            continue
        if qid in skip_eligible and qid in skipped:
            continue
        return False
    return True


# --- progress markers --------------------------------------------------------

def parse_progress_markers(text: str) -> Dict[str, Dict[str, str]]:
    """Parse wizard_progress.md markers into {marker_name: {status, ...fields, raw}}.

    Recognised line shape: `<name>: <status> [| key=value]... [| <freetext/timestamp>]`.
    Step markers (`step_05`), sub-step markers (`step_04_NOTIF-2`), and group markers
    (`group_vision_confirmed: complete | source_range=0:12 | source_hash=sha256:...`)
    all parse. `key=value` tokens become fields; a bare trailing token is the timestamp.
    """
    out: Dict[str, Dict[str, str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        if not name:
            continue
        tokens = [t.strip() for t in rest.split("|")]
        fields: Dict[str, str] = {"raw": rest.strip()}
        if tokens:
            fields["status"] = tokens[0]
        for tok in tokens[1:]:
            if "=" in tok:
                k, _, v = tok.partition("=")
                fields[k.strip()] = v.strip()
            elif tok and "timestamp" not in fields:
                fields["timestamp"] = tok
        out[name] = fields
    return out


def _is_complete(marker: Optional[Dict[str, str]]) -> bool:
    return bool(marker) and marker.get("status") == "complete"


def validate_marker_invariant(
    markers: Dict[str, Dict[str, str]],
    groups: DerivationGroups,
) -> List[str]:
    """The marker-ordering invariant. A `step_NN: complete` marker is ILLEGAL unless every
    group whose close_after == step_NN is confirmed. Returns a list of violation strings
    (empty == invariant holds). This closes the resume path where every sub-step marker is
    present and the step marker lands while a group barrier was skipped with unprojectable
    fields."""
    violations: List[str] = []
    for g in groups.groups:
        if _is_complete(markers.get(g.close_after)) and not _is_complete(markers.get(g.confirmation_marker)):
            violations.append(
                f"{g.close_after} is marked complete but group {g.group_id!r} "
                f"({g.confirmation_marker}) is not confirmed — the group barrier was skipped"
            )
    return violations


def resume_point(
    markers: Dict[str, Dict[str, str]],
    groups: DerivationGroups,
) -> Dict[str, object]:
    """Compute the resume cursor: highest completed step number, the set of confirmed groups,
    and any marker-invariant violations (a non-empty `violations` means an internal-state
    error the caller must reconcile before proceeding)."""
    highest = 0
    for name, fields in markers.items():
        m = _STEP_RE.match(name)
        if m and _is_complete(fields):
            highest = max(highest, int(m.group(1)))
    confirmed = {g.group_id for g in groups.groups if _is_complete(markers.get(g.confirmation_marker))}
    return {
        "highest_completed_step": highest,
        "confirmed_groups": confirmed,
        "violations": validate_marker_invariant(markers, groups),
    }


def group_confirmation_is_stale(
    group_marker: Dict[str, str],
    current_source_hash: str,
) -> bool:
    """True when a group's stored confirmation source_hash differs from the current recomputed
    hash — meaning an upstream answer feeding the group changed after it was confirmed, so the
    confirmation (and any dependent group confirmations) must be invalidated and re-run. A marker
    with no stored source_hash is treated as stale (cannot prove freshness; fail-closed)."""
    stored = (group_marker or {}).get("source_hash")
    if not stored:
        return True
    return stored != current_source_hash


def main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("usage: derivation_groups.py <system-shape> [registry-dir]", file=sys.stderr)
        return 2
    reg_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        dg = load_derivation_groups(sys.argv[1], reg_dir)
    except DerivationGroupsError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print(f"OK: {len(dg.groups)} groups for shape {dg.system_shape!r}")
    for g in dg.groups:
        print(f"  {g.group_id:20s} close_after={g.close_after} "
              f"inputs={len(g.input_question_ids)} fields={len(g.target_fields)} "
              f"preview={g.preview_docs}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
