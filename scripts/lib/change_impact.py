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


# Engine version — part of the receipt fingerprint, so an approval recorded under an older
# engine cannot silently unblock emit after the engine changes.
ENGINE_VERSION = "change-impact-v0"


# --- impact classes (v0 = the decision/document boundary) --------------------
# behavior-code is the DEFERRED edge (field -> emitted-behavior-code; un-defer triggers
# T1/T2/T3); it is intentionally NOT a value here. When un-deferred it joins this enum as
# the strongest class (behavior-code > rule-decision > content-only).
CONTENT_ONLY = "content-only"
RULE_DECISION = "rule-decision"

# Enforcement tier: which impact classes BLOCK emit when left un-dispositioned. content-only
# is guided (operator may proceed); rule-decision blocks (a generated-system-invariant
# boundary). behavior-code will join the blocking set when un-deferred.
_BLOCKING_CLASSES = {RULE_DECISION}

# --- operator dispositions (the batched "impact transaction") ----------------
# apply = accept the re-derived change; revise = operator edits it; defer = decide later
# (does NOT clear the pending gate); intentional_divergence = a durable, recorded fork
# (upstream and downstream deliberately disagree); freeze = pin this branch, stop propagating.
APPLY = "apply"
REVISE = "revise"
DEFER = "defer"
INTENTIONAL_DIVERGENCE = "intentional_divergence"
FREEZE = "freeze"
# Dispositions that RESOLVE a pending implication (clear it from the emit gate). `defer`
# deliberately does NOT resolve — a deferred rule/decision implication keeps emit blocked.
_RESOLVING_DISPOSITIONS = {APPLY, REVISE, INTENTIONAL_DIVERGENCE, FREEZE}
# The choices offered for every surfaced impact in the batched transaction (operator surface).
DISPOSITION_OPTIONS = (APPLY, REVISE, DEFER, INTENTIONAL_DIVERGENCE, FREEZE)


# --- determinism kind (a separate axis from derivation_class) ----------------
# Only pure_code may be silently auto-halted. recorded_replay_only is deterministic ONLY
# because it replays recorded events (not produced by candidate-space re-derivation, so it
# is reserved, not emitted by determinism_kind_for at v0). model_unstable covers every
# model-derived class: re-derivation is non-idempotent, so its fingerprint is unreliable and
# the node always surfaces for operator disposition.
PURE_CODE = "pure_code"
RECORDED_REPLAY_ONLY = "recorded_replay_only"
MODEL_UNSTABLE = "model_unstable"

# `auto` (code-computed globals) and `projection` (a deterministic role-filter/reshape of prior
# payload fields — pure code over confirmed inputs, never model authoring) are the pure_code
# classes that may auto-halt. Every model-derived class stays model_unstable.
_PURE_CODE_CLASSES = {"auto", "projection"}


def determinism_kind_for(derivation_class: str) -> str:
    """Map a field's derivation_class to its determinism_kind (conservative at v0).

    `auto` (code-computed globals) + `projection` (deterministic filter/reshape of prior fields)
    -> pure_code; every model class -> model_unstable. The conservative default means almost
    nothing auto-halts -> over-surface, never under-surface (the safe direction for a
    non-technical operator). pure_code lets an unchanged projected role-subset auto-halt instead
    of re-surfacing on every unrelated narrative edit to the canonical record (no alert fatigue)."""
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


# --- receipt + enforcement primitives ----------------------------------------

def _node_str(node: Node) -> str:
    """Stable string id for a node ("kind:id") — used as a dict key in receipts/indexes."""
    return "{}:{}".format(node.kind, node.id)


def impact_set_hash(impacts: List[ImpactNode]) -> str:
    """A stable, order-independent hash of the SET of surfaced impacts (node + class + status).

    Part of the receipt fingerprint: it changes when the surfaced impact set changes, so a
    disposition recorded against one impact set cannot unblock emit for a different one.
    """
    canonical = sorted([n.node.kind, n.node.id, n.impact_class or "", n.status] for n in impacts)
    return content_hash(canonical)


def make_receipt(change_detected_on: Node, graph_version: str, source_hash: str,
                 impacts: List[ImpactNode], dispositions: Dict[Node, str],
                 recorded_at: str) -> Dict[str, Any]:
    """Build a durable, machine-readable disposition receipt (anti-fiction).

    Fingerprinted by graph_version + source_hash + engine_version + impact_set_hash so a stale
    approval cannot unblock emit after the graph, the source answers, or the engine changed.
    """
    return {
        "change_detected_on": _node_str(change_detected_on),
        "recorded_at": recorded_at,
        "fingerprint": {
            "graph_version": graph_version,
            "source_hash": source_hash,
            "engine_version": ENGINE_VERSION,
            "impact_set_hash": impact_set_hash(impacts),
        },
        "implicated": {_node_str(i.node): i.impact_class for i in impacts},
        "dispositions": {_node_str(n): d for n, d in dispositions.items()},
    }


def pending_dispositions(impacts: List[ImpactNode],
                         dispositions: Dict[Node, str]) -> List[ImpactNode]:
    """Project the index of BLOCKING implications still awaiting a resolving disposition.

    Only blocking-class impacts (rule-decision; behavior-code when un-deferred) can block
    emit; content-only is guided and never pending. An impact is resolved only by a resolving
    disposition (apply / revise / intentional_divergence / freeze) — `defer` and a missing
    disposition both leave it pending. The emit gate checks this list is empty.
    """
    return [i for i in impacts
            if i.impact_class in _BLOCKING_CLASSES
            and dispositions.get(i.node) not in _RESOLVING_DISPOSITIONS]


def emit_blocked_by_pending(pending: List[ImpactNode]) -> bool:
    """The fail-closed emit predicate: emit is blocked iff any blocking implication is pending."""
    return len(pending) > 0


def pending_from_events(events: List[Dict[str, Any]]) -> List[ImpactNode]:
    """Project the emit-gate pending index from the recorded transcript events.

    Reads `impact_change` events (a detected change + its surfaced impacts, keyed by
    `change_id` = the impact fingerprint) and `impact_disposition` events (the operator's
    disposition, keyed by the SAME change_id). A blocking implication is pending unless a
    resolving disposition was recorded for its own change_id — so a NEW upstream change
    (new change_id) is never accidentally cleared by an OLD change's disposition.
    """
    pending: List[ImpactNode] = []
    for ch in [e for e in events if e.get("event_type") == "impact_change"]:
        change_id = ch.get("change_id")
        impacts = [ImpactNode(Node(i["node_kind"], i["node_id"]), i.get("impact_class"),
                              None, i.get("status"))
                   for i in ch.get("impacts", [])]
        dispositions = {
            Node(e["node_kind"], e["node_id"]): e["disposition"]
            for e in events
            if e.get("event_type") == "impact_disposition" and e.get("change_id") == change_id
        }
        pending.extend(pending_dispositions(impacts, dispositions))
    return pending


def is_fresh(node: Node, pending: List[ImpactNode]) -> bool:
    """Freshness as a validation input usable at EVERY boundary (group close, use as a
    derivation input, dependent preview render, emit): a node is fresh iff it carries no
    pending blocking implication."""
    return node not in {p.node for p in pending}


def tombstone_marker_line(confirmation_marker: str, reason: str, recorded_at: str) -> str:
    """Produce a progress-file line that TOMBSTONES a group's confirmation marker.

    The line drops the stored source_hash, so the substrate's group_confirmation_is_stale
    fires automatically (fail-closed on a missing hash) — no change to that ratified module.
    Appended after the original `complete` line, it overwrites the marker (last occurrence
    wins on parse). `reason` must not contain '|' (the marker field separator); pipes are
    replaced with '/' defensively.
    """
    safe_reason = reason.replace("|", "/")
    return "{}: tombstoned | reason={} | {}".format(confirmation_marker, safe_reason, recorded_at)


# --- operator surface (the batched "impact transaction") ---------------------

def build_impact_transaction(surfaced: List[ImpactNode],
                             sources: Optional[List[Node]] = None,
                             labels: Optional[Dict[Node, str]] = None) -> Dict[str, Any]:
    """Build the structured batched "impact transaction" the operator reviews and signs off.

    Groups the surfaced impacts by class (so the operator sees "this touches N wording changes
    and M rules your system follows" rather than a raw dependency dump), gives each item an
    operator-facing label (falling back to the field key only when no label is provided) and
    the full disposition option set, and carries the bidirectional `sources` trace. The exact
    per-item prose ("how it would change") is filled by the carrier at runtime; this builder
    fixes the STRUCTURE so the surface is consistent and the gate's contract is honoured.
    """
    labels = labels or {}
    summary: Dict[str, int] = {CONTENT_ONLY: 0, RULE_DECISION: 0}
    items: List[Dict[str, Any]] = []
    for imp in surfaced:
        cls = imp.impact_class or CONTENT_ONLY
        summary[cls] = summary.get(cls, 0) + 1
        items.append({
            "node": imp.node,
            "ref": _node_str(imp.node),
            "label": labels.get(imp.node, imp.node.id),
            "impact_class": cls,
            "status": imp.status,
            "options": list(DISPOSITION_OPTIONS),
        })
    return {"summary": summary, "items": items, "sources": list(sources or [])}


def render_impact_transaction_md(transaction: Dict[str, Any]) -> str:
    """Render the structured transaction to operator-facing markdown for the reviewable file.

    A thin, deterministic template — the carrier may enrich each item's "how it would change"
    prose, but the structure (summary, per-item choices, contributing answers) is fixed here.
    """
    s = transaction["summary"]
    lines: List[str] = ["# Changes that need your decision", ""]
    lines.append("This change touches **{} wording item(s)** and **{} rule(s) your system "
                 "follows**. For each item below, choose what to do.".format(
                     s.get(CONTENT_ONLY, 0), s.get(RULE_DECISION, 0)))
    lines.append("")
    for item in transaction["items"]:
        kind = "rule your system follows" if item["impact_class"] == RULE_DECISION else "wording"
        lines.append("## {}".format(item["label"]))
        lines.append("- Type: {} (`{}`)".format(kind, item["ref"]))
        lines.append("- Your choices: {}".format(", ".join(item["options"])))
        lines.append("")
    if transaction.get("sources"):
        lines.append("## Where this came from")
        lines.append("This was generated from your earlier answers — review them if the change "
                     "looks wrong at the source:")
        for src in transaction["sources"]:
            lines.append("- `{}`".format(_node_str(src)))
        lines.append("")
    return "\n".join(lines)


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
