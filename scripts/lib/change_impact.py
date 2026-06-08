"""Change-propagation & consistency engine for living foundation documents.

A build-time engine over the event-sourced derivation substrate. It computes an impact
TOPOLOGY ON THE FLY over the transcript + manifests (NOT a stored graph), so it can:
  - surface the implications of a change (downstream walk),
  - trace a downstream problem back to its source (inverted-edge walk),
  - and re-propagate a correction.

DISCIPLINE (anti-overfit): structural metadata ONLY, never prose meaning. Every edge
comes from a GENERIC substrate source (never a per-scenario hand-coding):
  answer -> field   from FieldSpec.source_question_ids   (static, manifest)
  field  -> field   from the `_audit` `_derivation_inputs` (runtime overlay, DR-8-proven)
  field  -> doc     from FieldSpec.preview_doc            (static, manifest)
The field -> emitted-behavior-code edge is DEFERRED at v0 (un-defer triggers T1/T2/T3);
the v0 graph carries fields + docs only.

v0 SCOPE = the decision/document boundary. KNOWN BOUNDARY (stated, not closed at v0):
inconsistency is caught along recorded dependency edges (incl. shared-ancestor), NOT
between two decisions that share no derivation link; the engine does NOT judge semantic
correctness (that remains the operator's review).

Stdlib-only, pip-install-free.
"""

from collections import deque
from typing import Any, Dict, List, NamedTuple, Optional, Set

from field_manifest import FieldManifest
# Reuse the substrate's canonical hashing + its definition of a "meaningful" envelope change
# (single source of truth). These are read-only; the existing stale-confirmation path in
# derivation_replay stays untouched.
from derivation_replay import (
    content_hash,
    _ENVELOPE_DRIFT_KEYS,
    _PROTOCOL_KEYS,
    _LIST_ENVELOPE_KEYS,
)

# The envelope keys that constitute a behavior-bearing change for fingerprint purposes —
# exactly the substrate's drift/protocol/list keys. Volatile bookkeeping (`_confirmed_at`,
# `_confirmed_with_adjustments`) is intentionally EXCLUDED so a no-op re-confirmation is not
# a false "changed."
_FINGERPRINT_ENVELOPE_KEYS = tuple(_ENVELOPE_DRIFT_KEYS) + tuple(_PROTOCOL_KEYS) + tuple(_LIST_ENVELOPE_KEYS)


# --- impact classes (v0 = the decision/document boundary) --------------------
# behavior-code is the DEFERRED edge (field -> emitted-behavior-code; un-defer triggers
# T1/T2/T3); it is intentionally NOT a value here. When un-deferred it joins this enum as
# the strongest class (behavior-code > rule-decision > content-only).
CONTENT_ONLY = "content-only"
RULE_DECISION = "rule-decision"


# --- determinism kind (a separate axis from derivation_class) ----------------
# Only pure_code may be silently auto-halted. recorded_replay_only is deterministic ONLY
# because it replays recorded events (not produced by candidate-space re-derivation, so it
# is reserved, not emitted by determinism_kind_for at v0). model_unstable covers every
# model-derived class: re-derivation is non-idempotent, so its fingerprint is unreliable and
# the node always surfaces for operator disposition.
PURE_CODE = "pure_code"
RECORDED_REPLAY_ONLY = "recorded_replay_only"
MODEL_UNSTABLE = "model_unstable"

_PURE_CODE_CLASSES = {"auto"}


def determinism_kind_for(derivation_class: str) -> str:
    """Map a field's derivation_class to its determinism_kind (conservative at v0).

    `auto` (code-computed globals) -> pure_code; every model class -> model_unstable.
    The conservative default means almost nothing auto-halts -> over-surface, never
    under-surface (the safe direction for a non-technical operator)."""
    return PURE_CODE if derivation_class in _PURE_CODE_CLASSES else MODEL_UNSTABLE


def may_auto_halt(determinism_kind: str) -> bool:
    """A node may be silently auto-halted (skipping the operator) iff it is pure_code."""
    return determinism_kind == PURE_CODE


# --- node fingerprints (kind-specific; not content_hash(text) alone) ----------

def field_fingerprint(value: Any, envelope: Dict[str, Any]) -> str:
    """Fingerprint a field node: value + behavior-bearing envelope metadata.

    A behavior change can travel through metadata (`_decision_kind`, `_source`,
    `_derivation_class`, `_confirmation_state`, derivation inputs/sources, protocol version)
    while the rendered text is identical, so the value alone is insufficient. Volatile
    bookkeeping (`_confirmed_at`) is excluded so a no-op re-confirmation is not a false change.
    """
    meaningful = {k: envelope.get(k) for k in _FINGERPRINT_ENVELOPE_KEYS if k in envelope}
    return content_hash({"value": value, "envelope": meaningful})


def doc_fingerprint(doc_id: str, rendered: str) -> str:
    """Fingerprint a foundation-doc node: the rendered document hash + its id."""
    return content_hash({"doc_id": doc_id, "rendered": rendered})


def classify(envelope: Dict[str, Any]) -> str:
    """Structurally classify a field by its `_audit` envelope (never prose meaning).

    rule-decision iff `_decision_field` is True; otherwise content-only. Reads metadata
    only (`_decision_field`), consistent with the contract coupling
    decision_field == (decision_kind != 'none'). A malformed envelope is caught upstream
    by the derived-record validator, not here.
    """
    return RULE_DECISION if envelope.get("_decision_field") is True else CONTENT_ONLY


class Node(NamedTuple):
    """A node in the impact topology, identified by kind + id.

    kind in {"answer", "field", "doc"} at v0 (artifact/artifact_slot deferred with the
    field->code edge). id is the question-ID / field-name / preview-doc filename.
    """
    kind: str
    id: str


class ImpactGraph:
    """A directed graph over Nodes with O(1) forward + inverted adjacency.

    Edges flow downstream (cause -> effect): answer -> field -> {field, doc}. The inverted
    adjacency (`predecessors`) backs the bidirectional source-trace (`sources`).
    """

    def __init__(self) -> None:
        self._succ: Dict[Node, Set[Node]] = {}
        self._pred: Dict[Node, Set[Node]] = {}

    def add_node(self, node: Node) -> None:
        self._succ.setdefault(node, set())
        self._pred.setdefault(node, set())

    def add_edge(self, src: Node, dst: Node) -> None:
        self.add_node(src)
        self.add_node(dst)
        self._succ[src].add(dst)
        self._pred[dst].add(src)

    def successors(self, node: Node) -> Set[Node]:
        return set(self._succ.get(node, set()))

    def predecessors(self, node: Node) -> Set[Node]:
        return set(self._pred.get(node, set()))


def build_graph(manifest: FieldManifest,
                audit: Optional[Dict[str, Dict[str, Any]]] = None) -> ImpactGraph:
    """Build the impact topology: static skeleton + optional runtime overlay.

    Skeleton (scenario-independent; same for every operator; derived from the manifest):
      answer -> field  (one per source_question_ids entry)
      field  -> doc    (when preview_doc is non-empty)

    Overlay (the operator's actual derivation; read GENERICALLY from a compiled record's
    `_audit` map of field -> envelope):
      field -> field   (one per `_derivation_inputs` entry: input field FED derived field)

    The same code reads every edge; there is no per-scenario branch anywhere. DR-8
    guarantees each `_derivation_inputs` entry resolves to a real payload field.
    """
    graph = ImpactGraph()
    for spec in manifest.fields.values():
        field_node = Node("field", spec.field)
        graph.add_node(field_node)
        for question_id in spec.source_question_ids:
            graph.add_edge(Node("answer", question_id), field_node)
        if spec.preview_doc:
            graph.add_edge(field_node, Node("doc", spec.preview_doc))

    if audit:
        for derived_field, envelope in audit.items():
            derived_node = Node("field", derived_field)
            graph.add_node(derived_node)
            for input_field in envelope.get("_derivation_inputs", []):
                graph.add_edge(Node("field", input_field), derived_node)

    return graph


# --- cascade (full closure computed in side-effect-free candidate space) ------
# A reached node's cascade status:
AUTO_HALTED = "auto_halted"            # pure_code, re-derived, fingerprint unchanged -> pruned
CHANGED = "changed"                    # pure_code, re-derived, fingerprint changed
REQUIRES_DISPOSITION = "requires_disposition"  # surfaces for the operator (model_unstable, docs)


class ImpactNode(NamedTuple):
    node: Node
    impact_class: Optional[str]       # content-only | rule-decision (None for docs handled as content)
    determinism_kind: Optional[str]   # for field nodes; None for docs
    status: str


class CascadeResult(NamedTuple):
    surfaced: List[ImpactNode]        # what the operator sees (the "inbox of required updates")
    auto_halted: List[Node]           # pure_code nodes pruned (fingerprint unchanged); for the receipt


def cascade(graph: ImpactGraph, changed_node: Node, record: Dict[str, Any],
            rederive=None, candidate_values: Optional[Dict[str, Any]] = None) -> CascadeResult:
    """Compute the full reachable downstream closure of a change, in candidate space.

    Computation is decoupled from commitment — `record` is NOT mutated; the whole blast
    radius is computed so a batched "impact transaction" can be presented before any
    sign-off.

    Per-reached-field decision:
      - pure_code with ALL field-inputs known (in `candidate_values`, grown as pure_code nodes
        re-derive) -> re-derive via `rederive(field, known_values)`, compare fingerprints:
        unchanged -> AUTO_HALTED (pruned, does not propagate); changed -> CHANGED (propagates).
      - otherwise (model_unstable, or a pure_code node with an undetermined input) ->
        REQUIRES_DISPOSITION (surfaces; propagates conservatively — over-surface, never under).

    `candidate_values` seeds the known-new-values of the directly-changed node(s). `rederive`
    is injected (the lib stays pure); it returns (new_value, new_envelope) for a field.
    """
    audit = record.get("_audit", {})
    known_values: Dict[str, Any] = dict(candidate_values or {})
    surfaced: List[ImpactNode] = []
    auto_halted: List[Node] = []
    seen: Set[Node] = {changed_node}
    frontier = deque([changed_node])

    while frontier:
        node = frontier.popleft()
        for succ in sorted(graph.successors(node)):
            if succ in seen:
                continue
            seen.add(succ)

            if succ.kind == "doc":
                # A doc re-renders from its (possibly changed) inputs; the operator reviews
                # the rendered preview. Docs are leaves (no downstream).
                surfaced.append(ImpactNode(succ, CONTENT_ONLY, None, REQUIRES_DISPOSITION))
                continue
            if succ.kind != "field":
                continue

            env = audit.get(succ.id, {})
            determinism = determinism_kind_for(env.get("_derivation_class", ""))
            impact_class = classify(env)
            field_inputs = [p.id for p in graph.predecessors(succ) if p.kind == "field"]
            inputs_known = all(fi in known_values for fi in field_inputs)

            if may_auto_halt(determinism) and rederive is not None and inputs_known:
                new_value, new_envelope = rederive(succ.id, dict(known_values))
                old_fp = field_fingerprint(record.get(succ.id), env)
                new_fp = field_fingerprint(new_value, new_envelope)
                if new_fp == old_fp:
                    auto_halted.append(succ)
                    continue  # pruned: stable branch does not propagate
                known_values[succ.id] = new_value
                surfaced.append(ImpactNode(succ, impact_class, determinism, CHANGED))
            else:
                surfaced.append(ImpactNode(succ, impact_class, determinism, REQUIRES_DISPOSITION))

            frontier.append(succ)

    return CascadeResult(surfaced=surfaced, auto_halted=auto_halted)


def sources(graph: ImpactGraph, point_of_notice: Node) -> List[Node]:
    """Bidirectional inverted-edge trace: from a point-of-notice, enumerate the transitive
    upstream contributors (intermediate fields + originating answers), ranked nearest-first.

    The primary structural ranking signal is shortest path (a direct input outranks a
    transitively-reached one); ties break deterministically by (kind, id). Richer signals
    (recency / group / fanout) and the plain-language rendering with current values are the
    operator-surface layer, not this pure trace. The point-of-notice itself is excluded.
    """
    distance: Dict[Node, int] = {}
    queue = deque([(point_of_notice, 0)])
    seen: Set[Node] = {point_of_notice}
    while queue:
        node, dist = queue.popleft()
        for predecessor in graph.predecessors(node):
            if predecessor not in seen:
                seen.add(predecessor)
                distance[predecessor] = dist + 1
                queue.append((predecessor, dist + 1))
    return sorted(distance, key=lambda n: (distance[n], n.kind, n.id))
