"""Bypass: calls the Gmail mutation API directly instead of routing through
the named-operation adapter (NF1 — external-write-gate-generalization
fix-wave, Task R2). Mirrors direct_api_call.py's Sheets fixture, but for
Gmail's verb shape (``service.users().messages()...``/``...drafts()...``/
``...settings().filters()...``).

Gmail's ambiguous verbs (create/delete/send/modify) collide with common
method names, so they are gated on a Gmail surface handle appearing in the
attribute chain (messages/drafts/threads/labels/filters/settings/users) —
the same ambiguous-vs-unambiguous discipline
``_check_surface_mutation`` already applies to the Sheets verbs. ``trash``/
``untrash`` are Gmail-specific enough to flag on name alone.
"""


def trash_message(service, message_id):
    # Unambiguous Gmail verb -- flagged on name alone.
    service.users().messages().trash(userId="me", id=message_id).execute()


def untrash_message(service, message_id):
    # Unambiguous Gmail verb -- flagged on name alone.
    service.users().messages().untrash(userId="me", id=message_id).execute()


def create_draft(service, draft_body):
    # Ambiguous verb ("create") gated on the "drafts" surface handle.
    service.users().drafts().create(userId="me", body=draft_body).execute()


def modify_message_labels(service, message_id, body):
    # Ambiguous verb ("modify") gated on the "messages" surface handle.
    service.users().messages().modify(
        userId="me", id=message_id, body=body
    ).execute()


def send_message(service, body):
    # Ambiguous verb ("send") gated on the "messages" surface handle.
    service.users().messages().send(userId="me", body=body).execute()


def create_filter(service, filter_body):
    # Ambiguous verb ("create") gated on the "filters" surface handle.
    service.users().settings().filters().create(
        userId="me", body=filter_body
    ).execute()


def delete_filter(service, filter_id):
    # Ambiguous verb ("delete") gated on the "filters" surface handle.
    service.users().settings().filters().delete(
        userId="me", id=filter_id
    ).execute()


def trash_message_bound_and_called_later(service, message_id):
    # Bound-and-called-later shape: the mutation verb is loaded as an
    # attribute, not the immediate func of a Call. The rule fires on the
    # Attribute node, so this must still be flagged.
    fn = service.users().messages().trash
    return fn(userId="me", id=message_id)
