"""Reference Gmail ReadFacade — split OUT of adapters_gmail.py (part of the
kernel ReadFacade registry generalization) so the reference facade lives in
its OWN scanned module, with no adapter class and no credential anywhere in
it.

------------------------------------------------------------------------------
Why this module exists (the hole it closes)
------------------------------------------------------------------------------
Previously, `GmailReadFacade` was defined inside `adapters_gmail.py` —
the ADAPTER_PROFILE module that ALSO defines every Gmail Adapter and would,
for a future self-provisioning adapter, define `build_write_client`. Design
review identified this as an architectural hole:
capability-zone code that recovered `facade.__class__.__module__` (or
imported the facade class directly, as the earlier emitted shape did)
landed on a module that ALSO holds write-capable adapter code — an
unnecessary, and exploitable, proximity between "read-only facade" and
"write-capable adapter" in the SAME file. A capability importing
`GmailReadFacade` from `adapters_gmail` had no reason to need anything else
that module exports, but the import surface made everything in that module
reachable by name regardless.

The fix: capability code no longer imports a facade class from an adapter
module at all. It calls `read_facade.build_read_facade(op_kind,
read_only_client)` (re-exported, capability-facing, via `capability_api.py`)
and the KERNEL resolves the concrete subclass from its own registry
(`read_facade._READ_FACADE_REGISTRY`, populated by `register_read_facade` —
see read_facade.py). This module is what populates that registry for the
four Gmail op_kinds, and it does so from a module that contains NOTHING but
the facade itself:

  * Imports ONLY `ReadFacade` + `register_read_facade` from `read_facade`
    (the SEALED_KERNEL module) — no vendor SDK import (no
    `googleapiclient`, not even TYPE_CHECKING-guarded), no Adapter class, no
    `build_write_client`, no credential/provisioner of any kind.
  * Duplicates the four Gmail op_kind string literals locally rather than
    importing them from `adapters_gmail.py` — importing anything from that
    module, even a harmless string constant, would re-create exactly the
    coupling this split exists to remove. The op_kind strings themselves are
    plain data (also declared independently in contracts.py), not a
    structural dependency.

This module is NOT listed in `zones.ADAPTER_PROFILE_MODULE_PATHS` (nor
`zones.SEALED_KERNEL_MODULE_PATHS`) — leaving it unlisted defaults it to the
fail-closed CAPABILITY classification (see zones.py's module docstring: an
unclassified module is always the MOST restrictive zone, never a silent
exemption). That is deliberately fine here: this module contains nothing
that trips `scan.py`'s CAPABILITY-zone checks (no forbidden import, no
direct vendor mutation call, no credential construction, no
credential-provider symbol reference) — see
test_external_write_adapters_gmail.py's
`test_read_facades_gmail_scans_clean`.

The whole point, restated: a capability that recovers
`facade.__class__.__module__` for a Gmail read facade now gets THIS
module — which has no adapter and no credential in it, and never will,
because it structurally cannot import one without violating its own
"imports only ReadFacade + register_read_facade" invariant — not
`adapters_gmail.py`.

Stdlib only — no third-party dependencies.
"""

from typing import Any, Optional

from external_write.read_facade import ReadFacade, register_read_facade

# ---------------------------------------------------------------------------
# Op-kind identifiers -- deliberately DUPLICATED from adapters_gmail.py's own
# OP_TRASH/OP_UNTRASH/OP_MODIFY_LABELS/OP_FILTER_CREATE constants (and from
# contracts.py's inline literals), not imported from either -- see the module
# docstring's "why this module exists" section for why importing from the
# adapter module at all would defeat the split.
# ---------------------------------------------------------------------------
OP_TRASH = "gmail.message.trash"
OP_UNTRASH = "gmail.message.untrash"
OP_MODIFY_LABELS = "gmail.message.modify_labels"
OP_FILTER_CREATE = "gmail.filter.create"


class GmailReadFacade(ReadFacade):
    """Read-only Gmail facade -- built via
    ``read_facade.build_read_facade(op_kind, read_only_client)`` (the
    capability-facing two-arg form; the kernel resolves THIS class from its
    registry) against a client scoped to gmail.readonly (see contracts.py's
    gmail op_kinds' declared ``read_only_scope``).

    Like every ReadFacade subclass, it MUST NOT re-stash the wrapped client
    as an attribute of its own: it declares read_methods only and every
    method dispatches via ``self._read``, so there is no additional
    attribute for the base class's runtime allowlist to police -- a
    subclass that stored the client under its own attribute would be
    refused at class-definition time (``ReadFacade.__init_subclass__``)
    before this module could even import.
    """

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


# ---------------------------------------------------------------------------
# Registration -- module-scope, mirroring adapter_registry.py's own
# convention (`register_adapter(op_kind, MyAdapter())` at module scope): all
# four Gmail op_kinds share ONE read-only shape (list/get messages, labels,
# filters), so one facade class registers against all four.
# ---------------------------------------------------------------------------
for _op_kind in (OP_TRASH, OP_UNTRASH, OP_MODIFY_LABELS, OP_FILTER_CREATE):
    register_read_facade(_op_kind, GmailReadFacade)
