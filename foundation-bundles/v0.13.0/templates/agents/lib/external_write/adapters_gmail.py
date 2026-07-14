"""Gmail verb-shaped adapter — the REFERENCE ADAPTER_PROFILE module.

The rest of this package builds a generalized external-write gate (verb-shaped Operations, a
per-op_kind Adapter registry, credential isolation via ReadFacade +
adapter-owned write-client provisioning, the zone-aware AST bypass scanner, the per-op_kind
effects manifest that binds a registered adapter's own bytes into the accepted-
write identity, and the acceptance ceremony). None of that had yet been proven
against a REAL vendor API shape — a verb-shaped surface (labels/filters), not
the seeded spreadsheet-style field write. This module is that proof: it
registers four Gmail op_kinds and is the ONLY module whose relative path is
listed in ``zones.ADAPTER_PROFILE_MODULE_PATHS`` (see zones.py) — the one
place a vendor SDK import, a write-capable credential, and a raw vendor
mutation are all legitimate.

Registered op_kinds (contracts declared in contracts.py):
  gmail.message.trash          -- add TRASH, remove INBOX (recoverable)
  gmail.message.untrash        -- restore a message's prior label set
  gmail.message.modify_labels  -- arbitrary label add/remove
  gmail.filter.create          -- create a Gmail filter rule (standing_automation)

Each op_kind's Adapter follows the SAME undo shape: apply mutates a message's
(or creates a filter's) live state; undo reverses it against the SAME
prestate the capability-side code already read via GmailReadFacade BEFORE
proposing the Operation (`plan()` below is a PURE repackaging of caller-
supplied params — it never reads or writes the surface itself, per the
Adapter protocol's ordering guarantee in adapter_registry.py). Every message
op_kind's undo descriptor declares its recovery obligation + the prestate it
requires (``prior_label_ids``); gmail.filter.create's undo obligation is
"delete the filter THIS adapter itself created" — tracked via the one piece
of adapter-instance state in this module (see GmailFilterCreateAdapter).

------------------------------------------------------------------------------
Structural safety — held by ABSENCE of code, not a runtime check
------------------------------------------------------------------------------
  * NO send / draft / forward path. This module never calls anything shaped
    like ``messages().send``, ``messages().insert`` (import-as-send),
    ``drafts().create``, or ``drafts().send`` — there is no code path here
    that could originate or forward a message. Verify by absence: grep this
    file for "send" or "draft" and find nothing but this sentence.
  * NO permanent delete. This module never calls Gmail's own
    ``messages().delete`` (a PERMANENT delete — distinct from ``trash``,
    which Gmail itself treats as recoverable for ~30 days) or
    ``messages().trash``/``messages().untrash`` either, for that matter:
    every message mutation here is a plain label delta via
    ``messages().modify`` (add TRASH / remove INBOX for trash; restore the
    prior label set for untrash and modify_labels' undo) — "trash" and
    "untrash" are two directions of the SAME label-delta primitive, not two
    different vendor verbs. ``gmail.filter.create``'s undo calls
    ``settings().filters().delete`` — deleting the FILTER RULE this adapter
    itself created, never a message and never user data.

------------------------------------------------------------------------------
Vendor import (proving the ADAPTER_PROFILE exemption is doing real work)
------------------------------------------------------------------------------
The ``TYPE_CHECKING``-guarded import below is a REAL ``from googleapiclient...
import ...`` statement — the AST bypass scanner (scan.py) does not evaluate
conditionals, so it would flag this as a forbidden_import violation in ANY
zone except ADAPTER_PROFILE (see test_external_write_adapters_gmail.py's
sibling "capability tried to import the client directly" negative control,
which reproduces exactly this import in a CAPABILITY-zone fixture and
confirms it IS flagged there). Guarding it with ``TYPE_CHECKING`` means it
never executes at runtime, so this module carries no hard dependency on
google-api-python-client being installed — every vendor call below is
duck-typed against ``raw_client: Any``, exactly like ``adapters.py``'s
``client.write(...)`` for the seeded field-write path.

Stdlib only at runtime; the vendor SDK's shape is duck-typed, never actually
imported outside the type-checking guard.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover - type-only; never executes at runtime.
    from googleapiclient.discovery import Resource  # noqa: F401

from external_write.adapter_registry import register_adapter
from external_write.operations import EffectUnit
from external_write.evidence import AdapterEvidence


# ---------------------------------------------------------------------------
# Op-kind identifiers (mirrors the op_kinds registered in contracts.py)
# ---------------------------------------------------------------------------
OP_TRASH = "gmail.message.trash"
OP_UNTRASH = "gmail.message.untrash"
OP_MODIFY_LABELS = "gmail.message.modify_labels"
OP_FILTER_CREATE = "gmail.filter.create"

TRASH_LABEL = "TRASH"
INBOX_LABEL = "INBOX"

# The short-form scope name every op_kind in this module declares as its
# contract's read_only_scope (contracts.py's _gmail_message_contract /
# _gmail_filter_create_contract — all four pass read_only_scope="gmail.readonly").
GMAIL_READONLY_SCOPE = "gmail.readonly"


# ---------------------------------------------------------------------------
# grant_preflight (Task 11, B3 / F-52,F-47 -- v0.13.0 Slice 2). SAFE, offline
# OAuth tokeninfo-class introspection, shared by all four op_kinds below
# (they all declare the SAME read_only_scope). See adapter_registry.py's
# Adapter protocol docstring for the full contract this fulfils: interprets
# an ALREADY-OBTAINED Google tokeninfo-shaped response
# (https://oauth2.googleapis.com/tokeninfo?access_token=... -- a SPACE-
# DELIMITED string of granted scopes under the "scope" key, e.g.
# {"scope": "https://www.googleapis.com/auth/gmail.readonly ..."}) -- never
# fetches that response itself, and never touches a real message or filter.
# Matches either the short form ("gmail.readonly") or the fully-qualified
# auth URL form (".../auth/gmail.readonly"), since providers are not
# consistent about which one a token-introspection response reports.
# ---------------------------------------------------------------------------

def _gmail_scope_granted(token_info: Any, declared_scope: str = GMAIL_READONLY_SCOPE) -> bool:
    if not isinstance(token_info, dict):
        return False
    granted_raw = token_info.get("scope", "")
    tokens = set(str(granted_raw or "").split())
    if declared_scope in tokens:
        return True
    return any(t.endswith(f"/auth/{declared_scope}") for t in tokens)


# ---------------------------------------------------------------------------
# Shared label-mutation helpers (DRY -- trash/untrash/modify_labels' apply_one
# and undo_one all reduce to "make this message's live label set equal some
# target set"; this is the ONE place that talks to raw_client to do it, so
# there is exactly one restoration algorithm, not three copies of it).
# ---------------------------------------------------------------------------

def _current_label_ids(raw_client: Any, message_id: str) -> List[str]:
    """A live read of message `message_id`'s CURRENT label set. Legitimate
    here (unlike in a Adapter.plan(), which must be pure — see
    adapter_registry.Adapter's protocol docstring): this runs inside
    apply_one/undo_one, against the WRITE-CAPABLE raw_client the
    credential-isolation seam hands this adapter, to compute the exact
    label delta a mutation needs. Never used by verify_one — see
    `_observed_label_ids` below, which reads through a READ-ONLY facade
    instead."""
    msg = raw_client.users().messages().get(
        userId="me", id=message_id, format="metadata").execute()
    return list(msg.get("labelIds", []))


def _observed_label_ids(observer: Any, message_id: str) -> List[str]:
    """verify_one's READ-ONLY observation of message `message_id`'s current
    label set (Task 3, A2 run-time — v0.12.0 Slice 1). `observer` is a
    `read_facades_gmail.GmailReadFacade` (or, in a unit test, a fixture
    exposing the same declared `read_methods`) — NEVER the write-capable
    raw_client `apply_one`/`undo_one` use above; the kernel
    (`adapters._run_adapter_operation`) builds it from a read-only-scoped
    client and hands it to verify_one, never the write client. `get_message`
    returns the SAME shape `_current_label_ids` reads off the write-capable
    client (`{"id": ..., "labelIds": [...]}`), so the rest of this module's
    label-diff logic is unchanged regardless of which client observed it."""
    msg = observer.get_message(message_id)
    return list((msg or {}).get("labelIds", []))


def _apply_label_delta(raw_client: Any, message_id: str,
                       add_label_ids: Sequence[str],
                       remove_label_ids: Sequence[str]) -> None:
    add = [l for l in add_label_ids if l]
    remove = [l for l in remove_label_ids if l]
    if not add and not remove:
        return
    raw_client.users().messages().modify(
        userId="me", id=message_id,
        body={"addLabelIds": add, "removeLabelIds": remove},
    ).execute()


def _set_exact_labels(raw_client: Any, message_id: str,
                      target_label_ids: Sequence[str]) -> None:
    """Mutate message `message_id`'s live label set to be EXACTLY
    `target_label_ids`: reads the current set, computes the minimal
    add/remove delta, and applies it. The one restoration algorithm shared
    by trash's undo, untrash's apply, and modify_labels' undo."""
    current = set(_current_label_ids(raw_client, message_id))
    target = set(target_label_ids)
    add = sorted(target - current)
    remove = sorted(current - target)
    _apply_label_delta(raw_client, message_id, add, remove)


def _trash_labels(raw_client: Any, message_id: str) -> None:
    """The one thing 'trash' means at the label level: add TRASH, remove
    INBOX. Shared by trash's apply and untrash's undo — trash/untrash are
    two directions of this SAME primitive, never Gmail's own
    messages().trash()/messages().delete() (see module docstring)."""
    _apply_label_delta(raw_client, message_id, [TRASH_LABEL], [INBOX_LABEL])


def _label_diff(observer: Any, message_id: str,
                prior_label_ids: Sequence[str]) -> Dict[str, Any]:
    """verify_one's prestate/label diff: the message's CURRENT live label
    set — read via the READ-ONLY `observer` (see `_observed_label_ids`
    above), never the write-capable client — plus whether it matches the
    trashed shape (TRASH present, INBOX absent) and/or the given prestate
    exactly. Generic enough to answer both "did apply land" and "did undo
    restore prestate" from one call."""
    current = _observed_label_ids(observer, message_id)
    current_set = set(current)
    prior_set = set(prior_label_ids)
    return {
        "message_id": message_id,
        "current_label_ids": sorted(current_set),
        "is_trashed": TRASH_LABEL in current_set and INBOX_LABEL not in current_set,
        "matches_prestate": current_set == prior_set,
    }


# ---------------------------------------------------------------------------
# gmail.message.trash
# ---------------------------------------------------------------------------

class GmailMessageTrashAdapter:
    """Adapter for gmail.message.trash.

    Undo descriptor: recovery obligation is "restore the message's prior
    label set" (add back INBOX plus whatever else was present before, remove
    TRASH); prestate requirement is `prior_label_ids` -- the message's FULL
    label set, read by the capability's GmailReadFacade BEFORE the Operation
    was proposed and carried in `params` (plan() below never reads the
    surface itself)."""

    UNDO_DESCRIPTOR = {
        "op_kind": OP_TRASH,
        "recovery": "restore_prior_label_set",
        "prestate_requirement": "prior_label_ids",
        "reverse_op_kind": OP_UNTRASH,
    }

    def plan(self, params: Optional[dict]) -> List[EffectUnit]:
        params = params or {}
        units: List[EffectUnit] = []
        for m in params.get("messages", []):
            message_id = m["message_id"]
            prior = tuple(m.get("prior_label_ids", ()))
            units.append(EffectUnit(
                unit_id=message_id,
                target_ref={"message_id": message_id},
                undo_ref={"message_id": message_id, "prior_label_ids": prior},
            ))
        return units

    def apply_one(self, raw_client: Any, unit: EffectUnit) -> None:
        _trash_labels(raw_client, unit.target_ref["message_id"])

    def undo_one(self, raw_client: Any, unit: EffectUnit) -> None:
        if unit.undo_ref is None:
            raise ValueError(f"{OP_TRASH}: unit {unit.unit_id!r} has no undo_ref")
        _set_exact_labels(raw_client, unit.undo_ref["message_id"],
                          unit.undo_ref["prior_label_ids"])

    def verify_one(self, observer: Any, unit: EffectUnit) -> Any:
        prior = unit.undo_ref["prior_label_ids"] if unit.undo_ref else ()
        return _label_diff(observer, unit.target_ref["message_id"], prior)

    # -----------------------------------------------------------------
    # Evidence predicates (Task 1, B4/T1 -- v0.12.0 Slice 1). Reads LABEL
    # STATE: `evidence.poststate` carries the SAME shape `verify_one`/
    # `_label_diff` already produces (`is_trashed`/`matches_prestate`) -- a
    # kernel task (Task 3, run-time) is expected to populate it from exactly
    # that call; a kernel task (Task 2, proof-time) is expected to populate
    # it from a captured evidence file recording the same observation made
    # during the copy-run. NEITHER predicate below re-reads the surface
    # itself or takes a path/ref argument -- see adapter_registry.py's
    # AdapterDispatch docstring for the anti-tautology property this relies
    # on.
    # -----------------------------------------------------------------

    def verify_apply_landed(self, evidence: AdapterEvidence) -> bool:
        """Apply landed iff the observed live label state shows the
        message actually trashed (TRASH present, INBOX absent) -- never
        merely that `apply_one` returned without raising."""
        return bool(evidence.poststate.get("is_trashed"))

    def verify_undo_restored(self, evidence: AdapterEvidence) -> bool:
        """Undo restored iff the observed live label state exactly matches
        the prestate (`prior_label_ids`) supplied when the evidence was
        captured."""
        return bool(evidence.poststate.get("matches_prestate"))

    def grant_preflight(self, token_info: Mapping[str, Any]) -> bool:
        """OPTIONAL, SAFE, offline scope grant-check (Task 11, B3/F-52,F-47)
        -- see `_gmail_scope_granted`'s docstring above; NEVER a destructive
        write, and never fetches `token_info` itself."""
        return _gmail_scope_granted(token_info)


# ---------------------------------------------------------------------------
# gmail.message.untrash
# ---------------------------------------------------------------------------

class GmailMessageUntrashAdapter:
    """Adapter for gmail.message.untrash -- addressable directly (not only as
    trash's undo path), for a capability that wants to restore a message on
    its own. Undo descriptor: recovery obligation is "re-trash the message"
    (the exact inverse of untrash); no prestate is required for the undo
    itself (re-trashing always means the same thing: add TRASH, remove
    INBOX)."""

    UNDO_DESCRIPTOR = {
        "op_kind": OP_UNTRASH,
        "recovery": "re_trash",
        "prestate_requirement": None,
        "reverse_op_kind": OP_TRASH,
    }

    def plan(self, params: Optional[dict]) -> List[EffectUnit]:
        params = params or {}
        units: List[EffectUnit] = []
        for m in params.get("messages", []):
            message_id = m["message_id"]
            prior = tuple(m.get("prior_label_ids", ()))
            units.append(EffectUnit(
                unit_id=message_id,
                target_ref={"message_id": message_id, "prior_label_ids": prior},
                undo_ref={"message_id": message_id},
            ))
        return units

    def apply_one(self, raw_client: Any, unit: EffectUnit) -> None:
        _set_exact_labels(raw_client, unit.target_ref["message_id"],
                          unit.target_ref.get("prior_label_ids", ()))

    def undo_one(self, raw_client: Any, unit: EffectUnit) -> None:
        if unit.undo_ref is None:
            raise ValueError(f"{OP_UNTRASH}: unit {unit.unit_id!r} has no undo_ref")
        _trash_labels(raw_client, unit.undo_ref["message_id"])

    def verify_one(self, observer: Any, unit: EffectUnit) -> Any:
        prior = unit.target_ref.get("prior_label_ids", ())
        return _label_diff(observer, unit.target_ref["message_id"], prior)

    def grant_preflight(self, token_info: Mapping[str, Any]) -> bool:
        """OPTIONAL, SAFE, offline scope grant-check (Task 11, B3/F-52,F-47)
        -- see `_gmail_scope_granted`'s docstring above; NEVER a destructive
        write, and never fetches `token_info` itself."""
        return _gmail_scope_granted(token_info)


# ---------------------------------------------------------------------------
# gmail.message.modify_labels
# ---------------------------------------------------------------------------

class GmailMessageModifyLabelsAdapter:
    """Adapter for gmail.message.modify_labels -- arbitrary label add/remove
    (e.g. applying a custom label, archiving by removing INBOX without
    trashing). Undo descriptor: recovery obligation is "restore the
    message's prior label set" -- the FULL prestate, not merely reversing
    the specific add/remove pair (a later concurrent edit could otherwise
    make a naive swap land on the wrong state; restoring the full prestate
    is exact regardless)."""

    UNDO_DESCRIPTOR = {
        "op_kind": OP_MODIFY_LABELS,
        "recovery": "restore_prior_label_set",
        "prestate_requirement": "prior_label_ids",
        "reverse_op_kind": OP_MODIFY_LABELS,
    }

    def plan(self, params: Optional[dict]) -> List[EffectUnit]:
        params = params or {}
        units: List[EffectUnit] = []
        for m in params.get("messages", []):
            message_id = m["message_id"]
            add = tuple(m.get("add_label_ids", ()))
            remove = tuple(m.get("remove_label_ids", ()))
            prior = tuple(m.get("prior_label_ids", ()))
            units.append(EffectUnit(
                unit_id=message_id,
                target_ref={"message_id": message_id, "add_label_ids": add,
                           "remove_label_ids": remove},
                undo_ref={"message_id": message_id, "prior_label_ids": prior},
            ))
        return units

    def apply_one(self, raw_client: Any, unit: EffectUnit) -> None:
        t = unit.target_ref
        _apply_label_delta(raw_client, t["message_id"], t["add_label_ids"],
                           t["remove_label_ids"])

    def undo_one(self, raw_client: Any, unit: EffectUnit) -> None:
        if unit.undo_ref is None:
            raise ValueError(f"{OP_MODIFY_LABELS}: unit {unit.unit_id!r} has no undo_ref")
        _set_exact_labels(raw_client, unit.undo_ref["message_id"],
                          unit.undo_ref["prior_label_ids"])

    def verify_one(self, observer: Any, unit: EffectUnit) -> Any:
        prior = unit.undo_ref["prior_label_ids"] if unit.undo_ref else ()
        return _label_diff(observer, unit.target_ref["message_id"], prior)

    def grant_preflight(self, token_info: Mapping[str, Any]) -> bool:
        """OPTIONAL, SAFE, offline scope grant-check (Task 11, B3/F-52,F-47)
        -- see `_gmail_scope_granted`'s docstring above; NEVER a destructive
        write, and never fetches `token_info` itself."""
        return _gmail_scope_granted(token_info)


# ---------------------------------------------------------------------------
# gmail.filter.create
# ---------------------------------------------------------------------------

class GmailFilterCreateAdapter:
    """Adapter for gmail.filter.create -- the one op_kind in this reference
    set with a PERSISTENT-BINDING risk shape (a created filter is a standing
    rule, not a one-shot edit; see contracts._gmail_filter_create_contract).

    Undo descriptor: recovery obligation is "delete the filter this adapter
    itself created" (never a message delete). Prestate requirement is None
    -- a filter does not exist before creation -- but the CREATED filter's
    id is a run-time fact this adapter must remember between apply_one and
    undo_one/verify_one. EffectUnit is an immutable, plan()-time-only record
    (plan() cannot predict a not-yet-created resource's id -- see
    adapter_registry.Adapter's protocol docstring), so this adapter INSTANCE
    holds that correlation itself, keyed by unit_id -- the one piece of
    adapter state anywhere in this module."""

    UNDO_DESCRIPTOR = {
        "op_kind": OP_FILTER_CREATE,
        "recovery": "delete_created_filter",
        "prestate_requirement": None,
        "reverse_op_kind": None,  # no native "un-create"; delete is the reverse.
    }

    def __init__(self) -> None:
        self._created_filter_ids: Dict[str, str] = {}

    def plan(self, params: Optional[dict]) -> List[EffectUnit]:
        params = params or {}
        units: List[EffectUnit] = []
        for i, f in enumerate(params.get("filters", [])):
            unit_id = f.get("client_ref") or f"filter-{i}"
            units.append(EffectUnit(
                unit_id=unit_id,
                target_ref={"criteria": f.get("criteria", {}),
                           "action": f.get("action", {})},
                undo_ref=None,
            ))
        return units

    def apply_one(self, raw_client: Any, unit: EffectUnit) -> None:
        body = {"criteria": unit.target_ref["criteria"],
                "action": unit.target_ref["action"]}
        result = raw_client.users().settings().filters().create(
            userId="me", body=body).execute()
        self._created_filter_ids[unit.unit_id] = result["id"]

    def undo_one(self, raw_client: Any, unit: EffectUnit) -> None:
        filter_id = self._created_filter_ids.get(unit.unit_id)
        if filter_id is None:
            raise ValueError(
                f"{OP_FILTER_CREATE}: no created filter id recorded for unit "
                f"{unit.unit_id!r} -- was apply_one ever called for it?")
        raw_client.users().settings().filters().delete(
            userId="me", id=filter_id).execute()
        del self._created_filter_ids[unit.unit_id]

    def verify_one(self, observer: Any, unit: EffectUnit) -> Any:
        """READ-ONLY observation via `observer` (a GmailReadFacade, or a
        fixture exposing the same read_methods) -- never the write-capable
        raw_client `apply_one`/`undo_one` use. `get_filter` is the facade's
        declared read method for this shape (see read_facades_gmail.py)."""
        filter_id = self._created_filter_ids.get(unit.unit_id)
        if filter_id is None:
            return {"unit_id": unit.unit_id, "exists": False, "filter_id": None}
        try:
            existing = observer.get_filter(filter_id)
        except Exception:
            return {"unit_id": unit.unit_id, "exists": False, "filter_id": filter_id}
        return {
            "unit_id": unit.unit_id,
            "exists": True,
            "filter_id": filter_id,
            "criteria": existing.get("criteria"),
            "action": existing.get("action"),
        }

    # -----------------------------------------------------------------
    # Evidence predicates (Task 1, B4/T1 -- v0.12.0 Slice 1; apply/undo
    # closed as a Task 2b follow-on -- see task-2-report.md Concern 1).
    # `evidence.poststate` carries the SAME shape `verify_one` above already
    # produces (`exists`/`filter_id`) for ALL THREE predicates below --
    # apply-landed, undo-restored, and durability all reduce to the same
    # observed fact ("does this filter id still resolve on the live
    # surface"), evaluated against evidence captured at three different
    # moments:
    #   * verify_apply_landed  -- evidence captured right after apply_one
    #     (raw_client.filters().create); a kernel task (Task 2's
    #     copy_run_proof.copy_apply_proof.apply_evidence / Task 3's
    #     run-time verify_one call) is expected to populate it from a
    #     fresh `get_filter` observation.
    #   * verify_undo_restored -- evidence captured right after undo_one
    #     (raw_client.filters().delete); populated the same way, but AFTER
    #     the delete -- "restored" for a create/delete pair means the
    #     filter is GONE again, the reverse of apply-landed's "exists".
    #   * verify_durability    -- evidence captured LATER, after ordinary
    #     operator actions (sort/filter/insert/delete/move) were performed
    #     on the copy (Task 2's copy_run_proof.durability_checks); same
    #     "does it still exist" question, at a later observation point.
    # gmail.filter.create is the one op_kind in this reference set whose
    # contract declares introduces_persistent_binding=True, which is why
    # `verify_durability` (optional on every other adapter here) is defined
    # here at all -- but a "verified" apply/undo claim needs the other two
    # regardless of the persistent-binding contract flag; see
    # copy_run_proof.py's fail-closed rule ("adapter declares no
    # evidence predicate" fails ANY registered-adapter op_kind, not only
    # binding ones).
    # -----------------------------------------------------------------

    def verify_apply_landed(self, evidence: AdapterEvidence) -> bool:
        """Apply landed iff the observed evidence shows the created filter
        resolvable on the live surface -- never merely that `apply_one`
        returned without raising."""
        return bool(evidence.poststate.get("exists"))

    def verify_undo_restored(self, evidence: AdapterEvidence) -> bool:
        """Undo restored iff the observed evidence shows the filter is NO
        LONGER resolvable -- the created filter was actually removed, the
        reverse of `verify_apply_landed` -- never merely that `undo_one`
        returned without raising."""
        return not bool(evidence.poststate.get("exists"))

    def verify_durability(self, evidence: AdapterEvidence) -> bool:
        """Durable iff the observed evidence shows the created filter still
        resolvable -- i.e. the persistent binding survived, not merely that
        `apply_one` once succeeded."""
        return bool(evidence.poststate.get("exists"))

    def grant_preflight(self, token_info: Mapping[str, Any]) -> bool:
        """OPTIONAL, SAFE, offline scope grant-check (Task 11, B3/F-52,F-47)
        -- see `_gmail_scope_granted`'s docstring above; NEVER a destructive
        write, and never fetches `token_info` itself. Note: this checks the
        READ-ONLY scope eligible for offline preflight; `gmail.filter.create`
        is itself a WRITE op_kind whose own exercise is the first bounded
        gated live apply (item 2's write-scope rule), never this preflight."""
        return _gmail_scope_granted(token_info)


# ---------------------------------------------------------------------------
# Registration -- module-scope, mirroring the real-adapter-module convention
# documented in adapter_registry.py (`a future adapter module calls
# register_adapter(op_kind, MyAdapter()) at module scope`).
# ---------------------------------------------------------------------------

register_adapter(OP_TRASH, GmailMessageTrashAdapter())
register_adapter(OP_UNTRASH, GmailMessageUntrashAdapter())
register_adapter(OP_MODIFY_LABELS, GmailMessageModifyLabelsAdapter())
register_adapter(OP_FILTER_CREATE, GmailFilterCreateAdapter())

# NOTE (kernel-registry generalization): the Gmail read-only facade used to
# be defined HERE, in this ADAPTER_PROFILE module -- which meant a
# capability that recovered `facade.__class__.__module__` landed on the SAME
# module that defines `build_write_client`-bearing adapters, an unnecessary
# (and exploitable) proximity between a read-only facade and write-capable
# adapter code. `GmailReadFacade` now lives in its
# own scanned module, `read_facades_gmail.py`, which imports only
# `ReadFacade` + `register_read_facade` from the kernel `read_facade` module
# -- no vendor SDK import, no adapter class, no credential/provisioner. See
# that module for the facade itself; it registers against the kernel
# `_READ_FACADE_REGISTRY` (read_facade.py) for this module's four op_kinds,
# and `read_facade.build_read_facade(op_kind, read_only_client)` resolves it
# from there -- this module no longer needs to be imported (or even exist,
# from the facade's point of view) for that resolution to work.
