"""Gmail verb-shaped adapter — the REFERENCE ADAPTER_PROFILE module (Task 7 —
external-write-gate-generalization slice).

Tasks 1-6 built a generalized external-write gate (verb-shaped Operations, a
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

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover - type-only; never executes at runtime.
    from googleapiclient.discovery import Resource  # noqa: F401

from external_write.adapter_registry import register_adapter
from external_write.operations import EffectUnit
from external_write.read_facade import ReadFacade


# ---------------------------------------------------------------------------
# Op-kind identifiers (mirrors the op_kinds registered in contracts.py)
# ---------------------------------------------------------------------------
OP_TRASH = "gmail.message.trash"
OP_UNTRASH = "gmail.message.untrash"
OP_MODIFY_LABELS = "gmail.message.modify_labels"
OP_FILTER_CREATE = "gmail.filter.create"

TRASH_LABEL = "TRASH"
INBOX_LABEL = "INBOX"


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
    apply_one/undo_one/verify_one, against the write-capable raw_client the
    credential-isolation seam (Task 4) hands this adapter, never against
    capability-side code's ReadFacade."""
    msg = raw_client.users().messages().get(
        userId="me", id=message_id, format="metadata").execute()
    return list(msg.get("labelIds", []))


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


def _label_diff(raw_client: Any, message_id: str,
                prior_label_ids: Sequence[str]) -> Dict[str, Any]:
    """verify_one's prestate/label diff: the message's CURRENT live label
    set, plus whether it matches the trashed shape (TRASH present, INBOX
    absent) and/or the given prestate exactly. Generic enough to answer
    both "did apply land" and "did undo restore prestate" from one call."""
    current = _current_label_ids(raw_client, message_id)
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

    def verify_one(self, raw_client: Any, unit: EffectUnit) -> Any:
        prior = unit.undo_ref["prior_label_ids"] if unit.undo_ref else ()
        return _label_diff(raw_client, unit.target_ref["message_id"], prior)


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

    def verify_one(self, raw_client: Any, unit: EffectUnit) -> Any:
        prior = unit.target_ref.get("prior_label_ids", ())
        return _label_diff(raw_client, unit.target_ref["message_id"], prior)


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

    def verify_one(self, raw_client: Any, unit: EffectUnit) -> Any:
        prior = unit.undo_ref["prior_label_ids"] if unit.undo_ref else ()
        return _label_diff(raw_client, unit.target_ref["message_id"], prior)


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

    def verify_one(self, raw_client: Any, unit: EffectUnit) -> Any:
        filter_id = self._created_filter_ids.get(unit.unit_id)
        if filter_id is None:
            return {"unit_id": unit.unit_id, "exists": False, "filter_id": None}
        try:
            existing = raw_client.users().settings().filters().get(
                userId="me", id=filter_id).execute()
        except Exception:
            return {"unit_id": unit.unit_id, "exists": False, "filter_id": filter_id}
        return {
            "unit_id": unit.unit_id,
            "exists": True,
            "filter_id": filter_id,
            "criteria": existing.get("criteria"),
            "action": existing.get("action"),
        }


# ---------------------------------------------------------------------------
# Registration -- module-scope, mirroring the real-adapter-module convention
# documented in adapter_registry.py (`a future adapter module calls
# register_adapter(op_kind, MyAdapter()) at module scope`).
# ---------------------------------------------------------------------------

register_adapter(OP_TRASH, GmailMessageTrashAdapter())
register_adapter(OP_UNTRASH, GmailMessageUntrashAdapter())
register_adapter(OP_MODIFY_LABELS, GmailMessageModifyLabelsAdapter())
register_adapter(OP_FILTER_CREATE, GmailFilterCreateAdapter())


# ---------------------------------------------------------------------------
# Gmail read-only facade (Task 4/T7 boundary closed): declares ONLY
# read/list/search methods, backed by a gmail.readonly-scoped client.
# Capability/proposal-side code reads through this, never the write-capable
# client -- see read_facade.py's module docstring for the credential-
# isolation guarantee this relies on. Like every ReadFacade subclass, it MUST
# NOT re-stash the wrapped client as an attribute of its own: this subclass
# declares read_methods only and every method dispatches via `self._read`,
# so there is no additional attribute for the base class's runtime allowlist
# to police -- a subclass that stored the client under its own attribute
# would be refused at class-definition time (ReadFacade.__init_subclass__)
# before this module could even import.
# ---------------------------------------------------------------------------

class GmailReadFacade(ReadFacade):
    """Read-only Gmail facade -- built via
    ``read_facade.build_read_facade(op_kind, read_only_client, GmailReadFacade)``
    against a client scoped to gmail.readonly (see contracts.py's gmail
    op_kinds' declared ``read_only_scope``)."""

    read_methods = (
        "list_messages", "get_message", "list_labels", "list_filters",
        "get_filter",
    )

    def list_messages(self, query: Optional[str] = None,
                      max_results: Optional[int] = None) -> Any:
        return self._read("list_messages", query=query, max_results=max_results)

    def get_message(self, message_id: str) -> Any:
        return self._read("get_message", message_id)

    def list_labels(self) -> Any:
        return self._read("list_labels")

    def list_filters(self) -> Any:
        return self._read("list_filters")

    def get_filter(self, filter_id: str) -> Any:
        return self._read("get_filter", filter_id)
