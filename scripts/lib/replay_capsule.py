"""Replay-capsule emitter — writes `.wizard/replay-capsule.json` into the operator
project so a future foundation-bundle upgrade can deterministically re-render the
foundation documents from the SAME inputs the project was first built from.

What the capsule carries:
  - the operator's foundation-doc inputs (`plan.foundation_doc_inputs`), so the
    upgrade path can render the CURRENT-version docs and confirm they match the
    manifest base_hash (replay-conformance) before it renders the target version.
  - provenance pinning the inputs to one build: foundation_bundle_version,
    generator_version (the same 40-char SHA the manifest records), system_shape,
    foundation_only_mode, plus the canonicalization/hash-scheme stamps shared with
    the upgrade engine.

Privacy posture: the capsule holds the operator's interview answers, so before any
write it is run through a FAIL-CLOSED secret scan. If any value looks like a
credential / token / private-key, the emit is REFUSED with a message naming the
offending KEY (never the value) — credentials belong in .env, not interview
answers. The emitted .gitignore excludes the capsule by default (local-only unless
the operator opts in).

Determinism: pretty JSON with sorted keys + trailing newline; no clock / no
randomness. Stdlib-only, pip-install-free (operator/runtime path).
"""

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from emission_plan import EmissionPlan  # type: ignore
from upgrade import CANONICALIZATION_VERSION, HASH_ALGORITHM  # type: ignore


# v1: foundation_doc_inputs only (could not re-render the operating layer).
# v2: adds an `operating` block carrying the RESOLVED substitution values for every
#     `delivery:wizard render_kind:render` operating-layer file, so a future upgrade
#     can re-render those files as a pure template-substitution op (durable against
#     generator-Python refactors — see the durability note on build_replay_capsule).
CAPSULE_SCHEMA_VERSION = "replay-capsule-v2"
CAPSULE_SCHEMA_VERSION_FOUNDATION_ONLY = "replay-capsule-v1"

REPLAY_CAPSULE_REL = ".wizard/replay-capsule.json"


class ReplayCapsuleError(Exception):
    """Raised when the replay capsule cannot be safely emitted — chiefly when a
    credential/token-shaped value is found in the foundation-doc inputs. Fail-closed:
    refuse to emit rather than persist a secret to disk."""


# --- Secret-scan rule set ---------------------------------------------------
#
# Rule-LEVEL detectors (not value-level): each describes a SHAPE of credential, so
# planting a fresh token of the same class is still caught. Tuned to avoid flagging
# ordinary business prose — the high-entropy heuristic only fires on a single
# unbroken token (no whitespace) that is both long AND high-entropy, which normal
# sentences (full of spaces + low per-char entropy) never are.

# Vendor / format-specific prefixes (anchored to a following token body so a bare
# mention of the prefix word in prose does not trip them).
_PREFIX_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("openai-style key (sk-)", re.compile(r"sk-[A-Za-z0-9_-]{16,}")),
    ("github token (ghp_/gho_/ghu_/ghs_)", re.compile(r"gh[pous]_[A-Za-z0-9]{16,}")),
    ("aws access key id (AKIA…)", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key block (-----BEGIN …-----)", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("slack token (xox[baprs]-…)", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
]

# `key=value` credential assignments (case-insensitive key; value must be a
# non-trivial token, not an empty placeholder or a relationship word).
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
    r"client[_-]?secret|auth[_-]?token|bearer)\s*[=:]\s*[^\s'\"]{6,}"
)

# High-entropy long-token heuristic: a single whitespace-free run of credential-class
# characters, long enough + random enough that prose never produces it.
_TOKEN_CHARS = re.compile(r"[A-Za-z0-9+/=_-]{32,}")
_ENTROPY_MIN_LEN = 32
_ENTROPY_BITS_PER_CHAR = 3.5  # english prose ~<3.0; random base64/hex ~4.5-6.0
_ENTROPY_MIN_DISTINCT = 16    # a 32-char run of few distinct symbols is not a secret


def _shannon_entropy_bits_per_char(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_high_entropy_token(token: str) -> bool:
    """True if `token` is a single long, high-entropy, high-cardinality run — the
    shape of an API key / hex digest, not of a word or a hyphenated phrase. Prose is
    excluded structurally: the token regex requires NO whitespace, so a sentence can
    never match as one token; on top of that we require both high per-char entropy
    AND many distinct characters, which ordinary identifiers (e.g. a long snake_case
    field name) fail."""
    if len(token) < _ENTROPY_MIN_LEN:
        return False
    if len(set(token)) < _ENTROPY_MIN_DISTINCT:
        return False
    return _shannon_entropy_bits_per_char(token) >= _ENTROPY_BITS_PER_CHAR


def _scan_value(value: Any) -> List[str]:
    """Return a list of human-readable reasons this value looks like a secret
    (empty list = clean). Recurses into list/dict containers so nested inputs are
    covered."""
    reasons: List[str] = []
    if isinstance(value, str):
        for label, pat in _PREFIX_PATTERNS:
            if pat.search(value):
                reasons.append(label)
        if _ASSIGNMENT_PATTERN.search(value):
            reasons.append("credential assignment (e.g. password=/token=/api_key=)")
        for token in _TOKEN_CHARS.findall(value):
            if _looks_high_entropy_token(token):
                reasons.append("high-entropy token (credential-shaped string)")
                break
    elif isinstance(value, dict):
        for v in value.values():
            reasons.extend(_scan_value(v))
    elif isinstance(value, (list, tuple)):
        for v in value:
            reasons.extend(_scan_value(v))
    return reasons


def _collect_secret_hits(inputs: dict, key_prefix: str = "") -> List[str]:
    """Return human-readable '<key> (<reasons>)' hits for credential-shaped values in
    `inputs`. `key_prefix` namespaces the reported key (e.g. an agent relpath) so the
    message points at the exact location across the capsule's nested blocks."""
    hits: List[str] = []
    for key, value in inputs.items():
        reasons = _scan_value(value)
        if reasons:
            seen: List[str] = []
            for r in reasons:
                if r not in seen:
                    seen.append(r)
            label = f"{key_prefix}{key}" if key_prefix else str(key)
            hits.append(f"{label!r} ({'; '.join(seen)})")
    return hits


def scan_inputs_for_secrets(foundation_doc_inputs: dict,
                            operating: Optional[dict] = None) -> None:
    """Fail-closed pre-write guard. Scan every value in `foundation_doc_inputs` AND,
    when present, every value in the v2 `operating` block (resolved_scaffold_inputs +
    each agent's resolved_inputs + orchestrator/qa/cron resolved_inputs) for
    credential/token-shaped strings. On ANY hit raise ReplayCapsuleError naming the
    offending KEY (never the value) and refusing to emit. Clean inputs return None."""
    hits: List[str] = _collect_secret_hits(foundation_doc_inputs)

    if operating:
        scaffold = operating.get("resolved_scaffold_inputs") or {}
        hits += _collect_secret_hits(scaffold, key_prefix="resolved_scaffold_inputs.")
        for relpath, resolved in sorted((operating.get("by_relpath") or {}).items()):
            hits += _collect_secret_hits(resolved, key_prefix=f"{relpath}:")

    if hits:
        raise ReplayCapsuleError(
            "refusing to write the replay capsule: credential/token-shaped value(s) "
            "found in capsule inputs: " + ", ".join(sorted(hits)) + ". "
            "Credentials belong in .env, not in interview answers — remove the secret "
            "from the answer (reference it indirectly) and re-run, so the capsule never "
            "persists a secret to disk."
        )


def _wizard_render_persisted_keys(bundle_version: str, build_repo_root: Path) -> set:
    """Union of `inputs.persisted` keys across every `delivery:wizard render_kind:render`
    contract entry for the bundle. These are the inputs the capsule must carry RESOLVED
    (the `inputs.derived` keys are re-derived from the target bundle at upgrade time and
    are NOT stored)."""
    from bundle_templates import _bundle_dir  # type: ignore
    contract_path = _bundle_dir(bundle_version, build_repo_root) / "system-artifacts.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    keys: set = set()
    for entry in contract.get("artifacts", []):
        if entry.get("delivery") == "wizard" and entry.get("render_kind") == "render":
            keys |= set((entry.get("inputs") or {}).get("persisted", []))
    return keys


def build_operating_block(plan: EmissionPlan, build_repo_root: Path) -> Optional[dict]:
    """Build the v2 `operating` block: the RESOLVED substitution values for every
    `delivery:wizard render_kind:render` operating-layer file. None when the bundle
    carries no operating layer or the plan is foundation-only (no operating files emitted).

    Two parts:
      - resolved_scaffold_inputs: the scaffold/root render files share ONE substitution
        map (build_scaffold_inputs). We carry the persisted subset only — keys that are
        (a) a persisted input of some wizard-render file per the contract AND (b) present
        in the scaffold map AND (c) NOT already in foundation_doc_inputs (those round-trip
        via the existing block — no duplication). `derived` inputs are excluded by
        construction (they are not persisted keys).
      - by_relpath: each agent-layer render file -> its exact resolved substitution dict
        (per-agent prompts/scripts + orchestrator + qa + cron).

    Values are the SAME strings the emitters substitute (reused from the emitter helpers),
    so re-render is a pure substitution that reproduces the emitted bytes."""
    from bundle_templates import bundle_has_operating_layer  # type: ignore
    if plan.foundation_only_mode:
        return None
    if not bundle_has_operating_layer(plan.bundle_version, build_repo_root):
        return None

    # Reuse the EXACT scaffold-extra the orchestrator feeds emit_scaffold, so the resolved
    # values match the emitted files byte-for-byte.
    from scaffold_emitter import build_scaffold_inputs  # type: ignore
    from corpus_emitter import render_claude_md_block  # type: ignore
    from corpus_loader import load_corpus_pack  # type: ignore
    from authority_profile import autonomous_actions_summary  # type: ignore
    from agent_emitter import build_agent_resolved_inputs  # type: ignore

    records = load_corpus_pack()
    block = render_claude_md_block(plan, records)
    autonomy_level = plan.foundation_doc_inputs.get("AUTONOMY_LEVEL", "1")
    scaffold_extra = {
        "INHERITED_OPERATING_PRINCIPLES": block,
        "AUTONOMOUS_ACTIONS": autonomous_actions_summary(autonomy_level),
    }
    core_purpose = str(plan.foundation_doc_inputs.get("CORE_PURPOSE", "")).strip()
    if core_purpose:
        scaffold_extra["PROJECT_PURPOSE"] = core_purpose
    scaffold_inputs = build_scaffold_inputs(plan, scaffold_extra)

    persisted = _wizard_render_persisted_keys(plan.bundle_version, build_repo_root)
    fdi_keys = set(plan.foundation_doc_inputs)
    resolved_scaffold_inputs = {
        k: scaffold_inputs[k]
        for k in persisted
        if k in scaffold_inputs and k not in fdi_keys
    }

    agent_block = build_agent_resolved_inputs(plan)
    by_relpath = agent_block.get("by_relpath", {}) if agent_block else {}

    return {
        "resolved_scaffold_inputs": resolved_scaffold_inputs,
        "by_relpath": by_relpath,
    }


def build_replay_capsule(plan: EmissionPlan, build_repo_root: Optional[Path] = None) -> dict:
    """Build the replay-capsule dict from the emission plan. Deterministic. Provenance
    fields come from the SAME plan attributes the manifest emitter uses (no
    re-derivation): foundation_bundle_version = plan.bundle_version, generator_version,
    system_shape, foundation_only_mode.

    When `build_repo_root` is supplied AND the plan emits an operating layer, the capsule
    is schema v2 and carries the resolved `operating` block (see build_operating_block).
    Foundation-only / no-operating-layer plans stay schema v1 and carry no operating block.

    DURABILITY: the operating block stores the RESOLVED substitution values (the exact
    strings passed into _substitute_placeholders), NOT raw upstream facts — so replay is a
    pure template-substitution op, durable against future generator-Python refactors. This
    mirrors how foundation_doc_inputs already stores resolved values (e.g. AGENT_ROSTER_ROWS)."""
    operating = None
    if build_repo_root is not None:
        operating = build_operating_block(plan, build_repo_root)

    doc = {
        "schema_version": CAPSULE_SCHEMA_VERSION if operating is not None
        else CAPSULE_SCHEMA_VERSION_FOUNDATION_ONLY,
        "foundation_bundle_version": plan.bundle_version,
        "generator_version": plan.generator_version,
        "system_shape": plan.system_shape,
        "foundation_only_mode": plan.foundation_only_mode,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "foundation_doc_inputs": dict(plan.foundation_doc_inputs),
    }
    if operating is not None:
        doc["operating"] = operating
    return doc


def capsule_supports_operating_replay(capsule: dict) -> bool:
    """Return True iff the capsule is schema v2 AND carries an `operating` block.

    A v1 capsule (foundation-only systems, e.g. built on v0.4.0) has schema
    CAPSULE_SCHEMA_VERSION_FOUNDATION_ONLY and no `operating` key — this returns
    False. A v2 capsule (full systems from v0.6.0) has schema CAPSULE_SCHEMA_VERSION
    and an `operating` block — returns True. Callers use this to decide between
    foundation-only vs full operating-layer replay handling without KeyError.

    Safe to call on any capsule dict; never raises."""
    return (
        isinstance(capsule, dict)
        and capsule.get("schema_version") == CAPSULE_SCHEMA_VERSION
        and isinstance(capsule.get("operating"), dict)
    )


def emit_replay_capsule(plan: EmissionPlan, staging_dir: Path,
                        build_repo_root: Path) -> Path:
    """Emit `.wizard/replay-capsule.json` into `staging_dir`. Runs the fail-closed
    secret scan FIRST (before any write) over BOTH foundation_doc_inputs and the v2
    operating block; on a hit raises ReplayCapsuleError and writes nothing. Provenance
    is reused from `plan` (the same source the manifest uses), not re-derived.

    Returns the path written. Deterministic: sorted keys + trailing newline; no
    clock / no randomness."""
    doc = build_replay_capsule(plan, build_repo_root)
    scan_inputs_for_secrets(plan.foundation_doc_inputs, doc.get("operating"))  # fail-closed; raises before write
    dest = staging_dir / REPLAY_CAPSULE_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest
