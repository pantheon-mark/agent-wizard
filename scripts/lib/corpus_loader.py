"""Inherited-corpus loader (stdlib-only; pip-install-free).

Loads the wizard-distributed inherited-corpus PACK (the self-contained set of operating
principles + disciplines compiled from the build-side policy registry) and validates it
against its contract (inherited-corpus-contract-v1.json) — invariants C1-C7, fail-closed.

Then RESOLVES the pack for a target system shape and projects the content-bearing cells
into the emission-plan `corpus_cells` shape, so the downstream emitter reads ONLY a
validated plan (never a build-side path). The pack is itself self-contained (operator-facing
content + neutral OP-NN identifiers only); this loader reads only the distributed pack + contract.

Three realization classes:
  - corpus-body      : carries a canonical principle body (-> a plan corpus_cell, inline_payload)
                       + optional per-target operational hooks (single-home + cross-reference).
  - scaffold-template: realized by installing scaffold template(s) (-> scaffold_targets; NOT a
                       plan corpus_cell — the scaffold emitter handles these).
  - delegated        : realized by a delegated control already in the scaffold (recorded for the
                       authority manifest; emits no new content).

The wizard distribution stays stdlib-only: JSON via `json`, no PyYAML / jsonschema.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


EXPECTED_CONTRACT_ID = "inherited-corpus"
EXPECTED_CONTRACT_VERSIONS = {"inherited-corpus-v1"}


class CorpusError(Exception):
    """Raised when corpus pack load/validation fails. Message names the invariant."""


# --- typed records -----------------------------------------------------------

@dataclass(frozen=True)
class Canonical:
    category: str
    home: str
    body: str


@dataclass(frozen=True)
class TargetHook:
    target: str
    hook_type: str
    text: str


@dataclass(frozen=True)
class CorpusCellRecord:
    cell_id: str
    cell_version: str
    shape_scope: List[str]
    phase_scope: List[str]
    authority_gate: str
    authority_basis_default: str
    authority_source_default: str
    data_risk_gate: str
    emission_posture: str
    realization: str
    public_source_label: str
    canonical: Optional[Canonical] = None
    target_hooks: List[TargetHook] = field(default_factory=list)
    scaffold_targets: List[str] = field(default_factory=list)
    applicability_gate: Optional[str] = None


# --- contract + pack loading -------------------------------------------------

def default_corpus_contract_path() -> Path:
    here = Path(__file__).resolve()
    wizard_root = here.parent.parent.parent
    return wizard_root / "foundation-bundles" / "v0" / "contracts" / "inherited-corpus-contract-v1.json"


def default_corpus_pack_path() -> Path:
    here = Path(__file__).resolve()
    wizard_root = here.parent.parent.parent
    return wizard_root / "foundation-bundles" / "v0" / "corpus" / "inherited-corpus-v1.json"


def load_corpus_contract(contract_path: Path) -> Dict[str, Any]:
    try:
        with contract_path.open("r", encoding="utf-8") as f:
            contract = json.load(f)
    except FileNotFoundError as e:
        raise CorpusError(f"Corpus contract not found: {contract_path}") from e
    except json.JSONDecodeError as e:
        raise CorpusError(f"Corpus contract is not valid JSON: {contract_path}: {e}") from e
    if not isinstance(contract, dict):
        raise CorpusError("Corpus contract top-level value must be a JSON object")
    if contract.get("contract_id") != EXPECTED_CONTRACT_ID:
        raise CorpusError(f"contract_id mismatch — expected {EXPECTED_CONTRACT_ID!r}, got {contract.get('contract_id')!r}")
    cv = contract.get("contract_version")
    if cv not in EXPECTED_CONTRACT_VERSIONS:
        raise CorpusError(f"contract_version must be one of {sorted(EXPECTED_CONTRACT_VERSIONS)}; got {cv!r}")
    for key in ("enums", "required_pack_fields", "required_cell_fields", "canonical_fields", "target_hook_fields"):
        if key not in contract:
            raise CorpusError(f"corpus contract missing required section {key!r}")
    return contract


# --- helpers -----------------------------------------------------------------

def _require(cond: bool, invariant: str, detail: str) -> None:
    if not cond:
        raise CorpusError(f"{invariant} FAIL: {detail}")


def _enum(enums: Dict[str, List[str]], name: str, value: Any, where: str) -> None:
    members = enums.get(name, [])
    _require(value in members, "C2", f"{where} value {value!r} not in closed enum {name}={members}")


# --- pack validation (C1-C7) -------------------------------------------------

def validate_corpus_pack(pack: Dict[str, Any], contract: Dict[str, Any]) -> List[CorpusCellRecord]:
    enums = contract["enums"]

    # C1 — pack-level fields
    for f_name in contract["required_pack_fields"]:
        _require(f_name in pack, "C1", f"missing required pack field {f_name!r}")
    _require(pack["contract_id"] == EXPECTED_CONTRACT_ID, "C1", "pack contract_id mismatch")
    _require(pack["contract_version"] in EXPECTED_CONTRACT_VERSIONS, "C1", "pack contract_version mismatch")
    _require(isinstance(pack["corpus_pack_version"], str) and pack["corpus_pack_version"], "C1",
             "corpus_pack_version must be a non-empty string")
    cells = pack["cells"]
    _require(isinstance(cells, list) and cells, "C1", "cells must be a non-empty list")

    records: List[CorpusCellRecord] = []
    seen_ids = set()
    for i, c in enumerate(cells):
        where = f"cells[{i}]"
        _require(isinstance(c, dict), "C2", f"{where} must be an object")
        for f_name in contract["required_cell_fields"]:
            _require(f_name in c, "C2", f"{where} missing required field {f_name!r}")

        # C3 — unique cell_id
        cid = c["cell_id"]
        _require(cid not in seen_ids, "C3", f"duplicate cell_id {cid!r}")
        seen_ids.add(cid)

        # C2 — enum-valued fields
        _enum(enums, "authority_gate", c["authority_gate"], f"{where}.authority_gate")
        _enum(enums, "authority_basis", c["authority_basis_default"], f"{where}.authority_basis_default")
        _enum(enums, "authority_source", c["authority_source_default"], f"{where}.authority_source_default")
        _enum(enums, "data_risk_gate", c["data_risk_gate"], f"{where}.data_risk_gate")
        _enum(enums, "emission_posture", c["emission_posture"], f"{where}.emission_posture")
        _enum(enums, "realization", c["realization"], f"{where}.realization")

        # C7 — shape/phase scope members
        _require(isinstance(c["shape_scope"], list) and c["shape_scope"], "C2", f"{where}.shape_scope must be a non-empty list")
        for s in c["shape_scope"]:
            _enum(enums, "system_shape", s, f"{where}.shape_scope")
        _require(isinstance(c["phase_scope"], list) and c["phase_scope"], "C2", f"{where}.phase_scope must be a non-empty list")
        for p in c["phase_scope"]:
            _enum(enums, "lifecycle_phase", p, f"{where}.phase_scope")

        # C5 — authority coupling (mirrors emission-plan I3)
        gate = c["authority_gate"]
        if gate == "applies-all":
            _require(c["authority_basis_default"] == "not_applicable", "C5",
                     f"{where} authority_gate=applies-all requires authority_basis_default=not_applicable")
            _require(c["authority_source_default"] == "not_applicable", "C5",
                     f"{where} authority_gate=applies-all requires authority_source_default=not_applicable")
        else:
            _require(c["authority_basis_default"] == "provisional_default", "C5",
                     f"{where} authority_gate={gate} requires authority_basis_default=provisional_default")
            _require(c["authority_source_default"] in ("delegated", "wizard-default", "hard-control", "operator-configured"),
                     "C5", f"{where} authority_gate={gate} requires a concrete authority_source_default")

        # C4 — realization / canonical coupling
        realization = c["realization"]
        canonical = c.get("canonical")
        if realization == "corpus-body":
            _require(isinstance(canonical, dict), "C4", f"{where} realization=corpus-body requires a canonical object")
            for cf in contract["canonical_fields"]:
                _require(cf in canonical, "C4", f"{where}.canonical missing field {cf!r}")
            _require(isinstance(canonical["body"], str) and canonical["body"].strip(), "C4",
                     f"{where}.canonical.body must be non-empty")
            _require(isinstance(canonical["home"], str) and canonical["home"], "C4",
                     f"{where}.canonical.home must be non-empty")
            _require(isinstance(canonical["category"], str) and canonical["category"], "C4",
                     f"{where}.canonical.category must be non-empty")
        else:
            _require(canonical is None, "C4",
                     f"{where} realization={realization} must NOT carry a canonical body")

        # C6 — target hooks
        hooks: List[TargetHook] = []
        for j, h in enumerate(c.get("target_hooks", []) or []):
            hw = f"{where}.target_hooks[{j}]"
            _require(isinstance(h.get("target"), str) and h["target"], "C6", f"{hw}.target must be non-empty")
            _require(h.get("hook_type") in enums.get("hook_type", []), "C6",
                     f"{hw}.hook_type {h.get('hook_type')!r} not in closed enum hook_type={enums.get('hook_type', [])}")
            hooks.append(TargetHook(target=h["target"], hook_type=h["hook_type"], text=h.get("text", "")))

        records.append(CorpusCellRecord(
            cell_id=cid, cell_version=str(c["cell_version"]),
            shape_scope=list(c["shape_scope"]), phase_scope=list(c["phase_scope"]),
            authority_gate=gate, authority_basis_default=c["authority_basis_default"],
            authority_source_default=c["authority_source_default"], data_risk_gate=c["data_risk_gate"],
            emission_posture=c["emission_posture"], realization=realization,
            public_source_label=c["public_source_label"],
            canonical=Canonical(**{k: canonical[k] for k in ("category", "home", "body")}) if canonical else None,
            target_hooks=hooks, scaffold_targets=list(c.get("scaffold_targets", []) or []),
            applicability_gate=c.get("applicability_gate"),
        ))
    return records


def load_corpus_pack(pack_path: Optional[Path] = None,
                     contract_path: Optional[Path] = None) -> List[CorpusCellRecord]:
    """Load + validate the distributed corpus pack; return typed cell records."""
    contract = load_corpus_contract(contract_path or default_corpus_contract_path())
    pp = pack_path or default_corpus_pack_path()
    try:
        with Path(pp).open("r", encoding="utf-8") as f:
            pack = json.load(f)
    except FileNotFoundError as e:
        raise CorpusError(f"Corpus pack not found: {pp}") from e
    except json.JSONDecodeError as e:
        raise CorpusError(f"Corpus pack is not valid JSON: {pp}: {e}") from e
    if not isinstance(pack, dict):
        raise CorpusError("Corpus pack top-level value must be a JSON object")
    return validate_corpus_pack(pack, contract)


# --- resolution + plan projection -------------------------------------------

def resolve_for_shape(records: List[CorpusCellRecord], system_shape: str) -> List[CorpusCellRecord]:
    """Filter to cells applicable to `system_shape` (shape_scope contains it OR 'all-shapes')."""
    return [r for r in records if system_shape in r.shape_scope or "all-shapes" in r.shape_scope]


def to_plan_corpus_cells(records: List[CorpusCellRecord]) -> List[Dict[str, Any]]:
    """Project the content-bearing (corpus-body) cells into emission-plan `corpus_cells`.

    Only corpus-body cells become plan corpus_cells (they carry inline payloads). scaffold-template
    and delegated cells are NOT plan corpus_cells — the scaffold emitter installs templates and the
    delegated controls are already in the scaffold; both are still recorded in the authority manifest.

    The projection is I1-I10-clean: source_type=inline_payload + non-empty payload (I8); authority
    basis/source coupling matches I3; emission_target = canonical home + hook targets.
    """
    out: List[Dict[str, Any]] = []
    for r in records:
        if r.realization != "corpus-body" or r.canonical is None:
            continue
        targets = [r.canonical.home] + [h.target for h in r.target_hooks]
        out.append({
            "cell_id": r.cell_id,
            "emission_target": targets,
            "emission_posture": r.emission_posture,
            "authority_gate": r.authority_gate,
            "authority_basis": r.authority_basis_default,
            "authority_source": r.authority_source_default,
            "source_type": "inline_payload",
            "payload": r.canonical.body,
        })
    return out


def main() -> int:
    import sys
    try:
        records = load_corpus_pack()
    except CorpusError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    body = sum(1 for r in records if r.realization == "corpus-body")
    scaf = sum(1 for r in records if r.realization == "scaffold-template")
    deleg = sum(1 for r in records if r.realization == "delegated")
    resolved = resolve_for_shape(records, "markdown-CC")
    plan_cells = to_plan_corpus_cells(resolved)
    print(f"OK: corpus pack validated — {len(records)} cells "
          f"({body} corpus-body / {scaf} scaffold-template / {deleg} delegated)")
    print(f"  markdown-CC resolved: {len(resolved)} cells; plan corpus_cells projection: {len(plan_cells)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
