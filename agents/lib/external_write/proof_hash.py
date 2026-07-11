"""Builder-computed proof hashes — the Proof clause identity (copy-first, hash-gated).

An operation's identity for the accepted-write list is (implementation_hash,
contract_hash), BOTH computed by the builder over the REAL material — never declared
by the model:

  * implementation_hash — sha256 over the bytes of every write-affecting dependency
    file (adapter code, helper libs, generated op templates, verifier defs file), the
    canonical contract, the resolved verifier defs, and runtime params that alter write
    semantics. Any change to any of these changes the hash, dropping the op off the
    accepted list and forcing a fresh copy-run. A missing dependency file is fail-closed
    (a coverage-incomplete hash would reopen the in-place-edit hole).

    The dependency-file list is resolved per op_kind by
    `effects_manifest.resolve_dependency_files` — the contract's declared
    `dependency_set` UNION the op_kind's registered adapter module, if any
    (Task 3 — external-write-gate-generalization; closes F-34, where this hash
    used to cover only a fixed shared-module tuple and structurally excluded a
    capability's own adapter code).
  * contract_hash — sha256 over the declared surface (writes/produces/dependency_set/
    verifier_set/binding flag) + resolved verifier defs. Schema/contract identity,
    independent of code bytes.

Enforcement ceiling: build-time + operator-as-approver, NOT a runtime/OS guarantee.

Stdlib only — no third-party dependencies.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from external_write.contracts import get_contract, get_verifier
from external_write.effects_manifest import resolve_dependency_files

# SHA-256 produces a 64-character lowercase hex digest.
SHA256_HEX_LEN = 64


class ProofHashError(Exception):
    """Raised when a hash cannot be computed over complete material (fail-closed)."""


def _default_lib_dir() -> Path:
    return Path(__file__).resolve().parent


def _verifier_canon(verifier_id: str) -> dict:
    v = get_verifier(verifier_id)
    if v is None:
        raise ProofHashError(f"verifier {verifier_id!r} is not registered")
    return {
        "verifier_id": v.verifier_id,
        "mode": v.mode.value,
        "pre_write_sources": list(v.source_lineage.pre_write_sources),
        "post_write_sources": list(v.source_lineage.post_write_sources),
        "forbidden_verification_inputs": list(
            v.source_lineage.forbidden_verification_inputs
        ),
    }


def _contract_canon(op_kind: str) -> dict:
    c = get_contract(op_kind)
    if c is None:
        raise ProofHashError(f"operation kind {op_kind!r} has no registered contract")
    return {
        "op_kind": c.op_kind,
        "writes": list(c.writes),
        "produces": list(c.produces),
        "dependency_set": list(c.dependency_set),
        "verifier_set": list(c.verifier_set),
        "introduces_persistent_binding": c.introduces_persistent_binding,
        # B1-3 / D-B1-b (LOCKED): these three risk fields are deliberately hash-bound
        # so a post-hoc change to any of them — most importantly a risk_class
        # downgrade — changes both compute_contract_hash and compute_implementation_hash
        # (the latter includes this canon via compute_implementation_hash's own
        # "contract" section below) and invalidates any previously-accepted proof.
        "risk_class": c.risk_class,
        "requires_accepted_phase": c.requires_accepted_phase,
        "blast_radius_cap": c.blast_radius_cap,
        "verifiers": [_verifier_canon(vid) for vid in sorted(c.verifier_set)],
    }


def compute_implementation_hash(op_kind: str, *, lib_dir: Optional[Path] = None,
                                runtime_params: Optional[dict] = None) -> str:
    """sha256 over the real transitive write-affecting dependency graph for op_kind."""
    c = get_contract(op_kind)
    if c is None:
        raise ProofHashError(f"operation kind {op_kind!r} has no registered contract")
    root = Path(lib_dir) if lib_dir is not None else _default_lib_dir()

    h = hashlib.sha256()
    for fname in sorted(resolve_dependency_files(op_kind)):
        candidate = Path(fname)
        # A bare filename (the static declared dependency_set) resolves
        # against `root` as before; an adapter module's path is already
        # absolute (resolved via its loaded module's __file__ in
        # effects_manifest) and hashes correctly regardless of `root`.
        fpath = candidate if candidate.is_absolute() else root / fname
        if not fpath.is_file():
            raise ProofHashError(
                f"write-affecting dependency {fname!r} not found under {root} "
                "(refusing a coverage-incomplete implementation hash)"
            )
        h.update(fname.encode("utf-8"))
        h.update(b"\x00")
        h.update(fpath.read_bytes())
        h.update(b"\x00")

    h.update(b"contract\x00")
    h.update(json.dumps(_contract_canon(op_kind), sort_keys=True,
                        ensure_ascii=True).encode("utf-8"))
    h.update(b"\x00runtime\x00")
    h.update(json.dumps(runtime_params or {}, sort_keys=True,
                        ensure_ascii=True).encode("utf-8"))
    return h.hexdigest()


def compute_contract_hash(op_kind: str) -> str:
    """sha256 over the declared contract surface + resolved verifier defs."""
    payload = json.dumps(_contract_canon(op_kind), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AcceptedWriteKey:
    implementation_hash: str
    contract_hash: str


def is_accepted(key: AcceptedWriteKey, registry: Iterable[AcceptedWriteKey]) -> bool:
    """True iff an entry in registry matches BOTH hashes of key."""
    for entry in registry:
        if (entry.implementation_hash == key.implementation_hash
                and entry.contract_hash == key.contract_hash):
            return True
    return False


# Nothing is accepted until a copy_run_proof records it. Empty by default so the
# gate fires for first live use of every operation.
ACCEPTED_WRITE_REGISTRY: tuple = ()
